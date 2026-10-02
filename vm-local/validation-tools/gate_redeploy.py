"""Gate B/M/N live: edit the VM topology (correct cJunosEvolved port names), Sync topology from VM, Redeploy lab through the UI, watch Starting → Running."""
import json, os, sys, time, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from live_lib import *
pw, b, ctx, r = session('redeploy'); p = r.page
before = {c: subprocess.run(['sudo', '-n', 'docker', 'inspect', '-f', '{{.State.StartedAt}}', c], capture_output=True, text=True).stdout.strip() for c in ('clab-clab-llm-dev2-PTX1', 'clab-clab-llm-dev2-SW1')}; r.note('StartedAt before redeploy', before)
r.open_lab(); r.tab('advanced'); p.wait_for_timeout(500)
p.click('#sync-vm'); p.wait_for_timeout(4000)
sync = r.js('() => ({files: document.getElementById("vm-files-status").textContent, msg: document.getElementById("deployment-message").textContent, links: document.getElementById("map-status")?.textContent})'); r.note('after Sync topology from VM', sync)
r.tab('topology'); p.wait_for_timeout(800); titles = r.js('() => [...document.querySelectorAll("#topology-map .topology-wire title")].map(t => t.textContent)'); r.note('link titles after sync', titles)
r.check('N sync: Sync topology from VM picks up the edited links (et-0/0/0 / et-0/0/1 names)', any('et-0/0/0' in t for t in titles), titles); r.shot('B-after-sync')
p.click('#lab-actions-button'); p.wait_for_selector('#lab-actions-menu:not([hidden])'); p.click('#lab-actions-menu [data-op-action="redeploy"]'); p.wait_for_selector('#operation-review[open]', timeout=20000); p.wait_for_timeout(400)
rv = r.js('() => ({title: document.querySelector("#operation-review h2").textContent, text: document.getElementById("operation-review").textContent.replace(/\\s+/g," ").slice(0,700), confirm: document.getElementById("op-confirm").textContent, danger: document.getElementById("op-confirm").classList.contains("danger"), save: !!document.getElementById("op-save-first"), pre: document.querySelector("#operation-review details pre")?.textContent})'); r.note('redeploy review', rv)
r.check('M redeploy review: warns that unsaved changes are lost, shows the last save, offers Save progress first, raw command under Technical details', 'Configuration changes you have not saved are lost' in rv['text'] and 'Last saved' in rv['text'] and rv['save'] and 'redeploy' in (rv['pre'] or ''), rv); r.shot('M-redeploy-review', full=True)
p.click('#op-confirm'); p.wait_for_function('() => !document.getElementById("operation-review")?.open', timeout=20000)
p.wait_for_function('() => !document.getElementById("lab-banner").hidden', timeout=20000); ban = r.js('() => ({text: document.getElementById("lab-banner-text").textContent, output: !document.getElementById("banner-output").hidden, pill: document.getElementById("lab-state").textContent})'); r.note('banner after confirm', ban)
r.check('B redeploy: banner-first confirm names the operation with View output, no output window pops', 'edeploy' in ban['text'] and ban['output'], ban); r.shot('B-redeploying')
last = None; n = 0; t0 = time.time(); seen = []
while time.time() - t0 < 2100:
    s = p.evaluate('''() => ({state: document.getElementById("lab-state")?.textContent.trim(), ready: document.getElementById("lab-ready")?.textContent.trim(), banner: document.getElementById("lab-banner")?.hidden ? "" : document.getElementById("lab-banner-text")?.textContent.trim(),
        rows: [...document.querySelectorAll("#device-list .pill")].map(e => e.textContent.trim()), map: [...document.querySelectorAll("#topology-map .map-device")].map(e => [...e.classList].filter(c => c.startsWith("state-")).join(",")),
        cli: [...document.querySelectorAll("#device-list [data-terminal]")].map(b => b.disabled), start: document.getElementById("lab-start")?.disabled, startReason: document.querySelector("#lab-actions-menu [data-op-action=start] .menu-reason, #menu-start .menu-reason")?.textContent || "", busy: typeof busy === "function" ? busy() : null})''')
    key = json.dumps(s, sort_keys=True)
    if key != last:
        n += 1; seen.append({'t': round(time.time() - t0), **s}); r.note(f'STATE {n} at +{round(time.time()-t0)}s', s); p.screenshot(path=os.path.join(OUT, f'redeploy-transition-{n:02d}.png')); last = key
    if s['ready'] and s['ready'].startswith('2 of 2') and s['state'] in ('Running', 'Ready') and not s['busy']: break
    p.wait_for_timeout(15000)
states = [x['state'] for x in seen]; readies = [x['ready'] for x in seen]
r.check('B redeploy: the UI went through a running operation, Starting (0 of 2, 1 of 2) and back to Running 2 of 2 without a page reload', 'Starting' in states and any(x.startswith('1 of 2') for x in readies) and readies[-1].startswith('2 of 2'), {'states': states, 'readies': readies})
r.check('B redeploy: device rows and map dots changed individually (one Ready while the other still Starting)', any(x['rows'] == ['Ready', 'Starting'] or x['rows'] == ['Starting', 'Ready'] for x in seen) and any(sorted(x['map']) == ['state-ready', 'state-starting'] for x in seen), [(x['rows'], x['map']) for x in seen])
r.check('B redeploy: Open CLI enabled per device as it became ready', any(x['cli'] == [False, True] or x['cli'] == [True, False] for x in seen) and seen[-1]['cli'] == [False, False], [x['cli'] for x in seen])
after = {c: subprocess.run(['sudo', '-n', 'docker', 'inspect', '-f', '{{.State.StartedAt}}', c], capture_output=True, text=True).stdout.strip() for c in before}; r.note('StartedAt after redeploy', after)
r.check('B redeploy: containers were recreated by the real redeploy (StartedAt changed)', all(after[c] != before[c] for c in before), (before, after))
r.shot('B-running-again'); r.report('redeploy'); b.close(); pw.stop()
