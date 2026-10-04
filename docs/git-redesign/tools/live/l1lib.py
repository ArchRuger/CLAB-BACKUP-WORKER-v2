"""Helpers for the L1 live backend pass (stdlib plus paramiko from clab-backup-ui/.venv).

Used from small scenario scripts; every function prints what it did in a form that can be pasted into an
evidence file. Nothing here prints a token, a password or a whole configuration: device reads are filtered to
the lines the caller asks for, and API answers are trimmed to the keys the caller names.
"""
import json
import pathlib
import re
import subprocess
import sys
import time
import uuid

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[3] / 'docs/multi-platform-restore/tools'))
import mgr  # noqa: E402

REPO = 'ArchRuger/clab-scratch-git-redesign'
CHECKOUT = '/home/archtop/labs/clab-scratch-git-redesign'
LAB_A = '63d53e20db83464392ebfd4712bba5e3'    # git-redesign (cjunos, xrv9k, ceos1, ceos2)
LAB_B = 'cbee72c4fe5741bca264d72dff0d8cab'    # git-redesign-b (ceos1, ceos2)
ROOT_BINDING = 'e7d5f64d4c85487ebcff3baeff12694a'
BUSY = ('queued', 'running', 'exporting', 'capturing', 'saving', 'pending', 'uploading')

# Management addresses and the published kind logins of the two labs (docs/git-redesign/LIVE-ENV.md section 3).
DEVICES = {
    'a-ceos1': ('172.20.20.101', 'admin', 'admin', 'eos'),
    'a-ceos2': ('172.20.20.102', 'admin', 'admin', 'eos'),
    'a-cjunos': ('172.20.20.103', 'admin', 'admin@123', 'junos'),
    'a-xrv9k': ('172.20.20.104', 'clab', 'clab@123', 'iosxr'),
    'b-ceos1': ('172.20.20.111', 'admin', 'admin', 'eos'),
    'b-ceos2': ('172.20.20.112', 'admin', 'admin', 'eos'),
}
CONTAINERS = {'a-ceos1': 'clab-git-redesign-ceos1', 'a-ceos2': 'clab-git-redesign-ceos2', 'a-cjunos': 'clab-git-redesign-cjunos',
              'a-xrv9k': 'clab-git-redesign-xrv9k', 'b-ceos1': 'clab-git-redesign-b-ceos1', 'b-ceos2': 'clab-git-redesign-b-ceos2'}
# The interface each device's recognisable description goes on (an interface that exists on the node).
IFACE = {'a-ceos1': 'Ethernet1', 'a-ceos2': 'Ethernet2', 'a-cjunos': 'et-0/0/1', 'a-xrv9k': 'GigabitEthernet0/0/0/0',
         'b-ceos1': 'Ethernet1', 'b-ceos2': 'Ethernet1'}


def now():
    return time.strftime('%H:%M:%S', time.gmtime())


def rid():
    return uuid.uuid4().hex


def trim(value, keys=None, limit=700):
    if keys and isinstance(value, dict):
        value = {k: value[k] for k in keys if k in value}
    text = json.dumps(value, sort_keys=True, default=str)
    return text if len(text) <= limit else text[:limit] + ' ...[trimmed]'


def api(method, path, body=None, keys=None, show=True, limit=700, timeout=600):
    start = time.monotonic()
    status, answer = mgr.call(method, path, body, timeout=timeout)
    if show:
        shown = {} if body is None else body
        print(f'[{now()}] {method} {path} {json.dumps(shown, sort_keys=True) if method != "GET" else ""}'.rstrip())
        print(f'    -> HTTP {status} ({time.monotonic() - start:.1f}s) {trim(answer, keys, limit)}')
    return status, answer


def git_job(job_id):
    return mgr.call('GET', f'/api/git/jobs/{job_id}')[1]


def wait_git(job_id, stop=('review_pending', 'synced', 'unchanged', 'failed', 'dismissed', 'capture_incomplete', 'upload_failed',
                          'needs_attention', 'interrupted', 'push_failed', 'push_pending', 'committed'), timeout=900, show=True):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        job = git_job(job_id)
        if job.get('status') != last:
            last = job.get('status')
            if show:
                print(f'[{now()}]    job {job_id[:8]} status={last} message={job.get("message")!r}')
        if job.get('status') in stop:
            return job
        time.sleep(2)
    raise SystemExit('job did not settle: ' + job_id)


JOB_KEYS = ('status', 'message', 'target', 'kind', 'note', 'note_auto', 'summary', 'commit', 'pushed', 'reviewed', 'destination',
            'changed_files', 'lab_name', 'checkpoint')


def show_job(job, keys=JOB_KEYS):
    print('    job:', trim(job, keys, 1200))


def save(lab, note='', push=True, target='latest', extra=None, wait=True, show=True):
    body = dict(request_id=rid(), target=target, push=push, note=note)
    body.update(extra or {})
    status, job = api('POST', f'/api/labs/{lab}/git/save', body, keys=('id', 'status', 'message', 'detail'), show=show)
    if status != 200 or not wait:
        return status, job
    return status, wait_git(job['id'], show=show)


def compare(lab, job_id):
    status, answer = api('POST', f'/api/labs/{lab}/git/compare', {'job_id': job_id}, show=False)
    print(f'[{now()}] POST /api/labs/{lab}/git/compare {{"job_id": "{job_id[:8]}.."}} -> HTTP {status}')
    if status == 200:
        files = [{k: f.get(k) for k in ('role', 'node', 'path', 'status', 'added', 'removed') if k in f} for f in answer.get('files', [])]
        for f in files:
            print('     file', json.dumps(f, sort_keys=True))
        print('     summary', trim(answer.get('summary')))
        print('     head', answer.get('head'), 'upload_job', answer.get('upload_job'))
        print('     also_sends', trim(answer.get('also_sends'), limit=900), 'count', answer.get('also_sends_count'),
              'other_labs', answer.get('also_sends_other_labs'))
    else:
        print('    ', trim(answer))
    return status, answer


def upload(job_id, head, show=True):
    status, answer = api('POST', f'/api/git/jobs/{job_id}/retry', dict(push=True, reviewed=True, head=head), keys=('id', 'status', 'message', 'detail'), show=show)
    return status, answer


def upload_and_wait(job_id, head):
    status, answer = upload(job_id, head)
    if status != 200:
        return status, answer
    return status, wait_git(answer['id'])


# --- VM checkout and GitHub ------------------------------------------------------------------------------------
def sh(*cmd, check=False):
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if check and out.returncode:
        raise SystemExit(f'{cmd} -> {out.returncode}: {out.stderr[:300]}')
    return out.returncode, (out.stdout + out.stderr).strip()


def vmgit(*args):
    return sh('git', '-C', CHECKOUT, *args)


def checkout(label=''):
    print(f'  [VM checkout {label}]')
    for cmd in (('log', '--oneline', '-4'), ('status', '-sb')):
        code, out = vmgit(*cmd)
        for line in out.splitlines()[:6]:
            print('     ', line)


def gh(path, jq=None):
    cmd = ['gh', 'api', f'repos/{REPO}/{path}']
    if jq:
        cmd += ['--jq', jq]
    code, out = sh(*cmd)
    return code, out


def github(label=''):
    print(f'  [GitHub {label}]')
    code, out = gh('commits?per_page=4', '.[] | "\\(.sha[0:10]) \\(.commit.message | split("\\n")[0])"')
    for line in out.splitlines():
        print('     ', line)


def gh_tree(prefix=''):
    code, out = gh('git/trees/main?recursive=1', '.tree[] | select(.type=="blob") | .path')
    paths = [p for p in out.splitlines() if p.startswith(prefix)]
    return paths


def gh_commit_patch(sha, path_filter=None, maxlines=14):
    """Changed lines of a commit on GitHub, one file at a time (no whole configurations)."""
    code, out = gh(f'commits/{sha}', '.files[] | "FILE \\(.filename) +\\(.additions) -\\(.deletions)\\n\\(.patch // "")"')
    lines = []
    show = True
    for line in out.splitlines():
        if line.startswith('FILE '):
            show = path_filter is None or re.search(path_filter, line) is not None
            print('     ', line)
            continue
        if show and (line.startswith('+') or line.startswith('-')) and not line.startswith(('+++', '---')):
            lines.append(line)
            if len(lines) <= maxlines:
                print('       ', line[:160])
    return out


# --- devices ----------------------------------------------------------------------------------------------------
def _session(name):
    import nodecli
    ip, user, password, family = DEVICES[name]
    nodecli.NODES[name] = (ip, user, password, family)
    return nodecli.Session(name, timeout=90)


def cli(name, lines, timeout=90):
    session = _session(name)
    out = ''
    try:
        for line in lines:
            out += session.run(line, timeout)
    finally:
        session.close()
    return out


def describe_cmds(name, tag):
    family = DEVICES[name][3]
    interface = IFACE[name]
    if family == 'eos':
        return ['configure', f'interface {interface}', f'description {tag}', 'end', 'write memory']
    if family == 'junos':
        return ['configure', f'set interfaces {interface} description {tag}', 'commit', 'exit']
    return ['configure', f'interface {interface}', f'description {tag}', 'commit', 'end']


def clear_cmds(name):
    family = DEVICES[name][3]
    interface = IFACE[name]
    if family == 'eos':
        return ['configure', f'interface {interface}', 'no description', 'end', 'write memory']
    if family == 'junos':
        return ['configure', f'delete interfaces {interface} description', 'commit', 'exit']
    return ['configure', f'interface {interface}', 'no description', 'commit', 'end']


def clear_description(name):
    return cli(name, clear_cmds(name))


def read_cmd(name):
    family = DEVICES[name][3]
    interface = IFACE[name]
    if family == 'eos':
        return f'show running-config interfaces {interface}'
    if family == 'junos':
        return f'show configuration interfaces {interface}'
    return f'show running-config interface {interface}'


def set_description(name, tag):
    out = cli(name, describe_cmds(name, tag))
    bad = [l for l in out.splitlines() if re.search(r'(^%|error|invalid|unknown command|cannot)', l, re.I) and 'description' not in l.lower()]
    return bad


def description_of(name):
    """The description line on the device's interface (the only line read back), '' when none."""
    out = cli(name, [read_cmd(name)])
    for line in out.splitlines():
        if 'description' in line.lower() and 'show ' not in line:
            return line.strip()
    return ''


def descriptions(names=None):
    result = {}
    for name in names or DEVICES:
        try:
            result[name] = description_of(name)
        except Exception as exc:  # noqa: BLE001 (reported, not fatal)
            result[name] = f'<unreadable: {type(exc).__name__}>'
    return result


def show_descriptions(label, names=None):
    print(f'  [device descriptions {label}]')
    for name, line in descriptions(names).items():
        print(f'      {name:9s} {IFACE[name]:24s} {line}')


def ready(lab):
    st = mgr.call('GET', '/api/state')[1]
    for l in st['labs']:
        if l['id'] == lab:
            return l['nos_readiness'], [(n['name'], n.get('readiness')) for n in l['nodes']], l.get('git_status')
    return None


# --- restore ----------------------------------------------------------------------------------------------------
RESTORE_END = ('succeeded', 'partial', 'needs_attention', 'failed', 'preflight_failed', 'interrupted')


def preflight(lab, source, nodes=None, show=True):
    body = dict(source=source)
    if nodes is not None:
        body['node_names'] = nodes
    status, answer = api('POST', f'/api/labs/{lab}/restore/preflight', body, show=False)
    print(f'[{now()}] POST /api/labs/{lab}/restore/preflight {json.dumps(body, sort_keys=True)} -> HTTP {status}')
    if status != 200:
        print('    ', trim(answer))
        return status, answer
    print('     source', trim(answer.get('source'), limit=600))
    for key in answer:
        if key not in ('source', 'nodes', 'targets', 'rows'):
            print(f'     {key}:', trim(answer[key], limit=300))
    rows = answer.get('nodes') or answer.get('targets') or answer.get('rows') or []
    for row in rows:
        print('     row', trim(row, ('node', 'name', 'eligible', 'status', 'platform', 'differs', 'counts', 'missing', 'extra', 'difference_count',
                                       'reason', 'unusable', 'confirm', 'changes', 'summary', 'selectable', 'offered', 'matches_saved', 'pending_changes', 'reachable', 'requested', 'running_platform'), 520))
        diff = row.get('diff')
        if isinstance(diff, dict):
            changed = [f"{l.get('type')}: {l.get('text')}" for h in diff.get('hunks', []) for l in h.get('lines', []) if l.get('type') != 'context']
            print('       diff (changed lines):', changed[:8], 'added', diff.get('added'), 'removed', diff.get('removed'))
    return status, answer


def restore(lab, source, nodes, minutes=5, wait=True, poll=5):
    body = dict(request_id=rid(), source=source, node_names=nodes, confirm_minutes=minutes, acknowledge=True)
    start = time.monotonic()
    status, answer = api('POST', f'/api/labs/{lab}/restore', body, keys=('id', 'status', 'message'))
    if status != 200 or not wait:
        return status, answer, 0
    return follow_restore(answer['id'], start, poll)


def follow_restore(job_id, start=None, poll=5):
    start = start or time.monotonic()
    last = None
    while True:
        job = mgr.call('GET', f'/api/restore/jobs/{job_id}')[1]
        marks = trim({t.get('short_name') or t.get('name'): t.get('stage') for t in job.get('targets', [])}, limit=400)
        if (job['status'], marks) != last:
            last = (job['status'], marks)
            print(f'[{now()}]    restore {job_id[:8]} status={job["status"]} stages={marks}')
        if job['status'] in RESTORE_END:
            return 200, job, time.monotonic() - start
        time.sleep(poll)


def show_restore(job, elapsed):
    print(f'    restore job status={job.get("status")} message={job.get("message")!r} elapsed={elapsed:.0f}s')
    print('    job keys:', sorted(job.keys()))
    for k in ('pre_backup_job_id', 'check_backup_job_id', 'confirm_minutes', 'source'):
        if k in job:
            print(f'    {k}:', trim(job[k], limit=400))
    for t in job.get('targets', []):
        keep = {k: t.get(k) for k in t if k not in ('diff', 'differences_sample', 'samples') and not k.startswith('_')}
        print('    target', trim(keep, limit=900))


def containers_up():
    code, out = sh('docker', 'ps', '--format', '{{.Names}} {{.Status}}')
    return [l for l in out.splitlines() if 'clab-git-redesign' in l]
