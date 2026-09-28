#!/usr/bin/env python3
"""Pass 6 mutation checks: undo one fix at a time in a scratch copy of clab-backup-ui (never the worktree), run the
fix's named regression test against the copy and record whether it FAILS (it must). Each mutation is first run
unmutated (the test must pass on the pristine copy), then mutated, then the file is restored before the next one.
Also exercises the TOOL-002 assertions of check_restart_device.py with synthetic inputs (no browser, no manager).
Usage: mutation_checks.py <scratch dir>   (prints a JSON ledger)"""
import json, os, shutil, subprocess, sys, datetime
ROOT = '/home/clabllm/projects/clab-manager-1.30.42'
SRC = ROOT + '/clab-backup-ui'
VENV = SRC + '/.venv/bin'
scratch = sys.argv[1]
COPY = os.path.join(scratch, 'clab-backup-ui')
if not os.path.exists(COPY):
    shutil.copytree(SRC, COPY, ignore=shutil.ignore_patterns('.venv', 'node_modules', '__pycache__'))
env = dict(os.environ, PATH=VENV + ':' + os.environ['PATH'])

def py(pattern, name):
    p = subprocess.run([VENV + '/python', '-m', 'unittest', 'discover', '-s', 'tests', '-t', 'tests', '-p', pattern, '-k', name],
                       cwd=COPY, env=env, capture_output=True, text=True, timeout=900)
    tail = [l for l in p.stderr.splitlines() if l.startswith(('Ran ', 'OK', 'FAILED'))]
    return p.returncode, ' | '.join(tail)

def js(file, pattern):
    p = subprocess.run(['node', '--test', '--test-name-pattern=' + pattern, 'tests/' + file], cwd=COPY, capture_output=True, text=True, timeout=300)
    tail = [l for l in p.stdout.splitlines() if l.startswith(('# pass', '# fail', '# tests'))]
    return p.returncode, ' | '.join(tail)

M = [
 ('QA-020', 'app/lab_operations.py', "                if preview.get('node'):\n                    # Restart device: the consent",
  "                self.guard(preview['lab_id'])\n                if preview.get('node'):\n                    # Restart device: the consent",
  'guard() moved back ahead of the consent checks in confirm()', ('py', 'test_lab_operations.py', 'test_a_stale_restart_review_hears_the_stale_reason_while_the_previous_job_still_refreshes')),
 ('QA-019', 'app/node_readiness.py', 'if since is not None and time.monotonic() - since < LOGIN_GRACE:', 'if False:',
  'login grace window disabled (a refusal always counts)', ('py', 'test_node_readiness.py', 'test_a_refused_login_right_after_a_manager_restart_reads_booting_until_the_grace_window_closes')),
 ('QA-019b', 'app/lab_operations.py', "LIFECYCLE_JOBS", "LIFECYCLE_JOBS", None, None),  # placeholder, replaced below
 ('QA-017', 'app/lab_operations.py', "    'cisco_xrv9k': 'Known limit of the XRv9k image", "    'cisco_xrv9k_UNDONE': 'Known limit of the XRv9k image",
  'the XRv9k known limit removed from RESTART_KNOWN_LIMITS', ('py', 'test_lab_operations.py', 'test_the_xrv9k_review_names_the_fresh_disk_limit_and_other_kinds_get_no_note')),
 ('QA-018', 'app/lab_operations.py', '            if label not in down: down.append(label)', '            pass',
  'restart_links() never reports a neighbour that is down', ('py', 'test_lab_operations.py', 'test_a_neighbour_that_is_not_running_is_named_in_the_review_and_the_job_counts_the_links')),
 ('QA-014', 'app/lab_operations.py', 'exited = self.settled_after_restart(restart_key)', "exited = ''",
  'the post-restart settle check skipped (exit status alone decides)', ('py', 'test_lab_operations.py', 'test_a_restart_whose_container_exits_right_after_is_a_failed_job_with_the_reason')),
 ('RD-001', 'app/lab_operations.py', "raise HTTPException(409, 'Another lab operation ran while this review was being prepared. Review the restart again.')", 'pass',
  'the preview-time lifecycle refusal removed', ('py', 'test_lab_operations.py', 'test_a_restart_device_review_is_stale_when_a_lifecycle_job_lands_during_its_own_helper_calls')),
 ('QA-016', 'app/design_intent.py', "NAME = re.compile(r'^[A-Za-z_][A-Za-z0-9_]{0,15}$')", "NAME = re.compile(r'^[A-Za-z_][A-Za-z0-9_]{0,63}$')",
  'NAME back to 64 characters', ('py', 'test_design_intent.py', 'test_engine_identifiers_follow_netlabs_16_character_rule')),
 ('QA-012', 'app/design_intent.py', '    _check_bgp_as(intent, modules, errors)   #', '    pass   #',
  'the BGP AS range check not called', ('py', 'test_design_intent.py', 'test_bgp_as_must_be_present_and_in_range')),
 ('QA-015', 'app/static/network-design.js', 'if(designState.labId!==labId||seq<=designViewApplied)return false;', 'if(designState.labId!==labId)return false;',
  'the sequence guard in designViewFresh removed (lab identity only)', ('js', 'test_network_design_ui.js', 'QA-015')),
]
# QA-019 second half: a lab-wide lifecycle job forgets every device (opens the grace window for all of them).
M[2] = None
out = {'started': datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'), 'copy': COPY, 'rows': []}
for m in M:
    if m is None: continue
    ident, rel, old, new, what, test = m
    path = os.path.join(COPY, rel); text = open(path).read()
    n = text.count(old)
    row = {'id': ident, 'file': rel, 'mutation': what, 'test': test[2], 'occurrences': n}
    run = py if test[0] == 'py' else js
    row['pristine_rc'], row['pristine'] = run(test[1], test[2])
    if n != 1: row['verdict'] = 'NOT RUN (anchor found %d times)' % n; out['rows'].append(row); continue
    open(path, 'w').write(text.replace(old, new))
    try: row['mutant_rc'], row['mutant'] = run(test[1], test[2])
    finally: open(path, 'w').write(text)
    row['verdict'] = 'KILLED (test fails with the fix undone)' if row['pristine_rc'] == 0 and row['mutant_rc'] != 0 else 'SURVIVED' if row['pristine_rc'] == 0 else 'INVALID (pristine test failed)'
    out['rows'].append(row)

# TOOL-002: the two assertions of check_restart_device.py, fed synthetic inputs.
sys.path.insert(0, ROOT + '/docs/netlab-ui-qa/tools')
import check_restart_device as crd  # noqa: E402
class R:
    def __init__(self): self.results = []
    def check(self, name, ok, detail=''): self.results.append((name, bool(ok)))
def argv_case(argv):
    crd.call = lambda base, path, method='GET', body=None: (200, {'argv': argv})
    r = R(); crd.check_argv(r, 'x', 'lab', 'clab-restore-square-ceos', 'ceos'); return r.results[-1][1]
T = '/srv/x/restore-square.clab.yml'
cases = {
 'exact argv accepted': argv_case(['/usr/bin/containerlab', 'restart', '-t', T, '--node', 'ceos']),
 'two --node refused': not argv_case(['/usr/bin/containerlab', 'restart', '-t', T, '--node', 'ceos', '--node', 'host1']),
 'wrong node refused': not argv_case(['/usr/bin/containerlab', 'restart', '-t', T, '--node', 'host1']),
 'no --node refused': not argv_case(['/usr/bin/containerlab', 'restart', '-t', T]),
 'destroy instead of restart refused': not argv_case(['/usr/bin/containerlab', 'destroy', '-t', T, '--node', 'ceos']),
}
words_ok = lambda words: 'failed' not in words and all(w in ('booting', 'restarting', 'ready', 'unavailable', 'checking') for w in words)
src = open(ROOT + '/docs/netlab-ui-qa/tools/check_restart_device.py').read()
cases['the failed-between check expression is the one in the tool'] = "'failed' not in words and all(w in ('booting', 'restarting', 'ready', 'unavailable', 'checking') for w in words)" in src
cases['booting → failed → booting → ready refused'] = not words_ok(['booting', 'failed', 'booting', 'ready'])
cases['booting → ready accepted'] = words_ok(['booting', 'ready'])
out['rows'].append({'id': 'TOOL-002', 'mutation': 'synthetic inputs to check_argv and the failed-between expression', 'cases': cases,
                    'verdict': 'HOLDS' if all(cases.values()) else 'BROKEN'})
out['finished'] = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')
print(json.dumps(out, indent=1))
