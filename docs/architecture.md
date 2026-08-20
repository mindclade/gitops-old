# GitOps architecture

Each environment has its own Argo CD trust domain and root composition under `roots/`.
An Argo instance can only discover ApplicationSets for its own environment; it cannot deploy
staging or production manifests into another cluster. The built-in `default` AppProject is
overwritten as deny-all. The narrow `bootstrap` project manages only Argo projects,
applications, application sets, and non-secret configuration in the `argocd` namespace.

Gatekeeper enforces structural workload policy. Google Cloud Binary Authorization is the
single production cryptographic attestation enforcement point. CI verifies release evidence;
this repository does not deploy a second signature admission controller.
