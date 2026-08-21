#!/usr/bin/env python3
# Copyright © 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary
"""Select signer refs only from an exact, trusted release-handoff transition policy."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


class TransitionError(ValueError):
    """The candidate policy is not one of the exact reviewed transition policies."""


def _policy(workflow_version: str) -> dict[str, Any]:
    prefix = "mindclade/.github/.github/workflows"
    return {
        "producer_schema_version": "mindclade.dev/release-evidence/v1",
        "consumer_contract_version": "4.0.0",
        "source_repository": "mindclade/mindclade-internal-monorepo",
        "signer_workflow_refs": {
            "build": (
                f"{prefix}/reusable-arc-oci-build.yml@refs/tags/{workflow_version}"
            ),
            "qualification": (
                f"{prefix}/reusable-arc-qualification-attest.yml@refs/tags/"
                f"{workflow_version}"
            ),
            "deployment": (
                f"{prefix}/reusable-binauthz-sign.yml@refs/tags/{workflow_version}"
            ),
        },
        "evidence_retention": {
            "nonproduction": "P1Y",
            "production": "P7Y",
        },
        "vulnerability_exception": {
            "approved_by": "@mindclade/security",
            "maximum_duration_days": 90,
        },
    }


APPROVED_POLICIES = {
    version: _policy(version)
    for version in (
        "v4.0.0",
        "v5.0.0",
    )
}


def select_policy(path: Path) -> tuple[str, dict[str, str]]:
    try:
        candidate = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TransitionError(f"cannot read release-handoff policy: {exc}") from exc
    for version, approved in APPROVED_POLICIES.items():
        if candidate == approved:
            return version, approved["signer_workflow_refs"]
    raise TransitionError(
        "release-handoff policy is not an exact approved v4-to-v5 transition policy"
    )


def write_outputs(path: Path, version: str, refs: dict[str, str]) -> None:
    values = {
        "workflow-version": version,
        "build-signer-workflow-ref": refs["build"],
        "qualification-signer-workflow-ref": refs["qualification"],
        "deployment-signer-workflow-ref": refs["deployment"],
    }
    with path.open("a", encoding="utf-8") as stream:
        for name, value in values.items():
            stream.write(f"{name}={value}\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--github-output", type=Path, required=True)
    args = parser.parse_args()
    try:
        version, refs = select_policy(args.policy)
        write_outputs(args.github_output, version, refs)
    except TransitionError as exc:
        print(f"release-handoff-transition: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
