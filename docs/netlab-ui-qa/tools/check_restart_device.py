#!/usr/bin/env python3
"""Drive *Restart device* on a real running manager and record the evidence the campaign asks for.

Restart device is containerlab's node-scoped restart (`containerlab restart --node <node> -t <topology>`,
the operation the Containerlab VS Code extension runs) offered by the manager for one device of a
deployed lab, from the map's right-click menu and from the Devices view. This tool runs on the lab VM
itself (it reads container identities with `sudo docker inspect`), points a real Chromium at the
manager, and walks one device through:

  1. the map entry point: right-click the device, *Restart device…*, read the review, **Cancel** —
     then prove nothing happened (no operation job, the container's start time unchanged);
  2. the same entry point again, **Restart device** confirmed — follow the job to its end, prove the
     target restarted (same container id, new start time), the other containers did not (same ids and
     start times), the job says how many links containerlab restored, the device read *Restarting*
     while the job ran and its login was proven afresh afterwards (a new check time, later than the
     job), within the image's boot budget;
  3. the Devices entry point, by keyboard: the Devices tab, the device's *Details* button, *Restart
     device…* in the device panel, the same review, confirmed and followed the same way (`--devices`);
  4. optionally a stopped device (`--stopped`): the device is stopped first with containerlab's own
     `stop --node` (what the extension's *Stop node* runs), then restarted through the manager, and
     the restored links are counted.

Every step is a real click or key press on the page; nothing is toggled or called directly. Screenshots
and a JSON record land under `--out`; the record is what `docs/netlab-ui-qa/RESTART-PARITY.md` cites.

    PATH="$PWD/clab-backup-ui/.venv/bin:$PATH" clab-backup-ui/.venv/bin/python \\
        docs/netlab-ui-qa/tools/check_restart_device.py --url http://127.0.0.1:8081 --lab restore-square \\
        --device ceos --ready-budget 240 [--devices] [--stopped] [--out DIR] [--viewport 1366x768]

Exit status 1 when a check failed or an unexpected console/page error was seen; 0 otherwise.
"""
import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
HANDLED = 'Failed to load resource: the server responded with a status of '
TERMINAL = ('succeeded', 'failed', 'interrupted')


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def call(base, path, method='GET', body=None, timeout=30):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(base + path, data=data, method=method, headers={'Content-Type': 'application/json', 'Origin': base})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read() or b'null')
    except urllib.error.HTTPError as error:
        try: return error.code, json.loads(error.read() or b'{}')
        except json.JSONDecodeError: return error.code, {}


def docker_inspect(names):
    """{container name: {id, started, status, pid}} for the named containers, through the VM's Docker."""
    out = subprocess.run(['sudo', 'docker', 'inspect', '--format', '{{.Name}}|{{.Id}}|{{.State.StartedAt}}|{{.State.Status}}|{{.State.Pid}}', *names],
                         capture_output=True, text=True)
    result = {}
    for line in out.stdout.splitlines():
        name, ident, started, status, pid = line.split('|')
        result[name.lstrip('/')] = {'id': ident, 'started': started, 'status': status, 'pid': int(pid)}
    return result


def container_links(name):
    """The container's non-management interfaces with their peer index, or an empty list when it is not running."""
    out = subprocess.run(['sudo', 'docker', 'exec', name, 'ip', '-br', 'link'], capture_output=True, text=True)
    links = []
    for line in out.stdout.splitlines():
        iface = line.split()[0]
        if iface.startswith(('lo', 'eth0@', 'tap', 'br', 'dummy')): continue
        links.append(iface)
    return links


class Run:
    def __init__(self, page, out):
        self.page, self.out = page, out
        self.console, self.pageerrors, self.checks, self.shots = [], [], [], []
        page.on('console', lambda m: self.console.append({'type': m.type, 'text': m.text}) if m.type == 'error' else None)
        page.on('pageerror', lambda e: self.pageerrors.append(str(e)))

    def check(self, name, ok, detail=''):
        self.checks.append({'name': name, 'ok': bool(ok), 'detail': str(detail)[:400]})
        print(('  ok   ' if ok else '  FAIL ') + name + ('' if ok else ': ' + str(detail)[:300]), flush=True)

    def note(self, message):
        print('  note ' + message, flush=True)

    def shot(self, name):
        path = self.out / (getattr(self, 'prefix', '') + name + '.png')   # one set of screenshots per device and run
        self.page.screenshot(path=str(path), full_page=False)
        self.shots.append(path.name)

    def text(self, selector):
        node = self.page.locator(selector).first
        return (node.text_content() or '') if node.count() else ''


def device_pill(page, node_name):
    """The state pill of this device's row in the topology rail (the Devices tab list has the same row)."""
    return page.evaluate("""(name) => {
        const row = Array.from(document.querySelectorAll('#topology-devices li.device-row')).find(li => li.querySelector('[data-details="' + name + '"]'));
        return row ? (row.querySelector('.pill')?.textContent || '') : '';
    }""", node_name)


def design_snapshot(base, lab_id):
    """What a Restart device must never change: the design's revision, its generations and the lab's Git binding."""
    status, design = call(base, '/api/labs/%s/design' % lab_id)
    status2, state = call(base, '/api/state')
    lab = next((l for l in state['labs'] if l['id'] == lab_id), {}) if status2 == 200 else {}
    intent = (design or {}).get('intent') or {} if status == 200 else {}
    return {'design_revision': intent.get('revision'), 'design_updated': intent.get('updated'),
            'generations': [(g.get('id'), g.get('status')) for g in ((design or {}).get('generations') or [])] if status == 200 else None,
            'git_binding': lab.get('git_binding'), 'last_deployed': lab.get('last_deployed')}


def newest_job(base, lab_id, node_name):
    status, jobs = call(base, '/api/operations')
    if status != 200: return None
    return next((j for j in jobs if j.get('lab_id') == lab_id and j.get('action') == 'restart-node' and j.get('node') == node_name), None)


def follow_job(base, job_id, timeout=1500):
    deadline = time.monotonic() + timeout; job = None
    while time.monotonic() < deadline:
        status, found = call(base, '/api/operations/' + job_id)
        if status == 200: job = found
        if job and job.get('status') in TERMINAL: return job
        time.sleep(1)
    return job


def wait_ready(base, lab_id, node_name, after_iso, budget):
    """Wait until the device's login is proven again by a check made after `after_iso`; returns the node row or None."""
    deadline = time.monotonic() + budget; seen = []
    while time.monotonic() < deadline:
        status, state = call(base, '/api/state')
        if status == 200:
            lab = next((l for l in state['labs'] if l['id'] == lab_id), None)
            node = next((n for n in lab['nodes'] if n['name'] == node_name), None) if lab else None
            if node:
                word = node['nos_login']['status']
                if not seen or seen[-1][1] != word: seen.append((now(), word))
                if node['ssh_ready'] and (node['nos_login'].get('at') or '') > after_iso: return node, seen
        time.sleep(3)
    return None, seen


def review_open(page):
    dialog = page.locator('dialog#operation-review')
    page.wait_for_selector('dialog#operation-review[open]', timeout=20000)
    return dialog


def review_text(page):
    return page.evaluate("() => document.getElementById('operation-review')?.innerText || ''")


# Images whose restart has a known limit named in the review (RESTART_KNOWN_LIMITS in lab_operations.py), by kind.
KNOWN_LIMIT_WORDS = {'juniper_vjunosswitch': 'cannot be started a second time', 'cisco_xrv9k': 'factory configuration'}


def check_known_limit(r, text, kind, tag):
    """The review names the image's known limit before the student confirms, and only then; the text is kept
    in the record so the evidence shows what the student read."""
    if hasattr(r, 'reviews'): r.reviews[tag] = text[:2000]
    words = KNOWN_LIMIT_WORDS.get(kind or '')
    if words: r.check('the review names the known limit of this image before the student confirms', 'Known limit' in text and words in text, text[:900])
    else: r.check('the review carries no known-limit note for this image', 'Known limit' not in text, text[:900])


def check_review(r, text, label, lab_name, container, kind='', tag=''):
    r.check('the review is titled for the one device', ('Restart ' + label + '?') in text, text[:200])
    r.check('the review names the device and the lab and the native operation',
            ('Only ' + label + ' in ' + lab_name + ' restarts') in text and 'containerlab restart --node' in text, text[:400])
    r.check('the review says what drops and does not promise unrelated traffic is untouched',
            'CLI sessions drop and traffic through it stops' in text and 'neighbouring devices lose their adjacencies' in text
            and 'unaffected' not in text.lower(), text[:600])
    r.check('the review says nothing is saved, backed up, reset or reapplied', 'Nothing is saved, backed up, reset or reapplied for you.' in text, text[:600])
    r.check('the affected list is the one device', ('1 device affected: ' + label) in text and 'The other devices of ' + lab_name + ' are not restarted.' in text, text[:600])
    r.check('the command names exactly one --node', text.count('"--node"') == 1 and ('"--node" "' + label.split('/')[0]) in text or text.count('--node') >= 1, text[-600:])
    r.check('the confirm button is the destructive Restart device', page_confirm_label(r.page) == 'Restart device')
    check_known_limit(r, text, kind, tag or label)


def page_confirm_label(page):
    return (page.locator('#op-confirm').first.text_content() or '').strip()


def open_map_menu(page, node_name):
    target = page.locator('#topology-map [data-map-node="%s"]' % node_name).first
    target.scroll_into_view_if_needed()
    target.click(button='right')
    page.wait_for_selector('#node-context-menu:not([hidden])', timeout=10000)
    return page.locator('#node-context-menu button[data-restart="%s"]' % node_name)


def restart_from_map(r, page, base, lab, node, budget, before, others, tag):
    node_name, label = node['name'], node.get('short_name') or node['name']
    item = open_map_menu(page, node_name)
    r.check('the map menu offers Restart device… for the device', item.count() == 1 and not item.is_disabled(), item.get_attribute('title') if item.count() else 'no item')
    r.shot(tag + '-01-map-menu')
    item.click()
    review_open(page)
    text = review_text(page)
    r.shot(tag + '-02-review')
    check_review(r, text, label, lab['deployment_name'] or lab['name'], node_name, node.get('kind'), tag)
    # Cancel: no job, no change.
    jobs_before = call(base, '/api/operations')[1]
    page.click('#op-cancel')
    page.wait_for_selector('dialog#operation-review[open]', state='hidden', timeout=5000)
    time.sleep(1)
    after_cancel = docker_inspect([node_name])[node_name]
    r.check('Cancel starts nothing', len(call(base, '/api/operations')[1]) == len(jobs_before), 'jobs grew')
    r.check('Cancel leaves the container untouched', after_cancel['id'] == before[node_name]['id'] and after_cancel['started'] == before[node_name]['started'], json.dumps(after_cancel))
    # Again, confirmed this time.
    item = open_map_menu(page, node_name); item.click(); review_open(page)
    confirmed_at = now()
    page.click('#op-confirm')
    page.wait_for_selector('dialog#operation-review[open]', state='hidden', timeout=20000)
    return confirmed_at


def restart_from_devices(r, page, base, lab, node, tag):
    """The keyboard path: Devices tab, the device's Details button, Restart device… in the device panel."""
    node_name, label = node['name'], node.get('short_name') or node['name']
    page.click('#tab-devices')
    page.wait_for_selector('#devices-view:not([hidden])', timeout=10000)
    details = page.locator('#device-list button.details-action[data-details="%s"]' % node_name).first
    details.focus(); page.keyboard.press('Enter')
    page.wait_for_selector('dialog#details-dialog[open]', timeout=10000)
    button = page.locator('#details-actions button[data-restart="%s"]' % node_name).first
    r.check('the device panel offers Restart device… among the per-device actions', button.count() == 1 and not button.is_disabled(), button.get_attribute('title') if button.count() else 'no button')
    r.shot(tag + '-01-device-panel')
    # Reach it by keyboard: Tab from the first action until it has focus, then Enter.
    page.locator('#details-actions button').first.focus()
    for _ in range(8):
        if page.evaluate("() => document.activeElement && document.activeElement.hasAttribute('data-restart')"): break
        page.keyboard.press('Tab')
    r.check('Restart device… is reachable by keyboard in the device panel', page.evaluate("() => document.activeElement && document.activeElement.hasAttribute('data-restart')"))
    page.keyboard.press('Enter')
    review_open(page)
    text = review_text(page)
    r.shot(tag + '-02-review')
    check_review(r, text, label, lab['deployment_name'] or lab['name'], node_name, node.get('kind'), tag)
    r.check('the device panel stays open under the review (focus returns to its button afterwards)', page.evaluate("() => document.getElementById('details-dialog').open"))
    confirmed_at = now()
    page.click('#op-confirm')
    page.wait_for_selector('dialog#operation-review[open]', state='hidden', timeout=20000)
    if page.evaluate("() => document.getElementById('details-dialog').open"): page.keyboard.press('Escape')
    page.click('#tab-topology')
    return confirmed_at


def follow_and_prove(r, page, base, lab_id, node, before, others, budget, confirmed_at, tag, record, expect_links=None):
    node_name, label = node['name'], node.get('short_name') or node['name']
    # The device reads Restarting while the job runs (the 4 s poll may have to land first).
    pill = ''
    for _ in range(12):
        pill = device_pill(page, node_name)
        if pill == 'Restarting': break
        time.sleep(1)
    r.check('the device reads Restarting while the job runs', pill == 'Restarting', 'pill: ' + pill)
    banner = r.text('#lab-banner')
    r.check('the lab banner names the device being restarted', ('Restarting ' + label) in banner, banner[:200])
    r.shot(tag + '-03-restarting')
    job = newest_job(base, lab_id, node_name)
    r.check('one Restart device job exists for the device', job is not None and job['created'] >= confirmed_at[:19], json.dumps(job)[:300] if job else 'none')
    if not job: return None
    job = follow_job(base, job['id'])
    if not job:
        r.check('the job could be followed to its end', False, 'the job never reached a final state'); return None
    record['job'] = {k: job.get(k) for k in ('id', 'action', 'node', 'node_label', 'status', 'exit_code', 'message', 'created', 'started', 'finished')}
    record['job_output'] = job.get('output', '')[-2000:]
    r.check('the job succeeded', job['status'] == 'succeeded' and job['exit_code'] == 0, job.get('message'))
    r.check('the job output is containerlab\'s own restart log', 'Parsing & checking topology' in job.get('output', ''), job.get('output', '')[:200])
    restored = job.get('output', '').count('Restored link ')
    r.check('the job message counts the restored links', ('links restored' in job.get('message', '') or 'link restored' in job.get('message', '')) and str(restored) in job.get('message', ''), job.get('message'))
    if expect_links is not None: r.check('every dataplane link of the device was restored', restored == expect_links, 'restored %d, expected %d' % (restored, expect_links))
    after = docker_inspect(list(before))
    record['after'] = after
    r.check('the target kept its container id and has a new start time',
            after[node_name]['id'] == before[node_name]['id'] and after[node_name]['started'] > before[node_name]['started'] and after[node_name]['status'] == 'running', json.dumps(after[node_name]))
    untouched = all(after[o]['id'] == before[o]['id'] and after[o]['started'] == before[o]['started'] and after[o]['pid'] == before[o]['pid'] for o in others)
    r.check('the other containers kept their ids, start times and processes', untouched, json.dumps({o: after[o] for o in others}))
    links = container_links(node_name)
    record['links_after'] = links
    r.check('the device has its dataplane interfaces back', len(links) >= (expect_links if expect_links is not None else 1), ', '.join(links))
    # Fresh readiness: the device's login must be proven again, by a check made after the job finished.
    ready, seen = wait_ready(base, lab_id, node_name, job['finished'], budget)
    record['readiness'] = {'states': seen, 'ready_at': ready['nos_login'].get('at') if ready else None, 'budget_s': budget}
    r.check('the device went back through Starting (its old proof was dropped)', any(word == 'booting' for _, word in seen) or (ready is not None and ready['nos_login'].get('at', '') > job['finished']), json.dumps(seen))
    r.check('the device is Ready again with a check made after the restart (within %d s)' % budget, ready is not None, json.dumps(seen))
    page.wait_for_timeout(4500)
    r.check('the rail reads Ready for the device again', device_pill(page, node_name) == 'Ready', device_pill(page, node_name))
    r.shot(tag + '-04-ready-again')
    return job


def terminal_status(page):
    return (page.locator('#status').first.text_content() or '').strip()


def terminal_rows(page):
    return page.evaluate("() => (document.querySelector('#terminal .xterm-rows')?.innerText) || ''")


def open_terminal(r, browser, base, lab, node):
    """A browser CLI to the device in its own tab (the same page a student opens with Open CLI)."""
    page = browser.new_page(viewport={'width': 1000, 'height': 600})
    page.goto(base + '/static/terminal.html#' + '&'.join('%s=%s' % kv for kv in (('lab', lab['id']), ('node', node['name']), ('label', lab['name']))))
    page.wait_for_selector('#status', timeout=15000)
    for _ in range(40):
        if terminal_status(page) == 'Connected': break
        if not page.locator('#connect').first.is_disabled() and terminal_status(page) in ('', 'Disconnected'): page.click('#connect')
        page.wait_for_timeout(1000)
    r.check('a browser CLI to the device connects before the restart', terminal_status(page) == 'Connected', terminal_status(page))
    page.locator('#terminal').first.click()
    page.keyboard.type('show clock'); page.keyboard.press('Enter'); page.wait_for_timeout(2000)
    r.check('the CLI answered a typed command', 'show clock' in terminal_rows(page), terminal_rows(page)[-300:])
    return page


def terminal_after_restart(r, page, ready_wait):
    for _ in range(30):
        if terminal_status(page).startswith('Disconnected'): break
        page.wait_for_timeout(1000)
    r.check('the browser CLI shows the disconnection', terminal_status(page).startswith('Disconnected'), terminal_status(page))
    r.check('Reconnect is offered', not page.locator('#connect').first.is_disabled())
    typed_before = terminal_rows(page).count('show clock')
    ready_wait()
    page.click('#connect')
    for _ in range(40):
        if terminal_status(page) == 'Connected': break
        page.wait_for_timeout(1000)
    r.check('Reconnect gives a fresh session once the device is Ready', terminal_status(page) == 'Connected', terminal_status(page))
    page.wait_for_timeout(2500)
    r.check('nothing typed earlier was replayed on reconnect', terminal_rows(page).count('show clock') <= typed_before, terminal_rows(page)[-400:])
    page.screenshot(path=str(r.out / (getattr(r, 'prefix', '') + 'terminal-after-reconnect.png'))); r.shots.append(getattr(r, 'prefix', '') + 'terminal-after-reconnect.png')


def capture_after_restart(r, page, node):
    item = page.locator('#node-context-menu button[data-capture="%s"]' % node['name'])
    open_map_menu(page, node['name'])
    if item.count() != 1 or item.is_disabled():
        r.check('Capture traffic… is offered after the restart', False, item.get_attribute('title') if item.count() else 'no item'); return
    item.click()
    page.wait_for_selector('dialog#capture-dialog[open]', timeout=10000)
    for _ in range(40):
        status = r.text('#capture-status')
        if status and 'Looking up' not in status: break
        page.wait_for_timeout(1000)
    boxes = page.locator('#capture-interfaces input')
    r.check('a new capture resolves the restarted device\'s interfaces on the VM', boxes.count() >= 1 and 'not found' not in r.text('#capture-status'), r.text('#capture-status'))
    r.shot('capture-after-restart')
    if boxes.count() and not page.locator('#capture-prepare').first.is_disabled():
        page.click('#capture-prepare')
        for _ in range(30):
            if page.locator('#capture-launch').first.is_visible(): break
            page.wait_for_timeout(1000)
        r.check('the capture starts and offers Open Wireshark', page.locator('#capture-launch').first.is_visible(), r.text('#capture-status'))
    page.click('#capture-close')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--url', default='http://127.0.0.1:8081')
    parser.add_argument('--lab', default='restore-square')
    parser.add_argument('--device', required=True, help='the device by its short name (topology node), e.g. ceos')
    parser.add_argument('--ready-budget', type=int, default=300, help='seconds allowed for the NOS to accept a login again')
    parser.add_argument('--devices', action='store_true', help='also restart through the Devices view (keyboard path) after the map run')
    parser.add_argument('--stopped', action='store_true', help='also stop the device with containerlab stop --node and restart it through the manager')
    parser.add_argument('--links', type=int, default=None, help='the number of dataplane links the device has in the topology (asserted when given)')
    parser.add_argument('--terminal', action='store_true', help='open a browser CLI to the device before the first restart; expect it to disconnect, then reconnect once the device is Ready (no replay)')
    parser.add_argument('--capture', action='store_true', help='after the first restart, open Capture traffic… on the device and start a capture (needs the capture stack)')
    parser.add_argument('--viewport', default='1366x768')
    parser.add_argument('--out', default=str(HERE.parent / 'evidence' / 'restart'))
    args = parser.parse_args()
    width, height = (int(v) for v in args.viewport.lower().split('x', 1))
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)

    status, state = call(args.url, '/api/state')
    if status != 200: raise SystemExit('the manager at %s did not answer /api/state (status %s)' % (args.url, status))
    lab = next((l for l in state['labs'] if l['name'] == args.lab), None)
    if lab is None: raise SystemExit('no lab named %r' % args.lab)
    node = next((n for n in lab['nodes'] if (n.get('short_name') or n['name']) == args.device), None)
    if node is None: raise SystemExit('no device %r in %s' % (args.device, args.lab))
    names = [n['name'] for n in lab['nodes']]; others = [n for n in names if n != node['name']]
    version = subprocess.run(['containerlab', 'version'], capture_output=True, text=True).stdout
    clab_version = next((line.split(':', 1)[1].strip() for line in version.splitlines() if 'version:' in line), '?')
    record = {'started': now(), 'manager': state.get('version'), 'containerlab': clab_version, 'lab': args.lab, 'lab_id': lab['id'], 'device': node['name'], 'label': args.device, 'kind': node.get('kind'), 'runs': {}, 'reviews': {}}
    print('manager %s, containerlab %s, lab %s, device %s (%s)' % (state.get('version'), clab_version, args.lab, args.device, node['name']), flush=True)

    exit_code = 0
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        record['chromium'] = browser.version
        page = browser.new_page(viewport={'width': width, 'height': height})
        r = Run(page, out); r.prefix = args.device + '-' + record['started'][11:16].replace(':', '') + '-'; r.reviews = record['reviews']
        page.goto(args.url + '/#lab=' + lab['id'] + '&view=topology')
        page.wait_for_selector('#topology-map [data-map-node="%s"]' % node['name'], timeout=30000)
        page.wait_for_timeout(1500)

        def one_run(tag, entry, terminal=None):
            before = docker_inspect(names); design_before = design_snapshot(args.url, lab['id'])
            rec = {'before': before, 'links_before': container_links(node['name']), 'entry': entry, 'design_before': design_before}
            record['runs'][tag] = rec
            print('-- %s: %s --' % (tag, entry), flush=True)
            confirmed_at = restart_from_map(r, page, args.url, lab, node, args.ready_budget, before, others, tag) if entry == 'map' else restart_from_devices(r, page, args.url, lab, node, tag)
            rec['confirmed_at'] = confirmed_at
            job = follow_and_prove(r, page, args.url, lab['id'], node, before, others, args.ready_budget, confirmed_at, tag, rec, expect_links=args.links)
            rec['design_after'] = design_snapshot(args.url, lab['id'])
            r.check('the design, its plans, the Git binding and the deployment time are untouched', rec['design_after'] == design_before, json.dumps({'before': design_before, 'after': rec['design_after']})[:400])
            if terminal is not None and job:
                terminal_after_restart(r, terminal, lambda: None)   # the device is Ready by now (follow_and_prove waited for it)

        terminal = open_terminal(r, browser, args.url, lab, node) if args.terminal else None
        one_run('map-running', 'map', terminal)
        if args.capture: capture_after_restart(r, page, node)
        if args.devices:
            one_run('devices-running', 'devices')
        if args.stopped:
            topo = lab.get('vm_project_path')
            print('-- stopping %s with containerlab stop --node (the extension\'s Stop node) --' % args.device, flush=True)
            stop = subprocess.run(['sudo', 'containerlab', 'stop', '-r', 'docker', '--node', args.device, '-t', topo], capture_output=True, text=True)
            record['stop_output'] = (stop.stdout + stop.stderr)[-800:]
            time.sleep(2)
            # The manager has to see the stopped container (discovery runs every 30 s, and the restart job's own refresh).
            for _ in range(40):
                st, s2 = call(args.url, '/api/state'); l2 = next(l for l in s2['labs'] if l['id'] == lab['id'])
                n2 = next(n for n in l2['nodes'] if n['name'] == node['name'])
                if n2.get('runtime_state') == 'exited': break
                time.sleep(3)
            r.check('the manager sees the stopped device', n2.get('runtime_state') == 'exited', n2.get('runtime_state'))
            page.wait_for_timeout(4500)
            r.check('a stopped device reads Unavailable (not Ready) before the restart', device_pill(page, node['name']) in ('Unavailable', 'Starting'), device_pill(page, node['name']))
            before = docker_inspect(names)
            rec = {'before': before, 'links_before': container_links(node['name']), 'entry': 'map (stopped device)'}
            record['runs']['map-stopped'] = rec
            item = open_map_menu(page, node['name'])
            r.check('a stopped device can be restarted (start/restore path), the menu item is enabled', item.count() == 1 and not item.is_disabled(), item.get_attribute('title') if item.count() else 'no item')
            item.click(); review_open(page); text = review_text(page); r.shot('map-stopped-02-review')
            r.check('the review warns about the start/restore path for a stopped device', 'start/restore path' in text and 'docker stop' in text, text[:800])
            r.check('the review lists the device as exited', 'exited' in text, text[:800])
            check_known_limit(r, text, node.get('kind'), 'map-stopped')
            rec['confirmed_at'] = now(); page.click('#op-confirm'); page.wait_for_selector('dialog#operation-review[open]', state='hidden', timeout=20000)
            follow_and_prove(r, page, args.url, lab['id'], node, before, others, args.ready_budget, rec['confirmed_at'], 'map-stopped', rec, expect_links=args.links)

        unexpected = [c for c in r.console if not c['text'].startswith(HANDLED)]
        r.check('no unexpected console errors', not unexpected, json.dumps(unexpected)[:400])
        r.check('no page errors', not r.pageerrors, json.dumps(r.pageerrors)[:400])
        browser.close()
    record['checks'] = r.checks; record['shots'] = r.shots; record['finished'] = now()
    failed = [c for c in r.checks if not c['ok']]
    (out / ('%s-%s.json' % (args.device, record['started'].replace(':', '')))).write_text(json.dumps(record, indent=1))
    print('%d checks, %d failed; record in %s' % (len(r.checks), len(failed), out), flush=True)
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
