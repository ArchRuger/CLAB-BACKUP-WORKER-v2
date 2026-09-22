# B8 — After Apply: Save progress still targets save-fix/working/latest — evidence

Build: `clab-backup:1.30.31` (image `d356c1d9253d`), helpers `1.30.31`, assets `?v=1.30.31`. Source
checkout HEAD `6c3e8b3` (dirty). Lab `restore-square`, bound to `save-fix/working`. Tool:
`docs/save-location-fix/tools/b8_after_apply.py`, raw record `17-b8-after-apply.json`.

## Result: PASS (7/7 checks)

Real change on ceos (`Ethernet2` description `QA-B8-after-apply`, made right after B7's real restore
put ceos back to `save-fix/Final`'s state), Progress tab → Save progress → review → Upload these
changes:

```
status: synced
snapshot_path: save-fix/working/latest
```

Confirms the fix holds even immediately after an Apply: the next Save progress still writes into the
lab's own `save-fix/working/latest` snapshot folder, never into `save-fix/Final` or a new nested
folder.

### `save-fix/Final` untouched

`git ls-tree HEAD -- save-fix/Final` tree hash before and after B8's save:
`7f0a08397a8191bf8451176088e92f1577c8a8e5` both times — byte-identical. Apply only ever writes to
devices, never back to the repository, and B8's save writes only into `save-fix/working/latest`.

### `l10-evpn`'s binding and files untouched

`GET /api/labs/797db5fc9757415eb008a1a98b6c9787/git` → `binding.repository.prefix` =
`l10-evpn/work`, identical before and after B8 (full binding object compared, byte-equal).
`git ls-tree -r --name-only HEAD -- l10-evpn/work` lists the same 9 files before and after.

## Independent Git verification

Local `HEAD` == `origin/main` == `d493f686a11de834a1f2633ba2e71f7678b52a89` at the end of B8.

## State left after B8 (end of the assigned matrix)

Lab `restore-square` bound to `save-fix/working`; ceos now equals `save-fix/Final`'s saved state plus
the `QA-B8-after-apply` description on `Ethernet2`; the other three nodes are unchanged (only ceos was
touched across the whole run).
