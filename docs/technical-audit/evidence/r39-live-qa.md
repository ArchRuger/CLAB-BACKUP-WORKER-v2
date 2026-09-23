# Release 1.30.39 live QA — telemetry and Grafana retirement

Independent live acceptance check, run as the sole operator of the manager at `http://127.0.0.1:8081`
(commit `73c6712`, `/api/state` reports `1.30.39`) and the lab `restore-square`
(`174386ec12ee496190c585c5796b2662`, cEOS + cJunosEvolved + vJunos-switch + XRv9k + host1, all
`nos_login` ready). Tooling: `docs/technical-audit/tools/check_release_1_30_39.py` (Playwright +
`httpx`/`urllib`, real browser, real API, real device sessions — never a fixture, never disposable
data). Full JSON report: `r39-live-qa.json`. Screenshots: the six PNGs in this folder.

Overall: **142 PASS / 0 FAIL / 3 INFO** across 145 recorded checks. Zero unhandled console errors,
zero page errors, and zero request URLs containing `/telemetry` other than `/telemetry-retired`,
across the whole run (browser `page.on('request')` log). Two script bugs were found and fixed while
running this check (a wrong JSON key, and an active-state omission in a poll loop); both are called
out below with the corrected, independently-verified evidence — nothing is claimed that was not
actually observed.

## A. Absence and presence, at 1920×1080, 1366×768 and 390×844

Every row below ran once per viewport (three runs; all three agreed).

| Check | Result | Evidence |
|---|---|---|
| No `#menu-telemetry`, `#grafana-open`, `#tools-telemetry-settings`, `#telemetry-line`, `#grafana-caption` anywhere in the DOM (checked on My labs, Topology, Devices, Progress, Tools, the open Lab actions ▾ menu + Advanced options group, the open Manager ▾ menu) | PASS ×3 | empty match list every time |
| No `#i-telemetry` symbol/element anywhere | PASS ×3 | `false` every time; confirmed by source read: no `<symbol id="i-telemetry">` in `index.html`'s sprite at all |
| No text "Telemetry settings", "Open lab map", "Open network dashboard" or "Grafana" in `document.body.innerText`, on every screen above | PASS ×3 | empty match list every time |
| `/static/grafana.html`, `/static/grafana.js` → 404; `/api/telemetry/health`, `/api/telemetry/metrics`, `/api/telemetry/grafana`, `/api/labs/<id>/telemetry` → 404 | PASS ×3 | `{'/static/grafana.html': 404, '/static/grafana.js': 404, '/api/telemetry/health': 404, '/api/telemetry/metrics': 404, '/api/telemetry/grafana': 404, '/api/labs/.../telemetry': 404}` |
| No request URL contains `/telemetry` except `/telemetry-retired`, across the whole run | PASS | GLOBAL check at the end of the run; `telemetry_requests_seen: []` in the JSON |
| Console errors / page errors | PASS (0 / 0) | GLOBAL checks; `console_errors: 0`, `page_errors: 0` in the JSON |
| Lab actions ▾ retained: Start lab, Stop devices, Restart devices, Redeploy lab…, Destroy lab…, Remove from this manager… all present | PASS ×3 | `lab-start`, `menu-destroy`, `menu-remove-lab`, `stop`/`restart`/`redeploy` (`data-op-action`) all `present: true` |
| Advanced options present: Import map…, Edit map, **Retired telemetry configuration…**, Operation history… | PASS ×3 | all four `present: true`. `#menu-telemetry-retired`'s own `hidden` state is conditional (visible while a retired-telemetry record exists, hidden once none does) — its visible→hidden **transition** is the one actually exercised, live, in section B, not here (this section always runs after B mutated the lab, so it correctly observed the post-removal, hidden state) |
| Manager ▾ menu has no telemetry/Grafana wording | PASS ×3 | menu text dump contains only VM connection…, Refresh lab list, Deploy a new lab…, Import lab files…, Import an Ansible inventory…, Labs found on the VM…, Running labs on the VM…, Operation history…, Manager settings…, Diagnostics |
| Tools cards *Packet capture* (`#capture-open`) and *Configuration backups* (`#backup`) present and enabled | PASS ×3 | both `present: true, disabled: false` |
| *Open all CLIs* (`#tools-ssh-all`) present and enabled | PASS ×3 | `present: true, disabled: false` |
| *Test logins* present on both the Topology rail (`#rail-test-logins`) and Devices tab (`#devices-test-logins`), same tooltip on both | PASS ×3 | tooltip: "Tests the SSH login of every device again. A successful test makes Open CLI available." |
| *Edit map* (`#map-edit`) present on the Topology tab map toolbar | PASS ×3 | `present: true, disabled: false` |
| Progress tab *Save progress* (`#progress-save`) present | PASS ×3 | `present: true, disabled: false`, title "Save every device's configuration to CLAB-MNGR-DEV-LLM › restore-square/qa-1-30-37 › latest/ · main" |

Screenshots: `r39-A-1920x1080-tools-view.png` (Tools tab, desktop), `r39-A-390x844-tools-view.png`
(Tools tab, phone width) — both show *Packet capture* and *Configuration backups* only, no telemetry
or Grafana surface.

## B. Migration notice and device-line removal (the one mutating step; ran once)

| Check | Result | Evidence |
|---|---|---|
| Banner text matches exactly | PASS | `Configuration lines added by the retired telemetry feature are still on: cjunosevolved.` |
| Banner *Review and remove…* (`#banner-retired-review`) visible | PASS | `reviewVisible: True` |
| Advanced options › *Retired telemetry configuration…* visible before removal | PASS | `present: True, hidden: False` |
| Dialog title | PASS | "Retired telemetry configuration" |
| Device row names `cjunosevolved` with kind badge "Junos" | PASS | `cjunosevolved Junos` |
| Device row shows the exact retired line | PASS | `set system services extension-service request-response grpc clear-text port 32767` |
| *Remove from devices* (`#op-retired-remove`) enabled | PASS | `removeEnabled: True` |
| Results area filled within 150 s | PASS | filled in ~2 s |
| **Removal result text** | PASS, matches exactly | `cjunosevolved: removed — Removed the lines the manager had added and read the device back: they are gone.` |
| Notification (toast) text | PASS | `Removed telemetry configuration on 1 of 1 device.` |
| `/api/state` lab has no `telemetry_retired` key afterward | PASS | key absent from the lab document |
| `GET /api/labs/<id>/telemetry-retired` → 404 afterward | PASS | 404 |
| Banner gone after the next render | PASS | `hidden: True` |
| `#menu-telemetry-retired` hidden again | PASS | `hidden: True` |
| `/api/logs` shows `telemetry.retired.removed` for the node, no configuration text in the message | PASS (after a script fix) | see note below |
| Lab not left busy: `POST ssh-check-all {}` starts (200) right after | PASS | `{'started': 5, 'skipped': [], 'at': '2026-09-23T11:23:09Z'}` |

Screenshots: `r39-B-retired-dialog-open.png` (dialog open, line shown, Remove enabled),
`r39-B-retired-dialog-results.png` (result row + toast, both matching text above).

**Script bug found and fixed:** the log check first read `logs.get('logs', [])`; the real response
key is `events`, so it wrongly reported FAIL. Fixed in the tool
(`logs.get('events', [])`); the corrected read was verified with a one-off query against the same,
real `/api/logs` response (this section is the one deliberate mutating step and was not re-run to
avoid a second, needless removal-and-nothing-to-remove cycle):
```
{'time': '2026-09-23T11:23:03.654113+00:00', 'action': 'telemetry.retired.removed',
 'message': 'Removed the lines the manager had added and read the device back: they are gone.',
 'node': 'clab-restore-square-cjunosevolved'}
```
No configuration text (no `grpc`, no `set system services…`) appears in the message.

## C. Retained workflows (after B)

### C.1 Backups

| Check | Result | Evidence |
|---|---|---|
| `POST /jobs {operation: backup}` accepted | PASS | job `queued` → `succeeded` |
| Job reaches a final status within 60 s | PASS | `4/4 NOS sessions completed successfully` |
| Every non-host1 node `succeeded` | PASS | ceos, cjunosevolved, vjunos-switch, xrv9k all `succeeded` |
| host1 excluded from the backup job (by design) | PASS | not present among the job's nodes |
| ZIP download succeeds and lists members | PASS | `CEOS_ceos_...UTC.conf`, `cjunosevo_cjunosevolved_...UTC.cfg`, `vJunos-switch_vjunos-switch_...UTC.cfg`, `IOS-XR_xrv9k_...UTC.txt`, `manifest.json` |
| ZIP contains `manifest.json` | PASS | present |
| Per-device extensions vs. NODE-FEATURES.md "Backup download names" | INFO (informational) | `.conf` (CEOS), `.cfg` (cjunosevo/Junos), `.txt` (IOS-XR) — matches the documented contract exactly (CEOS→`.conf`, cjunosevo/vJunos-switch/vQFX→`.cfg`, IOS-XR→`.txt`) |

### C.2 Test logins

| Check | Result | Evidence |
|---|---|---|
| `ssh-check-all` → `started: 5, skipped: []` | PASS | `{'started': 5, 'skipped': [], 'at': '...'}` |
| Every node's `nos_login.at` advances | PASS | all 5 nodes' timestamps advanced |

### C.3 Terminal

| Check | Result | Evidence |
|---|---|---|
| `terminal.html#lab=<id>&node=clab-restore-square-ceos&label=restore-square` reaches a `>`/`#` prompt within 30 s | PASS | `Last login: ... \nceos> ` |

Screenshot: `r39-C3-terminal-terminal-ceos.png` (Connected, `ceos>` prompt visible).

### C.4 Save progress

| Check | Result | Evidence |
|---|---|---|
| Review dialog appears before upload (mandatory review) | PASS on the first save this session (real diff); the repeat save later in the run correctly reported `unchanged` (no dialog needed) — both are valid, documented outcomes | see below |
| Save job reaches a final status | PASS | first save: `synced`; second (repeat) save: `unchanged` |
| **Destination and commit id** | PASS | destination `CLAB-MNGR-DEV-LLM › restore-square/qa-1-30-37 › latest` (branch `main`), **commit `a46b956915bcfb3d745581b4c41046fd2de52da0`**, label "Technical audit 1.30.39 live check" |

**Remote verification (independent, read-only Git on the registered checkout):**
```
$ git -C ~/labs/CLAB-MNGR-DEV-LLM fetch origin
   73c8112..a46b956  main       -> origin/main
$ git -C ~/labs/CLAB-MNGR-DEV-LLM log --oneline -3 origin/main
a46b956 Technical audit 1.30.39 live check
795edb2 Configuration B
f12421e Configuration A
$ git ls-tree -r origin/main --name-only | grep manifest.json
restore-square/qa-1-30-37/latest/manifest.json
```
The commit's own diff (`git show origin/main --stat`) touches `cjunosevolved.cfg`/`.jcfg`,
`vjunos-switch.cfg`/`.jcfg`, `xrv9k.cfg`/`.xrcfg` and `manifest.json`. Beyond the telemetry line's
removal, the diff also includes interface-description/prefix-list/static-route changes: these are
real drift from an unrelated restore ("Configuration replaced") recorded **8 hours before this
session** (visible in the Progress tab screenshot taken during section A: "Last configuration change:
Configuration replaced · 8 hours ago") for which no Save progress had run yet — not something this QA
session caused.

**Script bug found and fixed:** the poll loop waited for `status not in ('queued', 'running',
'review_pending', 'push_pending', 'export_pending')`, but the real active-state set
(`git-progress.js` `gitActiveStates`) is `{queued, capturing, exporting, pushing}` — `pushing` was
never excluded so the poll stopped one step early and mis-recorded a FAIL while the job was still
`pushing`. Fixed in the tool. The job's real final state (`GET /api/git/jobs/<id>`, re-fetched 3 s
later) was `synced`, `pushed: true`, matching the commit above — independently re-verified, not
assumed.

### C.5 Packet capture

| Check | Result | Evidence |
|---|---|---|
| Capture target list includes ceos | PASS | `clab-restore-square-ceos · 18 interfaces` |
| `eth1` (the ceos↔cjunosevolved link) selected | PASS | matches the topology's `capture_interface` mapping for that link |
| Capture session started | PASS | `/static/capture-session.html#<64-hex>` |
| `/api/capture/sessions` lists the session | PASS (after a script fix) | see note below |
| Session page renders the noVNC canvas, connects | PASS | status text "Connected to Wireshark on the VM." |
| Traffic generated: `show ip interface brief` then `ping 10.0.12.1` from ceos's own terminal | PASS | Ethernet1 `10.0.12.0/31` found; pinged the /31 neighbour `10.0.12.1` (cjunosevolved's `et-0/0/0`, confirmed against the C.4 diff); **5 packets transmitted, 5 received, 0% packet loss** |
| End session via the session page's own *End session* button | PASS | "Session ended. Its capture files were removed from the VM." |
| Session gone from `/api/capture/sessions` after ending | PASS | `{'sessions': []}` |
| Packet-count evidence | INFO — no such API field exists (checked in `app/capture_service.py Sessions.public()`: `id`/`name`/`interfaces`/`remaining_seconds`/`idle_seconds` only), but the real Wireshark GUI's own counter is visible in the screenshot | see below |

**Script bug found and fixed:** `/api/capture/sessions` ownership is a same-origin browser cookie
(`clab_capture_owner`); the first attempt queried it with a plain `urllib` call (no cookie), which
always sees an empty list and wrongly reported FAIL, and ending the session the same way got a 404
for the same reason. Fixed to read/end through the browser context that actually owns the session
(`page.evaluate(fetch(...))` and the session page's own *End session* button). One capture container
from that first, buggy attempt was left running (its cookie was lost when that browser context
closed); it was not touched directly (no `docker stop`/`rm` — that boundary belongs to
`capture_service.py` alone) and is left to expire on its own via the documented idle timeout.

**Packet evidence:** `r39-capture-session-vnc.png` is a screenshot of the live Wireshark GUI inside
the noVNC session, taken right after the ping. It shows, in Wireshark's own status bar, **"Packets:
13"**, and the packet list itself: 5 ICMP echo-request/reply pairs between `10.0.12.0` (ceos) and
`10.0.12.1` (cjunosevolved) exactly matching the ping above, plus 3 OSPF Hello packets on the same
link (an incidental, real routing-protocol observation, not something this check drove). This is the
actual "packet counter... in the page" the brief asked for; it is drawn by Wireshark itself inside the
VNC canvas, not by a manager API field (which does not carry one).

### C.6 Diagnostics

| Check | Result | Evidence |
|---|---|---|
| `/static/debug.html` renders three cards | PASS | 3 cards |
| `#debug-probe` answers with PASS rows | PASS | "Folder listing — PASSED · 2 entries · 280 ms" / "VM commands — PASSED · VM helper 1.30.39 · 454 ms — Helper matches the manager." |

## Limitations

- Section C.5's packet-count check could not be done exactly as the brief described (an API field);
  the actual, stronger evidence used instead is a screenshot of Wireshark's own packet list and
  counter, described above.
- No browser-tooling gap: Playwright + Chromium worked throughout; every FAIL encountered during this
  session was a bug in the check script itself (wrong JSON key, an incomplete active-state set, and a
  cookie-less out-of-band API call), never a missing capability. Each is called out above with its
  fix and the independently corrected evidence.
- Section B is the one mutating step and was run exactly once, as assigned; its own transcript
  (reproduced verbatim in `r39-live-qa.json`) is the evidence, not a repeat run.
- The device itself was not read back a second time by this session: per the brief, the lead reads it
  back independently.
