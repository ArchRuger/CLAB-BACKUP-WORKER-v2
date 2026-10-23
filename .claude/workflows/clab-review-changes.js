export const meta = {
  name: 'clab-review-changes',
  description: 'Review the branch diff with the project reviewers (invariants, correctness, UI contract, NOS, tests and CI lists), adversarially verify every finding, and return the confirmed list',
  whenToUse: 'Before the lead integrates a slice or opens a pull request. args: { base: "main", context: "what the change is for" }. base defaults to main; the diff is base...HEAD plus uncommitted changes.',
  phases: [
    { title: 'Scope', detail: 'list the changed files and which areas they touch' },
    { title: 'Review', detail: 'one project reviewer per touched area' },
    { title: 'Verify', detail: 'two refuters per finding' },
  ],
}

const REPO = 'the repository at your current working directory (its root holds CLAUDE.md)'
const base = (args && args.base) || 'main'
const context = (args && args.context) || '(no context given)'

const SCOPE = {
  type: 'object',
  properties: {
    files: { type: 'array', items: { type: 'string' } },
    summary: { type: 'string' },
    touches_privileged: { type: 'boolean', description: 'host_*.py, deploy/clab-manager-gateway, deploy/setup-*.sh, store.py, restore*.py, capture_service.py, main.py guard or allowed_hosts' },
    touches_ui: { type: 'boolean', description: 'clab-backup-ui/app/static/** or any .html' },
    touches_nos: { type: 'boolean', description: 'restore_*.py drivers, design_apply/design_<nos>.py, restore_shell.py, node_services.py' },
    touches_editor: { type: 'boolean', description: 'clab-backup-ui/lab-builder/** or app/static/lab-builder/**' },
    touches_tests: { type: 'boolean', description: 'clab-backup-ui/tests/** or .github/workflows/**' },
    touches_claude_config: { type: 'boolean', description: '.claude/** or CLAUDE.md' },
    patch_path: { type: 'string', description: 'absolute path of the patch file you wrote (committed diff followed by the uncommitted diff)' },
  },
  required: ['files', 'summary', 'touches_privileged', 'touches_ui', 'touches_nos', 'touches_editor', 'touches_tests', 'touches_claude_config', 'patch_path'],
}
const FINDINGS = {
  type: 'object',
  properties: {
    findings: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          title: { type: 'string' },
          severity: { type: 'string', description: 'must-fix | should-fix | optional' },
          file: { type: 'string' },
          line: { type: 'integer' },
          claim: { type: 'string' },
          failure_scenario: { type: 'string', description: 'concrete input or state, then the wrong outcome' },
          smallest_fix: { type: 'string' },
        },
        required: ['title', 'severity', 'file', 'claim', 'failure_scenario', 'smallest_fix'],
      },
    },
    verdict: { type: 'string' },
  },
  required: ['findings', 'verdict'],
}
const VERDICT = { type: 'object', properties: { refuted: { type: 'boolean' }, reason: { type: 'string' } }, required: ['refuted', 'reason'] }

phase('Scope')
const scope = await agent(`In ${REPO} run \`git diff --stat ${base}...HEAD\` and \`git status --short\`, then \`git diff ${base}...HEAD --name-only\` and list every changed or untracked path (read-only: run no other git command that changes anything). Write the full patch for the reviewers, who cannot run git themselves: \`git diff ${base}...HEAD\` followed by \`git diff\` (uncommitted changes) and, for each untracked text file, \`git diff --no-index /dev/null <file>\`, into one file created with \`mktemp /tmp/clab-review-XXXXXX.patch\`; report its absolute path as patch_path. Classify which areas the change touches per the schema descriptions. Summarise the change in three sentences. Context from the lead: ${context}`,
  { label: 'scope', phase: 'Scope', schema: SCOPE, model: 'claude-sonnet-5-5' })
if (!scope || !scope.files.length) return { confirmed: [], refuted: [], note: 'no changed files' }
log(`${scope.files.length} changed files: ${scope.summary}`)

const diffHint = `The change is the patch at ${scope.patch_path} (read it in full with the Read tool; it holds \`git diff ${base}...HEAD\` plus the uncommitted changes) in ${REPO}. Changed files: ${scope.files.join(', ')}. Context: ${context}. Review what changed, not the whole project; open the current files for context. Report only findings with file and line evidence and a concrete failure scenario; "none found" is a valid answer. Do not edit any file and run nothing that changes state.`
const reviewers = [
  { key: 'invariants', agentType: 'risk-reviewer', prompt: `${diffHint}\nLens: CLAUDE.md "Invariants that must not regress": privilege, trusted paths, owner-scoped Git, restore, persistence, concurrency, deletions (hunt for the consumer the author missed), public_* views leaking a private field, instruction migrations.` },
  { key: 'correctness', agentType: 'clab-opus-specialist', prompt: `${diffHint}\nLens: correctness and regression. Read every changed function and its callers and tests; look for broken behavioural claims, state the old code handled and the new code does not, error paths, concurrency with the Store lock and operation_busy, and tests weakened to pass.` },
]
if (scope.touches_ui || scope.touches_editor) reviewers.push({ key: 'ui', agentType: 'clab-ui-reviewer', prompt: `${diffHint}\nLens: the binding UI contract (docs/redesign/DESIGN-SPEC-ADDENDUM.md), lost functionality against docs/redesign/inventory and parity, shared globals across app/static/*.js, esc() on every interpolation, no inline styles on /, the ?v= marker on new scripts, keyboard, focus, loading, empty, error and disabled states.` })
if (scope.touches_nos) reviewers.push({ key: 'nos', agentType: 'clab-network-specialist', prompt: `${diffHint}\nLens: NOS transactions only, review without running anything against a device: timed recovery armed, confirmation over the right session, read-back before an outcome is reported, uncertain outcomes stay uncertain, ownership and conflict rules.` })
if (scope.touches_tests || scope.files.some(f => f.endsWith('.py') || f.endsWith('.js'))) reviewers.push({ key: 'tests', agentType: 'clab-test-engineer', prompt: `${diffHint}\nLens: test coverage and the explicit CI lists in .github/workflows/release-check.yml. Every new test file must appear there; every changed behaviour needs a failing-then-passing test; a pinned label is rewritten, never deleted; the stdlib-only group stays stdlib-only. Do not write or edit tests in this run: report.` })
if (scope.touches_claude_config) reviewers.push({ key: 'config', agentType: 'clab-opus-specialist', prompt: `${diffHint}\nLens: the Claude Code configuration under .claude/ and CLAUDE.md: frontmatter fields that the docs do not define, agents named in rules or CLAUDE.md that do not exist, skills preloaded that do not exist, the roster table out of step with the files, a read-only agent given a write tool, hooks that could block the project's own scripts. Run \`python3 -m unittest discover -s tests -p test_claude_config.py\` from clab-backup-ui and report its result.` })

phase('Review')
const reviews = (await parallel(reviewers.map(r => () =>
  agent(r.prompt, { agentType: r.agentType, label: `review:${r.key}`, phase: 'Review', schema: FINDINGS })
    .then(result => (result && Array.isArray(result.findings)) ? { reviewer: r.key, ...result } : null)
))).filter(Boolean)
const findings = reviews.flatMap(r => r.findings.map(f => ({ reviewer: r.reviewer, ...f })))
log(`${findings.length} findings from ${reviews.length} reviewers`)

phase('Verify')
const lenses = [
  'correctness: read the cited file and line in the current working tree. Refute if the code does not do what the claim says, or the scenario cannot occur.',
  'reproduction: try to reproduce the failure scenario with a focused test or a direct run that changes no committed file and no live system (a temporary directory, a scratch Store, python -c). Refute if you cannot make it fail.',
]
const verified = await pipeline(findings,
  f => parallel(lenses.map((lens, i) => () =>
    agent(`Finding (from ${f.reviewer}): "${f.title}" at ${f.file}${f.line ? ':' + f.line : ''}. ${f.claim}\nFailure scenario: ${f.failure_scenario}\nRepository: ${REPO}. Lens, ${lens}\nDefault to refuted=true when you cannot confirm it. Do not edit any tracked file and never point a Store at live data.`,
      { label: `verify:${i}:${f.title.slice(0, 40)}`, phase: 'Verify', schema: VERDICT, model: 'claude-opus-5-5' })))
    .then(votes => { const valid = votes.filter(Boolean); return { ...f, votes: valid, unverified: valid.length === 0, refuted: valid.length > 0 && valid.every(v => v.refuted) } }))
const kept = verified.filter(Boolean)
const order = { 'must-fix': 0, 'should-fix': 1, optional: 2 }
const bySeverity = (a, b) => (order[a.severity] ?? 3) - (order[b.severity] ?? 3)
const confirmed = kept.filter(f => !f.refuted && !f.unverified).sort(bySeverity)
const refuted = kept.filter(f => f.refuted)
const unverified = kept.filter(f => f.unverified).sort(bySeverity)
log(`${confirmed.length} confirmed, ${refuted.length} refuted, ${unverified.length} unverified (no verifier answered: treat as open)`)
return { scope, confirmed, refuted, unverified }
