# C05 design: mutating lifecycle through the operations helper, one release

Rows R040, R041, R042 (link impairments: set, reset, the per-device table, the map badge), R005 (start and stop one
device), R006 (apply with a dry-run plan), R007 (pending-changes indicator), R008 (node filter), R009 (extra run
flags), R011 (per-device save). Written against `claude/parity-campaign` at `c3f3d94` (release 1.31.1, containerlab
0.79.0 on the VM). Structure as `C03-DESIGN.md`; it builds on C03's `container_of`, `interfaces` and `netem-show`
(helper) and on `device_diagnostics.py` (manager) exactly as committed at `3c982c1`; the C03 UI slice
(`device-diagnostics.js`) is not built yet, so §4.1 is written against `C03-DESIGN.md` §4.1 and shares nothing but
two `typeof`-guarded hooks with it. C02's Stop model (`OperationStopped`, `STOPPABLE`, `LOCK_SENTENCE`, the 20 s
follow-up probe) is taken as it stands; §2.9 says what Stop means for each new mode.

Everything here is a helper change on the existing `clab-manager-operations` request name: the gateway is not
touched, `VERSION` moves with the release, and every VM runs `sudo bash deploy/start-manager.sh --enable-operations`
before any of it exists live. `risk-reviewer` attacks every helper change; §2 gives it, per mode, the argv, the
whitelist, the binding and the lock answer.

## 0. Facts verified live for this design (2026-10-23, this VM, containerlab 0.79.0)

On a disposable two-cEOS lab `c05probe` (`/srv/containerlab-node-manager/projects/c05probe/`, `free -g` before:
26 GB available; deployed 03:46 UTC, destroyed with `--cleanup` 03:54 UTC, folder removed) and on one disposable
plain container (`docker run --rm --entrypoint /bin/sleep n24l/ceos:4.35.0F`, removed). The `parity`, `git-redesign`
and `git-redesign-b` labs were not touched; no device was typed into.

| # | Fact | Consequence in this design |
|---|---|---|
| F1 | `containerlab start` and `stop` take `-n/--node` (repeatable or comma-separated) and `-t`; `stop --node r2` exits 0 in 1.2 s, `start --node r2` in 0.2 s and prints `Restored link node=r2 interface=eth1`; a stopped node keeps its `eth1` parked (`inspect interfaces` lists `eth1, lo` for it) and the neighbour keeps its end | §2.5: no Docker client call is needed for R005; `start-node` / `stop-node` run containerlab like `restart-node` |
| F2 | `stop --node r9`: `Incorrect input: node "r9" is not present in the topology.`, exit 1; stop of an already stopped node and start of a running node exit 0 silently | the helper refuses those two itself (§2.5) so a no-op never reads as a success |
| F3 | `docker stop r2` then `containerlab start --node r2`: **both** ends of the veth are gone afterwards (`r1` lists `eth0` only); the dry run then reports `restarted-nodes: [r1, r2]`, reason `added link` | the Start device review carries the neighbour note; the pending-changes check also catches lost links (§3.3) |
| F4 | `tools netem set -n <container> -i <if>` takes `--delay`, `--jitter`, `--loss`, `--rate` (kbit), `--corruption`; it **replaces** the whole qdisc (a second `set --delay 30ms` cleared the earlier jitter, loss, rate and corruption); explicit zeros (`--delay 0s --jitter 0s --loss 0 --rate 0 --corruption 0`) are accepted and leave a netem qdisc that shows as a row with empty values | the UI sends a row's full five values; the helper always passes all five flags; an all-zero set is refused in favour of Reset (§2.2) |
| F5 | `netem show -n <container> -f json` answers `{"<container>": null}` without impairments, else `{"<container>": [{"interface": "eth1", "delay": "20ms", "jitter": "5ms", "packet_loss": 1.5, "rate": 1000, "corruption": 0.5}]}`; empty delay or jitter is `""`; a lab-wide form does not exist (`--name` or `-t` without `-n`: `Invalid container name or ID: value is empty.`) | C03's `impairment_rows()` (which maps `packet_loss` to `loss`) is confirmed; the lab-wide answer is one helper call that loops (§2.4) |
| F6 | `netem set` on `eth0` is **accepted** by containerlab; `--jitter` without `--delay`: `Jitter cannot be set without setting delay.`; unknown interface or a stopped container: `Link not found.`; `--loss 150`: `Packet loss must be in the range between 0 and 100.`; all exit 1 | the helper and the manager refuse `eth0`, `lo`, internal and host-network interfaces and a stopped device before containerlab is asked (§2.2, §3.4) |
| F7 | `netem reset -n -i` prints `Reset impairments on node "…", interface "…"`, exit 0; on an interface without impairments it fails with `Netlink receive: invalid argument.`, exit 1 | `netem-reset` runs `show` first and does nothing when there is nothing to reset (§2.3) |
| F8 | `containerlab apply` is an alias of `deploy` on 0.79.0 (identical help; the command list has no `apply`); `deploy --dry-run --format json -t` runs in 50 ms, prints JSON on stdout and its log on stderr, writes nothing into the lab folder (mtimes unchanged), and compares the file with the **live** lab: keys `dry-run`, `deployed-lab`, `added-nodes`, `deleted-nodes`, `recreated-nodes`, `started-nodes`, `added-links` (`"r1:eth1 -- r2:eth1"`), `deleted-endpoints`, `restarted-nodes`, `node-change-reasons` (`{"r2": "config drift: Env", "r1": "added link"}`); on an undeployed lab `deployed-lab: true`, `lab-name`, and every list is `null`; a broken file exits 1 with `Failed to read topology file: …` on stderr and no JSON; `--dry-run` with `--reconfigure` is refused (`reconfigure always destroys and redeploys the full lab`) | §2.6 (the plan inside the apply review, bound by the digest) and §2.7 (`apply-plan`, outside the lock) |
| F9 | `deploy --node-filter r2` on an already deployed lab is **refused**: `Node filter is not supported when reconciling deployed lab "c05probe": running nodes excluded by the filter would be deleted; remove the filter or use --reconfigure.`, exit 1; on an undeployed lab `deploy --node-filter r1 --max-workers 1 --skip-post-deploy` creates the lab folder and `r1` only (exit 0), and the dry run afterwards plans `added-nodes: [r2]` | a deploy with chosen devices is only for a lab that is not deployed; the way to add the rest is Apply topology changes (§2.8, §3.2) |
| F10 | `destroy --node-filter r2` removes that container in 0.2 s, keeps `r1`, the lab folder and the other node folders (exit 0); `destroy --node-filter r2 --cleanup`: `Cleanup cannot be used with node-filter.`, exit 1; `destroy --node-filter r9` and `save --node-filter r9`: `Incorrect input: node "r9" is not present in the topology.`, exit 1; `destroy --node-filter r1 --graceful --keep-mgmt-net` exits 0 but the graceful stop of a cEOS took **two minutes**; `save --node-filter r1` exits 0 and writes `clab-c05probe/r1/flash/startup-config` | §2.8; the Graceful option names its cost in the review (§4.5) |
| F11 | `--max-workers 0` and `99` are accepted; `-1`, `abc`, `1.5`: `Try --help for usage.`, exit 1; `deploy --graceful`: `Try --help for usage.` (not a deploy flag); `redeploy` has `--max-workers`, `--skip-post-deploy`, `--skip-labdir-acl`, `--graceful`, `--keep-mgmt-net`, `--cleanup` and **no** `--node-filter`; `destroy` has `--max-workers`, `--node-filter`, `--graceful`, `--keep-mgmt-net`, `--cleanup`; `save` has `--node-filter` | the per-action option table (§2.8) and the helper's `1 ≤ max_workers ≤ 64` |
| F12 (added after the design review, 05:29 UTC, topology folder `c05dry`, never deployed, removed) | `deploy --dry-run --format json` on an **undeployed** topology whose second node names a missing image (`ghcr.io/srl-labs/network-multitool:c05-does-not-exist`): exit 0 in 42 ms, F8's undeployed shape (`deployed-lab: true`, every list `null`), and **nothing created or pulled**: no `clab-<lab>` folder, no container, the Docker image count unchanged (27 before and after), no `/etc/hosts` or `ssh_config.d` entry; stderr holds two INFO lines only | §2.7: the pending check is safe on an undeployed or partly deployed lab and on a lab whose images are absent; every dry-run argv carries `--dry-run` (pinned by a test) |
| F13 (same session) | on a failed dry run containerlab's stderr is an INFO line first, then a boxed `ERROR` whose **next** line is the sentence (`Failed to read topology file: yaml: line 3: …`) and whose **last** line is the generic `Consult with release notes to see if any fields were changed/removed.`; stdout is empty | the error the review shows is the line after `ERROR`, else the first line containing `Failed` or `ERRO`, else the last non-empty line (§2.6) |

## 1. Decisions in one place

1. **Start device and Stop device run containerlab, not Docker** (F1): `start-node` and `stop-node` are planned and
   run exactly like `restart-node` (same two selector keys, same binding to one deployed container with its id and
   state in the digest, under the host lock, stoppable). No `docker stop/start` enters the helper: the question in the
   assignment is moot on 0.79.0, and a Docker client lifecycle call would also lose containerlab's link parking (F3).
   A `--node` capability probe on `start` and `stop` decides availability, as for `restart-node`.
2. **Impairments are two mutating modes under the host flock, non-blocking, with a request digest** (`netem-set`,
   `netem-reset`) plus a lab-wide read outside the lock (`netem-show-all`). They change a qdisc on one interface of
   one running container in 60 ms and touch no lab file and no container lifecycle, so they need no preview/run pair
   (no `inspect --all` before and after): the binding to the live container is `container_of` at execution plus the
   container id the drawer showed (`expected_id`, §2.2). They do take the one host flock, `LOCK_EX | LOCK_NB`, through
   the same shared helper `main()` uses for `preview` and `run`: held → `ValueError(LOCK_SENTENCE)`, no wait, no retry
   loop; a netem change therefore never runs while a lifecycle command recreates the very container it targets,
   whoever started that command, and "one host lock" stays literally true. The other direction is closed on the
   manager: every in-flight impairment call is registered in a set that `LabOperations.guard()` checks, so a preview or
   confirm that arrives during one answers 409 `Wait for the current lab operation to finish.` instead of reaching the
   helper and failing a job (§3.4). The drawer words the helper's lock sentence as `Another lab operation is running on
   the VM (it may belong to another lab); try again when it has finished.` The digest is the helper's own `digest()`
   over `{mode, name, options, expected_id}`, computed by the manager when the student confirms the drawer sentence,
   recomputed by the helper over what it received (mismatch → `'Review the impairment again.'`), and `expected_id`
   is checked against `container_of()['id']` (§2.2). The review is the sentence in the drawer (§4.1); the manager's
   route is the only writer and logs controlled metadata. §8 (1) asks `risk-reviewer` to attack this form.
3. **The management interface is refused by name and by role, and host-network nodes entirely.** `eth0` and `lo` are
   refused in the helper (fixed names: containerlab itself names the management interface `eth0` for every kind) and
   the manager refuses anything whose `interface_role(kind, name)` is not `data` (cEOS `cpu`, `fabric*`,
   cJunosEvolved `eth1`–`eth3`; `interface_role`'s docstring is rewritten, since it is now a guard as well as a
   display rule); the helper also refuses a container whose `HostConfig.NetworkMode` is `host` or `container:*`
   (read in the same `docker inspect`; a missing or empty value refuses) and a task whose network namespace cannot be
   proven separate from the VM's (the check is tri-state: shared, separate, unknown; shared and unknown refuse).
   Containerlab accepts `eth0` (F6), so neither layer may rely on it.
4. **A netem set sends the whole row** (F4). The UI's Apply posts all five values of the row; the helper always passes
   all five flags; an all-zero row is refused with "use Reset"; jitter without delay is refused before containerlab.
5. **The dry run is read-only and runs twice in different places.** Inside `plan()` for `apply` it is part of the
   reviewed plan and enters the digest, so a run whose live plan differs from the reviewed one is refused with the
   existing "Preview the operation again." (that is the binding R006 asks for). As the mode `apply-plan` outside the
   lock it is the pending-changes check (R007): asked once when a lab opens, after each lab operation of that lab ends
   and on **Review changes…**; cached 60 s on the manager; never polled; never applied by itself.
6. **The node filter is a validated `nodes` option** on `destroy`, `save` and, only for a lab that is not deployed, on
   `deploy` (F9). The manager validates every name against the topology it already parses for the review; the helper
   validates shape and, for `destroy` and `save`, membership in the deployed rows (and containerlab refuses an unknown
   name before touching anything, F2/F10). `cleanup` with `nodes` is refused by the helper with the reason (F10).
   `redeploy` and `apply` take no filter (F11; apply is lab reconciliation by definition).
7. **A partial destroy never records a deployment**: `record_deployment()` keeps its only condition (`action in
   DEPLOY_ACTIONS` and `succeeded`), no new caller is added, and a test pins `last_deployed` unchanged after a filtered
   destroy and a filtered save. A filtered **deploy** is recorded: it is the deployment that created the lab (it is
   only allowed on a lab that is not deployed), and the plain deploy that later adds the rest records again.
8. **Three extra flags, each probed from the installed command's help like `cleanup` and `graceful`**: `max_workers`
   (int 1..64), `skip_post_deploy`, `keep_mgmt_net`, allowed per action by the table in §2.8. `skip_labdir_acl` is left
   out on purpose: the lab-folder ACLs are what let `clab_admins` (the owner-scoped Git account and the engineer
   account) read the lab folder; skipping them breaks saves and the health check and has no student use.
   `export_template` (a path flag) stays out as the matrix says.
9. **Every new per-device action is stoppable and stale-checked like `restart-node`**: `STOPPABLE`, `STOP_AFTERMATH`,
   `STOP_LABELS`, `LIFECYCLE_JOBS` and their `status.js` twins gain `start-node` and `stop-node`; the stale-review rule
   of `preview`/`confirm` (`stamp`, `expected_container`) applies to all three node actions. The follow-up probe after
   a Stop is unchanged (a preview of the same request under the flock, `LOCK_SENTENCE` as "not yet").
10. **The drawer gets one new section, "Impairments", in a file of its own** (`device-impairments.js`), a sibling of
    C03's two sections, not an extension of its Interfaces table: C03's file is being built by another owner, its
    Interfaces section is a read-only poll with its own plan, and an editable table with inline confirmations has
    different state. The two meet through two `typeof` hooks (§4.1).
11. **The map shows impairments as a class on the wire group and a caption**, never a stroke rule that reaches
    `path.capture-hit`; right-click on a link keeps opening Capture (zero regression); **Clear impairments** lives in
    the caption and in the drawer.

## 2. Helper modes (`clab-backup-ui/app/host_operations.py`)

New constants: `NODE_ACTIONS = ('restart-node', 'start-node', 'stop-node')` (containerlab command = the action without
`-node`); `NETEM_TIMEOUT = 15`; `IMPAIRMENT_INTERFACE = re.compile(r'[A-Za-z0-9_.-]{1,15}', re.ASCII)` (Linux
`IFNAMSIZ`); `IMPAIRMENT_TIME = re.compile(r'(0|[1-9][0-9]{0,5})(ms|s)', re.ASCII)`; `DELAY_LIMIT_MS = 60000`;
`RATE_LIMIT_KBIT = 10_000_000`; `MANAGEMENT_INTERFACES = ('eth0', 'lo')`; `NODE_FILTER_LIMIT = 64`;
`MAX_WORKERS_LIMIT = 64`; `APPLY_PLAN_TIMEOUT = 60`; `SHOW_ALL_DEADLINE = 60`; `PLAN_LIST_LIMIT = 256`. `main()` gains
one shared `locked(fn)` helper around the existing flock (`/run/clab-manager-operations.lock`, `LOCK_EX | LOCK_NB`,
held → `ValueError(LOCK_SENTENCE)`, where `LOCK_SENTENCE = 'Another host lab operation is running.'` becomes a module
constant that `lab_operations.LOCK_SENTENCE` is pinned equal to) and dispatches `preview`, `run`, `netem-set` and
`netem-reset` through it; every other mode (`netem-show-all`, `apply-plan`, C03's reads, `capabilities`, `images`,
`image-check`, `popular`, `browse`, `read`) is called without a lock. `test_main_dispatches…` names every mode and which
of the two paths it takes. A refused request runs nothing.

### 2.1 Shared pieces

- **`container_of` gains one field**: `INSPECT_FORMAT` ends with `{{.HostConfig.NetworkMode}}` (eleven fields; the
  length check becomes `!= 11`, `facts['network_mode']` is the bounded string, C03's `inspect_line` fixture gains the
  field; the read-only modes ignore it).
- **`container_matches(container, lab, node)`** (new, pure): `container == node or container == lab + '-' + node or
  container.endswith('-' + lab + '-' + node)`, the one rule `node_selector()` applies today; `node_selector()` calls it
  and so does the `nodes` membership check of §2.8 (one definition, one test with an empty-prefix lab).
- **`impairment_request(req, keys)`**: the request is `{'mode', 'name', 'options', 'expected_id', 'digest'}`;
  `digest(req minus 'digest')` must equal `req['digest']` (else `ValueError('Review the impairment again.')`), so
  `mode`, `name`, every option and `expected_id` are bound; `expected_id` must `CONTAINER_ID.fullmatch`.
- **`impairment_target(name, options, keys, expected_id)`**: `lab = identity(name)`; option keys exactly `keys`;
  `facts = self.container_of(options, lab)` (the C03 binding: `docker inspect --type container`, labels `containerlab`
  == lab and `clab-node-name` == node, 64-hex Id, `clab-topo-file` under a trusted root); `facts['present']` must be
  true and `facts['status'] == 'running'` (else `ValueError('Device <container> is not running; impairments exist only
  on a running device.')`); `facts['id'] == expected_id` (else `ValueError("The device's container changed since you
  opened this section; reopen it and apply again.")`: a container recreated after the drawer was read never receives
  the change); `facts['network_mode']` must be a non-empty string that is neither `host` nor starts with `container:`
  (`host` → `ValueError("This device shares the VM's own network; its interfaces are the VM's and cannot be
  impaired.")`; `container:*` → `ValueError("This device shares another container's network; its interfaces are not
  its own and cannot be impaired.")`; empty or missing → `ValueError("The manager could not read this device's network
  mode; try again in a moment.")`, fail closed); `interface = options['interface']` must `IMPAIRMENT_INTERFACE.fullmatch`
  and not be in `MANAGEMENT_INTERFACES` (`'The management interface eth0 cannot be impaired: the manager reaches the
  device through it.'` / `'lo cannot be impaired.'`); then the namespace check, tri-state: `self.network_separate(facts)`
  returns `True` (a `/proc/<pid>` directory fd whose cgroup names the Id and whose `ns/net` differs from pid 1's),
  `False` (same `ns/net` as pid 1) or `None` (no fd, cgroup mismatch, any `OSError` in `in_host_network`, which now
  returns `None` instead of `False` on error); `False` → the `host` sentence above; `None` → `ValueError("The manager
  could not bind this device's network namespace; try again in a moment.")`. Both the label check and the namespace
  check must pass. Returns `(lab, facts, interface)`.
- **`netem_rows(container)`**: `[self.clab, 'tools', 'netem', 'show', '-n', container, '-f', 'json']`, `self.run`,
  `NETEM_TIMEOUT`, parsed exactly as `netem_show()` does today (`impairment_rows`); non-zero or non-JSON →
  `ValueError('Containerlab on the VM did not show the impairments of this device.')`.

### 2.2 `netem-set` (host flock non-blocking, request digest, `expected_id`)

- Request `{'mode': 'netem-set', 'name': <lab>, 'options': {'node', 'container', 'interface', 'delay', 'jitter',
  'loss', 'rate', 'corruption'}, 'expected_id': <64 hex>, 'digest': <sha256>}`; the eight option keys exactly, all
  present; `impairment_request` then `impairment_target` (§2.1) before any value is looked at.
- Values, one table shared with the manager and the UI (`VALUE_RULES`, §4.1; one JSON case table drives the Python and
  the JS tests): `delay`, `jitter` are strings matching `IMPAIRMENT_TIME` (no leading zero; `'0ms'` for none; `''` is
  refused: the UI normalises), **each** ≤ `DELAY_LIMIT_MS` when converted (jitter too; the shared sentence says so);
  `loss`, `corruption` are `int` or `float` (never `bool`, `type(v) in (int, float)`) in `0..100`, with `-0.0`
  normalised to `0` before anything is rendered; `rate` is `int` in `0..RATE_LIMIT_KBIT`. Jitter above zero with
  delay zero → `ValueError('Set a delay before adding jitter.')`. All five at their zero → `ValueError('Set at least one
  impairment, or use Reset to remove them.')` (F4: an all-zero set leaves a phantom row).
- argv, always all five flags, in this order:
  `[self.clab, 'tools', 'netem', 'set', '-n', container, '-i', interface, '--delay', delay, '--jitter', jitter,
  '--loss', loss_text, '--rate', str(rate), '--corruption', corruption_text]` where `loss_text`/`corruption_text` are
  `repr`-free decimal renderings (`'%g' % value` after the `-0.0` normalisation, at most 6 significant digits; `1.5` →
  `1.5`, `0` → `0`). The variable
  argv elements are the bound container name, the validated interface and five validated numbers; none at argv[0..4].
  `self.probe(argv, NETEM_TIMEOUT)` (stderr kept so containerlab's own refusal, F6, becomes the sentence: a non-zero
  exit raises `ValueError('Containerlab on the VM refused the impairment: ' + last stderr line[:200])`, with
  `Link not found.` mapped to `'<interface> is not an interface of this device right now.'`).
- Result `{'facts', 'impairments': netem_rows(container)}` (the device's rows after the change).

### 2.3 `netem-reset` (host flock non-blocking, request digest, `expected_id`)

- Request `{'mode': 'netem-reset', 'name', 'options': {'node', 'container', 'interface'}, 'expected_id', 'digest'}`
  (the digest covers the three option keys here), the same `impairment_request` and `impairment_target` checks (a
  management or internal name is refused here too: the manager never set it, and resetting `eth0` would also be
  harmless but is not the manager's business).
- `rows = netem_rows(container)`; when no row names `interface`, return `{'facts', 'changed': False, 'impairments':
  rows}` without running anything (F7); else argv `[self.clab, 'tools', 'netem', 'reset', '-n', container, '-i',
  interface]`, `self.probe`, non-zero → `ValueError('Containerlab on the VM could not reset the impairment on
  <interface>.')`; result `{'facts', 'changed': True, 'impairments': netem_rows(container)}`.

### 2.4 `netem-show-all` (outside the lock, read-only)

- Request `{'mode': 'netem-show-all', 'name', 'options': {'nodes': [{'node', 'container'}, …]}}`, 1..64 pairs, each
  through `node_selector(pair, lab)` (shape) and `container_of(pair, lab)` (binding).
- For each pair: `{'node', 'container', 'present', 'impairments': netem_rows(container) if present and running else []}`.
  One SSH session, N `docker inspect` + N `netem show` (about 150 ms each live). A pair whose binding fails (another
  lab's container, a label mismatch) fails the whole call with C03's sentence: the request named something it must not.
- **Total deadline** `SHOW_ALL_DEADLINE = 60` s inside the helper (`time.monotonic()` checked before each pair): pairs
  not reached are returned as `{'node', 'container', 'unread': True}` and the result carries `'complete': False`; the
  manager says so (§3.4). The worst case of 64 × (12 s + 15 s) therefore cannot happen inside one call.
- Result `{'devices': [...], 'complete': bool}`. C03's per-device `netem-show` is unchanged.

### 2.5 `start-node` and `stop-node` (under the lock, preview/run)

The `restart-node` branch of `plan()` becomes the `NODE_ACTIONS` branch, `command = action[:-5]`:

- `allowed = {'node', 'container'}` for all three (the whitelist stays per action; no other action takes a selector).
- `help_text = self.help(command)`; empty → `'This Containerlab version does not support ' + command + '.'`; without
  `--node` → `'The installed Containerlab cannot ' + command + ' one device: its ' + command + ' command has no --node
  option. Upgrade containerlab on the VM.'`
- `targets = [r for r in rows if r['name'] == container]`, exactly one, else the existing `'Device … is not deployed in
  lab …'` sentence. New state checks (F2): `stop-node` with `state != 'running'` → `ValueError('Device <container> is
  <state>; there is nothing to stop.')`; `start-node` with `state == 'running'` → `ValueError('Device <container> is
  already running.')`. `restart-node` keeps its start/restore warning.
- argv `[self.clab, command, '-t', str(path)] + (['--name', name] if '--name' in help_text) + ['--node', node]`, the same
  three sanity asserts as today (`argv.count('--node') == 1`, `argv[-1] == node`, no comma).
- `affected` is the one target with its `id` and `state`; `extra = {'node', 'container'}`; the digest therefore binds
  the container id and its state, so a start, stop, restart or redeploy between review and run is refused at run time
  with the existing sentence.
- `execute()` is unchanged: `stream(argv)` under the flock, output streamed, exit code returned.

### 2.6 The plan inside the apply review (under the lock, read-only step)

In the `LIFECYCLE` branch, after the argv is built and only when `action == 'apply'`:

- If `'--dry-run' not in self.help('deploy')`: `extra['plan'] = None; extra['plan_failed'] = 'unsupported'` (the review
  says the installed containerlab cannot plan; the apply itself still runs).
- Else `code, out, err = self.probe([self.clab, 'deploy', '--dry-run', '--format', 'json', '-t', str(path), '--name',
  name], APPLY_PLAN_TIMEOUT)` (`--name` only when the deploy help has it, as the run does). `apply` is deploy's alias
  (F8); the dry run is spelled `deploy` so the argv matches the help text that was probed.
- `code == 0` and JSON → `extra['plan'] = apply_plan(value)`; else `extra['plan'] = None; extra['plan_failed'] =
  'error'`, and `error_line(stderr)` (≤ 300 chars, escapes stripped by the manager) goes into `warnings` as
  `'containerlab could not plan this change: …'`. `error_line` (pure, tested on F13's capture) is the line after a line
  that is exactly `ERROR` once stripped, else the first line containing `Failed` or `ERRO`, else the last non-empty
  line; never the first line, which is containerlab's INFO banner (F13). `warnings` are outside the digest; `plan` and
  `plan_failed` are inside. The digest stores the plan's lists **sorted** (`apply_plan` sorts every list and the
  reasons' keys), so containerlab's output order cannot alone change the digest.
- `apply_plan(value)` (pure, tested): `{'deploys_lab': value.get('deployed-lab') is True, 'added': [...],
  'removed': [...], 'recreated': [...], 'started': [...], 'restarted': [...], 'links_added': [...],
  'endpoints_removed': [...], 'reasons': {name: text}}` from the kebab-case keys of F8; `null` lists are `[]`; names and
  link texts are strings ≤ 120 chars, lists cut at `PLAN_LIST_LIMIT`, reasons ≤ 200 chars; unknown keys dropped.
  `plan_changes(plan)` = `deploys_lab or any list non-empty`.
- Cost: 50 ms live, 60 s bound; the preview budget (`remote` 180 s) holds `deployed()` 25 s + help calls + 60 s.
- Why the plan is in the digest: the dry run reads the live lab (F3, F8). A device that stops, a link that disappears or
  a file edit between review and confirm changes the plan, the run's `plan()` recomputes it, the digest differs and the
  run is refused with `'The topology or deployment changed. Preview the operation again.'`. That is R006's "confirm
  cannot apply a different change" without a new mechanism.

### 2.7 `apply-plan` (outside the lock, read-only)

- Request `{'mode': 'apply-plan', 'name': <lab>, 'path': <topology>}`; `identity(name)`; `path = self.path(req['path'])`
  with the `.yaml`/`.yml` suffix rule; the same `--dry-run` probe and argv as §2.6; no `deployed()` call (the dry run
  itself asks Docker). Result `{'plan': apply_plan(...) | None, 'failed': '' | 'unsupported' | 'error', 'error':
  error_line(stderr) ≤ 300}`.
- It never takes the flock (the critic's point on R007: a background check under the flock would make a student's
  Confirm fail). It writes nothing and pulls nothing, on a deployed lab (F8), on an undeployed lab and on a topology
  whose image is absent (F12). One test asserts that `'--dry-run'` is in every argv `apply-plan` and §2.6 build (the
  argv builder is one function, `dry_run_argv(path, name)`). Its 60 s bound and the manager's three diagnostics slots
  bound its cost.

### 2.8 The `nodes` option and the extra flags (under the lock, inside `plan()`)

New option keys, each checked only where the table allows it; a key outside the table is `'Unsupported operation
options.'` as today (the old union of keys is kept unchanged for the old keys, so nothing that works today changes):

| Action | `nodes` | `max_workers` | `skip_post_deploy` | `keep_mgmt_net` | `graceful` (existing) | `cleanup` (existing) |
|---|---|---|---|---|---|---|
| deploy | yes, only when `rows` is empty | yes | yes | no | no | yes |
| redeploy | no | yes | yes | yes | yes | yes |
| destroy | yes | yes | no | yes | yes | yes, never with `nodes` |
| save | yes | no | no | no | no | no |
| apply, start, stop, restart, inspect | no | no | no | no | no | no |

- `nodes`: a list of 1..`NODE_FILTER_LIMIT` strings, each `re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,119}')` (no
  comma can pass), unique; else `ValueError('Choose devices by their literal topology node names.')`. For `destroy`
  and `save` every name must map to exactly one deployed row through `container_matches(row['name'], lab, node)`
  (§2.1, the same function `node_selector` uses, so an empty-prefix lab whose containers are the bare node names is
  matched too), else `ValueError('Device <node> is not deployed in lab <name>. Refresh the lab list
  and review again.')`; `affected` is reduced to those rows and `extra['kept'] = [the other rows' names]`. For `deploy`
  with `rows` non-empty: `ValueError('This lab is already deployed, so a deploy limited to chosen devices is not
  possible (containerlab would remove the devices left out). Use Apply topology changes to add the missing devices.')`
  (F9); with `rows` empty the helper cannot check membership (no YAML parser in the stdlib helper) and relies on the
  manager's check (§3.2) and containerlab's own refusal (F10, exit 1 before anything is created). argv gains
  `['--node-filter', ','.join(nodes)]` (one element) when `--node-filter` is in the help text, else `ValueError('Installed
  command lacks --node-filter.')`. `cleanup` together with `nodes` → `ValueError('Clean up cannot be combined with chosen
  devices: containerlab would delete the whole lab folder, which the devices left running still use.')` before argv.
- `max_workers`: `type(v) is int` and `1 <= v <= MAX_WORKERS_LIMIT` (F11: 0 is accepted by containerlab but means
  "unlimited", which the student has by leaving the field empty) else `ValueError('Max workers must be a whole number
  from 1 to 64.')`; argv `['--max-workers', str(v)]` when probed.
- `skip_post_deploy`, `keep_mgmt_net`: `type is bool` like `cleanup`/`graceful`; each flag is appended only when its
  `--flag` is in the command's help, else the existing `'Installed command lacks --flag.'`.
- Fixed argv order after `-t <path> --name <name>`: `--node-filter X`, `--max-workers N`, `--skip-post-deploy`,
  `--cleanup`, `--graceful`, `--keep-mgmt-net`, then `--format json` for inspect. The review shows it verbatim.
- The redeploy fallback (`steps`, no `redeploy` command): the destroy step takes `cleanup`, `graceful`, `keep_mgmt_net`,
  `max_workers`; the deploy step takes `max_workers`, `skip_post_deploy`; each flag checked against that step's help.
- Digest: `options` is already part of `base`, so every new option is bound; `kept` is in `extra` and bound too (a
  device that appears or disappears between review and run changes it).

### 2.9 `capabilities`

Per lifecycle action the probe adds `'node_filter'`, `'max_workers'`, `'skip_post_deploy'`, `'keep_mgmt_net'` and
`'dry_run'` (each `'--x' in help_text`); `actions['start-node']` and `actions['stop-node']` are `{'available': bool(help)
and '--node' in help}` from the `start` and `stop` help texts; `actions['impairments'] = {'available':
bool(self.help('tools', 'netem', 'set'))}`; a marker `'lifecycle_options': True` tells the page this helper from an older
one without a failed call (as `'diagnostics'` does). Three more `--help` runs (15 s bound each); the manager caches
capabilities 60 s.

### 2.10 Lock and Stop answers per mode

| Mode | Host flock | Digest | C02 Stop |
|---|---|---|---|
| `netem-set`, `netem-reset` | yes, non-blocking, through the shared `locked()` of `main()` (held → `LOCK_SENTENCE`, no wait) | yes: `digest({mode, name, options, expected_id})` recomputed by the helper, `expected_id` checked against `container_of()['id']` at execution | not a job; a 15 s bounded call; the manager's per-lab lock, its `guard()` and the in-flight set it registers in serialise it against jobs in both directions |
| `netem-show-all` | no (read-only) | none | not a job; 60 s helper deadline; unguarded like C03's reads |
| `apply-plan` | no | none (read-only) | not a job; 60 s bound |
| `start-node`, `stop-node` | yes, as preview/run | yes: container id and state, like `restart-node` | in `STOPPABLE`; a stopped `stop-node` may leave the device stopped or running: aftermath "Stop device again (or Start device if it should run)"; a stopped `start-node`: "Start device again"; the follow-up probe is the same preview under the flock and `LOCK_SENTENCE` still means "not yet" |
| lifecycle with `nodes` / flags | yes | yes: `options` and `kept` are in `base` | unchanged per action; a stopped filtered destroy reads "The lab may be only partly removed: run Destroy lab again" (the aftermath table is per action, not per option) |
| the plan inside `apply` | yes (part of `plan()`) | yes (`plan`, `plan_failed`) | unchanged |

## 3. Manager side

### 3.1 `lab_operations.py`: node actions

- `NODE_ACTIONS = ('restart-node', 'start-node', 'stop-node')` imported from the helper module (one definition).
  `LIFECYCLE_JOBS`, `STOPPABLE`, `STOP_AFTERMATH` (`'start-node': ('started', 'Start device again')`, `'stop-node':
  ('stopped', 'Stop device again (or Start device if it should run)')`), `STOP_LABELS` (`'Start device'`, `'Stop
  device'`) gain both; `status.js` `STATUS_STOPPABLE`, `STATUS_STOP_AFTERMATH`, `STATUS_OPERATION_LABELS`
  (`'Starting device'`, `'Stopping device'`) and `operationLabel()` (`'Starting ' + node_label` / `'Stopping …'`) mirror
  them; the existing equality tests cover the new entries.
- `preview`: `if data.node and data.action not in NODE_ACTIONS` → 400 `'Only Restart device, Start device and Stop device
  name a single device.'` (the old sentence rewritten, its test updated). The whole `restart-node` resolution block
  (`target`, `expected_container`, `parse_definition` match, `options = {'node', 'container'}`, the 409 "cannot match"
  sentence, `review_stamp`) applies to all three; the sentences say the action's label (`'Choose the device to
  start.'`, `'Start device takes no options.'`, `'… review the start again.'`). Notes: `RESTART_KNOWN_LIMITS` are added
  to `start-node` as they are, and to `stop-node` reworded once per kind (`STOP_KNOWN_LIMITS`: vJunos-switch "…cannot be
  started a second time, so after this stop only Redeploy lab brings it back"; XRv9k "…the next start boots the device
  from a fresh disk: back up first"). `restart_links(lab, short)` returns `(expected, down, absent)`: `absent` are the
  neighbours whose `runtime_state` is `absent` (destroyed, filtered destroy included), `down` the stopped or exited
  ones as today. The note is built per action by `neighbour_note(action, shown, expected, down, absent)` (pure,
  tested): for `down` the existing sentence with the verb of the action (`comes back with this restart` / `… with this
  start`, `Restart device… on it` / `Start device on it`); for `absent` a separate sentence: `'<n> was removed from the
  VM (destroyed, not stopped): its link to <dev> is gone until Apply topology changes recreates <n>; <dev> may wait for
  that interface before it boots. Apply topology changes first (Lab actions ▾), then start this device.'`; `stop-node`
  gets `'Its links are parked, not removed: Start device or Restart device brings them back; a neighbour that restarts
  meanwhile keeps waiting for this link.'`. A test runs each with an absent neighbour and with a stopped one.
- Job titles and toasts name the device, never the lab-wide verb: `STOP_LABELS` and `opLabels` give the generic label
  (`'Start device'`, `'Stop device'`) only where no job is at hand; wherever a job record is (the history row, the
  job banner, the confirm toast, the lab header), the label comes from `operationLabel(action, job)` /
  `opJobLabel(job)` = `'Stop ' + node_label` → `✔ ceos stopped` / `✖ Stop ceos failed` / `Stopping ceos…`, so `Stop
  device` and `Stop devices` can never be confused one letter apart. The same rule applies to a filtered job through
  its public `nodes` field (§3.2): `Destroy ceos in <lab>`, `✔ ceos destroyed`, `Save ceos, vsw`.
- `confirm`: the `preview.get('node')` block (device unchanged, no lifecycle job since the stamp) applies to all three.
- `execute`: `restart_key` becomes `node_key = (lab_id, node)` for `restart-node` and `start-node` (readiness forgotten
  before and after, `Restored link` counted, `settled_after_restart` run; its sentence says "started" for `start-node`:
  `'containerlab started the device, but its container is …'`); `stop-node` forgets readiness once (the device will not
  answer) and has no settle check. `lab_keys` is unchanged (lab-wide actions only). `record_deployment` is untouched
  (§1.7).
- `restarting_nodes(state, lab_id)` returns `{name: action}` for the three node actions; `main.py` `public_lab` writes
  `nos_login = {'status': 'restarting' | 'starting' | 'stopping', 'message': …}` accordingly; `status.js` `deviceState`
  adds the two keys (`'Starting'` / `'Stopping'` labels, `pill: 'busy'`, `cli: false`).

### 3.2 `lab_operations.py`: options

In `preview`, before the helper is asked and only for `deploy`, `redeploy`, `destroy`, `save` (any other action with one
of the new keys: 400 `'This action takes no run options.'`):

- `nodes`: list of strings; every name must be a `definition_node` of `parse_definition(source['text'])['nodes']`, else
  400 `"Choose devices from this lab's topology file: <names> are not in it."`; for `deploy` the lab's
  `deployment['status']` must be `'Not deployed'` else 409 the helper's F9 sentence (the manager says it first so the
  review never shows a command that cannot run); `nodes` with `cleanup` → 400 the helper's cleanup sentence.
- `max_workers`: `int` (not `bool`) 1..64 else 400 `'Max workers must be a whole number from 1 to 64.'`;
  `skip_post_deploy`, `keep_mgmt_net`: `bool` else 400 `'Invalid boolean option.'`.
- The review result passes through the helper's `kept` (names of the devices left running) and, for `apply`, `plan`,
  `plan_failed`; `opReview` renders them (§4.4, §4.5). The token record keeps the validated `nodes` list
  (`preview['nodes']`), and `confirm()` writes it on the job as the public field `nodes` (controlled metadata: the same
  literal topology node names the review showed, validated against the parsed topology; never a container id). The
  history, the job banner and `labState`'s label read it (§3.1: `Destroy ceos in <lab>`, `Destroying ceos…`), so a
  one-device destroy or save is never shown as the whole-lab action, in this tab or any other.
- Try again: `opRetryRequest(job, labId)` first uses the remembered request (`rememberJobRequest`, this tab); without
  one it rebuilds a filtered job from the public field, `{action, options: {nodes: job.nodes}}`, and for a filtered
  `destroy` adds no `cleanup` (the two cannot combine); a job with `nodes` and an unknown action returns `null` so the
  banner opens the operations dialog. A cancelled filtered `deploy` maps to `redeploy` as a plain deploy does, and a
  `redeploy` cannot take `nodes`: the mapping drops `nodes` and the review shows the whole lab. The three node actions
  take the `restart-node` branch of `opRetryRequest` (the device from `job.node`), never `opPlainRetry` (§4.2). Tests:
  the fallback with no stored request for a filtered destroy (no `cleanup`), a filtered save, `start-node` and
  `stop-node`.

### 3.3 The apply plan and the pending check (`impairments.py` owns the route; `lab_operations.py` the cache drop)

- `GET /api/operations/apply-plan?lab_id&refresh` is declared in `impairments.py`, which `create_app` installs before
  `LabOperations`: `LabOperations` declares `GET /api/operations/{job_id}`, and FastAPI matches in declaration order,
  so a GET declared later under `/api/operations/…` would answer `404 Operation not found.` (the trap
  `device_diagnostics.py` documents for its own routes). An `httpx` test asks `/api/operations/apply-plan` and asserts
  it never reaches the job route. The lab must have a topology path and a `deployment_name` (409 with
  `device_diagnostics.UNLINKED_SENTENCE` / `NO_FOLDER_SENTENCE` reused); `diagnostics.diagnose({'mode': 'apply-plan',
  'name': deployment_name, 'path': path}, 75)` (the three-slot semaphore, 503 when full); answer `{'changed': bool,
  'plan': {...public copy of apply_plan, lists sorted...} | None, 'failed': '' | 'unsupported' | 'error', 'error':
  strip_escapes(error_line)[:300], 'checked_at': time.time()}`.
- Cache: `operations.plan_cache[lab_id] = (expires, answer)`, 60 s, bypassed with `refresh=1`. It is dropped
  **before** the job's terminal `update()` in `execute()` (both the `else` branch and the `except` branch, and in
  `finish_stopped` before its terminal write), so a browser that sees the job terminal and asks at once can never
  receive the pre-operation plan; a test pins the order (the cache is empty by the time the job reads `succeeded`).
  It is also dropped by `PUT /api/labs/{id}/operations-settings` with a path and by a successful **Sync topology from
  VM** (`discovery`'s sync route calls `operations.forget_plan(lab_id)`).
- The browser asks it (a) when a lab becomes active and reads `Running` or `Partially running`, (b) after a lab
  operation of that lab turns terminal, (c) after a successful Sync topology from VM, (d) on **Review changes…** with
  `refresh=1`, and never on a timer (`test_operations_ui.js` pins `opPlanTriggers` with exactly these four). Two tabs
  share the manager cache.
- The apply **review** needs no extra route: `plan` arrives in the preview result (§2.6).

### 3.4 `impairments.py` (new module; installed after `DeviceDiagnostics`, before `LabOperations`)

`Impairments(store, operations, diagnostics)`; it reuses `diagnostics.target()` (404/409 sentences), `diagnostics.ask()`
(errors mapped, `Unknown request mode.` → `OLD_HELPER_SENTENCE`) and `interface_role`; one `threading.Lock` per lab
(`self.locks[lab_id]`, non-blocking: a second concurrent change answers 409 `'Another impairment change on this lab is in
progress; try again in a moment.'`).

**Both directions of the busy rule.** Every mutating call (set, reset, each reset of a clear) runs inside
`operations.impairing(lab_id)`: a context manager that, under `store.lock`, calls `guard(lab_id)` and adds a token to
`operations.in_flight_impairments` (a set `guard()` checks exactly like `self.active`: `if self.active or
self.in_flight_impairments or operation_busy(...)`), and removes it in `finally`. So (a) an impairment is refused while
any job, restore, Git save or design apply holds the lab (`guard()`'s two sentences, `'Wait for the current lab
operation to finish.'` and `'Wait for the lab backup or login job to finish.'`), and (b) a `preview` or `confirm` that
arrives while an impairment call holds the host flock answers 409 `'Wait for the current lab operation to finish.'`
instead of reaching the helper, meeting `LOCK_SENTENCE` and being stored as a failed job. The window is the one
helper call (≤ 42 s worst case, 0.3 s typical). The helper's own `LOCK_SENTENCE` can still reach a mutating call when
another lab's job holds the flock; the route maps it to `'Another lab operation is running on the VM (it may belong to
another lab); try again when it has finished.'` (409). The drawer treats all three sentences as its busy state (§4.1).
A test runs a preview during a patched, slow impairment call and asserts the 409 and that `remote` was not called.

- `POST /api/operations/impairments` body `{lab_id, node, interface, delay, jitter, loss, rate, corruption,
  expected_id}` (Pydantic, `extra='forbid'`; `delay`/`jitter` `str` ≤ 16; `loss`/`corruption` `float`; `rate` `int`;
  `expected_id` `str` of 64 hex, the `facts.id` of C03's `/netem` or `/interfaces` answer the drawer showed). Order of
  checks: `impairing(lab_id)` (the guard above); `target()`; the node's `runtime_state == 'running'` from the store
  (409 `'<device> is not running. Impairments can be set only on a running device.'`); `interface_role(kind,
  interface) == 'data'` (409 `'<interface> is the management interface; the manager reaches the device through it and
  never impairs it.'` for `eth0`, `'<interface> is an internal interface of this device, not a lab link.'` otherwise);
  value shapes through the shared `VALUE_RULES` (400 with the helper's sentences, so the browser's pure validator and
  the server agree; `-0.0` → `0`, jitter ≤ 60 s); then the helper request `{mode, name, options, expected_id, digest:
  digest({mode, name, options, expected_id})}` (the helper's `digest()` imported, one definition). Answer `{container,
  impairments: public rows}`. Event `store.event('lab.impairment', 'Impairment set on <node> <interface>: delay 20ms,
  jitter 5ms, loss 1.5%, rate 1000 kbit, corruption 0.5%', lab_id=…, node=…)`: validated numbers and names only.
- **Public rows are normalised** (`public_impairment(row, kind)`): `delay` and `jitter` come back from containerlab as
  Go durations (`20ms`, but also `1.5s` and `1m0s` for values the student typed as `1500ms` and `60s`); the manager
  parses `h`, `m`, `s`, `ms`, `µs`/`us`, `ns` and renders whole milliseconds (`'1500ms'`, `'60000ms'`, `''` stays
  `''`); `loss` and `corruption` are rounded to two decimals; `rate` is an int; `port` is `displayed_interface(kind,
  interface)`. A row the student never touched therefore always passes the UI's validator. Unit cases: `60s` → `60000ms`,
  `1.5s` → `1500ms`, `1m0s` → `60000ms`, `33.333` → `33.33`; the fixture answers `1m0s` for a 60 s set.
- `POST /api/operations/impairments/reset` `{lab_id, node, interface, expected_id}` → the same guard, target and role
  checks → helper `netem-reset` → `{container, changed, impairments}`; event `'Impairment reset on <node> <interface>'`
  when `changed`.
- `POST /api/operations/impairments/clear` `{lab_id, node?}` → inside `impairing(lab_id)` and the per-lab lock: the
  device (or every device of the lab with a container) is read with `netem-show-all` (in calls of 64 pairs or fewer),
  then one `netem-reset` per impaired data interface, in device order, each with the `expected_id` that read returned;
  the whole call has a budget of 120 s (`CLEAR_BUDGET`): it stops at the first failure or when the budget is spent and
  answers `{cleared: n, total: m, failed: [{node, interface, reason}], remaining: [{node, interface}], devices: {...}}`;
  one event `'Impairments cleared on <lab or node>: n of m interfaces'`.
- `GET /api/operations/impairments?lab_id` is a **read, unguarded** like C03's reads (no `guard()`, no per-lab lock;
  only the three-slot semaphore): `netem-show-all` for every device with a container (`expected_container` non-empty),
  split into calls of 64 pairs or fewer, each through `diagnose(request, 75)`; **no call at all when there are no
  pairs** (the answer is empty with `complete: true`). Answer `{devices: {node_name: {present, id, impairments:
  [public rows]}}, interfaces: n, complete: bool, fetched_at}` where `interfaces` counts impaired data interfaces (the
  map counts wires itself, §4.3), `id` is the container id the drawer sends back as `expected_id`, and `complete` is
  false when the helper's 60 s deadline left pairs unread (the page says `Some devices could not be read; try again.`).
  Rows whose `interface_role` is not `data` are dropped from the public answer (an impairment someone set on `eth0`
  from a terminal is not the manager's to show or clear; the drawer never lists it). No server cache (one SSH session
  per 64 devices, N × 150 ms); GET, so no `api.request` event. Because it is unguarded, the fetch the browser makes
  when a job turns terminal is answered even while `execute()`'s `finally` still runs `discovery.refresh()`.
- Public copies are field by field, as `public_facts`; the raw helper result is never returned.

### 3.5 Public shapes and events, summarised

- Jobs: `start-node` and `stop-node` records look exactly like `restart-node` ones (`node`, `node_label`,
  `links_expected`, `neighbours_down`, `neighbours_absent`, `cancel_requested`, `status` incl. `cancelled`); the history
  strips `output` as today. A filtered job carries the public field `nodes` (the validated topology node names, §3.2);
  the flags (`max_workers`, the booleans) stay in the browser's job-request memory, the review and the helper's
  digest, since nothing reads them back.
- Events: `lab.operation` as today for every job; `lab.impairment` with the sentences above. Never: an interface list,
  raw helper output, container ids (the `expected_id` travels in requests and the GET answer, never into an event).
- `/api/state`: `nos_login.status` gains `starting` and `stopping`; jobs gain `nodes`; nothing else.

## 4. The UI

### 4.1 Device drawer: the Impairments section (`device-impairments.js`, new)

One `<details class="drawer-section" id="details-impairments">` after `#details-info`, next to C03's two sections
(placed after them when they exist: the hook appends in load order). Capability rule (the same as Restart device's):
the section is rendered unless the capabilities are **known** to lack it (`opCaps` loaded and
`opCaps.actions.impairments.available !== true` → absent); unknown capabilities count as available, and opening the
section first awaits `opCapabilities()` (cached 60 s on the manager) and re-checks, showing `Not available on this VM —
its containerlab or helper cannot set impairments (see Diagnostics)` when the fresh answer says so. `renderDetails()`
calls `if(typeof renderDeviceImpairments==='function')renderDeviceImpairments(n)`; the drawer's close hook in `shell.js`
calls `resetDeviceImpairments()` behind a `typeof` guard. **The section's markup is built only when the key `(activeId,
detailName, answer)` changes** (a new device, or a new fetched answer); every other call from the 4 s poll or `render()`
only toggles `disabled` and `title` on the buttons, so typed values, the focused input and an open inline question
survive the poll (a test types into a row, calls `renderDeviceImpairments` twice with a changed `busy()`, and asserts
the value, `document.activeElement` and the question are intact). Nothing is fetched until the section is opened.
Opening fetches, once, `GET /operations/interfaces?lab_id&node` (C03's route, for the data rows and their `port`) and
`GET /operations/netem?lab_id&node` (C03's route, for the current values and `facts.id`, which every Apply, Reset and
Clear sends back as `expected_id`); no poll. After a lab operation of this lab turns terminal, the section refreshes
from `opImpairmentCache` (§4.3) **only when no row is edited and no question is open**; otherwise a one-line status
`The lab changed on the VM; Refresh to re-read the impairments.` with a Refresh button appears above the table. The two
hooks with C03's file: after a change this file calls `if(typeof refreshDeviceDiagnostics==='function')
refreshDeviceDiagnostics('netem')` so the Interfaces section's "delay 15ms · loss 5%" line follows, and C03's file may
call `refreshDeviceImpairments()` after its own refresh; both are optional.

**Table** (`.table-wrap`, `tabindex="0"`): one row per `data` interface, columns Interface (port on the first line, the
Linux name muted beneath) · Delay · Jitter · Loss % · Rate kbit · Corruption % · actions. Inputs: `<input
inputmode="decimal" size="6">` with `aria-label="Delay on Ethernet1"` etc. and placeholders `0ms`, `0ms`, `0`, `0`,
`0`; a row's inputs show the current values (`delay`/`jitter` as containerlab prints them, `''` shown as empty). Row
actions: **Apply** (`button primary small`, enabled when the row differs from the shown values and
`impairmentProblem(row)` is `''`) and **Reset** (`button ghost small`, enabled only on an impaired row). Above the table:
`Clear impairments on this device` (enabled when any row is impaired; `Clearing…` and disabled while its call runs)
and a `role="status"` sentence holding the last outcome. Caption under the table: "Impairments shape traffic leaving
the interface (delay and jitter in ms or s, loss and corruption in percent, rate in kbit/s). A restart, a stop and
start, or a redeploy of the device can remove them; the map re-checks after each operation. They cannot be changed
while any lab operation runs on the VM." (the first sentence is reworded from the live-pass step of §6 once it has run:
the design does not claim what a restart or a stop and start does to a qdisc).

**Validation**, pure `impairmentProblem({delay, jitter, loss, rate, corruption})` over the shared `VALUE_RULES` (one
JSON case table under `tests/fixtures/impairment_values.json` is read by `test_host_lifecycle.py`, `test_impairments.py`
and `test_device_impairments_ui.js`, so the three validators cannot drift): delay and jitter `''` or
`/^\d{1,6}(ms|s)$/` after normalisation (a bare number is read as ms and normalised to `<n>ms`; leading zeros are
stripped, `007ms` → `7ms`; `0`, `0ms`, `0s`, `''` all mean none), **each** ≤ 60 s → `'Delay and jitter are a number with
ms or s, up to 60s.'`; jitter set without delay → `'Set a delay before adding jitter.'`; loss and corruption `0..100`
with at most two decimals (`-0` normalised to `0`) → `'Loss and corruption are a percentage from 0 to 100.'`; rate a
whole number `0..10000000` → `'Rate is a whole number of kbit/s.'`; everything zero → `'Set at least one impairment, or
use Reset to remove them.'`. The server repeats these checks with the same sentences. Values read back from the
manager are already normalised (§3.4: whole milliseconds, two decimals), so a row the student did not touch never
fails its own validator.

**Review sentence** (the "review" of §1.2), inline like C02's Stop block, not a dialog: pressing Apply replaces the
row's actions with a `role="group" aria-labelledby` question `Set <delay 20ms, jitter 5ms, loss 1.5%> on <device>
<Ethernet1>? Traffic leaving this interface is shaped until you reset it.` with `[Apply]` (`button danger small`) and
`[Keep as is]` (focused first); Reset asks `Remove the impairments on <device> <Ethernet1>?` `[Reset]` `[Keep]`; Clear
asks `Remove every impairment on <device> (n interfaces)?`. After the call: the table is re-rendered from the answer,
the status sentence reads `Impairments set on Ethernet1.` / `Impairments removed from Ethernet1.` / `Ethernet1 had no
impairments to remove.` (`changed: false`) / `n interfaces cleared.` / on a partial clear `2 of 3 interfaces cleared;
Ethernet3: <reason>. Try again.` (a budget stop reads `2 of 3 interfaces cleared; the rest were not reached in time.
Try again.`), focus moves to the row's Apply or Reset button (whichever is now enabled, else the status). An error puts
the manager's sentence in the status (`role="status"`) and in the drawer's `.form-error`; the row keeps the typed
values. **Busy state**: any of the three busy sentences (`Wait for the current lab operation to finish.`, `Wait for the
lab backup or login job to finish.`, `Another lab operation is running on the VM (it may belong to another lab); try
again when it has finished.`) disables Apply, Reset and Clear with that sentence in `title` and the status; the
poll's toggle re-enables them when `busy()` clears (the third case has no local signal: the status keeps a Retry).

**States**: device not running → table replaced by `<device> is not running. Impairments can be set only on a running
device.`; `present: false` → `No container for this device yet.`; no data interfaces → `This device has no lab links.`;
old helper → section absent; VM unreachable → the manager's sentence with **Retry**. Keyboard: real buttons, labelled
inputs, one status element; no sideways scroll at 390 px (seven narrow columns: the inputs are `size="6"`, the actions
wrap under the row at ≤ 520 px via a `.impairments-table` rule).

### 4.2 Start device and Stop device (`app.js` `nodeActions`, `topology.js` `openNodeMenu`, `operations.js`)

- `opNodeActionState(action, lab, n, discovery, isBusy)` in `operations.js` generalises `opRestartState` (kept as a
  one-line wrapper so existing tests and callers stand): the same eight checks, then per action: `stop-node` needs
  `n.runtime_state === 'running'` (`'<dev> is not running'`), `start-node` needs a container that is not running
  (`'<dev> is already running'`; `absent` keeps the existing "not deployed" reason), and the capability exactly as
  `opRestartState` reads it today: unknown capabilities (`opCaps` not loaded) count as available, and only a loaded
  `opCaps.actions[action]?.available !== true` disables with `'Not available on this VM — its containerlab or helper
  cannot <start|stop> one device (see Diagnostics)'`; the click handler (`opNodeAction`) awaits `opCapabilities()` and
  re-checks before the review, as `opRestartDevice` does, so a fresh page never shows a false "Not available".
- Buttons: `nodeActions()` renders, after **Restart device…**, `<button class="danger-action" data-node-action="stop-node"
  data-node="<name>">Stop device…</button>` and `<button data-node-action="start-node" data-node="<name>">Start
  device…</button>` with `disabled title="<reason>"` from the state function; `nodeActionNotes()` adds `'Stop device… is
  not available: …'` only for the action whose precondition is the device's own state is *not* the reason (a running
  device's disabled Start needs no note; a stopped device's disabled Stop needs none). The map menu renders the same
  two items after Restart device… (one `data-node-action` handler in `app.js` line 401's block calls
  `opNodeAction(action, labId, name, opener)`, which runs `opCapabilities()`, the state check with the banner-headline
  error as Restart does, then `opReview({lab_id, action, node, options:{}})`). The Devices table rows get them through
  the shared `nodeActions()`.
- Review copy (`opReviewCopy`): `'stop-node'`: title `Stop <device>?`, body `Only <device> in <lab> stops: containerlab
  stops its container and parks its links (containerlab stop --node). Its CLI sessions drop and traffic through it
  stops; neighbours lose their adjacencies to it until it starts again. Configuration changes you have not saved on
  the device may not survive. Nothing is saved, backed up, reset or reapplied for you.`, confirm **Stop device**,
  danger. `'start-node'`: title `Start <device>?`, body `Only <device> in <lab> starts: containerlab starts its
  container and restores the links it parked (containerlab start --node). The device boots and reads Starting until it
  accepts a login again.`, confirm **Start device**. The known-limit and neighbour notes arrive as `warnings` from the
  manager. `opLabels` gains `'start-node': 'Start device'`, `'stop-node': 'Stop device'`; `opLifecycle` and
  `opDisruptive` (stop-node only) are extended; `opPlainRetry` is **not** (a plain retry carries no device: the three
  node actions share the `restart-node` branch of `opRetryRequest`, which rebuilds `{action, node: job.node,
  options:{}}`); `STATUS_OPERATION_LABELS` as in §3.1. In the review, every action in `NODE_ACTIONS` is treated as
  `restart-node` is today for the three generic lines: no `Configuration changes you have not saved are lost.` (the
  body already says "may not survive"), no `Open CLI sessions to this lab will disconnect.`, and instead of `n running
  devices affected` a per-action line: `1 device affected: ceos (clab-parity-ceos, running). The other devices of
  <lab> are not stopped.` / `… (clab-parity-ceos, exited). The other devices of <lab> are not started.` Wherever a job
  is shown (banner, toast after confirm, history, header) the device is named: `Stopping ceos…`, `✔ ceos stopped`,
  `✖ Stop ceos failed` (`opJobLabel(job)`, §3.1), never the bare `Stop device`.

### 4.3 The map badge (`topology.js`, `topology-render.js`, `index.html`, `style.css`)

- `topology-render.js` already writes `data-capture-endpoints` (`[{node: inventory_name, interface}]`) on every wire
  group; nothing in the markup changes except that `topologyLink` also emits `data-link-ends="<node>:<if>|<node>:<if>"`
  (escaped) so matching needs no JSON parse per render.
- `renderMapImpairments(answer)` in `topology.js` (pure matcher `impairedWires(drawingLinks, devices)` tested in
  `test_topology_ui.js`, returning per wire the impaired ends): a wire end is impaired when its device matches the
  node name and its interface equals the impaired row's `interface` or its `port`; the group gets
  `classList.toggle('impaired', hit)`, its `<title>` becomes `<base> · impaired at ceos Ethernet1 (traffic leaving
  ceos): delay 20ms, loss 1.5%` (both ends listed when both are impaired; the base text is kept in a data attribute
  and restored, the way `renderMapState` restores titles) and the same clause is appended to the wire's `aria-label`
  (`Capture ceos:eth1 to vsw:eth1 · impaired at ceos Ethernet1 …`), so a screen reader hears it. It is re-applied from
  `opImpairmentCache` at the end of every map render (`renderMap` calls it after `renderMapState`), so a re-render
  never drops the class until the next fetch. CSS, obeying the invariant: `.topology-wire.impaired
  path:not(.capture-hit){stroke:var(--warn);stroke-dasharray:7 4}` and no other stroke rule; `path.capture-hit` keeps
  its 16 px transparent hit area, so right-click and click on an impaired link still open Capture.
- Caption: a static `<span id="map-impaired" role="status" hidden></span><button type="button" class="button ghost
  small" id="map-impaired-clear" hidden>Clear impairments</button>` in the map tools bar of `index.html` (and the
  expanded map's bar): the count is the number of **wires** `impairedWires()` matched (`1 link impaired` /
  `n links impaired`; a link impaired at both ends is one), with the interface count in the title (`2 interfaces`);
  `complete: false` adds `· some devices not read`. Clear impairments opens a confirmation dialog (`opDialog`) `Remove
  every impairment in <lab> (n interfaces on m devices)?` → `POST /operations/impairments/clear {lab_id}` (the button
  reads `Clearing…` and is disabled meanwhile), then re-fetches; a partial result shows `2 of 3 interfaces cleared;
  vsw Ethernet3: <reason>. Try again.` in the dialog's status.
- When it loads: `opLoadImpairments(labId)` (GET §3.4, unguarded) runs when a lab becomes active and reads Running or
  Partially running, after a lab operation of the lab turns terminal, after a successful Sync topology from VM, and
  after every change from the drawer; never on a timer; the answer is kept in `opImpairmentCache[labId]` and the
  drawer reads it to pre-fill before its own fetch returns.

### 4.4 The apply review with its plan, and the pending-changes line (`operations.js`, `app.js`, `index.html`)

- `opReview` for `apply` renders `value.plan` above the body as `opPlanMarkup(plan, failed)` (pure, tested): sections
  in this order, each only when non-empty, each a `<h4>` with a count and a list: **Create** (`added`), **Start**
  (`started`), **Restart** (`restarted`, with `reasons[name]` muted after the name), **Recreate** (`recreated`, reason;
  the section's own line `These devices are recreated: configuration you have not saved on them is lost.`), **Remove**
  (`removed`; `These devices are removed from the VM: their unsaved configuration is lost.`), **Links to connect**
  (`links_added`), **Link ends to disconnect** (`endpoints_removed`). `deploys_lab` → one line `The lab is not running:
  Apply deploys the whole topology.` An empty plan → `<p>Nothing to apply: the running lab already matches its topology
  file.</p>` and the confirm button becomes `button secondary` **Apply anyway**. `plan_failed: 'error'` → the warning the
  manager passed and the confirm reads **Apply anyway** (`danger`); `'unsupported'` → `<p class="op-notice">The installed
  containerlab cannot show what Apply will change; the command runs without a plan.</p>`, confirm **Apply changes**.
  The generic sentence `Configuration changes you have not saved are lost.` and `Open CLI sessions to this lab will
  disconnect.` stay while `plan_changes(plan)` is true or the plan is unknown (apply is disruptive); when the plan is
  known and empty both lines are dropped (nothing is lost by a no-op), and the plan's own lines name which devices.
- **Apply in the menu**: `Lab actions ▾` gains `<button role="menuitem" data-op-action="apply"
  data-op-options="{}"><span>Apply topology changes…</span>…` between *Restart all devices…* and the separator,
  enabled by `renderLabOperations`' existing rule (`running`, i.e. `Running` or `Partially running`, with the
  capability check), so every sentence that sends the student to Apply topology changes names a place one click away.
- Pending changes: `opPendingChanges(lab)` returns the cached `apply-plan` answer when `changed` is true. Its
  identity is `'pending.'+opPlanIdentity(plan)`, a short hash (the `deviceSlug` hash) of the canonical plan: every
  list sorted, the reasons' keys sorted, `checked_at` excluded; so a dismissed banner stays dismissed while the plan is
  the same and comes back when it differs (test: the same plan re-checked stays dismissed; a plan with one more device
  shows again). `renderLabBanner`: (a) in the **attention branch for `Partially running`** (which runs before any
  later branch and today offers Start), when the cached plan has `added`, `recreated` or `endpoints_removed` entries
  the action is `banner-review` (`Review changes…`) and the detail `opPlanSummary(plan)` (`ceos to create`), because
  the lab-wide `containerlab start` cannot recreate a destroyed device; Start stays only when the plan is absent,
  unknown, or `started`-only (a device merely stopped); (b) for a `Running` lab, after the `starting` branch and before
  `stopped`, `else if(pending)` → `{tone:'info', icon:'info', text:'The topology file differs from the running lab.',
  detail: opPlanSummary(plan) ("r3 to create · r2 to recreate · 1 link to connect"), identity, actions:{'banner-review':
  {label:'Review changes…', run:()=>opTask(null,()=>opReview({lab_id, action:'apply', options:{}}))}}}`; a new static
  `<button id="banner-review" hidden>` in `#lab-banner` and in `BANNER_BUTTONS`. Dismiss hides it for the session (the
  banner's own `noticeDismissed` with the identity). A banner-harness test covers a `Partially running` lab with a
  pending plan (Review changes… shown, no Start) and with a `started`-only plan (Start shown). **Advanced › Deployment
  details** gets `<dt>Topology file</dt><dd id="deployment-pending">` reading `Matches the running lab (checked 2 min
  ago)` / `Differs from the running lab: … — Review changes…` (a button) / `Not checked` / `Could not be checked: …`.
  Nothing applies by itself.

### 4.5 Run with options (`operations.js`, the reviews of deploy, redeploy, destroy, save)

- A `<details class="op-options" id="op-run-options"><summary>Run with options</summary>` fold under the body, built by
  `opOptionsForm(action, caps, lab, options)` (pure markup, tested), with only the controls the installed command has
  (`caps.actions[action].node_filter` etc.): **Choose devices** (a checkbox per device of the lab, labelled by its
  short name; for `deploy` only while the lab reads `Not deployed`, with the help line `Only possible before the lab is
  deployed; add the rest later with Apply topology changes.`; for `destroy` the line `The devices you leave out keep
  running; the lab folder is kept.`; for `save` `Only the chosen devices save their configuration.`), **Max workers**
  (`<input type="number" min="1" max="64">`, help `How many devices containerlab creates at once. Leave empty for
  containerlab's default; 1 or 2 spares memory when devices are VMs.`), **Skip post-deploy actions** (deploy,
  redeploy), **Keep the management network** (redeploy, destroy), **Graceful stop** (destroy, redeploy; help `Asks each
  device to shut down before removing it. A device that ignores the request is removed after two minutes, and with
  several devices the waits add up.`, F10; when Graceful is chosen together with a Max workers value below the number
  of affected devices and `2 min × devices ÷ workers` exceeds the run limit of 1250 s, the review shows the notice
  `With these options the command may take longer than the manager waits for it (about N minutes); choose more workers
  or leave Graceful stop off.`). `opReview` for these four actions awaits `opCapabilities()` first (also from
  `opQuickRun('start')`, which did not load them), so the fold never goes missing on a fresh page. A change of any
  option re-runs the preview with the new options (`opReview(request)` again: the review *is* the preview of the exact
  request, and the helper's digest binds it), with this sequencing: the whole fold is disabled and a `role="status"`
  line reads `Checking…` while a preview is in flight; each re-preview carries a sequence number and an answer older
  than the newest request is dropped (its token is never shown); checkboxes re-preview on `change`, the Max workers
  input on `change` (not on `input`); the fold stays open and focus returns to the changed control (`opReview` takes
  `{keepOptionsOpen, focusId, seq}`). Unticking every device returns the action's plain request (for Destroy lab,
  `opDestroyOptions()` with its `cleanup` default comes back). The command block then shows the exact argv. Tests in
  `test_operations_ui.js`: an out-of-order answer is dropped, the fold is disabled during the call, the defaults return.
- With `nodes` set, the Devices list of the review shows only the chosen devices and a line `Left running: a, b` from
  `value.kept` (destroy) or `Not saved: a, b` (save); the destroy title becomes `Destroy r2 in <lab>?` and the body
  `The chosen devices are removed from the VM; the other devices and the lab folder stay.`; **Clean up** is not offered
  while devices are chosen (the two cannot combine, F10) and the `cleanup` default of Destroy lab is dropped from the
  request when a device is chosen (`opDestroyOptions` unchanged for the plain path).
- Entry points: the fold is inside the existing reviews, so **Destroy lab…**, **Start lab**, **Redeploy lab…** and
  **Save device configurations** gain it without a new menu item. The lab-wide path is unchanged for a student who
  never opens the fold.

### 4.6 Save this device's configuration (`app.js` `nodeDrawerActions`)

The drawer's Advanced actions gain `<button data-save-node="<name>">Save startup configuration…</button>` (enabled when
the capabilities are unknown or say `actions.save.node_filter`, the device is running and the lab is not busy; reason
in `title` and the Advanced note; the click awaits `opCapabilities()` and re-checks) → `opReview({lab_id,
action:'save', options:{nodes:[short]}})`; the save review with one device reads `Save
<device>'s running configuration as its startup configuration on the VM? (containerlab save --node-filter). This is
separate from Save in the lab's header and from the manager's backups.`

## 5. Tests per layer and the fixture

- **Helper** (`tests/test_host_lifecycle.py`, new, copying `test_host_diagnostics.py`'s `DiagnosticsHarness` with the
  stub `docker`, the recorded `run`/`probe` argv and a fake `/proc` tree; `test_gateway_whitelist.py`'s "no new request
  name, no shell" assertion extended to the new modes):
  `netem-set` exact argv with all five flags and `'%g'` numbers; refusals run nothing: a missing key, a ninth key,
  a missing or malformed `digest` or `expected_id`, a digest over different options, an `expected_id` that is not the
  inspected Id (the "container changed" sentence), `eth0`, `lo`, a 16-char name, `'eth1;x'`, `'0'` and `''` for delay,
  `'61s'` for delay **and** for jitter, `'007ms'`, jitter without delay, `loss 100.1`, `loss -0.0` (rendered `0`),
  `True` for loss, `rate -1`, `rate 10000001`, all zeros, a stopped container, `present: False`, `network_mode`
  `host`, `container:abc`, `''` and missing (eleven-field inspect line), a task whose `ns/net` is pid 1's, an
  unbindable pid, a cgroup mismatch, an `OSError` inside `in_host_network` (tri-state `None` refuses), another lab's
  container; containerlab's `Link not found.` and `Jitter cannot…` map to the sentences; the result is the rows after;
  the shared value cases come from `tests/fixtures/impairment_values.json`. **The lock**: `netem-set` and `netem-reset`
  under a held flock (a second process holding `/run/clab-manager-operations.lock`, the C02 harness) answer exactly
  `LOCK_SENTENCE` and run nothing; `netem-show-all` and `apply-plan` under the same held lock still answer;
  `lab_operations.LOCK_SENTENCE == host_operations.LOCK_SENTENCE`. `netem-reset`: no reset argv when the interface
  has no row, `changed` flags, the two show calls around one reset. `netem-show-all`: 64 pairs ok, 65 refused, one bad
  pair fails the call, stopped containers answer `[]`, a patched clock past `SHOW_ALL_DEADLINE` returns the rest as
  `unread` with `complete: False`. `apply-plan` and the plan in `plan()`: one `dry_run_argv()` and a test that
  `'--dry-run'` is in every argv either builds (`deploy --dry-run --format json -t <path> --name <lab>`),
  `apply_plan()` on the three live shapes of F8 (deployed with changes, undeployed with `null` lists, empty) plus junk
  keys and over-long names, lists and reason keys sorted whatever the input order, `error_line()` on F13's capture
  (the line after `ERROR`, never the INFO banner, the `Consult…` line only when nothing better exists), a non-zero exit
  gives `plan_failed: 'error'` and the warning, `'--dry-run'` absent gives `'unsupported'`, and the digest of two
  `apply` plans with different live plans differs while the argv is identical. Node actions: `start-node`/`stop-node`
  argv, the `--node` probe for each, `stop-node` on an exited row refused, `start-node` on a running row refused, the
  digest changes with the state, and `test_restart_device_fails_closed_on_every_bad_selector…` runs for all three
  actions. Options: the per-action table as a parametrised test (every key against every action: accepted or
  `'Unsupported operation options.'`), `nodes` shapes (`'a,b'`, 65 names, duplicates, `['eth0 ']`), `nodes` on a
  deployed `deploy` refused with the F9 sentence, `nodes` with `cleanup` refused, `nodes` on destroy with an
  undeployed name refused, membership through `container_matches` in an **empty-prefix lab** (containers named `r1`,
  `r2`) and in a custom-prefix lab, `kept` and `affected` split, the fixed argv order, the redeploy fallback's flag
  distribution, `max_workers` `0`, `65`, `True`, `'4'` refused, each flag refused when its `--flag` is missing from
  the stubbed help; `capabilities` carries the new booleans, `start-node`, `stop-node`, `impairments`,
  `lifecycle_options`; `main()` dispatches exactly the named modes: `preview`, `run`, `netem-set` and `netem-reset`
  through the one `locked()` helper, every other mode without it (the test patches `fcntl.flock` and records which
  modes call it).
- **Manager** (`tests/test_lab_operations.py` additions and a new `tests/test_impairments.py` with `httpx`): preview of
  the three node actions resolves the device and refuses the same bad inputs; `stop-node` is refused by the manager's
  state check with the helper never asked; the stale-review rule holds for `start-node`; a stopped `stop-node` ends
  `cancelled` with its aftermath; `public_lab` shows `starting`/`stopping`; `STOPPABLE`/`STATUS_STOPPABLE` and the
  aftermath words stay equal (the C02 test, extended); `neighbour_note` with an absent neighbour (the "destroyed, not
  stopped" sentence, Apply named) and with a stopped one, per action verb. Options: a `nodes` name outside the parsed
  topology is 400 with the names listed; `nodes` on a Running lab's deploy is 409; `max_workers` `'4'`/`0`/`65` 400;
  the request reaching the patched `remote` carries exactly the options sent; the job record carries the public
  `nodes` and the history shows it (`Destroy ceos in <lab>` label built from it in JS); `last_deployed` unchanged after
  a succeeded filtered destroy and a filtered save, set after a filtered deploy. Apply plan: `GET
  /api/operations/apply-plan` is answered by `impairments.py`, never by the `{job_id}` route (an unknown lab is its
  own 404, not `Operation not found.`); caches 60 s, `refresh=1` bypasses; the cache is **already empty when the job
  record first reads terminal** (a fake `remote` whose job finishes while the test polls the record, then asks the
  plan: the answer is the post-operation plan); a successful sync drops it; the fourth concurrent call is 503; an
  unlinked lab gets its sentence; `error` is escape-stripped and cut. Impairments routes: `guard()` 409 while a job of
  the lab runs and while a restore holds it (both guard sentences covered); **a preview and a confirm during a slow
  patched impairment call answer 409 and never call `remote`** (the in-flight set); the helper's `LOCK_SENTENCE` maps
  to the "may belong to another lab" sentence; 404 unknown device; 409 not running; 409 for `eth0`, `cpu`,
  cJunosEvolved `eth2`; 400 for each value case of the shared JSON table; `expected_id` required and 64 hex; the helper
  request carries exactly `{mode, name, options, expected_id, digest}` with the normalised strings and a digest the
  helper's `digest()` reproduces; public rows normalise `1m0s`, `1.5s`, `60s` and `33.333`; a second concurrent change
  on the lab is 409 and the first completes; the event line is the controlled sentence and `events.jsonl` holds no
  interface list from `GET` and no container id; `clear` splits a 70-device lab into two helper calls, stops at the
  first failure, stops at its budget (patched clock) and reports `cleared`, `total`, `failed`, `remaining`; GET makes
  no helper call for a lab without containers, splits above 64, drops non-data rows, counts `interfaces`, carries
  `complete`, and is answered while a job's `finally` still holds `self.active`; a cross-origin POST is 403 and nothing
  reaches the helper.
- **UI** (`node:test`): new `tests/test_device_impairments_ui.js` (the `test_operations_ui.js` harness plus a fake
  `fetch`): `impairmentProblem` on every case of the shared JSON table and the normalisation (`'20'` → `'20ms'`,
  `'007ms'` → `'7ms'`, `-0` → `0`), row diff → Apply enabled, Reset only on impaired rows, the inline question markup
  (`role="group"`, labelled, Keep first), focus after a change, the three empty states, the three busy sentences as one
  disabled state, the `changed: false` and partial-clear sentences, `Clearing…`, **the rebuild rule** (typed value,
  focus and open question survive two renders with changed `busy()`; a new answer rebuilds; a terminal job with an
  edited row shows the Refresh line instead of rebuilding), `expected_id` sent from `facts.id`, the capability rule
  (unknown counts as available; a loaded `false` hides), the hooks guarded by `typeof`; `test_operations_ui.js`:
  `opNodeActionState` per action and state and with `opCaps` null, `opRestartState` unchanged, `opJobLabel`
  (`Stop ceos`, `✔ ceos stopped`, `Destroy ceos in lab` from `nodes`), the review's generic lines absent for the node
  actions and for an empty plan, the per-action affected line, `opPlanMarkup` (section order, reasons, empty, failed,
  unsupported, `deploys_lab`), `opPlanSummary`, `opPlanIdentity` (same plan in another order → same identity; one more
  device → different), `opOptionsForm` per action and capability set, the re-preview sequencing (out-of-order answer
  dropped, fold disabled, defaults back when no device is chosen, the Graceful notice), `opPendingChanges`,
  `opPlanTriggers` (open, after a job, after a sync, review; never a timer), `opRetryRequest` with `nodes` and without
  a stored request for destroy (no `cleanup`), save, `start-node`, `stop-node`; `test_topology_ui.js`: `impairedWires`
  by interface and by port returning the ends, the wire count against the interface count, the class toggle, the title
  and `aria-label` text with the end named, the re-apply after a map render; `test_status_ui.js`: the new labels and
  `deviceState` keys; a CSS test (grep in `test_topology_ui.js`, as the capture-hit invariant is pinned today) that
  every `stroke` rule on `.topology-wire … path` excludes `.capture-hit`; `test_page_load_ui.js` with
  `device-impairments.js` in its place; `test_home_ui.js`/banner harness: `banner-review` for a pending plan on a
  Running lab, **on a Partially running lab with `added` entries (no Start)**, Start kept for a `started`-only plan,
  dismissed per plan identity (the same plan re-checked stays dismissed), the Apply item of Lab actions ▾ enabled on
  Running and Partially running.
- **Fixture** (`docs/redesign/tools/fixture_manager.py`, `fake_remote`): `capabilities` gains the new booleans and the
  three new actions; a stateful `netem` map keyed by `(container, interface)` answers `netem-show`, `netem-show-all`,
  `netem-set` (replace semantics, the digest and `expected_id` checks, the helper's refusals for `eth0`, all zeros,
  jitter without delay, a stopped device; a 60 s set reads back as `1m0s`, 1500 ms as `1.5s`) and `netem-reset`
  (`changed` false when absent); `LOCK_SENTENCE` for a mutating netem mode while a scripted run is in its lock window;
  `apply-plan` returns an empty plan unless the control switch
  `pending_changes` is set (then `added: ['r3']`, `recreated: ['r2']` with a reason, one `links_added`) or
  `pending_failed` (an error line); `ops_preview` accepts `start-node`/`stop-node` with the state checks and the
  `nodes`/flag options with the argv order; `ops_run` flips the one node's state in `groups` for the node actions and
  removes only the chosen rows for a filtered destroy. The Playwright check (`docs/parity-campaign/tools/check_c05.py`,
  `clab-ui-qa`): the Impairments section at 1440 and 390 (no sideways scroll), Apply with its question, Reset, Clear
  all, the map class and caption, Stop device then Start device from the drawer and the map menu with their disabled
  reasons, the apply review with a scripted plan, the pending banner and its Review changes…, Run with options on
  Destroy lab (two devices chosen, `Left running`, Clean up absent) and the resulting command line, Save startup
  configuration… from the drawer.

## 6. Documentation, slices, acceptance checks, the live pass

**Documentation** (one owner, after the code settles): `docs/LAB-OPERATIONS.md` table rows — *Start device… / Stop
device…* (one paragraph beside Restart device…: containerlab's node-scoped start and stop, links parked and restored,
the two known limits, "a device stopped outside containerlab lost its links; Start device brings the device back
without them, Redeploy lab brings both back"), *Apply topology changes* (rewritten: the plan sections, "Nothing to
apply", Apply anyway, and that the plan is re-checked when you confirm), *Run with options* (a new row: Choose devices
on Destroy, Save and an undeployed Start lab, Max workers, Skip post-deploy, Keep the management network, Graceful
stop and its two minutes; why Clean up and chosen devices do not combine; why a running lab cannot take a partial
deploy), *Impairments* (a new row: the drawer section, the five values, replace semantics, the management interface
refusal, the map caption and Clear impairments, the lifetime sentence worded from live-pass step (7), and that no
impairment can be changed while any lab operation runs on the VM), *Save device configurations* (one device from the
drawer); the "Where the commands are" paragraph lists **Apply topology changes…** among the Lab actions ▾ items; the
*Restart device…* row's neighbour paragraph gains the destroyed-neighbour case; "Every operation is reviewed first" gains the
pending-changes banner sentence ("`The topology file differs from the running lab` appears once when you open a
running lab and after each operation; nothing is applied until you review"). `docs/DEBUG-PANEL.md`: the capabilities
row names `start-node`, `stop-node`, `impairments` and the per-action flags. `clab-backup-ui/NODE-FEATURES.md`: the
drawer's new actions in its device-panel list. `docs/CAPTURE.md`: one sentence that an impaired link still opens
Capture. Release records and `CLAUDE.md` invariants (a line under *VM boundary*: "impairments never touch `eth0`,
internal or host-network interfaces; a netem change is bound by `container_of` and logged as controlled metadata"):
the lead.

**Build slices** (disjoint files; the path rules name the builders; `/clab-slice-verify` per slice):

| Slice | Files | Builder | Size | Acceptance checks |
|---|---|---|---|---|
| S1 helper | `app/host_operations.py`, `tests/test_host_lifecycle.py` (new), `tests/fixtures/impairment_values.json` (new), `tests/test_gateway_whitelist.py` (one assertion), `tests/test_host_diagnostics.py` (the eleven-field inspect line) | lead or `clab-fable-specialist`; `risk-reviewer` on the diff | L | every §2 argv reproduced by a stub run; every §7 helper refusal runs nothing; `netem-set` never reaches containerlab for `eth0`, `host`/`container:*` network modes or a mismatched `expected_id`; the dry run is `deploy --dry-run --format json` and every dry-run argv carries `--dry-run`; `main()` takes the flock through one shared helper for exactly `preview`, `run`, `netem-set`, `netem-reset`, and `netem-set` under a held lock answers `LOCK_SENTENCE` and runs nothing; `test_host_diagnostics.py`, `test_lab_operations.py`, `test_gateway_*` green |
| S2 manager | `app/lab_operations.py`, `app/impairments.py` (new; owns `/impairments*` and `/apply-plan`), `app/main.py` (install line, `public_lab` status), `app/discovery.py` (the sync route's `forget_plan` call), `tests/test_lab_operations.py`, `tests/test_impairments.py` (new), `docs/redesign/tools/fixture_manager.py` | `clab-backend-engineer` from this document (line-by-line for `lab_operations.py` and `discovery.py`, privileged paths); `risk-reviewer` | L | the §3 routes and sentences; `guard()` refuses in both directions (the in-flight set); `/apply-plan` never reaches the job route; the plan cache is empty before the terminal write; `last_deployed` pins; the stale rule for the three node actions; the public `nodes` field; the normalised read-back; the C02 equality tests still pass with the new entries; the fixture answers every new mode |
| S3 UI drawer | `app/static/device-impairments.js` (new), `app/static/app.js` (`nodeActions`, `nodeActionNotes`, `nodeDrawerActions`, the two handler lines, `renderDetails` hook), `tests/test_device_impairments_ui.js` (new) | `clab-ui-builder` | M | §4.1, §4.2 buttons, §4.6; the section is absent without the capability; no inline styles; `esc()` on every value; no sideways scroll at 390 px (QA) |
| S4 UI map, reviews, status | `app/static/operations.js`, `topology.js`, `topology-render.js`, `status.js`, `shell.js` (close hook line), `index.html` (script tag with `?v=`, `banner-review`, `map-impaired*`, `deployment-pending`), `style.css`, `tests/test_operations_ui.js`, `test_topology_ui.js`, `test_status_ui.js`, `test_page_load_ui.js`, the banner harness | `clab-ui-builder` (a second one; S3 and S4 never share a file: S3's markup needs in `index.html`/`style.css` are listed in §4.1 and belong to S4) | L | §4.3 class and caption with the capture-hit rule intact; §4.4 plan sections and the banner; §4.5 fold per capability and the re-preview; the new vocabulary everywhere `STATUS_*` is read; `node --check` on every changed script |
| S5 QA and docs | `docs/parity-campaign/tools/check_c05.py` (new), `docs/LAB-OPERATIONS.md`, `docs/DEBUG-PANEL.md`, `NODE-FEATURES.md`, `docs/CAPTURE.md` | `clab-ui-qa`, then `docs-auditor` | M | the fixture pass of §5 at 1440/1280/760/390 in Chromium and Firefox; every documented sentence matches a sentence in the code |

Order: S1 first (its contract is §2; S2 builds against it with the fixture), S3 and S4 in parallel once S2's routes
exist in the fixture, S5 last. `/clab-review-changes` on the whole branch before the release step; the release bump,
the three records, the CI lists (`test_host_lifecycle.py`, `test_impairments.py`, `test_device_impairments_ui.js`) and
the helper refresh on the VM are the lead's.

**Live pass on the `parity` lab (the lead, after the helper refresh; one operator)**: (1) `vsw` drawer › Impairments:
Apply delay 200 ms on the `vsw`–`vrt` link's `vsw` end; on `vrt`'s CLI a ping to `vsw` shows ~200 ms where it showed
< 5 ms (read-only `ping` only; nothing configured); the map shows the dashed wire, the caption `1 link impaired`, the
title names the delay; a reload keeps it (R042). (2) Reset on that row: the ping returns to its base, the class and
caption clear. (3) Apply loss 50 % on `ceos` `eth1` and delay on `vsw` again, then **Clear impairments** from the map caption:
`2 interfaces cleared`, both drawers empty. (4) Destroy lab… › Run with options › choose `ceos` only: the review names
`Left running: vsw, vrt, cjunos, xrv9k`, Clean up is absent; after the job the lab reads *Some devices stopped*, `ceos`
is `absent`, `last_deployed` unchanged, the pending banner appears (`ceos to create`); Review changes… › Apply: `ceos`
comes back; the banner clears after the job. (5) Stop device on `ceos`: the job output, `ceos` reads *Stopping* then
*Stopped*/not running, the neighbour's interface still listed (C03 Interfaces of `vsw`); Start device on `ceos`:
`Restored link` in the output, *Starting*, then Ready; the readiness proof was forgotten and re-proven. (6) An apply
review of the unchanged lab reads `Nothing to apply` with **Apply anyway**. (7) **Lifetime of an impairment**: Apply
delay 100 ms on `ceos` `eth1`, read it back (`netem show` and the drawer), then Restart device on `ceos` and read it
back again; then Stop device, Start device, read back again; then Redeploy lab and read back once more. Record for
each step whether the qdisc survived; the drawer's caption (§4.1) and the LAB-OPERATIONS sentence are then worded from
that result (today's wording claims only "can remove them"). Record timings, the scrubbed outputs and the exact
sentences in `docs/parity-campaign/evidence/c05-live.md`.

## 7. Every refusal, with its wording

| Where | Condition | Sentence |
|---|---|---|
| helper | an option key outside the whitelist of the action | `Unsupported operation options.` (existing) |
| helper | `netem-set` with keys other than the eight, `netem-reset` other than three | `Unsupported impairment options.` |
| helper | `netem-set`/`netem-reset` while another process holds the host flock | `Another host lab operation is running.` (`LOCK_SENTENCE`; the manager shows the "may belong to another lab" sentence below) |
| helper | the request's `digest` is missing or differs from `digest({mode, name, options, expected_id})` | `Review the impairment again.` |
| helper | `expected_id` missing, not 64 hex, or not the inspected container's Id | `The device's container changed since you opened this section; reopen it and apply again.` |
| helper | interface name not `[A-Za-z0-9_.-]{1,15}` | `Choose an interface by its literal name.` |
| helper | interface `eth0` | `The management interface eth0 cannot be impaired: the manager reaches the device through it.` |
| helper | interface `lo` | `lo cannot be impaired.` |
| helper | device present but not running, or absent | `Device <container> is not running; impairments exist only on a running device.` |
| helper | `HostConfig.NetworkMode` is `host`, or the task's `ns/net` is pid 1's | `This device shares the VM's own network; its interfaces are the VM's and cannot be impaired.` |
| helper | `HostConfig.NetworkMode` is `container:*` | `This device shares another container's network; its interfaces are not its own and cannot be impaired.` |
| helper | `HostConfig.NetworkMode` empty or missing | `The manager could not read this device's network mode; try again in a moment.` |
| helper | `/proc/<pid>` not bindable, cgroup mismatch, or the namespace check errs (tri-state unknown) | `The manager could not bind this device's network namespace; try again in a moment.` |
| helper | `netem-show-all` past its 60 s deadline | not a refusal: the unread pairs come back as `unread`, `complete: false`; the page says `Some devices could not be read; try again.` |
| helper | delay or jitter not `<n>ms|s` (no leading zero), or either > 60 s | `Delay and jitter are a number with ms or s, up to 60s.` |
| helper | jitter > 0 with delay 0 | `Set a delay before adding jitter.` |
| helper | loss or corruption outside 0..100 or not a number | `Loss and corruption are a percentage from 0 to 100.` |
| helper | rate not an int in 0..10000000 | `Rate is a whole number of kbit/s.` |
| helper | all five zero | `Set at least one impairment, or use Reset to remove them.` |
| helper | containerlab exit ≠ 0 on set, `Link not found.` | `<interface> is not an interface of this device right now.` |
| helper | containerlab exit ≠ 0 on set, other | `Containerlab on the VM refused the impairment: <its last line>` |
| helper | containerlab exit ≠ 0 on reset | `Containerlab on the VM could not reset the impairment on <interface>.` |
| helper | `netem show` unreadable | `Containerlab on the VM did not show the impairments of this device.` (existing) |
| helper | `netem-show-all` with 0 or > 64 pairs | `Name 1 to 64 devices.` |
| helper | a pair's binding fails | C03's `This container does not belong to lab <lab>.` (existing) |
| helper | `start`/`stop` command missing or without `--node` | `This Containerlab version does not support <start|stop>.` / `The installed Containerlab cannot <start|stop> one device: its <command> command has no --node option. Upgrade containerlab on the VM.` |
| helper | `stop-node` on a container not running | `Device <container> is <state>; there is nothing to stop.` |
| helper | `start-node` on a running container | `Device <container> is already running.` |
| helper | node action's container not deployed, or several | `Device <container> is not deployed in lab <name>. Refresh the lab list and review again.` (existing) |
| helper | `nodes` not a list of 1..64 unique literal names | `Choose devices by their literal topology node names.` |
| helper | `nodes` on `deploy` while rows exist | `This lab is already deployed, so a deploy limited to chosen devices is not possible (containerlab would remove the devices left out). Use Apply topology changes to add the missing devices.` |
| helper | `nodes` with `cleanup` | `Clean up cannot be combined with chosen devices: containerlab would delete the whole lab folder, which the devices left running still use.` |
| helper | a `nodes` name not among the deployed rows (destroy, save) | `Device <node> is not deployed in lab <name>. Refresh the lab list and review again.` |
| helper | `max_workers` not an int in 1..64 | `Max workers must be a whole number from 1 to 64.` |
| helper | a flag the installed command lacks | `Installed command lacks --<flag>.` (existing) |
| helper | `apply-plan` with a missing or non-YAML path | `Select the original lab YAML.` / path sentences (existing) |
| helper | run whose recomputed plan differs | `The topology or deployment changed. Preview the operation again.` (existing) |
| manager | `node` with an action outside the three | `Only Restart device, Start device and Stop device name a single device.` |
| manager | a run option on an action outside deploy/redeploy/destroy/save | `This action takes no run options.` |
| manager | a `nodes` name outside the parsed topology | `Choose devices from this lab's topology file: <names> are not in it.` |
| manager | `nodes` on deploy while the lab is not `Not deployed` | the helper's F9 sentence |
| manager | impairment change while a job, restore, Git save or design apply holds the lab, or another impairment call is in flight | `Wait for the current lab operation to finish.` (existing guard sentence) |
| manager | impairment change while a backup or login job of the lab runs | `Wait for the lab backup or login job to finish.` (existing guard sentence) |
| manager | a preview or confirm while an impairment call is in flight | `Wait for the current lab operation to finish.` (409; the job is never created) |
| manager | the helper answered `LOCK_SENTENCE` to a mutating netem mode (another lab's job holds the flock) | `Another lab operation is running on the VM (it may belong to another lab); try again when it has finished.` |
| manager | `expected_id` missing or not 64 hex | `Reopen the Impairments section and apply again.` (400) |
| manager | impairment change on a device not running | `<device> is not running. Impairments can be set only on a running device.` |
| manager | interface role management | `<interface> is the management interface; the manager reaches the device through it and never impairs it.` |
| manager | interface role internal | `<interface> is an internal interface of this device, not a lab link.` |
| manager | a second concurrent change on the lab | `Another impairment change on this lab is in progress; try again in a moment.` |
| manager | apply-plan on an unlinked lab / without a folder | `UNLINKED_SENTENCE` / `NO_FOLDER_SENTENCE` (existing) |
| manager | the fourth concurrent diagnostics call | `The manager is already asking the VM for diagnostics; try again in a moment.` (existing) |
| manager | an older helper | `This VM's manager tools need an update; ask your instructor or administrator.` (existing) |
| UI | Stop device on a device not running / Start device on a running one | `<dev> is not running` / `<dev> is already running` (disabled reasons) |
| UI | capability missing | `Not available on this VM — its containerlab or helper cannot <start|stop> one device (see Diagnostics)`; the Impairments section and the options fold are simply absent |

Removed dead ends (each a refusal or impossibility today): "power down one router to watch the others react" (lab-wide
Stop or a restart only) → Stop device and Start device; "add latency or loss to a link" (nothing) → Impairments; "which
links are impaired after a reload" → the map class and caption; "Apply shows a generic danger review" → the plan with
reasons, Nothing to apply, Apply anyway; "nothing tells the student the running lab is out of date" → the pending
banner, once per open; "bring up half a lab on a small VM / remove one heavy node" → Choose devices (on an undeployed
Start lab; on Destroy); "cap parallel VM creation" → Max workers; "save one device's startup configuration" → the
drawer action. Refusals kept on purpose: a partial deploy of a running lab (containerlab would delete the rest; Apply is
the way); Clean up with chosen devices; impairments on `eth0`; a lab-wide `netem show` (does not exist).

## 8. Assumptions, what to attack, questions for the reviewers

**Assumptions.** (a) containerlab ≥ 0.79 for the dry run's JSON keys and for `--node` on start/stop; an older VM
answers "unsupported" through the probes and the page hides the controls. (b) The `interfaces` role rule of C03 is
right for every supported kind's data interfaces (verified live for cEOS, vJunos, cJunosEvolved, XRv9k in C03). (c)
`in_host_network` is a sound test for `network-mode: host` nodes (it compares `ns/net` inodes with pid 1's). (d) A
netem qdisc set on a veth end is removed with the veth (a redeploy or a lost link clears it): the pending check and
the map re-read after every operation, so a stale badge lasts at most until the next read. (e) The guard's
`content-length` rule means every impairment call is a POST with a body; there is no DELETE.

**Attack this.** (1) §1.2 as amended after the review: a netem change under the shared non-blocking flock, with a
digest over `{mode, name, options, expected_id}` and the `expected_id` check, but without the preview/run pair (no
`inspect --all` before and after). Is anything the pair proves (the affected container's state at review time)
missing here in a way that matters, given `container_of` and `expected_id` bind the container at execution and the
manager's `guard()` refuses in both directions? (2) `impairment_target`'s fail-closed branches: can a running
container legitimately have no bindable `/proc/<pid>`, an empty `HostConfig.NetworkMode`, or an `ns/net` the helper
cannot stat, and leave impairments unusable on a healthy VM? (3) The `nodes` validation on an undeployed `deploy`
relies on the manager's parse and on containerlab's own refusal (F10): is "exit 1 before anything is created"
guaranteed, or can a partial folder appear? (4) The plan in the digest: a reason text containerlab renders with a
changing detail (a timestamp, an image digest) would make every confirm fail; the live reasons seen are `added link`
and `config drift: Env`, and the lists are sorted before hashing. (5) `--max-workers 0` is accepted by containerlab
and refused here: right call? (6) The in-flight set makes a preview wait out an impairment call of up to 42 s in the
worst case: is a 409 the right answer for that window, or should the preview wait up to a few seconds? (7) The
`expected_id` round trip: the drawer learns the id from C03's `/netem` answer; a drawer left open across a redeploy
sends the old id and is refused with the reopen sentence; is there a path where it sends a *new* id it never showed?
(8) `apply` is deploy's alias: if a later containerlab gives `apply` its own command with different flags, the
helper's `help('deploy')` probe for `--dry-run` is the wrong probe; a test pins the alias assumption to a version
check. (9) The Partially running banner now prefers Review changes… over Start when the plan lists a device to create:
is a lab with one stopped device and one destroyed device served well by that order?

**Questions for `risk-reviewer`**: the §1.2 reading as amended; whether `lab.impairment` events may carry the numeric
values (they are validated numbers, no text from the VM); whether `SHOW_ALL_DEADLINE` at 60 s is the right bound.
**For `clab-ui-reviewer`**: the inline question versus a dialog for Apply (§4.1); the Partially running banner's new
order (Review changes… before Start when a device must be recreated); the two Run with options help lines; whether
Stop device belongs beside Restart device in the danger styling or above it.

## 9. Review answers

`/clab-design-review` (nos: false; `risk-reviewer` and `clab-ui-reviewer`, two refuters each): 30 confirmed (3 must-fix,
21 should-fix, 6 optional), 8 refuted. One row per confirmed finding, in the review's order; every smallest fix is
accepted as written, with the lead's choice where a finding offered two. The refuted eight (unsorted lists in the apply
digest; impairments surviving Stop/Start/Restart; the readiness summary and the new states; the check order and "runs
nothing"; Stop device on a `restarting` container; the filtered deploy's safety resting on `source_hash`; Try again on a
stopped filtered deploy; the pending line after a deliberate Stop device) need no answer, except that the first is
now moot (lists are sorted before hashing, §2.6) and the second is carried into live-pass step (7).

| # | Finding (severity, title) | Disposition | Sections changed |
|---|---|---|---|
| 0 | must-fix: the tests and acceptance checks contradict the flock amendment | Accepted: one shared `locked()` helper in `main()` for `preview`, `run`, `netem-set`, `netem-reset` (`LOCK_EX|LOCK_NB`), every other mode without a lock; the §1.2 lead-in and the "flock buys nothing" argument rewritten; the held-lock test added (`LOCK_SENTENCE`, nothing runs) | §1.2, §2 intro, §2.2, §2.3, §2.10, §5 helper, §6 S1 |
| 1 | should-fix: the host-network guard fails open | Accepted: `{{.HostConfig.NetworkMode}}` read in the same inspect, `host` and `container:*` refused, missing refuses; the namespace check is tri-state and unknown refuses; `interface_role`'s docstring rewritten as a guard; both pinned | §1.3, §2.1, §5 helper, §7 |
| 2 | should-fix: the impairment digest binds nothing the helper observed | Accepted: digest over `{mode, name, options, expected_id}`; `expected_id` is the container id the drawer showed (C03's `facts.id`) and the helper refuses when `container_of()['id']` differs, with the reopen sentence; §7 rows added | §1.2, §2.1, §2.2, §2.3, §2.10, §3.4, §4.1, §5, §7 |
| 3 | should-fix: the host-wide flock lets an impairment fail another lab's confirmed job; busy wording wrong | Accepted: in-flight impairment calls register in a set `LabOperations.guard()` checks, so preview and confirm answer 409 instead of a failed job; the lock sentence in the drawer reads "Another lab operation is running on the VM (it may belong to another lab); try again when it has finished." | §1.2, §2.10, §3.4, §4.1, §5 manager, §7 |
| 4 | should-fix: `GET /apply-plan` caught by `/{job_id}` | Accepted: the route is declared in `impairments.py` (installed before `LabOperations`), with the httpx test that it never reaches the job route | §3.3, §5 manager, §6 S2 |
| 5 | should-fix: the `nodes` membership rule leaves out the empty-prefix form | Accepted: one shared `container_matches()` used by `node_selector` and the membership check; empty-prefix test | §2.1, §2.8, §5 helper |
| 6 | should-fix: Start device's neighbour note wrong for a destroyed neighbour | Accepted (with 22): `restart_links` returns absent neighbours separately; the destroyed-neighbour sentence names Apply; tests | §3.1, §3.5, §5 manager, §6 docs |
| 7 | should-fix: the pending banner's identity is `checked_at` | Accepted (with 17): identity is a digest of the public plan (sorted lists and reasons); same plan stays dismissed, a different one shows | §4.4, §5 UI |
| 8 | should-fix: the automatic dry run shown safe only on a deployed lab with images; the error line is likely an INFO line | Accepted: F12 (undeployed lab, missing image: nothing created or pulled) and F13 (stderr order) verified live and added; every dry-run argv carries `--dry-run` (one builder, one pin); `error_line()` takes the line after `ERROR`, else `Failed`/`ERRO`, else the last line | §0 F12, F13, §2.6, §2.7, §3.3, §5 helper |
| 9 | should-fix: `netem-show-all` and Clear all have no total budget and fail with 0 or more than 64 devices | Accepted: helper-side 60 s deadline with `unread`/`complete`; the manager splits into calls of 64 or fewer and skips the call when there are no pairs; GET and clear timeouts named; Clear all stops at its 120 s budget and reports `cleared`, `total`, `failed`, `remaining` (wording in 27) | §2 intro, §2.4, §3.4, §4.1, §4.3, §5, §7 |
| 10 | optional: the value rules in the helper and the UI disagree | Accepted: jitter limited to 60 s too, leading zeros normalised in the UI and refused by the helper's pattern, `-0.0` normalised before rendering, one shared JSON case table for the three validators | §2.2, §4.1, §5 (all three layers), §6 S1 |
| 11 | must-fix: the pending banner never appears on a Partially running lab, and Start cannot recreate a destroyed device | Accepted: the attention branch for Partially running uses the cached plan: Review changes… as the action and `opPlanSummary` as the detail when the plan has `added`, `recreated` or `endpoints_removed`; Start kept only for a `started`-only or absent plan; banner-harness test | §4.4, §5 UI, §8 (9) |
| 12 | must-fix: Try again, the history and the banner treat a filtered destroy or save as the whole-lab action | Accepted: the validated node names are a public field `nodes` on the job; titles, history and the header name the devices (`Destroy ceos in <lab>`); `opRetryRequest` rebuilds from it (no `cleanup` for a filtered destroy) or returns null; fallback test without a stored request | §3.1, §3.2, §3.5, §4.2, §5 manager and UI |
| 13 | should-fix: the review's generic lines are wrong for Stop device, Start device and an empty Apply plan | Accepted: every `NODE_ACTIONS` action treated as `restart-node` in the three lines with a per-action affected line; the loss and disconnect lines dropped when `plan_changes(plan)` is false; pinned | §4.2, §4.4, §5 UI |
| 14 | should-fix: with capabilities not loaded the controls show false "Not available" or are missing | Accepted: unknown capabilities count as available (Restart's rule), the click re-checks after `opCapabilities()`; opening the section and `opReview` for deploy/redeploy/destroy/save call `opCapabilities()` first (also from `opQuickRun('start')`) | §4.1, §4.2, §4.5, §4.6, §5 UI |
| 15 | should-fix: the 4-second poll would wipe the section's typed values, focus and open question | Accepted: the section's markup is rebuilt only when `(activeId, detailName, answer)` changes; the poll toggles `disabled` and `title` only; after an operation it refreshes from the cache only when no row is edited and no question is open (else a Refresh line); `changed: false` wording | §4.1, §5 UI |
| 16 | should-fix: the busy refusals are VM- and manager-wide but the wording reads as this lab | Accepted (with 3): the lock sentence names another lab; both `guard()` sentences listed; the drawer treats all three as its busy state; the caption says impairments cannot be changed while any lab operation runs | §3.4, §4.1, §7 |
| 17 | should-fix: the pending banner's identity is the check time | Accepted (with 7): `opPlanIdentity(plan)`; tests | §4.4, §5 UI |
| 18 | should-fix: right after an operation the pending check can return the pre-operation plan; Sync is not a trigger | Accepted: the cache is dropped before the terminal `update()` (and in `finish_stopped`); a successful Sync topology from VM drops it and is a browser trigger; pinned in Python and in `opPlanTriggers` | §3.3, §4.3, §5 manager and UI, §6 S2 |
| 19 | should-fix: re-running the preview on every option change races the host lock and itself | Accepted: the fold is disabled with `Checking…` during a re-preview, a sequence number drops stale answers, the number input re-previews on `change`, the plain defaults return when no device is chosen; tests | §4.5, §5 UI |
| 20 | should-fix: the map caption counts interfaces as links; the map does not say which end | Accepted: the caption counts the wires `impairedWires()` matched (interfaces in the title and in the Clear question); the wire title and `aria-label` name the end and direction; re-applied from the cache after every map render | §3.4 (`interfaces`), §4.3, §5 UI |
| 21 | should-fix: read-back values in containerlab's format would disable Apply on an untouched row | Accepted: the manager's public rows normalise durations to whole milliseconds and percentages to two decimals; fixture and unit cases for `60s`, `1.5s`, `1m0s`, `33.333` | §3.4, §4.1, §5 manager and fixture |
| 22 | should-fix: Start device's neighbour note reuses Restart's words and is wrong for a destroyed neighbour | Accepted (with 6): per-action verb; the `absent` branch with its own sentence; test with an absent neighbour | §3.1, §5 manager |
| 23 | should-fix: students are sent to Apply topology changes, which is only inside All lab operations… | Accepted: **Apply topology changes…** in Lab actions ▾ (`data-op-action="apply"`), enabled on Running and Partially running through `renderLabOperations`' rule; the guide's menu paragraph lists it | §4.4, §5 UI, §6 docs |
| 24 | should-fix: adding the node actions to `opPlainRetry` makes Try again send them without a device | Accepted: the three node actions share the `restart-node` branch of `opRetryRequest` and stay out of `opPlainRetry`; tests for `start-node` and `stop-node` without a stored request | §3.2, §4.2, §5 UI |
| 25 | optional: "Stop device" and "Stop devices" differ by one letter | Accepted: node-job titles, toasts, history and header name the device (`Stop ceos`, `✔ ceos stopped`) through `opJobLabel` / `operationLabel`; filtered jobs likewise through `nodes` | §3.1, §4.2 |
| 26 | optional: the caption's claim about how long impairments last is not verified | Accepted: live-pass step (7) impairs, then Restart device, Stop/Start device and Redeploy, re-reading each time; the caption is worded as "can remove them; the map re-checks after each operation" until that result exists | §4.1, §6 live pass and docs |
| 27 | optional: Clear all's partial failure and in-progress states are unsaid | Accepted: `2 of 3 interfaces cleared; Ethernet3: <reason>. Try again.` (and the budget variant), `Clearing…` while it runs, `/clear` runs inside the guard and the per-lab lock, the button reads **Clear impairments** | §3.4, §4.1, §4.3 |
| 28 | optional: §2.10 and §3.4 disagree on whether the impairments read is guarded | Accepted: `GET /impairments` is a read, unguarded like C03's reads, so the fetch after a job turns terminal is answered while `finally` still holds `self.active` | §2.10, §3.4, §4.3, §5 manager |
| 29 | optional: Graceful stop plus low Max workers can outrun the job's time limit | Accepted: the Graceful help says the wait is per device and adds up; a review notice appears when graceful with `max_workers` below the device count puts the estimate past the run limit | §4.5, §5 UI |
