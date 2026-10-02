---
name: technical-audit
description: "2026-09-23 technical audit stream — telemetry/Grafana retired (1.30.39), debt closed in 1.30.40–1.30.42 on claude/technical-audit, PR #54; records and pickup under docs/technical-audit/"
metadata:
  node_type: memory
  type: project
  originSessionId: f71c2c82-f281-47da-9b5b-2f3a11b8e717
  modified: 2026-09-23T13:54:52.238Z
---

Technical audit delivered 2026-09-23 on branch `claude/technical-audit` (PR #54, base `main` `b1ced1d`), four
releases: 1.30.39 (telemetry + Grafana retired, `app/telemetry_retirement.py` and `deploy/retire-telemetry.sh` are
the only remnants), 1.30.40 (frontend/tooling/guides), 1.30.41 (editor dependency overrides + rebuilt bundle,
lazydocker checksum, prepared-image recreate, loopback capture ports), 1.30.42 (bounded job lists, scrub before
the output window is cut, git timeout). Final records commit `b8da59c`, CI green on every push.

**Why:** the maintainer authorised the removal (feature never used); everything else is preserved with live proof.

**How to apply:** read `docs/technical-audit/PICKUP.md` first (state, remaining debt in AUDIT.md §3). The dev VM
runs 1.30.42 from `~/projects/clab-manager-1.30.42`; `restore-square` is at configuration A, bound to
`restore-square/qa-1-30-37` (newest commit `27ccd71`). Pre-migration copies live under
`/srv/containerlab-node-manager/data.pre-telemetry-retirement-*` and the retired stack's archives under
`telemetry-retired-*` (operator's to delete). Node 24 is at `~/.local/node24` (needed for `node build.mjs`); a
fresh-install nested VM can be replayed with `docs/technical-audit/tools/fresh_install_vm.py` (QEMU/KVM, the
account is in the `kvm` group; use `sg kvm -c`). Never reintroduce telemetry; the retirement is final. See
[[user-pr-workflow]] for the push accounts and [[dev2-host-environment]].
