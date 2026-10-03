"""Keyboard-driven tests for the Slate Ops full-screen installer (deploy/installer_tui/app.py).

The tests drive the real Textual app headlessly with `App.run_test` and the Pilot, using
only key presses (and a resize), against FIXTURE data from docs/installer-tui/tools/fixture.py.

Safety: nothing here may reach the real install-manager.py run path. Runs shown on the run
screen are scripted objects whose phase states are set directly, and the one integration
section uses a FAKE install module whose steps are harmless `sh -c` commands in a temporary
directory. `engine.Run.start` and `core.StepProcess.start` are guarded so that any other use
fails loudly instead of running sudo or a helper. Probes, the installer lock and the run
record are redirected to temporary locations.

Textual is an optional dependency of the installer (it lives in a provisioned virtualenv, not
in system Python). Without it this module is skipped, unless INSTALLER_TUI_REQUIRED=1 is set
(CI), in which case the import fails loudly so the suite can never silently skip.
"""
import asyncio
import contextlib
import io
import os
from pathlib import Path
import re
import shlex
import signal
import sys
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'deploy'))
sys.path.insert(0, str(ROOT / 'docs' / 'installer-tui' / 'tools'))

try:
    import textual  # noqa: F401
except ImportError as error:  # pragma: no cover - depends on the interpreter running the suite
    if os.environ.get('INSTALLER_TUI_REQUIRED') == '1':
        raise ImportError('INSTALLER_TUI_REQUIRED=1 but textual cannot be imported by '
                          f'{sys.executable}: {error}') from error
    raise unittest.SkipTest('textual is not installed for this interpreter; the Slate Ops tests need the '
                            'installer virtualenv (set INSTALLER_TUI_REQUIRED=1 to make this a failure)')

from rich.console import Console  # noqa: E402
from rich.text import Text  # noqa: E402
from textual.widgets import Button, Checkbox, Input, ListItem, Log, RadioSet, Static  # noqa: E402

import fixture  # noqa: E402
from installer_tui import app as slate  # noqa: E402
from installer_tui import core, engine, probes  # noqa: E402

SIZES = [(80, 24), (120, 40), (160, 50)]
FULL_LABELS = ['Install / update', 'Git setup / repair', 'VS Code / Containerlab access', 'Browser Wireshark stack',
               'Check installation', 'Advanced settings', 'Exit']
NARROW_ALTERNATIVES = {'VS Code / Containerlab access': 'VS Code / clab access',
                       'Browser Wireshark stack': 'Browser Wireshark'}
DETAIL_TITLES = ['INSTALL OR UPDATE THE MANAGER', 'GIT SETUP OR REPAIR', 'VS CODE / CONTAINERLAB EXTENSION ACCESS',
                 'BROWSER WIRESHARK STACK', 'CHECK THE INSTALLATION', 'ADVANCED SETTINGS', 'EXIT']


# --------------------------------------------------------------------------------------------
# Text extraction
# --------------------------------------------------------------------------------------------
def plain(renderable, width=400):
    """Plain text of a Rich renderable (rendered wide, so nothing wraps)."""
    if isinstance(renderable, str):
        return renderable
    if isinstance(renderable, Text):
        return renderable.plain
    console = Console(width=width, file=io.StringIO(), force_terminal=False, color_system=None, legacy_windows=False)
    console.print(renderable)
    return console.file.getvalue()


def widget_text(widget, width=400):
    return plain(widget.content, width)


def screen_text(app):
    """What is actually painted on the active screen, one string per terminal row."""
    return '\n'.join(strip.text for strip in app.screen._compositor.render_strips())


def collapse(text):
    return re.sub(r'\s+', ' ', text).strip()


def nav_labels(app):
    return [widget_text(item.query_one('Label')).strip() for item in app.screen.query('#nav > ListItem')]


def highlighted_nav(app):
    return [item.id for item in app.screen.query('#nav > ListItem') if item.has_class('-highlight')]


def footer_text(app):
    return widget_text(app.screen.query_one(slate.Footer))


def notifications(app):
    return [note.message for note in app._notifications]


# --------------------------------------------------------------------------------------------
# Scripted runs and fakes
# --------------------------------------------------------------------------------------------
class AliveThread:
    """Stands in for a run thread that is still going (Run.active is `thread.is_alive()`)."""

    def is_alive(self):
        return True


def scripted_run(ctx, action='install', states=None, default=engine.PENDING, alive=False, outcome=None):
    """A Run whose phase states are set directly. Its thread is never started."""
    run = engine.Run(ctx.install, action, ctx.env, ctx.version, options=ctx.options)
    now = time.monotonic()
    run.started = time.time() - 120
    states = states or {}
    for index, phase in enumerate(run.phases):
        phase.state = states.get(phase.key, default)
        if phase.state in (engine.COMPLETED, engine.SKIPPED, engine.FAILED):
            phase.started, phase.finished = now - 100 + index * 5, now - 95 + index * 5
            phase.attempts, phase.code = 1, 0 if phase.state == engine.COMPLETED else 1
        elif phase.state == engine.RUNNING:
            phase.started, phase.attempts = now - 20, 1
    running = next((p for p in run.phases if p.state in (engine.RUNNING, engine.FAILED)), None)
    run.current = running if alive else None
    run.outcome = outcome
    if alive:
        run.thread = AliveThread()
    else:
        run.finished_at = time.time()
    return run


def full_install_run(ctx, partial=True):
    """A finished install: every phase Completed; with `partial`, Git skipped and lazydocker skipped."""
    run = scripted_run(ctx, 'install', default=engine.COMPLETED)
    run.phase('verify').outcome = 'http://127.0.0.1:8081/'
    if partial:
        git, lazy = run.phase('git'), run.phase('lazydocker')
        git.state, git.code, git.note = engine.SKIPPED, 2, 'not completed; run it again later from the dashboard'
        lazy.state, lazy.outcome = engine.SKIPPED, ('skipped', 'network unreachable (fixture)')
        run.outcome = 'partial'
    else:
        run.phase('lazydocker').outcome = ('installed', 'lazydocker 0.24.1 installed.')
        run.outcome = 'completed'
    return run


class FakeInstall:
    """A stand-in for install-manager.py whose phases are harmless `sh -c` commands."""

    def __init__(self, real, root, steps):
        self.SOURCE = root
        self.LOCK_SIGNATURE = real.LOCK_SIGNATURE
        self.RESTART_HINT = real.RESTART_HINT
        self.ENGINEER_RECONNECT = real.ENGINEER_RECONNECT
        self.Step = real.Step
        self.Options = real.Options
        self.environment = real.environment
        self.source_version = real.source_version
        self.steps = steps    # action -> list of Step
        self.calls = []

    def action_steps(self, action, env, version, options=None):
        return list(self.steps.get(action, []))

    def install_steps(self, env, version, options):
        return self.action_steps('install', env, version, options)

    def plan_lines(self, env, version, options):
        return ['Fake plan line']

    def copy_env(self, path):
        self.calls.append('copy_env')

    def check_manager(self, env, version, wait_seconds=45, say=print, sudo=('sudo',)):
        say('fake manager check')
        return 'http://127.0.0.1:8081/'

    def setup_lazydocker(self, env, say=print):
        return ('installed', 'fake lazydocker')

    def git_setup(self, env):
        return 0

    def run(self, args, env, capture=False, tee=False):
        raise AssertionError('the fake install module never runs a real command: ' + repr(args))

    def lock_free(self, env):
        return True

    def lock_holder_text(self, env):
        return ''

    def lock_wait_command(self):
        return ['sh', '-c', 'true']


def sh_step(real, key, title, script, *args):
    return real.Step(key, title, None, argv=['sh', '-c', script, 'sh', *args])


# --------------------------------------------------------------------------------------------
# Base class
# --------------------------------------------------------------------------------------------
class SlateCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='slate-tui-test-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.lock_path = self.root / 'installer.lock'
        self.probe_calls = []

        def fake_run_all(context, keys=None, on_result=None):
            self.probe_calls.append(keys)
            return {}, time.time()

        def guarded_start(run_self):
            if not isinstance(run_self.install, FakeInstall):
                raise AssertionError('a test tried to start a real engine.Run against the real install module')
            return real_start(run_self)

        real_start = engine.Run.start
        real_step_start = core.StepProcess.start

        def guarded_step_start(process):
            if process.argv[:1] != ['sh']:
                raise AssertionError('a test tried to run a non-fixture command: ' + repr(process.argv))
            return real_step_start(process)

        patches = [
            patch.dict(os.environ, {'XDG_STATE_HOME': str(self.root / 'state')}),
            patch.object(probes, 'run_all', fake_run_all),
            patch.object(core, 'default_lock_path', lambda: self.lock_path),
            patch.object(engine.Run, 'start', guarded_start),
            patch.object(core.StepProcess, 'start', guarded_step_start),
            patch.object(engine, 'credentials_cached', lambda env, cwd: True),
            patch.object(core, 'run_capture', lambda argv, env, cwd, timeout=10: (0, 'clab-discovery P')),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        # App.on_mount installs SIGHUP/SIGTERM handlers; put the originals back afterwards.
        for signum in (signal.SIGHUP, signal.SIGTERM):
            self.addCleanup(signal.signal, signum, signal.getsignal(signum))

    async def asyncSetUp(self):
        # IsolatedAsyncioTestCase turns on asyncio debug mode, which slows the app and logs
        # "slow callback" noise for every Textual frame.
        asyncio.get_running_loop().set_debug(False)

    def ctx(self, **kwargs):
        return fixture.context(**kwargs)

    @contextlib.asynccontextmanager
    async def running(self, size=(120, 40), ctx=None, start=None):
        ctx = ctx or self.ctx()
        app = fixture.make_app(ctx, start)
        try:
            async with app.run_test(size=size) as pilot:
                await pilot.pause()
                yield app, pilot
        finally:
            run = app.current_run
            thread = getattr(run, 'thread', None)
            if isinstance(thread, __import__('threading').Thread):
                # Never leave a real (fake-install) run thread blocked on a decision.
                if app.bridge is not None:
                    app.bridge.alive = False
                    app.bridge.decisions.put(engine.RETURN)
                run.disconnect('test finished')
                thread.join(timeout=10)

    def result_ready(self, app):
        """The result screen is on top and has rendered its summary."""
        if not isinstance(app.screen, slate.ResultScreen):
            return False
        try:
            return bool(widget_text(app.screen.query_one('#result', Static)).strip())
        except Exception:
            return False

    async def wait_for(self, pilot, condition, what, timeout=15.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if condition():
                return
            await pilot.pause(0.05)
        self.fail(f'timed out after {timeout}s waiting for: {what}')

    async def focus(self, app, pilot, widget_id):
        """Move focus to #widget_id with Tab or Shift+Tab (whichever is fewer presses)."""
        chain = list(app.screen.focus_chain)
        targets = [i for i, widget in enumerate(chain) if widget.id == widget_id]
        if not targets:
            self.fail(f'#{widget_id} is not in the focus chain: {[w.id for w in chain]}')
        target = targets[0]
        current = chain.index(app.focused) if app.focused in chain else -1
        forward = (target - current) % len(chain)
        backward = (current - target) % len(chain) if current >= 0 else len(chain)
        if forward <= backward:
            await pilot.press(*['tab'] * forward)
        else:
            await pilot.press(*['shift+tab'] * backward)
        await pilot.pause()
        self.assertIsNotNone(app.focused)
        self.assertEqual(app.focused.id, widget_id, f'focus is on {app.focused!r}')
        return app.focused

    async def open_nav(self, app, pilot, index):
        await pilot.press(*['down'] * index)
        await pilot.press('enter')
        await pilot.pause()

    async def show_run(self, app, pilot, run):
        app.current_run = run
        screen = slate.RunScreen(run)
        await app.push_screen(screen)
        await pilot.pause()
        return screen

    async def show_result(self, app, pilot, run):
        app.current_run = run
        await app.push_screen(slate.ResultScreen(run))
        await pilot.pause()
        return app.screen


# --------------------------------------------------------------------------------------------
# 1. Dashboard
# --------------------------------------------------------------------------------------------
class DashboardTests(SlateCase):
    async def test_header_actions_and_focus_at_every_size(self):
        for size in SIZES:
            with self.subTest(size=size):
                ctx = self.ctx()
                async with self.running(size, ctx) as (app, pilot):
                    self.assertIsInstance(app.screen, slate.Dashboard)
                    text = screen_text(app)
                    self.assertIn('SLATE OPS', text)
                    self.assertIn('source ' + ctx.version, text)
                    # Nav has focus, index 0.
                    nav = app.screen.query_one('#nav')
                    self.assertIs(app.focused, nav)
                    self.assertEqual(nav.index, 0)
                    self.assertEqual(highlighted_nav(app), ['nav-install'])
                    # All seven actions, in order; narrow widths may use the short form.
                    labels = nav_labels(app)
                    self.assertEqual(len(labels), 7)
                    for label, full in zip(labels, FULL_LABELS):
                        self.assertIn(label, (full, NARROW_ALTERNATIVES.get(full, full)))
                    if size[0] >= 110:
                        self.assertEqual(labels, FULL_LABELS)
                    rows = [next(i for i, line in enumerate(text.splitlines()) if label in line) for label in labels]
                    self.assertEqual(rows, sorted(rows), 'actions are listed top to bottom in order')

    async def test_header_shows_account_and_host_at_roomy_sizes(self):
        ctx = self.ctx()
        for size in SIZES[1:]:
            with self.subTest(size=size):
                async with self.running(size, ctx) as (app, pilot):
                    header = widget_text(app.screen.query_one('#header-title'))
                    self.assertIn(f'{ctx.account.pw_name}@{ctx.host}', header)

    async def test_header_shows_account_and_host_at_80x24(self):
        # PRODUCT BUG: deploy/installer_tui/app.py:147-151 (Header.refresh_text). At 80x24 the left
        # title ("SLATE OPS | Containerlab Node Manager setup | Dashboard", 59 cells) leaves
        # 72 - 59 - len("student@fixture-vm") < 2 cells of padding, so the right-hand account@host is dropped
        # entirely, and the Session panel that also names account and host is hidden at height < 32
        # (theme.py: `App.-short #session-panel { display: none; }`). Expected: account@host visible in
        # the header (or somewhere) at 80x24; actual: it appears nowhere on screen.
        ctx = self.ctx()
        async with self.running((80, 24), ctx) as (app, pilot):
            self.assertIn(f'{ctx.account.pw_name}@{ctx.host}', screen_text(app))

    async def test_arrow_keys_move_highlight_and_update_details_title(self):
        async with self.running((120, 40)) as (app, pilot):
            nav = app.screen.query_one('#nav')
            title = app.screen.query_one('#detail-title')
            self.assertEqual(widget_text(title), DETAIL_TITLES[0])
            for index in range(1, 7):
                await pilot.press('down')
                await pilot.pause()
                self.assertEqual(nav.index, index)
                self.assertEqual(highlighted_nav(app), ['nav-' + slate.ACTIONS[index][0]])
                self.assertEqual(widget_text(title), DETAIL_TITLES[index])
            await pilot.press('up')
            await pilot.pause()
            self.assertEqual(nav.index, 5)
            self.assertEqual(widget_text(title), DETAIL_TITLES[5])

    async def test_vscode_details_title_on_screen_at_80x24(self):
        async with self.running((80, 24)) as (app, pilot):
            await pilot.press('down', 'down')
            await pilot.pause()
            self.assertIn('VS CODE / CONTAINERLAB EXTENSION ACCESS', screen_text(app))

    async def test_capture_details_never_claim_interruption_free(self):
        async with self.running((120, 40)) as (app, pilot):
            await pilot.press('down', 'down', 'down')
            await pilot.pause()
            self.assertEqual(widget_text(app.screen.query_one('#detail-title')), 'BROWSER WIRESHARK STACK')
            body = collapse(widget_text(app.screen.query_one('#detail-body'))).lower()
            self.assertIn('manager container is recreated', body)
            self.assertIn('not interruption-free', body)
            self.assertIsNone(re.search(r'(?<!not )interruption-free', body))

    async def test_tab_moves_to_details_and_keeps_nav_highlight(self):
        async with self.running((120, 40)) as (app, pilot):
            await pilot.press('down', 'down')
            await pilot.pause()
            await pilot.press('tab')
            await pilot.pause()
            self.assertEqual(app.focused.id, 'detail-panel')
            self.assertEqual(highlighted_nav(app), ['nav-engineer'])
            self.assertEqual(app.screen.query_one('#nav').index, 2)
            # shift+tab returns to the nav with the same row selected.
            await pilot.press('shift+tab')
            await pilot.pause()
            self.assertEqual(app.focused.id, 'nav')
            self.assertEqual(highlighted_nav(app), ['nav-engineer'])

    async def test_status_table_renders_every_component_with_its_state_word(self):
        expected_words = {'prereqs': 'READY', 'manager': 'ATTENTION', 'access': 'NEEDS AUTH', 'engineer': 'READY',
                          'git': 'ATTENTION', 'capture': 'READY', 'lazydocker': 'NOT INSTALLED'}
        short = {'access': 'VM account', 'capture': 'Wireshark', 'engineer': 'VS Code access'}
        for size in SIZES:
            with self.subTest(size=size):
                async with self.running(size) as (app, pilot):
                    lines = screen_text(app).splitlines()
                    narrow = size[0] < 110
                    for key, label in probes.COMPONENTS:
                        name = short.get(key, label) if narrow else label
                        row = [line for line in lines if re.search(r'│\s*' + re.escape(name) + r'\s', line)
                               and expected_words[key] in line]
                        self.assertTrue(row, f'{name!r} row with {expected_words[key]!r} not found at {size}')

    async def test_unchecked_status_shows_not_checked_words_without_probing(self):
        ctx = self.ctx(status=None)
        ctx.checked_at = time.time()      # no automatic refresh on mount
        async with self.running((120, 40), ctx) as (app, pilot):
            text = screen_text(app)
            self.assertEqual(text.count('NOT CHECKED'), len(probes.COMPONENTS))
            self.assertEqual(self.probe_calls, [])

    async def test_refresh_key_runs_the_patched_probe_only(self):
        async with self.running((120, 40)) as (app, pilot):
            await pilot.press('r')
            await self.wait_for(pilot, lambda: self.probe_calls and not app.ctx.checking, 'patched probes finishing')
            self.assertEqual(len(self.probe_calls), 1)


# --------------------------------------------------------------------------------------------
# 2-3. Footer, review and exit
# --------------------------------------------------------------------------------------------
class ReviewAndExitTests(SlateCase):
    async def test_footer_hints_follow_the_context(self):
        async with self.running((120, 40)) as (app, pilot):
            self.assertIn('refresh', footer_text(app))
            self.assertNotIn('cancel', footer_text(app))
            await pilot.press('enter')
            await pilot.pause()
            self.assertIsInstance(app.screen, slate.ReviewScreen)
            self.assertIn('cancel', footer_text(app))
            self.assertNotIn('refresh', footer_text(app))

    async def test_enter_on_install_opens_review_and_escape_starts_nothing(self):
        ctx = self.ctx()
        async with self.running((120, 40), ctx) as (app, pilot):
            await pilot.press('enter')
            await pilot.pause()
            screen = app.screen
            self.assertIsInstance(screen, slate.ReviewScreen)
            self.assertEqual(screen.action, 'install')
            body = widget_text(screen.query_one('#review-body'))
            for line in ctx.install.plan_lines(ctx.env, ctx.version, ctx.options):
                self.assertIn(line, body)
            steps = [s for s in ctx.install.action_steps('install', ctx.env, ctx.version, ctx.options) if s.visible]
            for step in steps:
                self.assertIn(engine.label_for(step), body)
            self.assertIn('PHASES', body)
            start = screen.query_one('#start', Button)
            self.assertEqual(start.label.plain, 'Start')
            self.assertIs(app.focused, start)
            await pilot.press('escape')
            await pilot.pause()
            self.assertIsInstance(app.screen, slate.Dashboard)
            self.assertIsNone(app.current_run)
            self.assertFalse(app.started_any_run)
            self.assertFalse(self.lock_path.exists(), 'cancelling must not touch the installer lock')

    async def test_review_is_visible_on_screen_at_80x24(self):
        async with self.running((80, 24)) as (app, pilot):
            await pilot.press('enter')
            await pilot.pause()
            text = screen_text(app)
            # At 80 columns the header shortens its subtitle to keep account@host; the plan names the action.
            self.assertIsInstance(app.screen, slate.ReviewScreen)
            self.assertIn('INSTALL OR UPDATE THE MANAGER', text)
            self.assertIn('Start', text)
            self.assertIn('Cancel', text)

    async def test_git_review_opens_without_mutation(self):
        ctx = self.ctx()
        async with self.running((120, 40), ctx) as (app, pilot):
            await self.open_nav(app, pilot, 1)
            screen = app.screen
            self.assertIsInstance(screen, slate.ReviewScreen)
            self.assertEqual(screen.action, 'git')
            body = collapse(widget_text(screen.query_one('#review-body')))
            self.assertIn('Git setup', body)
            self.assertIn('deploy/setup-git.sh', body)
            self.assertIs(app.focused, screen.query_one('#start'))
            await pilot.press('escape')
            await pilot.pause()
            self.assertIsInstance(app.screen, slate.Dashboard)
            self.assertIsNone(app.current_run)
            self.assertFalse(self.lock_path.exists())

    async def test_capture_review_states_the_manager_is_recreated(self):
        async with self.running((120, 40)) as (app, pilot):
            await self.open_nav(app, pilot, 3)
            self.assertEqual(app.screen.action, 'capture')
            body = collapse(widget_text(app.screen.query_one('#review-body'))).lower()
            self.assertIn('manager container is recreated', body)
            self.assertIsNone(re.search(r'(?<!not )interruption-free', body))
            await pilot.press('escape')
            await pilot.pause()
            self.assertIsNone(app.current_run)
            self.assertFalse(self.lock_path.exists())

    async def test_review_cancel_button_by_keyboard_returns_to_dashboard(self):
        async with self.running((120, 40)) as (app, pilot):
            await pilot.press('enter')
            await pilot.pause()
            await self.focus(app, pilot, 'cancel')
            await pilot.press('enter')
            await pilot.pause()
            self.assertIsInstance(app.screen, slate.Dashboard)
            self.assertIsNone(app.current_run)

    async def test_exit_item_quits_with_return_code_zero_when_idle(self):
        async with self.running((120, 40)) as (app, pilot):
            await self.open_nav(app, pilot, 6)
            await pilot.pause()
            self.assertEqual(app.return_code, 0)
            self.assertIsNone(app.summary_lines)
            self.assertIsNone(app.current_run)

    async def test_ctrl_q_quits_immediately_when_idle(self):
        async with self.running((120, 40)) as (app, pilot):
            await pilot.press('ctrl+q')
            await pilot.pause()
            self.assertEqual(app.return_code, 0)


class StartActionTests(SlateCase):
    async def test_start_git_opens_the_git_review_on_mount_without_running_anything(self):
        ctx = self.ctx()
        async with self.running((120, 40), ctx, start='git') as (app, pilot):
            self.assertIsInstance(app.screen, slate.ReviewScreen)
            self.assertEqual(app.screen.action, 'git')
            self.assertEqual([type(screen).__name__ for screen in app.screen_stack[-2:]], ['Dashboard', 'ReviewScreen'])
            self.assertIs(app.focused, app.screen.query_one('#start'))
            self.assertIsNone(app.current_run)
            self.assertFalse(app.started_any_run)
            self.assertFalse(self.lock_path.exists(), 'opening the review takes no lock')
            await pilot.press('escape')
            await pilot.pause()
            self.assertIsInstance(app.screen, slate.Dashboard)

    async def test_start_advanced_opens_settings_from_install_and_then_the_review(self):
        ctx = self.ctx()
        async with self.running((120, 40), ctx, start='advanced') as (app, pilot):
            self.assertIsInstance(app.screen, slate.Dashboard, 'the dashboard is shown first')
            await pilot.press('enter')   # Install / update
            await pilot.pause()
            self.assertIsInstance(app.screen, slate.SettingsScreen)
            self.assertTrue(app.screen.then_review)
            self.assertIsNone(app.current_run)
            await self.focus(app, pilot, 'review')
            await pilot.press('enter')
            await pilot.pause()
            self.assertIsInstance(app.screen, slate.ReviewScreen)
            self.assertEqual(app.screen.action, 'install')
            self.assertTrue(ctx.advanced)
            self.assertFalse(self.lock_path.exists())

    async def test_start_advanced_leaves_the_other_actions_on_their_plain_review(self):
        async with self.running((120, 40), start='advanced') as (app, pilot):
            await self.open_nav(app, pilot, 1)   # Git setup / repair
            self.assertIsInstance(app.screen, slate.ReviewScreen)
            self.assertEqual(app.screen.action, 'git')

    async def test_without_a_start_action_install_opens_the_review_directly(self):
        async with self.running((120, 40)) as (app, pilot):
            await pilot.press('enter')
            await pilot.pause()
            self.assertIsInstance(app.screen, slate.ReviewScreen)
            self.assertEqual(app.screen.action, 'install')
            self.assertIsNone(app.start_action)


# --------------------------------------------------------------------------------------------
# 4 and 6. Advanced settings
# --------------------------------------------------------------------------------------------
class SettingsTests(SlateCase):
    async def open_settings(self, app, pilot):
        # Reaching Settings through the nav list is covered by test_settings_opens_from_nav_*; the other
        # tests open the same screen directly (the way the nav's Enter does) to save five key presses each.
        app.open_action('settings')
        await pilot.pause()
        self.assertIsInstance(app.screen, slate.SettingsScreen)

    async def choose(self, app, pilot, widget_id, index):
        """Select radio button `index` of the RadioSet `widget_id` with arrows and enter."""
        radios = await self.focus(app, pilot, widget_id)
        # Focusing a RadioSet highlights its pressed button; arrows move from there.
        step = index - radios.pressed_index
        await pilot.press(*(['down'] * step if step > 0 else ['up'] * -step))
        await pilot.press('enter')
        await pilot.pause()
        self.assertEqual(radios.pressed_index, index)

    async def review(self, app, pilot):
        await self.focus(app, pilot, 'review')
        await pilot.press('enter')
        await pilot.pause()

    async def type_path(self, app, pilot, value, typed=None):
        """Type `value` into the path field. A long path is pre-filled except its last few
        characters, which are typed (each key press costs time in a headless run)."""
        field = await self.focus(app, pilot, 'env-path')
        typed = len(value) if typed is None else typed
        field.value = value[:len(value) - typed]
        field.cursor_position = len(field.value)
        await pilot.press(*value[len(value) - typed:])
        await pilot.pause()
        self.assertEqual(field.value, value)

    def plan_phase_labels(self, app):
        body = widget_text(app.screen.query_one('#review-body'))
        section = body.split('PHASES', 1)[1].split('KEPT', 1)[0]
        return section

    async def test_settings_opens_from_nav_with_defaults_selected(self):
        async with self.running((120, 40)) as (app, pilot):
            await self.open_nav(app, pilot, 5)
            screen = app.screen
            self.assertIsInstance(screen, slate.SettingsScreen)
            self.assertEqual(screen.query_one('#env-choice', RadioSet).pressed_index, 0)
            self.assertTrue(screen.query_one('#env-path', Input).disabled)
            self.assertEqual(screen.query_one('#operations', RadioSet).pressed_index, 0)
            self.assertEqual(screen.query_one('#engineer', RadioSet).pressed_index, 0)
            self.assertFalse(screen.query_one('#engineer', RadioSet).disabled)
            self.assertTrue(screen.query_one('#repair', Checkbox).value)
            self.assertEqual(screen.query_one('#git-now', RadioSet).pressed_index, 0)
            self.assertIn('esc', footer_text(app))
            await pilot.press('escape')
            await pilot.pause()
            self.assertIsInstance(app.screen, slate.Dashboard)

    async def test_discovery_only_disables_engineer_choice(self):
        async with self.running((120, 40)) as (app, pilot):
            await self.open_settings(app, pilot)
            engineer = app.screen.query_one('#engineer', RadioSet)
            await self.choose(app, pilot, 'operations', 1)
            self.assertTrue(engineer.disabled)
            self.assertIn('Only offered with reviewed lab operations enabled',
                          widget_text(app.screen.query_one('#engineer-help')))
            await self.choose(app, pilot, 'operations', 0)
            self.assertFalse(engineer.disabled)
            self.assertEqual(widget_text(app.screen.query_one('#engineer-help')).strip(), '')

    async def test_operations_two_gives_engineer_two_in_options_and_plan(self):
        ctx = self.ctx()
        async with self.running((120, 40), ctx) as (app, pilot):
            await self.open_settings(app, pilot)
            await self.choose(app, pilot, 'operations', 1)
            await self.review(app, pilot)
            self.assertIsInstance(app.screen, slate.ReviewScreen)
            self.assertEqual(ctx.options.operations, '2')
            self.assertEqual(ctx.options.engineer, '2')
            self.assertTrue(ctx.advanced)
            body = widget_text(app.screen.query_one('#review-body'))
            self.assertIn('Lab operations: existing permissions retained', body)
            self.assertIn('Engineer access: not selected', body)
            self.assertNotIn('VS Code / Containerlab access', self.plan_phase_labels(app))

    async def test_repair_checkbox_off_gives_repair_false(self):
        ctx = self.ctx()
        async with self.running((120, 40), ctx) as (app, pilot):
            await self.open_settings(app, pilot)
            box = await self.focus(app, pilot, 'repair')
            await pilot.press('space')
            await pilot.pause()
            self.assertFalse(box.value)
            await self.review(app, pilot)
            self.assertIsInstance(app.screen, slate.ReviewScreen)
            self.assertIs(ctx.options.repair, False)
            self.assertIn('Installation-media APT repair: not selected', widget_text(app.screen.query_one('#review-body')))

    async def test_git_later_removes_git_phase_from_plan(self):
        ctx = self.ctx()
        async with self.running((120, 40), ctx) as (app, pilot):
            await self.open_settings(app, pilot)
            await self.choose(app, pilot, 'git-now', 1)
            await self.review(app, pilot)
            self.assertIsInstance(app.screen, slate.ReviewScreen)
            self.assertIs(ctx.options.git_now, False)
            keys = [s.key for s in ctx.install.install_steps(ctx.env, ctx.version, ctx.options) if s.visible]
            self.assertNotIn('git', keys)
            labels = self.plan_phase_labels(app)
            self.assertNotIn('Git setup', labels)
            self.assertIn('lazydocker', labels)

    async def test_default_plan_includes_git_phase(self):
        ctx = self.ctx()
        async with self.running((120, 40), ctx) as (app, pilot):
            await pilot.press('enter')
            await pilot.pause()
            self.assertIn('Git setup', self.plan_phase_labels(app))

    async def test_copy_env_with_relative_path_shows_field_error_and_stays(self):
        ctx = self.ctx()
        async with self.running((120, 40), ctx) as (app, pilot):
            await self.open_settings(app, pilot)
            screen = app.screen
            await self.choose(app, pilot, 'env-choice', 1)
            self.assertFalse(screen.query_one('#env-path', Input).disabled)
            await self.type_path(app, pilot, 'rel/x.env')
            await self.review(app, pilot)
            self.assertIs(app.screen, screen)
            self.assertIsInstance(app.screen, slate.SettingsScreen)
            self.assertIn('Choose a regular .env file', widget_text(screen.query_one('#env-error')))
            self.assertTrue(screen.query_one('#env-path', Input).has_class('-invalid'))
            self.assertEqual(app.focused.id, 'env-path')
            self.assertIsNone(ctx.options.env_source)
            self.assertFalse(ctx.advanced)
            self.assertIn('Choose a regular .env file', screen_text(app))

    async def test_copy_env_with_empty_path_asks_for_one(self):
        async with self.running((120, 40)) as (app, pilot):
            await self.open_settings(app, pilot)
            await self.choose(app, pilot, 'env-choice', 1)
            await self.review(app, pilot)
            self.assertIsInstance(app.screen, slate.SettingsScreen)
            self.assertIn('Enter the absolute path', widget_text(app.screen.query_one('#env-error')))

    async def test_copy_env_with_valid_temp_file_reviews_copy_plan(self):
        previous = self.root / 'previous' / '.env'
        previous.parent.mkdir()
        previous.write_text('UI_PORT=9090\nSECRET_THING=do-not-display\n')
        ctx = self.ctx()
        async with self.running((120, 40), ctx) as (app, pilot):
            await self.open_settings(app, pilot)
            await self.choose(app, pilot, 'env-choice', 1)
            await self.type_path(app, pilot, str(previous), typed=5)
            await self.review(app, pilot)
            self.assertIsInstance(app.screen, slate.ReviewScreen)
            body = widget_text(app.screen.query_one('#review-body'))
            self.assertIn(f'copy {previous}', body)
            self.assertNotIn('do-not-display', body)
            self.assertEqual(ctx.options.env_source, previous)
            self.assertIn('Copy previous settings', self.plan_phase_labels(app))
            # The review is still only a plan: nothing started.
            self.assertIsNone(app.current_run)
            self.assertFalse(self.lock_path.exists())

    async def assert_env_rejected(self, ctx, app, pilot, value, message, typed=5):
        await self.open_settings(app, pilot)
        screen = app.screen
        await self.choose(app, pilot, 'env-choice', 1)
        await self.type_path(app, pilot, value, typed=typed)
        await self.review(app, pilot)
        self.assertIs(app.screen, screen, 'the form does not proceed')
        self.assertIsInstance(app.screen, slate.SettingsScreen)
        self.assertIn(message, widget_text(screen.query_one('#env-error')))
        self.assertTrue(screen.query_one('#env-path', Input).has_class('-invalid'))
        self.assertEqual(app.focused.id, 'env-path')
        self.assertIsNone(ctx.options.env_source)
        self.assertFalse(ctx.advanced)
        self.assertIn(message, screen_text(app))
        self.assertIsNone(app.current_run)
        self.assertFalse(self.lock_path.exists())

    async def test_copy_env_with_a_directory_path_shows_the_field_error_and_stays(self):
        folder = self.root / 'old-checkout' / 'clab-backup-ui' / '.env'
        folder.mkdir(parents=True)   # a directory named like the file
        ctx = self.ctx()
        async with self.running((120, 40), ctx) as (app, pilot):
            await self.assert_env_rejected(ctx, app, pilot, str(folder), 'Choose a regular .env file')

    async def test_copy_env_with_a_file_over_64_kib_shows_the_size_error_and_stays(self):
        big = self.root / 'big.env'
        big.write_bytes(b'A=' + b'x' * 65535)   # 65537 bytes: one over 64 KiB
        self.assertEqual(big.stat().st_size, 65537)
        ctx = self.ctx()
        async with self.running((120, 40), ctx) as (app, pilot):
            await self.assert_env_rejected(ctx, app, pilot, str(big), 'no larger than 64 KiB')

    async def test_copy_env_with_exactly_64_kib_is_accepted(self):
        edge = self.root / 'edge.env'
        edge.write_bytes(b'A=' + b'x' * 65534)
        self.assertEqual(edge.stat().st_size, 65536)
        ctx = self.ctx()
        async with self.running((120, 40), ctx) as (app, pilot):
            await self.open_settings(app, pilot)
            await self.choose(app, pilot, 'env-choice', 1)
            await self.type_path(app, pilot, str(edge), typed=5)
            await self.review(app, pilot)
            self.assertIsInstance(app.screen, slate.ReviewScreen)
            self.assertEqual(ctx.options.env_source, edge)

    async def test_copy_env_with_a_symlink_is_refused_even_when_the_target_is_a_small_file(self):
        target = self.root / 'real.env'
        target.write_text('A=1\n')
        link = self.root / 'link.env'
        link.symlink_to(target)
        ctx = self.ctx()
        async with self.running((120, 40), ctx) as (app, pilot):
            await self.assert_env_rejected(ctx, app, pilot, str(link), 'Choose a regular .env file')

    async def test_a_rejected_env_file_can_be_replaced_by_a_valid_one_in_the_same_form(self):
        big = self.root / 'big.env'
        big.write_bytes(b'x' * 70000)
        good = self.root / 'good.env'
        good.write_text('UI_PORT=9090\n')
        ctx = self.ctx()
        async with self.running((120, 40), ctx) as (app, pilot):
            await self.assert_env_rejected(ctx, app, pilot, str(big), 'no larger than 64 KiB')
            await self.type_path(app, pilot, str(good), typed=5)
            await self.review(app, pilot)
            self.assertIsInstance(app.screen, slate.ReviewScreen)
            self.assertEqual(ctx.options.env_source, good)

    async def test_existing_env_hides_copy_controls_and_shows_retained_text(self):
        ctx = self.ctx()
        ctx.env_state = lambda: 'existing'
        async with self.running((120, 40), ctx) as (app, pilot):
            await self.open_settings(app, pilot)
            screen = app.screen
            self.assertEqual(len(screen.query('#env-choice')), 0)
            self.assertEqual(len(screen.query('#env-path')), 0)
            self.assertIn('Existing clab-backup-ui/.env will be retained unchanged.', screen_text(app))
            await self.review(app, pilot)
            self.assertIsInstance(app.screen, slate.ReviewScreen)
            self.assertIsNone(ctx.options.env_source)
            self.assertIn('retain current .env', widget_text(app.screen.query_one('#review-body')))

    async def test_symlinked_env_blocks_the_form_until_fixed(self):
        ctx = self.ctx()
        ctx.env_state = lambda: 'symlink'
        async with self.running((120, 40), ctx) as (app, pilot):
            await self.open_settings(app, pilot)
            self.assertIn('is a symlink', screen_text(app))
            self.assertEqual(len(app.screen.query('#env-path')), 0)

    async def test_standard_defaults_restores_options(self):
        ctx = self.ctx()
        ctx.options = ctx.install.Options(None, '2', '2', False, False)
        ctx.advanced = True
        async with self.running((120, 40), ctx) as (app, pilot):
            await self.open_settings(app, pilot)
            first = app.screen
            self.assertEqual(first.query_one('#operations', RadioSet).pressed_index, 1)
            self.assertFalse(first.query_one('#repair', Checkbox).value)
            self.assertEqual(first.query_one('#git-now', RadioSet).pressed_index, 1)
            await self.focus(app, pilot, 'defaults')
            await pilot.press('enter')
            await pilot.pause()
            self.assertIsNot(app.screen, first)
            self.assertIsInstance(app.screen, slate.SettingsScreen)
            expected = ctx.install.Options()
            for name in ('env_source', 'operations', 'engineer', 'repair', 'git_now'):
                self.assertEqual(getattr(ctx.options, name), getattr(expected, name), name)
            self.assertFalse(ctx.advanced)
            second = app.screen
            self.assertEqual(second.query_one('#operations', RadioSet).pressed_index, 0)
            self.assertTrue(second.query_one('#repair', Checkbox).value)
            self.assertEqual(second.query_one('#git-now', RadioSet).pressed_index, 0)

    async def test_back_button_returns_without_changing_options(self):
        ctx = self.ctx()
        async with self.running((120, 40), ctx) as (app, pilot):
            await self.open_settings(app, pilot)
            await self.choose(app, pilot, 'operations', 1)
            await self.focus(app, pilot, 'back')
            await pilot.press('enter')
            await pilot.pause()
            self.assertIsInstance(app.screen, slate.Dashboard)
            self.assertEqual(ctx.options.operations, '1')
            self.assertFalse(ctx.advanced)

    async def test_single_letter_bindings_do_not_steal_input_text(self):
        async with self.running((120, 40)) as (app, pilot):
            await self.open_settings(app, pilot)
            await self.choose(app, pilot, 'env-choice', 1)
            field = await self.focus(app, pilot, 'env-path')
            await pilot.press('r', 's', 'f', 'o', 'question_mark')
            await pilot.pause()
            self.assertEqual(field.value, 'rsfo?')
            self.assertIsInstance(app.screen, slate.SettingsScreen, 'no dialog or screen change from the letters')
            self.assertIs(app.focused, field)


# --------------------------------------------------------------------------------------------
# 5, 9. Dialogs
# --------------------------------------------------------------------------------------------
class DialogTests(SlateCase):
    async def test_help_dialog_traps_tab_and_restores_focus_on_escape(self):
        async with self.running((120, 40)) as (app, pilot):
            await pilot.press('tab')
            await pilot.pause()
            previous = app.focused
            self.assertEqual(previous.id, 'detail-panel')
            await pilot.press('question_mark')
            await pilot.pause()
            dialog = app.screen
            self.assertIsInstance(dialog, slate.Dialog)
            self.assertIn('Tab / Shift+Tab', screen_text(app))
            for key in ('tab', 'tab', 'shift+tab', 'tab'):
                await pilot.press(key)
                await pilot.pause()
                self.assertIs(app.screen, dialog)
                self.assertIsNotNone(app.focused)
                self.assertIn(dialog, app.focused.ancestors_with_self,
                              f'focus left the modal after {key}: {app.focused!r}')
            await pilot.press('escape')
            await pilot.pause()
            self.assertIsInstance(app.screen, slate.Dashboard)
            self.assertIs(app.focused, previous)

    async def test_help_dialog_from_nav_returns_focus_to_nav_and_f1_works(self):
        async with self.running((120, 40)) as (app, pilot):
            await pilot.press('f1')
            await pilot.pause()
            self.assertIsInstance(app.screen, slate.Dialog)
            await pilot.press('enter')      # the Close button
            await pilot.pause()
            self.assertIsInstance(app.screen, slate.Dashboard)
            self.assertEqual(app.focused.id, 'nav')

    async def test_quit_dialog_offers_only_stop_or_keep_and_keep_closes_it(self):
        ctx = self.ctx()
        async with self.running((120, 40), ctx) as (app, pilot):
            run = scripted_run(ctx, states={'admin': engine.COMPLETED, 'prereqs': engine.RUNNING}, alive=True)
            screen = await self.show_run(app, pilot, run)
            await pilot.press('ctrl+q')
            await pilot.pause()
            dialog = app.screen
            self.assertIsInstance(dialog, slate.Dialog)
            self.assertEqual(dialog.title_text, 'A phase is running')
            buttons = list(dialog.query(Button))
            # Keep running comes first and has the focus: Enter straight after ctrl+q is the safe choice.
            self.assertEqual([b.id for b in buttons], ['dialog-keep', 'dialog-stop'])
            self.assertEqual([b.label.plain for b in buttons],
                             ['Keep running', 'Stop after this phase, then quit'])
            self.assertEqual(app.focused.id, 'dialog-keep')
            text = collapse(screen_text(app))
            self.assertIn('A phase is running', text)
            self.assertNotIn('Quit now', text)
            self.assertNotIn('Quit immediately', text.replace('Quitting immediately', ''))
            # Tab cycles only between the two buttons.
            seen = []
            for _ in range(4):
                seen.append(app.focused.id)
                await pilot.press('tab')
                await pilot.pause()
            self.assertEqual(set(seen), {'dialog-stop', 'dialog-keep'})
            self.assertIs(app.screen, dialog)
            while app.focused.id != 'dialog-keep':
                await pilot.press('tab')
                await pilot.pause()
            await pilot.press('enter')
            await pilot.pause()
            self.assertIs(app.screen, screen)
            self.assertIsNone(app.return_code)
            self.assertFalse(run.stop)
            self.assertFalse(app.pending_quit)
            self.assertTrue(app.is_running)

    async def test_quit_dialog_escape_keeps_running(self):
        ctx = self.ctx()
        async with self.running((120, 40), ctx) as (app, pilot):
            run = scripted_run(ctx, states={'admin': engine.RUNNING}, alive=True)
            screen = await self.show_run(app, pilot, run)
            await pilot.press('ctrl+q')
            await pilot.pause()
            await pilot.press('escape')
            await pilot.pause()
            self.assertIs(app.screen, screen)
            self.assertFalse(run.stop)
            self.assertFalse(app.pending_quit)

    async def test_quit_dialog_stop_sets_run_stop_and_pending_quit(self):
        ctx = self.ctx()
        async with self.running((120, 40), ctx) as (app, pilot):
            run = scripted_run(ctx, states={'admin': engine.COMPLETED, 'prereqs': engine.RUNNING}, alive=True)
            screen = await self.show_run(app, pilot, run)
            await pilot.press('ctrl+q')
            await pilot.pause()
            self.assertEqual(app.focused.id, 'dialog-keep')
            await pilot.press('right')   # the arrow moves along the button row
            await pilot.pause()
            self.assertEqual(app.focused.id, 'dialog-stop')
            await pilot.press('enter')
            await pilot.pause()
            self.assertTrue(run.stop)
            self.assertEqual(run.stop.reason, 'quit requested')
            self.assertTrue(app.pending_quit)
            self.assertIs(app.screen, screen)
            self.assertIsNone(app.return_code, 'the app waits for the active phase before exiting')
            self.assertTrue(any('Quitting after the current phase' in note for note in notifications(app)))

    async def test_ctrl_c_also_asks_before_quitting_a_running_phase(self):
        ctx = self.ctx()
        async with self.running((120, 40), ctx) as (app, pilot):
            run = scripted_run(ctx, states={'admin': engine.RUNNING}, alive=True)
            await self.show_run(app, pilot, run)
            await pilot.press('ctrl+c')
            await pilot.pause()
            self.assertIsInstance(app.screen, slate.Dialog)
            self.assertEqual(app.screen.title_text, 'A phase is running')
            self.assertIsNone(app.return_code)


# --------------------------------------------------------------------------------------------
# 7-8. Run screen and recovery
# --------------------------------------------------------------------------------------------
class RunScreenTests(SlateCase):
    PROGRESS = {'admin': engine.COMPLETED, 'prereqs': engine.RUNNING}

    async def active_run_screen(self, app, pilot, ctx, states=None):
        run = scripted_run(ctx, states=states or self.PROGRESS, alive=True)
        screen = await self.show_run(app, pilot, run)
        return run, screen

    async def test_phase_list_shows_state_words(self):
        ctx = self.ctx()
        async with self.running((120, 40), ctx) as (app, pilot):
            run, screen = await self.active_run_screen(
                app, pilot, ctx, {'admin': engine.COMPLETED, 'prereqs': engine.COMPLETED, 'launch': engine.RUNNING})
            await pilot.pause(0.3)
            lines = screen_text(app).splitlines()
            for phase in run.phases:
                word = {engine.COMPLETED: 'Completed', engine.RUNNING: 'Running', engine.PENDING: 'Pending'}[phase.state]
                # Long labels are cut with an ellipsis in the narrow phase column; match their start.
                row = [line for line in lines if phase.label[:14] in line and word in line and '│' in line]
                self.assertTrue(row, f'{phase.label!r} with {word!r} not on screen')
            self.assertIn('2 of', widget_text(screen.query_one('#run-summary')))
            self.assertIn('Running', widget_text(screen.query_one('#activity')))

    async def test_big_output_keeps_log_bounded_and_notes_hidden_lines(self):
        ctx = self.ctx()
        async with self.running((120, 40), ctx) as (app, pilot):
            run, screen = await self.active_run_screen(app, pilot, ctx)
            screen.add_lines('prereqs', [f'line {number}' for number in range(6000)])
            await pilot.pause(0.3)
            log = screen.query_one('#output', Log)
            self.assertLessEqual(log.line_count, slate.OUTPUT_LINES)
            self.assertGreater(log.line_count, slate.OUTPUT_LINES - 10)
            self.assertEqual(log.lines[-1], 'line 5999')
            self.assertNotIn('line 0', log.lines)
            subtitle = screen.query_one('#output-panel').border_subtitle
            found = re.search(r'earlier (\d+) lines not shown', subtitle)
            self.assertIsNotNone(found, subtitle)
            self.assertGreaterEqual(int(found.group(1)), 1000)
            self.assertLessEqual(len(screen.buffers['prereqs']), core.TAIL_LINES)
            self.assertIn('earlier', screen_text(app))

    async def test_follow_toggle_changes_only_the_view(self):
        ctx = self.ctx()
        async with self.running((120, 40), ctx) as (app, pilot):
            run, screen = await self.active_run_screen(app, pilot, ctx)
            before = (run.stop.reason, bool(run.stop), run.outcome, run.current, run.thread,
                      [(p.key, p.state, p.attempts) for p in run.phases])
            panel = screen.query_one('#output-panel')
            self.assertEqual(panel.border_subtitle, '')
            await pilot.press('f')
            await pilot.pause()
            self.assertFalse(screen.follow)
            self.assertIn('follow paused', panel.border_subtitle)
            self.assertIn('the run continues', panel.border_subtitle)
            self.assertIn('follow paused', screen_text(app))
            self.assertIn('follow', footer_text(app))
            after = (run.stop.reason, bool(run.stop), run.outcome, run.current, run.thread,
                     [(p.key, p.state, p.attempts) for p in run.phases])
            self.assertEqual(before, after)
            await pilot.press('f')
            await pilot.pause()
            self.assertTrue(screen.follow)
            self.assertNotIn('follow paused', panel.border_subtitle)

    async def test_o_toggles_the_phase_panel(self):
        ctx = self.ctx()
        async with self.running((120, 40), ctx) as (app, pilot):
            run, screen = await self.active_run_screen(app, pilot, ctx)
            panel = screen.query_one('#phase-panel')
            self.assertTrue(panel.display)
            await pilot.press('o')
            await pilot.pause()
            self.assertFalse(panel.display)
            self.assertIs(app.screen, screen)
            self.assertFalse(run.stop)
            await pilot.press('o')
            await pilot.pause()
            self.assertTrue(panel.display)

    async def test_escape_while_active_does_not_leave_and_notifies(self):
        ctx = self.ctx()
        async with self.running((120, 40), ctx) as (app, pilot):
            run, screen = await self.active_run_screen(app, pilot, ctx)
            await pilot.press('escape')
            await pilot.pause()
            self.assertIs(app.screen, screen)
            self.assertIsInstance(app.screen, slate.RunScreen)
            self.assertTrue(any('A phase is running' in note for note in notifications(app)), notifications(app))
            self.assertFalse(run.stop, 'escape must not request a stop')
            await pilot.press('enter')
            await pilot.pause()
            self.assertIs(app.screen, screen, 'enter does not open a summary while the run is active')

    async def test_s_requests_stop_after_phase_and_notifies(self):
        ctx = self.ctx()
        async with self.running((120, 40), ctx) as (app, pilot):
            run, screen = await self.active_run_screen(app, pilot, ctx)
            await pilot.press('s')
            await pilot.pause()
            self.assertTrue(run.stop)
            self.assertTrue(any('no later phase starts' in note for note in notifications(app)))
            self.assertIn('Stopping after the current phase', widget_text(screen.query_one('#run-summary')))
            self.assertIs(app.screen, screen)

    async def test_output_is_inert_after_sanitising(self):
        ctx = self.ctx()
        async with self.running((120, 40), ctx) as (app, pilot):
            run, screen = await self.active_run_screen(app, pilot, ctx)
            hostile = ['ok \x1b[31mred\x1b[0m done',
                       'title \x1b]0;owned\x07 [bold]markup[/bold] [link=http://x]l[/link]',
                       '\x1b[2J\x1b[Hscreen wipe attempt [/]',
                       'progress 10%\rprogress 100% [red]fin[/red]']
            cleaned = [core.sanitize.clean_line(line) for line in hostile]
            screen.add_lines('prereqs', cleaned)
            await pilot.pause(0.3)
            log = screen.query_one('#output', Log)
            self.assertFalse(any('\x1b' in line for line in log.lines), log.lines)
            joined = '\n'.join(log.lines)
            self.assertIn('[bold]markup[/bold]', joined)
            self.assertIn('[link=http://x]l[/link]', joined)
            self.assertIn('[red]fin[/red]', joined)
            self.assertIn('red done', joined)
            text = screen_text(app)
            self.assertIn('[bold]markup[/bold]', text)
            self.assertIn('[red]fin[/red]', text)
            self.assertNotIn('\x1b', text)

    async def test_activity_line_is_inert_text(self):
        ctx = self.ctx()
        async with self.running((120, 40), ctx) as (app, pilot):
            run, screen = await self.active_run_screen(app, pilot, ctx)
            screen.add_lines('prereqs', ['[bold red]not styled[/]'])
            await pilot.pause(0.5)       # the activity line mirrors the last output line
            self.assertIn('[bold red]not styled[/]', widget_text(screen.query_one('#activity')))

    # ---- recovery ----
    async def failed_screen(self, app, pilot, ctx, failure, key='prereqs'):
        run = scripted_run(ctx, states={'admin': engine.COMPLETED, key: engine.FAILED}, alive=True)
        run.phase(key).failure = failure
        app.bridge = slate.Bridge(app)
        screen = await self.show_run(app, pilot, run)
        screen.show_recovery(key, failure)
        await self.wait_for(pilot, lambda: app.focused is not None and app.focused.id.startswith('choose-'),
                            'first recovery button focused')
        return run, screen

    def button_labels(self, screen):
        return [b.label.plain for b in screen.query('#recovery-buttons Button')]

    async def test_command_failure_recovery_buttons_focus_and_return(self):
        ctx = self.ctx()
        async with self.running((120, 40), ctx) as (app, pilot):
            failure = engine.Failure('command', 'The step stopped with exit status 1. Completed setup and existing '
                                                'data are retained.', 1)
            run, screen = await self.failed_screen(app, pilot, ctx, failure)
            box = screen.query_one('#recovery')
            self.assertTrue(box.has_class('-shown'))
            self.assertTrue(box.display)
            self.assertEqual(self.button_labels(screen), ['Retry phase', 'Return, keep work', 'Inspect output'])
            buttons = list(screen.query('#recovery-buttons Button'))
            self.assertIs(app.focused, buttons[0])
            self.assertIn('Retry repeats only this phase', widget_text(screen.query_one('#recovery-text')))
            self.assertIn('Kept: Administrator access', widget_text(screen.query_one('#recovery-text')))
            screen_painted = screen_text(app)
            for label in ('Retry phase', 'Return, keep work'):
                self.assertIn(label, screen_painted)
            await pilot.press('right')
            await pilot.pause()
            self.assertIs(app.focused, buttons[1])
            self.assertEqual(buttons[1].id, 'choose-return')
            await pilot.press('left')
            await pilot.pause()
            self.assertIs(app.focused, buttons[0])
            await pilot.press('right')
            await pilot.pause()
            await pilot.press('enter')
            await pilot.pause()
            self.assertEqual(app.bridge.decisions.get_nowait(), engine.RETURN)
            self.assertTrue(app.bridge.decisions.empty())
            self.assertFalse(box.has_class('-shown'))
            self.assertFalse(box.display)
            self.assertIsNone(screen.failure_key)
            self.assertEqual(len(screen.query('#recovery-buttons Button')), 0)

    async def test_retry_button_records_retry_decision(self):
        ctx = self.ctx()
        async with self.running((120, 40), ctx) as (app, pilot):
            failure = engine.Failure('command', 'The step stopped with exit status 1.', 1)
            run, screen = await self.failed_screen(app, pilot, ctx, failure)
            self.assertEqual(app.focused.id, 'choose-retry')
            await pilot.press('enter')
            await pilot.pause()
            self.assertEqual(app.bridge.decisions.get_nowait(), engine.RETRY)

    async def test_failed_phase_output_is_inspectable_without_deciding(self):
        ctx = self.ctx()
        async with self.running((120, 40), ctx) as (app, pilot):
            failure = engine.Failure('command', 'The step stopped with exit status 1.', 1)
            run, screen = await self.failed_screen(app, pilot, ctx, failure)
            screen.add_lines('prereqs', ['apt said: no'])
            # The failed phase's output is on screen below the choices; o widens it.
            self.assertIn('apt said: no', screen.query_one('#output', Log).lines)
            await pilot.press('o')
            await pilot.pause()
            self.assertFalse(screen.query_one('#phase-panel').display)
            self.assertTrue(screen.query_one('#activity-panel').display, 'the choices stay visible')
            self.assertTrue(app.bridge.decisions.empty(), 'inspecting output is not a decision')
            self.assertTrue(screen.query_one('#recovery').has_class('-shown'))

    async def test_lock_failure_shows_holder_copyable_command_and_four_choices(self):
        ctx = self.ctx()
        async with self.running((120, 40), ctx) as (app, pilot):
            holder = ('Package lock held by pid 2230 (unattended-upgr) on /var/lib/dpkg/lock-frontend.\n'
                      'Never stop unattended-upgrades.service, kill this process, or delete the lock file.')
            failure = engine.Failure('lock', 'The package manager (APT/dpkg) is locked by another process.', 100,
                                     choices=(engine.LOCK_WAIT, engine.RETRY, engine.LOCK_CHECK, engine.RETURN),
                                     holder=holder)
            run, screen = await self.failed_screen(app, pilot, ctx, failure)
            self.assertEqual(self.button_labels(screen),
                             ['Wait for lock', 'Retry phase', 'Check again', 'Return, keep work', 'Inspect output'])
            self.assertEqual(app.focused.id, 'choose-lock-wait')
            box = screen.query_one('#recovery')
            self.assertTrue(box.has_class('-lock'))
            self.assertEqual(box.border_title, 'Package lock')
            text = widget_text(screen.query_one('#recovery-text'))
            self.assertIn('Package lock held by pid 2230 (unattended-upgr)', text)
            self.assertIn('locked by another process', text)
            self.assertIn(collapse(ctx.install.RESTART_HINT), collapse(text))
            command = shlex.join(ctx.install.lock_wait_command())
            # The copyable command is pinned outside the scrolling report so it is always visible.
            pinned = widget_text(screen.query_one('#recovery-command'))
            self.assertIn(command, collapse(pinned))
            self.assertRegex(command, r'^sudo python3 \S+/deploy/apt_lock\.py --wait --pause-timers$')
            self.assertNotIn('sudo -n', text + pinned)
            self.assertIn('never stops the upgrade', text)

    async def test_lock_wait_choice_announces_the_wait(self):
        ctx = self.ctx()
        async with self.running((120, 40), ctx) as (app, pilot):
            failure = engine.Failure('lock', 'locked', 100, choices=(engine.LOCK_WAIT, engine.RETRY, engine.LOCK_CHECK,
                                                                    engine.RETURN), holder='held')
            run, screen = await self.failed_screen(app, pilot, ctx, failure)
            await pilot.press('enter')
            await pilot.pause()
            self.assertEqual(app.bridge.decisions.get_nowait(), engine.LOCK_WAIT)
            self.assertIn('Waiting for the package lock; press s to stop waiting.',
                          list(screen.query_one('#output', Log).lines))

    async def test_auth_failure_offers_authenticate_retry(self):
        ctx = self.ctx()
        async with self.running((120, 40), ctx) as (app, pilot):
            failure = engine.Failure('auth', 'sudo needs your password again before this step can run.', 1,
                                     choices=(engine.AUTH_RETRY, engine.RETURN))
            run, screen = await self.failed_screen(app, pilot, ctx, failure)
            self.assertEqual(self.button_labels(screen), ['Authenticate, retry', 'Return, keep work', 'Inspect output'])
            self.assertEqual(app.focused.id, 'choose-auth-retry')
            self.assertIn("sudo's own password prompt", widget_text(screen.query_one('#recovery-text')))
            self.assertEqual(screen.query_one('#recovery').border_title, 'Needs attention')
            await pilot.press('enter')
            await pilot.pause()
            self.assertEqual(app.bridge.decisions.get_nowait(), engine.AUTH_RETRY)

    async def test_recovery_footer_hints_and_escape_keep_the_run(self):
        ctx = self.ctx()
        async with self.running((120, 40), ctx) as (app, pilot):
            failure = engine.Failure('command', 'failed', 1)
            run, screen = await self.failed_screen(app, pilot, ctx, failure)
            self.assertIn('choose', footer_text(app))
            await pilot.press('escape')
            await pilot.pause()
            self.assertIs(app.screen, screen)
            self.assertTrue(screen.query_one('#recovery').has_class('-shown'))

    async def test_post_install_git_failure_offers_retry_finish_without_it_and_return(self):
        ctx = self.ctx()
        async with self.running((120, 40), ctx) as (app, pilot):
            failure = engine.Failure('git', 'Git setup did not complete (exit status 2). The manager and any existing '
                                            'checkout remain available.', 2,
                                     choices=(engine.RETRY, engine.SKIP, engine.RETURN))
            run, screen = await self.failed_screen(app, pilot, ctx, failure, key='git')
            self.assertEqual(self.button_labels(screen), ['Retry phase', 'Finish without it', 'Return, keep work', 'Inspect output'])
            self.assertEqual([b.id for b in screen.query('#recovery-buttons Button')],
                             ['choose-retry', 'choose-skip', 'choose-return', 'inspect'])
            self.assertEqual(app.focused.id, 'choose-retry')
            text = widget_text(screen.query_one('#recovery-text'))
            self.assertIn('Git setup', text)
            self.assertIn('exit status 2', text)
            self.assertEqual(screen.query_one('#recovery').border_title, 'Needs attention')
            painted = screen_text(app)
            for label in ('Retry phase', 'Finish without it', 'Return, keep work'):
                self.assertIn(label, painted)
            await pilot.press('right')
            await pilot.pause()
            self.assertEqual(app.focused.id, 'choose-skip')
            await pilot.press('enter')
            await pilot.pause()
            self.assertEqual(app.bridge.decisions.get_nowait(), engine.SKIP)
            self.assertTrue(app.bridge.decisions.empty())
            self.assertFalse(screen.query_one('#recovery').has_class('-shown'))

    async def test_x_with_no_running_step_process_only_notifies(self):
        ctx = self.ctx()
        async with self.running((120, 40), ctx) as (app, pilot):
            run, screen = await self.active_run_screen(app, pilot, ctx)
            self.assertIsNone(run.process)
            run.interrupt_current = Mock(return_value=True)
            await pilot.press('x')
            await pilot.pause()
            self.assertIs(app.screen, screen, 'no dialog opens')
            self.assertTrue(any('Nothing to interrupt' in note for note in notifications(app)), notifications(app))
            run.interrupt_current.assert_not_called()
            self.assertFalse(run.stop)

    async def test_x_on_a_finished_run_also_says_there_is_nothing_to_interrupt(self):
        ctx = self.ctx()
        async with self.running((120, 40), ctx) as (app, pilot):
            run = full_install_run(ctx)
            screen = await self.show_run(app, pilot, run)
            await pilot.press('x')
            await pilot.pause()
            self.assertIs(app.screen, screen)
            self.assertTrue(any('Nothing to interrupt' in note for note in notifications(app)), notifications(app))

    async def test_x_with_a_running_step_asks_first_and_keep_running_is_the_default(self):
        ctx = self.ctx()
        async with self.running((120, 40), ctx) as (app, pilot):
            run, screen = await self.active_run_screen(app, pilot, ctx)
            run.process = SimpleNamespace(process=SimpleNamespace(pid=0))   # a step process is "running"
            run.interrupt_current = Mock(return_value=True)
            await pilot.press('x')
            await pilot.pause()
            dialog = app.screen
            self.assertIsInstance(dialog, slate.Dialog)
            self.assertEqual(dialog.title_text, 'Interrupt this step?')
            run.interrupt_current.assert_not_called()   # asking is not interrupting
            buttons = list(dialog.query(Button))
            self.assertEqual([b.id for b in buttons], ['dialog-keep', 'dialog-interrupt'])
            self.assertEqual(buttons[0].label.plain, 'Keep running')
            self.assertEqual(app.focused.id, 'dialog-keep')
            body = collapse(widget_text(dialog.query_one('.prose')))
            self.assertIn('VM prerequisites is still running', body)
            self.assertIn('half-configured', body, 'the prereqs phase carries the APT warning')
            await pilot.press('enter')   # straight Enter is the safe choice
            await pilot.pause()
            self.assertIs(app.screen, screen)
            run.interrupt_current.assert_not_called()
            self.assertFalse(any('Ctrl+C sent' in note for note in notifications(app)))

    async def test_x_escape_closes_the_dialog_without_interrupting(self):
        ctx = self.ctx()
        async with self.running((120, 40), ctx) as (app, pilot):
            run, screen = await self.active_run_screen(app, pilot, ctx)
            run.process = SimpleNamespace(process=SimpleNamespace(pid=0))
            run.interrupt_current = Mock(return_value=True)
            await pilot.press('x')
            await pilot.pause()
            await pilot.press('escape')
            await pilot.pause()
            self.assertIs(app.screen, screen)
            run.interrupt_current.assert_not_called()

    async def test_choosing_interrupt_calls_the_runs_interrupt_current_exactly_once(self):
        ctx = self.ctx()
        async with self.running((120, 40), ctx) as (app, pilot):
            run, screen = await self.active_run_screen(app, pilot, ctx)
            run.process = SimpleNamespace(process=SimpleNamespace(pid=0))
            run.interrupt_current = Mock(return_value=True)
            await pilot.press('x')
            await pilot.pause()
            self.assertEqual(app.focused.id, 'dialog-keep')
            await pilot.press('right')
            await pilot.pause()
            self.assertEqual(app.focused.id, 'dialog-interrupt')
            self.assertEqual(app.focused.label.plain, 'Interrupt step')
            await pilot.press('enter')
            await pilot.pause()
            self.assertIs(app.screen, screen)
            run.interrupt_current.assert_called_once_with()
            self.assertTrue(any('Ctrl+C sent to the step.' in note for note in notifications(app)), notifications(app))

    async def test_choosing_interrupt_when_the_step_just_ended_does_not_claim_it_was_sent(self):
        ctx = self.ctx()
        async with self.running((120, 40), ctx) as (app, pilot):
            run, screen = await self.active_run_screen(app, pilot, ctx)
            run.process = SimpleNamespace(process=SimpleNamespace(pid=0))
            run.interrupt_current = Mock(return_value=False)   # it exited while the dialog was open
            await pilot.press('x')
            await pilot.pause()
            await pilot.press('right')
            await pilot.press('enter')
            await pilot.pause()
            run.interrupt_current.assert_called_once_with()
            self.assertFalse(any('Ctrl+C sent' in note for note in notifications(app)), notifications(app))

    async def test_the_interrupt_dialog_for_a_later_phase_has_the_plain_helper_wording(self):
        ctx = self.ctx()
        async with self.running((120, 40), ctx) as (app, pilot):
            run, screen = await self.active_run_screen(
                app, pilot, ctx, {'admin': engine.COMPLETED, 'prereqs': engine.COMPLETED, 'launch': engine.RUNNING})
            run.process = SimpleNamespace(process=SimpleNamespace(pid=0))
            await pilot.press('x')
            await pilot.pause()
            body = collapse(widget_text(app.screen.query_one('.prose')))
            self.assertIn('The helper stops where it is; completed phases and existing data are kept.', body)
            self.assertNotIn('half-configured', body)


# --------------------------------------------------------------------------------------------
# 10. Result screen
# --------------------------------------------------------------------------------------------
class ResultScreenTests(SlateCase):
    def ctx(self, **kwargs):
        # An empty source checkout keeps the manager address on its defaults (no real .env is read).
        source = self.root / 'checkout'
        (source / 'clab-backup-ui').mkdir(parents=True, exist_ok=True)
        return super().ctx(source=source, **kwargs)

    def setUp(self):
        super().setUp()
        patcher = patch.object(slate, 'vm_addresses', lambda: ['192.0.2.10'])
        patcher.start()
        self.addCleanup(patcher.stop)

    def row(self, text, name):
        found = [line for line in text.splitlines() if re.match(r'\s*' + re.escape(name) + r'\s', line)]
        self.assertEqual(len(found), 1, f'{name!r} rows in {text!r}')
        return found[0]

    async def test_partial_install_reports_each_outcome_separately(self):
        ctx = self.ctx()
        async with self.running((160, 50), ctx) as (app, pilot):
            run = full_install_run(ctx, partial=True)
            screen = await self.show_result(app, pilot, run)
            self.assertIsInstance(screen, slate.ResultScreen)
            body = widget_text(screen.query_one('#result'))
            self.assertIn('PARTIAL', body.splitlines()[0])
            self.assertRegex(self.row(body, 'Manager'), r'READY')
            self.assertRegex(self.row(body, 'Git'), r'ATTENTION')
            self.assertRegex(self.row(body, 'lazydocker'), r'SKIPPED')
            self.assertNotRegex(self.row(body, 'Manager'), r'ATTENTION|SKIPPED|FAILED')
            self.assertNotRegex(self.row(body, 'Git'), r'READY')
            self.assertIn('Verified only on this VM', collapse(body))
            self.assertIn('http://192.0.2.10:8081/', body)
            self.assertIn('network unreachable (fixture)', body)
            self.assertIn('Wireshark opens from the map', body)
            # And what is actually painted.
            painted = screen_text(app)
            self.assertIn('PARTIAL', painted)
            self.assertIn('READY', painted)
            self.assertIn('ATTENTION', painted)
            self.assertIn('SKIPPED', painted)
            self.assertIs(app.focused, screen.query_one('#finish'))

    async def test_summary_plain_matches_and_carries_no_markup(self):
        ctx = self.ctx()
        async with self.running((120, 40), ctx) as (app, pilot):
            run = full_install_run(ctx, partial=True)
            app.current_run = run
            lines = app.summary_plain(run)
            self.assertTrue(lines[0].endswith('Install / update: PARTIAL'), lines[0])
            joined = '\n'.join(lines)
            self.assertRegex(joined, r'(?m)^\s+Manager\s+READY\s')
            self.assertRegex(joined, r'(?m)^\s+Git\s+ATTENTION\s')
            self.assertRegex(joined, r'(?m)^\s+lazydocker\s+SKIPPED\s')
            # The plain summary wraps to the terminal with hanging indents; the words are unchanged.
            self.assertIn('Verified only on this VM', collapse(joined))
            self.assertIn('network unreachable (fixture)', collapse(joined))
            self.assertIn('Next steps:', lines)
            for line in lines:
                self.assertNotIn('\x1b', line)
                self.assertIsNone(re.search(r'\[/?[A-Za-z#@ ]*\]', line), line)
            # The rich summary and the plain summary agree on each outcome word.
            screen = await self.show_result(app, pilot, run)
            rich_body = widget_text(screen.query_one('#result'))
            for name, word in (('Manager', 'READY'), ('Git', 'ATTENTION'), ('lazydocker', 'SKIPPED')):
                self.assertIn(word, self.row(rich_body, name))

    async def test_finish_sets_summary_lines_and_exits_zero(self):
        ctx = self.ctx()
        async with self.running((120, 40), ctx) as (app, pilot):
            run = full_install_run(ctx, partial=True)
            screen = await self.show_result(app, pilot, run)
            self.assertIs(app.focused, screen.query_one('#finish'))
            await pilot.press('enter')
            await pilot.pause()
            self.assertEqual(app.summary_lines, app.summary_plain(run))
            self.assertEqual(app.return_code, 0)

    async def test_completed_install_is_ready_without_attention_rows(self):
        ctx = self.ctx()
        async with self.running((160, 50), ctx) as (app, pilot):
            run = full_install_run(ctx, partial=False)
            screen = await self.show_result(app, pilot, run)
            body = widget_text(screen.query_one('#result'))
            self.assertIn('COMPLETED', body.splitlines()[0])
            self.assertRegex(self.row(body, 'Manager'), r'READY')
            self.assertRegex(self.row(body, 'Git'), r'COMPLETED')
            self.assertRegex(self.row(body, 'lazydocker'), r'COMPLETED')
            self.assertNotIn('ATTENTION', body)

    async def test_returned_run_shows_manager_failed_and_no_wireshark_step(self):
        ctx = self.ctx()
        async with self.running((160, 50), ctx) as (app, pilot):
            run = scripted_run(ctx, 'install', states={'admin': engine.COMPLETED, 'prereqs': engine.COMPLETED,
                                                       'launch': engine.FAILED,
                                                       'capture': engine.NOT_STARTED, 'verify': engine.NOT_STARTED,
                                                       'engineer': engine.NOT_STARTED, 'lazydocker': engine.NOT_STARTED,
                                                       'git': engine.NOT_STARTED}, outcome='returned')
            run.phase('launch').failure = engine.Failure('command', 'The launcher stopped with exit status 1.', 1)
            screen = await self.show_result(app, pilot, run)
            body = widget_text(screen.query_one('#result'))
            self.assertIn('STOPPED', body.splitlines()[0])
            self.assertRegex(self.row(body, 'Manager'), r'FAILED')
            self.assertIn('Stopped at Password, helpers, image and manager', body)
            self.assertNotIn('Wireshark opens from the map', body)
            self.assertNotIn('Verified only on this VM', body)
            self.assertIn('Completed phases are kept', body)
            self.assertNotRegex(self.row(body, 'Browser Wireshark'), r'COMPLETED|READY')

    async def test_stopped_run_shows_manager_stopped(self):
        ctx = self.ctx()
        async with self.running((160, 50), ctx) as (app, pilot):
            run = scripted_run(ctx, 'install', states={'admin': engine.COMPLETED, 'prereqs': engine.COMPLETED,
                                                       'launch': engine.STOPPED, 'capture': engine.STOPPED,
                                                       'verify': engine.STOPPED, 'engineer': engine.STOPPED,
                                                       'lazydocker': engine.STOPPED, 'git': engine.STOPPED},
                               outcome='stopped')
            screen = await self.show_result(app, pilot, run)
            body = widget_text(screen.query_one('#result'))
            self.assertRegex(self.row(body, 'Manager'), r'STOPPED')
            self.assertNotIn('Wireshark opens from the map', body)
            self.assertNotIn('READY', body)

    async def test_wireshark_step_appears_only_when_capture_completed(self):
        ctx = self.ctx()
        async with self.running((160, 50), ctx) as (app, pilot):
            run = scripted_run(ctx, 'install', default=engine.NOT_STARTED,
                               states={'admin': engine.COMPLETED, 'prereqs': engine.COMPLETED,
                                       'launch': engine.COMPLETED, 'capture': engine.COMPLETED,
                                       'verify': engine.FAILED}, outcome='failed')
            run.phase('verify').failure = engine.Failure('verify', 'The manager did not answer.', 1)
            body = '\n'.join(app.summary_plain(run))
            self.assertIn('Wireshark opens from the map', body)
            self.assertRegex(body, r'(?m)^\s+Manager\s+FAILED\s')
            run.phase('capture').state = engine.FAILED
            body = '\n'.join(app.summary_plain(run))
            self.assertNotIn('Wireshark opens from the map', body)

    async def test_result_back_to_dashboard_button_is_keyboard_reachable(self):
        ctx = self.ctx()
        async with self.running((120, 40), ctx) as (app, pilot):
            run = full_install_run(ctx, partial=True)
            await self.show_result(app, pilot, run)
            await self.focus(app, pilot, 'dashboard')
            await pilot.press('enter')
            await pilot.pause()
            self.assertIsInstance(app.screen, slate.Dashboard)
            # Returning refreshes the status (read-only probes), which are patched here.
            await self.wait_for(pilot, lambda: not app.ctx.checking, 'patched status refresh')


# --------------------------------------------------------------------------------------------
# 11. Resize
# --------------------------------------------------------------------------------------------
class ResizeTests(SlateCase):
    async def test_live_resize_updates_tiny_and_narrow_classes(self):
        # PRODUCT BUG: deploy/installer_tui/app.py:1215-1216 (SlateOps.on_resize) calls
        # update_size_classes(), which reads `self.size` (app.py:1202). Textual dispatches the subclass
        # handler BEFORE App._on_resize stores the new size (textual/app.py:4345-4354), so `self.size`
        # still holds the PREVIOUS size and the classes lag one resize event behind.
        # Steps: start at 120x40, pilot.resize_terminal(70, 20).
        # Expected: App has class -tiny and the too-small notice shows (mentions 80x24).
        # Actual: classes unchanged (no -tiny, no -narrow) and the notice is not shown; a later
        # resize event or a new screen mounting finally applies the stale previous size.
        async with self.running((120, 40)) as (app, pilot):
            self.assertFalse(app.has_class('-tiny'))
            await pilot.resize_terminal(70, 20)
            await pilot.pause(0.1)
            self.assertTrue(app.has_class('-tiny'))
            notice = app.screen.query_one('#too-small', Static)
            self.assertIn('80×24', widget_text(notice))
            self.assertIn('70×20', widget_text(notice))
            self.assertTrue(notice.display)
            await pilot.resize_terminal(100, 30)
            await pilot.pause(0.3)
            self.assertFalse(app.has_class('-tiny'))
            self.assertTrue(app.has_class('-narrow'))
            self.assertFalse(app.screen.query_one('#too-small', Static).display)

    async def test_live_resize_height_alone_makes_the_terminal_tiny(self):
        # PRODUCT BUG: same cause as test_live_resize_updates_tiny_and_narrow_classes (stale `self.size`
        # in SlateOps.update_size_classes during on_resize, app.py:1202/1215).
        async with self.running((120, 40)) as (app, pilot):
            await pilot.resize_terminal(120, 20)
            await pilot.pause(0.3)
            self.assertTrue(app.has_class('-tiny'))

    async def test_tiny_terminal_shows_the_too_small_notice(self):
        async with self.running((70, 20)) as (app, pilot):
            self.assertTrue(app.has_class('-tiny'))
            notice = app.screen.query_one('#too-small', Static)
            self.assertIn('80×24', widget_text(notice))
            self.assertIn('70×20', widget_text(notice))
            self.assertTrue(notice.display)
            self.assertIn('80×24', screen_text(app))
            self.assertIn('ctrl+q quits', screen_text(app))
            await pilot.press('ctrl+q')
            await pilot.pause()
            self.assertEqual(app.return_code, 0)

    async def test_size_classes_at_each_starting_size(self):
        expected = {(79, 30): {'-tiny', '-narrow', '-short'}, (100, 30): {'-narrow', '-short'},
                    (120, 40): set(), (160, 50): {'-wide'}, (120, 23): {'-tiny', '-short'}}
        for size, classes in expected.items():
            with self.subTest(size=size):
                async with self.running(size) as (app, pilot):
                    found = {name for name in ('-tiny', '-narrow', '-short', '-wide') if app.has_class(name)}
                    self.assertEqual(found, classes)

    async def test_classes_are_applied_when_a_new_screen_mounts_after_a_resize(self):
        # Whatever the live-resize behaviour, opening the next screen re-reads the real size.
        async with self.running((120, 40)) as (app, pilot):
            await pilot.resize_terminal(100, 30)
            await pilot.pause(0.3)
            await pilot.press('enter')      # review screen mounts
            await pilot.pause(0.3)
            self.assertTrue(app.has_class('-narrow'))
            self.assertFalse(app.has_class('-tiny'))


# --------------------------------------------------------------------------------------------
# 12. Integration with a fake install module (real engine.Run thread, harmless `sh` phases)
# --------------------------------------------------------------------------------------------
class FakeRunTests(SlateCase):
    def fake_ctx(self, steps):
        ctx = self.ctx()
        source = self.root / 'fake-source'
        source.mkdir(exist_ok=True)
        fake = FakeInstall(ctx.install, source, steps)
        ctx.install = fake
        ctx.source = source
        return ctx, fake

    async def test_capture_run_streams_output_then_shows_the_result_automatically(self):
        real = self.ctx().install
        steps = {'capture': [sh_step(real, 'capture', 'Browser Wireshark capture stack',
                                     'echo first line; echo second line; echo third line; sleep 0.6')]}
        ctx, fake = self.fake_ctx(steps)
        async with self.running((120, 40), ctx) as (app, pilot):
            app.start_run('capture')
            await pilot.pause()
            run = app.current_run
            self.assertIsInstance(run, engine.Run)
            self.assertIs(run.install, fake)
            self.assertTrue(run.lock is not None and run.lock.held, 'a mutating run holds the installer lock')
            self.assertTrue(self.lock_path.exists())
            screen = app.screen
            self.assertIsInstance(screen, slate.RunScreen)
            log = screen.query_one('#output', Log)
            await self.wait_for(pilot, lambda: {'first line', 'second line', 'third line'} <= set(log.lines),
                                'three output lines on the run screen')
            self.assertIn('first line', screen_text(app))
            self.assertTrue(run.active)
            await self.wait_for(pilot, lambda: self.result_ready(app), 'result screen')
            self.assertEqual(run.outcome, 'completed')
            body = widget_text(app.screen.query_one('#result'))
            self.assertIn('COMPLETED', body)
            self.assertIn('Browser Wireshark', body)
            self.assertIn('Wireshark opens from the map', body)
            # The lock is released and the run record written with metadata only.
            probe = core.InstallerLock(self.lock_path).acquire()
            probe.release()
            record = core.read_run_record(ctx.env)
            self.assertEqual(record['outcome'], 'completed')
            self.assertEqual(record['action'], 'capture')
            self.assertNotIn('first line', repr(record))
            await pilot.press('enter')
            await pilot.pause()
            self.assertEqual(app.return_code, 0)
            self.assertIn('Browser Wireshark', '\n'.join(app.summary_lines))

    async def test_failed_phase_shows_recovery_and_retry_reruns_only_that_phase(self):
        real = self.ctx().install
        first_marker, second_marker = self.root / 'first.count', self.root / 'second.count'
        steps = {'capture': [
            sh_step(real, 'prereqs', 'VM prerequisites', 'echo x >> "$1"; echo prerequisites ran', str(first_marker)),
            sh_step(real, 'capture', 'Browser Wireshark capture stack',
                    'echo x >> "$1"; echo "attempt $(wc -l < "$1")"; [ "$(wc -l < "$1")" -ge 2 ]', str(second_marker)),
        ]}
        ctx, fake = self.fake_ctx(steps)

        def attempts(path):
            return len(path.read_text().splitlines()) if path.exists() else 0
        async with self.running((120, 40), ctx) as (app, pilot):
            app.start_run('capture')
            await pilot.pause()
            run = app.current_run
            screen = app.screen
            self.assertIsInstance(screen, slate.RunScreen)
            box = screen.query_one('#recovery')
            await self.wait_for(pilot, lambda: box.has_class('-shown'), 'recovery panel')
            await self.wait_for(pilot, lambda: app.focused is not None and app.focused.id == 'choose-retry',
                                'Retry phase focused')
            self.assertEqual(run.phase('prereqs').state, engine.COMPLETED)
            self.assertEqual(run.phase('capture').state, engine.FAILED)
            self.assertEqual((attempts(first_marker), attempts(second_marker)), (1, 1))
            self.assertEqual(self.button_labels(screen), ['Retry phase', 'Return, keep work', 'Inspect output'])
            self.assertIn('exit status 1', widget_text(screen.query_one('#recovery-text')))
            self.assertIn('Kept: VM prerequisites', widget_text(screen.query_one('#recovery-text')))
            self.assertIn('attempt 1', screen.query_one('#output', Log).lines)
            await pilot.press('enter')
            await self.wait_for(pilot, lambda: self.result_ready(app), 'result after retry')
            self.assertEqual((attempts(first_marker), attempts(second_marker)), (1, 2),
                             'only the failed phase ran again')
            self.assertEqual(run.phase('capture').attempts, 2)
            self.assertEqual(run.phase('prereqs').attempts, 1)
            self.assertEqual(run.outcome, 'completed')
            self.assertFalse(box.has_class('-shown'))
            self.assertIn('attempt 2', screen.query_one('#output', Log).lines)
            self.assertIn('COMPLETED', widget_text(app.screen.query_one('#result')))

    def button_labels(self, screen):
        return [b.label.plain for b in screen.query('#recovery-buttons Button')]

    async def test_failed_phase_return_keeps_work_and_reports_stopped_manager(self):
        real = self.ctx().install
        steps = {'install': [
            sh_step(real, 'admin', 'Administrator access', 'echo admin ok'),
            sh_step(real, 'prereqs', 'VM prerequisites', 'echo broken; exit 3'),
            sh_step(real, 'launch', 'Password, helpers, image and manager', 'echo must not run; exit 9'),
        ]}
        ctx, fake = self.fake_ctx(steps)
        async with self.running((120, 40), ctx) as (app, pilot):
            app.start_run('install')
            await pilot.pause()
            run = app.current_run
            screen = app.screen
            box = screen.query_one('#recovery')
            await self.wait_for(pilot, lambda: box.has_class('-shown'), 'recovery panel')
            await self.wait_for(pilot, lambda: app.focused is not None and app.focused.id == 'choose-retry', 'focus')
            await pilot.press('right')
            await pilot.pause()
            self.assertEqual(app.focused.id, 'choose-return')
            await pilot.press('enter')
            await self.wait_for(pilot, lambda: self.result_ready(app), 'result after return')
            self.assertEqual(run.outcome, 'returned')
            self.assertEqual(run.phase('admin').state, engine.COMPLETED)
            self.assertEqual(run.phase('prereqs').state, engine.FAILED)
            self.assertEqual(run.phase('launch').state, engine.NOT_STARTED)
            self.assertNotIn('must not run', list(screen.query_one('#output', Log).lines))
            body = widget_text(app.screen.query_one('#result'))
            self.assertRegex(body, r'Manager\s+FAILED')
            self.assertIn('Stopped at VM prerequisites', body)
            await pilot.press('enter')
            await pilot.pause()
            self.assertEqual(app.return_code, 0)

    async def test_busy_installer_lock_blocks_start_with_a_dialog(self):
        real = self.ctx().install
        steps = {'capture': [sh_step(real, 'capture', 'Browser Wireshark capture stack', 'echo never')]}
        ctx, fake = self.fake_ctx(steps)
        other = core.InstallerLock(self.lock_path).acquire()
        self.addCleanup(other.release)
        async with self.running((120, 40), ctx) as (app, pilot):
            app.start_run('capture')
            await pilot.pause()
            self.assertIsNone(app.current_run)
            self.assertIsInstance(app.screen, slate.Dialog)
            self.assertEqual(app.screen.title_text, 'Installer busy')
            await pilot.press('enter')
            await pilot.pause()
            self.assertIsInstance(app.screen, slate.Dashboard)


# --------------------------------------------------------------------------------------------
# Exit status of a run (the code the process returns for a finished action)
# --------------------------------------------------------------------------------------------
class ExitStatusTests(SlateCase):
    def setUp(self):
        super().setUp()
        self.ctx_ = self.ctx()
        self.app = fixture.make_app(self.ctx_)

    def health_run(self, report='absent', outcome=None):
        run = engine.HealthRun(self.ctx_.install, self.ctx_.env, self.ctx_.version)
        if report != 'absent':
            run.report = report
        run.outcome = outcome
        return run

    def action_run(self, action, outcome, code=None):
        run = engine.Run(self.ctx_.install, action, self.ctx_.env, self.ctx_.version, options=self.ctx_.options)
        run.outcome = outcome
        if code is not None:
            run.phase(action).code = code
        return run

    def test_no_run_is_zero(self):
        self.assertEqual(self.app.exit_status(None), 0)

    def test_health_report_exit_codes_pass_through(self):
        for code in (0, 1, 2):
            with self.subTest(exit_code=code):
                run = self.health_run({'schema': 'clab-manager-health-v1', 'exit_code': code},
                                      'completed' if code == 0 else 'partial')
                self.assertEqual(self.app.exit_status(run), code)

    def test_health_without_a_usable_report_is_one(self):
        for label, report in (('missing', None), ('never set', 'absent'), ('empty', {}), ('no code', {'counts': {}}),
                              ('text code', {'exit_code': '2'}), ('null code', {'exit_code': None})):
            with self.subTest(label):
                self.assertEqual(self.app.exit_status(self.health_run(report, 'failed')), 1)

    def test_git_action_returns_the_git_phase_status(self):
        for code, outcome in ((0, 'completed'), (1, 'returned'), (2, 'returned'), (130, 'returned'), (75, 'returned')):
            with self.subTest(code=code):
                self.assertEqual(self.app.exit_status(self.action_run('git', outcome, code)), code)

    def test_git_action_without_a_status_follows_the_outcome(self):
        self.assertEqual(self.app.exit_status(self.action_run('git', 'completed')), 0)
        for outcome in ('returned', 'failed', 'stopped', 'interrupted'):
            with self.subTest(outcome=outcome):
                self.assertEqual(self.app.exit_status(self.action_run('git', outcome)), 1)

    def test_install_outcomes_map_to_zero_or_one(self):
        expected = {'completed': 0, 'partial': 0, 'returned': 0, 'stopped': 0, 'failed': 1, 'interrupted': 1, None: 1}
        for outcome, code in expected.items():
            with self.subTest(outcome=outcome):
                self.assertEqual(self.app.exit_status(self.action_run('install', outcome)), code)

    def test_other_actions_use_the_outcome_mapping(self):
        for action in ('engineer', 'capture'):
            for outcome, code in (('completed', 0), ('returned', 0), ('failed', 1), ('interrupted', 1)):
                with self.subTest(action=action, outcome=outcome):
                    self.assertEqual(self.app.exit_status(self.action_run(action, outcome, code=7)), code,
                                     'a helper status is not the installer status outside the git action')


# --------------------------------------------------------------------------------------------
# main(): the process return code
# --------------------------------------------------------------------------------------------
class FakeTTY(io.StringIO):
    def __init__(self, tty=True):
        super().__init__()
        self.tty = tty

    def isatty(self):
        return self.tty


class FakeMainRun:
    """What main() reads from a run that is still active when the screen ends."""

    def __init__(self, outcome='returned'):
        self.joined = False
        self.disconnected = []
        self.hangup = core.Signal()   # falsy until the terminal is lost
        self.outcome = outcome
        self._active = True
        self.thread = SimpleNamespace(join=self.join)

    @property
    def active(self):
        return self._active

    def join(self):
        self.joined = True
        self._active = False

    def disconnect(self, reason):
        self.disconnected.append(reason)
        self.hangup.set(reason)


class MainReturnCodeTests(unittest.TestCase):
    """slate.main() with a scripted SlateOps: no terminal, no Textual app and no real install module."""

    def setUp(self):
        self.ctx = fixture.context()
        self.apps = []
        outer = self

        class FakeSlate:
            behavior = None

            def __init__(self, ctx, start_action=None, ansi_color=None):
                self.ctx = ctx
                self.start_action = start_action
                self.ansi_color = ansi_color
                self.current_run = None
                self.bridge = SimpleNamespace(alive=True, decisions=__import__('queue').Queue())
                self.summary_lines = None
                self.terminal_lost = False
                self.started_any_run = False
                self.pending_quit = False
                self.return_code = None
                outer.apps.append(self)

            def run(self):
                type(self).behavior(self)

            def summary_plain(self, run):
                return ['SUMMARY LINE']

        self.Fake = FakeSlate
        patches = [
            patch.object(slate, 'SlateOps', FakeSlate),
            patch.object(slate, 'load_install', lambda: self.ctx.install),
            patch.object(slate, 'Context', lambda install, look: self.ctx),
            patch.object(sys, '__stdin__', FakeTTY()),
            patch.object(sys, '__stdout__', FakeTTY()),
            patch.object(sys, '__stderr__', FakeTTY()),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

    def main(self, behavior, argv=()):
        self.Fake.behavior = staticmethod(behavior)
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = slate.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_a_crash_before_any_run_is_75_and_says_nothing_was_changed(self):
        def behavior(app):
            raise RuntimeError('screen blew up')
        code, out, err = self.main(behavior)
        self.assertEqual(code, 75)
        self.assertEqual(slate.UNAVAILABLE_EXIT, 75)
        self.assertIn('could not continue (RuntimeError: screen blew up)', err)
        self.assertIn('Nothing was changed', err)
        self.assertNotIn('stopped unexpectedly', out)

    def test_a_crash_after_a_run_started_is_1_and_the_plain_installer_hint_is_printed(self):
        def behavior(app):
            app.started_any_run = True
            raise RuntimeError('boom')
        code, out, err = self.main(behavior)
        self.assertEqual(code, 1)
        self.assertIn('The installer screen stopped unexpectedly (RuntimeError)', out)
        self.assertIn('rerun bash deploy/install.sh', out)
        self.assertNotIn('Nothing was changed', err)

    def test_return_code_75_after_a_run_is_reported_as_1(self):
        def behavior(app):
            app.started_any_run = True
            app.return_code = 75   # a helper's own 75 must not read as "stopped before changing anything"
        code, out, err = self.main(behavior)
        self.assertEqual(code, 1)

    def test_return_code_75_without_a_run_stays_75(self):
        def behavior(app):
            app.return_code = 75
        self.assertEqual(self.main(behavior)[0], 75)

    def test_no_return_code_means_ctrl_c_130(self):
        def behavior(app):
            app.return_code = None
        self.assertEqual(self.main(behavior)[0], 130)
        def after_run(app):
            app.started_any_run = True
        self.assertEqual(self.main(after_run)[0], 130)

    def test_ordinary_return_codes_pass_through(self):
        for value in (0, 1, 2, 3):
            with self.subTest(code=value):
                def behavior(app, value=value):
                    app.return_code = value
                    app.started_any_run = True
                self.assertEqual(self.main(behavior)[0], value)

    def test_a_lost_terminal_is_1_even_with_a_return_code(self):
        def behavior(app):
            app.terminal_lost = True
            app.started_any_run = True
            app.return_code = 0
        self.assertEqual(self.main(behavior)[0], 1)

    def test_the_summary_is_printed_after_the_screen_closes(self):
        def behavior(app):
            app.return_code = 0
            app.summary_lines = ['Containerlab Node Manager setup: COMPLETED', '  Manager  COMPLETED']
        code, out, err = self.main(behavior)
        self.assertEqual(code, 0)
        self.assertIn('Containerlab Node Manager setup: COMPLETED\n  Manager  COMPLETED', out)

    def test_flags_choose_the_start_action(self):
        def behavior(app):
            app.return_code = 0
        for argv, expected in (((), None), (('--git',), 'git'), (('--advanced',), 'advanced'), (('--git', '--advanced'), 'git')):
            with self.subTest(argv=argv):
                self.main(behavior, argv)
                self.assertEqual(self.apps[-1].start_action, expected)

    def test_without_a_terminal_on_every_stream_it_is_75_and_no_app_is_built(self):
        for name in ('__stdin__', '__stdout__', '__stderr__'):
            with self.subTest(stream=name), patch.object(sys, name, FakeTTY(tty=False)):
                before = len(self.apps)
                code, out, err = self.main(lambda app: None)
                self.assertEqual(code, 75)
                self.assertIn('needs an interactive terminal', err)
                self.assertEqual(len(self.apps), before)

    def test_a_run_still_active_when_the_screen_crashes_is_finished_not_abandoned(self):
        holder = {}

        def behavior(app):
            app.started_any_run = True
            holder['run'] = app.current_run = FakeMainRun()
            raise RuntimeError('boom')
        before = signal.getsignal(signal.SIGINT)
        code, out, err = self.main(behavior)
        run = holder['run']
        self.assertEqual(code, 1)
        self.assertTrue(run.joined, 'main waits for the active phase to finish')
        self.assertEqual(run.disconnected, ['the screen stopped unexpectedly'])
        self.assertFalse(self.apps[-1].bridge.alive)
        self.assertEqual(self.apps[-1].bridge.decisions.get_nowait(), engine.RETURN)
        self.assertIn('Finishing the current phase safely', out)
        self.assertIs(signal.getsignal(signal.SIGINT), before, 'the SIGINT guard is restored')

    def test_a_run_still_active_after_a_quit_is_finished_and_the_summary_printed(self):
        holder = {}

        def behavior(app):
            app.started_any_run = True
            app.pending_quit = True
            holder['run'] = app.current_run = FakeMainRun()
            app.return_code = 0
        code, out, err = self.main(behavior)
        run = holder['run']
        self.assertEqual(code, 0)
        self.assertTrue(run.joined)
        self.assertEqual(run.disconnected, ['quit after the current phase'])
        self.assertIn('SUMMARY LINE', out, 'a finished run is summarised on the normal terminal')


# --------------------------------------------------------------------------------------------
# Terminal handoff when the driver cannot suspend (headless)
# --------------------------------------------------------------------------------------------
class HandoffWithoutSuspendTests(SlateCase):
    async def test_handoff_returns_none_and_never_calls_the_work(self):
        work = Mock(return_value=0)
        async with self.running((120, 40)) as (app, pilot):
            self.assertFalse(getattr(app._driver, 'can_suspend', False), 'a headless driver cannot suspend')
            before = signal.getsignal(signal.SIGINT)
            result = app.handoff('Administrator access', 'sudo asks for your password.', work)
            self.assertIsNone(result)
            work.assert_not_called()
            self.assertIs(signal.getsignal(signal.SIGINT), before, 'the SIGINT guard is only installed when suspending')
            self.assertIsInstance(app.screen, slate.Dashboard)

    async def test_handoff_without_a_driver_returns_none(self):
        work = Mock(return_value=0)
        app = fixture.make_app(self.ctx())
        self.assertIsNone(app._driver)
        self.assertIsNone(app.handoff('Git setup', 'notice', work))
        work.assert_not_called()

    async def test_the_run_threads_bridge_handoff_reports_none_without_running_the_work(self):
        work = Mock(return_value=0)
        async with self.running((120, 40)) as (app, pilot):
            bridge = slate.Bridge(app)
            # The bridge blocks its caller until the screen has answered, so it is called off the loop
            # thread, exactly as the run thread calls it.
            result = await asyncio.wait_for(asyncio.to_thread(bridge.handoff, 'Git setup', 'notice', work), 20)
            self.assertIsNone(result)
            work.assert_not_called()
            bridge.alive = False
            self.assertIsNone(await asyncio.to_thread(bridge.handoff, 'Git setup', 'notice', work))
            work.assert_not_called()

    async def test_an_engine_run_treats_a_failed_git_handoff_as_a_recoverable_handoff_failure(self):
        ctx = self.ctx()
        async with self.running((120, 40), ctx) as (app, pilot):
            bridge = slate.Bridge(app)
            run = engine.Run(ctx.install, 'git', ctx.env, ctx.version)
            step = run.steps[0]
            phase = run.phases[0]
            run.bridge = bridge
            with patch.object(ctx.install, 'git_setup', Mock(return_value=0)) as git_setup:
                failure = await asyncio.wait_for(asyncio.to_thread(run._execute, step, phase), 20)
            git_setup.assert_not_called()
            self.assertEqual(failure.kind, 'handoff')
            self.assertEqual(failure.choices, (engine.RETRY, engine.RETURN))
            self.assertIsNone(phase.code)


if __name__ == '__main__':
    unittest.main()
