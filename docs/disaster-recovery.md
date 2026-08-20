<!-- mindclade-doc: runbook@1 -->

# Argo CD control plane is unavailable or lost

> **Use when:** Argo CD is unavailable or lost after cluster or namespace failure.
> **Impact:** reconciliation is unavailable; running workloads may drift until recovery completes.
> **Primary owner:** incident commander with platform and infrastructure operators.
> **Escalate:** when context, profile, commit, credential provenance, or cloud prerequisites differ.

## Symptoms

- the Argo CD API and controllers are unavailable after cluster or namespace loss;
- the `argocd` namespace cannot be recovered in place; or
- a replacement cluster has cloud prerequisites but no GitOps control plane.

## Impact and stop conditions

Reconciliation is unavailable for the affected environment. Existing workloads may continue
running, but drift will not self-heal. Stop if the intended environment, Kubernetes context,
bootstrap profile, Git commit, or credential-file provenance is uncertain. Recover cloud and
GKE prerequisites through `bootstrap` and `infrastructure-live` before using this runbook.

## Diagnose and prepare

1. Declare an incident and freeze ordinary promotion for the affected environment.
2. Record the last known-good GitOps commit and the current `main` commit.
3. Verify the target cluster and context independently:

   ```sh
   kubectl config current-context
   kubectl cluster-info
   kubectl auth can-i create namespaces
   ```

4. Select the profile already declared in `applications/<environment>/argocd.yaml`. Do not
   choose `ha` unless the cluster has at least three schedulable nodes across three zones.
5. Materialize the five required Argo OAuth and GitHub App credential values into separate
   restrictive temporary files. Never place the values in Git or command arguments.

## Recover

1. Export the credential file paths expected by `bootstrap/bootstrap.sh`:

   ```sh
   export ARGOCD_DEX_GITHUB_CLIENT_ID_FILE=/secure/path/dex-client-id
   export ARGOCD_DEX_GITHUB_CLIENT_SECRET_FILE=/secure/path/dex-client-secret
   export ARGOCD_GITHUB_APP_PRIVATE_KEY_FILE=/secure/path/github-app.pem
   export ARGOCD_GITHUB_APP_ID_FILE=/secure/path/github-app-id
   export ARGOCD_GITHUB_APP_INSTALLATION_ID_FILE=/secure/path/github-app-installation-id
   ```

2. For production only, set the explicit safety confirmation:

   ```sh
   export MINDCLADE_PRODUCTION_BOOTSTRAP_CONFIRM=production
   ```

3. Run the audited bootstrap against the exact expected context:

   ```sh
   ./bootstrap/bootstrap.sh --apply --environment <development|staging|production> --profile <standard|ha> --context <expected-context>
   ```

The script verifies the vendored install checksum, refuses the wrong context or profile,
establishes the deny-by-default bootstrap project, installs credential references, removes
the upstream initial-admin secret, applies the root application, and waits for core Argo
rollouts.

## Verify recovery

```sh
kubectl get applications.argoproj.io -n argocd
kubectl get appprojects.argoproj.io -n argocd
kubectl get pods -n argocd
```

Confirm the root application is present, only the intended environment's applications are
discovered, core components are ready, the initial-admin secret is absent, and Gatekeeper and
Binary Authorization still deny their qualified negative fixtures. Restore stateful workload
data from its authoritative backup system; GitOps restores configuration, not data.

## Escalation and handoff

Hand the next responder the incident ID, target context/environment/profile, authoritative commits,
credential-file provenance, commands, controller events, mutations, data recovery point, negative
policy tests, and remaining service risk. Escalate any cross-environment discovery or policy bypass
to security before reopening workloads.

## Close and prevent recurrence

Remove temporary credential files and environment variables, unfreeze promotion after health
checks, attach bootstrap evidence to the incident, and document the failure that made control
plane replacement necessary. Never retain the temporary credential files as a convenience
recovery kit.
