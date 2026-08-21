#!/usr/bin/env python3
# Copyright © 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

"""Verify or explicitly update deterministic GitOps renders from a pinned monorepo."""

from __future__ import annotations

import argparse
import filecmp
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


SCRIPT_ROOT = Path(__file__).resolve().parent.parent
ROOT = Path(os.environ.get("MINDCLADE_GITOPS_ROOT", SCRIPT_ROOT)).resolve()
MANIFEST = ROOT / "render-manifest.yaml"
ENVIRONMENTS = {"development", "staging", "production"}
DNS_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
RENDERERS = {"helm", "kustomize"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--monorepo", type=Path, required=True)
    parser.add_argument("--env", dest="environment", choices=sorted(ENVIRONMENTS))
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--write", action="store_true", help="atomically update rendered output"
    )
    mode.add_argument(
        "--check", action="store_true", help="deprecated; check is the default"
    )
    parser.add_argument("--skip-lock-verification", action="store_true")
    return parser.parse_args()


def json_command(arguments: list[str], *, cwd: Path | None = None) -> Any:
    result = subprocess.run(
        arguments, cwd=cwd, check=True, text=True, capture_output=True
    )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise ValueError(
            f"{' '.join(arguments)} returned invalid JSON: {error}"
        ) from error


def load_yaml(path: Path) -> dict[str, Any]:
    value = json_command(["yq", "-o=json", ".", str(path)])
    if not isinstance(value, dict):
        raise ValueError(f"expected a YAML object: {path}")
    return value


def git_revision(repo: Path, revision: str) -> str:
    return subprocess.run(
        ["git", "rev-parse", f"{revision}^{{commit}}"],
        cwd=repo,
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()


def verify_source_lock(monorepo: Path, manifest: dict[str, Any], skip: bool) -> None:
    if skip:
        if os.environ.get("CI") == "true":
            raise ValueError("--skip-lock-verification is forbidden in CI")
        print("Skipping lock verification. Never use this for a release render.")
        return
    lockfiles = manifest.get("spec", {}).get("lockfiles") or []
    if not isinstance(lockfiles, list) or not lockfiles:
        raise ValueError("no lockfiles declared; refusing unverified remote bases")
    verified = 0
    for relative in lockfiles:
        path = safe_child(monorepo, str(relative), "lockfile")
        if not path.is_file():
            raise ValueError(f"lockfile not found: {relative}")
        lock = load_yaml(path)
        sources = lock.get("spec", {}).get("sources") or []
        if not sources:
            raise ValueError(f"lockfile contains no sources: {relative}")
        for source in sources:
            url = str(source.get("url", ""))
            if not url.startswith("https://"):
                raise ValueError(f"locked source URL must use HTTPS: {url}")
            with tempfile.NamedTemporaryFile() as stream:
                subprocess.run(
                    [
                        "curl",
                        "--fail",
                        "--silent",
                        "--show-error",
                        "--location",
                        "--proto",
                        "=https",
                        "--tlsv1.2",
                        url,
                        "--output",
                        stream.name,
                    ],
                    check=True,
                )
                data = Path(stream.name).read_bytes()
            digest = hashlib.sha256(data).hexdigest()
            expected_digest = str(source.get("sha256", ""))
            expected_bytes = int(source.get("bytes", -1))
            if digest != expected_digest or len(data) != expected_bytes:
                raise ValueError(
                    f"lock mismatch for {source.get('name', url)}: expected "
                    f"sha256={expected_digest} bytes={expected_bytes}, got "
                    f"sha256={digest} bytes={len(data)}"
                )
            print(f"  lock ok: {source.get('name', url)} ({len(data)} bytes)")
            verified += 1
    if verified == 0:
        raise ValueError("verified zero locked sources")


def safe_child(root: Path, relative: str, label: str) -> Path:
    candidate = Path(relative)
    if candidate.is_absolute() or ".." in candidate.parts or "\\" in relative:
        raise ValueError(f"unsafe {label} path: {relative}")
    resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as error:
        raise ValueError(f"{label} escapes its root: {relative}") from error
    return resolved


def apply_artifact_selection(body: str, environment: str, application: str) -> str:
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_ROOT / "scripts/apply-artifact-selection.py"),
            "--selection",
            str(ROOT / "deployments" / f"{environment}.yaml"),
            "--application",
            application,
        ],
        input=body,
        text=True,
        check=True,
        capture_output=True,
    )
    return result.stdout


def render_source(
    target: dict[str, Any], monorepo: Path, environment: str, application: str
) -> tuple[str, list[str]]:
    """Render one local source without network access and return provenance headers."""

    source = str(target.get("source", ""))
    resolved_source = source.replace("{env}", environment)
    source_path = safe_child(monorepo, resolved_source, "render source")
    if not source_path.is_dir():
        raise ValueError(f"render source does not exist: {resolved_source}")

    renderer = str(target.get("renderer", "kustomize"))
    if renderer not in RENDERERS:
        raise ValueError(f"unsupported renderer for {application}: {renderer}")
    provenance = [f"# source: {resolved_source}", f"# render: {renderer}"]

    if renderer == "kustomize":
        unexpected = sorted(
            field for field in ("values", "release", "namespace") if field in target
        )
        if unexpected:
            raise ValueError(
                f"Kustomize target {application} has Helm-only fields: {', '.join(unexpected)}"
            )
        command = ["kustomize", "build", str(source_path)]
    else:
        if not (source_path / "Chart.yaml").is_file():
            raise ValueError(f"Helm render source has no Chart.yaml: {resolved_source}")
        crd_directory = source_path / "crds"
        if crd_directory.is_dir() and any(crd_directory.rglob("*.yaml")):
            raise ValueError(
                f"workload Helm target {application} may not install CRDs incidentally"
            )
        release = str(target.get("release", ""))
        namespace = str(target.get("namespace", ""))
        if not DNS_LABEL.fullmatch(release):
            raise ValueError(f"invalid Helm release for {application}: {release}")
        if not DNS_LABEL.fullmatch(namespace):
            raise ValueError(f"invalid Helm namespace for {application}: {namespace}")
        if namespace != application:
            raise ValueError(
                f"Helm namespace {namespace} must equal GitOps application {application}"
            )
        values = str(target.get("values", "")).replace("{env}", environment)
        values_path = safe_child(monorepo, values, "Helm values")
        if not values_path.is_file():
            raise ValueError(f"Helm values file does not exist: {values}")
        command = [
            "helm",
            "template",
            release,
            str(source_path),
            "--namespace",
            namespace,
            "--values",
            str(values_path),
            "--skip-tests",
        ]
        provenance.extend(
            (
                f"# values: {values}",
                f"# release: {release}",
                f"# namespace: {namespace}",
            )
        )

    result = subprocess.run(command, check=True, text=True, capture_output=True)
    return result.stdout, provenance


def render(
    manifest: dict[str, Any], monorepo: Path, destination: Path, pinned_ref: str
) -> None:
    targets = manifest.get("spec", {}).get("targets") or []
    total = 0
    empty = 0
    for target in targets:
        application = str(target.get("out", ""))
        if not application or not any(
            application.startswith(f"{prefix}-")
            for prefix in ("platform", "serving", "research", "data", "partner")
        ):
            raise ValueError(f"unsafe or unclaimed render output name: {application}")
        for environment in target.get("environments") or []:
            if environment not in ENVIRONMENTS:
                raise ValueError(f"invalid environment: {environment}")
            rendered, provenance = render_source(
                target, monorepo, environment, application
            )
            body = apply_artifact_selection(rendered, environment, application)
            count = sum(1 for line in body.splitlines() if line.startswith("kind:"))
            total += 1
            if count == 0:
                empty += 1
                print(
                    f"  {environment:12} {application:46} skipped — source lists no resources"
                )
                continue
            target_directory = destination / environment / application
            target_directory.mkdir(parents=True, exist_ok=True)
            provenance_text = "\n".join(provenance)
            content = (
                "# GENERATED by scripts/render.py — DO NOT EDIT.\n"
                f"{provenance_text}\n"
                f"# ref:    {pinned_ref}\n"
                f"# env:    {environment}\n"
                "---\n"
                f"{body.rstrip()}\n"
            )
            (target_directory / "manifests.yaml").write_text(content, encoding="utf-8")
            print(f"  {environment:12} {application:46} {count} resources")
    print(f"\nRendered {total} target(s); {empty} skipped as unwired.")


def trees_equal(left: Path, right: Path) -> bool:
    if not left.is_dir() or not right.is_dir():
        return False
    comparison = filecmp.dircmp(left, right)
    if comparison.left_only or comparison.right_only or comparison.funny_files:
        return False
    if any(
        not filecmp.cmp(left / name, right / name, shallow=False)
        for name in comparison.common_files
    ):
        return False
    return all(
        trees_equal(left / name, right / name) for name in comparison.common_dirs
    )


def selected_path(root: Path, environment: str | None) -> Path:
    return root / environment if environment else root


def publish(staging: Path, destination: Path, environment: str | None) -> None:
    if environment:
        source = staging / environment
        target = destination / environment
        backup = destination / f".{environment}.previous"
        destination.mkdir(parents=True, exist_ok=True)
    else:
        source = staging
        target = destination
        backup = destination.with_name(f".{destination.name}.previous")
    if backup.exists():
        shutil.rmtree(backup)
    try:
        if target.exists():
            target.replace(backup)
        source.replace(target)
    except Exception:
        if not target.exists() and backup.exists():
            backup.replace(target)
        raise
    if backup.exists():
        shutil.rmtree(backup)


def main() -> int:
    args = parse_args()
    monorepo = args.monorepo.resolve()
    if not (monorepo / "infra").is_dir():
        print(
            f"error: {monorepo} does not look like the monorepo (no infra/)",
            file=sys.stderr,
        )
        return 2
    staging = Path(tempfile.mkdtemp(prefix=".rendered.", dir=ROOT))
    try:
        manifest = load_yaml(MANIFEST)
        pinned_ref = str(manifest.get("spec", {}).get("source", {}).get("ref", ""))
        if not pinned_ref:
            raise ValueError("render manifest has no pinned source ref")
        actual = git_revision(monorepo, "HEAD")
        resolved = git_revision(monorepo, pinned_ref)
        if actual != resolved:
            message = f"monorepo is at {actual[:12]}, manifest pins {pinned_ref} ({resolved[:12]})"
            if not args.write:
                raise ValueError(
                    f"{message}; checks must render the pinned ref exactly"
                )
            print(f"WARNING: {message}", file=sys.stderr)
        verify_source_lock(monorepo, manifest, args.skip_lock_verification)
        render(manifest, monorepo, staging, pinned_ref)
        generated = selected_path(staging, args.environment)
        committed = selected_path(ROOT / "rendered", args.environment)
        if args.write:
            publish(staging, ROOT / "rendered", args.environment)
            print(f"Wrote {committed}")
        elif not trees_equal(generated, committed):
            subprocess.run(["diff", "-r", str(generated), str(committed)], check=False)
            print(
                "::error::rendered output does not match a fresh render",
                file=sys.stderr,
            )
            return 1
        else:
            print("rendered output matches a fresh render.")
        return 0
    except (
        FileNotFoundError,
        json.JSONDecodeError,
        OSError,
        subprocess.CalledProcessError,
        ValueError,
    ) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    finally:
        if staging.exists():
            shutil.rmtree(staging)


if __name__ == "__main__":
    raise SystemExit(main())
