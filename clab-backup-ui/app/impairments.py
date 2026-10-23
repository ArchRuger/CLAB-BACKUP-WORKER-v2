"""Link impairments and the pending-changes plan (docs/parity-campaign/C05-DESIGN.md, manager side).

Impairments: the lab-wide read, set, reset and Clear for one running device's data interface, through the operations helper's
`netem-show-all`, `netem-set` and `netem-reset`. The browser never names a container: it sends the manager's lab id, the device name,
the interface and the `expected_id` (the container id it was shown); the manager derives the deployment name, the container and the
helper's request digest. Every mutating call runs in `LabOperations.impairing()`, which `LabOperations.guard()` consults, so a lab
operation and an impairment never overlap in either direction. Events carry validated names and numbers only, never an interface
list, helper output or a container id.

The pending-changes plan (`GET /api/operations/apply-plan`) lives here because this module is installed before LabOperations, whose
`GET /api/operations/{job_id}` would otherwise answer 404 `Operation not found.` for it; the cache itself belongs to LabOperations,
which drops it before a job turns terminal.
"""
import re
import threading
import time

from fastapi import HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from typing import Any

from .device_diagnostics import (NO_FOLDER_SENTENCE, UNLINKED_SENTENCE, interface_role, strip_escapes, text_value)
from .discovery import expected_container
from .host_operations import LOCK_SENTENCE, NODE_FILTER_LIMIT, PLAN_KEYS, digest, impairment_values, plan_changes
from .topology import displayed_interface

CLEAR_BUDGET = 120
PLAN_TTL = 60
BUSY_ELSEWHERE = 'Another lab operation is running on the VM (it may belong to another lab); try again when it has finished.'
CHANGE_IN_PROGRESS = 'Another impairment change on this lab is in progress; try again in a moment.'
REOPEN_SENTENCE = 'Reopen the Impairments section and apply again.'
HEX64 = re.compile(r'[0-9a-f]{64}')
DURATION = re.compile(r'([0-9]+(?:\.[0-9]+)?)(ms|us|µs|ns|h|m|s)')
DURATION_UNITS_MS = {'h': 3600000.0, 'm': 60000.0, 's': 1000.0, 'ms': 1.0, 'us': 0.001, 'µs': 0.001, 'ns': 0.000001}
MUTATING_TIMEOUT = 45
READ_TIMEOUT = 75
ROW_LIMIT = 256


def duration_text(value):
    """A Go duration as containerlab prints it (`20ms`, `1.5s`, `1m0s`, `1h2m3.5s`) as whole milliseconds text (`1500ms`);
    '' stays '' and anything that does not read as a duration is ''."""
    if not isinstance(value, str) or not value.strip(): return ''
    text = value.strip(); total = 0.0; at = 0
    while at < len(text):
        match = DURATION.match(text, at)
        if not match: return ''
        total += float(match.group(1)) * DURATION_UNITS_MS[match.group(2)]; at = match.end()
    return '%dms' % int(total + 0.5)


def number(value, places=None):
    """An int or float from the helper (never a bool), rounded to `places` decimals, `-0.0` as 0; anything else 0."""
    if type(value) not in (int, float): return 0
    if places is None: return int(value)
    value = round(float(value), places)
    return 0 if value == 0 else value


def public_impairment(row, kind):
    """One impairment row as the browser may see it: containerlab's formats normalised so a row nobody touched always passes the
    page's own validator (durations in whole milliseconds, percentages to two decimals, the rate an int), plus the NOS's port name."""
    name = row['interface'][:64]
    return {'interface': name, 'port': (row.get('alias') if isinstance(row.get('alias'), str) and row.get('alias') else displayed_interface(kind, name)) if interface_role(kind, name) == 'data' else name,
            'delay': duration_text(row.get('delay')), 'jitter': duration_text(row.get('jitter')),
            'loss': number(row.get('loss'), 2), 'rate': number(row.get('rate')), 'corruption': number(row.get('corruption'), 2)}


def public_rows(rows, kind):
    """The data-interface rows of a helper answer. Rows on other roles (an impairment someone set on eth0 from a terminal) are not
    the manager's to show or clear."""
    found = []
    for row in rows if isinstance(rows, list) else []:
        if isinstance(row, dict) and isinstance(row.get('interface'), str) and row['interface'] and interface_role(kind, row['interface'][:64]) == 'data':
            found.append(public_impairment(row, kind))
        if len(found) >= ROW_LIMIT: break
    return found


def public_plan(plan):
    """The apply plan field by field: sorted bounded lists and the reasons per device."""
    plan = plan if isinstance(plan, dict) else {}
    result = {'deploys_lab': plan.get('deploys_lab') is True}
    for _, key in PLAN_KEYS:
        rows = plan.get(key)
        result[key] = sorted(r[:120] for r in rows if isinstance(r, str) and r)[:256] if isinstance(rows, list) else []
    reasons = plan.get('reasons') if isinstance(plan.get('reasons'), dict) else {}
    result['reasons'] = {k[:120]: v[:200] for k, v in sorted((k, v) for k, v in reasons.items() if isinstance(k, str) and k and isinstance(v, str))[:256]}
    return result


class DeviceRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    lab_id: str = Field(max_length=64)
    node: str = Field(max_length=253)
    interface: str = Field(max_length=64)
    expected_id: Any = None


class SetRequest(DeviceRequest):
    # Untyped on purpose: the shared value table (host_operations.impairment_values) decides what each wrong type or range answers.
    delay: Any = None
    jitter: Any = None
    loss: Any = None
    rate: Any = None
    corruption: Any = None


class ClearRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    lab_id: str = Field(max_length=64)
    node: str = Field(default='', max_length=253)


class Impairments:
    def __init__(self, store, operations, diagnostics):
        self.store = store; self.operations = operations; self.diagnostics = diagnostics
        self.locks = {}; self.locks_guard = threading.Lock()

    # Shared pieces -----------------------------------------------------------------------------------------------

    def lab_lock(self, lab_id):
        with self.locks_guard: return self.locks.setdefault(lab_id, threading.Lock())

    def helper(self, request):
        """One mutating or reading helper call (read to stream EOF in lab_operations.remote); the helper's lock sentence is worded for
        a person, because the lock may be held by another lab's job."""
        try: return self.diagnostics.ask(request, MUTATING_TIMEOUT)
        except HTTPException as exc:
            if exc.detail == LOCK_SENTENCE: raise HTTPException(409, BUSY_ELSEWHERE) from None
            raise

    def device(self, lab_id, node_name):
        """(node record fields, deployment name, container, topology node, shown name, runtime state) of a device."""
        lab, node, deployment, container = self.diagnostics.target(lab_id, node_name)
        with self.store.lock:
            row = next((n for n in (self.store.lab(lab_id) or {}).get('nodes', []) if n['name'] == node_name), {})
            state = row.get('runtime_state') or ''
        topo = node.get('definition_node') or node.get('short_name') or ''
        shown = node.get('short_name') or topo or node['name']
        return node, deployment, container, topo, shown, state

    def kind_of(self, node): return node.get('kind') or node.get('platform') or ''

    def checked_id(self, value):
        if not isinstance(value, str) or not HEX64.fullmatch(value): raise HTTPException(400, REOPEN_SENTENCE)
        return value

    def refuse_interface(self, kind, interface, shown, state):
        if state != 'running': raise HTTPException(409, shown + ' is not running. Impairments can be set only on a running device.')
        role = interface_role(kind, interface)
        if role == 'management':
            raise HTTPException(409, interface + ' is the management interface; the manager reaches the device through it and never impairs it.')
        if role != 'data': raise HTTPException(409, interface + ' is an internal interface of this device, not a lab link.')

    def describe(self, row):
        return 'delay %s, jitter %s, loss %s%%, rate %s kbit, corruption %s%%' % (row['delay'], row['jitter'], row['loss'], row['rate'], row['corruption'])

    # Reading -----------------------------------------------------------------------------------------------------

    def pairs(self, lab_id, only=''):
        """[(manager node name, kind, {node, container})] for every device of the lab with a container name (or the one named)."""
        with self.store.lock:
            lab = self.store.lab(lab_id)
            if not lab: raise HTTPException(404, 'Lab not found')
            deployment = lab.get('deployment_name') or ''
            head = {k: lab[k] for k in ('deployment_name', 'container_prefix') if k in lab}
            nodes = [dict(n) for n in lab['nodes'] if not only or n['name'] == only]
        if only and not nodes: raise HTTPException(404, 'Device not found')
        found = []
        for n in nodes:
            container = expected_container(head, n)
            if container: found.append((n['name'], n.get('kind') or n.get('platform') or '', n.get('definition_node') or n.get('short_name') or '', container, text_value(n.get('discovered_id'), 64)))
        return deployment, found

    def read_all(self, deployment, found, ask):
        """The impairments of every pair, in helper calls of 64 or fewer; no call at all without pairs. Returns
        ({manager node: {present, id, impairments, topo, container, kind}}, complete)."""
        devices = {}; complete = True
        for start in range(0, len(found), NODE_FILTER_LIMIT):
            chunk = found[start:start + NODE_FILTER_LIMIT]
            request = {'mode': 'netem-show-all', 'name': deployment, 'options': {'nodes': [{'node': topo, 'container': container} for _, _, topo, container, _ in chunk]}}
            result = ask(request)
            rows = result.get('devices') if isinstance(result.get('devices'), list) else []
            by_container = {r.get('container'): r for r in rows if isinstance(r, dict)}
            if result.get('complete') is not True: complete = False
            for name, kind, topo, container, known_id in chunk:
                row = by_container.get(container)
                if not row or row.get('unread') is True: complete = False; continue
                helper_id = row.get('id') if isinstance(row.get('id'), str) else ''
                devices[name] = {'present': row.get('present') is True, 'kind': kind, 'topo': topo, 'container': container,
                                 'id': helper_id if HEX64.fullmatch(helper_id) else known_id if HEX64.fullmatch(known_id) else '',
                                 'impairments': public_rows(row.get('impairments'), kind)}
        return devices, complete

    # The routes --------------------------------------------------------------------------------------------------

    def install(self, app):
        """Installed after DeviceDiagnostics and before LabOperations.install, whose GET /api/operations/{job_id} would take
        /impairments and /apply-plan."""

        @app.get('/api/operations/impairments')
        def read(lab_id: str = Query(max_length=64), node: str = Query(default='', max_length=253)):
            # A read, unguarded like the diagnostics reads: no guard(), no per-lab lock, only the three-slot semaphore.
            deployment, found = self.pairs(lab_id, node)
            devices, complete = self.read_all(deployment, found, lambda request: self.diagnostics.diagnose(request, READ_TIMEOUT)) if found else ({}, True)
            answer = {'devices': {}, 'interfaces': 0, 'complete': complete, 'fetched_at': time.time()}
            for name, item in devices.items():
                answer['devices'][name] = {'present': item['present'], 'id': item['id'], 'impairments': item['impairments']}
                answer['interfaces'] += len(item['impairments'])
            return answer

        @app.post('/api/operations/impairments/set')
        def set_impairment(data: SetRequest):
            expected_id = self.checked_id(data.expected_id)
            lock = self.lab_lock(data.lab_id)
            if not lock.acquire(blocking=False): raise HTTPException(409, CHANGE_IN_PROGRESS)
            try:
                with self.operations.impairing(data.lab_id):
                    node, deployment, container, topo, shown, state = self.device(data.lab_id, data.node)
                    self.refuse_interface(self.kind_of(node), data.interface, shown, state)
                    values = {k: getattr(data, k) for k in ('delay', 'jitter', 'loss', 'rate', 'corruption')}
                    try: impairment_values(values)
                    except ValueError as exc: raise HTTPException(400, str(exc)) from None
                    for key in ('loss', 'corruption'):
                        if values[key] == 0: values[key] = 0   # -0.0 travels as 0
                    options = {'node': topo, 'container': container, 'interface': data.interface, **values}
                    request = {'mode': 'netem-set', 'name': deployment, 'options': options, 'expected_id': expected_id}
                    request['digest'] = digest({k: request[k] for k in ('mode', 'name', 'options', 'expected_id')})
                    result = self.helper(request)
                    rows = public_rows(result.get('impairments'), self.kind_of(node))
                    row = next((r for r in rows if r['interface'] == data.interface), None)
                    self.store.event('lab.impairment', 'Impairment set on %s %s: %s' % (shown, data.interface, self.describe(row or {
                        'delay': values['delay'], 'jitter': values['jitter'], 'loss': values['loss'], 'rate': values['rate'], 'corruption': values['corruption']})),
                        lab_id=data.lab_id, node=shown)
                    return {'container': container, 'impairments': rows}
            finally: lock.release()

        @app.post('/api/operations/impairments/reset')
        def reset_impairment(data: DeviceRequest):
            expected_id = self.checked_id(data.expected_id)
            lock = self.lab_lock(data.lab_id)
            if not lock.acquire(blocking=False): raise HTTPException(409, CHANGE_IN_PROGRESS)
            try:
                with self.operations.impairing(data.lab_id):
                    node, deployment, container, topo, shown, state = self.device(data.lab_id, data.node)
                    self.refuse_interface(self.kind_of(node), data.interface, shown, state)
                    options = {'node': topo, 'container': container, 'interface': data.interface}
                    request = {'mode': 'netem-reset', 'name': deployment, 'options': options, 'expected_id': expected_id}
                    request['digest'] = digest({k: request[k] for k in ('mode', 'name', 'options', 'expected_id')})
                    result = self.helper(request)
                    changed = result.get('changed') is True
                    if changed: self.store.event('lab.impairment', 'Impairment reset on %s %s' % (shown, data.interface), lab_id=data.lab_id, node=shown)
                    return {'container': container, 'changed': changed, 'impairments': public_rows(result.get('impairments'), self.kind_of(node))}
            finally: lock.release()

        @app.post('/api/operations/impairments/clear')
        def clear_impairments(data: ClearRequest):
            lock = self.lab_lock(data.lab_id)
            if not lock.acquire(blocking=False): raise HTTPException(409, CHANGE_IN_PROGRESS)
            try:
                with self.operations.impairing(data.lab_id):
                    started = time.monotonic()
                    deployment, found = self.pairs(data.lab_id, data.node)
                    devices, complete = self.read_all(deployment, found, self.helper) if found else ({}, True)
                    with self.store.lock:
                        lab = self.store.lab(data.lab_id) or {}
                        names = {n['name']: n.get('short_name') or n.get('definition_node') or n['name'] for n in lab.get('nodes', [])}
                        scope = names.get(data.node, data.node) if data.node else lab.get('name', '')
                    work = [(name, row['interface']) for name, item in devices.items() for row in item['impairments']]
                    rows_now = {name: list(item['impairments']) for name, item in devices.items() if item['impairments']}
                    ids = {}; cleared = 0; failed = []; done = 0
                    for index, (name, interface) in enumerate(work):
                        if time.monotonic() - started >= CLEAR_BUDGET: break
                        item = devices[name]
                        try:
                            if name not in ids:
                                ids[name] = item['id']
                                if not ids[name]:
                                    # The read carried no container id: take it from a single-device read (the helper checks it again at execution).
                                    one = self.helper({'mode': 'netem-show', 'name': deployment, 'options': {'node': item['topo'], 'container': item['container']}})
                                    facts = one.get('facts') if isinstance(one.get('facts'), dict) else {}
                                    ids[name] = facts.get('id') if isinstance(facts.get('id'), str) and HEX64.fullmatch(facts['id']) else ''
                            if not ids[name]: raise HTTPException(409, "The manager could not read this device's container; try again in a moment.")
                            request = {'mode': 'netem-reset', 'name': deployment, 'options': {'node': item['topo'], 'container': item['container'], 'interface': interface},
                                       'expected_id': ids[name]}
                            request['digest'] = digest({k: request[k] for k in ('mode', 'name', 'options', 'expected_id')})
                            result = self.helper(request)
                        except HTTPException as exc:
                            failed.append({'node': name, 'interface': interface, 'reason': str(exc.detail)[:300]}); done = index + 1
                            break
                        cleared += 1; done = index + 1
                        rows_now[name] = public_rows(result.get('impairments'), item['kind'])
                    remaining = [{'node': n, 'interface': i} for n, i in work[done:]]
                    with self.store.lock:
                        lab = self.store.lab(data.lab_id) or {}
                        names = {n['name']: n.get('short_name') or n.get('definition_node') or n['name'] for n in lab.get('nodes', [])}
                        scope = names.get(data.node, data.node) if data.node else lab.get('name', '')
                    self.store.event('lab.impairment', 'Impairments cleared on %s: %d of %d interfaces' % (scope, cleared, len(work)), lab_id=data.lab_id, node=names.get(data.node, '') if data.node else '')
                    return {'cleared': cleared, 'total': len(work), 'failed': failed, 'remaining': remaining, 'complete': complete,
                            'devices': {name: {'impairments': rows} for name, rows in rows_now.items()}}
            finally: lock.release()

        @app.get('/api/operations/apply-plan')
        def apply_plan(lab_id: str = Query(max_length=64), refresh: str = ''):
            with self.store.lock:
                lab = self.store.lab(lab_id)
                if not lab: raise HTTPException(404, 'Lab not found')
                deployment = lab.get('deployment_name') or ''
                source = lab.get('vm_source') if isinstance(lab.get('vm_source'), dict) else {}
                path = lab.get('vm_project_path') or ((source.get('files') or {}).get('definition') or {}).get('path', '')
            if not deployment: raise HTTPException(409, UNLINKED_SENTENCE)
            if not isinstance(path, str) or not path.startswith('/'): raise HTTPException(409, NO_FOLDER_SENTENCE)
            operations = self.operations
            with operations.plan_lock:
                cached = operations.plan_cache.get(lab_id)
                generation = operations.plan_gen.get(lab_id, 0)
                if cached and cached[0] > time.monotonic() and refresh in ('', '0', 'false'): return dict(cached[1])
            result = self.diagnostics.diagnose({'mode': 'apply-plan', 'name': deployment, 'path': path}, READ_TIMEOUT)
            failed = result.get('failed') if result.get('failed') in ('unsupported', 'error') else ''
            plan = public_plan(result.get('plan')) if isinstance(result.get('plan'), dict) and not failed else None
            answer = {'changed': bool(plan) and plan_changes(plan), 'plan': plan, 'failed': failed,
                      'error': strip_escapes(text_value(result.get('error'), 2000))[:300] if failed == 'error' else '', 'checked_at': time.time()}
            with operations.plan_lock:
                if operations.plan_gen.get(lab_id, 0) == generation: operations.plan_cache[lab_id] = (time.monotonic() + PLAN_TTL, answer)
            return dict(answer)
