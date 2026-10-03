"""Slate Ops: the full-screen Containerlab Node Manager installer (Textual).

A presentation layer over install-manager.py. The plan, every helper command and its
order come from that module (`action_steps`, `plan_lines`, `Options`), exactly as the
plain menu uses them; engine.py runs the phases. Nothing here installs, repairs or
authenticates while the dashboard is merely being browsed: the status probes are
read-only and bounded, and a mutating action starts only from its review screen's
Start button.
"""
import importlib.util
import os
from pathlib import Path
import queue
import signal
import socket
import sys
import textwrap
import time

from rich.console import Group
from rich.style import Style
from rich.table import Table
from rich.text import Text
from textual import events, on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.theme import Theme
from textual.widgets import Button, Checkbox, Input, Label, ListItem, ListView, Log, RadioButton, RadioSet, Static

from . import core, engine, probes, theme
from .theme import T

DEPLOY = Path(__file__).resolve().parents[1]
SOURCE = DEPLOY.parent
UNAVAILABLE_EXIT = 75
OUTPUT_LINES = 5000

ACTIONS = [
    ('install', 'Install / update'),
    ('git', 'Git setup / repair'),
    ('engineer', 'VS Code / Containerlab access'),
    ('capture', 'Browser Wireshark stack'),
    ('health', 'Check installation'),
    ('settings', 'Advanced settings'),
    ('exit', 'Exit'),
]
SHORT_LABELS = {'engineer': 'VS Code / clab access', 'capture': 'Browser Wireshark'}
ACTION_LABELS = dict(ACTIONS)
OUTCOME_WORDS = {'completed': 'Completed', 'partial': 'Partial', 'failed': 'Failed', 'stopped': 'Stopped',
                 'returned': 'Stopped', 'interrupted': 'Stopped'}


def load_install():
    spec = importlib.util.spec_from_file_location('install_manager', DEPLOY / 'install-manager.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def middle(text, width):
    """Shorten a long path or hostname in the middle so both ends stay readable."""
    text = str(text)
    if width < 8 or len(text) <= width:
        return text
    keep = width - 1
    return text[:keep // 2] + '…' + text[-(keep - keep // 2):]


def clock(seconds):
    if seconds is None:
        return ''
    seconds = int(seconds)
    return f'{seconds // 3600}:{seconds // 60 % 60:02d}:{seconds % 60:02d}' if seconds >= 3600 else f'{seconds // 60:02d}:{seconds % 60:02d}'


def ago(timestamp):
    if not timestamp:
        return 'not checked yet'
    seconds = int(time.time() - timestamp)
    if seconds < 60:
        return 'just now'
    if seconds < 3600:
        return f'{seconds // 60} min ago'
    return f'{seconds // 3600} h ago'


class Context:
    """What every screen needs: the shared installer module, the account and this checkout."""

    def __init__(self, install, look):
        import pwd
        self.install = install
        self.look = look
        self.account = pwd.getpwuid(os.geteuid())
        self.env = install.environment(self.account)
        self.version = install.source_version()
        self.host = socket.gethostname()
        self.source = install.SOURCE
        self.options = install.Options()
        self.advanced = False
        self.status = probes.placeholder()
        self.checked_at = None
        self.checking = False
        self.last_run = core.read_run_record(self.env)
        self.health = None

    def env_state(self):
        """('existing'|'missing'|'symlink'): the source checkout's .env, which decides the bind/port question."""
        target = Path(self.source) / 'clab-backup-ui/.env'
        if target.is_symlink():
            return 'symlink'
        return 'existing' if target.exists() else 'missing'


# --------------------------------------------------------------------------------------------
# Chrome: header and contextual footer
# --------------------------------------------------------------------------------------------
class Header(Horizontal):
    def __init__(self, ctx, subtitle=''):
        super().__init__(id='header')
        self.ctx = ctx
        self.subtitle = subtitle

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(id='header-title')
            yield Static(id='header-meta')

    def on_mount(self):
        self.refresh_text()

    def on_resize(self, event):
        self.refresh_text()

    def refresh_text(self):
        look, ctx = self.ctx.look, self.ctx
        width = max(self.size.width - 4, 40)
        right = f'{ctx.account.pw_name}@{middle(ctx.host, 24)}'

        def build(product, subtitle):
            title = Text(no_wrap=True, overflow='ellipsis')
            title.append('SLATE OPS', style=Style(color=None if look.no_color else T['slate-accent'], bold=True))
            title.append(f' {look.glyph("sep")} ', style=Style(color=None if look.no_color else T['slate-border']))
            title.append(product, style=Style(color=None if look.no_color else T['slate-text'], bold=True))
            if subtitle:
                title.append(f' {look.glyph("sep")} ', style=Style(color=None if look.no_color else T['slate-border']))
                title.append(subtitle, style=Style(color=None if look.no_color else T['slate-muted']))
            return title
        # Account and host always stay visible: shorten the product name, then the subtitle, first.
        for product, subtitle in (('Containerlab Node Manager setup', self.subtitle), ('Node Manager setup', self.subtitle),
                                  ('Node Manager setup', middle(self.subtitle, 18)), ('setup', '')):
            title = build(product, subtitle)
            if width - title.cell_len - len(right) >= 2:
                break
        pad = width - title.cell_len - len(right)
        title.append(' ' * max(pad, 1))
        title.append(right, style=Style(color=None if look.no_color else T['slate-muted']))
        self.query_one('#header-title', Static).update(title)
        running = ctx.status.get('manager')
        if running is not None and running.value:
            running_text = f'  ·  manager {running.value} running'
        elif running is not None and running.state not in (probes.NOT_CHECKED, probes.CHECKING, probes.UNAVAILABLE,
                                                            probes.NEEDS_AUTH):
            running_text = '  ·  manager not running'
        else:
            running_text = ''
        meta = Text(no_wrap=True, overflow='ellipsis', style=Style(color=None if look.no_color else T['slate-dim']))
        fixed = f'source {ctx.version}{running_text}  ·  checkout '
        meta.append(fixed)
        meta.append(middle(str(ctx.source), max(width - len(fixed), 12)))
        self.query_one('#header-meta', Static).update(meta)


class Footer(Static):
    def __init__(self):
        super().__init__(id='footer')

    def show(self, hints, look):
        text = Text(no_wrap=True, overflow='ellipsis')
        gap = '   ' if self.app.size.width >= 100 else ' '
        for index, (key, label) in enumerate(hints):
            if index:
                text.append(gap)
            text.append(f' {key} ', style=Style(color=T['slate-bg'] if not look.no_color else None,
                                               bgcolor=None if look.no_color else T['slate-dim'], bold=True,
                                               reverse=look.no_color))
            text.append(' ' + label, style=Style(color=None if look.no_color else T['slate-muted']))
        self.update(text)


class Chrome(Screen):
    """A screen with the painted header band, a body and the contextual key footer."""

    subtitle = ''
    BINDINGS = [Binding('left', 'button_left', show=False), Binding('right', 'button_right', show=False)]

    def action_button_left(self):
        # In a row of buttons the arrow keys move between them, like Tab and Shift+Tab.
        if isinstance(self.focused, Button):
            self.focus_previous(Button)

    def action_button_right(self):
        if isinstance(self.focused, Button):
            self.focus_next(Button)

    @property
    def ctx(self):
        return self.app.ctx

    def chrome(self):
        yield Header(self.ctx, self.subtitle)
        yield Footer()
        yield Static('', id='too-small')

    def hints(self):
        return [('?', 'help'), ('ctrl+q', 'quit')]

    def update_footer(self):
        try:
            self.query_one(Footer).show(self.hints(), self.ctx.look)
        except Exception:
            pass

    def on_mount(self):
        self.update_footer()
        self.app.update_size_classes()

    def on_descendant_focus(self, event):
        self.update_footer()

    def on_screen_resume(self):
        self.update_footer()
        try:
            self.query_one(Header).refresh_text()
        except Exception:
            pass


def section(title, first=False):
    return Static(title.upper(), classes='section-title' + (' -first' if first else ''))


def prose(text):
    widget = Static(Text(text), classes='prose')
    return widget


# --------------------------------------------------------------------------------------------
# Dashboard
# --------------------------------------------------------------------------------------------
DETAILS = {
    'install': {
        'title': 'Install or update the manager',
        'changes': ('Installs missing prerequisites (Git, SSH, Docker/Compose, containerlab), prepares persistent '
                    'storage and the restricted clab-discovery account and helpers, rebuilds the manager image from '
                    'this checkout and recreates the manager, refreshes Browser Wireshark, verifies the running '
                    'version over HTTP, then sets up VS Code access, lazydocker and Git as selected.'),
        'keeps': ('Manager data, saved passwords, the clab-backup-ui/.env settings (or the defaults: all VM '
                  'interfaces, port 8081) and every lab container.'),
        'disruption': ('The manager container is rebuilt and recreated: its web UI is unavailable for a short time '
                       'and terminals or captures open in it end. Lab containers keep running. A first setup asks '
                       'you to create the clab-discovery password in the terminal.'),
    },
    'git': {
        'title': 'Git setup or repair',
        'changes': ('Runs deploy/setup-git.sh as {user} (home {home}): Git identity, GitHub login with a device '
                    'code, the checkout and its registration with the manager. It asks its own questions, so the '
                    'terminal is handed over while it runs.'),
        'keeps': 'The manager, its data and any existing checkout. Nothing is rebuilt.',
        'disruption': 'None for the manager. Git runs under your account only, never with sudo.',
    },
    'engineer': {
        'title': 'VS Code / Containerlab extension access',
        'changes': ('Adds {user} to the docker and clab_admins groups, makes the trusted lab folders '
                    'group-writable and sets the containerlab SUID bit, which VS Code Remote-SSH with the '
                    'Containerlab extension needs. Lab operations must already be enabled (Install/update does it).'),
        'keeps': 'The manager and its data. Nothing is rebuilt.',
        'disruption': ('New groups apply to new logins: reconnect SSH, and in VS Code run "Remote-SSH: Kill VS Code '
                       'Server on Host..." before using the extension.'),
    },
    'capture': {
        'title': 'Browser Wireshark stack',
        'changes': ('Pulls the pinned Wireshark image, rebuilds the capture session service, recreates the Edgeshark '
                    'and session containers, then recreates the manager container so it reads the capture '
                    'settings.'),
        'keeps': 'Manager data, labs and the capture session token in clab-backup-ui/.env.',
        'disruption': ('Not interruption-free: the manager container is recreated, so its web UI restarts briefly '
                       'and open capture sessions end.'),
    },
    'health': {
        'title': 'Check the installation',
        'changes': ('Nothing. Runs the read-only health report (deploy/check-install.sh): prerequisites, helpers, '
                    'manager routes, VM connection, Git and Browser Wireshark, with a next step for every problem.'),
        'keeps': 'Everything.',
        'disruption': ('None. Privileged checks use your cached sudo credentials; without them you are offered the '
                       'password prompt first, and declined checks are reported as skipped.'),
    },
    'settings': {
        'title': 'Advanced settings',
        'changes': ('Changes the Install/update choices: where the bind/port settings come from, lab operation '
                    'access, VS Code access, the installation-media APT repair, and Git now or later. Standard '
                    'defaults are preselected.'),
        'keeps': 'Everything: nothing runs until you press Start on the installation plan.',
        'disruption': 'None.',
    },
    'exit': {
        'title': 'Exit',
        'changes': 'Leaves the installer and returns to the shell. Nothing is changed.',
        'keeps': 'Everything.',
        'disruption': 'None.',
    },
}


class StatusTable(Static):
    def render_status(self, ctx):
        look = ctx.look
        narrow = self.app.size.width < 110
        table = Table.grid(padding=(0, 1), expand=True)
        table.add_column(width=15 if narrow else 22, no_wrap=True, overflow='ellipsis')
        table.add_column(width=15, no_wrap=True)
        table.add_column(ratio=1, no_wrap=True, overflow='ellipsis')
        short = {'access': 'VM account', 'capture': 'Wireshark', 'engineer': 'VS Code access'}
        for key, label in probes.COMPONENTS:
            result = ctx.status.get(key)
            state = probes.CHECKING if ctx.checking and result.state == probes.NOT_CHECKED else result.state
            summary = Text(result.summary or ('checking…' if ctx.checking else ''),
                           style=Style(color=None if look.no_color else T['slate-muted']))
            if result.detail and state != probes.READY and not narrow:
                summary.append(' — ' + result.detail, style=Style(color=None if look.no_color else T['slate-dim']))
            name = short.get(key, label) if narrow else label
            table.add_row(look.text(name, 'slate-text'), look.badge(state, 15), summary)
        self.update(table)


class Dashboard(Chrome):
    subtitle = 'Dashboard'
    BINDINGS = [
        Binding('r', 'refresh', 'refresh'),
        Binding('enter', 'open', 'open', show=False),
        Binding('escape', 'noop', show=False),
    ]

    def compose(self) -> ComposeResult:
        yield from self.chrome()
        with Horizontal(classes='body'):
            with Vertical(id='left-column'):
                with Vertical(id='nav-panel', classes='panel') as nav:
                    nav.border_title = 'Actions'
                    items = [ListItem(Label(id=f'nav-label-{key}'), id=f'nav-{key}') for key, _ in ACTIONS]
                    yield ListView(*items, id='nav')
                with Vertical(id='session-panel', classes='panel') as session:
                    session.border_title = 'Session'
                    yield Static(id='session')
                    yield Static(id='nav-hint')
            yield Static(classes='gap')
            with Vertical(id='right-column'):
                with VerticalScroll(id='detail-panel', classes='panel') as detail:
                    detail.border_title = 'Details'
                    detail.can_focus = True
                    yield Static(id='detail-title', classes='section-title -first')
                    yield Static(id='detail-body', classes='prose')
                with Vertical(id='status-panel', classes='panel') as status:
                    status.border_title = 'System status'
                    yield StatusTable(id='status', classes='statusline')

    def on_mount(self):
        super().on_mount()
        self.label_nav()
        nav = self.query_one('#nav', ListView)
        nav.index = 0
        nav.focus()
        self.show_details('install')
        self.refresh_status_view()
        self.set_interval(30, self.refresh_status_view)
        if self.ctx.checked_at is None and not self.ctx.checking:
            self.action_refresh()

    def hints(self):
        focused = self.focused
        arrows = '↑↓' if not self.ctx.look.ascii else 'up/dn'
        hints = [(arrows, 'scroll' if focused is not None and focused.id == 'detail-panel' else 'select'),
                 ('enter', 'open'), ('tab', 'pane'), ('r', 'refresh'), ('?', 'help'), ('ctrl+q', 'quit')]
        return hints

    def label_nav(self):
        narrow = self.app.size.width < 110
        for key, label in ACTIONS:
            text = Text(' ' + (SHORT_LABELS.get(key, label) if narrow else label), no_wrap=True, overflow='ellipsis')
            self.query_one(f'#nav-label-{key}', Label).update(text)

    def on_resize(self, event):
        self.label_nav()

    def current_action(self):
        nav = self.query_one('#nav', ListView)
        index = nav.index if nav.index is not None else 0
        return ACTIONS[index][0]

    @on(ListView.Highlighted, '#nav')
    def highlighted(self, event):
        if event.item is not None:
            self.show_details(event.item.id.removeprefix('nav-'))

    @on(ListView.Selected, '#nav')
    def selected(self, event):
        self.app.open_action(event.item.id.removeprefix('nav-'))

    def action_open(self):
        self.app.open_action(self.current_action())

    def action_noop(self):
        pass

    def show_details(self, key):
        ctx = self.ctx
        info = DETAILS[key]
        fill = {'user': ctx.env['USER'], 'home': ctx.env['HOME']}
        self.query_one('#detail-title', Static).update(info['title'].upper())
        look = ctx.look
        grid = Table.grid(padding=(0, 2, 1, 0), expand=True)
        grid.add_column(width=9, no_wrap=True)
        grid.add_column(ratio=1)
        warn = key in ('install', 'capture', 'engineer')
        for label, value, token in (('Changes', info['changes'], 'slate-text'), ('Keeps', info['keeps'], 'slate-text'),
                                    ('Restarts', info['disruption'], 'slate-warning' if warn else 'slate-text')):
            grid.add_row(Text(label, style=Style(color=None if look.no_color else T['slate-dim'], bold=True)),
                         Text(value.format(**fill), style=Style(color=None if look.no_color else T[token if token != 'slate-text' else 'slate-muted'])))
        if key == 'install':
            steps = [step for step in ctx.install.install_steps(ctx.env, ctx.version, ctx.options) if step.visible]
            phases = Text(style=Style(color=None if look.no_color else T['slate-muted']))
            for number, step in enumerate(steps, 1):
                phases.append(f'{number:>2}  {engine.label_for(step)}')
                if step.post:
                    phases.append('  after the manager', style=Style(color=None if look.no_color else T['slate-dim']))
                phases.append('\n')
            if ctx.advanced:
                phases.append('Advanced settings in use', style=Style(color=None if look.no_color else T['slate-warning']))
            phases.rstrip()
            grid.add_row(Text('Phases', style=Style(color=None if look.no_color else T['slate-dim'], bold=True)), phases)
        self.query_one('#detail-body', Static).update(grid)

    def refresh_status_view(self):
        ctx = self.ctx
        look = ctx.look
        stamp = ('checking now' if ctx.checking else
                 f'checked {time.strftime("%H:%M:%S", time.localtime(ctx.checked_at))} · {ago(ctx.checked_at)}'
                 if ctx.checked_at else 'not checked yet')
        self.query_one('#status-panel').border_subtitle = stamp + ' · r refreshes'
        self.query_one('#status', StatusTable).render_status(ctx)
        dim = Style(color=None if look.no_color else T['slate-dim'])
        value = Style(color=None if look.no_color else T['slate-muted'])
        grid = Table.grid(padding=(0, 1), expand=True)
        grid.add_column(width=9, no_wrap=True)
        grid.add_column(ratio=1, overflow='fold')
        manager = ctx.status.get('manager')
        sudo = ctx.status.get('sudo')
        rows = [('Account', ctx.account.pw_name), ('Host', ctx.host), ('Checkout', str(ctx.source)),
                ('Source', ctx.version),
                ('Manager', (manager.value + ' running') if manager and manager.value else
                 (manager.summary if manager and manager.summary else 'not checked')),
                ('sudo', sudo.summary if sudo and sudo.summary else 'not checked')]
        record = ctx.last_run
        if record:
            when = (record.get('finished') or '')[5:16].replace('T', ' ')
            rows.append(('Last run', f'{ACTION_LABELS.get(record.get("action"), record.get("action", ""))}: '
                                     f'{record.get("outcome") or "unknown"}, {when}'
                                     + (f' ({record["interrupted"]})' if record.get('interrupted') else '')))
        for key, text in rows:
            grid.add_row(Text(key, style=dim), Text(text, style=value))
        self.query_one('#session', Static).update(grid)
        self.query_one('#nav-hint', Static).update(
            Text('Browsing changes nothing. Enter reviews an action before anything runs.', style=dim))
        try:
            self.query_one(Header).refresh_text()
        except Exception:
            pass

    def action_refresh(self):
        self.app.refresh_status()


# --------------------------------------------------------------------------------------------
# Advanced settings and review
# --------------------------------------------------------------------------------------------
class SettingsScreen(Chrome):
    subtitle = 'Advanced settings'
    BINDINGS = [Binding('escape', 'back', 'back')]

    def __init__(self, then_review=False):
        super().__init__()
        self.then_review = then_review

    def compose(self) -> ComposeResult:
        ctx = self.ctx
        options = ctx.options
        env_state = ctx.env_state()
        yield from self.chrome()
        with Horizontal(classes='body'):
            with VerticalScroll(id='settings-panel', classes='panel'):
                yield Static('INSTALL / UPDATE CHOICES', classes='section-title -first')
                yield Static(Text('Standard defaults are preselected. Nothing runs until you press Start on the plan.'),
                             classes='field-help')
                yield Static('Manager bind/port settings', classes='field-label')
                if env_state == 'existing':
                    yield Static(Text('Existing clab-backup-ui/.env will be retained unchanged.'), classes='field-help')
                elif env_state == 'symlink':
                    yield Static(Text('The source .env is a symlink. Use a regular settings file before setup.'),
                                 classes='field-error')
                else:
                    with RadioSet(id='env-choice'):
                        yield RadioButton('Use defaults: all VM interfaces, port 8081', value=options.env_source is None)
                        yield RadioButton('Copy .env from a previous source folder', value=options.env_source is not None)
                    yield Input(value=str(options.env_source or ''), placeholder='/home/you/old-checkout/clab-backup-ui/.env',
                                id='env-path')
                    yield Static(Text('An absolute path to a regular file of at most 64 KiB. Its contents are '
                                      'never displayed; it is copied with private permissions.'), classes='field-help')
                    yield Static('', id='env-error', classes='field-error')
                yield Static('Lab operation access', classes='field-label')
                with RadioSet(id='operations'):
                    yield RadioButton('Enable reviewed lab operations (standard standalone setup)', value=options.operations == '1')
                    yield RadioButton('Discovery/import only; retain any previously enabled operations', value=options.operations == '2')
                yield Static('VS Code / Containerlab extension access for ' + ctx.env['USER'], classes='field-label')
                with RadioSet(id='engineer'):
                    yield RadioButton('Set up now: docker and clab_admins groups, group-writable lab folders, '
                                      'containerlab SUID (standard)', value=options.engineer == '1')
                    yield RadioButton('Skip; the manager does not need it', value=options.engineer != '1')
                yield Static('', id='engineer-help', classes='field-help')
                yield Static('Installation media', classes='field-label')
                yield Checkbox('Back up and disable obsolete installation-media APT entries if present',
                               value=options.repair, id='repair')
                yield Static('After the manager is ready', classes='field-label')
                with RadioSet(id='git-now'):
                    yield RadioButton('Set up or repair Git now', value=options.git_now)
                    yield RadioButton('Finish; set up Git later', value=not options.git_now)
                with Horizontal(classes='buttons'):
                    yield Button('Review plan', id='review', classes='primary')
                    yield Button('Standard defaults', id='defaults')
                    yield Button('Back', id='back')

    def on_mount(self):
        super().on_mount()
        self.sync_enabled()
        first = self.query('RadioSet, Checkbox, Input').first()
        if first is not None:
            first.focus()

    def hints(self):
        return [('tab', 'next field'), ('↑↓' if not self.ctx.look.ascii else 'up/dn', 'choose'), ('enter', 'select'),
                ('esc', 'back'), ('?', 'help')]

    def sync_enabled(self):
        operations = self.query_one('#operations', RadioSet).pressed_index
        engineer = self.query_one('#engineer', RadioSet)
        engineer.disabled = operations != 0
        self.query_one('#engineer-help', Static).update(
            Text('Only offered with reviewed lab operations enabled.' if operations != 0 else ''))
        try:
            copy = self.query_one('#env-choice', RadioSet).pressed_index == 1
            self.query_one('#env-path', Input).disabled = not copy
        except Exception:
            pass

    @on(RadioSet.Changed)
    def changed(self, event):
        self.sync_enabled()

    def collect(self):
        """Options from the form, or None with an explanation shown when the path is unusable."""
        ctx = self.ctx
        env_source = None
        try:
            if self.query_one('#env-choice', RadioSet).pressed_index == 1:
                value = self.query_one('#env-path', Input).value.strip()
                path = Path(value).expanduser() if value else None
                error = ''
                if path is None:
                    error = 'Enter the absolute path of the previous .env file.'
                elif not (path.is_absolute() and path.is_file() and not path.is_symlink()):
                    error = 'Choose a regular .env file (absolute path, not a symlink).'
                elif path.stat().st_size > 65536:
                    error = 'Choose a regular .env file no larger than 64 KiB.'
                self.query_one('#env-error', Static).update(Text(error))
                self.query_one('#env-path', Input).set_class(bool(error), '-invalid')
                if error:
                    self.query_one('#env-path', Input).focus()
                    return None
                env_source = path
        except OSError as error:
            self.query_one('#env-error', Static).update(Text(f'That file cannot be read: {error.strerror}'))
            return None
        except Exception:
            env_source = None
        operations = '1' if self.query_one('#operations', RadioSet).pressed_index == 0 else '2'
        engineer = '1' if (operations == '1' and self.query_one('#engineer', RadioSet).pressed_index == 0) else '2'
        repair = self.query_one('#repair', Checkbox).value
        git_now = self.query_one('#git-now', RadioSet).pressed_index == 0
        return ctx.install.Options(env_source, operations, engineer, repair, git_now)

    @on(Button.Pressed, '#review')
    def review(self):
        options = self.collect()
        if options is None:
            return
        self.ctx.options = options
        self.ctx.advanced = True
        self.app.switch_screen(ReviewScreen('install'))

    @on(Button.Pressed, '#defaults')
    def defaults(self):
        self.ctx.options = self.ctx.install.Options()
        self.ctx.advanced = False
        self.app.switch_screen(SettingsScreen(self.then_review))

    @on(Button.Pressed, '#back')
    def action_back(self):
        self.app.pop_screen()


class ReviewScreen(Chrome):
    """The short plan shown before a mutating action starts; one Start button."""

    BINDINGS = [Binding('escape', 'cancel', 'cancel')]

    def __init__(self, action):
        super().__init__()
        self.action = action
        self.subtitle = 'Review: ' + ACTION_LABELS[action]

    def compose(self) -> ComposeResult:
        yield from self.chrome()
        with Vertical(classes='body'):
            with VerticalScroll(id='review-panel', classes='panel') as panel:
                panel.border_title = 'Plan · nothing has run yet'
                panel.can_focus = True
                yield Static(id='review-body')
            with Horizontal(classes='buttons bar'):
                yield Button('Start', id='start', classes='primary')
                if self.action == 'install':
                    yield Button('Advanced settings', id='settings')
                yield Button('Cancel', id='cancel')

    def on_mount(self):
        super().on_mount()
        self.query_one('#review-body', Static).update(self.plan_text())
        self.query_one('#start', Button).focus()
        if self.action == 'install' and self.ctx.env_state() == 'symlink':
            self.query_one('#start', Button).disabled = True

    def hints(self):
        return [('enter', 'start' if isinstance(self.focused, Button) and self.focused.id == 'start' else 'press'),
                ('tab', 'next'), ('esc', 'cancel'), ('?', 'help')]

    def plan_text(self):
        ctx = self.ctx
        look = ctx.look
        install = ctx.install
        text = Text()
        heading = Style(color=None if look.no_color else T['slate-accent'], bold=True)
        body = Style(color=None if look.no_color else T['slate-muted'])
        warn = Style(color=None if look.no_color else T['slate-warning'], bold=True)
        bullet = look.glyph('bullet')
        dim = Style(color=None if look.no_color else T['slate-dim'])
        parts = [Text(DETAILS[self.action]['title'].upper(), style=heading)]

        def bullets(lines, style=body, marker=bullet):
            grid = Table.grid(padding=(0, 1))
            grid.add_column(width=3, justify='right', no_wrap=True)
            grid.add_column(ratio=1)
            for item in lines:
                grid.add_row(Text(marker, style=dim), Text(item, style=style))
            return grid
        if self.action == 'install':
            if ctx.env_state() == 'symlink':
                parts.append(Text('The source .env is a symlink. Use a regular settings file before setup.', style=warn))
            lines = install.plan_lines(ctx.env, ctx.version, ctx.options)
            if not ctx.options.git_now:
                # The plain wording above is shared; the advanced "Git later" choice is made before Start here.
                lines = lines + ['Git: not in this run (Finish; set up Git later was chosen in Advanced settings).']
            parts.append(bullets(lines))
        else:
            parts.append(bullets([DETAILS[self.action]['changes'].format(user=ctx.env['USER'], home=ctx.env['HOME'])]))
        steps = [step for step in install.action_steps(self.action, ctx.env, ctx.version, ctx.options) if step.visible]
        parts.append(Text('\nPHASES', style=heading))
        grid = Table.grid(padding=(0, 1))
        grid.add_column(width=3, justify='right', no_wrap=True)
        grid.add_column(no_wrap=True)
        grid.add_column(ratio=1)
        for number, step in enumerate(steps, 1):
            how = {'always': 'uses the terminal', 'password': 'first setup uses the terminal',
                   'auth': 'may ask for your sudo password'}.get(step.interactive, '')
            tags = ', '.join(tag for tag in (how, 'after the manager' if step.post else '') if tag)
            grid.add_row(Text(str(number), style=dim), Text(engine.label_for(step), style=Style(color=None if look.no_color else T['slate-text'])),
                         Text(tags, style=dim))
        parts.append(grid)
        parts.append(Text('\nKEPT', style=heading))
        parts.append(bullets([DETAILS[self.action]['keeps']]))
        parts.append(Text('\nRESTARTS AND INTERRUPTIONS', style=heading))
        parts.append(bullets([DETAILS[self.action]['disruption']], style=warn if self.action in ('install', 'capture') else body))
        parts.append(Text('\nStart runs these phases. Cancel returns to the dashboard without changing anything.', style=dim))
        return Group(*parts)

    @on(Button.Pressed, '#start')
    def start(self):
        self.app.start_run(self.action)

    @on(Button.Pressed, '#settings')
    def settings(self):
        self.app.switch_screen(SettingsScreen(then_review=True))

    @on(Button.Pressed, '#cancel')
    def action_cancel(self):
        self.app.pop_screen()


# --------------------------------------------------------------------------------------------
# Execution, recovery and results
# --------------------------------------------------------------------------------------------
class RunScreen(Chrome):
    BINDINGS = [
        Binding('s', 'stop', 'stop after step'),
        Binding('x', 'interrupt', 'interrupt step'),
        Binding('f', 'follow', 'follow'),
        Binding('o', 'view_output', 'view output'),
        Binding('a', 'all_output', 'all output', show=False),
        Binding('escape', 'escape', show=False),
        Binding('end', 'output_end', show=False),
    ]

    def __init__(self, run):
        super().__init__()
        self.run = run
        self.subtitle = 'Running: ' + ('Check installation' if run.action == 'health' else ACTION_LABELS[run.action])
        self.items = {}
        self.follow = True
        self.viewing = None          # None: all phases; else a phase key
        self.buffers = {p.key: [] for p in run.phases}
        self.total_lines = 0
        self.dropped = 0
        self.spin = 0
        self.decision = None
        self.failure_key = None
        self.headed = {}

    def compose(self) -> ComposeResult:
        yield from self.chrome()
        with Horizontal(classes='body'):
            with Vertical(id='phase-panel', classes='panel') as panel:
                panel.border_title = 'Phases'
                items = []
                for phase in self.run.phases:
                    label = Label(id=f'phase-label-{phase.key}')
                    self.items[phase.key] = label
                    items.append(ListItem(label, id=f'phase-{phase.key}'))
                yield ListView(*items, id='phases')
                yield Static(id='run-summary')
            yield Static(classes='gap')
            with Vertical(id='work-column'):
                with Vertical(id='activity-panel', classes='panel') as activity:
                    activity.border_title = 'Activity'
                    yield Static(id='activity')
                    with Vertical(id='recovery'):
                        with VerticalScroll(id='recovery-scroll'):
                            yield Static(id='recovery-text')
                        yield Vertical(id='recovery-buttons')
                with Vertical(id='output-panel', classes='panel') as output:
                    output.border_title = 'Output'
                    yield Log(id='output', max_lines=OUTPUT_LINES, auto_scroll=True, highlight=False)

    def on_mount(self):
        super().on_mount()
        for phase in self.run.phases:
            self.render_phase(phase)
        self.render_activity()
        self.set_interval(0.25, self.tick)
        self.query_one('#output', Log).focus()
        self.update_output_title()

    def hints(self):
        if self.run.active:
            if self.failure_key:
                return [('tab', 'next'), ('enter', 'choose'), ('o', 'view output'), ('?', 'help')]
            return [('s', 'stop after step' if not self.run.stop else 'stopping…'), ('f', 'pause follow' if self.follow else 'follow'),
                    ('o', 'output'), ('x', 'interrupt'), ('tab', 'pane'), ('?', 'help')]
        return [('enter', 'continue'), ('o', 'view output'), ('?', 'help')]

    # ---- rendering -------------------------------------------------------------------------
    def phase_text(self, phase):
        look = self.ctx.look
        state = phase.state
        color = look.state_color(state)
        glyph = look.glyph(state)
        if state == engine.RUNNING:
            glyph = look.glyph('spinner')[self.spin % 4]
        row = Table.grid(padding=(0, 1), expand=True)
        row.add_column(width=1, no_wrap=True)
        row.add_column(ratio=1, no_wrap=True, overflow='ellipsis')
        narrow = self.app.size.width < 110
        row.add_column(width=9 if narrow else 15, no_wrap=True, justify='right')
        word = {'Waiting for input': 'Waiting', 'Not started': 'Not run'}.get(state, state)
        elapsed = clock(phase.elapsed)
        # At compact widths the elapsed time moves to the activity line; the state word stays.
        tail = word + (f' {elapsed}' if elapsed and not narrow and state not in (engine.PENDING, engine.NOT_STARTED) else '')
        quiet = state in (engine.PENDING, engine.NOT_STARTED)
        row.add_row(Text(glyph, style=Style(color=None if look.no_color else color, bold=True)),
                    Text(phase.label, style=Style(color=None if look.no_color else (T['slate-muted'] if quiet else T['slate-text']),
                                                  bold=state in (engine.RUNNING, engine.WAITING, engine.FAILED))),
                    Text(tail, style=Style(color=None if look.no_color else (T['slate-dim'] if quiet else color))))
        return row

    def render_phase(self, phase):
        label = self.items.get(phase.key)
        if label is not None:
            label.update(self.phase_text(phase))

    def render_summary(self):
        look = self.ctx.look
        phases = self.run.phases
        done = sum(p.state == engine.COMPLETED for p in phases)
        text = Text(style=Style(color=None if look.no_color else T['slate-dim']))
        text.append(f'{done} of {len(phases)} phases completed\n')
        started = self.run.started
        if started:
            text.append(f'elapsed {clock((self.run.finished_at or time.time()) - started)}\n')
        if self.run.stop and self.run.active:
            text.append('Stopping after the current phase\n', style=Style(color=None if look.no_color else T['slate-warning'], bold=True))
        self.query_one('#run-summary', Static).update(text)

    def render_activity(self):
        look = self.ctx.look
        run = self.run
        current = run.current
        text = Text()
        if run.active and current is not None:
            if current.state == engine.WAITING:
                text.append('Waiting for input  ', style=Style(color=None if look.no_color else T['slate-warning'], bold=True))
                text.append(current.label + '\n', style=Style(bold=True))
                text.append(current.note or 'The terminal was handed over.', style=Style(color=None if look.no_color else T['slate-muted']))
            elif current.state == engine.FAILED:
                text.append('Needs attention  ', style=Style(color=None if look.no_color else T['slate-error'], bold=True))
                text.append(current.label, style=Style(bold=True))
            else:
                spinner = look.glyph('spinner')[self.spin % 4]
                text.append(f'{spinner} Running  ', style=Style(color=None if look.no_color else T['slate-accent'], bold=True))
                text.append(current.label, style=Style(bold=True))
                text.append(f'   {clock(current.elapsed)}', style=Style(color=None if look.no_color else T['slate-dim']))
                last = next((line for line in reversed(self.buffers.get(current.key, [])) if line.strip()), '')
                text.append('\n' + (last[:300] or 'starting…'), style=Style(color=None if look.no_color else T['slate-muted']))
        elif not run.active and run.outcome:
            word = OUTCOME_WORDS.get(run.outcome, 'Stopped')
            text.append_text(look.badge(word))
            text.append('  Run finished. Press enter for the summary.', style=Style(bold=True))
        else:
            text.append('Starting…', style=Style(color=None if look.no_color else T['slate-muted']))
        self.query_one('#activity', Static).update(text)

    def tick(self):
        self.spin += 1
        current = self.run.current
        if current is not None:
            self.render_phase(current)
        self.render_activity()
        self.render_summary()

    def update_output_title(self):
        panel = self.query_one('#output-panel')
        which = 'all phases' if self.viewing is None else engine.LABELS.get(self.viewing, self.viewing)
        panel.border_title = f'Output · {which}'
        notes = []
        if not self.follow:
            notes.append('follow paused (f resumes; the run continues)')
        hidden = self.total_lines - OUTPUT_LINES if self.viewing is None else 0
        if hidden > 0:
            notes.append(f'earlier {hidden} lines not shown')
        panel.border_subtitle = ' · '.join(notes)

    # ---- events from the run (main thread) -------------------------------------------------
    def on_phase(self, key):
        phase = self.run.phase(key)
        if phase is None:
            return
        self.render_phase(phase)
        self.render_activity()
        self.render_summary()
        if phase.state == engine.RUNNING and self.failure_key == key:
            self.hide_recovery()
        if phase.state == engine.RUNNING and self.headed.get(key) != phase.attempts:
            self.headed[key] = phase.attempts
            suffix = f': attempt {phase.attempts}' if phase.attempts > 1 else ''
            self.add_lines(key, [f'── {phase.label}{suffix} ──'])

    def add_lines(self, key, lines):
        buffer = self.buffers.setdefault(key, [])
        buffer.extend(lines)
        if len(buffer) > core.TAIL_LINES:
            del buffer[:len(buffer) - core.TAIL_LINES]
        self.total_lines += len(lines)
        if self.viewing is None or self.viewing == key:
            log = self.query_one('#output', Log)
            log.write_lines(lines, scroll_end=False)
            if self.follow:
                log.scroll_end(animate=False)
        if self.total_lines > OUTPUT_LINES:
            self.update_output_title()

    # ---- recovery --------------------------------------------------------------------------
    def show_recovery(self, key, failure):
        look = self.ctx.look
        phase = self.run.phase(key)
        self.failure_key = key
        box = self.query_one('#recovery')
        box.set_class(True, '-shown')
        box.set_class(failure.kind == 'lock', '-lock')
        box.border_title = 'Package lock' if failure.kind == 'lock' else 'Needs attention'
        text = Text()
        text.append(f'{phase.label}: ', style=Style(bold=True))
        text.append(failure.message + '\n', style=Style(color=None if look.no_color else T['slate-text']))
        if failure.kind == 'lock':
            install = self.ctx.install
            if failure.holder:
                text.append(failure.holder.strip()[:1500] + '\n', style=Style(color=None if look.no_color else T['slate-muted']))
            if 'snapshot rollback' not in (failure.holder or ''):
                text.append(install.RESTART_HINT + '\n', style=Style(color=None if look.no_color else T['slate-muted']))
            import shlex
            command = shlex.join(install.lock_wait_command())
            text.append('Copyable command, in another terminal (also on one line in the output pane): ',
                        style=Style(color=None if look.no_color else T['slate-dim']))
            text.append(command + '\n', style=Style(color=None if look.no_color else T['slate-text']))
            # The output pane never wraps, so the command can be selected there as one line.
            self.add_lines(key, ['Copyable command, in another terminal: ' + command])
            text.append('The installer never stops the upgrade, kills a process or deletes a lock file.',
                        style=Style(color=None if look.no_color else T['slate-dim']))
        elif failure.kind == 'auth':
            text.append('Authenticate opens sudo\'s own password prompt in the terminal, then retries this phase.',
                        style=Style(color=None if look.no_color else T['slate-muted']))
        else:
            done = [p.label for p in self.run.phases if p.state == engine.COMPLETED]
            if done:
                text.append('Kept: ' + ', '.join(done) + '.\n', style=Style(color=None if look.no_color else T['slate-muted']))
            text.append('Retry repeats only this phase. The output pane below shows what the step printed (o widens it).',
                        style=Style(color=None if look.no_color else T['slate-dim']))
        self.query_one('#recovery-text', Static).update(text)
        buttons = self.query_one('#recovery-buttons')
        buttons.remove_children()
        labels = {
            engine.RETRY: 'Retry phase', engine.AUTH_RETRY: 'Authenticate, retry',
            engine.LOCK_WAIT: 'Wait for lock', engine.LOCK_CHECK: 'Check again',
            engine.RETURN: 'Return, keep work', engine.SKIP: 'Finish without it',
        }
        widgets = []
        for index, choice in enumerate(failure.choices):
            widgets.append(Button(labels[choice], id=f'choose-{choice}', classes='primary' if index == 0 else ''))
        buttons.mount(*widgets)
        if self.viewing not in (None, key):
            self.show_output(key)
        self.call_after_refresh(lambda: widgets[0].focus())
        self.update_footer()

    def hide_recovery(self):
        self.failure_key = None
        box = self.query_one('#recovery')
        box.set_class(False, '-shown')
        self.query_one('#recovery-buttons').remove_children()
        self.query_one('#output', Log).focus()
        self.update_footer()

    @on(Button.Pressed, '#recovery-buttons Button')
    def choose(self, event):
        if event.button.id == 'inspect':
            self.show_output(self.failure_key)
            self.query_one('#output', Log).focus()
            return
        choice = event.button.id.removeprefix('choose-')
        if choice == engine.LOCK_WAIT:
            self.add_lines(self.failure_key, ['Waiting for the package lock; press s to stop waiting.'])
        self.hide_recovery()
        self.app.decide(choice)

    # ---- actions ---------------------------------------------------------------------------
    def action_stop(self):
        if not self.run.active:
            return
        if self.run._lock_waiter is not None:
            if getattr(self.run._lock_waiter, 'cancel_sent', False):
                self.app.notify('Already stopping the package-lock wait; its APT timers are being restored.', timeout=4)
            elif self.run.cancel_lock_wait():
                self.app.notify('Stopping the package-lock wait (APT timers are restored).', timeout=4)
            return
        self.run.request_stop()
        self.app.notify('The current phase finishes; no later phase starts.', title='Stop after this step', timeout=5)
        self.render_summary()
        self.update_footer()

    def action_interrupt(self):
        run = self.run
        if not run.active or run.process is None or run.current is None:
            self.app.notify('Nothing to interrupt: no step process is running right now.', timeout=4)
            return
        phase = run.current
        risk = ('Interrupting package installation can leave packages half-configured (the next run repairs '
                'them with dpkg). Prefer waiting unless it is clearly stuck.' if phase.key == 'prereqs' else
                'The helper stops where it is; completed phases and existing data are kept.')

        def chosen(answer):
            if answer == 'interrupt' and run.interrupt_current():
                self.app.notify('Ctrl+C sent to the step.', timeout=4)
        self.app.push_screen(Dialog('Interrupt this step?',
                                    Text(f'{phase.label} is still running. Interrupt sends it Ctrl+C, exactly as Ctrl+C '
                                         f'does in the plain installer. {risk}\n\nThe phase is then marked failed and '
                                         'you can retry it or return.'),
                                    buttons=(('keep', 'Keep running', 'primary'), ('interrupt', 'Interrupt step', 'warning'))),
                             chosen)

    def action_follow(self):
        self.follow = not self.follow
        log = self.query_one('#output', Log)
        log.auto_scroll = self.follow
        if self.follow:
            log.scroll_end(animate=False)
        self.update_output_title()
        self.update_footer()

    def action_output_end(self):
        self.query_one('#output', Log).scroll_end(animate=False)

    def action_view_output(self):
        panel = self.query_one('#phase-panel')
        activity = self.query_one('#activity-panel')
        maximize = panel.display
        panel.display = not maximize
        activity.display = not maximize or self.failure_key is not None
        self.query_one('#output', Log).focus()

    def action_all_output(self):
        self.show_output(None)

    def show_output(self, key):
        self.viewing = key
        log = self.query_one('#output', Log)
        log.clear()
        if key is None:
            lines = []
            for phase in self.run.phases:
                lines.extend(self.buffers.get(phase.key, []))
            log.write_lines(lines[-OUTPUT_LINES:])
        else:
            log.write_lines(self.buffers.get(key, []) or ['(no output from this phase)'])
        log.scroll_end(animate=False)
        self.update_output_title()

    @on(ListView.Selected, '#phases')
    def phase_selected(self, event):
        key = event.item.id.removeprefix('phase-')
        self.show_output(None if self.viewing == key else key)

    def action_escape(self):
        if self.run.active:
            self.app.notify('A phase is running. Press s to stop after it; nothing is abandoned.', timeout=5)
        else:
            self.app.show_result(self.run)

    def key_enter(self):
        if not self.run.active and not self.failure_key and not isinstance(self.focused, (Button, ListView)):
            self.app.show_result(self.run)

    def run_finished(self):
        self.render_activity()
        self.render_summary()
        for phase in self.run.phases:
            self.render_phase(phase)
        self.hide_recovery() if self.failure_key else None
        self.update_footer()


class ResultScreen(Chrome):
    BINDINGS = [Binding('escape', 'dashboard', 'dashboard'), Binding('o', 'output', 'output')]

    def __init__(self, run):
        super().__init__()
        self.run = run
        self.subtitle = 'Result: ' + ('Check installation' if run.action == 'health' else ACTION_LABELS[run.action])

    def compose(self) -> ComposeResult:
        yield from self.chrome()
        with Vertical(classes='body'):
            with VerticalScroll(id='result-panel', classes='panel') as panel:
                panel.border_title = 'Summary'
                panel.can_focus = True
                yield Static(id='result')
            with Horizontal(classes='buttons bar'):
                yield Button('Finish', id='finish', classes='primary')
                yield Button('Back to dashboard', id='dashboard')
                yield Button('View output', id='output')

    def on_mount(self):
        super().on_mount()
        self.query_one('#result', Static).update(self.app.summary_renderable(self.run))
        self.query_one('#finish', Button).focus()

    def hints(self):
        return [('enter', 'press'), ('tab', 'next'), ('esc', 'dashboard'), ('o', 'output'), ('?', 'help')]

    @on(Button.Pressed, '#finish')
    def finish(self):
        self.app.finish(self.run)

    @on(Button.Pressed, '#dashboard')
    def action_dashboard(self):
        self.app.back_to_dashboard()

    @on(Button.Pressed, '#output')
    def action_output(self):
        self.app.pop_screen()


# --------------------------------------------------------------------------------------------
# Dialogs
# --------------------------------------------------------------------------------------------
class Dialog(ModalScreen):
    BINDINGS = [Binding('escape', 'close', 'close'), Binding('left', 'button_left', show=False),
                Binding('right', 'button_right', show=False)]

    def action_button_left(self):
        self.focus_previous(Button)

    def action_button_right(self):
        self.focus_next(Button)

    def __init__(self, title, body, buttons=(('ok', 'Close', 'primary'),)):
        super().__init__()
        self.title_text = title
        self.body = body
        self.buttons = buttons

    def compose(self) -> ComposeResult:
        with Vertical(classes='dialog') as box:
            box.border_title = self.title_text
            yield Static(self.body, classes='prose')
            with Horizontal(classes='buttons'):
                for key, label, kind in self.buttons:
                    yield Button(label, id=f'dialog-{key}', classes=kind)

    def on_mount(self):
        self.query(Button).first().focus()

    @on(Button.Pressed)
    def pressed(self, event):
        self.dismiss(event.button.id.removeprefix('dialog-'))

    def action_close(self):
        self.dismiss(None)


HELP = [
    ('↑ ↓', 'Move the selection in a list; scroll a focused text pane'),
    ('Tab / Shift+Tab', 'Move focus between panes, fields and buttons'),
    ('Enter', 'Open the selected action, choose a button, or select a phase\'s output'),
    ('Esc', 'Go back or close a dialog (never abandons a running phase)'),
    ('r', 'Refresh the dashboard status (read-only checks)'),
    ('s', 'Stop after the current phase (or stop a package-lock wait)'),
    ('x', 'Interrupt the running step with Ctrl+C, after a confirmation (for a step that is stuck)'),
    ('f', 'Pause or resume following new output; the run continues either way'),
    ('o', 'View output: widen the output pane'),
    ('PgUp / PgDn / End', 'Scroll the focused output'),
    ('?', 'This help'),
    ('Ctrl+Q', 'Quit (asks first while a phase runs)'),
]


# --------------------------------------------------------------------------------------------
# The app
# --------------------------------------------------------------------------------------------
class SlateOps(App):
    CSS = theme.STYLESHEET
    TITLE = 'Slate Ops'
    ENABLE_COMMAND_PALETTE = False
    BINDINGS = [
        Binding('ctrl+q', 'request_quit', 'quit', priority=True),
        Binding('ctrl+c', 'request_quit', 'quit', priority=True, show=False),
        Binding('question_mark', 'help', 'help'),
        Binding('f1', 'help', 'help', show=False),
    ]

    def __init__(self, ctx, start_action=None, ansi_color=None):
        super().__init__(ansi_color=ansi_color)
        self.ctx = ctx
        self.start_action = start_action
        self.current_run = None
        self.bridge = None
        self.summary_lines = None
        self.exit_code = 0
        self.terminal_lost = False
        self.started_any_run = False

    def get_css_variables(self):
        variables = super().get_css_variables()
        variables.update(theme.css_variables())
        return variables

    def on_mount(self):
        self.register_theme(Theme(name='slate-ops', primary=T['slate-accent'], secondary=T['slate-accent-soft'],
                                  accent=T['slate-accent'], warning=T['slate-warning'], error=T['slate-error'],
                                  success=T['slate-success'], foreground=T['slate-text'], background=T['slate-bg'],
                                  surface=T['slate-panel'], panel=T['slate-elevated'], dark=True,
                                  variables={'block-cursor-background': T['slate-select'],
                                             'block-cursor-foreground': T['slate-text'],
                                             'block-cursor-blurred-background': T['slate-select-blur'],
                                             'footer-background': T['slate-wash'],
                                             'scrollbar': T['slate-border'],
                                             'scrollbar-hover': T['slate-accent'],
                                             'input-selection-background': T['slate-select']}))
        self.theme = 'slate-ops'
        self.set_class(self.ctx.look.ascii, '-ascii')
        for signum in (signal.SIGHUP, signal.SIGTERM):
            try:
                signal.signal(signum, self._terminal_signal)
            except (ValueError, OSError):
                pass
        self.push_screen(Dashboard())
        if self.start_action == 'git':
            self.open_action('git')

    # ---- size classes ----------------------------------------------------------------------
    def update_size_classes(self, size=None):
        width, height = size or self.size
        self.set_class(width < 80 or height < 24, '-tiny')
        self.set_class(width < 110, '-narrow')
        self.set_class(height < 32, '-short')
        self.set_class(width >= 150, '-wide')
        try:
            notice = self.screen.query_one('#too-small', Static)
            notice.update(Text(f'Terminal {width}×{height} is too small for the installer.\n'
                               'Enlarge the window to at least 80×24.\n'
                               'A running phase continues meanwhile; ctrl+q quits.', justify='center'))
        except Exception:
            pass

    def on_resize(self, event: events.Resize):
        # The handler runs before App stores the new size: use the event's.
        self.update_size_classes(event.size)

    # ---- navigation ------------------------------------------------------------------------
    def open_action(self, key):
        if self.current_run is not None and self.current_run.active:
            self.push_screen(RunScreen(self.current_run))
            return
        if key == 'exit':
            self.action_request_quit()
        elif key == 'settings':
            self.push_screen(SettingsScreen())
        elif key == 'health':
            self.start_run('health')
        elif key == 'install' and self.start_action == 'advanced':
            # --advanced: every Install/update choice is shown before the plan, as the plain menu asks them.
            self.push_screen(SettingsScreen(then_review=True))
        else:
            self.push_screen(ReviewScreen(key))

    def refresh_status(self):
        """Re-run the read-only probes in the background; every visible header and the dashboard
        update as answers arrive. Called on demand (r), at start, and after every run."""
        if self.ctx.checking:
            return
        self.ctx.checking = True
        self.status_changed()
        self._probe_worker()

    @work(thread=True, exclusive=True, group='probes')
    def _probe_worker(self):
        ctx = self.ctx
        context = probes.Context(ctx.env, ctx.source, ctx.version)

        def partial(result):
            try:
                self.call_from_thread(self._probe_result, result)
            except Exception:
                pass
        results, stamp = probes.run_all(context, on_result=partial)
        try:
            self.call_from_thread(self._probes_done, results, stamp)
        except Exception:
            pass

    def _probe_result(self, result):
        self.ctx.status[result.key] = result
        self.status_changed()

    def _probes_done(self, results, stamp):
        self.ctx.status.update(results)
        self.ctx.checked_at = stamp
        self.ctx.checking = False
        self.status_changed()

    def status_changed(self):
        for screen in self.screen_stack:
            if isinstance(screen, Dashboard):
                screen.refresh_status_view()
            try:
                screen.query_one(Header).refresh_text()
            except Exception:
                pass

    def back_to_dashboard(self):
        while len(self.screen_stack) > 2:
            self.pop_screen()
        self.refresh_status()

    # ---- runs ------------------------------------------------------------------------------
    def start_run(self, action):
        if self.current_run is not None and self.current_run.active:
            self.notify('Another action is still running.', severity='warning')
            return
        lock = None
        if action != 'health':
            try:
                lock = core.InstallerLock().acquire()
            except core.Busy as error:
                self.push_screen(Dialog('Installer busy', Text(str(error))))
                return
            except OSError as error:
                self.push_screen(Dialog('Installer lock unavailable', Text(f'The installer lock could not be opened: {error}')))
                return
        self.bridge = Bridge(self)
        if action == 'health':
            run = engine.HealthRun(self.ctx.install, self.ctx.env, self.ctx.version, bridge=self.bridge)
        else:
            run = engine.Run(self.ctx.install, action, self.ctx.env, self.ctx.version,
                             options=self.ctx.options if action == 'install' else None, bridge=self.bridge, lock=lock)
        self.current_run = run
        self.started_any_run = True
        while len(self.screen_stack) > 2:
            self.pop_screen()
        self.push_screen(RunScreen(run))
        run.start()

    def run_screen(self):
        for screen in reversed(self.screen_stack):
            if isinstance(screen, RunScreen) and screen.run is self.current_run:
                return screen
        return None

    def on_bridge_phase(self, key):
        screen = self.run_screen()
        if screen is not None:
            screen.on_phase(key)

    def on_bridge_output(self, key, lines):
        screen = self.run_screen()
        if screen is not None:
            screen.add_lines(key, lines)

    def on_bridge_recover(self, key, failure):
        screen = self.run_screen()
        if screen is None:
            self.push_screen(RunScreen(self.current_run))
            screen = self.run_screen()
        if self.screen is not screen:
            while self.screen is not screen and len(self.screen_stack) > 1:
                self.pop_screen()
        screen.show_recovery(key, failure)

    def decide(self, choice):
        if self.bridge is not None:
            self.bridge.decisions.put(choice)

    def on_bridge_finished(self):
        run = self.current_run
        screen = self.run_screen()
        if screen is not None:
            screen.run_finished()
        if run is not None and run.action == 'health':
            self.ctx.health = getattr(run, 'report', None)
        self.ctx.last_run = run.record() if run is not None else self.ctx.last_run
        if not self.terminal_lost:
            self.refresh_status()
        if self.pending_quit:
            self.exit(return_code=self.exit_status(run))
            return
        if run is not None and run.outcome in ('completed', 'partial', 'failed', 'stopped', 'returned'):
            self.show_result(run)

    pending_quit = False

    def show_result(self, run):
        if isinstance(self.screen, ResultScreen):
            return
        self.push_screen(ResultScreen(run))

    # ---- terminal handoff ------------------------------------------------------------------
    def handoff(self, title, notice, work):
        """Run `work` with the real terminal (sudo, the password prompt, Git). Main thread only."""
        driver = self._driver
        if driver is None or not getattr(driver, 'can_suspend', False):
            return None
        result = None
        # A Python-level no-op SIGINT handler (not SIG_IGN) for the whole time the terminal is in
        # normal mode: Ctrl+C still reaches the child, whose dispositions reset on exec, while this
        # process and its event loop survive it.
        guard = signal.signal(signal.SIGINT, lambda *_: None)
        try:
            with self.suspend():
                result = self._handoff_body(title, notice, work)
        finally:
            signal.signal(signal.SIGINT, guard)
        self.update_size_classes()
        self.refresh(layout=True)
        return result

    def _handoff_body(self, title, notice, work):
        # suspend() itself has no try/finally: nothing may escape this, or the screen never returns.
        result = None
        try:
            out = sys.__stdout__
            rule = '─' * 64 if not self.ctx.look.ascii else '-' * 64
            out.write(f'\n{rule}\nSlate Ops · {title}\n')
            out.write('\n'.join(textwrap.wrap(notice, 78)) + f'\n{rule}\n\n')
            out.flush()
            result = work()
            if result not in (0, None):
                out.write(f'\n{title} ended with exit status {result}. Press Enter to return to the installer. ')
                out.flush()
                try:
                    sys.__stdin__.readline()
                except (OSError, ValueError):
                    pass
            else:
                out.write(f'\n{title}: done. Returning to the installer…\n')
                out.flush()
                time.sleep(0.4)
        except BaseException as error:  # never leave the app suspended
            if result is None:
                result = 255
            try:
                sys.__stderr__.write(f'\n{title}: {type(error).__name__}\n')
            except Exception:
                pass
        return result

    # ---- quitting --------------------------------------------------------------------------
    def action_request_quit(self):
        run = self.current_run
        if run is not None and run.active:
            def chosen(answer):
                if answer == 'stop':
                    self.pending_quit = True
                    run.request_stop('quit requested')
                    if run._lock_waiter is not None:
                        run.cancel_lock_wait()
                    self.notify('Quitting after the current phase finishes.', timeout=6)
            phase = run.current.label if run.current else 'a phase'
            self.push_screen(Dialog('A phase is running',
                                    Text(f'{phase} is running. Quitting immediately would leave it unfinished '
                                         'in the background, so the installer does not offer that.\n\n'
                                         'Stop after it: the phase finishes safely, nothing later starts, and the '
                                         'installer then exits with a summary.'),
                                    buttons=(('keep', 'Keep running', 'primary'),
                                             ('stop', 'Stop after this phase, then quit', 'warning'))), chosen)
            return
        self.exit(return_code=self.exit_status(run) if run is not None else 0)

    def action_help(self):
        look = self.ctx.look
        table = Table.grid(padding=(0, 2))
        table.add_column(style=Style(color=None if look.no_color else T['slate-accent'], bold=True), no_wrap=True)
        table.add_column(style=Style(color=None if look.no_color else T['slate-muted']))
        for key, text in HELP:
            table.add_row(key, text)
        note = Text('\nSelect text with your terminal\'s own selection (often Shift+drag while the installer is '
                    'open). On Finish, a plain summary is also printed to the normal terminal scrollback.',
                    style=Style(color=None if look.no_color else T['slate-dim']))
        self.push_screen(Dialog('Keys', Group(table, note)))

    def _terminal_signal(self, signum, frame):
        # SIGHUP (SSH or terminal lost) or SIGTERM: let the active phase finish (its process group
        # does not receive the hangup), start nothing later, ask nothing, and exit.
        self.terminal_lost = signum == signal.SIGHUP
        reason = 'terminal disconnected' if signum == signal.SIGHUP else 'installer terminated'
        if self.bridge is not None:
            self.bridge.alive = False
            self.bridge.decisions.put(engine.RETURN)
        if self.current_run is not None and self.current_run.active:
            self.current_run.disconnect(reason)
        try:
            self.exit(return_code=1)
        except Exception:
            pass

    def exit_status(self, run):
        if run is None:
            return 0
        if run.action == 'health':
            report = getattr(run, 'report', None) or {}
            return report.get('exit_code', 1) if isinstance(report.get('exit_code'), int) else 1
        if run.action == 'git':
            phase = run.phase('git')
            return phase.code if phase and phase.code is not None else (0 if run.outcome == 'completed' else 1)
        return 0 if run.outcome in ('completed', 'partial', 'returned', 'stopped') else 1

    def finish(self, run):
        self.summary_lines = self.summary_plain(run)
        self.exit(return_code=self.exit_status(run))

    # ---- summaries -------------------------------------------------------------------------
    def outcomes(self, run):
        """[(component, state, detail)] reported separately, so an optional step's outcome never
        hides or replaces the manager's."""
        ctx = self.ctx
        rows = []
        by_key = {phase.key: phase for phase in run.phases}

        def detail_of(phase, fallback=''):
            if phase.failure is not None:
                return phase.failure.message
            return phase.note or fallback
        if run.action == 'health':
            report = getattr(run, 'report', None) or {}
            counts = report.get('counts') or {}
            state = {0: 'Ready', 1: 'Failed', 2: 'Attention'}.get(report.get('exit_code'), 'Unavailable')
            rows.append(('Health report', state, ' · '.join(f'{counts.get(k, 0)} {k}' for k in ('FAIL', 'WARN', 'SKIP', 'PASS', 'INFO'))
                         + '  (problems first)'))
            order = {'FAIL': 0, 'WARN': 1, 'SKIP': 2, 'PASS': 3}
            checks = [c for c in report.get('checks', []) if isinstance(c, dict) and c.get('status') in order]
            for check in sorted(checks, key=lambda c: order[c.get('status')]):
                rows.append((str(check.get('title', ''))[:60], check.get('status'),
                             str(check.get('detail', '')) + ('  Next: ' + str(check['fix']) if check.get('fix') and
                                                             check.get('status') in ('FAIL', 'WARN', 'SKIP') else '')))
            return rows
        verify = by_key.get('verify')
        if run.action == 'install':
            manager_steps = [p for p in run.phases if p.key in ('admin', 'settings', 'prereqs', 'launch', 'capture', 'verify')]
            if verify is not None and verify.state == engine.COMPLETED:
                rows.append(('Manager', 'Ready', f'{ctx.version} running; HTTP and version checks passed on this VM '
                                                 f'({verify.outcome or ""}).'))
            else:
                failed = next((p for p in manager_steps if p.state == engine.FAILED), None)
                stopped = next((p for p in manager_steps if p.state in (engine.STOPPED, engine.NOT_STARTED, engine.PENDING)), None)
                if failed is not None:
                    rows.append(('Manager', 'Failed', f'Stopped at {failed.label}: {detail_of(failed)}'))
                else:
                    rows.append(('Manager', 'Stopped', f'Not verified; {stopped.label if stopped else "a phase"} did not run.'))
        names = {'capture': 'Browser Wireshark', 'engineer': 'VS Code access', 'lazydocker': 'lazydocker', 'git': 'Git'}
        for key, name in names.items():
            phase = by_key.get(key)
            if phase is None:
                if run.action == 'install' and key == 'engineer':
                    rows.append((name, 'Not selected', 'Skipped by the advanced settings.'))
                if run.action == 'install' and key == 'git':
                    rows.append((name, 'Not selected', 'Chosen for later: Git setup / repair from the dashboard, or '
                                                       'bash deploy/install.sh --git.'))
                continue
            state = phase.state
            if key == 'git' and state == engine.SKIPPED:
                state = 'Attention'
            detail = detail_of(phase)
            if key == 'lazydocker' and phase.outcome:
                detail = phase.outcome[1]
            if key == 'engineer' and state == engine.COMPLETED:
                detail = 'Reconnect SSH, and in VS Code run "Remote-SSH: Kill VS Code Server on Host..." before using the extension.'
            if key == 'git' and state == engine.COMPLETED:
                detail = 'In the manager, connect the registered checkout to your lab.'
            rows.append((name, {'Completed': 'Completed', 'Failed': 'Failed'}.get(state, state), detail))
        return rows

    def next_steps(self, run):
        ctx = self.ctx
        steps = []
        if run.action == 'install':
            verify = run.phase('verify')
            if verify is not None and verify.state == engine.COMPLETED:
                _, port = probes.manager_address(ctx.source)
                addresses = vm_addresses()
                where = ', '.join(f'http://{address}:{port}/' for address in addresses[:3]) or f'http://<VM address>:{port}/'
                steps.append(f'From your workstation open the manager at the VM\'s address: {where}. Verified only on '
                             'this VM; reachability from your workstation depends on your network and firewall.')
                steps.append('In VM connection use clab-discovery and the password you created. Verify the host fingerprint.')
        if run.action in ('install', 'engineer'):
            engineer = run.phase('engineer')
            if engineer is not None and engineer.state == engine.COMPLETED:
                steps.append('Reconnect your SSH session (and the VS Code server) so the new groups apply.')
        capture = run.phase('capture')
        if capture is not None and capture.state == engine.COMPLETED:
            steps.append('Wireshark opens from the map (Capture packets).')
        if run.outcome in ('returned', 'failed', 'stopped', 'interrupted'):
            steps.append('Completed phases are kept. Run the action again from the dashboard: it checks the actual '
                         'system state and repeats only what is needed.')
        steps.append('Full installation health report (without sudo): bash ' + str(Path(ctx.source) / 'deploy/check-install.sh'))
        return steps

    def summary_renderable(self, run):
        look = self.ctx.look
        word = OUTCOME_WORDS.get(run.outcome, 'Stopped')
        headline = Text()
        headline.append_text(look.badge(word))
        title = 'Check installation' if run.action == 'health' else ACTION_LABELS[run.action]
        headline.append(f'  {title}', style=Style(bold=True))
        if run.started:
            headline.append(f'   {clock((run.finished_at or time.time()) - run.started)} elapsed',
                            style=Style(color=None if look.no_color else T['slate-dim']))
        if run.hangup:
            headline.append(f'\n{run.hangup.reason}', style=Style(color=None if look.no_color else T['slate-warning']))
        table = Table.grid(padding=(0, 1), expand=True)
        table.add_column(width=24, no_wrap=True, overflow='ellipsis')
        table.add_column(width=15, no_wrap=True)
        table.add_column(ratio=1, overflow='fold')
        for name, state, detail in self.outcomes(run):
            table.add_row(look.text(name), look.badge(state, 13), Text(detail or '', style=Style(color=None if look.no_color else T['slate-muted'])))
        heading = Text('\nNEXT STEPS', style=Style(color=None if look.no_color else T['slate-accent'], bold=True))
        steps = Table.grid(padding=(0, 1))
        steps.add_column(width=2, no_wrap=True, justify='right')
        steps.add_column(ratio=1)
        for line in self.next_steps(run):
            steps.add_row(Text(look.glyph('bullet'), style=Style(color=None if look.no_color else T['slate-dim'])),
                          Text(line, style=Style(color=None if look.no_color else T['slate-muted'])))
        return Group(headline, Text(''), table, heading, steps)

    def summary_plain(self, run):
        title = 'Check installation' if run.action == 'health' else ACTION_LABELS[run.action]
        lines = [f'Containerlab Node Manager setup — {title}: {OUTCOME_WORDS.get(run.outcome, "Stopped").upper()}']
        width = max((len(name) for name, _, _ in self.outcomes(run)), default=8)
        for name, state, detail in self.outcomes(run):
            lines.append(f'  {name.ljust(width)}  {theme.BADGES.get(state, (state.upper(),))[0]:<13} {detail}'.rstrip())
        lines.append('Next steps:')
        lines.extend('  - ' + line for line in self.next_steps(run))
        return lines


def vm_addresses():
    """This VM's non-loopback IPv4 addresses (candidates only; reachability is not verified)."""
    import subprocess
    try:
        result = subprocess.run(['hostname', '-I'], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, text=True, timeout=3)
        candidates = result.stdout.split()
    except (OSError, subprocess.SubprocessError):
        candidates = []
    import ipaddress
    addresses = []
    for value in candidates:
        try:
            address = ipaddress.ip_address(value)
        except ValueError:
            continue
        if address.version == 4 and not address.is_loopback and not address.is_link_local:
            if not str(address).startswith('172.') or not address.is_private:
                addresses.append(str(address))
            elif not any(str(address).startswith(prefix) for prefix in ('172.17.', '172.18.', '172.19.', '172.20.')):
                addresses.append(str(address))
    return addresses


class Bridge:
    """The run thread's view of the screen. Every call is marshalled onto the event loop and
    blocks until handled; once the screen is gone the calls become harmless no-ops."""

    def __init__(self, app):
        self.app = app
        self.alive = True
        self.decisions = queue.Queue()

    FAILED = object()

    def _call(self, method, *args):
        """Run `method` on the event loop and wait for it, but never forever: the wait is polled
        and abandoned once the screen is gone. Returns Bridge.FAILED if it could not run."""
        if not self.alive:
            return self.FAILED
        loop = getattr(self.app, '_loop', None)
        if loop is None or loop.is_closed():
            return self.FAILED
        import asyncio
        import concurrent.futures

        async def invoke():
            # The same context Textual's own call_from_thread sets (active app and message pump).
            with self.app._context():
                return method(*args)
        try:
            future = asyncio.run_coroutine_threadsafe(invoke(), loop)
        except RuntimeError:
            return self.FAILED
        while True:
            try:
                return future.result(timeout=0.5)
            except concurrent.futures.TimeoutError:
                if not self.alive or loop.is_closed() or not self.app.is_running:
                    future.cancel()
                    return self.FAILED
            except Exception:
                return self.FAILED

    def phase_changed(self, phase):
        self._call(self.app.on_bridge_phase, phase.key)

    def output(self, key, lines):
        self._call(self.app.on_bridge_output, key, list(lines))

    def activity(self, text):
        pass

    def handoff(self, title, notice, work):
        if not self.alive:
            return None
        result = self._call(self.app.handoff, title, notice, work)
        return None if result is self.FAILED else result

    def recover(self, phase, failure):
        while not self.decisions.empty():
            self.decisions.get_nowait()
        if self.app.pending_quit:
            return engine.RETURN   # quitting after this phase: do not wait for a choice
        if self._call(self.app.on_bridge_recover, phase.key, failure) is self.FAILED:
            return engine.RETURN   # the choice could not be shown: never leave the run waiting
        while self.alive:
            try:
                return self.decisions.get(timeout=0.5)
            except queue.Empty:
                continue
        return engine.RETURN

    def finished(self, run):
        self._call(self.app.on_bridge_finished)


def detect_look():
    no_color = 'NO_COLOR' in os.environ          # Textual treats an empty NO_COLOR as set too
    import locale
    encoding = (locale.getpreferredencoding(False) or '').lower().replace('-', '')
    ascii_only = os.environ.get('CLAB_INSTALLER_ASCII') == '1' or encoding not in ('utf8',)
    return theme.Look(no_color=no_color, ascii_only=ascii_only)


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(prog='install.sh --tui', description='Full-screen Containerlab Node Manager installer.')
    parser.add_argument('--git', action='store_true')
    parser.add_argument('--advanced', action='store_true')
    args = parser.parse_args(argv)
    if not (sys.__stdin__ and sys.__stdin__.isatty() and sys.__stderr__ and sys.__stderr__.isatty()
            and sys.__stdout__ and sys.__stdout__.isatty()):
        sys.stderr.write('The full-screen installer needs an interactive terminal on stdin, stdout and stderr.\n')
        return UNAVAILABLE_EXIT
    try:
        install = load_install()
        look = detect_look()
        ctx = Context(install, look)
    except (ValueError, OSError) as error:
        sys.stderr.write(f'Setup stopped: {error}\n')
        return 1
    start = 'git' if args.git else ('advanced' if args.advanced else None)
    app = SlateOps(ctx, start_action=start, ansi_color=True if look.no_color else None)
    crashed = None
    try:
        app.run()
    except Exception as error:  # the terminal is restored by Textual; report below
        crashed = error
    run = app.current_run
    if run is not None and run.active:
        # Whatever ended the screen (quit after stop, hang-up, a crash), the active phase is never
        # abandoned or replayed: let it finish, start nothing later, then report.
        if app.bridge is not None:
            app.bridge.alive = False
            app.bridge.decisions.put(engine.RETURN)
        run.disconnect(run.hangup.reason if run.hangup else ('the screen stopped unexpectedly' if crashed else 'quit after the current phase'))
        try:
            print('Finishing the current phase safely before exiting; nothing later starts…', flush=True)
        except OSError:
            pass
        guard = signal.signal(signal.SIGINT, lambda *_: None)   # Ctrl+C here must not lose the record
        try:
            run.thread.join()
        finally:
            signal.signal(signal.SIGINT, guard)
    if crashed is not None and not app.started_any_run:
        try:
            sys.stderr.write(f'The full-screen installer could not continue ({type(crashed).__name__}: {crashed}). '
                             'Nothing was changed.\n')
        except OSError:
            pass
        return UNAVAILABLE_EXIT
    try:
        if app.summary_lines:
            print('\n'.join(app.summary_lines), flush=True)
        elif run is not None and not run.active and run.outcome and (crashed or app.terminal_lost or app.pending_quit):
            print('\n'.join(app.summary_plain(run)), flush=True)
        if crashed is not None:
            print(f'The installer screen stopped unexpectedly ({type(crashed).__name__}). Completed phases are kept; '
                  'rerun bash deploy/install.sh to continue. It was not restarted automatically.', flush=True)
    except OSError:
        pass
    if crashed is not None or app.terminal_lost:
        return 1
    code = app.return_code if app.return_code is not None else 130
    # 75 means "stopped before changing anything"; a helper's own 75 after a run must not say so.
    return 1 if code == UNAVAILABLE_EXIT and app.started_any_run else code
