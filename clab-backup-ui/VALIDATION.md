# Validation — Containerlab Node Manager 1.6.0 (2026-09-10)

Source baseline: `11a457a` on `main`. This release includes the previously delivered
node actions, SSH terminals, topology imports and SuperPuTTY exports. The user
approved the demonstrated rendering and context menu before release packaging.

## Results

- Python: 44 tests, 40 passed, 4 skipped; no failures.
- JavaScript: 12 behavior tests passed. All application JS syntax checks passed.
- `git diff --check` passed.
- Source ZIP contents and both source patches verified during packaging.

Skipped checks: two Ansible control-node integration tests require Linux; the
symlink test requires unavailable Windows privileges; the EOS SSH driver fixture
is opt-in and requires Ansible collections. Portable traversal tests still run.

New coverage checks imported group colors/opacity, text sizes/weights, label positions,
exact node identity in SVG action targets, escaping, hidden endpoint labels, coincident
node geometry, lab-derived XML filenames, and duplicate prevention when exported
node keys are long names. Existing tests cover authentication, encrypted profiles,
inventory, vendor backup parameters, history/downloads, logs, targeted jobs, SSH
checks, single-use terminal tickets, origin checks, and resource-monitor removal.

## Browser verification

Ran the real FastAPI application with disposable data and a local Paramiko SSH
fixture. Inspected the approved seven-node/seven-link demonstration layout, annotation
colors, shapes, headings, node labels, expanded view and right-click menu. Right-click
SSH opened a separate terminal tab which displayed Connected. The menu includes
backup and details actions; shared targeted-backup behavior is covered by existing
tests. No host resource controls were reintroduced. The user approved this preview.

Actual lab annotation/topology files were not supplied, so exact visual comparison
with the user's VS Code map remains unverified. The importer supports a documented
subset of the upstream annotation format; it does not embed the full VS Code editor.
Old stored drawings require reimport to restore style fields discarded by 1.5.0.

## Release and deployment limitations

No Docker engine or WSL is available here. No image build, actual SuperPuTTY import,
real NOS backup, GitHub push or deployment was performed. Preserve the existing
/data volume and encryption key when upgrading. See NODE-FEATURES.md for build and
live-lab checks. On a Linux development host, run:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt httpx
PATH="$PWD/.venv/bin:$PATH" .venv/bin/python -m unittest discover -s tests -v
node --test tests/test_download_ui.js tests/test_topology_ui.js
.venv/bin/ansible-galaxy collection install -r collections.yml
RUN_SSH_FIXTURES=1 PATH="$PWD/.venv/bin:$PATH" .venv/bin/python -m unittest discover -s tests -p test_eos_ssh.py -v
```

The complete source patch applies to `11a457a`; the upgrade patch applies to the
previously delivered 1.5.0 source ZIP. Packaging applies each patch to its own baseline
and compares every resulting source file. The source ZIP excludes virtual environments,
preview fixtures, application state, tokens, keys, and captured configurations.
