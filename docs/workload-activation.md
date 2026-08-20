# Workload activation

The control plane is intentionally deployable before product workloads.

A workload becomes GitOps desired state only when one change can prove all of the following:

1. the source exists at the pinned monorepo release;
2. the built artifact is referenced by immutable digest;
3. SBOM and SLSA provenance attestations exist for that digest;
4. qualification and vulnerability results satisfy release policy;
5. the Binary Authorization attestation exists;
6. `scripts/render.sh --check` reproduces the committed render;
7. the matching AppProject already permits only the required destination and resource kinds.

Planned services that do not meet those gates remain in the monorepo and are **not** listed in
`render-manifest.yaml`. GitOps does not carry `:latest`, unbuilt-image exceptions, or inactive
render directories for topology documentation.
