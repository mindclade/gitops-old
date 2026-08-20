# GitOps disaster recovery

1. Recreate cloud and GKE prerequisites through `bootstrap` and `infrastructure-live`.
2. Verify the appropriate Argo CD install checksum.
3. Provision the OIDC/repository credential secret references.
4. Run `bootstrap/bootstrap.sh <environment> <standard|ha>`.
5. Confirm the root application reconciles projects before workload applications.
6. Restore stateful application data from its authoritative backup system.
7. Validate policy, provenance, serving, data, and research health.
