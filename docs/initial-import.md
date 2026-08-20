# Initial import and activation

Import this tree into the corresponding existing Mindclade repository while preserving its `.git` directory. Use `main` as the default branch. Apply `.github` first and create its protected `v1` workflow-contract tag; apply `bootstrap` next; then `github-config`; then `infrastructure-live`; and finally `gitops`. Do not enable apply workflows until their OIDC identities, protected environments, and negative authorization tests are qualified.
