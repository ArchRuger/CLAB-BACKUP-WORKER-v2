# Task routing: the roster, the staffing order and the workflows

The policy is `fable-opus-routing.md`. This file is the roster of `.claude/agents/`, the order in
which a feature uses it, and the workflows that run that order. Invoke a definition by its exact name.
Every definition preloads `clab-worker-contract`; the Writes column follows from its `tools`.

| Agent | Model | Writes | Use it for |
|---|---|---|---|
| `clab-fable-designer` | Fable 5.1 | yes | Design documents, interaction specifications, state machines, wording, reference implementations |
| `clab-fable-specialist` | Fable 5.1 | yes | The hardest build and debugging slices, cross-system problems |
| `clab-opus-specialist` | Opus 5.5 | yes | Adversarial verification of another worker's slice, difficult non-NOS debugging and implementation |
| `clab-network-specialist` | Opus 5.5 | yes | NOS transactions, timed rollback, configuration ownership, netlab |
| `risk-reviewer` | Opus 5.5 | no | Privileged helpers, trusted paths, owner-scoped Git, restore, persistence, concurrency, deletions |
| `clab-ui-reviewer` | Opus 5.5 | no | Design decisions, transactions and rollback as the person sees them, lost functionality |
| `clab-backend-engineer` | Sonnet 5.5 | yes | FastAPI services, state, jobs and their tests |
| `clab-ui-builder` | Sonnet 5.5 | yes | Vanilla JavaScript UI slices and their tests |
| `clab-test-engineer` | Sonnet 5.5 | yes | Unit, failure-path, integration and property-based tests; running an exact list of test commands |
| `clab-editor-specialist` | Sonnet 5.5 | yes | The embedded React/TypeScript adapter and its committed bundle |
| `clab-devops-engineer` | Sonnet 5.5 | yes | VM setup, Docker and containerlab, installer, labs, capture validation |
| `clab-ui-qa` | Sonnet 5.5 | yes | Browser and fixture workflows, live-device checks when assigned |
| `docs-auditor` | Sonnet 5.5 | yes | One documentation domain against the code |
| `clab-ui-scout` | Haiku 5.5 | no | Bounded file, symbol, selector, test and message inventory |
| `mechanical-editor` | Haiku 5.5 | yes | An already-decided rename, wording or formatting edit |

## Staffing a feature

1. **Design round (Fable).** The lead, with `clab-fable-designer` workers in parallel, writes the
   design: data and state models, interaction, wording, and the list of every refusal or dead end with
   its new outcome. Scouts gather the inventory it needs. The design lives under the stream's
   `docs/<stream>/` folder.
2. **Design review (Opus).** `/clab-design-review` with the design's paths (and `nos: true` when it
   touches a NOS transaction) has `risk-reviewer` and `clab-ui-reviewer` attack it, verifies every
   finding with two refuters and returns the table the design must answer. The answers go into the
   design document (the form is `docs/git-redesign/REVIEW.md`), not into a reply.
3. **Build (parallel).** Slices with disjoint files and a written API contract between them. The
   path-scoped rules name the builder for each area: hard slices go to `clab-fable-specialist`,
   `clab-opus-specialist` or `clab-network-specialist`, routine ones to the Sonnet implementers,
   decided edits to `mechanical-editor`. One owner per file; a worktree per worker where files overlap.
4. **Verification (independent).** `/clab-slice-verify` per slice runs its tests exactly, has an Opus
   specialist who did not write it attack the acceptance checks, and runs `clab-ui-qa` per viewport
   when it touches the UI. `/clab-review-changes` reviews the branch diff with every reviewer the diff
   needs before the lead integrates or opens a pull request. The lead runs or assigns the live pass and
   checks every result it reports.

## The path-scoped routing rules

Each loads only when a file it names is read or edited, for the lead and for every subagent:

| Rule | Covers | Builder | Reviewer |
|---|---|---|---|
| `routing-privileged-paths.md` | `host_*.py`, the gateway, `deploy/setup-*.sh`, the Store, the guard, the capture service | the lead, `clab-fable-specialist`, `clab-opus-specialist` | `risk-reviewer` |
| `routing-nos.md` | restore and design-apply drivers, node services, the runner | `clab-network-specialist` | `risk-reviewer`, `clab-network-specialist` |
| `routing-manager-ui.md` | `app/static/*.js`, pages, stylesheets, the browser tests | `clab-ui-builder`, designs by `clab-fable-designer` | `clab-ui-reviewer`, QA by `clab-ui-qa` |
| `routing-editor.md` | `lab-builder/`, the committed bundle, the two editor pages | `clab-editor-specialist` | `clab-ui-reviewer` |
| `routing-tests-ci.md` | `clab-backup-ui/tests/`, the CI workflow | `clab-test-engineer`, `clab-ui-qa` | the lead (CI lists) |
| `routing-release-records.md` | `VERSION`, the three history files | the lead only | `verify-release.py` |
| `routing-claude-config.md` | `.claude/`, `CLAUDE.md` | the lead | `risk-reviewer` for hooks and permissions |

For UI work the binding contract is `docs/redesign/DESIGN-SPEC-ADDENDUM.md`: plain scripts, no
framework, no build step, no CDN, no inline styles on `/`, and every capability the old UI offered
keeps a counterpart. Reuse targeted evidence instead of sending every worker the full history.
