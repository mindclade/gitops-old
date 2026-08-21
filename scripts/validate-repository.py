#!/usr/bin/env python3
# Copyright © 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

from pathlib import Path
import datetime as dt
import hashlib
import json
import re
import sys
import yaml

root = Path(__file__).resolve().parents[1]
errors = []
control_plane_images: set[str] = set()

# ARC may be rendered and reviewed offline, but it must not be reachable from an Argo root or
# a cloud-backed direct workflow until the coordinated v4 workflow/WIF release is complete.
for deferred_path in (
    ".github/workflows/dr-evidence.yml",
    "applications/ci/arc.yaml",
    "applications/ci/argocd.yaml",
    "bootstrap/argocd-config-ci.yaml",
    "projects/arc-artifact-authority.yaml",
    "roots/ci/kustomization.yaml",
):
    if (root / deferred_path).exists():
        errors.append(f"deferred ARC activation path is present: {deferred_path}")

for workflow in (root / ".github/workflows").glob("*.yml"):
    if re.search(
        r"uses:\s*mindclade/\.github/.+@(?:refs/tags/)?v4(?:\.|\b)",
        workflow.read_text(),
    ):
        errors.append(f"active workflow references unpublished v4 source: {workflow.relative_to(root)}")

for n in ["argocd-install.yaml", "argocd-install-ha.yaml"]:
    p = root / "bootstrap" / n
    sp = root / "bootstrap" / (n + ".sha256")
    if not p.exists() or not sp.exists():
        errors.append(f"missing pinned Argo file: {n}")
        continue
    expected = sp.read_text().split()[0]
    actual = hashlib.sha256(p.read_bytes()).hexdigest()
    if expected != actual:
        errors.append(f"checksum mismatch: {n}")
version = root / "bootstrap/argocd-install.version"
if not version.is_file() or not re.fullmatch(
    r"v[0-9]+\.[0-9]+\.[0-9]+\n?", version.read_text()
):
    errors.append("missing or invalid pinned Argo CD version")
try:
    provenance = json.loads(
        (root / "bootstrap/argocd-install.provenance.json").read_text()
    )
    if provenance.get("schema_version") != 1:
        errors.append("unsupported Argo CD provenance schema")
    if provenance.get("upstream_repository") != "argoproj/argo-cd":
        errors.append("Argo CD provenance names the wrong upstream repository")
    if provenance.get("upstream_ref") != version.read_text().strip():
        errors.append("Argo CD provenance ref disagrees with the pinned version")
    if not re.fullmatch(r"[0-9a-f]{40}", str(provenance.get("upstream_commit", ""))):
        errors.append("Argo CD provenance is missing an immutable upstream commit")
    records = {
        str(record.get("path")): record
        for record in provenance.get("artifacts", [])
        if isinstance(record, dict)
    }
    expected_paths = {
        "bootstrap/argocd-install.yaml",
        "bootstrap/argocd-install-ha.yaml",
    }
    if set(records) != expected_paths:
        errors.append("Argo CD provenance does not cover exactly both vendored profiles")
    for relative in sorted(expected_paths & set(records)):
        data = (root / relative).read_bytes()
        blob = hashlib.sha1(
            f"blob {len(data)}\0".encode() + data, usedforsecurity=False
        ).hexdigest()
        if records[relative].get("git_blob_sha1") != blob:
            errors.append(f"upstream Git blob identity mismatch: {relative}")
        if records[relative].get("sha256") != hashlib.sha256(data).hexdigest():
            errors.append(f"provenance SHA-256 mismatch: {relative}")

    try:
        dt.date.fromisoformat(str(provenance.get("images_resolved_at", "")))
    except ValueError:
        errors.append("Argo CD image provenance has no ISO resolution date")
    image_records = provenance.get("images") or []
    image_sources = [
        str(record.get("source"))
        for record in image_records
        if isinstance(record, dict)
    ]
    if image_sources != sorted(image_sources) or len(image_sources) != len(
        set(image_sources)
    ):
        errors.append("Argo CD image provenance is not unique and source-sorted")
    upstream_images = {
        match.group(1)
        for relative in expected_paths
        for match in re.finditer(
            r"(?m)^\s*image:\s*([^\s#]+)", (root / relative).read_text()
        )
    }
    if set(image_sources) != upstream_images:
        errors.append("Argo CD image provenance does not cover every upstream image tag")

    image_component = yaml.safe_load(
        (
            root / "bootstrap/components/immutable-images/kustomization.yaml"
        ).read_text()
    ) or {}
    component_images = {
        str(image.get("name")): str(image.get("digest"))
        for image in image_component.get("images") or []
        if isinstance(image, dict)
    }
    for record in image_records:
        if not isinstance(record, dict):
            errors.append("Argo CD image provenance contains a non-object record")
            continue
        source = str(record.get("source", ""))
        digest = str(record.get("digest", ""))
        name = source.rsplit(":", 1)[0]
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
            errors.append(f"Argo CD image has an invalid digest: {source}")
        if component_images.get(name) != digest:
            errors.append(f"Argo CD image component disagrees with provenance: {source}")
    if set(component_images) != {
        source.rsplit(":", 1)[0] for source in image_sources
    }:
        errors.append("Argo CD image component contains an unproven image")
    control_plane_images = {
        f"{name}@{digest}" for name, digest in component_images.items()
    }

    baseline_path = root / "bootstrap/components/control-plane-baseline/kustomization.yaml"
    baseline = yaml.safe_load(baseline_path.read_text()) or {}
    if baseline.get("namespace") != "argocd":
        errors.append("Argo CD control-plane baseline omits the explicit argocd namespace")
    expected_containers = {
        "argocd-application-controller",
        "argocd-applicationset-controller",
        "argocd-notifications-controller",
        "argocd-repo-server",
        "argocd-server",
        "config-init",
        "copyutil",
        "dex",
        "haproxy",
        "redis",
        "secret-init",
        "sentinel",
        "split-brain-fix",
    }
    qualified_containers = set()
    for patch_entry in baseline.get("patches") or []:
        patch_document = yaml.safe_load(str((patch_entry or {}).get("patch", ""))) or {}
        pod_spec = ((((patch_document.get("spec") or {}).get("template") or {}).get("spec")) or {})
        for container in (pod_spec.get("containers") or []) + (
            pod_spec.get("initContainers") or []
        ):
            name = str((container or {}).get("name", ""))
            qualified_containers.add(name)
            resources = (container or {}).get("resources") or {}
            for section in ("requests", "limits"):
                values = resources.get(section) or {}
                for resource_name in ("cpu", "memory"):
                    if not str(values.get(resource_name, "")).strip():
                        errors.append(
                            f"Argo CD baseline {name} omits {section}.{resource_name}"
                        )
    if qualified_containers != expected_containers:
        errors.append("Argo CD baseline does not qualify the exact standard/HA container set")

    for profile in [
        "bootstrap/install-profiles/standard/kustomization.yaml",
        "bootstrap/install-profiles/ha/kustomization.yaml",
        "bootstrap/profiles/standard/kustomization.yaml",
        "bootstrap/profiles/ha/kustomization.yaml",
    ]:
        profile_document = yaml.safe_load((root / profile).read_text()) or {}
        if profile_document.get("components") != [
            "../../components/immutable-images",
            "../../components/control-plane-baseline",
        ]:
            errors.append(f"Argo CD profile omits a required shared component: {profile}")
except Exception as e:
    errors.append(f"Argo CD provenance validation failed: {e}")
kubernetes_version = root / ".kubernetes-version"
if not kubernetes_version.is_file() or not re.fullmatch(
    r"1\.[0-9]+\.0\n?", kubernetes_version.read_text()
):
    errors.append("missing or invalid Kubernetes schema version")
if (root / "policy/sigstore").exists():
    errors.append(
        "duplicate Sigstore admission policy remains; Binary Authorization is authoritative"
    )
if list((root / "policy").rglob("*require-attestation*")):
    errors.append(
        "misleading require-attestation policy name remains; Gatekeeper owns structural image policy only"
    )
if (root / "CODEOWNERS").exists() or not (root / ".github/CODEOWNERS").exists():
    errors.append("CODEOWNERS must exist only at .github/CODEOWNERS")
for env in ["development", "staging", "production"]:
    if not (root / f"roots/{env}/kustomization.yaml").exists():
        errors.append(f"missing cluster composition: {env}")
    if not (root / f"applications/{env}/platform.yaml").exists():
        errors.append(f"missing applications: {env}")
    argocd_application = root / f"applications/{env}/argocd.yaml"
    if not argocd_application.exists():
        errors.append(f"missing Argo self-management application: {env}")
    else:
        try:
            application = yaml.safe_load(argocd_application.read_text()) or {}
            source = (application.get("spec") or {}).get("source") or {}
            if (application.get("spec") or {}).get(
                "project"
            ) != "argocd-administration":
                errors.append(f"Argo self-management uses wrong project: {env}")
            if source.get("path") not in {
                "bootstrap/profiles/standard",
                "bootstrap/profiles/ha",
            }:
                errors.append(f"Argo self-management uses unapproved profile: {env}")
        except Exception as e:
            errors.append(f"Argo self-management validation failed for {env}: {e}")
    try:
        config_documents = {
            (document.get("metadata") or {}).get("name"): document
            for document in yaml.safe_load_all(
                (root / f"bootstrap/argocd-config-{env}.yaml").read_text()
            )
            if isinstance(document, dict) and document.get("kind") == "ConfigMap"
        }
        argocd_config = (config_documents.get("argocd-cm") or {}).get("data") or {}
        if argocd_config.get("admin.enabled") != "false":
            errors.append(f"local Argo CD admin is not disabled: {env}")
        if argocd_config.get("users.anonymous.enabled") != "false":
            errors.append(f"anonymous Argo CD access is not disabled: {env}")
        dex = yaml.safe_load(argocd_config.get("dex.config", "")) or {}
        github_connectors = [
            connector
            for connector in dex.get("connectors", [])
            if isinstance(connector, dict) and connector.get("type") == "github"
        ]
        github_orgs = [
            str(org.get("name"))
            for connector in github_connectors
            for org in (connector.get("config") or {}).get("orgs", [])
            if isinstance(org, dict)
        ]
        if github_orgs != ["mindclade"]:
            errors.append(f"GitHub SSO organization is not exactly mindclade: {env}")

        rbac = (config_documents.get("argocd-rbac-cm") or {}).get("data") or {}
        if rbac.get("policy.default") != "role:none":
            errors.append(f"Argo CD default RBAC role is not deny-by-default: {env}")
        group_rules = {
            tuple(field.strip() for field in line.split(","))
            for line in str(rbac.get("policy.csv", "")).splitlines()
            if line.strip().startswith("g,")
        }
        expected_group_rules = {
            ("g", "mindclade:platform", "role:platform-admin"),
            ("g", "mindclade:incident-command", "role:platform-admin"),
            ("g", "mindclade:security", "role:security-readonly"),
        }
        if env != "production":
            expected_group_rules.add(
                ("g", "mindclade:engineering", "role:security-readonly")
            )
        if group_rules != expected_group_rules:
            errors.append(f"Argo CD GitHub group mappings are not canonical: {env}")
    except Exception as e:
        errors.append(f"Argo SSO/RBAC validation failed for {env}: {e}")
# Parse authored YAML; vendored upstream content has dedicated byte/provenance validators.
for p in root.rglob("*.yaml"):
    if (
        p.name.startswith("argocd-install")
        or "rendered" in p.parts
        or "vendor" in p.parts
    ):
        continue
    try:
        list(yaml.safe_load_all(p.read_text()))
    except Exception as e:
        errors.append(f"YAML parse {p.relative_to(root)}: {e}")

# A Constraint without its ConstraintTemplate is accepted by Git but rejected by the
# cluster, leaving the intended control absent. Prove the exact deployment bundle contains
# every active constraint and its matching template.
try:
    deploy_file = root / "policy/deploy/kustomization.yaml"
    deploy = yaml.safe_load(deploy_file.read_text()) or {}
    deployed_paths = set()
    for resource in deploy.get("resources") or []:
        path = (deploy_file.parent / resource).resolve()
        deployed_paths.add(path)
        if not path.is_file():
            errors.append(f"policy deployment references missing resource: {resource}")
    template_kinds = {}
    for path in deployed_paths:
        if not path.is_file():
            continue
        for document in yaml.safe_load_all(path.read_text()):
            if (
                not isinstance(document, dict)
                or document.get("kind") != "ConstraintTemplate"
            ):
                continue
            kind = (
                (((document.get("spec") or {}).get("crd") or {}).get("spec") or {}).get(
                    "names"
                )
                or {}
            ).get("kind")
            if not kind:
                errors.append(
                    f"ConstraintTemplate has no constraint kind: {path.relative_to(root)}"
                )
            elif kind in template_kinds:
                errors.append(f"duplicate deployed ConstraintTemplate kind: {kind}")
            else:
                template_kinds[kind] = path
    for path in (root / "policy/constraints").glob("*.yaml"):
        if path.resolve() not in deployed_paths:
            errors.append(f"constraint is not deployed: {path.relative_to(root)}")
        for document in yaml.safe_load_all(path.read_text()):
            if not isinstance(document, dict):
                continue
            kind = document.get("kind")
            if kind and kind not in template_kinds:
                errors.append(
                    f"constraint {path.relative_to(root)} has no deployed template for {kind}"
                )
except Exception as e:
    errors.append(f"policy deployment validation failed: {e}")

# Every active admission constraint must have behavior evidence that proves both sides of
# the boundary. Merely loading a template cannot distinguish a clean estate from inert Rego.
try:
    constraint_files = {
        path.resolve() for path in (root / "policy/constraints").glob("*.yaml")
    }
    suite_path = root / "policy/tests/suite.yaml"
    suite = yaml.safe_load(suite_path.read_text()) or {}
    tested_constraints = set()
    for test in suite.get("tests") or []:
        if not isinstance(test, dict):
            errors.append("policy behavior suite contains a non-object test")
            continue
        name = str(test.get("name", "<unnamed>"))
        raw_constraint = str(test.get("constraint", ""))
        constraint_path = (suite_path.parent / raw_constraint).resolve()
        if constraint_path in tested_constraints:
            errors.append(f"policy constraint has duplicate behavior suites: {raw_constraint}")
        tested_constraints.add(constraint_path)
        outcomes = {
            str(assertion.get("violations", ""))
            for case in test.get("cases") or []
            if isinstance(case, dict)
            for assertion in case.get("assertions") or []
            if isinstance(assertion, dict)
        }
        if "yes" not in outcomes:
            errors.append(f"policy behavior suite has no denied fixture: {name}")
        if "no" not in outcomes:
            errors.append(f"policy behavior suite has no allowed fixture: {name}")
    for path in sorted(constraint_files - tested_constraints):
        errors.append(
            f"active constraint has no behavior suite: {path.relative_to(root)}"
        )
    for path in sorted(tested_constraints - constraint_files):
        try:
            label = path.relative_to(root)
        except ValueError:
            label = path
        errors.append(f"policy behavior suite references an inactive constraint: {label}")
except Exception as e:
    errors.append(f"policy behavior-suite validation failed: {e}")

# Policy holes are short-lived, exact records rather than prose-based bypasses. Validate the
# complete record locally as well as in CI so a malformed exemption cannot wait until merge
# to reveal that ownership, approval, scope, or expiration evidence is missing.
try:
    exemption_document = yaml.safe_load((root / "policy/exemptions.yaml").read_text()) or {}
    exemptions = (exemption_document.get("spec") or {}).get("exemptions") or []
    if not isinstance(exemptions, list):
        errors.append("policy exemptions must be a list")
        exemptions = []
    today = dt.date.today()
    active_constraint_names = {
        str((document.get("metadata") or {}).get("name"))
        for path in (root / "policy/constraints").glob("*.yaml")
        for document in yaml.safe_load_all(path.read_text())
        if isinstance(document, dict) and (document.get("metadata") or {}).get("name")
    }
    never_exemptible = {"deny-holdout-bucket-mount"}
    seen_exemptions = set()
    exact_name = re.compile(r"[a-z0-9](?:[-a-z0-9.]*[a-z0-9])?")
    for index, exemption in enumerate(exemptions):
        label = f"policy exemption[{index}]"
        if not isinstance(exemption, dict):
            errors.append(f"{label} must be an object")
            continue
        constraint = str(exemption.get("constraint", "")).strip()
        if constraint not in active_constraint_names:
            errors.append(f"{label} names an inactive constraint: {constraint or '<empty>'}")
        if constraint in never_exemptible:
            errors.append(f"{label} attempts to exempt a never-exemptible constraint")
        for field in ["owner", "reason", "risk", "reviewer", "ticket", "removal"]:
            if not str(exemption.get(field, "")).strip():
                errors.append(f"{label} missing {field}")
        if "@mindclade/security" not in str(exemption.get("reviewer", "")):
            errors.append(f"{label} reviewer must identify a @mindclade/security approver")
        ticket = str(exemption.get("ticket", ""))
        if not re.fullmatch(r"https://github\.com/mindclade/gitops/issues/[1-9][0-9]*", ticket):
            errors.append(f"{label} ticket must be a mindclade/gitops issue")
        scope = exemption.get("scope") or {}
        if not isinstance(scope, dict) or set(scope) != {"namespace", "workload"}:
            errors.append(f"{label} scope must contain exactly namespace and workload")
            scope = {}
        for field in ["namespace", "workload"]:
            value = str(scope.get(field, ""))
            if not exact_name.fullmatch(value) or "*" in value:
                errors.append(f"{label} scope.{field} must be one exact Kubernetes name")
        identity = (constraint, str(scope.get("namespace", "")), str(scope.get("workload", "")))
        if identity in seen_exemptions:
            errors.append(f"{label} duplicates an existing constraint/scope exemption")
        seen_exemptions.add(identity)
        try:
            raw_granted = exemption.get("granted", "")
            granted = raw_granted if isinstance(raw_granted, dt.date) else dt.date.fromisoformat(str(raw_granted))
            raw_expires = exemption.get("expires", "")
            expires = raw_expires if isinstance(raw_expires, dt.date) else dt.date.fromisoformat(str(raw_expires))
            if granted > today:
                errors.append(f"{label} grant date is in the future")
            if expires < today:
                errors.append(f"{label} is expired")
            if expires <= granted or expires > granted + dt.timedelta(days=90):
                errors.append(f"{label} expiry must be 1-90 days after its grant date")
        except ValueError:
            errors.append(f"{label} granted and expires must be ISO dates")
except Exception as e:
    errors.append(f"policy exemption validation failed: {e}")

# AppProjects are the authorization boundary. Argo namespace deployment is administrative,
# cluster-scoped kinds are exact, and Dex team claims use the connector's canonical org login.
try:
    active_constraint_kinds = {
        str(document.get("kind"))
        for path in (root / "policy/constraints").glob("*.yaml")
        for document in yaml.safe_load_all(path.read_text())
        if isinstance(document, dict) and document.get("kind")
    }
    projects = {}
    for path in (root / "projects").glob("*.yaml"):
        project = yaml.safe_load(path.read_text()) or {}
        name = str((project.get("metadata") or {}).get("name", ""))
        projects[name] = project
        spec = project.get("spec") or {}
        for destination in spec.get("destinations") or []:
            if (
                destination.get("namespace") == "argocd"
                and name != "argocd-administration"
            ):
                errors.append(f"AppProject {name} has unauthorized argocd destination")
        for resource in spec.get("clusterResourceWhitelist") or []:
            if resource.get("group") == "*" or resource.get("kind") == "*":
                errors.append(f"AppProject {name} has wildcard cluster-scoped authority")
        for role in spec.get("roles") or []:
            for group in role.get("groups") or []:
                if not re.fullmatch(r"mindclade:[a-z0-9][a-z0-9-]*", str(group)):
                    errors.append(
                        f"AppProject {name} has noncanonical GitHub group claim: {group}"
                    )

    default = (projects.get("default") or {}).get("spec") or {}
    deny_all = [{"group": "*", "kind": "*"}]
    if (
        default.get("sourceRepos") != []
        or default.get("destinations") != []
        or default.get("clusterResourceBlacklist") != deny_all
        or default.get("namespaceResourceBlacklist") != deny_all
    ):
        errors.append("default AppProject is not exactly deny-all")

    platform = (projects.get("platform") or {}).get("spec") or {}
    allowed_constraint_kinds = {
        str(resource.get("kind"))
        for resource in platform.get("clusterResourceWhitelist") or []
        if resource.get("group") == "constraints.gatekeeper.sh"
    }
    if allowed_constraint_kinds != active_constraint_kinds:
        errors.append(
            "platform AppProject constraint kinds disagree with deployed Gatekeeper constraints"
        )
except Exception as e:
    errors.append(f"AppProject authorization validation failed: {e}")

# Composition deletion must not silently become workload deletion. Prune is governed by the
# per-environment sync policy; parent-object deletion is a separate, explicit operation.
try:
    root_application = yaml.safe_load((root / "bootstrap/root-app.yaml").read_text()) or {}
    if "resources-finalizer.argocd.argoproj.io" in (
        (root_application.get("metadata") or {}).get("finalizers") or []
    ):
        errors.append("root Application has a cascading resource-deletion finalizer")
    for path in (root / "applications").rglob("*.yaml"):
        application = yaml.safe_load(path.read_text()) or {}
        if application.get("kind") == "ApplicationSet":
            spec = application.get("spec") or {}
            if (spec.get("syncPolicy") or {}).get("preserveResourcesOnDeletion") is not True:
                errors.append(
                    f"ApplicationSet does not preserve resources on deletion: {path.relative_to(root)}"
                )
            finalizers = (
                (((spec.get("template") or {}).get("metadata") or {}).get("finalizers"))
                or []
            )
            if "resources-finalizer.argocd.argoproj.io" in finalizers:
                errors.append(
                    f"ApplicationSet template has a cascading finalizer: {path.relative_to(root)}"
                )

        if path.parts[-2] == "production":
            spec = application.get("spec") or {}
            if application.get("kind") == "ApplicationSet":
                spec = (spec.get("template") or {}).get("spec") or {}
            automated = (spec.get("syncPolicy") or {}).get("automated")
            if isinstance(automated, dict):
                if automated.get("prune") is not False:
                    errors.append(
                        f"production auto-sync does not explicitly disable prune: {path.relative_to(root)}"
                    )
                if automated.get("allowEmpty") is True:
                    errors.append(
                        f"production auto-sync allows empty desired state: {path.relative_to(root)}"
                    )
except Exception as e:
    errors.append(f"Argo deletion-safety validation failed: {e}")

# Pod Security Admission is the baseline control for host namespaces, hostPath, privilege
# escalation, and non-root operation. Every GitOps-owned namespace must enforce the
# restricted profile; audit/warn alone is not a production boundary.
for path in (root / "rendered").rglob("*.yaml"):
    try:
        for document in yaml.safe_load_all(path.read_text()):
            if not isinstance(document, dict) or document.get("kind") != "Namespace":
                continue
            name = (document.get("metadata") or {}).get("name") or "<unnamed>"
            labels = (document.get("metadata") or {}).get("labels") or {}
            for mode in ["enforce", "audit", "warn"]:
                if labels.get(f"pod-security.kubernetes.io/{mode}") != "restricted":
                    errors.append(
                        f"Namespace {name} in {path.relative_to(root)} must set Pod Security {mode}=restricted"
                    )
                if not labels.get(f"pod-security.kubernetes.io/{mode}-version"):
                    errors.append(
                        f"Namespace {name} in {path.relative_to(root)} is missing Pod Security {mode}-version"
                    )
    except Exception as e:
        errors.append(
            f"rendered namespace validation failed for {path.relative_to(root)}: {e}"
        )
text = "\n".join(
    p.read_text(errors="ignore")
    for p in root.rglob("*")
    if p.is_file()
    and ".git" not in p.parts
    and "__pycache__" not in p.parts
    and p.suffix != ".pyc"
    and "vendor" not in p.parts
    and not p.name.startswith("argocd-install")
    and p.name not in {"BLUEPRINT.md", "validate-repository.py"}
)
for stale in [
    "mindclade-org",
    "infrastructure-live/5-workloads/<env>/argocd",
    "https://github.com/mindclade/mindclade\n",
    "repo: mindclade/mindclade\n",
    "require-cosign-signature",
    "applied once, by Terraform",
]:
    if stale in text:
        errors.append(f"stale ownership/reference: {stale}")

# Third-party control-plane exceptions are exact immutable digests with explicit ownership,
# security review, scope, and expiry. Prefix exceptions silently authorize future bytes.
try:
    image_policy = yaml.safe_load((root / "image-policy.yaml").read_text()) or {}
    unsigned = (image_policy.get("spec") or {}).get("unsigned") or []
    if not isinstance(unsigned, list):
        errors.append("image-policy spec.unsigned must be a list")
        unsigned = []
    exception_images = []
    expected_fields = {
        "image",
        "owner",
        "reason",
        "scope",
        "granted",
        "expires",
        "reviewer",
        "approval",
        "change",
        "removal",
    }
    today = dt.date.today()
    for index, exception in enumerate(unsigned):
        label = f"image-policy unsigned[{index}]"
        if not isinstance(exception, dict):
            errors.append(f"{label} must be an object")
            continue
        if set(exception) != expected_fields:
            errors.append(f"{label} must contain exactly the governed exception fields")
        image = str(exception.get("image", ""))
        if not re.fullmatch(r"[^\s]+@sha256:[0-9a-f]{64}", image):
            errors.append(f"{label} must name one exact digest")
        exception_images.append(image)
        for field in [
            "owner",
            "reason",
            "reviewer",
            "approval",
            "change",
            "removal",
        ]:
            if not str(exception.get(field, "")).strip():
                errors.append(f"{label} missing {field}")
        if exception.get("owner") != "@mindclade/platform":
            errors.append(f"{label} owner must be @mindclade/platform")
        if exception.get("reviewer") != "@mindclade/security":
            errors.append(f"{label} reviewer must be @mindclade/security")
        if exception.get("approval") != "required-protected-security-review":
            errors.append(f"{label} must require protected security review")
        if exception.get("change") != "protected-gitops-and-infrastructure-live-pull-requests":
            errors.append(f"{label} must bind both protected control-plane changes")
        scope = exception.get("scope") or {}
        if scope != {
            "component": "argocd-control-plane",
            "environments": ["staging", "production"],
        }:
            errors.append(f"{label} scope must be the staging/production Argo control plane")
        try:
            granted = dt.date.fromisoformat(str(exception.get("granted", "")))
            expires = dt.date.fromisoformat(str(exception.get("expires", "")))
            if expires < today:
                errors.append(f"{label} is expired")
            if expires < granted or (expires - granted).days > 90:
                errors.append(f"{label} lifetime must be between 0 and 90 days")
        except ValueError:
            errors.append(f"{label} granted/expires must be ISO dates")
    if exception_images != sorted(exception_images) or len(exception_images) != len(
        set(exception_images)
    ):
        errors.append("image-policy exceptions must be unique and image-sorted")
    if set(exception_images) != control_plane_images:
        errors.append("image-policy exceptions disagree with Argo CD image provenance")

    gatekeeper = yaml.safe_load(
        (root / "policy/constraints/require-image-policy.yaml").read_text()
    ) or {}
    gatekeeper_exemptions = ((gatekeeper.get("spec") or {}).get("parameters") or {}).get(
        "exemptImages"
    ) or []
    if gatekeeper_exemptions != sorted(gatekeeper_exemptions):
        errors.append("Gatekeeper image exceptions must be image-sorted")
    if any("*" in str(image) for image in gatekeeper_exemptions):
        errors.append("Gatekeeper image exceptions may not contain wildcards")
    if set(map(str, gatekeeper_exemptions)) != control_plane_images:
        errors.append("Gatekeeper exceptions disagree with Argo CD image provenance")
except Exception as e:
    errors.append(f"image-policy validation failed: {e}")

# GitHub and Argo freeze controls must move together. Deny windows block manual sync by default;
# the emergency runbook permits one audited live override without committing a standing bypass.
try:
    production = yaml.safe_load((root / "overlays/production.yaml").read_text()) or {}
    operations = yaml.safe_load(
        (root / "roots/production/sync-windows-patch.yaml").read_text()
    )
    windows = next(
        (
            operation.get("value")
            for operation in operations or []
            if isinstance(operation, dict)
            and operation.get("path") == "/spec/syncWindows"
        ),
        None,
    )
    if not isinstance(windows, list) or len(windows) != 2:
        errors.append("production must define exactly two Argo deny windows")
        windows = []
    for window in windows:
        if (
            not isinstance(window, dict)
            or window.get("kind") != "deny"
            or window.get("applications") != ["*"]
            or window.get("manualSync") is not False
            or window.get("timeZone") != "America/Detroit"
        ):
            errors.append("production Argo deny window is not fail-closed")

    annual_window = next(
        (window for window in windows if window.get("schedule") == "0 0 20 12 *"),
        {},
    )
    if annual_window.get("duration") != "408h":
        errors.append("production annual Argo freeze does not cover December 20-January 5")
    expected_emergency_schedule = (
        "* * * * *" if bool(production.get("deployFreeze")) else "0 0 31 2 *"
    )
    emergency_window = next(
        (
            window
            for window in windows
            if window.get("schedule") == expected_emergency_schedule
        ),
        {},
    )
    if emergency_window.get("duration") != "2h":
        errors.append("production deployFreeze and Argo emergency sync window disagree")

    freeze_windows = yaml.safe_load(
        (root / "overlays/freeze-windows.yaml").read_text()
    ) or {}
    annual_definitions = freeze_windows.get("annual") or []
    if (
        len(annual_definitions) != 1
        or annual_definitions[0].get("start") != "12-20"
        or annual_definitions[0].get("end") != "01-05"
        or len(str(annual_definitions[0].get("reason", "")).strip()) < 12
    ):
        errors.append("GitHub annual freeze does not match the Argo annual deny window")

    override = yaml.safe_load((root / "overlays/freeze-override.yaml").read_text()) or {}
    if override.get("active") is True:
        if int(override.get("pullRequest", 0) or 0) <= 0:
            errors.append("active freeze override has no pull request")
        if not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9._:/-]{2,127}", str(override.get("ticket", ""))
        ):
            errors.append("active freeze override has no valid change reference")
        if override.get("approvedByTeam") not in {
            "platform",
            "security",
            "incident-command",
        }:
            errors.append("active freeze override has no authorized approving team")
        if len(str(override.get("reason", "")).strip()) < 12:
            errors.append("active freeze override reason is not specific")
        if "gitops-production" not in (override.get("scope") or []):
            errors.append("active freeze override does not include gitops-production")
        try:
            expiry = dt.date.fromisoformat(str(override.get("expires", "")))
            if expiry < dt.date.today() or expiry > dt.date.today() + dt.timedelta(days=3):
                errors.append("active freeze override expiry is outside the three-day limit")
        except ValueError:
            errors.append("active freeze override expiry is not an ISO date")
    elif override != {
        "active": False,
        "pullRequest": 0,
        "ticket": "",
        "approvedByTeam": "",
        "reason": "",
        "expires": "1970-01-01",
        "scope": [],
    }:
        errors.append("inactive freeze override is not in its canonical empty form")
except Exception as e:
    errors.append(f"freeze-control validation failed: {e}")

# No cross-environment ApplicationSet matrices remain.
for p in (root / "applications").rglob("*.yaml"):
    env = p.parts[-2]
    t = p.read_text()
    for other in {"development", "staging", "production"} - {env}:
        if f"rendered/{other}/" in t:
            errors.append(f"{p.relative_to(root)} references {other}")
if errors:
    print("\n".join("ERROR: " + e for e in errors), file=sys.stderr)
    sys.exit(1)
print("gitops repository invariants passed")
