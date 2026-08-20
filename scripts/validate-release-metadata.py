#!/usr/bin/env python3
# Copyright © 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

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
    print("jsonschema is required from the pinned repository toolchain", file=sys.stderr)
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
    "release_kind",
    "subject",
    "source_repository",
    "source_revision",
    "builder_identity",
    "build_invocation_id",
    "images",
    "artifacts",
    "evidence",
    "attestations",
    "compatibility",
    "migration",
    "rollback",
    "created_at",
}
PREDICATE_ARTIFACT_TYPES = {
    "build-provenance": "provenance",
    "qualification": "qualification",
    "sbom": "sbom",
    "vulnerability-scan": "vulnerability-scan",
}
REQUIRED_ARTIFACT_TYPES = set(PREDICATE_ARTIFACT_TYPES.values()) | {"rollback"}
DEFAULT_SOURCE_REPOSITORY = "mindclade/mindclade-internal-monorepo"
DEFAULT_SIGNER_WORKFLOW_REF = (
    "mindclade/.github/.github/workflows/reusable-binauthz-sign.yml@refs/tags/v4.0.0"
)


def nonempty(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def attestor_ref(value: object) -> bool:
    return (
        isinstance(value, dict)
        and nonempty(value.get("project"))
        and nonempty(value.get("attestor"))
    )


def aware_timestamp(value: object) -> dt.datetime | None:
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


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
        for field in ("owner", "reason", "reviewer", "approval", "change", "removal"):
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


def validate_record(
    path: Path,
    obj: dict,
    args: argparse.Namespace,
    errors: list[str],
) -> tuple[set[str], str, str]:
    """Validate semantic relationships that JSON Schema cannot express."""
    label = str(path)
    if obj.get("contract_version") != "4.0.0":
        errors.append(f"{label}: unsupported contract_version; expected 4.0.0")
    source_repository = str(obj.get("source_repository", ""))
    if not MINDCLADE_REPOSITORY.fullmatch(source_repository):
        errors.append(f"{label}: source_repository must be a Mindclade repository")
    elif source_repository != args.expected_source_repository:
        errors.append(
            f"{label}: source_repository is not the trusted producer {args.expected_source_repository}"
        )
    if not SHA40.fullmatch(str(obj.get("source_revision", ""))):
        errors.append(f"{label}: source_revision must be a full commit SHA")
    for field in ("release_id", "builder_identity", "build_invocation_id"):
        if not nonempty(obj.get(field)):
            errors.append(f"{label}: {field} must be non-empty")

    subject = obj.get("subject") if isinstance(obj.get("subject"), dict) else {}
    subject_name = str(subject.get("name", ""))
    subject_digest = str(subject.get("digest", ""))
    if not SHA256.fullmatch(subject_digest):
        errors.append(f"{label}: subject.digest must be one sha256 digest")

    raw_images = obj.get("images")
    images = raw_images if isinstance(raw_images, dict) else {}
    if list(images) != sorted(images):
        errors.append(f"{label}: image names must be sorted")
    image_values: set[str] = set()
    for name, image in images.items():
        image = str(image)
        if not DIGEST_IMAGE.fullmatch(image):
            errors.append(f"{label}: images.{name} must be an immutable sha256 reference")
        if image in image_values:
            errors.append(f"{label}: image digest reference is duplicated: {image}")
        image_values.add(image)

    raw_artifacts = obj.get("artifacts")
    artifacts = raw_artifacts if isinstance(raw_artifacts, list) else []
    artifact_names: list[str] = []
    artifact_by_name: dict[str, dict] = {}
    artifact_types: dict[str, list[str]] = {}
    for index, artifact in enumerate(artifacts):
        if not isinstance(artifact, dict):
            errors.append(f"{label}: artifacts[{index}] must be an object")
            continue
        name = str(artifact.get("name", ""))
        artifact_type = str(artifact.get("type", ""))
        if name in artifact_by_name:
            errors.append(f"{label}: duplicate artifact name {name!r}")
        artifact_names.append(name)
        artifact_by_name[name] = artifact
        artifact_types.setdefault(artifact_type, []).append(name)
    if artifact_names != sorted(artifact_names):
        errors.append(f"{label}: artifacts must be sorted by name")
    for required_type in sorted(REQUIRED_ARTIFACT_TYPES):
        names = artifact_types.get(required_type, [])
        if len(names) != 1:
            errors.append(
                f"{label}: artifacts must contain exactly one {required_type!r} record"
            )

    evidence = obj.get("evidence") if isinstance(obj.get("evidence"), dict) else {}
    if evidence.get("result") != "pass":
        errors.append(f"{label}: evidence.result must be pass")
    graph = evidence.get("graph") if isinstance(evidence.get("graph"), list) else []
    seen_predicates: set[str] = set()
    for index, edge in enumerate(graph):
        if not isinstance(edge, dict):
            errors.append(f"{label}: evidence.graph[{index}] must be an object")
            continue
        predicate = str(edge.get("predicate_type", ""))
        artifact_name = str(edge.get("artifact", ""))
        if predicate in seen_predicates:
            errors.append(f"{label}: duplicate evidence predicate {predicate!r}")
        seen_predicates.add(predicate)
        if edge.get("subject_digest") != subject_digest:
            errors.append(f"{label}: evidence.graph[{index}] does not bind the subject")
        artifact = artifact_by_name.get(artifact_name)
        expected_type = PREDICATE_ARTIFACT_TYPES.get(predicate)
        if artifact is None:
            errors.append(
                f"{label}: evidence.graph[{index}] references unknown artifact {artifact_name!r}"
            )
        elif expected_type is not None and artifact.get("type") != expected_type:
            errors.append(
                f"{label}: evidence predicate {predicate!r} must reference a {expected_type!r} artifact"
            )
        if predicate != "vulnerability-scan" and edge.get("result") != "pass":
            errors.append(f"{label}: evidence predicate {predicate!r} must pass")
    if seen_predicates != set(PREDICATE_ARTIFACT_TYPES):
        errors.append(f"{label}: evidence graph must cover every required predicate exactly once")
    qualification_epoch = aware_timestamp(evidence.get("qualification_epoch"))
    created_at = aware_timestamp(obj.get("created_at"))
    if qualification_epoch is None:
        errors.append(f"{label}: qualification_epoch must be timezone-aware RFC3339")
    if created_at is None:
        errors.append(f"{label}: created_at must be timezone-aware RFC3339")
    if qualification_epoch and created_at and qualification_epoch > created_at:
        errors.append(f"{label}: qualification_epoch may not be later than created_at")

    chain = obj.get("attestations")
    if not isinstance(chain, dict):
        errors.append(f"{label}: attestations must identify build, qualification, and deployment evidence")
    else:
        build = chain.get("build")
        qualification = chain.get("qualification")
        deployment = chain.get("deployment")
        workflow_ref = (
            deployment.get("signer_workflow_ref", "")
            if isinstance(deployment, dict)
            else ""
        )
        for name, item in (("build", build), ("qualification", qualification)):
            if not attestor_ref(item):
                errors.append(f"{label}: attestations.{name} must identify project and attestor")
        if not attestor_ref(deployment) or not SIGNER_WORKFLOW_REF.fullmatch(str(workflow_ref)):
            errors.append(
                f"{label}: attestations.deployment must identify project, attestor, and immutable signer workflow"
            )
        elif workflow_ref != args.expected_signer_workflow_ref:
            errors.append(
                f"{label}: deployment signer is not the trusted workflow {args.expected_signer_workflow_ref}"
            )
        if all(attestor_ref(item) for item in (build, qualification, deployment)):
            roots = {(item["project"], item["attestor"]) for item in (build, qualification, deployment)}
            if len(roots) != 3:
                errors.append(f"{label}: build, qualification, and deployment attestor roots must be distinct")
        if attestor_ref(deployment):
            if (
                args.expected_deployment_attestor_project is not None
                and deployment.get("project") != args.expected_deployment_attestor_project
            ):
                errors.append(f"{label}: deployment attestor project does not match the configured trust root")
            if (
                args.expected_deployment_attestor is not None
                and deployment.get("attestor") != args.expected_deployment_attestor
            ):
                errors.append(f"{label}: deployment attestor does not match the configured trust root")

    compatibility = obj.get("compatibility") if isinstance(obj.get("compatibility"), dict) else {}
    capabilities = compatibility.get("required_capabilities")
    if isinstance(capabilities, list) and capabilities != sorted(capabilities):
        errors.append(f"{label}: required_capabilities must be sorted")

    migration = obj.get("migration") if isinstance(obj.get("migration"), dict) else {}
    migration_artifact = migration.get("artifact")
    if migration.get("required") is True:
        if artifact_by_name.get(str(migration_artifact), {}).get("type") != "migration":
            errors.append(f"{label}: a required migration must reference a migration artifact")
    elif migration_artifact is not None:
        errors.append(f"{label}: migration.artifact must be null when migration is not required")

    rollback = obj.get("rollback") if isinstance(obj.get("rollback"), dict) else {}
    rollback_artifact = artifact_by_name.get(str(rollback.get("artifact")))
    if rollback_artifact is None or rollback_artifact.get("type") != "rollback":
        errors.append(f"{label}: rollback must reference the typed rollback artifact")
    previous_release = rollback.get("previous_release_id")
    previous_digest = rollback.get("previous_subject_digest")
    if rollback.get("strategy") == "previous-release":
        if not nonempty(previous_release) or not SHA256.fullmatch(str(previous_digest)):
            errors.append(
                f"{label}: previous-release rollback requires an exact prior release ID and subject digest"
            )
    elif rollback.get("strategy") == "bootstrap":
        if previous_release is not None or previous_digest is not None:
            errors.append(f"{label}: bootstrap rollback may not claim a previous release")

    return image_values, str(obj.get("release_id", "")), subject_name + "@" + subject_digest


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    ap.add_argument("--images-file", type=Path)
    ap.add_argument("--unsigned-exceptions-file", type=Path)
    ap.add_argument("--expected-source-repository", default=DEFAULT_SOURCE_REPOSITORY)
    ap.add_argument("--expected-signer-workflow-ref", default=DEFAULT_SIGNER_WORKFLOW_REF)
    ap.add_argument("--expected-deployment-attestor-project")
    ap.add_argument("--expected-deployment-attestor")
    args = ap.parse_args()
    root = args.root.resolve()
    errors: list[str] = []
    records: dict[str, str] = {}
    release_ids: dict[str, str] = {}
    subjects: dict[str, str] = {}
    unsigned_images = governed_exception_images(args.unsigned_exceptions_file, errors)
    if not MINDCLADE_REPOSITORY.fullmatch(str(args.expected_source_repository)):
        errors.append("--expected-source-repository must name one Mindclade repository")
    if not SIGNER_WORKFLOW_REF.fullmatch(str(args.expected_signer_workflow_ref)):
        errors.append("--expected-signer-workflow-ref must name an immutable Mindclade signer release")
    if args.expected_deployment_attestor_project is not None and not nonempty(args.expected_deployment_attestor_project):
        errors.append("--expected-deployment-attestor-project may not be empty")
    if args.expected_deployment_attestor is not None and not nonempty(args.expected_deployment_attestor):
        errors.append("--expected-deployment-attestor may not be empty")

    schema_path = root / "contracts/release-metadata.schema.json"
    schema_validator = None
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator.check_schema(schema)
        schema_validator = jsonschema.Draft202012Validator(
            schema, format_checker=jsonschema.FormatChecker()
        )
        schema_required = set(schema.get("required") or [])
        schema_version = ((schema.get("properties") or {}).get("contract_version") or {}).get("const")
        if schema_version != "4.0.0":
            errors.append(f"{schema_path}: contract_version const must be 4.0.0")
        if schema_required != REQUIRED:
            errors.append(f"{schema_path}: required fields do not match validator contract")
    except Exception as exc:
        errors.append(f"{schema_path}: invalid or missing schema: {exc}")

    release_root = root / "releases"
    paths = sorted(release_root.rglob("*.json")) if release_root.exists() else []
    for path in paths:
        try:
            obj = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            errors.append(f"{path}: invalid JSON: {exc}")
            continue
        if not isinstance(obj, dict):
            errors.append(f"{path}: release metadata must be an object")
            continue
        if schema_validator is not None:
            for failure in sorted(schema_validator.iter_errors(obj), key=lambda item: list(item.path)):
                location = ".".join(str(part) for part in failure.path) or "<root>"
                errors.append(f"{path}: schema violation at {location}: {failure.message}")
        missing = REQUIRED - set(obj)
        if missing:
            errors.append(f"{path}: missing {sorted(missing)}")
        images, release_id, subject = validate_record(path, obj, args, errors)
        relative = str(path.relative_to(root))
        if release_id in release_ids:
            errors.append(f"{path}: duplicate release_id also declared by {release_ids[release_id]}")
        release_ids[release_id] = relative
        if subject in subjects:
            errors.append(f"{path}: duplicate release subject also declared by {subjects[subject]}")
        subjects[subject] = relative
        for image in images:
            if image in records:
                errors.append(f"{path}: duplicate release record for {image}")
            records[image] = relative

    if args.images_file:
        try:
            images = [line.strip() for line in args.images_file.read_text().splitlines() if line.strip()]
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
    print(f"release metadata validation passed ({len(paths)} record(s), {len(records)} image(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
