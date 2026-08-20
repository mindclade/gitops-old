#!/usr/bin/env python3
# Copyright © 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

from pathlib import Path
import datetime as dt
import hashlib
import re
import sys
import yaml

root = Path(__file__).resolve().parents[1]
errors = []
for n in ["argocd-install.yaml", "argocd-install-ha.yaml"]:
    p = root / "bootstrap" / n
    sp = root / "bootstrap" / (n + ".sha256")
    if not p.exists() or not sp.exists():
        errors.append(f"missing pinned Argo file: {n}")
        continue
    expected = sp.read_text().split()[0]
    actual = hashlib.sha256(p.read_bytes()).hexdigest()
    if expected != actual:
        errors.append(f"checksum mismatch: {n}")
version = root / "bootstrap/argocd-install.version"
if not version.is_file() or not re.fullmatch(
    r"v[0-9]+\.[0-9]+\.[0-9]+\n?", version.read_text()
):
    errors.append("missing or invalid pinned Argo CD version")
kubernetes_version = root / ".kubernetes-version"
if not kubernetes_version.is_file() or not re.fullmatch(
    r"1\.[0-9]+\.0\n?", kubernetes_version.read_text()
):
    errors.append("missing or invalid Kubernetes schema version")
if (root / "policy/sigstore").exists():
    errors.append(
        "duplicate Sigstore admission policy remains; Binary Authorization is authoritative"
    )
if list((root / "policy").rglob("*require-attestation*")):
    errors.append(
        "misleading require-attestation policy name remains; Gatekeeper owns structural image policy only"
    )
if (root / "CODEOWNERS").exists() or not (root / ".github/CODEOWNERS").exists():
    errors.append("CODEOWNERS must exist only at .github/CODEOWNERS")
for env in ["development", "staging", "production"]:
    if not (root / f"roots/{env}/kustomization.yaml").exists():
        errors.append(f"missing cluster composition: {env}")
    if not (root / f"applications/{env}/platform.yaml").exists():
        errors.append(f"missing applications: {env}")
    argocd_application = root / f"applications/{env}/argocd.yaml"
    if not argocd_application.exists():
        errors.append(f"missing Argo self-management application: {env}")
    else:
        try:
            application = yaml.safe_load(argocd_application.read_text()) or {}
            source = (application.get("spec") or {}).get("source") or {}
            if (application.get("spec") or {}).get(
                "project"
            ) != "argocd-administration":
                errors.append(f"Argo self-management uses wrong project: {env}")
            if source.get("path") not in {
                "bootstrap/profiles/standard",
                "bootstrap/profiles/ha",
            }:
                errors.append(f"Argo self-management uses unapproved profile: {env}")
        except Exception as e:
            errors.append(f"Argo self-management validation failed for {env}: {e}")
# Parse authored YAML; the two vendored upstream manifests are protected by checksums and huge.
for p in root.rglob("*.yaml"):
    if p.name.startswith("argocd-install") or "rendered" in p.parts:
        continue
    try:
        list(yaml.safe_load_all(p.read_text()))
    except Exception as e:
        errors.append(f"YAML parse {p.relative_to(root)}: {e}")

# A Constraint without its ConstraintTemplate is accepted by Git but rejected by the
# cluster, leaving the intended control absent. Prove the exact deployment bundle contains
# every active constraint and its matching template.
try:
    deploy_file = root / "policy/deploy/kustomization.yaml"
    deploy = yaml.safe_load(deploy_file.read_text()) or {}
    deployed_paths = set()
    for resource in deploy.get("resources") or []:
        path = (deploy_file.parent / resource).resolve()
        deployed_paths.add(path)
        if not path.is_file():
            errors.append(f"policy deployment references missing resource: {resource}")
    template_kinds = {}
    for path in deployed_paths:
        if not path.is_file():
            continue
        for document in yaml.safe_load_all(path.read_text()):
            if (
                not isinstance(document, dict)
                or document.get("kind") != "ConstraintTemplate"
            ):
                continue
            kind = (
                (((document.get("spec") or {}).get("crd") or {}).get("spec") or {}).get(
                    "names"
                )
                or {}
            ).get("kind")
            if not kind:
                errors.append(
                    f"ConstraintTemplate has no constraint kind: {path.relative_to(root)}"
                )
            elif kind in template_kinds:
                errors.append(f"duplicate deployed ConstraintTemplate kind: {kind}")
            else:
                template_kinds[kind] = path
    for path in (root / "policy/constraints").glob("*.yaml"):
        if path.resolve() not in deployed_paths:
            errors.append(f"constraint is not deployed: {path.relative_to(root)}")
        for document in yaml.safe_load_all(path.read_text()):
            if not isinstance(document, dict):
                continue
            kind = document.get("kind")
            if kind and kind not in template_kinds:
                errors.append(
                    f"constraint {path.relative_to(root)} has no deployed template for {kind}"
                )
except Exception as e:
    errors.append(f"policy deployment validation failed: {e}")

# Pod Security Admission is the baseline control for host namespaces, hostPath, privilege
# escalation, and non-root operation. Every GitOps-owned namespace must enforce the
# restricted profile; audit/warn alone is not a production boundary.
for path in (root / "rendered").rglob("*.yaml"):
    try:
        for document in yaml.safe_load_all(path.read_text()):
            if not isinstance(document, dict) or document.get("kind") != "Namespace":
                continue
            name = (document.get("metadata") or {}).get("name") or "<unnamed>"
            labels = (document.get("metadata") or {}).get("labels") or {}
            for mode in ["enforce", "audit", "warn"]:
                if labels.get(f"pod-security.kubernetes.io/{mode}") != "restricted":
                    errors.append(
                        f"Namespace {name} in {path.relative_to(root)} must set Pod Security {mode}=restricted"
                    )
                if not labels.get(f"pod-security.kubernetes.io/{mode}-version"):
                    errors.append(
                        f"Namespace {name} in {path.relative_to(root)} is missing Pod Security {mode}-version"
                    )
    except Exception as e:
        errors.append(
            f"rendered namespace validation failed for {path.relative_to(root)}: {e}"
        )
text = "\n".join(
    p.read_text(errors="ignore")
    for p in root.rglob("*")
    if p.is_file()
    and ".git" not in p.parts
    and "__pycache__" not in p.parts
    and p.suffix != ".pyc"
    and not p.name.startswith("argocd-install")
    and p.name not in {"BLUEPRINT.md", "validate-repository.py"}
)
for stale in [
    "mindclade-org",
    "infrastructure-live/5-workloads/<env>/argocd",
    "https://github.com/mindclade/mindclade\n",
    "repo: mindclade/mindclade\n",
    "require-cosign-signature",
    "applied once, by Terraform",
]:
    if stale in text:
        errors.append(f"stale ownership/reference: {stale}")

# Third-party evidence exceptions are exact immutable digests with explicit ownership and
# expiry. Prefix exceptions can silently authorize future, unreviewed bytes.
try:
    image_policy = yaml.safe_load((root / "image-policy.yaml").read_text()) or {}
    unsigned = (image_policy.get("spec") or {}).get("unsigned") or []
    if not isinstance(unsigned, list):
        errors.append("image-policy spec.unsigned must be a list")
        unsigned = []
    for index, exception in enumerate(unsigned):
        label = f"image-policy unsigned[{index}]"
        if not isinstance(exception, dict):
            errors.append(f"{label} must be an object")
            continue
        image = str(exception.get("image", ""))
        if not re.fullmatch(r"[^\s]+@sha256:[0-9a-f]{64}", image):
            errors.append(f"{label} must name one exact digest")
        for field in ["owner", "reason", "expires"]:
            if not str(exception.get(field, "")).strip():
                errors.append(f"{label} missing {field}")
        try:
            if (
                dt.date.fromisoformat(str(exception.get("expires", "")))
                < dt.date.today()
            ):
                errors.append(f"{label} is expired")
        except ValueError:
            errors.append(f"{label} expires must be an ISO date")
except Exception as e:
    errors.append(f"image-policy validation failed: {e}")

# GitHub and Argo freeze controls must move together. The impossible February-31 schedule is
# the explicit dormant state; a continuous cron activates the emergency deny window.
try:
    production = yaml.safe_load((root / "overlays/production.yaml").read_text()) or {}
    sync_patch = (root / "roots/production/sync-windows-patch.yaml").read_text()
    emergency_active = 'schedule: "* * * * *"' in sync_patch
    if bool(production.get("deployFreeze")) != emergency_active:
        errors.append("production deployFreeze and Argo emergency sync window disagree")
except Exception as e:
    errors.append(f"freeze-control validation failed: {e}")

# No cross-environment ApplicationSet matrices remain.
for p in (root / "applications").rglob("*.yaml"):
    env = p.parts[-2]
    t = p.read_text()
    for other in {"development", "staging", "production"} - {env}:
        if f"rendered/{other}/" in t:
            errors.append(f"{p.relative_to(root)} references {other}")
if errors:
    print("\n".join("ERROR: " + e for e in errors), file=sys.stderr)
    sys.exit(1)
print("gitops repository invariants passed")
