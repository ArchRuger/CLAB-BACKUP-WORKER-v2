# Requirements matrix — "Ui/Ux Changes" email (UIUX-EMAIL-2026-10-03)

Source: the decoded email body and its 17 body-referenced screenshots (kept outside the checkout;
image names below are the bundle's `source/images/` names). IDs 9 and 10 are tracking labels for the
email's two closing, unnumbered requests; 8f is the text-only closing paragraph of Task #8.

Status values: `open`, `in progress`, `implemented` (code + unit tests), `done` (implemented and its
acceptance evidence exists), `blocked` (with reason).

| ID | Request (short) | Source image | Relevant files | Acceptance checks | Evidence | Status |
|---|---|---|---|---|---|---|
| 1 | Built-in templates pre-baked with n24l images | T01-node-template.png | `app/static/lab-builder-page.js` (`BUILDER_TEMPLATES` pinned, `builderMigrateTemplates`) | fresh profile add ×4, fields + YAML, draft/VM round trip, custom template untouched, references valid on dev1 | unit `test_lab_builder_ui.js` (images, pinned vs Linux preference, migration cases); fixture browser: four templates add nodes, Image/Version split, each reference once in YAML; `evidence/t01-*.png`; references resolve on dev1 (`docker manifest inspect`, pulled) | implemented |
| 2 | One persistent, replaceable, dismissible image-check notice; red errors | T02-image-check-notices.png | `lab-builder-page.js` (`builderImageCheck/Render/Dismiss/Key`, `builderImageSummary`), `lab-builder.{html,css}` | repeat/dismiss/new check, rapid edits, out-of-order responses, draft switch | unit: stale seq, draft switch, dismiss not resurrected, superseded, error outranks success, request failure; fixture browser: red error with role=alert, keyboard dismiss, single slot; `evidence/t02-*.png` | implemented |
| 3 | Center label placement, opaque readable background | T03-center-node-label.png | `lab-builder/patches.mjs` + rebuilt bundle, `map-editor-page.js`, `topology-render.js`, `drawio_export.py` | crowded links, long labels, zoom, drag, save/reopen, manager render | unit: bundle option/case, validator, renderer, drawio, topology round trip; fixture browser: centred, rgba(0,0,0,.94), pointer-events none, select/context menu work, zoom, long name; `evidence/t03-*.png`. Save-to-VM/reopen pending live | implemented |
| 4a | Save review: images warnings/errors only | T04a-save-image-noise.png | `app/static/operations.js` (`opImageAttention`, `opReviewImages`, `opReview`) | all-clear, failure, mixed, unavailable, retry | unit `test_operations_ui.js`; fixture browser: Save review not yet exercised in browser | implemented |
| 4b | Remove placeholder "Command run on the VM: Save lab to the VM" | T04b-placeholder-command.png | `app/static/operations.js` (`opReview` command block only with real argv/steps) | block absent; meaningful review content kept | unit `test_operations_ui.js` (create review has no placeholder command) | implemented |
| 4c | Start review: images warnings/errors only | T04c-start-image-noise.png | `app/static/operations.js` | as 4a in Start review | fixture browser: `evidence/t04c-start-review{,-allclear,-failed}.png` (all-clear: no section; not-found row; failed check warning) | implemented |
| 5a | After "Add without starting": Deploy now / Go to My labs | T05a-post-save-loop.png | tbd | both buttons, no implicit deploy, no duplicates | — | open |
| 5b | Closing post-save window returns cleanly to the editor | T05b-orphan-overlays.png | tbd | X/Escape/Cancel, repeated, no orphan layers, focus restored | — | open |
| 6 | Align "Connect a save location…" and "Start lab" | T06-action-alignment.png | `app/static/style.css` (`--lab-action-col` grid on `.lab-header` and `#lab-banner`) | bounding boxes at desktop widths, narrow wrap | fixture browser: left edges equal (0 px) at 1280/1600/1920 in four banner states and two save-button labels; 390 px no clipping; `evidence/t06-*.png` | implemented |
| 7 | cJunosEvolved real hostname | T07-cjunosevolved-hostname.png | tbd | fresh deploy, NOS read-back, restart, redeploy, custom hostname kept | — | open |
| 8a | Retire EIGRP, RIP, VXLAN from design services | T08a-protocol-selection.png | tbd | UI absent, backend refuses new generate/apply, old designs readable | — | open |
| 8b | Compact route-reflector grid | T08b-route-reflectors.png | tbd | 0/few/many, long names, keyboard, save/reopen, small screens | — | open |
| 8c | Obvious Save design / Generate plan errors | T08c-validation-errors.png | tbd | IPv6/family and BGP AS examples, backend failure, retry | — | open |
| 8d | EVPN: real MPLS path or gate it | T08d-evpn-transport.png | tbd | documented finding + chosen behaviour | — | open |
| 8e | Status log while "Reviewing N devices…" | T08e-device-review-pending.png | tbd | real progress, slow/unreachable, close≠cancel, retry, no duplicates | — | open |
| 8f | Network design under Advanced → Experimental, "Under construction / Under review" | text only | tbd | not prominent, old links handled, warning inside feature | — | open |
| 9 | Technical view replaces the device cards | T09-technical-view.png | `app/static/app.js` (`showTab`, `renderNodes`, `renderDeviceList`), `index.html` | one presentation at a time, actions and state consistent | unit `test_download_ui.js`; fixture browser: exactly one region visible across toggles, search filters the table, topology rail kept; `evidence/t09-*.png` | implemented |
| 10 | Remove packet-capture Search | T10-capture-search.png | `app/static/index.html`, `app/static/capture.js`, `tests/test_capture_ui.js`, two Playwright tools | control and state gone, rest of capture flow intact | unit `test_capture_ui.js` (all targets listed, aliases in labels, single target auto-selected) | implemented |

## Interpretation notes

- **cEOS reference.** The email writes `N24l/ceos:4.35.0F`; its screenshots use `n24l/ceos:4.35.0F`.
  On dev1 (2026-10-03) `docker manifest inspect N24l/ceos:4.35.0F` fails: Docker's reference grammar
  only allows lowercase repository components, so `N24l` is parsed as a registry host name
  (`lookup N24l … server misbehaving`). `n24l/ceos:4.35.0F` resolves on Docker Hub (single layer,
  ≈759 MiB). The default therefore uses `n24l/ceos:4.35.0F`: the namespace case is normalized, the tag
  `4.35.0F` is unchanged.
- **8f vs 8a–8e.** Moving Network design to Advanced → Experimental changes where it is exposed; the
  concrete fixes 8a–8e are still implemented inside the experimental area. No netlab redesign.
- **8d.** Conditional on whether this application's path supports EVPN over MPLS end to end.
