#!/usr/bin/env python3
# Copyright © 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

"""Generate deterministic third-party notices from reviewed provenance contracts."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

PROPRIETARY = "LicenseRef-Mindclade-Proprietary"
SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")
SOURCE_TYPES = {"dataset-manifest", "lockfile", "model-card", "sbom", "vendored-provenance"}


class NoticeError(ValueError):
    """Third-party provenance or notice output violated its contract."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _safe_path(root: Path, raw: Any, label: str) -> Path:
    if not isinstance(raw, str) or not raw or "\\" in raw:
        raise NoticeError(f"{label} must be a nonempty POSIX relative path")
    relative = Path(raw)
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        raise NoticeError(f"{label} must be a normalized relative path")
    path = (root / relative).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise NoticeError(f"{label} escapes the repository") from exc
    return path


def _exact(value: dict[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise NoticeError(f"{label} keys must be exactly {sorted(expected)}")


def load_contract(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise NoticeError(f"cannot load notice contract {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise NoticeError("notice contract must be an object")
    _exact(value, {"schemaVersion", "repository", "inventorySources", "materials"}, "contract")
    if value["schemaVersion"] != 1:
        raise NoticeError("schemaVersion must be 1")
    if not re.fullmatch(r"mindclade/[A-Za-z0-9._-]+", str(value["repository"])):
        raise NoticeError("repository must be a canonical mindclade owner/name")
    if not isinstance(value["inventorySources"], list) or not isinstance(value["materials"], list):
        raise NoticeError("inventorySources and materials must be lists")
    return value


def repository_identity(root: Path) -> str:
    """Resolve repository identity from the governed contract, not its checkout path."""
    path = root / "contracts" / "repository.yaml"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise NoticeError(f"cannot load repository contract {path}: {exc}") from exc
    matches = re.findall(r"^repository:\s*([A-Za-z0-9._-]+)\s*$", text, re.MULTILINE)
    if len(matches) != 1:
        raise NoticeError("repository contract must declare exactly one repository identity")
    return f"mindclade/{matches[0]}"


def validate_contract(contract: dict[str, Any], root: Path) -> list[dict[str, Any]]:
    sources: set[str] = set()
    for index, source in enumerate(contract["inventorySources"]):
        if not isinstance(source, dict):
            raise NoticeError(f"inventorySources[{index}] must be an object")
        _exact(source, {"type", "path", "sha256"}, f"inventorySources[{index}]")
        if source["type"] not in SOURCE_TYPES:
            raise NoticeError(f"inventorySources[{index}].type is unsupported")
        path = _safe_path(root, source["path"], f"inventorySources[{index}].path")
        if not path.is_file() or _sha256(path) != source["sha256"]:
            raise NoticeError(f"inventory source is absent or stale: {source['path']}")
        if source["path"] in sources:
            raise NoticeError(f"duplicate inventory source: {source['path']}")
        sources.add(source["path"])

    names: set[tuple[str, str]] = set()
    materials: list[dict[str, Any]] = []
    for index, material in enumerate(contract["materials"]):
        if not isinstance(material, dict):
            raise NoticeError(f"materials[{index}] must be an object")
        _exact(
            material,
            {
                "name",
                "version",
                "licenseExpression",
                "attribution",
                "sourceUrl",
                "licenseText",
                "includedPaths",
                "evidencePaths",
                "sbomNames",
            },
            f"materials[{index}]",
        )
        name, version = material["name"], material["version"]
        if not isinstance(name, str) or not name.strip():
            raise NoticeError(f"materials[{index}].name is missing")
        if not isinstance(version, str) or not VERSION_RE.fullmatch(version):
            raise NoticeError(f"materials[{index}].version is missing or malformed")
        if (name.casefold(), version.casefold()) in names:
            raise NoticeError(f"duplicate material: {name} {version}")
        names.add((name.casefold(), version.casefold()))
        expression = material["licenseExpression"]
        if expression in {"", "NONE", "NOASSERTION", PROPRIETARY}:
            raise NoticeError(f"materials[{index}] lacks an independent license expression")
        if not isinstance(material["attribution"], str) or len(material["attribution"].strip()) < 8:
            raise NoticeError(f"materials[{index}] lacks attribution")
        if not isinstance(material["sourceUrl"], str) or not material["sourceUrl"].startswith("https://"):
            raise NoticeError(f"materials[{index}] sourceUrl must be HTTPS")
        license_record = material["licenseText"]
        if not isinstance(license_record, dict):
            raise NoticeError(f"materials[{index}].licenseText must be an object")
        _exact(license_record, {"path", "sha256"}, f"materials[{index}].licenseText")
        license_path = _safe_path(root, license_record["path"], f"materials[{index}].licenseText.path")
        if not license_path.is_file() or license_path.stat().st_size < 100:
            raise NoticeError(f"materials[{index}] license text is absent or abbreviated")
        if not SHA256_RE.fullmatch(str(license_record["sha256"])) or _sha256(license_path) != license_record["sha256"]:
            raise NoticeError(f"materials[{index}] license text digest is absent or stale")
        for field in ("includedPaths", "evidencePaths", "sbomNames"):
            if not isinstance(material[field], list) or not all(
                isinstance(item, str) and item for item in material[field]
            ):
                raise NoticeError(f"materials[{index}].{field} must be a string list")
        if not material["includedPaths"] or not material["evidencePaths"]:
            raise NoticeError(f"materials[{index}] requires included and provenance paths")
        for field in ("includedPaths", "evidencePaths"):
            for raw in material[field]:
                if not _safe_path(root, raw, f"materials[{index}].{field}").exists():
                    raise NoticeError(f"materials[{index}] references missing path: {raw}")
        rendered = dict(material)
        rendered["licenseBody"] = license_path.read_text(encoding="utf-8")
        materials.append(rendered)
    return sorted(materials, key=lambda item: (item["name"].casefold(), item["version"]))


def validate_spdx_coverage(paths: list[Path], materials: list[dict[str, Any]]) -> None:
    covered = {
        name.casefold()
        for material in materials
        for name in material["sbomNames"]
    }
    for path in paths:
        document = json.loads(path.read_text(encoding="utf-8"))
        for package in document.get("packages", []):
            if not isinstance(package, dict):
                raise NoticeError(f"{path}: SPDX package must be an object")
            name = str(package.get("name", "")).strip()
            if package.get("SPDXID") in {
                "SPDXRef-Mindclade-Artifact",
                "SPDXRef-Mindclade-Release",
            }:
                continue
            if not name or name.casefold() not in covered:
                raise NoticeError(f"{path}: SPDX package lacks reviewed notice metadata: {name or '<unnamed>'}")


def render(contract: dict[str, Any], materials: list[dict[str, Any]]) -> str:
    lines = [
        "<!-- Generated by mindclade-policy-bundle third-party-notices@1; DO NOT EDIT. -->",
        "",
        "# Third-party notices",
        "",
        f"Repository: `{contract['repository']}`",
        "",
        "This file records independently licensed material declared by the reviewed provenance",
        "contract. The complete license text below controls for each identified material; the",
        "Mindclade proprietary license does not replace or narrow those third-party terms.",
        "",
        "## Inventory evidence",
        "",
    ]
    if contract["inventorySources"]:
        for source in sorted(contract["inventorySources"], key=lambda item: item["path"]):
            lines.append(
                f"- `{source['path']}` · {source['type']} · SHA-256 `{source['sha256']}`"
            )
    else:
        lines.append("- No repository-resident third-party inventory source is declared.")
    lines.extend(["", "## Materials", ""])
    if not materials:
        lines.extend(
            [
                "No repository-resident third-party material is declared by this contract.",
                "Release-time SBOM validation remains mandatory for distributed artifacts.",
                "",
            ]
        )
    for material in materials:
        lines.extend(
            [
                f"### {material['name']} {material['version']}",
                "",
                f"- License: `{material['licenseExpression']}`",
                f"- Attribution: {material['attribution']}",
                f"- Source: {material['sourceUrl']}",
                "- Included paths: "
                + ", ".join(f"`{path}`" for path in material["includedPaths"]),
                "- Provenance: "
                + ", ".join(f"`{path}`" for path in material["evidencePaths"]),
                f"- License text SHA-256: `{material['licenseText']['sha256']}`",
                "",
                "<details><summary>Complete license text</summary>",
                "",
                "<pre>",
                html.escape(material["licenseBody"].rstrip("\n")),
                "</pre>",
                "",
                "</details>",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def atomic_write(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
    ) as stream:
        temporary = Path(stream.name)
        stream.write(payload)
        stream.flush()
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--manifest", type=Path, default=Path("contracts/third-party-materials.json"))
    parser.add_argument("--output", type=Path, default=Path("THIRD_PARTY_NOTICES.md"))
    parser.add_argument("--spdx", type=Path, action="append", default=[])
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    try:
        manifest_path = args.manifest if args.manifest.is_absolute() else root / args.manifest
        output_path = args.output if args.output.is_absolute() else root / args.output
        contract = load_contract(manifest_path)
        if contract["repository"] != repository_identity(root):
            raise NoticeError("notice contract repository does not match the target root")
        materials = validate_contract(contract, root)
        spdx_paths = [path if path.is_absolute() else root / path for path in args.spdx]
        validate_spdx_coverage(spdx_paths, materials)
        payload = render(contract, materials)
        if args.write:
            atomic_write(output_path, payload)
            print(f"third-party notices generated: {output_path}")
        elif not output_path.is_file() or output_path.read_text(encoding="utf-8") != payload:
            raise NoticeError(f"generated output is absent or stale: {output_path}")
        else:
            print(f"third-party notices verified: {output_path}")
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, NoticeError) as exc:
        print(f"third-party notice validation failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
