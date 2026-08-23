<!-- mindclade-doc: runbook@1 -->

# Qualify the Argo CD production control plane

> **Use when:** promoting a reviewed Argo CD payload or closing its production preflight.
> **Outcome:** retain source and connected evidence proving the exact standard-profile control
> plane can be admitted, operated, recovered, and governed without promoting workloads.
> **Primary owners:** platform and security, using protected infrastructure and cluster paths.

## Source gate

1. Start from immutable GitOps and infrastructure commits with clean worktrees.
2. Run the complete GitOps validation, deterministic render, both standard/HA Kustomize renders,
   Kubeconform, and Gatekeeper behavior/evaluation suites.
3. Prove that Argo provenance, the immutable-image component, `image-policy.yaml`, Gatekeeper,
   and the infrastructure exception contract contain the same four exact digests.
4. Keep development, staging, and production deployment selections empty. Selecting the HA
   profile or an application workload is a separate production change.
5. Run Nix qualification only through the GitHub-verified `.github` main commit
   `0bdba2a8d06c732a6eb0a09238267dc83e1ca576`, whose reviewed tree is
   `9cf970b06e77ec42f12f935a98f7b57baeefcda4`. The production contract rejects a caller or
   runbook that names a different reusable-workflow authority.

Source success does not prove an applied policy, admission decision, Argo login, recovery, or
freeze path. Record it separately from the connected gate.

The immutable developer-workstation path has the same separation. Its source contracts select
bootstrap `1.6.0`, reusable workflows `v5.0.0`, and Terraform modules `v0.4.0`; GitOps records
their readiness in `qualification/workstation-image-readiness.yaml` but owns no VM image or GCP
resource. Keep all connected fields false and selection disabled until the create-only source
object, Terraform-owned Compute Image, first boot, idle shutdown, rollback, and enforced VPC-SC
cache path have independent evidence.

## Staging gate

1. Apply the protected staging infrastructure plan and export the applied Binary Authorization
   policy. Require global policy evaluation, an enforced build-attestor default, no cluster or
   namespace rules, and only the four exact Argo exceptions.
2. In an approved ephemeral qualification namespace, submit one digest-pinned Artifact Registry
   image that lacks the required attestation. Retain the denial and audit identifiers, then remove
   the rejected test object.
3. Reconcile and recreate every active standard-profile Argo component. Record its exact image,
   admission result, ready state, and Git revision. HAProxy remains source-qualified but inactive.
4. Verify GitHub SSO groups and project RBAC, read-only GitHub App repository access, absence of
   anonymous/local-admin access, controller logs, metrics, notifications, and root/self-management
   synchronization.
5. Rehearse a harmless rollback/forward recovery, failed sync, and complete Argo namespace-loss
   rebootstrap using the standard profile.

Any failed or unavailable staging step blocks the production apply; do not replace evidence with a
source inference or weaken admission.

## Production gate

1. Inspect and apply the exact merged-commit infrastructure plan. It may change the policy and
   verifier's read-only IAM only; cluster, KMS, attestor, replacement, destruction, or unexpected
   IAM changes are stop conditions.
2. Run the connected provenance workflow and retain its applied-policy result. Then a human
   operator reconciles the reviewed standard profile through the audited bootstrap path.
3. Repeat the policy export, approved negative admission attempt, active-controller recreation,
   SSO/RBAC/repository/health checks, and a harmless Git revert/forward rollback canary.
4. Rehearse the one-pull-request freeze override with a harmless control-plane change. Prove an
   ordinary change is blocked, one named Application can sync the exact approved revision, and
   `manualSync` immediately returns to `false` without weakening admission.

Do not perform destructive production namespace-loss testing; staging supplies that evidence.

## Evidence and disposition

Retain source commits, plan checksum, approvals, policy-export hash, exact digests, admission audit
IDs, Argo revision/health, SSO and RBAC outcomes, rollback/freeze/recovery results, owner, and next
revalidation date in the approved evidence system. Never commit plans, state, credentials, tokens,
kubeconfigs, or sensitive logs.

The protected workflow converts every successful connected check into a canonical evidence claim
and policy-bound verification for the exact deployment-bundle digest. The evaluator uses a
ten-minute keyless IAP credential to submit those records, requests one eligibility decision, and
accepts only an exact `eligible` result covering every active control. Both the evaluator and the
separate archive writer verify the Ed25519 signature against the immutable Cloud KMS key version;
the writer then publishes the response create-only beneath the qualification bundle. A stale,
revoked, incomplete, tampered, unsigned, or differently keyed decision is a hard failure.

Before production desired state can merge, first merge a `staged-v1` selection. The protected
workflow computes its candidate render without publishing it, assembles the v2 deployment bundle,
and emits a sanitized `mindclade.dev/production-handoff/v1` claim plus its pinned public key. The
activation pull request references that claim through the v3 deployment set, changes the state to
`qualified-v1`, and commits the exact candidate render atomically. The
claim contains no raw evidence or credential: it records the generation-pinned evidence URI,
bundle/decision/selection/render digests, exact source commits, signature, public-key fingerprint,
six-hour validity window, and rollback target. Credential-free validation verifies the committed
signature. On pull requests, the protected `production-handoff-gate` runs from the protected base
revision through `pull_request_target`, treats the head only as data, validates it before cloud
authentication, and re-fetches the exact immutable object generation. Merge groups receive no
cloud identity; they repeat signature, expiry, selection, and render validation with tooling from
the protected merge-group base. Trusted provenance pins the privileged workflow digest, so changing
that workflow requires a separate reviewed trust transition. Activate the required context through
GitHub governance before selecting production workloads.
Expiry freezes a new promotion and requires reviewed operator disposition rather than deleting a
healthy workload automatically.

The disposition is `PASS` only when all source and connected gates pass. Use
`PASS_WITH_DEPLOYMENT_PREFLIGHT` while a protected apply or drill remains, and `BLOCKED` when the
required protected path or evidence cannot be obtained without weakening a control.
