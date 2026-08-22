# Mindclade · Agent operating guide

## Purpose and authority

This repository owns Argo CD installation/configuration, Kubernetes desired state, admission
policy, immutable artifact selection, promotion, freeze controls, and rendered review output.
Read BLUEPRINT.md, README.md, CONTRIBUTING.md, and docs/architecture.md before editing.
Infrastructure-live owns cloud prerequisites; the monorepo owns workload source and artifacts.

## Working rules

- Never hand-edit rendered output; change its source and regenerate deterministically.
- Production images and model artifacts use immutable digests with release evidence.
- Preserve deny-all/default project boundaries, destination/source allowlists, partner and
  holdout isolation, and time-bounded exemptions.
- Do not sync Argo CD, apply kubectl, mutate a cluster, promote an artifact, freeze/unfreeze
  production, or use kubeconfig/Argo credentials from an agent session.
- Secrets in Git are references only; never add secret payloads or private keys.

## Validation

    nix develop .#ci --command make validate
    nix flake check --no-update-lock-file

Connected Argo reconciliation, admission, rollback, freeze, and disaster-recovery evidence must
come from the protected environment.

## Done

Render, policy, RBAC, release metadata, artifact selection, bootstrap checksum, shell, and
repository contracts pass; promotion and rollback consequences are documented.
