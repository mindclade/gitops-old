#!/usr/bin/env python3
# Copyright © 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

"""Build canonical deployment evidence and validate signed eligibility decisions."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import struct
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml


REPOSITORIES = (
    ".github",
    ".github-private",
    "bootstrap",
    "github-config",
    "gitops",
    "infrastructure-live",
    "mindclade-internal-monorepo",
)
SCHEMA_BUNDLE = "mindclade.dev/deployment-bundle/v1"
SCHEMA_CLAIM = "mindclade.dev/evidence-claim/v1"
SCHEMA_VERIFICATION = "mindclade.dev/evidence-verification/v1"
SCHEMA_DECISION = "mindclade.dev/production-eligibility/v1"
WORKFLOW_RELEASE = "v1.0.0"
SHA256 = re.compile(r"sha256:[0-9a-f]{64}")
SHA40 = re.compile(r"[0-9a-f]{40}")
CHANGE_REFERENCE = re.compile(r"(?:CHG|SEC|DR)-[A-Za-z0-9._-]+")
CANONICAL_NAME = re.compile(r"[a-z][a-z0-9_.-]{1,127}")
SEMANTIC_VERSION = re.compile(r"v[0-9]+\.[0-9]+\.[0-9]+")
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def fail(message: str) -> None:
    raise ValueError(message)


def digest_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def file_digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return "sha256:" + value.hexdigest()


class CanonicalEncoder:
    def __init__(self, document_type: str):
        self.value = bytearray(b"MCCE1/" + document_type.encode("utf-8") + b"\0")

    def field(self, key: str, value: bytes) -> None:
        encoded = key.encode("utf-8")
        self.value.extend(struct.pack(">H", len(encoded)))
        self.value.extend(encoded)
        self.value.extend(struct.pack(">I", len(value)))
        self.value.extend(value)

    def text(self, key: str, value: str) -> None:
        self.field(key, value.encode("utf-8"))

    def integer(self, key: str, value: int) -> None:
        self.field(key, struct.pack(">Q", value))

    def timestamp(self, key: str, value: str) -> None:
        parsed = parse_timestamp(value)
        delta = parsed - EPOCH
        if delta.days < 0:
            fail("canonical timestamp must not precede the Unix epoch")
        milliseconds = (
            delta.days * 86_400_000
            + delta.seconds * 1_000
            + delta.microseconds // 1_000
        )
        self.integer(key, milliseconds)

    def strings(self, key: str, values: list[str]) -> None:
        if values != sorted(set(values)) or any(not value for value in values):
            fail(f"{key} must be sorted and unique")
        payload = bytearray(struct.pack(">I", len(values)))
        for value in values:
            encoded = value.encode("utf-8")
            payload.extend(struct.pack(">I", len(encoded)))
            payload.extend(encoded)
        self.field(key, bytes(payload))

    def bytes(self) -> bytes:
        return bytes(self.value)


def parse_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as error:
        raise ValueError("timestamp must be RFC3339") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        fail("timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


def format_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def tree_digest(root: Path) -> str:
    if not root.is_dir():
        fail(f"required tree is absent: {root}")
    files = sorted(path for path in root.rglob("*") if path.is_file())
    if not files:
        fail(f"required tree is empty: {root}")
    value = hashlib.sha256(b"MCTREE1\0")
    for path in files:
        relative = path.relative_to(root).as_posix().encode("utf-8")
        content = path.read_bytes()
        value.update(struct.pack(">I", len(relative)))
        value.update(relative)
        value.update(struct.pack(">Q", len(content)))
        value.update(content)
    return "sha256:" + value.hexdigest()


def load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} is unreadable: {error}") from error
    if not isinstance(value, dict):
        fail(f"{label} must be an object")
    return value


def load_policy(path: Path) -> dict[str, Any]:
    policy = load_json(path, "production eligibility policy")
    required = {"id", "version", "digest", "epoch", "valid_until", "controls"}
    if set(policy) != required or policy["id"] != "production-controls":
        fail("production eligibility policy inventory is not exact")
    if (
        not SHA256.fullmatch(str(policy["digest"]))
        or not CANONICAL_NAME.fullmatch(str(policy["version"]))
        or not isinstance(policy["epoch"], int)
        or policy["epoch"] < 1
    ):
        fail("production eligibility policy identity is invalid")
    parse_timestamp(policy["valid_until"])
    controls = policy["controls"]
    if not isinstance(controls, list) or not 1 <= len(controls) <= 128:
        fail("production eligibility policy has no controls")
    control_fields = {"id", "owner", "maximum_age", "exception_allowed"}
    identifiers = []
    for control in controls:
        if (
            not isinstance(control, dict)
            or set(control) != control_fields
            or not CANONICAL_NAME.fullmatch(str(control.get("id", "")))
            or not CANONICAL_NAME.fullmatch(str(control.get("owner", "")))
            or not isinstance(control.get("maximum_age"), int)
            or not 0 < control["maximum_age"] <= 366 * 24 * 60 * 60 * 1_000_000_000
            or control["maximum_age"] % 1_000_000_000 != 0
            or not isinstance(control.get("exception_allowed"), bool)
        ):
            fail("production eligibility control is invalid")
        identifiers.append(control["id"])
    if len(identifiers) != len(controls) or identifiers != sorted(set(identifiers)):
        fail("production eligibility controls must be sorted and unique")
    encoder = CanonicalEncoder("production-control-policy/v1")
    encoder.text("id", policy["id"])
    encoder.text("version", policy["version"])
    encoder.integer("epoch", policy["epoch"])
    encoder.timestamp("valid_until", policy["valid_until"])
    encoder.strings(
        "controls",
        [
            "|".join(
                (
                    control["id"],
                    control["owner"],
                    go_duration(control["maximum_age"]),
                    str(control["exception_allowed"]).lower(),
                )
            )
            for control in controls
        ],
    )
    if policy["digest"] != digest_bytes(encoder.bytes()):
        fail("production eligibility policy digest differs from canonical content")
    return policy


def go_duration(nanoseconds: int) -> str:
    """Render the positive, whole-second duration subset accepted by this contract."""
    seconds = nanoseconds // 1_000_000_000
    hours, seconds = divmod(seconds, 3_600)
    minutes, seconds = divmod(seconds, 60)
    if hours:
        return f"{hours}h{minutes}m{seconds}s"
    if minutes:
        return f"{minutes}m{seconds}s"
    return f"{seconds}s"


def release_digests(gitops: Path) -> list[str]:
    selection_path = gitops / "deployments/production.yaml"
    try:
        selection = yaml.safe_load(selection_path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as error:
        raise ValueError(f"production deployment selection is unreadable: {error}") from error
    applications = selection.get("spec", {}).get("applications")
    if not isinstance(applications, list) or not applications:
        fail("production eligibility requires at least one active release selection")
    result: list[str] = []
    for item in applications:
        relative = Path(str(item.get("releaseMetadata", ""))) if isinstance(item, dict) else Path()
        if relative.is_absolute() or ".." in relative.parts or not str(relative).startswith("releases/"):
            fail("production deployment selection has an unsafe release path")
        record = load_json(gitops / relative, "selected release metadata")
        subject = record.get("subject")
        value = subject.get("digest") if isinstance(subject, dict) else None
        if not isinstance(value, str) or SHA256.fullmatch(value) is None:
            fail("selected release metadata has no immutable subject digest")
        result.append(value)
    result = sorted(set(result))
    if len(result) != len(applications):
        fail("production release subject digests must be unique")
    return result


def canonical_bundle(bundle: dict[str, Any]) -> bytes:
    encoder = CanonicalEncoder("deployment-bundle/v1")
    encoder.text("schema_version", bundle["schema_version"])
    encoder.text("change_reference", bundle["change_reference"])
    encoder.text("environment", bundle["environment"])
    encoder.strings(
        "repositories",
        [item["repository"] + "\0" + item["commit"] for item in bundle["repositories"]],
    )
    encoder.strings("release_digests", bundle["release_digests"])
    encoder.text("gitops_render_digest", bundle["gitops_render_digest"])
    encoder.text("deployment_selection_digest", bundle["deployment_selection_digest"])
    encoder.text("infrastructure_handoff_digest", bundle["infrastructure_handoff_digest"])
    encoder.text("governance_audit_digest", bundle["governance_audit_digest"])
    encoder.text("workflow_release", bundle["workflow_release"])
    encoder.text("policy_bundle_digest", bundle["policy_bundle_digest"])
    return encoder.bytes()


def validate_bundle(bundle: dict[str, Any]) -> None:
    required = {
        "schema_version",
        "bundle_digest",
        "change_reference",
        "environment",
        "repositories",
        "release_digests",
        "gitops_render_digest",
        "deployment_selection_digest",
        "infrastructure_handoff_digest",
        "governance_audit_digest",
        "workflow_release",
        "policy_bundle_digest",
    }
    digest_fields = (
        "bundle_digest",
        "gitops_render_digest",
        "deployment_selection_digest",
        "infrastructure_handoff_digest",
        "governance_audit_digest",
        "policy_bundle_digest",
    )
    repositories = bundle.get("repositories")
    releases = bundle.get("release_digests")
    if (
        set(bundle) != required
        or bundle.get("schema_version") != SCHEMA_BUNDLE
        or CHANGE_REFERENCE.fullmatch(str(bundle.get("change_reference", ""))) is None
        or bundle.get("environment") != "production"
        or not isinstance(repositories, list)
        or len(repositories) != len(REPOSITORIES)
        or not isinstance(releases, list)
        or not 1 <= len(releases) <= 64
        or releases != sorted(set(releases))
        or any(SHA256.fullmatch(str(value)) is None for value in releases)
        or any(SHA256.fullmatch(str(bundle.get(field, ""))) is None for field in digest_fields)
        or SEMANTIC_VERSION.fullmatch(str(bundle.get("workflow_release", ""))) is None
    ):
        fail("deployment bundle fields are invalid")
    for index, repository in enumerate(repositories):
        if (
            not isinstance(repository, dict)
            or set(repository) != {"repository", "commit"}
            or repository["repository"] != REPOSITORIES[index]
            or SHA40.fullmatch(str(repository["commit"])) is None
        ):
            fail("deployment bundle repositories are not exact and immutable")
    if bundle["bundle_digest"] != digest_bytes(canonical_bundle(bundle)):
        fail("deployment bundle digest differs from canonical content")


GOVERNED_POLICY = ".github/contracts/evidence/production-controls.json"


def require_governed_policy(policy: Path, estate: Path) -> None:
    """The policy a decision is evaluated against must match the governed estate copy.

    Extracted from build_bundle because it was unreachable as written and untestable in place.
    Its only caller passed `estate/.github/contracts/evidence/production-controls.json` as
    `policy`, so the comparison was that file against itself -- always equal, never firing, and
    the two copies were free to diverge silently.

    The copy that matters is gitops' VENDORED
    contracts/evidence/production-controls.json: production-qualification-evidence.yml invokes
    `records`, `decide` and `verify-response` with `--policy
    contracts/evidence/production-controls.json`, so that is what a decision is actually
    evaluated against. Proving it matches the governed copy at assembly time is the check this
    was written to be.

    Digests rather than bytes: load_policy canonicalizes, so formatting differences that do not
    change policy are not reported as drift.
    """
    governed = estate / GOVERNED_POLICY
    if policy.resolve() == governed.resolve():
        fail(
            "governed-policy comparison requires the vendored qualification policy, "
            f"not the governed copy at {GOVERNED_POLICY}"
        )
    if load_policy(policy)["digest"] != load_policy(governed)["digest"]:
        fail("qualification policy differs from the governed estate policy")


def build_bundle(
    request: dict[str, Any], estate: Path, audit: Path, policy: Path
) -> dict[str, Any]:
    repositories = request.get("repositories")
    if not isinstance(repositories, dict) or set(repositories) != set(REPOSITORIES):
        fail("deployment bundle repository inventory is not exact")
    revisions = [
        {"repository": repository, "commit": repositories[repository]}
        for repository in REPOSITORIES
    ]
    if any(SHA40.fullmatch(str(item["commit"])) is None for item in revisions):
        fail("deployment bundle contains a mutable repository revision")
    artifacts = request.get("evidence_artifacts")
    handoffs = [
        item
        for item in artifacts if isinstance(item, dict)
        and item.get("key") == "infrastructure-control-plane-handoff"
    ] if isinstance(artifacts, list) else []
    if len(handoffs) != 1:
        fail("production qualification requires one infrastructure control-plane handoff")
    gitops = estate / "gitops"
    bundle = {
        "schema_version": SCHEMA_BUNDLE,
        "bundle_digest": "",
        "change_reference": request["change_reference"],
        "environment": "production",
        "repositories": revisions,
        "release_digests": release_digests(gitops),
        "gitops_render_digest": tree_digest(gitops / "rendered/production"),
        "deployment_selection_digest": file_digest(gitops / "deployments/production.yaml"),
        "infrastructure_handoff_digest": "sha256:" + handoffs[0]["sha256"],
        "governance_audit_digest": file_digest(audit),
        "workflow_release": WORKFLOW_RELEASE,
        "policy_bundle_digest": file_digest(
            estate / ".github/contracts/policy-bundle/manifest.json"
        ),
    }
    require_governed_policy(policy, estate)
    bundle["bundle_digest"] = digest_bytes(canonical_bundle(bundle))
    validate_bundle(bundle)
    return bundle


def canonical_claim(claim: dict[str, Any]) -> bytes:
    artifact = claim["artifact"]
    encoder = CanonicalEncoder("evidence-claim/v1")
    encoder.text("schema_version", claim["schema_version"])
    encoder.text("subject_kind", claim["subject_kind"])
    encoder.text("subject_digest", claim["subject_digest"])
    encoder.text("control_id", claim["control_id"])
    encoder.text("owner", claim["owner"])
    encoder.text("scope", claim["scope"])
    encoder.text("artifact_uri", artifact["uri"])
    encoder.text("artifact_digest", artifact["digest"])
    encoder.text("artifact_media_type", artifact["media_type"])
    encoder.text("source_authority", claim["source_authority"])
    encoder.timestamp("issued_at", claim["issued_at"])
    encoder.timestamp("valid_until", claim["valid_until"])
    return encoder.bytes()


def canonical_verification(verification: dict[str, Any]) -> bytes:
    artifact = verification["artifact"]
    encoder = CanonicalEncoder("evidence-verification/v1")
    encoder.text("schema_version", verification["schema_version"])
    encoder.text("claim_digest", verification["claim_digest"])
    encoder.text("policy_digest", verification["policy_digest"])
    encoder.integer("policy_epoch", verification["policy_epoch"])
    encoder.text("result", verification["result"])
    encoder.strings("reasons", verification["reasons"])
    encoder.text("artifact_uri", artifact["uri"])
    encoder.text("artifact_digest", artifact["digest"])
    encoder.text("artifact_media_type", artifact["media_type"])
    encoder.timestamp("verified_at", verification["verified_at"])
    encoder.timestamp("valid_until", verification["valid_until"])
    return encoder.bytes()


def build_records(
    request: dict[str, Any],
    bundle: dict[str, Any],
    policy: dict[str, Any],
    artifact_root: str,
    issued_at: datetime,
) -> dict[str, Any]:
    validate_bundle(bundle)
    controls = {item["id"]: item for item in policy["controls"]}
    checks = request.get("checks")
    if (
        not isinstance(checks, list)
        or len(checks) != len(controls)
        or any(not isinstance(item, dict) for item in checks)
        or {item.get("control_id") for item in checks} != set(controls)
        or any(item.get("status") != "pass" for item in checks)
    ):
        fail("qualification checks do not cover the active control inventory")
    declarations = request.get("evidence_artifacts")
    if (
        not isinstance(declarations, list)
        or not declarations
        or any(
            not isinstance(item, dict)
            or not CANONICAL_NAME.fullmatch(str(item.get("key", "")))
            or re.fullmatch(r"[0-9a-f]{64}", str(item.get("sha256", ""))) is None
            for item in declarations
        )
    ):
        fail("qualification evidence artifact inventory is invalid")
    artifacts = {item["key"]: item for item in declarations}
    if len(artifacts) != len(declarations):
        fail("qualification evidence artifact keys must be unique")
    if not artifact_root.startswith("gs://") or any(
        character in artifact_root for character in ("\n", "\r", "\0")
    ):
        fail("qualification evidence artifact root is invalid")
    policy_expiry = parse_timestamp(policy["valid_until"])
    if not issued_at < policy_expiry:
        fail("production eligibility policy is expired")
    records = []
    for check in sorted(checks, key=lambda item: item["control_id"]):
        control = controls[check["control_id"]]
        declaration = artifacts.get(check["evidence_key"])
        if declaration is None:
            fail("qualification control references unknown evidence")
        valid_until = min(
            issued_at + timedelta(microseconds=int(control["maximum_age"]) // 1000),
            policy_expiry,
        )
        artifact = {
            "uri": artifact_root.rstrip("/") + "/connected-evidence/" + declaration["key"] + ".zip",
            "digest": "sha256:" + declaration["sha256"],
            "media_type": "application/zip",
        }
        claim = {
            "schema_version": SCHEMA_CLAIM,
            "claim_digest": "",
            "subject_kind": "deployment_bundle",
            "subject_digest": bundle["bundle_digest"],
            "control_id": control["id"],
            "owner": control["owner"],
            "scope": "production",
            "artifact": artifact,
            "source_authority": "production_qualification",
            "issued_at": format_timestamp(issued_at),
            "valid_until": format_timestamp(valid_until),
        }
        claim["claim_digest"] = digest_bytes(canonical_claim(claim))
        verification = {
            "schema_version": SCHEMA_VERIFICATION,
            "verification_digest": "",
            "claim_digest": claim["claim_digest"],
            "policy_digest": policy["digest"],
            "policy_epoch": policy["epoch"],
            "result": "pass",
            "reasons": ["protected_qualification_passed"],
            "artifact": artifact,
            "verified_at": format_timestamp(issued_at),
            "valid_until": format_timestamp(valid_until),
        }
        verification["verification_digest"] = digest_bytes(
            canonical_verification(verification)
        )
        records.append({"claim": claim, "verification": verification})
    return {"records": records}


def canonical_decision(decision: dict[str, Any]) -> bytes:
    encoder = CanonicalEncoder("production-eligibility/v1")
    encoder.text("schema_version", decision["schema_version"])
    encoder.text("bundle_digest", decision["bundle_digest"])
    encoder.text("policy_digest", decision["policy_digest"])
    encoder.integer("policy_epoch", decision["policy_epoch"])
    encoder.text("result", decision["result"])
    encoder.strings("reasons", decision["reasons"])
    encoder.strings(
        "selections",
        [
            item["control_id"] + "|" + item["claim_digest"] + "|" + item["verification_digest"]
            for item in decision["selections"]
        ],
    )
    encoder.strings("exceptions", decision["exceptions"])
    encoder.timestamp("evaluated_at", decision["evaluated_at"])
    encoder.timestamp("expires_at", decision["expires_at"])
    return encoder.bytes()


def verify_response(
    response: dict[str, Any],
    bundle: dict[str, Any],
    policy: dict[str, Any],
    key_id: str,
    payload_out: Path,
    signature_out: Path,
    *,
    now: datetime | None = None,
) -> str:
    verification_time = now if now is not None else datetime.now(timezone.utc)
    if verification_time.utcoffset() is None:
        fail("production eligibility verification time must be timezone-aware")
    validate_bundle(bundle)
    if (
        set(response) != {"signed_decision", "revoked"}
        or response["revoked"] is not False
    ):
        fail("eligibility response inventory or revocation state is invalid")
    signed = response["signed_decision"]
    if not isinstance(signed, dict) or set(signed) != {"decision", "signature"}:
        fail("signed eligibility decision inventory is invalid")
    decision = signed["decision"]
    signature = signed["signature"]
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
    signature_fields = {"algorithm", "key_id", "value"}
    if (
        not isinstance(decision, dict)
        or set(decision) != decision_fields
        or not isinstance(signature, dict)
        or set(signature) != signature_fields
    ):
        fail("signed eligibility decision fields are not exact")
    controls = [item["id"] for item in policy["controls"]]
    selections = decision.get("selections")
    if (
        decision.get("schema_version") != SCHEMA_DECISION
        or decision.get("bundle_digest") != bundle["bundle_digest"]
        or decision.get("policy_digest") != policy["digest"]
        or decision.get("policy_epoch") != policy["epoch"]
        or decision.get("result") != "eligible"
        or decision.get("reasons") != []
        or decision.get("exceptions") != []
        or not isinstance(selections, list)
        or len(selections) != len(controls)
        or any(not isinstance(item, dict) for item in selections)
        or [item.get("control_id") for item in selections] != controls
        or any(
            set(item) != {"control_id", "claim_digest", "verification_digest"}
            or SHA256.fullmatch(str(item.get("claim_digest", ""))) is None
            or SHA256.fullmatch(str(item.get("verification_digest", ""))) is None
            for item in selections
        )
    ):
        fail("production eligibility decision is not an exact eligible result")
    payload = canonical_decision(decision)
    if decision.get("decision_digest") != digest_bytes(payload):
        fail("production eligibility decision digest differs")
    evaluated = parse_timestamp(decision["evaluated_at"])
    expires = parse_timestamp(decision["expires_at"])
    if (
        not expires > evaluated
        or expires - evaluated > timedelta(hours=6)
        or expires > parse_timestamp(policy["valid_until"])
    ):
        fail("production eligibility decision validity window is invalid")
    # The three checks above establish only that the window is internally coherent -- ordered,
    # no wider than six hours, and inside the policy's own validity. None of them reads a clock,
    # so a decision whose window closed weeks ago would satisfy all three and be replayed into
    # `decide` or `publish-decision` as a currently-valid eligible result.
    if verification_time >= expires:
        fail("production eligibility decision has expired")
    if signature.get("algorithm") != "ed25519" or signature.get("key_id") != key_id:
        fail("production eligibility signature identity is invalid")
    try:
        signature_bytes = base64.b64decode(signature.get("value", ""), validate=True)
    except (ValueError, TypeError) as error:
        raise ValueError("production eligibility signature encoding is invalid") from error
    if len(signature_bytes) != 64:
        fail("production eligibility signature length is invalid")
    payload_out.write_bytes(payload)
    signature_out.write_bytes(signature_bytes)
    return decision["decision_digest"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    bundle = commands.add_parser("bundle")
    bundle.add_argument("--request", required=True, type=Path)
    bundle.add_argument("--estate", required=True, type=Path)
    bundle.add_argument("--audit", required=True, type=Path)
    bundle.add_argument("--policy", required=True, type=Path)
    bundle.add_argument("--output", required=True, type=Path)
    records = commands.add_parser("records")
    records.add_argument("--request", required=True, type=Path)
    records.add_argument("--bundle", required=True, type=Path)
    records.add_argument("--policy", required=True, type=Path)
    records.add_argument("--artifact-root", required=True)
    records.add_argument("--issued-at", required=True)
    records.add_argument("--output", required=True, type=Path)
    verify = commands.add_parser("verify-response")
    verify.add_argument("--response", required=True, type=Path)
    verify.add_argument("--bundle", required=True, type=Path)
    verify.add_argument("--policy", required=True, type=Path)
    verify.add_argument("--key-id", required=True)
    verify.add_argument("--payload-output", required=True, type=Path)
    verify.add_argument("--signature-output", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.command == "bundle":
            value = build_bundle(
                load_json(args.request, "qualification request"),
                args.estate,
                args.audit,
                args.policy,
            )
            args.output.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            print(value["bundle_digest"])
        elif args.command == "records":
            value = build_records(
                load_json(args.request, "qualification request"),
                load_json(args.bundle, "deployment bundle"),
                load_policy(args.policy),
                args.artifact_root,
                parse_timestamp(args.issued_at),
            )
            args.output.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            print(len(value["records"]))
        else:
            print(
                verify_response(
                    load_json(args.response, "eligibility response"),
                    load_json(args.bundle, "deployment bundle"),
                    load_policy(args.policy),
                    args.key_id,
                    args.payload_output,
                    args.signature_output,
                )
            )
        return 0
    except (OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
