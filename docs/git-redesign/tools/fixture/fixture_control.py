"""The fixture's control: switches a browser script can set while the server runs, and one-time actions.

Mechanism (one, documented in SCENARIOS.md): three routes mounted by the fixture on the real application, outside /api/,
so the application's own guard and routes are untouched. They answer on 127.0.0.1 only because the fixture does.

    GET  /fixture/state    switches, devices, repositories (heads, waiting commits), scenario names
    POST /fixture/switch   {"<name>": value, ...}   null clears a switch; "@<checkout>" scopes a name to one repository
    POST /fixture/action   {"action": "<name>", ...arguments}

A scoped switch is written `<name>@<repository>`, for example `status_problem@Nested-Labs`; the plain name applies to
every repository. `python fixture_control.py http://127.0.0.1:8191 switch push_fail_once=true` does the same from a shell.
"""
import json
import sys
import threading
import urllib.request

SWITCHES = {
    'vm_unreachable': 'true: every call of the Git helper fails the way an unreachable VM does',
    'status_problem': "staged | edits | operation | diverged | permission | any sentence: `status` answers ready=false with it",
    'remote_unreachable': 'true: the remote cannot be asked (push, compare.outgoing, update, retire)',
    'remote_ahead': 'true: the remote has a commit this VM lacks (push refused as diverged; update fast-forwards when nothing waits)',
    'push_refused': 'true: every push fails as when the account lacks permission',
    'push_fail_once': 'true: the next push fails once (Upload failed), then clears itself',
    'no_repositories': 'true: the helper `list` answers no repository (a VM with nothing registered; the first save asks for an address)',
    'list_first': 'repository name to list first in the helper `list` answer',
    'unreadable_states': 'list of folder paths whose manifest summary is null',
    'capture_seconds': 'seconds a capture (Save) takes, default 6',
    'restore_capture_seconds': 'seconds each safety backup of a load takes, default 2',
    'device_unreadable': 'list of devices (short or full name) a capture cannot read: Save ends "could not be read"',
    'load_preset': 'all-ok | one-failed | one-rolled-back | one-uncertain | one-unreachable | one-blocked | one-editing | one-bad-login | slow',
    'load_device': 'device (short or full name) the one-* presets act on, default xrv9k',
    'load_script': '{device: failed | rolled_back | uncertain | unreachable | blocked | blocked-editing | bad-login | slow | ok}, overrides the preset',
    'load_seconds': 'seconds per device rank for `slow` (device k settles after k*load_seconds), default 5',
}


class Control:
    def __init__(self):
        self.lock = threading.RLock()
        self.values = {}

    def get(self, name, scope=None, default=None):
        with self.lock:
            if scope is not None and (name + '@' + scope) in self.values:
                return self.values[name + '@' + scope]
            return self.values.get(name, default)

    def take(self, name, scope=None):
        """A one-time flag: true once, then cleared."""
        with self.lock:
            for key in ((name + '@' + scope) if scope is not None else None, name):
                if key and self.values.get(key):
                    self.values.pop(key)
                    return True
        return False

    def set(self, **values):
        with self.lock:
            for name, value in values.items():
                base = name.split('@', 1)[0]
                if base not in SWITCHES:
                    raise ValueError('Unknown switch ' + name + '. Known: ' + ', '.join(sorted(SWITCHES)))
                if value is None or value is False:
                    self.values.pop(name, None)
                else:
                    self.values[name] = value

    def reset(self):
        with self.lock:
            self.values.clear()

    def snapshot(self):
        with self.lock:
            return dict(self.values)


def install(app, control, actions, describe):
    """Mount the three routes. `actions` maps an action name to a callable(**arguments) -> JSON-able; `describe()` returns
    the state document of GET /fixture/state."""
    from fastapi import Request
    from fastapi.responses import JSONResponse

    @app.get('/fixture/state')
    def state():
        return {'switches': control.snapshot(), 'known_switches': SWITCHES, 'actions': sorted(actions), **describe()}

    @app.post('/fixture/switch')
    async def switch(request: Request):
        body = await request.json()
        if not isinstance(body, dict):
            return JSONResponse({'error': 'Send a JSON object of switches.'}, status_code=400)
        try:
            control.set(**body)
        except ValueError as exc:
            return JSONResponse({'error': str(exc)}, status_code=400)
        return {'switches': control.snapshot()}

    @app.post('/fixture/action')
    async def action(request: Request):
        body = await request.json()
        name = body.pop('action', '') if isinstance(body, dict) else ''
        if name not in actions:
            return JSONResponse({'error': 'Unknown action. Known: ' + ', '.join(sorted(actions))}, status_code=400)
        try:
            return {'ok': True, 'result': actions[name](**body)}
        except (ValueError, TypeError) as exc:
            return JSONResponse({'error': str(exc)}, status_code=400)


def call(base, route, body=None):
    request = urllib.request.Request(base.rstrip('/') + route, data=json.dumps(body).encode() if body is not None else None,
                                     headers={'Content-Type': 'application/json'}, method='POST' if body is not None else 'GET')
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode())


def main(argv):
    if len(argv) < 3:
        print(__doc__)
        return 2
    base, kind, rest = argv[1], argv[2], argv[3:]
    if kind == 'state':
        print(json.dumps(call(base, '/fixture/state'), indent=1))
    elif kind == 'switch':
        body = {}
        for item in rest:
            name, _, value = item.partition('=')
            body[name] = None if value in ('', 'null') else json.loads(value) if value[:1] in '[{' or value in ('true', 'false') or value.replace('.', '', 1).isdigit() else value
        print(json.dumps(call(base, '/fixture/switch', body)))
    elif kind == 'action':
        print(json.dumps(call(base, '/fixture/action', json.loads(rest[0]) if rest else {})))
    else:
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
