#!/usr/bin/env python3
# MINDCLADE CONFIDENTIAL - PROPRIETARY AND TRADE SECRET
# Copyright (c) 2026 Mindclade. All rights reserved.
from pathlib import Path
import sys,yaml
root=Path(__file__).resolve().parents[1]
errors=[]
for p in (root/"projects").glob("*.yaml"):
 for doc in yaml.safe_load_all(p.read_text("utf-8")):
  if not isinstance(doc,dict) or doc.get("kind")!="AppProject":continue
  project=doc.get("metadata",{}).get("name")
  for role in doc.get("spec",{}).get("roles",[]) or []:
   name=role.get("name")
   for policy in role.get("policies",[]) or []:
    if not isinstance(policy,str):errors.append(f"{p}: {project}/{name} policy is not a Casbin string");continue
    fields=[x.strip() for x in policy.split(",")];
    if len(fields)!=6:errors.append(f"{p}: {project}/{name} policy must have six Casbin fields: {policy}")
    if f"proj:{project}:{name}" not in policy:errors.append(f"{p}: role binding mismatch: {policy}")
if errors:
 print("\n".join(errors),file=sys.stderr);raise SystemExit(1)
print("Argo project RBAC validation passed")
