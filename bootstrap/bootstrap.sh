#!/usr/bin/env bash
# Copyright © 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

set -euo pipefail
IFS=$'\n\t'
umask 077

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENVIRONMENT=""
PROFILE="standard"
EXPECTED_CONTEXT=""
APPLY=0

usage() {
  echo "usage: $0 --apply --environment <development|staging|production> [--profile <standard|ha>] --context <expected-kube-context>" >&2
  exit 2
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --apply) APPLY=1; shift ;;
    --environment) [[ $# -ge 2 ]] || usage; ENVIRONMENT="$2"; shift 2 ;;
    --profile) [[ $# -ge 2 ]] || usage; PROFILE="$2"; shift 2 ;;
    --context) [[ $# -ge 2 ]] || usage; EXPECTED_CONTEXT="$2"; shift 2 ;;
    -h|--help) usage ;;
    *) usage ;;
  esac
done

[[ "$APPLY" -eq 1 ]] || {
  echo "refusing to mutate a cluster without explicit --apply" >&2
  usage
}

case "$ENVIRONMENT" in development|staging|production) ;; *) usage ;; esac
case "$PROFILE" in
  standard) INSTALL=argocd-install.yaml ;;
  ha) INSTALL=argocd-install-ha.yaml ;;
  *) usage ;;
esac
[[ -n "$EXPECTED_CONTEXT" ]] || usage
declared_profile="$(awk '$1 == "path:" && $2 ~ /^bootstrap\/profiles\// {print $2}' \
  "$ROOT/applications/$ENVIRONMENT/argocd.yaml")"
if [[ "$declared_profile" != "bootstrap/profiles/$PROFILE" ]]; then
  echo "bootstrap profile '$PROFILE' disagrees with Git desired state '$declared_profile' for $ENVIRONMENT" >&2
  echo "change and qualify applications/$ENVIRONMENT/argocd.yaml before bootstrapping a different profile" >&2
  exit 2
fi
if [[ "$ENVIRONMENT" == production && "${MINDCLADE_PRODUCTION_BOOTSTRAP_CONFIRM:-}" != "production" ]]; then
  echo "set MINDCLADE_PRODUCTION_BOOTSTRAP_CONFIRM=production for a production bootstrap" >&2
  exit 2
fi

for command in kubectl envsubst awk mktemp stat sort wc; do
  command -v "$command" >/dev/null || { echo "required command is missing: $command" >&2; exit 2; }
done
if command -v sha256sum >/dev/null; then
  hash_file() { sha256sum "$1" | awk '{print $1}'; }
elif command -v shasum >/dev/null; then
  hash_file() { shasum -a 256 "$1" | awk '{print $1}'; }
else
  echo "sha256sum or shasum is required" >&2
  exit 2
fi

actual_context="$(kubectl config current-context)"
if [[ "$actual_context" != "$EXPECTED_CONTEXT" ]]; then
  echo "refusing to bootstrap the wrong cluster: expected context '$EXPECTED_CONTEXT', current context '$actual_context'" >&2
  exit 2
fi
kubectl cluster-info >/dev/null
kubectl auth can-i create namespaces | grep -qx yes || {
  echo "current identity cannot create namespaces" >&2
  exit 2
}

# HA is a capacity decision, not a label. The upstream HA profile expects enough independent
# scheduling failure domains to keep its replicated control-plane components available.
# Refuse an HA bootstrap when the cluster cannot actually provide that topology. A small
# startup production cluster may deliberately use the standard profile until capacity grows.
if [[ "$PROFILE" == ha ]]; then
  node_zones="$(kubectl get nodes -o jsonpath='{range .items[?(@.spec.unschedulable!=true)]}{.metadata.labels.topology\.kubernetes\.io/zone}{"\n"}{end}')"
  schedulable_nodes="$(printf '%s\n' "$node_zones" | awk 'NF' | wc -l | tr -d ' ')"
  failure_domains="$(printf '%s\n' "$node_zones" | awk 'NF' | sort -u | wc -l | tr -d ' ')"
  if (( schedulable_nodes < 3 || failure_domains < 3 )); then
    echo "refusing HA Argo CD bootstrap: need >=3 schedulable nodes across >=3 zones; found ${schedulable_nodes} node(s) across ${failure_domains} zone(s)" >&2
    exit 2
  fi
fi

required_files=(
  ARGOCD_DEX_GITHUB_CLIENT_ID_FILE
  ARGOCD_DEX_GITHUB_CLIENT_SECRET_FILE
  ARGOCD_GITHUB_APP_PRIVATE_KEY_FILE
  ARGOCD_GITHUB_APP_ID_FILE
  ARGOCD_GITHUB_APP_INSTALLATION_ID_FILE
)
for variable in "${required_files[@]}"; do
  file="${!variable:-}"
  [[ -n "$file" && -f "$file" && -r "$file" && -s "$file" ]] || {
    echo "$variable must name a non-empty readable credential file" >&2
    exit 2
  }
  mode="$(stat -c '%a' "$file" 2>/dev/null || stat -f '%Lp' "$file")"
  [[ "$mode" =~ ^(400|440|600|640)$ ]] || {
    echo "$file must have restrictive permissions (0400/0440/0600/0640), found $mode" >&2
    exit 2
  }
done

cd "$ROOT/bootstrap"
expected_hash="$(awk 'NF {print $1; exit}' "${INSTALL}.sha256")"
actual_hash="$(hash_file "$INSTALL")"
[[ "$expected_hash" =~ ^[0-9a-f]{64}$ ]] || { echo "invalid checksum file for $INSTALL" >&2; exit 1; }
[[ "$actual_hash" == "$expected_hash" ]] || {
  echo "checksum mismatch for vendored $INSTALL" >&2
  exit 1
}

kubectl create namespace argocd --dry-run=client -o yaml | kubectl apply -f -
kubectl label namespace argocd \
  app.kubernetes.io/managed-by=mindclade-gitops \
  mindclade.dev/environment="$ENVIRONMENT" \
  --overwrite
kubectl apply -n argocd --server-side --force-conflicts -f "$INSTALL"

for crd in applications.argoproj.io applicationsets.argoproj.io appprojects.argoproj.io; do
  kubectl wait --for=condition=Established "crd/${crd}" --timeout=5m
done

# Merge OAuth credentials into the upstream-created argocd-secret without placing values in
# Git, process arguments, or Terraform state.
kubectl create secret generic argocd-secret \
  -n argocd \
  --from-file=dex.github.clientID="$ARGOCD_DEX_GITHUB_CLIENT_ID_FILE" \
  --from-file=dex.github.clientSecret="$ARGOCD_DEX_GITHUB_CLIENT_SECRET_FILE" \
  --dry-run=client -o yaml \
  | kubectl apply --server-side --field-manager=mindclade-bootstrap-sso -f -

# Prefix credential template. AppProjects still restrict the only allowed source repository.
kubectl create secret generic mindclade-github-repo-creds \
  -n argocd \
  --from-literal=type=git \
  --from-literal=url=https://github.com/mindclade \
  --from-file=githubAppPrivateKey="$ARGOCD_GITHUB_APP_PRIVATE_KEY_FILE" \
  --from-file=githubAppID="$ARGOCD_GITHUB_APP_ID_FILE" \
  --from-file=githubAppInstallationID="$ARGOCD_GITHUB_APP_INSTALLATION_ID_FILE" \
  --dry-run=client -o yaml \
  | kubectl label --local -f - argocd.argoproj.io/secret-type=repo-creds -o yaml \
  | kubectl apply --server-side --field-manager=mindclade-bootstrap-repository -f -

kubectl apply --server-side -f bootstrap-project.yaml
kubectl apply --server-side -f "argocd-config-${ENVIRONMENT}.yaml"

# The upstream installation creates a one-time local-admin password Secret. Mindclade disables
# local admin in argocd-cm and uses governed SSO, so retaining that credential creates an unused
# recovery path. Cluster-admin recovery remains possible by rerunning this audited bootstrap.
kubectl delete secret -n argocd argocd-initial-admin-secret --ignore-not-found

root_manifest="$(mktemp)"
trap 'rm -f "$root_manifest"' EXIT
# These are intentionally literal template expressions consumed by envsubst and the
# unresolved-variable guard, not shell expansions.
# shellcheck disable=SC2016
MINDCLADE_ENVIRONMENT="$ENVIRONMENT" envsubst '${MINDCLADE_ENVIRONMENT}' < root-app.yaml > "$root_manifest"
# shellcheck disable=SC2016
if grep -q '\${' "$root_manifest"; then
  echo "unresolved template variable remains in root application" >&2
  exit 1
fi
kubectl apply --server-side -f "$root_manifest"

# Wait for the core reconciliation path rather than reporting success while Argo is still
# crash-looping. Components absent from a selected upstream profile are skipped explicitly.
for resource in \
  deployment/argocd-server \
  deployment/argocd-repo-server \
  deployment/argocd-dex-server \
  deployment/argocd-applicationset-controller \
  statefulset/argocd-application-controller; do
  if kubectl get -n argocd "$resource" >/dev/null 2>&1; then
    kubectl rollout status -n argocd "$resource" --timeout=10m
  fi
done

kubectl get -n argocd "application/root-${ENVIRONMENT}" >/dev/null
if kubectl get secret -n argocd argocd-initial-admin-secret >/dev/null 2>&1; then
  echo "initial Argo CD local-admin credential still exists after SSO bootstrap" >&2
  exit 1
fi
printf 'Argo CD bootstrap applied for %s (%s) to context %s.\n' "$ENVIRONMENT" "$PROFILE" "$actual_context"
