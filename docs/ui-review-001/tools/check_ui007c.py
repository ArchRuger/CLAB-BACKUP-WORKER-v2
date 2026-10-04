#!/usr/bin/env python3
"""UI-007 C browser check, rewritten for the header Save and Load (Git save and load redesign): a save is reviewed before
anything is uploaded, whatever the lab's stored option says.

Runs against the fixture manager, whose labs carry a save location stored with the old opt-out (review_before_push
false). It creates saves in the fixture's scripted repository; use a scratch FIXTURE_DATA directory.

What moved (docs/git-redesign/inventory/CAPABILITIES.md C-001, C-004, C-005; DESIGN.md 3.2, 3.4, 7.6):

  * the "What changed?" label dialog before every save is gone (owner decision): Save starts at once and the manager names
    the save; the name is editable afterwards in the chip panel. The check "the save is labelled first" is now "no label
    dialog stands between Save and the result";
  * the review window ("Review before uploading") is the waiting view of the chip panel ("Not uploaded yet": Upload,
    Not now, See changes, Details) and the What changed drawer. Cancelling the review is Not now (no toast: DESIGN 7.6);
  * Recent saves > "Review and upload..." is the chip's waiting view (or See changes) > Upload;
  * "Save on this VM only" is Save, then Not now: the save stays on the VM, nothing is uploaded, no review opens;
  * the optional-review checkbox stays gone from Save settings, and the form no longer carries the sentence "Nothing is
    uploaded without you": the waiting view says it ("Not uploaded yet") and Upload is the only sender;
  * unchanged: the manager itself refuses an upload that does not state the review (409 "Review the changes").

    CLAB_BASE=http://127.0.0.1:8090 clab-backup-ui/.venv/bin/python docs/ui-review-001/tools/check_ui007c.py
"""
import os
import sys

from playwright.sync_api import sync_playwright

BASE = os.environ.get('CLAB_BASE', 'http://127.0.0.1:8090')
OUT = os.environ.get('CLAB_SHOTS', '')
LAB = os.environ.get('CLAB_LAB', 'BGP_TheoryToPractice')
failed = []


def check(name, ok, detail=''):
    print(('ok   ' if ok else 'FAIL ') + name + (f' :: {detail}' if not ok else ''), flush=True)
    if not ok:
        failed.append(name)


def shot(page, name):
    if OUT:
        page.screenshot(path=os.path.join(OUT, name + '.png'))


NEWEST = '''async (lab) => { const s = await (await fetch('/api/state')).json(); const id = s.labs.find(l => l.name === lab).id;
  const jobs = s.git_jobs.filter(j => j.lab_id === id).sort((a, b) => a.created < b.created ? 1 : -1); return {lab: id, opt_out: s.labs.find(l => l.name === lab).git_binding.review_before_push, job: jobs[0]}; }'''

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_page(viewport={'width': 1366, 'height': 768})
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.on('console', lambda m: errors.append(m.text) if m.type == 'error' and 'Failed to load resource' not in m.text else None)
    page.goto(BASE + '/')
    page.wait_for_selector('article.lab-card')
    page.click(f'article.lab-card:has(h3:text-is("{LAB}")) [data-lab]')
    page.wait_for_selector('#lab-content:not([hidden])')
    page.wait_for_function('() => document.getElementById("save-chip-text").textContent.length > 0')
    page.evaluate('() => { window.__toasts = []; const shown = notify; notify = function (m) { window.__toasts.push(String(m)); return shown(m); }; }')
    before = page.evaluate(NEWEST, LAB)
    check('the lab was saved with the old opt-out (review_before_push false)', before['opt_out'] is False, before['opt_out'])
    page.click('#save-chip')
    page.click('#save-settings')
    page.wait_for_selector('#save-drawer[open] .save-settings input[name=git-node]', timeout=20000)
    form = page.inner_text('#save-drawer-content')
    check('the optional-review checkbox is gone', page.evaluate('() => !document.getElementById("git-review-before-push")') and 'Let me review changes' not in form)
    check('device selection is still there', page.evaluate('() => document.querySelectorAll("#save-drawer-content [name=git-node]").length') > 0)
    page.click('#save-drawer-close')
    page.wait_for_function('() => !document.getElementById("save-drawer").open')

    # 1. Save: no label dialog; the waiting view opens by itself; cancelling uploads nothing
    page.click('#git-save-progress')
    page.wait_for_selector('#save-upload:not([disabled])', timeout=90000)
    check('no label dialog stands between Save and the result (the label dialog is gone)', page.evaluate('() => !document.getElementById("git-label-dialog")?.open && !document.getElementById("git-label-input")'))
    title = page.inner_text('#save-panel-title-text')
    check('Save ends in the waiting view of the chip panel, ready to upload', title == 'Not uploaded yet', title)
    check('the waiting view says nothing is uploaded unless the student chooses it', 'Not uploaded yet' in page.inner_text('#save-panel') and page.is_enabled('#save-upload') and page.is_visible('#save-not-now'))
    page.click('#save-see')
    page.wait_for_selector('#save-drawer[open] #save-drawer-content .diff-file', timeout=20000)
    check('See changes shows what changed, and that it is not uploaded', page.inner_text('#save-drawer-title') == 'What changed' and 'Not uploaded yet.' in page.inner_text('#save-drawer-meta'), page.inner_text('#save-drawer-meta'))
    shot(page, 'ui007c-review-window')
    page.click('#save-drawer-actions [data-save-action="not-now"]')
    page.wait_for_function('() => !document.getElementById("save-drawer").open')
    check('cancelling (Not now) says nothing of an upload and shows no "Saved to Git"', not any('Uploaded' in t or 'Saved to Git' in t for t in page.evaluate('() => window.__toasts')), page.evaluate('() => window.__toasts'))
    now = page.evaluate(NEWEST, LAB)
    job = now['job']
    check('after cancelling the save is on the VM only, waiting for the review', job['id'] != (before['job'] or {}).get('id') and job['status'] in ('review_pending', 'committed') and not job['pushed'], job)
    chip = page.inner_text('#save-chip-text')
    check('the chip does not claim an upload', 'to upload' in chip and not chip.startswith('Saved'), chip)
    shot(page, 'ui007c-after-cancel')

    # 2. The manager itself refuses an upload without the review (an old page, a script)
    refused = page.evaluate('''async (id) => { const r = await fetch('/api/git/jobs/' + id + '/retry', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({push: true})}); return {status: r.status, body: await r.json()}; }''', job['id'])
    check('the manager refuses an upload that does not state the review', refused['status'] == 409 and 'Review the changes' in refused['body'].get('detail', ''), refused)
    still = page.evaluate(NEWEST, LAB)['job']
    check('the refused upload changed nothing', still['status'] in ('review_pending', 'committed') and not still['pushed'], still)

    # 3. The chip leads back to the waiting save; the explicit choice uploads and records the review
    page.click('#save-chip')
    page.wait_for_selector('#save-upload:not([disabled])', timeout=30000)
    check('the chip panel offers "Upload" after a review, not a silent upload', page.inner_text('#save-upload') == 'Upload' and page.inner_text('#save-panel-title-text') == 'Not uploaded yet')
    page.click('#save-see')
    page.wait_for_selector('#save-drawer[open] #save-drawer-actions [data-save-action="upload"]:not([disabled])', timeout=30000)
    page.click('#save-drawer-actions [data-save-action="upload"]')
    page.wait_for_function('''async (id) => { const s = await (await fetch('/api/state')).json(); return s.git_jobs.some(j => j.id === id && j.status === 'synced' && j.pushed && j.reviewed); }''', arg=job['id'], timeout=60000)
    check('choosing "Upload" uploads the save and records the review', True)
    shot(page, 'ui007c-uploaded')
    if page.evaluate('() => document.getElementById("save-drawer").open'):
        page.keyboard.press('Escape')
    page.wait_for_function('() => !document.getElementById("save-drawer").open')

    # 4. Save, then Not now (the old "Save on this VM only") stays local and is reviewed when it is uploaded later
    check('there is no upload box to tick before a save', page.evaluate('() => !document.getElementById("git-save-push") && !document.getElementById("git-save-options")?.open'))
    known = page.evaluate('''async () => (await (await fetch('/api/state')).json()).git_jobs.map(j => j.id)''')
    page.click('#git-save-progress')
    page.wait_for_selector('#save-upload:not([disabled])', timeout=90000)
    page.click('#save-not-now')
    page.wait_for_function('() => document.getElementById("save-panel").hidden')
    local = page.evaluate('''async (known) => { const s = await (await fetch('/api/state')).json(); return s.git_jobs.filter(j => !known.includes(j.id)).sort((a, b) => a.created < b.created ? 1 : -1)[0]; }''', known)
    check('the newest save is a new one, kept on the VM', local and local['id'] not in known and local['status'] in ('review_pending', 'committed'), local)
    check('Save then Not now opens no review and uploads nothing', not local['pushed'] and not page.evaluate('() => document.getElementById("save-drawer").open'), local)
    check('no console or page errors', not errors, errors)
    browser.close()
sys.exit(1 if failed else 0)
