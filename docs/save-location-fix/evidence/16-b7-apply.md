# B7 — Apply to running lab: four entry points, one real restore, edge cases — evidence

Build: `clab-backup:1.30.31` (image `d356c1d9253d`), helpers `1.30.31`, assets `?v=1.30.31`. Source
checkout HEAD `6c3e8b3` (dirty). Lab `restore-square`, bound to `save-fix/working` throughout (Apply
never rebinds). Tools: `docs/save-location-fix/tools/b7_apply.py` (four preflight entry points,
keyboard, 390px viewport), `b7_restore_submit.py` (the one real restore), `b7_stale_invalid.py`
(stale review, invalid commit). Raw records `16-b7-apply.json`, `16-b7-restore-submit.json`,
`16-b7-stale-invalid.json`.

## Result: PASS (8 + 6 + 9 checks; one script bug fixed and reissued, see below)

### Four entry points — review opened, source recorded, not submitted (except entry 1, below)

| Entry point | How reached | Source line | Eligible rows |
|---|---|---|---|
| (1) Folder browser at `save-fix/Final` | Change folder… → `save-fix` → `Final` → **Apply to running lab…** | `Final state (instructor) · CLAB-MNGR-DEV-LLM › save-fix/Final · saved 1 hour ago · b302cb04cb` | ceos: 1 diff; cjunosevolved/vjunos-switch/xrv9k: already match |
| (2) Save location's own browser | Save location → **Change folder…** (same `#git-places-panel`, opened from the Save location card instead of "Browse the repository…") → `save-fix/Final` → Apply | identical: `... save-fix/Final · saved 1 hour ago · b302cb04cb` | identical |
| (3) Saved versions row, nested `solution` | Saved versions → the `solution` row → **Apply to running lab…** | `Final state (instructor) · CLAB-MNGR-DEV-LLM › save-fix/course/lab/reference/solution · saved 1 hour ago · b302cb04cb` | identical (same content, different path) |
| (4) Full history → a commit → View → Apply | header quick-save menu → **Saved versions & history** → the `qa checkpoint a` commit (only this lab's own commits are listed; each already resolves to a known job, so `gitOpenCommit` opens the version view directly rather than the intermediate picker) → **Apply to running lab…** | `save-fix/working/checkpoints/qa-cp-a · saved 13 minutes ago · 7865961503` | ceos: 2 diffs; others already match |

Screenshot `1x-b7-entry2-save-location-browser.png`.

### Keyboard access

Folder browser: focused the first outline entry, `Tab` moved focus within the panel (confirmed via
`document.activeElement`), `ArrowDown` moved it again. Screenshot `1x-b7-keyboard-nav.png`.

### 390 px viewport

Progress tab at 390×844, full page: `1x-b7-390px-progress.png` (Saved versions groups visible).

### The one real restore: `save-fix/Final` on ceos only

Drifted ceos to configuration B first (`docs/multi-platform-restore/tools/nodecli.py ceos --file
lab/drift/ceos-B.cli`), confirmed independently with `readback.py ceos --expect B` → `active: "B"`,
all 4 B-only markers present.

Opened Apply from entry point (1), unchecked every device except ceos, ticked the acknowledgement,
submitted:

```
source: {type: folder, path: /save-fix/Final, commit: b302cb04cb0745867b1cdb7c5e4b9303f1c539ea}
job status: succeeded
target ceos: status "verified", "Configuration replaced and verified against the saved desired state."
             missing_statements: 0, extra_statements: 0
```
(The job's own `diff_sample` — a handful of removed-line markers from the drift and from the QA
description change — is redacted from the evidence files per the sanitization rule; the
`missing_statements: 0, extra_statements: 0` counts and the independent readback below are the
kept proof.)

**Independent readback** (`readback.py ceos --expect A --saved <local copy of save-fix/Final/ceos.eoscfg>`):

```
b_only_present: 0 of 4        <- every B-drift statement is gone
compared_with_saved: {saved_statements: 27, active_statements: 27, missing: 0, extra: 0}
                               <- ceos's active configuration is byte-identical (as statements) to save-fix/Final
```

Note: the tool's generic `active: "A"/"B"` classifier uses two markers
(`description A to-cjunosevolved` on Ethernet1, `ip prefix-list RESTORE-A ...`) from the original
multi-platform-restore acceptance lab's own baseline configuration, which this `save-fix/Final`
snapshot (captured from `restore-square`'s own earlier Latest save, not that baseline) never
contained — so `active` reports `"mixed"` rather than `"A"`, even though the byte-exact comparison
above and the zero B-only markers prove state A (as saved in `save-fix/Final`) is genuinely restored
and every B-only statement is gone. This is a difference in which "A" baseline is being asked about,
not a restore defect; the `compared_with_saved` and `b_only_present` fields are the correct proof for
this lab's own Final snapshot and are unambiguous (0 missing, 0 extra, 0 of 4 B-only markers).

Screenshots `1x-b7-real-restore-review.png`, `1x-b7-restore-running.png`,
`1x-b7-restore-reopened-from-banner.png`, `1x-b7-restore-final-status.png`.

### Reopen from the banner, refresh

While the job was `applying`/`confirming`, `#banner-restore` ("View progress"/"Details") was visible
on the lab banner; clicking it reopened `#restore-job-dialog` with live status. The page was then
reloaded; polling `/api/restore/jobs/<id>` afterward still returned the same job progressing to
`succeeded`, and the Progress tab's own "Details" link (`#git-last-restore-open`) opened the same
final result after completion.

### Stale review: commit pinning survives "Update from the repository"

1. Opened Apply on `save-fix/Final` (fresh review) — reviewed commit `b302cb04cb`.
2. From the second checkout (`gh repo clone pruger-dev/CLAB-MNGR-DEV-LLM`, throwaway identity),
   pulled, added a trivial comment line to `save-fix/Final/ceos.cfg` only (never `ceos.eoscfg`,
   the restore artifact), committed, pushed → new commit `62c2dffff...`.
3. **Without closing the open review dialog**, ran "Update from the repository" (the identical
   same-origin request `#git-update-confirm` sends — the modal `<dialog>` review blocks pointer
   events to the "More" menu behind it by design, exactly as it blocks every other background
   control, so the request was issued the same way the button's own handler does):
   `POST /api/labs/<lab>/git/update {}` → `{"status": "updated", "head": "62c2dffff..."}`.
   The review dialog was confirmed still open afterward.
4. Submitted the **already-open** review (ceos only again; ceos already matched `save-fix/Final`, so
   this is an idempotent, safe second application, not a new device change):
   - job's `source.commit` = `b302cb04cb0745867b1cdb7c5e4b9303f1c539ea` — the **reviewed, older**
     commit, not the new HEAD `62c2dffff...`.
   - job succeeded, target ceos: `no_op: true`, `missing_statements: 0`, `extra_statements: 0`.
   - `git show b302cb04...:save-fix/Final/ceos.eoscfg` and `git show 62c2dffff...:save-fix/Final/ceos.eoscfg`
     are byte-identical (968 bytes both) — only `ceos.cfg` differed between the two commits, so the
     applied bytes are provably the reviewed ones either way; the decisive proof is the recorded
     `source.commit` itself pinning to the older commit.

### Invalid commit: refused before any device is touched

`POST /api/labs/<lab>/restore` with `source.commit` = 40 hex characters not in the branch history →

```
409  "The selected commit is outside this repository branch history."
```

(First attempt used a non-hex `request_id` and got `422` from request validation before reaching this
check — a QA script bug, not a manager behaviour; reissued with a valid 32-hex `request_id`, same
same-origin request shape, and got the `409` above.) No restore job was created for either attempt —
`resolve_source()` rejects the commit before `submit()` ever creates a job record or contacts a
device.

## State left for B8

Lab still bound to `save-fix/working`; local == origin at `62c2dffffbddb78abe6988f8304f78d4c1aa3973`;
ceos now carries `save-fix/Final`'s exact saved configuration (state A, byte-identical); `save-fix/Final`
itself untouched by any of this (Apply only writes to devices, never back to the repository).
