# Vendored Gatekeeper library templates

Upstream: <https://github.com/open-policy-agent/gatekeeper-library>

Vendored, not installed as a dependency, for the same reason `rendered/` is committed:
what the cluster enforces should be readable in this repository, not fetched at apply
time from a moving reference.

A constraint whose ConstraintTemplate is absent does not fail loudly — it fails to
apply, and the control silently does not exist. Vendoring makes `gator test` able to
evaluate every constraint in `../constraints/` without a cluster.

## Provenance

| File | Upstream path | Kind |
|---|---|---|
| `requiredannotations.yaml` | `library/general/requiredannotations` | `K8sRequiredAnnotations` |

Pinned at commit `e4d3bd2448b20bc7910417f5b2cf18b63a0bd33c`.

## Four templates were removed from here. Do not re-vendor them.

`disallowedtags`, `containerresources`, `privileged-containers` and `users` used to live in
this directory. Every one of them read containers from exactly one place:

```rego
input_containers[c] { c := input.review.object.spec.containers[_] }
```

That is the **Pod** shape. Each of our constraints matched `Pod, Deployment, StatefulSet,
DaemonSet, Job, CronJob` — and on all of those except `Pod` the containers live under
`spec.template.spec.containers`, or under `spec.jobTemplate.spec.template.spec.containers`
for a CronJob. The rule found nothing and reported clean.

So `deny-latest-tag`, `deny-privileged`, `require-resource-limits` and
`partner-namespace-isolation` were **inert against every workload Argo actually syncs**, for
as long as they had existed. The same manifest fires as a `Pod` and is silent as a
`Deployment`:

```
pod      deny-latest-tag FIRES
deploy   deny-latest-tag SILENT
```

Nothing detected it. `gator test` passed, the constraints were present, the templates were
present, and review saw a correct-looking policy. It surfaced only because a `:latest` image
reached `rendered/production` and someone asked why the gate had not caught it.

The upstream templates are not wrong — they are written for `kinds: ["Pod"]`, which is how
the library ships them. They were adopted here with `kinds` widened to cover workloads, and
nothing checked that the template supported it.

Replacements are first-party, in the parent directory:

| Removed | Replaced by | Constraint kind |
|---|---|---|
| `disallowedtags.yaml` | `../deny-latest-tag.yaml` | `MindcladeDisallowedTags` |
| `privileged-containers.yaml` | `../deny-privileged.yaml` | `MindcladePrivilegedContainer` |
| `containerresources.yaml` | `../require-resource-limits.yaml` | `MindcladeRequiredResources` |
| `users.yaml` | `../partner-allowed-users.yaml` | `MindcladePartnerAllowedUsers` |

Each reads every nesting, using the same `input_containers` set as `require-image-policy.yaml`.

`../tests/suite.yaml` now asserts that each constraint fires on each kind it claims to match.
Repointing any constraint back at a Pod-only template fails that suite immediately — verified
by doing exactly that, which turned four cases red and left only the `Pod` case passing.

## Updating

```sh
LIB=https://raw.githubusercontent.com/open-policy-agent/gatekeeper-library/<new-sha>/library
curl -fsSL "$LIB/general/requiredannotations/template.yaml" -o requiredannotations.yaml
# ...then update the commit above, and re-run BOTH:
gator verify ../tests/suite.yaml
gator test --filename=../templates --filename=../constraints --filename=../../rendered/development
```

`gator verify` is the one that catches a re-vendored template quietly narrowing what a
constraint covers. `gator test` alone cannot: it answers "do the current manifests violate
anything?", which is "no" both when the estate is clean and when the policy is broken.

Do not edit these files. A local modification is invisible next time someone re-vendors,
and the constraint that depended on it changes behaviour with no diff explaining why. If
upstream is wrong for us, write our own template in the parent directory instead —
`require-image-policy.yaml` and `deny-holdout-mount.yaml` are the original examples, and the
four replacements above are the rest.
