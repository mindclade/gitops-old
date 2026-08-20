# Argo CD upgrade

Argo CD is installed once by `bootstrap/bootstrap.sh`, then reconciles its pinned upstream
installation through `argocd-self-management`. Terraform owns only cloud prerequisites.

## Prepare

1. Review the upstream release notes, security advisories, Kubernetes compatibility, CRD changes,
   and standard/HA manifests from the official release.
2. Replace both vendored payloads from the same immutable upstream tag. Update
   `bootstrap/argocd-install.version`, both SHA-256 files, and
   `bootstrap/argocd-install.provenance.json`. Do not hand-edit upstream payloads or replace
   third-party notices with Mindclade licensing.
3. Render both profiles and run the complete contract:

   ```sh
   nix develop .#ci --command make validate
   nix develop .#ci --command kustomize build \
     --load-restrictor LoadRestrictionsNone bootstrap/profiles/standard
   nix develop .#ci --command kustomize build \
     --load-restrictor LoadRestrictionsNone bootstrap/profiles/ha
   ```

4. Confirm the profile renders exclude `argocd-cm`, `argocd-rbac-cm`, `argocd-secret`, and
   `argocd-notifications-secret`. Environment roots and bootstrap/secret operators own those
   objects; allowing both Applications to manage them creates conflicting field ownership and can
   erase SSO or repository credentials.

## Qualify and promote

1. Merge through the protected control-plane path and observe development reconciliation.
2. Verify login, team RBAC, repository access, ApplicationSet generation, sync/diff behavior,
   policy reconciliation, metrics, notifications, and controller logs.
3. Rehearse the same version/profile in staging across a full deployment cycle. Include rollback,
   CRD compatibility, controller restart, and loss/re-bootstrap checks.
4. Promote the production change with the required platform and security approvals and a named
   rollback/forward-recovery owner. Observe every Argo controller rollout and existing Application
   health before closing the change.

Changing production from the standard to HA profile additionally requires at least three
schedulable nodes across three zones and verified disruption budgets/capacity. Do not select HA as
a label when the cluster cannot sustain its replica topology.

## Failure

If reconciliation fails, do not force-sync or weaken the administration AppProject. Follow
`docs/failed-sync.md`. Revert the protected Git change only when CRD/data compatibility permits;
otherwise perform an explicitly reviewed forward recovery. The cold-start script remains the
recovery path after complete Argo loss, not the routine upgrade mechanism.
