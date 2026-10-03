"""*Network design*: the intent document on a lab, generation jobs, their immutable artifacts and the routes.

Planning never touches a device, the VM or Docker: this module imports no SSH transport and calls no
host helper. A generation reads the lab's stored topology text and its intent, builds the netlab topology
(:mod:`design_adapter`), refuses unsupported targets before the engine runs (:mod:`design_capabilities`),
runs the pinned engine in a private working directory (:mod:`design_engine`), fixes allocation collisions
with a second pass, checks the plan for overlaps, writes the ordered per-device artifacts and the plan
under ``DATA_DIR/network-design/<lab_id>/<generation_id>/`` and records an immutable generation on the lab.

State on the lab record (private, stripped by ``public_lab`` and exposed only through this module's own
serialisers): ``network_design`` (the normalised intent, :mod:`design_intent`) and ``network_generations``
(the newest ``GENERATION_CAP`` records). A lab without them behaves exactly as before: the feature is
opt-in and nothing migrates, renumbers or configures anything.

Applying a generation to devices is a separate contract (the provisioning drivers) and is not in this
module.
"""
import base64
import copy
import hashlib
import io
import json
import os
import re
import shutil
import threading
import time
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote

import yaml
from fastapi import HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, ConfigDict, Field
from starlette.background import BackgroundTask

from . import design_adapter as adapter
from . import design_capabilities as capabilities
from . import design_engine as engine
from . import design_intent as intent_schema
from .runner import now

ADAPTER_VERSION = '1'
GENERATION_CAP = 20
DESIGN_BUSY = ('queued', 'running')
PUBLIC_GENERATION = ('id', 'lab_id', 'created', 'started', 'finished', 'status', 'message', 'intent_revision',
                     'topology_digest', 'mapping_digest', 'engine_version', 'adapter_version', 'profiles',
                     'modules', 'families', 'nodes', 'blocked', 'notes', 'warnings', 'errors', 'artifacts',
                     'compatibility', 'ledger', 'renumbering', 'collision_fixes', 'overlaps', 'duration',
                     'plan_digest', 'passes', 'label')
NO_TOPOLOGY = ('This lab has no topology file in the manager, so nothing can be designed for it. Add the '
               'topology under Advanced › Update topology file… first.')
MODULE_FEATURES = {'ospf': ('ospfv2',), 'bgp': ('bgp',), 'isis': ('isis',), 'eigrp': ('eigrp',), 'ripv2': ('ripv2',),
                   'bfd': ('bfd',), 'dhcp': ('dhcp',), 'vlan': ('vlan',), 'vrf': ('vrf',), 'lag': ('lag',), 'stp': ('stp',),
                   'gateway': (), 'vxlan': ('vxlan',), 'evpn': ('evpn',), 'mpls': (), 'sr': ('sr_mpls',), 'srv6': ('srv6',),
                   'routing': ()}


def _settings_of(intent, modules, node=None):
    """Every value each module setting takes across the levels a design carries it at (global, the devices,
    the links and their ends, the VRFs), as {module: {key: [values]}}: what decides which sub-features are
    requested. With `node`, only that device's own settings and the links it is on count."""
    settings = {module: {} for module in modules}

    def merge(container):
        if not isinstance(container, dict): return
        for module in modules:
            body = container.get(module)
            if isinstance(body, dict):
                for key, value in body.items(): settings[module].setdefault(key, []).append(value)
    merge(intent)
    for name, body in (intent.get('nodes') or {}).items():
        if node is None or name == node: merge(body)
    for key, link in (intent.get('links') or {}).items():
        if not isinstance(link, dict): continue
        if node is not None and not any(end.startswith(node + ':') for end in key.split('--')): continue
        merge(link)
        for end_name, end in (link.get('endpoints') or {}).items():
            if node is None or end_name == node: merge(end)
    for vrf in (intent.get('vrfs') or {}).values(): merge(vrf)
    return settings


def _any(settings, module, key, test):
    return any(test(value) for value in (settings.get(module) or {}).get(key, []))


def requested_features(intent, modules=None, node=None):
    """The capability ids a design asks for, derived from its modules (or the given effective module set of
    one device), its families and its settings at every level (for `node`: that device's own), never from a
    device: what the compatibility check resolves per device before the engine runs. Every value a setting
    takes anywhere counts (two links with `vrrp` and `anycast` request both gateway protocols)."""
    modules = set(intent.get('modules') or []) if modules is None else set(modules)
    families = intent.get('families') or {'ipv4': True, 'ipv6': True}
    features = set()
    for module in modules:
        features.update(MODULE_FEATURES.get(module, ()))
    if families.get('ipv4', True): features.add('ipv4')
    if families.get('ipv6', True): features.add('ipv6')
    if 'ospf' in modules and families.get('ipv6', True): features.add('ospfv3')
    if 'ripv2' in modules and families.get('ipv6', True): features.add('ripng')
    if 'dhcp' in modules and families.get('ipv6', True): features.add('dhcpv6')
    settings = _settings_of(intent, modules, node)
    if 'gateway' in modules:
        protocols = [str(v) for v in (settings.get('gateway') or {}).get('protocol', [])] or ['anycast']
        if 'vrrp' in protocols: features.add('vrrp')
        if any(p != 'vrrp' for p in protocols): features.add('anycast_gateway')
    if 'lag' in modules:
        if _any(settings, 'lag', 'lacp', lambda v: v not in (None, 'off')): features.add('lacp')
        if 'mlag' in (settings.get('lag') or {}): features.add('mlag')
    if 'mpls' in modules:
        if not _any(settings, 'mpls', 'ldp', lambda v: v is False) or _any(settings, 'mpls', 'ldp', lambda v: v not in (False, None)): features.add('mpls_ldp')
        if _any(settings, 'mpls', 'bgp', bool): features.add('bgp_lu')
        if _any(settings, 'mpls', 'vpn', bool): features.add('l3vpn')
        if _any(settings, 'mpls', '6pe', bool): features.add('sixpe')
    if 'routing' in modules:
        for key, feature in (('policy', 'route_policy'), ('prefix', 'prefix_list'), ('aspath', 'aspath_filter'), ('static', 'static_routes')):
            if _any(settings, 'routing', key, bool): features.add(feature)
    for module in modules:
        if _any(settings, module, 'import', bool): features.add('redistribution')
    if 'bgp' in modules and _any(settings, 'bgp', 'originate', bool): features.add('default_originate')
    return features


def effective_modules(intent, name, row):
    """The modules one device really gets: its own `modules` list when it has one (netlab's rule: the list
    replaces the design's), else the design's modules, or none for a host without explicit modules (the
    adapter emits `module: []` for it)."""
    settings = (intent.get('nodes') or {}).get(name) or {}
    modules = set(intent.get('modules') or [])
    if isinstance(settings.get('modules'), list): return set(settings['modules'])
    if row.get('role') == 'host': return set()
    return modules


def digest(text):
    return hashlib.sha256(text.encode() if isinstance(text, str) else json.dumps(text, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def public_generation(generation):
    return {k: copy.deepcopy(generation[k]) for k in PUBLIC_GENERATION if k in generation}


def public_design(lab):
    """The design summary a lab carries in /api/state: presence, revision and the newest generation."""
    intent = lab.get('network_design')
    generations = lab.get('network_generations') or []
    newest = generations[-1] if generations else None
    if not intent and not newest: return None
    summary = {'present': bool(intent), 'revision': (intent or {}).get('revision', ''), 'updated': (intent or {}).get('updated', ''),
               'label': (intent or {}).get('label', ''), 'modules': list((intent or {}).get('modules') or []),
               'generating': any(g.get('status') in DESIGN_BUSY for g in generations),
               'generation': {k: newest.get(k) for k in ('id', 'status', 'message', 'created', 'finished', 'intent_revision')} if newest else None}
    if newest and intent: summary['stale'] = newest.get('intent_revision') != intent.get('revision') or (newest.get('status') == 'succeeded' and (newest.get('ledger') or {}) != (intent.get('allocations') or {}))
    return summary


def _append_generation(lab, generation):
    """Keep the newest GENERATION_CAP records; a running one is never dropped. Returns the dropped ids."""
    records = lab.setdefault('network_generations', [])
    records.append(generation)
    dropped = []
    while len(records) > GENERATION_CAP:
        victim = next((g for g in records if g.get('status') not in DESIGN_BUSY), None)
        if victim is None: break
        records.remove(victim); dropped.append(victim['id'])
    return dropped


class NetworkDesign:
    def __init__(self, store):
        self.store = store
        self.root = Path(store.root) / 'network-design'
        self.work = self.root / 'work'
        self.stopping = threading.Event()
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='design')
        self.cancel = {}          # generation id -> threading.Event
        self.active = set()
        with store.lock:
            for lab in store.state['labs']:
                for generation in lab.get('network_generations') or []:
                    if generation.get('status') in DESIGN_BUSY:
                        generation.update(status='interrupted', finished=now(),
                                          message='The manager restarted while this plan was being generated. Generate it again.')
            store.save()
        for job in (self.work.iterdir() if self.work.is_dir() else []):
            shutil.rmtree(job, ignore_errors=True)

    def close(self):
        self.stopping.set()
        for event in list(self.cancel.values()): event.set()
        self.pool.shutdown(wait=False, cancel_futures=True)

    def guard_idle(self, lab_id=None):
        """Refuse (409) while a plan is being generated for `lab_id` (or for any lab): Remove lab and Start
        fresh must not race a generation that is about to write its files."""
        for lab in self.store.state['labs']:
            if lab_id and lab.get('id') != lab_id: continue
            if any(g.get('status') in DESIGN_BUSY for g in lab.get('network_generations') or []):
                raise HTTPException(409, 'Wait for the network design plan being generated to finish.')

    # --- helpers ---------------------------------------------------------------------------------------

    def lab(self, lab_id):
        lab = self.store.lab(lab_id)
        if not lab: raise HTTPException(404, 'Lab not found')
        return lab

    def generation(self, lab, generation_id):
        found = next((g for g in lab.get('network_generations') or [] if g['id'] == generation_id), None)
        if not found: raise HTTPException(404, 'Generated plan not found.')
        return found

    def folder(self, lab_id, generation_id):
        if not re.fullmatch(r'[0-9a-f]{32}', lab_id or '') or not re.fullmatch(r'[0-9a-f]{32}', generation_id or ''):
            raise HTTPException(404, 'Generated plan not found.')
        return self.root / lab_id / generation_id

    def context(self, lab):
        """What the page needs beside the intent: the lab's designable devices and links with their mapping
        (as the adapter sees them today), the engine, and the capability matrix for the lab's kinds."""
        text = lab.get('definition_yaml') or ''
        intent = lab.get('network_design') or intent_schema.empty_intent()
        nodes = {}; links = []; notes = []
        if text:
            try:
                built = adapter.build(text, lab.get('nodes', []), intent, capabilities.profile_for)
                nodes = built['nodes']; links = built['links']; notes = built['notes']
            except (adapter.AdapterError, ValueError) as exc:
                notes = [str(exc)]
        kinds = sorted({row['kind'] for row in nodes.values() if row.get('kind')})
        # `modules` is what a student may choose (retired modules are not offered); `retired` explains each retired
        # one and `retired_in_design` lists where the saved design still uses one (kept, readable, not generated).
        return {'has_topology': bool(text), 'topology_digest': digest(text) if text else '', 'nodes': nodes, 'links': links,
                'notes': notes, 'kinds': kinds, 'capabilities': capabilities.public_matrix(kinds) if kinds else [],
                'catalogue': capabilities.public_catalogue(), 'engine': engine.engine_status(),
                'modules': list(intent_schema.AUTHORING_MODULES), 'pools': list(intent_schema.POOLS),
                'retired': dict(intent_schema.RETIRED), 'retired_status': dict(intent_schema.RETIRED_STATUS),
                'retired_labels': dict(intent_schema.RETIRED_LABELS),
                'retired_in_design': intent_schema.retired_in(lab.get('network_design') or {})}

    def validation(self, lab, intent):
        text = lab.get('definition_yaml') or ''
        lab_nodes = None; lab_links = None
        if text:
            try:
                from .discovery import parse_definition
                lab_nodes = {n['definition_node']: n.get('kind', '') for n in parse_definition(text.encode())['nodes']}
                lab_links = [l['key'] for l in adapter.parse_links(text) if not l['problem']]
            except (ValueError, adapter.AdapterError):
                lab_nodes = lab_links = None
        return intent_schema.validate(intent, lab_nodes=lab_nodes, lab_links=lab_links, schema=capabilities.engine_data(),
                                      management=adapter.management_networks(text, lab.get('nodes', [])))

    def view(self, lab):
        intent = lab.get('network_design')
        return {'intent': copy.deepcopy(intent) if intent else None, 'summary': public_design(lab),
                'generations': [public_generation(g) for g in lab.get('network_generations') or []],
                'problems': self.validation(lab, intent) if intent else [], **self.context(lab)}

    # --- generation ------------------------------------------------------------------------------------

    def compatibility(self, intent, nodes):
        """Per included device, every feature its effective module set asks for, resolved against its kind.
        `unsupported` and `blocked_missing_prerequisite` entries block the generation; nothing is dropped or
        downgraded silently."""
        report = {}; blocking = []
        for name, row in nodes.items():
            if not row.get('included'): continue
            modules = effective_modules(intent, name, row)
            rows = []
            for feature in sorted(requested_features(intent, modules, node=name)):
                result = capabilities.resolve(feature, row['kind'], requested_modules=modules)
                shown = capabilities.with_policy(result)   # a retired capability reads `retired`; blocking stays the engine's answer
                entry = {k: shown.get(k, '') for k in ('feature', 'level', 'reason', 'evidence', 'profile')}
                if 'policy' in shown: entry.update(engine_level=shown['engine_level'], policy=shown['policy'])
                rows.append(entry)
                if result.get('level') in ('unsupported', 'blocked_missing_prerequisite') and (modules or feature in ('ipv4', 'ipv6')) and not (row.get('role') == 'host' and not modules):
                    blocking.append(name + ': ' + feature + (' is not supported on kind ' if result.get('level') == 'unsupported' else ' is missing a prerequisite on kind ') + row['kind'] + (' (' + result['reason'] + ')' if result.get('reason') else ''))
            report[name] = rows
        return report, blocking

    def submit(self, lab_id, revision):
        with self.store.lock:
            lab = self.lab(lab_id)
            intent = lab.get('network_design')
            if not intent: raise HTTPException(409, 'Save a design first.')
            if revision and revision != intent.get('revision'): raise HTTPException(409, 'The design changed since this page loaded. Reload it and generate again.')
            if not lab.get('definition_yaml'): raise HTTPException(409, NO_TOPOLOGY)
            if any(g.get('status') in DESIGN_BUSY for g in lab.get('network_generations') or []):
                raise HTTPException(409, 'A plan is already being generated for this lab.')
            if self.store.reset_pending: raise HTTPException(409, 'Finish the storage reset first.')
            retired = intent_schema.retired_in(intent)
            if retired: raise HTTPException(409, retired_detail(retired))
            problems = self.validation(lab, intent)
            if problems: raise HTTPException(400, problems_detail(problems))
            generation = {'id': uuid.uuid4().hex, 'lab_id': lab_id, 'created': now(), 'status': 'queued', 'message': 'Waiting to generate',
                          'intent_revision': intent['revision'], 'topology_digest': digest(lab['definition_yaml']),
                          'adapter_version': ADAPTER_VERSION, 'label': intent.get('label', '')}
            before = list(lab.get('network_generations') or [])
            dropped = _append_generation(lab, generation)
            try: self.store.save()
            except OSError:
                lab['network_generations'] = before; raise HTTPException(500, 'Could not save the plan request; nothing was generated.')
            self.cancel[generation['id']] = threading.Event()
            previous = next((g for g in reversed(lab.get('network_generations') or []) if g.get('status') == 'succeeded' and g.get('ledger')), None)
            snapshot = {'lab_id': lab_id, 'generation_id': generation['id'], 'definition_yaml': lab['definition_yaml'],
                        'nodes': copy.deepcopy(lab.get('nodes', [])), 'intent': copy.deepcopy(intent),
                        'previous_ledger': copy.deepcopy(previous['ledger']) if previous else copy.deepcopy(intent.get('allocations') or {})}
            self.store.event('design.generate', 'Plan generation queued', lab_id=lab_id, job_id=generation['id'])
            for old in dropped: shutil.rmtree(self.root / lab_id / old, ignore_errors=True)   # under the lock: a reset cannot interleave
            try: self.pool.submit(self.execute, lab_id, generation['id'], snapshot)
            except RuntimeError:
                generation.update(status='interrupted', message='Manager is shutting down. Generate again after the restart.'); self.store.save()
                raise HTTPException(409, generation['message'])
        return public_generation(generation)

    def update(self, lab_id, generation_id, **fields):
        with self.store.lock:
            lab = self.store.lab(lab_id)
            generation = next((g for g in (lab or {}).get('network_generations') or [] if g['id'] == generation_id), None)
            if generation is None: return None
            generation.update(fields)
            try: self.store.save()
            except OSError: pass
            return generation

    def execute(self, lab_id, generation_id, snapshot):
        self.active.add(generation_id)
        stop = self.cancel.get(generation_id) or threading.Event()
        started = time.monotonic()
        try:
            if not self.update(lab_id, generation_id, status='running', started=now(), message='Generating the plan'): return
            result = self._generate(snapshot, stop)
            if not self._finish(lab_id, generation_id, snapshot['intent'].get('revision', ''), result): return
            self.store.event('design.generated', 'Plan generation finished: ' + str(result['status']), lab_id=lab_id, job_id=generation_id,
                             level='info' if result['status'] == 'succeeded' else 'error')
        except Exception:
            message = 'Plan generation failed inside the manager. Check the manager log and generate again.'
            self.update(lab_id, generation_id, status='failed', finished=now(), message=message, errors=[message], duration=round(time.monotonic() - started, 2))
        finally:
            self.active.discard(generation_id); self.cancel.pop(generation_id, None)

    def _finish(self, lab_id, generation_id, revision, result):
        """Record the outcome and, for a successful plan, write its allocations into the intent's ledger, in one
        locked step (so a Renumber cannot slip in between and be undone). The ledger is written only when the
        design is still the one the plan was made from. Returns False when the record is gone."""
        with self.store.lock:
            lab = self.store.lab(lab_id)
            generation = next((g for g in (lab or {}).get('network_generations') or [] if g['id'] == generation_id), None)
            if generation is None:
                # The lab (or the record) went away while the plan was being made: its files go too.
                shutil.rmtree(self.root / lab_id / generation_id, ignore_errors=True)
                if lab is None: shutil.rmtree(self.root / lab_id, ignore_errors=True)
                return False
            generation.update(result)
            intent = lab.get('network_design')
            if result.get('status') == 'succeeded' and intent and intent.get('revision') == revision and intent.get('allocations') != result.get('ledger'):
                intent['allocations'] = copy.deepcopy(result.get('ledger') or {})
            try: self.store.save()
            except OSError: pass
            return True

    def _run_engine(self, topology, stop):
        self.work.mkdir(parents=True, exist_ok=True, mode=0o700)
        result = engine.run_generation(str(self.work), topology, stopping=stop)
        return result

    def _scrub(self, lines):
        """Engine lines for a record: the data directory and the job directory never appear in them."""
        clean = []
        for line in lines:
            line = str(line).replace(str(self.work), '<work>').replace(str(self.root), '<design>').replace(str(self.store.root), '<data>')
            clean.append(line[:500])
        return clean

    def _generate(self, snapshot, stop):
        """The whole plan of one generation; returns the fields that finish the record."""
        started = time.monotonic(); text = snapshot['definition_yaml']; intent = snapshot['intent']
        try: built = adapter.build(text, snapshot['nodes'], intent, capabilities.profile_for)
        except adapter.AdapterError as exc:
            return dict(status='failed', finished=now(), message=str(exc), errors=[str(exc)], duration=round(time.monotonic() - started, 2))
        compatibility, blocking = self.compatibility(intent, built['nodes'])
        common = {'profiles': {n: r['profile'] for n, r in built['nodes'].items() if r['included']}, 'modules': list(intent.get('modules') or []),
                  'families': copy.deepcopy(intent.get('families') or {}), 'nodes': built['nodes'], 'blocked': built['blocked'], 'notes': built['notes'],
                  'compatibility': compatibility, 'mapping_digest': digest(built['mapping']), 'adapter_version': ADAPTER_VERSION}
        if blocking:
            return dict(common, status='failed', finished=now(), message='The design asks for something a device in this lab cannot do. Nothing was generated.',
                        errors=blocking, duration=round(time.monotonic() - started, 2))
        if stop.is_set(): return dict(common, status='failed', finished=now(), message='Generation cancelled.', errors=['Cancelled before the engine ran.'], duration=round(time.monotonic() - started, 2))
        management = adapter.management_networks(text, snapshot['nodes'])
        ledger = intent.get('allocations') or {}
        # Explicit link prefixes of the intent are as fixed as pinned ones for the collision check.
        pinned = {'links': dict((ledger.get('links') or {}))}
        for key, link in (intent.get('links') or {}).items():
            prefix = link.get('prefix') if isinstance(link, dict) else None
            if isinstance(prefix, dict): pinned['links'][key] = {f: prefix[f] for f in ('ipv4', 'ipv6') if isinstance(prefix.get(f), str)}
        passes = 0; fixes = {}; workdirs = []; run = None
        try:
            run = self._run_engine(built['topology'], stop); passes = 1; workdirs.append(run.get('workdir'))
            if run['ok']:
                collisions = adapter.collisions(run['transformed'], built['link_keys'], pinned)
                if collisions and not stop.is_set():
                    fixes = adapter.fix_collisions(run['transformed'], built['link_keys'], pinned, intent.get('addressing') or {}, avoid=[n for _, n in management])
                    unfixed = [c['key'] for c in collisions if c['family'] not in (fixes.get(c['key']) or {})]
                    if unfixed:
                        return dict(common, status='failed', finished=now(), passes=passes, message='The address pools are exhausted for some links. Enlarge the pools or clear the allocation ledger.',
                                    errors=['No free prefix for link ' + k for k in sorted(set(unfixed))], duration=round(time.monotonic() - started, 2))
                    # The second pass pins every link of the first pass (with the fixes applied), so nothing else moves.
                    pins = adapter.link_prefixes(run['transformed'], built['link_keys'])
                    for key, prefix in fixes.items(): pins.setdefault(key, {}).update(prefix)
                    built = adapter.build(text, snapshot['nodes'], intent, capabilities.profile_for, pins={'links': pins})
                    run = self._run_engine(built['topology'], stop); passes = 2; workdirs.append(run.get('workdir'))
            if not run['ok']:
                cancelled = stop.is_set()
                return dict(common, status='failed', finished=now(), passes=passes,
                            message='Generation cancelled.' if cancelled else 'The design engine could not generate this plan.',
                            errors=self._scrub(run.get('errors') or []) or ['The engine reported no detail.'], engine_version=run.get('engine_version', ''),
                            duration=round(time.monotonic() - started, 2))
            transformed = run['transformed']
            overlapping = adapter.overlaps(transformed, avoid=management)
            if overlapping:
                return dict(common, status='failed', finished=now(), passes=passes, overlaps=overlapping,
                            message='The plan has overlapping addresses. Check explicit prefixes and the allocation ledger.',
                            errors=[o['family'] + ': ' + o['a'] + ' overlaps ' + o['b'] for o in overlapping[:20]], duration=round(time.monotonic() - started, 2))
            new_ledger = intent_schema.ledger_from_plan(transformed, built['link_keys'])
            collisions_after = adapter.collisions(transformed, built['link_keys'], pinned)
            if collisions_after:
                return dict(common, status='failed', finished=now(), passes=passes, message='The plan still collides with pinned prefixes. Clear the allocation ledger or set explicit prefixes.',
                            errors=[c['key'] + ' (' + c['family'] + ') collides with ' + c['with'] for c in collisions_after[:20]], duration=round(time.monotonic() - started, 2))
            renumbering = intent_schema.renumbering(snapshot.get('previous_ledger') or {}, new_ledger)
            plan = adapter.plan_summary(transformed, built['mapping'])
            warnings = self._scrub([line for line in (run.get('stderr_tail') or '').splitlines() if re.match(r'^\w*Warning', line)][:50])
            self._store_artifacts(snapshot, run, built, plan, transformed, fixes)
            artifacts = {}
            for node, items in run['artifacts'].items():
                if node not in built['nodes'] or not built['nodes'][node]['included']: continue
                artifacts[node] = [{'module': module, 'size': len(text_.encode()), 'sha256': hashlib.sha256(text_.encode()).hexdigest()} for module, text_ in items]
            return dict(common, status='succeeded', finished=now(), passes=passes, message='Plan generated', engine_version=run.get('engine_version', ''),
                        artifacts=artifacts, ledger=new_ledger, renumbering=renumbering, collision_fixes=fixes, warnings=warnings, errors=[],
                        plan_digest=digest(plan), duration=round(time.monotonic() - started, 2))
        finally:
            for workdir in workdirs:
                if workdir: shutil.rmtree(workdir, ignore_errors=True)

    def _store_artifacts(self, snapshot, run, built, plan, transformed, fixes):
        folder = self.root / snapshot['lab_id'] / snapshot['generation_id']
        for part in (self.root, self.root / snapshot['lab_id'], folder):
            part.mkdir(exist_ok=True, mode=0o700)
            os.chmod(part, 0o700)
        _write(folder / 'intent.json', json.dumps(snapshot['intent'], indent=2, sort_keys=True))
        _write(folder / 'topology.yml', yaml.safe_dump(built['topology'], sort_keys=False))
        _write(folder / 'plan.json', json.dumps(plan, indent=2, sort_keys=True))
        _write(folder / 'transformed.json', json.dumps(transformed, sort_keys=True, default=str))
        _write(folder / 'mapping.json', json.dumps({'mapping': built['mapping'], 'link_keys': built['link_keys'], 'collision_fixes': fixes}, indent=2, sort_keys=True))
        for node, items in run['artifacts'].items():
            if node not in built['nodes'] or not built['nodes'][node]['included'] or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,199}', node): continue
            node_dir = folder / 'nodes' / node
            (folder / 'nodes').mkdir(exist_ok=True, mode=0o700); node_dir.mkdir(exist_ok=True, mode=0o700)
            for index, (module, text_) in enumerate(items):
                if not re.fullmatch(r'[a-z0-9_.-]{1,40}', module): continue
                _write(node_dir / ('%02d-%s' % (index, module)), text_)
        return folder

    def design_snapshot(self, lab, generation, lab_name=None):
        """The reviewed export set of one plan for the student's Git save (`git_progress`, kind `design`): the intent,
        the plan, the netlab topology, the endpoint mapping and every generated file, base64 like a capture, with a
        manifest that names them generated artifacts. Never a backup: no node rows, no restore artifact, so the
        restore lists such a version as view and download only."""
        if generation.get('status') != 'succeeded': raise ValueError('Only a generated plan can be exported.')
        folder = self.folder(lab['id'], generation['id'])
        files, rows, total = {}, [], 0

        def put(name, raw, **extra):
            nonlocal total
            if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,180}', name) or name in files: raise ValueError('The export has an unusable file name.')
            if not raw or len(raw) > 2 * 1024 * 1024: raise ValueError('A generated file is empty or too large to export.')
            total += len(raw)
            if total > 16 * 1024 * 1024 or len(files) >= 500: raise ValueError('The export exceeds the transfer limits.')
            files[name] = base64.b64encode(raw).decode()
            rows.append({'path': name, 'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(), 'artifact': 'network-design', **extra})

        try: intent = json.loads((folder / 'intent.json').read_text())   # the intent this plan was built from, not the design as it is now
        except (OSError, ValueError): raise ValueError('The intent of this plan is missing; generate the plan again.')
        if not isinstance(intent, dict): raise ValueError('The intent of this plan is unreadable; generate the plan again.')
        stamp = generation.get('finished') or generation.get('created', '')   # reproducible: the digest binds the export at creation and at execution
        name = lab_name if lab_name is not None else lab.get('name', '')   # the job's frozen name: a renamed lab does not change a pending export
        document = {'containerlab_node_manager': {'type': 'network-intent', 'exported': stamp, 'lab': name, 'generation': generation['id']}, **intent}
        put('network-intent.yml', yaml.safe_dump(document, sort_keys=False, allow_unicode=True).encode(), kind='intent')
        for name, kind in (('plan.json', 'plan'), ('topology.yml', 'topology'), ('mapping.json', 'mapping')):
            try: raw = (folder / name).read_bytes()
            except OSError: raise ValueError('A file of this plan is missing; generate the plan again.')
            put(name, raw, kind=kind)
        for node, entries in sorted((generation.get('artifacts') or {}).items()):
            if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,199}', node): raise ValueError('A device name of this plan cannot be exported.')
            for index, entry in enumerate(entries):
                path = folder / 'nodes' / node / ('%02d-%s' % (index, entry['module']))
                try: raw = path.read_bytes()
                except OSError: raise ValueError('A generated file of this plan is missing; generate the plan again.')
                if hashlib.sha256(raw).hexdigest() != entry['sha256']: raise ValueError('A generated file of this plan changed on disk; generate the plan again.')
                if not raw: continue   # netlab writes an empty file for a module with nothing to say on a device; an export carries no empty file
                put('%s--%02d-%s.cfg' % (node, index, entry['module']), raw, kind='fragment', device=node, module=entry['module'])
        manifest = {'schema': 2, 'kind': 'network-design', 'lab_id': lab['id'], 'lab_name': name,
                    'generation_id': generation['id'], 'intent_revision': generation.get('intent_revision', ''),
                    'topology_digest': generation.get('topology_digest', ''), 'engine_version': generation.get('engine_version', ''),
                    'generated_at': generation.get('finished') or generation.get('created', ''), 'modules': list(generation.get('modules') or []),
                    'devices': sorted({r['device'] for r in rows if r.get('device')}), 'node_names': [], 'restore_capable_nodes': 0, 'files': rows}
        return {'manifest': manifest, 'files': files}

    def forget_lab(self, lab_id):
        """Remove a removed lab's generated plans (plain-text copies of its intent and configuration)."""
        if re.fullmatch(r'[0-9a-f]{32}', lab_id or ''): shutil.rmtree(self.root / lab_id, ignore_errors=True)

    # --- routes ----------------------------------------------------------------------------------------

    def install(self, app):
        service = self

        class DesignBody(BaseModel):
            model_config = ConfigDict(extra='forbid')
            intent: dict
            revision: str = Field(default='', max_length=64)

        class Revision(BaseModel):
            model_config = ConfigDict(extra='forbid')
            revision: str = Field(default='', max_length=64)

        class Empty(BaseModel):
            model_config = ConfigDict(extra='forbid')

        @app.get('/api/design/engine')
        def engine_status():
            return engine.engine_status()

        @app.get('/api/labs/{lab_id}/design')
        def read_design(lab_id: str):
            with service.store.lock: return service.view(service.lab(lab_id))

        @app.post('/api/labs/{lab_id}/design/validate')
        def validate_design(lab_id: str, data: DesignBody):
            with service.store.lock:
                lab = service.lab(lab_id)
                submitted = dict(data.intent); submitted['allocations'] = copy.deepcopy((lab.get('network_design') or {}).get('allocations') or {})
                problems = service.validation(lab, submitted)
                # Retired uses are reported apart from the problems (the stored design may keep them): `new` marks one the
                # saved design does not have, which Save refuses; Generate refuses a design with any of them.
                added = {(e['path'], e['module']) for e in intent_schema.retired_added(submitted, lab.get('network_design'))}
                retired = [dict(e, new=(e['path'], e['module']) in added) for e in intent_schema.retired_in(submitted)]
                return {'problems': problems, 'valid': not problems, 'retired': retired}

        @app.put('/api/labs/{lab_id}/design')
        def save_design(lab_id: str, data: DesignBody):
            with service.store.lock:
                lab = service.lab(lab_id)
                current = lab.get('network_design')
                if current and data.revision != current.get('revision'):
                    raise HTTPException(409, 'The design changed since this page loaded. Reload it before saving your changes.')
                if not current and data.revision: raise HTTPException(409, 'This lab has no saved design any more. Reload the page.')
                # The allocation ledger is the manager's: a page never overwrites it (Clear allocations is its own action).
                submitted = dict(data.intent); submitted['allocations'] = copy.deepcopy((current or {}).get('allocations') or {})
                problems = service.validation(lab, submitted)
                if problems: raise HTTPException(400, 'Fix the design first: ' + '; '.join(p['path'] + ': ' + p['message'] for p in problems[:5]))
                added = intent_schema.retired_added(submitted, current)
                if added: raise HTTPException(400, retired_added_detail(added))
                stored = intent_schema.normalize(submitted)
                stored['updated'] = now()
                if current and stored['revision'] == current.get('revision') and stored.get('allocations') == current.get('allocations'):
                    return service.view(lab)
                previous = copy.deepcopy(current) if current else None
                lab['network_design'] = stored; lab['updated'] = now()
                try: service.store.save()
                except OSError:
                    if previous is None: lab.pop('network_design', None)
                    else: lab['network_design'] = previous
                    raise HTTPException(500, 'Could not save the design. Try again.')
                service.store.event('design.save', 'Network design saved (revision ' + stored['revision'] + '; modules: ' + ', '.join(stored.get('modules') or []) + ')', lab_id=lab_id)
                return service.view(lab)

        @app.post('/api/labs/{lab_id}/design/clear')
        def clear_design(lab_id: str, data: Revision):
            with service.store.lock:
                lab = service.lab(lab_id)
                current = lab.get('network_design')
                if not current: return service.view(lab)
                if data.revision != current.get('revision'): raise HTTPException(409, 'The design changed since this page loaded. Reload it first.')
                if any(g.get('status') in DESIGN_BUSY for g in lab.get('network_generations') or []): raise HTTPException(409, 'Wait for the plan being generated to finish.')
                lab.pop('network_design', None); lab['updated'] = now()
                try: service.store.save()
                except OSError:
                    lab['network_design'] = current; raise HTTPException(500, 'Could not remove the design. Try again.')
                service.store.event('design.clear', 'Network design removed; generated plans retained', lab_id=lab_id)
                return service.view(lab)

        @app.post('/api/labs/{lab_id}/design/renumber')
        def clear_ledger(lab_id: str, data: Revision):
            """Forget every pinned allocation: the next plan allocates from the pools again. Explicit, never implied."""
            with service.store.lock:
                lab = service.lab(lab_id)
                current = lab.get('network_design')
                if not current: raise HTTPException(404, 'This lab has no design.')
                if data.revision != current.get('revision'): raise HTTPException(409, 'The design changed since this page loaded. Reload it first.')
                if any(g.get('status') in DESIGN_BUSY for g in lab.get('network_generations') or []): raise HTTPException(409, 'Wait for the plan being generated to finish.')
                previous = copy.deepcopy(current.get('allocations') or {})
                current['allocations'] = {}; current['updated'] = now()
                try: service.store.save()
                except OSError:
                    current['allocations'] = previous; raise HTTPException(500, 'Could not clear the allocations. Try again.')
                service.store.event('design.renumber', 'Allocation ledger cleared; the next plan allocates afresh', lab_id=lab_id)
                return service.view(lab)

        @app.post('/api/labs/{lab_id}/design/generate')
        def generate(lab_id: str, data: Revision):
            return service.submit(lab_id, data.revision)

        @app.post('/api/labs/{lab_id}/design/generations/{generation_id}/cancel')
        def cancel(lab_id: str, generation_id: str, data: Empty):
            with service.store.lock:
                generation = service.generation(service.lab(lab_id), generation_id)
                if generation.get('status') not in DESIGN_BUSY: raise HTTPException(409, 'This plan is not being generated.')
                event = service.cancel.get(generation_id)
                if event: event.set()
                return {'cancelling': True}

        @app.get('/api/labs/{lab_id}/design/generations/{generation_id}')
        def read_generation(lab_id: str, generation_id: str):
            with service.store.lock:
                lab = service.lab(lab_id); generation = public_generation(service.generation(lab, generation_id))
            folder = service.folder(lab_id, generation_id)
            plan = None
            if generation.get('status') == 'succeeded':
                try: plan = json.loads((folder / 'plan.json').read_text())
                except (OSError, ValueError): plan = None
            return {'generation': generation, 'plan': plan}

        @app.get('/api/labs/{lab_id}/design/generations/{generation_id}/artifacts/{node}/{index}')
        def read_artifact(lab_id: str, generation_id: str, node: str, index: int):
            with service.store.lock:
                lab = service.lab(lab_id); generation = service.generation(lab, generation_id)
                entries = (generation.get('artifacts') or {}).get(node)
            if not entries or index < 0 or index >= len(entries): raise HTTPException(404, 'Generated file not found.')
            path = service.folder(lab_id, generation_id) / 'nodes' / node / ('%02d-%s' % (index, entries[index]['module']))
            try: text = path.read_bytes()
            except OSError: raise HTTPException(404, 'Generated file is unavailable.')
            if hashlib.sha256(text).hexdigest() != entries[index]['sha256']: raise HTTPException(409, 'The generated file no longer matches its recorded digest.')
            return Response(text, media_type='text/plain; charset=utf-8')

        @app.get('/api/labs/{lab_id}/design/generations/{generation_id}/download')
        def download(lab_id: str, generation_id: str):
            with service.store.lock:
                lab = service.lab(lab_id); generation = copy.deepcopy(service.generation(lab, generation_id)); lab_name = lab['name']
            if generation.get('status') != 'succeeded': raise HTTPException(409, 'Only a generated plan can be downloaded.')
            folder = service.folder(lab_id, generation_id)
            manifest = {'type': 'network-design-generation', 'schema': 1, 'lab': lab_name, 'generation': public_generation(generation),
                        'note': 'Generated configuration fragments and the plan of a network design. Not a backup; not a restore candidate.'}
            fd, path = tempfile_path()
            try:
                with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as archive:
                    for name in ('intent.json', 'plan.json', 'topology.yml', 'mapping.json'):
                        if (folder / name).is_file(): archive.write(folder / name, name)
                    for node, entries in (generation.get('artifacts') or {}).items():
                        for index, entry in enumerate(entries):
                            source = folder / 'nodes' / node / ('%02d-%s' % (index, entry['module']))
                            if source.is_file(): archive.write(source, 'nodes/' + node + '/' + ('%02d-%s' % (index, entry['module'])) + '.cfg')
                    archive.writestr('manifest.json', json.dumps(manifest, indent=2, sort_keys=True))
            except Exception:
                os.unlink(path); raise
            filename = re.sub(r'[^A-Za-z0-9_.-]+', '_', lab_name)[:80] + '-design-' + generation_id[:12] + '.zip'
            service.store.event('design.download', 'Generated plan downloaded: ' + generation_id, lab_id=lab_id, job_id=generation_id)
            return FileResponse(path, filename=filename, media_type='application/zip', background=BackgroundTask(os.unlink, path))

        @app.get('/api/labs/{lab_id}/design/export')
        def export_intent(lab_id: str):
            with service.store.lock:
                lab = service.lab(lab_id); intent = lab.get('network_design')
                if not intent: raise HTTPException(404, 'This lab has no design to export.')
                document = {'containerlab_node_manager': {'type': 'network-intent', 'exported': now(), 'lab': lab['name']}, **copy.deepcopy(intent)}
                filename = re.sub(r'[^A-Za-z0-9_.-]+', '_', lab['name'])[:80] + '.network-intent.yml'
            content = yaml.safe_dump(document, sort_keys=False, allow_unicode=True).encode()
            return Response(content, media_type='application/yaml', headers={'Content-Disposition': "attachment; filename=network-intent.yml; filename*=UTF-8''" + quote(filename, safe='')})

        @app.post('/api/labs/{lab_id}/design/import')
        async def import_intent(lab_id: str, intent: UploadFile = File(...), revision: str = Form('')):
            try:
                raw = await intent.read(intent_schema.MAX_DOCUMENT + 1)
            finally:
                await intent.close()
            if len(raw) > intent_schema.MAX_DOCUMENT: raise HTTPException(400, 'The design file must be smaller than 512 KiB.')
            try:
                from .inventory import read_data
                data = read_data(raw)
            except ValueError as exc: raise HTTPException(400, 'Upload a design exported by this manager (YAML or JSON): ' + str(exc))
            data.pop('containerlab_node_manager', None)
            if len(revision) > 64: raise HTTPException(400, 'Invalid revision.')
            with service.store.lock:
                lab = service.lab(lab_id)
                current = lab.get('network_design')
                if current and revision != current.get('revision'): raise HTTPException(409, 'The design changed since this page loaded. Reload it before importing.')
                if not current and revision: raise HTTPException(409, 'This lab has no saved design any more. Reload the page.')
                if isinstance(data, dict): data['allocations'] = copy.deepcopy((current or {}).get('allocations') or {})
                problems = service.validation(lab, data)
                if problems: return {'imported': False, 'problems': problems}
                added = intent_schema.retired_added(data, current)
                if added: raise HTTPException(400, retired_added_detail(added))
                stored = intent_schema.normalize(data); stored['updated'] = now()
                previous = lab.get('network_design')
                if any(g.get('status') in DESIGN_BUSY for g in lab.get('network_generations') or []): raise HTTPException(409, 'Wait for the plan being generated to finish.')
                lab['network_design'] = stored; lab['updated'] = now()
                try: service.store.save()
                except OSError:
                    if previous is None: lab.pop('network_design', None)
                    else: lab['network_design'] = previous
                    raise HTTPException(500, 'Could not save the imported design. Try again.')
                service.store.event('design.import', 'Network design imported (revision ' + stored['revision'] + ')', lab_id=lab_id)
                return {'imported': True, 'problems': [], **service.view(lab)}


def problems_detail(problems):
    """The structured 400 of Generate: the old one-line message (kept for clients that read a string's words) and
    every problem as {path, message} for the page's summary."""
    return {'message': 'Fix the design first: ' + '; '.join(p['path'] + ': ' + p['message'] for p in problems[:5]),
            'problems': [{'path': p['path'], 'message': p['message']} for p in problems]}


def retired_added_detail(entries):
    """The structured 400 of Save and Import when the document adds a retired module the saved design does not use."""
    modules = intent_schema.retired_modules(entries)
    return {'message': intent_schema.retired_sentence(modules) + ' ' + intent_schema.retired_phrase(modules) + ', so '
            + ('it' if len(modules) == 1 else 'they') + ' cannot be added to a design. Remove '
            + ('it' if len(modules) == 1 else 'them') + ' and save again; a design that already used '
            + ('it' if len(modules) == 1 else 'them') + ' keeps working as it is.',
            'problems': [{'path': e['path'], 'message': e['message']} for e in entries], 'retired': modules}


def retired_detail(entries):
    """The structured 409 of Generate for a design that still uses a retired module (nothing is queued)."""
    modules = intent_schema.retired_modules(entries)
    return {'message': 'This design uses ' + intent_schema.retired_sentence(modules) + ', which '
            + intent_schema.retired_phrase(modules) + ', so no new plan can be generated from it. Remove '
            + ('it' if len(modules) == 1 else 'them') + ' from the design to generate again. Earlier plans, the saved design file '
            'and its export are kept.',
            'problems': [{'path': e['path'], 'message': e['message']} for e in entries], 'retired': modules}


def _write(path, text):
    """A private (0600) UTF-8 file, whatever the umask."""
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as handle: handle.write(text)


def tempfile_path():
    import tempfile
    fd, path = tempfile.mkstemp(suffix='.zip'); os.close(fd)
    return fd, path
