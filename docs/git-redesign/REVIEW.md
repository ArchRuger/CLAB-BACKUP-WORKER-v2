# Git save and load redesign: design review

The Opus review of [DESIGN.md](DESIGN.md) and its part files, with the answer to each finding. A finding
is closed only by a change to the design or by a stated reason. Both reviewers were read-only and ran no
code; every answer below is a decision, and the code that implements it is tested in the build.

## 1. Folder model, helper changes and save model (risk reviewer, Opus 5.5)

Verdicts on the helper changes: H1 accept with F5, F6, F16; H2 accept with F9; H3 accept with F10; H4
rejected as written, accepted with F4. What the reviewer confirmed: the table of DESIGN.md 2.2 holds for
every path filter, `clean`, `history`, `browse`, `move` and `publish`; `colliding()` is exactly the set
of real collisions (tried `x` against `x/latest-notes`, `x/checkpoints2`, `latest/foo` against the top
level, `a/checkpoints/x/y`); keeping old registrations does not widen what a push may carry; a stored
binding cannot reach a public view and cannot switch VM; B4, B5 and the `repository` key on a restore
source give the page nothing it cannot read today.

| ID | Severity | Finding | Answer |
|---|---|---|---|
| F1 | must-fix | The helper pushes only the checkout's newest commit (`host_git.py` `push`: "The checkout moved since this save"). Once another save sits on top, a waiting save cannot be uploaded by itself, and the save on top may belong to another lab that the person was never shown. | **Accepted; DESIGN.md 3.4 rewritten.** An upload is of the repository's waiting saves, not of one save. The review names every un-uploaded save, older and newer; Upload goes to the save at the checkout's HEAD through that save's own binding and carries the HEAD the person reviewed; the manager compares it with the helper's `status` before pushing and sends the page back to the review when a save landed in between. |
| F2 | must-fix | A folder move pushes by itself. Without `guard_pending`, the lab's own unreviewed save under the move commit is uploaded with no Upload click. | **Accepted.** A move no longer uploads by itself. Its commit waits like a save and goes up with the next Upload, named in the sentence. |
| F3 | must-fix | `own-before` by lab *name*: a student's copy of a course lab defaults to the instructor's folder and its first save replaces the instructor's `latest`, with removals allowed, without a question. | **Accepted.** `own-before` only when the manifest's lab id is this lab's. A state of a lab with the same name is a `state`: in the chooser it gets question 2; in the first-save panel it gets one question, `This repository already holds saves of a lab named <name>.` with **Continue there** and **Save in `<name>-2`**. |
| F4 | must-fix | H4 uploads a README with no click from the person, and a failure between its steps can leave a checkout that can never be registered. | **Accepted.** The helper starts an empty repository only when the request says so (`connect` gains the boolean `initialize`; the one request option this work adds), which the page sends only from the button **Start the repository** under the sentence `<name> is empty. The manager adds a README.md file to start it.` The helper requires that the remote has no ref at all, builds the commit without touching the working tree, pushes it, verifies the remote and only then moves the local branch. Recorded in DESIGN.md section 6. |
| F5 | should-fix | *Use this folder anyway* for a collision that is not the same folder ends in a refusal when the other lab's registration cannot be retired. | **Accepted.** For a collision the question has one button, **Save in `<folder>/<this lab>`**. *Use this folder anyway* exists only for the identical folder. |
| F6 | should-fix | A folder that collides with a registration no lab uses was classified `free`, and the helper would refuse it. | **Accepted.** `place_answer` applies `colliding()` to every registration of the checkout. The route retires a colliding registration that nothing uses (F7 decides whether it may) and otherwise answers with the one-button question of F5. |
| F7 | should-fix | The manager cannot know whether an un-uploaded save was made through a registration (removed labs, trimmed jobs). | **Accepted as helper change H7.** `retire` is refused by the helper itself while a journal of that registration holds a verified commit that the remote branch does not contain, checked as the owner under the checkout lock; an unknown remote refuses. |
| F8 | should-fix | The manager's list of what an upload carries misses saves it no longer holds; the helper still approves their commits. | **Accepted as helper change H6.** `compare` also returns `outgoing`: every commit between the remote branch and HEAD with its journal's operation, its subject and the paths it changed. The review names a save the manager does not know by its subject and lists its files. Output only; no mode, no option. |
| F9 | should-fix | H2: how the approved revisions reach the owner's child, a remote object missing locally, and what "a further folder" means for `setup-git.sh`. | **Accepted.** Root builds the list from `git.json` alone; the child filters it by the branch and push URL it read, fetches without writing `FETCH_HEAD` before the ancestry test and treats any non-zero result as a refusal. "Further" means another registration with the same path, push URL, branch and uid exists. |
| F10 | should-fix | H3: cost under the two locks, hostile manifests, the lab's own states losing their summary when the budget runs out. | **Accepted.** Sizes come from `ls-tree -l`; a manifest over 256 KiB is never read; the rest are read in one `git show`; the lab's own states first; every field is type-checked, strings capped at 200 characters without control characters, at most 500 devices, `null` on any deviation. `history` also returns `head`. The manager caches the answer per checkout and HEAD. |
| F11 | should-fix | A lab state being saved and a lab placed into the same folder at the same time end up writing the same `latest`. | **Accepted.** The state route runs under `changing()`, and a folder named in the stored binding of a pending save of kind `state` is a `state` for `place_answer` and `bind_lab`. |
| F12 | should-fix | *Move and keep* while the lab's save has no commit yet: its retry later rewrites `latest` in the folder the lab left. | **Accepted.** The line that brings the saved files along is offered only when every pending save of the lab has a commit. Otherwise the chooser says `A save of this lab has not finished. Its files stay in <old folder>.` |
| F13 | should-fix | Registrations only grow; at 2 MiB the registry is refused and every mode fails. | **Accepted.** Above 200 registrations of one checkout, each place or state request retires up to five that nothing uses, oldest first, through H7. A test fills a registry to the limit. |
| F14 | optional | A save that starts during a place request stores the old binding. | **Accepted.** `refuse_while_rebinding` stays for the place and state routes; the page disables Save while its place request runs. |
| F15 | optional | `compare` needs the job's own lab and that lab's current binding, so the rows of other labs cannot be opened. | **Accepted.** `compare` uses the job's stored binding and accepts any job made in the same checkout. |
| F16 | optional | The deviation from "pending jobs compare their digest" is not listed; `colliding(x, x)` is false where `overlapping('', '')` was true. | **Accepted.** Row added to DESIGN.md section 6; callers keep their equality test; a test covers the top level against itself. |
| F17 | optional | A lab without a binding reads through a registration whose `status` also checks that registration's own folders. | **Accepted.** Reading through a repository handle takes HEAD from `history` (validate only), never from `status`. |
| Point 9 | | *Use this folder anyway* must unlink the other lab and bind this one in one store-lock section. | **Accepted.** |

## 2. Load path, lost functionality, chip, friction and accessibility (UI reviewer, Opus 5.5)

Verdict: not ready to build until the chip and the load state are one function (K1 to K4, O1), the upload
is bound to the saves that were shown (X3), the diverged dead end is settled (X9) and the names are
reconciled (X1, X2). The reviewer checked all 84 capabilities, PROMPT 5.4's parity gate and 5.11 row by
row; found the friction budget met for the first save (2 clicks), later saves (2) and loading a lab
state (3); and found nothing against: one request id per review, the pinned commit of folder sources,
undo and retry always passing the confirmation, typed text and tick boxes surviving the poll, Escape and
outside click, keyboard use of the tree, colour as the only signal, inline styles and global listeners.

The answers below are decisions of [DESIGN.md](DESIGN.md) section 7, which the part files were then
revised to follow.

| ID | Severity | Finding | Answer |
|---|---|---|---|
| F1 | should-fix | *Use as starting point…* only on the lab's own saves; today any complete capture can become the baseline (C-013). | The Starting point group of All versions also offers **Choose a backup as starting point…**, today's dialog with its replace review. |
| F2 | should-fix | A waiting save can never be cleared without uploading it: no way to today's save window and its *Keep snapshot only* (C-039, C-043). | The upload view and every waiting row offer **Details**, which opens today's save window. |
| F3 | should-fix | A synced save's window (commit, changed files, *View configuration backup*) cannot be reached (C-037, C-041). | Every row of Your saves offers **Details** while the manager still holds the save. |
| F4 | should-fix | After the next save a succeeded load's job window cannot be reached (C-025, C-072). | The panel at rest shows `Last load: <name>, <when>` with **Details** while the manager holds a finished load of the lab. |
| F5 | should-fix | The upload sentence names no destination; a waiting save can go to a folder the lab left. | The upload view shows `To: <repository> › <folder>` from the save's own frozen destination. |
| F6 | should-fix | The exact path of a state is nowhere in All versions. | The open row shows it. |
| F7 | should-fix | A device that cannot be read stops the save and nothing offers to leave it out. | That *Can't save* row offers **Try again**, **Save settings** and **Details**. |
| F8 | should-fix | Loading an older commit through Full history is not specified. | *Full history…* opens today's history; a commit's view offers **Load this state…** with a `git` source. |
| F9 | optional | The saved time and the pinned commit are only in the differences drawer. | The confirmation says `Saved <when>.` under its sentence. |
| L1 | should-fix | Nothing clears a finished review: reopening Load can show a confirmation of an old preflight or of another lab. | The review is cleared when the panel closes and when the lab changes; `loadSubmit` refuses unless the review is of the lab on screen; Load always opens on the list. |
| L2 | should-fix | A retry shows devices that were not asked for as ready and ticked. | A retry renders only the devices it asked about, without page-derived rows and without the subset sentence; a test pins it. |
| L3 | should-fix | The source carries five keys once `repository` exists. | Five keys; the test counts five. |
| L4 | optional | The drawer's Load submits tick boxes it does not show. | It reads `Load on 3 devices`. |
| O1 | must-fix | The header's chip counted replaced devices, the load design verified ones. | One function, `loadState`, counts verified devices only; the chip calls it. |
| O2 | should-fix | A device interrupted before it was changed made a load "effective": `Loaded 0 of 4`, Undo offered. | A device counts as unknown only when its stage is `uncertain` or it still awaits its read-back. |
| O3 | should-fix | "could not check what this device runs" is untrue when the device was read and matches neither configuration. | `The manager could not confirm what this device runs. Open Details.` |
| O4 | should-fix | The name after *Running* named the newest save for any commit of `latest`. | The save whose commit is the loaded commit names it; otherwise `an earlier save, <when>`. `saveLoadName` is dropped. |
| O5 | optional | The toast and the line "on all m devices". | The toast fires only for a load that succeeded; a subset reads `on <m> devices`. |
| K1 | must-fix | The chip took the newest restore job of any outcome: a failed load after a good one turned the chip to *Saved* while the devices ran the loaded state. | `saveChipState` calls `loadState`, which keeps the newest effective load. |
| K2 | must-fix | Three definitions of the save that ends *Running*. | One: the newest save that read the devices itself (public `captured`), of the lab's own kind (not a lab state, not a design export), finished as `synced`, `unchanged`, `committed`, `review_pending` or `push_pending`. A checkpoint or a starting point made from an existing capture reads no device and ends nothing. A failed attempt ends nothing either: it is shown as *Can't save* in front of the load, which stays reachable through its *Also* line with Undo. |
| K3 | must-fix | The header's code put *Waiting* before *Running*. | DESIGN.md 7.1 is the order; the part file and its tests follow it. |
| K4 | must-fix | After Disconnect the chip read *Not saved yet* and hid a waiting upload. | Waiting saves count whether or not the lab is connected. |
| K5 | should-fix | A lab state has target `latest` and would be taken for the lab's latest save; *Try again* would start a lab save. | Kind `state` is left out of "your latest save", stays in the waiting count, and its retry retries that job. |
| K6 | should-fix | *Running X* stays after a redeploy, a restart or a design apply changed the devices. | A finished deploy, redeploy, destroy or design apply of the lab newer than the load ends it. |
| K7 | should-fix | Save stays enabled while another lab's load, a design apply or a retirement holds the manager, and the click fails. | `busy()` in `app.js` mirrors `operation_busy`; Save is disabled with the sentence that names what runs. |
| U1 | should-fix | After a save Undo is gone although it would still work. | Today's restore job window gains **Load this backup…** beside its "before loading" backup while that backup is kept; the `Last load` line leads there. |
| U2 | should-fix | Undo offered when it cannot work, or lost. | Follows O2 and K2. For a trimmed backup: `The automatic backup of this load is no longer kept.` |
| U3 | optional | The name of an undo of an undo nests. | Collapsed: undoing an undo of X reads `X`. |
| R1 | should-fix | Four clicks to change the folder need the `Saves to … Change…` line; a question adds a click. | The line is in the panel at rest. Four clicks is the plain case; each question the situation needs adds one. |
| R2 | should-fix | *Save as a lab state…* cannot be reached for a lab without a save location. | The first-save view has it in its foot. |
| D1 | should-fix | Load disabled while saving blocks browsing the states. | The Load button is disabled only while a load runs (PROMPT 5.2), with the chip saying so; during a save it opens, and the red Load is disabled with `A save is running.` |
| D2 | should-fix | Save settings disabled while a save waits; an upload-blocked state. | Both removed with their tests (DESIGN.md 3.1, 3.4). |
| D3 | optional | Device reasons name a menu path instead of offering the action. | A link button where an action exists. |
| A1 | should-fix | A live region wraps buttons. | Each live region holds only its sentence. |
| A2 | should-fix | The Load panel lacks the header's panel attributes and has its own focus rule. | It uses `data-panel` and `data-panel-focus` like the chip panel. |
| A3 | optional | Board F16 predates the Load button. | The built layout is checked at 760 px in the fixture pass. |
| X1 | must-fix | The drawers call `loadState` to start a load; it is the pure status function. | `loadChoose` starts a load (DESIGN.md section 5). |
| X2 | must-fix | Two contracts for the single sender. | One: `gitReviewData(job)` fetches the review; `gitReviewJob(job, {upload: true})` uploads what that review showed; without `upload` it opens the What changed drawer (DESIGN.md 7.3). |
| X3 | must-fix | The upload request names nothing that was shown; another lab's later save goes out unseen. | The upload carries the reviewed HEAD and the server compares it (risk review F1; DESIGN.md 3.4). |
| X4 | should-fix | Two data contracts for the chooser. | One table: DESIGN.md 7.4. |
| X5 | should-fix | A lab state inside the lab's folder (DESIGN.md) or beside it (the prompt). | Inside, as the default the chooser starts in: `BGP/start` for a lab that saves to `BGP`, which is the prompt's own example. Recorded in DESIGN.md section 6. |
| X6 | should-fix | Functions one part assumes and none provides. | Each has an owner in DESIGN.md section 5. |
| X7 | should-fix | Five pairs of class names for the same thing. | One table: DESIGN.md 7.5. |
| X8 | optional | Smaller disagreements. | DESIGN.md 7.6 lists the answer to each. |
| X9 | must-fix | *Update from the repository* is offered for diverged copies, but it is fast-forward only and refused while a save waits: a dead end. | It is offered only when nothing waits in the repository. With saves waiting the action is **Upload**. When both sides have changes the other lacks, nothing in the manager can combine them; the sentence says so and **Details** says what the repository's owner does on the VM (DESIGN.md 3.6). |
| B1 | should-fix | More of the binding UI contract is superseded than listed. | A dated amendment to `docs/redesign/DESIGN-SPEC-ADDENDUM.md` lists every item; its J2 check runs as a test; `gitRenderAdvanced` is guarded. |

## 3. Review of the first merged slice (S0, the two reproduced defects)

Commit `bf02e6b` changed the root-installed helper, so its diff was reviewed by the risk reviewer (Opus
5.5, read-only) after the lead had run both suites on it (2254 Python tests, 504 browser tests, the
release check, the link check and `bash -n`, all passing).

Verdict: no must-fix; it can ship alone. Confirmed: no pair of folders that writes the same files passes
the new rule; the identical folder is still caught by every caller (`plan_prefix`, `plan_connect`,
`save_registration`, `setup-git.sh`); a legacy registration ending in `latest` still collides with its
parent; nothing but the rule changed in the helper (no mode, option, VERSION, gateway or lock change);
no other part of the manager matches on the helper's old sentence; `setup-git.sh` applies the installed
helper's own rule; every old assertion was rewritten, none dropped.

| # | Severity | Finding | Answer |
|---|---|---|---|
| 1 | should-fix | Today's folder browser allows a folder the VM refuses, in the reverse direction: a lab folder that lies inside what would be the chosen folder's saved states (`course/latest/working` against `course`). | Fixed in a follow-up commit to today's browser (`gitFolderChoice` checks both directions). The new chooser never meets it: the answer comes from the manager (DESIGN.md 2.5). |
| 2 | should-fix | *New folder…* accepts a typed name such as `latest/notes` inside a lab folder, which the VM refuses later. | Fixed in the same follow-up: the dialog refuses it with a plain sentence. |
| 3 | should-fix | `docs/WIKI-MASTER-GUIDE.md` still says "Prefixes must not overlap." | Fixed in the same follow-up. |
| 4 | optional | "(whole repository)" for a lab at the top level is untrue now that others may sit below it. | Reworded to "top level" in the follow-up. |
| 5 | optional | The saved states of a lab nested inside the asking lab's folder appear in no group of Saved versions. | Fixed in the follow-up where it is a few lines; the All versions drawer groups from the manager's list in any case. |
| 6 | optional | A stale comment in `git-progress.js`. | Reworded in the follow-up. |
| 7, 8 | optional | One helper test passes without `retire`; the identical top-level folder has no caller-level test. | Added by the helper slice (S1), which owns `tests/test_host_git.py`. |
| 9 | optional | For a legacy registration that is itself the saved-state folder the sentence says "x/latest is inside x/latest". | Reworded by the helper slice (S1). |
| 10 | optional | The setup wizard tells a new lab to take a subfolder and then offers the repository root. | Wording aligned in the follow-up. |

## 4. Review of the helper slice (S1, H2 to H7)

The diff of `host_git.py` and `deploy/setup-git.sh` against the helper as S0 left it was reviewed by
the risk reviewer (Opus 5.5, read-only) after the lead had merged it and run its tests (114 in
`tests/test_host_git.py`). Confirmed: every id is checked as a full commit id before it reaches an
argv; the approved revisions are built by root from `git.json` and a request cannot bring its own; the
temporary object files are created exclusively with mode 0600 in the owner's state folder and removed;
no push uses force or a `+` refspec; the registry lock is never held across a network call; summaries
and outgoing rows carry metadata and paths only; the gateway and the modes are unchanged. Verdicts: H3
and H5 accept; H2, H4, H6, H7 accept with the named fix. All fixes were sent back to the slice's author
as one follow-up commit (S1b).

| # | Severity | Finding | Answer |
|---|---|---|---|
| 1 | must-fix | `setup-git.sh` re-registering an existing folder with other options (a changed label) while a save waits gives the folder a new revision; the waiting save's commit is then no longer approved and every later push of the checkout refuses. | The child computes the registration first; when its revision would change, the waiting-save check of H7 runs for the old registration and refuses while a save made through it waits. |
| 2 | should-fix | A clone of an empty repository that already exists on the VM is never finished: after a README is added on GitHub every connect repeats the empty-repository sentence. | `connect` fetches the remote branch into an unborn clone and fast-forwards it; nothing is pushed. |
| 3 | should-fix | H7 decided "a save waits" by the remote alone: a commit no longer reachable from HEAD blocked for ever, and an unverified journal with a commit was skipped. | A save waits when its commit is an ancestor of HEAD and not of the remote branch, verified or not. |
| 4 | should-fix | An outgoing row could name a save that the push will refuse. | Each row gains `approved`, the push's own rule. The manager shows an unapproved commit as someone working in the repository (DESIGN.md 3.6). |
| 5 | optional | A commit subject is not filtered for control or bidi characters. | Filtered like the summary strings; the page names rows by the manager's own saves first. |
| 6 | optional | The 15 second bound covered only `ls-remote`. | The fetch of a missing remote commit gets 20 seconds. |
| 7 | optional | No byte budget: a hostile repository fails a whole mode at the 24 MiB check. | Summaries, `dirs` and `outgoing` are capped by bytes with their `truncated` flags. |
| 8 | optional | A branch of another name created between the check and the push leaves the README beside it. | The remote is listed again after the push and must hold exactly the one ref. |
| 9 | optional | `check-ref-format --branch` expands `@{-N}`; `start()` wrote before the ownership check. | `check-ref-format refs/heads/<branch>`; the ownership check runs first. |
| 10 | should-fix | Missing tests (the re-registration case, sibling and unverified journals in H7, the fetch path of `outgoing`, the real wiring of `initialize`, a tag-only remote). | Added in the follow-up. |
