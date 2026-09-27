# Tests and routing, per chunk

What was actually run for each checkpoint, at which level (static, unit, real engine, fixture/browser,
live VM or device), and which model each delegated task requested and observed.

## Chunk 0 (milestone A, no release)

- Baseline 2026-09-26 before any change: Python 1134 OK (1 skipped), browser 281 pass, `verify-release.py`
  clean. Environment and lab state in PICKUP.md.
- Reconnaissance: two Sonnet agents (requested `sonnet`, observed `claude-sonnet-5` per the task
  metadata), reports `~/research/netlab-integration/RECON-*.md` with raw outputs and prototypes.
  Verified by the orchestrator's own probes (`proto-mgmt`, the adapter smoke runs).

## Chunk 1 (milestone B: engine boundary and data model)

| Task | Requested | Observed | Result |
|---|---|---|---|
| `design_engine.py` and its tests | sonnet | claude-sonnet-5 (transcript metadata) | 12 tests, real engine (13 after the review's status regression test) |
| `design_capabilities.py`, the data tool, tests | sonnet | claude-sonnet-5 | 21 tests; GRE corrected by the lead to the engine's flag |
| `test_design_intent.py`, `test_design_adapter.py` | sonnet | claude-sonnet-5 | 116 and 66 tests, real engine schema and one real generation (135 and 69 after the two review passes' regressions) |
| `test_network_design.py` | sonnet | claude-sonnet-5 | 47 tests through the real app and the real engine (61 after the two review passes' regressions) |
| Intent schema, adapter, service, wiring, records | Fable (lead) | claude-fable-5-1 | |
| Risk review of the engine boundary, routes, ledger (two passes) | opus (`risk-reviewer`) | claude-opus-5-5 | first pass: 2 must-fix, 9 should-fix, 5 optional, all applied and pinned by `ReviewRegression*` tests; second pass: see VALIDATION 1.30.43 |

Suites and checks at the checkpoint (this checkout, `netlab` on PATH): Python 1433 OK (1 skipped, 335 s), browser 281
pass, `node --check`, `python -W error -c "import app.main"`, `verify-release.py`, `check_links.py` (137 files),
`git diff --check`; image `clab-backup:1.30.43` built twice (before and after the review fixes) with the offline
in-image generation passing both times. Live device evidence: none (by design in this chunk).

## Chunk 2 (milestone C: the Network design tab; the second and third review passes)

| Task | Requested | Observed | Result |
|---|---|---|---|
| Second and third risk-review passes on the chunk 1 backend | opus (`risk-reviewer`) | claude-opus-5-5 | 2 + 1 must-fix, several should-fix, all applied; pinned by `SecondPassRegression*`, `ThirdPassRegression*`, `CrashContractTests` |
| `network-design.js`, the Design tab, `test_network_design_ui.js` | sonnet | claude-sonnet-5 | 26 browser tests; two defects found by the lead's browser run (schema stamp, problems list placement), fixed by the lead |
| Browser check tools `check_design_ui.py` (fixture) and `check_design_live.py` (the deployed product) and their runs | Fable (lead) | claude-fable-5-1 | 20 of 20 and 17 of 17 |

Suites and checks at the checkpoint: Python 1439 OK (1 skipped), browser 307 pass, `verify-release.py`, `check_links.py`, `git diff --check`; the manager on the dev VM rebuilt and recreated at 1.30.44.
