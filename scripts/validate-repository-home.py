#!/usr/bin/env python3
# Copyright © 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

"""Validate and render assets for the Mindclade repository-home@2 contract."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

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
READER_SUCCESS_LABELS = (
    "Prerequisite:",
    "**Success means:**",
    "**If it fails:**",
    "**Safety boundary:**",
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

COMMON_DOCUMENT_MARKERS = {
    "CONTRIBUTING.md": "<!-- mindclade-doc: contributing@1 -->",
    "SECURITY.md": "<!-- mindclade-doc: security@1 -->",
    "SUPPORT.md": "<!-- mindclade-doc: support@1 -->",
    "CODE_OF_CONDUCT.md": "<!-- mindclade-doc: code-of-conduct@1 -->",
    "GOVERNANCE.md": "<!-- mindclade-doc: governance@1 -->",
    "CHANGELOG.md": "<!-- mindclade-doc: changelog@1 -->",
    "LEGAL.md": "<!-- mindclade-doc: legal-and-reliance@1 -->",
}
CANONICAL_DOCUMENT_DIGESTS = {
    "LICENSE": "a3fe40dac91dfc0c71eb8dc8ceb1c7b606ab8bc5fe26e09b8e53f6b9f8c8d57f",
    "CODE_OF_CONDUCT.md": "676edfffba55165ce25919f1a2d2a0b336e13a331bb4d5c47c8dcb20ca9872a9",
    "LEGAL.md": "65e8f593ad0927cdc5b6c1daceeae8ed14d0ac73f85ff1fc40db046387f01231",
}
SOURCE_HEADER_PATH = ".github/MINDCLADE_PROPRIETARY_SOURCE_HEADER.txt"
SOURCE_HEADER_DIGEST = "0f2b024dbf454c08d57b663d8ad8e469215984a7007ef66bd37d651e046e0029"
THIRD_PARTY_NOTICE_TOOL_DIGEST = "5c344b342d487242b5ff96dec64cf2f22afe52a3bbf8d1b6b97922cb0151d28f"
SPDX_LICENSE_TOOL_DIGEST = "c6e3077d817d7f9181f35e42a55944c65dc36acb28a2228ff5abbab90633f7bd"

LEGAL_CLAIM_PATTERNS = (
    (
        "unqualified certification or compliance claim",
        re.compile(
            r"\b(?:fully|completely|100%)\s+compliant\b|"
            r"\b(?:SOC\s*2|ISO\s*27001|HIPAA|GDPR|FedRAMP|PCI(?:[ -]DSS)?)\s+"
            r"(?:certified|compliant)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "unqualified guarantee",
        re.compile(
            r"\bguarantee(?:d|s)?\s+(?:availability|uptime|results?|security|safety|"
            r"compliance|response|recovery|performance)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "unqualified response-time promise",
        re.compile(
            r"\b(?:we|Mindclade|support|security)\s+will\s+(?:respond|acknowledge|resolve)\s+"
            r"within\s+\d+\s+(?:minutes?|hours?|business\s+days?|days?)\b",
            re.IGNORECASE,
        ),
    ),
)
LEGAL_CLAIM_ANNOTATION = re.compile(
    r"^\s*<!--\s*mindclade-legal-claim:\s*(.*?)\s*-->\s*$", re.IGNORECASE
)
LEGAL_CLAIM_REQUIRED_FIELDS = {"owner", "evidence", "scope", "reviewed", "expires"}
LEGAL_CLAIM_EXCLUDED_PARTS = {
    ".git",
    ".direnv",
    ".venv",
    "build",
    "dist",
    "node_modules",
    "target",
    "third_party",
    "vendor",
}


def _legal_claim_annotation(
    raw: str, path: Path, line_number: int
) -> tuple[dict[str, str] | None, list[str]]:
    """Parse and validate one legal-claim approval annotation."""
    match = LEGAL_CLAIM_ANNOTATION.fullmatch(raw)
    if not match:
        return None, []
    fields: dict[str, str] = {}
    errors: list[str] = []
    for item in match.group(1).split(";"):
        key, separator, value = item.strip().partition("=")
        if not separator or not key or not value:
            errors.append(f"{path}:{line_number}: malformed legal-claim annotation field")
            continue
        if key in fields:
            errors.append(f"{path}:{line_number}: duplicate legal-claim field: {key}")
        fields[key] = value.strip()
    if set(fields) != LEGAL_CLAIM_REQUIRED_FIELDS:
        errors.append(
            f"{path}:{line_number}: legal-claim fields must be exactly "
            f"{', '.join(sorted(LEGAL_CLAIM_REQUIRED_FIELDS))}"
        )
        return fields, errors
    if not re.fullmatch(r"[a-z0-9][a-z0-9._/-]*", fields["owner"], re.IGNORECASE):
        errors.append(f"{path}:{line_number}: legal-claim owner is malformed")
    if not re.fullmatch(r"(?:https://|[A-Z][A-Z0-9]+-)[^\s]+", fields["evidence"]):
        errors.append(
            f"{path}:{line_number}: legal-claim evidence must be an HTTPS URI or record id"
        )
    if len(fields["scope"]) < 3:
        errors.append(f"{path}:{line_number}: legal-claim scope is too short")
    dates: dict[str, dt.date] = {}
    for name in ("reviewed", "expires"):
        try:
            dates[name] = dt.date.fromisoformat(fields[name])
        except ValueError:
            errors.append(f"{path}:{line_number}: legal-claim {name} must be YYYY-MM-DD")
    if len(dates) == 2:
        if dates["reviewed"] > dates["expires"]:
            errors.append(f"{path}:{line_number}: legal-claim review occurs after expiry")
        if dates["expires"] < dt.date.today():
            errors.append(f"{path}:{line_number}: legal-claim approval is expired")
    return fields, errors


def validate_legal_claims(root: Path) -> list[str]:
    """Reject risky legal/marketing claims without scoped, expiring approval evidence."""
    errors: list[str] = []
    for path in sorted(root.rglob("*.md")):
        relative = path.relative_to(root)
        if LEGAL_CLAIM_EXCLUDED_PARTS.intersection(relative.parts):
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError) as exc:
            errors.append(f"{relative}: cannot lint legal claims: {exc}")
            continue
        in_fence = False
        pending_annotation: tuple[int, bool] | None = None
        for line_number, line in enumerate(lines, start=1):
            if line.lstrip().startswith("```"):
                in_fence = not in_fence
                continue
            if in_fence:
                continue
            annotation, annotation_errors = _legal_claim_annotation(
                line, relative, line_number
            )
            errors.extend(annotation_errors)
            if annotation is not None:
                pending_annotation = (line_number, not annotation_errors)
                continue
            for label, pattern in LEGAL_CLAIM_PATTERNS:
                if not pattern.search(line):
                    continue
                approved = (
                    pending_annotation is not None
                    and pending_annotation[1]
                    and line_number - pending_annotation[0] <= 3
                )
                if not approved:
                    errors.append(
                        f"{relative}:{line_number}: {label}; add a current "
                        "mindclade-legal-claim annotation with owner, evidence, scope, "
                        "reviewed, and expires"
                    )
            if line.strip() and pending_annotation and line_number - pending_annotation[0] > 3:
                pending_annotation = None
    return errors


def validate_third_party_notices(root: Path) -> list[str]:
    """Require deterministic, complete notice generation from reviewed provenance."""
    errors: list[str] = []
    for required in ("contracts/third-party-materials.json", "THIRD_PARTY_NOTICES.md"):
        if not (root / required).is_file():
            errors.append(f"missing required third-party notice artifact: {required}")
    tool = next(
        (
            candidate
            for candidate in (
                root / "scripts" / "generate-third-party-notices.py",
                root / "tools" / "third_party_notices.py",
            )
            if candidate.is_file()
        ),
        None,
    )
    if tool is None:
        errors.append("missing canonical third-party notice validator")
        return errors
    if hashlib.sha256(tool.read_bytes()).hexdigest() != THIRD_PARTY_NOTICE_TOOL_DIGEST:
        errors.append("third-party notice validator differs from the policy bundle")
        return errors
    spdx_tool = next(
        (
            candidate
            for candidate in (
                root / "scripts" / "enrich-spdx-license.py",
                root / "tools" / "enrich_spdx_license.py",
            )
            if candidate.is_file()
        ),
        None,
    )
    if spdx_tool is None:
        errors.append("missing canonical SPDX proprietary-license enricher")
        return errors
    if hashlib.sha256(spdx_tool.read_bytes()).hexdigest() != SPDX_LICENSE_TOOL_DIGEST:
        errors.append("SPDX proprietary-license enricher differs from the policy bundle")
        return errors
    if errors:
        return errors
    result = subprocess.run(
        [sys.executable, str(tool), "--root", str(root)],
        cwd=root,
        check=False,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        errors.append(f"third-party notice validation failed: {detail}")
    return errors


def validate_common_documents(root: Path, repository: str) -> list[str]:
    """Validate the versioned common-document@1 policy and legal surface."""
    errors: list[str] = []
    required = {
        "README.md",
        "AGENTS.md",
        "LICENSE",
        "NOTICE",
        *COMMON_DOCUMENT_MARKERS,
    }
    texts: dict[str, str] = {}

    duplicate_license_surfaces = sorted(
        path.name
        for path in root.iterdir()
        if path.is_file() and path.name.lower().startswith("license") and path.name != "LICENSE"
    )
    if duplicate_license_surfaces:
        errors.append(
            "duplicate root license surface(s); LICENSE must be the sole root license: "
            + ", ".join(duplicate_license_surfaces)
        )

    source_header = root / SOURCE_HEADER_PATH
    if source_header.is_file():
        payload = source_header.read_bytes()
        if hashlib.sha256(payload).hexdigest() != SOURCE_HEADER_DIGEST:
            errors.append(f"{SOURCE_HEADER_PATH} differs from the canonical source-header template")
        header_text = payload.decode("utf-8", errors="replace")
        for value in (
            "SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary",
            "Source-file header template; this file is not a standalone license.",
            "The sole repository license is the complete root LICENSE.",
        ):
            if value not in header_text:
                errors.append(f"{SOURCE_HEADER_PATH} lacks required identity: {value}")

    for name in sorted(required):
        path = root / name
        if not path.is_file():
            errors.append(f"missing required common document: {name}")
            continue
        payload = path.read_bytes()
        if not payload:
            errors.append(f"required common document is empty: {name}")
            continue
        if not payload.endswith(b"\n"):
            errors.append(f"required common document lacks final newline: {name}")
        try:
            texts[name] = payload.decode("utf-8")
        except UnicodeDecodeError:
            errors.append(f"required common document is not UTF-8: {name}")

    pull_request_path = next(
        (
            candidate
            for candidate in (
                root / ".github" / "PULL_REQUEST_TEMPLATE.md",
                root / ".github" / "pull_request_template.md",
            )
            if candidate.is_file()
        ),
        None,
    )
    if pull_request_path is None:
        errors.append("missing required common document: .github/PULL_REQUEST_TEMPLATE.md")
    else:
        payload = pull_request_path.read_bytes()
        if not payload:
            errors.append("required pull-request template is empty")
        else:
            if not payload.endswith(b"\n"):
                errors.append("required pull-request template lacks final newline")
            try:
                texts[".github/PULL_REQUEST_TEMPLATE.md"] = payload.decode("utf-8")
            except UnicodeDecodeError:
                errors.append("required pull-request template is not UTF-8")

    for name, marker in COMMON_DOCUMENT_MARKERS.items():
        text = texts.get(name, "")
        if text.count(marker) != 1:
            errors.append(f"{name} must contain exactly one {marker}")
        heading_text = re.sub(r"\x60\x60\x60.*?\x60\x60\x60", "", text, flags=re.S)
        if text and len(re.findall(r"^# ", heading_text, flags=re.M)) != 1:
            errors.append(f"{name} must contain exactly one level-one heading")

    for name, expected in CANONICAL_DOCUMENT_DIGESTS.items():
        path = root / name
        if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            errors.append(f"{name} differs from the canonical common-document@1 text")

    license_text = texts.get("LICENSE", "")
    for value in (
        "Document-Control: mindclade-license@2",
        "Effective date: August 21, 2026",
        "Copyright © 2026 Mindclade, LLC. All Rights Reserved.",
        "SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary",
        "controlling written agreement",
        "Third-party components",
        "Protected disclosures",
        "18 U.S.C. § 1833(b)",
    ):
        if value not in license_text:
            errors.append(f"LICENSE lacks required legal term: {value}")

    notice = re.sub(r"\s+", " ", texts.get("NOTICE", ""))
    expected_repository = f"Repository: mindclade/{repository}"
    for value in (
        "Document-Control: mindclade-notice@1",
        expected_repository,
        "SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary",
        "third-party",
        "terms control",
        "Contributor Covenant version 2.1",
        "Creative Commons Attribution 4.0",
    ):
        if value.lower() not in notice.lower():
            errors.append(f"NOTICE lacks required disclosure: {value}")

    contributing = re.sub(r"\s+", " ", texts.get("CONTRIBUTING.md", ""))
    for value in (
        "current written",
        "right and authority",
        "third-party",
        "By submitting or updating a pull request",
        "Signed commits",
        "not a substitute",
    ):
        if value not in contributing:
            errors.append(f"CONTRIBUTING.md lacks required authorization term: {value}")

    security = texts.get("SECURITY.md", "")
    for value in (
        "security@mindclade.com",
        "biosecurity@mindclade.com",
        "Do not open",
        "operational targets",
        "not contractual",
        "third-party systems",
        "unlawful conduct",
    ):
        if value.lower() not in security.lower():
            errors.append(f"SECURITY.md lacks required private-reporting term: {value}")
    if re.search(r"PGP key in the canonical policy|publishes? a public PGP key", security, re.I):
        errors.append("SECURITY.md incorrectly claims that Mindclade publishes a PGP key")

    legal = re.sub(r"\s+", " ", texts.get("LEGAL.md", ""))
    for value in (
        "does not by itself create a contract",
        "controlling written agreement",
        "not legal, medical, clinical, financial, or regulatory advice",
        "customer security schedule",
        "third-party systems or data",
        "protected disclosure",
        "qualified counsel",
    ):
        if value.lower() not in legal.lower():
            errors.append(f"LEGAL.md lacks required reliance boundary: {value}")

    support = texts.get("SUPPORT.md", "")
    for value in ("SECURITY.md", "SLA", "customer", "Do not"):
        if value.lower() not in support.lower():
            errors.append(f"SUPPORT.md lacks required routing term: {value}")

    pull_request = re.sub(
        r"\s+", " ", texts.get(".github/PULL_REQUEST_TEMPLATE.md", "")
    )
    for value in (
        "current written agreement with Mindclade, LLC.",
        "third-party",
        "LICENSE",
        "NOTICE",
    ):
        if value not in pull_request:
            errors.append(
                f".github/PULL_REQUEST_TEMPLATE.md lacks required contributor term: {value}"
            )

    return errors


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


def has_remote_shields_reference(markdown: str) -> bool:
    """Return whether Markdown contains a URL hosted by the Shields service."""
    urls = re.findall(r"https?://[^\s<>\"')]+", markdown, flags=re.I)
    for url in urls:
        try:
            if urlsplit(url).hostname == "img.shields.io":
                return True
        except ValueError:
            continue
    return False


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


def validate_local_validator(source: Path, root: Path, requested_path: str) -> list[str]:
    """Require an optional offline mirror to match this released validator exactly."""
    if not requested_path:
        return []

    relative = Path(requested_path)
    if relative.is_absolute():
        return ["local validator path must be relative to the workspace"]

    workspace = root.resolve()
    candidate = (workspace / relative).resolve()
    try:
        candidate.relative_to(workspace)
    except ValueError:
        return [f"local validator path escapes the workspace: {requested_path}"]

    if not candidate.is_file():
        return [f"local validator mirror does not exist: {requested_path}"]
    if candidate.read_bytes() != source.resolve().read_bytes():
        return [
            f"local validator mirror differs from the released action: {requested_path}"
        ]
    return []


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
    if "Brand distribution: mindclade/.github-private/mindclade-brand-assets (MONO family)." not in markdown:
        errors.append("README.md must identify the checked-in MONO brand distribution")
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
    if not rows.get("Primary readers", "").strip():
        errors.append("contract table must identify the primary readers")
    if not re.fullmatch(r"\[[^\]]+\]\(#quick-start\)", rows.get("First success", "")):
        errors.append("contract table First success must link to #quick-start")
    for label in READER_SUCCESS_LABELS:
        if markdown.count(label) != 1:
            errors.append(f"README.md must contain exactly one reader-success label: {label}")
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

    errors.extend(validate_common_documents(root, repository))
    errors.extend(validate_legal_claims(root))
    errors.extend(validate_third_party_notices(root))

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
    if has_remote_shields_reference(markdown):
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
    parser.add_argument("--local-validator-path", default="")
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
    errors.extend(
        validate_local_validator(Path(__file__), root, args.local_validator_path)
    )
    if errors:
        print("repository-home validation failed:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1
    print(f"repository-home validation passed: {root.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
