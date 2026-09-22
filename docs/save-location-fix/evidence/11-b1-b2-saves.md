# B1-B2 — Latest saves into save-fix/working/latest — evidence

Build: `clab-backup:1.30.31` (image `d356c1d9253d`), helpers `1.30.31`, assets `?v=1.30.31`. Source
checkout HEAD `6c3e8b3` (dirty). Lab `restore-square` (`904a35a79dc341ce8a4638f83fc34185`), bound to
`save-fix/working` after B0. Tool: `docs/save-location-fix/tools/b1_b2_saves.py`, raw record
`11-b1-b2-saves.json`. Each save made one distinguishable, reversible change on **ceos only**
(`interface Ethernet2` description — never OSPF or loopbacks), over a fresh SSH session
(`docs/multi-platform-restore/tools/nodecli.py`), then went through the real Progress tab: **Save
progress → review dialog → Upload these changes**.

## Result: PASS

### B1 — first save after B0's rebind

| Check | Result |
|---|---|
| Job reached `synced` | PASS |
| `snapshot_path` | `save-fix/working/latest` (the **original** snapshot folder, updated in place) |

### B2 — three more real Latest saves

| Save | Condition | Job status | `snapshot_path` |
|---|---|---|---|
| B2a | after browsing to `save-fix/working/latest` in the folder browser (disabled, *"This lab already saves here."*, no rebind offered — screenshot `1x-b2a-browse-latest.png`) | `push_pending` at first read (*"Another Git operation is already running for this repository"* — B1's own push was still finishing under the single host lock), then picked up by a later save's upload and re-queried as `synced`, `pushed: true`, commit `b52e7869...` | `save-fix/working/latest` |
| B2b | after a full page reload | `synced` | `save-fix/working/latest` |
| B2c | after a real `docker restart containerlab-node-manager-backup-ui-1` (waited for `/api/state` to answer again, then for readiness) | `synced` | `save-fix/working/latest` |

The B2a transient `push_pending` is the manager's documented one-host-lock concurrency (a second Git
job started less than a second after B1's own push queued), not a save-location defect: the job's
commit was made locally at once and the review dialog itself warns *"Uploading also sends N earlier
saves still waiting on the VM"* — exactly what happened when the B2b save's upload carried it along.

### Independent Git verification (after all four saves)

```
local HEAD  = 8f6ee3de259a5e2e1566bd90cba0d0a8acfc849c
origin/main = 8f6ee3de259a5e2e1566bd90cba0d0a8acfc849c   (in sync)
```

- `git ls-tree -r --name-only HEAD -- save-fix/working` lists exactly one `save-fix/working/latest/*`
  set of 9 files, plus the pre-existing legacy `save-fix/working/latest/latest/*` — **no**
  `save-fix/working/latest/latest/latest` (no further nesting was created by any of the four saves).
- The legacy nested tree `save-fix/working/latest/latest` has git tree hash
  `67e4375b2edb035964c2db58d34006c4a3362203` **before and after** all four saves — byte-identical,
  confirming none of B1/B2a/B2b/B2c touched it.
- `git log --oneline -- save-fix/working/latest/manifest.json`:
  ```
  8f6ee3d Save restore-square progress   (B2c)
  8edbc5b Save restore-square progress   (B2b)
  b52e786 Save restore-square progress   (B2a)
  5b35ee5 Save restore-square progress   (B1)
  4fa2578 Save restore-square progress   (original, from the reproduction)
  ```
  Five commits, one per save — history intact, no commit lost or squashed by the reload or the
  manager restart.

## State left for B3

Lab remains bound to `save-fix/working`; local == origin at `8f6ee3d`; ceos `Ethernet2` carries the
description `QA-B2c save test` (sanitized, reversible, no OSPF/loopback touched).
