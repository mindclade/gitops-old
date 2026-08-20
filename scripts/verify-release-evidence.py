#!/usr/bin/env python3
# Copyright © 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

"""Verify governed Binary Authorization evidence without mutating local credentials."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


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
        unsigned = set(lines(args.unsigned_exceptions))
        status = 0
        for image in lines(args.images):
            if image in unsigned:
                print(f"approved third-party digest: {image}")
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
