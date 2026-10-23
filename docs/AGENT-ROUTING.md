# Agent routing: the Claude Code configuration in this repository

How coding-agent sessions on this repository are organised, what ships in `.claude/` so that every
clone has the same agents, skills, workflows and guardrails, and how a development VM is set up from
the repository alone. The policy itself is in `.claude/rules/`; this page is the guide for a person.

## What ships in `.claude/`

| Path | What it is | Loaded when |
|---|---|---|
| `CLAUDE.md` (root) | The project instructions: state of `main`, commands, architecture, invariants, the routing table into the handoff notes | every session and every subagent |
| `.claude/rules/fable-opus-routing.md` | The routing policy: which model does what, how the harness resolves a route, parallelism, delegation, standing rules, the skills table | every session |
| `.claude/rules/clab-ui-routing.md` | The roster of the fifteen agents, the staffing order of a feature and the three workflows that run it | every session |
| `.claude/rules/00-clab-two-worker-routing.md` | The two-VM protocol, active only on a checkout that declares a worker | every session (short) |
| `.claude/rules/routing-*.md` | Seven path-scoped rules naming the builder, the reviewer and the tests of an area | only when a file they name is read or edited |
| `.claude/agents/*.md` | The fifteen agent definitions, each with its exact model, effort, tools and preloaded skills | when the lead delegates to one |
| `.claude/skills/clab-*/` | Thirteen project skills: the repository contracts, one per area, the worker contract, the release step, the two-VM handoff, the routing smoke | preloaded by the agents that need them, or on demand |
| `.claude/skills/<other>/` | Ten vendored third-party skills with their licences; `.claude/THIRD-PARTY-SKILLS.md` and `.claude/external-skills.lock.json` record source, commit and hash | on demand |
| `.claude/workflows/*.js` | `clab-design-review`, `clab-review-changes`, `clab-slice-verify`: the review and verification steps as dynamic workflows over the named agents | `/<name>` |
| `.claude/hooks/guard-bash.py` | The Bash guard: refuses the commands the rules forbid outright | before every Bash command, in every permission mode |
| `.claude/settings.json` | Shared settings: model pins, subagent defaults, nesting depth, plugins, the deny on the live `state.key`, the hook, the worktree base | every session |

Personal and machine files stay out of Git (`.gitignore`): `.claude/settings.local.json`,
`.claude/worker.local.json`, `.claude/worktrees/`, `.claude/agent-memory-local/`.

## The models and the roles

Fable 5.1 leads a session and designs; it may run Fable workers for design slices and the hardest
build work. Opus 5.5 reviews (two read-only reviewers) and specializes (adversarial verification,
NOS transactions). Sonnet 5.5 implements, tests, documents, runs QA and operates the VM. Haiku 5.5
scouts and applies decided edits, with a turn cap. The roster with each agent's purpose is the table in
`.claude/rules/clab-ui-routing.md`; the exact model IDs are the `ANTHROPIC_DEFAULT_*_MODEL` values in
`.claude/settings.json`, and every agent file names its model, so a route does not depend on the
model the session runs on.

Each delegation is checked, not trusted: `/tasks` names the model and effort a subagent runs on; for a
workflow agent the per-agent transcript (`agent-<id>.jsonl` under the session's `subagents/` directory)
records it. An agent saying its own model is not evidence.
`/clab-routing-smoke` is the deliberate check before a campaign (four small paid delegations).

## How a feature is staffed

1. **Design** by the lead and `clab-fable-designer`, under the stream's `docs/<stream>/` folder.
2. **Design review**: `/clab-design-review` with the design's paths has `risk-reviewer` and
   `clab-ui-reviewer` (and `clab-network-specialist` with `nos: true`) attack it, verifies each finding
   with two refuters and returns the table the design must answer.
3. **Build** in slices with disjoint files; the path-scoped rule of each area names the builder.
4. **Verification** by workers who did not write the slice: `/clab-slice-verify` runs the slice's
   tests exactly, attacks its acceptance checks and runs the browser fixture per viewport;
   `/clab-review-changes` reviews the branch diff with every reviewer the diff needs before the lead
   integrates or opens a pull request.

A workflow takes its input as `args` (`whenToUse` in each script's `meta` says what); run one by typing
its name, for example `/clab-review-changes` with `base: main` and a sentence of context.

## The guard hook

`.claude/hooks/guard-bash.py` runs before every Bash command of the session and of every subagent,
whatever the permission mode. It refuses, with the reason shown to the agent:

- a force push in any spelling (`--force`, `-f`, `--force-with-lease`, a `+` refspec, `--mirror`,
  `--prune`, abbreviated long options), a remote branch deletion, a tag push (also by the tag's short
  name), a tag creation in the checkout;
- a destructive reset, a forced `git clean`, a dropped stash or a whole-tree discard (`checkout -- .`,
  `restore .`, `checkout -f`) inside the checkout; a scratch clone elsewhere is not affected;
- `docker push` in its forms (`image push`, `compose push`, `build --push`), a blanket
  `docker system prune`, a volume prune, `docker image prune -a`, `docker compose down -v`, a GitHub
  release, `gh pr merge --admin`;
- deleting or moving the manager's directory `/srv/containerlab-node-manager` or anything in it (by an
  absolute, relative or glob path), and `state.key` or `state.enc` outside a scratch location.

It reads the command text, splits on operators and newlines, ignores heredoc bodies and redirections,
looks through `sudo -u`, `env`, `timeout`, `nice`, `xargs`, the shells' `-c` and `eval`, and follows `cd`
between subcommands. It is a guardrail, not a security boundary: a program reached another way is
not caught, and the product's own protections and GitHub's branch protection remain the real limits.
When the owner wants one of these commands run, the owner runs it in a shell of their own, outside the
Bash tool, which is the only thing the hook sees. The test suite
pins the hook's decisions (`test_claude_config.py`). `/hooks` lists the registration;
`claude --debug` shows a hook that failed to run.

## Setting up a development VM from the repository

The repository is the source of truth; no setup kit is needed and the one that first generated this
configuration must not be run against a checkout again (it would replace these files with its older
copies).

1. Install Claude Code 2.1.296 or later (`claude --version`): the agent frontmatter diagnostics,
   `claude plugin validate` for an agents directory and Haiku 5.5 need it. Install Git, Python 3,
   Node 24 or later, the GitHub CLI, Docker and containerlab as `docs/INSTALL.md` describes for the
   manager itself.
2. Clone the repository and start `claude` in the checkout. Accept the workspace trust dialog: in an
   interactive session, hooks from `.claude/settings.json` run only after it; a `claude -p` run treats the
   folder as trusted and runs them at once.
3. Plugins: `.claude/settings.json` enables `pyright-lsp`, `typescript-lsp` and `pr-review-toolkit`
   from the official marketplace. If `/plugin` does not know that marketplace yet, add it once
   (`/plugin marketplace add anthropics/claude-plugins-official`), then install the three. The two
   language servers need their binaries on `PATH` (`pyright`, `typescript-language-server`); the
   plugin alone does not provide them.
4. Personal settings belong in `~/.claude/settings.json`, never in the repository: the permission mode
   (the owner runs a disposable VM in bypass mode; the shared deny rules and the hook still apply
   there), the sandbox, the saved effort levels, the theme. A VM that takes part in the two-VM protocol
   also gets `.claude/worker.local.json` and `CLAB_WORKER_ID` in `.claude/settings.local.json`; both
   are ignored by Git.
5. Verify: from the root `claude plugin validate .claude/agents --strict`; from `clab-backup-ui/`
   `python3 -m unittest discover -s tests -p test_claude_config.py -v` and
   `node --test tests/test_claude_workflows.js`; in a session `/doctor`, `/hooks`, `/skills` and, before
   a campaign, `/clab-routing-smoke`.

## Changing the configuration

- The roster exists in four views that must agree: the agent files, the table in
  `clab-ui-routing.md`, the skills table in `fable-opus-routing.md` and `CLAUDE.md` "Delegating work".
  `test_claude_config.py` checks them against each other, checks every frontmatter field against the
  documented set (the harness ignores an unknown field silently), the hook's decisions and the vendored
  skills' hashes; `test_claude_workflows.js` parses the workflows. Both run in CI.
- The read-only roles (`risk-reviewer`, `clab-ui-reviewer`, `clab-ui-scout`) are read-only through
  their `tools` allowlist. Never give them `memory` (it re-enables file writes), `Bash`, `Edit`,
  `Write` or `Agent`.
- After a change to an agent file, start a new session before trusting a route and confirm it in `/tasks`
  (the documentation promises a live pickup within seconds; a running session was seen to keep the old
  definitions). A changed workflow needs `/reload-skills`. A skill an agent preloads must not carry
  `paths`: such a skill is silently not preloadable.
- A vendored skill is never edited in place; `.claude/THIRD-PARTY-SKILLS.md` says how to refresh one
  and what licence each carries.
- A change to `.claude/settings.json`, to the hook or to a read-only agent's tools goes to
  `risk-reviewer` before it is merged; the path-scoped rule `routing-claude-config.md` says so when the
  file is opened.

## Fields in use and where they are documented

Agents: `name`, `description`, `model`, `effort`, `color`, `tools` or `disallowedTools`, `maxTurns`,
`memory`, `skills`. Skills: `name`, `description`, `when_to_use`, `paths`, `user-invocable`,
`disable-model-invocation`, `argument-hint`. Rules: `paths`. Settings: `model`, `env`,
`enabledPlugins`, `permissions.deny`, `hooks`, `worktree.baseRef`, `workflowSizeGuideline`. The
official references are the Claude Code documentation pages on subagents, skills, memory and rules,
hooks, settings and workflows (`https://code.claude.com/docs/en/sub-agents`, `/skills`, `/memory`,
`/hooks`, `/settings`, `/workflows`).
