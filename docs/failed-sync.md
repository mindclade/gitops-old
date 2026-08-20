<!-- mindclade-doc: runbook@1 -->

# Failed Argo CD sync

> **Use when:** an Application is `OutOfSync`, `Degraded`, or repeatedly fails reconciliation.
> **Impact:** desired state or service health may be incomplete in the affected environment.
> **Primary owner:** the AppProject owner with platform support.
> **Escalate:** immediately for production impact, policy-control drift, or suspected credential use.

Use this runbook when an Application is `OutOfSync`, `Degraded`, or repeatedly failing to
reconcile. The normal repair path is a reviewed Git change; do not use an interactive sync or edit
live resources merely to make the dashboard green.

## Triage without mutation

Record the environment, Application, GitOps commit, first failure time, and owning AppProject.
Then collect:

```sh
kubectl get application -n argocd <application> -o yaml
kubectl describe application -n argocd <application>
kubectl get events -n argocd --sort-by=.lastTimestamp
kubectl logs -n argocd deployment/argocd-repo-server --since=30m
kubectl logs -n argocd statefulset/argocd-application-controller --since=30m
```

Do not attach Secret payloads, repository credentials, tokens, or sensitive workload data to an
issue. Redact evidence before sharing it outside the incident response group.

Classify the failure:

| Signal | Likely owner/action |
|---|---|
| Repository/authentication failure | Platform; verify the read-only GitHub App installation and Secret Manager rotation path |
| Render/path not found | GitOps/monorepo; reproduce with the pinned renderer and correct the reviewed source |
| AppProject destination/resource denial | Security/platform; fix the requested scope or reject the workload—do not broaden with `*` |
| Gatekeeper denial | Workload owner; correct the manifest or use the reviewed, expiring exemption process |
| Binary Authorization denial | Release owner; rebuild/qualify/attest the same digest or promote a new qualified digest |
| Missing CRD/controller | Platform; qualify and install the owning controller before its custom resources |
| Resource immutable or migration failure | Workload/infrastructure owner; choose reviewed replacement or forward recovery |
| Quota/capacity/scheduling failure | `infrastructure-live` owner; correct capacity without weakening workload policy |
| Secret reference not ready | Secret owner; repair the external source/IAM binding, never commit a Secret payload |

## Repair

1. Reproduce the failure from the exact Git commit with the pinned Nix toolchain:

   ```sh
   nix develop .#ci --command make validate
   nix develop .#ci --command kustomize build \
     --load-restrictor LoadRestrictionsNone roots/<environment>
   ```

2. Fix the authoritative source: the monorepo for workload packages, this repository for Argo and
   in-cluster desired state, or `infrastructure-live` for cloud prerequisites.
3. Open a protected pull request with the failure evidence, expected reconciliation delta, owner,
   and rollback/forward-recovery decision.
4. Allow Argo self-heal to reconcile the merged state. Observe health and Kubernetes events until
   the retry window completes.
5. Record the repairing PR/commit, Argo operation result, artifact digest, and service validation in
   the incident/change record.

## Emergency containment

An emergency live action requires the documented freeze/emergency bypass, an incident commander,
exact scope, and immediate reconciliation back into Git. Capture the pre-change object and audit
evidence. Revoke bypass access after containment and complete a post-incident review.

## Verify recovery

- The exact repairing commit renders successfully with the pinned toolchain.
- Argo CD reports the Application synchronized and healthy through the retry window.
- Kubernetes events and controller logs contain no recurring cause.
- The service acceptance check passes for the original failure path.
- Any emergency mutation is represented in Git and temporary access has been revoked.

Escalate when ownership is unclear, evidence suggests an admission or credential control has
drifted, or forward recovery would alter persistent data. Preserve the failed and repairing commits,
operation IDs, events, artifact digest, and incident timeline for handoff.

## Escalation and handoff

Provide the next responder with the environment, Application/AppProject, failed and current commits,
artifact digest, first-failure time, rendered diff, controller events/logs, attempted mutations, and
service impact. Escalate persistent-data decisions to the data owner and policy or credential drift
to security before recovery continues.
