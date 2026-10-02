---
name: remote-agent-guide-for-clab-llm-dev2
description: "Where the connection and working guide for the dev VM clab-llm-dev2 lives (on the VM and as a Claude doc), plus the persisted validation tooling paths"
metadata: 
  node_type: memory
  type: reference
  originSessionId: 1943562e-7407-4d16-ae80-e8fbedd849d3
  modified: 2026-09-17T13:13:32.308Z
---

The guide for an agent working on `clab-llm-dev2` (192.168.132.132, user `clabllm`, passwordless
sudo, manager 1.29.0 at http://127.0.0.1:8081, lab `clab-llm-dev2`) is at `~/AGENT-CONNECT.md` on
the VM and as a Claude doc: https://claude.ai/code/artifact/efb8b816-0b33-42ac-a649-615fc6eed23a
(written 2026-09-17). Persisted helpers: `~/validation-tools/` (live gate Playwright scripts,
`junos_ssh.py`, `prep_states.py`), `~/.local/lib/chromium-deps` (Chromium libraries, exported by
`~/.bashrc`), `~/.clab-discovery-password`. `gh` holds two accounts: `pruger-dev` (lab repository,
active) and `ArchRuger` (manager repository; switch before pushing source).

See [[clab-llm-dev2-is-not-the-dev-vm]] (now outdated: the host became the dev VM on 2026-09-17)
and [[node-boot-status-from-manager-not-docker-logs]].
