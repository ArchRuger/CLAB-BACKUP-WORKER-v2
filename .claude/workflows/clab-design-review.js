export const meta = {
  name: 'clab-design-review',
  description: 'Attack a design document with the project reviewers before any code is written, verify every finding, and return the table the design must answer',
  whenToUse: 'Step 2 of staffing a feature (.claude/rules/clab-ui-routing.md): a design document exists and no build slice has started. args: { paths: ["docs/<stream>/DESIGN.md", ...], nos: false, context: "one paragraph: what the design changes and why" }. Set nos: true when the design touches a NOS transaction, restore, design apply or netlab.',
  phases: [
    { title: 'Attack', detail: 'risk-reviewer and clab-ui-reviewer, plus clab-network-specialist when nos, each read the design and the code it must fit' },
    { title: 'Verify', detail: 'two refuters per finding, one for truth and one for materiality' },
    { title: 'Answer', detail: 'the findings table the design must answer, with a proposed answer for each' },
  ],
}

const REPO = 'the repository at your current working directory (its root holds CLAUDE.md)'
const paths = (args && Array.isArray(args.paths) && args.paths.length) ? args.paths : null
if (!paths) throw new Error('args.paths must list the design document(s), relative to the repository root')
const context = (args && args.context) || '(no context given; read the design and its README)'

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
          claim: { type: 'string', description: 'what is wrong or missing, in one or two sentences' },
          evidence: { type: 'string', description: 'file:line or section references in the design and the code' },
          smallest_fix: { type: 'string' },
        },
        required: ['title', 'severity', 'claim', 'evidence', 'smallest_fix'],
      },
    },
    verdict: { type: 'string', description: 'one line' },
  },
  required: ['findings', 'verdict'],
}
const VERDICT = {
  type: 'object',
  properties: { refuted: { type: 'boolean' }, reason: { type: 'string' } },
  required: ['refuted', 'reason'],
}

const brief = (lens) => `Design review, lens: ${lens}. Repository: ${REPO}. Read these design documents in full (paths relative to the repository root): ${paths.join(', ')}.
Context from the lead: ${context}
Read the code the design must fit before judging it (follow the design's own file references, CLAUDE.md "Invariants that must not regress", and the routing table's handoff sections for the area). Try to prove the design wrong: a refusal or dead end it leaves, a state it cannot reach or recover, an invariant it weakens, a capability the old behaviour had that the design drops, a wording a student would misread. Report only findings with evidence; "none found" is a valid answer for a category. Do not edit any file.`

const reviewers = [
  { key: 'risk', agentType: 'risk-reviewer', lens: 'privilege, trusted paths, owner-scoped Git, restore and transactions, persistence and concurrency, deletions, instruction migrations' },
  { key: 'ui', agentType: 'clab-ui-reviewer', lens: 'the interaction as the person sees it, transactions and rollback in the UI, lost functionality against docs/redesign inventories and parity records, wording, keyboard and error states' },
]
if (args && args.nos) {
  reviewers.push({ key: 'nos', agentType: 'clab-network-specialist', lens: 'NOS transactions: timed recovery, confirmation over the right session, read-back, ownership and conflict rules, uncertain outcomes. Review only; do not edit or run anything against a device.' })
}

phase('Attack')
const attacks = (await parallel(reviewers.map(r => () =>
  agent(brief(r.lens), { agentType: r.agentType, label: `attack:${r.key}`, phase: 'Attack', schema: FINDINGS })
    .then(result => (result && Array.isArray(result.findings)) ? { reviewer: r.key, ...result } : null)
))).filter(Boolean)
const findings = attacks.flatMap(a => a.findings.map(f => ({ reviewer: a.reviewer, ...f })))
log(`${findings.length} findings from ${attacks.length} reviewers`)

phase('Verify')
const lenses = [
  'truth: is the claim actually true of the design text and the code as they stand today? Read them. Refute if the design or code already handles it or the cited evidence does not say what the claim says.',
  'materiality: assuming the claim is true, would it change what gets built or protect an invariant in CLAUDE.md? Refute if it is a style preference or a restatement of something the design already decides.',
]
const verified = await pipeline(findings,
  f => parallel(lenses.map((lens, i) => () =>
    agent(`Finding to verify (from ${f.reviewer}): "${f.title}" — ${f.claim}\nEvidence given: ${f.evidence}\nDesign documents: ${paths.join(', ')} in ${REPO}.\nLens, ${lens}\nDefault to refuted=true when you cannot confirm it from the files. Do not edit any file.`,
      { label: `verify:${i}:${f.title.slice(0, 40)}`, phase: 'Verify', schema: VERDICT, model: 'claude-opus-5-5' })))
    .then(votes => { const valid = votes.filter(Boolean); return { ...f, votes: valid, unverified: valid.length === 0, refuted: valid.some(v => v.refuted) } }))
const kept = verified.filter(Boolean)
const confirmed = kept.filter(f => !f.refuted && !f.unverified)
const refuted = kept.filter(f => f.refuted)
const unverified = kept.filter(f => f.unverified)
log(`${confirmed.length} findings stand, ${refuted.length} refuted (a finding falls when either lens refutes it), ${unverified.length} unverified`)

phase('Answer')
const table = await agent(`You write the review record the design must answer (the project keeps it next to the design, see docs/git-redesign/REVIEW.md for the form). Repository ${REPO}; design documents ${paths.join(', ')}.
For each confirmed finding below write one row: finding, reviewer, severity, evidence, the smallest change that answers it, and a proposed answer (accept, accept with change, reject with reason). Then list the refuted findings in one line each with why they were refuted. Do not edit any file; return Markdown only.
CONFIRMED: ${JSON.stringify(confirmed)}
REFUTED: ${JSON.stringify(refuted)}
UNVERIFIED (no verifier answered; list them as open): ${JSON.stringify(unverified)}`, { label: 'answer-table', phase: 'Answer', model: 'claude-opus-5-5' })

return { confirmed, refuted, unverified, table }
