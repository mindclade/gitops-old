<!-- mindclade-doc: changelog@1 -->

# Mindclade changelog · GitOps control plane

This file records material repository changes from the adoption of the
estate-wide changelog contract. Earlier history remains available in Git and is
not reconstructed or relabeled here.

## Unreleased

### Added

- Added canonical deployment bundles, policy-bound evidence records, and a protected
  production-eligibility decision flow with independent Cloud KMS Ed25519 verification and
  immutable decision publication.
- Restored a tested source-authority gate that freezes the sole legacy monorepo GitOps package
  to `v0.1.1` and requires new render targets to use reusable `infra/kubernetes/**` packages.
- Added the exact estate-wide `LEGAL.md` reliance policy and made it part of
  the repository contract.
- Preserved and digest-pinned the upstream Apache-2.0 license texts beside the
  vendored ARC 0.14.2 charts and cert-manager v1.19.1 release.

### Changed

- Updated the proprietary license with the protected-disclosure notice and
  recorded the Contributor Covenant 2.1 attribution and modifications.
- Moved the reusable SPDX source-header template under `.github/` so `LICENSE`
  is the sole root license surface.

### Fixed

### Security

- Clarified that security response times are non-contractual operational
  targets and that safe harbor cannot authorize third-party systems or
  unlawful conduct.

### Removed

## 2026-08-21 — Common-document governance baseline

### Added

- established local, versioned contribution, security, support, conduct,
  governance, license, notice, and changelog documents;
- added machine-enforced presence and content requirements for those documents.

### Changed

- aligned the root documentation with the Mindclade MONO brand and repository
  authority contract;
- standardized proprietary rights, contributor authorization, third-party
  precedence, and support routing across the governed repository estate.

### Security

- made private vulnerability reporting and the absence of a published PGP key
  explicit;
- prohibited secrets, sensitive evidence, customer data, model material, and
  restricted biological content in public or general-purpose channels.
