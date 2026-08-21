#!/usr/bin/env python3
# Copyright © 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

# MINDCLADE CONFIDENTIAL - PROPRIETARY AND TRADE SECRET
# Copyright (c) 2026 Mindclade. All rights reserved.
"""Validate immutable deployment release evidence without contacting external services."""

from __future__ import annotations
import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

try:
    import jsonschema
except ImportError:
    print(
        "jsonschema is required from the pinned repository toolchain", file=sys.stderr
    )
    raise SystemExit(2)

SHA40 = re.compile(r"[0-9a-f]{40}")
DIGEST_IMAGE = re.compile(r"[^\s]+@sha256:[0-9a-f]{64}")
SHA256 = re.compile(r"sha256:[0-9a-f]{64}")
MINDCLADE_REPOSITORY = re.compile(r"mindclade/[A-Za-z0-9_.-]+")
SIGNER_WORKFLOW_REF = re.compile(
    r"mindclade/\.github/\.github/workflows/reusable-binauthz-sign\.yml@refs/tags/v[0-9]+\.[0-9]+\.[0-9]+"
)
REQUIRED = {
    "contract_version",
    "release_id",
    "source_repository",
    "source_revision",
    "builder_identity",
    "build_invocation_id",
    "image",
    "sbom",
    "provenance",
    "vulnerability",
    "qualification",
    "supply_chain_attestations",
    "created_at",
}
REQUIRED_V4 = {
    "contract_version",
    "release_id",
    "release_kind",
    "subject",
    "source_repository",
    "source_revision",
    "builder_identity",
    "build_invocation_id",
    "images",
    "artifacts",
    "producer_evidence",
    "vulnerability",
    "evidence",
    "attestations",
    "evidence_retention",
    "compatibility",
    "migration",
    "rollback",
    "created_at",
}
DEFAULT_SOURCE_REPOSITORY = "mindclade/mindclade-internal-monorepo"
DEFAULT_SIGNER_WORKFLOW_REF = (
    "mindclade/.github/.github/workflows/reusable-binauthz-sign.yml@refs/tags/v3.0.0"
)


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def artifact_ref(value):
    return (
        isinstance(value, dict)
        and nonempty(value.get("uri"))
        and SHA256.fullmatch(str(value.get("digest", ""))) is not None
    )


def attestor_ref(value):
    return (
        isinstance(value, dict)
        and nonempty(value.get("project"))
        and nonempty(value.get("attestor"))
    )


def governed_exception_images(path: Path | None, errors: list[str]) -> set[str]:
    """Load the trusted JSON projection of image-policy.spec.unsigned."""
    if path is None:
        return set()
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"cannot read unsigned exceptions file: {exc}")
        return set()
    if not isinstance(value, list):
        errors.append("unsigned exceptions file must contain one JSON list")
        return set()
    today = dt.date.today()
    images: set[str] = set()
    for index, exception in enumerate(value):
        label = f"unsigned exception[{index}]"
        if not isinstance(exception, dict):
            errors.append(f"{label} must be an object")
            continue
        image = str(exception.get("image", ""))
        if not DIGEST_IMAGE.fullmatch(image):
            errors.append(f"{label} must name one exact digest")
        elif image in images:
            errors.append(f"{label} duplicates {image}")
        else:
            images.add(image)
        for field in (
            "owner",
            "reason",
            "reviewer",
            "approval",
            "change",
            "removal",
        ):
            if not nonempty(exception.get(field)):
                errors.append(f"{label} missing {field}")
        if exception.get("owner") != "@mindclade/platform":
            errors.append(f"{label} owner must be @mindclade/platform")
        if exception.get("reviewer") != "@mindclade/security":
            errors.append(f"{label} reviewer must be @mindclade/security")
        if exception.get("approval") != "required-protected-security-review":
            errors.append(f"{label} must require protected security review")
        if exception.get("scope") != {
            "component": "argocd-control-plane",
            "environments": ["staging", "production"],
        }:
            errors.append(f"{label} has an invalid control-plane scope")
        try:
            granted = dt.date.fromisoformat(str(exception.get("granted", "")))
            expires = dt.date.fromisoformat(str(exception.get("expires", "")))
            if expires < today:
                errors.append(f"{label} is expired")
            if expires < granted or (expires - granted).days > 90:
                errors.append(f"{label} lifetime must be between 0 and 90 days")
        except ValueError:
            errors.append(f"{label} granted/expires must be ISO dates")
    return images


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    ap.add_argument("--images-file", type=Path)
    ap.add_argument("--unsigned-exceptions-file", type=Path)
    ap.add_argument("--expected-source-repository", default=DEFAULT_SOURCE_REPOSITORY)
    ap.add_argument(
        "--expected-signer-workflow-ref", default=DEFAULT_SIGNER_WORKFLOW_REF
    )
    ap.add_argument("--expected-deployment-attestor-project")
    ap.add_argument("--expected-deployment-attestor")
    args = ap.parse_args()
    root = args.root.resolve()
    errors = []
    records = {}
    unsigned_images = governed_exception_images(args.unsigned_exceptions_file, errors)
    if not MINDCLADE_REPOSITORY.fullmatch(str(args.expected_source_repository)):
        errors.append("--expected-source-repository must name one Mindclade repository")
    if not SIGNER_WORKFLOW_REF.fullmatch(str(args.expected_signer_workflow_ref)):
        errors.append(
            "--expected-signer-workflow-ref must name an immutable Mindclade signer release"
        )
    # The pull_request_target verifier passes repository variables as explicit arguments. Before
    # connected validation is activated GitHub expands both absent variables to empty strings.
    # Treat that pair as "not configured" while still rejecting a half-configured trust root.
    args.expected_deployment_attestor_project = (
        args.expected_deployment_attestor_project or None
    )
    args.expected_deployment_attestor = args.expected_deployment_attestor or None
    if (args.expected_deployment_attestor_project is None) != (
        args.expected_deployment_attestor is None
    ):
        errors.append("deployment attestor project and attestor must be configured together")
    schema_path = root / "contracts/release-metadata.schema.json"
    schema_validator = None
    schema_version = None
    try:
        schema = json.loads(schema_path.read_text("utf-8"))
        jsonschema.Draft202012Validator.check_schema(schema)
        schema_validator = jsonschema.Draft202012Validator(
            schema, format_checker=jsonschema.FormatChecker()
        )
        schema_required = set(schema.get("required") or [])
        schema_version = (
            (schema.get("properties") or {}).get("contract_version") or {}
        ).get("const")
        required_by_version = {
            "3.0.0": REQUIRED,
            "4.0.0": REQUIRED_V4,
        }
        if schema_version not in required_by_version:
            errors.append(
                f"{schema_path}: contract_version const must be 3.0.0 or 4.0.0"
            )
        elif schema_required != required_by_version[schema_version]:
            errors.append(
                f"{schema_path}: required fields do not match validator contract"
            )
    except Exception as exc:
        errors.append(f"{schema_path}: invalid or missing schema: {exc}")
    release_root = root / "releases"
    release_paths = (
        sorted(release_root.rglob("*.json")) if release_root.exists() else []
    )
    if schema_version == "4.0.0" and release_paths:
        errors.append(
            "the migration bridge accepts the v4 schema only while releases/ is empty"
        )
    for p in release_paths:
        if schema_version == "4.0.0":
            continue
        try:
            obj = json.loads(p.read_text("utf-8"))
        except Exception as exc:
            errors.append(f"{p}: invalid JSON: {exc}")
            continue
        if schema_validator is not None:
            for failure in sorted(
                schema_validator.iter_errors(obj), key=lambda item: list(item.path)
            ):
                location = ".".join(str(part) for part in failure.path) or "<root>"
                errors.append(f"{p}: schema violation at {location}: {failure.message}")
        missing = REQUIRED - set(obj)
        if missing:
            errors.append(f"{p}: missing {sorted(missing)}")
        if obj.get("contract_version") != "3.0.0":
            errors.append(f"{p}: unsupported contract_version; expected 3.0.0")
        if not nonempty(obj.get("release_id")):
            errors.append(f"{p}: release_id must be non-empty")
        source_repository = str(obj.get("source_repository", ""))
        if not MINDCLADE_REPOSITORY.fullmatch(source_repository):
            errors.append(f"{p}: source_repository must be a Mindclade repository")
        elif source_repository != args.expected_source_repository:
            errors.append(
                f"{p}: source_repository is not the trusted producer {args.expected_source_repository}"
            )
        if not SHA40.fullmatch(str(obj.get("source_revision", ""))):
            errors.append(f"{p}: source_revision must be a full commit SHA")
        if not nonempty(obj.get("builder_identity")):
            errors.append(f"{p}: builder_identity must be non-empty")
        if not nonempty(obj.get("build_invocation_id")):
            errors.append(f"{p}: build_invocation_id must be non-empty")
        image = str(obj.get("image", ""))
        if not DIGEST_IMAGE.fullmatch(image):
            errors.append(f"{p}: image must be an immutable sha256 digest reference")
        if not artifact_ref(obj.get("sbom")):
            errors.append(f"{p}: sbom must contain uri and sha256 digest")
        if not artifact_ref(obj.get("provenance")):
            errors.append(f"{p}: provenance must contain uri and sha256 digest")
        vuln = obj.get("vulnerability")
        if (
            not isinstance(vuln, dict)
            or vuln.get("result") not in {"pass", "approved"}
            or not nonempty(vuln.get("scanner"))
            or not artifact_ref(vuln.get("evidence"))
        ):
            errors.append(
                f"{p}: vulnerability must be passing and include scanner plus evidence uri/digest"
            )
        qual = obj.get("qualification")
        if (
            not isinstance(qual, dict)
            or qual.get("result") != "pass"
            or not artifact_ref(qual.get("evidence"))
        ):
            errors.append(f"{p}: qualification must be pass with evidence uri/digest")
        chain = obj.get("supply_chain_attestations")
        if not isinstance(chain, dict):
            errors.append(
                f"{p}: supply_chain_attestations must identify build, qualification, and deployment evidence"
            )
        else:
            build = chain.get("build")
            qualification = chain.get("qualification")
            deployment = chain.get("deployment")
            deployment_workflow_ref = (
                deployment.get("signer_workflow_ref", "")
                if isinstance(deployment, dict)
                else ""
            )
            if not attestor_ref(build):
                errors.append(
                    f"{p}: supply_chain_attestations.build must identify its project and attestor"
                )
            if not attestor_ref(qualification):
                errors.append(
                    f"{p}: supply_chain_attestations.qualification must identify its project and attestor"
                )
            if not attestor_ref(deployment) or not SIGNER_WORKFLOW_REF.fullmatch(
                str(deployment_workflow_ref)
            ):
                errors.append(
                    f"{p}: supply_chain_attestations.deployment must identify its project, attestor, and immutable signer workflow"
                )
            elif (
                deployment.get("signer_workflow_ref")
                != args.expected_signer_workflow_ref
            ):
                errors.append(
                    f"{p}: deployment signer is not the trusted workflow {args.expected_signer_workflow_ref}"
                )
            if all(attestor_ref(item) for item in (build, qualification, deployment)):
                roots = {
                    (item["project"], item["attestor"])
                    for item in (build, qualification, deployment)
                }
                if len(roots) != 3:
                    errors.append(
                        f"{p}: build, qualification, and deployment attestor roots must be distinct"
                    )
            if attestor_ref(deployment):
                if (
                    args.expected_deployment_attestor_project is not None
                    and deployment.get("project")
                    != args.expected_deployment_attestor_project
                ):
                    errors.append(
                        f"{p}: deployment attestor project does not match the configured trust root"
                    )
                if (
                    args.expected_deployment_attestor is not None
                    and deployment.get("attestor") != args.expected_deployment_attestor
                ):
                    errors.append(
                        f"{p}: deployment attestor does not match the configured trust root"
                    )
        created = str(obj.get("created_at", ""))
        try:
            parsed = dt.datetime.fromisoformat(created.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError
        except ValueError:
            errors.append(f"{p}: created_at must be timezone-aware RFC3339")
        if image:
            if image in records:
                errors.append(f"{p}: duplicate release record for {image}")
            records[image] = str(p.relative_to(root))
    if args.images_file:
        try:
            images = [
                x.strip()
                for x in args.images_file.read_text().splitlines()
                if x.strip()
            ]
        except OSError as exc:
            errors.append(f"cannot read images file: {exc}")
            images = []
        active_images = set(images)
        for image in images:
            if image not in records and image not in unsigned_images:
                errors.append(f"no release metadata record for active image: {image}")
        for image in sorted(unsigned_images - active_images):
            errors.append(f"unsigned exception is not an active control-plane image: {image}")
    if errors:
        for error in sorted(set(errors)):
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"release metadata validation passed ({len(records)} record(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
