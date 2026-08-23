#!/usr/bin/env python3
# Copyright © 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

"""Validate a signed, expiring production qualification handoff."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import production_eligibility


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "mindclade.dev/production-handoff/v1"
REPOSITORIES = production_eligibility.REPOSITORIES
SHA40 = re.compile(r"[0-9a-f]{40}")
SHA256 = re.compile(r"sha256:[0-9a-f]{64}")
IDENTIFIER = re.compile(r"[a-z0-9][a-z0-9-]{5,63}")
CHANGE_REFERENCE = re.compile(r"(?:CHG|SEC|DR)-[A-Za-z0-9._-]+")


def digest_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def file_digest(path: Path) -> str:
    return digest_bytes(path.read_bytes())


def selection_subject_digest(path: Path) -> str:
    return production_eligibility.selection_subject_digest(path)


def tree_digest(root: Path) -> str:
    return production_eligibility.tree_digest(root)


def canonical_handoff(value: dict[str, Any]) -> bytes:
    artifact = value["artifact"]
    public_key = value["public_key"]
    rollback = value["rollback"]
    decision = value["signed_decision"]["decision"]
    signature = value["signed_decision"]["signature"]
    encoder = production_eligibility.CanonicalEncoder("production-handoff/v1")
    encoder.text("schema_version", value["schema_version"])
    encoder.text("qualification_id", value["qualification_id"])
    encoder.text("change_reference", value["change_reference"])
    encoder.text("artifact_uri", artifact["uri"])
    encoder.integer("artifact_generation", artifact["generation"])
    encoder.text("artifact_digest", artifact["digest"])
    encoder.text("bundle_digest", value["bundle_digest"])
    encoder.text("selection_digest", value["selection_digest"])
    encoder.text("render_digest", value["render_digest"])
    encoder.strings(
        "repositories",
        [item["repository"] + "\0" + item["commit"] for item in value["repositories"]],
    )
    encoder.text("decision_digest", decision["decision_digest"])
    encoder.text("signature_key_id", signature["key_id"])
    encoder.text("signature_value", signature["value"])
    encoder.text("public_key_path", public_key["path"])
    encoder.text("public_key_digest", public_key["sha256"])
    encoder.text("rollback_strategy", rollback["strategy"])
    encoder.text(
        "previous_bundle_digest", rollback["previous_bundle_digest"] or ""
    )
    encoder.text(
        "target_selection_digest", rollback["target_selection_digest"] or ""
    )
    encoder.timestamp("issued_at", value["issued_at"])
    encoder.timestamp("expires_at", value["expires_at"])
    return encoder.bytes()


def build_handoff(
    *,
    qualification_id: str,
    bundle: dict[str, Any],
    response: dict[str, Any],
    selection_path: Path,
    artifact_uri: str,
    artifact_generation: int,
    artifact_digest: str,
    public_key: Path,
    public_key_path: str,
) -> dict[str, Any]:
    """Build the sanitized review artifact emitted by protected qualification."""

    production_eligibility.validate_bundle(bundle)
    if IDENTIFIER.fullmatch(qualification_id) is None:
        raise ValueError("production handoff qualification_id is invalid")
    if bundle.get("environment") != "production":
        raise ValueError("production handoff bundle environment is not production")
    selection_digest = selection_subject_digest(selection_path)
    if bundle.get("deployment_selection_digest") != selection_digest:
        raise ValueError("production bundle does not bind the staged selection")
    if (
        not isinstance(response, dict)
        or set(response) != {"signed_decision", "revoked"}
        or response.get("revoked") is not False
    ):
        raise ValueError("production eligibility response is invalid or revoked")
    signed = response.get("signed_decision")
    decision = signed.get("decision") if isinstance(signed, dict) else None
    if (
        not isinstance(decision, dict)
        or decision.get("bundle_digest") != bundle.get("bundle_digest")
    ):
        raise ValueError("production eligibility response does not bind the bundle")
    if (
        not artifact_uri.startswith("gs://")
        or not isinstance(artifact_generation, int)
        or artifact_generation < 1
        or SHA256.fullmatch(artifact_digest) is None
    ):
        raise ValueError("production eligibility artifact identity is invalid")
    relative_key = Path(public_key_path)
    if (
        not public_key_path.startswith("qualification/keys/")
        or relative_key.is_absolute()
        or relative_key.suffix != ".pem"
        or ".." in relative_key.parts
        or "\\" in public_key_path
    ):
        raise ValueError("production handoff public-key path is unsafe")
    repositories = bundle.get("repositories")
    if (
        not isinstance(repositories, list)
        or [item.get("repository") for item in repositories if isinstance(item, dict)]
        != list(REPOSITORIES)
    ):
        raise ValueError("production bundle repository inventory is not exact")
    rollback = bundle.get("rollback")
    if not isinstance(rollback, dict):
        raise ValueError("production bundle rollback is absent")
    value = {
        "schema_version": SCHEMA,
        "handoff_digest": "",
        "qualification_id": qualification_id,
        "change_reference": bundle["change_reference"],
        "artifact": {
            "uri": artifact_uri,
            "generation": artifact_generation,
            "digest": artifact_digest,
        },
        "bundle_digest": bundle["bundle_digest"],
        "selection_digest": selection_digest,
        "render_digest": bundle["gitops_render_digest"],
        "repositories": repositories,
        "signed_decision": signed,
        "revoked": False,
        "public_key": {
            "key_id": signed["signature"]["key_id"],
            "path": public_key_path,
            "sha256": file_digest(public_key),
        },
        "rollback": rollback,
        "issued_at": decision["evaluated_at"],
        "expires_at": decision["expires_at"],
    }
    value["handoff_digest"] = digest_bytes(canonical_handoff(value))
    return value


def _safe_repository_path(root: Path, raw: object, prefix: str) -> Path:
    value = str(raw or "")
    relative = Path(value)
    if (
        not value.startswith(prefix)
        or relative.is_absolute()
        or ".." in relative.parts
        or "\\" in value
    ):
        raise ValueError(f"handoff path must remain under {prefix}")
    resolved = (root / relative).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as error:
        raise ValueError("handoff path escapes the GitOps checkout") from error
    return resolved


def validate_handoff(
    value: dict[str, Any],
    *,
    root: Path,
    selection_path: Path,
    render_root: Path,
    now: datetime | None = None,
    verify_signature: bool = True,
) -> None:
    expected = {
        "schema_version",
        "handoff_digest",
        "qualification_id",
        "change_reference",
        "artifact",
        "bundle_digest",
        "selection_digest",
        "render_digest",
        "repositories",
        "signed_decision",
        "revoked",
        "public_key",
        "rollback",
        "issued_at",
        "expires_at",
    }
    if set(value) != expected or value.get("schema_version") != SCHEMA:
        raise ValueError("production handoff fields or schema are not exact")
    if value.get("revoked") is not False:
        raise ValueError("production handoff is revoked")
    if IDENTIFIER.fullmatch(str(value.get("qualification_id", ""))) is None:
        raise ValueError("production handoff qualification_id is invalid")
    if CHANGE_REFERENCE.fullmatch(str(value.get("change_reference", ""))) is None:
        raise ValueError("production handoff change_reference is invalid")
    for field in ("handoff_digest", "bundle_digest", "selection_digest", "render_digest"):
        if SHA256.fullmatch(str(value.get(field, ""))) is None:
            raise ValueError(f"production handoff {field} is invalid")

    artifact = value.get("artifact")
    if (
        not isinstance(artifact, dict)
        or set(artifact) != {"uri", "generation", "digest"}
        or not str(artifact.get("uri", "")).startswith("gs://")
        or any(character in str(artifact.get("uri", "")) for character in ("\n", "\r", "\0"))
        or not isinstance(artifact.get("generation"), int)
        or artifact["generation"] < 1
        or SHA256.fullmatch(str(artifact.get("digest", ""))) is None
    ):
        raise ValueError("production handoff artifact is invalid or mutable")

    repositories = value.get("repositories")
    if not isinstance(repositories, list) or len(repositories) != len(REPOSITORIES):
        raise ValueError("production handoff repository inventory is incomplete")
    for index, item in enumerate(repositories):
        if (
            not isinstance(item, dict)
            or set(item) != {"repository", "commit"}
            or item.get("repository") != REPOSITORIES[index]
            or SHA40.fullmatch(str(item.get("commit", ""))) is None
        ):
            raise ValueError("production handoff repository inventory is not exact")

    if value["selection_digest"] != selection_subject_digest(selection_path):
        raise ValueError("production handoff does not bind the deployment selection")
    if value["render_digest"] != tree_digest(render_root):
        raise ValueError("production handoff does not bind the production render")
    if value["handoff_digest"] != digest_bytes(canonical_handoff(value)):
        raise ValueError("production handoff digest differs from canonical content")

    signed = value.get("signed_decision")
    if not isinstance(signed, dict) or set(signed) != {"decision", "signature"}:
        raise ValueError("production handoff signed decision is invalid")
    decision = signed.get("decision")
    signature = signed.get("signature")
    decision_fields = {
        "schema_version",
        "decision_digest",
        "bundle_digest",
        "policy_digest",
        "policy_epoch",
        "result",
        "reasons",
        "selections",
        "exceptions",
        "evaluated_at",
        "expires_at",
    }
    if (
        not isinstance(decision, dict)
        or set(decision) != decision_fields
        or decision.get("schema_version") != production_eligibility.SCHEMA_DECISION
        or decision.get("bundle_digest") != value["bundle_digest"]
        or decision.get("result") != "eligible"
        or decision.get("reasons") != []
        or decision.get("exceptions") != []
    ):
        raise ValueError("production handoff decision is not an exact eligible result")
    payload = production_eligibility.canonical_decision(decision)
    if decision.get("decision_digest") != digest_bytes(payload):
        raise ValueError("production handoff decision digest differs")
    policy = production_eligibility.load_policy(
        root / "contracts/evidence/production-controls.json"
    )
    controls = [item["id"] for item in policy["controls"]]
    selections = decision.get("selections")
    if (
        decision.get("policy_digest") != policy["digest"]
        or decision.get("policy_epoch") != policy["epoch"]
        or not isinstance(selections, list)
        or [item.get("control_id") for item in selections if isinstance(item, dict)]
        != controls
        or any(
            not isinstance(item, dict)
            or set(item) != {"control_id", "claim_digest", "verification_digest"}
            or SHA256.fullmatch(str(item.get("claim_digest", ""))) is None
            or SHA256.fullmatch(str(item.get("verification_digest", ""))) is None
            for item in selections
        )
    ):
        raise ValueError("production handoff decision does not cover the governed controls")

    issued = production_eligibility.parse_timestamp(value["issued_at"])
    expires = production_eligibility.parse_timestamp(value["expires_at"])
    evaluated = production_eligibility.parse_timestamp(decision["evaluated_at"])
    decision_expires = production_eligibility.parse_timestamp(decision["expires_at"])
    verification_time = now or datetime.now(timezone.utc)
    if verification_time.utcoffset() is None:
        raise ValueError("production handoff verification time must be timezone-aware")
    if (
        issued != evaluated
        or expires != decision_expires
        or not issued < expires
        or expires - issued > timedelta(hours=6)
        or expires > production_eligibility.parse_timestamp(policy["valid_until"])
    ):
        raise ValueError("production handoff validity does not match its decision")
    if verification_time >= expires:
        raise ValueError("production handoff has expired")

    public_key = value.get("public_key")
    if (
        not isinstance(public_key, dict)
        or set(public_key) != {"key_id", "path", "sha256"}
        or SHA256.fullmatch(str(public_key.get("sha256", ""))) is None
    ):
        raise ValueError("production handoff public key identity is invalid")
    if (
        not isinstance(signature, dict)
        or set(signature) != {"algorithm", "key_id", "value"}
        or signature.get("algorithm") != "ed25519"
        or signature.get("key_id") != public_key.get("key_id")
    ):
        raise ValueError("production handoff signature identity is invalid")
    try:
        signature_bytes = base64.b64decode(signature.get("value", ""), validate=True)
    except (TypeError, ValueError) as error:
        raise ValueError("production handoff signature encoding is invalid") from error
    if len(signature_bytes) != 64:
        raise ValueError("production handoff signature length is invalid")
    key_path = _safe_repository_path(root, public_key.get("path"), "qualification/keys/")
    if file_digest(key_path) != public_key["sha256"]:
        raise ValueError("production handoff public key fingerprint differs")

    rollback = value.get("rollback")
    if not isinstance(rollback, dict) or set(rollback) != {
        "strategy",
        "previous_bundle_digest",
        "target_selection_digest",
    }:
        raise ValueError("production handoff rollback inventory is invalid")
    if rollback.get("strategy") == "bootstrap":
        if rollback.get("previous_bundle_digest") is not None or rollback.get("target_selection_digest") is not None:
            raise ValueError("bootstrap handoff cannot name a previous rollback target")
    elif rollback.get("strategy") == "previous-bundle":
        if SHA256.fullmatch(str(rollback.get("previous_bundle_digest", ""))) is None or SHA256.fullmatch(str(rollback.get("target_selection_digest", ""))) is None:
            raise ValueError("previous-bundle rollback must bind both immutable digests")
    else:
        raise ValueError("production handoff rollback strategy is unsupported")

    if verify_signature:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            payload_path = temporary / "decision.bin"
            signature_path = temporary / "signature.bin"
            payload_path.write_bytes(payload)
            signature_path.write_bytes(signature_bytes)
            result = subprocess.run(
                [
                    "openssl",
                    "pkeyutl",
                    "-verify",
                    "-pubin",
                    "-inkey",
                    str(key_path),
                    "-rawin",
                    "-in",
                    str(payload_path),
                    "-sigfile",
                    str(signature_path),
                ],
                capture_output=True,
                check=False,
                text=True,
            )
            if result.returncode != 0:
                raise ValueError("production handoff Ed25519 signature is invalid")


def main() -> int:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate")
    validate.add_argument("--handoff", required=True, type=Path)
    validate.add_argument("--selection", required=True, type=Path)
    validate.add_argument("--render-root", required=True, type=Path)
    validate.add_argument("--root", type=Path, default=ROOT)
    validate.add_argument("--as-of")
    create = commands.add_parser("create")
    create.add_argument("--qualification-id", required=True)
    create.add_argument("--bundle", required=True, type=Path)
    create.add_argument("--response", required=True, type=Path)
    create.add_argument("--selection", required=True, type=Path)
    create.add_argument("--artifact-uri", required=True)
    create.add_argument("--artifact-generation", required=True, type=int)
    create.add_argument("--artifact-digest", required=True)
    create.add_argument("--public-key", required=True, type=Path)
    create.add_argument(
        "--public-key-path",
        default="qualification/keys/production-eligibility.pem",
    )
    create.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        if args.command == "create":
            value = build_handoff(
                qualification_id=args.qualification_id,
                bundle=json.loads(args.bundle.read_text(encoding="utf-8")),
                response=json.loads(args.response.read_text(encoding="utf-8")),
                selection_path=args.selection,
                artifact_uri=args.artifact_uri,
                artifact_generation=args.artifact_generation,
                artifact_digest=args.artifact_digest,
                public_key=args.public_key,
                public_key_path=args.public_key_path,
            )
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            print(value["handoff_digest"])
            return 0
        now = (
            production_eligibility.parse_timestamp(args.as_of)
            if args.as_of
            else datetime.now(timezone.utc)
        )
        value = json.loads(args.handoff.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("production handoff must contain one JSON object")
        validate_handoff(
            value,
            root=args.root.resolve(),
            selection_path=args.selection.resolve(),
            render_root=args.render_root.resolve(),
            now=now,
        )
        print(f"production handoff passed: {value['qualification_id']}")
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"ERROR: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
