#!/usr/bin/env python3
# Copyright © 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

"""Pure behavior tests for connected Binary Authorization policy qualification."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "verify_release_evidence", ROOT / "scripts/verify-release-evidence.py"
)
assert SPEC is not None and SPEC.loader is not None
VERIFY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFY)

PROJECT = "mc-production-platform"
ATTESTOR = "deployment-attestor"
IMAGE = "quay.io/argoproj/argocd@sha256:" + "a" * 64


def valid_policy() -> dict:
    return {
        "globalPolicyEvaluationMode": "ENABLE",
        "defaultAdmissionRule": {
            "evaluationMode": "REQUIRE_ATTESTATION",
            "enforcementMode": "ENFORCED_BLOCK_AND_AUDIT_LOG",
            "requireAttestationsBy": [
                f"projects/{PROJECT}/attestors/{ATTESTOR}"
            ],
        },
        "admissionWhitelistPatterns": [{"namePattern": IMAGE}],
    }


class BinaryAuthorizationPolicyTest(unittest.TestCase):
    def errors(self, value: dict) -> list[str]:
        return VERIFY.policy_errors(value, {IMAGE}, PROJECT, ATTESTOR)

    def test_exact_enforced_policy_passes(self) -> None:
        self.assertEqual(self.errors(valid_policy()), [])

    def test_namespace_or_cluster_rule_fails(self) -> None:
        for key in (
            "clusterAdmissionRules",
            "kubernetesNamespaceAdmissionRules",
        ):
            with self.subTest(key=key):
                value = valid_policy()
                value[key] = {"argocd": {"evaluationMode": "ALWAYS_ALLOW"}}
                self.assertTrue(self.errors(value))

    def test_dry_run_default_fails(self) -> None:
        value = valid_policy()
        value["defaultAdmissionRule"]["enforcementMode"] = "DRYRUN_AUDIT_LOG_ONLY"
        self.assertTrue(self.errors(value))

    def test_extra_or_wildcard_exception_fails(self) -> None:
        value = valid_policy()
        value["admissionWhitelistPatterns"].append(
            {"namePattern": "quay.io/argoproj/*"}
        )
        self.assertTrue(self.errors(value))

    def test_wrong_attestor_fails(self) -> None:
        value = valid_policy()
        value["defaultAdmissionRule"]["requireAttestationsBy"] = [
            f"projects/{PROJECT}/attestors/build-attestor"
        ]
        self.assertTrue(self.errors(value))


if __name__ == "__main__":
    unittest.main()
