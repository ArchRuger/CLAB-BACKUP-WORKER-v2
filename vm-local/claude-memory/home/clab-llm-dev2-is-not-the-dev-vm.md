---
name: clab-llm-dev2-is-not-the-dev-vm
description: "The host clab-llm-dev2 (192.168.132.132) where ~/projects/clab-manager is checked out has no Docker, containerlab, manager data, Junos images, dev-VM SSH route or passwordless sudo; live-lab validation cannot run here"
metadata: 
  node_type: memory
  type: project
  originSessionId: 1943562e-7407-4d16-ae80-e8fbedd849d3
  modified: 2026-09-17T09:55:00.617Z
---

As of 2026-09-17 the checkout at `~/projects/clab-manager` lives on `clab-llm-dev2`
(192.168.132.132, Ubuntu 24.04, user `clabllm`), which is NOT the containerlab dev VM the
repository docs describe. Verified absent: `docker`, `containerlab`,
`/srv/containerlab-node-manager`, `/etc/clab-manager`, `/home/clabllm/clab-venv`, `newuidmap`
(so no rootless Docker), passwordless sudo, any SSH config or known host for a dev VM, and no
other host on 192.168.132.0/24 answering on 22, 8081 or 3000. The labs `clabllm-dev` and
`bgp-core`, the Junos images and the Git checkout `~/labs/CLAB-MNGR-DEV-LLM` exist only on the
real dev VM, which is unreachable from here.

What does work here: `clab-backup-ui/.venv` (fastapi, httpx, paramiko, ansible-core,
playwright 1.63 with Chromium 1243 in `~/.cache/ms-playwright`), Node 18, system Python 3.12,
`gh` authenticated as ArchRuger with workflow scope. Use `clab-backup-ui/.venv/bin/python`
instead of the documented `/home/clabllm/clab-venv/bin/python`.

**Why:** Prompts and `docs/redesign/PICKUP.md` §2 assume the dev VM; the 1.29.0 release was
blocked on 2026-09-17 solely because the live-lab gates cannot be exercised on this host.

**How to apply:** Run the automated suites, the fixture browser suite
(`docs/redesign/tools/fixture_manager.py` + `verify_after.py`) and CI from here, but never claim
a live-lab result; say plainly that the live pass needs the dev VM. See [[clab-release-procedure]].
