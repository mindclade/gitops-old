#!/usr/bin/env python3
# Copyright © 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary
#
# MINDCLADE CONFIDENTIAL - PROPRIETARY AND TRADE SECRET
# Copyright (c) 2026 Mindclade. All rights reserved.
"""Validate immutable deployment release evidence without contacting external services."""
from __future__ import annotations
import argparse, datetime as dt, json, re, sys
from pathlib import Path

SHA40=re.compile(r"[0-9a-f]{40}")
DIGEST_IMAGE=re.compile(r"[^\s]+@sha256:[0-9a-f]{64}")
SHA256=re.compile(r"sha256:[0-9a-f]{64}")


def nonempty(value): return isinstance(value,str) and bool(value.strip())
def artifact_ref(value):
    return isinstance(value,dict) and nonempty(value.get("uri")) and SHA256.fullmatch(str(value.get("digest",""))) is not None

def main()->int:
    ap=argparse.ArgumentParser()
    ap.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    ap.add_argument('--images-file', type=Path)
    args=ap.parse_args()
    root=args.root.resolve(); errors=[]; records={}
    release_root=root/'releases'
    for p in sorted(release_root.rglob('*.json')) if release_root.exists() else []:
        try: obj=json.loads(p.read_text('utf-8'))
        except Exception as exc: errors.append(f"{p}: invalid JSON: {exc}"); continue
        required={
            'contract_version','release_id','source_repository','source_revision',
            'builder_identity','build_invocation_id','image','sbom','provenance',
            'vulnerability','qualification','github_attestation','binary_authorization','created_at'
        }
        missing=required-set(obj)
        if missing: errors.append(f"{p}: missing {sorted(missing)}")
        if obj.get('contract_version')!='2.0.0': errors.append(f"{p}: unsupported contract_version; expected 2.0.0")
        if not nonempty(obj.get('release_id')): errors.append(f"{p}: release_id must be non-empty")
        if not nonempty(obj.get('source_repository')): errors.append(f"{p}: source_repository must be non-empty")
        if not SHA40.fullmatch(str(obj.get('source_revision',''))): errors.append(f"{p}: source_revision must be a full commit SHA")
        if not nonempty(obj.get('builder_identity')): errors.append(f"{p}: builder_identity must be non-empty")
        if not nonempty(obj.get('build_invocation_id')): errors.append(f"{p}: build_invocation_id must be non-empty")
        image=str(obj.get('image',''))
        if not DIGEST_IMAGE.fullmatch(image): errors.append(f"{p}: image must be an immutable sha256 digest reference")
        if not artifact_ref(obj.get('sbom')): errors.append(f"{p}: sbom must contain uri and sha256 digest")
        if not artifact_ref(obj.get('provenance')): errors.append(f"{p}: provenance must contain uri and sha256 digest")
        vuln=obj.get('vulnerability')
        if not isinstance(vuln,dict) or vuln.get('result') not in {'pass','approved'} or not nonempty(vuln.get('scanner')) or not artifact_ref(vuln.get('evidence')):
            errors.append(f"{p}: vulnerability must be passing and include scanner plus evidence uri/digest")
        qual=obj.get('qualification')
        if not isinstance(qual,dict) or qual.get('result')!='pass' or not artifact_ref(qual.get('evidence')):
            errors.append(f"{p}: qualification must be pass with evidence uri/digest")
        gha=obj.get('github_attestation')
        if not isinstance(gha,dict) or not nonempty(gha.get('repository')) or not nonempty(gha.get('signer_workflow')):
            errors.append(f"{p}: github_attestation must identify repository and signer_workflow")
        binauthz=obj.get('binary_authorization')
        if not isinstance(binauthz,dict) or not nonempty(binauthz.get('project')) or not nonempty(binauthz.get('attestor')):
            errors.append(f"{p}: binary_authorization must identify project and attestor")
        created=str(obj.get('created_at',''))
        try:
            parsed=dt.datetime.fromisoformat(created.replace('Z','+00:00'))
            if parsed.tzinfo is None: raise ValueError
        except ValueError: errors.append(f"{p}: created_at must be timezone-aware RFC3339")
        if image:
            if image in records: errors.append(f"{p}: duplicate release record for {image}")
            records[image]=str(p.relative_to(root))
    if args.images_file:
        try: images=[x.strip() for x in args.images_file.read_text().splitlines() if x.strip()]
        except OSError as exc: errors.append(f"cannot read images file: {exc}"); images=[]
        for image in images:
            if image not in records: errors.append(f"no release metadata record for active image: {image}")
    if errors:
        for error in sorted(set(errors)): print(f"ERROR: {error}",file=sys.stderr)
        return 1
    print(f"release metadata validation passed ({len(records)} record(s))")
    return 0
if __name__=='__main__': raise SystemExit(main())
