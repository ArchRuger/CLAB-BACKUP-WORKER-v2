# Defect ledger

One entry per finding, in the campaign's shape: id and severity, affected coverage IDs, build and
browser, setup and steps, expected, observed, reproducibility, evidence, impact, root cause, files
changed, regression test, deployed build, author retest, independent retest, disposition. Severity:
P0 wrong-device/lab mutation or data loss; P1 broken core task, silent semantic loss, false success;
P2 workflow, validation, accessibility, race, recovery or performance defect; P3 polish that materially
reduces clarity. `Disposition` is one of open, fixed (awaiting independent retest), closed,
not-a-defect (with the reason), or blocked.

| ID | Sev | Area | Summary | Disposition |
|---|---|---|---|---|
| QA-001 | P2 | Design state line | "No design yet" is shown for a saved design that has no plan yet (identical text, pill and detail for an empty lab and a saved-but-not-generated design) | fixed, awaiting independent retest |
| QA-003 | P1 | Design guided form | Any guided edit rebuilt `addressing` from the three visible pools, silently dropping `vrf_loopback`, `router_id` and pool keys such as `start`/`allocation` (probe P1) | fixed, awaiting independent retest |
| QA-004 | P1 | Design guided form | The single route-reflector select collapsed a design with several reflectors to one on any unrelated guided edit (probe P2) | fixed, awaiting independent retest |
| QA-005 | P2 | Advanced editor | Text that did not parse left the last good intent in force: Save/Check/Generate acted on it while the screen showed the broken text, with no message that the edit was discarded (probe P3) | fixed, awaiting independent retest |
| QA-006 | P1 | Generate / Download | Generate and Download design file used the last saved revision while the form showed unsaved changes and the header said "Unsaved changes" next to a fresh plan built from old values (probe P4) | fixed, awaiting independent retest |
| QA-007 | P1 | Cross-lab identity | A save (or validation) answered after the student moved to another lab repainted that lab's Design tab with the first lab's design (probe P5) | fixed, awaiting independent retest |
| QA-008 | P2 | Plan card | A delayed plan fetch for an older generation replaced the newest plan's body while header, download and history still pointed at the newest (probe P6) | fixed, awaiting independent retest |
| QA-009 | P2 | Progress polling | One failed poll stopped the watch for good with no retry and no message; only the unrelated 4 s heartbeat happened to restart it (probe P7) | fixed; browser retest `tools/check_design_poll_retry.py` 9/9 (one injected 500 → "attempt 1 of 5", plan still completes; six failures → *Plan progress unknown*, no further polls for 15 s, Generate again loads afresh) |
| QA-010 | P2 | Drafts | A draft the browser could not store (quota, private window) vanished on reload without any acknowledgement, while a stale draft did get a message (probe P8) | fixed, awaiting independent retest |
| QA-011 | P2 | History / Remove design | After Remove design the header still read "Plan ready to review" and the plan card presented the removed design's plan as current; earlier plans were unreachable once a newer one existed (probe P9) | fixed, awaiting independent retest |
| QA-012 | P2 | Guided form | `0` or a blank BGP AS became 65000 and a blank prefix became 31/24 silently; a module checkbox unticked by hand stayed unticked through a Save although the module was on (probe P10) | fixed, awaiting independent retest |
| QA-013 | P2 | Capture dialog (pre-existing, every Junos and IOS XR device) | *Capture traffic…* opened from a device compared the diagram's port names (`ge-0/0/0`, `et-0/0/0`, `Gi0/0/0/0`) with the VM's container interface names (`eth1`…), so on vJunos-switch, cJunosEvolved and XRv9k no port was ever recognised: "Diagram ports … were not found on the VM", no *Connected interfaces* list, the student picks from everything. Not restart-related (first seen in the cJunosEvolved run; reproduced on vJunos-switch and XRv9k without any restart, `evidence/restart/…capture…`) | fixed, awaiting independent retest |
| U-01 | P1 | Design form / lab switch | With a form field focused, switching lab by URL (browser Back) kept the previous lab's form on screen under the new lab's header; Save then wrote the previous lab's design into the new lab (usability review) | fixed, awaiting independent retest |
| U-02 | P2 | Restart device review | Focus dropped to the page body after Cancel/Escape on every path; from the device panel the panel was closed and not restored | fixed, awaiting independent retest |
| U-03 | P2 | Shared operation dialogs | The Restart review, Renumber, Remove design and file view dialogs had no accessible name | fixed (every `opDialog` is labelled by its heading) |
| U-04 | P2 | Design form | Role, link VRF/VLAN selects, pool size inputs, the Advanced textarea and per-row fields had no accessible names; the trunk field was named by its placeholder "red,blue" | fixed |
| U-05 | P2 | Apply review | No sign of work for up to a minute, then focus and scroll position lost when the review appeared | fixed (busy button text and `aria-busy`, focus on the review heading, scroll reset) |
| U-06 | P2 | Apply review | A review with no reachable device showed a raw exception name, Apply stayed disabled without a reason, and there was no Cancel | fixed (plain-words reason, a summary line, the reason under Apply, Cancel) |
| U-07 | P2 | Design tables | Remove dropped keyboard focus to the page body | fixed (focus goes to the table's Add button) |
| U-08 | P2 | More menu at 390 px | The menu opened off the left edge; four items were cut off | fixed (`menu-clamped`: a list that would overflow anchors to its button; every shared menu) |
| U-09 | P2 | Device panel | The reason *Restart device…* (and *Back up configuration*) was disabled lived only in `title` | fixed (a visible line under the actions) |
| U-10 | P3 | Design head | Generate plan was the enabled primary action on an empty design and only toasted "Save a design first." | fixed (disabled with the reason; the guidance names Save) |
| U-11 | P3 | Generated files caption | "Applying them to devices is not available yet." contradicted Apply to devices | fixed |
| U-12 | P3 | Design state line | Every state was read twice (pill and text) | fixed (the pill is decorative for assistive technology) |
| U-13 | P3 | Module settings | A module's settings appeared far below its checkbox | improved (the module list is a grid, the settings sit right under it as a row); not moved under each checkbox |
| U-14 | P3 | Advanced editor | 182–197 px wide at 1366 px | fixed (full width) |
| U-15 | P3 | Plan warnings | Folded with no count under a green state | fixed (`Warnings (n)`) |
| U-16 | P3 | Plan card reasons | Loose reason lines not tied to their buttons; one duplicated | fixed (`aria-describedby`; a shared reason is said once) |
| U-17 | P3 | Lab-wide restart | *Restart devices* differed from *Restart device…* by one letter; the two reviews described one mechanism differently; the CLI disconnect was said twice | fixed (*Restart all devices…*, one consistent review, the disconnect said once) |
| U-18 | P3 | Restart device banner | An unavailable action gave the generic "That did not work" headline with the reason folded away | fixed (the reason is the headline) |
| U-19 | P3 | Button names | File buttons were all "View"; Details buttons were named by the container name | fixed |
| U-20 | P3 | Renumber / Remove design | Neither dialog said what cannot be undone or what happens to configured devices | fixed |
| U-21 | P3 | Guided form | A module the design still needs (vrf with VRFs defined, vlan with VLANs, routing with static routes) bounced back to ticked without a word when unticked (found by the final probe rerun: the P10 script could no longer untick the box) | fixed (`designKeptModulesNotice`: a notice says why it stays on) |
| QA-014 | P1 | Restart device outcome | On vJunos-switch the restart command succeeded while the container exited 0.2 s after starting (the image's launcher cannot start a second time); the job read *succeeded · 3 links restored* and only the device list later contradicted it (false success, live run 14:47 UTC) | fixed, awaiting independent retest |
| RD-001 | P2 | Restart device (pre-release) | A lab-wide lifecycle job confirmed from another tab while a Restart device review was still asking the helper did not make that review stale (its stamp was taken after the helper round trips) | fixed, awaiting independent retest |
| RD-002 | P3 | Restart device (pre-release) | The uptime hint for restarts done outside the manager measured the container start from the end of the discovery pass, so a slow pass could turn a valid login proof into a spurious "restarted" re-check | fixed, awaiting independent retest |
| RD-003 | P3 | Restart device (pre-release, defence in depth) | The helper accepted any container name ending in `-<node>`, so a request that bypassed the manager could bind `switch` to `…-vjunos-switch` (never reachable through the manager, which requires the exact name) | fixed, awaiting independent retest |
| RD-004 | P3 | Restart device (pre-release) | The map menu's *Restart device…* carried `class="danger"` without a matching rule, so it was not red; an older helper without the capability left the action enabled until the server refused; a page-supplied `path` was accepted for the action; a brief *Ready* could show between the job turning succeeded and the second readiness invalidation | fixed, awaiting independent retest |
| QA-015 | P2 | Design loads (race) | Two overlapping loads of the same lab's design (`designLoad`, the progress poll) were guarded only by lab identity: an older answer delivered after a newer one painted the older generation list and plan over the newer one (stress pass 2b, fault injection: 20/20 replays) | fixed; retested with the same replays on the fixed tree: 0/20 stale-wins, 80/80 checks (15:50 UTC) |
| QA-016 | P2 | Design validation | The manager accepted VRF, VLAN, pool, named-prefix and policy names of up to 64 characters while netlab types them as 16-character identifiers, so a saved name failed only at Generate plan with the engine's raw schema message (stress pass 5, B1) | fixed; retested with the stress tool's pass 5 on the fixed tree against the real engine: a 17-character name refused at Save with the 16-character words, a 16-character one saved and generated, 43/43 checks (15:52 UTC) |
| QA-017 | P1 | Restart device outcome (XRv9k) | The first Restart device of an XRv9k after a deploy brought the device back *Ready* with its factory configuration: the loopback, the OSPF process and the interface addresses committed three minutes earlier were gone, the traffic probe's path through it never recovered, and the product had said nothing about it (live run 15:29 UTC). Cause in the image: its launcher picks the VM disk by sorted file name at every start and a second copy of the pristine image sorts first after the first start | fixed (known limit named in the review, guide, parity record); retest on the final build pending |
| QA-018 | P1 | Restart device with a neighbour down | Restarting XRv9k while its neighbour vJunos-switch was exited restored 1 of its 2 links (containerlab cannot restore a link whose other end is gone); the image's launcher then waited for its second interface and never launched the VM, so the device stayed at *Starting* for good while the job read *succeeded · 1 link restored* and the review had said nothing (live 16:00 UTC) | fixed (the review names the neighbour and both cases, parked link versus destroyed link; the job reports n of m links when fewer came back); live in both cases on the final build |
| QA-019 | P2 | Readiness after a restart (XRv9k) | During every XRv9k restart the device read red *Needs attention*, "SSH login failed with the saved credentials", for 1.5–4.5 min before *Ready*: XR's SSH answers before it accepts any login, and three refusals in a row read as a credentials failure (found by acceptance pass 2, F-2; present in all seven XRv9k records) | fixed (a login grace window after a manager-driven restart, start or deploy); live retest on 1.30.49 |
| TOOL-002 | — | Live check assertions | `check_restart_device.py`: "the command names exactly one --node" could not fail (operator precedence) and "went back through Starting" ignored a `failed` state between Starting and Ready, which is how QA-019 slipped through (acceptance pass 2, F-4) | fixed (exact argv assertion; a new check refuses any `failed` between Starting and Ready) |
| TOOL-003 | — | Probe script and whitespace | The probe script committed in `b4329d3` had three stale bug-side assertions (pass 1 F1, pass 2 F-3; corrected in the working tree before pass 2 ran); `git diff --check` flagged trailing whitespace in three evidence files of that commit (pass 2 F-1) | fixed in the evidence commit (files normalised; the staged tree is checked with `--cached` before every commit from now on) |
| QA-020 | P3 | Restart device, a second tab's stale review | A second tab confirming an older review right after another tab's restart of the same device was told "Wait for the current lab operation to finish." instead of "Another lab operation ran after this review. Review the restart again.": `confirm()` checked the busy guard, which the executor holds through its follow-up discovery refresh after the job already reads *succeeded*, before the consent checks (acceptance pass 4, F1; 3 of 3 runs on the recovered VM, where that refresh took 5–8 s) | fixed in 1.30.50 (consent checks before the guard, unit test); live retest on 1.30.50 |
| QA-021 | P0 | Design tab, Remove design and Renumber across a lab change | A *Remove design…* (or *Renumber…*) dialog opened in one lab stayed open when the browser went Back to another lab, and confirming it acted on the first lab while the second was shown: with the same design in both labs (the revision hashes the content) *Remove design* silently deleted the first lab's design (acceptance pass 8, F-1; reproduced twice on the fixture) | fixed in 1.30.51 (a lab change closes every lab-bound dialog; the two dialogs act only for the lab they were opened from, with its revision at open time; unit tests); fixture retest on 1.30.51 |
| TOOL-004 | — | Two-tabs live check | `check_restart_two_tabs.py` aborted with an unhandled Playwright timeout, writing no record, when the device menu's *Restart device…* entry stayed disabled after the stale-review step (pass 4's first run and the first 1.30.50 retest): the menu had been opened while the tab's last state poll still showed the finished job as running (OBS-004) | fixed (the later steps are guarded, a stuck control is a failed check with the record kept, and the tool waits for the tab's own `busy()` to clear before it reopens a menu, recording the wait) |
| OBS-003 | — | Acceptance charter, not the product | Pass 4's F2: a `POST /api/operations/preview` without an `Origin` header is accepted (200, token). The charter written for the 1.30.49 passes demanded a 4xx there; the product's contract (CLAUDE.md, `main.py` `guard`, every unit test that posts) refuses a *mismatched* `Origin` or `Sec-Fetch-Site: cross-site`, which is what a browser sends, and never required the header. The criterion was corrected for the following passes | not-a-defect (charter error, recorded) |
| OBS-004 | — | Device menu opened while busy | The map's device menu is rendered when it opens (`openNodeMenu`) and not again while it stays open; opened in the few seconds after a restart job while the tab's last 4 s state poll still showed that job running, its *Restart device…* entry reads "Wait for the current operation to finish" until the menu is closed and reopened, although the manager is idle. Seen by the live tool (pass 4's first run, the first 1.30.50 retest), never by a student in the campaign | recorded, not changed (the reason was true when the menu opened; reopening refreshes it) |
| OBS-005 | — | Probe driver's exit status | `tools/probes/design_probes.py` always exits 0, although its docstring promises 1 when a check recorded FAIL (acceptance pass 5, observation). Its CONFIRMED-target checks are *meant* to fail on the fixed build, so the printed PASS/FAIL lines, not the exit status, are what every pass reads | recorded, not changed (the docstring's promise is the misleading part; a later tooling pass may make the exit status mean "a CONFIRMED-target check passed") |
| TOOL-005 | — | Two-tabs live check, again | TOOL-004's guard covered only the steps after the stale review; step 1 (the two reviews) was outside it, so the tool still crashed without a record when another lab's operation kept the manager busy (acceptance pass 6, F-1: the maintainer's own `Quick-Test` lab was being destroyed and deleted on the manager at that moment, `acceptance/pass-6/two-tabs-run1-crashed.log`) | fixed (one guard around every step, an idle wait of both tabs before the first step, the waits recorded); retest `evidence/restart/two-tabs-host1-2026-09-28T010451+0000.json` 13 of 13, waits 0.0 s |
| OBS-006 | — | Traffic probe while a target is down | `tools/traffic_probe.py` logs `crossing_loss: null` while a target does not answer at all (ping prints no statistics), so a summary that reads `null` as clean shortens an outage (pass 6, O-3: one 00:24–00:26 outage would end at 00:25:04). Every pass's loss windows were read by hand from the rows | recorded, not changed |
| OBS-007 | — | Refusal wording of an empty body | A zero-length `POST /api/operations/preview` is refused with 413 and "Upload limit is 2.5 MB per request; content length is required.": the refusal is the documented guard (CLAUDE.md), the words are about upload size (pass 6, O-4) | recorded, not changed |
| OBS-001 | — | Generation time near the retention cap | Generation of an unchanged 300-VRF/300-VLAN design took about 4 s instead of about 2 s once the lab held close to 20 retained generations (stress pass 5, B2). Every generation completed and the pruning was exact; no student design is that size. Recorded, not changed | not-a-defect (observation) |
| OBS-002 | — | Heartbeat in a hidden tab | The manager's 4 s `refresh()` heartbeat runs at the same rate whether the tab is hidden or shown (stress pass 4). A shipped manager behaviour outside the netlab work, harmless at one request per 4 s; recorded for the maintainer | not-a-defect (out of scope) |
| TOOL-001 | — | Older browser tools | `check_ui005.py`, `check_ui007c.py` and `check_ui008a.py` (UI review 001, last touched 1.30.39) fail identically on this tree and on the untouched HEAD checkout (3194ec4) on a fresh fixture: stale expectations of that stream's tooling, not a regression of this campaign. Recorded in `EVIDENCE.md`; `verify_after.py` and `student_workflow.py` pass on this tree | not-a-defect (pre-existing tooling debt) |
| QA-002 | P3 | Design More menu | Download design file, Import design file…, Renumber and Remove design are never disabled with a reason on the client although their routes refuse (404 without a design, 409 while generating); Apply and Export plan to Git do show reasons | fixed, awaiting independent retest |

## QA-001 — "No design yet" after a saved design

- **Coverage:** ND-STATE-001, ND-SAVE-004. **Build:** 1.30.47 working tree, fixture manager, Chromium 153.0.8010.12.
- **Setup and steps:** open a lab's Design tab, tick OSPF, Save design (succeeds, no problems). Read the
  state line (`#design-state-pill`, `#design-state-text`, `#design-detail`).
- **Expected:** the line says the design is saved and no plan has been generated yet (the campaign's own
  rule: no "No design yet" after a confirmed saved design merely because no plan exists).
- **Observed:** byte-identical "No design yet" pill, text and detail for the empty lab and for the lab
  with a saved OSPF design (inventory run, `dom_states_full.json` "empty" vs `dom_states_apply_export.json`
  "ae_saved"). Only the ticked module checkboxes tell the two apart; a screen-reader user hears the same.
- **Reproducibility:** every time. **Impact:** a student cannot tell whether Save worked from the
  status line; no data loss.
- **Root cause:** `designStateOf()` (network-design.js) fell through to the `none` state whenever no
  generation existed, without looking at `view.intent` (the saved design the view carries).
- **Fix:** a `saved` state ("Design saved, no plan yet", neutral pill, detail pointing at Generate plan)
  ahead of `none`, taken only when `view.intent` is set; draft, problems, generating and every plan state
  still win. `docs/NETWORK-DESIGN.md` names the new word.
- **Regression test:** `tests/test_network_design_ui.js` "designStateOf: a saved design with no plan yet is
  not "No design yet"" (saved → `saved`; no intent → `none`; draft and a plan still win).
- **Author retest:** unit (66/66). Deployed build and independent retest: pending the next deploy.

## U-21 — an unticked module bounced back without a word

- **Found**: the final rerun of the ten probes on the 1.30.48 tree (17:24 UTC): probe 10's `uncheck()` of the vrf module refused ("Clicking the checkbox did not change its state") because, since QA-012, the box is redrawn from the draft and `designIntentFromForm` keeps vrf on while a VRF is defined. Correct data, silent screen.
- **Fix**: `designKeptModulesNotice(ticked, modules)` in `network-design.js`; `designOnGuidedChange` shows it: "The vrf module stays on while VRFs (or links in a VRF) are defined; remove them to turn it off." (vlan and routing alike).
- **Regression test**: `tests/test_network_design_ui.js` "U-21: designKeptModulesNotice …". The probe script clicks instead of asserting the untick.
- **Disposition**: fixed.

## QA-002 — More menu items without a client-side reason

- **Coverage:** ND-EXPORT-001, ND-IMPORT-001, ND-RENUMBER-001, ND-CLEAR-001. **Build:** as above.
- **Observed:** the four items carry the house-style `<small class="menu-reason">` markup but are never
  disabled; clicking Download design file on a lab without a design opens a 404 in a new tab
  (`window.open`), Import/Renumber/Remove fail only after the request.
- **Expected:** a disabled item with its reason underneath, the way Generate plan, Apply to devices…
  and Export plan to Git… already explain themselves.
- **Root cause:** `designRenderHeader()` computed a reason for Generate plan only; the four More-menu
  items were wired straight to their handlers.
- **Fix:** `designMoreMenuReasons(view, st)` (pure) returns `[id, reason]` for the four items, mirroring
  the routes' own refusals (no saved design → export/renumber/remove; a plan being generated →
  import/renumber/remove); `designRenderHeader()` applies disabled, title and the visible `menu-reason`.
- **Regression test:** `tests/test_network_design_ui.js` "the More menu items carry the reason the route
  would refuse, and none otherwise" (the table for none/saved/generating, and the header applying it).
- **Author retest:** unit (66/66). Deployed build and independent retest: pending the next deploy.

## RD-001 … RD-004 — Restart device, found by the independent Opus review before release

- **Source:** the `risk-reviewer` (Opus) pass over the Restart device diff (2026-09-27, 14:00 UTC), with
  reproducers for RD-001 (a fixture whose helper fake appends a `restart` job during the restart-node plan
  call: confirm returned 200) and RD-002 (`restarted_since()` with `checked_epoch` 122 s after a proof taken
  1.5 s after the start: True). No must-fix finding; no privilege widened; no existing test weakened.
- **Fixes:** RD-001 — the review stamp is taken under the first lock right after `guard()`, and the preview
  itself is refused (409) when a lifecycle job appeared while it was being prepared. RD-002 — discovery
  records `inspected_epoch` before `inspect_host()` and `restarted_since()` derives the start from it
  (falling back to `checked_epoch`). RD-003 — `node_selector(options, lab)` accepts only
  `<prefix>-<lab>-<node>`, `<lab>-<node>` or `<node>`. RD-004 — `.node-context-menu button.danger` rules;
  `opRestartState` requires `available === true` once capabilities are loaded; `path` refused (400) for
  `restart-node`; `invalidate_readiness()` also right after `remote()` returns.
- **Regression tests:** `test_lab_operations.py` "…stale_when_a_lifecycle_job_lands_during_its_own_helper_calls",
  "…binds_every_container_naming_shape_exactly", the extended bad-selector list; `test_node_readiness.py`
  (the slow-pass reproducer, unconditional assertions); `test_operations_ui.js` (older helper).
- **Retest:** unit suites green; the independent retest is the acceptance pass on the released build.

## QA-003 … QA-012 — the ten §6 probes (`probes-report.md`, `tools/probes/design_probes.py`, `evidence/probes/`)

- **Reproduction:** every hypothesis reproduced in Chromium 153.0.8010.12 against the fixture manager (real
  engine) on 2026-09-27, 58/58 probe checks, screenshots per step; the report names the source lines.
- **Root causes and fixes** (`network-design.js` unless said otherwise):
  - QA-003 — `designIntentFromForm` replaced `intent.addressing`; it now merges into the stored pools
    (`ipv4`/`ipv6` and, where the form has one, `prefix`), keeping every other key and pool.
  - QA-004 — the reflector control is a checklist (`designReflectorMarkup`, `#design-bgp-rr` fieldset in
    `index.html`); the form values carry the checked set and the shown set (`bgpRrKnown`), so routers the
    checklist does not show keep their flag and several reflectors survive any edit.
  - QA-005 — `designOnAdvancedChange` records `advancedInvalid`; the state line reads *Advanced JSON is not
    valid*; `designAdvancedBlocked()` refuses Save/Check/Generate; the textarea is never overwritten while
    invalid; *Discard changes* clears it.
  - QA-006 — `designGenerate` saves unsaved changes first (quiet save, then "Design saved. Generating the
    plan…") and only then generates from the saved revision; the More menu's Download design file and Import
    design file… carry a reason while changes are unsaved; a new *Discard changes* button offers the way back.
  - QA-007 — `designSave`, `designValidate`, `designGenerate`, `designRenumber`, `designClearDesign` and
    `designImportFile` capture the lab id and apply nothing (no state, no DOM, no toast) once
    `designState.labId` differs.
  - QA-008 — `designLoadPlan` applies a plan only if its generation is the one shown (`designPlanWanted`);
    History rows gained *View*, the plan card a *Back to newest plan* control (`designViewGeneration`,
    `designViewedGeneration`); files and the download follow the shown generation.
  - QA-009 — the watch retries up to `DESIGN_POLL_RETRIES` (5) with backoff and a visible "attempt n of 5"
    detail, then stops for good (`pollGaveUp`, state *Plan progress unknown*, the render never restarts it);
    Generate again or reopening the tab loads afresh.
  - QA-010 — `designSetDraft` reads `writeDesignDraft()`'s answer; a refused write reads as a red
    *Unsaved changes* with "could not be kept in this browser" and the advice to save now.
  - QA-011 — `designStateOf` has the *No design saved (earlier plans kept)* state ahead of the plan states;
    the plan card says a plan belongs to a removed design; History › View reaches every kept plan.
  - QA-012 — no numeric coercion (`designNumberOrRaw`; the form shows what is stored); `design_intent.py`
    gained `_check_bgp_as()` (1 to 4294967295, globally or per device, one problem per field); every render
    syncs the module and reflector checkboxes' live `checked` from the values (`designSyncChecked`).
- **Regression tests:** `tests/test_network_design_ui.js` P1…P10 (one per probe, 77 tests in the file);
  `tests/test_design_intent.py` `test_bgp_as_must_be_present_and_in_range`; the six pre-existing tests that
  pinned the old behaviour were rewritten to the new claims (plan states presuppose a saved design; the
  reflector value is an array; an empty intent shows an empty AS field).
- **Retest:** unit suites green; the probe driver is rerun against the fixed build during acceptance.

## U-01 — the previous lab's form saved into the new lab (usability review, 2026-09-27)

- **Reproduction (Chromium and Firefox):** lab A saved with BGP AS 65123; click into a pool field on A; browser
  Back to lab B; header and state say B, the form and Advanced JSON show A; change one field, Save → "Design
  saved." and B holds A's modules, AS and area (`evidence/usability/`, `manual-09-…`, `firefox-D10-…`).
- **Root cause:** `designRenderForm()` skipped every rewrite while `designFormFocused()` was true, also when
  `designState.labId` had just changed; `designOnGuidedChange()` then read the stale DOM as the new lab's edit.
- **Fix:** `designState.formLab` records the lab the form was drawn for; when it differs from the open lab the
  form is redrawn whatever has focus (the focused field is blurred first); `designOnGuidedChange()` refuses to
  build an intent from a form drawn for another lab and redraws instead.
- **Regression test:** `test_network_design_ui.js` "U-01: when another lab's design arrives, the form is
  redrawn even while a field has focus, and a stale form is never saved into the new lab".

## U-02 … U-20 — the usability review's findings (`usability-report.md`, `evidence/usability/`)

- **Source:** the independent Opus usability/keyboard/responsive/axe review of 2026-09-27 (Chromium 153,
  Firefox 155; WebKit could not launch on this VM for want of system libraries).
- **Fixes** (`operations.js`, `shell.js`, `app.js`, `network-design.js`, `index.html`, `style.css`):
  `opDialog(id, title, body, opener)` names every dialog by its heading and returns focus to its opener when
  it closes; `handleNodeAction` keeps the device panel open under the review and passes the button (or the
  drawn device, from the map menu) as the opener; `nodeActionNotes()` puts disabled reasons in words under the
  panel's actions; the shared `initMenu` adds `menu-clamped` when a list would open past the left edge;
  `shellErrorSentence` keeps "Restart device… is not available: …" as the headline; the lab-wide action is
  *Restart all devices…* with a review that describes the same mechanism as the one-device review; every
  Design row control carries an `aria-label`; `designFocus()` after Remove; Generate plan is disabled with a
  reason on nothing; the warnings summary carries its count; the plan card's buttons name their reasons; the
  apply review shows "Reviewing n devices…", lands on its heading, explains an empty review, names why Apply
  is off and has Cancel; Renumber and Remove design say what cannot be undone; file and Details buttons are
  named after the file and the device; the state pill is `aria-hidden`; the Advanced editor is full width and
  the module list a grid.
- **Regression tests:** `test_operations_ui.js` (dialog name and focus return, the lab-wide review copy, the
  banner reason), `test_readiness_ui.js` (panel stays open and hands the opener over; the reasons line;
  Details naming), `test_shell_ui.js` (menu clamp), `test_network_design_ui.js` (row names, Generate reason,
  warnings count, shared reason said once, apply review summary and reasons, Remove focus).
- **Not done:** U-13 in full (settings under each checkbox) — the grid keeps them one row below the list.

## QA-017 — an XRv9k comes back from its first restart with its factory configuration

- **Coverage**: Restart device on `cisco_xrv9k` (`NODE-RESTART` live rows), both entry points.
- **Build**: 1.30.47 working tree deployed on the dev VM (rebuilt 15:16 UTC), containerlab 0.79.0, `n24l/cisco_xrv9k:24.3.1`.
- **Steps**: deploy the lab (15:15 UTC), apply configuration A to xrv9k (committed 15:26:25), *Restart device…* from the map (job 15:29:19–15:29:28, exit 0, `2 links restored`, same container id), wait for *Ready* (15:40:37), then look at the device.
- **Expected**: the device reboots and comes back with the configuration it had (what a reboot means to a student, and what cEOS and cJunosEvolved did in their runs: the cEOS saved marker survived, the path through cJunosEvolved recovered after each of its restarts).
- **Observed**: `show running-config interface Loopback0` → *No such configuration item(s)*; both GigabitEthernet interfaces `Shutdown`/unassigned; no OSPF neighbours; the independent probe (`traffic_probe.py`, cEOS → 10.255.0.4) lost the path at 15:29:22 and never saw it again through the second and third restarts (`evidence/restart/xrv9k-traffic-from-ceos.jsonl`). The product's 75 checks all passed: the job, the links, the identity of the container and the readiness were all as designed, and the review carried no warning.
- **Reproducibility**: deterministic by construction (below); one live occurrence, the first restart of the container.
- **Root cause (image, read in the running container)**: `/launch.py` of the image chooses the VM disk with `for e in sorted(os.listdir("/")): if re.search(".qcow2", e)` and vrnetlab creates `<disk>-overlay.qcow2` for whatever it chose. The pristine image ships only `xrv9k-fullk9-24.3.1.qcow2`; at the first start the VM wrote `xrv9k-fullk9-24.3.1-overlay.qcow2` (last write 15:29, configuration A inside). By the second start a hard link of the pristine disk named `clab-24.3.1.qcow2` existed in `/` (same inode; who adds it is not determined) and sorts first, so the launcher created a fresh `clab-24.3.1-overlay.qcow2` (15:29–15:40) from the pristine image: the device booted factory-fresh, and the first overlay was orphaned. The third and fourth starts chained on that new overlay (`…-overlay-overlay.qcow2` 15:40–15:46, `…-overlay-overlay-overlay.qcow2` from 15:46), so what is configured after the first restart is kept from then on (proof below). The stop is a plain `sys.exit(0)` on SIGTERM (no guest shutdown), which is not what lost the data here: the disk that held it was simply not the one booted.
- **Impact**: P1, silent loss of everything a student configured on the device since the deploy, with a *succeeded* job and a *Ready* device; the same happens with the extension's *Restart node* (same command).
- **Fix (manager)**: `RESTART_KNOWN_LIMITS['cisco_xrv9k']` in `lab_operations.py`: the review names the limit before the student confirms (fresh disk on the first restart after a deploy, factory configuration, back up first and use *Replace running configuration* afterwards); `docs/LAB-OPERATIONS.md` and `RESTART-PARITY.md` (matrix and per-image row) say the same. The manager cannot detect the loss itself (the device answers its login as before), and a restart stays what the extension does: no automatic backup or restore is added.
- **Regression test**: `tests/test_lab_operations.py` `test_the_xrv9k_review_names_the_fresh_disk_limit_and_other_kinds_get_no_note`; `tools/check_restart_device.py` now asserts the known-limit note per image (present for vJunos-switch and XRv9k, absent for the others) and keeps every review text in its record.
- **Live proof of the later restarts**: attempted 15:59–16:22 (configuration A reapplied on the factory-fresh fourth boot, one restart from the map); the restart itself succeeded (`xrv9k-2026-09-27T160044+0000.json`) but the VM never booted because a neighbour was exited (QA-018), so the read-back could not run. The disks tell the rest: the fifth start chained a new overlay (`…-overlay-overlay-overlay-overlay.qcow2`, 197 KiB) on the fourth boot's disk, which holds the configuration applied at 15:59; what is configured after the first restart therefore stays on the disk the later boots use. Re-proven with a read-back on the redeployed lab: **proven on the final build**: configuration A applied at 17:17:43 and read back on the device (Loopback0 present) before the restart; one restart from the map at 17:19 (record `xrv9k-2026-09-27T171848+0000.json` (27/27, the review named the limit; job 17:18:53–17:19:26, `2 links restored`, *Ready* 17:24:27)); read-back at 17:25: `interface Loopback0 … ipv4 address 10.255.0.4`, OSPF FULL with 10.255.0.3 and 10.255.0.1, Loopback0 Up; the disk listing shows the boot chained a new overlay on the previous one (`…-overlay-overlay-overlay-overlay.qcow2` on `…-overlay-overlay-overlay.qcow2`). So only the first restart after a deploy loses the configuration; what is configured after it survives the next restarts.
- **Disposition**: fixed; the review note is to be seen live on the final build (the deployed manager of the run predates it: `evidence/restart/preview-warnings-1553.json` shows the API preview of 15:53 with the vJunos-switch note present and the XRv9k warnings empty).

## QA-018 — a restart with a neighbour down leaves a VM-based device waiting for its link

- **Coverage**: Restart device, any image; the consequence is worst for VM-based images (vrnetlab launchers wait for every provisioned interface before starting the VM).
- **Build**: 1.30.47 working tree deployed on the dev VM (rebuilt 15:16 UTC), containerlab 0.79.0.
- **Steps**: with vJunos-switch exited (after its own rerun, 15:53), *Restart device…* on XRv9k from the map (job 16:00:44–16:00:53, exit 0).
- **Expected**: the review says beforehand that the link to the exited neighbour cannot come back and what that means for the device; the job says how many of the device's links were restored.
- **Observed**: the review carried no such note; the job read *succeeded · 1 link restored*; the container came back with `eth0` and `eth2` only; the launcher logged "number of provisioned data plane interfaces is 2 … waiting for provisioned interfaces to appear…" and stayed there (`evidence/restart/xrv9k-1601-launcher-waits-for-links.txt`); the device read *Starting* until the 20-minute readiness budget ran out (`xrv9k-2026-09-27T160044+0000.json`, 26 checks, 4 failed: 1 of 2 links, `eth1` missing, no *Ready*).
- **Reproducibility**: deterministic: containerlab parks a link's veth on the node's stop and restores it on the start only while the peer's end still exists; an exited peer has no network namespace.
- **Impact**: P1: a device that never comes back with a *succeeded* job and no explanation; the same with the extension's *Restart node*.
- **Fix (manager)**: `restart_links(lab, short)` in `lab_operations.py` reads the device's dataplane links from the lab's drawing (parsed from the topology file) and the neighbours' runtime state; the review then names the neighbour and both cases, because the first live rerun on the final build showed they differ: a neighbour stopped with `containerlab stop --node` keeps its link ends parked in the host namespace and the restart restores every link (cEOS with host1 stopped that way, 16:49 UTC: `3 links restored`, all three interfaces back), while a neighbour that exited on its own (vJunos-switch's crash) or was stopped with `docker stop` took the link with it. Review text: "*<neighbour> is not running. If it was stopped by the manager, the VS Code extension or containerlab stop, its link to <device> is parked and comes back with this restart. If it exited on its own or was stopped with docker stop, that link is gone: containerlab restores only 1 of 2 links and the job says so, and a VM-based device then waits for all its interfaces before it boots and stays at Starting until <neighbour> runs again. Start <neighbour> first (Restart device… on it takes the start/restore path), then this device, or redeploy the lab.*" The counts travel with the review into the job: when fewer links came back than the topology has, the message reads "*1 of 2 links restored (no link to <neighbour>: not running, its link was gone; a VM-based device waits for it before it boots)*". A neighbour that is not a lab device (host, bridge) is counted but never named; a lab without a drawing gets no note; nothing is refused. The manager cannot tell the two cases apart itself (it sees no container interfaces), hence the two-case wording.
- **Regression test**: `tests/test_lab_operations.py` `test_a_neighbour_that_is_not_running_is_named_in_the_review_and_the_job_counts_the_links`.
- **Live** (`tools/check_restart_neighbour.py`, cEOS with host1, final build 1.30.48 of 17:17 UTC): parked case (`neighbour-ceos-containerlab-20260927T172520+0000.json`, 20 checks, 19 passed): the review named host1 and both cases, the API preview the same, the job read `3 links restored`, all three interfaces present, cEOS *Ready* 21 s later, host1 started through the product with `2 links restored`; the one failing check counted cEOS's own cpu/fabric/mirror interfaces as links (tool artefact, fixed: only `eth<n>@` ends count). Destroyed case (`neighbour-ceos-docker-20260927T172622+0000.json`, 20 checks, 18 passed): the job read **`2 of 3 links restored (no link to host1: not running, its link was gone; …)`**, host1's start read `no links restored (… redeploy the lab …)`, and cEOS did **not** come back within the 300 s budget: its init waited for the three interfaces containerlab told it to expect (`CLAB_INTFS=3`, "Waiting for 3 interfaces to be connected (timeout: 300s)", `evidence/restart/ceos-1727-waits-for-interfaces.txt`) and booted only after that timeout, so the wait is not a VM-only matter; the wording now says "the device waits for all its interfaces before it boots (cEOS gives up waiting after five minutes, a VM-based image waits for good)". The second failing check was the same count artefact. **Both modes rerun with the corrected tool after a redeploy on the final wording build (17:57 UTC)**: parked case `neighbour-ceos-containerlab-20260927T183741+0000.json` 20/20 (`3 links restored`, host1 back with `2 links restored`, all links present), destroyed case `neighbour-ceos-docker-20260927T183917+0000.json` 20/20 (`2 of 3 links restored (no link to host1: not running, its link was gone; the device waits for it before it boots)`, cEOS *Ready* again after the five-minute interface wait, host1's start `no links restored`, the lab redeployed afterwards); two-tabs `two-tabs-host1-2026-09-27T183839+0000.json` 13/13 in between.
- **Disposition**: fixed (review and job wording, unit test, live check).

## QA-019 — a false credentials failure while an XRv9k boots after its restart

- **Found by**: acceptance pass 2 (Opus, `acceptance/PASS-2-opus.md`, F-2), from the readiness timelines in the campaign's own records: every XRv9k restart went `booting → failed → booting → ready`, the `failed` window lasting 1.5–4.5 minutes (`xrv9k-2026-09-27T203626+0000.json`: 20:38:18–20:39:49, and all seven earlier XRv9k records). cEOS and cJunosEvolved never showed it.
- **What the student saw**: red *Needs attention*, "xrv9k is running, but SSH login failed with the saved credentials", with *Check credentials*, while the device was simply still booting; the guides promised "*Restarting*, then *Starting* until it accepts a login".
- **Root cause**: `node_readiness.py` maps `paramiko.AuthenticationException` to `failed`; three refusals in a row (`REFUSALS_BEFORE_FAILED`) become the reported failure. IOS XR answers SSH for minutes before its AAA accepts logins, so the count fills during a normal boot.
- **Fix**: a login grace window (`LOGIN_GRACE`, 15 min) after a restart, start or deploy the manager itself performed: `forget()` already records the epoch of the accepted operation; while the window is open a refused login reads *booting* with its own words ("SSH answers but the saved login is not accepted yet (a NOS accepts logins only late in its boot)"), and the refusal count starts only after it. Lab-wide lifecycle jobs (deploy, redeploy, start, restart) now `forget()` every device of the lab, so the window covers a deploy through the manager too. A device deployed outside the manager still gets the plain three-refusal rule (nothing tells the manager it just booted).
- **Regression tests**: `tests/test_node_readiness.py` (a refusal inside the window reads booting with the login message; after the window the three-refusal rule applies) and `tests/test_lab_operations.py` (a deploy job forgets every device). The live check now refuses any `failed` between *Starting* and *Ready* (TOOL-002).
- **Retest**: `evidence/restart/xrv9k-2026-09-27T205833+0000.json` on 1.30.49 (deployed 20:58 UTC): *Restart device…* from the map at 20:58:38 (`2 links restored`, same container), readiness `booting` from 20:58:48 straight to `ready` at 21:03:51 with no `failed` state in between (the strengthened check "no false credentials failure between Starting and Ready" passed); the configuration survived (Loopback0 read back before and after). 27 of 28 checks passed; the one failure was the tool's own new argv assertion, which read the review's prose and now reads the API preview's argv (TOOL-002).
- **Disposition**: fixed; retested live on 1.30.49.

## QA-020 — a stale second-tab review was told to wait instead of to review again

- **Found by**: acceptance pass 4 (Sonnet, `acceptance/PASS-4-sonnet.md`, F1) on 1.30.49, with `tools/check_restart_two_tabs.py` on host1: three runs (22:20, 22:21, 22:26 UTC), each failing the one check "the older review is refused with the reason" with the text "Wait for the current lab operation to finish." (`acceptance/pass-4/two-tabs-host1-2026-09-27T222121+0000.json`, `…T222644+0000.json`, `two-tabs-diag-run.log`). The same check had passed 13/13 in passes 1, 2 and 3 and in every campaign run before them.
- **Coverage**: Restart device, the second tab's stale consent (RD-001's confirm-time check).
- **Build and browser**: 1.30.49 deployed (recreated 22:02 UTC after the VM's crash), Chromium 153.0.8010.12.
- **Steps**: two tabs open a review for the same device; tab A confirms; when A's job reads *succeeded*, tab B confirms its older review.
- **Expected**: "Another lab operation ran after this review. Review the restart again.", the dialog stays open with the reason.
- **Observed**: "Wait for the current lab operation to finish."; the dialog stays open, nothing starts (no second job, no second restart: the stale consent was still refused, only the reason was wrong). In the first run the *Restart device…* entry then stayed disabled for more than 30 s and the tool aborted (TOOL-004).
- **Reproducibility**: timing. `LabOperations.execute()` marks the job *succeeded*, then in its `finally` runs `invalidate_readiness()`, the event and `discovery.refresh()` (a helper call to the VM) before it releases the `active` guard. `confirm()` called `self.guard()` first, so any confirm inside that window met the busy message, and the stale checks that would have given the right reason never ran. Before the crash the refresh took well under the tool's 1.5 s settle; on the recovered VM it took 5–8 s (pass 4's polling of `/api/state` showed the API idle while confirms were still refused as busy), which is why the same tool passed in the earlier passes and failed three times here. The window exists on every build since the feature; its length depends on the VM.
- **Impact**: P3. The stale consent is refused either way, so nothing is restarted twice and no state is touched; the student is told to wait for an operation they can see has finished, and would learn the real reason only on a retry. The contradiction with RD-001's documented wording is what made it a finding.
- **Fix (manager)**: `confirm()` in `lab_operations.py` runs the Restart device consent checks (same device and container, no lifecycle job of the lab since the review's stamp) before `self.guard()`. The guard is unchanged: new work is still refused while the refresh runs, and `active` is still released only after it (that refresh is what keeps the inventory consistent before the next operation).
- **Regression test**: `tests/test_lab_operations.py` `test_a_stale_restart_review_hears_the_stale_reason_while_the_previous_job_still_refreshes` (the guard held by hand after the job succeeded: the stale review hears its reason, a fresh review is still refused as busy, and once the guard is released a fresh review runs).
- **Retest**: live on 1.30.50 (deployed 23:17 UTC) with `check_restart_two_tabs.py` on host1: `evidence/restart/two-tabs-host1-2026-09-27T233946+0000.json` (the older review refused with "Another lab operation ran after this review. Review the restart again." at once, no second job, no second restart; the run's later step then stalled on a device menu opened while the tab's last state poll still showed the finished job as running, OBS-004, so the tool now waits for the tab's own idle) and `two-tabs-host1-2026-09-27T234527+0000.json`, 13 of 13 with idle waits of 0.0 s and 0.2 s. Then the acceptance passes that follow.
- **Disposition**: fixed; retested live on 1.30.50.

## QA-021 — a Remove design dialog acted on the lab it was opened from after the page had moved to another lab

- **Found by**: acceptance pass 8 (Opus, `acceptance/PASS-8-opus.md`, F-1) with its own fixture script `acceptance/pass-8/tools/adversarial_transitions.py` (T1, reproduced at 01:40 and 01:48 UTC on 2026-09-28; `adv8-T1-*.png`, `adversarial-transitions.json`).
- **Coverage**: the Design tab's More menu, *Remove design…* and *Renumber…*, across a lab change (browser Back, a link); the same class as U-01, which its fix did not cover.
- **Build and browser**: 1.30.50 (`02fd181`), fixture manager with the real engine, Chromium 153.0.8010.12.
- **Steps**: two labs hold the same saved design (identical content, so the same content-hash revision); open lab A's Design tab, then lab B's; More › *Remove design…*; press the browser's Back; the page shows lab A with the dialog still open; click *Remove design*.
- **Expected**: the dialog belongs to lab B; a lab change closes it, and a confirmation that still arrives does nothing and says so.
- **Observed**: the dialog stayed open over lab A, still reading "The saved network design for this lab is removed"; the confirmation removed **lab B's** design (the lab no longer shown), lab A kept its design, and nothing was said (`designClearDesign()` returned before its notice because the answer was not for the lab on screen). With different revisions the same stale dialog was refused by the server, with the wrong reason ("The design changed since this page loaded"). By the code the same held for *Renumber*.
- **Reproducibility**: deterministic when both labs share a revision (a class of identical starter designs makes this realistic).
- **Impact**: P0 by the ledger's scale: a change to a lab other than the one shown, with data loss (the saved design; plans and files stay). Nothing on a device is touched.
- **Root cause**: `selectLab()` and `applyRoute()` closed only the device drawer on a lab change; the two dialogs captured the lab when they opened but read the design revision from the view of the lab now on screen when confirmed, and the revision alone cannot tell two labs with the same content apart.
- **Fix (manager UI)**: `closeLabDialogs()` in `shell.js`, called by `selectLab()` and `goHome()`, closes the device drawer and every open `dialog[data-lab-dialog]` (the two design dialogs are marked when they open, the Apply and Export reviews in `index.html`); `designClearDesign()` and `designRenumber()` capture the lab id and revision when they open, send exactly those, and refuse to act once `designDialogStillForLab(labId)` is false (the design state or the lab on screen names another lab), closing the dialog with "The page moved to another lab while this dialog was open. Nothing was changed; open it again from that lab." The operation review (Restart, deploy, destroy) is bound to its lab by its token and names its lab and device; pass 8 judged it not a defect and it was left unchanged.
- **Regression tests**: `tests/test_network_design_ui.js` "QA-021: Remove design and Renumber act only for the lab they were opened from, with that lab's revision at open time, and are marked to close on a lab change"; `tests/test_shell_ui.js` "QA-021: a lab change closes every open dialog that speaks for a lab, and only those".
- **Retest**: the reviewer's script rerun unchanged against a fixture of the 1.30.51 tree at 02:03 UTC on 2026-09-28 (port 8198, fresh data, real engine): 12 of 12, including "T1 the Remove design dialog opened for A does not stay open over lab B" and "T1b the Renumber dialog closed on Back" (`evidence/design-dialogs/qa021-retest-2026-09-28T0203.json`, `qa021-retest-T1-*.png`). Then the acceptance passes that follow.
- **Disposition**: fixed in 1.30.51; retested on the fixture; the acceptance passes that follow.

## QA-015 — an older design answer painted over a newer one (stress finding R1)

- **Coverage**: the Design tab's loads and the progress poll (`designLoad`, `designMaybeStartWatch`), every lab.
- **Build and browser**: 1.30.47 working tree, fixture manager, Chromium 153.0.8010.12 (`evidence/stress/race-results.json`, pass 2b).
- **Setup and steps**: open a lab's Design tab; call `designLoad(labId)` twice for the same lab with the first answer held back (Playwright `route.fetch()` now, `route.fulfill()` later); between the two calls save and generate a newer plan through the API; let the second call's answer land, then release the first.
- **Expected**: the newer generation stays shown; an older answer that arrives late is dropped.
- **Observed**: the history and plan card showed the older generation as newest (20 of 20 replays, both lab identities).
- **Reproducibility**: 100 % under fault injection. Not reached by an unassisted click sequence in the campaign's other passes; it needs two in-flight reads whose answers cross, which a slow network can produce.
- **Impact**: P2, a stale view after a race; nothing is written wrongly (the equivalent save/plan-load race across labs, QA-007, was already guarded and stayed clean in 20/20 replays of pass 2a).
- **Root cause**: the loads compared only `designState.labId` after their `await`, so any answer for the current lab was applied whatever its age.
- **Fix**: `network-design.js` numbers every read of the design when it is sent (`designViewRequest`) and applies an answer only if nothing newer was applied since (`designViewFresh`); the poll re-arms itself when it drops a stale answer; a write (save, import, renumber, clear) marks everything sent before it stale (`designViewWritten`). The lab-identity guard stays.
- **Regression test**: `tests/test_network_design_ui.js` "QA-015: two overlapping loads …" (the older answer resolved last leaves the newer generation shown; a genuinely newer load still wins) and "QA-015: the lab-switch guard still holds …".
- **Retest**: `stress_design.py race --port 8112` on the fixed working tree, 15:43–15:50 UTC: race-a leaks 0/20, race-b stale-wins 0/20, 80/80 checks, no console or page errors (`evidence/stress/race-results.json`; the failing record of the first run is kept as `race-results-before-fix.json`).
- **Disposition**: fixed and retested (independent of the unit test: the same fault-injected replays that found it).

## QA-016 — names the manager accepted failed in the engine (stress finding B1)

- **Coverage**: the Design tab's VRF and VLAN tables, custom address pools, named prefixes, routing policies; Advanced editor and import.
- **Build**: 1.30.47 working tree, fixture manager with the real pinned netlab engine (`evidence/stress/bulk-results.json`, pass 5).
- **Steps**: save a design with a VRF named with 17 or more characters, then Generate plan.
- **Expected**: the manager refuses the name at Save with its own words.
- **Observed**: Save succeeded; the plan failed with the engine's "… must be a 16-character identifier, found str".
- **Root cause**: `design_intent.ID` allowed 64 characters wherever a name was checked, while netlab's `must_be_id` (netsim/data/types.py) caps every `id`-typed name at 16.
- **Fix**: `design_intent.py` gains `NAME` (netlab's rule: up to 16 characters, letters, digits and underscores, not starting with a digit) and `NAME_RULE` (the words), applied to VRF, VLAN and policy names, per-device VRF/VLAN names, trunk members, pool names (design and link), `id`-typed leaves and lists; setting keys keep the 64-character `ID`. The guided VRF/VLAN name inputs carry `maxlength="16"` and the matching pattern and title. `docs/NETWORK-DESIGN.md` states the rule.
- **Regression test**: `tests/test_design_intent.py` `test_engine_identifiers_follow_netlabs_16_character_rule`.
- **Retest**: `stress_design.py bulk --port 8113` on the fixed working tree with the real engine, 15:51–15:52 UTC: the boundary check's six assertions (a 17-character VRF name refused at save with HTTP 400 and the words "16 characters"; a 16-character name saved, generated and accepted by the engine) and the rest of the pass, 43/43 (`evidence/stress/bulk-results.json`; the first run's record is kept as `bulk-results-before-fix.json`).
- **Disposition**: fixed and retested.

## QA-014 — a restart that leaves the container exited read as a success (vJunos-switch)

- **Reproduction (live, 2026-09-27 14:47 UTC):** *Restart device…* on `vjunos-switch` (n24l/vjunos-switch:23.2R1.14):
  the job succeeded (`Operation completed · 3 links restored`), the container got a new start time and exited
  with code 1 within 0.2 s; `docker logs` shows the vrnetlab launcher failing on `open("init.conf")`, which
  the image renames to `juniper.conf` on its first start (`/launch.py` lines 60–110). The extension's own
  `containerlab restart --node` reaches the same point; only a redeploy recreates the node.
- **Root cause (product):** the job's outcome was the helper command's exit status alone.
- **Fix (`lab_operations.py`):** `settled_after_restart()` asks discovery again two seconds after a successful
  `restart-node` command; a container that is not running then makes the job **failed** with the state, the
  runtime's status line, the known reason for the image (`RESTART_KNOWN_LIMITS`) or a generic one, and the way
  out (Redeploy lab); `last_deployed` stays untouched. The review of a vJunos-switch names the limit beforehand.
- **Regression test:** `test_lab_operations.py`
  "test_a_restart_whose_container_exits_right_after_is_a_failed_job_with_the_reason".
- **Retest:** the vJunos-switch live run on the final build must show the failed job and the review warning.
