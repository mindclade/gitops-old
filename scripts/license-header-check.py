#!/usr/bin/env python3
# Copyright © 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

"""Check or repair Mindclade proprietary headers in repository source files."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


SUPPORTED_SUFFIXES = {".example", ".hcl", ".nix", ".py", ".sh", ".tf", ".yaml", ".yml"}
EXCLUDED_PARTS = {".git", ".terraform", ".terragrunt-cache", "rendered"}
EXCLUDED_PATHS = {"bootstrap/argocd-install-ha.yaml", "bootstrap/argocd-install.yaml"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate or repair proprietary source-file headers."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="validate headers (default)")
    mode.add_argument("--fix", action="store_true", help="repair missing headers")
    parser.add_argument("files", nargs="*", type=Path)
    return parser.parse_args()


def repository_root() -> Path:
    return Path(__file__).resolve().parent.parent


def load_header(root: Path) -> tuple[str, str, str]:
    candidates = (
        root / "license-header.txt",
        Path(__file__).with_name("license-header.txt"),
    )
    header_file = next((path for path in candidates if path.is_file()), None)
    if header_file is None:
        raise ValueError(
            f"missing license header file; checked: {', '.join(map(str, candidates))}"
        )
    lines = header_file.read_text(encoding="utf-8-sig").splitlines()[:3]
    if len(lines) != 3 or any(not line.rstrip("\r") for line in lines):
        raise ValueError(f"invalid three-line proprietary header: {header_file}")
    return tuple(line.rstrip("\r") for line in lines)  # type: ignore[return-value]


def relative_name(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def is_target(path: Path, root: Path) -> bool:
    relative = relative_name(path, root)
    if any(part in EXCLUDED_PARTS for part in Path(relative).parts):
        return False
    if relative.startswith("policy/templates/vendor/") or relative in EXCLUDED_PATHS:
        return False
    if path.name == ".terraform.lock.hcl" or path.name.endswith(".lock.hcl"):
        return False
    return path.name == "CODEOWNERS" or path.suffix in SUPPORTED_SUFFIXES


def repository_files(root: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    return [root / name.decode("utf-8") for name in result.stdout.split(b"\0") if name]


def header_offset(lines: list[str]) -> int:
    return 1 if lines and (lines[0].startswith("#!") or lines[0] == "---") else 0


def has_header(path: Path, header: tuple[str, str, str]) -> bool:
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    offset = header_offset(lines)
    return lines[offset : offset + 3] == list(header) and (
        len(lines) == offset + 3 or lines[offset + 3] == ""
    )


def repair_header(path: Path, header: tuple[str, str, str]) -> None:
    original = path.read_text(encoding="utf-8-sig")
    lines = original.splitlines()
    offset = header_offset(lines)
    prefix, remainder = lines[:offset], lines[offset:]
    if (
        remainder
        and remainder[0].startswith("# Copyright ")
        and "Mindclade, LLC" in remainder[0]
    ):
        remainder = remainder[3:]
        if remainder and remainder[0] == "":
            remainder = remainder[1:]
    updated = prefix + list(header) + [""] + remainder
    temporary = path.with_name(f".{path.name}.license-header.tmp")
    temporary.write_text("\n".join(updated) + "\n", encoding="utf-8")
    temporary.chmod(path.stat().st_mode)
    temporary.replace(path)


def main() -> int:
    args = parse_args()
    root = repository_root()
    try:
        header = load_header(root)
        candidates = args.files or repository_files(root)
    except (OSError, subprocess.CalledProcessError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    failures: list[Path] = []
    fixed = 0
    for candidate in candidates:
        path = candidate if candidate.is_absolute() else root / candidate
        if not path.is_file() or not is_target(path, root) or has_header(path, header):
            continue
        if args.fix:
            repair_header(path, header)
            print(f"Fixed proprietary header: {relative_name(path, root)}")
            fixed += 1
        else:
            failures.append(path)
            print(
                f"Missing or malformed proprietary header: {relative_name(path, root)}",
                file=sys.stderr,
            )
    if failures:
        print("License header check failed.", file=sys.stderr)
        return 1
    if args.fix:
        print(f"Fixed proprietary headers in {fixed} file(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
