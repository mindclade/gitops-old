#!/usr/bin/env python3
# Copyright © 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

#
"""Validate AppProject role bindings and rendered namespace authorization."""

from __future__ import annotations

import fnmatch
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
IN_CLUSTER = "https://kubernetes.default.svc"
DOMAIN_PROJECT = {
    "data-": "data",
    "partner-": "partner-isolated",
    "platform-": "platform",
    "research-": "research",
    "serving-": "serving",
}
errors: list[str] = []
projects: dict[str, dict] = {}


def project_allows_namespace(project: dict, namespace: str) -> bool:
    for destination in (project.get("spec") or {}).get("destinations") or []:
        if destination.get("server") not in {IN_CLUSTER, "*"}:
            continue
        pattern = str(destination.get("namespace", ""))
        if pattern and fnmatch.fnmatchcase(namespace, pattern):
            return True
    return False


for path in sorted((ROOT / "projects").glob("*.yaml")):
    for document in yaml.safe_load_all(path.read_text("utf-8")):
        if not isinstance(document, dict) or document.get("kind") != "AppProject":
            continue
        project_name = (document.get("metadata") or {}).get("name")
        if not project_name:
            errors.append(f"{path}: AppProject has no metadata.name")
            continue
        if project_name in projects:
            errors.append(f"duplicate AppProject: {project_name}")
        projects[project_name] = document

        for role in (document.get("spec") or {}).get("roles") or []:
            role_name = role.get("name")
            for policy in role.get("policies") or []:
                if not isinstance(policy, str):
                    errors.append(
                        f"{path}: {project_name}/{role_name} policy is not a Casbin string"
                    )
                    continue
                fields = [field.strip() for field in policy.split(",")]
                if len(fields) != 6:
                    errors.append(
                        f"{path}: {project_name}/{role_name} policy must have six Casbin fields: {policy}"
                    )
                if f"proj:{project_name}:{role_name}" not in policy:
                    errors.append(f"{path}: role binding mismatch: {policy}")


for path in sorted((ROOT / "applications").rglob("*.yaml")):
    for document in yaml.safe_load_all(path.read_text("utf-8")):
        if not isinstance(document, dict):
            continue
        spec = document.get("spec") or {}
        if document.get("kind") == "ApplicationSet":
            spec = (spec.get("template") or {}).get("spec") or {}
        if document.get("kind") not in {"Application", "ApplicationSet"}:
            continue
        project_name = spec.get("project")
        project = projects.get(project_name)
        if not project:
            errors.append(f"{path}: references unknown AppProject {project_name!r}")
            continue
        namespace = (spec.get("destination") or {}).get("namespace") or ""
        if (
            namespace
            and "{{" not in namespace
            and not project_allows_namespace(project, namespace)
        ):
            errors.append(
                f"{path}: AppProject {project_name} does not allow destination {namespace}"
            )


for app_directory in sorted((ROOT / "rendered").glob("*/*")):
    if not app_directory.is_dir():
        continue
    project_name = next(
        (
            project
            for prefix, project in DOMAIN_PROJECT.items()
            if app_directory.name.startswith(prefix)
        ),
        None,
    )
    if not project_name:
        errors.append(
            f"{app_directory}: rendered directory has no domain-to-project mapping"
        )
        continue
    project = projects.get(project_name)
    if not project:
        errors.append(
            f"{app_directory}: mapped AppProject {project_name} does not exist"
        )
        continue
    for manifest in sorted(app_directory.glob("*.yaml")):
        for document in yaml.safe_load_all(manifest.read_text("utf-8")):
            if not isinstance(document, dict):
                continue
            metadata = document.get("metadata") or {}
            namespace = (
                metadata.get("name")
                if document.get("kind") == "Namespace"
                else metadata.get("namespace")
            )
            if namespace and not project_allows_namespace(project, str(namespace)):
                errors.append(
                    f"{manifest}: {document.get('kind')} {metadata.get('name')} targets namespace "
                    f"{namespace!r}, which AppProject {project_name} does not allow"
                )


if errors:
    print("\n".join(errors), file=sys.stderr)
    raise SystemExit(1)
print("Argo project RBAC and rendered namespace authorization passed")
