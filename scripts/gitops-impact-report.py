#!/usr/bin/env python3
# Copyright © 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

"""Produce a deterministic desired-state blast-radius report for one Git range."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml
import jsonschema


ENVIRONMENTS = ("development", "staging", "production", "ci")
RBAC_ALLOW_FIELDS = (
    "sourceRepos",
    "sourceNamespaces",
    "destinations",
    "clusterResourceWhitelist",
    "namespaceResourceWhitelist",
    "roles",
)
RBAC_DENY_FIELDS = ("clusterResourceBlacklist", "namespaceResourceBlacklist")
CRITICAL_PREFIXES = (
    "bootstrap/",
    "deployments/production",
    "overlays/production",
    "roots/production/",
)
CONTROL_PREFIXES = ("applications/", "arc/", "policy/", "projects/")


class ImpactError(ValueError):
    """Raised when the comparison cannot be proven."""


def git(repository: Path, *arguments: str, check: bool = True) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=False,
        capture_output=True,
    )
    if check and result.returncode != 0:
        message = result.stderr.decode("utf-8", errors="replace").strip()
        raise ImpactError(message or f"git {' '.join(arguments)} failed")
    return result.stdout


def resolve_commit(repository: Path, revision: str) -> str:
    resolved = git(repository, "rev-parse", "--verify", f"{revision}^{{commit}}")
    value = resolved.decode("ascii").strip()
    if len(value) != 40:
        raise ImpactError(f"revision does not resolve to a full commit: {revision}")
    return value


def require_ancestor(repository: Path, base: str, head: str) -> None:
    result = subprocess.run(
        ["git", "-C", str(repository), "merge-base", "--is-ancestor", base, head],
        check=False,
        capture_output=True,
    )
    if result.returncode == 1:
        raise ImpactError("base commit is not an ancestor of the merge candidate")
    if result.returncode != 0:
        message = result.stderr.decode("utf-8", errors="replace").strip()
        raise ImpactError(message or "cannot prove merge-candidate ancestry")


def changed_paths(repository: Path, base: str, head: str) -> list[str]:
    output = git(repository, "diff", "--name-status", "--find-renames", "-z", base, head)
    tokens = output.split(b"\0")
    paths: set[str] = set()
    index = 0
    while index < len(tokens) and tokens[index]:
        status = tokens[index].decode("ascii", errors="strict")
        index += 1
        if not status or status[0] not in "ACDMRTUXB":
            raise ImpactError(f"unsupported git diff status: {status}")
        if status[0] in {"R", "C"}:
            if index + 1 >= len(tokens):
                raise ImpactError("truncated git rename/copy record")
            paths.add(tokens[index].decode("utf-8", errors="surrogateescape"))
            paths.add(tokens[index + 1].decode("utf-8", errors="surrogateescape"))
            index += 2
        else:
            if index >= len(tokens):
                raise ImpactError("truncated git diff record")
            paths.add(tokens[index].decode("utf-8", errors="surrogateescape"))
            index += 1
    return sorted(paths)


def file_at(repository: Path, revision: str, path: str) -> bytes | None:
    result = subprocess.run(
        ["git", "-C", str(repository), "show", f"{revision}:{path}"],
        check=False,
        capture_output=True,
    )
    if result.returncode == 0:
        return result.stdout
    exists = subprocess.run(
        ["git", "-C", str(repository), "cat-file", "-e", f"{revision}:{path}"],
        check=False,
        capture_output=True,
    )
    if exists.returncode != 0:
        return None
    raise ImpactError(f"cannot read {path} at {revision}")


def yaml_documents(contents: bytes | None, label: str) -> list[Any]:
    if contents is None:
        return []
    try:
        loaded = yaml.safe_load_all(contents.decode("utf-8"))
        return [document for document in loaded if document is not None]
    except (UnicodeDecodeError, yaml.YAMLError) as error:
        raise ImpactError(f"cannot parse changed YAML {label}: {error}") from error


def canonical_items(value: Any) -> set[str]:
    if not isinstance(value, list):
        return set()
    return {
        json.dumps(item, sort_keys=True, separators=(",", ":"))
        for item in value
    }


def object_names(documents: list[Any]) -> tuple[set[str], set[str]]:
    applications: set[str] = set()
    namespaces: set[str] = set()
    for document in documents:
        if not isinstance(document, dict):
            continue
        metadata = document.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else {}
        kind = document.get("kind")
        name = metadata.get("name")
        if kind in {"Application", "ApplicationSet"} and isinstance(name, str):
            applications.add(name)
        namespace = metadata.get("namespace")
        if isinstance(namespace, str) and namespace:
            namespaces.add(namespace)
        if kind == "Namespace" and isinstance(name, str):
            namespaces.add(name)
        spec = document.get("spec")
        spec = spec if isinstance(spec, dict) else {}
        if kind == "ArtifactDeploymentSet":
            for application in spec.get("applications") or []:
                if isinstance(application, dict) and isinstance(application.get("name"), str):
                    applications.add(application["name"])
        destination = spec.get("destination")
        if isinstance(destination, dict) and isinstance(destination.get("namespace"), str):
            namespaces.add(destination["namespace"])
    return applications, namespaces


def image_reference(value: dict[str, Any]) -> str | None:
    if len(value) == 1:
        candidate, marker = next(iter(value.items()))
        if isinstance(candidate, str) and marker is None:
            return candidate
    repository = value.get("repository") or value.get("newName") or value.get("name")
    if not isinstance(repository, str) or not repository:
        return None
    digest = value.get("digest")
    if isinstance(digest, str) and digest:
        return f"{repository}@{digest}"
    tag = value.get("tag") or value.get("newTag")
    if isinstance(tag, str) and tag:
        return f"{repository}:{tag}"
    return repository


def images(documents: list[Any]) -> set[str]:
    discovered: set[str] = set()

    def descend(value: Any) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if key == "image":
                    if isinstance(child, str):
                        discovered.add(child)
                    elif isinstance(child, dict):
                        reference = image_reference(child)
                        if reference:
                            discovered.add(reference)
                if key == "images" and isinstance(child, list):
                    for candidate in child:
                        if isinstance(candidate, str):
                            discovered.add(candidate)
                        elif isinstance(candidate, dict):
                            reference = image_reference(candidate)
                            if reference:
                                discovered.add(reference)
                descend(child)
        elif isinstance(value, list):
            for child in value:
                descend(child)

    for document in documents:
        descend(document)
    return discovered


def enabled_prune_scopes(documents: list[Any]) -> dict[str, str]:
    enabled: dict[str, str] = {}
    for document in documents:
        if not isinstance(document, dict):
            continue
        kind = document.get("kind")
        if kind not in {"Application", "ApplicationSet"}:
            continue
        metadata = document.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else {}
        name = metadata.get("name")
        namespace = metadata.get("namespace", "")
        if not isinstance(name, str) or not isinstance(namespace, str):
            continue
        spec = document.get("spec")
        spec = spec if isinstance(spec, dict) else {}
        if kind == "ApplicationSet":
            template = spec.get("template")
            template = template if isinstance(template, dict) else {}
            spec = template.get("spec")
            spec = spec if isinstance(spec, dict) else {}
        sync_policy = spec.get("syncPolicy")
        sync_policy = sync_policy if isinstance(sync_policy, dict) else {}
        automated = sync_policy.get("automated")
        automated = automated if isinstance(automated, dict) else {}
        if automated.get("prune") is True and automated.get("enabled") is not False:
            scope = {
                "destination": spec.get("destination"),
                "source": spec.get("source"),
                "sources": spec.get("sources"),
            }
            if kind == "ApplicationSet":
                outer_spec = document.get("spec")
                outer_spec = outer_spec if isinstance(outer_spec, dict) else {}
                scope["generators"] = outer_spec.get("generators")
            enabled[f"{kind}/{namespace}/{name}"] = json.dumps(
                scope, sort_keys=True, separators=(",", ":")
            )
    return enabled


def app_project_expansions(
    base_documents: list[Any], head_documents: list[Any]
) -> list[dict[str, Any]]:
    def projects(documents: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for document in documents:
            if not isinstance(document, dict):
                continue
            if document.get("kind") != "AppProject":
                continue
            metadata = document.get("metadata")
            name = metadata.get("name") if isinstance(metadata, dict) else None
            if isinstance(name, str):
                spec = document.get("spec")
                result[name] = spec if isinstance(spec, dict) else {}
        return result

    before = projects(base_documents)
    after = projects(head_documents)
    expansions: list[dict[str, Any]] = []
    for project in sorted(after):
        old = before.get(project, {})
        new = after[project]
        for field in RBAC_ALLOW_FIELDS:
            added = sorted(canonical_items(new.get(field)) - canonical_items(old.get(field)))
            if added:
                expansions.append(
                    {
                        "project": project,
                        "field": field,
                        "direction": "added",
                        "entries": added,
                    }
                )
        for field in RBAC_DENY_FIELDS:
            removed = sorted(canonical_items(old.get(field)) - canonical_items(new.get(field)))
            if removed:
                expansions.append(
                    {
                        "project": project,
                        "field": field,
                        "direction": "removed",
                        "entries": removed,
                    }
                )
        if old.get("permitOnlyProjectScopedClusters") is True and new.get(
            "permitOnlyProjectScopedClusters"
        ) is not True:
            expansions.append(
                {
                    "project": project,
                    "field": "permitOnlyProjectScopedClusters",
                    "direction": "disabled",
                    "entries": ["true -> false"],
                }
            )
    return expansions


def environment_for(path: str) -> set[str]:
    parts = set(Path(path).parts)
    return {
        environment
        for environment in ENVIRONMENTS
        if environment in parts
        or f"{environment}.yaml" in parts
        or f"{environment}.yml" in parts
        or f"{environment}.json" in parts
    }


def analyze(repository: Path, base_revision: str, head_revision: str) -> dict[str, Any]:
    base = resolve_commit(repository, base_revision)
    head = resolve_commit(repository, head_revision)
    require_ancestor(repository, base, head)
    paths = changed_paths(repository, base, head)
    affected_environments: set[str] = set()
    affected_applications: set[str] = set()
    affected_namespaces: set[str] = set()
    image_changes: list[dict[str, Any]] = []
    rbac_expansions: list[dict[str, Any]] = []
    policy_changes: list[dict[str, str]] = []
    prune_changes: list[dict[str, Any]] = []
    opaque_yaml_changes: list[dict[str, str]] = []
    change_types: dict[str, str] = {}

    for path in paths:
        base_contents = file_at(repository, base, path)
        head_contents = file_at(repository, head, path)
        change_type = (
            "added" if base_contents is None else "deleted" if head_contents is None else "modified"
        )
        change_types[path] = change_type
        affected_environments.update(environment_for(path))

        if path.startswith("rendered/"):
            parts = Path(path).parts
            if len(parts) >= 3:
                affected_environments.add(parts[1])
                affected_applications.add(parts[2])

        is_yaml = path.endswith((".yaml", ".yml"))
        parseable = is_yaml and not path.startswith("vendor/")
        base_documents = yaml_documents(base_contents, f"{base}:{path}") if parseable else []
        head_documents = yaml_documents(head_contents, f"{head}:{path}") if parseable else []
        if any(not isinstance(document, dict) for document in (*base_documents, *head_documents)):
            opaque_yaml_changes.append(
                {"path": path, "reason": "top-level sequence or scalar YAML requires manual review"}
            )
        for documents in (base_documents, head_documents):
            applications, namespaces = object_names(documents)
            affected_applications.update(applications)
            affected_namespaces.update(namespaces)

        before_images = images(base_documents)
        after_images = images(head_documents)
        if before_images != after_images:
            image_changes.append(
                {
                    "path": path,
                    "removed": sorted(before_images - after_images),
                    "added": sorted(after_images - before_images),
                }
            )

        for expansion in app_project_expansions(base_documents, head_documents):
            rbac_expansions.append({"path": path, **expansion})

        before_prune = enabled_prune_scopes(base_documents)
        after_prune = enabled_prune_scopes(head_documents)
        newly_enabled = sorted(set(after_prune) - set(before_prune))
        retargeted = [
            {
                "object": identity,
                "before": before_prune[identity],
                "after": after_prune[identity],
            }
            for identity in sorted(set(before_prune) & set(after_prune))
            if before_prune[identity] != after_prune[identity]
        ]
        if newly_enabled or retargeted:
            prune_changes.append(
                {"path": path, "enabled": newly_enabled, "retargeted": retargeted}
            )

        if path.startswith("policy/"):
            policy_changes.append({"path": path, "change": change_type})

    reasons: list[str] = []
    risk = "low"
    if any(path.startswith(CRITICAL_PREFIXES) for path in paths):
        risk = "critical"
        reasons.append("production, bootstrap, or production-root source changes")
    if rbac_expansions:
        risk = "critical"
        reasons.append("AppProject authority expands")
    if prune_changes:
        risk = "critical"
        reasons.append("resource pruning becomes enabled")
    if any(item["change"] == "deleted" for item in policy_changes):
        risk = "critical"
        reasons.append("admission policy source is deleted")
    if risk != "critical" and opaque_yaml_changes:
        risk = "high"
        reasons.append("opaque YAML patch or sequence changes require manual semantic review")
    if risk != "critical" and (
        image_changes or policy_changes or any(path.startswith(CONTROL_PREFIXES) for path in paths)
    ):
        risk = "high"
        reasons.append("runtime image or control-plane desired state changes")
    if risk == "low" and any(path.endswith((".yaml", ".yml", ".json")) for path in paths):
        risk = "medium"
        reasons.append("machine-readable repository state changes")
    if not reasons:
        reasons.append("documentation, test, or tooling-only change")

    return {
        "schemaVersion": 1,
        "baseCommit": base,
        "headCommit": head,
        "risk": {"rating": risk, "reasons": sorted(set(reasons))},
        "rollbackRequired": risk in {"critical", "high"},
        "changedPaths": [
            {"path": path, "change": change_types[path]} for path in paths
        ],
        "affectedEnvironments": sorted(affected_environments),
        "affectedApplications": sorted(affected_applications),
        "affectedNamespaces": sorted(affected_namespaces),
        "imageChanges": image_changes,
        "rbacExpansions": rbac_expansions,
        "policyChanges": policy_changes,
        "pruneChanges": prune_changes,
        "opaqueYamlChanges": opaque_yaml_changes,
    }


def markdown(report: dict[str, Any]) -> str:
    def joined(values: list[str]) -> str:
        return ", ".join(f"`{value}`" for value in values) if values else "None"

    risk = report["risk"]
    lines = [
        "## GitOps desired-state impact",
        "",
        f"**Risk:** `{risk['rating']}` · **Rollback plan required:** "
        + ("yes" if report["rollbackRequired"] else "no"),
        "",
        f"- Environments: {joined(report['affectedEnvironments'])}",
        f"- Applications: {joined(report['affectedApplications'])}",
        f"- Namespaces: {joined(report['affectedNamespaces'])}",
        f"- Changed paths: {len(report['changedPaths'])}",
        f"- Image changes: {len(report['imageChanges'])}",
        f"- RBAC expansions: {len(report['rbacExpansions'])}",
        f"- Policy changes: {len(report['policyChanges'])}",
        f"- Newly enabled prune paths: {len(report['pruneChanges'])}",
        f"- Opaque YAML changes: {len(report['opaqueYamlChanges'])}",
        "",
        "### Risk reasons",
        "",
        *[f"- {reason}" for reason in risk["reasons"]],
        "",
        "The JSON artifact is authoritative and contains exact additions/removals.",
        "This report is source analysis; it does not claim live Argo or cluster state.",
        "",
    ]
    return "\n".join(lines)


def validate_report(contract_root: Path, report: dict[str, Any]) -> None:
    schema_path = contract_root / "contracts/gitops-impact-report.schema.json"
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator.check_schema(schema)
        jsonschema.Draft202012Validator(schema).validate(report)
    except (OSError, json.JSONDecodeError, jsonschema.SchemaError, jsonschema.ValidationError) as error:
        raise ImpactError(f"impact report does not satisfy {schema_path}: {error}") from error


def write(path: Path, contents: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", type=Path, default=Path("."))
    parser.add_argument(
        "--contract-root",
        type=Path,
        help="trusted checkout that owns the report schema (defaults to --repository)",
    )
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--markdown-out", type=Path)
    args = parser.parse_args()
    try:
        repository = args.repository.resolve()
        contract_root = (args.contract_root or repository).resolve()
        report = analyze(repository, args.base_sha, args.head_sha)
        validate_report(contract_root, report)
    except (ImpactError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    json_text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    markdown_text = markdown(report)
    if args.json_out:
        write(args.json_out, json_text)
    else:
        print(json_text, end="")
    if args.markdown_out:
        write(args.markdown_out, markdown_text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
