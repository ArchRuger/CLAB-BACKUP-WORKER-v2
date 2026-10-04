"""Capture immutable lab snapshots and publish them through an owner-scoped VM helper."""
import base64
import contextlib
import copy
import functools
import hashlib
import io
import json
import re
import socket
import threading
import time
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote

import paramiko
from fastapi import HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from . import __version__
from .discovery import PinnedHostKey, vm_password
from .downloads import component, short_name, stored_file, stored_path, stored_restore_path, topology_names
from .inventory import PLATFORMS
from .lab_operations import design_rechecking, operation_busy, scrub, GIT_BUSY
from .runner import now, trim_jobs
from .textdiff import unified

PROTOCOL = 'clab-manager-git-v1'
UNREGISTERED = 'Select a registered Git repository.'   # host_git.main() for a binding_id git.json no longer holds
MAX_PLANNED_FOLDERS = 200
MAX_FILE = 2 * 1024 * 1024
MAX_TOTAL = 16 * 1024 * 1024
MAX_WIRE = 24 * 1024 * 1024
FORMATS = {'juniper_cjunosevolved': 'junos-display-set', 'juniper_vqfx': 'junos-display-set',
           'juniper_vjunosswitch': 'junos-display-set', 'cisco_xrv9k': 'iosxr-running-config',
           'arista_ceos': 'eos-running-config'}
PUBLIC_JOB = ('id', 'lab_id', 'lab_name', 'created', 'finished', 'status', 'message', 'backup_job_id',
              'commit', 'pushed', 'target', 'checkpoint', 'changed_files', 'snapshot_path', 'note', 'review_before_push',
              'reviewed', 'destination', 'kind', 'generation_id')
# A save with a filename that changed between releases (Junos moved its human backup extension from
# `.set` to `.cfg`, `snapshot_suffix` above) still reads as one changed file to a person, never a
# removed-plus-added pair. Built from PLATFORMS so a future extension change stays covered without
# a new constant to remember: every `(old suffix, new suffix)` pair where a platform's storage suffix
# differs from its Git snapshot suffix.
SUFFIX_RENAMES = {(p['suffix'], p['snapshot_suffix']) for p in PLATFORMS.values()
                   if p.get('snapshot_suffix') and p['snapshot_suffix'] != p['suffix']}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def host_identity(host):
    return digest({k: host.get(k) for k in ('address', 'port', 'username', 'fingerprint')})


def public_job(job):
    return {k: copy.deepcopy(job[k]) for k in PUBLIC_JOB if k in job}


def strip_credentials(url):
    """A push URL for display: userinfo (`user:pass@` or a bare token before `@`) removed, everything
    else unchanged. `''` in, `''` out."""
    return re.sub(r'^(https?://)[^/@]*@', r'\1', str(url or ''))


def repository_display_name(repo):
    """The repository's own name for a person: the remote URL's last path segment without `.git`
    when a push URL is known (verified at least once), else the VM checkout folder's own name."""
    push_url = str(repo.get('push_url') or '').rstrip('/')
    if push_url:
        leaf = push_url.rsplit('/', 1)[-1]
        if leaf.endswith('.git'): leaf = leaf[:-4]
        if leaf: return leaf
    path = str(repo.get('path') or '').rstrip('/')
    return (path.rsplit('/', 1)[-1] if path else '') or repo.get('label') or 'repository'


def job_destination(binding, target, checkpoint=''):
    """Freeze where a save is going, from the binding as it is right now (rule: capture immutably at
    save time, never re-derive from a binding that may have moved since). `path` is the exact
    repository-relative folder this save writes to, in the binding's own casing."""
    repo = binding['repository']
    leaf = 'checkpoints/' + checkpoint if target == 'checkpoint' else target
    return dict(repository=repository_display_name(repo), remote=strip_credentials(repo.get('push_url', '')),
                branch=repo.get('branch', ''), path=repo_path(binding, leaf), checkout=repo.get('path', ''))


def move_destination(binding):
    """The destination row for a folder move: the whole lab folder the files move into, not a single
    snapshot leaf inside it."""
    repo = binding['repository']
    return dict(repository=repository_display_name(repo), remote=strip_credentials(repo.get('push_url', '')),
                branch=repo.get('branch', ''), path=repo.get('prefix', '') or '(repository root)', checkout=repo.get('path', ''))


def file_label(name):
    """The device-facing label of a saved file, its name without the extension Save progress gave it
    (`<label>.<suffix>`, `captured_snapshot`). Falls back to the whole name when there is no
    extension to strip."""
    name = str(name or '')
    return name.rsplit('.', 1)[0] if '.' in name else name


def pair_renamed_files(files):
    """The VM helper's `compare` mode (host_git.py) pairs saved files by name, so a device whose
    human backup extension changed between saves (rule: `SUFFIX_RENAMES`, Junos `.set` to `.cfg`)
    comes back as one file removed and a different one added rather than one changed file. Fold an
    unambiguous removed/added pair with a known suffix swap and a matching stem back into a single
    `changed` entry with a `renamed_from` name, so a person sees one real change, not two false
    ones. Ambiguous stems (more than one candidate) are left alone rather than guessed at."""
    removed = [f for f in files if f.get('status') == 'removed']
    added = [f for f in files if f.get('status') == 'added']

    def stem_suffix(name):
        name = str(name or '')
        return (name.rsplit('.', 1)[0], name.rsplit('.', 1)[1]) if '.' in name else (name, '')

    matches = {}
    for old in removed:
        old_stem, old_suffix = stem_suffix(old.get('name'))
        candidates = [new for new in added if stem_suffix(new.get('name')) == (old_stem, next((b for a, b in SUFFIX_RENAMES if a == old_suffix), None))]
        if len(candidates) == 1:
            matches[old['name']] = candidates[0]
    used_new = set()
    result = []
    for f in files:
        if f.get('status') == 'removed' and f['name'] in matches:
            new = matches[f['name']]
            if new['name'] in used_new: continue
            used_new.add(new['name'])
            result.append(dict(name=new['name'], status='changed', before=f.get('before', ''), after=new.get('after', ''),
                               renamed_from=f['name']))
            continue
        if f.get('status') == 'added' and f.get('name') in used_new:
            continue
        result.append(f)
    return sorted(result, key=lambda f: f.get('name', ''))


def annotated_compare(files):
    """Every file the compare route returns gets a real line diff and a human label, on top of the
    `name`/`status`/`before`/`after` it already carries."""
    files = pair_renamed_files(files)
    for f in files:
        f['diff'] = unified(f.get('before', ''), f.get('after', ''))
        f['label'] = file_label(f.get('name', ''))
    return files


def repo_path(binding, value):
    """The browser uses logical snapshot paths, never arbitrary repository paths."""
    prefix = binding['repository'].get('prefix', '').strip('/')
    if prefix and value.startswith(prefix + '/'): value = value[len(prefix) + 1:]
    if value not in ('latest', 'baseline') and not re.fullmatch(r'checkpoints/[A-Za-z0-9][A-Za-z0-9_-]{0,99}', value):
        raise HTTPException(400, 'Choose latest, baseline or a named checkpoint.')
    return (prefix + '/' if prefix else '') + value


SNAP_PART = re.compile(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,180}')


def version_label(path):
    """A human label for a saved-version folder: '<lab folder> · latest', or a checkpoint."""
    parts = [p for p in str(path or '').split('/') if p]
    if not parts: return 'repository root'
    if parts[-1] in ('latest', 'baseline'):
        folder, state = '/'.join(parts[:-1]), parts[-1]
    elif len(parts) >= 2 and parts[-2] == 'checkpoints':
        folder, state = '/'.join(parts[:-2]), 'checkpoint · ' + parts[-1]
    else:
        return '/'.join(parts)
    return (folder + ' · ' + state) if folder else state


def _exact_snapshot_path(value):
    """Segment-validate a repository-relative path (no `.`, `..` or `.git` segment); '' is the
    repository root and passes through unchanged."""
    if not value:
        return ''
    parts = value.split('/')
    if any(not SNAP_PART.fullmatch(part) or part in ('.', '..') or part.lower() == '.git' for part in parts):
        raise HTTPException(400, 'Choose a safe saved version path.')
    return value


def resolve_version_path(binding, value):
    """Three wire shapes (rule 5): (a) a value starting with '/' is an exact repository-relative
    path -- strip exactly one leading slash ('/' alone is the repository root, '' after
    stripping); (b) a bare 'latest', 'baseline' or 'checkpoints/<name>' keeps its pre-upgrade
    meaning, the lab's own folder (`repo_path`) -- compatibility for a page or tool built before
    this release, so a tab opened before the upgrade is not silently redirected to a root-level
    folder; (c) any other bare path (e.g. 'labs/x/latest', 'Final') is exact, the same as (a) once
    the leading slash is accounted for. Empty raises 400."""
    if not value:
        raise HTTPException(400, 'Choose a saved version.')
    if value.startswith('/'):
        return _exact_snapshot_path(value[1:])
    if value in ('latest', 'baseline') or re.fullmatch(r'checkpoints/[A-Za-z0-9][A-Za-z0-9_-]{0,99}', value):
        return repo_path(binding, value)
    return _exact_snapshot_path(value)


RESERVED_SNAPSHOT_NAMES = ('latest', 'baseline', 'checkpoints')


def base_folder(value):
    """Refuse a lab folder (a registration prefix) that is itself one of the snapshot folders Save
    progress writes inside a lab folder (rule 1): `latest`, `baseline`, `checkpoints` or
    `checkpoints/<name>`. Raises ValueError naming the parent lab folder those saves belong to;
    returns `value` unchanged when it is a safe lab folder."""
    parts = value.split('/') if value else []
    if not parts: return value
    is_checkpoint = len(parts) >= 2 and parts[-2] == 'checkpoints'
    if parts[-1] in RESERVED_SNAPSHOT_NAMES or is_checkpoint:
        parent = '/'.join(parts[:-2] if is_checkpoint else parts[:-1])
        where = (parent + '/latest') if parent else "the repository root's latest"
        raise ValueError('latest, baseline and checkpoints are the folders Save progress writes inside a lab '
                         'folder. Choose the folder above them: its saves go to ' + where + '.')
    return value


def snapshot_conflict(files, prefix):
    """The saved-configuration folder (holds manifest.json at HEAD) that `prefix` would sit at or
    below (rule 2): `prefix` itself or any ancestor, the repository root included. Checking the
    root as an ancestor only makes sense for a non-empty `prefix` (an empty prefix is the
    repository root itself, never "below" anything), so an empty `prefix` is never a conflict here.
    Returns the conflicting folder's exact path, or '' when there is none."""
    if not prefix: return ''
    files_at = {f.get('path') for f in files if isinstance(f, dict)}
    parts = prefix.split('/')
    for depth in range(len(parts), -1, -1):
        ancestor = '/'.join(parts[:depth])
        candidate = ancestor + '/manifest.json' if ancestor else 'manifest.json'
        if candidate in files_at:
            return ancestor
    return ''


def job_pending(job):
    """True while a Git save still needs attention: awaiting review, a retry, capture, export or
    push. Also used to protect an entry from ``_append_git_job``'s cap: a pending save is compared
    by digest later and must stay findable."""
    return (job.get('status') not in ('synced', 'dismissed', 'capture_incomplete', 'failed') and
            not (job.get('status') == 'unchanged' and job.get('pushed')))


def pending_progress(state, lab_id=None):
    return any((not lab_id or j.get('lab_id') == lab_id) and job_pending(j)
               for j in state.get('git_jobs', []))


def may_hold_commit(job):
    """Whether a save may have a commit in its VM checkout: one with a known commit, or one whose publication was sent and
    whose answer may have been lost after the VM committed (`published_attempt`, or the HEAD a save records right before it
    sends its publication, `expected_head`). A save that stopped before that (a capture a restart interrupted, an export
    that never reached the VM) has none: nothing of it is on the VM to review or to go along with an upload."""
    return bool(job.get('commit') or job.get('published_attempt') or 'expected_head' in job)


def awaits_review(job):
    """A save that holds, or may hold (`may_hold_commit`), a commit in the VM checkout that nobody reviewed: any pending
    save but a folder move (no configuration change of its own) and one whose review is recorded. A save without a known
    commit counts while its answer may have been lost after the VM committed."""
    return job_pending(job) and not job.get('reviewed') and job.get('target') not in ('move', 'update') and may_hold_commit(job)


def kept_on_vm(job):
    """A save dismissed with Keep snapshot only that may still have a commit in its VM checkout which no upload was seen
    carrying: one with a known commit, or one whose publication was sent and whose answer may have been lost (the VM may
    have committed it, exactly as in its pending form). It is no longer pending, but the next upload from that checkout
    sends such a commit along: the helper approves the journaled commits of every current registration of the checkout,
    whichever lab made them and whether that lab is still connected. Which checkout it belongs to is `made_in`'s
    question; the review counts it until an upload is verified to have carried it (`finish`), or to have put the
    checkout's HEAD on the remote (`settle_kept`: then nothing of it is left to go along)."""
    return (job.get('status') == 'dismissed' and not job.get('pushed') and job.get('target') != 'update'
            and not job.get('head_uploaded') and may_hold_commit(job))


def sibling_refusal(name, job, upload=False, reviewed=False):
    """Why a save, move or upload waits for another lab of the same checkout, and what the student does next. Keep
    snapshot only there also lets this go ahead, but it is no equivalent: the commit stays in the checkout and the next
    upload from it carries it (the review then counts and names it, see `kept_on_vm`)."""
    label = " ('" + str(job['note']) + "')" if job.get('note') else ''
    why = (('This upload could send it along. ' + ('Your review of this save is kept. ' if reviewed else '')) if upload else
           'Saving here now would put a new commit on top of it, and a later upload would send it unreviewed. ')
    return ('Another lab in this repository, ' + name + ', has a save waiting on the VM without a review' + label + '. ' + why +
            'Open ' + name + ' › Progress, review and upload that save, then ' + ('upload this one.' if upload else 'try again.') +
            ' Choosing Keep snapshot only there instead keeps its commit on the VM: it goes along with the next upload from this repository.')


GIT_JOB_CAP = 200


def _newest_pushed_ids(jobs):
    """The id of the newest 'git_jobs' entry with `pushed=True`, per `binding_digest`. finish()'s
    'unchanged' detection compares a fresh commit against exactly this entry (same commit, same
    pushed, same binding): trimming it away makes that comparison find nothing and fall back to
    'review_pending' even though the save truly changed nothing."""
    newest = {}
    for j in jobs:
        if j.get('pushed') is True: newest[j.get('binding_digest')] = j.get('id')
    return set(newest.values())


def _append_git_job(state, job):
    """Append one entry to 'git_jobs' and cap it at the newest 200, never dropping one
    ``job_pending`` still calls true, nor the newest pushed save of any binding (see
    ``_newest_pushed_ids``, ``trim_jobs``), nor a kept save the review must still count (``kept_on_vm``; one an upload
    settled, ``finish`` and ``settle_kept``, may go like any finished save)."""
    state['git_jobs'].append(job)
    keep = _newest_pushed_ids(state['git_jobs'])
    state['git_jobs'] = trim_jobs(state['git_jobs'], GIT_JOB_CAP, lambda j: job_pending(j) or j.get('id') in keep or kept_on_vm(j), False)


def remote_git(host, request, stopping=None):
    """No shell, no credential forwarding; large artifacts travel only on this channel."""
    if not host.get('enabled') or not host.get('fingerprint'):
        raise ValueError('Connect the VM and verify its SSH host fingerprint first.')
    payload = (json.dumps(request, separators=(',', ':')) + '\n').encode()
    if len(payload) > MAX_WIRE: raise ValueError('Git snapshot exceeds the transfer limit.')
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(PinnedHostKey(host['fingerprint']))
    try:
        client.connect(hostname=host['address'], port=host['port'], username=host['username'],
                       password=vm_password(host), allow_agent=False, look_for_keys=False,
                       timeout=8, auth_timeout=8, banner_timeout=8)
        client.get_transport().set_keepalive(15)
        channel = client.get_transport().open_session(timeout=8)
        channel.settimeout(30)
        channel.exec_command('clab-manager-git')
        channel.sendall(payload); channel.shutdown_write()
        channel.settimeout(.2)
        data = bytearray(); until = time.monotonic() + 600; total = 0; eof = False
        while True:
            if time.monotonic() > until or (stopping and stopping.is_set()):
                raise ValueError('Git connection interrupted. Retry this saved operation to reconcile its result.')
            if channel.recv_stderr_ready(): total += len(channel.recv_stderr(65536))
            if total > MAX_WIRE: raise ValueError('Git helper response exceeded its limit.')
            if not eof:
                try: chunk = channel.recv(65536)
                except socket.timeout: continue
                eof = not chunk
                data.extend(chunk); total += len(chunk)
            if total > MAX_WIRE: raise ValueError('Git helper response exceeded its limit.')
            # Exit status can precede the last stdout packets; only stream EOF
            # proves the multi-megabyte envelope is complete.
            if eof and not channel.recv_stderr_ready() and channel.exit_status_ready(): break
            if eof: time.sleep(.03)
        try: envelope = json.loads(data)
        except (ValueError, UnicodeError): raise ValueError('Install or refresh the matching Git helper on the VM.')
        if not isinstance(envelope, dict): raise ValueError('Invalid Git helper response.')
        if 'error' in envelope: raise ValueError(str(envelope['error'])[:600])
        if channel.recv_exit_status() or not isinstance(envelope.get('result'), dict):
            raise ValueError('Git helper is unavailable. Run setup-git.sh on the VM.')
        return envelope['result']
    finally:
        client.close()


def captured_snapshot(store, backup, context=None, embedded_files=True, complete=True):
    """`complete=False` keeps only the devices whose file was captured and skips the scope check. It is for loading the
    automatic backup of a load back (a device whose safety backup failed was never changed by that load); a Git save
    always passes the strict default, so an older configuration is never saved in place of a device that failed."""
    if backup.get('operation') != 'backup' or backup.get('status') not in ('succeeded', 'partial'):
        raise ValueError('Choose a completed configuration capture.')
    nodes = backup.get('nodes', [])
    if not complete: nodes = [n for n in nodes if n.get('status') == 'succeeded']
    if not nodes or len(nodes) > 500 or any(n.get('status') != 'succeeded' for n in nodes):
        raise ValueError('Capture incomplete. Every included device must have a successful file; latest is unchanged.')
    if len({n.get('name') for n in nodes}) != len(nodes): raise ValueError('Capture has ambiguous device identities.')
    context = context or backup.get('progress_context') or {}
    expected = context.get('node_names')
    if complete and expected and set(expected) != {n['name'] for n in nodes}:
        raise ValueError('Capture device scope changed; save a new progress snapshot.')
    names = {}; files = {}; rows = []; total = 0
    for node in sorted(nodes, key=lambda n: n['name']):
        platform = node.get('platform')
        if platform not in FORMATS: raise ValueError('Capture is missing supported configuration-format metadata.')
        path = stored_path(store, backup, node)
        if path is None: raise ValueError('A captured file is missing or unsafe. The repository was not changed.')
        with path.open('rb') as stream: raw = stream.read(MAX_FILE + 1)
        total += len(raw)
        if not raw or len(raw) > MAX_FILE or total > MAX_TOTAL:
            raise ValueError('Use nonempty configs up to 2 MiB each and 16 MiB per snapshot.')
        try: raw.decode('utf-8')
        except UnicodeError: raise ValueError('Captured configuration is not valid UTF-8 text.')
        # Integrity: the runner records a digest when it stores a capture (captures older than that carry
        # none and are taken as they are). A stored file that no longer matches is never saved or applied.
        if node.get('sha256') and hashlib.sha256(raw).hexdigest() != node['sha256']:
            raise ValueError('A stored capture no longer matches the digest recorded when it was taken. Take a new backup.')
        # Whole-device restore candidate captured beside the backup (restore-capable platforms).
        restore_raw = None
        rpath = stored_restore_path(store, backup, node)
        if rpath is not None:
            with rpath.open('rb') as stream: restore_raw = stream.read(MAX_FILE + 1)
            total += len(restore_raw)
            if not restore_raw or len(restore_raw) > MAX_FILE or total > MAX_TOTAL:
                raise ValueError('Use nonempty configs up to 2 MiB each and 16 MiB per snapshot.')
            try: restore_raw.decode('utf-8')
            except UnicodeError: raise ValueError('Captured restore candidate is not valid UTF-8 text.')
            if node.get('restore_sha256') and hashlib.sha256(restore_raw).hexdigest() != node['restore_sha256']:
                raise ValueError('A stored restore candidate no longer matches the digest recorded when it was taken. Take a new backup.')
        label = component(short_name(node, backup.get('lab_name', '')))
        # The Git snapshot's human-facing file uses its own extension, `snapshot_suffix` when a
        # platform sets one (Junos: `.cfg`, matching EOS and IOS XR there), never the internal
        # capture storage extension (`suffix`, read by runner.py and unaffected by this).
        suffix = PLATFORMS[platform].get('snapshot_suffix') or PLATFORMS[platform]['suffix']
        name = f'{label}.{suffix}'
        names.setdefault(name.casefold(), []).append(node['name'])
        rows.append((node, name, raw, restore_raw))
    metadata = []
    restore_capable = 0
    for node, name, raw, restore_raw in rows:
        if len(names[name.casefold()]) > 1:
            base, suffix = name.rsplit('.', 1)
            name = f'{base}-{hashlib.sha256(node["name"].encode()).hexdigest()[:12]}.{suffix}'
        if name.casefold() == 'manifest.json' or name in files: raise ValueError('Capture filenames collide.')
        files[name] = base64.b64encode(raw).decode('ascii')
        entry = dict(path=name, size=len(raw), sha256=hashlib.sha256(raw).hexdigest(),
                     node=node['name'], short_name=node.get('short_name', ''),
                     platform=node['platform'], format=FORMATS[node['platform']])
        if restore_raw is not None:
            rsuffix = PLATFORMS[node['platform']].get('restore_suffix', 'restore')
            rname = name.rsplit('.', 1)[0] + '.' + rsuffix
            if rname.casefold() == 'manifest.json' or rname in files: raise ValueError('Capture filenames collide.')
            files[rname] = base64.b64encode(restore_raw).decode('ascii')
            entry.update(restore_artifact=rname, restore_size=len(restore_raw),
                         restore_sha256=hashlib.sha256(restore_raw).hexdigest(),
                         restore_format=PLATFORMS[node['platform']].get('restore_format', ''),
                         restore_capable=True)
            restore_capable += 1
        metadata.append(entry)
    # The topology and map the backup embedded travel with the save as entries of their own kind (no `node`:
    # restore and the device pairing leave them alone, the helper does not count them as devices). The manifest's
    # topology digest is then the embedded file's own, provenance `embedded`; older captures keep the digest of
    # the manager's copy at save time (`captured`) or none (`unknown`).
    topology_digest = context.get('topology_digest'); provenance = 'captured' if topology_digest else 'unknown'
    embedded = backup.get('topology') if isinstance(backup.get('topology'), dict) else {}
    if embedded_files and embedded.get('file'):
        extra_names = topology_names(backup)
        for key, field, sha_field in (('topology', 'file', 'sha256'), ('annotations', 'annotations_file', 'annotations_sha256')):
            if not embedded.get(field): continue
            path = stored_file(store, backup, embedded[field])
            if path is None: raise ValueError('The topology embedded with this capture is missing or unsafe. The repository was not changed.')
            with path.open('rb') as stream: raw = stream.read(MAX_FILE + 1)
            total += len(raw)
            if not raw or len(raw) > MAX_FILE or total > MAX_TOTAL:
                raise ValueError('Use nonempty configs up to 2 MiB each and 16 MiB per snapshot.')
            try: raw.decode('utf-8')
            except UnicodeError: raise ValueError('The embedded topology is not valid UTF-8 text.')
            if embedded.get(sha_field) and hashlib.sha256(raw).hexdigest() != embedded[sha_field]:
                raise ValueError('The embedded topology no longer matches the digest recorded when it was taken. Take a new backup.')
            name = extra_names[key]
            if name.casefold() == 'manifest.json' or name in files or name.casefold() in names: raise ValueError('Capture filenames collide.')
            files[name] = base64.b64encode(raw).decode('ascii')
            # Stable fields only: the time the file was read stays on the backup record, because an unchanged save
            # is told from the manifest's content digest and a time that moves with every discovery pass would make
            # every save a new commit.
            metadata.append(dict(path=name, size=len(raw), sha256=hashlib.sha256(raw).hexdigest(), kind=key,
                                 source=str(embedded.get('annotations_source') or embedded.get('source', '')) if key == 'annotations' else str(embedded.get('source', '')),
                                 vm_path=str(embedded.get('path', ''))))
            if key == 'topology': topology_digest = hashlib.sha256(raw).hexdigest(); provenance = 'embedded'
    manifest = dict(schema=2, lab_id=backup['lab_id'], lab_name=backup.get('lab_name', ''),
                    backup_job_id=backup['id'], captured_at=backup.get('finished', backup.get('created')),
                    topology_digest=topology_digest, topology_provenance=provenance,
                    node_names=sorted(n['name'] for n in nodes), excluded_nodes=context.get('excluded_nodes', []),
                    restore_capable_nodes=restore_capable, files=metadata)
    return dict(manifest=manifest, files=files)


def decoded_snapshot(result):
    snapshot = result.get('snapshot')
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get('manifest'), dict) or not isinstance(snapshot.get('files'), dict):
        raise ValueError('The saved version has no supported snapshot manifest.')
    rows = snapshot['manifest'].get('files', [])
    if not isinstance(rows, list) or not rows or len(rows) > 500: raise ValueError('Invalid version manifest.')
    files = {}; total = 0

    def take(name, size, sha):
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,180}', name) or name.lower() == 'manifest.json':
            raise ValueError('Version contains an unsafe filename.')
        if name in files: raise ValueError('Version contains duplicate files.')
        try: raw = base64.b64decode(snapshot['files'][name], validate=True)
        except (KeyError, ValueError, TypeError): raise ValueError('Invalid version file encoding.')
        nonlocal total; total += len(raw)
        if len(raw) > MAX_FILE or total > MAX_TOTAL or size != len(raw) or sha != hashlib.sha256(raw).hexdigest():
            raise ValueError('Version integrity check failed.')
        try: raw.decode('utf-8')
        except UnicodeError: raise ValueError('Version configuration is not UTF-8 text.')
        files[name] = raw

    for item in rows:
        if not isinstance(item, dict): raise ValueError('Invalid version manifest.')
        take(item.get('path', ''), item.get('size'), item.get('sha256'))
        # Restore-grade candidate (schema 2+): validated the same way and kept in files.
        if item.get('restore_artifact'):
            take(item['restore_artifact'], item.get('restore_size'), item.get('restore_sha256'))
    if set(files) != set(snapshot['files']): raise ValueError('Version files do not match the manifest.')
    return snapshot['manifest'], files


def _node_slots(manifest, files):
    """Map each saved node to its current human file and restore artifact, `(path, bytes)` each,
    keyed by the manifest's `node` identity rather than by filename: an older save's human file can
    carry a different extension than a fresh one (Junos moved from `.set` to `.cfg`), and the two
    must still be found as the same node's file."""
    slots = {}
    for entry in manifest.get('files', []):
        # A device by its name; the embedded topology and map by their kind, so a compare shows their changes too.
        node = entry.get('node') or ('file:' + str(entry['kind']) if entry.get('kind') else None)
        if not node: continue
        slot = slots.setdefault(node, {})
        slot['config'] = (entry.get('path', ''), files.get(entry.get('path', '')))
        if entry.get('restore_artifact'):
            slot['restore'] = (entry['restore_artifact'], files.get(entry['restore_artifact']))
    return slots


def snapshot_diff(before_manifest, before_files, after_manifest, after_files):
    """Pair two saved snapshots by manifest node, never by filename, so a device whose human backup
    extension changed between saves (Junos `.set` to `.cfg`) still compares as one changed file
    rather than a removed file plus an added one. Returns the same shape the compare route always
    has: a list of `{name, status, before, after}`, sorted by name."""
    before_slots = _node_slots(before_manifest, before_files)
    after_slots = _node_slots(after_manifest, after_files)
    result = []
    for node in before_slots.keys() | after_slots.keys():
        b = before_slots.get(node, {}); a = after_slots.get(node, {})
        for kind in ('config', 'restore'):
            b_path, b_raw = b.get(kind, ('', None))
            a_path, a_raw = a.get(kind, ('', None))
            if b_raw is None and a_raw is None: continue
            if b_raw == a_raw and b_path == a_path: continue
            status = 'added' if b_raw is None else 'removed' if a_raw is None else 'changed'
            result.append(dict(name=a_path or b_path, status=status,
                               before=b_raw.decode('utf-8') if b_raw is not None else '',
                               after=a_raw.decode('utf-8') if a_raw is not None else ''))
    return sorted(result, key=lambda f: f['name'])


class GitProgress:
    designs = None   # set by main.py: the NetworkDesign service, for design exports (kind `design`)

    def __init__(self, store, runner):
        self.store = store; self.runner = runner; self.stopping = threading.Event()
        # One helper call at a time from this manager: the helper takes a non-blocking lock per repository, and a page
        # reading the history while a save publishes would otherwise turn the save into "already running" (seen live).
        self.helper_lock = threading.Lock()
        # One change of a lab's repository connection at a time: a folder change checks everything before the VM
        # retires the old registration, and no other connection may take the new folder in between.
        self.binding_lock = threading.Lock()
        self.rebinding = None   # the lab whose connection is being changed while `binding_lock` is held (`changing`)
        self.pool = ThreadPoolExecutor(max_workers=1)
        with store.lock:
            for job in store.state.setdefault('git_jobs', []):
                child = next((b for b in store.state['jobs'] if b.get('progress_id') == job['id']), None)
                if child and not job.get('backup_job_id'):
                    job['backup_job_id'] = child['id']
                    if job['status'] == 'failed': job['status'] = 'interrupted'
                if job['status'] in GIT_BUSY:
                    if job.get('target') == 'update':
                        job.update(status='dismissed', message='Repository update interrupted. Check repository status before updating again.')
                        continue
                    job.update(status='interrupted', message='Manager restarted. Retry to reconcile the saved capture and Git result.')
            store.save()

    def close(self):
        self.stopping.set(); self.pool.shutdown(wait=False, cancel_futures=True)

    def invoke(self, request, binding=None):
        with self.store.lock:
            host = copy.deepcopy(self.store.state.get('host', {}))
        if binding:
            if binding.get('host_identity') != host_identity(host):
                raise ValueError('The VM identity changed. Return to the original VM or reconnect the repository.')
            request = dict(request, binding_id=binding['binding_id'], revision=binding['revision'])
        try:
            with self.helper_lock: return remote_git(host, request, self.stopping)
        except ValueError as exc:
            with self.store.lock: message = scrub(str(exc), self.store.state)
            raise ValueError(message[:600])
        except Exception:
            raise ValueError('Cannot reach the VM Git helper. The local capture is retained; check VM setup and retry.')

    def repositories(self):
        result = self.invoke({'mode': 'list'})
        if result.get('protocol') != PROTOCOL or result.get('version') != __version__:
            raise ValueError('Update the VM Git helper to match manager ' + __version__ + ' using setup-git.sh --refresh.')
        if not isinstance(result.get('repositories'), list): raise ValueError('Invalid repository list.')
        return result

    def binding(self, lab_id):
        lab = self.store.lab(lab_id)
        if not lab: raise HTTPException(404, 'Lab not found.')
        if not lab.get('git_binding'): raise HTTPException(409, 'Connect this lab to a Git repository first.')
        return copy.deepcopy(lab['git_binding'])

    def reader(self, lab_id, repository=''):
        """The binding to read a repository with: the lab's own, or, for a lab without a save location or for another
        repository of the connected VM, the registration `repository` once the helper's own list names it. Read-only
        callers only (the saved states of a repository, a state to load); a save always uses a binding of its own."""
        with self.store.lock:
            lab = self.store.lab(lab_id)
            if not lab: raise HTTPException(404, 'Lab not found.')
            own = copy.deepcopy(lab.get('git_binding'))
            host = host_identity(self.store.state.get('host', {}))
        if not repository:
            if not own: raise HTTPException(409, 'Connect this lab to a Git repository first.')
            return own
        if own and own.get('binding_id') == repository: return own
        try: catalog = self.repositories()['repositories']
        except ValueError as exc: raise HTTPException(409, str(exc))
        repo = next((r for r in catalog if isinstance(r, dict) and r.get('id') == repository), None)
        if not repo: raise HTTPException(404, 'This repository is not registered on the VM. Refresh the list.')
        return dict(binding_id=repo['id'], revision=repo['revision'], repository=repo, host_identity=host)

    def idle(self, lab_id=None):
        # A network-design apply read back after a restart holds its own lab only, so `operation_busy` without a lab does not
        # see it, and the Runner would refuse the capture of a save there: work of that lab waits here, saying why (L-15).
        if lab_id and design_rechecking(self.store.state, lab_id):
            raise HTTPException(409, "The manager is still reading this lab's devices back after a restart (a network design "
                                     'was being applied to them). Try again once that check has finished.')
        if operation_busy(self.store.state) or any(j['status'] in ('queued', 'running') for j in self.store.state['jobs']):
            raise HTTPException(409, 'Wait for the active backup, Git save or lab operation to finish.')
        if self.store.reset_pending: raise HTTPException(409, 'Finish the storage reset first.')

    def guard_pending(self, lab_id=None):
        if pending_progress(self.store.state, lab_id):
            raise HTTPException(409, 'Finish pending Git saves, or choose Keep snapshot only in Git history before continuing.')

    def checkout_labs(self, lab_id):
        """The other labs bound to a folder of this lab's VM checkout (one repository can hold several labs). Their
        commits are in the one branch history every one of them pushes."""
        binding = (self.store.lab(lab_id) or {}).get('git_binding') or {}
        path = binding.get('repository', {}).get('path')
        if not path: return {}
        return {lab['id']: lab for lab in self.store.state['labs'] if lab['id'] != lab_id and lab.get('git_binding')
                and lab['git_binding'].get('repository', {}).get('path') == path
                and lab['git_binding'].get('host_identity') == binding.get('host_identity')}

    def unreviewed_sibling(self, lab_id, commitless=False):
        """(lab, save) of another lab of this checkout whose save still awaits its review, else (None, None).
        The review before every upload holds per checkout: a commit made on top of such a save, and any push
        from this checkout, would carry it. Refusing new commits while one exists stops the stacking at its
        source; refusing uploads covers saves stacked before that rule. Neither can deadlock: an upload that
        is refused keeps its review, so it no longer holds the other lab; and a retry without a commit of its
        own (`commitless`, it only saves on the VM) is held only by a save that has a commit, so two labs whose
        saves both lack one (an older release could leave that) never refuse each other: the first retry reaches
        its review, and the uploads then wait for each other's review as above."""
        labs = self.checkout_labs(lab_id)
        held = next((j for j in self.store.state['git_jobs'] if j.get('lab_id') in labs and awaits_review(j)
                     and (j.get('commit') or not commitless)), None)
        return (labs[held['lab_id']], held) if held else (None, None)

    def guard_siblings(self, lab_id):
        lab, held = self.unreviewed_sibling(lab_id)
        if held: raise HTTPException(409, sibling_refusal(lab['name'], held))

    @contextlib.contextmanager
    def changing(self, lab_id):
        """One change of a repository connection at a time (`binding_lock`), recorded with the lab it changes: a folder
        change checks everything before the VM retires the old registration, and nothing may take the new one meanwhile.
        Saves and design exports of that lab wait for it (`refuse_while_rebinding`); other labs' work goes on."""
        if not self.binding_lock.acquire(blocking=False):
            raise HTTPException(409, 'Another repository connection is being changed. Try again in a moment.')
        self.rebinding = lab_id
        try: yield
        finally:
            self.rebinding = None; self.binding_lock.release()

    def made_in(self, job, binding):
        """Whether a save was made in the VM checkout `binding` points into: the same checkout folder on the same VM, as
        the save froze them when it was made. A save of an older release froze no VM (it is taken to be on its lab's
        VM, else this one), and the oldest froze no folder either (then only its lab's current binding can tell)."""
        bound = (self.store.lab(job.get('lab_id')) or {}).get('git_binding') or {}
        host = job.get('host_identity') or bound.get('host_identity') or binding['host_identity']
        where = (job.get('destination') or {}).get('checkout') or bound.get('repository', {}).get('path')
        return host == binding['host_identity'] and bool(where) and where == binding['repository'].get('path')

    def same_branch(self, job, binding):
        """Whether a save of this checkout (`made_in`) was made for the push URL and branch `binding` pushes, as the save
        froze them (an older save that froze nothing: as its lab's current binding says). The helper approves a journaled
        commit for a push only from a registration of the same checkout, push URL and branch."""
        frozen = job.get('destination') or {}
        if not frozen:
            bound = ((self.store.lab(job.get('lab_id')) or {}).get('git_binding') or {}).get('repository') or {}
            frozen = dict(remote=strip_credentials(bound.get('push_url', '')), branch=bound.get('branch', ''))
        repo = binding['repository']
        return frozen.get('branch') == repo.get('branch', '') and frozen.get('remote') == strip_credentials(repo.get('push_url', ''))

    def kept_saves(self, job, binding):
        """The saves kept with Keep snapshot only in the checkout `binding` points into (`kept_on_vm`, `made_in`) whose commit
        an upload of `job` may carry along, oldest first: all but `job` itself and a kept save that changed nothing and only
        reused the very commit `job` uploads (no changed file of its own: it holds nothing that `job`'s review does not
        show). A kept save that made the commit `job` only reuses (`job` changed nothing, the helper answered with the
        checkout's HEAD) is named: the review of `job` shows no difference of its own, while the upload sends that commit."""
        return [j for j in self.store.state['git_jobs'] if j['id'] != job['id'] and kept_on_vm(j) and self.made_in(j, binding)
                and not (j.get('commit') and j.get('commit') == job.get('commit') and not j.get('changed_files'))]

    def kept_names(self, kept):
        """Each kept save as the review names it: its lab (as the manager knows it now, else as the save froze it) and note."""
        return [dict(lab=(self.store.lab(j['lab_id']) or {}).get('name') or j.get('lab_name') or '', note=str(j.get('note') or ''))
                for j in kept]

    def kept_refusal(self, kept):
        """Why a folder move waits for its review: the saves kept with Keep snapshot only that its upload would send along."""
        named = ', '.join(k['lab'] + (" ('" + k['note'] + "')" if k['note'] else '') for k in self.kept_names(kept))
        return ('Its upload would also send ' + ('a save' if len(kept) == 1 else str(len(kept)) + ' saves') + ' kept with Keep '
                'snapshot only that ' + ('was' if len(kept) == 1 else 'were') + ' not seen uploaded yet: ' + named + '. Open this '
                'move under Progress › Recent saves and choose Review and upload…: the review names ' +
                ('it' if len(kept) == 1 else 'them') + ' before anything is uploaded.')

    def settle_kept(self, job, commit):
        """Give the kept saves of this checkout that a verified upload did not name an end. The helper names
        (`synced_operations`) only saves it journaled with a verified commit, so one whose publication the VM refused, or
        whose commit it never verified, was counted in every later review and kept beyond the jobs cap, for good. Once the
        checkout's HEAD is this uploaded commit, its whole branch is on the remote: a commit such a save made there (the
        helper commits only on the registered branch and only ever moves it forward) is on the remote already, or there is
        none, so nothing of it is left to go along (a commit the owner moved off the branch by hand, outside the manager,
        goes along again only if the owner puts it back). Recorded privately (`head_uploaded`), never as `pushed`: the
        manager did not see an upload carry it. Only saves of the same checkout, push URL and branch, chosen before the
        check (their publications ended before this upload: one worker, one helper call at a time, and the VM's lock per
        checkout refuses the check while an interrupted one still runs there). A HEAD that is not this commit (newer
        commits on top of an older save's upload) or a check that fails settles nothing; the upload stands."""
        with self.store.lock:
            where = copy.deepcopy((self.store.lab(job['lab_id']) or {}).get('git_binding'))
            open_ = {j['id'] for j in self.store.state['git_jobs'] if where and kept_on_vm(j) and self.made_in(j, where) and self.same_branch(j, where)}
        if not open_ or not commit: return
        try: head = self.invoke({'mode': 'status'}, where).get('head')
        except ValueError: return
        if head != commit: return
        with self.store.lock:
            settled = [j for j in self.store.state['git_jobs'] if j['id'] in open_ and kept_on_vm(j)]
            for previous in settled: previous['head_uploaded'] = True
            try: self.store.save()
            except OSError:
                for previous in settled: previous.pop('head_uploaded', None)

    def get_job(self, job_id):
        job = next((j for j in self.store.state['git_jobs'] if j['id'] == job_id), None)
        if not job: raise HTTPException(404, 'Git save not found.')
        return job

    def update(self, job_id, **fields):
        with self.store.lock:
            job = self.get_job(job_id); old = copy.deepcopy(job)
            job.update(fields)
            try: self.store.save()
            except OSError:
                job.clear(); job.update(old); raise

    def schedule(self, job):
        try: self.pool.submit(self.execute, job['id'])
        except RuntimeError:
            self.update(job['id'], status='interrupted', message='Manager is stopping. Retry after restarting.')
        return public_job(job)

    def execute(self, job_id):
        result = None
        try:
            with self.store.lock:
                job = copy.deepcopy(self.get_job(job_id))
                binding = self.binding(job['lab_id'])
                if digest(binding) != job['binding_digest']: raise ValueError('Repository settings changed; this save was not sent.')
            # A retry with a commit never recaptures or rewrites working files.
            if job.get('commit'):
                if job.get('retry_push'):
                    self.update(job_id, status='pushing', message='Pushing the saved commit.')
                    result = self.invoke({'mode': 'push', 'operation_id': job_id}, binding)
                else:
                    result = dict(status='committed', commit=job['commit'], pushed=False,
                                  changed_files=job.get('changed_files', []), snapshot_path=job.get('snapshot_path', ''))
                self.finish(job, result)
                return
            if job.get('target') == 'move':
                # Attempted from here on: whatever stops the move (a repository that needs attention, an answer lost
                # after the VM committed) leaves it retryable, never failed; the helper's move journal makes the
                # retry idempotent.
                self.update(job_id, status='exporting', published_attempt=True, message='Moving the saved folders inside the repository.')
                status = self.invoke({'mode': 'status'}, binding)
                if not status.get('ready'): raise ValueError(status.get('problem') or 'Repository needs attention before moving folders.')
                request = copy.deepcopy(job['request'])
                request.update(mode='move', operation_id=job_id, expected_head=status.get('head', ''))
                result = self.invoke(request, binding)
                if result.get('commit'):
                    self.update(job_id, commit=result['commit'], changed_files=result.get('changed_files', []), snapshot_path=result.get('snapshot_path', ''))
                if (job.get('retry_push', job.get('want_push')) and result.get('commit') and result.get('status') != 'needs_attention'
                        and not result.get('pushed')):
                    # The push would carry every commit below the move, so it waits while another lab of this
                    # checkout has a save that was never reviewed; the move stays on the VM, uploadable later.
                    with self.store.lock:
                        other, held = self.unreviewed_sibling(job['lab_id'])
                        # A save kept with Keep snapshot only in this checkout no longer holds anything, but this push would
                        # carry its commit with nothing naming it: the move waits for a review that names it (`kept_saves`).
                        kept = [] if held or job.get('reviewed') else self.kept_saves(dict(job, commit=result['commit']), binding)
                    if held:
                        result = dict(result, message='Moved on this VM, not uploaded: ' + sibling_refusal(other['name'], held, upload=True))
                    elif kept:
                        self.update(job_id, review_before_push=True)
                        result = dict(result, message='Moved on this VM, not uploaded. ' + self.kept_refusal(kept))
                    else:
                        self.update(job_id, status='pushing', commit=result['commit'], message='Pushing the moved folders.')
                        result = self.invoke({'mode': 'push', 'operation_id': job_id}, binding)
                self.finish(job, result)
                return
            if job.get('kind') == 'design':
                # A design export: the plan's files instead of a capture; the same review, publication and push.
                with self.store.lock:
                    lab = copy.deepcopy(self.store.lab(job['lab_id']))
                    generation = next((g for g in (lab or {}).get('network_generations', []) if g['id'] == job.get('generation_id')), None)
                if not lab or not generation or self.designs is None:
                    raise ValueError('The plan of this export is gone; dismiss this export, generate the plan again and start a new one.')
                try: snapshot = self.designs.design_snapshot(lab, generation, lab_name=job.get('lab_name'), bound=job.get('snapshot_digest'))
                except ValueError as exc:
                    if job.get('published_attempt'): raise   # the VM may hold the commit: stay pending, never failed
                    self.update(job_id, status='failed', message=str(exc), finished=now()); return
                fingerprint = digest(snapshot)
                if job.get('snapshot_digest') and fingerprint != job['snapshot_digest']:
                    raise ValueError('The plan changed since this export was started. It will not replace the repository snapshot.')
                self.update(job_id, status='exporting', snapshot_digest=fingerprint, message='Saving the plan to the VM repository.')
                request = copy.deepcopy(job['request'])
                if 'expected_head' not in job:
                    status = self.invoke({'mode': 'status'}, binding)
                    if not status.get('ready'): raise ValueError(status.get('problem') or 'Repository needs attention before exporting.')
                    expected_head = status.get('head', '')
                    self.update(job_id, expected_head=expected_head)
                else: expected_head = job['expected_head']
                request.update(mode='publish', operation_id=job_id, expected_head=expected_head, snapshot=snapshot)
                self.update(job_id, published_attempt=True)   # a lost answer leaves the job pending, never failed: the VM may hold the commit
                result = self.invoke(request, binding)
                if result.get('commit'):
                    self.update(job_id, commit=result['commit'], changed_files=result.get('changed_files', []), snapshot_path=result.get('snapshot_path', ''))
                if (job.get('retry_push', job.get('want_push', False)) and result.get('commit')
                        and result.get('status') != 'needs_attention' and not result.get('pushed')):
                    self.update(job_id, status='pushing', commit=result['commit'], message='Pushing the exported plan.')
                    result = self.invoke({'mode': 'push', 'operation_id': job_id}, binding)
                self.finish(job, result)
                return
            backup_id = job.get('backup_job_id', '')
            if not backup_id:
                if job.get('retry'):
                    raise ValueError('No complete capture is available for retry. Start a new Save progress capture.')
                self.update(job_id, status='capturing', message='Capturing the configured devices.')
                child = self.runner.submit(job['lab_id'], operation='backup', source='git-progress',
                                           node_names=job['node_names'], progress_id=job_id,
                                           progress_context=job['capture_context'])
                backup_id = child['id']; self.update(job_id, backup_job_id=backup_id)
            while True:
                with self.store.lock:
                    backup = next((copy.deepcopy(b) for b in self.store.state['jobs'] if b['id'] == backup_id), None)
                if not backup: raise ValueError('The original capture is unavailable; latest is unchanged.')
                if backup['status'] not in ('queued', 'running'): break
                if self.stopping.wait(.1): raise ValueError('Manager stopping. Retry after the capture result is available.')
            try: snapshot = captured_snapshot(self.store, backup)
            except ValueError as exc:
                self.update(job_id, status='capture_incomplete', message=str(exc), finished=now())
                return
            if set(snapshot['manifest']['node_names']) != set(job['node_names']):
                raise ValueError('This capture does not contain exactly the configured device scope.')
            fingerprint = digest(snapshot)
            if job.get('snapshot_digest') and fingerprint != job['snapshot_digest']:
                raise ValueError('The saved capture changed on disk. It will not replace the repository snapshot.')
            self.update(job_id, status='exporting', snapshot_digest=fingerprint, message='Saving captured configurations to the VM repository.')
            request = copy.deepcopy(job['request'])
            if 'expected_head' not in job:
                status = self.invoke({'mode': 'status'}, binding)
                if not status.get('ready'): raise ValueError(status.get('problem') or 'Repository needs attention before exporting.')
                expected_head = status.get('head', '')
                self.update(job_id, expected_head=expected_head)
            else: expected_head = job['expected_head']
            request.update(mode='publish', operation_id=job_id, expected_head=expected_head, snapshot=snapshot)
            result = self.invoke(request, binding)
            if result.get('commit'):
                self.update(job_id, commit=result['commit'], changed_files=result.get('changed_files', []),
                            snapshot_path=result.get('snapshot_path', ''))
            if (job.get('retry_push', job.get('want_push', False)) and result.get('commit')
                    and result.get('status') != 'needs_attention' and not result.get('pushed')):
                # The publication body is immutable for idempotency. Push is a
                # separate action after replay/reconciliation of a lost response.
                self.update(job_id, status='pushing', commit=result['commit'], message='Pushing the reconciled saved commit.')
                result = self.invoke({'mode': 'push', 'operation_id': job_id}, binding)
            self.finish(job, result)
        except Exception as exc:
            with self.store.lock:
                existing = copy.deepcopy(self.get_job(job_id))
                child = next((b for b in self.store.state['jobs'] if b.get('progress_id') == job_id), None)
                if child and not existing.get('backup_job_id'): existing['backup_job_id'] = child['id']
                if isinstance(result, dict) and re.fullmatch(r'[0-9a-f]{40,64}', str(result.get('commit', ''))):
                    existing['commit'] = result['commit']
                message = scrub(str(exc), self.store.state) if isinstance(exc, (ValueError, HTTPException)) else 'Git save interrupted. The local capture is retained; retry to reconcile.'
            status = 'interrupted' if self.stopping.is_set() else 'push_pending' if existing.get('commit') else 'export_pending' if (existing.get('backup_job_id') or existing.get('published_attempt')) else 'failed'
            recovery = dict(status=status, message=message[:600], finished=now(),
                            backup_job_id=existing.get('backup_job_id', ''), commit=existing.get('commit', ''))
            try: self.update(job_id, **recovery)
            except OSError:
                # The worker has ended. Do not retain a busy reservation in memory
                # until restart; retries after disk recovery reuse this capture.
                with self.store.lock: self.get_job(job_id).update(recovery)
        finally:
            try: self.store.event('git.progress', 'Git save stage completed; see its saved operation status.', lab_id=job.get('lab_id', '') if 'job' in locals() else '', job_id=job_id)
            except OSError: pass

    def finish(self, job, result):
        commit = result.get('commit', '')
        if commit and not re.fullmatch(r'[0-9a-f]{40,64}', commit): raise ValueError('Git helper returned an invalid commit identifier.')
        pushed = result.get('pushed') is True
        # A save with nothing new reuses HEAD. It has nothing to review and nothing to upload when the
        # manager already knows that exact commit was uploaded through this same binding; only then is it
        # 'unchanged'. A HEAD that was never uploaded keeps the ordinary path: there is still a save to
        # review, and it must keep blocking folder changes.
        uploaded = False
        if result.get('status') == 'unchanged' and commit and not pushed and job.get('target') != 'move':
            with self.store.lock:
                uploaded = any(other.get('id') != job['id'] and other.get('commit') == commit and other.get('pushed') is True
                               and other.get('binding_digest') == job.get('binding_digest') for other in self.store.state['git_jobs'])
        if pushed: status = 'synced'
        elif result.get('status') == 'needs_attention': status = 'push_pending' if commit else 'export_pending'
        elif uploaded: status = 'unchanged'
        elif job.get('review_before_push') and not job.get('retry_push') and job.get('target') != 'move': status = 'review_pending'
        else: status = 'committed'
        message = result.get('message') or ('Saved to Git.' if pushed else 'Saved on VM; not pushed.')
        if uploaded: message = 'Nothing changed since the last save, which was uploaded.'
        with self.store.lock: message = scrub(str(message), self.store.state)
        self.update(job['id'], status=status, commit=commit, pushed=pushed or uploaded, message=message[:600],
                    changed_files=result.get('changed_files', []), snapshot_path=result.get('snapshot_path', ''), finished=now())
        if pushed:
            with self.store.lock:
                # The helper names every journaled save the remote now holds. A push carries the saves of the other
                # labs of this checkout below it too (reviewed ones only: see unreviewed_sibling); each is matched by
                # its own lab's current binding.
                peers = {lab_id: digest(lab['git_binding']) for lab_id, lab in self.checkout_labs(job['lab_id']).items()}
                where = (self.store.lab(job['lab_id']) or {}).get('git_binding')
                for previous in self.store.state['git_jobs']:
                    if previous['id'] not in result.get('synced_operations', []): continue
                    if previous.get('status') == 'dismissed':
                        # A dismissed save stays dismissed; it is only known as uploaded now, so later reviews stop counting
                        # it. It is matched like the review counts it, by its checkout (`made_in`), not by a binding digest.
                        if where and self.made_in(previous, where):
                            previous.update(pushed=True, message='Snapshot kept; its commit is included in the verified remote history.')
                        continue
                    same = (previous.get('binding_digest') == job.get('binding_digest') or
                            peers.get(previous.get('lab_id'), '') == previous.get('binding_digest'))
                    if same: previous.update(status='synced', pushed=True, message='Saved commit is included in the verified remote history.', finished=now())
                self.store.save()
            self.settle_kept(job, commit)

    def install(self, app):
        # The review before an upload is mandatory (UI review 001, UI-007 C). `review_before_push` is still
        # accepted from pages loaded before that release, and ignored: a new binding records True, a
        # stored False is never consulted, and stored bindings are left alone so pending saves keep
        # their binding digest.
        class Link(BaseModel):
            model_config = ConfigDict(extra='forbid')
            binding_id: str = Field(min_length=1, max_length=120)
            node_names: list[str] = Field(min_length=1, max_length=500)
            review_before_push: bool = True

        class Save(BaseModel):
            model_config = ConfigDict(extra='forbid')
            request_id: str = Field(pattern=r'^[0-9a-f]{32}$')
            target: str = 'latest'
            checkpoint: str = Field(default='', max_length=100)
            push: bool = True
            note: str = Field(default='', max_length=120)
            backup_job_id: str = Field(default='', max_length=64)
            replace_baseline: bool = False
            expected_baseline: str = Field(default='', max_length=64)
            allow_removed: bool = False

        class Retry(BaseModel):
            model_config = ConfigDict(extra='forbid')
            push: bool = True
            reviewed: bool = False

        class Dismiss(BaseModel):
            model_config = ConfigDict(extra='forbid')
            acknowledge: bool = False

        class Version(BaseModel):
            model_config = ConfigDict(extra='forbid')
            commit: str = Field(pattern=r'^[0-9a-f]{40,64}$')
            path: str = Field(min_length=1, max_length=250)

        class Comparison(BaseModel):
            model_config = ConfigDict(extra='forbid')
            job_id: str = Field(default='', max_length=64)
            commit: str = Field(default='', max_length=64)
            path: str = Field(default='', max_length=250)

        class Folder(BaseModel):
            model_config = ConfigDict(extra='forbid')
            prefix: str = Field(default='', max_length=500)
            plan: bool = False

        class Destination(BaseModel):
            model_config = ConfigDict(extra='forbid')
            prefix: str = Field(default='', max_length=500)
            move_files: bool = False

        class Connect(BaseModel):
            model_config = ConfigDict(extra='forbid')
            url: str = Field(min_length=1, max_length=2048)
            prefix: str = Field(default='', max_length=500)
            node_names: list[str] = Field(default=[], max_length=500)
            review_before_push: bool = False
            acknowledge: bool = False

        def folder_value(value):
            value = value.strip().strip('/')
            if value and (len(value) > 500 or '\\' in value or any(not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,180}', part) or part.lower() == '.git' or part in ('.', '..') for part in value.split('/'))):
                raise HTTPException(400, 'Use folder names with letters, numbers, dashes or underscores; use / to nest. No leading slash, no .. and no .git parts.')
            try: base_folder(value)
            except ValueError as exc: raise HTTPException(400, str(exc))
            return value

        def refuse_snapshot_conflict(binding, prefix):
            """Rule 2: a lab folder cannot sit at, or below, an existing snapshot folder. `browse`
            can cap the tree at MAX_TREE and report `truncated`; this check only sees what came
            back, so a conflict below the cap is refused here and one beyond it is not caught this
            early. That is not a hole: the helper's `publish` independently refuses to write into a
            destination that already holds files outside its own manifest, so a snapshot folder the
            browser never listed is still refused, just later, at save time rather than at folder
            selection."""
            if not prefix: return
            seen = call({'mode': 'browse'}, binding)
            conflict = snapshot_conflict(seen.get('files', []), prefix)
            if conflict:
                raise HTTPException(409, conflict + ' is a saved configuration (it holds manifest.json). '
                                    'Choose the folder above it or a folder beside it.')
            return seen

        # Folders made or chosen through the manager, per checkout. Git has no empty folders and the VM
        # registry only knows the folder a lab saves to now (a move retires the previous registration, and
        # a folder inside a lab's own folder cannot be registered beside it), so without this list an empty
        # folder stops existing the moment the lab saves somewhere else. They are plans, not directories:
        # the tree reports them as `planned` and the page says they are not in the repository yet.
        def planned_folders(path):
            with self.store.lock: return list(self.store.state.get('git_folders', {}).get(path, []))

        def remember_folders(path, *prefixes):
            with self.store.lock:
                known = self.store.state.setdefault('git_folders', {}).setdefault(path, [])
                fresh = [p for p in dict.fromkeys(prefixes) if p and p not in known]
                if not fresh: return
                known.extend(fresh); del known[:-MAX_PLANNED_FOLDERS]
                try: self.store.save()
                except OSError: del known[-len(fresh):]

        def bound_labs():
            return {lab['git_binding']['binding_id']: dict(id=lab['id'], name=lab['name']) for lab in self.store.state['labs'] if lab.get('git_binding')}

        def catalog_binding(binding_id):
            result = repositories()
            repo = next((r for r in result['repositories'] if r['id'] == binding_id), None)
            if not repo: raise HTTPException(404, 'This repository is not registered on the VM. Refresh the list.')
            with self.store.lock: before = host_identity(self.store.state.get('host', {}))
            return repo, dict(binding_id=repo['id'], revision=repo['revision'], repository=repo, host_identity=before)

        def bind_lab(lab_id, repo, node_names, review, before, event, message):
            """Point the lab at a registration after a live status check; the exposure acknowledgement is the caller's job."""
            binding = dict(binding_id=repo['id'], revision=repo['revision'], repository=repo,
                           host_identity=before, node_names=node_names, review_before_push=True)
            call({'mode': 'status'}, binding)
            with self.store.lock:
                self.idle(); self.guard_pending(lab_id)
                if before != host_identity(self.store.state.get('host', {})): raise HTTPException(409, 'VM connection changed. Connect again.')
                lab = self.store.lab(lab_id)
                if not lab: raise HTTPException(404, 'Lab was removed.')
                valid = {n['name'] for n in lab['nodes'] if n.get('platform') in PLATFORMS}
                if len(set(node_names)) != len(node_names) or not node_names or not set(node_names) <= valid:
                    raise HTTPException(400, 'Select distinct supported devices from this lab.')
                for other in self.store.state['labs']:
                    if other['id'] != lab_id and other.get('git_binding', {}).get('binding_id') == repo['id']:
                        raise HTTPException(409, 'This folder is already connected to another lab (' + other['name'] + '). Choose a different folder.')
                old = lab.get('git_binding'); lab['git_binding'] = binding
                try: self.store.save()
                except OSError:
                    if old is None: lab.pop('git_binding', None)
                    else: lab['git_binding'] = old
                    raise HTTPException(500, 'Could not save the repository connection.')
            self.store.event(event, message, lab_id=lab_id)
            return binding

        def retired_already(binding, prefix, catalog=None):
            """The VM may have made a folder change whose answer was lost or refused, now or in an earlier request:
            when the lab's registration is gone and `prefix` is registered in the same checkout, that is the
            registration to follow; else None. Only from the VM connection the binding was made on: the connection
            can be switched during the long call, and another VM's catalog proves nothing about this one."""
            def same_vm():
                with self.store.lock: return host_identity(self.store.state.get('host', {})) == binding['host_identity']
            if not same_vm(): return None
            if catalog is None:
                try: catalog = self.repositories()['repositories']
                except ValueError: return None
                if not same_vm(): return None
            if any(r.get('id') == binding['binding_id'] for r in catalog): return None
            return next((r for r in catalog if r.get('path') == binding['repository'].get('path') and r.get('prefix') == prefix), None)

        def rebind(lab_id, repo, node_names, before, message):
            """Point the lab at the registration that replaced its retired one. Nothing refuses here: every check
            ran before the retire, `binding_lock` keeps every other connection change (link, connect, unlink) out
            meanwhile, and this lab's saves and design exports refuse while it changes (`refuse_while_rebinding`)."""
            binding = dict(binding_id=repo['id'], revision=repo['revision'], repository=repo,
                           host_identity=before, node_names=node_names, review_before_push=True)
            with self.store.lock:
                lab = self.store.lab(lab_id)
                if not lab: raise HTTPException(404, 'Lab was removed.')
                lab['git_binding'] = binding
                try: self.store.save()
                except OSError: raise HTTPException(500, 'The folder changed on the VM, but the manager could not store the change. Free disk space, then reopen this lab before saving.')
            self.store.event('git.destination', message, lab_id=lab_id)
            return binding

        def call(request, binding=None):
            try: return self.invoke(request, binding)
            except ValueError as exc: raise HTTPException(409, str(exc))

        def one_binding_change(route):
            """A route that changes which registration a lab points at (or disconnects it) runs alone (`binding_lock`):
            a folder change checks everything before the VM retires the old registration, nothing may take the new one
            meanwhile, and a Disconnect from another tab cannot be undone by the rebind that follows."""
            @functools.wraps(route)
            def alone(*args, **kwargs):
                with self.changing(kwargs.get('lab_id')): return route(*args, **kwargs)
            return alone

        def refuse_while_rebinding(lab_id):
            """A save or design export freezes the binding digest it is retried with. Created while a connection change
            rewrites its lab's binding, it could never be retried (export_pending for good), so it waits for the change.
            Only that lab's: another lab's binding is not touched, and connecting by URL can clone for minutes."""
            if self.rebinding == lab_id:
                raise HTTPException(409, "This lab's repository connection is being changed. Try again in a moment.")

        @app.get('/api/git/repositories')
        def repositories():
            try: return self.repositories()
            except ValueError as exc: raise HTTPException(409, str(exc))

        @app.get('/api/labs/{lab_id}/git')
        def settings(lab_id: str):
            with self.store.lock:
                lab = self.store.lab(lab_id)
                if not lab: raise HTTPException(404, 'Lab not found.')
                binding = copy.deepcopy(lab.get('git_binding'))
                jobs = [public_job(j) for j in reversed(self.store.state['git_jobs']) if j['lab_id'] == lab_id]
                supported = [{k: n.get(k, '') for k in ('name', 'short_name', 'platform')} for n in lab['nodes'] if n.get('platform') in PLATFORMS]
                unsupported = [n['name'] for n in lab['nodes'] if n.get('platform') not in PLATFORMS]
            status = {}
            if binding:
                try: status = self.invoke({'mode': 'status'}, binding)
                except ValueError as exc: status = {'ready': False, 'problem': str(exc)}
            return dict(binding=binding, repository_status=status, jobs=jobs, supported_nodes=supported, unsupported_nodes=unsupported)

        @app.put('/api/labs/{lab_id}/git')
        @one_binding_change
        def link(lab_id: str, data: Link):
            with self.store.lock:
                self.idle(); self.guard_pending(lab_id)
                if not self.store.lab(lab_id): raise HTTPException(404, 'Lab not found.')
                before = host_identity(self.store.state.get('host', {}))
            result = repositories()
            repo = next((r for r in result['repositories'] if r['id'] == data.binding_id), None)
            if not repo: raise HTTPException(400, 'Choose a repository registered by the VM administrator.')
            binding = dict(binding_id=repo['id'], revision=repo['revision'], repository=repo,
                           host_identity=before, node_names=data.node_names, review_before_push=True)
            call({'mode': 'status'}, binding)
            with self.store.lock:
                self.idle(); self.guard_pending(lab_id)
                if before != host_identity(self.store.state.get('host', {})): raise HTTPException(409, 'VM connection changed. Connect again.')
                lab = self.store.lab(lab_id)
                if not lab: raise HTTPException(404, 'Lab was removed.')
                valid = {n['name'] for n in lab['nodes'] if n.get('platform') in PLATFORMS}
                if len(set(data.node_names)) != len(data.node_names) or not set(data.node_names) <= valid:
                    raise HTTPException(400, 'Select distinct supported devices from this lab.')
                for other in self.store.state['labs']:
                    if other['id'] != lab_id and other.get('git_binding', {}).get('binding_id') == repo['id']:
                        raise HTTPException(409, 'This registered destination is already connected to another lab. Register a separate prefix.')
                old = lab.get('git_binding'); lab['git_binding'] = binding
                try: self.store.save()
                except OSError:
                    if old is None: lab.pop('git_binding', None)
                    else: lab['git_binding'] = old
                    raise HTTPException(500, 'Could not save the repository connection.')
            self.store.event('git.connect', 'Lab connected to a registered VM repository.', lab_id=lab_id)
            return {'saved': True, 'binding': binding}

        @app.get('/api/git/repositories/{binding_id}/tree')
        def tree(binding_id: str):
            repo, binding = catalog_binding(binding_id)
            result = call({'mode': 'browse'}, binding)
            labs = {}
            with self.store.lock: labs = bound_labs()
            folders = [dict(f, lab=labs.get(f.get('id'))) for f in result.get('folders', []) if isinstance(f, dict)]
            return dict(repository=result.get('repository', repo), head=result.get('head', ''), files=result.get('files', []),
                        truncated=bool(result.get('truncated')), saved=result.get('saved', {}), folders=folders,
                        planned=planned_folders(repo['path']))

        @app.post('/api/git/repositories/{binding_id}/folders')
        def folder(binding_id: str, data: Folder):
            prefix = folder_value(data.prefix)
            repo, binding = catalog_binding(binding_id)
            seen = refuse_snapshot_conflict(binding, prefix)
            if data.plan:
                # A folder to save into later: nothing is registered or written on the VM. The repository is
                # read once so a name that exists (committed, a lab folder, or planned) is refused as a duplicate.
                if not prefix: raise HTTPException(400, 'Enter a folder name.')
                seen = seen or call({'mode': 'browse'}, binding)
                taken = {f.get('prefix') for f in seen.get('folders', []) if isinstance(f, dict)} | set(planned_folders(repo['path']))
                if prefix in taken or any(str(f.get('path', '')).startswith(prefix + '/') for f in seen.get('files', []) if isinstance(f, dict)):
                    raise HTTPException(409, 'A folder named ' + prefix + ' already exists in this repository. Pick it in the list instead.')
                remember_folders(repo['path'], prefix)
                if prefix not in planned_folders(repo['path']): raise HTTPException(500, 'The folder could not be stored. Nothing was created.')
                self.store.event('git.folder', 'Repository folder planned for later saves.', lab_id='')
                return {'planned': prefix}
            created = call({'mode': 'register-prefix', 'prefix': prefix}, binding)
            if not isinstance(created, dict) or not created.get('id'): raise HTTPException(409, 'The VM did not return the new folder registration.')
            remember_folders(repo['path'], prefix)
            self.store.event('git.folder', 'Repository folder registered for lab saves.', lab_id='')
            return {'repository': created}

        @app.delete('/api/git/repositories/{binding_id}/folders')
        def forget_folder(binding_id: str, data: Folder):
            """Forget a planned folder that was never used. Nothing on the VM changes; a folder with saved files or a lab stays visible anyway."""
            prefix = folder_value(data.prefix)
            repo, _ = catalog_binding(binding_id)
            with self.store.lock:
                known = self.store.state.get('git_folders', {}).get(repo['path'], [])
                if prefix not in known: raise HTTPException(404, 'This folder is not one the manager created.')
                known.remove(prefix)
                try: self.store.save()
                except OSError:
                    known.append(prefix); raise HTTPException(500, 'The change could not be stored.')
            return {'forgotten': prefix}

        @app.post('/api/labs/{lab_id}/git/destination')
        @one_binding_change
        def destination(lab_id: str, data: Destination):
            prefix = folder_value(data.prefix)

            def refusals():
                """Everything that can refuse the change. It runs before the VM retires the lab's registration, never
                after: a refusal then would leave the lab bound to a registration that no longer exists."""
                with self.store.lock:
                    self.idle(lab_id if data.move_files else None); self.guard_pending(lab_id); binding = self.binding(lab_id)
                    lab = self.store.lab(lab_id)
                    if binding['host_identity'] != host_identity(self.store.state.get('host', {})):
                        raise HTTPException(409, 'Reconnect the original VM before changing the folder.')
                    valid = {n['name'] for n in lab['nodes'] if n.get('platform') in PLATFORMS}
                    names = binding.get('node_names') or []
                    if not names or len(set(names)) != len(names) or not set(names) <= valid:
                        raise HTTPException(409, 'The devices of this lab changed since it was connected. Choose its devices again under Save settings, then change the folder.')
                    # The move commits and uploads at once: it waits like a save for another lab's unreviewed save.
                    if data.move_files: self.guard_siblings(lab_id)
                    return binding, lab['name']

            binding, name = refusals()
            before = binding['host_identity']; node_names = list(binding['node_names'])
            source = binding['repository'].get('prefix', '')
            catalog = repositories()['repositories']
            # The lab's registration can be gone already: an earlier change of this folder went through on the VM but
            # its answer, and the check after it, were lost. Every call with it only answers UNREGISTERED, so the change
            # asked for now is checked against the VM's catalog and followed, never browsed with the retired binding.
            registered = any(r['id'] == binding['binding_id'] for r in catalog)
            if registered:
                if prefix == source: raise HTTPException(409, 'This lab already saves to that folder.')
                try: refuse_snapshot_conflict(binding, prefix)
                except HTTPException as exc:
                    if exc.detail != UNREGISTERED: raise
                    registered = False; catalog = repositories()['repositories']
            with self.store.lock: labs = bound_labs()
            for repo in catalog:
                if repo['path'] == binding['repository'].get('path') and repo['prefix'] == prefix and labs.get(repo['id'], {}).get('id') not in (None, lab_id):
                    raise HTTPException(409, 'This folder is already connected to another lab (' + labs[repo['id']]['name'] + '). Choose a different folder.')
            # Once more right before the irreversible step: the helper round trips above take time.
            if digest(refusals()[0]) != digest(binding): raise HTTPException(409, 'The repository connection changed meanwhile. Open Change folder again.')
            if not registered:
                created = retired_already(binding, prefix, catalog)
                if not created:
                    raise HTTPException(409, "This lab's folder registration is no longer on the VM: an earlier folder change probably went "
                                        'through there without reporting back. If so, choose that folder again; if not, connect the lab again '
                                        '(Use a different repository… on the Save location card).')
            else:
                try: created = self.invoke({'mode': 'register-prefix', 'prefix': prefix, 'retire': True}, binding)
                except ValueError as exc:
                    created = retired_already(binding, prefix)
                    if not created: raise HTTPException(409, str(exc))
            if not isinstance(created, dict) or not created.get('id'): raise HTTPException(409, 'The VM did not return the new folder registration.')
            # The folder the lab leaves is retired on the VM; keep it (and the new one) reachable while empty.
            remember_folders(binding['repository'].get('path', ''), source, prefix)
            new_binding = rebind(lab_id, created, node_names, before, 'Lab repository folder changed to ' + (prefix or 'the repository root') + '.')
            job = None
            if data.move_files:
                # No refusal here either: the lab already saves to the new folder, and a move that is not queued
                # could never be asked for again (the same folder is refused). The job queues behind running work.
                with self.store.lock:
                    request = dict(source_prefix=source, push=False, message='Move ' + name + ' progress to ' + (prefix + '/' if prefix else 'the repository root'))
                    job = dict(id=uuid.uuid4().hex, lab_id=lab_id, lab_name=name, created=now(), status='queued', message='Folder move queued.',
                               backup_job_id='', target='move', checkpoint='', note='', pushed=False, review_before_push=False,
                               binding_digest=digest(new_binding), request=request, want_push=True, node_names=node_names, capture_context={},
                               destination=move_destination(new_binding), host_identity=new_binding['host_identity'])
                    _append_git_job(self.store.state, job)
                    try: self.store.save()
                    except OSError:
                        self.store.state['git_jobs'].remove(job); raise HTTPException(500, 'The folder changed, but the file move could not be queued.')
                job = self.schedule(job)
            return {'saved': True, 'binding': new_binding, 'job': job}

        @app.post('/api/labs/{lab_id}/git/connect')
        @one_binding_change
        def connect(lab_id: str, data: Connect):
            if not data.acknowledge: raise HTTPException(400, 'Acknowledge that full device configurations will be committed and pushed to this repository.')
            prefix = folder_value(data.prefix)
            with self.store.lock:
                self.idle(); self.guard_pending(lab_id)
                lab = self.store.lab(lab_id)
                if not lab: raise HTTPException(404, 'Lab not found.')
                before = host_identity(self.store.state.get('host', {}))
                supported = [n['name'] for n in lab['nodes'] if n.get('platform') in PLATFORMS]
                previous = lab.get('git_binding') or {}
                node_names = list(data.node_names) or [n for n in previous.get('node_names', []) if n in supported] or supported
                review = data.review_before_push if data.node_names else previous.get('review_before_push', data.review_before_push)
            created = call({'mode': 'connect', 'url': data.url.strip(), 'prefix': prefix})
            if not isinstance(created, dict) or not created.get('id'): raise HTTPException(409, 'The VM did not return the repository registration.')
            binding = bind_lab(lab_id, created, node_names, review, before, 'git.connect', 'Lab connected to a repository from the manager.')
            return {'saved': True, 'binding': binding}

        @app.post('/api/labs/{lab_id}/git/unlink')
        @one_binding_change
        def unlink(lab_id: str):
            with self.store.lock:
                self.idle(); self.guard_pending(lab_id)
                lab = self.store.lab(lab_id)
                if not lab: raise HTTPException(404, 'Lab not found.')
                old = lab.pop('git_binding', None)
                try: self.store.save()
                except OSError:
                    if old: lab['git_binding'] = old
                    raise HTTPException(500, 'Could not disconnect the repository.')
            return {'unlinked': True}

        @app.post('/api/labs/{lab_id}/git/save')
        def save(lab_id: str, data: Save):
            if data.target not in ('latest', 'checkpoint', 'baseline'): raise HTTPException(400, 'Choose latest, checkpoint or baseline.')
            if data.target == 'checkpoint' and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,99}', data.checkpoint):
                raise HTTPException(400, 'Use a checkpoint name containing letters, numbers, hyphens or underscores.')
            if data.target == 'baseline' and not data.backup_job_id: raise HTTPException(400, 'Select a complete saved capture for the baseline.')
            if any(ord(c) < 32 for c in data.note): raise HTTPException(400, 'Use a single-line save note.')
            # Every save carries a short human label: it is the commit message and the way every
            # save is named back to the student (pending list, history, the job window). A save
            # (unlike a folder move or a remote update, which never reach this model) always needs one.
            if not data.note.strip(): raise HTTPException(400, 'Give this save a short label.')
            request_digest = digest(dict(lab_id=lab_id, **data.model_dump()))
            with self.store.lock:
                previous = next((j for j in self.store.state['git_jobs'] if j['id'] == data.request_id), None)
                if previous:
                    if previous.get('request_digest') != request_digest: raise HTTPException(409, 'Request ID already belongs to a different save.')
                    return public_job(previous)
                self.idle(lab_id); refuse_while_rebinding(lab_id); binding = self.binding(lab_id); self.guard_siblings(lab_id)
                lab = self.store.lab(lab_id)
                if binding['host_identity'] != host_identity(self.store.state.get('host', {})):
                    raise HTTPException(409, 'Reconnect the original VM before saving progress.')
                names = binding['node_names']; known = {n['name'] for n in lab['nodes'] if n.get('platform') in PLATFORMS}
                if not set(names) <= known: raise HTTPException(409, 'Configured devices changed. Review the Git repository device selection.')
                if data.backup_job_id:
                    backup = next((b for b in self.store.state['jobs'] if b['id'] == data.backup_job_id and b['lab_id'] == lab_id), None)
                    if not backup: raise HTTPException(404, 'Capture not found in this lab.')
                    try: snapshot = captured_snapshot(self.store, backup)
                    except ValueError as exc: raise HTTPException(400, str(exc))
                    if set(snapshot['manifest']['node_names']) != set(names): raise HTTPException(400, 'Capture must contain exactly the configured devices.')
                context = dict(node_names=sorted(names), excluded_nodes=sorted(n['name'] for n in lab['nodes'] if n['name'] not in names),
                               topology_digest=hashlib.sha256(lab['definition_yaml'].encode()).hexdigest() if lab.get('definition_yaml') else None)
                # A save a person starts never uploads by itself: it stops at review_pending and the upload
                # is a retry that states the review happened. The binding's old preference is not read.
                review = data.push
                request = dict(target=data.target, checkpoint=data.checkpoint, push=False,
                               replace_baseline=data.replace_baseline, expected_baseline=data.expected_baseline,
                               allow_removed=data.allow_removed, message=data.note.strip() or f'Save {lab["name"]} progress')
                job = dict(id=data.request_id, request_digest=request_digest, lab_id=lab_id, lab_name=lab['name'],
                           created=now(), status='queued', message='Save progress queued.', backup_job_id=data.backup_job_id,
                           target=data.target, checkpoint=data.checkpoint, note=data.note, pushed=False,
                           review_before_push=review, binding_digest=digest(binding), request=request,
                           want_push=data.push and not review,
                           # Frozen at capture time from the binding as it is now: never re-derived from a
                           # binding that may have moved by the time the save is reviewed or shown later.
                           destination=job_destination(binding, data.target, data.checkpoint),
                           # Private: the VM of that checkout, so a kept save is counted in its reviews only (made_in).
                           host_identity=binding['host_identity'],
                           node_names=copy.deepcopy(names), capture_context=context)
                _append_git_job(self.store.state, job)
                try: self.store.save()
                except OSError:
                    self.store.state['git_jobs'].remove(job); raise HTTPException(500, 'Could not save the request. No work was submitted.')
            return self.schedule(job)

        class DesignExport(BaseModel):
            model_config = ConfigDict(extra='forbid')
            request_id: str = Field(pattern=r'^[0-9a-f]{32}$')
            checkpoint: str = Field(min_length=1, max_length=100)
            note: str = Field(default='', max_length=200)
            push: bool = False

        @app.post('/api/labs/{lab_id}/design/generations/{generation_id}/git')
        def export_design(lab_id: str, generation_id: str, data: DesignExport):
            """A design export is a Git save of kind `design`: its own checkpoint folder, the plan's files with a
            manifest that names them generated artifacts, the same mandatory review before any upload."""
            if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,99}', data.checkpoint):
                raise HTTPException(400, 'Use a checkpoint name containing letters, numbers, hyphens or underscores.')
            if any(ord(c) < 32 for c in data.note): raise HTTPException(400, 'Use a single-line note.')
            if self.designs is None: raise HTTPException(503, 'Design exports are not available.')
            request_digest = digest(dict(lab_id=lab_id, generation_id=generation_id, **data.model_dump()))
            with self.store.lock:
                previous = next((j for j in self.store.state['git_jobs'] if j['id'] == data.request_id), None)
                if previous:
                    if previous.get('request_digest') != request_digest: raise HTTPException(409, 'Request ID already belongs to a different save.')
                    return public_job(previous)
                self.idle(lab_id); refuse_while_rebinding(lab_id); binding = self.binding(lab_id); self.guard_siblings(lab_id)
                lab = self.store.lab(lab_id)
                if binding['host_identity'] != host_identity(self.store.state.get('host', {})):
                    raise HTTPException(409, 'Reconnect the original VM before exporting.')
                generation = next((g for g in lab.get('network_generations', []) if g['id'] == generation_id), None)
                if not generation: raise HTTPException(404, 'Plan not found in this lab.')
                if generation.get('status') != 'succeeded': raise HTTPException(409, 'Only a generated plan can be exported.')
                try: snapshot = self.designs.design_snapshot(lab, generation)
                except ValueError as exc: raise HTTPException(400, str(exc))
                note = data.note.strip() or ('Design plan ' + generation_id[:12] + (' (' + str(generation.get('label') or '') + ')' if generation.get('label') else ''))
                request = dict(target='checkpoint', checkpoint=data.checkpoint, push=False, replace_baseline=False, expected_baseline='',
                               allow_removed=False, message=note)   # the helper writes a design to its own checkpoint folder only
                job = dict(id=data.request_id, request_digest=request_digest, lab_id=lab_id, lab_name=lab['name'], kind='design',
                           generation_id=generation_id, created=now(), status='queued', message='Design export queued.', backup_job_id='',
                           target='checkpoint', checkpoint=data.checkpoint, note=note, pushed=False, review_before_push=data.push,
                           binding_digest=digest(binding), request=request, want_push=False, snapshot_digest=digest(snapshot),
                           destination=job_destination(binding, 'checkpoint', data.checkpoint), host_identity=binding['host_identity'],
                           node_names=[], capture_context={})
                _append_git_job(self.store.state, job)
                try: self.store.save()
                except OSError:
                    self.store.state['git_jobs'].remove(job); raise HTTPException(500, 'Could not save the request. No work was submitted.')
            return self.schedule(job)

        @app.get('/api/git/jobs/{job_id}')
        def job_status(job_id: str):
            with self.store.lock: return public_job(self.get_job(job_id))

        @app.post('/api/git/jobs/{job_id}/retry')
        def retry(job_id: str, data: Retry):
            with self.store.lock:
                job = self.get_job(job_id); self.idle(job['lab_id']); move = job.get('target') == 'move'
                # A folder move has no new save to start instead (its folder is the lab's own now), and its journal on
                # the VM makes a retry idempotent: a move an older release marked failed stays retryable.
                if job['status'] in ('dismissed', 'capture_incomplete') or (job['status'] == 'failed' and not move):
                    raise HTTPException(409, 'Start a new save for this capture outcome.')
                if job['status'] == 'synced' or (job['status'] == 'unchanged' and job.get('pushed')): return public_job(job)
                binding = self.binding(job['lab_id'])
                if digest(binding) != job['binding_digest']: raise HTTPException(409, 'Repository settings changed. Reconnect the original destination.')
                # Uploading a save needs its review: stated with this request, or recorded by an earlier
                # one (an upload that failed after the review). A save without a commit has nothing to
                # review yet, so its retry saves on the VM and then waits for the review. A folder move
                # carries no configuration change and keeps its own confirmed upload.
                push, changes = data.push, {}
                if push and not move:
                    if not job.get('commit'): push, changes = False, dict(review_before_push=True)
                    elif not (data.reviewed or job.get('reviewed')):
                        raise HTTPException(409, 'Review the changes of this save before uploading it.')
                    elif not job.get('reviewed'): changes = dict(reviewed=now())
                elif push and job.get('commit') and not job.get('reviewed'):
                    # A folder move's upload sends the saves kept with Keep snapshot only in this checkout along: it goes
                    # through the review that names them (stated with this request), and only while there are such saves.
                    kept = [] if data.reviewed else self.kept_saves(job, binding)
                    if data.reviewed: changes = dict(reviewed=now())
                    elif kept:
                        self.update(job_id, review_before_push=True)
                        raise HTTPException(409, 'Review this folder move before uploading it. ' + self.kept_refusal(kept))
                # The same review holds across the labs of one checkout: an upload, or a retry that commits, waits
                # while another lab's save there is unreviewed. A refused upload keeps its review, so this save no
                # longer holds the other lab back; a retry that only commits waits only for a save that has a commit,
                # so two saves without one never hold each other back (see unreviewed_sibling).
                if push or not job.get('commit'):
                    other, held = self.unreviewed_sibling(job['lab_id'], commitless=not push)
                    if held:
                        if changes.get('reviewed'): self.update(job_id, reviewed=changes['reviewed'])
                        raise HTTPException(409, sibling_refusal(other['name'], held, upload=push, reviewed=push and not move))
                self.update(job_id, status='queued', retry=True, retry_push=push, message='Retry queued; the saved capture will be reused.', **changes)
            return self.schedule(job)

        @app.post('/api/git/jobs/{job_id}/dismiss')
        def dismiss(job_id: str, data: Dismiss):
            if not data.acknowledge: raise HTTPException(400, 'Confirm keeping the snapshot without tracking its pending Git save.')
            with self.store.lock:
                self.idle(); self.get_job(job_id)
                self.update(job_id, status='dismissed', message='Snapshot kept; pending Git tracking dismissed. Existing commits are unchanged.')
            return public_job(self.get_job(job_id))

        @app.post('/api/labs/{lab_id}/git/update')
        def update_remote(lab_id: str):
            with self.store.lock:
                self.idle(); self.guard_pending(lab_id); binding = self.binding(lab_id)
                ident = uuid.uuid4().hex
                marker = dict(id=ident, lab_id=lab_id, status='exporting', created=now(), message='Updating repository from remote.', target='update')
                _append_git_job(self.store.state, marker)
                try: self.store.save()
                except OSError:
                    self.store.state['git_jobs'].remove(marker)
                    raise HTTPException(500, 'Could not save the update request. No work was submitted.')
            completed = False
            try:
                status = call({'mode': 'status'}, binding)
                result = call({'mode': 'update', 'expected_head': status['head']}, binding)
                completed = True
                return result
            finally:
                terminal = dict(status='dismissed', finished=now(), message='Repository updated from remote.' if completed else 'Repository update needs attention. Check status before retrying.')
                try: self.update(ident, **terminal)
                except OSError:
                    with self.store.lock: self.get_job(ident).update(terminal)
                    raise

        @app.get('/api/labs/{lab_id}/git/history')
        def history(lab_id: str):
            with self.store.lock: binding = self.binding(lab_id)
            result = call({'mode': 'history'}, binding)
            # Versions come back with their full repository path; label each so a student sees
            # base/final/broken/work rather than an unlabelled "latest".
            for row in result.get('versions', []):
                row['label'] = version_label(row.get('path', ''))
            return result

        def version_data(lab_id, data):
            with self.store.lock: binding = self.binding(lab_id)
            result = call({'mode': 'read-version', 'commit': data.commit, 'path': resolve_version_path(binding, data.path)}, binding)
            try: return decoded_snapshot(result)
            except ValueError as exc: raise HTTPException(409, str(exc))

        @app.post('/api/labs/{lab_id}/git/version')
        def version(lab_id: str, data: Version):
            manifest, files = version_data(lab_id, data)
            restore_nodes = [f.get('node', '') for f in manifest.get('files', []) if f.get('restore_artifact')]
            return dict(manifest=manifest, files=[dict(name=n, text=v.decode('utf-8')) for n, v in files.items()],
                        restore_supported=bool(restore_nodes), restore_nodes=restore_nodes)

        @app.post('/api/labs/{lab_id}/git/version/download')
        def download(lab_id: str, data: Version):
            manifest, files = version_data(lab_id, data)
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as archive:
                archive.writestr('manifest.json', json.dumps(manifest, indent=2))
                for name, raw in files.items(): archive.writestr(name, raw)
            filename = component(manifest.get('lab_name', 'lab')) + '-' + data.commit[:12] + '.zip'
            return Response(buf.getvalue(), media_type='application/zip', headers={'Content-Disposition': "attachment; filename*=UTF-8''" + quote(filename, safe='')})

        @app.post('/api/labs/{lab_id}/git/compare')
        def compare(lab_id: str, data: Comparison):
            if data.job_id:
                with self.store.lock:
                    job = self.get_job(data.job_id)
                    if job['lab_id'] != lab_id: raise HTTPException(404, 'Git save not found in this lab.')
                    binding = self.binding(lab_id)
                    if digest(binding) != job.get('binding_digest'): raise HTTPException(409, 'Reconnect the original repository to review this save.')
                    # What an upload of this save may carry along: every other save of this checkout still waiting on
                    # the VM, this lab's and the other labs' (one without a known commit while it may hold one,
                    # `may_hold_commit`), and every save of this checkout kept with Keep snapshot only that was not seen
                    # uploaded (`kept_saves`: whichever lab made it, connected or not, under whatever binding, also the one
                    # whose commit this save only reuses because it changed nothing), named, until an upload settled it
                    # (`finish`, `settle_kept`). It can over-report (a kept save that never committed, or whose
                    # registration was retired since); it misses a save the manager no longer holds (a removed lab's) and
                    # one so old it froze no destination at all (saves froze none before 1.30.37), whose checkout only its
                    # lab's current binding can tell: while that lab is disconnected the save is in no checkout's count,
                    # and once it is connected to another checkout it is counted there instead. Nothing the manager still
                    # holds names that save's checkout. A save that froze its checkout but not its VM is placed on its lab's
                    # current VM, so it is missed too once the manager reaches that VM through another connection identity
                    # (`made_in`). While another lab's save is unreviewed the upload waits.
                    labs = self.checkout_labs(lab_id)
                    waiting = [j for j in self.store.state['git_jobs'] if j['id'] != job['id'] and (j.get('lab_id') == lab_id or j.get('lab_id') in labs)
                               and job_pending(j) and not j.get('pushed') and j.get('target') != 'update' and may_hold_commit(j)]
                    kept = self.kept_saves(job, binding)
                    other, held = self.unreviewed_sibling(lab_id)
                # A folder move changes no configuration: its review is about what its upload sends along. The helper's
                # comparison reads the moved `latest` folder, which a lab that saved only checkpoints or a baseline has
                # not, and a review that cannot open would keep a move held for it (`kept_saves`) from its upload.
                result = {'files': []} if job.get('target') == 'move' else call({'mode': 'compare', 'operation_id': data.job_id}, binding)
                # The helper pairs files by name; fold a suffix-renamed file (Junos `.set` to `.cfg`)
                # back into one changed entry before it ever reaches a person.
                answer = {'files': annotated_compare(result.get('files', [])), 'also_sends': len(waiting) + len(kept),
                          'also_sends_other_labs': sum(1 for j in waiting + kept if j.get('lab_id') != lab_id),
                          'also_sends_kept': self.kept_names(kept)}
                if held: answer['upload_blocked'] = sibling_refusal(other['name'], held, upload=True)
                return answer
            if not re.fullmatch(r'[0-9a-f]{40,64}', data.commit): raise HTTPException(400, 'Choose a saved commit.')
            before_manifest, before = version_data(lab_id, data)
            with self.store.lock: binding = self.binding(lab_id)
            status = call({'mode': 'status'}, binding)
            path = repo_path(binding, 'latest')
            result = call({'mode': 'read-version', 'commit': status['head'], 'path': path}, binding)
            try: after_manifest, after = decoded_snapshot(result)
            except ValueError as exc: raise HTTPException(409, str(exc))
            # snapshot_diff already pairs by manifest node identity, never by filename, so a suffix
            # rename never appears here as a false removed-plus-added pair.
            return {'files': annotated_compare(snapshot_diff(before_manifest, before, after_manifest, after))}
