#!/usr/bin/env python3
# Copyright © 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

"""Validate that ARC runners stay on their dedicated infrastructure-owned pool."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
ON_DEMAND_RELEASES = ("canary", "build", "qualify")
RUNNER_RELEASES = (*ON_DEMAND_RELEASES, "presubmit")
EXPECTED_NODE_SELECTOR = {
    "iam.gke.io/gke-metadata-server-enabled": "true",
    "mindclade.dev/workload-class": "arc-runner",
}
EXPECTED_TOLERATIONS = [
    {
        "key": "scheduling.mindclade.dev/arc-runner",
        "operator": "Equal",
        "value": "true",
        "effect": "NoSchedule",
    }
]
EXPECTED_SPOT_NODE_SELECTOR = {
    "iam.gke.io/gke-metadata-server-enabled": "true",
    "mindclade.dev/workload-class": "arc-presubmit-spot",
}
EXPECTED_SPOT_TOLERATIONS = [
    {
        "key": "scheduling.mindclade.dev/spot",
        "operator": "Equal",
        "value": "true",
        "effect": "NoSchedule",
    },
    {
        "key": "scheduling.mindclade.dev/arc-presubmit",
        "operator": "Equal",
        "value": "true",
        "effect": "NoSchedule",
    },
]


def load_mapping(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain one YAML object")
    return payload


def runner_pod_spec(values: dict[str, Any], label: str) -> dict[str, Any]:
    template = values.get("template")
    if not isinstance(template, dict):
        raise ValueError(f"{label} omits template")
    spec = template.get("spec")
    if not isinstance(spec, dict):
        raise ValueError(f"{label} omits template.spec")
    return spec


def validate_runner_spec(
    spec: dict[str, Any],
    label: str,
    *,
    node_selector: dict[str, str] = EXPECTED_NODE_SELECTOR,
    tolerations: list[dict[str, str]] = EXPECTED_TOLERATIONS,
) -> list[str]:
    errors: list[str] = []
    if spec.get("nodeSelector") != node_selector:
        errors.append(
            f"{label} must select the dedicated ARC runner pool with the exact node selector"
        )
    if spec.get("tolerations") != tolerations:
        errors.append(
            f"{label} must carry only the dedicated ARC runner-pool toleration"
        )
    return errors


def validate_controller_spec(spec: dict[str, Any], label: str) -> list[str]:
    errors: list[str] = []
    selector = spec.get("nodeSelector")
    if not isinstance(selector, dict) or selector != {
        "iam.gke.io/gke-metadata-server-enabled": "true"
    }:
        errors.append(
            f"{label} must remain on the system pool with only the metadata-server selector"
        )
    if spec.get("tolerations") not in (None, []):
        errors.append(f"{label} must not tolerate the ARC runner-pool taint")
    return errors


def rendered_object(path: Path, kind: str, name: str) -> dict[str, Any]:
    matches: list[dict[str, Any]] = []
    for document in yaml.safe_load_all(path.read_text(encoding="utf-8")):
        if not isinstance(document, dict) or document.get("kind") != kind:
            continue
        metadata = document.get("metadata")
        if isinstance(metadata, dict) and metadata.get("name") == name:
            matches.append(document)
    if len(matches) != 1:
        raise ValueError(f"{path} must contain exactly one {kind}/{name}")
    return matches[0]


def validate_all(root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    for release in RUNNER_RELEASES:
        node_selector = (
            EXPECTED_SPOT_NODE_SELECTOR
            if release == "presubmit"
            else EXPECTED_NODE_SELECTOR
        )
        tolerations = (
            EXPECTED_SPOT_TOLERATIONS
            if release == "presubmit"
            else EXPECTED_TOLERATIONS
        )
        values_path = root / f"arc/values/{release}.yaml"
        rendered_path = root / f"arc/rendered/{release}.yaml"
        try:
            values = load_mapping(values_path)
            values_spec = runner_pod_spec(values, f"arc/values/{release}.yaml")
            errors.extend(
                validate_runner_spec(
                    values_spec,
                    f"arc/values/{release}.yaml",
                    node_selector=node_selector,
                    tolerations=tolerations,
                )
            )
            scale_set_name = values.get("runnerScaleSetName")
            if not isinstance(scale_set_name, str) or not scale_set_name:
                errors.append(
                    f"arc/values/{release}.yaml omits runnerScaleSetName"
                )
                continue
            rendered = rendered_object(
                rendered_path, "AutoscalingRunnerSet", scale_set_name
            )
            rendered_spec = runner_pod_spec(
                rendered.get("spec") or {}, f"arc/rendered/{release}.yaml"
            )
            errors.extend(
                validate_runner_spec(
                    rendered_spec,
                    f"arc/rendered/{release}.yaml",
                    node_selector=node_selector,
                    tolerations=tolerations,
                )
            )
        except (OSError, ValueError, yaml.YAMLError) as error:
            errors.append(str(error))

    try:
        controller_values = load_mapping(root / "arc/values/controller.yaml")
        errors.extend(
            validate_controller_spec(
                controller_values, "arc/values/controller.yaml"
            )
        )
        controller = rendered_object(
            root / "arc/rendered/controller.yaml", "Deployment", "arc-controller"
        )
        deployment_spec = controller.get("spec")
        template = deployment_spec.get("template") if isinstance(deployment_spec, dict) else None
        controller_spec = template.get("spec") if isinstance(template, dict) else None
        if not isinstance(controller_spec, dict):
            errors.append("arc/rendered/controller.yaml omits Deployment template.spec")
        else:
            errors.extend(
                validate_controller_spec(
                    controller_spec, "arc/rendered/controller.yaml"
                )
            )
    except (OSError, ValueError, yaml.YAMLError) as error:
        errors.append(str(error))
    return errors


def main() -> int:
    errors = validate_all()
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("ARC runner placement contract passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
