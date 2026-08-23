# Deployment release selections

The three files in this directory are the only environment-specific artifact authority. Each
uses the `mindclade.dev/v3` `ArtifactDeploymentSet` contract and binds an active rendered
application to exactly one immutable release metadata record:

```yaml
apiVersion: mindclade.dev/v3
kind: ArtifactDeploymentSet
metadata:
  name: staging
spec:
  environment: staging
  qualificationState: null
  qualificationHandoff: null
  applications:
    - name: serving-api
      releaseMetadata: releases/serving-api/release-2026-08-20.json
```

The referenced 4.0 record owns the complete release subject: named digest-pinned images,
typed content-addressed artifacts, qualification evidence, attestors, compatibility, migration,
and rollback lineage. A deployment selection may not restate any of those fields.

The renderer replaces each manifest image from the record by repository. Explicit non-image
release inputs use these tokens in quoted YAML scalars:

- `mindclade-artifact-uri://<artifact-name>` selects the artifact URI.
- `mindclade-artifact-digest://<artifact-name>` selects its SHA-256 digest.
- `mindclade-release://release-id` selects the release ID.
- `mindclade-release://subject-digest` selects the release subject digest.

Selections promote unchanged through development and staging. Promotion to production writes a
non-reconcilable `staged-v1` selection with no handoff. The protected qualification workflow
renders that staged candidate, signs its exact tree digest, and emits a sanitized activation
artifact. The activation pull request atomically commits the candidate render, handoff, and
`qualified-v1` state. Empty application lists remain `blocked-v1`; nonproduction uses `null`.

A `qualified-v1` production selection requires `qualificationHandoff` to name one sanitized claim
under `qualification/handoffs/`. That claim binds the stable selection-subject and candidate-render
digests, all seven repository commits, an immutable evidence-object generation, the signed
eligibility decision, the pinned Ed25519 public-key fingerprint, and the rollback target. Ordinary
rendering refuses `staged-v1`; only the protected qualification candidate mode may render it.

The handoff expires after at most six hours. The stable `production-handoff-gate` pull-request
check runs protected-base tooling, treats the head only as data, and re-fetches the exact GCS object
generation. The merge-queue check has no cloud identity and repeats signature, expiry, selection,
and committed-render validation with protected-base tooling. Governance must make that context
required before activation. Expiry prevents a new promotion; it does not turn evidence freshness
into an automated production deletion.
