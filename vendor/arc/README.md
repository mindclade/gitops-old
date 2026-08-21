# Vendored Actions Runner Controller charts

The expanded Helm charts under the version directory are byte-for-byte copies of the official
GitHub Actions Runner Controller OCI artifacts named in `provenance.json`. They are vendored so
rendering and review do not fetch mutable remote content.

For an upgrade, pull both charts from the exact official OCI references, record Helm's manifest
digest and the downloaded archive SHA-256, expand into a new version directory, and update the
deterministic tree digests. `scripts/validate-production-contract.py` rejects missing, extra, or
modified chart trees. Upstream example values and Secret templates are not deployable desired
state; repository-owned values and rendered outputs remain subject to the normal secret and
immutable-image gates.
