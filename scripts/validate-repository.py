#!/usr/bin/env python3
# Copyright © 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary
#
from pathlib import Path
import hashlib, re, sys, yaml
root=Path(__file__).resolve().parents[1]
errors=[]
for n in ['argocd-install.yaml','argocd-install-ha.yaml']:
 p=root/'bootstrap'/n; sp=root/'bootstrap'/(n+'.sha256')
 if not p.exists() or not sp.exists(): errors.append(f'missing pinned Argo file: {n}'); continue
 expected=sp.read_text().split()[0]; actual=hashlib.sha256(p.read_bytes()).hexdigest()
 if expected!=actual: errors.append(f'checksum mismatch: {n}')
version=(root/'bootstrap/argocd-install.version')
if not version.is_file() or not re.fullmatch(r'v[0-9]+\.[0-9]+\.[0-9]+\n?', version.read_text()): errors.append('missing or invalid pinned Argo CD version')
if (root/'policy/sigstore').exists(): errors.append('duplicate Sigstore admission policy remains; Binary Authorization is authoritative')
if list((root/'policy').rglob('*require-attestation*')): errors.append('misleading require-attestation policy name remains; Gatekeeper owns structural image policy only')
if (root/'CODEOWNERS').exists() or not (root/'.github/CODEOWNERS').exists(): errors.append('CODEOWNERS must exist only at .github/CODEOWNERS')
for env in ['development','staging','production']:
 if not (root/f'roots/{env}/kustomization.yaml').exists(): errors.append(f'missing cluster composition: {env}')
 if not (root/f'applications/{env}/platform.yaml').exists(): errors.append(f'missing applications: {env}')
# Parse authored YAML; the two vendored upstream manifests are protected by checksums and huge.
for p in root.rglob('*.yaml'):
 if p.name.startswith('argocd-install') or 'rendered' in p.parts: continue
 try: list(yaml.safe_load_all(p.read_text()))
 except Exception as e: errors.append(f'YAML parse {p.relative_to(root)}: {e}')
text='\n'.join(p.read_text(errors='ignore') for p in root.rglob('*') if p.is_file() and '.git' not in p.parts and '__pycache__' not in p.parts and p.suffix != '.pyc' and not p.name.startswith('argocd-install') and p.name not in {'BLUEPRINT.md','validate-repository.py'})
for stale in ['mindclade-org','infrastructure-live/5-workloads/<env>/argocd','https://github.com/Mindclade/mindclade\n','repo: Mindclade/mindclade\n']:
 if stale in text: errors.append(f'stale ownership/reference: {stale}')

# GitHub and Argo freeze controls must move together. The impossible February-31 schedule is
# the explicit dormant state; a continuous cron activates the emergency deny window.
try:
 production = yaml.safe_load((root/'overlays/production.yaml').read_text()) or {}
 sync_patch = (root/'roots/production/sync-windows-patch.yaml').read_text()
 emergency_active = 'schedule: "* * * * *"' in sync_patch
 if bool(production.get('deployFreeze')) != emergency_active:
  errors.append('production deployFreeze and Argo emergency sync window disagree')
except Exception as e:
 errors.append(f'freeze-control validation failed: {e}')

# No cross-environment ApplicationSet matrices remain.
for p in (root/'applications').rglob('*.yaml'):
 env=p.parts[-2]; t=p.read_text()
 for other in {'development','staging','production'}-{env}:
  if f'rendered/{other}/' in t: errors.append(f'{p.relative_to(root)} references {other}')
if errors:
 print('\n'.join('ERROR: '+e for e in errors),file=sys.stderr); sys.exit(1)
print('gitops repository invariants passed')
