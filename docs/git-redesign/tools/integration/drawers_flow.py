"""Areas F and G: All versions, Save settings and Save as a lab state… (PROMPT 5.5, 5.7, 5.8), and the click counts of the
friction budget this script owns (PROMPT 9.5). Needs a fresh fixture. Fixture evidence only.
"""
import re
import sys

from common import Session, arguments, dump, expect, wait_until


def content(s):
    return s.page.locator('#save-drawer-content').inner_text()


def open_row(s, name):
    p = s.page
    row = p.locator('#save-drawer-content .save-list > li').filter(has=p.locator('button.save-item > span:first-child', has_text=re.compile('^' + re.escape(name) + '$'))).first
    row.locator('button.save-item').click()
    expect(row).to_have_class(re.compile('open'))
    return row


def main():
    args = arguments(__doc__)
    s = Session(args.base, args.headed, args.viewport)
    p = s.page
    s.switch(capture_seconds=1, restore_capture_seconds=1)
    s.open_lab('restore-square')

    # ---- F: All versions ------------------------------------------------------------------------------------------------------
    s.click('#save-chip')
    s.click('#save-all')
    expect(p.locator('#save-drawer-content .save-list').first).to_be_visible(timeout=20000)
    s.equal('F All versions: title', s.text('#save-drawer-title'), 'All versions')
    headings = [h.lower() for h in p.locator('#save-drawer-content h3.save-heading').all_inner_texts()]
    s.equal('F All versions: the groups', headings, ['your saves', 'checkpoints', 'starting point', 'lab states'])
    folds = p.locator('#save-drawer-content > details > summary').all_inner_texts()
    s.check('F All versions: other labs and the save activity are folded', any(f.startswith('Other labs in this repository') for f in folds) and all(not d for d in p.locator('#save-drawer-content > details').evaluate_all('ds=>ds.filter(d=>/Other labs/.test(d.textContent)).map(d=>d.open)')), folds)
    s.equal('F All versions: it ends with Full history… and Browse the repository…', p.locator('#save-drawer-content .save-foot button').all_inner_texts(), ['Full history…', 'Browse the repository…'])
    s.shot('F-all-versions')
    row = open_row(s, 'Broken')
    s.equal('F a lab state opens in place with its actions', row.locator('button[data-save-action]').all_inner_texts(), ['Load this state…', 'See what’s different', 'View files', 'Download ZIP'])
    row = open_row(s, 'Interface descriptions cleaned up')
    actions = row.locator('button[data-save-action]').all_inner_texts()
    s.check('F your own save also offers Keep as a checkpoint and Use as starting point…', 'Keep as a checkpoint' in actions and 'Use as starting point…' in actions and 'View files' in actions, actions)
    row = open_row(s, 'plan-sept')
    s.check('F a design export is view and download only', row.locator('[data-save-action="load"]').is_disabled() and 'Design plan: view and download only' in row.inner_text(), row.inner_text())
    row = open_row(s, 'Start')
    s.check('F a state without the files Load needs: Load this state… is disabled with the reason', row.locator('[data-save-action="load"]').is_disabled() and 'saved without the files needed to load it' in row.inner_text(), row.inner_text())
    row = open_row(s, 'Broken')
    row.locator('[data-save-action="files"]').click()
    expect(p.locator('#save-drawer-content details').first).to_be_visible(timeout=15000)
    s.equal('F View files: title, with Back', [s.text('#save-drawer-title'), s.visible('#save-drawer-back')], ['View files', True])
    s.check('F View files: devices, the topology file and the map', 'Topology file' in content(s) and 'Map' in content(s) and 'ceos' in content(s), content(s)[:300])
    s.click('#save-drawer-back', count=False)
    expect(p.locator('#save-drawer-content .save-list').first).to_be_visible(timeout=20000)
    s.equal('F Back returns to All versions', s.text('#save-drawer-title'), 'All versions')
    row = open_row(s, 'Broken')
    row.locator('[data-save-action="different"]').click()
    expect(p.locator('#save-drawer-title')).to_have_text('Different from your latest save', timeout=15000)
    expect(p.locator('#save-drawer-content .diff-file, #save-drawer-content .save-note').first).to_be_visible(timeout=15000)
    s.check('F See what\'s different: saved against saved, with Back', s.visible('#save-drawer-back'))
    s.click('#save-drawer-back', count=False)
    row = open_row(s, 'Broken')
    with p.expect_download() as download:
        row.locator('[data-save-action="zip"]').click()
    s.check('F Download ZIP downloads a file', download.value.suggested_filename.endswith('.zip'), download.value.suggested_filename)
    row.locator('[data-save-action="load"]').click()
    expect(p.locator('#load-run')).to_be_visible(timeout=30000)
    s.check('F Load this state… ends in the Load confirmation, the drawer closed', not s.visible('#save-drawer') and p.locator('#load-panel-body .save-state').inner_text() == 'Load Broken?')
    p.keyboard.press('Escape')
    s.no_errors('F All versions')

    # ---- F: Save settings -------------------------------------------------------------------------------------------------------
    s.click('#save-chip')
    s.click('#save-settings')
    expect(p.locator('#save-drawer-content .save-settings')).to_be_visible(timeout=20000)
    expect(p.locator('#save-drawer-content input[name="git-node"]').first).to_be_visible(timeout=20000)
    s.equal('F Save settings: title', s.text('#save-drawer-title'), 'Save settings')
    text = content(s)
    for want in ['Change folder…', 'Use a different repository…', 'Connect by URL…', 'Disconnect this lab…', 'Save settings']:
        s.check('F Save settings has ' + want, want in text, text[:200])
    ticks = p.locator('#save-drawer-content input[name="git-node"]')
    s.check('F Save settings: the devices of every save, as real tick boxes with labels', ticks.count() == 4 and all(ticks.nth(i).is_checked() for i in range(4)) and p.locator('#save-drawer-content label:has(input[name="git-node"])').count() == 4)
    s.check('F Save settings: a lab with its topology has no "device configurations only" sentence', 'so saves hold device configurations only' not in text)
    p.locator('#save-git-details > summary').click()
    s.equal('F Save settings: Git details with Refresh status and Update from the repository', p.locator('#save-git-details .save-row button').all_inner_texts(), ['Refresh status', 'Update from the repository'])
    s.shot('F-save-settings')
    p.locator('#save-git-details [data-git-repo-action="update"]').click()
    expect(p.locator('#git-update-dialog')).to_be_visible(timeout=10000)
    p.locator('#git-update-confirm').click()
    s.wait_toast(r'(?i)up to date|updated', timeout=30000)
    s.check('F Update from the repository runs', True)
    # leave a device out, Save settings
    s.click('#save-chip', count=False)
    s.click('#save-settings', count=False)
    expect(p.locator('#save-drawer-content input[name="git-node"]').first).to_be_visible(timeout=20000)
    p.locator('#save-drawer-content input[name="git-node"]').nth(3).uncheck()
    s.check('F Save settings: the sentence about the device left out', 'is no longer included. Its saved file is removed with the next save; older versions keep it.' in content(s))
    p.locator('#save-drawer-content [data-save-action="save-settings"]').click()
    s.wait_toast(r'^Save settings updated\.$')
    wait_until(lambda: len([l for l in s.api_state()['labs'] if l['name'] == 'restore-square'][0]['git_binding']['node_names']) == 3, what='the selection')
    s.check('F Save settings: the selection is saved', True)
    p.locator('#save-drawer-content input[name="git-node"]').nth(3).check()
    p.locator('#save-drawer-content [data-save-action="save-settings"]').click()
    s.wait_toast(r'^Save settings updated\.$')
    # Change folder… opens the chooser with Back to the settings
    p.locator('#save-drawer-content [data-save-action="folder"]').click()
    expect(p.locator('#folder-tree')).to_be_visible(timeout=20000)
    s.check('F Change folder… opens the chooser inside the drawer, with Back', s.visible('#save-drawer-back') and s.text('#save-drawer-title') == 'Where should restore-square save?')
    s.click('#save-drawer-back', count=False)
    expect(p.locator('#save-drawer-content .save-settings')).to_be_visible(timeout=20000)
    # Disconnect this lab… (edge-lab, so restore-square keeps its place)
    s.click('#save-drawer-close', count=False)
    s.equal('F the drawer closed: focus returns to the chip', s.focused(), 'save-chip')
    s.open_lab('edge-lab')
    s.click('#save-chip', count=False)
    s.click('#save-settings', count=False)
    expect(p.locator('#save-drawer-content [data-git-repo-action="unlink"]')).to_be_visible(timeout=20000)
    p.locator('#save-drawer-content [data-git-repo-action="unlink"]').click()
    expect(p.locator('#git-unlink-dialog')).to_be_visible(timeout=10000)
    p.locator('#git-unlink-confirm').click()
    wait_until(lambda: not [l for l in s.api_state()['labs'] if l['name'] == 'edge-lab'][0].get('git_binding'), what='the disconnect')
    s.check('F Disconnect this lab… disconnects', True)
    p.wait_for_timeout(500)
    s.no_errors('F Save settings')

    # ---- F and G: Save as a lab state… ------------------------------------------------------------------------------------------
    s.open_lab('restore-square')
    s.reset_counts()
    s.click('#save-chip')
    s.click('#save-as-state')
    expect(p.locator('#state-name')).to_be_visible(timeout=20000)
    s.equal('F Save as a lab state: title', s.text('#save-drawer-title'), 'Save as a lab state')
    s.equal('F Save as a lab state: the one-click names', p.locator('.folder-names button').all_inner_texts(), ['start', 'broken', 'final'])
    s.click('.folder-names [data-state-name="start"]')
    s.wait_js("!/Checking/.test(document.getElementById('folder-answer').textContent)&&document.getElementById('folder-path').value==='BGP/start'")
    s.equal('F Save as a lab state: the result line (beside the lab\'s own saves, DESIGN.md 6)', s.text('#folder-result').replace('\n', ' '), 'The state is saved in Nested-Labs › BGP/start')
    s.equal('F an existing state: the question', s.text('#folder-answer'), '“Start” already exists here.')
    s.equal('F an existing state: its answers', p.locator('#folder-foot button').all_inner_texts(), ['Cancel', 'Replace it', 'Use another name'])
    s.shot('F-lab-state-question')
    s.click('#folder-foot [data-folder-action="use-another-name"]', count=False)
    s.equal('F Use another name: focus is in the name field', s.focused(), 'state-name')
    # a new name, typed: chip, Save as a lab state…, Save state = 3 clicks plus the name
    s.click('#folder-foot [data-folder-action="cancel"]', count=False)
    s.reset_counts()
    s.click('#save-chip')
    s.click('#save-as-state')
    expect(p.locator('#state-name')).to_be_visible(timeout=20000)
    s.fill('#state-name', 'mine')
    s.wait_js("!/Checking/.test(document.getElementById('folder-answer').textContent)&&document.getElementById('folder-path').value==='BGP/mine'&&!document.querySelector('#folder-foot [data-folder-primary][disabled]')")
    s.equal('F a new state: the result line', s.text('#folder-result').replace('\n', ' '), 'The state is saved in Nested-Labs › BGP/mine')
    s.click('#folder-foot [data-folder-action="save"]')
    s.wait_toast(r'^State Mine saved in BGP/mine\.$')
    s.check('G save as a lab state: 3 clicks plus the name (at most 4)', s.clicks == 3 and s.typed == 1, (s.clicks, s.typed))
    s.wait_chip(r'^1 save to upload$', timeout=40000)
    s.check('F the lab\'s own save location did not change', [l for l in s.api_state()['labs'] if l['name'] == 'restore-square'][0]['git_binding']['repository']['prefix'] == 'BGP')
    s.click('#save-chip', count=False) if not s.visible('#save-panel') else None
    expect(p.locator('#save-upload')).to_be_enabled(timeout=20000)
    s.match('F a lab state ends waiting for upload with the same sentence as any save', s.text('#save-changes'), r'^This is the first save here: 4 devices, the topology and the map\.$')
    s.equal('F a lab state: its destination', s.text('#save-to'), 'To: Nested-Labs › BGP/mine')
    s.click('#save-upload', count=False)
    s.wait_toast(r'^Uploaded to ')
    # the state made here is a lab state in the Load panel
    p.keyboard.press('Escape') if s.visible('#save-panel') else None
    s.click('#load-button', count=False)
    expect(p.locator('#load-panel-body .save-list').first).to_be_visible(timeout=20000)
    s.check('F the new state is listed under Lab states as Mine', 'Mine' in p.locator('#load-panel-body .save-list').nth(1).inner_text(), p.locator('#load-panel-body').inner_text()[:900] + ' || ' + dump(p.evaluate("fetch('/api/labs/'+activeId+'/restore/states').then(r=>r.text()).catch(e=>String(e))"))[:1500])
    p.keyboard.press('Escape')
    # one click with a one-click name: chip, Save as a lab state…, final, Replace it
    s.reset_counts()
    s.click('#save-chip')
    s.click('#save-as-state')
    expect(p.locator('#state-name')).to_be_visible(timeout=20000)
    s.click('.folder-names [data-state-name="broken"]')
    expect(p.locator('#folder-foot [data-folder-choice="take"]')).to_be_enabled(timeout=20000)
    s.click('#folder-foot [data-folder-choice="take"]')
    s.wait_toast(r'^State Broken saved in BGP/broken\.$')
    s.check('G save as a lab state with a one-click name over an existing state: 4 clicks, nothing typed', s.clicks == 4 and s.typed == 0, (s.clicks, s.typed))
    s.wait_chip(r'^1 save to upload$', timeout=40000)
    s.no_errors('F Save as a lab state')

    # All versions also offers Save as a lab state…
    s.click('#save-chip', count=False) if not s.visible('#save-panel') else None
    s.click('#save-all', count=False)
    expect(p.locator('#save-drawer-content [data-save-action="state"]')).to_be_visible(timeout=20000)
    p.locator('#save-drawer-content [data-save-action="state"]').click()
    expect(p.locator('#state-name')).to_be_visible(timeout=20000)
    s.check('F All versions offers Save as a lab state…, with Back', s.visible('#save-drawer-back'))
    s.equal('F no inline style on / with a drawer open', [x for x in s.inline_styles() if not x.endswith(':')], [])
    s.no_errors('F All versions, Save as a lab state…')
    return s.finish()


if __name__ == '__main__':
    sys.exit(main())
