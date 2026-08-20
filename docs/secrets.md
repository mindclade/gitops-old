<!-- mindclade-doc: reference@1 -->

# Secret handling in GitOps

> **Audience:** Workload authors, platform engineers, and security reviewers
> **Outcome:** Declare secret consumption without committing secret values or creating a
> second cloud-identity path.

Plain Kubernetes Secret payloads are prohibited in authored and rendered Git content. GitOps
may declare ExternalSecret resources or CSI references whose values remain in an approved
external secret backend. Production workload identity is the default Google Cloud
authentication model.

| Git may contain | Git must not contain |
| --- | --- |
| Secret object name and namespace | Secret value or encoded payload |
| External secret store reference | Service-account JSON key |
| CSI driver configuration | Private key or OAuth client secret |
| Workload identity service-account annotation | Terraform state, provider credential, or raw plan |

Use the minimum namespace and workload scope. The cloud-side secret, IAM grant, and workload
identity are owned by `infrastructure-live`; this repository owns only the Kubernetes
reference. A pull request must prove that a reference cannot resolve across an unintended
environment or namespace.

If a value is committed, revoke or rotate it first, then remove it from the current tree and
follow the security incident process. Deleting a Git line does not invalidate an exposed
credential or remove it from history.
