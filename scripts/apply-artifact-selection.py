#!/usr/bin/env python3
# Copyright © 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

#
"""Apply one GitOps-owned digest selection to Kustomize-rendered YAML on stdin."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml


IMAGE_LINE = re.compile(
    r"(?m)^(?P<prefix>\s*(?:-\s*)?image:\s*)(?P<quote>['\"]?)"
    r"(?P<image>[^\s'\"#]+)(?P=quote)(?P<suffix>\s*(?:#.*)?)$"
)
DIGEST = re.compile(r"sha256:[0-9a-f]{64}")


def repository_of(image: str) -> str:
    repository = image.split("@", 1)[0]
    last_slash = repository.rfind("/")
    last_colon = repository.rfind(":")
    if last_colon > last_slash:
        repository = repository[:last_colon]
    return repository


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--application", required=True)
    args = parser.parse_args()
    text = sys.stdin.read()
    try:
        document = yaml.safe_load(args.selection.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        print(f"cannot load artifact selection: {exc}", file=sys.stderr)
        return 1
    applications = (document.get("spec") or {}).get("applications") or []
    selected = next(
        (item for item in applications if item.get("name") == args.application), None
    )
    matches = list(IMAGE_LINE.finditer(text))
    if not matches and selected is None:
        sys.stdout.write(text)
        return 0
    if matches and selected is None:
        print(
            f"rendered application {args.application} contains images but has no artifact selection",
            file=sys.stderr,
        )
        return 1
    mappings = {}
    for item in selected.get("images") or []:
        repository = str(item.get("repository", ""))
        digest = str(item.get("digest", ""))
        if not repository or not DIGEST.fullmatch(digest):
            print(
                f"invalid artifact selection for {args.application}: {repository}@{digest}",
                file=sys.stderr,
            )
            return 1
        mappings[repository] = f"{repository}@{digest}"
    used: set[str] = set()

    def replace(match: re.Match[str]) -> str:
        original = match.group("image")
        repository = repository_of(original)
        if repository not in mappings:
            raise ValueError(
                f"rendered image {original} has no selection in {args.application}"
            )
        used.add(repository)
        return f"{match.group('prefix')}{match.group('quote')}{mappings[repository]}{match.group('quote')}{match.group('suffix')}"

    try:
        output = IMAGE_LINE.sub(replace, text)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    unused = sorted(set(mappings) - used)
    if unused:
        print(
            f"artifact selections matched no rendered image in {args.application}: {', '.join(unused)}",
            file=sys.stderr,
        )
        return 1
    sys.stdout.write(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
