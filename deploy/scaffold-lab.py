#!/usr/bin/env python3
"""Scaffold a lab's saved-state library in the connected Git repository.

Single-tenant course helper. It drives the local manager API (the same actions as the
buttons) to create the standard folder structure and to capture the running device
configuration into a named reference folder:

    python3 deploy/scaffold-lab.py init bgp-core
    python3 deploy/scaffold-lab.py snapshot bgp-core start

`init` registers ``<slug>/reference/{start,solution,broken-01}`` and ``<slug>/work`` and
points the lab's saves at ``<slug>/work``. `snapshot <slug> <state>` captures whatever the
node is running now, saves it (and its restore-grade candidate) into
``<slug>/reference/<state>``, pushes, and rebinds the lab to ``<slug>/work``.

Prerequisites: the lab is deployed and reachable, and it is already connected to the target
repository in the manager (More -> Git repository -> Connect by URL). See docs/NAMING.md and
deploy/lab-template/README.md.
"""
import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
import uuid

DEFAULT_MANAGER = 'http://127.0.0.1:8081'
DEFAULT_STATES = 'start,solution,broken-01'
NAME = re.compile(r'[a-z0-9][a-z0-9-]{0,62}')          # lab slug and state names
GIT_ACTIVE = {'queued', 'capturing', 'exporting', 'pushing'}


def api(manager, path, method='GET', body=None):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(manager.rstrip('/') + '/api' + path, data=data, method=method,
                                     headers={'Content-Type': 'application/json'} if data else {})
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            return response.status, json.loads(response.read().decode() or '{}')
    except urllib.error.HTTPError as error:
        try:
            detail = json.loads(error.read().decode() or '{}').get('detail', '')
        except Exception:
            detail = ''
        return error.code, {'detail': detail}
    except urllib.error.URLError as error:
        sys.exit('Cannot reach the manager at %s (%s). Is it running?' % (manager, error))


def die(message):
    sys.exit('scaffold-lab: ' + message)


def valid(name, what):
    if not NAME.fullmatch(name or ''):
        die('%s must be lowercase letters, numbers and hyphens: %r' % (what, name))


def find_lab(manager, want):
    status, state = api(manager, '/state')
    if status != 200:
        die('the manager did not return state (HTTP %s).' % status)
    labs = state.get('labs', [])
    if want:
        lab = next((l for l in labs if l['id'] == want or l['name'] == want), None)
        if not lab:
            die('no lab matches %r. Labs: %s' % (want, ', '.join(l['name'] for l in labs) or '(none)'))
        return lab
    if not labs:
        die('no lab found in the manager. Deploy the lab first.')
    if len(labs) > 1:
        die('more than one lab; pass --lab <name>. Labs: ' + ', '.join(l['name'] for l in labs))
    return labs[0]


def binding_id(manager, lab_id):
    status, git = api(manager, '/labs/%s/git' % lab_id)
    binding = (git or {}).get('binding')
    if not binding:
        die('the lab is not connected to a Git repository yet. Connect one in More -> Git repository.')
    return binding['binding_id']


def poll_git(manager, job_id, timeout=300):
    deadline = time.time() + timeout
    while time.time() < deadline:
        status, job = api(manager, '/git/jobs/%s' % job_id)
        if job.get('status') not in GIT_ACTIVE:
            return job
        time.sleep(2)
    die('timed out waiting for Git job %s.' % job_id)


def register_folder(manager, binding, prefix):
    status, result = api(manager, '/git/repositories/%s/folders' % binding, 'POST', {'prefix': prefix})
    if status == 200:
        return
    detail = (result.get('detail') or '').lower()
    if 'already' in detail or 'exist' in detail:
        return  # re-running init is safe
    die('could not create folder %s: %s' % (prefix, result.get('detail')))


def bind_to(manager, lab_id, prefix):
    status, result = api(manager, '/labs/%s/git/destination' % lab_id, 'POST', {'prefix': prefix, 'move_files': False})
    if status != 200:
        if 'already saves to that folder' in (result.get('detail') or '').lower():
            return  # the lab is already bound here; nothing to do
        die('could not point the lab at %s: %s' % (prefix, result.get('detail')))
    job = result.get('job')
    if job:
        poll_git(manager, job['id'])


def save_progress(manager, lab_id):
    status, job = api(manager, '/labs/%s/git/save' % lab_id, 'POST',
                      {'request_id': uuid.uuid4().hex, 'target': 'latest', 'push': True})
    if status != 200:
        die('save failed to start: %s' % job.get('detail'))
    return poll_git(manager, job['id'])


def cmd_init(args):
    valid(args.slug, 'lab slug')
    states = [s.strip() for s in args.states.split(',') if s.strip()]
    for state in states:
        valid(state, 'state name')
    lab = find_lab(args.manager, args.lab)
    binding = binding_id(args.manager, lab['id'])
    for state in states:
        register_folder(args.manager, binding, '%s/reference/%s' % (args.slug, state))
    register_folder(args.manager, binding, '%s/work' % args.slug)
    bind_to(args.manager, lab['id'], '%s/work' % args.slug)
    print('Created %s/reference/{%s} and %s/work.' % (args.slug, ','.join(states), args.slug))
    print('Lab "%s" now saves to %s/work.' % (lab['name'], args.slug))
    print('Next: configure the device to a state, then:')
    print('  python3 deploy/scaffold-lab.py snapshot %s %s' % (args.slug, states[0] if states else '<state>'))


def cmd_snapshot(args):
    valid(args.slug, 'lab slug')
    valid(args.state, 'state name')
    lab = find_lab(args.manager, args.lab)
    reference = '%s/reference/%s' % (args.slug, args.state)
    work = '%s/work' % args.slug
    bind_to(args.manager, lab['id'], reference)          # register + connect the reference folder
    final = save_progress(args.manager, lab['id'])       # capture the running config into it
    bind_to(args.manager, lab['id'], work)               # rebind so the student keeps saving in work
    status = final.get('status')
    if status not in ('synced', 'committed'):
        die('the snapshot into %s did not finish cleanly: %s (%s). The lab is rebound to %s.'
            % (reference, status, final.get('message', ''), work))
    where = 'pushed' if status == 'synced' else 'saved locally (not pushed)'
    print('Captured the running configuration into %s and %s. Lab rebound to %s.' % (reference, where, work))


def main(argv=None):
    parser = argparse.ArgumentParser(description='Scaffold a lab state library in the connected Git repository.')
    parser.add_argument('--manager', default=DEFAULT_MANAGER, help='manager base URL (default %(default)s)')
    parser.add_argument('--lab', default='', help='lab name or id (default: the only lab)')
    sub = parser.add_subparsers(dest='command', required=True)
    p_init = sub.add_parser('init', help='create the reference/{...} and work folders and bind saves to work')
    p_init.add_argument('slug')
    p_init.add_argument('--states', default=DEFAULT_STATES, help='comma-separated reference states (default %(default)s)')
    p_init.set_defaults(func=cmd_init)
    p_snap = sub.add_parser('snapshot', help='capture the running config into <slug>/reference/<state>')
    p_snap.add_argument('slug')
    p_snap.add_argument('state')
    p_snap.set_defaults(func=cmd_snapshot)
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == '__main__':
    main()
