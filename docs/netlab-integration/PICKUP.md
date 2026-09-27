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
| 1 | B | Engine pinned and packaged; intent schema and validation; adapter with explicit identities, stable order, pins and collision fix; engine runner; capability model and data tool; service, routes, generations, artifacts, export/import; wiring; guide; CI step | 1.30.43 | `b96cb89` (pushed) | done; third-pass risk review pending at commit, recorded with chunk 2 |
| 2 | C | The Design tab (guided controls, advanced editor, plan, compatibility, files, history, export/import, renumber), the second and third review passes' fixes and regressions, the browser check tool and its run, deployment of the build on the dev VM | 1.30.44 | `64c954e` (pushed; CI green) | done; deployed on the dev VM |
| 3 | D | Safe provisioning platform by platform: `design_provision.py` (protected-settings filter), `design_ownership.py` (pure ownership algebra), `design_eos.py`/`design_junos.py`/`design_iosxr.py` (per-platform session/candidate transactions), `design_apply.py` (review token, apply job, ledger, routes), the Opus risk review of the first draft (seven must-fix findings, folded into `PROVISIONING.md`), the live proof on `restore-square` (all three platforms, ten cEOS steps including take-over/timer/restart, five Junos steps, five IOS XR steps) and the fixes that proof forced (§8 of `PROVISIONING.md`, DECISIONS.md §8) | 1.30.45 (not yet cut) | not yet committed (working tree) | implemented and live-proven 2026-09-27; release not cut, not committed, not pushed |

## Exact next action

Chunks 1–3 (milestones B, C, D) are implemented; B and C are released (1.30.43, 1.30.44) as commits on
`claude/netlab-integration` (PR #55, not merged to `main` yet). Milestone D (safe provisioning) is implemented, risk-reviewed and live-proven on
`restore-square` as of 2026-09-27 and ships as 1.30.45 (the release bump, the CHANGELOG/VALIDATION/handoff sections,
the fourth risk-review pass and its fixes, the browser runs of the dialog and the deployment on the development VM
are all in this release's commit; see `git log`). Milestone E (feature families) ships as 1.30.46: every family generates with the real engine on the four profiles
(`tests/test_design_families_*.py`), and IS-IS, VRFs, static routes, policies, redistribution, default origination
and VLANs were applied live through the deployed product on all four routers and removed again
(`evidence/live-apply-families.md`); VXLAN/EVPN was applied on cEOS and refused by vJunos-switch's own commit check;
LAG, gateways, STP and BFD stay generated-only on this lab. The next agent's exact next action is milestone F:
the reviewed design-artifact export (a generation's files through the student's Git save, `docs/GIT-PROGRESS.md`),
VM sync where it applies, diagnostics of a failed apply in the Debug panel, packaging/install/upgrade evidence on a
fresh VM, the full regressions and the final report; and, from E, the GRE plugin allowlist and the secret-reference
model for protocol authentication, which are the two families still outside the schema.

Read first, in this order: `docs/netlab-integration/PROVISIONING.md` (the milestone D contract; §8 lists what
the live proof changed), `docs/netlab-integration/evidence/live-apply-{ceos,junos,iosxr}.md` (the three live
runs), `docs/NETWORK-DESIGN.md` "Applying a plan to devices" (the student-facing shape), `docs/ARCHITECTURE.md`
module map (the `design_apply.py`/`design_provision.py`/`design_ownership.py`/`design_eos.py`/`design_junos.py`/
`design_iosxr.py` row), then `DECISIONS.md` §8 (the decisions and their evidence) and `LEDGER.md` (still at its
chunk-2 shape; every row's "Limitation / remaining work" column that says "(D)" needs updating now that apply
exists for cEOS/vJunos-switch/cJunosEvolved/XRv9k, before milestone E work starts).

### Rerunning the live proof

The three live-apply runs used a scratch harness, `scratchpad/live_apply_ceos.py`, that lives only in the
session's scratchpad directory and is **not** shipped in the repository (nothing under `scratchpad/` is
committed). To rebuild an equivalent harness: a scratch `create_app(<temp data dir>)` instance (never point one
at the deployed manager's `/srv/containerlab-node-manager/data`), with discovery seeded as already-run and one
enabled host record for the target node(s) so direct SSH credential precedence resolves without a real
discovery pass, the Runner started for real (so pre-/post-change backups actually run through Ansible), and
`ANSIBLE_COLLECTIONS_PATH` pointed at the user's collections (`~/.ansible/collections` or wherever
`collections.yml` installed them) so the EOS/IOS/Junos `network_cli` modules resolve. The harness exposed
subcommands `setup` (seed the scratch state), `intent` (write a design intent onto the seeded lab), `apply`
(review + submit one generation against chosen targets with a given `confirm_minutes`), `recover` (simulate a
manager restart by re-running the interrupted-job reconciliation against the same data directory),
`status` (print a job's per-device outcomes) and `ledger` (print the ownership ledger for a device). Each
`nodecli.py`-based independent read-back in the evidence files was taken from a second, unrelated process, not
the harness itself, so drift/rollback claims are not self-graded.

### Acceptance lab facts (`restore-square`, 2026-09-27)

Four routers: cEOS, vJunos-switch, cJunosEvolved (the `vptx` stand-in) and XRv9k (the `iosxr` stand-in). At the
end of the recorded run all four carry the same OSPF + BGP design (dual stack, iBGP full mesh) applied through
milestone D. The cEOS node additionally carries, beside the design and throughout every create/modify/remove
cycle in `evidence/live-apply-ceos.md`, a manual `interface Loopback99` (`description manual-kept`,
`192.0.2.99/32`) and a manual iBGP-shaped peer `neighbor 192.0.2.200` under the owned `router bgp 65000`: both
were added deliberately to prove manual configuration survives design applies and removals, and both are still
present at the end of the run. The devices started this stream's live proof at containerlab's plain startup
configuration (redeployed 2026-09-26/27 after a host reboot left them exited), not at "configuration A" of the
multi-platform restore acceptance record; putting configuration A back is
`docs/multi-platform-restore/tools/nodecli.py --file lab/base-configs/<node>.cli` per node, and would need the
design ownership ledger cleared or reconciled first since it is keyed to what is actually on each device now.

### Open items for milestones E and F

- **E (requested feature families).** Only OSPF and BGP have generation tests through the real engine and live
  apply proof; `LEDGER.md` lists IS-IS, EIGRP (upstream: none of the four images), RIPv2/DHCP (cEOS only),
  VLANs, VRFs, BFD, LACP/MLAG, STP, VRRP/anycast gateway, VXLAN, GRE/WireGuard (plugin allowlist not yet
  accepted by the schema), route policies, redistribution, MPLS/L3VPN/6PE, EVPN, SR-MPLS and SRv6 as schema-only
  or capability-test-only. E's job is to pick the next capability, extend the adapter and capability model, add
  real-engine generation tests, and — for anything the student can now also *apply* — extend
  `design_provision.py`'s protected-settings table and `design_ownership.py`'s per-platform refinements (§8 of
  DECISIONS.md) for whatever new statement shapes that module introduces (a new module may need its own
  created-ancestor or order-sensitive-object handling the way BGP neighbours and address families did).
- **F (persistence/export and release hardening).** D6.2 (VM publication of the design sidecar through a
  bounded helper action) is still provisional and unimplemented; the ownership ledger's export/import story
  (a re-imported intent currently keeps the server's ledger, per the risk review, but the ledger itself has no
  export path yet) needs deciding; full regression and packaging/install/upgrade evidence for milestone D
  specifically (a fresh VM install exercising an apply, not just chunk 2's fixture/browser checks) has not been
  done.
- Before either E or F: `LEDGER.md`'s "Live" and "Limitation / remaining work" columns need a pass now that
  apply is real for OSPF/BGP on all four platforms (several rows still say "apply not implemented (D)").

### Known limits

- **IOS XR AS/process-id changes need two applies.** IOS XR refuses to remove `router bgp 65000` and create
  `router bgp 65100` in the same commit; the manager reports the failure with the device's own reason and
  leaves the two-step workaround (drop the module, then re-add it with the new AS/process id) to the student
  rather than orchestrating a two-commit transaction (D8.11).
- **A kind without a driver is preview-only.** Generation, preview and download work for any kind the capability
  model accepts; *Apply to devices* is offered only for cEOS, vJunos-switch, cJunosEvolved and XRv9k (the kinds
  with a driver and a live proof); any other kind is listed with the reason and cannot be selected as an apply
  target.
- **The apply UI was checked in the browser on the deployed product.** `docs/netlab-integration/tools/check_design_apply_ui.py`
  drove the *Apply to devices…* dialog in Chromium against the rebuilt container and the live lab: the review
  without applying, then an apply to `ceos` from the dialog (`evidence/browser-design-apply-ui.md`); run it
  before every release that touches the dialog.
