#!/usr/bin/env python3
# Copyright © 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

#
"""Copy immutable application artifact selections between adjacent environments."""

from __future__ import annotations

import argparse
import copy
import re
import sys
import tempfile
import os
from pathlib import Path

import yaml


ADJACENT = {("development", "staging"), ("staging", "production")}
APPLICATION = re.compile(
    r"(?:platform|serving|research|data|partner)-[a-z0-9][a-z0-9-]*"
)
HEADER = """# Copyright © 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

---
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--application", required=True)
    parser.add_argument(
        "--apply", action="store_true", help="atomically update the target"
    )
    args = parser.parse_args()
    source = yaml.safe_load(args.source.read_text(encoding="utf-8")) or {}
    target = yaml.safe_load(args.target.read_text(encoding="utf-8")) or {}
    source_environment = (source.get("spec") or {}).get("environment")
    target_environment = (target.get("spec") or {}).get("environment")
    if (source_environment, target_environment) not in ADJACENT:
        raise SystemExit(
            f"invalid promotion path: {source_environment!r} to {target_environment!r}"
        )
    if args.application != "all" and not APPLICATION.fullmatch(args.application):
        raise SystemExit(f"invalid application name: {args.application!r}")
    source_apps = (source.get("spec") or {}).get("applications") or []
    target_apps = (target.get("spec") or {}).get("applications") or []
    if args.application == "all":
        selected = source_apps
    else:
        selected = [
            item for item in source_apps if item.get("name") == args.application
        ]
    if not selected:
        raise SystemExit(
            f"no artifact selection found for {args.application!r} in {args.source}"
        )
    selected_names = {item["name"] for item in selected}
    merged = [item for item in target_apps if item.get("name") not in selected_names]
    merged.extend(copy.deepcopy(selected))
    merged.sort(key=lambda item: item["name"])
    target.setdefault("spec", {})["applications"] = merged
    rendered = HEADER + yaml.safe_dump(target, sort_keys=False)
    if not args.apply:
        sys.stdout.write(rendered)
        return 0
    descriptor, name = tempfile.mkstemp(
        prefix=f".{args.target.name}.", dir=args.target.parent
    )
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(rendered)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(args.target)
    finally:
        temporary.unlink(missing_ok=True)
    print("promoted artifact selections: " + ", ".join(sorted(selected_names)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
