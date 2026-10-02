#!/usr/bin/env python3
"""Item 9, Hide from Home: a lab card is hidden from the ⋯ dialog, Home says so, the lab keeps everything,
the background discovery never puts the card back, Show on Home (Manager ▾ › Labs found on the VM…) and
adding the topology again from Choose a file on the lab VM… both bring it back. Zero console or page errors.

Runs against the deployed manager (default) or the fixture manager. The lab must be in My labs with its
topology file on the VM, not running, and not busy.

    CLAB_BASE=http://192.168.132.132:8081 CLAB_LAB=netlab-test CLAB_SHOTS=/tmp/shots \\
      clab-backup-ui/.venv/bin/python docs/ui-ux-changes-2/tools/check_hide_lab.py
"""
import json
import os
import sys
import time

from playwright.sync_api import sync_playwright

BASE = os.environ.get('CLAB_BASE', 'http://192.168.132.132:8081')
LAB = os.environ.get('CLAB_LAB', 'netlab-test')
OUT = os.environ.get('CLAB_SHOTS', '')
failed = []


def check(name, ok, detail=''):
    print(('ok   ' if ok else 'FAIL ') + name + (f' :: {detail}' if not ok else ''), flush=True)
    if not ok:
        failed.append(name)


with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_context(viewport={'width': 1440, 'height': 900}).new_page()
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)[:300]))
    page.on('console', lambda m: errors.append(m.text[:300]) if m.type == 'error' and 'Failed to load resource' not in m.text else None)
    api = lambda path: json.loads(page.request.get(BASE + '/api' + path).text())
    shot = lambda name: page.screenshot(path=os.path.join(OUT, name + '.png')) if OUT else None
    lab_of = lambda: next((l for l in api('/state')['labs'] if l['name'] == LAB), None)
    before = lab_of()
    check('the lab is in My labs', before is not None, LAB)
    lid = before['id']
    if before.get('hidden'):  # a previous run left it hidden: start from the shown state
        page.request.put(BASE + '/api/labs/%s/operations-settings' % lid, data=json.dumps({'hidden': False}), headers={'Content-Type': 'application/json'})
        before = lab_of()
    cards = lambda: page.locator('#lab-cards .lab-card[data-lab-id="%s"]' % lid)
    note = page.locator('#home-hidden-note')

    page.goto(BASE + '/', wait_until='networkidle')
    page.wait_for_selector('#lab-cards .lab-card', timeout=30000)
    check('step 1: the card is on Home', cards().count() == 1)
    shot('01-home-with-card')
    page.click('[data-lab-more="%s"]' % lid)
    page.wait_for_selector('#lab-operations-dialog [data-local="hide"]', timeout=15000)
    check('step 2: the ⋯ dialog offers Hide from Home', page.inner_text('#lab-operations-dialog [data-local="hide"]') == 'Hide from Home')
    help_text = page.inner_text('#lab-operations-dialog')
    check('step 2: the help says what stays and the ways back', 'backups, saved progress and settings are kept' in help_text and 'Choose a file on the lab VM' in help_text, help_text[:200])
    shot('02-card-menu-hide')
    page.click('#lab-operations-dialog [data-local="hide"]')
    page.wait_for_function('() => !document.querySelector("#lab-operations-dialog").open', timeout=15000)
    page.wait_for_timeout(800)
    check('step 3: the card is gone from Home', cards().count() == 0)
    check('step 3: Home says one lab is hidden and names both ways back', note.is_visible() and note.inner_text() == '1 lab is hidden from Home. Show it again under Manager ▾ › Labs found on the VM…, or add it again from Choose a file on the lab VM….', note.inner_text() if note.count() else 'no note')
    shot('03-home-hidden')
    after = lab_of()
    check('step 4: the lab keeps everything but the flag', after and after.get('hidden') is True and {k: v for k, v in after.items() if k not in ('hidden', 'updated', 'deployment', 'nodes', 'nos_readiness')} == {k: v for k, v in before.items() if k not in ('hidden', 'updated', 'deployment', 'nodes', 'nos_readiness')} and len(after['nodes']) == len(before['nodes']), after and sorted(set(after) ^ set(before)))
    page.click('#home-tab-all'); page.wait_for_timeout(400)
    check('step 4: All labs hides it too', cards().count() == 0)
    page.click('#home-tab-recent'); page.wait_for_timeout(200)
    # A discovery pass: checked_at moves on; the card stays away.
    stamp = api('/state')['discovery'].get('checked_at')
    deadline = time.time() + 75
    while time.time() < deadline and api('/state')['discovery'].get('checked_at') == stamp:
        time.sleep(3)
    moved = api('/state')['discovery'].get('checked_at') != stamp
    page.wait_for_timeout(4500)
    check('step 5: a discovery pass ran and the card stayed away', moved and cards().count() == 0 and lab_of().get('hidden') is True, 'discovery pass seen: %s' % moved)
    # Manager ▾ › Labs found on the VM… lists it under Hidden from Home with Show on Home.
    page.click('#manager-button'); page.wait_for_timeout(300)
    page.click('#manager-vm-labs')
    page.wait_for_selector('#vm-labs-dialog[open]', timeout=10000); page.wait_for_timeout(500)
    listing = page.inner_text('#hidden-labs')
    check('step 6: the VM labs dialog lists it under Hidden from Home', 'Hidden from Home' in listing and LAB in listing, listing[:200])
    shot('04-vm-labs-dialog-hidden')
    page.click('#hidden-labs [data-show-lab="%s"]' % lid)
    page.wait_for_timeout(1500)
    page.keyboard.press('Escape'); page.wait_for_timeout(500)
    check('step 6: Show on Home puts the card back', cards().count() == 1 and not lab_of().get('hidden') and not note.is_visible())
    shot('05-home-shown-again')
    # Hide again, then add the topology again from Choose a file on the lab VM…
    page.click('[data-lab-more="%s"]' % lid); page.wait_for_selector('#lab-operations-dialog [data-local="hide"]', timeout=15000)
    page.click('#lab-operations-dialog [data-local="hide"]')
    page.wait_for_function('() => !document.querySelector("#lab-operations-dialog").open', timeout=15000); page.wait_for_timeout(600)
    check('step 7: hidden again', cards().count() == 0 and lab_of().get('hidden') is True)
    topology = before.get('vm_project_path') or before.get('vm_source', {}).get('files', {}).get('definition', {}).get('path', '')
    page.click('#home-deploy')
    page.wait_for_selector('#op-browser[open] #op-file-tree', timeout=20000); page.wait_for_timeout(800)
    # The tree starts at the trusted roots (each listed by its full path); open the root that holds the
    # topology, then every folder down to the file.
    roots = api('/operations/capabilities').get('roots', [])
    root = max((r for r in roots if topology.startswith(r.rstrip('/') + '/')), key=len)
    page.locator('#op-file-tree > details > summary', has_text=root).first.click()
    inner = topology[len(root.rstrip('/')) + 1:].split('/')
    for part in inner[:-1]:
        page.locator('#op-file-tree summary', has_text=part).first.wait_for(timeout=20000)
        page.locator('#op-file-tree summary', has_text=part).first.click()
    page.locator('#op-file-tree .op-tree-file', has_text=inner[-1]).first.wait_for(timeout=20000)
    page.wait_for_timeout(300)
    page.locator('#op-file-tree .op-tree-file', has_text=inner[-1]).first.scroll_into_view_if_needed()
    page.locator('#op-file-tree .op-tree-file', has_text=inner[-1]).first.evaluate('button => button.click()')  # the tree scrolls inside the dialog; a DOM click reaches it regardless of the viewport
    page.wait_for_selector('#op-editor[open] #op-add-project', timeout=20000)
    shot('06-topology-file-dialog')
    page.click('#op-add-project')
    page.wait_for_selector('#op-add-confirm[open] #op-add-confirm-button', timeout=20000)
    page.click('#op-add-confirm-button')
    page.wait_for_function('() => !document.querySelector("#op-editor").open', timeout=20000); page.wait_for_timeout(1500)
    check('step 7: adding the topology again keeps the same lab id', lab_of() and lab_of()['id'] == lid and not lab_of().get('hidden'))
    # Add lab opens the lab; the topology browser dialog underneath stays open until it is closed.
    page.evaluate('() => document.querySelectorAll("dialog[open]").forEach(d => d.close())'); page.wait_for_timeout(300)
    page.click('#crumb-home'); page.wait_for_timeout(1200)
    check('step 7: the card is back on Home, the note is gone', cards().count() == 1 and not note.is_visible())
    shot('07-home-after-readd')
    check('no console or page errors', not errors, errors)
    browser.close()
print('FAILED: ' + ', '.join(failed) if failed else 'ALL CHECKS PASSED')
sys.exit(1 if failed else 0)
