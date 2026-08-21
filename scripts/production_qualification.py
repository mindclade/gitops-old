#!/usr/bin/env python3
# Copyright © 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

"""Validate and assemble the append-only production qualification bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import stat
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

REPOSITORIES = (
    ".github",
    ".github-private",
    "bootstrap",
    "github-config",
    "infrastructure-live",
    "gitops",
    "mindclade-internal-monorepo",
)
TOP_LEVEL = {
    "schema_version",
    "qualification_id",
    "change_reference",
    "qualification_level",
    "scope",
    "repositories",
    "checks",
    "module_references",
    "drill_evidence",
    "connected_boundary",
    "evidence_artifacts",
}
COMMIT = re.compile(r"^[0-9a-f]{40}$")
DIGEST = re.compile(r"^[0-9a-f]{64}$")
IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9-]{2,63}$")
ARTIFACT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{1,127}$")
QUALIFICATION_ID = re.compile(r"^[a-z0-9][a-z0-9-]{5,63}$")
CHANGE_REFERENCE = re.compile(r"^(?:CHG|SEC|DR)-[A-Za-z0-9._-]+$")
FORBIDDEN_PARTS = {
    ".git",
    ".terraform",
    ".terragrunt-cache",
    "__pycache__",
    "node_modules",
    ".venv",
    ".direnv",
    "__MACOSX",
}
FORBIDDEN_SUFFIXES = {".pyc", ".pyo", ".tfplan", ".pem", ".key"}
SECRET_PATTERNS = (
    re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(rb"gh[pousr]_[A-Za-z0-9]{30,}"),
    re.compile(rb"AIza[0-9A-Za-z_-]{35}"),
)
FIXED_TIME = (2026, 1, 1, 0, 0, 0)


def fail(message: str) -> None:
    raise ValueError(message)


def exact_object(value: Any, required: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != required:
        fail(f"{label} field inventory is not exact")
    return value


def nonempty(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        fail(f"{label} must be a non-empty string")
    return value


def load_request(path: Path) -> dict[str, Any]:
    try:
        request = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        fail(f"qualification request is unreadable: {error}")
    exact_object(request, TOP_LEVEL, "qualification request")
    if request["schema_version"] != 1:
        fail("qualification request schema_version must equal 1")
    if request["qualification_level"] != "production":
        fail("qualification_level must equal production")
    if not isinstance(request["qualification_id"], str) or not QUALIFICATION_ID.fullmatch(
        request["qualification_id"]
    ):
        fail("qualification_id is invalid")
    if not isinstance(request["change_reference"], str) or not CHANGE_REFERENCE.fullmatch(
        request["change_reference"]
    ):
        fail("change_reference must be a CHG-, SEC-, or DR- identifier")
    if (
        not isinstance(request["scope"], list)
        or not request["scope"]
        or len(request["scope"]) != len(set(request["scope"]))
        or not all(isinstance(item, str) and item for item in request["scope"])
    ):
        fail("scope must be a non-empty unique string list")

    repositories = exact_object(
        request["repositories"], set(REPOSITORIES), "repository"
    )
    for name, commit in repositories.items():
        if not isinstance(commit, str) or not COMMIT.fullmatch(commit):
            fail(f"repository {name} does not name a full commit SHA")

    artifacts = request["evidence_artifacts"]
    if not isinstance(artifacts, list) or not artifacts:
        fail("evidence_artifacts must not be empty")
    artifact_keys: set[str] = set()
    for item in artifacts:
        item = exact_object(
            item,
            {"key", "repository", "run_id", "artifact_name", "sha256"},
            "evidence artifact",
        )
        key = item["key"]
        if not isinstance(key, str) or not IDENTIFIER.fullmatch(key):
            fail("evidence artifact key is invalid")
        if key in artifact_keys:
            fail(f"duplicate evidence artifact key: {key}")
        artifact_keys.add(key)
        if item["repository"] not in REPOSITORIES:
            fail(f"evidence artifact {key} names an unknown repository")
        if not isinstance(item["run_id"], int) or item["run_id"] < 1:
            fail(f"evidence artifact {key} has an invalid run_id")
        if not isinstance(item["artifact_name"], str) or not ARTIFACT_NAME.fullmatch(
            item["artifact_name"]
        ):
            fail(f"evidence artifact {key} name is invalid")
        if not isinstance(item["sha256"], str) or not DIGEST.fullmatch(item["sha256"]):
            fail(f"evidence artifact {key} has an invalid SHA-256")

    checks = request["checks"]
    if not isinstance(checks, list) or not checks:
        fail("checks must not be empty")
    check_names: set[str] = set()
    used_evidence: set[str] = set()
    for check in checks:
        check = exact_object(
            check, {"name", "status", "command", "detail", "evidence_key"}, "check"
        )
        name = nonempty(check["name"], "check name")
        if name in check_names:
            fail(f"duplicate check name: {name}")
        check_names.add(name)
        if check["status"] != "pass":
            fail(f"request check is not passed: {name}")
        nonempty(check["command"], f"check {name} command")
        nonempty(check["detail"], f"check {name} detail")
        if check["evidence_key"] not in artifact_keys:
            fail(f"check {name} references unknown evidence")
        used_evidence.add(check["evidence_key"])
    if used_evidence != artifact_keys:
        fail("every evidence artifact must support at least one named check")

    modules = request["module_references"]
    if not isinstance(modules, list) or not modules:
        fail("module_references must not be empty")
    if not any(item.get("version") == "v0.4.0" for item in modules if isinstance(item, dict)):
        fail("module_references must include the qualified v0.4.0 release")
    for item in modules:
        item = exact_object(
            item, {"unit", "source", "version", "qualified"}, "module reference"
        )
        nonempty(item["unit"], "module unit")
        nonempty(item["source"], "module source")
        if not isinstance(item["version"], str) or re.fullmatch(
            r"v[0-9]+\.[0-9]+\.[0-9]+", item["version"]
        ) is None:
            fail("module reference version must be full semver")
        if item["qualified"] is not True:
            fail(f"module reference is not qualified: {item['unit']}")

    drills = request["drill_evidence"]
    if not isinstance(drills, list) or not drills:
        fail("drill_evidence must not be empty")
    for drill in drills:
        drill = exact_object(
            drill, {"drill_id", "report_uri", "sha256", "result"}, "drill evidence"
        )
        nonempty(drill["drill_id"], "drill_id")
        uri = nonempty(drill["report_uri"], "drill report_uri")
        if not uri.startswith(("gs://", "https://github.com/")):
            fail("drill report_uri must use protected GCS or GitHub evidence")
        if not isinstance(drill["sha256"], str) or not DIGEST.fullmatch(drill["sha256"]):
            fail("drill evidence SHA-256 is invalid")
        if drill["result"] != "pass":
            fail(f"drill did not pass: {drill['drill_id']}")

    connected = exact_object(
        request["connected_boundary"],
        {"performed", "environments", "mutations", "detail"},
        "connected boundary",
    )
    if connected["performed"] is not True:
        fail("connected production qualification must be performed")
    environments = connected["environments"]
    if (
        not isinstance(environments, list)
        or len(environments) != len(set(environments))
        or not {"staging", "production"}.issubset(environments)
        or not set(environments).issubset(
            {"scratch", "development", "staging", "production"}
        )
    ):
        fail("connected evidence must cover staging and production")
    if (
        not isinstance(connected["mutations"], list)
        or not connected["mutations"]
        or not all(isinstance(item, str) and item for item in connected["mutations"])
    ):
        fail("connected mutations must be explicitly recorded")
    nonempty(connected["detail"], "connected boundary detail")
    return request


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def archive_name(repository: str) -> str:
    return {
        ".github": "dot-github.zip",
        ".github-private": "dot-github-private.zip",
    }.get(repository, f"{repository}.zip")


def forbidden_member(name: str) -> bool:
    rel = PurePosixPath(name)
    lower = rel.name.lower()
    return (
        rel.is_absolute()
        or ".." in rel.parts
        or any(part in FORBIDDEN_PARTS or part.startswith("._") for part in rel.parts)
        or rel.name == ".DS_Store"
        or rel.name.startswith("terraform.tfstate")
        or rel.suffix.lower() in FORBIDDEN_SUFFIXES
        or "kubeconfig" in lower
        or lower in {"credentials", "credentials.json"}
    )


def verify_zip(path: Path) -> None:
    if not path.is_file():
        fail(f"required ZIP is absent: {path}")
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if not names or len(names) != len(set(names)):
            fail(f"ZIP member inventory is empty or duplicated: {path.name}")
        if archive.testzip() is not None:
            fail(f"ZIP CRC verification failed: {path.name}")
        total = 0
        for info in archive.infolist():
            total += info.file_size
            if total > 2_000_000_000:
                fail(f"ZIP uncompressed size exceeds limit: {path.name}")
            if forbidden_member(info.filename):
                fail(f"ZIP contains forbidden member: {path.name}:{info.filename}")
            mode = (info.external_attr >> 16) & 0xFFFF
            if stat.S_ISLNK(mode):
                fail(f"ZIP contains a symlink: {path.name}:{info.filename}")
            if info.file_size <= 2_000_000:
                content = archive.read(info)
                if any(pattern.search(content) for pattern in SECRET_PATTERNS):
                    fail(f"ZIP contains credential-like material: {path.name}:{info.filename}")


def git(repository: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=False,
        text=True,
        capture_output=True,
    )
    if result.returncode:
        fail(result.stderr.strip() or f"git {' '.join(arguments)} failed")
    return result.stdout.strip()


def validate_estate(request: dict[str, Any], estate: Path) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for name in REPOSITORIES:
        repository = estate / name
        if not (repository / ".git").exists():
            fail(f"estate repository is missing: {name}")
        before = git(repository, "status", "--porcelain=v1", "--untracked-files=all") == ""
        commit = git(repository, "rev-parse", "HEAD")
        if not before or commit != request["repositories"][name]:
            fail(f"estate repository is dirty or at the wrong commit: {name}")
        ancestry = subprocess.run(
            ["git", "-C", str(repository), "merge-base", "--is-ancestor", commit, "origin/main"],
            check=False,
        )
        if ancestry.returncode:
            fail(f"repository commit is not reachable from origin/main: {name}")
        after = git(repository, "status", "--porcelain=v1", "--untracked-files=all") == ""
        if not after:
            fail(f"qualification changed repository source: {name}")
        result.append(
            {
                "name": name,
                "commit": commit,
                "clean_before": before,
                "clean_after": after,
            }
        )
    return result


def write_bundle(directory: Path) -> tuple[Path, str]:
    members = sorted(
        path
        for path in directory.rglob("*")
        if path.is_file() and path.name not in {"qualification-bundle.zip", "bundle.sha256"}
    )
    bundle = directory / "qualification-bundle.zip"
    with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in members:
            rel = path.relative_to(directory).as_posix()
            if forbidden_member(rel):
                fail(f"bundle contains a forbidden path: {rel}")
            info = zipfile.ZipInfo(rel, FIXED_TIME)
            info.external_attr = ((stat.S_IFREG | 0o644) & 0xFFFF) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, path.read_bytes())
    verify_zip(bundle)
    digest = sha256(bundle)
    (directory / "bundle.sha256").write_text(
        f"{digest}  qualification-bundle.zip\n", encoding="utf-8"
    )
    return bundle, digest


def assemble(
    request_path: Path,
    estate: Path,
    source_archives: Path,
    evidence: Path,
    audit_path: Path,
    output: Path,
) -> str:
    request = load_request(request_path)
    repositories = validate_estate(request, estate)
    if output.exists() and any(output.iterdir()):
        fail("output directory must be absent or empty")
    output.mkdir(parents=True, exist_ok=True)
    source_target = output / "source"
    evidence_target = output / "connected-evidence"
    source_target.mkdir()
    evidence_target.mkdir()
    artifacts: list[dict[str, str]] = []

    for repository in REPOSITORIES:
        source = source_archives / archive_name(repository)
        verify_zip(source)
        target = source_target / source.name
        shutil.copyfile(source, target)
        artifacts.append({"path": target.relative_to(output).as_posix(), "sha256": sha256(target)})

    for declaration in request["evidence_artifacts"]:
        source = evidence / f"{declaration['key']}.zip"
        if sha256(source) != declaration["sha256"]:
            fail(f"evidence digest differs: {declaration['key']}")
        verify_zip(source)
        target = evidence_target / source.name
        shutil.copyfile(source, target)
        artifacts.append({"path": target.relative_to(output).as_posix(), "sha256": sha256(target)})

    try:
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        fail(f"estate audit is unreadable: {error}")
    if audit.get("status") != "PASS" or audit.get("repositories") != list(REPOSITORIES):
        fail("estate audit did not pass the exact seven-repository inventory")
    audit_target = output / "estate-audit.json"
    shutil.copyfile(audit_path, audit_target)
    artifacts.append({"path": audit_target.name, "sha256": sha256(audit_target)})

    checks = [
        {
            "name": "seven-repository-estate-audit",
            "status": "pass",
            "command": "python3 scripts/audit-production-estate.py <estate> --json estate-audit.json",
            "detail": "Canonical authority, inventory, hygiene, and immutable-image audit passed.",
        }
    ]
    checks.extend(
        {
            "name": item["name"],
            "status": item["status"],
            "command": item["command"],
            "detail": f"{item['detail']} Evidence artifact: {item['evidence_key']}.zip.",
        }
        for item in request["checks"]
    )
    gitops_epoch = int(git(estate / "gitops", "show", "-s", "--format=%ct", "HEAD"))
    generated_at = datetime.fromtimestamp(gitops_epoch, timezone.utc).isoformat().replace(
        "+00:00", "Z"
    )
    report = {
        "schema_version": 2,
        "status": "PASS",
        "generated_at": generated_at,
        "qualification_level": "production",
        "scope": request["scope"],
        "repositories": repositories,
        "checks": checks,
        "module_references": request["module_references"],
        "drill_evidence": request["drill_evidence"],
        "connected_boundary": request["connected_boundary"],
        "artifacts": sorted(artifacts, key=lambda item: item["path"]),
    }
    report_path = output / "qualification-report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary = output / "qualification-report.md"
    summary.write_text(
        "# Production qualification\n\n"
        f"- Status: PASS\n"
        f"- Qualification ID: {request['qualification_id']}\n"
        f"- Change reference: {request['change_reference']}\n"
        f"- Repositories: {len(repositories)} exact protected-main commits\n"
        f"- Connected checks: {len(request['checks'])}\n"
        f"- Evidence artifacts: {len(request['evidence_artifacts'])}\n"
        f"- Generated: {report['generated_at']}\n",
        encoding="utf-8",
    )
    manifest_entries = []
    for path in sorted(path for path in output.rglob("*") if path.is_file()):
        manifest_entries.append(
            {"path": path.relative_to(output).as_posix(), "sha256": sha256(path)}
        )
    (output / "checksums.json").write_text(
        json.dumps({"schema_version": 1, "files": manifest_entries}, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    _, bundle_digest = write_bundle(output)
    return bundle_digest


def verify(directory: Path) -> str:
    bundle = directory / "qualification-bundle.zip"
    digest_file = directory / "bundle.sha256"
    expected_line = digest_file.read_text(encoding="utf-8").strip()
    match = re.fullmatch(r"([0-9a-f]{64})  qualification-bundle\.zip", expected_line)
    if match is None or sha256(bundle) != match.group(1):
        fail("qualification bundle digest differs")
    verify_zip(bundle)
    with zipfile.ZipFile(bundle) as archive:
        names = set(archive.namelist())
        for required in (
            "qualification-report.json",
            "qualification-report.md",
            "estate-audit.json",
            "checksums.json",
        ):
            if required not in names:
                fail(f"qualification bundle omits {required}")
        report = json.loads(archive.read("qualification-report.json"))
        if report.get("schema_version") != 2 or report.get("status") != "PASS":
            fail("qualification report is not a production PASS report v2")
        repositories = report.get("repositories")
        if not isinstance(repositories, list) or {
            item.get("name") for item in repositories if isinstance(item, dict)
        } != set(REPOSITORIES):
            fail("qualification report repository inventory differs")
        checksums = json.loads(archive.read("checksums.json"))
        checksum_items = checksums.get("files")
        if checksums.get("schema_version") != 1 or not isinstance(checksum_items, list):
            fail("checksums manifest is invalid")
        checksum_paths = [
            item.get("path") for item in checksum_items if isinstance(item, dict)
        ]
        if (
            len(checksum_paths) != len(checksum_items)
            or len(checksum_paths) != len(set(checksum_paths))
            or set(checksum_paths) != names - {"checksums.json"}
        ):
            fail("checksums manifest inventory is not exact")
        for item in checksum_items:
            if set(item) != {"path", "sha256"}:
                fail("checksums manifest entry is not exact")
            if item["path"] not in names:
                fail(f"checksums manifest names an absent member: {item['path']}")
            if hashlib.sha256(archive.read(item["path"])).hexdigest() != item["sha256"]:
                fail(f"checksums manifest differs: {item['path']}")
    return match.group(1)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    request = subparsers.add_parser("request")
    request.add_argument("path", type=Path)
    assemble_parser = subparsers.add_parser("assemble")
    assemble_parser.add_argument("--request", required=True, type=Path)
    assemble_parser.add_argument("--estate", required=True, type=Path)
    assemble_parser.add_argument("--source-archives", required=True, type=Path)
    assemble_parser.add_argument("--evidence", required=True, type=Path)
    assemble_parser.add_argument("--audit", required=True, type=Path)
    assemble_parser.add_argument("--output", required=True, type=Path)
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("directory", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.command == "request":
            request = load_request(args.path)
            print(
                json.dumps(
                    {
                        "qualification_id": request["qualification_id"],
                        "repositories": request["repositories"],
                        "evidence_artifacts": request["evidence_artifacts"],
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                )
            )
        elif args.command == "assemble":
            print(
                assemble(
                    args.request,
                    args.estate,
                    args.source_archives,
                    args.evidence,
                    args.audit,
                    args.output,
                )
            )
        else:
            print(verify(args.directory))
        return 0
    except (OSError, ValueError, zipfile.BadZipFile) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
