---
name: readiness-only-via-ssh
description: Judge lab node state through SSH (the manager's readiness); the one trusted docker-log line is vJunos-switch's "Startup complete in"
metadata:
  type: feedback
---

Node readiness is judged via SSH: the manager's `/api/state` `nos_readiness` / `nos_login` (SSH login + `show version`), or a direct SSH login. Never treat a TCP banner on port 22 as readiness (the vJunos container's SSH forwarder answers before Junos does). Exception the user granted on 2026-09-18: for the exact image `n24l/vjunos-switch:23.2R1.14`, the container log line `INFO Startup complete in: <duration>` is accurate and may be used as the boot-complete signal (observed: ~27 min when two boot side by side, ~20 min alone). Other images' logs stay untrusted.

**Why:** the user first said "it should only be via ssh never trust docker logs", then corrected: "for this exact image and release you can trust the docker logs. 'INFO Startup complete in:' is accurate".

**How to apply:** poll `/api/state` in a background loop for the manager's view; for vJunos-switch 23.2R1.14 you may also grep its log for "Startup complete in". For a Linux PC, make `show version` answer on stdout so the probe passes. See [[af-learning-labs-project]].

Never `docker restart` a containerlab node to recover it: the restart drops the node's veth data links (the far ends go down, the container keeps only eth0), and everything recorded afterwards is invalid. A cJunosEvolved that kernel-panics during boot (seen once on the L7 lab, `Saving vmcore`) needs a manager `redeploy` of the lab, then the states are re-applied from Git.