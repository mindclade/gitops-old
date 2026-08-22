<!-- mindclade-doc: concept@1 -->

# Render source authority boundary

The committed `platform-core` output is a frozen transition render from the protected
`mindclade/mindclade-internal-monorepo` tag `v0.1.1`. That immutable tag contains
`infra/gitops/environments/{env}`; its reviewed output is already committed here, and this
repository remains the live desired-state authority consumed by Argo CD.

Current monorepo work does not add live GitOps composition or GitOps environment overlays. New
render targets use packages under `infra/kubernetes/`, while target selection, release binding,
rendered output, and promotion remain in this repository. The production-contract validator
freezes the historical source path to exactly `v0.1.1`, rejects any new `infra/gitops/**` target,
and rejects environment-specific composition beneath an `infra/kubernetes/**/overlays` or
`infra/kubernetes/**/environments` path.

To retire the transition path:

1. publish a protected monorepo release containing a reusable Kubernetes package;
2. reproduce `platform-core` through the canonical renderer and review the complete generated
   delta;
3. update `render-manifest.yaml` to the new immutable release and package;
4. qualify development and staging before promoting independently rendered production output;
   and
5. remove the exact legacy-path exception and its regression tests in the same reviewed change.

Do not recreate new `infra/gitops/**` packages or live environment overlays in the monorepo to
preserve the old render path.
