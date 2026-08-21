#!/usr/bin/env python3
# Copyright © 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

"""Validate immutable deployment release evidence without contacting external services."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import sys
from pathlib import Path

import yaml

from release_contract import (
    load_policy,
    projection_errors,
    validate_vulnerability,
)

try:
    import jsonschema
except ImportError:
    print("jsonschema is required from the pinned repository toolchain", file=sys.stderr)
    raise SystemExit(2)


SHA40 = re.compile(r"[0-9a-f]{40}")
DIGEST_IMAGE = re.compile(r"[^\s]+@sha256:[0-9a-f]{64}")
SHA256 = re.compile(r"sha256:[0-9a-f]{64}")
MINDCLADE_REPOSITORY = re.compile(r"mindclade/[A-Za-z0-9_.-]+")
SIGNER_WORKFLOW_REFS = {
    "build": re.compile(
        r"mindclade/\.github/\.github/workflows/reusable-arc-oci-build\.yml@refs/tags/v[0-9]+\.[0-9]+\.[0-9]+"
    ),
    "qualification": re.compile(
        r"mindclade/\.github/\.github/workflows/reusable-arc-qualification-attest\.yml@refs/tags/v[0-9]+\.[0-9]+\.[0-9]+"
    ),
    "deployment": re.compile(
        r"mindclade/\.github/\.github/workflows/reusable-binauthz-sign\.yml@refs/tags/v[0-9]+\.[0-9]+\.[0-9]+"
    ),
}
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
PREDICATE_ARTIFACT_TYPES = {
    "build-provenance": "provenance",
    "qualification": "qualification",
    "sbom": "sbom",
    "vulnerability-scan": "vulnerability-scan",
}
REQUIRED_ARTIFACT_TYPES = set(PREDICATE_ARTIFACT_TYPES.values()) | {"rollback"}
DEFAULT_SOURCE_REPOSITORY = "mindclade/mindclade-internal-monorepo"
DEFAULT_BUILD_SIGNER_WORKFLOW_REF = (
    "mindclade/.github/.github/workflows/reusable-arc-oci-build.yml@refs/tags/v4.0.0"
)
DEFAULT_QUALIFICATION_SIGNER_WORKFLOW_REF = (
    "mindclade/.github/.github/workflows/"
    "reusable-arc-qualification-attest.yml@refs/tags/v4.0.0"
)
DEFAULT_DEPLOYMENT_SIGNER_WORKFLOW_REF = (
    "mindclade/.github/.github/workflows/reusable-binauthz-sign.yml@refs/tags/v4.0.0"
)
QUARANTINED_V3_SCHEMA_SHA256 = (
    "4e40da787e7fec209721f4a111d501198c52b379b575d46a6672df8a5c77b783"
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


def validate_quarantined_v3_contract(
    root: Path,
    images_file: Path | None,
    policy_path: Path,
    unsigned_images: set[str],
    errors: list[str],
) -> bool:
    """Recognize the exact inert v3 rollback without weakening active v4 validation."""

    schema_path = root / "contracts/release-metadata.schema.json"
    try:
        schema_bytes = schema_path.read_bytes()
        schema = json.loads(schema_bytes)
    except (OSError, json.JSONDecodeError):
        return False
    schema_version = (
        ((schema.get("properties") or {}).get("contract_version") or {}).get("const")
        if isinstance(schema, dict)
        else None
    )
    if schema_version != "3.0.0":
        return False

    if hashlib.sha256(schema_bytes).hexdigest() != QUARANTINED_V3_SCHEMA_SHA256:
        errors.append(f"{schema_path}: quarantined v3 schema does not match the reviewed bytes")
    if policy_path.exists():
        errors.append(
            f"{policy_path}: v4 release handoff policy must be absent from the v3 quarantine"
        )
    release_paths = sorted((root / "releases").rglob("*.json"))
    if release_paths:
        errors.append("quarantined v3 contract may not contain release metadata records")

    for environment in ("development", "staging", "production"):
        path = root / "deployments" / f"{environment}.yaml"
        try:
            document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError) as exc:
            errors.append(f"{path}: cannot read the quarantine deployment envelope: {exc}")
            continue
        if document.get("apiVersion") != "mindclade.dev/v2" or document.get(
            "kind"
        ) != "ArtifactDeploymentSet":
            errors.append(f"{path}: quarantine deployment envelope must use mindclade.dev/v2")
        metadata = document.get("metadata") or {}
        spec = document.get("spec") or {}
        if metadata.get("name") != environment or spec.get("environment") != environment:
            errors.append(f"{path}: quarantine deployment envelope identity is invalid")
        if spec.get("applications") != []:
            errors.append(f"{path}: quarantine deployment envelope must remain empty")

    if images_file is None:
        errors.append("quarantined v3 validation requires the complete active-image projection")
        active_images: set[str] = set()
    else:
        try:
            images = [
                line.strip()
                for line in images_file.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        except OSError as exc:
            errors.append(f"cannot read images file: {exc}")
            images = []
        active_images = set(images)
        if len(active_images) != len(images):
            errors.append("active-image projection contains duplicates")
    for image in sorted(active_images - unsigned_images):
        errors.append(f"v3 quarantine contains a release-bound active image: {image}")
    for image in sorted(unsigned_images - active_images):
        errors.append(f"unsigned exception is not an active control-plane image: {image}")
    return True


def validate_record(
    path: Path,
    obj: dict,
    args: argparse.Namespace,
    policy: dict,
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
        expected_result = (
            "approved"
            if predicate == "vulnerability-scan"
            and (obj.get("vulnerability") or {}).get("result") == "approved-exception"
            else "pass"
        )
        if edge.get("result") != expected_result:
            errors.append(
                f"{label}: evidence predicate {predicate!r} must be {expected_result}"
            )
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
    for failure in validate_vulnerability(
        obj.get("vulnerability"),
        subject_digest=subject_digest,
        created_at=created_at,
        policy=policy,
        consumer=True,
    ):
        errors.append(f"{label}: {failure}")

    chain = obj.get("attestations")
    if not isinstance(chain, dict):
        errors.append(f"{label}: attestations must identify build, qualification, and deployment evidence")
    else:
        build = chain.get("build")
        qualification = chain.get("qualification")
        deployment = chain.get("deployment")
        expected_workflows = {
            "build": args.expected_build_signer_workflow_ref,
            "qualification": args.expected_qualification_signer_workflow_ref,
            "deployment": args.expected_deployment_signer_workflow_ref,
        }
        for name, item in (
            ("build", build),
            ("qualification", qualification),
            ("deployment", deployment),
        ):
            workflow_ref = (
                item.get("signer_workflow_ref", "") if isinstance(item, dict) else ""
            )
            if not attestor_ref(item) or not SIGNER_WORKFLOW_REFS[name].fullmatch(
                str(workflow_ref)
            ):
                errors.append(
                    f"{label}: attestations.{name} must identify project, attestor, and immutable signer workflow"
                )
            elif workflow_ref != expected_workflows[name]:
                errors.append(
                    f"{label}: {name} signer is not the trusted workflow {expected_workflows[name]}"
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

    if obj.get("evidence_retention") != policy["evidence_retention"]:
        errors.append(
            f"{label}: evidence retention must be P1Y nonproduction and P7Y production"
        )

    return image_values, str(obj.get("release_id", "")), subject_name + "@" + subject_digest


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    ap.add_argument("--images-file", type=Path)
    ap.add_argument("--unsigned-exceptions-file", type=Path)
    ap.add_argument("--handoff-policy", type=Path)
    ap.add_argument("--expected-source-repository", default=DEFAULT_SOURCE_REPOSITORY)
    ap.add_argument(
        "--expected-build-signer-workflow-ref",
        default=DEFAULT_BUILD_SIGNER_WORKFLOW_REF,
    )
    ap.add_argument(
        "--expected-qualification-signer-workflow-ref",
        default=DEFAULT_QUALIFICATION_SIGNER_WORKFLOW_REF,
    )
    ap.add_argument(
        "--expected-deployment-signer-workflow-ref",
        default=DEFAULT_DEPLOYMENT_SIGNER_WORKFLOW_REF,
    )
    ap.add_argument("--expected-deployment-attestor-project")
    ap.add_argument("--expected-deployment-attestor")
    args = ap.parse_args()
    root = args.root.resolve()
    errors: list[str] = []
    records: dict[str, str] = {}
    release_ids: dict[str, str] = {}
    subjects: dict[str, str] = {}
    unsigned_images = governed_exception_images(args.unsigned_exceptions_file, errors)
    policy_path = args.handoff_policy or root / "contracts/release-handoff-policy.json"
    if validate_quarantined_v3_contract(
        root,
        args.images_file,
        policy_path,
        unsigned_images,
        errors,
    ):
        if errors:
            for error in sorted(set(errors)):
                print(f"ERROR: {error}", file=sys.stderr)
            return 1
        print("release metadata validation passed (quarantined v3 contract; 0 records)")
        return 0
    try:
        policy = load_policy(policy_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        errors.append(f"{policy_path}: invalid or missing release handoff policy: {exc}")
        policy = {
            "producer_schema_version": "mindclade.dev/release-evidence/v1",
            "consumer_contract_version": "4.0.0",
            "source_repository": DEFAULT_SOURCE_REPOSITORY,
            "signer_workflow_refs": {
                "build": DEFAULT_BUILD_SIGNER_WORKFLOW_REF,
                "qualification": DEFAULT_QUALIFICATION_SIGNER_WORKFLOW_REF,
                "deployment": DEFAULT_DEPLOYMENT_SIGNER_WORKFLOW_REF,
            },
            "evidence_retention": {"nonproduction": "P1Y", "production": "P7Y"},
            "vulnerability_exception": {
                "approved_by": "@mindclade/security",
                "maximum_duration_days": 90,
            },
        }
    if not MINDCLADE_REPOSITORY.fullmatch(str(args.expected_source_repository)):
        errors.append("--expected-source-repository must name one Mindclade repository")
    elif args.expected_source_repository != policy["source_repository"]:
        errors.append("--expected-source-repository does not match the release handoff policy")
    for name, workflow_ref in (
        ("build", args.expected_build_signer_workflow_ref),
        ("qualification", args.expected_qualification_signer_workflow_ref),
        ("deployment", args.expected_deployment_signer_workflow_ref),
    ):
        if not SIGNER_WORKFLOW_REFS[name].fullmatch(str(workflow_ref)):
            errors.append(
                f"--expected-{name}-signer-workflow-ref must name an immutable Mindclade signer release"
            )
        elif workflow_ref != policy["signer_workflow_refs"][name]:
            errors.append(
                f"--expected-{name}-signer-workflow-ref does not match the release handoff policy"
            )
    if args.expected_deployment_attestor_project is not None and not nonempty(args.expected_deployment_attestor_project):
        errors.append("--expected-deployment-attestor-project may not be empty")
    if args.expected_deployment_attestor is not None and not nonempty(args.expected_deployment_attestor):
        errors.append("--expected-deployment-attestor may not be empty")

    schema_path = root / "contracts/release-metadata.schema.json"
    schema_validator = None
    schema_version = None
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
        images, release_id, subject = validate_record(path, obj, args, policy, errors)
        for failure in projection_errors(root, obj, policy):
            errors.append(f"{path}: {failure}")
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
