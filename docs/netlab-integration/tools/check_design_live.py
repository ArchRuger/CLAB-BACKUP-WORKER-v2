#!/usr/bin/env python3
"""Exercise the *Network design* tab on the running manager (the real product on the dev VM) for one lab.

Generation only: saving a design and generating a plan touch no device, no VM file and no Docker. The script
uses the manager's own API (same origin, JSON bodies) and then opens the tab in Chromium for screenshots.

    PATH="$PWD/clab-backup-ui/.venv/bin:$PATH" clab-backup-ui/.venv/bin/python \\
        docs/netlab-integration/tools/check_design_live.py --base http://127.0.0.1:8081 --lab restore-square

Writes `docs/netlab-integration/evidence/live-design-<lab>.md` and screenshots beside it. Exit 1 on a failed check.
"""
import argparse
import json
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent


def call(base, method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(base + path, data=data, method=method, headers={'Content-Type': 'application/json', 'Origin': base})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, json.loads(response.read() or b'null')
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read() or b'{}')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--base', default='http://127.0.0.1:8081')
    parser.add_argument('--lab', default='restore-square')
    parser.add_argument('--shots', default=str(HERE.parent / 'evidence' / 'shots'))
    args = parser.parse_args()
    checks = []
    def check(name, ok, detail=''):
        checks.append((name, bool(ok), str(detail)[:300])); print(('  ok   ' if ok else '  FAIL ') + name + ('' if ok else ': ' + str(detail)[:200]), flush=True)
    status, state = call(args.base, 'GET', '/api/state')
    lab = next(l for l in state['labs'] if l['name'] == args.lab)
    lab_id = lab['id']
    check('the manager answers and names its version', status == 200 and state.get('version'), state.get('version'))
    status, view = call(args.base, 'GET', '/api/labs/%s/design' % lab_id)
    check('the design view loads for the lab', status == 200 and view['has_topology'], status)
    engine = view['engine']
    check('the engine is available inside the product image', engine['available'] and engine['path'].startswith('/usr/local/bin'), engine)
    names = sorted(view['nodes'])
    check('every device of the lab has a profile or a reason', all(row['profile'] or row['reason'] for row in view['nodes'].values()), names)
    included = [n for n, row in view['nodes'].items() if row['included']]
    intent = view['intent'] or {'schema': 1, 'label': '', 'families': {'ipv4': True, 'ipv6': True},
                                'addressing': {'loopback': {'ipv4': '10.255.0.0/24', 'ipv6': '2001:db8:ff::/48'}, 'p2p': {'ipv4': '10.1.0.0/16', 'ipv6': '2001:db8:1::/48', 'prefix': 31}, 'lan': {'ipv4': '172.16.0.0/16', 'ipv6': '2001:db8:2::/48', 'prefix': 24}},
                                'modules': [], 'targets': None, 'nodes': {}, 'links': {}, 'vlans': {}, 'vrfs': {}, 'interfaces': {}, 'allocations': {}}
    revision = (view['intent'] or {}).get('revision', '')
    intent = dict(intent, modules=['ospf', 'bgp'], ospf={'area': '0.0.0.0'}, bgp={'as': 65000}, label='live check ' + datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M'))
    status, saved = call(args.base, 'PUT', '/api/labs/%s/design' % lab_id, {'intent': intent, 'revision': revision})
    check('the design saves on the live lab', status == 200 and saved['intent']['revision'], saved if status != 200 else '')
    revision = saved['intent']['revision']
    status, queued = call(args.base, 'POST', '/api/labs/%s/design/generate' % lab_id, {'revision': revision})
    check('a plan is queued', status == 200 and queued['status'] in ('queued', 'running'), queued)
    generation = None
    for _ in range(240):
        status, view = call(args.base, 'GET', '/api/labs/%s/design' % lab_id)
        generation = next((g for g in view['generations'] if g['id'] == queued['id']), None)
        if generation and generation['status'] not in ('queued', 'running'): break
        time.sleep(0.5)
    check('the plan succeeded on the live lab', generation and generation['status'] == 'succeeded', (generation or {}).get('errors') or (generation or {}).get('message'))
    if generation and generation['status'] == 'succeeded':
        check('every included device has files', set(generation['artifacts']) == set(included), sorted(generation['artifacts']))
        check('the ledger pinned every included device', set(generation['ledger']['node_ids']) == set(included), generation['ledger']['node_ids'])
        check('the engine is the pinned release', generation['engine_version'] == '26.09', generation['engine_version'])
        status, detail = call(args.base, 'GET', '/api/labs/%s/design/generations/%s' % (lab_id, generation['id']))
        plan = detail['plan']
        check('the plan carries the containerlab ports of the real topology', any(i['clab'] == 'Gi0/0/0/0' for d in plan['devices'] for i in d['interfaces']) and any(i['clab'] == 'et-0/0/0' for d in plan['devices'] for i in d['interfaces']))
        request = urllib.request.Request(args.base + '/api/labs/%s/design/generations/%s/download' % (lab_id, generation['id']), headers={'Origin': args.base})
        with urllib.request.urlopen(request, timeout=60) as response: archive = response.read()
        check('the ZIP downloads', response.status == 200 and archive[:2] == b'PK' and len(archive) > 2000, len(archive))
        status, second = call(args.base, 'POST', '/api/labs/%s/design/generate' % lab_id, {'revision': revision})
        for _ in range(240):
            status, view = call(args.base, 'GET', '/api/labs/%s/design' % lab_id)
            again = next((g for g in view['generations'] if g['id'] == second['id']), None)
            if again and again['status'] not in ('queued', 'running'): break
            time.sleep(0.5)
        check('a second plan of the same design keeps every allocation', again['status'] == 'succeeded' and again['renumbering'] == [] and again['ledger'] == generation['ledger'], again.get('renumbering'))
    status, state = call(args.base, 'GET', '/api/state')
    live = next(l for l in state['labs'] if l['id'] == lab_id)
    check('/api/state carries the summary and no intent', live.get('design', {}).get('present') is True and 'network_design' not in live and 'network_generations' not in live)
    shots = Path(args.shots); shots.mkdir(parents=True, exist_ok=True)
    errors = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(); page = browser.new_page(viewport={'width': 1440, 'height': 900})
        page.on('console', lambda m: errors.append(m.text) if m.type == 'error' else None); page.on('pageerror', lambda e: errors.append('PAGEERROR ' + str(e)))
        page.goto(args.base + '/#lab=' + lab_id + '&view=design'); page.wait_for_selector('#design-view:not([hidden])', timeout=20000)
        page.wait_for_function('() => (document.getElementById("design-state")?.textContent || "").includes("Plan ready")', timeout=30000)
        check('the live page shows the plan as ready', True)
        text = page.locator('#design-plan').text_content() or ''
        check('the live page lists the real devices in the plan', all(n in text for n in included), text[:200])
        page.screenshot(path=str(shots / ('live-%s-plan.png' % args.lab)), full_page=True)
        browser.close()
    check('no console or page errors on the live page', not errors, errors[:3])
    failed = [c for c in checks if not c[1]]
    report = ['# Live check: Network design on the running manager (' + args.lab + ')', '',
              'Run ' + datetime.now(timezone.utc).isoformat(timespec='seconds') + ' against ' + args.base + ' (manager ' + str(state.get('version')) + ', the real product on the dev VM). Generation only: no device, VM file or Docker action.', '',
              '%d of %d checks passed.' % (len(checks) - len(failed), len(checks)), '', '| Check | Result | Detail |', '|---|---|---|']
    report += ['| ' + n + ' | ' + ('ok' if ok else 'FAIL') + ' | ' + d.replace('|', '\\|').replace('\n', ' ')[:160] + ' |' for n, ok, d in checks]
    Path(HERE.parent / 'evidence' / ('live-design-%s.md' % args.lab)).write_text('\n'.join(report) + '\n')
    print(report[4])
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
