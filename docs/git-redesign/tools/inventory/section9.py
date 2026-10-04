"""Section 9 of docs/git-redesign/inventory/REFUSALS.md (R1), written by fill_outcomes.py; `{COUNTS}` is computed."""

SECTION9 = r'''
## 9. New outcomes

The last column of sections A to D, filled on 2026-10-04 from the code of `claude/git-save-load-redesign` at
a98d870 (branch `slice/r1-refusals`), read-only, by a checker who wrote none of that code. **Section E (R-429 to
R-490, the browser) stays `TBD`**: the page is still changing (slice S11 removes the Progress tab); it is filled
later with the same scripts.

### 9.1 How the column was filled

- `docs/git-redesign/tools/inventory/match_refusals.py` takes each row's text (placeholders as written) and looks
  for it among today's texts of the helper, the manager, the place routes, the restore service and its drivers and
  the deploy scripts (an `ast` walk that renders every raised message, module constants and one-line sentence
  functions included, plus every string of three or more words, plus the lines of `deploy/setup-git.sh` and of the page scripts, as plain text):
  `same` (raised in its own file), `moved`, `near` (closest text and ratio) or `gone`. With `--new-since 68f24d9`
  (the merge of 1.30.60 into `main`, the inventory's base) it lists the texts the same files did not raise there.
  Final run for A to D: 390 same, 6 moved (R-244, R-288 and R-355 are found only in a page script, R-423 to R-425
  moved into the helper), 12 near, 20 gone; every `near` and `gone` row was then located by hand (R-369, R-408 and
  R-428 are still raised: concatenations or `printf` lines the script cannot join; R-355 is the concatenation at
  app/restore.py:1132).
- Every cell was decided by reading the code around the hit, never from the text alone. The decisions are in
  `outcomes_ad.py`; `fill_outcomes.py` writes them and this section (rerunnable; `--check` prints the counts).
- Sections A to D hold **428 rows** (R-001 to R-428: A 167, B 149, C 49, D 63), not 421.
- Paths: `app/` is `clab-backup-ui/app/`; page scripts are named by file (`app/static/`). Line numbers are today's.
- "Choice:" in an F or S cell answers whether a person's choice in the manager can still end in that refusal.
- Evidence beyond reading: two read-only reproductions of F1 with the real helper code (9.5). No browser, VM, live
  device or test suite was run for any decision.

### 9.2 The chip panel per code, as the page shows it today

A text the helper's `status`, `publish`, `push`, `move` or `update` answers is mapped by `problem_code`
(app/git_progress.py:417-421) through `HELPER_PROBLEMS` (:296-398) and `MANAGER_PROBLEMS` (:400-413); a sentence
in neither table is `other`. `saveProblem` (status.js:364-387) shows:

| Code | Sentence | Actions |
|---|---|---|
| `vm` | `The lab VM could not be reached.` | Try again · Check the VM connection… |
| `account` | `The VM account cannot upload to <host>.` | Try again · Details |
| `busy` | `Someone is working in this repository on the VM.` | Try again · Details |
| `diverged` | `The online copy has changes this VM does not have.`; with saves waiting `The online copy and this VM both have changes the other does not have. They have to be combined on the VM.` | Update from the repository; with saves waiting Details |
| `files` | `<folder> holds files that were not saved by the manager.` | Choose another place · Details |
| `settings` | `No device of this lab is selected for saving.` (9.6 M1) | Save settings |
| `other` | `The save did not work.` | Try again · Details |
| `device` (a job ended `capture_incomplete`) | `<device> could not be read, so nothing was saved.` | Try again · Save settings · Details |

A refusal of a save request the page sent is shown as `other` with its text under Details (status.js:367-379).

### 9.3 Counts, sections A to D (category by outcome)

{COUNTS}

### 9.4 Every category-F row of sections A to D (the evidence for G2)

| Row | Rule | Outcome |
|---|---|---|
| R-003 | reserved names (helper) | Kept, not reachable through the page: step 2 uses the folder above; the old routes refuse first (R-171). |
| R-092 | other kind of snapshot | Kept, chip `files`; only a hand-committed design manifest at a lab's `latest` or `baseline` meets it. |
| R-095 | files outside the manifest | Kept, chip `files` with **Choose another place**; listed in DESIGN 3.6 and 2.3 "Not changed". |
| R-096 | non-empty folder without manifest | Kept, as R-095 (listed in 3.6). |
| R-126 | move into the own folder | Kept, not reachable through the page. |
| R-136 | move target holds saved files | Kept; the chooser never offers that move. **FINDING F4** through the Progress tab. |
| R-146 | overlap | Gone (H1); the narrower collision sentence becomes a replace or question 1 on the place route; **FINDING F2, F4**: raw on the old routes. |
| R-154 | overlap re-check under the registry lock | Kept as a race: question, or `The VM could not use this folder right now. Try again in a moment.` and the retry reuses the folder. |
| R-171 | reserved names (manager) | Kept on the old routes only; **FINDING F4**. |
| R-243 | carrier of R-171 | **FINDING F4**. |
| R-244 | at or below a saved configuration | Gone (DESIGN 4): no caller of `snapshot_conflict` left. |
| R-249 | one registration per lab (connect) | Kept on the old POST …/git/connect; **FINDING F2**. |
| R-262 | one registration per lab (PUT) | Reworded; **FINDING F3**. |
| R-265 | folder name taken | Gone: the existing folder is selected. |
| R-272 | the lab's own folder | Gone: answered without a change. |
| R-273 | another lab's folder (destination) | Kept on the old POST …/git/destination; **FINDING F4**. |
| R-383 | reserved names (wizard) | Reworded; terminal only, the wizard asks again. |
| R-387 | root would overlap (wizard) | Gone (H1): blank is accepted. |
| R-422 | overlap (CLI registration) | Gone (H1); a real collision only, terminal only. |

The 16 category-F rows of section E (R-432 to R-461) are `TBD`; the Progress tab that shows most of them is still
on the page (9.6 M5).

**Verdict on G2 for sections A to D.** On the new routes (`POST …/git/place`, `…/git/places/check`,
`…/git/state`, `…/folders/new`) no folder choice ends in a refusal except one (F1, the length of a folder path).
G2 is not met yet: today's page still reaches the old routes from three places (F2, F3, F4), and there the
1.30.60 refusals of category F, or their successors, still reach a person.

### 9.5 Findings

**F1. A folder path of about 100 characters is refused** (R-145, a V row that refuses a folder choice).
`POST /api/labs/{lab}/git/place` with `{repository, folder}` where `len(folder) + len(<checkout folder name>) + 3 > 100`:
the helper's `plan_prefix` builds the label `<checkout name> / <folder>` (app/host_git.py:1355; `plan_connect`
:1376) and `account_binding` refuses `Use a short repository label.` (:1328). `Placement.register` finds no
collision and answers HTTP 409 with that text (app/git_place.py:278-283); the chooser shows it. The same through
`POST …/git/state` (its default folder is `<lab folder>/<state name>`; `call()` raw, app/git_progress.py:1909) and
the old routes. Even the default first-save folder fails when the checkout name and the lab's folder name (up to
60 characters, app/git_places.py:20, 42-46) exceed 97 characters together. DESIGN 2.5 allows 500 characters.
Reproduced read-only: `host_git.plan_prefix` on a registry with the checkout `course-repo` accepts a 79-character
folder and refuses an 89-character one; `git_place.Placement.register` with a stub whose `invoke` calls the real
`plan_prefix` registers `week-04/bgp` and answers `HTTP 409 Use a short repository label.` for a 94-character folder.
*Smallest fix*: the helper cuts its generated default label to 100 characters instead of refusing (`plan_prefix`,
`plan_connect`, and `default_label` of `deploy/setup-git.sh`); a helper change, so a risk review.

**F2. Save settings › Connect by URL… uses the old `POST …/git/connect`** (R-249; R-146's successor; R-125 raw;
the new `A lab state is being saved into this folder right now…`, 9.8 row 24). save-drawers.js:384 (no location
yet) and :395 (with one) render `data-git-repo-action="connect"` → `drwRepoAction` (:445-450) → `gitRunAction('connect')`
(git-progress.js:872) → `gitConnectByUrl` (git-progress.js:493-512) → `POST /api/labs/{lab}/git/connect {url, prefix,
acknowledge: true}`. Reached when another lab is connected to the folder the address and the typed folder resolve
to (blank is the top level, which guided setup registers): `bind_lab` refuses `This folder is already connected to
another lab (<lab>). Choose a different folder.` (app/git_progress.py:1343-1345); a folder inside another lab's
`latest` gets the helper's collision sentence raw; an empty repository gets the raw H4 sentence without
**Start the repository**. *Smallest fix*: Connect by URL… opens the chooser's address mode, which posts
`…/git/place` with `url` like the first-save panel (save-header.js:378-388); or `…/git/connect` delegates to
`Placement.place`.

**F3. Save settings › Use a different repository… ends in `PUT …/git`** (R-262). save-drawers.js:395
`data-git-repo-action="switch"` → `gitSwitchRepository` (git-progress.js:485-491) lists every registration but the
lab's own, *Choose* opens the Progress tab's form with it, and its submit sends `PUT /api/labs/{lab}/git
{binding_id, node_names}` (git-progress.js:301); a registration another lab is connected to is refused
(app/git_progress.py:1597-1599). *Smallest fix*: open the drawer's chooser on that repository
(`saveDrawerOpen('chooser', …)`) instead.

**F4. The Progress tab still sends folder choices to `…/git/destination` and `…/folders`** (R-171, R-243, R-242,
R-273, R-276, R-136). The tab is visible (index.html:126, 154; the header's All versions also opens it,
save-header.js:357 → git-progress.js:864); its 1.30.60 folder browser (`gitPlacesShow` git-places.js:195,
git-progress.js:292) calls `gitUseFolder` (git-progress.js:446-459), `gitNewFolder` (:460-479) and the first-save
dialog (`gitFirstSave` :515-537). Reached with: a committed folder named `latest`, `baseline` or `checkpoints`
below a folder no lab saves to (git-places.js sets `managed` only below a registration) → HTTP 400 R-171; a
committed folder whose name has a space → HTTP 400 R-242; a stale tree or a race on another lab's folder → R-273; a
collision → the helper's sentence raw (R-276); *Use* on a folder that holds the saved files of a lab state or of a
removed lab, with "Also move the N files" ticked by default → the folder changes, the queued move fails with
`The new folder already contains saved files. Choose an empty folder.` and every retry fails again (chip `other`;
`destination` queues the move without the `bring` test, app/git_progress.py:1710-1725). *Smallest fix*: S11 (the
Progress tab loses its folder actions, or they open the drawer's chooser); on the server, `destination` applies
`Placement.bring` before it queues a move.

### 9.6 Other deviations from the design (not refusals of a folder choice)

- **M1. `settings` and `devices`.** DESIGN 3.6 (changed in 1e153fe) gives code `settings` the sentence
  `This lab’s save location has to be set up again.` with **Save settings** · **Details**, and a new code `devices`
  `No device of this lab is selected for saving.` with **Save settings**. Today status.js:385 shows the devices
  sentence for `settings`, `STATUS_PROBLEM_CODES` (status.js:189) has no `devices`, and the manager's NO_DEVICES
  refusal (app/git_progress.py:1767) reaches the chip as `other`. Every `settings` row above is therefore worded
  wrongly on the page today.
- **M2.** `This unchanged save points to a commit created outside manager saves…` (R-064) and `The push would
  include commits created outside manager saves…` (R-067) map to `diverged` (app/git_progress.py:339-340), which
  with nothing waiting offers *Update from the repository*, a fast-forward that cannot help. DESIGN 3.4 and the
  answer to review S1b row 4 say such commits read as someone working in the repository (`busy`).
- **M3.** Every job that ends `capture_incomplete` shows the device sentence, also for the manager's own capture
  problems (R-184 to R-200, TOPOLOGY_FAILED): then `A device could not be read, so nothing was saved.` with no
  device named.
- **M4.** `changing` is one lock for the whole manager (app/git_progress.py:996-1005): while one lab is placed (a
  clone can take minutes) every other lab's folder choice is answered `Another repository connection is being
  changed. Try again in a moment.` (R-224). Counted as transient (3.6, last paragraph), but DESIGN 7.1 disables Save
  only for "a place request of the lab"; the lead decides.
- **M5.** The Progress tab's folder browser (git-places.js `gitFolderChoice`, `gitCanCreateIn`,
  `gitNewFolderRefusal`, `gitFolderPath`) still refuses or disables choices in the browser; those are section E rows
  and are counted when E is filled.

### 9.7 Not decided by reading alone

- A typed folder whose first part is a committed *file* (`README.md/x`): `place_answer` calls it `free`, and the
  save would fail when the helper creates the folder, probably with the generic `The Git helper could not finish…`
  (chip `other`). Decide with a helper unit test on a checkout that holds such a file.
- R-092: no page flow was found that lands a capture on a design manifest; a design export named `latest` under a
  lab's `checkpoints` cannot be chosen as a lab folder (`leave_state`). Only a hand commit was found.
- R-136 through the chooser: only a race between the checkout view (cached for 10 s) and the move; not exercised.
- How NOT_OURS, ANOTHER_SAVE and the other 409s of the upload reach the person is decided by `gitReviewJob` and
  the chip panel (page, section E).

### 9.8 New refusals since 1.30.60 in these files

From `match_refusals.py --new-since 68f24d9`, each read at its source. Rewordings of an old row are in that row,
not here. Not listed: the drivers (unchanged since 68f24d9), `unreadable endpoint` (app/restore.py:280, caught
inside `topology_shape`, never shown), the informational move lines `MOVE_REASONS` (app/git_place.py:45-52) and the
question sentence `This folder is already used for saves on the VM.` (app/git_place.py:35, 272).

| # | Text | Where | Trigger | Cat | How it reaches the person |
|---|---|---|---|---|---|
| 1 | `The folder <P> is inside <S>, where the lab folder <O> keeps its saves; choose a folder above that saved state.` / `The lab folder <O> is inside <S>, where <P> would keep its saves; choose another folder for this lab.` (`is where` when it is that folder) | app/host_git.py:170-179, raised :1336; deploy/setup-git.sh:104 | a folder that lies in another registration's `latest`, `baseline` or `checkpoints`, or holds one in its own (H1) | F | place route: never shown (replace or question 1, app/git_place.py:275-295); old `…/folders`, `…/git/destination`, `…/git/connect`: raw 409 (F2, F4); setup-git.sh: terminal |
| 2 | `The online copy of this repository has changes this VM does not have.` | app/host_git.py:54, 568 | a further folder while the remote branch is not an ancestor of HEAD (H2) | X | 409 in the chooser |
| 3 | `This checkout has commits that were not made by manager saves.` | app/host_git.py:55, 570 | a further folder while HEAD is ahead with commits that are not verified manager saves (H2) | X | 409 in the chooser |
| 4 | `A save made in that folder still waits for upload.` | app/host_git.py:59, 603 | retiring a registration with a waiting save (H7) | S | place route: question 1 with one button (app/git_place.py:288-295); housekeeping ignores it; setup-git.sh re-registration: terminal |
| 5 | `The online copy could not be asked whether a save made in that folder still waits for upload.` | app/host_git.py:60, 601-602 | H7 with an unreachable remote | X | as row 4 |
| 6 | `The manager could not start the repository; connecting again retries it.` | app/host_git.py:57; 1154, 1171-1188 | H4 *Start the repository* failed | X | 409 under the address field |
| 7 | `README.md was pushed to start the repository, but other branches or tags appeared at the same time; connecting again finishes it.` | app/host_git.py:58, 1187 | H4 race with another push | X | 409 under the address field |
| 8 | `The repository has branches or tags but no branch <b>, which the VM folder <path> was cloned for; nothing was changed.` | app/host_git.py:182-183, 1143 | an empty clone whose remote now has other refs | X | 409 under the address field |
| 9 | `The VM folder <path> holds files that are not in the repository; nothing was changed.` | app/host_git.py:186-187, 1145 | an empty clone's folder holds files | X | 409 under the address field |
| 10 | `The VM folder <path> could not take the repository's first commits; connecting again retries it.` | app/host_git.py:190-191, 1148-1157 | finishing an empty clone failed | X | 409 under the address field |
| 11 | `Invalid connect option.` | app/host_git.py:1466 | `initialize` not a boolean | V | not reachable (the manager sends a boolean, app/git_place.py:247) |
| 12 | `Another save was made in this repository. Look at the changes again.` | app/git_progress.py:46, 2041 | Upload while HEAD is no longer the one the review showed (3.4) | S | 409 of the upload; the page shows the review again (7.3) |
| 13 | `The repository on the VM has changes the manager did not make.` | app/git_progress.py:47, 2044 | Upload while no manager save is at HEAD (3.4) | X | 409 of the upload; `busy` in `MANAGER_PROBLEMS` once it reaches the chip |
| 14 | `The repository on the VM could not be checked. Try again.` | app/git_progress.py:2040 | Upload: `status` named no HEAD | X | 409 of the upload |
| 15 | `Upload the waiting saves first; the online copy can only be fetched when nothing waits here.` | app/git_progress.py:51, 2074 | *Update from the repository* while saves wait | S | 409; the chip offers Upload instead (3.6) |
| 16 | `A save is still waiting to be uploaded. Upload it, or open its Details and choose Keep snapshot only, then try again.` | app/git_progress.py:52, 916 | Remove lab or Start fresh while a save needs attention (app/main.py:205, 241) | S | 409 in those dialogs (R-222 reworded) |
| 17 | `This capture does not include the topology. Save again first.` | app/git_progress.py:48, 1833 | a checkpoint or baseline from a capture without the lab's topology (3.9) | S | 400; the page disables the choice (`capture_whole`) |
| 18 | `The topology could not be saved with this capture. Try again.` | app/git_progress.py:49, 1175 | the capture recorded a topology or map write error (3.9) | O | job `capture_incomplete`, chip `device` (M3) |
| 19 | `None of the devices this lab saves exist in it any more. Choose the devices under Save settings.` | app/git_progress.py:50, 1767 | a save or lab state with no selected device left (3.3) | S | 409, chip `other` (M1) |
| 20 | `Use a name of at most 120 characters.` | app/git_progress.py:430 | a save, rename or lab-state name over 120 characters | V | 400 under the name field |
| 21 | `Give the lab state a name.` | app/git_progress.py:1876 | *Save as a lab state…* with an empty name | V | 400 in the drawer |
| 22 | `Choose Replace it or another name.` | app/git_progress.py:1877 | a `choice` other than `''` or `take` | V | not reachable (the page sends one of the two) |
| 23 | `Choose the repository this lab state is saved in.` | app/git_progress.py:1891 | a lab state without `repository` for a lab without a save location | V | 400 in the drawer |
| 24 | `A lab state is being saved into this folder right now. Try again when it has finished, or choose another folder.` | app/git_progress.py:1349 | old `…/git/connect` into a folder a lab state is being saved into (review F11) | S | 409 in the Connect by URL dialog (F2); the place route asks question 2 instead |
| 25 | `Could not store the name. Nothing was changed.` | app/git_progress.py:2005 | rename: the store write failed | O | 500 |
| 26 | `A folder path can be at most 500 characters long.` | app/git_places.py:24, 38; app/git_place.py:312-314, 333, 425-442, 501-507 | a typed path over 500 characters (2.5 step 1: the one validation left) | V | 400 in the chooser |
| 27 | `Choose a repository, or paste the address of one.` | app/git_place.py:36, 316 | a place request with both or neither of `repository` and `url` | V | not reachable (the page sends one) |
| 28 | `This repository is not on the VM. Refresh the list.` | app/git_place.py:37; 115, 495 | a registration that left the VM's list | S | 404 in the chooser |
| 29 | `The VM did not answer with the repository folder. Try again.` | app/git_place.py:38; 257, 365 | the helper's answer has no id or path | X | 409 in the chooser |
| 30 | `The VM could not use this folder right now. Try again in a moment.` | app/git_place.py:39, 58-61 | stands in for a helper sentence that names `registration`, `prefix` or `overlap` | X | 409 in the chooser |
| 31 | `The repository did not name its newest commit. Refresh the list and try again.` | app/restore.py:634 | a folder source read through another registration whose `history` has no HEAD | X | 409 in the Load review |
| 32 | `Resolve the problem reported above, then retry the original registration command.` | deploy/setup-git.sh:144 | a registration failed for a reason other than identity or login | X | terminal |
'''
