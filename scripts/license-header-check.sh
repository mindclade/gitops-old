#!/usr/bin/env bash
# Copyright © 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Prefer repository-local header so copied repos remain self-contained,
# and fall back to the workspace canonical header for local tooling runs.
if [[ -f "${REPO_ROOT}/license-header.txt" ]]; then
  HEADER_FILE="${REPO_ROOT}/license-header.txt"
else
  HEADER_FILE="${SCRIPT_DIR}/license-header.txt"
fi

normalize_line() {
  printf '%s' "$1" | tr -d '\r' | sed $'s/\xEF\xBB\xBF//' 
}

if [[ ! -f "${HEADER_FILE}" ]]; then
  echo "Missing license header file: ${HEADER_FILE}" >&2
  exit 1
fi

HEADER_LINES=()
while IFS= read -r header_line; do
  HEADER_LINES+=("${header_line}")
done < <(sed -n '1,4p' "${HEADER_FILE}")

if [[ "${#HEADER_LINES[@]}" -lt 4 ]]; then
  echo "license header file does not contain the expected 4-line header block: ${HEADER_FILE}" >&2
  exit 1
fi

for i in "${!HEADER_LINES[@]}"; do
  HEADER_LINES[$i]="$(normalize_line "${HEADER_LINES[$i]}")"
 done

if [[ -z "${HEADER_LINES[0]}" || -z "${HEADER_LINES[1]}" || -z "${HEADER_LINES[2]}" || -z "${HEADER_LINES[3]}" ]]; then
  echo "Invalid proprietary header block in ${HEADER_FILE}." >&2
  exit 1
fi

usage() {
  cat <<'USAGE'
Usage:
  scripts/license-header-check.sh [--check|--fix] [files...]

Modes:
  --check  Validate proprietary headers (default).
  --fix    Add or normalize proprietary headers on target files.

Checks files matching supported extensions under the repository,
excluding generated/lock locations:
  - rendered/
  - policy/templates/vendor/
  - bootstrap/argocd-install*.yaml (vendored upstream)
  - .terraform/
  - .terragrunt-cache/
  - *.lock.hcl
  - .terraform.lock.hcl
USAGE
}

CHECK_MODE="check"
files=()
while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --help|-h)
      usage
      exit 0
      ;;
    --check)
      CHECK_MODE="check"
      shift
      ;;
    --fix)
      CHECK_MODE="fix"
      shift
      ;;
    --)
      shift
      files+=("$@")
      break
      ;;
    --*)
      echo "Unknown option: $1" >&2
      usage
      exit 1
      ;;
    *)
      files+=("$1")
      shift
      ;;
  esac
done

is_target_file() {
  local f="$1"

  case "$f" in
    */.terraform/*|*/.terragrunt-cache/*|*/rendered/*|*/policy/templates/vendor/*|*/bootstrap/argocd-install.yaml|*/bootstrap/argocd-install-ha.yaml)
      return 1
      ;;
    */.terraform.lock.hcl|*.lock.hcl)
      return 1
      ;;
  esac

  local base="${f##*/}"
  case "$base" in
    *.tf|*.hcl|*.yml|*.yaml|*.sh|*.nix|*.example|CODEOWNERS)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

line_in_file() {
  local file="$1"
  local line_no="$2"
  sed -n "${line_no}p" "${file}" | tr -d '\r'
}

has_license_header() {
  local f="$1"
  local line0
  local line1
  local line2
  local line3
  local line4

  line0="$(line_in_file "${f}" 1)"
  # A shebang and a YAML document start are both valid only as the literal first line of a
  # file, so either may legitimately precede the header block. Accepting only the shebang is
  # why every .pre-commit-config.yaml in the estate — which opens with `---`, as yamllint's
  # document-start rule encourages — failed this check while carrying a correct header.
  if [[ "${line0}" == "#!"* || "${line0}" == "---" ]]; then
    line1="$(line_in_file "${f}" 2)"
    line2="$(line_in_file "${f}" 3)"
    line3="$(line_in_file "${f}" 4)"
    line4="$(line_in_file "${f}" 5)"

    [[ "${line1}" == "${HEADER_LINES[0]}" \
      && "${line2}" == "${HEADER_LINES[1]}" \
      && "${line3}" == "${HEADER_LINES[2]}" \
      && "${line4}" == "${HEADER_LINES[3]}" ]]
    return
  fi

  line1="$(line_in_file "${f}" 2)"
  line2="$(line_in_file "${f}" 3)"
  line3="$(line_in_file "${f}" 4)"

  [[ "${line0}" == "${HEADER_LINES[0]}" \
    && "${line1}" == "${HEADER_LINES[1]}" \
    && "${line2}" == "${HEADER_LINES[2]}" \
    && "${line3}" == "${HEADER_LINES[3]}" ]]
}

is_mindclade_license_like() {
  local f="$1"
  local candidate="$2"

  [[ "${candidate}" == "# Copyright "*"Mindclade, LLC. All Rights Reserved."* ]]
}

add_license_header() {
  local f="$1"
  local first_line
  local start_from=1
  local tmp

  first_line="$(line_in_file "${f}" 1)"
  tmp="$(mktemp)"

  if [[ "${first_line}" == "#!"* ]]; then
    printf '%s
' "${first_line}" > "${tmp}"

    local second_line
    second_line="$(line_in_file "${f}" 2)"
    start_from=2
    if is_mindclade_license_like "${f}" "${second_line}"; then
      start_from=6
    fi

    printf '%s
' "${HEADER_LINES[0]}" >> "${tmp}"
    printf '%s
' "${HEADER_LINES[1]}" >> "${tmp}"
    printf '%s
' "${HEADER_LINES[2]}" >> "${tmp}"
    printf '%s
' "${HEADER_LINES[3]}" >> "${tmp}"
    tail -n "+${start_from}" "${f}" >> "${tmp}"
  else
    if is_mindclade_license_like "${f}" "${first_line}"; then
      start_from=5
    fi

    printf '%s
' "${HEADER_LINES[0]}" > "${tmp}"
    printf '%s
' "${HEADER_LINES[1]}" >> "${tmp}"
    printf '%s
' "${HEADER_LINES[2]}" >> "${tmp}"
    printf '%s
' "${HEADER_LINES[3]}" >> "${tmp}"
    tail -n "+${start_from}" "${f}" >> "${tmp}"
  fi

  mv "${tmp}" "${f}"
}

if [[ "${#files[@]}" -eq 0 ]]; then
  while IFS= read -r -d '' file; do
    files+=("${file}")
  done < <(rg --files -0 \
    -g '**/*.tf' -g '**/*.hcl' -g '**/*.yml' -g '**/*.yaml' -g '**/*.sh' -g '**/*.nix' -g '**/*.example' -g '**/CODEOWNERS' \
    -g '!**/.terraform/**' -g '!**/.terragrunt-cache/**' -g '!**/rendered/**' -g '!**/policy/templates/vendor/**' \
    -g '!**/bootstrap/argocd-install.yaml' -g '!**/bootstrap/argocd-install-ha.yaml' -g '!**/*.lock.hcl' \
    "${REPO_ROOT}")
fi

failed=0
fixed=0
for file in "${files[@]}"; do
  [[ -e "${file}" ]] || continue

  if ! is_target_file "${file}"; then
    continue
  fi

  if has_license_header "${file}"; then
    continue
  fi

  case "${CHECK_MODE}" in
    check)
      echo "Missing or malformed proprietary header: ${file}" >&2
      failed=1
      ;;
    fix)
      add_license_header "${file}"
      echo "Fixed proprietary header: ${file}"
      fixed=$((fixed + 1))
      ;;
    *)
      echo "Unknown mode: ${CHECK_MODE}" >&2
      exit 1
      ;;
  esac

done

if [[ "${CHECK_MODE}" == "check" && "${failed}" -eq 1 ]]; then
  echo "License header check failed." >&2
  echo "Expected header block (from ${HEADER_FILE}):" >&2
  sed -n '1,4p' "${HEADER_FILE}" >&2
  exit 1
fi

if [[ "${CHECK_MODE}" == "fix" ]]; then
  echo "Fixed proprietary headers in ${fixed} file(s)."
fi
