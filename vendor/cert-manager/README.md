# Locked cert-manager static release

GitOps owns the cert-manager installer. The upstream v1.19.1 static release is byte-locked in
`contracts/cert-manager-v1.19.1.lock.yaml` and stored as two deterministic gzip/base64 phase
payloads so the large CRDs remain reviewable and transport-safe. Rendering expands them offline;
it never downloads content.

The CRD phase contains exactly six CRDs and receives `Prune=false,Delete=false`. The controller
phase contains the other 43 upstream objects, deletes the Namespace owned by the separate
foundation Application, pins all three images by digest, and applies reviewed availability,
resource, and system-node patches. `scripts/validate-cert-manager-vendor.py` proves phase hashes,
6+43 parity, normalized 49-object identity, disjointness, Kustomize renderability, and image locks.
