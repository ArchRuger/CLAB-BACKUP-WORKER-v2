"""Live gates A (Home), C (topology), D (device panel + CLI), devices tab, P (polling)."""
import json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from live_lib import *
pw, b, ctx, r = session('stage1'); p = r.page
# --- Gate A: Home
p.goto(BASE + '/'); p.wait_for_selector('article.lab-card', timeout=20000); p.wait_for_timeout(1200)
cards = r.js('() => [...document.querySelectorAll("article.lab-card")].map(a => ({name: a.querySelector("h3").textContent, pill: a.querySelector(".pill")?.textContent, text: a.textContent.replace(/\\s+/g," ").trim().slice(0,300)}))')
r.note('home cards', cards)
r.check('A home: the live lab card is present with a student pill', any(c['name'] == LAB and c['pill'] in ('Ready', 'Running', 'Starting', 'Needs attention') for c in cards), cards)
r.check('A home: readiness count on the card', any('devices ready' in c['text'] or 'device ready' in c['text'] for c in cards), cards)
r.check('A home: no raw internal state words', not any(c['pill'] in ('Unlinked', 'Not deployed', 'Partially running') for c in cards), cards)
r.check('A home: skeleton hidden, VM banner hidden (VM connected)', r.js('() => document.getElementById("home-skeleton").hidden && document.getElementById("home-vm-banner").hidden'))
p.click('#manager-button'); p.wait_for_selector('#manager-menu-list:not([hidden])')
mm = r.js('() => ({items: [...document.querySelectorAll("#manager-menu-list button, #manager-menu-list a")].map(b => b.textContent.trim().slice(0,40)), foot: document.getElementById("manager-menu-list").textContent.replace(/\\s+/g," ").slice(-200)})')
r.note('manager menu', mm)
r.check('A home: Manager menu lists VM connection, Deploy, Running labs, Operation history, Diagnostics', all(any(k in i for i in mm['items']) for k in ('VM connection', 'Deploy a new lab', 'Running labs', 'Operation history', 'Diagnostics')), mm)
r.check('A home: Manager menu footer carries VM status and version', 'VM' in mm['foot'] and '1.28.0' in mm['foot'], mm['foot'])
r.shot('A-home-manager-menu'); p.keyboard.press('Escape'); r.shot('A-home')
# --- Gate C: topology
r.open_lab(); p.wait_for_selector('#topology-map [data-map-node]', timeout=15000); p.wait_for_timeout(800)
info = r.js('''() => { const map = document.getElementById('topology-map'), rect = map.getBoundingClientRect(); const states = {};
  for (const g of map.querySelectorAll('.map-device')) for (const c of g.classList) if (c.startsWith('state-')) states[c] = (states[c] || 0) + 1;
  return {bottom: rect.bottom, inner: innerHeight, states, dots: map.querySelectorAll('.device-state-dot').length, links: map.querySelectorAll('[data-map-link], .map-link, .topology-link').length,
    status: document.getElementById('map-status').textContent, labels: [...map.querySelectorAll('[data-map-node]')].map(g => g.getAttribute('aria-label')),
    title: document.getElementById('title').textContent, pill: document.getElementById('lab-state').textContent, ready: document.getElementById('lab-ready').textContent, banner: document.getElementById('lab-banner').hidden}; }''')
r.note('topology', info)
r.check('C topology: map renders both devices with state dots', info['dots'] == 2 and len(info['labels']) == 2, info)
r.check('C topology: header pill and readiness reflect the live lab', info['pill'] in ('Ready', 'Running') and info['ready'].startswith('2 of 2'), info)
r.check('C topology: both device glyphs are in the ready state', info['states'].get('state-ready') == 2, info['states'])
r.check('C topology: map fits the viewport at 1440x900', info['bottom'] <= info['inner'] + 0.5, info)
r.shot('C-topology')
node = p.locator('#topology-map [data-map-node$="-PTX1"]').first; node.click(button='right'); p.wait_for_selector('#node-context-menu:not([hidden])')
menu = r.js('''() => { const m = document.getElementById('node-context-menu'); return {items: [...m.querySelectorAll('[role=menuitem]')].map(b => ({text: b.textContent.trim().slice(0, 60), disabled: b.disabled, reason: b.querySelector('small')?.textContent})), header: m.querySelector('.context-node-name')?.textContent, focused: document.activeElement?.closest('#node-context-menu') !== null}; }''')
r.note('context menu', menu)
r.check('C menu: Open CLI first and enabled on the ready device; capture, backup, details follow', menu['items'] and menu['items'][0]['text'].startswith('Open CLI') and not menu['items'][0]['disabled'] and [i['text'].split(' ')[0] for i in menu['items']] == ['Open', 'Capture', 'Back', 'Device'], menu)
r.check('C menu: header shows the state, focus in the menu', 'Ready' in (menu['header'] or '') and menu['focused'], menu)
r.shot('C-context-menu'); time.sleep(POLL_MS / 1000 + 0.5)
r.check('C menu: survives a poll', not r.js('() => document.getElementById("node-context-menu").hidden'))
p.keyboard.press('Escape'); r.check('C menu: Escape closes, focus back on the device', r.js('() => document.getElementById("node-context-menu").hidden && document.activeElement?.dataset.mapNode?.endsWith("-PTX1") === true'))
p.keyboard.press('Shift+F10'); r.check('C menu: Shift+F10 opens from the keyboard', not r.js('() => document.getElementById("node-context-menu").hidden')); p.keyboard.press('Escape')
p.click('#map-expand'); r.check('C topology: expand toggles', r.js('() => document.getElementById("map-expand").textContent') == 'Close expanded map'); r.shot('C-expanded'); p.keyboard.press('Escape')
r.check('C topology: Escape closes the expanded map', r.js('() => !document.getElementById("topology-view").classList.contains("map-expanded")'))
p.click('#map-edit'); p.wait_for_selector('#op-layout-editor[open]'); r.check('C editor: Edit lab map opens', r.js('() => document.querySelector("#op-layout-editor h2").textContent === "Edit lab map"')); r.shot('C-editor'); p.click('#diagram-cancel')
p.click('#map-more-button'); p.click('#import-map'); p.wait_for_selector('#map-dialog[open]'); r.check('C import map dialog opens', True); r.shot('C-import-map'); p.click('#cancel-map')
# link click → capture dialog
links = p.locator('#topology-map [data-map-link], #topology-map .map-link')
r.note('link count', links.count())
if links.count():
    links.first.click(); 
    try: p.wait_for_selector('#capture-dialog[open]', timeout=8000); r.check('C topology: clicking a link opens the capture dialog', True); r.shot('C-link-capture'); p.click('#capture-close')
    except Exception as exc: r.check('C topology: clicking a link opens the capture dialog', False, repr(exc))
# --- Gate D: device panel
p.locator('#topology-map [data-map-node$="-PTX1"]').first.click(); p.wait_for_selector('#details-dialog[open]'); p.wait_for_timeout(500)
drawer = r.js('''() => ({title: document.getElementById('details-title').textContent, pill: document.getElementById('details-state').textContent, status: document.getElementById('details-status-text').textContent,
  actions: [...document.querySelectorAll('#details-status-actions button')].map(b => b.textContent.trim()), primary: [...document.querySelectorAll('#details-actions button')].map(b => ({text: b.textContent.trim(), disabled: b.disabled})),
  advanced: [...document.querySelectorAll('#details-advanced-actions button')].map(b => b.textContent.trim()), platform: document.getElementById('node-platform')?.value || document.querySelector('#details-dialog .badge.platform')?.textContent, hash: location.hash, text: document.getElementById('details-dialog').textContent.replace(/\\s+/g,' ').slice(0,600)})''')
r.note('drawer', drawer)
r.check('D panel: device name, Ready pill, Open CLI first and enabled', 'PTX1' in drawer['title'] and drawer['pill'] == 'Ready' and drawer['primary'] and drawer['primary'][0]['text'].startswith('Open CLI') and not drawer['primary'][0]['disabled'], drawer)
r.check('D panel: platform named and history/backups + advanced present', ('Junos' in drawer['text'] or 'cJunos' in drawer['text'] or 'juniper' in drawer['text'].lower()) and ('Backups' in drawer['text'] or 'backup' in drawer['text']) and 'Advanced' in drawer['text'], drawer['text'][:300])
r.check('D panel: route carries the device', 'device=' in drawer['hash'], drawer['hash'])
r.shot('D-device-panel', full=True)
# Open CLI → popup terminal
with ctx.expect_page(timeout=15000) as popup_info:
    p.locator('#details-actions button', has_text='Open CLI').first.click()
term = popup_info.value; r.attach(term); term.wait_for_load_state()
term.wait_for_function('() => /^Connected/.test(document.getElementById("status").textContent)', timeout=60000); term.wait_for_timeout(1500)
r.note('terminal', term.evaluate('() => ({title: document.title, h: document.getElementById("title").textContent, status: document.getElementById("status").textContent, back: document.getElementById("back")?.textContent})'))
r.check('D CLI: terminal page opens and authenticates (Connected)', term.evaluate('() => document.getElementById("status").textContent') == 'Connected')
r.check('D CLI: device-first title', term.evaluate('() => document.getElementById("title").textContent').startswith('PTX1') or 'PTX1' in term.evaluate('() => document.title'))
term.click('#terminal'); term.wait_for_timeout(500)
def buf(): return term.evaluate('() => { const b = terminal.buffer.active; const out = []; for (let i = 0; i < b.length; i++) out.push(b.getLine(i)?.translateToString(true) || ""); return out.filter(l => l.trim()).join("\\n"); }')
for cmd in ('show version | no-more', 'show interfaces terse | no-more', 'show configuration | display set | no-more'):
    term.keyboard.type(cmd); term.keyboard.press('Enter'); term.wait_for_timeout(4000)
text = buf(); r.note('terminal output tail', text[-1500:])
r.check('D CLI: show version answered by Junos', 'Junos' in text or 'JUNOS' in text, text[-400:])
r.check('D CLI: show interfaces terse rendered', 'et-0/0/0' in text or 'ge-0/0/0' in text or 'lo0' in text, '')
r.check('D CLI: display set output rendered', 'set system' in text, '')
r.shot('D-terminal', page=term)
term.set_viewport_size({'width': 1000, 'height': 600}); term.wait_for_timeout(1000); cols1 = term.evaluate('() => terminal.cols')
term.set_viewport_size({'width': 1440, 'height': 900}); term.wait_for_timeout(1000); cols2 = term.evaluate('() => terminal.cols')
r.check('D CLI: resizing changes the terminal columns', cols1 != cols2, (cols1, cols2))
term.click('#disconnect'); term.wait_for_function('() => /^Disconnected/.test(document.getElementById("status").textContent)', timeout=15000)
r.check('D CLI: Disconnect clears the status cleanly', term.evaluate('() => document.getElementById("status").textContent').startswith('Disconnected'))
recon = term.locator('button', has_text='Reconnect').first
if recon.count(): recon.click(); term.wait_for_function('() => /^Connected/.test(document.getElementById("status").textContent)', timeout=60000); r.check('D CLI: Reconnect works', True); term.click('#disconnect'); term.wait_for_timeout(500)
else: r.check('D CLI: Reconnect works', False, 'no Reconnect button')
term.close()
time.sleep(POLL_MS / 1000 + 0.5); r.check('P polling: device panel still open after the CLI session', r.js('() => document.getElementById("details-dialog").open'))
p.keyboard.press('Escape'); p.wait_for_function('() => !document.getElementById("details-dialog").open', timeout=5000)
# --- Devices tab
r.tab('devices'); p.wait_for_timeout(500)
rows = r.js('() => [...document.querySelectorAll("#device-list .device-row")].map(li => ({name: li.querySelector(".node-name").textContent, pill: li.querySelector(".pill").textContent, platform: li.querySelector(".badge.platform")?.textContent, cli: li.querySelector("[data-terminal]").disabled}))')
r.note('device rows', rows); r.check('devices: both rows Ready with CLI enabled and a platform badge', len(rows) == 2 and all(x['pill'] == 'Ready' and not x['cli'] and x['platform'] for x in rows), rows)
r.shot('devices'); p.click('#devices-technical'); r.check('devices: technical table toggles', r.js('() => !document.getElementById("inventory-view").hidden')); r.shot('devices-technical'); p.click('#devices-technical')
# --- Gate P polling
p.locator('#devices-view [data-details]').first.click(); p.wait_for_selector('#details-dialog[open]')
before = r.js('() => ({title: document.getElementById("details-title")?.textContent, focus: document.activeElement?.id || document.activeElement?.tagName})'); p.wait_for_timeout(POLL_MS * 3 + 800)
after = r.js('() => ({open: document.getElementById("details-dialog").open, title: document.getElementById("details-title")?.textContent, focus: document.activeElement?.id || document.activeElement?.tagName})')
r.check('P polling: device panel stays open with the same device and focus across three live polls', after['open'] and after['title'] == before['title'] and after['focus'] == before['focus'], {'before': before, 'after': after})
p.keyboard.press('Escape'); p.wait_for_function('() => !document.getElementById("details-dialog").open')
p.click('#lab-actions-button'); p.wait_for_selector('#lab-actions-menu:not([hidden])'); p.keyboard.press('ArrowDown'); p.keyboard.press('ArrowDown')
focused = r.js('() => document.activeElement?.id || document.activeElement?.textContent'); p.wait_for_timeout(POLL_MS * 3 + 800)
still = r.js('() => ({open: !document.getElementById("lab-actions-menu").hidden, focus: document.activeElement?.id || document.activeElement?.textContent})')
r.check('P polling: open menu keeps its focused item across three live polls', still['open'] and still['focus'] == focused, {'focused': focused, 'still': still}); r.shot('P-menu-after-polls'); p.keyboard.press('Escape')
r.tab('devices'); p.locator('#device-list [data-terminal]').first.focus(); f0 = r.js('() => document.activeElement?.dataset?.terminal'); p.wait_for_timeout(POLL_MS * 2 + 500)
r.check('P polling: focus on an Open CLI row button is kept across two polls', r.js('() => document.activeElement?.dataset?.terminal') == f0 and f0, f0)
# --- Gate Q: viewports on the live lab
for (w, h) in ((1920, 1080), (1366, 768)):
    p.set_viewport_size({'width': w, 'height': h}); r.tab('topology'); p.wait_for_timeout(800)
    q = r.js('() => ({bottom: document.getElementById("topology-map").getBoundingClientRect().bottom, inner: innerHeight, scrollW: document.documentElement.scrollWidth, clientW: document.documentElement.clientWidth, header: document.querySelector("header, .lab-header")?.getBoundingClientRect().height, tabsRight: document.getElementById("lab-tabs").getBoundingClientRect().right, saveVisible: !!document.getElementById("progress-save") && document.getElementById("progress-save").getBoundingClientRect().right <= innerWidth})')
    r.note(f'viewport {w}x{h}', q)
    r.check(f'Q {w}x{h}: map fits, no horizontal page scroll, tabs and primary action within the viewport', q['bottom'] <= q['inner'] + 0.5 and q['scrollW'] <= q['clientW'] and q['tabsRight'] <= w and q['saveVisible'], q)
    r.shot(f'Q-{w}x{h}-topology')
    p.click('#lab-actions-button'); p.wait_for_selector('#lab-actions-menu:not([hidden])'); p.click('#menu-destroy'); p.wait_for_selector('#operation-review[open]', timeout=15000); p.wait_for_timeout(300)
    d = r.js('() => { const c = document.getElementById("op-confirm").getBoundingClientRect(); return {bottom: c.bottom, inner: innerHeight, visible: c.bottom <= innerHeight && c.top >= 0}; }')
    r.check(f'Q {w}x{h}: destroy review confirm button not clipped', d['visible'], d); r.shot(f'Q-{w}x{h}-destroy-review'); p.click('#op-cancel')
r.report('stage1'); b.close(); pw.stop()
