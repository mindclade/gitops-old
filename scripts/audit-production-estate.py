#!/usr/bin/env python3
# Copyright © 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

"""Fail-closed source audit for the seven-repository Mindclade estate."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Iterable

REPOS = [
    ".github",
    ".github-private",
    "bootstrap",
    "github-config",
    "infrastructure-live",
    "gitops",
    "mindclade-internal-monorepo",
]
FORBIDDEN_PARTS = {
    ".terraform",
    ".terragrunt-cache",
    "__pycache__",
    "node_modules",
    ".venv",
    ".direnv",
    "__MACOSX",
}
FORBIDDEN_SUFFIXES = {".pyc", ".pyo", ".tfplan"}


def add(checks: list[dict[str, Any]], name: str, ok: bool, detail: str) -> None:
    checks.append({"name": name, "status": "pass" if ok else "fail", "detail": detail})


def find_repo_root(estate: Path, name: str) -> Path:
    candidate = estate / name
    if candidate.is_dir():
        return candidate
    raise FileNotFoundError(f"missing repository directory: {candidate}")


def tracked_files(root: Path) -> list[Path]:
    proc = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(detail or "git ls-files failed")
    return [Path(item.decode("utf-8")) for item in proc.stdout.split(b"\0") if item]


def is_forbidden(rel: Path) -> bool:
    return (
        any(part in FORBIDDEN_PARTS or part.startswith("._") for part in rel.parts)
        or rel.name == ".DS_Store"
        or rel.name.startswith("terraform.tfstate")
        or rel.suffix in FORBIDDEN_SUFFIXES
    )


def local_cache_diagnostics(root: Path) -> list[str]:
    findings: list[str] = []
    for current, directories, files in os.walk(root):
        here = Path(current)
        rel_here = here.relative_to(root)
        retained: list[str] = []
        for directory in directories:
            rel = rel_here / directory
            if directory == ".git":
                continue
            if directory in FORBIDDEN_PARTS or directory.startswith("._"):
                findings.append(rel.as_posix())
            else:
                retained.append(directory)
        directories[:] = retained
        for filename in files:
            rel = rel_here / filename
            if is_forbidden(rel):
                findings.append(rel.as_posix())
    return sorted(findings)


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def tracked_matching(files: Iterable[Path], suffixes: set[str]) -> Iterable[Path]:
    return (path for path in files if path.suffix in suffixes)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("estate_root", type=Path)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()
    estate = args.estate_root.resolve()
    checks: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []

    roots: dict[str, Path] = {}
    inventories: dict[str, list[Path]] = {}
    for repo in REPOS:
        try:
            roots[repo] = find_repo_root(estate, repo)
            add(checks, f"repo:{repo}", True, str(roots[repo]))
        except FileNotFoundError as exc:
            add(checks, f"repo:{repo}", False, str(exc))

    for repo, root in roots.items():
        try:
            inventories[repo] = tracked_files(root)
            add(checks, f"git-inventory:{repo}", True, f"{len(inventories[repo])} tracked paths")
        except RuntimeError as exc:
            inventories[repo] = []
            add(checks, f"git-inventory:{repo}", False, str(exc))
            continue

        contaminated = [path.as_posix() for path in inventories[repo] if is_forbidden(path)]
        add(
            checks,
            f"tracked-hygiene:{repo}",
            not contaminated,
            ", ".join(contaminated[:20]) or "tracked source clean",
        )
        caches = local_cache_diagnostics(root)
        diagnostics.append(
            {
                "name": f"local-caches:{repo}",
                "status": "info",
                "detail": ", ".join(caches[:20]) or "none observed",
                "count": len(caches),
            }
        )
        add(checks, f"codeowners:{repo}", (root / ".github" / "CODEOWNERS").is_file(), ".github/CODEOWNERS")
        add(checks, f"contract:{repo}", (root / "contracts" / "repository.yaml").is_file(), "contracts/repository.yaml")
        add(checks, f"agents:{repo}", (root / "AGENTS.md").is_file(), "AGENTS.md")
        if repo != ".github-private":
            blueprint = root / "BLUEPRINT.md"
            detail = "BLUEPRINT.md"
            if repo == "mindclade-internal-monorepo":
                blueprint = root / "docs" / "blueprint" / "production-monorepo-blueprint.md"
                detail = "docs/blueprint/production-monorepo-blueprint.md"
            add(checks, f"blueprint:{repo}", blueprint.is_file(), detail)

    if ".github" in roots:
        root = roots[".github"]
        add(
            checks,
            ".github:workflow-contracts",
            (root / "contracts" / "workflows").is_dir() and (root / "tools" / "check_workflow_contracts.py").is_file(),
            "shared workflow implementations and snapshots",
        )

    if ".github-private" in roots:
        root = roots[".github-private"]
        reusable = list((root / ".github" / "workflows").glob("reusable-*.y*ml"))
        add(checks, ".github-private:member-profile", (root / "profile" / "README.md").is_file(), "profile/README.md")
        add(checks, ".github-private:no-reusable-workflows", not reusable, ", ".join(map(str, reusable)) or "member navigation only")

    if "bootstrap" in roots:
        root = roots["bootstrap"]
        forbidden = [root / "modules" / "folders", root / "modules" / "governance"]
        add(checks, "bootstrap:ring0-scope", not any(path.exists() for path in forbidden), "normal folders/governance are excluded")
        for script in ("verify-no-local-state.sh", "verify-wif-policy.py", "validate-production-contract.py"):
            add(checks, f"bootstrap:script:{script}", (root / "scripts" / script).is_file(), script)

    if "github-config" in roots:
        root = roots["github-config"]
        required = [
            "repositories.yaml", "repository-classes.yaml", "teams.yaml", "access.yaml",
            "environments.yaml", "rulesets.yaml", "actions-policy.yaml", "oidc-policy.yaml",
            "custom-properties.yaml", "ci-variables.yaml",
        ]
        missing = [name for name in required if not (root / "catalog" / name).is_file()]
        add(checks, "github-config:catalog", not missing, ", ".join(missing) or "complete")

    if "infrastructure-live" in roots:
        root = roots["infrastructure-live"]
        missing_envs = [env for env in ("development", "staging", "production") if not (root / "5-workloads" / env).is_dir()]
        add(checks, "infrastructure-live:environment-parity", not missing_envs, ", ".join(missing_envs) or "complete")
        bad_argocd = [path for path in root.glob("5-workloads/*/argocd") if path.is_dir()]
        add(checks, "infrastructure-live:argocd-boundary", not bad_argocd, ", ".join(map(str, bad_argocd)) or "cloud prerequisites only")
        legacy = []
        for rel in tracked_matching(inventories.get("infrastructure-live", []), {".hcl", ".sh", ".yml", ".yaml"}):
            if "terragrunt run-all" in read_text(root / rel):
                legacy.append(rel.as_posix())
        add(checks, "infrastructure-live:modern-terragrunt", not legacy, ", ".join(legacy) or "terragrunt run --all")

    if "gitops" in roots:
        root = roots["gitops"]
        checksums = list((root / "bootstrap").glob("*.sha256")) if (root / "bootstrap").is_dir() else []
        add(checks, "gitops:argocd-checksums", bool(checksums), ", ".join(path.name for path in checksums) or "missing")
        candidates = list((root / "projects").glob("default-deny.y*ml")) if (root / "projects").is_dir() else []
        if not candidates:
            for candidate in (root / "projects").glob("*.y*ml") if (root / "projects").is_dir() else []:
                if re.search(r"(?m)^\s*name:\s*default\s*$", read_text(candidate)):
                    candidates.append(candidate)
        add(checks, "gitops:deny-default-project", bool(candidates), ", ".join(path.name for path in candidates) or "missing")
        secret_findings: list[str] = []
        mutable_images: list[str] = []
        for rel in tracked_matching(inventories.get("gitops", []), {".yml", ".yaml"}):
            if rel.parts[:1] == ("bootstrap",) and rel.name.startswith("argocd-install"):
                continue
            # Vendored Helm sources are integrity-pinned and validated by the owning GitOps
            # provenance/render gates. Templates and CRD descriptions are not deployed YAML and
            # produce false Secret/image matches when scanned as already-rendered manifests.
            if rel.parts[:1] == ("vendor",):
                continue
            body = read_text(root / rel)
            if re.search(r"(?m)^kind:\s*Secret\s*$", body) and re.search(r"(?m)^(data|stringData):\s*$", body):
                secret_findings.append(rel.as_posix())
            # Keep the match on one physical YAML line. ``\s`` also includes newlines, which
            # made an empty OpenAPI ``image:`` property consume the following ``description:``
            # key and report it as a mutable container reference.
            for match in re.finditer(r"(?m)^[ \t]*image:[ \t]*['\"]?([^\s'\"]+)", body):
                value = match.group(1)
                if "@sha256:" not in value and ":" in value and not any(part in rel.parts for part in ("fixtures", "tests")):
                    mutable_images.append(f"{rel}:{value}")
        add(checks, "gitops:no-plaintext-secrets", not secret_findings, ", ".join(secret_findings) or "clean")
        add(checks, "gitops:immutable-images", not mutable_images, ", ".join(mutable_images[:20]) or "digests only")

    if "mindclade-internal-monorepo" in roots:
        root = roots["mindclade-internal-monorepo"]
        required = [root / "components.toml", root / "maturity.toml", root / "infra" / "terraform" / "modules"]
        missing = [str(path.relative_to(root)) for path in required if not path.exists()]
        add(checks, "monorepo:source-and-modules", not missing, ", ".join(missing) or "complete")

    failed = [check for check in checks if check["status"] == "fail"]
    result = {
        "schema_version": 2,
        "status": "FAIL" if failed else "PASS",
        "estate_root": str(estate),
        "repositories": REPOS,
        "checks": checks,
        "diagnostics": diagnostics,
    }
    rendered = json.dumps(result, indent=2) + "\n"
    if args.json:
        args.json.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
