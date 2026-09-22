# B5 — Fault injection: incomplete capture, failed push, retry — evidence

Build: `clab-backup:1.30.31` (image `d356c1d9253d`), helpers `1.30.31`, assets `?v=1.30.31`. Source
checkout HEAD `6c3e8b3` (dirty). Lab `restore-square`, bound to `save-fix/working`. Tool:
`docs/save-location-fix/tools/b5_faults.py`, raw record `14-b5-faults.json`.

## Result: PASS (19/19 checks)

### (a) Incomplete capture (wrong ceos credential)

- `PUT /api/labs/<lab>/node` assigned the existing `QA-wrong-password-ceos` profile
  (`311acce74c984d03a811fd789a821fe6`) to `ceos` → `200`.
- Real Progress tab → **Save progress**: newest job —
  ```
  status: capture_incomplete
  message: "Capture incomplete. Every included device must have a successful file; latest is unchanged."
  pushed: false
  ```
- Independent Git check: `save-fix/working/latest` tree hash and local `HEAD` **unchanged** before and
  after the attempt.
- `PUT /api/labs/<lab>/node` restored `profile_id: ""` (default/inventory) → `200`; ceos `readiness`
  returned to `Ready` within the poll window. Confirmed afterward via `/api/state`: `profile_id: ""`,
  `readiness: "Ready"` — credentials fully restored.

### (b) Failed push, then a successful retry

- `gh auth switch -u ArchRuger` (no push right to `pruger-dev/CLAB-MNGR-DEV-LLM`) → active account
  confirmed `ArchRuger`.
- Real change on ceos (`Ethernet2` description `QA-B5-failed-push`), Progress tab → Save progress →
  review → **Upload these changes**. Job result:
  ```
  status: push_pending
  message: "The commit is saved on the VM, but push failed. Check authentication, branch permissions
            or remote changes, then retry."
  commit: b302cb04cb0745867b1cdb7c5e4b9303f1c539ea
  pushed: false
  ```
- Independent Git check: `origin/main` **unchanged** by the failed push; the **local** checkout does
  carry the new commit (`b302cb04...`) — saved on the VM, upload only is what failed.
- `gh auth switch -u pruger-dev` → active account confirmed `pruger-dev`.
- Progress tab → Recent saves → the same job's row now offers **"Upload now"** (already reviewed, no
  second review needed) → clicked it → job reaches:
  ```
  status: synced
  commit: b302cb04cb0745867b1cdb7c5e4b9303f1c539ea   (the SAME commit, not a new one)
  ```
- Final Git check: local `HEAD` == `origin/main` == `b302cb04...`; `git ls-tree` under
  `save-fix/working/latest` shows exactly one `latest/` plus the pre-existing legacy
  `latest/latest/` — **no** `latest/latest/latest`, no duplicate nesting from the retry.

## State left for B6

- ceos back on its default/inventory credential, `readiness: Ready`.
- `gh auth status` active account: **pruger-dev** (left as required).
- Lab still bound to `save-fix/working`; local == origin at `b302cb04cb0745867b1cdb7c5e4b9303f1c539ea`.
