<!-- mindclade-doc: how-to@1 -->

# Activate a workload

> **Audience:** release owners adding a product workload to GitOps desired state.
> **Outcome:** commit a reproducible, policy-compliant render that references only a qualified
> immutable artifact.
> **Risk:** high—activation changes reconciled workload intent and can affect production service.

The control plane is intentionally deployable before product workloads.

A workload becomes GitOps desired state only when one change can prove all of the following:

1. the source exists at the pinned monorepo release;
2. the built artifact is referenced by immutable digest;
3. checksummed SBOM and provenance evidence exist for that digest;
4. independent ARC qualification, vulnerability, and numerical results satisfy release policy;
5. the protected signer has verified the build and qualification occurrences and issued the
   governed Binary Authorization deployment attestation;
6. `python3 scripts/render.py --monorepo <path>` reproduces the committed render;
7. the matching AppProject already permits only the required destination and resource kinds.

Planned services that do not meet those gates remain in the monorepo and are **not** listed in
`render-manifest.yaml`. GitOps does not carry `:latest`, unbuilt-image exceptions, or inactive
render directories for topology documentation.

The ARC CI control plane and DR-evidence caller follow the same rule. Their v4 contract and
validators remain reviewable source, but this repository does not publish a CI root, CI
Application, ARC AppProject, CI bootstrap configuration, or DR caller until the immutable
workflow/module releases and applied identity handoffs are qualified together.

## Procedure

1. Confirm the workload package exists at the exact protected monorepo release consumed by this
   repository.
2. Add the immutable 4.0 release record that binds the subject, named images, typed artifacts,
   evidence policy and qualification epoch, independent attestors, compatibility, migration,
   and exact rollback lineage. Verify its governed Binary Authorization deployment attestation.
3. Verify the target AppProject already permits only the required destination, namespace, and
   resource kinds. Submit a separate reviewed scope change if it does not.
4. Add the workload source to `render-manifest.yaml` and select that one release record for the
   intended application and environment. Do not restate images or artifacts in the selection.
5. Reproduce generated content with the canonical renderer:

   ```sh
   python3 scripts/render.py --monorepo <path-to-pinned-monorepo-checkout>
   ```

6. Review every generated delta and run the full contract:

   ```sh
   nix develop .#ci --command make validate
   ```

7. Merge through the protected environment path and observe development before promoting the same
   qualified digest through staging and production.

## Verify

- The committed render is reproducible and contains no mutable image reference.
- Argo CD reports the workload healthy and synchronized in the intended environment only.
- Binary Authorization admits the exact digest and retains the evidence linkage.
- Service, metrics, alerts, and rollback behavior meet the release acceptance criteria.

If admission or reconciliation fails, do not weaken policy. Preserve the digest and commits and
follow [Failed Argo CD sync](failed-sync.md).

## Roll back or recover

Revert the smallest selection/promotion commit only when the previous artifact remains compatible
with current data and configuration. Otherwise use a reviewed forward fix. Follow
[deployment rollback](rollback.md) and preserve the failed digest and qualification evidence.
