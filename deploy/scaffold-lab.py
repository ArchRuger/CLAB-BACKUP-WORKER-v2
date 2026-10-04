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
``<slug>/reference/<state>``, asks the manager what an upload would send (the files of this
state and every other save that waits in the repository on the VM, which the upload carries
too), shows it and asks before it uploads (the manager uploads only what a review showed;
``--yes`` states that review for scripted use), and rebinds the lab to ``<slug>/work``.
Answering no leaves the state waiting on the lab VM: it shows as a save to upload in the lab
header and goes up with the next upload of the repository.

Prerequisites: the lab is deployed and reachable, and it is already connected to the target
repository in the manager (press Save in the lab header and paste its HTTPS address, or open Save settings from the chip). See docs/NAMING.md
and deploy/lab-template/README.md.
"""
import argparse
import http.client
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
DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))
GIT_ACTIVE = {'queued', 'capturing', 'exporting', 'pushing'}
GIT_REVIEWABLE = {'review_pending', 'committed', 'unchanged'}   # saved on the VM, upload not done yet
CHANGED_MEANWHILE = 'Another save was made in this repository'    # the manager's answer when the reviewed HEAD moved


class ManagerLost(SystemExit):
    """The manager gave no answer (down, restarting, reset or too slow). For a request that changes something
    this is not a refusal: the change may or may not have happened."""


def api(manager, path, method='GET', body=None):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(manager.rstrip('/') + '/api' + path, data=data, method=method,
                                     headers={'Content-Type': 'application/json'} if data else {})
    try:
        # The manager is on this VM: no proxy from the environment (http_proxy) may sit in between.
        with DIRECT.open(request, timeout=180) as response:
            return response.status, json.loads(response.read().decode() or '{}')
    except urllib.error.HTTPError as error:
        try:
            detail = json.loads(error.read().decode() or '{}').get('detail', '')
        except Exception:
            detail = ''
        return error.code, {'detail': detail}
    except (OSError, http.client.HTTPException) as error:
        # urllib wraps only the connect: RemoteDisconnected (the manager restarts mid-request), a read timeout and
        # a reset raised while the answer is read come out as they are. HTTPError is caught above (it is an OSError).
        raise ManagerLost('Cannot reach the manager at %s (%s). Is it running?' % (manager, error or type(error).__name__))


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
        die('the lab is not connected to a Git repository yet. Press Save in the lab header and connect one, or open Save settings from the chip.')
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
    """Point the lab's saves at `prefix`. A save that waits for upload does not stop this: it keeps its own
    destination and stays uploadable."""
    status, result = api(manager, '/labs/%s/git/destination' % lab_id, 'POST', {'prefix': prefix, 'move_files': False})
    if status != 200:
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


def review_of(manager, lab_id, job_id):
    """What an upload of this save sends, as the manager's review says it: the HEAD of the repository on the VM, the
    save the upload goes through and every other save it carries."""
    status, review = api(manager, '/labs/%s/git/compare' % lab_id, 'POST', {'job_id': job_id})
    if status != 200:
        die('could not read what an upload would send: %s' % (review.get('detail') or 'HTTP %s' % status))
    return review


def upload_reviewed(manager, job_id, review):
    """Upload what the person running this tool has just been shown: through the save the review names, with the
    HEAD the review showed. Returns (job, changed): `changed` when another save was made meanwhile, so the review
    shown is no longer what an upload would send and nothing was uploaded."""
    target = review.get('upload_job') or job_id
    status, job = api(manager, '/git/jobs/%s/retry' % target, 'POST', {'push': True, 'reviewed': True, 'head': review.get('head') or ''})
    if status != 200:
        detail = job.get('detail') or 'HTTP %s' % status
        return {'status': 'refused', 'message': detail}, status == 409 and CHANGED_MEANWHILE in detail
    carrier = poll_git(manager, job.get('id') or target)
    if (job.get('id') or target) == job_id:
        return carrier, False
    # The upload went through a newer save of the repository; this one was carried by it.
    status, own = api(manager, '/git/jobs/%s' % job_id)
    if carrier.get('status') != 'synced':
        return dict(own, status=carrier.get('status'), message=carrier.get('message', '')), False
    return own, False


def confirmed(job, review, reference, assume_yes):
    files = job.get('changed_files') or []
    print('Saved into %s on the lab VM (%s).' % (reference, (job.get('commit') or '')[:12] or 'no new commit'))
    for name in files[:40]:
        print('  ' + str(name))
    if len(files) > 40:
        print('  ... and %d more' % (len(files) - 40))
    if not files:
        print('  nothing changed since the previous save of this folder')
    for row in review.get('also_sends') or []:
        name = str(row.get('name') or '') or ('a save without a name' if row.get('job_id') else str(row.get('commit') or '')[:12])
        print('This upload also sends: ' + (str(row['lab']) + ': ' if row.get('lab') else '') + name)
    print('Configuration files may contain passwords or keys.')
    if assume_yes:
        return True
    return input('Upload this to the online repository now? [y/N] ').strip().lower() in ('y', 'yes')


def review_and_upload(manager, lab_id, job, reference, assume_yes):
    """Show the review, ask, upload. When another save was made between the review and the upload the manager uploads
    nothing: the review is shown and asked again (with --yes one more time, then the state stays on the lab VM).
    Returns (final job, where)."""
    again = 0
    while True:
        review = review_of(manager, lab_id, job['id'])
        if not confirmed(job, review, reference, assume_yes):
            return job, 'kept on the lab VM only (it waits there as a save to upload and goes up with the next upload of this repository)'
        final, changed = upload_reviewed(manager, job['id'], review)
        if not changed:
            # A refused upload leaves the save as it was: on the lab VM, waiting.
            return (dict(job, **final) if final.get('status') == 'refused' else final), ''
        again += 1
        if assume_yes and again > 1:
            return job, ('kept on the lab VM only: other saves kept being made in this repository, so nothing was uploaded '
                         '(it waits there as a save to upload)')
        print('Another save was made in this repository meanwhile. This is what an upload sends now:')


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


def say_where_it_saves(args, reference, reason, unsure):
    """Stop with `reason` and the way out when the lab is not known to be back on the work folder. `unsure` is for
    a folder change that was under way or whose answer was lost: it may or may not have happened."""
    if unsure:
        sys.exit('%s The lab MAY STILL SAVE TO %s. Check where it saves under Save settings in the lab header, '
                 'then run: scaffold-lab.py init %s' % (reason, reference, args.slug))
    sys.exit('%s The lab STILL SAVES TO %s. Run: scaffold-lab.py init %s' % (reason, reference, args.slug))


def rebind_or_say(args, lab, reference, work, reason, unsure=False):
    """A snapshot stopped after the lab was bound to `reference`: rebind it to `work` (a save that waits for upload
    does not stop that), then stop with `reason` and the truth about where the lab saves now.
    `unsure` is for a stop while the move to `reference` was itself under way: it may not have happened.
    A rebind whose answer was lost is unsure too: the lab may already be back on `work`."""
    try:
        bind_to(args.manager, lab['id'], work)
    except SystemExit as stop:
        say_where_it_saves(args, reference, '%s %s' % (reason, stop.code), unsure or isinstance(stop, ManagerLost))
    sys.exit('%s The lab is rebound to %s.' % (reason, work))


def cmd_snapshot(args):
    valid(args.slug, 'lab slug')
    valid(args.state, 'state name')
    lab = find_lab(args.manager, args.lab)
    reference = '%s/reference/%s' % (args.slug, args.state)
    work = '%s/work' % args.slug
    assume_yes = bool(getattr(args, 'yes', False))
    if not assume_yes and not sys.stdin.isatty():
        die('an upload needs your review. Run this in a terminal, or pass --yes to state that you reviewed it.')
    try:
        bind_to(args.manager, lab['id'], reference)      # register + connect the reference folder
    except KeyboardInterrupt:
        # Ctrl+C while the destination change is under way: the manager may already have pointed the lab at the
        # reference folder, so the same handling as every later stop (a refused or failed bind still just stops).
        rebind_or_say(args, lab, reference, work, 'scaffold-lab: stopped.', unsure=True)
    except ManagerLost as lost:
        # The answer to the destination change was lost: the lab may already be on the reference folder.
        rebind_or_say(args, lab, reference, work, lost.code, unsure=True)
    try:
        final = save_progress(args.manager, lab['id'])   # capture the running config into it
        status, where = final.get('status'), ''
        # The manager never uploads a save by itself: it uploads what a review showed, bound to the HEAD of the
        # repository on the VM at that review. So the review comes first, then the question, then the upload.
        if status in GIT_REVIEWABLE and not final.get('pushed'):
            final, where = review_and_upload(args.manager, lab['id'], final, reference, assume_yes)
            status = final.get('status')
    except SystemExit as stop:
        # The save failed to start or timed out, or its review could not be read, after the lab was pointed at the
        # reference folder: put it back where it was, or say plainly that it is still there.
        rebind_or_say(args, lab, reference, work, stop.code)
    except (KeyboardInterrupt, EOFError):
        # Ctrl+C, or the end of input at the upload question, after the lab was pointed at the reference folder.
        # A save that was made waits on the lab VM; nothing was uploaded.
        rebind_or_say(args, lab, reference, work, 'scaffold-lab: stopped.')
    if status == 'synced' or (status == 'unchanged' and final.get('pushed')):
        where = 'uploaded'
    waits = bool(final.get('commit')) and not final.get('pushed')
    try:
        bind_to(args.manager, lab['id'], work)           # rebind so the student keeps saving in work
    except SystemExit as stop:
        say_where_it_saves(args, reference, '%s The snapshot into %s itself is %s.'
                           % (stop.code, reference, where or ('saved on the lab VM, not uploaded' if waits else 'not finished (%s)' % status)),
                           isinstance(stop, ManagerLost))
    if not where and waits:
        die('the snapshot into %s is saved on the lab VM but was not uploaded: %s (%s). It waits there as a save to upload: '
            'upload it from the save status in the lab header. The lab is rebound to %s.'
            % (reference, status, final.get('message', ''), work))
    if not where:
        die('the snapshot into %s did not finish cleanly: %s (%s). The lab is rebound to %s.'
            % (reference, status, final.get('message', ''), work))
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
    p_snap.add_argument('--yes', action='store_true', help='upload without asking: states that you reviewed what this state contains')
    p_snap.set_defaults(func=cmd_snapshot)
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == '__main__':
    main()
