#!/usr/bin/env python3
# Copyright © 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

"""Safety tests for mutating GitOps entrypoints."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import yaml


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

    def test_bootstrap_applies_the_digest_render_not_the_raw_upstream_file(self) -> None:
        source = (ROOT / "bootstrap/bootstrap.sh").read_text(encoding="utf-8")
        self.assertIn(
            'kustomize build --load-restrictor LoadRestrictionsNone "$INSTALL_PROFILE"',
            source,
        )
        self.assertIn(
            'kubectl apply -n argocd --server-side --force-conflicts -f "$install_manifest"',
            source,
        )
        self.assertNotIn(
            'kubectl apply -n argocd --server-side --force-conflicts -f "$INSTALL"',
            source,
        )

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

    def test_kustomize_is_the_default_renderer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            with mock.patch.object(
                RENDER.subprocess,
                "run",
                return_value=SimpleNamespace(stdout="apiVersion: v1\nkind: ConfigMap\n"),
            ) as run:
                body, provenance = RENDER.render_source(
                    {"source": "source"}, root, "development", "platform-core"
                )
            self.assertIn("kind: ConfigMap", body)
            self.assertEqual(provenance, ["# source: source", "# render: kustomize"])
            self.assertEqual(
                run.call_args.args[0], ["kustomize", "build", str(source.resolve())]
            )

    def test_helm_renderer_is_local_explicit_and_namespaced(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            chart = root / "chart"
            chart.mkdir()
            (chart / "Chart.yaml").write_text("apiVersion: v2\nname: test\nversion: 1.0.0\n")
            values = root / "values-development.yaml"
            values.write_text("activation:\n  enabled: true\n")
            target = {
                "source": "chart",
                "renderer": "helm",
                "release": "mindclade",
                "namespace": "research-mlflow",
                "values": "values-{env}.yaml",
            }
            with mock.patch.object(
                RENDER.subprocess,
                "run",
                return_value=SimpleNamespace(stdout="apiVersion: apps/v1\nkind: Deployment\n"),
            ) as run:
                _, provenance = RENDER.render_source(
                    target, root, "development", "research-mlflow"
                )
            self.assertEqual(
                run.call_args.args[0],
                [
                    "helm",
                    "template",
                    "mindclade",
                    str(chart.resolve()),
                    "--namespace",
                    "research-mlflow",
                    "--values",
                    str(values.resolve()),
                    "--skip-tests",
                ],
            )
            self.assertIn("# render: helm", provenance)
            self.assertIn("# values: values-development.yaml", provenance)

    def test_helm_renderer_rejects_namespace_drift_and_incidental_crds(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            chart = root / "chart"
            (chart / "crds").mkdir(parents=True)
            (chart / "Chart.yaml").write_text("apiVersion: v2\nname: test\nversion: 1.0.0\n")
            (chart / "crds" / "unsafe.yaml").write_text("kind: CustomResourceDefinition\n")
            (root / "values.yaml").write_text("{}\n")
            target = {
                "source": "chart",
                "renderer": "helm",
                "release": "mindclade",
                "namespace": "research-other",
                "values": "values.yaml",
            }
            with self.assertRaisesRegex(ValueError, "may not install CRDs"):
                RENDER.render_source(target, root, "development", "research-mlflow")

            (chart / "crds" / "unsafe.yaml").unlink()
            with self.assertRaisesRegex(ValueError, "must equal GitOps application"):
                RENDER.render_source(target, root, "development", "research-mlflow")

    def test_release_evidence_tool_has_no_docker_credential_mutation(self) -> None:
        source = (ROOT / "scripts/verify-release-evidence.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("configure-docker", source)

    def test_composition_deletion_preserves_managed_resources(self) -> None:
        root_application = yaml.safe_load(
            (ROOT / "bootstrap/root-app.yaml").read_text(encoding="utf-8")
        )
        self.assertNotIn(
            "resources-finalizer.argocd.argoproj.io",
            (root_application.get("metadata") or {}).get("finalizers") or [],
        )
        for path in sorted((ROOT / "applications").rglob("*.yaml")):
            application = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if application.get("kind") != "ApplicationSet":
                continue
            with self.subTest(path=path.relative_to(ROOT)):
                spec = application.get("spec") or {}
                self.assertIs(
                    (spec.get("syncPolicy") or {}).get(
                        "preserveResourcesOnDeletion"
                    ),
                    True,
                )
                self.assertNotIn(
                    "resources-finalizer.argocd.argoproj.io",
                    (((spec.get("template") or {}).get("metadata") or {}).get(
                        "finalizers"
                    ))
                    or [],
                )

    def test_production_deny_windows_have_no_manual_bypass(self) -> None:
        operations = yaml.safe_load(
            (ROOT / "roots/production/sync-windows-patch.yaml").read_text(
                encoding="utf-8"
            )
        )
        windows = next(
            operation["value"]
            for operation in operations
            if operation.get("path") == "/spec/syncWindows"
        )
        self.assertEqual(len(windows), 2)
        for window in windows:
            with self.subTest(schedule=window.get("schedule")):
                self.assertEqual(window.get("kind"), "deny")
                self.assertIs(window.get("manualSync"), False)

    def test_dex_and_rbac_use_the_same_canonical_github_org(self) -> None:
        for environment in ("development", "staging", "production"):
            path = ROOT / f"bootstrap/argocd-config-{environment}.yaml"
            documents = {
                document["metadata"]["name"]: document
                for document in yaml.safe_load_all(path.read_text(encoding="utf-8"))
            }
            dex = yaml.safe_load(documents["argocd-cm"]["data"]["dex.config"])
            self.assertEqual(
                dex["connectors"][0]["config"]["orgs"], [{"name": "mindclade"}]
            )
            group_rules = [
                line.strip()
                for line in documents["argocd-rbac-cm"]["data"][
                    "policy.csv"
                ].splitlines()
                if line.strip().startswith("g,")
            ]
            self.assertTrue(group_rules)
            self.assertTrue(
                all(rule.startswith("g, mindclade:") for rule in group_rules)
            )

    def test_every_argocd_profile_is_namespaced_resourced_and_digest_pinned(self) -> None:
        provenance = json.loads(
            (ROOT / "bootstrap/argocd-install.provenance.json").read_text(
                encoding="utf-8"
            )
        )
        approved_images = {
            f"{record['source'].rsplit(':', 1)[0]}@{record['digest']}"
            for record in provenance["images"]
        }
        for profile_type in ("install-profiles", "profiles"):
            for profile in ("standard", "ha"):
                with self.subTest(profile_type=profile_type, profile=profile):
                    result = subprocess.run(
                        [
                            "kustomize",
                            "build",
                            "--load-restrictor",
                            "LoadRestrictionsNone",
                            str(ROOT / f"bootstrap/{profile_type}/{profile}"),
                        ],
                        text=True,
                        capture_output=True,
                        check=True,
                    )
                    documents = [
                        document
                        for document in yaml.safe_load_all(result.stdout)
                        if isinstance(document, dict)
                    ]
                    workloads = [
                        document
                        for document in documents
                        if document.get("kind") in {"Deployment", "StatefulSet"}
                    ]
                    self.assertTrue(workloads)
                    for workload in workloads:
                        self.assertEqual(
                            workload["metadata"].get("namespace"), "argocd"
                        )
                        pod_spec = workload["spec"]["template"]["spec"]
                        for container in (
                            (pod_spec.get("containers") or [])
                            + (pod_spec.get("initContainers") or [])
                        ):
                            self.assertIn(container["image"], approved_images)
                            resources = container.get("resources") or {}
                            for section in ("requests", "limits"):
                                for resource_name in ("cpu", "memory"):
                                    self.assertTrue(
                                        (resources.get(section) or {}).get(resource_name),
                                        f"{workload['metadata']['name']}/{container['name']} "
                                        f"omits {section}.{resource_name}",
                                    )


if __name__ == "__main__":
    unittest.main()
