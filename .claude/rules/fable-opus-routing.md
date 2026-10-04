# Routing policy: models, roles and parallelism

This is the routing policy for a Claude Code session in this repository and for its subagents. It
decides who does what; the application's functional, security and evidence requirements in `CLAUDE.md`
are unchanged by it. A session is its own lead. `clab-ui-routing.md` holds the roster and how a feature
is staffed. The cross-VM protocol in `00-clab-two-worker-routing.md` applies only while the owner has
declared a second VM active.

## Models

- **Fable 5.1 (`claude-fable-5-1`) leads and designs.** The lead does product and interaction design,
  architecture, data and state models, integration, and any implementation it judges hardest. It may
  run Fable workers: `clab-fable-designer` for design and architecture slices (design documents,
  interaction specifications, state machines, wording, reference implementations of the hardest pieces)
  and `clab-fable-specialist` for build and debugging work where the difficulty calls for it. A Fable
  worker is never a nested lead.
- **Opus 5.5 (`claude-opus-5-5`) reviews and specializes.** `risk-reviewer` (read-only: anything
  touching `host_*.py`, the gateway, trusted paths, owner-scoped Git, restore, persistence or
  concurrency; deletions; instruction migrations), `clab-ui-reviewer` (read-only: design decisions,
  transactions, rollback, lost functionality), `clab-opus-specialist` (difficult debugging, complex
  implementation, adversarial verification) and `clab-network-specialist` (NOS transactions, timed
  rollback, configuration ownership, netlab). No failed cheaper attempt is needed before using Opus.
- **Sonnet 5.5 (`claude-sonnet-5-5`)** does routine implementation, tests, documentation, QA runs and
  VM operations: `clab-ui-builder`, `clab-backend-engineer`, `clab-test-engineer`,
  `clab-editor-specialist`, `clab-devops-engineer`, `clab-ui-qa`, `docs-auditor`.
- **Haiku 4.5 (`claude-haiku-4-5-20251001`)** does bounded inventory and decided mechanical edits:
  `clab-ui-scout`, `mechanical-editor`. It is never the final judge of a NOS transaction, security,
  state loss or integration correctness.

Scripts and searches come before any model. Do not send trivial edits to a premium model out of habit,
and do not hold back Fable or Opus where their judgement changes the result. A model change never
removes a role's tool restrictions: the two reviewers and the scout stay read-only.

Use the named project agents, so a task's route does not depend on the session's model. The
definitions carry exact model IDs. `.claude/settings.json` keeps Sonnet as the default for unnamed
subagents (`CLAUDE_CODE_SUBAGENT_MODEL`), forced overriding off (`CLAUDE_CODE_SUBAGENT_MODEL_FORCE=0`)
and no model allowlist; an allowlist added later must contain all four IDs. The lead may override a
definition's model for a task-specific reason and says so in the delegation. Verify the model a worker
actually ran on from task or transcript metadata, never from its self-description, and report any
substitution. Do not work around a user or managed setting that restricts models.

## Parallelism

- Run as many workers at once as there is independent work and the machine can carry; there is no
  fixed number. Measure before scaling (`free -g`, `nproc`) and keep headroom.
- One owner per file at a time. Give each worker its own files or its own Git worktree made from an
  explicit base commit; never switch the checkout beneath active editors. A worker delegates only what
  its own slice needs.
- Each browser or fixture worker gets its own port and its own fresh `FIXTURE_DATA`.
- Several disposable labs may run at once. Measure memory before starting one, because the
  VM-in-container nodes are heavy. A live lab has one operator at a time, assigned by the lead.
- The Workflow tool and agent teams may be used where the installed Claude Code offers them: check what
  they do on this installation first. Agent teams are off in `.claude/settings.json`
  (`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS`), and a change there takes effect only in a new session.

## Delegating

Before each delegation state task, agent, model, scope and acceptance check. Give a worker the exact
question, its writable paths, the invariants that apply, the API contract it builds against and the
acceptance checks, not the whole history. Hard slices go to Fable or an Opus specialist, routine ones
to Sonnet, inventory to Haiku. Escalate at once on high consequence; otherwise escalate when the first
concrete attempt shows missing understanding, instead of repeating guesses.

## Standing rules

- The lead integrates and owns shared files, release markers, the explicit CI test lists, commits on
  the task branch, pushes and pickup notes. A worker commits only inside a worktree the lead gave it.
- An implementer is never the only verifier of its own work: a design is attacked by an Opus reviewer
  before code is written, and a slice is checked by a worker that did not write it.
- Tests use disposable fixtures. Never point a test or a `Store` at live data.
- Never claim a VM, browser or live-device validation that did not happen in this session.
- No force-push, destructive reset, stash cleanup, branch-protection bypass, tag or image publishing
  unless the owner asks. A disposable VM does not make GitHub disposable.

## Skills

Every project skill (`.claude/skills/clab-*`) and every external skill installed on the VM is in use.
An agent definition preloads the one or two its role always needs and names the ones to load on demand.

| Skill | Used by |
|---|---|
| `clab-repo-contracts` | every design, review, documentation and scouting role; the lead before any change |
| `clab-backend` | `clab-backend-engineer`, `clab-test-engineer`; Fable and Opus workers on backend slices |
| `clab-manager-ui` | `clab-ui-builder`, `clab-ui-reviewer`, `clab-fable-designer` |
| `clab-browser-qa` | `clab-ui-qa`, `clab-ui-reviewer`, `clab-test-engineer` for browser harnesses |
| `clab-editor-build` | `clab-editor-specialist` |
| `clab-network-transactions`, `clab-netlab` | `clab-network-specialist`, `risk-reviewer` |
| `clab-host-ops`, `clab-capture` | `clab-devops-engineer`; `risk-reviewer` for the helper boundary |
| `clab-release` | the lead, at the release step |
| `clab-parallel-handoff` | both leads, only while two VMs are active |
| `test-driven-development`, `systematic-debugging`, `verification-before-completion` | implementers, test and QA workers, specialists |
| `writing-plans`, `requesting-code-review`, `receiving-code-review` | the lead and the designers; a review request goes to the project's reviewers |
| `frontend-design`, `web-design-guidelines` | `clab-fable-designer`, `clab-ui-builder`, `clab-ui-reviewer` |
| `webapp-testing` | `clab-ui-qa` |
| `vercel-react-best-practices` | `clab-editor-specialist`, for the embedded adapter only |

The external skills are installed per VM from the setup kit's lockfile and are not part of the
repository; a worker without one says so and continues. A skill is a task aid, not an orchestrator:
this policy wins over an imported skill's default model, framework, commit or merge policy and over
its demand for a new approval cycle. A planning or testing skill never deletes production code
because its generic example starts from scratch.

## Development authority, unchanged product boundaries

On the owner's disposable development VM, workers may install and repair packages, use passwordless
sudo, build and replace development images, refresh helpers with the project's setup scripts, restart
services, deploy and destroy their own labs, inject failures and clean identified unused artifacts,
without asking again. This authorizes neither production systems nor the removal of the product's own
access controls. Preserve every existing feature and test claim. Telemetry and Grafana stay retired.
The student guide is edited only when the owner reopens that scope.

## Evidence and completion

Every assignment ends with changed paths, the actual model route, tests and exit codes, scrubbed
evidence, unresolved gaps and the next step. Record static, unit, fixture, real-engine, live-NOS, VM
and CI validation separately. New test files reach the explicit CI lists through the lead. Before a
usage or context stop, make a durable branch checkpoint and a pickup note instead of leaving work only
in agent memory.
