<!-- mindclade-doc: reference@1 -->

# Artifact deployment selections

> **Audience:** Release owners and GitOps reviewers
> **Outcome:** Select an immutable artifact for one environment without changing workload
> source, scale, endpoints, or configuration ownership.

## Contract

Each `deployments/<environment>.yaml` document is a
`mindclade.dev/v1` `ArtifactDeploymentSet`. It binds an active rendered application to one or
more Artifact Registry repositories, exact SHA-256 digests, and repository-local release
records.

During the v4 quarantine, the three committed documents use an empty `mindclade.dev/v2`
compatibility envelope so the trusted-main provenance validator can inspect the downgrade. The
v3 release metadata contract remains authoritative, and the validator rejects any application in
that v2 envelope. Populating it requires the separately coordinated release-contract migration.

```yaml
apiVersion: mindclade.dev/v1
kind: ArtifactDeploymentSet
metadata:
  name: development
spec:
  environment: development
  applications:
    - name: serving-api
      images:
        - repository: us-central1-docker.pkg.dev/mindclade-development/containers/api
          digest: sha256:<64-lowercase-hex>
          releaseMetadata: releases/<release-id>.json
```

Applications and image repositories must be sorted and unique. Every application must also be
active for the same environment in `render-manifest.yaml`; every release record must bind the
selected `repository@digest` exactly.

## Promotion rule

Promotion copies the application selection—not rendered Kubernetes YAML—between adjacent
environments. The target keeps its own replicas, quotas, endpoints, and policy while using the
same qualified digest. A changed staging selection must match development; a changed production
selection must match staging. An unchanged target may lag while the next release qualifies.

## Validate

From the repository root:

```sh
python3 scripts/validate-deployment-selections.py
python3 scripts/validate-release-metadata.py
python3 scripts/render.py --monorepo ../mindclade-internal-monorepo
```

Review the rendered diff and release evidence before promotion. GitOps does not manufacture a
missing digest, release record, attestation, or qualification result.

See [release metadata](../releases/README.md), [workload activation](../docs/workload-activation.md),
and [architecture](../docs/architecture.md).
