# clab-backup-ui

The manager application: the FastAPI backend in `app/`, the browser UI in
`app/static/`, the helpers installed on the VM (`app/host_*.py`), the Dockerfile,
the Compose file and the test suites.

- Project overview, quick start and diagrams: [../README.md](../README.md)
- All guides: [../docs/README.md](../docs/README.md)
- Architecture and module map: [../docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md)
- What was tested for each release: [VALIDATION.md](VALIDATION.md)
- Node-level behaviour (SSH, backups, map, exports): [NODE-FEATURES.md](NODE-FEATURES.md)

Run the tests from this folder:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt httpx
.venv/bin/python -m unittest discover -s tests -t tests
node --test tests/*.js
```
