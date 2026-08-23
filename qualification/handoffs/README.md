# Production qualification handoffs

This directory contains sanitized, reviewable handoff claims only. A claim binds one nonempty
production deployment selection to the exact seven-repository source set, production render,
signed eligibility decision, immutable evidence-object URI and generation, pinned public key, and
rollback target.

Claims contain no credentials or raw connected evidence. The protected qualification workflow
publishes evidence create-only, and the protected `production-handoff-gate` merge check re-fetches
the exact object generation and verifies the Ed25519 decision before the qualified source can merge.
A decision is
valid for at most six hours. Expiry blocks a new promotion; it does not automatically delete a
healthy running workload.

Promotion first commits a nonempty `staged-v1` selection with no handoff; ordinary rendering cannot
materialize it. Protected qualification emits the handoff and public key as a short-lived review
artifact. Activation is one pull request that adds those files, commits the exact candidate render,
and changes the selection to `qualified-v1`. Until qualification exists, production remains
`blocked-v1` or `staged-v1` with `qualificationHandoff: null`.
