# Copyright © 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

from __future__ import annotations

import copy
import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "validate_workstation_image_readiness",
    ROOT / "scripts/validate-workstation-image-readiness.py",
)
assert SPEC is not None and SPEC.loader is not None
VALIDATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATE)


class WorkstationImageReadinessTest(unittest.TestCase):
    def setUp(self) -> None:
        self.contract = VALIDATE.load()

    def test_checked_in_contract_is_fail_closed(self) -> None:
        self.assertEqual(VALIDATE.errors(self.contract), [])

    def test_connected_claim_without_evidence_is_rejected(self) -> None:
        candidate = copy.deepcopy(self.contract)
        candidate["spec"]["connectedGates"]["computeImageApplied"] = True
        self.assertTrue(any("connected gates" in e for e in VALIDATE.errors(candidate)))

    def test_gitops_may_not_claim_infrastructure_authority(self) -> None:
        candidate = copy.deepcopy(self.contract)
        candidate["spec"]["authority"]["gitopsRole"] = "compute-image-owner"
        self.assertTrue(any("authority boundary" in e for e in VALIDATE.errors(candidate)))

    def test_selection_requires_a_separate_evidence_transition(self) -> None:
        candidate = copy.deepcopy(self.contract)
        candidate["spec"]["activation"]["selected"] = True
        self.assertTrue(any("may not reconcile" in e for e in VALIDATE.errors(candidate)))


if __name__ == "__main__":
    unittest.main()
