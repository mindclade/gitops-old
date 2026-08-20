<!-- mindclade-doc: runbook@1 -->

# A GitOps deployment must be rolled back

> **Audience:** Service owner, platform operator, and incident commander
> **Outcome:** Restore the last compatible reviewed artifact through Git while preserving
> audit evidence and reconciliation authority.

## Symptoms

- a recently reconciled artifact causes a confirmed regression;
- health checks or policy-qualified production behavior fails after promotion; or
- an incident commander directs a rollback to a known-good digest.

## Stop conditions

Do not roll back blindly across an irreversible data or schema migration. If the previous
artifact cannot safely run against current state, use a reviewed forward fix. Do not edit live
Applications, Deployments, image fields, or Argo parameters; those changes are drift and will
be overwritten.

## Procedure

1. Declare or link the incident/change record and freeze further promotion for the workload.
2. Identify the last known-good Git commit and immutable digest from deployment evidence.
3. Verify migration and configuration compatibility with the service owner.
4. Revert the smallest Git change that selected or promoted the failing artifact:

   ```sh
   git revert <failing-commit>
   ```

5. Open a pull request. Review the rendered diff as the exact cluster delta and run the normal
   policy, provenance, and promotion-integrity checks.
6. Merge through the protected path and observe Argo CD reconcile the reviewed state.

## Verify

- the live workload reports the known-good immutable digest;
- Argo reports `Synced` and `Healthy` without manual overrides;
- service health and the original incident symptom recover;
- Gatekeeper and Binary Authorization remain enforced; and
- the deployment record links source, GitOps commit, digest, approvals, and Argo sync.

## Follow-up

Unfreeze promotion only after stability criteria are met. Preserve failed-artifact evidence,
open the forward-fix work, and document why automated qualification did not catch the
regression.
