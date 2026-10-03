#!/usr/bin/env python3
"""Usability, keyboard, visual and accessibility scan: Network design (Advanced > Experimental) and Restart device.

Two targets, two rules:

* **Network design** (Advanced > Experimental) on the fixture manager (`docs/redesign/tools/fixture_manager.py`: the real app on
  scratch state with the real netlab engine, no VM). With `--start-fixture` this tool starts its own fixture
  on `--port` with a fresh data directory under `--data-root` for every browser and stops it afterwards.
  Everything is allowed there, including saving and generating.
* **Restart device** on the deployed manager (`--live-url`, lab `restore-square`), strictly read-only: every
  request that is not a GET/HEAD or `POST /api/operations/preview` is aborted by a route guard in the
  browser context, so `/api/operations/confirm` can never be reached. The review is only opened and cancelled.

axe-core is injected from a local file (`--axe`, e.g. from `npm pack axe-core`); the contexts use Playwright's
`bypass_csp` only so that the injected script may run (the app's CSP is `script-src 'self'`).

    npm pack axe-core && tar xzf axe-core-*.tgz        # gives package/axe.min.js
    PATH="$PWD/clab-backup-ui/.venv/bin:$PATH" clab-backup-ui/.venv/bin/python \\
        docs/netlab-ui-qa/tools/usability_scan.py --axe <dir>/package/axe.min.js \\
        --start-fixture --port 8103 --data-root <scratch dir> [--browsers chromium,firefox] [--no-live]

Writes `scan-<browser>.json`, `axe-<browser>-<screen>.json` and screenshots to `--out`
(default `docs/netlab-ui-qa/evidence/usability/`). Exit status 0 even when findings exist: this is a
measuring tool, the report interprets it.
"""
import argparse
import json
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
FIXTURE = ROOT / 'docs' / 'redesign' / 'tools' / 'fixture_manager.py'
VIEWPORTS = [('1920x1080', 1920, 1080, 1), ('1366x768', 1366, 768, 1), ('1024x768', 1024, 768, 1),
             ('768x1024', 768, 1024, 1), ('390x844', 390, 844, 1), ('zoom200-1366x768', 683, 384, 2)]
ACTIVE_JS = '''() => { const e = document.activeElement; if (!e || e === document.body) return 'BODY';
  const d = e.closest && e.closest('dialog[open]');
  const label = (e.getAttribute('aria-label') || e.textContent || e.value || '').trim().replace(/\\s+/g, ' ').slice(0, 40);
  return e.tagName.toLowerCase() + (e.id ? '#' + e.id : '') + (e.getAttribute('data-map-node') ? '[' + e.getAttribute('data-map-node') + ']' : '')
    + (e.getAttribute('role') ? '[role=' + e.getAttribute('role') + ']' : '') + ' "' + label + '"' + (d ? ' in dialog#' + d.id : ''); }'''
OVERFLOW_JS = '''(scope) => {
  const vw = document.documentElement.clientWidth, sw = document.documentElement.scrollWidth, root = document.querySelector(scope) || document.body;
  const scrolls = (a) => { while (a && a !== document.body) { const cs = getComputedStyle(a); if (/(auto|scroll)/.test(cs.overflowX)) { const r = a.getBoundingClientRect(); if (r.right <= vw + 1 && r.left >= -1) return true; } a = a.parentElement; } return false; };
  const out = [];
  for (const e of root.querySelectorAll('button, input, select, textarea, a[href], summary, [role=menuitem], [tabindex="0"]')) {
    const cs = getComputedStyle(e); if (cs.visibility === 'hidden' || cs.display === 'none' || !e.getClientRects().length) continue;
    const r = e.getBoundingClientRect(); if (r.width === 0) continue;
    if ((r.right > vw + 1 || r.left < -1) && !scrolls(e.parentElement)) out.push({el: e.tagName.toLowerCase() + (e.id ? '#' + e.id : ''), text: (e.textContent || e.value || '').trim().slice(0, 30), left: Math.round(r.left), right: Math.round(r.right)});
  }
  return {viewport: vw, scrollWidth: sw, pageOverflow: sw > vw + 1, clippedControls: out.slice(0, 15), clippedCount: out.length};
}'''


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def get_json(url):
    with urllib.request.urlopen(url, timeout=10) as response:
        return json.loads(response.read())


def wait_http(url, seconds=90):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            return get_json(url)
        except Exception:
            time.sleep(0.5)
    raise SystemExit('no answer at ' + url)


class Scan:
    def __init__(self, browser_name, out, axe_path):
        self.browser, self.out, self.axe_path = browser_name, out, axe_path
        self.record = {'browser': browser_name, 'started': now(), 'checks': [], 'keyboard': [], 'viewports': [],
                       'axe': {}, 'console_errors': [], 'notes': []}

    def check(self, area, name, ok, detail=''):
        self.record['checks'].append({'area': area, 'name': name, 'ok': bool(ok), 'detail': str(detail)[:400]})
        print(('  ok    ' if ok else '  FIND  ') + area + ': ' + name + ('' if ok else ' -- ' + str(detail)[:160]), flush=True)

    def key(self, control, sequence, reachable, operable, focus_return, detail=''):
        self.record['keyboard'].append({'control': control, 'keys': sequence, 'reachable': reachable, 'operable': operable,
                                        'focus_return': focus_return, 'detail': str(detail)[:400]})
        print('  key   %s: reach=%s op=%s return=%s %s' % (control, reachable, operable, focus_return, str(detail)[:120]), flush=True)

    def shot(self, page, name, full=False):
        path = self.out / ('%s-%s.png' % (self.browser, name))
        try:
            page.screenshot(path=str(path), full_page=full)
        except Exception as error:
            self.record['notes'].append('screenshot %s failed: %s' % (name, error))
        return path.name

    def axe(self, page, name, context=None):
        try:
            if not page.evaluate('() => typeof window.axe !== "undefined"'):
                page.add_script_tag(path=str(self.axe_path))
            result = page.evaluate('''async (ctx) => { const r = await axe.run(ctx ? document.querySelector(ctx) : document,
                {resultTypes: ['violations', 'incomplete']}); return {violations: r.violations.map(v => ({id: v.id, impact: v.impact, help: v.help,
                nodes: v.nodes.map(n => ({target: n.target.join(' '), html: n.html.slice(0, 220), summary: (n.failureSummary || '').slice(0, 300)}))})),
                incomplete: r.incomplete.map(v => ({id: v.id, impact: v.impact, count: v.nodes.length})), version: axe.version}; }''', context)
        except Exception as error:
            result = {'error': str(error)[:300], 'violations': [], 'incomplete': []}
        (self.out / ('axe-%s-%s.json' % (self.browser, name))).write_text(json.dumps(result, indent=1))
        self.record['axe'][name] = [{'id': v['id'], 'impact': v['impact'], 'count': len(v['nodes'])} for v in result.get('violations', [])]
        print('  axe   %s: %s' % (name, ', '.join('%s(%s)x%d' % (v['id'], v['impact'], len(v['nodes'])) for v in result.get('violations', [])) or 'no violations'), flush=True)
        return result

    def active(self, page):
        return page.evaluate(ACTIVE_JS)

    def text(self, page, selector):
        node = page.locator(selector).first
        return (node.text_content() or '').strip() if node.count() else ''


def lab_id(base, name):
    return next(l['id'] for l in get_json(base + '/api/state')['labs'] if l['name'] == name)


def open_design(page, base, lab):
    page.goto(base + '/#lab=' + lab + '&view=design')
    page.wait_for_selector('#design-view:not([hidden])', timeout=20000)
    page.wait_for_function('() => !(document.getElementById("design-state")?.textContent || "").includes("Loading")', timeout=20000)
    page.wait_for_timeout(600)


def open_design_via_advanced(page, timeout=15000):
    """Advanced > Experimental > Network design: the Design tab is gone, so click #tab-advanced, open
    #experimental-design (closed by default) and wait for the #design-view region to be visible."""
    page.click('#tab-advanced')
    if not page.evaluate("() => document.getElementById('experimental-design').open"):
        page.click('#experimental-design > summary')
    page.wait_for_selector('#design-view', state='visible', timeout=timeout)


def unfocus(page):
    page.locator('#design-view h2').first.click()
    page.wait_for_timeout(200)


def wait_not(page, word, timeout=180000):
    page.wait_for_function('(w) => !(document.getElementById("design-state")?.textContent || "").includes(w)', arg=word, timeout=timeout)


def generate(page):
    """Click Generate plan and wait for that generation to settle (it must first be seen starting or finished)."""
    page.click('#design-generate')
    try:
        page.wait_for_function('() => /Generating|ready|failed|interrupted/i.test(document.getElementById("design-state")?.textContent || "")', timeout=15000)
    except Exception:
        pass
    page.wait_for_timeout(300)
    wait_not(page, 'Generating')


def design_journey(s, page, base, full):
    ospf, bgp = lab_id(base, 'ospf-basics'), lab_id(base, 'BGP_TheoryToPractice')
    # 1. The empty design, as a student meets it.
    open_design(page, base, ospf)
    s.shot(page, 'D01-design-empty')
    s.check('design', 'state pill and text are not the same words twice',
            s.text(page, '#design-state-pill') != s.text(page, '#design-state-text'),
            '%r / %r' % (s.text(page, '#design-state-pill'), s.text(page, '#design-state-text')))
    files_caption = s.text(page, '#design-files')
    s.check('design', 'the Generated files card does not say applying is unavailable while Apply to devices exists',
            'not available yet' not in files_caption, files_caption[:160])
    if full:
        s.axe(page, 'design-empty', '#design-view')
    # 2. The primary button on an empty design.
    generate_disabled = page.locator('#design-generate').is_disabled()
    page.click('#design-generate')
    page.wait_for_timeout(700)
    toast = s.text(page, '#toast')
    s.check('design', 'Generate plan with nothing saved is disabled with a reason, or the guidance says to save first',
            generate_disabled or 'Save' in s.text(page, '#design-detail'),
            'enabled; detail says %r; click gives toast %r' % (s.text(page, '#design-detail'), toast))
    # 3. Unsaved, then saved.
    page.locator('input[name="design-module"][value="ospf"]').check()
    page.wait_for_timeout(300)
    s.check('design', 'editing shows Unsaved changes', 'Unsaved' in s.text(page, '#design-state'), s.text(page, '#design-state'))
    ospf_settings_gap = page.evaluate('''() => { const box = document.querySelector('input[name="design-module"][value="ospf"]').getBoundingClientRect();
        const area = document.getElementById('design-ospf-area').getBoundingClientRect(); return Math.round(area.top - box.top); }''')
    s.check('design', 'the OSPF area field appears near the OSPF checkbox (under 200 px)', ospf_settings_gap < 200, 'distance %s px' % ospf_settings_gap)
    if full:
        s.axe(page, 'design-unsaved', '#design-view')
    page.click('#design-save')
    wait_not(page, 'Unsaved', 20000)
    s.check('design', 'a saved design without a plan says it is saved', 'saved' in s.text(page, '#design-state').lower(), s.text(page, '#design-state'))
    # 4. An unsaved edit, then Generate: what does the plan use, and is the student told?
    unfocus(page)
    page.fill('#design-ospf-area', '0.0.0.9')
    page.locator('#design-ospf-area').dispatch_event('change')
    unfocus(page)
    page.click('#design-generate')
    page.wait_for_timeout(800)
    toast = s.text(page, '#toast')
    wait_not(page, 'Generating')
    plan = s.text(page, '#design-plan-body')
    s.check('design', 'Generate with an unsaved edit either uses it or says it did not',
            '0.0.0.9' in plan or 'unsaved' in (toast + s.text(page, '#design-plan-status')).lower(),
            'plan has area 0.0.0.9: %s; toast %r; plan status %r; state %r' % ('0.0.0.9' in plan, toast, s.text(page, '#design-plan-status'), s.text(page, '#design-state')))
    s.shot(page, 'D02-plan-while-unsaved')
    page.click('#design-save')
    wait_not(page, 'Unsaved', 20000)
    generate(page)
    s.check('design', 'plan ready', 'ready' in s.text(page, '#design-state').lower(), s.text(page, '#design-state'))
    s.shot(page, 'D03-plan-ready-full', full=True)
    reasons = page.evaluate('''() => [...document.querySelectorAll('#design-plan .caption, #design-plan small, #design-plan p')].filter(p => p.offsetParent).map(p => p.textContent.trim()).filter(t => t)''')
    s.record['notes'].append('plan card captions on ospf-basics: %s' % reasons)
    if full:
        s.axe(page, 'design-plan-ready', '#design-view')
    # 5. Keyboard: the tab list reaches Design.
    page.locator('#tab-topology').focus()
    for _ in range(4):
        page.keyboard.press('ArrowRight')
        page.wait_for_timeout(150)
    s.key('Advanced tab (hosts Experimental > Network design; there is no Design tab)', 'focus Topology tab, ArrowRight x4', 'tab-advanced' in s.active(page), page.locator('#tab-advanced[aria-selected="true"]').count() == 1 and page.locator('#tab-design').count() == 0, 'n/a', s.active(page))
    open_design_via_advanced(page)
    page.wait_for_timeout(1500)
    unfocus(page)
    # 6. More menu by keyboard.
    page.locator('#design-more-button').focus()
    page.keyboard.press('Enter')
    page.wait_for_timeout(300)
    opened = page.locator('#design-more-menu:not([hidden])').count() == 1
    first = s.active(page)
    visits = []
    for _ in range(5):
        page.keyboard.press('ArrowDown')
        page.wait_for_timeout(80)
        visits.append(s.active(page))
    page.keyboard.press('Escape')
    page.wait_for_timeout(200)
    s.key('More menu (#design-more-button)', 'Enter; ArrowDown x5; Escape', True, opened and 'design-export' in first,
          'design-more-button' in s.active(page), 'first=%s; arrows=%s' % (first, visits))
    if full:
        page.locator('#design-more-button').click()
        page.wait_for_timeout(200)
        s.axe(page, 'design-more-menu', '#design-view')
        page.keyboard.press('Escape')
    # 7. Renumber and Remove dialogs by keyboard.
    for item, dialog_id, name in (('design-renumber', 'design-renumber-dialog', 'Renumber'), ('design-clear', 'design-clear-dialog', 'Remove design')):
        page.locator('#design-more-button').focus()
        page.keyboard.press('Enter')
        page.wait_for_timeout(200)
        for _ in range(6):
            if item in s.active(page):
                break
            page.keyboard.press('ArrowDown')
            page.wait_for_timeout(60)
        page.keyboard.press('Enter')
        page.wait_for_timeout(500)
        inside = s.active(page)
        order = []
        for _ in range(5):
            page.keyboard.press('Tab')
            page.wait_for_timeout(60)
            order.append(s.active(page))
        contained = all(('dialog#' + dialog_id) in o for o in order if o != 'BODY')
        named = page.evaluate('(id) => { const d = document.getElementById(id); return !!(d && (d.getAttribute("aria-labelledby") || d.getAttribute("aria-label"))); }', dialog_id)
        modal = page.evaluate('(id) => document.getElementById(id)?.matches(":modal") || false', dialog_id)
        if full:
            s.axe(page, 'dialog-' + dialog_id, '#' + dialog_id)
            s.shot(page, 'D04-' + dialog_id)
        page.keyboard.press('Escape')
        page.wait_for_timeout(300)
        s.key(name + ' dialog (#' + dialog_id + ')', 'More: Enter, ArrowDown to item, Enter; Tab x5; Escape',
              ('dialog#' + dialog_id) in inside, modal and contained, 'design-more-button' in s.active(page),
              'focus in=%s; tab order=%s; accessible name=%s' % (inside, order, named))
    # 8. Advanced by keyboard.
    summary = page.locator('#design-advanced-details > summary')
    summary.focus()
    page.keyboard.press('Enter')
    page.wait_for_timeout(600)
    width = page.evaluate('() => Math.round(document.getElementById("design-advanced").getBoundingClientRect().width)')
    labelled = page.evaluate('() => { const t = document.getElementById("design-advanced"); return !!(t.labels.length || t.getAttribute("aria-label") || t.getAttribute("aria-labelledby")); }')
    page.keyboard.press('Tab')
    s.key('Advanced (<details>, #design-advanced)', 'focus summary, Enter, Tab', True, page.locator('#design-advanced-details[open]').count() == 1,
          'n/a', 'textarea focused=%s; width=%spx; labelled=%s' % ('design-advanced' in s.active(page), width, labelled))
    s.check('design', 'the Advanced JSON editor has an accessible name', labelled)
    s.check('design', 'the Advanced JSON editor is at least 400 px wide at 1366 px', width >= 400, '%s px' % width)
    if full:
        s.axe(page, 'design-advanced-open', '#design-view')
        page.locator('#design-advanced').scroll_into_view_if_needed()
        s.shot(page, 'D05-advanced-open')
    unfocus(page)
    # 9. Add VRF / Remove by keyboard: where does focus go?
    page.locator('#design-vrf-add').focus()
    page.keyboard.press('Enter')
    page.wait_for_timeout(400)
    after_add = s.active(page)
    page.locator('[data-design-vrf-remove]').first.focus()
    page.keyboard.press('Enter')
    page.wait_for_timeout(400)
    after_remove = s.active(page)
    s.key('Add VRF / Remove (#design-vrf-add, [data-design-vrf-remove])', 'Enter on Add VRF; Enter on Remove', True, True,
          'n/a', 'after Add focus=%s; after Remove focus=%s' % (after_add, after_remove))
    s.check('design', 'after Add VRF focus moves to the new row (or stays on Add)', 'vrf' in after_add.lower(), after_add)
    s.check('design', 'after Remove focus is not lost to the page body', after_remove != 'BODY', after_remove)
    page.click('#design-save')
    wait_not(page, 'Unsaved', 20000)
    # 10. A generated file by keyboard.
    view = page.locator('#design-files button[data-design-view-file]').first
    view_name = view.evaluate('(b) => b.getAttribute("aria-label") || b.textContent.trim()')
    view.focus()
    page.keyboard.press('Enter')
    page.wait_for_selector('dialog#design-file-dialog[open]', timeout=10000)
    page.wait_for_timeout(300)
    inside = s.active(page)
    if full:
        s.axe(page, 'dialog-design-file-dialog', '#design-file-dialog')
    page.keyboard.press('Escape')
    page.wait_for_timeout(300)
    s.key('Generated file View (dialog#design-file-dialog)', 'Enter on View; Escape', True, 'design-file-dialog' in inside,
          'data-design-view-file' in page.evaluate('() => document.activeElement.outerHTML.slice(0, 80)'), 'button name=%r; focus in=%s' % (view_name, inside))
    s.check('design', 'View buttons name their file', view_name.strip() != 'View', view_name)
    # 11. The running, git-bound lab: Export plan to Git and Apply to devices.
    open_design(page, base, bgp)
    unfocus(page)
    page.locator('input[name="design-module"][value="ospf"]').check()
    page.click('#design-save')
    wait_not(page, 'Unsaved', 20000)
    generate(page)
    warnings = page.locator('#design-plan-warnings-wrap')
    if warnings.count() and warnings.is_visible():
        s.check('design', 'plan warnings are visible without opening a fold or carry a count',
                warnings.evaluate('e => e.open') or any(ch.isdigit() for ch in s.text(page, '#design-plan-warnings-wrap > summary')),
                'summary %r, collapsed, %d warnings' % (s.text(page, '#design-plan-warnings-wrap > summary'), page.locator('#design-plan-warnings li').count()))
    page.locator('#design-export-git').focus()
    page.keyboard.press('Enter')
    page.wait_for_selector('dialog#design-export-git-dialog[open]', timeout=10000)
    page.wait_for_timeout(300)
    inside = s.active(page)
    order = []
    for _ in range(6):
        page.keyboard.press('Tab')
        page.wait_for_timeout(60)
        order.append(s.active(page))
    if full:
        s.axe(page, 'dialog-design-export-git', '#design-export-git-dialog')
        s.shot(page, 'D06-export-git-dialog')
    page.keyboard.press('Escape')
    page.wait_for_timeout(300)
    s.key('Export plan to Git (dialog#design-export-git-dialog)', 'Enter on Export plan to Git…; Tab x6; Escape', 'design-export-git-dialog' in inside,
          all('design-export-git-dialog' in o for o in order), 'design-export-git' in s.active(page), 'tab order=%s' % order)
    page.locator('#design-apply').focus()
    page.keyboard.press('Enter')
    page.wait_for_selector('dialog#design-apply-dialog[open]', timeout=10000)
    page.wait_for_timeout(300)
    inside = s.active(page)
    if full:
        s.axe(page, 'dialog-design-apply-choose', '#design-apply-dialog')
        s.shot(page, 'D07-apply-choose')
    page.locator('#design-apply-review-run').focus()
    started = time.monotonic()
    page.keyboard.press('Enter')
    page.wait_for_timeout(1500)
    busy = page.evaluate('''() => { const b = document.getElementById('design-apply-review-run'); const d = document.getElementById('design-apply-dialog');
        return {buttonDisabled: b.disabled, buttonText: b.textContent.trim(), ariaBusy: d.getAttribute('aria-busy'), dialogText: d.innerText.slice(0, 200).includes('Reviewing') || d.innerText.includes('Checking')}; }''')
    s.shot(page, 'D08-apply-review-in-flight')
    page.wait_for_function('() => !document.getElementById("design-apply-review-step").hidden || (document.getElementById("design-apply-choose-error")?.textContent || "").length > 0', timeout=240000)
    elapsed = round(time.monotonic() - started, 1)
    s.check('apply', 'the Review request shows that it is working (disabled button, busy text or aria-busy)',
            busy['buttonDisabled'] or busy['ariaBusy'] == 'true' or busy['dialogText'], 'after 1.5 s: %s; review took %s s' % (busy, elapsed))
    after = s.active(page)
    scroll_top = page.evaluate('() => document.getElementById("design-apply-dialog").scrollTop')
    s.check('apply', 'the review step receives focus when it replaces the choose step', after != 'BODY', after)
    s.check('apply', 'the review step starts at its top (title visible)', scroll_top == 0, 'dialog scrollTop %s' % scroll_top)
    reasons = page.evaluate('() => [...document.querySelectorAll("#design-apply-review-body .caption, #design-apply-review-body p")].map(p => p.textContent.trim()).slice(0, 6)')
    s.record['notes'].append('apply review per-device reasons (first 6): %s' % reasons)
    page.check('#design-apply-ack')
    page.wait_for_timeout(200)
    run_disabled = page.locator('#design-apply-run').is_disabled()
    reason = (page.locator('#design-apply-run').get_attribute('title') or '') + s.text(page, '#design-apply-review-error')
    s.check('apply', 'a disabled Apply button says why', not run_disabled or bool(reason.strip()), 'disabled=%s title/error=%r' % (run_disabled, reason))
    s.check('apply', 'the review step has a Cancel/Close control besides Back and the title-bar x',
            page.locator('#design-apply-review-step [data-design-apply-close]').count() > 0, 'controls: Back, Apply')
    if full:
        page.evaluate('() => { document.getElementById("design-apply-dialog").scrollTop = 0; }')
        s.axe(page, 'dialog-design-apply-review', '#design-apply-dialog')
        s.shot(page, 'D09-apply-review')
    page.keyboard.press('Escape')
    page.wait_for_timeout(300)
    s.key('Apply to devices (dialog#design-apply-dialog)', 'Enter on Apply to devices…; Enter on Review; Escape', 'design-apply-dialog' in inside,
          True, 'design-apply' in s.active(page), 'review took %s s; focus after review=%s' % (elapsed, after))
    return ospf, bgp


def lab_switch_repro(s, page, base, ospf, bgp):
    """A field of lab A's guided form keeps focus across a URL change to lab B (Back button): what does B show and save?"""
    def saved(lab):
        intent = get_json(base + '/api/labs/' + lab + '/design').get('intent') or {}
        return {'modules': intent.get('modules'), 'bgp': intent.get('bgp'), 'vrfs': sorted((intent.get('vrfs') or {}).keys()),
                'ospf': intent.get('ospf'), 'lan_prefix': ((intent.get('addressing') or {}).get('lan') or {}).get('prefix')}
    open_design(page, base, ospf)
    unfocus(page)
    box = page.locator('input[name="design-module"][value="bgp"]')
    if not box.is_checked():
        box.check()
    page.fill('#design-bgp-as', '65123')
    page.locator('#design-bgp-as').dispatch_event('change')
    unfocus(page)
    page.click('#design-save')
    wait_not(page, 'Unsaved', 20000)
    page.goto(base + '/#lab=' + bgp + '&view=design')
    page.wait_for_timeout(3000)
    before = saved(bgp)
    page.goto(base + '/#lab=' + ospf + '&view=design')
    page.wait_for_timeout(3000)
    page.locator('#design-pool-lan-prefix').click()        # the student is in a field of lab A's form
    page.go_back()                                          # browser Back to lab B
    page.wait_for_timeout(3500)
    shown = {'title': s.text(page, '#title'), 'device_rows': page.locator('[data-design-role]').count(),
             'bgp_ticked': page.locator('input[name="design-module"][value="bgp"]').is_checked(),
             'bgp_as': page.locator('#design-bgp-as').input_value(), 'state': s.text(page, '#design-state')}
    s.shot(page, 'D10-after-back-lab-b-header-lab-a-form', full=True)
    page.fill('#design-pool-lan-prefix', '25')
    page.locator('#design-pool-lan-prefix').dispatch_event('change')
    unfocus(page)
    page.click('#design-save')
    page.wait_for_timeout(2500)
    after = saved(bgp)
    contaminated = after.get('bgp') == {'as': 65123} and before.get('bgp') != {'as': 65123}
    s.check('design', 'after Back with a field focused, lab B shows lab B\'s form and Save writes only B\'s settings', not contaminated,
            'B before=%s; shown=%s; B after Save=%s' % (before, shown, after))
    s.record['lab_switch_repro'] = {'lab_a': ospf, 'lab_b': bgp, 'b_before': before, 'shown_under_b': shown, 'b_after_save': after, 'contaminated': contaminated}


def ensure_plan(page):
    if page.locator('#design-apply').is_disabled() or 'older' in (page.locator('#design-state').text_content() or ''):
        generate(page)


def viewport_matrix(s, browser, base, ospf, bgp):
    for label, width, height, scale in VIEWPORTS:
        ctx = browser.new_context(viewport={'width': width, 'height': height}, device_scale_factor=scale, bypass_csp=True)
        page = ctx.new_page()
        try:
            open_design(page, base, ospf)
            page.wait_for_timeout(500)
            row = {'viewport': label, 'screens': {}}
            row['screens']['design'] = page.evaluate(OVERFLOW_JS, '#design-view')
            page.goto(base + '/#lab=' + ospf + '&view=topology')
            page.wait_for_timeout(1200)
            row['screens']['topology (baseline shell)'] = page.evaluate(OVERFLOW_JS, 'main')
            open_design(page, base, ospf)
            s.shot(page, 'V-%s-design-top' % label)
            page.locator('#design-plan').scroll_into_view_if_needed()
            s.shot(page, 'V-%s-design-plan' % label)
            page.locator('#design-more-button').click()
            page.wait_for_timeout(200)
            row['screens']['more-menu'] = page.evaluate(OVERFLOW_JS, '#design-more-menu')
            s.shot(page, 'V-%s-more-menu' % label)
            page.keyboard.press('Escape')
            open_design(page, base, bgp)
            ensure_plan(page)
            page.locator('#design-apply').click()
            page.wait_for_selector('dialog#design-apply-dialog[open]', timeout=10000)
            page.wait_for_timeout(300)
            row['screens']['apply-dialog'] = page.evaluate('''() => { const d = document.getElementById('design-apply-dialog'); const r = d.getBoundingClientRect();
                const b = document.getElementById('design-apply-review-run').getBoundingClientRect();
                return {fitsWidth: r.left >= -1 && r.right <= document.documentElement.clientWidth + 1, innerScroll: d.scrollHeight > d.clientHeight,
                        reviewButtonVisible: b.top >= r.top && b.bottom <= r.bottom, width: Math.round(r.width)}; }''')
            s.shot(page, 'V-%s-apply-dialog' % label)
            page.keyboard.press('Escape')
            page.locator('#design-export-git').click()
            page.wait_for_selector('dialog#design-export-git-dialog[open]', timeout=10000)
            row['screens']['export-dialog'] = page.evaluate('''() => { const d = document.getElementById('design-export-git-dialog'); const r = d.getBoundingClientRect();
                return {fitsWidth: r.left >= -1 && r.right <= document.documentElement.clientWidth + 1, innerScroll: d.scrollHeight > d.clientHeight, width: Math.round(r.width)}; }''')
            s.shot(page, 'V-%s-export-dialog' % label)
            page.keyboard.press('Escape')
            s.record['viewports'].append(row)
            d = row['screens']['design']
            print('  vp    %s: design pageOverflow=%s sw=%s clipped=%s' % (label, d['pageOverflow'], d['scrollWidth'], d['clippedCount']), flush=True)
        except Exception as error:
            s.record['viewports'].append({'viewport': label, 'error': str(error)[:300]})
            print('  vp    %s: ERROR %s' % (label, str(error)[:200]), flush=True)
        finally:
            ctx.close()


def theme_checks(s, browser, base, ospf):
    for name, media in (('forced-colors', {'forced_colors': 'active'}), ('dark-preference', {'color_scheme': 'dark'})):
        ctx = browser.new_context(viewport={'width': 1366, 'height': 768}, bypass_csp=True)
        page = ctx.new_page()
        try:
            page.emulate_media(**media)
            open_design(page, base, ospf)
            s.shot(page, 'T-%s-design' % name)
            bg = page.evaluate('() => getComputedStyle(document.body).backgroundColor')
            s.record['notes'].append('%s: body background %s' % (name, bg))
        except Exception as error:
            s.record['notes'].append('%s failed: %s' % (name, error))
        finally:
            ctx.close()


def guard_factory(log):
    def guard(route, request):
        url = request.url.split('?')[0]
        if request.method in ('GET', 'HEAD') or (request.method == 'POST' and url.endswith('/api/operations/preview')):
            log.append(['pass', request.method, url])
            return route.continue_()
        log.append(['BLOCKED', request.method, url])
        return route.abort()
    return guard


def live_restart(s, browser, live, lab_name, device, full):
    log = []
    ctx = browser.new_context(viewport={'width': 1366, 'height': 768}, bypass_csp=True)
    ctx.route('**/*', guard_factory(log))
    page = ctx.new_page()
    page.on('console', lambda m: s.record['console_errors'].append('live: ' + m.text[:200]) if m.type == 'error' else None)
    try:
        state = get_json(live + '/api/state')
        s.record['live_version'] = state.get('version')
        lab = next(l for l in state['labs'] if l['name'] == lab_name)
        node = next(n for n in lab['nodes'] if n['name'].endswith('-' + device))['name']
        page.goto(live + '/#lab=' + lab['id'] + '&view=topology')
        page.wait_for_selector('#topology-map [data-map-node="%s"]' % node, timeout=30000)
        page.wait_for_timeout(1500)
        target = page.locator('#topology-map [data-map-node="%s"]' % node)
        # Mouse path: right click, the item, the review, Cancel.
        target.click(button='right')
        page.wait_for_selector('#node-context-menu:not([hidden])', timeout=5000)
        item = page.locator('#node-context-menu button[data-restart]')
        s.record['live_menu_item'] = {'text': item.text_content().strip(), 'disabled': item.is_disabled(), 'title': item.get_attribute('title'),
                                      'class': item.get_attribute('class'), 'color': item.evaluate('e => getComputedStyle(e).color')}
        if full:
            s.axe(page, 'live-map-menu', '#node-context-menu')
            s.shot(page, 'L01-map-menu')
        item.click()
        page.wait_for_selector('dialog#operation-review[open]', timeout=30000)
        page.wait_for_timeout(400)
        review = page.locator('dialog#operation-review')
        s.record['live_review_text'] = review.inner_text()
        named = review.evaluate('d => !!(d.getAttribute("aria-labelledby") || d.getAttribute("aria-label"))')
        s.check('restart', 'the review dialog has an accessible name', named, 'no aria-labelledby/aria-label on dialog#operation-review')
        if full:
            s.axe(page, 'live-restart-review', '#operation-review')
            s.shot(page, 'L02-review')
        assert 'op-confirm' not in s.active(page)
        page.locator('#op-cancel').click()
        page.wait_for_timeout(400)
        s.key('Restart device review from the map (mouse)', 'right click; click item; click Cancel', True, True,
              node in s.active(page), 'focus after Cancel=%s' % s.active(page))
        # Keyboard path: focus the device, Shift+F10, ArrowDown to the item, Enter, Tab order, Escape.
        target.focus()
        page.keyboard.press('Shift+F10')
        page.wait_for_timeout(400)
        menu_open = page.locator('#node-context-menu:not([hidden])').count() == 1
        for _ in range(6):
            if 'Restart device' in s.active(page):
                break
            page.keyboard.press('ArrowDown')
            page.wait_for_timeout(80)
        on_item = s.active(page)
        assert 'Restart device' in on_item and 'op-confirm' not in on_item
        page.keyboard.press('Enter')
        page.wait_for_selector('dialog#operation-review[open]', timeout=30000)
        page.wait_for_timeout(400)
        inside = s.active(page)
        order = []
        for _ in range(6):
            page.keyboard.press('Tab')
            page.wait_for_timeout(60)
            order.append(s.active(page))
        page.keyboard.press('Escape')
        page.wait_for_timeout(400)
        s.key('Restart device review from the map (keyboard)', 'focus device; Shift+F10; ArrowDown to item; Enter; Tab x6; Escape',
              menu_open, 'operation-review' in inside, node in s.active(page), 'focus in=%s; tab order=%s; after Escape=%s' % (inside, order, s.active(page)))
        target.focus()
        page.keyboard.press('ContextMenu')
        page.wait_for_timeout(300)
        s.check('restart', 'the ContextMenu key opens the device menu', page.locator('#node-context-menu:not([hidden])').count() == 1)
        page.keyboard.press('Escape')
        # Devices tab -> Details -> panel -> Restart device -> review -> Cancel.
        page.click('#tab-devices')
        page.wait_for_timeout(1200)
        details = page.locator('button[data-details="%s"][aria-label]:visible' % node).first
        details_name = details.get_attribute('aria-label')
        details.focus()
        page.keyboard.press('Enter')
        page.wait_for_selector('dialog#details-dialog[open]', timeout=10000)
        page.wait_for_timeout(500)
        if full:
            s.axe(page, 'live-device-panel', '#details-dialog')
            s.shot(page, 'L03-device-panel')
        for _ in range(12):
            if 'Restart device' in s.active(page):
                break
            page.keyboard.press('Tab')
            page.wait_for_timeout(60)
        on_item = s.active(page)
        assert 'Restart device' in on_item
        page.keyboard.press('Enter')
        page.wait_for_selector('dialog#operation-review[open]', timeout=30000)
        page.wait_for_timeout(400)
        panel_kept = page.locator('dialog#details-dialog[open]').count() == 1
        tab_cancel = 0
        while 'op-cancel' not in s.active(page) and tab_cancel < 6:
            page.keyboard.press('Tab')
            tab_cancel += 1
        assert 'op-cancel' in s.active(page)
        page.keyboard.press('Enter')
        page.wait_for_timeout(400)
        s.key('Restart device review from the device panel (keyboard)', 'Details (Enter); Tab to Restart device…; Enter; Tab to Cancel; Enter',
              True, True, 'data-restart' in page.evaluate('() => document.activeElement.outerHTML.slice(0, 60)'),
              'panel still open under the review=%s; focus after Cancel=%s; panel open after Cancel=%s; Details button name=%r' % (
                  panel_kept, s.active(page), page.locator('dialog#details-dialog[open]').count() == 1, details_name))
        # The review at phone width and 200 % zoom.
        for label, width, height, scale in (('390x844', 390, 844, 1), ('zoom200-1366x768', 683, 384, 2)):
            vctx = browser.new_context(viewport={'width': width, 'height': height}, device_scale_factor=scale, bypass_csp=True)
            vctx.route('**/*', guard_factory(log))
            vpage = vctx.new_page()
            try:
                vpage.goto(live + '/#lab=' + lab['id'] + '&view=topology')
                vpage.wait_for_selector('#topology-map [data-map-node="%s"]' % node, timeout=30000)
                vpage.wait_for_timeout(1200)
                vpage.locator('#topology-map [data-map-node="%s"]' % node).focus()
                vpage.keyboard.press('Shift+F10')
                vpage.wait_for_timeout(400)
                s.shot(vpage, 'L04-%s-map-menu' % label)
                menu_fit = vpage.evaluate('() => { const m = document.getElementById("node-context-menu").getBoundingClientRect(); return {left: Math.round(m.left), right: Math.round(m.right), top: Math.round(m.top), bottom: Math.round(m.bottom), vw: innerWidth, vh: innerHeight}; }')
                vpage.locator('#node-context-menu button[data-restart]').click()
                vpage.wait_for_selector('dialog#operation-review[open]', timeout=30000)
                vpage.wait_for_timeout(400)
                fit = vpage.evaluate('''() => { const d = document.getElementById('operation-review'); const r = d.getBoundingClientRect(); const c = document.getElementById('op-cancel').getBoundingClientRect();
                    return {fitsWidth: r.left >= -1 && r.right <= document.documentElement.clientWidth + 1, innerScroll: d.scrollHeight > d.clientHeight, cancelInsideDialog: c.right <= r.right + 1 && c.left >= r.left - 1}; }''')
                s.shot(vpage, 'L05-%s-review' % label)
                vpage.locator('#op-cancel').click()
                s.record['viewports'].append({'viewport': label, 'screens': {'live-map-menu': menu_fit, 'live-restart-review': fit}})
            finally:
                vctx.close()
    except Exception as error:
        s.record['notes'].append('live restart part stopped: %s' % str(error)[:300])
        print('  LIVE  stopped: %s' % str(error)[:200], flush=True)
    finally:
        ctx.close()
    s.record['live_requests'] = {'passed': sum(1 for l in log if l[0] == 'pass'), 'blocked': [l for l in log if l[0] == 'BLOCKED'],
                                 'previews': sum(1 for l in log if l[2].endswith('/api/operations/preview')),
                                 'confirm_attempted': any(l[2].endswith('/operations/confirm') for l in log)}
    s.check('restart', 'no mutating request reached the deployed manager', not s.record['live_requests']['blocked'] and not s.record['live_requests']['confirm_attempted'],
            s.record['live_requests']['blocked'])


def start_fixture(port, data_root):
    data = Path(tempfile.mkdtemp(prefix='usability-fixture-', dir=data_root))
    proc = subprocess.Popen([sys.executable, str(FIXTURE), '--port', str(port), '--data', str(data)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    wait_http('http://127.0.0.1:%d/api/state' % port)
    return proc, data


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--axe', required=True, help='path to axe.min.js')
    parser.add_argument('--fixture-url', default=None, help='use an already running fixture manager (one browser only)')
    parser.add_argument('--start-fixture', action='store_true', help='start a fresh fixture manager per browser')
    parser.add_argument('--port', type=int, default=8103)
    parser.add_argument('--data-root', default=None, help='parent directory for the fresh fixture data directories')
    parser.add_argument('--live-url', default='http://127.0.0.1:8081')
    parser.add_argument('--live-lab', default='restore-square')
    parser.add_argument('--live-device', default='host1')
    parser.add_argument('--no-live', action='store_true')
    parser.add_argument('--browsers', default='chromium,firefox,webkit')
    parser.add_argument('--full-browser', default='chromium', help='the browser that also runs axe, the viewport matrix and the theme checks')
    parser.add_argument('--out', default=str(ROOT / 'docs' / 'netlab-ui-qa' / 'evidence' / 'usability'))
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    summary = {'started': now(), 'browsers': {}}
    with sync_playwright() as pw:
        for name in [b.strip() for b in args.browsers.split(',') if b.strip()]:
            print('== ' + name, flush=True)
            try:
                browser = getattr(pw, name).launch()
            except Exception as error:
                summary['browsers'][name] = {'launched': False, 'error': str(error).splitlines()[0:6]}
                print('  could not launch: %s' % str(error).splitlines()[0:3], flush=True)
                continue
            full = name == args.full_browser
            s = Scan(name, out, Path(args.axe))
            s.record['version'] = browser.version
            proc = data = None
            try:
                if args.start_fixture:
                    proc, data = start_fixture(args.port, args.data_root)
                    base = 'http://127.0.0.1:%d' % args.port
                else:
                    base = args.fixture_url or 'http://127.0.0.1:%d' % args.port
                s.record['fixture'] = {'url': base, 'data': str(data) if data else 'external', 'version': get_json(base + '/api/state').get('version')}
                ctx = browser.new_context(viewport={'width': 1366, 'height': 768}, bypass_csp=True)
                page = ctx.new_page()
                page.on('console', lambda m: s.record['console_errors'].append(m.text[:200]) if m.type == 'error' else None)
                page.on('pageerror', lambda e: s.record['console_errors'].append('pageerror: ' + str(e)[:200]))
                try:
                    ospf, bgp = design_journey(s, page, base, full)
                    lab_switch_repro(s, page, base, ospf, bgp)
                except Exception as error:
                    s.record['notes'].append('design journey stopped: %s' % str(error)[:400])
                    print('  DESIGN stopped: %s' % str(error)[:300], flush=True)
                    s.shot(page, 'D99-stopped')
                    ospf, bgp = lab_id(base, 'ospf-basics'), lab_id(base, 'BGP_TheoryToPractice')
                ctx.close()
                if full:
                    viewport_matrix(s, browser, base, ospf, bgp)
                    theme_checks(s, browser, base, ospf)
                if not args.no_live:
                    live_restart(s, browser, args.live_url, args.live_lab, args.live_device, full)
            finally:
                if proc:
                    proc.terminate()
                    try:
                        proc.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                browser.close()
            s.record['finished'] = now()
            (out / ('scan-%s.json' % name)).write_text(json.dumps(s.record, indent=1))
            summary['browsers'][name] = {'launched': True, 'version': s.record['version'], 'findings': sum(1 for c in s.record['checks'] if not c['ok']),
                                         'checks': len(s.record['checks'])}
    summary['finished'] = now()
    (out / 'scan-summary.json').write_text(json.dumps(summary, indent=1))
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main())
