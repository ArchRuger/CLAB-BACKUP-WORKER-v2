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
   refuses the set with the sentence of §4 (the common case: one student on the VM), where `own` leaves out the
   sessions that belong to this very `request_id` (the manager keeps `request_id → derived ids`, §2.2), so the
   idempotent retry of a set is never refused by its own first attempt; the entries are started one by one with
   derived request ids `sha256(request_id + ':' + target_id + ':' + '/'.join(interfaces))`: derived from the entry's
   content, not its position, so a retry of the same entry, in a full or a narrowed set, meets the same session at
   the service (which dedups on owner + request id) and never a duplicate desktop. The cap is global, so another
   browser can take a slot between the pre-check and the fourth start: any refusal of entry *i* stops the set and is
   reported as `refused` beside the `sessions` that started (HTTP 200: the request produced sessions; the page keeps
   the `request_id`, narrows to the refused entries and offers **Start the remaining <n>**, §3.1).
4. **Both ends of a link are two sessions** (two containers are two namespaces; one stream cannot cross a namespace),
   started as one set. Each session gets its own **Open Wireshark: <end> ↗** link in the dialog: a browser allows one
   popup per user gesture, so "open both in one click" would lose the second tab to the popup blocker, and a wrapper
   page showing two desktops (R055) is a rewrite of the viewer's per-session logic for little value (§8). Two tabs, one
   click each, both listed under Your capture sessions. **The one exception is a link whose two ends are on the same
   device** (a self-loop, drawn with coincident ends): both veths are one namespace, so the plan is one session with
   both names (the single body form), as R052's agreed answer says.
5. **The manager knows its own sessions.** `Captures.known` is an in-memory map `sid → record` where the record is
   **one shape**, `{lab, lab_id, device, ports, label, started}` (`lab` the lab's display name, `lab_id` its id),
   produced by `label()` at launch and by the same `label()` as the fallback for a session the manager did not launch
   (a manager restart), and read field by field by `public_session`; beside it `Captures.requests` maps `request_id →
   [derived sid, …]` for the pre-check and the retry rules of decision 3. `GET /api/capture/sessions` answers a public
   view built by whitelist from the service's owner-scoped listing (`id, name, interfaces, remaining_seconds,
   idle_seconds`) plus `lab`, `device`, `ports` from the record. The service's rows are never returned verbatim: a
   field the service may add later stays private until copied, as every other public view in this manager. Nothing is
   persisted: a session dies with the service, and the Store carries controlled metadata only.
6. **End all my sessions is one manager route**, `POST /api/capture/sessions/end-all {}`: the manager lists the owner's
   sessions through the service and ends each; "my" is the cookie, exactly as for every other session call, so the
   route can never reach another browser's session; one confirmation, one event, partial results reported. The browser
   looping over the rows was rejected: a closed tab mid-loop leaves half, and the action log would show N events for one
   decision.
7. **A remembered selection per lab and browser, through `shell.js`**: key `clab.capture.<lab id>.<scope>` with scope
   `node:<node name>` or `link:<a>:<ifa>|<b>:<ifb>`, value `{"interfaces": [...], "separate": bool, "ends": [bool, bool]}`
   (JSON ≤ 2000 characters, `try/catch` through `shellGet/shellSet`); the last open-as choice is also kept as the
   browser default `clab.capture.openas`. Memory is restored only for interfaces the live list still holds, and only
   when the dialog was opened without a hint, an `options.end` or a preset: a click on a specific port (a link endpoint,
   a row of C03's table, a menu item naming an end) is the student's current intent and wins. Memory is **written under
   the same condition** and only after a full success (every entry started), so a one-time menu choice of one end never
   rewrites what the wire's left click opens with. The Store and the lab record learn nothing of it.
8. **The wire gets a right-click menu; the left click stays one click to capture.** `#link-context-menu` (built by
   `capture.js`, markup and behaviour modelled on `#node-context-menu`) opens on contextmenu, the ContextMenu key and
   Shift+F10 over a wire with three items: **Capture both ends…**, **Capture <A>: <port>…**, **Capture <B>: <port>…**;
   left click, Enter and Space keep opening the dialog directly, in link mode with both ends ticked. PARITY.md's critic
   required that Capture stay one click away when a link menu is added: it does (the click); on the keyboard, the
   menu's first item is focused, so right-click (or Shift+F10), Enter opens the dialog in link mode with both ends
   ticked, and Enter on **Start 2 captures** starts them. **The link menu is handled like the node menu, never through
   `closeMenus()`** (the lead's decision after the review): `shell.js` carries the three exceptions explicitly (§3.2),
   the menu's own keydown closes it and returns focus to the wire, and it carries a lab guard as `contextLab` does.
   C05's impairment badge (its §4.3) changes neither the wire's attributes nor its hit path, and the menu builder is one
   function C05 or C06 may append to.
9. **"All" means the connected interfaces.** The dialog's **All connected** preset ticks the wired ports whose veth the
   VM lists (never `eth0`, never a `tapN`, never a fabric or mirror device: the parity cEOS lists 16 interfaces of which
   two are wired); **None** clears. C03's Interfaces table gets **Capture all** in its header, which passes the table's
   own `data` rows as the preset (`openCapture(node, '', null, {preset: [names]})`): the table knows the roles, the
   dialog knows the map, and each uses its own knowledge. Management and internal interfaces stay opt-in behind the
   existing toggle; capturing `eth0` is not refused (watching the manager's own SSH is a legitimate lesson), it is just
   never part of "all".
10. **The open-as control appears only when it means something**: two or more interfaces ticked on one device, or the
    two ends of a self-loop on one device (decision 4). In link mode between two devices the ends are separate sessions
    by nature, so the control is hidden and the summary says so, and names the choice where it exists. The Start
    button names what it will do (§3.1), so a student never starts four desktops by surprise.
11. **Refusals are counted before anything starts and worded with the way out** (§4): too many sessions (own count,
    set size, the global cap mid-way; three variants of the sentence, one per mode, because "open one Wireshark for all
    of them" is no remedy for two ends on two devices and "untick" is none for a single capture), an end of a link
    whose device the VM does not list (not running), the stack disabled or unreachable, a target that changed (named by
    its position in the set: a vanished target has no name the manager can show). There is no new refusal for a
    non-data interface (decision 9).
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
   409 `Capture target changed or disappeared. Refresh interfaces and select it again.` (the existing sentence; in a set
   prefixed by the entry's **position**, `Capture 2 of 2: `, because a vanished target has only its opaque HMAC id and
   no name the manager can show); duplicate names inside an entry or a name outside the target's list → 409 `Select
   interfaces from the refreshed live list.` (existing; in a set with the same position prefix); the same `(target,
   interface)` in two entries → 409 `The same interface is listed twice. Refresh interfaces and select again.`.
   **Nothing has been started when any of these fires.**
3. Label every resolved entry: `label(target, interfaces)` under the store lock → the lab and node whose
   `expected_container(lab, n)` equals `target['name']` (first match; the lab the page sent is not trusted for the
   match, the container name is) gives **the one record shape** `{'lab': lab['name'], 'lab_id': lab['id'], 'device':
   short_name or name, 'ports': [displayed_interface(kind, iface) for iface in interfaces], 'label': f'{device}
   {", ".join(ports)}', 'started': 0.0}` (`topology.py:107`: the NOS port name for a kind with a rule, the veth name
   unchanged otherwise); no match → `lab = lab_id = ''`, `device = target['name']`, `ports = interfaces`. The same
   function is the fallback in §2.3, so `known` and the listing can never disagree on keys.
4. Pre-check, sets of two or more entries only: `rows = self.sessions.request('GET', 'sessions', who)['sessions']`,
   `mine = set(self.requests.get(data.request_id, ()))` (the derived ids of an earlier attempt of this same request),
   `own = len([r for r in rows if r.get('id') not in mine])`, `limit = self.capacity()` (the service health's
   `max_sessions`, fetched at most once a minute, `4` when the health call fails or lacks it); `len(entries) > limit` →
   409 `CAPTURE_SET_TOO_LARGE`; `own + len(entries) > limit` → 409 `CAPTURE_SLOTS_OWN` in the variant the body form
   implies (§4: `captures` whose entries share one target → device; two targets → link). A single launch keeps today's
   path: the service's own 429 is its answer. The pre-check is a convenience for the common case; the service's 429 is
   the cap, and no code path treats a passed pre-check as a reservation.
5. Start in order: `rid = data.request_id if len(entries) == 1 else hashlib.sha256(f'{data.request_id}:{entry.target_id}:{"/".join(entry.interfaces)}'.encode()).hexdigest()`
   (content-derived: the same entry in a retried or narrowed set meets the same service session; duplicates were
   refused in step 2, so the ids are distinct); `self.requests[data.request_id] = [rid, …]` is written **before** the
   first service call (capped at 64 request ids oldest-first); the service call is today's call with that
   `request_id`; the session id is checked with `TOKEN` as today; the event `capture.launch` is written per started
   session with today's text (container and interface names: controlled metadata); `self.known[sid] = record` with
   `started = time.time()` (`known` is pruned to the ids the next listing returns and capped at 64 oldest-first, so a
   service that lost its rows never grows it; both maps are read and written under `self.known_lock`, a
   `threading.Lock`, because the routes run on the threadpool). **Any `HTTPException` on entry *i*** (the adapter's
   mapped 429, 409, 503 or 502, and the manager's own `TOKEN` 502) stops the set: this entry and the remaining ones go
   to `refused` with the sentence of the exception. After a **502** (the adapter's transport failure or timeout: the
   container may have been created before the reply was lost) the owner's sessions are re-listed **once**; a row whose
   id equals the entry's derived `rid` is moved into `sessions` as started (its record written, its event logged);
   otherwise that entry's `refused` detail reads `This capture may have started; see Your capture sessions. <mapped
   sentence>`. When **no** entry started, raise the first exception as today (a single launch is unchanged; a set that
   fails at its first entry is a plain error).
6. Response: `{'sessions': [{'id', 'url', 'name', 'interfaces', 'label'}], 'refused': [{'position', 'label',
   'interfaces', 'detail'}], 'message'}` (`position` is `'Capture 2 of 2'`; `label` is the record's label, or the
   position when the entry never resolved) plus, when at least one started, `'id'` and `'url'` of the first (the old
   shape, for an old page). `message`: one started → today's sentence; several → `Wireshark started on the VM for <n>
   captures. Open each viewer below.`; with `refused` → `Wireshark started for <labels of started>; not for <labels of
   refused>: <detail of the first refused>` (one sentence).

### 2.3 `GET /api/capture/sessions` (`capture_sessions.py`, `install()`)

```python
PUBLIC_SESSION = ('id', 'name', 'interfaces', 'remaining_seconds', 'idle_seconds')
def public_session(row, record):
    """record: the one shape label() makes ({lab, lab_id, device, ports, label, started}), from known or the fallback."""
    out = {k: row[k] for k in PUBLIC_SESSION if k in row}
    out.update({'lab': record['lab'], 'device': record['device'], 'ports': list(record['ports']), 'label': record['label']})
    return out
```

`sessions()` lists through the service as today, prunes `captures.known` to the ids returned, and answers
`{'sessions': [public_session(row, captures.record_for(row))]}` where `record_for(row)` is `known[row['id']]` when
present, else `label({'name': row['name']}, row['interfaces'])` (step 3 of §2.2: store lock, container-name equality,
the same function, the same keys). `id` must match `TOKEN` or the row is dropped. The per-session status route
(`GET /sessions/{sid}`, the viewer's heartbeat, with `running` and `viewer_password`) is **unchanged**; the viewer page
only sets its own `document.title` from that answer (§3.5).

### 2.4 `POST /api/capture/sessions/end-all`

Body `{}` (the guard needs a body). `who = owner(request)` (a browser without the cookie gets today's 404 sentence:
it owns nothing). `rows = service().request('GET', 'sessions', who)['sessions']`; for each row with a valid id:
`service().request('POST', 'sessions/<id>/end', who, {})`; a 404 (expired between list and end) counts as ended; any
other `HTTPException` goes to `failed` with the **fixed sentence** `Could not end <label>; try End session on its row.`
(the adapter's mapped text would send the student to the setup page over a one-off cleanup failure, so it is not
shown here) and the loop continues. Response `{'ended': n, 'failed': [{'id', 'label', 'detail'}]}` (`label` from the
record). One event `capture.end_all`: `Ended <n> browser Wireshark session(s) and removed their temporary files.` (and
`; <m> could not be ended` when `failed`). `known` drops the ended ids. No row → `{'ended': 0, 'failed': []}`, no event.

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
eth1 for ge-0/0/0 yet: the device may still be starting, or the topology changed.` (box unticked and disabled) / `The
diagram calls this port Ethernet0/1, but the VM lists no interface with that name.` (a kind without a `PORT_RULES`
entry: cisco_iol, SR OS, vMX; box unticked and disabled) / `vrt is not running on the VM (no live interfaces), so this
end cannot be captured now.` (box unticked and disabled) / `this diagram node is not in the inventory — choose its
device under Advanced` (today's sentence, box disabled). **Under every disabled end** a button `<button type="button"
class="button secondary small" data-capture-choose="i">Choose the interface on <device>…</button>` (today's endpoint
button, kept per end): it leaves link mode for **device mode on that end** with today's hint (`captureNode = ep.node`,
`captureHint = ep.interface`, scope `lab`; scope `host` and `captureNode = ''` for a node outside the inventory), so the
student gets today's sentences and ticks the matching interface by hand, exactly as before this chunk. Link mode never
unfolds Advanced by itself and its label stays `Advanced: capture somewhere else` (the auto-unfold rule of
`refreshCaptureTargets` applies to device mode only, because the lab-wide fetch of link mode selects no single
target); choosing a target under Advanced in link mode leaves link mode for device mode on that target. The scope
select and Refresh interfaces keep working. **Both ends on one device** (same resolved target): the plan is one session
with both veths (decision 4), the summary says `Both ends are on <device>: one Wireshark for eth1, eth2.` and the open-as
control is shown with `one` selected (`each` makes two). The summary (below) counts the ticked, resolvable ends.

**Open as** (`#capture-openas`, a fieldset of two radios, name `capture-openas`, **placed after the Other interfaces
toggle and before `#capture-status`**, so its appearance never shifts the boxes under the pointer): `One Wireshark for
the ticked interfaces` (value `one`) and `One Wireshark per interface` (value `each`). Shown only in device mode with
two or more ticked interfaces, and in the same-device link case; hidden otherwise. Default from memory for the key,
else `clab.capture.openas`, else `one`. Changing it calls `invalidateCapture()` like any selection change. The plan
sentence names it while it is hidden by the count: see below.

**Presets**: in the Connected fieldset's legend row two small buttons, `<button type="button" … id="capture-all">`
**All connected** and `<button type="button" … id="capture-none">` **None** (device mode, shown only when the Connected
list has two or more boxes; `type="button"` because the whole dialog is one `<form>` whose submit starts a capture).
`options.preset` (from C03's table) ticks exactly the named interfaces that are in the live list; names not live are
reported with today's "not found" sentence. When a preset or memory ticks a box inside the collapsed `#capture-more`,
that `<details>` is opened so nothing is ticked out of sight.

**Summary and the Start button** (`captureSummary(mode, ticked, separate, ends)`, pure, tested): the button reads
`Start capture` (one session), `Start 2 captures` (per-interface or two ends: `Start <n> captures`), and is disabled
with no ticked interface or end. `#capture-status` carries the plan before Start: `One Wireshark for eth1, eth2 on vsw
(or one Wireshark per interface, under Open as).` / `One Wireshark per interface: eth1, eth2 on vsw (2 sessions).` /
`Both ends of the link: vsw ge-0/0/0 (eth1) and vrt ge-0/0/0 (eth1), one Wireshark each (2 sessions).` / `One end: vrt
ge-0/0/0 (eth1).` The slot arithmetic is done on the page before the request: `ownCount` (from a **fresh**
`/capture/sessions` fetch made when Start is pressed, never from the stale listing) + planned > `captureLimit` (from
`/capture/health`, read with the status at dialog open, default 4) → `#capture-status` reads the slot sentence in the
mode's variant (§4) and Start answers with it without a launch request; **the page skips this check when Start is a
retry that keeps its `request_id`** (the server excludes that request's own sessions, §2.2 step 4, and answers
idempotently). The server repeats the check; a stale page meets the server's sentence.

**Submit**: `mode === 'link'` → `captures` = one entry per ticked end (`target_id` of that end's container,
`interfaces: [veth]`), or the single body with both veths when both ends resolve to one target and `one` is selected;
device mode with `each` → one entry per ticked interface; otherwise today's single body. The `request_id` rule:
kept across uncertain retries, **kept after a response with `refused`**, reset on a full success and on any change of
the selection. **Results**: `#capture-launch` (one link) becomes `#capture-launches`, a container of one `<a
class="button primary" target="_blank" rel="noopener" href="/static/capture-session.html#<id>">Open Wireshark: <label>
↗</a>` per started session (one link in the single case, the old test claims kept: exactly one link, same href pattern,
the `javascript:` refusal); each `href` is checked against today's pattern before it is set. Clicking a link sets
today's "opened in a new tab" sentence with the label. **After a partial result** (`refused` non-empty) the dialog
narrows to the refused entries: the started ends or interfaces are unticked and their boxes disabled with `started
(open it above)`, the started links stay, the status shows the manager's sentence, the Start button reads `Start the
remaining <n>` and sends only the refused entries **with the kept `request_id`** (the content-derived ids make an entry
that in fact started during a lost reply come back as the same session instead of a duplicate; a new `request_id` would
forfeit that, §9 row 3). Memory is written only after a full success.

**Memory** (`shell.js`): `captureMemory(labId, scope)` → the parsed record or `null`; `rememberCapture(labId, scope,
record)` (serialises, refuses over 2000 characters, returns `false` when storage throws); `captureOpenAs()` /
`rememberOpenAs(value)`. `capture.js` reads memory in `renderCaptureInterfaces` when `captureHint` is empty and no
`options.preset`/`options.end` was given, intersects `interfaces` with the live list, ticks those, applies `separate`
to the radios, applies `ends` in link mode; when at least one box was restored the status says `Your last selection
here was restored.` before the plan sentence; a record whose interfaces are all gone is ignored silently. It writes
memory on a successful Start (the ticked set and the mode as started). Nothing is written on open or on a refusal.

**Sessions in the dialog** (`#capture-sessions`): rows read `<a …>vsw ge-0/0/0 (eth1) · parity</a> <span
class="caption">at most 1 h 58 min left (15 min once its viewer is closed)</span> <button type="button" class="button
secondary" data-end-capture="<id>">End session</button>` (label from `device` + `ports` with the container interface
in brackets when a port name differs, lab from `lab`; a row without a lab match reads the container name as today; the
time is an upper bound because the list is not polled and an idle session is reaped after 15 minutes);
`<button type="button" class="button danger" id="capture-end-all">` **End all my sessions** next to Refresh list,
hidden when the list is empty (`danger`: it deletes files, like the per-row End session's confirm says), with the
pluralisation rule `plural(n, 'session')` → `1 session` / `2 sessions` used everywhere a count is shown:
`confirm('End the 1 Wireshark session started from this browser and delete its capture files? Download saved files
first.')` / `confirm('End all 3 Wireshark sessions started from this browser and delete their capture files? Download
saved files first.')`, then `POST /capture/sessions/end-all {}`; the button's idle label is captured first and
restored after (`const label = button.textContent`, addendum rule 4), it reads `Ending…` and is disabled meanwhile; the
result sentence `Ended 1 session.` / `Ended 3 sessions.` or `Ended 2 sessions; 1 could not be ended: Could not end vsw
ge-0/0/0 (eth1); try End session on its row.` goes to `#capture-status`; then the list refreshes. Per-row End session
is unchanged.

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
link mode (`openCapture('', '', ends)` or with `{end: i}`) and closes the menu; `closeLinkMenu(restore)` hides it and
restores focus to the wire when asked. The wire's `contextmenu` listener (today: opens the dialog) opens the menu
instead; a `keydown` of `ContextMenu` or Shift+F10 on a focused wire opens it at the wire's box; click, Enter and Space
are unchanged (dialog, link mode, both ends ticked). **Lab guard**: `linkMenuLab = activeId` at open; a click while
`linkMenuLab !== activeId` closes the menu and does nothing (the `contextLab` rule of the node menu).

**Dismissal: handled like the node menu, never through `closeMenus()`** (the lead's decision). `capture.js` may not add
a document or window listener, so `shell.js` carries three explicit exceptions, each pinned in `test_shell_ui.js`:
(1) `shellPointerDown`: the `closest()` selector becomes `'.menu, details#lab-switcher, #link-context-menu'`, so a
pointerdown **inside** the link menu passes it as `except` and the menu survives until the item's click; a pointerdown
**outside** it calls `typeof closeLinkMenu==='function'&&closeLinkMenu()` after `closeMenus(...)` (the right-click on a
device that opens the node menu is such a pointerdown, so the two menus are never open together from the mouse);
(2) `shellEscape` returns early while `#link-context-menu` is open, exactly as it does for `#node-context-menu`, so the
menu's **own keydown** (an element listener in `capture.js`) handles Escape with `closeLinkMenu(true)` and focus
returns to the wire; that keydown also roves with ArrowUp/Down/Home/End and closes the menu on Tab (so a keyboard user
cannot leave it open and then open the node menu with Shift+F10 on a device); (3) the new `window` `resize` and `blur`
listeners in `shell.js`, and a capture-phase `scroll` listener next to them (the node menu's `topology.js:112-113`
rule: a menu must not float away from its wire), call **only** `typeof closeLinkMenu==='function'&&closeLinkMenu()`,
never `closeMenus()`, so an opening soft keyboard or a tab switch never closes the save chip panel or the Load panel.
`topology.js` is not changed; `openLinkMenu` calls `closeNodeMenu()` as the wire's contextmenu handler does today.

### 3.3 Sessions on the Tools card (`capture.js`, `index.html`)

The Packet capture card gains `<p class="caption" id="capture-sessions-caption" hidden></p>` and, in its `.actions`,
`<button type="button" class="button danger" id="tools-capture-end-all" hidden>End all my sessions</button>`. One
state object `captureSessionsState = {rows, fetched}` feeds the card and the dialog: `renderCaptureSessions()` writes
both places. The caption reads `1 Wireshark session running from this browser.` / `<n> Wireshark sessions running from
this browser.` and is hidden at zero; the button shows at one or more and runs the same confirm and route as the
dialog's (label captured and restored). The listing is refreshed **wherever the Tools view is shown**: one line in
`app.js`'s `showTab(value)`, `if(tab==='tools'&&typeof refreshCaptureSessions==='function')refreshCaptureSessions();`
beside the existing `refreshMap()` hook, which covers the click, the arrow keys (`tabKeydown`), a page opened at
`#view=tools` and Back/Forward alike; also when the dialog opens, after every launch and every end; never on a timer
(the inventory's "NOT auto-polled" stands; End all re-lists at the service, so it never acts on a stale count). When
`captureEnabled === false` the caption of today (`Packet capture is not set up…`) is shown and the sessions caption and
button are hidden.

### 3.4 C03's Interfaces table (`device-diagnostics.js`)

The table header row gains `<button type="button" class="button ghost small" data-diag-capture-all>Capture all
connected</button>` (the dialog's preset name, so the two controls name one idea) beside the caption, rendered only
when two or more `data` rows exist and carrying `captureActionAttrs()`; the click calls `openCapture(detailName, '',
null, {preset: <the data rows' container names>})`. The per-row Capture button is unchanged. The getter and the poll
plan are untouched (C04 S2 owns its own lines in this file; see §7 for ordering).

### 3.5 The viewer page: one line (`capture-session.js`)

Up to four viewer tabs open at once, so each must be tellable apart in the tab strip: `status()` sets `document.title
= data.name + ' · ' + data.interfaces.join(', ') + ' — Wireshark'` from the status answer it already reads (the
toolbar's `#capture-name` is unchanged). Nothing else in the viewer, the status route or the service changes.

What does not change on the pages: the node menu's Capture item; `nodeActions`' Capture button; the Lab actions item;
the Advanced selector and scope; the tap rule; the "not found" sentences; `#capture-sessions-refresh`; the setup
page's structure (two sentences change, §6).

### 3.6 States, in one place

Default: device mode as today with the presets visible at two or more connected boxes; link mode with both ends ticked
and the plan sentence. Loading: `Looking up interfaces on the VM…` (today), Start disabled. Empty: device without live
interfaces (today's sentence); link with neither end resolvable: `Neither end of this link is on the VM right now. Start
the lab, or choose a device under Advanced.` Error: the manager's sentence verbatim in `#capture-status`, Start
re-enabled (today). Success: the per-session links and the message. Disabled: the stack off → every entry point
disabled with the reason, the dialog explains and links the setup page (today); End all hidden. Cancel: closing the
dialog invalidates the plan, never ends a session (today). Retry: Start again reuses `request_id` until a change
(today); after a partial result the dialog is narrowed to the refused entries and Start reads `Start the remaining <n>`
with the kept `request_id` (§3.1). Reconnect: a session row's link reopens the viewer; the viewer's own Reconnect is
unchanged. Keyboard: native checkboxes and radios, labelled; the menu roves; `#capture-status` is the one
`role="status"`; focus returns to the wire after the menu closes with Escape (the menu's own keydown, §3.2).

## 4. Every refusal, with its wording

| Case | Where | HTTP | Sentence |
|---|---|---|---|
| set larger than the cap (device mode) | server `CAPTURE_SET_TOO_LARGE`; page before the request | 409 | `<k> separate Wireshark sessions are more than the limit of <limit> at a time. Untick interfaces, or open one Wireshark for all of them.` (a link set has at most two entries, so this is device mode only) |
| own sessions + set over the cap, **device mode** (the set's entries share one target, or `each` on the page) | server `CAPTURE_SLOTS_OWN_DEVICE`; page before the request | 409 | `You already have <n> Wireshark <session/sessions> running from this browser; <k> more would pass the limit of <limit> at a time. End a session under Your capture sessions, untick interfaces, or open one Wireshark for all of them.` |
| own sessions + set over the cap, **link mode** (two targets) | server `CAPTURE_SLOTS_OWN_LINK`; page before the request | 409 | `You already have <n> Wireshark <session/sessions> running from this browser; both ends would pass the limit of <limit> at a time. End a session under Your capture sessions, or untick one end.` |
| own sessions at the cap, **a single capture** | page only (the server keeps today's path: the service's 429) | — | `You already have <n> Wireshark <session/sessions> running from this browser, the limit at a time. End a session under Your capture sessions first.` |
| the global cap reached mid-set (another browser's sessions) | server, in `refused` | 200 with `refused` | `Wireshark started for <labels>; not for <labels>: All browser capture slots are in use. End a session or wait for expiry.` |
| any other refusal mid-set: the service's 409 (its own discovery disagrees), 503, the adapter's 502, the manager's `TOKEN` 502 | server, in `refused` | 200 with `refused` | the exception's sentence; after a 502 with no re-listed row: `This capture may have started; see Your capture sessions. <sentence>` |
| the global cap reached on a single launch or the first entry | service 429 through the adapter | 429 | `All browser capture slots are in use. End a session or wait for expiry.` (unchanged) |
| an entry's target changed or vanished | server, nothing started | 409 | `Capture 2 of 2: Capture target changed or disappeared. Refresh interfaces and select it again.` (position, never a label: the target has none) |
| an interface not in the fresh list, or twice in one entry | server, nothing started | 409 | `Select interfaces from the refreshed live list.` (unchanged; in a set with the position prefix) |
| the same interface in two entries | server, nothing started | 409 | `The same interface is listed twice. Refresh interfaces and select again.` |
| a retry of a set that already started (same `request_id`) | server: the request's own sessions are left out of `own`; page: no local check | 200 | the same ids again, no slot used |
| five or more entries, both body forms at once, neither | pydantic | 422 | (never built by the page) |
| a link end whose device the VM does not list | page, the end's box disabled | — | `<device> is not running on the VM (no live interfaces), so this end cannot be captured now.` |
| a link end whose veth is not listed yet | page, the end's box disabled | — | `The VM lists no <veth> for <port> yet: the device may still be starting, or the topology changed.` |
| a link end whose port has no veth mapping (a kind without a `PORT_RULES` entry) | page, the end's box disabled, **Choose the interface on <device>…** under it | — | `The diagram calls this port <port>, but the VM lists no interface with that name.` (today's sentence, shortened; the button leads to today's manual tick) |
| a link end whose diagram node is not in the inventory | page, the end's box disabled, **Choose the interface on <label>…** under it (scope host) | — | today's `this diagram node is not in the inventory — choose its device under Advanced` |
| neither end resolvable | page, both Choose buttons shown | — | `Neither end of this link is on the VM right now. Start the lab, or choose the interface by hand below.` |
| nothing ticked | page, Start disabled | — | `Choose a device and tick at least one interface.` (unchanged; link mode: `Tick at least one end of the link.`) |
| End all with no session | server | 200 `{ended: 0}` | page: `No capture sessions to end.` |
| End all, a session the service could not remove | server, in `failed`, the fixed sentence | 200 | page: `Ended 2 sessions; 1 could not be ended: Could not end <label>; try End session on its row.` |
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
  target `ens18`) → two service calls whose `request_id`s are `sha256('<rid>:<target_id>:eth2')` and
  `sha256('<rid>:<host id>:ens18')`, the response has two `sessions` with `label` `r1 eth2` and `init ens18`, `id`/`url`
  of the first, two `capture.launch` events, `requests[rid]` holds both derived ids, and `known` holds both ids with the
  one record shape (`lab='demo'`, `lab_id='lab'`, `device='r1'`, `ports`, `label`, `started`) for the first.
- `test_a_launched_session_is_listed_with_its_record` (launch, then list): the row of the launched id carries `lab
  'demo'`, `device 'r1'`, `ports`, `label 'r1 eth2'` from `known`, byte-equal to what the fallback produces for the same
  container name (the two paths return one shape).
- `test_a_set_is_validated_whole_before_anything_starts`: the second entry names `eth99` → 409 `Capture 2 of 2: Select
  interfaces…`, zero service calls; a vanished second target → 409 `Capture 2 of 2: Capture target changed…`, zero
  calls; the same `(target, eth2)` twice → 409 "listed twice".
- `test_the_own_slot_pre_check_refuses_before_starting_and_spares_the_requests_own_sessions`: `listing` with 3 rows
  and a device set of 2 → 409 `CAPTURE_SLOTS_OWN_DEVICE` with `3 Wireshark sessions`, `2`, `4` in the text and the
  device remedies, zero calls; a listing with 1 row reads `1 Wireshark session`; a link set (two targets) → the link
  variant (`untick one end`, no "one Wireshark for all"); a set of 5 is 422; with `capacity()` answering 6 (patched
  health), 3 + 2 passes; **the retry**: a set of 2 that started with `own = 2` is resent with the same `request_id`
  while the listing now holds 4 rows (its own two among them) → HTTP 200, the same two ids, no new service `POST`
  beyond the two idempotent ones, no 409.
- `test_a_mid_set_refusal_reports_started_and_refused`: `fail` on the second `POST` with 429 → HTTP 200, one session,
  one `refused` row with `position 'Capture 2 of 2'`, its label and the mapped 429 sentence, the message naming both
  labels; the same with a service **409** and with the manager's own `TOKEN` check failing on the second answer (an
  invalid `id`); `fail` on the first → HTTP 429 and no `sessions` key (a plain error, as today); a **502** on the
  second entry whose derived id then appears in the re-listing → that entry is in `sessions`, its event logged once;
  a 502 with no such row → `refused` with the "may have started" detail; the narrowed retry (only the refused entry,
  the same `request_id`) sends that entry's content-derived id and gets it back.
- `test_single_launch_body_and_response_are_unchanged`: the existing single tests are left as they are; this one
  additionally asserts the single response carries `sessions` of length 1 with the same `id`.
- `test_sessions_listing_is_a_whitelist_with_labels`: the fake listing returns rows with an extra `password` and
  `address` field → the manager's answer carries exactly `PUBLIC_SESSION + ('lab', 'device', 'ports', 'label')`, the
  lab **name** and device from `known` for a launched id and from container-name matching for an unknown id
  (`clab-demo-r1` → `demo`, `r1`), `ports` with `displayed_interface` for a Junos node fixture (`eth1` → `ge-0/0/0`),
  and a row with a bad id is dropped; `known` is pruned to the listed ids and capped at 64; `requests` capped at 64.
- `test_end_all_ends_only_the_cookies_sessions_and_reports_failures`: two rows → two `POST …/end` calls, `{ended: 2,
  failed: []}`, one `capture.end_all` event with `2`; a 404 on one end still counts; a 503 on one end → `failed` with
  the fixed sentence `Could not end r1 eth2; try End session on its row.` (never the adapter's setup sentence) and the
  other ended; an empty listing → `{ended: 0}` and no event; no cookie → 404; a cross-origin POST → 403; the request
  without a body → 413 (the guard).
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
  `eth2` for r1, `eth2` for r2); **the endpoint-switch test** "a link between two different kinds resolves the mapped
  interface on each end" (`test_capture_ui.js:179-190`) is rewritten as "a link between two different kinds resolves
  the mapped interface of each end, and unticking end 1 sends only end 2's veth": both ends' `<small>` read `eth1` and
  `eth4`, the plan names both, and after unticking r1's box the submit carries one entry with `['eth4']` (the two
  mapping claims kept, the switch claim restated as the untick). New: `captureSummary` for the plans and the Start
  label, with the `(or one Wireshark per interface, under Open as)` clause; the open-as control hidden at one box and
  in two-device link mode, shown with `one` for a same-device link whose submit is the single body with both veths;
  All connected never ticks `eth0`, a tap or `fabric`; None clears; a preset that ticks a box inside `#capture-more`
  opens it; a device-mode `each` submit sends `captures` with one entry per interface and the single-form body when
  `one`; a link submit sends two entries with the two target ids; **an unmapped kind on one end** (`Ethernet0/1` with no
  `capture_interface`) disables that end with the "diagram calls this port" sentence and shows **Choose the interface
  on <device>…**, whose click puts the dialog in device mode on that device with today's hint sentence and the manual
  list, and Advanced stays folded with the "capture somewhere else" label; an end whose device has no target is
  disabled with its sentence and the submit sends one entry; a `refused` answer keeps the `request_id`, shows the
  started links and the sentence, disables the started boxes, relabels Start `Start the remaining 1` and the next submit
  carries only the refused entry; a full success resets the `request_id`; the pre-check sentence (device variant)
  appears with 3 own sessions and 2 planned after a fresh listing fetch and without a launch request, the link variant
  for two ends, the single variant for one capture at 4, and **no pre-check on a retry with a kept `request_id`**;
  memory restores only live interfaces, is ignored with a hint, an `options.end` or a preset, is written only after a
  full success and only when the dialog was opened without any of the three; the link menu's three items, the
  disabled reason when `captureEnabled === false`, Enter on the first item opening link mode, the menu's own keydown:
  Escape → `closeLinkMenu(true)` focusing the wire, Tab closing it, the roving keys; a click with `linkMenuLab !==
  activeId` does nothing; **`type="button"`**: a click on All connected, None and End all my sessions sends no
  `/capture/launch`; the sessions list labels (`vsw ge-0/0/0 (eth1) · parity`), the upper-bound time text, `End all my
  sessions` hidden at zero and carrying `danger`, the confirm text at 1 and at 3, the result sentences at 1 and 3 and
  with a failure, the idle label restored after `Ending…`; the Tools caption text at 1 and 2 and hidden at 0.
- `tests/test_shell_ui.js`: `captureMemory` returns `null` on a missing key, on invalid JSON and when storage throws;
  `rememberCapture` refuses a 2001-character record; **the three link-menu exceptions**: a pointerdown inside an open
  `#link-context-menu` leaves it open (`closeLinkMenu` not called, `closeMenus` called with the menu as `except`) and a
  pointerdown outside calls `closeLinkMenu()`; `shellEscape` returns early while the menu is open (no `closeMenus`, no
  `closeLinkMenu` from shell, propagation not stopped: the menu's own keydown owns Escape); `resize`, `blur` and the
  capture-phase `scroll` call `closeLinkMenu()` only, and an open save panel (`[data-panel]` with `aria-expanded`) stays
  open through all three; `closeMenus()` itself never touches the link menu.
- `tests/test_readiness_ui.js` (`appHarness`, `showTab`): `showTab('tools')` calls a stub `refreshCaptureSessions`
  once, reached through `tabKeydown` with ArrowRight from the Devices tab; `showTab('devices')` does not call it; the
  page loads without the function defined.
- `tests/test_capture_session_ui.js`: after `status()` the context's `document.title` is `clab-demo-r1 · eth2 —
  Wireshark`; the toolbar text is unchanged.
- `tests/test_device_diagnostics_ui.js`: **Capture all connected** rendered only with two or more `data` rows, carrying
  the capture attributes, calling `openCapture(detailName, '', null, {preset: [data names]})`.
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
- **Frozen history, not edited** (the lead's decision after the review): the per-release check scripts under
  `docs/technical-audit/tools/`, `docs/ui-ux-cleanup/tools/` and `docs/netlab-ui-qa/tools/` still drive
  `#capture-launch` and `#capture-endpoints` (`check_release_1_30_36.py`, `live_1_30_37_b.py`, `check_release_1_30_39.py`,
  `check_release_1_30_42.py`, `check_restart_device.py`). They are dated acceptance records of their releases
  (REPOSITORY-MAINTENANCE's history folders), not the working regression tooling CLAUDE.md names
  (`docs/redesign/tools/`, `docs/ui-review-001/tools/`, `docs/lab-builder/tools/`, `docs/git-redesign/tools/`, none of
  which references either id: verified by grep at design time). The acceptance check S2 (10) is scoped accordingly.

## 7. Build slices, acceptance checks, the live pass

| Slice | Owner | Files (disjoint) | Size |
|---|---|---|---|
| S1 manager | `clab-opus-specialist` from §2 (`capture_sessions.py` is a privileged path, `routing-privileged-paths.md`); `risk-reviewer` on the diff (cookie scope, the pre-check and its `requests` exclusion, `known` and its lock, the whitelist, the 502 re-list) | `app/capture.py`, `app/capture_sessions.py`, `tests/test_capture.py`, `tests/test_capture_sessions.py` (§5.2 only) | M (about 150 lines of code, 260 of tests) |
| S2 UI | `clab-ui-builder` from §3; `clab-ui-reviewer` on the diff | `app/static/capture.js`, `app/static/shell.js` (memory functions, the three link-menu exceptions), `app/static/app.js` (the one `showTab` line), `app/static/capture-session.js` (the title line), `app/static/index.html` (dialog markup, the Tools card, `#link-context-menu`), `app/static/style.css` (two rules), `tests/test_capture_ui.js`, `tests/test_shell_ui.js`, `tests/test_readiness_ui.js` (the `showTab` case), `tests/test_capture_session_ui.js` | L (about 260 lines of code, 340 of tests) |
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
ids are deterministic per entry content and distinct within a set, and a retried or narrowed set with the same
`request_id` meets the same ids with no 409 and no duplicate container; (4) `GET /sessions` never returns a key outside
`PUBLIC_SESSION + (lab, device, ports, label)` whatever the service adds, and a launched row and a fallback row have the
same keys; (5) `end-all` is cookie-scoped (a second `TestClient` without the cookie gets 404, with another cookie ends
nothing of the first) and a failed end carries the fixed sentence; (6) no `Store` key and no event carries a session
id's password or a URL (grep the events for `viewer_password` and `packetflix`); (7) `capture_service.py`,
`compose.capture.yml` and `setup-capture.sh` are unchanged (`git diff --stat`); (8) `known` and `requests` are read and
written under one lock (grep).

S2: `node --test tests/test_capture_ui.js tests/test_shell_ui.js tests/test_readiness_ui.js tests/test_capture_session_ui.js
tests/test_page_load_ui.js tests/test_topology_menu_ui.js`, `node --check app/static/capture.js app/static/shell.js
app/static/app.js app/static/capture-session.js`, then: (1) a wire's left click still opens the dialog in one click,
right-click opens the menu with the first item focused, a mouse click on an item opens link mode (the pointerdown
exception), Escape returns focus to the wire; (2) the open-as control is absent with one box and in two-device link
mode, present for a same-device link; (3) All connected never ticks `eth0`, `tapN`, `lo`, `fabric*`; (4) the submit
body is the single form unless `each` or two-device link mode; (5) the pre-check sentence in the mode's variant appears
without a launch request after a fresh listing, and not on a retry; (6) memory is ignored when a hint, an `options.end`
or a preset was given, ticks only live names, and is written only after a full success under the same condition; (7)
`esc()` on every label, port and detail (grep the templates); (8) no document/window listener outside `shell.js` (grep
`capture.js` for `document.addEventListener|window.addEventListener`); (9) no inline style; (10) `#capture-launch\b`
and `#capture-endpoints\b` (exact ids, not `data-capture-endpoints`) referenced nowhere under `clab-backup-ui/app/static`,
`clab-backup-ui/tests`, `docs/redesign/tools`, `docs/ui-review-001/tools`, `docs/lab-builder/tools` and
`docs/git-redesign/tools` (the frozen per-release scripts of §6 are out of scope); (11) the three new buttons carry
`type="button"`; (12) an unmapped end offers **Choose the interface on <device>…** and lands in today's manual list.

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
choose **One Wireshark per interface**: the plan reads `(2 sessions)` and **no limit sentence appears** (2 running + 2
planned = 4, the limit, allowed); start them: four sessions; then on `vsw` try one more: the single-capture variant of
the slot sentence appears without a launch request; (4) reload the page, open `ceos` again: `Your last selection here
was restored.` with `eth1`, `eth2` and `each`; (5) **End all my sessions** from the card: confirm names `4`; the result
`Ended 4 sessions.`; the card
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
become the ends checklist, the menu's per-end items and, under every end the page cannot resolve, **Choose the
interface on <device>…**, which is the old endpoint button kept per end (one end is still one click away; the manual
tick for a kind without a port rule is still reachable); the single **Open Wireshark ↗** link becomes one link per
session (one session, one link, same href).

Not pursued, with the reason: one viewer window with tabs for several sessions (R055): the viewer page is one RFB, one
heartbeat, one download and one end per session, and two desktops side by side at 1180 px wide is not usable on the
student's laptop; two tabs are. A "Linked" preset that ticks only interfaces with a peer in the drawing: every connected
interface has a peer by construction, so it equals All connected. A per-device "capture inside the node's network
namespace" option (upstream's): Edgeshark already captures in the namespace. A service `close-all` route: the manager's
loop over at most four owner-scoped ends needs no new service surface.

Attack (for `risk-reviewer`): the set launch's two validation passes (manager, then service per entry) against a
target that changes between entries (the service's 409 mid-set is now a `refused` row); the derived request ids (can
a crafted `request_id` collide across owners? No: the service keys on owner + request id; the manager's derivation is
a hash of the student's own id and the entry's content, and duplicates are refused before derivation); the pre-check's
dependence on the owner-scoped listing (it is a convenience, the service's 429 is the authority: confirm no code path
treats the pre-check as the cap) and its exclusion of the request's own ids (can a student grow `own` past the cap by
retrying? No: the service answers the same sessions, no slot is used); `known` and `requests` as unbounded or stale
maps (pruned on every listing, capped at 64, one lock); the 502 re-list (one listing, matched by the derived id only);
`public_session` as the only path from a service row to the browser (grep for `request('GET', 'sessions'`);
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

One row per confirmed finding of `/clab-design-review`, in the review's order (28 confirmed: 5 must-fix, 19 should-fix,
4 optional; the 3 refuted ones, `known` pruned by an owner-scoped listing without a lock, unpruned remembered
selections, and "none found", need no answer, though the first's lock is adopted through [15]). The lead's decisions
are binding and are marked.

| # | Finding | Answer | Where |
|---|---|---|---|
| 0 | must-fix: mouse clicks on the wire menu are swallowed by `shellPointerDown` before the item's click | Accepted (lead's decision): the link menu is handled like the node menu, never through `closeMenus()`; `shellPointerDown` adds `#link-context-menu` to its `closest()` selector and passes it as `except`, closing the link menu only for a pointerdown outside it; pinned in `test_shell_ui.js` | §1.8, §3.2 exception (1), §5.3 shell tests, §7 S2 (1) |
| 1 | must-fix: removed ids still driven by Playwright tools no slice owns; acceptance S2 (10) cannot pass | Accepted, option (b) (lead's decision): the per-release scripts under `docs/technical-audit`, `docs/ui-ux-cleanup` and `docs/netlab-ui-qa` are frozen history; (10) narrowed to `app/static`, `tests` and the four CLAUDE.md-named tool folders with exact-id greps (`#capture-launch\b`, `#capture-endpoints\b`), which reference neither id (verified) | §6 last bullet, §7 S2 (10) |
| 2 | should-fix: the own-slot pre-check breaks the idempotent retry; the page refuses with no request | Accepted (lead's decision): `Captures.requests` records `request_id → derived ids`; the server's `own` leaves out this request's sessions; the page skips its local check on a retry that keeps the `request_id` and otherwise counts from a fresh listing fetched on Start; the `request_id` is kept after a partial result; retry test added | §1.3, §2.2 steps 4–5, §3.1 summary and submit, §4 retry row, §5.1 pre-check test |
| 3 | should-fix: after a partial set, Start again creates duplicate desktops | Accepted with one change (lead's decision on the narrowing): the dialog narrows to the refused entries, the started boxes are unticked and disabled, Start reads `Start the remaining <n>` and sends only them. **Deviation from the decision's "a new `request_id` for them", stated for the lead**: the remaining set keeps the `request_id`, because the derived ids are now content-derived (`request_id:target_id:interfaces`), so an entry whose container was created behind a lost reply comes back as the same session instead of a duplicate; a fresh id would forfeit exactly that, and the kept id is what [2]/[12] prescribe for the retry; position-derived ids would have made the narrowed set collide, which is why the derivation changed | §1.3, §2.2 step 5, §3.1 results, §3.6, §5.1 mid-set test, §5.3 |
| 4 | should-fix: `known` and `public_session` disagree on keys | Accepted (lead's decision): one record shape `{lab, lab_id, device, ports, label, started}` produced by `label()`, used for `known` and as the fallback, read by `public_session`; `lab` is the display name; a launch-then-list test pins it | §1.5, §2.2 step 3, §2.3, §5.1 |
| 5 | should-fix: a vanished target cannot be named by its label | Accepted (lead's decision): the entry is named by position, `Capture 2 of 2: …`; the test claim corrected | §1.11, §2.2 steps 2 and 6, §4, §5.1 |
| 6 | should-fix: mid-set failures incomplete (service 409, the manager's 502, a timeout after creation) | Accepted (lead's decision): any `HTTPException` on entry *i*, the manager's `TOKEN` 502 and the 409 included, stops the set into `refused`; after a 502 the owner's sessions are re-listed once and a row with the entry's derived id moves into `sessions`, else the entry reads "may have started, see Your capture sessions" | §2.2 step 5, §4, §5.1 mid-set test |
| 7 | should-fix: resize and blur listeners calling `closeMenus()` would close every header panel | Accepted (lead's decision): the new listeners call only `typeof closeLinkMenu==='function'&&closeLinkMenu()`; a capture-phase scroll listener with the same call is added for the floating-menu case the finding names; pinned with an open save panel | §3.2 exception (3), §5.3 shell tests |
| 8 | should-fix: Escape on the link menu cannot return focus to the wire | Accepted (lead's decision): `shellEscape` returns early while the link menu is open, as for the node menu; the menu's own keydown closes it with `closeLinkMenu(true)`; pinned | §3.2 exception (2), §3.6, §5.3 |
| 9 | should-fix: S1's builder conflicts with the privileged-path routing | Accepted (lead's decision): S1 goes to `clab-opus-specialist`, `risk-reviewer` on the diff | §7 table |
| 10 | optional: live-pass step 3 contradicts the pre-check rule | Accepted (lead's decision): reworded: no limit sentence at 2 + 2; the fifth on `vsw` shows the single-capture variant | §7 live pass (3) |
| 11 | must-fix: routing the link menu through `closeMenus()` breaks mouse selection and Escape focus, and both menus can open together | Accepted (lead's decision, with [0], [8], [7]): the three explicit `shell.js` exceptions; the menu's own keydown closes on Tab; an outside pointerdown (the device right-click included) closes it; a lab guard `linkMenuLab` like `contextLab`; the scroll close; tests for the pointerdown, the Escape focus and the lab guard | §1.8, §3.2, §5.3 |
| 12 | must-fix: the pre-check refuses the idempotent retry; the `request_id` after a partial result is undefined | Accepted (lead's decision, with [2]): `requests` map, own-request exclusion, the page's retry skip, the `request_id` kept after `refused`, memory written only after a full success, `Start the remaining <n>`; the retry test | §1.3, §1.7, §2.2, §3.1, §5.1 |
| 13 | must-fix: link mode has no recovery for an unresolvable end; today's endpoint switch with a manual tick is lost | Accepted (lead's decision): a per-end **Choose the interface on <device>…** button switches to device mode for that end with today's hint and sentences (scope host for a node outside the inventory); link mode never auto-unfolds Advanced and keeps the "capture somewhere else" label; a target chosen under Advanced leaves link mode; a browser test for an unmapped kind | §3.1 link mode, §4 three rows, §5.3, §7 S2 (12), §8 "changed in form" |
| 14 | should-fix: regression tooling still drives the old ids; the endpoint-switch test needs a named rewrite | Accepted (lead's decision, with [1]): option (b) and the narrowed check; §5.3 names the rewrite: unticking end 1 sends only end 2's veth, `eth4` | §5.3, §6, §7 S2 (10) |
| 15 | should-fix: `known` and `public_session` disagree, so launched sessions show empty labels | Accepted (lead's decision, with [4]): one shape, one producer, one reader; `known_lock` added for the threadpool routes (the refuted lock finding's remedy, adopted here) | §1.5, §2.2 steps 3 and 5, §2.3, §5.1, §7 S1 (8) |
| 16 | should-fix: a vanished target's 409 sentence is impossible | Accepted (lead's decision, with [5]): position naming | §2.2, §4, §5.1 |
| 17 | should-fix: End all and mid-set sentences do not match what the adapter returns | Accepted (lead's decision, with [6]): a failed end gets the fixed sentence `Could not end <label>; try End session on its row.`; the §4 wording corrected; 409 among the mid-set codes | §2.4, §4, §5.1 end-all test |
| 18 | should-fix: the slot-limit refusal suggests remedies that cannot work in link mode or for a single capture | Accepted (lead's decision): three variants (device, link, single) with the pluralisation rule `1 session` / `n sessions`; the server picks the variant from the body's targets, the page from its mode | §1.11, §2.2 step 4, §3.1, §4, §5.1, §5.3 |
| 19 | should-fix: the Tools caption refreshes only on a mouse click | Accepted (lead's decision): `showTab(value)` calls a `typeof`-guarded `refreshCaptureSessions()` for `tools`, covering the arrow keys, deep links and Back/Forward; tested on the arrow-key path in `test_readiness_ui.js`; `app.js` joins S2's files | §3.3, §5.3, §7 S2 |
| 20 | should-fix: `closeMenus()` on resize and blur would close the save panel while typing | Accepted (lead's decision, with [7]): the listeners call only `closeLinkMenu()` behind the guard | §3.2 exception (3), §5.3 |
| 21 | should-fix: new buttons inside `#capture-form` lack `type="button"` | Accepted (lead's decision): `type="button"` written into the markup of All connected, None, End all my sessions (and the per-end Choose button, the row's End session); a no-launch test | §3.1 presets and sessions, §5.3, §7 S2 (11) |
| 22 | should-fix: up to four viewer tabs share one title | Accepted (lead's decision): `capture-session.js` sets `document.title` to `<name> · <interfaces> — Wireshark` from the status answer; a test; the service and the status route unchanged | §2.3 last sentence, §3.5, §5.3, §7 S2 |
| 23 | should-fix: "ends in 1 h 58 min" overstates a session's life | Accepted (lead's decision): the row reads `at most 1 h 58 min left (15 min once its viewer is closed)` | §3.1 sessions, §5.3 |
| 24 | should-fix: a self-loop on one device still costs two slots, against R052's answer | Accepted (lead's decision): both ends on the same device are one session with both veths (the single body form); the open-as control shows there with `one` as default | §1.4, §1.10, §3.1 link mode and submit, §5.3, §7 S2 (2), (4) |
| 25 | optional: live-pass step 3 contradicts the pre-check rule | Accepted (lead's decision, with [10]) | §7 live pass (3) |
| 26 | optional: a one-time start from a per-end menu item rewrites the wire's left-click default | Accepted (lead's decision): link memory is written only when the dialog was opened without a hint, an `options.end` or a preset, the same condition that applies to reading it | §1.7, §3.1 memory, §5.3, §7 S2 (6) |
| 27 | optional: smaller wording and affordance points (six) | Accepted as proposed (lead's decision): counts pluralised everywhere; the C03 button reads **Capture all connected**; `#capture-openas` sits after the interface fieldsets and the plan sentence names it; `#capture-more` opens when a preset or memory ticks a box inside it; End all is `.button.danger` with the idle label captured and restored; decision 8's Enter sentence corrected | §1.8, §3.1, §3.3, §3.4, §5.3 |

## 10. Verification answers (`/clab-slice-verify` on `claude/c07-int` at d4eb1f4, six workers; 10 of 11 checks held)

| Finding | Answer | Where |
|---|---|---|
| Medium: the Tools tab's 4-second poll rebuilt the session list and dropped keyboard focus | Accepted: the sessions refresh only when Tools is newly shown or on an explicit action; the list is painted only when its markup changed (0 mutations and 0 requests over 12 s in the smoke) | §3.3; `app.js`, `capture.js` |
| Medium: with capture not set up every wire-menu item is disabled, so focus never entered the menu and Escape could not close it; Enter on the wire opened the dialog behind the menu; the menu floated over another view after a route change | Accepted: the menu is focusable (`tabindex=-1`) and takes focus when no item is enabled, so Escape and Tab close it; Enter closes the menu first; the hash router closes it | §3.2; `capture.js`, `shell.js` |
| Medium: at 390 the link-ends grid overflowed when one end was disabled and the Open Wireshark link clipped | Accepted: one column at 420 px and narrower, wrapping rows and launch row (measured 306 px, nothing outside the dialog) | `style.css` |
| Medium: End all my sessions from the Tools card confirmed a stale count and ended more than it named | Accepted: the list is re-read before asking and the current count named; a failed listing ends nothing | §3.3 |
| Low: a started link end rendered as a garbled column; Start stayed enabled after a full success; 'Capture both ends…' honoured memory; focus landed on BODY after closing the dialog or End all; duplicated veth; singular message after a narrowed retry; the launch row offset | Accepted, each as the fix round reports; a menu item ignores memory (§3.6), focus returns to the opener found by its ends | §3.1, §3.6; `capture.js` |
| Low: after a lost reply recovered on entry i the untried entries were refused with the transport sentence | Accepted: the set continues after a recovery; untried entries after a second 502 read "Not attempted: an earlier capture of this set failed." | §2.2; `capture.py` |
| Low: an idempotent repeat logged `capture.launch` again and reset the record's `started` | Accepted: `begin()` runs only for a session id not yet in `known` | §2.3; `capture.py` |
| Cosmetic: the dialog and plan say `label: port` while the session rows show the NOS name from `displayed_interface` | Open: one naming rule needs the NOS name on the link ends or a plan wording change with many pinned sentences; recorded for the release's handoff | §3.1 |
| Held with a note: the pre-check excludes only the current (possibly narrowed) set's ids, which counts a request's already started sessions; the single form also returns `sessions` and `refused` (additive); the public row carries no `started` | Accepted as more accurate than §2.2 step 4 and consistent with §2.2 step 6 and §2.3 | §2.2, §2.3 |

## 11. Live-pass answers (the parity lab, the real session service, 2026-10-23)

| Finding | Answer | Where |
|---|---|---|
| Every step held: both ends from a wire click (one set request, two viewers), one end from the menu, All connected as one Wireshark on `ceos`, the page's pre-check at four and at three sessions, End all my sessions emptying the list and the containers, memory written only after a full success and ignored by a menu item | Recorded in VALIDATION; no change | §3, §4 |
| Cosmetic: two sessions on the same end share a row label | Open with §10's naming rule: the row gains the session's start time or the NOS name once one rule covers the dialog and the card | §3.3 |
| Log only: the relay logs a `WebSocketDisconnect` traceback when the viewer closed first; an optional viewer asset (`core/rfb.js`) answers 404 | Accepted as noise: `desktop` may catch the disconnect on close in a later tidy; the asset probe is the viewer's own and harmless | `capture_sessions.py` |
| The Tools card shows the caption and End all; the labelled rows live in the dialog's session list | As designed (§3.3) | §3.3 |

## 12. Branch review answers (`/clab-review-changes` on the integrated chunk, base 6c3f5d5, 29 agents; 10 confirmed, 2 refuted)

| Finding | Answer | Where |
|---|---|---|
| Should-fix (two reviewers): the Tools card's session list was not refreshed when Tools appeared again after Home, or after a reload whose first render ran before `capture.js` was defined (`shownTab` stayed `'tools'` without a fetch) | Fixed: `shownTab` is recorded as `'tools'` only when the refresh was actually asked for, and cleared when no lab is on screen; two tests in `test_readiness_ui.js` fail on the old code; the 4 s poll still never refetches | `app.js` `render`, `showTab`; §3.3 |
| Should-fix: the re-list failure after a lost reply (the likeliest real 502) was untested | Fixed with a `list_fail` hook on the scripted service: a failing re-list after a lost reply gives a partial 200 with the may-have-started sentence and the not-attempted sentence for the rest; a failing pre-check listing is the plain 502 with no POST | `test_capture.py`; §2.2 |
| Should-fix: choosing a device under Advanced while in link mode had no test | Tested (no production change): the dialog leaves link mode for device mode on that target, the ends are hidden and cleared, the context line names the device; an empty selection stays in link mode; the target select is empty after a link open with one listed target | `test_capture_ui.js`; §3 |
| Optional: a retried launch could log `capture.launch` twice because a concurrent listing's prune can drop the in-memory record before the launch answers | Fixed: `prune()` keeps a record younger than `PRUNE_GRACE_SECONDS` (10 s); a record without `started`, or one in the future, is not protected; `known` stays memory only | `capture.py`; §10 |
| Optional: an owner cookie minted on a request that then raises is lost (pre-existing, widened by sets) | Open, recorded: the dialog lists the sessions before any launch, so the cookie exists in practice; a later tidy may return the error as a response that carries the cookie | §2.2 |
| Optional: a non-502 refusal mid-set gave its own reason to entries never sent | Fixed: on every error path entry *i* keeps its sentence and the later entries read the not-attempted sentence; one pinned sentence rewritten (the 409 case), a 429 test added | `capture.py`; §2.2 |
| Optional: Capture all connected sat inside the Name column header, so its name was read with every cell | Fixed: the button is a toolbar line before the table inside the same region (existing `.actions` class, same attributes and handler); the header is plain `Name` | `device-diagnostics.js`; §3.4 |
| Optional: small `capture.js` branches unpinned (time left under a minute and at an hour, the short-name lookup, the refusal matched by interfaces, a mixed set with an unsupported link) | Pinned in `test_capture_ui.js` | §3 |
| Optional: the scripted capture fixture (`--capture`) and its `fail_next_start` switch are under no automated check; its id derivation is a third copy | Recorded as an open point: at the next fixture touch, a stdlib check that the fixture's derivation equals `BrowserSessions.session_id`; until then the fixture is verified by the browser passes only | `fixture_manager.py`; §6 |
| Refuted: a C03 preset follows the student to another device chosen under Advanced | Unreachable: a preset opens the dialog in lab scope on that device, and `/api/capture/targets` with `node=` lists that device's container only; the only way to list another device is the scope change, which clears the preset and the hint first (verified in a harness copy); no change | §3 |
| Refuted: after a full success Start stays disabled and focus is dropped | Start is disabled by design after a full success until the selection changes; the button is disabled at the start of every submit (as before this chunk) and the next Tab lands on the first Open Wireshark link (verified in Chromium and Firefox on the fixture); no change | §3.6 |
