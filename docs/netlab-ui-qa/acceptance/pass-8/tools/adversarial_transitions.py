#!/usr/bin/env python3
"""Pass 8 adversarial Design-tab check (fixture manager, real netlab engine, no VM): transitions pass 6 did not cover.

T1 (wrong-lab write, P0 class): both labs carry the same saved design (same content, so the same content-hash
   revision). The student opens lab A's Design tab, opens More > Remove design..., and the browser goes Back to lab B
   (history navigation with the dialog open). What does the dialog say, which lab is shown, and if the student
   confirms, which lab loses its design, and is the student told?
T1b the same with Renumber (Forget allocations) and different revisions: must be refused with a reason, nothing changed.
T2 reload in the middle of a generation (BGP_TheoryToPractice, 13 devices): the reopened page must pick up the
   running generation and reach "Plan ready to review" with no second generation started.
T3 lab switched under an open Design tab while a generation runs, then Back: B shows nothing of A's generation,
   A shows its finished plan.
Usage: adversarial_transitions.py --port 8195 --data <fresh dir> --out <dir>"""
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
    checks.append({'name': name, 'ok': bool(ok), 'detail': str(detail)[:600], 'at': now()})
    print(('  ok   ' if ok else '  FAIL ') + name + ('' if ok else ': ' + str(detail)[:400]), flush=True)
def req(base, method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(base + path, data=data, method=method, headers={'Content-Type': 'application/json', 'Origin': base})
    try:
        with urllib.request.urlopen(r, timeout=20) as resp: return resp.status, json.loads(resp.read() or b'null')
    except urllib.error.HTTPError as e: return e.code, json.loads(e.read() or b'null')
def design(base, lab): return req(base, 'GET', '/api/labs/%s/design' % lab['id'])[1] or {}
def intent(base, lab): return design(base, lab).get('intent') or None
def state_text(p): return p.evaluate("() => document.getElementById('design-state')?.textContent || ''")
def open_design(p, base, lab):
    if p.url.startswith(base): p.evaluate("(h) => { location.hash = h }", '#lab=%s&view=design' % lab['id'])
    else: p.goto(base + '/#lab=%s&view=design' % lab['id'])
    p.wait_for_selector('#design-view:not([hidden])', timeout=15000)
    p.wait_for_function("(id) => typeof designState === 'object' && designState.labId === id && !(document.getElementById('design-state')?.textContent || '').includes('Loading')", arg=lab['id'], timeout=20000)
    p.wait_for_timeout(600)
def shown_lab(p): return p.evaluate("() => ({active: typeof activeId==='string'?activeId:'', designLab: designState.labId, hash: location.hash})")
def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--port', type=int, default=8195); ap.add_argument('--data', required=True); ap.add_argument('--out', required=True)
    a = ap.parse_args(); out = Path(a.out); out.mkdir(parents=True, exist_ok=True); base = 'http://127.0.0.1:%d' % a.port
    fx = subprocess.Popen([sys.executable, str(FIXTURE), '--port', str(a.port), '--data', a.data], stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    rec = {'started': now()}
    try:
        for _ in range(120):
            try: st = req(base, 'GET', '/api/state')[1]; break
            except Exception: time.sleep(0.5)
        labs = {l['name']: l for l in st['labs']}; A = labs['ospf-basics']; B = labs['BGP_TheoryToPractice']
        rec['labs'] = {'A': [A['id'], A['name']], 'B': [B['id'], B['name']]}
        same = {'schema': 1, 'label': '', 'families': {'ipv4': True, 'ipv6': False},
                'addressing': {'loopback': {'ipv4': '10.255.0.0/24'}, 'p2p': {'ipv4': '10.1.0.0/16', 'prefix': 31}, 'lan': {'ipv4': '172.16.0.0/16', 'prefix': 24}},
                'modules': ['ospf'], 'nodes': {}, 'links': {}, 'vlans': {}, 'vrfs': {}, 'interfaces': {}}
        sa = req(base, 'PUT', '/api/labs/%s/design' % A['id'], {'intent': same, 'revision': ''})
        sb = req(base, 'PUT', '/api/labs/%s/design' % B['id'], {'intent': same, 'revision': ''})
        ra, rb = (intent(base, A) or {}).get('revision'), (intent(base, B) or {}).get('revision')
        rec['t1_setup'] = {'put_a': sa[0], 'put_b': sb[0], 'rev_a': ra, 'rev_b': rb}
        check('T1 setup: both labs saved the same design (same revision)', sa[0] == 200 and sb[0] == 200 and ra and ra == rb, rec['t1_setup'])
        with sync_playwright() as pw:
            br = pw.chromium.launch(); ctx = br.new_context(viewport={'width': 1366, 'height': 800})
            def page():
                p = ctx.new_page(); p.on('console', lambda m: console.append(m.text) if m.type == 'error' else None); p.on('pageerror', lambda e: errors.append(str(e))); return p
            p = page()
            # history: B first, then A (so Back leads to B)
            open_design(p, base, B)
            p.click('#lab-switcher summary') if p.locator('#lab-switcher summary').count() else None
            p.keyboard.press('Escape')
            p.evaluate("(id) => selectLab(id, 'design')", A['id']) if False else None
            open_design(p, base, A)
            # T1: Remove design dialog in A, then browser Back
            p.click('#design-more-button'); p.click('#design-clear')
            p.wait_for_selector('#design-clear-dialog[open]', timeout=5000)
            before = shown_lab(p); rec['t1_before_back'] = before
            p.screenshot(path=str(out / 'adv8-T1-1-dialog-in-A.png'))
            p.go_back(); p.wait_for_timeout(2500)
            after = shown_lab(p); still_open = p.evaluate("() => !!document.getElementById('design-clear-dialog')?.open")
            head = p.evaluate("() => document.querySelector('header h1, #lab-title, .lab-title')?.textContent || ''")
            rec['t1_after_back'] = {'shown': after, 'dialog_open': still_open, 'heading': head.strip()[:120]}
            p.screenshot(path=str(out / 'adv8-T1-2-after-back.png'))
            check('T1 Back from A reached lab B', after['active'] == B['id'], after)
            check('T1 the Remove design dialog opened for A does not stay open over lab B', not still_open, rec['t1_after_back'])
            if still_open:
                p.click('#design-clear-run'); p.wait_for_timeout(2500)
                ia, ib = intent(base, A), intent(base, B)
                msg = p.evaluate("() => (document.querySelector('#design-clear-dialog .form-error')?.textContent || '') + ' | toast: ' + (document.querySelector('#toast, .toast, #notify')?.textContent || '')")
                rec['t1_after_confirm'] = {'a_present': bool(ia), 'b_present': bool(ib), 'dialog_open': p.evaluate("() => !!document.getElementById('design-clear-dialog')?.open"),
                                           'page_lab': shown_lab(p), 'b_state_text': state_text(p), 'message': msg[:300]}
                p.screenshot(path=str(out / 'adv8-T1-3-after-confirm.png'))
                check('T1 confirming the dialog shown over B does not remove a design the page does not show without saying so',
                      not (ib and not ia and 'removed' not in msg.lower()), rec['t1_after_confirm'])
                p.keyboard.press('Escape')
            # restore both designs for T1b
            if not intent(base, A): req(base, 'PUT', '/api/labs/%s/design' % A['id'], {'intent': same, 'revision': ''})
            other = dict(same); other['addressing'] = dict(same['addressing']); other['addressing']['loopback'] = {'ipv4': '10.254.0.0/24'}
            cur_b = (intent(base, B) or {}).get('revision', '')
            req(base, 'PUT', '/api/labs/%s/design' % B['id'], {'intent': other, 'revision': cur_b})
            rec['t1b_revisions'] = {'a': (intent(base, A) or {}).get('revision'), 'b': (intent(base, B) or {}).get('revision')}
            # T1b: Renumber dialog in A, Back to B, confirm: different revisions
            q = page(); open_design(q, base, B); open_design(q, base, A)
            q.click('#design-more-button'); q.click('#design-renumber'); q.wait_for_selector('#design-renumber-dialog[open]', timeout=5000)
            q.go_back(); q.wait_for_timeout(2500)
            open_after = q.evaluate("() => !!document.getElementById('design-renumber-dialog')?.open")
            rec['t1b_after_back'] = {'shown': shown_lab(q), 'dialog_open': open_after}
            if open_after:
                ia0, ib0 = intent(base, A), intent(base, B)
                q.click('#design-renumber-run'); q.wait_for_timeout(2500)
                err = q.evaluate("() => document.querySelector('#design-renumber-dialog .form-error')?.textContent || ''")
                ia1, ib1 = intent(base, A), intent(base, B)
                rec['t1b_after_confirm'] = {'error': err, 'a_unchanged': ia0 == ia1, 'b_unchanged': ib0 == ib1}
                q.screenshot(path=str(out / 'adv8-T1b-after-confirm.png'))
                check('T1b Renumber confirmed over B after Back (revisions differ) is refused with a reason and changes neither lab',
                      bool(err.strip()) and ia0 == ia1 and ib0 == ib1, rec['t1b_after_confirm'])
                q.keyboard.press('Escape')
            else:
                check('T1b the Renumber dialog closed on Back', True, rec['t1b_after_back'])
            q.close()
            # T2: reload in the middle of a generation of B
            r = page(); open_design(r, base, B)
            gens0 = len(design(base, B).get('generations') or [])
            r.click('#design-generate')
            r.wait_for_function("() => /Generating|Waiting/.test(document.getElementById('design-state')?.textContent || '')", timeout=15000)
            mid = state_text(r); rec['t2_before_reload'] = mid
            r.reload(); r.wait_for_selector('#design-view:not([hidden])', timeout=15000)
            r.wait_for_timeout(800); after_reload = state_text(r); rec['t2_after_reload'] = after_reload
            r.screenshot(path=str(out / 'adv8-T2-1-after-reload.png'))
            try:
                r.wait_for_function("() => /Plan ready to review/.test(document.getElementById('design-state')?.textContent || '')", timeout=180000); reached = True
            except Exception: reached = False
            gens1 = design(base, B).get('generations') or []
            rec['t2_final'] = {'state': state_text(r), 'generations_before': gens0, 'generations_after': len(gens1), 'newest': (gens1[-1] if gens1 else {}).get('status')}
            r.screenshot(path=str(out / 'adv8-T2-2-final.png'))
            check('T2 after a reload mid-generation the page shows the running generation (not "No plan"/idle)', bool(__import__('re').search('Generating|Waiting', after_reload)) or 'Plan ready' in after_reload, after_reload)
            check('T2 the reloaded page reaches "Plan ready to review" by itself', reached, rec['t2_final'])
            check('T2 exactly one new generation (the reload started none)', len(gens1) == gens0 + 1, rec['t2_final'])
            # T3: generate in B, switch to A under the open tab, then Back
            open_design(r, base, B)
            # make the design differ so the plan is stale and Generate is allowed again
            curb = (intent(base, B) or {}).get('revision', '')
            third = dict(other); third['addressing'] = dict(other['addressing']); third['addressing']['loopback'] = {'ipv4': '10.253.0.0/24'}
            req(base, 'PUT', '/api/labs/%s/design' % B['id'], {'intent': third, 'revision': curb})
            r.reload(); open_design(r, base, B)
            gens0 = len(design(base, B).get('generations') or [])
            r.click('#design-generate')
            r.wait_for_function("() => /Generating|Waiting/.test(document.getElementById('design-state')?.textContent || '')", timeout=15000)
            r.evaluate("(h) => { location.hash = h }", '#lab=%s&view=design' % A['id'])
            r.wait_for_function("(id) => designState.labId === id && !(document.getElementById('design-state')?.textContent || '').includes('Loading')", arg=A['id'], timeout=20000)
            r.wait_for_timeout(1500)
            in_a = state_text(r); gens_a = len(design(base, A).get('generations') or [])
            rec['t3_in_a'] = {'state': in_a, 'a_generations': gens_a}
            r.screenshot(path=str(out / 'adv8-T3-1-in-A.png'))
            check('T3 lab A shows nothing of B\'s running generation', 'Generating' not in in_a and gens_a == 0, rec['t3_in_a'])
            r.wait_for_timeout(4000); in_a2 = state_text(r)
            check('T3 lab A still shows its own state after B\'s poll would have fired', 'Generating' not in in_a2 and 'Plan ready' not in in_a2, in_a2)
            r.go_back()
            try:
                r.wait_for_function("(id) => designState.labId === id && /Plan ready to review/.test(document.getElementById('design-state')?.textContent || '')", arg=B['id'], timeout=180000); back_ok = True
            except Exception: back_ok = False
            g = design(base, B).get('generations') or []
            rec['t3_back_in_b'] = {'state': state_text(r), 'generations': len(g), 'before': gens0}
            r.screenshot(path=str(out / 'adv8-T3-2-back-in-B.png'))
            check('T3 Back to B shows its finished plan, one new generation', back_ok and len(g) == gens0 + 1, rec['t3_back_in_b'])
            br.close()
    finally:
        fx.terminate()
        try: fx.wait(timeout=10)
        except Exception: fx.kill()
    unexpected = [c for c in console if not c.startswith(HANDLED)]
    check('no unexpected console errors', not unexpected, json.dumps(unexpected)[:300]); check('no page errors', not errors, json.dumps(errors)[:300])
    rec['checks'] = checks; rec['console'] = console; rec['finished'] = now()
    (out / 'adversarial-transitions.json').write_text(json.dumps(rec, indent=1) + '\n')
    print('%d checks, %d failed' % (len(checks), sum(1 for c in checks if not c['ok'])))
    return 1 if any(not c['ok'] for c in checks) else 0
if __name__ == '__main__': sys.exit(main())
