# C1 — Section C preparation: states A / B / C and the repository fixtures — evidence

Build: manager `clab-backup:1.30.31` (image `3dfc4912c163`), built from commit `8ea56e0`
(`claude/save-location-fix`, pushed, `clab-backup-ui/app` clean). Helpers `1.30.31`, `http://127.0.0.1:8081`.
Lab `restore-square` (`904a35a79dc341ce8a4638f83fc34185`), bound to `save-fix/working`.

## Devices (image ids and NOS versions, read directly)

| Node | Address | Kind | Image | Image id (`docker inspect .Image`) | NOS version |
|---|---|---|---|---|---|
| ceos | 172.20.20.101 | arista_ceos | n24l/ceos:4.35.0F | `sha256:47b25129…` | EOS-4.35.0F-44178984.4350F (engineering build) |
| cjunosevolved | 172.20.20.102 | juniper_cjunosevolved | n24l/cjunosevolved:26.2R1.7-EVO | `sha256:d1dfc8bc…` | 26.2R1.7-EVO |
| vjunos-switch | 172.20.20.103 | juniper_vjunosswitch | n24l/vjunos-switch:23.2R1.14 | `sha256:12832fcb…` | 23.2R1.14 |
| xrv9k | 172.20.20.104 | cisco_xrv9k | n24l/cisco_xrv9k:24.3.1 | `sha256:1409cf12…` | IOS XR 24.3.1 |

## Deployment mismatch found and worked around (recorded, not silently absorbed)

`docs/multi-platform-restore/tools/readback.py`'s per-node `MARKERS` (and `square_check.py`'s OSPF
mesh/loopback pings) assume the richer restore-square configuration built for the multi-platform-restore
acceptance (interface descriptions `"A to-<neighbour>"`, `ip prefix-list RESTORE-A`, static routes to
`192.0.2.x`, an OSPF loopback mesh). Direct inspection of all four devices' running configuration on
2026-09-22 (before any change in this run) showed the bare containerlab day-0 default instead — this
`restore-square` instance was redeployed fresh (per `docs/save-location-fix/PICKUP.md` "Environment") and
never received that configuration; only `ceos` carried one leftover reversible `Ethernet2` description
from the B-matrix run (B8), removed first. `square_check.py`'s edge/loopback pings therefore fail on this
deployment (no interface has an address) and are **not evidence of a data-plane regression** — recorded
as a known limitation, not worked around by editing the shared tool (out of this task's assigned paths).
`readback.py`'s A/B markers likewise do not match; `docs/save-location-fix/tools/c_lib.py` defines its own
A/B/C classification from this deployment's actual configuration and the actual content of
`lab/drift/<node>-B.cli` (reused unmodified), independent of `readback.py`'s canned regexes.

## A / B / C definitions used for section C

- **A** = the bare deployed configuration (confirmed identical across saves before this run).
- **B** = A with `docs/multi-platform-restore/lab/drift/<node>-B.cli` applied verbatim over `nodecli.py`
  (one harmless "statement not found" warning per node, from a `delete`/`no` of an A-only statement this
  deployment's A never had — commit/end still succeeds; recorded in the raw JSON `drift_results_tail`).
- **C** = A with one new, node-specific marker statement not present in A or B: a description
  `SAVEFIX-C-<node>` on an interface untouched by A or B (`ceos` Ethernet3, `cjunosevolved` et-0/0/1,
  `vjunos-switch` ge-0/0/1, `xrv9k` GigabitEthernet0/0/0/1).

Independently verified distinguishable: `save-fix/Final/ceos.cfg` has neither marker;
`save-fix/Broken/ceos.cfg` has `vlan 777` / `description B changed`, no `SAVEFIX-C`;
`save-fix/working/latest/ceos.cfg` (state C) has `description SAVEFIX-C-ceos`, no B markers.

## What was built, through the product's real Save progress / Create checkpoint / Set baseline

| Step | Action | Job | Commit | Result |
|---|---|---|---|---|
| 1 | Save progress (state A) | `a9920ebac799be5777fdeede77d2d675` | `967f8945…` | synced, `save-fix/working/latest` |
| 2 | drift all four to B (nodecli, `lab/drift/*.cli`) | — | — | all four read `B` |
| 3 | Save progress (state B, temporary) | `82749caa5551…` | `0f6aa6bd…` | synced (self-healed from a transient `push_pending` — the single host lock racing the checkpoint save right after it, same documented behaviour as B-matrix row B2a; the commit was made locally at once and the push completed with the next Git operation) |
| 4 | Create checkpoint `state-B` | `2700120b3335…` | `76b832d8…` | synced, `save-fix/working/checkpoints/state-B` |
| 5 | undo B, add the C marker on all four | — | — | all four read `A` then `C` |
| 6 | Save progress (state C, current) | `0ef716150b37…` | `aa0d5467…` | synced, `save-fix/working/latest` |
| 7 | Set baseline… from the state-B checkpoint's capture | `e000587d2eb9…` | `cbed31b1…` | synced, `save-fix/working/baseline`; **byte-identical git tree** to the checkpoint's own tree (same underlying `backup_job_id`) |

One run of the preparation script raced the "Update from the repository" dropdown's own quirk (the
baseline `<select>` lists **backup jobs**, not Git-save jobs — value is `job.backup_job_id`, not the
checkpoint's own id) and crashed before seeding the repository fixtures; nothing was lost — the four
product-side saves above all completed and were re-derived from `GET /api/labs/<id>/git` rather than
repeated (`docs/save-location-fix/tools/c1_resume.py`).

### A self-caught and corrected mistake

The first seeding attempt's `git ls-tree <commit> -- <path>` call (no `-r`) returned only the directory
entry, not its files; combined with `git rm -r` on the pre-existing (B-matrix-era) `Final`/`Broken`/
`solution` content, this **emptied those three folders** in the second checkout and pushed the empty
commits (`b3acfbf`, `0c4d13c`, `0929d8a`) before the bug was noticed from the tool's own check output
(`"files": []`). Fixed (`-r`, filtered to direct children only) and corrected with new commits
(`ca8938b`, `68867d6`, `64c8fa0`, `9885f43`) restoring the intended content — verified below. No device
was affected; only the repository was briefly wrong, corrected within the same run before any Apply used it.

## Repository fixtures (second checkout, direct `git`, like a course maintainer)

| Folder | Layout | Content | Commit | Files |
|---|---|---|---|---|
| `save-fix/Final` | direct manifest | A | `ca8938b` (final: `9885f43`) | 9 |
| `save-fix/Broken` | direct manifest (no longer the legacy `Broken/latest` used for the B matrix) | B (from checkpoint `state-B`) | `9885f43` | 9 |
| `save-fix/Legacy/latest` | legacy layout (parent `save-fix/Legacy` has no manifest of its own) | A | `64c8fa0` | 9 |
| `save-fix/course/lab/reference/solution` | direct manifest, four levels deep | A | `68867d6` | 9 |

Second checkout `local HEAD == origin/main == 9885f430dd87181b69daa126d091dff8e2ee2b37`.

## Discovery after Update from the repository

`data-git-action="update"` (More… menu) → `#git-update-dialog` → Update now → `POST /labs/<id>/git/update`.
Binding line unchanged afterward: `restore-square saves to CLAB-MNGR-DEV-LLM › save-fix/working ›
latest/` (`latest/latest` never appears). `GET /api/labs/<id>/git/history` lists all seven expected
paths: `save-fix/Final`, `save-fix/Broken`, `save-fix/course/lab/reference/solution`,
`save-fix/Legacy/latest`, `save-fix/working/checkpoints/state-B`, `save-fix/working/baseline`,
`save-fix/working/latest`. Screenshot `20-saved-versions-prepared.png`.

## State left for C2 onward

All four devices read **C** (`docs/save-location-fix/tools/c_lib.py classify_all()`). Binding
`save-fix/working`; local == origin at `9885f43…`. Source commits for the matrix: state A =
`967f8945464abbed87ce49830f531ba200ff2e91`, checkpoint state-B = `76b832d873f259964bbd6cbfc6e57e2f88cdc1ab`,
state C (current working/latest) = `aa0d546765a2b1dd5d0bd1bd578d7ebc408b5020`.

## Result: PASS (20/20 checks, `docs/save-location-fix/tools/c1_resume.py`, raw record `20-c-preparation.json`)

Known limitation carried forward: `square_check.py`'s data-plane pings cannot pass against this
deployment (no interface addressing) — see "Deployment mismatch" above; C6's data-plane row records
this rather than a false pass.
