"""Attack 6: loading (fixture). A state whose devices do not match the lab, a state with no restore files, loading while a save runs
and saving while a load runs, Undo twice, a lab that stops between the confirmation and Load."""
import re
import sys

from blocked import Pass, Session, arguments, expect, fixture, wait_until


def lp(s):
    return re.sub(r'\s+', ' ', s.page.locator('#load-panel').inner_text()) if s.visible('#load-panel') else ''


def close(s):
    for _ in range(3):
        if s.visible('#load-panel') or s.visible('#save-panel') or s.visible('#save-drawer'): s.page.keyboard.press('Escape'); s.page.wait_for_timeout(250)


def open_load(s):
    close(s)
    s.click('#load-button')
    s.wait_js("!!document.querySelector('#load-panel [data-load-row], #load-panel .save-state')", timeout=20000, what='the load panel')
    s.page.wait_for_timeout(1200)


def row(s, name):
    rows = s.page.locator('#load-panel [data-load-row]')
    for i in range(rows.count()):
        if rows.nth(i).inner_text().split('\n')[0].strip().startswith(name): return rows.nth(i)
    return None


def confirm_for(s, P, name, label):
    """Opens the confirmation for the state `name`; returns the confirmation text, or '' with a suspect recorded."""
    open_load(s)
    r = row(s, name)
    if r is None:
        P.tried(label + ': the row', lp(s)[:300], ok=False, kind='dead-end', note='no row named %s' % name, shot=True); return ''
    r.click()
    try: s.wait_js("!!document.getElementById('load-run')||/cannot be loaded|can be loaded in a moment|View only|Start the lab/.test(document.getElementById('load-panel').textContent)", timeout=30000)
    except AssertionError: pass
    s.page.wait_for_timeout(800)
    return lp(s)


def main():
    args = arguments(__doc__)
    with fixture(args.port) as (base, data):
        s = Session(base, args.headed, (args.width, args.height))
        P = Pass(s, 'load', args.out)
        p = s.page
        s.switch(capture_seconds=1, restore_capture_seconds=1)

        # a state whose devices do not match: square-fresh with Big-Repo's states (0 of 4), and Junos-only for restore-square
        s.open_lab('square-fresh')
        s.switch(list_first='Big-Repo'); s.action('prefer_repository', repository='Big-Repo')
        open_load(s)
        P.tried('square-fresh: the Load list', lp(s)[:400], shot=True)
        text = confirm_for(s, P, 'Final', 'square-fresh loads a state of other devices')
        run = p.locator('#load-run')
        why = p.locator('#load-run-reason').inner_text() if s.visible('#load-run-reason') else ''
        P.tried('a state none of whose devices are in the lab: the confirmation', text[:400],
                ok=not (run.count() and run.is_disabled() and not why and 'None of the devices' not in text), kind='greyed', note='Load disabled without a reason', shot=True)
        close(s)
        s.open_lab('restore-square')
        text = confirm_for(s, P, 'Junos-only', 'restore-square loads Junos-only')
        P.tried('a state of 2 of 4 devices: the confirmation', text[:400], ok='Not in this state' in text, kind='untrue', note=text[:200], shot=True)
        close(s)

        # a state with no restore files (Start): what the row does
        open_load(s)
        r = row(s, 'Start')
        if r is not None:
            enabled = r.is_enabled(); r.click(); p.wait_for_timeout(1500)
            P.tried('a state with no restore files (Start)', 'row enabled=%s; after click: %s' % (enabled, lp(s)[:300]),
                    ok=bool(re.search(r'View only|without the files|View', lp(s))), kind='dead-end', note=lp(s)[:200], shot=True)
        close(s)

        # loading while a save runs
        s.switch(capture_seconds=20)
        s.action('edit_device', device='ceos', add=['   ip route 10.9.0.0/16 10.0.0.1'])
        s.click('#git-save-progress'); p.wait_for_timeout(1500); close(s)
        load_disabled = p.locator('#load-button').is_disabled()
        text = confirm_for(s, P, 'Final', 'load while a save runs') if not load_disabled else ''
        why = p.locator('#load-run-reason').inner_text() if s.visible('#load-run-reason') else ''
        P.tried('loading while a save runs', 'Load button disabled=%s; confirmation: %s | reason %r' % (load_disabled, text[:200], why),
                ok=load_disabled or 'A save is running' in (text + why), kind='greyed', note='no reason shown', shot=True)
        close(s)
        s.wait_chip(r'save to upload|Saved', timeout=60000)
        s.switch(capture_seconds=1)

        # saving while a load runs
        s.switch(load_preset='slow', load_seconds=3)
        text = confirm_for(s, P, 'Final', 'start a slow load')
        if s.visible('#load-run'):
            expect(p.locator('#load-run')).to_be_enabled(timeout=20000); p.locator('#load-run').click(); p.wait_for_timeout(2000)
            close(s)
            save = p.locator('#git-save-progress')
            reason = p.locator('#save-reason').inner_text() if s.visible('#save-reason') else ''
            P.tried('saving while a load runs', 'Save disabled=%s; reason %r; chip %r' % (save.is_disabled(), reason, s.chip()),
                    ok=(not save.is_disabled()) or bool(reason) or s.chip().startswith('Loading'), kind='greyed', note='Save disabled without a visible reason', shot=True)
            s.wait_js("!/Loading/.test(document.getElementById('save-chip-text').textContent)", timeout=90000, what='the load to end')
        s.switch(load_preset=None)
        P.tried('after the slow load: chip', s.chip(), ok=s.chip().startswith('Running'), kind='untrue', note=s.chip())

        # Undo twice
        for n in (1, 2):
            close(s)
            s.click('#load-button'); p.wait_for_timeout(1500)
            undo = p.locator('#load-undo')
            if not undo.count():
                P.tried('Undo #%d: offered' % n, lp(s)[:300], ok=False, kind='dead-end', note='no Undo this load', shot=True); break
            if undo.is_disabled():
                P.tried('Undo #%d: offered' % n, lp(s)[:300], ok=bool(re.search(r'Available when|not|cannot', lp(s))), kind='greyed', note='Undo disabled: ' + lp(s)[:200], shot=True); break
            undo.click(); p.wait_for_timeout(2500)
            if s.visible('#load-run'):
                expect(p.locator('#load-run')).to_be_enabled(timeout=20000); p.locator('#load-run').click()
                s.wait_js("!/Loading/.test(document.getElementById('save-chip-text').textContent)", timeout=90000)
                p.wait_for_timeout(1500)
                P.tried('Undo #%d' % n, 'chip %r; toasts %r' % (s.chip(), s.toasts()[-2:]), ok=not re.search(r'did not|failed', ' '.join(s.toasts()[-2:])), kind='dead-end', note=str(s.toasts()[-2:]), shot=True)
            else:
                P.tried('Undo #%d: the confirmation' % n, lp(s)[:300], ok=False, kind='dead-end', note='no Load in the undo confirmation', shot=True); break

        # a lab that stops between the confirmation and Load
        text = confirm_for(s, P, 'Broken', 'stop in between')
        s.action('lab_state', lab='restore-square', state='stopped'); p.wait_for_timeout(5000)
        run = p.locator('#load-run')
        state = 'Load disabled=%s, reason %r' % (run.is_disabled() if run.count() else None, p.locator('#load-run-reason').inner_text() if s.visible('#load-run-reason') else '')
        with s.expect_status(409, r'/restore'), s.expect_status(400, r'/restore'):
            if run.count() and run.is_enabled(): run.click(); p.wait_for_timeout(5000)
        after = lp(s)
        P.tried('the lab stops between the confirmation and Load', '%s | after: %s | chip %r' % (state, after[:300], s.chip()),
                ok=not P.raw_check(after) and not re.search(r'Loaded on', after), kind='untrue', note=after[:200], shot=True)
        s.action('lab_state', lab='restore-square', state='running')
        close(s)
        s.finish()
        return P.summary()


if __name__ == '__main__':
    sys.exit(main())
