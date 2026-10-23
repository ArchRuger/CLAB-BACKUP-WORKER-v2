# C03 design: read-only diagnostics through the operations helper

Rows R020 (container logs), R028 (interface list), R029 (one counter sample), R030 (containerlab version), R013
(inspect table extras), R091 (lab-folder files), R100 (image size and age). Written against `claude/parity-campaign`
at `becc525` (release 1.31.1, containerlab 0.79.0 on the VM), amended after the design review (§9). Everything here
is read-only: no mode starts, stops, writes, pulls or execs anything. C05 (impairments) builds on `interfaces` and
`netem-show`; C06 (link colours) on `interfaces`; C04 (container facts) on the `facts` these modes return.

## 1. Decisions in one place

1. **Five helper modes outside the host lock**, dispatched like `images` / `image-check` (`host_operations.py:702-703`):
   `logs`, `interfaces`, `netem-show`, `browse` with a `files` option, and `images` extended. They never take the flock
   because they change nothing and their value is highest exactly while `preview`/`run` holds it (a boot log during a
   deploy). Each has its own timeout; the manager admits three calls at once (§3); the browser never overlaps its polls (§4.1).
2. **The browser never names a container or a lab.** It sends `lab_id` and the manager's `node` name; the manager
   derives the lab name from `lab['deployment_name']` and the container from `expected_container(lab, node)`
   (`discovery.py:216`), the formula the helper's `node_selector()` binds. A device the manager cannot name a container
   for gets a sentence with its way out (§3), not a helper call.
3. **One binding check per call on the helper**: `docker inspect --type container` with a fixed format; the
   `containerlab` label must equal the lab name and `clab-node-name` the node, or the mode refuses; the returned
   64-hex `Id`, not the name, is what `docker logs` reads. One cheap call instead of `containerlab inspect --all`
   (25 s class), which would make a 5-second log follow unaffordable.
4. **Logs are transient**: redacted on the manager per line, returned to the browser, never written to the Store, a
   job, an event or a server log. The three polled reads are GET routes, so the guard writes no `api.request` event
   per poll (`main.py:116-126` logs non-GET requests only). Export is a browser download of the redacted text.
5. **`interfaces` is lab-wide**: one `containerlab inspect interfaces --name <lab>` per call; the manager picks the
   node's entry. One call feeds the drawer, C06's link colours and C05's selectors, and it sidesteps a `-n <node>`
   quirk seen live (`-n vsw` answered "no containers found" while the lab-wide call listed the node).
6. **Counters come from `/proc/<pid>/net/dev`** read through one directory fd of `/proc/<pid>` (bound to the original
   task, so a reused pid cannot be read), never from `docker exec`, `nsenter` or `containerlab events` (a stream that
   does not fit the read-to-EOF protocol). The browser computes rates from two samples of the same container.
7. **Not disabled while an operation runs.** The sections stay usable during a deploy; the states say when a
   container does not exist yet or is stopped. One poll plan (chained, backed off, paused after 30 minutes) governs both.
8. **The inspect table keeps its six columns in their order** (OPS-48 and `verify_after.py:514` pin them) and
   appends ID and Owner. PID and ports are not in 0.79.0's `inspect --all` JSON (verified live); they are container
   facts of one device (`facts`, §2.1) for C04.
9. **Wildcard search is not implemented**: the inspect filter is a case-insensitive substring. Students type words;
   the upstream `* ? #` grammar with a regex fallback is a foot-gun for a filter box of ten rows.

## 2. Helper modes (`clab-backup-ui/app/host_operations.py`)

All run through `self.run` (= `capture`, stderr discarded) or a new `self.run_merged` (`capture` with
`stderr=subprocess.STDOUT`, only for `logs`); fixed argv; the only client inputs are the validated lab name, node,
container, a tail count and a `since` stamp. The lab name is `identity(req['name'])` with no default (unlike `plan()`'s
`'manager'`). A refused request runs nothing. `main()` adds one `elif` per mode and nothing else;
`test_main_dispatches_the_two_modes_and_nothing_wider` grows to name all of them.

### 2.1 `container_of(options, lab)` — the shared binding check

`node, container = node_selector(options, lab)` (shape), then
`[DOCKER, 'inspect', '--type', 'container', '--format', '{{.Id}}\t{{.State.Pid}}\t{{.State.Status}}\t{{.State.StartedAt}}\t{{with .State.Health}}{{.Status}}{{end}}\t{{index .Config.Labels "containerlab"}}\t{{index .Config.Labels "clab-node-name"}}\t{{index .Config.Labels "clab-node-kind"}}\t{{json .NetworkSettings.Ports}}', container]`
with `probe()` (12 s); `--type container` keeps Docker from resolving an image, volume, network or ID prefix of that
name. Exit 1 with "No such" → `{'present': False}` (not an error: the device may not be deployed yet). `Id` must
`fullmatch('[0-9a-f]{64}')`; label `containerlab` != lab or `clab-node-name` != node → `ValueError('This container
does not belong to lab <lab>.')`. Returns `facts = {present, id, pid, status, health, started, kind, ports}` (`ports`
as `[{container: '22/tcp', host: '2201'}]`, digits only); every mode returns `facts`, so C04 needs no new mode.

### 2.2 `logs`

- Request `{'mode': 'logs', 'name': <lab>, 'options': {'node', 'container', 'tail': int, 'since': str?}}`; option
  keys exactly these. `tail`: `type(tail) is int` (so `True` is refused) and 1..2000 (`LOGS_TAIL_LIMIT`). `since`:
  `re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d{1,9})?Z', value, re.ASCII)`, a shape check only (the helper
  keeps no state to recognise a stamp it issued); anything else refused.
- argv `[DOCKER, 'logs', '--tail', str(tail), '--timestamps', *(['--since', since] if since else []), facts['id']]`
  (three validated variable elements, none at argv[0..1]), `run_merged`, timeout 15 s, limit `LOGS_LIMIT = 512 KiB`
  (over it: the last 512 KiB cut at a line, `truncated: True`). A non-zero exit raises `'Docker on the VM did not
  return this container's log.'`, never its stderr as log text. Live logs are 32 KiB (vJunos-switch) to 137 KiB (XRv9k).
- Result `{'facts', 'text': <bytes decoded, errors='replace'>, 'truncated'}`; the helper neither redacts nor strips (§3).

### 2.3 `interfaces`

- Request `{'mode': 'interfaces', 'name': <lab>, 'options': {'node', 'container'}}`.
- argv `[self.clab, 'inspect', 'interfaces', '--name', lab, '-f', 'json']`, timeout `INSPECT_TIMEOUT` (25 s), limit
  `INSPECT_LIMIT`. Output that is not a JSON list (containerlab prints "no containers found" as text, exit 0) →
  `{'present': False}`. The entry whose `name` equals the container is kept and reduced to `{name, alias, state, mac,
  mtu, type, ifindex}` (strings ≤ 64, ints), at most 256 per node; a container that exists but has no entry (stopped:
  containerlab prints `[]`, verified live) answers `interfaces: []` with `facts`.
- Counters, only when `facts['pid'] > 0`: `fd = os.open(f'{self.proc}/{pid}', O_RDONLY | O_DIRECTORY)` (`self.proc`
  defaults to `/proc`; a test points it at a temporary tree); through that `dir_fd`, `cgroup` must contain
  `facts['id']`, then `net/dev` (64 KiB cap) is parsed into `{name: {rx_bytes, rx_packets, rx_errors, rx_dropped,
  tx_bytes, tx_packets, tx_errors, tx_dropped}}` for the listed names only; `sampled_at = time.time()`. Any `OSError`
  or cgroup mismatch leaves counters out with `counters_reason: 'pid'`. No exec, no shell.
- Result `{'facts', 'interfaces': [...], 'counters': {...}, 'sampled_at'}`.

### 2.4 `netem-show`

- Request `{'mode': 'netem-show', 'name': <lab>, 'options': {'node', 'container'}}`.
- argv `[self.clab, 'tools', 'netem', 'show', '-n', container, '-f', 'json']` (containerlab takes a name here; the
  answer is read-only state shown beside the bound `facts`), timeout 15 s. Live on 0.79.0 a node without impairments
  answers `{"<container>": null}`: the helper returns `{'facts', 'impairments': []}` for null or missing, else the one
  container's list reduced to `{interface, delay, jitter, loss, rate, corruption}` (strings/numbers, unknown keys
  dropped). **Assumption**: the non-null shape is a list keyed as `netem set` names them; C05 confirms it live.

### 2.5 `images` (extended, contract kept)

argv `[DOCKER, 'image', 'ls', '--format', '{{.Repository}}:{{.Tag}}\t{{.ID}}\t{{.Size}}\t{{.CreatedAt}}']`. The result
keeps `images: [reference]` exactly as today and adds `details: [{reference, id, size, created}]` (Docker's strings,
`4.53GB`, `2026-10-23 02:03:42 +0000 UTC`; the manager normalises `created` to ISO). `lab-builder-page.js` reads
`images` only, so an old helper without `details` keeps working.

### 2.6 `browse` with `files`, and `read`

- Request `{'mode': 'browse', 'path', 'options': {'files': true}}` (the only option). Without it, unchanged.
- With it, entries also include regular files (no dot-files; `lstat`, so a symlink is skipped, never followed) whose
  suffix is in `READABLE = ('.yaml', '.yml', '.json', '.drawio', '.txt', '.cfg', '.conf', '.set', '.md')` or whose
  basename is exactly `startup-config` or `juniper.conf` (containerlab's lab directory names), each with `size` and
  `kind: 'topology' | 'file' | 'directory'`, 500 entries in all. Never listed: keys, certificates, `.env`, binaries, hooks.
- `read` accepts the same set (today's list plus `.md` and the two basenames), 1 MiB, path rules unchanged, and closes
  a race that predates this chunk: after `self.path()`, it opens `path.parent` with `O_DIRECTORY | O_NOFOLLOW`, then
  `path.name` with `O_RDONLY | O_NOFOLLOW | O_NONBLOCK` through that `dir_fd`; `fstat` must show `S_ISREG` within
  1 MiB; the bytes come from that fd (the `owned_bytes_any` pattern, `host_operations.py:586-594`). A symlink named
  `startup-config` planted after the check is refused; a FIFO does not hang.

### 2.7 `capabilities`

Adds `'containerlab': <version>` from `[self.clab, 'version', '--short']` (32 ms live, no network; kept only when it
matches `^\d+\.\d+\.\d+`), and `'diagnostics': True` so the page can tell this helper from an older one without a failed call.

## 3. Manager side (`clab-backup-ui/app/lab_operations.py`)

- `LabOperations.diagnostics_slots = threading.BoundedSemaphore(3)`; `diagnose(req, timeout)` acquires it without
  blocking, else `HTTPException(503, 'The manager is already asking the VM for diagnostics; try again in a moment.')`;
  then `remote(self.host(), req, timeout=timeout)` (EOF rule unchanged), errors mapped as `invoke()` maps them, and the
  exact helper text `Unknown request mode.` (an older helper's answer, `host_operations.py:711`) mapped to `'This VM's
  manager tools need an update; ask your instructor or administrator.'`
- `target(lab_id, node)` → `(lab, node_row, deployment_name, container)`; HTTP 404 for an unknown device; HTTP 409
  with the cause's way out when `expected_container` is `''`: no deployment name → `'This lab is not linked to a lab
  on the VM. Link it under Advanced › Link to a running lab… to see logs and interfaces.'`; no topology node name →
  `'The manager does not know this device's topology node. Sync the topology from the VM (Advanced › Deployment details).'`
- Redaction, one path for logs and `/view`: `strip_escapes(text)` on the whole text (CSI `\x1b\[[0-?]*[ -/]*[@-~]`,
  OSC `\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)?`, two-byte `\x1b[@-Z\\-_]`, `\r`, every C0 control except `\n` and `\t`);
  then `redact_lines(lines, state)`: for logs each line is first split into its `--timestamps` stamp and body, and
  only bodies are redacted, line by line, with `scrub`'s three rules lifted into module constants both share
  (`secret_values()` once per request, longest first; the private-key rule as a block state carried across lines, so
  every body from `BEGIN … PRIVATE KEY` through its `END` line is `[private key omitted]`; the
  `password|passphrase|private key|community|secret` line rule, which turns vrnetlab's `PASSWORD: …` into
  `[sensitive output omitted]` and leaves its stamp). `scrub()` itself is unchanged (pinned by tests on persisted job
  output). No claim beyond these rules: a value neither stored nor on such a line is shown, as `/read` already shows it.
- Routes (same-origin guard; the polled reads are GET, so no `api.request` event; query values validated by the manager):
  - `GET /api/operations/logs?lab_id&node&tail&since` → `{container, present, lines: [{at, text}], truncated,
    fetched_at}`; `at` is the stamp (`''` for a line without one), `text` the redacted body. Helper 15 s, `remote` 30 s.
  - `GET /api/operations/interfaces?lab_id&node` → `{container, present, facts, interfaces: [{..., port, role}],
    counters, sampled_at}`. `port` comes from `topology.displayed_interface(kind, name)` (`''` without a rule); `role`
    is `management` for `eth0`, `internal` for an `ethN` with N below the kind's `PORT_RULES` offset (cJunosEvolved's
    eth1–eth3, type `dummy` live) and for a name matching neither `eth\d+` nor `e1-\d+` (cEOS's `cpu`, `fabric*`),
    else `data`. `role` is a display rule; C05 states its own impairment guard (a host-network node lists the VM's
    links, so `role` alone is not that guard). `remote` 45 s.
  - `GET /api/operations/netem?lab_id&node` → `{container, present, impairments}`; `remote` 30 s.
  - `GET /api/operations/images` keeps its shape and adds `details` and `used_by: {reference: [lab name]}`, built
    from `topology_images()` of every lab's topology text under the store lock, uncapped; cached with it for a minute.
  - `POST /api/operations/browse` gains optional `files: bool`; `POST /api/operations/view {path}` = helper `read`,
    `strip_escapes`, then (before redaction) a text over 512 KiB keeps its last 512 KiB cut at a line with
    `truncated: true`, then `redact_lines`. `/view` stays POST: one event per opened file is a useful record.
    `/api/operations/read` is untouched: `opEdit` parses topology text and must see it exact.
  - `GET /api/operations/capabilities` passes `containerlab` and `diagnostics` through; `diagnostics.py` adds
    `containerlab_version` to its capabilities item.
- `image_key(reference)` (pure): default registry `docker.io`, `library/` for a one-part name, tag `latest` when none;
  "Missing" in §4.5 compares keys, never raw strings; a digest-pinned reference is never Missing (the VM list has tags only).
- Public views: `facts` is copied field by field (`id`, `pid`, `status`, `health`, `started`, `ports`); the raw helper
  result is never returned. Never returned or stored: raw log text, the lab directory's VM path, other labels,
  counters of any interface not in the list.

## 4. The UI
### 4.1 Device drawer: Interfaces and Logs (`device-diagnostics.js`, new; `index.html`; `style.css`; `shell.js`)

Two `<details class="drawer-section">` after `#details-info`, closed by default so an open drawer asks the VM for
nothing until a student opens a section, rendered only when `opCaps.diagnostics` is true (an older helper shows
neither section). `renderDetails()` (app.js:467) calls `if(typeof renderDeviceDiagnostics==='function')
renderDeviceDiagnostics(n)`; the hook resets both sections when the key `activeId + '/' + detailName` changes
(Previous/Next, another lab's device of the same name) and updates the reason sentence; the 4-second poll never
rewrites a section's body. The drawer's existing `close` listener in `shell.js` calls `resetDeviceDiagnostics()` behind
a `typeof` guard: both sections collapse and their follow, poll timers and samples are cleared, so reopening the same
device starts clean. Each section has one `role="status"` element holding only its current sentence: it announces the
first load, an error and a stopped follow or poll, never a routine poll.

**One poll plan for both sections** (`diagPollNext(state, answer)`, pure, tested): the next request is scheduled with
`setTimeout` only after the previous answer arrived (never two in flight); interval 5 s; a 503 doubles it up to 30 s
and a success halves it back; three consecutive errors stop it with Retry; after 30 minutes it pauses with Resume; it
also stops when the section is closed, the drawer closes or changes device, or the tab is hidden (`pageVisible()`, a
one-liner on `document.visibilityState` in `shell.js`; on return one fresh fetch replaces the content). During a 503
or an error the last shown data stays under the caption "Updating paused, retrying…"; the 503 sentence never replaces
shown data. `present: false` is not an error: the body reads "No container for this device yet (deploy the lab, or
wait for the deploy to create it)" and polling continues, which is the boot-log case.

**Interfaces** (`summary` "Interfaces"): a table inside `.table-wrap` with `tabindex="0"`, columns Name · Port · State
· RX · TX; MAC, MTU and type are a second muted line in the Name cell, so the 520 px drawer never scrolls sideways
(checked at 390 and 1280). Data interfaces first; the management row reads "eth0 · management (the manager reaches
the device through it)"; internal ones under a "Other interfaces (n)" `<details>`. RX/TX show bytes and, from the
second sample on, a rate (`B/s`, `kB/s`, `MB/s`) that `diagRate(prev, now)` gives only when both samples carry the
same `facts.id` and `facts.started`, the same interface, a non-negative delta and Δt > 0; otherwise bytes alone and
the new sample is the baseline (`present: false` clears it). Every `data` row has a **Capture** button calling
`openCapture(n.name, name)` with the container interface (the name the live list holds; `port` sits in the Port
column), carrying `captureActionAttrs()` and the capture caption's reason when capture is not set up. Impairments
from `/netem` appear as a line under a row ("delay 15ms · loss 5%"), fetched once per open and after every operation
of this lab. Empty states from `facts.status`: running → "No interfaces reported"; otherwise "The container is
stopped (<status>). Interfaces exist only while it runs; Logs shows its last output."

**Logs** (`summary` "Logs"): toolbar Tail (200 default, 1000, 2000) · Refresh · Follow (`<button aria-pressed>`) ·
Find (a visible `<label>`, "n of m lines", matching lines only while non-empty) · Export; a `<pre class="op-code"
tabindex="0">` of lines shown as `HH:MM:SS text` with the full stamp in `title` (Export and the cursor keep the full
stamp). Refresh scrolls to the end; a Follow append scrolls only when the reader was within 30 px of the bottom
before it (the `opShowJob` rule, OPS-46). Export builds a Blob of the shown (redacted) text and saves
`<lab>-<device>-logs-<UTC stamp>.txt` through an `<a download>`; nothing goes to the manager. Empty: "The container
has written nothing yet". Follow uses the poll plan with `tail=2000` on every request and `since` = the `at` of the
last received line with a non-empty `at`; an incoming line is dropped only when its own `at` is non-empty and at or
before the cursor (a redacted line keeps its stamp and is shown; a stampless line is kept); exactly 2000 lines back
shows "Some lines may be missing."; the DOM keeps 2000 lines (oldest dropped, "Older lines dropped"); the resume after
a hidden tab replaces the content.

Error state (both sections): the manager's sentence verbatim with Retry (an older helper past the gate reads "This
VM's manager tools need an update; ask your instructor or administrator."); disabled: never for a running operation
(§1.7), only the two reason sentences of §3; reconnect: an unreachable VM comes back on the next successful poll.

### 4.2 Inspect table (`operations.js`, `opInspectionRows`, `opInspectionTable`)

Rows gain `id` (first 12 of `container_id`) and `owner`; the six existing columns keep their order and names
("State / health" verbatim) and ID · Owner are appended. Each `<th>` carries `aria-sort` and holds a `<button>`; sort
state and the filter text live in the dialog, not in `state`. The filter box has a visible label "Filter devices" and
hides rows whose joined text (Lab included) lacks the substring; the caption stays "n running devices" and reads "n of
m running devices" while a filter is set. `opInspectionSort(rows, key, dir)` and `opInspectionFilter(rows, text)` are pure.

### 4.3 Containerlab version (`operations.js`, `index.html`, `debug.js`)

The Manager menu footer gets `<span id="clab-version" hidden>`; a `menuopen` listener on `#manager-menu-list` (next to
the Lab actions one, `operations.js:686`) calls `opCapabilities()` (cached 60 s on the server) and fills it with
`containerlab 0.79.0`, which Diagnostics also shows in its capabilities row.

### 4.4 Lab files (`operations.js`, `opBrowse`)

Opened with a `labId` ("Lab files · <lab>") and `opCaps.diagnostics`, the dialog is in files mode, a property of the
dialog: every browse it makes (first listing, folder expansion, Up one folder, All lab folders) sends `files: true`
and keeps `labId`, the title and the help line, and `addEntries` skips `opTopologyEntries`, so the node folders under
`clab-<lab>/` and their startup configurations are reachable. Files show their size (`◇ startup-config · 2.1 kB`),
topology files first; empty: "No files the manager can show in this folder."; help: "Files the manager can show (text
and configuration files). Other files on the VM are not listed." A non-topology file opens `opView(path)`: the
read-only `op-editor` dialog titled "File on the VM", text from `/operations/view`, Copy when C02's `copyText` exists,
no Deploy/Add buttons, the standing sentence "Lines with passwords, secrets or SNMP communities are hidden. This copy
is for reading, not for loading onto a device." and, with `truncated`, "Showing the last 512 KiB of this file."
Without the flag, or without `labId`, the dialog is today's topology browser.

### 4.5 Images on this VM (`operations.js`, Manager menu)

A menu item **Images on this VM…** opens a dialog with a labelled filter box and a table Reference · Size · Created ·
Used by (lab names from `used_by`) with chips All / Used by my labs / Missing (a reference some lab names whose
`image_key` matches no VM image); without `details` a caption reads "Size and age need the updated VM helper." Nothing is pulled or removed.

## 5. Version lockstep and tests

A helper change is a release: `deploy/set-release.py` moves `VERSION` and the helpers' `VERSION`/`helper_version`;
every VM runs `sudo bash deploy/start-manager.sh --enable-operations` (the `--refresh` path, which checks the helper
version before the manager starts); until then `capabilities` lacks `diagnostics` and the page shows neither section.
The gateway is **not** changed: the new modes are request lines on the existing `clab-manager-operations` name, so
`test_gateway_whitelist.py` gains only a test that reads `host_operations.py` and asserts the dispatch adds no request
name and no shell (`HELPERS`, `ARMS`, `REFUSED` unchanged).

`test_lab_operations.py`:
- `DiagnosticModeTests` (copy `ImageModeTests`): the exact argv of each mode with a stub `docker` and `clab`,
  `--type container` pinned and `docker logs` receiving the inspected Id; refusals run nothing (tail `0`, `2001`,
  `'10'`, `True`; `since` with a trailing newline, a non-ASCII digit or a date; a missing `name`; another lab's
  container; a label mismatch; an option outside the whitelist; a selector `node_selector` refuses); `present: False`
  for "No such container" and non-JSON interface output; `interfaces: []` with `facts` for a stopped container;
  counters through the `/proc` directory fd of a temporary tree, left out on a cgroup mismatch or `OSError`; a
  non-zero logs exit is the fixed sentence; `netem` null → `[]`; `images` keeps `images` and adds `details`; `browse`
  with `files` lists only readable names, skips dot-files and symlinks, carries `size`, and is unchanged without it
  (`test_browser_filters_non_topologies_before_entry_limit` kept); `read` accepts `startup-config`, refuses `id_rsa`,
  `.pem`, `.env`, a symlink named `startup-config` and a FIFO (without hanging); `capabilities` carries `containerlab`
  only when it parses; `main()` dispatches exactly the named modes and no `DOCKER, 'exec'` or `'logs', '-f'` appears.
- `OperationAPITests`: 20 `GET /logs` polls with a patched `remote` leave `events.jsonl` byte-identical and the Store
  free of log text and `facts`; a stamped `PASSWORD:` line comes back redacted with its `at`; a key printed over
  several stamped lines leaves no base64 line; CSI/OSC and `\r` are gone; an unlinked lab and a device without a
  topology node get their two sentences; `since` shape tests; `/interfaces` gives `port` and `role` (eth0 management;
  cEOS `cpu` internal; cJunosEvolved eth1–eth3 internal and eth4 `et-0/0/0`; vJunos `eth1` `ge-0/0/0`; XRv9k `eth1`
  `Gi0/0/0/0`); the fourth concurrent call is a 503; `Unknown request mode.` maps to the student sentence; `/view`
  redacts and flags a 600 KiB file `truncated` cut at a line; `/read` is byte-exact; `/images` tolerates a helper
  without `details` and builds `used_by`; `image_key` on `alpine`, `alpine:latest`, `docker.io/library/alpine:latest`
  and a digest.
- `test_device_diagnostics_ui.js` (new, `test_operations_ui.js` harness): `diagLogLines` and the cursor (survives a
  redacted last line; redacted lines shown in Follow; stampless lines kept), `diagFilter`, `diagRate` (same id and
  start, negative delta, new container), `diagPollNext` (every interval, back-off, stop and pause condition, the 30 px
  scroll rule), the export name, management/internal grouping, the `aria-pressed`, `tabindex` and label markup;
  `test_operations_ui.js` gains sort, filter and caption cases; `test_page_load_ui.js`, `test_debug_ui.js` plus the footer span.
- Fixture pass (`clab-ui-qa`): `fixture_manager.py` learns the five modes; a Playwright check opens the drawer, both
  sections, Follow for two polls, Find, Export (a download event), the inspect filter, files mode down to a node
  folder's startup configuration, the viewer, and no sideways drawer scroll, at 1440/1280/760/390. Live pass on the
  `parity` lab: a vrnetlab boot log while the container is unhealthy, the Junos and cJunosEvolved port names, a
  5-second counter rate during a ping, a stopped device's empty state. CI: the lead appends
  `test_device_diagnostics_ui.js` to the `node --test` line.

## 6. Questions put to `risk-reviewer`, and their answers
1. **Device console text in container logs.** Accepted as runtime introspection: a fixed read-only Docker client
   command, nothing sent to the device, no session on it; `TRACE OUTPUT` lines are not dropped.
2. **Argv per mode.** The logs argv has three validated variable elements (tail, since, the inspected Id), none at
   argv[0..1]; every other mode has one (lab name or container). The inspect call carries `--type container`.
3. **Counters and pid reuse.** The counters stay: the cgroup check and the `/proc/<pid>` directory fd close both windows.
4. **Path rules.** The whitelist stands; `read` gets the dirfd/`O_NOFOLLOW`/`fstat` open (§2.6); `juniper.conf` is
   listed and viewed (`/read` and backup downloads already serve such files raw; refusing it in `/view` protects nothing).
5. **Concurrent SSH sessions.** No sshd concern: one connection and one session per call, far below `MaxStartups`.
6. **Merged stderr.** Accepted, with the fixed sentence on a non-zero exit (§2.2).

## 7. Assumptions, removed dead ends, what to attack
Assumptions: containerlab ≥ 0.64 for `inspect interfaces` (0.79.0 installed; an older VM answers "unknown command",
the section shows the helper's sentence and stops after three errors); `docker logs --since` accepts RFC 3339 with
nanoseconds (Docker's own `--timestamps` form); the labels `containerlab` and `clab-node-name` are on every lab
container (verified on `clab-parity-ceos`); C02's `copyText` may land first or later (Copy buttons appear only when it exists).

Dead ends removed: a vrnetlab device that reads *Starting* for ten minutes with no explanation; a link that looks
the same up or down; "which veth is `ge-0/0/2`" (the Port column); a startup configuration in a node folder that
needed SSH to the VM to read; a VM full of images nobody can size or trace to a lab; "which containerlab is this".
Refusals kept: a container not labelled for this lab; any file outside the whitelist; a tail over 2000; any write. New
refusals, each with its sentence: diagnostics for a device the manager cannot name a container for.

Attack: the label check (can a container of lab B be read by naming lab A, given `node_selector` accepts
`<prefix>-<lab>-<node>` for any prefix?); `--tail`, `--since` and the Id as the only values reaching argv; the
redaction order (escapes stripped, stamp split, then the line rule per body, so a coloured `PASSWORD:` line still
matches and keeps its stamp; the key-block state across lines); whether anything logs the text (no `Store.event`,
GET is not audited, uvicorn access logs carry no body, `remote()` caps the helper's `error` at 1000 chars and never
echoes `result`); the poll plan's stop conditions and the DOM cap; `esc()` on every inspect cell; C05 taking `role`
as its sole impairment guard (it must not: a host-network node lists the VM's links); the `/view` cut before redaction.

## 8. Files to change
`clab-backup-ui/app/host_operations.py` (lead or `clab-fable-specialist`; `risk-reviewer` on the diff);
`clab-backup-ui/app/lab_operations.py`, `diagnostics.py` (`clab-backend-engineer` from this document);
`clab-backup-ui/app/static/device-diagnostics.js` (new), `operations.js`, `shell.js` (`pageVisible`, the close hook),
`app.js` (one hook line), `index.html`, `style.css`, `debug.js` (`clab-ui-builder`); the tests of §5 (`clab-test-engineer`,
`clab-ui-qa`); `docs/LAB-OPERATIONS.md` ("Diagnostics" subsection, the Lab files row), `docs/DEBUG-PANEL.md`,
`clab-backup-ui/NODE-FEATURES.md`, `docs/redesign/tools/fixture_manager.py`. Release records and CI: the lead.

## 9. Review answers

One row per confirmed finding (risk R1–R8, UI U1–U17); the refuted ones need no answer, except that refuted item 2
(host-network nodes) is carried to C05 in §3 and §7.

| Finding | Answer | Where |
|---|---|---|
| R1 polls write `api.request` events | Accepted with change: GET routes, not a middleware exemption | §1.4, §3 routes, §5 (20-poll test) |
| R2 redaction order vs. stamps | Accepted with change: strip, split stamp, redact bodies per line with shared constants and a key-block state | §3 redaction, §5, §7 |
| R3 binding checked on a name | Accepted: `--type container`, 64-hex Id, Id to `docker logs`; netem keeps `-n <name>` | §1.3, §2.1, §2.2, §2.4, §5 |
| R4 pid reuse in the counter read | Accepted: one `/proc/<pid>` directory fd, `counters_reason: 'pid'` on any error | §1.6, §2.3, §5, §6.3 |
| R5 `read` symlink race | Accepted: dirfd, `O_NOFOLLOW`, `fstat`; fixed in this chunk though older | §2.6, §5, §6.4 |
| R6 `/view` drops the start of large files | Accepted with change: last 512 KiB cut at a line before redaction, `truncated`, caption | §3 `/view`, §4.4, §5 |
| R7 Interfaces poll unbounded | Accepted with change: one poll plan for both sections | §1.7, §4.1 poll plan, §5, §6.5 |
| R8 `since`/`tail`/`name`/exit details | Accepted: `fullmatch` with `re.ASCII`, `type(tail) is int`, shape-only, no name default, fixed exit sentence, `tail=2000` on follow | §2, §2.2, §4.1 Follow, §5, §6.2, §6.6 |
| U1 inspect table drops Lab (must-fix) | Accepted with change: six columns in order, ID and Owner appended, caption kept | §1.8, §4.2 |
| U2 Capture hint is the NOS port | Accepted: container interface name, every data row, `captureActionAttrs()` | §4.1 Interfaces |
| U3 Follow cursor and dropped redacted lines | Accepted with change (with R2): cursor = last non-empty `at`, drop only stamped lines at or before it, resume replaces | §4.1 Follow, §5 |
| U4 `/view` cut and hidden lines unsaid | Accepted with change (with R6): standing sentence in the viewer, no count field | §4.4 |
| U5 files mode not nested | Accepted: files mode is a dialog property; every browse keeps it and `labId` | §4.4, §5 fixture |
| U6 Images data cannot fill Used by / Missing | Accepted with change: `used_by` from `topology_images()` per lab, `image_key` normaliser, digests never Missing | §3 images and `image_key`, §4.5, §5 |
| U7 cJunosEvolved eth1–eth3 as data | Accepted: `displayed_interface()`, below-offset `ethN` is internal | §3 interfaces, §5 |
| U8 Interfaces poll contention | Accepted with change (with R7): data kept during 503, "Updating paused, retrying…" | §4.1 poll plan |
| U9 negative rates after restart | Accepted: same id and start, same interface, non-negative delta, Δt > 0 | §4.1 Interfaces, §5 |
| U10 stale state on reopen | Accepted with change: key `activeId + detailName`; the close hook lives in `shell.js` | §4.1 first paragraph |
| U11 follow yanks the reader down | Accepted with change: the 30 px rule, no extra button | §4.1 Logs |
| U12 stopped container reads "No interfaces reported" | Accepted with change: empty sentence from `facts.status`, no promise that the log explains it | §2.3, §4.1 Interfaces |
| U13 table and stamps overflow 520 px | Accepted with change: five columns with a second line, `.table-wrap`, `HH:MM:SS` with full stamp in `title` | §4.1 Interfaces and Logs, §5 fixture |
| U14 keyboard and screen-reader details | Accepted: one status element per section, `tabindex="0"`, labels, `aria-sort` on `<th>`, `aria-pressed` Follow | §4.1, §4.2, §5 |
| U15 old-helper sentence wrong, `files` ignored | Accepted with change: gate on `opCaps.diagnostics`, map `Unknown request mode.` to the student sentence | §3 `diagnose`, §4.1, §4.4, §5 |
| U16 footer version rarely shows | Accepted: `menuopen` on `#manager-menu-list` loads capabilities | §4.3 |
| U17 refusal without a way out; management label | Accepted with change: two sentences, one per cause; label without "impaired" | §3 `target`, §4.1 Interfaces |
