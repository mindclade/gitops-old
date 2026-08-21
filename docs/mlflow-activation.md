<!-- mindclade-doc: how-to@1 -->

# Activate the MLflow mirror

> **Audience:** ML platform, security, database, and GitOps release owners.
> **Outcome:** reconcile an immutable, workspace-isolated MLflow mirror after its cloud and
> release evidence gates pass.
> **Risk:** high—this creates a SQL-backed metadata/security boundary and runs a schema migration.

MLflow is not active desired state. The GitOps renderer supports local Helm charts, but the target
is intentionally absent from `render-manifest.yaml` until all prerequisites are real. Do not add
placeholder values or render the monorepo qualification fixture into an environment.

## Preconditions

The proposed change must bind the exact monorepo release and MLflow image release record to:

- qualified private PostgreSQL, GCS artifact/archive prefixes, HA TLS Redis, Workload Identity,
  external Secret metadata, and identity-aware TLS ingress;
- successful Linux/amd64 image smoke, SBOM, provenance, signature, vulnerability, workspace
  isolation, migration/restore, artifact proxy, trace archival, Gateway budget/guardrail, load,
  disruption, and rollback evidence;
- environment values containing only observed hostnames, GSA, GCS prefixes, CIDRs, Secret name,
  and the immutable release evidence digest;
- an AppProject that permits only the required namespaced kinds. `research` explicitly permits
  GKE `PodMonitoring` and continues to forbid Secrets, quotas, limits, RBAC, and all cluster kinds.

## Source contract

Add one target per reviewed activation using this shape:

```yaml
- source: infra/kubernetes/platform/mlflow/chart
  renderer: helm
  values: infra/kubernetes/platform/mlflow/environments/{env}.yaml
  release: mindclade
  namespace: research-mlflow
  out: research-mlflow
  project: research
  environments: [development]
```

The renderer allows only a local chart and local values file from the pinned monorepo checkout,
requires release/namespace DNS labels, requires the Helm namespace to equal the GitOps application,
excludes incidental `crds/`, applies the selected release image digests, and records chart, values,
release, namespace, environment, and source ref in generated provenance headers.

The chart itself must continue to render zero objects without its environment values. The values
must enable the PreSync database migration and satisfy every non-placeholder activation guard.

## Procedure

1. Release the monorepo commit containing the image target, chart, environment values, and
   production-readiness evidence. Update the pinned source ref; never render a dirty checkout.
2. Add the governed release record for the exact `mlflow-server` digest and select it for
   `research-mlflow` in development only.
3. Add the target above and generate output with the pinned checkout:

   ```sh
   python3 scripts/render.py --monorepo <path-to-pinned-monorepo-checkout> --write
   nix develop .#ci --command make validate
   ```

4. Review all eight rendered objects, image substitution, PreSync hook, release evidence
   annotations, policies, and provenance. Confirm there is no Secret/RBAC/PVC/CRD/public Service.
5. Obtain an approved server-side diff in isolated development. Reconcile through Argo CD and
   observe the migration before the Deployment. Follow the monorepo MLflow runbook for acceptance.
6. Promote the same image/release graph to staging and production through adjacent-environment
   proposals only after each environment's distinct dependency and restore evidence passes.

Stop on a migration retry, missing release selection, mutable image, AppProject denial, unexpected
kind, workspace visibility failure, artifact direct-access URI, local budget strategy, SLO breach,
or non-empty post-sync drift. Do not weaken policy to make reconciliation proceed.

## Rollback

Before migration, revert the smallest target/selection change. After migration, use an older image
only if compatibility was proven against the migrated schema; otherwise stop writers and execute
the approved SQL restore plan before reconciling the prior render. GitOps rollback never rotates
credentials or deletes MLflow workspaces, artifacts, traces, CRDs, or cloud resources.
