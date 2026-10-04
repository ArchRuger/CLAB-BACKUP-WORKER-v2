"""Attack 2: other labs (fixture). The very folder another lab saves in, a folder inside another lab's `latest`, a folder above
another lab, two labs choosing the same new folder at the same moment (two browser contexts), and a lab whose folder was taken
by another lab's "Use this folder anyway" pressing Save, with and without a waiting save."""
import re
import sys

from blocked import Pass, Session, arguments, expect, fixture, wait_until
from folder_flow import open_chooser, repository, place_of, answer, foot_buttons


def chip_text(s):
    return s.page.locator('#save-chip-text').inner_text()


def panel(s):
    return s.page.locator('#save-panel').inner_text() if s.visible('#save-panel') else ''


def choose(s, folder, repo='Nested-Labs'):
    open_chooser(s); repository(s, repo)
    s.fill('#folder-path', folder)
    return answer(s)


def press(s, selector):
    box = s.page.locator('#folder-move input')
    if box.count() and box.is_checked(): box.uncheck()
    s.page.locator(selector).click()


def placed(s, lab, timeout=30):
    expect(s.page.locator('#save-drawer')).to_be_hidden(timeout=timeout * 1000)
    return wait_until(lambda: place_of(s, lab), timeout=timeout, what='a place')


def main():
    args = arguments(__doc__)
    with fixture(args.port) as (base, data):
        s = Session(base, args.headed, (args.width, args.height))
        P = Pass(s, 'labs', args.out)
        p = s.page
        s.switch(capture_seconds=1)

        # restore-square gets a waiting save first (its folder BGP is taken later)
        s.action('edit_device', device='ceos', add=['   ip route 0.0.0.0/0 10.0.0.1'])
        s.open_lab('restore-square')
        s.click('#git-save-progress')
        s.wait_chip(r'^1 save to upload$', timeout=40000)
        p.keyboard.press('Escape')

        # shared-b: first save into shared-a's folder, answered with Use this folder anyway
        s.open_lab('shared-b')
        s.click('#git-save-progress')
        expect(p.locator('#save-first-place-other')).to_be_visible(timeout=20000)
        said = choose(s, 'shared')
        buttons = foot_buttons(s)
        P.tried('the very folder another lab saves in (shared)', '%s %s' % (said, buttons), ok='Use this folder anyway' in buttons, kind='refusal', note=said)
        press(s, '#folder-foot [data-folder-choice="take"]')
        where = placed(s, 'shared-b')
        s.wait_chip(r'save to upload|Saved', timeout=40000)
        P.tried('Use this folder anyway: shared-b takes shared', 'shared-b in %s, shared-a in %s' % (where, place_of(s, 'shared-a')),
                ok=where.endswith(':shared') and place_of(s, 'shared-a') is None, kind='untrue', note='shared-a still %s' % place_of(s, 'shared-a'))
        if s.visible('#save-panel'): p.keyboard.press('Escape')

        # shared-a, its folder taken: press Save
        s.open_lab('shared-a')
        s.click('#git-save-progress')
        p.wait_for_timeout(2500)
        text = panel(s)
        P.tried('the lab whose folder was taken presses Save', text[:300], ok=bool(re.search(r'first save|Save|Choose another place', text)) and not re.search(r'cannot|could not|refus', text, re.I),
                kind='dead-end', note=text[:200], shot=True)
        # its first-save panel offers a default: where?
        first = p.locator('#save-first-place').inner_text() if s.visible('#save-first-place') else ''
        P.tried('shared-a: the place the first-save panel offers after losing its folder', first,
                ok=bool(first) and 'in the folder shared.' not in first, kind='untrue', note='offers its lost folder: ' + first, shot=True)
        if s.visible('#save-first'):
            s.click('#save-first')
            p.wait_for_timeout(1500)
            q = panel(s)
            P.tried('shared-a: Save on the offered place', q[:300], ok=not re.search(r'cannot|could not|did not work', q, re.I), kind='refusal', note=q[:200], shot=True)
            if s.visible('#save-drawer'):
                P.tried('shared-a: the offered place asks a question (the drawer opened)', p.locator('#save-drawer').inner_text()[:300], shot=True)
                p.keyboard.press('Escape')
        if s.visible('#save-panel'): p.keyboard.press('Escape')

        # shared-b takes BGP from restore-square while restore-square has a waiting save
        s.open_lab('shared-b')
        said = choose(s, 'BGP')
        press(s, '#folder-foot [data-folder-choice="take"]') if p.locator('#folder-foot [data-folder-choice="take"]').count() else None
        p.wait_for_timeout(2500)
        if p.locator('#folder-foot [data-folder-pending="keep"]').count():
            # shared-b's own first save still waits: question 3 comes first (expected), answered with Move and keep
            P.tried('take BGP while shared-b\'s own save waits: question 3 first', p.locator('#folder-answer').inner_text())
            p.locator('#folder-foot [data-folder-pending="keep"]').click()
        try: where = placed(s, 'shared-b')
        except AssertionError:
            P.tried('take BGP from restore-square (waiting save there)', p.locator('#save-drawer').inner_text()[:300], ok=False, kind='dead-end', note='drawer stays')
            where = place_of(s, 'shared-b')
        P.tried('take BGP from restore-square (waiting save there)', 'answer %r; shared-b now %s' % (said, where), ok=where and where.endswith(':BGP'), kind='refusal', note=said)
        if s.visible('#save-panel'): p.keyboard.press('Escape')
        s.open_lab('restore-square')
        P.tried('restore-square after losing BGP: chip', chip_text(s), ok='upload' in chip_text(s), kind='untrue', note='the waiting save is no longer named: ' + chip_text(s), shot=True)
        s.click('#save-chip'); p.wait_for_timeout(1500)
        text = panel(s)
        up = p.locator('#save-upload')
        if up.count():
            expect(up).to_be_enabled(timeout=20000)
            up.click()
            try:
                s.wait_toast(r'^Uploaded to ', timeout=30000)
                P.tried('restore-square uploads its waiting save after losing its folder', text[:200])
            except AssertionError:
                P.tried('restore-square uploads its waiting save after losing its folder', panel(s)[:300], ok=False, kind='dead-end', note=panel(s)[:200])
        else:
            P.tried('restore-square: Upload offered for the save that waits', text[:300], ok=False, kind='dead-end', note='no Upload')
        if s.visible('#save-panel'): p.keyboard.press('Escape')
        s.click('#git-save-progress'); p.wait_for_timeout(2500)
        text = panel(s)
        P.tried('restore-square presses Save without a folder', text[:300], ok=not re.search(r'cannot|could not|did not work', text, re.I), kind='dead-end', note=text[:200], shot=True)
        if s.visible('#save-panel'): p.keyboard.press('Escape')

        # inside another lab's latest, another lab's latest itself, above another lab, beside it
        s.open_lab('shared-b')
        for folder in ['BGP/edge/latest', 'BGP/edge/latest/x', 'BGP/edge/checkpoints', 'shared/latest/inner', 'BGP/edge', '']:
            said = choose(s, folder); buttons = foot_buttons(s)
            refused = s.visible('#folder-refused')
            P.tried('shared-b chooses %r' % folder, '%s %s | %s' % (said, buttons, p.locator('#folder-result').inner_text().replace('\n', ' ')),
                    ok=not refused and len(buttons) > 1 and all(b for b in buttons), kind='refusal', note=said)
            p.locator('#folder-foot [data-folder-action="cancel"]').click()

        # two labs, the same new folder, the same moment: square-fresh and solo-lab (two browser contexts)
        ctx2 = s.browser.new_context(viewport={'width': args.width, 'height': args.height}); p2 = ctx2.new_page()
        errors2 = []; p2.on('pageerror', lambda e: errors2.append(str(e))); p2.on('console', lambda m: errors2.append(m.text) if m.type == 'error' else None)
        s.open_lab('square-fresh')
        s.click('#git-save-progress'); expect(p.locator('#save-first-place-other')).to_be_visible(timeout=20000)
        open_chooser(s); repository(s, 'Nested-Labs'); s.fill('#folder-path', 'race-folder'); answer(s)
        solo = s.lab_id('solo-lab')
        p2.goto('%s/#lab=%s&view=topology' % (base, solo)); p2.wait_for_selector('#lab-content:not([hidden])')
        p2.locator('#save-chip').click(); p2.locator('#save-change').click()
        expect(p2.locator('#folder-tree')).to_be_visible(timeout=20000)
        p2.locator('#folder-repo').select_option(label='Nested-Labs'); expect(p2.locator('#folder-tree')).to_be_visible(timeout=20000)
        p2.wait_for_timeout(800)
        p2.locator('#folder-path').fill('race-folder')
        wait_until(lambda: p2.evaluate("(()=>{const a=document.getElementById('folder-answer');return !!a&&!/Checking/.test(a.textContent);})()"), timeout=20, what='second answer')
        for box in (p.locator('#folder-move input'), p2.locator('#folder-move input')):
            if box.count() and box.is_checked(): box.uncheck()
        p.locator('#folder-foot [data-folder-primary]').click(no_wait_after=True)
        p2.locator('#folder-foot [data-folder-primary]').click(no_wait_after=True)
        p.wait_for_timeout(15000); p2.wait_for_timeout(500)
        a1 = place_of(s, 'square-fresh'); a2 = place_of(s, 'solo-lab')
        d2 = p2.locator('#save-drawer').inner_text() if p2.locator('#save-drawer').is_visible() else ''
        d1 = p.locator('#save-drawer').inner_text() if p.locator('#save-drawer').is_visible() else ''
        p2.screenshot(path=str(P.out.parent / 'race-second.png'))
        both = (a1 or '').endswith(':race-folder') and (a2 or '').endswith(':race-folder')
        asked = 'saves here too' in d1 + d2
        P.tried('two labs choose the same new folder at the same moment', 'square-fresh %s, solo-lab %s | open drawers: %r / %r' % (a1, a2, d1[:160], d2[:160]),
                ok=not both and (asked or not (d1 or d2)) and not re.search(r'could not|cannot|did not', d1 + d2), kind='untrue' if both else 'refusal',
                note='both in race-folder' if both else (d1 + d2)[:200], shot=True)
        if errors2: P.tried('second context console', '; '.join(errors2[:4]), ok=False, kind='error', note='; '.join(errors2[:4]))
        ctx2.close()
        s.finish()
        return P.summary()


if __name__ == '__main__':
    sys.exit(main())
