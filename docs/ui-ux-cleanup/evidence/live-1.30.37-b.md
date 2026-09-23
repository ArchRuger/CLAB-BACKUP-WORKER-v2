# Live acceptance, release 1.30.37, pass B (E1-E7, F1, F2, D1)

Independent verification, run against the real manager (`clab-backup:1.30.37`, container
`containerlab-node-manager-backup-ui-1`) and the real `restore-square` lab (id
`174386ec12ee496190c585c5796b2662`), by the operator assigned this lab and this manager's
save/restore functions for this pass. Nothing here ran against a fixture or disposable data.
Product source, tests and other agents' evidence files were not touched; only new files under
`docs/ui-ux-cleanup/tools/` (`live_1_30_37_b.py`, `isolation_all_four.py`) and evidence files
prefixed `r37b-` were written. Raw device transcripts (`nodecli.py`) went to
`~/research/multi-platform-restore/raw/` and `~/research/ui-ux-cleanup/raw/`, outside Git; no
credential text appears below (device logins are the kinds' published containerlab defaults from
`docs/multi-platform-restore/tools/nodecli.py`'s `NODES` table, never printed here).

Distinguishing the kinds of check used throughout: **code inspection** (reading `git-progress.js`,
`git-places.js`, `restore.js`, `diff-view.js`, `capture.js`, `capture_sessions.py`, `capture.py`
to find real selectors and routes before automating anything), **browser checks** (Playwright,
headless Chromium, against the real manager UI), **live device checks** (`nodecli.py`, direct SSH,
independent of the manager's own drivers), and **API checks** (`curl`, `manager_restore.py`,
`gh api`). No unit/fixture tests were run in this pass; that is out of scope for a live-only
assignment and is not claimed here.

## Environment

- Manager: `/api/state` version `1.30.37`, container up ~1 minute when this pass started (freshly
  rebuilt by the lead), confirmed with `curl .../api/state`.
- Lab `restore-square`: 5/5 containers running, NOS readiness 5/5 ready throughout.
- Git checkout: `~/labs/CLAB-MNGR-DEV-LLM`, remote `pruger-dev/CLAB-MNGR-DEV-LLM`, branch `main`,
  repository id `96a38e04661d4266bd072a6490bf44da` (later re-registered as `ea54cc8842384a72b4d1c72ac8ad7cda`
  once its prefix moved off the repository root — see step 2's environment note).
- Tools used as-is (imported/invoked, never edited): `docs/multi-platform-restore/tools/{nodecli.py,
  square_check.py, readback.py, manager_restore.py, failure_harness.py, mixed_failure.py}`.
- New tools written for this pass (`docs/ui-ux-cleanup/tools/`):
  - `live_1_30_37_b.py` — Playwright, phase-selectable (`--phase`), one browser session per phase,
    conventions copied from `docs/ui-ux-cleanup/tools/check_release_1_30_36.py` (`Run`/`shot`/`rec`,
    `goto_home`/`open_lab`/`tab`).
  - `isolation_all_four.py` — imports (never edits) `manager_restore.py` and `failure_harness.py` to
    submit a real four-node restore and cut management to one node mid-run, recording every target's
    timeline (failure_harness.py's own `submit-cut` submits only the named node; this pass needed
    all four submitted together with one node blocked, per the design doc's E7 isolation check).

## Summary table

| # | Check | Result | Evidence |
|---|---|---|---|
| 1 | Baseline: `square_check.py`, `readback.py --expect A` | PASS | `r37b-baseline-square.json`, `r37b-baseline-readback-A.json` |
| 2 | E1/E3 browser: connect a save location, create a NEW folder, Save progress with mandatory label and review | PASS | `r37b-phase-connect-save-a-report.json`, `r37b-save-a-evidence.json`, screenshots below |
| 3 | Drift all four to B (`nodecli.py`), `readback.py --expect B`, `square_check.py` | PASS | `r37b-drift-b-readback.json`, `r37b-square-after-b.json` |
| 4 | E1/E4 browser: Save progress again (label "Configuration B"), review shows real unified diffs per platform | PASS | `r37b-phase-save-b-report.json`, `r37b-save-b-evidence.json`, `r37b-save-b-compare-sanitized.json` |
| 4b | F1: one `restore-square/qa-1-30-37/latest/` (no nested `latest/latest`); "Configuration A" and "Configuration B" distinct in history | PASS | `git log`, `gh api` tree listing below |
| 5 | E2: "Saves waiting to be uploaded" / history → "View configuration backup" leaves no stale save dialog open | PASS | `r37b-phase-e2-report.json`, `r37b-e2-after-view-backup.png` |
| 6 | E5: Saved versions → "Configuration A" (history) → "Apply to running lab…" shows per-device differences and an expandable saved-vs-running diff; cancelled | PASS | `r37b-phase-e5-cancel-report.json`, `r37b-e5-restore-review.png` |
| 6b | F2: the folder browser offers the same "Apply to running lab…" for `restore-square/qa-1-30-37` (via its `latest/` snapshot) | PASS | same report, `r37b-f2-folder-browser-apply.png`, `r37b-f2-restore-review-from-folder.png` |
| 7 | E6/E7: real four-node restore to Configuration A via the API (`manager_restore.py --commit --path`), browser progress screenshotted mid-run and at the end, overlap proved from the job document | PASS | `r37b-restore-all-four-2.json`, `r37b-phase-restore-progress-screenshot-report.json`, mid-run screenshots (the series was trimmed by the lead to `midrun-5`, `midrun-22` and `final` to keep the repository small) |
| 7b | Post-restore: `readback.py --expect A --saved <commit-A checkout>`, `square_check.py` | PASS | `r37b-postrestore-readback.json`, `r37b-postrestore-square.json` |
| 8 | Sequential-baseline comparison (`RESTORE_NODE_WORKERS=1`) | **SKIPPED** (would need a manager restart, which this pass may not do) — cited a stored baseline instead | see "Step 7 (sequential baseline)" below |
| 9 | Partial failure / isolation: drift to B, `isolation_all_four.py` cuts xrv9k at `applying`, all four submitted together | PASS | `r37b-failure-xrv9k.json` |
| 9b | Recovery of xrv9k to A, final readback/square check | PASS | `r37b-after-failure-recovery-readback.json`, `r37b-square-after-recovery.json` |
| 10 | Foreign change: `mixed_failure.py --folder restore-square/qa-1-30-37/latest` | PASS (with one documented tool-assumption caveat) | `r37b-mixed.json` |
| 11 | Restart recovery | **SKIPPED** (needs a manager restart; not run, as instructed) | — |
| 12 | D1 capture proof: right-click vjunos-switch↔xrv9k, endpoint `xrv9k` preselects `eth1`, real ICMP captured live; repeated for ceos↔xrv9k (`eth2`) | PASS | `r37b-d1-capture-watch-vjunos-switch-xrv9k-{3,5}.png`, `r37b-d1-capture-watch-ceos-xrv9k-2.png` (the other frames of each series were trimmed by the lead) |
| 13 | Final: `readback.py --expect A`, `square_check.py`, remote tree, no pending restore/save, no leftover capture sessions | PASS | `r37b-final-readback.json`, `r37b-final-square.json` |

Every numbered PASS above is a real browser action or a real device/API call against the running
manager and the live lab; nothing here is a unit or fixture result.

## Step-by-step detail

### 1. Baseline

`square_check.py`: all four edges both ways 3/3, full loopback mesh, `"ok": true`.
`readback.py ceos cjunosevolved vjunos-switch xrv9k --expect A`: all four `"active": "A"`, no
`pending_confirmation`. (`r37b-baseline-square.json`, `r37b-baseline-readback-A.json`)

### 2. E1/E3 — connect a save location, new folder, label, mandatory review

**Environment note (not a product defect in this pass's scope):** the repository root (prefix `''`)
already carried a free, unclaimed folder registration left over from earlier work on this VM.
`git-places.js`'s `gitOwningFolder` treats a root registration as owning the whole tree, so *New
folder…* was disabled everywhere until this lab actually held that registration. The recovery this
pass used is the one already documented in `docs/save-location-fix/PICKUP.md` ("Reviews": *Save this
lab here without moving the files*): connect at the free root first (`PUT /labs/{id}/git`), then use
*Change folder… → New folder…* to create `restore-square/qa-1-30-37` and move there in the same step
(`POST /labs/{id}/git/destination`) — both reviewed, existing routes; no workaround outside them. One
side effect: the accompanying "move N files" job raced the connect step's own Git status check
("Another Git operation is already running") since there were 0 files to move anyway; the prefix
move itself still applied (confirmed via `/api/labs/.../git` immediately after). This is recorded in
`r37b-phase-connect-save-a-report.json` as an INFO item, not counted as a FAIL.

Browser flow (`connect_save_location` in `live_1_30_37_b.py`), all PASS:
- Progress tab shows "Choose a save location" (no binding yet).
- Repository `CLAB-MNGR-DEV-LLM` listed and selectable.
- Folder created and the lab connected to it; destination line reads
  `Saving to CLAB-MNGR-DEV-LLM › restore-square/qa-1-30-37` (never `.../latest/latest`).
- *Save progress* → label dialog "What changed?" appears; empty label refused with
  *"Give this save a short label."*; label `Configuration A` accepted.
- Review dialog **opens automatically** (mandatory review — `git-progress.js`'s quiet watch calls
  `gitReviewJob` itself once the job reaches `review_pending`), titled "Review before uploading",
  destination line `Saving to CLAB-MNGR-DEV-LLM › main › restore-square/qa-1-30-37/latest`.
- File list: `ceos.cfg`, `ceos.eoscfg`, `cjunosevolved.cfg`, `cjunosevolved.jcfg`,
  `vjunos-switch.cfg`, `vjunos-switch.jcfg`, `xrv9k.cfg`, `xrv9k.xrcfg` — every Junos kind carries
  both `.cfg` (human, display-set text) **and** `.jcfg` (machine restore artifact); EOS and XR each
  carry `.cfg` alongside their existing machine artifact. This is A1 in the requirement map ("make
  sure all Junos config backups save as .cfg"), confirmed live.
- *Upload these changes* → job dialog "Progress saved", Label `Configuration A`, Destination
  `CLAB-MNGR-DEV-LLM · main · restore-square/qa-1-30-37/latest`, Commit
  `f12421e615d13adb938906621f0510b46d874283`, Checkout `/home/clabllm/labs/CLAB-MNGR-DEV-LLM`.

Independent confirmation (outside the browser):
```
$ git -C ~/labs/CLAB-MNGR-DEV-LLM log -1 --format=%s
Configuration A
$ gh api repos/pruger-dev/CLAB-MNGR-DEV-LLM/contents/restore-square/qa-1-30-37/latest
ceos.cfg  ceos.eoscfg  cjunosevolved.cfg  cjunosevolved.jcfg  manifest.json
vjunos-switch.cfg  vjunos-switch.jcfg  xrv9k.cfg  xrv9k.xrcfg
```
Screenshots: `r37b-e1-folder-browser-root.png`, `r37b-e1-new-folder-dialog.png`,
`r37b-e1-connected.png`, `r37b-e1-e3-save-a-empty-label-refused.png`,
`r37b-e1-e3-save-a-review-dialog.png`, `r37b-e1-e3-save-a-job-saved.png`.

### 3. Drift to B

`nodecli.py <node> --file lab/drift/<node>-B.cli` on all four; `readback.py --expect B` → all four
`"active": "B"`; `square_check.py` → `"ok": true` (mesh unaffected). (`r37b-drift-b-readback.json`,
`r37b-square-after-b.json`)

### 4. E1/E4 — real diff review, F1 stable destination

*Save progress* again, label `Configuration B`. Review dialog opened automatically again; file list
now says `changed` for every file (not `added`). Sanitized real diff, pulled from the same
`/git/compare` route the dialog itself calls (`r37b-save-b-compare-sanitized.json`), one hunk per
platform (comment lines and secrets excluded by the manager itself; nothing further was redacted
here because none of these hunks contain secrets):

**EOS** (`ceos.cfg`, `@@ -22,6 +22,9 @@`):
```
    unsupported error-correction action error
 !
+vlan 777
+   name B-ONLY
+!
 management api gnmi
```

**Junos, display-set** (`cjunosevolved.cfg`, `@@ -7,16 +7,17 @@`):
```
 set system services ssh
-set interfaces et-0/0/0 description "A to-ceos"
+set interfaces et-0/0/0 description "B changed"
 set interfaces et-0/0/0 unit 0 family inet address 10.0.12.1/31
```

**IOS XR** (`xrv9k.cfg`, one of several hunks, `@@ -31,21 +34,22 @@`):
```
 interface GigabitEthernet0/0/0/0
-  description A to-vjunos-switch
+  description B changed
  ipv4 address 10.0.34.1 255.255.255.254
 !
...
+prefix-set B-ONLY
+   198.51.100.0/24
+end-set
+!
```

Job dialog after upload: title "Progress saved", Label `Configuration B`, Destination
`CLAB-MNGR-DEV-LLM · main · restore-square/qa-1-30-37/latest`, Commit
`795edb28ae04fd9c3420914044c22856aba5d511`.

**F1** confirmed independently:
```
$ git -C ~/labs/CLAB-MNGR-DEV-LLM log -2 --oneline
795edb2 Configuration B
f12421e Configuration A
$ gh api repos/pruger-dev/CLAB-MNGR-DEV-LLM/contents/restore-square/qa-1-30-37
latest
```
One `latest/` folder, never `latest/latest`; two distinct commit subjects; both jobs listed
separately (by id, commit and note) in `/api/labs/.../git`'s job history.

Screenshots: `r37b-e1-e4-save-b-review-dialog.png`, `r37b-e1-e4-save-b-job-saved.png`, `r37b-f1-history.png`.

### 5. E2 — no stale dialog after "View configuration backup"

Opened the most recent save's job dialog, clicked "View configuration backup" (the button
`[data-git-job-action="backup"]`), landed on Tools → Configuration backups with the action log open.
Assertion: `[...document.querySelectorAll('dialog[open]')]` contains none of
`git-job-dialog`/`git-diff-dialog`/`git-pending-dialog` afterwards. PASS (`r37b-e2-after-view-backup.png`
shows the destination panel with no leftover dialog/backdrop).

### 6. E5 / F2 — restore review diff and the folder-browser entry point

From Progress → *Saved versions & history* → Save history → "Configuration A" → "Saved version"
dialog → *Apply to running lab…*. The preflight (a live call to all four devices — devices were on B
at this point from step 4) took a few seconds; the review then showed, for example:

- ceos: **"6 differences from the running configuration"**, expandable "Show differences (saved →
  running now)" with a real diff table (`4 added · 2 removed`, hunk `@@ -10,12 +10,14 @@`, the B-only
  `vlan 777`/`name B-ONLY` lines shown as `+`, the reverted description shown as one `-`/`+` pair).

Cancelled without submitting (`#restore-review-dialog [data-op-close]`).

**F2**: from the same Progress tab, opened *Change folder…*, navigated the outline to
`restore-square/qa-1-30-37`, and confirmed `[data-git-places-action="apply"]` ("Apply to running
lab…") is offered there too — the folder browser's caption reads *"Applies this folder's latest save
(restore-square/qa-1-30-37/latest) to the running devices. They are not rebooted."* Clicking it opened
the identical "Replace running configuration" review. Cancelled.

Screenshots: `r37b-e5-history-dialog.png`, `r37b-e5-saved-version-dialog.png`, `r37b-e5-restore-review.png`
(shows the real ceos diff table), `r37b-f2-folder-browser-apply.png`, `r37b-f2-restore-review-from-folder.png`.

### 7. E6/E7 — real parallel restore, overlap proof

Real restore via the API (`manager_restore.py --commit f12421e615d13adb938906621f0510b46d874283
--path restore-square/qa-1-30-37/latest --nodes ceos cjunosevolved vjunos-switch xrv9k`), with a
Playwright session already sitting on the lab page polling for the running-restore banner
(`live_1_30_37_b.py --phase restore-progress-screenshot`), 500 ms between polls.

**Overlap proof, from the job document alone** (`r37b-restore-all-four-2.json`):

| Node | worker | connecting (epoch) | settled (epoch) | interval |
|---|---|---|---|---|
| ceos | restore-node_0 | 1790132109.494 | 1790132111.646 | 2.15 s |
| cjunosevolved | restore-node_1 | 1790132109.496 | 1790132115.108 | 5.61 s |
| xrv9k | restore-node_2 | 1790132109.506 | 1790132117.705 | 8.20 s |
| vjunos-switch | restore-node_3 | 1790132109.504 | 1790132133.101 | 23.60 s |

`max(connecting) = 1790132109.5063` (xrv9k) `< min(settled) = 1790132111.6457` (ceos)` — **overlap
proved**: every node's connect happened before the fastest node had even settled. Four distinct
worker names (`restore-node_0..3`). Job `progress.settled == 4 == total`. Whole job (including the
readback-before/after this tool also does): `02:54:55` → `02:55:38`, 43 s; the restore itself (first
`backing_up` to `succeeded`): `02:55:06` → `02:55:35`, 29 s.

Browser mid-run evidence: 23 screenshots over ~24 s of polling, each showing the live per-device
stage list; `r37b-e6-restore-progress-midrun-4.png` shows all four devices in **different** stages at
once (ceos "Confirming…", the other three "Applying…/Validate"); `r37b-e6-restore-progress-final.png`
shows "3 of 4 devices settled" (ceos, cjunosevolved and xrv9k "Replaced", vjunos-switch still
"Validate…16 s") shortly before the fourth settles — direct visual proof of overlap, not just the
timestamps.

Post-restore: `readback.py --expect A --saved /tmp/r37b-config-a-checkout` (a `git show` export of
commit `f12421e615d...`'s exact tree, so the comparison is against the pinned commit, not the
repository's current `latest/` which by then held Configuration B's text) — all four `"active": "A"`,
`missing: 0`, `extra: 0` (Junos images show `tolerated_root_authentication` per the documented
synthesis limit, not a mismatch). `square_check.py` → `"ok": true`.

### 7 (sequential baseline) — SKIPPED

Per the assignment, comparing against `RESTORE_NODE_WORKERS=1` would need a manager restart with a
different environment variable, which this pass may not do. Cited instead, as instructed: the
existing one-at-a-time all-four run recorded in `docs/multi-platform-restore/evidence/50-all-four-browser-desktop.json`
(build 1.30.29, before node-level parallelism existed) ran `2026-09-21T01:48:40Z` →
`2026-09-21T01:50:04Z`, 84 s end to end through the browser (includes UI navigation, not a clean
apples-to-apples number against this pass's 29 s API-only apply). No new sequential run was
performed; this is not claimed as a controlled comparison, only as the cited prior baseline.

### 8/9. Partial failure and isolation (all four submitted, one blocked)

`docs/multi-platform-restore/tools/failure_harness.py submit-cut` submits **only the named node**
(`node_names: [name]`), which does not exercise E7's isolation-under-parallelism claim (the design
doc calls for "the other three run in parallel" while one is cut). A small new tool,
`docs/ui-ux-cleanup/tools/isolation_all_four.py`, was written for this pass: it imports (never edits)
`manager_restore.py` and `failure_harness.py`'s `Manager`, `block`/`unblock`/`local_ports`/`rule_present`
and submits all four nodes in one job, applying `failure_harness.py`'s own `submit-cut` technique
(iptables `OUTPUT … REJECT` on the victim's management address, applied the instant its target
reaches `applying`) to xrv9k only.

Drifted all four to B again, then ran `isolation_all_four.py --victim xrv9k --commit
f12421e615d13adb938906621f0510b46d874283 --path restore-square/qa-1-30-37/latest`:

- xrv9k reached `applying` at t=5.6 s; the block landed 9 ms later (t=5.6 s), before its driver could
  connect.
- Full per-target timeline (`r37b-failure-xrv9k.json`) shows ceos, cjunosevolved and vjunos-switch
  running their own `connecting → applying → confirming → replaced` sequence **while xrv9k sat at
  `applying`/`connecting` the whole time**, then `failed` at t=21.7 s once its connection attempts were
  exhausted; the other three reached `verified` independently (vjunos-switch as late as t≈28 s).
- Job ended **`partial`**. `iptables -S OUTPUT` showed the rule present before unblock, absent after
  (`rule_present_before_unblock: true`, `rule_present_after_unblock: false`).
- **Outcome for xrv9k was `failed`, not `rolled_back`.** This is the behaviour `submit-cut`'s own
  docstring predicts ("Expect the target `failed` with a connectivity message, never a partial
  change") because the cut happens *before* the driver opens its connection, so nothing was ever
  armed on the device to roll back. The task text's expectation of `rolled_back` does not match a
  `submit-cut`-style trigger; `armed-cut` (a different subcommand, arming first) would be the one that
  produces a genuine `rolled_back`. Recorded here as a factual correction, not silently reinterpreted.
- Readback: `ceos`/`cjunosevolved`/`vjunos-switch` → `active: A`, `xrv9k` → `active: B`,
  `pending_confirmation: false` (nothing left armed on it).

**Recovery**: a plain `manager_restore.py --commit ... --nodes xrv9k` restored it to A in 12 s
(`succeeded`, `verified`). Confirmed with `readback.py --expect A --saved ...` on all four: `A`, 0/0
on every node; `square_check.py` `"ok": true`.

### 9 (continued). Foreign change (`mixed_failure.py`)

Per the assignment, ran with `--folder restore-square/qa-1-30-37/latest` (the tool drifts all four to
B itself first). **Environment caveat**: this folder's on-disk content at the time was still
Configuration B (the last *Save progress* in this pass, step 4) — a `{type:'folder'}` source reads
whatever is currently on disk, not a pinned commit, so the "replace" for the three non-victim nodes
was a no-op (they already matched). This does not weaken the isolation proof itself, which does not
depend on the source content changing:

```json
{
 "armed_before_victim_connected": true,
 "three_replaced_and_verified": true,
 "victim_failed_not_changed": true,
 "job_partial": true,
 "devices_agree": false,
 "foreign_change_left_alone_and_rolled_back_by_itself": true,
 "recovery_verified": true
}
```

`devices_agree` is the tool's own hard-coded assumption that the non-victim nodes end at "A" — true
for its default folder (`restore-square/work/latest`, historically Configuration A), false here only
because this pass pointed it at a folder that currently holds Configuration B. Every other, more
meaningful assertion is `true`: the foreign `commit confirmed 120` was armed on xrv9k before the
manager's own driver connected to it (proving the refusal is real, not a race won by luck); ceos,
cjunosevolved and vjunos-switch ran side by side and reached `verified`; xrv9k's target ended
`failed` ("not changed" — the foreign pending change was left alone, never touched); the job was
`partial`; the foreign change rolled back by itself at its own timer (xrv9k read back as
`active: B, pending_confirmation: false` after the foreign window); the recovery restore of xrv9k
alone afterwards reached `verified`.

Devices were left at B by this check by design (drift + no-op restore); restored to A in the final
cleanup restore (see below).

### 10. Restart recovery — SKIPPED

Needs a manager restart, per the assignment; not run.

### 11 (renumbered from the task's step 11). D1 — real capture traffic proof

**Primary pair, vjunos-switch↔xrv9k**: right-clicked the link on the Topology map; the endpoint
picker showed `vjunos-switch: ge-0/0/1` / `xrv9k: Gi0/0/0/0`; chose `xrv9k`; the interface checkbox
preselected **`eth1`** (matching the identity mapping documented in 1.30.36's D1 evidence). Clicked
*Start capture*; the manager opened a real Wireshark session on the VM
(`/static/capture-session.html#<64-hex session id>`). Followed the new tab in the same browser
context (capture-session tickets are browser-scoped, so a fresh browser cannot open another
browser's session — see "Tooling defect found and fixed" below), waited for "Connected to Wireshark
on the VM", then ran `nodecli.py vjunos-switch 'ping 10.0.34.1 count 15'` (the xrv9k side of that
/31, from `docs/multi-platform-restore/lab/base-configs`/PICKUP's known addressing) while
screenshotting the live packet list every ~3.5 s.

Packet list (`r37b-d1-capture-watch-vjunos-switch-xrv9k-3.png`, `-5.png`) shows real traffic on
`clab-restore-square-xrv9k · eth1`:
```
10.0.34.0 → 10.0.34.1  ICMP  Echo (ping) request  id=0x6552, seq=3/768, ttl=64
10.0.34.1 → 10.0.34.0  ICMP  Echo (ping) reply    id=0x6552, seq=3/768, ttl=255
```
15 request/reply pairs visible, interleaved with OSPF Hello packets on the same segment. Ended the
session from the viewer (*End session*, confirmed the browser's native `confirm()` dialog).

**Second pair, ceos↔xrv9k**: right-clicked; endpoints `xrv9k: Gi0/0/0/1` / `ceos: eth2`; chose
`ceos`; preselected **`eth2`** (identity mapping). Ran `nodecli.py xrv9k 'ping 10.0.41.1 count 15'`
(100% success, 3-8 ms). Packet list on `clab-restore-square-ceos · eth2`
(`r37b-d1-capture-watch-ceos-xrv9k-2.png`) shows:
```
10.0.41.0 → 10.0.41.1  ICMP  Echo (ping) request  id=0xa252, seq=1/256, ttl=64
10.0.41.1 → 10.0.41.0  ICMP  Echo (ping) reply    id=0xa252, seq=1/256, ttl=255
```
14 request/reply pairs visible. Session ended the same way.

**Tooling defect found and fixed, in `docs/ui-ux-cleanup/tools/live_1_30_37_b.py` only (not a
product change):** the viewer's *End session* button asks a native `confirm()`
(`capture-session.js:54`); Playwright auto-dismisses a JS dialog by default, so the first two runs'
"session ended cleanly" assertion was a **false positive** — the click did nothing, the manager never
saw a `POST .../end`, and the underlying Wireshark/VNC container (a fixed pool of 4,
`capture.py`'s `max_sessions`) stayed running. This was caught independently in this same pass (the
manager log showed zero `POST /api/capture/sessions/.../end` requests despite two recorded "PASS"es,
and a subsequent launch failed with `429 Too Many Requests`/"All browser capture slots are in use").
Fixed by having the tool accept the dialog (`page.once('dialog', ...)`) and by asserting on the real
`/end` HTTP response rather than the click alone; the two orphaned sessions from the buggy runs were
removed directly (`docker stop`/`docker rm` on the two leftover `clab-capture-clab-manager-capture-v1-*`
containers — infrastructure cleanup by the VM operator, not a manager or capture-service code path;
the capture service's own `/sessions` listing, queried directly with its bearer token, already showed
zero sessions at that point) so the pool could accept new launches; the two capture pairs above were
then **re-run** with the fix and their evidence regenerated (the files named above are the corrected,
verified runs; the filenames now include both link endpoints so a second pair's screenshots cannot
silently overwrite the first's, which is what happened on the very first attempt at this step and was
also corrected).

### 12/13. Final state

```
$ readback.py ceos cjunosevolved vjunos-switch xrv9k --expect A --saved /tmp/r37b-config-a-checkout
ceos           A  missing=0 extra=0  pending=False
cjunosevolved  A  missing=0 extra=0  pending=False
vjunos-switch  A  missing=0 extra=0  pending=False
xrv9k          A  missing=0 extra=0  pending=False
$ square_check.py  → "ok": true (all edges 3/3, full loopback mesh)
$ curl .../api/restore/jobs  → no restore job outside a terminal state
$ curl .../api/labs/.../git  → binding prefix "restore-square/qa-1-30-37"; all jobs "synced"/"unchanged"
                                except one terminal "failed" move job from step 2's environment note
                                (0 files, nothing to retry)
$ curl .../api/capture/sessions → {"sessions": []}
$ docker ps --filter label=org.clab-manager.capture-owner → (none)
$ gh api .../contents/restore-square/qa-1-30-37 → ["latest"]   (no nested latest/latest)
```
(`r37b-final-readback.json`, `r37b-final-square.json`)

## What was NOT run (say plainly)

- **Step 7's sequential (`RESTORE_NODE_WORKERS=1`) rerun**: skipped, needs a manager restart; cited
  the stored 1.30.29 baseline instead (see above), not a fresh apples-to-apples measurement.
- **Step 10, restart recovery**: skipped, needs a manager restart, as instructed.
- **Unit/fixture tests**: none run in this pass; out of scope for a live-only assignment.
- **Downloading the pcap and inspecting it with `tshark`**: not done; `tshark` was not confirmed
  installed and the live packet list in the browser already gave unambiguous proof (real
  request/reply pairs with the expected addresses, ids and TTLs). The *Download saved captures*
  control was not exercised.
- The leftover, orphaned "free" folder registration at the repository root (pre-existing on this VM,
  not created by this pass) was **not** cleaned up (removing a Git-repository-level registration is
  outside a QA operator's authority and outside this pass's file scope); it is recorded here only as
  the reason step 2 needed the connect-then-move route instead of connecting to a brand-new folder
  directly.

## Files

Evidence (all under `docs/ui-ux-cleanup/evidence/`, prefix `r37b-`): baseline/final
readback+square-check JSON, per-phase Playwright reports, save A/B evidence and sanitized compare
JSON, the isolation and mixed-failure JSON, and all screenshots named in the sections above.

Tools (`docs/ui-ux-cleanup/tools/`): `live_1_30_37_b.py`, `isolation_all_four.py`.
