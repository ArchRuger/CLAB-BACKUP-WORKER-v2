---
name: dev2-host-environment
description: What the clab-llm-dev2 host has (full dev VM since 2026-09-17), the agent connection guide doc, and the host-crash recovery recipe (Docker's corrupted network store, 2026-09-27)
metadata:
  type: project
---

Host `clab-llm-dev2` (user clabllm, uid 1000, LAN 192.168.132.132 via DHCP, Ubuntu 24.04) IS the full dev VM since 2026-09-17: Docker 29.8, containerlab 0.79, the manager container (`containerlab-node-manager-backup-ui-1`, port 8081, data under `/srv/containerlab-node-manager/data`), capture and Prometheus stacks, and the live lab `clab-llm-dev2` (PTX1 cJunosEvolved 172.20.20.2, SW1 vJunos-switch 172.20.20.3, login admin/admin@123). `clabllm` has passwordless sudo (`/etc/sudoers.d/90-clabllm`) and is in the `docker` and `clab_admins` groups (a session started before the grant still needs `sudo docker`). The project `.venv` under `clab-backup-ui/` has the app requirements, httpx, Playwright and pexpect; headless Chromium libs are unpacked in `~/.local/lib/chromium-deps` and `~/.bashrc` exports `LD_LIBRARY_PATH` (non-login shells must export it themselves). Extra tooling: `~/validation-tools/` (live gate scripts), `~/ui-review/` (screenshot sweeps), `~/AGENT-CONNECT.md` (older note). The agent connection guide for Claude on the user's Windows desktop is the Claude Doc https://claude.ai/code/artifact/850097ee-1d9f-4b35-ab51-1e771644b0bd (written 2026-09-18).

**Why:** earlier notes (before 2026-09-17) said no Docker/sudo/labs; that is no longer true and live-lab validation can happen here.

**How to apply:** live checks may be run on this host; judge node readiness from `/api/state`, never `docker logs`; refresh helpers (`sudo bash deploy/setup-git.sh --refresh`) after editing `host_*.py`. See [[user-pr-workflow]] and [[fixture-manager-browser-validation]].

On 2026-09-18 from about 14:45 (host uptime ~30 h) every cJunosEvolved boot started failing with guest soft lockups, panics or a post-init hang, on labs that had booted fine hours earlier; routers that came up lost SSH minutes later. Eight deploys, cache drop/compaction and new mgmt addresses did not help; load ~8/28, no swap, no steal. Suspect host-level degradation; a reboot of clab-llm-dev2 was recommended to the user. Check `docker logs <node> | grep -c 'soft lockup'` before blaming a lesson.

On 2026-09-27 the host crashed at about 21:32 UTC (journal simply stops; `last -x` says crash; boot 21:51) while a
`containerlab restart --node` check ran; the previous Claude Code session died with it. After the boot `dockerd`
panicked (`invalid freelist page …, page type is branch`) opening `/var/lib/docker/network/files/local-kv.db` (libnetwork's
bolt store). Recipe: `sudo mv local-kv.db local-kv.db.corrupt-<stamp>`, `sudo systemctl reset-failed docker && sudo systemctl
start docker`; Docker recreates the store, but every user-defined network is gone, so the lab needs `containerlab destroy`
+ `deploy` (the manager on host network restarts by itself) and the capture stack `sudo bash deploy/setup-capture.sh`
(which also recreates the manager). Configuration A goes back with `nodecli.py <node> --file docs/multi-platform-restore/lab/base-configs/<node>.cli`.
