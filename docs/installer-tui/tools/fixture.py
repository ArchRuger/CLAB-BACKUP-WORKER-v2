"""FIXTURE ONLY: a Slate Ops app wired to scripted data for snapshots and headless tests.

Nothing here runs a probe, a helper or sudo. The account, host and status values are
invented and say so; the real installer never imports this module (it is not under
deploy/, and install.sh has no option that reaches it).
"""
import sys
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'deploy'))

from installer_tui import app as slate  # noqa: E402
from installer_tui import engine, probes, theme  # noqa: E402

FIXTURE_STATUS = {
    'prereqs': (probes.READY, 'Docker, Compose, containerlab, Git and SSH found', ''),
    'manager': (probes.ATTENTION, 'Running 1.30.57; this checkout is SOURCE', 'Install/update rebuilds it from this checkout.'),
    'access': (probes.NEEDS_AUTH, 'Account and helpers present; password state needs sudo', ''),
    'engineer': (probes.READY, 'docker and clab_admins groups and containerlab access for student', ''),
    'git': (probes.ATTENTION, 'No checkout registered yet', 'Git setup / repair registers one.'),
    'capture': (probes.READY, 'Edgeshark answering on 127.0.0.1:5001 (edgeshark)', ''),
    'lazydocker': (probes.NOT_INSTALLED, 'Not installed (optional)', ''),
    'sudo': (probes.NEEDS_AUTH, 'asks for your password when needed', ''),
}


def context(no_color=False, ascii_only=False, status=FIXTURE_STATUS, host='fixture-vm', source=None):
    install = slate.load_install()
    look = theme.Look(no_color=no_color, ascii_only=ascii_only)
    ctx = slate.Context.__new__(slate.Context)
    ctx.install = install
    ctx.look = look
    ctx.account = SimpleNamespace(pw_name='student', pw_dir='/home/student')
    ctx.env = install.environment(ctx.account)
    ctx.version = install.source_version()
    ctx.host = host
    ctx.source = source or install.SOURCE
    ctx.options = install.Options()
    ctx.advanced = False
    ctx.status = probes.placeholder()
    for key, (state, summary, detail) in (status or {}).items():
        ctx.status[key] = probes.Result(key, dict(probes.COMPONENTS + probes.EXTRA)[key], state,
                                        summary.replace('SOURCE', ctx.version), detail,
                                        '1.30.57' if key == 'manager' else None)
    ctx.checked_at = time.time() - 95
    ctx.checking = False
    ctx.last_run = {'action': 'install', 'finished': '2026-10-03T13:58:00', 'outcome': 'partial', 'interrupted': ''}
    ctx.health = None
    ctx.env_state = lambda: 'missing'
    return ctx


class FakeInstall:
    """A stand-in for install-manager.py whose phases sleep or fail on cue (fixture runs only)."""

    def __init__(self, real, script):
        self._real = real
        self.script = script   # {key: list of outcomes per attempt: 'ok', 'fail', 'lock', 'auth'}
        self.SOURCE = real.SOURCE
        self.LOCK_SIGNATURE = real.LOCK_SIGNATURE
        self.RESTART_HINT = real.RESTART_HINT
        self.ENGINEER_RECONNECT = real.ENGINEER_RECONNECT
        self.Step = real.Step
        self.Options = real.Options

    def __getattr__(self, name):
        return getattr(self._real, name)


def make_app(ctx, start=None):
    return slate.SlateOps(ctx, start_action=start, ansi_color=True if ctx.look.no_color else None)
