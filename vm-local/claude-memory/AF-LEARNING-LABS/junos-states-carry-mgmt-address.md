---
name: junos-states-carry-mgmt-address
description: Manager reference states for cJunosEvolved labs contain the management IP; changing mgmt addresses in the clab file requires rebuilding every state
metadata: 
  node_type: memory
  type: project
  originSessionId: c8e458a3-4605-4323-b09a-d0656874fbfa
  modified: 2026-09-18T20:57:05.051Z
---

In the AF-LEARNING-LABS labs, a Junos state snapshot (`<lab>/reference/{start,solution,broken-01}` in `pruger-dev/CLAB-MNGR-DEV-LLM`) includes `interfaces re0:mgmt-0 … address 172.20.20.x`. If `mgmt-ipv4` in the `.clab.yml` changes after the states were snapshotted, every manager restore moves the routers back to the old address: they answer ping there while tools and the manager report "lost SSH". The manager's `commit confirmed` rollback also fails on cJunosEvolved (`Missing mandatory statement: 'root-authentication'` in the factory config) and leaves a dirty shared candidate.

**Why:** This cost most of 2026-09-18 on Lesson 7 and was misdiagnosed as unstable Junos VM boots (which also happen on this nested VMware host, but recover by themselves).

**How to apply:** When routers "lose SSH" right after a restore, ping the old management addresses first. After any management address change, rerun `build_states.py` for every state. Start scripted `configure` sessions with `rollback 0`. Never `docker restart` a containerlab node; redeploy through the manager.
