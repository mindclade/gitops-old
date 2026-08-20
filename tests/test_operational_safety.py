#!/usr/bin/env python3
# Copyright © 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

"""Safety tests for mutating GitOps entrypoints."""

from __future__ import annotations

import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load(name: str, path: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RENDER = load("render", "scripts/render.py")


class GitOpsSafetyTest(unittest.TestCase):
    def test_bootstrap_requires_explicit_apply_before_tool_lookup(self) -> None:
        result = subprocess.run(
            ["bash", str(ROOT / "bootstrap/bootstrap.sh")],
            text=True,
            capture_output=True,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("explicit --apply", result.stderr)

    def test_tree_comparison_detects_extra_generated_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            left, right = root / "left", root / "right"
            left.mkdir()
            right.mkdir()
            (left / "manifest.yaml").write_text("same", encoding="utf-8")
            (right / "manifest.yaml").write_text("same", encoding="utf-8")
            self.assertTrue(RENDER.trees_equal(left, right))
            (right / "extra.yaml").write_text("unexpected", encoding="utf-8")
            self.assertFalse(RENDER.trees_equal(left, right))

    def test_release_evidence_tool_has_no_docker_credential_mutation(self) -> None:
        source = (ROOT / "scripts/verify-release-evidence.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("configure-docker", source)


if __name__ == "__main__":
    unittest.main()
