#!/usr/bin/env python3
# Copyright © 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

"""Create a deterministic ZIP from the committed files of a clean Git tree."""
from __future__ import annotations

import argparse
import hashlib
import stat
import subprocess
import zipfile
from pathlib import Path, PurePosixPath

FORBIDDEN = {".git", ".terraform", ".terragrunt-cache", "__pycache__", "node_modules", ".venv", ".direnv", "__MACOSX"}
FORBIDDEN_SUFFIXES = {".pyc", ".pyo", ".tfplan"}
FIXED_TIME = (2026, 1, 1, 0, 0, 0)


def git(source: Path, *args: str) -> bytes:
    proc = subprocess.run(["git", "-C", str(source), *args], check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode:
        raise ValueError(proc.stderr.decode("utf-8", errors="replace").strip() or f"git {' '.join(args)} failed")
    return proc.stdout


def forbidden(rel: PurePosixPath) -> bool:
    return (
        rel.is_absolute()
        or ".." in rel.parts
        or any(part in FORBIDDEN or part.startswith("._") for part in rel.parts)
        or rel.name == ".DS_Store"
        or rel.name.startswith("terraform.tfstate")
        or rel.suffix in FORBIDDEN_SUFFIXES
    )


def normalized_prefix(raw: str | None) -> PurePosixPath | None:
    if raw is None:
        return None
    prefix = PurePosixPath(raw)
    if not raw or forbidden(prefix):
        raise ValueError("prefix must be a safe relative archive path")
    return prefix


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--prefix")
    parser.add_argument("--allow-dirty", action="store_true", help="diagnostic only; release archives must remain clean")
    args = parser.parse_args()
    source = args.source.resolve()
    output = args.output.resolve()
    prefix = normalized_prefix(args.prefix)
    if not (source / ".git").exists():
        raise ValueError(f"source is not a Git worktree: {source}")
    dirty = git(source, "status", "--porcelain=v1", "--untracked-files=all")
    if dirty and not args.allow_dirty:
        raise ValueError("source worktree is dirty; refusing release archive")

    index = [
        item.decode("utf-8")
        for item in git(source, "ls-files", "--stage", "-z").split(b"\0")
        if item
    ]
    if not index:
        raise ValueError("source repository has no tracked files")
    entries: list[tuple[PurePosixPath, bytes, int]] = []
    for record in sorted(index, key=lambda item: item.split("\t", 1)[-1]):
        metadata, raw_path = record.split("\t", 1)
        mode, _object_id, stage = metadata.split(" ")
        rel = PurePosixPath(raw_path)
        if stage != "0" or mode not in {"100644", "100755"}:
            raise ValueError(f"tracked path is not a regular stage-zero file: {rel}")
        if forbidden(rel):
            raise ValueError(f"tracked forbidden path: {rel}")
        name = prefix / rel if prefix else rel
        entries.append((name, git(source, "show", f"HEAD:{raw_path}"), int(mode[-3:], 8)))

    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, content, perms in entries:
            info = zipfile.ZipInfo(str(name), FIXED_TIME)
            info.external_attr = ((stat.S_IFREG | perms) & 0xFFFF) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, content)

    expected = [str(name) for name, _ in entries]
    with zipfile.ZipFile(output, "r") as archive:
        observed = archive.namelist()
        if observed != expected or len(observed) != len(set(observed)):
            raise ValueError("archive member verification failed")
        if archive.testzip() is not None:
            raise ValueError("archive CRC verification failed")
        for member, (_, content, _) in zip(observed, entries):
            if archive.read(member) != content:
                raise ValueError(f"archive content verification failed: {member}")
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    print(f"{digest}  {output.name}")
    if dirty:
        print("WARNING: diagnostic archive includes tracked working-tree changes; it is not release-qualified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
