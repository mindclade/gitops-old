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

The disposition is `PASS` only when all source and connected gates pass. Use
`PASS_WITH_DEPLOYMENT_PREFLIGHT` while a protected apply or drill remains, and `BLOCKED` when the
required protected path or evidence cannot be obtained without weakening a control.
