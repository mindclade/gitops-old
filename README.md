# `gitops`

Mindclade's only source of truth for Argo CD and in-cluster Kubernetes desired state.

> ## `rendered/` IS GENERATED — NEVER HAND-EDIT IT
>
> CI writes it. An edit you make there is reverted by the next render, and the reversion looks
> like the cluster changing on its own. Change the source and let CI render.

## The rendered-manifests pattern

CI renders Helm and Kustomize down to plain YAML and commits the result. Argo applies that
YAML and does no templating of its own.

The reason is a single property: **the PR diff is the cluster delta.** Not an approximation
of it, not the inputs that produce it — the exact set of resources that will change.

With in-cluster templating, a PR that bumps one Helm value shows you one changed line and
tells you nothing about the 40 resources it rewrites. Reviewing "does this change do what it
says" becomes impossible, and the answer arrives after the apply.

Costs worth knowing: `rendered/` is large and noisy in history (`.gitattributes` marks it
`linguist-generated`), and a render bug is a commit rather than a runtime error. Both are
worth it for a readable production diff.

## Layout

```
bootstrap/      pinned Argo CD payloads and root app — applied once by the audited bootstrap script
applications/   ApplicationSets. HAND-WRITTEN
projects/       AppProject: repo, cluster, and namespace allowlists. HAND-WRITTEN
policy/         Policy Controller templates and constraints. HAND-WRITTEN
overlays/       per-environment overlay values. HAND-WRITTEN
rendered/       plain YAML, one directory per environment. CI-WRITTEN
```

Everything except `rendered/` is authored. `rendered/` is output.

## Promotion

`promote.yml` copies manifests **bit-identically** from `rendered/staging/<app>` to
`rendered/production/<app>` and applies only a namespace overlay. It does not re-render.

That is what makes "staging runs the same thing as production" a checkable claim rather than
an assertion. A re-render at promotion time could pick up a different chart version, a
different image tag, or a different default — and nothing in the diff would say so.

`validate.yml` enforces it: a promotion PR whose diff contains anything beyond namespace
changes fails.

## Policy

Policy Controller (Gatekeeper) constraints live in `policy/constraints/`. The two controls
with the highest consequence are:

- **`require-image-policy`** — an image must be digest-pinned and come from an approved registry.
  Binary Authorization separately verifies the cryptographic deployment attestation at admission.
- **`deny-holdout-bucket-mount`** — no training workload may mount the held-out evaluation
  bucket. Benchmark numbers are worthless if the holdout set has leaked into training, and
  that leak is invisible after the fact.

New constraints ship in `dryrun` and are promoted to `deny` once the violation count is zero.
`policy/README.md` has the process. Shipping straight to `deny` blocks deployments that were
already running fine, which is how a policy gets an emergency exemption on its first day.

Exemptions are in `policy/exemptions.yaml`. Every one has an expiry and a reviewer. An
exemption with no expiry is a deleted constraint with extra steps.

## Working on this

```sh
nix develop      # kubeconform, gator, kustomize, helm, opa

# Validate what CI validates
kubeconform -strict -summary -ignore-missing-schemas rendered/
gator verify policy/tests/suite.yaml
gator test --filename=policy/templates --filename=policy/constraints \
  --filename=rendered/development
```

To change a workload: edit its source in the monorepo, let CI render into
`rendered/development/`, then promote through staging to production.

To change platform policy or an ApplicationSet: edit here directly. Those are hand-written.

## CI

| Workflow | Trigger | What it does |
|---|---|---|
| `validate.yml` | PR | kubeconform, Gatekeeper behavior tests, and generated-output integrity checks |
| `provenance.yml` | PR | Every image digest referenced in `rendered/` has a valid attestation |
| `promote.yml` | dispatch | Opens a promotion PR, staging → production, bit-identical |
| `freeze.yml` | PR | Blocks production changes during a declared freeze window |

The no-drift check in `validate.yml` is what enforces the "never hand-edit" rule
mechanically rather than by asking nicely.

## Argo's access

Argo has **read-only** access to this repository and to nothing else. It cannot write here,
which means it cannot self-modify, and a compromised Argo cannot rewrite the manifests that
define what it is allowed to run.

The cloud-side identity and secret prerequisites are owned by the environment units in `infrastructure-live`; Argo CD itself is installed only from `bootstrap/` in this repository.
