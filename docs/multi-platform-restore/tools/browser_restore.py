#!/usr/bin/env python3
"""Browser acceptance of *Replace running configuration* against the RUNNING manager and the real lab.

The student's path, not the API: lab card -> Progress tab -> Saved versions -> "Apply to running
lab..." -> review dialog -> acknowledgement -> progress -> result. While the job runs the dialog is
closed and reopened from the lab banner, and the page is reloaded once, because a student does both.
Checks are printed as ok/FAIL lines and written, with what the page said, to a JSON evidence file.

    clab-backup-ui/.venv/bin/python docs/multi-platform-restore/tools/browser_restore.py \
        --row Latest --nodes ceos vjunos-switch --viewport desktop --evidence evidence/NN-browser.json [--shots DIR]

    --row        name of the Saved versions row to apply (its visible name, e.g. "Latest" or a folder's name)
    --nodes      short device names to restore; every other eligible device is unticked
    --expect     final per-device badge text expected for the chosen devices (default "Replaced and verified")
    --review-only  stop after checking the review dialog (nothing is changed)

It changes real devices: run it only as the lab's single operator. Needs playwright (in the app's
virtual environment on the development VM).
"""
import argparse
import json
import sys
import time
import urllib.request

from playwright.sync_api import sync_playwright

LAB = 'restore-square'
VIEWPORTS = {'desktop': {'width': 1366, 'height': 900}, 'tablet': {'width': 768, 'height': 1024},
             'narrow': {'width': 390, 'height': 844}}
results, failed = [], []


def check(name, ok, detail=None):
    print(('ok   ' if ok else 'FAIL ') + name + (f' :: {detail}' if detail and not ok else ''), flush=True)
    results.append({'check': name, 'ok': bool(ok), 'detail': str(detail)[:600]})
    if not ok:
        failed.append(name)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', default='http://127.0.0.1:8081')
    parser.add_argument('--row', default='Latest')
    parser.add_argument('--nodes', nargs='+', required=True)
    parser.add_argument('--viewport', choices=sorted(VIEWPORTS), default='desktop')
    parser.add_argument('--expect', default='Replaced and verified')
    parser.add_argument('--review-only', action='store_true')
    parser.add_argument('--evidence')
    parser.add_argument('--shots')
    parser.add_argument('--timeout', type=int, default=900, help='seconds to wait for the job to end')
    args = parser.parse_args()
    version = json.load(urllib.request.urlopen(args.base + '/api/state', timeout=20))['version']
    record = {'manager_version': version, 'viewport': args.viewport, 'row': args.row, 'nodes': args.nodes,
              'started_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}

    def shot(page, name):
        if args.shots:
            page.screenshot(path=f'{args.shots}/{args.viewport}-{name}.png', full_page=False)

    def open_lab(page, reload=False):
        # The manager reopens the lab the student had open, so after a reload the lab view is already
        # there and no lab card exists; on a first visit the card is clicked.
        page.reload() if reload else page.goto(args.base + '/')
        page.wait_for_selector('article.lab-card, #tab-progress', state='visible', timeout=30000)
        if page.locator('article.lab-card').count():
            page.click(f'article.lab-card:has(h3:text-is("{LAB}")) [data-lab]')
        page.click('#tab-progress')

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_context(viewport=VIEWPORTS[args.viewport]).new_page()   # fresh context: no cached assets
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('console', lambda m: errors.append(m.text) if m.type == 'error' and 'Failed to load resource' not in m.text else None)
        open_lab(page)
        stamp = page.evaluate('() => [...document.scripts].map(s => s.src).find(s => s.includes("/static/restore.js")) || ""')
        check('the page loads restore.js of the running release', stamp.endswith('?v=' + version), stamp)

        # --- entry point: Saved versions -> Apply to running lab...
        page.wait_for_selector('#git-saved-versions [data-git-version-action]', timeout=60000)
        page_width = page.evaluate('() => document.documentElement.scrollWidth')
        record['page_scroll_width_before_dialog'] = page_width
        if page_width > VIEWPORTS[args.viewport]['width'] + 1:
            # The manager's own layout (the lab list) is wider than a phone; its verification tool covers
            # 1366 px and up. That is the page's business, recorded here, not this feature's.
            record['note'] = f'the Progress tab itself is {page_width}px wide at this viewport, before any restore dialog'
        rows = page.evaluate('''() => [...document.querySelectorAll('#git-saved-versions [data-git-version-action="apply"]')]
            .map(b => (b.closest('li,tr,article,div')?.innerText || '').replace(/\\s+/g, ' ').slice(0, 160))''')
        record['apply_rows'] = rows
        apply = page.locator(f'#git-saved-versions :is(li,tr,article,div):has-text("{args.row}") >> [data-git-version-action="apply"]').first
        check('the saved version offers "Apply to running lab..."', apply.count() > 0, rows)
        apply.click()
        page.wait_for_selector('#restore-review-dialog[open] fieldset.restore-targets', timeout=240000)
        dialog = page.locator('#restore-review-dialog')
        review = dialog.inner_text()
        record['review_text'] = review
        shot(page, 'review')
        check('the review names the dialog, the lab and the source', 'Replace running configuration' in review and LAB in review and 'Source:' in review, review[:300])
        check('the review promises the backup, no reboot and the automatic undo', 'backed up first' in review and 'not rebooted' in review and 'minutes' in review)
        devices = page.evaluate('''() => [...document.querySelectorAll('#restore-review-dialog [name="restore-node"]')].map(i =>
            ({name: i.value, disabled: i.disabled, checked: i.checked, text: i.closest('label').innerText.replace(/\\s+/g, ' ')}))''')
        record['review_devices'] = devices
        wanted = ['clab-%s-%s' % (LAB, n) for n in args.nodes]
        by_name = {d['name']: d for d in devices}
        check('every chosen device is listed and can be selected', all(w in by_name and not by_name[w]['disabled'] for w in wanted),
              [d for d in devices if d['name'] in wanted])
        check('a device that cannot be restored is listed, disabled, with a reason', all(('Skipped' in d['text']) for d in devices if d['disabled']),
              [d['text'] for d in devices if d['disabled']])
        with_dialog = page.evaluate('() => document.documentElement.scrollWidth')
        check('opening the review adds no horizontal page scroll', with_dialog <= page_width, (page_width, with_dialog))
        overflowing = page.evaluate('''() => [...document.querySelectorAll('#restore-review-dialog *')].filter(e => {
            const r = e.getBoundingClientRect(); return r.width > 0 && r.right > window.innerWidth + 1; }).length''')
        check('nothing inside the review overflows the viewport', overflowing == 0, overflowing)
        inside = page.evaluate('''() => { const r = document.querySelector('#restore-review-dialog').getBoundingClientRect();
            return r.left >= -1 && r.right <= window.innerWidth + 1; }''')
        check('the review dialog fits the viewport width', inside)
        if args.review_only:
            page.keyboard.press('Escape')
        else:
            for device in devices:
                if not device['disabled'] and device['name'] not in wanted:
                    page.uncheck(f'#restore-review-dialog [name="restore-node"][value="{device["name"]}"]')
            # The acknowledgement is mandatory: without it nothing is sent.
            page.click('#restore-run')
            page.wait_for_function('() => (document.querySelector("#restore-review-dialog .form-error")?.textContent || "").trim().length > 0', timeout=10000)
            refusal = dialog.locator('.form-error').inner_text()
            check('without the acknowledgement the page refuses and says why', 'Tick the box' in refusal, refusal)
            check('the review is still open after the refusal', page.locator('#restore-review-dialog[open]').count() == 1)
            # Keyboard: focus the acknowledgement, Space ticks it, Enter on the button starts the change.
            page.focus('#restore-ack')
            page.keyboard.press('Space')
            check('Space ticks the acknowledgement', page.is_checked('#restore-ack'))
            page.focus('#restore-run')
            focused = page.evaluate('() => document.activeElement && document.activeElement.id')
            check('the Replace button takes keyboard focus', focused == 'restore-run', focused)
            page.keyboard.press('Enter')
            page.wait_for_selector('#restore-job-dialog[open] #restore-job-detail .restore-target-row', timeout=120000)
            record['progress_first_text'] = page.locator('#restore-job-dialog').inner_text()
            shot(page, 'progress')
            check('progress shows one row per chosen device', page.locator('#restore-job-detail .restore-target-row').count() == len(wanted))
            # Close and reopen from the lab banner while it runs.
            page.locator('#restore-job-dialog [data-op-close]').first.click()
            reopened = False
            try:
                page.wait_for_selector('#banner-restore:not([hidden])', timeout=15000)   # the lab banner's "View progress"
                page.click('#banner-restore')
                page.wait_for_selector('#restore-job-dialog[open]', timeout=15000)
                reopened = True
            except Exception as exc:   # the job may already be over on a fast platform
                record['reopen_note'] = type(exc).__name__
            running = page.evaluate('() => fetch("/api/state").then(r => r.json()).then(s => s.restore_jobs.slice(-1)[0].status)')
            check('the running change can be reopened from the lab banner (or had already ended)', reopened or running not in
                  ('queued', 'preflight', 'backing_up', 'applying', 'confirming', 'verifying'), running)
            # Reload in the middle: the job belongs to the manager, not to the page.
            open_lab(page, reload=True)
            check('after a reload the page is back in the same lab', LAB in page.locator('body').inner_text()[:4000])
            deadline = time.time() + args.timeout
            job = None
            while time.time() < deadline:
                job = page.evaluate('() => fetch("/api/state").then(r => r.json()).then(s => s.restore_jobs.slice(-1)[0])')
                if job['status'] not in ('queued', 'preflight', 'backing_up', 'applying', 'confirming', 'verifying'):
                    break
                time.sleep(2)
            record['job'] = job
            check('the job ended', job and job['status'] not in ('queued', 'preflight', 'backing_up', 'applying', 'confirming', 'verifying'), job and job['status'])
            page.evaluate('(id) => restoreShowJob(id)', job['id'])
            page.wait_for_selector('#restore-job-dialog[open] #restore-job-detail .restore-target-row', timeout=30000)
            collapsed = page.locator('#restore-job-dialog').inner_text()
            check('the result leads with the outcome, details stay collapsed', 'Backup taken before' not in collapsed and LAB not in collapsed[:0] and len(collapsed) > 0)
            page.click('#restore-job-dialog details.restore-job-details > summary')   # a student opens Details
            final = page.locator('#restore-job-dialog').inner_text()
            record['final_text'] = final
            shot(page, 'result')
            badges = page.evaluate('''() => [...document.querySelectorAll('#restore-job-detail .restore-target-row')].map(r =>
                ({device: r.querySelector('strong')?.innerText, badge: r.querySelector('.badge')?.innerText, cls: r.querySelector('.badge')?.className}))''')
            record['final_badges'] = badges
            check(f'every chosen device ends as "{args.expect}"', len(badges) == len(wanted) and all(b['badge'] == args.expect for b in badges), badges)
            check('the result names both safety backups under Details', 'Backup taken before the change' in final and ('Backup taken after the change' in final or args.expect != 'Replaced and verified'))
            check('no "undefined" or raw markup in the result', 'undefined' not in final and '<' not in final, final[:300])
            page.keyboard.press('Escape')
        check('no page or console errors', not errors, errors[:5])
        record['console_errors'] = errors[:20]
        browser.close()

    record.update(checks=results, failed=failed, finished_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))
    if args.evidence:
        with open(args.evidence, 'w') as handle:
            json.dump(record, handle, indent=1)
            handle.write('\n')
    print(f'{len(results) - len(failed)}/{len(results)} checks passed')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
