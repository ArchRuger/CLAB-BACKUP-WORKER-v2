# B6 — Discovery of Final, Broken, and a nested solution — evidence

Build: `clab-backup:1.30.31` (image `d356c1d9253d`), helpers `1.30.31`, assets `?v=1.30.31`. Source
checkout HEAD `6c3e8b3` (dirty). Lab `restore-square`, bound to `save-fix/working`. Tool:
`docs/save-location-fix/tools/b6_discovery.py`, raw record `15-b6-discovery.json`.

## Result: PASS (12/12 checks)

### Folder browser

| Folder | Reached, lists `manifest.json`? | Apply to running lab…? |
|---|---|---|
| `save-fix/Final` (direct manifest) | yes | not checked here (covered in reproduction 01 — no Apply button, only per-file "can be applied"); B7 exercises Apply from this exact folder |
| `save-fix/Broken` (legacy parent, only a `latest` child) | yes (via its listing) | **yes** — offered |
| `save-fix/Broken/latest` (direct) | yes | — |
| `save-fix/course/lab/reference/solution` (four levels deep) | yes | — |

Screenshots `1x-b6-browser-final.png`, `1x-b6-browser-broken.png`, `1x-b6-browser-solution.png`.

### Saved versions card — group and exact-path caption

| Row | Group heading | Caption (exact path) |
|---|---|---|
| Final | **Instructor and reference versions** | `save-fix/Final` |
| Broken | **Instructor and reference versions** | `save-fix/Broken/latest` (legacy parent convenience: the caption itself names the `.../latest` child, not the bare `Broken` folder) |
| solution | **Instructor and reference versions** | `save-fix/course/lab/reference/solution` |

Screenshot `1x-b6-saved-versions.png`.

### `GET /api/labs/<lab>/git/history`

62 total versions returned; confirmed present: `save-fix/Final`, `save-fix/Broken/latest`,
`save-fix/course/lab/reference/solution`.

### No rebind, no restart

Destination line before and after every browse/query:

```
restore-square saves to CLAB-MNGR-DEV-LLM › save-fix/working › latest/
```

Identical — none of the browsing, the Saved versions read, or the `/git/history` call changed the
lab's binding; the manager was not restarted for this row.

## State left for B7

Lab unchanged, still bound to `save-fix/working`.
