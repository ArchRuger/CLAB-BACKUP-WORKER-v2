# Load: "Apply to running lab" inside the header design

Design slice for PROMPT.md section 5.4 (all nine steps and the parity gate), owner decisions D4, D7 and
D10, section 7 items 6 and 7, and the restore rules of section 8. Boards G02 to G09.

Scope: the Load panel, its confirmation, the loading and result views, Undo this load, and the data they
need. Not in scope, named as hand-off points: the chip and its panel shell (header designer), the All
versions and What changed drawers (drawer designer), the folder model and every backend decision (lead).

All code paths are under `clab-backup-ui/`. Citations are `path:line` against the branch
`claude/git-save-load-redesign` at 1.30.60. Nothing in this document was run in a browser or against a
device. One throwaway unit probe was run against a temporary data directory (section 6); it is the only
executed evidence here.

Rule of this slice: the restore service is not redesigned. `app/restore.py` keeps its flow, its
vocabulary and its refusals; the page changes how they are reached and worded.

---

## 1. Today's map

### 1.1 Every way to reach "Apply to running lab…"

| # | Where | Control | Function chain | Source sent to the restore service |
|---|---|---|---|---|
| E1 | Progress tab, Saved versions rows (Latest, Checkpoints, Baseline, Instructor and reference, Other labs, Elsewhere) | `Apply to running lab…` button per row, `app/static/git-progress.js:372`; delegated click `git-progress.js:792` | `gitVersionAction('apply', row)` `git-progress.js:398-402` → `restoreFromFolder(id, row.apply.path, tree)` `app/static/restore.js:150-160` → `restoreReview` `restore.js:162` | `{type:'folder', path:'/<exact snapshot path>'}`; the submit adds the commit the review read (`restore.js:189`) |
| E2 | Saved-version view dialog (`git-version-dialog`), opened by a row's View, by Full history, by a commit | `Apply to running lab…` (danger), only when `restore_supported`, `git-progress.js:754` | `restoreFromVersion(id, {type:'git', commit, path}, name)` `git-progress.js:761` → `restoreReview` `restore.js:141-143` | `{type:'git', commit, path}` |
| E3 | Folder browser (Save location card), any selected folder that is a snapshot or whose `latest/` child is one | `Apply to running lab…` (danger-outline) `app/static/git-places.js:153-154`, wired `git-places.js:210` | `options.onApply` given by `git-progress.js:291` → `restoreFromFolder(id, gitApplySource(dir).path, tree)`; the folder-to-snapshot rule is `gitApplySource` `git-places.js:76-81` | `{type:'folder', path}` |
| E4 | Header save menu and Progress tab More menu | `Load a saved version…` (`data-git-action="load"`), `app/static/index.html:141` and the header menu at `index.html:75` | `gitRunAction('load')` `git-progress.js:771`: shows the Progress tab and scrolls to Saved versions. It starts no restore itself; it leads to E1. | none |
| E5 | Saved versions head | `Browse the repository…` `git-progress.js:388` | `gitRunAction('browse')` `git-progress.js:773`: opens the folder browser, leading to E3 | none |
| E6 | Saved versions head and save menu | `Full history…` `git-progress.js:388` | `gitHistory` `git-progress.js:724-730` → version rows open E2 | via E2 |
| E7 | Lab banner while a restore runs | `View progress` `app/static/app.js:222` | `restoreShowJob(runningRestore.id)` `restore.js:350-358` | none (re-enters the job) |
| E8 | Lab banner after a restore that needs attention | `Details` and `Dismiss` `app.js:224-226` (state from `labFailure`, `app/static/status.js:79`) | `restoreShowJob(job.id)` | none |
| E9 | Progress status card | `Last configuration change: …` line with an open link, `git-progress.js:213-221` | `restoreShowJob(last.id)` | none |
| E10 | Restore job window (`restore-job-dialog`) | opened automatically after submit `restore.js:222`; per-device steps, outcome, Details, links to the pre and post backups `restore.js:376-400` | `restoreRenderJob`, polled every 1.5 s by `restoreStartWatch` `restore.js:401-415` | none |
| E11 | Compare dialog text | The sentence points the person at "Apply to running lab…" `git-progress.js:746` | text only | none |
| E12 | API only | `GET /api/labs/{lab_id}/restore/sources` `app/restore.py:1282-1300` lists local backups that carry restore artifacts. No page script calls it (no hit for `restore/sources` under `app/static/`). | none | would be `{type:'backup', backup_job_id}` |

Global indicators that name a running restore without being entry points: the worker line
`Replacing configuration…` (`app.js:96`), the lab state `Replacing configuration` (`status.js:95`) and
`Checking devices` during a restart read-back (`status.js:94`).

### 1.2 The restore API as it is

Routes (all under the same-origin guard; installed by `RestoreService.install`, `restore.py:1261`):

| Route | Body | Answer |
|---|---|---|
| `GET /api/labs/{lab_id}/restore/sources` | none | `{backups:[{backup_job_id, created, finished, nodes}], supported_nodes, unsupported_nodes, restore_supported_platforms}` `restore.py:1282-1300` |
| `POST /api/labs/{lab_id}/restore/preflight` | `{source, node_names?}` (`Preflight`, `restore.py:1269-1272`) | `{source, targets, eligible_count}` `restore.py:613-614` |
| `POST /api/labs/{lab_id}/restore` | `{request_id (32 hex), source, node_names (1..500), confirm_minutes (2..60, default 5), acknowledge}` (`Run`, `restore.py:1274-1280`) | the public job |
| `GET /api/restore/jobs/{job_id}` | none | the public job `restore.py:1313-1316` |

`Source` is `{type, commit, path, backup_job_id}` with `extra='forbid'` (`restore.py:1262-1267`): a page
must send exactly these keys, never the richer `source` object a preflight or a job returns.

Source types (`resolve_source`, `restore.py:438-525`):

- `git` (`restore.py:442-454`): `commit` + `path`, read with the helper's `read-version` through the
  lab's own binding; `path` goes through `resolve_version_path` (`app/git_progress.py:190-205`).
- `folder` (`restore.py:469-504`): any snapshot folder of the connected repository, `path` exact with
  one leading slash (`/` is the root). Without `commit` the preflight reads HEAD and returns it as
  `source.commit`; a submit that carries `commit` reads exactly that commit (`restore.py:482-493`), so
  the reviewed bytes are the applied bytes. A malformed commit is 400 (`restore.py:483-484`).
- `backup` (`restore.py:455-468`): a backup job of this lab by `backup_job_id`, read with
  `captured_snapshot(..., embedded_files=False)`. 404 when the job is not in `state['jobs']` for this lab.
- anything else: 400 (`restore.py:506`).

Both Git-backed types call `self.git.binding(lab_id)` (`restore.py:444`, `restore.py:477`), which is 409
`Connect this lab to a Git repository first.` for a lab without a save location
(`git_progress.py:592-596`). The folder need not be registered to any lab; the loading lab must be
connected to the repository.

Every source ends in the same candidate table (`restore.py:508-525`): one entry per manifest file that
names a `node`; an entry without a usable `restore_artifact` is kept with `unusable: NO_ARTIFACT`
(`restore.py:50`, `restore.py:511-518`). `desc` gains `restore_capable_nodes` and `saved_nodes`
(`restore.py:523-524`).

Preflight result, per device (`map_targets` `restore.py:529-558`, then the live probe
`restore.py:590-612`):

```
{name, short_name, platform, running_platform, eligible, reason, requested,
 reachable?, matches_saved?, pending_changes?,
 diff?: {hunks, added, removed, truncated, identical, labels:{old,new}, counts_partial?, reason?},
 diff_reason?}
```

- Rows exist only for saved devices (`for name in sorted(candidates)`, `restore.py:532`). A lab device
  that the state does not contain has no row.
- A saved device is matched to a lab device by its full node name (`restore.py:534`), which is the
  container name `clab-<lab>-<node>` (`app/discovery.py:94`).
- Reasons without device access, in order (`restore.py:538-551`): no lab node of that name; no driver
  for the running platform; saved platform differs; no restore data (`NO_ARTIFACT`); candidate unusable
  (`UNUSABLE` + the driver's reason, `restore.py:51`, `restore.py:560-571`); node not running or
  discovery stale; no credentials. Stale discovery turns every eligible row ineligible
  (`restore.py:585-588`).
- Live probe of each eligible, requested row over one connection (`_probe`, `restore.py:645-659`):
  `FOREIGN_PENDING` (`restore.py:52`) or the driver's `blocked()` text makes the row
  `reachable: true, eligible: false`; rejected credentials give `BAD_LOGIN` (`restore.py:53`,
  `restore.py:608-609`); any other failure gives `reachable: false, eligible: false,
  reason: 'SSH probe failed: <ExceptionName>'` (`restore.py:610-612`). Otherwise `matches_saved`
  (the driver comparison's verdict), `pending_changes = len(missing) + len(extra)` and the masked
  review `diff` (`restore.py:600-607`, `review_diff` `restore.py:188-223`).
- The probes run one after another in the request (`restore.py:590`), so a preflight of four devices
  takes several seconds.
- The whole preflight is refused with 409 while anything holds the lab (`guard_idle`,
  `restore.py:428-434`, `restore.py:580`).

Submit (`restore.py:666-731`): idempotent on `request_id` (`restore.py:668-670`, `restore.py:705-707`);
refuses with 409 when any chosen device is ineligible (`restore.py:681-684`) or a second look finds a
pending change or an editor (`restore.py:689-699`); an unreachable device does not refuse the request
and gets its own outcome in the job.

`acknowledge`: the route refuses with 400 `Acknowledge that the running configuration will be
replaced.` unless the body carries `acknowledge: true` (`restore.py:1309-1310`, pinned by
`tests/test_restore.py:607`). It is a request-shape gate only; nothing is stored. Today its only sender
is `restoreReview`'s run handler, after the tick box check (`restore.js:217`, `restore.js:219-220`).

The job as `restore.public_job` exposes it (`restore.py:47-48`, `restore.py:83-92`), also in
`/api/state` as `restore_jobs` (`app/main.py:225`):

```
{id, lab_id, lab_name, created, finished, status, message,
 source: {type, path?, folder?, commit?, backup_job_id?, captured_at, lab_name,
          restore_capable_nodes, saved_nodes},
 confirm_minutes, pre_backup_job_id, post_backup_job_id,
 targets: [{name, short_name, platform, status, message, stage, timeline, attempts,
            worker?, diff_sample?, no_op?, persistence?, root_authentication?,
            missing_statements?, extra_statements?, missing_sample?, extra_sample?}],
 progress: {settled, total},
 rechecking: bool, server_time}
```

Keys that start with `_` (token, deadline, handle, candidates) never leave the service
(`restore.py:85-87`). `created` and `finished` are ISO UTC strings (`app/runner.py:34-35`).

Vocabulary:

- Job status while busy: `queued, preflight, backing_up, applying, confirming, verifying`
  (`app/lab_operations.py:30`). Final: `succeeded` (every target verified), `failed` (nothing replaced,
  nothing to review), `needs_attention`, `partial` (`_finalize`, `restore.py:1235-1247`);
  `preflight_failed` or `failed` for a controlled stop before any device was changed
  (`restore.py:834-838`); `needs_attention` for an internal error (`restore.py:843`); `interrupted`
  after a manager restart, with `rechecking: true` while devices are still read back
  (`restore.py:270-273`, `restore.py:90`).
- Target status: `pending, backing_up, applying, confirming` while running; outcomes `verified`,
  `applied` (transient, before the check), `applied_unverified`, `verify_mismatch`, `failed`,
  `ineligible`, `rolled_back`, `uncertain`, `interrupted`; `rollback_expected` only on jobs stored
  before 1.30.27 (`docs/multi-platform-restore/README.md`, "Outcomes the manager reports per node").
- `rolled_back` is written only by `_record_settled` when `_settle` returned it
  (`restore.py:1103-1108`), and `_settle` returns it only after it captured the device and the
  previous configuration compared equal, with the change known to have been armed
  (`restore.py:1057-1060`). The same read-back without proof of arming is `failed` with the sentence
  `Configuration was not changed. Checked: …` (`restore.py:1109-1117`). Everything else that could not
  be established is `uncertain` (`restore.py:1061`, `restore.py:1118-1122`).
- Stage (a label beside the status, `restore.py:56-66`): `queued, backing_up, backed_up, connecting,
  applying, armed, verifying, confirming, checking`, final `replaced, matched, skipped, failed,
  rolled_back, uncertain`. `timeline.settled` is the first final outcome and feeds `progress.settled`
  (`restore.py:235-244`).

---

## 2. The Load panel's data

### 2.1 Where the two lists come from today

Both lists are today's Saved versions groups, built in the browser by `gitVersionGroups`
(`git-progress.js:321-368`) from one repository tree.

| Piece | Today | Cost and freshness |
|---|---|---|
| Repository tree | `GET /api/git/repositories/{binding_id}/tree` (`git_progress.py:1168-1177`) → helper mode `browse` (`app/host_git.py:775-793`): `git ls-tree -r -l` of HEAD, cut at 4000 files (`host_git.py:37`), plus three `git log -1` calls for the lab's own `latest`, `baseline`, `checkpoints` times | One SSH round trip through the gateway under the helper lock (`git_progress.py:570-578`). Not cached by the manager. The page fetches it when the Progress tab is shown for a lab and on a forced refresh (`gitShowRepository`, `git-progress.js:233-242`), and keeps the last one in `gitVersionTree` (`git-progress.js:285`). It is not part of the 4 s poll. |
| Snapshot detection | `gitTreeModel` marks a folder `snapshot` when it holds `manifest.json` among its own files (`git-places.js:64`); a parent whose `latest/` child is a snapshot gets `latestSnapshot` (`git-places.js:66`) | pure, in the browser |
| Your saves: latest | `groups.latest`: `<prefix>/latest` when it has files (`git-progress.js:329-330`); time from `tree.saved.latest`, name from the newest finished save's `note` (`git-progress.js:325-326`) | from the tree and `/api/state` `git_jobs` |
| Your saves: checkpoints | `groups.checkpoints`: each folder under `<prefix>/checkpoints` (`git-progress.js:331-332`); time and note from the matching save job | same |
| Baseline | `groups.baseline` (`git-progress.js:333-334`) | same |
| Lab states | `groups.reference`: every other snapshot folder at or below the lab folder's parent (two levels for a top-level lab folder, `git-progress.js:335-346`, `git-progress.js:357`); `groups.elsewhere`: the rest (`git-progress.js:358`); `groups.others`: snapshots inside another lab's registered folder, named by that lab (`git-progress.js:355-356`) | same |
| Row name | `savedVersionName(folder)` (`status.js:171-177`): last path segment, with `final`/`solution` → `Final state (instructor)`, `start`/`base`/`initial` → `Starting state`, `broken-N` → `Troubleshooting scenario N`; pinned by `tests/test_status_ui.js:176-180` | pure |
| Fallback when the tree is unavailable | `GET /api/labs/{lab_id}/git/history` (`git_progress.py:1498-1506`) → helper `history` (`host_git.py:664-687`): every `manifest.json` folder at HEAD, `connected` for the lab's own; the manager labels each with `version_label` (`git_progress.py:166-176`); rows built at `git-progress.js:360-366` carry no apply | one SSH round trip |

### 2.2 The panel's lists

`Your saves` = `groups.latest` (one row, named by the save's name) followed by the three most recent
`groups.checkpoints` (newest first). `Lab states` = `groups.reference`, then `groups.elsewhere`, capped
at eight rows; when more exist the group ends with `N more in All versions`. `groups.others` (another
lab's own saves) and the baseline appear in All versions only (5.7), not in the panel. All three
groups stay reachable through **All versions** and **Browse the repository…**.

Hand-off (lead, folder model): `gitVersionsOwner` (`git-progress.js:317`) and the `reference` /
`others` / `elsewhere` split depend on registrations. If D8 changes what a registration is, the split
changes with it; the panel only needs "this lab's own snapshots" and "every other snapshot folder".

Naming. The prompt wants `start`, `broken`, `final` to read **Start**, **Broken**, **Final**. Change
`savedVersionName` so that it returns the last path segment (after a trailing `/latest` is dropped by
the caller, as today at `git-progress.js:348`) with its first letter upper-cased when the segment is
entirely lower case, and unchanged otherwise: `start` → `Start`, `broken-2` → `Broken-2`, `BGP` → `BGP`.
The three special cases go away; `tests/test_status_ui.js:176-180` is rewritten to the new names
(decision 5.4 step 1), not deleted. When two rows of the panel would carry the same name
(`BGP/start`, `OSPF/start`), each shows its parent folder after the name (`Start · BGP`). The exact
path stays visible in All versions. `version_label` (`git_progress.py:166`) is unchanged; it labels
history rows only.

Refresh. The lists are fetched when the Load panel opens and after a save of this lab finishes or
**Update from the repository** ran; never on the 4 s poll (each fetch is an SSH call that takes the
helper lock). The panel renders the previous answer at once when it has one for this lab and replaces
it through `setMarkup` when the new answer arrives.

### 2.3 What is missing, and the smallest addition for each

**M1. Device coverage on the row (`2 of 4 devices`).** The tree lists file names, not manifests. File
names are `<short label>.<suffix>` and get a hash on collision (`git_progress.py:403-415`), so they do
not identify lab devices. Today the coverage is known only after `read-version`, which returns every
file of one snapshot (`host_git.py:697-726`).

**M2. `View only` with its reason.** Today the list offers Apply for every `manifest.json` folder
(`git-progress.js:348`); the lack of restore artifacts shows only after the preflight, as every device
skipped (`NO_ARTIFACT`, pinned by `tests/test_restore.py:571`), or in the version view as
`restore_supported: false` (`git_progress.py:1516-1519`).

**M3. Topology comparison.** The manifest carries `topology_digest`, `topology_provenance` and, for
saves since 1.30.57, a `kind: 'topology'` file entry (`git_progress.py:437-467`). Nothing compares them
with the lab today.

Proposed additions (the lead decides each; none adds a NOS command, none touches the transaction):

**B1. Helper mode `states` (read-only) in `app/host_git.py`, beside `history`.** No input beyond the
binding. For every `manifest.json` folder at HEAD (the walk `history` already does,
`host_git.py:677-687`, same cap and the same "own snapshots are never cut" rule) it reads the manifest
with the existing `git show <head>:<folder>/manifest.json` call shape (`host_git.py:704`) and returns a
reduced, fixed-shape summary, never file contents:

```
{head, truncated,
 states: [{path, connected, lab_name, captured_at, topology_digest, topology_file: bool,
           devices: [{node, short_name, platform, restore: bool}]}]}
```

`devices` are the manifest entries that carry `node`; `restore` is "has a `restore_artifact`". A
manifest that is not valid JSON or exceeds the existing limits yields
`{path, invalid: true}` so the row can say so. The option whitelist grows by one mode name; the
gateway's command list does not change. This is a `host_*.py` change: security review, helper version
lockstep and `--refresh` apply.

**B2. Manager route `GET /api/labs/{lab_id}/restore/states`, in `RestoreService.install`.** It lives in
`restore.py` because coverage is the no-device half of `map_targets` and needs
`restore_drivers.for_platform` (`git_progress.py` cannot import `restore.py`; `restore.py` already
imports from it, `restore.py:40`). It calls `self.git.invoke({'mode': 'states'}, binding)` and answers,
through a new `public_state(row)` function that copies only these keys:

```
{head, truncated, lab_devices,
 states: [{path: '/BGP/final', connected, captured_at, saved_devices, loadable_devices,
           view_only: bool, view_only_reason: 'no_restore_data' | 'invalid' | '',
           topology: {differs: true|false|null, saved_devices, matching_devices}}]}
```

- `lab_devices`: lab nodes whose platform has a restore driver.
- `loadable_devices`: saved devices that match a lab node by name with the same platform, have a
  driver and carry a restore artifact. These are the first four tests of `map_targets`
  (`restore.py:538-545`); factor them into one module function used by both so the list and the
  preflight cannot disagree. No device is contacted.
- `view_only`: no saved device carries a restore artifact.
- `topology`: see B3.

`restore.py` gains no NOS knowledge: it reads manifest metadata and asks the driver registry whether a
kind is supported, as `sources` already does (`restore.py:1291-1292`). With B2 the panel needs one
round trip (`states`) instead of the tree; the names and times of the lab's own rows still come from
`git_jobs`.

Fallback when the lead refuses a helper change (B1): the panel uses the tree it has. `View only` is
then "the snapshot folder holds no file with a restore suffix" (`jcfg`, `eoscfg`, `xrcfg`, from
`state.platforms[*].restore_suffix`, `app/inventory.py:17-30`), and the row shows the count of such
files as `2 device files` instead of `2 of 4 devices`, because without the manifest the files cannot be
matched to lab devices. The exact coverage then appears at the confirmation only. This fallback does
not meet 5.4 step 2 literally and should be chosen knowingly.

**B3. Topology comparison in the source description.** In `resolve_source`, after the manifest is
read, add to `desc` (which the preflight returns and the job stores as `source`, exposed by
`public_job`):

```
topology: {differs: true|false|null, saved_devices: n, matching_devices: m}
```

`differs` is `null` when either digest is unknown (a backup source, a manifest without one, a lab
without a stored topology), else whether `manifest.topology_digest` differs from the SHA-256 of the
lab's `definition_yaml`, the digest a save computes for the same lab (`git_progress.py:1352`).
`matching_devices` is computed in `preflight` from the rows: saved devices whose row has a lab node of
that name and the same platform. Counts and booleans only. For **View its topology** the page opens
the state's files (today's version view, `git-progress.js:749-764`; in the new design the All versions
**View files**, drawer designer) at the topology file, which every manifest-listed file view already
includes (`git_progress.py:494-498`, `git_progress.py:1516-1518`).

Caveat for the reviewer: an `embedded` digest is the hash of the VM's topology file
(`git_progress.py:462`), while the lab side is the manager's copy. If those two can differ in bytes for
the same lab, `differs` is true without a real difference. The line is then still accurate about the
devices (`all 4 devices match`), but it is noise. See open question Q4.

---

## 3. The confirmation (G03, G07)

Choosing a row calls `loadChoose(labId, source, name)`. The panel shows `Checking <name> against your
devices…` (busy dot) while `POST …/restore/preflight` runs with `{source}` (no `node_names`, so every
saved device is probed, as today, `restore.js:166`). Then:

Headline `Load <name>?`, the sentence `The running configuration of the ticked devices is replaced.
The current one is backed up first; nothing reboots.`, and one row per device. The row set is the
preflight's `targets` plus, for G07, every lab device with a restore driver that has no row (derived in
the page from the lab's nodes and `state.platforms`; the preflight returns rows for saved devices only,
`restore.py:532`).

| Preflight row | Tick box | Right-hand text | Row class |
|---|---|---|---|
| `eligible`, `matches_saved` true | real input, ticked | `Already matches` | |
| `eligible`, `pending_changes` = n > 0 | ticked | `n lines differ` (`1 line differs`) | |
| `eligible`, no comparison (`matches_saved` absent) | ticked | `Ready to load` | |
| `reachable: false` (`SSH probe failed…`) | disabled, unticked | `Not reachable` and, under the name, `The device did not answer over SSH.` | `is-off` |
| `reachable: true`, not eligible (pending change, editor, rejected login) | disabled, unticked | `Blocked` and, under the name, the mapped reason | `is-off` |
| not eligible without a probe (not running, stale discovery, no credentials, platform differs, unsupported platform, no restore data, unusable data) | disabled, unticked | `Can't load` and the mapped reason | `is-off` |
| saved device with no lab node (`No running node in this lab matches…`) | disabled, unticked | `Not in this lab` | `is-off` |
| lab device with no row (page-derived) | disabled, unticked | `Not in this state` | `is-off` |

- `n` is `pending_changes`, the driver comparison's count (`restore.py:602-603`), the number today's
  dialog shows (`restore.js:178-179`). It is consistent with `matches_saved` by construction.
- Reasons go through today's `restoreReasonLabel` table (`restore.js:40-51`, `restore.js:100-104`),
  reworded where it says "saved version" (section 10). A reason is visible text under the device name,
  never a tooltip only. Where an action clears it, the action is named in the sentence
  (`Add login credentials for this device first (Advanced › Credentials).`).
- A disabled tick box cannot be ticked, and the submit sends only ticked names; the server would
  refuse an ineligible name anyway (`restore.py:681-684`).
- Leaving a device out is unticking it. With nothing ticked, **Load** is disabled and the line
  `Tick at least one device.` shows beside it.
- When no row is eligible: **Load** is disabled, the headline stays, and the sentence is replaced by
  `None of the devices can be loaded right now.`; each row still shows its reason.
- Subset (G07): the sentence becomes `This state covers 2 of your 4 devices. The others are left as
  they are.` when at least one lab device has no row.
- Topology line (B3), when `source.topology.differs` is true: `Saved on a different topology: 3 of 4
  devices match.` with the quiet button **View its topology**. Load changes device configurations
  only (D10); the line never offers to change the topology.
- Folded `Options` (parity with today's Advanced options, `restore.js:203-206`):
  `Undo automatically if a device cannot be reached again within [5] minutes` (number input, 2 to 60).
  The sentence `Each device checks the new configuration itself and undoes it if it loses contact.`
  stays visible above it.

Actions: **Load** (`button danger`), **Cancel** (back to the list; nothing was sent), **See what's
different**.

**The red Load button is the acknowledgement (D4).** There is no tick box. `loadSubmit()` is the one
function that posts to `/labs/{id}/restore`, and its body is built in one place:

```
{request_id, source: submitSource, node_names: <ticked>, confirm_minutes, acknowledge: true}
```

- `request_id` is made once per review (`restoreRequestId`, `restore.js:74-77`), so a double click or
  a retry after a lost answer returns the same job (`restore.py:668-670`).
- `submitSource` keeps today's rule (`restore.js:189`): a folder source carries the commit the
  preflight returned; `git` and `backup` sources are sent as chosen. Only the four `Source` keys are
  sent.
- `loadSubmit` is reachable only from the click handler of the danger button of a rendered
  confirmation (panel or the differences drawer below). `restoreFromVersion`, `restoreFromFolder`,
  `loadChoose`, `loadUndo` and `loadRetry` all end in the confirmation, never in `loadSubmit`.
- The server rule is unchanged: without `acknowledge: true` the route answers 400
  (`restore.py:1309-1310`).
- Node test (section 11): the string `acknowledge` followed by `true` occurs exactly once in the
  page scripts in a request to a `/restore` route, inside `loadSubmit`. (`git-progress.js:700` sends
  `{acknowledge:true}` to the Git dismiss route; that is a different route and stays.)

**See what's different** opens today's review differences: for every eligible row that differs,
`restoreDiffDetails(r)` (`restore.js:337-347`), which renders the preflight's masked `diff` through
`diffMarkup` (`app/static/diff-view.js:27`), saved against running now. No new request. It is shown in
a drawer in the visual language of What changed (F04), headed `What's different` with the meta line
`<name> compared with what the devices run now`, and **Load** / **Back** at the top. Because only one
panel or drawer is open at a time (5.1), the review lives in one module object
(`loadReview = {labId, source, name, review, chosen, minutes, requestId}`); the panel and the drawer
both render from it, ticks made in one are kept in the other, and **Back** reopens the panel in the
confirmation. Hand-off (drawer designer): the drawer shell; this slice supplies its body and its two
buttons.

---

## 4. Loading (G04)

After a successful submit the panel shows the job. Headline `Loading <name>…` (busy dot), sentence
`Each device checks the new configuration itself and undoes it if it loses contact. You can keep
working.`, and one row per `job.targets[]` entry (name from `short_name || name`, kind label from
`restorePlatformLabel`, `restore.js:35-38`).

Row text, from `target.status` and `target.stage` only:

| Condition | Text | Class |
|---|---|---|
| `restoreTargetOutcome(t)` returns an outcome (`restore.js:230-235`) | the final word of section 5 | per outcome |
| else `stage` is `queued` (or absent on an old job with `status: 'pending'`) | `Waiting` | |
| else `stage` is `backing_up` or `backed_up` | `Backing up…` | `now` |
| else (`connecting`, `applying`, `armed`, `verifying`, `confirming`, `checking`) | `Loading…` | `now` |
| job is `rechecking` and the target awaits its read-back (`restoreTargetRechecking`, `restore.js:15`) | `Checking…` | `now` |

`Backing up…` is one word more than the mockup's three. It is kept because the mandatory backup is a
distinct, visible step and today's label says it (`restore.js:24`); `Waiting` for a device whose
configuration is being read would be wrong. A device replaced and still under the follow-up check
(`status: 'applied'`, `stage: 'checking'`) reads `Loading…`, never `Loaded`: `restoreTargetOutcome`
returns null for it (`restore.js:231`), the claim `tests/test_restore_ui.js:176` pins.

Chip text `Loading… 2 of 4`: `2` is the number of targets for which the row shows a final word (the
same function as the rows, so chip and list cannot disagree), `4` is `targets.length`. It counts
devices that are finished, whatever their outcome. `job.progress.settled` (`restore.py:243-244`) is not
used: it counts a device at its first outcome, before the follow-up check, and would run ahead of the
rows.

Closing the panel does not stop the load. The job runs in the manager's own pool (`restore.py:728`)
and no route cancels a restore; the page holds nothing the job needs. The panel says so in its
sentence. While a job of this lab is active the Load panel and the chip panel both show this view
(hand-off, header designer: the chip panel calls `loadJobMarkup(job)` for the states *Loading*,
*Running* and *Partial*). An open view polls `GET /api/restore/jobs/{id}` every 1.5 s, as
`restoreStartWatch` does (`restore.js:401-415`), and re-renders through `setMarkup`; the chip itself
follows the 4 s `/api/state` poll. A poll that fails shows `Status updates paused.` with **Refresh**,
as today (`restore.js:388-389`).

Save and Load are disabled while a load runs (5.2), each with the visible reason `A load is running.`
The server would refuse both anyway (`guard_idle`, `restore.py:428-434`; `operation_busy`,
`lab_operations.py:58-75`).

---

## 5. Results (G05, G06)

### 5.1 Device words

One table, `STATUS_LOAD_WORDS` in `status.js`, keyed by the restore service's target status. Nothing
else maps an outcome to words in the panel.

| Target status (service) | Row text | Class | Meaning kept from the service |
|---|---|---|---|
| `verified` | `Loaded` | `ok` | replaced, confirmed, and a fresh capture equals the state |
| `verified` or `applied` with `stage: 'matched'` | `Already matched` | `ok` | the device reported nothing to change (`restore.py:63`, `restore.js:232-233`) |
| `applied` (only while the check runs) | not final; `Loading…` | `now` | |
| `applied_unverified` | `Loaded, not verified` | `warn` | replaced; the follow-up check did not run |
| `verify_mismatch` | `Loaded, differences remain` | `warn` | replaced; the comparison found differences |
| `failed` | `Not loaded` and, under the name, `restoreNotChangedReason(message)` (`restore.js:107-109`) | `bad` | not changed |
| `ineligible` | `Skipped` | | not running at start (`restore.py:773`) |
| `rolled_back` | `Kept previous` and, under the name, `Undid the change; its previous configuration was read back.` | `bad` | only `restore.py:1103-1108` writes it, only after the read-back of `restore.py:1057-1060` |
| `uncertain` | `Not confirmed` and, under the name, `The manager could not check what this device runs. Open Details.` | `warn` | `restore.py:1118-1122`, `restore.py:884-887` |
| `interrupted` (finished job) | `Interrupted` and `Open Details.` | `warn` | a restart before or during the change |
| `rollback_expected` (jobs before 1.30.27) | `Not confirmed` and `Open Details.` | `warn` | the manager had not read the device back |

`Kept previous` appears for `rolled_back` and for nothing else. In particular a `failed` device whose
message says the previous configuration was checked (`restore.py:1113-1115`) reads `Not loaded` with
that sentence as its reason, because the service did not call it a rollback. G06's mockup shows
`Kept previous` for a device that "did not accept" the state; under the prompt's rule that device is
`failed` and reads `Not loaded` with the driver's reason. The headline sentence differs accordingly
(section 10).

### 5.2 Chip state after a load

Definitions, over `/api/state` (pure function `loadState(lab, ctx)` in `status.js`, beside
`progressState`, `status.js:139`):

- `replaced(t)`: `t.status` in `verified, applied, applied_unverified, verify_mismatch` (today's
  `restoreReplacedTarget`, `restore.js:31`).
- `unknown(t)`: `t.status` in `uncertain, interrupted, rollback_expected`.
- An *effective load* is a finished restore job of this lab (not `statusRestoreActive`,
  `status.js:31`) with at least one target that is `replaced` or `unknown`. A job that changed nothing
  (every target `failed`, `ineligible` or `rolled_back`; job status `failed` or `preflight_failed`) is
  not an effective load: the devices run what they ran before, so the chip keeps what it showed. Its
  failure is still surfaced by the lab banner (`labFailure`, `status.js:79`) and by the panel
  (5.4 below).
- `L` is the newest effective load by `finished`. `S` is the newest completed save of this lab
  (section 7).

| Chip | Condition | Text |
|---|---|---|
| *Loading* | a restore job of this lab is active (busy status, or `interrupted` with `rechecking`) | `Loading… k of m` (section 4); during a restart read-back `Checking devices…` |
| *Running* | `L` exists, is newer than `S`, and `L.status === 'succeeded'` | `Running <name>` |
| *Partial* | `L` exists, is newer than `S`, and `L.status !== 'succeeded'` | `Loaded n of m`: `n` = targets with status `verified`, `m` = `targets.length` |
| (save states) | otherwise | header designer |

`succeeded` means every target is `verified` (`restore.py:1235-1237`); so *Running* is never shown
while any device is unverified, uncertain or unchanged. `n` counts `verified` only, the count the
service itself reports (`restore.py:1243`, `restore.py:1247`). A job with four replaced devices of
which one is `applied_unverified` therefore reads `Loaded 3 of 4` (amber), and its row says
`Loaded, not verified`: the chip never rounds an unverified device up.

Name in `Running <name>`: `loadSourceName(job.source, ctx)`, derived, nothing stored:

- `folder` / `git`: the lab's own `latest` → the name of the save that wrote it (`git_jobs` note), else
  `your latest save`; `checkpoints/<x>` → `x`; `baseline` → `your starting point`; any other path →
  `savedVersionName(folder)`.
- `backup`: when the backup job in `state.jobs` has `source === 'restore-pre'` and its `progress_id`
  names a restore job still listed (`runner.py:319-320`, exposed whole by `decorate_job`,
  `app/downloads.py:149-157`, `main.py:222`): `the configuration from before <that job's name>`;
  otherwise `a backup from <time>`.

### 5.3 Result panels

All loaded (G05), chip panel: `Running <name>` / `Loaded <when> on all <m> devices.` /
`Your latest save: <name>, <when>` / `Before loading: backed up automatically` /
**Undo this load**, **What changed**. Toast, once per job, when the page sees the job leave the active
set: `<Name> loaded on <m> devices.`

Some not changed (G06): headline `Loaded on n of m devices`, one summary sentence (section 10), one row
per device with the words of 5.1, then **Try <device> again** (primary), **Undo this load**,
**Details**.

**What changed** and **Details** both open today's restore job window, `restoreShowJob(job.id)`
(`restore.js:350-358`): the per-device step list, the outcome sentences, the masked `diff_sample` is
not shown there today and is not added; the links to the backups taken before and after
(`restore.js:380-387`). The window is unchanged except for wording that names the removed tab
(section 10). It remains the place where `uncertain`, `interrupted` and `verify_mismatch` are explained
in the service's own terms.

**Try <device> again** (`loadRetry(job)`):

- Devices: the targets with status `failed`, `rolled_back` or `ineligible`. The button names one
  device (`Try xrv9k again`) or counts them (`Try 2 devices again`). When there is none (only
  `uncertain`, `interrupted` or unverified devices remain) the button is absent: those devices send
  the person to Details first, and a new load of them starts from Load like any other.
- It rebuilds the source from `job.source` using only the `Source` keys: `{type:'folder', path,
  commit}` (the same commit, so the same bytes as the first attempt), `{type:'git', commit, path}` or
  `{type:'backup', backup_job_id}`.
- It runs the preflight with `node_names` set to those devices (`restore.py:1304`; unrequested rows
  are not probed, `restore.py:591`) and shows the confirmation of section 3 with only those rows, plus
  the line `Only the devices that were not loaded are listed.` The red **Load** submits with a fresh
  `request_id`. There is no shortcut around the preflight, the confirmation or the backup.

A load that changed nothing (not an effective load): the panel that was following the job shows
`<Name> was not loaded` / `No device was changed.` with the rows, **Try again** (the same rule as
above) and **Details**. The chip returns to what it showed before; the lab banner carries the failure
with **Details** and **Dismiss** as today (`app.js:224-226`).

---

## 6. Undo this load (D7)

`loadUndo(job)` = `loadChoose(labId, {type:'backup', backup_job_id: job.pre_backup_job_id},
'the configuration from before <name>')`. It is an ordinary load: same preflight, same confirmation
(headline `Undo loading <name>?`, same sentence, same rows), same red **Load**, same mandatory backup,
same transaction. No new restore mechanism and no new route.

Verified in the code:

- The source exists and is resolved like the others: `restore.py:455-468` reads the backup job of this
  lab, builds the same manifest and candidate table as a Git save (`captured_snapshot`,
  `git_progress.py:364-468`, restore artifacts at `git_progress.py:392-395` and
  `git_progress.py:421-431`), and from `restore.py:508` on nothing depends on the source type.
- It is the best-tested source: the service tests use it throughout (`tests/test_restore.py:168`).
- The pre-load backup is an ordinary Runner backup (`restore.py:783-785`) and therefore stores each
  device's restore artifact where the platform has one (`runner.py:485-497`).
- Throwaway probe (scratch script outside the repository, subclassing the existing test fixture, on a
  temporary data directory; unit level, fake devices): after a full load, a preflight of
  `{type:'backup', backup_job_id: <pre_backup_job_id>}` returned both devices eligible with
  `saved_nodes` equal to the loaded devices; submitting it produced a `succeeded` job with its own,
  different `pre_backup_job_id`. Exit status 0. This is not live evidence.

Edge cases:

| Case | What happens today | Design |
|---|---|---|
| The backup covers only the devices that were loaded | `saved_nodes` is exactly the job's live targets (`restore.py:783-785`); other lab devices have no row | The confirmation shows them as `Not in this state` (G07 rule), with the sentence `This undoes the load on the n devices it changed. The others are left as they are.` |
| A device was skipped before the backup (`ineligible`) | not in the backup (`restore.py:768-774`) | same as above |
| The safety backup failed for one device | The load leaves that device unchanged (`restore.py:916-920`) and the backup job is `partial`. `captured_snapshot` refuses any backup with a non-succeeded node (`git_progress.py:367-369`), so the whole undo is refused with 400 `Capture incomplete. Every included device must have a successful file; latest is unchanged.` (confirmed by the probe) | **Backend addition B4** below. Until then: **Undo this load** is disabled with `The automatic backup of this load is incomplete, so it cannot be undone in one step.` and **Details** beside it. |
| The backup holds no restore artifact for a device (the artifact capture is best-effort, `runner.py:485-497`) | the row is ineligible with `NO_ARTIFACT` | the row says so; the other devices can still be undone |
| The backup record was pruned (`jobs` is capped at 300 per lab, `runner.py:28`, `runner.py:326-327`; a pre-load backup is protected only while its restore job is busy or interrupted, `runner.py:197-199`) | 404 `Saved capture not found in this lab.` (confirmed by the probe) | The page checks `state.jobs` for `pre_backup_job_id` before offering the action; when absent, **Undo this load** is disabled with `The automatic backup of this load is no longer kept.` **Backend addition B5** keeps it for the newest load. |
| The job failed before changing anything | `pre_backup_job_id` may be empty (`restore.py:713`) or name a backup of unchanged devices | Not an effective load (5.2), so no chip panel offers Undo. In the failure panel the action is absent. |
| The job has no `pre_backup_job_id` or its backup job is `failed` | nothing to load | action absent |
| Undo after a partial load | the backup covers every device that was backed up, a superset of the devices changed | The preflight shows unchanged devices as `Already matches`; they stay ticked or can be left out. A device that is now unreachable shows that reason and cannot be ticked. |
| Devices left `uncertain` by the load | their state is unknown; the preflight may find a foreign pending change and block them | Rows show the preflight's reason; nothing is guessed. |
| Undo of an undo | The undo is a restore job with its own pre-load backup (the state that was loaded). | The chip reads `Running the configuration from before <name>`; its panel offers **Undo this load** again, which reloads what the first load had put there. It is a toggle between two captured states, each step with its own backup. |
| A save happened after the load | the chip is no longer *Running* (section 7) | Undo is offered only in the *Running* and *Partial* panels. The pre-load backup stays reachable under Advanced › Backups, where today's backup record lives. |

**B4. Undo with an incomplete safety backup.** `captured_snapshot` gains a keyword
(`complete=True`). With `complete=False` it keeps only nodes with `status == 'succeeded'` and skips the
scope check of `git_progress.py:371-373`; everything else (digest checks, limits) is unchanged.
`resolve_source` passes `complete=False` only when the backup job's `source` is `restore-pre`. A device
whose safety backup failed was never changed by that load (`restore.py:916-920`), so leaving it out of
the undo loses nothing. Git saves keep the strict default: "an older configuration is never saved in
its place" is untouched. Reviewer attention: this relaxes a check inside a function the save path
shares; the default must stay strict and be pinned by a test.

**B5. Keep the newest load's safety backup findable.** `protected_job_ids` (`runner.py:182-200`) also
protects `pre_backup_job_id` of each lab's newest restore job that has a `replaced` or `unknown`
target. One extra id per lab; no other trimming changes.

---

## 7. When the chip leaves *Running*

Rule: the chip is *Running* or *Partial* while the newest effective load `L` (5.2) is newer than the
newest completed save `S` of the same lab, and leaves it when the next save completes.

- `time(L)` = `L.finished` (set by `_finalize`, `restore.py:1249`; ISO UTC, `runner.py:34-35`).
- `S` = newest job in `git_jobs` with this `lab_id`, a save target (`latest`, `checkpoint`,
  `baseline`, and the lab-state target the lead defines for D9; not `move`, not `update`, not a design
  export) and a status in `synced, committed, review_pending, push_pending, unchanged`, the set
  `gitVersionGroups` treats as done (`git-progress.js:324`). `time(S)` = `finished || created`.
  `unchanged` counts: a save right after loading one's own latest completes without a commit, and the
  lab is then at its latest save.
- Compare with `statusEpoch` (`status.js:41`), which reads both forms.

Fields in `/api/state`, all present today, nothing new is needed for the chip:

| Field | Produced at |
|---|---|
| `restore_jobs[].lab_id, status, created, finished, source, pre_backup_job_id, targets[].name/short_name/platform/status/stage/timeline, rechecking` | `restore.py:47-48`, `restore.py:83-92`, served at `main.py:225` |
| `git_jobs[].lab_id, target, checkpoint, status, created, finished, note, snapshot_path` | `git_progress.py:40-42`, `git_progress.py:60-61`, served at `main.py:224` |
| `jobs[].id, source, status, progress_id, nodes[].status/restore_file` (is the pre-load backup still there, and is it complete) | `runner.py:316-320`, `runner.py:485-497`, served at `main.py:222` |
| `labs[].nodes[].name/short_name/platform`, `platforms` (which kinds have a restore format) | `main.py:154-166`, `main.py:223`, `inventory.py:17-30` |

`loadState(lab, ctx, now)` returns
`{key: 'loading'|'running'|'partial'|'', job, name, loaded, total, done, at, undo: {available, reason}}`.
The header designer's chip function calls it first for the three load states and falls through to the
save states when `key` is empty.

Limits to know: `restore_jobs` is capped at 200 for the whole manager (`restore.py:142`,
`restore.py:157-161`); a load older than that disappears and the chip falls back to the save state.
*Remove lab* drops the lab's restore jobs (`main.py:249`).

---

## 8. Not running, no saves, any folder

**Lab not running (G09).** When `labState(lab, ctx).key` is `stopped` (`status.js:101`), the Load panel
shows `Start the lab to load a state` / `Loading puts a saved configuration onto running devices. This
lab is not running.` / **Start lab**. The button calls `startLab()` (`app.js:200`), which runs the
header's own start action, `opQuickRun('start')` (`app/static/operations.js:679`), exactly as the lab
banner's start button does (`app.js:215-216`); it mirrors that button's disabled state and shows its
reason as text. No preflight is sent. For any other lab state the list is shown and the preflight
decides per device (a partly running lab loads the devices that run). After the start the person
presses Load again; the panel does not load on its own.

**No saves of its own (G08).** The lab has a save location but `groups.latest` and
`groups.checkpoints` are empty: the panel opens with `This lab has no saves of its own yet. You can
start from one of these.` and the Lab states group. With no lab states either:
`Nothing is saved in this repository yet. Save this lab, or ask your instructor for the course's lab
states.`

**No save location.** Today the Git-backed sources require the loading lab's own binding
(`restore.py:444`, `restore.py:477`, `git_progress.py:592-596`). The panel shows `Choose where this lab
saves to see the states you can load.` with the first-save action of 5.9 (header designer). Whether a
lab without a save location may read a registered repository is the lead's folder-model decision
(open question Q3).

**Any folder of the repository.** Verified: the `folder` source reads any safe path of the checkout,
registered or not. The manager resolves the path exactly (`restore.py:478-481`), the helper's
`read-version` accepts any safe folder (`allowed_repo_version`, `host_git.py:689-695`) and refuses only
a folder without `manifest.json` or a commit outside the branch history (`host_git.py:701-705`); the
service test `tests/test_restore.py:416` applies a sibling folder without rebinding. The browser rule
for "which snapshot does this folder mean" is `gitApplySource` (`git-places.js:76-81`): the folder
itself when it is a snapshot, else its `latest/` child, never a substitute for a folder that is itself
a snapshot (pinned by `tests/test_git_places_ui.js:302`).

The Load panel reuses, unchanged: `gitTreeModel` and `gitApplySource` (`git-places.js`),
`gitVersionGroups` and `gitSnapshotPath` (`git-progress.js:34`), `restoreFromFolder`'s path
normalisation (`restore.js:152-153`, pinned by `tests/test_restore_ui.js:32`), the `folder` source and
its commit pinning. **Browse the repository…** hands over to the folder browser (lead and drawer
designer); its action on a folder for which `gitApplySource` answers is **Load this state…**, calling
`loadChoose(labId, {type:'folder', path}, name)`.

---

## 9. Parity table

| Today | New design | Notes |
|---|---|---|
| E1 Saved versions row `Apply to running lab…` (own latest, checkpoints) | Load panel `Your saves` row; All versions row **Load this state…** | same `folder` source |
| E1 Baseline row | All versions `Starting point` row **Load this state…** | not in the panel |
| E1 Instructor and reference rows | Load panel `Lab states` rows; All versions `Lab states` | renamed group |
| E1 Other labs and Elsewhere rows | Load panel `Lab states` (elsewhere, within the cap); All versions folded groups | others: All versions only |
| E2 Saved-version view `Apply to running lab…` (a `git` source at a chosen commit) | All versions row and Full history entry: **Load this state…** calls `loadChoose` with the `git` source | keeps loading an older commit of a folder |
| E2 view-only note for a version without restore data | `View only` row with `Saved without the files needed to load it` and **View** | now visible before choosing |
| E3 Folder browser apply for any folder | **Browse the repository…** → **Load this state…** on any snapshot folder | `gitApplySource` unchanged |
| E4 `Load a saved version…` | the **Load** button | one click instead of a tab change and scroll |
| E5 `Browse the repository…` | same words, foot of the Load panel and of All versions | |
| E6 `Full history…` | foot of All versions | drawer designer |
| E7 Banner `View progress` while a restore runs | chip *Loading* with the device list; the banner keeps **View progress** → job window | both stay |
| E8 Banner `Details` / `Dismiss` after a restore that needs attention | unchanged banner; chip *Partial* with **Details** | |
| E9 `Last configuration change` line | chip *Running* / *Partial* and **What changed** | 5.11 |
| E10 Restore job window | unchanged; opened by **What changed**, **Details** and the banner | |
| E11 Compare text pointing at Apply | reworded to **Load this state…** | |
| E12 `/restore/sources` | route kept, still unused by pages | API parity |
| Review: per-device tick box (leave a device out) | tick boxes in the confirmation | D4 |
| Review: difference count per device | `n lines differ` / `Already matches` | same number (`pending_changes`) |
| Review: `Show differences (saved → running now)` per device | **See what's different** drawer | same data |
| Review: skipped devices with reasons, raw text under Details | reason under each device name; raw text stays in the job window for started jobs | |
| Review: saved time and pinned commit beside the source | meta line of the differences drawer (`saved <when> · <commit 10>`) | not in the small panel |
| Review: Advanced options, undo window minutes | folded `Options` in the confirmation | same bounds |
| Review: acknowledgement tick box | removed; the red **Load** is the acknowledgement | D4; request unchanged |
| Review: safety list (backup first, no reboot, self-undo, skipped untouched) | the confirmation sentence and the loading sentence | shorter, same facts |
| Row `View` (a state's files, topology and map included) | All versions **View files**; **View** on a `View only` row; **View its topology** | |
| Row `Compare with my latest save` | All versions **See what's different** (saved against saved) | drawer designer; distinct from the confirmation's saved-against-running view |
| Version view `Download (ZIP)` | All versions **Download ZIP** | drawer designer |
| New | **Undo this load**, **Try <device> again**, coverage on the row, topology line | D7, 5.4 |

Nothing is dropped. One behaviour changes by decision: the acknowledgement tick box (D4).

---

## 10. Wording

Final strings. "state" wherever the prompt says state; "version" only in **All versions**.

| Where | String |
|---|---|
| Header button | `Load` |
| Group headings | `Your saves`, `Lab states` |
| Row, right side | relative time (own saves); `4 devices`, `2 of 4 devices` (lab states); `View only` |
| View-only reason | `Saved without the files needed to load it` |
| Unreadable manifest | `View only` / `Its save details cannot be read` |
| Overflow | `N more in All versions` |
| Foot | `All versions`, `Browse the repository…` |
| Row action elsewhere | `Load this state…` |
| No own saves | `This lab has no saves of its own yet. You can start from one of these.` |
| Nothing at all | `Nothing is saved in this repository yet. Save this lab, or ask your instructor for the course's lab states.` |
| List cannot be read | `The saved states could not be read from the lab VM.` + the manager's sentence + `Try again` |
| Not running | `Start the lab to load a state` / `Loading puts a saved configuration onto running devices. This lab is not running.` / `Start lab` |
| Busy (disabled Load) | `A save is running.` / `A load is running.` / `The lab is busy: <operation label>.` |
| Preflight running | `Checking <name> against your devices…` |
| Preflight refused | `<Name> cannot be loaded right now.` + the manager's sentence + `Back` |
| Confirmation | `Load <name>?` / `The running configuration of the ticked devices is replaced. The current one is backed up first; nothing reboots.` |
| Subset | `This state covers 2 of your 4 devices. The others are left as they are.` |
| Topology | `Saved on a different topology: 3 of 4 devices match.` / `View its topology` |
| Row texts | `5 lines differ`, `1 line differs`, `Already matches`, `Ready to load`, `Not in this state`, `Not in this lab`, `Not reachable`, `Blocked`, `Can't load` |
| Nothing ticked | `Tick at least one device.` |
| Nothing loadable | `None of the devices can be loaded right now.` |
| Options | `Options` / `Undo automatically if a device cannot be reached again within (minutes)` |
| Confirmation actions | `Load`, `Cancel`, `See what's different` |
| Differences drawer | `What's different` / `<name> compared with what the devices run now` / `Load`, `Back` |
| Loading | `Loading <name>…` / `Each device checks the new configuration itself and undoes it if it loses contact. You can keep working.` |
| Loading rows | `Waiting`, `Backing up…`, `Loading…`, `Checking…` |
| Chip | `Loading… 2 of 4`, `Checking devices…`, `Running <name>`, `Loaded 3 of 4` |
| All loaded | `Running <name>` / `Loaded <when> on all 4 devices.` / `Your latest save: <name>, <when>` / `Before loading: backed up automatically` |
| Toast | `<Name> loaded on 4 devices.` (`on 1 device.`) |
| Partial headline | `Loaded on 3 of 4 devices` |
| Partial sentence, by the worst remaining outcome | `failed`: `xrv9k was not changed.` · `rolled_back`: `xrv9k undid the change and runs its previous configuration again.` · `uncertain` / `interrupted` / `rollback_expected`: `The manager could not confirm what xrv9k runs. Open Details before relying on it.` · unverified only: `xrv9k was loaded, but the check afterwards did not confirm it. Open Details.` · several devices: `2 devices were not changed.` and so on, one clause per kind, uncertain first |
| Result rows | section 5.1 |
| Result actions | `Try xrv9k again`, `Try 2 devices again`, `Undo this load`, `What changed`, `Details` |
| Nothing changed | `<Name> was not loaded` / `No device was changed.` |
| Retry note | `Only the devices that were not loaded are listed.` |
| Undo confirmation | `Undo loading <name>?` / the confirmation sentence / `This undoes the load on the 3 devices it changed. The others are left as they are.` |
| Undo unavailable | `The automatic backup of this load is no longer kept.` · `The automatic backup of this load is incomplete, so it cannot be undone in one step.` |
| Name of an undo | `the configuration from before <name>` |
| Live region | the chip text on every state change, and the toast |

Rewordings of existing strings (each is pinned by a test that is rewritten, not deleted):

- `restoreReasons` (`restore.js:40-51`): "This saved version was made before…" → `This state was saved
  before this kind of device could be loaded. Save the lab again to get a loadable state.`; "cannot be
  updated this way yet" → `This kind of device cannot be loaded yet.`; the credentials and refresh
  sentences keep their action hints.
- Banner and status: `Replacing configuration…` → `Loading a saved state…` (`app.js:96`, `app.js:222`),
  `Replacing configuration` → `Loading a saved state` (`status.js:79`, `status.js:95`),
  `STATUS_RESTORE_ATTENTION_DETAIL` (`status.js:19`) → `The load needs a check on some devices.` /
  `The load finished on some devices only.`
- Job window: titles and step labels stay (`restore.js:16-28`, `restore.js:55-71`,
  `restore.js:130-138`). It is the technical view, and its vocabulary is the service's. Only the two
  closing sentences that name `Advanced › Action logs` and the lab header stay true and are kept
  (`restore.js:391-392`).
- `git-progress.js:746` and `git-progress.js:727`: "Apply to running lab…" → `Load this state…`.

---

## 11. File plan

### 11.1 Scripts

| File | Change |
|---|---|
| `app/static/status.js` | Add pure functions `loadState(lab, ctx, now)`, `loadSourceName(source, ctx)`, `loadDeviceWord(target, job)` (returns `{text, cls, final, help}`), `loadCounts(job)`, the table `STATUS_LOAD_WORDS`, and the changed `savedVersionName`. No DOM. Reword the three restore strings above. |
| `app/static/restore.js` | Keep: constants, `restoreRequestId`, `restoreReasonLabel`, `restoreNotChangedReason`, `restorePlatformLabel`, `restoreTargetOutcome`, `restoreDiffDetails`, the whole job window. `restoreFromVersion` and `restoreFromFolder` keep their signatures and path rules and call `loadChoose`. `restoreReview` (the dialog with the tick box) is replaced by the panel confirmation; its name stays as an alias of `loadChoose` so other scripts and tools that call it keep working. |
| `app/static/load.js` (new; needs `?v=<release>` in `index.html`, lead) | `loadOpen(labId)`, `loadListMarkup(model)`, `loadChoose(labId, source, name, options)`, `loadConfirmMarkup(review)`, `loadSubmit()`, `loadJobMarkup(job)`, `loadRetry(job)`, `loadUndo(job)`, `loadWatch(job)`, `loadFetchStates(labId)`; module state `loadReview`, `loadStates` (per lab, with `head`), `loadSeenActive`. No `window`, `document` or storage listeners: opening, closing, Escape, outside click and focus return use the header panel mechanics the header designer builds in `shell.js`. |
| `app/static/git-progress.js` | `gitVersionAction('apply')` and the version view's button call `loadChoose`; `gitRunAction('load')` opens the Load panel; `gitRenderLastRestore` goes with the Progress tab (5.11). `gitVersionGroups` unchanged. |
| `app/static/git-places.js` | apply button label → `Load this state…`; `gitApplySource` unchanged. |
| `app/static/app.js` | banner wording; nothing else. |
| `app/static/index.html`, `style.css` | header markup and the shared classes: header designer and lead. |

Entry points offered to the other slices: `loadOpen`, `loadChoose`, `loadUndo`, `loadRetry`,
`loadJobMarkup`, `loadState`, and `restoreShowJob` (unchanged).

### 11.2 Markup

Shared base names as assigned: `save-chip`, `save-panel`, `save-dot`, `save-list`, `save-devices`.
Assumed shared with the header designer (same roles as the mockup's placeholders): `save-state`
(headline, was `rx-state`), `save-sub` (`rx-sub`), `save-actions` (`rx-row`), `save-quiet`
(`rx-quiet`), `save-group` (`rx-h`), `save-foot` (`rx-foot`), `save-kv` (`rx-kv`), `save-note`
(`rx-note`), dot modifiers `warn`, `bad`, `none`, `busy`, `info`. Added by this slice: `save-item`
(`rx-ver`), `save-item-when` (`rx-when`), `save-item-why` (`rx-why`), `save-device-end` (`rx-end`, with
`ok`, `bad`, `warn`, `now`), `save-device-help`, `save-options`, the state classes `is-off` (`rx-off`)
and `wide` (`rx-wide`). None of these exists in `style.css` today (a search for `.save-` finds only
`.git-save-*`). Existing classes used as they are: `button`, `button danger`, `button primary`,
`sr-only`, `caption`, `form-error`.

List (G02, G08):

```html
<div class="save-panel wide" id="load-panel" role="dialog" aria-labelledby="load-panel-title">
 <h2 class="sr-only" id="load-panel-title">Load a saved state</h2>
 <h3 class="save-group">Your saves</h3>
 <ul class="save-list">
  <li><button type="button" class="save-item" data-load-row="0"><span>NAME</span><span class="save-item-when">21 minutes ago</span></button></li>
 </ul>
 <h3 class="save-group">Lab states</h3>
 <ul class="save-list">
  <li><button type="button" class="save-item" data-load-row="3"><span>Final</span><span class="save-item-when">2 of 4 devices</span></button></li>
  <li class="is-off"><div class="save-item"><span>Start<span class="save-item-why">Saved without the files needed to load it</span></span><span class="save-item-when">View only</span></div><button type="button" class="save-quiet" data-load-view="5">View</button></li>
 </ul>
 <div class="save-foot"><button type="button" class="save-quiet" data-load-action="all">All versions</button><button type="button" class="save-quiet" data-load-action="browse">Browse the repository…</button></div>
</div>
```

A `View only` row is text plus a **View** button, not a disabled button: its reason is readable by
keyboard and screen reader, and the one thing that can be done with it is beside it.

Confirmation (G03, G07):

```html
<p class="save-state"><span class="save-dot warn"></span>Load NAME?</p>
<p class="save-sub">The running configuration of the ticked devices is replaced. The current one is backed up first; nothing reboots.</p>
<ul class="save-devices">
 <li><label><input type="checkbox" name="load-node" value="NODE" checked><span>ceos <small>EOS</small></span></label><span class="save-device-end">5 lines differ</span></li>
 <li class="is-off"><label><input type="checkbox" name="load-node" value="NODE" disabled><span>xrv9k <small>IOS XR</small><span class="save-device-help">The device did not answer over SSH.</span></span></label><span class="save-device-end">Not reachable</span></li>
</ul>
<details class="save-options"><summary>Options</summary><label for="load-minutes">Undo automatically if a device cannot be reached again within (minutes)</label><input id="load-minutes" type="number" min="2" max="60" value="5"></details>
<p class="form-error" role="alert"></p>
<div class="save-actions"><button type="button" class="button danger" id="load-run">Load</button><button type="button" class="save-quiet" data-load-action="cancel">Cancel</button><button type="button" class="save-quiet" data-load-action="diff">See what's different</button></div>
```

Loading and results (G04, G05, G06) use `save-state`, `save-sub`, `save-devices` rows without inputs
(`<li><span>ceos <small>EOS</small></span><span class="save-device-end ok">Loaded</span></li>`),
`save-kv` lines and a `save-actions` or `save-foot` row. Every value goes through `esc()`. No inline
style. Tick states are read from the DOM into `loadReview.chosen` on change, so a re-render never
loses them; the confirmation is not re-rendered by the 4 s poll (it shows a finished preflight), the
loading and result views are, through `setMarkup`.

Keyboard and focus: opening the panel focuses its first row; choosing a row moves focus to the
headline (`tabindex="-1"`) when the confirmation appears, so the question is read; **Cancel** returns
focus to the row that was chosen; Escape closes the panel and returns focus to **Load** (header
mechanics). The danger button is never focused automatically. Device rows are plain labels and inputs
in document order. State changes (`Checking…`, `Loading…`, the result headline) are written to the
header's polite live region.

### 11.3 Backend changes and their unit tests

| # | Change | Where | Tests to write |
|---|---|---|---|
| B1 | helper mode `states` (read-only manifest summaries at HEAD) | `app/host_git.py` | `tests/test_host_git.py`: lists every manifest folder with devices and restore flags; an invalid manifest yields `invalid`; never returns file contents; own snapshots survive the cap; mode refused with unknown options as the others are |
| B2 | `GET /api/labs/{lab_id}/restore/states` + `public_state`; the no-device eligibility test shared with `map_targets` | `app/restore.py` | `tests/test_restore.py`: coverage `2 of 4`; `view_only` with reason for a state without artifacts; a platform mismatch is not counted loadable; no SSH connector call is made; 409 without a save location; only the listed keys are exposed; the shared function gives the same verdict as a preflight row for each no-device reason |
| B3 | `source.topology` in the preflight and the job | `app/restore.py` | `differs` true, false and null (backup source, manifest without digest, lab without topology); `matching_devices` from the rows; present in `public_job`; no topology text anywhere in the answer |
| B4 | `captured_snapshot(complete=False)` for a `restore-pre` backup | `app/git_progress.py`, `app/restore.py` | undo of a load whose safety backup failed for one device lists the other devices; the same partial backup is still refused for a Git save and for a backup source that is not `restore-pre`; digest mismatch still refused |
| B5 | protect the newest load's `pre_backup_job_id` from the per-lab trim | `app/runner.py` | the backup survives 300 later jobs of the lab; an older load's backup is still trimmed |
| existing | `acknowledge` stays required; undo is a plain `backup` source | `app/restore.py` | `tests/test_restore.py:607` unchanged; new: a load, then a load of its `pre_backup_job_id`, ends `succeeded` with a new safety backup (the probe of section 6, made permanent) |

No change to `restore_drivers.py`, to any driver, to `_apply_one`, `_settle`, `_record_settled`,
`_verify` or `_finalize`. New test files reach CI only through the explicit list in
`.github/workflows/release-check.yml` (lead).

### 11.4 Node tests to write

`tests/test_load_ui.js` (new) and additions to `tests/test_status_ui.js`, `tests/test_restore_ui.js`:

1. `loadState`: active job → `loading` with `done` equal to the number of final rows; `succeeded`
   newer than the newest save → `running`; `partial` and `needs_attention` → `partial` with
   `loaded` = verified count; a job with only `failed` / `rolled_back` / `ineligible` targets is
   skipped and the previous load decides; a completed save newer than the load (each done status,
   including `unchanged`) → empty key; a `move` or `update` job does not count as a save; `rechecking`
   → `loading`.
2. `STATUS_LOAD_WORDS` covers every key of `restoreOutcomes` and every outcome status named in
   `restore.py`; `Kept previous` is produced for `rolled_back` only; `uncertain`, `interrupted` and
   `rollback_expected` never produce `Loaded` or `Kept previous` and always carry the Details hint.
3. A target `applied` + `checking` is not final and reads `Loading…`.
4. Confirmation markup: each preflight row kind of section 3 gives the stated text and tick box state;
   lab devices without a row read `Not in this state`; a saved device without a lab node reads
   `Not in this lab`; reasons are escaped; nothing ticked disables Load with its text.
5. The submit body: exactly `{request_id, source, node_names, confirm_minutes, acknowledge: true}`;
   a folder source carries the preflight's commit; only the four `Source` keys are sent (rewrite of
   `tests/test_restore_ui.js:54`).
6. Single sender: scanning the page scripts, `acknowledge: true` is sent to a restore route from one
   place, `loadSubmit`, and `loadSubmit` is referenced only by the confirmation's and the drawer's
   Load handlers.
7. `restoreFromFolder` still sends the exact path with one leading slash (keeps
   `tests/test_restore_ui.js:32`).
8. `loadRetry`: source rebuilt from a job's `source` for each type with only the model's keys;
   devices are the `failed`, `rolled_back` and `ineligible` targets; absent when none.
9. `loadUndo`: sends `{type:'backup', backup_job_id}`; unavailable with the right reason when the
   backup is missing from `state.jobs`, when it is partial (until B4), and when the job has no
   `pre_backup_job_id`.
10. `savedVersionName` / lab state names: `start`, `broken`, `final` → `Start`, `Broken`, `Final`;
    mixed-case names unchanged; duplicate names get their parent folder.
11. List markup: `View only` row is not a button, shows its reason and a View button; coverage text
    for full, partial and unknown coverage; the cap and its overflow line.
12. `loadSourceName` for each source type, including an undo and an undo of an undo.
13. Not running: the Start lab panel, no preflight request made.

### 11.5 Fixture and browser pass (lead, QA)

The fixture manager patches `restore._probe` (`docs/redesign/tools/fixture_manager.py:415-419`) and
needs, for this slice: `start`, `broken`, `final`; a state without restore artifacts; a state covering
two of four devices; a state from a different topology; a scripted `states` answer (B1); a probe that
reports one device unreachable and one blocked.

---

## 12. Friction budget

Load a lab state: **Load** (1), the state's row (2), red **Load** (3). Three clicks, nothing typed.
The preflight runs between clicks 2 and 3 and takes as long as the devices take to answer.

Undo: chip (1), **Undo this load** (2), **Load** (3). Retry: chip (1), **Try xrv9k again** (2),
**Load** (3). Leaving a device out adds one click. Looking at the differences adds two (open, Back).

---

## 13. Assumptions

1. The chip panel for *Loading*, *Running* and *Partial* is rendered by this slice's functions inside
   the header designer's panel shell; there is one live region for the header.
2. The All versions drawer and the folder browser call `loadChoose`; they close themselves first
   (a modal drawer makes the header inert, and only one panel or drawer is open at a time).
3. A lab state saved with **Save as a lab state…** is an ordinary snapshot folder with `manifest.json`
   and restore artifacts, so it appears in `Lab states` without special handling.
4. The save job of D9 is recognisable in `git_jobs` (its target), so section 7 can count it as a save.
5. `lab['definition_yaml']` is the right "lab's topology" for B3 (see Q4).
6. Platform short labels stay `restorePlatformLabels` (`restore.js:35-37`); the mockup's `IOS-XR`
   reads `IOS XR` as today.

---

## 14. Open questions for the lead

- **Q1. Helper change for the list (B1).** Coverage and `View only` on the row need manifest contents
  at list time. Accept the read-only `states` mode, or take the tree-only fallback of 2.3, which shows
  file counts instead of `2 of 4 devices`?
- **Q2. Device matching across labs.** A saved device matches a lab device by its full container name
  (`restore.py:534`, `discovery.py:94`). A course state loads on a student's lab only when the lab has
  the same name and prefix as the lab it was saved from (same topology file on another VM: yes; a
  second lab with another name on the same VM: no device matches). Section 9 item 6 of the prompt asks
  for "a state on a second lab with the same topology". Matching by the short node name would be a
  change to which device receives which configuration and needs its own risk review; saved
  configurations also carry the source lab's management settings on some platforms, which the timed
  recovery would catch only after the fact. Not proposed here; decide whether it is in scope.
- **Q3. Lab without a save location.** Git-backed sources need the lab's own binding. Should Load
  work before the first save (reading the default repository), and through which registration?
- **Q4. Topology digest.** Is the manager's `definition_yaml` byte-identical to the VM file a save
  embeds when nothing changed? If not, compare against the embedded topology of the lab's newest
  backup (`jobs[].topology.sha256`) instead.
- **Q5. Undo with an incomplete safety backup (B4)** relaxes `captured_snapshot` for one source kind.
  Accept, or keep Undo disabled in that case?
- **Q6. A load that changed nothing** leaves the chip as it was and relies on the banner and the
  panel. Should the chip show a failed state of its own (the prompt's table has none)?
- **Q7. Job window vocabulary** stays "Replaced and verified" while the panel says "Loaded". Align the
  window's words too, at the cost of rewriting most of `tests/test_restore_ui.js`?
- **Q8. `groups.others`** (another lab's saves) is kept out of the panel. Confirm, given D8 may change
  what "another lab's folder" means.

---

## 15. What a reviewer should attack

1. **The acknowledgement.** That no path reaches `POST …/restore` without the person pressing the red
   button of a confirmation built from a finished preflight: retry, undo, the drawer's Load, a double
   click, a re-render during the click, Enter in the minutes field, a stale `loadReview` from another
   lab after switching labs.
2. **Reviewed bytes are applied bytes.** Folder sources must carry the preflight's commit in the
   submit and in a retry; an undo must name the exact backup job.
3. **Outcome wording.** Every status against section 5.1: `Kept previous` for anything but
   `rolled_back`; `uncertain` or `interrupted` softened anywhere (chip, toast, sentence, name);
   `Loaded` shown before verification; the chip count rounding up; the toast firing for a job that is
   not `succeeded`.
4. **The mandatory backup and Undo.** That Undo never bypasses the new load's own safety backup; that
   B4 cannot let a Git save or a non-`restore-pre` source accept an incomplete capture; that B5 cannot
   pin unbounded records; that Undo is not offered when its backup cannot be read.
5. **Confirmation after management was proven.** Nothing in this slice touches it; check that no
   backend addition (B2, B3) adds a code path into `_apply_one`, `_settle` or a driver, and that
   `restore.py` still names no NOS command.
6. **The list's eligibility preview (B2)** drifting from `map_targets`: a row promising `4 devices`
   that the preflight then refuses, or the reverse.
7. **The helper mode (B1).** Input surface (none beyond the binding), output shape (no file contents,
   no configuration text), cost on a repository with thousands of files, behaviour on a hostile
   `manifest.json`.
8. **The topology line** claiming a difference that is only a byte difference between the VM file and
   the manager's copy (Q4), and "View its topology" ever offering a change to the lab (D10).
9. **Chip timing.** A save that completes while a load's follow-up check is still running; clock
   formats (`finished` strings against Git epoch seconds); a restart read-back job, whose `finished`
   is set at restart (`restore.py:271`), being taken for a finished load.
10. **Disabled states.** Every disabled control (Load while busy, a device row, Undo, a `View only`
    row) shows its reason as text and, where one exists, the action that clears it.
11. **Secrets and logs.** No new field carries configuration text; `source.topology` and the states
    route are counts and booleans; the differences drawer shows only the preflight's already masked
    `diff`.
12. **Cross-lab loads (Q2)** if the lead widens the matching.
