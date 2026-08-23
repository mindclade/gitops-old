#!/usr/bin/env python3
# Copyright © 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

"""Apply one GitOps-owned release selection to Kustomize-rendered YAML on stdin."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

import yaml


SCRIPT_ROOT = Path(__file__).resolve().parents[1]
IMAGE_LINE = re.compile(
    r"(?m)^(?P<prefix>\s*(?:-\s*)?image:\s*)(?P<quote>['\"]?)"
    r"(?P<image>[^\s'\"#]+)(?P=quote)(?P<suffix>\s*(?:#.*)?)$"
)
ARTIFACT_TOKEN = re.compile(
    r"mindclade-artifact-(?P<field>uri|digest)://(?P<name>[a-z][a-z0-9-]{1,62})"
)
RELEASE_TOKEN = re.compile(r"mindclade-release://(?P<field>release-id|subject-digest)")
DIGEST_IMAGE = re.compile(r"[^\s]+@sha256:[0-9a-f]{64}")
SHA256 = re.compile(r"sha256:[0-9a-f]{64}")


def repository_of(image: str) -> str:
    repository = image.split("@", 1)[0]
    last_slash = repository.rfind("/")
    last_colon = repository.rfind(":")
    if last_colon > last_slash:
        repository = repository[:last_colon]
    return repository


def safe_record(root: Path, value: object) -> Path:
    text = str(value or "")
    relative = Path(text)
    if (
        not text.startswith("releases/")
        or relative.suffix != ".json"
        or relative.is_absolute()
        or ".." in relative.parts
        or "\\" in text
    ):
        raise ValueError("releaseMetadata must be a safe releases/*.json path")
    resolved = (root / relative).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError("releaseMetadata escapes the repository root") from exc
    return resolved


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--application", required=True)
    parser.add_argument("--root", type=Path, default=SCRIPT_ROOT)
    parser.add_argument(
        "--allow-staged-production",
        action="store_true",
        help="render a staged production candidate only inside protected qualification",
    )
    args = parser.parse_args()
    text = sys.stdin.read()
    try:
        document = yaml.safe_load(args.selection.read_text(encoding="utf-8")) or {}
        if (
            document.get("apiVersion") != "mindclade.dev/v3"
            or document.get("kind") != "ArtifactDeploymentSet"
        ):
            raise ValueError("artifact selection must be mindclade.dev/v3 ArtifactDeploymentSet")
        spec = document.get("spec") or {}
        applications = spec.get("applications") or []
        selected = next(
            (item for item in applications if item.get("name") == args.application),
            None,
        )
        image_matches = list(IMAGE_LINE.finditer(text))
        has_tokens = ARTIFACT_TOKEN.search(text) is not None or RELEASE_TOKEN.search(text) is not None
        if not image_matches and not has_tokens and selected is None:
            sys.stdout.write(text)
            return 0
        if selected is None:
            raise ValueError(
                f"rendered application {args.application} contains release-controlled references but has no release selection"
            )
        if spec.get("environment") == "production":
            qualified = (
                spec.get("qualificationState") == "qualified-v1"
                and isinstance(spec.get("qualificationHandoff"), str)
            )
            candidate = (
                args.allow_staged_production
                and spec.get("qualificationState") == "staged-v1"
                and spec.get("qualificationHandoff") is None
                and os.environ.get("MINDCLADE_PROTECTED_QUALIFICATION") == "true"
            )
            if not qualified and not candidate:
                raise ValueError(
                    "production selection is not qualified-v1; ordinary rendering is forbidden"
                )
        record_path = safe_record(args.root.resolve(), selected.get("releaseMetadata"))
        record = json.loads(record_path.read_text(encoding="utf-8"))
        if not isinstance(record, dict) or record.get("contract_version") != "4.0.0":
            raise ValueError("selected release metadata must use contract 4.0.0")
        subject = record.get("subject") or {}
        if not isinstance(subject, dict) or subject.get("name") != args.application:
            raise ValueError("selected release subject does not bind the rendered application")

        raw_images = record.get("images") or {}
        if not isinstance(raw_images, dict) or not raw_images:
            raise ValueError("selected release contains no named images")
        mappings: dict[str, str] = {}
        for name, image_value in raw_images.items():
            image = str(image_value)
            if not DIGEST_IMAGE.fullmatch(image):
                raise ValueError(f"invalid release image {name!r}: {image}")
            repository = repository_of(image)
            if repository in mappings:
                raise ValueError(f"release maps repository more than once: {repository}")
            mappings[repository] = image

        raw_artifacts = record.get("artifacts") or []
        artifacts: dict[str, dict] = {}
        for item in raw_artifacts:
            if not isinstance(item, dict):
                raise ValueError("selected release contains a malformed artifact")
            name = str(item.get("name", ""))
            if name in artifacts:
                raise ValueError(f"selected release duplicates artifact {name!r}")
            if not SHA256.fullmatch(str(item.get("digest", ""))):
                raise ValueError(f"selected release artifact {name!r} lacks an immutable digest")
            artifacts[name] = item

        used_images: set[str] = set()

        def replace_image(match: re.Match[str]) -> str:
            original = match.group("image")
            repository = repository_of(original)
            if repository not in mappings:
                raise ValueError(
                    f"rendered image {original} has no mapping in the selected release"
                )
            used_images.add(repository)
            return (
                f"{match.group('prefix')}{match.group('quote')}"
                f"{mappings[repository]}{match.group('quote')}{match.group('suffix')}"
            )

        output = IMAGE_LINE.sub(replace_image, text)
        unused = sorted(set(mappings) - used_images)
        if unused:
            raise ValueError(
                "release images matched no rendered image in "
                f"{args.application}: {', '.join(unused)}"
            )

        def replace_artifact(match: re.Match[str]) -> str:
            name = match.group("name")
            artifact = artifacts.get(name)
            if artifact is None:
                raise ValueError(f"rendered artifact token references unknown artifact {name!r}")
            value = artifact.get(match.group("field"))
            if not isinstance(value, str) or not value:
                raise ValueError(f"release artifact {name!r} has no {match.group('field')}")
            return value

        output = ARTIFACT_TOKEN.sub(replace_artifact, output)

        def replace_release(match: re.Match[str]) -> str:
            if match.group("field") == "release-id":
                value = record.get("release_id")
            else:
                value = subject.get("digest")
            if not isinstance(value, str) or not value:
                raise ValueError(f"selected release has no {match.group('field')}")
            return value

        output = RELEASE_TOKEN.sub(replace_release, output)
        sys.stdout.write(output)
        return 0
    except (OSError, ValueError, json.JSONDecodeError, yaml.YAMLError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
