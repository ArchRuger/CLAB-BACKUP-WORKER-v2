#!/usr/bin/env python3
"""Pass-2 extra live check of DEFECTS QA-013 (read-only): open Capture traffic… from the map for the Junos and IOS XR
devices and read whether the diagram's ports were recognised among the VM's container interfaces. Nothing is
prepared or started (the dialog only issues GETs); the dialog is closed again."""
import json, sys, time
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, '/home/clabllm/projects/clab-manager-1.30.42/docs/netlab-ui-qa/tools')
from check_restart_device import call, open_map_menu  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402
base = 'http://127.0.0.1:8081'; out = Path(sys.argv[1])
now = lambda: datetime.now(timezone.utc).isoformat(timespec='seconds')
EXPECT = {'cjunosevolved': ['eth4', 'eth5'], 'vjunos-switch': ['eth1', 'eth2', 'eth3'], 'xrv9k': ['eth1', 'eth2']}
st, state = call(base, '/api/state'); lab = next(l for l in state['labs'] if l['name'] == 'restore-square')
record = {'started': now(), 'manager': state.get('version'), 'devices': {}}; checks = []
def check(name, ok, detail=''):
    checks.append({'name': name, 'ok': bool(ok), 'detail': str(detail)[:500]}); print(('  ok   ' if ok else '  FAIL ') + name + ('' if ok else ': ' + str(detail)[:300]), flush=True)
jobs_before = len(call(base, '/api/operations')[1]); sessions_before = call(base, '/api/capture/sessions')[1]
with sync_playwright() as pw:
    browser = pw.chromium.launch(); page = browser.new_page(viewport={'width': 1366, 'height': 768})
    errors = []; page.on('pageerror', lambda e: errors.append(str(e)))
    page.goto(base + '/#lab=' + lab['id'] + '&view=topology')
    page.wait_for_selector('#topology-map [data-map-node]', timeout=30000); page.wait_for_timeout(1500)
    for short, expected in EXPECT.items():
        name = 'clab-restore-square-' + short
        open_map_menu(page, name)
        item = page.locator('#node-context-menu button[data-capture="%s"]' % name)
        item.click(); page.wait_for_selector('dialog#capture-dialog[open]', timeout=10000)
        status = ''
        for _ in range(40):
            status = page.locator('#capture-status').first.text_content() or ''
            if status and 'Looking up' not in status: break
            page.wait_for_timeout(1000)
        legend = page.locator('#capture-primary-legend').first.text_content() or ''
        labels = page.evaluate("() => Array.from(document.querySelectorAll('#capture-interfaces label')).map(l => l.innerText.trim())")
        record['devices'][short] = {'status': status, 'legend': legend, 'interfaces': labels}
        check('%s: the diagram ports are recognised (legend "Connected interfaces", no "not found on the VM")' % short, legend == 'Connected interfaces' and 'not found' not in status, json.dumps({'legend': legend, 'status': status}))
        check('%s: the connected interfaces are the containerlab ends of its diagram ports %s' % (short, expected), all(any(e in l for l in labels) for e in expected), json.dumps(labels))
        if short == 'xrv9k': page.screenshot(path=str(out / 'capture-dialog-xrv9k.png'))
        page.click('#capture-close'); page.wait_for_timeout(500)
    browser.close()
check('no job and no capture session was created', len(call(base, '/api/operations')[1]) == jobs_before and call(base, '/api/capture/sessions')[1] == sessions_before, '')
check('no page errors', not errors, json.dumps(errors))
record['checks'] = checks; record['finished'] = now()
(out / 'capture-dialog-ports.json').write_text(json.dumps(record, indent=1))
print('%d checks, %d failed' % (len(checks), sum(1 for c in checks if not c['ok'])))
