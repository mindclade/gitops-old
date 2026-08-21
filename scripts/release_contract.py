#!/usr/bin/env python3
# Copyright © 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

"""Shared fail-closed release-evidence projection and policy validation."""

from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import re
from pathlib import Path
from typing import Any


PRODUCER_SCHEMA_VERSION = "mindclade.dev/release-evidence/v1"
CONSUMER_CONTRACT_VERSION = "4.0.0"
SHA40 = re.compile(r"[0-9a-f]{40}")
SHA256 = re.compile(r"sha256:[0-9a-f]{64}")
DIGEST_IMAGE = re.compile(r"[^\s]+@sha256:[0-9a-f]{64}")
IDENTIFIER = re.compile(r"[a-z][a-z0-9-]{1,62}")
PROJECT = re.compile(r"[a-z][a-z0-9-]{4,28}[a-z0-9]")
WORKFLOW = re.compile(
    r"mindclade/\.github/\.github/workflows/[a-z0-9-]+\.yml@refs/tags/"
    r"v[0-9]+\.[0-9]+\.[0-9]+"
)
PRODUCER_REQUIRED = {
    "schema_version",
    "release_id",
    "release_kind",
    "subject",
    "source_repository",
    "source_revision",
    "builder_identity",
    "build_invocation_id",
    "images",
    "artifacts",
    "vulnerability",
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
EXCEPTION_FIELDS = {
    "ticket",
    "approved_by",
    "approved_at",
    "expires_at",
    "justification",
}


def canonical_bytes(value: dict[str, Any]) -> bytes:
    """Return the producer's deterministic, whitespace-independent JSON encoding."""

    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def canonical_digest(value: dict[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(canonical_bytes(value)).hexdigest()


def aware_timestamp(value: object, label: str, errors: list[str]) -> dt.datetime | None:
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        errors.append(f"{label} must be a timezone-aware RFC3339 timestamp")
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        errors.append(f"{label} must be a timezone-aware RFC3339 timestamp")
        return None
    return parsed


def nonempty(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def load_policy(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("release handoff policy must be one JSON object")
    expected = {
        "producer_schema_version",
        "consumer_contract_version",
        "source_repository",
        "signer_workflow_refs",
        "evidence_retention",
        "vulnerability_exception",
    }
    if set(value) != expected:
        raise ValueError(f"release handoff policy fields must be exactly {sorted(expected)}")
    if value.get("producer_schema_version") != PRODUCER_SCHEMA_VERSION:
        raise ValueError("release handoff policy has an unsupported producer schema")
    if value.get("consumer_contract_version") != CONSUMER_CONTRACT_VERSION:
        raise ValueError("release handoff policy has an unsupported consumer contract")
    refs = value.get("signer_workflow_refs")
    if not isinstance(refs, dict) or set(refs) != {"build", "qualification", "deployment"}:
        raise ValueError("release handoff policy must bind all three signer workflows")
    for name, ref in refs.items():
        if not WORKFLOW.fullmatch(str(ref)):
            raise ValueError(f"release handoff policy has a mutable {name} workflow")
    if value.get("evidence_retention") != {
        "nonproduction": "P1Y",
        "production": "P7Y",
    }:
        raise ValueError("release evidence retention must be P1Y nonproduction and P7Y production")
    exception = value.get("vulnerability_exception")
    if exception != {"approved_by": "@mindclade/security", "maximum_duration_days": 90}:
        raise ValueError("release vulnerability exception policy is not the governed 90-day policy")
    return value


def safe_evidence_path(root: Path, value: object) -> Path:
    text = str(value or "")
    relative = Path(text)
    if (
        not text.startswith("evidence/")
        or relative.suffix != ".json"
        or relative.is_absolute()
        or ".." in relative.parts
        or "\\" in text
    ):
        raise ValueError("producer evidence path must be a safe evidence/*.json path")
    resolved = (root / relative).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError("producer evidence path escapes the repository root") from exc
    return resolved


def validate_vulnerability(
    value: object,
    *,
    subject_digest: str,
    created_at: dt.datetime | None,
    policy: dict[str, Any],
    consumer: bool,
) -> list[str]:
    """Validate Critical/High blocking and the one bounded exception shape."""

    errors: list[str] = []
    if not isinstance(value, dict):
        return ["vulnerability must be one object"]
    expected = {
        "result",
        "scanner",
        "scanner_version",
        "database_digest",
        "scanned_at",
        "finding_counts",
        "exception",
    }
    if set(value) != expected:
        errors.append(f"vulnerability fields must be exactly {sorted(expected)}")
    if not IDENTIFIER.fullmatch(str(value.get("scanner", ""))):
        errors.append("vulnerability scanner must be a stable identifier")
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", str(value.get("scanner_version", ""))):
        errors.append("vulnerability scanner_version must be semantic versioning")
    if not SHA256.fullmatch(str(value.get("database_digest", ""))):
        errors.append("vulnerability database_digest must be one SHA-256 digest")
    scanned_at = aware_timestamp(value.get("scanned_at"), "vulnerability.scanned_at", errors)
    if scanned_at and created_at and scanned_at > created_at:
        errors.append("vulnerability.scanned_at may not be later than created_at")

    counts = value.get("finding_counts")
    severities = {"critical", "high", "medium", "low", "unknown"}
    if not isinstance(counts, dict) or set(counts) != severities:
        errors.append(f"vulnerability finding_counts must contain exactly {sorted(severities)}")
        counts = {}
    for severity in severities:
        count = counts.get(severity)
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            errors.append(f"vulnerability finding_counts.{severity} must be a non-negative integer")

    result = value.get("result")
    exception = value.get("exception")
    critical = counts.get("critical", 0)
    high = counts.get("high", 0)
    unknown = counts.get("unknown", 0)
    if result == "pass":
        if critical != 0 or high != 0 or unknown != 0:
            errors.append("passing vulnerability evidence requires zero critical, high, and unknown findings")
        if exception is not None:
            errors.append("passing vulnerability evidence may not include an exception")
    elif result == "approved-exception":
        if unknown != 0:
            errors.append("unknown vulnerability findings cannot be excepted")
        if critical + high == 0:
            errors.append("a vulnerability exception requires at least one critical or high finding")
        if not isinstance(exception, dict):
            errors.append("approved vulnerability evidence requires one exception object")
        else:
            expected_exception = set(EXCEPTION_FIELDS)
            if consumer:
                expected_exception.add("subject_digest")
            if set(exception) != expected_exception:
                errors.append(
                    "vulnerability exception fields must be exactly "
                    f"{sorted(expected_exception)}"
                )
            exception_policy = policy["vulnerability_exception"]
            if exception.get("approved_by") != exception_policy["approved_by"]:
                errors.append("vulnerability exception requires @mindclade/security approval")
            for field in ("ticket", "justification"):
                if not nonempty(exception.get(field)):
                    errors.append(f"vulnerability exception {field} is required")
            if consumer and exception.get("subject_digest") != subject_digest:
                errors.append("vulnerability exception must bind the exact release subject digest")
            approved = aware_timestamp(
                exception.get("approved_at"), "vulnerability.exception.approved_at", errors
            )
            expires = aware_timestamp(
                exception.get("expires_at"), "vulnerability.exception.expires_at", errors
            )
            maximum = dt.timedelta(days=exception_policy["maximum_duration_days"])
            if approved and expires and (expires <= approved or expires - approved > maximum):
                errors.append("vulnerability exception must expire within 90 days")
            if approved and created_at and approved > created_at:
                errors.append("vulnerability exception may not be approved after created_at")
            if expires and created_at and expires <= created_at:
                errors.append("vulnerability exception must be active when the release is created")
    else:
        errors.append("vulnerability.result must be pass or approved-exception")
    return errors


def validate_producer_evidence(
    value: object, policy: dict[str, Any]
) -> list[str]:
    """Defensively validate the versioned monorepo handoff before projection."""

    if not isinstance(value, dict):
        return ["producer release evidence must be one JSON object"]
    errors: list[str] = []
    if set(value) != PRODUCER_REQUIRED:
        errors.append(f"producer release evidence fields must be exactly {sorted(PRODUCER_REQUIRED)}")
    if value.get("schema_version") != policy["producer_schema_version"]:
        errors.append("producer release evidence has an unsupported schema_version")
    if value.get("source_repository") != policy["source_repository"]:
        errors.append("producer release evidence is not from the trusted monorepo")
    if not SHA40.fullmatch(str(value.get("source_revision", ""))):
        errors.append("producer source_revision must be one full commit SHA")
    for field in ("release_id", "builder_identity", "build_invocation_id"):
        if not nonempty(value.get(field)):
            errors.append(f"producer {field} must be non-empty")

    subject = value.get("subject") if isinstance(value.get("subject"), dict) else {}
    subject_digest = str(subject.get("digest", ""))
    if not SHA256.fullmatch(subject_digest):
        errors.append("producer subject.digest must be one SHA-256 digest")
    images = value.get("images") if isinstance(value.get("images"), dict) else {}
    if not images:
        errors.append("producer release evidence must contain at least one named image")
    if list(images) != sorted(images):
        errors.append("producer images must be sorted by name")
    if len(set(map(str, images.values()))) != len(images):
        errors.append("producer images must not duplicate an immutable reference")
    for name, image in images.items():
        if not IDENTIFIER.fullmatch(str(name)) or not DIGEST_IMAGE.fullmatch(str(image)):
            errors.append(f"producer image {name!r} is not a named immutable digest")

    artifacts = value.get("artifacts") if isinstance(value.get("artifacts"), list) else []
    artifact_names: list[str] = []
    artifact_by_name: dict[str, dict[str, Any]] = {}
    artifact_types: dict[str, list[str]] = {}
    for index, artifact in enumerate(artifacts):
        if not isinstance(artifact, dict):
            errors.append(f"producer artifacts[{index}] must be an object")
            continue
        if set(artifact) != {"name", "type", "uri", "digest", "media_type"}:
            errors.append(f"producer artifacts[{index}] has unsupported or missing fields")
        name = str(artifact.get("name", ""))
        artifact_type = str(artifact.get("type", ""))
        if name in artifact_by_name:
            errors.append(f"producer duplicates artifact {name!r}")
        artifact_names.append(name)
        artifact_by_name[name] = artifact
        artifact_types.setdefault(artifact_type, []).append(name)
        if not SHA256.fullmatch(str(artifact.get("digest", ""))):
            errors.append(f"producer artifact {name!r} lacks a SHA-256 digest")
        if not re.match(r"^(?:gs|https|oci)://.+$", str(artifact.get("uri", ""))):
            errors.append(f"producer artifact {name!r} has an invalid immutable URI")
    if artifact_names != sorted(artifact_names):
        errors.append("producer artifacts must be sorted by name")
    for artifact_type in sorted(REQUIRED_ARTIFACT_TYPES):
        if len(artifact_types.get(artifact_type, [])) != 1:
            errors.append(f"producer must contain exactly one {artifact_type!r} artifact")

    evidence = value.get("evidence") if isinstance(value.get("evidence"), dict) else {}
    if evidence.get("result") != "pass":
        errors.append("producer evidence.result must be pass")
    graph = evidence.get("graph") if isinstance(evidence.get("graph"), list) else []
    predicates: set[str] = set()
    for index, edge in enumerate(graph):
        if not isinstance(edge, dict):
            errors.append(f"producer evidence.graph[{index}] must be an object")
            continue
        predicate = str(edge.get("predicate_type", ""))
        if predicate in predicates:
            errors.append(f"producer duplicates evidence predicate {predicate!r}")
        predicates.add(predicate)
        if edge.get("subject_digest") != subject_digest:
            errors.append(f"producer evidence predicate {predicate!r} does not bind the subject")
        artifact = artifact_by_name.get(str(edge.get("artifact", "")))
        if artifact is None or artifact.get("type") != PREDICATE_ARTIFACT_TYPES.get(predicate):
            errors.append(f"producer evidence predicate {predicate!r} references the wrong artifact")
        expected_result = (
            "approved"
            if predicate == "vulnerability-scan"
            and (value.get("vulnerability") or {}).get("result") == "approved-exception"
            else "pass"
        )
        if edge.get("result") != expected_result:
            errors.append(f"producer evidence predicate {predicate!r} must be {expected_result}")
    if predicates != set(PREDICATE_ARTIFACT_TYPES):
        errors.append("producer evidence graph must cover each required predicate exactly once")

    created_at = aware_timestamp(value.get("created_at"), "producer created_at", errors)
    qualification_epoch = aware_timestamp(
        evidence.get("qualification_epoch"), "producer qualification_epoch", errors
    )
    if qualification_epoch and created_at and qualification_epoch > created_at:
        errors.append("producer qualification_epoch may not be later than created_at")
    errors.extend(
        validate_vulnerability(
            value.get("vulnerability"),
            subject_digest=subject_digest,
            created_at=created_at,
            policy=policy,
            consumer=False,
        )
    )

    attestations = value.get("attestations")
    if not isinstance(attestations, dict) or set(attestations) != {"build", "qualification"}:
        errors.append("producer attestations must contain exactly build and qualification")
    else:
        roots: set[tuple[str, str]] = set()
        for name in ("build", "qualification"):
            ref = attestations.get(name)
            if not isinstance(ref, dict) or set(ref) != {"project", "attestor"}:
                errors.append(f"producer attestations.{name} has an invalid shape")
                continue
            project = str(ref.get("project", ""))
            attestor = str(ref.get("attestor", ""))
            if not PROJECT.fullmatch(project) or not IDENTIFIER.fullmatch(attestor):
                errors.append(f"producer attestations.{name} has an invalid identity")
            roots.add((project, attestor))
        if len(roots) != 2:
            errors.append("producer build and qualification attestor roots must be distinct")

    compatibility = value.get("compatibility") if isinstance(value.get("compatibility"), dict) else {}
    capabilities = compatibility.get("required_capabilities")
    if not isinstance(capabilities, list) or capabilities != sorted(capabilities) or len(capabilities) != len(set(map(str, capabilities))):
        errors.append("producer required_capabilities must be a sorted unique list")

    migration = value.get("migration") if isinstance(value.get("migration"), dict) else {}
    migration_artifact = artifact_by_name.get(str(migration.get("artifact")))
    if migration.get("required") is True:
        if migration_artifact is None or migration_artifact.get("type") != "migration":
            errors.append("producer required migration must reference one migration artifact")
    elif migration.get("artifact") is not None:
        errors.append("producer migration artifact must be null when migration is not required")
    rollback = value.get("rollback") if isinstance(value.get("rollback"), dict) else {}
    rollback_artifact = artifact_by_name.get(str(rollback.get("artifact")))
    if rollback_artifact is None or rollback_artifact.get("type") != "rollback":
        errors.append("producer rollback must reference one rollback artifact")
    previous_release = rollback.get("previous_release_id")
    previous_digest = rollback.get("previous_subject_digest")
    if rollback.get("strategy") == "previous-release":
        if not nonempty(previous_release) or not SHA256.fullmatch(str(previous_digest)):
            errors.append("producer previous-release rollback requires exact prior lineage")
    elif rollback.get("strategy") == "bootstrap" and (
        previous_release is not None or previous_digest is not None
    ):
        errors.append("producer bootstrap rollback may not claim prior lineage")
    return sorted(set(errors))


def project_release_evidence(
    producer: dict[str, Any],
    *,
    evidence_path: str,
    deployment_project: str,
    deployment_attestor: str,
    policy: dict[str, Any],
) -> dict[str, Any]:
    """Deterministically project producer v1 into the GitOps 4.0.0 consumer."""

    errors = validate_producer_evidence(producer, policy)
    if errors:
        raise ValueError("invalid producer release evidence: " + "; ".join(errors))
    if not PROJECT.fullmatch(deployment_project) or not IDENTIFIER.fullmatch(deployment_attestor):
        raise ValueError("deployment attestor project and name must be stable identifiers")
    record = copy.deepcopy(producer)
    schema_version = str(record.pop("schema_version"))
    record["contract_version"] = policy["consumer_contract_version"]
    record["producer_evidence"] = {
        "schema_version": schema_version,
        "path": evidence_path,
        "digest": canonical_digest(producer),
    }
    exception = (record.get("vulnerability") or {}).get("exception")
    if isinstance(exception, dict):
        exception["subject_digest"] = record["subject"]["digest"]
    workflow_refs = policy["signer_workflow_refs"]
    record["attestations"]["build"]["signer_workflow_ref"] = workflow_refs["build"]
    record["attestations"]["qualification"]["signer_workflow_ref"] = workflow_refs[
        "qualification"
    ]
    record["attestations"]["deployment"] = {
        "project": deployment_project,
        "attestor": deployment_attestor,
        "signer_workflow_ref": workflow_refs["deployment"],
    }
    record["evidence_retention"] = copy.deepcopy(policy["evidence_retention"])
    return record


def projection_errors(
    root: Path,
    consumer: dict[str, Any],
    policy: dict[str, Any],
) -> list[str]:
    """Prove a consumer record is the exact projection of its immutable producer input."""

    producer_ref = consumer.get("producer_evidence")
    if not isinstance(producer_ref, dict):
        return ["producer_evidence must identify the immutable producer input"]
    try:
        producer_path = safe_evidence_path(root, producer_ref.get("path"))
        producer = json.loads(producer_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return [f"cannot load producer release evidence: {exc}"]
    if not isinstance(producer, dict):
        return ["producer release evidence must be one JSON object"]
    errors = validate_producer_evidence(producer, policy)
    actual_digest = canonical_digest(producer)
    if producer_ref.get("digest") != actual_digest:
        errors.append("producer_evidence.digest does not match canonical producer bytes")
    try:
        deployment = consumer.get("attestations", {}).get("deployment", {})
        expected = project_release_evidence(
            producer,
            evidence_path=str(producer_ref.get("path", "")),
            deployment_project=str(deployment.get("project", "")),
            deployment_attestor=str(deployment.get("attestor", "")),
            policy=policy,
        )
    except (AttributeError, TypeError, ValueError) as exc:
        errors.append(str(exc))
    else:
        if consumer != expected:
            errors.append("release metadata is not the exact deterministic producer projection")
    return sorted(set(errors))


def active_exception_errors(
    record: dict[str, Any], as_of: dt.datetime
) -> list[str]:
    """Reject selection of a record after its bounded vulnerability exception expires."""

    vulnerability = record.get("vulnerability")
    if not isinstance(vulnerability, dict) or vulnerability.get("result") != "approved-exception":
        return []
    exception = vulnerability.get("exception")
    if not isinstance(exception, dict):
        return ["selected release has malformed vulnerability exception"]
    errors: list[str] = []
    expires = aware_timestamp(
        exception.get("expires_at"), "vulnerability.exception.expires_at", errors
    )
    if expires is not None and expires <= as_of:
        errors.append("selected release vulnerability exception is expired")
    return errors
