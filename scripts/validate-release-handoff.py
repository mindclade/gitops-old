#!/usr/bin/env python3
# Copyright © 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

"""Validate the canonical producer-v1 to GitOps-4.0.0 compatibility fixture."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import jsonschema

from release_contract import canonical_digest, load_policy, projection_errors


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = REPOSITORY_ROOT / "contracts/fixtures/release-handoff"


def safe_fixture_path(root: Path, value: object, prefix: str) -> Path:
    text = str(value or "")
    relative = Path(text)
    if (
        not text.startswith(prefix + "/")
        or relative.suffix != ".json"
        or relative.is_absolute()
        or ".." in relative.parts
        or "\\" in text
    ):
        raise ValueError(f"fixture {prefix} path is unsafe")
    path = (root / relative).resolve()
    path.relative_to(root.resolve())
    return path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=FIXTURE_ROOT)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument(
        "--schema",
        type=Path,
        default=REPOSITORY_ROOT / "contracts/release-metadata.schema.json",
    )
    parser.add_argument(
        "--policy",
        type=Path,
        default=REPOSITORY_ROOT / "contracts/release-handoff-policy.json",
    )
    args = parser.parse_args()
    root = args.root.resolve()
    manifest_path = args.manifest or root / "manifest.json"
    errors: list[str] = []
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict) or set(manifest) != {
            "producer",
            "consumer",
            "deployment_attestor",
        }:
            raise ValueError("fixture manifest fields are not exact")
        deployment = manifest.get("deployment_attestor")
        if not isinstance(deployment, dict) or set(deployment) != {"project", "attestor"}:
            raise ValueError("fixture deployment_attestor fields are not exact")
        producer_path = safe_fixture_path(root, manifest.get("producer"), "evidence")
        consumer_path = safe_fixture_path(root, manifest.get("consumer"), "releases")
        producer = json.loads(producer_path.read_text(encoding="utf-8"))
        consumer = json.loads(consumer_path.read_text(encoding="utf-8"))
        schema = json.loads(args.schema.read_text(encoding="utf-8"))
        policy = load_policy(args.policy)
        if not isinstance(producer, dict) or not isinstance(consumer, dict):
            raise ValueError("producer and consumer fixtures must be JSON objects")
        expected_ref = consumer.get("producer_evidence") or {}
        if expected_ref.get("path") != producer_path.relative_to(root).as_posix():
            errors.append("consumer fixture does not reference the manifest producer path")
        actual_deployment = (consumer.get("attestations") or {}).get("deployment") or {}
        if actual_deployment.get("project") != deployment.get("project"):
            errors.append("consumer fixture deployment project does not match the manifest")
        if actual_deployment.get("attestor") != deployment.get("attestor"):
            errors.append("consumer fixture deployment attestor does not match the manifest")
        jsonschema.Draft202012Validator.check_schema(schema)
        validator = jsonschema.Draft202012Validator(
            schema, format_checker=jsonschema.FormatChecker()
        )
        for failure in sorted(validator.iter_errors(consumer), key=lambda item: list(item.path)):
            location = ".".join(str(part) for part in failure.path) or "<root>"
            errors.append(f"consumer schema violation at {location}: {failure.message}")
        errors.extend(projection_errors(root, consumer, policy))
    except (OSError, ValueError, json.JSONDecodeError, jsonschema.SchemaError) as exc:
        errors.append(str(exc))
        producer = {}

    if errors:
        for error in sorted(set(errors)):
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(
        "release handoff fixture passed "
        f"(producer={canonical_digest(producer)}, consumer=4.0.0)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
