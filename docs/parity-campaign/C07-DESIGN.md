# C07 design: capture parity (one Wireshark per interface or one for all, both ends of a link, a remembered selection, End all my sessions)

Rows R051 (open as one Wireshark or one per interface), R052 (both ends of a link at once), R053 (remembered selection
and open mode), R054 (End all my sessions). R055 (several sessions as tabs in one viewer page) stays not pursued in
this chunk, with the reason in §8. Written against `claude/parity-campaign` at `08e7336` (release 1.31.2; the manager
on the VM is `clab-backup:1.31.2`, the capture stack `clab-capture-service:1.31.2` with Edgeshark, the `parity` lab up).
Code read: `capture.py` (identity, `LaunchRequest`, `targets`, `launch`), `capture_sessions.py` (the adapter, the
cookie `owner()`, the session routes, the two relays), `capture_service.py` (`Sessions.start`, `reap`, `public`, the
container spec, the routes), `capture.js`, `capture-session.js/.html`, `capture-setup.html`, `index.html` (the dialog,
the Tools card, the Lab actions item, the node menu element), `shell.js` (`shellGet/shellSet/shellRemove`, `closeMenus`,
`shellEscape`, `shellPointerDown`), `topology.js` (`openNodeMenu`, `nodeMenuReason`, the Escape order),
`topology-render.js` (`topologyLink`: `data-capture-endpoints`, `path.capture-hit`), `app.js` (`nodeActions`,
`handleNodeAction`), `device-diagnostics.js` (C03's Interfaces table and its Capture button), `deploy/compose.capture.yml`,
`deploy/capture/smoke.py`, `deploy/check_install.py` `check_capture`, the tests `test_capture.py`,
`test_capture_sessions.py`, `test_capture_proxy.py`, `test_capture_ui.js`, `test_capture_session_ui.js`,
`docs/CAPTURE.md`, `docs/redesign/inventory/capture.md` (the capabilities that must keep working), C03-DESIGN §4.1 and
C05-DESIGN §4.3. The invariants that bind (CLAUDE.md "Side stack"): only `capture_service.py` holds the Docker socket,
its API is never exposed to browsers and takes no client-supplied image, command, mount or URL; the `binary` VNC
subprotocol is offered upstream and echoed only when the client offered it; `/pcaps` is a labelled tmpfs-backed volume;
`setup-capture.sh` keeps `--force-recreate --remove-orphans`; the HMAC identity excludes the interface list; every
WebSocket checks `Origin`. **Nothing in this chunk changes the session service's code, its container spec, the gateway,
a helper, or adds a socket**: the work is in the manager (`capture.py`, `capture_sessions.py`), the page scripts, the
fixture tooling and the smoke test.

## 0. Facts verified live for this design (2026-10-23, this VM, release 1.31.2)

- Stack: `clab-manager-capture-sessions-1` (`clab-capture-service:1.31.2`), `-packetflix-1`, `-gostwire-1` up;
  `GET /api/capture/status` → `{"enabled": true, "provider": "edgeshark", …}`; `GET /api/capture/health` →
  `{"ready": true, "max_sessions": 4}` (the only capacity fact the service publishes: no "in use" count).
- `GET /api/capture/targets?lab_id=<parity>&node=clab-parity-ceos` lists 16 interfaces for the cEOS container
  (`arpinject, arpsnoop, cpu, eth0, eth1, eth2, fabric, fabric1–3, fwd0, lo, mirror0–3`); `clab-parity-vsw` and
  `clab-parity-vrt` list `eth0, eth1, eth2, lo, tap1, tap2` each (the tap devices the existing "never preselect a tap"
  rule is for). The lab-wide call lists the five containers. One target per container, one 64-hex id each.
- The drawing (`GET /api/labs/<parity>/topology`) carries `capture_interface` per endpoint: `vsw ge-0/0/0 → eth1`,
  `vrt ge-0/0/0 → eth1`, `vrt ge-0/0/1 → eth2`, `cjunos et-0/0/0 → eth4`, `cjunos et-0/0/1 → eth5`,
  `xrv9k Gi0/0/0/0 → eth1`, `xrv9k Gi0/0/0/1 → eth2`, `ceos eth1/eth2 → eth1/eth2`, `vsw ge-0/0/1 → eth2`. The live
  pass link is `vsw ge-0/0/0 (eth1) — vrt ge-0/0/0 (eth1)`.
- C03's `GET /api/operations/interfaces` for `vsw`: `eth1 ge-0/0/0 data`, `eth2 ge-0/0/1 data`, `eth0 management`,
  `lo`, `tap1`, `tap2` internal. The same call for `ceos` answered once with the helper's sentence "Docker on the VM did
  not answer about this container." (not retried; a transient of the C03 path, recorded for the lead, not this chunk's).
- **One capture started and ended on `clab-parity-ceos` `eth1`** (the one allowed): `POST /api/capture/launch
  {"target_id", "interfaces": ["eth1"], "request_id"}` → HTTP 200 `{"id": <64 hex>, "url": "/static/capture-session.html#<id>",
  "message": "Wireshark session started on the VM. Open the browser viewer to inspect packets."}` and the response set
  the cookie `clab_capture_owner`; the same body again (same `request_id`) answered the same `id` (idempotent at the
  service: `sid = HMAC(token, owner + request_id)`); `GET /api/capture/sessions` → `{"sessions": [{"id", "name":
  "clab-parity-ceos", "interfaces": ["eth1"], "remaining_seconds": 7199, "idle_seconds": 900}]}`;
  `GET /api/capture/sessions/<id>` adds `"running": true` and `"viewer_password"` (not recorded); the container was
  `clab-capture-clab-manager-capture-v1-<id>` with `Memory 1 GiB, NanoCpus 1.5, PidsLimit 256, NetworkMode
  clab-manager-capture, CapDrop NET_RAW, Tmpfs /config 64m and /tmp 256m, one volume mount at /pcaps`, and
  `PACKETFLIX_LINK=packetflix:ws://packetflix:5001/capture?container=…&nif=…` (the only per-session variable, built by
  the service from its own fresh discovery); `POST …/end {}` → `{"ended": true}`; the listing was empty and the container
  gone one second later. No second session was started.
- Bounds, from `capture_service.py`: `MAX_SESSIONS = 4` **across all owners** (the cap is global, the listing is
  owner-scoped and reaps first), `IDLE_SECONDS = 900` (viewer polling of a running desktop counts), `LIFETIME_SECONDS =
  7200`, the limits above, `/pcaps` 256 MiB. `StartRequest.interfaces` is `1..128` names; several names of one
  namespace share one PCAPNG stream (`nif=a/b`). A desktop is one namespace: two containers are two sessions.

## 1. Decisions in one place

1. **"One Wireshark for all interfaces" is one session whose validated interface list has several names: what the
   service does today, unchanged.** The client supplies interface *names* only; the manager checks them against a fresh
   Edgeshark discovery and the service checks them again against its own; the container spec is fixed and the only
   per-session variable is the `PACKETFLIX_LINK` value the service itself builds. No argv, command, image, mount or URL
   comes from a client, so both options the task names are within the invariants, and the second (one session with
   several validated names) needs nothing new. **"One Wireshark per interface" is a fan-out on the manager**: one
   request, N sessions of one interface each, each a normal service `POST /sessions`. The identity rule stays true as
   written: the HMAC identity is the namespace (`IDENTITY_FIELDS`, no interfaces); a set names `(target_id, interfaces)`
   per entry and each entry is validated as a single launch is (§2.2). No amendment of the rule is needed.
2. **One route, two body forms.** `POST /api/capture/launch` keeps today's `{target_id, interfaces, request_id}` byte for
   byte (every existing test and an old page keep working) and accepts the set form `{captures: [{target_id,
   interfaces}, …], request_id}` with 1 to 4 entries (4 = the service's cap; a set larger than the cap can never
   succeed). A second route was considered and dropped: the validation, the event and the cookie handling are the same.
3. **A set is validated whole, pre-checked against the student's own slots, then started in order.** One discovery for
   the whole set (today: one per launch); every entry resolved and its interfaces checked before any container is
   created, so a stale entry refuses the set with nothing started; the owner's listing is fetched and `own + k > limit`
   refuses the set with the sentence of §4 (the common case: one student on the VM); the entries are started one by
   one with derived request ids `sha256(request_id + ':' + index)` so an uncertain retry of the same set is idempotent
   per entry (the service dedups on owner + request id). The cap is global, so another browser can take a slot between
   the pre-check and the fourth start: a refusal mid-way stops the set and is reported as `refused` beside the
   `sessions` that started (HTTP 200: the request produced sessions; the page shows both halves and the student decides).
4. **Both ends of a link are two sessions** (two containers are two namespaces; one stream cannot cross a namespace),
   started as one set. Each session gets its own **Open Wireshark: <end> ↗** link in the dialog: a browser allows one
   popup per user gesture, so "open both in one click" would lose the second tab to the popup blocker, and a wrapper
   page showing two desktops (R055) is a rewrite of the viewer's per-session logic for little value (§8). Two tabs, one
   click each, both listed under Your capture sessions.
5. **The manager knows its own sessions.** `Captures.known` is an in-memory map `sid → {lab_id, node, label, ports,
   started}` written at launch; `GET /api/capture/sessions` answers a public view built by whitelist from the service's
   owner-scoped listing (`id, name, interfaces, remaining_seconds, idle_seconds`) plus the manager's decoration (`lab`,
   `device`, `ports`), from `known` when present and from matching `expected_container(lab, node)` across the labs when
   not (a manager restart). The service's rows are never returned verbatim: a field the service may add later stays
   private until copied, as every other public view in this manager. Nothing is persisted: a session dies with the
   service, and the Store carries controlled metadata only.
6. **End all my sessions is one manager route**, `POST /api/capture/sessions/end-all {}`: the manager lists the owner's
   sessions through the service and ends each; "my" is the cookie, exactly as for every other session call, so the
   route can never reach another browser's session; one confirmation, one event, partial results reported. The browser
   looping over the rows was rejected: a closed tab mid-loop leaves half, and the action log would show N events for one
   decision.
7. **A remembered selection per lab and browser, through `shell.js`**: key `clab.capture.<lab id>.<scope>` with scope
   `node:<node name>` or `link:<a>:<ifa>|<b>:<ifb>`, value `{"interfaces": [...], "separate": bool, "ends": [bool, bool]}`
   (JSON ≤ 2000 characters, `try/catch` through `shellGet/shellSet`); the last open-as choice is also kept as the
   browser default `clab.capture.openas`. Memory is restored only for interfaces the live list still holds, and only
   when the dialog was opened without a hint: a click on a specific port (a link endpoint, a row of C03's table, a menu
   item naming an end) is the student's current intent and wins. The Store and the lab record learn nothing of it.
8. **The wire gets a right-click menu; the left click stays one click to capture.** `#link-context-menu` (built by
   `capture.js`, markup and behaviour modelled on `#node-context-menu`) opens on contextmenu, the ContextMenu key and
   Shift+F10 over a wire with three items: **Capture both ends…**, **Capture <A>: <port>…**, **Capture <B>: <port>…**;
   left click, Enter and Space keep opening the dialog directly, in link mode with both ends ticked. PARITY.md's critic
   required that Capture stay one click away when a link menu is added: it does (the click), and in the menu the
   first item is focused, so right-click, Enter is a capture too. C05's impairment badge (its §4.3) changes neither the
   wire's attributes nor its hit path, and the menu builder is one function C05 or C06 may append to.
9. **"All" means the connected interfaces.** The dialog's **All connected** preset ticks the wired ports whose veth the
   VM lists (never `eth0`, never a `tapN`, never a fabric or mirror device: the parity cEOS lists 16 interfaces of which
   two are wired); **None** clears. C03's Interfaces table gets **Capture all** in its header, which passes the table's
   own `data` rows as the preset (`openCapture(node, '', null, {preset: [names]})`): the table knows the roles, the
   dialog knows the map, and each uses its own knowledge. Management and internal interfaces stay opt-in behind the
   existing toggle; capturing `eth0` is not refused (watching the manager's own SSH is a legitimate lesson), it is just
   never part of "all".
10. **The open-as control appears only when it means something**: two or more interfaces ticked on one device. In link
    mode the two ends are separate sessions by nature, so the control is hidden and the summary says so. The Start
    button names what it will do (§3.1), so a student never starts four desktops by surprise.
11. **Refusals are counted before anything starts and worded with the way out** (§4): too many sessions (own count,
    set size, the global cap mid-way), an end of a link whose device the VM does not list (not running), the stack
    disabled or unreachable, a target that changed. There is no new refusal for a non-data interface (decision 9).
12. **No service change.** The smoke test is extended to prove what the fan-out relies on at the service: two desktops
    for one namespace under two request ids, each with its own VNC password and listing row, the same request id
    answering the same session, and ending both leaves nothing (§5.4). The fixture manager gains a scripted capture
    stack (`--capture`) so the dialog, the fan-out, the cap and End all can be driven in a browser without Docker
    (§5.5); the cap and the partial-set case can only be driven there.

## 2. Backend contract (`clab-backup-ui/app/capture.py`, `capture_sessions.py`)

### 2.1 `LaunchRequest`

```python
class CaptureEntry(BaseModel):
    model_config = ConfigDict(extra='forbid')
    target_id: str = Field(min_length=64, max_length=64, pattern=r'^[0-9a-f]{64}$')
    interfaces: list[str] = Field(min_length=1, max_length=128)

class LaunchRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    target_id: str | None = Field(default=None, min_length=64, max_length=64, pattern=r'^[0-9a-f]{64}$')
    interfaces: list[str] | None = Field(default=None, min_length=1, max_length=128)
    captures: list[CaptureEntry] | None = Field(default=None, min_length=1, max_length=4)
    request_id: str = Field(default_factory=lambda: secrets.token_hex(32), pattern=r'^[0-9a-f]{64}$')

    @model_validator(mode='after')
    def one_form(self):
        single = self.target_id is not None or self.interfaces is not None
        if single == (self.captures is not None) or (single and (self.target_id is None or self.interfaces is None)):
            raise ValueError('Send either target_id with interfaces, or captures.')
        return self

    def entries(self):
        return self.captures or [CaptureEntry(target_id=self.target_id, interfaces=self.interfaces)]
```

Interface names are validated against the fresh list only (as today): the manager never pattern-checks a name itself,
because the live list is the whole contract. `captures` with 5 entries is a 422 (the page never builds one: it refuses
earlier with the sentence of §4).

### 2.2 `launch()`

1. `if not self.sessions: 503` (unchanged). `rows = self.discover()` **once**.
2. For every entry, in order: resolve the target by `hmac.compare_digest(self.identity(t), entry.target_id)`; missing →
   409 `Capture target changed or disappeared. Refresh interfaces and select it again.` (the existing sentence; for a
   set, prefixed with the entry's label: `vrt ge-0/0/0: `); duplicate names inside an entry or a name outside the
   target's list → 409 `Select interfaces from the refreshed live list.` (existing); the same `(target, interface)` in
   two entries → 409 `The same interface is listed twice. Refresh interfaces and select again.`. **Nothing has been
   started when any of these fires.**
3. Label every entry: `label(target, interfaces)` under the store lock → the lab and node whose
   `expected_container(lab, n)` equals `target['name']` (first match; the lab the page sent is not trusted for the
   match, the container name is) gives `device = short_name or name` and `ports = [displayed_interface(kind, iface)
   for iface in interfaces]` (`topology.py:107`: the NOS port name for a kind with a rule, the veth name unchanged
   otherwise); no match → `device = target['name']`, `ports = interfaces`. The label is `f'{device} {", ".join(ports)}'`.
4. Pre-check, sets of two or more entries only: `own = len(self.sessions.request('GET', 'sessions', who)['sessions'])`,
   `limit = self.capacity()` (the service health's `max_sessions`, fetched at most once a minute, `4` when the health
   call fails or lacks it); `len(entries) > limit` → 409 `CAPTURE_SET_TOO_LARGE`; `own + len(entries) > limit` → 409
   `CAPTURE_SLOTS_OWN` (both in §4). A single launch keeps today's path: the service's own 429 is its answer.
5. Start in order: `rid = data.request_id if len(entries) == 1 else hashlib.sha256(f'{data.request_id}:{i}'.encode()).hexdigest()`;
   the service call is today's call with that `request_id`; the session id is checked with `TOKEN` as today; the event
   `capture.launch` is written per started session with today's text (container and interface names: controlled
   metadata). `self.known[sid] = {'lab_id', 'node', 'label', 'ports', 'started': time.time()}` (bounded: `known` is
   pruned to the ids the next listing returns, and capped at 64 entries oldest-first, so a service that lost its rows
   never grows it). An `HTTPException` from the service (429, 503, 502) on entry `i`: stop; the remaining entries,
   this one included, go to `refused` with the mapped sentence (`capture_sessions.BrowserSessions.request` already maps
   codes to student sentences); when **no** entry started, raise that exception as today (a single launch is
   unchanged; a set that fails at its first entry is a plain error).
6. Response: `{'sessions': [{'id', 'url', 'name', 'interfaces', 'label'}], 'refused': [{'label', 'interfaces',
   'detail'}], 'message'}` plus, when at least one started, `'id'` and `'url'` of the first (the old shape, for an old
   page). `message`: one started → today's sentence; several → `Wireshark started on the VM for <n> captures. Open each
   viewer below.`; with `refused` → `Wireshark started for <labels of started>; not for <labels of refused>: <detail of
   the first refused>` (one sentence, the detail is the service's mapped text).

### 2.3 `GET /api/capture/sessions` (`capture_sessions.py`, `install()`)

```python
PUBLIC_SESSION = ('id', 'name', 'interfaces', 'remaining_seconds', 'idle_seconds')
def public_session(row, known, labelled):
    out = {k: row[k] for k in PUBLIC_SESSION if k in row}
    extra = known.get(out.get('id')) or labelled(out.get('name', ''), out.get('interfaces', []))
    out.update({'lab': extra.get('lab', ''), 'device': extra.get('device', ''), 'ports': extra.get('ports', [])})
    return out
```

`sessions()` lists through the service as today, prunes `captures.known` to the ids returned, and answers
`{'sessions': [public_session(...)]}`. `labelled(name, interfaces)` is step 3 of §2.2 (store lock, container-name
equality). `id` must match `TOKEN` or the row is dropped. The per-session status route (`GET /sessions/{sid}`, the
viewer's heartbeat, with `running` and `viewer_password`) is **unchanged**: the viewer page is not touched.

### 2.4 `POST /api/capture/sessions/end-all`

Body `{}` (the guard needs a body). `who = owner(request)` (a browser without the cookie gets today's 404 sentence:
it owns nothing). `rows = service().request('GET', 'sessions', who)['sessions']`; for each row with a valid id:
`service().request('POST', 'sessions/<id>/end', who, {})`; a 404 (expired between list and end) counts as ended; a
503/502 goes to `failed` with the mapped sentence and the loop continues. Response `{'ended': n, 'failed': [{'id',
'label', 'detail'}]}` (`label` from `known`/`labelled`). One event `capture.end_all`: `Ended <n> browser Wireshark
session(s) and removed their temporary files.` (and `; <m> could not be ended` when `failed`). `known` drops the ended
ids. No row → `{'ended': 0, 'failed': []}`, no event.

### 2.5 `capacity()` and what does not change

`Captures.capacity()` → `GET health` through the adapter, `max_sessions` when it is an `int` in `1..64`, else `4`;
cached 60 s; a failed health call does not fail a launch (the service's 429 remains the authority).

Unchanged: `identity()` and `IDENTITY_FIELDS`; `discover()` and its four slots; the service adapter's code mapping;
`owner()` and the cookie; the status, health, per-session status, end, assets, download and websockify routes; the two
relays and the `binary` subprotocol rule; `capture_service.py` entirely (image pin, spec, cap, idle, lifetime, sweep);
`compose.capture.yml`; `setup-capture.sh`. No helper, no new socket, no change to the guard.

## 3. The UI

### 3.1 The capture dialog (`capture.js`, `index.html`, `style.css`)

**Three modes**, decided by `openCapture(node, hint, ends, options)` (the fourth parameter is new; the three callers
of today pass nothing there):

| Mode | Opened by | `#capture-context` |
|---|---|---|
| device | the device panel, the Devices rows, the node menu (`data-capture`), C03's table (a row, or **Capture all** with `options.preset`), the Tools card with a device chosen under Advanced | `Device: <node>` (+ ` · port <hint>` as today) |
| link | a wire's click, Enter, Space; the menu's **Capture both ends…** (`ends` given, `options.end` absent); the menu's **Capture <A>: <port>…** (`options.end = 0/1`: link mode with only that end ticked) | `Link: <A>: <ifA> — <B>: <ifB>` |
| none | the Tools card, Lab actions ▾ › Packet capture… | today's `Lab <name> — choose a device below` |

**Link mode** replaces today's endpoint buttons (which switched the whole dialog to one end) with a fieldset
`#capture-ends` (`<legend>Link ends</legend>`): one `<label class="capture-interface"><input type="checkbox"
data-capture-end="i" checked> <span>vsw: ge-0/0/0</span> <small>eth1</small></label>` per end, both ticked by default
(memory or `options.end` may untick one). The dialog fetches `/capture/targets?lab_id=<lab>` once (lab-wide: both
containers in one call, as the targets route already supports) and resolves each end to its target and veth with the
rules of today's `renderCaptureInterfaces` (`capture_interface` from the drawing, the tap rule, "not listed yet"
reasons); the Connected and Other fieldsets are hidden in link mode (an end is one interface by definition; a student
who wants more opens the device from its menu). Per end, a status line under its box: `eth1 live` / `The VM lists no
eth1 for ge-0/0/0 yet: the device may still be starting, or the topology changed.` (box unticked and disabled) / `vrt
is not running on the VM (no live interfaces), so this end cannot be captured now.` (box unticked and disabled) / `this
diagram node is not in the inventory — choose its device under Advanced` (today's sentence, box disabled; Advanced
unfolds). The scope select and Refresh interfaces keep working; the device selector in Advanced stays for the
unresolved case. The summary (§ below) counts the ticked, resolvable ends.

**Open as** (`#capture-openas`, a fieldset of two radios, name `capture-openas`): `One Wireshark for the ticked
interfaces` (value `one`) and `One Wireshark per interface` (value `each`). Shown only in device mode with two or more
ticked interfaces; hidden otherwise (and in link mode). Default from memory for the key, else `clab.capture.openas`,
else `one`. Changing it calls `invalidateCapture()` like any selection change.

**Presets**: in the Connected fieldset's legend row two small buttons, `#capture-all` **All connected** and
`#capture-none` **None** (device mode, shown only when the Connected list has two or more boxes). `options.preset`
(from C03's table) ticks exactly the named interfaces that are in the live list; names not live are reported with
today's "not found" sentence.

**Summary and the Start button** (`captureSummary(mode, ticked, separate, ends)`, pure, tested): the button reads
`Start capture` (one session), `Start 2 captures` (per-interface or two ends: `Start <n> captures`), and is disabled
with no ticked interface or end. `#capture-status` carries the plan before Start: `One Wireshark for eth1, eth2 on
vsw.` / `One Wireshark per interface: eth1, eth2 on vsw (2 sessions).` / `Both ends of the link: vsw ge-0/0/0 (eth1)
and vrt ge-0/0/0 (eth1), one Wireshark each (2 sessions).` / `One end: vrt ge-0/0/0 (eth1).` The slot arithmetic is
done on the page before the request: `ownCount` (from the last sessions listing) + planned > `captureLimit` (from
`/capture/health`, read with the status at dialog open, default 4) → the Start button stays enabled but `#capture-status`
reads the `CAPTURE_SLOTS_OWN` sentence and Start answers with it without a request (the server repeats the check, §2.2
step 4; a stale page meets the server's sentence).

**Submit**: `mode === 'link'` → `captures` = one entry per ticked end (`target_id` of that end's container,
`interfaces: [veth]`); device mode with `each` → one entry per ticked interface; otherwise today's single body. The
`request_id` rule is unchanged (kept across uncertain retries, reset on success and on any change). **Results**:
`#capture-launch` (one link) becomes `#capture-launches`, a container of one `<a class="button primary" target="_blank"
rel="noopener" href="/static/capture-session.html#<id>">Open Wireshark: <label> ↗</a>` per started session (one link
in the single case, the old test claims kept: exactly one link, same href pattern, the `javascript:` refusal); each
`href` is checked against today's pattern before it is set; with `refused` the status shows the manager's sentence and
the started links stay. Clicking a link sets today's "opened in a new tab" sentence with the label.

**Memory** (`shell.js`): `captureMemory(labId, scope)` → the parsed record or `null`; `rememberCapture(labId, scope,
record)` (serialises, refuses over 2000 characters, returns `false` when storage throws); `captureOpenAs()` /
`rememberOpenAs(value)`. `capture.js` reads memory in `renderCaptureInterfaces` when `captureHint` is empty and no
`options.preset`/`options.end` was given, intersects `interfaces` with the live list, ticks those, applies `separate`
to the radios, applies `ends` in link mode; when at least one box was restored the status says `Your last selection
here was restored.` before the plan sentence; a record whose interfaces are all gone is ignored silently. It writes
memory on a successful Start (the ticked set and the mode as started). Nothing is written on open or on a refusal.

**Sessions in the dialog** (`#capture-sessions`): rows read `<a …>vsw ge-0/0/0 (eth1) · parity</a> <span
class="caption">ends in 1 h 58 min</span> <button class="button secondary" data-end-capture="<id>">End session</button>`
(label from `device` + `ports` with the container interface in brackets when a port name differs, lab from `lab`; a
row without a lab match reads the container name as today); `#capture-end-all` **End all my sessions** next to Refresh
list, hidden when the list is empty, `confirm('End all <n> Wireshark sessions started from this browser and delete
their capture files? Download saved files first.')`, then `POST /capture/sessions/end-all {}`; the button reads
`Ending…` and is disabled meanwhile; the result sentence `Ended <n> sessions.` or `Ended <n> sessions; <m> could not be
ended: <detail>. Try again.` goes to `#capture-status`; then the list refreshes. Per-row End session is unchanged.

**Width**: `.capture-openas label { display: block; }` at every width; `#capture-launches` reuses `.dialog-actions`
(`flex-wrap: wrap`); the ends fieldset reuses `.capture-interfaces` (two columns at 390 px per the existing rule); no
inline style. `#capture-ends` carries an id so `verify_after.py`'s order check (`capture-advanced` before the first
id-less `fieldset`) still names the Connected fieldset.

### 3.2 The wire menu (`capture.js`, `index.html`, `shell.js`)

`<div id="link-context-menu" class="node-context-menu" role="menu" aria-label="Link actions" hidden></div>` next to
`#node-context-menu` (same classes, so no new CSS). `openLinkMenu(element, x, y)` in `capture.js` (the wire listeners
already live there): header `<div class="context-node-name">vsw: ge-0/0/0 — vrt: ge-0/0/0</div>`, then three
`<button type="button" role="menuitem">`: `data-link-both` **Capture both ends…**, `data-link-end="0"` **Capture vsw:
ge-0/0/0…**, `data-link-end="1"` **Capture vrt: ge-0/0/0…**; each carries `captureActionAttrs()` and, when disabled,
`<small>Packet capture isn’t set up on this VM yet — see Tools › Packet capture.</small>` (the node menu's wording). The
first enabled item is focused; ArrowUp/Down/Home/End rove (the node menu's keydown, copied); a click opens the dialog in
link mode (`openCapture('', '', ends)` or with `{end: i}`) and closes the menu; `closeLinkMenu(restore)` restores focus
to the wire when asked. The wire's `contextmenu` listener (today: opens the dialog) opens the menu instead; a `keydown`
of `ContextMenu` or Shift+F10 on a focused wire opens it at the wire's box; click, Enter and Space are unchanged
(dialog, link mode, both ends ticked). **Dismissal through `shell.js`**: `closeMenus()` also closes
`#link-context-menu` when it is open (calling `closeLinkMenu()` behind a `typeof` guard) and counts it as closed, so
`shellEscape`, `shellPointerDown` and `topology.js`'s own Escape handler (`if(closeMenus())return;`) all do the right
thing without a change in `topology.js`; `window` resize and blur already close the node menu in `topology.js` and the
link menu adds the same two listeners **in `shell.js`** (`closeMenus()` is called there on both). The node menu's
Escape-first rule in `shellEscape` is kept; the link menu is never open at the same time (opening either closes the
other: `openLinkMenu` calls `closeNodeMenu()` as the wire's contextmenu handler does today).

### 3.3 Sessions on the Tools card (`capture.js`, `index.html`)

The Packet capture card gains `<p class="caption" id="capture-sessions-caption" hidden></p>` and, in its `.actions`,
`<button type="button" class="button secondary" id="tools-capture-end-all" hidden>End all my sessions</button>`. One
state object `captureSessionsState = {rows, fetched}` feeds the card and the dialog: `renderCaptureSessions()` writes
both places. The caption reads `1 Wireshark session running from this browser.` / `<n> Wireshark sessions running from
this browser.` and is hidden at zero; the button shows at one or more and runs the same confirm and route as the
dialog's. The listing is refreshed when the Tools tab is shown (an element listener on `#lab-tabs` for a click on
`[data-tab="tools"]`, kept in `capture.js`: an element listener, not a document one), when the dialog opens, after every
launch and every end; never on a timer (the inventory's "NOT auto-polled" stands; End all re-lists at the service, so
it never acts on a stale count). When `captureEnabled === false` the caption of today (`Packet capture is not set up…`)
is shown and the sessions caption and button are hidden.

### 3.4 C03's Interfaces table (`device-diagnostics.js`)

The table header row gains `<button type="button" class="button ghost small" data-diag-capture-all>Capture all</button>`
beside the caption, rendered only when two or more `data` rows exist and carrying `captureActionAttrs()`; the click
calls `openCapture(detailName, '', null, {preset: <the data rows' container names>})`. The per-row Capture button is
unchanged. The getter and the poll plan are untouched (C04 S2 owns its own lines in this file; see §7 for ordering).

### 3.5 What does not change on the pages

`capture-session.html/.js` (the viewer: name, interfaces, heartbeat, download, end, reconnect); the node menu's
Capture item; `nodeActions`' Capture button; the Lab actions item; the Advanced selector and scope; the tap rule; the
"not found" sentences; `#capture-sessions-refresh`; the setup page's structure (two sentences change, §6).

### 3.6 States, in one place

Default: device mode as today with the presets visible at two or more connected boxes; link mode with both ends ticked
and the plan sentence. Loading: `Looking up interfaces on the VM…` (today), Start disabled. Empty: device without live
interfaces (today's sentence); link with neither end resolvable: `Neither end of this link is on the VM right now. Start
the lab, or choose a device under Advanced.` Error: the manager's sentence verbatim in `#capture-status`, Start
re-enabled (today). Success: the per-session links and the message. Disabled: the stack off → every entry point
disabled with the reason, the dialog explains and links the setup page (today); End all hidden. Cancel: closing the
dialog invalidates the plan, never ends a session (today). Retry: Start again reuses `request_id` until a change
(today). Reconnect: a session row's link reopens the viewer; the viewer's own Reconnect is unchanged. Keyboard: native
checkboxes and radios, labelled; the menu roves; `#capture-status` is the one `role="status"`; focus returns to the wire
after the menu closes with Escape.

## 4. Every refusal, with its wording

| Case | Where | HTTP | Sentence |
|---|---|---|---|
| set larger than the cap | server `CAPTURE_SET_TOO_LARGE`; page before the request | 409 | `<k> separate Wireshark sessions are more than the limit of <limit> at a time. Untick interfaces, or open one Wireshark for all of them.` |
| own sessions + set over the cap | server `CAPTURE_SLOTS_OWN`; page before the request | 409 | `You already have <n> Wireshark session(s) running from this browser; <k> more would pass the limit of <limit> at a time. End a session under Your capture sessions, untick interfaces, or open one Wireshark for all of them.` |
| the global cap reached mid-set (another browser's sessions) | server, in `refused` | 200 with `refused` | `Wireshark started for <labels>; not for <labels>: All browser capture slots are in use. End a session or wait for expiry.` |
| the global cap reached on a single launch or the first entry | service 429 through the adapter | 429 | `All browser capture slots are in use. End a session or wait for expiry.` (unchanged) |
| an entry's target changed or vanished | server, nothing started | 409 | `<label>: Capture target changed or disappeared. Refresh interfaces and select it again.` |
| an interface not in the fresh list, or twice in one entry | server, nothing started | 409 | `Select interfaces from the refreshed live list.` (unchanged) |
| the same interface in two entries | server, nothing started | 409 | `The same interface is listed twice. Refresh interfaces and select again.` |
| five or more entries, both body forms at once, neither | pydantic | 422 | (never built by the page) |
| a link end whose device the VM does not list | page, the end's box disabled | — | `<device> is not running on the VM (no live interfaces), so this end cannot be captured now.` |
| a link end whose veth is not listed yet | page, the end's box disabled | — | `The VM lists no <veth> for <port> yet: the device may still be starting, or the topology changed.` |
| a link end whose diagram node is not in the inventory | page, the end's box disabled, Advanced unfolds | — | today's `this diagram node is not in the inventory — choose its device under Advanced` |
| neither end resolvable | page | — | `Neither end of this link is on the VM right now. Start the lab, or choose a device under Advanced.` |
| nothing ticked | page, Start disabled | — | `Choose a device and tick at least one interface.` (unchanged; link mode: `Tick at least one end of the link.`) |
| End all with no session | server | 200 `{ended: 0}` | page: `No capture sessions to end.` |
| End all, a session the service could not remove | server, in `failed` | 200 | `Ended <n> sessions; <m> could not be ended: Could not remove the capture container; retry End session. Try again.` |
| End all without the owner cookie | `owner()` | 404 | `Capture session not found in this browser.` (unchanged) |
| the stack disabled or unreachable | unchanged 503/502 and the page's disabled attributes | | unchanged sentences |
| a foreign origin | the guard | 403 | unchanged |

Kept, not refusals: capturing `eth0` or an internal interface is allowed when ticked by hand; a tap device is never
preselected; memory never ticks an interface the VM does not list.

## 5. Tests per layer

### 5.1 `tests/test_capture.py` (`CaptureAPITests`, existing harness: `FakeSessions`, patched `read_discovery`)

The fake sessions object grows a `listing` attribute (rows it returns for `GET sessions`), a per-call `fail` hook
(raise `HTTPException(429, …)` on the nth `POST sessions`), and records `request_id` per call. New tests:

- `test_a_set_starts_one_session_per_entry_with_derived_request_ids_and_labels`: two entries (r1 eth2, and the host
  target `ens18`) → two service calls whose `request_id`s are `sha256('<rid>:0')` and `sha256('<rid>:1')`, the response
  has two `sessions` with `label` `r1 eth2` and `init ens18`, `id`/`url` of the first, two `capture.launch` events, and
  `known` holds both ids with `lab_id='lab'`, `node='r1'` for the first.
- `test_a_set_is_validated_whole_before_anything_starts`: the second entry names `eth99` → 409, zero service calls;
  a vanished second target → 409 naming its label, zero calls; the same `(target, eth2)` twice → 409 "listed twice".
- `test_the_own_slot_pre_check_refuses_before_starting`: `listing` with 3 rows and a set of 2 → 409 `CAPTURE_SLOTS_OWN`
  with `3`, `2`, `4` in the text, zero calls; a set of 5 is 422; with `capacity()` answering 6 (patched health), 3 + 2
  passes.
- `test_a_mid_set_refusal_reports_started_and_refused`: `fail` on the second `POST` with 429 → HTTP 200, one session,
  one `refused` row with the mapped 429 sentence, the message naming both labels; `fail` on the first → HTTP 429 and
  no `sessions` key (a plain error, as today).
- `test_single_launch_body_and_response_are_unchanged`: the existing single tests are left as they are; this one
  additionally asserts the single response carries `sessions` of length 1 with the same `id`.
- `test_sessions_listing_is_a_whitelist_with_labels`: the fake listing returns rows with an extra `password` and
  `address` field → the manager's answer carries exactly `PUBLIC_SESSION + ('lab', 'device', 'ports')`, the lab and
  device from `known` for a launched id and from container-name matching for an unknown id (`clab-demo-r1` → `demo`,
  `r1`), `ports` with `displayed_interface` for a Junos node fixture (`eth1` → `ge-0/0/0`), and a row with a bad id is
  dropped; `known` is pruned to the listed ids and capped at 64.
- `test_end_all_ends_only_the_cookies_sessions_and_reports_failures`: two rows → two `POST …/end` calls, `{ended: 2,
  failed: []}`, one `capture.end_all` event with `2`; a 404 on one end still counts; a 503 on one end → `failed` with
  the mapped sentence and the other ended; an empty listing → `{ended: 0}` and no event; no cookie → 404; a cross-origin
  POST → 403; the request without a body → 413 (the guard).
- `test_capacity_falls_back_to_four_and_is_cached`: a failing health → 4; `max_sessions: 6` → 6 once per minute.

### 5.2 `tests/test_capture_sessions.py` (the service, unchanged code; new claims the fan-out relies on)

- `test_two_request_ids_for_one_namespace_are_two_desktops_with_their_own_passwords`: two starts with the same target
  and interface and different `request_id`s create two containers with different names and different `VNC_PASSWORD`
  values, the owner's listing has two rows, ending one leaves the other.
- The existing `test_retry_is_idempotent_and_capacity_is_bounded` is unchanged (it already pins the same-id answer and
  the 429 at the fifth).

### 5.3 Browser tests

- `tests/test_capture_ui.js` (harness extended with radios, the ends fieldset, `#capture-launches`, a `health` answer
  and `localStorage` stubs through `captureMemory`/`rememberCapture` globals): every existing test keeps its claim; the
  three that read `$('capture-launch')` are rewritten to read the single link inside `#capture-launches` (the href
  pattern, the hidden state, the `javascript:` refusal); the test "a link opens on its first endpoint with that port
  ticked" becomes "a link opens in link mode with both ends ticked and the veth of each shown" (its mapping claims kept:
  `eth2` for r1, `eth2` for r2); "a link between two different kinds resolves the mapped interface on each end" keeps
  its two assertions through the ends' `<small>` texts instead of the endpoint buttons. New: `captureSummary` for the
  four plans and the Start label; the open-as control hidden at one box and in link mode; All connected never ticks
  `eth0`, a tap or `fabric`; None clears; a device-mode `each` submit sends `captures` with one entry per interface and
  the single-form body when `one`; a link submit sends two entries with the two target ids; an end whose device has no
  target is disabled with its sentence and the submit sends one entry; a `refused` answer shows started links and the
  sentence; the pre-check sentence appears with 3 own sessions and 2 planned without a request; memory restores only
  live interfaces, is ignored with a hint or a preset, is written on Start with `separate`; the link menu's three items,
  the disabled reason when `captureEnabled === false`, Enter on the first item opening link mode, `closeLinkMenu(true)`
  focusing the wire; the sessions list labels (`vsw ge-0/0/0 (eth1) · parity`), `End all my sessions` hidden at zero,
  the confirm text with the count, the result sentences; the Tools caption text at 1 and 2 and hidden at 0.
- `tests/test_shell_ui.js`: `captureMemory` returns `null` on a missing key, on invalid JSON and when storage throws;
  `rememberCapture` refuses a 2001-character record; `closeMenus()` closes an open `#link-context-menu` through the
  guard and returns `true`.
- `tests/test_device_diagnostics_ui.js`: **Capture all** rendered only with two or more `data` rows, carrying the
  capture attributes, calling `openCapture(detailName, '', null, {preset: [data names]})`.
- `tests/test_page_load_ui.js`: no new script; the new ids (`capture-ends`, `capture-openas`, `capture-all`,
  `capture-none`, `capture-launches`, `capture-end-all`, `capture-sessions-caption`, `tools-capture-end-all`,
  `link-context-menu`) are in `index.html` and `capture-launch`/`capture-endpoints` are gone from both files (the
  `grep -o "\$('…')"` rule of the addendum).

### 5.4 `deploy/capture/smoke.py` (CI, the real stack on loopback)

After the existing single-session checks and before the end: start a **second** session on the same `lo` target with a
new `request_id`; assert its `id` differs, the listing has two rows, its `viewer_password` differs from the first's,
and both containers exist with distinct names; post the first body again (same `request_id`) and assert the same first
`id` (idempotency at the service); then end both and assert the listing is empty and no labelled container remains.
Cost: one more Wireshark container (1 GiB) for a few seconds. Nothing else in the smoke changes.

### 5.5 The fixture: a scripted capture stack (`docs/redesign/tools/fixture_manager.py --capture`)

With the flag the fixture does what `test_capture.py` does in-process: sets `CAPTURE_PROVIDER=edgeshark`, patches
`app.capture.read_discovery` to answer a `containers` list built from the fixture labs' running containers (`eth0`,
`eth1`, `eth2`, `lo` each; `tap1` for a Junos kind; `fabric` for cEOS) and the host namespace, and replaces
`captures.sessions` with a `ScriptedSessions` object: `POST sessions` creates a row (cap 4, 429 past it, the same id for
the same owner + `request_id`), `GET sessions` lists the owner's rows, `GET sessions/<id>` answers `running: true` and
a fake password, `POST …/end` removes, `health` answers `{ready: true, max_sessions: 4}`, assets answer 404 forever (the
viewer page shows `Starting Wireshark…` then offers Reconnect, which is the honest fixture state). `fixture_control`
gains `capture: {fail_next_start: n}` so QA can force the mid-set refusal. The Playwright pass (`clab-ui-qa`): the wire
menu by right-click and Shift+F10, link mode with both ends, Start 2 captures and two Open links, device mode with
All connected and `One Wireshark per interface`, the pre-check sentence at 3 + 2, the mid-set `refused` state, memory
across a reload, End all from the card and from the dialog, the disabled state with `--capture` absent, at
1440/1280/760/390.

CI: `.github/workflows/release-check.yml` runs `test_capture*.py` as a glob, so a new Python file named
`test_capture_*.py` runs without a list change; the browser tests go into existing files. The lead confirms.

## 6. Documentation

- `docs/CAPTURE.md`: first paragraph — after "a link opens on its first endpoint" → "a link opens with **both ends**
  ticked (one Wireshark per end, since each end is its own container); right-click a link for a menu of the two ends;
  **All connected** ticks every wired port of a device and **Open as** chooses one Wireshark for them all or one per
  interface; the dialog remembers your last selection per device and link in this browser." "Sessions and files" — a
  bullet: "**End all my sessions** (the Tools card and the dialog) ends every session started from this browser, after
  one confirmation; other browsers' sessions are untouched." and in the limits bullet: "The 4-session limit counts every
  browser on the VM: one Wireshark per interface or per end uses one slot each, and the dialog says before starting when
  a plan would pass it." "Coverage" — "Multiple interfaces in one namespace share a PCAPNG stream, or open one Wireshark
  each when you choose *One Wireshark per interface*. Separate namespaces use separate sessions, so both ends of a link
  are two sessions." "Architecture" — one sentence: the manager keeps an in-memory label (lab, device, port names) for
  the sessions it started and never stores them; the set launch validates every entry against one fresh discovery
  before starting any.
- `capture-setup.html` §2: "On a link both ends are captured, one Wireshark each; right-click a link to pick one end."
  §3: "**End all my sessions** ends every session of this browser at once."
- `clab-backup-ui/NODE-FEATURES.md` "Node actions" (the Capture bullet): "The Interfaces section's **Capture all** opens
  the dialog with every data interface ticked; the dialog's *Open as* chooses one Wireshark or one per interface."
- `docs/LAB-OPERATIONS.md` line 182 (the right-click list): "right-click a link for Capture both ends or one end".
- `docs/redesign/inventory/capture.md` is history (pre-redesign) and is not edited; the capabilities it lists keep
  working (§8 names the two whose form changes).

## 7. Build slices, acceptance checks, the live pass

| Slice | Owner | Files (disjoint) | Size |
|---|---|---|---|
| S1 manager | `clab-backend-engineer` from §2; `risk-reviewer` on the diff (cookie scope, the pre-check, `known`, the whitelist) | `app/capture.py`, `app/capture_sessions.py`, `tests/test_capture.py`, `tests/test_capture_sessions.py` (§5.2 only) | M (about 120 lines of code, 200 of tests) |
| S2 UI | `clab-ui-builder` from §3; `clab-ui-reviewer` on the diff | `app/static/capture.js`, `app/static/shell.js` (memory functions, `closeMenus`, the two window listeners), `app/static/index.html` (dialog markup, the Tools card, `#link-context-menu`), `app/static/style.css` (two rules), `tests/test_capture_ui.js`, `tests/test_shell_ui.js` | L (about 220 lines of code, 300 of tests) |
| S2b table button | `clab-ui-builder`, after C04 S2 has landed in `device-diagnostics.js` (one owner per file) | `app/static/device-diagnostics.js`, `tests/test_device_diagnostics_ui.js` | XS |
| S3 smoke and fixture | `clab-devops-engineer` (smoke) and `clab-ui-qa` (fixture flag, `fixture_control`) | `deploy/capture/smoke.py`, `docs/redesign/tools/fixture_manager.py`, `docs/git-redesign/tools/fixture/fixture_control.py` | S |
| S4 docs | `docs-auditor` | `docs/CAPTURE.md`, `app/static/capture-setup.html` (text only), `clab-backup-ui/NODE-FEATURES.md`, `docs/LAB-OPERATIONS.md` | S |
| Lead | release records, the live pass, `evidence/c07-live-capture.md`; CI list check | | |

Shared contracts: S1 and S2 share §2.2's request and response shapes and §2.3's `public_session` keys; S2 can start on
the fixture's single-session answers and the harness while S1 is in flight. S2 and C05's UI slice both touch
`index.html` (C05 adds the map caption, S2 the dialog and the menu element): the lead sequences them or gives S2 a
worktree. `topology.js` and `topology-render.js` are not touched by this chunk.

Acceptance checks for `/clab-slice-verify`:

S1: `PATH="$PWD/.venv/bin:$PATH" .venv/bin/python -m unittest discover -s tests -t tests -p "test_capture*.py" -v`, then:
(1) a set never creates a container before every entry validated (zero service calls on every 409 of §4); (2) the
single body and response are byte-identical in behaviour (the existing tests untouched and green); (3) derived request
ids are deterministic and distinct per index; (4) `GET /sessions` never returns a key outside `PUBLIC_SESSION + (lab,
device, ports)` whatever the service adds; (5) `end-all` is cookie-scoped (a second `TestClient` without the cookie gets
404, with another cookie ends nothing of the first); (6) no `Store` key and no event carries a session id's password or
a URL (grep the events for `viewer_password` and `packetflix`); (7) `capture_service.py`, `compose.capture.yml` and
`setup-capture.sh` are unchanged (`git diff --stat`).

S2: `node --test tests/test_capture_ui.js tests/test_shell_ui.js tests/test_page_load_ui.js tests/test_topology_menu_ui.js`,
`node --check app/static/capture.js app/static/shell.js`, then: (1) a wire's left click still opens the dialog in one
click, right-click opens the menu with the first item focused; (2) the open-as control is absent with one box and in
link mode; (3) All connected never ticks `eth0`, `tapN`, `lo`, `fabric*`; (4) the submit body is the single form unless
`each` or link mode; (5) the pre-check sentence appears without a request; (6) memory is ignored when a hint or a
preset was given, and ticks only live names; (7) `esc()` on every label, port and detail (grep the templates); (8) no
document/window listener outside `shell.js` (grep `capture.js` for `document.addEventListener|window.addEventListener`);
(9) no inline style; (10) `#capture-launch` and `#capture-endpoints` referenced nowhere (`grep -rn` over `app/static`,
`tests`, `docs/*/tools`).

S3: `python3 deploy/capture/smoke.py` on an isolated Docker host (CI) passes with the second session; the fixture with
`--capture` serves the dialog and the QA pass of §5.5 at four viewports.

**Live pass on the `parity` lab (the lead, one operator; the stack is up; memory 26 GB available at design time):**
with the manager rebuilt from the tree: (1) right-click the `vsw — vrt` wire: the menu reads `vsw: ge-0/0/0 — vrt:
ge-0/0/0` with three items; choose **Capture both ends…**: the dialog shows both ends ticked with `eth1` under each and
the plan sentence; **Start 2 captures**; two links `Open Wireshark: vsw ge-0/0/0 ↗` and `… vrt ge-0/0/0 ↗`; open both
tabs; from `vsw`'s CLI (Open CLI) `ping` the `vrt` interface address (or `vrt` → `vsw`), and confirm the same ICMP
packets appear once in each Wireshark (both ends, two desktops); (2) the Tools card reads `2 Wireshark sessions running
from this browser.`; the dialog lists `vsw ge-0/0/0 (eth1) · parity` and `vrt ge-0/0/0 (eth1) · parity` with `ends in
…`; (3) device mode on `ceos` from its drawer: **All connected** ticks `eth1`, `eth2` only (not `fabric`, `cpu`, `eth0`),
choose **One Wireshark per interface**: the plan says `(2 sessions)` and, with two running, the pre-check sentence
appears (`2` + `2` = the limit, allowed) — start them: four sessions; then on `vsw` try one more: the dialog's sentence
without a request; (4) reload the page, open `ceos` again: `Your last selection here was restored.` with `eth1`, `eth2`
and `each`; (5) **End all my sessions** from the card: confirm names `4`; the result `Ended 4 sessions.`; the card
caption disappears; `docker ps --filter label=org.clab-manager.capture-owner` is empty; Tools › action logs show four
`capture.launch` and one `capture.end_all` with no password or URL; (6) the viewer tabs of the ended sessions show the
service's "ended" sentence on their next heartbeat. Record in `evidence/c07-live-capture.md`. Never more than four
sessions; end everything before leaving.

## 8. Assumptions, dead ends removed, not pursued, what to attack

Assumptions: the service's `/health` keeps `max_sessions` (it does at 1.31.2; the page and the manager default to 4
without it); a popup blocker allows one `target="_blank"` link per click (the per-session links need no `window.open`);
two Wireshark desktops on one namespace do not disturb each other at Edgeshark (packetflix opens one capture stream per
websocket; the smoke proves two desktops exist and the live pass that both show packets); the parity cEOS's `fabric*`,
`mirror*`, `cpu` names stay outside the drawing (they are, so "All connected" excludes them by construction);
`displayed_interface` returns the veth name unchanged for a kind without a rule (verified in `topology.py:107-119`),
so a label never reads empty.

Dead ends removed: comparing two ends of a link side by side needed two dialog rounds and two Starts (now one Start,
two links); capturing every wired port of a device needed ticking each (All connected); a student who wanted one window
per interface could not get it (Open as); every dialog open started from scratch (memory); ending four sessions took
four confirmations (End all); the 4-session limit was met as the service's 429 after a start (now counted before, with
the way out); a session row read `clab-parity-vsw · eth1` (now `vsw ge-0/0/0 (eth1) · parity`).

Changed in form, capability kept (the zero-regression rule): the endpoint buttons that switched the dialog to one end
become the ends checklist and the menu's per-end items (one end is still one click away: the menu item, or untick the
other end); the single **Open Wireshark ↗** link becomes one link per session (one session, one link, same href).

Not pursued, with the reason: one viewer window with tabs for several sessions (R055): the viewer page is one RFB, one
heartbeat, one download and one end per session, and two desktops side by side at 1180 px wide is not usable on the
student's laptop; two tabs are. A "Linked" preset that ticks only interfaces with a peer in the drawing: every connected
interface has a peer by construction, so it equals All connected. A per-device "capture inside the node's network
namespace" option (upstream's): Edgeshark already captures in the namespace. A service `close-all` route: the manager's
loop over at most four owner-scoped ends needs no new service surface.

Attack (for `risk-reviewer`): the set launch's two validation passes (manager, then service per entry) against a
target that changes between entries; the derived request ids (can a crafted `request_id` collide across owners? No:
the service keys on owner + request id; and the manager's derivation is a hash of the student's own id); the
pre-check's dependence on the owner-scoped listing (it is a convenience, the service's 429 is the authority: confirm
no code path treats the pre-check as the cap); `known` as an unbounded or stale map (pruned on every listing, capped
at 64); `public_session` as the only path from a service row to the browser (grep for `request('GET', 'sessions'`);
`end-all` with a forged or missing cookie (404 before any service call); events: labels and interface names only;
`capture_service.py` unchanged. (For `clab-ui-reviewer`): the right-click menu replacing today's right-click-opens-
dialog (one more keystroke on the keyboard path, stated); both ends ticked by default costing two slots of four (the
plan sentence and the Start label say so before anything starts); the open-as control appearing and disappearing with
the tick count (is that discoverable?); the memory sentence not reading as an error; the Tools caption going stale
between tab shows (no polling by design, End all re-lists); the four-viewport fit of the ends fieldset and two Open
links at 390 px; whether `Start 2 captures` is the right verb for a student who thinks in Wiresharks (alternative:
`Open 2 Wiresharks`, rejected because the viewer still needs a click per tab); the mid-set `refused` state at HTTP 200
(a result with a problem, shown with the started links) against a plain error.

Open questions for the lead: (a) should the default for a wire's left click be both ends (this design, upstream's
summary) or the first end as today (one slot)? The design takes both and the memory per link remembers an untick.
(b) Should `end-all` be offered in the Lab actions ▾ menu as well? Not in this design (the card and the dialog are the
two homes of sessions). (c) The C03 `ceos` interfaces answer that failed once during the live facts is outside this
chunk; the lead may want a second read before the live pass.

**Lead's decisions on the open questions:** (a) a wire's left click opens the dialog in link mode with both ends ticked
(upstream parity; two slots, each named); (b) End all my sessions stays in the sessions list only, not in Lab actions ▾;
(c) the `ceos` interfaces refusal seen during the live probe was the helper's inspect-format defect fixed in `524fba4`
(C03-DESIGN §11), not a capture matter.

## 9. Review answers

One row per confirmed finding of `/clab-design-review` (R = risk-reviewer, U = clab-ui-reviewer); filled in after the
review, the lead's decisions binding.

| # | Finding | Answer | Where |
|---|---|---|---|
| | | | |
