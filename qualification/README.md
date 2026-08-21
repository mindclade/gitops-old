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
