# Student quick start: pickup file

## Campaign 2, D10 (reopened 2026-10-27): done, waiting for the lead's commit

The guide, screenshots, tools and PDF were redone against release 1.31.6 (commit 973668e of `claude/parity-campaign`); see
the top section of `VALIDATION.md` for what was replayed, with timings, and what was not. The 2026-09 text further down is the
record of the first pass (the old Progress tab) and is history.

- **Repositories (private, owner ArchRuger, disposable; the VM's `gh` has no `delete_repo` scope, so the owner deletes them):**
  `https://github.com/ArchRuger/campaign2-netlab-course-student` (Scenario A, made from the public template
  `pruger-dev/netlab-course`) and `https://github.com/ArchRuger/campaign2-my-network-labs` (Scenario B, with a README). Their
  checkouts on the VM are `~/labs/campaign2-netlab-course-student` and `~/labs/campaign2-my-network-labs`; the manager
  registered both in the VM Git registry (not touched), and `/srv/containerlab-node-manager/projects/campaign2-my-network-labs/`
  is the clone Scenario B step B9 makes. `/srv/containerlab-node-manager/projects/link-basics/` holds the staged instructor
  package; `/srv/containerlab-node-manager/projects-aside-qs/` holds the old `my-first-lab` folders put aside by the reset tool.
- **State left on the VM:** `link-basics` is deployed, Running, in My labs (2 cEOS, loaded to the Running state of the last
  replay) and `my-first-lab` is rebuilt and running from the clone; the student repository holds `link-basics/work/`
  (latest, checkpoint `loopback-added`) and the B repository holds `my-first-lab/` (latest, checkpoint `link-up`).
  `bash tools/reset_scenario_a.sh` and `bash tools/reset_scenario_b.sh` return the manager and the repositories to the starting
  states (they remove the lab from My labs, destroy its containers, restore the staged package and remove the saved folder from
  the repository with one ordinary commit; they never touch the VM Git registry or other labs). They keep a waiting save out of
  the way with the page's own *Keep snapshot only* call. Destroy the two labs before another campaign needs the memory.
- **Names in the guide:** the text and the screenshots show `ArchRuger`, `campaign2-netlab-course-student`,
  `campaign2-my-network-labs` and the manager address `http://192.168.132.134:8081`, because they are what was captured. To make
  the guide for other names: replay with `QS_GH_ACCOUNT`, `QS_STUDENT_REPO`, `QS_B_REPO` set, then replace the names in
  `source/guide.md` (a search for `ArchRuger` and `campaign2-` finds them all).
- **Tooling:** `tools/qs_lib.py` (browser, API, waiting for the manager's guard), `tools/qs_ui.py` (the save chip, Save, Load
  helpers shared by both scenarios), `tools/capture_scenario_a.py` and `tools/capture_scenario_b.py` (`--steps N-M` resumes,
  state in `build/state-*.json`), `tools/compose_screenshots.py` with `screenshots/spec.json` (crops in raw pixels at device
  scale 2). Run them with `/home/archtop/pw-venv/bin/python` (Playwright and paramiko). The shared manager makes the page
  answer "Wait for the current lab operation to finish." while another worker's operation runs: the tools call
  `wait_idle()` first. Do not poll with `pgrep -f "<pattern>"` inside a wait loop that carries the pattern itself.
- **Stale records kept as history:** `evidence/qa/*` (the 2026-09 QA replay drivers) and `evidence/ui-index.md` describe the
  Progress tab and its selectors; do not reuse them for the current UI.
- **Open points for the lead:** (1) the course repository `pruger-dev/netlab-course` still holds schema 2 states (no topology,
  no map) and its README says "Apply to running lab…"; the guide works with it because Load lists them as Start, Solution and
  Broken-01, but the instructor may want to re-record them with *Save as a lab state…*; (2) after *Replace it* in step B9 the
  manager makes a save of the fresh devices at once, which the guide sets aside with *Not now*; (3) the guide's first save
  and the `link-basics/reference` folders live in different folders of one repository: a student sees them under Lab states only
  after the repository is up to date (it was, because the repository was connected after the template copy).

## Deliverables (this directory)

| Path | What |
|---|---|
| `Containerlab_Node_Manager_Student_Quick_Start.pdf` | The student guide (26 pages as of 2026-10-27; inspected page by page; replayed twice by an independent QA agent; SHA-256 in `VALIDATION.md`). |
| `source/guide.md`, `source/style.css`, `build.py`, `build.sh`, `BUILD.md` | Editable source and the one-command build (Markdown → HTML → WeasyPrint). |
| `screenshots/` (`raw/` captures, `spec.json` crops and callouts, composed PNGs) | Illustrations, all from the real manager and the exercised examples. |
| `examples/` | The instructor package (`link-basics`) and the personal lab (`my-first-lab`) with a nonsecret preparation README. |
| `tools/` | `capture_scenario_a.py` / `capture_scenario_b.py` (Playwright walkthroughs that made the screenshots and evidence), `reset_scenario_a.sh`, `eos.py`, `compose_screenshots.py`, `inspect_pdf.py`. |
| `evidence/` | `scenario-a.*`, `scenario-b.*` (step logs with quoted labels, timings, commit ids, remote trees), `ui-index.md` (label/selector index), QA replay reports. |
| `VALIDATION.md` | Step-by-step replay results, tested version, Git/device evidence, PDF inspection outcome and the PDF hash. |

## Environment (development VM `clab-llm-dev2`, 2026-09-22)

- Manager `http://192.168.132.132:8081` (`http://127.0.0.1:8081` for tools), Docker, containerlab 0.79, passwordless
  sudo, gh logged in as `pruger-dev` (active; `ArchRuger` for the manager source), Playwright in
  `clab-backup-ui/.venv` (`export LD_LIBRARY_PATH=$HOME/.local/lib/chromium-deps`), WeasyPrint 61.1 + poppler from apt.
- **What was changed on the VM to obtain a first-time student state (all reversible):** the manager data directory was
  copied to `/srv/containerlab-node-manager/data.pre-quickstart-2026-09-22` and the live manager reset with
  *Start fresh* (VM connection kept); the four-image lab `restore-square` was destroyed (its topology stays in
  `projects-archive-2026-09-22/restore-square`); the earlier lab folders were moved from the trusted root to
  `/srv/containerlab-node-manager/projects-archive-2026-09-22/`; the VM Git registry `/etc/clab-manager/git.json` was
  emptied (backups: `git.json.pre-quickstart-2026-09-22` with the 17 CLAB-MNGR-DEV-LLM registrations, `git.json.instructor-2026-09-22`
  with the instructor's netlab-course registrations). To go back: stop the manager, swap the data directory, restore
  `git.json`, move the folders back, redeploy `restore-square`.
- Repositories made for the guide (owner `pruger-dev`): `netlab-course` (public, template; the instructor's course
  repository with `link-basics/reference/{start,solution,broken-01}/latest`), `netlab-course-student` (private, the
  student's copy used in Scenario A), `my-network-labs` (private, Scenario B; created during the scenario).
- Instructor package staged at `/srv/containerlab-node-manager/projects/link-basics/` (copy of `examples/link-basics/`).

## Application changes made for this work (separate from the documentation)

- `clab-backup-ui/app/host_git.py` `ensure_identity()`: a GitHub account without a display name made *Connect a
  repository by URL* fail with "This VM account has no Git commit identity yet" (the tab-separated `gh api user` line
  ended with an empty field that `strip()` removed). Fixed with `rstrip('\r\n')`; regression test in
  `tests/test_host_git.py`; helper refreshed on the VM with `sudo bash deploy/setup-git.sh --refresh`.
- `deploy/verify-release.py` and `docs/REPOSITORY-MAINTENANCE.md`: `docs/student-quick-start/` is a history directory
  (its guide names the release it was tested with).
- `docs/NAMING.md`: the stale "Live restore is Junos only" sentence now names the three supported platforms.

## Routing (verified from transcript metadata)

Lead Fable 5.1 (`claude-fable-5-1`); `clab-ui-scout` → `claude-haiku-4-5-20251001` (UI index); `clab-ui-builder` →
`claude-sonnet-5` (Scenario A capture; PDF pipeline); `docs-auditor` → `claude-sonnet-5` (guide text);
`risk-reviewer` → opus (helper fix review). Settings: project `.claude/settings.json` (`CLAUDE_CODE_SUBAGENT_MODEL=sonnet`,
force off, agent teams off) overrides the user file; the routing files under `.claude/` stay uncommitted (user's choice).

## Log

- 2026-09-22 16:30–17:10 UTC: routing and build checked (main = `132122b`, 1.30.32, deployed 1.30.32, helpers 1.30.32);
  environment prepared as above; helper defect found and fixed while connecting the course repository; instructor states
  recorded with `deploy/scaffold-lab.py`; Scenario A capture, PDF pipeline and guide draft started in parallel.

- 2026-09-22 17:58 UTC: **checkpoint 1 = release 1.30.33, commit `cf7bc5d`, PR #51** (Scenario A executed and recorded,
  pipeline, guide draft with A reconciled, helper fix). Manager image rebuilt and running at 1.30.33 with `link-basics`
  Ready and connected. Scenario B capture started (`tools/capture_scenario_b.py`).

- 2026-09-22 18:45–19:40 UTC: Scenario B executed (`tools/capture_scenario_b.py`); B10 re-executed from the real clone
  after the first run deployed the original folder; guide reconciled for B; **checkpoint 2 = release 1.30.34**.

- 2026-09-22 19:40–20:40 UTC: Opus review applied (account convention, status texts, timings); layout trimmed to 20
  pages; QA replay 1 on the draft (21/21 PASS); manager rebuilt at 1.30.35; every page of the final build inspected;
  QA replay 2 on the delivered file (21/21 PASS, one reload hint added afterwards); **checkpoint 3 = release 1.30.35**.
  The VM was then reset to the guide's starting state for a demonstration (see below).

## State left on the VM for a demonstration

My labs empty, VM connected, VM Git registry empty, `link-basics` staged under `/srv/containerlab-node-manager/projects/`,
`pruger-dev/netlab-course-student` reset to the template content (its earlier `link-basics/work` saves removed with an
ordinary commit, history kept), `pruger-dev/my-network-labs` renamed to `my-network-labs-authoring` so that step B5 can
create `my-network-labs` afresh. The replay repositories `netlab-course-qa`, `netlab-course-qa2`, `my-network-labs-qa`,
`my-network-labs-qa2` stay as evidence. To demonstrate: open the manager and follow the PDF; to reset again:
`tools/reset_scenario_a.sh netlab-course-student` and `tools/reset_scenario_b.sh my-network-labs` (rename or delete a
`my-network-labs` that a demo created first).

## Exact next action

The stream is complete (PR #51 merged 1.30.33; PR #52 carries 1.30.34 and 1.30.35). If it is picked up again: a change to `source/guide.md`, `screenshots/spec.json` or
`source/style.css` needs `bash docs/student-quick-start/build.sh`, a look at `build/pages/`, and — when a step's action or
expected result changed — a replay of that step on the real manager (`evidence/qa/final_*.py` are the replay drivers;
the reset tools bring the VM back to the starting states). Then update `VALIDATION.md` with the new SHA-256.
