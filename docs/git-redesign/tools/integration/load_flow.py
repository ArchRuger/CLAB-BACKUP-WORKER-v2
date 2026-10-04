"""Area E: loading (PROMPT 5.4), which is "Apply to running lab" in full. Needs a fresh fixture. Fixture evidence only:
the real restore service runs, the devices are scripted (SCENARIOS.md), nothing here says anything about a real NOS.
"""
import re
import sys

from common import Session, arguments, expect, wait_until
from save_flow import page_fetch


FINAL = 'Final · BGP'   # the fixture holds two states named Final (BGP/final and the top-level Final): each adds its parent


def body(s):
    return s.page.locator('#load-panel-body').inner_text()


def chip_body(s):
    return s.page.locator('#save-panel-body').inner_text()


def open_list(s):
    p = s.page
    s.click('#load-button')
    expect(p.locator('#load-panel-body .save-list').first).to_be_visible(timeout=20000)


def row(s, name):
    """The row of the Load list whose name is exactly `name`."""
    return s.page.locator('#load-panel-body .save-list > li').filter(has=s.page.locator('.save-item > span:first-child', has_text=re.compile('^' + re.escape(name)))).first


def choose(s, name):
    p = s.page
    s.click(row(s, name).locator('button.save-item'))
    expect(p.locator('#load-run')).to_be_visible(timeout=30000)


def devices(s, root='#load-panel-body'):
    """{device: right-hand text} of a device list."""
    out = {}
    for item in s.page.locator(root + ' ul.save-devices > li').all():
        text = item.inner_text().split('\n')
        out[text[0].split(' ')[0].strip()] = item.locator('.save-end').inner_text()
    return out


def load_and_wait(s, pattern, timeout=90000):
    """Presses the red Load and waits for the chip that ends the load."""
    s.click('#load-run')
    s.wait_chip(r'^(Loading…|Checking)', timeout=15000)
    s.wait_chip(pattern, timeout=timeout)


def visible_load_buttons(s):
    return s.page.evaluate("[...document.querySelectorAll('button')].filter(b=>b.offsetParent!==null&&/^Load( on \\d+ devices?)?$/.test(b.textContent.trim())&&b.id!=='load-button').map(b=>b.textContent.trim())")


def main():
    args = arguments(__doc__)
    s = Session(args.base, args.headed)
    p = s.page
    s.switch(capture_seconds=1, restore_capture_seconds=1)
    lab = s.lab_id('restore-square')

    # ---- the Load panel: two groups, the subset, the view-only row ----------------------------------------------------------------
    s.open_lab('restore-square')
    s.reset_counts()
    open_list(s)
    headings = p.locator('#load-panel-body h3.save-heading').all_inner_texts()
    s.equal('E Load panel: two groups', [h.lower() for h in headings], ['your saves', 'lab states'])
    states = p.locator('#load-panel-body .save-list').nth(1).locator('li .save-item > span:first-child').all_inner_texts()
    names = [x.split('\n')[0] for x in states]
    s.check('E Lab states: Start, Broken and Final by name', all(n in names for n in ['Start', 'Broken', FINAL]), names)
    s.check('E Lab states: none is named by its repository or folder path', not any('›' in n or '/' in n for n in names), names)
    s.check('E two states of one name each add their parent (DESIGN.md 3.8 N3)', 'Final · BGP' in names and 'Final · Top level' in names, names)
    s.match('E the subset state says so on its row', row(s, 'Junos-only').inner_text(), r'2 of 4 devices')
    start = [r for r in p.locator('#load-panel-body .save-list > li.off').all_inner_texts() if r.startswith('Start')]
    s.check('E the view-only state stays listed, disabled, with its reason', len(start) == 1 and 'View only' in start[0] and 'Saved without the files needed to load it' in start[0], start)
    s.check('E the view-only row has no load button, only View', row(s, 'Start').locator('button.save-item').count() == 0 and row(s, 'Start').locator('[data-load-view]').count() == 1)
    foot = p.locator('#load-panel-body .save-foot button').all_inner_texts()
    s.equal('E Load panel: All versions and Browse the repository…', foot, ['All versions', 'Browse the repository…'])
    s.shot('E-load-panel')

    # ---- the confirmation ---------------------------------------------------------------------------------------------------------------
    choose(s, FINAL)
    s.equal('E confirmation headline', p.locator('#load-panel-body .save-state').inner_text(), 'Load ' + FINAL + '?')
    s.check('E confirmation sentence', 'The running configuration of the ticked devices is replaced. The current one is backed up first; nothing reboots.' in body(s))
    rows = devices(s)
    s.check('E confirmation: one row per device with its difference count', re.match(r'^\d+ lines? differs?$', rows.get('ceos', '')) and re.match(r'^\d+ lines? differs?$', rows.get('xrv9k', '')) and rows.get('cjunosevolved') == 'Already matches' and rows.get('vjunos-switch') == 'Already matches', rows)
    boxes = p.locator('#load-panel-body input[name="load-node"]')
    s.check('E confirmation: real tick boxes, all ticked', boxes.count() == 4 and all(boxes.nth(i).is_checked() for i in range(4)))
    s.equal('E confirmation: Load, Cancel, See what\'s different', p.locator('#load-panel-body .save-row').last.locator('button').all_inner_texts(), ['Load', 'Cancel', "See what's different"])
    s.check('E confirmation: the red Load is the danger button', 'danger' in p.locator('#load-run').get_attribute('class'))
    s.shot('E-confirmation')

    # See what's different: load.js's view in the drawer, exactly one Load button on screen, Back returns to the same confirmation
    boxes.nth(1).uncheck()
    s.click('#load-diff', count=False)
    expect(p.locator('#save-drawer')).to_be_visible()
    s.equal('E differences drawer: title', s.text('#save-drawer-title'), "What's different")
    s.equal('E differences drawer: exactly one Load button on screen, naming the count', visible_load_buttons(s), ['Load on 3 devices'])
    s.check('E differences drawer: one Back', p.locator('#save-drawer button:visible', has_text=re.compile('^Back$')).count() == 1)
    s.check('E differences drawer: the differences of the ticked devices', p.locator('#save-drawer-content .save-heading').count() >= 1)
    s.shot('E-differences')
    s.click('#load-diff-back', count=False)
    expect(p.locator('#load-run')).to_be_visible(timeout=10000)
    s.check('E Back: the drawer is closed and the panel shows the same confirmation', not s.visible('#save-drawer') and p.locator('#load-panel-body .save-state').inner_text() == 'Load ' + FINAL + '?')
    s.check('E Back: the ticks are kept', not boxes.nth(1).is_checked() and boxes.nth(0).is_checked())
    s.check('E Back: focus lands on the confirmation\'s headline', p.evaluate("document.activeElement===document.querySelector('#load-panel-body [data-panel-focus]')"))
    s.equal('E Back: no second preflight was sent', len(s.calls('/restore/preflight')), 1)
    boxes.nth(1).check()

    # the red Load is held while a save runs (render() -> loadRender())
    s.switch(capture_seconds=7)
    s.action('edit_device', device='vjunos-switch', add=['set system host-name vjunos-i1'], remove=[])
    saved = page_fetch(s, 'POST', '/api/labs/%s/git/save' % lab, {'request_id': '%032x' % 0x2201, 'target': 'latest', 'checkpoint': '', 'push': True, 'note': '', 'backup_job_id': '', 'replace_baseline': False, 'expected_baseline': '', 'allow_removed': True})
    s.check('E a save started from elsewhere', saved['status'] == 200, saved)
    expect(p.locator('#load-run')).to_be_disabled(timeout=10000)
    s.equal('E during a save the red Load is disabled with its reason', s.text('#load-run-reason'), 'A save is running.')
    s.check('E during a save the ticks stay', all(boxes.nth(i).is_checked() for i in range(4)))
    expect(p.locator('#load-run')).to_be_enabled(timeout=30000)
    s.check('E the red Load is available again when the save ends', not s.visible('#load-run-reason'))
    s.switch(capture_seconds=1)
    s.click('#load-cancel', count=False)
    expect(p.locator('#load-panel-body .save-list').first).to_be_visible(timeout=20000)
    p.keyboard.press('Escape')
    s.equal('E Escape closes the Load panel and focus returns to Load', s.focused(), 'load-button')
    s.no_errors('E list, confirmation, differences')

    # ---- load a lab state in three clicks; the loading view; Running ---------------------------------------------------------------
    s.switch_raw({'load_preset': 'slow', 'load_seconds': 2})
    s.reset_counts()
    open_list(s)
    choose(s, FINAL)
    s.click('#load-run')
    s.check('E load a lab state: 3 clicks, nothing typed', s.clicks == 3 and s.typed == 0, s.clicks)
    s.wait_chip(r'^Loading… \d of 4$', timeout=20000)
    expect(p.locator('#save-panel')).to_be_visible(timeout=10000)
    s.equal('E loading: the chip panel opens with the loading view', s.text('#save-panel-title'), 'Loading ' + FINAL + '…')
    words = set(devices(s, '#save-panel-body').values())
    s.check('E loading: each device reads Waiting, Backing up…, Loading… or its outcome', words <= {'Waiting', 'Backing up…', 'Loading…', 'Loaded', 'Already matched', 'Checking…'} and len(words) >= 1, words)
    s.check('E loading: Save and Load are disabled', p.locator('#git-save-progress').is_disabled() and p.locator('#load-button').is_disabled())
    s.shot('E-loading')
    p.keyboard.press('Escape')
    s.check('E closing the panel does not stop the load', s.chip().startswith('Loading'))
    s.wait_chip('^Running ' + re.escape(FINAL) + '$', timeout=120000)
    s.wait_toast('^' + re.escape(FINAL) + r' loaded on 4 devices\.$')
    s.switch_raw({'load_preset': None, 'load_seconds': None})
    s.click('#save-chip', count=False)
    s.equal('E Running: panel title', s.text('#save-panel-title'), 'Running ' + FINAL + '')
    text = chip_body(s)
    s.match('E Running: loaded when and on how many', text, r'Loaded (just now|\d+ (seconds?|minutes?) ago|less than a minute ago|[a-z ]+ago) on all 4 devices\.')
    s.check('E Running: Your latest save and Before loading', 'Your latest save:' in text and 'Before loading: backed up automatically' in text, text)
    s.equal('E Running: Undo this load and What changed', [p.locator('#load-undo').inner_text(), p.locator('#load-details').inner_text()], ['Undo this load', 'What changed'])
    s.check('E Running: the waiting save is one line with Show', 'Also: 1 save to upload.' in text and s.visible('#save-also-show'), text)
    s.shot('E-running')
    s.click('#load-details', count=False)
    expect(p.locator('#restore-job-dialog')).to_be_visible(timeout=10000)
    s.check('E What changed opens today\'s restore job window', True)
    p.locator('#restore-job-dialog .close, #restore-job-dialog [aria-label="Close"]').first.click()
    s.no_errors('E load in three clicks, Running')

    # an upload of the older waiting save does not end Running (the save's time is when it read the devices)
    s.click('#save-chip', count=False) if not s.visible('#save-panel') else None
    s.click('#save-also-show', count=False)
    expect(p.locator('#save-upload')).to_be_enabled(timeout=20000)
    s.click('#save-upload', count=False)
    s.wait_toast(r'^Uploaded to ')
    p.wait_for_timeout(4500)
    s.equal('E an upload after the load leaves the chip Running', s.chip(), 'Running ' + FINAL + '')

    # ---- Undo this load ------------------------------------------------------------------------------------------------------------------
    s.click('#save-chip', count=False) if not s.visible('#save-panel') else None
    s.click('#load-undo', count=False)
    expect(p.locator('#load-run')).to_be_visible(timeout=30000)
    s.equal('E Undo this load: an ordinary confirmation', p.locator('#load-panel-body .save-state').inner_text(), 'Undo loading ' + FINAL + '?')
    load_and_wait(s, '^Running the configuration from before ' + re.escape(FINAL) + '$')
    s.check('E Undo this load: the chip names what runs', True)
    s.wait_toast(r'^The configuration from before .+ loaded on 4 devices\.$')
    s.no_errors('E undo')

    # ---- results: one not loaded, Try <device> again; one kept previous; one not confirmed ---------------------------------------
    s.switch(load_preset='one-failed')
    open_list(s)
    choose(s, FINAL)
    load_and_wait(s, r'^Loaded \d of 4$')
    s.click('#save-chip', count=False) if not s.visible('#save-panel') else None
    expect(p.locator('#load-retry')).to_be_visible(timeout=10000)
    rows = devices(s, '#save-panel-body')
    s.equal('E one not loaded: the device reads Not loaded', rows.get('xrv9k'), 'Not loaded')
    s.match('E one not loaded: the panel title counts', s.text('#save-panel-title'), r'^Loaded on \d of 4 devices$')
    s.equal('E one not loaded: Try xrv9k again', s.text('#load-retry'), 'Try xrv9k again')
    s.check('E one not loaded: Undo this load and Details', s.visible('#load-undo') and s.text('#load-details') == 'Details')
    s.check('E no toast for a load that did not succeed', not [t for t in s.toasts() if 'loaded on' in t], s.toasts())
    s.shot('E-partial')
    s.switch(load_preset=None)
    s.click('#load-retry', count=False)
    expect(p.locator('#load-run')).to_be_visible(timeout=30000)
    s.equal('E Try xrv9k again: only that device is listed', list(devices(s)), ['xrv9k'])
    s.check('E Try xrv9k again: the line says so', 'Only the devices that were not loaded are listed.' in body(s))
    load_and_wait(s, '^(Running ' + re.escape(FINAL) + r'|Loaded \d of \d)$')
    s.wait_toast('^' + re.escape(FINAL) + r' loaded on 1 device\.$')
    s.no_errors('E one not loaded, Try again')

    for preset, word, sentence in [('one-rolled-back', 'Kept previous', r'xrv9k undid the change and runs its previous configuration again\.'),
                                   ('one-uncertain', 'Not confirmed', r'The manager could not confirm what xrv9k runs\. Open Details before relying on it\.')]:
        s.switch(load_preset=preset)
        if s.visible('#save-panel'):
            p.keyboard.press('Escape')
        open_list(s)
        choose(s, 'Broken')
        load_and_wait(s, r'^Loaded \d of 4$')
        s.click('#save-chip', count=False) if not s.visible('#save-panel') else None
        expect(p.locator('#save-panel-body ul.save-devices')).to_be_visible(timeout=10000)
        s.equal('E %s: the device reads %s' % (preset, word), devices(s, '#save-panel-body').get('xrv9k'), word)
        s.match('E %s: the sentence' % preset, chip_body(s), sentence)
        s.shot('E-' + preset)
        s.switch(load_preset=None)
        s.action('reset')
        s.switch(capture_seconds=1, restore_capture_seconds=1)
    s.no_errors('E kept previous, not confirmed')

    # ---- a subset state; a state saved on a different topology ----------------------------------------------------------------------
    p.keyboard.press('Escape') if s.visible('#save-panel') else None
    open_list(s)
    choose(s, 'Junos-only')
    rows = devices(s)
    s.check('E subset: the devices the state does not hold read Not in this state, unticked', rows.get('ceos') == 'Not in this state' and rows.get('xrv9k') == 'Not in this state', rows)
    s.check('E subset: the sentence', 'This state covers 2 of your 4 devices. The others are left as they are.' in body(s), body(s))
    s.shot('E-subset')
    s.click('#load-cancel', count=False)
    choose(s, 'Other-topology')
    s.match('E different topology: the line', body(s), r'Saved on a different topology: 3 of 4 devices match\.')
    s.equal('E different topology: View its topology', s.text('#load-topology'), 'View its topology')
    s.shot('E-other-topology')
    s.click('#load-topology', count=False)
    expect(p.locator('#save-drawer')).to_be_visible(timeout=10000)
    expect(p.locator('#save-drawer-content details[open] pre').first).to_be_visible(timeout=15000)
    s.equal('E View its topology: the drawer shows the state\'s files', s.text('#save-drawer-title'), 'View files')
    s.check('E View its topology: the topology file is open and is the state\'s own (it has the node ceos2)', 'ceos2' in p.locator('#save-drawer-content details[open] pre').first.inner_text())
    s.click('#save-drawer-close', count=False)
    s.no_errors('E subset, different topology')

    # ---- a stopped lab -------------------------------------------------------------------------------------------------------------------
    s.action('lab_state', lab='restore-square', state='stopped')
    s.open_lab('restore-square')
    s.wait_js("document.getElementById('lab-state').textContent!=='Running'", timeout=40000, what='the lab to read stopped')
    s.click('#load-button', count=False)
    expect(p.locator('#load-start')).to_be_visible(timeout=15000)
    s.check('E a stopped lab: Start the lab to load a state, with Start lab', 'Start the lab to load a state' in body(s) and s.text('#load-start') == 'Start lab', body(s))
    s.shot('E-stopped')
    p.keyboard.press('Escape')
    s.action('lab_state', lab='restore-square', state='running')
    s.no_errors('E stopped lab')

    # ---- a lab with no saves of its own and no save location still offers the lab states --------------------------------------------
    s.switch(list_first='Archtop-Lab')
    s.open_lab('square-fresh')
    s.click('#load-button', count=False)
    expect(p.locator('#load-panel-body .save-list').first).to_be_visible(timeout=20000)
    text = body(s)
    s.check('E a lab without a save location: the lab states of the default repository', 'This lab has no saves of its own yet. You can start from one of these.' in text and 'lab states' in text.lower() and re.search(r'From [\w-]+\.', text), text)
    s.check('E a lab without saves: no Your saves group', 'your saves' not in text.lower())
    s.shot('E-fresh-lab')
    loadable = p.locator('#load-panel-body .save-list > li:not(.off) button.save-item')
    name = loadable.first.locator('span').first.inner_text().split('\n')[0]
    s.click(loadable.first, count=False)
    expect(p.locator('#load-run')).to_be_visible(timeout=30000)
    s.equal('E a lab without a save location: a state can be chosen and is confirmed', p.locator('#load-panel-body .save-state').inner_text(), 'Load %s?' % name)
    s.check('E a lab without a save location: the source names the repository', '"repository":"reg-' in s.calls('/restore/preflight')[-1], s.calls('/restore/preflight')[-1])
    # The default repository of this fixture run holds another lab's states: none of its devices is in this lab, and the page says so.
    if p.locator('#load-run').is_disabled():
        s.check('E a state of another lab: Load is disabled with the reason per device', 'None of the devices can be loaded right now.' in body(s) and set(devices(s).values()) <= {'Not in this lab', 'Not in this state'}, body(s))
    else:
        load_and_wait(s, r'^Running ' + re.escape(name) + '$')
        s.check('E a lab without a save location: the state is loaded', True)
    s.no_errors('E fresh lab')
    return s.finish()


if __name__ == '__main__':
    sys.exit(main())
