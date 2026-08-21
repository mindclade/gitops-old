#!/usr/bin/env python3
# Copyright © 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

#
"""Behavior tests for the immutable release-evidence trust contract."""

from __future__ import annotations

import datetime as dt
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "scripts/validate-release-metadata.py"
ATTESTOR_PROJECT = "mindclade-security"
BUILD_ATTESTOR = "build-attestor"
QUALIFICATION_ATTESTOR = "qualification-attestor"
DEPLOYMENT_ATTESTOR = "deployment-attestor"
SIGNER_WORKFLOW_REF = (
    "mindclade/.github/.github/workflows/reusable-binauthz-sign.yml@refs/tags/v3.0.0"
)
IMAGE = (
    "us-central1-docker.pkg.dev/mindclade-production/containers/app@sha256:" + "b" * 64
)


def valid_record() -> dict:
    artifact = {
        "uri": "gs://mindclade-release-evidence/object",
        "digest": "sha256:" + "c" * 64,
    }
    return {
        "contract_version": "3.0.0",
        "release_id": "release-1",
        "source_repository": "mindclade/mindclade-internal-monorepo",
        "source_revision": "a" * 40,
        "builder_identity": "mindclade-oci-builder",
        "build_invocation_id": "build-123",
        "image": IMAGE,
        "sbom": artifact,
        "provenance": artifact,
        "vulnerability": {"result": "pass", "scanner": "osv", "evidence": artifact},
        "qualification": {"result": "pass", "evidence": artifact},
        "supply_chain_attestations": {
            "build": {"project": ATTESTOR_PROJECT, "attestor": BUILD_ATTESTOR},
            "qualification": {
                "project": ATTESTOR_PROJECT,
                "attestor": QUALIFICATION_ATTESTOR,
            },
            "deployment": {
                "project": ATTESTOR_PROJECT,
                "attestor": DEPLOYMENT_ATTESTOR,
                "signer_workflow_ref": SIGNER_WORKFLOW_REF,
            },
        },
        "created_at": "2026-08-20T00:00:00Z",
    }


def valid_exception(image: str) -> dict:
    granted = dt.date.today()
    return {
        "image": image,
        "owner": "@mindclade/platform",
        "reason": "Reviewed upstream GitOps control-plane runtime.",
        "scope": {
            "component": "argocd-control-plane",
            "environments": ["staging", "production"],
        },
        "granted": granted.isoformat(),
        "expires": (granted + dt.timedelta(days=90)).isoformat(),
        "reviewer": "@mindclade/security",
        "approval": "required-protected-security-review",
        "change": "protected-gitops-and-infrastructure-live-pull-requests",
        "removal": "Replace with a mirrored and attested digest.",
    }


class ReleaseMetadataContractTest(unittest.TestCase):
    def run_validator(
        self,
        record: dict,
        *,
        active_image: str | None = None,
        exceptions: list[dict] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "contracts").mkdir()
            (root / "releases").mkdir()
            (root / "contracts/release-metadata.schema.json").write_bytes(
                (ROOT / "contracts/release-metadata.schema.json").read_bytes()
            )
            (root / "releases/release.json").write_text(
                json.dumps(record), encoding="utf-8"
            )
            command = [
                sys.executable,
                str(VALIDATOR),
                "--root",
                str(root),
                "--expected-deployment-attestor-project",
                ATTESTOR_PROJECT,
                "--expected-deployment-attestor",
                DEPLOYMENT_ATTESTOR,
            ]
            if active_image is not None:
                images = root / "images.txt"
                images.write_text(active_image + "\n", encoding="utf-8")
                command.extend(["--images-file", str(images)])
            if exceptions is not None:
                exception_file = root / "unsigned-exceptions.json"
                exception_file.write_text(json.dumps(exceptions), encoding="utf-8")
                command.extend(["--unsigned-exceptions-file", str(exception_file)])
            return subprocess.run(command, capture_output=True, check=False, text=True)

    def test_trusted_complete_record_passes(self) -> None:
        result = self.run_validator(valid_record(), active_image=IMAGE)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_untrusted_signer_fails(self) -> None:
        record = valid_record()
        record["supply_chain_attestations"]["deployment"]["signer_workflow_ref"] = (
            "mindclade/.github/.github/workflows/reusable-binauthz-sign.yml@refs/tags/v2.9.0"
        )
        result = self.run_validator(record)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not the trusted workflow", result.stderr)

    def test_untrusted_binauthz_project_fails(self) -> None:
        record = valid_record()
        record["supply_chain_attestations"]["deployment"]["project"] = (
            "mindclade-development"
        )
        result = self.run_validator(record)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("does not match the configured trust root", result.stderr)

    def test_builder_cannot_be_the_deployment_authority(self) -> None:
        record = valid_record()
        record["supply_chain_attestations"]["deployment"]["attestor"] = BUILD_ATTESTOR
        result = self.run_validator(record)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("attestor roots must be distinct", result.stderr)

    def test_active_digest_without_matching_record_fails(self) -> None:
        other_image = IMAGE[:-1] + "d"
        result = self.run_validator(valid_record(), active_image=other_image)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no release metadata record for active image", result.stderr)

    def test_governed_control_plane_exception_replaces_release_record(self) -> None:
        upstream = "quay.io/argoproj/argocd@sha256:" + "d" * 64
        result = self.run_validator(
            valid_record(),
            active_image=upstream,
            exceptions=[valid_exception(upstream)],
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_orphaned_control_plane_exception_fails(self) -> None:
        upstream = "quay.io/argoproj/argocd@sha256:" + "d" * 64
        result = self.run_validator(
            valid_record(),
            active_image=IMAGE,
            exceptions=[valid_exception(upstream)],
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not an active control-plane image", result.stderr)

    def test_expired_control_plane_exception_fails(self) -> None:
        upstream = "quay.io/argoproj/argocd@sha256:" + "d" * 64
        exception = valid_exception(upstream)
        exception["granted"] = "2025-01-01"
        exception["expires"] = "2025-03-01"
        result = self.run_validator(
            valid_record(),
            active_image=upstream,
            exceptions=[exception],
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("is expired", result.stderr)


if __name__ == "__main__":
    unittest.main()
