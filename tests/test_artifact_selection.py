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
        + f"""apiVersion: mindclade.dev/v1
kind: ArtifactDeploymentSet
metadata:
  name: {environment}
spec:
  environment: {environment}
  applications:{applications}
"""
    )


def application(digest: str) -> str:
    return f"""
    - name: serving-api
      images:
        - repository: {REPOSITORY}
          digest: {digest}
          releaseMetadata: releases/release.json"""


class ArtifactSelectionTest(unittest.TestCase):
    def test_empty_selection_preserves_imageless_render_byte_for_byte(self) -> None:
        rendered = "apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: contract\n"
        with tempfile.TemporaryDirectory() as directory:
            selected = Path(directory) / "development.yaml"
            selected.write_text(selection("development", " []"), encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(APPLY),
                    "--selection",
                    str(selected),
                    "--application",
                    "platform-core",
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
        applications = f"""
    - name: serving-api
      images:
        - repository: {REPOSITORY}
          digest: {DIGEST}
          releaseMetadata: releases/release.json"""
        with tempfile.TemporaryDirectory() as directory:
            selected = Path(directory) / "staging.yaml"
            selected.write_text(selection("staging", applications), encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(APPLY),
                    "--selection",
                    str(selected),
                    "--application",
                    "serving-api",
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
            selected = Path(directory) / "production.yaml"
            selected.write_text(selection("production", " []"), encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(APPLY),
                    "--selection",
                    str(selected),
                    "--application",
                    "serving-api",
                ],
                input=rendered,
                capture_output=True,
                check=False,
                text=True,
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("contains images but has no artifact selection", result.stderr)

    def test_promotion_copies_only_selected_application(self) -> None:
        applications = application(DIGEST)
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
        self.assertIn(f"digest: {DIGEST}", promoted)

    def test_promotion_is_read_only_without_apply(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "staging.yaml"
            target = root / "production.yaml"
            source.write_text(
                selection("staging", application(DIGEST)), encoding="utf-8"
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
        self.assertIn(f"digest: {DIGEST}", result.stdout)

    def test_only_changed_target_apps_must_match_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.yaml"
            target = root / "target.yaml"
            base = root / "base.yaml"
            source.write_text(
                selection("staging", application(DIGEST)), encoding="utf-8"
            )
            target.write_text(
                selection("production", application(DIGEST)), encoding="utf-8"
            )
            base.write_text(
                selection("production", application("sha256:" + "b" * 64)),
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
                selection("staging", application(DIGEST)), encoding="utf-8"
            )
            target.write_text(
                selection("production", application("sha256:" + "c" * 64)),
                encoding="utf-8",
            )
            base.write_text(
                selection("production", application("sha256:" + "b" * 64)),
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
