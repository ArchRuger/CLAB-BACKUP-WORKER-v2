"""Read-only facts for the health check, without a session: `python -m app.probe <name> [arg]`.

docs/sign-on/EXPOSURE.md 6.1 is the contract (DESIGN.md 6.7, REVIEW R16). The health check runs a probe through
`docker exec <container>`, so it acts with the container's own trust and asks the manager nothing over HTTP. A probe
prints exactly one line of JSON on stdout and nothing on stderr; it exits 0 for an answer, 1 for
`{"error": "<sentence>"}` and 2 for an unknown name or a bad argument (usage on stderr, no JSON). Every string it
prints is at most 600 characters, fields keep the documented order and none is omitted.

What a probe never does: construct a `Store` (constructing one writes state, and a second process against the live
data is forbidden), start the application or build a class that takes a `Store`, write a file, log, make an HTTP request to the
manager, or print a password, key, hash, setup code, session id, cookie value, host fingerprint or capture token. The
three that need the saved state decrypt `state.enc` read-only in the `STORAGE_PROBE` pattern of
deploy/check_install.py and run the manager's own module-level clients in their read-only modes: the operations
helper's `browse` and the Git helper's `list`, neither of which takes a helper lock.
"""
import json
import logging
import os
from pathlib import Path
import sys
import warnings

sys.dont_write_bytecode = True   # the probe's imports leave no files behind either

MAX_STATE = 64 * 1024 * 1024
MAX_KEY = 4096
MAX_TEXT = 600
MAX_ENTRIES = 500
BROWSE_TIMEOUT = 25
STATE_UNREADABLE = 'state unreadable'
RESET_PENDING = 'reset pending'
UNEXPECTED = 'The probe failed unexpectedly.'
USAGE = 'usage: python -m app.probe {design-engine | capture | vm-connection | browse <path> | git-registry}'
# The status route's two sentences (capture.py, Captures.install, GET /api/capture/status).
CAPTURE_READY = 'Ready to discover live interfaces.'
CAPTURE_OPTIONAL = 'Packet capture is optional. Follow Capture setup to enable it.'


class ProbeError(Exception):
    """A fixed sentence printed as {"error": …}."""


class Usage(Exception):
    pass


def data_dir():
    return Path(os.environ.get('DATA_DIR', '/data'))   # as the app factory reads it (main.py:51)


def read_bounded(path, limit):
    with open(path, 'rb') as handle:
        data = handle.read(limit + 1)
    if len(data) > limit:
        raise ProbeError(STATE_UNREADABLE)
    return data


def read_state():
    """The decrypted state document, read-only; ProbeError('reset pending') while a reset journal exists (the
    manager may be moving the files), ProbeError('state unreadable') for missing, oversized or undecryptable files."""
    root = data_dir()
    if (root / '.reset-pending').exists():
        raise ProbeError(RESET_PENDING)
    try:
        from cryptography.fernet import Fernet
        key = read_bounded(root / 'state.key', MAX_KEY)
        data = read_bounded(root / 'state.enc', MAX_STATE)
        state = json.loads(Fernet(key.strip()).decrypt(data))
    except ProbeError:
        raise
    except Exception:
        raise ProbeError(STATE_UNREADABLE) from None
    if not isinstance(state, dict) or not isinstance(state.get('labs', []), list):
        raise ProbeError(STATE_UNREADABLE)
    state.setdefault('labs', [])
    return state


def saved_host(state):
    host = state.get('host')
    return host if isinstance(host, dict) else {}


def text(value):
    return value if isinstance(value, str) else ''


def design_engine(args):
    from . import design_engine as engine
    status = engine.engine_status()
    return {'available': status.get('available') is True, 'version': text(status.get('version')),
            'path': text(status.get('path')), 'diagnostic': text(status.get('diagnostic'))}


def capture(args):
    """The provider configuration as the manager builds it, then Edgeshark discovery and the session service's
    health over loopback; the count of capture locations only, so no lab state is needed."""
    from .capture import CaptureError, configured_provider, merge_shared_namespaces
    from .capture_sessions import BrowserSessions
    environ = os.environ
    provider = sessions = None
    error = ''
    try:   # Captures.__init__, without the class (it takes a Store)
        provider = configured_provider(environ)
        if provider:
            sessions = BrowserSessions(environ.get('CAPTURE_SESSION_URL', 'http://127.0.0.1:5801'),
                                       environ.get('CAPTURE_SESSION_TOKEN', ''))
    except CaptureError as exc:
        provider, sessions, error = None, None, str(exc)
    answer = {'enabled': bool(provider), 'provider': 'edgeshark' if provider else 'disabled',
              'message': error or (CAPTURE_READY if provider else CAPTURE_OPTIONAL),
              'targets': None, 'ready': None, 'diagnostic': ''}
    if provider:
        try:
            answer['targets'] = len(merge_shared_namespaces(provider.discover()))
        except CaptureError as exc:
            answer['diagnostic'] = str(exc)
        try:
            ready = sessions.request('GET', 'health').get('ready')
            answer['ready'] = ready if isinstance(ready, bool) else None
        except Exception:
            answer['ready'] = None
    # The CaptureError sentences name no URL by construction; the configured values are removed anyway.
    hidden = [environ.get(key, '') for key in ('CAPTURE_SESSION_TOKEN', 'CAPTURE_EDGESHARK_URL', 'CAPTURE_SESSION_URL')]
    hidden += [value.rstrip('/') for value in hidden]
    for key in ('message', 'diagnostic'):
        for value in sorted({v for v in hidden if len(v) >= 4}, key=len, reverse=True):
            answer[key] = answer[key].replace(value, '[redacted]')
    return answer


def vm_connection(args):
    from .discovery import discovery_fresh
    state = read_state()
    host = saved_host(state)
    info = state.get('discovery') if isinstance(state.get('discovery'), dict) else {}
    public = None
    if host:
        public = {'address': text(host.get('address')), 'port': host['port'] if type(host.get('port')) is int else 0,
                  'username': text(host.get('username')), 'auth': text(host.get('auth')),
                  'command_mode': text(host.get('command_mode')), 'enabled': host.get('enabled') is True,
                  'fingerprint_saved': bool(host.get('fingerprint'))}
    checked = info.get('checked_at')
    return {'configured': bool(state.get('host')), 'connected': discovery_fresh({'host': host, 'discovery': info}),
            'host': public, 'checked_at': checked if isinstance(checked, str) else None}


def valid_path(path):
    """'' (the trusted roots) or the check's own rule (check_install.valid_path), within the 600-character limit."""
    return path == '' or (len(path) <= MAX_TEXT and path.startswith('/') and '..' not in Path(path).parts
                          and not any(ord(c) < 32 or ord(c) == 127 for c in path))


def browse(args):
    """The operations helper's `browse` mode, as POST /api/operations/browse sends it without `files`."""
    from . import lab_operations
    from .device_diagnostics import OLD_HELPER_SENTENCE, UNREACHABLE_SENTENCE, UNUSABLE_SENTENCE
    path, = args
    state = read_state()
    try:
        result = lab_operations.remote(saved_host(state), {'mode': 'browse', 'path': path}, timeout=BROWSE_TIMEOUT)
    except Exception as exc:   # DeviceDiagnostics.ask: a ValueError is the manager's sentence, anything else is fixed
        message = str(exc) if type(exc) is ValueError else UNREACHABLE_SENTENCE
        if message == 'Unknown request mode.': message = OLD_HELPER_SENTENCE
        raise ProbeError(lab_operations.scrub(message, state))
    if not isinstance(result, dict) or not isinstance(result.get('entries'), list):
        raise ProbeError(UNUSABLE_SENTENCE)
    entries = []
    for entry in result['entries'][:MAX_ENTRIES]:
        if not isinstance(entry, dict) or not isinstance(entry.get('name'), str) or not isinstance(entry.get('path'), str):
            continue
        if len(entry['name']) > MAX_TEXT or len(entry['path']) > MAX_TEXT:
            continue   # a cut path would name another folder; such an entry is left out, not shortened
        entries.append({'name': entry['name'], 'path': entry['path'], 'directory': entry.get('directory') is True})
    return {'path': text(result.get('path')), 'entries': entries}


def git_registry(args):
    """The Git helper's `list` mode, counted: the registrations' owners, paths and URLs are never printed."""
    from . import git_progress
    from .lab_operations import scrub
    state = read_state()
    try:
        result = git_progress.remote_git(saved_host(state), {'mode': 'list'})
    except ValueError as exc:   # GitProgress.invoke: the helper's fixed sentences pass, anything else is scrubbed
        message = str(exc)
        raise ProbeError(message if message in git_progress.PROBLEM_CODES else scrub(message, state))
    except Exception:
        raise ProbeError(git_progress.VM_UNREACHABLE)
    if not isinstance(result, dict) or not isinstance(result.get('repositories'), list):
        raise ProbeError('Invalid repository list.')
    bound = sum(1 for lab in state['labs'] if isinstance(lab, dict) and lab.get('git_binding'))
    return {'protocol': text(result.get('protocol')), 'version': text(result.get('version')),
            'repositories': len(result['repositories']), 'bound_labs': bound}


PROBES = {'design-engine': (design_engine, 0), 'capture': (capture, 0), 'vm-connection': (vm_connection, 0),
          'browse': (browse, 1), 'git-registry': (git_registry, 0)}


def limited(value):
    """Every string at most 600 characters, recursively; order and keys unchanged."""
    if isinstance(value, str): return value[:MAX_TEXT]
    if isinstance(value, dict): return {key: limited(item) for key, item in value.items()}
    if isinstance(value, list): return [limited(item) for item in value]
    return value


def run(argv):
    """(exit code, the printed object) or Usage."""
    if not argv or argv[0] not in PROBES:
        raise Usage()
    probe, count = PROBES[argv[0]]
    args = argv[1:]
    if len(args) != count or (argv[0] == 'browse' and not valid_path(args[0])):
        raise Usage()
    try:
        return 0, probe(args)
    except ProbeError as exc:
        return 1, {'error': str(exc)}
    except Exception:
        return 1, {'error': UNEXPECTED}   # never a traceback: it could carry a value from the state


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    disabled = logging.root.manager.disable
    logging.disable(logging.CRITICAL)   # paramiko and httpx log through the root's last resort, which is stderr
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            try:
                code, value = run(argv)
            except Usage:
                print(USAGE, file=sys.stderr, flush=True)
                return 2
    finally:
        logging.disable(disabled)
    print(json.dumps(limited(value)), flush=True)
    return code


if __name__ == '__main__':
    sys.exit(main())
