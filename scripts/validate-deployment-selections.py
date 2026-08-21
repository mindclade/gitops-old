#!/usr/bin/env python3
# Copyright © 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

"""Validate environment selections that bind each application to one release record."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import sys
from pathlib import Path

import yaml

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from release_contract import active_exception_errors


ROOT = Path(__file__).resolve().parents[1]
AS_OF = dt.datetime.now(dt.timezone.utc)
ENVIRONMENTS = ("development", "staging", "production")
APP = re.compile(r"(?:platform|serving|research|data|partner)-[a-z0-9][a-z0-9-]*")
DIGEST_IMAGE = re.compile(r"[^\s]+@sha256:[0-9a-f]{64}")
SHA40 = re.compile(r"[0-9a-f]{40}")
SHA256 = re.compile(r"sha256:[0-9a-f]{64}")
RELEASE = re.compile(r"v[0-9]+\.[0-9]+\.[0-9]+")
RELEASE_KINDS = {"application", "bundle", "dataset", "model", "pipeline", "platform"}
RELEASE_IMAGE = re.compile(
    r"[a-z0-9][a-z0-9.-]*-docker\.pkg\.dev/"
    r"[a-z][a-z0-9-]{4,28}[a-z0-9]/releases/"
    r"[a-z][a-z0-9-]{1,62}@(?P<digest>sha256:[0-9a-f]{64})"
)
REQUIRED_PROPOSAL_EVIDENCE = {
    "build-attestation",
    "deployment-attestation",
    "provenance",
    "qualification-attestation",
    "release-metadata-4.0.0",
    "release-evidence-retention",
    "release-evidence-v1",
    "sbom",
    "vulnerability-scan",
}


def canonical_spec_digest(spec: dict) -> str:
    encoded = json.dumps(
        spec, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def validate_selected_proposal(
    application: str,
    release_path: str,
    record: dict,
    label: str,
    errors: list[str],
) -> None:
    """Bind every active selection to its inert, producer-authored review proposal."""

    release_id = str(record.get("release_id", ""))
    path = ROOT / "deployments/proposals" / f"{release_id}.yaml"
    try:
        proposal = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        errors.append(f"{label}: missing or unreadable promotion proposal for {release_id}: {exc}")
        return
    spec = proposal.get("spec") if isinstance(proposal, dict) else None
    target = spec.get("target") if isinstance(spec, dict) else None
    if not isinstance(target, dict):
        errors.append(f"{label}: promotion proposal has no target")
        return
    producer = record.get("producer_evidence")
    subject = record.get("subject")
    images = record.get("images")
    checks = {
        "application": application,
        "releaseKind": record.get("release_kind"),
        "releaseMetadata": release_path,
        "subjectDigest": subject.get("digest") if isinstance(subject, dict) else None,
        "producerEvidenceDigest": (
            producer.get("digest") if isinstance(producer, dict) else None
        ),
    }
    for field, expected in checks.items():
        if target.get(field) != expected:
            errors.append(f"{label}: promotion proposal {field} does not bind the selected release")
    if not isinstance(images, dict) or target.get("imageRef") not in images.values():
        errors.append(f"{label}: promotion proposal imageRef is not owned by the selected release")
    if isinstance(spec, dict) and spec.get("sourceRevision") != record.get("source_revision"):
        errors.append(f"{label}: promotion proposal sourceRevision does not bind the selected release")


def safe_release_path(value: object) -> Path | None:
    release_path = str(value or "")
    relative = Path(release_path)
    if (
        not release_path.startswith("releases/")
        or relative.suffix != ".json"
        or relative.is_absolute()
        or ".." in relative.parts
        or "\\" in release_path
    ):
        return None
    return relative


def load_selection(environment: str, errors: list[str]) -> dict[str, dict]:
    path = ROOT / "deployments" / f"{environment}.yaml"
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        errors.append(f"{path.relative_to(ROOT)}: cannot parse: {exc}")
        return {}
    if (
        document.get("apiVersion") != "mindclade.dev/v2"
        or document.get("kind") != "ArtifactDeploymentSet"
    ):
        errors.append(f"{path.relative_to(ROOT)}: invalid apiVersion/kind")
    if (document.get("metadata") or {}).get("name") != environment:
        errors.append(f"{path.relative_to(ROOT)}: metadata.name must be {environment}")
    spec = document.get("spec") or {}
    if spec.get("environment") != environment:
        errors.append(f"{path.relative_to(ROOT)}: spec.environment must be {environment}")
    raw_apps = spec.get("applications") or []
    if not isinstance(raw_apps, list):
        errors.append(f"{path.relative_to(ROOT)}: spec.applications must be a list")
        return {}
    applications: dict[str, dict] = {}
    observed_names: list[str] = []
    observed_records: set[str] = set()
    for index, application in enumerate(raw_apps):
        label = f"{path.relative_to(ROOT)} applications[{index}]"
        if not isinstance(application, dict):
            errors.append(f"{label}: must be an object")
            continue
        extra = set(application) - {"name", "releaseMetadata"}
        missing = {"name", "releaseMetadata"} - set(application)
        if extra:
            errors.append(f"{label}: unsupported fields {sorted(extra)}")
        if missing:
            errors.append(f"{label}: missing fields {sorted(missing)}")
        name = str(application.get("name", ""))
        if not APP.fullmatch(name):
            errors.append(f"{label}: invalid application name {name!r}")
        if name in applications:
            errors.append(f"{label}: duplicate application {name}")
        applications[name] = application
        observed_names.append(name)

        relative = safe_release_path(application.get("releaseMetadata"))
        if relative is None:
            errors.append(f"{label}: releaseMetadata must be a safe releases/*.json path")
            continue
        relative_text = relative.as_posix()
        if relative_text in observed_records:
            errors.append(f"{label}: release record is already selected by another application")
        observed_records.add(relative_text)
        record_path = ROOT / relative
        try:
            record = json.loads(record_path.read_text(encoding="utf-8"))
        except Exception as exc:
            errors.append(f"{label}: cannot read release record: {exc}")
            continue
        if not isinstance(record, dict) or record.get("contract_version") != "4.0.0":
            errors.append(f"{label}: release record must use contract 4.0.0")
            continue
        subject = record.get("subject") or {}
        if not isinstance(subject, dict) or subject.get("name") != name:
            errors.append(f"{label}: release record subject does not bind application {name!r}")
        images = record.get("images") or {}
        if not isinstance(images, dict) or not images:
            errors.append(f"{label}: release record must contain named images")
        elif any(not DIGEST_IMAGE.fullmatch(str(image)) for image in images.values()):
            errors.append(f"{label}: release record contains a non-immutable image")
        producer = record.get("producer_evidence")
        if (
            not isinstance(producer, dict)
            or producer.get("schema_version") != "mindclade.dev/release-evidence/v1"
            or not SHA256.fullmatch(str(producer.get("digest", "")))
        ):
            errors.append(f"{label}: release record lacks immutable producer-v1 evidence")
        if record.get("evidence_retention") != {
            "nonproduction": "P1Y",
            "production": "P7Y",
        }:
            errors.append(f"{label}: release record lacks P1Y/P7Y evidence retention")
        for failure in active_exception_errors(record, AS_OF):
            errors.append(f"{label}: {failure}")
        validate_selected_proposal(name, relative_text, record, label, errors)
    if observed_names != sorted(observed_names):
        errors.append(f"{path.relative_to(ROOT)}: applications must be sorted by name")
    return applications


def validate_promotion_proposals(errors: list[str]) -> int:
    """Reject hand-edited or incomplete promotion proposals in the review surface."""
    root = ROOT / "deployments/proposals"
    paths = sorted(root.glob("*.yaml")) if root.exists() else []
    for path in paths:
        label = str(path.relative_to(ROOT))
        try:
            document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception as exc:
            errors.append(f"{label}: cannot parse: {exc}")
            continue
        if not isinstance(document, dict):
            errors.append(f"{label}: proposal must be an object")
            continue
        if (
            document.get("apiVersion") != "release.mindclade.dev/v1beta1"
            or document.get("kind") != "PromotionProposal"
        ):
            errors.append(f"{label}: invalid apiVersion/kind")
        metadata = document.get("metadata") or {}
        release_id = str(metadata.get("name", "")) if isinstance(metadata, dict) else ""
        expected_metadata_fields = {"name", "annotations"}
        if not isinstance(metadata, dict) or set(metadata) != expected_metadata_fields:
            errors.append(f"{label}: metadata fields must be exactly {sorted(expected_metadata_fields)}")
        if not RELEASE.fullmatch(release_id) or path.stem != release_id:
            errors.append(f"{label}: metadata.name and filename must be the same vX.Y.Z release ID")
        spec = document.get("spec") or {}
        if not isinstance(spec, dict):
            errors.append(f"{label}: spec must be an object")
            continue
        expected_spec = {
            "target",
            "sourceRepository",
            "sourceRevision",
            "previousRelease",
            "targetEnvironment",
            "requiredEvidence",
        }
        if set(spec) != expected_spec:
            errors.append(f"{label}: spec fields must be exactly {sorted(expected_spec)}")
        if spec.get("sourceRepository") != "mindclade/mindclade-internal-monorepo":
            errors.append(f"{label}: sourceRepository is not the trusted producer")
        if not SHA40.fullmatch(str(spec.get("sourceRevision", ""))):
            errors.append(f"{label}: sourceRevision must be one full commit SHA")
        if spec.get("targetEnvironment") != "development":
            errors.append(f"{label}: proposals may target only development")

        target = spec.get("target") or {}
        expected_target = {
            "application",
            "releaseKind",
            "releaseMetadata",
            "imageRef",
            "subjectDigest",
            "producerEvidenceDigest",
        }
        if not isinstance(target, dict) or set(target) != expected_target:
            errors.append(f"{label}: target must contain exactly {sorted(expected_target)}")
        else:
            if not APP.fullmatch(str(target.get("application", ""))):
                errors.append(f"{label}: target application is invalid")
            if target.get("releaseKind") not in RELEASE_KINDS:
                errors.append(f"{label}: target releaseKind is unsupported")
            expected_release_path = (
                f"releases/{target.get('application')}/{release_id}.json"
            )
            if target.get("releaseMetadata") != expected_release_path:
                errors.append(f"{label}: target releaseMetadata is not the deterministic release path")
            if not SHA256.fullmatch(str(target.get("producerEvidenceDigest", ""))):
                errors.append(f"{label}: target producerEvidenceDigest must be one SHA-256 digest")
            image_match = RELEASE_IMAGE.fullmatch(str(target.get("imageRef", "")))
            if image_match is None:
                errors.append(f"{label}: target imageRef is outside the immutable releases repository")
            elif target.get("subjectDigest") != image_match.group("digest"):
                errors.append(f"{label}: target subjectDigest does not bind imageRef")

        previous = spec.get("previousRelease") or {}
        expected_previous = {"releaseId", "subjectDigest"}
        if not isinstance(previous, dict) or set(previous) != expected_previous:
            errors.append(f"{label}: previousRelease must contain exactly {sorted(expected_previous)}")
        else:
            previous_id = str(previous.get("releaseId", ""))
            previous_digest = str(previous.get("subjectDigest", ""))
            if not RELEASE.fullmatch(previous_id) or previous_id == release_id:
                errors.append(f"{label}: previousRelease.releaseId must be an exact different release")
            if not SHA256.fullmatch(previous_digest) or previous_digest == "sha256:" + "0" * 64:
                errors.append(f"{label}: previousRelease.subjectDigest must be one nonzero digest")
            if isinstance(target, dict) and previous_digest == target.get("subjectDigest"):
                errors.append(f"{label}: candidate and previous subject digests must differ")

        evidence = spec.get("requiredEvidence")
        if (
            not isinstance(evidence, list)
            or len(evidence) != len(set(map(str, evidence)))
            or set(map(str, evidence)) != REQUIRED_PROPOSAL_EVIDENCE
            or evidence != sorted(REQUIRED_PROPOSAL_EVIDENCE)
        ):
            errors.append(
                f"{label}: requiredEvidence must contain the sorted complete governed evidence set"
            )
        annotations = metadata.get("annotations") if isinstance(metadata, dict) else None
        expected_annotations = {
            "release.mindclade.dev/consumer-contract": "4.0.0",
            "release.mindclade.dev/producer-schema": "mindclade.dev/release-evidence/v1",
            "release.mindclade.dev/spec-digest": canonical_spec_digest(spec),
        }
        if annotations != expected_annotations:
            errors.append(f"{label}: metadata.annotations are not the deterministic proposal binding")
    return len(paths)


def active_targets(errors: list[str]) -> dict[str, set[str]]:
    path = ROOT / "render-manifest.yaml"
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        errors.append(f"render-manifest.yaml: cannot parse: {exc}")
        return {environment: set() for environment in ENVIRONMENTS}
    targets = (document.get("spec") or {}).get("targets") or []
    active = {environment: set() for environment in ENVIRONMENTS}
    if not isinstance(targets, list):
        errors.append("render-manifest.yaml: spec.targets must be a list")
        return active
    for index, target in enumerate(targets):
        label = f"render-manifest.yaml targets[{index}]"
        if not isinstance(target, dict):
            errors.append(f"{label}: must be an object")
            continue
        name = str(target.get("out", ""))
        if not APP.fullmatch(name):
            errors.append(f"{label}: invalid output/application name {name!r}")
            continue
        environments = target.get("environments") or []
        if not isinstance(environments, list) or not environments:
            errors.append(f"{label}: environments must be a non-empty list")
            continue
        for environment in environments:
            if environment not in active:
                errors.append(f"{label}: invalid environment {environment!r}")
            elif name in active[environment]:
                errors.append(f"{label}: duplicate {name!r} target in {environment}")
            else:
                active[environment].add(name)
    return active


def selected_release_images() -> list[str]:
    """Return the unique named images from already-validated selected release records."""
    images: set[str] = set()
    for environment in ENVIRONMENTS:
        document = yaml.safe_load(
            (ROOT / "deployments" / f"{environment}.yaml").read_text(encoding="utf-8")
        ) or {}
        for application in (document.get("spec") or {}).get("applications") or []:
            relative = safe_release_path(application.get("releaseMetadata"))
            if relative is None:
                raise ValueError("validated release path unexpectedly became unsafe")
            record = json.loads((ROOT / relative).read_text(encoding="utf-8"))
            images.update(str(image) for image in (record.get("images") or {}).values())
    return sorted(images)


def main() -> int:
    global AS_OF, ROOT
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--print-images", action="store_true")
    parser.add_argument("--as-of")
    args = parser.parse_args()
    ROOT = args.root.resolve()
    if args.as_of:
        try:
            AS_OF = dt.datetime.fromisoformat(args.as_of.replace("Z", "+00:00"))
        except ValueError:
            print("ERROR: --as-of must be a timezone-aware RFC3339 timestamp", file=sys.stderr)
            return 1
        if AS_OF.tzinfo is None or AS_OF.utcoffset() is None:
            print("ERROR: --as-of must be a timezone-aware RFC3339 timestamp", file=sys.stderr)
            return 1
    errors: list[str] = []
    selections = {
        environment: load_selection(environment, errors) for environment in ENVIRONMENTS
    }
    targets = active_targets(errors)
    proposal_count = validate_promotion_proposals(errors)
    for environment, applications in selections.items():
        for name in applications:
            if name not in targets[environment]:
                errors.append(f"{environment} application {name} is not active in render-manifest.yaml")
    if errors:
        for error in sorted(set(errors)):
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    if args.print_images:
        try:
            for image in selected_release_images():
                print(image)
        except (OSError, ValueError, json.JSONDecodeError, yaml.YAMLError) as exc:
            print(f"ERROR: cannot enumerate selected release images: {exc}", file=sys.stderr)
            return 1
        return 0
    counts = ", ".join(
        f"{environment}={len(selections[environment])}" for environment in ENVIRONMENTS
    )
    print(f"deployment release selections passed ({counts}; proposals={proposal_count})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
