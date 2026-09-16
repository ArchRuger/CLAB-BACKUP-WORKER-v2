# Student-centred UI redesign — pickup notes for the next agent

**Status: WORK IN PROGRESS, unreleased.** The running tree is still labelled 1.28.0; the target release is
1.29.0. Read this file first, then `DESIGN-SPEC.md` and `DESIGN-SPEC-ADDENDUM.md` (the addendum overrides
the spec wherever they disagree). The brief that started this work is the user's prompt file
`~/UltraCode Prompt — Student-Centered Full UI-UX Redesign.md` on the dev VM (not in the repository); its
requirements are restated in the spec's §0 non-negotiables: zero functional regression, backend untouched,
progressive disclosure instead of deletion, vanilla JS/HTML/CSS, browser and live-lab validation before
calling anything done.

## 1. What this folder holds

| Path | What it is | Use it for |
|---|---|---|
| `UX-AUDIT.md` | Problems found in the 1.28.0 UI from a real browser (screenshots in `shots/before/`) | The "UX audit" section of the final report |
| `DESIGN-SPEC.md` | Information architecture, status vocabulary, visual system, file plan (first draft) | The overall shape |
| `DESIGN-SPEC-ADDENDUM.md` | Decisions on every review finding; §J is the shell contract, §J9 the migration order | **The binding contract** — read all of it |
| `inventory/*.md` | Exhaustive inventory of the OLD UI: every control, dialog, string, timer, test contract, CSS hook, backend state value | The regression checklist (`MERGED-INVENTORY.md` is the consolidated 134-row table; the per-module files are finer-grained) |
| `parity/*.md` | Per-module mapping old location → new location for every capability, plus the spec gaps and microcopy rewrites the implementation must apply | The "Functional Parity" section of the final report; the copy sweep |
| `critique/*.md` | Adversarial reviews of the spec (student-first, feasibility/regression, visual/accessibility) and of the new stylesheet | Already folded into the addendum; consult for rationale |
| `tools/*.py` | Playwright scripts that captured the old UI (`audit_current.py`, `audit_rest.py`, `audit_menus.py`) | Template for the "after" validation script |
| `shots/before/` | Curated 1.28.0 screenshots (1920×1080 and 1366×768) | Before/after comparison in the report |

## 2. Environment facts you need

- Repository: `~/projects/clab-manager`. App: `clab-backup-ui/` (FastAPI + vanilla JS). House style in JS is
  dense one-statement-per-line; keep `'use strict'`, `esc()` on every interpolation, no inline styles,
  self-only CSP, no frameworks, no CDN.
- Manager container: `containerlab-node-manager-backup-ui-1` from `clab-backup-ui/compose.yml`, host
  networking, port 8081, data bind-mounted from `/srv/containerlab-node-manager/data`. **Rebuild + recreate
  loop (≈3 s):** `cd ~/projects/clab-manager && docker compose -f clab-backup-ui/compose.yml up -d --build`.
  Never mount the Docker socket; never add a host helper for device work (see `agent instructions.md`).
- Live labs on the VM: `clabllm-dev` (PTX1 cJunosEvolved 172.20.20.2, SW1 vJunos-switch 172.20.20.3,
  containerlab default Junos login, Git-bound to `~/labs/CLAB-MNGR-DEV-LLM` prefix `labs/BGP-LAB/work`) and
  `bgp-core` (2 × cJunosEvolved). Redeploying `bgp-core` is the safe way to observe Starting → Running.
  These are VM-in-container nodes: after a redeploy allow several minutes for the NOS.
- Python venv with the app requirements, httpx and Playwright (Chromium installed):
  `/home/clabllm/clab-venv/bin/python`.
- Tests: `cd clab-backup-ui && node --test tests/*.js` and
  `PATH=/home/clabllm/clab-venv/bin:$PATH /home/clabllm/clab-venv/bin/python -m unittest discover -s tests`.
  Baseline before this work: 96 JS tests, 691 Python tests (1 skipped), all passing.
- Release procedure: `python3 deploy/set-release.py 1.29.0`, then hand-written sections at the top of
  `docs/CHANGELOG.md`, `clab-backup-ui/VALIDATION.md` and `agent instructions.md`, then
  `python3 deploy/verify-release.py`. New static scripts need `?v=<release>` in every HTML page and must be
  appended to the `node --test` list in `.github/workflows/release-check.yml`. `docs/redesign/` is exempt
  from the living-doc version check (`deploy/verify-release.py` `HISTORY_DIRS`).

## 3. Where the implementation stands

See §7 "Handoff status" at the end of this file — it is updated at every handoff and is the single source
of truth for what is done, what is verified, and what is next.

## 4. The plan (addendum §J9)

1. `status.js` vocabulary (pure functions) + both app.js test harnesses load it. **Done.**
2. Shell: `shell.js` (router, menus, storage), new `index.html`, `app.js` navigation/home/header/banner,
   `home.js`, minimal `management.js`/`operations.js` adaptations, `tests/test_shell_ui.js`,
   `tests/test_home_ui.js`. Gate: all JS tests green, id diff clean, container rebuilt, Playwright console
   watch clean with a menu and the drawer open across three polls.
3. In parallel, file-disjoint (one agent or one sitting each):
   - (a) Devices tab, device drawer, map states — `app.js`, `topology.js`, `topology-render.js`
     (addendum §J7, parity/topology.md gaps A–S, parity/shell.md G8–G11).
   - (b) Progress tab — `git-progress.js`, `git-places.js`, `restore.js` (addendum §D, §H, §J6;
     parity/git-progress.md GAP-A…U; parity/git-places-restore.md).
   - (c) Operations, management, capture and the standalone pages — `operations.js`, `management.js`,
     `capture.js`, `workspace.js/html`, `terminal.js/html`, `grafana.js/html`, `debug.js/html`,
     `vm-connection.html`, `capture-setup.html` (addendum §E, §G; parity/operations.md, management.md,
     capture.md, pages.md).
4. Stylesheet fix pass per addendum §J8 (tokens, focus ring, menu-button pattern, tablist, layout heights,
   map glyphs, skeleton, code surfaces, drawer, sprite) — `style.css`, `terminal.css`.
5. Integration: full `node --test`, Python suite, `node --check`, `git diff --check`, id diff, Playwright
   "after" pass at 1920×1080 / 1440×900 / 1366×768 (every screen, dialog and menu; assert the map fits at
   1366×768), live-lab pass (deploy/redeploy bgp-core and watch Starting → Running; Open CLI; Save progress;
   checkpoint; view/compare/apply a saved state from the folder browser; capture entry point; telemetry
   link; destroy confirmation cancelled).
6. Docs (`docs/TOUR.md`, `LAB-OPERATIONS.md`, `GIT-PROGRESS.md`, `GIT-SETUP.md`, `TELEMETRY.md`,
   `CAPTURE.md`, `NAMING.md`, `WIKI-MASTER-GUIDE.md` parts 12–14/17/21, `README.md`,
   `clab-backup-ui/NODE-FEATURES.md`, `docs/ARCHITECTURE.md` module map), release 1.29.0, the final report
   with the sections the brief lists (UX audit, IA, student workflow, visual system, files changed,
   automated testing, browser validation, live lab validation, screenshots, remaining limitations, Git,
   **Functional Parity** with "Intentionally removed: None").

## 5. Rules that bit us already (do not relearn them)

- `app.js` must still load inside `tests/test_download_ui.js` / `tests/test_readiness_ui.js` contexts:
  no `window`/`location`/`history`/`localStorage`/`document.addEventListener` at top level — those live in
  `shell.js` and are called through `typeof` guards.
- One element per id. Items that "trigger" another control mirror `disabled`/`title` (`data-proxy`) and
  call the owner's `onclick()`; never `.click()` a hidden or disabled control.
- Header, banner, tabs and menus are never re-rendered with `innerHTML` on the 4 s poll; lists use
  `setMarkup()` (the `_markup` diff) so focus and open menus survive.
- `operations.js` wires everything inside `if($('import-top'))` — `#import-top` must exist at load; the
  `#lab-actions` button is static in `index.html` (inside the Lab actions menu) and the injection is
  guarded by `if(!$('lab-actions'))`.
- Legacy tab names (`inventory`, `git`, `backups`, `credentials`, `logs`) are still assigned by old
  callers; `setTab()` normalises them and `logsVisible()` replaces `tab==='logs'`.
- Backend `node.readiness === 'Ready'` means "can be backed up", not "SSH ready"; never show it through the
  student pill vocabulary. `deviceState()` is SSH-centred.
- `/git/compare` diffs against the latest save, not the running configuration — the button says
  "Compare with my latest save".
- Apply-to-running-lab must stay pick-and-load from any folder without rebinding (`restoreFromFolder`);
  the user rejected the earlier flow that forced a rebind.
- `topologyMarkup()` stays pure (tested without status.js); map state is applied afterwards by
  `renderMapState()` with `classList`, never by rebuilding the SVG.
- Test regexes that pin old labels are rewritten to the new label while keeping the behavioural claim;
  never delete or weaken a test (`inventory/tests.md` §14, `critique/feasibility.md` A16).

## 6. How to validate a stage in the browser

```bash
cd ~/projects/clab-manager && docker compose -f clab-backup-ui/compose.yml up -d --build
/home/clabllm/clab-venv/bin/python docs/redesign/tools/audit_current.py   # adapt: it targets the OLD ids
```
Write the "after" script from `tools/audit_current.py`: load `/`, collect `console` errors and
`pageerror`s for 13 s (three polls) with a menu open, open each lab, click every tab, open a device, open
every dialog, screenshot at 1920×1080 / 1440×900 / 1366×768, and assert
`document.getElementById('topology-map').getBoundingClientRect().bottom <= innerHeight` at 1366×768.

## 7. Handoff status

_(newest entry first)_

### 2026-09-16 — stages 1 and 2 of the plan done; stages 3–6 not started

**Done and verified (commit on `claude/wip-student-centered-ui-redesign`):**
- Plan step 1: `app/static/status.js` (labState / deviceState / progressState / progressSummary /
  relativeTime / badgeLabel / telemetryLine / credentialsNeeded / savedVersionName / operationLabel) with
  `tests/test_status_ui.js` (9 tests). Both app.js harnesses load it.
- Plan step 2: `app/static/shell.js` (router: hash → sessionStorage → Home; `replaceState` on poll writes;
  menu contract with roving keys/Escape/outside click; localStorage helpers; `showActionError`),
  new `app/static/index.html` (top bar + Manager menu, Home with skeleton/Continue card/lab cards/other
  labs on the VM, lab header with pill + "n of m devices ready" + progress + Save progress + Lab actions
  menu, situational banner with static children, tablist with Topology/Devices/Progress/Tools/Advanced
  panels wrapping every legacy section, drawer with static Advanced section, inline SVG sprite, every
  old dialog kept), `app/static/app.js` (no auto-select, `setTab` legacy mapping, `renderLabBanner`,
  `syncProxies`, `setMarkup`, `renderDeviceList`, `nodeDrawerActions`, drawer wiring),
  `app/static/home.js`, minimal `management.js`/`operations.js` adaptations (guarded `#lab-actions`
  injection, menu `[data-op-action]` delegation and gating, `showActionError`, `data-label` restores,
  `#vm-projects` → in-page deploy dialog), rewritten `style.css`/`terminal.css` (design system, all hooks
  kept, WCAG-checked tokens), `tests/test_shell_ui.js`, `tests/test_home_ui.js`.
- Checks at handoff: `node --test tests/*.js` 120/120; Python `unittest` 691 pass, 1 skipped;
  `node --check` clean; `git diff --check` clean; `python3 deploy/verify-release.py` passes (1.28.0);
  Playwright pass at 1920×1080 and 1366×768 with zero console/page errors across three polls, menu
  open, drawer open, Back button, deep link `#lab=<id>&view=progress`, map bottom ≤ viewport at
  1366×768 (screenshots in `shots/stage1/`, script `tools/verify_stage1.py`).
- Live: the manager container was rebuilt from this tree and served both dev labs (`clabllm-dev`,
  `bgp-core`) with existing state, Git binding and backups intact.

**Not done yet (in plan order):**
1. Step 3(a) devices/drawer/map: map state dots and glyphs (`renderMapState`), renderer defaults
   (`.device-body:not([fill])` etc. — the CSS is ready, the renderer still emits the cream background
   and `#0066ff` bodies), map caption copy, empty/loading map states, context-menu copy with inline
   reasons, drawer attention actions ("Check credentials" / "Test login now"), `test_topology_menu_ui.js`.
2. Step 3(b) Progress tab: today the tab shows the OLD Git repository layout inside the new panel
   (status card + `#git-repository-content`); the Saved versions list, first-save dialog, quiet saves,
   recent-saves rows, folder-browser placement, restore copy and the `tab==='git'` → `gitTabActive()`
   change are all pending (addendum §D, §H, §J6).
3. Step 3(c) operations/management/capture/pages copy sweep and dialogs (per-action review copy with the
   unsaved-work line, opLabels student labels + `opReviewCopy`, telemetry settings copy, standalone
   pages, Diagnostics rename, `workspace.html` loading `status.js`).
4. Step 4 stylesheet fix pass is largely done (the audit/fix pass already applied §J8's tokens, focus
   ring, menu-button, tablist, glyph and skeleton rules) — re-audit after 3(a)–(c) land.
5. Steps 5–6: full "after" Playwright pass at 1440×900 too, live-lab pass (redeploy `bgp-core`, save,
   checkpoint, apply from folder, capture, telemetry, destroy cancelled), docs, `set-release.py 1.29.0`
   + CHANGELOG/VALIDATION/agent-instructions sections, CI test list, final report with Functional
   Parity ("Intentionally removed: None").

**Known rough edges to fix in step 3:** Devices tab rows use the old address line and the technical
table toggle is plain; the header Grafana link keeps its old text until the Tools card copy lands;
the Lab actions menu items for stop/restart/redeploy are wired but their capability gating is only
checked on first open; `#lab-start` is disabled on a Running lab with the reason shown in the menu.
