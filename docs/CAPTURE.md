# Browser Wireshark

Select **Capture traffic…** (the **Packet capture** card on the lab's **Tools** tab, a
device's right-click menu or device panel, or **Lab actions ▾ › Packet capture…**), or
click a topology link. The dialog lists the interfaces the topology
wires to that device first (a single one is already ticked). A link opens in link mode with
**both ends** ticked, one Wireshark per end because each end is its own container; right-click a link
(or focus it and press the ContextMenu key or Shift+F10) for a menu of **Capture both ends…** and
one entry per end. On a device, **All connected** ticks every wired port and **None** clears them, and
**Open as** (shown once two or more interfaces are ticked) chooses **One Wireshark for the ticked
interfaces** or **One Wireshark per interface**. The device's Interfaces section has **Capture all
connected**, which opens the dialog with every data interface ticked. The dialog remembers your last
selection for each device and link in this browser. *Other interfaces on this device* holds the rest of that namespace, and
*Advanced: capture somewhere else* holds the scope, search and capture-target selector
for bridges, host NICs, other namespaces or a device that discovery did not match; it
unfolds by itself (as *Choose a device*) only when no target could be resolved. Click
**Start capture** (the button names the plan: **Start 2 captures** when two sessions will start), then
**Open Wireshark ↗**; a plan with several sessions gives one **Open Wireshark: <device and port> ↗** link
per session, each opening its own tab. Wireshark runs on
the Containerlab VM; the workstation only needs a browser that can reach the manager.

## One interface, all connected interfaces, both ends of a link

- **One interface:** tick it (a click on a port, or the table's per-row **Capture**, ticks only that one
  and wins over anything remembered) and press **Start capture**.
- **All connected interfaces of a device:** **All connected** ticks the wired ports the VM lists. It never
  ticks `eth0`, a `tapN` or an internal device such as cEOS `fabric`; those stay opt-in under *Other
  interfaces on this device*. If the device has two or more connected ports, **Open as** decides
  whether they share **One Wireshark for the ticked interfaces** (one session, one PCAPNG stream; the
  default) or get **One Wireshark per interface** (one session each). The plan sentence above
  **Start capture** says which will happen before anything starts.
- **Both ends of a link:** click the link (or press Enter or Space on it). Each end has a checkbox, both
  ticked, with the container interface the port maps to. Two ends on two devices are two sessions, so
  **Open as** is hidden; the plan reads *Both ends of the link: … one Wireshark each (2 sessions)*. Untick
  an end, or choose **Capture <device>: <port>…** in the link's menu, to capture only one. A self-loop (both ends on one
  device) is one namespace, so **Open as** appears there. An end the VM cannot list yet (device still
  starting, not running, or a port name with no known mapping) is disabled with the reason, and
  **Choose the interface on <device>…** switches the dialog to that device's own interface list.
- **What the manager remembers:** per lab and device or link, the last ticked interfaces (or ends) and the
  **Open as** choice, plus the last **Open as** choice as a browser default. It is kept in this browser
  only (browser storage), applies only to interfaces the VM still lists, is read and written only when
  the dialog was opened without a specific port in mind (a clicked port, a menu entry naming one end or
  **Capture all connected** wins), and is written only after every session of a plan started. The dialog
  says *Your last selection here was restored.* when it applied. Nothing about it reaches the manager's
  data.

## The capture stack

The stack is part of every installation: the installer sets it up as its fourth
phase, and every later install or upgrade refreshes it (the session service image
carries the release number). The same script works on its own from any directory
and recreates the manager itself so it loads the settings:

```bash
sudo bash "$HOME/projects/clab-manager/deploy/setup-capture.sh"
```

It pulls the pinned Wireshark image, builds the session service from this source,
starts the capture Compose project (Edgeshark on localhost 5001, the session service
on localhost 5801), writes `CAPTURE_PROVIDER`, the two URLs and the service token into
`clab-backup-ui/.env` while preserving unrelated settings and an existing token, and
recreates the manager (`--no-recreate` leaves the manager container alone; `start-manager.sh` uses it
and recreates the manager itself). It recreates the Edgeshark and session containers every time
(an upgrade can rename the project network, and only a recreated container joins the
new one), so discovery pauses for a few seconds and running browser sessions are
removed: download saved captures before upgrading.

To take the stack down deliberately, add `--remove`: it stops the services and
writes `CAPTURE_PROVIDER=disabled` (the token is kept), the device and link
**Capture traffic…** actions report that packet capture is not set up on this VM, and
later upgrades leave the stack alone. Rerun without `--remove`
to bring it back. The health check reports a missing stack as a WARN with that
command.

The stack owns localhost ports **5001** (Edgeshark) and **5801** (sessions).
Desktops have no published ports. If another Edgeshark installation owns 5001,
resolve that conflict first; setup never removes another project's containers.
Custom capture URLs cause automatic configuration to stop without overwriting
them. The supported default is this bundled stack on the manager's Linux VM.

For manual or image-based manager configuration, copy the four capture settings
from the protected source `.env` into the manager's existing environment file:

```dotenv
CAPTURE_PROVIDER=edgeshark
CAPTURE_EDGESHARK_URL=http://127.0.0.1:5001
CAPTURE_SESSION_URL=http://127.0.0.1:5801
CAPTURE_SESSION_TOKEN=<the same 64-hex-character secret used by the session service>
```

Do not commit environment files or print the token in support logs. The browser
never receives it. These addresses resolve on the VM. The session service uses
`http://packetflix:5001` on the dedicated `clab-manager-capture` Docker network.
Discovery and capture must reach that same instance; the bundled service is not
configured to capture from arbitrary remote Edgeshark hosts.

## Sessions and files

- Stop capture in Wireshark, then **File → Save As** under **/pcaps**, typing the
  full file name ending in `.pcapng`: Wireshark on the VM does not add the extension.
  The viewer's *How to save a capture* toggle repeats these steps.
- Click **Download saved captures** and extract the `.tar` archive to obtain the
  PCAP/PCAPNG files. Files saved outside `/pcaps` are not included. While nothing
  has been saved there yet, the button reports "No saved captures yet" instead of
  handing over an empty archive.
- **Reconnect viewer** returns to the existing session. Closing a tab leaves it
  available under **Your capture sessions** until idle expiry.
- **End session** deletes its container and temporary files, with confirmation.
- **Your capture sessions** (in the dialog) lists what was started from this browser, each row named by
  device, port and lab (for example *vsw ge-0/0/0 (eth1) · parity*) with *at most … left (15 min once its
  viewer is closed)*: the time is an upper bound, because the list is read when the dialog or the Tools
  tab opens and after a start or an end, never on a timer. Each viewer tab is titled with its device and
  interfaces, so several are told apart in the tab strip. The Tools tab's **Packet capture** card shows
  *n Wireshark session(s) running from this browser.*
- **End all my sessions** (the Tools card and the dialog, shown only while a session exists) ends every
  session started from this browser after one confirmation that counts them and warns that capture files
  are deleted. The manager lists the sessions of this browser at the service and ends each; a session that
  could not be ended is named (*Could not end …; try End session on its row.*) and the rest are still
  ended. Other browsers' sessions are untouched.
- Maximum **4 concurrent sessions** on the VM, counted across every browser, **15 minutes idle** without viewer
  polling (the idle rule starts to matter once the viewer is closed), and **2 hours total lifetime**. One
  Wireshark per interface, or per link end, uses one slot each. Before it starts a plan the dialog counts
  your own running sessions and refuses a plan that would pass the limit, with the way out (*End a
  session under Your capture sessions, untick interfaces, or open one Wireshark for all of them*; for a
  link, *untick one end*). Another browser's sessions are not visible to that count, so a slot can still be
  taken meanwhile. Cleanup normally sweeps every 15 seconds; a
  container Docker refuses to remove is retried on the next sweep without
  holding up the others. An open viewer of a stopped desktop does not count as
  activity, so that session's slot frees after the idle time.
- Quitting Wireshark (or Wireshark ending on its own) restarts it in the same
  desktop, and files already saved under `/pcaps` stay. If the desktop container
  itself stops (Docker restart, the whole container killed), its tmpfs-backed
  `/pcaps` is normally gone with it: the viewer says the desktop stopped and keeps
  **Download saved captures** as the check, which reports the loss or hands over
  whatever is still there.
- Each session has 1 GiB RAM, 1.5 CPU quota, 256 PIDs, 256 MiB `/pcaps`, 256 MiB
  `/tmp` and 64 MiB `/config`. Use Wireshark capture limits/ring buffers for busy
  interfaces; temporary storage can fill before the lifetime limit.

When a plan with several sessions starts only in part (for example the limit is reached by another
browser after the first start), the dialog shows the manager's sentence naming what started and what did
not, keeps the **Open Wireshark** links of the sessions that started, unticks and disables their boxes, and
the button reads **Start the remaining <n>**. Pressing it asks again for only the remaining ones; a session
that had in fact started, if the reply was lost, is met again instead of duplicated. If a reply is lost
the row says *This capture may have started; see Your capture sessions.*

Captures are separate from backups, Git history and persistent manager data.
The manager stores nothing about them: no capture file, no session record and no choice of the person is
kept in its Store, and its in-memory list of session labels is gone when it restarts (a session it did
not start itself is then named from its container). They do not survive session deletion, service restart or host restart. Browser
cookies isolate sessions between profiles; tabs in the same profile share them.
Clearing cookies loses access until automatic cleanup.

## Coverage

Live node management/data ports, host NICs, bridges, veth, VLAN, VXLAN, loopback
and other namespace interfaces are selectable when exposed by Edgeshark. The scope
**Everything on the VM** (under *Advanced*) includes interfaces outside the drawing. Shared host namespaces
are deduplicated with aliases; node/lab views retain exact container-name matching.
Multiple interfaces in one namespace share a PCAPNG stream, or open one Wireshark each when you choose
*One Wireshark per interface*. Separate namespaces use separate sessions, so both ends of a link are two
sessions. Either link end captures that side's traffic.

NOS aliases can differ from Linux interface names. A link (its menu, or a click on it) resolves this automatically: containerlab wires each supported kind's own port
names onto sequential `ethN` container veths in a fixed, documented order (never a "+1"
guess), so `ge-0/0/0` preselects `eth1` on a vJunos-switch, vJunos-router or vSRX, `et-0/0/0` preselects
`eth4` on cJunosEvolved (its own `eth1`-`eth3` are reserved), `xe-0/0/0` preselects `eth1` on a vQFX and
`Gi0/0/0/0` preselects `eth1` on an XRv9k; Nokia SR Linux keeps its own `e1-N` veth names (`ethernet-1/N` is
the same port's alias); EOS and Linux port names already are the container name. The mapping (`app/topology.py`
`container_interface`, cited to each kind's page on containerlab.dev) is always confirmed
against the live Edgeshark interface list before *Start capture* is enabled — a name that is
not (yet) live keeps the manual list open with the reason instead of guessing. **The tap
device is never preselected**: a vJunos-style image's own management VM exposes both a
`tapN` (its side of the link) and the `ethN` veth next to it; only the veth is what
containerlab's Wireshark integration captures, so a mapped port only ever preselects `ethN`.
An unrecognised kind or port shape (a breakout child, a `.unit` sub-interface, or a kind with
no rule) falls back to the manual interface list exactly as before.

DOWN interfaces omitted by Edgeshark, stopped containers, and traffic hidden inside nested
router VMs remain outside this view. Guest capture or mirroring is needed for unexposed
traffic.

## Architecture and maintenance

`app/capture.py` handles Edgeshark discovery and identity/interface validation. `POST /api/capture/launch`
takes either one `target_id` with its `interfaces`, or `captures`, one to four such entries (the set
form, used for one Wireshark per interface and for both ends of a link): the manager validates every entry
against one fresh discovery before it starts any, counts your own running sessions, then starts the entries
in order with request ids derived from each entry's content, so a retry meets the same session. The
manager keeps an in-memory label (lab, device, port names) for the sessions it started, never stores it,
and answers `GET /api/capture/sessions` and `POST /api/capture/sessions/end-all` from the service's
listing for the browser's own cookie only.
`app/capture_sessions.py` is the authenticated service adapter and bounded
HTTP/WebSocket relay. `app/capture_service.py` runs separately and creates only
fixed-image, labelled Wireshark containers. `static/capture-session.js` embeds the
noVNC RFB module supplied by the pinned image, without VS Code or CDN dependencies.
That module runs as the manager's own JavaScript, so the service and the manager
relay `core/rfb.js` and the modules it imports only when each one's SHA-256 matches
`VIEWER_ASSETS` in `app/capture_sessions.py`, the pinned image's own bytes; a desktop
that serves anything else (a changed or compromised container) gets the viewer
refused instead of run. The viewer stops waiting at that refusal and asks for a new
capture; only a desktop that is still starting, or a capture service that cannot be
reached for a moment, keeps it polling before it offers **Reconnect viewer**.

`/pcaps` is a tmpfs-backed anonymous Docker volume (256 MiB, owned by the desktop
user, labelled, removed with the container and swept at service start) rather than a
container tmpfs: the daemon's archive API behind the download reads volumes but never
a tmpfs mounted inside the container. `/tmp` and `/config` stay container tmpfs, so
tools that inspect them must run inside the container (`docker exec`), never
`docker cp`. Both WebSocket relays offer websockify's `binary` subprotocol upstream
and echo it only to a browser that offered it; the pinned image's websockify rejects
a handshake without it.

The session service alone mounts the Docker socket, which gives it host-level
administrative power. Keep it restricted to trusted VM operators. Both published
ports (`5001`, `5801`) are hard-coded to `127.0.0.1` in `deploy/compose.capture.yml`
— there is no `CAPTURE_BIND`/`CAPTURE_PORT` override — so they are reached only
through the manager's same-origin relay (`app/capture_sessions.py`) or a browser on
the VM itself, never directly from the LAN. The manager
never receives that socket, privileged mode or new host-gateway commands. API
clients cannot specify images, commands, mounts, networks, ports or service URLs.
Wireshark containers have no host mounts or Docker socket. The browser receives
only noVNC JavaScript, the desktop stream, its own desktop's password and its own
capture-folder download; upstream file-manager and terminal endpoints are not exposed.

All desktops share the `clab-manager-capture` network with each other and with
Edgeshark, and the pinned Wireshark runs Lua, so a student can run programs inside
their own desktop. So each desktop's VNC server demands a random password created for that
session (`VNC_PASSWORD`), which only the service creates and only the owning browser is given (through the manager's same-origin relay, which does not store or log it), and
its raw VNC port 5900 stays closed (`VNC_LISTENING_PORT=-1`): a program in one desktop
reaches another desktop's web port, but not its screen, files or session. It can
still reach Edgeshark's capture and discovery services, which stream and list any
interface on the VM just as the *Everything on the VM* scope does, and the manager's
own port when it listens on all addresses.

The manager still has no user login. Cookie isolation is not account-based
multi-user authorization. Retain the trusted management-network boundary or use
an authenticated HTTPS reverse proxy. The proxy must support WebSocket upgrades
for `/api/capture/sessions/*/websockify`. The proxy's public name must be listed in
`UI_ALLOWED_HOSTS` and passed to the manager as the `Host` header; see
[Opening the manager by a name](INSTALL.md#opening-the-manager-by-a-name). Do not
expose Docker or ports 5001/5801.
No additional browser-facing port or iframe is needed.

Manager and service both re-discover and validate selected identity/interfaces
before creation. Identity HMACs exclude unrelated interface churn. This reduces
stale selections but does not claim Packetflix itself validates PID/start-time
identity or eliminates the final discovery-to-capture race.

The image is digest-pinned. Changes must preserve `PACKETFLIX_LINK`, `/core/rfb.js`,
`/vendor/` modules, `/websockify` and the `VNC_PASSWORD`/`VNC_LISTENING_PORT` settings,
and pass unit and Docker smoke tests. Keep the pin in `capture_service.py` and
`setup-capture.sh` identical, and replace `VIEWER_IMAGE` and `VIEWER_ASSETS` in
`capture_sessions.py` with the new image's list: copy its `/opt/noVNC` out without
running it and print the list with
`python3 "$HOME/projects/clab-manager/deploy/capture/viewer_assets.py" <folder>` (the
tool's docstring has the commands). The smoke test fetches every listed module from
the real image. Upstream resolves the latest plugin at build time; consuming a fixed
built image avoids installation variation. Security updates still require deliberate review and a new pin. See
`deploy/CAPTURE-THIRD-PARTY-NOTICES.md`.

## Health, troubleshooting and removal

```bash
sudo docker compose --env-file "$HOME/projects/clab-manager/clab-backup-ui/.env" -f "$HOME/projects/clab-manager/deploy/compose.capture.yml" ps
sudo docker compose --env-file "$HOME/projects/clab-manager/clab-backup-ui/.env" -f "$HOME/projects/clab-manager/deploy/compose.capture.yml" logs --tail=80 sessions
curl --fail http://127.0.0.1:5001/discover/mobyshark
bash "$HOME/projects/clab-manager/deploy/check-install.sh"
```

The health checker verifies discovery, service authentication and availability of
the pinned image without starting capture. It cannot prove live packets arrived.
If the desktop starts slowly, reconnect after initialization. If Wireshark exits,
it restarts in the same desktop; reconnect the viewer. If the viewer reports that
the desktop stopped, click **Download saved captures** first: Docker normally discards
the tmpfs-backed `/pcaps` with a stopped desktop, and the download then says the files
were lost, but anything still there is handed over. Then end the old session and
create another. A capture outage does not disable backups, topology, SSH or lab operations.

The browser console logs `noVNC requires a secure context (TLS)` on every viewer
load over plain HTTP: noVNC reports that the page is not served over HTTPS. It does
not mean the desktop is open. Every desktop sets its own per-session VNC password
(`VNC_PASSWORD`), which only the session service creates and only the owning browser is given (through the manager's same-origin relay, which does not store or log it), and
`deploy/capture/smoke.py` checks that a desktop offers only VNC password
authentication. Over plain HTTP the stream, like every other manager page, is not
encrypted on its way to the browser; use an authenticated HTTPS reverse proxy (above)
where that matters. A viewer that disconnects immediately while the
sessions log shows `websockify ... 403` means the service could not complete the
websockify handshake (a session service built before 1.21.1 omitted the `binary`
subprotocol): rebuild the stack with the setup command above.

To disable capture, download and end your sessions, then:

```bash
sudo bash "$HOME/projects/clab-manager/deploy/setup-capture.sh" --remove
```

Normal shutdown removes this service's labelled Wireshark containers. After forced
shutdown or a Docker outage, restart the capture service for orphan cleanup. Its stable deployment label
survives token rotation. Do not remove unrelated containers or manager data.

## Sources and acceptance

- [Containerlab GUI capture](https://containerlab.dev/manual/gui/#packet-capture)
- [SR Labs Wireshark container](https://github.com/srl-labs/wireshark-vnc-docker)
- [Startup contract](https://github.com/srl-labs/wireshark-vnc-docker/blob/main/startapp.sh)
- [noVNC API](https://github.com/novnc/noVNC/blob/master/docs/API.md)
- [Packetflix API](https://github.com/siemens/packetflix/blob/main/api.md)
- [Containerlab capture coverage](https://containerlab.dev/manual/wireshark/)
- Per-kind veth order behind the automatic mapping: [vr-vjunosswitch](https://containerlab.dev/manual/kinds/vr-vjunosswitch/),
  [cjunosevolved](https://containerlab.dev/manual/kinds/cjunosevolved/),
  [vr-vqfx](https://containerlab.dev/manual/kinds/vr-vqfx/), [vr-xrv9k](https://containerlab.dev/manual/kinds/vr-xrv9k/),
  [vr-vsrx](https://containerlab.dev/manual/kinds/vr-vsrx/),
  [ceos](https://containerlab.dev/manual/kinds/ceos/), [srl](https://containerlab.dev/manual/kinds/srl/)

`deploy/capture/smoke.py` also starts a second desktop on the same namespace under another request id
and checks that the two sessions have their own id, container and VNC password, that repeating the first
request returns the first session, and that ending both leaves nothing. For a browser pass without Docker,
`docs/redesign/tools/fixture_manager.py --capture` scripts the discovery and the session service.

The unit tests (`test_capture*.py`, `test_capture_ui.js`) run with the rest of the
suites; see the README's development section. On an isolated Linux Docker host,
`deploy/capture/smoke.py` exercises the pinned image and live Edgeshark loopback
traffic; CI runs it on every push. See `clab-backup-ui/VALIDATION.md` for checks
actually executed. VM acceptance also includes a topology link, expected packets,
Wireshark Save As, download, reconnect and session removal.
