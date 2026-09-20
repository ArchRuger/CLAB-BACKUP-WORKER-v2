#!/usr/bin/env python3
"""UI-002 (part 2) browser check: Recent labs is ordered by real deployments, and the tab stays put.

Runs against the fixture manager on fresh data (no lab has a recorded deployment at the start). It
redeploys two fixture labs through the reviewed operation; use a scratch FIXTURE_DATA directory.

    CLAB_BASE=http://127.0.0.1:8090 clab-backup-ui/.venv/bin/python docs/ui-review-001/tools/check_ui002b.py
"""
import os
import sys
import time

from playwright.sync_api import sync_playwright

BASE = os.environ.get('CLAB_BASE', 'http://127.0.0.1:8090')
OUT = os.environ.get('CLAB_SHOTS', '')
failed = []

NAMES = '() => [...document.querySelectorAll("#lab-cards article.lab-card h3")].map(h => h.textContent)'
TIMES = '() => Object.fromEntries([...document.querySelectorAll("#lab-cards article.lab-card")].map(a => [a.querySelector("h3").textContent, a.querySelector(".lab-card-times").textContent]))'
SELECTED = '() => document.querySelector("#home-tabs [aria-selected=true]").dataset.homeTab'


def check(name, ok, detail=''):
    print(('ok   ' if ok else 'FAIL ') + name + (f' :: {detail}' if not ok else ''), flush=True)
    if not ok:
        failed.append(name)


def shot(page, name):
    if OUT:
        page.screenshot(path=os.path.join(OUT, name + '.png'), full_page=True)


def redeploy(page, lab):
    previous = page.evaluate("async (lab) => (await (await fetch('/api/state')).json()).labs.find(l => l.name === lab).last_deployed", lab)
    page.click(f'article.lab-card:has(h3:text-is("{lab}")) [data-lab]')
    page.wait_for_selector('#lab-content:not([hidden])')
    page.click('#lab-actions-button')
    page.click('#lab-actions-menu [data-op-action="redeploy"]:not([data-op-variant])')
    page.wait_for_selector('#operation-review[open] #op-confirm', timeout=30000)
    page.click('#op-confirm')
    page.wait_for_function("async (lab) => { const s = await (await fetch('/api/state')).json(); return s.labs.find(l => l.name === lab).last_deployed !== previous && !s.operations.some(o => ['queued', 'running'].includes(o.status)); }".replace('previous', repr(previous or '')), arg=lab, timeout=90000)
    if page.evaluate('() => !!document.querySelector("dialog[open]")'):
        page.keyboard.press('Escape')
    page.click('#crumb-home')
    page.wait_for_selector('#home-labs:not([hidden])')
    # Home draws from the last poll; the card follows within one poll (4 s)
    page.wait_for_function('(lab) => [...document.querySelectorAll("#lab-cards article.lab-card")].some(a => a.querySelector("h3").textContent === lab && a.querySelector(".lab-card-times").textContent.startsWith("Deployed "))', arg=lab, timeout=15000)


with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_page(viewport={'width': 1366, 'height': 768})
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.on('response', lambda r: print('req', r.status, r.request.method, r.url.split('/api/')[-1], flush=True) if r.request.method != 'GET' else None)
    page.on('console', lambda m: errors.append(m.text) if m.type == 'error' and 'Failed to load resource' not in m.text else None)
    page.goto(BASE + '/')
    page.wait_for_selector('#home-labs:not([hidden])')
    start = page.evaluate(NAMES)
    check('Recent labs is the first tab and it is selected', page.evaluate(SELECTED) == 'recent' and page.inner_text('#home-tabs').split('\n')[0].strip() == 'Recent labs')
    check('without any recorded deployment the labs are listed by name and none claims a time', start == sorted(start, key=str.lower) and all(t.startswith('No deployment recorded by this manager') for t in page.evaluate(TIMES).values()), (start, page.evaluate(TIMES)))
    check('no "Continue where you left off" block stands above the list', 'Continue where you left off' not in page.inner_text('#home') and not page.query_selector('#home-continue'))
    shot(page, 'ui002b-no-deployments')

    redeploy(page, 'vlan-lab')
    names = page.evaluate(NAMES)
    check('a lab that was just deployed leads Recent labs', names[0] == 'vlan-lab' and page.evaluate(TIMES)['vlan-lab'].startswith('Deployed '), (names, page.evaluate(TIMES)))
    check('the labs without a deployment follow, by name', names[1:] == sorted(names[1:], key=str.lower), names)
    time.sleep(1.2)
    redeploy(page, 'BGP_TheoryToPractice')
    names = page.evaluate(NAMES)
    check('the newest deployment comes first', names[:2] == ['BGP_TheoryToPractice', 'vlan-lab'], names)
    shot(page, 'ui002b-recent')
    # Unrelated activity: open another lab, favourite one, wait for polls
    page.click('article.lab-card:has(h3:text-is("ospf-basics")) [data-lab]')
    page.wait_for_selector('#lab-content:not([hidden])')
    page.click('#crumb-home')
    page.wait_for_selector('#home-labs:not([hidden])')
    page.click('article.lab-card:has(h3:text-is("switching-basics")) [data-lab-favorite]')
    page.wait_for_function('() => document.querySelector("article.lab-card [data-lab-favorite][aria-pressed=true]")')
    time.sleep(9)
    check('opening a lab, a favourite and two polls do not reorder Recent labs', page.evaluate(NAMES) == names, page.evaluate(NAMES))
    check('the opened lab only gains its "Last opened" note', 'Last opened' in page.evaluate(TIMES)['ospf-basics'])

    # The tab: chosen by the student, kept across polls, a lab visit and a reload
    page.click('#home-tab-all')
    allnames = page.evaluate(NAMES)
    check('All labs keeps favourites first, then by name', allnames[0] == 'switching-basics' and allnames[1:] == sorted(allnames[1:], key=str.lower), allnames)
    shot(page, 'ui002b-all-labs')
    time.sleep(9)
    check('the tab survives background polls', page.evaluate(SELECTED) == 'all' and page.evaluate(NAMES) == allnames)
    page.click('article.lab-card:has(h3:text-is("vlan-lab")) [data-lab]')
    page.wait_for_selector('#lab-content:not([hidden])')
    page.click('#crumb-home')
    page.wait_for_selector('#home-labs:not([hidden])')
    check('and opening a lab and coming back', page.evaluate(SELECTED) == 'all')
    page.reload()
    page.wait_for_selector('#home-labs:not([hidden]), #lab-content:not([hidden])')
    if page.is_visible('#lab-content'):
        page.click('#crumb-home')
    check('and a reload in the same session', page.evaluate(SELECTED) == 'all')
    page.focus('#home-tab-all')
    page.keyboard.press('ArrowLeft')
    check('the arrow keys move between the tabs with the focus', page.evaluate(SELECTED) == 'recent' and page.evaluate('() => document.activeElement.id') == 'home-tab-recent')
    check('card actions still work from the list', page.is_visible('article.lab-card [data-lab-more]') and page.is_visible('article.lab-card [data-lab-favorite]'))
    box = page.evaluate('() => { const h = document.querySelector("article.lab-card h3"), c = h.closest("article").getBoundingClientRect(), t = h.closest(".lab-card-head").querySelector(".lab-card-tools").getBoundingClientRect(); return {lines: Math.round(h.getBoundingClientRect().height / parseFloat(getComputedStyle(h).lineHeight)), toolsRight: Math.round(c.right - t.right)}; }')
    check('a lab name gets the width of its card: one line, tools at the right edge', box['lines'] == 1 and box['toolsRight'] <= 24, box)
    check('no console or page errors', not errors, errors)
    browser.close()
sys.exit(1 if failed else 0)
