<!-- mindclade-doc: contributing@1 -->

# Contributing to Mindclade · `gitops`

Org-wide conventions are the canonical
[`CONTRIBUTING.md`](https://github.com/mindclade/.github/blob/main/CONTRIBUTING.md).
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

## Promotion preserves the immutable artifact

`promote.yml` copies only the selected Artifact Registry repository, digest, and release record
between adjacent environments. CI then renders the target from that environment's own reviewed
configuration.

Do not copy rendered manifests across environments: their replicas, quotas, endpoints, and policy
are intentionally different. CI instead fails when a changed target selection is not exactly the
one currently qualified in its adjacent source environment.

## Policy changes use a staged rollout

Use `dryrun` first for existing clusters. A greenfield baseline can start at `deny` before
workload activation only when positive and negative behavior fixtures pass, rendered state has
zero violations, and the change still promotes through development and staging.

The process is in [`policy/README.md`](policy/README.md). Roughly: `dryrun`, wait a full
deployment cycle, read the violations, fix the workloads, then promote.

`deny-holdout-bucket-mount` and Binary Authorization for Mindclade-produced application images
take **no exemption, ever**. Reviewed upstream GitOps control-plane images are the sole temporary
exception class: each exact digest must be present in `image-policy.yaml`, Gatekeeper, and the
applied staging/production Binary Authorization policy, with platform ownership, security review,
and an expiry of at most 90 days. Registry prefixes and namespace-wide bypasses are prohibited.

## Exemptions expire

Every entry in `policy/exemptions.yaml` needs an accountable owner, one exact namespace and
workload, a grant date, an expiry no more than 90 days later, a named `@security` reviewer,
specific reason and risk statements, a removal condition, and a repository issue. CI rejects
wildcards, missing fields, duplicates, inactive constraints, never-exemptible controls, and
expired records — that friction is the point.

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


## Contributor authorization and intellectual property

A contribution may be submitted only by a person authorized under a current
written employment, contractor, assignment, or other contribution agreement
with Mindclade, LLC. Before opening or updating a pull request, the contributor
must confirm that:

- they have the right and authority to submit every part of the contribution;
- first-party work is covered by the contributor's controlling written
  agreement with Mindclade, LLC.;
- third-party code, data, models, media, fonts, specifications, and generated
  material are identified with their source, version, license, provenance, and
  required notices;
- the contribution contains no material whose confidentiality, license,
  consent, acceptable-use terms, export controls, or other restrictions
  prohibit submission; and
- the change description and validation evidence are complete and accurate.

By submitting or updating a pull request, the contributor represents that these
statements are true. Submission is not acceptance and does not by itself alter
ownership, grant a license, or replace the controlling written agreement.
Signed commits establish source identity and integrity; they are not a
substitute for the required written agreement.

If authorization or ownership is unclear, stop before submission and use the
legal or contract channel named in the applicable agreement. Do not place
confidential material in a public issue or an unapproved email.
