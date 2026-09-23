# Browser Wireshark

Select **Capture traffic…** (the **Packet capture** card on the lab's **Tools** tab, a
device's right-click menu or device panel, or **Lab actions ▾ › Packet capture…**), or
click either endpoint of a topology link. The dialog lists the interfaces the topology
wires to that device first (a single one is already ticked; a link opens on its first
endpoint). *Other interfaces on this device* holds the rest of that namespace, and
*Advanced: capture somewhere else* holds the scope, search and capture-target selector
for bridges, host NICs, other namespaces or a device that discovery did not match; it
unfolds by itself (as *Choose a device*) only when no target could be resolved. Click
**Start capture**, then **Open Wireshark ↗**. Wireshark runs on
the Containerlab VM; the workstation only needs a browser that can reach the manager.

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
recreates the manager. It recreates the Edgeshark and session containers every time
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
- Maximum **4 concurrent sessions**, **15 minutes idle** without viewer polling,
  and **2 hours total lifetime**. Cleanup normally sweeps every 15 seconds.
- Each session has 1 GiB RAM, 1.5 CPU quota, 256 PIDs, 256 MiB `/pcaps`, 256 MiB
  `/tmp` and 64 MiB `/config`. Use Wireshark capture limits/ring buffers for busy
  interfaces; temporary storage can fill before the lifetime limit.

Captures are separate from backups, Git history and persistent manager data.
They do not survive session deletion, service restart or host restart. Browser
cookies isolate sessions between profiles; tabs in the same profile share them.
Clearing cookies loses access until automatic cleanup.

## Coverage

Live node management/data ports, host NICs, bridges, veth, VLAN, VXLAN, loopback
and other namespace interfaces are selectable when exposed by Edgeshark. The scope
**Everything on the VM** (under *Advanced*) includes interfaces outside the drawing. Shared host namespaces
are deduplicated with aliases; node/lab views retain exact container-name matching.
Multiple interfaces in one namespace share a PCAPNG stream. Separate namespaces
use separate sessions. Either link endpoint captures that side's traffic.

NOS aliases can differ from Linux interface names. Right-clicking a link (or its endpoint
buttons) resolves this automatically: containerlab wires each supported kind's own port
names onto sequential `ethN` container veths in a fixed, documented order (never a "+1"
guess), so `ge-0/0/0` preselects `eth1` on a vJunos-switch, `et-0/0/0` preselects `eth4` on
cJunosEvolved (its own `eth1`-`eth3` are reserved), and `Gi0/0/0/0` preselects `eth1` on an
XRv9k; EOS and Linux port names already are the container name. The mapping (`app/topology.py`
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

`app/capture.py` handles Edgeshark discovery and identity/interface validation.
`app/capture_sessions.py` is the authenticated service adapter and bounded
HTTP/WebSocket relay. `app/capture_service.py` runs separately and creates only
fixed-image, labelled Wireshark containers. `static/capture-session.js` embeds the
noVNC RFB module supplied by the pinned image, without VS Code or CDN dependencies.

`/pcaps` is a tmpfs-backed anonymous Docker volume (256 MiB, owned by the desktop
user, labelled, removed with the container and swept at service start) rather than a
container tmpfs: the daemon's archive API behind the download reads volumes but never
a tmpfs mounted inside the container. `/tmp` and `/config` stay container tmpfs, so
tools that inspect them must run inside the container (`docker exec`), never
`docker cp`. Both WebSocket relays offer websockify's `binary` subprotocol upstream
and echo it only to a browser that offered it; the pinned image's websockify rejects
a handshake without it.

The session service alone mounts the Docker socket, which gives it host-level
administrative power. Keep it restricted to trusted VM operators. The manager
never receives that socket, privileged mode or new host-gateway commands. API
clients cannot specify images, commands, mounts, networks, ports or service URLs.
Wireshark containers have no host mounts or Docker socket. The browser receives
only noVNC JavaScript, the desktop stream and its own capture-folder download;
upstream file-manager and terminal endpoints are not exposed.

The manager still has no user login. Cookie isolation is not account-based
multi-user authorization. Retain the trusted management-network boundary or use
an authenticated HTTPS reverse proxy. The proxy must support WebSocket upgrades
for `/api/capture/sessions/*/websockify`. Do not expose Docker or ports 5001/5801.
No additional browser-facing port or iframe is needed.

Manager and service both re-discover and validate selected identity/interfaces
before creation. Identity HMACs exclude unrelated interface churn. This reduces
stale selections but does not claim Packetflix itself validates PID/start-time
identity or eliminates the final discovery-to-capture race.

The image is digest-pinned. Changes must preserve `PACKETFLIX_LINK`, `/core/rfb.js`,
`/vendor/` modules and `/websockify`, and pass unit and Docker smoke tests. Keep
the pin in `capture_service.py` and `setup-capture.sh` identical. Upstream resolves
the latest plugin at build time; consuming a fixed built image avoids installation
variation. Security updates still require deliberate review and a new pin. See
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
download saved files, end the old session and create another. A capture outage
does not disable backups, topology, SSH or lab operations.

The browser console logs `noVNC requires a secure context (TLS)` on every viewer
load over plain HTTP; it is harmless here because the desktop stream uses VNC
security type None inside the VM. A viewer that disconnects immediately while the
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
  [ceos](https://containerlab.dev/manual/kinds/ceos/), [srl](https://containerlab.dev/manual/kinds/srl/)

The unit tests (`test_capture*.py`, `test_capture_ui.js`) run with the rest of the
suites; see the README's development section. On an isolated Linux Docker host,
`deploy/capture/smoke.py` exercises the pinned image and live Edgeshark loopback
traffic; CI runs it on every push. See `clab-backup-ui/VALIDATION.md` for checks
actually executed. VM acceptance also includes a topology link, expected packets,
Wireshark Save As, download, reconnect and session removal.
