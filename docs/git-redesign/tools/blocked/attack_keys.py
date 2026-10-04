"""Attack 8: the keyboard only (fixture). Every flow from the first key press: Tab to the control, Enter/Space, arrows in the tree,
Escape out; the pointer is never used. Reports where focus lands and every step that needs a pointer."""
import re
import sys

from blocked import Pass, Session, arguments, expect, fixture, wait_until


def focus_id(s):
    return s.page.evaluate("(()=>{const a=document.activeElement;if(!a)return '';return a.id||(a.dataset&&(a.dataset.folderAction||a.dataset.folderChoice||a.dataset.saveAction||a.dataset.loadAction||a.dataset.folder))||(a.tagName+':'+(a.textContent||'').trim().slice(0,30));})()")


def tab_to(s, test, limit=80, shift=False):
    """Presses Tab until `test(focused)`; returns the number of presses, or None."""
    for n in range(1, limit + 1):
        s.page.keyboard.press('Shift+Tab' if shift else 'Tab')
        f = focus_id(s)
        if test(f): return n
    return None


def main():
    args = arguments(__doc__)
    with fixture(args.port) as (base, data):
        s = Session(base, args.headed, (args.width, args.height))
        P = Pass(s, 'keys', args.out)
        p = s.page
        s.switch(capture_seconds=1)

        # first save of shared-b, keyboard only: Save, then Choose another place, type a folder, Enter, question 1 by keyboard
        s.open_lab('shared-b')
        p.locator('body').focus() if False else p.evaluate("document.activeElement&&document.activeElement.blur()")
        n = tab_to(s, lambda f: f == 'git-save-progress')
        P.tried('Tab reaches Save', 'after %s presses' % n, ok=n is not None, kind='dead-end', note='Save never focused')
        p.keyboard.press('Enter'); p.wait_for_timeout(2500)
        P.tried('Enter on Save opens the first-save panel; focus', focus_id(s), ok=s.visible('#save-panel'), kind='nothing', note='no panel', shot=True)
        n = tab_to(s, lambda f: f == 'save-first-place-other', limit=20)
        P.tried('Tab reaches Choose another place', str(n), ok=n is not None, kind='dead-end', note='not reachable')
        p.keyboard.press('Enter'); p.wait_for_timeout(3000)
        P.tried('the chooser opens; focus', focus_id(s), ok=s.visible('#folder-tree'), kind='nothing', note='no chooser', shot=True)
        n = tab_to(s, lambda f: f == 'folder-repo', limit=20)
        P.tried('Tab reaches the repository select', str(n), ok=n is not None, kind='dead-end', note='not reachable')
        n = tab_to(s, lambda f: f == 'folder-path', limit=20)
        P.tried('Tab reaches the Folder field', str(n), ok=n is not None, kind='dead-end', note='not reachable')
        p.keyboard.press('Control+a'); p.keyboard.type('shared'); p.wait_for_timeout(2500)
        P.tried('typed a folder: the answer', p.locator('#folder-answer').inner_text(), shot=True)
        n = tab_to(s, lambda f: f in ('take', 'beside', 'save', 'keep'), limit=40)
        P.tried('Tab reaches the answer buttons', '%s presses, focus %s' % (n, focus_id(s)), ok=n is not None, kind='dead-end', note='not reachable')
        # the tree: Shift+Tab back to it, then arrows
        n = tab_to(s, lambda f: p.evaluate("document.activeElement&&document.activeElement.getAttribute('role')==='treeitem'"), limit=60, shift=True)
        P.tried('Shift+Tab reaches the tree', '%s presses, focus %s' % (n, focus_id(s)), ok=n is not None, kind='dead-end', note='tree not reachable')
        if n is not None:
            p.keyboard.press('Home'); p.keyboard.press('ArrowDown'); p.keyboard.press('ArrowDown'); p.keyboard.press('Enter'); p.wait_for_timeout(2000)
            P.tried('arrows and Enter select a folder', 'field %r | %s' % (p.locator('#folder-path').input_value(), p.locator('#folder-answer').inner_text()))
            p.keyboard.press('ArrowRight'); p.keyboard.press('ArrowDown'); p.keyboard.press(' '); p.wait_for_timeout(1500)
            P.tried('ArrowRight opens a branch, Space selects', 'field %r' % p.locator('#folder-path').input_value())
        # New folder… by keyboard
        n = tab_to(s, lambda f: f == 'new', limit=60)
        P.tried('Tab reaches New folder…', str(n), ok=n is not None, kind='dead-end', note='not reachable')
        if n is not None:
            p.keyboard.press('Enter'); p.wait_for_timeout(500)
            P.tried('New folder… puts focus in its field', focus_id(s), ok=focus_id(s) == 'folder-new', kind='nothing', note=focus_id(s))
            p.keyboard.type('by-keys'); p.keyboard.press('Enter'); p.wait_for_timeout(3000)
            P.tried('Enter adds the folder; focus', 'field %r | focus %s | %s' % (p.locator('#folder-path').input_value(), focus_id(s), p.locator('#folder-answer').inner_text()),
                    ok=p.locator('#folder-path').input_value().endswith('by-keys'), kind='nothing', note='not added')
        # Save here by keyboard
        n = tab_to(s, lambda f: f == 'save', limit=40)
        P.tried('Tab reaches Save here', str(n), ok=n is not None, kind='dead-end', note='not reachable')
        p.keyboard.press('Enter'); p.wait_for_timeout(4000)
        s.wait_chip(r'save to upload|Saved', timeout=40000)
        P.tried('Save here by Enter: placed and saved', 'chip %r, focus %s' % (s.chip(), focus_id(s)), ok='upload' in s.chip(), kind='dead-end', note=s.chip(), shot=True)
        # Upload by keyboard from the chip
        for _ in range(3): p.keyboard.press('Escape'); p.wait_for_timeout(300)
        P.tried('after Save here: what is open', 'panel %s drawer %s dialogs %s focus %s' % (s.visible('#save-panel'), s.visible('#save-drawer'), p.locator('dialog[open]').count(), focus_id(s)), shot=True)
        p.evaluate("document.activeElement&&document.activeElement.blur()")
        n = tab_to(s, lambda f: f == 'save-chip')
        P.tried('Tab reaches the chip', str(n), ok=n is not None, kind='dead-end', note='not reachable')
        p.keyboard.press('Enter'); p.wait_for_timeout(1500)
        try: expect(p.locator('#save-upload')).to_be_enabled(timeout=20000)
        except AssertionError: pass
        n = tab_to(s, lambda f: f == 'save-upload', limit=20)
        P.tried('Tab reaches Upload', str(n), ok=n is not None, kind='dead-end', note='not reachable')
        p.keyboard.press('Enter')
        try: s.wait_toast(r'^Uploaded', timeout=30000); P.tried('Upload by Enter', s.chip())
        except AssertionError: P.tried('Upload by Enter', s.chip(), ok=False, kind='dead-end', note=s.chip(), shot=True)
        p.keyboard.press('Escape'); p.wait_for_timeout(300)
        # Load by keyboard: Load, a row, the red Load
        s.open_lab('restore-square')
        p.evaluate("document.activeElement&&document.activeElement.blur()")
        n = tab_to(s, lambda f: f == 'load-button')
        P.tried('Tab reaches Load', str(n), ok=n is not None, kind='dead-end', note='not reachable')
        p.keyboard.press('Enter'); p.wait_for_timeout(2500)
        P.tried('Enter on Load: focus', focus_id(s), ok=s.visible('#load-panel'), kind='nothing', note='no panel')
        n = tab_to(s, lambda f: p.evaluate("(()=>{const a=document.activeElement;return !!a&&/Final/.test(a.textContent||'')&&a.matches('[data-load-row]');})()"), limit=30)
        P.tried('Tab reaches the row Final', str(n), ok=n is not None, kind='dead-end', note='not reachable')
        p.keyboard.press('Enter'); p.wait_for_timeout(4000)
        n = tab_to(s, lambda f: f == 'load-run', limit=30)
        P.tried('Tab reaches the red Load', str(n), ok=n is not None, kind='dead-end', note='not reachable', shot=True)
        if n is not None:
            p.keyboard.press('Enter')
            s.wait_js("!/Loading/.test(document.getElementById('save-chip-text').textContent)", timeout=90000)
            p.wait_for_timeout(1500)
            P.tried('Load by Enter', 'chip %r toasts %r' % (s.chip(), s.toasts()[-1:]), ok=s.chip().startswith('Running'), kind='dead-end', note=s.chip())
        # Escape closes and focus returns to the opener
        p.evaluate("document.activeElement&&document.activeElement.blur()")
        tab_to(s, lambda f: f == 'save-chip'); p.keyboard.press('Enter'); p.wait_for_timeout(800)
        p.keyboard.press('Escape'); p.wait_for_timeout(500)
        P.tried('Escape closes the chip panel; focus returns', focus_id(s), ok=focus_id(s) == 'save-chip' and not s.visible('#save-panel'), kind='nothing', note=focus_id(s))
        # Save settings and its drawer by keyboard: devices ticks and Disconnect reachable
        p.keyboard.press('Enter'); p.wait_for_timeout(800)
        n = tab_to(s, lambda f: f == 'save-settings', limit=30); p.keyboard.press('Enter'); p.wait_for_timeout(2500)
        P.tried('Save settings by keyboard', 'presses %s, drawer %s, focus %s' % (n, s.visible('#save-drawer'), focus_id(s)), ok=s.visible('#save-drawer'), kind='dead-end', note='no drawer')
        n = tab_to(s, lambda f: f == 'save-settings' or 'Save settings' in f, limit=60)
        P.tried('Tab reaches the drawer\'s Save settings button', str(n), ok=n is not None, kind='dead-end', note='not reachable')
        p.keyboard.press('Escape'); p.wait_for_timeout(500)
        P.tried('Escape closes the drawer; focus', focus_id(s), ok=not s.visible('#save-drawer'), kind='nothing', note='drawer stays')
        s.finish()
        return P.summary()


if __name__ == '__main__':
    sys.exit(main())
