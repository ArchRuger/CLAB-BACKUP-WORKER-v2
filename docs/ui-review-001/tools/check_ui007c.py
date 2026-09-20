#!/usr/bin/env python3
"""UI-007 C browser check: the review before an upload is mandatory.

Runs against the fixture manager, whose labs carry a save location stored with the old opt-out
(review_before_push false). It creates saves in the fixture's scripted repository; use a scratch
FIXTURE_DATA directory.

    CLAB_BASE=http://127.0.0.1:8090 clab-backup-ui/.venv/bin/python docs/ui-review-001/tools/check_ui007c.py
"""
import os
import sys
import time

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
    page.wait_for_selector('#git-save-menu:not([hidden])')
    before = page.evaluate(NEWEST, LAB)
    check('the lab was saved with the old opt-out (review_before_push false)', before['opt_out'] is False, before['opt_out'])
    page.click('#tab-progress')
    page.wait_for_selector('#git-binding-form')
    form = page.inner_text('#git-binding-form')
    check('the optional-review checkbox is gone', page.evaluate('() => !document.getElementById("git-review-before-push")') and 'Let me review changes' not in form)
    check('the form says that nothing is uploaded without the student', 'Nothing is uploaded without you' in form)
    check('device selection is still there', page.evaluate('() => document.querySelectorAll("#git-binding-form [name=git-node]").length') > 0)

    # 1. Save progress: the review opens by itself; cancelling uploads nothing
    page.click('#progress-save')
    page.wait_for_selector('#git-diff-dialog[open] #git-review-push', timeout=60000)
    title = page.inner_text('#git-diff-dialog h2')
    check('Save progress ends in the review window', title == 'Review before uploading', title)
    check('the review says nothing is uploaded unless the student chooses it', 'Nothing is uploaded to' in page.inner_text('#git-review-decision'))
    check('the review shows what changed', page.evaluate('() => document.querySelectorAll("#git-diff-dialog .git-diff, #git-diff-dialog pre, #git-diff-dialog details").length') > 0)
    shot(page, 'ui007c-review-window')
    page.click('#git-review-cancel')
    page.wait_for_function('() => !document.getElementById("git-diff-dialog").open')
    toast = page.inner_text('#toast')
    check('cancelling says "Not uploaded" and never "Saved to Git"', toast.startswith('Not uploaded') and 'Saved to Git' not in toast, toast)
    time.sleep(5)
    now = page.evaluate(NEWEST, LAB)
    job = now['job']
    check('after cancelling the save is on the VM only, waiting for the review', job['id'] != (before['job'] or {}).get('id') and job['status'] == 'review_pending' and not job['pushed'], job)
    status = page.inner_text('#git-progress-status')
    check('the status line does not claim an upload', 'Saved on this VM' in status and 'Saved to Git' not in status, status)
    shot(page, 'ui007c-after-cancel')

    # 2. The manager itself refuses an upload without the review (an old page, a script)
    refused = page.evaluate('''async (id) => { const r = await fetch('/api/git/jobs/' + id + '/retry', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({push: true})}); return {status: r.status, body: await r.json()}; }''', job['id'])
    check('the manager refuses an upload that does not state the review', refused['status'] == 409 and 'Review the changes' in refused['body'].get('detail', ''), refused)
    still = page.evaluate(NEWEST, LAB)['job']
    check('the refused upload changed nothing', still['status'] == 'review_pending' and not still['pushed'], still)

    # 3. Recent saves leads to the review; the explicit choice uploads
    row = f'#git-saves-list details[data-git-job="{job["id"]}"]'
    page.click(row + ' > summary')
    label = page.inner_text(row + ' [data-git-job-upload]')
    check('Recent saves offers "Review and upload…", not a direct upload', label == 'Review and upload…', label)
    page.click(row + ' [data-git-job-upload]')
    page.wait_for_selector('#git-diff-dialog[open] #git-review-push', timeout=30000)
    page.click('#git-review-push')
    page.wait_for_function('''async () => { const s = await (await fetch('/api/state')).json(); return s.git_jobs.some(j => j.id === "%s" && j.status === 'synced' && j.pushed && j.reviewed); }''' % job['id'], timeout=60000)
    check('choosing "Upload these changes" uploads the save and records the review', True)
    shot(page, 'ui007c-uploaded')
    page.keyboard.press('Escape')

    # 4. Save on this VM only stays local and is reviewed when it is uploaded later
    page.click('#progress-more-button')
    page.click('#progress-more-menu [data-git-action="local"]')
    page.wait_for_selector('#git-save-options[open] #git-save-confirm')
    check('the local save dialog has no upload box', page.evaluate('() => !document.getElementById("git-save-push")'))
    page.click('#git-save-confirm')
    page.wait_for_function('''async (before) => { const s = await (await fetch('/api/state')).json(); const j = s.git_jobs.filter(j => j.id !== before).sort((a, b) => a.created < b.created ? 1 : -1)[0]; return j && ['committed', 'unchanged'].includes(j.status); }''', arg=job['id'], timeout=60000)
    local = page.evaluate(NEWEST, LAB)['job']
    check('a local save opens no review and uploads nothing', not local['pushed'] and not page.evaluate('() => document.getElementById("git-diff-dialog")?.open'), local)
    check('no console or page errors', not errors, errors)
    browser.close()
sys.exit(1 if failed else 0)
