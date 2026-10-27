# Campaign 2 (2026-10-27): parity completion, device support, topology editing, documentation

The owner's instruction of 2026-10-27 extends the parity campaign with four connected objectives, run as small,
recoverable chunks on `claude/parity-campaign`. This file is the chunk ledger and the acceptance matrices; only
the lead writes it. [PICKUP.md](PICKUP.md) keeps the dated log; [ACCEPTANCE.md](ACCEPTANCE.md) is the parity
acceptance matrix against the baseline; [DEVICES.md](DEVICES.md) is the per-image capability and evidence matrix.

Objectives: (1) establish whether the containerlab-app / VS Code extension parity campaign is complete and close its
actionable gaps; (2) complete vJunos-router and add vSRX, verify the other four exact images, with official kind
defaults; (3) device creation and link editing from the Topology view through the embedded editor; (4) validate and
clean every user-facing and agent-facing document, the student guide included (its earlier exclusion is reopened).

## Starting point (recorded 2026-10-27 01:15 UTC)

- Checkout `/home/archtop/projects/clab-manager`, branch `claude/parity-campaign` at `e709f3d` (release 1.31.6),
  clean tree, equal to `origin/claude/parity-campaign`; `origin/main` is `49b2e91` (the merge of pull request 77,
  which carried 1.31.6: `main` and the branch differ by that merge commit only). No open pull request.
- Worktrees under `.claude/worktrees/` (21) and the side branches are history after 1.31.6 (PICKUP 17:30 entry).
- VM: 24 CPUs, 72 GB RAM, `/dev/kvm`, 70 GB free; Docker 27.5.1, containerlab 0.79.0, Node 24.21, Python 3.12.3,
  the venv present. The VM rebooted about 00:35 UTC: the manager (`clab-backup:1.31.6`, port 8081) and the capture
  stack (1.31.6) came back; every lab container is `Exited (255)` (the campaign lab `parity`; `git-redesign` and
  `git-redesign-b` are not ours and stay untouched).
- Images present: the five of the first campaign plus `local/juniper_vjunos-router:26.2R1.7-nested`;
  `n24l/juniper_vsrx:23.2R2.21` exists on Docker Hub (manifest read) and is pulled in B03a.
- Editor: `@containerlab/clab-ui` 0.3.2 pinned; npm lists only 0.3.2 (checked 2026-10-27), so C11 stays blocked.
- `vm-local/` (a 2026-10-02 VM snapshot "not for merging") is tracked on `main`: a documentation-cleanup item.

### Routing verification (this runtime)

Claude Code 2.1.311, session model `claude-fable-5-1`, effort `high` (73 of 73 requests in the session transcript);
user settings `~/.claude/settings.json` set `model` only; project `.claude/settings.json` sets the agent env
(`CLAUDE_CODE_SUBAGENT_MODEL=claude-sonnet-5-5`, depth 2, teams off) and the guard hook; `settings.local.json` sets
bypass permissions and no sandbox; no managed settings (`/etc/claude-code` absent); no `availableModels`, no
`CLAUDE_CODE_SUBAGENT_MODEL_FORCE`; no `.claude/worker.local.json` (the two-VM protocol is off). The 15 agent
definitions carry the models and efforts the roster table lists. Smoke with real work, read from the per-agent
transcripts under the session's `subagents/` directory (not from the agents' words): `clab-ui-scout` ran on
`claude-haiku-5-5` effort medium (A03 inventory), `clab-devops-engineer` on `claude-sonnet-5-5` effort high (B03a).
The Opus and Fable routes are verified the same way when their first task returns (A02a, A02b).

## Official kind defaults (checked 2026-10-27 against containerlab.dev)

| Image | Kind | Login | Source (fetched 2026-10-27) | Notes from the page |
|---|---|---|---|---|
| `n24l/juniper_vjunos-router:26.2R1.7` | `juniper_vjunosrouter` | `admin` / `admin@123` | https://containerlab.dev/manual/kinds/vr-vjunosrouter/ | eth1 = ge-0/0/0; "Due to its nested architecture, vJunos-router cannot be used in any deployments that launch it from within a VM" (the C00 blocker is an official host limitation) |
| `n24l/juniper_vsrx:23.2R2.21` | `juniper_vsrx` | `admin` / `admin@123` | https://containerlab.dev/manual/kinds/vr-vsrx/ | eth1 = ge-0/0/0 (ge/xe/et accepted); no console note; no nested-virtualization note |
| `n24l/vjunos-switch:23.2R1.14` | `juniper_vjunosswitch` | `admin` / `admin@123` | https://containerlab.dev/manual/kinds/vr-vjunosswitch/ | eth1 = ge-0/0/0; ~15 min boot |
| `n24l/ceos:4.35.0F` | `arista_ceos` | `admin` / `admin` | https://containerlab.dev/manual/kinds/ceos/ | eth1 first data interface |
| `n24l/cjunosevolved:26.2R1.7-EVO` | `juniper_cjunosevolved` | `admin` / `admin@123` | https://containerlab.dev/manual/kinds/cjunosevolved/ | eth1–eth3 reserved, eth4 = et-0/0/0; BT mode 12 ports |
| `n24l/cisco_xrv9k:24.3.1` | `cisco_xrv9k` | `clab` / `clab@123` | https://containerlab.dev/manual/kinds/vr-xrv9k/ | eth1 = Gi0/0/0/0; 2 vCPU / 16 GB default; up to 25 min boot |

The registry `DEFAULT_CREDENTIALS` in `clab-backup-ui/app/inventory.py` already matches the five known kinds; vSRX
is added in B02. Precedence stays: profile > inventory login > kind default > image default (`linux` only).

## Chunk ledger

Status vocabulary: PLANNED, ACTIVE, CHECKPOINTED (committed locally), VALIDATED (its checks ran), INTEGRATED (on the
campaign branch), BLOCKED. Local, remote, validation and CI are recorded separately in the "state" column as
`local:<sha> remote:<yes/no> val:<what> ci:<pending/green/red/n.a.>`. The checkpoint owner of every chunk is the lead
unless named. Owned paths are exclusive while a chunk is ACTIVE.

| ID | Outcome | Acceptance | Depends on | Owner (agent) | Owned paths | Status | State |
|---|---|---|---|---|---|---|---|
| D00 | Baseline, routing smoke, this ledger, PICKUP entry | file committed and pushed; routes recorded from transcripts | - | lead | `docs/parity-campaign/CAMPAIGN-2.md`, `PICKUP.md` | INTEGRATED | local:62b0212 remote:yes ci:red (check_links: two files linked before they existed; green from 0752662) |
| A01 | `ACCEPTANCE.md`: current matrix linked to the R-ids, implementation vs verification status, recorded gaps | every README chunk row and every PARITY present/partial/not-pursued row has a line; counts at the end | - | `docs-auditor` | `docs/parity-campaign/ACCEPTANCE.md` | INTEGRATED | local:1400fbc remote:yes val:docs checks ci:pending |
| A02 | The deferred full reviews of C06, C08, C09 (`risk-reviewer` on backend+tests diff, `clab-ui-reviewer` on UI+editor+docs diff); confirmed findings fixed with tests | review tables recorded in C06/C08/C09-DESIGN answers; must-fix and should-fix applied; suites green | - | reviewers, then builders per path rule | the files each finding names | INTEGRATED | local:0752662 remote:yes val:python 2915 OK, node suite OK, verify-release, check_links ci:pending; the helper change is not on the live VM until the next `start-manager.sh` |
| A03 | The 17 open table rows and 13 open-point items of C03–C09: reproduce, fix, or evidence-based disposition | each item has a disposition line in its design's answers | A02 | lead + builders | per item | PLANNED | - |
| A04 | C05 impairment behaviour across device restart, stop/start and redeploy, live | evidence file with the netem state before/after each operation on `parity`; the caption's "can last" claim matched to the result | B03a (lab up) | `clab-devops-engineer` | `evidence/a04-impairments-persistence-2026-10-27.md` | INTEGRATED | local: this commit; val:live (C05-DESIGN §13: impairments do not survive the device's own restart, stop/start or a redeploy; the caption already says so) |
| A05 | C07 capture proof with real device packets (a ping between two parity nodes seen in the viewer, pcap retrieved) | evidence with packet counts and the interface pair; not loopback | B03a | `clab-devops-engineer` / `clab-ui-qa` | `evidence/a05-b06-vsrx-2026-10-27.md` | INTEGRATED | val:live (40 ICMP packets in the viewer and the pcap; C07-DESIGN §13); the vSRX "before" state on 1.31.6 recorded for B06 |
| A06 | C06 live browser interactions (chip, Find, hover, Download picture, arrange/Undo) against the live manager | `check_c06.py` or Playwright evidence against port 8081 | B03a | `clab-ui-qa` | `evidence/a06-c06-live-browser-2026-10-27.md` | INTEGRATED | local:1551233 val:live read-only (chip, Find, hover, picture, shortcuts); arrange/Undo live stays with T07 |
| A07 | Stale expectations: `verify_after.py` device-menu order (Console and C05 items); any other stale tool check | `verify_after.py` passes its menu check on the fixture | - | `clab-ui-qa` | `docs/redesign/tools/verify_after.py` | INTEGRATED | local:1551233 val:fixture 107/107 at three viewports |
| A08 | End-to-end workflow traces (lifecycle+cancel, diagnostics, terminals/console, per-device actions, apply previews, impairments, topology interactions/exports, captures, builder checks, Help/shortcuts/filter/preferences) with loading/success/failure/empty/disabled/retry/stale/partial states | one fixture pass per family with findings; verified gaps fixed | A07 | `clab-ui-qa` | `evidence/a08-*.md` | PLANNED | - |
| B01 | Official credentials rechecked and recorded (table above) | six source URLs with check dates | - | lead | this file | INTEGRATED | local:62b0212 remote:yes |
| B02 | vSRX in the registry and every integration path (inventory, aliases, downloads, topology interface map, git_progress format, diagnostics VM kinds, builder catalog, labels, discovery hints), with kind-identity tests (generic `junos` keeps concrete kinds; vSRX never becomes cJunosEvolved); vJunos-router paths audited | unit tests for precedence and identity; restore and design stay off for vSRX until proven | B01 | lead (registry), `clab-test-engineer` (tests) | `inventory.py`, `downloads.py`, `topology.py`, `git_progress.py`, `device_diagnostics.py`, builder catalog files, new tests | INTEGRATED | local:1400fbc remote:yes val:unit (test_junos_kinds 21, device_diagnostics) ci:red at 1400fbc (the VM_KINDS pin, fixed in 0752662); import/sync fixture pass is B07 |
| B03a | vSRX pulled, booted alone (`camp-vsrx`), facts recorded; `parity` lab back up after the reboot | evidence file with digest, image id, NOS version, console answer, boot time | - | `clab-devops-engineer` | `evidence/b03-vsrx-boot-2026-10-27.md` | INTEGRATED | local:0752662 remote:yes val:live (exact image booted, console on 5000, Docker health never healthy) |
| B03b | vJunos-router exact published image re-evaluated against the official limitation; blocker record | the page's sentence, the host facts (nested KVM), the assertion from `docker logs`, the supported-environment statement | B03a | lead | `DEVICES.md` | PLANNED | - |
| B04 | C10: Load (restore) proven live on vJunos-router (nested derivative, labelled as such) and on vSRX, with the `docs/multi-platform-restore` tools; then the kinds join `restore_junos.SUPPORTED_KINDS` and get restore keys | A over B replacement, readback, persistence over a real reboot, A onto A, back-to-back, selected device, mixed job; failure checks | B02, B03a | `clab-network-specialist` | `restore_junos.py`, `inventory.py` restore keys, tests, evidence | PLANNED | - |
| B05 | Network Design for vJunos-router and vSRX: capabilities, adapter, ownership, provisioning; live apply and readback where claimed | generated configuration applied live and read back; otherwise the capability stays off with the reason | B04 | `clab-network-specialist` | `design_*.py`, tests | PLANNED | - |
| B06 | Six-image regression qualification through the manager (login, backup, download names, Git save, console where offered, restore for the four proven kinds), exact image identity recorded per node | `DEVICES.md` rows with PASS/FAIL/BLOCKED/NOT TESTED per capability | B03a, B04 | `clab-devops-engineer`, `clab-ui-qa` | `DEVICES.md`, evidence | PLANNED | - |
| B07 | Import, sync and discovery identity: static and script inventories, topology hints, aliases; saved settings survive sync | unit tests + one fixture pass | B02 | `clab-test-engineer` | tests | PLANNED | - |
| T01 | Topology editing design (`TOPOLOGY-EDIT-DESIGN.md`): mode, catalog, commands whitelist, draft/save/plan/apply contract, deployed-lab path, failure handling | design answers every item of the owner's section 7 | B02 (catalog) | lead | `docs/parity-campaign/TOPOLOGY-EDIT-DESIGN.md` | INTEGRATED | local:1551233 remote:yes |
| T02 | Design review (`risk-reviewer`, `clab-ui-reviewer`) and answers | review table answered in the design | T01 | reviewers | design | INTEGRATED | local:1551233 remote:yes; 14 must-fix, 21 should-fix, 10 low, all answered with binding amendments (§12) |
| T03 | Helper slice: reviewed topology save for a deployed lab (digest-bound, trusted roots, lock) | `test_lab_operations.py` helper side; `risk-reviewer` | T02 | lead / `clab-opus-specialist` | `host_operations.py`, tests | ACTIVE | build started 03:20 UTC from 1551233 (T04 as T04a manager and T04b catalog; T06 as T06a builder page and T06b lab page) |
| T04 | Manager slice: draft, save, plan, apply routes and state | tests | T02 | `clab-backend-engineer` | `lab_operations.py`, new module, tests | ACTIVE | build started 03:20 UTC from 1551233 (T04 as T04a manager and T04b catalog; T06 as T06a builder page and T06b lab page) |
| T05 | Editor adapter slice: topology mode in the embedded editor with the command whitelist and the catalog | bundle rebuilt, `build.mjs --check` | T02 | `clab-editor-specialist` | `lab-builder/src/main.tsx`, bundle, page script | ACTIVE | build started 03:20 UTC from 1551233 (T04 as T04a manager and T04b catalog; T06 as T06a builder page and T06b lab page) |
| T06 | Topology tab UI: Edit topology entry, pending changes, apply plan, draft/saved/running distinction | node tests, fixture pass | T04, T05 | `clab-ui-builder` | `topology.js`, new page script, `index.html` | ACTIVE | build started 03:20 UTC from 1551233 (T04 as T04a manager and T04b catalog; T06 as T06a builder page and T06b lab page) |
| T07 | Verification and live acceptance (browser → file → runtime on the six catalog entries) | the section 7 acceptance list | T06 | `clab-ui-qa`, `clab-devops-engineer` | evidence | PLANNED | - |
| T08 | Documentation of the workflow (Topology, Lab builder, Help, student guide, agent contracts) | docs match the shipped behaviour | T07 | `docs-auditor`, lead | guides | PLANNED | - |
| D01 | Documentation inventory script and classification (current / historical / retired) | `docs/maintenance-audit/tools/doc_inventory.py` output committed | - | lead | tool + `docs/parity-campaign/DOCS-INVENTORY.md` | INTEGRATED | local:0752662 remote:yes; 422 files: 28 guides, 29 agent, 206 history, 108 vendored, 47 vm-local, 3 other |
| D02a/b/c | Install, health, VM connection (a); Git, course, naming, telemetry notice (b); overview, architecture, capture (c) | each domain's corrections committed with the auditor's report under `docs/maintenance-audit/reports/` | D01 | `docs-auditor` ×3 | the guides named in each brief | INTEGRATED | a: 18 of 45 claims fixed (1551233); b: 3 labels (1551233); c: 21 corrections (this commit); checks green; left for later domains: NETWORK-DESIGN's tab heading, the `docs/images/ui` screenshots, `start-manager.sh`'s pointer to a migration section that moved |
| D03–D05 | NODE-FEATURES and LAB-* guides after the B and T streams; NETWORK-DESIGN after B05; agent docs and `.claude/` (lead); legacy VM material and `vm-local/` | as above | B06, T08 | `docs-auditor`, lead | per domain | PLANNED | - |
| D10 | Student quick-start guide: sources, screenshots, generated PDF against the final UI | PDF regenerated from sources and inspected; Help entry restored only then | T08, D02 | assigned explicitly (not `docs-auditor`): `clab-ui-qa` for screenshots, lead for text | `docs/student-quick-start/` | PLANNED | - |
| D11 | Links, anchors, images, external references; superseded notices | `check_links.py` green plus the supplement's report with a reason per unresolved external item | D02–D10 | lead | tool, docs | PLANNED | - |
| T09 | A reviewed "Put back the previous file" after a deployed save (from the recovery copy) | reviewed revise of the remembered texts | T07 | `clab-ui-builder` + lead | builder page, docs | PLANNED | follow-up recorded from the UI review (#14) |
| R-n | Releases: one `+0.0.1` per integrated, validated group (A-group, B-group, T-group, D-group), each with CHANGELOG, VALIDATION, handoff, CI lists | `verify-release.py`; suites; push; CI | per group | lead only | release files | PLANNED | - |

## Decisions

- The first campaign's leaner scrutiny stays (one slice-verify, one reviewer pass per area) except where the owner's
  instruction asks for an independent review: A02 gives C06/C08/C09 the two full reviewer passes they missed.
- Owner preference (2026-10-23): the lead writes the designs and takes the hardest slices; Fable workers only when
  the quality difference is real. Opus reviews and NOS work; Sonnet builds, tests, QA, docs; Haiku inventories.
- vJunos-router's exact published image is qualified only on a host that is not itself a VM (official limitation);
  on this nested VM the local derivative is diagnostic evidence, labelled as such everywhere.
- The `parity` lab is the campaign's mixed lab; `camp-*` labs are campaign-owned single-kind labs. Nothing else on
  the VM is touched.
