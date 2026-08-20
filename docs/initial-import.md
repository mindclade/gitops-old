<!-- mindclade-doc: how-to@1 -->

# Import and activate the GitOps repository

> **Audience:** Platform bootstrap operators
> **Outcome:** Import the repository, validate generated and hand-authored state, and activate
> each environment only after its cloud and trust prerequisites are qualified.
> **Risk:** critical—activation establishes continuous reconciliation authority in each cluster.

## Prerequisites

- the existing `mindclade/gitops` repository and its `.git` history;
- `.github` workflow release `v3.0.0` and the corresponding `github-config` policy;
- completed `bootstrap` and `infrastructure-live` prerequisites for the first environment;
- a read-only Argo GitHub App installation and approved OAuth client values; and
- a checkout of `mindclade-internal-monorepo` at the ref pinned by `render-manifest.yaml`.

## Import and validate

1. Back up the current repository and record its default-branch commit.
2. Copy this tree into the existing checkout while preserving `.git`. Exclude kubeconfigs,
   credentials, temporary secret files, and local render scratch data.
3. Enter the pinned shell and run repository validation:

   ```sh
   nix develop
   make validate
   python3 scripts/render.py --monorepo ../mindclade-internal-monorepo
   gator verify policy/tests/suite.yaml
   ```

4. Review the complete diff. Any hand-authored change under `rendered/`, unresolved content
   lock, unpinned image, or cross-environment destination is a stop condition.
5. Open and merge the import pull request through the normal production-control rules.

## Activate one environment

1. Verify the cluster, cloud-side Argo prerequisites, Binary Authorization policy, secret
   backend, and repository credential are for the same environment.
2. Follow [disaster recovery](disaster-recovery.md) to run the audited bootstrap with the
   declared profile and exact Kubernetes context.
3. Confirm the root app establishes projects before workload applications and that the
   default project is deny-all.
4. Activate workloads through [workload activation](workload-activation.md), beginning with
   development and promoting reviewed bytes to staging and production.

## Verify

- Argo has read-only access to this repository and no unrelated repository;
- each Argo instance discovers only its environment paths and destinations;
- generated manifests match the pinned monorepo ref and artifact selections;
- Gatekeeper positive and negative behavior tests pass;
- Binary Authorization rejects an unqualified production artifact; and
- no plaintext or encoded secret value exists in Git.

The platform import order is `.github`, `bootstrap`, `github-config`,
`infrastructure-live`, then `gitops`.

## Roll back or recover

Before bootstrap, revert or close the import change. After Argo owns an environment, restore only a
compatible reviewed Git commit and let reconciliation converge; do not delete Applications or edit
live resources to undo the import. Follow [disaster recovery](disaster-recovery.md) if the control
plane is unavailable and [rollback](rollback.md) for a workload regression.
