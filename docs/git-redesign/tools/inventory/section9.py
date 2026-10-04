"""Section 9 of docs/git-redesign/inventory/REFUSALS.md (R1, R2), written by fill_outcomes.py; `{COUNTS…}` are computed."""

SECTION9 = r'''
## 9. New outcomes

The last column of every row. **R1** filled sections A to D from `claude/git-save-load-redesign` at a98d870 and
found F1 to F4 and M1 to M5. **R2** (branch `slice/r2-refusals`, cut from 2578f22, after the Progress tab was
removed and the R1 findings were acted on) filled section E from the finished page and corrected every row of A to D
whose outcome changed. Both passes are read-only and by a checker who wrote none of the code. No `TBD` is left.
The "try to get blocked" pass in the fixture is reported separately in
`docs/git-redesign/evidence/blocked/FINDINGS.md`.

### 9.1 How the column was filled

- `docs/git-redesign/tools/inventory/match_refusals.py` takes each row's text (placeholders as written) and looks
  for it among today's texts: an `ast` walk of the helper, the manager, the place routes, the restore service, its
  drivers and the deploy scripts (every raised message, module constants and one-line sentence functions included,
  plus every string of three or more words), and the lines of `deploy/setup-git.sh` and of the page scripts as
  plain text. It answers `same`, `moved`, `near` or `gone`; `--new-since 68f24d9` lists the texts the same files
  did not raise at the inventory's base (the merge of 1.30.60 into `main`). `problem_codes()` reads
  `HELPER_PROBLEMS`, its `update({...})` for placements and `MANAGER_PROBLEMS` with the helper's constants, so a
  cell can name the chip code a sentence gets.
- R2: `remap_lines.py a98d870 2578f22` moved every `app/*.py` line reference of R1's decisions to today's lines;
  the references in changed blocks were checked by hand, the page references were rewritten by hand.
- Every cell was decided by reading the code around the hit, never from the text alone. The decisions are in
  `outcomes_ad.py` (A to D, the R2 corrections in its last block, then E); `fill_outcomes.py` writes them and this
  section (rerunnable; `--check` prints the counts and fails when a row has no decision).
- 490 rows: A 167, B 149, C 49, D 63 (R1), E 62 (R2).
- Paths: `app/` is `clab-backup-ui/app/`; page scripts are named by file (`app/static/`). Line numbers are of 2578f22.
- "Choice:" in an F or S cell answers whether a person's choice in the manager can still end in that refusal.
- "Kept, not reachable through the page" for a row of E means dead code: the function is still in the file and
  tested, but no page script calls it (9.6 M6).

### 9.2 The chip panel per code, as the page shows it at 2578f22

A text the helper's `status`, `publish`, `push`, `move` or `update` answers, and since R1 also what `register-prefix`
and `connect` answer when a lab or a lab state is placed (`placement_refused` app/git_progress.py:1015-1022), is
mapped by `problem_code` (app/git_progress.py:459-465) through `HELPER_PROBLEMS` (:302-438) and
`MANAGER_PROBLEMS` (:441-455). `saveProblem` (status.js:350-379) shows:

| Code | Sentence | Actions |
|---|---|---|
| `vm` | `The lab VM could not be reached.` | Try again · Check the VM connection… |
| `account` | `The VM account cannot upload to <host>.` | Try again · Details |
| `busy` | `Someone is working in this repository on the VM.` | Try again · Details |
| `diverged` | nothing waits: `The online copy has changes this VM does not have.`; saves wait: `The online copy and this VM both have changes the other does not have. They have to be combined on the VM.` | Update from the repository; with saves waiting Try again · Details and the owner's two commands (`git -C <checkout> pull --no-rebase`, `git -C <checkout> push`) |
| `files` | `<folder> holds files that were not saved by the manager.` | Choose another place · Details |
| `settings` | `This lab’s save location has to be set up again.` | Save settings · Details |
| `devices` | `No device of this lab is selected for saving.` | Save settings |
| `device` (a job ended `capture_incomplete` because a device failed) | `<device> could not be read, so nothing was saved.` | Try again · Save settings · Details |
| `capture` (the manager stopped the capture for its own reason) | the manager's sentence | Try again · Details |
| `other` | `The save did not work.` | Try again · Details |

A refused placement is shown in the chooser and in the first-save panel with that code's sentence and the
manager's text under Details, or with the manager's text itself for `other` (`drwChooserRefused`
save-drawers.js:609-619).

### 9.3 Counts (category by outcome)

Sections A to D:

{COUNTS}

Section E:

{COUNTS_E}

All 490 rows:

{COUNTS_ALL}

### 9.4 Every category-F row (the evidence for G2)

| Row | Rule | Outcome at 2578f22 |
|---|---|---|
| R-003 | reserved names (helper) | Kept, not reachable through the page: step 2 uses the folder above; the old routes are not called. |
| R-092 | other kind of snapshot | Kept, chip `files`; only a hand-committed design manifest at a lab's `latest` or `baseline` meets it. |
| R-095 | files outside the manifest | Kept, chip `files` with **Choose another place**; listed in DESIGN 3.6 and 2.3 "Not changed". |
| R-096 | non-empty folder without manifest | Kept, as R-095 (listed in 3.6). |
| R-126 | move into the own folder | Kept, not reachable through the page. |
| R-136 | move target holds saved files | Kept as a guard; neither the chooser nor the old destination route queues that move any more (F4 closed). |
| R-146 | overlap | Gone (H1); a real collision is replaced or asked about (question 1); no page path shows the helper's sentence. |
| R-154 | overlap re-check under the registry lock | Kept as a race: question, or chip `busy` with Try again, which reuses the folder. |
| R-171 | reserved names (manager) | Kept, not reachable through the page (old routes only; F4 closed). |
| R-243 | carrier of R-171 | Kept, not reachable through the page. |
| R-244 | at or below a saved configuration | Gone (DESIGN 4); its browser copy is dead code (M6). |
| R-249 | one registration per lab (connect) | Kept, not reachable through the page (F2 closed): the place route asks question 1. |
| R-262 | one registration per lab (PUT) | Kept, not reachable through the page (F3 closed). |
| R-265 | folder name taken | Gone: the existing folder is selected. |
| R-272 | the lab's own folder | Gone: answered without a change. |
| R-273 | another lab's folder (destination) | Kept, not reachable through the page (F4 closed). |
| R-383 | reserved names (wizard) | Reworded; terminal only, the wizard asks again. |
| R-387 | root would overlap (wizard) | Gone (H1): blank is accepted. |
| R-422 | overlap (CLI registration) | Gone (H1); a real collision only, terminal only. |
| R-432 | reserved names (browser) | Kept, not reachable: dead code; the chooser uses the folder above and says so. |
| R-434 | `latest` resolves to its parent (browser) | Kept, not reachable: dead code; live: the folder above, said in the sentence. |
| R-435 | `baseline`/`checkpoints` of a lab (browser) | Kept, not reachable: dead code; live: the folder above, not listed in the tree. |
| R-436 | a checkpoint (browser) | Kept, not reachable: dead code; live: the lab folder above. |
| R-437 | a folder holding manifest.json (browser) | Kept, not reachable: dead code; live: question 2 (Save beside it · Use this folder anyway). |
| R-438 | below a saved configuration (browser) | Kept, not reachable: dead code; live: `free` (disjoint) or the folder above. |
| R-439 | inside another lab's folder | Gone (H1). |
| R-440 | this lab's own folder (browser) | Kept, not reachable: dead code; live: `<lab> already saves here.` · Keep saving here. |
| R-441 | another lab's folder (browser) | Kept, not reachable: dead code; live: question 1. |
| R-442 | a registration no lab uses | Gone (H1, 2.4). |
| R-443 | the top level beside lab folders | Gone (H1). |
| R-444 | subfolders below a top-level lab | Gone (H1). |
| R-445 | a folder above lab folders | Gone (H1). |
| R-446 | New folder… disabled | Gone: always enabled. |
| R-448 | the same, as a caption | Gone. |
| R-461 | a folder name taken (browser) | Gone: the existing folder is selected. |

**Verdict on G2 from the code.** No folder refusal of the 35 category-F rows can be reached from the page at
2578f22: every one is Gone, a question, a guard the page cannot reach, or one of the outside causes DESIGN 3.6
lists (R-092, R-095, R-096). Whether the page behaves so in a browser is the subject of the blocked pass
(FINDINGS.md).

### 9.5 The R1 findings

- **F1 Closed.** The helper cuts a label it generates (`folder_label` app/host_git.py:1328-1341, used by
  `plan_prefix` :1375 and `plan_connect` :1396); only a label typed for `setup-git.sh --label` keeps the check
  (:1348). R-145 is no longer reachable through the page.
- **F2 Closed.** Connect by URL… is the chooser's address mode (`gitRunAction('connect')` git-progress.js:418,
  save-drawers.js:702), posting POST …/git/place with `url` (save-drawers.js:578-590); no page script calls
  …/git/connect (tests/test_save_router_ui.js:113-118).
- **F3 Closed.** Use a different repository… opens the chooser on the chosen repository, or its address mode
  (`gitSwitchRepository` git-progress.js:132-139); Save settings saves its devices through POST …/git/place
  (save-drawers.js:449); no page script sends PUT …/git (the same test).
- **F4 Closed.** The Progress tab, `gitUseFolder`, `gitNewFolder` and `gitFirstSave` are gone (index.html has no
  `#progress-view`); no page script calls …/git/destination or POST …/folders; `destination` moves files only when
  `brings_files` holds (app/git_progress.py:553-558, 1818-1830). Dead functions of the old browser are left (M6).

### 9.6 The R1 deviations, and what R2 adds

- **M1 Closed.** `settings` reads `This lab’s save location has to be set up again.` · Save settings · Details
  (status.js:376); `devices` exists (status.js:162, 377) and NO_DEVICES is recorded with it
  (app/git_progress.py:452, 1903-1911).
- **M2 Closed.** Commits not made by manager saves map to `busy` (app/git_progress.py:345-346).
- **M3 Closed.** A capture stopped for the manager's own reason shows the manager's sentence (`capture`,
  status.js:357-369).
- **M4 Closed.** A connection change waits up to 10 s for another one (`CONNECTION_WAIT` app/git_progress.py:57,
  1080-1090); only a clone that holds the lock longer still answers `Another repository connection is being changed.
  Try again in a moment.` (transient).
- **M5 Closed.** The old folder browser is no longer shown; its refusals are dead code (M6).
- **M6 Open (cosmetic, code hygiene).** git-places.js keeps the old browser's refusing helpers with no page caller:
  `gitFolderName` (:9-13), `GIT_RESERVED_FOLDER_MESSAGE` and `gitFolderPath` (:19-27), `gitDestinationPreview`,
  `gitSavesHoldingLab`, `gitNewFolderRefusal` (:113-122), `gitFolderChoice` (:124-148), `GIT_NO_NEW_FOLDER` and
  `gitCanCreateIn` (:151-156), `gitFolderTag`. Only tests/test_git_places_ui.js uses them. Nothing reaches a person,
  but a later page change could call them again; removing them (and rewriting those tests to the chooser) closes it.

### 9.7 Decided since R1, and what reading alone does not decide

- **Decided.** A typed folder through a committed file (`README.md/x`) is corrected, never refused:
  `past_files` (app/git_places.py:160-171) makes it `README.md-2/x` with `adjusted: 'past-file'`, and the chooser
  says `README.md is a file in the repository, so <lab> saves in README.md-2/x.` (git-places.js:380-384).
- **Decided.** A 409 of an upload (ANOTHER_SAVE, NOT_OURS, REVIEW_FIRST) makes `gitReviewJob` read the review again
  and redraw the panel and the drawer before the error is shown (git-progress.js:298-316).
- **Decided.** R-136 through the old route: `destination` now applies the same rule as the chooser.
- **Not decided by reading.** R-092: no page flow lands a capture on a design manifest; only a hand commit was found.
- **Not decided by reading.** R-136 through the chooser: a race between the checkout view (cached 10 s) and the move.
- The browser behaviour of every flow above is tried in the blocked pass (FINDINGS.md).

### 9.8 New refusals since 1.30.60

From `match_refusals.py --new-since 68f24d9` (the helper, the manager, the restore service, the deploy scripts) and
from reading the page scripts that did not exist in 1.30.60 (save-header.js, save-drawers.js, load.js) and the
rewritten ones. Rewordings of an old row are in that row. Not listed: the drivers (unchanged), `unreadable endpoint`
(app/restore.py:280, never shown), informational lines (`MOVE_REASONS` app/git_place.py:45-52, `UPDATED_FIRST`
app/git_progress.py:59, an event) and question sentences.

Helper, manager and restore service:

| # | Text | Where | Trigger | Cat | How it reaches the person |
|---|---|---|---|---|---|
| 1 | `The folder <P> is inside <S>, where the lab folder <O> keeps its saves; choose a folder above that saved state.` / `The lab folder <O> is inside <S>, where <P> would keep its saves; choose another folder for this lab.` (`is where` when it is that folder) | app/host_git.py:170-179, raised :1356; deploy/setup-git.sh:104 | a folder in another registration's saved states, or holding one in its own (H1) | F | place route: never shown (replace or question 1); old routes: not called by the page; setup-git.sh: terminal |
| 2 | `The online copy of this repository has changes this VM does not have.` | app/host_git.py:54, 568 | a further folder while the remote branch is not an ancestor of HEAD (H2) | X | 409 of the place route, recorded as code `diverged`: the chooser shows the chip sentence and offers Update from the repository |
| 3 | `This checkout has commits that were not made by manager saves.` | app/host_git.py:55, 570 | a further folder over commits that are not verified manager saves (H2) | X | 409 of the place route, code `busy` |
| 4 | `A save made in that folder still waits for upload.` | app/host_git.py:59, 603 | retiring a registration with a waiting save (H7) | S | place route: question 1 with one button (app/git_place.py:290-299); never a status (`NOT_A_STATUS` app/git_progress.py:439) |
| 5 | `The online copy could not be asked whether a save made in that folder still waits for upload.` | app/host_git.py:60, 601-602 | H7 with an unreachable remote | X | as row 4; code `account` if it reaches a status |
| 6 | `The manager could not start the repository; connecting again retries it.` | app/host_git.py:57; 1158, 1167-1192 | H4 *Start the repository* failed | X | 409 of the place route, code `other`: the sentence itself in the chooser |
| 7 | `README.md was pushed to start the repository, but other branches or tags appeared at the same time; connecting again finishes it.` | app/host_git.py:58, 1191 | H4 race | X | as row 6 |
| 8 | `The repository has branches or tags but no branch <b>, which the VM folder <path> was cloned for; nothing was changed.` | app/host_git.py:182-183, 1147 | an empty clone whose remote now has other refs | X | 409 under the address field (`clean_text` keeps it) |
| 9 | `The VM folder <path> holds files that are not in the repository; nothing was changed.` | app/host_git.py:186-187, 1149 | an empty clone's folder holds files | X | as row 8 |
| 10 | `The VM folder <path> could not take the repository's first commits; connecting again retries it.` | app/host_git.py:190-191, 1152-1161 | finishing an empty clone failed | X | as row 8 |
| 11 | `Invalid connect option.` | app/host_git.py:1486 | `initialize` not a boolean | V | not reachable (the manager sends a boolean) |
| 12 | `Another save was made in this repository. Look at the changes again.` | app/git_progress.py:48, 2203 | Upload while HEAD is no longer the reviewed one, and since R1 also an upload that names no HEAD | S | 409 of the upload; the page reads the review again (9.7) |
| 13 | `The repository on the VM has changes the manager did not make.` | app/git_progress.py:49, 2206 | Upload while no manager save is at HEAD | X | 409 of the upload; code `busy` |
| 14 | `The repository on the VM could not be checked. Try again.` | app/git_progress.py:2202 | Upload: `status` named no HEAD | X | 409 of the upload |
| 15 | `Upload the waiting saves first; the online copy can only be fetched when nothing waits here.` | app/git_progress.py:53, 2236 | Update from the repository while saves wait | S | 409; the chip offers Upload instead (3.6) |
| 16 | `A save is still waiting to be uploaded. Upload it, or open its Details and choose Keep snapshot only, then try again.` | app/git_progress.py:54, 988 | Remove lab or Start fresh while a save needs attention (app/main.py:211, 247) | S | 409 in those dialogs (R-222 reworded) |
| 17 | `This capture does not include the topology. Save again first.` | app/git_progress.py:50, 1976 | a checkpoint or starting point from a capture without the topology (3.9) | S | 400; the page disables the choice and says this sentence (save-header.js:156, save-drawers.js:214) |
| 18 | `The topology could not be saved with this capture. Try again.` | app/git_progress.py:51, 1294 | the capture recorded a topology or map write error (3.9) | O | job `capture_incomplete`, chip `capture` with this sentence |
| 19 | `None of the devices this lab saves exist in it any more. Choose the devices under Save settings.` | app/git_progress.py:52, 1903-1911 | a save or lab state with no selected device left (3.3) | S | 409, chip `devices` |
| 20 | `Use a name of at most 120 characters.` | app/git_progress.py:472 | a save, rename or lab-state name over 120 characters | V | 400 under the name field |
| 21 | `Give the lab state a name.` | app/git_progress.py:2032 | Save as a lab state… with an empty name | V | 400 in the drawer |
| 22 | `Choose Replace it or another name.` | app/git_progress.py:2036 | a `choice` other than `''` or `take` | V | not reachable |
| 23 | `Choose the repository this lab state is saved in.` | app/git_progress.py:2050 | a lab state without `repository` for a lab without a save location | V | 400 in the drawer |
| 24 | `A lab state is being saved into this folder right now. Try again when it has finished, or choose another folder.` | app/git_progress.py:1474 | old …/git/connect into a folder a lab state is being saved into | S | not reachable through the page (F2 closed); the place route asks question 2 |
| 25 | `Could not store the name. Nothing was changed.` | app/git_progress.py:2164 | rename: the store write failed | O | 500 |
| 26 | `A folder path can be at most 500 characters long.` | app/git_places.py:24, 38, 225; app/git_place.py:316-337, 429-446, 505-511 | a typed path over 500 characters (2.5 step 1), and since R1 a path that grows over 500 when a part is moved past a file (`past_files`) | V | 400 in the chooser; the fields have `maxlength="500"` |
| 27 | `Choose a repository, or paste the address of one.` | app/git_place.py:36, 320 | a place request with both or neither of `repository` and `url` | V | not reachable |
| 28 | `This repository is not on the VM. Refresh the list.` | app/git_place.py:37; 115, 499 | a registration that left the VM's list | S | 404 in the chooser |
| 29 | `The VM did not answer with the repository folder. Try again.` | app/git_place.py:38; 261, 369 | the helper's answer has no id or path | X | 409 in the chooser |
| 30 | `The VM could not use this folder right now. Try again in a moment.` | app/git_place.py:39, 58-61 | stands in for a helper sentence naming `registration`, `prefix` or `overlap` | X | 409 in the chooser, with the chip sentence of the helper sentence's code |
| 31 | `The repository did not name its newest commit. Refresh the list and try again.` | app/restore.py:634 | a folder source read through another registration whose `history` has no HEAD | X | 409 in the Load panel |
| 32 | `Resolve the problem reported above, then retry the original registration command.` | deploy/setup-git.sh:144 | a registration failed for a reason other than identity or login | X | terminal |

The page (new or rewritten since 1.30.60; each disables or refuses something):

| # | Text | Where | Trigger | Cat | How it reaches the person |
|---|---|---|---|---|---|
| P1 | `The place to save is being set.` / `<what runs> Save is available when it finishes.` | save-header.js:298-300 | Save while a placement of the lab or other work runs | S | header Save disabled, the sentence under it (#save-reason) |
| P2 | `Looking for a place to save…` | save-header.js:401 | first save clicked before the default place arrived | S | error line of the first-save panel |
| P3 | `This lab has no device whose configuration can be saved.` | save-header.js:177-181 | a lab without devices (unbound) or a binding with no device (bound) | O | first-save panel without a Save button; Change… stays |
| P4 | `The capture of this save is no longer kept. Save again to make a checkpoint.` / `This capture does not include the topology. Save again first.` / `Kept as checkpoint <name>.` | save-header.js:156-158; save-drawers.js:213-219 | Keep as a checkpoint / Use as starting point… on a save whose capture is gone, lacks the topology, or was kept already | S | tick box or buttons disabled, the sentence beside them, with **Save** |
| P5 | `Checking what this upload sends…` | save-header.js:123-127; git-places.js:368-372 | Upload (and *Upload it, then move*) before the review answered | S | button disabled, the sentence beside it |
| P6 | `What this upload sends could not be read from the lab VM.` / `Someone is working in this repository on the VM.` | save-header.js:125 | the review failed, or no manager save is at HEAD | X | Upload replaced by Try again |
| P7 | `See what this upload sends before uploading.` | git-progress.js:304 | an upload asked without a review in the page's memory | S | error of the caller |
| P8 | `The devices could not be saved. Open Change folder… and choose the folder again.` | save-drawers.js:450 | Save settings: the place request with the new devices did not answer `saved` (a question) | O | Save settings error line |
| P9 | `The upload did not finish, so nothing moved.` / `The upload is still running. Nothing moved.` | save-drawers.js:565, 568, 641 | *Upload it, then move* when the upload fails or is not done after 3 minutes | X | chooser error line with Try again |
| P10 | `The folders are still loading.` / `The lab VM cannot be reached, so its folders cannot be shown.` | git-places.js:479-480, 510-513 | Save here before the tree arrived, or with the VM unreachable | S/X | Save here disabled, the sentence beside it; Try again · Check the VM connection… |
| P11 | `Paste the HTTPS address, for example https://github.com/you/your-lab-repo.` | save-drawers.js:585; save-header.js:18, 396 | an address that is not `https://host/path` | V | error line (R-462) |
| P12 | `The repository cannot be started from this page.` / `Upload is not available on this page.` / `This part of the page did not load. Reload the page and try again.` / `Loading is not available on this page.` | save-drawers.js:638, 716; save-header.js:20; git-progress.js:135, 405; restore.js:167 | a script of the page did not load | O | error line or toast (a broken page only) |
| P13 | `A save is running.` / `Tick at least one device.` / the busy reason | load.js:244-251 | the red Load during a save, with nothing ticked, or while work runs | S | Load disabled, the sentence beside it |
| P14 | `<name> can be loaded in a moment.` with the reason; `<name> cannot be loaded right now.` | load.js:275-282 | a preflight refused (busy: a wait; otherwise the manager's sentence) | S/X | Load panel with Try again (disabled while the hold lasts) and Back |
| P15 | `Start the lab to load a state` with Start lab (disabled with the lab's own reason) | load.js:179-182 | Load on a lab that is not running | S | Load panel |
| P16 | Undo this load disabled with its reason, or `<what runs> Available when it finishes.` | load.js:380-384 | undo not possible (its backup is gone) or work runs | S | button disabled, the reason as a note |
| P17 | `Save this lab once first (Save in the lab’s header): the export goes into the folder the lab saves to.` | network-design.js:887 | a design export of a lab without a save location | S | the export button disabled with this caption (R-475 reworded) |
'''
