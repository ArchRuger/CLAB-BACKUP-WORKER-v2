"""The old addresses of the removed Progress tab (PROMPT 5.11): each opens the lab's default tab with the header's save
panel, once; a link to the save location opens Save settings and one to the saved versions opens All versions.

Needs a fresh fixture (docs/git-redesign/tools/fixture/SCENARIOS.md). Fixture evidence only.
"""
import sys

from common import Session, arguments, expect

BOUND = 'restore-square'      # a lab with a save location
UNBOUND = 'shared-b'          # a lab without one


def go(s, lab, view):
    """A link followed from outside: a fresh load of the page at the old address."""
    s.page.goto('about:blank')
    s.page.goto('%s/#lab=%s&view=%s' % (s.base, s.lab_id(lab), view))
    s.page.wait_for_selector('#lab-content:not([hidden])')
    expect(s.page.locator('#title')).to_have_text(lab)


def main():
    args = arguments(__doc__)
    s = Session(args.base, args.headed, args.viewport)
    p = s.page
    size = '%dx%d' % args.viewport
    labs = s.fixture_state()['labs']
    unbound = UNBOUND if UNBOUND in labs else next(name for name in labs if not next(l for l in s.api_state()['labs'] if l['name'] == name).get('git_binding'))

    s.check('the page has no Progress tab', p.locator('#tab-progress').count() == 0 and p.locator('#progress-view').count() == 0)
    for view in ['progress', 'git']:
        go(s, BOUND, view)
        expect(p.locator('#save-panel')).to_be_visible(timeout=20000)
        name = 'view=%s, a lab with a save location' % view
        s.equal(name + ': the default tab is shown', p.locator('#lab-content [data-tab][aria-selected="true"]').get_attribute('id'), 'tab-topology')
        s.check(name + ': the save panel is open, the chip says so', p.locator('#save-chip').get_attribute('aria-expanded') == 'true' and s.visible('#save-panel-body'))
        s.match(name + ': the address is the tab it resolves to', p.evaluate('location.hash'), r'^#lab=[^&]+&view=topology$')
        s.check(name + ': focus is inside the panel', p.evaluate("!!document.activeElement&&!!document.activeElement.closest('#save-panel')"))
        s.shot('old-address-%s-%s' % (view, size))
        p.keyboard.press('Escape')
        expect(p.locator('#save-panel')).to_be_hidden()
        p.wait_for_timeout(6500)   # longer than one poll of /api/state
        s.check(name + ': a poll does not open it again', not s.visible('#save-panel'))
        # Chromium leaves an empty style attribute on form fields of a page it loads a second time in one tab; only a style
        # with a value is one the page wrote.
        styles = [x for x in s.inline_styles() if not x.endswith(':')]
        s.check(name + ': no inline style on /', not styles, styles)
        s.no_errors(name)

    go(s, unbound, 'progress')
    expect(p.locator('#save-panel')).to_be_visible(timeout=20000)
    text = p.locator('#save-panel-body').inner_text()
    s.check('view=progress, a lab without a save location: the first-save view', s.visible('#save-first-url') and 'Connect by URL' in text, text[:300])
    s.equal('view=progress, a lab without a save location: the default tab', p.locator('#lab-content [data-tab][aria-selected="true"]').get_attribute('id'), 'tab-topology')
    s.shot('old-address-progress-unbound-%s' % size)
    s.no_errors('view=progress, a lab without a save location')

    for view, title in [('save-location', 'Save settings'), ('saved-versions', 'All versions')]:
        go(s, BOUND, view)
        expect(p.locator('#save-drawer')).to_be_visible(timeout=20000)
        expect(p.locator('#save-drawer-title')).to_have_text(title, timeout=20000)
        s.equal('view=%s opens %s on the default tab' % (view, title), [s.text('#save-drawer-title'), p.locator('#lab-content [data-tab][aria-selected="true"]').get_attribute('id')], [title, 'tab-topology'])
        s.shot('old-address-%s-%s' % (view, size))
        p.keyboard.press('Escape')
        expect(p.locator('#save-drawer')).to_be_hidden()
        s.no_errors('view=' + view)

    # a hash change inside the open page (a link clicked in another document of the same tab, the back button)
    go(s, BOUND, 'devices')
    s.check('a tab address opens no panel', not s.visible('#save-panel') and not s.visible('#save-drawer'))
    p.evaluate("location.hash='#lab=%s&view=progress'" % s.lab_id(BOUND))
    expect(p.locator('#save-panel')).to_be_visible(timeout=20000)
    s.equal('a hash change to the old address: the default tab and the panel', p.locator('#lab-content [data-tab][aria-selected="true"]').get_attribute('id'), 'tab-topology')
    s.no_errors('a hash change to the old address')
    return s.finish()


if __name__ == '__main__':
    sys.exit(main())
