# Save location fix: pickup file

Two connected requirements, worked on `claude/save-location-fix` (branched from `main` `6c3e8b3`,
release 1.30.30): (1) saving as Latest updates the existing `<lab folder>/latest` snapshot in place and
never nests a second `latest`; (2) *Apply to running lab…* is offered for any repository folder that
holds `manifest.json`, whatever its name or depth. Read this file first; keep it current before a
compaction or a handoff. Sanitized evidence lives in `evidence/`; raw device output stays out of Git.

## The contract (what every layer implements)

Two path roles, named explicitly everywhere:

- **Lab folder** (`prefix` of a registration, the lab's *base folder*). Save progress writes the
  snapshot folders `<lab folder>/latest`, `<lab folder>/baseline` and
  `<lab folder>/checkpoints/<name>` inside it. `''` is the repository root.
- **Snapshot folder**: any repository folder that holds `manifest.json`. On the wire the browser
  always sends its exact repository-relative path with one leading slash (`'/'` = the repository
  root, `'/Final'`, `'/working/latest'`). The manager also accepts a bare `latest`, `baseline` or
  `checkpoints/<name>` with its old meaning (this lab's own folder: compatibility for pages and tools
  from before this release) and any other bare path as exact (the acceptance tools). No name pattern
  decides what a snapshot is; the manifest and its referenced files decide what can be applied.

Rules:

1. `latest`, `baseline` and `checkpoints` are reserved names inside a lab folder. A lab folder whose
   last segment is one of them, or whose last two segments are `checkpoints/<name>`, is refused by the
   browser (`gitFolderPath` for typed names), the manager (`folder_value`, HTTP 400) and the helper
   (`plan_prefix`, `plan_connect`, `ValueError`). Wording: *latest, baseline and checkpoints are the
   folders Save progress writes inside a lab folder. Choose the folder above them: its saves go to
   `<parent>/latest`.*
2. A lab folder at, or below, an existing snapshot folder (manifest.json at HEAD at the prefix or an
   ancestor) is refused by the manager routes that can read the tree (`POST …/folders`, both forms, and
   `POST …/git/destination`): *`<path>` is a saved configuration (it holds manifest.json) …*.
3. In the folder browser, selecting a snapshot folder named `latest` resolves the choice to its parent:
   `gitFolderChoice` returns `{allowed, reason, target: <parent path>}` evaluated for the parent, and
   *Save this lab here* uses `target`. Any other snapshot folder (`Final/manifest.json`, `baseline`,
   a checkpoint) is not a destination (`allowed: false`, reason says why). No folder can be created
   inside a snapshot folder (`gitCanCreateIn`).
4. The helper's `publish` refuses a destination that holds *files* outside its manifest; subdirectories
   are not files the export owns, so a legacy nested `latest/latest` folder no longer blocks saving into
   the snapshot it sits in. A destination without a manifest is adopted only when it is empty (a
   subdirectory counts). Existing registrations, bindings and trees are never rewritten; the reserved-name
   rule applies to a *new* lab folder only, so a registration an older release made at `x/latest` stays
   selectable, repairable (`setup-git.sh`, the wizard's "reuse a saved destination") and movable one
   level up; the Save location card shows a notice with that recovery for such a binding.
5. `read-version` accepts any safe repository folder (`''`, `'/'` = root; one leading slash is
   stripped); `history` lists every snapshot folder at HEAD as plain paths (`''` for the root;
   `connected` marks the lab's own three kinds, which are never dropped by the 500-row cap).
   `resolve_version_path`: leading slash = exact (`'/'` → `''`), bare reserved names = the lab's own
   folder (kept for old pages and tools), other bare paths = exact. The browser sends the slash form
   everywhere (`'/' + job.snapshot_path`, `gitSnapshotPath(binding, 'latest')`).
6. A folder restore source is `{type: 'folder', path: <exact>, commit?: <sha>}`. Preflight without
   `commit` reads HEAD and returns `source.commit`; the browser submits exactly the reviewed
   `{type, path, commit}`; a submit with `commit` reads that commit (the helper refuses one outside the
   branch history). So a sync between review and submission never applies different bytes.
7. Browser discovery: `gitTreeModel` marks `dir.snapshot` (manifest.json among the folder's own files)
   and `dir.latestSnapshot` (its `latest` child is a snapshot). `gitApplySource(dir)` is `{path: dir.path}`
   for a snapshot folder, `{path: dir.path + '/latest'}` for the legacy parent convenience, else `null`.
   Selecting `Final` applies `Final`; selecting `Final/latest` applies `Final/latest`; nothing is
   substituted. Saved versions lists every snapshot folder (own · reference under the lab folder's
   parent · other labs' · elsewhere in the repository), each row with its exact path.

## Plan (chunks)

1. Routing and build check; live reproduction on the running 1.30.30; failing regressions; the fix
   for the stable Latest destination through browser, manager and helper. **Done in the working tree
   (release 1.30.31 being validated).**
2. Manifest-based source selection through every layer (browser, manager, helper, restore service);
   review-to-submit commit pinning; Playwright and API proof. **Code done with chunk 1 (same path
   contract); the B matrix on the deployed `clab-backup:1.30.31` is running.**
3. Live acceptance on the four images from `Final`, `Broken`, `working/latest`, a nested folder, the
   legacy parent convenience, a checkpoint/baseline and a historical commit; release records.

## Routing preflight (2026-09-22, Claude Code 2.1.278)

Resolved models read from `~/.claude/projects/<project>/<session>/subagents/agent-*.jsonl`
(`message.model`) joined with `agent-*.meta.json` (`agentType`), and from the session transcript for
the lead. Settings: the project `.claude/settings.json` (`model: claude-fable-5-1`,
`availableModels: [haiku, sonnet, opus, fable]`, `CLAUDE_CODE_SUBAGENT_MODEL=sonnet`,
`CLAUDE_CODE_SUBAGENT_MODEL_FORCE=0`) overrides the user file, which still forces Fable subagents
outside this project; no managed settings, no `settings.local.json`. The installed CLI honours an
agent definition's `model:` when the force flag is off and the model is in the allowlist (its resolver
drops the requested model only when `CLAUDE_CODE_SUBAGENT_MODEL_FORCE` is set).

| Role | Expected | Configured | Observed | Result |
|---|---|---|---|---|
| Main session | `claude-fable-5-1` | project `model` | `claude-fable-5-1` on every assistant turn | PASS |
| `clab-ui-scout` | haiku | `model: haiku` | `claude-haiku-4-5-20251001` (inventory task) | PASS |
| `clab-ui-builder` | sonnet | `model: sonnet` | `claude-sonnet-5` (four implementation tasks) | PASS |
| `clab-ui-reviewer` | opus | `model: opus` | `claude-opus-5` (whole-change review) | PASS |
| `clab-ui-qa` | sonnet | `model: sonnet` | `claude-sonnet-5` (reproduction, B matrix) | PASS |
| `docs-auditor` / `risk-reviewer` | sonnet / opus | as defined | `risk-reviewer` on the helper diff, `docs-auditor` on the guides (models read from the transcripts) | see below |
| `clab-ui-escalation` | fable, if defined | not defined | — | nothing to preserve |

## Environment (checked 2026-09-22)

- Host `clab-llm-dev2`: Docker, containerlab, passwordless sudo, Node 18 (no lab-builder rebuild here,
  none needed), Python 3.12 venv under `clab-backup-ui/.venv` with Playwright.
- Source `main` = `6c3e8b3` = release 1.30.30; branch `claude/multi-platform-restore` at `11e5104`
  is merged into `main`. Work continues on `claude/save-location-fix`.
- Deployed: manager `clab-backup:1.30.30` on TCP 8081 (host network), helpers 1.30.30, capture
  service image `clab-capture-service:1.29.1` (pre-existing, unrelated). Served assets `?v=1.30.30`.
- Lab `restore-square` (four nodes, one per image) was found exited after a host reboot and redeployed
  with `containerlab deploy --reconfigure` from `/srv/containerlab-node-manager/projects/restore-square/`
  at about 07:40 UTC; manager lab id `904a35a79dc341ce8a4638f83fc34185`, bound to
  `CLAB-MNGR-DEV-LLM / restore-square/work` (checkout `~/labs/CLAB-MNGR-DEV-LLM`, remote
  `pruger-dev/CLAB-MNGR-DEV-LLM`, `main`, four unpushed manager commits).

## Findings

- Root cause (source, to be confirmed live): the registration prefix is the lab folder and every layer
  appends `latest` to it. Nothing refuses a prefix that is itself a snapshot folder: `gitFolderChoice`
  only knows `latest` as "managed" when its parent is *registered*, so an unregistered `working/latest`
  (after a move retired the registration, after a re-import, or synced from elsewhere) is offered as a
  destination; typed names (`gitFolderPath`, first save, connect by URL) and the API accept
  `working/latest` too. The helper then writes `working/latest/latest`.
- Apply: `gitTreeModel` marks a folder restorable only when its `latest/` child holds `.jcfg`,
  `.eoscfg` or `.xrcfg`; `restoreFromFolder` appends `/latest`; `allowed_repo_version` and
  `resolve_version_path` accept only name-shaped paths. A `Final/manifest.json` folder is neither
  listed nor appliable, whatever its manifest says.

## Reviews (2026-09-22)

Two independent Opus reviews of the first implementation (`risk-reviewer` on the helper diff,
`clab-ui-reviewer` on the whole change): the security invariants hold (no new mode, argv, file write
or privilege; traversal and `.git` still refused; `publish` cannot delete or overwrite outside the old
manifest). Findings fixed before deployment: `gitOpenCommit`'s fast path still sent a bare `latest`; a
tab opened before the upgrade would have been redirected to a root-level `latest` (hence the leading
slash wire form); the root snapshot's View/Compare/Download sent `''` (422); a top-level lab folder made
the reference group absorb the whole repository; browser and manager disagreed one level below a
snapshot folder; `base_prefix` ran before the "already registered" lookups, so a legacy `x/latest`
binding could not be repaired; the wizard prompt accepted reserved names; the history cap could drop
the lab's own rows; the relaxed publish check would have adopted a directory-only destination.

Accepted as documented limits (not fixed): any file named `manifest.json` is listed as a snapshot until
the preflight reads it (an npm or extension manifest gets an Apply button that fails at review with
the reason); rule 2 is checked against the browse listing, which is capped at 4000 files (`publish`
still refuses to write into a foreign snapshot folder later); `POST …/git/connect` applies the name rule
only (no tree before the clone); a directory named like a device file inside a snapshot folder is
refused with the generic "ordinary, unlinked snapshot files" sentence; a lab stuck at `x/latest`
cannot *move* its files one level up (the parent snapshot exists), which is why the recovery is
"Save this lab here without moving the files".

## Exact next action

The stream is complete: 1.30.31 (`8ea56e0`, PR #49, CI green) carries the code; 1.30.32 carries the four-image
acceptance record (matrix C, all PASS, including the data-plane closure `30-c6-dataplane.md`). If it is picked up
again: (1) a new image or release reruns `tools/c1_prepare.py` and `tools/c_apply.py` on the lab, then adds a row
with evidence; (2) the documented limits in "Reviews" are the open points; (3) for the user: the lab repository
`pruger-dev/CLAB-MNGR-DEV-LLM` now holds the QA fixture folders `save-fix/{working,Final,Broken,Legacy,course,Bad,Missing}`
and a few QA checkpoints; the unassigned credential profile `QA-wrong-password-ceos` still exists; the lab is bound to
`save-fix/working`, all four nodes on the real square configuration A with the mesh healthy.
