# Deployment release selections

The three files in this directory are the only environment-specific artifact authority. Each
uses the `mindclade.dev/v2` `ArtifactDeploymentSet` contract and binds an active rendered
application to exactly one immutable release metadata record:

```yaml
apiVersion: mindclade.dev/v2
kind: ArtifactDeploymentSet
metadata:
  name: staging
spec:
  environment: staging
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

Selections promote unchanged through development, staging, and production. Empty application
lists are intentionally valid while no workload has completed release qualification.
