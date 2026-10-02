---
name: vm-rollback-preservation
description: "Before the 2026-10-02 VM snapshot rollback, everything VM-only was pushed to branch claude/vm-local-preservation (routing agents, rules, settings, memory, prompts, research reports, scripts); restore recipe in vm-local/README.md there"
metadata:
  node_type: memory
  type: project
  originSessionId: 52d7420b-89c4-432a-99b8-a280852eb41a
  modified: 2026-10-02T23:44:10.508Z
---

On 2026-10-02 the maintainer rolled clab-llm-dev2 back to a VM snapshot. Before that, every file that
lived only on the VM and mattered to development was committed on the branch
`claude/vm-local-preservation` of ArchRuger/CLAB-BACKUP-WORKER-v2 (not for merging):

- At their repo paths: the untracked `.claude/agents/clab-*.md` (scout, builder, qa, reviewer,
  opus-specialist), `.claude/rules/{clab-ui-routing,fable-opus-routing}.md`, the modified
  `.claude/settings.json` and `risk-reviewer.md` (model pins), the three netlab/restart prompt files.
- Under `vm-local/`: the Claude memory of all three projects, the user-level `~/.claude/settings.json`,
  `~/setup_claude_ui_routing.py`, the two agent connection guides, the research reports (lab builder
  feasibility, netlab RECON-*), `~/validation-tools`, the README screenshot scripts, the dev lab topology.
- The netlab stream's set-aside WIP commit was pushed on `claude/netlab-integration` (one commit ahead of
  the merged PR #59; `git reset --soft HEAD~1` restores it as uncommitted work).

**Why:** the snapshot predates some of these; without the branch the routing setup and the memory
index would have been lost.

**How to apply:** after a rollback, follow `vm-local/README.md` on that branch to put the files back,
then re-login `gh` (ArchRuger and pruger-dev) and Claude Code. Not restored from Git: `.env` files,
`~/.clab-discovery-password`, `/srv/containerlab-node-manager/data` (the installer regenerates them),
raw device transcripts and screenshots. See [[dev2-host-environment]] and [[user-pr-workflow]].
