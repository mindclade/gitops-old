# Copyright © 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

from __future__ import annotations

import copy
import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "validate_arc_runner_placement",
    ROOT / "scripts/validate-arc-runner-placement.py",
)
assert SPEC is not None and SPEC.loader is not None
VALIDATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATE)


class ArcRunnerPlacementTest(unittest.TestCase):
    def test_repository_contract_passes(self) -> None:
        self.assertEqual(VALIDATE.validate_all(ROOT), [])

    def test_runner_requires_pool_selector_and_toleration(self) -> None:
        spec = {
            "nodeSelector": copy.deepcopy(VALIDATE.EXPECTED_NODE_SELECTOR),
            "tolerations": copy.deepcopy(VALIDATE.EXPECTED_TOLERATIONS),
        }
        spec["nodeSelector"].pop("mindclade.dev/workload-class")
        errors = VALIDATE.validate_runner_spec(spec, "fixture")
        self.assertTrue(any("exact node selector" in error for error in errors), errors)

        spec["nodeSelector"] = copy.deepcopy(VALIDATE.EXPECTED_NODE_SELECTOR)
        spec["tolerations"] = []
        errors = VALIDATE.validate_runner_spec(spec, "fixture")
        self.assertTrue(any("runner-pool toleration" in error for error in errors), errors)

    def test_controller_cannot_follow_runners(self) -> None:
        spec = {
            "nodeSelector": copy.deepcopy(VALIDATE.EXPECTED_NODE_SELECTOR),
            "tolerations": copy.deepcopy(VALIDATE.EXPECTED_TOLERATIONS),
        }
        errors = VALIDATE.validate_controller_spec(spec, "fixture")
        self.assertTrue(any("system pool" in error for error in errors), errors)
        self.assertTrue(any("must not tolerate" in error for error in errors), errors)


if __name__ == "__main__":
    unittest.main()
