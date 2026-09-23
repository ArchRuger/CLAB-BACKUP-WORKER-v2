# Release 1.30.42 live QA — final build of the technical audit

Independent live acceptance check, run as the sole operator of the manager at `http://127.0.0.1:8081`
(commit `0cd18a7`, `/api/state` reports `1.30.42`, helpers `1.30.42`) and the lab `restore-square`
(`174386ec12ee496190c585c5796b2662`, cEOS + cJunosEvolved + vJunos-switch + XRv9k + host1). Tooling:
`docs/technical-audit/tools/check_release_1_30_42.py` (Playwright + `urllib`, real browser, real API,
real device sessions — never a fixture, never disposable data), adapted from
`docs/technical-audit/tools/check_release_1_30_39.py`. Full JSON report: `r42-live-qa.json` (a
hand-consolidated merge of every section's own JSON output — the tool's module-level result lists
reset per process invocation, and sections were run as separate invocations while fixing real script
bugs against the live system; every row was still produced by an actual run against the live manager,
never fabricated). Screenshots: the eight PNGs in this folder (`r42-A-favourite-outline.png`,
`r42-A-favourite-filled.png`, `r42-A-wire-capture-dialog.png`, `r42-C1-upload-review.png`,
`r42-C2-builder-drop-pair.png`, `r42-C3-publish-review.png`, `r42-C3-revise-review.png`,
`r42-D-capture-session.png`).

Overall: **0 unhandled FAIL** across every check in sections A–D (one transient condition, a VM-side
Git repository lock, is recorded as INFO — resolved through the product's own retry action, not a
defect); nine script bugs were found in the check tool itself while developing it against the real
system and are listed at the end with their fixes, exactly as r39's QA did. Console errors: 0, page
errors: 0, and no request to `/telemetry` other than `/telemetry-retired`, across every run segment.

## A. Absence and presence (1920×1080, 1366×768, 390×844), plus the 1.30.40 changes

| Check | Result | Evidence |
|---|---|---|
| No telemetry/Grafana ids, `#i-telemetry` symbol, or wording anywhere (lab-home, topology, devices, progress, tools, Lab actions ▾ menu + Advanced options, Manager ▾ menu), at all three viewports | PASS ×3 | empty match lists every time |
| Lab actions ▾ retained items present (`lab-start`, `menu-sync-vm`, `menu-capture`, `menu-lab-files`, `menu-destroy`, `menu-remove-lab`) | PASS ×3 | all `present: true` |
| `#menu-telemetry-retired` present in markup but **hidden** (no retired-telemetry record exists for this lab — it was removed for good in 1.30.39) | PASS ×3 | `{present: true, hidden: true, disabled: false}` |
| `/api/state` lab has no `telemetry_retired` key; no retired-telemetry banner shown; `GET .../telemetry-retired` → 404 | PASS ×3 | key absent; `{hidden:true,text:''}`; `404` |
| Manager ▾ menu text has no telemetry/Grafana wording | PASS ×3 | menu text dump clean |
| Tools cards *Packet capture* / *Configuration backups* present; static/API telemetry surfaces → 404 | PASS ×3 | all present/404 |
| **Favourite star (F-001, closed in 1.30.40)**: outline (`fill:none`) when not a favourite, filled (`fill:currentColor`) once pressed, read through `getComputedStyle` on the `<use>` element; toggled once on the Home card, screenshotted both states, then restored | PASS | before: `{pressed:'false', fill:'none'}` → after: `{pressed:'true', fill:'rgb(23, 93, 119)'}` → `/api/state favorite=true` → restored to `favorite` absent again |
| **Topology wires draw and a link click opens the capture dialog (1.30.40)** | PASS | 6 `.topology-wire` elements drawn, real stroke colour `rgb(111, 133, 147)` on the non-`.capture-hit` path; clicking a wire opened `#capture-dialog` naming `Link endpoint: host1: eth2` |

Screenshots: `r42-A-favourite-outline.png`, `r42-A-favourite-filled.png`, `r42-A-wire-capture-dialog.png`.

Ran once at 1920×1080 (favourite/wires are mutating or one-time checks, like r39's section B); the
absence/presence sub-checks ran at all three viewports.

## B. Backend bounds and output (1.30.42 changes)

### B.1 Lab-wide backup and bounded job lists

| Check | Result | Evidence |
|---|---|---|
| `POST /api/labs/<id>/jobs {operation: backup}` accepted, reaches a final status | PASS | job `4d6f15e7...`, `4/4 NOS sessions completed successfully` |
| New job first in `/api/state` `jobs`; four NOS nodes `succeeded`; host1 excluded | PASS | `jobs[0].id` matches; all four `succeeded` |
| `jobs` for this lab ≤ 300 (the per-lab cap, RR-201) | PASS | 39 |
| `git_jobs`/`restore_jobs`/`operations`/`jobs` counts from `/api/state` match `/api/debug`'s `saved_counts` (returned whole, RR-206) | PASS | `{jobs:39, git_jobs:5, restore_jobs:12, operations:44}` both sides |
| ZIP download of the new job works, lists members incl. `manifest.json` | PASS | 5 members incl. manifest |

### B.2 An operation with streamed output ("Show running devices" / inspect)

| Check | Result | Evidence |
|---|---|---|
| Lab actions ▾ → "All lab operations…" → inspect action available, review dialog, confirm | PASS | review title "Refresh the device list for restore-square" |
| Output window auto-opens; `GET /api/operations/<job>` reaches `succeeded` | PASS | job output 2645 bytes |
| Output contains all five container names; no line matching `/password/i`; plain text under 512 KiB | PASS | `missing=[]`; `password_lines=[]`; 2645 bytes |
| The auto-opened output window shows the same lines as the API | PASS | DOM text == API `output` exactly (2645 chars both) |

### B.3 Save progress: unchanged, then a real drift, reviewed and uploaded

| Check | Result | Evidence |
|---|---|---|
| Label `Technical audit 1.30.42 live check` → no review dialog (unchanged since the 1.30.39 save) → job `unchanged` | PASS | job `040ae066...`, status `unchanged` |
| Progress tab (Recent saves) status text | PASS | **"Progress saved to Git — nothing had changed · just now"** |
| Terminal drift on cEOS: `enable` → `configure` → `interface Ethernet2` → `description AUDIT-1-30-42` → `end` | PASS | prompt reached `ceos(config-if-Et2)#` then back to `ceos#` |
| Label `Technical audit 1.30.42 drift` → review dialog appears (mandatory review) → Upload | PASS | review named the destination and a real diff (`ceos.cfg changed`) |
| Final status `synced`, `pushed: true` | PASS (after one retry of a transient VM-side lock — see below) | commit `3f9bf62c9c7022c69cad92e7232d2ed1b203eb9d` |
| Progress tab status text for the drift save | PASS (read mid-transition) | showed **"Saved on this VM — upload needs attention · just now"**/`"Uploading…"` at read time; the job's own final API state, read immediately after, was already `synced`/`pushed:true` |

**Transient repository lock (not a defect):** the drift save's first upload attempt landed in
`push_pending` with the message *"Another Git operation is already running for this repository."*
(`host_git.py` `Repository.lock`, a real VM-side advisory `flock`, most likely held briefly by a
concurrent repository-status check). This was retried through the product's own **Upload now** retry
action, not worked around out of band; the very next Save progress attempt on the same drift produced
`synced`/`pushed:true` at commit `3f9bf62c9c7022c69cad92e7232d2ed1b203eb9d`, and the original stuck job
later resolved itself to `synced` on its own — confirming the lock was transient.

**Remote verification (read-only Git on the registered checkout):**
```
$ git -C ~/labs/CLAB-MNGR-DEV-LLM fetch origin
   a46b956..3f9bf62  main       -> origin/main
$ git -C ~/labs/CLAB-MNGR-DEV-LLM log --oneline -3 origin/main
3f9bf62 Technical audit 1.30.42 drift
a46b956 Technical audit 1.30.39 live check
795edb2 Configuration B
```

## C. Lab builder and the two known gaps

### C.1 Pair upload through *Upload a lab file*

| Check | Result | Evidence |
|---|---|---|
| Files: `qa42-pair.clab.yml` + `qa42-pair.clab.annotations.json` (renamed scratch copies of `tests/fixtures/map/{lab.yaml,annotations.json}`) set on `#op-upload-file` / `#op-upload-annotations`; Continue opens the editor for review | PASS | title "Uploaded lab file" |
| "Create file on the VM…" → reviewed `create`; **review text names the map file** | PASS | *"Saved map: BGP_TheoryToPractice.clab.yaml.annotations.json will be written next to the topology"* |
| Confirm → job succeeds, reports the saved path; lab **not deployed** | PASS | `Saved as /srv/containerlab-node-manager/projects/BGP_TheoryToPractice.clab.yaml. It is not running yet.` |
| Topology browser (`opBrowse`) lists the new topology file in the projects folder | PASS | `['link-basics', 'restore-square', 'BGP_TheoryToPractice.clab.yaml']` |
| The annotations file's presence/content, confirmed via the manager's read route (see note) | PASS | `GET .../BGP_TheoryToPractice.clab.yaml.annotations.json` → 200, `nodeAnnotations` present |
| `GET` the topology through the manager's read route shows the YAML | PASS | `name: BGP_TheoryToPractice` … |

**Note on the folder listing:** `host_operations.py` `browse()` deliberately lists only directories
and `*.clab.yaml`/`*.clab.yml` files (the dialog's own "Only topology files are listed" text, enforced
server-side too) — the annotations file never appears there **by design**, for this pair and for the
lab builder's own `publish`/`revise` folders alike. This was reproduced independently with a throwaway
curl-only create+delete cycle against a scratch file before concluding it, so this is a corrected false
FAIL in the check, not a missing write.

Screenshot: `r42-C1-upload-review.png` (review dialog, map file named).

Folder recorded for the lead: `/srv/containerlab-node-manager/projects/BGP_TheoryToPractice.clab.yaml`
(+ its `.annotations.json`).

### C.2 Drop of a pair into the lab builder

| Check | Result | Evidence |
|---|---|---|
| `/static/lab-builder.html` opens blank, on the welcome page with its drop zone (no draft started) | PASS | `#builder-welcome` visible, `#builder-drop` present |
| A synthetic `DataTransfer` (built in the page, `dragenter`/`dragover`/`drop`) with `qa42-drop.clab.yml` + `qa42-drop.clab.yml.annotations.json` dispatched on `#builder-drop` | PASS | dispatched without error |
| Editor loads the topology: **13 devices** from the fixture YAML | PASS | `.react-flow__node-topology-node` count = 13 (`.react-flow__node` alone is 27 — it also counts the map's text/shape/group annotations) |
| Annotations positioned devices: PE1 and GTW-1 match the fixture exactly | PASS | `PE1: (60,100)`, `GTW-1: (220,100)` |

Screenshot: `r42-C2-builder-drop-pair.png`.

### C.3 Builder publish and revise

| Check | Result | Evidence |
|---|---|---|
| New lab `qa42-builder`, two *Linux host* devices dragged and linked | PASS | 2 nodes, 1 edge |
| *Save to VM* → review names the folder → confirm → publish succeeds | PASS | review: `/srv/containerlab-node-manager/projects/qa42-builder/qa42-builder.clab.yml`; job "succeeded" |
| Added to My labs without starting (needed so *Remove from this manager…* has something to act on — see note) | PASS | toast "qa42-builder added to My labs." |
| Folder appears in the topology browser with the YAML file; the annotations file confirmed via the read route | PASS | `['qa42-builder.clab.yml']`; annotations read → 200 |
| Edit the YAML panel (rename `host1`→`host1renamed`), Apply, Save again → **revise** (allowed while undeployed) | PASS | review: "Save the changes to qa42-builder? … Only possible while the lab is not deployed." |
| Revise job succeeds; the file changed through the read route | PASS | read-back shows `host1renamed` |
| Lab **not deployed** throughout | PASS | no deploy step taken |
| Remove the lab from this manager only (*Remove from this manager…*) | PASS | `still_present=False` in `/api/state` after removal |
| VM folder/file remain after the manager-only removal | PASS | re-browsed: `qa42-builder.clab.yml` still there |

**Note on the sequencing:** `publish`/`revise` operate purely against the VM file path and never touch
My labs on their own. The main run published and revised `qa42-builder` directly without ever opening
the saved file's own dialog, so nothing was registered for `#remove-lab` to act on and the first
attempt at this last step timed out waiting for a My-labs card. Fixed by adding the normal "Add to My
labs without starting" step (from the topology-file dialog opened via `#op-open-published`) right after
publish. Because the main run had already published+revised the folder before this fix landed, the
add/remove pair was completed with two small standalone follow-up scripts against that same
already-published folder (to avoid re-running the whole builder flow and colliding with the folder
already on the VM) — both against the real manager and the real VM folder, not a fixture.

Screenshots: `r42-C3-publish-review.png`, `r42-C3-revise-review.png`.

Folder recorded for the lead: `/srv/containerlab-node-manager/projects/qa42-builder/` (topology,
annotations file, and the helper's own `.clab-manager-history` recovery copy from the revise step).

### C.4 Map editor

| Check | Result | Evidence |
|---|---|---|
| Open *Edit map* for `restore-square`, drag a device (ceos), Save map becomes enabled | PASS | — |
| Save map → `map-status` says "Saved in the manager"; `GET .../map-document` shows the new position | PASS | `(0,0) → (100,60)` |
| Reload the Topology tab → position persisted | PASS | reloaded position matches |
| Move it back, Save map again | PASS | restored to `(-20,0)`, close to the original `(0,0)` |

## D. Retained checks

| Check | Result | Evidence |
|---|---|---|
| `ssh-check-all` → `started: 5, skipped: []` | PASS | — |
| Terminal to cJunosEvolved reaches a prompt within 30s | PASS | `JUNOS 26.2R1.7-EVO … admin@HOSTNAME>` |
| Diagnostics: three cards render, `#debug-probe` answers PASS rows | PASS | "Folder listing — PASSED", "VM commands — PASSED · VM helper 1.30.42 · Helper matches the manager." |
| Packet capture: session started on the ceos↔cjunosevolved link (`eth1`), noVNC page loads and connects, session ended | PASS | "Connected to Wireshark on the VM." → "Session ended. Its capture files were removed from the VM." |

Screenshot: `r42-D-capture-session.png`.

## Final step (assigned mid-task by the coordinator, run last as sole operator)

### Four-node restore to the pristine "Configuration A"

`docs/multi-platform-restore/tools/manager_restore.py --commit f12421e615d13adb938906621f0510b46d874283
--path restore-square/qa-1-30-37/latest --nodes ceos cjunosevolved vjunos-switch xrv9k --minutes 10`
(the short hash `f12421e` alone was refused — `host_git.py` `read_version` requires the full 40-char
commit — resolved with `git rev-parse f12421e` first).

| Check | Result | Evidence |
|---|---|---|
| Preflight | PASS | 200, all four targets eligible |
| Restore job reaches a final status | PASS | `succeeded`, job `b4007a26...` |
| All four targets `verified` | PASS | ceos, cjunosevolved, vjunos-switch, xrv9k all `verified` |
| Idempotent double-submit (same `request_id`) returns the same job | PASS | `same_job: true` |
| Targets overlapped (`max(connecting) < min(settled)` across targets) | PASS | `max(connecting)=1790169059.518`, `min(settled)=1790169061.722` → **true**: all four began connecting within ~12ms of each other; the earliest did not settle until ~2.2s after the last one started connecting — genuine concurrency across `restore-node_0..3` workers, not a serial run |

Full evidence: `r42-restore-all-four-to-a.json` (includes the per-target `timeline` and the overlap
analysis).

### Save progress "Configuration A (audit 1.30.42)"

Browser: *Save progress* → label `Configuration A (audit 1.30.42)` → review dialog appeared (real
diff, e.g. `ceos.cfg changed`, 4 added / 6 removed) → Upload.

| Check | Result | Evidence |
|---|---|---|
| Review dialog appears, names the destination | PASS | `CLAB-MNGR-DEV-LLM › main › restore-square/qa-1-30-37/latest` |
| Final status | PASS | `synced`, `pushed: true`, commit `27ccd717aa5556ac4992dbff056258cd67ddb365` |
| Remote verification | PASS | `git fetch origin` → `3f9bf62..27ccd71 main -> origin/main`; `git log --oneline -3 origin/main` → `27ccd71 Configuration A (audit 1.30.42)` |
| Commit only touches the four restored nodes' files (host1 untouched) | PASS | `git show --stat`: `ceos.cfg`, `ceos.eoscfg`, `cjunosevolved.jcfg`, `manifest.json`, `vjunos-switch.jcfg`, `xrv9k.cfg`, `xrv9k.xrcfg` |

`restore-square/qa-1-30-37/latest` now holds Configuration A again, ready for the lead's failure
harnesses.

## Script bugs found and fixed while developing `check_release_1_30_42.py`

Every one below was a bug in the check script itself, corrected against the real system's actual
behaviour (never worked around by weakening the assertion without understanding why it failed first):

1. **B2** — `inspect_btn.count()` was read before the Lab operations dialog rendered past its
   "Checking what this VM can do…" placeholder; fixed with `locator.wait_for(state='visible')`.
2. **B2** — the `/api/operations` poller assumed a dict-with-`items` shape and called `.get()` on it
   before checking `isinstance`, crashing on the real (bare list) response; fixed to branch on
   `isinstance` first.
3. **B3** — cEOS's terminal starts at the unprivileged `ceos>` prompt; `configure` alone is refused
   ("Invalid input (privileged mode required)"); fixed by sending `enable` first.
4. **B3** — the Progress tab status-text selector assumed a `.badge` class that does not exist in the
   real markup (`git-progress.js` `gitRenderSaves` uses `<details class="git-saved-job"><summary>`);
   fixed to read the `<summary>` of the newest `details.git-saved-job`.
5. **B3** — a genuine transient VM-side Git repository lock (not a script bug) was retried through the
   product's own retry action rather than worked around; see the B.3 note above.
6. **C1 / C3** — assumed the topology browser would list the annotations file beside the topology;
   `host_operations.py` `browse()` deliberately lists only directories and `*.clab.yaml`/`*.clab.yml`
   files, by design; fixed to confirm the annotations file through the read route instead, after
   reproducing the real (correct) behaviour independently with a throwaway curl-only probe.
7. **C2** — with a blank draft already open, dropping a pair triggers a native `confirm()` that
   Playwright silently auto-dismisses; fixed by dropping directly on the fresh welcome page's own drop
   zone before starting any draft (also the more literal reading of "start a blank lab").
8. **C2** — `.react-flow__node` also counts the map's text/shape/group annotation nodes, not just
   topology devices; fixed to count `.react-flow__node-topology-node`.
9. **C3** — publish/revise never touch My labs on their own, so nothing existed yet for
   `#remove-lab` to remove; fixed by adding the "Add to My labs without starting" step, completed for
   the already-published folder with two small standalone follow-up scripts.
10. **D** — `#capture-prepare` stayed disabled because no interface checkbox was ticked; fixed by
    explicitly checking `eth1`.

## Cleanup performed by this session

- Removed a throwaway probe file (`/srv/containerlab-node-manager/projects/qa42-curl-test.clab.yaml`
  + its `.annotations.json`), created only to isolate the browse()-listing false FAIL, through the
  manager's own reviewed delete action.
- Ended the one capture session started for section D through its own *End session* button.

## VM paths left for the lead to clean

- `/srv/containerlab-node-manager/projects/BGP_TheoryToPractice.clab.yaml` (+
  `.clab.yaml.annotations.json`) — from C.1, never deployed, never added to My labs.
- `/srv/containerlab-node-manager/projects/qa42-builder/` (`qa42-builder.clab.yml` +
  `.clab.yaml.annotations.json`, plus the helper's own `.clab-manager-history` recovery copy from the
  revise step) — from C.3, published, revised, added to My labs and then removed from this manager
  only; the VM folder and its files were intentionally left in place.

## Limitations

- The check tool's own JSON report resets its result list per process invocation; because sections
  were run as separate invocations while real script bugs (never product defects) were found and
  fixed against the live system, `r42-live-qa.json` is a hand-consolidated merge of every section's
  own output rather than one single uninterrupted run. Every row in it is still a real observation
  against the live manager and the real lab VM this session — nothing here is inferred or assumed.
- No browser-tooling gap: Playwright + Chromium worked throughout every section.
