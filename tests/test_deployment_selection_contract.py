#!/usr/bin/env python3
# Copyright © 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

"""Behavior tests for the v2 one-record-per-application selection contract."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/validate-deployment-selections.py"
sys.path.insert(0, str(SCRIPT.parent))
SPEC = importlib.util.spec_from_file_location("deployment_selections", SCRIPT)
assert SPEC and SPEC.loader
SELECTIONS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SELECTIONS)

CANDIDATE = "sha256:" + "c" * 64
PRODUCER_DIGEST = "sha256:" + "9" * 64
RELEASE_PATH = "releases/serving-api/v1.2.3.json"
IMAGE = "us-central1-docker.pkg.dev/mc-common-ci/releases/api@" + CANDIDATE


def record(application: str = "serving-api") -> dict:
    return {
        "contract_version": "4.0.0",
        "release_id": "v1.2.3",
        "release_kind": "application",
        "source_revision": "d" * 40,
        "subject": {"name": application, "digest": CANDIDATE},
        "images": {"api": IMAGE},
        "producer_evidence": {
            "schema_version": "mindclade.dev/release-evidence/v1",
            "path": "evidence/serving-api/v1.2.3.json",
            "digest": PRODUCER_DIGEST,
        },
        "vulnerability": {
            "result": "pass",
            "finding_counts": {
                "critical": 0,
                "high": 0,
                "medium": 0,
                "low": 0,
                "unknown": 0,
            },
            "exception": None,
        },
        "evidence_retention": {"nonproduction": "P1Y", "production": "P7Y"},
        "rollback": {
            "strategy": "previous-release",
            "previous_release_id": "v1.2.2",
            "previous_subject_digest": "sha256:" + "e" * 64,
            "artifact": "rollback-plan",
        },
    }


def selection(application: dict) -> dict:
    return {
        "apiVersion": "mindclade.dev/v2",
        "kind": "ArtifactDeploymentSet",
        "metadata": {"name": "development"},
        "spec": {"environment": "development", "applications": [application]},
    }


def proposal() -> dict:
    spec = {
        "target": {
            "application": "serving-api",
            "releaseKind": "application",
            "releaseMetadata": RELEASE_PATH,
            "imageRef": IMAGE,
            "subjectDigest": CANDIDATE,
            "producerEvidenceDigest": PRODUCER_DIGEST,
        },
        "sourceRepository": "mindclade/mindclade-internal-monorepo",
        "sourceRevision": "d" * 40,
        "rollback": {
            "strategy": "previous-release",
            "previousRelease": {
                "releaseId": "v1.2.2",
                "subjectDigest": "sha256:" + "e" * 64,
            },
            "bootstrapAction": None,
        },
        "targetEnvironment": "development",
        "requiredEvidence": sorted(SELECTIONS.REQUIRED_PROPOSAL_EVIDENCE),
    }
    return {
        "apiVersion": "release.mindclade.dev/v1beta2",
        "kind": "PromotionProposal",
        "metadata": {
            "name": "v1.2.3",
            "annotations": {
                "release.mindclade.dev/consumer-contract": "4.0.0",
                "release.mindclade.dev/producer-schema": "mindclade.dev/release-evidence/v1",
                "release.mindclade.dev/spec-digest": SELECTIONS.canonical_spec_digest(spec),
            },
        },
        "spec": spec,
    }


class DeploymentSelectionContractTest(unittest.TestCase):
    def validate(self, document: dict, release: dict | None = None) -> list[str]:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "deployments").mkdir()
            (root / "releases").mkdir()
            (root / "deployments/development.yaml").write_text(
                yaml.safe_dump(document, sort_keys=False), encoding="utf-8"
            )
            if release is not None:
                release_path = root / RELEASE_PATH
                release_path.parent.mkdir(parents=True)
                release_path.write_text(
                    json.dumps(release), encoding="utf-8"
                )
                proposal_path = root / "deployments/proposals/v1.2.3.yaml"
                proposal_path.parent.mkdir(parents=True)
                proposal_path.write_text(
                    yaml.safe_dump(proposal(), sort_keys=False), encoding="utf-8"
                )
            errors: list[str] = []
            with mock.patch.object(SELECTIONS, "ROOT", root):
                SELECTIONS.load_selection("development", errors)
            return errors

    def test_one_release_record_binds_the_application(self) -> None:
        errors = self.validate(
            selection(
                {
                    "name": "serving-api",
                    "releaseMetadata": RELEASE_PATH,
                }
            ),
            record(),
        )
        self.assertEqual(errors, [])

    def test_v3_transition_preserves_trusted_release_validation(self) -> None:
        document = selection(
            {
                "name": "serving-api",
                "releaseMetadata": RELEASE_PATH,
            }
        )
        document["apiVersion"] = "mindclade.dev/v3"
        document["spec"]["qualificationState"] = None
        document["spec"]["qualificationHandoff"] = None
        self.assertEqual(self.validate(document, record()), [])

    def test_inline_image_selection_is_rejected(self) -> None:
        errors = self.validate(
            selection(
                {
                    "name": "serving-api",
                    "images": [{"repository": "example.invalid/api", "digest": "sha256:" + "c" * 64}],
                }
            )
        )
        self.assertTrue(any("unsupported fields" in error for error in errors))
        self.assertTrue(any("missing fields" in error for error in errors))

    def test_release_subject_cannot_bind_another_application(self) -> None:
        errors = self.validate(
            selection(
                {
                    "name": "serving-api",
                    "releaseMetadata": RELEASE_PATH,
                }
            ),
            record("platform-core"),
        )
        self.assertTrue(any("does not bind application" in error for error in errors))

    def test_release_path_cannot_escape_repository(self) -> None:
        errors = self.validate(
            selection(
                {
                    "name": "serving-api",
                    "releaseMetadata": "releases/../outside.json",
                }
            )
        )
        self.assertTrue(any("safe releases" in error for error in errors))

    def validate_proposal(self, value: dict) -> list[str]:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "deployments/proposals").mkdir(parents=True)
            (root / "deployments/proposals/v1.2.3.yaml").write_text(
                yaml.safe_dump(value, sort_keys=False), encoding="utf-8"
            )
            errors: list[str] = []
            with mock.patch.object(SELECTIONS, "ROOT", root):
                count = SELECTIONS.validate_promotion_proposals(errors)
            self.assertEqual(count, 1)
            return errors

    def test_complete_promotion_proposal_passes(self) -> None:
        self.assertEqual(self.validate_proposal(proposal()), [])

    def test_promotion_proposal_cannot_change_previous_lineage(self) -> None:
        value = proposal()
        value["spec"]["rollback"]["previousRelease"]["subjectDigest"] = value["spec"]["target"]["subjectDigest"]
        errors = self.validate_proposal(value)
        self.assertTrue(any("candidate and previous" in error for error in errors))

    def test_promotion_proposal_cannot_drop_evidence(self) -> None:
        value = proposal()
        value["spec"]["requiredEvidence"].remove("vulnerability-scan")
        errors = self.validate_proposal(value)
        self.assertTrue(any("complete governed evidence" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
