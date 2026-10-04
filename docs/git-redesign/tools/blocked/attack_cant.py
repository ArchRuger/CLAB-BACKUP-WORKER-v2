"""Attack 7: every Can't save cause of SCENARIOS.md (fixture). For each: set the cause, press Save (or Upload), read the chip
panel's sentence and actions, press the action it offers, clear the cause, and check that the next click succeeds."""
import re
import sys

from blocked import Pass, Session, arguments, expect, fixture, wait_until

N = [0]


def panel(s):
    return re.sub(r'\s+', ' ', s.page.locator('#save-panel').inner_text()) if s.visible('#save-panel') else ''


def close(s):
    for _ in range(4):
        if s.visible('#save-panel') or s.visible('#save-drawer') or s.visible('#load-panel') or s.page.locator('dialog[open]').count():
            s.page.keyboard.press('Escape'); s.page.wait_for_timeout(250)


def edit(s):
    N[0] += 1
    s.action('edit_device', device='ceos', add=['   ip route 10.%d.1.0/24 10.0.0.1' % N[0]])


def settle(s, timeout=40000):
    s.wait_js("!/Saving|Uploading|Updating/.test(document.getElementById('save-chip-text').textContent)", timeout=timeout, what='the chip to settle')
    s.page.wait_for_timeout(800)


def save(s):
    close(s); s.click('#git-save-progress'); s.page.wait_for_timeout(800); settle(s)


def upload(s, P, label):
    close(s); s.click('#save-chip'); s.page.wait_for_timeout(800)
    up = s.page.locator('#save-upload')
    if not up.count(): return False
    try: expect(up).to_be_enabled(timeout=20000)
    except AssertionError: P.tried(label + ': Upload enabled', panel(s)[:300], ok=False, kind='greyed', note='Upload stays disabled', shot=True); return False
    with s.expect_status(409, r'/retry'):
        up.click(); s.page.wait_for_timeout(1500); settle(s)
    return True


def actions(s):
    return [b.inner_text() for b in s.page.locator('#save-panel-body button').all() if b.is_visible()]


def cant(s, P, label, want, want_actions):
    close(s); s.click('#save-chip'); s.page.wait_for_timeout(1000)
    text = panel(s); acts = actions(s)
    ok = bool(re.search(want, text)) and all(a in acts for a in want_actions)
    hit = P.raw_check(text.replace('Details', ''))
    P.tried(label + ': the chip panel', 'chip %r | %s | actions %r' % (s.chip(), text[:300], acts), ok=ok and not hit,
            kind='raw' if hit else 'untrue', note=('raw %r' % hit) if hit else 'want /%s/ and %r' % (want, want_actions), shot=True)
    return acts


def press(s, label):
    b = s.page.locator('#save-panel-body button', has_text=re.compile('^' + re.escape(label) + '$'))
    if not b.count(): return False
    with s.expect_status(409, r'/git/'):
        b.first.click(); s.page.wait_for_timeout(1500)
    return True


def main():
    args = arguments(__doc__)
    with fixture(args.port) as (base, data):
        s = Session(base, args.headed, (args.width, args.height))
        P = Pass(s, 'cant', args.out)
        p = s.page
        s.switch(capture_seconds=1)
        s.open_lab('restore-square')

        # 1 the VM cannot be reached
        edit(s); s.switch(vm_unreachable=True)
        with s.expect_status(409, r'/git/'): save(s)
        cant(s, P, 'vm', r'The lab VM could not be reached', ['Try again', 'Check the VM connection…'])
        if press(s, 'Check the VM connection…'):
            P.tried('vm: Check the VM connection… opens the VM dialog', 'dialog open=%s' % s.visible('dialog[open]'), ok=s.visible('dialog[open]'), kind='nothing', note='no dialog', shot=True)
        close(s); s.switch(vm_unreachable=None)
        s.click('#save-chip'); p.wait_for_timeout(500); press(s, 'Try again'); settle(s)
        P.tried('vm: cleared, Try again', s.chip(), ok='upload' in s.chip(), kind='dead-end', note=s.chip(), shot='upload' not in s.chip())
        # 2 the VM account cannot upload (persistent), then cleared
        s.switch(push_refused=True)
        upload(s, P, 'account/push')
        cant(s, P, 'account (push refused)', r'could not be uploaded|cannot upload', ['Try again'])
        s.switch(push_refused=None)
        press(s, 'Try again'); settle(s)
        P.tried('account: cleared, Try again uploads', 'chip %r toasts %r' % (s.chip(), s.toasts()[-1:]), ok=s.chip().startswith('Saved'), kind='dead-end', note=s.chip())
        # 3 the VM account cannot commit
        edit(s); s.switch(status_problem='identity'); save(s)
        cant(s, P, 'account (identity)', r'cannot upload|account', ['Try again'])
        s.switch(status_problem=None); close(s); s.click('#save-chip'); p.wait_for_timeout(500); press(s, 'Try again'); settle(s)
        P.tried('identity: cleared, Try again (capture reused)', s.chip(), ok='upload' in s.chip(), kind='dead-end', note=s.chip())
        # 4 the remote cannot be reached at upload
        s.switch(remote_unreachable=True); upload(s, P, 'remote')
        cant(s, P, 'remote unreachable', r'could not be reached|could not be uploaded|cannot upload', ['Try again'])
        s.switch(remote_unreachable=None); press(s, 'Try again'); settle(s)
        P.tried('remote: cleared, Try again uploads', s.chip(), ok=s.chip().startswith('Saved'), kind='dead-end', note=s.chip())
        # 5 someone is working in the repository
        for problem in ('staged', 'edits', 'operation'):
            edit(s); s.switch(status_problem=problem)
            with s.expect_status(409, r'/git/'): save(s)
            cant(s, P, 'busy (%s)' % problem, r'Someone is working in this repository', ['Try again', 'Details'])
            s.switch(status_problem=None); press(s, 'Try again'); settle(s)
            P.tried('busy (%s): cleared, Try again' % problem, s.chip(), ok='upload' in s.chip(), kind='dead-end', note=s.chip())
            upload(s, P, 'busy upload'); close(s)
        # 6 the online copy is ahead, nothing waits: the shortcut and the real thing
        s.switch(status_problem='diverged'); edit(s)
        with s.expect_status(409, r'/git/'): save(s)
        acts = cant(s, P, 'diverged, nothing waits', r'online copy has changes', ['Update from the repository'])
        s.switch(status_problem=None)
        if press(s, 'Update from the repository'):
            dlg = p.locator('#git-update-confirm')
            if dlg.count() and dlg.is_visible(): dlg.click(); p.wait_for_timeout(2000)
            P.tried('diverged: Update from the repository', 'chip %r toasts %r dialog %s' % (s.chip(), s.toasts()[-2:], s.visible('dialog[open]')), shot=True)
            close(s)
        save(s)
        P.tried('diverged: cleared, Save', s.chip(), ok='upload' in s.chip() or s.chip().startswith('Saved'), kind='dead-end', note=s.chip())
        upload(s, P, 'after diverged'); close(s)
        s.switch(remote_ahead=True); edit(s); save(s)
        P.tried('remote ahead, nothing waits: Save fast-forwards first', 'chip %r' % s.chip(), ok='upload' in s.chip(), kind='dead-end', note=s.chip())
        upload(s, P, 'after remote ahead'); close(s)
        P.tried('remote ahead: the upload after the fast-forward', 'chip %r toasts %r' % (s.chip(), s.toasts()[-1:]), ok=s.chip().startswith('Saved'), kind='dead-end', note=s.chip(), shot=not s.chip().startswith('Saved'))
        # 7 the same while saves wait
        edit(s); save(s); s.switch(remote_ahead=True); upload(s, P, 'diverged with waiting')
        acts = cant(s, P, 'diverged, saves wait', r'both have changes', ['Details'])
        cmds = p.locator('#save-panel-body code').all_inner_texts()
        P.tried('diverged with saves waiting: the owner\'s commands shown', str(cmds), ok=any('pull' in c for c in cmds), kind='dead-end', note='no commands', shot=True)
        s.switch(remote_ahead=None)
        # what a person can do from here in the page: Try again keeps failing until the VM is merged (outside, PROMPT 6.5)
        press(s, 'Try again'); settle(s)
        P.tried('diverged with saves waiting: Try again (remote_ahead cleared, the VM still lacks the commit)', 'chip %r' % s.chip(), shot=True)
        close(s)
        # 8 files the manager did not save
        edit(s); s.switch(status_problem='files')
        with s.expect_status(409, r'/git/'): save(s)
        cant(s, P, 'files', r'holds files that were not saved by the manager', ['Choose another place', 'Details'])
        if press(s, 'Choose another place'):
            P.tried('files: Choose another place opens the chooser', 'drawer=%s' % s.visible('#folder-tree'), ok=s.visible('#save-drawer'), kind='nothing', note='no chooser', shot=True)
        close(s); s.switch(status_problem=None)
        s.click('#save-chip'); p.wait_for_timeout(500); press(s, 'Try again'); settle(s)
        P.tried('files: cleared, Try again', s.chip(), ok='upload' in s.chip() or s.chip().startswith('Saved'), kind='dead-end', note=s.chip())
        # 9 the save location has to be set up again
        edit(s); s.switch(status_problem='settings')
        with s.expect_status(409, r'/git/'): save(s)
        cant(s, P, 'settings', r'save location has to be set up again', ['Save settings'])
        if press(s, 'Save settings'):
            P.tried('settings: Save settings opens the drawer', re.sub(r'\s+', ' ', p.locator('#save-drawer').inner_text())[:300] if s.visible('#save-drawer') else 'no drawer',
                    ok=s.visible('#save-drawer'), kind='nothing', note='no drawer', shot=True)
        close(s); s.switch(status_problem=None); save(s)
        P.tried('settings: cleared, Save', s.chip(), ok='upload' in s.chip() or s.chip().startswith('Saved'), kind='dead-end', note=s.chip())
        # 10 a device cannot be read: leave it out in Save settings
        edit(s); s.switch(device_unreadable=['xrv9k']); save(s)
        cant(s, P, 'device', r'xrv9k could not be read', ['Try again', 'Save settings'])
        if press(s, 'Save settings'):
            p.wait_for_timeout(2000)
            box = p.locator('#save-drawer input[name="git-node"][value*="xrv9k"]')
            if box.count():
                box.uncheck(); p.locator('#save-drawer [data-save-action="save-settings"]').click(); p.wait_for_timeout(3000)
                note = re.sub(r'\s+', ' ', p.locator('#save-drawer').inner_text())[:300] if s.visible('#save-drawer') else ''
                P.tried('device: left out in Save settings', note, ok='updated' in note or not s.visible('#save-drawer'), kind='dead-end', note=note[:200], shot=True)
        close(s); save(s)
        P.tried('device left out: Save', s.chip(), ok='upload' in s.chip() or s.chip().startswith('Saved'), kind='dead-end', note=s.chip(), shot=True)
        s.switch(device_unreadable=None)
        # 11 no save at HEAD (a hand commit)
        edit(s); save(s); s.action('hand_commit', repository='Nested-Labs')
        upload(s, P, 'hand commit'); p.wait_for_timeout(1000)
        text = panel(s)
        P.tried('a hand commit: what Upload says', text[:400], ok=bool(re.search(r'Someone is working|changes the manager did not make|Another save', text)), kind='untrue', note=text[:200], shot=True)
        close(s)
        # 12 something unlisted
        edit(s); s.switch(status_problem='The checkout is haunted.')
        with s.expect_status(409, r'/git/'): save(s)
        cant(s, P, 'other', r'The save did not work', ['Try again', 'Details'])
        if press(s, 'Details'):
            P.tried('other: Details shows the sentence', re.sub(r'\s+', ' ', p.locator('body').inner_text())[-400:], ok='haunted' in p.locator('body').inner_text(), kind='nothing', note='sentence not shown', shot=True)
        close(s); s.switch(status_problem=None)
        s.finish()
        return P.summary()


if __name__ == '__main__':
    sys.exit(main())
