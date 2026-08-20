<!-- mindclade-doc: documentation-home@1 -->

# Mindclade · GitOps documentation

> **Platform Foundation · Kubernetes operations**  
> Architecture, activation, promotion, recovery, and security guidance for the GitOps
> control plane.

| Need | Document | Page type |
| --- | --- | --- |
| Understand repository and cluster boundaries | [Architecture](architecture.md) | Architecture |
| Import and activate the repository | [Initial import](initial-import.md) | How-to |
| Activate a workload | [Workload activation](workload-activation.md) | How-to |
| Activate gateway and TLS | [Gateway activation](gateway-activation.md) | How-to |
| Upgrade Argo CD | [Argo CD upgrade](argocd-upgrade.md) | How-to |
| Handle an Argo reconciliation failure | [Failed sync](failed-sync.md) | Runbook |
| Revert a deployment safely | [Rollback](rollback.md) | Runbook |
| Rebuild the GitOps control plane | [Disaster recovery](disaster-recovery.md) | Runbook |
| Handle Kubernetes secret references | [Secrets](secrets.md) | Reference |
| Roll out and test admission policy | [Policy guide](../policy/README.md) | How-to and reference |
| Understand the complete platform | [Enterprise platform blueprint](MINDCLADE_ENTERPRISE_PLATFORM_FOUNDATION_BLUEPRINT.md) | Blueprint |

For an active incident, start with the symptom-specific runbook. Do not use bootstrap or
direct `kubectl` edits as an ordinary deployment path.
