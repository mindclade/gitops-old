#!/usr/bin/env python3
# Copyright © 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

#
"""Prove changed target selections came unchanged from the adjacent environment."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml


def applications(path: Path) -> dict[str, dict]:
    document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    raw = (document.get("spec") or {}).get("applications") or []
    if not isinstance(raw, list):
        raise ValueError(f"{path}: spec.applications must be a list")
    result: dict[str, dict] = {}
    for item in raw:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            raise ValueError(f"{path}: every application must be a named object")
        if item["name"] in result:
            raise ValueError(f"{path}: duplicate application {item['name']}")
        result[item["name"]] = item
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--base-target", type=Path, required=True)
    args = parser.parse_args()
    try:
        source = applications(args.source)
        target = applications(args.target)
        base_target = applications(args.base_target)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    changed = sorted(
        name
        for name in set(target) | set(base_target)
        if target.get(name) != base_target.get(name)
    )
    errors = [name for name in changed if target.get(name) != source.get(name)]
    if errors:
        for name in errors:
            print(
                f"ERROR: changed target selection {name!r} does not exactly match "
                f"the adjacent source environment",
                file=sys.stderr,
            )
        return 1
    if changed:
        print("promotion lineage passed: " + ", ".join(changed))
    else:
        print("promotion lineage passed: target selection unchanged")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
