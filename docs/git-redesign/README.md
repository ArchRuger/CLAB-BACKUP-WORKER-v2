# Git save and load redesign

The record of the work stream that moved saving and loading out of the Progress tab into the lab header,
made a save the whole lab, let a lab save into any folder of a repository, and made a course's lab states
saved and loaded like any other save. It is a history folder: it names the release it was made for and is
not kept current afterwards. The guides for the product as it is are [GIT-PROGRESS.md](../GIT-PROGRESS.md),
[GIT-SETUP.md](../GIT-SETUP.md) and [COURSE-STATES.md](../COURSE-STATES.md).

| What | File |
|---|---|
| The owner's task, goals G1 to G4 and decisions D1 to D11, verbatim | [PROMPT.md](PROMPT.md) |
| The design: the folder model and every helper change (section 2), the save model (3), the backend contract (4), the decisions that differ from the prompt's letter (6), the rulings that bind the page (7) | [DESIGN.md](DESIGN.md), with the three part files in [design/](design/) |
| The independent reviews and how each finding was answered: the design's risk review and UI review, four reviews of the VM Git helper and the save sequence | [REVIEW.md](REVIEW.md) |
| The two acceptance inventories: every capability of the removed tab with its new home, every refusal message with its new outcome | [INVENTORY.md](INVENTORY.md), [inventory/CAPABILITIES.md](inventory/CAPABILITIES.md), [inventory/REFUSALS.md](inventory/REFUSALS.md) |
| The live environment on the development VM and the live passes (backend through the API, then the page in a browser) | [LIVE-ENV.md](LIVE-ENV.md) |
| Evidence: the fixture pass at 1440, 1280, 760 and 390 px, the "try to get blocked" pass, the live browser pass | `evidence/` |
| Tools that stay as regression tooling: the fixture's scripted Git helper with its scenarios and self-check, the browser scripts and the evidence pass, the inventory scripts, the live scripts | `tools/fixture/`, `tools/integration/`, `tools/inventory/`, `tools/live/` |
| What each worker was asked to do | `briefs/` |
| Which steps of the dated student guide are out of date | [STUDENT-GUIDE-GAPS.md](STUDENT-GUIDE-GAPS.md) |
| The state of the work, step by step | [PICKUP.md](PICKUP.md) |
| The approved mockups | [reference/README.md](reference/README.md) |
