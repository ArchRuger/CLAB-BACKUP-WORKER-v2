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
from fastapi import HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from . import __version__
from . import git_places
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
              'reviewed', 'destination', 'kind', 'generation_id', 'note_auto', 'summary')
# Fixed sentences of the save model. The page recognises none of them by text: it shows what the manager answers.
REVIEW_FIRST = 'Review the changes of this save before uploading it.'
ANOTHER_SAVE = 'Another save was made in this repository. Look at the changes again.'
NOT_OURS = 'The repository on the VM has changes the manager did not make.'
NOT_WHOLE = 'This capture does not include the topology. Save again first.'
TOPOLOGY_FAILED = 'The topology could not be saved with this capture. Try again.'
NO_DEVICES = 'None of the devices this lab saves exist in it any more. Choose the devices under Save settings.'
WAITING_FIRST = 'Upload the waiting saves first; the online copy can only be fetched when nothing waits here.'
STILL_WAITING = 'A save is still waiting to be uploaded. Upload it, or open its Details and choose Keep snapshot only, then try again.'
VM_UNREACHABLE = 'Cannot reach the VM Git helper. The local capture is retained; check VM setup and retry.'
MAX_SAVE_NAMES = 2000
NOTE_LIMIT = 120
SLUG = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,99}')   # host_git.SLUG: a checkpoint's folder name
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


# What stops a save or an upload, as one code for the header chip (DESIGN.md 3.6, 3.8 N1): `vm` the VM cannot be
# reached, `account` the VM account cannot commit or upload, `busy` someone is working in the checkout (or it moved
# under a save), `diverged` the online copy and the VM have changes the other lacks, `files` files the manager did
# not save are where a save goes, `settings` the save location has to be set up again, `other` everything else.
# Every sentence the helper's `status`, `publish`, `push` and `update` can answer is listed with its code, as it is
# written in host_git.py (tests/test_git_save_model.py compares both ways, so a reworded sentence breaks the test).
HELPER_PROBLEMS = {
    'Select a registered Git repository.': 'settings',
    'The repository binding changed. Select it again.': 'settings',
    'This directory is not a Git checkout: .git is missing. Run guided Git setup to clone a repository; mkdir alone is insufficient.': 'settings',
    'Linked worktrees and bare repositories are not supported.': 'settings',
    'Git progress storage must belong to the registered owner.': 'settings',
    'The registered repository path is missing.': 'settings',
    'Symlinked repository paths are not supported.': 'settings',
    'Select the repository root of a standard checkout.': 'settings',
    'Bare repositories are unsupported.': 'settings',
    'Linked worktrees are unsupported.': 'settings',
    'Submodules and linked worktrees are unsupported.': 'settings',
    'Submodules are unsupported.': 'settings',
    'The repository branch changed. Restore the registered branch or register it again.': 'settings',
    'Git URL rewrites are unsupported for registered repositories.': 'settings',
    'The Git push destination changed. Register the repository again.': 'settings',
    'Initialize the repository with its first commit.': 'settings',
    'The registered Git owner changed or is not an ordinary VM account.': 'settings',
    'Saved progress journal not found for this binding.': 'settings',
    'Git commit identity is missing or invalid. As the registered Linux owner, run guided Git setup or set user.name and user.email inside this checkout, then retry the original save.': 'account',
    "The remote branch is unavailable. Check connectivity and the owner's noninteractive HTTPS Git login.": 'account',
    'The commit is saved on the VM, but push failed. Check authentication, branch permissions or remote changes, then retry.': 'account',
    'Git command timed out. Check the repository and credential helper before retrying.': 'account',
    'Another Git operation is already running for this repository.': 'busy',
    'Finish the existing Git operation before saving lab progress.': 'busy',
    'The repository already has staged changes. If an earlier manager save failed, fix its reported issue and retry that original save: Retry commits automatically. For unrelated staged work, resolve it as the repository owner first.': 'busy',
    'The repository has unsaved edits in the selected scope. Resolve them before continuing.': 'busy',
    'Finish the existing Git operation before retrying export.': 'busy',
    'Unrelated files entered the index during export; no commit was attempted.': 'busy',
    'An exported file has separately staged edits. Preserve those edits before retrying.': 'busy',
    'An exported file was edited after saving began. Review it before retrying; the snapshot is preserved.': 'busy',
    'The checkout changed during export. Preserve the snapshot and review the working files.': 'busy',
    'The checkout changed before staging. Review the working files.': 'busy',
    'The checkout changed after committing. Review the preserved commit before pushing.': 'busy',
    'The checkout changed before push; review the repository.': 'busy',
    'The checkout moved after this save. Review its commit before retrying.': 'busy',
    'The checkout moved since this save. Push the newest saved progress or resolve it as the repository owner.': 'busy',
    'The repository changed since it was selected. Refresh status and retry the preserved snapshot.': 'busy',
    'The repository changed before export.': 'busy',
    'The checkout changed. Refresh repository status before updating.': 'busy',
    'The checkout changed during fetch.': 'busy',
    'The remote branch advanced or diverged. Resolve the branch before pushing; no force push was attempted.': 'diverged',
    'Local and remote history diverged or local commits are pending. Resolve them as the repository owner.': 'diverged',
    'The push would include commits created outside manager saves. Publish or resolve them as the repository owner first.': 'diverged',
    'This unchanged save points to a commit created outside manager saves. Publish it as the repository owner first.': 'diverged',
    'The destination contains files outside its manager manifest; preserve or move them first.': 'files',
    'The destination is not an empty manager snapshot folder.': 'files',
    'Only ordinary, unlinked snapshot files are supported.': 'files',
    'Existing manifest is too large.': 'files',
    'Existing snapshot manifest is invalid.': 'files',
    'Existing snapshot manifest has an invalid file count.': 'files',
    'Existing snapshot manifest has unsafe or duplicate filenames.': 'files',
    'Existing snapshot files are missing or too large.': 'files',
    'Existing snapshot files no longer match their saved manifest. Review the repository before exporting.': 'files',
    'Existing snapshot manifest contains invalid file metadata.': 'files',
    'Existing manifest contains an invalid file path.': 'files',
    'This folder holds a different kind of snapshot; choose another name.': 'files',
    'Git hooks changed files outside the approved snapshot. Review the local commit; it was not pushed.': 'other',
    'Git filters or hooks changed snapshot content. Review the local commit; it was not pushed.': 'other',
    'Git filters changed the saved configuration. Review attributes and staged files; nothing was pushed.': 'other',
    'Git staging changed the approved file set. Review the index; nothing was pushed.': 'other',
    'The committed deletion did not match the approved snapshot.': 'other',
    'Invalid Git commit identity.': 'other',
    'Git could not complete this operation. Check the repository as its registered owner.': 'other',
    'Git output exceeded its bounded response limit.': 'other',
    'The remote branch response was invalid.': 'other',
    'Push returned, but its remote result could not be verified. Retry the saved progress.': 'other',
    'This save has no verified commit to push. Review its export status.': 'other',
    'Invalid progress operation ID.': 'other',
    'The saved progress journal is invalid.': 'other',
    'This operation ID already belongs to a different snapshot or save action.': 'other',
    'Choose latest, baseline or checkpoint.': 'other',
    'Invalid save option.': 'other',
    'Unsupported snapshot kind.': 'other',
    'A design export goes to its own checkpoint folder.': 'other',
    'The baseline already exists or changed. Review it and explicitly confirm replacement.': 'other',
    'Choose a short literal checkpoint name.': 'other',
    'This checkpoint already exists. Choose a new name.': 'other',
    'This capture removes previously saved devices. Review the new device scope before allowing removal.': 'other',
    'Use a short single-line commit note.': 'other',
    'A complete manifest and file map are required.': 'other',
    'Unsupported snapshot schema.': 'other',
    'The snapshot requires between 1 and 500 bounded files.': 'other',
    'The file map must exactly match the manifest.': 'other',
    'Snapshot filenames must be unique plain filenames.': 'other',
    'Missing or oversized snapshot file.': 'other',
    'Invalid snapshot file encoding.': 'other',
    'Snapshot exceeds the transfer limits.': 'other',
    'Snapshot file length or checksum did not match its manifest.': 'other',
    'Invalid snapshot file metadata.': 'other',
    'Use a safe relative repository path.': 'other',
    'Use literal repository paths without traversal or hidden Git paths.': 'other',
    'Unsupported Git operation.': 'other',
    'The Git helper and bindings must be root-owned and not writable by other users.': 'other',
    'Git repository registry is too large.': 'other',
    'Invalid Git repository registry.': 'other',
    'Could not drop Git worker privileges.': 'other',
    'Invoke the installed Git helper through the discovery gateway.': 'other',
    'Git request exceeds 24 MiB.': 'other',
    'A structured Git request is required.': 'other',
    'The Git response is too large to transfer. Select a smaller snapshot.': 'other',
    'The Git helper could not finish. Check installation and repository permissions as its owner.': 'other',
}
# The manager's own sentences for the same calls (`remote_git`, `invoke`, `repositories`, the upload check).
MANAGER_PROBLEMS = {
    'Connect the VM and verify its SSH host fingerprint first.': 'vm',
    VM_UNREACHABLE: 'vm',
    'Git connection interrupted. Retry this saved operation to reconcile its result.': 'vm',
    'Install or refresh the matching Git helper on the VM.': 'vm',
    'Git helper is unavailable. Run setup-git.sh on the VM.': 'vm',
    'Invalid Git helper response.': 'vm',
    'Git helper response exceeded its limit.': 'vm',
    'Update the VM Git helper to match manager ': 'vm',
    'The VM identity changed. Return to the original VM or reconnect the repository.': 'settings',
    'Git snapshot exceeds the transfer limit.': 'other',
    ANOTHER_SAVE: 'busy',
    NOT_OURS: 'busy',
}
PROBLEM_CODES = {**HELPER_PROBLEMS, **MANAGER_PROBLEMS}


def problem_code(problem):
    """The chip's code for a sentence a helper call answered (`PROBLEM_CODES`); `other` for one the table does not hold."""
    problem = str(problem or '')
    if problem in PROBLEM_CODES: return PROBLEM_CODES[problem]
    return next((code for sentence, code in PROBLEM_CODES.items() if sentence in problem), 'other')


def note_value(value):
    """A save's name as a person typed it: one line, at most NOTE_LIMIT characters, no control character; '' is allowed
    (the manager then names the save from what changed)."""
    value = str(value or '')
    if any(ord(c) < 32 or ord(c) == 127 for c in value): raise HTTPException(400, 'Use a single-line save note.')
    value = value.strip()
    if len(value) > NOTE_LIMIT: raise HTTPException(400, 'Use a name of at most ' + str(NOTE_LIMIT) + ' characters.')
    return value


CONFIG_SUFFIXES = {p[key] for p in PLATFORMS.values() for key in ('suffix', 'snapshot_suffix') if p.get(key)}
RESTORE_SUFFIXES = {p.get('restore_suffix', 'restore') for p in PLATFORMS.values()}


def file_role(name):
    """What a saved file is, from the name the manager itself gave it (`captured_snapshot`, `topology_names`):
    `(role, node)` with role one of device, restore, topology, map, manifest, other, and `node` the device's label for
    a device file and its restore artifact."""
    name = str(name or '').rsplit('/', 1)[-1]
    if name == 'manifest.json': return 'manifest', ''
    if name.endswith('.clab.yml.annotations.json'): return 'map', ''
    if name.endswith('.clab.yml'): return 'topology', ''
    suffix = name.rsplit('.', 1)[1] if '.' in name else ''
    if suffix in RESTORE_SUFFIXES: return 'restore', file_label(name)
    if suffix in CONFIG_SUFFIXES: return 'device', file_label(name)
    return 'other', ''


def manifest_changes(old, new):
    """What changed between two capture manifests, pairing entries by device (`node`) and by `kind` for the topology
    and the map, never by file name (a device's file was renamed between releases): labels and flags only.
    `devices` are the labels of every device that was added, removed or changed (its restore artifact is never a
    second change), `removed_devices` those that left; `first` when there was no manifest before."""
    def entries(manifest):
        devices = {}; kinds = {}
        for item in (manifest or {}).get('files', []) if isinstance((manifest or {}).get('files'), list) else []:
            if not isinstance(item, dict) or not isinstance(item.get('path'), str): continue
            if item.get('kind'): kinds[str(item['kind'])] = item
            else: devices[str(item.get('node') or 'file:' + file_label(item['path']))] = item
        return devices, kinds
    def same(a, b): return a.get('sha256') == b.get('sha256') and a.get('restore_sha256') == b.get('restore_sha256')
    before, before_kinds = entries(old); after, after_kinds = entries(new)
    # An entry saved without its device name (schema 1) is found by its file's label instead.
    by_label = {file_label(item['path']): key for key, item in before.items() if key.startswith('file:')}
    changed = []; seen = set()
    for key, item in after.items():
        match = key if key in before else by_label.get(file_label(item['path']))
        if match is not None: seen.add(match)
        if match is None or not same(before[match], item): changed.append(file_label(item['path']))
    removed = [file_label(item['path']) for key, item in before.items() if key not in seen]
    def differs(kind):
        a, b = before_kinds.get(kind), after_kinds.get(kind)
        return (a is None) != (b is None) or bool(a and b and a.get('sha256') != b.get('sha256'))
    return dict(first=old is None, devices=sorted(set(changed + removed)), removed_devices=sorted(set(removed)),
                topology=differs('topology'), map=differs('annotations'))


def change_name(changes):
    """The name of a save nobody named, from what changed (`manifest_changes`): `ceos changed`, `ceos and xrv9k
    changed`, `ceos, cjunos and xrv9k changed`, `4 devices changed`, `Topology changed`, `Map changed`, `Topology and
    map changed`, devices first when both; `First save` without an earlier save and '' when nothing changed."""
    if changes['first']: return 'First save'
    names = changes['devices']
    devices = ('' if not names else names[0] + ' changed' if len(names) == 1 else
               ', '.join(names[:-1]) + ' and ' + names[-1] + ' changed' if len(names) <= 3 else str(len(names)) + ' devices changed')
    files = 'topology and map changed' if changes['topology'] and changes['map'] else 'topology changed' if changes['topology'] else 'map changed' if changes['map'] else ''
    if devices and len(devices + ', ' + files) > NOTE_LIMIT: devices = str(len(names)) + ' devices changed'
    return devices + ', ' + files if devices and files else devices or (files[:1].upper() + files[1:])


def checkpoint_slug(note):
    """A checkpoint's folder name made from a save's name: its words in lower case joined by `-`, in the helper's own
    alphabet (`SLUG`). `checkpoint` when the name holds nothing usable."""
    slug = re.sub(r'[^A-Za-z0-9_]+', '-', str(note or '').lower()).strip('-_')[:80].rstrip('-_')
    return slug if SLUG.fullmatch(slug) else 'checkpoint'


def free_checkpoint(slug, taken):
    """`slug`, or the first of `slug-2`, `slug-3`, … that no known checkpoint has (names compare without case: the
    VM's file system may not tell them apart)."""
    taken = {str(name).lower() for name in taken}
    return next(name for name in (slug if n == 1 else slug + '-' + str(n) for n in range(1, len(taken) + 3)) if name.lower() not in taken)


def review_files(files, job):
    """The files of a save's review: the helper's comparison (one folder, paired and diffed, `annotated_compare`) with
    each file's `role`, `node` and repository `path`, then one row without a diff for every other path the save
    changed (the manifest, the second folder of a checkpoint), so the review lists everything the commit holds."""
    design = job.get('kind') == 'design'; folder = str(job.get('snapshot_path') or '')
    rows = []; shown = set()
    def described(row, name, path):
        role, node = file_role(name)
        if design and role != 'manifest': role, node = 'other', ''
        return dict(row, name=name, path=path, role=role, node=node, label=row.get('label') or file_label(name))
    for item in annotated_compare(files):
        name = str(item.get('name', '')); path = (folder + '/' if folder else '') + name
        shown.add(path)
        if item.get('renamed_from'): shown.add((folder + '/' if folder else '') + str(item['renamed_from']))
        rows.append(described(item, name, path))
    for path in job.get('changed_files') or []:
        if not isinstance(path, str) or path in shown: continue
        shown.add(path)
        rows.append(described(dict(status=''), path.rsplit('/', 1)[-1], path))
    return rows


def save_summary(files, first=False):
    """What a save changed, for the sentence under it (DESIGN.md 3.8 N4): labels and counts only, never configuration
    text. Each device counts once: lines are counted on its human configuration file, its restore artifact only says
    that the device changed."""
    devices = {}; removed = set(); added = lines_removed = 0; topology = map_ = False
    for item in files:
        role = item.get('role'); diff = item.get('diff') if isinstance(item.get('diff'), dict) else None
        if role == 'topology': topology = topology or bool(diff)
        elif role == 'map': map_ = map_ or bool(diff)
        elif role in ('device', 'restore') and diff:
            devices.setdefault(item['node'], set()).add(item.get('status'))
            if role == 'device':
                added += int(diff.get('added') or 0); lines_removed += int(diff.get('removed') or 0)
                if item.get('status') == 'removed': removed.add(item['node'])
    return dict(devices=sorted(devices), added=added, removed=lines_removed, topology=topology, map=map_, first=bool(first),
                removed_devices=sorted(removed))


GIT_JOB_CAP = 200
CHECKOUT_VIEW_SECONDS = 10


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


def folder_value(value):
    value = value.strip().strip('/')
    if value and (len(value) > 500 or '\\' in value or any(not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,180}', part) or part.lower() == '.git' or part in ('.', '..') for part in value.split('/'))):
        raise HTTPException(400, 'Use folder names with letters, numbers, dashes or underscores; use / to nest. No leading slash, no .. and no .git parts.')
    try: base_folder(value)
    except ValueError as exc: raise HTTPException(400, str(exc))
    return value


class HelperProblem(ValueError):
    """What a call to the VM's Git helper answered instead of a result (`invoke`): the sentence is the helper's, or the
    manager's own for a VM it cannot reach. A plain ValueError to every caller; the save worker tells it apart from its
    own refusals, because only this says something about the repository (`seen_status`)."""


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
        # The helper's three answers about a checkout (its registrations, tree and saved states), kept for a few seconds:
        # a folder chooser asks about every typed path, and each answer is a round trip to the VM (`checkout_view`).
        self.views = {}; self.view_lock = threading.Lock()
        # The last answer of the helper's `status` per lab, for the header chip (`git_status`). In memory only: a
        # restart forgets it and the next settings read, save or update asks again; the poll never asks the VM.
        self.statuses = {}
        self.pool = ThreadPoolExecutor(max_workers=1)
        with store.lock:
            store.state.setdefault('git_save_names', {})
            bindings = {lab['id']: lab['git_binding'] for lab in store.state.get('labs', []) if isinstance(lab.get('git_binding'), dict)}
            for job in store.state.setdefault('git_jobs', []):
                # A save carries its own binding (DESIGN.md 3.1). One made by an older release stored only the digest
                # of its lab's binding: while that is still the lab's binding it is copied in (additive: the digest
                # the save stores stays true), so the save survives the lab's next folder, device or repository change.
                if ('binding' not in job and (job_pending(job) or kept_on_vm(job)) and job.get('lab_id') in bindings
                        and digest(bindings[job['lab_id']]) == job.get('binding_digest')):
                    job['binding'] = copy.deepcopy(bindings[job['lab_id']])
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
            raise HelperProblem(message[:600])
        except Exception:
            raise HelperProblem(VM_UNREACHABLE)

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
        """Remove lab and Start fresh drop the manager's record of a save: they wait while one still needs attention."""
        if pending_progress(self.store.state, lab_id): raise HTTPException(409, STILL_WAITING)

    def job_binding(self, job, refusal='Repository settings changed. Reconnect the original destination.'):
        """The binding a save is executed, retried and reviewed with: the copy it carries (DESIGN.md 3.1). A save of an
        older release carries none and keeps the old rule: its lab's binding, while that is still the one it was made
        with. Call with the store lock held."""
        if isinstance(job.get('binding'), dict): return copy.deepcopy(job['binding'])
        binding = self.binding(job['lab_id'])
        if digest(binding) != job.get('binding_digest'): raise HTTPException(409, refusal)
        return binding

    def waiting_saves(self, binding, but=None):
        """The saves the manager holds that wait for upload in the checkout `binding` points into, whichever lab made
        them and wherever that lab saves now, oldest first: pending, not uploaded, and holding or possibly holding a
        commit there (`may_hold_commit`). Call with the store lock held."""
        return [j for j in self.store.state['git_jobs'] if j.get('id') != but and job_pending(j) and not j.get('pushed')
                and j.get('target') != 'update' and may_hold_commit(j) and self.made_in(j, binding)]

    def head_save(self, head, binding, prefer=None):
        """The manager's save whose commit is the checkout's HEAD: `prefer` when it is that save, else the newest one
        not uploaded yet (waiting, or kept with Keep snapshot only), else the newest uploaded one; None when no save of
        the manager made that commit. Only the save at HEAD can be pushed, and its push carries every earlier one."""
        if not head: return None
        if prefer is not None and prefer.get('commit') == head: return prefer
        found = [j for j in self.store.state['git_jobs'] if j.get('commit') == head and j.get('target') != 'update' and self.made_in(j, binding)]
        return next((j for j in reversed(found) if not j.get('pushed') and (job_pending(j) or kept_on_vm(j))), found[-1] if found else None)

    def seen_status(self, lab_id, status=None, problem=None):
        """Remember what the helper's `status` (or a failed save, upload or update) said about a lab's save location."""
        if not lab_id: return
        if problem is None:
            ready = bool((status or {}).get('ready')); problem = '' if ready else str((status or {}).get('problem') or 'The repository needs attention.')
        else: ready = False
        with self.store.lock: problem = scrub(str(problem), self.store.state)[:600]
        self.statuses[lab_id] = dict(checked=now(), ready=ready, problem=problem, code=problem_code(problem) if problem else '')

    def git_status(self, lab_id):
        """`git_status` of a lab in /api/state: the last check (never made by the poll; `ready` is None until one was
        made) and how many saves wait for upload in the lab's checkout, any lab's."""
        seen = self.statuses.get(lab_id) or dict(checked='', ready=None, problem='', code='')
        with self.store.lock:
            binding = (self.store.lab(lab_id) or {}).get('git_binding')
            waiting = len(self.waiting_saves(binding)) if binding else sum(1 for j in self.store.state['git_jobs'] if j.get('lab_id') == lab_id and job_pending(j) and not j.get('pushed') and j.get('target') != 'update' and may_hold_commit(j))
        return dict(seen, waiting=waiting)

    def public(self, job):
        """A save as a page sees it: the allowlisted fields plus what only the rest of the state can tell. `captured`:
        the save read the devices itself (absent for a save of an older release whose capture is gone);
        `capture_kept`: its capture still exists with its files, so a checkpoint can be made from it without reading a
        device; `capture_whole`: that capture carries the topology when the lab has one (DESIGN.md 3.5, 3.9). Call with
        the store lock held."""
        result = public_job(job)
        if job.get('target') == 'update': return result
        backup = next((b for b in self.store.state['jobs'] if b['id'] == job.get('backup_job_id')), None) if job.get('backup_job_id') else None
        if 'own_capture' in job: result['captured'] = bool(job['own_capture'])
        elif job.get('kind') == 'design' or job.get('target') == 'move': result['captured'] = False
        elif backup is not None: result['captured'] = backup.get('progress_id') == job['id']
        kept = bool(backup and backup.get('operation') == 'backup' and backup.get('status') in ('succeeded', 'partial')
                    and (self.store.root / 'backups' / str(backup.get('lab_id')) / 'history' / str(backup['id'])).is_dir())
        result['capture_kept'] = kept
        result['capture_whole'] = kept and self.capture_whole(self.store.lab(job.get('lab_id')), backup)
        return result

    @staticmethod
    def capture_whole(lab, backup):
        """Whether a capture carries the whole lab: the topology file whenever the lab has topology text, and no
        record that the topology or the map could not be written with it."""
        if backup.get('topology_missing') in ('error', 'map-error'): return False
        embedded = backup.get('topology') if isinstance(backup.get('topology'), dict) else {}
        return bool(embedded.get('file')) or not (lab or {}).get('definition_yaml')

    def remember_name(self, commit, name):
        """A renamed save's name by its commit, so the name outlives the job (the cap, Remove lab). Newest last, the
        oldest go first. Call with the store lock held; the caller saves."""
        names = self.store.state.setdefault('git_save_names', {})
        names.pop(commit, None)
        if name: names[commit] = name
        for old in list(names)[:-MAX_SAVE_NAMES]: del names[old]

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

    def settle_kept(self, job, commit, where):
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
        with self.store.lock: return self.public(job)

    def execute(self, job_id):
        result = None; binding = None
        try:
            with self.store.lock:
                job = copy.deepcopy(self.get_job(job_id))
                # The save's own binding (DESIGN.md 3.1): where the lab saves now does not matter to a save already made.
                # A save of an older release carries none and is sent only while its lab's binding is still the same.
                if isinstance(job.get('binding'), dict): binding = copy.deepcopy(job['binding'])
                else:
                    binding = self.binding(job['lab_id'])
                    if digest(binding) != job['binding_digest']: raise ValueError('Repository settings changed; this save was not sent.')
            # A retry with a commit never recaptures or rewrites working files.
            if job.get('commit'):
                # The only place the helper's `push` is asked for: a retry the upload route queued (`retry_push`) for a
                # save whose review is recorded. Nothing else in the manager uploads.
                if job.get('retry_push') and job.get('reviewed'):
                    self.update(job_id, status='pushing', message='Pushing the saved commit.')
                    result = self.invoke({'mode': 'push', 'operation_id': job_id}, binding)
                else:
                    result = dict(status='committed', commit=job['commit'], pushed=False,
                                  changed_files=job.get('changed_files', []), snapshot_path=job.get('snapshot_path', ''))
                self.finish(job, result, binding)
                return
            if job.get('target') == 'move':
                # Attempted from here on: whatever stops the move (a repository that needs attention, an answer lost
                # after the VM committed) leaves it retryable, never failed; the helper's move journal makes the
                # retry idempotent. A move never uploads by itself: its commit waits for Upload like a save, because
                # its push would carry every save below it (DESIGN.md 3.4).
                self.update(job_id, status='exporting', published_attempt=True, message='Moving the saved folders inside the repository.')
                status = self.invoke({'mode': 'status'}, binding); self.seen_status(job['lab_id'], status)
                if not status.get('ready'): raise ValueError(status.get('problem') or 'Repository needs attention before moving folders.')
                request = copy.deepcopy(job['request'])
                request.update(mode='move', operation_id=job_id, expected_head=status.get('head', ''))
                result = self.invoke(request, binding)
                if result.get('commit'):
                    self.update(job_id, commit=result['commit'], changed_files=result.get('changed_files', []), snapshot_path=result.get('snapshot_path', ''))
                self.finish(job, result, binding)
                return
            if job.get('kind') == 'design':
                # A design export: the plan's files instead of a capture; the same review, publication and upload.
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
                    status = self.invoke({'mode': 'status'}, binding); self.seen_status(job['lab_id'], status)
                    if not status.get('ready'): raise ValueError(status.get('problem') or 'Repository needs attention before exporting.')
                    expected_head = status.get('head', '')
                    self.update(job_id, expected_head=expected_head)
                else: expected_head = job['expected_head']
                request.update(mode='publish', operation_id=job_id, expected_head=expected_head, snapshot=snapshot)
                self.update(job_id, published_attempt=True)   # a lost answer leaves the job pending, never failed: the VM may hold the commit
                result = self.invoke(request, binding)
                if result.get('commit'):
                    self.update(job_id, commit=result['commit'], changed_files=result.get('changed_files', []), snapshot_path=result.get('snapshot_path', ''))
                self.finish(job, result, binding)
                return
            backup_id = job.get('backup_job_id', '')
            if not backup_id:
                if job.get('retry'):
                    raise ValueError('No complete capture is available for retry. Start a new save.')
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
            # The whole lab in every save (DESIGN.md 3.9): a capture whose topology or map could not be written with
            # it never reaches the repository, where it would delete the files `latest` holds. A lab without topology
            # text (`no-text`) saves its device configurations as before.
            if backup.get('topology_missing') in ('error', 'map-error'):
                self.update(job_id, status='capture_incomplete', message=TOPOLOGY_FAILED, finished=now())
                return
            if set(snapshot['manifest']['node_names']) != set(job['node_names']):
                raise ValueError('This capture does not contain exactly the configured device scope.')
            # A lab state says so in its manifest (the name the person gave it), identically on every retry, so every
            # lab, the one that saved it included, lists a lab state there and never its own earlier folder.
            if job.get('kind') == 'state': snapshot['manifest']['state'] = str(job.get('state_name') or job.get('note') or '')[:NOTE_LIMIT]
            fingerprint = digest(snapshot)
            if job.get('snapshot_digest') and fingerprint != job['snapshot_digest']:
                raise ValueError('The saved capture changed on disk. It will not replace the repository snapshot.')
            self.update(job_id, status='exporting', snapshot_digest=fingerprint, message='Saving captured configurations to the VM repository.')
            request = copy.deepcopy(job['request'])
            if 'expected_head' not in job:
                status = self.invoke({'mode': 'status'}, binding); self.seen_status(job['lab_id'], status)
                if not status.get('ready'): raise ValueError(status.get('problem') or 'Repository needs attention before exporting.')
                expected_head = status.get('head', '')
                # The save's name, once, before the first publication (its body must never change afterwards: the
                # helper compares its digest on every retry): what the person typed, else what changed against the
                # manifest of `latest` the status just returned. The automatic name is kept privately so a rename
                # can return to it. A save that changed nothing stays unnamed.
                previous = status.get('latest_manifest') if isinstance(status.get('latest_manifest'), dict) else None
                changes = manifest_changes(previous, snapshot['manifest'])
                named = dict(expected_head=expected_head, auto_note=change_name(changes), first_save=changes['first'])
                if not str(job.get('note') or '').strip():
                    named.update(note=named['auto_note'], note_auto=True)
                    request['message'] = named['auto_note'] or 'Save ' + str(job.get('lab_name') or 'lab') + ' progress'
                    named['request'] = copy.deepcopy(request)
                self.update(job_id, **named)
            else: expected_head = job['expected_head']
            if not request.get('message'): request['message'] = 'Save ' + str(job.get('lab_name') or 'lab') + ' progress'
            request.update(mode='publish', operation_id=job_id, expected_head=expected_head, snapshot=snapshot)
            result = self.invoke(request, binding)
            if result.get('commit'):
                self.update(job_id, commit=result['commit'], changed_files=result.get('changed_files', []),
                            snapshot_path=result.get('snapshot_path', ''))
                self.summarize(job_id, binding, result)
            self.finish(job, result, binding)
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
            # What stopped the save is what the chip says about the lab's save location (a helper answer only: a
            # manager fault says nothing about the repository).
            if isinstance(exc, HelperProblem) and not self.stopping.is_set(): self.seen_status(existing.get('lab_id'), problem=message)
        finally:
            self.forget_views()
            try: self.store.event('git.progress', 'Git save stage completed; see its saved operation status.', lab_id=job.get('lab_id', '') if 'job' in locals() else '', job_id=job_id)
            except OSError: pass

    def summarize(self, job_id, binding, result):
        """After a save committed: ask the helper's comparison once and keep what changed as counts and labels on the
        job (public `summary`), so the sentence under the save needs no request. A save that changed nothing has none,
        and a comparison that fails leaves it absent: the save stands. A checkpoint or a starting point compares its
        own new folder, so the device lines of such a save are those of the files it wrote."""
        if result.get('status') == 'unchanged' or not result.get('changed_files'): return
        try:
            with self.store.lock: job = copy.deepcopy(self.get_job(job_id))
            if 'summary' in job: return
            answer = self.invoke({'mode': 'compare', 'operation_id': job_id}, binding)
            files = review_files(answer.get('files', []) if isinstance(answer.get('files'), list) else [], job)
            self.update(job_id, summary=save_summary(files, first=bool(job.get('first_save')) and job.get('target') == 'latest'))
        except (ValueError, OSError, HTTPException): pass

    def finish(self, job, result, binding):
        commit = result.get('commit', '')
        if commit and not re.fullmatch(r'[0-9a-f]{40,64}', commit): raise ValueError('Git helper returned an invalid commit identifier.')
        pushed = result.get('pushed') is True
        # A save with nothing new reuses HEAD. It has nothing to review and nothing to upload when the
        # manager already knows that exact commit was uploaded through this same binding; only then is it
        # 'unchanged'. A HEAD that was never uploaded keeps the ordinary path: there is still a save to review.
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
        if result.get('status') == 'needs_attention': self.seen_status(job['lab_id'], problem=message)
        elif pushed: self.seen_status(job['lab_id'], dict(ready=True))
        with self.store.lock:
            stored = self.get_job(job['id'])
            # A renamed save is known by its commit from now on (`git_save_names`); a save that only reused HEAD made none.
            if stored.get('renamed') and commit and stored.get('changed_files') and stored.get('note'):
                self.remember_name(commit, stored['note'])
                try: self.store.save()
                except OSError: pass
        if pushed:
            with self.store.lock:
                # The helper names every journaled save the remote now holds: this push carried every earlier commit of
                # the checkout, whichever lab made it and wherever that lab saves now. Each is matched by the checkout it
                # was made in (`made_in`), never by its lab's current binding, and is reviewed with this upload: the
                # review of the save at HEAD named every one of them before the person chose Upload.
                reviewed = self.get_job(job['id']).get('reviewed') or now()
                for previous in self.store.state['git_jobs']:
                    if previous['id'] == job['id'] or previous['id'] not in (result.get('synced_operations') or []) or not self.made_in(previous, binding): continue
                    if previous.get('status') == 'dismissed':
                        # A dismissed save stays dismissed; it is only known as uploaded now, so later reviews stop counting it.
                        previous.update(pushed=True, message='Snapshot kept; its commit is included in the verified remote history.')
                        continue
                    previous.update(status='synced', pushed=True, message='Saved commit is included in the verified remote history.', finished=now())
                    previous.setdefault('reviewed', reviewed)
                self.store.save()
            self.settle_kept(job, commit, binding)

    def catalog(self):
        """The helper's registrations for a route: a helper problem is the request's 409."""
        try: return self.repositories()
        except ValueError as exc: raise HTTPException(409, str(exc))

    # Folders made or chosen through the manager, per checkout. Git has no empty folders, so without this
    # list a folder nothing was saved into yet would not be in the tree. They are plans, not directories:
    # the tree reports them as `planned` and the page says they are not in the repository yet.
    def planned_folders(self, path):
        with self.store.lock: return list(self.store.state.get('git_folders', {}).get(path, []))

    def remember_folders(self, path, *prefixes):
        with self.store.lock:
            known = self.store.state.setdefault('git_folders', {}).setdefault(path, [])
            fresh = [p for p in dict.fromkeys(prefixes) if p and p not in known]
            if not fresh: return
            known.extend(fresh); del known[:-MAX_PLANNED_FOLDERS]
            try: self.store.save()
            except OSError: del known[-len(fresh):]

    def bound_labs(self):
        return {lab['git_binding']['binding_id']: dict(id=lab['id'], name=lab['name']) for lab in self.store.state['labs'] if lab.get('git_binding')}

    def catalog_binding(self, binding_id):
        result = self.catalog()
        repo = next((r for r in result['repositories'] if r['id'] == binding_id), None)
        if not repo: raise HTTPException(404, 'This repository is not registered on the VM. Refresh the list.')
        with self.store.lock: before = host_identity(self.store.state.get('host', {}))
        return repo, dict(binding_id=repo['id'], revision=repo['revision'], repository=repo, host_identity=before)

    def bind_lab(self, lab_id, repo, node_names, review, before, event, message):
        """Point the lab at a registration after a live status check; the exposure acknowledgement is the caller's job."""
        binding = dict(binding_id=repo['id'], revision=repo['revision'], repository=repo,
                       host_identity=before, node_names=node_names, review_before_push=True)
        self.seen_status(lab_id, self.call({'mode': 'status'}, binding))
        with self.store.lock:
            # A waiting save does not hold a connection change back: it carries its own binding (DESIGN.md 3.1).
            self.idle()
            if before != host_identity(self.store.state.get('host', {})): raise HTTPException(409, 'VM connection changed. Connect again.')
            lab = self.store.lab(lab_id)
            if not lab: raise HTTPException(404, 'Lab was removed.')
            valid = {n['name'] for n in lab['nodes'] if n.get('platform') in PLATFORMS}
            if len(set(node_names)) != len(node_names) or not node_names or not set(node_names) <= valid:
                raise HTTPException(400, 'Select distinct supported devices from this lab.')
            for other in self.store.state['labs']:
                if other['id'] != lab_id and other.get('git_binding', {}).get('binding_id') == repo['id']:
                    raise HTTPException(409, 'This folder is already connected to another lab (' + other['name'] + '). Choose a different folder.')
            # A lab state on its way into this folder (no commit yet) would write the same `latest` (review F11).
            if any(j.get('kind') == 'state' and job_pending(j) and not j.get('commit') and isinstance(j.get('binding'), dict)
                   and j['binding'].get('binding_id') == repo['id'] for j in self.store.state['git_jobs']):
                raise HTTPException(409, 'A lab state is being saved into this folder right now. Try again when it has finished, or choose another folder.')
            old = lab.get('git_binding'); lab['git_binding'] = binding
            try: self.store.save()
            except OSError:
                if old is None: lab.pop('git_binding', None)
                else: lab['git_binding'] = old
                raise HTTPException(500, 'Could not save the repository connection.')
        self.forget_views()
        self.store.event(event, message, lab_id=lab_id)
        return binding

    def retired_already(self, binding, prefix, catalog=None):
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

    def rebind(self, lab_id, repo, node_names, before, message):
        """Point the lab at the registration of its new folder. Nothing refuses here: every check ran before the VM
        was asked, `binding_lock` keeps every other connection change (link, connect, unlink) out meanwhile, and this
        lab's saves and design exports refuse while it changes (`refuse_while_rebinding`). A new binding dict: the one
        the lab had is never edited, because waiting saves were made with it."""
        binding = dict(binding_id=repo['id'], revision=repo['revision'], repository=repo,
                       host_identity=before, node_names=node_names, review_before_push=True)
        with self.store.lock:
            lab = self.store.lab(lab_id)
            if not lab: raise HTTPException(404, 'Lab was removed.')
            lab['git_binding'] = binding
            try: self.store.save()
            except OSError: raise HTTPException(500, 'The folder changed on the VM, but the manager could not store the change. Free disk space, then reopen this lab before saving.')
        self.forget_views()
        self.store.event('git.destination', message, lab_id=lab_id)
        return binding

    def call(self, request, binding=None):
        try: return self.invoke(request, binding)
        except ValueError as exc: raise HTTPException(409, str(exc))

    def checkout_view(self, binding, fresh=False):
        """What the folder answers are decided from (git_places.py), for the checkout `binding` points into: its
        registrations with the labs connected to them, the committed tree, the saved states with their summaries, the
        folders made through the manager and the lab states being saved right now. The helper's answers are kept for
        CHECKOUT_VIEW_SECONDS per checkout unless `fresh`; the labs, the planned folders and the pending lab states
        come from the store on every call, because they change without the VM."""
        path = binding['repository'].get('path', ''); key = (binding['host_identity'], path)
        with self.view_lock:
            seen = None if fresh else self.views.get(key)
            if seen and time.monotonic() - seen['at'] > CHECKOUT_VIEW_SECONDS: seen = None
        if seen is None:
            catalog = [r for r in self.catalog()['repositories'] if isinstance(r, dict) and r.get('path') == path]
            tree = self.call({'mode': 'browse'}, binding)
            history = self.call({'mode': 'history'}, binding)
            states = {str(v.get('path', '')): v.get('summary') for v in history.get('versions', []) if isinstance(v, dict)}
            seen = dict(at=time.monotonic(), catalog=catalog, head=str(history.get('head') or tree.get('head') or ''), repository=tree.get('repository') or binding['repository'],
                        files=[f.get('path') for f in tree.get('files', []) if isinstance(f, dict) and isinstance(f.get('path'), str)],
                        sizes={f.get('path'): f.get('size', 0) for f in tree.get('files', []) if isinstance(f, dict) and isinstance(f.get('path'), str)},
                        dirs=tree.get('dirs') if isinstance(tree.get('dirs'), list) else None,
                        truncated=bool(tree.get('truncated')), saved=tree.get('saved', {}), states=states)
            with self.view_lock: self.views[key] = seen
        with self.store.lock:
            labs = self.bound_labs()
            planned = list(self.store.state.get('git_folders', {}).get(path, []))
            pending = [dict(prefix=j['binding']['repository'].get('prefix', ''), name=str(j.get('note') or ''))
                       for j in self.store.state.get('git_jobs', [])
                       if j.get('kind') == 'state' and job_pending(j) and isinstance(j.get('binding'), dict)
                       and j['binding'].get('repository', {}).get('path') == path and j['binding'].get('host_identity') == binding['host_identity']]
        registrations = [dict(id=r['id'], prefix=r.get('prefix', ''), revision=r.get('revision', ''), lab=labs.get(r['id'])) for r in seen['catalog']]
        return dict(registrations=registrations, files=seen['files'], sizes=seen['sizes'], dirs=seen['dirs'], states=seen['states'], planned=planned,
                    pending_states=pending, truncated=seen['truncated'], head=seen['head'], repository=seen['repository'], saved=seen['saved'])

    def forget_views(self):
        """After anything that moved a checkout's HEAD or its registrations (a save, a move, an update, a placement)."""
        with self.view_lock: self.views.clear()

    def refuse_while_rebinding(self, lab_id):
        """A save or design export carries the binding it is created with. Created while a connection change gives its
        lab a new one, it would go to the folder the lab is leaving, so it waits for the change (review F14).
        Only that lab's: another lab's binding is not touched, and connecting by URL can clone for minutes."""
        if self.rebinding == lab_id:
            raise HTTPException(409, "This lab's repository connection is being changed. Try again in a moment.")

    def place_lab(self, lab_id, binding):
        """The lab as git_places.py takes it, for the checkout `binding` points into: `prefix` is the folder the lab
        saves to there, or None when it saves elsewhere or nowhere."""
        with self.store.lock:
            lab = self.store.lab(lab_id)
            if not lab: raise HTTPException(404, 'Lab not found.')
            own = lab.get('git_binding') or {}
            here = (own.get('host_identity') == binding['host_identity'] and own.get('repository', {}).get('path') == binding['repository'].get('path'))
            return dict(id=lab['id'], name=lab['name'], prefix=own['repository'].get('prefix', '') if own and here else None)

    def states(self, lab_id, repository=''):
        """Every saved state of a repository as this lab sees it (git_places.state_rows: one name rule for the Load
        panel, All versions and the chooser), read through the lab's own binding or, for a lab without a save location
        or another repository of the VM, through the registration `repository` (`reader`). HEAD comes from the helper's
        `history`, never from `status`, which also checks the registration's own folders (review F17)."""
        binding = self.reader(lab_id, repository)
        view = self.checkout_view(binding)
        rows = git_places.state_rows(self.place_lab(lab_id, binding), view)
        for row in rows:
            summary = row.get('summary') if isinstance(row.get('summary'), dict) else {}
            row['commit'] = view['head']
            row['saved_at'] = summary['captured_at'] if isinstance(summary.get('captured_at'), str) else ''
        return dict(head=view['head'], truncated=bool(view['truncated']), states=rows)

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
            allow_removed: bool = False   # accepted from older pages and ignored: removals are always allowed (DESIGN.md 3.3)

        class Retry(BaseModel):
            model_config = ConfigDict(extra='forbid')
            push: bool = True
            reviewed: bool = False
            head: str = Field(default='', pattern=r'^([0-9a-f]{40,64})?$')   # the HEAD the review showed, with an upload

        class Name(BaseModel):
            model_config = ConfigDict(extra='forbid')
            note: str = Field(default='', max_length=500)

        class State(BaseModel):
            model_config = ConfigDict(extra='forbid')
            request_id: str = Field(pattern=r'^[0-9a-f]{32}$')
            repository: str = Field(default='', max_length=64, pattern=r'^[A-Za-z0-9_-]*$')
            folder: str = Field(default='', max_length=2000)
            name: str = Field(min_length=1, max_length=500)
            choice: str = Field(default='', max_length=20)

        class Dismiss(BaseModel):
            model_config = ConfigDict(extra='forbid')
            acknowledge: bool = False

        class Version(BaseModel):
            model_config = ConfigDict(extra='forbid')
            commit: str = Field(pattern=r'^[0-9a-f]{40,64}$')
            path: str = Field(min_length=1, max_length=250)
            repository: str = Field(default='', max_length=64, pattern=r'^[A-Za-z0-9_-]*$')   # read through this registration (`reader`)

        class Comparison(BaseModel):
            model_config = ConfigDict(extra='forbid')
            job_id: str = Field(default='', max_length=64)
            commit: str = Field(default='', max_length=64)
            path: str = Field(default='', max_length=250)
            repository: str = Field(default='', max_length=64, pattern=r'^[A-Za-z0-9_-]*$')

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

        # The route helpers are methods (other modules place labs too); the routes below keep their short names.
        call = self.call; planned_folders = self.planned_folders; remember_folders = self.remember_folders
        bound_labs = self.bound_labs; catalog_binding = self.catalog_binding; bind_lab = self.bind_lab
        retired_already = self.retired_already; rebind = self.rebind
        refuse_while_rebinding = self.refuse_while_rebinding

        def one_binding_change(route):
            """A route that changes which registration a lab points at (or disconnects it) runs alone (`binding_lock`):
            a folder change checks everything before the VM is asked, nothing may take the new folder meanwhile, and a
            Disconnect from another tab cannot be undone by the rebind that follows."""
            @functools.wraps(route)
            def alone(*args, **kwargs):
                with self.changing(kwargs.get('lab_id')): return route(*args, **kwargs)
            return alone

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
                jobs = [self.public(j) for j in reversed(self.store.state['git_jobs']) if j['lab_id'] == lab_id]
                supported = [{k: n.get(k, '') for k in ('name', 'short_name', 'platform')} for n in lab['nodes'] if n.get('platform') in PLATFORMS]
                unsupported = [n['name'] for n in lab['nodes'] if n.get('platform') not in PLATFORMS]
            status = {}
            if binding:
                try: status = self.invoke({'mode': 'status'}, binding)
                except ValueError as exc: status = {'ready': False, 'problem': str(exc)}
                self.seen_status(lab_id, status)
            return dict(binding=binding, repository_status=status, jobs=jobs, supported_nodes=supported, unsupported_nodes=unsupported)

        @app.put('/api/labs/{lab_id}/git')
        @one_binding_change
        def link(lab_id: str, data: Link):
            with self.store.lock:
                self.idle()
                if not self.store.lab(lab_id): raise HTTPException(404, 'Lab not found.')
                before = host_identity(self.store.state.get('host', {}))
            result = repositories()
            repo = next((r for r in result['repositories'] if r['id'] == data.binding_id), None)
            if not repo: raise HTTPException(400, 'Choose a repository registered by the VM administrator.')
            binding = dict(binding_id=repo['id'], revision=repo['revision'], repository=repo,
                           host_identity=before, node_names=data.node_names, review_before_push=True)
            self.seen_status(lab_id, call({'mode': 'status'}, binding))
            with self.store.lock:
                # A waiting save stays part of the next upload: it carries the binding it was made with (DESIGN.md 3.1).
                self.idle()
                if before != host_identity(self.store.state.get('host', {})): raise HTTPException(409, 'VM connection changed. Connect again.')
                lab = self.store.lab(lab_id)
                if not lab: raise HTTPException(404, 'Lab was removed.')
                valid = {n['name'] for n in lab['nodes'] if n.get('platform') in PLATFORMS}
                if len(set(data.node_names)) != len(data.node_names) or not set(data.node_names) <= valid:
                    raise HTTPException(400, 'Select distinct supported devices from this lab.')
                for other in self.store.state['labs']:
                    if other['id'] != lab_id and other.get('git_binding', {}).get('binding_id') == repo['id']:
                        raise HTTPException(409, 'This folder is already connected to another lab (' + other['name'] + '). Choose a different folder under Save settings.')
                old = lab.get('git_binding'); lab['git_binding'] = binding
                try: self.store.save()
                except OSError:
                    if old is None: lab.pop('git_binding', None)
                    else: lab['git_binding'] = old
                    raise HTTPException(500, 'Could not save the repository connection.')
            self.forget_views()
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
            if data.plan:
                # A folder to save into later: nothing is registered or written on the VM. A name that exists already
                # (committed, a lab folder, or planned) is not refused: the answer says that folder is the one meant.
                if not prefix: raise HTTPException(400, 'Enter a folder name.')
                seen = call({'mode': 'browse'}, binding)
                if (prefix in {f.get('prefix') for f in seen.get('folders', []) if isinstance(f, dict)}
                        or any(str(f.get('path', '')).startswith(prefix + '/') for f in seen.get('files', []) if isinstance(f, dict))):
                    return {'selected': prefix}
                if prefix in planned_folders(repo['path']): return {'planned': prefix}
                remember_folders(repo['path'], prefix)
                if prefix not in planned_folders(repo['path']): raise HTTPException(500, 'The folder could not be stored. Nothing was created.')
                self.store.event('git.folder', 'Repository folder planned for later saves.', lab_id='')
                return {'planned': prefix}
            created = call({'mode': 'register-prefix', 'prefix': prefix}, binding)
            if not isinstance(created, dict) or not created.get('id'): raise HTTPException(409, 'The VM did not answer with the new folder. Try again.')
            remember_folders(repo['path'], prefix); self.forget_views()
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
                """Everything that can stop the change. It runs before the VM is asked, never after. A waiting save does
                not stop it: it carries its own binding and stays part of the next upload (DESIGN.md 3.1), and nothing
                is retired on the VM (2.4), so its commit stays uploadable."""
                with self.store.lock:
                    self.idle(lab_id if data.move_files else None); binding = self.binding(lab_id)
                    lab = self.store.lab(lab_id)
                    if binding['host_identity'] != host_identity(self.store.state.get('host', {})):
                        raise HTTPException(409, 'Reconnect the original VM before changing the folder.')
                    return binding, lab['name'], {n['name'] for n in lab['nodes'] if n.get('platform') in PLATFORMS}

            binding, name, valid = refusals()
            # Devices that left the lab since it was connected leave the selection with the change (DESIGN.md 3.3);
            # when none is left the selection stays as it was and the next save says so.
            before = binding['host_identity']; node_names = [n for n in dict.fromkeys(binding.get('node_names') or []) if n in valid] or list(binding.get('node_names') or [])
            source = binding['repository'].get('prefix', '')
            catalog = repositories()['repositories']
            # The lab's registration can be gone: an older release retired it with a folder change whose answer, and the
            # check after it, were lost. Every call with it only answers UNREGISTERED, so the change asked for now is
            # checked against the VM's catalog and followed.
            registered = any(r['id'] == binding['binding_id'] for r in catalog)
            # The folder the lab saves to already is no refusal: it is the one meant, and nothing changes.
            if registered and prefix == source: return {'saved': True, 'binding': binding, 'job': None}
            with self.store.lock: labs = bound_labs()
            for repo in catalog:
                if repo['path'] == binding['repository'].get('path') and repo['prefix'] == prefix and labs.get(repo['id'], {}).get('id') not in (None, lab_id):
                    raise HTTPException(409, 'This folder is already connected to another lab (' + labs[repo['id']]['name'] + '). Choose a different folder.')
            # Once more right before the VM is asked: the helper round trip above takes time.
            if digest(refusals()[0]) != digest(binding): raise HTTPException(409, 'The repository connection changed meanwhile. Choose the folder again.')
            if not registered:
                created = retired_already(binding, prefix, catalog)
                if not created:
                    raise HTTPException(409, "This lab's folder is no longer set up on the VM: an earlier folder change probably went "
                                        'through there without reporting back. If so, choose that folder again; if not, connect the lab again '
                                        '(Use a different repository… in Save settings).')
            else:
                # The new folder is registered beside the old one; nothing is retired (DESIGN.md 2.4), so commits made
                # through the folder the lab leaves stay uploadable. A folder that is registered already is reused.
                try: created = self.invoke({'mode': 'register-prefix', 'prefix': prefix}, binding)
                except ValueError as exc:
                    created = retired_already(binding, prefix)
                    if not created: raise HTTPException(409, str(exc))
            if not isinstance(created, dict) or not created.get('id'): raise HTTPException(409, 'The VM did not answer with the new folder. Try again.')
            # Keep the folder the lab leaves (and the new one) in the tree while they are empty.
            remember_folders(binding['repository'].get('path', ''), source, prefix)
            new_binding = rebind(lab_id, created, node_names, before, 'Lab repository folder changed to ' + (prefix or 'the repository root') + '.')
            job = None
            if data.move_files:
                # No refusal here either: the lab already saves to the new folder, and a move that is not queued
                # could never be asked for again. The job queues behind running work. It never uploads by itself
                # (`want_push` false): its commit waits for Upload like a save (DESIGN.md 3.4, review F2).
                with self.store.lock:
                    request = dict(source_prefix=source, push=False, message='Move ' + name + ' progress to ' + (prefix + '/' if prefix else 'the repository root'))
                    job = dict(id=uuid.uuid4().hex, lab_id=lab_id, lab_name=name, created=now(), status='queued', message='Folder move queued.',
                               backup_job_id='', target='move', checkpoint='', note='', pushed=False, review_before_push=False,
                               binding_digest=digest(new_binding), binding=copy.deepcopy(new_binding), request=request, want_push=False,
                               node_names=node_names, capture_context={},
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
                self.idle()
                lab = self.store.lab(lab_id)
                if not lab: raise HTTPException(404, 'Lab not found.')
                before = host_identity(self.store.state.get('host', {}))
                supported = [n['name'] for n in lab['nodes'] if n.get('platform') in PLATFORMS]
                previous = lab.get('git_binding') or {}
                node_names = list(data.node_names) or [n for n in previous.get('node_names', []) if n in supported] or supported
                review = data.review_before_push if data.node_names else previous.get('review_before_push', data.review_before_push)
            created = call({'mode': 'connect', 'url': data.url.strip(), 'prefix': prefix})
            if not isinstance(created, dict) or not created.get('id'): raise HTTPException(409, 'The VM did not answer with the repository. Try again.')
            binding = bind_lab(lab_id, created, node_names, review, before, 'git.connect', 'Lab connected to a repository from the manager.')
            return {'saved': True, 'binding': binding}

        @app.post('/api/labs/{lab_id}/git/unlink')
        @one_binding_change
        def unlink(lab_id: str):
            with self.store.lock:
                # A waiting save keeps waiting and stays uploadable after the disconnect (DESIGN.md 3.1, 7.6).
                self.idle()
                lab = self.store.lab(lab_id)
                if not lab: raise HTTPException(404, 'Lab not found.')
                old = lab.pop('git_binding', None)
                try: self.store.save()
                except OSError:
                    if old: lab['git_binding'] = old
                    raise HTTPException(500, 'Could not disconnect the repository.')
            self.statuses.pop(lab_id, None)
            return {'unlinked': True}

        def selection(lab, names):
            """The devices a save reads: the binding's selection without the devices that left the lab (DESIGN.md 3.3)."""
            known = {n['name'] for n in lab['nodes'] if n.get('platform') in PLATFORMS}
            kept = [n for n in dict.fromkeys(names or []) if n in known]
            if not kept: raise HTTPException(409, NO_DEVICES)
            return kept

        def capture_context(lab, names):
            return dict(node_names=sorted(names), excluded_nodes=sorted(n['name'] for n in lab['nodes'] if n['name'] not in names),
                        topology_digest=hashlib.sha256(lab['definition_yaml'].encode()).hexdigest() if lab.get('definition_yaml') else None)

        def known_checkpoints(lab_id, binding):
            """The checkpoint names of the lab's folder that are taken: in its saves the manager holds and, when the VM
            answers, in the repository."""
            prefix = binding['repository'].get('prefix', '').strip('/'); folder = (prefix + '/' if prefix else '') + 'checkpoints/'
            with self.store.lock:
                taken = {j.get('checkpoint') for j in self.store.state['git_jobs'] if j.get('lab_id') == lab_id and j.get('target') == 'checkpoint' and j.get('checkpoint')}
            try: view = self.checkout_view(binding)
            except HTTPException: return taken   # the VM cannot be asked now: the helper still refuses a name that exists
            for path in list(view.get('files') or []) + list(view.get('dirs') or []) + list(view.get('states') or {}):
                if isinstance(path, str) and path.startswith(folder) and path[len(folder):]: taken.add(path[len(folder):].split('/', 1)[0])
            return taken

        @app.post('/api/labs/{lab_id}/git/save')
        def save(lab_id: str, data: Save):
            if data.target not in ('latest', 'checkpoint', 'baseline'): raise HTTPException(400, 'Choose latest, checkpoint or baseline.')
            # A checkpoint made from a save names itself: its folder is made from that save's name (DESIGN.md 3.5).
            derive = data.target == 'checkpoint' and not data.checkpoint and bool(data.backup_job_id)
            if data.target == 'checkpoint' and not derive and not SLUG.fullmatch(data.checkpoint):
                raise HTTPException(400, 'Use a checkpoint name containing letters, numbers, hyphens or underscores.')
            if data.target == 'baseline' and not data.backup_job_id: raise HTTPException(400, 'Select a complete saved capture for the baseline.')
            # The name is optional (owner decision D2): an empty one is written by the manager from what changed.
            note = note_value(data.note); checkpoint = data.checkpoint; note_auto = False
            request_digest = digest(dict(lab_id=lab_id, **data.model_dump()))

            def repeated():
                previous = next((j for j in self.store.state['git_jobs'] if j['id'] == data.request_id), None)
                if previous and previous.get('request_digest') != request_digest: raise HTTPException(409, 'Request ID already belongs to a different save.')
                return previous

            if derive:
                with self.store.lock:
                    previous = repeated()
                    if previous: return self.public(previous)
                    binding = self.binding(lab_id)
                    source = next((j for j in reversed(self.store.state['git_jobs']) if j.get('lab_id') == lab_id and j.get('backup_job_id') == data.backup_job_id
                                   and j.get('kind') not in ('design',) and j.get('target') != 'move' and str(j.get('note') or '').strip()), None)
                    if not note and source: note, note_auto = str(source['note']).strip()[:NOTE_LIMIT], bool(source.get('note_auto'))
                checkpoint = free_checkpoint(checkpoint_slug(note), known_checkpoints(lab_id, binding))
            with self.store.lock:
                previous = repeated()
                if previous: return self.public(previous)
                self.idle(lab_id); refuse_while_rebinding(lab_id); binding = self.binding(lab_id)
                lab = self.store.lab(lab_id)
                if binding['host_identity'] != host_identity(self.store.state.get('host', {})):
                    raise HTTPException(409, 'Reconnect the original VM before saving.')
                names = selection(lab, binding.get('node_names'))
                # Devices of the selection left the lab: the lab gets a new binding without them and the save goes on.
                # The stored one is never edited: waiting saves were made with it.
                old_binding = lab['git_binding']
                if names != list(binding.get('node_names') or []):
                    binding = dict(binding, node_names=names); lab['git_binding'] = copy.deepcopy(binding)
                if data.backup_job_id:
                    backup = next((b for b in self.store.state['jobs'] if b['id'] == data.backup_job_id and b['lab_id'] == lab_id), None)
                    try:
                        if not backup: raise HTTPException(404, 'Capture not found in this lab.')
                        # The whole lab in every save (DESIGN.md 3.9): a capture without the lab's topology is not saved again.
                        if not self.capture_whole(lab, backup): raise HTTPException(400, NOT_WHOLE)
                        try: snapshot = captured_snapshot(self.store, backup)
                        except ValueError as exc: raise HTTPException(400, str(exc))
                        if set(snapshot['manifest']['node_names']) != set(names): raise HTTPException(400, 'Capture must contain exactly the configured devices.')
                    except HTTPException:
                        lab['git_binding'] = old_binding; raise
                context = capture_context(lab, names)
                # A save a person starts never uploads by itself: it stops at review_pending and the upload
                # is a retry that states the review happened. The binding's old preference is not read.
                review = data.push
                # `message` is the commit's subject. For an unnamed save it is written with the name, once, right
                # before the first publication (`execute`); the publication body never changes after that.
                request = dict(target=data.target, checkpoint=checkpoint, push=False,
                               replace_baseline=data.replace_baseline, expected_baseline=data.expected_baseline,
                               allow_removed=True, message=note)
                job = dict(id=data.request_id, request_digest=request_digest, lab_id=lab_id, lab_name=lab['name'],
                           created=now(), status='queued', message='Save queued.', backup_job_id=data.backup_job_id,
                           target=data.target, checkpoint=checkpoint, note=note, note_auto=note_auto, pushed=False,
                           review_before_push=review, binding_digest=digest(binding), request=request,
                           want_push=False,
                           # Private: the binding the save was made with. It is executed, retried, reviewed and uploaded
                           # through this copy, wherever its lab saves afterwards (DESIGN.md 3.1).
                           binding=copy.deepcopy(binding),
                           # Private: whether the save reads the devices itself (public `captured`).
                           own_capture=not data.backup_job_id,
                           # Frozen at capture time from the binding as it is now: never re-derived from a
                           # binding that may have moved by the time the save is reviewed or shown later.
                           destination=job_destination(binding, data.target, checkpoint),
                           # Private: the VM of that checkout, so a save is counted in its reviews only (made_in).
                           host_identity=binding['host_identity'],
                           node_names=copy.deepcopy(names), capture_context=context)
                _append_git_job(self.store.state, job)
                try: self.store.save()
                except OSError:
                    self.store.state['git_jobs'].remove(job); lab['git_binding'] = old_binding
                    raise HTTPException(500, 'Could not save the request. No work was submitted.')
            return self.schedule(job)

        @app.post('/api/labs/{lab_id}/git/state')
        def save_state(lab_id: str, data: State):
            """Save as a lab state… (DESIGN.md 2.9): a normal save into a folder of its own, through a binding of its own.
            The lab's save location is not touched. An answer that needs a choice comes back as `{question}`, status 200."""
            name = note_value(data.name)
            if not name: raise HTTPException(400, 'Give the lab state a name.')
            if data.choice not in ('', 'take'): raise HTTPException(400, 'Choose Replace it or another name.')
            request_digest = digest(dict(lab_id=lab_id, **data.model_dump()))

            def repeated():
                previous = next((j for j in self.store.state['git_jobs'] if j['id'] == data.request_id), None)
                if previous and previous.get('request_digest') != request_digest: raise HTTPException(409, 'Request ID already belongs to a different save.')
                return previous

            with self.store.lock:
                previous = repeated()
                if previous: return self.public(previous)
                self.idle(lab_id)
                lab = self.store.lab(lab_id)
                if not lab: raise HTTPException(404, 'Lab not found.')
                if not data.repository and not lab.get('git_binding'): raise HTTPException(400, 'Choose the repository this lab state is saved in.')
            # One placement at a time, and no save of this lab meanwhile: a lab placed into the folder while the state
            # is registered there would write the same `latest` (review F11).
            with self.changing(lab_id):
                reader = self.reader(lab_id, data.repository)
                with self.store.lock:
                    if reader['host_identity'] != host_identity(self.store.state.get('host', {})):
                        raise HTTPException(409, 'Reconnect the original VM before saving.')
                view = self.checkout_view(reader, fresh=True)
                try: answer = git_places.place_answer(self.place_lab(lab_id, reader), view, data.folder, purpose='state', name=name)
                except ValueError as exc: raise HTTPException(400, str(exc))
                # `free`: go on. `state`: one question, answered with `take` (Replace it). A lab's own folder that the
                # answer could not leave (`own`, `lab`) is asked about too; it cannot be taken for a state.
                if answer['kind'] != 'free' and not (answer['kind'] == 'state' and data.choice == 'take'): return {'question': answer}
                folder = answer['folder']
                catalog = [r for r in self.catalog()['repositories'] if isinstance(r, dict) and r.get('path') == reader['repository'].get('path')]
                created = next((r for r in catalog if r.get('prefix', '') == folder), None)
                # The folder gets its own registration; nothing is retired, whatever else the checkout holds (2.4).
                if created is None: created = call({'mode': 'register-prefix', 'prefix': folder}, reader)
                if not isinstance(created, dict) or not created.get('id'): raise HTTPException(409, 'The VM did not answer with the new folder. Try again.')
                with self.store.lock:
                    previous = repeated()
                    if previous: return self.public(previous)
                    self.idle(lab_id)
                    lab = self.store.lab(lab_id)
                    if not lab: raise HTTPException(404, 'Lab was removed.')
                    if any(other.get('git_binding', {}).get('binding_id') == created['id'] for other in self.store.state['labs']):
                        return {'question': dict(answer, kind='lab')}   # a lab was placed there meanwhile
                    own = lab.get('git_binding') or {}
                    names = selection(lab, own.get('node_names') if own else [n['name'] for n in lab['nodes'] if n.get('platform') in PLATFORMS])
                    binding = dict(binding_id=created['id'], revision=created['revision'], repository=created,
                                   host_identity=reader['host_identity'], node_names=names, review_before_push=True)
                    request = dict(target='latest', checkpoint='', push=False, replace_baseline=False, expected_baseline='', allow_removed=True, message=name)
                    job = dict(id=data.request_id, request_digest=request_digest, lab_id=lab_id, lab_name=lab['name'], kind='state',
                               created=now(), status='queued', message='Save queued.', backup_job_id='', target='latest', checkpoint='',
                               note=name, note_auto=False, state_name=name, pushed=False, review_before_push=True,
                               binding_digest=digest(binding), binding=binding, request=request, want_push=False, own_capture=True,
                               destination=job_destination(binding, 'latest'), host_identity=binding['host_identity'],
                               node_names=copy.deepcopy(names), capture_context=capture_context(lab, names))
                    _append_git_job(self.store.state, job)
                    try: self.store.save()
                    except OSError:
                        self.store.state['git_jobs'].remove(job); raise HTTPException(500, 'Could not save the request. No work was submitted.')
                remember_folders(reader['repository'].get('path', ''), folder); self.forget_views()
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
            if not SLUG.fullmatch(data.checkpoint):
                raise HTTPException(400, 'Use a checkpoint name containing letters, numbers, hyphens or underscores.')
            if any(ord(c) < 32 for c in data.note): raise HTTPException(400, 'Use a single-line note.')
            if self.designs is None: raise HTTPException(503, 'Design exports are not available.')
            request_digest = digest(dict(lab_id=lab_id, generation_id=generation_id, **data.model_dump()))
            with self.store.lock:
                previous = next((j for j in self.store.state['git_jobs'] if j['id'] == data.request_id), None)
                if previous:
                    if previous.get('request_digest') != request_digest: raise HTTPException(409, 'Request ID already belongs to a different save.')
                    return self.public(previous)
                self.idle(lab_id); refuse_while_rebinding(lab_id); binding = self.binding(lab_id)
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
                           binding_digest=digest(binding), binding=copy.deepcopy(binding), request=request, want_push=False, snapshot_digest=digest(snapshot),
                           destination=job_destination(binding, 'checkpoint', data.checkpoint), host_identity=binding['host_identity'],
                           node_names=[], capture_context={})
                _append_git_job(self.store.state, job)
                try: self.store.save()
                except OSError:
                    self.store.state['git_jobs'].remove(job); raise HTTPException(500, 'Could not save the request. No work was submitted.')
            return self.schedule(job)

        @app.get('/api/git/jobs/{job_id}')
        def job_status(job_id: str):
            with self.store.lock: return self.public(self.get_job(job_id))

        @app.post('/api/git/jobs/{job_id}/name')
        def rename(job_id: str, data: Name):
            """Rename a save. Only the name the manager shows changes, never a commit; an empty name returns to the one the
            manager wrote from what changed. Not held by running work: a name can be typed while the next save runs."""
            note = note_value(data.note)
            with self.store.lock:
                job = self.get_job(job_id)
                if job.get('target') == 'update': raise HTTPException(404, 'Git save not found.')
                changes = dict(note=note, note_auto=False, renamed=True) if note else dict(note=str(job.get('auto_note') or ''), note_auto=True, renamed=False)
                old = {k: copy.deepcopy(job[k]) if k in job else None for k in changes}; names = dict(self.store.state.setdefault('git_save_names', {}))
                job.update(changes)
                # By its commit too, so the name outlives the job (a save that only reused HEAD made no commit of its own).
                if job.get('commit') and job.get('changed_files'): self.remember_name(job['commit'], note)
                try: self.store.save()
                except OSError:
                    for key, value in old.items():
                        if value is None: job.pop(key, None)
                        else: job[key] = value
                    self.store.state['git_save_names'] = names
                    raise HTTPException(500, 'Could not store the name. Nothing was changed.')
                return self.public(job)

        @app.post('/api/git/jobs/{job_id}/retry')
        def retry(job_id: str, data: Retry):
            with self.store.lock:
                job = self.get_job(job_id); self.idle(job['lab_id']); move = job.get('target') == 'move'
                # A save kept with Keep snapshot only that holds a commit can still be the one an upload goes through:
                # when its commit is the checkout's HEAD, only its push can carry the saves below it.
                carrier = data.push and bool(job.get('commit')) and kept_on_vm(job)
                # A folder move has no new save to start instead (its folder is the lab's own now), and its journal on
                # the VM makes a retry idempotent: a move an older release marked failed stays retryable.
                if (job['status'] == 'capture_incomplete' or (job['status'] == 'dismissed' and not carrier) or (job['status'] == 'failed' and not move)
                        or job.get('target') == 'update'):
                    raise HTTPException(409, 'Start a new save for this capture outcome.')
                if job['status'] == 'synced' or (job['status'] == 'unchanged' and job.get('pushed')): return self.public(job)
                binding = self.job_binding(job)
                uploading = data.push and bool(job.get('commit'))
                # An upload needs its review: stated with this request, or recorded by an earlier one (an upload that
                # failed after the review). There is no upload without it, for a folder move as for a save.
                if uploading and not (data.reviewed or job.get('reviewed')): raise HTTPException(409, REVIEW_FIRST)
                if not uploading:
                    # A save without a commit has nothing to review yet: its retry saves on the VM and then waits for
                    # the review, whatever the request asked. A retry on the VM only never uploads.
                    changes = dict(review_before_push=True) if data.push and not move else {}
                    self.update(job_id, status='queued', retry=True, retry_push=False, message='Retry queued; the saved capture will be reused.', **changes)
                    return self.schedule(job)
            # An upload is always of the checkout's newest save: Git pushes a branch, the helper pushes only the commit
            # at HEAD, and that push carries every earlier save (DESIGN.md 3.4). So the checkout is asked first, and the
            # upload goes through the manager's save at HEAD, only when HEAD is still what the review showed.
            try: status = self.invoke({'mode': 'status'}, binding)
            except ValueError as exc:
                self.seen_status(job['lab_id'], problem=str(exc)); raise HTTPException(409, str(exc))
            self.seen_status(job['lab_id'], status)
            head = str(status.get('head') or '')
            if not head: raise HTTPException(409, str(status.get('problem') or 'The repository on the VM could not be checked. Try again.'))
            if data.head and data.head != head: raise HTTPException(409, ANOTHER_SAVE)
            with self.store.lock:
                job = self.get_job(job_id); target = self.head_save(head, binding, prefer=job)
                if target is None: raise HTTPException(409, NOT_OURS)
                # A save at HEAD that is uploaded already carries nothing: the asked save reconciles itself (the helper
                # answers that its commit is on the remote).
                if target.get('pushed') or target['status'] == 'synced': target = job
                self.idle(target['lab_id'])
                if target['status'] in GIT_BUSY: raise HTTPException(409, 'Wait for the active backup, Git save or lab operation to finish.')
                if target is not job: self.job_binding(target)   # a save of an older release still needs its lab's binding
                reviewed = target.get('reviewed') or now()
                self.update(target['id'], status='queued', retry=True, retry_push=True, reviewed=reviewed,
                            message='Upload queued; the saved commit will be reused.')
                target = self.get_job(target['id'])
            return self.schedule(target)

        @app.post('/api/git/jobs/{job_id}/dismiss')
        def dismiss(job_id: str, data: Dismiss):
            if not data.acknowledge: raise HTTPException(400, 'Confirm keeping the snapshot without tracking its pending Git save.')
            with self.store.lock:
                self.idle(); self.get_job(job_id)
                self.update(job_id, status='dismissed', message='Snapshot kept; pending Git tracking dismissed. Existing commits are unchanged.')
                return self.public(self.get_job(job_id))

        @app.post('/api/labs/{lab_id}/git/update')
        def update_remote(lab_id: str):
            with self.store.lock:
                self.idle(); binding = self.binding(lab_id)
                # A fast-forward cannot work while a save waits in the checkout (the helper refuses it as diverged), so
                # the action then is Upload (DESIGN.md 3.6, review X9).
                if self.waiting_saves(binding): raise HTTPException(409, WAITING_FIRST)
                ident = uuid.uuid4().hex
                marker = dict(id=ident, lab_id=lab_id, status='exporting', created=now(), message='Updating repository from remote.', target='update')
                _append_git_job(self.store.state, marker)
                try: self.store.save()
                except OSError:
                    self.store.state['git_jobs'].remove(marker)
                    raise HTTPException(500, 'Could not save the update request. No work was submitted.')
            completed = False
            try:
                try:
                    status = self.invoke({'mode': 'status'}, binding); self.seen_status(lab_id, status)
                    result = self.invoke({'mode': 'update', 'expected_head': status['head']}, binding)
                except ValueError as exc:
                    self.seen_status(lab_id, problem=str(exc)); raise HTTPException(409, str(exc))
                completed = True
                self.seen_status(lab_id, dict(ready=True))
                return result
            finally:
                self.forget_views()
                terminal = dict(status='dismissed', finished=now(), message='Repository updated from remote.' if completed else 'Repository update needs attention. Check status before retrying.')
                try: self.update(ident, **terminal)
                except OSError:
                    with self.store.lock: self.get_job(ident).update(terminal)
                    raise

        @app.get('/api/labs/{lab_id}/git/history')
        def history(lab_id: str, repository: str = Query(default='', max_length=64, pattern=r'^[A-Za-z0-9_-]*$')):
            binding = self.reader(lab_id, repository)
            result = call({'mode': 'history'}, binding)
            # Versions come back with their full repository path; label each so a student sees
            # base/final/broken/work rather than an unlabelled "latest".
            for row in result.get('versions', []):
                row['label'] = version_label(row.get('path', ''))
            # A commit is named as the manager names its save: a renamed save keeps its name after its job is gone
            # (`git_save_names`), and a save the manager still holds shows the name it has now.
            with self.store.lock:
                names = dict(self.store.state.get('git_save_names', {}))
                for job in self.store.state['git_jobs']:
                    if job.get('commit') and job.get('changed_files') and job.get('note') and job.get('target') not in ('move', 'update') and self.made_in(job, binding):
                        names.setdefault(job['commit'], str(job['note']))
            for row in result.get('commits', []) if isinstance(result.get('commits'), list) else []:
                if isinstance(row, dict) and row.get('commit') in names: row['name'] = names[row['commit']]
            return result

        def version_data(lab_id, data):
            binding = self.reader(lab_id, data.repository)
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
                    job = copy.deepcopy(self.get_job(data.job_id))
                    lab = self.store.lab(lab_id)
                    if not lab: raise HTTPException(404, 'Lab not found.')
                    # Through the save's own binding, wherever its lab saves now (DESIGN.md 3.1, review F15).
                    binding = self.job_binding(job, 'Reconnect the original repository to review this save.')
                    # Any save made in the same checkout can be opened from a lab of that checkout, because the review
                    # of one save names the others its upload carries.
                    if job['lab_id'] != lab_id and not (lab.get('git_binding') and self.made_in(job, lab['git_binding'])):
                        raise HTTPException(404, 'Git save not found in this lab.')
                    # What an upload carries along: every other save the manager holds that waits in this checkout
                    # (one without a known commit while it may hold one, `may_hold_commit`) and every save kept there with
                    # Keep snapshot only that was not seen uploaded (`kept_saves`), older and newer, whichever lab made
                    # it, connected or not, under whatever binding. It can over-report (a kept save that never
                    # committed); the saves the manager no longer holds come from the helper's `outgoing` list below.
                    waiting = self.waiting_saves(binding, but=job['id'])
                    kept = self.kept_saves(job, binding)
                    def row(j):
                        return dict(job_id=j['id'], lab=(self.store.lab(j['lab_id']) or {}).get('name') or j.get('lab_name') or '', name=str(j.get('note') or ''),
                                    kind=j.get('kind') or ('move' if j.get('target') == 'move' else 'save'), target=j.get('target', ''))
                    also = [row(j) for j in sorted(waiting + kept, key=lambda j: str(j.get('created') or ''))]
                    count = len(waiting) + len(kept); elsewhere = sum(1 for j in waiting + kept if j.get('lab_id') != lab_id)
                    kept_names = self.kept_names(kept)
                # A folder move changes no configuration: its review is about what its upload sends along. The helper's
                # comparison reads the moved `latest` folder, which a lab that saved only checkpoints or a baseline has not.
                result = {'files': []} if job.get('target') == 'move' else call({'mode': 'compare', 'operation_id': data.job_id}, binding)
                files = review_files(result.get('files', []) if isinstance(result.get('files'), list) else [], job)
                # The checkout's HEAD, which the upload is bound to: the page sends it back with Upload, and a save that
                # landed in between sends the person back to this review (DESIGN.md 3.4, review X3).
                head = str(result.get('head') or '')
                if not re.fullmatch(r'[0-9a-f]{40,64}', head):
                    try: status = self.invoke({'mode': 'status'}, binding); self.seen_status(job['lab_id'], status); head = str(status.get('head') or '')
                    except ValueError: head = ''
                with self.store.lock:
                    held = {j['id'] for j in self.store.state['git_jobs']} | {j.get('commit') for j in self.store.state['git_jobs'] if j.get('commit')}
                    at_head = self.head_save(head, binding, prefer=next((j for j in self.store.state['git_jobs'] if j['id'] == job['id']), None))
                # Commits the VM would upload that no save of the manager accounts for (a removed lab's, one the job cap
                # let go, one of an older release): named by their subject with the paths they changed (helper change H6).
                for item in result.get('outgoing') or [] if isinstance(result.get('outgoing'), list) else []:
                    if not isinstance(item, dict) or item.get('operation_id') in held or item.get('commit') in held: continue
                    also.append(dict(commit=str(item.get('commit') or '')[:64], name=''.join(c for c in str(item.get('subject') or '') if ord(c) >= 32)[:200],
                                     files=[str(f)[:500] for f in (item.get('files') or [] if isinstance(item.get('files'), list) else []) if isinstance(f, str)][:500]))
                with self.store.lock:
                    stored = job.get('summary') if isinstance(job.get('summary'), dict) else None
                    for entry in also:
                        if 'name' in entry: entry['name'] = scrub(entry['name'], self.store.state)
                return {'files': files, 'summary': stored or (save_summary(files, first=bool(job.get('first_save')) and job.get('target') == 'latest') if files and job.get('target') != 'move' else None),
                        'head': head, 'upload_job': at_head['id'] if at_head and not at_head.get('pushed') else None,
                        'also_sends': also, 'also_sends_count': count, 'also_sends_other_labs': elsewhere, 'also_sends_kept': kept_names}
            if not re.fullmatch(r'[0-9a-f]{40,64}', data.commit): raise HTTPException(400, 'Choose a saved commit.')
            before_manifest, before = version_data(lab_id, data)
            binding = self.reader(lab_id, data.repository)
            # Through a repository the lab does not save to, HEAD comes from `history` (review F17).
            head = call({'mode': 'history'}, binding).get('head') if data.repository else None
            if not head: head = call({'mode': 'status'}, binding)['head']
            path = repo_path(binding, 'latest')
            result = call({'mode': 'read-version', 'commit': head, 'path': path}, binding)
            try: after_manifest, after = decoded_snapshot(result)
            except ValueError as exc: raise HTTPException(409, str(exc))
            # snapshot_diff already pairs by manifest node identity, never by filename, so a suffix
            # rename never appears here as a false removed-plus-added pair.
            return {'files': annotated_compare(snapshot_diff(before_manifest, before, after_manifest, after))}
