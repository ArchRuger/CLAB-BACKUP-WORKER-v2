"""The page fixes after the QA wave that only a browser can show (F1): the name field under the poll, the arrow keys of the
folder tree, a click made right after typing, the header's panels under the action row, no sideways scroll, the remembered
branches. Needs a fresh fixture. Fixture evidence only.
"""
import re
import sys

from common import Session, arguments, expect
from folder_flow import open_chooser, place_of, saved_here


def main():
    args = arguments(__doc__)
    s = Session(args.base, args.headed, args.viewport)
    p = s.page
    s.switch(capture_seconds=1)
    s.open_lab('restore-square')

    # Q390-02: the page does not scroll sideways (a lab page and Home)
    wide = p.evaluate('document.documentElement.scrollWidth-document.documentElement.clientWidth')
    s.check('Q390-02 a lab page does not scroll sideways', wide <= 0, wide)
    box = p.locator('#manager-button').bounding_box()
    s.check('Q390-02 the Manager button is inside the screen', box['x'] + box['width'] <= args.width + 0.5, box)
    brand, crumb = p.locator('#nav-home').bounding_box(), p.locator('.crumbs').bounding_box()
    s.check('Q390-03 the breadcrumb is not printed over the brand', brand['x'] + brand['width'] <= crumb['x'] + 0.5, (brand, crumb))

    # Q760-04: with the chip panel open, Save, Load and Lab actions stay visible and Load can be clicked without closing it first
    s.click('#save-chip')
    expect(p.locator('#save-panel')).to_be_visible()
    panel = p.locator('#save-panel').bounding_box()
    under = [p.locator(sel).bounding_box() for sel in ['#save-chip', '#git-save-progress', '#load-button', '#lab-actions-button']]
    s.check('Q760-04 the chip panel opens below the header’s controls', all(b['y'] + b['height'] <= panel['y'] + 0.5 for b in under), (panel, under))
    # Q390-05: a caret put in the middle of the name stays there over two polls, the text is kept and nothing is posted
    name = p.locator('#save-name')
    name.click()
    name.evaluate('e=>e.setSelectionRange(4,4)')
    del s.sent[:]
    for letter in 'XYZ':
        p.keyboard.type(letter)
        p.wait_for_timeout(3200)
    value, caret = name.input_value(), name.evaluate('e=>e.selectionStart')
    s.equal('Q390-05 typed in the middle over three polls: the text is in order', value[:7], 'InteXYZ')
    s.equal('Q390-05 the caret is where the person left it', caret, 7)
    s.equal('Q390-05 the poll posted no rename', s.calls('/name'), [])
    p.keyboard.press('Enter')
    p.wait_for_timeout(800)
    s.equal('Q390-05 Enter posts the rename, once', len(s.calls('/name')), 1)
    s.click('#load-button')
    expect(p.locator('#load-panel-body .save-list').first).to_be_visible(timeout=20000)
    s.check('Q760-04 Load opens with the chip panel open before it: no Escape needed', not s.visible('#save-panel'))
    panel = p.locator('#load-panel').bounding_box()
    s.check('Q760-04 the Load panel opens below the header’s controls too', all(b['y'] + b['height'] <= panel['y'] + 0.5 for b in under), (panel, under))
    p.keyboard.press('Escape')
    s.no_errors('header')

    # Q390-04: the arrow keys move the focus in the folder tree; Enter selects the focused row
    s.open_lab('shared-b')
    s.click('#git-save-progress')
    expect(p.locator('#save-first-place-other')).to_be_visible(timeout=15000)
    open_chooser(s)
    p.locator('#folder-repo').select_option(label='Nested-Labs')
    expect(p.locator('#folder-tree [data-folder="notes"]')).to_be_visible(timeout=20000)
    p.locator('#folder-tree > [data-folder=""]').focus()
    seen = []
    for _ in range(3):
        p.keyboard.press('ArrowDown')
        p.wait_for_timeout(150)
        seen.append(p.evaluate("document.activeElement&&document.activeElement.getAttribute('data-folder')"))
    s.check('Q390-04 ArrowDown moves the focus from row to row', len(set(seen)) == 3 and '' not in seen and None not in seen, seen)
    p.keyboard.press('Enter')
    p.wait_for_timeout(600)
    s.equal('Q390-04 Enter selects the row that has the focus', p.locator('#folder-path').input_value(), seen[-1])

    # T1-5: the branches the person opened and closed are kept across closing and reopening the chooser
    twist = p.locator('[data-folder="BGP"] > .folder-row [data-folder-twist]')
    before = p.locator('[data-folder="BGP"]').get_attribute('aria-expanded')
    twist.click()
    p.wait_for_timeout(200)
    after = p.locator('[data-folder="BGP"]').get_attribute('aria-expanded')
    s.check('T1-5 the twisty toggles the branch', before != after, (before, after))
    s.click('#folder-foot [data-folder-action="cancel"]')
    s.click('#git-save-progress') if not s.visible('#save-first-place-other') else None
    open_chooser(s)
    if p.locator('#folder-repo option:checked').inner_text() != 'Nested-Labs':
        p.locator('#folder-repo').select_option(label='Nested-Labs')
    expect(p.locator('#folder-tree [data-folder="BGP"]')).to_be_visible(timeout=20000)
    p.wait_for_timeout(4500)
    s.equal('T1-5 reopened, and after a poll: the branch is as the person left it', p.locator('[data-folder="BGP"]').get_attribute('aria-expanded'), after)

    if args.width <= 480:
        heights = [p.locator(sel).first.bounding_box()['height'] for sel in ['.folder-chooser [data-folder-action="new"]', '#folder-foot [data-folder-action="cancel"]', '#save-drawer-close']]
        s.check('Q390-09, L2-8 New folder…, Cancel and the close button are at least 40 px high on a phone', all(h >= 39.5 for h in heights), heights)
    # Q1280-04: Save here pressed right after typing (within the 250 ms before the check is even sent) is not lost
    del s.sent[:]
    p.locator('#folder-path').fill('quick-click')
    p.locator('#folder-foot [data-folder-primary]').click()
    saved_here(s, 'shared-b', 'Nested-Labs:quick-click', 'Q1280-04 a click right after typing')
    s.equal('Q1280-04 one place request followed the check', len(s.calls('/git/place ')), 1)
    s.no_errors('chooser')

    # Home at this width
    p.locator('#crumb-home').click()
    expect(p.locator('#home-title')).to_be_visible(timeout=15000)
    wide = p.evaluate('document.documentElement.scrollWidth-document.documentElement.clientWidth')
    s.check('Q390-02 Home does not scroll sideways', wide <= 0, wide)
    s.check('Q1440-12 Home says your saves', 'your saves.' in p.locator('.home-hero').inner_text() and 'saved progress' not in p.locator('.home-hero').inner_text())
    return s.finish()


if __name__ == '__main__':
    sys.exit(main())
