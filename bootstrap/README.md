# Argo CD bootstrap

Argo CD v3.5.1 is vendored byte-for-byte from the official release. Both the standard and HA
manifests have committed SHA-256 files and must not be hand-edited. Production requires the HA
profile after the production cluster has sufficient multi-zone capacity.

The ARC CI control plane is deliberately not bootstrappable yet. Its reusable-workflow v4
release, bootstrap identity contract, infrastructure module release, and applied CI cluster must
all be qualified first. The repository retains the inactive ARC source and release validators,
but exposes no CI bootstrap configuration, root Application, or AppProject until that coordinated
activation change is reviewed.

The upstream payloads name versioned container tags. Both cold-start and self-management render
them through `components/immutable-images`, whose manifest-list digests are bound to the exact
upstream tags in `argocd-install.provenance.json`. The bootstrap script refuses any rendered Argo
install profile that still contains a non-digest image reference.

The bootstrap process needs five temporary files supplied through a protected operator or
Secret Manager workflow:

```text
ARGOCD_DEX_GITHUB_CLIENT_ID_FILE
ARGOCD_DEX_GITHUB_CLIENT_SECRET_FILE
ARGOCD_GITHUB_APP_PRIVATE_KEY_FILE
ARGOCD_GITHUB_APP_ID_FILE
ARGOCD_GITHUB_APP_INSTALLATION_ID_FILE
```

Each file must be mode 0400, 0440, 0600, or 0640. Values are never committed or passed as
command-line literals. The GitHub OAuth app provides Argo CD login through the governed
Mindclade organization and teams. The GitHub App has read-only access to the private `gitops`
repository.

Dex emits GitHub team groups using the configured lower-case organization login, for example
`mindclade:platform`. RBAC and AppProject role mappings use that exact claim form. Changing the
organization name or connector changes an authentication boundary and must be rehearsed while a
protected cluster-admin recovery path remains available.

The selected command profile must match `applications/<environment>/argocd.yaml`. The script
fails when cold-start intent and ongoing Git desired state disagree, preventing an HA bootstrap
from immediately reconciling into a standard/hybrid installation (or the reverse).

Run:

```bash
./bootstrap/bootstrap.sh --apply --environment ci --profile standard --context mindclade-ci-arc
./bootstrap/bootstrap.sh --apply --environment development --profile standard --context mindclade-development
./bootstrap/bootstrap.sh --apply --environment staging --profile standard --context mindclade-staging
MINDCLADE_PRODUCTION_BOOTSTRAP_CONFIRM=production \
  ./bootstrap/bootstrap.sh --apply --environment production --profile standard --context mindclade-production
```

The script verifies the exact kube context, upstream checksum, and digest-only rendered install;
requires restrictive credential-file permissions; waits for CRDs and core Argo workloads; merges
OAuth and GitHub App credentials without committing them; applies the least-privilege bootstrap
AppProject; disables local admin through the hardened environment configuration; removes the
upstream one-time local-admin Secret; and creates the environment-specific root Application.
Production additionally requires an explicit confirmation value. Terraform never installs Argo
CD.

After cold start, the root creates `argocd-self-management` in the tightly scoped
`argocd-administration` AppProject. That Application reconciles either
`bootstrap/profiles/standard` or `bootstrap/profiles/ha`; it excludes the SSO/RBAC ConfigMaps and
credential-bearing Secrets because those objects have separate owners. The administration project
has no Secret authority. Upgrades are protected Git changes, not repeated ad hoc applies of the
bootstrap payload.

The root Application intentionally has no resource-deletion finalizer. Losing or deleting the
composition object must stop reconciliation, not cascade through ApplicationSets into running
workloads. Environment ApplicationSets likewise preserve managed resources on deletion; planned
retirement is a separate reviewed prune/decommission operation.

## Standard versus HA

The production bootstrap does **not** force the upstream HA manifest onto a cluster that
cannot support it. Use `standard` for a small startup production cluster. Use `ha` only after
the cluster has at least three schedulable nodes across three zones; `bootstrap.sh` verifies
that topology and fails closed when it is absent. Promotion from standard to HA is a reviewed
GitOps/operations change to the environment's self-management Application and must be rehearsed
in staging first. See `docs/argocd-upgrade.md`.
