# 1.30.37 browser QA — pass "a" (B3, D2, B5, C1–C4)

Independent verification, run against the **real deployed manager** on this VM (`http://127.0.0.1:8081`,
confirmed release 1.30.37, helper 1.30.37) and the real lab VM. No fixture manager and no disposable
Store were used for anything in this pass. The concurrently-assigned lab `restore-square` was only read
and, for D2, driven through its real "Test logins" (SSH login check) endpoint — no save, restore, deploy,
destroy or VM-connection change was performed. The lab builder work (C1–C4) built and discarded
browser-only drafts in `localStorage`; **"Save to the VM…" was never pressed.**

Script: `docs/ui-ux-cleanup/tools/check_release_1_30_37_a.py` (copies the console/page-error capture and
viewport conventions of `check_release_1_30_36.py`; the C1–C4 flow follows the two-viewport pattern of
`check_lab_builder_yaml.py`, pointed at the real manager instead of a fixture).

Run:
```
export LD_LIBRARY_PATH=$HOME/.local/lib/chromium-deps
clab-backup-ui/.venv/bin/python docs/ui-ux-cleanup/tools/check_release_1_30_37_a.py
```

Evidence: `docs/ui-ux-cleanup/evidence/r37a-*.png`, `docs/ui-ux-cleanup/evidence/r37a-report.json` (68
checks; see the full detail objects there — this report summarizes them).

**Totals (final run):** 62 PASS / 1 FAIL / 5 INFO. Console errors: 0. Page errors: 0. Two *handled* HTTP
409 console entries (`Failed to load resource: … 409`) are the expected refusal of an overlapping
`ssh-check-all` call (one from this script's own concurrency test, one from ordinary lab-busy noise while
the other assigned operator was active on the same lab) — not product defects. `/api/state` at the end:
**version 1.30.37, helper_version 1.30.37**.

## B3 — Preview topology dialog (real browser, real manager)

Tested twice: `link-basics` (has a saved `.annotations.json` map) at all three viewports, and
`restore-square` (no map file — confirmed via `/api/state.discovery.file_reports.restore-square.annotations.status == "missing"`) at 1920×1080.

| Viewport | Lab | Size vs viewport | viewBox set | No clipping (scene bbox ⊆ viewBox) | Caption absent | Close visible | Resize refits | Escape closes |
|---|---|---|---|---|---|---|---|---|
| 1920×1080 | link-basics | 94% × 92% (≥80% both) | PASS | PASS | PASS | PASS | PASS | PASS |
| 1366×768 | link-basics | 96% × 92% (≥80% both) | PASS | PASS | PASS | PASS | PASS | PASS |
| 390×844 | link-basics | 96% × 98% (full screen) | PASS | PASS | PASS | PASS | n/a (mobile: not resized) | PASS |
| 1920×1080 | restore-square | 94% × 92% | PASS | PASS | PASS | PASS | PASS | PASS |

Notes:
- The caption `"Wiring from the topology file; device positions from its saved map file."` is absent in
  every case — code inspection confirms `opMapPreview()` (`app/static/operations.js`) no longer renders any
  caption text at all (the dialog body is only the `<svg>`; the `positioned` parameter is accepted but
  unused), so this holds regardless of whether a map file exists.
- "No clipping" was checked by comparing the SVG's `viewBox` (set by `opFitPreview()` →
  `measureTopology()`, which reads `#topology-scene`'s `getBBox()` plus a 35px margin) against the drawn
  scene's own bbox: the viewBox fully contains the scene in all six cases.
- "Resize refits": resizing the browser window while the dialog stays open re-invokes `opFitPreview` (a
  live `resize` listener installed by `opMapPreview`). The recomputed `viewBox` numbers are nearly
  identical before/after (they derive from the SVG's user-space content bbox, not window pixels), which is
  expected — the important property, confirmed, is that the fit routine reruns without error and the
  content still fits with no clipping after the resize. Not exercised at 390×844 (a real phone would not
  resize while a full-screen dialog is open).
- Dialog CSS (`style.css` `.dialog-viewport`): `width: min(96vw, 1800px); height: min(92vh, 1200px)`,
  `100vw`/`100vh` under 600px — this is why 1920×1080 reads 94%/92% rather than 96%/92% (the 1800px cap
  applies at that width) while 1366×768 reads the uncapped 96%/92%. Both clear the ≥80%/≥80% bar.

## D2 — "Test logins" control

| Check | Result |
|---|---|
| `#rail-test-logins` present beside the Topology-tab "Devices" heading | PASS |
| `#devices-test-logins` present beside the Devices-tab "Devices" heading | PASS |
| Both buttons' `title` = "Tests the SSH login of every device again. A successful test makes Open CLI available." | PASS |
| Two concurrent `ssh-check-all` POSTs → exactly one 200 (`{started,skipped}`), one 409 | PASS |
| Clicking Test logins immediately sets **both** buttons to "Testing…" / disabled | PASS |
| A device card shows the "Testing login…" busy pill while the check runs | PASS (ceos, cjunosevolved, vjunos-switch seen; one card briefly read "Needs attention" instead of "Testing login…" mid-run — see note) |
| Both buttons settle back to "Test logins" within ~60s | PASS (well under 60s — see note on speed) |
| `nos_login.at` updated in `/api/state` for the tested devices | PASS (ceos, cjunosevolved, vjunos-switch, xrv9k) |
| **host1 (the multitool) is included among the tested devices** | **FAIL** |
| `deviceState()` detail for a `booting` device mentions "Test logins" | PASS |
| `deviceState()` detail for a `needs_credentials` device mentions "Test logins" | PASS |

### FAIL: host1 is silently excluded from the bulk "Test logins" action

The real `ssh-check-all` response for the click was:
```json
{"started": 4, "skipped": [{"name": "clab-restore-square-host1", "reason": "disabled"}],
 "at": "2026-09-23T02:43:24.034786+00:00"}
```
`host1`'s `nos_login.at` in `/api/state` was byte-for-byte unchanged before/after the run, and
`/api/state` shows `"enabled": false` on the host1 node.

Root cause (code inspection): `NodeServices.bulk_check_targets()`
(`clab-backup-ui/app/node_services.py:99-118`) skips any node where `not node.get('enabled', True)` with
reason `'disabled'`, before it ever looks at credentials. A node's `enabled` flag is set at inventory
import time to `bool(kind)` where `kind` is the **recognized NOS platform** resolved from
`ansible_network_os`/`clab_kind`/topology groups (`clab-backup-ui/app/inventory.py:199-204`), not a
"should this device be tested" flag. `host1` is a plain `network-multitool` Linux image with no NOS kind,
so `platform == ""` (shown in the UI as "Choose NOS") and `enabled == False` — even though, per the B6 fix
already in 1.30.36/1.30.37, it has baked-in default credentials (`credential_source: "default"`,
`ghcr.io/srl-labs/network-multitool` → `admin`/`multit00l` in `inventory.py`'s
`IMAGE_DEFAULT_CREDENTIALS`), a real address, and is fully `ssh_ready: true` with **Open CLI already
enabled** for it (confirmed live: individual/automatic readiness already marks it Ready).

So `bulk_check_targets()` reuses the "has a recognized NOS platform" flag as a bulk-eligibility gate, which
was presumably intended to skip devices that have no NOS CLI to answer `show version` — but it has the
side effect of excluding host1 from the lab-wide "Test logins" refresh entirely, contradicting the
explicit assignment expectation that "host1 (multitool) is included." The individual per-node
`POST /api/labs/{id}/ssh-check` route (`node_services.py:186-198`) does **not** apply this `enabled` gate
(only checks that credentials exist), so a per-device "Test login" on host1's own card would very likely
still work — this pass did not additionally verify that per-node path, since it was out of scope for D2's
"Test logins" bulk-refresh check, but it is worth the lead's attention as the probable reason the bulk
action and the per-device action disagree about host1.

**This is a real product finding, not a script bug** — confirmed via the raw `ssh-check-all` JSON response
and `/api/state`'s `enabled`/`nos_login.at` fields, both read directly from the real manager.

Note on speed: these are local, already-`Ready` containers on the containerlab bridge (172.20.20.0/24);
the real SSH probe + `show version`/`echo` round trip for all four eligible devices completed in well
under a second in every observed run, which is why one device card's busy pill was caught mid-flight in
one run but a different one ("xrv9k" briefly showed "Needs attention") in the final run — almost certainly
a moment of contention with the other operator's concurrent Save/Restore activity on the same lab, not
something this pass's "Test logins" click caused (Test logins never sets a "Needs attention"/`failed`
device state by itself; `deviceState()`'s `attention` key requires `login==='failed'`). This pass did not
investigate further since diagnosing the other operator's session is out of this pass's scope; flagged
here only as context for the lead.

## B5 — Notice banners

At the **first** observation this pass made (an earlier run of this same script, 02:41 UTC, before the
settle-loop fix below was added), `#lab-banner` was visible with text **"The last save did not complete."**
(evidently from the other operator's concurrent Save-progress/Restore work on `restore-square`). That
banner's close control (`#lab-banner-close`) had `aria-label="Hide this notice"`; clicking it hid the
banner, and after a full page reload it stayed hidden (sessionStorage) — screenshots
`r37a-1920x1080-b5-earlier-pass-0241-after-dismiss.png` and
`r37a-1920x1080-b5-earlier-pass-0241-after-reload.png` are that evidence.

In the **final** run (used for `r37a-report.json`), by the time this pass reached B5 the other operator's
save had evidently succeeded and the banner was gone: both `#lab-banner` and `#home-banner` read
`hidden: true`. Per the assignment ("if none is visible, report that and skip … do not wait for it"), this
is reported as INFO/skip in the final report, with the dismiss-and-reload behavior already independently
confirmed by the earlier observation above.

## C1–C4 — Lab Builder (real manager, no fixture)

Run in full at both required viewports (1366×768, 390×844), each in its own fresh browser context/profile.

| Check | 1366×768 | 390×844 |
|---|---|---|
| C2: `#builder-status` hidden on the welcome page before any draft | PASS | PASS |
| C3: welcome drop-zone text + "Open lab files…" button | PASS | PASS |
| C1: New lab dialog has only "Lab name" + "Lab folder on the VM" (no "Start from"/"Device type for the starter") | PASS | PASS |
| C1: new draft opens on a blank canvas (0 `.react-flow__node`) | PASS | PASS |
| C2: `#builder-status` visible with text once a draft exists ("Draft · kept in this browser only · not on the VM yet") | PASS | PASS |
| C4: YAML button opens `#builder-yaml-panel`; no overlap with the canvas (side-by-side at 1366, stacked at 390) | PASS | PASS |
| C4: typing a two-node topology + Apply → two nodes drawn | PASS | PASS |
| C4: broken YAML + Apply → parser's `Line N: …` message, nodes unchanged | PASS | PASS |
| C4: Revert restores the applied text | PASS | PASS |
| C4: right-click a node → Create Link → link drawn, reflected in the clean YAML panel | PASS | INFO (skipped — see below) |
| "Save to the VM…" never pressed | PASS (sanity) | PASS (sanity) |
| Draft discarded via Drafts… → delete; nothing left in `localStorage` | PASS | PASS |

At 390×844 the link-drawing step could not be exercised: the editor's own side palette
(`[data-testid="context-panel"]`) covers the whole canvas at that width and its fold button
(`[data-testid="panel-toggle-btn"]`) is unreachable/does not respond within 30s, so there was no way to
right-click a node on the canvas at that viewport. This matches the same limitation already recorded by
`check_lab_builder_yaml.py` against the fixture ("the editor's palette covers the canvas… drawing on the
canvas is not possible at this width, with or without the YAML panel") — a pre-existing constraint of the
embedded editor at phone width, not something this pass's changes touch, and not attributed to 1.30.37.
Reported as a gap, not a failure.

## Console / page errors

Zero real console errors and zero page errors across every context in this pass. Two *handled* HTTP 409
entries (both expected `ssh-check-all` refusals, see above) were excluded from the error count by the same
`HANDLED` prefix rule `check_release_1_30_36.py` uses.

## Limitations

- D2's per-device "Test login" (the single-node path) was **not** independently re-verified for host1 in
  this pass; the finding above is about the **bulk** "Test logins" action only. The lead should confirm
  whether the per-node route also needs the same fix, or whether it already works (code inspection
  suggests it does, since it has no `enabled` gate).
- The B3 "resize refits" check confirms the fit routine reruns and the content still fits; it does not
  prove the numeric `viewBox` values are recomputed from a different content bbox, because the dialog's
  content does not change size when the window is resized (see note in the B3 section) — recorded as
  such rather than overclaimed.
- C4's link-drawing step is unverified at 390×844 for the reason given above (editor palette layout, not
  attributable to this release).
- B5's "banner visible → dismiss → survives reload" cycle was confirmed from an earlier run in this same
  session rather than the final run, because the underlying condition (another operator's failed save)
  resolved between runs; both observations are reported with their timestamps rather than merged into one
  claim.
