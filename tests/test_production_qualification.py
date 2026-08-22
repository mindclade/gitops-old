#!/usr/bin/env python3
# Copyright © 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

"""Mutation and determinism tests for production qualification evidence."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "production_qualification", ROOT / "scripts/production_qualification.py"
)
assert SPEC is not None and SPEC.loader is not None
QUALIFICATION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(QUALIFICATION)


def request_payload() -> dict:
    commits = {repository: "a" * 40 for repository in QUALIFICATION.REPOSITORIES}
    controls = QUALIFICATION.production_eligibility.load_policy(
        ROOT / "contracts/evidence/production-controls.json"
    )["controls"]
    return {
        "schema_version": 1,
        "qualification_id": "prod-qualification-20260821",
        "change_reference": "CHG-2026-0821",
        "qualification_level": "production",
        "scope": ["enterprise-platform"],
        "repositories": commits,
        "checks": [
            {
                "name": f"connected-{control['id'].replace('_', '-')}",
                "control_id": control["id"],
                "status": "pass",
                "command": "make qualify-connected",
                "detail": "Protected staging and production checks passed.",
                "evidence_key": (
                    "infrastructure-control-plane-handoff"
                    if control["id"] == "github_protections"
                    else "connected-control-plane"
                ),
            }
            for control in controls
        ],
        "module_references": [
            {
                "unit": "production qualification archive",
                "source": "mindclade/mindclade-internal-monorepo//infra/terraform/modules/storage",
                "version": "v0.4.0",
                "qualified": True,
            }
        ],
        "drill_evidence": [
            {
                "drill_id": "DR-2026-08",
                "report_uri": "gs://evidence/dr/report.json",
                "sha256": "b" * 64,
                "result": "pass",
            }
        ],
        "connected_boundary": {
            "performed": True,
            "environments": ["staging", "production"],
            "mutations": ["staging rebootstrap", "production controller recreation"],
            "detail": "Protected connected qualification completed.",
        },
        "evidence_artifacts": [
            {
                "key": "connected-control-plane",
                "repository": "gitops",
                "run_id": 12345,
                "artifact_name": "connected-control-plane-12345",
                "sha256": "c" * 64,
            },
            {
                "key": "infrastructure-control-plane-handoff",
                "repository": "infrastructure-live",
                "run_id": 23456,
                "artifact_name": "infrastructure-control-plane-handoff-23456",
                "sha256": "d" * 64,
            },
        ],
    }


def write_zip(path: Path, name: str = "evidence.json", content: bytes = b"{}\n") -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(name, content)


class RequestContractTest(unittest.TestCase):
    def write_request(self, directory: str, payload: dict) -> Path:
        path = Path(directory) / "request.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_valid_exact_request_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            payload = request_payload()
            self.assertEqual(
                QUALIFICATION.load_request(self.write_request(directory, payload)),
                payload,
            )

    def test_request_mutations_fail_closed(self) -> None:
        mutations = (
            ("failed check", lambda value: value["checks"][0].update(status="fail")),
            ("missing control", lambda value: value["checks"].pop()),
            ("missing repository", lambda value: value["repositories"].pop("bootstrap")),
            (
                "unsafe artifact name",
                lambda value: value["evidence_artifacts"][0].update(
                    artifact_name='bad\" or true or \"'
                ),
            ),
            (
                "unknown environment",
                lambda value: value["connected_boundary"]["environments"].append("other"),
            ),
        )
        for label, mutate in mutations:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                payload = request_payload()
                mutate(payload)
                with self.assertRaises(ValueError):
                    QUALIFICATION.load_request(self.write_request(directory, payload))


class ArchiveContractTest(unittest.TestCase):
    def test_forbidden_zip_members_and_credentials_are_rejected(self) -> None:
        fixtures = (
            ("traversal.zip", "../escape", b"safe"),
            ("state.zip", "terraform.tfstate", b"safe"),
            (
                "credential.zip",
                "output.txt",
                b"-----BEGIN " + b"PRIVATE KEY-----\nnot-a-real-key",
            ),
        )
        with tempfile.TemporaryDirectory() as directory:
            for filename, member, content in fixtures:
                with self.subTest(filename=filename):
                    path = Path(directory) / filename
                    write_zip(path, member, content)
                    with self.assertRaises(ValueError):
                        QUALIFICATION.verify_zip(path)


class DeterministicAssemblyTest(unittest.TestCase):
    @staticmethod
    def git(repository: Path, *args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(repository), *args],
            check=True,
            text=True,
            capture_output=True,
        ).stdout.strip()

    def test_same_inputs_produce_the_same_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            estate = root / "estate"
            sources = root / "source-archives"
            evidence = root / "evidence"
            estate.mkdir()
            sources.mkdir()
            evidence.mkdir()
            payload = request_payload()

            for repository in QUALIFICATION.REPOSITORIES:
                checkout = estate / repository
                checkout.mkdir()
                self.git(checkout, "init", "-q")
                self.git(checkout, "config", "user.name", "Qualification Test")
                self.git(checkout, "config", "user.email", "test@mindclade.invalid")
                (checkout / "README.md").write_text(repository + "\n", encoding="utf-8")
                if repository == ".github":
                    policy = checkout / "contracts/evidence/production-controls.json"
                    policy.parent.mkdir(parents=True)
                    policy.write_bytes(
                        (ROOT / "contracts/evidence/production-controls.json").read_bytes()
                    )
                    manifest = checkout / "contracts/policy-bundle/manifest.json"
                    manifest.parent.mkdir(parents=True)
                    manifest.write_text('{"version":"fixture"}\n', encoding="utf-8")
                if repository == "gitops":
                    rendered = checkout / "rendered/production"
                    rendered.mkdir(parents=True)
                    (rendered / "manifests.yaml").write_text(
                        "apiVersion: v1\nkind: ConfigMap\nmetadata: {name: fixture}\n",
                        encoding="utf-8",
                    )
                    releases = checkout / "releases/platform-fixture"
                    releases.mkdir(parents=True)
                    (releases / "v1.json").write_text(
                        json.dumps({"subject": {"digest": "sha256:" + "e" * 64}}),
                        encoding="utf-8",
                    )
                    deployments = checkout / "deployments"
                    deployments.mkdir()
                    (deployments / "production.yaml").write_text(
                        "apiVersion: mindclade.dev/v2\n"
                        "kind: ArtifactDeploymentSet\n"
                        "spec:\n"
                        "  environment: production\n"
                        "  applications:\n"
                        "    - name: platform-fixture\n"
                        "      releaseMetadata: releases/platform-fixture/v1.json\n",
                        encoding="utf-8",
                    )
                self.git(checkout, "add", ".")
                subprocess.run(
                    ["git", "-C", str(checkout), "commit", "-q", "-m", "fixture"],
                    check=True,
                    env={
                        **__import__("os").environ,
                        "GIT_AUTHOR_DATE": "2026-08-21T12:00:00Z",
                        "GIT_COMMITTER_DATE": "2026-08-21T12:00:00Z",
                    },
                )
                commit = self.git(checkout, "rev-parse", "HEAD")
                self.git(checkout, "update-ref", "refs/remotes/origin/main", commit)
                payload["repositories"][repository] = commit
                write_zip(sources / QUALIFICATION.archive_name(repository))

            evidence_zip = evidence / "connected-control-plane.zip"
            write_zip(evidence_zip)
            payload["evidence_artifacts"][0]["sha256"] = QUALIFICATION.sha256(
                evidence_zip
            )
            handoff_zip = evidence / "infrastructure-control-plane-handoff.zip"
            write_zip(handoff_zip, "handoff.json")
            payload["evidence_artifacts"][1]["sha256"] = QUALIFICATION.sha256(
                handoff_zip
            )
            request = root / "request.json"
            request.write_text(json.dumps(payload), encoding="utf-8")
            audit = root / "audit.json"
            audit.write_text(
                json.dumps(
                    {
                        "status": "PASS",
                        "repositories": list(QUALIFICATION.REPOSITORIES),
                    }
                ),
                encoding="utf-8",
            )

            digests = []
            with mock.patch.object(
                QUALIFICATION.production_eligibility,
                "build_bundle",
                wraps=QUALIFICATION.production_eligibility.build_bundle,
            ) as build_bundle:
                for name in ("first", "second"):
                    output = root / name
                    digests.append(
                        QUALIFICATION.assemble(
                            request, estate, sources, evidence, audit, output
                        )
                    )
                    self.assertEqual(QUALIFICATION.verify(output), digests[-1])
            expected_policy = ROOT / "contracts/evidence/production-controls.json"
            self.assertEqual(
                [call.args[3] for call in build_bundle.call_args_list],
                [expected_policy, expected_policy],
            )
            self.assertEqual(digests[0], digests[1])


if __name__ == "__main__":
    unittest.main()
