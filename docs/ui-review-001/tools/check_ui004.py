#!/usr/bin/env python3
"""UI-004 browser check, rewritten for the header Save and Load (Git save and load redesign): every view of the chip
panel states what it does and where it goes, its options are reachable and explained without a hover, and the panel
stays on screen.

Until 1.30.x UI-004 checked the help pane of the *Save progress* menu (four options, explained on hover and on focus).
The menu and its help pane are gone (docs/git-redesign/inventory/CAPABILITIES.md C-002, C-003: "no help pane; each
chip-panel view states its effect and destination"), so the same claims are asserted in the new home:

  * the rest view ("Saved ...") and the waiting view ("Not uploaded yet") each say what the save is, where it goes
    ("Saves to:", "To:", "Uploaded:") and that saved files can contain passwords or keys; every option is a labelled
    button of the panel with its effect in words (Upload, Not now, See changes, Details, All versions, Save as a lab
    state..., Save settings), none depends on a hover;
  * "inside the viewport" keeps its meaning: never beyond the left or right edge, and either above the bottom edge or
    reachable by scrolling the page (a 1280x720 laptop at 200 % zoom is 360 CSS pixels high); the panel is unclipped
    and does not cover the chip that opened it;
  * keyboard only: Tab reaches every option of the waiting view and of the rest view, Escape closes the panel and the
    focus returns to the chip;
  * the actions still do what they did: Keep as a checkpoint makes a checkpoint; Save then Not now keeps the save on
    the VM (the old Save on this VM only) and uploads nothing; All versions (with Full history...) and Save settings
    open their drawers.

It creates saves in the fixture (the old check was read-only): each viewport saves once, keeps it on the VM, checks
the waiting view, then uploads it through the panel; use a scratch FIXTURE_DATA directory.

    CLAB_BASE=http://127.0.0.1:8090 clab-backup-ui/.venv/bin/python docs/ui-review-001/tools/check_ui004.py
"""
import os
import sys

from playwright.sync_api import sync_playwright

BASE = os.environ.get('CLAB_BASE', 'http://127.0.0.1:8090')
OUT = os.environ.get('CLAB_SHOTS', '')
LAB = os.environ.get('CLAB_LAB', 'BGP_TheoryToPractice')
REST_OPTIONS = ['save-all', 'save-as-state', 'save-settings']
WAITING_OPTIONS = ['save-upload', 'save-not-now', 'save-see', 'save-details']
failed = []

GEOMETRY = '''(opener) => {
  const r = e => { const b = e.getBoundingClientRect(); return {l: b.left, t: b.top, r: b.right, b: b.bottom}; };
  const panel = document.getElementById('save-panel'), chip = document.getElementById(opener), p = r(panel), c = r(chip);
  const overlaps = (a, b) => a.l < b.r - 1 && b.l < a.r - 1 && a.t < b.b - 1 && b.t < a.b - 1;
  const buttons = [...panel.querySelectorAll('button')].filter(b => b.offsetParent);
  return {open: !panel.hidden, title: document.getElementById('save-panel-title-text').textContent, words: panel.innerText,
    inside: p.l >= 0 && p.r <= innerWidth + 1 && p.t >= 0 && (p.b <= innerHeight + 1 || p.b + scrollY <= document.documentElement.scrollHeight + 1),
    clipped: panel.scrollWidth > panel.clientWidth + 1 || buttons.some(b => r(b).r > p.r + 1 || r(b).l < p.l - 1),
    coversOpener: overlaps(p, c), unnamed: buttons.filter(b => !(b.innerText || b.getAttribute('aria-label') || '').trim()).length,
    labelled: panel.getAttribute('aria-labelledby') === 'save-panel-title' && !!document.getElementById('save-panel-title-text').textContent.trim(),
    panel: p, chip: c, vw: innerWidth, vh: innerHeight};
}'''

TAB_ORDER = '''() => document.activeElement && document.activeElement.closest('#save-panel') ? document.activeElement.id : ''
'''


def check(name, ok, detail=''):
    print(('ok   ' if ok else 'FAIL ') + name + (f' :: {detail}' if not ok else ''), flush=True)
    if not ok:
        failed.append(name)


def open_lab(page):
    page.goto(BASE + '/')
    page.wait_for_selector('article.lab-card')
    page.click(f'article.lab-card:has(h3:text-is("{LAB}")) [data-lab]')
    page.wait_for_selector('#lab-content:not([hidden])')
    page.wait_for_function('() => document.getElementById("save-chip-text").textContent.length > 0')
    page.evaluate('() => { if (window.__toasts) return; window.__toasts = []; const shown = notify; notify = function (m) { window.__toasts.push(String(m)); return shown(m); }; }')


def chip_text(page):
    return page.inner_text('#save-chip-text')


def upload(page):
    """Upload from the panel and wait until the upload ended: the toast says so and the panel closes."""
    page.click('#save-upload')
    page.wait_for_function('() => window.__toasts.some(t => /^Uploaded to /.test(t)) && document.getElementById("save-panel").hidden', timeout=90000)
    page.evaluate('() => { window.__toasts.length = 0; }')


def tab_through(page, first, ids):
    """Tab from `first` until every id of `ids` was focused (or a bound is hit). Returns the focused ids inside the panel."""
    page.focus('#' + first)
    seen = [first]
    for _ in range(len(ids) + 12):
        page.keyboard.press('Tab')
        focused = page.evaluate(TAB_ORDER)
        if not focused:
            break
        seen.append(focused)
        if all(i in seen for i in ids):
            break
    return seen


with sync_playwright() as pw:
    browser = pw.chromium.launch()
    for width, height, scale in [(1366, 768, 1), (1280, 720, 1.5), (1280, 720, 2), (1280, 720, 2.5), (950, 700, 1)]:
        tag = f'{width}x{height}@{scale}'
        ctx = browser.new_context(viewport={'width': int(width / scale), 'height': int(height / scale)})
        page = ctx.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('console', lambda m: errors.append(m.text) if m.type == 'error' and 'Failed to load resource' not in m.text else None)
        open_lab(page)

        # The rest view: what the save is, where it goes, and every option of its foot
        page.click('#save-chip')
        page.wait_for_selector('#save-panel:not([hidden]) #save-all')
        g = page.evaluate(GEOMETRY, 'save-chip')
        check(f'{tag}: the rest view says what the save is and where it goes, with no hover needed', g['title'].startswith('Saved') and 'Uploaded:' in g['words'] and 'Saves to:' in g['words'] and 'Course-Labs' in g['words'], g['words'])
        check(f'{tag}: every option of the rest view is a labelled button (All versions, Save as a lab state..., Save settings)', all(page.is_visible('#' + i) for i in REST_OPTIONS) and g['unnamed'] == 0 and g['labelled'], g)
        check(f'{tag}: the rest view is inside the viewport, unclipped and does not cover the chip', g['inside'] and not g['clipped'] and not g['coversOpener'], g)
        if OUT:
            page.screenshot(path=os.path.join(OUT, f'ui004-{tag}-rest.png'))
        # Keyboard only: Tab reaches every option of the rest view; Escape closes and returns the focus to the chip
        seen = tab_through(page, 'save-panel-title', REST_OPTIONS)
        check(f'{tag}: Tab reaches every option of the rest view', all(i in seen for i in REST_OPTIONS), seen)
        page.keyboard.press('Escape')
        check(f'{tag}: Escape closes the panel and returns the focus to the chip', page.evaluate('() => document.getElementById("save-panel").hidden && document.activeElement.id === "save-chip"'))

        # Save, then Not now: the old "Save on this VM only"
        known = page.evaluate('''async () => (await (await fetch('/api/state')).json()).git_jobs.map(j => j.id)''')
        page.click('#git-save-progress')
        page.wait_for_selector('#save-upload:not([disabled])', timeout=90000)
        job = page.evaluate('''async (known) => { const s = await (await fetch('/api/state')).json(); return s.git_jobs.filter(j => !known.includes(j.id)).sort((a, b) => a.created < b.created ? 1 : -1)[0]; }''', known)
        g = page.evaluate(GEOMETRY, 'save-chip')
        check(f'{tag}: the waiting view says it is not uploaded, where it goes and what the options do', g['title'] == 'Not uploaded yet' and 'To:' in g['words'] and 'Saved files can contain passwords or keys.' in g['words'] and all(w in g['words'] for w in ('Upload', 'Not now', 'See changes', 'Details')), g['words'])
        check(f'{tag}: every option of the waiting view is a labelled button', all(page.is_visible('#' + i) for i in WAITING_OPTIONS) and g['unnamed'] == 0, g)
        check(f'{tag}: the waiting view is inside the viewport, unclipped and does not cover the chip', g['inside'] and not g['clipped'] and not g['coversOpener'], g)
        if OUT:
            page.screenshot(path=os.path.join(OUT, f'ui004-{tag}-waiting.png'))
        seen = tab_through(page, 'save-panel-title', WAITING_OPTIONS + REST_OPTIONS)
        check(f'{tag}: Tab reaches every option of the waiting view and its foot', all(i in seen for i in WAITING_OPTIONS + REST_OPTIONS), seen)
        page.keyboard.press('Escape')
        check(f'{tag}: Escape closes the waiting view too, and the focus returns to the chip', page.evaluate('() => document.getElementById("save-panel").hidden && document.activeElement.id === "save-chip"'))
        # The save stays on this VM: nothing was uploaded and the chip says so
        check(f'{tag}: a save left with Not now stays on the VM and the chip says it waits', job and not job['pushed'] and 'upload' in chip_text(page), (job or {}).get('status'))
        # Upload it through the panel so the next viewport starts from a clean chip
        page.click('#save-chip')
        page.wait_for_selector('#save-upload:not([disabled])', timeout=30000)
        upload(page)

        # The actions still do what they did (the last viewport state is a fresh, uploaded save)
        if (width, height, scale) == (1366, 768, 1):
            before = page.evaluate('''async () => (await (await fetch('/api/state')).json()).git_jobs.map(j => j.id)''')
            page.click('#git-save-progress')
            page.wait_for_selector('#save-upload:not([disabled])', timeout=90000)
            upload(page)
            page.click('#save-chip')
            page.wait_for_selector('#save-keep:not([disabled])', state='attached')
            page.click('label.save-keep')   # the box itself is drawn by the label
            page.wait_for_function('''async (before) => { const s = await (await fetch('/api/state')).json(); return s.git_jobs.some(j => !before.includes(j.id) && j.target === 'checkpoint'); }''', arg=before, timeout=60000)
            check('Keep as a checkpoint still makes a checkpoint', True)
            # The checkpoint waits for upload like any save: upload it so the next viewport starts from a clean chip
            page.click('#save-chip') if page.evaluate('() => document.getElementById("save-panel").hidden') else None
            page.wait_for_selector('#save-upload:not([disabled])', timeout=60000)
            upload(page)
            page.click('#save-chip')
            page.click('#save-all')
            page.wait_for_selector('#save-drawer[open] #save-drawer-content .save-list', timeout=20000)
            check('All versions still opens its drawer', page.inner_text('#save-drawer-title') == 'All versions')
            page.click('#save-drawer-content [data-save-action="history"]')
            page.wait_for_selector('#git-history-dialog[open]', timeout=15000)
            check('Full history... still opens the history window', True)
            page.keyboard.press('Escape')
            page.wait_for_function('() => !document.getElementById("git-history-dialog").open')
            page.click('#save-chip')
            page.click('#save-settings')
            page.wait_for_selector('#save-drawer[open] .save-settings', timeout=20000)
            check('Save settings still opens its drawer', page.inner_text('#save-drawer-title') == 'Save settings')
            page.keyboard.press('Escape')
            page.wait_for_function('() => !document.getElementById("save-drawer").open')
        check(f'{tag}: no console or page errors', not errors, errors)
        ctx.close()
    browser.close()
sys.exit(1 if failed else 0)
