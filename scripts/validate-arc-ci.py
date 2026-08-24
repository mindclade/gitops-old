#!/usr/bin/env python3
# Copyright © 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

"""Validate the dormant ARC presubmit source and its activation boundary."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import jsonschema
import yaml


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "arc/presubmit-readiness.yaml"
SCHEMA_PATH = ROOT / "contracts/arc-ci-presubmit.schema.json"
VALUES_PATH = ROOT / "arc/values/presubmit.yaml"
RENDERED_PATH = ROOT / "arc/rendered/presubmit.yaml"
PROVENANCE_PATH = ROOT / "vendor/arc/provenance.yaml"

EXPECTED_ROUTING = {
    "githubConfigUrl": "https://github.com/mindclade",
    "runnerGroup": "mindclade-arc-ci",
    "scaleSetName": "mindclade-arc-presubmit-spot",
    "namespace": "arc-presubmit",
}
EXPECTED_BASE_PACKAGE = ".#remote-execution-base"
EXPECTED_AUTHORITY_REPOSITORY = "mindclade/mindclade-internal-monorepo"
EXPECTED_REGISTRATION_SECRET = "arc-github-app"
EXPECTED_TARGET_CAPACITY = {"minRunners": 2, "maxRunners": 24}
EXPECTED_CANARY_CAPACITY = {"minRunners": 0, "maxRunners": 1}
EXPECTED_PLACEMENT = {
    "infrastructureUnit": "5-workloads/ci/nodepools/runner-spot",
    "capacityType": "SPOT",
    "maxNodes": 8,
    "runnersPerNode": 3,
    "nodeSelector": {
        "iam.gke.io/gke-metadata-server-enabled": "true",
        "mindclade.dev/workload-class": "arc-presubmit-spot",
    },
    "tolerations": [
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
    ],
}
EXPECTED_GATE_NAMES = {
    "nixBinaryCache",
    "runnerImage",
    "runnerGroup",
    "readOnlyCacheWif",
    "connectedCluster",
    "workflowRouting",
    "spotInterruption",
    "onDemandRollback",
}
ACTIVATION_PATHS = (
    "applications/ci/arc.yaml",
    "applications/ci/argocd.yaml",
    "bootstrap/argocd-config-ci.yaml",
    "projects/arc-ci.yaml",
    "roots/ci/kustomization.yaml",
)


def load_yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_documents(path: Path) -> list[dict[str, Any]]:
    return [
        document
        for document in yaml.safe_load_all(path.read_text(encoding="utf-8"))
        if isinstance(document, dict)
    ]


def validate_schema(contract: Any, schema: Any) -> list[str]:
    try:
        jsonschema.Draft202012Validator.check_schema(schema)
    except jsonschema.SchemaError as error:
        return [f"schema definition is invalid: {error.message}"]
    validator = jsonschema.Draft202012Validator(
        schema,
        format_checker=jsonschema.FormatChecker(),
    )
    return [
        "schema: "
        + ".".join(str(item) for item in error.absolute_path)
        + (": " if error.absolute_path else "")
        + error.message
        for error in sorted(validator.iter_errors(contract), key=lambda item: list(item.path))
    ]


def qualified_runner_image(image: dict[str, Any]) -> str | None:
    repository = image.get("repository")
    digest = image.get("digest")
    if not isinstance(repository, str) or not isinstance(digest, str):
        return None
    return f"{repository}@{digest}"


def validate_readiness(
    contract: dict[str, Any],
    values: dict[str, Any],
    vendor_runner_image: str,
) -> list[str]:
    errors: list[str] = []
    spec = contract["spec"]
    phase = spec["phase"]
    selected = spec["selected"]
    routing = spec["routing"]
    capacity = spec["capacity"]
    placement = spec["placement"]
    image = spec["runnerImage"]
    gates = spec["gates"]

    if routing != EXPECTED_ROUTING:
        errors.append("routing contract differs from the isolated presubmit boundary")
    if capacity["activatedTarget"] != EXPECTED_TARGET_CAPACITY:
        errors.append("activated capacity must remain minRunners=2 and maxRunners=24")
    if capacity["activatedTarget"]["maxRunners"] <= 6:
        errors.append("activated presubmit fanout must exceed the release-lane maximum")
    if capacity["configured"]["minRunners"] > capacity["configured"]["maxRunners"]:
        errors.append("configured minRunners exceeds maxRunners")
    if placement != EXPECTED_PLACEMENT:
        errors.append("presubmit placement differs from the dedicated Spot pool contract")
    placement_ceiling = placement["maxNodes"] * placement["runnersPerNode"]
    if capacity["activatedTarget"]["maxRunners"] != placement_ceiling:
        errors.append("activated capacity must equal the reviewed Spot pool ceiling")

    if image["authorityRepository"] != EXPECTED_AUTHORITY_REPOSITORY:
        errors.append("runner image authority must remain in the internal monorepo")
    if image["baseFlakePackage"] != EXPECTED_BASE_PACKAGE:
        errors.append("runner image must extend the existing Nix remote-execution base")
    if image["validationFixture"] != vendor_runner_image:
        errors.append("dormant runner image must equal the vendored validation fixture")

    if set(gates) != EXPECTED_GATE_NAMES:
        errors.append("ARC presubmit readiness gates are incomplete or unexpected")
    for gate_name, gate in gates.items():
        if bool(gate["qualified"]) != (gate["evidence"] is not None):
            errors.append(
                f"gate {gate_name} must carry evidence exactly when it is qualified"
            )

    all_gates_qualified = all(gate["qualified"] for gate in gates.values())
    runner_gate_qualified = gates["runnerImage"]["qualified"]
    runner_fields = (
        image["runnerFlakePackage"],
        image["repository"],
        image["digest"],
        image["sourceCommit"],
        image["releaseRecord"],
    )
    if runner_gate_qualified and any(value is None for value in runner_fields):
        errors.append("qualified runner image gate requires complete immutable image evidence")
    if not runner_gate_qualified and any(value is not None for value in runner_fields):
        errors.append("unqualified runner image fields must remain null")

    if phase == "blocked":
        if all_gates_qualified:
            errors.append("blocked phase requires at least one unqualified gate")
        if selected:
            errors.append("blocked ARC presubmit source must not be selected")
        if capacity["configured"] != {"minRunners": 0, "maxRunners": 0}:
            errors.append("blocked ARC presubmit capacity must remain zero")
        expected_image = image["validationFixture"]
    elif phase == "qualified":
        if not all_gates_qualified:
            errors.append("qualified phase requires every readiness gate")
        if selected:
            errors.append("qualified ARC presubmit source requires a separate activation change")
        if capacity["configured"] != {"minRunners": 0, "maxRunners": 0}:
            errors.append("qualified but unselected ARC presubmit capacity must remain zero")
        expected_image = qualified_runner_image(image)
    elif phase == "canary":
        if not all_gates_qualified:
            errors.append("canary phase requires every readiness gate")
        if not selected:
            errors.append("canary phase must record selected=true")
        if capacity["configured"] != EXPECTED_CANARY_CAPACITY:
            errors.append("canary ARC presubmit capacity must remain minRunners=0 and maxRunners=1")
        expected_image = qualified_runner_image(image)
    else:
        if not all_gates_qualified:
            errors.append("activated phase requires every readiness gate")
        if not selected:
            errors.append("activated phase must record selected=true")
        if capacity["configured"] != capacity["activatedTarget"]:
            errors.append("activated ARC presubmit capacity must equal its reviewed target")
        expected_image = qualified_runner_image(image)

    if values.get("githubConfigUrl") != routing["githubConfigUrl"]:
        errors.append("presubmit values use the wrong GitHub configuration URL")
    if values.get("githubConfigSecret") != EXPECTED_REGISTRATION_SECRET:
        errors.append("presubmit values use an unexpected ARC registration secret")
    if values.get("runnerGroup") != routing["runnerGroup"]:
        errors.append("presubmit values use the wrong runner group")
    if values.get("runnerScaleSetName") != routing["scaleSetName"]:
        errors.append("presubmit values use the wrong scale-set name")
    if values.get("minRunners") != capacity["configured"]["minRunners"]:
        errors.append("presubmit values minRunners differs from readiness contract")
    if values.get("maxRunners") != capacity["configured"]["maxRunners"]:
        errors.append("presubmit values maxRunners differs from readiness contract")

    annotations = values.get("annotations") or {}
    if annotations.get("mindclade.dev/activation-state") != phase:
        errors.append("presubmit values do not expose the readiness phase")
    if (
        annotations.get("mindclade.dev/readiness-contract")
        != "arc/presubmit-readiness.yaml"
    ):
        errors.append("presubmit values do not identify the readiness contract")

    template_spec = ((values.get("template") or {}).get("spec") or {})
    if template_spec.get("nodeSelector") != placement["nodeSelector"]:
        errors.append("presubmit values differ from the Spot node selector")
    if template_spec.get("tolerations") != placement["tolerations"]:
        errors.append("presubmit values differ from the two-taint Spot contract")
    containers = template_spec.get("containers") or []
    if len(containers) != 1 or containers[0].get("name") != "runner":
        errors.append("presubmit values must define exactly one runner container")
    elif containers[0].get("image") != expected_image:
        errors.append("presubmit values do not use the contract-authorized runner image")
    if template_spec.get("automountServiceAccountToken") is not False:
        errors.append("presubmit runner must disable service-account token automount")
    if values.get("containerMode") is not None:
        errors.append("presubmit runner must not enable privileged container modes")
    if template_spec.get("volumes"):
        errors.append("presubmit runner must not define shared writable volumes")
    if template_spec.get("initContainers"):
        errors.append("presubmit runner must not define init containers")

    return errors


def validate_rendered(
    contract: dict[str, Any],
    values: dict[str, Any],
    documents: list[dict[str, Any]],
) -> list[str]:
    errors: list[str] = []
    spec = contract["spec"]
    routing = spec["routing"]
    forbidden_kinds = {"Secret", "PersistentVolume", "PersistentVolumeClaim"}
    discovered_forbidden = sorted(
        {str(document.get("kind")) for document in documents} & forbidden_kinds
    )
    if discovered_forbidden:
        errors.append(
            "presubmit render contains credential or persistent-storage resources: "
            + ", ".join(discovered_forbidden)
        )
    if any(
        (document.get("metadata") or {}).get("namespace") != routing["namespace"]
        for document in documents
    ):
        errors.append("presubmit render escapes its dedicated namespace")

    scale_sets = [
        document
        for document in documents
        if document.get("kind") == "AutoscalingRunnerSet"
    ]
    if len(scale_sets) != 1:
        return errors + ["presubmit render must contain exactly one AutoscalingRunnerSet"]
    scale_set = scale_sets[0]
    metadata = scale_set.get("metadata") or {}
    rendered_spec = scale_set.get("spec") or {}
    if metadata.get("name") != routing["scaleSetName"]:
        errors.append("rendered presubmit scale-set name differs from its routing contract")
    if rendered_spec.get("runnerGroup") != routing["runnerGroup"]:
        errors.append("rendered presubmit scale set uses the wrong runner group")
    if rendered_spec.get("minRunners") != values.get("minRunners"):
        errors.append("rendered presubmit minRunners differs from authored values")
    if rendered_spec.get("maxRunners") != values.get("maxRunners"):
        errors.append("rendered presubmit maxRunners differs from authored values")

    pod_spec = ((rendered_spec.get("template") or {}).get("spec") or {})
    placement = spec["placement"]
    if pod_spec.get("nodeSelector") != placement["nodeSelector"]:
        errors.append("rendered presubmit pod differs from the Spot node selector")
    if pod_spec.get("tolerations") != placement["tolerations"]:
        errors.append("rendered presubmit pod differs from the two-taint Spot contract")
    if pod_spec.get("restartPolicy") != "Never":
        errors.append("ARC presubmit runners must be ephemeral restartPolicy=Never pods")
    if pod_spec.get("automountServiceAccountToken") is not False:
        errors.append("rendered presubmit runner automounts a service-account token")
    if pod_spec.get("serviceAccountName") != (
        f"{routing['scaleSetName']}-gha-rs-no-permission"
    ):
        errors.append("rendered presubmit runner does not use the no-permission service account")
    for field in ("hostIPC", "hostNetwork", "hostPID", "shareProcessNamespace"):
        if pod_spec.get(field) is True:
            errors.append(f"rendered presubmit runner enables {field}")
    if pod_spec.get("volumes"):
        errors.append("rendered presubmit runner contains a shared writable volume")
    if pod_spec.get("initContainers"):
        errors.append("rendered presubmit runner contains an init container")
    pod_security_context = pod_spec.get("securityContext") or {}
    if pod_security_context.get("runAsNonRoot") is not True:
        errors.append("rendered presubmit pod does not require a non-root user")
    if (pod_security_context.get("seccompProfile") or {}).get("type") != "RuntimeDefault":
        errors.append("rendered presubmit pod does not require RuntimeDefault seccomp")

    containers = pod_spec.get("containers") or []
    if len(containers) != 1 or containers[0].get("name") != "runner":
        return errors + ["rendered presubmit pod must contain exactly one runner container"]
    runner = containers[0]
    if runner.get("env") or runner.get("envFrom") or runner.get("volumeMounts"):
        errors.append("rendered presubmit runner contains a credential or volume injection path")
    security_context = runner.get("securityContext") or {}
    if security_context.get("allowPrivilegeEscalation") is not False:
        errors.append("rendered presubmit runner permits privilege escalation")
    if security_context.get("runAsNonRoot") is not True:
        errors.append("rendered presubmit runner does not require a non-root user")
    if "ALL" not in ((security_context.get("capabilities") or {}).get("drop") or []):
        errors.append("rendered presubmit runner does not drop all Linux capabilities")
    image = runner.get("image")
    if not isinstance(image, str) or "@sha256:" not in image:
        errors.append("rendered presubmit runner image is not digest-pinned")

    no_permission_accounts = [
        document
        for document in documents
        if document.get("kind") == "ServiceAccount"
        and (document.get("metadata") or {}).get("name")
        == f"{routing['scaleSetName']}-gha-rs-no-permission"
    ]
    if len(no_permission_accounts) != 1:
        errors.append("presubmit render must contain exactly one no-permission service account")
    elif "iam.gke.io/gcp-service-account" in (
        (no_permission_accounts[0].get("metadata") or {}).get("annotations") or {}
    ):
        errors.append("dormant presubmit service account must not impersonate a cloud identity")

    return errors


def validate_selection(root: Path, contract: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    selected = contract["spec"]["selected"]
    rendered_kustomization = load_yaml(root / "arc/rendered/kustomization.yaml") or {}
    if not isinstance(rendered_kustomization, dict):
        return ["ARC rendered kustomization is not a mapping"]
    rendered_selected = "presubmit.yaml" in (rendered_kustomization.get("resources") or [])
    present_activation_paths = [path for path in ACTIVATION_PATHS if (root / path).exists()]
    namespaces = load_documents(root / "arc/platform/namespaces.yaml")
    namespace_selected = any(
        document.get("kind") == "Namespace"
        and (document.get("metadata") or {}).get("name") == "arc-presubmit"
        for document in namespaces
    )
    platform_documents = {
        relative: load_documents(root / relative)
        for relative in (
            "arc/platform/network-policies.yaml",
            "arc/platform/secret-sync.yaml",
        )
    }
    namespaced_platform_objects = [
        document
        for documents in platform_documents.values()
        for document in documents
        if (document.get("metadata") or {}).get("namespace") == "arc-presubmit"
    ]

    if not selected:
        if rendered_selected:
            errors.append("blocked presubmit render is selected by ARC kustomization")
        if namespace_selected:
            errors.append("blocked presubmit namespace is selected by ARC platform source")
        if namespaced_platform_objects:
            errors.append("blocked presubmit platform resources are selected by ARC source")
        for path in present_activation_paths:
            errors.append(f"blocked presubmit activation path exists: {path}")
    else:
        if not rendered_selected:
            errors.append("selected presubmit contract is absent from ARC kustomization")
        if not namespace_selected:
            errors.append("selected presubmit contract has no dedicated namespace")
        missing_activation_paths = [
            path for path in ACTIVATION_PATHS if path not in present_activation_paths
        ]
        for path in missing_activation_paths:
            errors.append(f"selected presubmit contract is missing activation path: {path}")
        required_platform_kinds = {
            "NetworkPolicy",
            "SecretProviderClass",
            "SecretSync",
            "ServiceAccount",
        }
        present_platform_kinds = {
            str(document.get("kind")) for document in namespaced_platform_objects
        }
        missing_platform_kinds = sorted(required_platform_kinds - present_platform_kinds)
        if missing_platform_kinds:
            errors.append(
                "selected presubmit contract is missing namespaced platform resources: "
                + ", ".join(missing_platform_kinds)
            )

    for application_path in (root / "applications").rglob("*.yaml"):
        for document in load_documents(application_path):
            application_spec = document.get("spec") or {}
            if not isinstance(application_spec, dict):
                continue
            source = application_spec.get("source") or {}
            if not isinstance(source, dict):
                continue
            source_path = source.get("path")
            if source_path == "arc" and not selected:
                errors.append(
                    f"blocked ARC source is selected by {application_path.relative_to(root)}"
                )

    return errors


def validate_all(root: Path = ROOT) -> list[str]:
    try:
        contract = load_yaml(root / CONTRACT_PATH.relative_to(ROOT))
        schema = json.loads((root / SCHEMA_PATH.relative_to(ROOT)).read_text(encoding="utf-8"))
        values = load_yaml(root / VALUES_PATH.relative_to(ROOT))
        documents = load_documents(root / RENDERED_PATH.relative_to(ROOT))
        provenance = load_yaml(root / PROVENANCE_PATH.relative_to(ROOT))
    except (OSError, json.JSONDecodeError, yaml.YAMLError) as error:
        return [f"ARC presubmit contract input is unreadable: {error}"]

    schema_failures = validate_schema(contract, schema)
    if schema_failures:
        return schema_failures
    if not isinstance(values, dict):
        return ["ARC presubmit values must be a mapping"]
    provenance_spec = provenance.get("spec") if isinstance(provenance, dict) else None
    provenance_images = (
        provenance_spec.get("images") if isinstance(provenance_spec, dict) else None
    )
    vendor_runner_image = (
        provenance_images.get("runner") if isinstance(provenance_images, dict) else None
    )
    if not isinstance(vendor_runner_image, str):
        return ["ARC vendor provenance omits the runner validation fixture"]
    return (
        validate_readiness(contract, values, vendor_runner_image)
        + validate_rendered(contract, values, documents)
        + validate_selection(root, contract)
    )


def main() -> int:
    errors = validate_all()
    if errors:
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        return 1
    print("ARC presubmit source and activation boundary: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
