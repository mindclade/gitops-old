#!/usr/bin/env python3
# Copyright © 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

# MINDCLADE CONFIDENTIAL - PROPRIETARY AND TRADE SECRET
# Copyright (c) 2026 Mindclade. All rights reserved.
"""Validate the Mindclade GitOps production repository contract.

This validator intentionally uses only the Python standard library so the
repository's most important boundary checks run before cluster tooling exists.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "gitops"
CONTRACT = json.loads(
    '{"authority":["argocd-installation","argocd-configuration",'
    '"kubernetes-desired-state","promotion","admission-policy"],'
    '"forbidden_authority":["gcp-resource-provisioning","container-builds",'
    '"application-source","plaintext-secrets"],'
    '"forbidden_paths":[".terraform",".terragrunt-cache"],'
    '"repository_class":"production-control",'
    '"required_paths":[".kubernetes-version","bootstrap/argocd-install.yaml","bootstrap/argocd-install.provenance.json","bootstrap/components/immutable-images/kustomization.yaml","bootstrap/components/control-plane-baseline/kustomization.yaml","bootstrap/install-profiles/standard/kustomization.yaml","bootstrap/install-profiles/ha/kustomization.yaml","bootstrap/profiles/standard/kustomization.yaml",'
    '"bootstrap/profiles/ha/kustomization.yaml","bootstrap/root-app.yaml",'
    '"applications","deployments","projects","projects/argocd-administration.yaml","policy","overlays/production.yaml",'
    '"docs/disaster-recovery.md","docs/argocd-upgrade.md","docs/production-qualification.md","docs/failed-sync.md","docs/freeze-and-emergency.md","docs/rollback.md","vendor/arc/provenance.json"],'
    '"visibility":"internal"}'
)
ERRORS: list[str] = []


def error(message: str) -> None:
    ERRORS.append(message)


def repository_paths() -> list[Path]:
    """Return version-controlled paths in a checkout, or all paths in an exported tree."""
    if (ROOT / ".git").exists():
        result = subprocess.run(
            [
                "git",
                "-C",
                str(ROOT),
                "ls-files",
                "--cached",
                "--others",
                "--exclude-standard",
                "-z",
            ],
            check=True,
            capture_output=True,
        )
        return [
            ROOT / raw.decode("utf-8", errors="surrogateescape")
            for raw in result.stdout.split(b"\0")
            if raw
        ]
    return list(ROOT.rglob("*"))


TRACKED_PATHS = repository_paths()
TRACKED_RELATIVE = {path.relative_to(ROOT).as_posix() for path in TRACKED_PATHS}
LEGACY_GITHUB_IDENTITIES = (
    "Mind" + "clade/",
    "github.com/" + "Mind" + "clade",
    "/orgs/" + "Mind" + "clade",
)


def tracked_prefix_exists(relative: str) -> bool:
    prefix = relative.rstrip("/")
    return prefix in TRACKED_RELATIVE or any(
        path.startswith(prefix + "/") for path in TRACKED_RELATIVE
    )


def vendored_tree_sha256(root: Path) -> str:
    """Hash both relative names and bytes so file moves are provenance changes."""
    digest = hashlib.sha256()
    for path in sorted(candidate for candidate in root.rglob("*") if candidate.is_file()):
        data = path.read_bytes()
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(relative + b"\0")
        digest.update(str(len(data)).encode("ascii") + b"\0")
        digest.update(data + b"\0")
    return "sha256:" + digest.hexdigest()


try:
    arc_provenance = json.loads((ROOT / "vendor/arc/provenance.json").read_text())
    if arc_provenance.get("schema_version") != 1:
        error("unsupported ARC vendor provenance schema")
    artifacts = arc_provenance.get("artifacts")
    if not isinstance(artifacts, list):
        artifacts = []
        error("ARC vendor provenance artifacts must be a list")
    expected = {
        "gha-runner-scale-set": "vendor/arc/0.14.2/gha-runner-scale-set",
        "gha-runner-scale-set-controller": (
            "vendor/arc/0.14.2/gha-runner-scale-set-controller"
        ),
    }
    records = {
        str(record.get("name")): record
        for record in artifacts
        if isinstance(record, dict)
    }
    if set(records) != set(expected) or len(records) != len(artifacts):
        error("ARC vendor provenance must cover exactly both official charts")
    for name, vendored_path in expected.items():
        record = records.get(name, {})
        if record.get("version") != "0.14.2":
            error(f"ARC vendor provenance has an unexpected version: {name}")
        expected_reference = (
            "oci://ghcr.io/actions/actions-runner-controller-charts/"
            f"{name}:0.14.2"
        )
        if record.get("oci_reference") != expected_reference:
            error(f"ARC vendor provenance has an unexpected OCI reference: {name}")
        if record.get("vendored_path") != vendored_path:
            error(f"ARC vendor provenance has an unexpected local path: {name}")
        for digest_field in (
            "oci_manifest_digest",
            "archive_sha256",
            "vendored_tree_sha256",
        ):
            if not re.fullmatch(
                r"sha256:[0-9a-f]{64}", str(record.get(digest_field, ""))
            ):
                error(f"ARC vendor provenance has an invalid {digest_field}: {name}")
        chart_root = ROOT / vendored_path
        if not chart_root.is_dir():
            error(f"ARC vendored chart is missing: {vendored_path}")
        else:
            actual_tree_digest = vendored_tree_sha256(chart_root)
            if record.get("vendored_tree_sha256") != actual_tree_digest:
                error(
                    "ARC vendored chart tree digest mismatch: "
                    f"{name}: expected {record.get('vendored_tree_sha256')}, "
                    f"got {actual_tree_digest}"
                )
except (OSError, json.JSONDecodeError) as exception:
    error(f"ARC vendor provenance is unreadable: {exception}")


# These names are the GitHub Actions `runs-on` routing contract. A syntactically valid chart
# with a different scale-set name leaves a protected release job queued forever, so keep the
# three provisioned labels and their restricted enterprise runner group exact.
arc_scale_sets = {
    "canary.yaml": "mindclade-arc-canary",
    "build.yaml": "mindclade-arc-build-cpu",
    "qualify.yaml": "mindclade-arc-qualify-cpu",
}
for values_file, expected_name in arc_scale_sets.items():
    path = ROOT / "arc" / "values" / values_file
    try:
        values_text = path.read_text(encoding="utf-8")
    except OSError as exception:
        error(f"ARC scale-set values are unreadable: {values_file}: {exception}")
        continue
    for required_line in (
        "runnerGroup: mindclade-arc-artifact-authority",
        f"runnerScaleSetName: {expected_name}",
        "githubConfigSecret: arc-github-app",
    ):
        if required_line not in values_text:
            error(f"ARC scale-set contract drift in {values_file}: {required_line}")


repository_contract = (ROOT / "contracts/repository.yaml").read_text(
    "utf-8", errors="ignore"
)
for canonical_url in (
    "https://github.com/enterprises/mindclade",
    "https://github.com/mindclade",
    "https://github.com/orgs/mindclade/repositories",
    f"https://github.com/mindclade/{REPOSITORY}",
):
    if canonical_url not in repository_contract:
        error(f"repository contract omits canonical GitHub URL: {canonical_url}")


for path in TRACKED_PATHS:
    if not path.is_file() or path.stat().st_size > 2_000_000:
        continue
    text = path.read_text("utf-8", errors="ignore")
    if any(legacy in text for legacy in LEGACY_GITHUB_IDENTITIES):
        error(f"noncanonical GitHub organization identity in {path.relative_to(ROOT)}")


def workflow_uses(text: str) -> list[str]:
    values = re.findall(r"(?m)^\s*-?\s*uses:\s*([^#\s]+)", text)
    return [value.strip("\"'") for value in values]


def yaml_documents(text: str) -> list[str]:
    return re.split(r"(?m)^---\s*$", text)


def secret_document_has_payload(document: str) -> bool:
    if not re.search(r"(?m)^\s*kind:\s*Secret\s*$", document):
        return False
    lines = document.splitlines()
    for index, line in enumerate(lines):
        match = re.match(r"^(\s*)(data|stringData):\s*(.*?)\s*$", line)
        if not match:
            continue
        indent = len(match.group(1))
        inline = match.group(3).split("#", 1)[0].strip()
        if inline not in {"", "{}", "null", "~"}:
            return True
        for following in lines[index + 1 :]:
            stripped = following.strip()
            if not stripped or stripped.startswith("#"):
                continue
            child_indent = len(following) - len(following.lstrip())
            if child_indent <= indent:
                break
            return True
    return False


for rel in CONTRACT["required_paths"]:
    if not (ROOT / rel).exists():
        error(f"missing required path: {rel}")
for rel in CONTRACT["forbidden_paths"]:
    if tracked_prefix_exists(rel):
        error(f"forbidden tracked path present: {rel}")

for path in TRACKED_PATHS:
    relative = path.relative_to(ROOT)
    if any(
        part in {".terraform", ".terragrunt-cache", "__MACOSX", "__pycache__"}
        for part in relative.parts
    ):
        error(f"local/cache artifact is tracked: {relative}")
    if (
        path.name.startswith("._")
        or ".tfstate" in path.name
        or path.suffix in {".pyc", ".tfplan"}
    ):
        error(f"generated/sensitive artifact is tracked: {relative}")
    if path.is_symlink():
        error(f"symlink forbidden in delivery: {relative}")

workflow_root = ROOT / ".github/workflows"
for path in workflow_root.glob("*.y*ml") if workflow_root.exists() else []:
    text = path.read_text(encoding="utf-8", errors="ignore")
    for use in workflow_uses(text):
        if use.startswith("./"):
            continue
        immutable = (
            re.search(r"@[0-9a-f]{40}$", use)
            or re.search(r"@sha256:[0-9a-f]{64}$", use)
            or re.fullmatch(
                r"mindclade/\.github/\.github/workflows/[^@]+@v[0-9]+\.[0-9]+\.[0-9]+",
                use,
            )
        )
        if not immutable:
            error(
                f"workflow action is not immutable-pinned in {path.relative_to(ROOT)}: {use}"
            )
    if "permissions:" not in text:
        error(f"workflow lacks explicit permissions: {path.relative_to(ROOT)}")

render_workflow = (workflow_root / "render.yml").read_text(encoding="utf-8")
provenance_workflow = (workflow_root / "provenance.yml").read_text(encoding="utf-8")
validate_workflow = (workflow_root / "validate.yml").read_text(encoding="utf-8")
contract_workflow = (workflow_root / "production-contract.yml").read_text(
    encoding="utf-8"
)
release_validator = (ROOT / "scripts/validate-release-metadata.py").read_text(
    encoding="utf-8"
)
release_verifier = (ROOT / "scripts/verify-release-evidence.py").read_text(
    encoding="utf-8"
)
release_schema = (ROOT / "contracts/release-metadata.schema.json").read_text(
    encoding="utf-8"
)
for required in (
    "BINAUTHZ_DEPLOYMENT_ATTESTOR_PROJECT",
    "BINAUTHZ_DEPLOYMENT_ATTESTOR",
):
    if required not in provenance_workflow or required not in release_verifier:
        error(f"deployment trust root is not enforced end-to-end: {required}")
if "scripts/verify-release-evidence.py" not in provenance_workflow:
    error("provenance workflow does not delegate to the cryptographic release verifier")
if (
    "validate-deployment-selections.py" not in provenance_workflow
    or "--print-images" not in provenance_workflow
):
    error("provenance workflow does not enumerate images through trusted v2 release selections")
if ".spec.applications[]?.images" in provenance_workflow:
    error("provenance workflow still trusts the removed inline deployment image contract")
for required in (":validateAttestationOccurrence", 'value.get("result") == "VERIFIED"'):
    if required not in release_verifier:
        error(
            f"release verifier omits cryptographic attestation validation: {required}"
        )
for required in (
    "globalPolicyEvaluationMode",
    "ENFORCED_BLOCK_AND_AUDIT_LOG",
    "clusterAdmissionRules",
    "kubernetesNamespaceAdmissionRules",
    "admissionWhitelistPatterns",
):
    if required not in release_verifier:
        error(f"release verifier omits applied Binary Authorization policy check: {required}")
if "unsigned-exceptions-file" not in release_validator or "unsigned-exceptions.json" not in provenance_workflow:
    error("release metadata path does not consume governed control-plane exceptions")
for forbidden in (
    "BINAUTHZ_ATTESTOR_PROJECT",
    "BINAUTHZ_BUILD_ATTESTOR",
    "reusable-oci-build.yml",
    "gh attestation verify",
):
    if forbidden in provenance_workflow or forbidden in release_verifier:
        error(f"GitOps depends on the wrong artifact authority: {forbidden}")
for required in (
    '"const": "4.0.0"',
    '"attestations"',
    '"qualification_epoch"',
    '"previous_subject_digest"',
    "reusable-binauthz-sign.yml@refs/tags/v4.0.0",
):
    if required not in release_schema and required not in release_validator:
        error(f"release contract omits governed supply-chain binding: {required}")

for name, workflow in (
    ("render", render_workflow),
    ("provenance", provenance_workflow),
):
    if 'test "$GITHUB_REF" = refs/heads/main' not in workflow:
        error(f"{name} manual cloud path does not fail before auth off main")
if "merge_group:" not in validate_workflow or "merge_group:" not in contract_workflow:
    error("required GitOps checks do not run for merge-queue groups")
for context in (
    "lint",
    "schema",
    "policy",
    "exemptions",
    "promotion-integrity",
    "repository-invariants",
):
    if not re.search(
        rf"(?m)^  {re.escape(context)}:\n    name: {re.escape(context)}$",
        validate_workflow,
    ):
        error(
            f"required GitOps job does not emit its governed check context: {context}"
        )
if not re.search(r"(?m)^  contract:\n    name: contract$", contract_workflow):
    error("production-contract workflow does not emit the governed contract context")
if render_workflow.count('rm -f -- "$GOOGLE_GHA_CREDS_PATH"') < 2:
    error("render workflow retains GCP credentials while processing desired-state data")

secret_patterns = [
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"AIza[0-9A-Za-z_-]{35}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}"),
]
for path in TRACKED_PATHS:
    if not path.is_file() or path.stat().st_size > 2_000_000:
        continue
    relative = path.relative_to(ROOT)
    if relative.parts and relative.parts[0] == "vendor":
        continue
    text = path.read_text(encoding="utf-8", errors="ignore")
    for pattern in secret_patterns:
        if pattern.search(text):
            error(f"possible credential in {path.relative_to(ROOT)}")

for path in list((ROOT / "applications").rglob("*.yaml")) + list(
    (ROOT / "projects").rglob("*.yaml")
):
    text = path.read_text(encoding="utf-8", errors="ignore")
    if re.search(r"(?m)^\s*(?:sourceRepos|destinations):\s*\[?\s*[\"']?\*[\"']?", text):
        error(f"wildcard Argo authority in {path.relative_to(ROOT)}")


# The privileged renderer may only read the canonical monorepo at an immutable/protected ref.
render_manifest = ROOT / "render-manifest.yaml"
if render_manifest.exists():
    text = render_manifest.read_text(encoding="utf-8")
    repo_match = re.search(r"(?m)^\s*repo:\s*([^#\s]+)", text)
    ref_match = re.search(r"(?m)^\s*ref:\s*([^#\s]+)", text)
    repo = repo_match.group(1).strip("\"'") if repo_match else ""
    ref = ref_match.group(1).strip("\"'") if ref_match else ""
    if repo != "mindclade/mindclade-internal-monorepo":
        error(f"unauthorized render source repository: {repo or '<missing>'}")
    if not (
        re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", ref)
        or re.fullmatch(r"[0-9a-f]{40}", ref)
    ):
        error(
            f"render source ref is not a protected full semver tag or commit SHA: {ref or '<missing>'}"
        )

image_field = re.compile(r"^\s*(?:-\s*)?image:\s*[\"']?([^\"'\s#]+)")
new_tag_field = re.compile(r"^\s*newTag:\s*[\"']?([^\"'\s#]+)")
for path in ROOT.rglob("*.y*ml"):
    relative = path.relative_to(ROOT)
    if (
        "tests" in relative.parts
        or "testdata" in relative.parts
        or (relative.parts and relative.parts[0] == "vendor")
    ):
        continue
    text = path.read_text(encoding="utf-8", errors="ignore")
    for line_number, line in enumerate(text.splitlines(), start=1):
        image_match = image_field.match(line)
        tag_match = new_tag_field.match(line)
        if image_match:
            reference = image_match.group(1)
            if reference.endswith(":latest"):
                error(f"mutable image tag in {relative}:{line_number}")
            if (
                relative.parts[:2] == ("rendered", "production")
                and "@sha256:" not in reference
            ):
                error(
                    f"production image is not digest-pinned in {relative}:{line_number}"
                )
        elif tag_match and tag_match.group(1) == "latest":
            error(f"mutable Kustomize image tag in {relative}:{line_number}")
    for document in yaml_documents(text):
        if secret_document_has_payload(document):
            error(f"plaintext Kubernetes Secret payload in {relative}")
            break

if ERRORS:
    for message in sorted(set(ERRORS)):
        print(f"ERROR: {message}", file=sys.stderr)
    print(f"{len(set(ERRORS))} production contract violation(s)", file=sys.stderr)
    raise SystemExit(1)
print(f"{REPOSITORY}: production contract passed")
