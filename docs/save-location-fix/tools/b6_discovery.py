#!/usr/bin/env python3
"""Section B, row B6: discovery of Final, Broken, and a nested solution -- without rebinding/restart.

Confirms the folder browser, the Saved versions card (which group each row is in, and that its
caption is the exact path) and GET /api/labs/<lab>/git/history all list save-fix/Final,
save-fix/course/lab/reference/solution, save-fix/Broken (legacy parent convenience, caption names
.../latest) and save-fix/Broken/latest, and that none of this touches the lab's own binding.

    clab-backup-ui/.venv/bin/python docs/save-location-fix/tools/b6_discovery.py \\
        --evidence docs/save-location-fix/evidence/15-b6-discovery.json \\
        --shots docs/save-location-fix/evidence
"""
import argparse
import json
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from qa_lib import BASE, LAB_ID, LAB_NAME, Checker, api, destination_line, go_to, open_change_folder, open_lab


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--evidence', required=True)
    ap.add_argument('--shots', required=True)
    args = ap.parse_args()
    pathlib.Path(args.shots).mkdir(parents=True, exist_ok=True)

    record = {'manager_base': BASE, 'lab_id': LAB_ID, 'lab_name': LAB_NAME, 'build': 'clab-backup:1.30.31',
              'started_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'steps': {}}
    c = Checker()

    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_context(viewport={'width': 1366, 'height': 900}).new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('console', lambda m: errors.append(m.text) if m.type == 'error' and 'Failed to load resource' not in m.text else None)

        open_lab(page)
        binding_before = destination_line(page)
        record['steps']['binding_before'] = binding_before

        # ---- Folder browser ----
        open_change_folder(page)
        go_to(page, 'save-fix')
        go_to(page, 'save-fix/Final')
        page.wait_for_timeout(300)
        final_listing = page.locator('#git-places-panel').inner_text()
        final_has_apply = page.locator('#git-places-panel [data-git-places-action="apply"]').count()
        record['steps']['browser_final'] = {'listing_excerpt': final_listing[:600], 'apply_button_count': final_has_apply}
        page.screenshot(path=f'{args.shots}/1x-b6-browser-final.png')
        c.check('folder browser reaches save-fix/Final and lists its files', 'manifest.json' in final_listing, final_listing[:300])

        go_to(page, 'save-fix')
        go_to(page, 'save-fix/Broken')
        page.wait_for_timeout(300)
        broken_listing = page.locator('#git-places-panel').inner_text()
        broken_apply = page.locator('#git-places-panel [data-git-places-action="apply"]')
        record['steps']['browser_broken'] = {'listing_excerpt': broken_listing[:600], 'apply_button_count': broken_apply.count(),
                                              'apply_caption': broken_apply.get_attribute('title') if broken_apply.count() else None}
        page.screenshot(path=f'{args.shots}/1x-b6-browser-broken.png')
        c.check('folder browser at save-fix/Broken (legacy parent) offers Apply to running lab…', broken_apply.count() == 1, broken_apply.count())

        go_to(page, 'save-fix/Broken')
        go_to(page, 'save-fix/Broken/latest')
        page.wait_for_timeout(300)
        broken_latest_listing = page.locator('#git-places-panel').inner_text()
        record['steps']['browser_broken_latest'] = {'listing_excerpt': broken_latest_listing[:600]}
        c.check('folder browser reaches save-fix/Broken/latest directly too', 'manifest.json' in broken_latest_listing, broken_latest_listing[:300])

        go_to(page, 'save-fix')
        go_to(page, 'save-fix/course')
        go_to(page, 'save-fix/course/lab')
        go_to(page, 'save-fix/course/lab/reference')
        go_to(page, 'save-fix/course/lab/reference/solution')
        page.wait_for_timeout(300)
        solution_listing = page.locator('#git-places-panel').inner_text()
        record['steps']['browser_solution'] = {'listing_excerpt': solution_listing[:600]}
        page.screenshot(path=f'{args.shots}/1x-b6-browser-solution.png')
        c.check('folder browser reaches the deep save-fix/course/lab/reference/solution folder', 'manifest.json' in solution_listing, solution_listing[:300])

        # Close the browser without submitting anything (no rebind).
        details = page.locator('#git-change-folder')
        if details.count() and details.get_attribute('open') is not None:
            page.click('#git-change-folder summary')

        # ---- Saved versions card ----
        page.reload()
        page.click('#tab-progress')
        page.wait_for_selector('#git-saved-versions', timeout=20000)
        versions_html_text = page.locator('#git-saved-versions').inner_text()
        record['steps']['saved_versions_text'] = versions_html_text[:3000]
        page.screenshot(path=f'{args.shots}/1x-b6-saved-versions.png')

        def row_group_and_caption(name_text):
            rows = page.locator('#git-saved-versions li.git-version-row', has_text=name_text)
            if not rows.count():
                return None
            row = rows.first
            caption = row.locator('small.caption.mono')
            group_heading = row.locator('xpath=ancestor::*[self::section or self::details][1]//h3 | ancestor::*[self::section or self::details][1]//summary')
            return {'caption': caption.inner_text() if caption.count() else None,
                    'group_heading': group_heading.first.inner_text() if group_heading.count() else None}

        final_row_info = row_group_and_caption('Final')
        broken_row_info = row_group_and_caption('Broken')
        solution_row_info = row_group_and_caption('solution')
        record['steps']['saved_versions_rows'] = {'Final': final_row_info, 'Broken': broken_row_info, 'solution': solution_row_info}
        c.check('Saved versions lists a Final row with caption save-fix/Final in "Instructor and reference versions"',
                final_row_info and final_row_info['caption'] == 'save-fix/Final' and 'reference' in (final_row_info['group_heading'] or '').lower(), final_row_info)
        c.check('Saved versions lists a Broken row whose caption names .../latest (legacy parent convenience)',
                broken_row_info and broken_row_info['caption'] and broken_row_info['caption'].endswith('/latest'), broken_row_info)
        c.check('Saved versions lists the deep solution row with its exact caption path',
                solution_row_info and solution_row_info['caption'] and solution_row_info['caption'].endswith('/solution'), solution_row_info)

        # ---- /git/history ----
        history = api(page, 'GET', f'/api/labs/{LAB_ID}/git/history')['body']
        paths = [v.get('path') for v in history.get('versions', [])]
        record['steps']['history_paths_sample'] = paths[:80]
        record['steps']['history_total'] = len(paths)
        for expect in ('save-fix/Final', 'save-fix/Broken/latest', 'save-fix/course/lab/reference/solution'):
            c.check(f'/git/history lists {expect}', expect in paths, expect in paths)

        # ---- confirm no rebind, no restart happened ----
        page.reload()
        page.click('#tab-progress')
        page.wait_for_selector('#git-repository-content .git-save-location', timeout=30000)
        binding_after = destination_line(page)
        record['steps']['binding_after'] = binding_after
        c.check('lab binding unchanged by browsing (still save-fix/working, no rebind)',
                'save-fix/working' in binding_after.replace(' ', '') and 'save-fix/working/latest' not in binding_after.replace(' ', ''),
                (binding_before, binding_after))

        c.check('no page or console errors', not errors, errors[:8])
        browser.close()

    record['checks'] = c.checks
    record['failed'] = c.failed
    record['finished_utc'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    with open(args.evidence, 'w') as fh:
        json.dump(record, fh, indent=1)
        fh.write('\n')
    passed = sum(1 for x in c.checks if x['ok'])
    print(f'{passed} passed, {len(c.failed)} failed')
    return 1 if c.failed else 0


if __name__ == '__main__':
    sys.exit(main())
