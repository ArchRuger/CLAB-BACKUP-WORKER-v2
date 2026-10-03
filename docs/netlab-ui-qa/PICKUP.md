# Relentless netlab UI/UX campaign + Restart device: pickup file

Read this first. The assignment is the owner's `CLAB_Netlab_Relentless_UI_UX_QA_Campaign_v2.md` (kept
outside Git in the worktree root; revision 2 folds in `CLAB_Single_Device_Restart_Addendum.md`): validate,
debug, repair and polish every implemented netlab workflow, and implement **Restart device** (one node,
native `containerlab restart --node`, Containerlab VS Code extension parity) as the one authorized new
feature. Companion records in this folder:

- `COVERAGE.md` / `coverage.json`: the coverage inventory (stable IDs, one row per control/workflow/state).
- `DEFECTS.md`: the defect ledger (P0–P3, reproduction, root cause, fix, regression test, retests).
- `EVIDENCE.md`: index of evidence files under `evidence/` (sanitised; raw traces stay outside Git).
- `RESTART-PARITY.md`: the compact parity record for Restart device (extension ref, CLI, command, matrix).
- `tools/`: reusable checks (Playwright against the fixture manager or the deployed product).

## Branch, build, environment (2026-09-27)

- Branch `claude/netlab-integration`, worktree `~/projects/clab-manager-1.30.42`, HEAD `3194ec4` at start
  (release 1.30.47, PR #55 open). Push with the `ArchRuger` gh account, switch back to `pruger-dev`.
- Installed product: `clab-backup:1.30.48` since 16:31 UTC (`sudo bash deploy/start-manager.sh --manager-only`;
  container `containerlab-node-manager-backup-ui-1`, port 8081, data `/srv/containerlab-node-manager/data`), helpers
  1.30.48 under `/usr/local/lib/clab-manager` (verified by the launcher and `check-install.sh`: PASS 62, WARN 1 =
  folder coverage cap), capture stack `clab-manager-capture` (its session service ran `clab-capture-service:1.30.42`
  until the host crash of 21:32 UTC; reinstalled with `setup-capture.sh` at 22:02, now `clab-capture-service:1.30.49`). Earlier builds of the day: the 1.30.47 working tree at 13:37, 14:45 and 15:16 UTC.
- VM: Docker 29.8.1, **containerlab 0.79.0** (commit 5ae50094a, 2026-08-21; `restart --node` present),
  28 CPUs, 67 GiB RAM, 22 GiB free disk. Python 3.12.3; system Node 18.19.1 (Node 24 under
  `~/.local/node24`, only for the editor bundle). Playwright 1.63.0 in `clab-backup-ui/.venv`, Chromium
  1243 in `~/.cache/ms-playwright`.
- Routing: user settings `CLAUDE_CODE_SUBAGENT_MODEL=sonnet`, `_FORCE=0`; project agents carry their model
  (`risk-reviewer` opus, `docs-auditor` sonnet, `mechanical-editor` haiku). Requested vs observed routes
  are recorded per chunk below.
- Lab `restore-square` (four baseline images + `host1`) was **not deployed** at the start of the campaign
  (containers gone, lab folder held only the YAML). Redeployed with `sudo containerlab deploy` at
  13:10 UTC on 2026-09-27 (log: session scratch); devices start from containerlab startup configuration,
  not from the restore record's configuration A. Boot: cEOS ~1 min, cJunosEvolved ~8, XRv9k ~11–13,
  vJunos-switch ~17. Redeployed again at 15:15 UTC (vJunos-switch exited after its restart, QA-014) and at
  16:22 UTC (vJunos-switch exited again after the rerun; XRv9k on a fresh disk, QA-017, then stuck waiting for
  its link, QA-018); configuration A put back each time with `nodecli.py <node> --file …/base-configs/<node>.cli`
  (16:22 cEOS, 16:34 XRv9k, 16:40 vJunos-switch, cJunosEvolved ~16:44). **vJunos-switch cannot be restarted** and
  **XRv9k's first restart after a deploy loses its configuration**: plan live work around that (a redeploy plus
  configuration A takes ~20 min).

## Baseline (before any change)

- Python: `python -m unittest discover -s tests -t tests` → **1686 tests OK (1 skipped)**, 200 s.
- Browser: `node --test tests/*.js` → **347 pass, 0 fail**.
- `python3 deploy/verify-release.py` → 1.30.47 everywhere; `git diff --check` clean. No inherited failures.

## Chunks

| Chunk | Phase | Content | Release | Commit | Status |
|---|---|---|---|---|---|
| 0 | A | Baseline, runtime identity, lab redeploy, workspace skeleton, reference fetch (extension `6df8e96`, 0.26.3; containerlab restart docs), inventory (Sonnet: `COVERAGE.md`, 123 rows) and §6 probe charters (Sonnet) | none | | done |
| 1 | B2 | Restart device: helper action `restart-node` (fail-closed selector, one `--node`, target bound by container id/state), manager resolution and stale-consent checks, readiness epoch + `restarting` state + uptime hint, map menu and Devices/panel entry points, review copy, docs; unit tests (Python 1686→1692, browser 347→353); deployed on the dev VM 13:37 UTC; live on cEOS (66/66); cJunosEvolved first run 70/73 (map, stopped, terminal PASS; the second boot stalled in GRUB, capture list stale right after readiness → rerun on the reviewed build in progress); Opus risk review applied (RD-001…004); QA-001…QA-012 fixed (inventory + the ten §6 probes, all confirmed by the probe run) with 77 Design tab unit tests; stress pass and usability review running | 1.30.48 (not yet cut) | not yet committed | in progress |

## Exact next action

Release 1.30.48 is committed as `b4329d3` and pushed (remote verified); **PR #56** (`claude/netlab-integration` → `main`,
covering 1.30.44–1.30.48) is open and CI is green on `b4329d3` (runs 36339238311 and 36339241324). Markers moved, the three history sections written, `verify-release.py`
green, Python 1701 OK, browser 379, deployed on the dev VM (rebuilt at 17:57 UTC with the final wording). Running or just
finished when this was written: the final-build live runs (`session scratch: final-live.sh` → cEOS full run, the
neighbour check `tools/check_restart_neighbour.py`, two-tabs on `host1`, XRv9k restart 1 (fresh disk expected) →
configuration A → restart 2 (Devices view) with read-backs), and the coverage closure is done (Sonnet agent, `tools/coverage_run.py`: 112 PASS, 0 FAIL, 8 BLOCKED, 3 NOT RUN of 123 rows,
`evidence/coverage/`, `COVERAGE.md` › Results). Final-build live results so far (all on 1.30.48, redeployed lab with
configuration A): cEOS 78/78 (16:45), two-tabs 13/13 (16:50), XRv9k 27/27 + 52/52 with the known-limit note in every
review and the first restart losing its configuration (16:50–17:15), the later-restart persistence proof 27/27 with the
configuration kept (17:19–17:25), the neighbour checks in both stop modes (17:25, 17:26: parked link comes back, destroyed
link reported as `2 of 3 links restored`, cEOS then waits five minutes for the missing interface: `CLAB_INTFS`). The last
chain rebuilt the manager with the final wording (17:57), redeployed, reran both neighbour checks (20/20 each) and two-tabs
(13/13), and redeployed again (18:45) for the acceptance passes; cJunosEvolved's VM hung after that redeploy (guest soft
lockups) and was brought back with *Restart device…* itself (27/27 on the final build, 20:13) plus configuration A.
**Acceptance pass 1 (Sonnet, 19:29–20:11): CLEAN** (`acceptance/PASS-1-sonnet.md`; its finding F1 = three stale probe
assertions, corrected in `tools/probes/design_probes.py`). **Pass 2 (Opus, 20:22–20:49): NOT CLEAN** (`acceptance/PASS-2-opus.md`):
F-1 trailing whitespace in three evidence files, F-2 a false credentials failure during every XRv9k boot after a restart
(**QA-019**, product), F-3 the stale probe assertions, F-4 two live-check assertions that could not fail (TOOL-002). All four
fixed; **release 1.30.49 committed as `14c2f05` and pushed** (PR #57 carried it and was merged to `main` at 21:55 UTC as `e42d3b6`; CI green, run 36350623338): markers,
history sections, `verify-release.py` green, Python 1703 OK, browser 379, the manager rebuilt at 1.30.49 (20:58 UTC) and the
QA-019 live retest done (XRv9k `booting → ready`, no `failed`, configuration kept; cEOS 28/28 with the corrected tool). Both
acceptance passes were taken again on 1.30.49 (the gate is two clean passes on one build). **Pass 3 (Sonnet, started
21:12) was lost with the session when the VM crashed at 21:32** (`acceptance/pass-3/INTERRUPTED.md`: what it completed,
all clean; the crash; Docker's corrupted network store moved aside; lab redeployed 22:00 and configuration A reapplied;
capture stack reinstalled, session service now 1.30.49). **Pass 4 (Sonnet, 22:15–22:57, `acceptance/PASS-4-sonnet.md`):
NOT CLEAN**: F1 = **QA-020** (a second tab's stale review told to wait instead of to review again: `confirm()` consulted
the busy guard, held through the executor's follow-up `discovery.refresh()`, before the consent checks), F2 = a wrong
charter criterion (a request without `Origin` is accepted by design, OBS-003). **Release 1.30.50** fixes QA-020 (consent
checks before the guard, unit test `test_a_stale_restart_review_hears_the_stale_reason_while_the_previous_job_still_refreshes`;
the two-tabs tool keeps its record on a stuck control and waits for the tab's idle before reopening a menu, TOOL-004,
OBS-004): markers moved, the three history sections written, `verify-release.py` green, Python 1704 OK (1 skipped) on the
rerun, browser 379, `check_links.py` clean, the manager rebuilt at 1.30.50 (23:17 UTC, helpers 1.30.50; capture stack left
at its 1.30.49 build, unchanged code), the QA-020 live retest done (two-tabs 13/13 at 23:45). Committed as `1e12f37` + hygiene `9aa25c3`; **PR #58 merged
by the maintainer at 00:11 UTC**. **Pass 5 (Sonnet, 23:48–00:14): CLEAN.** **Pass 6 (Opus, 00:22–00:35): NOT CLEAN** on one
tooling finding (TOOL-005: the two-tabs tool crashed without a record while the maintainer's own `Quick-Test` lab was being
destroyed on the manager; every product check passed); tool revised (one guard around every step, idle wait first), retested
13/13, committed with passes 5 and 6 as `02fd181` (**PR #59**, CI green). **Pass 7 (Sonnet, 01:09–01:33): CLEAN.** **Pass 8
(Opus, 01:36–01:52): NOT CLEAN** on **QA-021** (P0: a *Remove design* dialog opened in one lab acted on it after the browser's
Back to another lab with the same design revision). The fix (`closeLabDialogs()` on a lab change; the two dialogs act only
for the lab they were opened from, with its revision at open time; two browser tests; the reviewer's script 12/12 on a
fixture of the fix) was built on 2026-09-28 as 1.30.51 and deployed on the dev VM, but never committed: the UI/UX changes 2
stream took over the worktree the same day and shipped 1.30.52–1.30.57 from it, leaving this work as a local WIP commit on
this branch. On 2026-10-02 that commit was pushed, `main` (1.30.57) merged into the branch (markers from main, no code
change) and the fix cut as **release 1.30.58** (**PR #62**); its validation record says what was run then (static, unit and
browser suites only). **Next**: deploy 1.30.58 on the dev VM, then **pass 9 (Sonnet)** and **pass 10 (Opus)** on it
(`acceptance/PASS-9-*.md`, `PASS-10-*.md`), then the evidence commit with `FINAL-REPORT.md` completed.

Then: add the final3 neighbour rerun records to `DEFECTS.md` (QA-018, Live) and `EVIDENCE.md` in the evidence commit; `python3 deploy/verify-release.py`;
commit the intended files only (never `git add -A`: `.claude/`, the three prompt files in the worktree root and any
`failure.png`/`student-workflow.json` tool droppings stay out; `docs/netlab-ui-qa/` goes in), push with the `ArchRuger`
gh account (`gh auth switch --user ArchRuger`, push, `gh auth switch --user pruger-dev`), open a pull request to
`main` (PR #55 covered only 1.30.43; 1.30.44–1.30.48 have none), watch CI. Then the two independent clean acceptance
passes on the final build (fresh Sonnet and Opus agents, `docs/netlab-ui-qa/tools/` plus the live lab; never rebuild the
manager container while one runs) and the final report (`docs/netlab-ui-qa/FINAL-REPORT.md`: "Implemented:
individual-device restart", UI paths, versions and commands tested, per-image results, limits, "Intentionally removed
functionality: None", every BLOCKED/NOT RUN named).

Open findings to carry: TOOL-001 (three UI-review tools fail on HEAD too), OBS-001/OBS-002 (recorded, not changed),
U-13 (partial). Known image facts: `RESTART_KNOWN_LIMITS` (vJunos-switch, XRv9k) and the neighbour-down behaviour
(`restart_links`) in `lab_operations.py`, all proven live on 2026-09-27.
