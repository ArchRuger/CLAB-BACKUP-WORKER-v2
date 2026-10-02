---
name: stagger-junos-boots
description: "When cJunosEvolved VMs hang or lock up at boot on this host, redeploy with containerlab startup-delay of 10 minutes per router; do not reset guests by hand"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: d39f9f66-a051-4ff6-8897-f7d3c22aeafe
  modified: 2026-09-19T18:14:25.058Z
---

When cJunosEvolved routers fail to boot on the lab host (soft lockups, reinstall loops, VMs spinning at 400 % CPU with a silent console), stagger the starts greatly: `startup-delay: 0` for the first router, `600` for the second, `1200` for the third, and so on, then redeploy through the manager.

**Why:** The owner said so on 2026-09-19 during Lesson 10, after three deploys of four routers each lost one to three VMs; a 90-second stagger had not helped, and the owner rejected my attempt to reset hung guests through the qemu monitor (`system_reset` on port 8701 inside the container).

**How to apply:** Put `startup-delay` in the lesson's `.clab.yml` before the first redeploy attempt after a boot failure; expect the deploy operation to take (N-1) x 10 minutes plus boot time and use the wait for writing. Do not poke at qemu monitors or restart containers. See also [[junos-states-carry-mgmt-address]].

**Update 2026-09-19 (evening):** the manager's deploy operation is killed after 20 minutes (hardcoded `timeout=1200` in `clab-backup-ui/app/host_operations.py`), so with four routers 10-minute steps cannot be deployed through it. `startup-delay` 0/360/720/1080 fits (deploy took 18 min) and all four Lesson 10 routers booted cleanly with it, right after the owner rebooted the host VM. Before that reboot four deploys had failed, including a 0/600 one, so when VMs spin at ~380 % CPU with silent consoles, ask the owner for a host reboot rather than trying more staggers. Watch boots with one light poll (every 30 s), not several SSH loops.
