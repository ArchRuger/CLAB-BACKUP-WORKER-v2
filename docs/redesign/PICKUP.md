# Student-centred UI redesign — pickup notes for the next agent

**Status: RELEASED as 1.29.0 on 2026-09-17** after the live-lab pass (see §7's newest entry and
`clab-backup-ui/VALIDATION.md`). The notes below are the history of the redesign. Read this file first, then `DESIGN-SPEC.md` and `DESIGN-SPEC-ADDENDUM.md` (the addendum overrides
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

### 2026-09-17 (later still) — student-page screenshot pass on the live dev VM; eight layout fixes, released as 1.29.1

Systematic screenshot sweep of every student page and dialog (My labs and the Manager menu; Topology
with the context menu, the expanded map, the More menu and the device panel; Devices and Technical
view; Progress with every dialog; Tools with the capture and telemetry dialogs; Advanced; Lab
actions, the destroy review, All lab operations and Operation history; the CLI launcher, deploy page,
terminal, Diagnostics and both guides) against the live manager on `clab-llm-dev2` at 1440×900,
1280×720 and 1920×1080 (`~/ui-review/student_shots.py` on the VM: Playwright, one screenshot per
state, a layout probe for right-edge overflow and clipped text, console and page errors collected),
plus the desktop app's browser pane at 800 px. Fixed, in `style.css` unless noted:

- Topology device rail: a long network OS badge (`Junos (vJunos-switch)`) ran under the state pill.
  The rail row is a named grid now — name and pill on the first line, the badge on its own line, the
  reason and the actions below.
- Expanded map filled only the top-left corner of its overlay: the grid rule's `align-items: start`
  carried into the flex column and the rule targeted a `.topology-body` element the markup no longer
  has. The map column stretches and the SVG takes the stage height.
- The map toolbar's More ▾ items were drawn as boxed toolbar buttons (`.map-tools button` leaked into
  `.menu-list`); the rule excludes menu items.
- Tools: the cards use `auto-fit` with a 400 px minimum, so three cards share the row instead of
  leaving an empty fourth column; the schedule label and its hint have their own lines; the backup
  summary's date and device count no longer break mid-phrase (`app.js` `jobMarkup` wraps each in a
  span).
- Capture dialog: the "Choose a device above…" sentence spans the interface grid instead of one
  145 px cell.
- All lab operations: "Open all CLIs ↗" keeps the arrow on the label's line (`operations.js`; the
  grid buttons are column flexboxes).
- Progress error state ("Saved progress could not be loaded"): the Try again button is centred with
  its text, and the manager's own sentence leads (`git-progress.js`; a 409 helper-version answer said
  what to do while the copy told the student to check the VM connection).
- Advanced: key/value lists keep a 12 px gap from the heading or caption above them.

Not a defect: the capture setup page's long commands sit in a scrollable `pre` (headless Chromium
hides the scrollbar in screenshots). Environment finding: after the checkout moved to `main` the VM
Git helper had to be refreshed (`sudo bash deploy/setup-git.sh --refresh`); until then
`/api/git/repositories` answered 409 and the Progress tab showed its error state.

Validation: `node --test tests/*.js` 134/134; `node --check` on the changed scripts; live sweep of
42 screenshots per viewport with 0 console errors, 0 page errors and no layout flags beyond the
`sr-only` label and the scrollable `pre`; `verify_after.py` against the fixture manager 93/93 at
1920×1080, 1440×900 and 1366×768 with 0 console / 0 page errors. The tour images in
`docs/images/ui/` that show the rail, the Tools cards, the capture dialog and the Advanced lists were
regenerated from that fixture run. No backend, helper or route changed. Released as 1.29.1 directly
on `main`: `set-release.py`, the three history sections, `verify-release.py`, the Python suite and
`bash -n` on the VM, a container rebuild at 1.29.1 with the helpers refreshed.

### 2026-09-17 (later) — live-lab pass done on `clab-llm-dev2`, two fixes, released as 1.29.0

The host became the dev VM (quick-install: Docker 29.8.1, containerlab 0.79.0, both stacks, Git
helper). Lab `clab-llm-dev2` (PTX1 `n24l/cjunosevolved:26.2R1.7-EVO`, SW1
`n24l/vjunos-switch:23.2R1.14`, links on the `et-0/0/0` aliases, pinned `mgmt-ipv4`) deployed and
redeployed through the UI; Git `pruger-dev/CLAB-MNGR-DEV-LLM` at `clab-llm-dev2/work` with the
scaffold's `reference/{start,solution,broken-01}`. Every gate in the brief was exercised live
(table in VALIDATION.md). Found and fixed: the helper refusing repeat saves into schema-2 folders
(blocker) and Saved versions missing nested reference states (medium). Then
`set-release.py 1.29.0`, the history sections, `verify-release.py`, rebuild, PR #37, CI green.

### 2026-09-17 — release-validation pass on `claude/1.29-release-validation`: BLOCKED on the live-lab gate (superseded the same day)

Branch from `main` `66864c8` (PR #35 merged). Done: `.github/workflows/release-check.yml`
names `tests/test_topology_menu_ui.js` in *Check browser regressions* (all 17 browser suites
listed); GitHub Actions run 35207663245 green end to end. Re-baselined on `clab-llm-dev2`:
`node --test` 133/133, Python 691 OK (1 skipped), `node --check` 18 files, `bash -n` 15
scripts, `git diff --check`, `verify-release.py` 1.28.0, `verify_after.py` 93/93 at the three
viewports with 0 console / 0 page errors (Chromium needed five Ubuntu libraries extracted with
`dpkg-deb -x` under `LD_LIBRARY_PATH`), static security sanity (socket only in the capture
compose, CSP intact, no inline script/style). **Not done: the live-lab pass** — `clab-llm-dev2`
is not the dev VM (no Docker, containerlab, data directory, sudo, or route to the VM; §2's
`/home/clabllm/clab-venv` does not exist there, use `clab-backup-ui/.venv`). No version bump,
no "Unreleased" rename. Next agent, on the dev VM: run §4 step 5 in full (see the gate table in
`VALIDATION.md`), then `set-release.py 1.29.0`, the history sections, `verify-release.py`,
rebuild, PR.

### 2026-09-17 — stages 4, 5 and the documentation of 6 done; live-lab pass and the release remain

**Stage 4 (style/accessibility audit, focused):** no inline `style=` anywhere (SVG presentation
attributes only), no coral outside the danger tokens, every disabled control now carries a visible
reason (menu `.menu-reason`, `data-proxy-reason` captions under the Advanced buttons and the Danger
zone, the banner's Details line for a disabled Start, the device panel's note for a disabled Capture
traffic), device row ids collision-free (`deviceSlug` + hash), Action logs refreshed on the poll only
while the section is on screen, one extra `render()` on `DOMContentLoaded` (`shell.js`).

**Stage 5 (integration):** `node --test tests/*.js` 133/133; Python `unittest` OK (1 skipped); `node
--check` clean; `git diff --check` clean; `deploy/verify-release.py` passes (1.28.0); id audit clean.
`docs/redesign/tools/verify_after.py` now covers Home, Topology (map fits at 1366×768, context menu,
expanded map, editor, import dialog, empty map), Devices, Progress (versions, compare, apply review,
first save, save window, checkpoint name, save location browser, unbound lab), Tools (capture dialog,
telemetry settings), operations (menu reasons, destroy review, stop confirm → banner, output window,
All lab operations, Running labs on the VM + table, history), Advanced (+ Remove lab), polling
stability (device panel and a menu across two polls, focus kept) and the standalone pages (CLI
launcher, deploy page → browser → editor → preview, Diagnostics + checks, network dashboard page,
terminal, guides): **93/93 checks at 1920×1080, 1440×900 and 1366×768, 0 console errors, 0 page
errors**, one handled HTTP 409 per viewport (the optional `.annotations.json` read). Screenshots:
`shots/after/` (1366×768 set) and `docs/images/ui/` (the tour, 1440×900). The fixture manager
answers `lab_operations.remote` in-process (capabilities, browse, read, preview, run) and gives two
labs a `vm_project_path`.

**Functional-parity review:** four independent read-only code reviews against `inventory/*.md` and
`parity/*.md` (shell + topology; git-progress + git-places + restore; operations + management;
capture + pages). Every inventory row present. Findings fixed here: destroy copy conditioned on the
cleanup option; clone review titled after the project (not "manager"); busy-disabled Advanced
controls carry a reason; the restore review shows the lab again (`Lab:` line); a failed history/tree
fetch reads as "Try again", never "not saved yet"; the blank Progress state has *Check again*;
*Browse the repository…* opens the folder browser from Saved versions; checkpoint rows no longer
borrow another checkpoint's time; lab-scoped operation history from Lab actions ▾ and Advanced
(Manager ▾ keeps every lab); *Lab files…* opens files bound to the lab (link, not duplicate);
per-lab VM file details of every lab under Advanced › Deployment details; capture's service hint
relabelled, *Refresh list* re-asks the manager while the service is missing, the Tools caption links
the setup guide; the terminal clears its raw title on close; Diagnostics reports "The manager
answered HTTP n: …"; `opSaveWorkspace` routes through `selectLab`. **Intentionally removed: none.**

**Stage 6 (documentation):** `docs/TOUR.md` rewritten around the student UI with the after
screenshots; `docs/LAB-OPERATIONS.md`, `docs/DEBUG-PANEL.md` (Diagnostics), `README.md`,
`docs/README.md`, `docs/ARCHITECTURE.md`, `clab-backup-ui/NODE-FEATURES.md`, `docs/GIT-PROGRESS.md`
and the label sweep across `docs/WIKI-MASTER-GUIDE.md`, `TELEMETRY.md`, `CAPTURE.md`,
`GIT-SETUP.md`, `NAMING.md`, `INSTALL.md`, `QUICK-INSTALL.md`, `FRESH-VM-GUIDE-V2.md`,
`HEALTH-CHECK.md`, `STANDALONE-SETUP.md`; "Unreleased" sections at the top of `docs/CHANGELOG.md`
and `VALIDATION.md` (the release check keys on "Changes in x.y.z" / a heading ending in the
current release, so both pass at 1.28.0); the handoff section of `agent instructions.md`.

**Not done — external blockers:** the live-lab pass (this host has no Docker, containerlab, lab VM
or manager data directory; see §2) and therefore the release: run the §4 step 5 live list on the
dev VM first, then `python3 deploy/set-release.py 1.29.0`, rename the two "Unreleased" sections and
record the live results in `VALIDATION.md`.

### 2026-09-17 — stages 3(b) Progress tab and 3(c) operations / management / capture / pages done

**3(b) done and verified:** `git-progress.js` rewritten around the student vocabulary (`gitSaveSentences`,
`gitJobTitle`, `progressSummary` for the status card, `gitVersionGroups` → Latest / Checkpoints / Baseline /
Instructor and reference versions / Other labs in this repository, `gitRenderSaves` rows with Open / Upload
now / Keep snapshot only, `gitFirstSave` "Where should <lab>'s progress be saved?", quiet saves that only open
the job window for attention states, `gitCheckpointName` live "Saved as:" preview, Save location card with the
folder browser inside the form, blank state without a catalog); `git-places.js` student folder copy and the
`options.tree` reuse; `restore.js` rewritten (`restoreJobLabels`/`restoreTargetLabels`, reasons in student
words with the raw reason under Details, review with Devices legend, three safety bullets, Advanced options,
acknowledgement, per-device outcomes); `index.html` Progress panel (status card, Saved versions, Recent saves,
`#git-problem`, `#git-last-restore`); apply-from-any-folder (`restoreFromFolder`) kept and exercised.
`verify_after.py` `progress` step: 68/68 checks at 1920×1080, 1440×900 and 1366×768, 0 console and 0 page
errors (screenshots 30–39). `fixture_manager.py` binds a second lab (`vlan-lab`) and fakes the restore probe
(`app.state.restore._capture`) so the review shows matching, differing and unreachable devices.

**3(c) done and verified:** `operations.js` (`opLabels` student table, `opReviewCopy` per-action title / effect /
confirm with `.button.danger` for the disruptive ones, the "Configuration changes you have not saved are lost."
line, the last-save line from `progressState` (red when never saved or older than the last operation) and
[Save progress first], raw argv and cleanup warning under Technical details, banner-first confirm for
lifecycle actions on the open lab, `opJobBanner` with the exit code as a separate detail, All lab operations
dialog in Deployment / Lab tools / Danger sections, telemetry settings copy with `Dashboard:` lines, history,
browser, editor, clone, preview copy, `opBrowse(path, labId)`); `management.js` (dialog copy without eyebrows,
`vmSummaryMarkup`, `vmFilesStatus`, sync/remove reasons, `.button.danger` on Remove lab and Start fresh,
Back up all review); `capture.js` + the dialog markup (device picker first with a switching summary, M1–M27
strings, `(kind)` only in VM scope, sessions asked for only when the service exists, Tools card caption when
disabled); `capture-session.*` V1–V11; `capture-setup.html` for administrators; `workspace.html/js` (loads
`status.js`; "Deploy a new lab"; CLI launcher "Open CLIs · <lab>" with `deviceState` pills and reasons, history
as a link row); `terminal.html/js/css` (device-first title, "← <lab>" link to `/#lab=&device=`, student status
map with the raw text in `title`, replace-not-append on close, Reconnect/Disconnect, notice + Details);
`grafana.html/js` ("Network dashboard · <lab>", `#grafana-headline` + raw Details); `debug.html/js`
("Diagnostics", card/probe/table copy, `code` → sentence map, `detail` surfaced); `vm-connection.html` link;
`app.js` Tools link "Open lab map ↗" / "Open network dashboard ↗", banner Start label from the menu `<span>`
and a disabled Start's reason as the banner Details; `shell.js` re-renders once on `DOMContentLoaded` (a fast
first `/api/state` could render before the later deferred scripts defined their renderers). Tests: the pinned
labels in `test_capture_ui.js`, `test_operations_ui.js`, `test_grafana_ui.js`, `test_readiness_ui.js` were
rewritten, every behavioural claim kept; `node --test tests/*.js` 133/133. Browser: `tools/smoke_3c.py`
against the fixture (whose `lab_operations.remote` is now answered in-process: capabilities, browse, read,
preview, run) — 23/23 checks, 0 console / 0 page errors, one handled HTTP 409 (the optional
`.annotations.json` read beside a topology, which the page expects to fail); screenshots 40–57. The Python
suite was not rerun for 3(c) (no backend file changed); stage 5 runs it. Live-lab validation still pending.

**Known, deliberate:** Chromium logs every non-2xx fetch as a console error ("Failed to load resource"); the
scripts report those the page handles (a missing optional file, a disabled service) apart from real errors.
The Diagnostics probe on the fixture fails by design (`diagnostics.py` binds `remote` at import time, the
fixture only patches `lab_operations.remote`), which is what exercises the failure rows.

### 2026-09-17 — stage 3(a) devices / drawer / map done (continuation branch `claude/continue-student-centered-ui-redesign`)

**Done and verified:** `topology-render.js` emits `state-*` classes, a `device-state-dot` and a glyph group per
device, `fill` only for imported colours (`.topology-bg`, `.topology-grid-dot`, `.device-body`,
`.device-label-bg` default from CSS); `topology.js` has `renderMapState()` (class swaps from `deviceState`, aria
labels and titles, `working` during a lab operation), the student context menu (state pill in the header,
inline reasons, Open CLI first), the loading / empty (`#map-empty`) / caption states, `data-label` on
`#map-expand`, Escape order; `app.js` calls `renderMapState()` from `render()`, leads the action row with Open
CLI, drops the address from the simple device rows and shows "Checking <device> again…" after a connection or
credential edit from the drawer; import/export dialog copy (GAP K/L), diagram-editor copy (GAP N);
`tests/test_topology_menu_ui.js` (7 tests, in CI). **This host is not the dev VM** (no Docker, no labs):
browser validation runs against `docs/redesign/tools/fixture_manager.py` (the real app on a scratch data
directory with seeded labs and scripted VM hooks) with `docs/redesign/tools/verify_after.py`
(1920×1080 / 1440×900 / 1366×768: 41/41 checks, 0 console errors, 0 page errors). Live-lab validation is
still pending and must happen on a VM with containerlab.


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
