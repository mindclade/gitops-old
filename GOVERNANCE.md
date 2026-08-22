<!-- mindclade-doc: governance@1 -->

# Mindclade governance · `gitops`

| Document control | Value |
| --- | --- |
| Owner | Mindclade Platform |
| Version | 1.0 |
| Last reviewed | August 21, 2026 |
| Authority | Argo CD, Kubernetes desired state, admission policy, and promotion records |

## Authority boundary

This repository is authoritative for the scopes declared in
[contracts/repository.yaml](contracts/repository.yaml). Cloud-resource
provisioning belongs to `infrastructure-live`; application source and image
builds belong to the monorepo; plaintext secrets are prohibited.

## Decisions and approvals

Routine development changes require passing checks, one approval, and code-
owner review. Production state, admission policy, image policy, Argo CD
administration, promotion, exemptions, or workflow authorization require
Platform and Security review and two qualified approvals. Rendered application
state is generated and must not be hand-edited.

## Evidence and reconciliation

Pull requests bind source revision, artifact digest, release and qualification
evidence, environment transition, policy results, observability, and rollback.
Argo CD reconciliation is the only routine mutation path. A green render proves
determinism; it does not prove that a workload is qualified for production.

## Exceptions and review

Policy exceptions require an exact workload and namespace, owner, Security
reviewer, reason, risk, removal condition, issue, and expiry of no more than 90
days. Holdout-data isolation and provenance enforcement have no exemption.
Emergency procedures are defined in
[docs/freeze-and-emergency.md](docs/freeze-and-emergency.md).

Drift, exemptions, image provenance, failed syncs, recovery evidence, and
privileged project membership are reviewed at least quarterly and after every
emergency use. Organization-wide defaults are defined in
[`mindclade/.github/GOVERNANCE.md`](https://github.com/mindclade/.github/blob/main/GOVERNANCE.md).

