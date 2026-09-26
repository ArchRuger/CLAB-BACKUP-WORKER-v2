# netlab integration: pickup file

Read this first, then [DECISIONS.md](DECISIONS.md) (architecture decisions with their evidence),
[LEDGER.md](LEDGER.md) (feature-by-platform ledger: requested capability, upstream support, adapter support,
generation tests, live evidence, UI path, limitation, remaining work) and [TESTS.md](TESTS.md) (what was run,
per chunk). Git and GitHub are the authority for what is committed, pushed and merged; this file records the
state between sessions so the next agent can continue without rediscovering it.

## Assignment

Integrate netlab's addressing, network-design and device-configuration capabilities into Containerlab Node
Manager as an opt-in *Network design* capability: build or open a lab, define network intent, calculate
addressing and routing, inspect generated configuration and compatibility, explicitly apply to selected
devices, verify, keep and export the design and its evidence. The full assignment text is the owner's prompt
`CLAB_Netlab_Integration_Claude_Code_Prompt_v2.md` (kept outside Git in the worktree root); its nonnegotiable
boundaries are repeated in DECISIONS.md §0.

## Branch, releases, commits

- Branch `claude/netlab-integration`, cut 2026-09-26 from `origin/main` `1e72899` (release 1.30.42, PR #54
  merged). Remote `origin` = ArchRuger/CLAB-BACKUP-WORKER-v2. Push with the `ArchRuger` gh account, switch back
  to `pruger-dev` afterwards so lab saves keep working.
- Worktree `~/projects/clab-manager-1.30.42` (the main checkout `~/projects/clab-manager` stays on
  `claude/technical-audit`; leave it alone). Its `.venv` was created from `requirements.txt` + httpx on
  2026-09-26.
- Local uncommitted routing files (`.claude/settings.json`, `.claude/agents/*`) stay uncommitted on purpose
  (the user's earlier choice); never `git add -A`; the prompt file stays untracked.
- Releases: one +0.0.1 per finished chunk with `deploy/set-release.py`, then CHANGELOG, VALIDATION and the
  handoff section, then `verify-release.py`. Chunk table below.

## Environment (clab-llm-dev2, 2026-09-26)

- 28 CPUs, 67 GiB RAM, disk 72 GiB with 18 GiB free at start (74 % used; the four NOS images take 19 GB).
  Docker 29.8.1, containerlab present, passwordless sudo. Python 3.12.3 (no system pip; use a venv).
  System Node 18.19.1; Node 24 for the editor bundle is under `~/.local/node24` (not needed unless
  `lab-builder/src/main.tsx` changes, which this stream avoids).
- Claude Code 2.1.283. User settings: model `claude-fable-5-1`, `CLAUDE_CODE_SUBAGENT_MODEL=sonnet`,
  `CLAUDE_CODE_SUBAGENT_MODEL_FORCE=0`, `availableModels` fable / haiku / sonnet / `claude-opus-5-5`. Project
  agents `docs-auditor` (sonnet), `mechanical-editor` (haiku), `risk-reviewer` (opus) carry their model in the
  definition; an ad-hoc agent without a `model` argument runs on Sonnet. Observed routes are recorded in
  TESTS.md per chunk (requested vs observed).
- Manager 1.30.42 (`clab-backup:1.30.42`, container `containerlab-node-manager-backup-ui-1`, host network,
  port 8081, data `/srv/containerlab-node-manager/data`), helpers 1.30.42, capture stack `clab-manager-capture`
  running (`clab-backup-ui/.env` in the worktree holds the capture token; it still carries obsolete
  `TELEMETRY_*` lines that nothing reads).
- Rebuild loop: `cd ~/projects/clab-manager-1.30.42 && sudo docker compose -f clab-backup-ui/compose.yml
  --env-file clab-backup-ui/.env up -d --build` (about 3 s without dependency changes; a `requirements.txt`
  change rebuilds the image layer). Helpers: `sudo bash deploy/setup-operations.sh --refresh` and the other
  `setup-*.sh --refresh` after a `host_*.py` or VERSION change; `sudo bash deploy/check-install.sh` verifies.
- Lab `restore-square` (`/srv/containerlab-node-manager/projects/restore-square/restore-square.clab.yml`,
  the four-image square of `docs/multi-platform-restore/lab/`): found with its four NOS containers exited
  (host reboot two days earlier, only `host1` running). Destroyed with `--cleanup` and redeployed on
  2026-09-26 (log in the session scratch); the devices therefore start from containerlab's startup
  configurations, **not** from "configuration A" of the restore acceptance record. Configuration A can be put
  back with `docs/multi-platform-restore/tools/nodecli.py --file lab/base-configs/<node>.cli`. Boot times on
  this VM: cEOS about 1 min, cJunosEvolved about 8 min, XRv9k about 11 to 13 min, vJunos-switch about 17 min.
  Manager lab id `174386ec12ee496190c585c5796b2662`, bound to `restore-square/qa-1-30-37` of
  `~/labs/CLAB-MNGR-DEV-LLM`.
- netlab research area: `~/research/netlab-integration/` (outside Git): `netlab-venv` (networklab 26.09 from
  PyPI, `netlab-26.9-freeze.txt` is its `pip freeze`), `netlab-src` (upstream clone at tag `release_26.09`,
  commit `e2b636bd02`; the prompt's inspected `dev` revision `3cfe023094` is 11 commits later), the
  reconnaissance reports `RECON-*.md` and the prototypes `proto-*`.

## Baseline (before any change, 2026-09-26)

- Python: `python -m unittest discover -s tests -t tests` → 1134 tests OK (1 skipped), 82 s.
- Browser: `node --test tests/*.js` → 281 pass, 0 fail.
- `python3 deploy/verify-release.py` → source and documentation at 1.30.42; `git diff --check` clean.
- Pre-existing failures: none.

## Chunks

| Chunk | Milestone | Content | Release | Commit | Status |
|---|---|---|---|---|---|
| 0 | A | Baseline, reconnaissance, compiler-only proof, decisions, records skeleton | none (records land with chunk 1) | | done |
| 1 | B | Engine pinned and packaged; intent schema and validation; adapter with explicit identities, stable order, pins and collision fix; engine runner; capability model and data tool; service, routes, generations, artifacts, export/import; wiring; guide; CI step | 1.30.43 | (filled at commit) | in progress |

## Exact next action

Chunk 1 closes with the 1.30.43 commit and push (records: CHANGELOG, VALIDATION, the handoff section, TESTS.md).
Then milestone C: the *Network design* tab (`app/static/network-design.js`, a `design` panel in `index.html`,
`tests/test_network_design_ui.js` registered in CI), the guided flow (families, pools, OSPF/BGP settings, per-device
exclusion, generate, plan, files, download, export/import) plus the schema-validated advanced editor, then a browser
run against the fixture manager and the rebuilt product on the VM. Check `sudo containerlab inspect --all` before
any live step; cJunosEvolved was still booting at the end of chunk 1.
