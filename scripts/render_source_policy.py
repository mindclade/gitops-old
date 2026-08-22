#!/usr/bin/env python3
# Copyright © 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

"""Validate the monorepo-to-GitOps render source authority boundary."""

from __future__ import annotations

import re


CANONICAL_REPOSITORY = "mindclade/mindclade-internal-monorepo"
LEGACY_SOURCE = "infra/gitops/environments/{env}"
LEGACY_REF = "v0.1.1"


def render_source_policy_errors(
    repository: str, ref: str, target_sources: list[str]
) -> list[str]:
    """Return every source-authority violation without mutating render state."""

    errors: list[str] = []
    if repository != CANONICAL_REPOSITORY:
        errors.append(
            f"unauthorized render source repository: {repository or '<missing>'}"
        )
    if not (
        re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", ref)
        or re.fullmatch(r"[0-9a-f]{40}", ref)
    ):
        errors.append(
            "render source ref is not a protected full semver tag or commit SHA: "
            f"{ref or '<missing>'}"
        )

    for source in target_sources:
        if source == LEGACY_SOURCE:
            if ref != LEGACY_REF:
                errors.append(
                    f"the frozen legacy platform-core source is authorized only at {LEGACY_REF}"
                )
            continue
        if source.startswith("infra/gitops/"):
            errors.append(
                f"new render target uses retired monorepo GitOps authority: {source}"
            )
            continue
        if not source.startswith("infra/kubernetes/"):
            errors.append(
                f"render target is outside the approved Kubernetes source tree: {source}"
            )
            continue
        if re.search(
            r"/(?:overlays|environments)/(?:development|staging|production)(?:/|$)",
            source,
        ):
            errors.append(
                f"render target embeds live environment composition in the monorepo: {source}"
            )
    return errors
