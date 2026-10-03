#!/usr/bin/env python3
"""Pass 8 mutation checks: undo a fix in a scratch copy of clab-backup-ui (never the worktree), run the fix's named
regression test against the copy, and require it to FAIL; then restore the file and require the same test to PASS
again (so a failure is the mutation's, not the copy's). Also exercises the TOOL-002 assertions of
check_restart_device.py with synthetic inputs, evaluating the tool's own expression text.
Usage: mutation_checks.py <scratch dir made with mktemp -d> <out json>"""
import json, re, shutil, subprocess, sys, os
from datetime import datetime, timezone
from pathlib import Path
W = Path('/home/clabllm/projects/clab-manager-1.30.42'); SRC = W / 'clab-backup-ui'
S = Path(sys.argv[1]) / 'clab-backup-ui'; OUT = Path(sys.argv[2])
def now(): return datetime.now(timezone.utc).isoformat(timespec='seconds')
if not S.exists():
    shutil.copytree(SRC, S, ignore=shutil.ignore_patterns('.venv', 'node_modules', '__pycache__', 'lab-builder'))
ENV = dict(os.environ, PATH=str(SRC / '.venv/bin') + ':' + os.environ['PATH'], PYTHONDONTWRITEBYTECODE='1')
# No bytecode cache: a mutant of the same size written in the same second would otherwise be served from a stale .pyc
# to the restored run (seen in this pass's first run: QA-016's restored test failed).
def clean():
    for d in S.rglob('__pycache__'): shutil.rmtree(d, ignore_errors=True)
PY = str(SRC / '.venv/bin/python')
def run_py(pattern, name):
    clean()
    p = subprocess.run([PY, '-m', 'unittest', 'discover', '-s', 'tests', '-t', 'tests', '-p', pattern, '-k', name], cwd=S, env=ENV, capture_output=True, text=True, timeout=600)
    tail = (p.stderr or p.stdout).strip().splitlines()
    ran = next((l for l in tail if l.startswith('Ran ')), '')
    return p.returncode, ran, tail[-1] if tail else ''
def run_js(file, pattern):
    p = subprocess.run(['node', '--test', '--test-name-pattern=' + pattern, 'tests/' + file], cwd=S, capture_output=True, text=True, timeout=300)
    out = p.stdout.splitlines()
    return p.returncode, next((l for l in out if l.startswith('# pass')), '') + ' ' + next((l for l in out if l.startswith('# fail')), ''), ''
M = [
 ('QA-020', 'app/lab_operations.py',
  "                if preview['lab_id'] and not self.store.lab(preview['lab_id']): raise HTTPException(409, 'Saved lab was removed. Preview again.')\n",
  "                if preview['lab_id'] and not self.store.lab(preview['lab_id']): raise HTTPException(409, 'Saved lab was removed. Preview again.')\n                self.guard(preview['lab_id'])   # MUTANT: the busy guard before the stale checks (pre-QA-020 order)\n",
  ('py', 'test_lab_operations.py', 'test_a_stale_restart_review_hears_the_stale_reason_while_the_previous_job_still_refreshes')),
 ('QA-019a', 'app/node_readiness.py', 'LOGIN_GRACE = 900', 'LOGIN_GRACE = 0',
  ('py', 'test_node_readiness.py', 'test_a_refused_login_right_after_a_manager_restart_reads_booting_until_the_grace_window_closes')),
 ('QA-019b', 'app/lab_operations.py', '            for key in lab_keys: self.readiness.forget(key)\n', '            pass   # MUTANT: lab-wide jobs forget no device\n',
  ('py', 'test_lab_operations.py', 'test_a_lab_wide_lifecycle_job_drops_every_device_login_proof_for_the_grace_window')),
 ('QA-017', 'app/lab_operations.py', "    'cisco_xrv9k': 'Known limit of the XRv9k image", "    'cisco_xrv9k_mutant': 'Known limit of the XRv9k image",
  ('py', 'test_lab_operations.py', 'test_the_xrv9k_review_names_the_fresh_disk_limit_and_other_kinds_get_no_note')),
 ('QA-018', 'app/lab_operations.py', "        if peer is not None and state and state not in ('running', 'unknown'):", "        if False:   # MUTANT",
  ('py', 'test_lab_operations.py', 'test_a_neighbour_that_is_not_running_is_named_in_the_review_and_the_job_counts_the_links')),
 ('QA-014', 'app/lab_operations.py', "        if state in ('', 'running'): return ''", "        return ''   # MUTANT",
  ('py', 'test_lab_operations.py', 'test_a_restart_whose_container_exits_right_after_is_a_failed_job_with_the_reason')),
 ('RD-001', 'app/lab_operations.py', "                    raise HTTPException(409, 'Another lab operation ran while this review was being prepared. Review the restart again.')",
  "                    pass   # MUTANT",
  ('py', 'test_lab_operations.py', 'test_a_restart_device_review_is_stale_when_a_lifecycle_job_lands_during_its_own_helper_calls')),
 ('RD-003', 'app/host_operations.py', "    if container != node and container != lab + '-' + node and not container.endswith('-' + lab + '-' + node):",
  "    if not container.endswith(node):   # MUTANT: bare suffix match",
  ('py', 'test_lab_operations.py', 'test_restart_device_binds_every_container_naming_shape_exactly')),
 ('QA-016', 'app/design_intent.py', "NAME = re.compile(r'^[A-Za-z_][A-Za-z0-9_]{0,15}$')", "NAME = re.compile(r'^[A-Za-z_][A-Za-z0-9_]{0,63}$')",
  ('py', 'test_design_intent.py', 'test_engine_identifiers_follow_netlabs_16_character_rule')),
 ('QA-015', 'app/static/network-design.js', "if(designState.labId!==labId||seq<=designViewApplied)return false;", "if(designState.labId!==labId)return false;",
  ('js', 'test_network_design_ui.js', 'QA-015: two overlapping loads')),
]
rows = []
for ident, rel, old, new, (kind, file, name) in M:
    f = S / rel; text = f.read_text()
    row = {'id': ident, 'file': rel, 'test': file + ' :: ' + name, 'at': now()}
    if text.count(old) != 1:
        row.update(result='NOT RUN', reason='anchor found %d times' % text.count(old)); rows.append(row); print(ident, 'NOT RUN anchor', text.count(old)); continue
    f.write_text(text.replace(old, new))
    try: rc, ran, last = run_py(file, name) if kind == 'py' else run_js(file, name)
    finally: f.write_text(text)
    rc2, ran2, last2 = run_py(file, name) if kind == 'py' else run_js(file, name)
    killed = rc != 0 and rc2 == 0 and ('Ran 0 tests' not in ran)
    row.update(mutant_exit=rc, mutant_summary=(ran + ' ' + last).strip(), restored_exit=rc2, restored_summary=(ran2 + ' ' + last2).strip(), result='KILLED' if killed else 'SURVIVED')
    rows.append(row); print(ident, row['result'], '| mutant:', row['mutant_summary'], '| restored:', row['restored_summary'], flush=True)
# TOOL-002: evaluate the tool's own expression text with synthetic inputs.
tool = (W / 'docs/netlab-ui-qa/tools/check_restart_device.py').read_text()
fail_expr = re.search(r"r\.check\('no false credentials failure between Starting and Ready', (.+), json\.dumps\(seen\)\)", tool).group(1)
argv_expr1 = re.search(r"\n    ok = (status == 200 and argv\.count.+)\n", tool).group(1)
argv_expr2 = re.search(r"\n    ok = (ok and len\(argv\).+)\n", tool).group(1)
def falsecheck(words): return eval(fail_expr, {}, {'words': words})
def argvcheck(argv, short='xrv9k', status=200):
    ok = eval(argv_expr1, {}, {'status': status, 'argv': argv, 'short': short}); return eval(argv_expr2, {}, {'ok': ok, 'argv': argv})
T = [('booting→ready passes', falsecheck(['booting', 'ready']), True),
     ('booting→failed→booting→ready fails (QA-019 timeline)', falsecheck(['booting', 'failed', 'booting', 'ready']), False),
     ('restarting→booting→ready passes', falsecheck(['restarting', 'booting', 'ready']), True),
     ('an unknown word (reachable) fails', falsecheck(['booting', 'reachable', 'ready']), False),
     ('exact argv passes', argvcheck(['containerlab', 'restart', '-t', 'x.clab.yml', '--node', 'xrv9k']), True),
     ('two --node fails', argvcheck(['containerlab', 'restart', '-t', 'x', '--node', 'xrv9k', '--node', 'ceos']), False),
     ('--node followed by another device fails', argvcheck(['containerlab', 'restart', '-t', 'x', '--node', 'ceos']), False),
     ('no --node (lab-wide restart) fails', argvcheck(['containerlab', 'restart', '-t', 'x']), False),
     ('a deploy argv fails', argvcheck(['containerlab', 'deploy', '-t', 'x', '--node', 'xrv9k']), False),
     ('preview status 409 fails', argvcheck(['containerlab', 'restart', '-t', 'x', '--node', 'xrv9k'], status=409), False)]
tool_rows = [{'case': c, 'got': g, 'expected': e, 'ok': g == e} for c, g, e in T]
for t in tool_rows: print('TOOL-002', 'ok  ' if t['ok'] else 'FAIL', t['case'])
json.dump({'at': now(), 'scratch': str(S), 'mutations': rows, 'tool_002': {'expressions': [fail_expr, argv_expr1, argv_expr2], 'cases': tool_rows}}, open(OUT, 'w'), indent=1)
open(OUT, 'a').write('\n')
print('mutants killed %d of %d; TOOL-002 cases %d of %d as expected' % (sum(r['result'] == 'KILLED' for r in rows), len(rows), sum(t['ok'] for t in tool_rows), len(tool_rows)))
