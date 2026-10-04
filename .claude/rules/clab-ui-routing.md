# Task routing: the roster and how a feature is staffed

The policy is `fable-opus-routing.md`. This file is the roster of `.claude/agents/` and the order in
which a feature uses it. Invoke a definition by its exact name.

| Agent | Model | Writes | Use it for |
|---|---|---|---|
| `clab-fable-designer` | Fable 5.1 | yes | Design documents, interaction specifications, state machines, wording, reference implementations |
| `clab-fable-specialist` | Fable 5.1 | yes | The hardest build and debugging slices, cross-system problems |
| `clab-opus-specialist` | Opus 5.5 | yes | Difficult debugging, complex implementation, adversarial verification |
| `clab-network-specialist` | Opus 5.5 | yes | NOS transactions, timed rollback, configuration ownership, netlab |
| `risk-reviewer` | Opus 5.5 | no | Privileged helpers, trusted paths, owner-scoped Git, restore, persistence, concurrency, deletions |
| `clab-ui-reviewer` | Opus 5.5 | no | Design decisions, transactions and rollback as the person sees them, lost functionality |
| `clab-backend-engineer` | Sonnet 5.5 | yes | FastAPI services, state, jobs and their tests |
| `clab-ui-builder` | Sonnet 5.5 | yes | Vanilla JavaScript UI slices and their tests |
| `clab-test-engineer` | Sonnet 5.5 | yes | Unit, failure-path, integration and property-based tests |
| `clab-editor-specialist` | Sonnet 5.5 | yes | The embedded React/TypeScript adapter and its committed bundle |
| `clab-devops-engineer` | Sonnet 5.5 | yes | VM setup, Docker and containerlab, installer, labs, capture validation |
| `clab-ui-qa` | Sonnet 5.5 | yes | Browser and fixture workflows, live-device checks when assigned |
| `docs-auditor` | Sonnet 5.5 | yes | One documentation domain against the code |
| `clab-ui-scout` | Haiku 4.5 | no | Bounded file, symbol, selector, test and message inventory |
| `mechanical-editor` | Haiku 4.5 | yes | An already-decided rename, wording or formatting edit |

## Staffing a feature

1. **Design round (Fable).** The lead, with `clab-fable-designer` workers in parallel, writes the
   design: data and state models, interaction, wording, and the list of every refusal or dead end with
   its new outcome. Scouts gather the inventory it needs.
2. **Design review (Opus).** `risk-reviewer` attacks every change to a privileged helper, trusted path,
   transaction or stored state before code is written; `clab-ui-reviewer` attacks the interaction and
   the lost-functionality map. Their findings are answered in the design document, not waved through.
3. **Build (parallel).** Slices with disjoint files and a written API contract between them. Hard
   slices go to `clab-fable-specialist`, `clab-opus-specialist` or `clab-network-specialist`, routine
   ones to the Sonnet implementers, decided edits to `mechanical-editor`.
4. **Verification (independent).** `clab-ui-qa` workers run the fixture pass per viewport in parallel;
   an Opus specialist who did not write the code runs the adverse pass; the lead runs or assigns the
   live pass and checks every result it reports.

For UI work the binding contract is `docs/redesign/DESIGN-SPEC-ADDENDUM.md`: plain scripts, no
framework, no build step, no CDN, no inline styles on `/`, and every capability the old UI offered
keeps a counterpart. Reuse targeted evidence instead of sending every worker the full history.
