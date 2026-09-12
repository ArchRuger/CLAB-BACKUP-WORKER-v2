# Packet capture and Wireshark — 1.20.0

Capture packets from node actions, a topology link, or **Capture packets** in the
workspace toolbar. Select a live target and one or more Linux interfaces, click
**Prepare capture**, then **Open Wireshark**. Stop, filter, inspect and save the
PCAPNG file in Wireshark. Each link exposes both endpoints; selecting either side
observes that side's traffic. Separate namespaces require separate capture sessions.

The feature is optional and disabled until configured. It uses Edgeshark's
discovery and packet streaming services with the workstation's cshargextcap plugin.
It does not require a VS Code session, device SSH credentials, tcpdump inside NOS
images, a privileged manager, or changes to the existing restricted SSH gateway.

## Setup on the Containerlab VM

If Edgeshark is already installed for VS Code, reuse that service instead of
starting a second installation on port 5001. Both manager and workstation must
reach the **same** Edgeshark instance on the intended lab host.

For a new installation, from this repository root on the Linux lab VM:

```bash
sudo docker compose -f deploy/compose.capture.yml up -d
curl --fail http://127.0.0.1:5001/version
curl --fail http://127.0.0.1:5001/discover/mobyshark
```

The first discovery request can take longer while engines are detected. Retry
after startup if needed. The response contains a `containers` list with namespace
identities and `network-interfaces`. The separate `clab-manager-capture` project
contains Ghostwire and Packetflix, with pinned multi-architecture image digests.
It does not start, stop, recreate or alter any lab node.

In `clab-backup-ui/.env`, add or update these settings, preserving existing values
such as UI port and binding. Do not replace the entire file:

```dotenv
CAPTURE_PROVIDER=edgeshark
CAPTURE_EDGESHARK_URL=http://127.0.0.1:5001
CAPTURE_EDGESHARK_PUBLIC_URL=http://127.0.0.1:5001
```

Upgrade the complete source using the normal `bash deploy/install.sh` workflow;
this updates the version-matched helpers and manager while retaining data and VM
passwords. For an already installed 1.20.0 manager, applying only capture settings
requires recreating that service:

```bash
sudo docker compose --env-file clab-backup-ui/.env \
  -f clab-backup-ui/compose.yml up -d --no-deps backup-ui
```

For image-based deployment, put the same variables in your existing
`deploy/image.env` and use the existing `deploy/compose.image.yml` launch command
with a 1.20.0 image. A Docker container restart alone does not load changed Compose
environment values. Keep the persistent `/data` mount and encryption key.

## Workstation setup (Windows, Linux or macOS)

Install desktop Wireshark and the matching
[Siemens cshargextcap release](https://github.com/siemens/cshargextcap/releases/latest).
On Windows, run the installer EXE from the Windows amd64 ZIP. It installs the
external capture plugin and the `packetflix:` URL handler. Restart Wireshark.
The Wireshark capture interface list should include **Docker host capture**.
On Linux use the appropriate upstream package. On macOS install both the binary
and the separate URL handler using the
[upstream instructions](https://github.com/siemens/cshargextcap#installation).
The upstream project specifically documents incompatibility with Wireshark 4.4.0.

With the supplied localhost-only deployment, keep this tunnel running in your
workstation terminal (replace the account/host with your normal VM login):

```text
ssh -N -L 127.0.0.1:5001:127.0.0.1:5001 your-linux-user@your-lab-vm
```

Use your normal Linux account; the manager's `clab-discovery` account deliberately
does not provide a general shell or port forwarding. Open
`http://127.0.0.1:5001` on the workstation to verify access. Both desktop Wireshark
and its plugin use the workstation end of the tunnel. If port 5001 is occupied
locally, use a different **left-hand** port in `-L` and change only
`CAPTURE_EDGESHARK_PUBLIC_URL` accordingly.

An existing directly reachable service may instead use its lab-host URL for both
settings. `CAPTURE_EDGESHARK_URL` is resolved by the manager; the public URL is
resolved by each workstation. HTTP and HTTPS, IPv6 literals and reverse-proxy
path prefixes are supported. HTTPS becomes WSS for the native plugin. No password
or token is accepted in these URLs. TLS certificates must be trusted on both ends.
Interactive SSO in a browser is not automatically available to a native plugin.

## Coverage and limits

| Target | Selection |
| --- | --- |
| Node management and data ports | Node Capture, then its live Linux interface |
| Either endpoint of a drawn link, including coincident nodes | Click or right-click the link, or focus it and press Enter |
| Interfaces added since topology import | Refresh interfaces; discovery is independent of the drawing |
| Host NICs, bridges, host veth, VLAN/VXLAN, macvlan, management network | All host targets; select the namespace and interface |
| Unmatched map nodes, custom names, unlinked legacy inventory | All host targets; explicitly select the actual namespace |
| Processless network namespaces | All host targets; choose the bindmount target |
| Several interfaces in one namespace | Select multiple checkboxes; PCAPNG preserves interfaces |

The live Linux namespace/interface is the capture location, not the displayed NOS
port alias. For example, the existing XRv9k diagram importer can display an
`eth2` export as `Gi0/0/0/1`; select the live `eth2` interface. The UI preselects an
imported port only when its name exists in the live interface list. It never
guesses an alias or silently captures the whole namespace.

Ghostwire omits interfaces reported DOWN because dumpcap may fail on them,
particularly TAP/TUN. Stopped containers and nonexistent interfaces cannot be
captured. For VM-based NOS images, capture observes exposed Linux links/TAPs;
traffic wholly inside a VM, a NOS logical interface, or a userspace dataplane may
need that platform's own capture/mirroring facility. Bridge, offload and interface
placement affect which frames are visible. This is not a promise that a single
host bridge capture sees every switched frame or every guest-internal packet.

The manager prepares a handoff; it cannot detect whether your browser launched
Wireshark or whether packets are arriving. It never reports a handoff as a running
or completed capture. Closing the manager tab does not stop an external capture.
Use Wireshark to stop it. Captures are stored only where you save them locally;
they are not backup jobs, Git snapshots, or automatic scheduled operations.

## Troubleshooting

- **Disabled:** configure the three variables, then recreate the manager.
- **Cannot read discovery:** check the VM-side URL and `/discover/mobyshark`, the
  two service logs, port conflicts, trusted TLS certificates and proxy path.
- **No matching node:** use All host targets. Matching uses the exact container
  prefix, deployment name and definition node, never substring/IP matching.
- **Target changed:** refresh and reselect. Restarts, changed interfaces or a
  manager restart invalidate old selections.
- **No Wireshark opens:** allow the browser's external-app prompt, verify the
  plugin/URL handler installation, and follow the local setup page.
- **Wireshark opens but cannot connect:** verify the workstation public URL and
  tunnel. The manager's connection test cannot establish workstation reachability.
- **Empty capture:** generate expected traffic and check interface selection,
  state and guest/host visibility. Try the other endpoint. Save as PCAPNG.

## Access, isolation and removal

This application retains its existing trusted-lab, no-login access model. Anyone
with manager access can browse capture targets when enabled. Edgeshark itself
needs substantial host namespace capabilities; its endpoint grants packet access.
The supplied deployment binds port 5001 to loopback. Use a tunnel or an appropriately
protected management network; do not expose an unauthenticated capture endpoint
to the Internet. Opening the manager's port does not protect Edgeshark's port.
The manager receives no additional capabilities, Docker socket, SSH command or
VM password permissions. Packet data travels from Packetflix to the workstation.

Set `CAPTURE_PROVIDER=disabled` and recreate the manager to disable new handoffs.
Stop external captures in Wireshark. To remove only the optional services:

```bash
sudo docker compose -f deploy/compose.capture.yml down
```

Do not run that command against an independently managed VS Code Edgeshark stack.
Disabling the manager provider does not revoke capture URLs or direct Edgeshark
access; stop the provider or restrict its network access when revocation is needed.

## Maintenance contract and research

`app/capture.py` contains the provider protocol, explicit provider factory,
normalized discovery contract and launch builder. `static/capture.js` owns the
dialog. The rest of the application only registers routes and provides entry
points. There is no frontend framework, vendored Wireshark build, packet parser,
background capture process, new database schema or privileged manager helper.

Endpoints: `GET /api/capture/status`, `GET /api/capture/targets` (optional `lab_id`
and `node`), and `POST /api/capture/launch` with an opaque target ID and selected
interfaces. Same-origin protections apply. Four simultaneous discovery requests,
bounded reads/timeouts and strict payload limits prevent a broken provider from
holding unlimited resources. URL redirects and ambient HTTP proxies are disabled.
The UI cannot supply a server URL, process ID, namespace number or command.

Each handoff performs fresh discovery and verifies the full selected identity
with a server-generated HMAC. URLs include namespace, PID, process start time,
name and engine prefix for Packetflix's own stale-namespace checks. Processless
namespaces have no PID/start-time protection; their identifiers can be reused
between verification and capture, an upstream limitation. The UI hides prepared
URLs after 60 seconds, but URLs themselves are not bearer tickets with server-side
expiry. They remain native Edgeshark URLs governed by provider access.

The image digests in `deploy/compose.capture.yml` were resolved from Siemens'
public multi-architecture manifests on 2026-09-12. Update them deliberately and
run the contract tests plus the live acceptance checks below. Keeping images
pinned and the integration small reduces drift; it does not eliminate upstream
maintenance or the need to apply security updates.

Research checked on 2026-09-12:

- [Containerlab capture guide](https://containerlab.dev/manual/wireshark/): namespace
  capture, SSH/tcpdump/tshark alternatives, and the recommended Edgeshark integration.
- [Containerlab networking](https://containerlab.dev/manual/network/): management,
  point-to-point, host, bridge and macvlan link placement.
- [Containerlab VS Code integration](https://github.com/srl-labs/vscode-containerlab):
  the extension can install Edgeshark; the desktop plugin is installed separately.
- [Siemens plugin](https://github.com/siemens/cshargextcap): workstation installation
  and protocol-handler responsibilities. It is a Wireshark extension, not a VS Code extension.
- [Packetflix API](https://github.com/siemens/packetflix/blob/main/api.md): discovery
  proxy and structured `/capture?container=...` namespace identity contract.
- [Ghostwire target schema](https://github.com/siemens/ghostwire/blob/main/api/v1/targets.go)
  and [target wrapper](https://github.com/siemens/ghostwire/blob/main/api/v1/targetdiscovery.go):
  host/process/container/bindmount discovery and omission of DOWN interfaces.
- [Upstream launch implementation](https://github.com/siemens/ghostwire/blob/main/webui/src/components/targetcapture/TargetCapture.tsx):
  `packetflix:ws(s)://.../capture`, JSON container selector and slash-separated `nif`.
- [Upstream deployment](https://github.com/siemens/edgeshark/blob/main/deployments/wget/docker-compose-localhost.yaml):
  service capabilities, host PID visibility, AppArmor and localhost binding.

## Validation and live acceptance

Automated contract/API and JavaScript tests cover the provider boundary, exact
matching, namespaces, multiple interfaces, safe URLs, bounded reads, errors,
stale selections, native handoff and link actions. See `clab-backup-ui/VALIDATION.md`
for the actual local results and remaining deployment checks.

On a Linux lab host after installation, verify `/version` and discovery; then use
a disposable two-node test lab. Generate ping traffic and confirm live ICMP in
Wireshark from both endpoints, a management interface and a host interface. Select
two interfaces in one namespace and verify their PCAPNG interface identifiers.
Restart a disposable node after discovery and verify the old selection is rejected.
Stop Edgeshark and confirm existing manager operations remain usable. Test your
Windows plugin/tunnel route and each supported NOS mapping before declaring the
integration validated in that environment. Never restart a training lab to run
these acceptance checks without the operator's authorization.
