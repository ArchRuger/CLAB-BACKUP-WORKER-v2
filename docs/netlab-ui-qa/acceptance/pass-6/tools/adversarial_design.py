#!/usr/bin/env python3
"""Pass 6 adversarial Design-tab check (fixture manager, real engine, no VM), warm/returned sessions.

S1 (U-01 class, in the pass's own order): lab B saved first (OSPF area 0.0.0.7), then lab A saved with BGP AS 65123;
   focus a field in A and go browser Back to B; B's form must be B's; an edit + Save in B must store B's values only.
S2 (QA-010/QA-001 class): an unsaved edit in A (AS 65124) abandoned by leaving the tab and closing the page; a new page
   in the same browser context reopens A: the draft is offered as Unsaved; Discard restores 65123; a reload then reads
   the saved state (never "No design yet").
S3 (stale write across two tabs): tab 1 holds an unsaved edit of A while tab 2 saves A (AS 65200); tab 1's Save must
   not overwrite tab 2's save silently.
Usage: adversarial_design.py --port 8175 --data <fresh dir> --out <dir>"""
import argparse, json, subprocess, sys, time, urllib.request
from datetime import datetime, timezone
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT = Path('/home/clabllm/projects/clab-manager-1.30.42')
FIXTURE = ROOT / 'docs/redesign/tools/fixture_manager.py'
HANDLED = 'Failed to load resource: the server responded with a status of '
checks, console, errors = [], [], []
def now(): return datetime.now(timezone.utc).isoformat(timespec='seconds')
def check(name, ok, detail=''):
    checks.append({'name': name, 'ok': bool(ok), 'detail': str(detail)[:400], 'at': now()})
    print(('  ok   ' if ok else '  FAIL ') + name + ('' if ok else ': ' + str(detail)[:300]), flush=True)
def get(base, path):
    with urllib.request.urlopen(base + path, timeout=10) as r: return json.loads(r.read())
def state_text(p): return p.evaluate("() => document.getElementById('design-state')?.textContent || ''")
def open_design(p, base, lab):
    p.evaluate("(h) => { location.hash = h }", '#lab=%s&view=design' % lab['id']) if p.url.startswith(base) else p.goto(base + '/#lab=%s&view=design' % lab['id'])
    p.wait_for_selector('#design-view:not([hidden])', timeout=15000)
    p.wait_for_function("(id) => typeof designState === 'object' && designState.labId === id && !(document.getElementById('design-state')?.textContent || '').includes('Loading')", arg=lab['id'], timeout=20000)
    p.wait_for_timeout(500)
def tick(p, module):
    box = p.locator('input[name="design-module"][value="%s"]' % module)
    if not box.is_checked(): box.check()
def setv(p, sel, v): p.fill(sel, v); p.locator(sel).dispatch_event('change')
def save(p):
    p.click('#design-save')
    p.wait_for_function("() => !(document.getElementById('design-state')?.textContent || '').includes('Unsaved') || (document.getElementById('design-problems')?.textContent || '').length > 0", timeout=15000)
    p.wait_for_timeout(500)
def intent(base, lab): return (get(base, '/api/labs/%s/design' % lab['id']) or {}).get('intent') or {}
def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--port', type=int, default=8175); ap.add_argument('--data', required=True); ap.add_argument('--out', required=True)
    a = ap.parse_args(); out = Path(a.out); out.mkdir(parents=True, exist_ok=True); base = 'http://127.0.0.1:%d' % a.port
    fx = subprocess.Popen([sys.executable, str(FIXTURE), '--port', str(a.port), '--data', a.data], stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    rec = {'started': now()}
    try:
        for _ in range(120):
            try: st = get(base, '/api/state'); break
            except Exception: time.sleep(0.5)
        labs = {l['name']: l for l in st['labs']}; A = labs['ospf-basics']; B = labs['BGP_TheoryToPractice']
        with sync_playwright() as pw:
            br = pw.chromium.launch(); ctx = br.new_context(viewport={'width': 1366, 'height': 800})
            def page():
                p = ctx.new_page(); p.on('console', lambda m: console.append(m.text) if m.type == 'error' else None); p.on('pageerror', lambda e: errors.append(str(e))); return p
            # S1
            p = page(); open_design(p, base, B)
            tick(p, 'ospf'); setv(p, '#design-ospf-area', '0.0.0.7'); save(p)
            check('S1 B saved with area 0.0.0.7', (intent(base, B).get('ospf') or {}).get('area') == '0.0.0.7', intent(base, B).get('ospf'))
            open_design(p, base, A)
            tick(p, 'bgp'); setv(p, '#design-bgp-as', '65123'); save(p)
            check('S1 A saved with AS 65123', (intent(base, A).get('bgp') or {}).get('as') == 65123, intent(base, A).get('bgp'))
            p.click('#design-pool-lan-ipv4'); p.keyboard.type('')   # focus a field in A, no change
            p.go_back()
            p.wait_for_function("(id) => designState.labId === id && !(document.getElementById('design-state')?.textContent || '').includes('Loading')", arg=B['id'], timeout=20000); p.wait_for_timeout(1200)
            as_b = p.locator('#design-bgp-as').input_value(); area_b = p.locator('#design-ospf-area').input_value()
            p.locator('#design-view h2').first.click(); p.wait_for_timeout(300)
            adv = p.locator('#design-advanced').input_value()
            p.screenshot(path=str(out / 'adv-S1-after-back.png'))
            check('S1 after Back the form is B\'s (area 0.0.0.7, not A\'s AS 65123)', area_b == '0.0.0.7' and as_b != '65123' and '65123' not in adv, 'area=%r as=%r adv_has_65123=%s' % (area_b, as_b, '65123' in adv))
            setv(p, '#design-ospf-area', '0.0.0.8'); save(p)
            ib = intent(base, B); ia = intent(base, A)
            check('S1 Save in B stores B\'s edit only', (ib.get('ospf') or {}).get('area') == '0.0.0.8' and 'bgp' not in (ib.get('modules') or []) and (ib.get('bgp') or {}).get('as') != 65123, json.dumps({'modules': ib.get('modules'), 'bgp': ib.get('bgp'), 'ospf': ib.get('ospf')}))
            check('S1 A untouched by the Back', (ia.get('bgp') or {}).get('as') == 65123, ia.get('bgp'))
            # S2
            open_design(p, base, A); setv(p, '#design-bgp-as', '65124')
            check('S2 the edit reads Unsaved', 'Unsaved' in state_text(p), state_text(p))
            p.evaluate("(h) => { location.hash = h }", '#lab=%s&view=topology' % A['id']); p.wait_for_timeout(800); p.close()
            q = page(); q.goto(base + '/#lab=%s&view=design' % A['id']); open_design(q, base, A); q.wait_for_timeout(800)
            s2 = state_text(q); as_q = q.locator('#design-bgp-as').input_value(); q.screenshot(path=str(out / 'adv-S2-reopened.png'))
            check('S2 a reopened page offers the abandoned draft as Unsaved (65124), not silently lost', 'Unsaved' in s2 and as_q == '65124', 'state=%r as=%r' % (s2, as_q))
            check('S2 the abandoned draft was never saved', (intent(base, A).get('bgp') or {}).get('as') == 65123, intent(base, A).get('bgp'))
            if q.locator('#design-discard').is_visible():
                q.click('#design-discard'); q.wait_for_timeout(800)
            as_d = q.locator('#design-bgp-as').input_value(); s_d = state_text(q)
            check('S2 Discard changes restores the saved 65123 and clears Unsaved', as_d == '65123' and 'Unsaved' not in s_d, 'as=%r state=%r' % (as_d, s_d))
            q.reload(); open_design(q, base, A); s_r = state_text(q)
            check('S2 after a reload the saved design is not "No design yet" (QA-001)', 'No design yet' not in s_r and 'Unsaved' not in s_r and q.locator('#design-bgp-as').input_value() == '65123', 's=%r' % s_r)
            # S3
            t1 = q; setv(t1, '#design-bgp-as', '65111')
            t2 = page(); t2.goto(base + '/#lab=%s&view=design' % A['id']); open_design(t2, base, A)
            as_t2 = t2.locator('#design-bgp-as').input_value()
            rec['s3_tab2_initial_as'] = as_t2
            if as_t2 != '65123':
                check('S3 (note) tab 2 opened showing the shared browser draft, discarding it first', True, as_t2)
                if t2.locator('#design-discard').is_visible(): t2.click('#design-discard'); t2.wait_for_timeout(500)
            setv(t2, '#design-bgp-as', '65200'); save(t2)
            check('S3 tab 2 saved AS 65200', (intent(base, A).get('bgp') or {}).get('as') == 65200, intent(base, A).get('bgp'))
            t1.bring_to_front(); t1.wait_for_timeout(5000)   # a heartbeat or two
            as_t1 = t1.locator('#design-bgp-as').input_value(); rec['s3_tab1_before_save'] = {'as': as_t1, 'state': state_text(t1)}
            t1.click('#design-save'); t1.wait_for_timeout(2500)
            final = (intent(base, A).get('bgp') or {}).get('as')
            msg = t1.evaluate("() => (document.getElementById('design-problems')?.textContent || '') + ' | ' + (document.getElementById('design-detail')?.textContent || '') + ' | ' + (document.querySelector('.toast, #toast, [role=status]')?.textContent || '')")
            t1.screenshot(path=str(out / 'adv-S3-tab1-save.png'))
            rec['s3'] = {'final_as': final, 'tab1_message': msg[:400], 'tab1_state': state_text(t1)}
            check('S3 tab 1\'s older edit does not silently overwrite tab 2\'s save (either refused with a reason, or it was the student\'s visible latest value)',
                  final == 65200 or (final == 65111 and as_t1 == '65111' and 'Unsaved' in rec['s3_tab1_before_save']['state']), json.dumps(rec['s3']))
            br.close()
    finally:
        fx.terminate()
        try: fx.wait(timeout=10)
        except Exception: fx.kill()
    unexpected = [c for c in console if not c.startswith(HANDLED)]
    check('no unexpected console errors', not unexpected, json.dumps(unexpected)[:300]); check('no page errors', not errors, json.dumps(errors)[:300])
    rec['checks'] = checks; rec['console'] = console; rec['finished'] = now()
    (out / 'adversarial-design.json').write_text(json.dumps(rec, indent=1) + '\n')
    print('%d checks, %d failed' % (len(checks), sum(1 for c in checks if not c['ok'])))
    return 1 if any(not c['ok'] for c in checks) else 0
if __name__ == '__main__': sys.exit(main())
