# Student-centred UI redesign — engineering report

Branch `claude/continue-student-centered-ui-redesign` (continues the WIP merged from PR #33,
merged to `main` as PR #35), prepared on release 1.28.0. **Not released**: the release-validation
pass of 2026-09-17 (branch `claude/1.29-release-validation`) re-ran every automated gate and
fixed the CI test list, but ran on a host without the lab VM, so the live-lab pass and
`set-release.py 1.29.0` are still to do (see *Live lab validation* and *Remaining limitations*).

## 1. UX audit — what was wrong for a student

The findings of `UX-AUDIT.md` and `critique/*.md`, in one paragraph: the old UI was an
operator console. A sidebar mixed labs with manager-wide actions; the lab view opened on
the map with no statement of whether the lab was usable; readiness was expressed in NOS
and container vocabulary (*NOS booting 1/2*, *Ready* meaning "can be backed up"); SSH,
capture, backup and Git were four unrelated toolbars; the Git tab was a repository
browser first and a "save my work" button second; every host command opened a raw output
window; disabled controls gave no reason; the standalone pages (terminal, Grafana, debug
panel) spoke in backend terms ("Viewer authentication failed", "helper predates
on-demand Grafana"); and the topology map had no notion of device state.

## 2. Information architecture

- **Home — My labs**: lab cards (state pill · *n of m devices ready* · last save · Open lab
  · Start), the *Continue* card, *Also running on the VM* (Import, hidden labs, file check
  details), *Deploy a new lab*, and the **Manager ▾** menu (VM connection…, Import lab
  files…, Deploy a new lab…, Refresh lab list, Running labs on the VM…, Operation
  history…, Manager settings…, Diagnostics; VM status and version in its footer).
- **Lab workspace**: header (name, state, readiness, last save, **Save progress** ▾, **Lab
  actions ▾**), one situational banner, tabs **Topology · Devices · Progress · Tools ·
  Advanced**, and the **device panel** (state, actions, status with *Test login now* /
  *Check credentials*, backups of the device, Advanced: connection and credentials).
- Routing: `#lab=<id>&view=<tab>&device=<name>`, Back button, legacy tab names mapped,
  session storage restores the last lab once; standalone pages keep their own headers.

## 3. Student workflow (the seven journeys)

Open a lab → see which devices are ready and why not → Open CLI → work → Save progress
(first save asks where; later saves are quiet) → create a checkpoint at a milestone →
compare with the latest save or apply an instructor's saved state without changing where
the lab saves → capture traffic on a link or an interface → look at the live map → stop,
redeploy or destroy with a review that says what is lost and offers *Save progress first*.

## 4. Visual system

Tokens on `:root` (ink, muted, surfaces, lines, accent, ok/warn/danger with soft and
strong variants, focus ring, radii, fonts), a menu-button pattern with roving keys, a
tablist, pills and state dots, a glyph sprite, skeletons for loading, a light code surface,
the drawer, and `terminal.css` re-tokenised for the dark terminal page. No inline styles,
no CDN, self-only CSP kept. Red is danger only.

## 5. Files changed

Frontend: `clab-backup-ui/app/static/` — `index.html`, `app.js`, `shell.js` (new), `status.js`
(new), `home.js` (new), `topology.js`, `topology-render.js`, `diagram-editor.js`,
`git-progress.js`, `git-places.js`, `restore.js`, `operations.js`, `management.js`,
`capture.js`, `capture-session.html/js`, `capture-setup.html`, `workspace.html/js`,
`terminal.html/js/css`, `grafana.html/js`, `debug.html/js`, `vm-connection.html`,
`style.css`. Tests: `tests/test_status_ui.js`, `test_shell_ui.js`, `test_home_ui.js`,
`test_topology_menu_ui.js` (new) and every existing browser suite whose pinned labels
changed. Tools: `docs/redesign/tools/fixture_manager.py`, `verify_after.py`. Docs: the
tour, the guides listed in `PICKUP.md` §7, `CHANGELOG.md`, `VALIDATION.md`, the agent
instructions. **Backend, helpers (`host_*.py`), routes, schemas: unchanged.** CI workflow: the
`node --test` list gained `tests/test_topology_menu_ui.js` on `claude/1.29-release-validation`
(the other three new suites were already named); the branch's GitHub Actions run is green.

## 6. Automated testing

`node --test tests/*.js`: 133 tests pass. Python `unittest`: OK, one opt-in fixture skipped.
`node --check` on every static script, `git diff --check`, `deploy/verify-release.py`
(1.28.0) all clean. Every old assertion that pinned a label was rewritten to the new label
with its behavioural claim intact; none was deleted or weakened.

## 7. Browser validation

`docs/redesign/tools/verify_after.py` against the fixture manager (the real application on
a scratch data directory with seeded labs, the VM answers scripted in-process) at
1920×1080, 1440×900 and 1366×768: 93/93 checks at each viewport, 0 console errors, 0
page errors (one handled HTTP 409 per viewport: the optional `.annotations.json` read the
page expects to fail). Covered: Home, every tab, the map (fits the viewport at 1366×768),
the context menu, the expanded map, the editor and import dialog, the empty map, the
device panel, the Progress flows (versions, compare, apply review, first save, save
window, checkpoint name, save location browser, an unbound lab), Tools (capture dialog,
telemetry settings), the operation reviews and the banner-first confirm, All lab
operations, Running labs on the VM with its table, operation history and output,
Advanced and Remove lab, polling stability with the device panel and a menu open across
two polls (focus kept), the CLI launcher, the deploy page with the topology browser,
editor and preview, Diagnostics with its checks, the network dashboard page, the
terminal page and the guides. Screenshots: `docs/redesign/shots/after/` and
`docs/images/ui/`.

## 8. Live lab validation

**Not performed — twice blocked by the host.** The redesign session and the release-validation
pass of 2026-09-17 both ran on hosts without Docker, containerlab, the lab VM or the manager
data directory (`clab-llm-dev2` in the second case: no engine, no data, no sudo, no route to
the dev VM), so the manager container was not rebuilt and the dev labs (`clabllm-dev`,
`bgp-core`) were not opened, deployed, saved, applied, captured or destroyed through the new
UI. The release decision of that pass is **BLOCKED** on this gate alone: every automated and
fixture gate passed again (`VALIDATION.md` has the table). The list to run on the dev VM is
in `PICKUP.md` §4 step 5 and `VALIDATION.md`.

## 9. Screenshots

`docs/images/ui/` (tour, 1440×900) and `docs/redesign/shots/after/` (1366×768 full set with
`report.json`); the before set is in `docs/redesign/shots/before/`.

## 10. Remaining limitations

- Live-lab validation and the release itself (1.29.0) are pending; the history sections
  are written as "Unreleased".
- The tour screenshots come from the fixture manager, not from a live containerlab
  deployment; the layout and copy are the real UI.
- Chromium logs every non-2xx fetch as a console error; the validation reports the ones
  the page handles separately (currently one per run).
- Vendor xterm assets on the terminal page carry no `?v=` marker (pre-existing, pinned).

## 11. Git

Commits on `claude/continue-student-centered-ui-redesign` from `main` `045a0cb` (the
merge of PR #34): stage 3(a) map/drawer/devices; stage 3(b)+3(c) Progress, restore,
operations, management, capture, pages; stage 4–6 fixes, validation, parity fixes and
documentation. Delivered as a pull request for the maintainer to merge.

## 12. Functional parity

Four independent read-only reviews checked every row of `inventory/*.md` against the
code (`parity/*.md` as the map): shell + topology, Git progress + places + restore,
operations + management, capture + pages. Every capability is present and reachable; the
defects those reviews found are fixed on this branch (listed in `PICKUP.md` §7).

**Intentionally removed: None.**
