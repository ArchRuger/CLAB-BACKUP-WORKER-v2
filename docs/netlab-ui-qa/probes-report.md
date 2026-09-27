# Network design (Design tab) — ten probe reproductions

Reproduced against the fixture manager (real FastAPI app, scratch state, pinned `netlab` 26.9 engine, no
VM) — never the deployed product on 8081, never `/srv/containerlab-node-manager`, never `~/labs`. All
runs used Chromium **153.0.8010.12** (Playwright 1.63, `clab-backup-ui/.venv`).

- Tool: `docs/netlab-ui-qa/tools/probes/design_probes.py` (one driver, one function per probe, `--probes`
  selects which to run). Rerun with a fresh scratch data dir:

  ```bash
  PATH="$PWD/clab-backup-ui/.venv/bin:$PATH" clab-backup-ui/.venv/bin/python \
      docs/netlab-ui-qa/tools/probes/design_probes.py --port 8098 --data <FRESH dir> --probes 1,2,3,4,5,6,7,8,9,10
  ```

  It starts/stops its own fixture manager on port 8098 (never 8097), prints one `PASS`/`FAIL` line per
  check, and writes screenshots to `docs/netlab-ui-qa/evidence/probes/P<n>-<step>.png`.
- Final full run: started 2026-09-27T13:53:59Z, data dir a fresh `mkdtemp`-style scratch directory,
  labs `ospf-basics` (2×`arista_ceos` + 1×`cisco_xrv9k`), `vlan-lab` (3 devices) and
  `BGP_TheoryToPractice` (13 devices, used only where a bigger engine run was needed). All 58 checks
  across all ten probes passed in that run (log kept at
  `/tmp/claude-1000/.../scratchpad/probes/final-run.log` in this session's scratch area — not part of
  this deliverable's tracked files). Console/page errors were monitored for the whole session; the only
  console error seen anywhere was the single deliberately-injected HTTP 500 in Probe 7 (fault injection,
  expected). No unexpected console or page errors in any run.
- Methodology note: a route handler that blocks with `time.sleep()` to simulate a slow response also
  blocks Playwright's own sync-API driver thread, serializing every other Playwright command behind the
  "network" delay instead of letting the test race it. Probes 5 and 6 instead hand the delay to a
  background Python thread that calls `route.continue_()` later (`delayed_continue()` in the driver);
  this is what actually lets the fault-injection scenarios exercise a real race. Calling
  `route.continue_()` from that thread occasionally prints a benign `greenlet.error` /
  `cannot switch to a different thread` warning from Playwright's own internals — this is test-harness
  noise (confirmed harmless: every check still passed and no page-side console/page error was ever
  attributed to it), not a product defect.

## Verdict table

| # | Hypothesis | Verdict |
|---|---|---|
| 1 | Advanced-to-guided data loss (addressing pools) | **CONFIRMED** |
| 2 | Multiple route reflectors collapsed to one | **CONFIRMED** |
| 3 | Acting on stale intent while screen shows something else | **CONFIRMED** |
| 4 | Unsaved Generate/Export uses old saved content | **CONFIRMED** |
| 5 | Cross-lab asynchronous contamination | **CONFIRMED** |
| 6 | Same-lab different-generation race | **CONFIRMED** |
| 7 | Polling failure and stale success | **CONFIRMED (severity refined)** |
| 8 | Draft conflict / storage failure | **CONFIRMED** |
| 9 | History usefulness / "masquerade" | **CONFIRMED** |
| 10 | Falsy/default coercion | **CONFIRMED** |

---

## P1 — Advanced-to-guided data loss on the addressing pools

**Verdict: CONFIRMED.**

**Steps.** Open `ospf-basics` → Design. In Advanced, enter a valid intent whose `addressing` has the
three guided pools (`loopback`, `p2p`, `lan`) **plus** two extra pools the schema explicitly allows
(`vrf_loopback`, `router_id` — `design_intent.py` `POOLS`, line 40) and two extra keys on the `lan` pool
(`start`, `allocation`) that the schema also allows (`POOL_KEYS`, line 41) but the guided form has no
control for. Save; reload; confirm everything round-trips. Then edit one unrelated guided field (OSPF
area) and blur.

**Observed.** `designIntentFromForm` (network-design.js:54, the object literal at line 60) rebuilds
`intent.addressing` from scratch as exactly `{loopback, p2p, lan}` on **every** guided-field edit,
whatever `base` had. The OSPF-area edit alone erased `vrf_loopback`, `router_id`, and `lan.start`/
`lan.allocation` — silently, with `#design-problems` staying empty (P1-02). Save + reload confirmed the
loss is permanent (P1-03), even though the server side (`design_intent.py normalize()`, line 698) never
strips these keys — the loss is 100% client-side.

**Evidence.** `P1-01-baseline-saved.png`, `P1-02-after-unrelated-guided-edit.png`,
`P1-03-after-save-and-reload.png`.

**Source.** `clab-backup-ui/app/static/network-design.js:54-63` (`designIntentFromForm`'s addressing
rebuild); `clab-backup-ui/app/design_intent.py:37-42` (`POOLS`/`POOL_KEYS` prove these are legitimate,
not junk, fields).

**Fix direction.** Merge into the existing `addressing` object's `loopback`/`p2p`/`lan` keys (like the
VRF/VLAN/link/static-route code just below it already does), instead of replacing the whole object.

---

## P2 — Multiple route reflectors collapsed to one

**Verdict: CONFIRMED.**

**Steps.** Same lab, Advanced intent with `bgp.as` and **two** nodes each carrying `bgp.rr: true`
(`r1`, `r2`). Save; reload; confirm both are stored (`"rr": true` appears twice). Edit one unrelated
guided field (BGP AS number, not the reflector select) and Save again.

**Observed.** The guided form has one `<select id="design-bgp-rr">`. `designIntentFromForm`'s per-node
loop (network-design.js, inside `designIntentFromForm`) sets `bgp.rr = true` only for the single name
matching that select's current value and **deletes** `bgp.rr` for every other node — on any guided
change, not just an edit to the reflector control itself. After the AS-only edit and Save, exactly one
of the two reflectors survived (`"rr": true"` count dropped from 2 to 1), with no warning.

**Evidence.** `P2-01-two-reflectors-saved.png`, `P2-02-after-unrelated-guided-edit.png`.

**Source.** `clab-backup-ui/app/static/network-design.js` — the `if(has('bgp'))` block inside
`designIntentFromForm` (around line 76-82: `if(values.bgpRr&&values.bgpRr===name)bgp.rr=true;else delete
bgp.rr;`).

**Fix direction.** Make the guided control a multi-select (or checkbox list) of reflectors, or leave
`bgp.rr` alone for any node not present in `values.devices`'s edited set.

---

## P3 — Acting on the last parsed (stale) intent while the screen shows something else

**Verdict: CONFIRMED**, with one platform caveat noted below.

**Steps.** Save a baseline (`label: "P3-baseline"`, OSPF area `0.0.0.0`). Type syntactically invalid JSON
into Advanced (`page.fill`, leaving it un-blurred — P3-01). Click **Save**.

**Observed.** `#design-advanced` listens on `'change'` (bound at network-design.js:1373), which browsers
fire on blur-with-a-changed-value — Chromium's own click handling blurs the previously-focused textarea
*before* the button's click event fires, so "click Save without blurring" cannot be produced by a literal
mouse click in a real browser (noted honestly rather than claimed). What matters is what happens once
that native blur/'change' fires: `designOnAdvancedChange` (network-design.js:954) fails to parse, shows
"not valid JSON" in `#design-problems`, and returns **without touching `designState.draft`** — the stale,
last-good intent stays in effect. The follow-on Save then silently used that stale intent
(`captured PUT body contained "P3-baseline"`, never the typed "P3-BROKEN-EDIT"), the save succeeded, and
`#design-problems` was cleared — with the textarea's on-screen malformed text simply overwritten back to
the stale content, and no message ever says "your edit was discarded." The same "Generate" run afterward
(P3-03/04) was **not blocked** by malformed on-screen JSON at any point — Generate/Save/Check all operate
against `designState.draft`/`view.intent`, never re-reading `#design-advanced` themselves.

**Evidence.** `P3-00-baseline-saved.png` … `P3-04-generated-after-malformed-edit.png`; captured PUT body
via `page.route` interception.

**Source.** `clab-backup-ui/app/static/network-design.js:954-965` (`designOnAdvancedChange`'s early
`return` on parse failure), `:1045-1065` (`designSave` reading `designCurrentIntent(designState.view)`,
never the textarea).

**Fix direction.** Disable Save/Generate/Check (or show a blocking banner) while `#design-advanced`'s
current text does not parse to the intent currently backing those actions, so the "not valid JSON"
message and the outcome of the next action always agree.

---

## P4 — Unsaved Generate/Export silently use the old saved content

**Verdict: CONFIRMED.**

**Steps.** Save `bgp.as: 65001`; Generate (plan correctly shows 65001). Edit AS to `65099` through the
guided field **without saving** (state correctly shows "Unsaved changes"). Click **Generate** again, then
**Download design file**.

**Observed.** `designGenerate()` (network-design.js:1071) sends only `{revision}` — the **last saved**
revision, read from `designState.view.intent.revision`, never the draft — confirmed by intercepting the
POST body (no `bgp`/`65099` anywhere in it). The server's `submit()` (`network_design.py:278`) always
generates from `lab['network_design']` (the saved record), and only rejects when a **non-empty**
`revision` mismatches it — an empty/absent revision is accepted unconditionally. The resulting "new" plan
still showed AS 65001, not 65099 (P4-03), while the guided AS field still showed 65099 the whole time and
the header still said **"Unsaved changes"** even after the plan finished — because `designStateOf()`
(network-design.js:29) checks `view.draft` *before* it ever reaches the "ready" branch. **Download design
file** (`designExport`, network-design.js:1115 → `GET /api/labs/{id}/design/export`,
`network_design.py` `export_intent`) reads `lab.get('network_design')` directly — the downloaded YAML
also contained AS 65001, not the unsaved 65099.

**Evidence.** `P4-01-plan-with-as-65001.png`, `P4-02-unsaved-edit-to-65099.png`,
`P4-03-plan-after-clicking-generate-while-unsaved.png`; captured Generate POST body; downloaded export
file contents (via `page.expect_download()`).

**Source.** `clab-backup-ui/app/static/network-design.js:1071-1078` (`designGenerate`);
`clab-backup-ui/app/network_design.py:278-306` (`submit`, the empty-revision bypass);
`clab-backup-ui/app/static/network-design.js:29-51` (`designStateOf`'s `draft`-before-`ready` priority).

**Fix direction.** Refuse Generate/Export (with a clear message) while `view.draft` is truthy, or require
the draft's own revision to match before either action proceeds.

---

## P5 — Cross-lab asynchronous contamination

**Verdict: CONFIRMED — high severity.**

**Steps.** On `ospf-basics` (lab A), set OSPF area to the distinctive value `9.9.9.9` and click **Save**.
A `page.route` fault-injector delays *only* that PUT response by 5s (using a background thread so the
delay is real concurrency, not a blocked test driver — see methodology note above). Before it resolves,
switch to `vlan-lab` (lab B, no design saved) and open its Design tab.

**Observed.** Immediately after switching, lab B correctly showed "No design yet" (P5-01). ~5s later,
once lab A's delayed PUT resolved, **lab B's Design tab silently repainted itself with lab A's saved
content**: OSPF checked, area `9.9.9.9`, a "Design saved." toast — while the breadcrumb still read
`vlan-lab` and the URL/tab were still lab B's (P5-02). A direct server-side check confirmed lab B's own
`network_design` was still `None` — this is a pure client-side rendering race, not data corruption on
disk. Root cause: `designSave()`'s success handler (network-design.js:1045) does
`designState.view = view; ...; designRenderAll();` with **no check that `designState.labId` still equals
the lab the request was made for** — and since navigating to lab B only changes `designState.labId` (not
`.view`), the delayed response's unconditional `designState.view = <lab A's data>` gets rendered under
lab B's still-matching `labId`.

**Evidence.** `P5-01-lab-b-immediately-after-switch.png`,
`P5-02-lab-b-after-lab-a-save-resolved.png` (shows `vlan-lab` breadcrumb with `ospf-basics`' OSPF/9.9.9.9
content and a "Design saved." toast).

**Source.** `clab-backup-ui/app/static/network-design.js:1045-1065` (`designSave`, no `labId` guard
before `designState.view = view`).

**Fix direction.** Capture `labId` at the start of `designSave()`/`designValidate()` and check it against
`designState.labId` before applying the response, exactly like `designLoad()`/`designLoadPlan()` already
do.

---

## P6 — Same-lab different-generation race

**Verdict: CONFIRMED.**

**Steps.** On `ospf-basics`, generate G1 (OSPF-only). Add a fault-injector that delays (10s, background
thread) the `GET .../design/generations/{G1_id}` request specifically. Reload the page (this refetches
G1's plan through the now-delayed route). While that fetch is in flight, add BGP (AS 65077) and generate
G2; wait for G2 to succeed normally.

**Observed.** G2 correctly showed "bgp"/"65077" in the plan immediately after it finished (P6-01). ~11s
after the reload (once the delayed G1 fetch finally landed), **the "Plan" panel reverted to G1's stale,
BGP-less content** — no BGP sessions anywhere in the device tables — while the Download link and history
still correctly pointed at G2 (P6-02: form shows OSPF+BGP/65077, "Plan ready to review" header, but the
plan body underneath has no BGP section at all). Root cause: `designLoadPlan(labId, generationId)`
(network-design.js:682) checks only `designState.labId === labId` before overwriting
`designState.plan` — never that `generationId` still matches the currently "newest" generation. A
lab-id-only check is exactly insufficient once two different generations for the *same* lab are in
flight.

**Evidence.** `P6-01-g2-ready-immediately.png`, `P6-02-after-delayed-g1-fetch-lands.png`.

**Source.** `clab-backup-ui/app/static/network-design.js:682-687` (`designLoadPlan`, missing
generation-id check).

**Fix direction.** Have `designLoadPlan` compare `generationId` against `designNewestGeneration(view).id`
before assigning `designState.plan`, discarding a response for a generation that is no longer newest.

---

## P7 — Polling failure and stale success

**Verdict: CONFIRMED, severity refined by testing.** The originally-suspected "frozen forever" outcome
does not usually happen in a live session, but a real, un-retried failure mode does, and the thing that
masks it is accidental, not designed.

**Steps.** On the 13-device `BGP_TheoryToPractice` lab (needed so the real engine stays "running" long
enough to hit a genuine poll cycle — `ospf-basics` generates too fast for this), start Generate, then
fulfill the **second** matching `GET .../design` (the first real poll tick, ~2s after the first fetch)
with a bare HTTP 500.

**Observed.** `designMaybeStartWatch()`'s `poll()` (network-design.js:705) has a bare
`catch{designStopWatch();}` — any failure (a 500, a network blip, malformed JSON) kills the poll
permanently, with no retry and no user-facing error; 3 seconds after the injected 500 (well past the
poll's own 2s cadence) the tab was still stuck on "Generating the plan…" (P7-02, CONFIRMED). It did
recover about 8 seconds later (P7-03) — but not via the poll's own logic: `designMaybeStartWatch()`
checks `if(designWatch===designState.labId)return;`, and since `designStopWatch()` had set `designWatch`
to `null`, the **next unrelated call** to `designRenderAll()` (from `app.js`'s own
`setInterval(() => refresh(), 4000)` global heartbeat, `app.js:393`, which calls the shared `render()` →
`renderNetworkDesign()` regardless of which tab is showing) restarts the watch as a side effect, using
the stale-but-still-"running" cached generation status. This is a coincidental rescue by an unrelated
timer, not a retry — a session where nothing else happens to call `render()` while the stuck lab is
`current()` (there is always at least the 4s heartbeat while a lab is selected, so in practice this
window is bounded to ~4s) would have no such rescue.

**Evidence.** `P7-01-generating-before-fault.png`, `P7-02-shortly-after-injected-500.png`,
`P7-03-well-after-fault-recovered-via-the-global-refresh.png`; direct server-side check confirmed the
generation had in fact succeeded well before the page caught up.

**Source.** `clab-backup-ui/app/static/network-design.js:705-726` (`designMaybeStartWatch`/`poll`, the
bare catch); `clab-backup-ui/app/static/app.js:393` (the unrelated global refresh that happens to mask
it).

**Fix direction.** Retry the poll a bounded number of times with backoff instead of dying on the first
failure, and surface a visible "couldn't check progress, retrying…" state instead of silently freezing.

---

## P8 — Draft conflict and storage failure

**Verdict: CONFIRMED.**

**Steps.** Override `Storage.prototype.setItem` (via `page.add_init_script`, keeping the original
function reachable for the test's own later use) to throw for the `clab.design.draft.*` key, simulating
a full quota / private-browsing storage failure. Edit a guided field (creating a draft that can now only
ever live in memory); reload.

**Observed.** The app tolerated the throwing `setItem` without any uncaught page error (`writeDesignDraft`
in `shell.js` wraps it in `try{...}catch{return false;}`) and correctly showed "Unsaved changes" while the
edit was live (P8-01). After reload, the edit was gone (expected, since it was never persisted) — but
**`#design-detail` showed no message at all** about it (P8-02), not even a generic "you had unsaved
changes" — total silent loss. For contrast, a genuinely stale (revision-mismatched) draft written
directly into `localStorage` (bypassing the fault, via the preserved original `setItem`) **does** produce
an explicit "Your unsaved changes were older than the saved design and were discarded." message on reload
(P8-03, `designApplyDraft`/`designState.draftDiscarded` in network-design.js). So the one storage-failure
path that destroys a student's only copy of their edit is also the one path with zero acknowledgment.

**Evidence.** `P8-01-unsaved-edit-with-storage-failing.png`, `P8-02-after-reload-storage-had-failed.png`,
`P8-03-stale-draft-discard-message-for-contrast.png` (message present).

**Source.** `clab-backup-ui/app/static/shell.js` (`writeDesignDraft`'s swallowed return value — its
caller, `designSetDraft` in `network-design.js:930-934`, never checks it); the discard message is in
`clab-backup-ui/app/static/network-design.js` (`designRenderHeader`, `designState.draftDiscarded`).

**Fix direction.** Have `designSetDraft` check `writeDesignDraft`'s return value and surface a visible
"couldn't save your draft locally" warning the first time it fails, rather than silently continuing.

---

## P9 — History usefulness ("masquerade")

**Verdict: CONFIRMED**, and more strikingly than the hypothesis's own framing suggested.

**Steps.** Generate G1 (succeeds). Force a failed generation G2 (`eigrp` on `arista_ceos`, the same
proven-unsupported combination `docs/netlab-integration/tools/check_design_ui.py` already relies on).
Fix it and generate G3 (succeeds). Then use **Remove design**.

**Observed.**
- History (`#design-history-body`, `designHistoryMarkup`) lists every generation, but as **plain text**
  (a pill + relative time + message) — zero links or buttons. Once G3 exists, G1's and G2's own plan
  bodies/error lists are **unreachable through the UI**: the single "Download design file"/plan-body/
  files card always points at `designNewestGeneration(view)` only (CONFIRMED).
- **Remove design** does clear the intent (guided form goes back to no modules checked, Advanced JSON
  goes back to an empty intent — P9-03) and shows a "Design removed." toast. But the **header still
  says "Plan ready to review"**, and the entire "Generated plan" card below keeps presenting G3's full
  device/interface/BGP tables as a live, current result — because `designStateOf()`
  (network-design.js:29-51) derives the header purely from the newest generation's status/staleness and
  **never checks whether an intent is actually saved at all**. The screenshot shows the contradiction
  directly on one page: an empty guided form and an empty Advanced JSON, sitting right above a fully
  populated "ready to review" plan for a design that a toast just confirmed was removed.
- The one useful "good news": the last succeeded generation (G3) stays downloadable after Remove design
  (server-side generations are retained, matching the `design.clear` event's own wording), so the
  underlying data isn't lost — only the *labeling* of it as "the current design" is wrong.

**Evidence.** `P9-01-g2-failed.png`, `P9-02-g3-ready-history-has-three.png`,
`P9-03-after-remove-design.png` (the key shot: empty form + "Plan ready to review" header + full plan
card, together).

**Source.** `clab-backup-ui/app/static/network-design.js:29-51` (`designStateOf`, no `view.intent` check
at all); `:338-345` (`designHistoryMarkup`, plain text only); `network_design.py` `clear_design`
(generations retained, intent popped).

**Fix direction.** Add an explicit "no design saved" branch to `designStateOf()` that overrides the
newest-generation branches whenever `view.intent` is null, and give each history entry a way to open its
own plan/errors/files (even read-only) instead of only ever showing the newest.

---

## P10 — Falsy/default coercion

**Verdict: CONFIRMED**, three distinct mechanisms.

**10a — numeric defaults.** Typing BGP AS `0` is silently coerced to `65000`
(`Number(values.bgpAs)||65000`, `designIntentFromForm`) with no warning and the field itself re-displays
`65000` after blur, as if that were what was typed. Same mechanism, same result, for a **blank** p2p
prefix size (`Number(...)||31`).

**10b — a checkbox that desyncs from reality, invisibly, even across Save.** Adding a VRF named `red`
correctly auto-checks the "VRFs" module checkbox (documented/intended). Manually unchecking that checkbox
while the VRF row still exists does **not** remove the VRF — `designIntentFromForm`'s own auto-re-add
rule (`if(...Object.keys(newVrfs).length...)&&!modules.includes('vrf'))modules.push('vrf')`) puts `vrf`
straight back into the draft's `modules`. That part is intended/documented. What is not intended: the
checkbox **stays visually unchecked** — not just briefly, but **through a full successful Save** — because
`setMarkup()` (`app.js:25`) caches the last HTML string it wrote per element and skips reassigning
`innerHTML` when the freshly computed string is byte-identical to what's cached; since the "vrf checked"
markup string is identical to what was already rendered right after "Add VRF", the DOM's live `.checked`
property is never touched again, so the checkbox never visually corrects itself in the same session. Only
a full page reload (a fresh element, no stale cache) shows the truth: the module was on the whole time.

**Evidence.** `P10-01-as-zero-coerced.png`, `P10-02-p2p-prefix-blank-coerced.png`,
`P10-03-vrf-module-auto-checked-after-naming-a-vrf.png`,
`P10-04-vrf-checkbox-immediately-after-manual-uncheck.png`,
`P10-05-vrf-checkbox-after-save-still-shows-unchecked.png`,
`P10-06-vrf-checkbox-corrects-itself-only-after-a-full-reload.png`.

**Source.** `clab-backup-ui/app/static/network-design.js:54-98` (`designIntentFromForm`'s
`Number(...)||default` coercions and the module auto-re-add rule); `clab-backup-ui/app/static/app.js:25`
(`setMarkup`'s string-equality cache).

**Fix direction.** For 10a, reject/flag `0`/blank instead of silently substituting a look-alike default.
For 10b, key `setMarkup`'s cache off more than the exact string when a control's own `checked`/`value`
was touched from outside the last render (or simplest: never cache `#design-modules`, whose cost of
re-rendering is trivial).

---

## Files

- Report: `docs/netlab-ui-qa/probes-report.md` (this file).
- Driver: `docs/netlab-ui-qa/tools/probes/design_probes.py`.
- Screenshots: `docs/netlab-ui-qa/evidence/probes/P<1-10>-*.png` (32 files).
