# Production release-chain bindings

Each connected production qualification request has one reviewed JSON record named
`<qualification-id>.json`. The record binds the signed `v5.0.0` workflow release, signed `v0.4.0`
module release, applied bootstrap `1.6.0` outputs, protected saved plan, applied outputs, and exact
rollback lineage.

The qualification assembler compares every recorded digest with the independently downloaded
evidence artifact before constructing deployment bundle v2. No record is committed until both
release tags exist and the protected connected evidence has been produced.
