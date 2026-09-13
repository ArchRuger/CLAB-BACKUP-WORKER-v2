# Browser Wireshark — 1.21.1

Select **Capture packets**, a node's **Capture** action, or either endpoint of a
topology link. Select one or more live Linux interfaces and click **Start browser
capture**, then **Open Wireshark in browser**. Wireshark runs on the Containerlab
VM; the workstation only needs a browser that can reach the manager.

## Install or migrate from 1.20.x

From this complete source checkout on the Linux VM:

```bash
sudo bash deploy/setup-capture.sh
bash deploy/install.sh
```

Optional setup pulls the pinned Wireshark image, builds the session service,
starts the capture Compose project, and configures `clab-backup-ui/.env`. It
preserves unrelated settings and the existing service token, and removes the
obsolete `CAPTURE_EDGESHARK_PUBLIC_URL`. It recreates the Edgeshark and session
containers every time (an upgrade can rename the project network, and only a
recreated container joins the new one), so discovery pauses for a few seconds and
running browser sessions are removed. The normal installer upgrades the manager
and matching helpers while preserving data and VM credentials.

If the manager already runs 1.21.0, apply changed capture settings with:

```bash
sudo docker compose --env-file clab-backup-ui/.env \
  -f clab-backup-ui/compose.yml up -d --no-deps backup-ui
```

No Windows plugin, URL handler, VNC client or capture-port SSH tunnel is needed.
An existing capture-only tunnel may be closed. Workstation software used by other
tools is not uninstalled. Save and stop any old desktop captures yourself.
Download browser captures before upgrading/restarting the session service: its
startup reconciliation removes temporary session containers.

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

- Stop capture in Wireshark, then **File → Save As** under **/pcaps**.
- Click **Download saved captures (.tar)** and extract the archive to obtain the
  PCAP/PCAPNG files. Files saved outside `/pcaps` are not included. While nothing
  has been saved there yet, the button reports "No saved captures yet" instead of
  handing over an empty archive.
- **Reconnect viewer** returns to the existing session. Closing a tab leaves it
  available under **Sessions in this browser** until idle expiry.
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
and other namespace interfaces are selectable when exposed by Edgeshark. **All
host targets** includes interfaces outside the drawing. Shared host namespaces
are deduplicated with aliases; node/lab views retain exact container-name matching.
Multiple interfaces in one namespace share a PCAPNG stream. Separate namespaces
use separate sessions. Either link endpoint captures that side's traffic.

NOS aliases can differ from Linux interface names. DOWN interfaces omitted by
Edgeshark, stopped containers, and traffic hidden inside nested router VMs remain
outside this view. Guest capture or mirroring is needed for unexposed traffic.

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
sudo docker compose --env-file clab-backup-ui/.env -f deploy/compose.capture.yml ps
sudo docker compose --env-file clab-backup-ui/.env -f deploy/compose.capture.yml logs --tail=80 sessions
curl --fail http://127.0.0.1:5001/discover/mobyshark
bash deploy/check-install.sh
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
websockify handshake (1.21.0 omitted the `binary` subprotocol): rebuild the
sessions service with `sudo bash deploy/setup-capture.sh`.

To disable capture, download/end sessions, set `CAPTURE_PROVIDER=disabled` and
recreate the manager. Remove the optional stack using:

```bash
sudo docker compose --env-file clab-backup-ui/.env -f deploy/compose.capture.yml down
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

From `clab-backup-ui`, run `python -m unittest discover -s tests -t tests -p
"test_capture*.py"` and `node --test tests/test_capture_ui.js`. On an isolated Linux
Docker host, `deploy/capture/smoke.py` exercises the pinned image and live Edgeshark
loopback traffic; CI is configured to run it. See `clab-backup-ui/VALIDATION.md` for
checks actually executed. VM acceptance also includes a topology link, expected
packets, Wireshark Save As, download, reconnect and session removal.
