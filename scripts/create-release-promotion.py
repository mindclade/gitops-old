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
    parser.add_argument("--previous-release-id", required=True)
    parser.add_argument("--previous-subject-digest", required=True)
    args = parser.parse_args()

    if not RELEASE.fullmatch(args.release_id):
        raise ValueError("release-id must be vX.Y.Z")
    if not SHA.fullmatch(args.source_sha):
        raise ValueError("source-sha must be a full lowercase commit SHA")
    if not DIGEST.fullmatch(args.producer_evidence_digest):
        raise ValueError("producer-evidence-digest must be one canonical SHA-256 digest")
    if not RELEASE.fullmatch(args.previous_release_id):
        raise ValueError("previous-release-id must be vX.Y.Z")
    if args.previous_release_id == args.release_id:
        raise ValueError("previous-release-id must differ from release-id")
    if (
        not DIGEST.fullmatch(args.previous_subject_digest)
        or args.previous_subject_digest == "sha256:" + "0" * 64
    ):
        raise ValueError(
            "previous-subject-digest must be a nonzero canonical SHA-256 digest"
        )
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
        "previousRelease": {
            "releaseId": args.previous_release_id,
            "subjectDigest": args.previous_subject_digest,
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
        "apiVersion": "release.mindclade.dev/v1beta1",
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
