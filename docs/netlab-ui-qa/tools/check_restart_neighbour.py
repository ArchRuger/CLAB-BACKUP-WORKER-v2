#!/usr/bin/env python3
"""QA-018 live check: a Restart device review names a neighbour whose container is not running and says what
that means for the link between them, and the job reports how many of the device's links containerlab restored.

Against the deployed product (real VM, real lab), in one of two modes:

  --stop-mode containerlab (default): the neighbour is stopped with containerlab's own `stop --node` (the
      extension's *Stop node*), which parks its link ends. Expected: the review names the neighbour and the two
      cases; the restart restores every link of the device (m links restored); the neighbour started again
      through the product (start/restore path) gets its own links back.
  --stop-mode docker: the neighbour is stopped with `docker stop`, which destroys its links. Expected: the same
      review; the job reads `n of m links restored (no link to <neighbour>: not running, its link was gone …)`;
      the device has one link fewer; the neighbour started through the product reads `no links restored` and
      has no dataplane links (the way out is a redeploy, which this check does not run).

    PATH="$PWD/clab-backup-ui/.venv/bin:$PATH" clab-backup-ui/.venv/bin/python docs/netlab-ui-qa/tools/check_restart_neighbour.py \\
        --url http://127.0.0.1:8081 --lab restore-square --device ceos --neighbour host1 --links 3 --neighbour-links 2 [--stop-mode docker]
"""
import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_restart_device import (Run, call, container_links, docker_inspect, follow_job, newest_job, now,  # noqa: E402
                                  open_map_menu, review_open, review_text, wait_ready)
from playwright.sync_api import sync_playwright  # noqa: E402


def dataplane(links):
    """Only the veth ends containerlab manages (`eth<n>@if<m>`): cEOS adds cpu, fabric and mirror interfaces of its own
    a little after it starts, and they must not count as links."""
    return [l for l in links if re.match(r'eth\d+@', l)]


def lab_state(base, lab_name):
    status, state = call(base, '/api/state')
    if status != 200: raise SystemExit('manager not reachable at ' + base)
    lab = next((l for l in state['labs'] if l['name'] == lab_name), None)
    if lab is None: raise SystemExit('no lab %r' % lab_name)
    return state, lab


def node_of(lab, short):
    node = next((n for n in lab['nodes'] if (n.get('short_name') or n['name']) == short), None)
    if node is None: raise SystemExit('no device %r in %s' % (short, lab['name']))
    return node


def wait_state(base, lab_name, short, wanted, budget):
    deadline = time.monotonic() + budget
    while time.monotonic() < deadline:
        _, lab = lab_state(base, lab_name)
        node = node_of(lab, short)
        if node.get('runtime_state') == wanted: return node
        time.sleep(3)
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--url', default='http://127.0.0.1:8081')
    parser.add_argument('--lab', default='restore-square')
    parser.add_argument('--device', default='ceos', help='the device to restart (short name)')
    parser.add_argument('--neighbour', default='host1', help='its neighbour to stop first (short name)')
    parser.add_argument('--links', type=int, default=3, help='dataplane links of the device in the topology')
    parser.add_argument('--neighbour-links', type=int, default=2, help='dataplane links of the neighbour in the topology')
    parser.add_argument('--ready-budget', type=int, default=300)
    parser.add_argument('--stop-mode', choices=['containerlab', 'docker'], default='containerlab')
    parser.add_argument('--out', default=str(Path(__file__).resolve().parents[1] / 'evidence' / 'restart'))
    args = parser.parse_args()
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    state, lab = lab_state(args.url, args.lab)
    node = node_of(lab, args.device); neighbour = node_of(lab, args.neighbour)
    topology = lab.get('vm_project_path') or ''
    record = {'started': now(), 'manager': state.get('version'), 'lab': args.lab, 'lab_id': lab['id'], 'device': node['name'],
              'neighbour': neighbour['name'], 'kind': node.get('kind'), 'stop_mode': args.stop_mode, 'steps': {}, 'reviews': {}}
    names = [n['name'] for n in lab['nodes']]
    print('manager %s, lab %s, device %s, neighbour %s' % (state.get('version'), args.lab, args.device, args.neighbour), flush=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(); record['chromium'] = browser.version
        page = browser.new_page(viewport={'width': 1366, 'height': 768})
        r = Run(page, out); r.prefix = 'neighbour-' + args.stop_mode + '-' + args.device + '-' + record['started'][11:16].replace(':', '') + '-'; r.reviews = record['reviews']
        page.goto(args.url + '/#lab=' + lab['id'] + '&view=topology')
        page.wait_for_selector('#topology-map [data-map-node="%s"]' % node['name'], timeout=30000); page.wait_for_timeout(1500)
        # 1. The neighbour stops the way the extension stops a node (its links are parked by containerlab).
        parked = args.stop_mode == 'containerlab'
        stop_cmd = ['sudo', 'containerlab', 'stop', '-t', topology, '--node', args.neighbour] if parked else ['docker', 'stop', neighbour['name']]
        stop = subprocess.run(stop_cmd, capture_output=True, text=True)
        record['steps']['stop_neighbour'] = {'mode': args.stop_mode, 'exit': stop.returncode, 'output': (stop.stdout + stop.stderr)[-800:]}
        r.check('the neighbour was stopped with ' + ('containerlab stop --node (links parked)' if parked else 'docker stop (links destroyed)'), stop.returncode == 0, (stop.stdout + stop.stderr)[-300:])
        seen = wait_state(args.url, args.lab, args.neighbour, 'exited', 120)
        r.check('the manager lists the neighbour as exited', seen is not None, seen and seen.get('runtime_status'))
        before = docker_inspect(names); record['steps']['before'] = before
        # 2. The review of the device names the neighbour and the consequence.
        item = open_map_menu(page, node['name']); r.shot('01-map-menu'); item.click(); review_open(page); text = review_text(page); r.shot('02-review')
        r.reviews['device'] = text[:2000]
        expected_words = '%s is not running. If it was stopped by the manager, the VS Code extension or containerlab stop, its link to %s is parked and comes back' % (args.neighbour, args.device)
        r.check('the review names the neighbour that is not running and the parked case', expected_words in text, text[:900])
        r.check('the review names the destroyed case with the count', ('containerlab restores only %d of %d links and the job says so' % (args.links - 1, args.links)) in text, text[:900])
        r.check('the review says the device waits for its interfaces and how to proceed', 'waits for all its interfaces before it boots (cEOS gives up waiting after five minutes, a VM-based image waits for good)' in text and ('Start %s first' % args.neighbour) in text, text[:900])
        status, preview = call(args.url, '/api/operations/preview', 'POST', {'action': 'restart-node', 'lab_id': lab['id'], 'node': node['name']})
        r.check('the API preview carries the same warning', status == 200 and any(expected_words in w for w in preview.get('warnings') or []), (status, (preview.get('warnings') or [])[:3]))
        # 3. Confirm: the job counts the links.
        confirmed_at = now(); page.click('#op-confirm'); page.wait_for_selector('dialog#operation-review[open]', state='hidden', timeout=20000)
        job = None
        for _ in range(60):
            job = newest_job(args.url, lab['id'], node['name'])
            if job and job.get('created', '') >= confirmed_at: break
            time.sleep(1)
        r.check('one Restart device job exists for the device', bool(job) and job.get('created', '') >= confirmed_at, job and job.get('id'))
        job = follow_job(args.url, job['id']) if job else None
        record['steps']['job'] = {k: job.get(k) for k in ('id', 'status', 'message', 'created', 'finished', 'exit_code', 'links_expected', 'neighbours_down')} if job else None
        r.check('the job succeeded (containerlab restored what it could)', bool(job) and job.get('status') == 'succeeded', job and job.get('message'))
        if parked:
            wanted = '%d links restored' % args.links
            r.check('the job message counts every link (the parked link came back)', bool(job) and wanted in (job.get('message') or '') and ' of ' not in (job.get('message') or ''), job and job.get('message'))
        else:
            wanted = '%d of %d links restored (no link to %s: not running, its link was gone; the device waits for it before it boots)' % (args.links - 1, args.links, args.neighbour)
            r.check('the job message reports n of m links and names the neighbour', bool(job) and wanted in (job.get('message') or ''), job and job.get('message'))
        after = docker_inspect(names); record['steps']['after'] = after
        r.check('the target kept its container id', before[node['name']]['id'] == after[node['name']]['id'], (before[node['name']]['id'], after[node['name']]['id']))
        links_now = dataplane(container_links(node['name'])); record['steps']['device_links_after'] = links_now
        r.check('the device has ' + ('all its dataplane links' if parked else 'one dataplane link fewer than its topology says'), len(links_now) == (args.links if parked else args.links - 1), links_now)
        ready, seen = wait_ready(args.url, lab['id'], node['name'], confirmed_at, args.ready_budget); record['steps']['readiness'] = seen
        r.check('the device is Ready again' + ('' if parked else ' (cEOS boots after the five minutes containerlab gives a missing interface)'), ready is not None, seen)
        r.shot('03-after-restart')
        # 4. The way out the review named: start the neighbour through the product (start/restore path).
        item = open_map_menu(page, neighbour['name']); r.check('Restart device… is offered for the exited neighbour', item.count() == 1 and not item.is_disabled())
        item.click(); review_open(page); text = review_text(page); r.reviews['neighbour'] = text[:2000]; r.shot('04-neighbour-review')
        r.check('the neighbour review takes the start/restore path', 'start/restore path' in text and 'exited' in text, text[:800])
        confirmed_at = now(); page.click('#op-confirm'); page.wait_for_selector('dialog#operation-review[open]', state='hidden', timeout=20000)
        job2 = None
        for _ in range(60):
            job2 = newest_job(args.url, lab['id'], neighbour['name'])
            if job2 and job2.get('created', '') >= confirmed_at: break
            time.sleep(1)
        job2 = follow_job(args.url, job2['id']) if job2 else None
        record['steps']['neighbour_job'] = {k: job2.get(k) for k in ('id', 'status', 'message', 'created', 'finished', 'exit_code')} if job2 else None
        r.check('the neighbour started again through the product', bool(job2) and job2.get('status') == 'succeeded', job2 and job2.get('message'))
        time.sleep(5)
        record['steps']['neighbour_links_after'] = dataplane(container_links(neighbour['name'])); record['steps']['device_links_final'] = dataplane(container_links(node['name']))
        if parked:
            r.check('the neighbour job counts its own links', bool(job2) and ('%d links restored' % args.neighbour_links) in (job2.get('message') or ''), job2 and job2.get('message'))
            r.check('the neighbour has its dataplane links back', len(record['steps']['neighbour_links_after']) == args.neighbour_links, record['steps']['neighbour_links_after'])
            r.check('the device has all its links once the neighbour runs', len(record['steps']['device_links_final']) == args.links, record['steps']['device_links_final'])
        else:
            r.check('the neighbour job says no links were restored and names the way out', bool(job2) and 'no links restored' in (job2.get('message') or '') and 'redeploy the lab' in (job2.get('message') or ''), job2 and job2.get('message'))
            r.check('the neighbour has no dataplane links (docker stop destroyed them; a redeploy is the way out)', len(record['steps']['neighbour_links_after']) == 0, record['steps']['neighbour_links_after'])
            r.check('the device still lacks the destroyed link', len(record['steps']['device_links_final']) == args.links - 1, record['steps']['device_links_final'])
        r.shot('05-neighbour-back')
        r.check('no unexpected console errors', not r.console, json.dumps(r.console)[:300]); r.check('no page errors', not r.pageerrors, json.dumps(r.pageerrors)[:300])
        browser.close()
    record['finished'] = now(); record['checks'] = r.checks; record['shots'] = r.shots
    failed = [c for c in r.checks if not c['ok']]
    path = out / ('neighbour-%s-%s-%s.json' % (args.device, args.stop_mode, record['started'].replace(':', '').replace('-', '')))
    path.write_text(json.dumps(record, indent=1))
    print('%d checks, %d failed; record %s' % (len(r.checks), len(failed), path), flush=True)
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
