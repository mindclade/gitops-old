# Copyright © 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/create-release-promotion.py"
SPEC = importlib.util.spec_from_file_location("promotion", SCRIPT)
assert SPEC and SPEC.loader
PROMOTION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PROMOTION)
EVIDENCE_DIGEST = "sha256:" + "3" * 64


class PromotionTest(unittest.TestCase):
    def run_main(self, root: Path, *arguments: str) -> int:
        with mock.patch.object(PROMOTION, "PROPOSALS", root / "deployments/proposals"):
            with mock.patch.object(PROMOTION.sys, "argv", [str(SCRIPT), *arguments]):
                return PROMOTION.main()

    def test_writes_only_closed_catalog_proposal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            digest = "sha256:" + "1" * 64
            previous_subject = "sha256:" + "2" * 64
            self.assertEqual(
                self.run_main(
                    root,
                    "--release-id", "v1.2.3",
                    "--application", "platform-go-vanity",
                    "--release-kind", "application",
                    "--image-ref", f"us-central1-docker.pkg.dev/mc-common-ci/releases/go-vanity@{digest}",
                    "--source-sha", "a" * 40,
                    "--producer-evidence-digest", EVIDENCE_DIGEST,
                    "--rollback-strategy", "previous-release",
                    "--previous-release-id", "v1.2.2",
                    "--previous-subject-digest", previous_subject,
                ),
                0,
            )
            text = (root / "deployments/proposals/v1.2.3.yaml").read_text()
            self.assertIn("apiVersion: release.mindclade.dev/v1beta2", text)
            self.assertIn("application: platform-go-vanity", text)
            self.assertIn("releaseId: v1.2.2", text)
            self.assertIn(f"subjectDigest: {previous_subject}", text)
            self.assertIn(f"imageRef: us-central1-docker.pkg.dev/mc-common-ci/releases/go-vanity@{digest}", text)
            self.assertIn("releaseMetadata: releases/platform-go-vanity/v1.2.3.json", text)
            self.assertIn(f"producerEvidenceDigest: {EVIDENCE_DIGEST}", text)
            self.assertIn("release.mindclade.dev/spec-digest: sha256:", text)

    def test_rejects_unknown_package(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "closed promotion catalog"):
                self.run_main(
                    Path(directory),
                    "--release-id", "v1.2.3",
                    "--application", "platform-injected",
                    "--release-kind", "application",
                    "--image-ref", "us-central1-docker.pkg.dev/mc-common-ci/releases/injected@sha256:" + "1" * 64,
                    "--source-sha", "a" * 40,
                    "--producer-evidence-digest", EVIDENCE_DIGEST,
                    "--rollback-strategy", "previous-release",
                    "--previous-release-id", "v1.2.2",
                    "--previous-subject-digest", "sha256:" + "2" * 64,
                )

    def test_refuses_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            existing = root / "deployments/proposals/v1.2.3.yaml"
            existing.parent.mkdir(parents=True)
            existing.write_text("existing\n")
            with self.assertRaisesRegex(ValueError, "refusing to replace"):
                self.run_main(
                    root,
                    "--release-id", "v1.2.3",
                    "--application", "platform-go-vanity",
                    "--release-kind", "application",
                    "--image-ref", "us-central1-docker.pkg.dev/mc-common-ci/releases/go-vanity@sha256:" + "1" * 64,
                    "--source-sha", "a" * 40,
                    "--producer-evidence-digest", EVIDENCE_DIGEST,
                    "--rollback-strategy", "previous-release",
                    "--previous-release-id", "v1.2.2",
                    "--previous-subject-digest", "sha256:" + "2" * 64,
                )

    def test_rejects_missing_rollback_lineage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "previous-release-id must be older"):
                self.run_main(
                    Path(directory),
                    "--release-id", "v1.2.3",
                    "--application", "platform-go-vanity",
                    "--release-kind", "application",
                    "--image-ref", "us-central1-docker.pkg.dev/mc-common-ci/releases/go-vanity@sha256:" + "1" * 64,
                    "--source-sha", "a" * 40,
                    "--producer-evidence-digest", EVIDENCE_DIGEST,
                    "--rollback-strategy", "previous-release",
                    "--previous-release-id", "v1.2.3",
                    "--previous-subject-digest", "sha256:" + "2" * 64,
                )

    def test_rejects_catalog_identity_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "release-kind does not match"):
                self.run_main(
                    Path(directory),
                    "--release-id", "v1.2.3",
                    "--application", "platform-go-vanity",
                    "--release-kind", "model",
                    "--image-ref", "us-central1-docker.pkg.dev/mc-common-ci/releases/go-vanity@sha256:" + "1" * 64,
                    "--source-sha", "a" * 40,
                    "--producer-evidence-digest", EVIDENCE_DIGEST,
                    "--rollback-strategy", "previous-release",
                    "--previous-release-id", "v1.2.2",
                    "--previous-subject-digest", "sha256:" + "2" * 64,
                )

    def test_identical_inputs_produce_identical_proposal_bytes(self) -> None:
        arguments = (
            "--release-id", "v1.2.3",
            "--application", "platform-go-vanity",
            "--release-kind", "application",
            "--image-ref", "us-central1-docker.pkg.dev/mc-common-ci/releases/go-vanity@sha256:" + "1" * 64,
            "--source-sha", "a" * 40,
            "--producer-evidence-digest", EVIDENCE_DIGEST,
            "--rollback-strategy", "previous-release",
            "--previous-release-id", "v1.2.2",
            "--previous-subject-digest", "sha256:" + "2" * 64,
        )
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            self.assertEqual(self.run_main(Path(first), *arguments), 0)
            self.assertEqual(self.run_main(Path(second), *arguments), 0)
            first_bytes = Path(first, "deployments/proposals/v1.2.3.yaml").read_bytes()
            second_bytes = Path(second, "deployments/proposals/v1.2.3.yaml").read_bytes()
            self.assertEqual(first_bytes, second_bytes)

    def test_bootstrap_first_release_has_no_previous_lineage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            digest = "sha256:" + "1" * 64
            self.assertEqual(
                self.run_main(
                    root,
                    "--release-id", "v1.0.0",
                    "--application", "platform-go-vanity",
                    "--release-kind", "application",
                    "--image-ref", f"us-central1-docker.pkg.dev/mc-common-ci/releases/go-vanity@{digest}",
                    "--source-sha", "a" * 40,
                    "--producer-evidence-digest", EVIDENCE_DIGEST,
                    "--rollback-strategy", "bootstrap",
                ),
                0,
            )
            text = (root / "deployments/proposals/v1.0.0.yaml").read_text()
            self.assertIn("strategy: bootstrap", text)
            self.assertIn("previousRelease: null", text)
            self.assertIn(
                "bootstrapAction: remove-development-selection-and-restore-blocked-zero-state",
                text,
            )


if __name__ == "__main__":
    unittest.main()
