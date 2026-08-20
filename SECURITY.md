# Security

**Do not open a public issue for a vulnerability.**

| Channel | For |
|---|---|
| [Private security advisory](https://github.com/mindclade/gitops/security/advisories/new) | Anything in this repository. Preferred |
| `security@mindclade.com` | The same, by email. PGP key in the canonical policy |
| `biosecurity@mindclade.com` | Screening bypasses, unsafe model behaviour |

Acknowledgement within 2 business days, triage within 5. Good-faith research is covered by
safe harbour.

**The full policy — scope, SLAs, PGP key, safe-harbour text — is the canonical one:**
[`mindclade/.github/SECURITY.md`](https://github.com/mindclade/.github/blob/main/SECURITY.md).

This file exists because the `.github` repo is **internal**, and GitHub only inherits
community health files from a *public* one. Nothing is inherited here, so every repository
carries its own. Deliberately short — a duplicated hundred-line policy goes stale in every
copy but one.

## Specific to `gitops`

`rendered/` is applied directly to production clusters by ArgoCD. A manifest change here is a cluster change. Anything that bypasses admission policy — an exemption, a constraint downgrade, an unsigned image — is a security report, not a bug report.

Never commit credentials, private keys, out-of-band sensitive configuration, customer data, model
weights, or restricted biological sequences. The `push-blocklist` org ruleset rejects the
common shapes at push time, before the object reaches a branch — but it is not exhaustive.

If you commit a secret, **rotate it first**, then clean the history. Rewriting history is not
remediation: the value was already exposed to every clone, fetch, and webhook subscriber.

## Proprietary header policy

First-party configuration and policy files in this repository use a shared comment header block.
It is defined once in `license-header.txt` at the workspace root:

```text
# Copyright © 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

```

The pre-commit hook enforces this header automatically:

```sh
pre-commit install
pre-commit run --all-files mindclade-license-header
```

These checks intentionally skip generated/lock artifacts (`rendered/`, `.terraform/`,
`.terragrunt-cache/`, and `*.lock.hcl`).
