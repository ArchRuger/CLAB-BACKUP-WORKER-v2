# B4 — Checkpoints, baseline, compare, history, ZIP — evidence

Build: `clab-backup:1.30.31` (image `d356c1d9253d`), helpers `1.30.31`, assets `?v=1.30.31`. Source
checkout HEAD `6c3e8b3` (dirty). Lab `restore-square`, bound to `save-fix/working`. Tool:
`docs/save-location-fix/tools/b4_checkpoints_baseline.py`, raw record
`13-b4-checkpoints-baseline.json`.

Note on the run: a first attempt hit a UI race in this QA tool's own Recent-saves-reopen logic while
completing checkpoint `qa-cp-a`'s review (documented in the tool's comments); the review for that one
job was completed with the exact same-origin request the page's own "Upload these changes" button
sends (`POST /api/git/jobs/<id>/retry {"push":true,"reviewed":true}`), verified synced, and the tool
was fixed (reload before reopening a Recent-saves row) before every other step below, which all ran
cleanly through the browser end to end.

## Result: PASS (14/14 checks)

### Two checkpoints, a Latest save between, then again

| Step | Change | Result |
|---|---|---|
| Checkpoint `qa-cp-a` | `Ethernet2` description `QA-B4-checkpoint-a` | job `aacc1020...` synced, `snapshot_path save-fix/working/checkpoints/qa-cp-a` |
| Checkpoint `qa-cp-b` | `Ethernet2` description `QA-B4-checkpoint-b` | synced, `save-fix/working/checkpoints/qa-cp-b` |
| Latest save after both checkpoints | `Ethernet2` description `QA-B4-latest-after-checkpoints` | synced, `snapshot_path save-fix/working/latest` (real Progress tab → review → Upload) |

### Both checkpoints stay byte-identical

```
                 at creation                              after the Latest save
qa-cp-a  69e64585b04a4c011b9f2fae97e96d1e4a13c747   ==     69e64585b04a4c011b9f2fae97e96d1e4a13c747
qa-cp-b  10337c13edf63ac1f279fdc119009b2e6a5547bc   ==     10337c13edf63ac1f279fdc119009b2e6a5547bc
```

(`git ls-tree HEAD -- save-fix/working/checkpoints/<name>` tree hash, independent of the manager.)

### Set baseline

**Set baseline…** (Progress tab → More → Set baseline…) with the latest complete capture selected →
job reached `synced`.

### Compare with my latest save

Opened from the Saved versions card, `qa-cp-a`'s row → **Compare with my latest save** →
`POST /api/labs/<lab>/git/compare` → dialog titled *"Compared with your latest save"*, with per-file
diff content (screenshot `1x-b4-compare.png`).

### Full history…

Progress tab's header quick-save menu → **Saved versions & history** → `#git-history-dialog` lists
both a **Saved versions** section (every snapshot folder) and a **Save history** section (commits) —
screenshot `1x-b4-history.png`.

### View + ZIP: `save-fix/Final`

Saved versions → the `Final` row (reference group, `save-fix/Final`) → **View** → `#git-version-dialog`
→ **Download (ZIP)**. Real file downloaded and unzipped:

```
ceos.cfg  ceos.eoscfg  cjunosevolved.jcfg  cjunosevolved.set  manifest.json
vjunos-switch.jcfg  vjunos-switch.set  xrv9k.cfg  xrv9k.xrcfg
```

9 files including `manifest.json` — matches the contract ("the ZIP must contain manifest.json and the
nine files").

### View + ZIP: the `qa-cp-a` checkpoint

Same flow from the `qa-cp-a` row → ZIP downloaded and unzipped to the identical 9-file set
(`manifest.json` + the 8 device files across the four kinds).

## Independent Git verification

Local `HEAD` == `origin/main` == `9ab58e4ea8668bd5d95fe3e9a64ee79c54c603bc` at the end of B4.

## State left for B5

Lab bound to `save-fix/working`; checkpoints `qa-cp-a`/`qa-cp-b` and a baseline exist under it; ceos
`Ethernet2` description is `QA-B4-latest-after-checkpoints`.
