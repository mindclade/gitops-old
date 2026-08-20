<!-- mindclade-doc: runbook@1 -->

# Revoke a compromised artifact

Owner: Security incident commander. Required actors: a primary response operator and a distinct
observer. The artifact repository and signing systems own artifact/attestation revocation;
`gitops` owns promotion freezes, immutable deployment selections, and workload convergence.

## Symptoms and immediate containment

Trigger on a compromised build identity, invalid provenance, vulnerable or malicious digest,
unexpected runtime behavior, or security direction. Record every affected digest, repository,
environment, workload, release record, source revision, and UTC detection time. Enable the GitHub
promotion freeze and the independent Argo synchronization freeze before changing selections.

Abort a drill if any digest is deployed in production, if the last-known-good digest cannot be
proven, if the proposed denial affects an undeclared artifact, or if cluster state cannot be read.
A real incident involving production requires the incident commander's explicit production path.

## Read-only diagnosis

1. Search deployment selections, release metadata, rendered manifests, and live workload status for
   the exact digest; do not search by mutable tag.
2. Verify provenance and qualification evidence for both the suspect digest and candidate
   last-known-good digest.
3. Capture Binary Authorization policy/attestation state and admission/audit events. Determine
   whether running pods already contain the digest.
4. Render and validate a Git revert or replacement selection. Confirm that only declared workloads
   and environments change.

## Revoke and recover

Security revokes or denies deployment eligibility through the artifact/Binary Authorization
authority. A reviewed Git change then selects the proven last-known-good digest or scales the
affected workload to its approved containment state. After both freezes receive their independent
approvals, allow only the targeted reconciliation. Never edit a live workload, use a mutable tag, or
delete release evidence.

Verify the suspect digest is denied for new admission, no running pod uses it, the replacement
digest has valid provenance/qualification, health checks pass, and Argo is synchronized to the
reviewed commit. Re-enable promotion only after incident approval and preserve the denial until the
security owner closes the compromise.

## Evidence and success

Success requires complete digest inventory, verified revocation/denial, healthy replacement or
approved containment, immutable Git history, and no unrelated sync. Measure RPO from the last
qualified selection and RTO through verified convergence. Record operator identities, source SHAs,
commands, evidence URIs/hashes, failures, corrective actions, and next drill date in report v2.
