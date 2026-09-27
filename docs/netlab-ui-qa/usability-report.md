# Usability and accessibility review: Design tab and Restart device

An independent reviewer's findings on how easy these are to use, how they work by keyboard and at different sizes, and how accessible they are, with evidence. The reviewer reported problems and did not fix anything. Evidence is in
`evidence/usability/`. The rerunnable driver is `tools/usability_scan.py`.

## Environment

| Item | Value |
|---|---|
| Fixture manager | `docs/redesign/tools/fixture_manager.py` on port 8103, the working tree (`/api/state` version **1.30.47**), real `netlab` engine, no VM. Fresh data directory per run, all under the session scratch area (`…/scratchpad/usability/`): `fixture-data-135528` (manual walkthrough), `runs/usability-fixture-rmjnnm1u` (Chromium scan), `runs/usability-fixture-95ao1_kc` (Firefox scan), `fixture-data-142042` (manual rechecks), `runs/usability-fixture-mhd7xyce` (tool verification) |
| Tree drift | The lead edited the tree during the review. `network-design.js` changed at 14:14:20 UTC; after that edit its md5 is `4af4a8c6…` and `operations.js` is `939c51a3…`. The manual walkthrough ran from 13:55 to 14:15 UTC. The scans ran from 14:16 to 14:24 UTC, and every open finding below was reproduced on the tree as it stood at that time |
| Deployed manager | http://127.0.0.1:8081, `/api/state` version **1.30.47**, lab `restore-square`, device `host1`. The manual live session (about 14:03–14:12) ran on the 13:37 deploy, which did not yet have the RD-004 menu styling. The scan's live part ran at 14:18 (Chromium) and 14:20 (Firefox) on a redeploy whose static files match the tree byte for byte |
| Live safety | Each live browser context used a route guard that aborted every request other than a GET or `POST /api/operations/preview`. Result: 197 requests passed, **0 blocked**, 10 previews, `confirm` never requested. `#op-confirm` was never clicked, and Enter was pressed only after asserting which element had focus |
| Browsers | Chromium **153.0.8010.12** and Firefox **155.0** (Playwright 1.63.0). WebKit 26.6 downloaded but **would not launch**, see "Not reached" |
| axe-core | **4.13.0** (`npm pack axe-core`), injected into contexts opened with `bypass_csp` because the app's CSP is `script-src 'self'`. Chromium only |
| Zoom | 200 % was simulated with a 683×384 CSS px viewport at `device_scale_factor=2`. CSS `zoom` was not used |
| Themes | There is one light theme: no toggle and no `prefers-color-scheme` rules. `forced-colors` and `prefers-reduced-motion` rules exist. Both were emulated (`T-*.png`) |

## Findings (ordered by severity)

**P1 = a broken required task or an inaccessible required control; P2 = a meaningful usability, keyboard, focus or accessibility defect; P3 = polish that materially reduces clarity.**

**U-01 — P1 (P0 on the campaign's scale: data written to the wrong lab). With a field focused, switching labs by URL shows the previous lab's form, and Save writes it into the new lab.**
- *Where:* Design tab in both Chromium and Firefox. Setup: lab A (`ospf-basics`) is saved with BGP AS 65123. Click into a pool field on A, then use browser Back to reach lab B (`BGP_TheoryToPractice`).
- *What a novice sees:* the header, breadcrumb and state line all say lab B. The guided form and the Advanced JSON show lab A: its 3 devices, BGP ticked, AS 65123 and A's OSPF area. The student changes the Shared-links size and presses Save design. The toast says "Design saved.", and B's saved design now holds A's modules, BGP AS and area (`scan-*.json` → `lab_switch_repro`). A mouse Back button or Alt+Left does this just as well. A keyboard user who Tabs into the form while a lab is loading got the same stale form in the manual walkthrough.
- *Expected:* the form always shows the lab in the header, and no other lab's values are ever saved.
- *Evidence:* `chromium-D10-…`, `firefox-D10-after-back-lab-b-header-lab-a-form.png`, `manual-09-lab-switch-other-labs-form-saved.png`.
- *Cause (read after the fact):* `designRenderForm()` rewrites nothing while `designFormFocused()` is true, even when `designState.labId` has just changed. Probe P5 (a delayed Save response) is a different cause.
- *Direction:* when the lab changes, bypass the focus guard (or blur the field), and refuse a draft built from a form rendered for another lab.

**U-02 — P2. The Restart device review drops focus to `<body>` on every path.**
- *Where:* 8081, both browsers. Map by mouse: right-click → *Restart device…* → Cancel. Map by keyboard: focus the device, Shift+F10 (or ContextMenu), ArrowDown ×2, Enter, then Escape. Devices tab: *Details* (Enter) → Tab ×5 → *Restart device…* (Enter) → Tab ×2 → Cancel (Enter).
- *What a novice experiences:* the menu itself is excellent: focus lands on the first item, the arrows skip disabled items, Home and End work, and Escape returns to the device. After the review, focus is always on `<body>`, so a keyboard user starts again from the page top. From the device panel, opening the review closes the panel, and after Cancel neither the panel nor focus returns.
- *Expected:* focus returns to the invoking device or panel button, and the panel is still open after Cancel.
- *Evidence:* keyboard rows in `scan-*.json`, `chromium-L01…L03`.
- *Direction:* `opReview` remembers `document.activeElement` (or the device) and restores it on `close`. It keeps the panel open, or reopens it.

**U-03 — P2. The shared `opDialog` dialogs have no accessible name.**
- *Where:* `dialog#operation-review` (the Restart review), `#design-renumber-dialog`, `#design-clear-dialog` and `#design-file-dialog`.
- *What happens:* a screen reader announces an unnamed dialog. The accessibility tree shows `- dialog:` with no name. Apply and Export carry `aria-labelledby` and are fine. axe reports no violation here because its dialog-name rule only checks an explicit `role=dialog`.
- *Direction:* in `opDialog`, set `aria-labelledby` to the dialog's own `h2`.

**U-04 — P2. Design form controls have no accessible names.**
- *Where:* `#design-pool-p2p-prefix`, `#design-pool-lan-prefix` and `#design-advanced` (axe `label`, critical). Every Role select and every link VRF/Access-VLAN select (`select-name`, critical: 7 on `ospf-basics`; the BGP lab renders 13 + 32 more the same way, not scanned with axe).
- *What else:* the pool prefix inputs and the Trunk VLANs inputs are named only by their placeholder. The trunk one is announced as "red,blue", which sounds like a value and names VLANs that do not exist.
- *Evidence:* `axe-chromium-design-*.json`.
- *Direction:* use `aria-label` or `aria-labelledby` built from the row and column, such as "Role of r1" or "Trunk VLANs, r1 — r2".

**U-05 — P2. The Apply review gives no sign that it is working, then loses focus and scroll position.**
- *Where:* `#design-apply-review-run` on BGP_TheoryToPractice (12 devices, unreachable on the fixture).
- *What a novice sees:* nothing happens for **54.8 s** (both browsers). The Review button stays enabled, and there is no busy text and no `aria-busy`, so the student clicks again or gives up. When the review appears, focus is on `<body>`, and the dialog is scrolled 77–78 px down, which hides the title and the introduction.
- *Evidence:* `chromium-D08-apply-review-in-flight.png`, `D09`.
- *Direction:* disable Review while it runs, with "Reviewing 12 devices…" and `aria-busy`. Move focus to the review heading and reset `scrollTop`.

**U-06 — P2. A review with no device that can be applied offers no reason and no way forward.**
- *What a novice sees:* every device reads only "Connectivity: NoValidConnectionsError", a Python exception name with no next step. The recovery window and the acknowledgement are still offered. Ticking the acknowledgement leaves Apply disabled with no reason. The review step has no Cancel: only Back, Apply and a × that has scrolled out of view.
- *Evidence:* `manual-03`, `manual-04`.
- *Direction:* add one summary line, for example "None of the 12 devices answered over SSH: is the lab running? (Devices › Test logins)". Put the reason next to Apply, add Cancel, and hide the acknowledgement when nothing can be applied.

**U-07 — P2. *Remove* in the VRFs, VLANs and Static routes tables drops keyboard focus to `<body>`** (both browsers). Enter on Remove deletes the row and the student's place is lost. *Direction:* move focus to the next row's Remove, or to the Add button.

**U-08 — P2. At 390 px the More menu opens off the left edge of the screen.**
- *What happens:* the items sit at x = −102…124, so "Download design file", "Import…", "Renumber…" and "Remove design…" are cut off and cannot be scrolled into view.
- *Evidence:* `chromium-V-390x844-more-menu.png`.
- *Direction:* anchor the menu to its button's left edge when it would overflow, or clamp it to the viewport.

**U-09 — P2. In the device panel, the reason *Restart device…* is disabled lives only in `title`.**
- *What happens:* a disabled button cannot take focus, so keyboard, touch and screen-reader users never get the reason, for example "This lab has no topology file on the VM (Advanced › Deployment details)". The map menu shows the same reason visibly. Open CLI and Back up in the panel have the same pre-existing pattern.
- *Evidence:* `manual-05`.
- *Direction:* show a visible caption, as the menu does.

**U-10 — P3. Generate plan on an empty design is the primary, enabled button, and the headline tells the student to use it** ("Choose addressing, protocols and services below, then Generate plan."). Clicking it gives only the toast "Save a design first." (`manual-01`). *Direction:* disable it with that reason, or mention Save in the guidance line.

**U-11 — P3. A stale caption.** Generated files says "Applying them to devices is not available yet.", while *Apply to devices…* sits on the plan card and `NETWORK-DESIGN.md` says the files reach devices through it. *Direction:* use the guide's sentence.

**U-12 — P3. The state line says every state twice**, as the pill and as identical text beside it ("No design yet No design yet"), and `role=status` reads both. *Direction:* drop one, or use the text for the detail.

**U-13 — P3. Module settings appear far from the checkbox that reveals them.** OSPF area, BGP AS and the others appear about 620 px below their checkbox, after all 18 modules, and their labels touch the inputs (`manual-09`). *Direction:* render each module's settings under its own checkbox.

**U-14 — P3. The Advanced JSON editor is 182–197 px wide at 1366 px** (the default 20 columns), so every JSON value wraps (`manual-02`, `D05`). *Direction:* make it full width.

**U-15 — P3. Plan warnings are hidden.** They sit in a closed "Warnings" fold with no count, under a green "Plan ready to review" (2 warnings on the BGP lab). *Direction:* label it "Warnings (2)" or open it by default.

**U-16 — P3. The plan card's disabled reasons are loose lines that are not tied to their buttons.** "The lab is not running." and "Bind this lab to a repository under Progress first." are stacked, and on an empty plan "Generate a plan first." appears twice. *Direction:* put each reason under its own button and link it with `aria-describedby`.

**U-17 — P3. *Restart device…* and the lab-wide action are easy to confuse.**
- *The labels:* *Restart device…* (map and panel) and Lab actions › *Restart devices* differ by one letter. The lab-wide item has no ellipsis and is not red, although it restarts every device and opens a review.
- *The reviews:* they describe the same containerlab mechanism differently. The lab-wide one says "restart from their startup configuration"; the single-device one says unsaved changes "may not survive".
- *The single-device review itself is clear.* It says only this one device restarts, naming its container and state, and that the rest of the lab does not. It says what drops, that neighbours lose adjacencies, and that nothing is saved, backed up, reset or reapplied.
- *Minor:* the CLI disconnect is stated twice. The body text carries `(containerlab restart --node)`. A red "Last saved … to Git." next to *Save progress first* can suggest that saving protects the device.
- *Direction:* rename the lab-wide action "Restart all devices…" and state the CLI disconnect once.

**U-18 — P3. *Restart device…* is offered before the manager knows whether the VM supports it.** On the fixture, whose helper lacks the capability, the first click gives "That did not work. The details below say why." with the reason folded away. Only the next right-click shows the item disabled with its reason (`manual-07`). *Direction:* load the capability with the lab, or put the reason in the banner headline.

**U-19 — P3. Buttons whose names do not identify their target.** Every generated file's button is named just "View". The Details buttons are named "Details for clab-restore-square-host1", the container name, although the page shows `host1`. *Direction:* name them from the short name.

**U-20 — P3. The Remove design and Renumber dialogs leave two questions open.** Neither says whether the action can be undone (download the design file first). Neither says that devices already configured keep their configuration.

**Resolved during the review (not counted):**
- Generate with unsaved edits generated from the old saved design without saying so (seen at 14:00; campaign probe P4). The 14:14 tree saves first: "Design saved. Generating the plan…".
- The 13:37 live deploy showed *Restart device…* in the menu without any red styling (`manual-11`). This was RD-004, and the fix was deployed by 14:18.

## Walkthrough notes per screen (novice questions)

- **Empty Design tab.** *What can I do?* Clear enough: settings, then plan. *What next?* Misleading (U-10). *What is saved?* The pool fields hold real values, not placeholders, but look identical to the placeholders. A novice cannot tell "defaults" from "mine". The Size column means prefix length, and nothing says so.
- **Unsaved/saved.** "Unsaved changes — Save the design to keep these changes." and "Design saved, no plan yet" (QA-001 fix) are both clear. *Discard changes* exists in the tree but was not exercised here.
- **Plan ready.** Compatibility is shown as 4 × 3 "Generated, not yet tested live" pills: honest, but dense. The file groups use netlab jargon (`normalize`, `initial`) with no explanation. Warnings are hidden (U-15).
- **More menu.** It explains its disabled items (QA-002 fix). "Renumber (forget allocations)…" is jargon until the dialog opens. The dialogs are clear about what changes, but not about undo (U-20).
- **Export plan to Git.** The best screen: it names the destination (repo › branch › path), labels its fields and says the upload waits for review.
- **Apply to devices.** The choose step explains excluded devices. The review step fails the novice when nothing is reachable (U-05, U-06).
- **Restart device (map and panel).** The menu shows each reason visibly and puts the destructive item last before Details. The review answers "which device, what drops, what is not done" well. For recovery and focus, see U-02.

## Keyboard matrix (Chromium and Firefox agree unless noted)

| Control | Reachable | Operable | Focus return |
|---|---|---|---|
| Design tab (tablist ArrowRight) | yes | yes (roving `tabindex`) | n/a |
| Generate / Save / More → form | yes, in visual order | yes | n/a |
| Guided checkboxes, inputs, selects | yes | yes; names missing (U-04) | n/a |
| Add VRF / VLAN / static route | yes | yes; focus stays on Add, and the new row is not focused | n/a |
| Remove row | yes | yes | **no: `<body>`** (U-07) |
| More menu | Enter | first item focused, arrows cycle, Escape | yes, to More |
| Renumber / Remove design dialogs | via menu | focus on ×; Tab cycles × → Cancel → action (Chromium passes once through the browser chrome, native) | yes, to More |
| Advanced `<details>`, textarea, Check | yes | yes | n/a |
| Generated file View dialog | yes | Escape | yes, to View |
| Export plan to Git dialog | yes | Tab stays inside (Firefox); once through browser chrome (Chromium) | yes |
| Apply dialog: choose → review | yes | yes, but the review lands on `<body>` (U-05) | yes, to Apply |
| Restart: map device menu | Shift+F10 / ContextMenu | arrows, Home/End, Escape back to device | yes (menu) |
| Restart review (map or panel) | Enter on item | focus on ×; Tab: Technical details, Cancel, Save progress first, Restart device | **no: `<body>`** (U-02) |

Scroll locking: the page behind a modal still scrolls with the wheel, but the background is inert (clicks are blocked). This is native `<dialog>` behaviour and is noted, not listed as a finding.

## Viewport matrix (Chromium; "OK" = no clipped control and no whole-page overflow the shell does not already have)

| Size | Design tab | Plan tables | More menu | Apply dialog | Export dialog | Restart review / map menu (live) |
|---|---|---|---|---|---|---|
| 1920×1080 | OK | OK | OK | OK | OK | not run |
| 1366×768 | OK | OK | OK | OK, inner scroll (Review below the fold) | OK | OK (manual) |
| 1024×768 | OK | OK | OK | OK, inner scroll | OK | not run |
| 768×1024 | OK | OK | OK | OK | OK | not run |
| 390×844 | page is 428 px wide: the **shell** (Topology is also 428; the header breadcrumb overlaps the product name) | inner scroll, OK | **clipped** (U-08) | OK | OK | OK: fits, buttons wrap / menu fits |
| 200 % (683×384 @2x) | OK | OK | OK | OK, inner scroll | OK, inner scroll | OK, inner scroll / menu fits |

## Automated accessibility (axe-core 4.13.0, Chromium)

| Screen | Violations (impact × nodes) |
|---|---|
| Design: empty, unsaved, plan ready, More menu | `select-name` critical ×7, `label` critical ×2, `empty-table-header` minor ×4 |
| Design: Advanced open | as above, plus `label` ×1 (`#design-advanced`) |
| Apply review | `heading-order` moderate ×1 (device `h4` directly under the dialog `h2`) |
| Apply choose, Export, Renumber, Remove, file view | none |
| Live: map menu, Restart review, device panel | none |

**Actionable:** `select-name`, `label` and `heading-order`, all folded into U-04.

**Judged low value:**
- `empty-table-header` is the unlabelled Remove column. It is real but minor: add a visually hidden "Actions".
- "Incomplete" results were left for manual review and are not counted: `aria-allowed-role` ×1, `aria-valid-attr-value` ×1 and `color-contrast` ×1 behind the modal backdrop. The first two were not attributed to an element.

**What axe missed:** unnamed native dialogs (U-03), placeholder-only names, focus loss (U-02, U-05, U-07) and the clipped menu (U-08). An automated pass does not prove compliance. No screen reader was run.

## Cross-browser matrix

| Journey | Chromium 153.0.8010.12 | Firefox 155.0 | WebKit 26.6 |
|---|---|---|---|
| Design: open, edit, save, generate, view a file | pass, with the findings above | pass, same findings | not run |
| Renumber / Remove / Export / Apply dialogs by keyboard | pass (focus as in the matrix) | pass | not run |
| U-01 lab-switch contamination | reproduced | reproduced | not run |
| Restart review open and cancel, live (guarded) | pass; 0 blocked, 5 previews | pass; 0 blocked, 5 previews | not run |
| Advanced editor width | 197 px | 182 px | — |

## Not reached, and why

- **WebKit.** `playwright install webkit` downloaded WebKit 26.6, but the launch failed with "Host system is missing dependencies to run browsers" (`libgtk-4.so.1`, `libgraphene-1.0.so.0`, `libevent-2.1.so.7`, GStreamer GL/codecparsers, `libflite*`, `libavif.so.16`, `libwayland-server.so.0`, `libmanette-0.2.so.0`, `libenchant-2.so.2`, `libsecret-1.so.0`, `libx264.so`). Installing them needs `sudo playwright install-deps` / apt on the shared dev VM. I did not change the system.
- **Apply review branches.** Only the unreachable-device review was reached (the fixture has no SSH endpoints). No diff, conflict, take-over or progress-step screens were seen. Export's submit, the Import file flow and the design-engine-unavailable state were not exercised.
- **Restart device.** Confirm was never used, by rule. Disabled reasons were read on the fixture, because every live device is deployed.
- **Coverage limits.** No screen reader and no real touch device. Firefox ran without axe and without the viewport matrix. 400 % zoom and 320 px were not tried.

## Files

`tools/usability_scan.py` (the rerun command is in its docstring), `evidence/usability/scan-{chromium,firefox}.json`,
`scan-summary.json`, `axe-chromium-*.json` (14 screens), `{chromium,firefox}-D*.png` (Design journey),
`chromium-V-*.png` (viewport matrix), `chromium-T-*.png` (forced colours, dark preference), `chromium-L*.png`
(live Restart), `manual-*.png` (the walkthrough screenshots cited above).
