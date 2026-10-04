---
name: clab-host-ops
description: "Administer the assigned development VM and preserve CLAB host-helper boundaries."
---

# clab-host-ops

The assigned disposable VM authorizes sudo, apt/package repair, Docker builds,
containerlab operations, helper refreshes, service restarts and disruptive tests
within its assigned labs. Do not repeatedly request permission for these authorized
steps. Discover CPU/RAM/disk, Docker context, KVM availability, manager location and
lab ownership first. Clear only identified unused caches/artifacts; never blanket
prune needed proprietary images, worktrees, configs or the other worker's lab.

The shipped gateway still has exact command names, structured stdin, fixed argv,
trusted roots, review digests, ownership and locking. Never grant the application
arbitrary host commands or a Docker socket to make a test convenient. Installed
helpers and manager versions must match after an isolated-VM deployment.

Single-device restart uses the current containerlab native node restart path,
matching the extension's behavior; inspect installed CLI help and upstream source
for exact syntax. Do not substitute docker restart, NOS reload, or destroy/redeploy.
Verify the selected topology/node/container, peers' uptime and traffic, readiness
transition, CLI reconnection and stored manager state.

One mutating live-lab test at a time per VM, unless independently isolated labs and
resources are verified. Stop on evidence that the target is outside the assigned
VM; worker autonomy does not authorize production or unrelated remote resources.
