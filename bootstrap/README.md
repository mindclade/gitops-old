# Argo CD bootstrap

Argo CD v3.5.1 is vendored byte-for-byte from the official release. Both the standard and HA
manifests have committed SHA-256 files and must not be hand-edited. Production requires the HA
profile after the production cluster has sufficient multi-zone capacity.

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

Run:

```bash
./bootstrap/bootstrap.sh development standard mindclade-development
./bootstrap/bootstrap.sh staging standard mindclade-staging
MINDCLADE_PRODUCTION_BOOTSTRAP_CONFIRM=production \
  ./bootstrap/bootstrap.sh production ha mindclade-production
```

The script verifies the exact kube context and upstream checksum, requires restrictive credential-file permissions, waits for CRDs and core Argo workloads, merges OAuth and GitHub App credentials without committing them, applies the least-privilege bootstrap AppProject, disables local admin through the hardened environment configuration, and creates the environment-specific root Application. Production additionally requires an explicit confirmation value. Terraform never installs Argo CD.

## Standard versus HA

The production bootstrap does **not** force the upstream HA manifest onto a cluster that
cannot support it. Use `standard` for a small startup production cluster. Use `ha` only after
the cluster has at least three schedulable nodes across three zones; `bootstrap.sh` verifies
that topology and fails closed when it is absent. Promotion from standard to HA is a reviewed
GitOps/operations change and should be rehearsed in staging first.
