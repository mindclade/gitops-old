# Mindclade Enterprise Platform Foundation Blueprint

**Company:** Mindclade  
**Scope:** GitHub Enterprise, Google Cloud foundation, Terraform/Terragrunt live infrastructure, Argo CD GitOps, and artifact promotion  
**Repositories:** `.github`, `github-config`, `bootstrap`, `infrastructure-live`, `gitops`, `mindclade-internal-monorepo`  
**Status:** Final — production architecture decision  
**Date:** 2026-08-19  
**Supersedes:** Earlier standalone draft blueprints for `github-config`, `bootstrap`, `infrastructure-live`, and `gitops`

---

## 1. Executive Decision

Mindclade will operate six repositories with non-overlapping authority:

| Repository | Final authority |
|---|---|
| `.github` | Shared GitHub workflows, templates, organization profile, and organization-wide contributor experience |
| `github-config` | GitHub Enterprise organization, repository, team, ruleset, Actions, environment, and access governance |
| `bootstrap` | Ring 0 Google Cloud state, initial automation trust, seed projects, and break-glass recovery |
| `infrastructure-live` | Normal Google Cloud organization, environment, network, project, cluster, storage, database, and security infrastructure |
| `gitops` | In-cluster Kubernetes desired state, Argo CD orchestration, workload policy, and environment promotion |
| `mindclade-internal-monorepo` | Product, model, training, data, serving, platform source, build logic, deployable packages, and release artifacts |

The operating invariant is:

> **The monorepo produces immutable artifacts. Bootstrap establishes durable trust. Infrastructure-live produces cloud infrastructure. GitOps declares what runs. Argo CD reconciles it. GitHub-config governs who and what may change the system. The `.github` repository provides shared workflow implementations without becoming a second policy source.**

This is a production target, not a requirement to deploy every scale feature immediately. The architecture defines the stable boundaries now so Mindclade can grow without later repository ownership surgery.

---

## 2. Review Scope and Confidence

This review is based on:

- the supplied directory inventory for `gitops`;
- the supplied directory inventory for `github-config`;
- the supplied directory inventories for `bootstrap` and `infrastructure-live`;
- the four draft blueprints produced from those inventories;
- Mindclade's established use of GitHub Enterprise, Google Cloud, Terraform, Terragrunt, GKE, Argo CD, GitHub Actions, Buildkite, and a Bazel monorepo.

The inventories demonstrate strong foundations, but they do not expose the full contents of every Terraform module, workflow, Argo CD object, policy template, or script. Therefore:

- this document finalizes architecture, ownership, repository shape, control flow, and production acceptance criteria;
- it does not claim that every current implementation already satisfies those criteria;
- cryptographic verification, IAM least privilege, Terraform behavior, policy semantics, and destructive-change behavior still require code-level validation before production.

---

## 3. Final Review Disposition

### 3.1 Retain

The following existing decisions are strong and should be retained:

- `github-config` uses a declarative catalog for repositories, teams, access, environments, and CI variables.
- `github-config` has explicit Terraform modules for repositories, teams, policies, and rulesets.
- `bootstrap` has dedicated modules for state, identity, seed projects, and recovery documentation.
- `infrastructure-live` uses a staged `1-org` through `5-workloads` layout.
- `infrastructure-live` separates development, staging, and production.
- `infrastructure-live` models GPU node pools, protected storage, Binary Authorization, VPC Service Controls, backup/DR, and GKE.
- `gitops` separates Argo CD projects and applications into platform, data, research, serving, and partner domains.
- `gitops` already includes environment overlays, render verification, promotion/freeze workflows, policy constraints, policy fixtures, and artifact-verification intent.
- all four control repositories use pinned development environments, pre-commit, Renovate, CI, security documentation, and proprietary headers.

### 3.2 Modify

The following changes are required:

1. **Shrink `bootstrap`.** Move normal folders, organization policies, billing governance, Essential Contacts, SCC configuration, and normal log sinks to `infrastructure-live`.
2. **Give Argo CD one owner.** Terraform owns cloud prerequisites only. `gitops` owns installation manifests, Argo CD configuration, projects, applications, and upgrades.
3. **Separate `.github` from `github-config`.** `.github` owns reusable workflow implementations; `github-config` owns rulesets that require those workflows.
4. **Use current GitHub terminology.** Use ruleset workflows for mandatory checks. Treat workflow execution protections as an optional control until Mindclade accepts its current maturity.
5. **Standardize one CODEOWNERS location.** Use `.github/CODEOWNERS` in every repository.
6. **Normalize project layout.** Remove ambiguous top-level `4-projects/{research,serving,data,...}` duplicates unless they are explicitly shared. Use `shared/`, environment folders, and `partners/`.
7. **Replace `argocd/` in infrastructure-live with `argocd-prereqs/`.**
8. **Complete staging and production workload layers.** Development cannot remain the only fully modeled environment.
9. **Enable modern Terragrunt behavior.** Use `terragrunt run --all`, dependency-aware run queues, and strict mode in CI.
10. **Clarify state protection.** Use GCS state locking, soft delete, object versioning, lifecycle controls, and strict IAM. Do not lock a bucket retention policy in a way that prevents normal state replacement.
11. **Use one image trust chain.** Build/qualification creates attestations; Binary Authorization enforces them; GitOps references the verified digest. Do not deploy multiple overlapping signature controllers without a defined reason.
12. **Make production cluster topology AI-aware.** Preserve a low-cost startup path, but establish separate production serving and compute trust domains as the target.

### 3.3 Remove or prohibit

- committed `.terraform/` directories;
- committed `.terragrunt-cache/` directories;
- committed Terraform plans or state;
- plaintext Kubernetes secrets;
- service-account JSON keys;
- direct monorepo CI access to production clusters;
- direct pushes to protected branches;
- manually edited rendered manifests;
- mutable production image tags;
- duplicate management of a resource by multiple repositories;
- permanent policy exemptions;
- organization-wide basic roles such as Owner for automation;
- daily use of break-glass identities.

---

## 4. Trust Rings and Dependency Order

### Ring 0 — Bootstrap and recovery

Owned by `bootstrap`.

Provides:

- Terraform remote state;
- initial GitHub/Buildkite-to-Google Cloud federation;
- seed and CI trust projects;
- bootstrap service accounts;
- break-glass recovery.

### Ring 1 — Governance and cloud foundation

Owned by `github-config` and `infrastructure-live`.

Provides:

- GitHub governance and access;
- Google Cloud resource hierarchy;
- organization security controls;
- networking;
- environment and workload projects;
- cloud services and clusters.

### Ring 2 — Kubernetes control plane

Owned by `gitops`.

Provides:

- Argo CD;
- AppProjects;
- namespaces;
- policy controllers;
- platform operators;
- workload deployments;
- drift reconciliation.

### Ring 3 — Mindclade products and AI workloads

Built by `mindclade-internal-monorepo` and deployed through `gitops`.

Provides:

- model training;
- model serving;
- data ingestion;
- evaluation;
- product APIs;
- internal applications.

### Dependency graph

```text
GitHub Enterprise / Cloud Identity / billing account
                         |
                         v
                     bootstrap
             +-----------+-----------+
             |                       |
             v                       v
       github-config          infrastructure-live
                                     |
                                     v
                                GCP + GKE
                                     |
mindclade-internal-monorepo           |
             |                        |
             | immutable artifacts    |
             +------------+-----------+
                          v
                        gitops
                          |
                          v
                       Argo CD
                          |
                          v
                 Mindclade workloads
```

No dependency may point backward across these rings during normal operation.

---

## 5. Repository Visibility Policy

GitHub internal repositories are readable by all enterprise members. Mindclade must choose visibility deliberately.

| Repository | Final default |
|---|---|
| `.github` | Internal |
| `github-config` | Private |
| `bootstrap` | Private |
| `infrastructure-live` | Private |
| `gitops` | Internal, per Mindclade's stated intent |
| `mindclade-internal-monorepo` | Internal |

### Conditions on internal visibility

`gitops` and the monorepo may remain internal only while every enterprise member is authorized to read:

- environment topology;
- deployment names;
- project/cluster identifiers;
- non-secret endpoints;
- policy definitions;
- internal source code.

If partner users, acquired-company users, contractors, or other restricted populations become enterprise members, change sensitive repositories to private or separate them into a different organization. Partner isolation cannot rely only on teams inside an internal repository.

No repository visibility change to public may be an ordinary Terraform edit. Public release requires an explicit security, intellectual-property, secret-history, licensing, and product review.

---

## 6. Repository Classifications

`github-config` will assign every repository a custom property `mindclade.repository_class`.

| Class | Repositories | Policy |
|---|---|---|
| `enterprise-control` | `.github`, `github-config`, `bootstrap` | Strongest governance and smallest bypass surface |
| `production-control` | `infrastructure-live`, `gitops` | Protected deployment paths and elevated review |
| `source-monorepo` | `mindclade-internal-monorepo` | Merge queue, affected CI, release controls |
| `public-sdk` | Future public SDK repositories | Public contribution and release controls |
| `archive` | Retired repositories | Read-only, no deployment authority |

Recommended custom properties:

```text
mindclade.owner_team
mindclade.repository_class
mindclade.criticality
mindclade.data_classification
mindclade.production_authority
mindclade.ci_profile
mindclade.lifecycle
```

Rulesets should target custom properties rather than depend only on repository names.

---

## 7. Global Engineering Invariants

### 7.1 One source of truth per resource

Every managed object has exactly one authoritative repository and one state owner.

### 7.2 Build once, promote the same artifact

Development, staging, and production use the same immutable digest. Environment-specific rebuilds are prohibited.

### 7.3 Keyless automation

GitHub Actions and Buildkite authenticate to Google Cloud with short-lived OIDC federation. GKE workloads use Workload Identity Federation for GKE. Static service-account keys are prohibited.

### 7.4 Git-mediated production change

Normal production changes require a protected Git commit. CI, operators, and Argo CD do not bypass the authoritative repository.

### 7.5 Least privilege and separation of duties

Plan, apply, build, qualification, signing, promotion, and runtime identities are distinct capabilities.

### 7.6 Secrets remain outside Git

Git stores references, not credentials or secret payloads.

### 7.7 Recovery does not depend on the failed runtime

Bootstrap and state recovery cannot require Kubernetes, Argo CD, a production database, or a production application.

### 7.8 Environment and data boundaries are explicit

Development, staging, production, partner, holdout, and restricted-data trust boundaries are represented in projects, identities, networks, storage, policies, and GitHub controls.

### 7.9 Generated files are never hand-authored

Rendered manifests, generated catalogs, plans, SBOMs, and release metadata are produced by deterministic tooling.

### 7.10 Production exemptions expire

Every policy, IAM, freeze, or admission exemption has an owner, reason, approval, exact scope, and expiration.

---

## 8. Final `.github` Repository Blueprint

### 8.1 Charter

The `.github` repository owns reusable GitHub-facing assets, not organization configuration.

It owns:

- organization profile;
- issue and pull-request templates;
- contribution and support templates;
- reusable GitHub Actions workflows;
- ruleset workflow definitions required by `github-config`;
- shared action policy documentation;
- standard security reporting guidance.

It does not own:

- teams;
- repository settings;
- GitHub environments;
- rulesets;
- cloud IAM;
- Kubernetes;
- application source.

### 8.2 Target layout

```text
.github/
├── .github/
│   ├── CODEOWNERS
│   ├── ISSUE_TEMPLATE/
│   ├── PULL_REQUEST_TEMPLATE.md
│   └── workflows/
│       ├── required-repository-policy.yml
│       ├── required-security-baseline.yml
│       ├── reusable-license-headers.yml
│       ├── reusable-nix-flake.yml
│       ├── reusable-terraform-validate.yml
│       ├── reusable-terragrunt-plan.yml
│       └── reusable-artifact-verification.yml
├── profile/
│   └── README.md
├── workflow-templates/
├── docs/
│   ├── workflow-contracts.md
│   └── actions-security.md
├── CONTRIBUTING.md
├── SECURITY.md
├── LICENSE
└── README.md
```

### 8.3 Workflow strategy

- Organization-mandated checks use ruleset workflows.
- Reusable workflows are referenced by immutable commit SHA or a tightly controlled release tag.
- Repository-specific apply workflows remain in their owning repositories.
- OIDC trust may include the called workflow identity through `job_workflow_ref`.
- Third-party Actions are allowlisted and immutable-pinned for privileged workflows.
- The default `GITHUB_TOKEN` permission is read-only.

---

## 9. Final `github-config` Blueprint

### 9.1 Charter

`github-config` is the authoritative GitHub Enterprise governance repository.

It owns:

- repository inventory and creation;
- visibility;
- archival state;
- custom properties;
- teams and hierarchy;
- team-based repository access;
- GitHub environments;
- rulesets;
- ruleset workflow requirements;
- Actions policy;
- OIDC configuration metadata;
- approved GitHub Apps and webhooks where provider support is reliable;
- non-secret repository and organization variables;
- drift detection;
- documented manual controls for unsupported APIs.

### 9.2 Catalog-first architecture

Human-authored policy lives in `catalog/`.

Terraform modules compile the catalog into GitHub resources. Modules must not contain hidden repository-specific policy.

```text
catalog
  -> schema validation
  -> normalized locals
  -> repositories / teams / access / rulesets / environments
  -> GitHub Enterprise
```

### 9.3 Target layout

```text
github-config/
├── .github/
│   ├── CODEOWNERS
│   ├── actionlint.yaml
│   └── workflows/
│       ├── validate.yml
│       ├── plan.yml
│       ├── apply.yml
│       ├── drift.yml
│       ├── idp-sync.yml
│       └── nix-flake.yml
├── catalog/
│   ├── repositories.yaml
│   ├── repository-classes.yaml
│   ├── teams.yaml
│   ├── access.yaml
│   ├── environments.yaml
│   ├── rulesets.yaml
│   ├── actions-policy.yaml
│   ├── oidc-policy.yaml
│   ├── custom-properties.yaml
│   ├── ci-variables.yaml
│   └── schema/
├── idp/
│   ├── README.md
│   └── mappings.yaml
├── modules/
│   ├── catalog/
│   ├── enterprise/
│   ├── organization/
│   ├── repositories/
│   ├── teams/
│   ├── rulesets/
│   └── policies/
├── tests/
├── docs/
├── scripts/
├── backend.tf
├── imports.tf
├── main.tf
├── outputs.tf
├── providers.tf
├── variables.tf
├── versions.tf
├── .terraform.lock.hcl
├── flake.nix
├── flake.lock
├── renovate.json5
├── CONTRIBUTING.md
├── SECURITY.md
├── LICENSE
├── README.md
└── BLUEPRINT.md
```

### 9.4 Access model

- Team-based access is the default.
- Direct user grants are prohibited except documented emergency or temporary access.
- Admin is limited to organization owners and explicitly approved automation.
- Temporary access includes an expiration and fails policy checks when stale.
- Identity lifecycle is driven by the corporate IdP/SCIM model, not Terraform-created human accounts.
- Break-glass enterprise owners remain outside normal automated removal paths but are audited.

### 9.5 Ruleset model

Use a small number of composable organization-level rulesets:

```text
baseline-all
enterprise-control
production-control
source-monorepo
release-tags
push-protection
protected-paths
```

Rules include:

- pull requests required;
- required approvals;
- CODEOWNERS;
- stale approval dismissal;
- conversation resolution;
- no force push;
- no branch deletion;
- merge queue for production-control and monorepo repositories;
- required status checks;
- required ruleset workflows;
- protected release tags;
- restricted repository rename/visibility changes;
- protected workflow and policy paths.

Workflow execution protections may be evaluated, but they are not a mandatory production dependency until Mindclade explicitly accepts their maturity and operational behavior.

### 9.6 Approval policy

Target state:

- ordinary changes: one independent approval;
- production-control changes: one CODEOWNER plus one independent approval;
- Ring 0, identity, policy, trust, and public-visibility changes: two distinct qualified approvals.

During a genuinely solo-founder period, use a documented, time-bounded exception with enhanced automated checks and mandatory post-change review. Do not silently weaken the ruleset.

### 9.7 OIDC governance

GitHub-to-Google Cloud trust conditions should use:

- trusted organization/owner identity;
- immutable repository identifiers where possible;
- repository identity;
- protected environment;
- protected branch/ref;
- called reusable workflow identity;
- explicit audience.

Do not authorize every repository in the organization to impersonate a broad service account.

### 9.8 Apply and drift

- Pull requests run schema tests, Terraform tests, policy tests, and speculative plans.
- Merge to `main` creates a plan for the exact merged SHA.
- Apply waits behind a protected environment approval and applies that exact plan.
- Plan artifacts are sensitive, access-restricted, minimally retained, and never committed.
- Scheduled drift reports out-of-band access, ruleset, visibility, Actions, and environment changes.
- High-risk drift pages security/platform; it is not silently ignored.

---

## 10. Final `bootstrap` Blueprint

### 10.1 Charter

`bootstrap` is Ring 0.

It owns only the minimum resources needed to store state, authenticate automation, and recover the rest of the platform.

### 10.2 Final ownership

Keep:

```text
state
identity
seed projects
CI trust project
bootstrap naming
break-glass
recovery documentation
```

Move to `infrastructure-live`:

```text
normal organization folders
normal organization policies
billing governance
Essential Contacts
SCC
normal organization log sinks
environment projects
workload infrastructure
```

### 10.3 Target layout

```text
bootstrap/
├── .github/
│   ├── CODEOWNERS
│   └── workflows/
│       ├── validate.yml
│       ├── plan.yml
│       ├── apply.yml
│       ├── drift.yml
│       ├── recovery-drill.yml
│       └── nix-flake.yml
├── modules/
│   ├── naming/
│   ├── state/
│   ├── projects/
│   └── identity/
├── docs/
│   ├── architecture.md
│   ├── first-apply.md
│   ├── cold-start.md
│   ├── state-recovery.md
│   ├── break-glass.md
│   ├── credential-rotation.md
│   └── ownership-handoff.md
├── test/
│   ├── scratch-org-drill.md
│   └── clean-room-recovery.md
├── scripts/
├── backend.tf
├── main.tf
├── outputs.tf
├── providers.tf
├── variables.tf
├── versions.tf
├── .terraform.lock.hcl
├── flake.nix
├── flake.lock
├── renovate.json5
├── CONTRIBUTING.md
├── SECURITY.md
├── LICENSE
├── README.md
└── BLUEPRINT.md
```

### 10.4 State backend

Use a dedicated GCS state bucket with:

- uniform bucket-level access;
- public access prevention;
- GCS-native state locking;
- soft delete;
- object versioning;
- lifecycle cleanup for old noncurrent versions;
- narrow IAM;
- audit logs;
- separate prefixes for each repository and live unit;
- documented restore procedure.

Do not apply an irreversible retention lock that prevents Terraform from replacing the current state object. If a retention control is used, validate its behavior against state writes before adoption.

Terraform state is sensitive even when outputs are marked sensitive. Avoid secret payloads in Terraform whenever the provider can use ephemeral/write-only inputs or an external secret-injection path.

### 10.5 First apply

The one-time bootstrap sequence is explicit:

```text
1. authenticate with a tightly controlled founder/organization recovery identity
2. create the state and trust prerequisites with local state
3. migrate bootstrap state to GCS
4. verify the remote state
5. securely destroy local state copies
6. switch all future changes to protected CI
```

### 10.6 WIF architecture

Use a dedicated workload identity project and narrowly scoped providers.

Trust providers separately for:

- GitHub Actions infrastructure workflows;
- Buildkite artifact/build workflows, if Buildkite needs Google Cloud access.

Use:

- attribute conditions for the trusted GitHub organization or Buildkite organization;
- immutable identity attributes;
- explicit audiences;
- one provider per external issuer where practical;
- service-account impersonation;
- audit logging for token exchange and impersonation.

### 10.7 Automation identities

Bootstrap-created or bootstrap-authorized identities are limited to the control-plane recovery path:

```text
bootstrap-plan
bootstrap-apply
github-config-plan
github-config-apply
infrastructure-live-plan
infrastructure-live-apply-development
infrastructure-live-apply-staging
infrastructure-live-apply-production
```

Normal build, qualification, and signing identities are created under `infrastructure-live` in the appropriate common CI/security projects:

```text
artifact-builder
artifact-qualifier
artifact-signer
```

No principal receives Owner. Production apply and signing are separate capabilities.

### 10.8 Break-glass

Break-glass access:

- is independent of daily SSO failure modes;
- requires strong MFA;
- is held by the minimum number of people;
- is never used by CI;
- alerts on activation;
- is audited;
- is rotated/reviewed after use;
- can recover state, WIF, and infrastructure automation.

---

## 11. Final `infrastructure-live` Blueprint

### 11.1 Charter

`infrastructure-live` owns all normal Google Cloud infrastructure after Ring 0.

### 11.2 Final layered layout

```text
infrastructure-live/
├── 1-org/
│   ├── folders/
│   ├── common-projects/
│   ├── org-policies/
│   ├── log-sinks/
│   ├── essential-contacts/
│   ├── scc/
│   ├── access-transparency/
│   ├── kms/
│   └── kms-binauthz/
├── 2-environments/
│   ├── development/
│   ├── staging/
│   └── production/
├── 3-networks/
│   ├── shared/
│   ├── development/
│   ├── staging/
│   └── production/
├── 4-projects/
│   ├── shared/
│   ├── development/
│   ├── staging/
│   ├── production/
│   └── partners/
├── 5-workloads/
│   ├── shared/
│   ├── development/
│   ├── staging/
│   ├── production/
│   └── partners/
├── _envcommon/
├── docs/
├── scripts/
├── .github/
├── root.hcl
├── account.hcl
├── flake.nix
├── flake.lock
├── .terraform-version
├── .terragrunt-version
├── .terraform.lock.hcl
├── renovate.json5
├── CONTRIBUTING.md
├── SECURITY.md
├── LICENSE
├── README.md
└── BLUEPRINT.md
```

### 11.3 Resource hierarchy

Target conceptual folders:

```text
organization
├── bootstrap
├── common
├── networking
├── development
├── staging
├── production
└── partners
```

`bootstrap` owns only the bootstrap folder/projects. `infrastructure-live` owns the remaining folders and normal projects.

Common projects may include:

```text
central logging
SCC/security operations
billing export
common KMS
common secrets
CI runner infrastructure
```

The bootstrap state/WIF projects remain Ring 0 and are not re-owned here.

### 11.4 Layer contract

```text
1-org          organization and common controls
2-environments environment folders and environment foundations
3-networks     Shared VPC, DNS, NAT, PSC, firewall policy
4-projects     workload and partner projects
5-workloads    managed cloud services and clusters
```

A lower-numbered layer cannot depend on a higher-numbered layer.

### 11.5 Project normalization

Replace ambiguous top-level project entries with:

```text
4-projects/shared/<shared-service>
4-projects/development/<domain>
4-projects/staging/<domain>
4-projects/production/<domain>
4-projects/partners/<partner-id>
```

Domain projects may include:

```text
data
research
serving
security
observability
```

Create a project boundary only when justified by IAM, quota, billing, network, lifecycle, or blast-radius isolation.

`1-org/common-projects` is reserved for organization-wide foundation services such as centralized logging, SCC, billing export, and common KMS. `4-projects/shared` is reserved for shared workload/platform projects that sit above individual environments but are not part of Ring 0 or organization governance. A project must not appear in both locations.

### 11.6 Networking

Use:

- Shared VPC per environment;
- private nodes and private service access;
- Private Google Access;
- Private Service Connect where appropriate;
- hierarchical firewall policies for organization/folder baselines;
- network firewall policies for environment-specific control;
- controlled Cloud NAT;
- explicit DNS architecture;
- no default network;
- no broad production/non-production peering;
- partner-specific connectivity;
- deny-by-default egress for sensitive workloads where operationally practical.

Do not mix legacy firewall rules with the strategic firewall-policy model without a documented exception.

### 11.7 Organization policy rollout

Organization policy changes follow:

```text
evaluate/dry run
-> development
-> staging
-> production
```

High-risk constraints must include a lockout and recovery test before organization-wide enforcement.

### 11.8 GKE topology

#### Startup implementation

- one private development cluster, zonal or regional according to budget and test requirements;
- one private regional staging cluster when staging is expected to rehearse production availability and upgrades;
- one private regional production cluster if cost requires initial consolidation.

#### Production target

- `production-serving`: latency-sensitive inference and customer-facing control surfaces;
- `production-compute`: training, evaluation, batch inference, and research compute;
- optional partner-isolated clusters when contractual or risk boundaries require them.

The GitOps project/namespace model must allow this split without reorganizing application source.

#### GKE baseline

- GKE Standard for advanced GPU and node-pool control;
- regional production control planes;
- nodes across multiple zones where the workload supports it;
- release channel enrollment;
- maintenance windows and exclusions;
- Workload Identity Federation for GKE;
- minimal node service accounts;
- private networking;
- cluster hardening baseline;
- managed audit logs and cluster notifications;
- explicit upgrade rehearsals in staging;
- no production dependence on unsupported Kubernetes versions.

### 11.9 GPU and AI capacity

Separate node pools by purpose and accelerator family.

Examples:

```text
system-cpu
general-cpu
gpu-a3-training
gpu-a4-training
gpu-serving
spot-batch
```

Each pool declares:

- accelerator family;
- machine type;
- zone/region;
- capacity model;
- autoscaling envelope;
- labels and taints;
- disk/network profile;
- upgrade behavior;
- workload class;
- cost owner.

Use reservations or committed capacity for critical production serving where needed. Use flex-start/queued provisioning or opportunistic capacity only for interruption-tolerant training and batch workloads. GPU CI runners must not share production serving capacity.

### 11.10 Cloud services

`5-workloads` may own:

- GKE;
- node pools;
- Artifact Registry;
- Binary Authorization;
- Secret Manager resources and IAM;
- Cloud SQL;
- GCS lakehouse;
- GCS checkpoints;
- GCS holdout;
- Parallelstore;
- backup/DR;
- IAP access;
- infrastructure observability;
- VPC Service Controls;
- Argo CD cloud prerequisites;
- CI runner infrastructure.

It does not install Kubernetes applications.

### 11.11 Argo CD boundary

Rename:

```text
5-workloads/<env>/argocd
```

to:

```text
5-workloads/<env>/argocd-prereqs
```

That unit may create cloud identities, DNS, KMS, or cluster access prerequisites. The Argo CD deployment itself belongs exclusively to `gitops`.

### 11.12 Data security

Classify storage and projects:

| Class | Examples | Baseline |
|---|---|---|
| Public scientific | PDB, UniProt, RNACentral mirrors | Integrity and provenance controls |
| Internal research | Curated features, experiments | Employee-only, environment isolation |
| Proprietary assets | Model weights, checkpoints, training corpora | Restricted identities, audit, encryption |
| Holdout/evaluation | Unseen test sets, safety/benchmark data | Default deny to training identities |
| Partner/customer | Partner datasets and outputs | Dedicated identity/project/perimeter where required |
| Restricted biological | Controlled or safety-sensitive data | Explicit authorization and additional review |

Holdout protection must exist at IAM, project/bucket, network/perimeter, workload identity, and Kubernetes policy layers.

### 11.13 VPC Service Controls

Adopt VPC Service Controls first in dry-run/evaluation mode for high-value data services.

Enforce only after:

- supported-service review;
- developer/CI access-path testing;
- ingress and egress policy review;
- incident runbook;
- staging rehearsal.

Perimeter changes are high risk.

### 11.14 Terraform/Terragrunt operation

- Standardize on Terraform plus Terragrunt for these repositories.
- Do not claim simultaneous Terraform/OpenTofu support unless continuously tested.
- Use `terragrunt run --all`, not deprecated `run-all`.
- Enable Terragrunt strict mode in CI, first in lower environments and then globally.
- Keep each state to a few dozen resources where practical and below roughly one hundred.
- Use explicit dependency blocks and stable outputs.
- Do not create cross-environment dependencies.
- Use `_envcommon` for inputs/includes only; it creates no resources.
- Pin reusable module revisions immutably.

### 11.15 Plan and apply

Pull request:

```text
format
validate
lint/security
dependency graph
affected plans
cost analysis
destructive-change classification
```

After merge:

```text
plan exact main SHA
store short-lived protected plan
wait for environment approval
apply exact plan
publish audit summary
```

A PR plan is speculative and is not reused after merge.

Production applies have concurrency control and deterministic unit selection. User-supplied arbitrary paths are prohibited.

### 11.16 Destructive-change gate

Elevated approval is mandatory for destruction/replacement of:

- organization folders/projects;
- production GKE clusters;
- VPCs/subnets;
- KMS keys;
- VPC-SC perimeters;
- Cloud SQL;
- protected buckets;
- state backends;
- organization policies;
- centralized logging/security projects.

---

## 12. Final `gitops` Blueprint

### 12.1 Charter

`gitops` is the authoritative desired-state repository for Kubernetes.

It owns:

- Argo CD bootstrap handoff and self-management;
- root applications;
- AppProjects;
- application composition;
- environment overlays;
- namespaces and in-cluster platform configuration;
- policy-as-code;
- immutable artifact references;
- promotion and freeze controls;
- rendered-manifest verification;
- in-cluster secrets references;
- drift reconciliation;
- Kubernetes recovery runbooks.

### 12.2 Target layout

The existing layout is retained and tightened:

```text
gitops/
├── .github/
│   ├── CODEOWNERS
│   └── workflows/
│       ├── validate.yml
│       ├── render.yml
│       ├── policy.yml
│       ├── provenance.yml
│       ├── promote.yml
│       ├── freeze.yml
│       └── nix-flake.yml
├── bootstrap/
│   ├── README.md
│   ├── argocd-install.yaml
│   ├── argocd-install.sha256
│   └── root-app.yaml
├── applications/
│   ├── platform.yaml
│   ├── data.yaml
│   ├── research.yaml
│   ├── serving.yaml
│   └── partner.yaml
├── projects/
│   ├── platform.yaml
│   ├── data.yaml
│   ├── research.yaml
│   ├── serving.yaml
│   └── partner-isolated.yaml
├── overlays/
│   ├── development.yaml
│   ├── staging.yaml
│   ├── production.yaml
│   └── freeze-windows.yaml
├── policy/
├── rendered/
├── scripts/
├── docs/
├── image-policy.yaml
├── render-manifest.yaml
├── flake.nix
├── flake.lock
├── renovate.json5
├── CONTRIBUTING.md
├── SECURITY.md
├── LICENSE
├── README.md
└── BLUEPRINT.md
```

Add a `clusters/` inventory only when Mindclade operates multiple clusters within an environment. Do not introduce it before it carries real information.

### 12.3 Argo CD deployment model

- `argocd-install.yaml` is generated or vendored from an explicitly pinned upstream release.
- Store its checksum and provenance metadata.
- Do not hand-edit the upstream payload.
- Apply it once after the cluster exists.
- Apply the root application once.
- From then on, Argo CD self-manages through Git.
- Production uses the HA installation only when the cluster has the required failure-domain capacity.
- Development may use a smaller installation.
- Argo CD upgrades are GitOps changes with staging qualification.

### 12.4 Argo CD isolation

Target one Argo CD instance per environment trust domain.

A production serving cluster and a production compute cluster may use separate Argo CD instances to reduce credential and reconciliation blast radius.

CI does not receive Argo CD admin credentials or production kubeconfigs. CI changes Git; Argo CD reconciles Git.

### 12.5 AppProject rules

- Disable practical use of the `default` project by making it deny-all.
- Each project explicitly lists source repositories.
- Each project explicitly lists destination clusters/namespaces.
- Cluster-scoped resource creation is allowlisted.
- Partner projects cannot deploy to shared namespaces.
- Only the tightly restricted platform-administration project may deploy into the Argo CD namespace.
- Push access to repositories trusted by an Argo-admin project is restricted equivalently to cluster-admin access.

### 12.6 Argo CD authentication and RBAC

- SSO through the corporate identity system.
- Anonymous access disabled.
- Local admin disabled after bootstrap or retained only as a controlled break-glass mechanism.
- Default authenticated role has minimal read access or none.
- Project roles map to IdP groups.
- Argo CD administrative access is separate from ordinary application ownership.

### 12.7 Sync policy

Recommended defaults:

| Environment | Auto-sync | Self-heal | Prune |
|---|---:|---:|---:|
| Development | Yes | Yes | Yes for GitOps-owned stateless resources |
| Staging | Yes | Yes | Controlled |
| Production | Yes after protected Git merge | Yes | Opt-in per application/resource class |

Production rules:

- `allowEmpty` is false unless explicitly justified.
- Stateful and destructive resources do not inherit blanket pruning.
- Pruning behavior is tested.
- manual live edits self-heal and alert.
- emergency live changes are reconciled back into Git immediately.

### 12.8 Promotion

```text
monorepo/buildkite
  -> candidate image digest
  -> SBOM
  -> provenance
  -> qualification attestation
  -> promotion PR to gitops
  -> development
  -> staging
  -> production PR
  -> Argo CD
```

The promotion bot may open or update a PR. It may not directly push to production branches or bypass required review.

### 12.9 Freeze control

Production freezes use two layers:

- GitHub promotion controls prevent ordinary production merges;
- Argo CD sync windows prevent ordinary reconciliation during the window.

Emergency override requires:

- incident/change record;
- privileged approval;
- audit trail;
- post-event review.

### 12.10 Rendered manifests

Keep committed rendered manifests for now because the repository already uses them and they improve effective-diff review.

Rules:

- generated only;
- deterministic;
- no timestamps or unstable ordering;
- CI fails on stale output;
- never hand-edited;
- not a second source of truth.

Move renders to CI artifacts later only if repository churn outweighs review value.

### 12.11 Policy engines

Use a clear split:

- Gatekeeper/GKE Policy Controller for structural workload policy;
- Binary Authorization for cryptographic image/attestation enforcement;
- CI verification for release metadata and policy tests.

Do not run a second Sigstore admission controller in production unless it enforces a distinct, documented requirement not already covered by Binary Authorization. Duplicate signature enforcement increases failure modes and policy ambiguity.

Required workload policies include:

- no privileged containers;
- restricted host namespaces and host paths;
- required non-root/security context where compatible;
- required resource requests/limits;
- no mutable image tags;
- approved registries;
- workload identity;
- protected holdout mount restrictions;
- partner namespace isolation;
- time-bounded exemptions.

### 12.12 Secrets

GitOps may commit:

- ExternalSecret or CSI reference objects;
- SecretStore references;
- non-sensitive ConfigMaps;
- secret version references where needed.

GitOps may not commit:

- credential values;
- private keys;
- tokens;
- kubeconfigs;
- partner secrets;
- model-provider secrets.

---

## 13. Final `mindclade-internal-monorepo` Boundary

The monorepo owns:

- all application, platform, model, training, inference, evaluation, data, and SDK source;
- Bazel build graph;
- container definitions;
- environment-neutral Helm/Kustomize/package templates where needed;
- Buildkite pipelines;
- unit, integration, numerical, GPU, security, and release qualification;
- artifact manifests;
- SBOM generation;
- provenance generation;
- release signing/attestation requests.

It does not own:

- production environment image references;
- cloud resource desired state;
- GitHub organization governance;
- cluster credentials;
- Argo CD production configuration.

### CI split

Use:

- GitHub Actions for lightweight PR metadata, organization-required workflows, documentation checks, and repository administration;
- Buildkite for authoritative heavy CI, GPU qualification, clean-checkout builds, numerical qualification, integration tests, release builds, and artifact publication.

Buildkite agents use OIDC and short-lived Google Cloud credentials. They do not store service-account keys.

---

## 14. Software Supply-Chain Architecture

### 14.1 Roles

```text
builder      builds artifact
qualifier    verifies tests/security/numerical gates
signer       signs or creates deployment attestation
promoter     proposes digest in gitops
reconciler   Argo CD deploys approved desired state
```

A compromised builder alone cannot deploy to production.

### 14.2 Release evidence

Every production artifact has:

- immutable image digest;
- source repository and commit SHA;
- builder identity;
- build invocation identity;
- SBOM;
- provenance;
- vulnerability result;
- qualification result;
- attestation/signature;
- release ID;
- compatible configuration/schema metadata where needed.

### 14.3 Artifact flow

- Buildkite publishes a candidate to Artifact Registry.
- Qualification runs against the digest.
- The signer attests the digest only after qualification.
- Binary Authorization accepts only approved attestations in production.
- GitOps verifies metadata and references the digest.
- Argo CD deploys the digest.
- Runtime identity is unrelated to build identity.

### 14.4 Signing keys

Prefer keyless workload identity for access to a narrowly scoped signing service or KMS-backed signing key.

Separate:

- key administration;
- signing permission;
- attestor policy administration;
- production promotion approval.

---

## 15. Identity Architecture

### Humans

```text
Corporate IdP
  -> GitHub Enterprise membership/team sync
  -> Google Cloud workforce identity/IAM groups
  -> Argo CD SSO groups
```

### GitHub Actions

```text
GitHub OIDC
  -> bootstrap-managed WIF provider
  -> scoped service-account impersonation
```

### Buildkite

```text
Buildkite OIDC
  -> bootstrap-managed WIF provider
  -> scoped build/registry/signing identities
```

### GKE workloads

```text
Kubernetes service account
  -> Workload Identity Federation for GKE
  -> narrowly scoped Google Cloud permissions
```

### Prohibited

- shared human service accounts;
- service-account JSON keys;
- broad node service-account permissions;
- one universal Terraform principal;
- one universal runtime identity;
- long-lived repository deployment tokens.

---

## 16. CI Runner Isolation

Buildkite runner infrastructure is not Ring 0.

Ownership split:

- `bootstrap`: WIF trust and minimal CI identity prerequisites;
- `infrastructure-live`: runner projects, networks, clusters/node pools, storage, and IAM;
- `gitops`: Kubernetes Buildkite agent/controller deployment if agents run on GKE;
- monorepo: pipeline definitions.

Rules:

- CI runners do not run in production serving clusters.
- Untrusted PR jobs cannot reach production credentials or networks.
- GPU CI runners are separate from production inference capacity.
- Agents are ephemeral where possible.
- Job identities are short-lived and pipeline-scoped.
- Secrets are fetched just in time from Secret Manager.

---

## 17. Environment and Cluster Promotion Model

### Development

- rapid automated reconciliation;
- no production credentials;
- no production data;
- policy in audit or enforcement according to maturity;
- lower-cost GPU capacity may be opportunistic.

### Staging

- production-like architecture;
- same artifact digest intended for production;
- enforced admission and provenance;
- migration and rollback rehearsal;
- GKE upgrade rehearsal;
- VPC-SC and organization-policy rehearsal.

### Production

- protected Git merge;
- verified digest;
- enforced Binary Authorization;
- enforced workload policy;
- protected secrets/data;
- controlled prune;
- maintenance/freeze windows;
- explicit rollback/forward-recovery path;
- critical serving capacity not entirely opportunistic.

---

## 18. AI-Specific Workload Boundaries

### Training

- batch/queue-oriented;
- interruption-tolerant classes clearly marked;
- checkpoint storage separate from serving assets;
- high-throughput storage/network configuration;
- no default access to holdout data;
- explicit quota and capacity model.

### Evaluation

- separate identities from training;
- holdout access only for evaluation workloads;
- outputs protected from leakage back into training data unless explicitly approved;
- reproducible artifact/model/dataset lineage.

### Serving

- separate SLO and cluster/node-pool policy;
- immutable model and runtime references;
- controlled model rollout;
- capacity floor for production;
- request and model telemetry that does not leak sensitive payloads.

### Research

- flexible but not ungoverned;
- non-production by default;
- approved images and identities;
- data-classification-aware access;
- isolated partner and restricted-data workflows.

---

## 19. Observability and Audit

Centralize evidence from:

- GitHub audit log;
- GitHub Actions;
- Buildkite;
- Google Cloud audit logs;
- WIF token exchange and service-account impersonation;
- Terraform/Terragrunt plans and applies;
- Argo CD audit and sync events;
- Kubernetes audit logs;
- Binary Authorization decisions;
- policy-controller denials;
- GKE upgrade/security notifications;
- Artifact Registry and signing events.

Every production deployment must be attributable to:

```text
Git commit
pull request
approvers
artifact digest
source commit
qualification
attestation
GitOps commit
Argo CD sync
runtime environment
```

Logs must not contain credentials, private keys, full sensitive biological payloads, or partner data unless explicitly required and protected.

---

## 20. Backup and Disaster Recovery

### 20.1 Recovery order

```text
1. recover GitHub/identity/billing ownership
2. recover bootstrap state and WIF
3. recover github-config governance
4. recover infrastructure-live
5. rebuild GCP layers 1 through 5
6. install Argo CD
7. apply root application
8. reconcile gitops
9. restore stateful data
10. validate serving/training/data integrity
```

### 20.2 Control-plane backups

Maintain:

- GCS state soft delete/version history;
- protected off-platform backups or mirrors of critical control repositories;
- release metadata and artifact registry retention;
- database and object-storage backup policies;
- KMS and recovery documentation;
- tested emergency identity recovery.

### 20.3 Drills

Required recurring exercises:

- bootstrap clean-room recovery;
- Terraform state recovery;
- GitHub/IdP outage procedure;
- failed organization-policy rollback;
- VPC-SC lockout recovery;
- GKE cluster reconstruction;
- Argo CD loss and re-bootstrap;
- Cloud SQL restore;
- protected bucket restore;
- compromised artifact revocation.

---

## 21. Production Change Classification

| Class | Examples | Required control |
|---|---|---|
| Low | Documentation, non-production labels | Normal review |
| Medium | Staging deployment, bounded resource tuning | CODEOWNER or domain owner |
| High | Production artifact, network/IAM change, production secret reference | Independent approval and protected environment |
| Critical | Ring 0, state, WIF, org policy, KMS trust, Argo admin, Binary Authorization, partner isolation, destructive production change | Two qualified approvals and explicit rollback/recovery plan |

Automation must classify clearly destructive plans rather than rely only on a reviewer noticing text in raw Terraform output.

---

## 22. Freeze and Emergency Change Model

A production freeze blocks ordinary:

- `infrastructure-live` production applies;
- `gitops` production promotions;
- high-risk GitHub governance changes.

It does not block:

- read-only plans;
- drift detection;
- incident containment;
- recovery;
- urgent security remediation.

Emergency changes require:

- incident/change identifier;
- authorized bypass;
- exact scope;
- audit evidence;
- immediate reconciliation to Git;
- post-incident review;
- bypass revocation.

---

## 23. Standard Repository Hygiene

Every control repository uses:

```text
.github/CODEOWNERS
SECURITY.md
CONTRIBUTING.md
README.md
BLUEPRINT.md
proprietary LICENSE/notice
Nix flake
pre-commit
Renovate
pinned dependency lock files
minimal GitHub workflow permissions
```

Rules:

- retain upstream notices for vendored third-party content;
- do not apply Mindclade proprietary headers to third-party files in a way that obscures their license;
- do not commit local caches;
- do not expose secrets in examples;
- use exact tool versions in CI;
- use one canonical Makefile/command vocabulary per repo.

---

## 24. Concrete Repository Migration Map

| Current path or pattern | Final disposition |
|---|---|
| `bootstrap/modules/folders/**` | Migrate normal folder hierarchy to `infrastructure-live/1-org/folders`; retain only a bootstrap folder if Ring 0 needs it |
| `bootstrap/modules/governance/org-policies.tf` | Move normal organization policy to `infrastructure-live/1-org/org-policies` |
| `bootstrap/modules/governance/contacts.tf` | Move to `infrastructure-live/1-org/essential-contacts` |
| `bootstrap/modules/governance/billing.tf` | Move billing export/governance to `infrastructure-live/1-org/common-projects` |
| `bootstrap/modules/governance/audit.tf` | Move normal audit sinks/configuration to `infrastructure-live/1-org/log-sinks`; retain only prerequisites that must predate infrastructure-live |
| `infrastructure-live/4-projects/{research,serving,data,security,observability}` | Classify each as truly shared or move it into `development`, `staging`, or `production`; remove ambiguous duplicates |
| `infrastructure-live/4-projects/partner-acme` | Move to `4-projects/partners/<partner-id>` and keep partner names out of generic modules |
| `infrastructure-live/5-workloads/development/argocd` | Rename to `argocd-prereqs`; remove Kubernetes installation ownership |
| Missing `5-workloads/staging/**` and `5-workloads/production/**` equivalents | Add only services actually required, using development as the architectural template rather than copying scale blindly |
| `github-config/modules/rulesets/required-workflows.tf` | Rename/reframe as ruleset workflow enforcement; keep workflow implementation in `.github` |
| Duplicate root and `.github` CODEOWNERS patterns | Standardize on `.github/CODEOWNERS` |
| Repeated generic validation workflows | Move implementation to reusable/ruleset workflows in `.github`; keep thin repository wrappers |
| `gitops/policy/sigstore/**` plus Binary Authorization | Keep only if it enforces a distinct requirement; otherwise consolidate cryptographic enforcement on Binary Authorization |
| `gitops/rendered/**` | Retain as generated review output; prohibit manual edits and verify determinism |
| `.terraform/**` and `.terragrunt-cache/**` | Delete from working trees before packaging/committing; enforce ignore and CI hygiene checks |
| legacy `terragrunt run-all` usage | Replace with `terragrunt run --all` and enable strict mode in CI |

---

## 25. Implementation Priorities

### P0 — Before any production workload

- [ ] Finalize repository visibility.
- [ ] Establish repository classes/custom properties.
- [ ] Protect all default branches and critical paths.
- [ ] Centralize required ruleset workflows.
- [ ] Remove committed local Terraform/Terragrunt caches.
- [ ] Complete bootstrap remote state migration.
- [ ] Enable WIF for GitHub Actions and Buildkite.
- [ ] Separate plan/apply identities.
- [ ] Resolve all bootstrap/infrastructure-live ownership overlap.
- [ ] Rename Terraform Argo CD ownership to `argocd-prereqs`.
- [ ] Create complete staging and production live trees.
- [ ] Enforce immutable image digests.
- [ ] Establish Artifact Registry, provenance, attestation, and Binary Authorization.
- [ ] Enable Workload Identity Federation for GKE.
- [ ] Deploy Argo CD with restricted projects/RBAC.
- [ ] Eliminate plaintext secrets from Git.
- [ ] Create state, cluster, failed-sync, and rollback runbooks.

### P1 — Before external users or valuable proprietary models

- [ ] Separate production serving and compute trust domains.
- [ ] Enforce holdout isolation across IAM and Kubernetes.
- [ ] Add VPC-SC dry-run and staged enforcement.
- [ ] Add partner project/namespace/network patterns.
- [ ] Complete centralized audit ingestion.
- [ ] Add destructive-plan classification.
- [ ] Rehearse cluster and Argo CD reconstruction.
- [ ] Rehearse database and protected-storage restore.
- [ ] Add critical GPU capacity strategy.

### P2 — At larger scale

- [ ] Multi-region serving design.
- [ ] Additional production clusters/Argo instances.
- [ ] Fleet-level identity or policy where justified.
- [ ] Automated privileged-access management.
- [ ] Capacity reservations across accelerator families.
- [ ] Off-platform repository recovery automation.
- [ ] Formal compliance evidence generation.

---

## 26. Repository-Specific Production Acceptance Gates

### `.github`

- [ ] Reusable workflows are immutable-referenced.
- [ ] Mandatory ruleset workflows are minimal and stable.
- [ ] Privileged workflows use explicit permissions.
- [ ] Templates do not leak internal data.

### `github-config`

- [ ] Catalog schemas pass.
- [ ] Every repo has owner/class/lifecycle metadata.
- [ ] Direct admin grants are allowlisted and reviewed.
- [ ] Rulesets protect branches, tags, workflows, and visibility.
- [ ] OIDC metadata is narrowly scoped.
- [ ] Drift detects out-of-band access changes.
- [ ] Manual-only enterprise controls are inventoried.

### `bootstrap`

- [ ] Remote GCS state is active and locking works.
- [ ] Soft delete/version recovery is tested.
- [ ] Local state is destroyed after migration.
- [ ] WIF conditions use trusted and immutable attributes.
- [ ] No automation identity has Owner.
- [ ] Break-glass has been tested.
- [ ] Normal folders/governance have moved out.

### `infrastructure-live`

- [ ] No duplicate ownership with bootstrap.
- [ ] All states are small and uniquely addressed.
- [ ] Development/staging/production are complete.
- [ ] Private regional GKE and release-channel policy are set.
- [ ] Network and workload identity baselines are enforced.
- [ ] GPU pools and cost/capacity controls are explicit.
- [ ] VPC-SC has been tested before enforcement.
- [ ] Destructive production plans are gated.
- [ ] Argo CD resources are not installed by Terraform.

### `gitops`

- [ ] Argo install is pinned and checksummed.
- [ ] `default` AppProject is deny-all.
- [ ] Argo namespace deployment authority is narrowly restricted.
- [ ] SSO/RBAC is least privilege.
- [ ] Production uses immutable digests.
- [ ] Policy tests cover allowed and denied fixtures.
- [ ] Binary Authorization and structural policy responsibilities are distinct.
- [ ] Secrets are references only.
- [ ] Freeze and rollback procedures are tested.
- [ ] Rendered output is deterministic.

### `mindclade-internal-monorepo`

- [ ] Buildkite is the authoritative heavy qualification engine.
- [ ] Clean-checkout builds are reproducible.
- [ ] Release artifacts include SBOM/provenance.
- [ ] Builder and signer capabilities are separate.
- [ ] Promotion occurs through GitOps PRs.
- [ ] The monorepo has no production kubeconfig or direct Argo admin token.

---

## 27. Final Architecture

```text
                         MINDCLADE ENTERPRISE
                                  |
              +-------------------+-------------------+
              |                                       |
              v                                       v
         GitHub Enterprise                       Google Cloud
              |                                       |
      +-------+--------+                              |
      |                |                              |
      v                v                              v
   .github       github-config                    bootstrap
      |                |                              |
      | shared         | governance                   | state + trust
      | workflows      |                              |
      +--------+-------+------------------------------+
               |                                      |
               v                                      v
      mindclade-internal-monorepo             infrastructure-live
               |                                      |
               | signed immutable artifacts           | GCP + GKE
               +-------------------+------------------+
                                   v
                                 gitops
                                   |
                                   v
                                Argo CD
                                   |
                                   v
                 data | research | training | serving
```

### Final decision statement

> **Mindclade's platform foundation is production-grade when every change can be traced from an approved source commit to an immutable qualified artifact, through an explicitly governed infrastructure or GitOps change, into an isolated runtime identity—and when the entire control plane can be reconstructed without depending on the workload it is recovering.**

This blueprint is the final architectural contract for Mindclade's GitHub Enterprise and Google Cloud control-plane repositories.
