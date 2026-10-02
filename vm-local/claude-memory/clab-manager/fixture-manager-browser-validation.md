---
name: fixture-manager-browser-validation
description: "How browser validation of the redesign runs on this host without a VM (fixture manager, Playwright, pkill pitfall)"
metadata: 
  node_type: memory
  type: project
  originSessionId: 1091edac-9ddb-4b0c-a33c-fc03097e5fb4
  modified: 2026-09-17T01:37:00.024Z
---

Browser validation of the WebUI runs against `docs/redesign/tools/fixture_manager.py` (the real app on a scratch data dir; readiness, discovery, jobs, Git helper, restore probe and the lab-operations helper are answered in-process) with `docs/redesign/tools/verify_after.py` (3 viewports, screenshots, zero console/page errors; "Failed to load resource" for a handled non-2xx is reported apart). Chromium needs `LD_LIBRARY_PATH=<scratchpad>/chromium-libs/root/usr/lib/x86_64-linux-gnu` (5 libs extracted from .debs, no sudo).

**Why:** the host `clab-llm-dev2` has no Docker/containerlab/lab VM, so the live-lab pass cannot happen here; the fixture is the only way to see the real UI. Live-lab validation stays a reported blocker, never claimed.

**How to apply:** start it with `FIXTURE_DATA=<scratchpad>/fixture-data clab-backup-ui/.venv/bin/python docs/redesign/tools/fixture_manager.py --port 8090` in the background. Stop it ONLY with `pkill -f "^[^ ]*python[^ ]* docs/redesign/tools/fixture_manager.py"` in its own Bash call: an unanchored `pkill -f fixture_manager` (or a start command in the same shell line) matches the calling shell and kills it (exit 144). The validation script must go Home through `#crumb-home`, not `goto('/')` (the router restores the last lab from sessionStorage). See [[dev2-host-environment]].
