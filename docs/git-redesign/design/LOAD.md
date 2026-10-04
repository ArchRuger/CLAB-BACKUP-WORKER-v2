# Load: "Apply to running lab" inside the header design

Design slice for PROMPT.md section 5.4 (all nine steps and the parity gate), owner decisions D4, D7 and
D10, section 7 items 6 and 7, and the restore rules of section 8. Boards G02 to G09.

Scope: the Load panel, its confirmation, the loading and result views, Undo this load, and the data they
need. Not in scope, named as hand-off points: the chip and its panel shell (header slice), the All
versions and What changed drawers (drawer slice), the folder model and every backend decision (lead).

Revised after the design review. The rulings are in [DESIGN.md](../DESIGN.md) sections 3.7, 3.8, 4, 5
and 7 and the findings in [REVIEW.md](../REVIEW.md); where this file and DESIGN.md disagree, DESIGN.md
wins. Section 14 lists where each of this file's former open questions was decided.

All code paths are under `clab-backup-ui/`. Citations are `path:line` against the branch
`claude/git-save-load-redesign` at commit `a3aacca` (1.30.60 plus the first slices of this work).
The backend slices are being merged while this is written, so the line numbers of `app/git_progress.py`,
`app/runner.py` and `app/host_git.py` move first. Nothing in
this document was run in a browser or against a device. One throwaway unit probe was run against a
temporary data directory (section 6); it is the only executed evidence here.

Rule of this slice: the restore service is not redesigned. `app/restore.py` keeps its flow, its
vocabulary and its refusals; the page changes how they are reached and worded.

---

## 1. Today's map

### 1.1 Every way to reach "Apply to running lab…"

| # | Where | Control | Function chain | Source sent to the restore service |
|---|---|---|---|---|
| E1 | Progress tab, Saved versions rows (Latest, Checkpoints, Baseline, Instructor and reference, Other labs, Elsewhere) | `Apply to running lab…` button per row, `app/static/git-progress.js:372`; delegated click `git-progress.js:792` | `gitVersionAction('apply', row)` `git-progress.js:398-402` → `restoreFromFolder(id, row.apply.path, tree)` `app/static/restore.js:150-160` → `restoreReview` `restore.js:162` | `{type:'folder', path:'/<exact snapshot path>'}`; the submit adds the commit the review read (`restore.js:189`) |
| E2 | Saved-version view dialog (`git-version-dialog`), opened by a row's View, by Full history, by a commit | `Apply to running lab…` (danger), only when `restore_supported`, `git-progress.js:754` | `restoreFromVersion(id, {type:'git', commit, path}, name)` `git-progress.js:761` → `restoreReview` `restore.js:141-143` | `{type:'git', commit, path}` |
| E3 | Folder browser (Save location card), any selected folder that is a snapshot or whose `latest/` child is one | `Apply to running lab…` (danger-outline) `app/static/git-places.js:160`, wired `git-places.js:216` | `options.onApply` given by `git-progress.js:291` → `restoreFromFolder(id, gitApplySource(dir).path, tree)`; the folder-to-snapshot rule is `gitApplySource` `git-places.js:76-81` | `{type:'folder', path}` |
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
`Replacing configuration…` (`app.js:96`), the lab state `Replacing configuration` (`status.js:94`) and
`Checking devices` during a restart read-back (`status.js:93`).

### 1.2 The restore API as it is

Routes (all under the same-origin guard; installed by `RestoreService.install`, `restore.py:1261`):

| Route | Body | Answer |
|---|---|---|
| `GET /api/labs/{lab_id}/restore/sources` | none | `{backups:[{backup_job_id, created, finished, nodes}], supported_nodes, unsupported_nodes, restore_supported_platforms}` `restore.py:1282-1300` |
| `POST /api/labs/{lab_id}/restore/preflight` | `{source, node_names?}` (`Preflight`, `restore.py:1269-1272`) | `{source, targets, eligible_count}` `restore.py:613-614` |
| `POST /api/labs/{lab_id}/restore` | `{request_id (32 hex), source, node_names (1..500), confirm_minutes (2..60, default 5), acknowledge}` (`Run`, `restore.py:1274-1280`) | the public job |
| `GET /api/restore/jobs/{job_id}` | none | the public job `restore.py:1313-1316` |

`Source` is `{type, commit, path, backup_job_id}` with `extra='forbid'` (`restore.py:1262-1267`): a page
must send exactly these keys, never the richer `source` object a preflight or a job returns. (The
design adds a fifth key, `repository`: 2.3.)

Source types (`resolve_source`, `restore.py:438-525`):

- `git` (`restore.py:442-454`): `commit` + `path`, read with the helper's `read-version` through the
  lab's own binding; `path` goes through `resolve_version_path` (`app/git_progress.py:190-204`).
- `folder` (`restore.py:469-504`): any snapshot folder of the connected repository, `path` exact with
  one leading slash (`/` is the root). Without `commit` the preflight reads HEAD and returns it as
  `source.commit`; a submit that carries `commit` reads exactly that commit (`restore.py:482-493`), so
  the reviewed bytes are the applied bytes. A malformed commit is 400 (`restore.py:483-484`).
- `backup` (`restore.py:455-468`): a backup job of this lab by `backup_job_id`, read with
  `captured_snapshot(..., embedded_files=False)`. 404 when the job is not in `state['jobs']` for this lab.
- anything else: 400 (`restore.py:506`).

Both Git-backed types call `self.git.binding(lab_id)` (`restore.py:444`, `restore.py:477`), which is 409
`Connect this lab to a Git repository first.` for a lab without a save location
(`git_progress.py:609-613`). The folder need not be registered to any lab; the loading lab must be
connected to the repository. (The design removes that condition: 2.3 and section 8.)

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
| Repository tree | `GET /api/git/repositories/{binding_id}/tree` (`git_progress.py:1243-1252`) → helper mode `browse` (`app/host_git.py:793-811`): `git ls-tree -r -l` of HEAD, cut at 4000 files (`host_git.py:37`), plus three `git log -1` calls for the lab's own `latest`, `baseline`, `checkpoints` times | One SSH round trip through the gateway under the helper lock (`git_progress.py:587-595`). Not cached by the manager. The page fetches it when the Progress tab is shown for a lab and on a forced refresh (`gitShowRepository`, `git-progress.js:233-242`), and keeps the last one in `gitVersionTree` (`git-progress.js:285`). It is not part of the 4 s poll. |
| Snapshot detection | `gitTreeModel` marks a folder `snapshot` when it holds `manifest.json` among its own files (`git-places.js:64`); a parent whose `latest/` child is a snapshot gets `latestSnapshot` (`git-places.js:66`) | pure, in the browser |
| Your saves: latest | `groups.latest`: `<prefix>/latest` when it has files (`git-progress.js:329-330`); time from `tree.saved.latest`, name from the newest finished save's `note` (`git-progress.js:325-326`) | from the tree and `/api/state` `git_jobs` |
| Your saves: checkpoints | `groups.checkpoints`: each folder under `<prefix>/checkpoints` (`git-progress.js:331-332`); time and note from the matching save job | same |
| Baseline | `groups.baseline` (`git-progress.js:333-334`) | same |
| Lab states | `groups.reference`: every other snapshot folder at or below the lab folder's parent (two levels for a top-level lab folder, `git-progress.js:335-346`, `git-progress.js:357`); `groups.elsewhere`: the rest (`git-progress.js:358`); `groups.others`: snapshots inside another lab's registered folder, named by that lab (`git-progress.js:355-356`) | same |
| Row name | `savedVersionName(folder)` (`status.js:171-177`): last path segment, with `final`/`solution` → `Final state (instructor)`, `start`/`base`/`initial` → `Starting state`, `broken-N` → `Troubleshooting scenario N`; pinned by `tests/test_status_ui.js:176-180` | pure |
| Fallback when the tree is unavailable | `GET /api/labs/{lab_id}/git/history` (`git_progress.py:1573-1581`) → helper `history` (`host_git.py:682-705`): every `manifest.json` folder at HEAD, `connected` for the lab's own; the manager labels each with `version_label` (`git_progress.py:166-176`); rows built at `git-progress.js:360-366` carry no apply | one SSH round trip |

### 2.2 The panel's lists

Both lists come from one request, `GET /api/labs/{lab_id}/restore/states?repository=<id>` (B2 in 2.3):
one row per saved state of the repository, each with `path`, `commit`, `name`, `group`, `lab`, `kind`,
`saved_at`, `devices`, `loadable`, `view_only` and `view_only_reason`. The page no longer builds the
groups from the tree; `gitVersionGroups` stays for the pages that still call it.

| Row `group` | In the Load panel | Elsewhere |
|---|---|---|
| `latest` | `Your saves`, first row | All versions |
| `checkpoint` | `Your saves`: the three newest by `saved_at` | All versions (all of them) |
| `state` | `Lab states`, in the order the route returns them, capped at eight; when more exist the group ends with `N more in All versions` | All versions |
| `baseline` | not in the panel | All versions, `Starting point` |
| `other-lab` | not in the panel (DESIGN.md 3.7 Q8) | All versions, folded |

"Another lab's" means inside the saved-state folders of a lab that is connected now; every other saved
state is a lab state (DESIGN.md 3.7 Q8). Every group stays reachable through **All versions** and
**Browse the repository…**.

Naming. The panel shows the row's `name`. The rule lives in the states route (DESIGN.md 3.8, drawers
N3): the last folder name once a trailing `latest` is dropped, its first letter upper-cased when the
name is all lower case (`start` → `Start`, `broken-2` → `Broken-2`, `BGP` → `BGP`); two equal names each
add their parent (`Start · BGP`). `savedVersionName` in `status.js` follows the same rule for a page
without the list (status slice); its three special cases go away and `tests/test_status_ui.js:176-180`
is rewritten to the new names, not deleted. One exception, made in the page: the lab's own `latest` row
is named by the save in `git_jobs` whose `commit` equals the row's `commit` (its `note`), and reads
`Your latest save` when the manager no longer holds that save. The exact path stays visible in All
versions. `version_label` (`git_progress.py:166-176`) is unchanged; it labels history rows only.

The source a row sends is `{type: 'folder', path: row.path, commit: row.commit, repository}`: the
row's own commit, so the bytes that are checked and loaded are the state as listed, and the loaded
commit is the commit of the save that wrote it (the name rule of 5.2 depends on this; assumption 13.7).

Refresh. The list is fetched when the Load panel opens and after a save of this lab finishes or
**Update from the repository** ran; never on the 4 s poll (each fetch is an SSH call that takes the
helper lock; the manager caches the helper's answer per checkout and HEAD, DESIGN.md H3). The panel
renders the previous answer at once when it has one for this lab and repository and replaces it
through `setMarkup` when the new answer arrives.

### 2.3 What was missing, and what was decided

**M1. Device coverage on the row (`2 of 4 devices`).** The tree lists file names, not manifests. File
names are `<short label>.<suffix>` and get a hash on collision (`git_progress.py:408-421`), so they do
not identify lab devices. Before this work the coverage is known only after `read-version`, which
returns every file of one snapshot (`host_git.py:715-745`).

**M2. `View only` with its reason.** The old list offers Apply for every `manifest.json` folder
(`git-progress.js:348`); the lack of restore artifacts shows only after the preflight, as every device
skipped (`NO_ARTIFACT`, pinned by `tests/test_restore.py:571`), or in the version view as
`restore_supported: false` (`git_progress.py:1591-1594`).

**M3. Topology comparison.** The manifest carries `topology_digest`, `topology_provenance` and, for
saves since 1.30.57, a `kind: 'topology'` file entry (`git_progress.py:442-472`). Nothing compared them
with the lab.

The decisions (DESIGN.md 3.7; none adds a NOS command, none touches the transaction):

**B1. The helper's `history` mode returns `head` and a bounded `summary` per saved state** (DESIGN.md
H3; owned by the helper slice, not by this one). No mode named `states` is added, so the option
whitelist and the gateway's command list do not change. Each row of `versions` gains `summary`:
`lab_id`, `lab_name`, `captured_at`, `kind`, `topology_digest` and, per device entry, `node`,
`short_name`, `platform` and whether it has a restore artifact; never file contents. Bounds (review
F10): sizes come from `ls-tree -l`; a manifest over 256 KiB is never read; the others are read in one
`git show`, 4 MiB in total, the lab's own states first; every field is type-checked, strings are cut at
200 characters and hold no control character, at most 500 devices; on any deviation the row's `summary`
is `null`. The manager caches the answer per checkout and HEAD. This is a `host_*.py` change: security
review, helper version lockstep and `--refresh` apply.

**B2. Manager route `GET /api/labs/{lab_id}/restore/states?repository=<id>`, in
`RestoreService.install`.** It lives in `restore.py` because coverage is the no-device half of
`map_targets` and needs `restore_drivers.for_platform` (`git_progress.py` cannot import `restore.py`;
`restore.py` already imports from it, `restore.py:40`). It is built on the seam
`self.git.states(lab_id, repository)` (DESIGN.md section 5), which returns `{head, truncated, states}`
with one row per saved state: `path`, `commit`, `name`, `group` (`latest`, `checkpoint`, `baseline`,
`state`, `other-lab`), `lab`, `kind`, `summary`, `saved_at`. The route adds the coverage and answers
through a new `public_state(row)` function that copies only these keys (`summary` stays inside):

```
{head, truncated,
 states: [{path, commit, name, group, lab, kind, saved_at,
           devices, loadable,
           view_only: bool, view_only_reason: 'no_restore_data' | 'unreadable' | ''}]}
```

- `devices`: the number of saved devices in the summary.
- `loadable`: saved devices that match a lab node by full node name (DESIGN.md 3.7 Q2) with the same
  platform, have a driver and carry a restore artifact. These are the first four tests of `map_targets`
  (`restore.py:538-545`); they are factored into one module function used by both, so the list and the
  preflight cannot disagree. No device is contacted.
- `view_only`: no saved device carries a restore artifact (`no_restore_data`), or the row's `summary`
  is `null` (`unreadable`); `devices` and `loadable` are then `null` for an unreadable row.
- Without `repository` the lab's own binding is read; a lab without one answers 409, as
  `self.git.reader` does (`git_progress.py:615-632`), and the page asks with the default repository
  of DESIGN.md 2.8 instead (section 8).

`restore.py` gains no NOS knowledge: it reads manifest metadata and asks the driver registry whether a
kind is supported, as `sources` already does (`restore.py:1291-1292`). The panel needs this one round
trip; the name of the lab's own latest save still comes from `git_jobs` (2.2). The number after "of" in
`2 of 4 devices` is counted in the page: the lab's devices whose kind has a restore format
(`state.platforms[*].restore_suffix`, `app/inventory.py:17-30`), the same set the confirmation uses for
its `Not in this state` rows.

**A source may carry `repository`** (DESIGN.md 3.7 Q3). `Source` (`restore.py:1262-1267`) gains the
optional key `repository`, a registration id of this VM; the model keeps `extra='forbid'`, so a source
has five keys. In `resolve_source` the two Git-backed types read through
`self.git.reader(lab_id, source.repository)` instead of `self.git.binding(lab_id)`
(`restore.py:444`, `restore.py:477`): the lab's own binding when `repository` is empty or names it, else
that registration once the helper's own `list` names it (404 otherwise). Read through a registration
that is not the lab's own, a `folder` source without a commit takes HEAD from the `history` answer
(`head`), never from `status`, because `status` also checks that registration's own folders (review
F17); the lab's own binding keeps today's path (`restore.py:489-492`). The stored description (`desc`,
shown as the job's `source`) records `repository` so that a retry reads the same place. So a lab
without a save location loads before its first save.

**B3. Topology comparison in the source description, by structure** (DESIGN.md 3.7 Q4). In the
preflight, after the manifest is read, `desc` (which the preflight returns and the job stores as
`source`, exposed by `public_job`) gains:

```
topology: {differs: true|false|null, saved_devices: n, matching_devices: m}
```

`differs` compares the node names with their kinds and the link endpoints of the state's embedded
topology file (the manifest entry of `kind: 'topology'`, `git_progress.py:464-467`) with the lab's
topology (`definition_yaml`), both parsed in the preflight with the parser the manager already has
(`parse_definition`, `app/discovery.py:54`). Bytes and digests are not compared, so a difference in
comments, order or line endings between the VM's file and the manager's copy is not a difference.
`differs` is `null` when either side is missing or unreadable (a backup source, which is read without
embedded files, `restore.py:462`; a state saved before topologies were embedded; a lab without a
topology text; a file that does not parse), and no line is shown then. `matching_devices` is computed
from the rows: saved devices whose row has a lab node of that name and the same platform. Counts and
booleans only; no topology text in the answer. For **View its topology** the page opens the state's
files (All versions **View files**, drawer slice) at the topology file, which every manifest-listed
file view already includes (`git_progress.py:499-503`, `git_progress.py:1591-1593`).

---

## 3. The confirmation (G03, G07)

### 3.1 The review object and its life (review L1)

One module object in `load.js` holds a review:

```
loadReview = {labId, source, name, saved, review, chosen, minutes, requestId, retry, drawer}
```

- **The Load button always opens on the list.** `loadOpen(labId)` runs on the panel's `panelopen`
  event (section 11.2), drops any review and renders the list. A confirmation is never what a click
  on **Load** shows.
- **A review starts only with `loadChoose(labId, source, name, options)`**: a row of the list, **Load
  this state…** in a drawer or the folder browser, **Undo this load**, **Try … again**, **Load this
  backup…**. It opens the Load panel when it is closed, replaces any earlier review and runs a new
  preflight. It does nothing while a load of the lab runs (section 4).
- **The review is cleared** when the Load panel closes (its `panelclose` event: Escape, an outside
  click, Tab leaving it, another menu or panel opening) and when the lab on screen changes
  (`selectLab()` and `goHome()` close the panel through `closeMenus()`, and every render compares
  `loadReview.labId` with `activeId` and drops a review of another lab). One exception: the
  differences drawer (3.4) holds the review while it is open (`drawer: true`), because opening a drawer
  closes the panel; closing the drawer by anything but **Back** clears it.
- **`loadSubmit()` does nothing unless** `loadReview` exists, its `labId` equals `activeId`, its
  `review` is a finished preflight and at least one device is ticked. A preflight answer that arrives
  for a review that was cleared or replaced meanwhile is dropped (each review carries its own
  `requestId`, compared when the answer arrives).

### 3.2 The rows

`loadChoose` shows `Checking <name> against your devices…` (busy dot) while
`POST …/restore/preflight` runs with `{source}` (no `node_names`, so every saved device is probed, as
today, `restore.js:166`). Then:

Headline `Load <name>?`, the sentence `The running configuration of the ticked devices is replaced.
The current one is backed up first; nothing reboots.`, under it `Saved <when>.` (review F9: the
relative time of `source.captured_at`; the pinned commit stays in the differences drawer's meta line),
and one row per device. The row set is the preflight's `targets` plus, for G07, every lab device with
a restore format that has no row (derived in the page from the lab's nodes and `state.platforms`; the
preflight returns rows for saved devices only, `restore.py:532`).

| Preflight row | Tick box | Right-hand text | Row class |
|---|---|---|---|
| `eligible`, `matches_saved` true | real input, ticked | `Already matches` | |
| `eligible`, `pending_changes` = n > 0 | ticked | `n lines differ` (`1 line differs`) | |
| `eligible`, no comparison (`matches_saved` absent) | ticked | `Ready to load` | |
| `reachable: false` (`SSH probe failed…`) | disabled, unticked | `Not reachable` and, under the name, `The device did not answer over SSH.` | `off` |
| `reachable: true`, not eligible (pending change, editor, rejected login) | disabled, unticked | `Blocked` and, under the name, the mapped reason | `off` |
| not eligible without a probe (not running, stale discovery, no credentials, platform differs, unsupported platform, no restore data, unusable data) | disabled, unticked | `Can't load` and the mapped reason | `off` |
| saved device with no lab node (`No running node in this lab matches…`) | disabled, unticked | `Not in this lab` | `off` |
| lab device with no row (page-derived) | disabled, unticked | `Not in this state` | `off` |

- `n` is `pending_changes`, the driver comparison's count (`restore.py:602-603`), the number today's
  dialog shows (`restore.js:178-179`). It is consistent with `matches_saved` by construction.
- Reasons go through today's `restoreReasonLabel` table (`restore.js:40-51`, `restore.js:100-104`),
  reworded where it says "saved version" (section 10). A reason is visible text under the device name,
  never a tooltip only. Where an action clears it, the reason ends in a link button for that action
  (review D3: `Add login credentials for this device first.` with **Credentials…**, which closes the
  panel and opens Advanced › Credentials); where none exists the sentence stands alone.
- A disabled tick box cannot be ticked, and the submit sends only ticked names; the server would
  refuse an ineligible name anyway (`restore.py:681-684`).
- Leaving a device out is unticking it. With nothing ticked, **Load** is disabled and the line
  `Tick at least one device.` shows beside it.
- When no row is eligible: **Load** is disabled, the headline stays, and the sentence is replaced by
  `None of the devices can be loaded right now.`; each row still shows its reason.
- Subset (G07): the sentence gains `This state covers 2 of your 4 devices. The others are left as
  they are.` when at least one lab device has no row.
- **A retry** (`loadRetry`, 5.3; review L2) renders only the devices it asked about: the preflight
  rows with `requested` true. No page-derived row, no row of a device that was not asked for, and no
  subset sentence; the line `Only the devices that were not loaded are listed.` stands in its place.
- Topology line (B3), only when `source.topology.differs` is true: `Saved on a different topology: 3
  of 4 devices match.` with the quiet button **View its topology**. Load changes device configurations
  only (D10); the line never offers to change the topology.
- Folded `Options` (parity with today's Advanced options, `restore.js:203-206`):
  `Undo automatically if a device cannot be reached again within [5] minutes` (number input, 2 to 60).
  The sentence `Each device checks the new configuration itself and undoes it if it loses contact.`
  stays visible above it.

Actions: **Load** (`button danger`), **Cancel** (back to the list; nothing was sent; the review is
dropped), **See what's different**.

While a save of the lab runs (chip *Saving*, DESIGN.md 7.1 row 2) the red **Load** is disabled with
the visible line `A save is running.` and becomes available again when the save ends; the ticks are
kept. Any other hold (a backup, a lab operation, another lab's load) is answered by the server's own
409 on the submit (`guard_idle`, `restore.py:428-434`), shown in the confirmation's error line; the
confirmation stays, so nothing has to be chosen again.

### 3.3 The red Load button is the acknowledgement (D4)

There is no tick box. `loadSubmit()` is the one function that posts to `/labs/{id}/restore`, and its
body is built in one place:

```
{request_id, source: submitSource, node_names: <ticked>, confirm_minutes, acknowledge: true}
```

- `request_id` is made once per review (`restoreRequestId`, `restore.js:74-77`), so a double click or
  a retry after a lost answer returns the same job (`restore.py:668-670`).
- **A source carries five keys** (review L3): `type`, `commit`, `path`, `backup_job_id`, `repository`.
  One function, `loadSource(source)`, builds every source the page sends, to the preflight and to the
  submit, with exactly these keys (an unused one is the empty string), never the richer `source`
  object a preflight or a job returns. `repository` is empty for the lab's own save location and is
  the registration id for a lab without one or for another repository of the VM (2.3).
- `submitSource` keeps today's rule (`restore.js:189`): a folder source carries the commit the
  preflight returned (which is the row's own commit when the row sent one, 2.2); `git` and `backup`
  sources are sent as chosen.
- `loadSubmit` is reachable only from the click handler of the danger button of a rendered
  confirmation (panel or the differences drawer below). `restoreFromVersion`, `restoreFromFolder`,
  `loadChoose`, `loadUndo` and `loadRetry` all end in the confirmation, never in `loadSubmit`.
- The server rule is unchanged: without `acknowledge: true` the route answers 400
  (`restore.py:1309-1310`).
- Node test (section 11): the string `acknowledge` followed by `true` occurs exactly once in the
  page scripts in a request to a `/restore` route, inside `loadSubmit`. (`git-progress.js:700` sends
  `{acknowledge:true}` to the Git dismiss route; that is a different route and stays.)
- After a successful submit `loadSubmit` drops the review, closes the Load panel (or the drawer) and
  opens the chip panel (`saveOpenPanel('status')`), which shows the loading view of section 4.

### 3.4 See what's different

It opens today's review differences: for every ticked row that differs, `restoreDiffDetails(r)`
(`restore.js:337-347`), which renders the preflight's masked `diff` through `diffMarkup`
(`app/static/diff-view.js:27`), saved against running now. No new request. It is the drawer kind
`different` of `saveDrawerOpen` (drawer slice: the shell, the close and the focus return); this slice
supplies its body as `loadDifferentMarkup(review)`, in the visual language of What changed (F04),
headed `What's different` with the meta line `<name> compared with what the devices run now · saved
<when> · <commit, 10 characters>`.

The drawer shows no tick boxes. Its danger button therefore says what it will do (review L4):
**Load on 3 devices** (`Load on 1 device`), the number of devices ticked in the confirmation; it calls
the same `loadSubmit()`. With nothing ticked it is disabled with `Tick at least one device.`; during a
save it is disabled with `A save is running.` **Back** closes the drawer and shows the panel in the
same confirmation, with the same ticks and the same `requestId` (the one way a confirmation appears
without a new preflight, and only for the review the drawer was holding, of the lab on screen).
Closing the drawer any other way drops the review.

---

## 4. Loading (G04)

After a successful submit the chip panel shows the job (3.3). Headline `Loading <name>…` (busy dot), sentence
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
sentence. The loading view lives in one place, the chip panel: the header slice's `savePanelView`
calls `loadChipView(cs, lab)` for the states *Loading*, *Running* and *Partial*, which returns
`{title, dot, key, html}` with `html` built by `loadJobMarkup(job)`. After the red **Load** the Load
panel closes and the chip panel opens by itself with this view (3.3). An open view polls
`GET /api/restore/jobs/{id}` every 1.5 s, as `restoreStartWatch` does (`restore.js:401-415`), and
re-renders through the header's keyed rebuild; the chip itself follows the 4 s `/api/state` poll. A
poll that fails shows `Status updates paused.` with **Refresh**, as today (`restore.js:388-389`).

Disabled controls (DESIGN.md 7.1, last paragraph; review D1):

| Control | Disabled when | Visible reason |
|---|---|---|
| **Load** (header button) | only while a load of this lab runs (chip *Loading*) | the chip beside it: `Loading… 2 of 4` or `Checking devices…` |
| **Save** | header slice: while a load or a save runs, and for the other causes of DESIGN.md 7.1 | header slice |
| red **Load** of a confirmation, and the drawer's **Load on n devices** | while a save of this lab runs (chip *Saving*) | `A save is running.` beside the button |
| red **Load** | nothing ticked | `Tick at least one device.` |

The Load button is not disabled during a save, a backup or a lab operation: the panel opens and the
states can be looked at. A row chosen while a save of the lab runs sends no preflight (the server
would refuse it, `guard_idle`, `restore.py:428-434`); the panel shows `<Name> cannot be loaded right
now.` / `A save is running.` with **Try again** and **Back**. A preflight the server refuses for any
other hold shows the same view with the manager's sentence. The server refuses a submit during any
hold as well (`operation_busy`, `lab_operations.py:58-75`), so none of these rules is the only guard.

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
| `uncertain` | `Not confirmed` and, under the name, `The manager could not confirm what this device runs. Open Details.` (review O3: the device may have been read and match neither configuration, so "could not check" would be untrue) | `warn` | `restore.py:1118-1122`, `restore.py:884-887` |
| `interrupted` (finished job) | `Interrupted` and `Open Details.` | `warn` | a restart before or during the change |
| `rollback_expected` (jobs before 1.30.27) | `Not confirmed` and `Open Details.` | `warn` | the manager had not read the device back |

`Kept previous` appears for `rolled_back` and for nothing else. In particular a `failed` device whose
message says the previous configuration was checked (`restore.py:1113-1115`) reads `Not loaded` with
that sentence as its reason, because the service did not call it a rollback. G06's mockup shows
`Kept previous` for a device that "did not accept" the state; under the prompt's rule that device is
`failed` and reads `Not loaded` with the driver's reason. The headline sentence differs accordingly
(section 10).

### 5.2 Chip state after a load

`loadState(lab, ctx, now)` is the one function of DESIGN.md 7.1. It lives in `status.js` beside
`progressState` (`status.js:139`), is owned by the status slice, and is called by `saveChipState`;
nothing else decides a load state, a count or a name. This section restates 7.1 for the load rows with
the fields each term is read from; where the two differ, DESIGN.md 7.1 wins.

Definitions, over `/api/state`:

- `replaced(t)`: `t.status` in `verified, applied, applied_unverified, verify_mismatch` (today's
  `restoreReplacedTarget`, `restore.js:31`).
- `unknown(t)`: only when the target's stage is `uncertain` (the service writes status and stage
  `uncertain` together, `restore.py:1166`), or the target still awaits its read-back: status
  `interrupted` with a timeline that has no `settled` entry (the target test of
  `restoreTargetRechecking`, `restore.js:15`). A device interrupted before it was changed is not
  unknown: the restart gives it the final stage `failed`, so its timeline is settled
  (`restore.py:279-281`). Its row still reads `Interrupted` (5.1); it only does not make a load
  effective (review O2: no `Loaded 0 of 4`, no Undo for a load that changed nothing).
- An **effective load** is a finished restore job of this lab (not `statusRestoreActive`,
  `status.js:31`) with at least one target that is `replaced` or `unknown`. A job that changed nothing
  (every target `failed`, `ineligible`, `rolled_back` or interrupted before the change; job status
  `failed` or `preflight_failed`) is not an effective load: the devices run what they ran before, so
  the chip keeps what it showed (DESIGN.md 3.7 Q6). Its failure is still surfaced by the lab banner
  (`labFailure`, `status.js:79`) and by the panel (5.3).
- `L` is the newest effective load by `finished`. A later load that was not effective does not
  replace it (review K1: load A succeeds, load B changes nothing, the chip still reads `Running A`).
- **What ends `L` besides a save** (review K6): a finished deploy, redeploy or destroy of the lab, or
  a finished design apply of the lab, that is newer than `L`. They are read from `operations[]` (an
  entry with this `lab_id`, `action` in `deploy`, `redeploy`, `destroy` and `finished` set;
  `lab_operations.py:644-645`, finished at `lab_operations.py:915` and `lab_operations.py:921-922`;
  served at `main.py:227`) and from `design_jobs[]` (an entry with this `lab_id` and `finished` set
  that is no longer busy or read back; `design_apply.py:49-51`, finished at `design_apply.py:925`;
  served at `main.py:226`). `finished` is compared with `L.finished` through `statusEpoch`
  (`status.js:41`). The outcome of the operation is not asked: a redeploy that failed half way has
  changed what the devices run as well, and `Running <name>` would then be a guess.
- `S` is the newest **capture save**: a job in `git_jobs` of this lab that read the devices itself
  (public job field `captured`, section 7), whose `kind` is neither `state` nor `design`, finished as
  `synced`, `unchanged`, `committed`, `review_pending` or `push_pending`. A checkpoint or a starting
  point made from an existing capture reads no device and is not one. A failed attempt ends nothing
  (review K2): it is the chip's *Can't save* in front of the load (row 3 of 7.1), and the load stays
  reachable through that panel's *Also* line, with Undo.

The rows of 7.1 that this function decides:

| Row of 7.1 | Chip | Condition | Text |
|---|---|---|---|
| 1 | *Loading* | a restore job of this lab is active (busy status, or `interrupted` with `rechecking`) | `Loading… k of m` (section 4); during a restart read-back `Checking devices…` |
| 4 | *Partial* | `L` exists, nothing of the list above ended it, it is newer than `S`, and `L.status !== 'succeeded'` | `Loaded n of m`: `n` = targets with status `verified`, `m` = `targets.length` |
| 5 | *Running* | the same, and `L.status === 'succeeded'` | `Running <name>` |
| 3 | *Can't save* (header slice) | a failed save attempt newer than `L` and `S` | the load of row 4 or 5 is its `also` |
| 6 to 11 | save states (header slice) | otherwise | |

`succeeded` means every target is `verified` (`restore.py:1235-1237`); so *Running* is never shown
while any device is unverified, uncertain or unchanged. `Loaded n of m` counts verified devices only
(review O1), the count the service itself reports (`restore.py:1243`, `restore.py:1247`). A job with
four replaced devices of which one is `applied_unverified` therefore reads `Loaded 3 of 4` (amber),
and its row says `Loaded, not verified`: the chip never rounds an unverified device up.

Name in `Running <name>`: `loadSourceName(source, ctx)` in `status.js`, derived, nothing stored on
the job (DESIGN.md 3.8 N2), so a renamed save shows its current name:

- The lab's own `latest`: the name of the save in `git_jobs` whose `commit` is the loaded commit
  (`source.commit`); when no save of the lab has that commit, `an earlier save, <when>` with the
  relative time of `source.captured_at` (review O4: never the newest save's name for an older commit).
- `checkpoints/<x>` of the lab → `x`; the lab's `baseline` → `your starting point`.
- Any other state → its `name` from the states list when the page holds the list, else
  `savedVersionName(folder)`, which follows the same rule.
- `backup`: when the backup job in `state.jobs` has `source === 'restore-pre'` and its `progress_id`
  names a restore job `X` still listed (`runner.py:363-364`, exposed whole by `decorate_job`,
  `app/downloads.py:149-157`, `main.py:222`): `the configuration from before <name of X's source>`.
  When `X`'s own source is such a backup, taken before a load `Y`, the name is the name of `Y`'s source
  (review U3: the undo of an undo of `Y` reads `Y`, not a nested phrase). Otherwise
  `a backup from <time>`.

### 5.3 Result panels

All loaded (G05), chip panel: `Running <name>` / `Loaded <when> on all <m> devices.` /
`Your latest save: <name>, <when>` / `Before loading: backed up automatically` /
**Undo this load**, **What changed**. The second line says `on all <m> devices` only when the load
covered every lab device that has a restore format; for a subset it reads `Loaded <when> on <m>
devices.` (review O5). Toast, once per job, when the page sees the job leave the active set, and only
for a job whose status is `succeeded`: `<Name> loaded on <m> devices.`

Some not changed (G06): headline `Loaded on n of m devices` (`n` verified, as the chip), one summary
sentence (section 10), one row per device with the words of 5.1, then **Try <device> again**
(primary), **Undo this load**, **Details**. No toast.

In both panels the header slice adds its *Also* line for a hidden save state (`Also: 1 save to
upload.` with **Show**, DESIGN.md 3.8).

After the next save the chip leaves these states (section 7) and the load would be out of reach. The
chip panel at rest therefore shows `Last load: <name>, <when>` with **Details** while the manager
holds a finished effective load of the lab (review F4; the line is the header slice's, the data is
`loadState(...).last`). **Details** opens the restore job window, which also carries the way back to
before that load (section 6).

**What changed** and **Details** both open today's restore job window, `restoreShowJob(job.id)`
(`restore.js:350-358`): the per-device step list, the outcome sentences, the masked `diff_sample` is
not shown there today and is not added; the links to the backups taken before and after
(`restore.js:380-387`). The window is unchanged except for the button of section 6 and for wording
that names the removed tab (section 10). It remains the place where `uncertain`, `interrupted` and
`verify_mismatch` are explained in the service's own terms.

**Try <device> again** (`loadRetry(job)`):

- Devices: the targets with status `failed`, `rolled_back` or `ineligible`. The button names one
  device (`Try xrv9k again`) or counts them (`Try 2 devices again`). When there is none (only
  `uncertain`, `interrupted` or unverified devices remain) the button is absent: those devices send
  the person to Details first, and a new load of them starts from Load like any other.
- It rebuilds the source from `job.source` with `loadSource` (five keys): `{type:'folder', path,
  commit, repository}` (the same commit, so the same bytes as the first attempt), `{type:'git',
  commit, path, repository}` or `{type:'backup', backup_job_id}`.
- It calls `loadChoose` with `options.nodes` set to those devices, which runs the preflight with
  `node_names` (`restore.py:1304`; unrequested rows are not probed, `restore.py:591`) and shows the
  confirmation of section 3 with only the devices it asked about (the rows with `requested` true), no
  page-derived rows, no subset sentence, and the line `Only the devices that were not loaded are
  listed.` (review L2). The red **Load** submits with a fresh `request_id`. There is no shortcut
  around the preflight, the confirmation or the backup.

A load that changed nothing (not an effective load) is not a chip state, so the chip panel has no view
for it. When the chip panel was showing that job as it ended, `loadWatch` shows the result in the Load
panel instead (the Load button is enabled again by then): `<Name> was not loaded` / `No device was
changed.` with the rows, **Try again** (the same rule as above) and **Details**. This view holds no
review and no red button. The chip returns to what it showed before, which after an earlier effective
load is that load (K1); the lab banner carries the failure with **Details** and **Dismiss** as today
(`app.js:224-226`), also when no panel was open.

---

## 6. Undo this load (D7)

`loadUndo(job)` = `loadChoose(labId, {type:'backup', backup_job_id: job.pre_backup_job_id},
<name>)`, where `<name>` is `loadSourceName` of that backup (5.2): `the configuration from before
<X>`, or `<Y>` when the job being undone is itself the undo of a load of `Y`. It is an ordinary load:
same preflight, same confirmation (headline `Undo loading <X>?`, or `Load <Y> again?` for the undo of
an undo; same sentence, same rows), same red **Load**, same mandatory backup, same transaction. No new
restore mechanism and no new route.

Where it is offered:

| Place | Control | While |
|---|---|---|
| The *Running* and *Partial* chip panels (5.3), and the *Also* line's panel when a failed save attempt sits in front of the load | **Undo this load** | the chip state lasts, that is until the next capture save or a deploy, redeploy, destroy or design apply (5.2) |
| The restore job window (`restoreRenderJob`, `restore.js:376-387`), beside its `Backup taken before the change` link | **Load this backup…** (review U1) | the manager still keeps that backup (`state.jobs` holds `pre_backup_job_id`), whatever the chip shows; it calls `loadUndo(job)` after closing the window |
| The chip panel at rest | `Last load: <name>, <when>` with **Details** (header slice), which opens that job window | the manager holds a finished effective load of the lab |

So after a save, when the chip no longer says *Running*, Undo is still three steps away and still
works: chip, **Details**, **Load this backup…**, then the confirmation.

Verified in the code:

- The source exists and is resolved like the others: `restore.py:455-468` reads the backup job of this
  lab, builds the same manifest and candidate table as a Git save (`captured_snapshot`,
  `git_progress.py:365-473`, restore artifacts at `git_progress.py:397-400` and
  `git_progress.py:427-436`), and from `restore.py:508` on nothing depends on the source type.
- It is the best-tested source: the service tests use it throughout (`tests/test_restore.py:168`).
- The pre-load backup is an ordinary Runner backup (`restore.py:783-785`) and therefore stores each
  device's restore artifact where the platform has one (`runner.py:529-542`).
- Throwaway probe (scratch script outside the repository, subclassing the existing test fixture, on a
  temporary data directory; unit level, fake devices; run before B4 existed): after a full load, a
  preflight of `{type:'backup', backup_job_id: <pre_backup_job_id>}` returned both devices eligible
  with `saved_nodes` equal to the loaded devices; submitting it produced a `succeeded` job with its
  own, different `pre_backup_job_id`. Exit status 0. This is not live evidence.

Edge cases:

| Case | What happens in the service | Design |
|---|---|---|
| The backup covers only the devices that were loaded | `saved_nodes` is exactly the job's live targets (`restore.py:783-785`); other lab devices have no row | The confirmation shows them as `Not in this state` (G07 rule), with the sentence `This undoes the load on the n devices it changed. The others are left as they are.` |
| A device was skipped before the backup (`ineligible`) | not in the backup (`restore.py:768-774`) | same as above |
| The safety backup failed for one device | The load leaves that device unchanged (`restore.py:916-920`) and the backup job is `partial`. With the strict default `captured_snapshot` refuses any backup with a non-succeeded node (`git_progress.py:371-374`) | **B4** below: the undo reads the devices whose backup succeeded. The device whose backup failed was never changed; it has no row in the preflight and reads `Not in this state`. |
| The backup holds no restore artifact for a device (the artifact capture is best-effort, `runner.py:529-542`) | the row is ineligible with `NO_ARTIFACT` | the row says so; the other devices can still be undone |
| The backup record was trimmed (`jobs` is capped at 300 per lab, `runner.py:28`, `runner.py:370-371`; a pre-load backup is protected while its restore job is busy or interrupted, `runner.py:199-201`, and for the lab's newest effective load, B5) | 404 `Saved capture not found in this lab.` (confirmed by the probe) | The page checks `state.jobs` for `pre_backup_job_id` before offering the action; when absent, **Undo this load** is disabled with `The automatic backup of this load is no longer kept.` and **Load this backup…** is not shown (review U2). **B5** keeps the backup of the newest effective load, so this case is an older load's. |
| The job changed nothing | `pre_backup_job_id` may be empty (`restore.py:713`) or name a backup of unchanged devices | Not an effective load (5.2: this includes a job whose only doubtful devices were interrupted before the change), so no chip panel offers Undo (review U2). In the "was not loaded" view the action is absent. |
| The job has no `pre_backup_job_id` or its backup job is `failed` | nothing to load | action absent |
| Undo after a partial load | the backup covers every device that was backed up, a superset of the devices changed | The preflight shows unchanged devices as `Already matches`; they stay ticked or can be left out. A device that is now unreachable shows that reason and cannot be ticked. |
| Devices left `uncertain` by the load | their state is unknown; the preflight may find a foreign pending change and block them | Rows show the preflight's reason; nothing is guessed. |
| Undo of an undo | The undo is a restore job with its own pre-load backup (the state that was loaded). | After undoing a load of `X` the chip reads `Running the configuration from before X`; its panel offers **Undo this load** again, whose confirmation asks `Load X again?` and after which the chip reads `Running X` (review U3). It is a toggle between two captured states, each step with its own backup, and the name never nests. |
| A save happened after the load | the chip is no longer *Running* (section 7) | **Load this backup…** in the job window, reached through the `Last load` line (review U1). The backup also stays listed under Advanced › Backups. |
| A deploy, redeploy, destroy or design apply happened after the load | the chip is no longer *Running* (5.2) | The same route. The preflight decides per device; after a redeploy the saved management settings may no longer fit, which the preflight's comparison and each device's own timed recovery cover as for any load. |

**B4. Undo with an incomplete safety backup** (DESIGN.md 3.7 Q5; the seam exists in the code).
`captured_snapshot(store, backup, context=None, embedded_files=True, complete=True)`
(`git_progress.py:365`). With `complete=False` it keeps only nodes with `status == 'succeeded'`
(`git_progress.py:372`) and skips the scope check (`git_progress.py:376-379`); everything else (digest
checks, limits) is unchanged. `resolve_source` passes `complete=False` only when the backup job's
`source` is `restore-pre` (`restore.py:462`, `restore.py:783`). A device whose safety backup failed was
never changed by that load (`restore.py:916-920`), so leaving it out of the undo loses nothing. Git
saves and every other backup source keep the strict default: "an older configuration is never saved in
its place" is untouched, and a test pins the default.

**B5. Keep the newest load's safety backup findable** (DESIGN.md 3.7; built with `app/runner.py` by
the slice that owns it, not as part of the restore route work, and present in the code now).
`protected_job_ids` (`runner.py:184-210`) also protects `pre_backup_job_id` of each lab's newest
restore job that has a target in `verified`, `applied`, `applied_unverified`, `verify_mismatch` or
`uncertain` (`CHANGED_TARGETS`, `runner.py:182`, `runner.py:202-209`): the effective-load test of 5.2.
A job that still awaits a read-back is `interrupted` and was protected already (`runner.py:199-201`).
One more protected job id per lab; no other trimming changes.

---

## 7. When the chip leaves *Running*

Rule (DESIGN.md 7.1, restated in 5.2): the chip is *Running* or *Partial* while the newest effective
load `L` is newer than the newest capture save `S` of the same lab and no deploy, redeploy, destroy or
design apply of the lab finished after `L`. It leaves the state when the next capture save completes,
or when one of those operations finishes.

- `time(L)` = `L.finished` (set by `_finalize`, `restore.py:1249`; ISO UTC, `runner.py:34-35`).
- `S` = the newest job in `git_jobs` with this `lab_id` for which all of these hold: `captured` is
  true (the job read the devices itself); `kind` is neither `state` (a lab state, DESIGN.md 2.9) nor
  `design` (a design export); its status is one of `synced`, `unchanged`, `committed`,
  `review_pending`, `push_pending`. `time(S)` = `finished || created`.
- `unchanged` counts: a save right after loading one's own latest completes without a commit, and the
  lab is then at its latest save.
- What does not count as `S`: a checkpoint or a starting point made from an existing capture (it sends
  `backup_job_id` and reads no device, so `captured` is false: the devices may have been loaded since
  that capture was taken); a lab state; a design export; a folder move; an update; a failed attempt
  (`export_pending`, `capture_incomplete`, `failed`, `interrupted`), which is the chip's *Can't save*
  in front of the load and ends nothing.
- A finished deploy, redeploy or destroy (`operations[]`) or design apply (`design_jobs[]`) of the lab
  newer than `L` ends it (5.2 has the fields).
- Compare with `statusEpoch` (`status.js:41`), which reads both time forms.

Fields in `/api/state`. One is new (`captured`, built by the save slice); the others exist today:

| Field | Produced at |
|---|---|
| `restore_jobs[].lab_id, status, created, finished, source, pre_backup_job_id, targets[].name/short_name/platform/status/stage/timeline, rechecking` | `restore.py:47-48`, `restore.py:83-92`, served at `main.py:225` |
| `git_jobs[].lab_id, target, checkpoint, status, created, finished, note, commit, kind, snapshot_path` | `git_progress.py:40-42`, `git_progress.py:60-61`, served at `main.py:224` |
| `git_jobs[].captured` (new, public): true when the job captured the devices itself, false when it was made from an existing capture (`backup_job_id` in the request) | to be added to `PUBLIC_JOB`, `git_progress.py:40-42` (save slice; DESIGN.md 7.1) |
| `operations[].lab_id, action, status, finished` | `lab_operations.py:644-645`, `lab_operations.py:915`, `lab_operations.py:921-922`, served at `main.py:227` |
| `design_jobs[].lab_id, status, finished, rechecking` | `design_apply.py:49-51`, `design_apply.py:925`, served at `main.py:226` |
| `jobs[].id, source, status, progress_id, nodes[].status/restore_file` (is the pre-load backup still there) | `runner.py:360-364`, `runner.py:529-542`, served at `main.py:222` |
| `labs[].nodes[].name/short_name/platform`, `platforms` (which kinds have a restore format) | `main.py:154-166`, `main.py:223`, `inventory.py:17-30` |

`loadState(lab, ctx, now)` returns
`{key: 'loading'|'running'|'partial'|'', job, name, loaded, total, done, at, last, undo: {available, reason}}`.
`job` is the active job or `L`; `last` is the newest effective load whether or not something ended it
(for the `Last load` line and for the *Also* line of a *Can't save* panel); `loaded` is the verified
count; `undo.reason` is empty or `The automatic backup of this load is no longer kept.`
`saveChipState` calls it and applies the order of DESIGN.md 7.1.

Limits to know: `restore_jobs` is capped at 200 for the whole manager (`restore.py:142`,
`restore.py:157-161`); a load older than that disappears and the chip falls back to the save state.
`operations` keeps its newest 200 entries for the whole manager (`lab_operations.py:647-648`), so a
redeploy can drop out of the list while the load it ended is still listed. For a successful deploy or
redeploy the lab's own record covers that: `labs[].last_deployed` (`lab_operations.py:818-824`, served
at `main.py:176`) newer than `L` ends it too. A destroy, a failed deploy and a design apply have only
their capped lists; after more than 200 later operations the chip could read *Running* again until the
next save. Accepted as a limit, named for the reviewer (section 15).
*Remove lab* drops the lab's restore jobs (`main.py:249`).

---

## 8. Not running, no saves, no save location, any folder, an older commit

**Lab not running (G09).** When `labState(lab, ctx).key` is `stopped` (`status.js:101`), the Load panel
shows `Start the lab to load a state` / `Loading puts a saved configuration onto running devices. This
lab is not running.` / **Start lab**. The button calls `startLab()` (`app.js:200`), which runs the
header's own start action, `opQuickRun('start')` (`app/static/operations.js:679`), exactly as the lab
banner's start button does (`app.js:215-216`); it mirrors that button's disabled state and shows its
reason as text. No preflight is sent. For any other lab state the list is shown and the preflight
decides per device (a partly running lab loads the devices that run). After the start the person
presses Load again; the panel does not load on its own.

**No saves of its own (G08).** The lab has a save location but the list holds no row of group
`latest` or `checkpoint`: the panel opens with `This lab has no saves of its own yet. You can start
from one of these.` and the Lab states group. With no lab states either:
`Nothing is saved in this repository yet. Save this lab, or ask your instructor for the course's lab
states.`

**No save location** (DESIGN.md 3.7 Q3: Load works before the first save). Before this work the
Git-backed sources require the loading lab's own binding (`restore.py:444`, `restore.py:477`,
`git_progress.py:609-613`). Now:

1. For a lab without a binding `loadOpen` first asks `GET /api/labs/{lab}/git/places` without a
   repository, which answers with the repositories on the VM and the default of DESIGN.md 2.8 (the
   repository the lab used last, else the one saved to most recently, else the first).
2. It then fetches `…/restore/states?repository=<default repository id>` and shows the list as in
   G08: no `Your saves` group, the sentence `This lab has no saves of its own yet. You can start from
   one of these.`, the `Lab states` group, and under it the line `From <repository name>.` so the
   person sees which repository is listed.
3. Every source sent from this list carries `repository`, and the service reads through
   `self.git.reader(lab_id, repository)` (2.3). Nothing is registered, bound or written: loading a
   course's `Start` does not choose where the lab saves.
4. **All versions** and **Browse the repository…** take the same `repository` (DESIGN.md 3.8, drawers
   N4), and are the way to another repository when the VM has several.

**No repository on the VM at all.** The places answer lists none, so there is nothing to read. The
panel shows `There is nothing to load yet` / `No repository is connected to this lab VM. Save this lab
once to connect one, or ask your instructor for the course repository's address.` with **Save…**,
which closes the Load panel and opens the first-save view of the chip panel (`saveOpenPanel('status')`;
that view asks for the HTTPS address, DESIGN.md 2.8). The foot's **All versions** and **Browse the
repository…** are left out, because both need a repository. Loading a backup of this lab (Undo, **Load
this backup…**) needs no repository and keeps working.

**The VM cannot be asked** (either request fails): `The saved states could not be read from the lab
VM.` with the manager's sentence and **Try again**; the foot stays.

**Any folder of the repository.** Verified: the `folder` source reads any safe path of the checkout,
registered or not. The manager resolves the path exactly (`restore.py:478-481`), the helper's
`read-version` accepts any safe folder (`allowed_repo_version`, `host_git.py:707-713`) and refuses only
a folder without `manifest.json` or a commit outside the branch history (`host_git.py:719-723`); the
service test `tests/test_restore.py:416` applies a sibling folder without rebinding. The browser rule
for "which snapshot does this folder mean" is `gitApplySource` (`git-places.js:76-81`): the folder
itself when it is a snapshot, else its `latest/` child, never a substitute for a folder that is itself
a snapshot (pinned by `tests/test_git_places_ui.js:332`).

The Load path reuses, unchanged: `gitTreeModel` and `gitApplySource` (`git-places.js`),
`gitSnapshotPath` (`git-progress.js:34`), `restoreFromFolder`'s path normalisation
(`restore.js:152-153`, pinned by `tests/test_restore_ui.js:32`), the `folder` source and its commit
pinning. **Browse the repository…** hands over to the folder chooser in browse mode (chooser and
drawer slices); its action on a folder for which `gitApplySource` answers is **Load this state…**,
calling `loadChoose(labId, {type:'folder', path, repository}, name)`. No other script starts a load:
`loadState` is the pure status function, `loadChoose` is the entry (review X1).

**An older commit (review F8).** *Full history…*, in the foot of All versions, opens today's history
(`gitHistory`, `git-progress.js:724-730`). A commit's view there is today's saved-version view; its
danger-outline button reads **Load this state…** (today `Apply to running lab…`, `git-progress.js:754`,
shown only when the version has restore data) and calls
`loadChoose(labId, {type:'git', commit, path, repository}, name)` after closing the dialog, through
`restoreFromVersion` (`git-progress.js:761`, `restore.js:141-143`). A `git` source names its commit
itself, so the loaded bytes are those of that commit; for the lab's own `latest` the chip then reads the name
of that commit's save, or `Running an earlier save, <when>` when the manager no longer holds it (5.2).

---

## 9. Parity table

| Today | New design | Notes |
|---|---|---|
| E1 Saved versions row `Apply to running lab…` (own latest, checkpoints) | Load panel `Your saves` row; All versions row **Load this state…** | same `folder` source, now with the row's commit |
| E1 Baseline row | All versions `Starting point` row **Load this state…** | not in the panel |
| E1 Instructor and reference rows, Elsewhere rows | Load panel `Lab states` rows (within the cap); All versions `Lab states` | one group: every saved state that no connected lab owns |
| E1 Other labs rows | All versions, folded group | not in the panel (DESIGN.md 3.7 Q8) |
| E2 Saved-version view `Apply to running lab…` (a `git` source at a chosen commit) | All versions → *Full history…* → a commit's view: **Load this state…** calls `loadChoose` with the `git` source | keeps loading an older commit of a folder (review F8) |
| E2 view-only note for a version without restore data | `View only` row with `Saved without the files needed to load it` and **View** | now visible before choosing |
| E3 Folder browser apply for any folder | **Browse the repository…** → **Load this state…** on any snapshot folder | `gitApplySource` unchanged |
| E4 `Load a saved version…` | the **Load** button | one click instead of a tab change and scroll |
| E5 `Browse the repository…` | same words, foot of the Load panel and of All versions | |
| E6 `Full history…` | foot of All versions; opens today's history | drawer slice |
| E7 Banner `View progress` while a restore runs | chip *Loading* with the device list in its panel; the banner keeps **View progress** → job window | both stay |
| E8 Banner `Details` / `Dismiss` after a restore that needs attention | unchanged banner; chip *Partial* with **Details** | |
| E9 `Last configuration change` line | chip *Running* / *Partial* with **What changed**; after the next save the chip panel's `Last load: <name>, <when>` with **Details** | review F4; header slice |
| E10 Restore job window | unchanged but for one added button; opened by **What changed**, **Details**, the `Last load` line and the banner | gains **Load this backup…** (review U1) |
| E11 Compare text pointing at Apply | reworded to **Load this state…** | |
| E12 `/restore/sources` | route kept, still unused by pages | API parity |
| Review: per-device tick box (leave a device out) | tick boxes in the confirmation | D4 |
| Review: difference count per device | `n lines differ` / `Already matches` | same number (`pending_changes`) |
| Review: `Show differences (saved → running now)` per device | **See what's different** drawer | same data; its button reads `Load on n devices` |
| Review: skipped devices with reasons, raw text under Details | reason under each device name; raw text stays in the job window for started jobs | |
| Review: saved time and pinned commit beside the source | `Saved <when>.` under the confirmation's sentence; time and commit in the meta line of the differences drawer | review F9 |
| Review: Advanced options, undo window minutes | folded `Options` in the confirmation | same bounds |
| Review: acknowledgement tick box | removed; the red **Load** is the acknowledgement | D4; request unchanged |
| Review: safety list (backup first, no reboot, self-undo, skipped untouched) | the confirmation sentence and the loading sentence | shorter, same facts |
| Row `View` (a state's files, topology and map included) | All versions **View files**; **View** on a `View only` row; **View its topology** | |
| Row `Compare with my latest save` | All versions **See what's different** (saved against saved) | drawer slice; distinct from the confirmation's saved-against-running view |
| Version view `Download (ZIP)` | All versions **Download ZIP** | drawer slice |
| Applying needs the lab's own save location (409 without one) | Load lists and loads from the default repository before the first save | DESIGN.md 3.7 Q3; a gain, nothing removed |
| The pre-restore backup's link in the job window (view only) | the same link, and **Load this backup…** beside it | review U1 |
| New | **Undo this load**, **Try <device> again**, coverage on the row, topology line, `Last load` line | D7, 5.4 |

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
| No save location | the `No own saves` sentence, and under the list `From <repository name>.` |
| No repository on the VM | `There is nothing to load yet` / `No repository is connected to this lab VM. Save this lab once to connect one, or ask your instructor for the course repository's address.` / `Save…` |
| Overflow | `N more in All versions` |
| Foot | `All versions`, `Browse the repository…` |
| Row action elsewhere | `Load this state…` |
| No own saves | `This lab has no saves of its own yet. You can start from one of these.` |
| Nothing at all | `Nothing is saved in this repository yet. Save this lab, or ask your instructor for the course's lab states.` |
| List cannot be read | `The saved states could not be read from the lab VM.` + the manager's sentence + `Try again` |
| Not running | `Start the lab to load a state` / `Loading puts a saved configuration onto running devices. This lab is not running.` / `Start lab` |
| Load button disabled | only while a load runs; the reason is the chip beside it (`Loading… 2 of 4`) |
| Red Load disabled during a save | `A save is running.` |
| A row chosen during a save | `<Name> cannot be loaded right now.` / `A save is running.` / `Try again`, `Back` |
| Preflight running | `Checking <name> against your devices…` |
| Preflight refused | `<Name> cannot be loaded right now.` + the manager's sentence + `Try again`, `Back` |
| Confirmation | `Load <name>?` / `The running configuration of the ticked devices is replaced. The current one is backed up first; nothing reboots.` / `Saved <when>.` |
| Subset | `This state covers 2 of your 4 devices. The others are left as they are.` |
| Topology | `Saved on a different topology: 3 of 4 devices match.` / `View its topology` |
| Row texts | `5 lines differ`, `1 line differs`, `Already matches`, `Ready to load`, `Not in this state`, `Not in this lab`, `Not reachable`, `Blocked`, `Can't load` |
| Nothing ticked | `Tick at least one device.` |
| Nothing loadable | `None of the devices can be loaded right now.` |
| Options | `Options` / `Undo automatically if a device cannot be reached again within (minutes)` |
| Confirmation actions | `Load`, `Cancel`, `See what's different` |
| Differences drawer | `What's different` / `<name> compared with what the devices run now · saved <when> · <commit>` / `Load on 3 devices` (`Load on 1 device`), `Back` |
| Loading | `Loading <name>…` / `Each device checks the new configuration itself and undoes it if it loses contact. You can keep working.` |
| Loading rows | `Waiting`, `Backing up…`, `Loading…`, `Checking…` |
| Chip | `Loading… 2 of 4`, `Checking devices…`, `Running <name>`, `Loaded 3 of 4` |
| All loaded | `Running <name>` / `Loaded <when> on all 4 devices.` (a subset: `Loaded <when> on 2 devices.`) / `Your latest save: <name>, <when>` / `Before loading: backed up automatically` |
| Toast, only for a load that succeeded | `<Name> loaded on 4 devices.` (`on 1 device.`) |
| Partial headline | `Loaded on 3 of 4 devices` |
| Partial sentence, by the worst remaining outcome | `failed`: `xrv9k was not changed.` · `rolled_back`: `xrv9k undid the change and runs its previous configuration again.` · `uncertain` / `interrupted` / `rollback_expected`: `The manager could not confirm what xrv9k runs. Open Details before relying on it.` · unverified only: `xrv9k was loaded, but the check afterwards did not confirm it. Open Details.` · several devices: `2 devices were not changed.` and so on, one clause per kind, uncertain first |
| Result rows | section 5.1; `uncertain`: `Not confirmed` / `The manager could not confirm what this device runs. Open Details.` |
| Result actions | `Try xrv9k again`, `Try 2 devices again`, `Undo this load`, `What changed`, `Details` |
| Nothing changed | `<Name> was not loaded` / `No device was changed.` |
| Retry note (in place of the subset sentence) | `Only the devices that were not loaded are listed.` |
| Undo confirmation | `Undo loading <name>?` (the undo of an undo of X: `Load X again?`) / the confirmation sentence / `This undoes the load on the 3 devices it changed. The others are left as they are.` |
| Undo unavailable | `The automatic backup of this load is no longer kept.` |
| Job window, beside the backup taken before the change | `Load this backup…` |
| Chip panel at rest (header slice) | `Last load: <name>, <when>` / `Details` |
| Name after *Running* | the save's name; `an earlier save, <when>`; a checkpoint's name; `your starting point`; a lab state's name; `the configuration from before <name>`; for the undo of an undo of X: `X`; `a backup from <time>` |
| Live region | the chip text on every state change, and the toast; a sentence only, never a button |

Rewordings of existing strings (each is pinned by a test that is rewritten, not deleted):

- `restoreReasons` (`restore.js:40-51`): "This saved version was made before…" → `This state was saved
  before this kind of device could be loaded. Save the lab again to get a loadable state.`; "cannot be
  updated this way yet" → `This kind of device cannot be loaded yet.`; the credentials and refresh
  sentences keep their meaning, and where an action exists it is a link button beside the sentence
  instead of a menu path in it (review D3).
- Banner and status: `Replacing configuration…` → `Loading a saved state…` (`app.js:96`, `app.js:222`),
  `Replacing configuration` → `Loading a saved state` (`status.js:94`),
  `STATUS_RESTORE_ATTENTION_DETAIL` (`status.js:19`) → `The load needs a check on some devices.` /
  `The load finished on some devices only.`
- Job window: titles and step labels stay (`restore.js:16-28`, `restore.js:55-71`,
  `restore.js:130-138`). It is the technical view, and its vocabulary is the service's (DESIGN.md 3.7
  Q7). The two closing sentences that name `Advanced › Action logs` and the lab header stay true and
  are kept (`restore.js:391-392`). One control is added: **Load this backup…** (section 6).
- `git-progress.js:746` and `git-progress.js:727`: "Apply to running lab…" → `Load this state…`.

---

## 11. File plan

Owners are the slices of DESIGN.md section 5. This slice (S8) owns `app/static/load.js`,
`app/static/restore.js`, `tests/test_load_ui.js` and `tests/test_restore_ui.js`; every other row says
what this design needs from its owner.

### 11.1 Scripts

| File | Owner | Change |
|---|---|---|
| `app/static/load.js` (new; needs `?v=<release>` in `index.html`, lead) | this slice | Shared names (DESIGN.md section 5): `loadOpen(labId)`, `loadChoose(labId, source, name, options)`, `loadUndo(job)`, `loadRetry(job)`, `loadJobMarkup(job)`, `loadChipView(cs, lab)`. Supplied to the drawer slice: `loadDifferentMarkup(review)`. Internal: `loadSubmit()` (the only sender of `acknowledge: true` to a restore route), `loadSource(source)` (the five keys), `loadListMarkup(model)`, `loadConfirmMarkup(review)`, `loadFetchStates(labId, repository)`, `loadWatch(job)`; module state `loadReview`, `loadStates` (per lab and repository, with `head`), `loadSeenActive`. No `window`, `document` or storage listeners: opening, closing, Escape, outside click and focus use `initPanel` in `shell.js`; `load.js` listens only on `#load-panel` itself (`panelopen`, `panelclose`, one delegated `click`, one `change`). Every name of another script is read at call time behind a `typeof` guard. |
| `app/static/restore.js` | this slice | Keep: constants, `restoreRequestId`, `restoreReasonLabel`, `restoreNotChangedReason`, `restorePlatformLabel`, `restoreTargetOutcome`, `restoreDiffDetails`, the whole job window. The job window gains **Load this backup…** beside the link of the backup taken before the change, shown while `state.jobs` holds that backup; it closes the window and calls `loadUndo(job)`. `restoreFromVersion` and `restoreFromFolder` keep their signatures and path rules and call `loadChoose`. `restoreReview` (the dialog with the tick box) is replaced by the panel confirmation; its name stays as an alias of `loadChoose` so other scripts and tools that call it keep working. |
| `app/static/status.js` | status slice (S6) | The pure functions `loadState(lab, ctx, now)` (DESIGN.md 7.1; 5.2 and section 7 here), `loadSourceName(source, ctx)`, `loadDeviceWord(target, job)` (returns `{text, cls, final, help}`), the table `STATUS_LOAD_WORDS` (5.1), and the changed `savedVersionName`. No DOM. The three restore strings of section 10 are reworded. `saveLoadName` and `loadCounts` do not exist: the counts are fields of `loadState`'s answer. |
| `app/static/save-header.js` | header slice (S7) | `savePanelView` calls `loadChipView(cs, lab)` for *Loading*, *Running* and *Partial*; the panel at rest shows `Last load: <name>, <when>` with **Details** from `loadState(...).last`; `saveOpenPanel('load')` and `saveOpenPanel('status')` are what `load.js` calls to open a panel. |
| `app/static/save-drawers.js` | drawer slice (S9) | The drawer kind `different` of `saveDrawerOpen`, whose body is `loadDifferentMarkup(review)`; its **Back** and its close tell `load.js` (3.4). All versions and the browse mode call `loadChoose`, never `loadState`. |
| `app/static/git-progress.js`, `app/static/git-places.js` | S11, S10 | `gitVersionAction('apply')` and the version view's button call `loadChoose` (through `restoreFromVersion` / `restoreFromFolder`) and read **Load this state…**; `gitRunAction('load')` opens the Load panel; `gitRenderLastRestore` goes with the Progress tab (5.11). `gitApplySource` unchanged. |
| `app/static/app.js`, `index.html`, `style.css`, `shell.js` | page skeleton (S5) | banner wording (section 10); the header markup of HEADER.md 1.2 with `#load-panel`; the shared classes; `initPanel`. |

### 11.2 Markup

Class names are those of HEADER.md 1.3 as listed in DESIGN.md 7.5, and no others: `save-panel`
(`wide`), `save-state`, `save-sub`, `save-row`, `save-note`, `save-kv`, `save-foot`, `save-heading`,
`save-list`, `save-item`, `save-when`, `save-why`, `save-devices`, `save-end` (`ok`, `bad`, `now`,
`warn`), `save-dot` (`ok`, `warn`, `bad`, `none`, `busy`, `info`) and the state class `off`. A quiet
action is the existing `button ghost small`. This slice adds no class: the reason under a device name
is a `save-why` (the same role as under a list row), and the folded `Options` is a plain `<details>`
styled as `.save-panel details`. Existing classes used as they are: `button`, `button danger`,
`button primary`, `sr-only`, `caption`, `form-error`.

Panel mechanics (review A2). The Load panel is a panel exactly like the chip panel: the markup of
HEADER.md 1.2, `div.save-panel.wide#load-panel[data-panel]` beside the `panel-button` **Load** inside
`span.menu`, opened and closed by `initPanel`. Only `#load-panel-body` is rendered by `load.js`. One
focus rule, the header's: on opening, `initPanel` focuses the element marked `data-panel-focus`. Every
view this slice renders starts with exactly one such element (`tabindex="-1"`): the list's heading
`Load a saved state` (`sr-only`), or the view's `save-state` headline. `loadOpen` renders on
`panelopen`, which fires before the focus is set, so the target exists. A view change inside the open
panel (list to checking, checking to confirmation, **Cancel** back to the list) moves focus to the new
view's `data-panel-focus` element, so the question is read. Escape closes the panel and returns focus
to **Load**; the danger button is never focused automatically.

List (G02, G08):

```html
<h2 class="sr-only" tabindex="-1" data-panel-focus>Load a saved state</h2>
<h3 class="save-heading">Your saves</h3>
<ul class="save-list">
 <li><button type="button" class="save-item" id="load-row-0" data-load-row="0"><span>NAME</span><span class="save-when">21 minutes ago</span></button></li>
</ul>
<h3 class="save-heading">Lab states</h3>
<ul class="save-list">
 <li><button type="button" class="save-item" id="load-row-3" data-load-row="3"><span>Final</span><span class="save-when">2 of 4 devices</span></button></li>
 <li class="off"><div class="save-item"><span>Start<span class="save-why">Saved without the files needed to load it</span></span><span class="save-when">View only</span></div><button type="button" class="button ghost small" id="load-view-5" data-load-view="5">View</button></li>
</ul>
<div class="save-foot"><button type="button" class="button ghost small" data-load-action="all">All versions</button><button type="button" class="button ghost small" data-load-action="browse">Browse the repository…</button></div>
```

A `View only` row is text plus a **View** button, not a disabled button: its reason is readable by
keyboard and screen reader, and the one thing that can be done with it is beside it.

Confirmation (G03, G07):

```html
<p class="save-state" tabindex="-1" data-panel-focus><span class="save-dot warn" aria-hidden="true"></span>Load NAME?</p>
<p class="save-sub">The running configuration of the ticked devices is replaced. The current one is backed up first; nothing reboots.</p>
<p class="save-note">Saved 2 days ago.</p>
<ul class="save-devices">
 <li><label><input type="checkbox" name="load-node" value="NODE" checked><span>ceos <small>EOS</small></span></label><span class="save-end">5 lines differ</span></li>
 <li class="off"><label><input type="checkbox" name="load-node" value="NODE" disabled><span>xrv9k <small>IOS XR</small><span class="save-why">The device did not answer over SSH.</span></span></label><span class="save-end">Not reachable</span></li>
</ul>
<details><summary>Options</summary><label for="load-minutes">Undo automatically if a device cannot be reached again within (minutes)</label><input id="load-minutes" type="number" min="2" max="60" value="5"></details>
<p class="form-error" role="alert"></p>
<div class="save-row"><button type="button" class="button danger" id="load-run">Load</button><button type="button" class="button ghost small" data-load-action="cancel">Cancel</button><button type="button" class="button ghost small" data-load-action="diff">See what's different</button><span class="caption" id="load-run-reason" hidden></span></div>
```

`#load-run-reason` holds `Tick at least one device.` or `A save is running.` while the red button is
disabled. Loading and results (G04, G05, G06) use `save-state`, `save-sub`, `save-devices` rows
without inputs (`<li><span>ceos <small>EOS</small></span><span class="save-end ok">Loaded</span></li>`),
`save-kv` lines and a `save-row` or `save-foot` row. Every value goes through `esc()`. No inline
style. Tick states are read from the DOM into `loadReview.chosen` on change, so a re-render never
loses them; the confirmation is not re-rendered by the 4 s poll (it shows a finished preflight; the
poll only switches the red button's disabled state and its reason), the loading and result views are,
through the header's keyed rebuild.

Device rows are plain labels and inputs in document order. State changes (`Checking…`, `Loading…`, the
result headline) are written to the header's polite live region as sentences only; a live region
never wraps a button (DESIGN.md 7.6).

### 11.3 Backend changes and their unit tests

| # | Change | Where, owner | Tests to write |
|---|---|---|---|
| B1 | `history` returns `head` and a bounded `summary` per saved state (DESIGN.md H3, review F10); no new mode, no new option | `app/host_git.py`, helper slice | `tests/test_host_git.py`: every listed manifest folder has a summary with its devices and restore flags; a manifest over 256 KiB is not read and its `summary` is `null`; the 4 MiB budget is spent on the lab's own states first; a wrong type, a control character or more than 500 devices yields `null`; strings are cut at 200 characters; no file contents in the answer; `head` is present; the mode list and the option whitelist are unchanged |
| B2 | `GET /api/labs/{lab_id}/restore/states?repository=<id>` + `public_state`, built on `self.git.states(lab_id, repository)`; the no-device eligibility test shared with `map_targets` | `app/restore.py`, load backend slice | `tests/test_restore.py`: `devices` and `loadable` for a state covering two of four devices; `view_only` with `no_restore_data` and with `unreadable` (a `null` summary); a platform mismatch is not counted loadable; no SSH connector call is made; a lab without a save location gets 409 without `repository` and the list with it; an unknown `repository` is 404; only the listed keys are exposed (no `summary`); the shared function gives the same verdict as a preflight row for each no-device reason |
| Source | `Source.repository`; Git-backed sources read through `self.git.reader`; HEAD from `history` for a registration that is not the lab's own | `app/restore.py`, load backend slice | a source with five keys is accepted and a sixth key is refused (`extra='forbid'`); a lab without a binding preflights and loads a `folder` source with `repository`; on that path no `status` request reaches the helper and the commit is the `history` answer's `head`; the lab's own binding keeps its path; a `repository` the helper's `list` does not name is 404; the job's public `source` carries `repository` and nothing else of the registration |
| B3 | `source.topology` in the preflight and the job, compared by structure | `app/restore.py`, load backend slice | `differs` false for the same nodes, kinds and link endpoints in another order or with other comments; true for a node added, a kind changed, a link moved; `null` for a backup source, a state without an embedded topology, a lab without a topology text and a file that does not parse; `matching_devices` from the rows; present in `public_job`; no topology text anywhere in the answer |
| B4 | `captured_snapshot(..., complete=False)` only for a backup whose `source` is `restore-pre` | `app/restore.py` (the keyword exists in `app/git_progress.py`) | the undo of a load whose safety backup failed for one device lists the other devices; the same partial backup is still refused for a Git save and for a backup source that is not `restore-pre`; a digest mismatch is still refused; the default of the keyword is strict |
| B5 | one more protected job id per lab: the newest effective load's `pre_backup_job_id` | `app/runner.py`, its owning slice | the backup survives 300 later jobs of the lab; an older load's backup is still trimmed; a load that changed nothing (targets interrupted before the change included) protects nothing |
| existing | `acknowledge` stays required; undo is a plain `backup` source | `app/restore.py` | `tests/test_restore.py:607` unchanged; new: a load, then a load of its `pre_backup_job_id`, ends `succeeded` with a new safety backup (the probe of section 6, made permanent) |

No change to `restore_drivers.py`, to any driver, to `_apply_one`, `_settle`, `_record_settled`,
`_verify` or `_finalize`. New test files reach CI only through the explicit list in
`.github/workflows/release-check.yml` (lead).

### 11.4 Node tests to write

`tests/test_load_ui.js` (new) and `tests/test_restore_ui.js` are this slice's;
`tests/test_status_ui.js` is the status slice's and carries the tests marked (status).

1. (status) `loadState`: an active job → `loading` with `done` equal to the number of final rows;
   `succeeded` newer than the newest capture save → `running`; `partial` and `needs_attention` →
   `partial` with `loaded` = the verified count (a job with four replaced devices, one
   `applied_unverified`, gives 3 of 4); a job with only `failed` / `rolled_back` / `ineligible`
   targets is skipped and the previous load decides; `rechecking` → `loading`.
2. (status, review O2) A finished job whose targets are `failed` and `interrupted` with a settled
   timeline (interrupted before the change) is not an effective load: empty key, no `Loaded 0 of 4`,
   `undo.available` false. The same job with one target of stage `uncertain`, or one `interrupted`
   target whose timeline has no `settled`, is effective.
3. (status, review K1) The sequence "load A succeeds, load B fails": after B (every target `failed`)
   the key is still `running` with A's name and `job` is A; the same with B `preflight_failed`; with B
   `partial` (one device verified) the key is `partial` and `job` is B.
4. (status, review K2) What ends *Running*: a capture save in each of `synced`, `unchanged`,
   `committed`, `review_pending`, `push_pending` newer than the load → empty key; a job with
   `captured: false` (a checkpoint or a starting point from an existing capture), a job of kind
   `state`, a job of kind `design`, a `move`, an `update` and a failed attempt (`export_pending`,
   `capture_incomplete`, `failed`, `interrupted`) do not end it.
5. (status, review K6) A finished `deploy`, `redeploy` or `destroy` in `operations` and a finished
   job in `design_jobs`, each of this lab and newer than the load, end it; one of another lab, one
   older than the load, one still running and a `restart` do not; `lab.last_deployed` newer than the
   load ends it without an operation entry.
6. (status) `STATUS_LOAD_WORDS` covers every key of `restoreOutcomes` and every outcome status named
   in `restore.py`; `Kept previous` is produced for `rolled_back` only; `uncertain`, `interrupted` and
   `rollback_expected` never produce `Loaded` or `Kept previous` and always carry the Details hint;
   the help of `uncertain` is exactly `The manager could not confirm what this device runs. Open
   Details.` (review O3). A target `applied` + `checking` is not final and reads `Loading…`.
7. (status) `loadSourceName` for each source type: the lab's `latest` at the commit of a listed save
   gives that save's name, and its current name after a rename; at a commit no save has, `an earlier
   save, <when>` and never the newest save's name (review O4); a checkpoint, the starting point, a lab
   state by its list name; the backup before a load of `X` gives `the configuration from before X`;
   the backup before the undo of a load of `X` gives `X` (review U3).
8. (status) `savedVersionName`: `start`, `broken`, `final` → `Start`, `Broken`, `Final`; mixed-case
   names unchanged (rewrite of `tests/test_status_ui.js:176-180`).
9. List markup: rows by `group` (`latest`, three newest `checkpoint`, `state` capped at eight with the
   overflow line; `baseline` and `other-lab` absent); a `View only` row is not a button, shows its
   reason (`no_restore_data`, `unreadable`) and a View button; coverage text for full, partial and
   unknown coverage; a row's source carries its `commit` and the list's `repository`; only class names
   of DESIGN.md 7.5 occur in the markup of every view.
10. Confirmation markup: each preflight row kind of section 3 gives the stated text and tick box
    state; lab devices without a row read `Not in this state`; a saved device without a lab node reads
    `Not in this lab`; reasons are escaped; `Saved <when>.` is present (review F9); nothing ticked
    disables Load with its text; a save of the lab running disables Load with `A save is running.`
    and keeps the ticks (review D1).
11. (review L1) The review's life: after `panelclose` the review is gone and the next `loadOpen`
    renders the list; after the lab on screen changes, `loadSubmit()` sends nothing and the review is
    gone; `loadSubmit()` sends nothing without a finished preflight; a preflight answer that arrives
    after its review was replaced or cleared renders nothing; while the differences drawer is open the
    review is held, **Back** shows the same confirmation with the same ticks and request id, any other
    close clears it.
12. (review L2) A retry: the confirmation holds exactly the rows the preflight marks `requested`; a
    lab device that was not asked for and a saved device that was not asked for have no row; the
    subset sentence is absent; the retry note is present.
13. (review L3) The submit body is exactly `{request_id, source, node_names, confirm_minutes,
    acknowledge: true}`; `loadSource` returns exactly five keys (`type`, `commit`, `path`,
    `backup_job_id`, `repository`) for a folder, a git and a backup source, never a key of the richer
    object a preflight returns; a folder source carries the preflight's commit; the preflight is sent
    the same five keys (rewrite of `tests/test_restore_ui.js:54`).
14. Single sender: scanning the page scripts, `acknowledge: true` is sent to a restore route from one
    place, `loadSubmit`, and `loadSubmit` is referenced only by the confirmation's and the drawer's
    Load handlers.
15. (review L4) `loadDifferentMarkup`: the button reads `Load on 3 devices` / `Load on 1 device` for
    the ticked count, shows differences of ticked devices only, and is disabled with its reason when
    nothing is ticked or a save runs.
16. `restoreFromFolder` still sends the exact path with one leading slash (keeps
    `tests/test_restore_ui.js:32`).
17. `loadRetry`: the source is rebuilt from a job's `source` for each type with the five keys, the
    job's `repository` included; devices are the `failed`, `rolled_back` and `ineligible` targets; the
    button is absent when there is none.
18. `loadUndo`: sends `{type:'backup', backup_job_id}` in five keys; unavailable with `The automatic
    backup of this load is no longer kept.` when the backup is missing from `state.jobs`; absent when
    the job has no `pre_backup_job_id` or is not an effective load; available for a `partial` backup
    (B4). The headline is `Undo loading X?`, and `Load X again?` for the undo of an undo.
19. (review U1) The job window shows **Load this backup…** only while `state.jobs` holds the backup
    taken before the change, and its click ends in `loadUndo`, never in a request.
20. (review O5) The toast fires once for a job that ended `succeeded` and for no other status; the
    panel line reads `on all 4 devices` for a full load and `on 2 devices` for a subset.
21. Disabled states (review D1): the Load button is disabled while a restore job of the lab is active
    and in no other state (a save, a backup, a lab operation, another lab's load); a row chosen during
    a save sends no request and shows `A save is running.`
22. (review A2) Every view's markup holds exactly one `data-panel-focus` element with
    `tabindex="-1"`; `load.js` adds no listener to `document` or `window`.
23. Not running: the Start lab view, no preflight request made. No save location: the places request,
    then the states request with the default repository; `From <repository>.` shown; sources carry
    `repository`. No repository on the VM: the "nothing to load yet" view with **Save…** and no foot.

### 11.5 Fixture and browser pass (lead, QA)

The fixture manager patches `restore._probe` (`docs/redesign/tools/fixture_manager.py:417-421`) and
needs, for this slice: `start`, `broken`, `final`; a state without restore artifacts; a state covering
two of four devices; a state from a different topology; a scripted `history` answer with summaries
(B1); a lab without a save location on a VM with a repository; a probe that reports one device
unreachable and one blocked.

---

## 12. Friction budget

Load a lab state: **Load** (1), the state's row (2), red **Load** (3). Three clicks, nothing typed.
The preflight runs between clicks 2 and 3 and takes as long as the devices take to answer. The same
three clicks for a lab without a save location.

Undo while the chip says *Running* or *Partial*: chip (1), **Undo this load** (2), **Load** (3).
Undo after a later save: chip (1), **Details** on the `Last load` line (2), **Load this backup…** (3),
**Load** (4). Retry: chip (1), **Try xrv9k again** (2), **Load** (3). Leaving a device out adds one
click. Looking at the differences adds two (open, **Back**), or none when the load is started from
the drawer's own **Load on n devices**.

---

## 13. Assumptions

1. The chip panel for *Loading*, *Running* and *Partial* is rendered by this slice's `loadChipView`
   inside the header slice's panel shell; there is one live region for the header.
2. The All versions drawer, the history's commit view and the folder chooser call `loadChoose`; they
   close themselves first (a modal drawer makes the header inert, and only one panel or drawer is open
   at a time).
3. A lab state saved with **Save as a lab state…** is an ordinary snapshot folder with `manifest.json`
   and restore artifacts (DESIGN.md 2.9), so it appears in `Lab states` without special handling.
4. A save job says whether it read the devices (`captured`) and what it is (`kind`: `state`,
   `design`), so `S` needs no guess from `target` (DESIGN.md 7.1).
5. `lab['definition_yaml']` is the lab's topology for B3, compared by structure (DESIGN.md 3.7 Q4).
6. Platform short labels stay `restorePlatformLabels` (`restore.js:35-37`); the mockup's `IOS-XR`
   reads `IOS XR` as today.
7. A row's `commit` in the states list is the commit that last wrote that state (what `history`
   reports for the folder), not the checkout's HEAD. The name rule of DESIGN.md 7.1 ("the save whose
   commit is the loaded commit") needs it: a `folder` source without a commit is read at HEAD, and
   HEAD is another lab's save as soon as one is made in the same repository. If the row's `commit`
   were HEAD, a load of the lab's newest save would read `Running an earlier save, …`.
8. `initPanel` fires `panelopen` and `panelclose` on the panel element (HEADER.md 2.2), which is how
   `load.js` learns of both without a document listener.

---

## 14. Where each open question was decided

The questions this section asked are answered by the lead in DESIGN.md 3.7 and folded into the body.

| Question | Decision | In DESIGN.md | In this file |
|---|---|---|---|
| Q1, B1: manifest contents at list time | The helper's `history` mode returns `head` and a bounded `summary` per saved state; no mode `states`. The tree-only fallback is not built. | 3.7, H3; bounds from REVIEW.md section 1 F10 | 2.3 B1, B2 |
| B2: the list route | `GET /api/labs/{lab}/restore/states?repository=<id>` in `restore.py`, on `self.git.states` | 3.7, 3.8 (drawers N3), section 4, section 5 | 2.2, 2.3 B2 |
| Q2: matching a saved device to a lab device | Unchanged: by full node name. Matching across differently named labs is left open for the owner. | 3.7, section 6 | 1.2, 2.3 B2 |
| Q3: a lab without a save location | Load works before the first save: a source may carry `repository`, read through `self.git.reader`; HEAD from `history`, never `status` | 3.7; REVIEW.md section 1 F17 | 2.3, section 8 |
| Q4: the topology comparison | By structure (node names with kinds, link endpoints); `null` when either side is missing or unreadable | 3.7 | 2.3 B3 |
| Q5, B4: undo after an incomplete safety backup | `captured_snapshot(..., complete=False)` only for a backup whose `source` is `restore-pre` | 3.7 | section 6 B4 |
| B5: keep the newest load's safety backup | One more protected job id per lab, built with `runner.py` | 3.7 | section 6 B5 |
| Q6: a load that changed nothing | The chip keeps what it showed; the banner and the panel carry the failure | 3.7, 7.1 | 5.2, 5.3 |
| Q7: the job window's vocabulary | Kept; only wording that names the removed tab changes, and one button is added | 3.7, 7.2 | 5.3, section 6, section 10 |
| Q8: another lab's saves | Out of the Load panel, folded in All versions | 3.7 | 2.2 |

---

## 15. What a reviewer should attack

1. **The acknowledgement.** That no path reaches `POST …/restore` without the person pressing the red
   button of a confirmation built from a finished preflight: retry, undo, **Load this backup…**, the
   drawer's Load, a double click, a re-render during the click, Enter in the minutes field.
2. **The review's life (L1).** A stale `loadReview` after switching labs, after closing the panel,
   after a second `loadChoose` while the first preflight is still out; the drawer's **Back** showing a
   confirmation of another lab or of a review that was cleared; the drawer holding a review for ever.
3. **Reviewed bytes are applied bytes.** Folder sources must carry the commit in the submit and in a
   retry; a row's commit must be read exactly; an undo must name the exact backup job; a retry must
   read the same repository.
4. **Outcome wording.** Every status against section 5.1: `Kept previous` for anything but
   `rolled_back`; `uncertain` or `interrupted` softened anywhere (chip, toast, sentence, name);
   `Loaded` shown before verification; the chip count rounding up; the toast firing for a job that is
   not `succeeded`.
5. **The effective load (O2, K1, K6).** A device interrupted before the change taken for unknown, or
   one awaiting its read-back taken for unchanged; a failed load hiding an earlier good one; `Running
   X` surviving a redeploy, a destroy or a design apply; the capped `operations` list letting it come
   back (section 7); jobs stored before stages existed, whose `rollback_expected` and timeline-less
   `interrupted` targets are not unknown under DESIGN.md 7.1.
6. **The mandatory backup and Undo.** That Undo never bypasses the new load's own safety backup; that
   B4 cannot let a Git save or a non-`restore-pre` source accept an incomplete capture; that B5 cannot
   pin unbounded records; that Undo and **Load this backup…** are not offered when the backup cannot
   be read.
7. **Confirmation after management was proven.** Nothing in this slice touches it; check that no
   backend addition (B2, B3, the `repository` key) adds a code path into `_apply_one`, `_settle` or a
   driver, and that `restore.py` still names no NOS command.
8. **The list's eligibility preview (B2)** drifting from `map_targets`: a row promising `4 devices`
   that the preflight then refuses, or the reverse.
9. **The summaries (B1).** Input surface (none beyond the binding), output shape (no file contents,
   no configuration text), the bounds of review F10 on a repository with thousands of files, behaviour
   on a hostile `manifest.json`.
10. **Reading through a registration (Q3).** That `repository` is checked against the helper's own
    `list`; that a lab can read only repositories of its own VM; that nothing on this path writes,
    registers or binds; that HEAD never comes from `status` there.
11. **The topology line** claiming a difference for a file that differs only in bytes, or staying
    silent for a real one; "View its topology" ever offering a change to the lab (D10).
12. **Chip timing.** A save that completes while a load's follow-up check is still running; clock
    formats (`finished` strings against Git epoch seconds); a restart read-back job, whose `finished`
    is set at restart (`restore.py:271`), being taken for a finished load.
13. **Disabled states.** The Load button disabled for anything but a running load; the red **Load**
    enabled during a save; every disabled control (a device row, Undo, a `View only` row) showing its
    reason as text and, where one exists, the action that clears it.
14. **Secrets and logs.** No new field carries configuration text; `source.topology` and the states
    route are counts, names and booleans; the differences drawer shows only the preflight's already
    masked `diff`.
15. **Cross-lab loads (Q2)** if the owner widens the matching.
