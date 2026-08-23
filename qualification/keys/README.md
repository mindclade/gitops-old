# Production eligibility public keys

Only non-secret Ed25519 public keys used to verify signed production eligibility decisions belong
here. Each handoff pins both the repository path and SHA-256 fingerprint. Adding or rotating a key
requires an independently reviewed governance audit and positive/negative signature verification.

Private key material and service credentials are forbidden. An absent key keeps production
selection blocked.
