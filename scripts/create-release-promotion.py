#!/usr/bin/env python3
# Copyright © 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

"""Create a review-only deployment proposal from immutable release workflow inputs."""

from __future__ import annotations

import argparse
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
    "go-vanity": "platform-go-vanity",
    "weights-fixture": "research-weights-fixture",
}
HEADER = """# Copyright © 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

---
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--image-ref", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--previous-release-id", required=True)
    parser.add_argument("--previous-subject-digest", required=True)
    args = parser.parse_args()

    if not RELEASE.fullmatch(args.release_id):
        raise ValueError("release-id must be vX.Y.Z")
    if not SHA.fullmatch(args.source_sha):
        raise ValueError("source-sha must be a full lowercase commit SHA")
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
    output = PROPOSALS / f"{args.release_id}.yaml"
    if output.exists():
        raise ValueError(f"refusing to replace an existing promotion proposal: {output.name}")
    output.parent.mkdir(parents=True, exist_ok=True)
    proposal = {
        "apiVersion": "release.mindclade.dev/v1beta1",
        "kind": "PromotionProposal",
        "metadata": {"name": args.release_id},
        "spec": {
            "target": {
                "application": TARGETS[package],
                "releaseKind": "application",
                "imageRef": args.image_ref,
                "subjectDigest": match.group("digest"),
            },
            "sourceRepository": "mindclade/mindclade-internal-monorepo",
            "sourceRevision": args.source_sha,
            "previousRelease": {
                "releaseId": args.previous_release_id,
                "subjectDigest": args.previous_subject_digest,
            },
            "targetEnvironment": "development",
            "requiredEvidence": [
                "build-attestation",
                "qualification-attestation",
                "deployment-attestation",
                "provenance",
                "sbom",
                "vulnerability-scan",
                "release-metadata-4.0.0",
            ],
        },
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
