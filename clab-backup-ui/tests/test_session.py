"""The gate, the sessions and the sign-on routes (sign-on DESIGN.md 5, 6, 7, 13.1; BUILD.md S1b).

Every test builds the real app on a temporary directory and signs in through the real routes
(tests/session_fixture.py). The clock of the Sessions object is replaced, never `time.monotonic` itself.
"""
import asyncio
import json
import tempfile
import threading
import time
import unittest
from http.cookies import SimpleCookie
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from starlette.routing import Mount, WebSocketRoute
from starlette.websockets import WebSocketDisconnect

from app import accounts, sessions as sessions_module
from app.main import create_app, APP
from app.sessions import EXEMPT, RESTRICTED, COOKIE, IDLE, ABSOLUTE, Sessions, SessionGate, source_key, source_prefix
from session_fixture import SignedInClient, PASSWORD, NAME, complete_setup, sign_in, sign_out, assert_not_logged, setup_code

HTML = {'Accept': 'text/html,application/xhtml+xml,*/*;q=0.8'}
LOGIN_HTML = (APP/'static'/'login.html').is_file()

# DESIGN 7.1, 7.2: every route of the app, classified. A route missing here fails the walk below; a new
# route must be classified when it is added. 'exempt' rows are EXEMPT; 'restricted' is the one route a
# restricted session may use beyond them; everything else needs a session, 'admin' rows an admin's.
ADMIN = {('POST', '/api/manager/reset'), ('PUT', '/api/host'), ('GET', '/api/debug'), ('POST', '/api/debug/probe'),
         ('GET', '/api/users'), ('POST', '/api/users'), ('PATCH', '/api/users/{name}'), ('DELETE', '/api/users/{name}'),
         ('POST', '/api/users/{name}/password'), ('GET', '/api/audit')}
OPERATOR_ROUTES = '''
GET /api/operations/logs | GET /api/operations/interfaces | GET /api/operations/link-state | GET /api/operations/netem
GET /api/operations/images | POST /api/operations/browse | POST /api/operations/view | GET /api/operations/impairments
POST /api/operations/impairments/set | POST /api/operations/impairments/reset | POST /api/operations/impairments/clear
GET /api/operations/apply-plan | GET /api/operations/capabilities | POST /api/operations/read | GET /api/operations/popular
GET /api/operations/known-images | POST /api/operations/image-check | POST /api/operations/parse-yaml
POST /api/operations/preview | POST /api/operations/confirm | GET /api/operations | GET /api/operations/{job_id}
POST /api/operations/{job_id}/cancel | PUT /api/labs/{lab_id}/operations-settings | GET /api/labs/{lab_id}/drawio
PUT /api/labs/{lab_id}/layout | GET /api/labs/{lab_id}/map-document | PUT /api/labs/{lab_id}/map-document
POST /api/labs/{lab_id}/arrange | POST /api/labs/{lab_id}/annotations | POST /api/labs/{lab_id}/drawio | GET /api/catalog
GET /api/git/repositories | GET /api/labs/{lab_id}/git | PUT /api/labs/{lab_id}/git
GET /api/git/repositories/{binding_id}/tree | POST /api/git/repositories/{binding_id}/folders
DELETE /api/git/repositories/{binding_id}/folders | POST /api/labs/{lab_id}/git/destination
POST /api/labs/{lab_id}/git/connect | POST /api/labs/{lab_id}/git/unlink | POST /api/labs/{lab_id}/git/save
POST /api/labs/{lab_id}/git/state | POST /api/labs/{lab_id}/design/generations/{generation_id}/git
GET /api/git/jobs/{job_id} | POST /api/git/jobs/{job_id}/name | POST /api/git/jobs/{job_id}/retry
POST /api/git/jobs/{job_id}/dismiss | POST /api/labs/{lab_id}/git/update | GET /api/labs/{lab_id}/git/history
POST /api/labs/{lab_id}/git/version | POST /api/labs/{lab_id}/git/version/download | POST /api/labs/{lab_id}/git/compare
GET /api/labs/{lab_id}/git/places | POST /api/labs/{lab_id}/git/places/check | POST /api/labs/{lab_id}/git/place
POST /api/git/repositories/{binding_id}/folders/new | GET /api/labs/{lab_id}/restore/sources
GET /api/labs/{lab_id}/restore/states | POST /api/labs/{lab_id}/restore/preflight | POST /api/labs/{lab_id}/restore
GET /api/restore/jobs/{job_id} | GET /api/labs/{lab_id}/health | POST /api/labs/{lab_id}/ssh-check
POST /api/labs/{lab_id}/ssh-check-all | POST /api/labs/{lab_id}/terminal-ticket | GET /api/labs/{lab_id}/topology
POST /api/labs/{lab_id}/topology | POST /api/labs/{lab_id}/superputty | GET /api/capture/health | GET /api/capture/sessions
POST /api/capture/sessions/end-all | GET /api/capture/sessions/{sid} | POST /api/capture/sessions/{sid}/end
GET /api/capture/sessions/{sid}/assets/{path:path} | GET /api/capture/sessions/{sid}/download | GET /api/capture/status
GET /api/capture/targets | POST /api/capture/launch | GET /api/labs/{lab_id}/telemetry-retired
POST /api/labs/{lab_id}/telemetry-retired/remove | POST /api/labs/{lab_id}/telemetry-retired/forget | GET /api/design/engine
GET /api/labs/{lab_id}/design | POST /api/labs/{lab_id}/design/validate | PUT /api/labs/{lab_id}/design
POST /api/labs/{lab_id}/design/clear | POST /api/labs/{lab_id}/design/renumber | POST /api/labs/{lab_id}/design/generate
POST /api/labs/{lab_id}/design/generations/{generation_id}/cancel | GET /api/labs/{lab_id}/design/generations/{generation_id}
GET /api/labs/{lab_id}/design/generations/{generation_id}/artifacts/{node}/{index}
GET /api/labs/{lab_id}/design/generations/{generation_id}/download | GET /api/labs/{lab_id}/design/export
POST /api/labs/{lab_id}/design/import | POST /api/labs/{lab_id}/design/generations/{generation_id}/review
GET /api/labs/{lab_id}/design/review-jobs | GET /api/labs/{lab_id}/design/review-jobs/{job_id} | POST /api/labs/{lab_id}/design/apply
GET /api/labs/{lab_id}/design/apply/jobs | GET /api/design/apply/jobs/{job_id} | GET /api/labs/{lab_id}/design/ownership
GET /api/discovery | POST /api/discovery/refresh | POST /api/discovery/import-preview | POST /api/discovery/import
POST /api/discovery/forget-exclusion | POST /api/discovery/allow-import | POST /api/labs/{lab_id}/sync
PUT /api/labs/{lab_id}/deployment | POST /api/lab-definitions | GET /api/state | DELETE /api/labs/{lab_id} | GET /api/logs
POST /api/inventory | PUT /api/labs/{lab_id}/node | POST /api/labs/{lab_id}/profiles | PUT /api/labs/{lab_id}/schedule
POST /api/labs/{lab_id}/jobs | GET /api/jobs/{job_id}/nodes/{node_index}/download | GET /api/jobs/{job_id}/download
GET /vm-connection-guide | GET /student-guide | GET /
'''
OPERATOR = {tuple(row.strip().split(' ', 1)) for row in OPERATOR_ROUTES.replace('\n', '|').split('|') if row.strip()}
SOCKETS = {'/api/terminal', '/api/capture/sessions/{sid}/websockify'}
MOUNTS = {'/static'}
TABLE = {row: 'exempt' for row in EXEMPT}
TABLE[('POST', '/api/session/password')] = 'restricted'
TABLE.update({row: 'admin' for row in ADMIN})
TABLE.update({row: 'operator' for row in OPERATOR})


def fill(path):
    out = path
    for name in ('{lab_id}', '{job_id}', '{binding_id}', '{generation_id}', '{sid}', '{name}', '{node}', '{index}', '{node_index}', '{path:path}'):
        out = out.replace(name, 'x' if name not in ('{index}', '{node_index}') else '0')
    return out


def close_app(app):
    for name in ('design_apply', 'network_design', 'telemetry_retirement', 'restore', 'git_progress', 'operations', 'discovery',
                 'readiness', 'node_services', 'runner'):
        getattr(app.state, name).close()


def cookie_of(client):
    return client.cookies.get(COOKIE)


def cookie_from(response, name=COOKIE):
    """The attributes of one Set-Cookie header of a response (the first with that name), lower-cased keys."""
    for header in response.headers.get_list('set-cookie'):
        jar = SimpleCookie(); jar.load(header)
        if name in jar: return jar[name]
    return None


def raw(app, method, path, headers=(), scheme='http', query=b''):
    """One HTTP request sent straight to the ASGI app with an unnormalised path: the gate and the router see
    exactly this string (DESIGN 6.3)."""
    sent = []
    async def receive(): return {'type': 'http.request', 'body': b'', 'more_body': False}
    async def send(message): sent.append(message)
    scope = {'type': 'http', 'asgi': {'version': '3.0'}, 'http_version': '1.1', 'method': method, 'scheme': scheme,
             'path': path, 'raw_path': path.encode(), 'query_string': query, 'root_path': '',
             'headers': [(b'host', b'testserver')] + [(k.lower().encode(), v.encode()) for k, v in headers],
             'client': ('203.0.113.7', 4242), 'server': ('testserver', 80)}
    asyncio.run(app(scope, receive, send))
    status = next(m['status'] for m in sent if m['type'] == 'http.response.start')
    head = {k.decode(): v.decode() for k, v in next(m for m in sent if m['type'] == 'http.response.start')['headers']}
    body = b''.join(m.get('body', b'') for m in sent if m['type'] == 'http.response.body')
    return status, head, body


class SessionTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.app = create_app(self.tmp.name); self.addCleanup(close_app, self.app)
        self.store = self.app.state.store; self.sessions = self.app.state.sessions
        self.client = SignedInClient(self.app); self.addCleanup(self.client.close)

    def anonymous(self):
        client = TestClient(self.app); self.addCleanup(client.close); return client

    def operator(self, name='olivia', password='another fine passphrase'):
        client = SignedInClient(self.app, role='operator', name=name, password=password); self.addCleanup(client.close); return client

    def session_ids(self, name=None):
        with self.sessions.lock:
            return [sid for sid, s in self.sessions.sessions.items() if name is None or s['user'] == name]

    def audit(self, name='audit.jsonl'):
        path = Path(self.tmp.name)/name
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


class RouteWalkTests(SessionTestCase):
    def test_every_route_is_classified_and_every_classified_route_exists(self):
        found = set(); sockets = set(); mounts = set()
        for route in self.app.routes:
            if isinstance(route, WebSocketRoute): sockets.add(route.path)
            elif isinstance(route, Mount): mounts.add(route.path)
            else: found.update((m, route.path) for m in route.methods if m != 'HEAD')
        self.assertEqual(found - set(TABLE), set(), 'routes without a classification (DESIGN 7.1)')
        static = {row for row in TABLE if row[1].startswith('/static/')}   # the four exempt assets are files of the mount, not routes
        self.assertEqual(set(TABLE) - found - static, set(), 'classified routes that do not exist')
        self.assertEqual(sockets, SOCKETS); self.assertEqual(mounts, MOUNTS)

    def test_without_a_session_every_route_answers_by_design_6_4_except_the_exempt_rows(self):
        anonymous = self.anonymous()
        for (method, path), role in sorted(TABLE.items()):
            response = anonymous.request(method, fill(path), json={} if method != 'GET' else None)
            if role == 'exempt':
                # The gate passed it: no redirect, and no gate 401 (GET /api/session answers its own 401 with a clearing cookie).
                self.assertNotEqual(response.status_code, 302, (method, path))
                if (method, path) != ('GET', '/api/session'): self.assertNotEqual(response.status_code, 401, (method, path))
                else: self.assertIsNotNone(cookie_from(response))
                continue
            self.assertEqual(response.status_code, 401, (method, path, response.text))
            self.assertEqual(response.json(), {'detail': {'code': 'signed_out', 'message': 'Your session ended. Sign in again.'}}, (method, path))
            self.assertNotIn('www-authenticate', response.headers)
            self.assertEqual(response.headers['cache-control'], 'no-store')
            self.assertEqual(response.headers['x-content-type-options'], 'nosniff')
            if method == 'GET':
                page = anonymous.get(fill(path), headers=HTML, follow_redirects=False)
                self.assertEqual(page.status_code, 302, (method, path))
                self.assertEqual(page.headers['location'], '/login?next=' + fill(path).replace('/', '%2F'), (method, path))
        for path in SOCKETS:
            with self.assertRaises(WebSocketDisconnect) as ctx:
                with anonymous.websocket_connect(fill(path), headers={'Origin': 'http://testserver'}): pass
            self.assertEqual((ctx.exception.code, ctx.exception.reason), (1008, 'signed_out'), path)
        # A static file behind the gate, a page and a query string in `next`.
        self.assertEqual(anonymous.get('/static/app.js').status_code, 401)
        page = anonymous.get('/student-guide?x=1&y=2', headers=HTML, follow_redirects=False)
        self.assertEqual(page.headers['location'], '/login?next=%2Fstudent-guide%3Fx%3D1%26y%3D2')
        # Page against API is decided by Accept, not by the path (6.4).
        self.assertEqual(anonymous.get('/api/state', headers=HTML, follow_redirects=False).status_code, 302)
        # Nothing of this is logged anywhere (REVIEW R8).
        for line in Path(self.tmp.name).glob('*.jsonl'):
            self.assertNotIn('signed_out', line.read_text())
        # The one 401 the diagnostics list may hold is the exempt route's own (GET /api/session), never the gate's.
        self.assertEqual([r for r in self.app.state.diagnostics.requests if r['status'] == 401 and r['route'] != '/api/session'], [])

    def test_admin_routes_refuse_an_operator_with_the_sentence_and_operator_routes_do_not(self):
        operator = self.operator()
        for method, path in sorted(ADMIN):
            response = operator.request(method, fill(path), json={} if method != 'GET' else None)
            self.assertEqual(response.status_code, 403, (method, path, response.text))
            self.assertEqual(response.json()['detail'], {'code': 'admin_required', 'message': 'Administrators only.'})
        for method, path in sorted(OPERATOR):
            response = operator.request(method, fill(path), json={} if method != 'GET' else None)
            if response.status_code == 403:
                self.assertNotEqual(response.json().get('detail', {}).get('code') if response.headers.get('content-type', '').startswith('application/json') else '', 'admin_required', (method, path))
        # Summed into one `forbidden` entry per route and minute, in audit.jsonl, with the route template (10.1).
        self.sessions.flush_failures(force=True)
        forbidden = [e for e in self.audit() if e['event'] == 'forbidden']
        self.assertEqual({e['target'] for e in forbidden}, {path for _, path in ADMIN})
        self.assertTrue(all(e['actor'] == 'olivia' and e['outcome'] == 'failed' and e['detail'].startswith('admin_required count=') for e in forbidden))
        self.assertEqual(sum(int(e['detail'].split('count=')[1]) for e in forbidden), len(ADMIN))
        self.assertEqual([e for e in self.audit('audit-failures.jsonl') if e['event'] == 'forbidden'], [])

    def test_a_signed_in_admin_passes_the_gate_and_the_guard_keeps_its_own_refusals(self):
        self.assertEqual(self.client.get('/api/state').status_code, 200)
        self.assertEqual(self.client.get('/', headers=HTML).status_code, 200)
        self.assertEqual(self.client.get('/api/state', headers={'Origin': 'https://other.example'}).status_code, 403)
        self.assertEqual(self.client.post('/api/manager/reset').status_code, 413)
        self.assertEqual(self.client.get('/static/style.css').status_code, 200)
        self.assertEqual(self.client.get('/api/health').json(), {'ready': True})

    def test_the_health_route_answers_ready_and_nothing_else(self):
        for client in (self.anonymous(), self.client):
            response = client.get('/api/health', headers=HTML)
            self.assertEqual((response.status_code, response.json()), (200, {'ready': True}))
            self.assertEqual(response.headers['cache-control'], 'no-store')
            self.assertNotIn('set-cookie', response.headers)
            self.assertNotIn('server', response.headers)


class CookieTests(SessionTestCase):
    def test_cookie_attributes_under_http(self):
        anonymous = self.anonymous()
        response = anonymous.post('/api/session', json={'username': NAME, 'password': PASSWORD})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['user'], {'name': NAME, 'role': 'admin', 'must_change_password': False})
        self.assertIn('expires', response.json())
        morsel = cookie_from(response)
        self.assertTrue(morsel['httponly']); self.assertEqual(morsel['samesite'], 'Strict'); self.assertEqual(morsel['path'], '/')
        self.assertEqual(morsel['max-age'], str(ABSOLUTE)); self.assertFalse(morsel['secure']); self.assertEqual(morsel['domain'], '')
        self.assertEqual(len(morsel.value) >= 43, True)
        assert_not_logged(self.app, PASSWORD, morsel.value)

    def test_cookie_attributes_under_https_and_hsts(self):
        secure = TestClient(self.app, base_url='https://testserver'); self.addCleanup(secure.close)
        response = secure.post('/api/session', json={'username': NAME, 'password': PASSWORD})
        self.assertEqual(response.status_code, 200, response.text)
        morsel = cookie_from(response)
        self.assertTrue(morsel['secure']); self.assertTrue(morsel['httponly']); self.assertEqual(morsel['samesite'], 'Strict')
        self.assertEqual(response.headers['strict-transport-security'], 'max-age=15552000')
        self.assertEqual(secure.get('/api/state').status_code, 200)
        self.assertEqual(secure.get('/api/state').headers['strict-transport-security'], 'max-age=15552000')
        self.assertNotIn('strict-transport-security', self.client.get('/api/state').headers)
        # The gate's own refusal carries it too (6.1).
        plain = TestClient(self.app, base_url='https://testserver'); self.addCleanup(plain.close)
        refused = plain.get('/api/state')
        self.assertEqual(refused.status_code, 401); self.assertEqual(refused.headers['strict-transport-security'], 'max-age=15552000')
        self.assertEqual(refused.headers['content-security-policy'], "default-src 'none'; frame-ancestors 'none'")

    def test_sign_out_clears_both_cookies_always_and_never_answers_401(self):
        response = sign_out(self.client)
        self.assertEqual((response.status_code, response.json()), (200, {'signed_out': True}))
        session = cookie_from(response); capture = cookie_from(response, 'clab_capture_owner')
        self.assertEqual((session['max-age'], session['path']), ('0', '/'))
        self.assertEqual((capture['max-age'], capture['path'], bool(capture['httponly']), capture['samesite']), ('0', '/api/capture', True, 'Strict'))
        self.assertEqual(self.client.get('/api/state').status_code, 401)
        again = sign_out(self.client)
        self.assertEqual((again.status_code, again.json()), (200, {'signed_out': True}))
        self.assertIsNotNone(cookie_from(again, 'clab_capture_owner'))
        self.assertEqual([e['event'] for e in self.audit() if e['event'] in ('signout',)], ['signout'])

    def test_get_session_without_a_session_clears_the_cookie(self):
        anonymous = self.anonymous()
        response = anonymous.get('/api/session')
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()['detail']['code'], 'signed_out')
        self.assertEqual(cookie_from(response)['max-age'], '0')
        mine = self.client.get('/api/session')
        self.assertEqual(mine.json()['user'], {'name': NAME, 'role': 'admin', 'must_change_password': False})
        self.assertNotIn('set-cookie', mine.headers)

    def test_set_cookie_appears_only_on_the_five_responses_of_5_4(self):
        for method, path, body in (('GET', '/api/state', None), ('POST', '/api/labs/x/jobs', {}), ('GET', '/', None), ('GET', '/api/session', None)):
            response = self.client.request(method, path, json=body, headers=HTML if path == '/' else None)
            self.assertNotIn('set-cookie', response.headers, (method, path))
        changed = self.client.post('/api/session/password', json={'current': PASSWORD, 'password': 'a brand new passphrase'})
        self.assertEqual(changed.status_code, 200, changed.text)
        self.assertIsNotNone(cookie_from(changed))

    def test_session_fixation_a_cookie_sent_with_the_sign_in_is_ignored(self):
        anonymous = self.anonymous()
        response = anonymous.post('/api/session', json={'username': NAME, 'password': PASSWORD}, headers={'Cookie': COOKIE + '=attacker-chosen-id'})
        self.assertEqual(response.status_code, 200)
        minted = cookie_from(response).value
        self.assertNotEqual(minted, 'attacker-chosen-id')
        self.assertNotIn('attacker-chosen-id', self.session_ids())
        # A sign-in over a live session rotates: the old id is gone.
        before = self.client.session_cookie()
        again = self.client.post('/api/session', json={'username': NAME, 'password': PASSWORD})
        self.assertNotEqual(cookie_from(again).value, before)
        self.assertNotIn(before, self.session_ids())


class ExpiryAndRenewalTests(SessionTestCase):
    def setUp(self):
        super().setUp()
        self.now = [1000.0]
        self.sessions.clock = lambda: self.now[0]
        # The fixture's session was minted on the real clock: mint one on the fake clock instead.
        sign_out(self.client); sign_in(self.client)
        self.sid = self.client.session_cookie()

    def last_seen(self):
        with self.sessions.lock: return self.sessions.sessions[self.sid]['last_seen']

    def test_no_get_api_request_renews_and_acts_of_the_person_do(self):
        self.assertEqual(self.last_seen(), 1000.0)
        self.now[0] = 1100.0
        for path in ('/api/state', '/api/session', '/api/labs/x/git/history', '/api/discovery'):
            self.client.get(path)
            self.assertEqual(self.last_seen(), 1000.0, path)
        self.client.get('/static/app.js'); self.assertEqual(self.last_seen(), 1000.0)
        self.client.post('/api/labs/x/jobs', json={})
        self.assertEqual(self.last_seen(), 1100.0)
        self.now[0] = 1200.0
        self.client.get('/', headers=HTML)
        self.assertEqual(self.last_seen(), 1200.0)
        self.now[0] = 1300.0
        self.client.head('/', headers=HTML)
        self.assertEqual(self.last_seen(), 1300.0)

    def test_idle_expiry_is_audited_once_and_later_polls_are_logged_nowhere(self):
        self.now[0] = 1000.0 + IDLE + 1
        self.assertEqual(self.client.get('/api/state').status_code, 401)
        self.assertNotIn(self.sid, self.session_ids())
        for _ in range(10): self.assertEqual(self.client.get('/api/state').status_code, 401)
        self.sessions.sweep()
        expired = [e for e in self.audit() if e['event'] == 'session.expired']
        self.assertEqual(len(expired), 1)
        self.assertEqual((expired[0]['actor'], expired[0]['detail'], expired[0]['outcome']), (NAME, 'idle', 'ok'))
        self.assertEqual([e for e in self.store.events() if 'signed_out' in json.dumps(e)], [])
        self.assertEqual(self.audit('audit-failures.jsonl'), [])
        assert_not_logged(self.app, self.sid, PASSWORD)

    def test_absolute_expiry_despite_activity(self):
        for step in range(1, 28):   # an act every six hours keeps the idle rule quiet; the absolute rule still ends it
            self.now[0] = 1000.0 + step * 21600
            self.assertEqual(self.client.post('/api/labs/x/jobs', json={}).status_code, 400, step)
        self.now[0] = 1000.0 + ABSOLUTE + 1
        self.assertEqual(self.client.get('/api/state').status_code, 401)
        self.sessions.sweep()
        self.assertEqual([e['detail'] for e in self.audit() if e['event'] == 'session.expired'], ['absolute'])

    def test_the_sweep_deletes_expired_sessions_it_never_saw_again(self):
        other = self.anonymous(); sign_in(other); other_id = cookie_of(other)
        self.now[0] = 1000.0 + IDLE + 5
        self.sessions.sweep()
        self.assertNotIn(other_id, self.session_ids()); self.assertNotIn(self.sid, self.session_ids())
        self.assertEqual(len([e for e in self.audit() if e['event'] == 'session.expired']), 2)
        self.assertEqual(self.sessions.count(NAME), 0)


class RestrictedSessionTests(SessionTestCase):
    def setUp(self):
        super().setUp()
        self.assertEqual(self.client.post('/api/users', json={'name': 'newbie', 'role': 'operator', 'password': 'set by the admin 1'}).status_code, 200)
        self.newbie = self.anonymous()
        answer = self.newbie.post('/api/session', json={'username': 'newbie', 'password': 'set by the admin 1'})
        self.assertEqual(answer.status_code, 200, answer.text)
        self.assertEqual(answer.json()['user'], {'name': 'newbie', 'role': 'operator', 'must_change_password': True})

    def test_the_restricted_session_reaches_the_change_and_nothing_else(self):
        self.assertEqual(self.newbie.get('/api/session').json()['user']['must_change_password'], True)
        refused = self.newbie.get('/api/state')
        self.assertEqual((refused.status_code, refused.json()['detail']), (403, {'code': 'password_change_required', 'message': 'Choose your own password before you continue.'}))
        self.assertEqual(self.newbie.get('/static/app.js').status_code, 403)
        page = self.newbie.get('/', headers=HTML, follow_redirects=False)
        self.assertEqual((page.status_code, page.headers['location']), (302, '/login?change=1&next=%2F'))
        page = self.newbie.get('/student-guide?a=1', headers=HTML, follow_redirects=False)
        self.assertEqual(page.headers['location'], '/login?change=1&next=%2Fstudent-guide%3Fa%3D1')
        with self.assertRaises(WebSocketDisconnect) as ctx:
            with self.newbie.websocket_connect('/api/terminal', headers={'Origin': 'http://testserver'}): pass
        self.assertEqual((ctx.exception.code, ctx.exception.reason), (1008, 'password_change_required'))
        # No redirect loop: every redirect from a page lands on /login?change=1, which the route serves to a restricted session.
        hops = []; location = '/'
        for _ in range(5):
            response = self.newbie.get(location, headers=HTML, follow_redirects=False)
            hops.append((location, response.status_code))
            if response.status_code != 302: break
            location = response.headers['location']
        self.assertEqual(hops[0], ('/', 302)); self.assertTrue(location.startswith('/login?change=1'))
        final = self.newbie.get(location, headers=HTML, follow_redirects=False)
        self.assertNotEqual(final.status_code, 302, 'GET /login must not redirect a restricted session (REVIEW R1)')
        if LOGIN_HTML: self.assertEqual(final.status_code, 200)
        else: self.assertEqual(final.status_code, 404, 'login.html is S7 (absent here): the route answers 404, never a redirect')
        # The allowlist resists path tricks (6.3: no normalisation, no case folding, no trailing slash).
        for method, path in (('GET', '/API/state'), ('GET', '/api/state/'), ('POST', '/api/session/password/'), ('GET', '/api/session/password/../../state')):
            status, _, _ = raw(self.app, method, path, [('cookie', COOKIE + '=' + cookie_of(self.newbie)), ('content-length', '2'), ('content-type', 'application/json')])
            self.assertEqual(status, 403, (method, path))
        self.assertEqual(self.newbie.get('/api/health').json(), {'ready': True})
        # The way out: the own change, then `next` answers 200 and the old sessions of the user are gone.
        weak = self.newbie.post('/api/session/password', json={'current': 'set by the admin 1', 'password': 'short'})
        self.assertEqual(weak.status_code, 422); self.assertEqual(weak.json()['detail']['code'], 'weak_password'); self.assertIn('message', weak.json()['detail'])
        wrong = self.newbie.post('/api/session/password', json={'current': 'not the password 1', 'password': 'my own choice of words'})
        self.assertEqual((wrong.status_code, wrong.json()['detail']), (401, {'code': 'invalid_credentials', 'message': 'The current password is not right.'}))
        changed = self.newbie.post('/api/session/password', json={'current': 'set by the admin 1', 'password': 'my own choice of words'})
        self.assertEqual((changed.status_code, changed.json()), (200, {'changed': True}), changed.text)
        self.assertEqual(self.newbie.get('/', headers=HTML).status_code, 200)
        self.assertEqual(self.newbie.get('/api/state').status_code, 200)
        self.assertEqual(self.newbie.get('/api/session').json()['user']['must_change_password'], False)
        failed = [e for e in self.audit() if e['event'] == 'password.changed']
        self.assertEqual([(e['outcome'], e['detail'], e['actor']) for e in failed], [('failed', 'invalid_credentials', 'newbie'), ('ok', '', 'newbie')])
        assert_not_logged(self.app, 'set by the admin 1', 'my own choice of words', 'not the password 1', cookie_of(self.newbie))

    def test_get_login_serves_the_page_to_a_restricted_session_and_redirects_an_unrestricted_one(self):
        mine = self.client.get('/login', headers=HTML, follow_redirects=False)
        self.assertEqual((mine.status_code, mine.headers['location']), (302, '/'))
        theirs = self.newbie.get('/login', headers=HTML, follow_redirects=False)
        self.assertEqual(theirs.status_code, 200 if LOGIN_HTML else 404)
        anonymous = self.anonymous().get('/login', headers=HTML, follow_redirects=False)
        self.assertEqual(anonymous.status_code, 200 if LOGIN_HTML else 404)
        self.assertEqual(self.anonymous().get('/setup', headers=HTML).status_code, 404, 'after setup, /setup is a plain 404 (9.4)')

    def test_sign_out_is_the_other_way_out(self):
        self.assertEqual(sign_out(self.newbie).status_code, 200)
        self.assertEqual(self.newbie.get('/api/session').status_code, 401)
        self.assertEqual(self.sessions.count('newbie'), 0)


class SignOutEverywhereTests(SessionTestCase):
    def setUp(self):
        super().setUp()
        self.operator('olivia', 'another fine passphrase')
        self.browsers = [self.anonymous() for _ in range(3)]
        for browser in self.browsers: sign_in(browser, 'olivia', 'another fine passphrase')
        self.assertEqual(self.sessions.count('olivia'), 4)

    def ended(self):
        return [e['detail'] for e in self.audit() if e['event'] == 'session.ended' and e['actor'] == 'olivia']

    def test_disable_ends_every_session(self):
        self.assertEqual(self.client.patch('/api/users/olivia', json={'disabled': True}).status_code, 200)
        self.assertEqual(self.sessions.count('olivia'), 0)
        for browser in self.browsers: self.assertEqual(browser.get('/api/state').status_code, 401)
        self.assertEqual(self.ended(), ['user_disabled'] * 4)
        self.assertEqual(self.client.patch('/api/users/olivia', json={'disabled': False}).status_code, 200)
        refused = self.browsers[0].post('/api/session', json={'username': 'olivia', 'password': 'another fine passphrase'})
        self.assertEqual(refused.status_code, 200, 'enabled again: signs in')

    def test_delete_ends_every_session(self):
        self.assertEqual(self.client.request('DELETE', '/api/users/olivia', json={}).status_code, 200)
        self.assertEqual(self.sessions.count('olivia'), 0)
        for browser in self.browsers: self.assertEqual(browser.get('/api/state').status_code, 401)
        self.assertEqual(self.ended(), ['user_deleted'] * 4)

    def test_admin_reset_ends_every_session_and_restricts_the_next(self):
        self.assertEqual(self.client.post('/api/users/olivia/password', json={'password': 'reset by the admin 2'}).status_code, 200)
        self.assertEqual(self.sessions.count('olivia'), 0)
        for browser in self.browsers: self.assertEqual(browser.get('/api/state').status_code, 401)
        self.assertEqual(self.ended(), ['password_reset'] * 4)
        answer = self.browsers[0].post('/api/session', json={'username': 'olivia', 'password': 'reset by the admin 2'})
        self.assertEqual(answer.json()['user']['must_change_password'], True)

    def test_own_change_ends_the_other_sessions_and_keeps_the_current_one_rotated(self):
        current = self.browsers[0]; old_id = cookie_of(current)
        changed = current.post('/api/session/password', json={'current': 'another fine passphrase', 'password': 'she chose this one herself'})
        self.assertEqual(changed.status_code, 200, changed.text)
        new_id = cookie_from(changed).value
        self.assertNotEqual(new_id, old_id)
        self.assertEqual(current.get('/', headers=HTML).status_code, 200)
        self.assertEqual(current.get('/api/state').status_code, 200)
        self.assertEqual(self.sessions.count('olivia'), 1)
        for browser in self.browsers[1:]: self.assertEqual(browser.get('/api/state').status_code, 401)
        status, _, _ = raw(self.app, 'GET', '/api/state', [('cookie', COOKIE + '=' + old_id)])
        self.assertEqual(status, 401, 'the old cookie finds no session')
        self.assertEqual(self.ended(), ['password_changed'] * 3)
        assert_not_logged(self.app, old_id, new_id, 'she chose this one herself', 'another fine passphrase')

    def test_the_rotated_session_resolves_at_every_step_of_the_own_change(self):
        # R1/R4: the current session resolves before rotate (old id, old stamp) and, under its new id, right after
        # set_user and after end_user. Between rotate and set_user the new id is known to nobody yet (the response
        # that carries it is sent after the whole locked block), so no request can observe that step.
        current = self.browsers[0]; old_id = cookie_of(current)
        seen = []; rotated = []
        real_set_user = self.sessions.set_user; real_end_user = self.sessions.end_user; real_rotate = self.sessions.rotate
        def rotate(sid, stamp):
            seen.append(('before rotate', self.sessions.resolve(sid) is not None, sid == old_id))
            rotated.append(real_rotate(sid, stamp)); return rotated[-1]
        def set_user(record):
            real_set_user(record); seen.append(('after set_user', self.sessions.resolve(rotated[-1]) is not None))
        def end_user(name, reason, keep=None):
            count = real_end_user(name, reason, keep=keep); seen.append(('after end_user', self.sessions.resolve(rotated[-1]) is not None, keep == rotated[-1])); return count
        with patch.object(self.sessions, 'rotate', rotate), patch.object(self.sessions, 'set_user', set_user), patch.object(self.sessions, 'end_user', end_user):
            changed = current.post('/api/session/password', json={'current': 'another fine passphrase', 'password': 'she chose this one herself'})
        self.assertEqual(changed.status_code, 200, changed.text)
        self.assertEqual(seen, [('before rotate', True, True), ('after set_user', True), ('after end_user', True, True)])
        self.assertEqual(cookie_from(changed).value, rotated[-1])
        self.assertIsNone(self.sessions.resolve(old_id))
        self.assertEqual(current.get('/api/state').status_code, 200)


class RecordingLock:
    """A lock proxy that records, per thread, the locks held when another is acquired."""
    held = threading.local()
    violations = []
    def __init__(self, name, inner):
        self.name = name; self.inner = inner
    def _stack(self):
        if not hasattr(self.held, 'stack'): self.held.stack = []
        return self.held.stack
    def acquire(self, *args, **kwargs):
        if self.name == 'store' and 'sessions' in self._stack(): self.violations.append(('store under sessions', threading.current_thread().name))
        if getattr(self.held, 'in_gate', False) and self.name == 'store': self.violations.append(('store in the gate', threading.current_thread().name))
        got = self.inner.acquire(*args, **kwargs)
        if got: self._stack().append(self.name)
        return got
    def release(self):
        self._stack().remove(self.name); self.inner.release()
    def __enter__(self): self.acquire(); return self
    def __exit__(self, *exc): self.release()
    def _is_owned(self): return self.inner._is_owned()


class LockOrderTests(SessionTestCase):
    def test_store_lock_is_never_taken_under_the_sessions_lock_and_never_by_the_gate(self):
        RecordingLock.violations.clear()
        self.store.lock = RecordingLock('store', self.store.lock)
        self.sessions.lock = RecordingLock('sessions', self.sessions.lock)
        real_decide = SessionGate.decide
        def decide(gate, scope):
            RecordingLock.held.in_gate = True
            try: return real_decide(gate, scope)
            finally: RecordingLock.held.in_gate = False
        operator = self.operator()
        with patch.object(SessionGate, 'decide', decide):
            for client in (self.client, operator, self.anonymous()):
                for (method, path), role in sorted(TABLE.items()):
                    client.request(method, fill(path), json={} if method != 'GET' else None)
                    if method == 'GET': client.get(fill(path), headers=HTML, follow_redirects=False)
                for path in SOCKETS:
                    try:
                        with client.websocket_connect(fill(path), headers={'Origin': 'http://testserver'}) as ws: ws.send_text('{}')
                    except WebSocketDisconnect: pass
            anonymous = self.anonymous()
            anonymous.post('/api/session', json={'username': NAME, 'password': 'wrong passphrase here'})
            anonymous.post('/api/session', json={'username': NAME, 'password': PASSWORD})
            anonymous.post('/api/session/password', json={'current': PASSWORD, 'password': 'rotated once more here'})
            sign_out(anonymous)
            self.client.post('/api/users', json={'name': 'zed', 'role': 'operator', 'password': 'the eighth symphony plays'})
            self.client.patch('/api/users/zed', json={'disabled': True}); self.client.post('/api/users/zed/password', json={'password': 'reset again for zed'})
            self.client.request('DELETE', '/api/users/zed', json={})
            self.sessions.sweep(); self.sessions.flush_failures(force=True)
        self.assertEqual(RecordingLock.violations, [])


class ConstantWorkTests(SessionTestCase):
    def test_a_wrong_user_a_wrong_password_and_a_disabled_user_each_cost_one_verify_and_a_throttled_attempt_none(self):
        self.client.post('/api/users', json={'name': 'dora', 'role': 'operator', 'password': 'the ninth symphony plays'})
        self.client.patch('/api/users/dora', json={'disabled': True})
        anonymous = self.anonymous(); calls = []
        real = accounts.verify_password
        def counting(hash_string, password):
            calls.append(hash_string is None or hash_string == accounts.DUMMY_HASH); return real(hash_string, password)
        with patch('app.accounts.verify_password', counting):
            for name, password, dummy in (('nobody', 'whatever it is', True), (NAME, 'wrong passphrase', False), ('dora', 'the ninth symphony plays', True), ('Not A Name!', 'x', True)):
                calls.clear()
                response = anonymous.post('/api/session', json={'username': name, 'password': password})
                self.assertEqual((response.status_code, response.json()['detail']), (401, {'code': 'invalid_credentials', 'message': 'Wrong username or password.'}), name)
                self.assertEqual(calls, [dummy], name)
            calls.clear()
            with patch.object(self.sessions, 'check', return_value=30):
                response = anonymous.post('/api/session', json={'username': NAME, 'password': PASSWORD})
            self.assertEqual(response.status_code, 429); self.assertEqual(response.headers['retry-after'], '30')
            self.assertEqual(response.json()['detail'], {'code': 'throttled', 'retry_after': 30, 'message': 'Too many sign-in attempts. Try again in 30 s.'})
            self.assertEqual(calls, [])
        self.sessions.flush_failures(force=True)
        failures = self.audit('audit-failures.jsonl')
        self.assertEqual(sorted((e['event'], e['actor'], e['detail'].split(' count=')[0]) for e in failures),
                         sorted([('signin.failed', '-', 'invalid_credentials'), ('signin.failed', NAME, 'invalid_credentials'), ('signin.failed', 'dora', 'disabled'), ('signin.failed', '-', 'invalid_name')]))
        assert_not_logged(self.app, 'whatever it is', 'wrong passphrase', 'the ninth symphony plays', 'Not A Name!')
        self.assertEqual([e for e in self.store.events() if e['action'] == 'api.request' and '/api/session' in e['message']], [], 'no api.request for the sign-in route (R8)')

    def test_state_holds_neither_users_nor_hashes_and_names_the_session_user(self):
        text = self.client.get('/api/state').text
        for secret in ('"users"', 'known_sources', 'scrypt$', PASSWORD): self.assertNotIn(secret, text)
        self.assertEqual(json.loads(text)['user'], {'name': NAME, 'role': 'admin', 'must_change_password': False})

    def test_a_bad_record_costs_one_verify_and_is_audited_bad_record(self):
        with self.store.lock:
            self.store.state['users'][NAME]['password'] = 'not a hash string'; self.store.save()
        anonymous = self.anonymous(); calls = []
        with patch('app.accounts.verify_password', lambda h, p: calls.append(h) or False):
            self.assertEqual(anonymous.post('/api/session', json={'username': NAME, 'password': PASSWORD}).status_code, 401)
        self.assertEqual(calls, ['not a hash string'])
        self.sessions.flush_failures(force=True)
        self.assertEqual([(e['actor'], e['detail']) for e in self.audit('audit-failures.jsonl')], [(NAME, 'bad_record count=1')])
        self.assertIsNone(self.client.get('/api/users').json()['users'][0]['password_changed'])


class NoNormalisationTests(SessionTestCase):
    def test_a_dotted_spelling_of_an_exempt_path_still_needs_a_session(self):
        status, head, body = raw(self.app, 'GET', '/api/capture/sessions/x/assets/../../../../session')
        self.assertEqual(status, 401); self.assertEqual(json.loads(body)['detail']['code'], 'signed_out')
        self.assertEqual(head['cache-control'], 'no-store')
        for path in ('/API/session', '/api/session/', '//api/session', '/api//session'):
            status, _, _ = raw(self.app, 'GET', path)
            self.assertEqual(status, 401, path)
        status, _, _ = raw(self.app, 'GET', '/api/session')
        self.assertEqual(status, 401, 'exempt, reaches the route, which answers 401 cleanly')
        status, head, _ = raw(self.app, 'GET', '/api/health')
        self.assertEqual(status, 200)


class SessionsObjectTests(unittest.TestCase):
    """The object on its own, with a fake clock and a Store on a temporary directory."""
    def setUp(self):
        from app.store import Store
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.store = Store(self.tmp.name)
        self.sessions = Sessions(self.store)
        self.now = [100.0]; self.sessions.clock = lambda: self.now[0]
        self.record = accounts.new_record('alice', 'operator', accounts.DUMMY_HASH, created_by='root', must_change_password=False)
        self.sessions.load_users({'alice': self.record})

    def audit(self):
        path = Path(self.tmp.name)/'audit.jsonl'
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def test_record_shape_and_resolve(self):
        sid, session = self.sessions.create(self.record, '203.0.113.7')
        self.assertEqual(set(session), {'user', 'role', 'provider', 'created', 'created_at', 'last_seen', 'password_changed', 'source'})
        self.assertEqual((session['user'], session['role'], session['provider'], session['source'], session['password_changed']), ('alice', 'operator', 'local', '203.0.113.7', self.record['password_changed']))
        resolved = self.sessions.resolve(sid)
        self.assertEqual((resolved['id'], resolved['user'], resolved['role'], resolved['must_change_password']), (sid, 'alice', 'operator', False))
        self.assertIsNone(self.sessions.resolve('nope')); self.assertIsNone(self.sessions.resolve(None)); self.assertIsNone(self.sessions.resolve(''))
        self.assertEqual(self.sessions.count('alice'), 1)
        self.assertEqual(self.sessions.user('alice'), (self.record['role'], False, self.record['password_changed'], False))
        self.assertFalse(self.sessions.setup_mode())

    def test_the_index_decides_role_state_and_stamp_on_every_request(self):
        sid, _ = self.sessions.create(self.record, '203.0.113.7')
        self.sessions.set_user({**self.record, 'role': 'admin'})
        self.assertEqual(self.sessions.resolve(sid)['role'], 'admin')
        self.sessions.set_user({**self.record, 'role': 'admin', 'must_change_password': True})
        self.assertEqual(self.sessions.resolve(sid)['must_change_password'], True)
        self.sessions.set_user({**self.record, 'disabled': True})
        self.assertIsNone(self.sessions.resolve(sid)); self.assertEqual(self.sessions.count('alice'), 0)
        sid, _ = self.sessions.create(self.record, '203.0.113.7'); self.sessions.set_user(self.record)
        self.sessions.set_user({**self.record, 'password_changed': 'later'})
        self.assertIsNone(self.sessions.resolve(sid))
        sid, _ = self.sessions.create(self.record, '203.0.113.7'); self.sessions.set_user(self.record)
        self.sessions.drop_user('alice')
        self.assertIsNone(self.sessions.resolve(sid)); self.assertTrue(self.sessions.setup_mode())
        self.sessions.sweep()
        self.assertEqual([e['detail'] for e in self.audit() if e['event'] == 'session.ended'], ['user_disabled', 'password_reset', 'user_deleted'])

    def test_eviction_bounds(self):
        ids = [self.sessions.create(self.record, '203.0.113.7')[0] for _ in range(33)]
        self.assertEqual(self.sessions.count('alice'), 32); self.assertIsNone(self.sessions.resolve(ids[0]))
        self.assertEqual([e['detail'] for e in self.audit() if e['event'] == 'session.ended'], ['evicted'])
        users = {f'u{i:03d}': accounts.new_record(f'u{i:03d}', 'operator', accounts.DUMMY_HASH, created_by='root', must_change_password=False) for i in range(20)}
        self.sessions.load_users({**users, 'alice': self.record})
        for name, record in users.items():
            for _ in range(30): self.sessions.create(record, '203.0.113.8')
        with self.sessions.lock: total = len(self.sessions.sessions)
        self.assertEqual(total, 512)

    def test_end_and_end_user_audit_and_run_callbacks(self):
        ended = []; self.sessions.on_end.append(ended.append)
        a, _ = self.sessions.create(self.record, '203.0.113.7'); b, _ = self.sessions.create(self.record, '203.0.113.7'); c, _ = self.sessions.create(self.record, '203.0.113.7')
        self.assertEqual(self.sessions.end(a, 'signout')['user'], 'alice'); self.assertIsNone(self.sessions.end(a, 'signout'))
        self.assertEqual(self.sessions.end_user('alice', 'password_changed', keep=c), 1)
        self.assertEqual(ended, [a, b]); self.assertIsNotNone(self.sessions.resolve(c))
        self.assertEqual([(e['event'], e['detail'], e['source']) for e in self.audit()], [('signout', '', '203.0.113.7'), ('session.ended', 'password_changed', '203.0.113.7')])

    def test_rotate_moves_the_record_and_writes_the_stamp(self):
        sid, _ = self.sessions.create(self.record, '203.0.113.7')
        new = self.sessions.rotate(sid, 'new-stamp')
        self.assertNotEqual(new, sid); self.assertIsNone(self.sessions.resolve(sid))
        with self.sessions.lock: self.assertEqual(self.sessions.sessions[new]['password_changed'], 'new-stamp')
        self.sessions.set_user({**self.record, 'password_changed': 'new-stamp'})
        self.assertIsNotNone(self.sessions.resolve(new))

    def test_touch_and_expiry_on_the_fake_clock(self):
        sid, _ = self.sessions.create(self.record, '203.0.113.7')
        self.now[0] = 100.0 + IDLE - 1; self.assertIsNotNone(self.sessions.resolve(sid))
        self.sessions.touch(sid)
        self.now[0] = 100.0 + IDLE + 1; self.assertIsNotNone(self.sessions.resolve(sid), 'renewed by touch')
        self.now[0] = 100.0 + IDLE + IDLE; self.assertIsNone(self.sessions.resolve(sid))
        self.sessions.sweep()
        self.assertEqual([e['detail'] for e in self.audit() if e['event'] == 'session.expired'], ['idle'])

    def test_source_key_and_prefix(self):
        self.assertEqual(source_key('203.0.113.7'), '203.0.113.7'); self.assertEqual(source_prefix('203.0.113.7'), '203.0.113.0/24')
        self.assertEqual(source_key('::ffff:203.0.113.7'), '203.0.113.7'); self.assertEqual(source_prefix('::ffff:203.0.113.7'), '203.0.113.0/24')
        self.assertEqual(source_key('2001:db8:1:2:3:4:5:6'), '2001:db8:1:2::/64'); self.assertEqual(source_prefix('2001:db8:1:2:3:4:5:6'), '2001:db8:1:2::/64')
        self.assertEqual(source_key('testclient'), 'testclient'); self.assertEqual(source_prefix('testclient'), '')
        self.assertEqual(source_key(''), '-'); self.assertEqual(source_key(None), '-')


if __name__ == '__main__':
    unittest.main()
