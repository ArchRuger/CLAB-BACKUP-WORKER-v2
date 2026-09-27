# Browser check of *Apply to devices…* on the deployed manager (2026-09-27)

Tool: `docs/netlab-integration/tools/check_design_apply_ui.py` (Playwright 1.63, Chromium 153.0.8010.12), run against
the manager rebuilt from the 1.30.45 tree on the development VM (http://192.168.132.132:8081) and the live lab
`restore-square`, whose devices carried the design from the earlier live runs (one owned description removed by
hand so the review had something to add). The tool was developed against the fixture manager (no devices: the
review ends "not ready", exit 3) and then run here.

## Run 1: review without applying (`--targets ceos`)

14 of 14 checks, 0 console errors, 0 page errors:

- the plan card offers *Apply to devices…* for the succeeded plan;
- the dialog lists the lab's devices; `host1` is disabled with "A support host is generated only, never applied.";
- at 1280×900 the dialog adds no horizontal overflow beyond the shell;
- the review of `ceos` renders the counts the API returned (added 1, removed 0, stale 0, conflicts 0, expected 0),
  the 16 protected settings and a 4-line diff;
- *Apply* is disabled until the acknowledgement is ticked and enabled afterwards;
- closing the dialog applies nothing; the plan card's last-apply line reads "Last apply: Applied · 10 minutes ago"
  (the API apply of the take-over proof).

Screenshots: `shots/design-apply-01-plan.png`, `shots/design-apply-02-choose.png`, `shots/design-apply-03-review.png`.

## Runs 2–4: applying from the dialog (`--apply --targets ceos --minutes 3`)

After the manager was rebuilt with the fourth review pass's fixes (the acknowledgement unticked on every new
review, a stale plan disabling *Apply*, "… and N more" on capped samples):

- **Run 2:** review (1 added), acknowledgement, *Apply*; the progress view followed the job to "ceos: verified —
  Applied, confirmed and read back."; the device shows the design's session `clabdsg-34e6dacc committed`,
  `show running-config diffs` empty, and the product's ledger owns 1 statement on `ceos`. The tool's last step
  then crashed on an ambiguous locator of its own (`summary` also matched the per-device `<details>` under
  *Owned settings*).
- **Run 3:** the locator fixed; the tool then clicked outside the still-open modal dialog (Playwright: "intercepts
  pointer events"). Fixed: the dialog is closed with its × control before *Advanced* is opened.
- **Run 4:** 16 of 16 checks, 0 console errors, 0 page errors: the review reports "already matches the plan",
  *Apply* stays disabled until acknowledged, the no-op apply is accepted, the job finishes `succeeded` ("Every
  selected device already matched the plan; nothing was changed."), the progress table lists `ceos` as
  "Already matches the plan; nothing to change.", the dialog closes, *Owned settings* under Advanced lists `ceos`
  with its statement count. Screenshots `shots/design-apply-04-progress.png`, `shots/design-apply-05-ownership.png`.
