# Telemetry live fixes — 1.23.1

Prepared on `claude/v1.23.0-validation` from main `c8a2e26` (1.23.0) on 2026-09-13.
Scope: the first live run of the 1.23.0 telemetry release and the fixes it needed.
The user reported "the Grafana dashboard says there was an error"; the task was to
deploy the latest main on the dev VM and validate the whole setup and deployment.

## Environment

- Dev VM `clab-dev-llm` (Ubuntu 24.04.4, Docker 29.8, Compose v5.5.1, containerlab
  0.79.0, no KVM), manager 1.23.0 staged from main `c8a2e26` with
  `deploy/start-manager.sh --enable-operations` (image rebuilt, pygnmi installed),
  capture stack on `clab-capture-service:1.22.0` images, `sudo bash
  deploy/setup-telemetry.sh` (Prometheus v3.14.0 and Grafana OSS 13.0.2 pulled by
  digest), manager recreated with the new `.env`.
- Lab `ceos-pair` (two `arista_ceos` nodes, `n24l/ceos:4.35.0F`, `eth1`–`eth1`),
  saved by 1.22.0 (no telemetry setting yet), deployed through the manager's
  operations API; Ethernet1 addressed 10.0.0.1/24 and 10.0.0.2/24 by hand for link
  traffic. NOS login: containerlab default `admin`/`admin`.
- Browser checks in the desktop app's browser pane at 1280x900, console watched for
  errors; API checks with curl and stdlib Python on the VM.

## What 1.23.0 did on the VM before any fix

| Check | Result |
|---|---|
| `deploy/verify-release.py` on the staged tree | `Source release verified: 1.23.0` |
| `start-manager.sh` rebuild + helpers | exit 0; `/api/telemetry/health` enabled, pygnmi present, states `disabled: 2` (pre-1.23.0 lab) |
| `setup-telemetry.sh` | exit 0 and "Grafana dashboards installed", although `docker ps` showed `clab-manager-telemetry-prometheus-1 Restarting (1)`; its log: `Error parsing command line arguments: unexpected false` / `prometheus: error: unexpected false` |
| Grafana `/api/health` | `{"database":"ok","version":"13.0.2"}`; data source `clab-prometheus` and the three dashboards provisioned in folder *Containerlab Node Manager*; anonymous read of a dashboard 200 with `canEdit:false` |
| Grafana in the browser | every panel of *Lab overview* showed a red triangle, **"An error occurred within the plugin"** and *No data* (the user's report reproduced) |
| `check-install.sh` | PASS 60 / FAIL 1 / WARN 1: `[FAIL] Grafana telemetry dashboards — Grafana answers, but Prometheus on 127.0.0.1:9090 is not scraping the manager`; its *Next* step (rerun the setup) would not have fixed a rejected flag |
| Telemetry tab (pre-1.23.0 lab) | banner *Automatic telemetry is not enabled for this lab yet* with the **Enable** button, *Open Grafana ↗* offered, nodes *Off*; no console errors |
| **Enable automatic telemetry** on the live cEOS pair | both nodes went Waiting → Configuring → Connecting → Streaming within seconds; `applied=0` (containerlab's default `management api gnmi` / `transport grpc default` found, nothing written, no `telemetry.configure` event); endpoint `172.20.20.x:6030` plain text, JSON_IETF |
| Store after two minutes of streaming | `samples=116 dropped=60` and `samples=124 dropped=52`; Ethernet1 `rx_bps=None`, admin/oper empty on every interface; map link *unknown* |
| Raw pygnmi probe from the manager container | one 10 s cycle of `Ethernet1 counters` arrived as four notifications with timestamp ages 718 s (idle counters), 2 s (`in-octets`, `in-pkts`), 247 s (`in-unicast-pkts`) and 0.1 s (`last-update`): cEOS stamps each notification with the last change time of its leaves; a plain on-change subscription for `oper-status`/`admin-status` returned the sync marker and nothing else in 14 s, on-change with a 5 s heartbeat and sample mode both delivered the value every interval |
| After two quiet minutes | both nodes' BGP group `failed` ("No notifications for two minutes; resubscribing.") on a lab without BGP; the pill was red in the Telemetry tab |
| `docker restart clab-ceos-pair-ceos2` | the node reported *failed: The gNMI port did not answer* and the retry delay grew 15, 30, 60, 120, 240 s (`attempts=5` after eight minutes) |

## Fixes and their live verification (hot-loaded into the running container, then re-staged)

| Fix | Verification |
|---|---|
| `compose.telemetry.yml` without `--web.enable-remote-write-receiver=false` | Prometheus ready 2 s after `up -d --force-recreate`; target `http://127.0.0.1:8081/api/telemetry/metrics` `up`; Grafana data-source health `Successfully queried the Prometheus API`; *Lab overview* rendered with no error (find "error" on the page: none), Lab variable resolved to `ceos-pair`, *Nodes with telemetry* 2 |
| `setup-telemetry.sh` waits (`setup_telemetry.py --wait`) | unit-tested against stub servers (ready path, Prometheus down path, Grafana down path); exercised on the final re-stage (see below) |
| `deploy/telemetry/smoke.py` in CI | stdlib script; runs in the release-check workflow on push (result recorded in the PR checks) |
| Store: per-leaf ordering, receive-time rates and points, `POINT_MERGE`, per-field newest rate | after the hot-load: `dropped=0` on both nodes, Management0 rates present, Ethernet1 `rx_bps` follows traffic; with 10 pps × 1400 B ping between the nodes both ends showed ≈111 kb/s RX (`111244` / `111242` b/s), chart in the Telemetry tab drew the ramp; `tx_bps` 0 because the cEOS container reports 0 `out-octets` on data ports (`show interfaces Ethernet1 counters`: OutOctets 0 while InOctets grew by exactly the ping bytes) |
| EOS on-change state with heartbeat | admin/oper `UP/UP` on every interface within 10 s; map link *up* from both ends, green wire, green node dots, live legend |
| Flap | `shutdown` on ceos2 Ethernet1: link *down*, both ends `DOWN`, within 3 s; `no shutdown`: *up* within 3 s; rates resumed; Grafana *Interfaces* operational-state timeline showed the red gap |
| Idle groups | after the hot-load the BGP group reads `idle` ("nothing to report on this path"), interfaces `streaming`; in-process gNMI server test drives the same transition and the return to streaming when a neighbour appears |
| Retry cap for a port that does not answer | after `docker restart` the node retried every 30 s (`connecting` every fourth 10 s poll) instead of backing off to minutes; note that a bare `docker restart` also removes containerlab's veth links (Ethernet1 disappeared on the restarted cEOS and its gNMI server stayed "not yet running"), so the lab was recovered with a manager redeploy — see below |
| check-install hints | unit tests cover the "Prometheus does not answer" and "target down with classified error" cases; the FAIL text no longer echoes scrape errors |

## Redeploy, disable and remove, other features while streaming

Filled in below from the final run on the re-staged 1.23.1 tree.

# Automatic network telemetry — 1.23.0

Prepared on `claude/keen-dirac-qk9zzi` from main `36dfdf6` (1.22.0). Scope: the
telemetry feature described in docs/TELEMETRY.md (automatic gNMI provisioning over
SSH, an in-process pygnmi dial-in collector, a bounded in-memory session store, the
Telemetry tab, charts and the live link overlay on the map). No live lab VM or NOS
image was available in this session; everything below is local evidence.

**Round two (same branch): XR gRPC in plain text (`no-tls` ensured, recorded as
manager-owned) at the operator's request, and the optional Grafana stack.** Added
`app/telemetry_metrics.py` (Prometheus exposition at `/api/telemetry/metrics`),
`deploy/compose.telemetry.yml` (Prometheus v3.14.0 and Grafana OSS 13.0.2 pinned by
digest, host network, tmpfs volumes, memory and PID limits), `deploy/setup-telemetry.sh`
with `setup_telemetry.py`, the provisioned data source and three dashboards, the
*Grafana telemetry dashboards* health check and the **Open Grafana ↗** links. Evidence:
`test_telemetry_metrics.py` (4), `test_telemetry_setup.py` (5: env preservation and
refusals, Compose pinning/bounds, provisioning, dashboard JSON referencing only
exported metrics and the provisioned data source), one more `test_check_install.py`
case and one more browser test; `docker compose -f deploy/compose.telemetry.yml config`
accepts the file; the browser smoke with the stack announced shows both links with
the expected `var-lab`, `var-node` and `var-interface` parameters and a 73-line
metrics document. Grafana and Prometheus were **not started** in the development
session (no Docker daemon); their first run is part of the live acceptance.

**Local checks (Linux container, Python 3.11.15, Node 22.22.2).**

- `python3 deploy/verify-release.py`: `Source release verified: 1.23.0`;
  `test_release_consistency.py` passes on the bumped tree.
- Full Python suite, `.venv/bin/python -m unittest discover -s tests -t tests`:
  577 tests, OK, 1 skipped (the opt-in EOS SSH fixture, as before). The 74 new
  tests are `test_telemetry_names.py` (5), `test_telemetry_store.py` (7),
  `test_telemetry_adapters.py` (12), `test_telemetry_provision.py` (12: scripted
  EOS, IOS XR and Junos Evolved shells including enable password, privilege 15,
  rejected lines and aborts, output and prompt time limits, repeat runs that write
  nothing, removal of recorded lines only), `test_telemetry_collector.py` (7:
  normalisation of the six vendor-shaped fixtures in `tests/fixtures/telemetry/`,
  timestamp policy, failure classification without echoing details),
  `test_telemetry_manager.py` (13: readiness-triggered provisioning on the running
  app, repeat safety and backoff, credential failures and secret redaction in
  state, logs and telemetry responses, unsupported and partially supported nodes,
  stale detection and recovery, runtime change, lab operation, removal and reset
  clearing the session, address reuse across generations, settings gating, series
  API validation and bounds, explicit removal, link statuses from both ends,
  environment disable), `test_telemetry_gnmi.py` (5: the real pygnmi client against
  an in-process gRPC gNMI server that answers like EOS, XR and Junos, including
  origins, encodings, on-change fallback, login refusal and stream loss, TLS-first
  targets), `test_telemetry_metrics.py` (4), `test_telemetry_setup.py` (5) and two
  telemetry cases in `test_check_install.py`. Earlier suites
  (`test_app.py`, `test_node_readiness.py`, capture, operations, Git) are unchanged
  and green.
- Browser tests, `node --test tests/*.js`: 85 pass, 0 fail (new
  `test_telemetry_ui.js`: charts, link classes and titles, view states, settings
  save, overlay application, polling scope, Grafana links, link menu, renderer
  attributes, node menu, details drawer and tab wiring, capture context-menu
  delegation).
- Real browser smoke (not committed; Playwright with the session's Chromium against
  the app started with a seeded lab of one cEOS, one XRv9k and one cJunosEvolved
  node and 60 minutes of fake samples): the Telemetry tab, node cards, interface
  table, three charts, BGP table, settings dialog, the topology overlay (red
  mismatched link, dotted unknown links, node dots, live legend), the right-click
  link menu and *Telemetry r1:eth1* opening the tab preselected all rendered with
  no console errors and no CSP violations. Screenshots were reviewed for the
  legend/axis collision and the alias spacing, both fixed before delivery.
- Linux build path: no Docker daemon in the session, so no image build. `pip
  download --only-binary=:all: --python-version 3.12 --platform
  manylinux2014_x86_64` resolves pygnmi 0.8.15, grpcio 1.83.1, protobuf 7.36.1,
  dictdiffer and cryptography as wheels, so `pip install -r requirements.txt` in
  the python:3.12-slim image needs no compiler. `docker compose -f
  clab-backup-ui/compose.yml config --quiet` accepts the new
  `TELEMETRY_COLLECTOR` variable. `git diff --check` and `bash -n` on the deploy
  scripts are clean.

**Per-NOS support and validation matrix.**

| | cEOS | XRv9k | cJunosEvolved |
|---|---|---|---|
| Provisioning lines, prompts, scoped commit | fixture (scripted shell) | fixture (scripted shell) | fixture (scripted shell) |
| gNMI subscribe, encodings, paths | in-process gNMI server through pygnmi | in-process gNMI server through pygnmi | in-process gNMI server through pygnmi |
| Notification normalisation | fixture (`eos_*.json`) | fixture (`xr_*.json`) | fixture (`junos_*.json`) |
| Interface name mapping | unit tests | unit tests | unit tests |
| Live device: configuration, samples, traffic, link state, BGP, restart/redeploy, removal | **not verified** | **not verified** | **not verified** |

**Unverified on real images and to be confirmed with docs/TELEMETRY.md "Live
acceptance procedure":** that the containerlab defaults still enable gNMI on cEOS
and XRv9k as documented; that adding `no-tls` under an existing XRv9k `grpc` block
commits cleanly and the plain-text gRPC session accepts the password login; that
the Grafana and Prometheus containers start on the VM with the host-network,
tmpfs and dropped-capability settings; that cJunosEvolved 26.x accepts
`configure private` from the admin user and streams OpenConfig interface counters
with JSON_IETF or PROTO; which BGP paths each image serves (the BGP group reports
*unsupported* with the NOS reason when none does); the exact prompt strings of the
three CLIs (the drivers match generic prompt shapes and report a controlled
"did not return to its prompt" failure otherwise); and the real sample cadence,
which decides how quickly link colours follow an interface shutdown.

# Deploy-first UI and automatic NOS login — 1.22.0

Prepared on `claude/deploy-first-ui` from main `873366f` (1.21.1) for eight UI requests
(landing page, VM connection defaults, operation output, automatic NOS login, capture
interface list, capture target, viewer banner, `.pcapng` guidance). Everything below was
run on the Ubuntu 24.04 dev VM (Docker 29.8, Compose v5.5.1, containerlab 0.79.0, two
`arista_ceos` nodes, no KVM) against the staged 1.22.0 source (`git archive` of the
release commit), with the manager image and `clab-capture-service:1.22.0` rebuilt.

**Local checks (Windows workstation).** `python deploy/verify-release.py` reports
1.22.0. `node --test` over the ten browser test files: 74 pass, 0 fail (new
`test_readiness_ui.js`; extended `test_capture_ui.js`, `test_operations_ui.js`,
`test_vm_password_ui.js`, `test_capture_session_ui.js`). Python:
`test_node_readiness.py` (10 tests, new), `test_app.py`, `test_nodes.py`,
`test_junos_kinds.py`, `test_vm_files.py` (+1), `test_discovery.py`,
`test_import_confirmation.py`, `test_capture_sessions.py`, `test_capture_proxy.py`,
`test_runner_resilience.py`, `test_logging.py`, `test_topology.py`, `test_remove_lab.py`
and `test_manager_reset.py` pass in isolation; the full 500-test run shows only the
known Windows `os.replace` flake on random tests, each green on rerun. Linux CI is
authoritative.

**Verified on the VM, first staging (12:41 UTC):**

- Health: `check-install` PASS 59 / FAIL 0 / WARN 1 (folder coverage) with
  `[PASS] Running application version` and `[PASS] Optional packet capture`; helper
  1.22.0 connected; `/api/capture/health` ready.
- Readiness on the pair that was already running: within 6 s of the manager restart
  both nodes were probed with the saved profile, answered, the automatic NOS login
  test ran (`2/2 NOS sessions completed successfully`), the deployment bar read *NOS
  ready · 2/2 nodes accept SSH login* and the Nodes table showed *reachable* with the
  automatic-check timestamps.
- VM connection dialog: *Enable automatic discovery* and *Trust a replacement SSH
  host key on the next connection* both checked on open.
- Capture from the ceos1 row: *Topology interfaces* listed eth1 ticked, *All live
  Linux interfaces (14)* and *Advanced: other capture targets* collapsed, Start
  enabled. The session started; the viewer showed the one-row toolbar with the status
  inline and live STP/LLDP frames on eth1; *Download saved captures* answered in
  place with *No saved captures yet … type the full file name ending in .pcapng
  (Wireshark on the VM does not add the extension)*; *How to save a capture* opened
  with the same steps; the session was ended.
- Destroy lab from the deployment bar: Operation output opened with the green banner
  *✓ Destroy deployment succeeded · ceos-pair · Exit 0 · Operation completed*; the
  destroyed lab then reported *Not deployed* with both nodes *unavailable* and lab
  readiness idle.
- With the saved workspace removed, the landing page showed *Deploy a new lab*
  enabled, no VM note, no *Already running on the VM* list (nothing deployed), the
  two import links, and no *Lab actions* button.
- Deploy a new lab → Lab Topologies (in place) → /etc/containerlab → ceos-pair →
  ceos-pair.clab.yaml → Deploy lab: the workspace existed before containerlab ran
  (`lab.register` 13:04:26, deploy operation 13:04:42, VM path linked, both nodes on
  the containerlab default login, status booting); the banner read *Deploy lab
  running…* and then *✓ Deploy lab succeeded · Exit 0*; the monitor reported both
  nodes booting at 13:05:33 and answering at 13:05:53.

**Found and fixed during that run.** The automatic login test at 13:05:53 failed
`0/2` with `host key mismatch for 172.20.20.3`: the redeployed containers had new SSH
host keys (and swapped management addresses), and Ansible's paramiko transport had
recorded the old keys in the manager container's `~/.ssh/known_hosts` at 12:41 (the
inventory's `ansible_host_key_checking: False` does not reach the paramiko
sub-connection that ansible.netcommon opens, which loads and records known_hosts when
its own option is on). Before 1.22.0 every backup and login test after a redeploy
therefore failed until the manager container was recreated. Fixed by giving each job
HOME in its temporary directory plus `ANSIBLE_HOST_KEY_CHECKING=False`
(`runner.job_environment`), by making the readiness probe require a `show version`
answer over an SSH exec channel (checked against both live nodes: 0.5 s, exit 0,
`Arista cEOSLab …`) so SSH accepting a login while the CLI still starts no longer
counts, and by sending the nodes of a failed automatic test back to booting with up to
three automatic tests per boot. The shared not-ready pattern now also matches cEOS's
`% System is not yet ready` reply, which the backup path had accepted as output.

**Verified after the second staging (13:15 UTC, same manager container throughout).**
Right after the restart both running nodes answered `show version` and the automatic
test succeeded `2/2`. Then, through the API (the same preview/confirm path the UI
uses): destroy succeeded in 2 s; deploy succeeded in 46 s; 48 s after the deploy
started both nodes were *booting* (SSH not answering yet, addresses ceos1 172.20.20.3
and ceos2 172.20.20.2 reconciled by discovery); at 73 s both answered *NOS accepted SSH
login and answered show version*, the deployment bar state went to *ready*, `ssh_ready`
turned true for both, and the automatic NOS login test ran and succeeded `2/2` at
13:18:03 with the containers' new host keys. A manual backup on the redeployed lab
then succeeded `2/2` (13:18:15), and the manager container has no `~/.ssh` directory
at all afterwards: the jobs' known_hosts lived and died with their temporary
directories. `check-install` after the second staging: PASS 59 / FAIL 0 / WARN 1.
One API-only quirk seen while scripting this: a preview issued within about two
seconds of an operation finishing gets 409 *Wait for the current lab operation to
finish* while the manager runs its post-operation discovery refresh; the UI cannot
click that fast and the retry succeeds.

**Not run here.** vJunos, vQFX and XRv9k nodes cannot boot on this VM (no KVM): their
default logins are taken from containerlab.dev and their `show version` exec answers
were not exercised. `deploy/capture/smoke.py` is left to CI (`release-check`). The
Wireshark Save As dialog was not driven through noVNC.

# Browser Wireshark fixes — 1.21.1

Prepared on `claude/browser-capture-fixes` from main `7032daa` (1.21.0) after live
bug testing of 1.21.0 on the Ubuntu 24.04 dev VM (Docker 29.8, Compose v5.5.1,
containerlab 0.79.0, two `arista_ceos` nodes, no KVM). Everything below was run on
that VM against the staged 1.21.1 source (`git archive` of the release commit), with
the manager image and the `clab-capture-service:1.21.1` image both rebuilt from it.

**What 1.21.0 did on the VM before the fixes.** Every browser viewer failed with
*Viewer disconnected* (WebSocket close 1006): the pinned `wireshark-vnc-docker`
image's websockify answers HTTP 400 to a handshake without the `binary`
subprotocol, the session service closed before accept (403 in its log), and the
manager relayed the 403. CI's smoke step failed on `main` for the same reason. A
file written inside the container's `/pcaps` (what File → Save As does) was absent
from **Download saved captures** because the Docker archive API reads the container
filesystem through the daemon and never sees a tmpfs mounted inside the container.
`sudo bash deploy/setup-capture.sh` on a VM running the 1.20.1 stack ended with
`could not find a network matching network mode clab-manager-capture_default`
twice in a row and left Edgeshark stopped.

**Verified on the VM with 1.21.1:**

- **Migration.** The 1.20.1 capture stack was recreated on its original
  `clab-manager-capture_default` network, then the 1.21.1 `setup-capture.sh` ran:
  it rebuilt the service image, recreated gostwire and packetflix, created
  `sessions`, removed the old network and exited 0. `/api/capture/status` enabled,
  `/api/capture/health` `{"ready": true}`; `check-install` PASS 59 / FAIL 0 / WARN 1
  (folder coverage) with `[PASS] Optional packet capture`.
- **Viewer.** Through the manager relay from a stdlib-free `websockets` client:
  `RFB 003.008` greeting, version echo and security-type list `[1, 1]` both with no
  subprotocol offered (what the served noVNC does) and with `binary` offered
  (negotiated `binary`). In the desktop-app browser, **Start browser capture →
  Open Wireshark in browser** on `clab-ceos-pair-ceos1 eth1` rendered the real
  Wireshark desktop with *live capture in progress* and listed ICMP echo
  request/reply pairs from `ping 10.0.0.1` on ceos2 plus LLDP; Reconnect viewer
  reloaded into the same session. Cross-origin and foreign-cookie WebSocket
  attempts still return 403.
- **Downloads.** The Wireshark container now carries a labelled tmpfs-backed
  anonymous volume on `/pcaps` (256 MiB, uid/gid 1000, mode 0700, nosuid/nodev/noexec)
  and container tmpfs only for `/tmp` and `/config`. With nothing saved, the API
  answers 409 *No saved captures yet…* and the viewer shows that sentence in place
  instead of opening JSON. After copying the live capture file into `/pcaps` as
  uid 1000 inside the container, the download returned a tar with
  `pcaps/<name>.pcapng` whose bytes matched the file inside the container (pcapng
  magic, interface block present), and the viewer's Download button reported
  *Downloading saved captures*. A foreign cookie gets 404.
- **Cleanup.** End session removed the container and its volume; a dangling volume
  created by hand with the capture label was swept when the session service
  restarted; sessions survive a manager container restart.
- **Unchanged behaviour rechecked:** owner cookie flags, idempotent retry,
  409/422/404/429 paths, asset allow-list, no token in any manager response,
  service 403 without a bearer, backup job 2/2 cEOS nodes with ZIP download,
  inspect operation through the gateway.

**Not run here:** `deploy/capture/smoke.py` refuses a host with an existing capture
stack and the maintainer was using the VM's stack during this session, so its
run is left to CI (`release-check` executes it on push); it now reads `/tmp` and
saves into `/pcaps` with `docker exec`, never `docker cp`, and asserts the
empty-folder 409. Wireshark's own Save As dialog was not driven through noVNC
(keyboard modifiers do not reach the remote desktop from the desktop-app browser
pane); the file was written inside the container as the desktop user instead.

**Windows:** `python -m unittest discover -s tests -t tests -p "test_capture*.py"`
40 tests OK (with `websockets` and `uvicorn` installed), `test_release_consistency.py`
and `test_check_install.py` OK, `node --test` on the five UI suites 33 passed
including the new `tests/test_capture_session_ui.js`, `bash -n` on every deploy
script, `python deploy/verify-release.py` = 1.21.1, `git diff --check` clean.

# Browser Wireshark — 1.21.0

Prepared on `codex/browser-wireshark` from latest main `1d7e0f9` (1.20.1).
A final fetch found no additional main commits. This is source delivery, not a
published image, pushed commit or VM deployment.

- **490 Python tests completed across all 41 test files: 479 passed, 11 platform
  skips.** Tests ran per file in isolated processes on Windows. The first combined
  run was stopped while the Git integration suite was still running; a subsequent
  100-second per-file budget also timed out that suite. Its independent rerun
  completed all **24 Git tests in 248 seconds**, with no failures. The final **38
  capture tests** include discovery, stale selection, fixed Docker policy,
  ownership/authentication, retry idempotency, capacity, idle/hard expiry, partial
  creation cleanup, token rotation, saved-file transport and configuration migration.
- The manager's HTTP and binary WebSocket proxy was exercised over **real loopback
  connections to a synthetic session service**. Tests cover browser-cookie
  isolation, cross-origin rejection, upstream credential separation, JavaScript
  asset restrictions, binary round trip, download bytes and scoped CSP.
- **29 JavaScript regressions passed**, including 12 capture UI tests. Capture UI
  tests were rerun after the final launch-key/reset wording change.
- **Headless Chrome** exercised actual HTML/JS: live-interface selection against
  a synthetic API, launch, the browser popup, loading the noVNC adapter contract,
  viewer layout and ending a session. No browser script errors. Screenshots were
  visually reviewed; fixture screenshots/logs remain ignored under `.build/`.
  The displayed desktop was synthetic, not a real Wireshark GUI.
- Release metadata verifies as **1.21.0**, including the new viewer page and
  optional session-service image version. `bash -n deploy/setup-capture.sh`, Python
  compilation, parsing the four affected YAML files, and `git diff --check` passed.
- The public Wireshark image manifest was resolved and pinned to
  `sha256:682c8bd42282c44f991e0d6015ce3303e5a3aa08a1e2c2b6937fd554ddb31186`
  (Linux amd64 and arm64). Upstream Dockerfile/startup code and noVNC service paths
  were inspected. Setup's image pin is checked against the service constant.

**Still requires Linux/Docker acceptance:** no local Docker daemon was available.
The new `deploy/capture/smoke.py` and CI step have been authored but not executed
here. They start an isolated optional stack, check the real noVNC RFB greeting,
find actual captured loopback packet bytes, download saved capture data and end
its session. The smoke test refuses an existing capture stack/session and never
operates a training lab. CI also validates Compose configuration and builds the
session-service image. Do not equate local mocks, YAML parsing or this CI
configuration with a successful Docker build or live capture.

On the real VM also exercise a topology link, Wireshark filters, Stop / File →
Save As under `/pcaps`, archive download, reconnect, timeout and explicit End.
Confirm existing backup/SSH/lab operations continue. See docs/CAPTURE.md for setup,
limits, trust boundary, migration and cleanup. Historical validation below applies
to the releases named there, not to the new browser runtime.

# Capture vetting fixes — 1.20.1

- Prepared on branch `claude/capture-vetting-fixes` from main `71fb0e5` (1.20.0).
  Source delivery; no Docker image is published. Lockstep metadata verifies as
  **1.20.1** including `capture-setup.html`.
- **Live vetting of 1.20.0 on the dev VM (Ubuntu 24.04.4, no KVM)** that produced the
  findings: Edgeshark started from `deploy/compose.capture.yml` (packetflix 0.9.7,
  `127.0.0.1:5001`; `/` serves the UI, `/version` answers); the real
  `/discover/mobyshark` payload (15 rows over 5 namespaces) passes `normalize_targets`;
  the manager-built `packetflix:ws://…/capture?container=…&nif=eth0%2Feth1` URI, read
  with a stdlib WebSocket client on the VM while pinging between the cEOS nodes,
  delivered valid pcapng (one SHB, two IDBs, dozens of EPBs), so multi-interface and
  the percent-encoded `nif` work; 409 for unknown, duplicate and forged selections and
  after a disposable container restart; 403 cross-origin; 502 with a safe message when
  packetflix was stopped while the operations probe kept passing. Against packetflix
  0.9.7 a wrong PID, wrong start time, another live namespace identifier and a
  netns-only request **all captured**, which is why docs/CAPTURE.md no longer describes the
  `container=` identity as a stale-namespace check. A host-namespace launch returned
  200, then **409 after an unrelated container started** (a new veth), then 200 after
  it stopped: the identity hashed the whole interface list.
- Windows unit tests with the CI-style discover invocation: `test_capture` (22; four
  new: skipped rows, namespace merge preferring init, unrelated interface changes keep
  a selection valid, shared namespace listed once and launchable without aliases in the
  URL, unreadable rows counted), `test_check_install` (35; new capture check for
  disabled/enabled/failed/no-manager), `test_release_consistency`; all 58 JavaScript
  tests pass (three new capture-dialog tests plus the alias/loopback label test). The
  known Windows `state.enc` rename flake appeared once in `setUp` and passes on rerun.
- **Live verification of 1.20.1 on the same VM** after `start-manager.sh` rebuilt the
  manager: version 1.20.1 with the provider enabled; the host view lists the host
  namespace once as `systemd(1)` with `containerlab-node-manager-backup-ui-1` as its
  alias and merges the cEOS `CliShell(pid)` process rows into their node rows (the raw
  15 rows have exactly 5 distinct netns); a host launch returned **200, 200, 200**
  across an unrelated container start and stop; lab/node views are unchanged; forged
  and missing-interface selections still return 409; `check-install` reports
  **PASS 59 / FAIL 0 / WARN 1** with `[PASS] Optional packet capture` and its manual
  Wireshark item. In a real browser: the toolbar dialog shows "Choose a capture target
  above." with Prepare disabled, the host scope shows the alias labels, selecting
  `systemd(1)` keeps Prepare disabled until `ens33` is ticked, and Prepare then yields
  the `packetflix:` link with no console errors. The alias-label truncation ("+N more")
  landed after that browser run and is covered by the JavaScript test only.
- Found while redeploying: `setup-git.sh --list` (run as root by guided Git setup)
  imported `host_git.py` from the owner's source checkout and left a root-owned
  `__pycache__` there, so `rm -rf ~/projects/v1.20.1` failed as the owner.
  `git-registrations.py` and `check_install.module()` now set
  `sys.dont_write_bytecode`; the VM was cleaned with sudo once and the final commit
  redeployed from a fresh extract.
- Not exercised: the workstation cshargextcap plugin and SSH tunnel (Wireshark 4.6.8 is
  installed on the workstation but the plugin is not), VM-based NOS kinds, HTTPS/proxy
  Edgeshark deployments, and the `.env` copy path of `install.sh`.

# 1.20.0 — optional Wireshark capture (2026-09-12)

Prepared in the active workspace on `codex/wireshark-capture`, based on fetched
`origin/main` at `822cb33`, then synchronized with main `2b36478` (1.19.4)
after PRs #16 and #17 merged. Engineer access setup, topology file permissions,
installer/health checks and upstream live-validation records are retained.
The feature remains staged, with no source commit, push, image build or live
Wireshark deployment performed here.

## Verified locally

- After synchronizing with main `2b36478` (PRs #16 and #17), the full Python
  suite ran **469 tests, OK, 11 skipped**, in 239 seconds on Windows. No failures.
  This includes all **18 capture tests**, the engineer-access health and installer
  regressions, and the existing operations/backup/Git tests. The additional
  POSIX topology-permission regression is among the Windows skips.
- All upstream-only files were verified byte-for-byte against main. Host helpers
  match main exactly apart from their 1.20.0 release metadata. Feature-only files
  match the preserved pre-sync feature, and upstream validation history is retained.
- All **55 JavaScript tests passed** again after main synchronization, including
  nine capture UI regressions. Desktop/mobile browser checks below were also rerun.
- All seven release-consistency tests passed with the new setup page included.
  `deploy/verify-release.py` reports **1.20.0**.
- JavaScript syntax and `git diff --check` passed.
- Headless desktop Chrome used the real application UI and FastAPI server, with
  isolated temporary lab data and a synthetic Edgeshark provider. Checked a node,
  both link endpoint selection and interface preselection, two interfaces in one
  namespace, host-interface capture preparation, native URI generation, and the
  in-app setup page. No browser JavaScript errors.
- Inspected desktop and 390px mobile screenshots; verified dialog and page have
  no horizontal overflow, including the capture and topology action rows.
- Checked Siemens' discovery schema, Packetflix API and native launch code.
  Resolved and pinned public multi-architecture image manifest digests; both
  contain Linux amd64 and arm64 images. Provider response time/size bounds,
  redirect rejection, exact node matching, process restart/interface changes,
  malformed payloads, cross-origin requests and concurrent discovery limits are
  covered by the regression tests.

## Deployment checks still required

There is no Docker executable or installed WSL/Linux environment on this machine.
No manager image or optional-service containers were built/run locally. YAML
parsing is checked locally; actual `docker compose config` is added to Linux CI,
with no claim that the new CI job has run. No desktop Wireshark plugin was installed
or invoked, and no live packets, router NOS, host capture capabilities, SSH tunnel,
TLS proxy or Linux namespace lifecycle were tested. Browser checks prove capture
selection and handoff generation, not packet streaming.

Follow [docs/CAPTURE.md](../docs/CAPTURE.md) for installation, research sources, known
Linux/VM visibility limits, and the disposable-lab live acceptance procedure.
Prepared URLs include Packetflix namespace/process identity checks; processless
namespaces retain the upstream namespace-reuse limitation. The provider is
optional, has no manager socket/capability changes, and is disabled by default.

---

# Engineer access for VS Code and the Containerlab extension — 1.19.4

- Prepared on branch `claude/engineer-access` from the 1.19.3 branch tip `3d10cb4`
  (main `822cb33`). Source delivery; no Docker image is published.
- Adds `deploy/setup-engineer-access.sh`, the `start-manager.sh --refresh` re-apply,
  the installer question/phase 5/menu option 3, the `check_host._engineer` health
  check, and the `host_operations.py` create mode (0664 in a setgid parent, else
  0644). Lockstep metadata verifies as **1.19.4**; the new script is in the CI
  `bash -n` list.
- Windows unit tests with the CI-style discover invocation: `test_check_host` (16,
  four new: unconfigured INFO, configured PASS, each missing piece FAIL, unprivileged
  runs no commands), `test_install_manager` (16, one new: the engineer phase runs
  after manager verification only when chosen, with `--owner USER`),
  `test_lab_operations` (22; the POSIX file-mode test skips on Windows and runs in
  Linux CI), `test_check_install` (34), `test_release_consistency`,
  `test_helper_preflight`, `test_gateway_preflight` and `test_git_onboard` all pass.
- **Live dev-VM validation (Ubuntu 24.04.4, no `/dev/kvm`), applied by the author with
  the maintainer's passwordless sudo and read back afterwards:** before the change the
  VM reproduced both reported errors (no `clab_admins` group, `clabllm` in neither
  `docker` nor `clab_admins`, `/etc/containerlab` root:root 0755, containerlab 0755;
  `mkdir /etc/containerlab/vscode-test` denied). After
  `setup-engineer-access.sh --owner clabllm`, a fresh login showed both groups; the
  roots became `clab_admins 2775` and the existing lab file 664; `mkdir` and a new
  topology under `/etc/containerlab/vscode-test` succeeded as `clabllm`, inheriting
  `clab_admins 664`; `containerlab inspect --all` and `docker ps` worked without
  sudo (SUID `-rwsr-xr-x root root`). The still-running 1.19.3 manager browsed and
  read that engineer-created folder through the gateway. `start-manager.sh
  --enable-operations` then upgraded the VM to **1.19.4** (gateway verified for
  discovery, operations and Git at 1.19.4; container `clab-backup:1.19.4`), and its
  `--refresh` call restored `clab_admins 2775` on the projects root that
  `setup-operations.sh` had reset plus the SUID bit. Afterwards: Debug probe
  **browse PASS, capabilities PASS (1.19.4)**; `check-install` **PASS 58 / FAIL 0 /
  WARN 1 / INFO 5** including `[PASS] Engineer access for VS Code / Containerlab
  extension`; a topology **created by the manager** through the operations gateway
  (`preview` + `confirm`, job succeeded) landed as `root:clab_admins 664` and the
  engineer could edit it. Negative path: with the projects folder and SUID
  deliberately reset, `check-install` reported `[FAIL] Engineer access` naming both
  pieces with the `--refresh` fix, `--refresh` repaired them, and the report returned
  to PASS 58 / FAIL 0. The VS Code extension's own activation after killing its
  server was left to the maintainer and not observed by the author.

# V1.19.2 bug-fix report follow-up — 1.19.3

- Prepared from published main `0faae0b` (1.19.2) on branch
  `claude/v1.19.2-bug-fix-report`. Source delivery; no Docker image is published.
- **Live dev-VM validation (Ubuntu 24.04.4, x86_64, no `/dev/kvm`):** the branch was
  staged with `git archive`, `deploy/install-prerequisites.sh --docker --containerlab`
  installed Docker 29.8 / Compose v5.5.1 / containerlab 0.79.0, and the maintainer ran
  the interactive steps (`start-manager.sh --enable-operations` with the clab-discovery
  password, the browser VM connection, and `setup-git.sh` choosing a subfolder). The
  resulting state, read back without changing it: manager container `clab-backup:1.19.3`
  running; `/api/state` reports version 1.19.3, discovery configured and connected as
  `clab-discovery`, helper 1.19.3; the Debug probe reports **browse PASS and
  capabilities PASS** through the real SSH gateway (the path that returned 409 in the
  1.19.2 report); a two-node `arista_ceos` lab (`n24l/ceos:4.35.0F`, container-only)
  was **deployed through the operations gateway** (`deploy` succeeded, exit 0, then
  `inspect-all`), imported as Running with both nodes Ready; a NOS login test and a
  backup **succeeded on both nodes**; one Git registration carries the new
  subfolder prompt (label `CLAB-MNGR-DEV-LLM / ARISTA-LAB-TEST`, prefix
  `ARISTA-LAB-TEST`) and one Save progress is `synced` with a verified pushed commit;
  `bash deploy/check-install.sh` reports **PASS 57 / FAIL 0 / WARN 1 / INFO 5** on
  source 1.19.3, the WARN being the default 20-folder browse budget. The first-run VM
  connection dialog and the green setup banner were exercised by the maintainer and
  not directly observed by the author.
- Fixes: `diagnostics.failure_hint` now orders the gateway/account phrases before a
  tightened password rule, so the Debug panel no longer reports a reachable-account
  operations-gateway failure as an authentication/password problem;
  `lab_operations.operation_connection_error` and `check_install`'s topology-browser
  next step were reworded to match, and `check_install` gives a gateway-specific step
  when discovery is connected. The manager prompts for the VM connection once on first
  load when none is configured. Guided Git setup prompts for a per-lab repository
  subfolder (one repository, many labs) and ends with a success banner.
- Release metadata verifies as **1.19.3** (`python deploy/verify-release.py`), including
  the `app.js` footer fallback and every `?v=` asset in the five static HTML pages.
- Focused suites run on the Windows workstation with FastAPI/httpx/paramiko installed:
  `test_diagnostics` (9), `test_operations_ssh` (14), `test_lab_operations` (21, 1 skip),
  `test_check_install` (34, 1 skip), `test_check_host`, `test_git_onboard` (42),
  `test_git_registrations`, `test_gateway_preflight`, `test_helper_preflight`,
  `test_install_manager`, `test_check_git`, `test_apt_sources`, `test_apt_update`,
  `test_junos_kinds` and `test_release_consistency` all pass. The new/changed test
  methods were also run individually and pass.
- JavaScript: **46 tests pass** (`node --test tests/*.js`), including three new
  first-run VM-prompt tests; `node --check` passes for `app.js` and `management.js`.
- The full Windows unittest run (445 tests) shows the known, nondeterministic
  `PermissionError: [WinError 5]` on `os.replace(state.enc.tmp -> state.enc)` in
  `Store.atomic` during `setUp`; each affected test passes when rerun in isolation.
  This is a Windows open-handle rename limitation, not a product defect. Judge the
  suite by isolated reruns or by Linux CI.
- `bash -n` passes for all deploy scripts. VM-based NOS kinds (vJunos, XRv9k) were
  not exercised because the dev VM lacks nested virtualization; only the container
  cEOS kind was deployed and backed up.

# Integrated audit recovery fixes — 1.19.2

- Integrated the unmerged audit commit `8d87ea8` with current main `2c10037`
  (1.19.1) on `codex/deployment-operation-audit`. The local merge is resolved
  and staged for review; no new commit, push or GitHub merge was performed.
- Full combined Python suite: **443 tests ran, 433 passed and 10 skipped**
  in 244 seconds. All **43 JavaScript tests pass**. Skips cover Linux
  Ansible control-node behavior, controlling-terminal/process groups,
  symlink/openat checks and the opt-in EOS SSH fixture. No remote CI result is
  available for the uncommitted integration.
- Before integration, 16 focused audit tests against current main produced
  three passes, five failures, seven errors and one Linux-only skip. The failure
  paths cover topology overwrite, storage recovery, stuck lab/Git guards, audit
  logging, bounded Git stderr and cleanup after the Git parent exits. The
  previously failing regressions now pass as part of the combined suite.
- Retained main's SSH EOF implementations and added audit bounds/recovery without
  shortening its 60-second discovery deadline, helper inspect/label budgets,
  refresh wait or 90-second debug probes. Its authentication hints, terminal Git
  clone behavior, dependency bounds and LF normalization remain present.
- Real localhost SSH regressions from both branches pass, including delayed and
  fragmented output after exit status. Helper-timeout tests and diagnostics
  tests confirm the newer budgets are retained. Host-service/package probes use
  mocks; localhost Paramiko is not an Ubuntu OpenSSH installation test.
- Release metadata, including the app.js footer fallback, verifies as 1.19.2.
  Workflow YAML, Bash syntax for all ten deployment scripts, and Git whitespace
  checks pass. CI includes both branches' relevant SSH, timeout, Git recovery,
  operation, logging and browser regressions.
- No Docker build, fresh Ubuntu install, live VM helper call, device action or
  remote Git push was performed. The real Linux Git inherited-stdout timeout
  regression is skipped locally and included in CI. Full deployment validation
  remains outstanding; see the [audit report](../docs/archive/DEPLOYMENT-AUDIT.md).

# Transport EOF, helper timeouts and hygiene — 1.19.1

- Prepared from published main `2d34415` (1.19.0) on
  `claude/transport-eof-and-helper-timeouts`. No image build, fresh-VM run,
  live VM helper call or device validation was performed on this Windows host.
- Real localhost Paramiko regressions now cover discovery as they did
  operations: exit status before a delayed tail, exit status before a 160 KiB
  multipart tail, and nonzero status before a tail (six discovery SSH tests).
  Git transport tests replace the old `recv_ready` mock with an EOF-terminated
  stream, add a fragmented tail with early exit status, and assert a truncated
  envelope is never parsed (six tests). Both loops copy `lab_operations.remote`.
- Four helper timeout tests verify the 25 s inspect / 8 s label budget fits the
  60 s manager deadline, that an expired watchdog raises `TimeoutError`, that a
  completed inspect parses, and that the helper's stderr names the timeout.
  Diagnostics tests cover the new `failure_hint` classification of Paramiko
  "Authentication failed." and the 90 s probe budget.
- Full Python suite on Windows with Git and Node on PATH: 427 tests ran,
  424 passed, nine skipped (Linux Ansible control node, controlling terminal,
  openat symlink, opt-in EOS fixture). Three errors were the known Windows
  `os.replace` PermissionError on `state.enc` and each passes when rerun alone.
  Twenty-two real-repository host Git tests ran that previous Windows runs
  skipped for lack of git. JavaScript: 42 tests pass; `node --check` passes.
- `deploy/verify-release.py` reports 1.19.1 including the new `app.js` footer
  check; `bash -n` passes for every deploy script. ShellCheck was unavailable.
- Vendor collection ranges were read from the Galaxy API on 2026-09-11
  (netcommon 8.6.2, junos 11.1.1, iosxr 12.4.2, eos 12.2.0); an unconstrained
  build that day would resolve the same majors. A Docker build with the pinned
  ranges has not been run here.
- Line-ending normalization was committed separately with
  `git add --renormalize`; the change is content-neutral for every parser the
  files feed and must be reviewed as such.
- The OpenSSH ordering (exit-status request emitted before the remaining pipe
  data is drained) is modelled by the fixtures; the effect on the user's VM
  still needs a live discovery and Git save after upgrading image and helpers.

# Development debug panel and folder browsing — 1.19.0

- Prepared from merged main `a7a016b` (1.18.1) on
  `codex/development-debug-panel`. No commit, push, image publication or VM
  deployment was performed.
- Full Python suite: 416 tests ran, 407 passed and nine skipped. Skips cover
  Linux Ansible control-node behavior, controlling-terminal/process groups,
  symlink/openat checks and the opt-in EOS SSH fixture. The seven focused debug
  tests also pass, including a server-error test added after the full run.
- All 42 JavaScript tests pass (39 existing/operations tests plus three debug
  UI tests). Browser regression proves a listing renders while capabilities
  are still pending, survives their failure and retries folder expansion.
- Debug tests cover availability before setup, metadata bounds, secret/path
  exclusion, safe exception classification, same-origin rejection, simultaneous
  probe rejection, settings changes during checks, version mismatch, failed
  checks, safe text rendering, retry and JSON report generation.
- An isolated localhost browser fixture verified the debug page, readable
  narrow layout, separate browse PASS / capabilities FAIL results, and topology
  folder expansion while capability checks fail. No real VM was contacted.
  Report Blob contents and download naming passed the UI harness; the in-app
  browser did not emit a download event, so a saved workstation file was not
  independently confirmed.
- Release metadata, workflow YAML and Git whitespace checks pass. CI now runs
  debug API and browser regressions; this branch's remote CI has not run yet.
- Existing 1.18.1 SSH EOF handling is retained and its real localhost Paramiko
  tests pass. The identified browser dependency is a separate failure path;
  confirmation of the user's actual VM error still requires a live debug report.

# Operations helper and installation diagnostics — 1.18.1

- Prepared from merged main `7331e9a` (1.18.0) on `codex/operations-helper-fix`.
  Commit, push, publication and VM deployment remain pending.
- Reproduced the exact generic operations-helper error in two real localhost SSH
  tests before changing the client: exit status arriving before the final JSON
  result, including a fragmented 160 KiB response. Both pass with EOF-based reads.
  This establishes a transport defect; it does not prove the cause on the user's VM.
- All 14 real SSH regressions pass, including streamed output, fingerprint pinning,
  late output, nonzero/missing exit status, incomplete JSON, bounded stderr and
  controlled diagnostic messages without leaked stderr secrets.
- The 133-test application/health/installer regression run passed with two skips:
  131 passed; the Linux controlling-terminal regression and symlink creation test
  could not run on this Windows host. Host services and permission probes are
  mocked; the localhost SSH tests use Paramiko, not Ubuntu OpenSSH.
- The checker now retains its terminal/session for sudo's authentication timestamp,
  and tests the actual query runner before reporting administrator access PASS.
  This corrects the false-failure pattern in the user's 1.18.0 report. The root-run
  workaround is documented; the corrected live VM report is still outstanding.
- The delegated gateway suite adds 12 passing tests and two Linux-only process
  regressions skipped here: 147 tests selected overall, 143 passed and four skipped.
  It covers sudo denial, missing capabilities, invalid versions, timeout/overflow
  cleanup, failed pipe reads and unfinished readers without exposing helper output.
- The launcher additionally checks the restricted gateway and core capabilities
  before rebuilding. These are read-only preflight queries, not a lab deployment.
- Source metadata verifies as 1.18.1. ShellCheck, Python syntax, workflow YAML,
  documentation links/fences and Git whitespace checks passed. CI includes the
  SSH, operations and delegated gateway suites; this branch's CI has not run yet.
- No Docker image build, real fresh Ubuntu install, live gateway/sudo check or lab
  deployment was performed. The saved VM account and live deployment outcome still
  need verification on the user's VM. No existing labs or credentials were changed.

# Juniper vQFX and vJunos-switch — 1.18.0

- Prepared from merged main `712662f` (1.17.0) on `codex/junos-switch-kinds`.
  Commit, push, publication and VM deployment remain pending.
- 118 focused tests selected: 114 passed and four Linux-only checks skipped on
  this Windows host. Coverage includes 14 new Junos-kind tests plus application,
  discovery, VM import, downloads, Git progress, topology, release consistency
  and helper-preflight regressions.
- The new tests exercise canonical/legacy kind imports, generic Junos driver
  precedence and conflicting groups, saved-node sync with retained selection,
  credentials and manual endpoints, distinct credential defaults, generated
  Junos commands, `.set` captures, immutable download naming, Git manifest/byte
  preservation and SuperPuTTY usernames. Device and Git processes are mocked;
  temporary captured fixtures do not demonstrate a live NOS backup or push.
- Source release verification reports 1.18.0. Python syntax, workflow YAML,
  documentation links/fences and Git whitespace checks passed. CI now includes
  the Junos-kind suite with application test dependencies; that workflow has
  not yet run on GitHub for this branch.
- No Docker image build, live SSH/backup against either new NOS, or VM deployment
  was performed. Existing cJunos behavior and historical capture metadata are
  retained. Manager support does not remove Containerlab's documented restriction
  on deploying vJunos-switch inside another VM; this is covered in the VM guides.

# Installation health report — 1.17.0

- Prepared from merged main `7c25648` (1.16.1), retaining the pending WinSCP
  instruction updates. Commit, push and VM deployment remain pending.
- 163 focused tests passed: health report 32, host checks 12, Git checks 13,
  installer 15, APT clock/update 17, Git wizard 40, registrations 9, APT sources
  14, release consistency 7 and helper preflight 4. Host/service commands and
  HTTP were mocked; this is not evidence that the user's VM is healthy.
- Covered root-only helper success with failed restricted access, unavailable
  operations, real-folder request failures, empty inventories/folders, bounded
  traversal, stale or unsafe helpers, missing persistent storage/key, invalid
  state, version drift, Git owner/identity/staging/remote-read failures, omitted
  secrets and independent continued reporting. Watchdog regressions cover
  descendants holding stdout, privileged timeout wrapping and one HTTP deadline
  across connection and body reads.
- ShellCheck passed for check-install.sh, install.sh, install-prerequisites.sh,
  setup-git.sh and start-manager.sh. Source consistency reports 1.17.0; Python
  syntax, Markdown links/fences and Git whitespace checks passed. CI includes
  the new tests and shell launcher, but has not run on GitHub for this change.
- No packages, clocks, services, Git checkouts or lab configurations were changed
  on a VM. No Docker build, live SSH/SFTP login, device backup or real GitHub
  authorization/push was performed. The report distinguishes these remaining
  manual workflow tests from automated checks.

# Installer clock recovery — 1.16.1

- Prepared from merged GitHub main `58a17bd` (1.16.0); commit/push is pending.
- 105 focused tests passed: APT clock/update handling 17, installer 14, Git
  wizard 40, registrations 9, APT sources 14, release consistency 7 and helper
  preflight 4. System/package commands were mocked; no clock was changed.
- Covered the reported future Release date error, expired/stale metadata,
  synchronized/manual/unavailable clocks, bounded active-NTP waits using
  monotonic time, strict APT checks, streamed output and original failure codes.
  Git package setup stops before installation after a failed update.
- ShellCheck passed for install.sh, install-prerequisites.sh, setup-git.sh and
  start-manager.sh. Source consistency reports 1.16.1. Documentation adds
  pre-bootstrap clock checks and recovery within the original paused run.
- No live Ubuntu package installation, NTP recovery, Docker build or VM
  deployment was performed. The new CI test entry is prepared locally.

# Consolidated terminal installer — 1.16.0

- Prepared from local 1.15.3 commit e64790a; latest fetched main was 0658562.
- 88 focused tests passed: installer 14, Git wizard 40, read-only registrations 9,
  APT source handling 14, release consistency 7 and helper preflight 4.
- Covered step retry/cancel, real-owner environment, retained .env bytes, custom
  ports/IPv6 and version failures, registered checkout selection, custom binding
  preservation/rechecks, URL correction, login recovery, identity repair and
  exact APT backups that preserve network sources, disabled Docker repositories,
  and explicit local Docker targeting. Package/sudo commands were mocked.
- ShellCheck passed for install.sh, install-prerequisites.sh, setup-git.sh and
  start-manager.sh. Source verification reports 1.16.0. Git whitespace checks passed.
- CI now includes these stdlib regression tests and installer shell syntax checks;
  the updated workflow has not yet run on GitHub.
- No fresh Ubuntu install, live GitHub authorization, package installation,
  Docker build or VM deployment was performed here. Validate the complete path
  on a disposable Ubuntu 24.04 VM before treating it as a verified VM install.

# Git owner and identity guidance — 1.15.3

- Based on merged main 0658562. Guided setup accepts an existing checkout directly,
  repairs invalid identity, and retains valid settings and the owner's environment.
- 19 onboarding tests passed, including existing-checkout resume without cloning,
  blank input retry, invalid identity repair and preservation of valid identity.
  Seven release-consistency and four helper-preflight tests passed (30 total).
- ShellCheck passed for setup-git.sh and start-manager.sh. Source verification
  reports 1.15.3; Git whitespace checks passed.
- Shell registration still runs Git only after dropping to the owner. Failure
  guidance retains custom registration settings and provides absolute paths.
- No live Ubuntu registration, package installation, Docker build or deployment
  was performed. Changes are prepared locally for user commit and push.

# Guided Git setup recovery — 1.15.2

- Based on GitHub main 698fabb, preserving the latest user wiki edits.
- Reject GitHub branch/file page URLs before choosing a directory or authenticating;
  retain HTTPS repository URLs and nested namespaces on other Git hosts.
- Package-update failures stop before installation, with source-repair instructions;
  package-install errors report their own recovery step. System sources are not edited.
- Focused validation passed: 15 onboarding tests, seven release-consistency tests
  and four helper-preflight tests (26 total). Source verification reports 1.15.2;
  the Git whitespace check passed. These are local tests with mocked package commands.
- No live Ubuntu package installation, Docker build, VM upgrade or push was performed.

# Repository consistency repair — 1.15.1

- Audited current GitHub main b0389ba and reproduced its source/helper version
  mismatch. Corrected VERSION to match the existing 1.15.1 runtime components.
- Seven release-consistency tests and four helper-preflight tests passed. Cases
  include the stale VERSION file, each runtime metadata location, empty lab
  inventory, malformed responses, and version errors without credential leakage.
- Source consistency check, launcher ShellCheck and Git whitespace checks passed.
- New GitHub Actions workflow is prepared but has not run on GitHub. Docker build
  and fresh-VM launch have not been executed here. No remote push was performed.
- Existing runtime code is retained; the historical full-suite results below
  describe their original runs, not a new full-suite run for this cleanup.

# Git progress validation — 1.15.0

- Baseline: GitHub main 160fe5e. This cumulative source release includes the prior
  VM password and UI/diagram changes documented below.
- Full Python suite: 204 tests run, 198 passed, 6 platform/opt-in skips.
  Includes 20 host Git tests (real disposable repositories/bare remotes and mocked
  production dispatch), 19 coordinator tests, four bounded SSH transport tests,
  and five worker logging/persistence recovery tests. Existing backup, password,
  topology, file-transfer and lab-operation regressions also passed.
- Real Git cases cover exact artifact bytes, unrelated/staged work, foreign
  outgoing commits, no-op saves, baseline-only changes, checkpoint uniqueness,
  changed remotes, fast-forward updates/divergence, failed pushes, ancestor-save
  reconciliation, interrupted writes/commits and retries after owner repairs.
  A no-change save compares as empty; long and reserved device names export safely.
- Coordinator tests cover exact selected scope, incomplete captures, provenance,
  idempotency, review preferences, retry-without-push, lost replies, capture-ID
  persistence failure, restart recovery, pending-save guards and version ZIPs.
- JavaScript: 38 tests passed, including 14 Git workflow tests for payloads,
  escaped output, destination acknowledgement, historical target selection,
  request-ID reuse, double-click prevention and modal/polling behavior.
- Browser QA used an isolated local manager, synthetic device captures and real
  local Git checkouts/remotes. Checked repository selection, one-click save,
  diff/version viewing, ZIP download, checkpoint capture, failed push and retry,
  and baseline from an older capture. Verified retry created no new capture and
  baseline left latest untouched. No real VM/device/remote account was accessed.
- ShellCheck passed for setup-git.sh, start-manager.sh and clab-manager-gateway.
  Deploy shell files remain LF; Python source/embedded setup code compile.
- The source ZIP and cumulative patch are verified against clean 160fe5e. The
  package excludes preview state, environments, real captures and credentials.
- Linux sudo/UID transitions, the owner's noninteractive HTTPS credential helper,
  Docker image build and real NOS captures still require deployment validation.
  Mocked privilege-order checks do not establish live Linux permission behavior.
  No GitHub push, registry publication or deployment was performed. Load version
  retrieves files; applying configurations to live devices remains unavailable.

# UI and diagram validation — 1.14.0

- Baseline: GitHub main 160fe5e; includes the 1.13.0 VM password changes below.
- Full Python suite: 156 tests run, 150 passed, six platform/opt-in skips.
  New tests cover saved annotation persistence/restart, unchanged wiring/no VM writes,
  unsaved export, XML escaping, JSON style round-trip, invalid input, stale-map
  conflicts and rollback after failed saves.
- JavaScript: 24 tests passed. New geometry/payload tests cover line movement,
  coordinate limits, node identity and revision retention.
- Browser checks used an isolated local 1.14.0 fixture without a VM connection:
  sidebar labels/order, release caption, default Topology view, Credentials dropdown,
  equal 12px tab text, Deploy New Lab wording, text/box editing, saved/reopened edits,
  Undo and discard confirmation. Input events update the canvas before Save.
- Inspection dialog checked at a 1280px viewport: width about 1242px; full long
  topology path wraps and no table cell truncates its text.
- Master wiki updated from the user-supplied document. Proxmox/Ubuntu sections
  retained; old VM client-key procedures replaced with setup, encrypted persistence,
  one-time migration and password recovery. Source builds are the default.
- Source ZIP and cumulative patch checked against clean 160fe5e; Linux scripts
  remain LF. Generated artifacts exclude preview data and email attachments.
- No Linux VM installation, Docker build, live-device test, registry publication,
  GitHub push or deployment was performed. Those deployment checks remain as
  described in the password validation below.

# VM password validation — 1.13.0

- Baseline: fresh clone of GitHub origin/main at 160fe5e (V1.12.1 bug fixs).
  Work is isolated in branch codex/vm-password; previous local checkouts preserved.
- Full Python suite: 151 tests run, 145 passed, six platform/opt-in skips. Includes
  synthetic local SSH transport for discovery, SFTP and structured operations.
- New tests cover key-to-password migration, fingerprint retention, encrypted
  persistence/restart, password rotation and blank preservation, rejection of key
  fields, no credential leakage, and effective SSH policy conflict detection.
- JavaScript: 22 tests passed, including new password form and migration behavior.
  Node syntax check passed for management.js.
- ShellCheck 0.11.0: no findings for setup-discovery.sh, setup-password.sh,
  setup-operations.sh, start-manager.sh and the shared gateway.
- Browser: inspected the real local 1.13.0 app with isolated data, confirmed the
  masked/required password field, default account, absence of client-key controls,
  dialog layout and rendered password setup/recovery guide.
- Whitespace check passed with cr-at-eol for the repository's tracked CRLF files;
  Linux scripts remain LF and are protected by .gitattributes.
- No Linux VM/systemd/passwd/sshd installation, Docker image build, live NOS test,
  registry publication or GitHub push was performed. Deployment validation should
  cover a fresh account, existing key migration, cancelled password prompt, restart,
  password reset, rejected client keys/shell/forwarding and unchanged admin login.

# UI refinement validation — 1.12.1

- Python regression run: 145 tests; six platform/environment skips. The only
  initial failure was the previous version assertion, updated to 1.12.1 and rerun.
- New coverage: topology filtering before the 500-entry limit, quick-action state
  guards and deploy/start selection, and no automatic topology dialog on entry.
- Browser fixture: same-tab Deploy New Lab landing page, explicit Lab Topologies
  opening, filtering old-helper mixed results, topology Deploy lab confirmation,
  cancellation, return navigation, and status-panel Destroy confirmation. No
  browser console errors were reported during the check.
- Synthetic SSH/operation fixtures only; no live NOS commands or Docker build.
- Git fetch was unavailable because the local Git remote-https helper is missing.
  Existing local source was preserved; no push or registry publication occurred.

# Validation — Containerlab Node Manager 1.12.0 (2026-09-10)

## Current release

- Python: 144 tests completed, 138 passed and 6 existing platform/opt-in skips.
  The suite includes discovery/import, persistence, backups, terminal tickets,
  scoped host operations, source deletion and current removed-action rejection.
- JavaScript: all 17 regression tests passed. All application scripts pass Node
  syntax checks. Inspection tests cover flat/grouped JSON, surrounding CLI logs,
  IPv4/IPv6, health/image fields, malformed output and escaped untrusted values.
- Start fresh tests verify explicit confirmation, busy backup/operation/SSH/
  discovery guards, retained VM credentials/fingerprint/encryption key, deletion
  of backup files/history/exclusions, cache invalidation and retention of unknown
  files. Interrupted state commits and staged cleanup failures resume correctly.
- Draw.io tests verify the supplied fixture's annotation text, node coordinates,
  containment-relative coordinates, unique cell IDs, endpoint labels, source/target
  references, escaped XML and unsupported-layout rejection. Exporting unsaved
  node positions leaves the saved layout unchanged. The full diagrams.net desktop
  editor was not launched; pixel-identical rendering is not claimed.
- Browser checks on isolated loopback SSH fixtures: automatic page load without
  login; retained VM settings and guide link; simplified lab action menu; interactive
  editor/full export; inspect review and 12-node result table; expanded topology
  bulk backup review; node right-click SSH/backup menu; exclusion clearing; lazy
  vertical project tree and read-only YAML. Start fresh cleared preview storage,
  preserved VM connection and returned the deployment to Ready to import with
  confirmation still required. No real VM or device commands were run.
- Fetched origin/main 7c5cef6 exactly matches the previous delivered 1.11.0 source.
  Release ZIP and patches are verified against that revision, the previous source
  ZIP and original baseline 06b8624. Shell files retain LF line endings.
- This Windows environment cannot build/run the Linux Docker image or install
  privileged helpers on a Containerlab VM. Actual image build, sudo/helper setup,
  Containerlab lifecycle commands and live NOS connectivity remain VM validation.
  Use the documented start-manager command to update helpers and image together.

## Historical release evidence

# Validation — Containerlab Node Manager 1.11.0 (2026-09-10)



## 1.11.0 evidence



- Full Python suite: 136 tests, 130 passed, 6 skipped for unavailable platform

  capabilities. Existing map, persistence, import confirmation, discovery, backup,

  SSH and removal checks remain included.

- All 14 JavaScript regression tests pass; new operations/workspace scripts pass

  Node syntax checks. Browser checks cover the new interactive flows.

- Host operation tests exercise exact scoped argv, feature detection, redeploy

  fallback order, unsupported flags/actions, path traversal, changed source/state/

  options, file creation, write/delete recovery, active-lab deletion refusal,

  optional cloning/sharing/fcli constraints, output bounds and secret redaction.

- Real subprocess tests verify stderr cannot corrupt inspection JSON and a

  disconnected streaming consumer terminates the child process.

- Real loopback Paramiko tests verify structured stdin, literal forced command,

  fragmented NDJSON output, failed exit/error handling and fingerprint mismatch.

- Authenticated API tests cover cancel, single-use/expired/revision-bound reviews,

  backup/operation conflicts, disk-save failure, output persistence and restart

  interruption, YAML diffs/name overrides, favorites/layouts and XML parsing.

  GoTTY JSON-port and HOST_IP output formats are covered; fcli reads the current

  VM management network and rejects incompatible saved labs.

- Browser fixture uses the supplied BGP topology with sanitized annotations and

  twelve nodes. Verified lab header and sidebar right-click menus, cleanup review

  cancellation, inspect confirmation/live output/success, YAML diff/cancel,

  drag-and-save layout, project browser, popular catalog selection, clone details,

  GoTTY port entry, and the new-tab SSH launcher with correct node-specific links.

  No browser console errors observed. No real VM/device commands were run.

  Screenshot: dist/lab-actions-1.11.0.png.

- Latest fetched origin/main b20468e matches delivered 1.10.0 source except the

  three ignore files. Source ZIP and patches target that commit, previous 1.10.0

  delivery and original baseline 06b8624; packaging checks reconstruct the source.

- Windows has no Docker/Containerlab/Linux host service here. Actual root helper

  installation, flock/process-group behavior, Docker image build, lifecycle

  operations and external SSHX/GoTTY/fcli services require a disposable Linux lab.

  These are not claimed as live deployment validation.



## Earlier release evidence



# Validation — Containerlab Node Manager 1.10.0 (2026-09-10)



## 1.10.0 evidence



- Full Python suite: **113 tests, 108 passed, 5 skipped**. Existing platform/opt-in

  skips remain. JavaScript regressions: **14 passed**; management script syntax checked.

- Eight confirmation tests cover background polling/preview without saving, cancel

  semantics, explicit token requirement, single save, changed files/VM, expiry,

  retained exclusions on cancel, old-client bypass rejection, disk-failure rollback

  and retry, offline/cross-name rejection, and authentication. Existing file-import

  regression fixtures now explicitly confirm before expecting a saved workspace.

- Two subprocess preflight tests exercise deploy/verify-helper.py with valid current

  envelopes (including zero labs), old helpers and malformed bundles. Only controlled

  version/status text is printed, never source contents or credentials.

- Browser on synthetic local SSH fixture: 12-node lab appeared Ready to import.

  Preview showed 12 nodes, 16 links and four exact source paths. Cancel followed by

  Refresh discovery left no saved workspace. Reopening and choosing Import lab saved

  the lab, inventory credentials and map; status was Running. No browser console errors.

  Screenshot: import-confirmation-1.10.0.png. No live device actions performed.

- New host-side start-manager.sh updates/installs the helper, verifies the expected

  version/file protocol before recreation, prepares persistent storage, builds and

  starts Compose. Existing key retained; existing account plus supplied key is

  rejected to prevent accidental rotation. Another running data-sharing manager is

  rejected. Scripts kept LF for Linux.

- Latest fetched origin/main 0c0182c matches the 1.9.1 source delivery except three

  ignore/attributes files restored here. ZIP and patches are verified against that

  revision, previous 1.9.1 delivery and original baseline 06b8624.

- No Linux shell, Docker engine or live VM was available here. Privileged setup,

  shell execution, actual image build/recreation and real deployment connectivity

  remain VM checks; preflight parser tests do not establish full installer success.

  No GitHub push or user-VM deployment was performed.



## Earlier 1.9.1 evidence (retained for context)



## 1.9.1 evidence



- Full Python suite: **103 tests, 98 passed, 5 skipped**. Existing platform/opt-in

  skips remain. New coverage includes missing Docker labels, standard generated

  folder lookup, grouped inspect output, absolute labPath, permission errors,

  sanitized diagnostics, automatic-import retry and old-helper upgrade feedback.

- Real local Paramiko server tests exercised direct inspection plus SFTP on the

  same authenticated connection: original YAML and generated inventory read,

  permission-denied definition, and unavailable SFTP. Discovery survives file

  failures and no unrelated files are opened.

- New imports retain valid YAML when optional exports/inventory are mismatched;

  tests verify foreign credentials are discarded. Existing explicit sync remains

  atomic and preserves the saved workspace on invalid optional files.

- JavaScript regressions: **14 passed**. Production script syntax checked.

- Browser: synthetic SSH helper using the production collector, with the screenshot's

  `/etc/containerlab/<name>/clab-<name>/` layout and a sanitized 12-node BGP fixture.

  Denied YAML access produced a detected lab; clicking it attempted automatic

  import and then opened the manual form with a retry button. File details showed

  the exact denied YAML path and three found companion files. Restoring fixture

  access and clicking retry imported 12 nodes, inventory credentials and 16 map

  links with zero unmatched nodes. No files were uploaded through the form.

  General Import a lab offered the detected name and automatic retry. Right-click

  PE1 showed SSH, backup and details. No browser console errors were observed.

  Screenshot: auto-import-1.9.1.png. No live NOS actions were invoked.

- GitHub origin/main at d84c76b matches delivered 1.9.0 except the three missing

  ignore/attributes files restored here. Source ZIP and patches are verified against

  that commit, the 1.9.0 delivery, and baseline 06b8624.

- This upgrade changes the installed VM helper; --update-helper retains the current

  account and authorized key. Docker image label and static asset versions are 1.9.1.

- Docker builds, privileged Linux provisioning, Linux openat protections and access

  to the user's actual VM remain untested here. No GitHub push or VM deployment.



## Earlier 1.9.0 evidence (retained for context)



## 1.9.0 evidence



- Full Python suite: 94 tests, 89 passed, 5 existing platform/integration skips.

  Eight new removal tests verify scoped state/history removal, retained backup

  files and other labs/host credentials, absence of remote command calls,

  persistent exclusions across restarts, explicit reimport, immediate rediscovery,

  removal during an in-flight poll, active-job and stale-name guards, failed-save

  rollback, authentication, and manual import clearing a matching exclusion.

- JavaScript regressions: 14 passed. All application JavaScript syntax checked.

- Browser with synthetic local data: Cancel retains the workspace; default removal

  leaves an excluded sidebar entry, and refreshing discovery does not recreate it.

  Import again creates a new 13-node Running workspace. Removing with exclusion

  unchecked and refreshing discovery also imports a fresh workspace successfully.

  No browser console errors were observed. Screenshot: remove-lab-1.9.0.png.

- Removal has no remote side effects and performs no filesystem deletion. Saved

  backup files and shared audit logs remain on disk; prior history entries and

  credential profiles are not restored when a new workspace is imported.

- Latest fetched GitHub commit 63ca6d6 contains the 1.8.0 delivery except for the

  three ignore/attributes files restored here. Source ZIP and patches verified

  against that commit, prior 1.8.0 delivery, and original 06b8624 baseline.

- No helper/key change is required from 1.8.0. Docker/Linux deployment remains

  untested here; no changes were pushed to GitHub or deployed to the user's VM.



## Earlier 1.8.0 validation (retained for context)



## 1.8.0 evidence



- Full Python suite: 86 tests, 81 passed, 5 skipped. Added 18 VM-file tests:

  automatic import; encrypted persistence and public/log secret exclusion;

  explicit sync preserving manual endpoints, credentials, profiles, identity,

  schedules and history; pending annotation changes; bad/mismatched/missing files;

  removed deployments; old helper compatibility; authentication/offline rejection;

  custom inventory ports; saved display-name map binding; real loopback SSH file

  transport; helper paths, custom generated directories, digests and size budgets.

- The additional skip is the helper's Linux openat/O_NOFOLLOW symlink test. The

  original four platform/integration skips remain as documented below.

- JavaScript regressions: 14 passed. Application JavaScript syntax checked.

- Browser: the production app received all four files over a local Paramiko SSH

  fixture, automatically created the 13-node BGP workspace, imported credentials

  and rendered 16 links with zero unmatched nodes. A changed annotation produced

  Updates available while retaining the map. Clicking Sync from VM changed the

  saved/rendered coordinate from x=320 to x=360 and returned Up to date. Restored

  original fixture geometry afterward. Right-click node actions remain available.

- Updated the restricted helper installation and added a key-preserving upgrade.

  Added docs/archive/FRESH-VM-GUIDE.md covering clean Ubuntu installation through deployment,

  connectivity, keys, persistence, first lab, backups and upgrades.

- Verified complete source archive and patches against Git baseline 06b8624 and

  the previously delivered 1.7.0 source archive, and GitHub commit 4742a90. The

  fetched GitHub 1.7.0 source matches that delivery except for three absent ignore/

  attributes files, restored here. No live state/keys included.



No Docker engine, Linux VM or WSL distribution is available in this workspace.

Docker image build, privileged installation, sudoers/SSH restrictions, Linux

openat protections and real vendor-node operations remain VM deployment checks.

The helper's portable file-collection branch was tested with temporary directories;

that is not evidence that Linux provisioning has run successfully.

No code was pushed to GitHub or deployed to the user's VM.



## Earlier 1.7.0 evidence (retained for context)



Repository: ArchRuger/CLAB-BACKUP-WORKER-v2. Git baseline: 06b8624 (1.6.0 upload).

This release includes the previously delivered 1.6.1 map corrections. No changes

were pushed to GitHub or deployed to the user's VM.



## Automated evidence



- Across the full suite and focused reruns: 68 Python tests covered, 64 passed,

  4 skipped. Discovery coverage includes 21 passing tests, three of which use

  real loopback SSH. Existing JavaScript behavior tests: 14 passed.

- All application JavaScript syntax checks passed.

- Compose YAML structure checked for host networking, persistent bind mount,

  create_host_path=false, and absence of Docker port publishing.

- CRLF-aware git diff whitespace check passed. Linux shell scripts retain LF endings.

- Full source ZIP and patches verified during packaging against the v2 baseline

  and the delivered 1.6.1 source ZIP, ignoring checkout line-ending differences.



Four existing skips: two Ansible control-node integrations require Linux; one

symlink check requires Windows privileges; one EOS fixture requires the opt-in

Ansible collections environment. No additional tests were skipped for discovery.



New coverage includes registration from YAML, default kinds and prefixes, exact

node matching, multiple active labs, discovery without registration, empty and

malformed inspect output, IPv6 addresses, partial/stopped/missing/stale conditions,

credential exclusion/encryption, restart invalidation, manual endpoint retention,

reimport identity/history preservation, renamed deployment linking, stale in-flight

result rejection, unavailable node-action blocking, and scheduled-backup resumption.



Three tests run a real Paramiko server on loopback: the fixed inspect command and

JSON response, rejection of a nonzero remote exit even with plausible JSON, and a

changed SSH fingerprint blocking command execution. Other tests simulate inspection

results. No live lab devices or actual host containerlab instance were contacted.



## Browser verification



Ran the production FastAPI app with disposable local state and a loopback SSH

server returning synthetic inspect JSON. The map uses sanitized copies of the

user's actual annotation/wiring geometry.



- Saved VM password credentials through the UI and tested discovery over SSH.

- Retested the same account with blank credential fields; retained credentials

  worked and the UI reported "VM connected. Lab discovery is active."

- Confirmed Running for the 13-node lab and Not deployed for a second saved lab.

- Confirmed a discovered but unregistered lab offers setup.

- Inspected the YAML/annotation import dialog and legacy inventory alternative;

  multipart YAML import/reimport behavior is covered through the real API tests.

- Saved a deployment link from the browser.

- Set PE1's address/port to a manual endpoint, refreshed discovery, and verified

  the override remained unchanged.

- Verified the existing topology view still shows 13 nodes, 16 links, zero unmatched.

- Adjusted sidebar scrolling so saved labs and discovery controls remain accessible.

- Captured the final standalone workspace screenshot in the release artifacts.



## Deployment limits



No Docker engine or Linux/WSL execution environment is available here. The image

was not built, host networking was not exercised on Linux, and privileged VM setup,

sudoers installation and migration scripts were not executed. Script contents and

Compose structure were reviewed; Linux provisioning is the remaining deployment

validation. No real NOS backup, SuperPuTTY import, or live host discovery was run.



Follow docs/STANDALONE-SETUP.md for a deployment test: preserve existing data, start one

standalone manager, configure the restricted account, import an edited lab YAML,

verify discovery through lab stop/redeploy, and test a real node SSH/backup. Verify

history and keys before removing the old worker. Discovery reports container state;

it does not prove that a virtual NOS has finished booting.



The source archive excludes raw uploads, preview state, tokens, private keys,

configuration captures, virtual environments and .build/. Only sanitized geometry

regression fixtures are included. Original uploaded YAML is encrypted at runtime

and omitted from public API responses.
