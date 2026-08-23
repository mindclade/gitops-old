#!/usr/bin/env python3
# Copyright © 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

"""Validate the immutable, base-trusted production handoff workflow."""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = Path(".github/workflows/production-handoff.yml")
EXPECTED_SHA256 = "d44181a11dcd71acbdecaa92d70621cc596c1638e395fcdace39368130e5041f"


def load_mapping(path: Path) -> dict[str | bool, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("production handoff workflow must contain one YAML object")
    return value


def validate_workflow(path: Path) -> list[str]:
    errors: list[str] = []
    contents = path.read_bytes()
    actual = hashlib.sha256(contents).hexdigest()
    if actual != EXPECTED_SHA256:
        errors.append(
            "production handoff workflow differs from the trusted digest; update the trusted "
            "validator in a separate reviewed transition before changing the privileged workflow"
        )
    try:
        workflow = load_mapping(path)
    except (OSError, ValueError, yaml.YAMLError) as error:
        return [str(error)]

    events = workflow.get(True, workflow.get("on"))
    if not isinstance(events, dict) or set(events) != {
        "pull_request_target",
        "merge_group",
    }:
        errors.append(
            "production handoff events must be exactly pull_request_target and merge_group"
        )
    if workflow.get("permissions") != {"contents": "read"}:
        errors.append("production handoff top-level permissions must be contents: read")

    jobs = workflow.get("jobs")
    expected_jobs = {
        "detect",
        "connected",
        "merge-group-offline",
        "production-handoff-gate",
    }
    if not isinstance(jobs, dict) or set(jobs) != expected_jobs:
        errors.append("production handoff job inventory is not exact")
        return errors

    connected = jobs["connected"]
    if connected.get("environment") != "production":
        errors.append(
            "connected handoff verification must use the production environment"
        )
    if connected.get("permissions") != {"contents": "read", "id-token": "write"}:
        errors.append("only connected handoff verification may receive an OIDC token")
    connected_if = str(connected.get("if", ""))
    for required in (
        "github.event_name == 'pull_request_target'",
        "needs.detect.outputs.qualified == 'true'",
    ):
        if required not in connected_if:
            errors.append(f"connected handoff condition omits: {required}")

    for name in ("detect", "merge-group-offline", "production-handoff-gate"):
        job = jobs[name]
        if job.get("permissions") != {"contents": "read"}:
            errors.append(f"{name} permissions must be contents: read")
        if "environment" in job:
            errors.append(f"{name} must not request an environment")

    offline_if = str(jobs["merge-group-offline"].get("if", ""))
    for required in (
        "github.event_name == 'merge_group'",
        "needs.detect.outputs.qualified == 'true'",
    ):
        if required not in offline_if:
            errors.append(f"merge-group offline condition omits: {required}")

    text = contents.decode("utf-8", errors="replace")
    for required in (
        "github.event.pull_request.base.sha",
        "github.event.pull_request.head.sha",
        "github.event.merge_group.base_sha",
        "github.event.merge_group.head_sha",
        "path: .trusted",
        "path: .candidate",
        "nix develop ./.trusted#ci",
        ".trusted/scripts/production_handoff.py validate",
        "--root .candidate",
        'gcloud storage cat "${uri}#${generation}"',
        'rm -f -- "$GOOGLE_GHA_CREDS_PATH"',
    ):
        if required not in text:
            errors.append(f"production handoff trust boundary omits: {required}")
    for forbidden in (
        "\n  pull_request:\n",
        "nix develop .#ci",
        "nix develop ./.candidate",
        ".candidate/scripts/",
    ):
        if forbidden in text:
            errors.append(
                f"production handoff trust boundary contains forbidden text: {forbidden.strip()}"
            )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workflow", type=Path, default=ROOT / WORKFLOW)
    args = parser.parse_args()
    errors = validate_workflow(args.workflow)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("production handoff workflow trust boundary passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
