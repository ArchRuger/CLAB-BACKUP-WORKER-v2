# D04: lab operations guide against the code (campaign 2, 2026-10-27)

Scope: `docs/LAB-OPERATIONS.md`, `docs/TOUR.md` (where it names the topology editor). Base commit 64e8b66.
Evidence class: static (code and design read; no browser, no VM, no live device in this task). The live facts
are quoted from `docs/parity-campaign/evidence/t07-live-topology-editing-2026-10-27.md`, not re-run.

## Claim table

| # | Claim now in the guide | Where it is true | Result |
|---|---|---|---|
| 1 | Edit map is "positions and drawing, kept in the manager"; Edit topology is "devices and links, saved to the lab file on the VM; applying is a separate step" | `index.html` button titles (`#map-edit`, `#topology-edit`); design 12.1 #11 | confirmed |
| 2 | Entry in three places: map tools beside Edit map, Lab actions > Advanced options, Tools > Map card; at phone width in More | `index.html` lines 136, 158, 188; design 12.1 #10; T07 step 11 (live, 390 px) | confirmed |
| 3 | Inline reasons: no VM file; VM not connected; helpers older than the manager; operation running; status unknown; file outside the trusted folders | `opTopologyEditReason` (`operations.js`) in that order; shown by `data-proxy-reason` (`app.js`), `menu-reason`, the button title | confirmed |
| 4 | Save review sentences: running and stopped counts; saving replaces file and map layout only; applying is a separate step | `host_operations.py` revise warnings (counts by state) | confirmed |
| 5 | "Running devices the new file does not define ... keep running until the changes are applied" | `deployed_save_warnings` | confirmed |
| 6 | "Devices whose definition changed" with kind, image, environment, startup configuration; rename shown as "renamed to"; recreate loses unsaved configuration | `deployed_save_warnings`, `DEFINITION_FIELDS` | confirmed (rename is in the changed sentence, not the removed one: worded so) |
| 7 | No-dry-run sentence in the save review | `deployed_save_warnings(dry_run=False)` | confirmed |
| 8 | Review bound to the listed devices (name and id) | design 12.4 R3/R16/A11; `host_operations.py` revise comment | confirmed (static; helper tests not run here) |
| 9 | A deployed save never deploys, restarts, recreates or removes; Devices and map keep showing what runs; re-registration only after a successful apply, deploy or redeploy | `REGISTER_ACTIONS`, `reregister` call in `lab_operations.py` ("A deployed save (revise) never does this") | confirmed |
| 10 | Dialog text "Saved to the VM. The running lab is unchanged until you apply the changes"; pill "Saved on the VM · not applied" | `opDeployedSaveMarkup`; `lab-builder-page.js` line 302 | confirmed |
| 11 | "Back to lab and review changes…" in the bar and in the save dialog opens `/#lab=<id>&view=topology&review=apply`, the lab page runs the apply review once | `lab-builder.html` `#builder-review`, `opBackToReviewHash`, `shell.js` `readReview`/`tryRouteReview` | confirmed |
| 12 | Apply review lists create/start/restart/recreate/remove, links to connect, link ends to disconnect, reasons | `OP_PLAN_SECTIONS`, `opPlanMarkup` | confirmed |
| 13 | Per-device limit sentence under the row; "Back up these devices first: ..." above the plan | `opPlanMarkup` (`limits`), `opBackupFirstMarkup`, `annotate_plan` (backup_first = every device with a limit) | confirmed |
| 14 | linux host: link changes without a restart | T07 table (`Applying link change without node lifecycle action`) | confirmed (live, by T07 evidence) |
| 15 | cEOS: link change restarts it in place; unsaved running configuration lost, startup kept | `CEOS_LINK_RESTART`; T07 (same container id, about 2 s) | confirmed (live, by T07 evidence) |
| 16 | vSRX: recreated, configuration lost; other VM kinds "expected" | `VRNETLAB_LINK_RECREATE` ("Proven on vSRX; expected on the other VM-based kinds"); T07 | confirmed; the other kinds stay unverified, as worded |
| 17 | After apply/deploy/redeploy succeeds the manager re-reads the file; map changed in the manager is kept | `reregister`, `Runner.map_changed_in_manager`, design 12.6 | confirmed |
| 18 | Pending-changes notice is one summary line plus Review changes...; it prints NO limit sentences | `opPendingMarkup`, `opPlanSummary` | the brief asked for "the plan's limits appear there too": contradicted by the code. The check's plan is annotated (`impairments.py` calls `annotate_plan`) but the notice does not print `limits`; the guide says the limits are in the review the button opens |
| 19 | Device menu order: Open CLI, Console (3 kinds), Capture traffic..., Back up configuration, Restart device..., Stop device..., Start device..., Device details | `topology.js` lines 154-160 | corrected (old text lacked the ellipsis and Stop/Start) |
| 20 | Link state "paused" when the lab status is Unknown, with no request | `map-tools.js` line 10, 134 | already correct, unchanged |
| 21 | Shortcuts dialog: Find's Enter fits, Escape clears the field and keeps the expanded map; builder drawing Ctrl+Z / Ctrl+Shift+Z / Ctrl+Y; YAML panel Ctrl+Enter, Escape | `index.html` `#shortcuts-dialog`; `map-tools.js` 295-296 | corrected in the Help section |
| 22 | "Save changes to the VM... only for a lab that is not deployed" (Removed in earlier releases paragraph) | retired by design 12.1 #6 and `RUNNING_REVISE_SENTENCE` | contradicted; rewritten |
| 23 | "Structural topology changes are made in the original VM YAML" | superseded by Edit topology | rewritten |

## Paragraphs changed or added in LAB-OPERATIONS.md

Changed: Advanced options list; operations table rows *Apply topology changes…*, *Edit map*, *Build a lab
visually… / Edit topology…*; the "Removed in earlier releases" paragraph; the keyboard shortcuts paragraph; the
draw.io closing paragraph; the device right-click sentence in the map section.
Added: **Apply topology changes** (new, before Diagnostics) and **Edit topology: devices and links** (new, after
the Arrange paragraph in the map section).
TOUR.md: the Tools paragraph and the Lab actions Advanced options sentence name Edit topology...

## Not verified

No browser, fixture or live run was made. The helper and manager tests that pin the deployed-save contract were not run.
The guide's per-kind facts rest on T07 (containerlab 0.79; cEOS, vSRX and linux only); vJunos, cJunosEvolved and
XRv9k reconcile behaviour is not claimed beyond "expected".
