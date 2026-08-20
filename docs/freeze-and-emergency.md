<!-- mindclade-doc: runbook@1 -->

# Production freeze and emergency change

> **Use when:** a scheduled or incident freeze is active and an urgent production change is
> required.
> **Impact:** critical—the procedure temporarily permits an exact reviewed sync while ordinary
> production reconciliation remains blocked.
> **Primary owner:** incident commander with platform and security approval.

## Invariant

A production freeze has two independent gates:

1. `freeze.yml` blocks an ordinary production pull request from merging.
2. the production AppProject deny windows block both automated and manual Argo CD syncs.

The committed deny windows keep `manualSync: false`. A GitHub override authorizes one reviewed
pull request to merge; it does not grant every AppProject sync role permission to bypass the live
Argo window.

## Stop conditions

Stop if the incident/change record, exact pull request, target Application, target Git commit,
approving teams, cluster context, or rollback/forward-recovery owner is unknown. Do not disable a
window for an entire environment when one Application is sufficient. Do not use a local Argo
admin password, commit credentials, or edit workload resources directly.

## Authorize the Git change

1. Record the incident/change identifier, scope, reason, owner, and expiry.
2. Update `overlays/freeze-override.yaml` in the emergency pull request:
   - set `active: true`;
   - set `pullRequest` to that exact pull-request number;
   - record the ticket, approving team, specific reason, expiry of at most three days, and
     `gitops-production` scope.
3. Obtain the protected platform and security review required by CODEOWNERS and the production
   ruleset.
4. Merge only after all normal artifact, render, policy, and provenance gates pass. Record the
   exact merged commit.

At this point GitHub has accepted the reviewed desired state, but Argo CD remains denied by the
live sync window.

## Permit one audited live sync

The cluster-admin operator uses the protected Kubernetes access path; ordinary project roles do
not have this authority.

1. Verify the exact context and inspect the target project before mutation:

   ```sh
   kubectl config current-context
   kubectl get appproject -n argocd <project> -o yaml
   argocd app get <application>
   ```

2. Identify the active deny-window array index from the live AppProject. Temporarily replace only
   that window's `manualSync` field with `true`, using a JSON patch whose reviewed index and value
   are recorded in the incident log:

   ```sh
   kubectl patch appproject -n argocd <project> --type=json \
     -p='[{"op":"test","path":"/spec/syncWindows/<index>/manualSync","value":false},{"op":"replace","path":"/spec/syncWindows/<index>/manualSync","value":true}]'
   ```

3. Sync only the named Application at the exact approved GitOps commit:

   ```sh
   argocd app sync <application> --revision <approved-gitops-commit>
   ```

4. Immediately set the live field back to `false` with another test-and-replace JSON patch. The
   root Application also self-heals the committed `false` value; verify that convergence rather
   than relying on it silently.

Do not broaden an AppProject, disable admission, use `--force`, or sync an unreviewed revision to
make an emergency change pass.

## Verify and close

- confirm the Application is `Synced` and `Healthy` at the approved commit;
- confirm every production AppProject deny window again reports `manualSync: false`;
- confirm the root Application is synchronized and no live-only drift remains;
- reset `overlays/freeze-override.yaml` to its inactive canonical form through a reviewed cleanup
  pull request as soon as the active freeze permits it;
- revoke temporary cluster access and preserve Kubernetes, Argo CD, GitHub, approval, and service
  evidence; and
- complete post-incident review and the rollback or forward-recovery follow-up.

If the change cannot pass policy, provenance, or Binary Authorization, the freeze override does
not authorize weakening those controls.
