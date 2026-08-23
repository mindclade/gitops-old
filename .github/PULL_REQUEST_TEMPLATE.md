## Desired-state outcome

Describe the source revision, affected application or policy, environments, and
operator-visible result.

## Promotion and policy evidence

- Release and qualification record:
- Exact subject digest:
- Source and target environment:
- Render, schema, policy, and drift results:
- Automated desired-state impact artifact reviewed (risk, RBAC, prune, images):
- Required approvers:

## Validation evidence

List the exact commands and results. `rendered/**` must be generated.

```text
nix develop --command make validate
```

## Rollback and recovery

State the previous qualified release, rollback trigger, observable success, and
the freeze or failed-sync runbook used if reconciliation fails.

## Checklist

- [ ] Rendered state was generated and not hand-edited.
- [ ] Promotion preserves an immutable qualified artifact.
- [ ] Policy exceptions are exact, reviewed, time-bounded, and permitted.
- [ ] No plaintext secret, customer data, model weight, or incident evidence is committed.
- [ ] Production changes have Platform and Security review and two qualified approvals.

## Contributor authorization

- [ ] I am authorized under a current written agreement with Mindclade, LLC. to
      submit every part of this contribution.
- [ ] I identified every third-party component, image, chart, specification, or
      generated artifact and preserved its source, license, provenance, and notices.
- [ ] I updated `LICENSE`, `NOTICE`, the SBOM, or other license evidence when
      the included or distributed material changed.
