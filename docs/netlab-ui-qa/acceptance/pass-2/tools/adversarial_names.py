#!/usr/bin/env python3
"""Pass-2 adversarial fixture check (own design) against DEFECTS.md QA-016 and QA-012, through the API only.

Claim under test (QA-016 + NETWORK-DESIGN.md): every name the engine types as an identifier follows netlab's
16-character rule and is refused at Save with the manager's own words, "so that a name the manager accepts
never fails the plan later". The unit test covers VRF, VLAN, pool, per-device VRF and link-pool names; this
check goes after the positions it does not cover (routing policy / prefix-list / static-route names, per-device
VLANs, an id-typed *value* such as a static route's vrf), plus a trailing-newline key (Python's `$` matches
before a final newline), and QA-012's AS range at the API. Positive control: 16-character names in those
positions save AND generate with the real engine.
"""
import json, sys, time, subprocess, urllib.request, urllib.error
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path('/home/clabllm/projects/clab-manager-1.30.42')
FIXTURE = ROOT / 'docs/redesign/tools/fixture_manager.py'
sys.path.insert(0, str(ROOT / 'clab-backup-ui'))
from app import design_intent as di  # noqa: E402

port, data, out = int(sys.argv[1]), sys.argv[2], sys.argv[3]
base = 'http://127.0.0.1:%d' % port
now = lambda: datetime.now(timezone.utc).isoformat(timespec='seconds')

def call(path, method='GET', body=None):
    req = urllib.request.Request(base + path, data=json.dumps(body).encode() if body is not None else None, method=method,
                                 headers={'Content-Type': 'application/json', 'Origin': base})
    try:
        with urllib.request.urlopen(req, timeout=60) as r: return r.status, json.loads(r.read() or b'null')
    except urllib.error.HTTPError as e:
        raw = e.read()
        try: return e.code, json.loads(raw or b'{}')
        except Exception: return e.code, {'raw': raw[:300].decode(errors='replace')}

checks = []
def check(name, ok, detail=''):
    checks.append({'name': name, 'ok': bool(ok), 'detail': str(detail)[:700]})
    print(('  ok   ' if ok else '  FAIL ') + name + ('' if ok else ': ' + str(detail)[:400]), flush=True)

record = {'started': now(), 'port': port, 'data': data, 'cases': []}
proc = subprocess.Popen([sys.executable, str(FIXTURE), '--port', str(port), '--data', data], stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
try:
    for _ in range(120):
        try:
            st, state = call('/api/state')
            if st == 200: break
        except Exception: pass
        time.sleep(0.5)
    record['manager'] = state.get('version')
    lab = next(l for l in state['labs'] if l['name'] == 'ospf-basics')
    lid = lab['id']
    devices = sorted(n.get('short_name') or n['name'] for n in lab['nodes'])
    record['lab'] = {'name': lab['name'], 'id': lid, 'devices': devices}
    r1 = devices[0]

    def revision():
        st, view = call('/api/labs/%s/design' % lid)
        return ((view or {}).get('intent') or {}).get('revision', '')

    def base_intent(**extra):
        intent = di.empty_intent(); intent.update({'modules': ['ospf']}); intent.update(extra); return intent

    def save(label, intent, expect_ok, words=None):
        st, body = call('/api/labs/%s/design' % lid, 'PUT', {'intent': intent, 'revision': revision()})
        detail = body.get('detail') if isinstance(body, dict) else body
        record['cases'].append({'case': label, 'status': st, 'detail': detail if st != 200 else 'saved revision ' + str(((body or {}).get('intent') or {}).get('revision'))})
        if expect_ok: check(label + ': saved (200)', st == 200, '%s %s' % (st, detail))
        else: check(label + ': refused at Save (400)' + (' naming "%s"' % words if words else ''), st == 400 and (words is None or words in str(detail)), '%s %s' % (st, detail))
        return st, body

    L17, L16 = 'p' * 17, 'p' * 16
    # QA-016 positions the unit test does not cover.
    save('routing.policy name of 17 characters', base_intent(modules=['ospf', 'routing'], routing={'policy': {L17: [{'action': 'permit'}]}}), False, '16 characters')
    save('routing.prefix (prefix-list) name of 17 characters', base_intent(modules=['ospf', 'routing'], routing={'prefix': {L17: [{'action': 'permit', 'ipv4': ['10.0.0.0/8']}]}}), False, '16 characters')
    save('routing.static name of 17 characters', base_intent(modules=['ospf', 'routing'], routing={'static': {L17: [{'ipv4': '192.0.2.0/24', 'nexthop': {'discard': True}}]}}), False, '16 characters')
    save('per-device VLAN name of 17 characters', base_intent(modules=['ospf', 'vlan'], nodes={r1: {'vlans': {L17: {'id': 10}}}}), False, '16 characters')
    save('a 17-character VRF name as an id-typed value (static route vrf)', base_intent(modules=['ospf', 'routing', 'vrf'], vrfs={'red': {}}, nodes={r1: {'routing': {'static': [{'ipv4': '192.0.2.0/24', 'vrf': L17, 'nexthop': {'discard': True}}]}}}), False)
    # Edge cases of the identifier rule itself.
    save('VRF key with a trailing newline ("red\\n")', base_intent(modules=['ospf', 'vrf'], vrfs={'red\n': {}}), False)
    save('VRF name starting with a digit', base_intent(modules=['ospf', 'vrf'], vrfs={'1red': {}}), False)
    st, _ = save('VRF name with a hyphen (netlab itself accepts [A-Za-z0-9_-])', base_intent(modules=['ospf', 'vrf'], vrfs={'red-blue': {}}), False)
    # QA-012 at the API.
    save('BGP AS 0', base_intent(modules=['ospf', 'bgp'], bgp={'as': 0}), False, 'bgp.as')
    save('BGP AS 4294967296', base_intent(modules=['ospf', 'bgp'], bgp={'as': 4294967296}), False, 'bgp.as')
    save('BGP AS as the string "65000"', base_intent(modules=['ospf', 'bgp'], bgp={'as': '65000'}), False, 'bgp.as')
    save('BGP AS true (a bool)', base_intent(modules=['ospf', 'bgp'], bgp={'as': True}), False, 'bgp.as')
    # Positive control: 16-character names in every position above save and the real engine generates the plan.
    good = base_intent(modules=['ospf', 'bgp', 'routing', 'vrf'], bgp={'as': 4294967295},
                       vrfs={L16: {}},
                       routing={'policy': {L16: [{'action': 'permit'}]}, 'prefix': {'q' * 16: [{'action': 'permit', 'ipv4': ['10.0.0.0/8']}]},
                                'static': {'s' * 16: [{'ipv4': '192.0.2.0/24', 'nexthop': {'discard': True}}]}})
    st, body = save('16-character VRF, policy, prefix-list and static names with AS 4294967295', good, True)
    if st == 200:
        rev = revision()
        st, gen = call('/api/labs/%s/design/generate' % lid, 'POST', {'revision': rev})
        check('generate accepted', st in (200, 202), '%s %s' % (st, gen))
        status = None; message = ''
        for _ in range(120):
            st, view = call('/api/labs/%s/design' % lid)
            gens = (view or {}).get('generations') or []
            if gens and gens[-1].get('status') in ('succeeded', 'failed', 'interrupted', 'cancelled'):
                status = gens[-1]['status']; message = json.dumps({k: gens[-1].get(k) for k in ('status', 'message', 'errors', 'engine')})[:600]; break
            time.sleep(1)
        record['generation'] = {'status': status, 'detail': message}
        check('the real engine generates the plan for names the manager accepted (never fails later)', status == 'succeeded', message)
    # Exploratory, outside the documented claims: a policy that matches a prefix list that does not exist.
    save('exploratory: policy match.prefix naming a prefix list that does not exist', base_intent(modules=['ospf', 'routing'], routing={'policy': {'pol': [{'action': 'permit', 'match': {'prefix': 'nosuchlist'}}]}}), True)
    rev = revision(); st, gen = call('/api/labs/%s/design/generate' % lid, 'POST', {'revision': rev}); status = None; message = ''
    for _ in range(120):
        st, view = call('/api/labs/%s/design' % lid)
        gens = (view or {}).get('generations') or []
        if gens and gens[-1].get('status') in ('succeeded', 'failed', 'interrupted', 'cancelled') and len(gens) >= 2:
            status = gens[-1]['status']; message = json.dumps({k: gens[-1].get(k) for k in ('status', 'message', 'errors')})[:700]; break
        time.sleep(1)
    record['exploratory_dangling_prefix_generation'] = {'status': status, 'detail': message}
    print('  note exploratory dangling prefix-list reference: generation %s %s' % (status, message[:400]))
finally:
    proc.terminate()
    try: proc.wait(timeout=10)
    except subprocess.TimeoutExpired: proc.kill()
record['checks'] = checks; record['finished'] = now()
Path(out).write_text(json.dumps(record, indent=1))
failed = [c for c in checks if not c['ok']]
print('%d checks, %d failed' % (len(checks), len(failed)))
