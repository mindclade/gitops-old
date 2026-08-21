#!/usr/bin/env python3
# Copyright © 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

#
"""Behavior tests for the immutable release-evidence trust contract."""

from __future__ import annotations

import datetime as dt
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "scripts/validate-release-metadata.py"
ATTESTOR_PROJECT = "mindclade-security"
BUILD_ATTESTOR = "build-attestor"
QUALIFICATION_ATTESTOR = "qualification-attestor"
DEPLOYMENT_ATTESTOR = "deployment-attestor"
BUILD_SIGNER_WORKFLOW_REF = (
    "mindclade/.github/.github/workflows/reusable-arc-oci-build.yml@refs/tags/v4.0.0"
)
QUALIFICATION_SIGNER_WORKFLOW_REF = (
    "mindclade/.github/.github/workflows/"
    "reusable-arc-qualification-attest.yml@refs/tags/v4.0.0"
)
DEPLOYMENT_SIGNER_WORKFLOW_REF = (
    "mindclade/.github/.github/workflows/reusable-binauthz-sign.yml@refs/tags/v4.0.0"
)
IMAGE = (
    "us-central1-docker.pkg.dev/mindclade-production/containers/app@sha256:" + "b" * 64
)
CONTRACT_SCRIPT = ROOT / "scripts/release_contract.py"
CONTRACT_SPEC = importlib.util.spec_from_file_location("release_contract", CONTRACT_SCRIPT)
assert CONTRACT_SPEC and CONTRACT_SPEC.loader
CONTRACT = importlib.util.module_from_spec(CONTRACT_SPEC)
CONTRACT_SPEC.loader.exec_module(CONTRACT)
POLICY = CONTRACT.load_policy(ROOT / "contracts/release-handoff-policy.json")
sys.path.insert(0, str(ROOT / "scripts"))
VALIDATOR_SPEC = importlib.util.spec_from_file_location(
    "validate_release_metadata", VALIDATOR
)
assert VALIDATOR_SPEC and VALIDATOR_SPEC.loader
VALIDATOR_MODULE = importlib.util.module_from_spec(VALIDATOR_SPEC)
VALIDATOR_SPEC.loader.exec_module(VALIDATOR_MODULE)
PRODUCER_PATH = "evidence/serving-api/v1.2.3.json"


def valid_producer() -> dict:
    subject_digest = "sha256:" + "f" * 64
    def artifact(name: str, artifact_type: str) -> dict:
        return {
            "name": name,
            "type": artifact_type,
            "uri": f"gs://mindclade-release-evidence/{name}",
            "digest": "sha256:" + "c" * 64,
            "media_type": "application/json",
        }
    return {
        "schema_version": "mindclade.dev/release-evidence/v1",
        "release_id": "v1.2.3",
        "release_kind": "application",
        "subject": {"name": "serving-api", "digest": subject_digest},
        "source_repository": "mindclade/mindclade-internal-monorepo",
        "source_revision": "a" * 40,
        "builder_identity": "mindclade-oci-builder",
        "build_invocation_id": "build-123",
        "images": {"api": IMAGE},
        "artifacts": [
            artifact("build-provenance", "provenance"),
            artifact("qualification-results", "qualification"),
            artifact("rollback-plan", "rollback"),
            artifact("sbom", "sbom"),
            artifact("vulnerability-report", "vulnerability-scan"),
        ],
        "vulnerability": {
            "result": "pass",
            "scanner": "trivy",
            "scanner_version": "1.2.3",
            "database_digest": "sha256:" + "8" * 64,
            "scanned_at": "2026-08-19T22:00:00Z",
            "finding_counts": {
                "critical": 0,
                "high": 0,
                "medium": 0,
                "low": 0,
                "unknown": 0,
            },
            "exception": None,
        },
        "evidence": {
            "result": "pass",
            "policy": {
                "id": "release-policy",
                "version": "4.0.0",
                "digest": "sha256:" + "9" * 64,
            },
            "qualification_epoch": "2026-08-19T23:00:00Z",
            "graph": [
                {
                    "subject_digest": subject_digest,
                    "predicate_type": "build-provenance",
                    "artifact": "build-provenance",
                    "result": "pass",
                },
                {
                    "subject_digest": subject_digest,
                    "predicate_type": "qualification",
                    "artifact": "qualification-results",
                    "result": "pass",
                },
                {
                    "subject_digest": subject_digest,
                    "predicate_type": "sbom",
                    "artifact": "sbom",
                    "result": "pass",
                },
                {
                    "subject_digest": subject_digest,
                    "predicate_type": "vulnerability-scan",
                    "artifact": "vulnerability-report",
                    "result": "pass",
                },
            ],
        },
        "attestations": {
            "build": {
                "project": ATTESTOR_PROJECT,
                "attestor": BUILD_ATTESTOR,
            },
            "qualification": {
                "project": ATTESTOR_PROJECT,
                "attestor": QUALIFICATION_ATTESTOR,
            },
        },
        "compatibility": {
            "kubernetes": ">=1.36.0 <1.37.0",
            "platform_api": "1.0.0",
            "required_capabilities": ["gateway-api", "workload-identity"],
        },
        "migration": {"required": False, "artifact": None},
        "rollback": {
            "strategy": "bootstrap",
            "previous_release_id": None,
            "previous_subject_digest": None,
            "artifact": "rollback-plan",
        },
        "created_at": "2026-08-20T00:00:00Z",
    }


def valid_record() -> dict:
    return CONTRACT.project_release_evidence(
        valid_producer(),
        evidence_path=PRODUCER_PATH,
        deployment_project=ATTESTOR_PROJECT,
        deployment_attestor=DEPLOYMENT_ATTESTOR,
        policy=POLICY,
    )


def exception_producer() -> dict:
    value = valid_producer()
    value["vulnerability"]["result"] = "approved-exception"
    value["vulnerability"]["finding_counts"]["high"] = 1
    value["vulnerability"]["exception"] = {
        "ticket": "SEC-123",
        "approved_by": "@mindclade/security",
        "approved_at": "2026-08-19T23:30:00Z",
        "expires_at": "2026-11-17T23:30:00Z",
        "justification": "Bound contract test exception.",
    }
    value["evidence"]["graph"][3]["result"] = "approved"
    return value


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
    def test_exact_empty_v3_quarantine_is_fail_closed(self) -> None:
        schema_bytes = json.dumps(
            {"properties": {"contract_version": {"const": "3.0.0"}}},
            sort_keys=True,
        ).encode("utf-8")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "contracts").mkdir()
            (root / "releases").mkdir()
            (root / "deployments").mkdir()
            (root / "contracts/release-metadata.schema.json").write_bytes(schema_bytes)
            for environment in ("development", "staging", "production"):
                (root / "deployments" / f"{environment}.yaml").write_text(
                    "\n".join(
                        (
                            "apiVersion: mindclade.dev/v2",
                            "kind: ArtifactDeploymentSet",
                            "metadata:",
                            f"  name: {environment}",
                            "spec:",
                            f"  environment: {environment}",
                            "  applications: []",
                            "",
                        )
                    ),
                    encoding="utf-8",
                )
            images = root / "images.txt"
            images.write_text("", encoding="utf-8")
            errors: list[str] = []
            with mock.patch.object(
                VALIDATOR_MODULE,
                "QUARANTINED_V3_SCHEMA_SHA256",
                hashlib.sha256(schema_bytes).hexdigest(),
            ):
                recognized = VALIDATOR_MODULE.validate_quarantined_v3_contract(
                    root,
                    images,
                    root / "contracts/release-handoff-policy.json",
                    set(),
                    errors,
                )
                self.assertTrue(recognized)
                self.assertEqual(errors, [])

                production = root / "deployments/production.yaml"
                production.write_text(
                    production.read_text(encoding="utf-8").replace(
                        "applications: []", "applications: [{}]"
                    ),
                    encoding="utf-8",
                )
                errors = []
                VALIDATOR_MODULE.validate_quarantined_v3_contract(
                    root,
                    images,
                    root / "contracts/release-handoff-policy.json",
                    set(),
                    errors,
                )
                self.assertTrue(any("must remain empty" in error for error in errors))

    def run_schema_validator(
        self, schema: dict, record: dict | None = None
    ) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "contracts").mkdir()
            (root / "releases").mkdir()
            (root / "contracts/release-handoff-policy.json").write_bytes(
                (ROOT / "contracts/release-handoff-policy.json").read_bytes()
            )
            (root / "contracts/release-metadata.schema.json").write_text(
                json.dumps(schema), encoding="utf-8"
            )
            if record is not None:
                (root / "releases/release.json").write_text(
                    json.dumps(record), encoding="utf-8"
                )
            return subprocess.run(
                [sys.executable, str(VALIDATOR), "--root", str(root)],
                capture_output=True,
                check=False,
                text=True,
            )

    def run_validator(
        self,
        record: dict,
        *,
        active_image: str | None = None,
        exceptions: list[dict] | None = None,
        producer_evidence: dict | None = None,
    ) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "contracts").mkdir()
            (root / "releases").mkdir()
            (root / "contracts/release-metadata.schema.json").write_bytes(
                (ROOT / "contracts/release-metadata.schema.json").read_bytes()
            )
            (root / "contracts/release-handoff-policy.json").write_bytes(
                (ROOT / "contracts/release-handoff-policy.json").read_bytes()
            )
            producer_path = root / PRODUCER_PATH
            producer_path.parent.mkdir(parents=True)
            producer_path.write_text(
                json.dumps(producer_evidence or valid_producer()), encoding="utf-8"
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

    def test_empty_v4_schema_migration_is_trusted(self) -> None:
        required = set(VALIDATOR_MODULE.REQUIRED)
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "required": sorted(required),
            "properties": {"contract_version": {"const": "4.0.0"}},
        }
        result = self.run_schema_validator(schema)
        self.assertEqual(result.returncode, 0, result.stderr)

        result = self.run_schema_validator(schema, {"contract_version": "4.0.0"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            "producer_evidence must identify the immutable producer input",
            result.stderr,
        )

    def test_untrusted_signer_fails(self) -> None:
        record = valid_record()
        record["attestations"]["deployment"]["signer_workflow_ref"] = (
            "mindclade/.github/.github/workflows/reusable-binauthz-sign.yml@refs/tags/v2.9.0"
        )
        result = self.run_validator(record)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not the trusted workflow", result.stderr)

    def test_build_attestor_must_bind_the_immutable_builder_workflow(self) -> None:
        record = valid_record()
        record["attestations"]["build"]["signer_workflow_ref"] = (
            "mindclade/.github/.github/workflows/"
            "reusable-arc-oci-build.yml@refs/tags/v3.9.0"
        )
        result = self.run_validator(record)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("build signer is not the trusted workflow", result.stderr)

    def test_untrusted_binauthz_project_fails(self) -> None:
        record = valid_record()
        record["attestations"]["deployment"]["project"] = (
            "mindclade-development"
        )
        result = self.run_validator(record)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("does not match the configured trust root", result.stderr)

    def test_builder_cannot_be_the_deployment_authority(self) -> None:
        record = valid_record()
        record["attestations"]["deployment"]["attestor"] = BUILD_ATTESTOR
        result = self.run_validator(record)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("attestor roots must be distinct", result.stderr)

    def test_active_digest_without_matching_record_fails(self) -> None:
        other_image = IMAGE[:-1] + "d"
        result = self.run_validator(valid_record(), active_image=other_image)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no release metadata record for active image", result.stderr)

    def test_critical_and_high_findings_fail_closed_without_exception(self) -> None:
        for severity in ("critical", "high"):
            with self.subTest(severity=severity):
                record = valid_record()
                record["vulnerability"]["finding_counts"][severity] = 1
                result = self.run_validator(record)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("zero critical, high", result.stderr)

    def test_exact_digest_bounded_security_exception_passes(self) -> None:
        producer = exception_producer()
        record = CONTRACT.project_release_evidence(
            producer,
            evidence_path=PRODUCER_PATH,
            deployment_project=ATTESTOR_PROJECT,
            deployment_attestor=DEPLOYMENT_ATTESTOR,
            policy=POLICY,
        )
        result = self.run_validator(record, producer_evidence=producer)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_vulnerability_exception_cannot_bind_another_digest(self) -> None:
        producer = exception_producer()
        record = CONTRACT.project_release_evidence(
            producer,
            evidence_path=PRODUCER_PATH,
            deployment_project=ATTESTOR_PROJECT,
            deployment_attestor=DEPLOYMENT_ATTESTOR,
            policy=POLICY,
        )
        record["vulnerability"]["exception"]["subject_digest"] = "sha256:" + "1" * 64
        result = self.run_validator(record, producer_evidence=producer)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("exact release subject digest", result.stderr)

    def test_vulnerability_exception_cannot_exceed_ninety_days(self) -> None:
        producer = exception_producer()
        record = CONTRACT.project_release_evidence(
            producer,
            evidence_path=PRODUCER_PATH,
            deployment_project=ATTESTOR_PROJECT,
            deployment_attestor=DEPLOYMENT_ATTESTOR,
            policy=POLICY,
        )
        record["vulnerability"]["exception"]["expires_at"] = "2027-08-20T00:00:00Z"
        result = self.run_validator(record, producer_evidence=producer)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("within 90 days", result.stderr)

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

    def test_evidence_edge_cannot_bind_another_subject(self) -> None:
        record = valid_record()
        record["evidence"]["graph"][0]["subject_digest"] = "sha256:" + "1" * 64
        result = self.run_validator(record)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("does not bind the subject", result.stderr)

    def test_previous_release_rollback_requires_exact_lineage(self) -> None:
        record = valid_record()
        record["rollback"]["strategy"] = "previous-release"
        result = self.run_validator(record)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("exact prior release ID and subject digest", result.stderr)


if __name__ == "__main__":
    unittest.main()
