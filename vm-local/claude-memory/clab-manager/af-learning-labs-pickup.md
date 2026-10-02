---
name: af-learning-labs-pickup
description: Where to resume the AF-LEARNING-LABS course work after the 2026-09-18 host reboot (Lesson 7 recording is the open item)
metadata:
  type: project
---

Open item as of 2026-09-18 19:00 UTC: Lesson 7 (Intro to BGP) is built but its lab listings are not recorded, because every cJunosEvolved boot on clab-llm-dev2 was failing (guest soft lockups / panics); the user rebooted the VM to clear it. The step-by-step continuation is in the repository: `/home/clabllm/projects/AF-LEARNING-LABS/lessons/07-intro-to-bgp/PICKUP.md` (deploy, verify no lockups, run the recording chain, write the guide stubs individually, build, deliver, destroy). Lesson 8 is finished and delivered. All work is pushed to `ArchRuger/AF-LEARNING-LABS` main (be71b95 and after); nothing depended on /tmp except lab ids, which `/api/state` gives back by name.

**Why:** the session was cut by a host reboot; the next agent must not rebuild what exists.

**How to apply:** read PICKUP.md first, then [[af-learning-labs-project]] for the course facts and [[dev2-host-environment]] for the host caveats (check `docker logs <node> | grep -c "soft lockup"` before trusting a boot).
