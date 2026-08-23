# Copyright © 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

from __future__ import annotations

import importlib.util
import shutil
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts/render-arc.py"
ROOT = MODULE_PATH.parents[1]
SPEC = importlib.util.spec_from_file_location("render_arc", MODULE_PATH)
assert SPEC and SPEC.loader
render_arc = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(render_arc)


class RenderArcTest(unittest.TestCase):
    def test_rendered_yaml_normalization_is_platform_independent(self) -> None:
        expected = b"apiVersion: v1\n---\nkind: Service\n"
        self.assertEqual(render_arc.normalize_rendered_yaml(expected), expected)
        self.assertEqual(
            render_arc.normalize_rendered_yaml(
                b"apiVersion: v1  \n\n\n---\nkind: Service\t\n\n"
            ),
            expected,
        )

    @unittest.skipUnless(shutil.which("helm"), "pinned Helm is required")
    def test_presubmit_render_is_deterministic(self) -> None:
        first = render_arc.render("presubmit")
        second = render_arc.render("presubmit")
        self.assertEqual(first, second)
        self.assertEqual(first, (ROOT / "arc/rendered/presubmit.yaml").read_bytes())


if __name__ == "__main__":
    unittest.main()
