# Validation — Containerlab Node Manager 1.6.1 (2026-09-10)

Source: ArchRuger/CLAB-BACKUP-WORKER-v2, baseline `06b8624` (1.6.0 upload),
local branch `codex/map-import-fixes`.

## Results

- Python: 47 tests, 43 passed, 4 skipped; no failures.
- JavaScript: 14 behavior tests passed. Application JS syntax checks passed.
- `git diff --check` passed.
- Source ZIP and upgrade patch verified against the baseline during packaging.

Skipped checks: two Ansible control-node integration tests require Linux; the
symlink test requires unavailable Windows privileges; the EOS SSH driver fixture
is opt-in and requires Ansible collections. Portable traversal tests still run.

New regression fixtures preserve the actual supplied annotation geometry and lab
wiring with connection details and credential text removed. Tests check equivalent
YAML/export imports, 13 nodes and 16 links, exact inventory identity, XRv9k interface
conversion, unchanged Junos names, endpoint offsets, legacy text spacing, opacity,
and consistent top-left node/link coordinates. Existing tests cover authentication,
profiles, inventory, targeted backups, terminal tickets/origins, vendor backup
parameters, downloads, and removal of resource monitoring.

## Browser verification using the supplied lab

Ran the real FastAPI application with the original annotations, generated topology
export, and inventory in disposable local state. Replaced every connection endpoint
and credential with a local Paramiko SSH fixture. No live lab connection was made.

- Expanded map rendered 13 nodes, 16 links, and zero unmatched nodes.
- Compared node/shape positions, notes, group labels, and interface labels against
  the supplied VS Code screenshot. This is a compatible operational rendering,
  not a pixel-identical copy of the full upstream editor.
- Right-click PE1 displayed SSH, Back up configuration, and Node details.
- SSH opened a separate tab for the exact PE1 inventory name and reached Connected
  against the local SSH fixture.
- Back up configuration passed through the real UI/API/queue and selected only
  `clab-BGP_TheoryToPractice-PE1`. Background Ansible execution was stubbed for
  this browser check; this is target-selection evidence, not a live backup result.
- Saved screenshots of the corrected map and its right-click menu with the release.

The supplied problem screenshot reports v1.5.0, which predates the context menu.
Release 1.6.1 adds versioned static asset URLs. Confirm the running container version
and reimport the original annotations plus topology to restore all schema 3 fields.
Reimporting the drawing does not replace inventory, profiles, or history.

## Limits and deployment

No Docker engine or WSL is available here. No image build, actual SuperPuTTY import,
real NOS backup, GitHub push, or deployment was performed. The supplied worker YAML
has no /data mount; follow [fresh-image instructions](../FRESH-IMAGE.md) to preserve
its data and encryption key before replacing the container.

On a Linux development host, from clab-backup-ui:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt httpx
PATH="$PWD/.venv/bin:$PATH" .venv/bin/python -m unittest discover -s tests -v
node --test tests/test_download_ui.js tests/test_topology_ui.js
.venv/bin/ansible-galaxy collection install -r collections.yml
RUN_SSH_FIXTURES=1 PATH="$PWD/.venv/bin:$PATH" .venv/bin/python -m unittest discover -s tests -p test_eos_ssh.py -v
```

The upgrade patch applies to v2 commit `06b8624`. Packaging applies it to a clean
copy of that baseline and compares the resulting source files. The ZIP excludes
virtual environments, raw uploads, preview state, tokens, keys, and configurations.
Only sanitized map regression fixtures are included in source.
