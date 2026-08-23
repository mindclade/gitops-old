# Copyright © 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

from __future__ import annotations

import copy
import importlib.util
import json
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts/validate-arc-ci.py"
SPEC = importlib.util.spec_from_file_location("validate_arc_ci", MODULE_PATH)
assert SPEC and SPEC.loader
validate_arc_ci = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validate_arc_ci)


class ArcCiContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = yaml.safe_load(
            (ROOT / "arc/presubmit-readiness.yaml").read_text(encoding="utf-8")
        )
        cls.values = yaml.safe_load(
            (ROOT / "arc/values/presubmit.yaml").read_text(encoding="utf-8")
        )
        cls.documents = [
            document
            for document in yaml.safe_load_all(
                (ROOT / "arc/rendered/presubmit.yaml").read_text(encoding="utf-8")
            )
            if isinstance(document, dict)
        ]
        cls.vendor_runner_image = yaml.safe_load(
            (ROOT / "vendor/arc/provenance.yaml").read_text(encoding="utf-8")
        )["spec"]["images"]["runner"]

    def test_repository_contract_is_valid_and_dormant(self) -> None:
        self.assertEqual(validate_arc_ci.validate_all(ROOT), [])

    def test_schema_rejects_unknown_fields(self) -> None:
        contract = copy.deepcopy(self.contract)
        contract["spec"]["unexpected"] = True
        schema = json.loads(
            (ROOT / "contracts/arc-ci-presubmit.schema.json").read_text(
                encoding="utf-8"
            )
        )
        errors = validate_arc_ci.validate_schema(contract, schema)
        self.assertTrue(any("unexpected" in error for error in errors), errors)

    def test_blocked_contract_rejects_nonzero_capacity(self) -> None:
        contract = copy.deepcopy(self.contract)
        values = copy.deepcopy(self.values)
        contract["spec"]["capacity"]["configured"]["maxRunners"] = 1
        values["maxRunners"] = 1
        errors = validate_arc_ci.validate_readiness(
            contract,
            values,
            self.vendor_runner_image,
        )
        self.assertIn("blocked ARC presubmit capacity must remain zero", errors)

    def test_qualified_gate_requires_redacted_evidence(self) -> None:
        contract = copy.deepcopy(self.contract)
        contract["spec"]["gates"]["nixBinaryCache"]["qualified"] = True
        errors = validate_arc_ci.validate_readiness(
            contract,
            self.values,
            self.vendor_runner_image,
        )
        self.assertIn(
            "gate nixBinaryCache must carry evidence exactly when it is qualified",
            errors,
        )

    def test_spot_capacity_cannot_exceed_pool_ceiling(self) -> None:
        contract = copy.deepcopy(self.contract)
        contract["spec"]["capacity"]["activatedTarget"]["maxRunners"] = 25
        errors = validate_arc_ci.validate_readiness(
            contract,
            self.values,
            self.vendor_runner_image,
        )
        self.assertIn(
            "activated capacity must equal the reviewed Spot pool ceiling",
            errors,
        )

    def test_spot_placement_requires_both_taints(self) -> None:
        contract = copy.deepcopy(self.contract)
        values = copy.deepcopy(self.values)
        contract["spec"]["placement"]["tolerations"].pop()
        values["template"]["spec"]["tolerations"].pop()
        errors = validate_arc_ci.validate_readiness(
            contract,
            values,
            self.vendor_runner_image,
        )
        self.assertIn(
            "presubmit placement differs from the dedicated Spot pool contract",
            errors,
        )

    def test_unqualified_runner_image_rejects_invented_coordinates(self) -> None:
        contract = copy.deepcopy(self.contract)
        contract["spec"]["runnerImage"]["digest"] = "sha256:" + ("1" * 64)
        errors = validate_arc_ci.validate_readiness(
            contract,
            self.values,
            self.vendor_runner_image,
        )
        self.assertIn("unqualified runner image fields must remain null", errors)

    def test_render_rejects_shared_writable_storage(self) -> None:
        documents = copy.deepcopy(self.documents)
        scale_set = next(
            document
            for document in documents
            if document.get("kind") == "AutoscalingRunnerSet"
        )
        scale_set["spec"]["template"]["spec"]["volumes"] = [
            {
                "name": "cache",
                "persistentVolumeClaim": {"claimName": "shared-cache"},
            }
        ]
        errors = validate_arc_ci.validate_rendered(
            self.contract,
            self.values,
            documents,
        )
        self.assertIn("rendered presubmit runner contains a shared writable volume", errors)

    def test_render_rejects_runner_credentials(self) -> None:
        documents = copy.deepcopy(self.documents)
        scale_set = next(
            document
            for document in documents
            if document.get("kind") == "AutoscalingRunnerSet"
        )
        runner = scale_set["spec"]["template"]["spec"]["containers"][0]
        runner["envFrom"] = [{"secretRef": {"name": "artifact-signer"}}]
        errors = validate_arc_ci.validate_rendered(
            self.contract,
            self.values,
            documents,
        )
        self.assertIn(
            "rendered presubmit runner contains a credential or volume injection path",
            errors,
        )


if __name__ == "__main__":
    unittest.main()
