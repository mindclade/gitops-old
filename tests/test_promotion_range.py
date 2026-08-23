#!/usr/bin/env python3
# Copyright © 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

"""Behavior tests for exact-ref promotion integrity validation."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "scripts/validate-promotion-range.py"
WORKFLOW = ROOT / ".github/workflows/validate.yml"
HEADER = """# Copyright © 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

---
"""


def selection(environment: str, release: str | None) -> str:
    applications = " []"
    if release is not None:
        applications = (
            f"\n    - name: serving-api\n      releaseMetadata: releases/{release}.json"
        )
    return (
        HEADER
        + "apiVersion: mindclade.dev/v2\n"
        + "kind: ArtifactDeploymentSet\n"
        + "metadata:\n"
        + f"  name: {environment}\n"
        + "spec:\n"
        + f"  environment: {environment}\n"
        + f"  applications:{applications}\n"
    )


def run_git(repository: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


class PromotionRangeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.repository = Path(self.temporary_directory.name)
        run_git(self.repository, "init", "--initial-branch=main")
        run_git(self.repository, "config", "user.name", "Test")
        run_git(self.repository, "config", "user.email", "test@example.com")
        (self.repository / "deployments").mkdir()
        self.write_selections(None, None, None)
        self.base_sha = self.commit("base")

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def write_selections(
        self,
        development: str | None,
        staging: str | None,
        production: str | None,
    ) -> None:
        for environment, release in (
            ("development", development),
            ("staging", staging),
            ("production", production),
        ):
            (self.repository / "deployments" / f"{environment}.yaml").write_text(
                selection(environment, release), encoding="utf-8"
            )

    def commit(self, message: str) -> str:
        run_git(self.repository, "add", "deployments")
        run_git(self.repository, "commit", "-m", message)
        return run_git(self.repository, "rev-parse", "HEAD")

    def validate(
        self, base_sha: str, head_sha: str
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(VALIDATOR),
                "--repository",
                str(self.repository),
                "--base-sha",
                base_sha,
                "--head-sha",
                head_sha,
            ],
            check=False,
            capture_output=True,
            text=True,
        )

    def test_targets_may_copy_only_the_base_adjacent_environment(self) -> None:
        self.write_selections("release-b", "release-a", None)
        base_sha = self.commit("qualified adjacent environments")
        self.write_selections("release-c", "release-b", "release-a")
        head_sha = self.commit("advance each qualified selection")

        result = self.validate(base_sha, head_sha)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Checked 2 changed promotion target(s)", result.stdout)

    def test_one_range_cannot_leapfrog_all_environments(self) -> None:
        self.write_selections("candidate", "candidate", "candidate")
        head_sha = self.commit("unqualified combined promotion")

        result = self.validate(self.base_sha, head_sha)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("does not exactly match", result.stderr)

    def test_target_that_skips_adjacent_environment_fails(self) -> None:
        self.write_selections("candidate", "candidate", "unreviewed")
        head_sha = self.commit("invalid production promotion")

        result = self.validate(self.base_sha, head_sha)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("does not exactly match", result.stderr)

    def test_validation_uses_supplied_head_not_working_tree_head(self) -> None:
        self.write_selections("release-b", "release-a", None)
        base_sha = self.commit("qualified adjacent environments")
        self.write_selections("release-c", "release-b", "release-a")
        valid_head_sha = self.commit("valid queue head")
        self.write_selections("release-c", "release-b", "later-unreviewed")
        self.commit("unrelated checked-out head")

        result = self.validate(base_sha, valid_head_sha)

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_missing_or_invalid_commit_fails_closed(self) -> None:
        result = self.validate(self.base_sha, "not-a-sha")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("invalid head SHA", result.stderr)

    def test_workflow_wires_pull_request_and_merge_group_event_ranges(self) -> None:
        workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
        steps = workflow["jobs"]["promotion-integrity"]["steps"]
        proof = next(
            step
            for step in steps
            if step.get("name")
            == "Prove changed selections came from the adjacent environment"
        )

        self.assertEqual(
            proof["if"],
            "github.event_name == 'pull_request' || github.event_name == 'merge_group'",
        )
        self.assertEqual(
            proof["env"]["BASE_SHA"],
            "${{ github.event_name == 'pull_request' && "
            "github.event.pull_request.base.sha || "
            "github.event.merge_group.base_sha }}",
        )
        self.assertEqual(
            proof["env"]["HEAD_SHA"],
            "${{ github.event_name == 'pull_request' && "
            "github.sha || "
            "github.event.merge_group.head_sha }}",
        )
        self.assertIn("scripts/validate-promotion-range.py", proof["run"])


if __name__ == "__main__":
    unittest.main()
