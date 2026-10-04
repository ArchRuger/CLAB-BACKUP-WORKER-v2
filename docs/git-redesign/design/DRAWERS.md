# Drawers, the folder chooser, "Save as a lab state…" and the end of the Progress tab

Design slice of the Git save and load redesign ([PROMPT.md](../PROMPT.md) 5.3 step 4, 5.5, 5.7, 5.8, 5.11,
6.2, 6.3). Written against `main` at 1.30.60 on 2026-10-04. Nothing in this file was built or run: it is a
specification read off the code. Every citation is a path below `clab-backup-ui/` with a line number of
that checkout.

Scope. This file owns the three drawers, the folder chooser as an interface, "Save as a lab state…" and
the removal of the Progress tab. It does not own the header chip and its panels, the save flow or the Load
flow (other designers), nor any folder rule or backend decision (the lead). Where this design needs
something from those slices it says **NEEDS (backend)** or **NEEDS (header)** / **NEEDS (load)** and
names the smallest thing that would do.

Contents: 0 shared mechanics · 1 What changed · 2 All versions · 3 Save settings · 4 folder chooser ·
5 Save as a lab state · 6 removing the Progress tab · 7 tests · 8 wording, files, friction, assumptions,
open questions, what to attack.

---

## 0. Shared mechanics

### 0.1 One drawer element

One static element at page level in `index.html`, beside the device drawer (`app/static/index.html:335`),
never inside a tab panel (the reason is the one recorded for `#design-apply-dialog`,
`app/static/index.html:294`: a modal inside a hidden panel shows nothing):

```html
<dialog id="save-drawer" class="drawer save-drawer" data-lab-dialog aria-labelledby="save-drawer-title">
  <div class="drawer-head">
    <div class="dialog-head">
      <button type="button" class="save-quiet save-back" id="save-drawer-back" hidden>Back</button>
      <h2 id="save-drawer-title"></h2>
      <button type="button" class="icon-button close" id="save-drawer-close" aria-label="Close"><svg class="icon" width="16" height="16" aria-hidden="true"><use href="#i-close"></use></svg></button>
    </div>
    <p class="drawer-meta" id="save-drawer-meta"></p>
    <div class="save-row" id="save-drawer-actions" hidden></div>
  </div>
  <div class="drawer-content" id="save-drawer-content"></div>
</dialog>
```

- It is one `<dialog>` with one content at a time (`changes`, `versions`, `settings`, `chooser`), so
  "only one panel or drawer is open at a time" (PROMPT 5.1) is true by construction, not by bookkeeping.
- `dialog.drawer` already gives the right-hand sheet, the sticky head and the light backdrop
  (`app/static/style.css:1521-1556`). `data-lab-dialog` makes it close when the page moves to another lab
  or Home (`closeLabDialogs`, `app/static/shell.js:54-58`): a drawer never acts on a lab it was not opened
  for.
- Opened with `showModal()` like every dialog here (`app/static/operations.js:21`,
  `app/static/app.js:421`). The head and the two buttons are static; only text, `hidden` and the content
  change (addendum J3: header, banner, tabs and menus are never re-rendered with `innerHTML`).
- The content is written with `setMarkup` (`app/static/app.js:35`), so the 4 s poll costs nothing when
  nothing changed and never moves focus or the scroll position.

### 0.2 State and API (new file `app/static/save-drawers.js`)

```js
const saveDrawer={kind:'',lab:'',back:null,request:0,opener:null,openRow:'',data:null,draft:null};
function saveDrawerOpen(kind,options={})   // 'changes' | 'versions' | 'settings' | 'chooser'
function saveDrawerBack()                  // one level: different/files → versions, chooser → settings
function saveDrawerClose()
function saveDrawerRender()                // pure markup → setMarkup; called by render() on every poll
function saveDrawerRefresh(force)          // refetch what the open kind shows; replaces gitShowRepository(true)
```

- `saveDrawerOpen` closes the header panels first (`closeMenus()`, `app/static/shell.js:71-76`), records
  the opener (`document.activeElement`), fills the head, shows the dialog and moves focus to the heading
  (the existing rule in `gitFocusDialog`, `app/static/git-progress.js:98-104`: the destination's heading,
  never the close button).
- **Escape** goes back one level when `saveDrawer.back` is set (the dialog's own `cancel` event,
  `preventDefault`), otherwise closes. The close button and a click on the backdrop always close.
- On close, focus returns to the opener when it is still visible, otherwise to the chip button
  (`#save-chip`, **NEEDS (header)**: the id of the chip button).
- Listeners sit on the dialog element only (one delegated `click`, `input`, `keydown`, `cancel`,
  `close`). No `window`, `document`, `location`, `history` or storage listener is added outside
  `shell.js` (PROMPT 5.1; addendum J1). The wiring block is guarded like today's
  (`if(typeof $==='function'&&$('save-drawer'))`, the pattern of `app/static/git-progress.js:783`), so
  the file loads in Node with no DOM.
- `saveDrawer.openRow`, the chooser's selection and the settings draft live in this object, not in the
  DOM, so a re-render on the poll keeps them.
- A polite live region inside the drawer (`<p class="sr-only" role="status" aria-live="polite"
  id="save-drawer-status">`) announces what a click did (`Uploading…`, `Folder BGP/final selected`,
  `Uploaded to github.com.`). The toast stays the visible message.

### 0.3 Interfaces assumed from the other slices

| Name | Owner | What this slice needs from it |
|---|---|---|
| `saveOpenPanel(kind)` | header | Opens the chip panel (`'status'`, default) or the Load panel (`'load'`) on the current tab. Used by the router (6.2) and by every text that used to say "under Progress". |
| `saveChipState(lab, state)` in `status.js` | header | The one status function of PROMPT 5.2. The drawers read `waiting` (the saves that wait for upload) from it, so the chip, the home card and a drawer can never disagree. |
| `gitReviewJob(job, review)` | save flow | The single sender of `{push: true, reviewed: true}` (section 1.4). |
| `saveChangeSummary(review)` | save flow | The sentence parts (`ceos and xrv9k`, `19 lines added, 1 removed`, `The topology changed.`) from one review answer; the drawer's meta line calls the same function as the panel's sentence. |
| `loadState(labId, source, name)` | load | Starts the Load confirmation (G03) for a source `{type:'folder',path}` or `{type:'git',commit,path}`: today's `restoreFromFolder` and `restoreFromVersion` (`app/static/restore.js:141-160`). |

---

## 1. "What changed" drawer (PROMPT 5.3 step 4, board F04)

### 1.1 What feeds it today

- The review dialog `git-diff-dialog` is built by `gitReviewJob` (`app/static/git-progress.js:654-673`)
  from `POST /api/labs/{id}/git/compare {job_id}` (`app/git_progress.py:1531-1567`).
- The answer is `{files, also_sends, also_sends_other_labs, also_sends_kept, upload_blocked?}`
  (`app/git_progress.py:1563-1566`). Each file is `{name, status, before, after, diff, label,
  renamed_from?}`: `annotated_compare` adds the real line diff (`textdiff.unified`) and a label
  (`app/git_progress.py:144-151`) and folds a `.set`/`.cfg` rename into one changed file
  (`pair_renamed_files`, `app/git_progress.py:108-142`).
- The markup is `gitFilesDiffMarkup(files, oldLabel, newLabel)` (`app/static/git-progress.js:134-137`),
  a thin adapter over `diffFileMarkup` (`app/static/diff-view.js:48-51`), which renders one
  `<details class="diff-file">` per file with `diffMarkup`'s table (`app/static/diff-view.js:27-40`).
- What the helper compares: `compare` reads the save's folder at its commit and at the parent commit and
  returns every file whose bytes differ (`app/host_git.py:729-749`). "Every file" there means every file
  the manifest references: the human configuration, the restore artifact of the same device, and the
  topology and map entries (`read_version` reads `item.path` and `item.restore_artifact` for every
  manifest entry, `app/host_git.py:721-725`; the topology and the map are manifest entries of their own
  kind, `app/git_progress.py:433-462`). It never returns `manifest.json` (`read_one` refuses that name,
  `app/host_git.py:715`).
- What the upload really sends: the commit's `changed_files`, the repository-relative paths the helper
  wrote, `manifest.json` included (`app/host_git.py:635-643`, `:656`), public on the job (`PUBLIC_JOB`,
  `app/git_progress.py:40-42`). A checkpoint save writes `latest` and its checkpoint folder in one commit
  (`folders = [self.scope('latest')]` plus the target, `app/host_git.py:593`), while `compare` reads
  only the job's `snapshot_path` (`app/host_git.py:735`).
- An upload also carries the earlier commits still waiting in the checkout: `also_sends` and its two
  companions (`app/git_progress.py:1538-1558`), worded in today's review
  (`app/static/git-progress.js:657-668`).

So today's review data is complete for the configuration text and incomplete as a list of files: it
omits `manifest.json`, the second folder of a checkpoint save, and it shows a device's restore artifact
as a second changed file.

### 1.2 The guarantee "every file the upload would send is visible"

A pure function accounts for every path; nothing is left to a naming habit.

```js
// → {entries:[{role:'device'|'topology'|'map'|'other', title, file, artifact, paths:[…]}], rest:[path…]}
function saveChangeAccount(job, review)
```

1. Every file of `review.files` becomes, or joins, exactly one entry: a device's human file opens the
   entry, its restore artifact joins it (never a second entry: PROMPT 5.3 step 3), the topology file and
   the map get one entry each, anything else is `other`.
2. Each entry lists the repository paths it stands for: `job.snapshot_path + '/' + name` (and
   `renamed_from` when present).
3. `rest` is `job.changed_files` minus every path an entry stands for. It is rendered, always, as a plain
   list under the heading **Also in this upload** (`manifest.json` reads `Save details (which devices,
   when they were saved)`, the wording the folder listing uses today, `app/static/git-places.js:146`;
   the copies a checkpoint save writes read `<path> (the same file, kept in the checkpoint)`).
4. The invariant, asserted in a Node test: the union of all `entries[].paths` and `rest` equals
   `job.changed_files`, for a latest save, a checkpoint save, a baseline, a lab state, a renamed Junos
   file, a removed device and a save that changed only the map.
5. The earlier saves the upload carries along are stated under the head with today's sentence, from
   `also_sends`, `also_sends_other_labs` and `also_sends_kept`.

To group files by role the drawer must know which file is whose. Today the compare answer carries only
names. Guessing from suffixes (`.eoscfg`, `.clab.yml`) would be a second, weaker source.

**NEEDS (backend) N1.** The job compare answer gives each file `role` (`device`, `restore`, `topology`,
`map`, `other`) and, for `device` and `restore`, `node` (the device's short name), read from the save's
manifest (the after manifest; the before manifest for a removed file). A file without a role is shown as
`other`: still visible, so a missing role can never hide a file.

**NEEDS (backend) N2.** `upload_blocked` is a sentence today (`sibling_refusal`,
`app/git_progress.py:283-292`, which ends in "Open <lab> › Progress"). The drawer needs
`upload_blocked: {lab_id, lab_name, message}` so the action that clears it can be a button.

### 1.3 Markup

Head (static slots filled; classes are the shared base names plus this slice's, see 8.2):

```html
<h2 id="save-drawer-title">What changed</h2>
<p class="drawer-meta" id="save-drawer-meta">ceos and xrv9k · 19 lines added, 1 removed · not uploaded yet</p>
<div class="save-row" id="save-drawer-actions">
  <button type="button" class="button primary" data-save-action="upload">Upload</button>
  <button type="button" class="save-quiet" data-save-action="not-now">Not now</button>
  <button type="button" class="save-quiet" data-save-action="files">View files</button>
</div>
```

Content:

```html
<p class="save-note">Saved files can contain passwords or keys.</p>
<p class="save-note" id="save-changes-also">Uploading also sends 2 earlier saves that are still waiting on the VM, 1 of them from another lab in this repository.</p>
<details class="diff-file" open><summary>ceos <span class="badge">changed</span></summary>
  <div class="diff-body">
    …diffMarkup(file.diff,{oldLabel:'Before this save',newLabel:'This save'})…
    <details class="save-also"><summary>Also uploaded for ceos: ceos.eoscfg, the file Load uses</summary>…diffMarkup(artifact.diff)…</details>
  </div>
</details>
<details class="diff-file" open><summary>Topology file <span class="badge">changed</span></summary>…</details>
<details class="diff-file" open><summary>Map <span class="badge">changed</span></summary>…</details>
<h3 class="save-h">Also in this upload</h3>
<ul class="save-list save-plain"><li><code>restore-square/latest/manifest.json</code> Save details (which devices, when they were saved)</li></ul>
```

- A device entry is titled with the device's name, the file name follows in the summary as muted text
  (`ceos <small>ceos.cfg</small>`); the topology file and the map are titled in words with the file name
  the same way. The diff itself is `diffMarkup` unchanged, through `gitFilesDiffMarkup` for the human
  file, so the cut-line, truncation and "counts in the part shown" wording stay
  (`app/static/diff-view.js:26-39`).
- A device whose human file is unchanged while its restore artifact changed still gets one entry: the
  body says `The configuration text is the same. The file Load uses changed.` and the artifact's diff is
  open. It counts as one device.
- A removed device (`status: 'removed'`) is an entry with the badge `removed`.
- A folder move shows no diff, with today's lead sentence (`app/static/git-progress.js:666-668`); its
  moved files appear under **Also in this upload** from `changed_files`.
- A design export (`job.kind==='design'`) uses the same drawer titled `What this design export changed`
  (today's separate title, `app/static/git-progress.js:665`, test at
  `tests/test_git_progress_ui.js:536`).
- A save that is already uploaded, opened from All versions or from Details: the same drawer without
  the action row; the meta line ends `uploaded to github.com`.

### 1.4 Upload and Not now: one function

Rule kept: `gitReviewJob` is the only sender of `{push: true, reviewed: true}` (CLAUDE.md "Save
progress"; PROMPT 7.5). Today it both builds the dialog and sends (`app/static/git-progress.js:672`). It
is split so the panel and the drawer cannot each grow a sender:

```js
async function gitReviewData(job)           // POST /git/compare {job_id}; cached per job id + commit
async function gitReviewJob(job, review)    // the only sender; refuses without a review of this very job
```

`gitReviewJob(job, review)` throws when `review.job_id!==job.id`, when `review.upload_blocked` is set,
or when the job no longer needs an upload; otherwise it posts
`/git/jobs/{id}/retry {push:true, reviewed:true}`, remembers the answer (`gitRememberJob`,
`app/static/git-progress.js:611-614`) and refreshes. The panel's **Upload** and the drawer's **Upload**
both call it with the review object their sentence was rendered from. The existing source-level test
that only one place sends `reviewed: true` (`tests/test_git_progress_ui.js:170`) keeps its claim.

- **Upload**: the button reads `Uploading…` and is disabled with that text as its reason; on success the
  drawer closes and the header shows the toast; on failure the drawer stays open, a
  `<p class="form-error" role="alert">` under the action row says why, and the chip turns *Failed*.
- **Upload blocked** (another lab's unreviewed save, N2): Upload is disabled, the reason is visible
  text above it and the clearing action is beside it: `<Other lab> has a save that must be uploaded
  first.` **Open <Other lab>** (`selectLab(id)` then `saveOpenPanel()`).
- **Not now**: closes the drawer; toast `Not uploaded. The save stays on the lab VM.`; the chip stays
  *Waiting* (today's "Not now — keep it on the VM", `app/static/git-progress.js:668`, `:671`).
- **View files**: today's "Open the full saved version" (`app/static/git-progress.js:670`), the files
  view of 2.4 for this save's commit and path.

States: loading (`Reading what changed…`, `role="status"`); error (the manager's sentence, **Try
again**; a save from before a folder change answers `Reconnect the original repository to review this
save.`, `app/git_progress.py:1538`: shown as is with **Details** → the job window); nothing changed (the
drawer is not reachable: the panel says `Nothing changed since your last save.`).

---

## 2. All versions drawer (PROMPT 5.7, board F11)

### 2.1 Today's data and functions

| Piece | Today | Citation |
|---|---|---|
| Grouping | `gitVersionGroups(id, context, model, tree, history)` → `latest`, `checkpoints`, `baseline`, `reference`, `others`, `elsewhere` | `app/static/git-progress.js:321-368` |
| Source of rows | the repository tree (`GET /api/git/repositories/{binding}/tree`: files, lab folders with their lab, planned folders, `saved`, `head`) through `gitTreeModel`; a folder is a saved state when it holds `manifest.json` | `app/git_progress.py:1168-1177`, `app/static/git-places.js:48-71` |
| Fallback when the tree did not load | `GET /api/labs/{id}/git/history` `versions[]`, labelled by `version_label` (`<folder> · latest`, `checkpoint · <name>`) | `app/git_progress.py:166-176`, `:1498-1506`, `app/static/git-progress.js:360-366` |
| Names of other folders | `savedVersionName(folder)` (`final` → "Final state (instructor)", `start` → "Starting state") | `app/static/status.js:171-177` |
| Whose folder | `gitVersionsOwner` (deepest lab folder at or above a path; a root lab folder owns only the root) | `app/static/git-progress.js:317` |
| Row and list | `gitVersionRowMarkup`, `gitRenderVersions` (headings Latest, Checkpoints, Baseline, Instructor and reference versions, folded Other labs, folded Elsewhere) | `app/static/git-progress.js:369-397` |
| Row actions | `gitVersionAction`: view, compare, apply | `app/static/git-progress.js:398-403` |
| View dialog | `gitViewVersion`: `POST /git/version` → manifest, every file's text, `restore_supported`; buttons Apply, Compare, Download (ZIP) | `app/static/git-progress.js:749-764`, `app/git_progress.py:1514-1519` |
| Compare | `gitCompareVersion`: `POST /git/compare {commit, path}`, against the lab's own `latest` at HEAD | `app/static/git-progress.js:743-748`, `app/git_progress.py:1568-1577` |
| Download | `POST /git/version/download` (manifest and every file as a ZIP) | `app/static/git-progress.js:763`, `app/git_progress.py:1521-1529` |
| Set baseline | `gitSaveOptions('baseline')`: pick a complete capture (`gitCompleteBackups`), tick "Replace the current baseline", send `replace_baseline` and `expected_baseline` | `app/static/git-progress.js:585-609`, `:67-70` |
| Full history | `gitHistory` (saved versions and commits) and `gitOpenCommit` | `app/static/git-progress.js:724-742` |
| Recent saves | `gitRenderSaves`, `gitSavesAction` (Open, Review and upload… / Upload now, Keep snapshot only) | `app/static/git-progress.js:406-422` |

### 2.2 Groups

| New group | Fed by | Notes |
|---|---|---|
| **Your saves** | New: the lab's finished saves to `latest`, newest first, from the lab's jobs (`gitLabJobs`, `app/static/git-progress.js:19-22`): `target==='latest'`, a commit, a non-empty `changed_files` (an unchanged save reuses HEAD and is not a version of its own, `app/static/git-progress.js:733-734`). Each is opened by `{commit: job.commit, path: '/'+job.snapshot_path}`, the way `gitOpenCommit` opens one today (`app/static/git-progress.js:738`). Without any job (jobs are capped at 200, `app/git_progress.py:309-313`, `:295`) the one row of today's `groups.latest` stands in. | Today's "Latest" is a single row; F11 shows several saves. The first five show, **Show older saves** shows the rest; **Full history…** reaches every commit. The name is the save's name (`job.note`, automatic or typed after D2). A save that waits for upload carries `Not uploaded yet` as its second line. |
| **Checkpoints** | `groups.checkpoints` | The star icon of the board (`#i-star`). A design export is a checkpoint of another kind: see 2.5. |
| **Starting point** | `groups.baseline` | Row name `Starting configuration`. Hidden when the lab has none (today's behaviour, `app/static/git-progress.js:391`). |
| **Lab states** | `groups.reference`, named by the one naming function (open question Q3) | Heading carries the quiet action **Save as a lab state…**. |
| folded **Other labs in this repository (n)** | `groups.others` | Named by the owning lab, as today (`app/static/git-progress.js:356`). |
| folded **Everything else in this repository (n)** | `groups.elsewhere` | Today's "Elsewhere in this repository". |
| folded **Save activity (n)** | New home for Recent saves: every job of the lab that is not a row above (failed, a device could not be read, interrupted, kept on the VM, repository updates, folder moves) | Each row opens today's save window (`gitShowJob`, `app/static/git-progress.js:626-632`), which keeps its retry and keep-on-the-VM actions. Without this fold a failed attempt older than the newest one would have no home. |

One grouping function feeds the Load panel and this drawer. `gitVersionGroups` stays in
`git-progress.js` (its tests load that file, `tests/test_git_progress_ui.js:294-365`) and gains the
`saves` group; nothing else about its grouping changes in this slice. Whether "Lab states" should stop
depending on distance from the lab's folder (`belowParent`, `app/static/git-progress.js:342-346`) is a
folder-model question for the lead (Q3); the drawer renders whatever the function returns.

What is missing today:

1. **A list of the lab's saves** (above): present as jobs and commits, never shown as versions.
2. **Coverage and loadability per row.** The tree knows only that a folder holds `manifest.json`
   (`app/static/git-places.js:64`); whether a state can be loaded, on how many devices, and whether it is
   a design export is known only after `/git/version` (`restore_supported`, `restore_nodes`,
   `app/git_progress.py:1517-1519`). Today a checkpoint row offers Apply whenever the folder is a
   snapshot (`app/static/git-progress.js:332`), a design export included.
   **NEEDS (backend) N3**: one list of saved states per repository, each
   `{path, commit, name, group, lab, kind ('capture'|'design'), devices:[…], loadable:[…], files, saved_at}`,
   in the tree answer or beside it. PROMPT 7.6 already asks for the device coverage; `group` and `name`
   coming from the same answer is what keeps the Load panel, this drawer and the chooser's marks
   (`Lab state: Start`) from disagreeing.
3. **A lab without a save location.** `history`, `version`, `download` and `compare` all start with
   `self.binding(lab_id)` (`app/git_progress.py:1500`, `:1509`, `:1570`), so a lab that never saved can
   neither list nor view the course's states (PROMPT 5.4 step 8, parity gate).
   **NEEDS (backend) N4**: view, download and list by repository for a lab without a binding.
4. **Keep as a checkpoint** from an existing save (PROMPT 7.4) and a rename route (PROMPT 7.3).
5. **When a state was saved**: the tree gives a time only for the lab's own `latest` and `baseline`
   (`tree.saved`, `app/static/git-progress.js:330`, `:334`); other rows show the file count, as the
   board does (`9 files`). N3's `saved_at` would let every row show a time.

### 2.3 Markup

```html
<h2 id="save-drawer-title">All versions</h2>
<p class="drawer-meta">Everything saved for restore-square. Choose one to load it.</p>

<h3 class="save-h">Your saves</h3>
<ul class="save-list">
  <li><button type="button" class="save-item" aria-expanded="false" aria-controls="save-row-1" data-save-row="…"><span>Interface descriptions cleaned up</span><span class="save-when">21 minutes ago</span></button></li>
  <li class="save-open"><button type="button" class="save-item" aria-expanded="true" aria-controls="save-row-2" data-save-row="…"><span>Point-to-point OSPF on all four links</span><span class="save-when">47 minutes ago</span></button>
    <div id="save-row-2">
      <p>Your save · 4 devices · topology and map included</p>
      <div class="save-row">
        <button type="button" class="button secondary" data-save-action="load">Load this state…</button>
        <button type="button" class="save-quiet" data-save-action="different">See what’s different</button>
        <button type="button" class="save-quiet" data-save-action="files">View files</button>
        <button type="button" class="save-quiet" data-save-action="zip">Download ZIP</button>
      </div>
      <div class="save-row">
        <button type="button" class="save-quiet" data-save-action="checkpoint">Keep as a checkpoint</button>
        <button type="button" class="save-quiet" data-save-action="baseline">Use as starting point…</button>
      </div>
    </div></li>
</ul>
<h3 class="save-h">Checkpoints</h3> …
<h3 class="save-h">Starting point</h3> …
<div class="save-h-row"><h3 class="save-h">Lab states</h3><button type="button" class="save-quiet" data-save-action="state">Save as a lab state…</button></div> …
<details class="save-fold"><summary>Other labs in this repository (3)</summary>…</details>
<details class="save-fold"><summary>Everything else in this repository (2)</summary>…</details>
<details class="save-fold"><summary>Save activity (4)</summary>…</details>
<div class="save-foot"><button type="button" class="save-quiet" data-save-action="history">Full history…</button><button type="button" class="save-quiet" data-save-action="browse">Browse the repository…</button></div>
```

- A row is a real button with `aria-expanded`; Enter and Space open it in place. One row is open at a
  time; which one is `saveDrawer.openRow`, so the poll keeps it open. Tab order is the document order;
  no roving focus is needed in a plain list.
- The line under an open row is built from one answer (N3): `Your save · 4 devices`, `Lab state · covers
  2 of your 4 devices`, `From OSPF-lab · 4 devices`, `Checkpoint · 4 devices`.
- Empty groups: Your saves `No saves yet. Save makes the first one.`; Checkpoints `No checkpoints yet.
  Keep a save as a checkpoint to hold on to it.`; Lab states `No lab states in this repository yet.`
  (with **Save as a lab state…** beside the heading). Starting point and the folds are omitted when empty.
- Loading: `Loading the saved versions…` (`role="status"`). The VM did not answer: today's blank state
  and its rule that a failed read is never worded as "not saved yet"
  (`app/static/git-progress.js:230`, `:243-248`): `The saved versions could not be loaded.` with the
  manager's sentence, **Try again** and, for a network failure, **Check the VM connection…**.
- No save location and no repository: `This lab has not been saved yet.` with **Save** (the header's
  first-save action). With a repository on the VM the Lab states group still lists (needs N4).

### 2.4 Actions

| Action | On | Does | Today |
|---|---|---|---|
| **Load this state…** | every loadable row | closes the drawer, then `loadState(lab, source, name)`; source is `{type:'folder', path}` for a folder at HEAD and `{type:'git', commit, path}` for an older save | `restoreFromFolder` from the list (`app/static/git-progress.js:401`), `restoreFromVersion` from the view dialog (`:761`) |
| | a row that cannot be loaded | the button is disabled and the reason is the visible second line of the row: `View only: saved without the files needed to load it` (PROMPT 5.4 step 2); the clearing action is **View files** beside it | today's sentence in the view dialog (`app/static/git-progress.js:757`) |
| **See what’s different** | every row except the newest own save; omitted when the lab has no save of its own (there is nothing to compare with) | the drawer shows the difference with **Back**; title `Different from your latest save`, lead `How <name> differs from the last save of <lab>. To see what would change on the devices, choose Load this state…: the devices are compared before anything is loaded.`; body `gitFilesDiffMarkup(files,'This version','Your latest save')` | `gitCompareVersion`. The wording stays true to what the backend compares (addendum D and H7: never "compare with current") |
| **View files** | every row | the drawer shows the files with **Back**: three groups read off the returned manifest (`node`, `kind`, `restore_artifact`): **Devices**, **Topology and map**, folded **Files Load uses** and **Save details** (the manifest JSON). A state saved before the topology travelled says `Saved without its topology file.` | `gitViewVersion` (files as one flat list, manifest under "Technical details") |
| **Download ZIP** | every row | unchanged request and file name | `app/static/git-progress.js:763` |
| **Keep as a checkpoint** | own saves whose capture the manager still keeps | opens one field inside the row (`Checkpoint name`, prefilled from the save's name, corrected as typed by `gitCheckpointName`, `app/static/git-progress.js:584`, with `Saved as: <name>`, `:599`) and **Keep**; sends the save route's `backup_job_id` with `target:'checkpoint'` (PROMPT 7.4) | `Create checkpoint…` recaptured the devices (`app/static/git-progress.js:585-609`) |
| | capture no longer kept | disabled; visible reason `The files of this save are no longer kept by the manager. Save again, then keep that save.` with **Save** beside it. Whether it is kept is known in the page: `job.backup_job_id` is among the complete captures of `state.jobs` (`gitCompleteBackups`) | new |
| **Use as starting point…** | own saves with a complete capture | a review inside the row: `Make this save the starting point of <lab>? No device is read or changed.`; when one exists also `It replaces the current starting point, saved <when>. The previous one stays in the history.`; **Use as starting point** or **Replace the starting point**, and **Cancel**. Sends `{target:'baseline', backup_job_id, replace_baseline, expected_baseline}` exactly as today; `expected_baseline` is `repository_status.baseline_revision` | `gitSaveOptions('baseline')`. The replace tick box becomes the named button; the server check (`expected_baseline`) is unchanged |
| **Save as a lab state…** | Lab states heading | section 5 | new |
| **Full history…** | foot | `gitHistory` unchanged, retitled `Full history` | `app/static/git-progress.js:724-730` |
| **Browse the repository…** | foot | the folder chooser in `browse` mode (section 4.2) | the folder browser with its per-folder Apply (`app/static/git-progress.js:773`, `:291`) |
| a waiting save's row | Your saves | first action is **Upload…** (opens What changed for that save) | Recent saves "Review and upload…" (`app/static/git-progress.js:419`) |
| a Save activity row | fold | **Details** → `gitShowJob` | Recent saves "Open" (`app/static/git-progress.js:418`) |

Keep as a checkpoint and Use as starting point both create a commit, so both end in the same upload
sentence as any save (chip *Waiting*).

### 2.5 A design export

A design export is a save of kind `design` into its own checkpoint folder
(`app/git_progress.py:1383-1386`), its manifest marked `kind: network-design`
(`app/host_git.py:588-592`); it is never a restore source (`app/static/git-progress.js:615-617`). Its
row sits under Checkpoints with the second line `Design plan: view and download only` and offers **View
files** and **Download ZIP** only. Until N3 gives `kind`, the page recognises it from the lab's own jobs
(`job.kind==='design'` with the same `checkpoint`); a design export whose job is gone would show a
disabled Load with the view-only reason once `/git/version` was read. N3 removes that gap.

---

## 3. Save settings drawer (PROMPT 5.8, board F15)

### 3.1 Control map

| Control (F15) | Today | Citation | Change |
|---|---|---|---|
| Destination line `repo › folder › latest/` | the Save location card's `.git-destination-line` | `app/static/git-progress.js:281` | moves unchanged |
| Legacy notice (a lab folder named like a saved state) | `gitLegacyDestinationNotice` under the line | `app/static/git-progress.js:38-46`, `:279-281` | moves; its instruction is reworded (8.1) |
| **Change folder…** | `<details id="git-change-folder">` holding the select `#git-binding-id` and the folder browser | `app/static/git-progress.js:265-269` | becomes a button that shows the chooser (section 4) in the drawer, with **Back** |
| **Use a different repository…** | `gitSwitchRepository`: a dialog listing the VM's lab folders as `repo › prefix` | `app/static/git-progress.js:477-483` | same dialog; it lists repositories (one per checkout path, as `gitFirstSave` already does, `:513`) and continues in the chooser on the chosen one. With no other repository it says so and offers Connect by URL, as today |
| **Connect by URL…** | `gitConnectByUrl` | `app/static/git-progress.js:485-504` | same dialog and request; the folder field is the chooser's path field (4.4) and the tick box becomes the passwords sentence beside the button, which sends `acknowledge: true` (D5) |
| Devices included in every save | `fieldset.git-node-scope`, the "can’t be included yet" sentence, the "save stops and nothing is written" sentence | `app/static/git-progress.js:271-273` | moves unchanged (`.git-node-scope`, `app/static/style.css:1992-2005`) |
| "Nothing is uploaded without you…" | form help | `app/static/git-progress.js:274` | retired: the upload sentence says it at the moment it matters |
| Exposure tick box | `#git-exposure`, required when the destination changed | `app/static/git-progress.js:275`, `:294`, `:299` | retired with D5; the sentence `Saved files can contain passwords or keys.` stands beside **Save here** in the chooser, where the destination changes |
| Git details | three places: "Git repo details" (`:278`), "Registration details" (`:276`), and the static card "Advanced repository details" with Refresh status, Update from the repository, Disconnect… (`app/static/index.html:147`, filled by `gitRenderAdvanced`, `app/static/git-progress.js:423-431`) | | one fold **Git details**: the same `dl.kv` (Uploads go to, Branch, VM account, Checkout path, Status, the account sentence), then **Refresh status** and **Update from the repository**. The text `Verified push destination: <code>url</code>` stays (addendum H4, test at `tests/test_git_progress_ui.js:101`) |
| **Refresh status** | `#git-repository-refresh` → `gitShowRepository(true)` | `app/static/git-progress.js:786` | → `saveDrawerRefresh(true)`: rereads `GET /api/labs/{id}/git` (`app/git_progress.py:1120-1133`) |
| **Update from the repository** | `gitUpdateRemote` (confirmation dialog, then `POST /git/update`) | `app/static/git-progress.js:714-718` | moves unchanged |
| **Disconnect this lab…** | `gitUnlink` | `app/static/git-progress.js:719-723` | same dialog; the waiting-save notice becomes two buttons (3.3) |
| **Save settings** | the form's submit: `PUT /api/labs/{id}/git {binding_id, node_names}` | `app/static/git-progress.js:296-302` | same request with the lab's current `binding_id`; only the devices can change here |
| "Saving to Git is not possible right now" | `#git-problem` on the status card | `app/static/index.html:142`, `app/static/git-progress.js:205` | the chip's *Can't save* (header); the drawer repeats the reason as a `.banner.warn` above Save location and as Status in Git details |

The mockup shows three folds ("Git repo details", "Registration details", "Advanced repository
details"); PROMPT 5.8 says "the folded Git details". One fold is the design: three were an accident of
the tab's history, and G4 asks to hide what can be hidden.

### 3.2 Markup

```html
<h2 id="save-drawer-title">Save settings</h2>
<p class="drawer-meta">Where restore-square saves, and which devices each save includes.</p>

<h3 class="save-h">Save location</h3>
<p class="git-destination-line"><code>CLAB-MNGR-DEV-LLM</code><span aria-hidden="true">›</span><code>restore-square/qa-1-30-37</code><span aria-hidden="true">›</span><code>latest/</code></p>
<div class="actions">
  <button type="button" class="button secondary small" data-save-action="folder">Change folder…</button>
  <button type="button" class="button secondary small" data-git-repo-action="switch">Use a different repository…</button>
  <button type="button" class="button secondary small" data-git-repo-action="connect">Connect by URL…</button>
</div>

<h3 class="save-h">Devices included in every save</h3>
<fieldset class="git-node-scope"><legend class="sr-only">Devices included in every save</legend>
  <label class="checkbox-label"><input type="checkbox" name="git-node" value="ceos" checked> <span>ceos <small>EOS</small></span></label> …
</fieldset>
<p class="form-help">clab-restore-square-host1 can’t be included yet — configuration saves aren’t supported for its platform.</p>
<p class="form-help">If an included device can’t be reached, the save stops and nothing is written — an older configuration is never saved in its place.</p>

<details class="save-fold" id="save-git-details"><summary>Git details</summary>
  <dl class="kv"><dt>Uploads go to</dt><dd id="git-advanced-push-url">…</dd><dt>Branch</dt><dd id="git-advanced-branch">…</dd><dt>VM account</dt><dd id="git-advanced-owner">…</dd><dt>Checkout path</dt><dd id="git-advanced-path" class="mono">…</dd><dt>Status</dt><dd id="git-advanced-status">…</dd></dl>
  <p id="git-advanced-account" class="caption"></p>
  <div class="actions"><button type="button" class="button secondary small" data-git-repo-action="refresh">Refresh status</button><button type="button" class="button secondary small" data-git-repo-action="update">Update from the repository</button></div>
</details>

<p class="form-error" role="alert" id="save-settings-error"></p>
<div class="save-drawer-foot"><button type="button" class="link-button" data-git-repo-action="unlink">Disconnect this lab…</button><button type="button" class="button primary" data-save-action="save-settings">Save settings</button></div>
```

`data-git-repo-action` is kept on purpose: `gitRunAction` already dispatches `switch`, `connect`,
`refresh`, `update` and `unlink` (`app/static/git-progress.js:765-782`).

### 3.3 States and the two inline questions

- **Loading**: `Loading the save settings…`. **Error**: today's blank state and its Try again
  (`app/static/git-progress.js:243-248`).
- **No save location, a repository on the VM**: `This lab has no save location yet.` with **Choose a
  place…** (the chooser) and **Connect by URL…**; no devices section (the device choice is stored in the
  binding, `app/git_progress.py:1145-1146`).
- **No repository on the VM**: today's blank state with **Connect a repository by URL**, **Check
  again** and the folded administrator instruction (`app/static/git-progress.js:284`), unchanged.
- **Unticked every device**: an error under the list, `Choose at least one device to include.`
  (`app/static/git-progress.js:298`); the button is not disabled.
- **A save waits for upload, and the person changes the devices.** Today the request is refused: the
  link route runs `guard_pending` (`app/git_progress.py:1138-1139`) and answers `Finish pending Git
  saves, or choose Keep snapshot only in Git history before continuing.` (`:610`), naming a place that
  will not exist. The constraint is real (a pending save is bound to the binding's digest; stored
  bindings are never rewritten). The drawer therefore says it before the click: above the foot,
  `A save is still waiting to be uploaded. The devices can be changed once it is uploaded or kept on
  the VM only.` with **Upload…** (What changed for that save) and **Keep it on the VM only** (today's
  dismiss route, `app/static/git-progress.js:698-701`); **Save settings** is disabled while the device
  ticks differ from the stored ones, with that sentence as its visible reason. Which saves wait comes
  from the chip's status function, so the drawer cannot contradict the chip.
  **NEEDS (backend) N5**: reword the message of `guard_pending` (and of `app/discovery.py:669`), or let a
  device change proceed with the same inline choice as a folder change.
- **Disconnect with a waiting save.** Today the dialog shows a notice and the server refuses
  (`app/static/git-progress.js:721`). The dialog instead offers the two ways on: **Upload it, then
  disconnect** and **Disconnect and keep that save on the VM only** (dismiss, then unlink: two existing
  routes, no backend change). Without a waiting save the dialog is today's, with the danger button
  **Disconnect**.
- **A device was unticked whose file is already saved.** Today the next save is refused by the helper
  unless the request carries `allow_removed` (`app/host_git.py:632-633`), a tick box that lives in the
  save options dialog (`app/static/git-progress.js:595`), which D6 and 5.3 remove. The drawer says, under
  the list, `<device> is no longer included. Its saved file leaves the next save; older versions keep
  it.` and **NEEDS (header/save flow)**: the next Save sends `allow_removed: true` when the stored
  device list no longer includes a device the last save had, or the chip offers **Save without
  <device>** after the refusal. Without one of the two this is a dead end (Q4).

### 3.4 What moves unchanged

The destination line, the devices fieldset and its two sentences, the Git details values and their
ids, Refresh status, Update from the repository (dialog and request), Use a different repository… and
Connect by URL… (dialogs and requests), Disconnect (dialog and request), the request of Save settings,
and the load-error state.

---

## 4. The folder chooser (PROMPT 6.3)

### 4.1 Today's modes of `git-places.js`, and what each becomes

| # | Today | Citation | Becomes |
|---|---|---|---|
| 1 | Not connected: the browser sits under "Choose a folder for this lab"; the primary button reads **Choose this folder**; `gitUseFolder` registers the folder and preselects it in the connect form; toast "Now tick the devices…" | `app/static/git-places.js:156`; `app/static/git-progress.js:265`, `:442-448` | chooser `location` mode; **Save here** connects the lab in one request (N7). No second form. |
| 2 | Connected, same repository: **Save this lab here** → dialog "Save this lab here?" with the "Also move the N files" tick box → `POST /git/destination` | `app/static/git-places.js:156`; `app/static/git-progress.js:449-452`, `:433-439` | `location` mode; the confirmation dialog goes; the move tick box is one line in the chooser (4.5) |
| 3 | Connected, browsing another repository through the select `#git-binding-id`: behaves like 1 | `app/static/git-progress.js:290`, `:294-295` | the chooser's Repository select |
| 4 | **New folder…**: its own dialog; three outcomes (move there, plan only, register); disabled inside another lab's folder, inside a saved state and under one | `app/static/git-progress.js:454-472`; `gitCanCreateIn`, `app/static/git-places.js:121-128`, `:156`, `:158` | an inline row in the tree; never disabled (4.6) |
| 5 | **Remove empty folder** for a folder made through the manager that holds nothing | `app/static/git-places.js:155-156`; `gitForgetFolder`, `app/static/git-progress.js:473-476` | kept: quiet **Remove from the list** on such a row |
| 6 | **Apply to running lab…** on any folder that resolves to a saved state | `app/static/git-places.js:153-157`, `gitApplySource` `:76-81` | `browse` mode: **Load this state…** |
| 7 | Read-only (`canAct: false`): Apply only | `app/static/git-places.js:156`, `:193` | `browse` mode |
| 8 | First save: a text field `#git-first-folder` and **Browse…**, which jumps to the tab's browser | `app/static/git-progress.js:514`, `:517` | the first-save panel's **Choose another place** opens the chooser |
| 9 | Connect by URL: a second, separately validated folder field | `app/static/git-progress.js:488`, `:495` | the chooser's path field alone (4.4): the repository is not on the VM yet, so there is no tree |
| 10 | Breadcrumbs, a file listing with a "What it is" column, a foot with "Last saved", Details and "This lab saves to … Looking at other folders does not change that." | `app/static/git-places.js:137`, `:144-146`, `:149-152`, `:161` | breadcrumbs go (the path field is the breadcrumb); the file listing stays in `browse` mode only; the "does not change that" sentence stays in `browse` and `state` modes |
| 11 | The rules themselves: `gitFolderChoice` (twelve refusals), `gitCanCreateIn`, `GIT_RESERVED_FOLDER_MESSAGE` | `app/static/git-places.js:91-128`, `:22-28` | removed from the page. The page renders the backend's one answer (4.7); it holds no folder rule |

Kept as they are: `gitTreeModel` and `gitApplySource` (`app/static/git-places.js:48-81`), the state
object and the open-branch helpers `gitDefaultExpanded`, `gitToggleFolder`, `gitRevealFolder`,
`gitKeepExpanded` (`:10`, `:41-47`), `gitAncestors`, `gitSize`, `gitLabFolder`.

### 4.2 One component, three uses

```js
folderChooserOpen({labId, mode, repository, path, back})
```

| `mode` | Opened from | Head | Ends in |
|---|---|---|---|
| `location` | Save settings **Change folder…**, **Choose a place…**; the first-save panel's **Choose another place**; **Use a different repository…** | `Where should <lab> save?` / `Pick a folder, type a path, or make a new folder.` | **Save here** |
| `state` | **Save as a lab state…** (section 5) | `Save as a lab state` / `Saves <lab> as it is now into a folder of its own. Where <lab> normally saves does not change.` | **Save state** |
| `browse` | All versions and Load panel **Browse the repository…** | `Browse the repository` / `Every folder of <repo>. Looking at folders does not change where <lab> saves.` | no primary button; per saved state **Load this state…**, **View files** |

It is content of `#save-drawer` (kind `chooser`), 760 px wide like the other drawers, so it never
stacks on another modal. Opened from Save settings it has **Back**; the unsaved device ticks are kept
in `saveDrawer.draft` and restored.

### 4.3 Markup

```html
<div class="folder-chooser" data-mode="location">
  <label for="folder-repo">Repository</label>
  <select id="folder-repo">…one option per checkout…</select>            <!-- only when the VM has more than one -->

  <label for="folder-path">Folder</label>
  <input id="folder-path" maxlength="360" autocomplete="off" spellcheck="false" aria-describedby="folder-result folder-answer" value="BGP/week-4">
  <p class="git-destination-line" id="folder-result"><span>Saves go to</span><code>Course-Labs</code><span aria-hidden="true">›</span><code>BGP/week-4</code></p>

  <ul class="folder-tree" role="tree" aria-label="Folders of Course-Labs" id="folder-tree">
    <li role="treeitem" aria-level="1" aria-expanded="true" aria-selected="false" tabindex="-1" data-folder="">
      <span class="folder-row"><span class="git-twist-space" aria-hidden="true"></span><i class="git-folder-icon"></i><span class="folder-name">Course-Labs</span><small>top level</small></span>
      <ul role="group">
        <li role="treeitem" aria-level="2" aria-expanded="false" aria-selected="false" tabindex="-1" data-folder="BGP">
          <span class="folder-row"><span class="git-twist" data-folder-twist="BGP" aria-hidden="true"></span><i class="git-folder-icon lab"></i><span class="folder-name">BGP</span><b class="git-tag other">UX-TEST-003 saves here</b></span></li>
        <li role="treeitem" aria-level="2" aria-selected="true" tabindex="0" data-folder="BGP/start">
          <span class="folder-row"><span class="git-twist-space" aria-hidden="true"></span><i class="git-folder-icon managed"></i><span class="folder-name">start</span><b class="git-tag state">Lab state: Start</b></span></li>
        <li role="treeitem" aria-level="2" aria-selected="false" tabindex="-1" data-folder="week-5">
          <span class="folder-row"><span class="git-twist-space" aria-hidden="true"></span><i class="git-folder-icon pending"></i><span class="folder-name">week-5</span><b class="git-tag pending">New</b></span></li>
      </ul></li>
  </ul>
  <p class="save-note" id="folder-tree-note" hidden></p>

  <div class="save-row"><button type="button" class="button secondary small" data-folder-action="new">New folder…</button></div>

  <div class="folder-answer" id="folder-answer" role="status" aria-live="polite">
    <p>This folder holds the state “Start”.</p>
    <div class="save-row">
      <button type="button" class="button primary" data-folder-choice="beside">Save beside it in BGP/start/restore-square</button>
      <button type="button" class="button secondary" data-folder-choice="replace">Replace it</button>
    </div>
    <p class="save-note">If you replace it, the older contents stay in the Git history.</p>
  </div>

  <div class="save-drawer-foot"><button type="button" class="save-quiet" data-folder-action="cancel">Cancel</button><button type="button" class="button primary" data-folder-action="save">Save here</button></div>
  <p class="save-note">Saved files can contain passwords or keys.</p>
</div>
```

- The tree is a real ARIA tree, not nested `<details>` as today (`app/static/git-places.js:142-143`):
  one tab stop, arrow keys inside (4.8). The twist is `aria-hidden` because the tree item carries
  `aria-expanded`; a mouse click on the twist toggles, a click on the row selects.
- A mark is text, never colour alone: `This lab saves here`, `<Lab> saves here`, `Lab state: <Name>`,
  `New` (a folder that is in no commit yet: never worded as existing in the repository). The classes
  `git-tag`, `git-tag other`, `git-tag pending` exist (`app/static/style.css:818-829`); `git-tag state`
  is new.
- In `location` and `state` mode the inside of a saved state is not listed (a folder a lab saves to
  shows its other subfolders but not `latest`, `baseline`, `checkpoints`; a folder that holds
  `manifest.json` is a leaf). Fewer rows, and the only way to point at such a folder is to type it, which
  the notice of 4.5 answers. `browse` mode lists everything, with today's file listing
  (`app/static/git-places.js:144-146`, `.git-listing`) under the tree for the selected folder.
- Only open branches are rendered (today's rule, `app/static/git-places.js:143`), so a large repository
  costs what is on screen.

### 4.4 Picking, typing, correcting

- **Pick**: a click, Enter or Space on a row selects it and writes its path into the field.
- **Type**: the field accepts any path. It is corrected as typed, the way the checkpoint name field
  rewrites its own value and shows `Saved as: <name>` (`gitCheckpointName`,
  `app/static/git-progress.js:584`; its `oninput`, `:599`):

  ```js
  // "Week 4//BGP lab/" → "Week-4/BGP-lab/"; the result line shows it without the trailing slash
  function folderClean(value)
  ```

  per segment: whitespace becomes `-`, a character outside `A-Z a-z 0-9 _ . -` is dropped, leading
  characters that are not a letter, digit or underscore are dropped, the segment is cut at 181
  characters (the helper's segment rule, mirrored today by `gitFolderName`,
  `app/static/git-places.js:12-16`); empty segments, `.`, `..` and `.git` are dropped; a leading slash is
  dropped; one trailing slash survives while typing. The input's value is rewritten only when it
  differs, with the caret kept at the same distance from the end. The result is always on screen in
  `#folder-result` (`Saves go to Course-Labs › Week-4/BGP-lab`; `…› top level` for an empty path).
  Nothing is ever thrown at the person: `gitFolderPath`'s errors (`app/static/git-places.js:23-29`,
  `GIT_RESERVED_FOLDER_MESSAGE` `:22`) have no counterpart.
- A typed path that exists selects that row and opens the way to it (`gitRevealFolder`); one that does
  not exist shows a provisional row marked `New` at its place in the tree.
- **Open branches belong to the person.** `aria-expanded` and the rendered children come from
  `gitPlacesState.expanded` only (`app/static/git-places.js:8-10`, `:141-143`). A click on a twist,
  Left and Right change it (`gitToggleFolder`). A selection the person made adds the way to it and never
  closes anything (`gitRevealFolder`, `:43-45`); a refresh keeps what still exists (`gitKeepExpanded`,
  `:47`); the first display of a repository opens the way to the lab's own folder
  (`gitDefaultExpanded`, `:41`). No code path computes "open" from the selected path at render time.
  The test at `tests/test_git_places_ui.js:147` keeps this claim.
- The same path field, without a tree, is the folder field of Connect by URL: `folderClean`, the result
  line, no second validator.

### 4.5 The one answer, and the questions as buttons

The chooser asks the backend what a folder is and renders the answer; it decides nothing. For the
selected path it shows one sentence and, at most, one question.

| Answer (`kind`) | Sentence in `#folder-answer` | Buttons |
|---|---|---|
| `free`, the folder exists | none (the result line is the statement) | **Save here** |
| `free`, the folder does not exist | `<path> is new. It appears in the repository with the first save.` | **Save here** |
| `free`, top level | `<lab> will save at the top level of <repo>.` | **Save here** |
| `this` | `<lab> already saves here.` | **Keep saving here** (closes; nothing is sent, nothing is disabled) |
| `lab` | `<Other lab> saves here too.` | **Save in <path>/<this lab>** (primary) · **Use this folder anyway**; note `If you use this folder anyway, <Other lab> is disconnected from it. Its saves stay as versions.` |
| `state` | `This folder holds the state “<Name>”.` | **Save beside it in <path>/<this lab>** (primary) · **Replace it**; note `If you replace it, the older contents stay in the Git history.` |
| `inside` | `<path> is part of a saved state, so <lab> saves in <folder above>, the lab folder above it.` | **Save here** (acts on the folder above; the result line shows that folder) |

- When the answer is a question, its two buttons take the place of **Save here** in the foot: there is
  one primary button on screen at any time, and choosing an answer is the confirmation (no extra click).
- **A save of this lab still waits for upload** (any folder other than the current one): the confirm
  button, whichever it is, is replaced by `A save of <lab> is still waiting to be uploaded: <the upload
  sentence>.` with **Upload it, then move** (primary; it goes through `gitReviewJob` with that save's
  review, so the single-sender rule and "nothing is uploaded without the sentence on screen" both hold),
  **Move and keep that save on the VM only**, and **See changes**. When a folder question applies as
  well, the folder question is answered first and the waiting-save choice follows in the same place.
- **The lab already has saves and moves to another folder**: one tick box above the foot, ticked, `Move
  the saves made so far into the new folder` (today's default, `app/static/git-progress.js:450`). Whether
  moving stays optional is the lead's folder model (Q5); the chooser sends the tick as `move_files`.
- While the request runs the confirm button reads `Saving here…` and the tree is inert (`aria-busy`).
  On success the drawer goes back to Save settings (or closes, when it was opened from the header) and
  the toast says `<lab> now saves to <repo> › <path>.` (today's toast, `app/static/git-progress.js:437`).
- If the answer changed between display and click (another lab took the folder meanwhile), the request
  comes back with the new answer and the chooser shows that question. It is never an error message.
- The words `registration`, `prefix` and `overlap` appear in no string of the chooser; a Node test
  greps the markup of every answer and state for them.

### 4.6 "New folder…" is always enabled

- It is rendered without a `disabled` attribute in every mode and state; there is no code path that
  sets one (today's is `app/static/git-places.js:156`). A Node test renders the chooser for every answer
  kind, for loading, empty, truncated, error and VM-unreachable, and asserts the button is present and
  enabled each time.
- A click adds a row with a text field under the selected folder and focuses it; the field is corrected
  as typed (`folderClean`; `/` makes nested folders in one step, as today,
  `app/static/git-progress.js:457`). Enter (or **Add**) makes it the selection and puts it in the path
  field; Escape removes the row. In `location` and `state` mode nothing is sent: the folder comes into
  being with the save (Git keeps no empty folders), and it is marked `New` until then.
- Inside a saved state it creates the folder in the lab folder above and says so in the answer area:
  `<selected> is part of a saved state, so the new folder is made in <folder above>.` The parent comes
  from the answer (`use`), not from a rule in the page.
- A name that already exists is not an error: that folder is selected and the status line says `<path>
  already exists. It is selected.` (today: an error, `app/static/git-progress.js:464`, and a 409,
  `app/git_progress.py:1190-1191`).
- In `browse` mode, where no save follows, the new folder is kept by the manager as today (`POST
  …/folders {prefix, plan: true}`, `app/git_progress.py:1184-1195`) and listed with the mark `New`;
  **Remove from the list** takes it away again (`DELETE …/folders`, `:1202-1214`).

### 4.7 Data contract (proposal for the lead)

**NEEDS (backend) N6: one answer per folder.** `GET /api/git/repositories/{id}/tree?lab=<lab_id>` adds,
for every folder of the repository (committed, planned, or a place a lab saves to):

```json
{"path": "BGP/start",
 "answer": {"kind": "state", "state": {"name": "Start"}, "choices": [{"id": "beside", "path": "BGP/start/restore-square"}, {"id": "replace"}]},
 "below":  {"kind": "inside", "use": "BGP"},
 "new": false}
```

- `answer.kind` is exactly one of `free`, `this` (the asking lab saves here), `lab` (with `lab: {id,
  name}`), `state` (with `state: {name}`), `inside` (with `use`: the folder that is used instead).
- `choices` lists the answers the backend will accept for a question, with the path each leads to. The
  page maps the ids to its fixed button texts and prints the path it was given; it never builds
  `<folder>/<this lab>` itself.
- `below` is the answer for a path that does not exist yet and whose nearest existing folder is this one
  (`free`, or `inside` with `use`). With it the page answers any typed path with no further request and
  no rule of its own: an existing path uses its own `answer`, a new one the `below` of its nearest
  existing ancestor.
- `new` is true for a folder that is in no commit (today's `planned`, `app/git_progress.py:1177`).
- A folder registered on the VM that no lab uses is simply `free` (PROMPT 6.2, last row); today it is
  marked "Lab folder" (`app/static/git-places.js:133`).
- The marks in the tree, the sentence, the buttons, and the Lab states names of section 2 all read this
  one object. That is what makes two contradicting texts on one screen impossible (the reported
  "This lab folder is free" beside a greyed New folder came from two functions,
  `gitFolderChoice` and `gitCanCreateIn`, `app/static/git-places.js:113`, `:121-128`).

**NEEDS (backend) N7: one request for "Save here".**
`POST /api/labs/{lab_id}/git/place {repository, path, choice, pending, move_files, expect}` where
`choice` is `''`, `beside`, `anyway` or `replace`, `pending` is `''`, `upload` (the page uploaded
first) or `keep`, and `expect` is the `kind` the page showed. It answers `{saved, binding, job?}` or,
when the situation is not the one shown or a choice is missing, `{question: <answer object>}` with
status 200. It serves a lab without a save location (first place) and a lab with one (change), in the
current or another repository, and replaces the page's sequences `POST …/folders` then `PUT …/git`
(`app/static/git-progress.js:445`, `:526-527`) and `POST …/git/destination` (`:434`).

**NEEDS (backend) N8: every folder even in a large repository.** The helper stops at 4000 files
(`MAX_TREE`, `app/host_git.py:37`, `:785`) and the tree answer only says `truncated`
(`app/git_progress.py:1176`). The chooser needs the folders complete (they are few even when files are
many), or it must tell the person to type.

### 4.8 Keyboard

The field, the tree, New folder…, the answer buttons and the foot are five tab stops in that order.

| Key (focus in the tree) | Effect |
|---|---|
| Down / Up | next / previous visible row; focus only, the selection does not move |
| Right | on a closed branch: open it; on an open branch: first child; on a leaf: nothing |
| Left | on an open branch: close it; otherwise: the parent row |
| Home / End | first / last visible row |
| Enter or Space | select the focused row (writes the path field, shows the answer) |
| a letter | next visible row whose name starts with it |
| Tab | leaves the tree; the selected row (else the first) is the tree's one tab stop |

In the path field Enter presses the primary button; in the new-folder field Enter adds and Escape
cancels (it does not close the drawer). The reducer is pure and tested in Node:
`folderKey(rows, focusIndex, key, expanded) → {focus, toggle, select}`. Focus and scroll survive a
re-render the way today's panel restores them (`app/static/git-places.js:190-205`).

### 4.9 States

| State | What shows | Controls |
|---|---|---|
| Loading | `Loading folders…` (`role="status"`), the path field already usable | **Save here** waits with the visible reason `The folders are still loading.`; New folder… enabled |
| Empty repository | the top-level row only; `<repo> is empty. <lab> can save at the top level or in a new folder.`; the path field prefilled with the suggested folder (`gitSuggestedFolder`, `app/static/git-progress.js:484`) | all enabled |
| Huge repository | open branches only are rendered; a branch with more than 200 folders shows the first 200 and **Show all 1,240 folders**; when the list was shortened: `This repository is large and not every folder is listed. Type the path of a folder that is not shown.` | all enabled; an unlisted path is answered by the save request (N7) |
| Error (the VM answered with a reason) | `The folders could not be loaded.` and the manager's sentence; **Try again** | the path field and New folder… work; **Save here** sends the typed path and the backend answers |
| VM unreachable | `The lab VM cannot be reached, so its folders cannot be shown.`; **Try again**, **Check the VM connection…** (`openVmDialog`) | **Save here** disabled with that sentence as its reason and those two buttons beside it; New folder… enabled (it only writes the path) |
| No repository on the VM | not a chooser state: the caller shows Connect by URL | |

---

## 5. "Save as a lab state…" (PROMPT 5.5, D9)

Reached from the chip panel at rest and from the Lab states heading of All versions. It is the chooser
in `state` mode with a name above the tree.

```html
<div class="folder-chooser" data-mode="state">
  <label for="state-name">Name</label>
  <input id="state-name" maxlength="100" autocomplete="off" spellcheck="false" placeholder="start">
  <div class="save-row folder-names" role="group" aria-label="Common names">
    <button type="button" class="pill neutral" data-state-name="start">start</button>
    <button type="button" class="pill neutral" data-state-name="broken">broken</button>
    <button type="button" class="pill neutral" data-state-name="final">final</button>
  </div>
  <label for="folder-path">Folder</label>
  <input id="folder-path" value="BGP/start" …>
  <p class="git-destination-line" id="folder-result"><span>The state is saved in</span><code>Course-Labs</code><span aria-hidden="true">›</span><code>BGP/start</code></p>
  <details class="save-fold"><summary>Put it somewhere else</summary>…the tree and New folder… of 4.3…</details>
  <div class="folder-answer" id="folder-answer" role="status" aria-live="polite"></div>
  <div class="save-drawer-foot"><button type="button" class="save-quiet" data-folder-action="cancel">Cancel</button><button type="button" class="button primary" data-folder-action="save">Save state</button></div>
  <p class="save-note">Reads every included device now. Saved files can contain passwords or keys. Where restore-square normally saves does not change.</p>
</div>
```

- The folder starts **beside the lab's own folder**: for a lab that saves to `BGP/restore-square` the
  parent is `BGP` and the path is `BGP/<name>`. The path field follows the name until the person edits
  the path or picks a folder in the tree; picking a folder makes it the parent. Selecting a folder that
  already is a state fills the name from it.
- The name is corrected as typed like a folder segment (`folderClean` on one segment). The three name
  buttons fill it in one click; they are real buttons in a labelled group, and the pressed one carries
  `aria-pressed="true"`.
- The tree is folded because the default place is right in the common case; **New folder…** is inside
  the fold, enabled.
- Answers: `free` → **Save state**. `state` → `This folder holds the state “Start”.` with the choices
  the backend lists for this purpose (**Replace it**, **Save beside it in …**) and the note about the
  Git history. `lab` and `inside` → as in 4.5. The page shows what `choices` holds; which choices exist
  for a state save is the lead's rule.
- **Save state** closes the drawer and starts a save whose destination is that folder; the chip shows
  *Saving* (`Saving the state Start…`), then the same upload sentence as any save, with **Upload** and
  **Not now**. Toast when the files are written: `State Start saved in BGP/start.` The lab's own save
  location, its chip text for its own saves and its Your saves list are untouched; the new state appears
  under Lab states, here and in every lab that uses the repository.
- A lab without a save location can still author a state: the chooser shows the Repository select; with
  no repository on the VM the action leads to Connect by URL first.
- **NEEDS (backend) N9**: a save whose destination is a folder other than the lab's own (PROMPT 6.4, 7.8):
  the save route accepts `state: {repository, path, choice}`, answers a `{question}` like N7, and the job
  carries its destination so the chip can name it.

Clicks: chip (1), **Save as a lab state…** (2), a name button or typing the name (3, or none), **Save
state** (4). Three clicks plus a typed name, four with a name button; the upload afterwards is the same
one click as after any save.

---

## 6. Removing the Progress tab (D1) and "Where everything goes" (PROMPT 5.11)

### 6.1 Markup of `index.html`

| Markup | Line | Fate |
|---|---|---|
| `#lab-progress` in the status line | `app/static/index.html:73` | retired (PROMPT 5.1: the chip carries it); its writer at `app/static/app.js:103` goes with it |
| `.git-save-control`: `#git-save-progress`, `details#git-save-menu`, its four items and the help pane | `:75` | replaced by the chip, Save and Load (header slice). `closeMenus` and `shellEscape` name `details#git-save-menu` (`app/static/shell.js:74`, `:130`, `:134`): the header slice drops or keeps those selectors with its markup |
| banner buttons `#banner-retry-save`, `#banner-save-details`, `#banner-restore` | `:107` | ids stay (static children, addendum J3); their actions change (6.5) |
| `#tab-progress` | `:109` | removed. The tab key handler and `showTab` iterate `PANELS` and `[data-tab]` (`app/static/app.js:316`, `:322`, `:332`), so removing the name from `PANELS` is enough |
| `section#progress-view`, `#git-view` | `:137-149` | removed with everything inside |
| status card `#git-progress-bar`: `#git-open-settings`, `#git-destination`, `#git-progress-status`, `#progress-save-reason`, `#git-last-restore` (+ `-text`, `-open`) | `:139-140` | retired: chip and chip panel. The destination with its Change… button: see Q1 |
| `#progress-save`, **Create checkpoint…**, `#progress-more-button` and `#progress-more-menu` (Save on this VM only, Upload saved progress, Update from the repository, Set baseline…, Load a saved version…, Save location settings…) | `:141` | Save · Keep as a checkpoint · Save then Not now · Upload in the chip panel · Save settings › Git details · All versions › Use as starting point… · Load · Save settings |
| `#git-problem` | `:142` | chip *Can't save*; repeated in Save settings (3.1) |
| Saved versions section, `#git-saved-versions` | `:144` | All versions drawer |
| Recent saves section, `#git-recent`, `#git-saves-list` | `:145` | chip panel (newest), All versions rows and its Save activity fold |
| `#git-repository-content` | `:146` | Save settings drawer and the chooser |
| `details#git-repository-advanced` and `#git-advanced-*`, `#git-repository-refresh`, Update, Disconnect… | `:147` | Save settings › Git details (same ids for the values); Disconnect in the drawer's foot |
| new: `dialog#save-drawer` | beside `:335` | 0.1 |
| drawer caption "Progress saved to Git is under the Progress tab." | `:335` | reworded (6.4) |

Addendum J2 lists `git-progress-bar git-open-settings git-destination git-progress-status
git-save-progress git-save-menu git-repository-refresh git-repository-content git-view` as load-bearing
ids. They are load-bearing only for the wiring block at `app/static/git-progress.js:783-796`, which is
rewritten; J2's own rule (every `$('id')` in the scripts exists in `index.html`) is the acceptance check
after the removal, and the addendum needs a dated amendment (documentation slice).

### 6.2 The router: old links land on the default tab with the chip panel open

Today: `PANELS` holds `progress` and `TAB_ALIAS` maps `git` to it (`app/static/app.js:8-9`); `setTab`
resolves an alias, then falls back to `topology` for an unknown name (`:62`); `showTab('progress')` loads
the tab (`:324`); `applyRoute` passes the hash's view to `selectLab` or `showTab`
(`app/static/shell.js:41-43`) and writes the normalised route back (`:47`).

Change, in `app.js` only:

```js
const PANELS=['topology','devices','tools','advanced'];
const TAB_ALIAS={inventory:'devices',git:'topology',progress:'topology',backups:'tools',credentials:'advanced',logs:'advanced',design:'advanced'};
const SAVE_VIEWS=['git','progress'];        // the removed Progress tab and its older name
let savePanelWanted=false;
function setTab(value){if(SAVE_VIEWS.includes(value)){savePanelWanted=true;subview='';tab='topology';return;} …unchanged… }
// last line of showTab():
if(savePanelWanted&&typeof saveOpenPanel==='function'){savePanelWanted=false;saveOpenPanel();}
```

- `git` stays in `TAB_ALIAS` and `progress` joins it: stored-data compatibility, not dead code
  (CLAUDE.md). The lab's default tab is `topology` (`selectLab(id, view='topology')`,
  `app/static/app.js:64`; `route.view||'topology'`, `app/static/shell.js:41`).
- The flag is one-shot. `render()` calls `showTab(tab)` on every poll (`app/static/app.js:141`); with a
  flag the panel opens once per old link, and it survives until the header script has loaded (deferred
  scripts and the first render, `app/static/shell.js:209-212`).
- `shell.js` needs no change: it still passes the raw view through (the test at
  `tests/test_shell_ui.js:87-88` stays true), and its closing `writeRoute(currentRoute())` rewrites
  `#lab=a&view=progress` to `#lab=a&view=topology` with `replaceState`, so a reload does not open the
  panel again and Back does not loop.
- `showTab('progress')` and `showTab('git')` from any remaining caller behave the same way.
- Stored tab preferences: there are none. The only browser storage about navigation is
  `sessionStorage.activeLab` (a lab id, `app/static/app.js:64`) and `clab.homeTab` (the Home list,
  `app/static/shell.js:138-139`); `clab.opened.<id>` and `clab.dismissed.<id>` hold no tab
  (`app/static/shell.js:136-142`). Checked by searching every script for `localStorage` and
  `sessionStorage`.
- `gitTabActive()` (`app/static/git-progress.js:18`) goes; its six callers (`:500`, `:517`, `:528`,
  `:693`, `:700`, `:717`) call `saveDrawerRefresh()` instead, which does nothing when no drawer is open.
- The `if(tab==='progress')` line (`app/static/app.js:324`) and the wiring loop over
  `#progress-view [data-git-action]` (`:353-354`) are removed.

### 6.3 Functions of `git-progress.js`

Consumers were searched in every script, `index.html`, the Node tests and the Playwright tools under
`docs/*/tools`. "header", "save flow" and "load" mean the decision belongs to that slice; this table
records what the Progress tab's removal requires.

| Function or constant (line) | Fate |
|---|---|
| `gitActiveStates`, `gitPendingStates` (6-7), `gitStateLabels`, `gitLabel` (8, 14), `gitSaveSentences`, `gitSaveSentence`, `gitSavePill`, `gitBadgeClass`, `gitSavedAs`, `gitUploadState` (9, 55-65) | keep: the save window (Details) and the Save activity fold use them |
| `GIT_EXPOSURE_TEXT`, `GIT_EXPOSURE_ERROR` (10-11), `gitBindingChanged` (24) | retire with the tick box (D5). Used only by the form, Connect by URL and the first-save dialog (`:275`, `:299`, `:488`, `:496`, `:514`, `:522`) |
| `gitContexts`, `gitLoads`, `gitLoadContext` (12, 138) | keep (`gitProblem` in `app/static/app.js:88` reads `gitContexts`) |
| `gitViewLab`, `gitViewRequest` (13), `gitShowRepository` (233), `gitFolderCollapsed` (251) | retire; `saveDrawerOpen` / `saveDrawerRefresh` take over. Callers to update: `app/static/app.js:324`, `app/static/git-places.js:174`, and the stubs in `tests/test_git_places_ui.js` |
| `gitVersionRows`, `gitVersionTree` (13) | move into `saveDrawer.data` |
| `gitJobTime`, `gitTime`, `gitWhen` (15-17), `gitLabJobs` (19), `gitRepository` (23), `gitRepoName` (26; also `app/static/restore.js:155`), `gitFolderWords` (29), `gitSnapshotPath` (34), `gitTargetPath`, `gitTargetLabel`, `gitMoveDone`, `gitMoveFolder` (47-53), `gitLabName` (432) | keep |
| `gitTabActive` (18) | retire (6.2) |
| `gitRegisteredDestination` (25) | keep; it becomes the last line of Git details (test `tests/test_git_progress_ui.js:95`) |
| `gitDestination` (27) | header (it only feeds the Save button's title, `:200`) |
| `gitLegacyDestinationNotice` (38) | keep, reworded; shown in Save settings |
| `gitCompleteBackups` (67) | keep: decides whether Keep as a checkpoint and Use as starting point… are available |
| `gitSavePayload`, `gitRequestId`, `GIT_REQUEST_REUSE_MS`, `gitNow`, `gitReusableRequest`, `gitSubmitSave` (71-72, 536-562) | keep (save flow) |
| `gitLabelKey` … `gitValidateLabel` (77-88), `gitLabelDialog` (566) | save flow (D2): the dialog goes, the validation serves the rename |
| `closeDialogsExcept`, `gitFocusDialog` (92-104) | keep; `#save-drawer` is a dialog like the others for both |
| `gitDestinationState`, `gitDestinationPill`, `gitDestinationMarkup`, `gitJobMarkup` (108-131) | keep (save window) |
| `gitFilesDiffMarkup` (134) | keep: What changed and "See what’s different" |
| `gitActionButtons` (144), `GIT_SAVE_HELP_ACTIONS` … `gitInsideMenu` (151-183), `gitSaveReason` (186), `renderGitProgress` (191) | header: the menu, its help pane and the status card go; `render()` calls `renderGitProgress` (`app/static/app.js:122`), so the name or its replacement must stay callable there |
| `gitRenderLastRestore` (213) | retire: chip *Running* / *Partial* and What changed (5.11) |
| `gitOpenRepository` (222) | keep the name, new body `saveDrawerOpen('settings')`. Consumers: the banner (`app/static/app.js:237`), `:769`, `:787`, `:517` |
| `gitFetchHistory`, `gitFetchTree` (231-232) | keep (drawer loaders) |
| `gitRenderRepository` (252) | split into the pure `saveSettingsMarkup(id, context, catalog)` and its wiring in `save-drawers.js` |
| `gitVersionsOwner`, `gitVersionGroups` (317-368) | keep in this file; gains the `saves` group; also feeds the Load panel |
| `gitVersionRowMarkup`, `gitRenderVersions`, `gitVersionAction` (369-403) | replaced by `saveVersionsMarkup` and the drawer's action dispatcher; `gitVersionsMarkup` (376) goes with them (`setMarkup` is always present on `/`) |
| `gitRenderSaves`, `gitSavesAction` (406-422) | replaced by the waiting rows and the Save activity fold. The direct `{push: true}` for a save whose review already happened (`:420`) stays the Try again of the *Failed* chip |
| `gitRenderAdvanced` (423) | keep; fills the same ids inside Git details |
| `gitApplyDestination`, `gitUseFolder`, `gitNewFolder` (433-472) | replaced by the chooser (`folderSaveHere`, the inline new-folder row) |
| `gitForgetFolder` (473) | keep (Remove from the list) |
| `gitSwitchRepository` (477) | keep; lists repositories, continues in the chooser |
| `gitSuggestedFolder` (484) | keep |
| `gitConnectByUrl` (485) | keep; the path field and the sentence replace its folder field and tick box |
| `gitFirstSave` (507) | header / save flow (F12 panel); its Browse… becomes `folderChooserOpen` |
| `gitSaveProgress` (578) | keep the name: `operations.js` offers "Save progress first" through it (`app/static/operations.js:238-241`) |
| `gitCheckpointName` (584) | keep (Keep as a checkpoint; the model for `folderClean`) |
| `gitSaveOptions` (585) | retire, target by target: checkpoint → Keep as a checkpoint; local → Not now; baseline → Use as starting point…; its `allow_removed` tick box → Q4 |
| `gitRememberJob` (611), `gitStartWatch` (682) | keep (`app/static/network-design.js:2137-2139`); the watch's automatic review (`:692`) becomes "open the chip panel" (header) |
| `gitJobTitle`, `gitShowJob`, `gitRenderJob` (618-647) | keep: "Details opens today's save window"; one sentence reworded (6.4) |
| `gitNeedsReview`, `gitUploadLabel` (652-653) | keep |
| `gitReviewJob` (654) | reshaped: the sender only (1.4); its dialog becomes the What changed drawer; `gitReviewData` is new |
| `gitDoneToast` (674) | save flow |
| `gitDismissJob` (698) | keep, reworded (8.1) |
| `gitJobLabel` (704), `gitPushPending` (705) | header: the banner's Retry calls `gitPushPending` (`app/static/app.js:240`); with the chip panel listing the waiting saves, its `git-pending-dialog` has no other caller |
| `gitUpdateRemote`, `gitUnlink` (714-723) | keep; unlink gains the two buttons of 3.3 |
| `gitHistory`, `gitOpenCommit` (724-742) | keep (Full history…) |
| `gitCompareVersion` (743) | keep the request; renders into the drawer |
| `gitViewVersion` (749) | keep the request; renders into the drawer as View files; its Apply button becomes **Load this state…** |
| `gitRunAction` (765) | keep as the dispatcher of `[data-git-repo-action]`; `settings` opens the drawer, `load` opens the Load panel, `browse` opens the chooser in `browse` mode, `history` unchanged |
| load-time wiring (783-796) | rewritten: the two document listeners for the old menu (`:794-795`) go with it |

`git-places.js`: see 4.1.

Playwright tools that drive the tab (to update with the fixture slice; listed here because "no
reference in this file" proves nothing): `docs/redesign/tools/verify_after.py` (`TABS`, `r.tab('progress')`,
`#progress-view [data-git-action="checkpoint"]`, lines 22, 223, 292, 330),
`docs/redesign/tools/verify_stage1.py` (the `view=progress` deep link, lines 21, 270, 279),
`docs/ui-review-001/tools/check_ui004.py`, `check_ui007ab.py`, `check_ui007c.py`, `check_ui008a.py`,
`check_ui008b.py` (`#tab-progress`, `#progress-view`). Tools under `docs/save-location-fix/`,
`docs/student-quick-start/`, `docs/multi-platform-restore/`, `docs/technical-audit/` and
`docs/ui-ux-cleanup/` also use these selectors; they are dated records and are listed as out of date,
not edited.

### 6.4 Texts that point at the tab (`app/` and `tests/` only)

| Where | Today | New wording |
|---|---|---|
| `app/static/shell.js:183` | "…Check the devices under Progress › Save settings." | `The devices in this lab changed since the save location was set up. Open Save settings and choose the devices again.` (the banner action beside it opens the drawer) |
| `app/static/network-design.js:887`, pinned by `tests/test_network_design_ui.js:695` | "Bind this lab to a repository under Progress first." | `Save this lab once first: the export goes to the lab's save location.` |
| `app/static/network-design.js:2138` | `showTab('progress')` after an export started | `saveOpenPanel()` |
| `app/static/git-progress.js:156`, `:158` | menu help: "Progress › More › Upload saved progress", "Opens Progress › Save location." | retired with the menu help (header) |
| `app/static/git-progress.js:639` | "…its result appears under Progress › Recent saves." | `You can close this window. The save continues, and the save status in the lab header shows when it is done.` |
| `app/static/git-progress.js:671` | "Not uploaded. … upload it from Progress › Recent saves when you are ready." | `Not uploaded. The save stays on the lab VM.` |
| `app/static/git-progress.js:695` | "Open the save under Progress › Recent saves to check it." | `The save status could not be refreshed. Open the save status in the lab header to check it.` |
| `app/static/git-progress.js:127` | "No saves yet. Save progress saves every device chosen under Save settings." | `No saves yet. Save reads every device chosen in Save settings.` |
| `app/static/git-progress.js:45` | "…open Change folder…, pick <x> and choose Save this lab here without moving the files." | `…open Save settings, choose Change folder…, pick <x> and choose Save here.` |
| `app/static/git-progress.js:447`, `:481` | "Now tick the devices to include and choose Connect." / "Choose the folder, then tick the devices under Save settings." | retired (one request connects) |
| `app/static/index.html:335` | "Backups kept on this VM by the manager. Progress saved to Git is under the Progress tab." | `Backups kept on this VM by the manager. What you saved with Save is under All versions.` |
| `app/static/app.js:237` | banner "Saving to Git is not possible right now." with **Save location settings** | the chip's *Can't save* (5.11); if the banner line is kept its button reads **Save settings** and opens the drawer |
| `app/static/operations.js:145`, `:238` | "Save progress first" | `Save first` (the button runs Save) |
| `app/git_progress.py:291` | "Open <lab> › Progress, review and upload that save, then …" | `Open <lab> and upload that save, then …` (and structured, N2) |
| `app/git_progress.py:691` | "Open this move under Progress › Recent saves and choose Review and upload…" | `Open the save status in the lab header and choose Upload: what the upload sends is named before anything is uploaded.` |
| `app/git_progress.py:610`, `app/discovery.py:669` | "Finish pending Git saves, or choose Keep snapshot only in Git history before continuing." | `A save is still waiting to be uploaded. Upload it, or keep it on the VM only, then try again.` |
| `app/git_progress.py:1232` | "…Choose its devices again under Save settings, then change the folder." | `…Open Save settings, choose its devices again, then change the folder.` |
| `app/git_progress.py:1256` | "…Open Change folder again." | `…Choose the folder again.` |
| `app/git_progress.py:1262` | "(Use a different repository… on the Save location card)" | `(Use a different repository… in Save settings)` |
| comments only | `app/static/git-progress.js:4`, `app/static/git-places.js:163`, `app/static/restore.js:349`, `app/static/style.css:2461` | reworded when the line is touched |

The Python messages are the lead's (several disappear with the folder rules); Python tests that pin them
move with them.

### 6.5 Lab banner and home card

- Banner, restore running or finished: **View progress** / **Details** → `restoreShowJob`
  (`app/static/app.js:222`, `:226`): unchanged, it is "today's job window".
- Banner, save location problem: **Save location settings** → `gitOpenRepository`
  (`app/static/app.js:237`): the function now opens the Save settings drawer on the current tab.
- Banner, save needs attention: **Retry** → `gitPushPending` (`:240`) becomes `saveOpenPanel()` (the
  panel holds **Try again** / **Upload**); **Details** → `gitShowJob` (`:241`) unchanged.
- Home card: it has no link to the tab; its click opens the lab on the default tab. Its saved line
  (`homeSavedLine`, `app/static/home.js:7-14`) reads the chip's status function (PROMPT 5.2), so the
  card says what the chip says (`tests/test_home_ui.js:29`, `:31` are rewritten for the new strings).

---

## 7. Tests

### 7.1 Existing Node tests that pin this slice's surfaces

A test whose subject an owner decision removes is rewritten to assert the new behaviour; none is deleted.

`tests/test_git_places_ui.js`

| Test (line) | Asserts today | Afterwards | Decision |
|---|---|---|---|
| folder rules: own, other lab, inside, managed, unused, root versus subfolders (29) | twelve outcomes of `gitFolderChoice` and `gitCanCreateIn`, most of them refusals | the same fixtures, each mapped to its answer kind and buttons: own → `this` / Keep saving here; other lab → `lab` with both choices; inside another lab's folder → `free`; top level → `free`; `bgp/latest` → `inside`, uses `bgp`; nothing refuses | D8 |
| selecting a snapshot folder named latest resolves to its parent; any other snapshot folder is refused outright (52) | `target` is the parent; another snapshot folder is refused | `latest` → `inside` with `use`; another saved state → the `state` question with its two buttons | D8 |
| a folder below a saved configuration is refused too (70) | refusal naming the ancestor | `inside`: the sentence names the folder above and **Save here** acts on it | D8 |
| folder names are literal single segments (83); nested folder helpers validate each segment and preview the full destination (248) | `gitFolderName` / `gitFolderPath` throw; `gitDestinationPreview` | `folderClean` corrects the same inputs and never throws; the result line shows the same destinations | D8 |
| latest, baseline and checkpoints are reserved names inside a lab folder (261) | `gitFolderPath` throws the reserved-name message | typing such a path yields the `inside` notice from the nearest folder's `below`; a `latest` segment higher up stays an ordinary name | D8 |
| the browser markup escapes names and labels and explains each folder (93) | escaping; `data-git-places-action="new" disabled`; `use disabled` with "already saves here" | escaping of names, lab names and state names in tree, marks, result line and answer; no `disabled` on New folder… or the primary button for any answer | D8 |
| an empty folder made through the manager stays in the tree, is told apart from a saved one, and can be chosen (108) | `pending` rows, "not in the repository until the first save" | the mark `New`; never worded as existing | unchanged claim |
| New folder: a connected lab plans the folder without moving, a duplicate is refused before any request, an unconnected lab still registers (128) | three requests; a duplicate throws | New folder… adds the selection with no request in `location` mode; a duplicate selects the existing folder; `browse` mode still sends `{plan: true}` | D8 |
| the outline opens and closes by the student's own state (147); the folder panel keeps branches, selection and focus across a refresh (176) | `expanded` rules; focus and scroll restored | unchanged claims, asserted on `role="tree"` markup and `aria-expanded` | none |
| the connected card names the folder path and offers the switch and disconnect actions (205) | the Save location card's markup | `saveSettingsMarkup`: the destination line, `data-git-repo-action` switch, connect, unlink, and **Change folder…** | D1 |
| Save location opens with the folder browser unfolded, keeps a deliberate fold per lab, and names its Git details (213) | `details#git-change-folder` open / folded; "Git repo details", "Registration details" | Change folder… is a button that opens the chooser; one fold **Git details** holds push destination, branch, account, path, status | D1 |
| choosing a folder in a repository the lab is not connected to prepares the form instead of moving (234) | register, then preselect in the form | **Save here** in another repository sends one `place` request with that repository | D5, D8 |
| Apply to running lab sends the exact resolved snapshot path to onApply (302) | the path given to `onApply` | `browse` mode: **Load this state…** hands the same exact path to `loadState` | D4 |
| saved versions come from the repository tree … apply only where one exists (317) | `gitRenderVersions` output | the drawer's markup from the same groups; Load offered only where the state can be loaded | D1 |
| recent saves rows explain each save and offer upload or keep-snapshot-only while one is pending (353) | `gitRenderSaves` rows | waiting rows in Your saves offer **Upload…**; other jobs sit in the Save activity fold and open the save window | D1, D3 |
| tree model (15), path chips (24), sizes (89), saved-configuration detection (268), move jobs (228) | pure helpers | unchanged; `gitPathChips` goes with the breadcrumbs unless `browse` mode keeps them, then the test stays as is | none |

`tests/test_git_progress_ui.js`

| Test (line) | Asserts today | Afterwards | Decision |
|---|---|---|---|
| a changed registered destination requires export acknowledgement even with the same binding ID (88) | `gitBindingChanged` drives a required tick box | the chooser shows `Saved files can contain passwords or keys.` beside the confirm button in `location` and `state` mode | D5 |
| repository selection identifies the verified remote URL and branch (95); connected repository displays the push URL as escaped text (101) | `gitRegisteredDestination`; escaped push URL on the card | the same strings inside Git details | D1 |
| the review before an upload is mandatory … only its button uploads (170) | every upload of an unreviewed save goes through the review window; one sender | `gitReviewJob(job, review)` is the only sender; it refuses without this job's review; the panel's and the drawer's Upload both call it | D3 |
| the save location form no longer offers to skip the review (196) | no `review_before_push` control or field | same claim on `saveSettingsMarkup` and its request | none |
| single-job review requests parent-versus-saved changes (236) | `compare {job_id}` | `gitReviewData` sends the same request | D3 |
| saved versions list every snapshot folder … (294), top-level lab folder (330), lab at the repository root (343), root snapshot uses "/" (355) | `gitVersionGroups` | unchanged, plus the `saves` group | none |
| gitReviewJob's "Open the full saved version" opens the job's own snapshot path (386) | the path it requests | What changed › **View files** requests the same path | D3 |
| the Full history… dialog opens a saved version with the leading slash (400); gitViewVersion falls back to a slash-free label (413) | request and label | unchanged; rendered into the drawer | none |
| gitLegacyDestinationNotice … (423); a legacy binding shows the notice on the Save location card (435) | sentence; placement under the destination line | new sentence; placement under the destination line of Save settings | D1 |
| the review dialog for a design export says "Design export…" (536) | dialog title | the drawer's title for `kind: design` | D3 |
| a folder move kept on the VM … is uploaded through the review that names them (566); the review counts the saves an upload carries … (596); the review names the saves kept with Keep snapshot only (612) | sentences from `also_sends*`, `upload_blocked` | the same facts in the drawer's `#save-changes-also` and the blocked state; the single-sender call unchanged | D3 |
| the disabled reason of Save progress is visible text … (286); the three menu tests (48, 66, 75); the last configuration change skips a restore still read back (649); one-click save asks for a label first (134); an empty or over-length label is refused (151) | status card, menu, label dialog | header and save-flow slices rewrite them (chip state function, optional label) | D1, D2 |

Other files: `tests/test_shell_ui.js:87-88` stays as it is (the shell passes `progress` through);
`tests/test_network_design_ui.js:695` gets the new sentence; `tests/test_home_ui.js:29`, `:31` follow the
chip's strings (header slice).

### 7.2 New Node tests

`tests/test_save_drawers_ui.js` (new; `status.js`, `diff-view.js`, `git-progress.js`, `git-places.js`,
`save-drawers.js` in one context, the harness of `tests/test_git_progress_ui.js`):

1. `saveChangeAccount`: for a latest save, a checkpoint save, a baseline, a lab state, a Junos rename, a
   removed device and a map-only change, entries plus rest equal `changed_files`; a restore artifact
   never opens a second entry; a file without a role is listed as other.
2. What changed markup: one entry per device, topology and map titled in words, Upload and Not now in
   the head, the passwords sentence, the also-sends sentence; names, notes and diff text escaped.
3. Upload blocked: the button is disabled, the reason is visible text and **Open <lab>** is present.
4. Single sender: the string `reviewed:true` occurs once in the static scripts, inside `gitReviewJob`;
   the drawer's and the panel's Upload reach it; without a review of the same job it throws and sends
   nothing.
5. All versions markup: the group order; a row opens in place with the four actions; own saves add the
   two; the newest own save has no "See what’s different"; a design export has only View files and
   Download ZIP; a state without restore files shows `View only` with the reason as text; empty groups;
   the open row survives a re-render.
6. Use as starting point: the request carries `backup_job_id`, `replace_baseline` and
   `expected_baseline` exactly as `gitSaveOptions('baseline')` does today; without a kept capture the
   reason is visible.
7. Save settings markup: the F15 controls, one Git details fold with the `git-advanced-*` ids, the
   waiting-save state (reason and its two buttons), the no-location and no-repository states.
8. Disconnect with a waiting save offers the two buttons and sends dismiss before unlink.
9. One drawer: opening a second kind replaces the first; Back and Escape go one level; the drawer
   closes on a lab change.

`tests/test_git_places_ui.js` (existing file, extended):

10. **New folder is enabled in every state**: every answer kind, every mode, loading, empty, truncated,
    error, VM unreachable: the button is present and carries no `disabled`.
11. `folderClean`: spaces, unsafe characters, leading dots and dashes, `..`, `.git`, double and leading
    slashes, over-long segments; idempotent (`folderClean(folderClean(x))===folderClean(x)`).
12. One answer: for each kind the mark, the sentence and the buttons come from the same object; a typed
    path that does not exist takes `below` of its nearest existing folder.
13. The words `registration`, `prefix` and `overlap` occur in no chooser markup, for any answer or state.
14. Keyboard reducer `folderKey`: every key of 4.8; focus movement never changes `expanded` or the
    selection.
15. `aria-expanded` and the rendered children depend on `expanded` only: selecting a deep path adds its
    ancestors and removes nothing; a re-render with another selection leaves the set equal.
16. State mode: the name buttons fill the name and the path; the path follows the name until edited;
    the default parent is the folder above the lab's own; the request names the state's folder and
    leaves the lab's binding out.
17. A `{question}` answer to Save here re-renders the question and reports no error.

`tests/test_save_routing_ui.js` (new; the `status.js` + `app.js` harness of
`tests/test_readiness_ui.js`):

18. `setTab('progress')` and `setTab('git')` leave `tab==='topology'` and ask for the panel once; a
    second `showTab(tab)` (the poll) does not ask again.
19. `PANELS` has no `progress`; `TAB_ALIAS.git` and `TAB_ALIAS.progress` exist.
20. With `saveOpenPanel` undefined at the first render the request is kept and served by the next one.
21. Every `$('…')` id used by the static scripts exists in `index.html` (addendum J2's rule as a test).

New test files reach CI only through the explicit list in `.github/workflows/release-check.yml`
(lead).

---

## 8. Wording, files, friction, assumptions, questions

### 8.1 Final strings

| Where | String |
|---|---|
| What changed: title / design export | `What changed` / `What this design export changed` |
| meta | `<devices> · <n> lines added, <m> removed · not uploaded yet` (or `· uploaded to <host>`) |
| buttons | `Upload` · `Not now` · `View files` · `Uploading…` |
| notes | `Saved files can contain passwords or keys.` · `Uploading also sends <n> earlier save(s) that is/are still waiting on the VM[, <k> of them from another lab / other labs in this repository].` · `Among them, kept on the VM only and not seen uploaded yet: <names>.` |
| entries | `<device>` · `Topology file` · `Map` · `Also uploaded for <device>: <file>, the file Load uses` · `The configuration text is the same. The file Load uses changed.` |
| rest | `Also in this upload` · `Save details (which devices, when they were saved)` · `<path> (the same file, kept in the checkpoint)` |
| blocked | `<Lab> has a save that must be uploaded first.` · `Open <Lab>` |
| toast | `Not uploaded. The save stays on the lab VM.` |
| All versions: title / meta | `All versions` / `Everything saved for <lab>. Choose one to load it.` |
| groups | `Your saves` · `Checkpoints` · `Starting point` · `Lab states` · `Other labs in this repository (n)` · `Everything else in this repository (n)` · `Save activity (n)` |
| row lines | `Your save · <n> devices · topology and map included` · `Checkpoint · <n> devices` · `Lab state · covers <k> of your <n> devices` · `From <lab> · <n> devices` · `Not uploaded yet` · `View only: saved without the files needed to load it` · `Design plan: view and download only` |
| actions | `Load this state…` · `See what’s different` · `View files` · `Download ZIP` · `Keep as a checkpoint` · `Use as starting point…` · `Upload…` · `Details` · `Show older saves` |
| checkpoint | `Checkpoint name` · `Saved as: <name>` · `Keep` · `The files of this save are no longer kept by the manager. Save again, then keep that save.` |
| starting point | `Make this save the starting point of <lab>? No device is read or changed.` · `It replaces the current starting point, saved <when>. The previous one stays in the history.` · `Use as starting point` · `Replace the starting point` · `Cancel` |
| different | `Different from your latest save` · `How <name> differs from the last save of <lab>. To see what would change on the devices, choose Load this state…: the devices are compared before anything is loaded.` · `No differences: this version matches your latest save.` |
| files | `Devices` · `Topology and map` · `Files Load uses` · `Save details` · `Saved without its topology file.` |
| empties | `No saves yet. Save makes the first one.` · `No checkpoints yet. Keep a save as a checkpoint to hold on to it.` · `No lab states in this repository yet.` |
| load states | `Loading the saved versions…` · `The saved versions could not be loaded.` · `Try again` · `Check the VM connection…` |
| foot | `Full history…` · `Browse the repository…` · `Save as a lab state…` |
| Save settings: title / meta | `Save settings` / `Where <lab> saves, and which devices each save includes.` |
| sections | `Save location` · `Devices included in every save` · `Git details` |
| buttons | `Change folder…` · `Use a different repository…` · `Connect by URL…` · `Refresh status` · `Update from the repository` · `Disconnect this lab…` · `Save settings` · `Choose a place…` |
| states | `This lab has no save location yet.` · `Choose at least one device to include.` · `A save is still waiting to be uploaded. The devices can be changed once it is uploaded or kept on the VM only.` · `Upload…` · `Keep it on the VM only` · `<device> is no longer included. Its saved file leaves the next save; older versions keep it.` · `Save settings updated.` |
| disconnect | `Upload it, then disconnect` · `Disconnect and keep that save on the VM only` · `Disconnect` |
| keep on the VM (today "Keep snapshot only") | title `Keep this save on the VM only?` · button `Keep it on the VM only` |
| chooser: heads | `Where should <lab> save?` / `Pick a folder, type a path, or make a new folder.` · `Browse the repository` / `Every folder of <repo>. Looking at folders does not change where <lab> saves.` |
| chooser: field and result | `Repository` · `Folder` · `Saves go to <repo> › <path>` · `… › top level` |
| marks | `This lab saves here` · `<Lab> saves here` · `Lab state: <Name>` · `New` |
| answers | as in the table of 4.5 |
| chooser: buttons | `Save here` · `Keep saving here` · `Save in <path>` · `Use this folder anyway` · `Save beside it in <path>` · `Replace it` · `Upload it, then move` · `Move and keep that save on the VM only` · `New folder…` · `Add` · `Remove from the list` · `Cancel` · `Saving here…` |
| chooser: notes | `Move the saves made so far into the new folder` · `<path> already exists. It is selected.` · `<path> is part of a saved state, so the new folder is made in <folder above>.` · the state sentences of 4.9 |
| toast | `<lab> now saves to <repo> › <path>.` |
| lab state: head | `Save as a lab state` / `Saves <lab> as it is now into a folder of its own. Where <lab> normally saves does not change.` |
| lab state: fields | `Name` · `start` · `broken` · `final` · `The state is saved in <repo> › <path>` · `Put it somewhere else` · `Save state` · `Reads every included device now. Saved files can contain passwords or keys.` |
| lab state: progress | `Saving the state <Name>…` · `State <Name> saved in <path>.` |

### 8.2 Classes

Shared base names used: `save-list`, `save-devices`, `save-dot`, `save-panel`, `save-chip` (the last three
only through the header's pieces).

Added by this slice:

| Class | Replaces (Appendix A) | Use |
|---|---|---|
| `save-drawer` | `rx-drawer`, `px-drawer` | `dialog.save-drawer{width:min(760px,100vw)}` and the drawer's inner spacing |
| `save-drawer-foot` | `px-drawer-foot` | the foot row of settings and chooser |
| `save-back` | none | the Back button in the head |
| `save-h`, `save-h-row` | `rx-h` | group headings; a heading with an action beside it |
| `save-item`, `save-when`, `save-why` | `rx-ver`, `rx-when`, `rx-why` | a row of `save-list`, its right-hand text, its second line |
| `save-open` | `rx-open` | the row opened in place |
| `save-row` | `rx-row` | a row of buttons |
| `save-quiet` | `rx-quiet` | the quiet text button |
| `save-note` | `rx-note` | the small note |
| `save-foot` | `rx-foot` | the closing links of a list |
| `save-fold` | `.px-drawer details` | a folded group |
| `save-also`, `save-plain` | none | the artifact fold inside a diff entry; the plain file list |
| `folder-chooser`, `folder-tree`, `folder-row`, `folder-name`, `folder-answer`, `folder-names` | none | the chooser |
| `git-tag state` | none | the lab-state mark (same shape as `git-tag other`) |

`save-row`, `save-quiet`, `save-note` and `save-h` are needed by the header's panels as well; the lead
settles the names once (Q6). Reused as they are: `drawer`, `drawer-head`, `drawer-meta`,
`drawer-content`, `dialog-head`, `icon-button`, `button` and its variants, `git-destination-line`,
`git-node-scope`, `checkbox-label`, `kv`, `form-help`, `form-error`, `banner`, `pill`, `badge`,
`git-tag`, `git-twist`, `git-folder-icon`, `git-file-icon`, `git-listing`, `diff-*`, `sr-only`.

No new colour is used: marks and rows take existing tokens, so no contrast figure changes. The focus
ring is the existing two-tone ring; tree rows get it through an inset outline like
`.git-outline summary:focus-visible` (`app/static/style.css:2323`).

CSS that leaves with the tab: `.git-progress-bar` (`app/static/style.css:1966-1980`),
`.git-binding-form` (`:1982-1991`, `:2005-2007`), `#git-saves-list` and `.git-saved-job` (`:2020-2054`),
`.git-versions-head`, `.git-version-group`, `.git-version-list`, `.git-version-row`,
`.git-versions-empty`, `.git-version-when` (`:2463-2472`, `:2486-2487`, `:2505`), `.git-change-folder`,
`.git-first-folder` (`:2478-2480`), `.git-places*`, `.git-crumbs`, `.git-outline*` (`:2091-2151`,
`:2167`, `:2389-2390`, `:2481-2484`). Each selector is searched in scripts, HTML, tests and tools before
it is deleted.

### 8.3 File plan

| File | Change |
|---|---|
| `app/static/save-drawers.js` | new: the drawer shell, What changed, All versions, Save settings |
| `app/static/git-places.js` | rewritten in place: the chooser (three modes), `folderClean`, `folderKey`, the tree markup; pure helpers kept |
| `app/static/git-progress.js` | per 6.3 |
| `app/static/app.js` | `PANELS`, `TAB_ALIAS`, `SAVE_VIEWS`, `setTab`, `showTab` (6.2); the banner actions (6.5); `render()` calls `saveDrawerRender` behind a `typeof` guard |
| `app/static/index.html` | per 6.1; one new script tag |
| `app/static/style.css` | 8.2 |
| `app/static/shell.js` | one sentence (`:183`); the `#git-save-menu` selectors follow the header slice |
| `app/static/network-design.js`, `app/static/operations.js` | the strings and the one call of 6.4 |
| `app/git_progress.py`, `app/discovery.py` | messages of 6.4 and N1 to N9 (lead) |
| tests | 7 |

Load order in `index.html` (`:3`): … `diff-view.js`, `git-progress.js`, `git-places.js`,
**`save-drawers.js`**, `restore.js`, … Functions of other files are read at call time behind `typeof`
guards, so the header's script may load before or after. The new tag carries `?v=<release>` like every
other (`deploy/verify-release.py` refuses a page asset without it); only `index.html` loads it. No
framework, no build step, no CDN, no inline style, `esc()` on every interpolation, `setMarkup` for
everything the poll re-renders.

### 8.4 Friction budget (designed, not measured)

| Task | Clicks | Path |
|---|---|---|
| Change folder | 4 | chip → **Change…** beside the save location in the chip panel (Q1) → folder → **Save here** |
| | 5 | chip → **Save settings** → **Change folder…** → folder → **Save here** (the path the prompt names) |
| | 4 | the same path with a typed folder: focus lands in the path field, Enter confirms |
| with a folder question | same | the answer button is the confirmation |
| with a waiting save | same | the two choices replace the confirm button |
| Save as a lab state | 4 + nothing typed | chip → **Save as a lab state…** → `start` → **Save state** |
| | 3 + the name | chip → **Save as a lab state…** → type → **Save state** |
| See what an upload sends | 1 from the panel | **See changes** |
| Load a state from All versions | chip → **All versions** → row → **Load this state…**, then the Load confirmation | |

The budget of four clicks for a folder change is met only through Q1 or by typing; through Save
settings with a mouse pick it is five. This is stated rather than hidden: the count must be measured on
the build (PROMPT 9.5).

Refusals and dead ends this design removes from the page: the twelve reasons of `gitFolderChoice`
(`app/static/git-places.js:92-119`); the disabled New folder… and its caption (`:156`, `:158`); the
disabled "Save this lab here" on the lab's own folder (`:111`); the errors of `gitFolderName` and
`gitFolderPath` (`:14`, `:25`, `:27`); "A folder named … already exists" (`app/static/git-progress.js:464`);
the two-step "choose the folder, then tick the devices and Connect" (`:447`, `:481`); the required
exposure tick box (`:299`, `:496`, `:522`); the baseline tick box error (`:605`); the disconnect notice
with no way on (`:721`).

### 8.5 Assumptions

1. The backend gives one answer per folder (N6) and one request for Save here (N7). Until it does, the
   chooser cannot be built without copying rules into the page, which is the defect being removed.
2. A saved state keeps its manifest-referenced layout, so View files can group by `node`, `kind` and
   `restore_artifact` from the manifest the version route already returns.
3. The save route's `backup_job_id` path accepts `target: 'checkpoint'` (PROMPT 7.4) and keeps accepting
   `target: 'baseline'` with `replace_baseline` and `expected_baseline`.
4. The save window (`git-job-dialog`), Full history, Update from the repository, Use a different
   repository and Connect by URL stay centred dialogs; opening one closes the drawer
   (`closeDialogsExcept`), and they do not return to it.
5. A lab's saves are listed from its jobs; the manager keeps the newest 200 jobs per installation, never
   dropping a pending one. Older saves are reached through Full history.
6. `#save-chip` is the chip button's id and `saveOpenPanel` its opener (header slice).
7. The mockups' wording loses to the prompt where they differ: "Load this state…", "Lab states",
   "Choose one to load it".

### 8.6 Open questions for the lead

- **Q1. Four clicks for a folder change.** Through Save settings a mouse pick takes five. Adding the
  save location with **Change…** to the chip panel at rest (today's status card has exactly that,
  `app/static/index.html:140`, addendum H10) makes it four. Accept that line in the panel, or accept
  five?
- **Q2. Device changes and disconnect while a save waits.** Keep the constraint and show the two
  buttons (3.3), or resolve it in the backend like a folder change (N5)?
- **Q3. What is a "Lab state" and what is it called.** Today the group depends on distance from the
  lab's folder and the names are "Final state (instructor)", "Starting state"; the prompt wants every
  other saved state under Lab states, named Start, Broken, Final. One function (or N3's `group` and
  `name`) must serve the Load panel, this drawer and the chooser's marks. Which rule, and does "Everything
  else" then still have members?
- **Q4. A device removed from the save.** `allow_removed` has no home once the save options dialog is
  gone; without one the next save is refused by the helper (3.3). Send it automatically after the
  person unticked the device in Save settings, or ask in the chip panel after the refusal?
- **Q5. Moving the earlier saves on a folder change.** Keep today's ticked box (one line in the
  chooser), always move, or never move (the old folder then shows up as a lab state of its own)?
- Q6. The shared names for `save-row`, `save-quiet`, `save-note`, `save-h` (header and drawers both
  need them).
- Q7. Where a lab state is saved for a lab at the top level of its repository, and for a lab with no
  save location ("beside the lab's own folder" has no meaning there). The chooser shows whatever default
  path it is given.
- Q8. Whether folder moves stay their own job kind with their own review; the drawer supports them as
  today.
- Q9. "Keep snapshot only" is renamed "Keep it on the VM only" here, to match Not now; it is the same
  dismiss route. Accept the rename (it touches Python messages)?

### 8.7 NEEDS (backend), in one place

| # | Need |
|---|---|
| N1 | job compare: per file `role` and `node`, read from the manifest |
| N2 | `upload_blocked` as `{lab_id, lab_name, message}` |
| N3 | one list of saved states per repository: `path, commit, name, group, lab, kind, devices, loadable, files, saved_at` |
| N4 | list, view, download and compare for a lab without a save location (by repository) |
| N5 | reword `guard_pending` (and `discovery.py:669`), or allow a device change with an inline choice |
| N6 | tree answer: per folder one `answer` (`free`, `this`, `lab`, `state`, `inside`) with `choices`, plus `below` and `new`; `?lab=` names the asking lab |
| N7 | one `place` request for Save here (first place and change, any repository) that answers `{question}` instead of refusing |
| N8 | every folder listed even when the file list is cut at 4000 |
| N9 | a save into a folder other than the lab's own (`state`), answering `{question}` like N7 |

### 8.8 What a reviewer should attack

1. **The accounting of 1.2.** Find a save whose upload sends a file the drawer does not show: a
   checkpoint save, a baseline, a state replaced in place, a device removed, a rename, a save reusing
   HEAD, and above all the earlier commits (`also_sends` is a count with names, not a file list: is a
   count enough to call them "visible"?).
2. **The single sender.** Can any path reach `{push: true, reviewed: true}` without the sentence of that
   very job having been on screen: the chooser's "Upload it, then move", a stale review after the job
   changed, two tabs?
3. **One answer.** Is there any text in the chooser that is computed in the page from something other
   than `answer` / `below`: the default path of a lab state, the hidden insides of a saved state, the
   provisional `New` row?
4. **`below` for typed paths.** Does "nearest existing ancestor" give the right answer for a path under
   another lab's folder, under a state, under a planned folder, and in a truncated tree where the
   nearest listed ancestor is not the nearest real one?
5. **Open branches.** Any render path where `aria-expanded` follows the selection instead of
   `gitPlacesState.expanded`, including the typed path, the new-folder row and a repository switch.
6. **The router.** `view=progress` with a device (`&device=R1`), on an unknown lab, before the first
   state, with the header script not yet loaded, twice in a row; Back after the rewrite; the poll
   reopening the panel.
7. **Lost functions.** Walk every row of 6.1 and 6.3 against the build: Remove empty folder, the saves
   that failed before the newest one, Keep snapshot only, the legacy-folder notice, the administrator
   setup text, the per-folder Apply, View configuration backup in the save window.
8. **Disabled controls.** Each remaining disabled state (Upload blocked, Save here while loading or
   with the VM unreachable, Save settings with a waiting save, Keep as a checkpoint without a capture,
   Load on a view-only state) must show its reason as text and the clearing action beside it. New
   folder… must have none.
9. **Keyboard and focus.** The tree as one tab stop; Escape in the new-folder field versus Escape in the
   drawer; focus after Back, after Save here, after the drawer closes onto a panel that is gone.
10. **The poll.** A drawer open for ten minutes: does a re-render move focus, close the open row, reset
    the device ticks, refetch the tree, or drop a half-typed path?
