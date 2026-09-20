#!/usr/bin/env python3
"""UI-006 browser check: the Devices tab lines up.

Runs against the fixture manager; read-only. It measures the real layout: every row's identity, state
and action columns start at the same x, the list is flush with the heading and the search controls,
nothing overlaps or is clipped, and the page never scrolls sideways. One device is given a very long
name and a long reason in the page only (no request is sent) to exercise wrapping.

    CLAB_BASE=http://127.0.0.1:8090 clab-backup-ui/.venv/bin/python docs/ui-review-001/tools/check_ui006.py
"""
import os
import sys

from playwright.sync_api import sync_playwright

BASE = os.environ.get('CLAB_BASE', 'http://127.0.0.1:8090')
OUT = os.environ.get('CLAB_SHOTS', '')
LAB = os.environ.get('CLAB_LAB', 'BGP_TheoryToPractice')
failed = []

MEASURE = '''() => {
  const r = e => { const b = e.getBoundingClientRect(); return {l: Math.round(b.left), t: Math.round(b.top), r: Math.round(b.right), b: Math.round(b.bottom)}; };
  const rows = [...document.querySelectorAll('#device-list .device-row')].map(row => { const cli = row.querySelector('[data-terminal]'), det = row.querySelector('.details-action'), reason = row.querySelector('.row-reason');
    return {row: r(row), name: r(row.querySelector('.node-name')), pill: r(row.querySelector('.pill')), cli: r(cli), details: r(det), reason: reason ? r(reason) : null, state: row.className,
      label: row.querySelector('.pill').textContent, clipped: [cli, det].some(e => e.scrollWidth > e.clientWidth + 1)}; });
  const head = r(document.querySelector('#devices-view .section-heading')), title = r(document.querySelector('#devices-view .section-heading h2')), search = r(document.getElementById('search')), tech = r(document.getElementById('devices-technical'));
  return {rows, head, title, search, tech, list: r(document.getElementById('device-list')), vw: innerWidth, sideways: document.documentElement.scrollWidth > innerWidth + 1};
}'''


def check(name, ok, detail=''):
    print(('ok   ' if ok else 'FAIL ') + name + (f' :: {detail}' if not ok else ''), flush=True)
    if not ok:
        failed.append(name)


def overlap(a, b):
    return a['l'] < b['r'] - 1 and b['l'] < a['r'] - 1 and a['t'] < b['b'] - 1 and b['t'] < a['b'] - 1


with sync_playwright() as pw:
    browser = pw.chromium.launch()
    for width, height, scale in [(1920, 1080, 1), (1366, 768, 1), (1280, 720, 1.25), (1280, 720, 1.5), (1280, 720, 2)]:
        tag = f'{width}x{height}@{scale}'
        page = browser.new_page(viewport={'width': int(width / scale), 'height': int(height / scale)})
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(BASE + '/')
        page.wait_for_selector('article.lab-card')
        page.click(f'article.lab-card:has(h3:text-is("{LAB}")) [data-lab]')
        page.click('#tab-devices')
        page.wait_for_selector('#device-list .device-row')
        for long_case in (False, True):
            if long_case:
                # Stop the poll from redrawing, then stretch one row in place
                page.evaluate('''() => { window.refresh = async () => {}; const row = document.querySelectorAll('#device-list .device-row')[1];
                  row.querySelector('.node-name').textContent = 'clab-BGP_TheoryToPractice-distribution-switch-building-C-floor-03';
                  const cell = row.children[1]; cell.insertAdjacentHTML('beforeend', '<small class="row-reason">This device is running, but the manager could not log in with the saved credentials after three attempts. Check the credentials under Advanced, then open Details and choose Test login now.</small>'); }''')
            m = page.evaluate(MEASURE)
            rows, kind = m['rows'], 'long name and reason' if long_case else 'fixture states'
            single = m['vw'] <= 760
            check(f'{tag} {kind}: the list is flush with the heading on both sides', m['list']['l'] == m['title']['l'] and abs(m['list']['r'] - m['head']['r']) <= 1, (m['list'], m['title'], m['head']))
            check(f'{tag} {kind}: identity starts at one x in every row', len({r['name']['l'] for r in rows}) == 1, sorted({r['name']['l'] for r in rows}))
            check(f'{tag} {kind}: state starts at one x in every row', len({r['pill']['l'] for r in rows}) == 1, sorted({r['pill']['l'] for r in rows}))
            check(f'{tag} {kind}: Open CLI and Details each start at one x', len({r['cli']['l'] for r in rows}) == 1 and len({r['details']['l'] for r in rows}) == 1, (sorted({r['cli']['l'] for r in rows}), sorted({r['details']['l'] for r in rows})))
            if not single:
                check(f'{tag} {kind}: name, state and Open CLI share one line in every row', all(abs((r['name']['t'] + r['name']['b']) / 2 - (r['cli']['t'] + r['cli']['b']) / 2) <= 3 and abs((r['pill']['t'] + r['pill']['b']) / 2 - (r['cli']['t'] + r['cli']['b']) / 2) <= 3 for r in rows if not (long_case and r is rows[1])),
                      [(r['name'], r['pill'], r['cli']) for r in rows[:3]])
            bad = [i for i, r in enumerate(rows) if overlap(r['name'], r['pill']) or overlap(r['pill'], r['cli']) or (r['reason'] and (overlap(r['reason'], r['cli']) or overlap(r['reason'], r['details']) or overlap(r['reason'], r['name'])))
                   or r['clipped'] or r['details']['r'] > r['row']['r'] or r['name']['l'] < r['row']['l']]
            check(f'{tag} {kind}: nothing overlaps, is clipped or leaves its row', not bad, [rows[i] for i in bad][:2])
            check(f'{tag} {kind}: no sideways scrolling', not m['sideways'])
            if not long_case:
                check(f'{tag}: search and Technical view have one height and sit on one line', abs((m['search']['b'] - m['search']['t']) - (m['tech']['b'] - m['tech']['t'])) <= 1 and abs(m['search']['t'] - m['tech']['t']) <= 1, (m['search'], m['tech']))
                check(f'{tag}: every state keeps its label and its reason', {r['label'] for r in rows} >= {'Ready', 'Starting', 'Needs credentials', 'Needs attention'} and all(r['reason'] for r in rows if r['label'] != 'Ready'), sorted({r['label'] for r in rows}))
            if OUT:
                page.screenshot(path=os.path.join(OUT, f'ui006-{tag}-{"long" if long_case else "states"}.png'), full_page=True)
        check(f'{tag}: no page errors', not errors, errors)
        page.close()

    # The controls still work
    page = browser.new_page(viewport={'width': 1366, 'height': 768})
    page.goto(BASE + '/')
    page.wait_for_selector('article.lab-card')
    page.click(f'article.lab-card:has(h3:text-is("{LAB}")) [data-lab]')
    page.click('#tab-devices')
    page.fill('#search', 'RTR')
    page.wait_for_function('() => document.querySelectorAll("#device-list .device-row").length < 6')
    names = page.evaluate('() => [...document.querySelectorAll("#device-list .node-name")].map(n => n.textContent)')
    check('search filters the list', names and all('RTR' in n.upper() for n in names), names)
    page.fill('#search', 'zzzz')
    page.wait_for_selector('#device-list .table-empty')
    check('an empty result spans the list', page.evaluate('() => { const e = document.querySelector("#device-list .table-empty").getBoundingClientRect(), l = document.getElementById("device-list").getBoundingClientRect(); return Math.abs(e.width - l.width) < 2; }'))
    page.fill('#search', '')
    page.click('#devices-technical')
    check('Technical view opens the table', page.is_visible('#inventory-view'))
    page.click('#device-list .device-row:nth-child(2) .details-action')
    page.wait_for_selector('#details-dialog[open]')
    check('Details opens the device panel', True)
    page.keyboard.press('Escape')
    with page.context.expect_page(timeout=15000) as popup:
        page.click('#device-list .device-row:nth-child(2) [data-terminal]')
    check('Open CLI opens the terminal tab', 'terminal' in popup.value.url, popup.value.url)
    # The rail on the Topology tab shares the list reset
    page.click('#tab-topology')
    rail = page.evaluate('() => { const h = document.getElementById("topology-devices-title").getBoundingClientRect(), r = document.querySelector("#topology-devices .device-row").getBoundingClientRect(); return {heading: Math.round(h.left), row: Math.round(r.left)}; }')
    check('the Topology rail is flush with its heading too', rail['heading'] == rail['row'], rail)
    if OUT:
        page.screenshot(path=os.path.join(OUT, 'ui006-topology-rail.png'))
    browser.close()
sys.exit(1 if failed else 0)
