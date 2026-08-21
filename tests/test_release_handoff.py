#!/usr/bin/env python3
# Copyright © 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

"""Behavior tests for the producer-v1 to GitOps-4.0.0 projection."""

from __future__ import annotations

import copy
import datetime as dt
import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/release_contract.py"
SPEC = importlib.util.spec_from_file_location("release_contract", SCRIPT)
assert SPEC and SPEC.loader
CONTRACT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CONTRACT)
FIXTURE_ROOT = ROOT / "contracts/fixtures/release-handoff"
PRODUCER_PATH = (
    FIXTURE_ROOT
    / "evidence/platform-contract-fixture/v1.0.0-contract-fixture.json"
)
CONSUMER_PATH = (
    FIXTURE_ROOT
    / "releases/platform-contract-fixture/v1.0.0-contract-fixture.json"
)


def producer() -> dict:
    return json.loads(PRODUCER_PATH.read_text(encoding="utf-8"))


def consumer() -> dict:
    return json.loads(CONSUMER_PATH.read_text(encoding="utf-8"))


def policy() -> dict:
    return CONTRACT.load_policy(ROOT / "contracts/release-handoff-policy.json")


class ReleaseHandoffTest(unittest.TestCase):
    def test_fixture_is_the_exact_deterministic_projection(self) -> None:
        self.assertEqual(CONTRACT.validate_producer_evidence(producer(), policy()), [])
        self.assertEqual(CONTRACT.projection_errors(FIXTURE_ROOT, consumer(), policy()), [])

    def test_canonical_producer_digest_is_key_order_independent(self) -> None:
        value = producer()
        reordered = {key: value[key] for key in reversed(value)}
        self.assertEqual(CONTRACT.canonical_digest(value), CONTRACT.canonical_digest(reordered))

    def test_consumer_cannot_rewrite_producer_evidence(self) -> None:
        value = consumer()
        value["builder_identity"] = "rewritten-builder"
        errors = CONTRACT.projection_errors(FIXTURE_ROOT, value, policy())
        self.assertIn(
            "release metadata is not the exact deterministic producer projection",
            errors,
        )

    def test_critical_or_high_finding_cannot_claim_pass(self) -> None:
        for severity in ("critical", "high"):
            with self.subTest(severity=severity):
                value = producer()
                value["vulnerability"]["finding_counts"][severity] = 1
                errors = CONTRACT.validate_producer_evidence(value, policy())
                self.assertTrue(any("zero critical, high" in error for error in errors))

    def test_exception_is_exact_digest_security_approved_and_bounded(self) -> None:
        value = producer()
        value["vulnerability"]["result"] = "approved-exception"
        value["vulnerability"]["finding_counts"]["high"] = 1
        value["vulnerability"]["exception"] = {
            "ticket": "SEC-123",
            "approved_by": "@mindclade/security",
            "approved_at": "2026-08-20T00:00:00Z",
            "expires_at": "2026-11-18T00:00:00Z",
            "justification": "Contract fixture only.",
        }
        value["evidence"]["graph"][3]["result"] = "approved"
        self.assertEqual(CONTRACT.validate_producer_evidence(value, policy()), [])
        projected = CONTRACT.project_release_evidence(
            value,
            evidence_path="evidence/platform-contract-fixture/v1.0.0-contract-fixture.json",
            deployment_project="mc-production-security",
            deployment_attestor="deployment-attestor",
            policy=policy(),
        )
        self.assertEqual(
            projected["vulnerability"]["exception"]["subject_digest"],
            value["subject"]["digest"],
        )
        projected["vulnerability"]["exception"]["subject_digest"] = "sha256:" + "9" * 64
        errors = CONTRACT.validate_vulnerability(
            projected["vulnerability"],
            subject_digest=value["subject"]["digest"],
            created_at=dt.datetime(2026, 8, 20, 0, 3, tzinfo=dt.timezone.utc),
            policy=policy(),
            consumer=True,
        )
        self.assertTrue(any("exact release subject digest" in error for error in errors))

    def test_active_selection_rejects_an_expired_exception(self) -> None:
        value = copy.deepcopy(consumer())
        value["vulnerability"]["result"] = "approved-exception"
        value["vulnerability"]["finding_counts"]["high"] = 1
        value["vulnerability"]["exception"] = {
            "ticket": "SEC-123",
            "approved_by": "@mindclade/security",
            "approved_at": "2026-08-20T00:00:00Z",
            "expires_at": "2026-08-21T00:00:00Z",
            "justification": "Contract fixture only.",
            "subject_digest": value["subject"]["digest"],
        }
        errors = CONTRACT.active_exception_errors(
            value, dt.datetime(2026, 8, 22, tzinfo=dt.timezone.utc)
        )
        self.assertEqual(errors, ["selected release vulnerability exception is expired"])


if __name__ == "__main__":
    unittest.main()
