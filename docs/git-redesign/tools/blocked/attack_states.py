"""Attack 3: states (fixture). A folder that holds a course state (latest and flat layout) as a lab's place; Save as a lab state…
into the lab's own folder, into another lab's folder, into an existing state (Replace it and Use another name), with an empty
name, a 120-character name and a name of only unsafe characters; a lab without a save location saving a state."""
import re
import sys

from blocked import Pass, Session, arguments, expect, fixture, wait_until, settle_question3
from folder_flow import open_chooser, repository, place_of, answer, foot_buttons


def panel(s):
    return s.page.locator('#save-panel').inner_text() if s.visible('#save-panel') else ''


def open_state(s):
    p = s.page
    if s.visible('#save-drawer'): p.keyboard.press('Escape'); p.wait_for_timeout(300)
    if not s.visible('#save-panel'): s.click('#save-chip')
    expect(p.locator('#save-as-state')).to_be_visible(timeout=15000)
    s.click('#save-as-state')
    expect(p.locator('#state-name')).to_be_visible(timeout=20000)
    s.wait_js("!!document.getElementById('folder-path')", what='the state chooser')
    p.wait_for_timeout(600)


def state_answer(s):
    p = s.page
    p.wait_for_timeout(400)
    s.wait_js("(()=>{const a=document.getElementById('folder-answer');return !!a&&!/Checking/.test(a.textContent);})()", timeout=20000, what='an answer')
    return dict(said=p.locator('#folder-answer').inner_text(), note=p.locator('#folder-answer-note').inner_text() if s.visible('#folder-answer-note') else '',
                result=p.locator('#folder-result').inner_text().replace('\n', ' '), buttons=foot_buttons(s), field=p.locator('#folder-path').input_value(),
                name=p.locator('#state-name').input_value(),
                refused=p.locator('#folder-refused').inner_text() if s.visible('#folder-refused') else '')


def submit_state(s, P, label, choice=None):
    """Presses the primary button (or the given choice) and reports where the state went, or what stopped it."""
    p = s.page
    sent = len(s.sent)
    sel = '#folder-foot [data-folder-choice="%s"]' % choice if choice else '#folder-foot [data-folder-primary]'
    button = p.locator(sel)
    if not button.count():
        return P.tried(label, 'no button %s; buttons %r' % (sel, foot_buttons(s)), ok=False, kind='dead-end', note='no such button')
    if not button.is_enabled():
        return P.tried(label, 'button disabled: %r' % foot_buttons(s), ok=False, kind='greyed', note='the primary button is disabled')
    button.click()
    p.wait_for_timeout(2500)
    calls = [c for c in s.sent[sent:] if '/git/state' in c]
    if s.visible('#save-drawer'):
        x = state_answer(s)
        if x['refused']: return P.tried(label, str(x), ok=False, kind='refusal', note=x['refused'], request=';'.join(calls)[:300])
        if not calls: return P.tried(label, str(x), ok=False, kind='nothing', note='the click sent nothing and the drawer says nothing new')
        return P.tried(label + ' (asks)', '%s | %s' % (x['said'], x['buttons']), shot=True)
    toasts = s.toasts()
    return P.tried(label, 'toasts %r; request %s' % (toasts[-2:], (calls[-1] if calls else 'none')[:200]))


def main():
    args = arguments(__doc__)
    with fixture(args.port) as (base, data):
        s = Session(base, args.headed, (args.width, args.height))
        P = Pass(s, 'states', args.out)
        p = s.page
        s.switch(capture_seconds=1)

        # A course state's folder as a lab's place: latest layout (BGP/start) and flat (Final), Replace it and Use this folder anyway
        s.open_lab('shared-b')
        s.click('#git-save-progress'); expect(p.locator('#save-first-place-other')).to_be_visible(timeout=20000)
        for folder, choice in [('BGP/final', 'take'), ('Final', 'take')]:
            open_chooser(s) if not s.visible('#folder-path') else None
            repository(s, 'Nested-Labs'); s.fill('#folder-path', folder); said = answer(s); buttons = foot_buttons(s)
            P.tried('place shared-b in the state folder %s' % folder, '%s %s' % (said, buttons), ok=len(buttons) == 3, kind='refusal', note=said)
            box = p.locator('#folder-move input')
            if box.count() and box.is_checked(): box.uncheck()
            p.locator('#folder-foot [data-folder-choice="%s"]' % choice).click()
            settle_question3(s, P, 'place shared-b in %s' % folder)
            try:
                expect(p.locator('#save-drawer')).to_be_hidden(timeout=30000)
                P.tried('  … %s answered %s' % (folder, choice), 'shared-b now %s' % place_of(s, 'shared-b'))
            except AssertionError:
                P.tried('  … %s answered %s' % (folder, choice), p.locator('#save-drawer').inner_text()[:300], ok=False, kind='dead-end', note='drawer stays')
            s.wait_chip(r'save to upload|Saved|Can.t save', timeout=40000)
            chip = s.chip()
            P.tried('  … the save after taking %s' % folder, chip, ok=not chip.startswith("Can"), kind='refusal', note=panel(s)[:200] if True else '', shot=chip.startswith("Can"))
            if s.visible('#save-panel'): p.keyboard.press('Escape')
            # what Load lists now: is the course state still there under its name?
            s.click('#load-button'); p.wait_for_timeout(2500)
            text = p.locator('#save-panel').inner_text() if s.visible('#save-panel') else ''
            P.tried('  … Load after taking %s' % folder, re.sub(r'\s+', ' ', text)[:300], shot=True)
            p.keyboard.press('Escape'); p.wait_for_timeout(300)
            if folder == 'BGP/final': open_chooser(s)

        # Save as a lab state… from restore-square
        s.open_lab('restore-square')
        cases = [
            ('into the lab\'s own folder', 'Inside', 'BGP', None),
            ('into another lab\'s folder', 'Edgy', 'BGP/edge', None),
            ('into an existing state, Replace it', 'Start', 'BGP/start', 'take'),
            ('into an existing state, Use another name', 'Broken', 'BGP/broken', 'use-another'),
            ('empty name', '', None, None),
            ('120-character name', 'n' * 120, None, None),
            ('only unsafe characters', '???!!!', None, None),
            ('only non-ASCII letters', 'Übung größe', None, None),
            ('a name that is a saved-state word', 'latest', None, None),
            ('the top level', 'Top', '', None),
        ]
        for label, name, folder, choice in cases:
            open_state(s)
            p.locator('#state-name').fill(name)
            p.wait_for_timeout(400)
            typed_name = p.locator('#state-name').input_value()
            if folder is not None:
                p.locator('#folder-path').fill(folder)
            x = state_answer(s)
            P.tried('state %s: before saving' % label, 'name field %r (%d chars) | %s | %s | %s' % (typed_name[:30], len(typed_name), x['said'], x['result'], x['buttons']),
                    ok=not (name and len(typed_name) < len(name) and len(name) <= 120), kind='untrue', note='the name field cut %d characters to %d without a word' % (len(name), len(typed_name)))
            if choice == 'use-another':
                submit_state(s, P, 'state %s: Save state' % label)
                btn = p.locator('#folder-foot [data-folder-action="use-another-name"]')
                if btn.count():
                    btn.click(); p.wait_for_timeout(300)
                    P.tried('state %s: Use another name focuses the name' % label, s.focused(), ok=s.focused() == 'state-name', kind='nothing', note=s.focused())
                    p.locator('#state-name').fill('Broken-2'); p.wait_for_timeout(500)
                    submit_state(s, P, 'state %s: saved as Broken-2' % label)
            elif choice == 'take':
                submit_state(s, P, 'state %s: Save state' % label)
                if s.visible('#save-drawer') and p.locator('#folder-foot [data-folder-choice="take"]').count():
                    submit_state(s, P, 'state %s: Replace it' % label, choice='take')
            else:
                submit_state(s, P, 'state %s: Save state' % label)
            s.wait_chip(r'save|Saved|Can.t', timeout=40000)
            p.wait_for_timeout(1500)
            if s.visible('#save-drawer'): p.keyboard.press('Escape')
            if s.visible('#save-panel'): p.keyboard.press('Escape')
        # what the list of states holds now
        s.click('#load-button'); p.wait_for_timeout(3000)
        P.tried('Load lists the states saved above', re.sub(r'\s+', ' ', p.locator('#save-panel').inner_text())[:500], shot=True)
        p.keyboard.press('Escape')

        # a lab without a save location saves a state
        s.open_lab('square-fresh')
        s.click('#save-chip'); p.wait_for_timeout(1500)
        if s.visible('#save-as-state'):
            s.click('#save-as-state'); expect(p.locator('#state-name')).to_be_visible(timeout=20000); p.wait_for_timeout(800)
            p.locator('#state-name').fill('Fresh-start'); x = state_answer(s)
            P.tried('square-fresh (no save location): state chooser', '%s | %s | %s' % (x['said'], x['result'], x['buttons']))
            submit_state(s, P, 'square-fresh saves a lab state')
            s.wait_chip(r'save|Saved|Can.t|Not saved', timeout=40000); p.wait_for_timeout(1000)
            P.tried('square-fresh after the state: chip', s.chip(), ok=True, shot=True)
        else:
            P.tried('square-fresh (no save location): Save as a lab state… offered', panel(s)[:300], ok=False, kind='dead-end', note='no button', shot=True)
        s.finish()
        return P.summary()


if __name__ == '__main__':
    sys.exit(main())
