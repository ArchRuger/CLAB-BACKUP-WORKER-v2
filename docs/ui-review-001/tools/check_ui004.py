#!/usr/bin/env python3
"""UI-004 browser check: every option of the Save progress menu is explained on hover and on focus.

"Inside the viewport" means: never beyond the left or right edge, and either above the bottom edge or
reachable by scrolling the page (a 1280x720 laptop at 200 % zoom is 360 CSS pixels high).

Runs against the fixture manager; read-only.

    CLAB_BASE=http://127.0.0.1:8090 clab-backup-ui/.venv/bin/python docs/ui-review-001/tools/check_ui004.py
"""
import os
import sys
import time

from playwright.sync_api import sync_playwright

BASE = os.environ.get('CLAB_BASE', 'http://127.0.0.1:8090')
OUT = os.environ.get('CLAB_SHOTS', '')
LAB = os.environ.get('CLAB_LAB', 'BGP_TheoryToPractice')
ACTIONS = ['checkpoint', 'local', 'history', 'settings']
failed = []

GEOMETRY = '''(action) => {
  const r = e => { const b = e.getBoundingClientRect(); return {l: b.left, t: b.top, r: b.right, b: b.bottom}; };
  const help = document.getElementById('git-save-help'), text = document.getElementById('git-save-help-' + action);
  const buttons = [...document.querySelectorAll('#git-save-menu [data-git-action]')].map(r), h = r(help), t = r(text);
  const overlaps = (a, b) => a.l < b.r - 1 && b.l < a.r - 1 && a.t < b.b - 1 && b.t < a.b - 1;
  return {open: document.getElementById('git-save-menu').open, shown: !text.hidden && text.offsetParent !== null, words: text.innerText,
    others: [...help.querySelectorAll('div[id]')].filter(d => !d.hidden).length, defaultHidden: document.getElementById('git-save-help-default').hidden,
    inside: h.l >= 0 && h.t >= 0 && h.r <= innerWidth + 1 && (h.b <= innerHeight + 1 || h.b + scrollY <= document.documentElement.scrollHeight + 1), clipped: text.scrollWidth > text.clientWidth + 1 || t.r > h.r + 1 || t.b > h.b + 1,
    covers: buttons.some(b => overlaps(b, h)) || (o => h.l < o.l - 1 || h.r > o.r + 1 || h.b > o.b + 1)(r(document.querySelector('.git-save-options'))), help: h, vw: innerWidth, vh: innerHeight};
}'''


def check(name, ok, detail=''):
    print(('ok   ' if ok else 'FAIL ') + name + (f' :: {detail}' if not ok else ''), flush=True)
    if not ok:
        failed.append(name)


with sync_playwright() as pw:
    browser = pw.chromium.launch()
    for width, height, scale in [(1366, 768, 1), (1280, 720, 1.5), (1280, 720, 2), (1280, 720, 2.5), (950, 700, 1)]:
        tag = f'{width}x{height}@{scale}'
        ctx = browser.new_context(viewport={'width': int(width / scale), 'height': int(height / scale)})
        page = ctx.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('console', lambda m: errors.append(m.text) if m.type == 'error' and 'Failed to load resource' not in m.text else None)
        page.goto(BASE + '/')
        page.wait_for_selector('article.lab-card')
        page.click(f'article.lab-card:has(h3:text-is("{LAB}")) [data-lab]')
        page.wait_for_selector('#git-save-menu:not([hidden])')
        page.click('#git-save-menu > summary')
        page.wait_for_selector('#git-save-menu[open]')
        check(f'{tag}: the default line shows before any option is active', page.evaluate('() => !document.getElementById("git-save-help-default").hidden'))
        for action in ACTIONS:
            page.hover(f'#git-save-menu [data-git-action="{action}"]')
            g = page.evaluate(GEOMETRY, action)
            check(f'{tag}: hover explains {action}', g['shown'] and g['others'] == 1 and g['defaultHidden'] and len(g['words']) > 60, g)
            check(f'{tag}: {action} explanation is inside the viewport, unclipped, on the menu surface and covers no option', g['inside'] and not g['clipped'] and not g['covers'], g)
            if OUT and action in ('checkpoint', 'local'):
                page.screenshot(path=os.path.join(OUT, f'ui004-{tag}-{action}.png'))
        # Reading the explanation: the pointer moves onto the pane, the menu and the text stay
        page.hover('#git-save-menu [data-git-action="local"]')
        page.hover('#git-save-help-local')
        time.sleep(4.5)  # one background poll
        g = page.evaluate(GEOMETRY, 'local')
        check(f'{tag}: the menu and the text stay while the explanation is read, across a poll', g['open'] and g['shown'], g)
        page.keyboard.press('Escape')
        # Keyboard only. The pointer is parked first: a page that scrolls under a resting pointer fires
        # mouseover, and the latest of pointer and focus wins by design.
        page.mouse.move(1, 1)
        page.focus('#git-save-menu > summary')
        page.keyboard.press('Enter')
        page.wait_for_selector('#git-save-menu[open]')
        seen = []
        for action in ACTIONS:
            page.keyboard.press('Tab')
            focused = page.evaluate('() => document.activeElement?.dataset?.gitAction || ""')
            g = page.evaluate(GEOMETRY, focused or action)
            seen.append((focused, g['shown'], g['inside'], g['covers']))
        check(f'{tag}: Tab reaches every option and each focus shows its explanation', [s[0] for s in seen] == ACTIONS and all(s[1] and s[2] and not s[3] for s in seen), seen)
        described = page.evaluate('() => [...document.querySelectorAll("#git-save-menu [data-git-action]")].every(b => { const d = document.getElementById(b.getAttribute("aria-describedby")); return d && d.textContent.length > 60; })')
        check(f'{tag}: every option is described for assistive technology', described)
        page.keyboard.press('Escape')
        check(f'{tag}: Escape closes the menu', page.evaluate('() => !document.getElementById("git-save-menu").open'))
        check(f'{tag}: no console or page errors', not errors, errors)
        ctx.close()

    # The actions still do what they did
    ctx = browser.new_context(viewport={'width': 1366, 'height': 768})
    page = ctx.new_page()
    page.goto(BASE + '/')
    page.wait_for_selector('article.lab-card')
    page.click(f'article.lab-card:has(h3:text-is("{LAB}")) [data-lab]')
    page.wait_for_selector('#git-save-menu:not([hidden])')
    for action, selector in [('checkpoint', '#git-save-options[open] #git-checkpoint-name'), ('local', '#git-save-options[open] #git-save-note'), ('history', '#git-history-dialog[open]')]:
        page.click('#git-save-menu > summary')
        page.click(f'#git-save-menu [data-git-action="{action}"]')
        page.wait_for_selector(selector, timeout=15000)
        check(f'{action} still opens its window', True)
        page.keyboard.press('Escape')
    page.click('#git-save-menu > summary')
    page.click('#git-save-menu [data-git-action="settings"]')
    page.wait_for_selector('#progress-view:not([hidden])')
    check('settings still opens Progress', True)
    browser.close()
sys.exit(1 if failed else 0)
