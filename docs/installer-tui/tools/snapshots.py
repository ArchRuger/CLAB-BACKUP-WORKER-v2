"""Render FIXTURE screenshots of every Slate Ops screen (SVG, optionally PNG).

    <tui-venv>/bin/python docs/installer-tui/tools/snapshots.py [out_dir] [--png]

Uses tools/fixture.py: invented account/host/status, a scripted run; nothing on the VM
is probed or changed. Each file name carries its size and colour mode.
"""
import asyncio
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fixture  # noqa: E402
from installer_tui import app as slate, engine  # noqa: E402

SIZES = [(80, 24), (120, 40), (160, 50)]


class ScriptedBridge(slate.Bridge):
    pass


def scripted_run(ctx, action='install', upto=3, fail_key=None, kind='command'):
    """A finished-looking Run object with phase states set directly (no thread, no commands)."""
    run = engine.Run(ctx.install, action, ctx.env, ctx.version, options=ctx.options)
    import time
    now = time.monotonic()
    run.started = time.time() - 412
    for index, phase in enumerate(run.phases):
        if index < upto:
            phase.state = engine.COMPLETED
            phase.started, phase.finished = now - 400 + index * 50, now - 360 + index * 50
            phase.attempts = 1
            phase.code = 0
        elif index == upto:
            phase.started = now - 61
            phase.attempts = 1
            if fail_key:
                phase.state = engine.FAILED
                phase.finished = now - 2
        else:
            phase.state = engine.PENDING
    return run


async def shoot(out, name, ctx, size, steps):
    app = fixture.make_app(ctx)
    async with app.run_test(size=size) as pilot:
        await pilot.pause(0.3)
        for step in steps:
            await step(app, pilot)
            await pilot.pause(0.2)
        await pilot.pause(0.3)
        target = out / f'{name}-{size[0]}x{size[1]}.svg'
        app.save_screenshot(filename=target.name, path=str(out))
        return target


async def nothing(app, pilot):
    pass


async def tab(app, pilot):
    await pilot.press('tab')


async def down2(app, pilot):
    await pilot.press('down', 'down')


async def status_focus(app, pilot):
    await pilot.press('tab', 'tab', 'down')   # nav -> details -> status, then the Manager row


async def review(app, pilot):
    await pilot.press('enter')


async def settings(app, pilot):
    await pilot.press('down', 'down', 'down', 'down', 'down', 'enter')


async def helpdlg(app, pilot):
    await pilot.press('question_mark')


def run_screen(upto, fail=False, lock=False):
    async def step(app, pilot):
        run = scripted_run(app.ctx, upto=upto, fail_key='x' if fail or lock else None)
        app.current_run = run
        screen = slate.RunScreen(run)
        await app.push_screen(screen)
        await pilot.pause(0.2)
        for phase in run.phases[:upto + 1]:
            screen.add_lines(phase.key, [f'── {phase.label} ──'] + [
                f'{phase.label}: sample output line {i} (fixture)' for i in range(1, 6)])
        run.current = run.phases[upto]
        if run.phases[upto].state == engine.PENDING:
            run.phases[upto].state = engine.RUNNING
        run.thread = type('T', (), {'is_alive': lambda self: True})()
        for phase in run.phases:
            screen.render_phase(phase)
        screen.render_summary()
        screen.update_footer()   # the stub thread now reads as active: show the running-phase keys
        screen.query_one('#phases').index = upto   # a live run moves the highlight with the phase
        if lock:
            install = app.ctx.install
            failure = engine.Failure('lock', 'The package manager (APT/dpkg) is locked by another process.', 100,
                                     choices=(engine.LOCK_WAIT, engine.RETRY, engine.LOCK_CHECK, engine.RETURN),
                                     holder='Package lock held by pid 2230 (unattended-upgr) on /var/lib/dpkg/lock-frontend.\n'
                                            'Never stop unattended-upgrades.service, kill this process, or delete the lock file.')
            run.phases[upto].failure = failure
            screen.show_recovery(run.phases[upto].key, failure)
        elif fail:
            failure = engine.Failure('command', 'The step stopped with exit status 1. Completed setup and existing data are retained.', 1)
            run.phases[upto].failure = failure
            screen.show_recovery(run.phases[upto].key, failure)
        screen.render_activity()
    return step


def result_screen(partial=True):
    async def step(app, pilot):
        run = scripted_run(app.ctx, upto=len(engine.Run(app.ctx.install, 'install', app.ctx.env, app.ctx.version).phases))
        run.finished_at = run.started + 1312
        verify = run.phase('verify')
        verify.outcome = 'http://127.0.0.1:8081/'
        if partial:
            git = run.phase('git')
            git.state = engine.SKIPPED
            git.note = 'not completed; run it again later from the dashboard'
            git.code = 2
            lazy = run.phase('lazydocker')
            lazy.state = engine.SKIPPED
            lazy.outcome = ('skipped', 'network unreachable (fixture)')
            run.outcome = 'partial'
        else:
            run.outcome = 'completed'
            run.phase('lazydocker').outcome = ('installed', 'lazydocker 0.24.1 installed to /home/student/.local/bin/lazydocker.')
        run.thread = None
        app.current_run = run
        slate.vm_addresses = lambda: ['192.0.2.10']
        await app.push_screen(slate.ResultScreen(run))
    return step


SCENES = [
    ('dashboard', [nothing]),
    ('dashboard-detail-focus', [down2, tab]),
    ('dashboard-status-focus', [status_focus]),
    ('review-install', [review]),
    ('settings', [settings]),
    ('help', [helpdlg]),
    ('run-progress', [run_screen(3)]),
    ('run-failed', [run_screen(3, fail=True)]),
    ('run-lock', [run_screen(1, lock=True)]),
    ('result-partial', [result_screen(True)]),
    ('result-completed', [result_screen(False)]),
]


async def main():
    out = Path(sys.argv[1]) if len(sys.argv) > 1 and not sys.argv[1].startswith('--') else \
        Path(__file__).resolve().parents[1] / 'snapshots'
    out.mkdir(parents=True, exist_ok=True)
    png = '--png' in sys.argv
    only = [arg.split('=', 1)[1] for arg in sys.argv if arg.startswith('--only=')]
    files = []
    for name, steps in SCENES:
        if only and name not in only:
            continue
        for size in SIZES:
            files.append(await shoot(out, name, fixture.context(scrub=True), size, steps))
    import os
    for mode, kwargs in (('nocolor', {'no_color': True}), ('ascii', {'ascii_only': True})):
        if only and 'dashboard' not in only:
            continue
        if mode == 'nocolor':
            os.environ['NO_COLOR'] = '1'   # Textual picks its monochrome filter at construction
        try:
            files.append(await shoot(out, f'dashboard-{mode}', fixture.context(scrub=True, **kwargs), (100, 30), [nothing]))
        finally:
            os.environ.pop('NO_COLOR', None)
    if png and shutil.which('rsvg-convert'):
        for svg in files:
            subprocess.run(['rsvg-convert', '-b', '#0F172A', '-o', str(svg.with_suffix('.png')), str(svg)], check=False)
    print('\n'.join(str(f) for f in files))


if __name__ == '__main__':
    asyncio.run(main())
