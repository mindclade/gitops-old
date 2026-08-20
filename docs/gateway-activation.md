<!-- Copyright © 2026 Mindclade, LLC. All Rights Reserved. Mindclade Proprietary and Confidential. SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary -->

# Gateway and TLS activation

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
