# Fresh install of 1.30.47 in a nested VM (2026-09-27)

Tool: `docs/technical-audit/tools/fresh_install_vm.py` (QEMU/KVM, an unmodified Ubuntu 24.04 cloud image, 6 vCPU,
8 GiB, a 30 G copy-on-write disk, cloud-init seeding the `student` account), isolated from the host's manager,
`/srv` and `/etc`. The source is `git archive` of the release commit `b3404f8` (prefix `clab-manager/`), staged as
`~/projects/clab-manager` inside the guest; `deploy/verify-release.py` answered `Source release verified: 1.30.47`
there before the installer ran.

Stages and results (raw logs kept out of the evidence: the installer transcript and health report live in the
session scratch):

- `installer`: `deploy/install.sh` driven interactively over SSH to the end of its guided steps, stopping at the
  Git wizard as the tool does by design (no Git registry on a brand-new VM).
- `health` (`deploy/check-install.sh` inside the guest): **32 PASS, 0 FAIL, 3 WARN, 2 SKIP, 2 INFO**.
  `[PASS] Running application version` (matches the source release), **`[PASS] Network design engine — netlab 26.9
  inside the image; planning and Apply to devices are available`** (the engine ships in the image: nothing was
  installed on the guest for it). The warnings and skips are the state of a fresh VM whose operator has not yet
  finished the wizards: the Git helper not installed (the wizard was not run), the VM connection not yet confirmed
  in the manager, no Git registry; the topology browser and the Git registry checks skipped for the same reason.
- `state`: `/api/state` answers with `version 1.30.47`, no labs, the platform table.
- `inventory`: helper files `clab_manager_files.py` (`helper_version 1.30.47`) and `host_operations.py`
  (`VERSION 1.30.47`) installed; no Grafana or telemetry remnant in `host_operations.py`; no `host_git.py` (not
  installed, see above).

What this proves: a VM that never saw the manager installs this release from the archive alone, runs the image
that carries the pinned engine, and its health check reports the engine as its own item. What it does not prove:
the Git wizard and a VM connection on that guest (the tool stops before them), and upgrade from an earlier
release on a real installation (the development VM was upgraded in place through every release of this stream,
with the helpers refreshed by hand as `PICKUP.md` records).

Cleanup: the QEMU process was stopped and the scratch disk discarded after this record was written.
