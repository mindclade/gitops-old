#!/usr/bin/env python3
# Copyright © 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

"""Validate promotion changes between two exact Git commits."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path


SHA_PATTERN = re.compile(r"[0-9a-f]{40}")
PROMOTION_PAIRS = (("development", "staging"), ("staging", "production"))


def git(
    repository: Path, *arguments: str, check: bool = True
) -> subprocess.CompletedProcess[bytes]:
    result = subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=False,
        capture_output=True,
    )
    if check and result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise ValueError(detail or f"git {' '.join(arguments)} failed")
    return result


def require_commit(repository: Path, label: str, revision: str) -> None:
    if SHA_PATTERN.fullmatch(revision) is None:
        raise ValueError(f"invalid {label} SHA")
    result = git(repository, "cat-file", "-e", f"{revision}^{{commit}}", check=False)
    if result.returncode != 0:
        raise ValueError(f"{label} SHA is not an available commit")


def changed(repository: Path, base_sha: str, head_sha: str, relative: str) -> bool:
    result = git(
        repository,
        "diff",
        "--quiet",
        f"{base_sha}...{head_sha}",
        "--",
        relative,
        check=False,
    )
    if result.returncode not in (0, 1):
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise ValueError(detail or f"could not compare {relative}")
    return result.returncode == 1


def blob(
    repository: Path,
    revision: str,
    relative: str,
    *,
    missing_ok: bool = False,
) -> bytes:
    if missing_ok:
        listing = git(repository, "ls-tree", "--name-only", revision, "--", relative)
        if listing.stdout.decode("utf-8", errors="strict").strip() != relative:
            return b""
    return git(repository, "show", f"{revision}:{relative}").stdout


def validate_range(repository: Path, base_sha: str, head_sha: str) -> int:
    require_commit(repository, "base", base_sha)
    require_commit(repository, "head", head_sha)
    validator = Path(__file__).with_name("validate-promotion-change.py")
    checked = 0

    with tempfile.TemporaryDirectory() as directory:
        stage = Path(directory)
        for source, target in PROMOTION_PAIRS:
            target_relative = f"deployments/{target}.yaml"
            if not changed(repository, base_sha, head_sha, target_relative):
                continue

            source_path = stage / f"{source}.yaml"
            target_path = stage / f"{target}.yaml"
            base_target_path = stage / f"base-{target}.yaml"
            source_path.write_bytes(
                blob(repository, base_sha, f"deployments/{source}.yaml")
            )
            target_path.write_bytes(blob(repository, head_sha, target_relative))
            base_target_path.write_bytes(
                blob(repository, base_sha, target_relative, missing_ok=True)
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(validator),
                    "--source",
                    str(source_path),
                    "--target",
                    str(target_path),
                    "--base-target",
                    str(base_target_path),
                ],
                check=False,
            )
            if result.returncode != 0:
                return result.returncode
            checked += 1

    print(
        f"Checked {checked} changed promotion target(s) between "
        f"{base_sha} and {head_sha}."
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--head-sha", required=True)
    args = parser.parse_args()
    try:
        return validate_range(args.repository.resolve(), args.base_sha, args.head_sha)
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
