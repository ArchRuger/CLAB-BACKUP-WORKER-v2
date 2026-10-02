---
name: user-pr-workflow
description: "How work is delivered for this repo (claude/ branch + PR, user merges) and the two gh accounts on the host"
metadata:
  type: feedback
---

The user wants every piece of work delivered as a `claude/...` branch pushed to `ArchRuger/CLAB-BACKUP-WORKER-v2` with a pull request they merge themselves; no GitHub login of their own is needed on their side. `gh` on this host holds two accounts: `ArchRuger` (owns the manager source) and `pruger-dev` (owns the lab-save repository `CLAB-MNGR-DEV-LLM`, used by the Git helper through the credential helper; the ACTIVE account as of 2026-09-18). Both tokens carry `repo` and `workflow`.

**Why:** they said "Your work against the project will just be opened as a PR, I will merge it" and "push it and open the PR".

**How to apply:** commit with `git -c user.name='clabllm' -c user.email='samcolt519@gmail.com'`; `gh auth switch -u ArchRuger` before pushing manager source, push the branch, `gh pr create` against `main`, end PR bodies with the Claude Code attribution line, then `gh auth switch -u pruger-dev` so lab saves keep pushing. If a push touching `.github/workflows/*` is rejected, check `gh auth status` scopes. Related: [[dev2-host-environment]].
