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

## Chunk 3 (milestone D: safe provisioning, "Apply to devices")

New unit test files, run and counted directly against this checkout on 2026-09-27 (`.venv` created from
`requirements.txt` + httpx per the top-level `README`/`CLAUDE.md` recipe). Each pins what its module
docstring and class names say, not more:

| File | Count | Pins |
|---|---|---|
| `tests/test_design_provision.py` | 12 (`EosTests`, `IosXrTests`, `JunosTests`; the last three pin the fourth review pass's hardening: AAA servers, SNMP, NTP, Junos `root-authentication` block, `management-instance`, `mgmt_junos`) | `app/design_provision.py`: what a generated fragment may reach a device with, on fixtures shaped like netlab 26.09's own rendering for the acceptance topology (PROVISIONING.md §1 and §7) — the protected-settings filter, statement by statement, per platform |
| `tests/test_design_ownership.py` | 26 (`StatementFormTests`, `DiffTests`, `RemovalPlanTests`) | `app/design_ownership.py`: the ownership algebra of PROVISIONING.md §3 (statement form, `before`/`desired`/`owned`/`stale`/`conflicts`, created-ancestor collapse, order-sensitive objects), statement by statement |
| `tests/test_design_eos.py` | 27 (+1 from the 2026-10-03 audit: the would-be configuration is offered to `accept` before `commit timer`, a refusal aborts unarmed (L-14)) (`FakeDevice`, `FakeChannel`, `FakeClient`, `DesignEosDriverTests`) | The Arista EOS design driver (`app/design_eos.py`) against a scripted fake channel, mirroring `tests/test_restore_eos.py`'s FakeDevice/FakeChannel approach adapted to the driver's own shape: sessions named `clabdsg-<8 hex>`, the `show session-config` / `show session-config diffs` review pair |
| `tests/test_design_junos.py` | 27, 29 today (+1 in chunk 4; +1 from the 2026-10-03 audit: `accept` is asked before `commit check`, a refusal rolls back unarmed (L-14)) (`FakeDevice`, `FakeChannel`, `FakeClient`, `DesignJunosDriverTests`) | The Junos design driver (`app/design_junos.py`) against a scripted fake channel, mirroring `tests/test_restore_junos.py`'s FakeDevice/FakeChannel (operational/configuration prompts, `show system commit`, `show \| compare`, a `load … terminal` paste ended by Ctrl-D, `commit check`, `commit confirmed`) and `test_design_eos.py`'s thin `FakeClient` |
| `tests/test_design_iosxr.py` | 32 (+1 from the 2026-10-03 audit: `accept` is asked before `commit confirmed`, a refusal aborts unarmed and holds nothing (L-14)) (`FakeDevice`, `FakeChannel`, `FakeClient`, `DesignIosXrDriverTests`, `ReviewPassFourTests`) | The Cisco IOS XR design driver (`app/design_iosxr.py`) against a scripted fake channel, modeled on `tests/test_restore_iosxr.py`'s FakeDevice/FakeChannel (the XRv9k prompt shapes and the hierarchical push/leaf-line/plain-`exit` tracking `design_iosxr` reuses from the restore driver) |
| `tests/test_design_apply.py` | 54 (`python -m unittest discover -s tests -t tests -p test_design_apply.py -v`; seven added by the lead: the interrupted job's read-back summary, the take-over second pass, the pending ledger entry settled by the next review, an armed change that cannot be matched with the review, the held session released when the timer ran out, a stale plan refused, another lab's apply refusing the review; three from the 2026-10-03 audit: a trial of this manager still armed is not read back as owned (L-13), an IOS XR pending entry with typed negations is judged by the absence of their positive form (M-6), a would-be configuration unlike the review is never armed (L-14), and four for the read-back after a restart (L-15): a new apply on another lab is not queued behind it, the lab under read-back is held until its devices settle, a restart during the read-back reads the rest back, a read-back that fails inside the manager leaves the device `uncertain` with a pending ledger entry, never "not changed"; and two for `operation_busy` (L-15 review): the read-back never holds another lab or a check that names no lab, and a restore and a backup of the lab under read-back are refused until it settles) (`DeviceState`, `FakeDriver`, `FakeRunner`, `DesignApplyTestCase`, `ReviewGuardTests`, `SuccessfulReviewTests`, `ConflictTakeoverTests`, `ApplyGuardTests`, `FullApplySuccessTests`, `NoOpAndRemovalTests`, `DriftTests`, `StageFailureTests`, `BackupFailureTests`, `BusyGuardTests`, `RestartReconciliationTests`, `RecheckConcurrencyTests`, `PublicHelperTests`, `PartialOutcomeTests`) | `app/design_apply.py`: the review token, the apply job, drift and session-loss handling, the ownership ledger and restart reconciliation. Drives the real app through FastAPI `TestClient` against scratch state (`create_app(<tempdir>)`); no SSH is ever opened. The platform driver (`app/design_eos.py`) is replaced with a compact fake modeling one Arista-cEOS-shaped device per node |
| `tests/test_network_design_ui.js` | 39 total (`node --test tests/test_network_design_ui.js` → 39 pass), of which 13 are new for this chunk: `designApplyDeviceMarkup` (5), `designApplyCanSubmit`, `designApplyRequestId`, `designApplyBody`, `designApplyProgressMarkup` (2), `designApplyOwnershipMarkup`, `designApplyLastLineMarkup`, `designApplyDisabledReason` | The apply dialog's per-device markup (ready/conflict+take-over/ineligible/unreachable/no-op), the submit gate, the request id and request body shaping, the live progress markup per outcome word, the ownership summary markup, and the last-apply-line markup; run the same way `tests/test_restore_ui.js` drives `restore.js` — a `vm` context with a fake `$`, `esc` and `state`, no DOM |

Exact commands:

```bash
cd clab-backup-ui
PATH="$PWD/.venv/bin:$PATH" .venv/bin/python -m unittest discover -s tests -t tests -p test_design_provision.py -v
PATH="$PWD/.venv/bin:$PATH" .venv/bin/python -m unittest discover -s tests -t tests -p test_design_ownership.py -v
PATH="$PWD/.venv/bin:$PATH" .venv/bin/python -m unittest discover -s tests -t tests -p test_design_eos.py -v
PATH="$PWD/.venv/bin:$PATH" .venv/bin/python -m unittest discover -s tests -t tests -p test_design_junos.py -v
PATH="$PWD/.venv/bin:$PATH" .venv/bin/python -m unittest discover -s tests -t tests -p test_design_iosxr.py -v
PATH="$PWD/.venv/bin:$PATH" .venv/bin/python -m unittest discover -s tests -t tests -p test_design_apply.py -v
node --test tests/test_network_design_ui.js
```

All six Python files (each named with its own `-p`, not the `test_capture*.py` glob) and
`tests/test_network_design_ui.js` (in the one `node --test` line with every other browser file) are listed
in `.github/workflows/release-check.yml`, so this chunk's tests run in CI.

Live tools, milestone D:

- `scratchpad/live_apply_ceos.py` — description only; it lives in the session's scratchpad directory, not
  in the repository. It drives the real service path (`DesignApply.review` → `submit` → `execute` → settle
  → ledger) from a scratch `create_app` instance on its own data directory: discovery seeded fresh, the
  Runner started for the real pre- and post-change backups through Ansible, never the deployed manager's
  data. One run per platform produced the step tables in `evidence/live-apply-{ceos,junos,iosxr}.md`.
- `docs/multi-platform-restore/tools/nodecli.py` — the independent read-back tool (paramiko, outside the
  code under test) used to verify every step of the live proof. Transcripts under its `transcripts/` folder
  (raw device output; not committed) are tagged `pre-apply`, `post-apply1` … `post-apply9`, `post-recover7`,
  `post-recover8` (cEOS steps 1–10 of `live-apply-ceos.md`); `post-junos-apply1`, `post-junos-modify`,
  `post-junos-drop` (the Junos steps of `live-apply-junos.md`); `post-xr-review1`, `post-xr-review2`,
  `post-xr-apply1`, `post-xr-identity`, `post-xr-drop` (the IOS XR steps of `live-apply-iosxr.md`).

Suites and checks at the checkpoint: the six new Python files above all pass on this checkout (135 tests,
0 failures); `node --test tests/test_network_design_ui.js` passes (39, 0 failures). Full-suite counts,
`verify-release.py`, `check_links.py` and `git diff --check` for the release that ships this chunk (1.30.45)
belong in `clab-backup-ui/VALIDATION.md` and `docs/CHANGELOG.md`, not here.

## Chunk 4 (milestone E: feature families)

| File | Count | Pins |
|---|---|---|
| `tests/test_design_families_routing.py` | 20 (`IsisFamilyTests`, `StaticRoutesFamilyTests`, `VrfFamilyTests`, `BgpPolicyFamilyTests`, `BfdFamilyTests`) | Real-engine generation on the four-node topology: IS-IS (NET from the area, per-node level), node-level static routes with a discard next hop, VRF objects with link attachment and a VRF loopback, prefix lists / route policies / redistribution / default origination, BFD on cEOS and Junos with XRv9k refused by the capability model; validation accepts the proven shapes and refuses the wrong ones; byte-identical reruns |
| `tests/test_design_families_l2.py` | 25 (`VlanFamilyTests`, `LagFamilyTests`, `GatewayFamilyTests`, `VxlanEvpnFamilyTests`, `StpFamilyTests`) | VLAN access and trunk ports, a two-link LAG bundle (cEOS port-channel, Junos ae), VRRP on all four and anycast on three, VXLAN + EVPN, STP on cEOS; the capability answers for the unsupported kinds; byte-identical reruns |
| `tests/test_design_intent.py` | 140 (+2: LAG members, the IS-IS area / default origination / redistribution forms) | as before |
| `tests/test_design_adapter.py` | 72 (+1: `BuildLagTests`, the bundle with member ports by ifindex; the per-node module rule rewritten) | as before |
| `tests/test_network_design.py` | 61 (the per-node module rule rewritten) | as before |
| `tests/test_design_junos.py` | 28 (+1: `CheckReasonTests`, a commit-check refusal classified into fixed words) | as before |
| `tests/test_network_design_ui.js` | 57 (+13: the guided tables `designVrfsMarkup`, `designVlansMarkup`, `designLinksMarkup`, `designStaticMarkup`, their form-to-intent round trips, module auto-add, empty rows dropped) | as before |

Both family files are registered in `.github/workflows/release-check.yml`. Live: `scratchpad/product_design.py`
(change the deployed lab's design through `PUT …/design` and generate) and `scratchpad/product_apply.py` (review
and apply through the product's API), both described only; the read-backs use `nodecli.py` with the transcript tags
`e1-isis`, `e1-isis-recheck`, `e2-vrf`, `e3-policy`, `e4-vlan`.

## Chunk 5 (milestone F: Git export, health check, final report)

| File | Count | Pins |
|---|---|---|
| `tests/test_design_export_git.py` | 24 (`DesignSnapshotTests`, the route tests, the execution tests against a fake helper, `PublicJobTests`, `RestoreCandidateTests`) | `NetworkDesign.design_snapshot` (file set and names, base64, the manifest, refusals: not succeeded, missing or changed fragment, unusable name; an empty generated file left out), the route's fields, idempotency and refusals, `GitProgress.execute` for kind `design` (the `publish` request with the checkpoint target, `review_pending` vs `committed`, the reviewed retry, the digest mismatch), `public_job`, the restore never offering a design version |
| `tests/test_host_git.py` | 70 (+3: `HostGitDesignExportTests`) | the helper writes a design snapshot to its own checkpoint folder only, refuses it at `latest`/`baseline`, and never lets the two kinds share a folder |
| `tests/test_check_install.py` | 40 (+2: `DesignEngineCheckTests`) | the health check's network design engine item (PASS with the version, WARN with the diagnostic, WARN when the manager does not answer) |
| `tests/test_network_design_ui.js` | 64 (+7) | the *Export plan to Git…* reason, default checkpoint, name validation, request id, body, destination markup, button render |
| `tests/test_git_progress_ui.js` | 41 (+2) | the *Design export* labels of a job of kind `design`; ordinary saves unchanged |

All registered in `.github/workflows/release-check.yml`. Browser: `docs/netlab-integration/tools/check_design_export_ui.py`
(the dialog, the review the job stops at, the upload through the review's own button, the repository history and the
restore's refusal, against a running manager); fresh install: `docs/technical-audit/tools/fresh_install_vm.py` on the
Ubuntu 24.04 cloud image.
