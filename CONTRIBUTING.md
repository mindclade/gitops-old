# Contributing to `gitops`

Org-wide conventions are the canonical
[`CONTRIBUTING.md`](https://github.com/Mindclade/.github/blob/main/CONTRIBUTING.md).
This file covers what is different here.

*(This exists because `.github` is internal, so nothing inherits. See `SECURITY.md`.)*

## `rendered/` is generated — never hand-edit it

CI writes it. An edit you make there is reverted by the next render, and the reversion looks
like the cluster changing on its own.

`validate.yml` re-renders and diffs, so a hand-edit fails the PR rather than merging and
confusing someone a week later.

**To change a workload:** edit its source in the monorepo, let CI render into
`rendered/development/`, then promote through staging to production.

**To change platform policy, an ApplicationSet, or an AppProject:** edit here directly. Those
are hand-written.

## Adding a workload to the render

`render-manifest.yaml` is data. Add an entry — source path, output directory, Argo project,
and which environments it renders into — and the renderer picks it up. No workflow change.

The output directory prefix matters: it decides which ApplicationSet claims it. `platform-*`,
`serving-*`, `research-*`, `data-*`, `partner-*`. A directory matching no glob renders fine
and is then ignored by Argo, which is a confusing way to discover a typo.

## Promotion is bit-identical

`promote.yml` copies manifests between environments and applies **only** a namespace overlay.
It does not re-render.

That is what makes "staging runs the same thing as production" checkable rather than asserted.
A re-render at promotion could pick up a different chart version or base image and nothing in
the diff would say so. CI fails a promotion PR whose diff contains anything beyond namespace
changes.

## Policy changes ship at `dryrun` first

Never straight to `deny`. A constraint that is right in principle and slightly wrong in
practice blocks deployments that were working an hour ago, and the first response is a
permanent exemption — worse than not shipping it.

The process is in [`policy/README.md`](policy/README.md). Roughly: `dryrun`, wait a full
deployment cycle, read the violations, fix the workloads, then promote.

Two controls take **no exemption, ever**: `deny-holdout-bucket-mount` and the production
Binary Authorization attestation policy. Both guard against things that are unrecoverable
once they happen. Gatekeeper's `require-image-policy` remains the distinct structural control
for approved registries and immutable digests.

## Exemptions expire

Every entry in `policy/exemptions.yaml` needs an expiry, a named `@security` reviewer, a
specific reason, and a ticket. CI fails on an expired one — that friction is the point.

## Local checks

```sh
nix develop
kubeconform -strict -summary -ignore-missing-schemas rendered/
gator verify policy/tests/suite.yaml
gator test --filename=policy/templates --filename=policy/constraints \
  --filename=rendered/development
pre-commit install
pre-commit run --all-files mindclade-license-header
```
