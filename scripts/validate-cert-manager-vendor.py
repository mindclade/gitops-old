#!/usr/bin/env python3
# Copyright © 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

"""Prove the offline cert-manager v1.19.1 split, provenance, and render locks."""

from __future__ import annotations

import base64
import gzip
import hashlib
import shutil
import subprocess
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "contracts/cert-manager-v1.19.1.lock.yaml"


def expanded_phase(name: str, phase: dict) -> bytes:
    payload = ROOT / str(phase["payload"])
    compressed = base64.b64decode("".join(payload.read_text().split()), validate=True)
    expanded = gzip.decompress(compressed)
    if len(expanded) != phase["expandedBytes"]:
        raise ValueError(f"cert-manager {name} expanded byte count drifted")
    if hashlib.sha256(expanded).hexdigest() != phase["expandedSha256"]:
        raise ValueError(f"cert-manager {name} expanded SHA-256 drifted")
    documents = [item for item in yaml.safe_load_all(expanded) if isinstance(item, dict)]
    if len(documents) != phase["objects"]:
        raise ValueError(f"cert-manager {name} object count drifted")
    expected_kind = "CustomResourceDefinition" if name == "crds" else None
    if expected_kind and any(item.get("kind") != expected_kind for item in documents):
        raise ValueError("cert-manager CRD phase contains a non-CRD")
    if name == "controllers" and any(item.get("kind") == "CustomResourceDefinition" for item in documents):
        raise ValueError("cert-manager controller phase contains a CRD")
    return expanded


def normalized_inventory(paths: list[Path]) -> bytes:
    expression = (
        "[.] | flatten | map(select(.kind != null and .apiVersion != null)) | "
        'sort_by(.apiVersion, .kind, (.metadata.namespace // ""), .metadata.name)'
    )
    return subprocess.run(
        ["yq", "eval-all", "-o=json", "-I=0", expression, *map(str, paths)],
        check=True,
        capture_output=True,
    ).stdout


def main() -> int:
    lock = yaml.safe_load(LOCK.read_text()) or {}
    spec = lock.get("spec") or {}
    upstream = spec.get("upstream") or {}
    expected_upstream = {
        "url": "https://github.com/cert-manager/cert-manager/releases/download/v1.19.1/cert-manager.yaml",
        "bytes": 1007958,
        "sha256": "876a41a57e36b85619f4124b24b3deb80912b5ffed515f90e2f160b6e6338e81",
        "objects": 49,
        "normalizedSha256": "bfed2738c90092d611ddbad9ba4ae5e1a4af3a291c45f1fd3cddfe9f5914f677",
    }
    if upstream != expected_upstream:
        raise ValueError("cert-manager upstream provenance lock drifted")
    phases = spec.get("phases") or {}
    if set(phases) != {"crds", "controllers"}:
        raise ValueError("cert-manager phase inventory is not exact")
    expanded = {name: expanded_phase(name, phases[name]) for name in phases}
    if sum(phases[name]["objects"] for name in phases) != upstream["objects"]:
        raise ValueError("cert-manager 6+43 phase parity is not 49")

    with tempfile.TemporaryDirectory(prefix="mindclade-cert-manager-validate-") as directory:
        temp = Path(directory)
        raw_paths = []
        rendered: dict[str, list[dict]] = {}
        for name, body in expanded.items():
            raw = temp / f"{name}.yaml"
            raw.write_bytes(body)
            raw_paths.append(raw)
            stage = temp / name
            stage.mkdir()
            source = ROOT / "vendor/cert-manager/v1.19.1" / name
            for path in source.iterdir():
                if path.is_file() and not path.name.endswith(".gz.b64"):
                    shutil.copy2(path, stage / path.name)
            (stage / "upstream.yaml").write_bytes(body)
            output = subprocess.run(
                ["kustomize", "build", "--load-restrictor", "LoadRestrictionsNone", str(stage)],
                check=True,
                capture_output=True,
                text=True,
            ).stdout
            rendered[name] = [item for item in yaml.safe_load_all(output) if isinstance(item, dict)]
        normalized = normalized_inventory(raw_paths)
        if hashlib.sha256(normalized).hexdigest() != upstream["normalizedSha256"]:
            raise ValueError("cert-manager normalized 49-object inventory drifted")

    crds = rendered["crds"]
    if len(crds) != 6 or any(
        "Prune=false,Delete=false"
        not in ((item.get("metadata") or {}).get("annotations") or {}).get(
            "argocd.argoproj.io/sync-options", ""
        )
        for item in crds
    ):
        raise ValueError("cert-manager CRDs lost no-prune/no-delete protection")
    controllers = rendered["controllers"]
    if any(item.get("kind") == "Namespace" for item in controllers):
        raise ValueError("cert-manager controller phase overlaps Namespace ownership")
    images = []
    for item in controllers:
        if item.get("kind") == "Deployment":
            containers = ((((item.get("spec") or {}).get("template") or {}).get("spec") or {}).get("containers") or [])
            images.extend(str(container.get("image", "")) for container in containers)
    expected_digests = set((spec.get("controllerImages") or {}).values())
    if {image.split("@", 1)[1] for image in images if "@" in image} != expected_digests:
        raise ValueError("cert-manager controller image digest set drifted")
    if any("@sha256:" not in image for image in images):
        raise ValueError("cert-manager controller phase contains an unpinned image")
    print("cert-manager offline vendor lock passed (6 CRDs + 43 controllers = 49 upstream objects)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
