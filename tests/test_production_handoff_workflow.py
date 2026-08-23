# Copyright © 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "validate_production_handoff_workflow",
    ROOT / "scripts/validate-production-handoff-workflow.py",
)
assert SPEC is not None and SPEC.loader is not None
VALIDATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATE)


class ProductionHandoffWorkflowTest(unittest.TestCase):
    def test_stable_gate_uses_base_trusted_connected_verification(self) -> None:
        path = ROOT / ".github/workflows/production-handoff.yml"
        self.assertEqual(VALIDATE.validate_workflow(path), [])
        workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
        self.assertEqual(set(workflow[True]), {"pull_request_target", "merge_group"})
        jobs = workflow["jobs"]
        connected = jobs["connected"]
        self.assertEqual(connected["environment"], "production")
        self.assertEqual(connected["permissions"]["id-token"], "write")
        self.assertIn("pull_request_target", connected["if"])
        command = "\n".join(str(step.get("run", "")) for step in connected["steps"])
        self.assertIn('gcloud storage cat "${uri}#${generation}"', command)
        self.assertIn(".trusted/scripts/production_handoff.py validate", command)
        self.assertIn("--root .candidate", command)
        offline = jobs["merge-group-offline"]
        self.assertEqual(offline["permissions"], {"contents": "read"})
        self.assertNotIn("environment", offline)
        gate = jobs["production-handoff-gate"]
        self.assertEqual(gate["if"], "always()")
        self.assertEqual(gate["needs"], ["detect", "connected", "merge-group-offline"])

    def test_normal_pull_request_trigger_is_rejected(self) -> None:
        source = (ROOT / ".github/workflows/production-handoff.yml").read_text(
            encoding="utf-8"
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "workflow.yml"
            path.write_text(
                source.replace("  pull_request_target:\n", "  pull_request:\n", 1),
                encoding="utf-8",
            )
            errors = VALIDATE.validate_workflow(path)
        self.assertTrue(any("trusted digest" in error for error in errors), errors)
        self.assertTrue(
            any("events must be exactly" in error for error in errors), errors
        )

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
