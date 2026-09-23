#!/usr/bin/env python3
"""Rehearse the telemetry-retirement upgrade against an isolated copy of a manager data directory.

Never points the application at live data: the given directory is copied into a scratch folder first
(copy the live one yourself with sudo and chown it to your account; the recovery copies of the audit
are `/srv/containerlab-node-manager/data.pre-telemetry-retirement-*`). The tool decrypts the state
before and after `create_app()` (which runs the startup migrations), then proves that every protected
field survived: labs (all keys but the retired `telemetry` one), profiles and their secrets, nodes,
Git bindings, pending Git jobs, restore jobs and history, backups, host trust and fingerprints,
ignored labs, drawings and annotations. A second `create_app()` on the migrated copy must change
nothing but the events file (idempotent migration). Exit 0 only when every check passes.

    clab-backup-ui/.venv/bin/python docs/technical-audit/tools/upgrade_rehearsal.py <data-dir-copy> [--keep]

Prints the labs that keep a `telemetry_retired` ledger (node names and line counts, never the lines).
"""
import copy
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'clab-backup-ui'))
os.chdir(ROOT / 'clab-backup-ui')

from cryptography.fernet import Fernet  # noqa: E402

RETIRED = ('telemetry', 'telemetry_retired')


def decrypt(folder):
    key = (folder / 'state.key').read_bytes()
    return json.loads(Fernet(key).decrypt((folder / 'state.enc').read_bytes()))


def strip(state):
    """The state without the retired keys and without the startup's own job marking."""
    result = copy.deepcopy(state)
    for lab in result.get('labs', []):
        for key in RETIRED:
            lab.pop(key, None)
    # Discovery's constructor marks the VM inspection stale at every start (discovery.py Discovery.__init__).
    if isinstance(result.get('discovery'), dict):
        result['discovery'].update(ok=False, error='Waiting for a fresh VM inspection.')
    for job in result.get('jobs', []):
        if job.get('status') in ('queued', 'running'):
            job['status'] = 'interrupted'; job['message'] = 'Worker restarted during this job; run again.'
    return result


def diff(a, b, path='$'):
    """Paths whose values differ between two JSON documents."""
    if isinstance(a, dict) and isinstance(b, dict):
        out = []
        for key in sorted(set(a) | set(b)):
            if key not in a or key not in b: out.append(f'{path}.{key} ({"missing after" if key not in b else "new after"})')
            else: out.extend(diff(a[key], b[key], f'{path}.{key}'))
        return out
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b): return [f'{path} length {len(a)} -> {len(b)}']
        out = []
        for index, (x, y) in enumerate(zip(a, b)): out.extend(diff(x, y, f'{path}[{index}]'))
        return out
    return [] if a == b else [path]


def main(argv):
    keep = '--keep' in argv
    args = [a for a in argv if not a.startswith('--')]
    if len(args) != 1: sys.exit(__doc__)
    source = Path(args[0]).resolve()
    if not (source / 'state.enc').is_file() or not (source / 'state.key').is_file(): sys.exit('state.enc and state.key are required')
    if source.is_relative_to(Path('/srv/containerlab-node-manager/data')): sys.exit('refusing the live data directory; copy it first')
    scratch = Path(tempfile.mkdtemp(prefix='upgrade-rehearsal-'))
    work = scratch / 'data'
    shutil.copytree(source, work)
    before = decrypt(work)
    labs_before = {lab['id']: lab for lab in before.get('labs', [])}
    ledgers = {}
    for lab in before.get('labs', []):
        applied = (lab.get('telemetry') or {}).get('applied') if isinstance(lab.get('telemetry'), dict) else None
        if isinstance(applied, dict):
            counted = {name: len(entry.get('lines', [])) for name, entry in applied.items() if isinstance(entry, dict) and entry.get('lines')}
            if counted: ledgers[lab['id']] = counted
    from app.main import create_app
    failures = []
    create_app(str(work))
    after = decrypt(work)
    for line in diff(strip(before), strip(after)): failures.append('protected field changed: ' + line)
    for lab in after.get('labs', []):
        if 'telemetry' in lab: failures.append(f"lab {lab['name']}: the retired 'telemetry' key survived")
        record = lab.get('telemetry_retired')
        expected = ledgers.get(lab['id'])
        if expected:
            got = {name: len(entry.get('lines', [])) for name, entry in (record or {}).get('applied', {}).items()}
            if got != expected: failures.append(f"lab {lab['name']}: ledger {expected} became {got}")
            print(f"lab {lab['name']}: keeps a retired-telemetry ledger for " + ', '.join(f'{n} ({c})' for n, c in sorted(expected.items())))
        elif record: failures.append(f"lab {lab['name']}: unexpected telemetry_retired record {json.dumps(record)[:200]}")
    for lab_id, lab in labs_before.items():
        after_lab = next((l for l in after.get('labs', []) if l['id'] == lab_id), None)
        if after_lab is None: failures.append(f'lab {lab_id} disappeared'); continue
        if lab.get('profiles') != after_lab.get('profiles'): failures.append(f"lab {lab['name']}: profiles changed")
        if lab.get('git_binding') != after_lab.get('git_binding'): failures.append(f"lab {lab['name']}: git binding changed")
    create_app(str(work))
    again = decrypt(work)
    for line in diff(after, again): failures.append('second migration changed: ' + line)
    print(f'labs {len(after.get("labs", []))}, jobs {len(after.get("jobs", []))}, git jobs {len(after.get("git_jobs", []))}, restore jobs {len(after.get("restore_jobs", []))}, operations {len(after.get("operations", []))}')
    events = (work / 'events.jsonl').read_text(encoding='utf-8').splitlines()
    retired = [json.loads(l) for l in events if '"telemetry.retired' in l]
    for entry in retired: print('event', entry['action'], entry['level'], entry['message'])
    if not keep: shutil.rmtree(scratch)
    else: print('scratch copy kept at', work)
    if failures:
        print('FAILED'); [print(' -', f) for f in failures]; return 1
    print('PASS: protected fields identical before and after; migration idempotent')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
