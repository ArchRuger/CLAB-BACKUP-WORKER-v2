"""Attack 5: repositories (fixture). The large repository (a folder that is not listed, typed by its path), the empty repository by
address (Start the repository; cancel halfway; an address that is not a repository; an address with credentials; forbidden and
missing), a second repository on the VM, and a lab with no repository on the VM at all."""
import re
import sys

from blocked import Pass, Session, arguments, expect, fixture, wait_until
from folder_flow import open_chooser, repository, place_of, answer, foot_buttons


def panel(s):
    return re.sub(r'\s+', ' ', s.page.locator('#save-panel').inner_text()) if s.visible('#save-panel') else ''


def close(s):
    for _ in range(3):
        if s.visible('#save-drawer') or s.visible('#save-panel'): s.page.keyboard.press('Escape'); s.page.wait_for_timeout(250)


def address_flow(s, P, url, label, expect_question=False, start=False, cancel=False):
    """The first-save panel's address field (no repository on the VM)."""
    p = s.page
    close(s)
    s.click('#git-save-progress'); expect(p.locator('#save-url')).to_be_visible(timeout=20000)
    if p.locator('#save-url').get_attribute('readonly') is not None:
        # the empty-repository question of an earlier address is still on screen: no way to type another address but a reload
        P.tried(label + ': another address after an empty one', panel(s)[:300], ok=False, kind='dead-end',
                note='the address field stays read-only with the empty-repository question; only Start the repository or a page reload leads on')
        s.open_lab(s.page.locator('#title').inner_text())
        s.click('#git-save-progress'); expect(p.locator('#save-url')).to_be_visible(timeout=20000)
    p.locator('#save-url').fill(url)
    sent = len(s.sent)
    with s.expect_status(409, r'/git/place'), s.expect_status(400, r'/git/place'):
        s.click('#save-first'); p.wait_for_timeout(4000)
    text = panel(s)
    calls = [c for c in s.sent[sent:] if '/git/place' in c]
    shown = re.sub(r'\s+', ' ', text)
    hit = P.raw_check(shown)
    if s.visible('#save-first-start'):
        P.tried(label + ': asks to start it', shown[:300], ok=True)
        if cancel:
            close(s); s.click('#git-save-progress'); p.wait_for_timeout(1500)
            again = panel(s)
            P.tried(label + ': cancelled halfway, Save again', again[:300], ok=not P.raw_check(again), kind='raw', note=again[:200], shot=True)
            close(s)
            return
        if start:
            with s.expect_status(409, r'/git/place'):
                s.click('#save-first-start'); p.wait_for_timeout(5000)
            after = panel(s)
            P.tried(label + ': Start the repository', after[:300] + ' | chip ' + s.chip(), ok=not re.search(r'could not|did not', after) or 'Try again' in after, kind='dead-end', note=after[:200], shot=True)
        return
    ok = not hit and ('cannot' not in shown.lower() or 'Try again' in shown or 'Details' in shown)
    P.tried(label, '%s | requests %s' % (shown[:400], [c[:120] for c in calls]), ok=ok, kind='raw' if hit else 'dead-end', note=('raw word %r' % hit) if hit else shown[:200], shot=True)
    close(s)


def main():
    args = arguments(__doc__)
    with fixture(args.port) as (base, data):
        s = Session(base, args.headed, (args.width, args.height))
        P = Pass(s, 'repos', args.out)
        p = s.page
        s.switch(capture_seconds=1)

        # ---- the large repository: square-fresh's chooser on Big-Repo
        s.open_lab('square-fresh')
        s.click('#git-save-progress'); expect(p.locator('#save-first-place-other')).to_be_visible(timeout=20000)
        open_chooser(s); repository(s, 'Big-Repo')
        note = p.locator('#folder-tree-note').inner_text() if s.visible('#folder-tree-note') else ''
        P.tried('Big-Repo: what the chooser says about its size', note, ok=True, shot=True)
        tree = p.locator('#folder-tree [data-folder]').count()
        P.tried('Big-Repo: tree rows on screen', str(tree), ok=tree > 1, kind='dead-end', note='empty tree')
        for folder in ['docs/week-22/topic-269', 'docs/week-01/topic-001', 'zz-states/final', 'zz-states/start/latest', 'docs/week-99/new', 'docs']:
            s.fill('#folder-path', folder); said = answer(s)
            listed = p.locator('[data-folder="%s"]' % folder).count() > 0
            P.tried('Big-Repo: type %s' % folder, '%s | listed=%s | %s' % (said, listed, foot_buttons(s)), ok=not s.visible('#folder-refused') and len(foot_buttons(s)) > 1, kind='refusal', note=said)
        # Show all on a branch with many folders
        twist = p.locator('[data-folder="docs"] > .folder-row [data-folder-twist]')
        if twist.count():
            twist.click(); p.wait_for_timeout(500)
            more = p.locator('[data-folder-action="show-all"]')
            P.tried('Big-Repo: a branch over 200 folders offers Show all', more.first.inner_text() if more.count() else 'no Show all', ok=True, shot=True)
        s.fill('#folder-path', 'docs/week-22/topic-269'); answer(s)
        box = p.locator('#folder-move input')
        if box.count() and box.is_checked(): box.uncheck()
        p.locator('#folder-foot [data-folder-primary]').click()
        try:
            expect(p.locator('#save-drawer')).to_be_hidden(timeout=30000)
            s.wait_chip(r'save to upload|Saved|Can.t', timeout=40000)
            P.tried('Big-Repo: save into a folder of the large repository', '%s, chip %s' % (place_of(s, 'square-fresh'), s.chip()), ok=not s.chip().startswith('Can'), kind='refusal', note=panel(s)[:200])
        except AssertionError:
            P.tried('Big-Repo: save into a folder of the large repository', p.locator('#save-drawer').inner_text()[:300], ok=False, kind='dead-end', note='drawer stays')
        close(s)
        s.click('#load-button'); p.wait_for_timeout(3000)
        lp = re.sub(r'\s+', ' ', p.locator('#load-panel').inner_text()) if s.visible('#load-panel') else ''
        P.tried('Big-Repo: Load lists its states beyond the file cap', lp[:400], ok='Final' in lp, kind='untrue', note='states beyond the cap missing', shot=True)
        close(s)

        # ---- a second repository: solo-lab moves to Nested-Labs and back
        s.open_lab('solo-lab')
        open_chooser(s); repository(s, 'Nested-Labs'); s.fill('#folder-path', 'solo-here'); answer(s)
        p.locator('#folder-foot [data-folder-primary]').click()
        try:
            expect(p.locator('#save-drawer')).to_be_hidden(timeout=30000)
            P.tried('another repository of the VM: solo-lab to Nested-Labs', place_of(s, 'solo-lab'))
        except AssertionError:
            P.tried('another repository of the VM: solo-lab to Nested-Labs', p.locator('#save-drawer').inner_text()[:300], ok=False, kind='dead-end', note='drawer stays', shot=True)
        close(s)
        # Use a different repository… from Save settings, then its dialog
        s.click('#save-chip'); s.click('#save-settings'); p.wait_for_timeout(2500)
        sw = p.locator('#save-drawer [data-git-repo-action="switch"]')
        if sw.count():
            sw.click(); p.wait_for_timeout(2000)
            dlg = p.locator('#git-switch-dialog')
            P.tried('Use a different repository…: the dialog', re.sub(r'\s+', ' ', dlg.inner_text())[:300] if dlg.count() else 'no dialog', ok=dlg.count() > 0, kind='nothing', note='no dialog', shot=True)
            if dlg.count() and p.locator('#git-switch-choose').count():
                p.locator('#git-switch-choose').click(); p.wait_for_timeout(2500)
                P.tried('Use a different repository… → Choose: the chooser opens on it', p.locator('#save-drawer-title').inner_text() if s.visible('#save-drawer') else 'no drawer',
                        ok=s.visible('#folder-tree'), kind='nothing', note='no chooser')
        close(s)

        # ---- addresses: Connect by URL… in the chooser of a lab that saves somewhere
        for url, label in [('https://github.com/ArchRuger/Spare-Lab.git', 'Connect by URL…: a repository with a README'),
                           ('https://user:token@github.com/ArchRuger/Spare-Lab.git', 'Connect by URL…: an address with credentials'),
                           ('https://github.com/ArchRuger/Spare-Lab/tree/main', 'Connect by URL…: a page link (/tree/main)'),
                           ('https://example.com/', 'Connect by URL…: an address that is not a repository'),
                           ('https://github.com/ArchRuger/forbidden-x.git', 'Connect by URL…: the account cannot push'),
                           ('https://github.com/ArchRuger/missing-x.git', 'Connect by URL…: cloning fails'),
                           ('git@github.com:ArchRuger/Spare-Lab.git', 'Connect by URL…: an SSH address'),
                           ('http://github.com/ArchRuger/Spare-Lab.git', 'Connect by URL…: plain http')]:
            s.open_lab('edge-lab')
            open_chooser(s)
            p.locator('.folder-chooser [data-folder-action="address-on"]').click(); p.wait_for_timeout(300)
            p.locator('#folder-url').fill(url); p.wait_for_timeout(200)
            # the folder field keeps the lab's own folder: its answer (Keep saving here) would close the drawer (finding); a new folder
            p.locator('#folder-path').fill('by-url-%d' % (len(P.rows) % 97)); p.wait_for_timeout(300)
            sent = len(s.sent)
            with s.expect_status(409, r'/git/place'), s.expect_status(400, r'/git/place'):
                p.locator('#folder-foot [data-folder-primary]').click(); p.wait_for_timeout(5000)
            calls = [c for c in s.sent[sent:] if '/git/place' in c]
            if s.visible('#save-drawer'):
                text = re.sub(r'\s+', ' ', p.locator('#save-drawer').inner_text())
                refused = p.locator('#folder-refused').inner_text() if s.visible('#folder-refused') else ''
                hit = P.raw_check(refused)
                creds = 'token' in ' '.join(calls) and 'credentials' in label
                P.tried(label, 'refused %r | buttons %r | sent %s' % (refused, foot_buttons(s), [c[:160] for c in calls]),
                        ok=not hit, kind='raw', note='raw %r in %r' % (hit, refused), shot=bool(refused))
                close(s)
            else:
                P.tried(label, 'placed: %s | sent %s' % (place_of(s, 'edge-lab'), [c[:160] for c in calls]))
            st = s.api_state()
            leaked = [r for r in (st.get('labs') or []) if 'token' in str(r.get('git_binding') or '')]
            if 'credentials' in label:
                P.tried(label + ': nothing of the token is kept or shown', 'bindings with "token": %d' % len(leaked), ok=not leaked, kind='untrue', note='token stored')

        # ---- no repository on the VM: square-fresh is placed already; use shared-b (never saved) with no_repositories
        s.switch(no_repositories=True)
        s.open_lab('shared-b')
        address_flow(s, P, 'https://github.com/ArchRuger/New-Empty.git', 'no repository on the VM: an empty repository', cancel=True)
        address_flow(s, P, 'not a url', 'no repository on the VM: text that is not an address')
        address_flow(s, P, 'https://github.com/ArchRuger/missing-x.git', 'no repository on the VM: cloning fails')
        s.switch(initialize_fails=True)
        address_flow(s, P, 'https://github.com/ArchRuger/New-Empty.git', 'no repository on the VM: Start the repository fails', start=True)
        s.switch(initialize_fails=None)
        address_flow(s, P, 'https://github.com/ArchRuger/New-Empty.git', 'no repository on the VM: Start the repository', start=True)
        s.wait_chip(r'save to upload|Saved|Can.t|Not saved', timeout=40000)
        P.tried('after Start the repository: chip and place', '%s, %s' % (s.chip(), place_of(s, 'shared-b')), ok='upload' in s.chip() or 'Saved' in s.chip(), kind='dead-end', note=s.chip(), shot=True)
        s.finish()
        return P.summary()


if __name__ == '__main__':
    sys.exit(main())
