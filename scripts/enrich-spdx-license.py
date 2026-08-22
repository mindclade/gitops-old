#!/usr/bin/env python3
# Copyright © 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

"""Attach and validate Mindclade's proprietary LicenseRef in SPDX 2.3 SBOMs."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

LICENSE_ID = "LicenseRef-Mindclade-Proprietary"
LICENSE_NAME = "Mindclade Proprietary License (mindclade-license@2)"
PACKAGE_ID = "SPDXRef-Mindclade-Artifact"
DOCUMENT_ID = "SPDXRef-DOCUMENT"
SHA256_RE = re.compile(r"^sha256:([a-f0-9]{64})$")
SOURCE_SHA_RE = re.compile(r"^[a-f0-9]{40,64}$")
REPOSITORY_RE = re.compile(r"^mindclade/[A-Za-z0-9._-]+$")
VERSION_RE = re.compile(r"^[0-9]{4}\.[0-9]{2}\.[0-9]{2}\.[1-9][0-9]*$")


class SpdxLicenseError(ValueError):
    """An SBOM or policy input violated the proprietary-license contract."""


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise SpdxLicenseError(f"{label} must be a string-keyed object")
    return value


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SpdxLicenseError(f"cannot load {label} {path}: {exc}") from exc
    return _mapping(value, label)


def policy_identity(manifest_path: Path, license_path: Path) -> tuple[str, str, str]:
    manifest = _load_json(manifest_path, "policy manifest")
    if manifest.get("bundleId") != "mindclade-policy-bundle":
        raise SpdxLicenseError("policy manifest bundleId is not canonical")
    if manifest.get("licenseExpression") != LICENSE_ID:
        raise SpdxLicenseError("policy manifest does not declare the proprietary LicenseRef")
    version = manifest.get("version")
    if not isinstance(version, str) or not VERSION_RE.fullmatch(version):
        raise SpdxLicenseError("policy manifest version is malformed")
    licenses = [
        item
        for item in manifest.get("artifacts", [])
        if isinstance(item, dict) and item.get("name") == "proprietary-license"
    ]
    if len(licenses) != 1 or licenses[0].get("source") != "LICENSE":
        raise SpdxLicenseError("policy manifest must identify one canonical LICENSE artifact")
    license_digest = _sha256(license_path)
    if licenses[0].get("sha256") != license_digest:
        raise SpdxLicenseError("LICENSE bytes do not match the policy bundle")
    return version, _sha256(manifest_path), license_digest


def _license_info(
    *,
    license_text: str,
    license_digest: str,
    repository: str,
    source_sha: str,
    bundle_version: str,
    manifest_digest: str,
) -> dict[str, Any]:
    return {
        "licenseId": LICENSE_ID,
        "extractedText": license_text,
        "name": LICENSE_NAME,
        "comment": (
            f"Complete canonical license text; SHA-256: {license_digest}; "
            f"policy bundle: {bundle_version}; manifest SHA-256: {manifest_digest}."
        ),
        "seeAlsos": [
            f"https://github.com/{repository}/blob/{source_sha}/LICENSE",
            "https://github.com/mindclade/.github/blob/main/"
            "contracts/policy-bundle/manifest.json",
        ],
    }


def _first_party_package(
    *, artifact_name: str, artifact_digest: str, repository: str, source_sha: str
) -> dict[str, Any]:
    digest = SHA256_RE.fullmatch(artifact_digest)
    if digest is None:
        raise SpdxLicenseError("artifact digest must be lowercase sha256:<64 hex>")
    if not artifact_name.strip() or "\n" in artifact_name:
        raise SpdxLicenseError("artifact name must be a nonempty single-line value")
    return {
        "name": artifact_name,
        "SPDXID": PACKAGE_ID,
        "versionInfo": artifact_digest,
        "supplier": "Organization: Mindclade, LLC.",
        "downloadLocation": "NOASSERTION",
        "filesAnalyzed": False,
        "checksums": [{"algorithm": "SHA256", "checksumValue": digest.group(1)}],
        "licenseConcluded": LICENSE_ID,
        "licenseDeclared": LICENSE_ID,
        "copyrightText": "Copyright © 2026 Mindclade, LLC. All Rights Reserved.",
        "comment": f"First-party artifact from {repository} source commit {source_sha}.",
    }


def enrich_document(
    document: dict[str, Any],
    *,
    license_text: str,
    license_digest: str,
    repository: str,
    source_sha: str,
    artifact_name: str,
    artifact_digest: str,
    bundle_version: str,
    manifest_digest: str,
) -> dict[str, Any]:
    """Add one exact extracted license and one first-party artifact package."""
    if document.get("spdxVersion") != "SPDX-2.3":
        raise SpdxLicenseError("SBOM must use SPDX-2.3")
    if document.get("dataLicense") != "CC0-1.0":
        raise SpdxLicenseError("SPDX document dataLicense must be CC0-1.0")
    if document.get("SPDXID") != DOCUMENT_ID:
        raise SpdxLicenseError(f"SPDX document id must be {DOCUMENT_ID}")
    if not REPOSITORY_RE.fullmatch(repository):
        raise SpdxLicenseError("repository must be a canonical mindclade owner/name")
    if not SOURCE_SHA_RE.fullmatch(source_sha):
        raise SpdxLicenseError("source SHA must be a lowercase Git object id")
    if not license_text.endswith("\n") or LICENSE_ID not in license_text:
        raise SpdxLicenseError(
            "canonical LICENSE must be complete, newline-terminated, and identify its LicenseRef"
        )
    if _sha256_bytes(license_text.encode("utf-8")) != license_digest:
        raise SpdxLicenseError("canonical LICENSE digest does not match its bytes")

    extracted = document.get("hasExtractedLicensingInfos", [])
    if not isinstance(extracted, list):
        raise SpdxLicenseError("hasExtractedLicensingInfos must be a list")
    extracted = [
        item
        for item in extracted
        if not isinstance(item, dict) or item.get("licenseId") != LICENSE_ID
    ]
    extracted.append(
        _license_info(
            license_text=license_text,
            license_digest=license_digest,
            repository=repository,
            source_sha=source_sha,
            bundle_version=bundle_version,
            manifest_digest=manifest_digest,
        )
    )
    document["hasExtractedLicensingInfos"] = sorted(
        extracted,
        key=lambda item: str(item.get("licenseId", "")) if isinstance(item, dict) else "",
    )

    packages = document.get("packages", [])
    if not isinstance(packages, list):
        raise SpdxLicenseError("packages must be a list")
    packages = [
        item
        for item in packages
        if not isinstance(item, dict) or item.get("SPDXID") != PACKAGE_ID
    ]
    packages.append(
        _first_party_package(
            artifact_name=artifact_name,
            artifact_digest=artifact_digest,
            repository=repository,
            source_sha=source_sha,
        )
    )
    document["packages"] = packages

    relationships = document.get("relationships", [])
    if not isinstance(relationships, list):
        raise SpdxLicenseError("relationships must be a list")
    relationship = {
        "spdxElementId": DOCUMENT_ID,
        "relationshipType": "DESCRIBES",
        "relatedSpdxElement": PACKAGE_ID,
    }
    document["relationships"] = [
        item
        for item in relationships
        if not (
            isinstance(item, dict)
            and item.get("spdxElementId") == DOCUMENT_ID
            and item.get("relationshipType") == "DESCRIBES"
            and item.get("relatedSpdxElement") == PACKAGE_ID
        )
    ] + [relationship]
    return document


def validate_document(document: dict[str, Any], **contract: Any) -> None:
    expected = enrich_document(json.loads(json.dumps(document)), **contract)
    expected_license = next(
        item
        for item in expected["hasExtractedLicensingInfos"]
        if item.get("licenseId") == LICENSE_ID
    )
    actual_licenses = [
        item
        for item in document.get("hasExtractedLicensingInfos", [])
        if isinstance(item, dict) and item.get("licenseId") == LICENSE_ID
    ]
    if actual_licenses != [expected_license]:
        raise SpdxLicenseError(
            "SPDX proprietary extracted licensing information is absent or stale"
        )
    expected_package = next(
        item for item in expected["packages"] if item.get("SPDXID") == PACKAGE_ID
    )
    actual_packages = [
        item
        for item in document.get("packages", [])
        if isinstance(item, dict) and item.get("SPDXID") == PACKAGE_ID
    ]
    if actual_packages != [expected_package]:
        raise SpdxLicenseError("SPDX first-party artifact package is absent or stale")
    relationship = {
        "spdxElementId": DOCUMENT_ID,
        "relationshipType": "DESCRIBES",
        "relatedSpdxElement": PACKAGE_ID,
    }
    if document.get("relationships", []).count(relationship) != 1:
        raise SpdxLicenseError(
            "SPDX document must describe the first-party artifact exactly once"
        )


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    payload = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        delete=False,
    ) as stream:
        temporary = Path(stream.name)
        stream.write(payload)
        stream.flush()
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("enrich", "validate"))
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--license", type=Path, default=Path("LICENSE"))
    parser.add_argument(
        "--policy-manifest",
        type=Path,
        default=Path("contracts/policy-bundle/manifest.json"),
    )
    parser.add_argument("--repository", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--artifact-name", required=True)
    parser.add_argument("--artifact-digest", required=True)
    args = parser.parse_args()
    try:
        document = _load_json(args.input, "SPDX document")
        license_text = args.license.read_text(encoding="utf-8")
        bundle_version, manifest_digest, license_digest = policy_identity(
            args.policy_manifest, args.license
        )
        contract = {
            "license_text": license_text,
            "license_digest": license_digest,
            "repository": args.repository,
            "source_sha": args.source_sha,
            "artifact_name": args.artifact_name,
            "artifact_digest": args.artifact_digest,
            "bundle_version": bundle_version,
            "manifest_digest": manifest_digest,
        }
        if args.command == "enrich":
            if args.output is None:
                raise SpdxLicenseError("enrich requires --output")
            enriched = enrich_document(document, **contract)
            validate_document(enriched, **contract)
            _atomic_json(args.output, enriched)
            print(f"SPDX proprietary LicenseRef enriched: {args.output}")
        else:
            if args.output is not None:
                raise SpdxLicenseError("validate does not accept --output")
            validate_document(document, **contract)
            print(f"SPDX proprietary LicenseRef validated: {args.input}")
    except (OSError, UnicodeDecodeError, SpdxLicenseError) as exc:
        print(f"SPDX proprietary LicenseRef validation failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
