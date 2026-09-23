#!/usr/bin/env python3
"""UI-005 browser check: Lab actions ends with an expandable Advanced options group.

Runs against the fixture manager; read-only (every dialog it opens is closed again).

    CLAB_BASE=http://127.0.0.1:8090 clab-backup-ui/.venv/bin/python docs/ui-review-001/tools/check_ui005.py
"""
import os
import sys

from playwright.sync_api import sync_playwright

BASE = os.environ.get('CLAB_BASE', 'http://127.0.0.1:8090')
OUT = os.environ.get('CLAB_SHOTS', '')
LAB = os.environ.get('CLAB_LAB', 'BGP_TheoryToPractice')
EMPTY_MAP_LAB = os.environ.get('CLAB_EMPTY_LAB', 'ospf-basics')
MOVED = ['menu-import-map', 'menu-map-edit', 'menu-operation-history']
failed = []


def check(name, ok, detail=''):
    print(('ok   ' if ok else 'FAIL ') + name + (f' :: {detail}' if not ok else ''), flush=True)
    if not ok:
        failed.append(name)


def open_lab(page, name):
    page.goto(BASE + '/')
    page.wait_for_selector('article.lab-card')
    page.click(f'article.lab-card:has(h3:text-is("{name}")) [data-lab]')
    page.wait_for_selector('#lab-content:not([hidden])')


def open_group(page):
    page.click('#lab-actions-button')
    page.wait_for_selector('#lab-actions-menu:not([hidden])')
    page.click('#lab-actions-advanced-toggle')
    page.wait_for_selector('#lab-actions-advanced:not([hidden])')


def shot(page, name):
    if OUT:
        page.screenshot(path=os.path.join(OUT, name + '.png'))


with sync_playwright() as pw:
    browser = pw.chromium.launch()
    for width, height, scale in [(1366, 768, 1), (1280, 720, 1.5)]:
        tag = f'{width}x{height}@{scale}'
        # A device scale factor does not change layout; browser zoom does. Zoom 150 % on a 1280x720
        # laptop is a 853x480 CSS viewport.
        ctx = browser.new_context(viewport={'width': int(width / scale), 'height': int(height / scale)})
        page = ctx.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('console', lambda m: errors.append(m.text) if m.type == 'error' and 'Failed to load resource' not in m.text else None)
        open_lab(page, LAB)
        page.click('#lab-actions-button')
        page.wait_for_selector('#lab-actions-menu:not([hidden])')
        visible = page.evaluate('() => [...document.querySelectorAll("#lab-actions-menu [role=menuitem]")].filter(b => b.offsetParent).map(b => b.id || b.textContent.trim())')
        check(f'{tag}: the moved items are not in the collapsed menu', not any(i in visible for i in MOVED), visible)
        check(f'{tag}: Advanced options is the last entry', visible[-1] == 'lab-actions-advanced-toggle', visible)
        check(f'{tag}: Packet capture, Lab files and the lifecycle items stay in the main list', all(i in visible for i in ['lab-start', 'menu-capture', 'menu-lab-files', 'menu-destroy', 'menu-remove-lab']), visible)
        shot(page, f'ui005-{tag}-collapsed')
        page.click('#lab-actions-advanced-toggle')
        page.wait_for_selector('#lab-actions-advanced:not([hidden])')
        box = page.evaluate('''() => { const m = document.getElementById("lab-actions-menu").getBoundingClientRect(), l = document.getElementById("menu-operation-history").getBoundingClientRect();
          return {menuTop: m.top, menuBottom: m.bottom, menuRight: m.right, menuLeft: m.left, lastTop: l.top, lastBottom: l.bottom, vh: innerHeight, vw: innerWidth, open: !document.getElementById("lab-actions-menu").hidden}; }''')
        check(f'{tag}: the toggle keeps the menu open', box['open'])
        check(f'{tag}: the expanded menu stays inside the viewport', box['menuBottom'] <= box['vh'] + 1 and box['menuRight'] <= box['vw'] + 1 and box['menuLeft'] >= 0, box)
        check(f'{tag}: the last advanced item is visible', box['lastBottom'] <= box['vh'] + 1 and box['lastTop'] >= box['menuTop'], box)
        shot(page, f'ui005-{tag}-expanded')
        page.keyboard.press('Escape')
        check(f'{tag}: no console or page errors', not errors, errors)
        ctx.close()

    ctx = browser.new_context(viewport={'width': 1366, 'height': 768})
    page = ctx.new_page()
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.on('console', lambda m: errors.append(m.text) if m.type == 'error' and 'Failed to load resource' not in m.text else None)
    open_lab(page, LAB)
    # Keyboard only: button, End, ArrowRight into the group, End, Enter
    page.focus('#lab-actions-button')
    page.keyboard.press('ArrowDown')
    page.keyboard.press('End')
    check('keyboard: End lands on Advanced options while it is collapsed', page.evaluate('() => document.activeElement.id') == 'lab-actions-advanced-toggle')
    page.keyboard.press('ArrowRight')
    check('keyboard: ArrowRight opens the group and enters it', page.evaluate('() => document.activeElement.id') == 'menu-import-map')
    page.keyboard.press('ArrowLeft')
    check('keyboard: ArrowLeft collapses it and returns to the toggle', page.evaluate('() => document.activeElement.id === "lab-actions-advanced-toggle" && document.getElementById("lab-actions-advanced").hidden'))
    page.keyboard.press('Enter')
    check('keyboard: Enter on the toggle expands it and keeps the menu open', page.evaluate('() => !document.getElementById("lab-actions-advanced").hidden && !document.getElementById("lab-actions-menu").hidden'))
    page.keyboard.press('End')
    page.keyboard.press('Enter')
    page.wait_for_selector('#operation-history[open], dialog[open]', timeout=15000)
    title = page.evaluate('() => document.querySelector("dialog[open] h2")?.textContent || ""')
    check('Operation history opens from the group by keyboard', 'history' in title.lower(), title)
    shot(page, 'ui005-operation-history')
    page.keyboard.press('Escape')
    check('focus returns to the Lab actions button', page.evaluate('() => document.activeElement.id') == 'lab-actions-button')
    # Pointer: Operation history again (by click, not keyboard), then the two remaining actions
    open_group(page)
    page.click('#menu-operation-history')
    page.wait_for_selector('dialog[open]', timeout=15000)
    title = page.evaluate('() => document.querySelector("dialog[open] h2")?.textContent || ""')
    check('Operation history opens from the group by pointer', 'history' in title.lower(), title)
    page.keyboard.press('Escape')
    open_group(page)
    page.click('#menu-import-map')
    page.wait_for_selector('#map-dialog[open]')
    check('Import map opens from the group', True)
    page.click('#cancel-map')
    open_group(page)
    check('Edit map is available for a lab with a map', not page.evaluate('() => document.getElementById("menu-map-edit").disabled'))
    page.click('#menu-map-edit')
    page.wait_for_function('() => /Editing|Save map|Done/i.test(document.body.innerText) && document.getElementById("lab-actions-menu").hidden', timeout=15000)
    check('Edit map starts the map editor from the group', True)
    shot(page, 'ui005-edit-map')
    check('Edit map is still on the map toolbar', page.evaluate('() => !!document.getElementById("map-edit")'))
    # A lab without a map: the moved item keeps its disabled state and its reason. A fresh context,
    # because the router reopens the last lab of a session and the map editor is still open in this one.
    ctx.close()
    ctx = browser.new_context(viewport={'width': 1366, 'height': 768})
    page = ctx.new_page()
    page.on('pageerror', lambda e: errors.append(str(e)))
    open_lab(page, EMPTY_MAP_LAB)
    open_group(page)
    state = page.evaluate('() => { const b = document.getElementById("menu-map-edit"), t = document.getElementById("map-edit"); return {disabled: b.disabled, toolbar: t.disabled, reason: b.querySelector(".menu-reason")?.textContent || b.title}; }')
    check('Edit map mirrors the toolbar state and says why when there is no map', state['disabled'] == state['toolbar'] and (not state['disabled'] or state['reason']), state)
    shot(page, 'ui005-no-map')
    check('no console or page errors', not errors, errors)
    browser.close()
sys.exit(1 if failed else 0)
