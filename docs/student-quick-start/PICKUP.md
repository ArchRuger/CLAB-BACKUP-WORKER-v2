# Student quick start: pickup file

An illustrated PDF quick-start guide for a first-time student, produced by executing two workflows on the
development VM: Scenario A (use an instructor's lab) and Scenario B (build a lab and keep it and its saved
configurations in Git). Read this file first; keep it current before a compaction or a handoff.

## Deliverables (this directory)

| Path | What |
|---|---|
| `Containerlab_Node_Manager_Student_Quick_Start.pdf` | The student guide (built, inspected page by page). |
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

## Exact next action

Scenario A capture is running (`tools/capture_scenario_a.py`). When it lands: reconcile `source/guide.md` with
`evidence/scenario-a.md`, then execute Scenario B the same way, then compose screenshots, build, inspect, QA replay,
Opus review, release records (+0.0.1 per chunk with `deploy/set-release.py`), commit, push, PR.
