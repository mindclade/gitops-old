#!/usr/bin/env python3
# Copyright © 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

"""Canonical parity and mutation tests for production eligibility evidence."""

from __future__ import annotations

import base64
import copy
import importlib.util
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "production_eligibility", ROOT / "scripts/production_eligibility.py"
)
assert SPEC is not None and SPEC.loader is not None
ELIGIBILITY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ELIGIBILITY)

POLICY_PATH = ROOT / "contracts/evidence/production-controls.json"
EXPECTED_POLICY_DIGEST = (
    "sha256:affcc099bf4e423232e9176d2f77c9d08e0d4fd4eac6d4fb926a9abe85aa5326"
)
EXPECTED_BUNDLE_DIGEST = (
    "sha256:8790176a9a3f68f6830e4fea9a5132d4e2c1166a46e0e0d51f694a62657eac6e"
)
EXPECTED_SOURCE_CI_CLAIM = (
    "sha256:d6d7560f3f24232414aa92831d0912be51b7dce7f2b6e5f0b6bda1248b79828c"
)
EXPECTED_SOURCE_CI_VERIFICATION = (
    "sha256:d68fe9f18b012170a6f4d62c3bb0047e95e4669959bd83d5f12f068f80c8d175"
)
EXPECTED_DECISION_DIGEST = (
    "sha256:5f41137dc4380fbb543420c62a515397915fb4956e74cdc6fca1956434141fbd"
)


def bundle_fixture() -> dict:
    bundle = {
        "schema_version": ELIGIBILITY.SCHEMA_BUNDLE,
        "bundle_digest": "",
        "change_reference": "CHG-123",
        "environment": "production",
        "repositories": [
            {"repository": repository, "commit": "0" * 40}
            for repository in ELIGIBILITY.REPOSITORIES
        ],
        "release_digests": ["sha256:" + "a" * 64],
        "gitops_render_digest": "sha256:" + "b" * 64,
        "deployment_selection_digest": "sha256:" + "c" * 64,
        "infrastructure_handoff_digest": "sha256:" + "d" * 64,
        "governance_audit_digest": "sha256:" + "e" * 64,
        "workflow_release": "v1.0.0",
        "policy_bundle_digest": "sha256:" + "f" * 64,
    }
    bundle["bundle_digest"] = ELIGIBILITY.digest_bytes(
        ELIGIBILITY.canonical_bundle(bundle)
    )
    return bundle


def records_fixture(bundle: dict, policy: dict) -> dict:
    return ELIGIBILITY.build_records(
        {
            "checks": [
                {
                    "control_id": control["id"],
                    "status": "pass",
                    "evidence_key": "connected-control-plane",
                }
                for control in policy["controls"]
            ],
            "evidence_artifacts": [
                {"key": "connected-control-plane", "sha256": "1" * 64}
            ],
        },
        bundle,
        policy,
        "gs://fixture/root",
        datetime(2026, 8, 22, 12, tzinfo=timezone.utc),
    )


def response_fixture(bundle: dict, policy: dict, records: dict) -> dict:
    decision = {
        "schema_version": ELIGIBILITY.SCHEMA_DECISION,
        "decision_digest": "",
        "bundle_digest": bundle["bundle_digest"],
        "policy_digest": policy["digest"],
        "policy_epoch": policy["epoch"],
        "result": "eligible",
        "reasons": [],
        "selections": [
            {
                "control_id": record["claim"]["control_id"],
                "claim_digest": record["claim"]["claim_digest"],
                "verification_digest": record["verification"][
                    "verification_digest"
                ],
            }
            for record in records["records"]
        ],
        "exceptions": [],
        "evaluated_at": "2026-08-22T12:00:00Z",
        "expires_at": "2026-08-22T13:00:00Z",
    }
    decision["decision_digest"] = ELIGIBILITY.digest_bytes(
        ELIGIBILITY.canonical_decision(decision)
    )
    return {
        "signed_decision": {
            "decision": decision,
            "signature": {
                "algorithm": "ed25519",
                "key_id": "production-eligibility-v1",
                "value": base64.b64encode(bytes(64)).decode("ascii"),
            },
        },
        "revoked": False,
    }


class CanonicalEligibilityTest(unittest.TestCase):
    def test_policy_and_cross_language_vectors_are_stable(self) -> None:
        policy = ELIGIBILITY.load_policy(POLICY_PATH)
        self.assertEqual(policy["digest"], EXPECTED_POLICY_DIGEST)
        bundle = bundle_fixture()
        ELIGIBILITY.validate_bundle(bundle)
        self.assertEqual(bundle["bundle_digest"], EXPECTED_BUNDLE_DIGEST)
        records = records_fixture(bundle, policy)
        source_ci = next(
            record
            for record in records["records"]
            if record["claim"]["control_id"] == "source_ci"
        )
        self.assertEqual(source_ci["claim"]["claim_digest"], EXPECTED_SOURCE_CI_CLAIM)
        self.assertEqual(
            source_ci["verification"]["verification_digest"],
            EXPECTED_SOURCE_CI_VERIFICATION,
        )

    def test_policy_and_bundle_mutations_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
            policy["controls"][0]["owner"] = "other"
            path = Path(directory) / "policy.json"
            path.write_text(json.dumps(policy), encoding="utf-8")
            with self.assertRaises(ValueError):
                ELIGIBILITY.load_policy(path)

        bundle = bundle_fixture()
        bundle["change_reference"] = "CHG-tampered"
        with self.assertRaises(ValueError):
            ELIGIBILITY.validate_bundle(bundle)

    def test_signed_response_is_exact_and_tamper_evident(self) -> None:
        policy = ELIGIBILITY.load_policy(POLICY_PATH)
        bundle = bundle_fixture()
        records = records_fixture(bundle, policy)
        response = response_fixture(bundle, policy, records)
        self.assertEqual(
            response["signed_decision"]["decision"]["decision_digest"],
            EXPECTED_DECISION_DIGEST,
        )
        with tempfile.TemporaryDirectory() as directory:
            payload = Path(directory) / "payload.bin"
            signature = Path(directory) / "signature.bin"
            self.assertEqual(
                ELIGIBILITY.verify_response(
                    response,
                    bundle,
                    policy,
                    "production-eligibility-v1",
                    payload,
                    signature,
                ),
                EXPECTED_DECISION_DIGEST,
            )
            self.assertEqual(len(signature.read_bytes()), 64)

            mutations = (
                lambda value: value.update(revoked=True),
                lambda value: value["signed_decision"]["decision"].update(
                    result="ineligible"
                ),
                lambda value: value["signed_decision"]["decision"][
                    "selections"
                ].pop(),
                lambda value: value["signed_decision"]["signature"].update(
                    key_id="other-key"
                ),
                lambda value: value["signed_decision"]["decision"].update(
                    unexpected=True
                ),
            )
            for mutate in mutations:
                candidate = copy.deepcopy(response)
                mutate(candidate)
                with self.assertRaises(ValueError):
                    ELIGIBILITY.verify_response(
                        candidate,
                        bundle,
                        policy,
                        "production-eligibility-v1",
                        payload,
                        signature,
                    )


if __name__ == "__main__":
    unittest.main()
