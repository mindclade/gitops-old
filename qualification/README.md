# Infrastructure qualification overlays

These overlays are the environment/cluster-owned half of the monorepo
`infra/kubernetes/platform/qualification` contract. The renderer injects the protected source
render as `base.yaml`; the committed overlays currently add identity labels only and preserve the
blocked namespace, zero quotas, digest-zero image, and suspended CPU/H100/H200 Jobs.

Activation is deliberately absent. `run-contracts.yaml` permits exactly one
environment/cluster/profile selection per reviewed run. Serving clusters permit CPU only;
development combined and staging/production compute clusters permit CPU, H100, or H200, but never
more than one in a run. A later, connected qualification change must patch exactly one
Job and atomically provide the measured ResourceQuota, an attested immutable image digest, immutable
run/source/evidence labels, set the namespace activation label to the reserved value
`mindclade.dev/workload-activation=qualification`, and set `suspend: false`. `active` is forbidden:
the fail-closed admission policy reserves `qualification` to the exact
`mindclade-qualification` namespace and rejects that value everywhere else. It must keep normal
Kueue queues held. The same
change must include rollback evidence showing restoration of zero quota, the blocked namespace, and
all Jobs suspended before another profile can be selected. `scripts/render.py` rejects a blocked
qualification render that violates those invariants.

Live activation must also retain the canonical namespace owner and restricted Pod Security labels,
bind the foundation target plus release and rendered-manifest evidence required by the canonical
security policy, remove `mindclade.dev/activation-blocker`, and use the exact three-template digest
pinned to the `v0.2.0` source lock. The rendered-manifest digest is not caller-authored: it is the
SHA-256 of canonical JSON for resources sorted by API version, kind, namespace, and name after
removing only `mindclade.dev/rendered-manifest-digest` from Namespace and Job annotations. Both the
Namespace and selected Job must carry that recomputed value. A future authenticated result must
report the same value before any image can be selected. The unresolved lock is an intentional stop
condition.
