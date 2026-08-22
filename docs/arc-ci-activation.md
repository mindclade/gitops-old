<!-- mindclade-doc: operations-runbook@1 -->

# Activate ARC presubmit capacity

> **Audience:** CI platform, GitHub governance, security, and cluster operators
> **Outcome:** Route presubmit jobs to a separate, ephemeral ARC scale set without granting
> release, signing, push, or cache-write authority.
> **Risk:** critical—activation allows pull-request code to execute on a Mindclade-managed runner.

## Current state

`arc/presubmit-readiness.yaml` is the machine-readable activation authority. It is intentionally
`blocked`, has `selected: false`, and configures `minRunners: 0` and `maxRunners: 0`.
`arc/rendered/presubmit.yaml` is an offline Helm review fixture only: it is absent from
`arc/rendered/kustomization.yaml`, no `arc-presubmit` namespace or secret sync exists, and no Argo
root can reach it. Merging the dormant source therefore cannot register or start a runner.

The fixture uses the digest already locked in the vendored ARC provenance solely to exercise the
chart. It is not the Mindclade CI image and cannot satisfy the `runnerImage` gate. Do not activate
that fixture.

## Authority boundaries

| Concern | Authority |
| --- | --- |
| Nix base and future Actions runner image | `mindclade-internal-monorepo` |
| Cache, cluster, workload identity, and secret prerequisites | `infrastructure-live` |
| Runner group and permitted workflow routing | `github-config` |
| Reusable workflow behavior | `.github` |
| ARC values, namespace policy, and Argo selection | `gitops` |

Keep `mindclade-arc-artifact-authority` and its canary, build, and qualification scale sets
unchanged. Presubmit uses `mindclade-arc-ci`; that group must have no workflow capable of signing
or publishing an artifact.

## Readiness evidence

Do not mark a gate qualified from source inspection. Each gate needs an immutable evidence object
with its URI, SHA-256, reviewer, and UTC timestamp in `arc/presubmit-readiness.yaml`.

1. **Nix binary cache:** a Linux `x86_64` runner substitutes every required CI shell from the
   protected cache, with no source build and with cache signatures verified.
2. **Runner image:** a monorepo Nix package extends `.#remote-execution-base`, includes the Actions
   runner and required CI shell closures, is published by the protected release lane, and is
   recorded by exact repository, digest, source commit, flake package, and release record.
3. **Runner group:** `mindclade-arc-ci` exists separately from artifact authority and permits only
   reviewed presubmit callers. Confirm with the live GitHub API whether authorization is evaluated
   against the calling workflow; do not infer this from catalog source.
4. **Read-only cache WIF:** the runner identity can read the Bazel and Nix caches but cannot write
   them, push packages or images, create attestations, use signing keys, or impersonate release
   identities.
5. **Connected cluster:** the target cluster, ARC controller, workload identity, network policy,
   Secret Sync CRDs, and bounded resource capacity pass connected qualification.
6. **Workflow routing:** an internal test repository proves the exact scale-set label accepts the
   permitted workflow and rejects an unlisted workflow, a fork, and an artifact-authority job.

The GitHub App secret named in the chart is a controller registration credential. It is never
mounted into a runner pod. Runner pods use the chart-created no-permission service account,
disable service-account-token automount, run once with `restartPolicy: Never`, and have no shared
writable cache volume.

## Prepare the qualified source

Use a dedicated pull request while capacity and selection remain zero.

1. Fill `runnerImage.runnerFlakePackage`, `repository`, `digest`, `sourceCommit`, and
   `releaseRecord` from the protected runner-image evidence. Never invent a digest or reuse the
   validation fixture.
2. Point `arc/values/presubmit.yaml` at exactly `repository@digest` and update the ARC renderer so
   that image is accepted only when it matches the qualified readiness contract.
3. Attach evidence to each completed gate. Set `phase: qualified`; keep `selected: false`,
   `minRunners: 0`, and `maxRunners: 0`.
4. Reproduce and validate the source without cluster access:

   ```sh
   nix develop .#ci --command python3 scripts/render-arc.py --write
   nix develop .#ci --command make validate
   nix flake check --no-update-lock-file
   ```

5. Merge only after required checks pass. A qualified source still creates no namespace, runner
   registration, or pods.

## Protected canary activation

Use a second, approved change only after all six gates remain qualified.

1. In `github-config`, apply the separate `mindclade-arc-ci` group and its exact workflow
   allowlist. In `infrastructure-live`, apply the read-only cache identity and qualified cluster
   prerequisites through their protected plan/apply paths. Record applied outputs; do not copy raw
   credentials into Git.
2. Add the `arc-presubmit` namespace with restricted Pod Security labels, default-deny and required
   egress policies, and controller-only GitHub App Secret Sync resources following the existing ARC
   platform patterns.
3. Add the least-privilege CI AppProject, CI Argo configuration, root, and ARC Application at the
   exact paths enforced by `scripts/validate-arc-ci.py`. Add `presubmit.yaml` to
   `arc/rendered/kustomization.yaml` only in this activation change.
4. Set `phase: canary`, `selected: true`, `minRunners: 0`, and `maxRunners: 1`. Render, validate,
   review every generated object, and merge through the protected queue.
5. From an approved operator session, sync the reviewed commit. Run one non-publishing test job and
   prove the pod terminates after the job, no persistent volume exists, cache access is read-only,
   forbidden workflow routing is denied, and no signing or push credential is reachable.
6. Store the connected canary record at the restricted evidence boundary with the Git commit,
   image digest, workflow run ID, pod UID, timestamps, reviewer, and SHA-256.

Any missing object, queued job on the wrong scale set, unexpected credential, mutable image,
cache write, surviving pod, or shared storage is a stop condition. Revert the activation change;
do not weaken the validator or runner-group restriction.

## Scale to presubmit capacity

After the canary evidence is independently reviewed, use a third pull request to set
`phase: activated`, `minRunners: 2`, and `maxRunners: 24`. The minimum absorbs queue latency; the
maximum provides full-graph fanout and is intentionally higher than the release lane's maximum of
six. Do not increase the ceiling until the cluster quota, cache service, queue latency, and cost
evidence support it.

After merge and protected sync, observe at least one pull request and one merge-group full-graph
run. Confirm cache-hit rate, startup latency, CPU/memory saturation, pod deletion, rejected cache
writes, and hosted-runner fallback behavior before making the ARC label a required merge context.

## Roll back

First route workflows back to `ubuntu-24.04`. Then set `minRunners: 0`, `maxRunners: 0`, remove
`presubmit.yaml` from the ARC kustomization, and merge the reviewed GitOps rollback. Preserve the
runner image, logs, and evidence. Revoke the read-only runner identity or registration access only
through its owning repository after no job is running; never delete shared release-lane ARC
resources as part of a presubmit rollback.
