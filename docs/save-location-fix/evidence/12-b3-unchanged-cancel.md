# B3 — Unchanged save, cancelled review, completed upload — evidence

Build: `clab-backup:1.30.31` (image `d356c1d9253d`), helpers `1.30.31`, assets `?v=1.30.31`. Source
checkout HEAD `6c3e8b3` (dirty). Lab `restore-square`, bound to `save-fix/working`. Tool:
`docs/save-location-fix/tools/b3_unchanged_cancel.py`, raw record `12-b3-unchanged-cancel.json`.

## Result: PASS (9/9 checks)

### Part 1 — save without any device change

No dialog opened (a quiet save); the newest job read back from `GET /api/labs/<lab>/git`:

```
status: unchanged
message: "Nothing changed since the last save, which was uploaded."
commit: 8f6ee3de259a5e2e1566bd90cba0d0a8acfc849c   (== previous HEAD)
changed_files: []
snapshot_path: save-fix/working/latest
```

No new local commit (`git rev-parse HEAD` identical before/after). No new directory: `snapshot_path`
stayed `save-fix/working/latest`.

### Part 2 — change, save, CANCEL the review

Real change on ceos (`Ethernet2` description `QA-B3-cancelled-review`). Review dialog text: *"This
save is on the lab VM only. Nothing is uploaded to github.com unless you choose Upload these
changes."* — clicked **Not now — keep it on the VM** (`#git-review-cancel`, sends no request; confirmed
no `/retry` request fired). Job afterward:

```
status: review_pending
message: "Saved in the VM repository; not pushed."
pushed: false
commit: 26a2504306680dd7f4e7dcdf23968d2f148e1596   (a NEW local commit)
```

Independent Git check: `origin/main` unchanged before/after the cancel
(`8f6ee3de259a5e2e1566bd90cba0d0a8acfc849c` both times) — **nothing was pushed**. The local checkout's
`HEAD`, however, does carry the new commit (`26a25043...`) — the save really happened on the VM, it was
only the upload that was declined, matching the product's contract (a mandatory review, with a real
"keep it local" option).

### Part 3 — complete from Recent saves

Progress tab → Recent saves → the pending job's row shows **"Review and upload…"**
(`gitUploadLabel`, confirmed by reading the button's own text) → clicking it reopens the same review
dialog (`#git-diff-dialog`) → **Upload these changes** → `POST /api/git/jobs/<id>/retry
{"push":true,"reviewed":true}` → job reaches:

```
status: synced
pushed: true
commit: 26a2504306680dd7f4e7dcdf23968d2f148e1596   (the SAME commit reviewed and cancelled above)
message: "Saved commit is included in the verified remote history."
```

Final Git check: local `HEAD` == `origin/main` == `26a25043...` — the exact commit that was reviewed
in Part 2 is the one that ended up pushed; no duplicate commit, no new directory, `snapshot_path`
stayed `save-fix/working/latest` throughout.

## State left for B4

Lab still bound to `save-fix/working`; local == origin at `26a25043...`; ceos `Ethernet2` carries the
description `QA-B3-cancelled-review`.
