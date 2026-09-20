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
| 4 | Code cleanup (T3): dead CSS, two dead handlers, unused imports, stale wording printed by deploy scripts and `vm-connection.html`, eight test files added to CI | complete when this commit is on the remote |
| 5 | Final verification: an independent verifier over chunks 2 to 4, a risk reviewer over the CSS removal; fixes; final state of the record | not started |

The state column is filled in by the commit that completes a chunk; a chunk is complete only when its
commit is on the remote branch.

## Unfinished work

Written at the end of each session. If the working tree is not clean when you arrive, `git status` and
`git stash list` show what was left; nothing here is complete unless a pushed commit says so.
