"""Shared helpers for the section-C live acceptance (four real devices, real Save/Apply flows).

Extends qa_lib.py (browser helpers against the running 1.30.31 manager) with:
  - independent per-node A/B/C state detection, built from the ACTUAL content of this deployment's
    devices and of docs/multi-platform-restore/lab/drift/<node>-B.cli, not from readback.py's own
    MARKERS dict (those assume a different, richer restore-square configuration from the
    multi-platform-restore project; this restore-square instance was redeployed fresh and its A is
    the bare containerlab default, confirmed by direct inspection on 2026-09-22 -- see evidence
    20-c-preparation.md "deployment mismatch" note).
  - drift-to-B, undo-B-back-to-A, and add/remove the C marker, all over nodecli.py sessions.
  - a thin git wrapper for the second checkout used to seed Final/Broken/Legacy/solution out of band.

Nothing here imports the application; every state check reads the device over its own fresh SSH
session (nodecli.py), independent of the code under test.
"""
import pathlib
import re
import subprocess
import sys
import time

TOOLS = pathlib.Path(__file__).resolve().parent
MP_TOOLS = TOOLS.parent.parent / 'multi-platform-restore' / 'tools'
DRIFT_DIR = TOOLS.parent.parent / 'multi-platform-restore' / 'lab' / 'drift'
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(MP_TOOLS))
from qa_lib import BASE, LAB_ID, LAB_NAME, Checker, api, click_save_with_retry, complete_pending_via_recent  # noqa: E402
from qa_lib import destination_line, go_to, open_change_folder, open_lab, poll_job, upload_review  # noqa: E402
from nodecli import Session  # noqa: E402

REPO = pathlib.Path.home() / 'labs' / 'CLAB-MNGR-DEV-LLM'
NODES = ['ceos', 'cjunosevolved', 'vjunos-switch', 'xrv9k']
CAPTURE = {'eos': 'show running-config', 'junos': 'show configuration | display set | no-more', 'iosxr': 'show running-config'}

# Statements added by lab/drift/<node>-B.cli that are guaranteed new (the file also touches two
# statements -- a prefix-list delete and a static-route delete -- that do not exist in this
# deployment's bare A, so they are not usable as "A statement removed by B" markers here).
B_MARKERS = {
    'ceos': [r'^\s*description B changed$', r'^ip route 198\.51\.100\.0/24 Null0$', r'^vlan 777$', r'^\s*name B-ONLY$'],
    'cjunosevolved': [r'^set interfaces et-0/0/0 description "B changed"$', r'^set policy-options prefix-list B-ONLY ',
                       r'^set routing-options static route 198\.51\.100\.0/24 discard$'],
    'vjunos-switch': [r'^set interfaces ge-0/0/0 description "B changed"$', r'^set policy-options prefix-list B-ONLY ',
                       r'^set vlans B-ONLY vlan-id 777$'],
    'xrv9k': [r'^\s*description B changed$', r'^prefix-set B-ONLY$', r'^interface Loopback777$'],
}
C_MARKER_TEXT = {'ceos': 'SAVEFIX-C-ceos', 'cjunosevolved': 'SAVEFIX-C-cjunosevolved',
                  'vjunos-switch': 'SAVEFIX-C-vjunos-switch', 'xrv9k': 'SAVEFIX-C-xrv9k'}
C_MARKER_PATTERN = {node: re.escape(text) for node, text in C_MARKER_TEXT.items()}

UNDO_B = {
    'ceos': ['configure', 'interface Ethernet1', 'no description', 'exit',
             'no ip route 198.51.100.0/24 Null0', 'no vlan 777', 'end'],
    'cjunosevolved': ['configure', 'delete interfaces et-0/0/0 description', 'delete policy-options prefix-list B-ONLY',
                       'delete routing-options static route 198.51.100.0/24', 'commit and-quit'],
    'vjunos-switch': ['configure', 'delete interfaces ge-0/0/0 description', 'delete policy-options prefix-list B-ONLY',
                       'delete vlans B-ONLY', 'commit and-quit'],
    'xrv9k': ['configure', 'interface GigabitEthernet0/0/0/0', 'no description', 'root',
              'no prefix-set B-ONLY', 'no interface Loopback777', 'root', 'commit', 'end'],
}
ADD_C_MARKER = {
    'ceos': ['configure', 'interface Ethernet3', 'description SAVEFIX-C-ceos', 'end'],
    'cjunosevolved': ['configure', 'set interfaces et-0/0/1 description "SAVEFIX-C-cjunosevolved"', 'commit and-quit'],
    'vjunos-switch': ['configure', 'set interfaces ge-0/0/1 description "SAVEFIX-C-vjunos-switch"', 'commit and-quit'],
    'xrv9k': ['configure', 'interface GigabitEthernet0/0/0/1', 'description SAVEFIX-C-xrv9k', 'root', 'commit', 'end'],
}
REMOVE_C_MARKER = {
    'ceos': ['configure', 'interface Ethernet3', 'no description', 'end'],
    'cjunosevolved': ['configure', 'delete interfaces et-0/0/1 description', 'commit and-quit'],
    'vjunos-switch': ['configure', 'delete interfaces ge-0/0/1 description', 'commit and-quit'],
    'xrv9k': ['configure', 'interface GigabitEthernet0/0/0/1', 'no description', 'root', 'commit', 'end'],
}


def run_lines(node, lines, tag='c-matrix', timeout=240):
    session = Session(node, timeout)
    try:
        out = []
        for line in lines:
            out.append(session.run(line, timeout))
        return '\n'.join(out)
    finally:
        session.close()


def body(text):
    lines = text.split('\n')
    return '\n'.join(lines[1:-1]) if len(lines) > 2 else text


def read_config(node):
    session = Session(node, 180)
    try:
        return body(session.run(CAPTURE[session.family], 180)), session.family
    finally:
        session.close()


def classify(node, text=None):
    """A / B / C / unknown, from this node's own running configuration."""
    text = text if text is not None else read_config(node)[0]
    b_hits = sum(1 for pat in B_MARKERS[node] if re.search(pat, text, re.M))
    c_hit = bool(re.search(C_MARKER_PATTERN[node], text))
    if c_hit and b_hits == 0:
        return 'C'
    if b_hits == len(B_MARKERS[node]) and not c_hit:
        return 'B'
    if b_hits == 0 and not c_hit:
        return 'A'
    return 'mixed(b_hits=%d/%d,c=%s)' % (b_hits, len(B_MARKERS[node]), c_hit)


def classify_all(nodes=NODES):
    result = {}
    for node in nodes:
        text, family = read_config(node)
        result[node] = classify(node, text)
    return result


def drift_to_b(node):
    drift_file = DRIFT_DIR / f'{node}-B.cli'
    out = run_lines(node, drift_file.read_text().splitlines(), tag='c-drift-b')
    return out


def undo_b_to_a(node):
    return run_lines(node, UNDO_B[node], tag='c-undo-b')


def add_c_marker(node):
    return run_lines(node, ADD_C_MARKER[node], tag='c-add-marker')


def remove_c_marker(node):
    return run_lines(node, REMOVE_C_MARKER[node], tag='c-remove-marker')


# ---- git helpers for the second checkout ----

def git(repo, *args, check=True):
    r = subprocess.run(['git', '-C', str(repo), *args], capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f'git {args} failed: {r.stdout} {r.stderr}')
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def git_rev(repo, ref='HEAD'):
    return git(repo, 'rev-parse', ref)[1]


def git_tree_hash(repo, path):
    out = git(repo, 'ls-tree', 'HEAD', '--', path)[1]
    return out.split()[2] if out else None


def git_show_raw(repo, ref_path):
    """`git show <ref>:<path>` with the exact bytes (no strip): git.git()'s stdout.strip() would
    silently drop a file's trailing newline, corrupting its size/sha256 against the manifest --
    exactly what caused a real, caught 'Snapshot file length or checksum did not match its manifest'
    preflight refusal when this bug first shipped (see 21-c2-final evidence)."""
    r = subprocess.run(['git', '-C', str(repo), 'show', ref_path], capture_output=True, check=True)
    return r.stdout


def replace_snapshot_folder(repo, source_dir, dest_rel, commit_message, push=True):
    """git rm -r dest_rel (if tracked), copy the top-level files of source_dir into dest_rel
    (never recursing into a nested snapshot folder like the legacy .../latest/latest artifact),
    commit and (optionally) push. Returns the new commit sha, or None if nothing changed."""
    import shutil
    dest = pathlib.Path(repo) / dest_rel
    tracked = git(repo, 'ls-files', '--', dest_rel)[1]
    if tracked:
        git(repo, 'rm', '-r', '--quiet', dest_rel)
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)
    src = pathlib.Path(source_dir)
    copied = []
    for item in sorted(src.iterdir()):
        if item.is_file():
            shutil.copy2(item, dest / item.name)
            copied.append(item.name)
    git(repo, 'add', dest_rel)
    status = git(repo, 'status', '--porcelain')[1]
    if not status.strip():
        return None, copied
    git(repo, 'commit', '--quiet', '-m', commit_message)
    if push:
        git(repo, 'push', '--quiet', 'origin', 'main')
    return git_rev(repo), copied


def stamp():
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
