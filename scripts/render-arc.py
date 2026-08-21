#!/usr/bin/env python3
# Copyright © 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

"""Verify the vendored ARC release and reproduce its committed manifests offline."""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterator

import yaml


ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "vendor/arc/0.14.2"
PROVENANCE = ROOT / "vendor/arc/provenance.yaml"
EXPECTED_RELEASES = {
    "controller": (
        "arc-controller",
        "arc-systems",
        "gha-runner-scale-set-controller",
        "controller.yaml",
    ),
    "canary": ("arc-canary", "arc-canary", "gha-runner-scale-set", "canary.yaml"),
    "build": ("arc-build", "arc-build", "gha-runner-scale-set", "build.yaml"),
    "qualify": (
        "arc-qualify",
        "arc-qualify",
        "gha-runner-scale-set",
        "qualify.yaml",
    ),
}


def expanded_tree_sha256() -> str:
    lines: list[str] = []
    files = [item for item in VENDOR.rglob("*") if item.is_file()]
    for path in sorted(files, key=lambda item: item.relative_to(ROOT).as_posix()):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        lines.append(f"{digest}  {path.relative_to(ROOT).as_posix()}\n")
    return hashlib.sha256("".join(lines).encode()).hexdigest()


def image_values(value: Any) -> Iterator[str]:
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "image" and isinstance(child, str) and child:
                yield child
            yield from image_values(child)
    elif isinstance(value, list):
        for child in value:
            yield from image_values(child)


def render(name: str) -> bytes:
    release, namespace, chart, output = EXPECTED_RELEASES[name]
    command = [
        "helm",
        "template",
        release,
        str(VENDOR / chart),
        "--namespace",
        namespace,
        "--values",
        str(ROOT / f"arc/values/{name}.yaml"),
    ]
    if name == "controller":
        command.append("--include-crds")
    result = subprocess.run(command, cwd=ROOT, check=True, capture_output=True)
    if not result.stdout:
        raise ValueError(f"ARC render is empty: {output}")
    # Helm emits an extra terminal blank line. Normalize generated output to one final newline
    # so the committed manifests satisfy strict yamllint and byte-for-byte drift checks agree.
    return result.stdout.rstrip(b"\n") + b"\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--write", action="store_true", help="replace committed generated manifests"
    )
    args = parser.parse_args()

    contract = yaml.safe_load(PROVENANCE.read_text(encoding="utf-8"))
    spec = contract.get("spec") or {}
    actual_tree = expanded_tree_sha256()
    if spec.get("expandedTreeSha256") != actual_tree:
        raise ValueError(
            "vendored ARC tree differs from provenance: "
            f"expected {spec.get('expandedTreeSha256')}, got {actual_tree}"
        )

    approved_images = set((spec.get("images") or {}).values())
    if len(approved_images) != 2 or not all(
        "@sha256:" in image for image in approved_images
    ):
        raise ValueError("ARC provenance must contain exactly two digest-pinned images")

    failures: list[str] = []
    for name, (_, _, _, output_name) in EXPECTED_RELEASES.items():
        generated = render(name)
        discovered = {
            image
            for document in yaml.safe_load_all(generated)
            for image in image_values(document)
        }
        if not discovered or not discovered.issubset(approved_images):
            raise ValueError(
                f"{output_name} uses unapproved images: "
                f"{sorted(discovered - approved_images)}"
            )
        output_path = ROOT / "arc/rendered" / output_name
        if args.write:
            temporary = output_path.with_suffix(".yaml.tmp")
            temporary.write_bytes(generated)
            temporary.replace(output_path)
        elif not output_path.is_file() or output_path.read_bytes() != generated:
            failures.append(output_path.relative_to(ROOT).as_posix())

    if failures:
        print(
            "ARC rendered output is stale; run scripts/render-arc.py --write: "
            + ", ".join(failures),
            file=sys.stderr,
        )
        return 1
    print("ARC vendor provenance and offline render: OK")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, subprocess.CalledProcessError, ValueError, yaml.YAMLError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1) from error
