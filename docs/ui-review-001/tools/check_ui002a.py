#!/usr/bin/env python3
"""UI-002 (part 1) browser check: Home leads with Deploy and Build; an upload goes through the review.

Runs against the fixture manager. It creates one topology file in the fixture's scripted VM folder; use
a scratch FIXTURE_DATA directory. The "VM not connected" and "no labs" pages are produced by rewriting
the /api/state answer in the browser only.

    CLAB_BASE=http://127.0.0.1:8090 clab-backup-ui/.venv/bin/python docs/ui-review-001/tools/check_ui002a.py
"""
import json
import os
import sys
import tempfile

from playwright.sync_api import sync_playwright

BASE = os.environ.get('CLAB_BASE', 'http://127.0.0.1:8090')
OUT = os.environ.get('CLAB_SHOTS', '')
failed = []
TOPOLOGY = 'name: ui002-upload\ntopology:\n  nodes:\n    r1:\n      kind: linux\n      image: alpine:latest\n    r2:\n      kind: linux\n      image: alpine:latest\n  links:\n    - endpoints: ["r1:eth1", "r2:eth1"]\n'


def check(name, ok, detail=''):
    print(('ok   ' if ok else 'FAIL ') + name + (f' :: {detail}' if not ok else ''), flush=True)
    if not ok:
        failed.append(name)


def shot(page, name, full=False):
    if OUT:
        page.screenshot(path=os.path.join(OUT, name + '.png'), full_page=full)


def rewrite_state(change):
    def handler(route):
        response = route.fetch()
        body = response.json()
        change(body)
        route.fulfill(response=response, body=json.dumps(body), headers={**response.headers, 'content-type': 'application/json'})
    return handler


with sync_playwright() as pw:
    browser = pw.chromium.launch()
    work = tempfile.mkdtemp()
    good, bad, wrong = (os.path.join(work, n) for n in ('ui002-upload.clab.yaml', 'broken.clab.yaml', 'notes.txt'))
    open(good, 'w').write(TOPOLOGY)
    open(bad, 'w').write('name: x\ntopology: [unclosed\n')
    open(wrong, 'w').write('hello')

    for width, height, scale in [(1366, 768, 1), (1280, 720, 1.5), (1280, 720, 2)]:
        tag = f'{width}x{height}@{scale}'
        page = browser.new_page(viewport={'width': int(width / scale), 'height': int(height / scale)})
        page.goto(BASE + '/')
        page.wait_for_selector('#home-start:not([hidden])')
        m = page.evaluate('''() => { const r = e => e.getBoundingClientRect(), cards = [...document.querySelectorAll('.start-card')].map(r), first = document.querySelector('#home-continue:not([hidden]), #lab-cards:not([hidden])');
          const btns = [...document.querySelectorAll('.start-card .button')].map(b => ({t: b.textContent.trim(), clipped: b.scrollWidth > b.clientWidth + 1, right: r(b).right}));
          return {cards: cards.map(c => ({l: c.left, t: c.top, w: c.width, h: c.height, b: c.bottom})), listTop: first ? r(first).top : null, btns, vw: innerWidth, sideways: document.documentElement.scrollWidth > innerWidth + 1}; }''')
        check(f'{tag}: Deploy and Build are two cards of equal size', len(m['cards']) == 2 and abs(m['cards'][0]['w'] - m['cards'][1]['w']) <= 1 and (abs(m['cards'][0]['h'] - m['cards'][1]['h']) <= 1 or m['cards'][0]['l'] == m['cards'][1]['l']), m['cards'])
        check(f'{tag}: they come before the labs', m['listTop'] is None or m['listTop'] >= max(c['b'] for c in m['cards']), m)
        check(f'{tag}: no clipped button, no sideways scrolling', not m['sideways'] and not any(b['clipped'] or b['right'] > m['vw'] for b in m['btns']), m['btns'])
        shot(page, f'ui002a-home-{tag}', full=True)
        page.close()

    page = browser.new_page(viewport={'width': 1366, 'height': 768})
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.on('console', lambda m: errors.append(m.text) if m.type == 'error' and 'Failed to load resource' not in m.text else None)
    page.goto(BASE + '/')
    page.wait_for_selector('#home-start:not([hidden])')
    # Deploy > a file on the lab VM
    page.click('#home-deploy')
    page.wait_for_selector('#op-browser[open] #op-file-tree')
    check('Choose a file on the lab VM opens the VM folders', 'Lab folders on the VM' in page.inner_text('#op-browser') or page.is_visible('#op-file-tree'))
    check('the VM browser says these files are on the lab VM and offers the upload', 'These are files on the lab VM' in page.inner_text('#op-browser') and page.is_visible('#op-browse-upload'))
    page.keyboard.press('Escape')
    # Build opens the builder itself
    href = page.get_attribute('#home-build', 'href')
    check('Build links straight to the lab builder', href == '/static/lab-builder.html', href)
    # Deploy > upload: refusals in words
    page.click('#home-upload')
    page.wait_for_selector('#op-upload[open]')
    shot(page, 'ui002a-upload-dialog')
    page.click('#op-upload-next')
    check('no file: a plain sentence', 'Choose a file first' in page.inner_text('#op-upload .form-error'))
    page.set_input_files('#op-upload-file', wrong)
    page.click('#op-upload-next')
    page.wait_for_function('() => /Its name ends in/.test(document.querySelector("#op-upload .form-error").textContent)')
    check('a wrong kind of file is refused with what to choose instead', True)
    page.set_input_files('#op-upload-file', bad)
    page.click('#op-upload-next')
    page.wait_for_function('() => /not a containerlab topology the manager can read/.test(document.querySelector("#op-upload .form-error").textContent)', timeout=15000)
    check('a broken topology is refused with the manager\'s reason', True)
    shot(page, 'ui002a-upload-refused')
    # A good file: shown for review, then the reviewed create, then deploy
    page.set_input_files('#op-upload-file', good)
    page.click('#op-upload-next')
    page.wait_for_selector('#op-editor[open]', timeout=15000)
    check('the uploaded text and its destination are shown before anything is written', page.input_value('#op-edit-text') == TOPOLOGY and page.input_value('#op-edit-path').endswith('/ui002-upload.clab.yaml') and 'Nothing is on the lab VM yet' in page.inner_text('#op-editor'))
    check('it cannot be deployed before it is on the VM', not page.query_selector('#op-deploy-project'))
    shot(page, 'ui002a-upload-review')
    page.click('#op-save-yaml')
    page.wait_for_selector('#operation-review[open] #op-confirm', timeout=20000)
    check('Create file on the VM opens the operation review', page.input_value('#op-edit-path') in page.inner_text('#operation-review') or 'ui002-upload' in page.inner_text('#operation-review'))
    page.click('#op-confirm')
    page.wait_for_selector('#op-open-published', timeout=60000)
    check('after the confirmed create the file is on the VM and not running', 'It is not running yet' in page.inner_text('#op-job-result'))
    page.click('#op-open-published')
    page.wait_for_selector('#op-editor[open] #op-deploy-project', timeout=20000)
    check('the file now offers Deploy lab like any file on the VM', True)
    page.click('#op-deploy-project')
    page.wait_for_selector('#operation-review[open] #op-confirm', timeout=30000)
    check('Deploy lab is reviewed too', 'ui002-upload' in page.inner_text('#operation-review'))
    shot(page, 'ui002a-deploy-review')
    page.click('#operation-review .dialog-head .icon-button, #operation-review [data-dismiss], #operation-review .close')
    check('no console or page errors', not errors, errors)
    page.close()

    # VM not connected: both deploy buttons wait, with the reason in words; Build stays available
    page = browser.new_page(viewport={'width': 1366, 'height': 768})
    page.route('**/api/state', rewrite_state(lambda s: s['discovery'].update(connected=False, error='Cannot reach the VM SSH service.')))
    page.goto(BASE + '/')
    page.wait_for_selector('#home-start:not([hidden])')
    page.wait_for_function('() => document.getElementById("home-deploy").disabled')
    reason = page.inner_text('#home-deploy-reason')
    check('without the VM both Deploy buttons are off and say why', page.is_disabled('#home-upload') and 'deploying needs it' in reason and 'Building a lab works' in reason, reason)
    check('Build stays available', page.is_visible('#home-build') and page.get_attribute('#home-build', 'href') == '/static/lab-builder.html')
    shot(page, 'ui002a-home-vm-away')
    page.close()
    # No labs at all: the two choices lead, the empty state follows without a second set of buttons
    page = browser.new_page(viewport={'width': 1366, 'height': 768})
    page.route('**/api/state', rewrite_state(lambda s: s.update(labs=[])))
    page.goto(BASE + '/')
    page.wait_for_selector('#empty:not([hidden])')
    check('a first-time student sees Deploy and Build at once, above "No labs yet"', page.evaluate('() => !document.getElementById("home-start").hidden && document.getElementById("home-start").getBoundingClientRect().bottom <= document.getElementById("empty").getBoundingClientRect().top') and not page.query_selector('#deploy-empty'))
    shot(page, 'ui002a-home-first-time')
    browser.close()
sys.exit(1 if failed else 0)
