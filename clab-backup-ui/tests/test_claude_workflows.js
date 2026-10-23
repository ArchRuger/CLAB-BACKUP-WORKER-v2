'use strict';
// The project workflows under .claude/workflows/ are plain JavaScript with top-level await that the Workflow tool
// runs; nothing else parses them before a run. This file parses each one the way the runtime does (a meta literal
// first, then an async body), checks the meta block the runtime and the `/` menu depend on, and checks that every
// agentType names an agent that exists, so a renamed agent cannot silently turn a review step into a general one.
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');

const ROOT = path.resolve(__dirname, '..', '..');
const WORKFLOWS = path.join(ROOT, '.claude', 'workflows');
const AGENTS = path.join(ROOT, '.claude', 'agents');
const BUILT_IN_AGENTS = new Set(['general-purpose', 'Explore', 'Plan']);
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
const RUNTIME_GLOBALS = ['agent', 'parallel', 'pipeline', 'phase', 'log', 'args', 'budget', 'workflow'];

function agentNames() {
  const names = new Set();
  for (const file of fs.readdirSync(AGENTS)) {
    if (!file.endsWith('.md')) continue;
    const match = /^name:\s*(.+?)\s*$/m.exec(fs.readFileSync(path.join(AGENTS, file), 'utf8'));
    if (match) names.add(match[1]);
  }
  return names;
}

function splitScript(text) {
  assert.ok(text.startsWith('export const meta = {'), 'the first statement must be `export const meta = {`');
  const end = text.indexOf('\n}\n');
  assert.notStrictEqual(end, -1, 'the meta literal must end with a `}` on its own line');
  const metaSource = text.slice('export const meta = '.length, end + 2);
  // eslint-disable-next-line no-new-func
  const meta = new Function(`'use strict'; return (${metaSource});`)();
  return { meta, body: text.slice(end + 3) };
}

const files = fs.readdirSync(WORKFLOWS).filter((file) => file.endsWith('.js')).sort();

test('the workflows directory holds the three staffing workflows', () => {
  assert.deepStrictEqual(files, ['clab-design-review.js', 'clab-review-changes.js', 'clab-slice-verify.js']);
});

for (const file of files) {
  const text = fs.readFileSync(path.join(WORKFLOWS, file), 'utf8');

  test(`${file}: meta is a literal with name, description, whenToUse and phases`, () => {
    const { meta } = splitScript(text);
    assert.strictEqual(meta.name, path.basename(file, '.js'), 'meta.name must equal the file name');
    assert.ok(meta.description && meta.description.length > 20);
    assert.ok(meta.whenToUse && meta.whenToUse.includes('args'), 'whenToUse must say what args the workflow takes');
    assert.ok(Array.isArray(meta.phases) && meta.phases.length >= 2);
    for (const phase of meta.phases) assert.ok(phase.title && phase.detail, 'each phase needs title and detail');
  });

  test(`${file}: the body parses as an async function with the runtime globals`, () => {
    const { body } = splitScript(text);
    assert.doesNotThrow(() => new AsyncFunction(...RUNTIME_GLOBALS, body));
  });

  test(`${file}: every phase() title is declared in meta.phases and vice versa`, () => {
    const { meta, body } = splitScript(text);
    const declared = new Set(meta.phases.map((phase) => phase.title));
    const called = new Set();
    for (const match of body.matchAll(/\bphase\('([^']+)'\)/g)) called.add(match[1]);
    for (const match of body.matchAll(/phase:\s*'([^']+)'/g)) called.add(match[1]);
    assert.deepStrictEqual([...called].sort(), [...declared].sort());
  });

  test(`${file}: every agentType names a project agent or a built-in one`, () => {
    const known = agentNames();
    const used = [...text.matchAll(/agentType:\s*'([^']+)'/g)].map((match) => match[1]);
    assert.ok(used.length > 0, 'a staffing workflow must route to named agents');
    for (const name of used) assert.ok(known.has(name) || BUILT_IN_AGENTS.has(name), `unknown agentType ${name}`);
  });

  test(`${file}: no wall-clock or randomness (they break resume)`, () => {
    assert.ok(!/Date\.now\(|Math\.random\(|new Date\(\)/.test(text));
  });

  test(`${file}: results of parallel() and pipeline() are filtered for null agents`, () => {
    assert.ok(/\.filter\(Boolean\)/.test(text), 'a stopped or failed agent resolves to null; filter it');
  });
}
