"""A small probe for one flow, used to look closer at a suspect of the attack scripts (fixture evidence only).

    ~/pw-venv/bin/python docs/git-redesign/tools/blocked/probe.py --port 8196 <name>
"""
import re
import sys

from blocked import Pass, Session, expect, fixture, wait_until, settle_question3
from folder_flow import open_chooser, repository, place_of, answer, foot_buttons


def connect_by_url(s, P):
    p = s.page
    s.switch(capture_seconds=1)
    s.open_lab('edge-lab')
    open_chooser(s)
    p.locator('.folder-chooser [data-folder-action="address-on"]').click(); p.wait_for_timeout(500)
    P.tried('address mode: what the chooser shows', re.sub(r'\s+', ' ', p.locator('#save-drawer').inner_text())[:500], shot=True)
    p.locator('#folder-url').fill('https://github.com/ArchRuger/Spare-Lab.git'); p.wait_for_timeout(300)
    buttons = [(b.inner_text(), b.get_attribute('data-folder-action'), b.get_attribute('data-folder-primary'), b.is_enabled()) for b in p.locator('#folder-foot button').all()]
    P.tried('address mode: the buttons', str(buttons))
    sent = len(s.sent)
    p.locator('#folder-foot [data-folder-primary]').click()
    p.wait_for_timeout(6000)
    P.tried('address mode: after the click', 'drawer visible=%s; text=%r; sent=%r; place=%s; toasts=%r' % (
        s.visible('#save-drawer'), re.sub(r'\s+', ' ', p.locator('#save-drawer').inner_text())[:300] if s.visible('#save-drawer') else '',
        [c[:200] for c in s.sent[sent:]], place_of(s, 'edge-lab'), s.toasts()), shot=True)


def new_folder_answer(s, P):
    p = s.page
    s.open_lab('shared-b')
    s.click('#git-save-progress'); expect(p.locator('#save-first-place-other')).to_be_visible(timeout=20000)
    open_chooser(s); repository(s, 'Nested-Labs')
    for parent, name in [('', 'a/b/c'), ('', 'NOTES'), ('BGP', 'my lab'), ('', 'latest'), ('BGP', 'latest'), ('BGP', 'README.md')]:
        p.locator('#folder-path').fill(parent); answer(s)
        p.locator('.folder-chooser [data-folder-action="new"]').click()
        p.locator('#folder-new').fill(name)
        sent = len(s.sent)
        p.locator('.folder-new [data-folder-action="new-add"]').click()
        p.wait_for_timeout(4000)
        P.tried('New folder… %r in %r' % (name, parent or 'top'), 'field=%r | answer=%r | result=%r | sent=%r' % (
            p.locator('#folder-path').input_value(), p.locator('#folder-answer').inner_text(), p.locator('#folder-result').inner_text().replace('\n', ' '),
            [c[:220] for c in s.sent[sent:]]), shot=True)


def panel_text(s):
    return re.sub(r'\s+', ' ', s.page.locator('#save-panel').inner_text()) if s.visible('#save-panel') else ''


def settle(s, timeout=60000):
    s.wait_js("!/Saving|Uploading|Updating|Loading/.test(document.getElementById('save-chip-text').textContent)", timeout=timeout)
    s.page.wait_for_timeout(1500)


def close(s):
    for _ in range(4):
        if s.visible('#save-panel') or s.visible('#save-drawer') or s.visible('#load-panel'): s.page.keyboard.press('Escape'); s.page.wait_for_timeout(250)


def press_panel(s, label):
    b = s.page.locator('#save-panel-body button', has_text=re.compile('^' + re.escape(label) + '$'))
    if not b.count(): return False
    b.first.click(); s.page.wait_for_timeout(1500); return True


def push_refused_try_again(s, P):
    """After a refused upload: what Try again in the chip panel does once the cause is cleared."""
    p = s.page
    s.switch(capture_seconds=1)
    s.open_lab('restore-square')
    s.action('edit_device', device='ceos', add=['   ip route 10.77.0.0/16 10.0.0.1'])
    s.click('#git-save-progress'); settle(s); close(s)
    s.switch(push_refused=True)
    s.click('#save-chip'); expect(p.locator('#save-upload')).to_be_enabled(timeout=20000)
    with s.expect_status(409, r'/retry'):
        p.locator('#save-upload').click(); settle(s)
    close(s); s.click('#save-chip'); p.wait_for_timeout(800)
    P.tried('push refused: the chip and its panel', 'chip %r | %s' % (s.chip(), panel_text(s)[:300]), shot=True)
    s.switch(push_refused=None)
    jobs_before = len(s.api_state()['git_jobs']); captures_before = len(s.api_state()['jobs'])
    sent = len(s.sent)
    press_panel(s, 'Try again'); settle(s)
    st = s.api_state()
    P.tried('push refused, cleared: Try again', 'chip %r | requests %r | new git jobs %d | new captures %d | toasts %r' % (
        s.chip(), [c[:120] for c in s.sent[sent:]], len(st['git_jobs']) - jobs_before, len(st['jobs']) - captures_before, s.toasts()[-2:]),
        ok=s.chip().startswith('Saved'), kind='untrue', note='Try again did not upload', shot=True)
    close(s); s.click('#save-chip'); p.wait_for_timeout(800)
    P.tried('push refused, after Try again: the panel', 'chip %r | %s' % (s.chip(), panel_text(s)[:300]), shot=True)
    if press_panel(s, 'Try again'): settle(s)
    P.tried('push refused: the second Try again', 'chip %r toasts %r' % (s.chip(), s.toasts()[-2:]))


def identity_try_again(s, P):
    p = s.page
    s.switch(capture_seconds=1)
    s.open_lab('restore-square')
    s.action('edit_device', device='ceos', add=['   ip route 10.78.0.0/16 10.0.0.1'])
    s.switch(status_problem='identity')
    s.click('#git-save-progress'); settle(s); close(s)
    s.click('#save-chip'); p.wait_for_timeout(800)
    P.tried('identity: the panel', 'chip %r | %s' % (s.chip(), panel_text(s)[:300]), shot=True)
    s.switch(status_problem=None)
    sent = len(s.sent)
    press_panel(s, 'Try again'); settle(s)
    close(s); s.click('#save-chip'); p.wait_for_timeout(800)
    P.tried('identity cleared: Try again', 'chip %r | requests %r | %s' % (s.chip(), [c[:120] for c in s.sent[sent:]], panel_text(s)[:300]),
            ok='upload' in s.chip(), kind='dead-end', note=s.chip(), shot=True)


def undo_twice(s, P):
    p = s.page
    s.switch(capture_seconds=1, restore_capture_seconds=1)
    s.open_lab('restore-square')
    s.click('#load-button'); p.wait_for_timeout(2500)
    rows = p.locator('#load-panel [data-load-row]')
    target = [i for i in range(rows.count()) if rows.nth(i).inner_text().startswith('Final')][0]
    rows.nth(target).click(); expect(p.locator('#load-run')).to_be_enabled(timeout=30000); p.locator('#load-run').click()
    settle(s, 90000)
    for n in (1, 2, 3):
        close(s); s.click('#save-chip'); p.wait_for_timeout(1500)
        undo = p.locator('#load-undo')
        P.tried('undo %d: the chip panel' % n, 'chip %r | %s | undo %s' % (s.chip(), panel_text(s)[:300], undo.count() and (undo.is_enabled() and 'enabled' or 'disabled')), shot=True)
        if not undo.count() or not undo.is_enabled(): break
        undo.click(); p.wait_for_timeout(3000)
        if s.visible('#load-run'):
            expect(p.locator('#load-run')).to_be_enabled(timeout=30000); p.locator('#load-run').click(); settle(s, 90000)
            P.tried('undo %d: done' % n, 'chip %r toasts %r' % (s.chip(), s.toasts()[-1:]))
        else:
            P.tried('undo %d: the confirmation' % n, re.sub(r'\s+', ' ', p.locator('#load-panel').inner_text())[:300] if s.visible('#load-panel') else 'nothing open', ok=False, kind='dead-end', note='no Load', shot=True)
            break


def keep_older_checkpoint(s, P):
    p = s.page
    s.switch(capture_seconds=1)
    s.open_lab('restore-square')
    for k in (1, 2):
        s.action('edit_device', device='ceos', add=['   ip route 10.9%d.0.0/16 10.0.0.1' % k])
        s.click('#git-save-progress'); settle(s); close(s)
    s.click('#save-chip'); s.click('#save-all'); p.wait_for_timeout(3000)
    names = p.locator('#save-drawer .save-item').all_inner_texts()
    P.tried('All versions: rows', str([n[:40] for n in names][:8]), shot=True)
    items = p.locator('#save-drawer .save-item')
    # the second row of Your saves: an older save
    items.nth(1).click(); p.wait_for_timeout(1000)
    ck = p.locator('#save-drawer [data-save-action="checkpoint"]')
    P.tried('older save: Keep as a checkpoint', '%d buttons, enabled %s | %s' % (ck.count(), ck.count() and ck.first.is_enabled(), re.sub(r'\s+', ' ', p.locator('#save-drawer').inner_text())[:300]), shot=True)
    if ck.count() and ck.first.is_enabled():
        ck.first.click(); p.wait_for_timeout(600)
        p.locator('#save-checkpoint-name').fill('older-one'); p.locator('#save-drawer [data-save-action="checkpoint-keep"]').click(); settle(s)
        P.tried('older save kept as a checkpoint while a save waits', 'chip %r toasts %r' % (s.chip(), s.toasts()[-2:]), ok=not s.chip().startswith('Can'), kind='refusal', note=s.chip(), shot=True)
        st = s.fixture_state()
        P.tried('fixture: the repository after it', str(st.get('repositories', {}).get('Nested-Labs', {}))[:300])


def files_try_again(s, P):
    p = s.page
    s.switch(capture_seconds=1)
    s.open_lab('restore-square')
    s.action('edit_device', device='ceos', add=['   ip route 10.79.0.0/16 10.0.0.1'])
    s.switch(status_problem='files')
    with s.expect_status(409, r'/git/'):
        s.click('#git-save-progress'); settle(s)
    close(s); s.click('#save-chip'); p.wait_for_timeout(800)
    P.tried('files: the panel', 'chip %r | %s' % (s.chip(), panel_text(s)[:300]), shot=True)
    s.switch(status_problem=None)
    sent = len(s.sent)
    with s.expect_status(409, r'/git/'):
        press_panel(s, 'Try again'); settle(s)
    close(s); s.click('#save-chip'); p.wait_for_timeout(800)
    P.tried('files cleared: Try again', 'chip %r | requests %r | %s' % (s.chip(), [c[:120] for c in s.sent[sent:]], panel_text(s)[:300]),
            ok='upload' in s.chip(), kind='dead-end', note=s.chip(), shot=True)


def refused_address_then_another(s, P):
    """No repository on the VM: an address that fails to clone, then the person wants to paste another one."""
    p = s.page
    s.switch(capture_seconds=1, no_repositories=True)
    s.open_lab('shared-b')
    s.click('#git-save-progress'); expect(p.locator('#save-url')).to_be_visible(timeout=20000)
    p.locator('#save-url').fill('https://github.com/ArchRuger/missing-x.git')
    with s.expect_status(409, r'/git/place'):
        s.click('#save-first'); p.wait_for_timeout(4000)
    P.tried('a refused address: the panel', 'chip %r | %s' % (s.chip(), panel_text(s)[:400]), shot=True)
    close(s); s.click('#git-save-progress'); p.wait_for_timeout(2500)
    P.tried('Save again after the refusal: the panel', 'url field %s | %s' % (s.visible('#save-url'), panel_text(s)[:400]), shot=True)
    b = p.locator('#save-panel-body button', has_text=re.compile('^Choose another place$'))
    if b.count():
        b.first.click(); p.wait_for_timeout(3000)
        text = re.sub(r'\s+', ' ', p.locator('#save-drawer').inner_text()) if s.visible('#save-drawer') else 'no drawer'
        P.tried('Choose another place with no repository on the VM', text[:400], ok='Repository address' in text or s.visible('#folder-url') or 'Connect by URL' in text, kind='dead-end', note=text[:200], shot=True)
        addr = p.locator('.folder-chooser [data-folder-action="address-on"]')
        if addr.count():
            addr.click(); p.wait_for_timeout(500)
            p.locator('#folder-url').fill('https://github.com/ArchRuger/Spare-Lab.git'); p.wait_for_timeout(300)
            P.tried('the chooser\'s address mode: buttons', str([(x.inner_text(), x.is_enabled()) for x in p.locator('#folder-foot button').all()]))
            with s.expect_status(409, r'/git/place'):
                p.locator('#folder-foot [data-folder-primary]').click(); p.wait_for_timeout(5000)
            P.tried('another address through the chooser', 'drawer %s | chip %r | place %s' % (s.visible('#save-drawer'), s.chip(), place_of(s, 'shared-b')),
                    ok=bool(place_of(s, 'shared-b')), kind='dead-end', note='not placed', shot=True)


def no_repository_chooser(s, P):
    """No repository on the VM: the chooser from Choose another place; what Save here and New folder… do there."""
    p = s.page
    s.switch(capture_seconds=1, no_repositories=True)
    s.open_lab('shared-b')
    s.click('#git-save-progress'); expect(p.locator('#save-url')).to_be_visible(timeout=20000)
    p.locator('#save-url').fill('https://github.com/ArchRuger/missing-x.git')
    with s.expect_status(409, r'/git/place'):
        s.click('#save-first'); p.wait_for_timeout(4000)
    close(s); s.click('#git-save-progress'); p.wait_for_timeout(2500)
    p.locator('#save-panel-body button', has_text=re.compile('^Choose another place$')).first.click(); p.wait_for_timeout(3000)
    s.errors.clear()
    sent = len(s.sent)
    with s.expect_status(422, r'/git/'), s.expect_status(400, r'/git/'), s.expect_status(404, r'/git/'):
        p.locator('#folder-foot [data-folder-primary]').click(); p.wait_for_timeout(3000)
    refused = p.locator('#folder-refused').inner_text() if s.visible('#folder-refused') else ''
    P.tried('no repository: Save here in the chooser', 'refused %r | requests %r' % (refused, [c[:160] for c in s.sent[sent:]]), ok=not refused, kind='refusal', note=refused, shot=True)
    sent = len(s.sent)
    with s.expect_status(422, r'/git/'), s.expect_status(400, r'/git/'), s.expect_status(404, r'/git/'):
        p.locator('.folder-chooser [data-folder-action="new"]').click(); p.locator('#folder-new').fill('x'); p.locator('.folder-new [data-folder-action="new-add"]').click(); p.wait_for_timeout(3000)
    refused = p.locator('#folder-refused').inner_text() if s.visible('#folder-refused') else ''
    P.tried('no repository: New folder… in the chooser', 'refused %r | requests %r' % (refused, [c[:160] for c in s.sent[sent:]]), ok=not refused, kind='refusal', note=refused, shot=True)


def failed_connect_pollutes_chip(s, P):
    """A lab that saves fine tries another repository by address and the clone fails: what its chip says afterwards."""
    p = s.page
    s.switch(capture_seconds=1)
    s.open_lab('edge-lab')
    P.tried('edge-lab before: chip', s.chip())
    open_chooser(s)
    p.locator('.folder-chooser [data-folder-action="address-on"]').click(); p.wait_for_timeout(300)
    p.locator('#folder-url').fill('https://github.com/ArchRuger/missing-x.git'); p.locator('#folder-path').fill('elsewhere'); p.wait_for_timeout(300)
    with s.expect_status(409, r'/git/place'):
        p.locator('#folder-foot [data-folder-primary]').click(); p.wait_for_timeout(5000)
    P.tried('the refusal in the chooser', p.locator('#folder-refused').inner_text() if s.visible('#folder-refused') else '', shot=True)
    close(s); p.wait_for_timeout(1500)
    chip = s.chip()
    s.click('#save-chip'); p.wait_for_timeout(800)
    P.tried('edge-lab after the failed connect: chip and panel (its own place BGP/edge is untouched)', 'chip %r | %s' % (chip, panel_text(s)[:300]),
            ok=not chip.startswith('Can'), kind='untrue', note='the chip says Can\'t save for a save location that works', shot=True)
    close(s)
    s.action('edit_device', device='clab-edge-lab-r1', add=['   ip route 10.55.0.0/16 10.0.0.1'])
    s.click('#git-save-progress'); settle(s)
    P.tried('edge-lab: the next Save', 'chip %r' % s.chip())


def typed_names(s, P):
    """Screenshots of what the chooser says for a few typed names (fixture)."""
    p = s.page
    s.open_lab('shared-b')
    s.click('#git-save-progress'); expect(p.locator('#save-first-place-other')).to_be_visible(timeout=20000)
    open_chooser(s); repository(s, 'Nested-Labs')
    for typed in ['UX TEST (3)', 'latest', 'Übung/größe']:
        p.locator('#folder-path').fill(''); p.locator('#folder-path').type(typed, delay=20); p.wait_for_timeout(2500)
        P.tried('typed %r' % typed, 'field %r | %s | %s' % (p.locator('#folder-path').input_value(), p.locator('#folder-answer').inner_text(),
                p.locator('#folder-result').inner_text().replace('\n', ' ')), shot=True)


def new_folder_unsafe(s, P):
    """New folder… with a name that has no safe character: what Add does (fixture)."""
    p = s.page
    s.open_lab('shared-b')
    s.click('#git-save-progress'); expect(p.locator('#save-first-place-other')).to_be_visible(timeout=20000)
    open_chooser(s); repository(s, 'Nested-Labs')
    p.locator('.folder-chooser [data-folder-action="new"]').click()
    p.locator('#folder-new').fill('日本語'); sent = len(s.sent)
    p.locator('.folder-new [data-folder-action="new-add"]').click(); p.wait_for_timeout(3000)
    P.tried('New folder… named 日本語: Add', 'requests %r | field still open %s' % (s.sent[sent:], p.locator('#folder-new').count() > 0),
            ok=bool(s.sent[sent:]), kind='nothing', note='Add sent nothing, said nothing')


def main():
    port = int(sys.argv[sys.argv.index('--port') + 1]) if '--port' in sys.argv else 8196
    name = sys.argv[-1]
    with fixture(port) as (base, data):
        s = Session(base, False, (1440, 900))
        P = Pass(s, 'probe-' + name)
        globals()[name](s, P)
        s.finish()


if __name__ == '__main__':
    main()
