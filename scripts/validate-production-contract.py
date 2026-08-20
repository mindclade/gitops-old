#!/usr/bin/env python3
# Copyright © 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary
#
# MINDCLADE CONFIDENTIAL - PROPRIETARY AND TRADE SECRET
# Copyright (c) 2026 Mindclade. All rights reserved.
"""Validate the Mindclade GitOps production repository contract.

This validator intentionally uses only the Python standard library so the
repository's most important boundary checks run before cluster tooling exists.
"""
from __future__ import annotations

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
    '"required_paths":["bootstrap/argocd-install.yaml","bootstrap/argocd-install.provenance.json","bootstrap/root-app.yaml",'
    '"applications","projects","policy","overlays/production.yaml"],'
    '"visibility":"internal"}'
)
ERRORS: list[str] = []


def error(message: str) -> None:
    ERRORS.append(message)


def repository_paths() -> list[Path]:
    """Return version-controlled paths in a checkout, or all paths in an exported tree."""
    if (ROOT / ".git").exists():
        result = subprocess.run(
            ["git", "-C", str(ROOT), "ls-files", "-z"],
            check=True,
            capture_output=True,
        )
        return [ROOT / raw.decode("utf-8", errors="surrogateescape") for raw in result.stdout.split(b"\0") if raw]
    return list(ROOT.rglob("*"))


TRACKED_PATHS = repository_paths()
TRACKED_RELATIVE = {path.relative_to(ROOT).as_posix() for path in TRACKED_PATHS}


def tracked_prefix_exists(relative: str) -> bool:
    prefix = relative.rstrip("/")
    return prefix in TRACKED_RELATIVE or any(path.startswith(prefix + "/") for path in TRACKED_RELATIVE)


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
    if path.name.startswith("._") or ".tfstate" in path.name or path.suffix in {".pyc", ".tfplan"}:
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
            or re.fullmatch(r"Mindclade/\.github/\.github/workflows/[^@]+@v[0-9]+\.[0-9]+\.[0-9]+", use)
        )
        if not immutable:
            error(f"workflow action is not immutable-pinned in {path.relative_to(ROOT)}: {use}")
    if "permissions:" not in text:
        error(f"workflow lacks explicit permissions: {path.relative_to(ROOT)}")

secret_patterns = [
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"AIza[0-9A-Za-z_-]{35}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}"),
]
for path in TRACKED_PATHS:
    if not path.is_file() or path.stat().st_size > 2_000_000:
        continue
    text = path.read_text(encoding="utf-8", errors="ignore")
    for pattern in secret_patterns:
        if pattern.search(text):
            error(f"possible credential in {path.relative_to(ROOT)}")

for path in list((ROOT / "applications").glob("*.yaml")) + list((ROOT / "projects").glob("*.yaml")):
    text = path.read_text(encoding="utf-8", errors="ignore")
    if re.search(r"(?m)^\s*(?:sourceRepos|destinations):\s*\[?\s*[\"']?\*[\"']?", text):
        error(f"wildcard Argo authority in {path.relative_to(ROOT)}")


# The privileged renderer may only read the canonical monorepo at an immutable/protected ref.
render_manifest = ROOT / "render-manifest.yaml"
if render_manifest.exists():
    text = render_manifest.read_text(encoding="utf-8")
    repo_match = re.search(r"(?m)^\s*repo:\s*([^#\s]+)", text)
    ref_match = re.search(r"(?m)^\s*ref:\s*([^#\s]+)", text)
    repo = repo_match.group(1).strip('"\'') if repo_match else ""
    ref = ref_match.group(1).strip('"\'') if ref_match else ""
    if repo != "Mindclade/mindclade-internal-monorepo":
        error(f"unauthorized render source repository: {repo or '<missing>'}")
    if not (re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", ref) or re.fullmatch(r"[0-9a-f]{40}", ref)):
        error(f"render source ref is not a protected full semver tag or commit SHA: {ref or '<missing>'}")

image_field = re.compile(r"^\s*(?:-\s*)?image:\s*[\"']?([^\"'\s#]+)")
new_tag_field = re.compile(r"^\s*newTag:\s*[\"']?([^\"'\s#]+)")
for path in ROOT.rglob("*.y*ml"):
    relative = path.relative_to(ROOT)
    if "tests" in relative.parts or "testdata" in relative.parts:
        continue
    text = path.read_text(encoding="utf-8", errors="ignore")
    for line_number, line in enumerate(text.splitlines(), start=1):
        image_match = image_field.match(line)
        tag_match = new_tag_field.match(line)
        if image_match:
            reference = image_match.group(1)
            if reference.endswith(":latest"):
                error(f"mutable image tag in {relative}:{line_number}")
            if relative.parts[:2] == ("rendered", "production") and "@sha256:" not in reference:
                error(f"production image is not digest-pinned in {relative}:{line_number}")
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
