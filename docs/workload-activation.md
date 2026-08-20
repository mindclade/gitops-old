# Workload activation

The control plane is intentionally deployable before product workloads.

A workload becomes GitOps desired state only when one change can prove all of the following:

1. the source exists at the pinned monorepo release;
2. the built artifact is referenced by immutable digest;
3. checksummed SBOM and provenance evidence exist for that digest;
4. independent Buildkite qualification, vulnerability, and numerical results satisfy release policy;
5. the protected signer has verified the build and qualification occurrences and issued the
   governed Binary Authorization deployment attestation;
6. `python3 scripts/render.py --monorepo <path>` reproduces the committed render;
7. the matching AppProject already permits only the required destination and resource kinds.

Planned services that do not meet those gates remain in the monorepo and are **not** listed in
`render-manifest.yaml`. GitOps does not carry `:latest`, unbuilt-image exceptions, or inactive
render directories for topology documentation.
