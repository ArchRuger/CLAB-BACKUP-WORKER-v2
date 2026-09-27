# A plan exported to Git through the deployed product (`restore-square`, 2026-09-27)

Tool: `docs/netlab-integration/tools/check_design_export_ui.py` (Playwright, Chromium 153) against the manager rebuilt
from the 1.30.47 tree on the development VM (http://192.168.132.132:8081), the lab bound to the QA repository
`CLAB-MNGR-DEV-LLM` (folder `restore-square/qa-1-30-37`, remote on GitHub), the plan `57371369e14e` (the E6 design:
IS-IS + BGP, policy, static routes, two VLANs).

## Runs

1. **Refused: an empty generated file.** The first export answered 400 "A generated file is empty or too large to
   export.": netlab had written an empty `vlan` fragment for cJunosEvolved (the module on, no VLAN port). The Git helper
   refuses empty files, so the export now leaves an empty fragment out (`tests/test_design_export_git.py`).
2. **Failed: "Another Git operation is already running for this repository."** The job reached the helper's
   `publish` while the Progress tab's own history read held the helper's per-repository lock (a non-blocking lock:
   the second caller fails). Fixed in the manager: helper calls from one manager are serialised
   (`GitProgress.helper_lock`), so a page reading while a save publishes waits instead of failing; the same race
   existed for ordinary saves.
3. **12 of 12 checks, 0 console errors, 0 page errors:** *Export plan to Git…* offered for the bound lab's plan; the
   dialog names the repository and `…/checkpoints/design-57371369e14e-86fb`; the request accepted; the job of kind
   `design` with the checkpoint destination; saved on the VM and stopped at `review_pending`; the review dialog opened
   by itself, titled as a design export and listing `network-intent.yml` and `plan.json` under the checkpoint folder;
   the upload through the review's own button ended `synced`; the repository history lists the checkpoint; its
   manifest is `kind: network-design` with no device rows; no restore candidate.

## The repository afterwards (read on the VM checkout, independently of the manager)

- `HEAD` = `6fadd0c "Design export check 03:28"`, present on the remote (`git ls-remote`); the commit touches only
  `restore-square/qa-1-30-37/checkpoints/design-57371369e14e-86fb/` — 26 files: `manifest.json`,
  `network-intent.yml`, `plan.json`, `topology.yml`, `mapping.json` and the device fragments
  (`ceos--00-normalize.cfg` … `xrv9k--…`; cJunosEvolved's empty `01-vlan` left out); **`latest/` untouched**
  (0 lines of the commit's stat mention it).
- The manifest: `kind network-design`, the plan's id, `modules [isis, bgp, vlan, routing]`, `devices [ceos,
  cjunosevolved, host1, vjunos-switch, xrv9k]`, `restore_capable_nodes 0`.

Screenshots: `shots/design-export-01-dialog.png`, `shots/design-export-02-review.png`,
`shots/design-export-03-uploaded.png`.
