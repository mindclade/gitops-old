#!/usr/bin/env python3
# Copyright © 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

#
"""Validate digest-only environment artifact selections and release-record bindings."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
ENVIRONMENTS = ("development", "staging", "production")
APP = re.compile(r"(?:platform|serving|research|data|partner)-[a-z0-9][a-z0-9-]*")
REPOSITORY = re.compile(
    r"[a-z0-9][a-z0-9.-]*-docker\.pkg\.dev/"
    r"[a-z][a-z0-9-]{4,28}[a-z0-9]/[a-z0-9._/-]+"
)
DIGEST = re.compile(r"sha256:[0-9a-f]{64}")


def load_selection(environment: str, errors: list[str]) -> dict[str, dict]:
    path = ROOT / "deployments" / f"{environment}.yaml"
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        errors.append(f"{path.relative_to(ROOT)}: cannot parse: {exc}")
        return {}
    if (
        document.get("apiVersion") != "mindclade.dev/v1"
        or document.get("kind") != "ArtifactDeploymentSet"
    ):
        errors.append(f"{path.relative_to(ROOT)}: invalid apiVersion/kind")
    if (document.get("metadata") or {}).get("name") != environment:
        errors.append(f"{path.relative_to(ROOT)}: metadata.name must be {environment}")
    spec = document.get("spec") or {}
    if spec.get("environment") != environment:
        errors.append(
            f"{path.relative_to(ROOT)}: spec.environment must be {environment}"
        )
    raw_apps = spec.get("applications") or []
    if not isinstance(raw_apps, list):
        errors.append(f"{path.relative_to(ROOT)}: spec.applications must be a list")
        return {}
    applications: dict[str, dict] = {}
    observed_names: list[str] = []
    for index, application in enumerate(raw_apps):
        label = f"{path.relative_to(ROOT)} applications[{index}]"
        if not isinstance(application, dict):
            errors.append(f"{label}: must be an object")
            continue
        name = str(application.get("name", ""))
        if not APP.fullmatch(name):
            errors.append(f"{label}: invalid application name {name!r}")
        if name in applications:
            errors.append(f"{label}: duplicate application {name}")
        applications[name] = application
        observed_names.append(name)
        images = application.get("images") or []
        if not isinstance(images, list) or not images:
            errors.append(f"{label}: images must be a non-empty list")
            continue
        observed_repositories: list[str] = []
        for image_index, image in enumerate(images):
            image_label = f"{label} images[{image_index}]"
            if not isinstance(image, dict):
                errors.append(f"{image_label}: must be an object")
                continue
            repository = str(image.get("repository", ""))
            digest = str(image.get("digest", ""))
            release_path = str(image.get("releaseMetadata", ""))
            if not REPOSITORY.fullmatch(repository):
                errors.append(f"{image_label}: invalid Artifact Registry repository")
            if not DIGEST.fullmatch(digest):
                errors.append(f"{image_label}: digest must be immutable sha256")
            if repository in observed_repositories:
                errors.append(f"{image_label}: duplicate repository {repository}")
            observed_repositories.append(repository)
            relative = Path(release_path)
            if (
                not release_path.startswith("releases/")
                or relative.suffix != ".json"
                or relative.is_absolute()
                or ".." in relative.parts
            ):
                errors.append(
                    f"{image_label}: releaseMetadata must be a safe releases/*.json path"
                )
                continue
            record_path = ROOT / relative
            try:
                record = json.loads(record_path.read_text(encoding="utf-8"))
                if record.get("image") != f"{repository}@{digest}":
                    errors.append(
                        f"{image_label}: release record does not bind the selected image"
                    )
            except Exception as exc:
                errors.append(f"{image_label}: cannot read release record: {exc}")
        if observed_repositories != sorted(observed_repositories):
            errors.append(f"{label}: images must be sorted by repository")
    if observed_names != sorted(observed_names):
        errors.append(f"{path.relative_to(ROOT)}: applications must be sorted by name")
    return applications


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


def main() -> int:
    errors: list[str] = []
    selections = {
        environment: load_selection(environment, errors) for environment in ENVIRONMENTS
    }
    targets = active_targets(errors)
    for environment, applications in selections.items():
        for name in applications:
            if name not in targets[environment]:
                errors.append(
                    f"{environment} application {name} is not active in render-manifest.yaml"
                )
    if errors:
        for error in sorted(set(errors)):
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    counts = ", ".join(
        f"{environment}={len(selections[environment])}" for environment in ENVIRONMENTS
    )
    print(f"deployment artifact selections passed ({counts})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
