# C04 design: serial console for the vrnetlab kinds, container facts in the device drawer

Rows R021 (serial console) and R024 (container facts; R025's Copy buttons shipped in C02 as `clipboard.js`,
`copyButton(value, what, targetId, visibleText?)`). Written against `claude/parity-campaign` at `c3f3d94` (release
1.31.1, containerlab 0.79.0 on the VM, the `parity` lab up: `vsw` juniper_vjunosswitch 172.20.20.111, `vrt`
juniper_vjunosrouter .112, `cjunos` juniper_cjunosevolved .113, `xrv9k` cisco_xrv9k .114, `ceos` arista_ceos .115),
amended after the design review (§9 answers every confirmed finding; the lead's decisions on them are binding).
Code read: `node_services.py` (ticket route, the `/api/terminal` socket, `reserve()`/`release()`, `connect()`),
`terminal.js/.html/.css`, `clipboard.js`, `app.js` (`sshHint`, `nodeActions`, `deviceRow`, the terminal click,
`renderDetails`, `setMarkup`, `setListMarkup`), `status.js` (`deviceState`), `topology.js` (the node menu),
`workspace.js`, `main.py` (`public_lab`, `/api/state`, the Start fresh guard), `discovery.py` (`parse_inspect`,
`container_name`, `expected_container`, `uptime_seconds`, `reconcile`, `public()`), `lab_operations.py`
(`restarting_nodes`), `inventory.py`, `device_diagnostics.py` (C03: `public_facts`, `target`), the tests named in §5,
C02-DESIGN §1 and C03-DESIGN §2.1 and §4.1. No helper change, no helper `VERSION` bump, no new route or socket outside
the same-origin guard; the console is direct node access like SSH (invariant: no helper for device work).

Live facts re-checked read-only in this session (one TCP connect and a 2 s read, nothing typed): 172.20.20.111:5000
accepts and sends `ff fb 01 ff fb 03 ff fb 00 ff fd 00` at once (WILL ECHO, WILL SGA, WILL BINARY, DO BINARY), then
nothing; .113:5000 is refused; .115:5000 times out. The lead's facts for .112 and .114 (same negotiation), port 23
refused everywhere, qemu's one-client chardev (a second client connects but receives nothing until the first leaves,
then is served), and vrnetlab's launcher holding the console during the first boot are taken as given. The review's
verifiers added, from the launcher source read inside the `parity` containers: qemu listens on 5000
(`server=on,wait=off`) about 2 s before the launcher connects to it, at every container start and at every relaunch
of the VM inside the container; `bootstrap_spin` restarts the VM after 300 silent one-second spins; the health file is
written when bootstrap ends, so on these kinds *healthy* means *console released*.

## 1. Decisions in one place

1. **Three kinds offer a console, by a per-kind table in `inventory.py`**: `CONSOLE_PORTS = {'juniper_vjunosswitch':
   5000, 'juniper_vjunosrouter': 5000, 'cisco_xrv9k': 5000}`, the three proven live on this VM. `juniper_vqfx` is
   vrnetlab-based per containerlab.dev and plausibly identical, but it is neither documented with a console on its
   page nor proven here: **kept off until proven live** (the repository's rule for defaults). `juniper_cjunosevolved`
   (not vrnetlab; 5000 refused) and `arista_ceos` never. containerlab.dev documents `telnet <node-name> 5000` only on
   the vJunos-router page; the vJunos-switch and XRv9k pages say "built using vrnetlab" and nothing about the console,
   and vrnetlab's README names "the QEMU serial port on TCP port 5000" as the one fixed pass-through exception. The
   documentation half of the rule therefore rests on vrnetlab's project for two of the three kinds; the live half is
   this VM. **Lead's decision:** accepted for all three. A console port is a fact of the image, not a login default,
   so the bar is the one the repository sets for an image default: the image's own project documents it (vrnetlab's
   README, and the vJunos-router page of containerlab.dev) and it was verified live (this VM, all three kinds). A kind
   joins the table only on both halves; `juniper_vqfx` waits for its live proof.
2. **The console is decided by the topology kind, never by the student-editable platform.** A node's `kind` comes
   from the topology at import (`parse_definition`); `reconcile()` copies no kind, so a lab imported from an inventory
   and linked later has none. `platform` can be set by hand under Edit connection. `console_port(kind)` resolves
   `ALIASES.get(kind, kind)` (so `vr-vjunosswitch` and `vr-xrv9k` count) and reads `CONSOLE_PORTS`. A node without a
   `kind` is not "a kind without a console": it gets its own sentence (`CONSOLE_KIND_UNKNOWN`, §2.2) and drawer line
   (§4.3), both naming Sync topology from VM as the way out.
3. **The manager picks the address and the port; the browser sends `lab_id`, `name` and the word `console`.** The
   address is `discovered_address` (what the VM's inspect reported), never the SSH `address` (which a manual endpoint
   can point elsewhere); the port is the kind's constant. No client-controlled host or port exists. A console needs
   a linked lab, a topology node name, a discovered running container and a discovered address; each missing piece
   has its own sentence (§2.2).
4. **One ticket route, one socket, a protocol bound into the ticket.** `POST /api/labs/{lab_id}/terminal-ticket` gains
   an optional `protocol: 'ssh' | 'console'` (default `ssh`, so the SSH page's body `{name}` is unchanged, pinned by
   `test_terminal_ui.js`); the ticket tuple carries the protocol and the socket `/api/terminal` branches on it after
   the ticket is popped. A sibling socket was considered and dropped: it would duplicate the origin check and the
   ticket store for no isolation gain, and the ticket already binds what the socket may open.
5. **A console session is asyncio streams, not a thread.** The SSH loop polls a Paramiko channel through
   `asyncio.to_thread`; a console is a plain TCP socket, so `asyncio.open_connection` and `asyncio.wait(...,
   FIRST_COMPLETED)` over the device read and the browser read serve it without an executor thread per session.
   Its cap is its own (`CONSOLE_LIMIT = 8`), reserved with a sentinel inside the locked block that checks it (§2.3),
   and it never calls `reserve()`: it is not a Paramiko client and must not eat the SSH limit of 32.
6. **The server gates the console; the qemu probe is the second defence.** This reverses the first draft, which took
   the probe as the truth. The probe only detects a console the launcher *already* holds; in the roughly 2 s gap
   between qemu listening and the launcher connecting (every container start, every relaunch inside the container) a
   student's click would take the only client slot, the launcher would wait in the backlog reading nothing, and its
   bootstrap would fail or restart the VM (PARITY.md:376 recorded this risk; `vrt` relaunched 240 times under C00).
   `console_target` therefore refuses, each with its own sentence, while the node is in `restarting_nodes()`, while
   `runtime_status` reports `(health: starting)` or `(unhealthy)` (all three kinds' containers have a healthcheck and
   the health file is written when bootstrap ends, so *healthy* is *console released*), and while the container is
   younger than `CONSOLE_SETTLE = 120` s computed from `uptime_seconds(runtime_status)` and the inspection time. The
   public row carries the same decision (§2.5), `consoleState()` reads it (§4.1), so the button is disabled with the
   reason and a Reconnect from the terminal page (which mints a new ticket) meets the same refusal on the server. A
   device that never turns healthy has its console held by the launcher anyway: for a failed boot the way in is the
   Logs section of the device panel where it exists (C03), not the console. §8 states the residual windows.
7. **One console per device from this manager, keyed by `(lab_id, name)`.** A second open for the same device is
   refused at once, without a TCP connect, with a sentence that names when the first opened; a forgotten tab cannot
   hold the device's only console for four hours because the idle clock counts browser input only (15 minutes, as
   SSH), and the notice says so. The probe stays for a console held by the launcher or by a client outside this manager.
8. **Minimal telnet, correct on both sides.** Output: the server's IAC sequences are stripped (`IAC IAC` becomes one
   0xFF, 2- and 3-byte commands and `SB … SE` are removed, across chunk boundaries). Input: 0xFF is doubled (a no-op
   for UTF-8 text, kept for correctness). Negotiation: the first `WILL ECHO`, `WILL SGA`, `WILL BINARY` are answered
   `DO`, `DO BINARY` is answered `WILL BINARY`, every other option is refused (`DONT`/`WONT`); qemu ignores the
   answers (verified live), a compliant peer would keep echoing. No NAWS: a `resize` message is validated and ignored.
9. **The terminal page is the same page in console mode** (`#protocol=console` in the hash): title "Console", brand
   label "Serial console", its own notice (the device shows its login prompt when it is ready; Enter is for a prompt
   that is already there), the C02 toolbar unchanged, export names with a `console-` prefix, the status map extended.
   Nothing of the SSH mode changes.
10. **The Container section is built from discovery alone and never calls the VM.** Discovery keeps four more inspect
   fields per row (`container_id`, `ipv4`, `ipv6`, `image`), `reconcile()` copies them onto the node as
   `discovered_id`, `discovered_ipv4`, `discovered_ipv6`, `discovered_image`, and `public_lab` adds `container` (the
   `expected_container()` formula), `console` (bool) and `console_hold` (the server's gate decision). When the manager
   knows no container for the device the section is one sentence plus the topology facts it does have. C03's `facts`
   (pid, health, started, ports) are shown in the same section only while a diagnostics section is open and polling,
   through a getter the diagnostics script owns; the Container section itself never fetches. Volatile rows live in
   their own element so Copy buttons, focus and the "Copied" feedback survive the 4-second poll.
11. **The legacy `container_name` field stays private and untouched.** It belonged to the host-resource monitoring
   removed in 1.6.0 ("Existing `monitor_host` / `container_name` values in encrypted state are ignored and omitted from
   public state", pinned by `test_resource_monitoring_removed_without_destroying_existing_state`). The container name
   the drawer shows is the formula every other module uses (`discovery.container_name`), already public as the node's
   `name` for topology imports and as `container` in every C03 diagnostics answer. Nothing resurrects the old key.
12. **Where Console lives**: the device panel's action row (its home), the Devices tab rows (list and technical table)
   and the map's right-click menu, each only for a kind that has one; not the topology rail (width; its row opens the
   drawer in one click) and not the Open all CLIs launcher (that page is "ready SSH CLIs"). A kind without a console
   shows no button anywhere and a line in the Container section; a held, starting or stopped container shows the
   button disabled with the reason. The labels C02 pinned (`Container kind`, `Image`) keep their words.
13. **What the console is for**, in every sentence of the design and the docs: the way in when SSH does not answer or
   the management configuration is broken, once the device has booted; and watching a reload after bootstrap. Not
   "watch the first boot": the launcher owns the console then, and the Logs section (where the panel has one) shows it.

## 2. Backend (`clab-backup-ui/app/`)

### 2.1 `inventory.py`

```python
CONSOLE_PORTS = {'juniper_vjunosswitch': 5000, 'juniper_vjunosrouter': 5000, 'cisco_xrv9k': 5000}
def console_port(kind):
    """The serial console port of a vrnetlab-based kind, or None. Kinds proven live on a VM only (docs/parity-campaign/C04-DESIGN.md §1)."""
    return CONSOLE_PORTS.get(ALIASES.get(kind or '', kind or ''))
```

`PLATFORMS` is unchanged (it is keyed by platform and returned whole by `/api/state`; a console key there would follow
the student-chosen platform, decision 2).

### 2.2 `node_services.py`: the gate and the ticket

```python
class TicketRequest(NodeRequest):
    protocol: Literal['ssh', 'console'] = 'ssh'
```

`ticket()` takes `TicketRequest`. For `ssh` the body is today's code, byte for byte in behaviour. For `console`:
`address, port = self.console_target(lab_id, data.name)` (below), no credential check, the same ticket store, the same
32-pending limit and 30 s expiry, the tuple `(expiry, lab_id, name, protocol)` (SSH tickets carry `'ssh'`; the
existing test rewrites `entry[1:]`, which survives a fourth element). Response `{'ticket', 'expires_in': 30,
'endpoint': f'{address}:{port}', 'protocol': 'console'}`; the SSH response gains `'protocol': 'ssh'`.

**One decider, `console_gate(state, lab, node)`**, a module-level pure function in `node_services.py`, called under
the store lock by `console_target()` (the ticket and the socket) and by `public_lab()` (the row's `console_hold`,
§2.5), so the page and the server can never disagree. It returns `None` when a console may open now, else `(status,
key, sentence)`, the first row that holds (`<device>` is `short_name or name`, `<kind>` the node's kind):

| Check | Answer |
|---|---|
| `not node.get('kind')` | 409 `kind_unknown`, `CONSOLE_KIND_UNKNOWN` = `'The manager has no topology kind for <device> (it came from an inventory file), so it cannot tell whether it has a serial console. Link the lab and use Lab actions ▾ › Sync topology from VM.'` |
| `console_port(node.get('kind'))` is None | 400 `none`, `CONSOLE_NONE` = `'<device> has no serial console: its kind (<kind>) does not expose one. Open CLI is the way in.'` |
| lab has no `deployment_name` or `expected_container(lab, node)` is `''` | 409 `unlinked`, `CONSOLE_UNLINKED` = `'The console needs a lab linked to the VM with this device in its topology. Link it under Advanced › Link to a running lab…, or sync the topology from the VM.'` |
| not `node_available(state, lab, node)` or `runtime_state != 'running'` | 409 `not_running`, `CONSOLE_NOT_RUNNING` = `'<device> is not running on the VM (or the lab status is out of date), so its console is closed. Start the lab, then try again.'` |
| `discovered_address` empty | 409 `no_address`, `CONSOLE_NO_ADDRESS` = `'The VM has not reported a management address for <device>. Refresh the lab list and try again.'` |
| `node['name'] in restarting_nodes(state, lab['id'])` | 409 `restarting`, `CONSOLE_RESTARTING` = `'<device> is restarting on the VM. Its launcher takes the console first; the console opens once the device reports healthy.'` |
| `CONSOLE_HEALTH.search(runtime_status)` is `health: starting` | 409 `starting`, `CONSOLE_STARTING` = `'<device> is still starting: its launcher uses the console until the device reports healthy. Try again once it is healthy; if the device panel has a Logs section, it shows the boot.'` |
| … is `unhealthy` | 409 `unhealthy`, `CONSOLE_UNHEALTHY` = `'<device> has not finished booting (its health check fails), so its launcher keeps the console. If the device panel has a Logs section, it shows why.'` |
| `age = uptime_seconds(runtime_status)` is not None and `age + max(0, time.time() - inspected_epoch) < CONSOLE_SETTLE` (120 s; `inspected_epoch = state['discovery'].get('inspected_epoch', 0)`) | 409 `young`, `CONSOLE_YOUNG` = `'<device> started less than two minutes ago; its launcher takes the console first. Try again in a moment.'` |

`CONSOLE_HEALTH = re.compile(r'\((health: starting|healthy|unhealthy)\)')` on Docker's status line (`Up 12 minutes
(health: starting)`, `Up 23 minutes (unhealthy)`, `Up 2 hours (healthy)`; discovery.py:140-146 keeps it as
`runtime_status`). The health rows dominate for the three kinds (each container defines a healthcheck); the young-
container floor covers a status line without a health part and any kind added later, and it uses the inspection time
so a status that is a discovery interval old is not read as younger than it is. A `healthy` status passes.

`console_target(lab_id, name)` → 404 `Lab not found` / `Node not found`, then `console_gate`; a hit raises
`HTTPException(status, sentence)`; otherwise it returns `(discovered_address, console_port(kind))`. The address is an
IP string the manager parsed with `ipaddress` in `parse_inspect`, the port the kind's constant: nothing of the request
reaches the connect call.

### 2.3 `node_services.py`: the socket

`/api/terminal` keeps its origin check, `accept()`, the 5 s first message, the 512-byte cap and the single-use pop.
After `_, lab_id, name, protocol = item` (older three-element tuples cannot exist across a restart: tickets live in
memory), `protocol == 'console'` calls `await self.console_session(ws, lab_id, name)` and returns; the SSH branch is
unchanged. The console branch:

- `address, port = self.console_target(lab_id, name)` again (the device may have stopped, or started restarting, in
  the 30 s). Its `HTTPException` is caught below and its `detail` is what the student reads.
- **Reserve, in one locked block.** `self.consoles` is a dict keyed by `(lab_id, name)`, each value a session record
  `{'opened': time.time(), 'writer': None}`. `with self.lock:` → `self.closed` or `len(self.consoles) >= CONSOLE_LIMIT`
  → `ConsoleBusy(CONSOLE_LIMIT_SENTENCE)` (`'Too many consoles are open (limit 8). Close one and try again.'`); the key
  already present → `ConsoleBusy(CONSOLE_OPEN_HERE)` = `'The console of <device> is already open from this manager
  (since <HH:MM> UTC), in another tab or browser. Close that tab, or wait: it closes after 15 minutes without typing.'`
  (no TCP connect is made); otherwise the record is inserted and `record` kept locally. Eight: one per vrnetlab device
  is all a console is for, the parity lab has three, and the limit is separate from the 32 SSH clients so a console
  storm cannot block Open CLI or Test login. `close()` closes every record's attached writer, as it closes `clients`.
- Connect: `reader, writer = await asyncio.wait_for(asyncio.open_connection(address, port), CONSOLE_CONNECT_TIMEOUT = 5)`;
  `record['writer'] = writer`. `OSError`/`TimeoutError` → `CONSOLE_UNREACHABLE` = `'Could not reach the console of
  <device> (port <port> on its management address). The device may be stopping or restarting, or its console is in
  use by another client; if the device panel has a Logs section, it shows what the device prints.'` (both causes:
  qemu's accept backlog is 1, so a console held by an outside client can time out the connect instead of answering).
- Probe: `first = await asyncio.wait_for(reader.read(16384), CONSOLE_PROBE_TIMEOUT = 3)`; `TimeoutError` or `b''` →
  close the writer (`writer.close()`, then `await asyncio.wait_for(writer.wait_closed(), 2)` with its own timeout
  swallowed) and raise `ConsoleBusy(CONSOLE_HELD)` = `'The console of <device> is in use by its launcher (while the
  device boots or its boot fails) or by a client outside this manager. If the device panel has a Logs section, it
  shows the boot; try again once the device reports healthy.'`. Nothing is written to the device before the first
  byte arrived (an idle client must not wake a console it will abandon).
- Served: `self.store.event('console.open', 'Serial console opened', lab_id=lab_id, node=name)`, `opened = True`,
  `await ws.send_json({'type': 'status', 'message': 'Connected'})`, then `first` goes through the codec like every
  later chunk (its negotiation produces the replies, written with `writer.write(...)`, `await writer.drain()`).
- Loop, the SSH limits exactly: `started = last_input = time.monotonic()`; `last_input` is refreshed by a browser
  `input` frame only (device output never counts: a forgotten tab on a chatty console must not hold the device's only
  console; the 4-hour total also stands); idle 900 s or 14400 s total → `{'type': 'status', 'message': 'Session
  timeout. Reconnect to continue.'}` and break. Two pending tasks, `reader.read(16384)` and `ws.receive_text()`,
  `asyncio.wait(..., timeout=1, return_when=FIRST_COMPLETED)` (the timeout is only for the idle clock); device bytes →
  `output, replies = codec.feed(chunk)`; replies to the device; `await ws.send_bytes(output)` when non-empty (awaited:
  socket backpressure as in the SSH loop); `b''` from the device → `{'type': 'status', 'message': 'The console
  closed: the device stopped or restarted.'}` then break (the page shows `Disconnected — The console closed…`).
  Browser frames: the same 20 000-byte raw cap and validation as SSH; `input` → `writer.write(telnet_escape(value.encode()))`,
  `await writer.drain()`, `last_input` updated; `resize` → validated (`20 <= cols <= 400`, `5 <= rows <= 150`, else
  `ValueError`) and ignored; anything else → `ValueError('Invalid terminal message')`.
- `except WebSocketDisconnect: pass`; `except HTTPException as exc`: send `{'type': 'error', 'message': exc.detail}`
  (the gate's own sentence at socket time, never flattened); `except ConsoleBusy as exc`: send `{'type': 'error',
  'message': str(exc)}`; `except Exception`: send `{'type': 'error', 'message': 'Session ended.'}` (no credentials
  sentence: a console has none). `finally`: cancel the pending tasks, close the writer, pop the record from
  `self.consoles` only when the stored value is this session's record (a refused second open never pops the first),
  and only when `opened`: `self.store.event('console.close', 'Serial console closed', lab_id=lab_id, node=name)`;
  `await ws.close()`.
- Events carry lab id and node only; no address, no port, no bytes, no time of the other tab. The sentence of a
  refusal goes to the browser, never to an event (the guard audits the POST ticket route as `api.request` today; the
  socket is not audited).

### 2.4 `node_console.py` (new): the codec, pure and testable

```python
IAC, DONT, DO, WONT, WILL, SB, SE = 255, 254, 253, 252, 251, 250, 240
ACCEPT_WILL = {1, 3, 0}      # ECHO, SGA, BINARY: answered DO
ACCEPT_DO = {0}              # BINARY: answered WILL
class TelnetCodec:
    """Strips the server's IAC sequences from output and answers its options; carries state across chunks."""
    def feed(self, data: bytes) -> tuple[bytes, bytes]: ...   # (bytes for the terminal, replies for the device)
def telnet_escape(data: bytes) -> bytes: return data.replace(b'\xff', b'\xff\xff')
```

`feed` is a byte-at-a-time state machine (`data`, `iac`, `option` with the pending command, `sb`, `sb_iac`): `IAC IAC`
→ one 0xFF; `IAC WILL|WONT|DO|DONT x` → three bytes dropped, the reply decided once per option (a repeated `WILL`
is not answered again: the `answered` set bounds the reply traffic); `IAC SB … IAC SE` dropped whole; any other
`IAC x` → two bytes dropped. A chunk that ends inside a sequence keeps the state for the next chunk. The output is
raw for xterm (the device's own escape sequences pass through, that is a terminal), so `node_console.py` never
redacts: console bytes are never stored or logged, as SSH bytes are not. CR is sent as the browser sends it (`\r`
from Enter): qemu's telnet chardev negotiates BINARY, in which CR is literal; §8 lists this for the live pass.

### 2.5 `discovery.py`: four more inspect fields, and the public row

`parse_inspect` keeps, each optional and never fatal (the `status` pattern at lines 136-140):

| Row key | Entry key | Rule |
|---|---|---|
| `container_id` | `id` | `str`, `re.fullmatch('[0-9a-f]{12,64}')`, else dropped |
| `ipv4_address` | `ipv4` | the IP without its prefix via `ip_interface(...).ip` when not `N/A`/`-`/empty and it parses, else `''` |
| `ipv6_address` | `ipv6` | the same |
| `image` | `image` | `literal(..., 'Container image', 300)` in a `try`, else dropped |

`address` keeps today's meaning (the first usable of the two): nothing that reads it changes. `reconcile()` copies
`discovered_id = found.get('id', '')`, `discovered_ipv4 = found.get('ipv4', '')`, `discovered_ipv6 = found.get('ipv6',
'')`, `discovered_image = found.get('image', '')` and sets all four to `''` when the container is absent (the
`runtime_status` rule). `reconcile` still skips an unlinked lab, so after an unlink the fields keep their last values
as `discovered_address` does today; the drawer never shows them without a known container (§4.3), which is the
cheaper of the two fixes the review offered. `owner` is not kept: it is a VM user name of no use to a student and
C03's inspect table already shows it when asked. `discovery.public()` is unchanged (it never exposed rows).

`public_lab` (`main.py`): the node row copies every stored key except the private four, so the new node fields are
public by construction; this design names them as intended public (`discovered_id`, `discovered_ipv4`,
`discovered_ipv6`, `discovered_image`: a container id prefix, the management addresses the inspect table already
shows, an image tag) and the test pins the exact set. Three computed fields are added explicitly:
`row['container'] = expected_container(lab, n)` (`''` when the formula has nothing); `row['console'] =
bool(console_port(n.get('kind')) and row['container'])`; and `row['console_hold']`, `''` when `console_gate(state,
lab, n)` returns `None`, else `{'key': key, 'text': sentence}` (the same function the ticket route runs, §2.2; the
page cannot compute the young-container floor itself, because `inspected_epoch` is not public, and must not keep a
second copy of the sentences). Nothing else: the port is a constant the page does not need.

### 2.6 `main.py`: Start fresh waits for consoles too

The reset route's guard (`main.py:217`) becomes `if services.clients or services.checking or services.consoles:` with
the sentence `'Close SSH sessions and serial consoles and wait for connection checks before resetting.'` (a console
left running would relay to a device of a lab the manager no longer has, and its `console.close` would name a removed
lab). `test_manager_reset.py` pins it with a record in `services.consoles`; if an existing test pins the old
sentence, its regex is rewritten and its claim kept.

### 2.7 What does not change

`reserve()`/`release()`, `connect()`, the readiness monitor, `restore_shell.py`, the SSH loop, the guard, every
helper. A console counts in no job and in no `operation_busy`.

## 3. The terminal page in console mode (`terminal.js`, `terminal.html`)

- `const protocol = params.get('protocol') === 'console' ? 'console' : 'ssh'`. The page's static `<title>` stays
  (the script sets `document.title`); the brand label gets `id="brand-label"` and reads `Serial console`; `#title`
  reads `<node> · Console · <lab>` and `document.title` `<node> · Console · <lab> · Containerlab Node Manager`;
  `#terminal` gets `aria-label="Serial console terminal"`. SSH mode renders exactly today's strings.
- Ticket body: `{name, protocol: 'console'}`; SSH keeps `{name}` (pinned). `#endpoint` shows the manager's
  `endpoint` (`172.20.20.112:5000`). The socket, `binaryType`, `resize` frames (sent, ignored by the manager),
  `onData`, Reconnect/Disconnect, `generation` and the tools are shared code. Reconnect mints a new ticket, so every
  refusal of §2.2 applies to it as to the first open: the page cannot bypass the gate.
- Notice (`#notice-text`): `Serial console of <device>: the same as a cable in its console port. The device shows
  its login prompt when it is ready; Enter is only for a prompt that is already there. The manager sends no
  credentials. Log out before you disconnect, because a console login stays open on the device. The session closes
  after 15 minutes without typing, and a console open in another tab blocks this one until then. Alt+T moves to the
  terminal tools; Alt+Up, Alt+Down and Alt+0 change the text size.` Details: `The console opens once the device
  reports healthy: during a boot its launcher uses the console. One console per device at a time; output is not
  recorded by the manager. A session ends after 4 hours at most.`
- `statusText` in console mode adds, before the SSH rows: `[/^Connecting/, 'Connecting to the console of
  <device>…']`, `[/^Session ended\.$/, 'The console session ended.']`, `[/Too many pending/, 'Too many sessions are
  starting at once. Try again in a moment.']` (the shared 32-ticket limit must not read as the SSH "Too many CLIs"
  sentence), and a passthrough for every sentence of §2.2–2.3 (`/serial console|console of .* is|console is closed|
  console closed|limit 8|topology kind/` → the text verbatim) so the SSH rewrite rules (`Session ended. Check
  credentials…`, `refresh VM discovery`) never fire on a console sentence. The device-side close arrives as a status
  and `onclose` keeps it: `Disconnected — The console closed: the device stopped or restarted.`
- Export names: `exportName(labLabel, name, date, kind)` with `kind` `console-screen` / `console-session`, so a file
  reads `parity-vrt-20261023T041500Z-console-session.txt`; SSH names are unchanged.
- Everything of C02 (font size and its key, Copy, Clear, Save, roving toolbar, `#tools-status`, the 30 px rule, the
  focus rule) is untouched; `terminal.css` is not changed.

## 4. The UI on `/` (`status.js`, `app.js`, `topology.js`; `device-diagnostics.js` for one hook)

### 4.1 One decider: `consoleState(node)` in `status.js`, fed by the server's decision

```js
// Whether this device offers a serial console and whether it can open now. The server decides (console_hold in the
// public row, the same function the ticket route runs); the drawer, the rows and the map menu all read this.
function consoleState(node){
 if(!node||!node.console)return {offered:false,ok:false,reason:'',key:''};
 const hold=node.console_hold;
 if(hold&&hold.text)return {offered:true,ok:false,reason:hold.text,key:hold.key||''};
 return {offered:true,ok:true,reason:'',key:''};
}
```

The 4-second poll keeps `console_hold` current (restarting, health starting or unhealthy, young, not running, stale
discovery, no address); a stale page that still shows an enabled button meets the server's refusal on the ticket.
`consoleState` never derives a reason of its own, so the words a student reads beside the button and in the terminal
page are the same.

### 4.2 The button

`consoleButton(n)` in `app.js`: `''` when not offered; otherwise `<button class="console-action" data-console="<name>"
[disabled title="<reason>"]>Console <span aria-hidden="true">↗</span></button>`. Placed after **Open CLI** in
`nodeActions(n, details)` (the drawer and the technical table) and in `deviceRow(n, rail)` for `!rail` (the Devices
list); the rail keeps Open CLI only. `nodeActionNotes(n)` adds `Console is not available: <reason>` when offered and
not ok, so a keyboard or touch user reads the reason. `handleNodeAction` opens
`/static/terminal.html#` + `new URLSearchParams({lab: activeId, node: name, label: current().name, protocol:
'console'})` in a new tab, the Open CLI pattern. The map menu (`topology.js:95`) gets `<button role="menuitem"
data-console=…>Console ↗</button>` after Open CLI, only when offered, with `nodeMenuReason(reason)` when disabled;
`handleNodeAction` already receives the menu's clicks. The hover title of a disabled button is the reason; the
visible reason is the row's `.row-reason` only for the CLI (unchanged) and the drawer's note for the console.

### 4.3 The Container section (`renderDetails`)

`#details-info` renders two sections: **Connection** (today's rows minus `Container kind` and `Image`, which move)
and **Container**, a `<section class="drawer-section"><h3>Container</h3>` holding a static `<dl class="health-grid">`
(the rows with Copy buttons) followed by `<dl class="health-grid" id="details-container-live">` (the volatile rows).

**When the manager knows no container** (`n.container === ''`: an unlinked lab, an inventory device without a
topology name, a lab unlinked after discovery) the section is one sentence: `Container facts come from the VM. This
lab is not linked to a running lab (Advanced › Link to a running lab…).`, followed only by `Container kind` and
`Image` when they are known (topology facts); no ID, State, Addresses or Console rows, so a stale `discovered_*` value
never reaches the drawer and nothing reads as waiting or as a fault.

**With a known container**, the static rows:

| Row | Value | Copy |
|---|---|---|
| Container | `n.container` in `.mono` (`clab-parity-vrt`) | `copyIf(n.container, 'the container name', 'details-fact-container')` |
| ID | `n.discovered_id` (`.mono`; 12 characters, the whole id when a full one is known); `Not reported` when `''` (no button) | `copyIf(id, 'the container id', 'details-fact-id')` |
| Container kind | `n.kind` (`.mono`); the row renders only with a value (the C02 claim) | existing `details-fact-kind` |
| Image | `n.discovered_image || n.image`, rendered only with a value, plus a `secondary-text` line `topology names <n.image>` when both exist and differ (the PICKUP case: the running tag is the local nested-virtualization image) | `copyIf(shown image, 'the image', 'details-fact-image')` |
| Addresses | `IPv4 <discovered_ipv4>` and `IPv6 <discovered_ipv6>` on two lines, each `.mono` with its own Copy (`'the IPv4 address'`, `'the IPv6 address'`); absent families are not shown; neither known: `No address reported` | per line |
| Console | offered: `Serial, port 5000 (Console ↗ above)`; `n.kind` empty: `Not known: the manager has no topology kind for this device`; else `None for this kind` | none |

Copy targets in document order: name, endpoint, address (Connection), then container, id, kind, image, ipv4, ipv6.

The volatile rows, in `#details-container-live` and written through their own `setMarkup` call after the static one
(so the static markup, and with it every Copy button, is rebuilt only when a static value changes; a focused Copy
button and its "Copied" flip survive the minute-by-minute `Up n minutes` and every facts refresh):

| Row | Value |
|---|---|
| State | `runtime_state` with `runtime_status` when present: `running · Up 2 hours (healthy)`; `absent` reads `Not on the VM` |
| *live rows* | only when `diagnosticsFacts(key)` returns facts with `present`: `Process` `pid`, `Health` `health` (or `no health check`), `Started` `started` as `utcDisplay`, `Published ports` `host → container/proto` lines or `none`; a caption `From the Interfaces or Logs section while it is open.` |

When `setMarkup($('details-info'), static)` rewrites (a static change), the live `<dl>` is new and empty and the
second call fills it. The port in the Console row is literal only through `n.console` (when a second port ever
exists the row comes from the server). Every value goes through `esc()`; ids are unique per row.

**The facts hook, pull model.** `device-diagnostics.js` (C03's UI slice, in build) keeps the latest `facts` of the
open device in its state; it exposes `function diagnosticsFacts(key)` (`key = activeId + '/' + detailName`, C03's own
key) which returns that object **only while at least one diagnostics section is open and its poll is not stopped or
paused**, else `null`; after every diagnostics answer whose `facts` changed, and when a section is closed, it calls
`renderDetails()` if the drawer is open, so the live rows drop at once and the caption is never false.
`renderDetails()` reads `typeof diagnosticsFacts === 'function' ? diagnosticsFacts(activeId + '/' + detailName) :
null`; `resetDeviceDiagnostics()` (C03) clears the cache on drawer close or device change. Nothing in `app.js`
fetches; opening the drawer costs the VM nothing (C03 §4.1's rule holds). Ordering: the C04 UI slice starts after
C03's UI slice lands and owns this small addition to `device-diagnostics.js` then (§7).

**States.** Default: a linked lab shows the rows above from the 4 s poll's state. Empty: the one-sentence form.
Stale discovery: State keeps the last `runtime_status` and the Console button is disabled with the server's reason
(the lab banner already says the VM cannot be reached). Error: none of its own. Copy feedback: the drawer is a
`dialog[open]`, so `copyFeedback` writes beside the button (C02). Width: every value wraps (`overflow-wrap: anywhere`
on `.health-grid dd`), two Copy buttons per address row at 390 px wrap under the value as the Address row does today.

### 4.4 Where nothing changes

`workspace.js` (Open all CLIs) lists SSH readiness only; `#details-meta`; the Status section; the Backups section;
Advanced; `shell.js` (no new browser listener is needed: `window.open` lives in `handleNodeAction` as today, the
drawer's close hook is C03's); `terminal.css`; `style.css` (`.console-action` needs no rule: the house `button`
styles apply; if a width tweak is wanted for three actions at 390 px it is one `.node-actions` rule, the builder decides).

## 5. Tests

`tests/test_node_console.py` (new, stdlib + unittest): `TelnetCodec.feed` on the live negotiation bytes (output
empty, replies exactly `DO ECHO, DO SGA, DO BINARY, WILL BINARY`); `IAC IAC` → one 0xFF; a sequence split across two
chunks (`b'\xff'` then `b'\xfb\x01'`); `SB … SE` dropped whole across chunks; an unknown `WILL 24` answered `DONT 24`
once even when repeated; `telnet_escape` doubles 0xFF and leaves UTF-8 alone (`'ÿ'.encode()` holds no 0xFF).

`tests/test_nodes.py` (S1a; new tests, a fixture that links the lab: `deployment_name='example'`,
`container_prefix='clab'`, `state['host']={'enabled': True}`, `state['discovery']={'ok': True, 'checked_epoch':
time.time(), 'inspected_epoch': time.time() - 600, 'labs': {}}`, the node `kind='juniper_vjunosswitch'`,
`definition_node='r1'`, `discovered=True`, `runtime_state='running'`, `runtime_status='Up 2 hours (healthy)'`,
`discovered_address='127.0.0.1'`, `endpoint_mode='auto'`; a `FakeConsole` thread server on `127.0.0.1:0` whose port
the test injects through `patch.dict(app.inventory.CONSOLE_PORTS, {'juniper_vjunosswitch': port})`, `console_port`
reading the dict at call time):
- `test_console_ticket_refuses_each_cause_with_its_sentence`: cEOS → 400 `CONSOLE_NONE`; an inventory node without
  `kind` → 409 `CONSOLE_KIND_UNKNOWN`; `runtime_state='exited'` → 409 `CONSOLE_NOT_RUNNING`; no `deployment_name` →
  409 `CONSOLE_UNLINKED`; `discovered_address=''` → 409 `CONSOLE_NO_ADDRESS`; an operation `restart-node` for `r1` in
  `state['operations']` with a `BUSY` status → 409 `CONSOLE_RESTARTING`; `runtime_status='Up 3 minutes (health:
  starting)'` → 409 `CONSOLE_STARTING`; `'Up 23 minutes (unhealthy)'` → 409 `CONSOLE_UNHEALTHY`; `'Up 30 seconds'`
  with `inspected_epoch = now - 10` → 409 `CONSOLE_YOUNG`, and the same status with `inspected_epoch = now - 200` →
  200 (the inspection time counts); `'Up 2 hours (healthy)'` → 200 with `protocol` and `endpoint` `127.0.0.1:<port>`;
  an SSH ticket for the same node still needs credentials (400 unchanged); the public row's `console_hold` carries
  the same key for each refused case and `''` for the accepted one.
- `test_console_roundtrip_strips_iac_answers_options_and_ignores_resize`: the server sends the negotiation, then
  `b'login: '`, then `b'\xff\xff\xfb\x01x'` (one literal 0xFF, a stray `WILL ECHO`, `x`); the browser receives
  `Connected`, then bytes whose concatenation is `b'login: \xffx'`; the browser sends `resize` and `input 'admin\r'`;
  the server received exactly the four replies then `b'admin\r'` and nothing for the resize; the server then closes
  its side and the browser receives the status `The console closed: the device stopped or restarted.`; after the
  socket closes `self.services.consoles` is empty, `/api/logs` holds `console.open` and `console.close` with the node
  and neither `admin` nor the ticket nor `127.0.0.1`.
- `test_console_second_open_for_the_same_device_is_refused_without_connecting`: with one session served, a second
  ticket and socket for `r1` gets `CONSOLE_OPEN_HERE` with a `HH:MM UTC` time, the fake server saw exactly one
  connection, the first session still relays, and the first session's record is still in `self.services.consoles`
  after the second socket closed (the refused open never pops it); no second `console.open`.
- `test_console_held_by_an_outside_client_is_reported_within_the_probe_timeout_and_left`: a server that accepts and
  sends nothing; with `CONSOLE_PROBE_TIMEOUT` patched to 0.3 the browser gets `{'type': 'error', 'message':
  CONSOLE_HELD…}` in under 2 s; the server sees EOF; no `console.open`/`console.close` event.
- `test_console_connect_failure_limit_and_socket_time_refusals`: an unused port → `CONSOLE_UNREACHABLE` (naming both
  causes); eight records in `self.services.consoles` → the limit sentence; nine concurrent sockets against a server
  that delays its negotiation → never more than eight connections (the slot is reserved under the lock); a device
  whose `runtime_state` flips to `exited` between ticket and socket → the error frame carries `CONSOLE_NOT_RUNNING`
  verbatim, not `Session ended.`; all without events.
- `test_terminal_rejects_origin_invalid_expired_and_reused_ticket` gains a console ticket in its loop (same 1008 codes).
- `test_terminal_roundtrip_resize_and_cleanup` and the L-23 test unchanged (they prove the SSH branch is untouched).

`tests/test_discovery.py` (S1b): `test_container_status_uptime_and_expected_container_names` gains the four fields
(a row with `container_id` 12 hex, `ipv4_address` `172.20.20.112/24` → `172.20.20.112`, `ipv6_address` `N/A` → `''`,
`image`); an id of `xyz` and a 400-character image are dropped, never fatal; `reconcile` carries
`discovered_id/ipv4/ipv6/image` and clears them with the container; `address` still prefers IPv4. New
`test_public_row_adds_container_console_and_the_four_discovered_fields` (this file already builds the app with
`create_app`): the public node row contains exactly these new keys with their values, `console` false for cEOS and
for an unlinked lab, `console_hold` `''` for a healthy linked node and `{key, text}` otherwise, `container_name`
still absent.

`tests/test_manager_reset.py` (S1b): Start fresh answers 409 with the new sentence while `services.consoles` holds
a record, and proceeds once it is empty; an existing assertion on the old sentence is rewritten with its claim kept.

`tests/test_terminal_ui.js`: console mode (`#lab=l1&node=vrt&label=parity&protocol=console`): title and
`document.title`, `#brand-label`, the notice sentences (login prompt when ready, log out, 15 minutes without typing,
the other-tab clause), the ticket body `{name:'vrt', protocol:'console'}`, the endpoint, `exportName(...,
'console-session')`; the console sentences shown verbatim, `Too many pending` mapped to the console sentence, the
SSH `Session ended` rewrite not applied, the device-side close kept after `Disconnected —`; an SSH hash still posts
`{name}` only (existing test).

`tests/test_readiness_ui.js` (the `appHarness` loads `status.js` and `app.js`):
- `consoleState` on a cEOS node (not offered), a node with `console_hold` (`ok` false, the server's text as reason),
  a healthy node (`ok`); `nodeActions(n, true)` carries `data-console` only when offered and disabled with the reason;
  `deviceRow(n, false)` carries it and `deviceRow(n, true)` does not; `nodeActionNotes` names the reason.
- The C02 test `C02: the device drawer facts carry Copy buttons for the name, endpoint, address, kind and image;
  absent facts have none; IPv6 is bracketed; values are escaped` is **rewritten, every claim kept**: the Copy target
  order becomes name, endpoint, address, container, id, kind, image, ipv4, ipv6 (the fixture node gains `container`,
  `discovered_id`, `discovered_ipv4`); `<dt>Container kind</dt>` and `<dt>Image</dt>` are still asserted present with a
  value (now inside the Container section) and still absent when the node names none; `Copy address only`, the
  two-label Address row, the IPv6 bracket, the escaping and the no-`clipboard.js` case stay as they are.
- New: `renderDetails()` with a linked lab renders Connection without kind and image and the Container section with
  the rows of §4.3; the "topology names" line when the tags differ; the one-sentence form for `container: ''` with
  kind and image only when known and no `discovered_*` value shown; the Console row's three wordings; the live rows
  only when a stub `diagnosticsFacts` returns facts and gone when it returns `null`; State in
  `#details-container-live`; **focus survives**: focus a Copy button in the drawer, change `runtime_status`, call
  `renderDetails()`, the same button element is still `document.activeElement` and the static `innerHTML` was not
  rewritten.
- `tests/test_topology_menu_ui.js`: the menu item appears only when offered, disabled with the reason when held.
  `tests/test_page_load_ui.js` needs no change (no new script on `/`).

Fixture pass (`clab-ui-qa`, `/clab-slice-verify` with `ui: true`): the drawer's Container section for a discovered
device and for an inventory import (the one sentence), Copy on the container name and both addresses at
1440/1280/760/390, the Console button disabled with the `starting` reason while the fixture's status reads `(health:
starting)` and enabled once `(healthy)`, the map menu item, and the terminal page in console mode against a fake
console server bound to 127.0.0.1:5000 by the QA worker when the port is free (the fixture's discovery rows point at
127.0.0.1); without the port, the page's refusals only.

## 6. Documentation

- `clab-backup-ui/NODE-FEATURES.md` "Node actions": a bullet after Open CLI: **Console ↗** opens the device's serial
  console (the vrnetlab-based kinds vJunos-switch, vJunos-router and XRv9k: telnet port 5000 of the container,
  reached directly like SSH) in the terminal page's console mode. It opens once the container reports healthy (the
  launcher uses the console during the first boot; if the device panel has a Logs section, it shows that boot) and is
  the way in when SSH does not answer or the management configuration is broken, once the device has booted. The
  device prompts for its own login and the manager sends no credentials; log out before disconnecting. One console
  per device at a time; a second tab is told who has it, and a console closes after 15 minutes without typing.
  "Browser terminal behaviour": a paragraph on console mode (same ticket and origin rules, no Paramiko, the telnet
  handling, `console.open`/`close` events, no output recorded, the 15-minute and 4-hour limits, the limit of eight
  consoles, Start fresh waits for open consoles).
- `docs/LAB-OPERATIONS.md`: in the readiness paragraph (line 108) one sentence: *Console ↗* (vJunos-switch,
  vJunos-router, XRv9k) opens once the container reports healthy, the way in when SSH does not answer or the
  management configuration is broken; and in "The device panel" (or where the drawer's sections are listed) the
  Container section's rows and its one-sentence form for an unlinked lab.
- `CLAUDE.md` (the lead owns it; the edit as the review words it): "Three paths out of the container" item 2 gains
  *and the serial console of vrnetlab kinds (`node_console.py` telnet codec, TCP from `node_services.py`, same ticket
  and Origin rules)*; the Rules sentence *device access stays on the direct node-SSH path* reads *direct node path
  (SSH or the serial console)*; the routing row "Terminals, CLI launcher" lists `test_node_console.py`.
- `docs/VM-CONNECTION.md`: not touched. The console does not use the VM account or the helpers; the page that
  describes the three paths out of the container is `docs/ARCHITECTURE.md` "Module map", which the lead updates with
  the release (one line under node access: a console is a TCP client in `node_services.py` with the codec in
  `node_console.py`).

## 7. Build slices and acceptance checks

| Slice | Owner | Files (disjoint) | Size |
|---|---|---|---|
| S1a console service | `clab-fable-specialist` (or the lead) per `routing-nos.md`; `risk-reviewer` and `clab-network-specialist` on the diff | `app/node_console.py` (new), `app/node_services.py`, `app/inventory.py`, `tests/test_node_console.py` (new), `tests/test_nodes.py` | M (about 200 lines of code, 220 of tests) |
| S1b discovery and public row | `clab-backend-engineer`, from the line-specified edits of §2.5 and §2.6 (`discovery.py` `parse_inspect` rows and `reconcile`; `main.py` `public_lab` three lines and the guard at line 217) per `routing-privileged-paths.md`; `risk-reviewer` on the diff | `app/discovery.py`, `app/main.py`, `tests/test_discovery.py`, `tests/test_manager_reset.py` | S (about 30 lines of code, 80 of tests) |
| S2 UI | `clab-ui-builder`, after C03's UI slice has landed | `app/static/status.js`, `app.js`, `topology.js`, `terminal.js`, `terminal.html`, `device-diagnostics.js` (the getter, the open-and-polling condition and the `renderDetails()` calls only), `tests/test_terminal_ui.js`, `tests/test_readiness_ui.js`, `tests/test_topology_menu_ui.js` | M (about 140 lines of code, 180 of tests) |
| S3 docs | `docs-auditor` | `clab-backup-ui/NODE-FEATURES.md`, `docs/LAB-OPERATIONS.md` | S |
| Lead | release records, `.github/workflows/release-check.yml` (`-p test_node_console.py`), `CLAUDE.md` and `docs/ARCHITECTURE.md` lines, the live pass | |

S1a and S1b share `console_gate` (S1a writes it in `node_services.py`; S1b imports it into `main.py` for the row) and
the row contract of §2.5; S2 shares the ticket/socket contract of §2.2–2.3 and can start on the fixture's state with
`console`, `console_hold` and `container` hand-added while S1 is in flight.

Acceptance checks for `/clab-slice-verify`:

S1a: `PATH="$PWD/.venv/bin:$PATH" .venv/bin/python -m unittest discover -s tests -t tests -p test_node_console.py -v`,
`-p test_nodes.py -v`, then: (1) every refusal of §2.2 answers its own sentence and opens nothing; (2) the socket never
reads a host or a port from the client (grep: the connect call takes `console_target`'s values only); (3) a `(health:
starting)`, `(unhealthy)`, restarting or young node is refused at the ticket and again at the socket, where the error
frame carries the gate's sentence verbatim; (4) a second open for the same device is refused without a connection and
never pops the first record; (5) the held-console case closes the TCP socket within the probe timeout and leaves no
event; (6) the two events carry lab id and node only and no byte of the session reaches `events.jsonl` or the Store;
(7) the SSH tests are byte-identical in behaviour; (8) a console session does not appear in `self.services.clients`;
(9) the idle clock advances on browser input only (a chatty fake server does not keep a silent session alive past the
patched idle limit).

S1b: `-p test_discovery.py -v`, `-p test_manager_reset.py -v`, `-p test_app.py`, then: (1) `container_name` is still
absent from `/api/state`; (2) the public row's new keys are exactly the named set; (3) Start fresh refuses while a
console record exists; (4) an odd id or image in an inspect row never fails discovery.

S2: `node --test tests/test_terminal_ui.js tests/test_readiness_ui.js tests/test_topology_menu_ui.js
tests/test_page_load_ui.js`, `node --check` on each changed script, then: (1) the SSH page posts `{name}` only; (2) no
Console button for cEOS or cJunosEvolved anywhere; (3) Console is disabled with the server's reason while health is
starting and enabled once healthy, while Open CLI stays disabled with *Starting*; (4) `esc()` on every Container value
(grep the template); (5) the Container section renders without `diagnosticsFacts` defined, and the live rows vanish
when it returns `null`; (6) the rail row has no Console button; (7) a focused Copy button survives a `runtime_status`
change; (8) no inline style, no new top-level name that collides (`test_page_load_ui.js`).

Live pass on the `parity` lab (the lead, one operator): with the manager rebuilt from the tree, open `vrt`'s panel:
the Container section shows `clab-parity-vrt`, its id, both addresses, the running local image with the "topology
names" line, State `running · Up … (healthy)`; press **Console ↗**; the page connects, the Junos login prompt is
there or appears on Enter, log in with the published default, `show version` answers (Model vmx), `exit` logs out,
Disconnect; from a second tab press Console on `vrt` while the first is open: `CONSOLE_OPEN_HERE` at once, with the
time, and the first session unaffected; `console.open`/`console.close` once each in Tools › action logs with no
output text; `xrv9k` and `vsw` once each (login, `show version`, log out). The outside-holder case: from a VM shell
hold `vsw`'s console with `nc 172.20.20.111 5000` (type nothing), then press Console on `vsw` three times a few
seconds apart and record the sentences (expected `CONSOLE_HELD`; `CONSOLE_UNREACHABLE` would show the accept-backlog
effect of §2.3), then end the `nc`. The gate during a boot is observed on the fixture (a status with `(health:
starting)`), not live: no device of the parity lab is restarted for it (a vJunos-switch cannot be restarted and an
XRv9k restart boots a fresh disk, `docs/LAB-OPERATIONS.md`). Record in `evidence/c04-live-console.md`. Never type into
a console held by the launcher.

## 8. Assumptions, dead ends removed, refusals, residual risk, what to attack

Assumptions: Enter as a bare `\r` is what qemu's BINARY-mode telnet passes to the guest (the live pass proves it:
a login works); the negotiation arrives within 3 s on a served console (2.0 s read saw all 12 bytes at once);
`discovered_address` is the container's management IP reachable from the manager's `network_mode: host`
(`compose.yml:7`; the SSH path uses the same address); containerlab's inspect rows carry `container_id`, both
address families and `image` on 0.79.0 (verified by the lead; older inspects simply leave the fields empty); the
three kinds' containers define a healthcheck whose success coincides with the launcher releasing the console (the
verifiers' reading of the launcher; the vJunos-router page's "monitor the progress with `docker logs`" is consistent);
C03's UI slice lands before S2 (otherwise the getter waits and the Container section shows discovery rows only).

Dead ends removed: a vrnetlab device that has booted but whose SSH does not answer or whose management configuration
is broken, with no way in (the console opens on a healthy container; a failed boot stays with the launcher and the
Logs section, where the panel has one, is its window); "which container is this device" (name, id, addresses, image,
one Copy each); a running image that differs from the topology's tag with no way to see it; a console taken from the
launcher by a click (the gate refuses before the connect; the probe catches an outside holder).

Refusals, each with its wording: no topology kind (`CONSOLE_KIND_UNKNOWN`, 409); a kind without a console
(`CONSOLE_NONE`, 400); an unlinked lab or a device without a topology node (`CONSOLE_UNLINKED`, 409); not running or
stale discovery (`CONSOLE_NOT_RUNNING`, 409); no discovered address (`CONSOLE_NO_ADDRESS`, 409); restarting
(`CONSOLE_RESTARTING`, 409); health starting (`CONSOLE_STARTING`, 409); unhealthy (`CONSOLE_UNHEALTHY`, 409); started
under two minutes ago (`CONSOLE_YOUNG`, 409); already open from this manager (`CONSOLE_OPEN_HERE`, socket error, no
connect); held by the launcher or an outside client (`CONSOLE_HELD`, socket error); an unreachable port
(`CONSOLE_UNREACHABLE`); the ninth console (`CONSOLE_LIMIT_SENTENCE`); Start fresh while a console is open (409, §2.6);
a foreign origin, an expired or reused ticket (1008, unchanged); a frame over 20 000 bytes or an input over 16 KiB
(session ends, unchanged). Kept: the legacy `container_name` field never reaches `/api/state`; `juniper_vqfx` has no
console until proven.

Residual risk, stated for the record: the gate reads discovery's view. (1) A relaunch of the VM inside a container
that discovery still reports as healthy (vrnetlab restarts the VM in place when its bootstrap gives up): Docker's
health interval plus up to one discovery pass (30 s) can elapse before `(health: starting)` reaches the manager, and
a click in that lag can land in the roughly 2 s gap before the launcher reconnects. (2) A restart made outside the
manager (`docker restart`, `containerlab restart` from a VM shell) before the next discovery pass, same window. In
both, the probe does not help (the console is free) and the consequence is the launcher's bootstrap waiting in the
backlog until the student disconnects, then the VM restart `bootstrap_spin` performs. The lead may close most of (2)
later with the review's fourth condition (refuse while discovery's `inspected_epoch` is older than the lab's newest
finished lifecycle job); it is not in this chunk.

Attack (for `risk-reviewer` and `clab-network-specialist`): the only inputs to `open_connection` are
`discovered_address` (parsed by `ipaddress` in `parse_inspect`, written by `reconcile` from the VM's inspect) and a
constant port: is that exposure wider than today's SSH to the same address? (A hostile VM could already send the
manager's SSH anywhere; the console adds port 5000 on the same host network.) `console_gate` is one function for the
ticket, the socket and the row: confirm no caller computes its own version. The busy probe writes nothing before the
first byte. The held-console close: `wait_closed` is bounded so a half-open peer cannot pin the session. The slot
sentinel: the record is inserted in the same locked block as the count and the per-device check, and only its own
session pops it. Events: only ids. The idle clock counts browser input only; a chatty console cannot hold a slot past
15 idle minutes. The four new node fields are public by the copy-all rule: confirm nothing else lands in a node
record through `reconcile`. (For `clab-ui-reviewer`): the Console button beside a disabled Open CLI reads as "the way
in now" only when it is enabled, and its disabled reason names the launcher; the moved `Container kind` and `Image`
rows keep their labels, Copy buttons and ids; the "log out before disconnecting" and "15 minutes without typing"
sentences are in the notice, not only in Details; the held and starting sentences tell the student where to look
(the Logs section, conditionally) and when to retry (once healthy); the one-sentence Container section on an
inventory import does not read as an error; the map menu gains an item only for three kinds; the terminal page in
console mode is still identifiable as not SSH at a glance (brand label, title, endpoint with `:5000`); a focused
Copy button survives the poll.

## 9. Review answers

One row per confirmed finding of `/clab-design-review` (indices as in the review result; R = risk-reviewer, U =
clab-ui-reviewer); the refuted item ("the shared ticket limit reads as a CLI limit in console mode") needed no
answer, but its fix is adopted through [11]. PARITY.md:376 ("offer the console only after the container reports
healthy, never during bootstrap") is answered by [0] and [12]: the design now does exactly that, on the server.

| # | Finding | Answer | Where |
|---|---|---|---|
| 0 | must-fix: a console opened before the launcher reconnects can block bootstrap; the probe covers only the launcher-first order | Accepted with change (lead's decision): the server gates the console in `console_gate` (restarting, health starting or unhealthy, younger than 120 s from `uptime_seconds` and the inspection time), each with its own sentence; the probe is the second defence; the notice loses "press Enter"; the residual relaunch-in-place window is stated; `consoleState` mirrors the server's decision from the row, so Reconnect cannot bypass it | §1.6, §2.2 table and `CONSOLE_HEALTH`, §2.5 `console_hold`, §3 notice, §4.1, §5, §8 residual risk |
| 1 | should-fix: for a boot that never finishes the console is held for good, so the "no way in" dead end is not removed | Accepted: the dead-end claim is narrowed to a booted device whose SSH does not answer or whose management configuration is broken; `CONSOLE_HELD` says the launcher keeps it while the boot runs or fails and points at the Logs section (conditionally); decision 6 names the Logs section as the way in for a failed boot | §1.6, §1.13, §2.3 `CONSOLE_HELD`, §8 dead ends |
| 2 | should-fix: the cap of 8 is checked before the awaits and the writer added after, so concurrent opens exceed it | Accepted (lead's decision): the slot is reserved in the locked block with a sentinel record, the writer attached after connect, `close()` closes attached writers, `finally` pops only its own record; a nine-socket test pins it | §1.5, §2.3 "Reserve, in one locked block", §5 limit test, §7 S1a (4) |
| 3 | should-fix: Start fresh no longer waits for open interactive sessions | Accepted (lead's decision): the guard at `main.py:217` also refuses on `services.consoles`, sentence "Close SSH sessions and serial consoles and wait for connection checks before resetting.", pinned in `test_manager_reset.py` | §2.6, §5, §7 S1b (3), §8 refusals |
| 4 | should-fix: `console_target` reads `node['kind']`, a 500 for inventory nodes | Accepted: `node.get('kind')` everywhere; a kindless node is its own case (`CONSOLE_KIND_UNKNOWN`) and is in the ticket test | §2.2 table rows 1–2, §5 |
| 5 | should-fix: a refusal raised at socket time becomes the generic "Session ended." | Accepted (lead's decision): `except HTTPException as exc` sends `exc.detail` as the error frame before the generic handler; pinned by the socket-time refusal test | §2.3 exception handling, §5, §7 S1a (3) |
| 6 | should-fix: S1's builder and reviewers contradict the path-scoped routing | Accepted (lead's decision): S1 split into S1a (`node_services.py`, `node_console.py`, `inventory.py`: `clab-fable-specialist`, `risk-reviewer` and `clab-network-specialist` on the diff) and S1b (`discovery.py`, `main.py`, line-specified: `clab-backend-engineer`) | §7 table and shared contract |
| 7 | should-fix: `CLAUDE.md`'s paths to the nodes and the terminals routing row go stale | Accepted (lead's decision): the lead-owned `CLAUDE.md` edit is listed in §6 exactly as the finding words it | §6 `CLAUDE.md` bullet, §7 Lead row |
| 8 | should-fix: moving Kind and Image breaks test claims the design does not say it rewrites | Accepted (lead's decision): the labels `Container kind` and `Image` keep their words; both rows render only with a value; the C02 test is named with the new Copy target order and every kept claim; the unlinked case is settled as one sentence | §1.12, §4.3 table and Copy order, §5 `test_readiness_ui.js` |
| 9 | optional: an unknown kind is worded as "this kind has no console" | Accepted as proposed: `CONSOLE_KIND_UNKNOWN` (409) and the drawer line "Not known: the manager has no topology kind for this device"; decision 2 drops "and from discovery" | §1.2, §2.2, §4.3 Console row |
| 10 | optional: an unlinked lab keeps stale `discovered_*` facts | Accepted as proposed (the cheaper fix): ID, State, Addresses and Console render only with a known container; `reconcile` is unchanged | §2.5, §4.3 "When the manager knows no container" |
| 11 | optional: the shared 32-ticket limit reads as "Too many CLIs" in console mode | Accepted as proposed: console mode maps `/Too many pending/` to "Too many sessions are starting at once. Try again in a moment." | §3 `statusText`, §5 |
| 12 | must-fix: no health gate; the console is enabled in the phase where it always fails and a retry can take it from the launcher | Accepted with change (lead's decision, with [0]): `console_target` and the row refuse while `runtime_status` reports `(health: starting)` or `(unhealthy)` for these kinds, which all define a healthcheck; S2 check (3) rewritten: disabled with that reason while starting, enabled once healthy | §1.6, §2.2, §4.1, §7 S2 (3), §5 fixture pass |
| 13 | should-fix: docs and design claim the console works while the NOS boots, before SSH answers | Accepted: every sentence now reads "opens once the container reports healthy; the way in when SSH does not answer or the management configuration is broken, once the device has booted" | §1.13, §6 NODE-FEATURES and LAB-OPERATIONS, §8 dead ends |
| 14 | should-fix: the busy case cannot tell "your own other tab" from the launcher; a forgotten tab can hold the console for 4 hours | Accepted (lead's decision): `self.consoles` keyed by `(lab_id, name)`; a second open for the same device is refused at once without a TCP connect with `CONSOLE_OPEN_HERE` naming the time; the idle clock counts browser input only (the earlier output-counts amendment reverted), so the 15-minute rule applies as to SSH, and the notice says so | §1.7, §2.3 reserve block and loop, §3 notice, §5 same-device test, §7 S1a (4) and (9) |
| 15 | should-fix: refusal sentences send the student to a Logs section that may not exist | Accepted (lead's decision): every Logs clause is conditional, "if the device panel has a Logs section, it shows the boot" | §2.2 `CONSOLE_STARTING`/`CONSOLE_UNHEALTHY`, §2.3 `CONSOLE_UNREACHABLE`/`CONSOLE_HELD`, §6 |
| 16 | should-fix: live rows outlive the open section, so the caption becomes false | Accepted (lead's decision): `diagnosticsFacts(key)` returns `null` unless a diagnostics section is open and its poll is running; closing a section calls `renderDetails()`; both cases tested | §4.3 facts hook, §5 `test_readiness_ui.js`, §7 S2 (5) |
| 17 | should-fix: volatile State and live rows rewrite `#details-info` often, losing focus and the "Copied" feedback | Accepted (lead's decision): State and the live rows live in `#details-container-live`, written by their own `setMarkup` call; the static rows with Copy buttons are rebuilt only when a static value changes; a focus-survival harness test | §1.10, §4.3 volatile rows, §5, §7 S2 (7) |
| 18 | should-fix: the C02 test that pins "Container kind" and the conditional rows is not named for rewrite | Accepted (lead's decision, with [8]): label kept, conditional rendering kept, the test named with its kept claims and the Copy target order | §4.3, §5 |
| 19 | should-fix: the inventory-import and unlinked empty state reads as waiting or as a contradiction | Accepted as proposed: one sentence "Container facts come from the VM. This lab is not linked to a running lab (Advanced › Link to a running lab…)." plus kind and image when known; "yet" dropped from the address row; "Not known" for a kindless Console row | §4.3 |
| 20 | optional: an abandoned probe can fill qemu's one-slot backlog, so a later click reads "unreachable" | Accepted as proposed: `CONSOLE_UNREACHABLE` names both causes; the live pass holds a console from the VM and clicks three times; the per-device refusal removes most repeat probes | §2.3 connect, §7 live pass |
| 21 | optional: the device closing the console ends in a bare "Disconnected" | Accepted as proposed: on device EOF the manager sends the status "The console closed: the device stopped or restarted." before breaking; the page keeps it after "Disconnected —" | §2.3 loop, §3, §5 roundtrip test |
