---
name: node-boot-status-from-manager-not-docker-logs
description: "The user says containerlab node docker logs are mostly wrong about Junos boot state; judge boot/readiness from the manager's readiness probes and real SSH instead"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 1943562e-7407-4d16-ae80-e8fbedd849d3
  modified: 2026-09-17T12:31:41.046Z
---

When validating the clab-manager against live Junos nodes (cJunosEvolved, vJunos-switch), do not
read `docker logs <node>` to decide whether a node has booted. Use the manager's `/api/state`
node fields (`ssh_ready`, the Starting/Ready pills) and a real SSH login instead.

**Why:** The user said on 2026-09-17: "Stop using the docker logs to see if the nodes booted
correctly, that info is mostly wrong." vrnetlab/EVO entrypoint logs describe the outer VM
launch, not the NOS being ready to accept logins.

**How to apply:** Poll the manager's readiness (or the UI's `n of m devices ready`) and confirm
with an SSH `show version`; treat container health/logs as irrelevant to readiness. Also: do not
switch models mid-task on this project. See [[clab-llm-dev2-is-not-the-dev-vm]].
