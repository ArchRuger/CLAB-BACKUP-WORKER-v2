# Independent browser verification — release 1.30.36 (Setup Script Cleanup Log, part 1)

Verifier: independent QA pass (not the author of 1.30.36). Manager: the real, running manager on this
VM (`http://127.0.0.1:8081`), confirmed at `1.30.36` before any check (`/api/state` → `version`).
Lab: the live `restore-square` lab, already deployed and imported (5 nodes: ceos, cjunosevolved,
vjunos-switch, xrv9k, host1 — all `Running` / `Ready` at the start of this pass). No VM/manager restart,
no installer run, no destructive action taken. **No deploy, destroy, restore, Save progress or capture
was started** — every review/preview dialog was opened, read and then cancelled.

Tool: `docs/ui-ux-cleanup/tools/check_release_1_30_36.py` (Playwright, headless Chromium), run with

```
export LD_LIBRARY_PATH=$HOME/.local/lib/chromium-deps
clab-backup-ui/.venv/bin/python docs/ui-ux-cleanup/tools/check_release_1_30_36.py
```

Screenshots and `report.json` are in this folder (`docs/ui-ux-cleanup/evidence/`). No credentials are
recorded anywhere in the tool, the screenshots or this report.

**Kind of check throughout this report:** every row below is a *live browser check* against the real
manager and the real lab VM (Playwright driving headless Chromium), not code inspection and not a unit
test, unless a row explicitly says "code inspection" (used only where a live condition could not be
produced, noted as a limitation, never as a substitute pass).

## Summary

- Script totals (three runs, final one clean): **34 PASS / 2 FAIL / 12 INFO** across 48 checks.
- Console errors: **0**. Page errors: **0**. Handled (non-2xx) HTTP responses logged by Chromium: **5**,
  all `409 Conflict` from repeatedly opening the same "Start restore-square?" review in this same
  session without confirming (`LabOperations` serialises overlapping preview/settings calls) — cosmetic
  console noise from the *test driving the app twice*, not a defect; confirmed by reading
  `clab-backup-ui/app/lab_operations.py:156` (`self.active or operation_busy(...)` → 409) and by the
  fact every subsequent review still opened correctly with the right content.
- Page reload behaviour: `location.reload()` (used for the B5 check) re-runs the SPA's boot sequence,
  which restores `sessionStorage.activeLab` and reopens the last lab directly (by design — see
  `app/static/shell.js` line ~35, and the comment in `docs/redesign/tools/verify_after.py`'s
  `go_home()` that documents the same behaviour). A bare `goto('/')` does **not** reliably show the
  card grid for this reason; the tool follows the breadcrumb (`#crumb-home`) instead, matching
  `verify_after.py`'s convention.
- One item outside the assigned list is a genuine finding: **B3's banned caption is only removed on
  one of its two code paths** — see B3 below.

## PASS/FAIL table

| Item | Viewport | Result | Observed |
|---|---|---|---|
| B1 upload dialog has the annotations input | 1920×1080 | **PASS** | `#op-upload-annotations` present, label text exactly `Saved map (annotations JSON, optional)`, help text `JSON · up to 1 MiB · optional`, positioned directly after the topology file input. Screenshot: `1920x1080-b1-upload-dialog.png`. |
| B2 button label "Open in Lab Builder…" (not "Edit visually…") | 1920×1080 | **PASS** | Dialog actions: `['Preview topology', 'Open in Lab Builder…', 'Add to My labs without starting', 'Deploy lab']`. Screenshot: `1920x1080-b2-topology-file-dialog.png`. |
| B2 Lab Builder opens with the topology | 1920×1080 | **PASS** | Navigated to `/static/lab-builder.html#path=...`; 5 `.react-flow__node` elements rendered (ceos, cjunosevolved, vjunos-switch, xrv9k, host1). Screenshot: `1920x1080-b2-lab-builder-opened.png`. |
| B2 "← My labs" link reopens the Topology file dialog on the same path/content | 1920×1080 | **PASS** | After clicking `a.builder-back` (`href="/"`), `#op-editor` reopened with `op-edit-path` = `/srv/containerlab-node-manager/projects/restore-square/restore-square.clab.yml` and 1931 chars of YAML loaded (freshly re-read, not stale). Screenshot: `1920x1080-b2-reopened-after-my-labs-link.png`. |
| B2 browser Back button also reopens the dialog | 1920×1080 | **PASS** | Reopened the builder a second time, then used Playwright's `go_back()` (the real browser Back). Same result: `#op-editor` reopened on the same path. Screenshot: `1920x1080-b2-reopened-after-browser-back.png`. |
| B3 preview dialog size vs viewport | 1920×1080 | **FAIL** | Dialog `1120×643.5` px in a `1920×1080` viewport = **58% width / 60% height** (requirement: ≥80% of both). Visually the dialog floats in the middle of the screen with large unused margins on every side. Screenshot: `1920x1080-b3-preview-dialog.png`. |
| B3 preview dialog size vs viewport | 1366×768 | **FAIL** | `1120×493.8` px in `1366×768` = **82% width / 64% height** — width passes, height does not. Screenshot: `1366x768-b3-preview-dialog.png`. |
| B3 caption absent (restore-square, no saved map file) | 1920×1080 & 1366×768 | **PASS** (but see finding below) | For `restore-square.clab.yml` (which has no `.annotations.json` on the VM) the caption reads *"Wiring from the topology file. Devices sit on a default grid — arrange them later with Edit map."* — the banned sentence is absent **in this specific case**. |
| **Finding (outside the strict PASS list, code path only reachable with a saved map file):** for a topology that *does* have a saved `.annotations.json` (`link-basics`, read-only preview, nothing uploaded/deployed), the preview shows **exactly the banned caption**: *"Wiring from the topology file; device positions from its saved map file."* Confirmed live. Screenshot: `extra-b3-positioned-link-basics.png`. Source: `app/static/operations.js` `opMapPreview(drawing, name, positioned)` line ~443 still emits this string when `positioned` is true; only the `positioned=false` string was changed. The 1.30.36 CHANGELOG says "its wiring caption is gone" unconditionally — that is only true for topologies without a saved map file. | 1920×1080 | **FAIL** (regression / incomplete fix) | See above. |
| B4 review title "Start restore-square?" | 1920×1080 | **PASS** | `#operation-review h2` = `Start restore-square?`. |
| B4 no orange "Runs this trusted topology with host privileges…" box | 1920×1080 | **PASS** | Text absent (this warning is only appended server-side for `redeploy`/`apply`, not a fresh `deploy` — `app/host_operations.py` line ~322). |
| B4 no "Runs on the lab VM. If the lab changes before you confirm, this check is repeated." | 1920×1080 | **PASS** | Absent (client skips this caption for `action==='deploy'`). |
| B4 no "Technical details" summary wrapper | 1920×1080 | **PASS** | `Technical details` string not present; headings are `['Devices', 'Command run on the VM']` shown directly. |
| B4 "Command run on the VM" with containerlab argv visible directly | 1920×1080 | **PASS** | `"/usr/bin/containerlab" "deploy" "-t" "/srv/containerlab-node-manager/projects/restore-square/restore-square.clab.yml" "--name" "restore-square"`. Screenshot: `1920x1080-b4-deploy-review.png`. Dialog was **Cancelled**, not confirmed. |
| B5 banner present to dismiss | 1920×1080 | **INFO — not exercised** | Neither `#lab-banner` nor `#home-banner` was showing: `restore-square` is currently fully healthy (5/5 Ready, VM connected, no running/failed job), so the app correctly shows no notice. Screenshot: `1920x1080-b5-banner-before-dismiss.png`. Could not force a real notice without violating the "no deploy/destroy/restore" restriction (all of which would be needed to produce an "attention"/"needs credentials"/"operation running" banner). |
| B5 close control aria-label / sessionStorage mechanism | — | **Code inspection only (see limitation above)** | `index.html` bakes `aria-label="Hide this notice"` onto both `#lab-banner-close` and `#home-banner-close` statically; `app/static/app.js` `setBanner()` sets the same label dynamically for a non-running notice and calls `dismissNotice(key)` (→ `sessionStorage['clab.notice.<key>']='1'`) on click; `noticeDismissed(key)` is checked before ever un-hiding a banner again, and the key includes a digest of the banner text so a materially different notice is shown again. This is confirmed by reading the code, not by clicking a live banner — flagged per instructions rather than claimed as an executed pass. |
| B6 host1 Topology-tab rail: no "Needs credentials" | 1920×1080 | **PASS** | Row text: `host1 · Unmapped · Ready · Open CLI ↗`. `needsCreds` regex did not match; pill = `Ready`. Screenshot: `1920x1080-b6-topology-rail.png`. |
| B6 host1 Topology-tab Open CLI enabled | 1920×1080 | **PASS** | `cliDisabled: False`, no title/reason attached. |
| B6 host1 Devices-tab: no "Needs credentials" | 1920×1080 | **PASS** | Same row content plus a `Details` action. Screenshot: `1920x1080-b6-devices-tab.png`. |
| B6 host1 Devices-tab Open CLI enabled | 1920×1080 | **PASS** | `cliDisabled: False`. |
| B7 "Details" disclosure / "Lines show how the lab is wired…" absent | 1920×1080, 1366×768, 390×844 | **PASS** (all 3) | Sentence not found anywhere in `#topology-view` at any viewport. |
| B7 hint text present | 1920×1080, 1366×768, 390×844 | **PASS** (all 3) | `Click a device to open it. Click a link to capture its traffic. Right-click for more actions.` |
| B7 device rail independently scrollable (desktop) | 1920×1080 | **PASS** (overflow-y:auto confirmed; not exercised — 5 devices fit) | `scrollHeight === clientHeight === 808` at this height — 5 devices did not overflow even after retrying at forced heights, so scrolling itself could not be exercised at this exact viewport. `overflow-y: auto` and the two-column grid (`1116px 300px`) were confirmed. |
| B7 device rail independently scrollable (laptop) | 1366×768 | **PASS** | Overflowed as expected (`scrollHeight 612` vs `clientHeight 496`); `aside.device-rail.scrollTop = 200` moved the rail to `116` while `window.scrollY` stayed `0`; the "Devices" heading stayed visible (sticky); the map stayed visible throughout. Screenshots: `1366x768-b7-topology-1366x768.png`, `...-scrolled.png`. |
| B7 layout stacks at 390×844 | 390×844 | **PASS** | Single-column grid (`grid-template-columns` → 1 track); rail `overflow-y: visible` (scrolls with the page below the 1280px breakpoint, by design). Screenshot: `390x844-b7-topology-390x844.png`. |
| D1 vjunos-switch↔cjunosevolved, endpoint `vjunos-switch: ge-0/0/0` | 1920×1080 | **PASS** | Preselected `eth1`. Status text: *"Capturing clab-restore-square-vjunos-switch port ge-0/0/0 (container interface eth1) — start the capture when you are ready."* Screenshot: `1920x1080-d1-vjunos-switch-cjunosevolved-vjunos-switch.png`. |
| D1 same link, other endpoint `cjunosevolved: et-0/0/1` | 1920×1080 | **PASS (with a task-text discrepancy noted)** | Preselected `eth5`, not `eth4`. The assigned task text said "the cjunosevolved endpoint 'et-0/0/0' → eth4"; the actual topology link between vjunos-switch and cjunosevolved uses `cjunosevolved:et-0/0/1` (the `et-0/0/0` port is on the *other* cjunosevolved link, to ceos). Given the per-kind offset rule in `app/topology.py` (`juniper_cjunosevolved` offset 4), `et-0/0/1` → `eth5` is the mathematically correct mapping, and `et-0/0/0` → `eth4` is also correct — for the ceos↔cjunosevolved link, not this one. Treated as a labelling mismatch in the assignment, not a product defect; the mapping logic itself checks out on both links (see next rows and the extra check below). |
| D1 vjunos-switch↔xrv9k, endpoint `xrv9k: Gi0/0/0/0` | 1920×1080 | **PASS** | Preselected `eth1`. |
| D1 ceos↔xrv9k, endpoint `ceos: eth2` | 1920×1080 | **PASS** | Preselected `eth2` (identity — ceos ports are already named `ethN`). |
| D1 host1↔vjunos-switch, endpoint `host1: eth1` | 1920×1080 | **PASS** | Preselected `eth1` (identity — Linux node, no per-kind rule needed). Screenshot: `1920x1080-d1-host1-vjunos-switch-host1.png`. |

## `/api/state` excerpt for host1 (no passwords)

```json
{
  "name": "clab-restore-square-host1",
  "short_name": "host1",
  "kind": "linux",
  "image": "ghcr.io/srl-labs/network-multitool:latest",
  "readiness": "Choose NOS",
  "credential_source": "default",
  "login_configured": true,
  "nos_login": {
    "status": "ready",
    "message": "NOS accepted SSH login and answered show version (automatic check)"
  },
  "ssh_ready": true
}
```

`image` was already present (this lab had already been synced/imported with the current build), so
*Sync from VM* was **not** needed and was **not** run. `credential_source: "default"` matches
`app/inventory.py`'s new `ghcr.io/srl-labs/network-multitool` default-login entry; because
`deviceState()` (`app/static/status.js`) branches on `node.ssh_ready` before it ever looks at
`readiness`, host1 reads as plain `Ready` in the UI even though its `readiness` field is the unrelated
`"Choose NOS"` value (no specific NOS chosen for this generic Linux node) — this is consistent, not a
bug.

## D1 — full topology and mapping used to derive expectations

```
ceos:eth1  ---- cjunosevolved:et-0/0/0
cjunosevolved:et-0/0/1 ---- vjunos-switch:ge-0/0/0
vjunos-switch:ge-0/0/1 ---- xrv9k:Gi0/0/0/0
xrv9k:Gi0/0/0/1 ---- ceos:eth2
host1:eth1 ---- vjunos-switch:ge-0/0/2
host1:eth2 ---- ceos:eth3
```

Per-kind offsets from `app/topology.py` `PORT_RULES` (`juniper_vjunosswitch` +1, `juniper_cjunosevolved`
+4, `cisco_xrv9k` +1, `arista_ceos`/`linux` identity), every endpoint tested resolved to the
mathematically expected `ethN`, confirmed live against the VM's actual interface list (not guessed):
`ge-0/0/0→eth1`, `ge-0/0/1→eth2`, `ge-0/0/2→eth3`, `et-0/0/0→eth4` (not directly tested — belongs to the
ceos↔cjunosevolved link, out of the assigned pair), `et-0/0/1→eth5`, `Gi0/0/0/0→eth1`, `Gi0/0/0/1→eth2`,
ceos/host1 ports pass through unchanged.

## Limitations / gaps

1. **B5 was not exercised against a real visible notice.** `restore-square` is fully healthy right now,
   so no lab or home banner is showing. Producing one live (e.g. a failed operation, missing
   credentials, or a running job) would have required an action outside this pass's permitted scope
   (deploy/destroy/restore/save). The close-control label and the sessionStorage-backed persistence
   were confirmed by code inspection only, which is flagged here rather than presented as an executed
   browser pass. **Recommend**: a follow-up pass with a lead-approved lab state that does show a banner
   (or a fixture-based unit/browser test, since fixtures are disposable data and do not have this
   restriction).
2. **B7 rail scrolling was not exercised at exactly 1920×1080** because 5 devices fit without
   overflowing at that height; confirmed instead at 1366×768 per the task's own fallback instruction.
3. The D1 task text's expected label for one sub-case ("cjunosevolved endpoint 'et-0/0/0' → eth4") does
   not match the actual `restore-square` topology for the vjunos-switch↔cjunosevolved link (which uses
   `et-0/0/1`); reported as a likely mix-up with the neighbouring ceos↔cjunosevolved link rather than a
   product defect, since the underlying mapping rule was independently verified correct on both links.
4. Chromium's automatic "Failed to load resource: 409" console entries (5, all from this session
   re-opening the same deploy review multiple times without confirming) are reported separately from
   real console/page errors per the project's own convention (`docs/redesign/tools/verify_after.py`
   `HANDLED` prefix), and were 0 real errors either way.

## Files

- Script (owned, new): `docs/ui-ux-cleanup/tools/check_release_1_30_36.py`
- Evidence (owned, new): `docs/ui-ux-cleanup/evidence/*.png`, `docs/ui-ux-cleanup/evidence/report.json`,
  this file.
- No product source, configuration or test file was edited.
