"""Seeded labs, repositories and saved states for the Git save and load redesign (PROMPT 9.3). SCENARIOS.md lists them.

`seed()` runs once, after the classic fixture labs exist. Everything goes through the application's own routes and code
(`/api/lab-definitions`, profiles, `captured_snapshot`) or into the scripted helper's memory; no VM, no device, no live data.
"""
import copy
import hashlib
import time
import uuid

from app import git_progress as gp
from app.discovery import reconcile
from app.downloads import component
from app.git_progress import captured_snapshot, digest, host_identity
from app.host_git import snapshot_file
from app.inventory import PLATFORMS
from app.layout import map_document
from app.runner import now

import fixture_content as content

INSTRUCTOR = 'ffffffff' + 'instructor'.encode().hex() + 'ffff'     # a lab id no lab of this manager has
HOUR, DAY = 3600, 86400
URL = 'https://github.com/{}.git'

# The labs the scenarios add. name -> (topology yaml builder, platforms that get a login profile)
NEW_LABS = ('restore-square', 'square-fresh', 'edge-lab', 'shared-a', 'shared-b', 'solo-lab')


def nodes_of(lab, only=None):
    """The device rows a capture of `lab` carries (the shape `captured_snapshot` reads), optionally only some short names."""
    rows = [dict(name=n['name'], short_name=n.get('short_name') or n.get('definition_node') or '', platform=n['platform'])
            for n in lab['nodes'] if n.get('platform') in PLATFORMS]
    return [r for r in rows if only is None or r['short_name'] in only]


class Seeder:
    def __init__(self, app, client, store, data_dir, register, profile, devices, fake, control, run_sync):
        self.app, self.client, self.store, self.data_dir = app, client, store, data_dir
        self.register_lab, self.profile, self.devices, self.fake, self.control, self.run_sync = register, profile, devices, fake, control, run_sync
        self.labs = {}
        self.ids = {}

    # --- labs -------------------------------------------------------------------------------------------------------

    def lab(self, name):
        with self.store.lock:
            return next(l for l in self.store.state['labs'] if l['name'] == name)

    def create_labs(self):
        specs = [('restore-square', content.square_yaml('restore-square'), ('arista_ceos', 'cisco_xrv9k', 'juniper_cjunosevolved', 'juniper_vjunosswitch')),
                 ('square-fresh', content.square_yaml('square-fresh'), ('arista_ceos', 'cisco_xrv9k', 'juniper_cjunosevolved', 'juniper_vjunosswitch')),
                 ('edge-lab', content.pair_yaml('edge-lab'), ('arista_ceos',)),
                 ('shared-a', content.pair_yaml('shared-a'), ('arista_ceos',)),
                 ('shared-b', content.pair_yaml('shared-b'), ('arista_ceos',)),
                 ('solo-lab', content.pair_yaml('solo-lab'), ('arista_ceos',))]
        for name, yaml_text, platforms in specs:
            created = self.register_lab(yaml_text.encode(), name + '.clab.yaml')
            for platform in platforms:
                self.profile(created['id'], platform)
            self.ids[name] = created['id']

    def run_labs(self, services):
        """The new labs run on the VM and every device answers: Ready, so a save and a load can be shown end to end."""
        with self.store.lock:
            discovery_rows = self.store.state['discovery']['labs']
            labs = {l['name']: l for l in self.store.state['labs']}
            for name in NEW_LABS:
                discovery_rows[name] = [dict(name=n['name'], address=f'172.20.30.{10 + i + 10 * NEW_LABS.index(name)}', state='running', kind=n.get('kind', ''))
                                        for i, n in enumerate(labs[name]['nodes'])]
            reconcile(self.store.state)
            for name in NEW_LABS:
                labs[name]['vm_project_path'] = f'/etc/containerlab/{name}/{name}.clab.yaml'
                # The automatic login check that ran when every device answered (so the monitor does not start one per lab at launch).
                started = now()
                self.store.state['jobs'].append(dict(
                    id=uuid.uuid4().hex, lab_id=labs[name]['id'], lab_name=name, operation='test', source='automatic', created=started, started=started,
                    finished=started, status='succeeded', message='Every device answered show version.',
                    nodes=[dict(name=n['name'], short_name=n.get('short_name') or n.get('definition_node'), status='succeeded', message='show version answered')
                           for n in labs[name]['nodes'] if n.get('platform')]))
            self.store.save()
        monitor = self.app.state.readiness
        with monitor.lock:
            monitor.tested.update(labs[name]['id'] for name in NEW_LABS)   # their login test ran: none starts at launch
        with services.lock:
            for name in NEW_LABS:
                for n in labs[name]['nodes']:
                    services.checks[(labs[name]['id'], n['name'])] = dict(status='reachable', message='show version answered.', at=now(), source='automatic')

    # --- repositories -------------------------------------------------------------------------------------------------

    def state(self, checkout, folder, lab, tag, message, age, restore=True, only=None, topology=True, **kw):
        """A saved state written directly into the checkout (an instructor's or another lab's commit, no manager save)."""
        topo = lab['definition_yaml'].encode() if topology else None
        notes = map_document(lab).encode() if topology and map_document(lab) else None
        manifest, files = content.build_state(kw.get('lab_id', INSTRUCTOR), kw.get('lab_name', lab['name']), nodes_of(lab, only) + list(kw.get('extra_nodes', [])), tag,
                                              restore=restore, topology=kw.get('topology_bytes', topo), annotations=notes, captured_ago=age)
        changes = {snapshot_file(folder, n): raw for n, raw in files.items()}
        changes[snapshot_file(folder, 'manifest.json')] = content.dumps(manifest)
        return checkout.add_commit(message, changes, pushed=True, age=age)

    def publish(self, lab, checkout, reg, tag, target, message, age, checkpoint='', note='', pushed=True, devices=None):
        """One save of `lab` through the manager's own capture and the helper's own publish: `tag` is what the devices run."""
        for node in nodes_of(lab):
            self.devices.set_tag(node['name'], tag)
        names = [n['name'] for n in nodes_of(lab)]
        op = uuid.uuid4().hex
        # The context a Save carries (git_progress `save`): the devices, the nodes left out and the topology's digest.
        context = dict(node_names=sorted(names), excluded_nodes=sorted(n['name'] for n in lab['nodes'] if n['name'] not in names),
                       topology_digest=hashlib.sha256(lab['definition_yaml'].encode()).hexdigest() if lab.get('definition_yaml') else None)
        backup = self.run_sync(lab['id'], 'backup', 'git-progress', names, op, context)
        snap = captured_snapshot(self.store, backup, context)
        request = dict(mode='publish', binding_id=reg['id'], revision=reg['revision'], operation_id=op, snapshot=snap, target=target,
                       checkpoint=checkpoint, replace_baseline=False, expected_baseline='', allow_removed=True, push=False, message=message,
                       expected_head=checkout.head)
        if target == 'baseline':
            request.update(expected_baseline='', replace_baseline=False)
        result = self.fake(None, request)
        assert result['status'] in ('committed', 'unchanged'), result
        commit = result['commit']
        checkout.commit(commit)['time'] = int(time.time() - age) if result['status'] == 'committed' else checkout.commit(commit)['time']
        if pushed:
            pushed_result = self.fake(None, dict(mode='push', binding_id=reg['id'], revision=reg['revision'], operation_id=op))
            assert pushed_result['pushed'], pushed_result
        job = dict(id=op, lab_id=lab['id'], lab_name=lab['name'], backup_job_id=backup['id'], pushed=pushed, review_before_push=False,
                   binding_digest=digest(lab['git_binding']), node_names=list(lab['git_binding']['node_names']), request={}, capture_context=context,
                   created=now(), finished=now(), status='synced' if pushed else 'committed',
                   message='Saved to Git.' if pushed else 'Saved on VM; not pushed.', commit=commit, target=target, checkpoint=checkpoint, note=note,
                   changed_files=result['changed_files'], snapshot_path=result['snapshot_path'])
        self.age_job(job, age)
        with self.store.lock:
            self.store.state.setdefault('git_jobs', []).append(job)
            self.store.save()
        return job

    @staticmethod
    def age_job(job, age):
        from datetime import datetime, timedelta, timezone
        stamp = (datetime.now(timezone.utc) - timedelta(seconds=age)).isoformat()
        job.update(created=stamp, finished=stamp)

    def prune_backups(self, names):
        """The classic labs keep the backup jobs the first fixture seeded: drop the capture jobs the seeding made for them, and for the
        new labs keep only the newest one (an ordinary finished backup)."""
        with self.store.lock:
            keep = {}
            for job in self.store.state['jobs']:
                if job.get('source') == 'git-progress' and job.get('operation') == 'backup':
                    keep.setdefault(job['lab_id'], job['id'])
            classic = {l['id'] for l in self.store.state['labs'] if l['name'] in names}
            gone = {j['id'] for j in self.store.state['jobs'] if j.get('source') == 'git-progress' and (j['lab_id'] in classic or keep.get(j['lab_id']) != j['id'])}
            self.store.state['jobs'] = [j for j in self.store.state['jobs'] if j['id'] not in gone]
            for job in self.store.state.get('git_jobs', []):
                if job.get('backup_job_id') in gone:
                    job['backup_job_id'] = ''
            self.store.save()

    def bind(self, lab, reg, checkout):
        binding = dict(binding_id=reg['id'], revision=reg['revision'], repository=dict(gp_descriptor(reg)),
                       host_identity=host_identity(self.store.state['host']), node_names=[n['name'] for n in nodes_of(lab)], review_before_push=False)
        with self.store.lock:
            self.store.lab(lab['id'])['git_binding'] = binding
            lab['git_binding'] = binding
            self.store.save()
        return binding

    # --- the scenarios --------------------------------------------------------------------------------------------------

    def course_labs(self, bgp_lab, vlan_lab):
        """The classic fixture repository, as the first fixture had it: BGP_TheoryToPractice saves to labs/BGP/work, vlan-lab to labs/VLAN."""
        co = self.fake.add_checkout('Course-Labs', URL.format('example/Course-Labs'))
        co.add_commit('Initial commit', {'README.md': b'# Course labs\n'}, pushed=True, age=60 * DAY)
        work = self.fake.register(co, 'labs/BGP/work', id='reg-work', label='Course-Labs / labs/BGP/work')
        vlan = self.fake.register(co, 'labs/VLAN', id='reg-vlan', label='Course-Labs / labs/VLAN')
        work['revision'], vlan['revision'] = 'rev-work', 'rev-vlan'
        junos = [n['short_name'] for n in nodes_of(bgp_lab) if n['platform'].startswith('juniper')]
        self.state(co, 'labs/BGP/solution/latest', bgp_lab, 'final', 'Add the solution', 50 * DAY, only=junos)
        self.state(co, 'labs/BGP/start/latest', bgp_lab, 'start', 'Add the starting state', 49 * DAY, restore=False)
        self.bind(bgp_lab, work, co)
        self.bind(vlan_lab, vlan, co)
        self.publish(vlan_lab, co, vlan, 'latest', 'latest', 'Save vlan-lab progress', 4000)
        self.publish(bgp_lab, co, work, 'baseline', 'baseline', 'Set baseline', DAY)
        self.publish(bgp_lab, co, work, 'ospf-up', 'checkpoint', "Checkpoint 'ospf-done'", 7200, checkpoint='ospf-done', note='OSPF adjacencies up on every device')
        self.publish(bgp_lab, co, work, 'latest', 'latest', 'Save BGP_TheoryToPractice progress', 1200)
        return co

    def archtop_lab(self, fresh):
        """The owner's standard install: registered at its top level only, no lab connected, ordinary files, lab states of `fresh`."""
        co = self.fake.add_checkout('Archtop-Lab', URL.format('ArchRuger/Archtop-Lab'))
        co.add_commit('Initial commit', {'README.md': b'# Archtop-Lab\n', 'notes/week1.md': b'Week 1 notes\n', 'Examples/hello.txt': b'hello\n'}, pushed=True, age=30 * DAY)
        reg = self.fake.register(co, '', id='reg-archtop', label='Archtop-Lab')
        self.state(co, 'Course/start/latest', fresh, 'start', 'Add the starting state', 20 * DAY, restore=False, lab_name='square-fresh')
        self.state(co, 'Course/broken/latest', fresh, 'broken', 'Add the broken state', 19 * DAY, lab_name='square-fresh')
        self.state(co, 'Course/final/latest', fresh, 'final', 'Add the final state', 18 * DAY, lab_name='square-fresh')
        return co, reg

    def nested_labs(self, square, edge, shared_a, solo_unused=None):
        """Nested lab folders in one repository, the course states under the lab's folder, and every kind of state beside them."""
        co = self.fake.add_checkout('Nested-Labs', URL.format('ArchRuger/Nested-Labs'))
        co.add_commit('Initial commit', {'README.md': b'# Nested labs\n', 'notes/week1.md': b'Week 1 notes\n'}, pushed=True, age=60 * DAY)
        reg_bgp = self.fake.register(co, 'BGP', id='reg-bgp', label='Nested-Labs / BGP')
        reg_edge = self.fake.register(co, 'BGP/edge', id='reg-bgp-edge', label='Nested-Labs / BGP/edge')
        reg_shared = self.fake.register(co, 'shared', id='reg-shared', label='Nested-Labs / shared')
        self.fake.register(co, 'old-lab-folder', id='reg-unused', label='Nested-Labs / old-lab-folder')   # no lab uses it: invisible
        # The course states, under the lab's folder (layout `latest`): Start (view only), Broken, Final, and a state stored directly in a folder (flat).
        self.state(co, 'BGP/start/latest', square, 'start', 'Add the starting state', 50 * DAY, restore=False, lab_name='restore-square')
        self.state(co, 'BGP/broken/latest', square, 'broken', 'Add the broken state', 49 * DAY, lab_name='restore-square')
        self.state(co, 'BGP/final/latest', square, 'final', 'Add the final state', 48 * DAY, lab_name='restore-square')
        self.state(co, 'Final', square, 'final', 'Add the final state (flat folder)', 47 * DAY, lab_name='restore-square')
        # A subset of the lab's devices (2 of 4), a state saved on a different topology (3 of its 4 devices match), a design export, an unreadable manifest.
        self.state(co, 'BGP/junos-only/latest', square, 'final', 'Add the Junos-only state', 46 * DAY, only=('cjunosevolved', 'vjunos-switch'), lab_name='restore-square')
        self.state(co, 'BGP/other-topology/latest', square, 'other', 'Add a state saved on another topology', 45 * DAY, lab_name='restore-square',
                   only=('ceos', 'cjunosevolved', 'vjunos-switch'), topology_bytes=content.square_yaml('restore-square', other=True).encode(),
                   extra_nodes=[dict(name='clab-restore-square-ceos2', short_name='ceos2', platform='arista_ceos')])
        manifest, files = content.build_design_export(INSTRUCTOR, 'restore-square')
        changes = {snapshot_file('BGP/checkpoints/plan-sept', n): raw for n, raw in files.items()}
        changes['BGP/checkpoints/plan-sept/manifest.json'] = content.dumps(manifest)
        co.add_commit("Export the plan 'plan-sept'", changes, pushed=True, age=40 * DAY)
        co.add_commit('Add notes', {'BGP/notes.md': b'Ordinary files may sit beside saved states.\n', 'BGP/exercises/ex1.txt': b'exercise 1\n'}, pushed=True, age=39 * DAY)
        co.add_commit('Add an old save that cannot be read', {'BGP/legacy/manifest.json': b'{ this is not json', 'BGP/legacy/old.cfg': b'old\n'}, pushed=True, age=38 * DAY)
        # Other labs of the repository: BGP/edge inside BGP, `shared` that lab A saves to and lab B wants too.
        self.bind(edge, reg_edge, co)
        self.bind(shared_a, reg_shared, co)
        self.publish(edge, co, reg_edge, 'latest', 'latest', 'Save edge-lab progress', 20 * HOUR)
        self.publish(shared_a, co, reg_shared, 'latest', 'latest', 'Save shared-a progress', 18 * HOUR)
        # The lab's own saves: a starting point, two checkpoints, three latest saves; the newest is uploaded and the devices run it.
        self.bind(square, reg_bgp, co)
        self.publish(square, co, reg_bgp, 'baseline', 'baseline', 'Set baseline', 3 * DAY)
        self.publish(square, co, reg_bgp, 'ospf-up', 'latest', 'Save restore-square progress', 6 * HOUR, note='OSPF is up')
        self.publish(square, co, reg_bgp, 'ospf-up', 'checkpoint', "Checkpoint 'ospf-up'", 5 * HOUR, checkpoint='ospf-up', note='OSPF is up')
        self.publish(square, co, reg_bgp, 'loopbacks-reachable', 'latest', 'Save restore-square progress', 3 * HOUR, note='Loopbacks answer')
        self.publish(square, co, reg_bgp, 'loopbacks-reachable', 'checkpoint', "Checkpoint 'loopbacks-reachable'", 2 * HOUR, checkpoint='loopbacks-reachable', note='Loopbacks answer')
        self.publish(square, co, reg_bgp, 'running', 'latest', 'Interface descriptions cleaned up', 21 * 60, note='Interface descriptions cleaned up')
        return co

    def solo_lab(self, solo):
        co = self.fake.add_checkout('Solo-Lab', URL.format('ArchRuger/Solo-Lab'))
        co.add_commit('Initial commit', {'README.md': b'# Solo lab\n'}, pushed=True, age=20 * DAY)
        reg = self.fake.register(co, '', id='reg-solo', label='Solo-Lab')
        self.bind(solo, reg, co)
        self.publish(solo, co, reg, 'latest', 'latest', 'Save solo-lab progress', 5 * HOUR)
        return co

    def big_repo(self, square):
        """5000 files in about 300 folders; the saved states sort after the 4000th file, beyond the tree listing cap."""
        co = self.fake.add_checkout('Big-Repo', URL.format('example/Big-Repo'))
        files = {'README.md': b'# Big repository\n'}
        for index in range(4970):
            folder, item = index % 270, index // 270
            files[f'docs/week-{folder // 12:02d}/topic-{folder:03d}/note-{item:02d}.md'] = f'note {folder}-{item}\n'.encode()
        co.add_commit('Initial commit', files, pushed=True, age=90 * DAY)
        self.fake.register(co, '', id='reg-big', label='Big-Repo')
        for name, tag, restore in (('start', 'start', False), ('broken', 'broken', True), ('final', 'final', True)):
            self.state(co, f'zz-states/{name}/latest', square, tag, f'Add the {name} state', 30 * DAY, restore=restore, lab_name='restore-square')
        return co

    def remotes(self):
        self.fake.remote_only(URL.format('ArchRuger/New-Empty'), empty=True)
        self.fake.remote_only(URL.format('ArchRuger/Spare-Lab'), empty=False)


def gp_descriptor(reg):
    return {k: reg[k] for k in ('id', 'label', 'owner', 'path', 'remote', 'push_url', 'branch', 'prefix', 'revision')}


def seed(app, client, store, data_dir, register, profile, devices, fake, control, run_sync, services, extra=True):
    """Create the labs, the repositories and every scenario. Returns the Seeder (labs, ids). `extra=False` seeds only the first
    fixture's repository (Course-Labs)."""
    seeder = Seeder(app, client, store, data_dir, register, profile, devices, fake, control, run_sync)
    devices.steady = set(NEW_LABS)
    if extra:
        seeder.create_labs()
        seeder.run_labs(services)
    with store.lock:
        labs = {l['name']: copy.deepcopy(l) for l in store.state['labs']}
    for name in NEW_LABS if extra else ():
        devices.register_lab(labs[name])
    devices.register_lab(labs['BGP_TheoryToPractice'], 'latest')
    devices.register_lab(labs['vlan-lab'], 'latest')
    seeder.course_labs(seeder.lab('BGP_TheoryToPractice'), seeder.lab('vlan-lab'))
    # BGP_TheoryToPractice: UP-2 matches the solution state, GTW-2 differs by one line, PE2 does not answer (as the first fixture scripted).
    junos = [n for n in labs['BGP_TheoryToPractice']['nodes'] if str(n.get('platform', '')).startswith('juniper')]
    for index, node in enumerate(junos):
        devices.set_tag(node['name'], 'final')
        if index == 1:
            devices.edit(node['name'], add=['set system services ssh'])
        if index >= 2:
            devices.nodes[node['name']].down = True
    if extra:
        seeder.archtop_lab(labs['square-fresh'])
        seeder.nested_labs(seeder.lab('restore-square'), seeder.lab('edge-lab'), seeder.lab('shared-a'))
        seeder.solo_lab(seeder.lab('solo-lab'))
        seeder.big_repo(labs['restore-square'])
        seeder.remotes()
    seeder.prune_backups(('BGP_TheoryToPractice', 'vlan-lab'))
    devices.snapshot_initial()
    return seeder
