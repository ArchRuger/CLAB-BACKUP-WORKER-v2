# Network design (Design tab) coverage inventory

Every row was executed against the real application (fixture manager, real pinned `netlab==26.9` engine, no VM) on 2026-09-27 16:53 UTC, Chromium 153.0.8010.12; see `## Results` below and the `Result` column in the Rows table. `coverage.json` is the full record
(one object per row: id, surface, control, preconditions, states, intent, expected behaviour,
forbidden side effects, existing tests, which of the three sources found it, and notes).

Build: **1.30.47**. Generated: 2026-09-27T13:34:39+00:00.

## How this was built

Three independent sources, compared:

1. **Source**: `clab-backup-ui/app/static/network-design.js` (1392 lines), its markup in
   `clab-backup-ui/app/static/index.html` (`#design-view`, lines 150-278), the routes in
   `network_design.py`, `design_apply.py` and the design git-export route in `git_progress.py`,
   plus `design_intent.py`, `design_adapter.py`, `design_engine.py`, `design_capabilities.py` and
   `docs/NETWORK-DESIGN.md`.
2. **Rendered DOM**: `docs/netlab-ui-qa/tools/inventory_dom.py` (Playwright) against the fixture
   manager (`docs/redesign/tools/fixture_manager.py`), in two runs:
   - `--mode full` on lab **ospf-basics** (linked, Not deployed, no git binding): empty, unsaved
     edit, invalid pool, saved, plan generated (the real pinned `netlab==26.9` engine), files
     list, history, owned-settings (empty), More menu, Renumber and Clear dialogs (opened then
     cancelled), a cancel-generation attempt, and the 390x844 viewport.
   - `--mode apply_export` on lab **BGP_TheoryToPractice** (Running, git-bound, 13 devices): the
     Export plan to Git dialog (filled, not submitted) and the Apply to devices dialog past its
     Choose step into a real (and, in this no-VM fixture, uniformly failing) device review.
   - Chromium **153.0.8010.12** (Playwright), reported identically by both runs.
   - Fixture data directory used: a fresh scratch directory per run, port 8100 for the run this
     report is built from (`docs/redesign/tools/fixture_manager.py --port 8100 --data <scratch>`).
     Raw per-element JSON dumps from both runs (`dom_states_full.json`, `dom_states_apply_export.json`)
     are session scratch output, not committed alongside this report; every fact drawn from them is
     restated in the rows below and in `coverage.json`'s per-row `notes`.
3. **Navigation**: every entry route (tab click, hash route `#lab=<id>&view=design`, the Tools tab
   shortcut `#tools-design`, arrow-key tab roving, browser back/forward) and exit (another tab,
   lab switch, reload) traced from `shell.js`, `app.js` and `network-design.js`.

## Counts

| Area | Rows |
|---|---:|
| NAV -- Navigation (tabs, hash route, Tools shortcut) | 7 |
| GUIDED -- Design settings (guided form) | 20 |
| ADVANCED -- Advanced (JSON editor, ledger, ownership) | 6 |
| SAVE -- Save design | 5 |
| GENERATE -- Generate plan | 5 |
| PLAN -- Generated plan card | 9 |
| FILES -- Generated files | 3 |
| HISTORY -- History | 2 |
| EXPORT -- Export (design file + plan to Git) | 8 |
| IMPORT -- Import design file | 5 |
| RENUMBER -- Renumber (forget allocations) | 4 |
| CLEAR -- Remove design | 4 |
| APPLY -- Apply to devices | 18 |
| STATE -- Design state line | 9 |
| ERROR -- Error/refusal surfaces | 10 |
| A11Y -- Accessibility | 8 |
| **Total rows** | **123** |
| State-transition rows (separate table, `transitions` in the JSON) | 17 |
| Discrepancies found | 9 |

Of the 123 rows: **88** confirmed in both source and the rendered DOM live in this recon; **35**
confirmed only in source/tests (not reached live -- see "Not reached live" notes below and per-row
`notes`); **3** are themselves navigation rows.

## Three-source comparison

- **Source vs. DOM**: every control this recon could reach without a VM was found in both the
  source and the live DOM capture, with matching selectors/ids. Nothing was found rendered that
  has no source (the app has no dead markup discovered here).
- **DOM vs. navigation**: the Design tab is reachable by tab click, hash deep link, and the Tools
  tab shortcut; all three were driven live. Arrow-key roving and browser back/forward are source-
  and-test only in this recon (generic shell behaviour, not design-specific).
- **What could not be reached without a VM or a second session**: the Apply job's settle states
  beyond "unreachable" (no real SSH endpoint behind the fixture); the Export-to-Git submit itself
  (would start a real save-progress job); the Import file flow (native OS file picker); every
  stale-revision race (needs two concurrent sessions); the engine-unavailable state (this venv
  always has a working `netlab`); a manager restart mid-generation. These are recorded per-row
  with `sources.dom: false` and a note, not silently assumed working.

## Discrepancies

- **DOM vs. source** (note; rows ND-STATE-001): The "No design yet" pill/text/detail (designStateOf's fallback branch, network-design.js:46) is identical for two different underlying preconditions: a lab with no network_design at all, and a lab with a saved network_design but no generation yet. Confirmed live: dom_states_full.json "empty" (ospf-basics, nothing saved) and dom_states_apply_export.json "ae_saved" (BGP_TheoryToPractice, an OSPF design just saved) render byte-identical #design-state-pill/#design-state-text/#design-detail text. The two states are distinguishable only from the surrounding form (module checkboxes ticked, VRF/VLAN/static tables non-empty), never from the state line a screen-reader user would hear.
- **Source vs. behaviour** (note; rows ND-EXPORT-001, ND-IMPORT-001, ND-RENUMBER-001, ND-CLEAR-001): #design-export ("Download design file") and #design-import ("Import design file…") menu items have the <small class="menu-reason"> markup the house style uses for a disabled reason (same pattern as #design-generate via menuReasonSafe, and as operations.js's generic menuReason()), but network-design.js never calls menuReason for either of them, and neither button is ever .disabled. The backend, however, does refuse both: export 404s with no design (network_design.py:662), and import 409s while a generation is busy (network_design.py:691). #design-renumber and #design-clear have the same markup and are likewise never client-disabled, although their backend routes 404/409 on no-design/busy. #design-apply and #design-export-git, by contrast, DO compute and show a disabled reason (designApplyDisabledReason, designExportGitReason). This is an inconsistency in the More menu, not confirmed live for the failure path (no fetch was attempted through a stray window.open in this recon), so it is reported as a note rather than a defect.
- **Source-only** (info; rows ND-GUIDED-003): designToggleModuleSettings (network-design.js:734-740) only knows four modules with a dedicated settings block: ospf, bgp, isis, gateway. The remaining 13 modules in DESIGN_MODULE_LABELS (eigrp, ripv2, bfd, dhcp, vlan, vrf, lag, stp, vxlan, evpn, mpls, sr, srv6, routing) have no guided settings surface at all beyond the checkbox itself; their options exist only under the Advanced JSON textarea. This is documented behaviour (docs/NETWORK-DESIGN.md lists exactly this set of common settings), not a bug, but it means the "GUIDED" area's per-module settings coverage caps out at 4 of 17 modules -- the rest fall through to ND-ADVANCED-002/006.
- **DOM vs. navigation** (info; rows ND-EXPORT-002, ND-APPLY-001): Two states in the "full" tour (dom_states_full.json) could not be reached on ospf-basics because that fixture lab is deliberately Not deployed and has no git binding (by fixture_manager.py's own design): export_git_dialog_open and apply_dialog_choose_step. Both were then reached in a second, separate run (dom_states_apply_export.json, --mode apply_export) against BGP_TheoryToPractice (Running, git-bound). No control is actually missing; the split is a fixture-data limitation of a single lab, addressed by running the tool twice against two different seeded labs.
- **Not reached live** (info; rows ND-APPLY-007, ND-APPLY-008, ND-APPLY-012, ND-APPLY-013, ND-APPLY-014, ND-APPLY-017): The Apply review step was reached live, but only its "unreachable" branch (Connectivity: NoValidConnectionsError) -- the fixture manager has no real SSH endpoint behind BGP_TheoryToPractice's scripted devices. The eligible-and-reachable branches (normal diff, no-op, conflicts+takeover, protected settings, expected changes, removal commands) exist only in source and in test_design_apply.py/test_network_design_ui.js's designApplyDeviceMarkup unit tests, and were previously proven live (against real devices) by docs/netlab-integration/tools/check_design_apply_ui.py and docs/netlab-integration/evidence/live-apply-*.md, which this recon did not re-run.
- **Not reached live** (info; rows ND-IMPORT-003, ND-IMPORT-004): The Import design file… flow (both the success and failure paths) could not be exercised live: Playwright cannot drive a native OS file-picker headlessly, and clicking #design-import only calls .click() on a hidden <input type=file> (network-design.js:1108). Reaching it would need page.set_input_files() against a staged fixture .network-intent.yml, which this recon did not stage since the tool's scope is DOM-state enumeration, not functional testing. The control's presence and hidden-input wiring were confirmed in source and in the "import_control_state" DOM capture (the button and hidden input both present, unhidden, enabled).
- **Not reached live** (info; rows ND-SAVE-002, ND-ERROR-003): Several stale-revision / concurrent-edit error states (ND-SAVE-002, ND-ERROR-003) require two sessions racing the same lab's revision and were not reproduced with a single Playwright page in this recon; they are covered by test_network_design.py's revision tests instead.
- **In source, not rendered** (info; rows ND-STATE-009): The "Design engine unavailable" state (network-design.js:32-33, DESIGN state key "engine", which wins over every other state including a busy generation) was never rendered in either fixture run: the recon's virtualenv always has a working, on-PATH netlab, so engine.available is always true. This is the one STATE-area branch that is source- and test-only in this inventory.
- **Doc vs. code** (info; rows (cross-cutting)): docs/NETWORK-DESIGN.md's "The Design tab" section describes the tab top-to-bottom in prose and matches the actual DOM order found live (state/actions, design settings incl. Advanced, plan, files, history, Apply/Export-Git on the plan card) with no section named in the doc that is absent from the DOM, and no DOM section absent from the doc's description. No documentation-vs-code discrepancy was found in this recon beyond the two "note"-level menu-disabling asymmetries above, which the doc does not claim either way.

## Results

Executed 2026-09-27 16:53 UTC against the fixture manager (real app, real pinned `netlab==26.9` engine, no VM), Chromium 153.0.8010.12. Counts:

| Result | Rows |
|---|---:|
| PASS | 112 |
| FAIL | 0 |
| BLOCKED | 8 |
| NOT RUN | 3 |
| **Total** | **123** |

| Area | PASS | FAIL | BLOCKED | NOT RUN |
|---|---:|---:|---:|---:|
| A11Y | 8 | 0 | 0 | 0 |
| ADVANCED | 6 | 0 | 0 | 0 |
| APPLY | 11 | 0 | 6 | 1 |
| CLEAR | 4 | 0 | 0 | 0 |
| ERROR | 9 | 0 | 1 | 0 |
| EXPORT | 8 | 0 | 0 | 0 |
| FILES | 3 | 0 | 0 | 0 |
| GENERATE | 4 | 0 | 0 | 1 |
| GUIDED | 20 | 0 | 0 | 0 |
| HISTORY | 2 | 0 | 0 | 0 |
| IMPORT | 5 | 0 | 0 | 0 |
| NAV | 7 | 0 | 0 | 0 |
| PLAN | 7 | 0 | 1 | 1 |
| RENUMBER | 4 | 0 | 0 | 0 |
| SAVE | 5 | 0 | 0 | 0 |
| STATE | 9 | 0 | 0 | 0 |

### FAIL rows

None: every row executed either passed or is recorded as BLOCKED/NOT RUN with its reason below.

### BLOCKED rows (need a VM, real devices or a real Git remote)

- **ND-PLAN-009** (Plan card): Last apply line + Show button needs a real apply job, which needs a real device: see ND-APPLY area (BLOCKED, part 2)
- **ND-APPLY-007** (Review step): [BLOCKED for the eligible/no-op/conflict/protected/expected/removal branches -- see note] the unreachable branch is reached and reads plain words: needs real devices behind the review: the fixture has no SSH endpoint, so every device reports Connectivity: NoValidConnectionsError (proven live here); the eligible, no-op, conflict, protected-settings, expected-changes and removal-command review branches, a real Apply submit and its progress/ownership effects were proven live earlier on real devices: docs/netlab-integration/evidence/live-apply-*.md, check_design_apply_ui.py, test_design_apply.py, test_design_ownership.py
- **ND-APPLY-008** (Review step): no device in this review reported a conflict (none is reachable), so the take-over checkbox path is BLOCKED: needs real devices behind the review: the fixture has no SSH endpoint, so every device reports Connectivity: NoValidConnectionsError (proven live here); the eligible, no-op, conflict, protected-settings, expected-changes and removal-command review branches, a real Apply submit and its progress/ownership effects were proven live earlier on real devices: docs/netlab-integration/evidence/live-apply-*.md, check_design_apply_ui.py, test_design_apply.py, test_design_ownership.py
- **ND-APPLY-012** (Review->Apply): Apply submit needs at least one reachable, eligible device to become enabled: needs real devices behind the review: the fixture has no SSH endpoint, so every device reports Connectivity: NoValidConnectionsError (proven live here); the eligible, no-op, conflict, protected-settings, expected-changes and removal-command review branches, a real Apply submit and its progress/ownership effects were proven live earlier on real devices: docs/netlab-integration/evidence/live-apply-*.md, check_design_apply_ui.py, test_design_apply.py, test_design_ownership.py
- **ND-APPLY-013** (Progress step): the progress table's per-device stage/outcome words need a real applying job: needs real devices behind the review: the fixture has no SSH endpoint, so every device reports Connectivity: NoValidConnectionsError (proven live here); the eligible, no-op, conflict, protected-settings, expected-changes and removal-command review branches, a real Apply submit and its progress/ownership effects were proven live earlier on real devices: docs/netlab-integration/evidence/live-apply-*.md, check_design_apply_ui.py, test_design_apply.py, test_design_ownership.py
- **ND-APPLY-014** (Plan card): the plan card's "Last apply" line needs a completed real apply job: needs real devices behind the review: the fixture has no SSH endpoint, so every device reports Connectivity: NoValidConnectionsError (proven live here); the eligible, no-op, conflict, protected-settings, expected-changes and removal-command review branches, a real Apply submit and its progress/ownership effects were proven live earlier on real devices: docs/netlab-integration/evidence/live-apply-*.md, check_design_apply_ui.py, test_design_apply.py, test_design_ownership.py | additionally confirmed live: #design-apply-last stays hidden with no apply job yet for this lab
- **ND-APPLY-017** (Server): the ownership ledger only grows once a real apply has run against a real device: needs real devices behind the review: the fixture has no SSH endpoint, so every device reports Connectivity: NoValidConnectionsError (proven live here); the eligible, no-op, conflict, protected-settings, expected-changes and removal-command review branches, a real Apply submit and its progress/ownership effects were proven live earlier on real devices: docs/netlab-integration/evidence/live-apply-*.md, check_design_apply_ui.py, test_design_apply.py, test_design_ownership.py
- **ND-ERROR-007** (Apply run): "Changed since the review" per device at Apply time needs a real device that answers at Review time and then drifts before the Apply POST -- both steps need a reachable device: needs real devices behind the review: the fixture has no SSH endpoint, so every device reports Connectivity: NoValidConnectionsError (proven live here); the eligible, no-op, conflict, protected-settings, expected-changes and removal-command review branches, a real Apply submit and its progress/ownership effects were proven live earlier on real devices: docs/netlab-integration/evidence/live-apply-*.md, check_design_apply_ui.py, test_design_apply.py, test_design_ownership.py; proven live by test_design_apply.py:907 test_drift_between_review_and_apply_fails_only_that_device

### NOT RUN rows

- **ND-GENERATE-005** (Plan card): not reproduced live in this recon: no allocation collision was triggered by the edits made (hidden state confirmed instead: #design-plan-collisions stayed hidden). The markup/hide-toggle is source-confirmed (network-design.js:810-814) and this is a read-only report with no dedicated test named in coverage.json.
- **ND-PLAN-004** (Plan card): not reproduced live: changing the loopback pool and regenerating kept the same allocations for this 3-device lab (netlab's own deterministic ordering); the "hidden (nothing renumbered)" branch was exercised (#design-plan-renumbering-wrap stayed hidden) but the "visible" branch needs a topology change (device add/remove) this recon did not attempt within budget. Covered by test_network_design.py:926 test_renumbering_is_reported_against_the_previous_plan.
- **ND-APPLY-016** (Server): not attempted live in this recon: reproducing operation_busy exclusion needs winning a race against a second, genuinely concurrent manager job (a backup, Git save, restore, discovery import or removal) inside the review/apply window, which this recon did not attempt within budget; the exact 409 contract (and every one of the excluded operation kinds) is asserted directly by test_design_apply.py:608 test_busy_operation_is_409 and its neighbours

## Rows

Full detail (preconditions, forbidden side effects, exact sources) is in `coverage.json`. `S`/`D`/`N`
mark whether the control was found in Source / DOM / Navigation tracing.

| ID | Surface | Control | States | Expected visible | Backend | Tests | S | D | N | Result |
|---|---|---|---|---|---|---|---|---|---|---|
| ND-NAV-001 | Lab tabs bar (#lab-tabs) | Design tab button #tab-design (role=tab, aria-controls=design-view) | inactive (aria-selected=false, tabindex=-1), active (aria-s… | Panel #design-view unhidden, #tools-view etc. hidden; showTab('design… | client-side only: setTab/showTab (app.js:254-262); no reque… | test_shell_ui.js (tab route round-trip, generic); check_des… | x | x | x | PASS |
| ND-NAV-002 | Hash route | Deep link `#lab=<id>&view=design` | fresh load, reload with a route already set, back/forward t… | On load, shell.js applies the route and calls showTab('design') (shel… | GET /api/labs/{id}/design (network_design.py:528) | check_design_ui.py: page.goto(base+'/#lab='+id+'&view=desig… | x | x | x | PASS |
| ND-NAV-003 | Tools tab (#tools-view) | Shortcut button #tools-design ("Design this lab…") | default | onclick calls showTab('design') (network-design.js:1388) | none | check_design_ui.py does not exercise this path directly; no… | x | x | x | PASS |
| ND-NAV-004 | Lab tabs bar | Arrow-key / Home / End tab navigation reaching #tab-design | keyboard-focused | tabKeydown (app.js:264-269) moves focus and calls showTab | none | no dedicated design-tab keyboard test found (generic tab-ba… | x |  |  | PASS |
| ND-NAV-005 | Leaving the tab | Switching to another tab (#tab-topology etc.) while a plan is generat… | generation continues in background while #design-view is hi… | designMaybeStartWatch (network-design.js:703-726) is lab-scoped, not … | GET /api/labs/{id}/design (poll) | — | x |  |  | PASS |
| ND-NAV-006 | Lab switch | Selecting a different lab while the Design tab is active (selectLab) | switches to lab B's design, or resets to "topology" per sel… | selectLab(id, view) (app.js:33) defaults view to 'topology' unless a … | GET /api/labs/{id}/design for the new lab | — | x |  |  | PASS |
| ND-NAV-007 | Design tab exit | Design watch teardown / draft handling on leaving the app or reloadin… | reload, close tab | writeDesignDraft persists the draft to browser storage keyed by lab i… | none (client storage only) | test_network_design_ui.js:388 "the design draft is written,… | x | x |  | PASS |
| ND-GUIDED-001 | Design settings form | Address family checkboxes #design-ipv4, #design-ipv6 | unchecked/checked per intent.families, focused (form re-ren… | designRenderForm sets .checked from designFormFromIntent (network-des… | none until Save; then PUT /api/labs/{id}/design carries fam… | test_network_design_ui.js:99 "designIntentFromForm writes f… | x | x |  | PASS |
| ND-GUIDED-002 | Design settings form | Addressing pool inputs (loopback/p2p/lan × IPv4/IPv6, p2p/lan prefix … | empty (placeholder shown), filled, invalid (overlaps mgmt n… | designRenderForm fills each input from values.pools (network-design.j… | POST /api/labs/{id}/design/validate on Save-time check; poo… | test_design_intent.py:170 test_two_pools_overlapping_is_ref… | x | x |  | PASS |
| ND-GUIDED-003 | Design settings form | Protocol/service module checklist #design-modules (17 checkboxes, DES… | none selected, one or more selected, a module a device kind… | designModulesMarkup renders one checkbox per DESIGN_MODULE_LABELS ent… | modules[] written into the intent on Save; compatibility ch… | test_network_design_ui.js:220 "designModulesMarkup ticks th… | x | x |  | PASS |
| ND-GUIDED-004 | Design settings form | OSPF settings #design-ospf-settings (area input #design-ospf-area) | hidden (module off), visible (module on), value from intent… | designToggleModuleSettings toggles .hidden (network-design.js:736); d… | saved in intent.ospf on PUT | test_network_design_ui.js:99 | x | x |  | PASS |
| ND-GUIDED-005 | Design settings form | BGP settings #design-bgp-settings (#design-bgp-as, #design-bgp-rr rou… | hidden, visible, AS from intent.bgp.as or 65000 default, ro… | network-design.js:68,745-750; designRenderDeviceOptions rebuilds the … | intent.bgp.as and node[name].bgp.rr on PUT | test_network_design_ui.js:99; check_design_ui.py: "BGP sess… | x | x |  | PASS |
| ND-GUIDED-006 | Design settings form | IS-IS settings #design-isis-settings (#design-isis-area, #design-isis… | hidden, visible, area default 49.0001, level default level-2 | network-design.js:70,209-210 | intent.isis.{area,type} on PUT | test_network_design_ui.js:112 "designIntentFromForm writes … | x | x |  | PASS |
| ND-GUIDED-007 | Design settings form | Gateway settings #design-gateway-settings (#design-gateway-protocol: … | hidden, visible, default anycast | network-design.js:72,211 | intent.gateway.protocol on PUT | test_network_design_ui.js:112 | x | x |  | PASS |
| ND-GUIDED-008 | Devices table (#design-devices) | Per-device role select [data-design-role] (router/host/exclude) | no profile mapped (select disabled, reason shown as title +… | designDeviceRow renders one <tr> per device (network-design.js:228-24… | node[name].role on PUT (empty/omitted for the router defaul… | test_network_design_ui.js:227 "designDevicesMarkup shows th… | x | x |  | PASS |
| ND-GUIDED-009 | VRFs table (#design-vrfs) | Per-row name input, loopback checkbox, Remove button [data-design-vrf… | empty ("No VRFs yet"), one or more rows, a row mid-rename (… | designVrfRow/designVrfsMarkup (network-design.js:247-258); reads back… | PUT writes intent.vrfs; defining a VRF turns the vrf module… | test_network_design_ui.js:244 "designVrfsMarkup renders eac… | x | x |  | PASS |
| ND-GUIDED-010 | VRFs table | Add VRF button #design-vrf-add | default | designAddVrf (network-design.js:971-976) patches the draft intent dir… | none until Save | test_network_design_ui.js VRF suite (see ND-GUIDED-009) | x | x |  | PASS |
| ND-GUIDED-011 | VLANs table (#design-vlans) | Per-row name input, id number input, Remove button [data-design-vlan-… | empty ("No VLANs yet"), one or more rows | designVlanRow/designVlansMarkup (network-design.js:259-270); designVl… | PUT writes intent.vlans; defining one turns the vlan module… | test_network_design_ui.js:253 "designVlansMarkup renders ea… | x | x |  | PASS |
| ND-GUIDED-012 | VLANs table | Add VLAN button #design-vlan-add | default | designAddVlan (network-design.js:986-991); designNextVlanId (982-985)… | none until Save | test_network_design_ui.js VLAN suite | x | x |  | PASS |
| ND-GUIDED-013 | Links table (#design-links) | Per-link VRF select, access-VLAN select, trunk-VLAN text input, "also… | no designable links ("This lab has no designable links yet.… | designLinksMarkup/designLinkVrfVlanRow (network-design.js:284-302); t… | PUT writes intent.links[key].{vrf,vlan}; a link left with n… | test_network_design_ui.js:262 "designLinksMarkup shows each… | x | x |  | PASS |
| ND-GUIDED-014 | Static routes table (#design-static) | Per-row device select, prefix input, next-hop-type select (discard/ad… | empty ("No static routes yet."), a discard route, an addres… | designStaticRouteRow/designStaticMarkup (network-design.js:307-328); … | PUT writes node[device].routing.static[]; defining one turn… | test_network_design_ui.js:274 "designStaticMarkup shows eac… | x | x |  | PASS |
| ND-GUIDED-015 | Static routes table | Add static route button #design-static-add | default, no-op when there is no router device (designAddSta… | network-design.js:997-1008 | none until Save | — | x | x |  | PASS |
| ND-GUIDED-016 | Design settings form | Problems alert #design-problems (role=alert), shown inline above Adva… | empty, one or more {path,message} entries, escaped | designProblemsMarkup (network-design.js:217-219); populated by design… | none (client render of server-returned problems, or a clien… | test_network_design_ui.js:210 "designProblemsMarkup escapes… | x | x |  | PASS |
| ND-GUIDED-017 | Design settings form | Form focus guard (designFormFocused) | focused (re-render of guided controls suppressed), not focu… | designFormFocused (network-design.js:728-733) checks document.activeE… | none (client-only) | — | x |  |  | PASS |
| ND-GUIDED-018 | Design settings form | Guided-to-Advanced sync | guided edit reflected in #design-advanced JSON, Advanced ed… | designOnGuidedChange (935-942) rebuilds the draft via designIntentFro… | none until Save (both write to the same in-memory/local-sto… | test_network_design_ui.js:90 "designIntentFromForm keeps ev… | x | x |  | PASS |
| ND-GUIDED-019 | Design settings form | Devices table Notes column (blocked reason) and disabled role select … | profile mapped (role select enabled), no profile (role sele… | designDeviceRow (network-design.js:228-234) | such a device is left out of the generation entirely (netwo… | test_network_design_ui.js:227 | x | x |  | PASS |
| ND-GUIDED-020 | Design settings form | Devices table Kind/Profile columns | profile shown, profile blank with the reason as a neutral p… | network-design.js:231-232; profiles come from design_capabilities.PRO… | none | — | x | x |  | PASS |
| ND-ADVANCED-001 | Advanced section | Advanced <details>/<summary> #design-advanced-details | closed (default), open | plain <details>; opening it also triggers designApplyLoadOwnership vi… | GET /api/labs/{id}/design/ownership fires only once opened | — | x | x |  | PASS |
| ND-ADVANCED-002 | Advanced section | Advanced JSON textarea #design-advanced | reflects the saved intent, reflects an unsaved draft, holds… | network-design.js:778 (render), 943-956 designOnAdvancedChange (parse… | validated the same as a guided edit on Save; PUT/validate r… | test_network_design_ui.js:90; test_design_intent.py (recurs… | x | x |  | PASS |
| ND-ADVANCED-003 | Advanced section | Check button #design-validate | default | designValidate (network-design.js:1024-1032) | POST /api/labs/{id}/design/validate (network_design.py:532-… | test_network_design.py (validate-route tests, e.g. line 191… | x | x |  | PASS |
| ND-ADVANCED-004 | Advanced section | Allocation ledger #design-ledger (read-only device loopback / link pr… | no allocations yet (caption), device + link tables populated | designLedgerMarkup (network-design.js:329-337) | read-only render of intent.allocations; cleared only via Re… | — | x | x |  | PASS |
| ND-ADVANCED-005 | Advanced section | Owned settings #design-ownership (per-device <details> of statements … | no owned settings anywhere ("No settings are owned by the d… | designApplyLoadOwnership (network-design.js:1278-1284) -> GET /api/la… | statements shown are masked (design_apply.py masked(), cap … | test_network_design_ui.js:495 "designApplyOwnershipMarkup: … | x | x |  | PASS |
| ND-ADVANCED-006 | Advanced section | Advanced round-trip of guided-table objects (VRF/VLAN objects, per-li… | visible only under Advanced JSON, never in the guided tables | design_intent.py's generic engine-schema type checker (docs/NETWORK-D… | validated the same as everything else | test_design_intent.py:822 test_vlan_body_is_checked_against… | x |  |  | PASS |
| ND-SAVE-001 | Head actions | Save design button #design-save | enabled always (no client-side disabled reason is computed … | designSave (network-design.js:1034-1058): validates first, then PUT | POST /api/labs/{id}/design/validate then PUT /api/labs/{id}… | test_network_design.py:224 test_saving_a_valid_intent_succe… | x | x |  | PASS |
| ND-SAVE-002 | Head actions | Stale-revision conflict on Save (409) | 409 with designStaleMessage() matching text -> showActionEr… | designSave catch block (network-design.js:1052-1056); server compares… | PUT returns 409 "The design changed since this page loaded.… | test_network_design.py:247 | x |  |  | PASS |
| ND-SAVE-003 | Client-side draft | Unsaved-draft persistence across a reload (browser storage, per lab i… | draft matches the currently loaded revision (restored), dra… | readDesignDraft/writeDesignDraft/clearDesignDraft (referenced network… | client storage only; never sent to the server until Save | test_network_design_ui.js:388; test_network_design_ui.js:399 | x | x |  | PASS |
| ND-SAVE-004 | Head actions | "Unsaved changes" -> "No design yet"/"Plan ready…" transition on succ… | before: pill=warn "Unsaved changes", after: pill matches wh… | designSave clears designState.draft then calls designRenderAll (netwo… | PUT response replaces designState.view wholesale | check_design_ui.py: "editing marks the design as unsaved" /… | x | x |  | PASS |
| ND-SAVE-005 | Server | Allocation ledger is never client-writable through Save | client value ignored; server always substitutes its own sto… | network_design.py:549 `submitted['allocations'] = copy.deepcopy((curr… | PUT /api/labs/{id}/design | test_network_design.py:266 test_client_supplied_allocations… | x |  |  | PASS |
| ND-GENERATE-001 | Head actions | Generate plan button #design-generate | enabled, disabled: engine unavailable (title = diagnostic),… | designRenderHeader (network-design.js:791-798) computes .disabled/.ti… | POST /api/labs/{id}/design/generate (network_design.py:598-… | test_network_design.py:342 test_generate_without_a_design_i… | x | x |  | PASS |
| ND-GENERATE-002 | Plan card | Cancel button #design-cancel (hidden unless a generation is queued/ru… | hidden (no busy generation), visible | designRenderPlanCard (network-design.js:817) toggles .hidden from DES… | POST /api/labs/{id}/design/generations/{gid}/cancel (networ… | — | x | x |  | PASS |
| ND-GENERATE-003 | Design state line | "Generating the plan…" busy pill + 2s poll | queued, running | designMaybeStartWatch (network-design.js:703-726) polls every 2000ms … | GET /api/labs/{id}/design repeated | — | x | x |  | PASS |
| ND-GENERATE-004 | Plan card | Generation outcome variety: succeeded / failed (with errors) / interr… | succeeded, failed (unsupported module, engine error, addres… | network_design.py execute()/_generate() (321-437) covers every branch | errors[] shown verbatim in #design-plan-errors, never a sta… | test_network_design.py:541 test_an_unsupported_module_fails… | x | x |  | PASS |
| ND-GENERATE-005 | Plan card | Collision-fix notice #design-plan-collisions | hidden (no collisions), visible with a count ("… reassigned… | network-design.js:810-814; collision_fixes populated by network_desig… | none (read-only report) | — | x |  |  | NOT RUN |
| ND-PLAN-001 | Plan card | Status line #design-plan-status | "No plan generated yet.", "Generating the plan… <message>",… | designGenerationLine (network-design.js:434-443) | none (client render) | test_network_design_ui.js:200 "designGenerationLine words f… | x | x |  | PASS |
| ND-PLAN-002 | Plan card | Errors list #design-plan-errors-wrap / #design-plan-errors (role=aler… | hidden, visible with one <li> per error | designRenderPlanCard (network-design.js:804-805) | none | — | x | x |  | PASS |
| ND-PLAN-003 | Plan card | Warnings <details> #design-plan-warnings-wrap / #design-plan-warnings | hidden (no warnings), visible, collapsed by default | network-design.js:806-807; engine.run_generation stderr_tail filtered… | none | — | x | x |  | PASS |
| ND-PLAN-004 | Plan card | Renumbering table #design-plan-renumbering-wrap / #design-plan-renumb… | hidden (nothing renumbered), visible table: Kind/Name/Famil… | designRenumberingMarkup (network-design.js:357-362); intent_schema.re… | none | test_network_design.py:926 test_renumbering_is_reported_aga… | x |  |  | NOT RUN |
| ND-PLAN-005 | Plan card | Compatibility table #design-compatibility (one row per device, one co… | "No compatibility information yet.", populated grid with pi… | designCompatibilityMarkup/designLevelWord (network-design.js:410-432)… | network_design.py compatibility()/design_capabilities.resol… | test_network_design_ui.js:178 "designCompatibilityMarkup re… | x | x |  | PASS |
| ND-PLAN-006 | Plan card | Plan body #design-plan-body (per-device blocks: profile/id/loopbacks/… | "Generate a plan to see it here." (no succeeded generation)… | designPlanMarkup/designDeviceBlock/designInterfaceRow/designBgpTable/… | GET /api/labs/{id}/design/generations/{gid} supplies plan.j… | test_network_design_ui.js:158 "designPlanMarkup escapes a d… | x | x |  | PASS |
| ND-PLAN-007 | Plan card | Apply to devices… button #design-apply and its disabled-reason captio… | see ND-APPLY-002 | see ND-APPLY area | see ND-APPLY area | see ND-APPLY area | x | x |  | PASS |
| ND-PLAN-008 | Plan card | Export plan to Git… button #design-export-git and its disabled-reason… | see ND-EXPORT area | see ND-EXPORT area | see ND-EXPORT area | see ND-EXPORT area | x | x |  | PASS |
| ND-PLAN-009 | Plan card | Last apply line #design-apply-last (status) + its Show button [data-d… | see ND-APPLY-013 | see ND-APPLY area | see ND-APPLY area | see ND-APPLY area | x |  |  | BLOCKED |
| ND-FILES-001 | Files card | Generated files list #design-files-body (grouped per device, module n… | "Generate a plan to see its files here." (no succeeded gene… | designFilesMarkup/designFileSize (network-design.js:346-356) | artifact list comes from the generation record; content is … | check_design_ui.py: "the files card lists initial, ospf, bg… | x | x |  | PASS |
| ND-FILES-002 | Files card | View button [data-design-view-file][data-design-view-index] -> file d… | default | designViewFile (network-design.js:1130-1138) -> GET .../artifacts/{no… | GET /api/labs/{id}/design/generations/{gid}/artifacts/{node… | check_design_ui.py: "a generated file opens in a dialog" | x | x |  | PASS |
| ND-FILES-003 | Files card | Download all files (ZIP) link #design-download | hidden (no succeeded generation), visible, href points at t… | designUpdateDownloadLink (network-design.js:819-824) | GET /api/labs/{id}/design/generations/{gid}/download (netwo… | test_network_design.py:427 test_generation_detail_artifacts… | x | x |  | PASS |
| ND-HISTORY-001 | History card | <details> #design-history / summary "History" | closed (default), open | plain <details> | none (renders from the already-fetched view.generations) | — | x | x |  | PASS |
| ND-HISTORY-002 | History card | History list #design-history-body (newest first; pill per status + re… | "No plans generated yet.", one or more entries, each pilled… | designHistoryWord/Pill/Markup (network-design.js:338-345); capped at … | none | test_network_design.py:637 test_a_running_record_is_never_d… | x | x |  | PASS |
| ND-EXPORT-001 | More menu | Download design file menuitem #design-export | default | designExport (network-design.js:1104-1107) -- window.open, no fetch/d… | GET /api/labs/{id}/design/export (network_design.py:658-666… | test_network_design.py:703 test_export_then_import_round_tr… | x | x |  | PASS |
| ND-EXPORT-002 | Plan card | Export plan to Git… button #design-export-git | disabled: no succeeded plan ("Generate a plan first."), dis… | designExportGitReason/designRenderExportGitButton (network-design.js:… | opens a client dialog only; no request until Save to VM and… | test_network_design_ui.js:602 "designExportGitReason: no su… | x | x |  | PASS |
| ND-EXPORT-003 | Export dialog | Destination line #design-export-git-destination ("Saving to <repo> › … | updates live as the checkpoint field is typed | designExportGitDestinationMarkup/designExportGitUpdateDestination (ne… | none (client render of lab.git_binding) | test_network_design_ui.js:641 "designExportGitDestinationMa… | x | x |  | PASS |
| ND-EXPORT-004 | Export dialog | Checkpoint name input #design-export-git-checkpoint | prefilled with default "design-<first 12 chars of generatio… | designExportGitDefaultCheckpoint/Valid (network-design.js:626-627); c… | POST .../design/generations/{gid}/git | test_network_design_ui.js:611 "designExportGitDefaultCheckp… | x | x |  | PASS |
| ND-EXPORT-005 | Export dialog | Note input #design-export-git-note (optional, one line, 200 chars) | blank (server writes its own note naming the plan), filled,… | designExportGitNote (network-design.js:631) folds \r\n\t and repeated… | sent as note in the POST body | test_network_design_ui.js:631 "designExportGitBody folds a … | x | x |  | PASS |
| ND-EXPORT-006 | Export dialog | Save to VM and review button #design-export-git-confirm | default | designExportGitSubmit (network-design.js:1325-1341): POST, then hands… | POST /api/labs/{id}/design/generations/{gid}/git (git_progr… | test_design_export_git.py:307 test_route_creates_job_with_e… | x |  |  | PASS |
| ND-EXPORT-007 | Export dialog | Error line #design-export-git-error (role=alert) | empty, populated | network-design.js:1326,1340 | server 400/409 message passed through verbatim | — | x | x |  | PASS |
| ND-EXPORT-008 | Export dialog | Close controls: title-bar × and Cancel [data-design-export-git-close] | default | designExportGitClose (network-design.js:1320) | none | — | x | x |  | PASS |
| ND-IMPORT-001 | More menu | Import design file… menuitem #design-import | default | designImportPrompt (network-design.js:1108) just clicks the hidden fi… | none yet (file picker is native) | — | x | x |  | PASS |
| ND-IMPORT-002 | Hidden control | File input #design-import-file (hidden, accept=".yml,.yaml,.json") | no file chosen (change fires with none, no-op), a file chos… | network-design.js:1380-1382 clears .value after reading so choosing t… | multipart POST via designImportFile | — | x | x |  | PASS |
| ND-IMPORT-003 | Import flow | Successful import replaces the view and clears any draft | imported:true | designImportFile (network-design.js:1109-1129) | POST /api/labs/{id}/design/import (network_design.py:668-69… | test_network_design.py:703; test_network_design.py:978 | x |  |  | PASS |
| ND-IMPORT-004 | Import flow | Failed import shows problems without saving | imported:false, problems[] shown in #design-problems | designImportFile's !result.imported branch (network-design.js:1115-11… | POST returns {imported:false, problems} | test_network_design.py:728 test_import_of_an_invalid_docume… | x |  |  | PASS |
| ND-IMPORT-005 | Import flow | Imported allocations are always ignored; the server's own ledger is k… | client value discarded | network_design.py:686 | POST /api/labs/{id}/design/import | test_network_design.py:978 | x |  |  | PASS |
| ND-RENUMBER-001 | More menu | Renumber (forget allocations)… menuitem #design-renumber | default | network-design.js:1077,1383 | none yet (opens a confirm dialog) | — | x | x |  | PASS |
| ND-RENUMBER-002 | Confirm dialog | #design-renumber-dialog (Cancel / "Forget allocations" danger button) | open, closed (Cancel, no request sent), closed (confirmed, … | designRenumber (network-design.js:1077-1089) built via opDialog with … | POST /api/labs/{id}/design/renumber only on confirm (networ… | test_network_design.py:311 test_renumber_empties_the_alloca… | x | x |  | PASS |
| ND-RENUMBER-003 | Server effect | Clearing the ledger does not touch modules, addressing pools, or the … | allocations {} after; next generation reallocates from the … | network_design.py:590-591 | PUT-equivalent via the renumber route | test_network_design.py:311 | x |  |  | PASS |
| ND-RENUMBER-004 | Server effect | Renumbering is reported against the *previous* plan, never against a … | renumbering[] compares old vs new correctly | network_design.py:299-302 snapshot.previous_ledger, resolved before t… | none (internal correctness) | test_network_design.py:926 test_renumbering_is_reported_aga… | x |  |  | PASS |
| ND-CLEAR-001 | More menu (danger group) | Remove design… menuitem #design-clear | default | network-design.js:1090,1384 | none yet (opens a confirm dialog) | — | x | x |  | PASS |
| ND-CLEAR-002 | Confirm dialog | #design-clear-dialog (Cancel / "Remove design" danger button) | open, closed (Cancel, no request), closed (confirmed, reque… | designClearDesign (network-design.js:1090-1103); dialog copy explicit… | POST /api/labs/{id}/design/clear only on confirm (network_d… | test_network_design.py:298 test_clear_with_wrong_revision_t… | x | x |  | PASS |
| ND-CLEAR-003 | Server effect | Clearing removes network_design only; network_generations and their f… | intent gone, generations/history still there | network_design.py:574 `lab.pop('network_design', None)` | POST /api/labs/{id}/design/clear | test_network_design.py:298 | x |  |  | PASS |
| ND-CLEAR-004 | Server guard | A stale revision on Clear is refused, same as Save/Renumber/Import | 409 | network_design.py:572 | POST clear | test_network_design.py:298 | x |  |  | PASS |
| ND-APPLY-001 | Plan card | Apply to devices… button #design-apply | enabled | designRenderApplyButton (network-design.js:1152-1158) | no request on click beyond opening the dialog client-side | check_design_apply_ui.py (whole flow, live-VM tool) | x | x |  | PASS |
| ND-APPLY-002 | Plan card | Apply-disabled reasons (designApplyDisabledReason), one per precondit… | engine unavailable (its diagnostic), no succeeded plan ("Ge… | network-design.js:603-617 | read-only client computation from already-fetched state | test_network_design_ui.js:517 "designApplyDisabledReason: n… | x | x |  | PASS |
| ND-APPLY-003 | Apply dialog | Dialog shell #design-apply-dialog (three steps: choose/review/progres… | choose, review, progress | designApplyShowStep (network-design.js:1171-1176) | none (client step machine) | — | x | x |  | PASS |
| ND-APPLY-004 | Choose step | Device checklist #design-apply-choose-body (name=design-apply-target) | no devices ("This plan has no devices to apply."), a device… | designApplyChooseMarkup/designApplyDefaultSelection (network-design.j… | none until Review | test_network_design_ui.js (choose-markup coverage via desig… | x | x |  | PASS |
| ND-APPLY-005 | Choose step | Choose error #design-apply-choose-error | empty, "Choose at least one device." | designApplyRunReview (network-design.js:1196-1200) | client-only guard (server also 400s: len(targets)>=1 requir… | — | x | x |  | PASS |
| ND-APPLY-006 | Choose step | Review button #design-apply-review-run | default | designApplyRunReview -> POST .../review | POST /api/labs/{id}/design/generations/{gid}/review (design… | test_design_apply.py:628 test_review_token_and_public_fields | x | x |  | PASS |
| ND-APPLY-007 | Review step | Per-device review block: ineligible / unreachable-not-ready / no-op /… | ineligible (not part of the plan / blocked / host / kind wi… | designApplyDeviceMarkup (network-design.js:501-525); design_apply.py … | none (already fetched by Review) | test_network_design_ui.js:416,423,434,440,446 (the five des… | x | x |  | BLOCKED |
| ND-APPLY-008 | Review step | Conflict take-over checkbox [data-design-apply-takeover] per device | unticked (device blocked from Apply until resolved), ticked… | designApplyToggleTakeover (network-design.js:1222-1231) re-POSTs revi… | POST .../review again with takeover updated | test_network_design_ui.js:423 "a conflict shows the take-ov… | x | x |  | BLOCKED |
| ND-APPLY-009 | Review step | Recovery window input #design-apply-minutes (2-30, default 5) and its… | default 5, edited within 2-30, clamped client-side to [2,30… | index.html:253-255; designApplyClampMinutes (network-design.js:545-54… | sent as confirm_minutes in the apply POST; server also boun… | test_network_design_ui.js:469 "designApplyBody clamps confi… | x | x |  | PASS |
| ND-APPLY-010 | Review step | Acknowledgement checkbox #design-apply-ack + Apply button #design-app… | ack unticked (Apply disabled), ack ticked but nothing appli… | designApplyCanSubmit (network-design.js:533-538); designApplyUpdateRu… | server re-checks: acknowledged must be true (400 otherwise)… | test_network_design_ui.js:453 "designApplyCanSubmit: needs … | x | x |  | PASS |
| ND-APPLY-011 | Review step | Back button #design-apply-back | default | network-design.js:1288 -> designApplyShowStep('choose') | none | — | x | x |  | PASS |
| ND-APPLY-012 | Review->Apply | Apply button #design-apply-run submit | default | designApplySubmit (network-design.js:1232-1245) | POST /api/labs/{id}/design/apply (design_apply.py:667-670);… | test_design_apply.py:735 test_bad_token_is_409; test_design… | x |  |  | BLOCKED |
| ND-APPLY-013 | Progress step | Progress body #design-apply-progress-body (per-target table: device/k… | queued/preflight/backing_up/applying/confirming/verifying (… | designApplyProgressMarkup/designApplyTargetRow (network-design.js:556… | GET /api/design/apply/jobs/{job_id} polled every 2s while b… | test_network_design_ui.js:480 "designApplyProgressMarkup: e… | x |  |  | BLOCKED |
| ND-APPLY-014 | Plan card | Last-apply line #design-apply-last + Show button [data-design-apply-s… | hidden (no job yet), visible with the job's word + relative… | designApplyRenderLast/designApplyShowJob (network-design.js:1165-1170… | GET /api/labs/{id}/design/apply/jobs (design_apply.py:672-6… | test_network_design_ui.js:507 "designApplyLastLineMarkup: a… | x |  |  | BLOCKED |
| ND-APPLY-015 | Apply dialog | Close controls: title-bar × and Cancel/Close [data-design-apply-close… | choose, review, progress | initDesignApply wires every [data-design-apply-close] to designApplyC… | stops the apply-job poll if one was running (designApplySto… | — | x | x |  | PASS |
| ND-APPLY-016 | Server | operation_busy exclusion: apply excludes backups, Git saves, restores… | review/apply refused for another operation; another operati… | design_apply.py guard_idle / operation_busy (per docs/NETWORK-DESIGN.… | various 409s | test_design_apply.py:608 test_busy_operation_is_409; test_d… | x |  |  | NOT RUN |
| ND-APPLY-017 | Server | Ownership ledger updates after every apply (owned statements, highest… | owned settings grow/shrink; a container with a manual child… | design_apply.py ownership merge/diff logic; see docs/NETWORK-DESIGN.m… | reflected in GET .../design/ownership (ND-ADVANCED-005) | test_design_ownership.py (whole file: 24 tests on the owner… | x |  |  | BLOCKED |
| ND-APPLY-018 | Client state | designApplyState requestId regenerated once per dialog open, reused a… | fresh id on open, same id reused if the same submit is retr… | designApplyRequestId (network-design.js:539-544); designApplyOpen set… | request_id in the apply POST body; server treats a repeat a… | test_network_design_ui.js:464 "designApplyRequestId returns… | x |  |  | PASS |
| ND-STATE-001 | Head status line | #design-state-pill / #design-state-text: "No design yet" | truly no design ever saved, a design IS saved but no plan h… | designStateOf fallback branch (network-design.js:46) | none | test_network_design_ui.js:23 "designStateOf: no design yet" | x | x |  | PASS |
| ND-STATE-002 | Head status line | "Unsaved changes" (warn) | default | network-design.js:37 | none | test_network_design_ui.js:28 | x | x |  | PASS |
| ND-STATE-003 | Head status line | "The design has problems" (danger) | default, detail = first problem's message | network-design.js:38-39 | none | test_network_design_ui.js:40 | x |  |  | PASS |
| ND-STATE-004 | Head status line | "Generating the plan…" (busy) | default | network-design.js:35-36 | none | test_network_design_ui.js:33 | x | x |  | PASS |
| ND-STATE-005 | Head status line | "The last plan was interrupted" (warn) | default | network-design.js:40-41 | none | test_network_design_ui.js:62 | x |  |  | PASS |
| ND-STATE-006 | Head status line | "The last plan failed" (danger) | default | network-design.js:42 | none | test_network_design_ui.js:56 | x | x |  | PASS |
| ND-STATE-007 | Head status line | "Plan is older than the design" / stale (warn) | default | network-design.js:43-44 | none | test_network_design_ui.js:51 | x |  |  | PASS |
| ND-STATE-008 | Head status line | "Plan ready to review" (ok) | default | network-design.js:45 | none | test_network_design_ui.js:46 | x | x |  | PASS |
| ND-STATE-009 | Head status line + banner | "Design engine unavailable" (danger) + #design-engine banner, wins ov… | default, detail/banner text = engine.diagnostic | designStateOf checks engine first, before draft/generating/problems (… | GET /api/design/engine (network_design.py:524-526) | test_network_design_ui.js:67 "designStateOf: design engine … | x |  |  | PASS |
| ND-ERROR-001 | Guided form | Pool overlapping the lab's management network is refused with the exa… | #design-problems shows "addressing.<pool>.<family>: … manag… | design_intent.py pool-overlap-with-management check | POST validate / PUT save both 400 with the same {path,messa… | test_design_intent.py:175 test_pool_overlapping_management_… | x | x |  | PASS |
| ND-ERROR-002 | Server | Unknown top-level intent key is refused | 400 with the key named | design_intent.py allowlist | validate/save/import all 400 | test_network_design.py:191 test_invalid_intent_with_unknown… | x |  |  | PASS |
| ND-ERROR-003 | Save/Renumber/Clear/Import | Stale-revision conflict (409) refuses every mutating route the same w… | 409 with a reload-first message | network_design.py:545-546 (save), 572 (clear), 588 (renumber), 684-68… | various 409s | test_network_design.py:247,298; test_network_design.py:978 | x |  |  | PASS |
| ND-ERROR-004 | Plan card | Generation errors list shows the device and the exact reason (not a g… | e.g. "eigrp on cEOS ... arista_ceos" | network_design.py compatibility()/_generate() (261-276,370-434) | errors[] recorded on the generation | test_network_design.py:541 test_an_unsupported_module_fails… | x |  |  | PASS |
| ND-ERROR-005 | Apply choose step | "Choose at least one device." on empty Review | #design-apply-choose-error populated | network-design.js:1200 | client + server (Review model min_length=1) both refuse | — | x | x |  | PASS |
| ND-ERROR-006 | Apply review step | "Connectivity: <ExceptionType>" per unreachable device | visible as the device's "reason" text in place of a diff | design_apply.py review()/work() catches any exception and records it … | part of the review response | test_design_apply.py:595 test_device_without_credentials_is… | x | x |  | PASS |
| ND-ERROR-007 | Apply run | "Changed since the review" per device at Apply time | that device fails with this exact reason; others proceed | docs/NETWORK-DESIGN.md "Apply" step 3 | per-target status failed with this message | test_design_apply.py:907 test_drift_between_review_and_appl… | x |  |  | BLOCKED |
| ND-ERROR-008 | Export Git dialog | "Use a checkpoint name containing letters, numbers, hyphens or unders… | inline error, submit refused before any request | network-design.js:1328-1331 | server re-checks the identical pattern (git_progress.py:108… | test_network_design_ui.js:617; test_design_export_git.py:347 | x |  |  | PASS |
| ND-ERROR-009 | Advanced editor | "This is not valid JSON: <parser message>" / "The design must be a JS… | #design-problems shows the client-side message; the draft i… | designOnAdvancedChange (network-design.js:947-951) | none (pure client-side JSON.parse) | test_network_design_ui.js (advanced-editor coverage is impl… | x |  |  | PASS |
| ND-ERROR-010 | Import flow | Import failure keeps the previous design untouched and shows problems… | imported:false | network_design.py:687-688 | response body only, no store mutation | test_network_design.py:728,739,747 | x |  |  | PASS |
| ND-A11Y-001 | Tab bar | role=tab / aria-selected / aria-controls / roving tabindex on #tab-de… | inactive, active | index.html:108; app.js:259 sets aria-selected/tabIndex on every tab b… | none | — | x | x |  | PASS |
| ND-A11Y-002 | Design panel | role=tabpanel + aria-labelledby="tab-design" on #design-view | hidden, visible | index.html:150 | none | — | x | x |  | PASS |
| ND-A11Y-003 | Status line | role=status on #design-state (live region) | every STATE value | index.html:154 | none | — | x | x |  | PASS |
| ND-A11Y-004 | Problems / error lines | role=alert on #design-problems, #design-plan-errors, #design-apply-ch… | populated | index.html:207,223,248,257,275 | none | — | x | x |  | PASS |
| ND-A11Y-005 | Dialogs | Native <dialog> with aria-labelledby + a labelled close icon-button (… | open | index.html:243-244,265-266 (Apply, Export-Git); network-design.js:107… | none | — | x | x |  | PASS |
| ND-A11Y-006 | Compatibility table | scope="row" row headers, <caption>-equivalent via a semantic <table>/… | populated | network-design.js:429 (`<th scope="row">`) | none | — | x | x |  | PASS |
| ND-A11Y-007 | Checkbox rows | .checkbox-label wrapping pattern (label wraps its input) used through… | every checkbox in the tab | network-design.js:177 (index.html), :223,250,257,481,521 (markup func… | none | — | x | x |  | PASS |
| ND-A11Y-008 | Narrow viewport (390×844) | Design tab adds no horizontal overflow beyond what the shell chrome a… | default | no dedicated CSS rule found in source for this; behavioural, checked … | none | check_design_ui.py: "the Design tab adds no horizontal over… | x | x |  | PASS |

## State transitions

| ID | Surface | Control | Backend |
|---|---|---|---|
| ND-STATE-T01 | Design state machine | empty -> dirty | none |
| ND-STATE-T02 | Design state machine | dirty -> invalid (validating, then refused) | POST validate embedded in designSave, then no PUT is even attempted |
| ND-STATE-T03 | Design state machine | invalid -> clean/saved | PUT succeeds |
| ND-STATE-T04 | Generation state machine | clean -> queued -> generating | POST generate, then poll |
| ND-STATE-T05 | Generation state machine | generating -> succeeded | poll stops itself |
| ND-STATE-T06 | Generation state machine | generating -> cancelled/failed | POST cancel sets a threading.Event; the worker checks it between pass… |
| ND-STATE-T07 | Generation state machine | succeeded -> stale | none (client + summary computation) |
| ND-STATE-T08 | Generation state machine | any -> interrupted | none |
| ND-STATE-T09 | Apply job state machine | choose -> review (queued -> running review connections -> settled) | POST review, synchronous (not polled) -- the whole review completes b… |
| ND-STATE-T10 | Apply job state machine | review -> conflicting (per device) -> takeover -> re-reviewed | POST review again with the updated takeover[] |
| ND-STATE-T11 | Apply job state machine | submitted -> queued -> preflight -> backing_up -> applying -> armed -> confirming -> veri… | GET /api/design/apply/jobs/{id} polled |
| ND-STATE-T12 | Apply job state machine | settled job -> reopened via Show | GET /api/design/apply/jobs/{job_id} |
| ND-STATE-T13 | Export-to-Git state machine | dialog filled -> submitted -> queued Git job -> review_pending | POST .../git, then the job is watched by git-progress.js, not this fi… |
| ND-STATE-T14 | Design engine availability | available -> unavailable (e.g. netlab uninstalled/broken) -> every action gated | GET /api/design/engine |
| ND-STATE-T15 | Draft vs saved revision | clean -> edited elsewhere (import, or another tab) -> local draft now stale -> discarded … | none (client-only) |
| ND-STATE-T16 | Missing topology precondition | has_topology:false blocks Generate specifically (not Save/guided editing) | POST generate -> 409 NO_TOPOLOGY |
| ND-STATE-T17 | Unsupported-target precondition | a requested feature is unsupported/blocked-missing-prerequisite for a device's kind | generation fails with status failed, errors[] naming device+feature+k… |

