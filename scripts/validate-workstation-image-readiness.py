#!/usr/bin/env python3
# Copyright © 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

"""Validate GitOps' evidence-only workstation-image qualification boundary."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "qualification/workstation-image-readiness.yaml"
SOURCE_GATES = {
    "imageContractValidated",
    "runtimeFetchesAbsent",
    "createOnlyPublicationContract",
    "terraformImageAuthoritySeparated",
    "governedSourceEvidenceTransition",
}
CONNECTED_GATES = {
    "bootstrapApplied",
    "workflowContractPublished",
    "terraformModulesPublished",
    "sourceBucketApplied",
    "sourceObjectPublished",
    "sourceEvidenceCatalogQualified",
    "computeImageApplied",
    "firstBootQualified",
    "idleShutdownObserved",
    "rollbackImageBooted",
    "vpcScCachePathQualified",
}


def errors(document: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    if document.get("apiVersion") != "mindclade.dev/v1alpha1":
        failures.append("unsupported workstation qualification apiVersion")
    if document.get("kind") != "WorkstationImageQualification":
        failures.append("workstation qualification kind differs")
    spec = document.get("spec")
    if not isinstance(spec, dict):
        return failures + ["workstation qualification spec must be an object"]
    if spec.get("state") != "qualifying":
        failures.append("workstation qualification must remain qualifying before evidence")
    authority = spec.get("authority")
    expected_authority = {
        "sourceRepository": "mindclade/mindclade-internal-monorepo",
        "workflowRepository": "mindclade/.github",
        "infrastructureRepository": "mindclade/infrastructure-live",
        "gitopsRole": "evidence-only",
    }
    if authority != expected_authority:
        failures.append("workstation qualification authority boundary differs")
    if spec.get("releases") != {
        "bootstrapContract": "2.0.0",
        "workflowContract": "v5.0.0",
        "terraformModules": "v0.4.0",
    }:
        failures.append("workstation qualification release set differs")
    source = spec.get("sourceGates")
    if not isinstance(source, dict) or set(source) != SOURCE_GATES or not all(source.values()):
        failures.append("workstation source gates must be exact and passed")
    connected = spec.get("connectedGates")
    if (
        not isinstance(connected, dict)
        or set(connected) != CONNECTED_GATES
        or any(connected.values())
    ):
        failures.append("unproven workstation connected gates must remain exact and false")
    if spec.get("activation") != {
        "argoReconciliationAllowed": False,
        "productActivationAllowed": False,
        "selected": False,
    }:
        failures.append("GitOps may not reconcile or activate the workstation")
    return failures


def load(path: Path = CONTRACT) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("workstation qualification root must be an object")
    return value


def main() -> int:
    try:
        failures = errors(load())
    except (OSError, ValueError, yaml.YAMLError) as error:
        failures = [str(error)]
    if failures:
        for failure in failures:
            print(f"ERROR: {failure}", file=sys.stderr)
        return 1
    print("workstation image qualification boundary passed (state: qualifying)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
