# Policy

Policy Controller (Gatekeeper) constraints. This is where the build pipeline's guarantees
become preconditions rather than metadata.

Gatekeeper enforces the structural preconditions for deployment: immutable digests and approved registries. Binary Authorization is the single cryptographic admission gate that verifies the required attestations before a workload starts.

## Layout

```
templates/          ConstraintTemplates we wrote — the Rego. Reusable logic.
templates/vendor/   ConstraintTemplates vendored from gatekeeper-library, pinned.
constraints/        Constraint instances — where each template applies, and how hard.
exemptions.yaml     Expiring, reviewer-signed holes.
```

A template defines *what* can be checked. A constraint decides *where* it applies and whether
a violation warns or blocks.

**A constraint whose template is missing does not fail loudly.** It fails to apply, and the
control silently does not exist. That is why library templates are vendored rather than
assumed present, and why `validate.yml` checks every constraint kind has a template before it
evaluates anything.

## One cryptographic enforcement point

Image controls are intentionally divided by responsibility without deploying overlapping
signature admission controllers:

| Control | Where | Proves |
|---|---|---|
| `require-image-policy` | Gatekeeper, admission | Image is pinned by digest, from an evaluated registry |
| Release verification | GitHub Actions, before merge | Provenance, SBOM, qualification, and attestation evidence resolve for the exact digest |
| Binary Authorization | GKE, admission | A valid attestation exists from every required production attestor |

GitHub Actions verifies the producer identity and evidence before merge. Binary Authorization
is the single runtime cryptographic gate. A second Sigstore admission controller is prohibited
unless Mindclade approves a distinct requirement and failure model in a new architecture decision.

## dryrun → deny

**Never ship a new constraint at `deny`.** A constraint that is correct in principle and
slightly wrong in practice blocks deployments that were working fine an hour ago, and the
first thing anyone does is grant it a permanent exemption. That is worse than not having
shipped it.

The process:

**1. Ship at `dryrun`.**

```yaml
spec:
  enforcementAction: dryrun
```

Violations are recorded on the constraint's status and in the audit log; nothing is blocked.

**2. Wait a full deployment cycle.** At minimum a week — long enough for the weekly batch
jobs, the scheduled retrains, and whatever only runs on release day.

**3. Read the violations.**

```sh
kubectl get constraint <name> -o jsonpath='{.status.violations}' | jq
```

For each one, decide: is the workload wrong, or is the constraint wrong? Both answers are
common, and assuming the first is how a bad constraint ships.

**4. Fix the workloads.** Not the constraint, unless the constraint is genuinely wrong.

**5. Promote to `deny`** once violations are zero for a week.

```yaml
spec:
  enforcementAction: deny
```

**6. Watch for a day.** Something always runs on a schedule you did not think about.

## Exemptions

In `exemptions.yaml`. Every one has:

- **An expiry.** Not optional. An exemption with no expiry is a deleted constraint with extra
  steps.
- **A reviewer.** Named, from `@security`.
- **A reason.** Specific enough that someone can tell in three months whether it still holds.
- **A ticket.** Linking to the work that removes the need for it.

`validate.yml` fails on an exemption past its expiry. That is deliberate friction: renewing
one should require someone to look at it again.

## The two constraints that matter most

**`require-image-policy`** — an image must be pinned by digest and come from an approved registry. Binary Authorization separately requires the build, vulnerability, qualification, and any required biosecurity attestations. The two controls have deliberately distinct responsibilities.

**`deny-holdout-bucket-mount`** — no training workload may mount the held-out evaluation
bucket. Benchmark numbers are worthless if the holdout set leaked into training, and the leak
is invisible afterwards: the model just looks better than it is. There is also an IAM DENY
policy on the bucket in `infrastructure-live`. Two independent controls, because this one
cannot be detected after the fact.

## Testing a constraint before shipping it

```sh
nix develop
gator test \
  --filename=policy/templates \
  --filename=policy/constraints \
  --filename=rendered/development
```

**`gator`, not `conftest`.** The Rego here is embedded inside YAML ConstraintTemplates, so
`conftest test --policy policy/` finds no `.rego` files and errors with "no policies found" —
it evaluates nothing while appearing to run. `gator` is Gatekeeper's own evaluator: it loads
templates and constraints exactly as the cluster does, so it also catches a template the
cluster would reject.

For the last word, a server dry-run runs the real admission webhook:

```sh
kubectl apply --dry-run=server -f rendered/development/<app>/
```

### A note on Rego dialect

Use `import future.keywords.{if,contains,in}`, **not** `import rego.v1`. Gatekeeper validates
ConstraintTemplate imports against an allowlist and rejects `rego.v1` with
`invalid ConstraintTemplate: invalid import`. `future.keywords` gives the same modern syntax
and loads. `gator test` is how you find out which is true for your Gatekeeper version.
