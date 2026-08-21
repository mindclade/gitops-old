#!/usr/bin/env python3
# Copyright © 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

"""Transition tests for trusted v3 quarantine and v4/v5 release validation."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "scripts/validate-release-metadata.py"
SOURCE_REPOSITORY = "mindclade/mindclade-internal-monorepo"
PREFIX = "mindclade/.github/.github/workflows"


def signer_refs(version: str) -> dict[str, str]:
    return {
        "build": f"{PREFIX}/reusable-arc-oci-build.yml@refs/tags/{version}",
        "qualification": (
            f"{PREFIX}/reusable-arc-qualification-attest.yml@refs/tags/{version}"
        ),
        "deployment": f"{PREFIX}/reusable-binauthz-sign.yml@refs/tags/{version}",
    }


def policy(version: str) -> dict:
    return {
        "producer_schema_version": "mindclade.dev/release-evidence/v1",
        "consumer_contract_version": "4.0.0",
        "source_repository": SOURCE_REPOSITORY,
        "signer_workflow_refs": signer_refs(version),
        "evidence_retention": {
            "nonproduction": "P1Y",
            "production": "P7Y",
        },
        "vulnerability_exception": {
            "approved_by": "@mindclade/security",
            "maximum_duration_days": 90,
        },
    }


class ReleaseMetadataTransitionTest(unittest.TestCase):
    def run_validator(
        self,
        root: Path,
        *,
        version: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        images = root / "images.txt"
        images.write_text("", encoding="utf-8")
        command = [
            sys.executable,
            str(VALIDATOR),
            "--root",
            str(root),
            "--images-file",
            str(images),
        ]
        if version is not None:
            refs = signer_refs(version)
            command.extend(
                [
                    "--expected-build-signer-workflow-ref",
                    refs["build"],
                    "--expected-qualification-signer-workflow-ref",
                    refs["qualification"],
                    "--expected-deployment-signer-workflow-ref",
                    refs["deployment"],
                ]
            )
        return subprocess.run(command, capture_output=True, check=False, text=True)

    def copy_v3_quarantine(self, root: Path) -> None:
        (root / "contracts").mkdir()
        (root / "deployments").mkdir()
        (root / "releases").mkdir()
        (root / "contracts/release-metadata.schema.json").write_bytes(
            (ROOT / "contracts/release-metadata.schema.json").read_bytes()
        )
        for environment in ("development", "staging", "production"):
            (root / f"deployments/{environment}.yaml").write_bytes(
                (ROOT / f"deployments/{environment}.yaml").read_bytes()
            )

    def write_empty_v4_contract(self, root: Path, version: str) -> None:
        (root / "contracts").mkdir()
        (root / "releases").mkdir()
        required = sorted(
            {
                "contract_version",
                "release_id",
                "release_kind",
                "subject",
                "source_repository",
                "source_revision",
                "builder_identity",
                "build_invocation_id",
                "images",
                "artifacts",
                "producer_evidence",
                "vulnerability",
                "evidence",
                "attestations",
                "evidence_retention",
                "compatibility",
                "migration",
                "rollback",
                "created_at",
            }
        )
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "required": required,
            "properties": {"contract_version": {"const": "4.0.0"}},
        }
        (root / "contracts/release-metadata.schema.json").write_text(
            json.dumps(schema), encoding="utf-8"
        )
        (root / "contracts/release-handoff-policy.json").write_text(
            json.dumps(policy(version)), encoding="utf-8"
        )

    def test_exact_v3_quarantine_passes(self) -> None:
        with tempfile.TemporaryDirectory() as raw_temp:
            root = Path(raw_temp)
            self.copy_v3_quarantine(root)
            result = self.run_validator(root, version="v3.0.0")
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn("quarantined v3 contract", result.stdout)

    def test_v3_quarantine_schema_drift_fails(self) -> None:
        with tempfile.TemporaryDirectory() as raw_temp:
            root = Path(raw_temp)
            self.copy_v3_quarantine(root)
            schema = root / "contracts/release-metadata.schema.json"
            schema.write_bytes(schema.read_bytes() + b"\n")
            result = self.run_validator(root, version="v3.0.0")
            self.assertNotEqual(0, result.returncode)
            self.assertIn("does not match the reviewed bytes", result.stderr)

    def test_v3_quarantine_rejects_release_records(self) -> None:
        with tempfile.TemporaryDirectory() as raw_temp:
            root = Path(raw_temp)
            self.copy_v3_quarantine(root)
            (root / "releases/untrusted.json").write_text("{}", encoding="utf-8")
            result = self.run_validator(root, version="v3.0.0")
            self.assertNotEqual(0, result.returncode)
            self.assertIn("may not contain release metadata", result.stderr)

    def test_empty_v4_and_v5_transition_contracts_bind_exact_signers(self) -> None:
        for version in ("v4.0.0", "v5.0.0"):
            with (
                self.subTest(version=version),
                tempfile.TemporaryDirectory() as raw_temp,
            ):
                root = Path(raw_temp)
                self.write_empty_v4_contract(root, version)
                result = self.run_validator(root, version=version)
                self.assertEqual(0, result.returncode, result.stderr)

    def test_transition_rejects_signer_policy_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as raw_temp:
            root = Path(raw_temp)
            self.write_empty_v4_contract(root, "v5.0.0")
            result = self.run_validator(root, version="v4.0.0")
            self.assertNotEqual(0, result.returncode)
            self.assertIn("does not match the release handoff policy", result.stderr)


if __name__ == "__main__":
    unittest.main()
