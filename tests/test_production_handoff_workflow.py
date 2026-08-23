# Copyright © 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

from __future__ import annotations

import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


class ProductionHandoffWorkflowTest(unittest.TestCase):
    def test_stable_gate_reverifies_the_exact_remote_generation(self) -> None:
        workflow = yaml.safe_load(
            (ROOT / ".github/workflows/production-handoff.yml").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(set(workflow[True]), {"pull_request", "merge_group"})
        jobs = workflow["jobs"]
        connected = jobs["connected"]
        self.assertEqual(connected["environment"], "production")
        self.assertEqual(connected["permissions"]["id-token"], "write")
        command = connected["steps"][-1]["run"]
        self.assertIn('gcloud storage cat "${uri}#${generation}"', command)
        self.assertIn("scripts/production_handoff.py validate", command)
        gate = jobs["production-handoff-gate"]
        self.assertEqual(gate["if"], "always()")
        self.assertEqual(gate["needs"], ["detect", "connected"])

    def test_protected_qualification_emits_the_activation_artifact(self) -> None:
        workflow = (
            ROOT / ".github/workflows/production-qualification-evidence.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("--candidate-digest-output", workflow)
        self.assertIn("--candidate-render-digest-file", workflow)
        self.assertIn("scripts/production_handoff.py create", workflow)
        self.assertIn("production-activation-handoff-", workflow)


if __name__ == "__main__":
    unittest.main()
