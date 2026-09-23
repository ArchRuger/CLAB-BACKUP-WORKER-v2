# Documentation audit and technical-debt cleanup: the record

One record for the audit that started on 2026-09-20 from `main` `d510b7a`. The resumable state is in
[PICKUP.md](PICKUP.md). This folder is ordinary living documentation: it follows the version rules of
[repository maintenance](../REPOSITORY-MAINTENANCE.md) (chunks are named by number and commit, not by
release), and what each release changed is in the [changelog](../CHANGELOG.md).

Evidence classes used below: **static** (read or searched), **unit** (the Python and `node:test`
suites), **fixture** (the fixture manager in a browser), **CI**, **live** (a real VM, lab or remote).
Nothing in this audit is live evidence unless a row says so.

## 1. Baseline

| Item | Value | Evidence |
|---|---|---|
| Base | `origin/main` `d510b7a`, the merge of pull request #43; tree identical to `claude/ui-review-001` `3578907` | `git diff --stat`, `gh pr list --state all` |
| Audit branch | `claude/maintenance-audit`, created from that commit; no open pull request existed | Git |
| Python suite | 711 tests, OK, 1 skipped (the opt-in EOS SSH fixture) | unit, run at the base commit |
| Browser suite | 189 tests pass with the system Node 18; Node 24 is only needed for the editor build | unit |
| Release check | passes | `python3 deploy/verify-release.py` |
| Links | 77 tracked Markdown files; 6 broken relative links, all in one archived guide | `tools/check_links.py` |
| Default-loaded agent instructions | 141,185 bytes (`CLAUDE.md` + the imported handoff history + the maintenance rules) | `wc -c`; bytes, not measured tokens |

## 2. Model routing: requested and effective

The brief asked for Sonnet, Haiku and Opus routes. The session's user settings
(`~/.claude/settings.json`) set `CLAUDE_CODE_SUBAGENT_MODEL` and `availableModels` to one model, and
three probe tasks requested as `haiku`, `sonnet` and `opus` each reported that same model. The brief
forbids changing global settings or working around a restriction, so every task below ran on the
session's model regardless of the requested route. With no cheaper route available, the lead did the
deterministic and shared-file work itself and delegated only where isolated context or an independent
review paid for a worker's fixed start-up cost (roughly 80 thousand tokens per worker, measured on the
probes).

| Task | Deliverable | Specialist | Requested → effective | Reason | Write owner | Acceptance |
|---|---|---|---|---|---|---|
| L0 | Inventory, links, CI-versus-local test lists, baseline | Deterministic tools | none | Scripts answer it | Lead | Outputs reproducible |
| L1 | `CLAUDE.md` migration, architecture module map, pickup status lines, this record | Audit lead | lead model | Shared files; the lead already held the whole handoff in context | Lead | R1 review, release check, link check |
| T1 | Installation and operations guides against `deploy/` | Domain auditor and writer | sonnet → session model | Large read scope, isolated context | T1 (eleven guides) | Release check, link check, findings table |
| T2 | Student workflow guides against the UI code and routes | Domain auditor and writer | sonnet → session model | Same | T2 (nine files) | Same |
| T3 | Dead-code and CI-gap candidates with consumer traces | Maintenance scout, read-only | sonnet → session model | Shared-globals tracing is context-heavy | none | Evidence per candidate |
| V2 | Thirty of the statements added in chunks 2 and 3, against the code | Verifier, read-only | sonnet → session model | The brief asks for an independent check of ordinary changes | none | Tally and the wrong ones only |
| V1 | A producer for any selector, handler or import removed in chunk 4; the new CI step on a clean runner | Risk reviewer, read-only | opus → session model | Consequential deletion | none | Finding list; none found, two wording follow-ups applied |
| R1 | Lost or misstated obligations in the `CLAUDE.md` migration | Risk reviewer, read-only | opus → session model | Instruction migration is consequential | none | Finding list with severity |

## 3. Disposition table

Status: **chunk N** (changed in that chunk, see [PICKUP.md](PICKUP.md) for which chunks are pushed), **kept**
(audited, no change needed), **open** (see §5).

| Path or group | Audience | Purpose | Decision | Evidence | Risk | Task | Status |
|---|---|---|---|---|---|---|---|
| `CLAUDE.md` | Agents | Always-loaded guidance | Update (default-loaded set 141,185 → 28,817 bytes): removed the false "unreleased redesign" and "no Docker here" statements, stopped importing the handoff history, added the three frontend layers, an invariant digest and a routing table | Git history (redesign, builder and UI review merged), `main.py` CSP line, `lab-builder/package.json`, CI builder step | High (misroutes agents) | L1, R1 | chunk 1; R1 found five must-fix and seven smaller items, all applied |
| `agent instructions.md` + symlink `agent-instructions.md` | Agents | Per-release handoff history, one content source | Keep both; no longer auto-loaded; the only import consumer was `CLAUDE.md`, the release check reads the real file | `rg` over consumers; `verify-release.py` `HISTORY_FILES` | Medium | L1 | chunk 1 |
| `docs/REPOSITORY-MAINTENANCE.md` | Maintainers, agents | Release and documentation rules | Keep, still imported by `CLAUDE.md`; add this folder's tool | Matches `verify-release.py` and CI | Low | L1 | chunk 1 |
| `docs/ARCHITECTURE.md` | Everyone | Diagrams and module map | Update: the static-files row described the UI before the redesign; `downloads.py` and `grafana_control.py` were missing | File lists against the map | Medium | L1 | chunk 1 |
| `docs/README.md` | Everyone | Documentation index | Update: add this folder | Link check | Low | L1 | chunk 1 |
| `docs/ui-review-001/PICKUP.md`, `docs/lab-builder/PICKUP.md` | Agents | Work-stream records | Update the status lines only (merged, verified on GitHub); every qualification kept | `gh pr list` | Medium | L1 | chunk 1 |
| `docs/redesign/` notes | Agents | Design contract, inventory, parity, critique | Keep: the addendum is still the binding UI contract; status line already says released | Read | Low | L1 | kept |
| `docs/redesign/tools/`, `docs/ui-review-001/tools/`, `docs/lab-builder/tools/` | Agents, maintainers | Fixture manager and Playwright regression checks | Keep where they are: moving them breaks the documented commands in three pickups and the handoff; they are executable tooling, not notes | Consumers in `CLAUDE.md`, pickups, handoff | Medium | L1 | kept |
| `docs/redesign/shots/` (67 files) | Report readers | Before and after evidence of the redesign | Keep: referenced history | `git ls-files` | Low | L1 | kept |
| `docs/archive/*` | History | Superseded guides and proposals | Keep; repaired six relative links in `DOCKER-HUB-SETUP.md` broken by its move into the archive | `tools/check_links.py` | Low | L0 | chunk 1 |
| `docs/INSTALL.md`, `QUICK-INSTALL.md`, `FRESH-VM-GUIDE-V2.md`, `STANDALONE-SETUP.md`, `WIKI-MASTER-GUIDE.md` | Operators | Five installation routes for five readers (paste-only, build-it-yourself with recovery, installer reference, manual pieces and migration, self-contained Wiki.js copy) | Keep all five, no merge: the overlap is purposeful. Update: a save no longer "pushes automatically" (the upload review is mandatory), retry button labels, VM connection field labels, the dialog and menu names after the redesign, `UI_BIND`/`UI_PORT` belong in `clab-backup-ui/.env`, the Junos switch kinds have a documented default login and live restore, the Git wizard's subfolder prompt, commands made absolute | `git-progress.js` `gitUploadLabel`, `management.js`, `inventory.DEFAULT_CREDENTIALS`, `restore_junos.SUPPORTED_KINDS`, `setup_telemetry.py`, `git-onboard.py` | High (a student waits for a push that never comes) | T1 | chunk 2 |
| `docs/HEALTH-CHECK.md`, `VM-CONNECTION.md`, `GIT-SETUP.md` | Operators | Health check, VM account, Git registration | Update labels and the review step; installer menu, phases, flags, check outcomes verified correct | `install-manager.py`, `check_install.py`, `start-manager.sh` | Medium | T1 | chunk 2 |
| `docs/CAPTURE.md`, `TELEMETRY.md`, `GRAFANA-MAP.md` | Operators | The two side stacks | Update UI labels only (Tools › Telemetry links, *Restart devices*, *Advanced options*, capture dialog names); every port, `.env` key, default, limit and bound verified correct | `index.html`, `app.js`, `capture.js`, `setup_capture.py`, `setup_telemetry.py`, compose files | Low | T1 | chunk 2 |
| `README.md`, `docs/TOUR.md` | Everyone | Overview and screenshot tour | Update: workstation upload, the builder, the upload review, *Diagnostics*; three stale screenshots regenerated from the fixture manager (simulated data) | `index.html`, `home.js` | Medium | T2, L1 | chunk 3 |
| `docs/LAB-OPERATIONS.md`, `LAB-BUILDER.md`, `clab-backup-ui/NODE-FEATURES.md` | Students, operators | Lab commands, map and editor, node features | Update: Undo/Redo, *Device look…*, *Link labels…*, what the Topology tab keeps but does not draw, destroy cleanup default, *Advanced options*, import confirmation, labels from before the redesign; new "Backup download names" section (no living guide had the contract) | `map-editor.html`, `operations.js` `opDestroyOptions`, `downloads.py` | Medium | T2 | chunk 3 |
| `docs/GIT-PROGRESS.md` | Students | The Progress tab | Update: mandatory review, a folder move uploads on its own confirmation, *New folder…* without the tick only plans a folder, the real recovery labels | `git_progress.py` save and retry routes, `git-progress.js` | High | T2 | chunk 3 |
| `docs/NAMING.md` | Instructors | Course structure and the scaffold tool | Update labels; records that `scaffold-lab.py snapshot` stops at the review (see §5) instead of claiming an automatic push; added to the index, where it was missing | `deploy/scaffold-lab.py`, `git_progress.py` | High for instructors | T2, L1 | chunk 3 |
| `docs/DEBUG-PANEL.md`, `clab-backup-ui/README.md`, notices, fixture and template READMEs | Various | | Keep: verified against `debug.html`, `debug.js` | Read | Low | T2 | kept |
| `app/static/style.css` | Maintainers | Manager stylesheet | Remove 70 rules and 20 selector-list entries whose classes no markup, script, test, tool, editor bundle or vendor file produces (the old sidebar shell, the old landing panel and tab strip, orphan classes, `button.git-saved-job`, the unused `--focus` alias); stale comments fixed | Class-by-class search over every consumer; rule-aware script; before and after screenshots | Medium | T3, L1 | chunk 4 |
| `operations.js`, `management.js` | Maintainers | | Remove two handlers for ids that no markup creates (`deploy-empty`, `home-import`) | Search over markup, tests, tools; `test_home_ui.js` asserts the ids are gone | Low | T3, L1 | chunk 4 |
| `app/discovery.py`, `inventory.py`, `main.py`, `telemetry_map.py`, `telemetry_metrics.py`, `deploy/capture/smoke.py`, `deploy/setup_telemetry.py` | Maintainers | | Remove unused imports and one unused exception name; no re-export, patch target or `getattr` reaches them | pyflakes, vulture, search over tests and tools, import check | Low | T3, L1 | chunk 4 |
| `.github/workflows/release-check.yml` | Maintainers | CI | Add the eight test files CI never ran (`test_app`, `test_diagram_editor`, `test_downloads`, `test_import_confirmation`, `test_manager_reset`, `test_remove_lab`, `test_topology`, `test_vm_password`; about nine seconds); `test_eos_ssh.py` stays opt-in | Workflow read line by line; each file run locally | Medium | T3, L1 | chunk 4 |
| Stale UI wording printed by `deploy/git-onboard.py`, `check_install.py`, `setup-telemetry.sh` and `vm-connection.html` | Operators | Closing hints | Update to the current labels and the review step | The same label evidence as the guides | Medium | T1, L1 | chunk 4 |
| `docs/INSTALL.md` | Operators | Installer reference | Update: the four telemetry `.env` keys, their defaults and rules were named in no guide; now a table (read from `setup_telemetry.py`) | `setup_telemetry.py` `port_value`, the bind and idle checks | Low | L1 | chunk 5 |
| `.claude/agents/` (`docs-auditor`, `mechanical-editor`, `risk-reviewer`) | Agents | Task routes that carry their model in the definition | New, three small definitions; `CLAUDE.md` "Delegating work" explains them and the setting that can override them | The brief's routing table; Claude Code's agent `model` field | Low | L1 | chunk 5 |
| `host_git.py` `allowed_version()`, unused names in `restore.py` | Maintainers | Sensitive modules | Removed in follow-up 3 after a risk review; the two unused Junos names stay with a note | Caller search, helper and restore tests, independent review | Medium | L1, V3 | follow-up 3 |

## 4. Feature-to-documentation map

Evidence column: what validation exists, by class; "fixture" rows were re-run in this audit
(`verify_after.py`, 98 checks at three window sizes), the rest is cited from the validation record.

| Workflow | Implementation entry point | Current behaviour | Canonical guide | Evidence |
|---|---|---|---|---|
| Deploy a lab from a VM file | `home.js` `#home-deploy` → `operations.js` `openDeploy()` | Topology browser (*Lab folders on the VM*), reviewed deploy | [Lab operations](../LAB-OPERATIONS.md) | unit, fixture; live in the validation record |
| Deploy from a workstation file | `operations.js` `opUpload()` → reviewed `create` | File checks, parse without reading the VM, path derived under a trusted root | [Lab operations](../LAB-OPERATIONS.md) | unit, fixture; never exercised against a real VM |
| Build a lab | `lab-builder.html`, `lab-builder-page.js`, helper `publish` / `revise` | Browser drafts, reviewed save, revise only while undeployed | [Lab builder](../LAB-BUILDER.md) | unit, fixture; live with Linux hosts only |
| Recent labs | `home.js` `homeOrder`, `LabOperations.record_deployment()` | Time of the last successful deploy, undated labs last | [Tour](../TOUR.md), [Lab operations](../LAB-OPERATIONS.md) | unit, fixture |
| Lifecycle, destroy | `lab_operations.py`, `host_operations.py` | Reviewed commands; destroy cleans up by default where the helper allows | [Lab operations](../LAB-OPERATIONS.md) | unit, fixture, live |
| Discovery and import | `discovery.py`, `vm_files.py`, `management.js` | Manager ▾ › *Labs found on the VM…*, preview token and confirmation | [Lab operations](../LAB-OPERATIONS.md), [VM connection](../VM-CONNECTION.md) | unit; the successful confirmation was not exercised in a browser |
| Readiness and logins | `node_readiness.py`, `runner.effective_credentials` | SSH login plus `show version` | [Lab operations](../LAB-OPERATIONS.md), [Node features](../../clab-backup-ui/NODE-FEATURES.md) | unit, live |
| SSH terminals | `node_services.py`, `terminal.html` | Single-use ticket, origin-checked WebSocket | [Node features](../../clab-backup-ui/NODE-FEATURES.md) | unit, live |
| Backups and downloads | `runner.py`, `downloads.py` | Per-device files and ZIP with readable names | [Node features](../../clab-backup-ui/NODE-FEATURES.md#backup-download-names) | unit (in CI from chunk 4) |
| Save progress and upload review | `git_progress.py`, `git-progress.js` `gitReviewJob` | Every upload needs the review | [Save progress](../GIT-PROGRESS.md) | unit, fixture; a real upload to a Git host was never exercised |
| Save location, folders | `git-places.js`, `host_git.py` | Folder browser, planned folders, moves, connect by URL | [Save progress](../GIT-PROGRESS.md), [Git setup](../GIT-SETUP.md) | unit with real Git, fixture; a real folder move was never exercised |
| Apply to running lab | `restore.py`, `restore_junos.py` | Junos only, mandatory pre-backup, confirmed commit | [Save progress](../GIT-PROGRESS.md) | unit, live on both Junos kinds |
| Edit map | `map-editor.html`, `map-editor-page.js`, `GET`/`PUT …/map-document` | Map only; page-level undo; device look; link labels; arrows, rounded text backgrounds and nested groups are kept but not drawn on the Topology tab | [Lab operations](../LAB-OPERATIONS.md), [map parity](../ui-review-001/MAP-PARITY.md) | unit, fixture, live on a QA lab |
| Exports | `drawio_export.py`, `topology.py` | draw.io, annotations JSON, SuperPuTTY XML with opt-in passwords | [Node features](../../clab-backup-ui/NODE-FEATURES.md) | unit |
| Browser Wireshark | `capture.py`, `capture_sessions.py`, `capture_service.py` | Sessions in the pinned VM image | [Browser Wireshark](../CAPTURE.md) | unit, CI smoke with real packets, live |
| Telemetry and Grafana | `telemetry*.py`, `grafana_control.py` | Automatic collection, Grafana started on demand | [Telemetry](../TELEMETRY.md), `GRAFANA-MAP.md` (removed as of 1.30.39; see [TELEMETRY.md](../TELEMETRY.md)) | unit, CI smoke, live on cEOS |
| Install, upgrade, recover | `deploy/install-manager.py`, `start-manager.sh`, `check_install.py` | Seven phases, both stacks included | [Install](../INSTALL.md), [Health check](../HEALTH-CHECK.md) | unit; live in the validation record |

## 5. Remaining debt

Confirmed defects are marked **defect**; everything else is a hypothesis or a decision to take.
"Model" is the route the brief would give the task.

| Item | Kind | Impact | Evidence | Why deferred | Next step | Model |
|---|---|---|---|---|---|---|
| ~~`deploy/scaffold-lab.py snapshot` cannot finish~~ | resolved in follow-up 1 | | The tool states the review itself after showing the files (`--yes` for scripts), uploads or sets the save aside before it rebinds; its fake manager is faithful now | | | |
| ~~An unchanged save opens a review with an empty diff~~ | resolved in follow-up 4 | | The manager ends such a save `unchanged` only when the reused commit is known to be uploaded under the same binding; otherwise the review still waits. Unit evidence only: the fixture's scripted helper never answers `unchanged` | | Make the fixture helper answer `unchanged` and add a browser check | Sonnet |
| ~~`deploy/compose.image.yml` does not pass `TELEMETRY_GRAFANA_IDLE_MINUTES`~~ | resolved in follow-up 1 | | Line added with the same default; a test keeps both compose files' settings equal | | | |
| Image-only installs and the stack setup scripts | documented in follow-up 1, script unchanged | `recreate-manager.sh` still uses the source compose file | The Wiki guide's prepared-image part now gives the working route (`--no-recreate`, settings copied into `deploy/image.env`, recreate with the image compose file) | A script change needs a scratch VM | Optional: teach `recreate-manager.sh` to detect a prepared-image installation, or retire the route | Opus |
| ~~Unused names in `host_git.py` and `restore.py`~~ | resolved in follow-up 3 | | Removed after a risk review. `restore_junos.py` kept `pending_rollback_shell()` and `COMMIT_ERROR` then. Decided since by the multi-platform restore work: an interrupted restore does probe the node (`RestoreService.start()` reads every node that was mid-change back), the probe is `pending_commit()`, and `COMMIT_ERROR` was replaced by the narrower `COMMIT_FAILED` | | none | |
| ~~`shell.js` `lastOpened()` and the `clab.lastLab` write~~ | resolved in follow-up 2 | | Removed; the test's claim was rewritten to what is still true | | | |
| `main.py` audit text contains mojibake (`â†’` for `→`) | **defect**, cosmetic | Garbled arrow in `api.request` log lines | `main.py` guard | Changes log text | One-line fix with a logging test | Haiku |
| `vJunos-switch` "cannot run inside a VM" in two guides versus the validation record, which deployed one on the dev VM | contradiction to settle | Misleads readers | Fresh VM guide, Wiki guide part 2, validation record | Needs the maintainer's knowledge of the supported setups | Reword once confirmed | Sonnet |
| The Wiki guide's "Edit the map and export" section describes the basic editor's layout | stale section | Low | Read | The Wiki guide is self-contained by design; needs a rewrite from [Lab operations](../LAB-OPERATIONS.md), not a label fix | Rewrite the section | Sonnet |
| `CAPTURE_BIND` and `CAPTURE_PORT` exist in `deploy/compose.capture.yml` but are not settable in practice | hypothesis | An operator who changes them gets a capture setup that rewrites the manager's addresses to the fixed localhost ports | `setup_capture.py` writes `CAPTURE_EDGESHARK_URL` and `CAPTURE_SESSION_URL` as fixed values | Removing or wiring the two variables is a deployment change | Decide: drop the two variables from the compose file, or make the setup honour them | Sonnet, Opus review (capture boundary) |
| `docs/redesign/tools/verify_stage1.py`, `audit_*.py` target the UI before the redesign | historical tooling | None | They query removed ids | History folder; harmless | Leave, or mark in the redesign pickup | Haiku |
| First-run Home lists *Already running on the VM* (`#empty-discovered`) while the handoff says no discovery list on Home | recorded decision (UI review checklist), not a defect | Could misroute an agent | `index.html`, `management.js` | Documented as is | Note the exception in the next handoff section that touches Home | none |
| No screenshots of Edit map, the lab builder, the save help pane or the upload review | gap | | Tour | Needs new fixture states | Add captures to `verify_after.py` | Sonnet |

Carried over unchanged from the [UI review pickup](../ui-review-001/PICKUP.md), confirmed there and not
re-tested here: the Topology tab keeps but does not draw line arrows, rounded text backgrounds and nested
group levels; a real review-and-upload to a Git host, a real upload with `create` and a real folder move
were never exercised against real services; a failed `bind_lab` after the VM retired the old registration
leaves a lab pointing at a missing registration; the lab banner is too tall at 200 % zoom.
