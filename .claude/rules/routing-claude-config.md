---
paths:
  - ".claude/**"
  - "CLAUDE.md"
---

# Routing: the Claude Code configuration itself (this rule loaded because you touched it)

- **Owner.** The lead edits `.claude/` and `CLAUDE.md`; `risk-reviewer` reviews a change to
  `.claude/settings.json` (hooks, permissions, environment), to `.claude/hooks/` or to a read-only
  agent's tools. A worker proposes such a change in its hand-back.
- **Keep the views in step.** An agent appears in its file, in the roster of `clab-ui-routing.md`, in
  the skills table of `fable-opus-routing.md` and in `CLAUDE.md` "Delegating work". A skill an agent
  preloads exists under `.claude/skills/<name>/SKILL.md` and is not `disable-model-invocation`.
- **Only documented fields.** The harness ignores an unknown frontmatter field without a warning;
  `docs/AGENT-ROUTING.md` lists the fields in use and where the official reference is. The read-only
  roles never get `memory`, `Bash`, `Edit`, `Write` or `Agent` (memory would re-enable file writes).
- **Vendored skills are read-only.** `.claude/THIRD-PARTY-SKILLS.md` says how to refresh one; an edit
  in place fails the hash check.
- **Checks.** From `clab-backup-ui/`: `python3 -m unittest discover -s tests -p test_claude_config.py
  -v` and `node --test tests/test_claude_workflows.js`; from the root: `claude plugin validate
  .claude/agents --strict` (a parse check only). A changed workflow needs `/reload-skills`, which also
  reads a new `workflows` directory; after a change to an agent file start a new session before trusting
  a route, and confirm it in `/tasks`: a running session was seen to keep the old definitions. A skill an
  agent preloads must not carry `paths`.
