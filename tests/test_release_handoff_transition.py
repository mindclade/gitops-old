# Copyright © 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

from __future__ import annotations

import importlib.util
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = (
    Path(__file__).resolve().parents[1] / "scripts/select-release-handoff-transition.py"
)
V3_SCHEMA = (
    Path(__file__).resolve().parent
    / "fixtures/release-metadata-3.0.0.schema.json"
)
SPEC = importlib.util.spec_from_file_location("release_handoff_transition", MODULE_PATH)
assert SPEC and SPEC.loader
transition = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(transition)


class ReleaseHandoffTransitionTest(unittest.TestCase):
    def test_exact_absent_policy_v3_quarantine_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as raw_temp:
            contracts = Path(raw_temp) / "contracts"
            contracts.mkdir()
            schema = contracts / "release-metadata.schema.json"
            schema.write_bytes(V3_SCHEMA.read_bytes())
            self.assertEqual(
                transition.QUARANTINED_V3_SCHEMA_SHA256,
                hashlib.sha256(schema.read_bytes()).hexdigest(),
            )
            version, refs = transition.select_policy(
                contracts / "release-handoff-policy.json"
            )
            self.assertEqual("v3.0.0", version)
            self.assertEqual(transition._signer_refs("v3.0.0"), refs)

    def test_absent_policy_with_unreviewed_schema_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw_temp:
            contracts = Path(raw_temp) / "contracts"
            contracts.mkdir()
            (contracts / "release-metadata.schema.json").write_text(
                '{"contract_version":"3.0.0"}', encoding="utf-8"
            )
            with self.assertRaisesRegex(transition.TransitionError, "exact reviewed"):
                transition.select_policy(contracts / "release-handoff-policy.json")

    def test_only_exact_v4_and_v5_policies_are_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as raw_temp:
            root = Path(raw_temp)
            for version, policy in transition.APPROVED_POLICIES.items():
                path = root / f"{version}.json"
                path.write_text(json.dumps(policy), encoding="utf-8")
                selected, refs = transition.select_policy(path)
                self.assertEqual(version, selected)
                self.assertEqual(policy["signer_workflow_refs"], refs)

    def test_policy_field_drift_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw_temp:
            path = Path(raw_temp) / "policy.json"
            candidate = transition._policy("v5.0.0")
            candidate["evidence_retention"]["production"] = "P1D"
            path.write_text(json.dumps(candidate), encoding="utf-8")
            with self.assertRaisesRegex(
                transition.TransitionError, "not an exact approved"
            ):
                transition.select_policy(path)

    def test_outputs_are_complete_and_versioned(self) -> None:
        with tempfile.TemporaryDirectory() as raw_temp:
            output = Path(raw_temp) / "github-output"
            refs = transition.APPROVED_POLICIES["v5.0.0"]["signer_workflow_refs"]
            transition.write_outputs(output, "v5.0.0", refs)
            values = dict(
                line.split("=", 1)
                for line in output.read_text(encoding="utf-8").splitlines()
            )
            self.assertEqual("v5.0.0", values["workflow-version"])
            self.assertEqual(refs["build"], values["build-signer-workflow-ref"])
            self.assertEqual(
                refs["qualification"], values["qualification-signer-workflow-ref"]
            )
            self.assertEqual(
                refs["deployment"], values["deployment-signer-workflow-ref"]
            )


if __name__ == "__main__":
    unittest.main()
