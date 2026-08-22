<!-- mindclade-doc: documentation-home@1 -->

# Mindclade · GitOps documentation

> **Platform Foundation · Kubernetes operations**  
> Understand, activate, operate, and recover environment-scoped Argo CD desired state.

## Choose your path

| If you need to... | Start with | You will... |
| --- | --- | --- |
| Understand reconciliation and trust | [Architecture](architecture.md) | Learn repository, cluster, policy, and promotion boundaries |
| Import or activate the control plane | [Initial import](initial-import.md) | Validate generated state and bootstrap one environment |
| Activate a workload | [Workload activation](workload-activation.md) | Prove artifact, policy, and destination readiness |
| Diagnose reconciliation failure | [Failed sync](failed-sync.md) | Classify the owner and repair the authoritative source |
| Make an emergency frozen change | [Freeze and emergency](freeze-and-emergency.md) | Authorize one reviewed merge and audited sync without a standing bypass |
| Qualify production Argo CD | [Production qualification](production-qualification.md) | Separate source checks from applied policy, admission, recovery, and freeze evidence |
| Recover Argo CD | [Disaster recovery](disaster-recovery.md) | Recreate the control plane from pinned Git state |
| Revoke a compromised artifact | [Compromised artifact revocation](compromised-artifact-revocation.md) | Freeze promotion, deny the digest, and restore a last-known-good selection |

## Getting started

- [Initial import and activation](initial-import.md) — validate the repository and activate
  environments in dependency order.
- [Workload activation](workload-activation.md) — introduce a qualified immutable artifact.
- [MLflow activation](mlflow-activation.md) — render the activation-gated Helm service without
  transferring release or serving authority to MLflow.
- [Gateway and TLS activation](gateway-activation.md) — enable public routing only after its
  controller, cloud, certificate, and rollback gates are met.

## Concepts and architecture

- [Architecture](architecture.md) — control-plane composition, environment isolation, and
  promotion flow.
- [Render source authority boundary](source-boundary-migration.md) — keep live GitOps
  composition here while retiring the frozen monorepo transition package.
- [Argo CD bootstrap](../bootstrap/README.md) — pinned installation, protected credentials,
  and standard-versus-HA profiles.
- [Artifact deployment selections](../deployments/README.md) — environment digest selection
  and adjacent-environment promotion rules.

## Operations

- [Failed sync](failed-sync.md) — read-only triage and Git-mediated repair.
- [Freeze and emergency change](freeze-and-emergency.md) — operate the independent GitHub and
  Argo deny gates without granting a standing manual-sync bypass.
- [Rollback](rollback.md) — restore the last compatible reviewed digest.
- [Argo CD upgrade](argocd-upgrade.md) — qualify and promote pinned standard and HA payloads.
- [Production qualification](production-qualification.md) — close applied policy, admission,
  rollback, freeze, and recovery evidence without promoting workloads.
- [Disaster recovery](disaster-recovery.md) — rebuild Argo CD without changing workload intent.
- [Compromised artifact revocation](compromised-artifact-revocation.md) — contain a suspect digest,
  revoke deployment eligibility, and prove workload replacement.
- [Policy guide](../policy/README.md) — stage, test, and enforce admission policy.

## Reference and governance

- [Secret handling](secrets.md) — references allowed in Git and prohibited payloads.
- [Release metadata](../releases/README.md) — immutable artifact evidence contract.
- [Vendored policy provenance](../policy/templates/vendor/README.md) — upstream pinning,
  supported workload shapes, and update verification.
- [Repository production blueprint](../BLUEPRINT.md) — compact authority and exclusion contract.
- [Enterprise platform blueprint](MINDCLADE_ENTERPRISE_PLATFORM_FOUNDATION_BLUEPRINT.md) —
  stable pointer to the canonical estate-wide contract.

## Source of truth

`render-manifest.yaml`, environment selections under `deployments/`, generated `rendered/`
state, roots, ApplicationSets, AppProjects, policy tests, release schemas, protected workflows,
and `contracts/repository.yaml` are authoritative. Never hand-edit generated output.

## Validate documentation changes

Run from the repository root:

```sh
nix develop .#ci --command make validate
```

Also render changed sources from the pinned monorepo checkout when practical, check local links,
and preview Markdown before merge. New pages follow the canonical
[Mindclade documentation templates](https://github.com/mindclade/.github/tree/main/docs/templates).
