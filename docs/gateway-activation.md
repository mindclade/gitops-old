<!-- Copyright © 2026 Mindclade, LLC. All Rights Reserved. Mindclade Proprietary and Confidential. SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary -->

<!-- mindclade-doc: how-to@1 -->

# Activate Gateway and TLS

> **Audience:** platform operators enabling public ingress for an environment.
> **Outcome:** reconcile Gateway resources only after their controller, DNS, certificate, and
> cloud prerequisites have been qualified.

The public Gateway/TLS path is intentionally **inactive by default** in this repository.

The pinned monorepo release currently exposes Gateway and cert-manager Kustomize sources, but
GitOps must not reconcile custom resources whose controller or cloud-side certificate ownership
has not been qualified. `render-manifest.yaml` therefore activates only the environment/platform
baseline until this gate is completed.

Activate Gateway/TLS only after all of the following are true:

1. `infrastructure-live` owns and has applied the required public DNS, reserved VIP, IAM, and
   certificate prerequisites for the selected certificate strategy.
2. If cert-manager is retained, `gitops` owns a pinned, checksummed, licensed, and staged
   cert-manager controller/CRD installation. If Google Certificate Manager is selected instead,
   remove the cert-manager custom resources from the monorepo Gateway package.
3. Development and staging prove certificate issuance/renewal, Gateway programming, DNS
   authorization, rollback, and loss/re-bootstrap behavior.
4. The production Gateway references only qualified certificate resources and no plaintext
   private keys are committed to Git.
5. The reviewed `render-manifest.yaml` change activates the Gateway source and generated output
   is committed by the canonical renderer.

This gate prevents Argo CD from applying `Certificate`/`ClusterIssuer` resources before their CRDs
exist or from programming a Gateway that references certificate secrets that can never be
created.

## Procedure

1. Record the selected certificate ownership strategy and the exact infrastructure and GitOps
   commits in the change.
2. Prove the prerequisites above in development, including DNS authorization, issuance, renewal,
   controller restart, and rollback.
3. Add the reviewed Gateway source to `render-manifest.yaml` and generate the canonical output:

   ```sh
   python3 scripts/render.py --monorepo <path-to-pinned-monorepo-checkout>
   nix develop .#ci --command make validate
   ```

4. Merge through the protected path, observe Argo reconciliation, and verify the reserved address,
   Gateway status, certificate status, DNS answers, TLS chain, and application health.
5. Repeat the qualification in staging before promoting the same strategy to production.

## Rollback

Revert the reviewed render selection only when doing so leaves compatible CRDs and controller
state. Restore the last known-good DNS/Gateway target through its owning repository and verify
external resolution and TLS. Never commit a private key or replace a failed certificate gate with
plaintext Kubernetes Secret data.
