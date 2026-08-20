<!-- mindclade-doc: canonical-pointer@1 -->

# Mindclade Enterprise Platform Foundation Blueprint

> **Platform Foundation · Canonical architecture pointer**
> Use the organization-wide blueprint for trust rings, repository authority, production
> invariants, and acceptance gates.

The canonical blueprint is maintained in
[`mindclade/.github`](https://github.com/mindclade/.github/blob/main/docs/MINDCLADE_ENTERPRISE_PLATFORM_FOUNDATION_BLUEPRINT.md).
This compatibility page preserves the established path without duplicating a long-lived
architecture contract that could drift between repositories.

## GitOps-specific guidance

- [GitOps architecture](architecture.md) defines the current reconciliation and trust model.
- [Repository production blueprint](../BLUEPRINT.md) is the compact authority contract.
- [Documentation home](README.md) routes activation, promotion, policy, and recovery work.

When repository behavior and the enterprise target differ, treat code, tests, rendered-state
validation, `contracts/repository.yaml`, and repository-specific documentation as current
evidence; the enterprise blueprint remains the approved target architecture.
