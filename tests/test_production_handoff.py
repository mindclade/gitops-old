# Copyright © 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

from __future__ import annotations

import base64
import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from tests.test_production_eligibility import (
    bundle_fixture,
    records_fixture,
    response_fixture,
)


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
SPEC = importlib.util.spec_from_file_location(
    "production_handoff", ROOT / "scripts/production_handoff.py"
)
assert SPEC is not None and SPEC.loader is not None
HANDOFF = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HANDOFF)


class ProductionHandoffTest(unittest.TestCase):
    def fixture(self, root: Path) -> tuple[dict, Path, Path]:
        (root / "contracts/evidence").mkdir(parents=True)
        (root / "contracts/evidence/production-controls.json").write_bytes(
            (ROOT / "contracts/evidence/production-controls.json").read_bytes()
        )
        (root / "qualification/keys").mkdir(parents=True)
        (root / "deployments").mkdir()
        (root / "rendered/production/platform-core").mkdir(parents=True)
        selection = root / "deployments/production.yaml"
        selection.write_text(
            "apiVersion: mindclade.dev/v3\n"
            "kind: ArtifactDeploymentSet\n"
            "metadata: {name: production}\n"
            "spec:\n"
            "  environment: production\n"
            "  qualificationState: qualified-v1\n"
            "  qualificationHandoff: qualification/handoffs/qualification-one.json\n"
            "  applications: []\n",
            encoding="utf-8",
        )
        render_root = root / "rendered/production"
        (render_root / "platform-core/manifests.yaml").write_text(
            "apiVersion: v1\nkind: ConfigMap\n", encoding="utf-8"
        )

        private_key = root / "private.pem"
        public_key = root / "qualification/keys/production-eligibility.pem"
        subprocess.run(
            ["openssl", "genpkey", "-algorithm", "ED25519", "-out", str(private_key)],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            [
                "openssl",
                "pkey",
                "-in",
                str(private_key),
                "-pubout",
                "-out",
                str(public_key),
            ],
            check=True,
            capture_output=True,
        )

        policy = HANDOFF.production_eligibility.load_policy(
            root / "contracts/evidence/production-controls.json"
        )
        decision = {
            "schema_version": HANDOFF.production_eligibility.SCHEMA_DECISION,
            "decision_digest": "",
            "bundle_digest": "sha256:" + "a" * 64,
            "policy_digest": policy["digest"],
            "policy_epoch": policy["epoch"],
            "result": "eligible",
            "reasons": [],
            "selections": [
                {
                    "control_id": control["id"],
                    "claim_digest": "sha256:" + "b" * 64,
                    "verification_digest": "sha256:" + "c" * 64,
                }
                for control in policy["controls"]
            ],
            "exceptions": [],
            "evaluated_at": "2026-08-23T12:00:00Z",
            "expires_at": "2026-08-23T13:00:00Z",
        }
        payload = HANDOFF.production_eligibility.canonical_decision(decision)
        decision["decision_digest"] = HANDOFF.digest_bytes(payload)
        payload = HANDOFF.production_eligibility.canonical_decision(decision)
        payload_path = root / "decision.bin"
        signature_path = root / "decision.sig"
        payload_path.write_bytes(payload)
        subprocess.run(
            [
                "openssl",
                "pkeyutl",
                "-sign",
                "-inkey",
                str(private_key),
                "-rawin",
                "-in",
                str(payload_path),
                "-out",
                str(signature_path),
            ],
            check=True,
            capture_output=True,
        )
        value = {
            "schema_version": HANDOFF.SCHEMA,
            "handoff_digest": "",
            "qualification_id": "qualification-one",
            "change_reference": "CHG-123",
            "artifact": {
                "uri": "gs://evidence/qualification-one.json",
                "generation": 123,
                "digest": "sha256:" + "d" * 64,
            },
            "bundle_digest": decision["bundle_digest"],
            "selection_digest": HANDOFF.selection_subject_digest(selection),
            "render_digest": HANDOFF.tree_digest(render_root),
            "repositories": [
                {"repository": repository, "commit": "1" * 40}
                for repository in HANDOFF.REPOSITORIES
            ],
            "signed_decision": {
                "decision": decision,
                "signature": {
                    "algorithm": "ed25519",
                    "key_id": "production-eligibility-v1",
                    "value": base64.b64encode(signature_path.read_bytes()).decode("ascii"),
                },
            },
            "revoked": False,
            "public_key": {
                "key_id": "production-eligibility-v1",
                "path": "qualification/keys/production-eligibility.pem",
                "sha256": HANDOFF.file_digest(public_key),
            },
            "rollback": {
                "strategy": "bootstrap",
                "previous_bundle_digest": None,
                "target_selection_digest": None,
            },
            "issued_at": decision["evaluated_at"],
            "expires_at": decision["expires_at"],
        }
        value["handoff_digest"] = HANDOFF.digest_bytes(HANDOFF.canonical_handoff(value))
        return value, selection, render_root

    def test_signed_handoff_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value, selection, render_root = self.fixture(root)
            HANDOFF.validate_handoff(
                value,
                root=root,
                selection_path=selection,
                render_root=render_root,
                now=datetime(2026, 8, 23, 12, 30, tzinfo=timezone.utc),
            )

    def test_tamper_expiry_and_revocation_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value, selection, render_root = self.fixture(root)
            cases = (
                ("revoked", lambda candidate: candidate.update(revoked=True)),
                (
                    "selection",
                    lambda candidate: candidate.update(
                        selection_digest="sha256:" + "0" * 64
                    ),
                ),
                (
                    "key",
                    lambda candidate: candidate["public_key"].update(
                        sha256="sha256:" + "0" * 64
                    ),
                ),
            )
            for label, mutate in cases:
                with self.subTest(label=label):
                    candidate = copy.deepcopy(value)
                    mutate(candidate)
                    with self.assertRaises(ValueError):
                        HANDOFF.validate_handoff(
                            candidate,
                            root=root,
                            selection_path=selection,
                            render_root=render_root,
                            now=datetime(2026, 8, 23, 12, 30, tzinfo=timezone.utc),
                        )
            with self.assertRaisesRegex(ValueError, "expired"):
                HANDOFF.validate_handoff(
                    value,
                    root=root,
                    selection_path=selection,
                    render_root=render_root,
                    now=datetime(2026, 8, 23, 13, 0, tzinfo=timezone.utc),
                )

    def test_activation_fields_do_not_create_a_selection_digest_cycle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value, selection, _ = self.fixture(root)
            before = HANDOFF.selection_subject_digest(selection)
            text = selection.read_text(encoding="utf-8")
            selection.write_text(
                text.replace("qualified-v1", "staged-v1").replace(
                    "qualification/handoffs/qualification-one.json", "null"
                ),
                encoding="utf-8",
            )
            self.assertEqual(before, HANDOFF.selection_subject_digest(selection))
            self.assertEqual(value["selection_digest"], before)

    def test_protected_builder_emits_a_sanitized_activation_claim(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, selection, render_root = self.fixture(root)
            bundle = bundle_fixture()
            bundle["deployment_selection_digest"] = HANDOFF.selection_subject_digest(
                selection
            )
            bundle["gitops_render_digest"] = HANDOFF.tree_digest(render_root)
            bundle["bundle_digest"] = HANDOFF.digest_bytes(
                HANDOFF.production_eligibility.canonical_bundle(bundle)
            )
            policy = HANDOFF.production_eligibility.load_policy(
                root / "contracts/evidence/production-controls.json"
            )
            response = response_fixture(bundle, policy, records_fixture(bundle, policy))
            public_key = root / "qualification/keys/production-eligibility.pem"
            value = HANDOFF.build_handoff(
                qualification_id="qualification-one",
                bundle=bundle,
                response=response,
                selection_path=selection,
                artifact_uri="gs://evidence/eligibility-decision.json",
                artifact_generation=123,
                artifact_digest="sha256:" + "d" * 64,
                public_key=public_key,
                public_key_path="qualification/keys/production-eligibility.pem",
            )
            self.assertEqual(value["selection_digest"], bundle["deployment_selection_digest"])
            self.assertEqual(value["render_digest"], bundle["gitops_render_digest"])
            self.assertEqual(
                value["handoff_digest"],
                HANDOFF.digest_bytes(HANDOFF.canonical_handoff(value)),
            )


if __name__ == "__main__":
    unittest.main()
