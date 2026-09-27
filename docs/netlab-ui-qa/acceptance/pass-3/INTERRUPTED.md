# Acceptance pass 3 (Sonnet), release 1.30.49: interrupted by a host crash, no verdict

Written by the lead, not by the pass's agent. Pass 3 was the first of the two gate passes on the final build
(release 1.30.49, commit `14c2f05`, manager rebuilt at 20:58 UTC). A fresh Sonnet agent started it at 21:12 UTC on
2026-09-27 with the same charter as passes 1 and 2. It produced the evidence in this folder and was lost, with the
session that ran it, when the development VM crashed. It wrote no report and reached no verdict, so it does not
count as a pass; it recorded no finding either, so it does not reset the clean-pass count. The gate passes on
1.30.49 are pass 4 (Sonnet) and pass 5 (Opus).

## What the pass had completed (all UTC, all on the deployed 1.30.49 and its fixture)

| Step | Evidence | Result |
|---|---|---|
| `check_design_ui.py` (fixture, real engine) | `browser-design-ui.md`, `shots-design-ui/` (21:14) | 29 of 29, 0 console errors, 0 page errors |
| `check_design_poll_retry.py` | `poll-retry.json`, `poll-retry-*.png` (21:15) | 9 checks, 0 failed |
| `stress_design.py race` | `race-results.json` (21:15–21:22) | 80 checks, 0 failed, race-a leaks 0/20, race-b stale-wins 0/20 |
| `stress_design.py bulk` | `bulk-results.json` (21:22–21:23) | 43 checks, 0 failed, 24 generations |
| `coverage_run.py` | `coverage-results.json` (21:24) | 123 rows: 112 PASS, 8 BLOCKED, 3 NOT RUN, 0 FAIL |
| `design_probes.py` (working-tree script) | `probes-run.log` (21:24–21:27) | 55 checks; all 19 CONFIRMED-target checks fail as required, plus the two bug-describing checks; the one console error is the injected 500 |
| own adversarial check (QA-007 cross-lab guard: Renumber and Remove design) | `adversarial-qa007-renumber-clear.json`, `shots/adversarial-final.png` (21:27) | 0 failed |
| `check_restart_device.py` cEOS, full run (map, Devices view, stopped; terminal, capture, 3 links) | `ceos-2026-09-27T212819+0000.json`, `ceos-2128-*.png` (21:28–21:30) | 81 checks, 0 failed (78 of 1.30.48 plus the three TOOL-002 assertions) |
| `check_restart_two_tabs.py` host1 | `two-tabs-host1-2026-09-27T213104+0000.json`, `two-tabs-stale-review.png` (21:31) | 13 checks, 0 failed |
| `check_restart_neighbour.py` cEOS with host1 stopped (`--stop-mode containerlab`) | `neighbour-containerlab-ceos-2131-0{1..4}.png` (21:31–21:32) | **unfinished**: the four screenshots end at the neighbour's review; the JSON record was never written |
| `traffic_probe.py` from cJunosEvolved (crossing 10.255.0.1, other 10.255.0.3) | `ceos-traffic.jsonl` (21:28–21:32, 34 rows) | ran until the crash |

Not reached: the API previews and refusals, the XRv9k restart with its read-backs, the ledger spot check, the report.

## The crash and the recovery

- The host's journal ends at 21:32:14 UTC with ordinary entries (the manager's discovery logins); `last -x` records the
  previous run level as ended by a crash; the next entry is the boot at 21:51 UTC. No kernel message was captured. The
  host stopped logging while the neighbour check was between its restart of cEOS and its start of host1. Whether the
  check's activity and the crash are related is unknown; the same check had run clean six times that day.
- After the boot the Docker daemon panicked at start (`invalid freelist page: 24, page type is branch`) while opening
  its network store `/var/lib/docker/network/files/local-kv.db` (last written 21:32). The file was moved aside as
  `local-kv.db.corrupt-20260927T2151` at 21:58 and Docker started; the manager container (host network) came back on
  its own, the lab and capture containers could not start because their two networks lived in that store.
- Lab `restore-square` was destroyed and deployed again from the host CLI at 22:00 UTC (containerlab 0.79.0), and
  configuration A applied per device once its NOS answered. The capture stack was reinstalled with
  `deploy/setup-capture.sh` (its session service now runs `clab-capture-service:1.30.49`; it had kept running the
  1.30.42 build since the stack was last recreated) and the manager recreated by that script. The manager's image,
  helpers and source are unchanged: `clab-backup:1.30.49`, commit `14c2f05`.
- Because the deploy came from the host CLI and not from the manager, the devices' first boot lies outside the QA-019
  login grace window by design; any `failed` login state before they first read *Ready* is not a restart outcome.
