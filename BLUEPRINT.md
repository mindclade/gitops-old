# Mindclade · `gitops` production blueprint

**Repository class:** `production-control`  
**Visibility:** `internal`  
**Default branch:** `main`

## Authoritative responsibilities

- `argocd-installation`
- `argocd-configuration`
- `kubernetes-desired-state`
- `promotion`
- `admission-policy`

## Explicit exclusions

- `gcp-resource-provisioning`
- `container-builds`
- `application-source`
- `plaintext-secrets`

## Operating invariant

All changes are pull-request reviewed, subject to CODEOWNERS and required checks, merged through the configured queue for protected repositories, and performed by narrowly scoped identities. Live-system qualification evidence is separate from source completeness.
