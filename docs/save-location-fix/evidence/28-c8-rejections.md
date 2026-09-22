# C8 — Invalid sources and a stale review, all refused before any device mutation — evidence

Build: `clab-backup:1.30.31` (image `3dfc4912c163`), commit `8ea56e0`. Lab `restore-square`
(`904a35a79dc341ce8a4638f83fc34185`), bound to `save-fix/working`. Tool:
`docs/save-location-fix/tools/c8_rejections.py`, raw record `28-c8-rejections.json`. Screenshots
`28-c8-bad.png`, `28-c8-missing.png`, `28-c8-stale-review-open.png`.

## Result: PASS (14/14 checks)

### 1. `save-fix/Bad` — `manifest.json` is literally invalid JSON

Seeded from the second checkout (`{ this is not valid JSON ]` as the file's entire content), pushed,
discovered with **Update from the repository** (`head` reached the seed commit `2e2d19d8…`). The
folder browser still offers **Apply to running lab…** (it only checks for a file literally named
`manifest.json`, as documented — "any file named `manifest.json` is listed as a snapshot until the
preflight reads it"). Clicking it opens the review dialog, which immediately shows:

> The saved configuration cannot be applied right now.
> The saved version manifest is invalid.

`POST /api/labs/<id>/restore/preflight` → **409**, no `.restore-targets` fieldset ever rendered, and
**no new restore job was created** (`restore_jobs` list identical before/after) — no device was
contacted.

### 2. `save-fix/Missing` — valid JSON, but the manifest's `ceos` `restore_artifact` (`ceos.eoscfg`)
is absent from the folder

Seeded by copying `save-fix/Final`'s real 9 files and deleting `ceos.eoscfg` only (the manifest keeps
referencing it). Review dialog:

> The saved configuration cannot be applied right now.
> The saved snapshot is missing files or exceeds its limit.

Same result: `POST .../restore/preflight` → **409**, no targets rendered, no restore job created — no
device contacted, for *any* of the four nodes (not just `ceos`): `decoded_snapshot()` in
`app/git_progress.py` validates every manifest-referenced file (`restore_artifact` included) before
any per-node candidate is built, so a single missing file refuses the whole folder at the manifest
stage, before `map_targets()`/the live SSH probe ever runs.

### 3. A commit id outside the branch history

Direct `POST /api/labs/<id>/restore` with `source.commit` = `"a" * 40` (a syntactically valid but
unknown sha): **409**, `"The selected commit is outside this repository branch history."` No restore
job created.

### 4. A stale review, once more, on `/save-fix/Final`

Opened the review on `/save-fix/Final` (reviewed commit `2e2d19d8…`), then — with the dialog still
open — pushed a trivial one-line change to `save-fix/Final/ceos.cfg` from the second checkout and ran
**Update from the repository** through the same-origin API the page's own button sends
(`POST /labs/<id>/git/update`, since the modal `<dialog>` blocks the covered "More…" menu button by
design — not a bypass). The manager's `head` advanced to the new commit; the already-open review
dialog **stayed open**, unaffected. Submitting it (ceos only) produced a job whose `source.commit` is
still the **reviewed** commit (`2e2d19d8…`), not the new `HEAD` — the bytes reviewed are the bytes
applied, confirmed by the job record itself. Job `succeeded`.

## No device contacted, shown two ways

- `GET /api/state` → `restore_jobs` list length identical immediately before and after each of the
  three refused attempts (Bad, Missing, invalid commit) — nothing was queued, so nothing could reach
  the live SSH probe stage of `preflight()`.
- The response captured for each refused attempt is the **preflight** call itself (`.../restore/preflight`,
  409) — `preflight()` in `app/restore.py` calls `resolve_source()` before any per-node loop, and
  `resolve_source()`/`decoded_snapshot()` raise before `map_targets()` builds any row, so the
  live-probe loop (which is the only place a device is contacted) never runs.

## State left after C8

`ceos` (the only node touched, by the stale-review restore) reads **A**
(`c_lib.classify_all(['ceos'])`); the other three were untouched by this row and remain at whatever
C7 left them (**A**, confirmed in `27-c7-mixed.md`). Binding `save-fix/working` unchanged throughout.
