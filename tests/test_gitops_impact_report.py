# Copyright © 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

from __future__ import annotations

import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

import jsonschema


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "gitops_impact_report", ROOT / "scripts/gitops-impact-report.py"
)
assert SPEC and SPEC.loader
IMPACT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(IMPACT)


class GitOpsImpactReportTest(unittest.TestCase):
    def repository(self) -> tuple[tempfile.TemporaryDirectory[str], Path, str]:
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        subprocess.run(["git", "init", "-q", root], check=True)
        subprocess.run(["git", "-C", root, "config", "user.email", "test@example.com"], check=True)
        subprocess.run(["git", "-C", root, "config", "user.name", "Test"], check=True)
        (root / "README.md").write_text("base\n", encoding="utf-8")
        subprocess.run(["git", "-C", root, "add", "."], check=True)
        subprocess.run(["git", "-C", root, "commit", "-qm", "base"], check=True)
        base = subprocess.run(
            ["git", "-C", root, "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        return temporary, root, base

    def commit(self, root: Path) -> str:
        subprocess.run(["git", "-C", root, "add", "."], check=True)
        subprocess.run(["git", "-C", root, "commit", "-qm", "head"], check=True)
        return subprocess.run(
            ["git", "-C", root, "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    def test_documentation_only_change_is_low_risk(self) -> None:
        temporary, root, base = self.repository()
        self.addCleanup(temporary.cleanup)
        (root / "README.md").write_text("head\n", encoding="utf-8")
        report = IMPACT.analyze(root, base, self.commit(root))
        self.assertEqual(report["risk"]["rating"], "low")
        self.assertFalse(report["rollbackRequired"])

    def test_production_prune_and_image_change_is_critical(self) -> None:
        temporary, root, base = self.repository()
        self.addCleanup(temporary.cleanup)
        path = root / "roots/production/application.yaml"
        path.parent.mkdir(parents=True)
        path.write_text(
            """apiVersion: argoproj.io/v1alpha1
kind: Application
metadata: {name: api, namespace: argocd}
spec:
  destination: {namespace: api}
  syncPolicy: {automated: {prune: true}}
  template: {spec: {containers: [{name: api, image: example/api@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa}]}}
""",
            encoding="utf-8",
        )
        report = IMPACT.analyze(root, base, self.commit(root))
        self.assertEqual(report["risk"]["rating"], "critical")
        self.assertEqual(report["affectedEnvironments"], ["production"])
        self.assertIn("api", report["affectedApplications"])
        self.assertTrue(report["imageChanges"])
        self.assertTrue(report["pruneChanges"])

    def test_all_production_delivery_paths_are_critical(self) -> None:
        for relative in (
            "applications/production/api.yaml",
            "rendered/production/api/configmap.yaml",
        ):
            with self.subTest(relative=relative):
                temporary, root, base = self.repository()
                self.addCleanup(temporary.cleanup)
                path = root / relative
                path.parent.mkdir(parents=True)
                path.write_text(
                    "apiVersion: v1\n"
                    "kind: ConfigMap\n"
                    "metadata: {name: api, namespace: api}\n",
                    encoding="utf-8",
                )
                report = IMPACT.analyze(root, base, self.commit(root))
                self.assertEqual(report["risk"]["rating"], "critical")
                self.assertIn("production", report["affectedEnvironments"])

    def test_application_set_template_destination_is_reported(self) -> None:
        documents = [
            {
                "kind": "ApplicationSet",
                "metadata": {"name": "platform", "namespace": "argocd"},
                "spec": {
                    "template": {
                        "spec": {"destination": {"namespace": "{{.path.basename}}"}}
                    }
                },
            }
        ]
        applications, namespaces = IMPACT.object_names(documents)
        self.assertEqual(applications, {"platform"})
        self.assertEqual(namespaces, {"argocd", "{{.path.basename}}"})

    def test_app_project_authority_expansion_is_critical(self) -> None:
        temporary, root, base = self.repository()
        self.addCleanup(temporary.cleanup)
        path = root / "projects/app.yaml"
        path.parent.mkdir(parents=True)
        path.write_text(
            """apiVersion: argoproj.io/v1alpha1
kind: AppProject
metadata: {name: app}
spec: {sourceRepos: ['https://github.com/mindclade/app']}
""",
            encoding="utf-8",
        )
        report = IMPACT.analyze(root, base, self.commit(root))
        self.assertEqual(report["risk"]["rating"], "critical")
        self.assertEqual(report["rbacExpansions"][0]["field"], "sourceRepos")
        self.assertEqual(report["rbacExpansions"][0]["direction"], "added")

    def test_removing_secret_blacklist_expands_authority(self) -> None:
        before = [
            {
                "kind": "AppProject",
                "metadata": {"name": "platform"},
                "spec": {"namespaceResourceBlacklist": [{"group": "", "kind": "Secret"}]},
            }
        ]
        after = [
            {
                "kind": "AppProject",
                "metadata": {"name": "platform"},
                "spec": {"namespaceResourceBlacklist": []},
            }
        ]
        expansions = IMPACT.app_project_expansions(before, after)
        self.assertEqual(expansions[0]["field"], "namespaceResourceBlacklist")
        self.assertEqual(expansions[0]["direction"], "removed")

    def test_all_repository_image_shapes_are_detected(self) -> None:
        documents = [
            {"spec": {"containers": [{"image": "registry/api@sha256:" + "a" * 64}]}},
            {
                "kind": "Kustomization",
                "images": [
                    {"name": "registry/base", "digest": "sha256:" + "b" * 64},
                    "registry/old=registry/new@sha256:" + "d" * 64,
                ],
            },
            {"image": {"repository": "registry/controller", "tag": "1.2.3@sha256:" + "c" * 64}},
            {"image": {"registry/arc@sha256:" + "e" * 64: None}},
        ]
        self.assertEqual(
            IMPACT.images(documents),
            {
                "registry/api@sha256:" + "a" * 64,
                "registry/base@sha256:" + "b" * 64,
                "registry/controller:1.2.3@sha256:" + "c" * 64,
                "registry/old=registry/new@sha256:" + "d" * 64,
                "registry/arc@sha256:" + "e" * 64,
            },
        )

    def test_prune_detection_uses_effective_argo_semantics(self) -> None:
        disabled = {
            "kind": "Application",
            "metadata": {"name": "api", "namespace": "argocd"},
            "spec": {"syncPolicy": {"automated": {"enabled": False, "prune": True}}},
        }
        enabled = {
            "kind": "Application",
            "metadata": {"name": "api", "namespace": "argocd"},
            "spec": {"syncPolicy": {"automated": {"enabled": True, "prune": True}}},
        }
        unrelated = {"kind": "Example", "metadata": {"name": "x"}, "spec": {"prune": True}}
        self.assertEqual(IMPACT.enabled_prune_scopes([disabled, unrelated]), {})
        self.assertEqual(
            set(IMPACT.enabled_prune_scopes([unrelated, enabled])),
            {"Application/argocd/api"},
        )

    def test_effective_prune_scope_retarget_is_critical(self) -> None:
        temporary, root, _ = self.repository()
        self.addCleanup(temporary.cleanup)
        path = root / "applications/development/api.yaml"
        path.parent.mkdir(parents=True)
        path.write_text(
            """apiVersion: argoproj.io/v1alpha1
kind: Application
metadata: {name: api, namespace: argocd}
spec:
  source: {repoURL: https://github.com/mindclade/gitops, path: rendered/development/api-v1}
  destination: {server: https://kubernetes.default.svc, namespace: api}
  syncPolicy: {automated: {enabled: true, prune: true}}
""",
            encoding="utf-8",
        )
        base = self.commit(root)
        source = path.read_text(encoding="utf-8")
        path.write_text(source.replace("api-v1", "api-v2"), encoding="utf-8")
        report = IMPACT.analyze(root, base, self.commit(root))
        self.assertEqual(report["risk"]["rating"], "critical")
        self.assertEqual(
            report["pruneChanges"][0]["retargeted"][0]["object"],
            "Application/argocd/api",
        )

    def test_deployment_filename_and_application_are_reported(self) -> None:
        temporary, root, base = self.repository()
        self.addCleanup(temporary.cleanup)
        path = root / "deployments/staging.yaml"
        path.parent.mkdir(parents=True)
        path.write_text(
            """apiVersion: mindclade.dev/v3
kind: ArtifactDeploymentSet
metadata: {name: staging}
spec:
  environment: staging
  applications:
    - {name: serving-api, releaseMetadata: releases/api.json}
""",
            encoding="utf-8",
        )
        report = IMPACT.analyze(root, base, self.commit(root))
        self.assertEqual(report["affectedEnvironments"], ["staging"])
        self.assertEqual(report["affectedApplications"], ["serving-api"])

    def test_rename_reports_both_authority_boundaries(self) -> None:
        temporary, root, _ = self.repository()
        self.addCleanup(temporary.cleanup)
        source = root / "applications/development/api.yaml"
        source.parent.mkdir(parents=True)
        source.write_text(
            "apiVersion: argoproj.io/v1alpha1\nkind: Application\nmetadata: {name: api}\n",
            encoding="utf-8",
        )
        base = self.commit(root)
        destination = root / "applications/production/api.yaml"
        destination.parent.mkdir(parents=True)
        subprocess.run(["git", "-C", root, "mv", source, destination], check=True)
        report = IMPACT.analyze(root, base, self.commit(root))
        self.assertEqual(report["affectedEnvironments"], ["development", "production"])
        self.assertEqual(
            report["changedPaths"],
            [
                {"path": "applications/development/api.yaml", "change": "deleted"},
                {"path": "applications/production/api.yaml", "change": "added"},
            ],
        )
        self.assertEqual(report["risk"]["rating"], "critical")

    def test_top_level_sequence_is_never_silently_discarded(self) -> None:
        temporary, root, base = self.repository()
        self.addCleanup(temporary.cleanup)
        path = root / "roots/development/patch.yaml"
        path.parent.mkdir(parents=True)
        path.write_text(
            "- op: replace\n  path: /spec/syncPolicy/automated/prune\n  value: true\n",
            encoding="utf-8",
        )
        report = IMPACT.analyze(root, base, self.commit(root))
        self.assertEqual(report["risk"]["rating"], "high")
        self.assertEqual(report["opaqueYamlChanges"][0]["path"], "roots/development/patch.yaml")

    def test_divergent_history_is_rejected(self) -> None:
        temporary, root, initial = self.repository()
        self.addCleanup(temporary.cleanup)
        (root / "README.md").write_text("base branch\n", encoding="utf-8")
        base = self.commit(root)
        subprocess.run(["git", "-C", root, "checkout", "-qb", "candidate", initial], check=True)
        (root / "README.md").write_text("candidate branch\n", encoding="utf-8")
        head = self.commit(root)
        with self.assertRaisesRegex(IMPACT.ImpactError, "not an ancestor"):
            IMPACT.analyze(root, base, head)

    def test_report_matches_machine_schema(self) -> None:
        temporary, root, base = self.repository()
        self.addCleanup(temporary.cleanup)
        (root / "README.md").write_text("head\n", encoding="utf-8")
        report = IMPACT.analyze(root, base, self.commit(root))
        schema = json.loads(
            (ROOT / "contracts/gitops-impact-report.schema.json").read_text(encoding="utf-8")
        )
        jsonschema.Draft202012Validator(schema).validate(report)

    def test_workflow_executes_only_base_trusted_analyzer(self) -> None:
        workflow = (ROOT / ".github/workflows/impact-report.yml").read_text(encoding="utf-8")
        self.assertIn("pull_request_target:", workflow)
        self.assertNotIn("\n  pull_request:\n", workflow)
        self.assertIn("ready_for_review, edited", workflow)
        self.assertIn("path: .trusted", workflow)
        self.assertIn("path: .candidate", workflow)
        self.assertIn("nix develop ./.trusted#ci", workflow)
        self.assertIn(".trusted/scripts/gitops-impact-report.py", workflow)
        self.assertNotIn(".candidate/scripts/", workflow)
        self.assertIn("github.event.pull_request.number", workflow)

    def test_report_validator_rejects_unknown_output(self) -> None:
        report = {
            "schemaVersion": 1,
            "baseCommit": "0" * 40,
            "headCommit": "1" * 40,
            "risk": {"rating": "low", "reasons": ["test"]},
            "rollbackRequired": False,
            "changedPaths": [],
            "affectedEnvironments": [],
            "affectedApplications": [],
            "affectedNamespaces": [],
            "imageChanges": [],
            "rbacExpansions": [],
            "policyChanges": [],
            "pruneChanges": [],
            "opaqueYamlChanges": [],
            "unexpected": True,
        }
        with self.assertRaises(IMPACT.ImpactError):
            IMPACT.validate_report(ROOT, report)

    def test_schema_rejects_risk_rollback_contradiction(self) -> None:
        report = {
            "schemaVersion": 1,
            "baseCommit": "0" * 40,
            "headCommit": "1" * 40,
            "risk": {"rating": "critical", "reasons": ["test"]},
            "rollbackRequired": False,
            "changedPaths": [],
            "affectedEnvironments": [],
            "affectedApplications": [],
            "affectedNamespaces": [],
            "imageChanges": [],
            "rbacExpansions": [],
            "policyChanges": [],
            "pruneChanges": [],
            "opaqueYamlChanges": [],
        }
        with self.assertRaises(IMPACT.ImpactError):
            IMPACT.validate_report(ROOT, report)

    def test_schema_rejects_empty_image_delta(self) -> None:
        report = {
            "schemaVersion": 1,
            "baseCommit": "0" * 40,
            "headCommit": "1" * 40,
            "risk": {"rating": "high", "reasons": ["image"]},
            "rollbackRequired": True,
            "changedPaths": [],
            "affectedEnvironments": [],
            "affectedApplications": [],
            "affectedNamespaces": [],
            "imageChanges": [{"path": "x.yaml", "removed": [], "added": []}],
            "rbacExpansions": [],
            "policyChanges": [],
            "pruneChanges": [],
            "opaqueYamlChanges": [],
        }
        with self.assertRaises(IMPACT.ImpactError):
            IMPACT.validate_report(ROOT, report)


if __name__ == "__main__":
    unittest.main()
