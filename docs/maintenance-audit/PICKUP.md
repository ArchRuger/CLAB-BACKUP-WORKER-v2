# Maintenance audit: pickup file

Read this, then `git log --oneline origin/claude/maintenance-audit` and `gh pr list`: Git and GitHub are
the authority for what is committed, pushed and merged; this file is not. The findings and decisions are
in [AUDIT.md](AUDIT.md).

## How the work is delivered

- Branch `claude/maintenance-audit`, cut from `main` `d510b7a`. The maintainer merged chunks 1 to 3 as pull request #44 on 2026-09-20
  (`main` `a9c6015`); the branch was fast-forwarded to that merge and the work continues on it, to be offered
  as a second pull request. Remote `origin`. Push with the `ArchRuger`
  gh account (`gh auth switch -u ArchRuger`), then switch back to `pruger-dev` so lab saves keep working.
  Never force-push, tag, publish an image, deploy or merge.
- One chunk = one bounded change → checks → `python3 deploy/set-release.py` to the next patch number →
  the three history sections, this file and the record → `python3 deploy/verify-release.py` and the
  remaining gates → one commit → push → verify the remote SHA → look at CI → next chunk.
- Gates for every chunk: both test suites from `clab-backup-ui/`, the release check,
  `python3 docs/maintenance-audit/tools/check_links.py`, `git diff --check`. A chunk that changes the
  manager UI also runs `docs/redesign/tools/verify_after.py` against the fixture manager on fresh
  `FIXTURE_DATA`.
- Workers cannot be routed to a cheaper model while `~/.claude/settings.json` forces one subagent model
  (see the record, §2). Check that first on resumption; if it changed, use the brief's routes.

## Chunks

| Chunk | Content | State |
|---|---|---|
| 1 | Agent guidance: `CLAUDE.md` without the handoff import, invariant digest and routing table (reviewed by R1), architecture module map, pickup status lines, archive links, documentation index, link checker, this folder | pushed, `569a58a` |
| 2 | Installation and operations guides (T1): eleven files | pushed, `e2bb15b` |
| 3 | Student workflow guides (T2): seven files, plus the three stale tour screenshots regenerated from the fixture manager | pushed, `3bbc8d0` |
| 4 | Code cleanup (T3): dead CSS, two dead handlers, unused imports, stale wording printed by deploy scripts and `vm-connection.html`, eight test files added to CI | pushed, `a59378a`; reviewed independently before the commit |
| 5 | The telemetry `.env` key table, three project agent definitions with their models and the "Delegating work" section of `CLAUDE.md`, fixes from the independent verification of chunks 2 and 3, final state of the record | complete when this commit is on the remote |

The state column is filled in by the commit that completes a chunk; a chunk is complete only when its
commit is on the remote branch.

## Follow-ups (chosen by the maintainer after the pass)

Pull request #45 (chunks 4 and 5) was merged on 2026-09-20 (`main` `fc6da24`); the branch was fast-forwarded
again. The maintainer chose six of the record's open items, in this order:

| Follow-up | Content | State |
|---|---|---|
| 1 | Scaffold tool and the mandatory review; image compose line and parity test; prepared-image stack instructions; `deploy/image.env` ignored | pushed, `1807eee` |
| 2 | `shell.js` `lastOpened()` and the `clab.lastLab` write removed, the test's claim rewritten | pushed, `08eac01` |
| 3 | Pure deletions in `host_git.py`, `restore.py`, `restore_junos.py` after a risk review (`pending_rollback_shell` and `COMMIT_ERROR` stay until the maintainer decides whether to wire the probe) | pushed, `2dd62a5`; risk-reviewed before the commit |
| 4 | Manager-side `unchanged` save status (`finish()` in `git_progress.py`), risk-reviewed; the careful part is a HEAD that was never uploaded | complete when this commit is on the remote; risk-reviewed before the commit |

## Next

All six follow-ups the maintainer chose are done. Still open in the record's §5: whether
`recreate-manager.sh` should handle a prepared-image installation (or that route be retired), whether an
interrupted restore should probe the node (`pending_rollback_shell`), the garbled arrow in the audit log,
the folder change that fails half-way, `CAPTURE_BIND` / `CAPTURE_PORT`, the vJunos-switch statement, the
Wiki guide's map section, and the fixture helper that never answers `unchanged`. A pull request for the
follow-ups is to be opened or merged by the maintainer.

## Unfinished work

Written at the end of each session. If the working tree is not clean when you arrive, `git status` and
`git stash list` show what was left; nothing here is complete unless a pushed commit says so.
