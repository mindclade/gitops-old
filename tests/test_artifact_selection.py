#!/usr/bin/env python3
# Copyright © 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

#
"""Behavior tests for digest-only render selection and adjacent promotion."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APPLY = ROOT / "scripts/apply-artifact-selection.py"
PROMOTE = ROOT / "scripts/promote-artifacts.py"
PROMOTION_CHANGE = ROOT / "scripts/validate-promotion-change.py"
REPOSITORY = "us-central1-docker.pkg.dev/mindclade-production/containers/api"
DIGEST = "sha256:" + "d" * 64
HEADER = """# Copyright © 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

---
"""


def selection(environment: str, applications: str) -> str:
    return (
        HEADER
        + f"""apiVersion: mindclade.dev/v2
kind: ArtifactDeploymentSet
metadata:
  name: {environment}
spec:
  environment: {environment}
  applications:{applications}
"""
    )


def application(release: str = "releases/release.json") -> str:
    return f"""
    - name: serving-api
      releaseMetadata: {release}"""


def release_record() -> dict:
    return {
        "contract_version": "4.0.0",
        "release_id": "v1.2.3",
        "subject": {"name": "serving-api", "digest": "sha256:" + "a" * 64},
        "images": {"api": f"{REPOSITORY}@{DIGEST}"},
        "artifacts": [
            {
                "name": "model",
                "type": "model",
                "uri": "gs://mindclade-models/model#1",
                "digest": "sha256:" + "e" * 64,
            }
        ],
    }


def write_release_root(root: Path, environment: str, applications: str) -> Path:
    (root / "deployments").mkdir()
    (root / "releases").mkdir()
    selected = root / "deployments" / f"{environment}.yaml"
    selected.write_text(selection(environment, applications), encoding="utf-8")
    (root / "releases/release.json").write_text(
        json.dumps(release_record()), encoding="utf-8"
    )
    return selected


class ArtifactSelectionTest(unittest.TestCase):
    def test_empty_selection_preserves_imageless_render_byte_for_byte(self) -> None:
        rendered = "apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: contract\n"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            selected = write_release_root(root, "development", " []")
            result = subprocess.run(
                [
                    sys.executable,
                    str(APPLY),
                    "--selection",
                    str(selected),
                    "--application",
                    "platform-core",
                    "--root",
                    str(root),
                ],
                input=rendered,
                capture_output=True,
                check=False,
                text=True,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, rendered)

    def test_selected_digest_replaces_tag(self) -> None:
        rendered = f"apiVersion: v1\nkind: Pod\nspec:\n  containers:\n    - name: api\n      image: {REPOSITORY}:candidate\n"
        applications = application()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            selected = write_release_root(root, "staging", applications)
            result = subprocess.run(
                [
                    sys.executable,
                    str(APPLY),
                    "--selection",
                    str(selected),
                    "--application",
                    "serving-api",
                    "--root",
                    str(root),
                ],
                input=rendered,
                capture_output=True,
                check=False,
                text=True,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"image: {REPOSITORY}@{DIGEST}", result.stdout)
        self.assertNotIn(":candidate", result.stdout)

    def test_image_without_selection_fails_closed(self) -> None:
        rendered = f"image: {REPOSITORY}:candidate\n"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            selected = write_release_root(root, "production", " []")
            result = subprocess.run(
                [
                    sys.executable,
                    str(APPLY),
                    "--selection",
                    str(selected),
                    "--application",
                    "serving-api",
                    "--root",
                    str(root),
                ],
                input=rendered,
                capture_output=True,
                check=False,
                text=True,
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("has no release selection", result.stderr)

    def test_release_and_artifact_tokens_are_bound_from_the_same_record(self) -> None:
        rendered = (
            "apiVersion: v1\nkind: ConfigMap\ndata:\n"
            '  model-uri: "mindclade-artifact-uri://model"\n'
            '  model-digest: "mindclade-artifact-digest://model"\n'
            '  release: "mindclade-release://release-id"\n'
            '  subject: "mindclade-release://subject-digest"\n'
            f"  image: {REPOSITORY}:candidate\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            selected = write_release_root(root, "staging", application())
            result = subprocess.run(
                [
                    sys.executable,
                    str(APPLY),
                    "--selection",
                    str(selected),
                    "--application",
                    "serving-api",
                    "--root",
                    str(root),
                ],
                input=rendered,
                capture_output=True,
                check=False,
                text=True,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("gs://mindclade-models/model#1", result.stdout)
        self.assertIn("sha256:" + "e" * 64, result.stdout)
        self.assertIn("v1.2.3", result.stdout)
        self.assertIn("sha256:" + "a" * 64, result.stdout)

    def test_promotion_copies_only_selected_application(self) -> None:
        applications = application()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "staging.yaml"
            target = root / "production.yaml"
            source.write_text(selection("staging", applications), encoding="utf-8")
            target.write_text(selection("production", " []"), encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(PROMOTE),
                    "--source",
                    str(source),
                    "--target",
                    str(target),
                    "--application",
                    "serving-api",
                    "--apply",
                ],
                capture_output=True,
                check=False,
                text=True,
            )
            promoted = target.read_text(encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("name: production", promoted)
        self.assertIn("releaseMetadata: releases/release.json", promoted)

    def test_promotion_is_read_only_without_apply(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "staging.yaml"
            target = root / "production.yaml"
            source.write_text(
                selection("staging", application()), encoding="utf-8"
            )
            original = selection("production", " []")
            target.write_text(original, encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(PROMOTE),
                    "--source",
                    str(source),
                    "--target",
                    str(target),
                    "--application",
                    "serving-api",
                ],
                capture_output=True,
                check=False,
                text=True,
            )
            self.assertEqual(target.read_text(encoding="utf-8"), original)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("releaseMetadata: releases/release.json", result.stdout)

    def test_only_changed_target_apps_must_match_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.yaml"
            target = root / "target.yaml"
            base = root / "base.yaml"
            source.write_text(
                selection("staging", application("releases/release-d.json")), encoding="utf-8"
            )
            target.write_text(
                selection("production", application("releases/release-d.json")), encoding="utf-8"
            )
            base.write_text(
                selection("production", application("releases/release-b.json")),
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(PROMOTION_CHANGE),
                    "--source",
                    str(source),
                    "--target",
                    str(target),
                    "--base-target",
                    str(base),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_changed_target_app_cannot_skip_adjacent_environment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.yaml"
            target = root / "target.yaml"
            base = root / "base.yaml"
            source.write_text(
                selection("staging", application("releases/release-d.json")), encoding="utf-8"
            )
            target.write_text(
                selection("production", application("releases/release-c.json")),
                encoding="utf-8",
            )
            base.write_text(
                selection("production", application("releases/release-b.json")),
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(PROMOTION_CHANGE),
                    "--source",
                    str(source),
                    "--target",
                    str(target),
                    "--base-target",
                    str(base),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("does not exactly match", result.stderr)


if __name__ == "__main__":
    unittest.main()
