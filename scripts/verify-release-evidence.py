#!/usr/bin/env python3
# Copyright © 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

"""Verify governed Binary Authorization evidence without mutating local credentials."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


DIGEST_IMAGE = re.compile(r"[^\s]+@sha256:[0-9a-f]{64}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("images", type=Path)
    parser.add_argument("unsigned_exceptions", type=Path)
    return parser.parse_args()


def gcloud_json(arguments: list[str]) -> Any:
    output = subprocess.run(
        ["gcloud", *arguments, "--format=json"],
        check=True,
        text=True,
        capture_output=True,
    ).stdout
    return json.loads(output)


def valid_occurrence(
    occurrence: dict[str, Any], token: str, project: str, attestor: str
) -> bool:
    if not all(
        occurrence.get(key) for key in ("attestation", "noteName", "resourceUri")
    ):
        return False
    payload = json.dumps(
        {
            "attestation": occurrence["attestation"],
            "occurrenceNote": occurrence["noteName"],
            "occurrenceResourceUri": occurrence["resourceUri"],
        }
    ).encode()
    request = urllib.request.Request(
        f"https://binaryauthorization.googleapis.com/v1/projects/{project}/attestors/"
        f"{attestor}:validateAttestationOccurrence",
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        value = json.load(response)
    return value.get("result") == "VERIFIED"


def image_has_evidence(image: str, token: str, project: str, attestor: str) -> bool:
    occurrences = gcloud_json(
        [
            "container",
            "binauthz",
            "attestations",
            "list",
            f"--project={project}",
            f"--attestor={attestor}",
            f"--attestor-project={project}",
            f"--artifact-url={image}",
            "--limit=100",
        ]
    )
    return any(valid_occurrence(item, token, project, attestor) for item in occurrences)


def policy(token: str, project: str) -> dict[str, Any]:
    request = urllib.request.Request(
        f"https://binaryauthorization.googleapis.com/v1/projects/{project}/policy",
        headers={"Authorization": f"Bearer {token}"},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        value = json.load(response)
    if not isinstance(value, dict):
        raise ValueError("Binary Authorization policy response is not an object")
    return value


def governed_exceptions(path: Path) -> dict[str, dict[str, Any]]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list):
        raise ValueError("unsigned exceptions must be a JSON list")
    today = dt.date.today()
    result: dict[str, dict[str, Any]] = {}
    for index, exception in enumerate(value):
        if not isinstance(exception, dict):
            raise ValueError(f"unsigned exception[{index}] is not an object")
        image = str(exception.get("image", ""))
        if not DIGEST_IMAGE.fullmatch(image) or image in result:
            raise ValueError(f"unsigned exception[{index}] is not one unique exact digest")
        if exception.get("owner") != "@mindclade/platform":
            raise ValueError(f"unsigned exception[{index}] has the wrong owner")
        if exception.get("reviewer") != "@mindclade/security":
            raise ValueError(f"unsigned exception[{index}] has the wrong reviewer")
        if exception.get("approval") != "required-protected-security-review":
            raise ValueError(f"unsigned exception[{index}] lacks protected review")
        if exception.get("scope") != {
            "component": "argocd-control-plane",
            "environments": ["staging", "production"],
        }:
            raise ValueError(f"unsigned exception[{index}] has the wrong scope")
        for field in ("reason", "change", "removal"):
            if not str(exception.get(field, "")).strip():
                raise ValueError(f"unsigned exception[{index}] is missing {field}")
        granted = dt.date.fromisoformat(str(exception.get("granted", "")))
        expires = dt.date.fromisoformat(str(exception.get("expires", "")))
        if expires < today or expires < granted or (expires - granted).days > 90:
            raise ValueError(f"unsigned exception[{index}] is expired or too broad in time")
        result[image] = exception
    return result


def policy_errors(
    value: dict[str, Any], exceptions: set[str], project: str, attestor: str
) -> list[str]:
    errors: list[str] = []
    if value.get("globalPolicyEvaluationMode") != "ENABLE":
        errors.append("global policy evaluation is not enabled")
    default = value.get("defaultAdmissionRule") or {}
    if default.get("evaluationMode") != "REQUIRE_ATTESTATION":
        errors.append("default rule does not require attestation")
    if default.get("enforcementMode") != "ENFORCED_BLOCK_AND_AUDIT_LOG":
        errors.append("default rule is not block-and-audit enforced")
    required_attestors = set(default.get("requireAttestationsBy") or [])
    expected_attestor = f"projects/{project}/attestors/{attestor}"
    if required_attestors != {expected_attestor}:
        errors.append("default rule does not require exactly the deployment attestor")
    if value.get("clusterAdmissionRules"):
        errors.append("cluster admission rules must be empty")
    if value.get("kubernetesNamespaceAdmissionRules"):
        errors.append("namespace admission rules must be empty")
    applied_exceptions = {
        str(item.get("namePattern", ""))
        for item in value.get("admissionWhitelistPatterns") or []
        if isinstance(item, dict)
    }
    if applied_exceptions != exceptions:
        missing = sorted(exceptions - applied_exceptions)
        extra = sorted(applied_exceptions - exceptions)
        errors.append(
            f"applied exact-digest exceptions disagree with GitOps; missing={missing}, extra={extra}"
        )
    if any("*" in image or not DIGEST_IMAGE.fullmatch(image) for image in applied_exceptions):
        errors.append("applied exception is not one exact digest")
    return errors


def lines(path: Path) -> list[str]:
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def main() -> int:
    args = parse_args()
    if not args.images.is_file() or not args.unsigned_exceptions.is_file():
        print(
            "error: images and unsigned-exceptions files are required", file=sys.stderr
        )
        return 2
    project = os.environ.get("BINAUTHZ_DEPLOYMENT_ATTESTOR_PROJECT", "")
    attestor = os.environ.get("BINAUTHZ_DEPLOYMENT_ATTESTOR", "")
    if not project or not attestor:
        print(
            "error: Binary Authorization attestor environment is incomplete",
            file=sys.stderr,
        )
        return 2
    try:
        token = subprocess.run(
            ["gcloud", "auth", "print-access-token"],
            check=True,
            text=True,
            capture_output=True,
        ).stdout.strip()
        if not token:
            raise ValueError("gcloud returned an empty access token")
        unsigned = governed_exceptions(args.unsigned_exceptions)
        active_images = set(lines(args.images))
        orphaned = set(unsigned) - active_images
        if orphaned:
            raise ValueError(f"unsigned exceptions are not active control-plane images: {sorted(orphaned)}")
        applied_policy = policy(token, project)
        failures = policy_errors(applied_policy, set(unsigned), project, attestor)
        if failures:
            for failure in failures:
                print(f"::error::Binary Authorization policy: {failure}", file=sys.stderr)
            return 1
        status = 0
        for image in sorted(active_images):
            if image in unsigned:
                print(f"verified applied exact-digest control-plane exception: {image}")
            elif image_has_evidence(image, token, project, attestor):
                print(f"verified governed deployment attestation: {image}")
            else:
                print(
                    f"::error::no cryptographically valid governed deployment attestation for {image}",
                    file=sys.stderr,
                )
                status = 1
        return status
    except (
        FileNotFoundError,
        json.JSONDecodeError,
        OSError,
        subprocess.CalledProcessError,
        urllib.error.URLError,
        ValueError,
    ) as error:
        print(
            f"error: evidence service unavailable or invalid: {error}", file=sys.stderr
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
