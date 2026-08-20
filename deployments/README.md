# Artifact deployment selections

These files own the environment-specific choice of immutable deployable artifacts. They do not
own replicas, quotas, endpoints, or application source.

An activated application entry has this shape:

```yaml
- name: serving-api
  images:
    - repository: us-central1-docker.pkg.dev/mindclade-production/containers/api
      digest: sha256:<64-lowercase-hex>
      releaseMetadata: releases/<release-id>.json
```

The renderer rejects every workload image that lacks an entry and every entry that did not match
the rendered application. Promotion copies the application entry—not rendered Kubernetes YAML—so
staging and production keep the same digest while retaining their own scale and configuration.
Every changed target entry must exactly match the adjacent source environment and reference a
complete release record. An unchanged production entry may lag while staging qualifies the next
release.
