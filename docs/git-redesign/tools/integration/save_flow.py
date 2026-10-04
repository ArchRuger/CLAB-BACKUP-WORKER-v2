"""Areas A and B: the header on every lab tab, the chip states a save reaches, and saving end to end (PROMPT 5.1 to 5.3).

Needs a fresh fixture (docs/git-redesign/tools/fixture/SCENARIOS.md). Fixture evidence only.
"""
import re
import sys

from common import Session, arguments, expect, wait_until

EXPOSURE = 'Saved files can contain passwords or keys.'
IDENTITY = ('Git commit identity is missing or invalid. As the registered Linux owner, run guided Git setup or set user.name and '
            'user.email inside this checkout, then retry the original save.')


def panel_text(s):
    return s.page.locator('#save-panel-body').inner_text()


def page_fetch(s, method, path, body=None):
    """A request the page itself makes (same origin, so the manager's guard accepts it)."""
    return s.page.evaluate("""async([method,path,body])=>{const r=await fetch(path,{method,headers:body?{'Content-Type':'application/json'}:{},body:body?JSON.stringify(body):undefined});
      let data=null;try{data=await r.json();}catch{}return {status:r.status,data};}""", [method, path, body])


def save_and_wait(s, pattern='to upload'):
    s.click('#git-save-progress')
    s.wait_chip('Saving…', timeout=5000)
    s.wait_chip(pattern, timeout=40000)


def main():
    args = arguments(__doc__)
    s = Session(args.base, args.headed)
    p = s.page
    lab = s.lab_id('restore-square')

    # ---- A: the header on every lab tab -------------------------------------------------------------------------
    s.open_lab('restore-square')
    for tab in ['topology', 'devices', 'progress', 'tools', 'advanced']:
        s.click('#tab-' + tab, count=False)
        boxes = [p.locator(sel).bounding_box() for sel in ['#save-chip', '#git-save-progress', '#load-button', '#lab-actions-button']]
        s.check('A header on the %s tab: chip, Save, Load, Lab actions visible' % tab, all(boxes))
        s.check('A header on the %s tab: the four controls share one row at 1440' % tab, all(boxes) and len({round(b['y'] + b['height'] / 2) for b in boxes}) == 1,
                [b and (b['y'], b['height']) for b in boxes])
        s.check('A header on the %s tab: order chip, Save, Load, Lab actions' % tab, all(boxes) and [b['x'] for b in boxes] == sorted(b['x'] for b in boxes))
    s.click('#tab-topology', count=False)
    s.match('A chip Saved', s.chip(), r'^Saved (\d+ (min|h) ago|just now|yesterday)$')
    s.check('A chip dot of Saved is ok', 'ok' in p.locator('#save-chip-dot').get_attribute('class'))
    s.equal('A no inline style on /', [x for x in s.inline_styles() if not x.endswith(':')], [])

    # the panel at rest (PROMPT 5.6)
    s.click('#save-chip', count=False)
    text = panel_text(s)
    s.match('A rest panel title', s.text('#save-panel-title'), r'^Saved \d+ (minutes?|hours?) ago$')
    s.equal('A rest panel: the save name in the editable field', p.locator('#save-name').input_value(), 'Interface descriptions cleaned up')
    s.check('A rest panel: Keep as a checkpoint present', s.visible('#save-keep'))
    for want in ['Running: your latest save', 'Uploaded: yes, to github.com', 'Saves to: Nested-Labs › BGP', 'All versions', 'Save as a lab state…', 'Save settings']:
        s.check('A rest panel shows "%s"' % want, want in text.replace('\n', ' ').replace('  ', ' '), text)
    p.keyboard.press('Escape')
    s.equal('A Escape closes the chip panel and focus returns to the chip', s.focused(), 'save-chip')
    s.click('#save-chip', count=False)
    p.mouse.click(300, 600)
    s.check('A an outside click closes the chip panel', not s.visible('#save-panel'))

    # ---- B: Save with nothing changed --------------------------------------------------------------------------
    s.reset_counts()
    s.click('#git-save-progress')
    s.wait_chip('Saving…', timeout=5000)
    s.check('B Save starts at once: nothing typed', s.typed == 0 and s.clicks == 1)
    s.equal('B the Saving panel opens by itself', s.text('#save-panel-title'), 'Saving…')
    s.match('B the Saving sentence', panel_text(s), r'Reading the configuration of 4 devices\. You can keep working\.')
    s.check('B Save is disabled while saving', p.locator('#git-save-progress').is_disabled())
    s.check('B the chip dot pulses (busy)', 'busy' in p.locator('#save-chip-dot').get_attribute('class'))
    s.shot('B-saving')
    s.wait_toast(r'^Nothing changed since your last save\.$')
    s.wait_chip('^Saved ')
    p.wait_for_timeout(400)
    s.check('B nothing changed: the panel that showed Saving closes', not s.visible('#save-panel'))
    s.no_errors('B unchanged save')

    # ---- B: two devices changed: the waiting panel, Not now, See changes, Details --------------------------------
    s.action('edit_device', device='ceos', add=['interface Loopback77', '   description i1-integration'], remove=[])
    s.action('edit_device', device='xrv9k', add=['hostname xrv9k-i1'], remove=[])
    p.wait_for_timeout(5200)   # the toast of the save before is gone
    s.reset_counts()
    save_and_wait(s, r'^1 save to upload$')
    expect(p.locator('#save-panel')).to_be_visible()
    expect(p.locator('#save-upload')).to_be_enabled(timeout=15000)
    s.equal('B waiting: the panel opens by itself', s.text('#save-panel-title'), 'Not uploaded yet')
    s.match('B waiting: the sentence', s.text('#save-changes'), r'^2 devices changed since your last save: ceos and xrv9k\. \d+ lines? added, \d+ removed\.$')
    s.equal('B waiting: the destination line', s.text('#save-to'), 'To: Nested-Labs › BGP')
    s.check('B waiting: Upload enabled once the review arrived', p.locator('#save-upload').is_enabled())
    for sel, label in [('#save-not-now', 'Not now'), ('#save-see', 'See changes'), ('#save-details', 'Details')]:
        s.equal('B waiting: ' + label, s.text(sel), label)
    s.check('B waiting: the exposure sentence', EXPOSURE in panel_text(s))
    s.check('B waiting: no toast', not s.toasts(), s.toasts())
    s.check('B waiting: chip dot warn', 'warn' in p.locator('#save-chip-dot').get_attribute('class'))
    s.shot('B-waiting')
    s.click('#save-not-now')
    s.check('B Not now closes the panel', not s.visible('#save-panel'))
    s.equal('B Not now: the chip stays Waiting', s.chip(), '1 save to upload')
    s.equal('B Not now: focus returns to the chip', s.focused(), 'save-chip')
    s.check('B Not now: no toast (DESIGN.md 7.6)', not s.toasts(), s.toasts())

    s.click('#save-chip')
    expect(p.locator('#save-upload')).to_be_enabled(timeout=15000)
    s.click('#save-see')
    expect(p.locator('#save-drawer')).to_be_visible()
    expect(p.locator('#save-drawer-content .diff-file').first).to_be_visible(timeout=15000)
    s.equal('B What changed: title', s.text('#save-drawer-title'), 'What changed')
    entries = p.locator('#save-drawer-content details.diff-file > summary').all_inner_texts()
    s.check('B What changed: one entry per device (ceos, xrv9k), the restore artifact is not a second one', sum('ceos' in e for e in entries) == 1 and sum('xrv9k' in e for e in entries) == 1, entries)
    job = [j for j in s.api_state()['git_jobs'] if j['lab_id'] == lab and j['status'] == 'review_pending'][0]
    drawer = p.locator('#save-drawer-content').inner_text()
    hidden = p.locator('#save-drawer-content').inner_html()
    names = [f.split('/')[-1] for f in job['changed_files']]
    s.check('B What changed: every file the upload sends is in the drawer', all(n in hidden for n in names), [n for n in names if n not in hidden])
    s.check('B What changed: a real line diff (the added line is shown)', 'Loopback77' in drawer and 'xrv9k-i1' in drawer)
    s.check('B What changed: Upload and Not now at the top', p.locator('#save-drawer-actions [data-save-action="upload"]').is_enabled() and s.visible('#save-drawer-actions [data-save-action="not-now"]'))
    s.shot('B-what-changed')
    s.click('#save-drawer-close')
    s.check('B the drawer closes', not s.visible('#save-drawer'))
    s.equal('B the drawer closed: focus returns to its opener (the chip)', s.focused(), 'save-chip')

    s.click('#save-chip')
    s.click('#save-details')
    expect(p.locator('#git-job-dialog')).to_be_visible()
    s.check('B Details opens today\'s save window with Keep snapshot only', 'Keep snapshot only' in s.text('#git-job-dialog'))
    p.locator('#git-job-dialog .close, #git-job-dialog [aria-label="Close"]').first.click()
    s.no_errors('B waiting, See changes, Details')

    # ---- B: Upload ----------------------------------------------------------------------------------------------
    s.click('#save-chip')
    expect(p.locator('#save-upload')).to_be_enabled(timeout=15000)
    s.click('#save-upload')
    s.wait_toast(r'^Uploaded to github\.com\.$')
    s.wait_chip('^Saved ')
    s.check('B Upload ends in the Saved chip', s.chip().startswith('Saved'))
    p.wait_for_timeout(400)
    s.check('B after the upload the panel is closed', not s.visible('#save-panel'))
    s.no_errors('B upload')

    # ---- B: the name field and Keep as a checkpoint (PROMPT 5.3 step 7) -------------------------------------------
    p.wait_for_timeout(5200)
    s.reset_counts()
    s.click('#save-chip')
    name = p.locator('#save-name')
    expect(name).to_be_visible()
    s.match('B naming: the automatic name', name.input_value(), r'^ceos and xrv9k changed$')
    name.fill('Loopback 77 and a hostname')
    name.press('Enter')
    wait_until(lambda: any(j.get('note') == 'Loopback 77 and a hostname' for j in s.api_state()['git_jobs']), what='the rename')
    s.check('B naming: Enter renames and the panel stays open', s.visible('#save-panel') and p.locator('#save-name').input_value() == 'Loopback 77 and a hostname')
    s.check('B naming: Keep as a checkpoint is a real, enabled tick box', p.locator('#save-keep').is_enabled())
    s.click('#save-keep')
    s.wait_chip(r'^1 save to upload$', timeout=40000)
    expect(p.locator('#save-upload')).to_be_enabled(timeout=15000)
    s.match('B checkpoint: the sentence', s.text('#save-changes'), r'^Checkpoint [Ll]oopback-77-and-a-hostname kept\. It is not uploaded yet\.')
    s.check('B chip -> Keep as a checkpoint is 2 clicks (3 with Upload)', s.clicks == 2, s.clicks)
    s.click('#save-upload')
    s.wait_toast(r'^Uploaded to github\.com\.$')
    s.wait_chip('^Saved ')
    s.no_errors('B naming and checkpoint')

    # ---- B: the upload fails, Try again ----------------------------------------------------------------------------
    p.wait_for_timeout(5200)
    s.action('edit_device', device='ceos', add=['interface Loopback78'], remove=[])
    s.switch(push_fail_once=True)
    save_and_wait(s, r'^1 save to upload$')
    expect(p.locator('#save-upload')).to_be_enabled(timeout=15000)
    s.click('#save-upload')
    s.wait_chip(r'^Upload failed$', timeout=30000)
    expect(p.locator('#save-retry')).to_be_visible(timeout=15000)
    s.equal('B failed: panel title', s.text('#save-panel-title'), 'Upload failed')
    s.match('B failed: the sentence', s.text('#save-changes'), r'^Your save is safe on the lab VM, but (github\.com could not be reached|it could not be uploaded to github\.com)\.')
    s.check('B failed: Try again and Details', s.text('#save-retry') == 'Try again' and s.visible('#save-details'))
    s.check('B failed: chip dot bad', 'bad' in p.locator('#save-chip-dot').get_attribute('class'))
    s.shot('B-upload-failed')
    expect(p.locator('#save-retry')).to_be_enabled(timeout=15000)
    s.click('#save-retry')
    s.wait_toast(r'^Uploaded to github\.com\.$')
    s.wait_chip('^Saved ')
    s.no_errors('B upload failed, Try again')

    # ---- B: two labs of one repository: one upload carries both saves ----------------------------------------------
    p.wait_for_timeout(5200)
    s.action('edit_device', device='ceos', add=['interface Loopback79'], remove=[])
    save_and_wait(s, r'^1 save to upload$')
    expect(p.locator('#save-upload')).to_be_enabled(timeout=15000)
    s.click('#save-not-now')
    edge = [d for d in s.fixture_state()['devices'] if d.startswith('clab-edge-lab-')][0]
    s.action('edit_device', device=edge, add=['interface Loopback90'], remove=[])
    s.open_lab('edge-lab')
    save_and_wait(s, r'^1 save to upload$')
    expect(p.locator('#save-upload')).to_be_enabled(timeout=15000)
    s.match('B two labs: the sentence names the other save and its lab', s.text('#save-changes'), r'This upload also sends 1 other save: .+ \(restore-square\)\.$')
    s.shot('B-two-labs')
    s.click('#save-see')
    expect(p.locator('#save-changes-also')).to_be_visible(timeout=15000)
    s.match('B two labs: the drawer names it too', s.text('#save-changes-also'), r'This upload also sends 1 other save: .+ \(restore-square\)\.')
    also = p.locator('#save-drawer-content details[data-save-also] > summary')
    also.click()
    expect(p.locator('#save-drawer-content details[data-save-also] .diff-file').first).to_be_visible(timeout=15000)
    s.check('B two labs: the other save\'s files open in the drawer', 'Loopback79' in p.locator('#save-drawer-content details[data-save-also]').inner_text())
    s.click('#save-drawer-actions [data-save-action="upload"]')
    s.wait_toast(r'^Uploaded to github\.com\.$')
    s.wait_chip('^Saved ')
    s.check('B two labs: the drawer closes after its Upload', not s.visible('#save-drawer'))
    s.open_lab('restore-square')
    s.match('B two labs: the other lab\'s chip is Saved too (one upload carried both)', s.chip(), '^Saved ')
    s.no_errors('B two labs, one upload')

    # ---- B: a save lands between the review and Upload (409) --------------------------------------------------------
    s.action('edit_device', device='ceos', add=['interface Loopback80'], remove=[])
    save_and_wait(s, r'^1 save to upload$')
    expect(p.locator('#save-upload')).to_be_enabled(timeout=15000)
    stale = p.evaluate("fetch('/api/state').then(r=>r.text())")
    p.route('**/api/state', lambda route: route.fulfill(status=200, content_type='application/json', body=stale))   # the page does not see the other save yet
    s.action('edit_device', device=edge, add=['interface Loopback91'], remove=[])
    s.switch(capture_seconds=1)
    answer = page_fetch(s, 'POST', '/api/labs/%s/git/save' % s.lab_id('edge-lab'),
                        {'request_id': '%032x' % 0x1101, 'target': 'latest', 'checkpoint': '', 'push': True, 'note': '', 'backup_job_id': '', 'replace_baseline': False, 'expected_baseline': '', 'allow_removed': True})
    s.check('B 409: the other lab\'s save was accepted', answer['status'] == 200, answer)
    other = answer['data']['id']
    wait_until(lambda: s.page.request.get(s.base + '/api/git/jobs/' + other).json()['status'] == 'review_pending', timeout=40, what='the other save')
    with s.expect_status(409, r'/api/git/jobs/.+/retry'):
        s.click('#save-upload')
        expect(p.locator('#save-panel-error')).to_have_text(re.compile('Another save was made in this repository'), timeout=15000)
    p.unroute('**/api/state')
    s.equal('B 409: the manager\'s sentence', s.text('#save-panel-error'), 'Another save was made in this repository. Look at the changes again.')
    expect(p.locator('#save-changes')).to_have_text(re.compile(r'This upload also sends 1 other save: .+ \(edge-lab\)\.$'), timeout=15000)
    s.check('B 409: the review is shown again, naming the save that landed', True)
    s.equal('B 409: nothing was uploaded', s.chip(), '1 save to upload')
    s.shot('B-409')
    expect(p.locator('#save-upload')).to_be_enabled(timeout=15000)
    s.click('#save-upload')
    s.wait_toast(r'^Uploaded to github\.com\.$')
    s.wait_chip('^Saved ')
    s.switch(capture_seconds=None)
    s.no_errors('B 409 path')

    # ---- B: the map and the topology are named in the sentence and shown in the drawer -----------------------------
    p.wait_for_timeout(5200)
    document = page_fetch(s, 'GET', '/api/labs/%s/map-document' % lab)['data']
    moved = document['annotations'].replace('"x": 0,', '"x": 40,', 1)
    put = page_fetch(s, 'PUT', '/api/labs/%s/map-document' % lab, {'annotations': moved, 'revision': document['revision']})
    s.check('B map: the manager accepted the changed map', put['status'] == 200 and moved != document['annotations'], put)
    save_and_wait(s, r'^1 save to upload$')
    expect(p.locator('#save-upload')).to_be_enabled(timeout=15000)
    s.match('B map: the sentence names the map', s.text('#save-changes'), r'^The map changed since your last save\.')
    s.click('#save-see')
    expect(p.locator('#save-drawer-content .diff-file').first).to_be_visible(timeout=15000)
    entries = p.locator('#save-drawer-content details.diff-file > summary').all_inner_texts()
    s.check('B map: the drawer has the Map entry', any(e.startswith('Map') for e in entries), entries)
    s.shot('B-map-changed')
    s.click('#save-drawer-actions [data-save-action="upload"]')
    s.wait_toast(r'^Uploaded to github\.com\.$')
    s.wait_chip('^Saved ')
    s.no_errors('B map change')

    # ---- A: Can't save, by cause (DESIGN.md 3.6) ------------------------------------------------------------------
    p.wait_for_timeout(5200)
    causes = [({'status_problem': 'staged'}, 'Someone is working in this repository on the VM.', ['Try again', 'Details']),
              # The fixture's own `permission` sentence is one the helper's `status` never answers (it belongs to `connect`), so the
              # manager has no code for it; a sentence `status` really answers is used instead.
              ({'status_problem': IDENTITY}, 'The VM account cannot upload to github.com.', ['Try again', 'Details']),
              ({'vm_unreachable': True}, 'The lab VM could not be reached.', ['Try again', 'Check the VM connection…']),
              ({'device_unreadable': ['xrv9k']}, 'xrv9k could not be read, so nothing was saved.', ['Try again', 'Save settings', 'Details'])]
    for switches, sentence, buttons in causes:
        s.action('reset')
        s.action('edit_device', device='ceos', add=['interface Loopback8%d' % (causes.index((switches, sentence, buttons)) + 1)], remove=[])
        s.switch_raw(switches)
        key = list(switches)[0] + '=' + str(list(switches.values())[0])[:12]
        with s.expect_status(409, r'/api/labs/.+/git/(save|settings)'), s.expect_status(502, r'/api/'), s.expect_status(503, r'/api/'):
            s.click('#git-save-progress')
            s.wait_chip(r'^Can’t save$', timeout=40000)
            expect(p.locator('#save-cant-why')).to_be_visible(timeout=15000)
            s.equal('A Can\'t save (%s): the sentence' % key, s.text('#save-cant-why'), sentence)
            got = p.locator('#save-panel-body .save-row').first.locator('button').all_inner_texts()
            s.equal('A Can\'t save (%s): the actions' % key, got, buttons)
            s.check('A Can\'t save (%s): chip dot bad' % key, 'bad' in p.locator('#save-chip-dot').get_attribute('class'))
            s.shot('A-cant-%d' % causes.index((switches, sentence, buttons)))
            s.action('reset')
            s.click('#save-cant-again')
            s.wait_chip(r'^(1 save to upload|Saved .*)$', timeout=60000)
        s.check('A Can\'t save (%s): Try again saves once the cause is gone' % key, True)
        if s.visible('#save-upload'):
            expect(p.locator('#save-upload')).to_be_enabled(timeout=15000)
            s.click('#save-upload')
            s.wait_toast(r'^Uploaded to github\.com\.$')
            s.wait_chip('^Saved ')
        p.keyboard.press('Escape')
        p.wait_for_timeout(5200)
    s.no_errors('A Can\'t save causes')

    # ---- A: Not saved yet ------------------------------------------------------------------------------------------
    s.open_lab('square-fresh')
    s.equal('A chip Not saved yet', s.chip(), 'Not saved yet')
    s.check('A Not saved yet: hollow dot', 'none' in p.locator('#save-chip-dot').get_attribute('class'))
    s.no_errors('A not saved')
    return s.finish()


if __name__ == '__main__':
    sys.exit(main())
