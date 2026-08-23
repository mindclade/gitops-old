# Production qualification evidence

Requests under `qualification/requests/` bind final production qualification to exact commits,
protected workflow-run artifacts, module releases, staging/production mutations, and DR evidence.
Each request is pull-request reviewed on protected `main`; no request is evidence by itself.

The protected workflow checks out exactly seven repositories, requires every commit to be reachable
from its protected main branch, downloads the named GitHub Actions artifacts through the read-only
qualification App, verifies every declared SHA-256 digest, creates deterministic sanitized source
archives, and publishes the independently verified bundle to the append-only GCS archive.

Do not place state, plans, credentials, tokens, kubeconfigs, secret values, holdout data, partner
data, or sensitive logs in a request or evidence artifact. A missing, expired, changed, or
unreadable artifact blocks qualification.

## Workstation image boundary

`workstation-image-readiness.yaml` records the cross-repository source and connected gates for
the immutable development workstation image. GitOps is evidence-only for this capability: it does
not build the image, publish the raw disk, create the Compute Image, provision the VM, or reconcile
any of those resources through Argo CD. Those authorities remain in `.github`, the internal
monorepo, `bootstrap`, and `infrastructure-live`.

The checked-in state is `qualifying`: the source contracts pass, while every applied or connected
claim remains false and both Argo reconciliation and product activation remain prohibited. Move
those fields only in a separately reviewed evidence transition after the exact protected runs and
applied outputs exist. The transition must include the atomic `github-config` source tuple at
`qualified-v1`; an object URI or digest copied directly into `infrastructure-live` is not evidence.
