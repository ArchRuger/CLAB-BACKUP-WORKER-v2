#!/usr/bin/env python3
"""Stage 1 browser verification (round 2) for the clab-backup-ui shell.

For each viewport: home watch (13 s, three polls), open a lab, Topology
screenshot + map-bottom assertion, Lab actions menu held open across a poll,
five tabs, device drawer, Manager menu, browser Back, deep link to
#lab=<id>&view=progress, breadcrumb Home. Console errors and pageerrors are
collected for the whole run and reported per viewport.
"""
import json
import os
import sys
import time

from playwright.sync_api import sync_playwright

BASE = 'http://127.0.0.1:8081'
OUT = '/tmp/claude-1000/-home-clabllm/58f9753c-3287-4bf9-9f68-d2da708ca22e/scratchpad/shots/stage1-r2'
os.makedirs(OUT, exist_ok=True)
POLL_MS = 4000
TABS = ['topology', 'devices', 'progress', 'tools', 'advanced']


def js(page, expr, arg=None):
    return page.evaluate(expr, arg)


def run_viewport(browser, vw, vh):
    tag = f'{vw}x{vh}'
    r = {'viewport': tag, 'console': [], 'pageerrors': [], 'failed_requests': [], 'http_errors': [],
         'asserts': [], 'notes': [], 'shots': []}
    t0 = time.time()

    def el(t):
        return round(time.time() - t0, 1)

    ctx = browser.new_context(viewport={'width': vw, 'height': vh}, device_scale_factor=1)
    page = ctx.new_page()
    page.on('console', lambda m: r['console'].append({'t': el(0), 'type': m.type, 'text': m.text,
                                                        'loc': f"{m.location.get('url','')}:{m.location.get('lineNumber','')}"})
            if m.type in ('error', 'warning') else None)
    page.on('pageerror', lambda e: r['pageerrors'].append({'t': el(0), 'text': str(e)}))
    page.on('requestfailed', lambda q: r['failed_requests'].append({'t': el(0), 'url': q.url, 'err': q.failure}))
    page.on('response', lambda s: r['http_errors'].append({'t': el(0), 'url': s.url, 'status': s.status})
            if s.status >= 400 else None)

    def shot(name, full=True):
        path = os.path.join(OUT, f'{tag}-{name}.png')
        page.screenshot(path=path, full_page=full)
        r['shots'].append(path)
        return path

    def check(name, ok, detail=''):
        r['asserts'].append({'name': name, 'ok': bool(ok), 'detail': detail})

    # ---- A. Home watch: 13 s = three 4 s polls -------------------------------
    page.goto(BASE + '/')
    page.wait_for_selector('article.lab-card, #empty:not([hidden])', timeout=15000)
    loaded_at = el(0)
    r['notes'].append(f'home loaded (first card) at {loaded_at}s')
    # console errors are collected the whole time; wait until 13 s have passed
    while time.time() - t0 < 13:
        time.sleep(0.25)
    home_info = js(page, """() => {
      const q = s => document.querySelector(s);
      const cards = [...document.querySelectorAll('article.lab-card')].map(a => ({
        id: a.dataset.labId, name: a.querySelector('h3')?.textContent,
        continued: a.classList.contains('continue'),
        pill: a.querySelector('.pill')?.textContent, pillClass: a.querySelector('.pill')?.className,
        lines: [...a.querySelectorAll(':scope > p')].map(p => p.textContent.trim()),
        buttons: [...a.querySelectorAll('button')].map(b => ({text: b.textContent.trim(), disabled: b.disabled, title: b.title, aria: b.getAttribute('aria-label'), pressed: b.getAttribute('aria-pressed')}))
      }));
      return {
        cards, skeletonHidden: q('#home-skeleton')?.hidden, emptyHidden: q('#empty')?.hidden,
        continueHidden: q('#home-continue')?.hidden, cardsHidden: q('#lab-cards')?.hidden,
        homeActionsHidden: q('#home-actions')?.hidden, deployReason: q('#home-deploy-reason')?.textContent,
        homeBanner: {hidden: q('#home-banner')?.hidden, text: q('#home-banner-text')?.textContent},
        vmBanner: {hidden: q('#home-vm-banner')?.hidden, text: q('#home-vm-banner-text')?.textContent},
        discoveredHidden: q('#home-discovered')?.hidden,
        workerState: q('#worker-state')?.textContent, hash: location.hash,
        scrollWidth: document.documentElement.scrollWidth, innerWidth,
        labContentHidden: q('#lab-content')?.hidden,
      };
    }""")
    r['home'] = home_info
    check('home: no horizontal overflow', home_info['scrollWidth'] <= home_info['innerWidth'],
          f"scrollWidth={home_info['scrollWidth']} innerWidth={home_info['innerWidth']}")
    check('home: skeleton hidden once loaded', home_info['skeletonHidden'] is True)
    check('home: at least one card', len(home_info['cards']) >= 1, f"{len(home_info['cards'])} cards")
    r['notes'].append(f'home watch finished at {el(0)}s; console errors so far: {len(r["console"])}, pageerrors: {len(r["pageerrors"])}')
    shot('01-home-initial')

    # ---- B. Open lab ---------------------------------------------------------
    card = page.locator('article.lab-card').first
    lab_id = card.get_attribute('data-lab-id')
    r['lab_id'] = lab_id
    card.locator('button[data-lab]').first.click()
    time.sleep(5)
    topo = js(page, """() => {
      const q = s => document.querySelector(s);
      const m = q('#topology-map').getBoundingClientRect();
      const hdr = q('.lab-header')?.getBoundingClientRect(), tabs = q('#lab-tabs')?.getBoundingClientRect();
      const banner = q('#lab-banner');
      const items = [...document.querySelectorAll('#lab-tabs [role=tab]')].map(b => ({id: b.id, sel: b.getAttribute('aria-selected'), ti: b.getAttribute('tabindex'), controls: b.getAttribute('aria-controls'), active: b.classList.contains('active'), weight: getComputedStyle(b).fontWeight}));
      const panels = [...document.querySelectorAll('[role=tabpanel]')].map(p => ({id: p.id, hidden: p.hidden, labelledby: p.getAttribute('aria-labelledby')}));
      const title = q('#title')?.getBoundingClientRect(), acts = q('.lab-header-actions')?.getBoundingClientRect();
      return {
        mapBottom: m.bottom, mapTop: m.top, mapHeight: m.height, innerHeight, innerWidth,
        scrollWidth: document.documentElement.scrollWidth,
        headerH: hdr && hdr.height, headerTop: hdr && hdr.top, tabsTop: tabs && tabs.top, tabsH: tabs && tabs.height,
        titleRight: title && title.right, actionsLeft: acts && acts.left,
        titleOverlapsActions: !!(title && acts && title.right > acts.left && title.top < acts.bottom && title.bottom > acts.top),
        stageMinH: getComputedStyle(q('.topology-stage') || q('#topology-map')).minHeight,
        title: q('#title')?.textContent, pill: q('#lab-state')?.textContent, pillClass: q('#lab-state')?.className,
        ready: q('#lab-ready')?.textContent, progress: q('#lab-progress')?.textContent,
        banner: {hidden: banner?.hidden, cls: banner?.className, role: banner?.getAttribute('role'), text: q('#lab-banner-text')?.textContent,
                 visibleButtons: [...banner.querySelectorAll('button')].filter(b => !b.hidden).map(b => b.id)},
        tablistRole: q('#lab-tabs')?.getAttribute('role'), tabs: items, panels,
        mapStatus: q('#map-status')?.textContent, mapNodes: document.querySelectorAll('#topology-map .node, #topology-map g[data-node], #topology-map [aria-label]').length,
        railRows: document.querySelectorAll('#topology-devices li').length,
        hash: location.hash, histLen: history.length,
        breadcrumb: q('#breadcrumb')?.textContent, breadcrumbHidden: q('#breadcrumb')?.hidden,
        opSummaryHidden: q('#operation-summary')?.hidden,
      };
    }""")
    r['topology'] = topo
    fits = topo['mapBottom'] <= topo['innerHeight']
    check(f'topology: #topology-map bottom <= innerHeight ({tag})', fits if (vw, vh) == (1366, 768) else True,
          f"mapBottom={topo['mapBottom']:.1f} innerHeight={topo['innerHeight']} mapTop={topo['mapTop']:.1f} mapHeight={topo['mapHeight']:.1f} bannerHidden={topo['banner']['hidden']} (asserted only at 1366x768; here fits={fits})")
    check('topology: no horizontal overflow', topo['scrollWidth'] <= topo['innerWidth'], f"scrollWidth={topo['scrollWidth']}")
    check('topology: title does not overlap header actions', not topo['titleOverlapsActions'],
          f"titleRight={topo['titleRight']} actionsLeft={topo['actionsLeft']}")
    check('tabs: role=tablist', topo['tablistRole'] == 'tablist')
    check('tabs: exactly one aria-selected=true and it is topology',
          [t['id'] for t in topo['tabs'] if t['sel'] == 'true'] == ['tab-topology'], json.dumps(topo['tabs']))
    check('tabs: exactly one panel visible and it is topology-view',
          [p['id'] for p in topo['panels'] if not p['hidden']] == ['topology-view'], json.dumps(topo['panels']))
    check('route: hash carries lab and view after Open lab', f'lab={lab_id}' in topo['hash'] and 'view=topology' in topo['hash'], topo['hash'])
    shot('02-topology')

    # ---- C. Lab actions menu open across one poll ----------------------------
    page.click('#lab-actions-button')
    time.sleep(0.4)
    m0 = js(page, "() => ({hidden: document.getElementById('lab-actions-menu').hidden, expanded: document.getElementById('lab-actions-button').getAttribute('aria-expanded'), focus: document.activeElement && (document.activeElement.id || document.activeElement.textContent.trim().slice(0,40))})")
    check('lab actions: opens (hidden=false, aria-expanded=true)', m0['hidden'] is False and m0['expanded'] == 'true', json.dumps(m0))
    check('lab actions: focus moves to first enabled menuitem', bool(m0['focus']) and m0['focus'] != 'lab-actions-button', f"activeElement={m0['focus']}")
    time.sleep(POLL_MS / 1000 + 2.5)  # at least one poll while open
    menu = js(page, """() => {
      const menu = document.getElementById('lab-actions-menu');
      const rect = menu.getBoundingClientRect();
      return {hidden: menu.hidden, expanded: document.getElementById('lab-actions-button').getAttribute('aria-expanded'),
        focus: document.activeElement && (document.activeElement.id || document.activeElement.textContent.trim().slice(0,40)),
        offRight: rect.right > innerWidth, offBottom: rect.bottom > innerHeight, rect: {l: rect.left, r: rect.right, t: rect.top, b: rect.bottom},
        items: [...menu.querySelectorAll('[role=menuitem]')].map(b => ({id: b.id || b.dataset.opAction + (b.dataset.opVariant ? ':' + b.dataset.opVariant : ''), text: b.querySelector('span')?.textContent.trim() || b.textContent.trim(),
          disabled: b.disabled, hidden: b.hidden, title: b.title, reason: b.querySelector('.menu-reason')?.textContent.trim(), reasonHidden: b.querySelector('.menu-reason')?.hidden,
          proxy: b.dataset.proxy, ownerDisabled: b.dataset.proxy ? document.getElementById(b.dataset.proxy)?.disabled : null, ownerTitle: b.dataset.proxy ? document.getElementById(b.dataset.proxy)?.title : null}))};
    }""")
    r['lab_actions_menu'] = menu
    check('lab actions: still open after a poll', menu['hidden'] is False and menu['expanded'] == 'true', json.dumps({k: menu[k] for k in ('hidden', 'expanded', 'focus')}))
    check('lab actions: menu within viewport', not menu['offRight'] and not menu['offBottom'], json.dumps(menu['rect']))
    bad_gate = [i for i in menu['items'] if i['disabled'] and not i['hidden'] and not (i['reason'] and i['reasonHidden'] is False) and not i['title']]
    check('lab actions: every disabled visible item has a visible reason', not bad_gate, json.dumps(bad_gate))
    proxy_mismatch = [i for i in menu['items'] if i['proxy'] and i['ownerDisabled'] is not None and i['ownerDisabled'] != i['disabled']]
    check('lab actions: proxies mirror owner disabled state', not proxy_mismatch, json.dumps(proxy_mismatch))
    shot('03-lab-actions-menu', full=False)
    page.keyboard.press('Escape')
    time.sleep(0.3)
    m2 = js(page, "() => ({hidden: document.getElementById('lab-actions-menu').hidden, focus: document.activeElement && document.activeElement.id})")
    check('lab actions: Escape closes and returns focus to button', m2['hidden'] is True and m2['focus'] == 'lab-actions-button', json.dumps(m2))
    r['notes'].append(f'menu phase done at {el(0)}s')

    # ---- D. Five tabs --------------------------------------------------------
    r['tabs'] = {}
    for name in TABS:
        page.click(f'#tab-{name}')
        time.sleep(1.3)
        info = js(page, """(name) => {
          const q = s => document.querySelector(s);
          const tabs = [...document.querySelectorAll('#lab-tabs [role=tab]')].map(b => ({id: b.id, sel: b.getAttribute('aria-selected'), ti: b.getAttribute('tabindex'), active: b.classList.contains('active'), weight: getComputedStyle(b).fontWeight}));
          const panels = [...document.querySelectorAll('[role=tabpanel]')].map(p => ({id: p.id, hidden: p.hidden}));
          const panel = q('#' + name + '-view');
          const heads = panel ? [...panel.querySelectorAll('h2, h3')].filter(h => h.offsetParent !== null).map(h => h.textContent.trim()).slice(0, 25) : [];
          const bannerH = q('#lab-banner').hidden;
          return {hash: location.hash, histLen: history.length, tabs, panels, heads,
            scrollWidth: document.documentElement.scrollWidth, innerWidth, docH: document.documentElement.scrollHeight,
            focus: document.activeElement && document.activeElement.id, bannerHidden: bannerH,
            visibleText: panel ? panel.innerText.slice(0, 1500) : ''};
        }""", name)
        r['tabs'][name] = info
        check(f'tab {name}: aria-selected only on tab-{name}', [t['id'] for t in info['tabs'] if t['sel'] == 'true'] == [f'tab-{name}'], json.dumps(info['tabs']))
        check(f'tab {name}: tabindex 0 only on tab-{name}', [t['id'] for t in info['tabs'] if t['ti'] == '0'] == [f'tab-{name}'])
        check(f'tab {name}: only {name}-view visible', [p['id'] for p in info['panels'] if not p['hidden']] == [f'{name}-view'], json.dumps(info['panels']))
        check(f'tab {name}: route view={name}', f'view={name}' in info['hash'], info['hash'])
        check(f'tab {name}: no horizontal overflow', info['scrollWidth'] <= info['innerWidth'], f"scrollWidth={info['scrollWidth']}")
        shot(f'04-tab-{name}')

    # ---- E. Device drawer from the Devices tab -------------------------------
    page.click('#tab-devices')
    time.sleep(0.8)
    rows = page.locator('#device-list li.device-row')
    r['device_rows'] = rows.count()
    if rows.count():
        rows.first.locator('button.node-name').click()
        time.sleep(1.5)
        drawer = js(page, """() => {
          const q = s => document.querySelector(s), d = q('#details-dialog');
          const rect = d.getBoundingClientRect();
          return {open: d.open, hash: location.hash, title: q('#details-title')?.textContent, endpoint: q('#details-endpoint')?.textContent,
            width: rect.width, right: rect.right, innerWidth,
            actions: [...(q('#details-actions')?.querySelectorAll('button') || [])].map(b => ({text: b.textContent.trim(), disabled: b.disabled, title: b.title})),
            closeBtn: !!d.querySelector('button[aria-label="Close device panel"]'),
            hasAdvanced: !!q('#details-advanced'), infoText: (q('#details-info')?.innerText || '').slice(0, 600),
            current: [...document.querySelectorAll('#device-list li[aria-current="true"]')].length,
            eyebrow: !!d.querySelector('.eyebrow'), historyText: (q('#node-history')?.innerText || '').slice(0, 300)};
        }""")
        r['drawer'] = drawer
        check('drawer: opens', drawer['open'] is True)
        check('drawer: route carries device=', 'device=' in drawer['hash'], drawer['hash'])
        check('drawer: within viewport', drawer['right'] <= drawer['innerWidth'] + 1, f"right={drawer['right']} width={drawer['width']}")
        check('drawer: open row has aria-current', drawer['current'] == 1, f"count={drawer['current']}")
        check('drawer: has close button (aria-label="Close device panel")', drawer['closeBtn'])
        shot('05-drawer', full=False)
        if drawer['closeBtn']:
            page.click('#details-dialog button[aria-label="Close device panel"]')
        else:
            page.keyboard.press('Escape')
        time.sleep(0.6)
        after = js(page, "() => ({open: document.getElementById('details-dialog').open, hash: location.hash})")
        check('drawer: close clears device from route', after['open'] is False and 'device=' not in after['hash'], json.dumps(after))
    else:
        check('drawer: device rows present in Devices tab', False, 'no li.device-row in #device-list')

    # ---- F. Manager menu -----------------------------------------------------
    page.click('#manager-button')
    time.sleep(0.5)
    mm = js(page, """() => {
      const menu = document.getElementById('manager-menu-list'), rect = menu.getBoundingClientRect();
      return {hidden: menu.hidden, expanded: document.getElementById('manager-button').getAttribute('aria-expanded'),
        offRight: rect.right > innerWidth, rect: {l: rect.left, r: rect.right, b: rect.bottom},
        focus: document.activeElement && (document.activeElement.id || document.activeElement.textContent.trim().slice(0,40)),
        items: [...menu.querySelectorAll('[role=menuitem]')].map(b => ({id: b.id, text: b.textContent.trim(), disabled: b.disabled, hidden: b.hidden, reason: b.querySelector('.menu-reason')?.textContent.trim()}))};
    }""")
    r['manager_menu'] = mm
    check('manager menu: opens', mm['hidden'] is False and mm['expanded'] == 'true', json.dumps({k: mm[k] for k in ('hidden', 'expanded', 'focus')}))
    check('manager menu: within viewport', not mm['offRight'], json.dumps(mm['rect']))
    shot('06-manager-menu', full=False)
    page.keyboard.press('Escape')
    time.sleep(0.3)

    # ---- G. Browser Back once ------------------------------------------------
    before = js(page, "() => ({hash: location.hash, histLen: history.length})")
    page.go_back()
    time.sleep(1.5)
    back = js(page, """() => {
      const q = s => document.querySelector(s);
      return {hash: location.hash, labContentHidden: q('#lab-content').hidden, homeVisible: !!(q('#home-title') && q('#home-title').offsetParent !== null),
        activeTab: q('#lab-tabs [aria-selected="true"]')?.id, visiblePanel: [...document.querySelectorAll('[role=tabpanel]')].filter(p => !p.hidden).map(p => p.id),
        drawerOpen: q('#details-dialog').open, title: q('#title')?.textContent};
    }""")
    r['back'] = {'before': before, 'after': back}
    hv = back['hash']
    expected_tab = None
    if 'view=' in hv:
        expected_tab = 'tab-' + hv.split('view=')[1].split('&')[0]
    consistent = (back['labContentHidden'] is True and back['homeVisible']) if not hv or 'lab=' not in hv else (back['labContentHidden'] is False and back['activeTab'] == expected_tab)
    check('back: UI matches the route it landed on', consistent, json.dumps(r['back']))
    r['notes'].append(f"Back landed on hash={hv!r}: labContentHidden={back['labContentHidden']} activeTab={back['activeTab']} panel={back['visiblePanel']} drawerOpen={back['drawerOpen']} (before: {before['hash']!r})")

    # ---- H. Deep link to progress -------------------------------------------
    page.goto(f'{BASE}/#lab={lab_id}&view=progress')
    try:
        page.wait_for_selector('#lab-content:not([hidden])', timeout=10000)
    except Exception as e:  # noqa: BLE001
        r['notes'].append(f'deep link: #lab-content never shown: {e}')
    time.sleep(2.5)
    deep = js(page, """() => {
      const q = s => document.querySelector(s);
      return {hash: location.hash, labContentHidden: q('#lab-content').hidden, activeTab: q('#lab-tabs [aria-selected="true"]')?.id,
        progressSelected: q('#tab-progress')?.getAttribute('aria-selected'), progressHidden: q('#progress-view')?.hidden,
        visiblePanel: [...document.querySelectorAll('[role=tabpanel]')].filter(p => !p.hidden).map(p => p.id), title: q('#title')?.textContent,
        breadcrumb: q('#breadcrumb')?.textContent};
    }""")
    r['deep_link'] = deep
    check('deep link: Progress tab active and panel visible', deep['progressSelected'] == 'true' and deep['progressHidden'] is False and deep['labContentHidden'] is False, json.dumps(deep))
    shot('07-deeplink-progress')

    # ---- I. Home via breadcrumb ---------------------------------------------
    page.click('#crumb-home')
    time.sleep(1.5)
    home2 = js(page, """() => {
      const q = s => document.querySelector(s);
      return {hash: location.hash, labContentHidden: q('#lab-content').hidden, homeVisible: !!(q('#home-title') && q('#home-title').offsetParent !== null),
        cards: document.querySelectorAll('article.lab-card').length, breadcrumbHidden: q('#breadcrumb')?.hidden, sepHidden: q('#crumb-sep')?.hidden,
        scrollWidth: document.documentElement.scrollWidth, innerWidth};
    }""")
    r['home_after'] = home2
    check('breadcrumb home: shows Home, hides lab content, clears route', home2['homeVisible'] and home2['labContentHidden'] is True and 'lab=' not in home2['hash'], json.dumps(home2))
    shot('08-home')

    r['notes'].append(f'viewport done at {el(0)}s')
    ctx.close()
    return r


def main():
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for vw, vh in ((1920, 1080), (1366, 768)):
            results.append(run_viewport(browser, vw, vh))
        browser.close()
    out = os.path.join(OUT, 'report.json')
    with open(out, 'w') as f:
        json.dump(results, f, indent=1, default=str)
    for r in results:
        print('=' * 78)
        print(r['viewport'])
        print('console errors/warnings:', len(r['console']), ' pageerrors:', len(r['pageerrors']),
              ' failed requests:', len(r['failed_requests']), ' http>=400:', len(r['http_errors']))
        for c in r['console']:
            print('  CONSOLE', c)
        for e in r['pageerrors']:
            print('  PAGEERROR', e)
        for e in r['failed_requests']:
            print('  REQFAIL', e)
        for e in r['http_errors']:
            print('  HTTP', e)
        for n in r['notes']:
            print('  note:', n)
        for a in r['asserts']:
            print('  ', 'PASS' if a['ok'] else 'FAIL', a['name'], ('-- ' + a['detail'][:400]) if (not a['ok'] or 'bottom' in a['name']) else '')
        print('  shots:')
        for s in r['shots']:
            print('    ', s)
    print('report:', out)


if __name__ == '__main__':
    main()
