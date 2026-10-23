# C03 design: read-only diagnostics through the operations helper

Rows R020 (container logs), R028 (interface list), R029 (one counter sample), R030 (containerlab version),
R013 (inspect table extras), R091 (lab-folder files), R100 (image size and age). Written against
`claude/parity-campaign` at `becc525` (release 1.31.1, containerlab 0.79.0 on the VM). Everything here is
read-only: no mode starts, stops, writes, pulls or execs anything. C05 (impairments) builds on `interfaces`
and `netem-show`; C06 (link colours) on `interfaces`; C04 (container facts) on the facts these modes return.

## 1. Decisions in one place

1. **Five helper modes outside the host lock**, dispatched like `images` / `image-check` (`host_operations.py:702-703`):
   `logs`, `interfaces`, `netem-show`, `browse` with a `files` option, and `images` extended. They never take the
   flock because they change nothing and their value is highest exactly while `preview`/`run` holds it (a boot log
   during a deploy). The only shared resources are Docker and containerlab CPU; each mode is bounded by its own
   timeout and the manager admits at most three diagnostics calls at once (§3).
2. **The browser never names a container or a lab.** It sends `lab_id` and the manager's `node` name; the manager
   derives the lab name from `lab['deployment_name']` and the container from `expected_container(lab, node)`
   (`discovery.py:216`), the one formula the helper's `node_selector()` already binds. A device without a topology
   node name (an inventory-only device, a lab with no deployment name) gets a plain sentence, not a helper call.
3. **One binding check per call on the helper**: `docker inspect` of the named container with a fixed format; the
   `containerlab` label must equal the lab name and `clab-node-name` the node, or the mode refuses. It is one cheap
   Docker call instead of `containerlab inspect --all` (25 s class, a Docker inspection per container), which would
   make a 5-second log follow unaffordable.
4. **Logs are transient**: redacted on the manager, returned to the browser, never written to the Store, a job, an
   event or a server log. Export is a browser download of the redacted text.
5. **`interfaces` is lab-wide**: one `containerlab inspect interfaces --name <lab>` per call; the manager picks the
   node's entry. One call feeds the drawer, C06's link colours and C05's selectors, and it sidesteps a `-n <node>`
   quirk seen live (`-n vsw` answered "no containers found" while the lab-wide call listed the node).
6. **Counters come from `/proc/<pid>/net/dev`** of the container's init process (pid from the same `docker inspect`,
   bound to the container by its cgroup line), never from `docker exec`, `nsenter` or `containerlab events`
   (a streaming command that does not fit the read-to-EOF protocol). The browser computes rates from two samples.
7. **Not disabled while an operation runs.** The sections stay usable during a deploy; the states say when a
   container does not exist yet.
8. **PID and ports are not in the inspect table**: containerlab 0.79.0's `inspect --all` JSON carries `container_id`
   and `owner` but neither (verified live). They are container facts of one device (`facts` in §2.1) and C04 shows
   them in the drawer; the table gets ID, owner, sort and a filter box.
9. **Wildcard search is not implemented**: the inspect filter is a case-insensitive substring. Students type words;
   the upstream `* ? #` grammar with a regex fallback is a foot-gun for a filter box of ten rows.

## 2. Helper modes (`clab-backup-ui/app/host_operations.py`)

All run through `self.run` (= `capture`, stderr discarded) or a new `self.run_merged` (`capture` with
`stderr=subprocess.STDOUT`, only for `logs`); fixed argv; the only client inputs are the validated lab name, node,
container, a tail count and a `since` stamp. A refused request runs nothing. `main()` adds one `elif` per mode
and nothing else; `test_main_dispatches_the_two_modes_and_nothing_wider` grows to name all of them.

### 2.1 `container_of(options, lab)` — the shared binding check

`node, container = node_selector(options, lab)` (shape), then
`[DOCKER, 'inspect', '--format', '{{.Id}}\t{{.State.Pid}}\t{{.State.Status}}\t{{.State.StartedAt}}\t{{with .State.Health}}{{.Status}}{{end}}\t{{index .Config.Labels "containerlab"}}\t{{index .Config.Labels "clab-node-name"}}\t{{index .Config.Labels "clab-node-kind"}}\t{{json .NetworkSettings.Ports}}', container]`
with `probe()` (12 s). Exit 1 with "No such" → `{'present': False}` (not an error: the device may not be deployed
yet). Label `containerlab` != lab or `clab-node-name` != node → `ValueError('This container does not belong to lab
<lab>.')`. Returns `facts = {present, id, pid, status, health, started, kind, ports}` where `ports` is reduced to
`[{container: '22/tcp', host: '2201'}]` (host port digits only). Every mode below returns `facts` beside its own
result, so C04 needs no new mode.

### 2.2 `logs`

- Request `{'mode': 'logs', 'name': <lab>, 'options': {'node', 'container', 'tail': int, 'since': str?}}`;
  option keys exactly these. `tail`: integer 1..2000 (`LOGS_TAIL_LIMIT`). `since`: `^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d{1,9})?Z$`,
  from a timestamp the helper itself returned; anything else refused.
- argv `[DOCKER, 'logs', '--tail', str(tail), '--timestamps', *(['--since', since] if since else []), container]`,
  `run_merged`, timeout 15 s, limit `LOGS_LIMIT = 512 KiB` (over the limit: the last 512 KiB, cut at a line, `truncated: True`).
  vJunos-switch's full log is 32 KiB, XRv9k's 137 KiB (live), so 2000 lines fit.
- Result `{'facts', 'text': <raw bytes decoded, errors='replace'>, 'truncated'}`. The helper does not redact: the
  manager holds the secrets (§3). The helper strips nothing either, so a review reads one redaction path.

### 2.3 `interfaces`

- Request `{'mode': 'interfaces', 'name': <lab>, 'options': {'node', 'container'}}`.
- argv `[self.clab, 'inspect', 'interfaces', '--name', lab, '-f', 'json']`, timeout `INSPECT_TIMEOUT` (25 s), limit
  `INSPECT_LIMIT`. Output that is not a JSON list (containerlab prints "no containers found" as text, exit 0) →
  `{'present': False}`. The entry whose `name` equals the container is kept; interfaces are reduced to
  `{name, alias, state, mac, mtu, type, ifindex}` with types checked (strings ≤ 64, ints), at most 256 per node.
- Counters, only when `facts['pid'] > 0`: `/proc/<pid>/cgroup` must contain `facts['id']` (else counters are
  left out with `counters_reason: 'pid'`), then `/proc/<pid>/net/dev` is read (64 KiB cap) and parsed into
  `{name: {rx_bytes, rx_packets, rx_errors, rx_dropped, tx_bytes, tx_packets, tx_errors, tx_dropped}}` for the
  listed interface names only; `sampled_at = time.time()`. No `docker exec`, no `nsenter`, no shell.
- Result `{'facts', 'interfaces': [...], 'counters': {...}, 'sampled_at'}`.

### 2.4 `netem-show`

- Request `{'mode': 'netem-show', 'name': <lab>, 'options': {'node', 'container'}}`.
- argv `[self.clab, 'tools', 'netem', 'show', '-n', container, '-f', 'json']`, timeout 15 s. Live on 0.79.0 a node
  without impairments answers `{"<container>": null}`. The helper returns `{'facts', 'impairments': []}` for null or
  missing, else the list for the one container reduced to `{interface, delay, jitter, loss, rate, corruption}` with
  values as strings/numbers only, unknown keys dropped. **Assumption**: the non-null shape is a list of objects
  keyed as containerlab's `netem set` names them; C05 confirms it live before it is drawn as more than a table.

### 2.5 `images` (extended, contract kept)

argv `[DOCKER, 'image', 'ls', '--format', '{{.Repository}}:{{.Tag}}\t{{.ID}}\t{{.Size}}\t{{.CreatedAt}}']`. The result
keeps `images: [reference]` exactly as today and adds `details: [{reference, id, size, created}]` (strings as Docker
prints them: `4.53GB`, `2026-10-23 02:03:42 +0000 UTC`; the manager normalises `created` to ISO). `lab-builder-page.js`
reads `images` only, so an old helper without `details` keeps working.

### 2.6 `browse` with `files`, and `read`

- Request `{'mode': 'browse', 'path', 'options': {'files': true}}` (the only option). Without it, unchanged.
- With it, entries also include regular files (no dot-files, no symlinks, `is_file()` after `lstat`) whose
  suffix is in `READABLE = ('.yaml', '.yml', '.json', '.drawio', '.txt', '.cfg', '.conf', '.set', '.md')` or whose
  basename is exactly `startup-config` or `juniper.conf` (the names containerlab's lab directory uses), each with
  `size` and `kind: 'topology' | 'file' | 'directory'`, 500 entries in all. Never listed: anything else (keys,
  certificates, `.env`, binaries, `.sh` hooks).
- `read` accepts the same set (today's suffix list plus `.md` and the two basenames), 1 MiB, path rules unchanged.

### 2.7 `capabilities`

Adds `'containerlab': <version>` from `[self.clab, 'version', '--short']` (32 ms live, no network; kept only when
it matches `^\d+\.\d+\.\d+`), and `'diagnostics': True` so the manager can tell this helper from an older one
without a failed call.

## 3. Manager side (`clab-backup-ui/app/lab_operations.py`)

- `LabOperations.diagnostics_slots = threading.BoundedSemaphore(3)`; `diagnose(req, timeout)` acquires it without
  blocking, else `HTTPException(503, 'The manager is already asking the VM for diagnostics; try again in a moment.')`;
  then `remote(self.host(), req, timeout=timeout)` (EOF rule unchanged: `remote()` already waits for stream EOF),
  errors mapped as `invoke()` maps them (a `ValueError` text, else the gateway sentence). The VM-connection
  preconditions in `remote()` give the existing "Configure and enable the VM connection first" wording.
- `target(lab_id, node)` → `(lab, node_row, deployment_name, container)`; HTTP 404 for an unknown device, HTTP 409
  `'This device has no container the manager can name (it is not a node of a deployed topology).'` when
  `expected_container` is `''`.
- `strip_escapes(text)`: CSI `\x1b\[[0-?]*[ -/]*[@-~]`, OSC `\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)?`, two-byte
  `\x1b[@-Z\\-_]`, `\r`, and every C0 control except `\n` and `\t`. Then `scrub(text, state)` unchanged
  (`lab_operations.py:223-226`: stored secrets, private keys, the `password|passphrase|private key|community|secret`
  line rule that turns vrnetlab's `PASSWORD: …` lines into `[sensitive output omitted]`). `scrub` itself is not
  changed: its behaviour on persisted job output is pinned by tests.
- Routes (same-origin guard, bodies are JSON objects):
  - `POST /api/operations/logs {lab_id, node, tail?, since?}` → `{container, present, lines: [{at, text}], truncated,
    fetched_at}`; `at` is the `--timestamps` prefix, `text` the redacted rest; lines without a parsable stamp keep
    `at: ''`. Helper timeout 15 s, `remote` timeout 30 s. Nothing is stored; no `Store.event`.
  - `POST /api/operations/interfaces {lab_id, node}` → `{container, present, facts, interfaces: [{..., port, role}],
    counters, sampled_at}`. `port` is the NOS name from `topology.PORT_RULES` reversed (`ethN` → `ge-0/0/(N-offset)`,
    `''` for kinds without a rule); `role` is `management` for `eth0`, `internal` for a name that matches neither
    `eth\d+` nor `e1-\d+` (cEOS's `cpu`, `fabric*`, `arpsnoop`), else `data`. `remote` timeout 45 s.
  - `POST /api/operations/netem {lab_id, node}` → `{container, present, impairments}`; `remote` timeout 30 s.
  - `GET /api/operations/images` keeps its shape and adds `details` (cached with it for a minute).
  - `POST /api/operations/browse` gains optional `files: bool`; `POST /api/operations/view {path}` = helper `read`
    then `strip_escapes` + `scrub` (a `juniper.conf` carries password hashes). `/api/operations/read` is untouched:
    `opEdit` parses topology text and must see it exact.
  - `GET /api/operations/capabilities` passes `containerlab` and `diagnostics` through; `diagnostics.py` adds
    `containerlab_version` to its capabilities check item.
- Public views: `facts` is copied field by field (`id`, `pid`, `status`, `health`, `started`, `ports`); the raw helper
  result is never returned. Never returned or stored: raw log text, the VM path of the lab directory, labels other
  than the two checked, counters of any interface not in the list.

## 4. The UI

### 4.1 Device drawer: Interfaces and Logs (`device-diagnostics.js`, new; `index.html`; `style.css`)

Two `<details class="drawer-section">` after `#details-info` in the drawer, closed by default so an open drawer
asks the VM for nothing until a student opens a section. `renderDetails()` (app.js:467) calls
`if(typeof renderDeviceDiagnostics==='function')renderDeviceDiagnostics(n)`; that hook only resets the sections
when `detailName` changed (Previous/Next) and updates the disabled reason; the 4-second poll never rewrites a
section's body, so a log being read and a find box keep their content and focus.

**Interfaces** (`summary` "Interfaces"): table Name · Port · State · MAC · MTU · Type · RX · TX, data interfaces
first, management row labelled "eth0 · management (used by the manager; never impaired)", internal ones under a
"Other interfaces (n)" `<details>`. RX/TX show bytes and, from the second sample on, a rate (`B/s`, `kB/s`, `MB/s`)
from `(now.bytes - prev.bytes) / (now.sampled_at - prev.sampled_at)`. A data row with `port` gets a **Capture** button
calling `openCapture(n.name, port || name)` (capture stays one click away, zero regression). Impairments from
`/netem` appear as a line under a row ("delay 15ms · loss 5%"); none → nothing. The section polls `/interfaces`
every 5 s while it is open, the drawer is open and `pageVisible()` (shell.js, new one-liner on
`document.visibilityState`) is true; `/netem` once per open and after every operation of this lab finishes.

**Logs** (`summary` "Logs"): toolbar Tail (200 default, 1000, 2000) · Refresh · Follow (toggle) · Find (text input,
"n of m lines", matching lines only while non-empty) · Export; a `<pre class="op-code">` of `at text` lines, newest
at the bottom, scrolled to the end on Refresh and while following. Export builds a Blob of the shown (redacted)
text and saves `<lab>-<device>-logs-<UTC stamp>.txt` through an `<a download>`; nothing goes to the manager.

Follow: first request with `tail`, then every 5 s with `since` = the `at` of the last line received (lines with
`at` ≤ that stamp are dropped, `--since` is inclusive); appended lines are capped at 2000 in the DOM (oldest
dropped, a "Older lines dropped" caption). Stops when: the toggle is switched off, the section is closed, the drawer
closes or switches device, the tab is hidden (resumes on return with one full `tail` fetch, not a backlog), 30 minutes
have passed ("Follow paused after 30 minutes. Resume"), or three consecutive errors ("Follow stopped: <message>.
Resume"). A 503 from the manager doubles the interval up to 30 s and halves it back on success. A `present: false`
answer is not an error: the body reads "No container for this device yet (deploy the lab, or wait for the deploy to
create it)" and the follow keeps polling, which is the boot-log case.

States (both sections): default "Open to load"; loading "Asking the VM…" with the previous content kept;
empty (logs) "The container has written nothing yet"; empty (interfaces) "No interfaces reported"; error:
the manager's sentence, verbatim, plus Retry (`Operations helper is unavailable or outdated. Run start-manager.sh
--enable-operations on the VM.` is `remote()`'s own text for an old helper; the `diagnostics` capability flag lets the
drawer say "This VM's helper predates diagnostics; run start-manager.sh --enable-operations on the VM" before the
first call); disabled: not while an operation runs (§1.7) but the reason sentence for a device without a container
name (§3); reconnect: a VM that was unreachable comes back on the next poll with no manual step.

### 4.2 Inspect table (`operations.js`, `opInspectionRows`, `opInspectionTable`)

Rows gain `id` (first 12 of `container_id`) and `owner`; columns Device · ID · Owner · Type / image · State / health ·
IPv4 / IPv6 · Topology. Headers are buttons with `aria-sort`; sort state and the filter text live in the dialog, not
in `state`. The filter box ("Filter devices") hides rows whose joined text lacks the substring; the caption reads
"n of m devices". `opInspectionSort(rows, key, dir)` and `opInspectionFilter(rows, text)` are pure (tested).

### 4.3 Containerlab version (`operations.js`, `index.html`, `debug.js`)

The Manager menu footer gets `<span id="clab-version" hidden>`; `renderLabOperations()` fills it with
`containerlab 0.79.0` when `opCaps.containerlab` is known (the footer already renders on `menuopen`). Diagnostics
shows "containerlab 0.79.0" in the capabilities row.

### 4.4 Lab files (`operations.js`, `opBrowse`)

Opened with a `labId` ("Lab files · <lab>"), the browser asks `browse` with `files: true`, lists every readable file
with its size (`◇ ceos.cfg · 2.1 kB`), topology files first; a non-topology file opens `opView(path)`: the
read-only `op-editor` dialog titled "File on the VM", text from `/operations/view`, a Copy button when C02's
`copyText` exists, no Deploy/Add buttons. "Deploy a new lab…" (no `labId`) is unchanged: topology files only.
The help line under the tree says which it is: "Files the manager can show (text and configuration files). Other
files on the VM are not listed."

### 4.5 Images on this VM (`operations.js`, Manager menu)

A menu item **Images on this VM…** opens a dialog with a filter box and a table Reference · Size · Created · Used by
(labs from `/known-images`) with chips All / Used by my labs / Missing (named by a lab, not on the VM), and a
caption when `details` is absent: "Size and age need the updated VM helper." Nothing is pulled or removed.

## 5. Version lockstep and tests

A helper change is a release: `deploy/set-release.py` moves `VERSION` and the helpers' `VERSION`/`helper_version`;
every VM runs `sudo bash deploy/start-manager.sh --enable-operations` (the `--refresh` path) before the new modes
answer, and until then `remote()`'s "unavailable or outdated" sentence is what the drawer shows (§4.1).
The gateway is **not** changed: the new modes are request lines on the existing `clab-manager-operations` name, so
`test_gateway_whitelist.py` extends only by a test that reads `host_operations.py` and asserts the dispatch adds no
new request name and no shell (`HELPERS`, `ARMS` and `REFUSED` unchanged; a reviewer confirms the diff touches no
line of `deploy/clab-manager-gateway`).

`test_lab_operations.py`:
- `DiagnosticModeTests` (copy `ImageModeTests`): the exact argv of each mode with a stub `docker` and `clab`;
  refusals (bad tail 0/2001/"10", bad `since`, a container of another lab, a label mismatch, an option outside the
  whitelist, a selector shape `node_selector` refuses) run nothing; `present: False` for "No such container" and for
  non-JSON interface output; counters left out when the cgroup line lacks the id; `netem` null → `[]`; `images`
  keeps `images` and adds `details`; `browse` with `files` lists only readable names, skips dot-files and symlinks,
  carries `size`, and without the option is unchanged (`test_browser_filters_non_topologies_before_entry_limit` kept);
  `read` accepts `startup-config` and refuses `id_rsa`, `.pem`, `.env`; `capabilities` carries `containerlab` only
  when it parses; `main()` dispatches exactly the named modes and no `DOCKER, 'exec'`/`'logs', '-f'` appears.
- `OperationAPITests`: `/logs` with a patched `remote` returns redacted lines (a stored password, a `PASSWORD:` line,
  CSI/OSC sequences, `\r`), stores nothing (the Store's JSON and the event log contain no log text, no `facts`),
  refuses an inventory-only device with the sentence, caps lines at 2000, passes `since` through unchanged and refuses
  one the browser invented; `/interfaces` adds `port` and `role` (eth0 management; cEOS `cpu` internal; vJunos
  `eth1` → `ge-0/0/0`; XRv9k `eth1` → `Gi0/0/0/0`); the fourth concurrent diagnostics call is a 503; `/view` scrubs;
  `/read` is byte-exact; `/images` tolerates a helper without `details`.
- `test_device_diagnostics_ui.js` (new, `test_operations_ui.js` harness): `diagLogLines` parsing and the `since`
  cursor, `diagFilter`, `diagRate`, the follow plan (interval, back-off, every stop condition as a pure state
  function `diagFollowNext(state, answer)`), the export name, management/internal grouping; `test_operations_ui.js`
  gains sort and filter cases; `test_page_load_ui.js` and `test_debug_ui.js` run unchanged plus the footer span.
- Fixture pass (`clab-ui-qa`): `fixture_manager.py` learns the five modes with scripted answers; a Playwright check
  opens the drawer, both sections, Follow for two polls, Find, Export (a download event), the inspect filter, the
  files list and the viewer at 1440/1280/760/390. Live pass on the `parity` lab: a vrnetlab boot log while the
  container is unhealthy, the Junos port names, a 5-second counter rate during a ping.
- CI: the lead appends `test_device_diagnostics_ui.js` to the `node --test` line.

## 6. Questions for `risk-reviewer`, explicit

1. **Device console text in container logs.** `docker logs` of a vrnetlab container carries the NOS serial console
   (`launch TRACE OUTPUT: …`), that is device output read through a helper. The claim that this is not "device work":
   the helper runs a fixed read-only Docker client command against the container runtime, sends nothing to the
   device, opens no session on it, and the text is the same stream `docker logs` shows any VM administrator; device
   *access* stays on direct node SSH. Accept, or require the manager to drop `TRACE OUTPUT` lines?
2. **Exact argv per mode** (§2.2-2.7) and `probe()`'s `docker inspect` format string: confirm each has one variable
   element at most (the validated container / lab name / tail / since), none at argv[0..1].
3. **`/proc/<pid>/net/dev` with the cgroup binding**: is pid reuse between `docker inspect` and the read a risk worth
   more than "counters left out when the cgroup does not name the container"? Alternative is dropping counters.
4. **Path rules of `browse files` and `read`**: the suffix and basename whitelist, dot-files and symlinks skipped
   through `lstat`, 500 entries, 1 MiB; `view` scrubbed, `read` exact. Is listing `juniper.conf` (password hashes
   scrubbed by the line rule) acceptable, or should `view` refuse it?
5. **Three concurrent SSH sessions** from one manager to `clab-discovery` (discovery's own plus up to three
   diagnostics): any sshd `MaxStartups`/`MaxSessions` concern on the installed VM?
6. The `logs` mode merges the container's stderr into the result (`run_merged`); the `images`/`image-check` precedent
   discards stderr. Acceptable for a read-only text answer?

## 7. Assumptions, removed dead ends, what to attack

Assumptions: containerlab ≥ 0.64 for `inspect interfaces` (0.79.0 installed; an older VM answers "unknown command"
and the section shows the helper's own sentence); `docker logs --since` accepts RFC 3339 with nanoseconds (Docker's
own `--timestamps` form); the containerlab labels `containerlab` and `clab-node-name` are set on every lab
container (verified on `clab-parity-ceos`); C02's `copyText` may or may not be merged first (Copy buttons appear only
when it exists; nothing else depends on C02).

Dead ends removed: a vrnetlab device that reads *Starting* for ten minutes with no explanation (the boot log is
readable during the deploy); a link that looks the same up or down (state per interface, port names joined);
"which veth is `ge-0/0/2`" (the Port column); a startup configuration next to the topology that needed SSH to the
VM to read; a VM full of images nobody can size; "which containerlab is this" for support.

Refusals kept as refusals: a container not labelled for this lab; any file outside the whitelist; a tail over 2000;
any write. New refusal, with its sentence: diagnostics for a device the manager cannot name a container for.

Attack: the label check (can a container of lab B be read by naming lab A, given `node_selector` accepts
`<prefix>-<lab>-<node>` for any prefix?); the `since` regex and `--tail` as the only way a number reaches argv; the
redaction order (escapes stripped *before* the line rule, so a coloured `PASSWORD:` line still matches); whether any
route or helper path logs the text (`Store.event`, uvicorn access logs carry no body; `remote()`'s error text is
capped at 1000 chars of the helper's `error`, never of `result`); the follow's stop conditions and the DOM cap; the
inspect filter never escaping into HTML (`esc()` on every cell); C05 reusing `role` as the sole impairment guard.

## 8. Files to change
`clab-backup-ui/app/host_operations.py` (lead or `clab-fable-specialist`; `risk-reviewer` on the diff);
`clab-backup-ui/app/lab_operations.py`, `diagnostics.py` (`clab-backend-engineer` from this document);
`clab-backup-ui/app/static/device-diagnostics.js` (new), `operations.js`, `shell.js` (`pageVisible`), `app.js` (one
hook line), `index.html`, `style.css`, `debug.js` (`clab-ui-builder`); tests named in §5 (`clab-test-engineer`,
`clab-ui-qa`); `docs/LAB-OPERATIONS.md` (a "Diagnostics" subsection and the Lab files row), `docs/DEBUG-PANEL.md`
(the version line), `clab-backup-ui/NODE-FEATURES.md` (the drawer sections); `docs/redesign/tools/fixture_manager.py`.
Release records and the CI list: the lead.
