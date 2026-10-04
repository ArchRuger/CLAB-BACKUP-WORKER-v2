"""Tests for app/design_apply.py: the review token, the apply job, drift and session-loss handling,
the ownership ledger and restart reconciliation.

docs/netlab-integration/PROVISIONING.md is the contract. Everything here drives the real app through
TestClient against scratch state (create_app(<tempdir>)); no SSH is ever opened. The platform driver
(app/design_eos.py) is replaced with a compact fake that models one Arista-cEOS-shaped device per node
as plain running-config text and a small set of scripted failure knobs (rejected load, lost session
before/after arming, a foreign pending change, "never confirmed"); the merge and removal semantics are
delegated to the real app.design_ownership functions wherever possible so the fake stays a text model,
not a second implementation of the ownership algebra. `app.state.design_apply.connect` is patched to a
no-op so `_open()` "connects" without a network, and `app.design_apply.DRIVERS` is patched to
`{'arista_ceos': fake}` for the duration of each test.
"""
import copy
import hashlib
import json
import tempfile
import time
import unittest
import uuid
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import create_app
from app.store import Store
from app.discovery import parse_definition
from app.network_design import NetworkDesign
from app.runner import Runner, now as runner_now
from app.restore import RestoreService
from app.lab_operations import operation_busy
from app.restore_shell import RestoreError, SessionLost
from app import design_apply as da
from app import design_ownership as own

# --- topologies --------------------------------------------------------------------------------------

TWO_CEOS_TOPOLOGY = '''name: design-apply-test
mgmt:
  network: clab
  ipv4-subnet: 172.20.20.0/24
topology:
  nodes:
    ceos:
      kind: arista_ceos
      image: n24l/ceos:4.35.0F
      mgmt-ipv4: 172.20.20.101
    ceos2:
      kind: arista_ceos
      image: n24l/ceos:4.35.0F
      mgmt-ipv4: 172.20.20.102
  links:
    - endpoints: ["ceos:eth1", "ceos2:eth1"]
'''

FOUR_KIND_TOPOLOGY = '''name: restore-square
mgmt:
  network: clab
  ipv4-subnet: 172.20.20.0/24
topology:
  nodes:
    ceos:
      kind: arista_ceos
      image: n24l/ceos:4.35.0F
      mgmt-ipv4: 172.20.20.101
    cjunosevolved:
      kind: juniper_cjunosevolved
      image: n24l/cjunosevolved:26.2R1.7-EVO
      mgmt-ipv4: 172.20.20.102
    vjunos-switch:
      kind: juniper_vjunosswitch
      image: n24l/vjunos-switch:23.2R1.14
      mgmt-ipv4: 172.20.20.103
    xrv9k:
      kind: cisco_xrv9k
      image: n24l/cisco_xrv9k:24.3.1
      mgmt-ipv4: 172.20.20.104
    host1:
      kind: linux
      image: ghcr.io/srl-labs/network-multitool:latest
      mgmt-ipv4: 172.20.20.105
    ceos2:
      kind: arista_ceos
      image: n24l/ceos:4.35.0F
      mgmt-ipv4: 172.20.20.106
  links:
    - endpoints: ["ceos:eth1", "cjunosevolved:et-0/0/0"]
    - endpoints: ["cjunosevolved:et-0/0/1", "vjunos-switch:ge-0/0/0"]
    - endpoints: ["vjunos-switch:ge-0/0/1", "xrv9k:Gi0/0/0/0"]
    - endpoints: ["xrv9k:Gi0/0/0/1", "ceos:eth2"]
    - endpoints: ["host1:eth1", "vjunos-switch:ge-0/0/2"]
    - endpoints: ["host1:eth2", "ceos:eth3"]
    - endpoints: ["ceos2:eth1", "ceos:eth4"]
'''

# --- device text fixtures -----------------------------------------------------------------------------

CLEAN_BASE = '!\nend\n'

BASELINE = ('interface Ethernet1\n'
            '!\n'
            'interface Management0\n'
            '   ip address 172.20.20.101/24\n'
            '!\n'
            'hostname ceos\n'
            '!\n'
            'end\n')

CONFLICT_BASELINE = ('interface Ethernet1\n'
                      '   ip address 10.9.9.9/24\n'
                      '!\n'
                      'interface Management0\n'
                      '   ip address 172.20.20.101/24\n'
                      '!\n'
                      'hostname ceos\n'
                      '!\n'
                      'end\n')

# Mirrors PROVISIONING.md §7's live evidence: an interface block and a router ospf block, plus a
# hostname line and a management block that `prepare` must leave out.
FRAGMENT = ('hostname ceos\n'
            '!\n'
            'interface Management0\n'
            '   ip address dhcp\n'
            '!\n'
            'interface Ethernet1\n'
            '   no switchport\n'
            '   ip address 10.0.0.1/30\n'
            '!\n'
            'router ospf 7\n'
            '   router-id 7.7.7.7\n'
            '   network 10.0.0.0/30 area 0.0.0.0\n'
            '!\n'
            'end\n')

# The same fragment with the ospf module dropped (used for the "stale statement" scenario).
FRAGMENT_NO_OSPF = ('hostname ceos\n'
                     '!\n'
                     'interface Management0\n'
                     '   ip address dhcp\n'
                     '!\n'
                     'interface Ethernet1\n'
                     '   no switchport\n'
                     '   ip address 10.0.0.1/30\n'
                     '!\n'
                     'end\n')

KIND = 'arista_ceos'


# --- text-level merge helpers for the fake driver -----------------------------------------------------

def _blocks(text):
    blocks, current = [], None
    for raw in (text or '').splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith('!') or stripped == 'end':
            current = None
            continue
        if line.startswith((' ', '\t')) and current is not None:
            current[1].append(line)
            continue
        current = [line, []]
        blocks.append(current)
    return blocks


def _render(blocks):
    lines = ['!']
    for header, children in blocks:
        lines.append(header)
        lines.extend(children)
        lines.append('!')
    lines.append('end')
    return '\n'.join(lines) + '\n'


REPLACE_PREFIXES = ('ip address ', 'ipv6 address ', 'router-id ', 'description ')


def _merge_blocks(blocks, candidate_blocks):
    index = {item[0].strip(): item for item in blocks}
    for chead, cchildren in candidate_blocks:
        key = chead.strip()
        block = index.get(key)
        if block is None:
            new_block = [chead, list(cchildren)]
            blocks.append(new_block)
            index[key] = new_block
            continue
        for child in cchildren:
            cstripped = child.strip()
            if any(c.strip() == cstripped for c in block[1]):
                continue
            for prefix in REPLACE_PREFIXES:
                if cstripped.startswith(prefix):
                    block[1] = [c for c in block[1] if not c.strip().startswith(prefix)]
                    index[key][1] = block[1]
                    break
            block[1].append(child)
    return blocks


def _apply_removals(blocks, removals):
    if not removals:
        return blocks
    chunks, current = [], []
    for line in removals:
        if line.strip() == '!':
            if current:
                chunks.append(current)
            current = []
        else:
            current.append(line)
    if current:
        chunks.append(current)
    index = {item[0].strip(): item for item in blocks}
    for chunk in chunks:
        if not chunk:
            continue
        *context, negation = chunk
        neg = negation.strip()
        if neg.startswith('default '):
            leaf = 'no ' + neg[len('default '):]
        elif neg.startswith('no '):
            leaf = neg[len('no '):]
        else:
            leaf = neg
        if context:
            header = context[0].strip()
            block = index.get(header)
            if block is not None:
                block[1] = [c for c in block[1] if c.strip() != leaf]
        else:
            blocks[:] = [b for b in blocks if b[0].strip() != leaf]
            index.pop(leaf, None)
    return blocks


def _merge(running_text, candidate_text, removals):
    blocks = [[h, list(c)] for h, c in _blocks(running_text)]
    _apply_removals(blocks, removals)
    _merge_blocks(blocks, _blocks(candidate_text))
    return _render(blocks)


def _diff_text(before, after):
    before_lines = set(before.splitlines())
    return '\n'.join(l for l in after.splitlines() if l.strip() and l.strip() != '!' and l not in before_lines)


# --- the fake driver -----------------------------------------------------------------------------------

class DeviceState:
    def __init__(self, running):
        self.running = running
        self.pending = None
        self.armed = False
        self.would_be_pending = None
        self.reject_load = False
        self.lose_before_arm = False
        self.lose_after_arm = False
        self.never_confirm = False
        self.foreign_after_arm = None


class FakeDriver:
    """Stands in for app/design_eos.py: a per-node text model with scripted apply-time failures."""

    SUPPORTED_KINDS = (KIND,)

    def __init__(self):
        self.devices = {}
        self.calls = []

    def register(self, key, running_text=BASELINE):
        self.devices[key] = DeviceState(running_text)

    def set_running(self, key, text):
        self.devices[key].running = text

    def _dev(self, o):
        return self.devices[o['_key']]

    # driver contract -----------------------------------------------------------------------------

    def options(self, creds):
        return {'_key': (creds or {}).get('enable_password') or (creds or {}).get('username') or ''}

    def session_name(self):
        return 'clabdsg-' + uuid.uuid4().hex[:8]

    def snapshot(self, client, **o):
        dev = self._dev(o)
        # While a timed commit is pending the device runs the would-be configuration (EOS, Junos and IOS XR alike).
        return dev.would_be_pending if (dev.pending and dev.would_be_pending is not None) else dev.running

    def render_desired(self, client, candidate, **o):
        return CLEAN_BASE, CLEAN_BASE + candidate

    def stage(self, client, candidate, removals, name, confirm_minutes=5, arm=False, accept=None, **o):
        self.calls.append(('stage', o.get('_key'), arm))
        dev = self._dev(o)
        if dev.reject_load:
            raise RestoreError('The node rejected part of the generated configuration while loading it.')
        merged = _merge(dev.running, candidate, removals)
        no_op = merged == dev.running
        diff = _diff_text(dev.running, merged)
        if not arm or no_op:
            return {'before': dev.running, 'would_be': merged, 'diff': diff, 'no_op': no_op, 'armed': False, 'handle': {'session': name}}
        if accept is not None and not accept(merged):   # the drivers' contract: asked before anything is armed
            raise RestoreError('The configuration the device would run differs from the reviewed one; nothing was applied.')
        if dev.lose_before_arm:
            raise SessionLost('The session to the device was lost while staging the change.')
        if dev.lose_after_arm:
            dev.pending = name
            dev.armed = True
            dev.would_be_pending = merged
            raise SessionLost('The session to the device was lost after the change was armed.')
        if dev.foreign_after_arm:
            dev.pending = dev.foreign_after_arm
            dev.armed = True
            dev.would_be_pending = None
        elif dev.never_confirm:
            dev.pending = None
            dev.armed = True
            dev.would_be_pending = None
        else:
            dev.pending = name
            dev.armed = True
            dev.would_be_pending = merged
        return {'before': dev.running, 'would_be': merged, 'diff': diff, 'no_op': False, 'armed': True, 'handle': {'session': name}}

    def confirm(self, client, handle, **o):
        dev = self._dev(o)
        session = (handle or {}).get('session')
        if not dev.pending or dev.pending != session:
            raise RestoreError('The change was already reverted or was never armed; there is nothing to confirm.')
        if dev.would_be_pending is not None:
            dev.running = dev.would_be_pending
        dev.pending = None
        dev.armed = False
        dev.would_be_pending = None
        return {'confirmed': True, 'saved': True}

    def pending(self, client, **o):
        return self._dev(o).pending

    def cleanup(self, client, **o):
        return []

    def persist(self, client, **o):
        return True


class FakeRunner:
    """Stands in for Runner.submit: writes a completed backup job without touching Ansible or SSH."""

    def __init__(self, store, fail_nodes=(), refuse_sources=()):
        self.store = store
        self.fail_nodes = set(fail_nodes)
        self.refuse_sources = set(refuse_sources)
        self.calls = []

    def submit(self, lab_id, operation='backup', source='manual', node_names=None, progress_id=None, progress_context=None):
        self.calls.append(dict(source=source, node_names=list(node_names or []), progress_id=progress_id))
        if source in self.refuse_sources:
            raise ValueError('The backup worker is busy.')
        job_id = uuid.uuid4().hex
        lab = self.store.lab(lab_id)
        nodes = []
        for node in lab['nodes']:
            if node_names is not None and node['name'] not in node_names:
                continue
            if node['name'] in self.fail_nodes:
                nodes.append({'name': node['name'], 'status': 'failed', 'message': 'capture failed'})
            else:
                nodes.append({'name': node['name'], 'status': 'succeeded'})
        if not nodes:
            status = 'failed'
        elif all(n['status'] == 'succeeded' for n in nodes):
            status = 'succeeded'
        elif any(n['status'] == 'succeeded' for n in nodes):
            status = 'partial'
        else:
            status = 'failed'
        job = dict(id=job_id, lab_id=lab_id, lab_name=lab['name'], operation=operation, source=source,
                   status=status, created=runner_now(), finished=runner_now(), nodes=nodes, progress_id=progress_id)
        self.store.state['jobs'].insert(0, job)
        self.store.save()
        return copy.deepcopy(job)


def fake_connect(client, node, creds):
    return None


# --- fixture helpers -----------------------------------------------------------------------------------

def add_lab(app, name='design-apply-test', definition_yaml=TWO_CEOS_TOPOLOGY):
    lab_id = uuid.uuid4().hex
    with app.state.store.lock:
        nodes = parse_definition(definition_yaml.encode())['nodes']
        lab = dict(id=lab_id, name=name, nodes=nodes, profiles=[], defaults={}, interval=0, next_run=None,
                   created='2026-09-27T00:00:00+00:00', updated='2026-09-27T00:00:00+00:00',
                   definition_yaml=definition_yaml)
        app.state.store.state['labs'].append(lab)
        app.state.store.save()
    return lab_id


def seed_discovery(app, lab_id, deployment_name='design-apply-test'):
    store = app.state.store
    with store.lock:
        lab = store.lab(lab_id)
        lab['deployment_name'] = deployment_name
        for node in lab['nodes']:
            node.update(discovered=True, runtime_state='running', discovered_address=node['address'], endpoint_mode='manual')
        store.state['host'] = {'enabled': True, 'address': '10.0.0.1', 'port': 22, 'username': 'clab',
                               'password': 'vm-secret', 'fingerprint': 'SHA256:fix', 'auth': 'password'}
        store.state['discovery'] = {'ok': True, 'checked_epoch': time.time(), 'checked_at': 'x', 'last_success': 'x', 'labs': {}}
        store.save()


def mark_unavailable(app, lab_id, short):
    store = app.state.store
    with store.lock:
        node = _find_node(store.lab(lab_id), short)
        node.update(discovered=False, runtime_state='exited')
        store.save()


def _find_node(lab, short):
    return next(n for n in lab['nodes'] if (n.get('definition_node') or n.get('short_name')) == short)


def set_credentials(app, lab_id, short, username='admin', password='admin', enable_password=None):
    store = app.state.store
    with store.lock:
        node = _find_node(store.lab(lab_id), short)
        node.update(username=username, password=password, enable_password=enable_password or short)
        store.save()


def add_generation(app, lab_id, nodes_map, fragments, status='succeeded', revision='rev1', extra=None):
    """`nodes_map`: {short: {'kind','included','role','blocked'}}; `fragments`: {short: [(module, text)]}."""
    store = app.state.store
    with store.lock:
        lab = store.lab(lab_id)
        gen_id = uuid.uuid4().hex
        folder = app.state.network_design.root / lab_id / gen_id
        artifacts = {}
        for short, items in fragments.items():
            node_dir = folder / 'nodes' / short
            node_dir.mkdir(parents=True, exist_ok=True)
            entries = []
            for index, (module, text) in enumerate(items):
                raw = text.encode('utf-8')
                (node_dir / ('%02d-%s' % (index, module))).write_bytes(raw)
                entries.append({'module': module, 'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()})
            artifacts[short] = entries
        lab.setdefault('network_design', {})['revision'] = revision   # the plan is the current design's
        generation = {'id': gen_id, 'lab_id': lab_id, 'created': '2026-09-27T00:00:00+00:00', 'status': status,
                      'message': 'Plan generated', 'intent_revision': revision,
                      'topology_digest': hashlib.sha256(lab['definition_yaml'].encode()).hexdigest(),
                      'mapping_digest': 'm' * 8, 'nodes': nodes_map,
                      'compatibility': {short: [{'feature': 'ospfv2', 'level': 'generated_not_live_tested'}] for short in nodes_map},
                      'artifacts': artifacts}
        if extra:
            generation.update(extra)
        lab.setdefault('network_generations', []).append(generation)
        store.save()
    return gen_id


def update_fragment(app, lab_id, generation_id, short, index, module, text):
    store = app.state.store
    with store.lock:
        lab = store.lab(lab_id)
        generation = next(g for g in lab['network_generations'] if g['id'] == generation_id)
        folder = app.state.network_design.root / lab_id / generation_id
        raw = text.encode('utf-8')
        (folder / 'nodes' / short / ('%02d-%s' % (index, module))).write_bytes(raw)
        generation['artifacts'][short][index] = {'module': module, 'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
        store.save()


def node_map(short, kind=KIND, included=True, role='router', blocked=''):
    return {short: {'kind': kind, 'included': included, 'role': role, 'blocked': blocked}}


def poll_job(client, job_id, timeout=30):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        response = client.get(f'/api/design/apply/jobs/{job_id}')
        last = response.json()
        if last['status'] not in da.DESIGN_APPLY_BUSY:
            return last
        time.sleep(0.05)
    raise AssertionError('Design apply job did not finish in time: ' + str(last))


def poll_review_job(client, lab_id, job_id, timeout=30):
    """Follows GET .../design/review-jobs/{id} until the job leaves `running`; returns the last body."""
    deadline = time.monotonic() + timeout
    body = None
    while time.monotonic() < deadline:
        response = client.get(f'/api/labs/{lab_id}/design/review-jobs/{job_id}')
        assert response.status_code == 200, response.text
        body = response.json()
        if body['status'] != 'running': return body
        time.sleep(0.02)
    raise AssertionError('Review job did not finish in time: ' + str(body))


class ReviewedBody:
    """A finished review job read the way the synchronous review response was: status code and JSON body."""
    def __init__(self, status_code, body):
        self.status_code = status_code; self.body = body
        self.text = json.dumps(body)

    def json(self):
        return self.body


class DesignApplyTestCase(unittest.TestCase):
    """Common fixture: a two-node cEOS lab, discovery marked fresh, both devices credentialed and
    registered with the fake driver, a default one-node generation from FRAGMENT."""

    topology = TWO_CEOS_TOPOLOGY

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.app = create_app(self.tmp.name)
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)
        self.addCleanup(self.app.state.design_apply.close)
        self.addCleanup(self.app.state.network_design.close)
        self.fake = FakeDriver()
        self.fake.register('ceos', BASELINE)
        self.fake.register('ceos2', BASELINE)
        patcher = patch('app.design_apply.DRIVERS', {KIND: self.fake})
        patcher.start()
        self.addCleanup(patcher.stop)
        service = self.app.state.design_apply
        service.connect = fake_connect
        service.retry_interval = 0.05
        service.recovery_grace = 0.05
        service.connect_pause = 0.05
        self.runner = FakeRunner(self.app.state.store)
        service.runner = self.runner
        self.lab_id = add_lab(self.app, definition_yaml=self.topology)
        seed_discovery(self.app, self.lab_id)
        set_credentials(self.app, self.lab_id, 'ceos')
        if 'ceos2' in [n.get('definition_node') for n in self.app.state.store.lab(self.lab_id)['nodes']]:
            set_credentials(self.app, self.lab_id, 'ceos2')

    def default_generation(self, running='ceos'):
        return add_generation(self.app, self.lab_id, node_map('ceos'), {'ceos': [('initial', FRAGMENT)]})

    def review(self, generation_id, targets=('ceos',), takeover=()):
        """The review as these tests knew it before it became a job: POST starts the job (its synchronous guards still
        answer with their status at once), then the job is followed until it finishes and its review payload (with the
        token) stands in for the old synchronous body; a job that finishes failed reads as the 409 it used to be."""
        response = self.client.post(f'/api/labs/{self.lab_id}/design/generations/{generation_id}/review',
                                    json={'targets': list(targets), 'takeover': list(takeover), 'request_id': uuid.uuid4().hex})
        if response.status_code != 200: return response
        self.last_review_job = poll_review_job(self.client, self.lab_id, response.json()['review_job']['id'])
        if self.last_review_job['status'] == 'done': return ReviewedBody(200, self.last_review_job['review'])
        return ReviewedBody(409, {'detail': self.last_review_job['message']})

    def submit_http(self, token, confirm_minutes=5, takeover=(), request_id=None, acknowledged=True):
        body = {'token': token, 'confirm_minutes': confirm_minutes, 'takeover': list(takeover),
                'request_id': request_id or uuid.uuid4().hex, 'acknowledged': acknowledged}
        return self.client.post(f'/api/labs/{self.lab_id}/design/apply', json=body)


# --- 1. review guards ------------------------------------------------------------------------------

class ReviewGuardTests(DesignApplyTestCase):
    topology = FOUR_KIND_TOPOLOGY

    def setUp(self):
        super().setUp()
        set_credentials(self.app, self.lab_id, 'ceos')
        seed_discovery(self.app, self.lab_id)
        mark_unavailable(self.app, self.lab_id, 'ceos2')
        # The base fixture credentials both cEOS nodes by default; this suite needs ceos2 to lack
        # credentials instead (a kind the fake driver supports, so the "no credentials" branch is
        # reached rather than the "kind without a driver" one).
        with self.app.state.store.lock:
            node = _find_node(self.app.state.store.lab(self.lab_id), 'ceos2')
            node.update(username='', password='', enable_password='')
            self.app.state.store.save()

    def test_unknown_lab_is_404(self):
        gen_id = add_generation(self.app, self.lab_id, node_map('ceos'), {'ceos': [('initial', FRAGMENT)]})
        response = self.client.post(f'/api/labs/{uuid.uuid4().hex}/design/generations/{gen_id}/review',
                                    json={'targets': ['ceos'], 'takeover': []})
        self.assertEqual(response.status_code, 404)

    def test_generation_not_succeeded_is_409(self):
        gen_id = add_generation(self.app, self.lab_id, node_map('ceos'), {'ceos': [('initial', FRAGMENT)]}, status='running')
        response = self.review(gen_id)
        self.assertEqual(response.status_code, 409)
        self.assertIn('generated plan', response.json()['detail'])

    def test_each_ineligible_reason_and_409_when_all_ineligible(self):
        nodes_map = {}
        nodes_map.update(node_map('ceos2'))
        nodes_map.update(node_map('vjunos-switch', kind='juniper_vjunosswitch'))
        nodes_map.update(node_map('host1', kind='linux', role='host'))
        gen_id = add_generation(self.app, self.lab_id, nodes_map, {'ceos2': [('initial', FRAGMENT)]})
        # ceos2: marked not running above. cjunosevolved (unnamed in the plan below, "ghost" stands
        # in for a device not present in the generation at all).
        response = self.review(gen_id, targets=['ghost', 'host1', 'vjunos-switch', 'ceos2'])
        self.assertEqual(response.status_code, 409)
        detail = response.json()['detail']
        self.assertIn('ghost: This device is not part of the plan.', detail)
        self.assertIn('host1: A support host is generated only', detail)
        self.assertIn('vjunos-switch: ' + da.NOT_AVAILABLE, detail)
        self.assertIn('ceos2: This device is not running', detail)

    def test_device_without_credentials_is_ineligible(self):
        gen_id = add_generation(self.app, self.lab_id, node_map('ceos2'), {'ceos2': [('initial', FRAGMENT)]})
        with self.app.state.store.lock:
            node = _find_node(self.app.state.store.lab(self.lab_id), 'ceos2')
            # arista_ceos has a documented containerlab default login (admin/admin), so an empty
            # username/password alone still resolves credentials; a profile_id with no matching
            # profile is the one path effective_credentials() returns {} for.
            node.update(discovered=True, runtime_state='running', discovered_address=node['address'], profile_id='missing-profile')
            self.app.state.store.save()
        response = self.review(gen_id, targets=['ceos2'])
        self.assertEqual(response.status_code, 409)
        self.assertIn('Add login credentials', response.json()['detail'])

    def test_busy_operation_is_409(self):
        gen_id = add_generation(self.app, self.lab_id, node_map('ceos'), {'ceos': [('initial', FRAGMENT)]})
        self.app.state.store.state.setdefault('restore_jobs', []).append({'id': 'r1', 'status': 'applying', 'lab_id': self.lab_id})
        self.app.state.store.save()
        response = self.review(gen_id)
        self.assertEqual(response.status_code, 409)

    def test_stale_discovery_is_409(self):
        gen_id = add_generation(self.app, self.lab_id, node_map('ceos'), {'ceos': [('initial', FRAGMENT)]})
        with self.app.state.store.lock:
            self.app.state.store.state['discovery']['checked_epoch'] = 0
            self.app.state.store.save()
        response = self.review(gen_id)
        self.assertEqual(response.status_code, 409)
        self.assertIn('Refresh the lab list', response.json()['detail'])


# --- 2. a successful review -------------------------------------------------------------------------

class SuccessfulReviewTests(DesignApplyTestCase):
    def test_review_token_and_public_fields(self):
        gen_id = self.default_generation()
        response = self.review(gen_id)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(len(body['token']), 32)
        int(body['token'], 16)
        self.assertEqual(body['expires_in'], da.REVIEW_TTL)
        self.assertEqual(body['applicable'], ['ceos'])
        row = next(r for r in body['targets'] if r['name'] == 'ceos')
        self.assertTrue(row['eligible'])
        self.assertTrue(row['reachable'])
        self.assertTrue(row['ready'])
        self.assertFalse(row['no_op'])
        protected_statements = {p['statement'] for p in row['protected']}
        self.assertIn('hostname ceos', protected_statements)
        self.assertIn('interface Management0', protected_statements)
        self.assertTrue(row['diff'])
        self.assertTrue(row['added'])
        self.assertEqual(row['removed'], [])
        self.assertEqual(row['removals'], [])
        self.assertEqual(row['counts']['removals'], 0)
        self.assertTrue(row['compatibility'])
        # no private keys ever cross the wire
        self.assertFalse(any(k.startswith('_') for k in row))
        self.assertNotIn('reviews', body)


# --- 3. conflicts and take-over ------------------------------------------------------------------------

class ConflictTakeoverTests(DesignApplyTestCase):
    def setUp(self):
        super().setUp()
        self.fake.register('ceos', CONFLICT_BASELINE)

    def test_conflict_blocks_applicable_without_takeover(self):
        gen_id = self.default_generation()
        body = self.review(gen_id).json()
        row = next(r for r in body['targets'] if r['name'] == 'ceos')
        self.assertTrue(row['ready'])
        self.assertIn('interface Ethernet1 > ip address 10.9.9.9/24', row['conflicts'])
        self.assertEqual(body['applicable'], [])

    def test_takeover_makes_it_applicable_and_apply_needs_matching_takeover(self):
        gen_id = self.default_generation()
        body = self.review(gen_id, takeover=['ceos']).json()
        self.assertEqual(body['applicable'], ['ceos'])
        token = body['token']
        # A submit whose take-over list differs from the review's is refused.
        response = self.submit_http(token, takeover=[])
        self.assertEqual(response.status_code, 409)
        self.assertIn('differs from the review', response.json()['detail'])

    def test_takeover_of_an_exclusive_sibling_stages_a_second_pass_with_its_removal(self):
        # A merge replaces the single-valued address of this fixture by itself; an exclusive sibling (a second IPv6
        # address, a Junos address) would stay. Simulate that shape: the first pass reports the conflict as still
        # present, so the review must stage once more with the conflict among the removals and verify it gone.
        from app import design_ownership as own
        gen_id = self.default_generation()
        calls = []
        real_stage = self.fake.stage
        def counting_stage(client, candidate, removals, name, confirm_minutes=5, arm=False, **o):
            calls.append(list(removals)); return real_stage(client, candidate, removals, name, confirm_minutes, arm, **o)
        conflict = 'interface Ethernet1 > ip address 10.9.9.9/24'
        with patch.object(self.fake, 'stage', side_effect=counting_stage), \
             patch.object(own, 'takeover_leftovers', side_effect=lambda conflicts, would_be: [conflict] if conflict in conflicts else []):
            body = self.review(gen_id, takeover=['ceos']).json()
        self.assertEqual(len(calls), 2, 'the review staged twice: once to find the leftover, once with its removal')
        self.assertEqual(calls[0], [])
        self.assertEqual(calls[1], ['interface Ethernet1', ' no ip address 10.9.9.9/24', '!'])
        row = next(r for r in body['targets'] if r['name'] == 'ceos')
        self.assertIn(' no ip address 10.9.9.9/24', row['removals'])
        self.assertEqual(row['counts']['removals'], 1)
        bound = self.app.state.design_apply.reviews[body['token']]['targets']['ceos']
        self.assertIn(conflict, bound['_stale'], 'a taken-over statement must be verified gone afterwards')
        self.assertEqual(bound['_removals'], calls[1])


    def test_a_plan_of_another_design_revision_or_topology_is_refused(self):
        gen_id = self.default_generation()
        token = self.review(gen_id).json()['token']
        with self.app.state.store.lock:
            self.app.state.store.lab(self.lab_id)['network_design']['revision'] = 'rev2'; self.app.state.store.save()
        response = self.submit_http(token)
        self.assertEqual(response.status_code, 409); self.assertIn('older than the design', response.json()['detail'])
        response = self.review(gen_id)
        self.assertEqual(response.status_code, 409); self.assertIn('generate it again', response.json()['detail'])
        with self.app.state.store.lock:
            lab = self.app.state.store.lab(self.lab_id); lab['network_design']['revision'] = 'rev1'; lab['definition_yaml'] += '\n# edited\n'; self.app.state.store.save()
        response = self.review(gen_id)
        self.assertEqual(response.status_code, 409, 'a changed topology makes the plan stale too')

    def test_another_labs_running_apply_refuses_the_review(self):
        gen_id = self.default_generation()
        with self.app.state.store.lock:
            self.app.state.store.state.setdefault('design_jobs', []).append({'id': 'other', 'lab_id': 'other-lab', 'status': 'applying', 'targets': []}); self.app.state.store.save()
        response = self.review(gen_id)
        self.assertEqual(response.status_code, 409); self.assertIn('Another design apply is running', response.json()['detail'])
        with self.app.state.store.lock:
            self.app.state.store.state['design_jobs'] = []; self.app.state.store.state['restore_jobs'] = [{'id': 'r', 'status': 'applying'}]; self.app.state.store.save()
        response = self.review(gen_id)
        self.assertEqual(response.status_code, 409); self.assertIn('restore', response.json()['detail'])


# --- 4. apply guards --------------------------------------------------------------------------------

class ApplyGuardTests(DesignApplyTestCase):
    def test_bad_token_is_409(self):
        response = self.submit_http(uuid.uuid4().hex)
        self.assertEqual(response.status_code, 409)

    def test_expired_token_is_409(self):
        gen_id = self.default_generation()
        token = self.review(gen_id).json()['token']
        self.app.state.design_apply.reviews[token]['expires'] = time.monotonic() - 1
        response = self.submit_http(token)
        self.assertEqual(response.status_code, 409)

    def test_same_request_id_returns_the_same_job(self):
        gen_id = self.default_generation()
        token = self.review(gen_id).json()['token']
        request_id = uuid.uuid4().hex
        first = self.submit_http(token, request_id=request_id)
        self.assertEqual(first.status_code, 200)
        job_id = first.json()['id']
        # The token was consumed; a second submit with the same body must still short-circuit to the same job.
        second = self.submit_http(token, request_id=request_id)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()['id'], job_id)
        poll_job(self.client, job_id)

    def test_generation_changed_since_review_is_409(self):
        gen_id = self.default_generation()
        token = self.review(gen_id).json()['token']
        with self.app.state.store.lock:
            lab = self.app.state.store.lab(self.lab_id)
            gen = next(g for g in lab['network_generations'] if g['id'] == gen_id)
            gen['intent_revision'] = 'changed'
            self.app.state.store.save()
        response = self.submit_http(token)
        self.assertEqual(response.status_code, 409)
        self.assertIn('changed', response.json()['detail'])

    def test_token_of_another_lab_is_409(self):
        gen_id = self.default_generation()
        token = self.review(gen_id).json()['token']
        other_lab_id = add_lab(self.app, name='other', definition_yaml=TWO_CEOS_TOPOLOGY)
        body = {'token': token, 'confirm_minutes': 5, 'takeover': [], 'request_id': uuid.uuid4().hex, 'acknowledged': True}
        response = self.client.post(f'/api/labs/{other_lab_id}/design/apply', json=body)
        self.assertEqual(response.status_code, 409)

    def test_acknowledged_false_is_400(self):
        gen_id = self.default_generation()
        token = self.review(gen_id).json()['token']
        response = self.submit_http(token, acknowledged=False)
        self.assertEqual(response.status_code, 400)

    def test_conflicts_without_takeover_are_409_at_submit(self):
        self.fake.register('ceos', CONFLICT_BASELINE)
        gen_id = self.default_generation()
        token = self.review(gen_id, takeover=['ceos']).json()['token']
        # Force the review's own record to look as if take-over had not been granted, mimicking
        # a client that dropped the flag between review and submit.
        self.app.state.design_apply.reviews[token]['takeover'] = []
        response = self.submit_http(token, takeover=[])
        self.assertEqual(response.status_code, 409)
        self.assertIn('Conflicts', response.json()['detail'])


# --- 5. a full, successful apply ------------------------------------------------------------------------

class FullApplySuccessTests(DesignApplyTestCase):
    def test_full_apply_succeeds_and_records_everything(self):
        gen_id = self.default_generation()
        token = self.review(gen_id).json()['token']
        submitted = self.submit_http(token)
        self.assertEqual(submitted.status_code, 200)
        job_id = submitted.json()['id']
        job = poll_job(self.client, job_id)

        self.assertEqual(job['status'], 'succeeded')
        target = next(t for t in job['targets'] if t['name'] == 'ceos')
        self.assertEqual(target['status'], 'verified')
        self.assertEqual(target['stage'], 'applied')
        self.assertEqual(target['persistence'], 'saved')
        self.assertTrue(target['diff_sample'])
        self.assertEqual(target['verify'], {'missing': [], 'remaining': []})
        self.assertFalse(any(k.startswith('_') for k in target))

        self.assertTrue(job['pre_backup_job_id'])
        self.assertTrue(job['post_backup_job_id'])
        sources = [c['source'] for c in self.runner.calls]
        self.assertIn('design-pre', sources)
        self.assertIn('design-post', sources)
        for call in self.runner.calls:
            if call['source'] in ('design-pre', 'design-post'):
                self.assertEqual(call['progress_id'], job_id)

        with self.app.state.store.lock:
            lab = self.app.state.store.lab(self.lab_id)
            ledger = lab['network_ownership']['ceos']
        self.assertEqual(ledger['generation_id'], gen_id)
        self.assertIn('interface Ethernet1 > ip address 10.0.0.1/30', ledger['statements'])
        self.assertIn('router ospf 7 > router-id 7.7.7.7', ledger['statements'])
        self.assertIn('router ospf 7', ledger['ancestors'])
        self.assertIsNone(ledger['pending'])

        state = self.client.get('/api/state').json()
        state_job = next(j for j in state['design_jobs'] if j['id'] == job_id)
        self.assertEqual(state_job['status'], 'succeeded')
        self.assertFalse(any(k.startswith('_') for t in state_job['targets'] for k in t))
        lab_state = next(l for l in state['labs'] if l['id'] == self.lab_id)
        self.assertNotIn('network_ownership', lab_state)

        ownership = self.client.get(f'/api/labs/{self.lab_id}/design/ownership').json()
        self.assertEqual(ownership['summary']['ceos']['statements'], len(ledger['statements']))
        self.assertEqual(ownership['summary']['ceos']['generation_id'], gen_id)
        self.assertTrue(ownership['statements']['ceos'])

        events = self.app.state.store.events(job_id=job_id)
        actions = {e['action'] for e in events}
        self.assertIn('design.apply.queued', actions)
        self.assertIn('design.apply.finished', actions)


# --- 6. no-op and stale-statement removal ---------------------------------------------------------------

class NoOpAndRemovalTests(DesignApplyTestCase):
    def _apply_once(self, gen_id):
        token = self.review(gen_id).json()['token']
        job_id = self.submit_http(token).json()['id']
        return poll_job(self.client, job_id)

    def test_a_second_review_and_apply_are_no_op_and_the_job_succeeds(self):
        gen_id = self.default_generation()
        first = self._apply_once(gen_id)
        self.assertEqual(first['status'], 'succeeded')

        second_review = self.review(gen_id).json()
        row = next(r for r in second_review['targets'] if r['name'] == 'ceos')
        self.assertTrue(row['no_op'])
        self.assertIn('ceos', second_review['applicable'])

        token = second_review['token']
        job_id = self.submit_http(token).json()['id']
        job = poll_job(self.client, job_id)
        target = next(t for t in job['targets'] if t['name'] == 'ceos')
        self.assertEqual(target['status'], 'no_op')
        self.assertEqual(job['status'], 'succeeded')

    def test_modified_candidate_drops_a_statement_and_the_removal_shrinks_the_ledger(self):
        gen_id = self.default_generation()
        first = self._apply_once(gen_id)
        self.assertEqual(first['status'], 'succeeded')

        update_fragment(self.app, self.lab_id, gen_id, 'ceos', 0, 'initial', FRAGMENT_NO_OSPF)
        review = self.review(gen_id).json()
        row = next(r for r in review['targets'] if r['name'] == 'ceos')
        self.assertFalse(row['no_op'])
        stale_text = ' '.join(row['stale'])
        self.assertIn('router ospf 7', stale_text)
        self.assertTrue(row['removals'])

        job_id = self.submit_http(review['token']).json()['id']
        job = poll_job(self.client, job_id)
        self.assertEqual(job['status'], 'succeeded')
        target = next(t for t in job['targets'] if t['name'] == 'ceos')
        self.assertEqual(target['status'], 'verified')

        with self.app.state.store.lock:
            ledger = self.app.state.store.lab(self.lab_id)['network_ownership']['ceos']
        self.assertNotIn('router ospf 7', ledger['ancestors'])
        self.assertFalse(any('ospf' in s for s in ledger['statements']))
        self.assertIn('interface Ethernet1 > ip address 10.0.0.1/30', ledger['statements'])


# --- 7. drift --------------------------------------------------------------------------------------------

class DriftTests(DesignApplyTestCase):
    def test_drift_between_review_and_apply_fails_the_device_and_arms_nothing(self):
        gen_id = self.default_generation()
        token = self.review(gen_id).json()['token']
        # The device's running configuration changes after the review but before the apply.
        self.fake.set_running('ceos', BASELINE.replace('interface Ethernet1', 'interface Ethernet1\n   description changed-by-someone-else', 1))
        job_id = self.submit_http(token).json()['id']
        job = poll_job(self.client, job_id)
        target = next(t for t in job['targets'] if t['name'] == 'ceos')
        self.assertEqual(target['status'], 'drifted')
        self.assertIn('changed since you reviewed it', target['message'])
        self.assertEqual(job['status'], 'failed')
        self.assertFalse(self.fake.devices['ceos'].armed)
        self.assertIsNone(self.fake.devices['ceos'].pending)

    def test_a_would_be_configuration_unlike_the_review_is_never_armed(self):
        # Someone changes the device after the apply's drift snapshot and before the transaction reads its own base:
        # the would-be configuration is not the reviewed one, so the driver is told so before it arms anything and the
        # unreviewed merge never runs for the confirmation window (audit L-14).
        gen_id = self.default_generation()
        token = self.review(gen_id).json()['token']
        dev = self.fake.devices['ceos']; real_stage = self.fake.stage; asked = []
        def concurrent_edit(client, candidate, removals, name, confirm_minutes=5, arm=False, accept=None, **o):
            if arm: dev.running = dev.running.replace('hostname ceos\n', 'hostname ceos\n!\nbanner motd X\n', 1)
            def spy(text):
                result = accept(text); asked.append(result); return result
            return real_stage(client, candidate, removals, name, confirm_minutes, arm, accept=spy if accept else None, **o)
        with patch.object(self.fake, 'stage', side_effect=concurrent_edit):
            job = poll_job(self.client, self.submit_http(token).json()['id'])
        target = next(t for t in job['targets'] if t['name'] == 'ceos')
        self.assertEqual(asked, [False], 'the reviewed would-be digest was compared before arming')
        self.assertEqual(target['status'], 'drifted')
        self.assertIn('differs from the reviewed one', target['message'])
        self.assertIn('not changed', target['message'])
        self.assertFalse(dev.armed, 'nothing unreviewed was armed')
        self.assertIsNone(dev.pending)
        self.assertEqual(job['status'], 'failed')
        with self.app.state.store.lock:
            ledger = (self.app.state.store.lab(self.lab_id).get('network_ownership') or {}).get('ceos') or {}
        self.assertFalse(ledger.get('statements') or ledger.get('pending'), 'nothing is owned or pending from it')

        # The same apply with the device as reviewed is accepted and armed.
        dev.running = BASELINE; asked.clear()
        token = self.review(gen_id).json()['token']
        with patch.object(self.fake, 'stage', side_effect=lambda *a, accept=None, **o: real_stage(*a, accept=(lambda t: asked.append(accept(t)) or asked[-1]), **o)):
            job = poll_job(self.client, self.submit_http(token).json()['id'])
        self.assertEqual(asked, [True])
        self.assertEqual(next(t for t in job['targets'] if t['name'] == 'ceos')['status'], 'verified')


# --- 8. stage and settle-path failures -------------------------------------------------------------------

class StageFailureTests(DesignApplyTestCase):
    def _submit(self, gen_id, confirm_minutes=5):
        token = self.review(gen_id).json()['token']
        return token

    def test_load_rejected_is_failed_not_changed(self):
        gen_id = self.default_generation()
        token = self._submit(gen_id)
        self.fake.devices['ceos'].reject_load = True
        job_id = self.submit_http(token).json()['id']
        job = poll_job(self.client, job_id)
        target = next(t for t in job['targets'] if t['name'] == 'ceos')
        self.assertEqual(target['status'], 'failed')
        self.assertIn('not changed', target['message'])

    def test_session_lost_before_arm_is_failed_not_changed_device_unchanged(self):
        gen_id = self.default_generation()
        token = self._submit(gen_id)
        self.fake.devices['ceos'].lose_before_arm = True
        job_id = self.submit_http(token, confirm_minutes=2).json()['id']
        job = poll_job(self.client, job_id)
        target = next(t for t in job['targets'] if t['name'] == 'ceos')
        self.assertEqual(target['status'], 'failed')
        self.assertIn('not changed', target['message'])
        self.assertEqual(self.fake.devices['ceos'].running, BASELINE)

    def test_session_lost_after_arm_is_verified(self):
        gen_id = self.default_generation()
        token = self._submit(gen_id)
        self.fake.devices['ceos'].lose_after_arm = True
        job_id = self.submit_http(token, confirm_minutes=2).json()['id']
        job = poll_job(self.client, job_id)
        target = next(t for t in job['targets'] if t['name'] == 'ceos')
        self.assertEqual(target['status'], 'verified')

    def test_never_confirmed_is_rolled_back(self):
        gen_id = self.default_generation()
        token = self._submit(gen_id)
        self.fake.devices['ceos'].never_confirm = True
        job_id = self.submit_http(token, confirm_minutes=2).json()['id']
        job = poll_job(self.client, job_id)
        target = next(t for t in job['targets'] if t['name'] == 'ceos')
        self.assertEqual(target['status'], 'rolled_back')
        self.assertEqual(self.fake.devices['ceos'].running, BASELINE)

    def test_foreign_pending_ends_uncertain_and_blocks_the_next_review(self):
        gen_id = self.default_generation()
        token = self._submit(gen_id)
        self.fake.devices['ceos'].foreign_after_arm = 'clabmgr-deadbeef'
        # confirm_minutes=0 makes the settle deadline arrive almost immediately, so the loop that
        # otherwise waits for the real timer does not stall the test.
        submit = self.app.state.design_apply.submit(self.lab_id, token, 0, uuid.uuid4().hex, [])
        job = poll_job(self.client, submit['id'])
        target = next(t for t in job['targets'] if t['name'] == 'ceos')
        self.assertEqual(target['status'], 'uncertain')
        self.assertIn('could not establish', target['message'])
        with self.app.state.store.lock:
            ledger = self.app.state.store.lab(self.lab_id)['network_ownership']['ceos']
        self.assertTrue(ledger['pending'])

        # The foreign change still refuses the next review, and while it waits for confirmation the running
        # configuration is not settled, so the pending entry is left for a later read-back (audit L-13).
        next_review = self.review(gen_id).json()
        row = next(r for r in next_review['targets'] if r['name'] == 'ceos')
        self.assertFalse(row['ready'])
        self.assertIn('Another change is waiting for confirmation', row['reason'])
        with self.app.state.store.lock:
            ledger = self.app.state.store.lab(self.lab_id)['network_ownership']['ceos']
        self.assertTrue(ledger['pending'], 'nothing is read back while a change waits for confirmation')
        self.assertEqual(ledger['statements'], [])

        # Once nothing waits any more, the next review reads the device back and settles the pending entry (the
        # change is not there: nothing is owned from it).
        dev = self.fake.devices['ceos']; dev.pending = None; dev.armed = False
        row = next(r for r in self.review(gen_id).json()['targets'] if r['name'] == 'ceos')
        self.assertTrue(row['ready'], row.get('reason'))
        with self.app.state.store.lock:
            ledger = self.app.state.store.lab(self.lab_id)['network_ownership']['ceos']
        self.assertIsNone(ledger['pending'], 'the read-back settled the entry')
        self.assertEqual(ledger['statements'], [])

    def test_a_trial_of_this_manager_still_armed_is_not_read_back_as_owned(self):
        # The settle loop can record `uncertain` while this manager's own EOS/Junos timer still runs (an unexpected
        # error breaks it at once; neither driver can release the trial). While the timer runs the device runs the
        # would-be configuration: reading it back then would own lines the device is about to undo (audit L-13).
        gen_id = self.default_generation()
        token = self._submit(gen_id)
        dev = self.fake.devices['ceos']; real_pending = self.fake.pending; calls = []
        def broken_once(client, **o):
            calls.append(1)
            if len(calls) == 1: raise ValueError('unexpected device output')
            return real_pending(client, **o)
        with patch.object(self.fake, 'pending', side_effect=broken_once):
            job = poll_job(self.client, self.submit_http(token).json()['id'])
        target = next(t for t in job['targets'] if t['name'] == 'ceos')
        self.assertEqual(target['status'], 'uncertain')
        self.assertTrue(dev.pending and dev.would_be_pending, 'the trial is still armed on the device')
        row = next(r for r in self.review(gen_id).json()['targets'] if r['name'] == 'ceos')
        self.assertFalse(row['ready'])
        self.assertIn('Another change is waiting for confirmation', row['reason'])
        with self.app.state.store.lock:
            ledger = self.app.state.store.lab(self.lab_id)['network_ownership']['ceos']
        self.assertTrue(ledger['pending'], 'the entry waits for the device to decide')
        self.assertEqual(ledger['statements'], [], 'nothing of a trial still running is owned')

        # The device's timer runs out and it undoes the trial: the next review finds the change absent.
        dev.pending = None; dev.armed = False; dev.would_be_pending = None
        row = next(r for r in self.review(gen_id).json()['targets'] if r['name'] == 'ceos')
        self.assertTrue(row['ready'], row.get('reason'))
        with self.app.state.store.lock:
            ledger = self.app.state.store.lab(self.lab_id)['network_ownership']['ceos']
        self.assertIsNone(ledger['pending'])
        self.assertEqual(ledger['statements'], [], 'the undone change left nothing owned')

    def _resolve_xr(self, running, added, desired):
        """Seed an `uncertain` IOS XR ledger entry and run the review's read-back of it on `running`."""
        with self.app.state.store.lock:
            lab = self.app.state.store.lab(self.lab_id)
            entry = {'statements': [], 'ancestors': [], 'generation_id': '', 'applied_at': '',
                     'pending': {'job_id': 'old', 'added': added, 'desired': desired, 'ancestors': []}}
            lab.setdefault('network_ownership', {})['xrv9k'] = copy.deepcopy(entry)
            self.app.state.store.save()
        driver = type('XrSnapshot', (), {'snapshot': staticmethod(lambda client, **o: running)})
        owned, _ = self.app.state.design_apply._resolve_pending(self.lab_id, 'cisco_xrv9k', 'xrv9k', entry, driver, None, {})
        with self.app.state.store.lock:
            ledger = copy.deepcopy(self.app.state.store.lab(self.lab_id)['network_ownership']['xrv9k'])
        return owned, ledger

    def test_an_xr_pending_entry_with_typed_negations_is_owned_when_the_change_is_active(self):
        # IOS XR's desired set carries the target buffer's typed negations, which the running configuration never
        # shows (PROVISIONING §8 "IOS XR negations"): the read-back judges them as the absence of their positive
        # form, the same test as the settle loop and verify() (audit M-6).
        address = 'interface GigabitEthernet0/0/0/0 > ipv4 address 10.1.0.1 255.255.255.252'
        added = [address, 'interface GigabitEthernet0/0/0/0 > no shutdown', 'lldp > no management enable']
        desired = added + ['interface GigabitEthernet0/0/0/0', 'lldp']
        active = ('hostname xrv9k\ninterface GigabitEthernet0/0/0/0\n ipv4 address 10.1.0.1 255.255.255.252\n!\nlldp\n!\nend\n')
        owned, ledger = self._resolve_xr(active, added, desired)
        self.assertIsNone(ledger['pending'])
        self.assertEqual(ledger['statements'], [address], 'the active change is owned; a negation is never a running statement')
        self.assertEqual(owned, {address})
        for label, running in (('still shut down', active.replace(' ipv4 address 10.1.0.1 255.255.255.252\n', ' ipv4 address 10.1.0.1 255.255.255.252\n shutdown\n')),
                               ('lldp management still on', active.replace('lldp\n', 'lldp\n management enable\n')),
                               ('address missing', active.replace(' ipv4 address 10.1.0.1 255.255.255.252\n', ''))):
            with self.subTest(label):
                owned, ledger = self._resolve_xr(running, added, desired)
                self.assertIsNone(ledger['pending'])
                self.assertEqual(ledger['statements'], [], 'the change is not there: nothing is owned from it')
                self.assertEqual(owned, set())

    def test_a_pending_entry_whose_change_is_present_becomes_owned_at_the_next_review(self):
        gen_id = self.default_generation()
        _, would_be_text, _, _, _, _, _ = _interface_only_plan() if '_interface_only_plan' in globals() else (None,) * 7
        added = ['interface Ethernet1 > ip address 10.0.0.5/30']
        with self.app.state.store.lock:
            lab = self.app.state.store.lab(self.lab_id)
            lab.setdefault('network_ownership', {})['ceos'] = {'statements': [], 'ancestors': [], 'generation_id': '', 'applied_at': '',
                                                                 'pending': {'job_id': 'old', 'added': added, 'desired': added, 'ancestors': []}}
            self.app.state.store.save()
        self.fake.set_running('ceos', BASELINE.replace('interface Ethernet1\n', 'interface Ethernet1\n   ip address 10.0.0.5/30\n', 1))
        body = self.review(gen_id).json()
        row = next(r for r in body['targets'] if r['name'] == 'ceos')
        self.assertTrue(row['ready'], row.get('reason'))
        with self.app.state.store.lock:
            ledger = self.app.state.store.lab(self.lab_id)['network_ownership']['ceos']
        self.assertIsNone(ledger['pending'])
        self.assertEqual(ledger['statements'], added, 'the change was read back present: its statements are owned')

    def test_an_armed_change_that_cannot_be_matched_with_the_review_is_not_confirmed(self):
        gen_id = self.default_generation()
        token = self._submit(gen_id)
        dev = self.fake.devices['ceos']
        dev.lose_after_arm = True
        released = []
        self.fake.release = lambda name: released.append(name)
        real_stage = self.fake.stage
        def stage_then_drift(client, candidate, removals, name, confirm_minutes=5, arm=False, **o):
            try: return real_stage(client, candidate, removals, name, confirm_minutes, arm, **o)
            finally:
                if arm and dev.would_be_pending is not None: dev.would_be_pending = dev.would_be_pending + 'banner motd X\n'   # the device runs something else than reviewed
        with patch.object(self.fake, 'stage', side_effect=stage_then_drift):
            submit = self.app.state.design_apply.submit(self.lab_id, token, 0, uuid.uuid4().hex, [])
            job = poll_job(self.client, submit['id'])
        target = next(t for t in job['targets'] if t['name'] == 'ceos')
        self.assertEqual(target['status'], 'uncertain')
        self.assertIn("left to the device's timer", target['message'])
        self.assertIsNotNone(dev.pending, 'nothing was confirmed: the device still holds the timer')
        self.assertTrue(released, 'a driver that holds the arming session is asked to release it')

    def test_a_driver_holding_the_session_is_released_when_the_timer_ran_out(self):
        gen_id = self.default_generation()
        token = self._submit(gen_id)
        self.fake.devices['ceos'].never_confirm = True
        released = []
        self.fake.release = lambda name: released.append(name)
        submit = self.app.state.design_apply.submit(self.lab_id, token, 0, uuid.uuid4().hex, [])
        job = poll_job(self.client, submit['id'])
        target = next(t for t in job['targets'] if t['name'] == 'ceos')
        self.assertEqual(target['status'], 'rolled_back')
        self.assertEqual(len(released), 1)
        self.assertRegex(released[0], r'^clabdsg-[0-9a-f]{8}$')


# --- 9. pre-change backup failures ------------------------------------------------------------------------

class BackupFailureTests(DesignApplyTestCase):
    def test_pre_change_backup_fails_for_one_device_others_proceed(self):
        gen_id = add_generation(self.app, self.lab_id, {**node_map('ceos'), **node_map('ceos2')},
                                {'ceos': [('initial', FRAGMENT)], 'ceos2': [('initial', FRAGMENT)]})
        ceos_full_name = _find_node(self.app.state.store.lab(self.lab_id), 'ceos')['name']
        self.runner.fail_nodes = {ceos_full_name}
        token = self.review(gen_id, targets=['ceos', 'ceos2']).json()['token']
        job_id = self.submit_http(token).json()['id']
        job = poll_job(self.client, job_id)
        failed = next(t for t in job['targets'] if t['name'] == 'ceos')
        ok = next(t for t in job['targets'] if t['name'] == 'ceos2')
        self.assertEqual(failed['status'], 'failed')
        self.assertIn('pre-change backup', failed['message'])
        self.assertEqual(ok['status'], 'verified')

    def test_runner_refuses_the_pre_change_backup_entirely(self):
        gen_id = self.default_generation()
        self.runner.refuse_sources = {'design-pre'}
        token = self.review(gen_id).json()['token']
        job_id = self.submit_http(token).json()['id']
        job = poll_job(self.client, job_id)
        self.assertEqual(job['status'], 'failed')
        self.assertFalse(self.fake.devices['ceos'].armed)
        self.assertIsNone(job.get('pre_backup_job_id'))


# --- 10. busy guards -------------------------------------------------------------------------------------

class BusyGuardTests(DesignApplyTestCase):
    def test_operation_busy_is_scoped_by_lab_and_excludes_its_own_progress_id(self):
        store = self.app.state.store
        with store.lock:
            store.state.setdefault('design_jobs', []).append({'id': 'job-x', 'lab_id': self.lab_id, 'status': 'applying', 'targets': []})
            store.save()
        self.assertTrue(operation_busy(store.state, self.lab_id))
        self.assertFalse(operation_busy(store.state, self.lab_id, progress_id='job-x'))
        # A design apply busy on another lab does not block this one through `operation_busy` (it is
        # lab-scoped); `Runner.submit`'s own, separate design-apply guard (below) is not lab-scoped.
        self.assertFalse(operation_busy(store.state, 'some-other-lab'))

    def test_runner_refuses_a_manual_backup_while_a_design_is_applying_but_allows_its_own(self):
        store = self.app.state.store
        # `Runner.submit`'s `DESIGN_APPLY_BUSY` guard is not lab-scoped, unlike `operation_busy`
        # (which is checked first and is lab-scoped): use a job on a different lab so that guard,
        # specifically, is what raises.
        other_lab_id = add_lab(self.app, name='other', definition_yaml=TWO_CEOS_TOPOLOGY)
        with store.lock:
            store.state.setdefault('design_jobs', []).append({'id': 'job-y', 'lab_id': other_lab_id, 'status': 'applying', 'targets': []})
            store.save()
        real_runner = Runner(store)
        self.addCleanup(real_runner.close)
        with patch.object(real_runner.pool, 'submit'):
            with self.assertRaises(ValueError) as caught:
                real_runner.submit(self.lab_id, operation='backup', source='manual')
            self.assertIn('being applied', str(caught.exception))
            # The apply's own backups pass the busy job's id as progress_id and are allowed through
            # this specific guard (other guards, e.g. node readiness, are not exercised here).
            try:
                real_runner.submit(self.lab_id, operation='backup', source='design-pre',
                                   node_names=[_find_node(store.lab(self.lab_id), 'ceos')['name']],
                                   progress_id='job-y')
            except ValueError as exc:
                self.assertNotIn('being applied', str(exc))

    def test_restore_guard_idle_refuses_while_a_design_is_applying(self):
        store = self.app.state.store
        with store.lock:
            store.state.setdefault('design_jobs', []).append({'id': 'job-z', 'lab_id': self.lab_id, 'status': 'applying', 'targets': []})
            store.save()
        real_runner = Runner(store)
        self.addCleanup(real_runner.close)
        restore_service = RestoreService(store, real_runner, object(), connector=fake_connect)
        with self.assertRaises(Exception) as restore_caught:
            restore_service.guard_idle(self.lab_id)
        self.assertEqual(getattr(restore_caught.exception, 'status_code', None), 409)

    def _reading_back(self):
        """A job of this lab whose devices are still read back after a restart: `interrupted` with `rechecking`
        (audit L-15). Its status is no longer in DESIGN_APPLY_BUSY, so only `rechecking` can hold the lab."""
        store = self.app.state.store
        other_lab_id = add_lab(self.app, name='other', definition_yaml=TWO_CEOS_TOPOLOGY)
        with store.lock:
            store.state.setdefault('design_jobs', []).append(
                {'id': 'job-r', 'lab_id': self.lab_id, 'status': 'interrupted', 'rechecking': ['ceos'], 'targets': []})
            store.save()
        return store, other_lab_id

    def test_the_read_back_after_a_restart_never_holds_another_lab_or_a_check_that_names_no_lab(self):
        # The read-back waits out an IOS XR trial at the device's timer (up to about 31 minutes): other labs, and the
        # callers that name no lab (background discovery, Git's idle check, a lab-operation submit that names no lab),
        # stay free. A lab operation of the lab under read-back is held (review follow-up K3, the next test).
        store, other_lab_id = self._reading_back()
        self.assertFalse(operation_busy(store.state, other_lab_id), 'another lab stays free')
        self.assertFalse(operation_busy(store.state))
        with store.lock:
            self.app.state.operations.guard(other_lab_id)
            self.app.state.operations.guard()
        real_runner = Runner(store)
        self.addCleanup(real_runner.close)
        RestoreService(store, real_runner, object(), connector=fake_connect).guard_idle(other_lab_id)
        with patch.object(real_runner.pool, 'submit'):
            try: real_runner.submit(other_lab_id, operation='backup', source='manual')
            except ValueError as exc:   # other guards (node readiness) may refuse; the read-back must not
                self.assertNotIn('Wait for the lab operation', str(exc))

    def test_a_restore_and_a_backup_of_the_lab_under_read_back_are_refused_until_it_settles(self):
        # A restore arming its own `commit confirmed` on the lab under read-back would be read back as a foreign
        # pending change (`uncertain`) or, when the restored text holds the reviewed statements, as `verified`.
        store, other_lab_id = self._reading_back()
        self.assertTrue(operation_busy(store.state, self.lab_id))
        self.assertTrue(operation_busy(store.state, self.lab_id, progress_id='some-restore'))
        real_runner = Runner(store)
        self.addCleanup(real_runner.close)
        restore_service = RestoreService(store, real_runner, object(), connector=fake_connect)
        with self.assertRaises(Exception) as restore_caught:
            restore_service.guard_idle(self.lab_id)
        self.assertEqual(getattr(restore_caught.exception, 'status_code', None), 409)
        with patch.object(real_runner.pool, 'submit'):
            with self.assertRaises(ValueError) as caught:
                real_runner.submit(self.lab_id, operation='backup', source='manual')
            self.assertIn('Wait for the lab operation', str(caught.exception))
        with store.lock:
            store.state['design_jobs'][-1].pop('rechecking')
            store.save()
        self.assertFalse(operation_busy(store.state, self.lab_id), 'once read back, the lab is free')
        restore_service.guard_idle(self.lab_id)

    def test_a_lab_operation_of_the_lab_under_read_back_is_refused_until_it_settles(self):
        # Review follow-up K3 (audit L-15): Deploy, Destroy and Restart device of that lab were accepted (LabOperations.guard
        # asked operation_busy without a lab), so the read-back could record `rolled_back` or `uncertain` about a device the
        # manager itself had rebooted. The stricter claim: the lab under read-back is held for its lab operations and its
        # map and setting edits too; another lab and an operation that names no lab stay free (the test above).
        store, other_lab_id = self._reading_back()
        operations = self.app.state.operations
        with store.lock:
            with self.assertRaises(da.HTTPException) as caught: operations.guard(self.lab_id)
        self.assertEqual(caught.exception.status_code, 409)
        self.assertIn('Wait for the current lab operation', caught.exception.detail)
        with patch('app.lab_operations.remote') as remote:
            for action, extra in (('deploy', {}), ('destroy', {}), ('restart-node', {'node': 'ceos'})):
                refused = self.client.post('/api/operations/preview', json=dict(action=action, lab_id=self.lab_id, **extra))
                self.assertEqual(refused.status_code, 409, (action, refused.text))
            for path, body in ((f'/api/labs/{self.lab_id}/layout', {'positions': {}}),
                               (f'/api/labs/{self.lab_id}/operations-settings', {'favorite': True})):
                self.assertEqual(self.client.put(path, json=body).status_code, 409, path)
            remote.assert_not_called()                                   # refused before the VM is asked anything
        with store.lock:
            store.state['design_jobs'][-1].pop('rechecking')
            store.save()
        with store.lock: operations.guard(self.lab_id)                    # once read back, the lab is free

    def test_start_fresh_and_a_vm_connection_change_wait_for_the_read_back(self):
        # Both refuse during a restore's read-back (operation_busy without a lab); a design apply's read-back holds them
        # the same way and with the same words: Start fresh would drop the job that is reading the devices back, and a
        # new VM connection would point the read-back at another VM's devices (review follow-up K3).
        store, _ = self._reading_back()
        host = {k: store.state['host'][k] for k in ('address', 'port', 'username', 'password')}
        changed = self.client.put('/api/host', json=host)
        self.assertEqual(changed.status_code, 409, changed.text)
        self.assertEqual(changed.json()['detail'], 'Wait for the lab operation to finish.')
        reset = self.client.post('/api/manager/reset', json={'confirmation': 'RESET'})
        self.assertEqual(reset.status_code, 409, reset.text)
        self.assertEqual(reset.json()['detail'], 'Wait for the current lab operation to finish.')
        self.assertEqual(len(store.state['labs']), 2, 'nothing was reset')
        with store.lock:
            store.state['design_jobs'][-1].pop('rechecking')
            store.save()
        self.assertEqual(self.client.put('/api/host', json=host).status_code, 200)
        self.assertEqual(self.client.post('/api/manager/reset', json={'confirmation': 'RESET'}).status_code, 200)

    def test_the_page_sees_the_read_back_while_it_holds_the_lab_and_not_after(self):
        # The page shows the lab as "Checking devices" from the public job's `rechecking` list (status.js): it must
        # reach /api/state and the job routes while the read-back holds the lab, and be gone once it settled (audit L-15).
        store, _ = self._reading_back()
        with store.lock:
            job = store.state['design_jobs'][-1]
            job['targets'] = [{'name': 'ceos', 'status': 'interrupted', '_candidate': 'interface Ethernet1', '_session': 'clabdsg-1'}]
            store.save()
        def seen():
            state_job = next(j for j in self.client.get('/api/state').json()['design_jobs'] if j['id'] == 'job-r')
            return state_job, self.client.get('/api/design/apply/jobs/job-r').json(), next(
                j for j in self.client.get(f'/api/labs/{self.lab_id}/design/apply/jobs').json() if j['id'] == 'job-r')
        for public in seen():
            self.assertEqual(public.get('rechecking'), ['ceos'])
            self.assertEqual([t['name'] for t in public['targets']], ['ceos'], 'the names it lists are public already')
            self.assertNotIn('_candidate', json.dumps(public))
            self.assertNotIn('_session', json.dumps(public))
        self.app.state.design_apply._rechecked('job-r', 'ceos')
        for public in seen(): self.assertNotIn('rechecking', public)
        with store.lock: self.assertNotIn('rechecking', store.state['design_jobs'][-1])

# --- 11. restart reconciliation --------------------------------------------------------------------------

def _interface_only_plan():
    """A single-leaf candidate (no ospf, to keep this test independent of FRAGMENT) and the pieces
    a restart-interrupted target would have recorded: the before/would-be statement sets, the desired
    set (device-rendered on an empty base) and the created ancestors."""
    interface_candidate = 'interface Ethernet1\n   no switchport\n   ip address 10.0.0.5/30\n!\n'
    before_stmts = own.statements(KIND, BASELINE)
    would_be_text = _merge(BASELINE, interface_candidate, [])
    would_be_stmts = own.statements(KIND, would_be_text)
    desired = own.statements(KIND, CLEAN_BASE + interface_candidate) - own.statements(KIND, CLEAN_BASE)
    added = would_be_stmts - before_stmts
    ancestors = own.created_ancestors(KIND, added, before_stmts)
    return interface_candidate, would_be_text, before_stmts, would_be_stmts, desired, added, ancestors


class RestartReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.fake = FakeDriver()
        self.fake.register('ceos', BASELINE)
        patcher = patch('app.design_apply.DRIVERS', {KIND: self.fake})
        patcher.start()
        self.addCleanup(patcher.stop)

    def _build(self, running_at_recheck):
        store = Store(self.tmp.name)
        nodes = parse_definition(TWO_CEOS_TOPOLOGY.encode())['nodes']
        lab_id = uuid.uuid4().hex
        lab = dict(id=lab_id, name='reconcile', nodes=nodes, profiles=[], defaults={}, interval=0, next_run=None,
                   definition_yaml=TWO_CEOS_TOPOLOGY)
        ceos = _find_node(lab, 'ceos')
        ceos.update(username='admin', password='admin', enable_password='ceos', discovered=True,
                    runtime_state='running', discovered_address=ceos['address'], endpoint_mode='manual')
        lab['deployment_name'] = 'reconcile'
        store.state['labs'].append(lab)
        store.state['host'] = {'enabled': True, 'address': '10.0.0.1', 'port': 22, 'username': 'clab',
                               'password': 'x', 'fingerprint': 'SHA256:fix', 'auth': 'password'}
        store.state['discovery'] = {'ok': True, 'checked_epoch': time.time(), 'checked_at': 'x', 'last_success': 'x', 'labs': {}}

        interface_candidate, would_be_text, before_stmts, would_be_stmts, desired, added, ancestors = _interface_only_plan()
        session = 'clabdsg-11111111'
        job_id = uuid.uuid4().hex
        target = {'name': 'ceos', 'kind': KIND, 'status': 'applying', 'stage': 'applying', 'message': 'Staging.',
                  'timeline': {'queued': time.time(), 'applying': time.time()},
                  '_session': session, '_before_digest': da.digest_of(before_stmts),
                  '_desired': sorted(desired), '_added': sorted(added), '_stale': [],
                  '_ancestors': sorted(ancestors), '_removed_ancestors': [], '_candidate': interface_candidate,
                  '_removals': [], '_would_be_digest': da.digest_of(would_be_stmts),
                  # Recorded by `_apply_one` once staging succeeds, before the settle path is entered;
                  # a target interrupted mid-transaction with the timer already armed carries it too.
                  '_armed': True}
        job = {'id': job_id, 'request_id': uuid.uuid4().hex, 'lab_id': lab_id, 'lab_name': 'reconcile',
               'generation_id': 'a' * 32, 'created': runner_now(), 'started': runner_now(), 'status': 'applying',
               'message': 'Applying.', 'confirm_minutes': 5, 'host_identity': '', 'takeover': [],
               'targets': [target], 'progress': {'settled': 0, 'total': 1}}
        store.state.setdefault('design_jobs', []).append(job)
        store.save()

        self.fake.devices['ceos'].running = running_at_recheck
        self.fake.devices['ceos'].pending = None

        network_design = NetworkDesign(store)
        self.addCleanup(network_design.close)
        service = da.DesignApply(store, runner=None, network_design=network_design)
        self.addCleanup(service.close)
        service.connect = fake_connect
        service.retry_interval = 0.05
        service.recovery_grace = 0.05
        service.connect_pause = 0.05
        return store, service, job_id, lab_id, would_be_text

    def test_construction_marks_job_and_target_interrupted(self):
        store, service, job_id, lab_id, would_be_text = self._build(BASELINE)
        job = next(j for j in store.state['design_jobs'] if j['id'] == job_id)
        self.assertEqual(job['status'], 'interrupted')
        self.assertEqual(job['targets'][0]['status'], 'interrupted')

    def _wait_settled(self, store, service, job_id, timeout=10):
        service.start()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            job = next(j for j in store.state['design_jobs'] if j['id'] == job_id)
            if job['status'] not in da.DESIGN_APPLY_BUSY and job['status'] != 'interrupted':
                return job
            if job['targets'][0]['status'] not in da.IN_FLIGHT and job['targets'][0]['status'] != 'interrupted':
                return job
            time.sleep(0.05)
        raise AssertionError('Reconciliation did not settle in time')

    def test_recheck_with_desired_statements_present_is_verified(self):
        _, would_be_text, _, _, _, _, _ = _interface_only_plan()
        store, service, job_id, lab_id, _ = self._build(would_be_text)
        job = self._wait_settled(store, service, job_id)
        target = job['targets'][0]
        self.assertEqual(target['status'], 'verified')
        with store.lock:
            self.assertIn('interface Ethernet1 > ip address 10.0.0.5/30', store.lab(lab_id)['network_ownership']['ceos']['statements'])

    def test_recheck_with_pre_apply_text_back_is_rolled_back(self):
        store, service, job_id, lab_id, would_be_text = self._build(BASELINE)
        job = self._wait_settled(store, service, job_id)
        target = job['targets'][0]
        self.assertEqual(target['status'], 'rolled_back')

    def test_the_interrupted_job_says_what_the_read_back_came_to(self):
        store, service, job_id, lab_id, would_be_text = self._build(BASELINE)
        self._wait_settled(store, service, job_id)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            job = next(j for j in store.state['design_jobs'] if j['id'] == job_id)
            if 'Read back afterwards' in job['message']: break
            time.sleep(0.05)
        self.assertEqual(job['status'], 'interrupted', 'the job stays interrupted: the record says what happened')
        self.assertIn('Read back afterwards: ceos undone by the device.', job['message'])
        self.assertNotIn('is undone by the device itself', job['message'])


class RecheckConcurrencyTests(DesignApplyTestCase):
    """The read-back after a restart (audit L-15): an IOS XR trial nobody can confirm any more is waited out at the
    device's own timer, up to 30 minutes. That wait must neither hold the single apply worker (a new apply on another
    lab would sit `queued`, and a queued apply makes the Runner refuse every backup and restore on every lab) nor
    leave the lab under read-back free for a new apply."""

    def _restart_with_an_unconfirmable_trial(self, rechecking=None, deadline_in=120, **target_fields):
        """Lab `other` has an apply in flight on its `ceos`, whose trial nobody can confirm (the IOS XR case after a
        restart: `pending` answers True); the manager restarts and starts its read-back."""
        other = add_lab(self.app, name='other', definition_yaml=TWO_CEOS_TOPOLOGY)
        set_credentials(self.app, other, 'ceos', enable_password='under-recheck')
        self.fake.register('under-recheck', BASELINE)
        dev = self.fake.devices['under-recheck']; dev.pending = True
        candidate, _, before, would_be, desired, added, ancestors = _interface_only_plan()
        target = {'name': 'ceos', 'kind': KIND, 'status': 'confirming', 'stage': 'armed', 'message': 'Change armed.',
                  'timeline': {'queued': time.time()}, '_session': 'clabdsg-22222222', '_before_digest': da.digest_of(before),
                  '_desired': sorted(desired), '_added': sorted(added), '_stale': [], '_ancestors': sorted(ancestors),
                  '_removed_ancestors': [], '_candidate': candidate, '_removals': [], '_would_be_digest': da.digest_of(would_be),
                  '_armed': True, '_deadline': time.time() + deadline_in}
        target.update(target_fields)
        job = {'id': uuid.uuid4().hex, 'request_id': uuid.uuid4().hex, 'lab_id': other, 'lab_name': 'other', 'generation_id': 'b' * 32,
               'created': runner_now(), 'started': runner_now(), 'status': 'confirming', 'message': 'Applying.', 'confirm_minutes': 30,
               'host_identity': '', 'takeover': [], 'targets': [target], 'progress': {'settled': 0, 'total': 1}}
        if rechecking is not None:   # a restart during an earlier restart's read-back
            job.update(status='interrupted', rechecking=rechecking); target.update(status='interrupted', stage='verifying')
        with self.app.state.store.lock:
            self.app.state.store.state.setdefault('design_jobs', []).append(job)
            self.app.state.store.save()
        # The restart: a new app on the same data directory; its design service marks the job and reads it back.
        self.app.state.design_apply.close()
        self.app = create_app(self.tmp.name)
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)
        self.addCleanup(self.app.state.design_apply.close)
        self.addCleanup(self.app.state.network_design.close)
        service = self.app.state.design_apply
        service.connect = fake_connect
        service.retry_interval = 0.05; service.recovery_grace = 0.05; service.connect_pause = 0.05
        self.runner = FakeRunner(self.app.state.store); service.runner = self.runner
        seed_discovery(self.app, self.lab_id)   # a new process trusts no discovery of the old one
        service.start()
        return other, job['id'], dev

    def _job(self, job_id):
        with self.app.state.store.lock: return copy.deepcopy(next(j for j in self.app.state.store.state['design_jobs'] if j['id'] == job_id))

    def _wait(self, check, timeout=10):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if check(): return
            time.sleep(0.05)
        raise AssertionError('condition not reached in time')

    def test_a_new_apply_on_another_lab_is_not_queued_behind_the_read_back(self):
        other, job_id, dev = self._restart_with_an_unconfirmable_trial()
        self._wait(lambda: self._job(job_id)['targets'][0].get('attempts', 0) >= 2)   # the read-back is waiting for the trial
        gen_id = self.default_generation()
        reviewed = self.review(gen_id).json()
        self.assertIn('token', reviewed, reviewed)
        token = reviewed['token']
        job = poll_job(self.client, self.submit_http(token).json()['id'], timeout=10)
        self.assertEqual(next(t for t in job['targets'] if t['name'] == 'ceos')['status'], 'verified',
                         'the apply ran while the other lab was still being read back')
        self.assertEqual(self._job(job_id)['targets'][0]['status'], 'interrupted', 'the read-back is still waiting for the trial')

    def test_the_lab_under_read_back_is_held_until_its_devices_settle(self):
        other, job_id, dev = self._restart_with_an_unconfirmable_trial()
        self._wait(lambda: self._job(job_id)['targets'][0].get('attempts', 0) >= 2)
        self.assertEqual(self._job(job_id)['status'], 'interrupted')
        self.assertEqual(self._job(job_id).get('rechecking'), ['ceos'], 'the job records which devices are still read back')
        with self.app.state.store.lock:
            with self.assertRaises(da.HTTPException) as caught: self.app.state.design_apply.guard_idle(other)
            self.assertEqual(caught.exception.status_code, 409)
            self.assertIn('reading back', caught.exception.detail)
            self.app.state.design_apply.guard_idle(self.lab_id)   # another lab is not held
        # The device's timer runs out and it undoes the trial: the read-back settles and the lab is free again.
        dev.pending = None
        self._wait(lambda: 'Read back afterwards' in self._job(job_id)['message'])
        job = self._job(job_id)
        self.assertEqual(job['targets'][0]['status'], 'rolled_back')
        self.assertNotIn('rechecking', job)
        self.assertNotIn('rechecking', da.public_job(job))
        with self.app.state.store.lock: self.app.state.design_apply.guard_idle(other)

    def test_a_restart_during_the_read_back_reads_the_rest_back_and_never_leaves_the_lab_held(self):
        other, job_id, dev = self._restart_with_an_unconfirmable_trial(rechecking=['ceos'], deadline_in=-120)
        dev.pending = None; dev.running = _interface_only_plan()[1]   # the trial was confirmed before the first restart
        self._wait(lambda: 'Read back afterwards' in self._job(job_id)['message'])
        job = self._job(job_id)
        self.assertEqual(job['status'], 'interrupted')
        self.assertEqual(job['targets'][0]['status'], 'verified')
        self.assertNotIn('rechecking', job)
        with self.app.state.store.lock: self.app.state.design_apply.guard_idle(other)

    def test_a_read_back_that_fails_inside_the_manager_leaves_the_device_uncertain_not_unchanged(self):
        # A stored deadline the read-back cannot use (a corrupt record) makes `_recheck` raise before it reaches the
        # device. The trial may have been confirmed before the restart, so the device is never worded "not changed":
        # it is `uncertain` with a pending ledger entry that the next review settles, and the lab is freed.
        other, job_id, dev = self._restart_with_an_unconfirmable_trial(rechecking=['ceos'], _deadline='not-a-time')
        self._wait(lambda: 'Read back afterwards' in self._job(job_id)['message'])
        job = self._job(job_id)
        self.assertEqual(job['status'], 'interrupted')
        self.assertEqual(job['targets'][0]['status'], 'uncertain')
        self.assertIn('ceos outcome unknown', job['message'])
        self.assertNotIn('not changed', job['message'])
        self.assertNotIn('rechecking', job)
        with self.app.state.store.lock:
            pending = self.app.state.store.lab(other)['network_ownership']['ceos']['pending']
            self.app.state.design_apply.guard_idle(other)
        self.assertEqual(pending['job_id'], job_id)
        self.assertEqual(sorted(pending['added']), sorted(_interface_only_plan()[5]))


# --- 12. pure helper functions ------------------------------------------------------------------------

class PublicHelperTests(unittest.TestCase):
    def test_public_job_strips_underscore_keys_and_adds_server_time(self):
        job = {'id': 'j1', 'lab_id': 'l1', 'lab_name': 'lab', 'status': 'succeeded', 'targets':
                [{'name': 'ceos', 'status': 'verified', '_secret': 'x', '_candidate': 'config text'}]}
        public = da.public_job(job)
        self.assertIn('server_time', public)
        self.assertNotIn('_secret', public['targets'][0])
        self.assertNotIn('_candidate', public['targets'][0])
        self.assertEqual(public['targets'][0]['name'], 'ceos')

    def test_append_job_keeps_busy_and_interrupted_jobs_beyond_the_cap(self):
        state = {'design_jobs': [{'id': str(i), 'status': 'succeeded', 'targets': []} for i in range(da.JOB_CAP)]}
        state['design_jobs'][0]['status'] = 'interrupted'
        da._append_job(state, {'id': 'busy', 'status': 'applying', 'targets': []})
        self.assertGreater(len(state['design_jobs']), da.JOB_CAP)
        ids = [j['id'] for j in state['design_jobs']]
        self.assertIn('0', ids)
        self.assertIn('busy', ids)

    def test_public_ownership_counts(self):
        lab = {'network_ownership': {'ceos': {'statements': ['a', 'b', 'c'], 'generation_id': 'g1',
                                              'applied_at': 't', 'pending': None},
                                     'ceos2': {'statements': [], 'generation_id': '', 'applied_at': '', 'pending': {'job_id': 'x'}}}}
        summary = da.public_ownership(lab)
        self.assertEqual(summary['ceos']['statements'], 3)
        self.assertFalse(summary['ceos']['pending'])
        self.assertTrue(summary['ceos2']['pending'])


# --- 13. partial outcomes across two targets --------------------------------------------------------------

class PartialOutcomeTests(DesignApplyTestCase):
    def _two_node_generation(self):
        return add_generation(self.app, self.lab_id, {**node_map('ceos'), **node_map('ceos2')},
                              {'ceos': [('initial', FRAGMENT)], 'ceos2': [('initial', FRAGMENT)]})

    def test_partial_when_one_fails_and_one_verifies(self):
        gen_id = self._two_node_generation()
        token = self.review(gen_id, targets=['ceos', 'ceos2']).json()['token']
        self.fake.devices['ceos'].reject_load = True
        job_id = self.submit_http(token).json()['id']
        job = poll_job(self.client, job_id)
        self.assertEqual(job['status'], 'partial')
        failed = next(t for t in job['targets'] if t['name'] == 'ceos')
        ok = next(t for t in job['targets'] if t['name'] == 'ceos2')
        self.assertEqual(failed['status'], 'failed')
        self.assertEqual(ok['status'], 'verified')

    def test_needs_attention_when_one_is_uncertain(self):
        gen_id = self._two_node_generation()
        token = self.review(gen_id, targets=['ceos', 'ceos2']).json()['token']
        self.fake.devices['ceos'].foreign_after_arm = 'clabmgr-deadbeef'
        submitted = self.app.state.design_apply.submit(self.lab_id, token, 0, uuid.uuid4().hex, [])
        job = poll_job(self.client, submitted['id'])
        self.assertEqual(job['status'], 'needs_attention')
        uncertain = next(t for t in job['targets'] if t['name'] == 'ceos')
        ok = next(t for t in job['targets'] if t['name'] == 'ceos2')
        self.assertEqual(uncertain['status'], 'uncertain')
        self.assertEqual(ok['status'], 'verified')


if __name__ == '__main__':
    unittest.main()
