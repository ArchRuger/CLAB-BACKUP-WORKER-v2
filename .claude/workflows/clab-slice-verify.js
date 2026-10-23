export const meta = {
  name: 'clab-slice-verify',
  description: 'Independent verification of a built slice by workers that did not write it: run its tests exactly, attack it against its acceptance checks, and run the browser fixture pass per viewport when it touches the UI',
  whenToUse: 'Step 4 of staffing a feature (.claude/rules/clab-ui-routing.md): a worker reports a slice done and the lead has not integrated it yet. args: { slice: "name", paths: ["changed/paths"], tests: ["exact command", ...], acceptance: ["check", ...], ui: false, viewports: [1440, 1280, 760, 390], flows: "what the QA worker must exercise", base_port: 8800 }. Without tests the test run is reported as not run.',
  phases: [
    { title: 'Run tests', detail: 'every listed command exactly, with exit codes' },
    { title: 'Attack', detail: 'an Opus specialist who did not write the slice tries to break it against the acceptance checks' },
    { title: 'Fixture', detail: 'clab-ui-qa per viewport on its own port and FIXTURE_DATA, only when ui' },
    { title: 'Report', detail: 'one verdict with blockers and evidence' },
  ],
}

const REPO = 'the repository at your current working directory (its root holds CLAUDE.md)'
const slice = (args && args.slice) || 'unnamed slice'
const paths = (args && args.paths) || []
const tests = (args && args.tests) || []
const acceptance = (args && args.acceptance) || []
const ui = Boolean(args && args.ui)
const viewports = (args && args.viewports) || [1440, 1280, 760, 390]
const flows = (args && args.flows) || 'the flows the changed files implement'
const basePort = (args && args.base_port) || 8800
if (!paths.length || !acceptance.length) throw new Error('args.paths and args.acceptance are required')
if (!tests.length) log('no test commands given: the test run is skipped and reported as not run')

const RUNS = {
  type: 'object',
  properties: {
    runs: { type: 'array', items: { type: 'object', properties: { command: { type: 'string' }, cwd: { type: 'string' }, exit_code: { type: 'integer' }, summary: { type: 'string' } }, required: ['command', 'cwd', 'exit_code', 'summary'] } },
    all_passed: { type: 'boolean' },
  },
  required: ['runs', 'all_passed'],
}
const ATTACK = {
  type: 'object',
  properties: {
    checks: { type: 'array', items: { type: 'object', properties: { acceptance: { type: 'string' }, held: { type: 'boolean' }, how_checked: { type: 'string' }, evidence: { type: 'string' } }, required: ['acceptance', 'held', 'how_checked', 'evidence'] } },
    breaks: { type: 'array', items: { type: 'object', properties: { title: { type: 'string' }, severity: { type: 'string' }, steps: { type: 'string' }, evidence: { type: 'string' } }, required: ['title', 'severity', 'steps', 'evidence'] } },
    verdict: { type: 'string' },
  },
  required: ['checks', 'breaks', 'verdict'],
}
const QA = {
  type: 'object',
  properties: {
    viewport: { type: 'integer' },
    port: { type: 'integer' },
    fixture_data: { type: 'string' },
    passed: { type: 'boolean' },
    findings: { type: 'array', items: { type: 'object', properties: { title: { type: 'string' }, severity: { type: 'string' }, expected: { type: 'string' }, actual: { type: 'string' }, evidence: { type: 'string' } }, required: ['title', 'severity', 'expected', 'actual', 'evidence'] } },
    console_errors: { type: 'integer' },
    failed_requests: { type: 'integer' },
  },
  required: ['viewport', 'port', 'fixture_data', 'passed', 'findings', 'console_errors', 'failed_requests'],
}

const common = `Slice "${slice}" in ${REPO}; changed paths (relative to the repository root): ${paths.join(', ')}. You did not write this slice and you must not repair it: report. Edit no tracked file. Never point a Store or a test at live data (/srv/containerlab-node-manager/data).`

const jobs = [
  () => tests.length === 0 ? Promise.resolve(null) : agent(`${common}\nRun each of these commands exactly as written (from clab-backup-ui unless the command says otherwise; keep PATH="$PWD/.venv/bin:$PATH" for the Python suites) and report the exit code and a one-line summary of each. Do not add, change or skip a command.\n${tests.map((t, i) => `${i + 1}. ${t}`).join('\n')}`,
    { agentType: 'clab-test-engineer', label: 'run-tests', phase: 'Run tests', schema: RUNS }),
  () => agent(`${common}\nAcceptance checks the slice claims:\n${acceptance.map((a, i) => `${i + 1}. ${a}`).join('\n')}\nFor each check: decide how to verify it (read the code, write a throwaway test in a temporary directory, run the app on a scratch FIXTURE_DATA, or state that it needs a VM or device and could not be checked here), do it, and report held/not held with evidence. Then try to break the slice: wrong input, double clicks, interrupted jobs, restart, a missing file, concurrency with operation_busy, an old stored state shape. Report each break with steps.`,
    { agentType: 'clab-opus-specialist', label: 'attack', phase: 'Attack', schema: ATTACK }),
]
if (ui) {
  viewports.forEach((width, index) => jobs.push(() =>
    agent(`${common}\nBrowser fixture pass at viewport width ${width}. Use port ${basePort + index} and a fresh FIXTURE_DATA directory you create with mktemp -d (name it in the report); start the fixture with docs/redesign/tools/fixture_manager.py as docs/redesign/PICKUP.md section 2 describes, exercise: ${flows}. Follow the clab-browser-qa skill: wait on UI conditions, capture console errors and failed requests, keyboard-only where the flow allows, scrub secrets. Stop your own fixture when done.`,
      { agentType: 'clab-ui-qa', label: `fixture:${width}`, phase: 'Fixture', schema: QA })))
}

const results = (await parallel(jobs))
const runs = results[0]
const attack = results[1]
const fixture = ui ? results.slice(2).filter(Boolean) : []
log(`tests ${runs ? (runs.all_passed ? 'passed' : 'FAILED') : 'not run'}; attack ${attack ? attack.breaks.length + ' breaks' : 'not run'}; fixture ${fixture.length}/${ui ? viewports.length : 0} viewports`)

phase('Report')
const report = await agent(`Write the verification record for slice "${slice}" (repository: ${REPO}). Separate evidence by kind as the repository's VALIDATION.md does: unit and static, fixture and browser, not run. State plainly what was not verified and why. End with one line: integrate | fix first | blocked, and the blockers. Return Markdown only; edit no file.\nTEST RUNS: ${JSON.stringify(runs)}\nATTACK: ${JSON.stringify(attack)}\nFIXTURE: ${JSON.stringify(fixture)}`,
  { label: 'report', phase: 'Report', model: 'claude-opus-5-5' })

return { runs, attack, fixture, report }
