# Reproduction 2: manifest folders not appliable — evidence

QA operator run against the **running deployed manager 1.30.30** and the real lab `restore-square`
(id `904a35a79dc341ce8a4638f83fc34185`), through the product (browser Progress tab, folder browser) and
its real API, plus a second, independent Git checkout used only to push instructor-style reference
snapshots (never through the manager). Full raw records are in `01-repro-apply-manifest.json`. Result:
**PASS — the bug reproduces** exactly as described in `docs/save-location-fix/PICKUP.md` "Findings": a
folder that holds `manifest.json` directly is invisible to *Apply to running lab…*, to the Saved
versions list, to `/git/history`, to `/git/version`, and to `/restore/preflight`, no matter its name or
depth, while the legacy `<name>/latest` layout still works everywhere.

## Setup (once, out of band)

1. A **second** Git checkout, `gh repo clone pruger-dev/CLAB-MNGR-DEV-LLM <scratchpad>/second-checkout`,
   with a throwaway identity (`git config user.name "instructor snapshots"`, a `.invalid` e-mail) — this
   clone never touches the manager.
2. Copied the lab's own complete, non-nested `save-fix/working/latest/` snapshot from Reproduction 1
   step b (`manifest.json` + the 8 device files; the nested `latest/latest/` created by Reproduction 1's
   bug was excluded from every copy) to three places:
   - `save-fix/Final/` — a direct manifest folder, no `latest` child
   - `save-fix/course/lab/reference/solution/` — the same, four levels deep
   - `save-fix/Broken/latest/` — a **legacy-layout control**: a plain folder whose only content is a
     child literally named `latest`
3. Committed as **instructor snapshots** and pushed to `origin main`:
   commit `f79b4e0cb6c126b579958f0766cb0b50eab3297f`.
4. In the product: `POST /api/labs/<lab>/git/update {}` → `{"status": "updated", "head":
   "f79b4e0c…", "message": "Updated from remote using fast-forward only."}` — the manager's own
   operator checkout fast-forwarded to the new commit.

## Browser: the folder browser (real Playwright session, `docs/save-location-fix/tools/repro_apply_manifest.py`)

| Folder | Its own `manifest.json`? | Apply to running lab… offered? | Screenshot |
|---|---|---|---|
| `save-fix/Final` | yes, directly | **NO** — action bar has only *New folder…* / *Save this lab here* | `01-b-final-no-apply.png` |
| `save-fix/course/lab/reference/solution` | yes, directly, 4 levels deep | **NO** | `01-d-deep-solution-no-apply.png` |
| `save-fix/Broken` | no (only a `latest` child folder) | **YES** — red *Apply to running lab…* button, caption *"Applies this folder's latest save to the running devices. They are not rebooted."* | `01-c-broken-has-apply.png` |

Notably, at `save-fix/Final` the browser *does* recognise the individual files as restore artifacts
(`ceos.eoscfg`, `cjunosevolved.jcfg`, `vjunos-switch.jcfg`, `xrv9k.xrcfg` are each labelled "Device
configuration (**can be applied to a running lab**)" in the listing) — it is only the folder-level
*Apply* action that is missing, confirming the defect is in folder recognition
(`gitTreeModel`/`dir.restorable`, which only checks a `latest/` child), not in file-format recognition.

The **Saved versions** card (`01-a-saved-versions.png`) lists only this lab's own registered nested
snapshot (`CLAB-MNGR-DEV-LLM › save-fix/working/latest › latest`, 9 files) — `Final`, the deep
`solution` path, and `Broken` appear nowhere in it.

## API

| Check | save-fix/Final | save-fix/Broken/latest |
|---|---|---|
| `GET /api/labs/<lab>/git/history` — path present among the 57 returned `versions`? | **absent** | present (`connected: false`) |
| `POST /api/labs/<lab>/git/version {"commit": "f79b4e0c…", "path": "…"}` | **400** `{"detail": "Choose latest, baseline or a named checkpoint version."}` | **200**, full manifest (schema 2, 4 files, all `restore_capable: true`) |
| `POST /api/labs/<lab>/restore/preflight {"source": {"type":"folder","path":"…"}}` | **409** `{"detail": "Select a listed snapshot path and exact commit."}` | **200**, review with **4/4 eligible rows** (ceos, cjunosevolved, vjunos-switch, xrv9k, each `eligible: true`) |

No restore was submitted at any point (`POST /api/labs/<lab>/restore` was never called) — the review
stopped at preflight, per the assignment.

`save-fix/course/lab/reference/solution` was not separately re-tested through `/git/version` and
`/restore/preflight` (the browser check at four levels of depth, `01-d-deep-solution-no-apply.png`,
already shows the same folder-recognition rule applies regardless of depth, and both API checks key off
exactly the same `resolve_version_path`/`allowed_repo_version` machinery already exercised by `Final`).

## Final repository state

| Checkout | HEAD | vs `origin/main` |
|---|---|---|
| Operator (`~/labs/CLAB-MNGR-DEV-LLM`, the manager's own registered checkout) | `f79b4e0cb6c126b579958f0766cb0b50eab3297f` | in sync |
| Second (`<scratchpad>/second-checkout`) | `f79b4e0cb6c126b579958f0766cb0b50eab3297f` | in sync |
| `origin/main` (`git ls-remote`) | `f79b4e0cb6c126b579958f0766cb0b50eab3297f` | — |

## Tooling

`docs/save-location-fix/tools/repro_apply_manifest.py` — rerunnable Playwright script; browses to
`save-fix/Final`, `save-fix/Broken`, and `save-fix/course/lab/reference/solution` and asserts the
presence/absence of `[data-git-places-action="apply"]`. It never submits a restore.
