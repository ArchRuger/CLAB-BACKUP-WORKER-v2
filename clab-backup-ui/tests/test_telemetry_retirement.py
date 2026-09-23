"""Retirement of the removed telemetry feature: the startup migration of its ledger, the public summary,
the lab page's view and the explicit removal of the recorded device lines. Devices are scripted fakes:
no network, no live data."""
import copy
import json
import socket
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import telemetry_retirement as retirement
from app.main import create_app
from app.store import Store
from app.lab_operations import operation_busy
from app.telemetry_retirement import migrate_retired_telemetry, plan_block, plan_junos, public_retired_telemetry

EOS = 'clab-square-ceos1'
XR = 'clab-square-xr1'
JUNOS = 'clab-square-cjunos1'
HOST = 'clab-square-host'
EOS_LINES = ['management api gnmi', '   transport grpc default']
XR_LINES = ['grpc', ' port 57400', ' no-tls']
GRPC = 'set system services extension-service request-response grpc'
JUNOS_LINES = [GRPC + ' clear-text port 32767']
NOTIFICATION = 'set system services extension-service notification allow-clients address 0.0.0.0/0'
# Text that only ever appears in configuration: none of it may reach an event, a message or /api/state.
CONFIG_TEXT = ('management api', 'transport grpc', 'no-tls', 'extension-service', 'port 57400', 'clear-text', 'port 32767')
AT = '2026-09-18T10:00:00+00:00'


def node(name, short, platform, address, **extra):
    row = {'name': name, 'short_name': short, 'definition_node': short, 'address': address, 'port': 22,
           'platform': platform, 'enabled': bool(platform), 'profile_id': '', 'username': 'admin',
           'password': 'node-secret-' + short, 'enable_password': '', 'groups': [], 'endpoint_mode': 'auto',
           'discovered': True, 'runtime_state': 'running', 'discovered_address': address}
    row.update(extra)
    return row


def make_lab(lab_id='lab1', telemetry=None, **extra):
    lab = {'id': lab_id, 'name': 'Restore square', 'deployment_name': 'square', 'container_prefix': 'clab',
           'profiles': [{'id': 'p1', 'label': 'EOS admin', 'platform': 'arista_ceos', 'username': 'admin',
                         'auth': 'password', 'password': 'profile-secret'}],
           'defaults': {}, 'interval': 0, 'next_run': None, 'created': '2026-09-01T00:00:00+00:00',
           'nodes': [node(EOS, 'ceos1', 'arista_ceos', '192.0.2.11'), node(XR, 'xr1', 'cisco_xrv9k', '192.0.2.12'),
                     node(JUNOS, 'cjunos1', 'juniper_cjunosevolved', '192.0.2.13'),
                     node(HOST, 'host', '', '192.0.2.14', username='', password='')],
           'drawing': {'nodes': {'ceos1': {'x': 1, 'y': 2}}}, 'last_deployed': '2026-09-18T09:00:00+00:00'}
    if telemetry is not None:
        lab['telemetry'] = telemetry
    lab.update(extra)
    return lab


def ledger(**entries):
    return {'auto': False, 'decided': True, 'profile_id': '',
            'applied': {name: {'lines': lines, 'at': AT, 'kind': kind} for name, (lines, kind) in entries.items()}}


def events(root):
    path = Path(root) / 'events.jsonl'
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


# ---- scripted devices --------------------------------------------------------------------------------

class Device:
    """A NOS CLI: echoes each line, answers from its configuration and prints its prompt."""

    def __init__(self, hang=()):
        self.sent = []
        self.mode = 'exec'
        self.hang = hang

    def on_line(self, line):
        self.sent.append(line)
        if line in self.hang:
            return b''
        output = self.answer(line)
        return (line + '\r\n' + (output + '\r\n' if output else '') + self.prompt() + ' ').encode()


class Channel:
    def __init__(self, device):
        self.device = device
        self.inbuf = bytearray((device.prompt() + ' ').encode())
        self.outbuf = b''
        self.closed = False

    def settimeout(self, _):
        pass

    def sendall(self, data):
        self.outbuf += data
        while b'\n' in self.outbuf:
            line, self.outbuf = self.outbuf.split(b'\n', 1)
            self.inbuf += self.device.on_line(line.decode())

    def recv(self, n):
        if self.closed:
            return b''
        if not self.inbuf:
            time.sleep(0.002)
            raise socket.timeout()
        chunk = bytes(self.inbuf[:n])
        del self.inbuf[:n]
        return chunk

    def close(self):
        self.closed = True


class FakeEos(Device):
    def __init__(self, block, pending=False, reject=(), unprivileged=False, garbled=False, **kw):
        super().__init__(**kw)
        self.block, self.pending, self.reject, self.unprivileged, self.garbled = list(block), pending, reject, unprivileged, garbled

    def prompt(self):
        return 'ceos1(config)#' if self.mode == 'config' else 'ceos1>' if self.unprivileged else 'ceos1#'

    def answer(self, line):
        if line in self.reject:
            return '% Invalid input'
        if line == 'enable':
            return '% Access denied'
        if line.startswith('terminal '):
            return ''
        if line == 'show running-config | section management api gnmi':
            if self.unprivileged:
                return '% Invalid input (privileged mode required)'
            return 'Error: the configuration is not available right now' if self.garbled else '\r\n'.join(self.block)
        if line == 'show configuration sessions detail':
            return 'Session with pending commit timer: s1' if self.pending else 'Maximum number of completed sessions: 1'
        if line == 'configure terminal':
            self.mode = 'config'
            return ''
        if line == 'no management api gnmi' and self.mode == 'config':
            self.block = []
            return ''
        if line == 'end':
            self.mode = 'exec'
            return ''
        return '% Invalid input'


class FakeXr(Device):
    def __init__(self, block, reject=(), trial=False, **kw):
        super().__init__(**kw)
        self.running, self.candidate, self.reject, self.trial = list(block), None, reject, trial

    def prompt(self):
        return 'RP/0/RP0/CPU0:xr1' + {'grpc': '(config-grpc)#', 'config': '(config)#'}.get(self.mode, '#')

    def answer(self, line):
        if line in self.reject:
            return '% Failed to commit one or more configuration items during a pseudo-atomic operation.'
        if line.startswith('terminal '):
            return ''
        if line == 'show running-config grpc':
            body = '\r\n'.join(self.running + ['!']) if self.running else '% No such configuration item(s)'
            return 'Tue Sep 23 10:00:00.000 UTC\r\n' + body
        if line == 'show configuration sessions detail':
            return '1) Session: 1\r\n   Client: commit-confirm' if self.trial else ''
        if line == 'configure terminal':
            self.mode, self.candidate = 'config', list(self.running)
            return ''
        if self.mode in ('config', 'grpc'):
            if line == 'no grpc':
                self.candidate = []
                return ''
            if line == 'grpc':
                self.mode = 'grpc'
                return ''
            if line.startswith('no ') and self.mode == 'grpc' and ' ' + line[3:] in self.candidate:
                self.candidate.remove(' ' + line[3:])
                return ''
            if line == 'commit':
                self.running = list(self.candidate)
                return ''
            if line in ('end', 'abort'):
                self.mode, self.candidate = 'exec', None
                return ''
        return "% Invalid input detected at '^' marker."


class FakeJunos(Device):
    def __init__(self, lines, reject_commit=False, pending=False, stubborn=False, **kw):
        super().__init__(**kw)
        self.running, self.candidate, self.reject_commit, self.pending = list(lines), None, reject_commit, pending
        self.stubborn = stubborn        # accepts the delete but keeps the lines (the read-back must notice)

    def prompt(self):
        return 'admin@cjunos1#' if self.mode == 'config' else 'admin@cjunos1>'

    def answer(self, line):
        if line.startswith('set cli '):
            return ''
        if line == 'show configuration system services extension-service | display set':
            return '\r\n'.join(l for l in self.running if ' system services extension-service ' in l)
        if line == 'show system commit | no-more':
            newest = '0   2026-09-23 10:00:00 UTC by admin via cli'
            return newest + (' commit confirmed, rollback in 5mins\r\n    rollback pending' if self.pending else '')
        if line == 'configure private':
            self.mode, self.candidate = 'config', list(self.running)
            return 'warning: uncommitted changes will be discarded on exit\r\nEntering configuration mode\r\n\r\n[edit]'
        if self.mode == 'config':
            if line.startswith('delete '):
                path = 'set ' + line[len('delete '):]
                if not self.stubborn:
                    self.candidate = [l for l in self.candidate if not (l == path or l.startswith(path + ' '))]
                return '\r\n[edit]'
            if line == 'commit and-quit':
                if self.reject_commit:
                    return 'error: configuration check-out failed\r\n\r\n[edit]'
                self.running, self.mode = list(self.candidate), 'exec'
                return 'commit complete\r\nExiting configuration mode'
            if line == 'rollback 0':
                self.candidate = list(self.running)
                return 'load complete\r\n\r\n[edit]'
            if line == 'exit configuration-mode':
                self.mode = 'exec'
                return 'Exiting configuration mode'
        return 'syntax error.'


# ---- migration -----------------------------------------------------------------------------------------

class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def retired_events(self):
        return [e for e in events(self.tmp.name) if e['action'].startswith('telemetry.retired')]

    def test_default_setting_is_dropped_and_nothing_else_changes(self):
        lab = make_lab(telemetry={'auto': True, 'decided': True, 'profile_id': '', 'applied': {}})
        other = make_lab('lab2')
        self.store.state['labs'] = [lab, other]
        expected = [{k: v for k, v in copy.deepcopy(lab).items() if k != 'telemetry'}, copy.deepcopy(other)]
        summary = migrate_retired_telemetry(self.store)
        self.assertEqual(summary, {'labs': 1, 'kept': {}, 'malformed': []})
        self.assertEqual(self.store.state['labs'], expected)
        self.assertEqual(json.dumps(self.store.state['labs']), json.dumps(expected))   # key order kept too
        self.assertEqual(Store(self.tmp.name).state['labs'], expected)                  # saved
        self.assertEqual(self.retired_events(), [])
        self.assertIsNone(public_retired_telemetry(self.store.state['labs'][0]))

    def test_ledger_is_kept_with_names_and_counts_in_the_event_only(self):
        lab = make_lab(telemetry=ledger(**{JUNOS: (JUNOS_LINES, 'juniper_cjunosevolved'), EOS: ([], 'arista_ceos'),
                                           XR: (['  ', ''], 'cisco_xrv9k')}))
        before = copy.deepcopy(lab)
        self.store.state['labs'] = [lab]
        summary = migrate_retired_telemetry(self.store)
        self.assertEqual(summary, {'labs': 1, 'kept': {'lab1': [JUNOS]}, 'malformed': []})
        stored = self.store.state['labs'][0]
        record = stored['telemetry_retired']
        self.assertEqual(record['applied'], {JUNOS: {'lines': JUNOS_LINES, 'at': AT, 'kind': 'juniper_cjunosevolved'}})
        self.assertTrue(record['retired_at'])
        self.assertNotIn('malformed', record)
        self.assertNotIn('telemetry', stored)
        rest = {k: v for k, v in stored.items() if k != 'telemetry_retired'}
        self.assertEqual(rest, {k: v for k, v in before.items() if k != 'telemetry'})
        self.assertEqual(stored['profiles'][0]['password'], 'profile-secret')
        [event] = self.retired_events()
        self.assertEqual((event['action'], event['level'], event['lab_id']), ('telemetry.retired', 'info', 'lab1'))
        self.assertIn('recorded for 1 device: cjunos1 (1).', event['message'])
        self.assertIn('Remove them from the lab page.', event['message'])
        text = (Path(self.tmp.name) / 'events.jsonl').read_text()
        for fragment in CONFIG_TEXT + ('profile-secret', 'node-secret'):
            self.assertNotIn(fragment, text)
        self.assertEqual(Store(self.tmp.name).state['labs'][0]['telemetry_retired'], record)

    def test_second_run_is_a_no_op(self):
        self.store.state['labs'] = [make_lab(telemetry=ledger(**{JUNOS: (JUNOS_LINES, 'juniper_cjunosevolved')}))]
        migrate_retired_telemetry(self.store)
        state = copy.deepcopy(self.store.state)
        count = len(events(self.tmp.name))
        with patch.object(self.store, 'save') as save:
            summary = migrate_retired_telemetry(self.store)
        save.assert_not_called()
        self.assertEqual(summary, {'labs': 0, 'kept': {}, 'malformed': []})
        self.assertEqual(self.store.state, state)
        self.assertEqual(len(events(self.tmp.name)), count)

    def test_a_stale_removing_flag_is_cleared_quietly(self):
        kept = {'applied': {JUNOS: {'lines': JUNOS_LINES, 'at': AT, 'kind': 'juniper_cjunosevolved'}},
                'retired_at': AT, 'removing': AT}
        self.store.state['labs'] = [make_lab(telemetry_retired=copy.deepcopy(kept)),
                                    make_lab('lab2', telemetry_retired={'applied': {}, 'retired_at': AT, 'removing': AT})]
        self.assertTrue(operation_busy(self.store.state, 'lab1'))
        summary = migrate_retired_telemetry(self.store)
        self.assertEqual(summary, {'labs': 2, 'kept': {}, 'malformed': []})
        record = self.store.lab('lab1')['telemetry_retired']
        self.assertEqual(record, {k: v for k, v in kept.items() if k != 'removing'})
        self.assertNotIn('telemetry_retired', self.store.lab('lab2'))      # nothing left in it
        self.assertFalse(operation_busy(self.store.state, 'lab1'))
        self.assertEqual(self.retired_events(), [])
        self.assertNotIn('removing', json.dumps(Store(self.tmp.name).state['labs']))

    def test_merge_with_an_existing_record_keeps_the_newer_entry_per_node(self):
        existing = {'applied': {'n1': {'lines': ['old one'], 'at': '2026-09-01T00:00:00+00:00', 'kind': 'k'},
                                'n2': {'lines': ['kept two'], 'at': '2026-09-05T00:00:00+00:00', 'kind': 'k'},
                                'n4': {'lines': ['kept four'], 'at': 'yesterday', 'kind': 'k'}},
                    'retired_at': '2026-09-02T00:00:00+00:00'}
        telemetry = {'auto': True, 'applied': {
            'n1': {'lines': ['new one'], 'at': '2026-09-10T00:00:00+00:00', 'kind': 'k'},
            'n2': {'lines': ['older two'], 'at': '2026-08-01T00:00:00+00:00', 'kind': 'k'},
            'n3': {'lines': ['three'], 'at': 'not a time', 'kind': 'k'},
            'n4': {'lines': ['newer four?'], 'at': '2026-09-20T00:00:00+00:00', 'kind': 'k'}}}
        self.store.state['labs'] = [make_lab(telemetry=telemetry, telemetry_retired=copy.deepcopy(existing))]
        summary = migrate_retired_telemetry(self.store)
        record = self.store.state['labs'][0]['telemetry_retired']
        self.assertEqual(record['retired_at'], existing['retired_at'])
        self.assertEqual({name: entry['lines'] for name, entry in record['applied'].items()},
                         {'n1': ['new one'], 'n2': ['kept two'], 'n3': ['three'], 'n4': ['kept four']})
        self.assertEqual(sorted(summary['kept']['lab1']), ['n1', 'n2', 'n3', 'n4'])

    def test_malformed_values_are_kept_with_a_warning(self):
        huge = {'applied': ['x' * 5000]}
        variants = {'m1': 'on', 'm2': {'auto': True, 'applied': ['set x']}, 'm3': {'applied': {'r1': {'lines': 'set x'}}},
                    'm4': {'applied': {'r1': {'lines': ['a', 3]}}}, 'm5': {'applied': {'r1': 'x'}},
                    'm6': {'applied': {'good': {'lines': JUNOS_LINES, 'at': AT, 'kind': 'juniper_cjunosevolved'},
                                       'bad': {'lines': 5}}},
                    'm7': huge}
        self.store.state['labs'] = [make_lab(lab_id, telemetry=copy.deepcopy(value)) for lab_id, value in variants.items()]
        summary = migrate_retired_telemetry(self.store)
        self.assertEqual(sorted(summary['malformed']), sorted(variants))
        self.assertEqual(summary['kept'], {'m6': ['good']})
        warnings = {e['lab_id']: e for e in self.retired_events() if e['action'] == 'telemetry.retired.malformed'}
        self.assertEqual(sorted(warnings), sorted(variants))
        for lab in self.store.state['labs']:
            with self.subTest(lab=lab['id']):
                self.assertNotIn('telemetry', lab)
                [kept] = lab['telemetry_retired']['malformed']
                self.assertTrue(kept['reason'])
                self.assertEqual(warnings[lab['id']]['level'], 'warning')
                self.assertIn("'Restore square'", warnings[lab['id']]['message'])
                if lab['id'] == 'm7':
                    self.assertTrue(kept['value'].endswith('…(truncated)'))
                    self.assertEqual(len(kept['value']), 4096 + len('…(truncated)'))
                    self.assertTrue(kept['value'].startswith('{"applied": ["xxx'))
                else:
                    self.assertEqual(kept['value'], variants[lab['id']])
                summary_view = public_retired_telemetry(lab)
                self.assertTrue(summary_view['malformed'])
        m6 = next(l for l in self.store.state['labs'] if l['id'] == 'm6')
        self.assertEqual(list(m6['telemetry_retired']['applied']), ['good'])
        self.assertEqual(public_retired_telemetry(m6)['total'], 1)


class PublicSummaryTests(unittest.TestCase):
    def test_absent_present_and_malformed(self):
        self.assertIsNone(public_retired_telemetry(make_lab()))
        self.assertIsNone(public_retired_telemetry(make_lab(telemetry_retired={'applied': {}, 'retired_at': AT})))
        lab = make_lab(telemetry_retired={'applied': {JUNOS: {'lines': JUNOS_LINES, 'at': AT, 'kind': 'juniper_cjunosevolved'},
                                                      EOS: {'lines': EOS_LINES, 'at': AT, 'kind': 'arista_ceos'},
                                                      'clab-square-gone': {'lines': ['x'], 'at': AT, 'kind': ''}},
                                          'retired_at': AT})
        view = public_retired_telemetry(lab)
        self.assertEqual(view, {'nodes': [{'name': EOS, 'short_name': 'ceos1', 'lines': 2},
                                          {'name': JUNOS, 'short_name': 'cjunos1', 'lines': 1},
                                          {'name': 'clab-square-gone', 'short_name': 'clab-square-gone', 'lines': 1}],
                                'total': 4, 'malformed': False})
        for fragment in CONFIG_TEXT:
            self.assertNotIn(fragment, json.dumps(view))
        malformed = make_lab(telemetry_retired={'applied': {}, 'retired_at': AT, 'malformed': [{'reason': 'r', 'value': 'on', 'at': AT}]})
        self.assertEqual(public_retired_telemetry(malformed), {'nodes': [], 'total': 0, 'malformed': True})


class PlanTests(unittest.TestCase):
    def test_eos_block_the_manager_created(self):
        lines = EOS_LINES + ['      vrf MGMT']
        text = 'management api gnmi\n   transport grpc default\n      vrf MGMT\n'
        self.assertEqual(plan_block('management api gnmi', lines, text).commands, ['no management api gnmi'])
        foreign = text + '   transport grpc other\n'
        self.assertEqual(plan_block('management api gnmi', lines, foreign).outcome, 'foreign')
        extra_leaf = 'management api gnmi\n   transport grpc default\n      vrf MGMT\n      port 6031\n'
        self.assertEqual(plan_block('management api gnmi', lines, extra_leaf).outcome, 'foreign')
        mine_gone = 'management api gnmi\n   transport grpc students\n'
        decision = plan_block('management api gnmi', lines, mine_gone)
        self.assertEqual((decision.outcome, decision.message), ('absent', retirement.LEFT_IN_PLACE))
        self.assertEqual(plan_block('management api gnmi', lines, '').outcome, 'absent')

    def test_iosxr_line_added_to_an_existing_block(self):
        text = 'Tue Sep 23 10:00:00.000 UTC\ngrpc\n port 57400\n no-tls\n address-family dual\n!\n'
        decision = plan_block('grpc', [' no-tls'], text)
        self.assertEqual((decision.outcome, decision.commands), ('remove', ['grpc', 'no no-tls']))
        self.assertEqual(plan_block('grpc', [' no-tls'], 'grpc\n port 57400\n!\n').outcome, 'absent')
        self.assertEqual(plan_block('grpc', XR_LINES, text).outcome, 'foreign')
        self.assertEqual(plan_block('grpc', XR_LINES, 'grpc\n port 57400\n no-tls\n!\n').commands, ['no grpc'])

    def test_junos_stanza_and_service(self):
        alone = GRPC + ' clear-text port 32767\n' + NOTIFICATION + '\n'
        self.assertEqual(plan_junos(JUNOS_LINES, alone).commands, ['delete ' + GRPC[4:]])
        shared = GRPC + ' clear-text port 32767\n' + GRPC + ' skip-authentication\n'
        self.assertEqual(plan_junos(JUNOS_LINES, shared).commands, ['delete ' + GRPC[4:] + ' clear-text'])
        address = GRPC + ' clear-text port 32767\n' + GRPC + ' clear-text address 0.0.0.0\n'
        self.assertEqual(plan_junos(JUNOS_LINES, address).outcome, 'foreign')
        inactive = GRPC + ' clear-text port 32767\n' + 'deactivate' + GRPC[3:] + ' clear-text\n'
        self.assertEqual(plan_junos(JUNOS_LINES, inactive).outcome, 'foreign')
        self.assertEqual(plan_junos(JUNOS_LINES, NOTIFICATION).outcome, 'absent')
        routed = JUNOS_LINES + [GRPC + ' routing-instance mgmt_junos']
        self.assertEqual(plan_junos(routed, '\n'.join(routed)).commands, ['delete ' + GRPC[4:]])
        # J1: the student replaced clear-text with ssl and kept the manager's routing instance.
        ssl = GRPC + ' ssl port 32767\n' + GRPC + ' routing-instance mgmt_junos\n'
        self.assertEqual(plan_junos(routed, ssl).outcome, 'foreign')
        # J2: both manager lines, plus a leaf the manager did not add.
        extra = '\n'.join(routed) + '\n' + GRPC + ' skip-authentication\n'
        self.assertEqual(plan_junos(routed, extra).outcome, 'foreign')

    def test_unrecognised_ledgers_are_never_acted_on(self):
        self.assertEqual(plan_block('management api gnmi', ['interface Ethernet1', ' shutdown'], '').outcome, 'invalid')
        self.assertEqual(plan_block('grpc', ['grpc', 'router bgp 1'], '').outcome, 'invalid')
        self.assertEqual(plan_junos(['set system host-name x'], '').outcome, 'invalid')


# ---- the API and the removal -----------------------------------------------------------------------------

class RetirementApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        seed = Store(self.tmp.name)
        seed.state['labs'] = [make_lab(telemetry=ledger(**{EOS: (EOS_LINES, 'arista_ceos'), XR: (XR_LINES, 'cisco_xrv9k'),
                                                           JUNOS: (JUNOS_LINES, 'juniper_cjunosevolved')})),
                              make_lab('lab2')]
        seed.save()
        self.app = create_app(self.tmp.name)
        self.store = self.app.state.store
        self.client = TestClient(self.app)
        self.retirement = self.app.state.telemetry_retirement
        with self.store.lock:
            self.store.state['host'] = {'enabled': True}
            self.store.state['discovery'] = {'ok': True, 'checked_epoch': time.time(), 'labs': {}}
        self.opened = []

    def tearDown(self):
        self.retirement.close()
        self.app.state.node_services.close()
        self.app.state.runner.close()
        self.client.close()
        self.tmp.cleanup()

    def login(self, *names):
        for name in names:
            self.app.state.node_services.checks[('lab1', name)] = {'status': 'reachable', 'at': '', 'message': ''}

    def lab_view(self, lab_id='lab1'):
        response = self.client.get('/api/state')
        self.assertEqual(response.status_code, 200, response.text)
        return next(lab for lab in response.json()['labs'] if lab['id'] == lab_id), response.text

    def remove(self, devices, node=''):
        def opener(services, target, creds):
            self.opened.append(target['name'])
            self.assertEqual(creds['password'], 'node-secret-' + target['short_name'])
            return Channel(devices[target['name']]), lambda: None
        with patch.object(retirement, 'open_channel', side_effect=opener):
            return self.client.post('/api/labs/lab1/telemetry-retired/remove', json={'node': node})

    def outcomes(self, response):
        self.assertEqual(response.status_code, 200, response.text)
        return {row['name']: (row['outcome'], row['message']) for row in response.json()['results']}

    def retired_events(self):
        return [e for e in events(self.tmp.name) if e['action'].startswith('telemetry.retired')]

    def saved(self):
        """The state as written to disk (read without constructing another Store on the same directory)."""
        return json.loads(self.store.cipher.decrypt((Path(self.tmp.name) / 'state.enc').read_bytes()))

    def forget(self, lab_id='lab1', **body):
        return self.client.post(f'/api/labs/{lab_id}/telemetry-retired/forget', json=body)

    def assert_no_config_text(self, *texts):
        for text in texts + ((Path(self.tmp.name) / 'events.jsonl').read_text(),):
            for fragment in CONFIG_TEXT:
                self.assertNotIn(fragment, text)

    def test_startup_migration_and_state_summary(self):
        stored = self.store.lab('lab1')
        self.assertNotIn('telemetry', stored)
        self.assertEqual(sorted(stored['telemetry_retired']['applied']), sorted([EOS, XR, JUNOS]))
        lab, text = self.lab_view()
        self.assertEqual(lab['telemetry_retired'], {'nodes': [{'name': EOS, 'short_name': 'ceos1', 'lines': 2},
                                                              {'name': XR, 'short_name': 'xr1', 'lines': 3},
                                                              {'name': JUNOS, 'short_name': 'cjunos1', 'lines': 1}],
                                                    'total': 6, 'malformed': False})
        self.assertNotIn('telemetry', lab)
        self.assertNotIn('telemetry_retired', self.lab_view('lab2')[0])
        self.assertNotIn('retired_at', text)
        self.assertNotIn('profile-secret', text)
        self.assert_no_config_text(text)

    def test_view_returns_lines_and_why_a_node_cannot_be_removed_yet(self):
        self.assertEqual(self.client.get('/api/labs/nope/telemetry-retired').status_code, 404)
        self.assertEqual(self.client.get('/api/labs/lab2/telemetry-retired').status_code, 404)
        response = self.client.get('/api/labs/lab1/telemetry-retired')
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual((body['lab_id'], body['lab_name'], body['malformed']), ('lab1', 'Restore square', False))
        rows = {row['name']: row for row in body['nodes']}
        self.assertEqual(rows[JUNOS], {'name': JUNOS, 'short_name': 'cjunos1', 'kind': 'juniper_cjunosevolved', 'lines': JUNOS_LINES,
                                       'at': AT, 'removable': False, 'permanent': False,
                                       'reason': 'Log in to the device first (Test logins).'})
        self.assertEqual(rows[EOS]['lines'], EOS_LINES)
        self.login(EOS, XR, JUNOS)
        with self.store.lock:
            self.store.lab('lab1')['nodes'][1]['runtime_state'] = 'exited'
        rows = {row['name']: row for row in self.client.get('/api/labs/lab1/telemetry-retired').json()['nodes']}
        self.assertEqual((rows[JUNOS]['removable'], rows[JUNOS]['permanent'], rows[JUNOS]['reason']), (True, False, ''))
        self.assertEqual((rows[XR]['removable'], rows[XR]['permanent'], rows[XR]['reason']), (False, False, 'The device is not running.'))
        with self.store.lock:
            self.store.state['discovery']['checked_epoch'] = 0
        rows = {row['name']: row for row in self.client.get('/api/labs/lab1/telemetry-retired').json()['nodes']}
        self.assertEqual((rows[JUNOS]['removable'], rows[JUNOS]['permanent']), (False, False))
        self.assertIn('VM', rows[JUNOS]['reason'])

    def test_guards(self):
        self.login(EOS, XR, JUNOS)
        post = lambda lab_id='lab1', body=None: self.client.post(f'/api/labs/{lab_id}/telemetry-retired/remove', json=body or {})
        self.assertEqual(post('nope').status_code, 404)
        self.assertEqual(post('lab2').status_code, 404)
        self.assertEqual(post(body={'node': 'clab-square-host'}).status_code, 404)
        self.assertEqual(post(body={'node': JUNOS, 'lines': ['x']}).status_code, 422)
        self.assertEqual(post(body={'node': 'x' * 201}).status_code, 422)
        with self.store.lock:
            self.store.state['operations'] = [{'id': 'op1', 'lab_id': 'lab1', 'status': 'running', 'action': 'deploy'}]
        self.assertEqual(post().status_code, 409)
        with self.store.lock:
            self.store.state['operations'] = []
            self.store.state['restore_jobs'] = [{'id': 'r1', 'lab_id': 'lab1', 'status': 'interrupted',
                                                 'targets': [{'name': JUNOS, 'status': 'confirming'}]}]
        self.assertEqual(post().status_code, 409)
        with self.store.lock:
            self.store.state['restore_jobs'] = []
            self.store.state['jobs'] = [{'id': 'b1', 'lab_id': 'lab1', 'status': 'running'}]
        self.assertEqual(post().status_code, 409)
        with self.store.lock:
            self.store.state['jobs'] = []
        self.retirement.running.add('lab1')
        self.assertEqual(post().status_code, 409)
        self.retirement.running.clear()
        self.store.lab('lab1')['telemetry_retired']['removing'] = AT
        self.assertEqual(post().status_code, 409)
        self.assertEqual(post().json()['detail'], 'A removal is already running for this lab.')
        del self.store.lab('lab1')['telemetry_retired']['removing']
        self.assertEqual(self.opened, [])
        self.assertEqual(sorted(self.store.lab('lab1')['telemetry_retired']['applied']), sorted([EOS, XR, JUNOS]))

    def test_nodes_without_a_proven_login_are_skipped(self):
        response = self.remove({})
        self.assertEqual(self.outcomes(response)[JUNOS], ('skipped', 'Log in to the device first (Test logins).'))
        self.assertEqual(self.opened, [])
        self.assertEqual(response.json()['remaining'], [EOS, XR, JUNOS])

    def test_removes_each_kind_and_reads_it_back(self):
        self.login(EOS, XR, JUNOS)
        devices = {EOS: FakeEos(EOS_LINES), XR: FakeXr(XR_LINES), JUNOS: FakeJunos(JUNOS_LINES + [NOTIFICATION])}
        response = self.remove(devices)
        outcomes = self.outcomes(response)
        self.assertEqual(outcomes, {name: ('removed', retirement.REMOVED) for name in (EOS, XR, JUNOS)})
        self.assertEqual(response.json()['remaining'], [])
        self.assertEqual(devices[EOS].block, [])
        self.assertEqual(devices[XR].running, [])
        self.assertEqual(devices[JUNOS].running, [NOTIFICATION])
        eos = devices[EOS].sent
        self.assertEqual(eos[eos.index('configure terminal'):], ['configure terminal', 'no management api gnmi', 'end',
                                                                 'show running-config | section management api gnmi'])
        self.assertIn('show configuration sessions detail', eos)
        xr = devices[XR].sent
        self.assertEqual(xr[xr.index('configure terminal'):], ['configure terminal', 'no grpc', 'commit', 'end', 'show running-config grpc'])
        junos = devices[JUNOS].sent
        self.assertEqual(junos[junos.index('configure private'):],
                         ['configure private', 'delete ' + GRPC[4:], 'commit and-quit',
                          'show configuration system services extension-service | display set'])
        self.assertIn('show system commit | no-more', junos)
        self.assertNotIn('telemetry_retired', self.store.lab('lab1'))
        lab, text = self.lab_view()
        self.assertNotIn('telemetry_retired', lab)
        self.assertEqual(self.client.get('/api/labs/lab1/telemetry-retired').status_code, 404)
        removed = [e for e in self.retired_events() if e['action'] == 'telemetry.retired.removed']
        self.assertEqual(sorted(e['node'] for e in removed), sorted([EOS, XR, JUNOS]))
        self.assertEqual(Store(self.tmp.name).lab('lab1').get('telemetry_retired'), None)
        self.assert_no_config_text(response.text, text)

    def test_absent_lines_clear_the_record_without_configuring(self):
        self.login(JUNOS)
        device = FakeJunos([NOTIFICATION])
        response = self.remove({JUNOS: device}, node=JUNOS)
        self.assertEqual(self.outcomes(response), {JUNOS: ('absent', retirement.ABSENT)})
        self.assertNotIn('configure private', device.sent)
        self.assertEqual(response.json()['remaining'], [EOS, XR])
        self.assertEqual([n['name'] for n in self.lab_view()[0]['telemetry_retired']['nodes']], [EOS, XR])
        self.assertEqual([e['action'] for e in self.retired_events()][-1], 'telemetry.retired.absent')

    def test_foreign_settings_in_the_block_change_nothing(self):
        self.login(EOS)
        device = FakeEos(EOS_LINES + ['   transport grpc students', '      port 6031'])
        response = self.remove({EOS: device}, node=EOS)
        self.assertEqual(self.outcomes(response), {EOS: ('failed', retirement.FOREIGN)})
        self.assertNotIn('configure terminal', device.sent)
        self.assertFalse([line for line in device.sent if line.startswith('no ')])
        self.assertEqual(len(device.block), 4)
        self.assertEqual(response.json()['remaining'], [EOS, XR, JUNOS])
        self.assertIn(EOS, [n['name'] for n in self.lab_view()[0]['telemetry_retired']['nodes']])
        [event] = [e for e in self.retired_events() if e['action'] == 'telemetry.retired.failed']
        self.assertEqual((event['level'], event['node']), ('warning', EOS))

    def test_iosxr_line_added_to_an_existing_service_is_removed_alone(self):
        with self.store.lock:
            self.store.lab('lab1')['telemetry_retired']['applied'][XR]['lines'] = [' no-tls']
        self.login(XR)
        device = FakeXr(['grpc', ' port 57400', ' no-tls'])
        response = self.remove({XR: device}, node=XR)
        self.assertEqual(self.outcomes(response), {XR: ('removed', retirement.REMOVED)})
        self.assertEqual(device.running, ['grpc', ' port 57400'])
        self.assertNotIn('no grpc', device.sent)
        self.assertEqual(device.sent[device.sent.index('configure terminal'):],
                         ['configure terminal', 'grpc', 'no no-tls', 'commit', 'end', 'show running-config grpc'])

    def test_nos_errors_abort_the_candidate(self):
        self.login(EOS, XR, JUNOS)
        devices = {EOS: FakeEos(EOS_LINES, reject=('no management api gnmi',)), XR: FakeXr(XR_LINES, reject=('commit',)),
                   JUNOS: FakeJunos(JUNOS_LINES, reject_commit=True)}
        outcomes = self.outcomes(self.remove(devices))
        self.assertEqual(outcomes, {EOS: ('failed', retirement.REJECTED_EOS), XR: ('failed', retirement.REJECTED),
                                    JUNOS: ('failed', retirement.REJECTED)})
        self.assertEqual(devices[EOS].sent[-2:], ['no management api gnmi', 'end'])
        self.assertEqual(devices[XR].sent[-2:], ['commit', 'abort'])
        self.assertEqual(devices[JUNOS].sent[-3:], ['commit and-quit', 'rollback 0', 'exit configuration-mode'])
        self.assertEqual((devices[XR].running, devices[JUNOS].running), (XR_LINES, JUNOS_LINES))
        self.assertEqual(sorted(self.store.lab('lab1')['telemetry_retired']['applied']), sorted([EOS, XR, JUNOS]))
        self.assertEqual(self.lab_view()[0]['telemetry_retired']['total'], 6)

    def test_a_change_waiting_for_confirmation_is_never_committed_over(self):
        self.login(EOS, XR, JUNOS)
        devices = {EOS: FakeEos(EOS_LINES, pending=True), XR: FakeXr(XR_LINES, trial=True), JUNOS: FakeJunos(JUNOS_LINES, pending=True)}
        outcomes = self.outcomes(self.remove(devices))
        self.assertEqual(outcomes, {name: ('failed', retirement.PENDING) for name in (EOS, XR, JUNOS)})
        for device in devices.values():
            self.assertFalse([line for line in device.sent if line.startswith(('configure terminal', 'configure private'))])

    def test_lines_still_shown_after_the_change_keep_the_record(self):
        self.login(JUNOS)
        device = FakeJunos(JUNOS_LINES, stubborn=True)
        response = self.remove({JUNOS: device}, node=JUNOS)
        self.assertEqual(self.outcomes(response), {JUNOS: ('failed', retirement.STILL)})
        self.assertIn('commit and-quit', device.sent)
        self.assertEqual(response.json()['remaining'], [EOS, XR, JUNOS])

    def test_an_unexpected_answer_is_never_taken_as_absent(self):
        self.login(EOS)
        garbled = FakeEos([], garbled=True)
        self.assertEqual(self.outcomes(self.remove({EOS: garbled}, node=EOS)), {EOS: ('failed', retirement.READ_FAILED)})
        unprivileged = FakeEos(EOS_LINES, unprivileged=True)
        self.assertEqual(self.outcomes(self.remove({EOS: unprivileged}, node=EOS)), {EOS: ('failed', retirement.ENABLE)})
        self.assertIn('enable', unprivileged.sent)
        for device in (garbled, unprivileged):
            self.assertNotIn('configure terminal', device.sent)
        self.assertIn(EOS, self.store.lab('lab1')['telemetry_retired']['applied'])

    def test_a_silent_device_fails_within_the_time_bound(self):
        self.login(JUNOS)
        device = FakeJunos(JUNOS_LINES, hang=('show configuration system services extension-service | display set',))
        started = time.monotonic()
        with patch.object(retirement, 'NODE_SECONDS', 0.5):
            response = self.remove({JUNOS: device}, node=JUNOS)
        self.assertLess(time.monotonic() - started, 5)
        self.assertEqual(self.outcomes(response), {JUNOS: ('failed', retirement.NO_ANSWER)})
        self.assertEqual(response.json()['remaining'], [EOS, XR, JUNOS])

    def test_a_device_that_stops_answering_mid_change_is_left_without_the_change(self):
        self.login(JUNOS)
        before_commit = FakeJunos(JUNOS_LINES, hang=('delete ' + GRPC[4:],))
        with patch.object(retirement, 'NODE_SECONDS', 0.5):
            response = self.remove({JUNOS: before_commit}, node=JUNOS)
        self.assertEqual(self.outcomes(response), {JUNOS: ('failed', retirement.NO_ANSWER)})
        self.assertEqual(before_commit.sent[-2:], ['rollback 0', 'exit configuration-mode'])    # sent after the deadline
        self.assertEqual(before_commit.running, JUNOS_LINES)
        during_commit = FakeJunos(JUNOS_LINES, hang=('commit and-quit',))
        with patch.object(retirement, 'NODE_SECONDS', 0.5):
            response = self.remove({JUNOS: during_commit}, node=JUNOS)
        self.assertEqual(self.outcomes(response), {JUNOS: ('failed', retirement.UNCONFIRMED)})
        self.assertEqual(during_commit.sent[-1], 'commit and-quit')
        self.assertIn(JUNOS, self.store.lab('lab1')['telemetry_retired']['applied'])

    def test_the_lab_is_busy_for_everything_else_while_a_removal_runs(self):
        self.login(EOS, JUNOS)
        seen = {}

        def probe(device):
            def answer(line, inner=device.answer):
                if line == 'show system commit | no-more':
                    with self.store.lock:
                        seen['busy'] = operation_busy(self.store.state, 'lab1')
                        seen['everywhere'] = operation_busy(self.store.state)
                        seen['other lab'] = operation_busy(self.store.state, 'lab2')
                    seen['saved'] = self.saved()['labs'][0]['telemetry_retired'].get('removing')
                    seen['forget'] = self.forget(node=EOS).status_code
                    seen['remove'] = self.client.post('/api/labs/lab1/telemetry-retired/remove', json={}).status_code
                    try:
                        self.app.state.restore.guard_idle('lab1')
                    except Exception as error:
                        seen['restore'] = getattr(error, 'status_code', None)
                    try:
                        self.app.state.runner.submit('lab1', 'backup')
                    except ValueError:
                        seen['backup'] = 'refused'
                return inner(line)
            device.answer = answer
            return device
        devices = {EOS: FakeEos(EOS_LINES + ['   transport grpc students']), JUNOS: probe(FakeJunos(JUNOS_LINES))}
        response = self.remove(devices)
        self.assertEqual(self.outcomes(response), {EOS: ('failed', retirement.FOREIGN), JUNOS: ('removed', retirement.REMOVED),
                                                   XR: ('skipped', 'Log in to the device first (Test logins).')})
        self.assertEqual(seen, {'busy': True, 'everywhere': True, 'other lab': False, 'saved': seen['saved'], 'forget': 409,
                                'remove': 409, 'restore': 409, 'backup': 'refused'})
        self.assertTrue(seen['saved'])
        self.assertNotIn('removing', self.store.lab('lab1')['telemetry_retired'])     # success and failure paths ended
        self.assertNotIn('removing', self.saved()['labs'][0]['telemetry_retired'])
        self.assertFalse(operation_busy(self.store.state, 'lab1'))
        self.assertNotIn('removing', self.client.get('/api/labs/lab1/telemetry-retired').text)
        self.assertNotIn('removing', self.lab_view()[1])

    def test_the_flag_is_released_when_every_node_fails(self):
        self.login(JUNOS)
        with patch.object(retirement, 'open_channel', side_effect=OSError('unreachable')):
            response = self.client.post('/api/labs/lab1/telemetry-retired/remove', json={'node': JUNOS})
        self.assertEqual(self.outcomes(response), {JUNOS: ('failed', retirement.SSH_FAILED)})
        self.assertNotIn('removing', self.store.lab('lab1')['telemetry_retired'])
        self.assertNotIn('removing', self.saved()['labs'][0]['telemetry_retired'])
        self.assertFalse(operation_busy(self.store.state, 'lab1'))

    def test_a_redeploy_after_the_lines_were_recorded_clears_the_record_without_touching_the_device(self):
        self.login(EOS, XR, JUNOS)
        with self.store.lock:
            lab = self.store.lab('lab1')
            lab['last_deployed'] = '2026-09-20T08:00:00+00:00'
            lab['telemetry_retired']['applied'][XR]['at'] = '2026-09-21T08:00:00+00:00'      # recorded after it
            lab['telemetry_retired']['applied'][JUNOS]['at'] = 'not a time'                  # unreadable counts as older
        rows = {row['name']: row for row in self.client.get('/api/labs/lab1/telemetry-retired').json()['nodes']}
        for name in (EOS, JUNOS):
            self.assertEqual((rows[name]['removable'], rows[name]['permanent'], rows[name]['reason']),
                             (False, True, retirement.REDEPLOYED_REASON))
        self.assertEqual((rows[XR]['removable'], rows[XR]['permanent']), (True, False))
        devices = {XR: FakeXr(XR_LINES)}
        response = self.remove(devices)
        self.assertEqual(self.outcomes(response), {EOS: ('absent', retirement.REDEPLOYED), JUNOS: ('absent', retirement.REDEPLOYED),
                                                   XR: ('removed', retirement.REMOVED)})
        self.assertEqual(self.opened, [XR])                     # the redeployed devices were never contacted
        self.assertNotIn('telemetry_retired', self.store.lab('lab1'))
        absent = [e for e in self.retired_events() if e['action'] == 'telemetry.retired.absent']
        self.assertEqual(sorted(e['node'] for e in absent), sorted([EOS, JUNOS]))

    def test_an_unreadable_deployment_time_proves_nothing(self):
        with self.store.lock:
            self.store.lab('lab1')['last_deployed'] = 'sometime'
        rows = {row['name']: row for row in self.client.get('/api/labs/lab1/telemetry-retired').json()['nodes']}
        self.assertFalse(rows[EOS]['permanent'])
        self.assertEqual(rows[EOS]['reason'], 'Log in to the device first (Test logins).')

    def test_forget_drops_only_entries_the_manager_can_never_act_on(self):
        with self.store.lock:
            record = self.store.lab('lab1')['telemetry_retired']
            record['applied']['clab-square-gone'] = {'lines': ['set x'], 'at': AT, 'kind': 'juniper_cjunosevolved'}
            record['malformed'] = [{'reason': 'the recorded lines of r9 are not in the expected shape', 'value': {'lines': 5}, 'at': AT}]
        self.assertEqual(self.forget('nope', node=EOS).status_code, 404)
        self.assertEqual(self.forget('lab2', node=EOS).status_code, 404)
        self.assertEqual(self.forget(node='clab-square-host').status_code, 404)
        self.assertEqual(self.forget().status_code, 400)
        self.assertEqual(self.forget(node=EOS, malformed=True).status_code, 400)
        self.assertEqual(self.forget(node=EOS, lines=['x']).status_code, 422)
        refused = self.forget(node=EOS)                                  # only waiting for a login: remove it instead
        self.assertEqual((refused.status_code, refused.json()['detail']), (409, 'Remove the lines from the device instead.'))
        with self.store.lock:
            self.store.state['operations'] = [{'id': 'op1', 'lab_id': 'lab1', 'status': 'running', 'action': 'deploy'}]
        self.assertEqual(self.forget(node='clab-square-gone').status_code, 409)
        with self.store.lock:
            self.store.state['operations'] = []
        gone = self.forget(node='clab-square-gone')
        self.assertEqual(gone.status_code, 200, gone.text)
        self.assertEqual(gone.json(), {'forgotten': 'clab-square-gone', 'remaining': [EOS, XR, JUNOS]})
        malformed = self.forget(malformed=True)
        self.assertEqual(malformed.json(), {'forgotten': 'malformed', 'remaining': [EOS, XR, JUNOS]})
        self.assertEqual(self.forget(malformed=True).status_code, 404)
        self.assertNotIn('malformed', self.saved()['labs'][0]['telemetry_retired'])
        forgotten = [e for e in self.retired_events() if e['action'] == 'telemetry.retired.forgotten']
        self.assertEqual([e['node'] for e in forgotten], ['clab-square-gone', ''])
        self.assertIn('This device is no longer part of the lab.', forgotten[0]['message'])
        self.assertIn('malformed record', forgotten[1]['message'])
        self.assertIn('not in the expected shape', forgotten[1]['message'])
        with self.store.lock:
            self.store.lab('lab1')['last_deployed'] = '2026-09-30T00:00:00+00:00'      # every entry now predates a redeploy
        for name in (EOS, XR, JUNOS):
            self.assertEqual(self.forget(node=name).status_code, 200)
        self.assertNotIn('telemetry_retired', self.store.lab('lab1'))
        self.assertNotIn('telemetry_retired', self.lab_view()[0])
        self.assertEqual(self.client.get('/api/labs/lab1/telemetry-retired').status_code, 404)
        self.assert_no_config_text()

    def test_a_refused_login_keeps_the_record(self):
        import paramiko
        self.login(JUNOS)
        with patch.object(retirement, 'open_channel', side_effect=paramiko.AuthenticationException('no')):
            response = self.client.post('/api/labs/lab1/telemetry-retired/remove', json={'node': JUNOS})
        self.assertEqual(self.outcomes(response), {JUNOS: ('failed', retirement.LOGIN)})
        self.assertIn(JUNOS, self.store.lab('lab1')['telemetry_retired']['applied'])


if __name__ == '__main__':
    unittest.main()
