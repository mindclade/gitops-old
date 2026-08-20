#!/usr/bin/env python3
# Copyright © 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary
#
# MINDCLADE CONFIDENTIAL - PROPRIETARY AND TRADE SECRET
# Copyright (c) 2026 Mindclade. All rights reserved.
from pathlib import Path
import sys
try:
 import yaml
except ImportError:
 print("PyYAML is required from the pinned repository toolchain",file=sys.stderr);raise SystemExit(2)
class StrictLoader(yaml.SafeLoader): pass
def construct_mapping(loader,node,deep=False):
 mapping={}
 for key_node,value_node in node.value:
  key=loader.construct_object(key_node,deep=deep)
  if key in mapping: raise ValueError(f"duplicate YAML key: {key}")
  mapping[key]=loader.construct_object(value_node,deep=deep)
 return mapping
StrictLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,construct_mapping)
for p in Path(__file__).resolve().parents[1].rglob("*.y*ml"):
 if any(x in p.parts for x in (".git","rendered")): continue
 # Vendored Argo CD payloads are byte-verified against the pinned upstream release.
 # Re-parsing thousands of upstream documents here adds minutes without validating
 # Mindclade-authored configuration; authored bootstrap overlays are still parsed.
 if p.name in {"argocd-install.yaml", "argocd-install-ha.yaml"}: continue
 try:
  list(yaml.load_all(p.read_text("utf-8"),Loader=StrictLoader))
 except Exception as e:
  print(f"{p}: {e}",file=sys.stderr);raise SystemExit(1)
print("strict YAML validation passed")
