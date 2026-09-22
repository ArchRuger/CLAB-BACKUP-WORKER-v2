# C6 data-plane follow-up: real square configuration A, drift to B, Apply from `/save-fix/Final` — evidence

Build: `clab-backup:1.30.31` (image `3dfc4912c163`), commit `8ea56e0`. Lab `restore-square`
(`904a35a79dc341ce8a4638f83fc34185`), bound to `save-fix/working`. Operator: this QA follow-up session
(one operator, live lab and manager exclusively owned for the duration). Repository
`~/labs/CLAB-MNGR-DEV-LLM`, remote `pruger-dev/CLAB-MNGR-DEV-LLM`, `gh` on `pruger-dev`.

Closes the gap the C run recorded (`docs/save-location-fix/evidence/26-c6-summary.md` "Data plane: a
documented, pre-existing gap"; `20-c-preparation.md` "Deployment mismatch found and worked around"):
this `restore-square` instance had never received the real square configuration, so
`square_check.py` was "not applicable" throughout section C. All four nodes now run the real square
(`docs/multi-platform-restore/lab/base-configs/<node>.cli`: /31 edges `10.0.12/23/34/41.0`, loopbacks
`10.255.0.1`-`10.255.0.4`, OSPF area 0), `square_check.py` is fully applicable, and it was run before
load, after drift, and after the `/save-fix/Final` restore.

## 1. Loaded the real configuration A on all four nodes (`nodecli.py`, per-node `.cli` files)

Each base-config file's own final lines performed the persistence step named in the task (EOS
`write memory`, Junos `commit and-quit`, IOS XR `commit`); no separate persistence step was needed.
All four committed cleanly, no errors.

`square_check.py` immediately after (`30-c6-square-A-before.json`): **every edge both ways and the
full loopback mesh `3/3`, `ok: true`** for all four nodes. Boot identity unchanged from the
pre-existing deployment (`ceos` `boot_id cf6042b3-484d-4495-8eea-58392edd3d05`; the Junos/IOS XR boot
timestamps/uptime matched the values already on record from `29-c-square-final.json`) — loading A was
configuration only, no device was rebooted.

## 2. Through the product: Save progress, then Final = square A

`docs/save-location-fix/tools/c6_save_and_seed.py` (real Playwright browser against the running
manager; second checkout for the out-of-band copy, exactly the pattern `c1_prepare.py` used for the
original fixtures) — 10/10 checks passed (`30-c6-save-seed.json`):

1. Save progress reached `synced` at `save-fix/working/latest`, commit `4d7c9045fb5002aa5746e…`.
2. Second checkout extracted that commit's `save-fix/working/latest` tree byte-exactly
   (`git show <commit>:<path>`, no `.strip()` — the same corruption the original C1 note warns
   about is avoided the same way).
3. **Every extracted file's sha256 and size were checked against the extracted `manifest.json`
   before any push** (`checksum_report_before_push`, all `match: true`); the push would have been
   skipped had any mismatched.
4. `save-fix/Final` replaced (9 files: `ceos.cfg`, `ceos.eoscfg`, `cjunosevolved.jcfg`,
   `cjunosevolved.set`, `manifest.json`, `vjunos-switch.jcfg`, `vjunos-switch.set`, `xrv9k.cfg`,
   `xrv9k.xrcfg`), commit `245df9d014e65f173d34d591b1228dd981070716`, pushed; second checkout local
   HEAD == `origin/main` afterward.
5. *Update from the repository* run in the product; binding line still
   `restore-square saves to CLAB-MNGR-DEV-LLM › save-fix/working › latest/` (never `latest/latest`).
6. `/save-fix/Final` proven to read at the new commit two ways: `/git/history`'s own row for
   `save-fix/Final` carries `commit: 245df9d0…` (the exact pushed sha — `30-c6-history-after-final-seed.json`,
   folded into the evidence JSON's `history_final_row`), and the product's own `/git/version` call for
   `{commit: 245df9d0…, path: '/save-fix/Final'}` returned HTTP 200 with the manifest's files.
   Screenshot `30-c6-final-seeded.png` (Saved versions after the update).

## 3. Drift to B on all four (`lab/drift/<node>-B.cli`)

All four committed cleanly this time (unlike the earlier bare-day-0 run in `20-c-preparation.md`,
which logged one harmless "statement not found" warning per node because the deployment's original A
never had the `RESTORE-A` prefix-list/route the drift file tries to remove — this run's A is the real
square, so the delete targets that now genuinely exist). Independently reclassified `B` on all four
(`docs/save-location-fix/tools/c_lib.py classify_all()`).

`square_check.py` after the drift (`30-c6-square-B-drifted.json`): **still `ok: true`, every edge and
loopback `3/3`, on all four nodes.** This is not a tooling gap: `lab/drift/<node>-B.cli` changes
interface *descriptions*, adds an unreferenced `B-ONLY` prefix-list, a discard static route to
`198.51.100.0/24`, and (on `ceos`/`vjunos-switch`) an unused VLAN, and (on `xrv9k`) an unused
`Loopback777` — none of the four files touch an interface's IP address, `ip ospf`/`protocols ospf`/
`router ospf` stanza, or `no shutdown` state. B is drift *of the saved configuration*, not of the
data plane; the square staying healthy after B is a fact about `lab/drift/`'s own content, recorded
here rather than assumed away.

## 4. Apply `/save-fix/Final` from the folder browser to all four (real browser)

`docs/save-location-fix/tools/c_apply.py --entry folder --path save-fix/Final --expect-state A
--saved-dir ~/labs/CLAB-MNGR-DEV-LLM/save-fix/Final --label c6-square` — **18/18 checks passed**
(`30-c6-apply-final.json`):

- Review: `Source: … save-fix/Final · commit 245df9d014` (exact path + 10-char commit), four eligible
  rows shown, all four nodes checked before submit. Screenshot `30-c6-review.png`.
- Restore job `7edff056f123435e89901b0909272c17` submitted and reached **`succeeded`**; result
  screenshot `30-c6-result.png`. Lab binding unchanged (still `save-fix/working`, no nesting). No
  page/console errors.
- Independent verification, per node: `c_lib.classify()` reads **A** on all four; boot identity
  unchanged (no reboot) on all four; `readback.py --saved` whole-configuration comparison against the
  actual `save-fix/Final` checkout on disk: **`missing=0`, `extra=0`** beyond the one documented,
  tolerated Junos `root-authentication` exclusion, on all four nodes.
- Pre-restore backup job `ab51353ce4184f4692908062f017073d`; post-restore backup job
  `190f587e403d4b09af91ad6d89ea8e41`. Per-node target status: all four `verified`
  ("Configuration replaced and verified against the saved desired state."), `no_op: false`,
  `persistence: saved`. Overall job status `succeeded`.

`square_check.py` after the restore (`30-c6-square-A-after.json`): **every edge both ways and the
full loopback mesh `3/3`, `ok: true`, all four nodes** — the gap the C run flagged is closed; boot
identity unchanged from before the restore (no reboot anywhere in this section).

## 5. Repository and binding, unchanged by Apply

`save-fix/Final`'s tree hash at HEAD was `9ba68dcc67bcbe1d0658d5bfeebeb65ac68448fe` before the restore
and the identical `9ba68dcc67bcbe1d0658d5bfeebeb65ac68448fe` after (the repository HEAD never moved
between the seed push and the check after the restore — Apply never writes to the repository, per the
invariant in `docs/save-location-fix/PICKUP.md`). Binding prefix before and after:
`save-fix/working`, unchanged. Local checkout HEAD == `origin/main` ==
`245df9d014e65f173d34d591b1228dd981070716` throughout.

## 6. One normal backup after everything else

`manager_restore.py --backup-now`, run twice (once without `--evidence` while diagnosing an early-exit
path that skips the flag, once redirected to file): job `0fe0781b3eb84b89b45ead1751ad1e98` then job
`32b038c3908e42a9b3279cc4f4207d52` (`30-c6-final-backup.json`), **both `status: succeeded`, all four
nodes `succeeded`** each time.

## Per-node result

| Node | Load A | Drift to B | Apply `/save-fix/Final` | Data plane after | Result |
|---|---|---|---|---|---|
| ceos | committed, `write memory` | committed, reclassified B | `verified`, no reboot, whole-config match | edges+loopbacks `3/3` | **PASS** |
| cjunosevolved | committed, `commit and-quit` | committed, reclassified B | `verified`, no reboot, whole-config match | edges+loopbacks `3/3` | **PASS** |
| vjunos-switch | committed, `commit and-quit` | committed, reclassified B | `verified`, no reboot, whole-config match | edges+loopbacks `3/3` | **PASS** |
| xrv9k | committed, `commit` | committed, reclassified B | `verified`, no reboot, whole-config match | edges+loopbacks `3/3` | **PASS** |

No BLOCKED rows: `square_check.py` passed cleanly at every checkpoint it was run, so the 30-minute
retry contingency in the task was not needed.

## Lab state at handoff

- All four nodes run the real square configuration A (identical to `save-fix/Final`'s content),
  independently confirmed by `c_lib.classify()`, `readback.py --saved` and `square_check.py`.
- `square_check.py` reports `ok: true` — every edge both ways, full loopback mesh.
- Binding: `restore-square` → `CLAB-MNGR-DEV-LLM` › `save-fix/working` › `latest/`, unchanged
  throughout this section.
- Local checkout (`~/labs/CLAB-MNGR-DEV-LLM`) HEAD == `origin/main` ==
  `245df9d014e65f173d34d591b1228dd981070716`.
- `gh` active account: `pruger-dev`.
- New tooling added (verification only, this task's assigned paths):
  `docs/save-location-fix/tools/c6_save_and_seed.py`. No product source, configuration or test file
  was changed.

## Sanitization note

Raw device transcripts stay outside Git (`~/research/multi-platform-restore/raw/`, `nodecli.py`'s own
convention). Evidence JSON/MD here carry only job ids, commit shas, booleans, counts and the marker
strings already used throughout this project (`SAVEFIX-C-*`, `description B changed`, `B-ONLY`) —
no full configuration text, no passwords. Screenshots compressed with `pngquant --quality=40-70`.
