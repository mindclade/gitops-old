#!/usr/bin/env bash
# Copyright © 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary
#
# Render the monorepo's Kustomize sources into rendered/.
#
# CI calls this; so can you. Running it locally and getting an empty `git diff` is the same
# check validate.yml performs, which is what makes "rendered/ is generated" enforceable
# rather than a request in the README.
#
#   ./scripts/render.sh --monorepo ../../mindclade-github/mindclade-internal-monorepo
#   ./scripts/render.sh --monorepo <path> --check      # fail if output differs, write nothing
#   ./scripts/render.sh --monorepo <path> --env development
set -euo pipefail

DEFAULT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ROOT="${MINDCLADE_GITOPS_ROOT:-$DEFAULT_ROOT}"
ROOT="$(cd "$ROOT" && pwd)"
MANIFEST="$ROOT/render-manifest.yaml"

MONOREPO=""
ONLY_ENV=""
CHECK=0
SKIP_LOCK=0

while [ $# -gt 0 ]; do
  case "$1" in
    --monorepo) MONOREPO="$2"; shift 2 ;;
    --env)      ONLY_ENV="$2"; shift 2 ;;
    --check)    CHECK=1; shift ;;
    --skip-lock-verification) SKIP_LOCK=1; shift ;;
    -h|--help)  sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

if [ -z "$MONOREPO" ]; then
  echo "error: --monorepo <path> is required" >&2
  exit 2
fi
MONOREPO="$(cd "$MONOREPO" && pwd)"
if [ ! -d "$MONOREPO/infra" ]; then
  echo "error: $MONOREPO does not look like the monorepo (no infra/)" >&2
  exit 2
fi

command -v kustomize >/dev/null || { echo "error: kustomize not on PATH. Run: nix develop" >&2; exit 2; }
command -v yq >/dev/null       || { echo "error: yq not on PATH. Run: nix develop" >&2; exit 2; }

PINNED_REF=$(yq -r '.spec.source.ref' "$MANIFEST")

# ---------------------------------------------------------------------------------------
# Pinned ref
# ---------------------------------------------------------------------------------------
# The manifest pins a ref for the same reason Terraform modules pin a tag: otherwise a merge
# to the monorepo's main changes what the next render produces, with no diff in this repo.
# A warning rather than an error locally, because iterating against a working tree is the
# normal way to develop a change. CI passes --check, where the mismatch does fail.
# RESOLVED, not compared as a string.
#
# The manifest pins a semver tag now that the monorepo carries one, and `rev-parse HEAD`
# returns a SHA — so comparing the two literally never matched, and every render reported a
# mismatch. Under --check that is a hard failure on a correctly pinned tree; without it, a
# warning nobody can act on. Resolving the pin first makes a tag, a SHA, and a branch name all
# behave the same way.
ACTUAL_REF=$(git -C "$MONOREPO" rev-parse HEAD 2>/dev/null || echo "unknown")
RESOLVED_REF=$(git -C "$MONOREPO" rev-parse "${PINNED_REF}^{commit}" 2>/dev/null || echo "")
if [ -z "$RESOLVED_REF" ]; then
  echo "::error::the manifest pins '${PINNED_REF}', which does not resolve in $MONOREPO." >&2
  echo "  Fetch its tags — git -C $MONOREPO fetch --tags — or fix .spec.source.ref." >&2
  exit 1
fi

if [ "$ACTUAL_REF" != "$RESOLVED_REF" ]; then
  msg="monorepo is at ${ACTUAL_REF:0:12}, manifest pins ${PINNED_REF} (${RESOLVED_REF:0:12})"
  if [ "$CHECK" -eq 1 ]; then
    echo "::error::$msg — CI must render the pinned ref exactly" >&2
    exit 1
  fi
  echo "WARNING: $msg" >&2
fi

# ---------------------------------------------------------------------------------------
# Verify content locks before rendering anything
# ---------------------------------------------------------------------------------------
# A kustomization here fetches one base over the network. The commit SHA in that URL
# identifies a revision but does not bind the bytes, so the monorepo records a sha256 and a
# byte count alongside it. Re-check that here: rendering unverified remote content into
# manifests that ArgoCD applies to production is the supply-chain hole this closes.
verify_locks() {
  local n=0 lockfiles sources

  # Captured into a variable, NOT piped into `while read` via process substitution.
  # A failing command inside `< <(...)` does not fail the script even under `set -e`, so an
  # earlier version of this silently verified nothing and reported success. A verification
  # step that fails open is worse than no verification at all.
  if ! lockfiles=$(yq -r '.spec.lockfiles // [] | .[]' "$MANIFEST"); then
    echo "error: could not read .spec.lockfiles from $MANIFEST" >&2
    return 1
  fi
  if [ -z "$lockfiles" ]; then
    echo "error: no lockfiles declared. Remote bases would be fetched unverified." >&2
    return 1
  fi

  while IFS= read -r lockfile; do
    [ -z "$lockfile" ] && continue
    case "$lockfile" in
      /*|*\\*|../*|*/../*|*/..)
        echo "error: unsafe lockfile path: $lockfile" >&2
        return 1
        ;;
    esac
    local path="$MONOREPO/$lockfile"
    if [ ! -f "$path" ]; then
      echo "error: lockfile $lockfile not found in the monorepo" >&2
      return 1
    fi
    if ! sources=$(yq -r '.spec.sources[] | [.name, .url, .sha256, .bytes] | @tsv' "$path"); then
      echo "error: could not parse locked sources from $lockfile" >&2
      return 1
    fi
    while IFS=$'\t' read -r name url want_sha want_bytes; do
      [ -z "$url" ] && continue
      case "$url" in
        https://*) ;;
        *) echo "error: locked source URL must use HTTPS: $url" >&2; return 1 ;;
      esac
      local tmp; tmp=$(mktemp)
      if ! curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 "$url" -o "$tmp"; then
        echo "error: could not fetch $name from $url" >&2
        rm -f "$tmp"; return 1
      fi
      local got_sha got_bytes
      got_sha=$(shasum -a 256 "$tmp" | awk '{print $1}')
      got_bytes=$(wc -c < "$tmp" | tr -d ' ')
      rm -f "$tmp"

      if [ "$got_sha" != "$want_sha" ] || [ "$got_bytes" != "$want_bytes" ]; then
        echo "error: LOCK MISMATCH for $name" >&2
        echo "  url:      $url" >&2
        echo "  expected: sha256=$want_sha bytes=$want_bytes" >&2
        echo "  actual:   sha256=$got_sha bytes=$got_bytes" >&2
        echo "  The upstream content changed at a pinned revision. Do not render until this" >&2
        echo "  is explained — it is either a repository rewrite or a compromised mirror." >&2
        return 1
      fi
      echo "  lock ok: $name ($want_bytes bytes)"
      n=$((n + 1))
    done <<<"$sources"
  done <<<"$lockfiles"

  if [ "$n" -eq 0 ]; then
    echo "error: verified 0 sources but lockfiles were declared — refusing to render." >&2
    return 1
  fi
  echo "  verified $n locked source(s)"
}

if [ "$SKIP_LOCK" -eq 1 ] && [ "${CI:-}" = "true" ]; then
  echo "error: --skip-lock-verification is forbidden in CI" >&2
  exit 2
fi
if [ "$SKIP_LOCK" -eq 1 ]; then
  echo "Skipping lock verification (--skip-lock-verification). Never use this for a release render."
else
  echo "Verifying content locks..."
  verify_locks
fi

# ---------------------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------------------
STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT

targets=$(yq -o=json -I=0 '.spec.targets[]' "$MANIFEST")
total=0
empty=0

while IFS= read -r target; do
  [ -z "$target" ] && continue
  src=$(jq -r '.source' <<<"$target")
  out=$(jq -r '.out' <<<"$target")

  while IFS= read -r env; do
    [ -z "$env" ] && continue
    [ -n "$ONLY_ENV" ] && [ "$env" != "$ONLY_ENV" ] && continue

    # {env} lets one entry cover all three environment overlays.
    case "$env" in development|staging|production) ;; *) echo "error: invalid environment: $env" >&2; exit 1 ;; esac
    [[ "$out" =~ ^(platform|serving|research|data|partner)-[a-z0-9][a-z0-9-]*$ ]] || {
      echo "error: unsafe or unclaimed render output name: $out" >&2
      exit 1
    }
    resolved_src="${src//\{env\}/$env}"
    case "$resolved_src" in
      /*|*\\*|../*|*/../*|*/..)
        echo "error: render source escapes the monorepo: $resolved_src" >&2
        exit 1
        ;;
    esac
    src_path="$MONOREPO/$resolved_src"

    if [ ! -d "$src_path" ]; then
      echo "::error::$resolved_src does not exist in the monorepo" >&2
      exit 1
    fi

    # DISTINGUISH "rendered nothing" FROM "failed to render".
    #
    # This was `kustomize build ... 2>/dev/null || true`, which conflated them: a
    # kustomization with a syntax error, a missing base, or an unresolvable remote produced
    # empty output and was then reported as "skipped — source lists no resources". The
    # directory was dropped from rendered/, the next sync had Argo prune the application, and
    # the whole chain reported success.
    #
    # That is the same fail-open the lock verification above refuses to allow, and it is
    # worse here: verify_locks failing open means unverified content, this failing open means
    # a workload silently deleted from a cluster.
    build_err=$(mktemp)
    if ! body=$(kustomize build "$src_path" 2>"$build_err"); then
      echo "::error::kustomize build failed for ${resolved_src} (${env})" >&2
      sed 's/^/    /' "$build_err" >&2
      rm -f "$build_err"
      exit 1
    fi
    rm -f "$build_err"

    count=$(grep -c '^kind:' <<<"$body" || true)
    total=$((total + 1))

    # NO DIRECTORY when a source renders nothing.
    #
    # An empty directory still matches an ApplicationSet glob, so Argo creates an Application
    # for it — one that is vacuously "Synced/Healthy" and reconciles against nothing, forever.
    # Forty-nine of those is forty-nine real reconcile loops and forty-nine rows of noise
    # hiding the applications that matter.
    #
    # The render-manifest entry stays: it is the record of intent, and the moment the source
    # kustomization is wired the directory appears with content. Nothing here changes.
    if [ "$count" -eq 0 ]; then
      empty=$((empty + 1))
      printf '  %-12s %-46s %s\n' "$env" "$out" "skipped — source lists no resources"
      continue
    fi

    dest="$STAGE/$env/$out"
    mkdir -p "$dest"

    {
      echo "# GENERATED by scripts/render.sh — DO NOT EDIT."
      echo "# source: ${resolved_src}"
      echo "# ref:    ${PINNED_REF}"
      echo "# env:    ${env}"
      echo "---"
      printf '%s\n' "$body"
    } > "$dest/manifests.yaml"

    printf '  %-12s %-46s %s\n' "$env" "$out" "$count resources"
  done < <(jq -r '.environments[]' <<<"$target")
done <<<"$targets"

echo
echo "Rendered $total target(s); $empty skipped as unwired (no directory emitted)."

# ---------------------------------------------------------------------------------------
# Publish or compare
# ---------------------------------------------------------------------------------------
if [ "$CHECK" -eq 1 ]; then
  # mktemp, not a fixed /tmp path. Two renders running concurrently — a PR check and a
  # scheduled run on the same runner — would otherwise overwrite each other's diff and
  # report the wrong one.
  diff_out=$(mktemp)
  if diff -r "$STAGE" "$ROOT/rendered" >"$diff_out" 2>&1; then
    rm -f "$diff_out"
    echo "rendered/ matches a fresh render."
    exit 0
  fi
  echo "::error::rendered/ does not match a fresh render."
  echo "Either it was hand-edited, or the render is not deterministic. Both need fixing —"
  echo "the PR diff is only the cluster delta if this holds."
  head -60 "$diff_out"
  rm -f "$diff_out"
  exit 1
fi

# Replace the tree wholesale rather than copying over it, so a target removed from the
# manifest has its directory removed too. Without that, a deleted workload keeps a stale
# rendered directory that Argo happily goes on syncing.
rm -rf "$ROOT/rendered"
mkdir -p "$ROOT/rendered"
cp -R "$STAGE"/. "$ROOT/rendered"/

echo "Wrote $ROOT/rendered"
