#!/usr/bin/env python3
"""Reusable live-failure triggers for *Replace running configuration*, and their evidence.

Every subcommand submits a REAL restore job against the running manager (``--url``, default
``http://127.0.0.1:8081``) and a REAL restore-square node, and disrupts only what the check asks
for: a host ``iptables OUTPUT`` rule against that one node's management address (always removed in
a ``finally`` block, and its absence is asserted before exit), or the manager container itself
(``docker restart``, never rebuilt, and never run unless the caller explicitly asks for the
``restart-confirming`` subcommand). It never touches the driver or service code under test: the
trigger, the readback and the identity are all independent of it.

    failure_harness.py submit-cut     --node ceos --backup JOB_ID [--minutes 2] --evidence FILE
    failure_harness.py armed-cut      --node cjunosevolved --commit SHA --path PATH [--minutes 2] --evidence FILE
    failure_harness.py restart-confirming --node ceos --backup JOB_ID [--minutes 3] [--ssh-blocked] --evidence FILE

``--backup JOB_ID`` / ``--folder PATH`` / ``--commit SHA --path PATH`` choose the restore source,
exactly as in manager_restore.py. One node per invocation (the trigger races a single TCP identity
or device state, which is only unambiguous for one target).

Subcommands
-----------
``submit-cut``
    B3 at application: cut management the instant this node's target reaches ``applying`` -- after
    the mandatory pre-restore backup has already succeeded, but before the driver can open its own
    connection to replace the configuration. A tight busy loop on ``/proc/net/tcp`` (host-wide,
    because the manager runs with host networking) blocks on the first sign of that connection, not
    on the coarser HTTP poll, so the device is never actually reached. Expect the target ``failed``
    with a connectivity message, never a partial change.

``armed-cut``
    B4: cut management once the change is armed on the device and is awaiting confirmation. cEOS is
    asked directly and repeatedly while blocked (``docker exec ... Cli -p 15``, read-only, the one
    channel that survives an iptables block on port 22) for "Session with pending commit timer".
    The two Junos images cannot be read while blocked, so the trigger there is the manager's own TCP
    behaviour instead: ``_apply_one`` (restore.py) opens exactly one SSH connection for the whole
    apply, closes it, and only then opens a fresh one to confirm -- blocking the instant a *new*
    local port appears after the first one closes lands inside that gap.

``restart-confirming``
    B5: restart the manager container (``docker restart``, not a rebuild) the instant this node's
    target reaches ``confirming``. SSH is left reachable by default, so the restart re-check should
    recover the armed change under its own token; ``--ssh-blocked`` cuts management first too, for
    the harder case where the device also cannot be reached when the manager comes back.

Every subcommand's evidence embeds ``manager_restore.build_identity()`` (the running image, the
checkout it was built from) and a ``readback.py`` snapshot (booleans, counts, boot identity -- never
raw configuration) taken before the trigger and again after the iptables rule is removed. Run with
the application's virtual environment (paramiko):

    clab-backup-ui/.venv/bin/python docs/multi-platform-restore/tools/failure_harness.py ...

No credentials or raw device output are read or written by this tool; only counts, booleans, status
strings and the scrubbed messages the manager's own API already returns.
"""
import argparse
import json
import socket
import struct
import subprocess
import sys
import time
import uuid

import manager_restore as mr
import readback as rb

NODES = {
    'ceos': {'container': 'clab-restore-square-ceos', 'ip': '172.20.20.101', 'family': 'eos'},
    'cjunosevolved': {'container': 'clab-restore-square-cjunosevolved', 'ip': '172.20.20.102', 'family': 'junos'},
    'vjunos-switch': {'container': 'clab-restore-square-vjunos-switch', 'ip': '172.20.20.103', 'family': 'junos'},
    # IOS XR: the manager keeps the arming connection open and opens a second one to prove management, so the same
    # connection-identity trigger applies: block the instant a NEW local port appears beside the apply connection.
    # The block also kills the held arming session, so nothing can confirm and the node undoes the change at its timer.
    'xrv9k': {'container': 'clab-restore-square-xrv9k', 'ip': '172.20.20.104', 'family': 'iosxr'},
}
MANAGER_CONTAINER = mr.CONTAINER
PENDING_TIMER = __import__('re').compile(r'Session with pending commit timer:\s*(\S+)')

CURRENT_IP = None   # set while a block may be in place; the safety net in main() reads it


def stamp():
    return time.strftime('%H:%M:%S', time.gmtime()) + ('.%03d' % (time.time() % 1 * 1000))


def target_name(node):
    return 'clab-%s-%s' % (mr.LAB, node)


def source_from_args(args):
    if args.backup:
        return {'type': 'backup', 'backup_job_id': args.backup}
    if args.folder:
        return {'type': 'folder', 'path': args.folder}
    if args.commit:
        return {'type': 'git', 'commit': args.commit, 'path': args.path}
    raise SystemExit('Choose one restore source: --backup, --folder, or --commit --path.')


def try_call(manager, path, body=None, timeout=5):
    try:
        return manager.call(path, body, timeout)
    except Exception as exc:
        return None, {'error': type(exc).__name__ + ': ' + str(exc)}


# --- iptables: the one disruption every subcommand may make, always undone -------------------

def block(ip):
    global CURRENT_IP
    CURRENT_IP = ip
    subprocess.run(['sudo', '-n', 'iptables', '-I', 'OUTPUT', '-p', 'tcp', '-d', ip, '--dport', '22', '-j', 'REJECT'],
                    check=True, capture_output=True)


def unblock(ip):
    subprocess.run(['sudo', '-n', 'iptables', '-D', 'OUTPUT', '-p', 'tcp', '-d', ip, '--dport', '22', '-j', 'REJECT'],
                    check=False, capture_output=True)


def rule_present(ip):
    result = subprocess.run(['sudo', '-n', 'iptables', '-S', 'OUTPUT'], capture_output=True, text=True)
    return ip in result.stdout


# --- the manager container: restart-confirming only, and only when asked ---------------------

def restart_manager():
    result = subprocess.run(['sudo', '-n', 'docker', 'restart', MANAGER_CONTAINER], capture_output=True, text=True, timeout=60)
    return result.returncode, result.stdout.strip(), result.stderr.strip()


# --- cEOS device truth: the one channel that still answers while SSH is blocked --------------

def device_sessions(container):
    result = subprocess.run(['sudo', '-n', 'docker', 'exec', container, 'Cli', '-p', '15', '-c',
                             'show configuration sessions detail'], capture_output=True, text=True, timeout=10)
    return result.stdout.strip()


# --- the manager's own TCP identity, read from the host (host networking) --------------------

def _hexaddr(ip):
    return '%08X' % struct.unpack('<I', socket.inet_aton(ip))[0]


def local_ports(ip, port=22):
    """Local (ephemeral) ports of any not-yet-closed connection to ip:port (ESTABLISHED/SYN_SENT/SYN_RECV).

    A closing connection and a newly opening one can be a fraction of a millisecond apart, so
    identity (which port) rather than a raw count is what survives a same-poll-gap transition.
    """
    target, suffix, ports = _hexaddr(ip), ':%04X' % port, set()
    try:
        with open('/proc/net/tcp') as handle:
            lines = handle.readlines()[1:]
    except FileNotFoundError:
        return ports
    for line in lines:
        fields = line.split()
        local, remote, state = fields[1], fields[2], fields[3]
        if remote == target + suffix and state in ('01', '02', '03'):
            ports.add(local.split(':')[1])
    return ports


def device_readback(node, saved=None):
    try:
        return rb.read(node, saved)
    except Exception as exc:
        return {'error': type(exc).__name__ + ': ' + str(exc)}


def poll_job(manager, job_id, name, predicate, timeout, interval=0.05):
    """Poll until `predicate(job, target)` is true for the named target, or timeout. Returns (job, target)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        _, job = try_call(manager, '/restore/jobs/' + job_id, timeout=3)
        target = next((t for t in (job or {}).get('targets', []) if t['name'] == name), None) if job else None
        if target and predicate(job, target):
            return job, target
        time.sleep(interval)
    return None, None


def drain_job(manager, job_id, name, timeline, t0, deadline_s):
    """Poll to a terminal job status, recording every (job, target) status change. Returns the final job."""
    last = None
    deadline = time.monotonic() + deadline_s
    while time.monotonic() < deadline:
        _, job = try_call(manager, '/restore/jobs/' + job_id, timeout=5)
        if not job or 'targets' not in job:
            time.sleep(0.5)
            continue
        target = next((t for t in job['targets'] if t['name'] == name), {})
        view = (job.get('status'), target.get('status'))
        if view != last:
            timeline.append({'t': time.monotonic() - t0, 'utc': stamp(), 'job_status': view[0],
                             'target_status': view[1], 'message': target.get('message', '')})
            last = view
        if job.get('status') in mr.ENDED:
            return job
        time.sleep(1)
    _, job = try_call(manager, '/restore/jobs/' + job_id, timeout=5)
    return job


# --- submit-cut: B3 at application ------------------------------------------------------------

def submit_cut(args, manager):
    node = NODES[args.node]
    name = target_name(args.node)
    record = {'trigger': 'submit-cut', 'node': args.node, 'minutes': args.minutes, 'started_utc': stamp(),
              'method': 'block the first sign of the apply connection, once this target reaches applying '
                        '(the mandatory pre-restore backup has already succeeded by then)',
              'build': mr.build_identity(), 'readback_before': device_readback(args.node, args.saved)}
    lab_id = manager.lab()[1]['id']
    body = {'request_id': uuid.uuid4().hex, 'source': source_from_args(args), 'node_names': [name],
            'confirm_minutes': args.minutes, 'acknowledge': True}
    t0 = time.monotonic()
    code, job = manager.call('/labs/%s/restore' % lab_id, body)
    record['submit'] = {'http': code, 'id': job.get('id')}
    if code != 200:
        record['submit_body'] = job
        return record
    job_id = job['id']

    _, applying = poll_job(manager, job_id, name, lambda j, t: t['status'] == 'applying', timeout=60, interval=0.02)
    record['reached_applying'] = applying is not None
    if applying is None:
        record['note'] = 'Target never reached applying within 60s; nothing was blocked.'
        record['final_job'] = drain_job(manager, job_id, name, [], t0, 120)
        return record
    record['reached_applying_at_rel_s'] = time.monotonic() - t0

    # Tight busy loop: block the instant ANY connection to the node's management port appears.
    tight_deadline = time.monotonic() + 15
    blocked_at = None
    while time.monotonic() < tight_deadline and blocked_at is None:
        if local_ports(node['ip']):
            block(node['ip'])
            blocked_at = time.monotonic() - t0
    record['blocked_at_rel_s'] = blocked_at
    if blocked_at is None:
        # The apply connection never appeared inside the tight window (unusually slow scheduling);
        # block now regardless so a late connection still finds it, and say so plainly.
        block(node['ip'])
        record['note'] = 'The apply connection was not observed opening within 15s of applying; blocked late.'

    timeline = []
    record['final_job'] = drain_job(manager, job_id, name, timeline, t0, args.minutes * 60 + 90 + 30)
    record['timeline'] = timeline
    record['rule_present_before_unblock'] = rule_present(node['ip'])
    unblock(node['ip'])
    record['rule_present_after_unblock'] = rule_present(node['ip'])
    # Give the job a little more time to reflect the unblock, in case it was still retrying.
    extra = []
    record['final_job'] = drain_job(manager, job_id, name, extra, t0, 60)
    record['timeline'] += extra
    record['finished_utc'] = stamp()
    record['readback_after'] = device_readback(args.node, args.saved)
    return record


# --- armed-cut: B4 -----------------------------------------------------------------------------

def armed_cut(args, manager):
    node = NODES[args.node]
    name = target_name(args.node)
    record = {'trigger': 'armed-cut', 'node': args.node, 'minutes': args.minutes, 'started_utc': stamp(),
              'method': ('device-truth (docker exec Cli -p 15)' if node['family'] == 'eos'
                        else 'connection-identity (apply connection closes, then the confirm reconnect opens)'),
              'build': mr.build_identity(), 'readback_before': device_readback(args.node, args.saved)}
    lab_id = manager.lab()[1]['id']
    body = {'request_id': uuid.uuid4().hex, 'source': source_from_args(args), 'node_names': [name],
            'confirm_minutes': args.minutes, 'acknowledge': True}
    t0 = time.monotonic()
    code, job = manager.call('/labs/%s/restore' % lab_id, body)
    record['submit'] = {'http': code, 'id': job.get('id')}
    if code != 200:
        record['submit_body'] = job
        return record
    job_id = job['id']

    blocked_at = None
    if node['family'] == 'eos':
        tight_deadline = time.monotonic() + 20
        poll_log = []
        while time.monotonic() < tight_deadline and blocked_at is None:
            text = device_sessions(node['container'])
            match = PENDING_TIMER.search(text)
            poll_log.append({'t': time.monotonic() - t0, 'armed': bool(match)})
            if match:
                block(node['ip'])
                blocked_at = time.monotonic() - t0
                record['armed_session_name'] = match.group(1)
        record['device_poll_count_before_block'] = len(poll_log)
    else:
        _, applying = poll_job(manager, job_id, name, lambda j, t: t['status'] == 'applying', timeout=30, interval=0.05)
        record['reached_applying'] = applying is not None
        if applying is None:
            record['note'] = 'Target never reached applying within 30s.'
            record['final_job'] = drain_job(manager, job_id, name, [], t0, 60)
            return record
        conn_log, apply_port = [], None
        tight_deadline = time.monotonic() + 30
        while time.monotonic() < tight_deadline and blocked_at is None:
            ports = local_ports(node['ip'])
            if apply_port is None and ports:
                apply_port = next(iter(ports))
                conn_log.append({'t': time.monotonic() - t0, 'event': 'apply_connection_port', 'port': apply_port})
            elif apply_port is not None and (ports - {apply_port}):
                block(node['ip'])
                blocked_at = time.monotonic() - t0
                conn_log.append({'t': blocked_at, 'event': 'blocked_on_new_port'})
        record['conn_log'] = conn_log
    record['blocked_at_rel_s'] = blocked_at
    if blocked_at is None:
        record['note'] = 'Never observed the arming trigger within the tight window; nothing was blocked.'
        record['final_job'] = drain_job(manager, job_id, name, [], t0, 60)
        return record

    timeline = []
    hold_s = min(args.minutes * 60 + 90 - 15, blocked_at + args.minutes * 60 + 40)
    record['final_job_while_blocked'] = drain_job(manager, job_id, name, timeline, t0, hold_s)
    record['rule_present_before_unblock'] = rule_present(node['ip'])
    unblock(node['ip'])
    record['rule_present_after_unblock'] = rule_present(node['ip'])
    record['unblocked_at_rel_s'] = time.monotonic() - t0
    extra = []
    record['final_job'] = drain_job(manager, job_id, name, extra, t0, 240)
    record['timeline'] = timeline + extra
    record['finished_utc'] = stamp()
    record['readback_after'] = device_readback(args.node, args.saved)
    return record


# --- restart-confirming: B5 ---------------------------------------------------------------------

def restart_confirming(args, manager):
    node = NODES[args.node]
    name = target_name(args.node)
    record = {'trigger': 'restart-confirming', 'node': args.node, 'minutes': args.minutes, 'started_utc': stamp(),
              'ssh_blocked': args.ssh_blocked, 'build': mr.build_identity(),
              'readback_before': device_readback(args.node, args.saved) if not args.ssh_blocked else None}
    lab_id = manager.lab()[1]['id']
    body = {'request_id': uuid.uuid4().hex, 'source': source_from_args(args), 'node_names': [name],
            'confirm_minutes': args.minutes, 'acknowledge': True}
    t0 = time.monotonic()
    code, job = manager.call('/labs/%s/restore' % lab_id, body)
    record['submit'] = {'http': code, 'id': job.get('id')}
    if code != 200:
        record['submit_body'] = job
        return record
    job_id = job['id']

    _, confirming = poll_job(manager, job_id, name, lambda j, t: t['status'] == 'confirming', timeout=60, interval=0.05)
    record['reached_confirming'] = confirming is not None
    if confirming is None:
        record['note'] = 'Target never reached confirming within 60s; the manager was not restarted.'
        record['final_job'] = drain_job(manager, job_id, name, [], t0, 60)
        return record
    record['reached_confirming_at_rel_s'] = time.monotonic() - t0

    if args.ssh_blocked:
        block(node['ip'])
        record['blocked_at_rel_s'] = time.monotonic() - t0

    restart_t = time.monotonic() - t0
    rc, out, err = restart_manager()
    record['restart'] = {'t': restart_t, 'utc': stamp(), 'returncode': rc, 'stdout': out, 'stderr': err}

    up_deadline = time.monotonic() + 90
    up_at = None
    while time.monotonic() < up_deadline:
        code, state = try_call(manager, '/state')
        if code == 200:
            up_at = time.monotonic() - t0
            record['manager_version_after_restart'] = state.get('version')
            break
        time.sleep(0.5)
    record['manager_back_at_rel_s'] = up_at
    _, right_after = try_call(manager, '/restore/jobs/' + job_id)
    record['job_right_after_restart'] = right_after

    timeline = []
    record['final_job'] = drain_job(manager, job_id, name, timeline, t0, 240)
    record['timeline'] = timeline
    if args.ssh_blocked:
        record['rule_present_before_unblock'] = rule_present(node['ip'])
        unblock(node['ip'])
        record['rule_present_after_unblock'] = rule_present(node['ip'])
        extra = []
        record['final_job'] = drain_job(manager, job_id, name, extra, t0, 240)
        record['timeline'] += extra
    record['finished_utc'] = stamp()
    record['readback_after'] = device_readback(args.node, args.saved)
    return record


SUBCOMMANDS = {'submit-cut': submit_cut, 'armed-cut': armed_cut, 'restart-confirming': restart_confirming}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('subcommand', choices=sorted(SUBCOMMANDS))
    parser.add_argument('--url', default='http://127.0.0.1:8081')
    parser.add_argument('--node', required=True, choices=sorted(NODES))
    parser.add_argument('--backup'); parser.add_argument('--folder')
    parser.add_argument('--commit'); parser.add_argument('--path')
    parser.add_argument('--minutes', type=int, default=2)
    parser.add_argument('--ssh-blocked', action='store_true', help='restart-confirming only: also cut management first')
    parser.add_argument('--saved', help='a saved folder of the repository checkout, for readback.py --saved')
    parser.add_argument('--evidence', required=True)
    args = parser.parse_args()
    manager = mr.Manager(args.url)
    try:
        record = SUBCOMMANDS[args.subcommand](args, manager)
    finally:
        if CURRENT_IP:
            unblock(CURRENT_IP)
            still = rule_present(CURRENT_IP)
            if still:
                # Never exit with a rule left behind: try once more, then say so loudly.
                unblock(CURRENT_IP)
                still = rule_present(CURRENT_IP)
            assert not still, 'IPTABLES RULE STILL PRESENT AFTER failure_harness.py EXIT for %s' % CURRENT_IP
    record['iptables_clean_at_exit'] = not (CURRENT_IP and rule_present(CURRENT_IP))
    with open(args.evidence, 'w') as handle:
        json.dump(record, handle, indent=1)
        handle.write('\n')
    print(json.dumps({k: record[k] for k in ('trigger', 'node', 'final_job') if k in record}, indent=1,
                     default=str)[:4000])
    final = (record.get('final_job') or {})
    return 0 if final.get('status') in mr.ENDED else 1


if __name__ == '__main__':
    sys.exit(main())
