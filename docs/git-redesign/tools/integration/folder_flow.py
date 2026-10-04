"""Areas C and D: the first save (PROMPT 5.9) and the folder chooser (PROMPT 6.2, 6.3).

Every row of the 6.2 table must end in a saved place or in a question with buttons, never in a refusal, and New folder…
must be enabled in every state. Needs a fresh fixture. Fixture evidence only.
"""
import re
import sys

from common import Session, arguments, expect, wait_until
from save_flow import page_fetch

NESTED = 'Nested-Labs'      # the fixture's repositories (SCENARIOS.md)
BIG = 'Big-Repo'


def place_of(s, lab):
    found = [l for l in s.api_state()['labs'] if l['name'] == lab][0].get('git_binding')
    if not found:
        return None
    repo = found['repository']
    return repo['path'].rstrip('/').split('/')[-1] + ':' + (repo.get('prefix') or '')


def open_chooser(s):
    """The chooser from the chip panel: Change… for a lab with a save location, Choose another place for one without."""
    p = s.page
    if not s.visible('#save-panel'):
        s.click('#save-chip')
    button = p.locator('#save-change, #save-first-place-other').first
    expect(button).to_be_visible(timeout=15000)
    s.click(button)
    expect(p.locator('#folder-tree')).to_be_visible(timeout=20000)
    new_folder_enabled(s, 'when the chooser opens')


def new_folder_enabled(s, when):
    button = s.page.locator('.folder-chooser [data-folder-action="new"]')
    s.check('D New folder… is enabled ' + when, button.count() == 1 and button.is_enabled())


def repository(s, name):
    """Chooses a repository by its name (the id behind it is the lab's own record once the lab saves there)."""
    p = s.page
    if p.locator('#folder-repo option:checked').inner_text() != name:
        p.locator('#folder-repo').select_option(label=name)
        s.clicks += 1
        expect(p.locator('#folder-tree')).to_be_visible(timeout=20000)
        s.wait_js("document.querySelector('#folder-repo option:checked').textContent===%r&&!!document.getElementById('folder-tree')" % name)
        p.wait_for_timeout(300)


def type_folder(s, text):
    p = s.page
    s.fill('#folder-path', text)
    answer(s)


def answer(s):
    """The sentence under the tree once the manager has answered for the chosen folder."""
    p = s.page
    s.wait_js("(()=>{const a=document.getElementById('folder-answer');return !!a&&!/Checking/.test(a.textContent)&&!document.querySelector('.folder-chooser [data-folder-primary][disabled]');})()", what='the answer for the folder')
    return p.locator('#folder-answer').inner_text()


def press(s, selector, bring=False):
    """Presses a button of the chooser's foot. The line that brings the saved files along is unticked first unless the step is
    about it: a move waits for upload like a save, and every later folder change would then ask question 3."""
    box = s.page.locator('#folder-move input')
    if not bring and box.count() and box.is_checked():
        box.uncheck()
    s.click(selector)


def foot_buttons(s):
    return s.page.locator('#folder-foot button').all_inner_texts()


def no_refusal(s, name):
    s.check(name + ': no refusal', not s.visible('#folder-refused'), s.text('#folder-refused') if s.visible('#folder-refused') else '')


def saved_here(s, lab, want, name):
    """The drawer closed and the lab saves in `want` ("<repository>:<folder>")."""
    p = s.page
    expect(p.locator('#save-drawer')).to_be_hidden(timeout=30000)
    wait_until(lambda: place_of(s, lab) == want, timeout=20, what=name + ': ' + want)
    s.check(name + ': the lab saves in ' + want, place_of(s, lab) == want, place_of(s, lab))


def upload_waiting(s):
    """Upload whatever waits (the chip panel is open or is opened)."""
    p = s.page
    if not s.visible('#save-upload'):
        if s.visible('#save-panel'):
            p.keyboard.press('Escape')
        s.click('#save-chip', count=False)
    expect(p.locator('#save-upload')).to_be_enabled(timeout=20000)
    s.click('#save-upload', count=False)
    s.wait_toast(r'^Uploaded to ')
    s.wait_chip('^Saved ')
    p.wait_for_timeout(300)
    if s.visible('#save-panel'):
        p.keyboard.press('Escape')


def main():
    args = arguments(__doc__)
    s = Session(args.base, args.headed, args.viewport)
    p = s.page
    s.switch(capture_seconds=1)

    # ---- C: the never-saved lab: two clicks, nothing typed --------------------------------------------------------------------
    s.switch(list_first='Archtop-Lab')
    s.open_lab('square-fresh')
    s.reset_counts()
    s.click('#git-save-progress')
    expect(p.locator('#save-first')).to_be_visible(timeout=15000)
    s.equal('C first save: panel title', s.text('#save-panel-title'), 'Not saved yet')
    s.match('C first save: the sentence names the repository and a folder named after the lab', s.text('#save-first-place'), r'^Your first save goes to [\w-]+, in a folder named square-fresh\.$')
    first_repo = re.match(r'^Your first save goes to ([\w-]+),', s.text('#save-first-place')).group(1)
    s.check('C first save: Save, Choose another place and the exposure sentence', s.text('#save-first') == 'Save' and s.text('#save-first-place-other') == 'Choose another place' and 'Saved files can contain passwords or keys.' in p.locator('#save-panel-body').inner_text())
    s.shot('C-first-save')
    s.click('#save-first')
    s.wait_chip(r'^1 save to upload$', timeout=40000)
    s.check('C first save: 2 clicks, nothing typed', s.clicks == 2 and s.typed == 0, (s.clicks, s.typed))
    expect(p.locator('#save-upload')).to_be_enabled(timeout=15000)
    s.equal('C first save: the sentence', s.text('#save-changes'), 'This is the first save here: 4 devices, the topology and the map.')
    s.equal('C first save: the destination', s.text('#save-to'), 'To: %s › square-fresh' % first_repo)
    s.equal('C first save: the lab saves in the folder named after it', place_of(s, 'square-fresh'), first_repo + ':square-fresh')
    upload_waiting(s)
    s.no_errors('C first save')

    # ---- C: Choose another place: the chooser, then the save follows by itself ---------------------------------------------------
    s.open_lab('shared-b')
    s.click('#git-save-progress')
    expect(p.locator('#save-first-place-other')).to_be_visible(timeout=15000)
    open_chooser(s)
    s.equal('C Choose another place: the chooser\'s title', s.text('#save-drawer-title'), 'Where should shared-b save?')
    repository(s, NESTED)
    # D row 1: a folder that does not exist
    type_folder(s, 'brand-new/deeper')
    s.equal('D a folder that does not exist: the sentence', answer(s), 'brand-new/deeper is new. It appears in the repository with the first save.')
    s.check('D a folder that does not exist: listed as New in the tree', p.locator('[data-folder="brand-new/deeper"] .git-tag.pending').inner_text() == 'New')
    s.equal('D a folder that does not exist: one button, Save here', foot_buttons(s), ['Cancel', 'Save here'])
    s.shot('D-new-folder-path')
    press(s, '#folder-foot [data-folder-action="save"]')
    saved_here(s, 'shared-b', 'Nested-Labs:brand-new/deeper', 'D a folder that does not exist')
    s.wait_chip(r'^1 save to upload$', timeout=40000)
    s.check('C Choose another place: the save follows the choice by itself', True)
    upload_waiting(s)
    s.no_errors('C Choose another place, D new folder')

    # ---- D: the chooser, row by row, for a lab that has a save location ---------------------------------------------------------
    def choose(folder, registration=NESTED):
        open_chooser(s)
        repository(s, registration)
        type_folder(s, folder)
        return answer(s)

    # the chip panel's Change… in four clicks: chip, Change…, a folder, Save here
    s.reset_counts()
    del s.sent[:]
    s.click('#save-chip')
    s.click('#save-change')
    expect(p.locator('#folder-tree')).to_be_visible(timeout=20000)
    s.click(p.locator('[data-folder="BGP"] > .folder-row [data-folder-twist]'), count=False) if p.locator('[data-folder="BGP/exercises"]').count() == 0 else None
    s.click('[data-folder="notes"] > .folder-row')
    s.match('D ordinary files, no saved state: the folder is simply chosen', answer(s), r'^$')
    s.check('D the line that brings the saved files along is offered (the lab has saved files, the new folder none)', p.locator('#folder-move input').is_checked())
    s.click('#folder-foot [data-folder-action="save"]')
    saved_here(s, 'shared-b', 'Nested-Labs:notes', 'D an existing folder with ordinary files')
    s.check('D change folder from the chip panel: 4 clicks', s.clicks == 4, s.clicks)
    s.equal('D change folder: one place request, no refusal', len(s.calls('/git/place ')), 1)

    s.wait_toast(r'^shared-b now saves to Nested-Labs › notes\.$')
    s.wait_chip(r'^1 save to upload$', timeout=30000)
    s.click('#save-chip', count=False)
    expect(p.locator('#save-upload')).to_be_enabled(timeout=20000)
    s.equal('D the move waits for upload like a save, with its own sentence', s.text('#save-changes'), 'shared-b’s saved files moved to notes.')
    s.click('#save-see', count=False)
    expect(p.locator('#save-drawer-content')).to_contain_text('This moves the saved files of shared-b from brand-new/deeper to notes. No device file changes.', timeout=15000)
    s.check('D the move in What changed names the folder it left', True)
    s.click('#save-drawer-actions [data-save-action="upload"]', count=False)
    s.wait_toast(r'^Uploaded to ')
    s.wait_chip('^Saved ')
    s.no_errors('D change folder in four clicks, the files brought along')

    # the top level
    open_chooser(s)
    s.click('#folder-tree > [data-folder=""] > .folder-row')
    s.equal('D the top level: the sentence', answer(s), 'shared-b will save at the top level of Nested-Labs.')
    press(s, '#folder-foot [data-folder-action="save"]')
    saved_here(s, 'shared-b', 'Nested-Labs:', 'D the top level (above every lab folder)')

    # inside, above or beside another lab's folder
    for folder in ['BGP/edge/inner', 'BGP-beside', 'BGP/exercises']:
        text = choose(folder)
        no_refusal(s, 'D ' + folder)
        s.equal('D inside, above or beside another lab\'s folder (%s): Save here' % folder, foot_buttons(s), ['Cancel', 'Save here'])
        press(s, '#folder-foot [data-folder-action="save"]')
        saved_here(s, 'shared-b', 'Nested-Labs:' + folder, 'D ' + folder)

    # a folder registered on the VM that no lab uses: invisible, used when chosen
    open_chooser(s)
    s.check('D a folder registered on the VM that no lab uses is not in the tree', p.locator('[data-folder="old-lab-folder"]').count() == 0)
    s.check('D the words registration, prefix and overlap are nowhere in the chooser', not re.search(r'registration|prefix|overlap', p.locator('#save-drawer').inner_text(), re.I))
    type_folder(s, 'old-lab-folder')
    s.equal('D a folder registered on the VM that no lab uses: free like any new folder', answer(s), 'old-lab-folder is new. It appears in the repository with the first save.')
    press(s, '#folder-foot [data-folder-action="save"]')
    saved_here(s, 'shared-b', 'Nested-Labs:old-lab-folder', 'D a registered folder no lab uses')

    # the very folder another connected lab saves to: question 1, the suggested answer
    text = choose('shared')
    s.equal('D another lab\'s folder: question 1', text, 'shared-a saves here too.')
    s.equal('D another lab\'s folder: its two answers', foot_buttons(s), ['Cancel', 'Save in shared/shared-b', 'Use this folder anyway'])
    s.check('D another lab\'s folder: the note says what Use this folder anyway does', 'shared-a is disconnected from it' in s.text('#folder-answer-note'))
    new_folder_enabled(s, 'while question 1 is asked')
    s.shot('D-question-1')
    press(s, '#folder-foot [data-folder-choice="beside"]')
    saved_here(s, 'shared-b', 'Nested-Labs:shared/shared-b', 'D question 1, Save in shared/shared-b')
    s.equal('D question 1, beside: the other lab keeps its folder', place_of(s, 'shared-a'), 'Nested-Labs:shared')

    # a folder that holds a saved state: question 2, the suggested answer
    text = choose('BGP/start')
    s.equal('D a folder that holds a state: question 2', text, 'This folder holds the state “Start”.')
    s.equal('D a folder that holds a state: its two answers', foot_buttons(s), ['Cancel', 'Save beside it in BGP/start/shared-b', 'Replace it'])
    new_folder_enabled(s, 'while question 2 is asked')
    s.shot('D-question-2')
    press(s, '#folder-foot [data-folder-choice="beside"]')
    saved_here(s, 'shared-b', 'Nested-Labs:BGP/start/shared-b', 'D question 2, Save beside it')
    text = choose('Final')
    s.equal('D a state stored directly in the folder: question 2', text, 'This folder holds the state “Final”.')
    s.equal('D a state stored directly in the folder: the second answer is Use this folder anyway (DESIGN.md 6)', foot_buttons(s)[-1], 'Use this folder anyway')
    press(s, '#folder-foot [data-folder-choice="take"]')
    saved_here(s, 'shared-b', 'Nested-Labs:Final', 'D question 2, Use this folder anyway (flat state)')
    text = choose('BGP/broken')
    s.equal('D a folder that holds a state (Broken): question 2', text, 'This folder holds the state “Broken”.')
    press(s, '#folder-foot [data-folder-choice="take"]')
    saved_here(s, 'shared-b', 'Nested-Labs:BGP/broken', 'D question 2, Replace it')

    # a folder that is part of a saved state: the lab folder above is used, and the chooser says so
    text = choose('shared/shared-b/checkpoints/x')
    s.match('D part of a saved state: the chooser says the folder above is used', text, r'^shared/shared-b/checkpoints/x is part of a saved state, so shared-b saves in shared/shared-b, the lab folder above it\.')
    s.equal('D part of a saved state: the result line shows the folder that is used', s.text('#folder-result').replace('\n', ' '), 'Saves go to Nested-Labs › shared/shared-b')
    press(s, '#folder-foot [data-folder-primary]')
    saved_here(s, 'shared-b', 'Nested-Labs:shared/shared-b', 'D part of a saved state')
    text = choose('BGP/latest')
    s.match('D part of another lab\'s saved state: said, then question 1 for the folder above', text, r'^BGP/latest is part of a saved state, so shared-b saves in BGP, the lab folder above it\. restore-square saves here too\.$')
    s.check('D part of another lab\'s saved state: buttons, not a refusal', foot_buttons(s)[1].startswith('Save in BGP/shared-b'), foot_buttons(s))
    s.click('#folder-foot [data-folder-action="cancel"]')

    # unsafe characters: corrected as typed, the result shown
    open_chooser(s)
    s.fill('#folder-path', 'My Lab: A/B')
    s.equal('D unsafe characters: corrected as typed in the field', p.locator('#folder-path').input_value(), 'My-Lab-A/B')
    answer(s)
    s.equal('D unsafe characters: the result line', s.text('#folder-result').replace('\n', ' '), 'Saves go to Nested-Labs › My-Lab-A/B')
    no_refusal(s, 'D unsafe characters')
    press(s, '#folder-foot [data-folder-action="save"]')
    saved_here(s, 'shared-b', 'Nested-Labs:My-Lab-A/B', 'D unsafe characters')
    s.no_errors('D the 6.2 rows without a waiting save')

    # New folder…: at the top level, inside a lab folder, inside a nested one, inside a saved state
    for parent, name, want in [('', 'top-new', 'top-new'), ('BGP', 'in-lab', 'BGP/in-lab'), ('BGP/edge', 'in-nested', 'BGP/edge/in-nested')]:
        open_chooser(s)
        row = '#folder-tree > [data-folder=""] > .folder-row' if not parent else '[data-folder="%s"] > .folder-row' % parent
        if parent and p.locator(row).count() == 0:
            p.locator('[data-folder="BGP"] > .folder-row [data-folder-twist]').click()
        s.click(row)
        new_folder_enabled(s, 'with %s selected' % (parent or 'the top level'))
        s.click('.folder-chooser [data-folder-action="new"]')
        s.equal('D New folder… in %s: its field takes the focus' % (parent or 'the top level'), s.focused(), 'folder-new')
        s.fill('#folder-new', name)
        s.click('.folder-new [data-folder-action="new-add"]')
        expect(p.locator('[data-folder="%s"]' % want)).to_be_visible(timeout=15000)
        s.equal('D New folder… in %s: the folder is selected' % (parent or 'the top level'), p.locator('#folder-path').input_value(), want)
        s.equal('D New folder… in %s: said as planned, never as in the repository' % (parent or 'the top level'), answer(s), want + ' is new. It appears in the repository with the first save.')
        no_refusal(s, 'D New folder… in ' + (parent or 'the top level'))
        s.click('#folder-foot [data-folder-action="cancel"]')
    open_chooser(s)
    type_folder(s, 'BGP/start')
    new_folder_enabled(s, 'with a folder that holds a saved state chosen')
    s.click('.folder-chooser [data-folder-action="new"]')
    s.fill('#folder-new', 'beside-start')
    s.click('.folder-new [data-folder-action="new-add"]')
    s.wait_js("document.getElementById('folder-path').value.includes('beside-start')")
    s.check('D New folder… inside a saved state: made, not refused', 'beside-start' in p.locator('#folder-path').input_value(), p.locator('#folder-path').input_value())
    s.shot('D-new-folder-in-state')
    no_refusal(s, 'D New folder… inside a saved state')
    s.click('#folder-foot [data-folder-action="cancel"]')
    s.no_errors('D New folder…')

    # ---- D: a folder change while a save waits: question 3, both answers; the line that brings the saved files along ---------------
    edit = [d for d in s.fixture_state()['devices'] if d.startswith('clab-shared-b-')][0]

    def waiting_save(line):
        s.action('edit_device', device=edit, add=[line], remove=[])
        s.click('#git-save-progress', count=False)
        s.wait_chip(r'^1 save to upload$', timeout=40000)
        expect(p.locator('#save-upload')).to_be_enabled(timeout=15000)
        s.click('#save-not-now', count=False)

    waiting_save('interface Loopback41')
    text = choose('moved-1')
    s.equal('D the bring-along line', s.text('#folder-move').strip(), 'Bring this lab’s saved files along')
    s.click('#folder-foot [data-folder-action="save"]')
    expect(p.locator('#folder-foot [data-folder-pending="keep"]')).to_be_visible(timeout=15000)
    s.equal('D while a save waits: question 3', s.text('#folder-answer'), '1 save of shared-b is waiting for upload.')
    s.equal('D while a save waits: its two answers', foot_buttons(s), ['Cancel', 'Upload it, then move', 'Move and keep that save on the VM only'])
    new_folder_enabled(s, 'while question 3 is asked')
    s.shot('D-question-3')
    s.click('#folder-foot [data-folder-pending="keep"]')
    saved_here(s, 'shared-b', 'Nested-Labs:moved-1', 'D question 3, Move and keep that save on the VM only')
    s.wait_chip(r'^\d saves? to upload$', timeout=40000)
    wait_until(lambda: any(j.get('target') == 'move' and j['status'] in ('committed', 'review_pending') for j in s.api_state()['git_jobs']), timeout=30, what='the move')
    s.wait_chip(r'^2 saves to upload$', timeout=20000)
    s.check('D question 3, keep: the save keeps waiting and the move waits with it (it never uploads by itself)', True)
    s.click('#save-chip', count=False)
    expect(p.locator('#save-upload')).to_be_enabled(timeout=20000)
    s.match('D the move in the upload sentence', p.locator('#save-panel-body').inner_text(), r'saved files moved to moved-1')
    s.click('#save-upload', count=False)
    s.wait_toast(r'^Uploaded to ')
    s.wait_chip('^Saved ')
    waiting_save('interface Loopback42')
    choose('moved-2')
    press(s, '#folder-foot [data-folder-action="save"]')
    expect(p.locator('#folder-foot [data-folder-pending="upload"]')).to_be_enabled(timeout=20000)
    s.match('D question 3: the note carries the upload sentence before the click', s.text('#folder-answer-note'), r'device changed since your last save')
    s.click('#folder-foot [data-folder-pending="upload"]')
    saved_here(s, 'shared-b', 'Nested-Labs:moved-2', 'D question 3, Upload it, then move')
    wait_until(lambda: not any(j.get('note') and 'Loopback' in str(j.get('summary')) and not j.get('pushed') for j in s.api_state()['git_jobs']), timeout=20, what='the upload before the move')
    s.check('D question 3, upload: the waiting save was uploaded before the move', all(j.get('pushed') for j in s.api_state()['git_jobs'] if j.get('lab_name') == 'shared-b' and j.get('target') == 'latest'))
    s.wait_chip('^Saved ', timeout=40000)
    s.no_errors('D question 3 and the bring-along line')

    # question 1, the other answer: Use this folder anyway disconnects the other lab
    choose('shared')
    press(s, '#folder-foot [data-folder-choice="take"]')
    saved_here(s, 'shared-b', 'Nested-Labs:shared', 'D question 1, Use this folder anyway')
    s.equal('D question 1, take: the other lab is disconnected from the folder', place_of(s, 'shared-a'), None)
    s.no_errors('D question 1, Use this folder anyway')

    # ---- a placement the VM refuses for a cause outside the manager (PROMPT 6.5) reads like the chip, and Try again repeats it -----
    choose('refused-then-fine')
    # The VM refuses a new folder while the online copy is ahead (host_git register(): the fixture's `remote_ahead`). A Git
    # operation left open on the VM no longer refuses a placement in the fixture, as it does not on a real VM.
    s.switch(remote_ahead=True)
    with s.expect_status(409, r'/git/place$'):
        press(s, '#folder-foot [data-folder-action="save"]')
        expect(p.locator('#folder-refused')).to_be_visible(timeout=20000)
    s.equal('D a placement the VM refuses: the cause in the chip\'s words', s.text('#folder-refused'), 'The online copy has changes this VM does not have.')
    s.check('D a placement the VM refuses: Update from the repository, Try again and Details, New folder… still enabled', s.visible('[data-folder-action="update"]') and s.visible('[data-folder-action="again"]') and s.visible('#folder-refused-details') and p.locator('.folder-chooser [data-folder-action="new"]').is_enabled())
    s.shot('D-refused-by-the-vm')
    s.switch(remote_ahead=None)
    s.click('[data-folder-action="again"]')
    saved_here(s, 'shared-b', 'Nested-Labs:refused-then-fine', 'D Try again after the cause is gone')
    s.match('D after the placement the chip no longer says Can\'t save', s.chip(), r'^(Saved|Not saved|\d save)')
    s.no_errors('D a placement the VM refuses')

    # ---- D: a large repository ------------------------------------------------------------------------------------------------------
    open_chooser(s)
    repository(s, BIG)
    new_folder_enabled(s, 'in a repository of 5000 files')
    s.check('D a large repository: a folder beyond the 4000th file is in the tree (every folder is listed)', p.locator('[data-folder="zz-states"]').count() == 1)
    note = s.text('#folder-tree-note') if s.visible('#folder-tree-note') else ''
    s.equal('D a large repository: no sentence claims folders are missing when every folder is listed', note, '')
    type_folder(s, 'zz-states/start')
    s.equal('D a large repository: a state beyond the listing is known', answer(s), 'This folder holds the state “Start”.')
    type_folder(s, 'deep/er/than/the/list')
    s.equal('D a large repository: any typed path can be used', foot_buttons(s), ['Cancel', 'Save here'])
    s.shot('D-big-repo')
    press(s, '#folder-foot [data-folder-action="save"]')
    saved_here(s, 'shared-b', 'Big-Repo:deep/er/than/the/list', 'D a large repository')
    s.no_errors('D a large repository')

    # ---- C: no repository on the VM: the address field; the empty repository: Start the repository ------------------------------------
    s.switch(no_repositories=True)
    s.open_lab('ospf-basics')
    s.reset_counts()
    s.click('#git-save-progress')
    expect(p.locator('#save-url')).to_be_visible(timeout=15000)
    s.check('C no repository on the VM: one field for the HTTPS address', 'Paste its address' in p.locator('#save-panel-body').inner_text())
    s.shot('C-address')
    s.fill('#save-url', 'https://github.com/ArchRuger/New-Empty.git')
    s.click('#save-first')
    expect(p.locator('#save-first-start')).to_be_visible(timeout=30000)
    s.equal('C the empty repository: the sentence', s.text('#save-first-empty'), 'New-Empty is empty. The manager adds a README.md file to start it.')
    s.equal('C the empty repository: one button', s.text('#save-first-start'), 'Start the repository')
    s.shot('C-empty-repository')
    s.click('#save-first-start')
    wait_until(lambda: place_of(s, 'ospf-basics') == 'New-Empty:ospf-basics', timeout=40, what='the placement in New-Empty')
    s.check('C the empty repository: started, and the lab is placed in its folder inside it', True)
    s.no_errors('C address and empty repository')
    return s.finish()


if __name__ == '__main__':
    sys.exit(main())
