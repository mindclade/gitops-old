#!/usr/bin/env python3
# Copyright © 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

"""Create a review-only deployment proposal from immutable release workflow inputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
PROPOSALS = ROOT / "deployments/proposals"
RELEASE = re.compile(r"v[0-9]+\.[0-9]+\.[0-9]+")
SHA = re.compile(r"[0-9a-f]{40}")
DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
IMAGE = re.compile(
    r"(?P<host>[a-z0-9][a-z0-9.-]*-docker\.pkg\.dev)/"
    r"(?P<project>[a-z][a-z0-9-]{4,28}[a-z0-9])/releases/"
    r"(?P<package>[a-z][a-z0-9-]{1,62})@(?P<digest>sha256:[0-9a-f]{64})"
)
TARGETS = {
    "go-vanity": ("platform-go-vanity", "application"),
    "weights-fixture": ("research-weights-fixture", "model"),
}
REQUIRED_EVIDENCE = sorted(
    {
        "build-attestation",
        "deployment-attestation",
        "provenance",
        "qualification-attestation",
        "release-evidence-retention",
        "release-evidence-v1",
        "release-metadata-4.0.0",
        "rollback",
        "sbom",
        "vulnerability-scan",
    }
)
HEADER = """# Copyright © 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

---
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--application", required=True)
    parser.add_argument("--release-kind", required=True)
    parser.add_argument("--image-ref", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--producer-evidence-digest", required=True)
    parser.add_argument(
        "--rollback-strategy", choices=("bootstrap", "previous-release"), required=True
    )
    parser.add_argument("--previous-release-id")
    parser.add_argument("--previous-subject-digest")
    args = parser.parse_args()

    if not RELEASE.fullmatch(args.release_id):
        raise ValueError("release-id must be vX.Y.Z")
    if not SHA.fullmatch(args.source_sha):
        raise ValueError("source-sha must be a full lowercase commit SHA")
    if not DIGEST.fullmatch(args.producer_evidence_digest):
        raise ValueError("producer-evidence-digest must be one canonical SHA-256 digest")
    previous_release: dict[str, str] | None = None
    if args.rollback_strategy == "bootstrap":
        if args.release_id != "v1.0.0":
            raise ValueError("bootstrap rollback is permitted only for v1.0.0")
        if args.previous_release_id is not None or args.previous_subject_digest is not None:
            raise ValueError("bootstrap rollback forbids previous release lineage")
    else:
        if not args.previous_release_id or not RELEASE.fullmatch(args.previous_release_id):
            raise ValueError("previous-release-id must be vX.Y.Z")
        candidate = tuple(int(part) for part in args.release_id[1:].split("."))
        previous = tuple(int(part) for part in args.previous_release_id[1:].split("."))
        if previous >= candidate:
            raise ValueError("previous-release-id must be older than release-id")
        if (
            not args.previous_subject_digest
            or not DIGEST.fullmatch(args.previous_subject_digest)
            or args.previous_subject_digest == "sha256:" + "0" * 64
        ):
            raise ValueError(
                "previous-subject-digest must be a nonzero canonical SHA-256 digest"
            )
        previous_release = {
            "releaseId": args.previous_release_id,
            "subjectDigest": args.previous_subject_digest,
        }
    match = IMAGE.fullmatch(args.image_ref)
    if match is None:
        raise ValueError("image-ref must identify one digest in the CI releases repository")
    package = match.group("package")
    if package not in TARGETS:
        raise ValueError(f"image package is outside the closed promotion catalog: {package}")
    expected_application, expected_release_kind = TARGETS[package]
    if args.application != expected_application:
        raise ValueError("application does not match the closed promotion catalog")
    if args.release_kind != expected_release_kind:
        raise ValueError("release-kind does not match the closed promotion catalog")
    output = PROPOSALS / f"{args.release_id}.yaml"
    if output.exists():
        raise ValueError(f"refusing to replace an existing promotion proposal: {output.name}")
    output.parent.mkdir(parents=True, exist_ok=True)
    spec = {
        "target": {
            "application": args.application,
            "releaseKind": args.release_kind,
            "releaseMetadata": f"releases/{args.application}/{args.release_id}.json",
            "imageRef": args.image_ref,
            "subjectDigest": match.group("digest"),
            "producerEvidenceDigest": args.producer_evidence_digest,
        },
        "sourceRepository": "mindclade/mindclade-internal-monorepo",
        "sourceRevision": args.source_sha,
        "rollback": {
            "strategy": args.rollback_strategy,
            "previousRelease": previous_release,
            "bootstrapAction": (
                "remove-development-selection-and-restore-blocked-zero-state"
                if args.rollback_strategy == "bootstrap"
                else None
            ),
        },
        "targetEnvironment": "development",
        "requiredEvidence": REQUIRED_EVIDENCE,
    }
    spec_digest = "sha256:" + hashlib.sha256(
        json.dumps(
            spec, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("utf-8")
    ).hexdigest()
    proposal = {
        "apiVersion": "release.mindclade.dev/v1beta2",
        "kind": "PromotionProposal",
        "metadata": {
            "name": args.release_id,
            "annotations": {
                "release.mindclade.dev/consumer-contract": "4.0.0",
                "release.mindclade.dev/producer-schema": "mindclade.dev/release-evidence/v1",
                "release.mindclade.dev/spec-digest": spec_digest,
            },
        },
        "spec": spec,
    }
    output.write_text(
        HEADER + yaml.safe_dump(proposal, sort_keys=False), encoding="utf-8"
    )
    print(output)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, yaml.YAMLError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1) from error
