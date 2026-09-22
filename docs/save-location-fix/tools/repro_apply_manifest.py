#!/usr/bin/env python3
"""Browser reproduction of "save location fix" reproduction 2 (manifest folders not appliable).

Runs against the RUNNING manager (1.30.30) and the real lab `restore-square`, through the product:
the Progress tab's folder browser (Change folder…) and the Saved versions list. It only browses and
screenshots; it never applies anything to the running lab (no restore is submitted from here — the API
preflight/version checks in the markdown report cover that, and restore submission is explicitly out of
scope for this reproduction).

Preconditions (done once, out of band, by the operator): a second Git checkout pushed reference copies
of the lab's own Latest save to `save-fix/Final` (direct manifest, no `latest` child), a deep path
`save-fix/course/lab/reference/solution`, and a legacy-shaped `save-fix/Broken/latest`; the manager's
own "Update from the repository" (`POST /api/labs/<lab>/git/update`) pulled that commit.

    clab-backup-ui/.venv/bin/python docs/save-location-fix/tools/repro_apply_manifest.py \\
        --evidence docs/save-location-fix/evidence/01-repro-apply-manifest.json \\
        --shots docs/save-location-fix/evidence
"""
import argparse
import json
import pathlib
import sys
import time

from playwright.sync_api import sync_playwright

BASE = 'http://127.0.0.1:8081'
LAB_ID = '904a35a79dc341ce8a4638f83fc34185'
LAB_NAME = 'restore-square'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--evidence', required=True)
    ap.add_argument('--shots', required=True)
    args = ap.parse_args()
    pathlib.Path(args.shots).mkdir(parents=True, exist_ok=True)

    record = {'manager_base': BASE, 'lab_id': LAB_ID, 'lab_name': LAB_NAME,
              'started_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'steps': {}}
    checks, failed = [], []

    def check(name, ok, detail=None):
        print(('ok   ' if ok else 'FAIL ') + name + (f' :: {detail}' if detail and not ok else ''), flush=True)
        checks.append({'check': name, 'ok': ok, 'detail': str(detail)[:800] if detail is not None else None})
        if not ok:
            failed.append(name)

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_context(viewport={'width': 1366, 'height': 900}).new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('console', lambda m: errors.append(m.text) if m.type == 'error' and 'Failed to load resource' not in m.text else None)

        page.goto(BASE + '/')
        page.wait_for_selector('article.lab-card, #tab-progress', state='visible', timeout=30000)
        if page.locator('article.lab-card').count():
            page.click(f'article.lab-card:has(h3:text-is("{LAB_NAME}")) [data-lab]')
        page.click('#tab-progress')
        page.wait_for_selector('#git-repository-content .git-save-location', timeout=30000)

        # Saved versions card, as the student sees it, before touching the folder browser.
        page.wait_for_selector('#git-saved-versions', timeout=20000)
        page.locator('#git-saved-versions').scroll_into_view_if_needed()
        page.screenshot(path=f'{args.shots}/01-a-saved-versions.png')
        saved_versions_text = page.locator('#git-saved-versions').inner_text()
        record['steps']['saved_versions_text'] = saved_versions_text[:2000]

        change_folder = page.locator('#git-change-folder')
        if change_folder.count() and change_folder.get_attribute('open') is None:
            page.click('#git-change-folder summary')
        page.wait_for_selector('#git-places-panel .git-places-head', timeout=30000)

        def go_to(path):
            page.click(f'[data-git-place="{path}"]', timeout=15000)
            page.wait_for_selector('#git-places-panel .git-crumbs [aria-current=page]', timeout=15000)

        # save-fix/Final: a direct manifest folder (no `latest` child) -- expect NO Apply button.
        go_to('save-fix')
        go_to('save-fix/Final')
        page.wait_for_timeout(300)
        page.locator('#git-places-panel').scroll_into_view_if_needed()
        page.screenshot(path=f'{args.shots}/01-b-final-no-apply.png')
        final_apply = page.locator('#git-places-panel [data-git-places-action="apply"]')
        check('save-fix/Final (direct manifest, no latest/ child) offers NO Apply button', final_apply.count() == 0,
              f'{final_apply.count()} apply button(s) found')
        record['steps']['final_listing_text'] = page.locator('#git-places-panel .git-listing').inner_text()[:1500]

        # save-fix/Broken (the legacy lab-folder-with-latest-child layout): expect Apply IS offered.
        go_to('save-fix')
        go_to('save-fix/Broken')
        page.wait_for_timeout(300)
        page.screenshot(path=f'{args.shots}/01-c-broken-has-apply.png')
        broken_apply = page.locator('#git-places-panel [data-git-places-action="apply"]')
        check('save-fix/Broken (legacy parent of a latest/ child) DOES offer Apply to running lab…', broken_apply.count() == 1,
              f'{broken_apply.count()} apply button(s) found')
        record['steps']['broken_listing_text'] = page.locator('#git-places-panel .git-listing').inner_text()[:1500]

        # save-fix/course/lab/reference/solution: another direct manifest folder, deeper -- expect NO Apply.
        go_to('save-fix')
        go_to('save-fix/course')
        go_to('save-fix/course/lab')
        go_to('save-fix/course/lab/reference')
        go_to('save-fix/course/lab/reference/solution')
        page.wait_for_timeout(300)
        page.screenshot(path=f'{args.shots}/01-d-deep-solution-no-apply.png')
        deep_apply = page.locator('#git-places-panel [data-git-places-action="apply"]')
        check('save-fix/course/lab/reference/solution (deep direct manifest folder) also offers NO Apply button', deep_apply.count() == 0,
              f'{deep_apply.count()} apply button(s) found')
        record['steps']['deep_listing_text'] = page.locator('#git-places-panel .git-listing').inner_text()[:1500]

        check('no page or console errors', not errors, errors[:8])
        browser.close()

    record['checks'] = checks
    record['failed'] = failed
    record['finished_utc'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    with open(args.evidence, 'w') as fh:
        json.dump(record, fh, indent=1)
        fh.write('\n')
    passed = sum(1 for c in checks if c['ok'])
    print(f'{passed} passed, {len(failed)} failed')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
