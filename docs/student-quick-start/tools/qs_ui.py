"""UI helpers shared by the scenario captures: the lab header's save chip, Save, Load, the terminals and GitHub
read-backs (release 1.31.6 UI). Every helper drives the real page; nothing reaches into the Store.

The chip panel (`#save-panel`) opens by itself after a save and after a load, so `open_chip` opens it only when it
is closed (a second click would close it). The manager has one guard shared with every other worker on the live
manager: `wait_idle()` first, then act.
"""
import json
import re
import subprocess
import time

import qs_lib
from qs_lib import BASE, settle, wait_idle, wait_text


def gh_tree(repo):
    """Full recursive tree of origin/main, read-only, via the already-authenticated gh CLI."""
    out = subprocess.run(['gh', 'api', f'repos/{repo}/git/trees/main?recursive=1'],
                         capture_output=True, text=True, timeout=60, check=True).stdout
    return {t['path']: t for t in json.loads(out).get('tree', [])}


def gh_blob_text(repo, path):
    return subprocess.run(['gh', 'api', f'repos/{repo}/contents/{path}', '-H', 'Accept: application/vnd.github.raw'],
                          capture_output=True, text=True, timeout=60, check=True).stdout


def open_lab(page, lab_id, view='topology'):
    page.goto(f'{BASE}/#lab={lab_id}&view={view}')
    page.wait_for_selector('#lab-content:not([hidden])', timeout=30000)
    page.wait_for_selector('#save-chip-text', timeout=15000)
    settle(page, 800)


def open_cli(context, page, container):
    """Devices tab > Open CLI of one device; returns the terminal page once it reads Connected."""
    page.click('#tab-devices')
    button = page.locator(f'#device-list button[data-terminal="{container}"]')
    button.wait_for(state='visible', timeout=15000)
    with context.expect_page() as info:
        button.click()
    term = info.value
    term.wait_for_selector('#terminal', timeout=20000)
    wait_text(term, '#status', r'^Connected$', timeout=40)
    settle(term, 600)
    term.click('#terminal')
    return term


def type_lines(term, lines, pause=900):
    for line in lines:
        term.keyboard.type(line)
        term.keyboard.press('Enter')
        term.wait_for_timeout(pause)


def chip(page):
    return page.locator('#save-chip-text').inner_text().strip()


def open_chip(page):
    """Open the chip panel unless it is already open (it opens by itself after a save or a load)."""
    if not page.locator('#save-panel').is_visible():
        page.click('#save-chip')
    page.wait_for_selector('#save-panel', state='visible', timeout=10000)


def wait_load_done(page, pattern, timeout=300):
    """The chip first keeps the old text for a moment, then reads Loading…: wait for Loading…, then the end."""
    try:
        wait_text(page, '#save-chip-text', r'^(Loading|Checking)', timeout=30, interval=0.3)
    except TimeoutError:
        pass
    return wait_text(page, '#save-chip-text', pattern, timeout=timeout)


def wait_devices_ready(page, count, timeout=420):
    """Reload the Devices tab until every row reads Ready; returns (pills, seconds)."""
    t0 = time.time()
    pills = []
    while time.time() - t0 < timeout:
        page.reload()
        page.wait_for_selector('#device-list li.device-row', timeout=30000)
        settle(page, 500)
        pills = [p.strip() for p in page.locator('#device-list li.device-row .pill').all_inner_texts()]
        if len(pills) == count and all(p == 'Ready' for p in pills):
            return pills, round(time.time() - t0, 1)
        page.wait_for_timeout(8000)
    return pills, None


def connect_and_save(rec, page, s, repo_url, folder, label='connect'):
    """Chip > Connect by URL… > address + folder > Save here. The place is connected and the lab saved in one
    click; when another worker holds the manager's guard at that moment the lab is connected and the first Save
    has to be pressed again. Leaves the chip panel open on "Not uploaded yet". Returns the seconds taken."""
    wait_idle()
    open_chip(page)
    page.wait_for_selector('#save-panel button:has-text("Connect by URL…")', timeout=20000)
    settle(page, 800)
    s['observed'][f'{label}_first_save_panel'] = page.locator('#save-panel').inner_text()
    rec.shoot_full(page, s, f'{label}-chip-first-save')
    page.get_by_role('button', name='Connect by URL…').click()
    page.wait_for_selector('#folder-url', timeout=20000)
    page.fill('#folder-url', repo_url)
    page.fill('#folder-path', folder)
    wait_text(page, '#save-drawer', r'Saves go to')
    settle(page, 800)
    s['observed'][f'{label}_drawer_text'] = page.locator('#save-drawer').inner_text()
    rec.shoot_full(page, s, f'{label}-drawer')
    rec.shoot_element(page.locator('#save-drawer'), s, f'{label}-drawer', label='Where should the lab save?')
    t0 = time.time()
    page.get_by_role('button', name='Save here').click()
    deadline = time.time() + 300
    path = None
    while time.time() < deadline:
        try:
            drawer_open = page.evaluate("() => document.getElementById('save-drawer').open")
            if not drawer_open and not page.locator('#save-panel').is_visible() and time.time() - t0 > 6:
                page.click('#save-chip')
                page.wait_for_timeout(800)
            text = page.locator('#save-panel').inner_text(timeout=2000) if page.locator('#save-panel').is_visible() else ''
        except Exception:
            text = ''
        if 'Not uploaded yet' in text:
            path = 'saved at once'
            break
        if 'Your first save goes to' in text and page.locator('#git-save-progress').is_enabled():
            wait_idle()
            page.click('#git-save-progress')
            path = 'connected, then Save pressed (the guard was busy at the first click)'
            wait_text(page, '#save-panel', r'Not uploaded yet', timeout=240)
            break
        page.wait_for_timeout(1000)
    if path is None:
        rec.fail(s, 'the first save never reached "Not uploaded yet"', page)
    s['observed'][f'{label}_path'] = path
    secs = round(time.time() - t0, 1)
    s['observed'][f'{label}_seconds_to_save_on_vm'] = secs
    settle(page, 1000)
    s['observed'][f'{label}_save_sentence'] = page.locator('#save-panel').inner_text()
    s['observed'][f'{label}_chip'] = chip(page)
    return secs


def do_save(rec, page, s, label):
    """Save in the lab header; the chip panel opens with the one-sentence summary. Returns the start time."""
    wait_idle()
    t0 = time.time()
    page.click('#git-save-progress')
    wait_text(page, '#save-panel', r'Not uploaded yet|Nothing changed', timeout=240)
    s['observed'][f'{label}_seconds_to_commit'] = round(time.time() - t0, 1)
    settle(page, 1200)
    s['observed'][f'{label}_panel'] = page.locator('#save-panel').inner_text()
    rec.shoot_full(page, s, f'{label}-panel')
    return t0


def upload_from_panel(page, s, label, t0):
    page.locator('#save-panel').get_by_role('button', name='Upload', exact=True).click()
    wait_text(page, '#save-chip-text', r'^Saved', timeout=180)
    s['observed'][f'{label}_seconds_to_uploaded'] = round(time.time() - t0, 1)
    settle(page, 1500)
    s['observed'][f'{label}_chip'] = chip(page)


def see_changes(rec, page, s, label, upload=True):
    """Chip panel > See changes (the What changed drawer); optionally Upload from the drawer."""
    page.get_by_role('button', name='See changes').click()
    wait_text(page, '#save-drawer', r'What changed')
    settle(page, 1200)
    text = qs_lib.StepRecorder.scrub(page.locator('#save-drawer').inner_text())
    s['observed'][f'{label}_drawer'] = text[:1800]
    s['observed'][f'{label}_files'] = re.findall(r'^(?:Topology file|Map|r\d)\s.*$', text, re.M)
    rec.shoot_full(page, s, f'{label}')
    rec.shoot_element(page.locator('#save-drawer'), s, f'{label}', label='What changed')
    if upload:
        page.locator('#save-drawer-actions').get_by_role('button', name='Upload', exact=True).click()
        wait_text(page, '#save-chip-text', r'^Saved', timeout=180)
        settle(page, 1500)
    else:
        page.click('#save-drawer-close')
        page.wait_for_timeout(600)


def do_load(rec, page, s, name, label, first_own_save=False):
    """Load > row > confirmation > red Load; waits until the chip says Running <name>. Returns the name loaded.
    first_own_save=True takes the first row of "Your saves" (the newest own save) whatever its name."""
    wait_idle()
    page.click('#load-button')
    wait_text(page, '#load-panel', r'Load a saved state')
    page.wait_for_selector('#load-panel [data-load-row]', timeout=20000)
    settle(page, 1000)
    s['observed'][f'{label}_list'] = page.locator('#load-panel').inner_text()
    rec.shoot_full(page, s, f'{label}-list')
    if first_own_save:
        row = page.locator('#load-panel [data-load-row]').first
    else:
        row = page.locator('#load-panel [data-load-row]').filter(has=page.get_by_text(name, exact=True)).first
    row.click()
    text = wait_text(page, '#load-panel', r'Load .+\?', timeout=90)
    loaded_name = re.search(r'Load (.+)\?', text).group(1)
    page.wait_for_selector('#load-run', state='visible', timeout=30000)
    settle(page, 1000)
    s['observed'][f'{label}_confirmation'] = page.locator('#load-panel').inner_text()
    rec.shoot_full(page, s, f'{label}-confirm')
    t0 = time.time()
    page.click('#load-run')
    wait_load_done(page, rf'^(Running {re.escape(loaded_name)}|Loaded \d+ of \d+)')
    s['observed'][f'{label}_seconds'] = round(time.time() - t0, 1)
    settle(page, 1500)
    s['observed'][f'{label}_chip'] = chip(page)
    return loaded_name
