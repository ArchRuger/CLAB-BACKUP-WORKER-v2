# clab-backup-ui

The manager application: the FastAPI backend in `app/`, the browser UI in
`app/static/` (plain scripts, no build step), the helpers installed on the VM
(`app/host_*.py`), the embedded topology editor's build project in `lab-builder/` (its
committed output is `app/static/lab-builder/`; the VM needs neither Node nor npm), the
Dockerfile, the Compose file and the test suites.

- Project overview, quick start and diagrams: [../README.md](../README.md)
- All guides: [../docs/README.md](../docs/README.md)
- Architecture and module map: [../docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md)
- What was tested for each release: [VALIDATION.md](VALIDATION.md)
- Node-level behaviour (SSH, backups, map, exports): [NODE-FEATURES.md](NODE-FEATURES.md)

Run the tests from this folder. The `PATH` prefix matters: the runner starts `ansible-playbook` by
bare name and `tests/test_app.py` drives that real pipeline:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt httpx
PATH="$PWD/.venv/bin:$PATH" .venv/bin/python -m unittest discover -s tests -t tests
node --test tests/*.js
```

CI names each test file explicitly in `.github/workflows/release-check.yml`; a new test file
that is not added there does not run in CI.
