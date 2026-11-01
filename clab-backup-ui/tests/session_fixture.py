"""The sign-on fixture for the Python tests (sign-on DESIGN.md 13.2, 13.3; BUILD.md S1b).

`SignedInClient` is a `TestClient` that completed setup through the real routes (`<data>/setup-code`,
`POST /api/setup`) as the admin `tester` and keeps the session cookie in its `httpx` cookie jar, so every
later request and every `websocket_connect` (which goes through `super().request`) carries it. A second
client on the same app signs in instead of setting up; `role='operator'` creates that user with the admin,
signs in as it and completes the forced password change, so the client holds an unrestricted operator
session. There is no test-only argument to `create_app` and no fixture code in `app/` (ruling 12).

Explicit `Host` headers (HostCheckTests) change nothing here: `httpx` keys its jar by the request URL's
host, which stays `testserver`, so the cookie travels with those requests too.

`assert_not_logged` is the log-hygiene check of 13.3: after a forced flush of the failure buckets it reads
`events.jsonl*`, `audit.jsonl*` and `audit-failures.jsonl*` under the data directory, the open buckets and a
captured container log, and fails when any secret appears in them.

Secrets are never printed: an assertion names what leaked by position, not by value.
"""
import json
from pathlib import Path

from fastapi.testclient import TestClient

PASSWORD = 'correct horse battery staple'
NAME = 'tester'


def setup_code(app):
    """The code `create_app` wrote in setup mode, read as the test process (the owner of the temp dir)."""
    path = Path(app.state.store.root)/'setup-code'
    if not path.is_file(): return None
    fields = dict(line.partition('=')[::2] for line in path.read_text().splitlines() if '=' in line)
    return fields.get('code')


def complete_setup(client, app, name=NAME, password=PASSWORD):
    """Creates the first admin through `POST /api/setup` when the manager is in setup mode; otherwise signs in
    as `name` through `POST /api/session`. Raises AssertionError with the status, never the body's secrets."""
    code = setup_code(app)
    if code is not None and app.state.sessions.setup_mode():
        response = client.post('/api/setup', json={'code': code, 'username': name, 'password': password})
        if response.status_code != 200:
            raise AssertionError(f'setup failed with {response.status_code}: {response.json().get("detail")}')
        return response.json()
    return sign_in(client, name, password)


def sign_in(client, name=NAME, password=PASSWORD):
    response = client.post('/api/session', json={'username': name, 'password': password})
    if response.status_code != 200:
        raise AssertionError(f'sign-in failed with {response.status_code}: {response.json().get("detail")}')
    return response.json()


def sign_out(client):
    return client.request('DELETE', '/api/session', json={})


class SignedInClient(TestClient):
    """A TestClient that completed setup as 'tester' (admin by default) and keeps the cookie."""
    def __init__(self, app, role='admin', name=NAME, password=PASSWORD, **kwargs):
        super().__init__(app, **kwargs)
        self.user = name
        self.password = password
        if role == 'admin':
            complete_setup(self, app, name, password)
            return
        # An operator: the default admin creates it (or it exists already), then this client signs in as it and
        # completes the forced change, so the session is not restricted.
        admin_name, admin_password = (NAME, PASSWORD) if name != NAME else ('tester-admin', PASSWORD)
        complete_setup(self, app, admin_name, admin_password)
        created = self.post('/api/users', json={'name': name, 'role': role, 'password': password})
        if created.status_code not in (200, 409):
            raise AssertionError(f'creating the {role} failed with {created.status_code}: {created.json().get("detail")}')
        sign_out(self)
        answer = sign_in(self, name, password)
        if answer['user']['must_change_password']:
            changed = self.post('/api/session/password', json={'current': password, 'password': password})
            if changed.status_code != 200:
                raise AssertionError(f'the forced change failed with {changed.status_code}: {changed.json().get("detail")}')

    def session_cookie(self):
        return self.cookies.get('clab_session')


def log_text(app, captured=''):
    root = Path(app.state.store.root)
    parts = [captured]
    for name in ('events.jsonl', 'audit.jsonl', 'audit-failures.jsonl'):
        for path in sorted(root.glob(name + '*')):
            parts.append(path.read_text(encoding='utf8', errors='replace'))
    parts.append(json.dumps(app.state.sessions.open_failures()))
    return '\n'.join(parts)


def assert_not_logged(app, *secrets, captured=''):
    """Flushes the failure buckets, then asserts that none of `secrets` appears in the three log files (with
    their rotations), the open buckets or `captured`."""
    app.state.sessions.flush_failures(force=True)
    text = log_text(app, captured)
    for index, secret in enumerate(secrets):
        if secret and secret in text:
            raise AssertionError(f'secret #{index} of {len(secrets)} reached a log')
