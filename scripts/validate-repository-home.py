#!/usr/bin/env python3
# Copyright © 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary
"""Validate and render assets for the Mindclade repository-home@2 contract."""

from __future__ import annotations

import argparse
import html
import re
import sys
from pathlib import Path

MARKER = "<!-- mindclade-doc: repository-home@2 -->"
THEME_DIRECTIVE = '%%{init: {"theme":"base"'
REQUIRED_HEADINGS = (
    "## Mission",
    "## Authority boundary",
    "### This repository creates",
    "### This repository deliberately does not create",
    "## Quick start",
    "## Estate position",
    "## Repository map",
    "## Change path",
    "## Documentation and support",
    "## Security",
)
EXTRA_BADGES = {
    "bootstrap": (("trust", "Ring 0"),),
    "infrastructure-live": (("stack", "Terraform + Terragrunt"),),
    "github-config": (("policy", "catalog-driven"),),
    "gitops": (("delivery", "Argo CD"),),
    "mindclade-internal-monorepo": (("build", "Bazel + Nix"), ("maturity", "mixed")),
    ".github": (("surface", "shared workflows"),),
    ".github-private": (("surface", "brand + profile"),),
}
CORE_BADGES = (
    ("repository-class", "class", "repository_class"),
    ("visibility", "visibility", "visibility"),
    ("change-model", "change", "change_model"),
)
VERSION_SOURCES = {
    "Terraform": (".terraform-version", re.compile(r"Terraform\s+v?(\d+\.\d+(?:\.\d+)?)", re.I)),
    "Go": ("go.mod", re.compile(r"\bGo\s+v?(\d+\.\d+(?:\.\d+)?)", re.I)),
    "Kubernetes": (".kubernetes-version", re.compile(r"Kubernetes\s+v?(\d+\.\d+(?:\.\d+)?)", re.I)),
}
PALETTE = {"#201C24", "#B5673F", "#D68A61", "#FBFAF7", "#F2EFE8", "#423D48", "#5B5660", "#E2DED4"}


def parse_contract(path: Path) -> dict[str, object]:
    """Parse the small top-level subset used by repository contracts without PyYAML."""
    result: dict[str, object] = {}
    active_list: str | None = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line or line == "---":
            continue
        if not line.startswith((" ", "\t")):
            match = re.fullmatch(r"([a-z_]+):(?:\s*(.*))?", line)
            if not match:
                active_list = None
                continue
            key, value = match.groups()
            if value:
                result[key] = value.strip().strip('"\'')
                active_list = None
            else:
                result[key] = []
                active_list = key
            continue
        if active_list and re.match(r"^\s+-\s+", raw):
            value = re.sub(r"^\s+-\s+", "", line).strip().strip('"\'')
            values = result[active_list]
            if isinstance(values, list):
                values.append(value)
        elif raw and len(raw) - len(raw.lstrip()) <= 2:
            active_list = None
    return result


def contract_table(markdown: str) -> dict[str, str]:
    rows: dict[str, str] = {}
    for line in markdown.splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) == 2 and cells[0] not in {"---", "Repository contract"}:
            rows[cells[0]] = cells[1]
    return rows


def markdown_slug(heading: str) -> str:
    value = re.sub(r"<[^>]+>", "", heading.strip().lower())
    value = re.sub(r"[^\w\- ]", "", value)
    return re.sub(r"\s+", "-", value)


def local_links(markdown: str) -> list[str]:
    return re.findall(r"(?<!!)\[[^\]]+\]\(([^)]+)\)", markdown)


def image_sources(markdown: str) -> list[str]:
    values = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", markdown)
    values.extend(re.findall(r"\b(?:src|srcset)=[\"']([^\"']+)[\"']", markdown))
    return values


def prose_word_count(markdown: str) -> int:
    text = re.sub(r"```.*?```", " ", markdown, flags=re.S)
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("|"))
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    return len(re.findall(r"\b[\w][\w'\-]*\b", text))


def badge_svg(label: str, value: str) -> str:
    left = max(58, 18 + len(label) * 7)
    right = max(54, 18 + len(value) * 7)
    total = left + right
    title = html.escape(f"{label}: {value}")
    label_text = html.escape(label)
    value_text = html.escape(value)
    return f'''<svg xmlns="http://www.w3.org/2000/svg" role="img" aria-label="{title}" width="{total}" height="24" viewBox="0 0 {total} 24">
  <title>{title}</title>
  <defs><clipPath id="badge-shape"><rect width="{total}" height="24" rx="4"/></clipPath></defs>
  <g clip-path="url(#badge-shape)">
    <rect width="{total}" height="24" fill="#201C24"/>
    <path d="M{left} 0h{right}v24H{left}z" fill="#B5673F"/>
  </g>
  <g fill="#F2EFE8" font-family="Verdana,DejaVu Sans,sans-serif" font-size="11" text-anchor="middle">
    <text x="{left / 2:g}" y="16">{label_text}</text>
    <text x="{left + right / 2:g}" y="16" font-weight="700">{value_text}</text>
  </g>
</svg>
'''


def write_badges(root: Path, contract: dict[str, object]) -> None:
    repository = str(contract.get("repository", root.name))
    target = root / "docs" / "assets" / "badges"
    target.mkdir(parents=True, exist_ok=True)
    for filename, label, key in CORE_BADGES:
        (target / f"{filename}.svg").write_text(
            badge_svg(label, str(contract.get(key, "unknown"))), encoding="utf-8"
        )
    for label, value in EXTRA_BADGES.get(repository, ()):
        (target / f"{label}.svg").write_text(badge_svg(label, value), encoding="utf-8")


def validate(root: Path) -> list[str]:
    errors: list[str] = []
    readme_path = root / "README.md"
    contract_path = root / "contracts" / "repository.yaml"
    if not readme_path.is_file():
        return ["missing README.md"]
    if not contract_path.is_file():
        return ["missing contracts/repository.yaml"]

    markdown = readme_path.read_text(encoding="utf-8")
    contract = parse_contract(contract_path)
    repository = str(contract.get("repository", root.name))

    if markdown.count(MARKER) != 1 or not markdown.startswith(MARKER):
        errors.append(f"README.md must begin with exactly one {MARKER}")
    if "Brand source: mindclade/.github-private/mindclade-brand-assets (MONO family)." not in markdown:
        errors.append("README.md must identify the canonical MONO brand source")
    if len(re.findall(r"^# ", markdown, flags=re.M)) != 1:
        errors.append("README.md must contain exactly one level-one heading")
    if not re.search(r"^# Mindclade · ", markdown, flags=re.M):
        errors.append("README.md title must use 'Mindclade · <Repository>'")
    for heading in REQUIRED_HEADINGS:
        if heading not in markdown:
            errors.append(f"README.md is missing required heading: {heading}")

    expected_brand = (
        "mindclade-brand-assets/png/mono-wordmark-1080w.png"
        if repository == ".github-private"
        else "docs/assets/brand/mono-wordmark-1080w.png"
    )
    expected_dark = expected_brand.replace("mono-wordmark-", "mono-wordmark-dark-")
    for value in (expected_brand, expected_dark, 'alt="Mindclade."', 'width="360"'):
        if value not in markdown:
            errors.append(f"README.md header is missing {value}")
    if "<picture>" not in markdown or "prefers-color-scheme: dark" not in markdown:
        errors.append("README.md must use the responsive light/dark <picture> header")

    rows = contract_table(markdown)
    expected_rows = {
        "Class": str(contract.get("repository_class", "")),
        "Visibility": str(contract.get("visibility", "")),
        "Change model": str(contract.get("change_model", "")),
    }
    for label, expected in expected_rows.items():
        actual = rows.get(label, "").replace("`", "").strip()
        if actual != expected:
            errors.append(f"contract table {label!r} is {actual!r}; expected {expected!r}")
    table_authority = re.findall(r"`([^`]+)`", rows.get("Authority", ""))
    expected_authority = contract.get("authority", [])
    if table_authority != expected_authority:
        errors.append(
            f"contract table authority {table_authority!r} does not match {expected_authority!r}"
        )

    required_paths = contract.get("required_paths", [])
    if isinstance(required_paths, list):
        for required in required_paths:
            if not (root / str(required)).exists():
                errors.append(f"repository contract required path does not exist: {required}")

    badge_dir = root / "docs" / "assets" / "badges"
    for filename, label, key in CORE_BADGES:
        relative = f"docs/assets/badges/{filename}.svg"
        path = root / relative
        if relative not in markdown:
            errors.append(f"README.md does not reference required local badge: {relative}")
            continue
        if not path.is_file():
            errors.append(f"missing required local badge: {relative}")
            continue
        svg = path.read_text(encoding="utf-8")
        expected_title = f"{label}: {contract.get(key, 'unknown')}"
        if expected_title not in html.unescape(svg):
            errors.append(f"badge {relative} does not match repository contract")
        colors = set(re.findall(r"#[0-9A-Fa-f]{6}", svg))
        if not colors or not colors.issubset(PALETTE):
            errors.append(f"badge {relative} uses colors outside the Mindclade palette")
    if len(re.findall(r"docs/assets/badges/[^\"')\s]+\.svg", markdown)) < 4:
        errors.append("README.md must display at least four local SVG badges")

    for source in image_sources(markdown):
        source = source.strip().split()[0]
        if re.match(r"https?://", source):
            errors.append(f"remote README image is not allowed: {source}")
            continue
        destination = source.split("#", 1)[0]
        if destination and not (root / destination).is_file():
            errors.append(f"broken local README image: {destination}")
    if "img.shields.io" in markdown:
        errors.append("remote Shields badges are not allowed")
    if re.search(r"\.gif(?:[\"')\s]|$)", markdown, flags=re.I):
        errors.append("animated GIFs are not allowed in root READMEs")

    headings_by_file: dict[Path, set[str]] = {}
    for destination in local_links(markdown):
        destination = destination.strip().strip("<>")
        if not destination or re.match(r"(?:https?://|mailto:)", destination):
            continue
        file_part, _, anchor = destination.partition("#")
        target = (root / file_part).resolve() if file_part else readme_path.resolve()
        try:
            target.relative_to(root.resolve())
        except ValueError:
            errors.append(f"README.md link escapes repository: {destination}")
            continue
        if not target.exists():
            errors.append(f"broken local README link: {destination}")
            continue
        if anchor and target.is_file() and target.suffix.lower() == ".md":
            if target not in headings_by_file:
                headings_by_file[target] = {
                    markdown_slug(match.group(1))
                    for match in re.finditer(r"^#{1,6}\s+(.+)$", target.read_text(encoding="utf-8"), re.M)
                }
            if anchor not in headings_by_file[target]:
                errors.append(f"broken local README anchor: {destination}")

    mermaid = re.findall(r"```mermaid\n(.*?)```", markdown, flags=re.S)
    if len(mermaid) != 1:
        errors.append("README.md must contain exactly one Mermaid diagram")
    else:
        diagram = mermaid[0]
        if THEME_DIRECTIVE not in diagram:
            errors.append("Mermaid diagram is missing the shared base-theme directive")
        if "flowchart LR" not in diagram:
            errors.append("Mermaid estate diagram must use flowchart LR")
        if f"%% current: {repository} %%" not in diagram:
            errors.append("Mermaid estate diagram does not identify the highlighted repository")

    count = prose_word_count(markdown)
    if count > 850:
        errors.append(f"README.md contains {count} prose words; maximum is 850")

    for label, (relative, pattern) in VERSION_SOURCES.items():
        source = root / relative
        for match in pattern.finditer(markdown):
            stated = match.group(1)
            if not source.exists():
                errors.append(f"README.md states {label} {stated} but {relative} is absent")
                continue
            source_text = source.read_text(encoding="utf-8")
            if label == "Go":
                pinned_match = re.search(r"^go\s+(\d+\.\d+(?:\.\d+)?)", source_text, re.M)
                pinned = pinned_match.group(1) if pinned_match else ""
            else:
                pinned = source_text.strip().lstrip("v")
            if stated != pinned:
                errors.append(f"README.md states {label} {stated}; {relative} pins {pinned}")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--write-badges", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    contract_path = root / "contracts" / "repository.yaml"
    if args.write_badges:
        if not contract_path.is_file():
            print("missing contracts/repository.yaml", file=sys.stderr)
            return 1
        write_badges(root, parse_contract(contract_path))
    errors = validate(root)
    if errors:
        print("repository-home validation failed:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1
    print(f"repository-home validation passed: {root.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
