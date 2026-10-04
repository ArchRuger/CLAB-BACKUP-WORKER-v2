# Git save and load redesign: design

The decisions of the design round, written before code. The task is [PROMPT.md](PROMPT.md), the owner's
corrections are in [PICKUP.md](PICKUP.md) section 1, and the acceptance lists are in
[INVENTORY.md](INVENTORY.md). Base: `main` at 1.30.60.

| Part | Where |
|---|---|
| The folder model, the save model, the API between backend and page, the build slices | this file |
| The header control, the chip state function, the save and upload panels, the first save | [design/HEADER.md](design/HEADER.md) |
| Load (today's *Apply to running lab* in full), lab states, undo | [design/LOAD.md](design/LOAD.md) |
| The drawers, the folder chooser as a component, *Save as a lab state…*, the Progress tab's removal | [design/DRAWERS.md](design/DRAWERS.md) |
| The Opus design review and the answer to each finding | [REVIEW.md](REVIEW.md) |

Where a part file and this file disagree, this file wins: it was written last, with all three in hand.

## 1. What 1.30.60 changed against the prompt

The prompt was written on 1.30.59. Release 1.30.60 (the audit of 2026-10-03) added rules that the prompt's
goals now meet:

- **A save or an upload waits while another lab of the same repository has an unreviewed save**
  (`guard_siblings`, `sibling_refusal`, `git_progress.py`). This is a refusal inside the manager's
  control, so by PROMPT 6.5 it may not stop a save. Section 3.4 replaces it: the upload sentence names
  every save the upload carries and the *What changed* drawer shows their files. The audit's rule
  survives in its real form: no upload carries a save that the person pressing Upload was not shown.
- **A folder move whose upload would carry saves kept with *Keep snapshot only* waits for a review**
  (`kept_saves`, `kept_refusal`). A folder move no longer uploads by itself (3.4), so the refusal goes;
  the kept saves are named in the review of whatever upload carries them, as before.
- **`Host` allowlist, checked restart read-backs, capture hardening**: untouched by this work.

## 2. The folder model (PROMPT section 6, D8)

### 2.1 Vocabulary

- **Repository**: a checkout on the VM that root registered (`deploy/setup-git.sh`, or the helper's
  `connect` for a pasted address).
- **Lab folder**: the folder a lab saves into. The lab writes exactly three things inside it: `latest/`,
  `baseline/` and `checkpoints/<name>/`, its *saved-state folders*.
- **Saved state**: a folder that holds a `manifest.json` committed at HEAD. A **lab state** is a saved
  state no connected lab owns: a course's `start`, another lab's last save, an earlier folder of this lab.
- **Registration**: the VM's record `(checkout, folder)` in `/etc/clab-manager/git.json` that the helper
  needs before it writes. It is plumbing. The page never shows the word, a registration that no lab is
  connected to is invisible, and nothing a person does depends on knowing one exists.

### 2.2 Why folders could not overlap, and what is true

No document or comment gives a technical reason for the rule ([INVENTORY.md](INVENTORY.md), "Why
folders may not overlap today"): the handoff says only that "a root registration and subfolders in one
repository overlap by design". The only reasoned rule is the reserved names (`host_git.py`
`base_prefix`): a lab folder named `latest` would nest a second saved state inside the first.

The prompt's reading (6.4) was checked against every helper mode. `P` is the registration's folder and
`S(P)` its three saved-state folders.

| Mode | What it reads or writes by folder | Another lab folder inside, above or beside `P` |
|---|---|---|
| `status` | `clean()` looks at `S(P)` only; reads the manifests of `P/latest` and `P/baseline` | No effect unless it lies inside `S(P)` |
| `publish` | Writes files directly in `P/latest`, `P/baseline` or `P/checkpoints/<name>`; lists those folders without descending | No effect unless it lies inside `S(P)` |
| `push` | Commits, not folders. Only the checkout's newest commit can be pushed, it carries every earlier un-uploaded one, and each must be journaled under a current registration of the checkout | None by folder; the order of commits is shared by every lab of the checkout (3.4) |
| `history` | `git log -- S(P)`; lists every folder of the checkout that holds a manifest and marks `S(P)` as the lab's own | None |
| `read-version`, `compare` | An exact folder at an exact commit | None |
| `update` | The whole checkout, fast-forward only | None |
| `browse` | The whole committed tree | None |
| `move` | Moves `S(source)` to `S(P)` | Moves another lab's files only if that lab lies inside `S(source)` |
| `register-prefix`, `connect` | The registry | The overlap rule itself |

Whole-checkout checks (a staged change, an unfinished Git operation, the branch, the push URL) are the
same for every lab and stay.

So the reading holds. Two lab folders write the same files in exactly two cases:

1. they are the same folder;
2. one lies inside a saved-state folder of the other (`P/latest/…`, `P/baseline/…`, `P/checkpoints/…`).

Everything else (inside, above, beside, the top level next to subfolders) is disjoint.

### 2.3 Helper changes

Each is reviewed in [REVIEW.md](REVIEW.md). The protocol, the gateway's command list, the option
whitelist, structured stdin, the registry lock, the per-checkout lock, the review digests, the path
rules (`relpath`, no `.`, `..`, `.git`, no symlink traversal) and the privilege drop are untouched. No
mode is added. One request option is added: the boolean `initialize` of `connect` (H4).

**H1. The overlap rule becomes the collision rule.** `overlapping()` is replaced by `colliding()`:

```python
def colliding(prefix, other):
    """Two lab folders write the same files only when one lies inside a folder the other writes its saves
    into (latest, baseline, checkpoints). Otherwise they may sit inside, above or beside each other."""
    def inside(a, b): return any(a == f or a.startswith(f + '/') for f in ((b + '/' if b else '') + n for n in RESERVED))
    return prefix != other and (inside(prefix, other) or inside(other, prefix))
```

It is used wherever `overlapping()` was: `check_overlap` (renamed `check_collision`, called by
`plan_prefix` and `plan_connect`) and the race check in `save_registration`. `base_prefix` stays: a new
lab folder still cannot be named `latest`, `baseline`, `checkpoints` or `checkpoints/<name>`. The same
rule replaces the copy in `deploy/setup-git.sh` (it calls `h.colliding`), the wording in
`deploy/git-onboard.py` and the scripted helper of the fixture.
*Reason*: G2, and section 2.2 shows the old rule protected nothing the new one does not.

**H2. A further lab folder may be registered while saves wait on the VM.** `register()` refuses when the
branch is not exactly the remote branch ("Before linking, synchronize…"). For the first registration of
a checkout that stays. For a further folder of a checkout that is already registered (`register-prefix`,
and `connect` for a known checkout) the branch may be ahead of the remote, provided the remote branch is
an ancestor of HEAD and every commit in between is a journaled manager save of that checkout
(`known_commits()`, the test a push applies). The check moves into one method,
`GitRepository.check_synchronized(head, further)`, which `register()` and the child in
`deploy/setup-git.sh` both call, so the two stay equivalent by construction. "Further" means that
another registration with the same path, push URL, branch and uid exists. Root builds the approved
revisions from `git.json` alone, never from the request; the child keeps those that match the branch and
push URL it read itself, fetches the remote branch without writing `FETCH_HEAD` before the ancestry
test, and treats any result but success as a refusal (a remote commit it does not have is a refusal).
*Reason*: without it a folder change, a second lab's first save and *Save as a lab state…* are all
refused whenever a save waits for upload, which is the normal state after **Not now**.

**H3. `history` returns a bounded summary of each listed manifest.** Each row of `versions` gains
`summary`: `lab_id`, `lab_name`, `captured_at`, `kind`, `topology_digest` and, per device entry, `node`,
`short_name`, `platform` and whether it has a restore artifact, and `state` (the name a lab state gave
itself, else empty); the answer also carries `head`. Sizes
come from `ls-tree -l`, a manifest over 256 KiB is never read, the others are read in one `git show`
(4 MiB in total, the lab's own states first). Every field is type-checked, strings are cut at 200
characters and may hold no control character, at most 500 devices are returned; on any deviation the
row's `summary` is `null`. The manager caches the answer per checkout and HEAD.
*Reason*: the Load panel's `2 of 4 devices`, the `View only` reason, the topology comparison and "whose
state is this" all need the manifest. Reading every state through `read-version` would transfer every
file of every state. This is read-only and adds no mode and no option.

**H4. `connect` can start an empty repository, when asked to.** Today: "This repository has no commits
yet. Add a README on GitHub first, then connect it." `connect` gains the boolean `initialize`. Without
it nothing changes, except that the refusal for an empty repository is one the manager can recognise.
With it, and only when the remote has no ref at all (`ls-remote --heads --tags` is empty), the owner's
child builds a commit holding one fixed `README.md` without touching the working tree
(`hash-object`, `mktree`, `commit-tree`, under the ensured identity), pushes it to the branch the
clone's HEAD names (`main` when that name is unusable), verifies the remote head and only then moves the
local branch to it. A failed push leaves the clone as it was.
*Reason*: a brand-new repository is the most common first contact, and making that first commit is
within the manager's control. The page sends `initialize` only from the button **Start the repository**
under the sentence `<name> is empty. The manager adds a README.md file to start it.`: an upload with the
person's explicit click, of a file that holds nothing of a lab.

**H5. `browse` also returns every directory.** `dirs`: the directories of the tree at HEAD
(`git ls-tree -r -d`), at most 20 000, with `dirs_truncated`. *Reason*: the file list stops at 4000, and
a chooser that cannot show a folder cannot offer it; directories are few even when files are many.

**H6. `compare` also returns what an upload would send.** `outgoing`: every commit between the remote
branch and HEAD with its journal's operation id, its subject and the paths it changed, or `null` when
the remote cannot be asked. *Reason*: the manager forgets saves (a removed lab, the job cap, releases
before 1.30.37) that the helper still approves for a push; the review must name them (3.4).

**H7. `retire` protects waiting saves.** `register-prefix` with `retire` is refused while a journal of
the registration being retired holds a verified commit that the remote branch does not contain, checked
as the owner under the checkout's lock; a remote that cannot be asked refuses. *Reason*: retiring such a
registration makes every later push of the checkout fail for every lab, and the manager cannot know
whether one exists.

**Not changed.** `publish` still refuses a `latest`, `baseline` or checkpoint folder that holds files
its manifest does not own. Those are someone's own files inside a folder the manager would otherwise
write over; the manager avoids the case when it can see it (2.5) and otherwise reports it as *Can't
save* with **Choose another place**. `move` still refuses a destination that already holds saved
files; the chooser does not offer the move there.

### 2.4 Registrations are never retired by a folder change

Today a folder change calls `register-prefix` with `retire`, and pending saves block it. Both follow
from the overlap rule and from saves being tied to the lab's current binding. In the new model:

- **A folder change registers the new folder and rebinds the lab. It retires nothing.** A registration
  costs nothing, blocks nothing (H1) and stays invisible. Retiring one makes every un-uploaded commit
  journaled under it unpushable for good ("commits created outside manager saves"), which is a dead end
  the person cannot leave from the page.
- **Reuse.** Choosing a folder that already has a registration reuses it (`plan_prefix` already answers
  with the existing one).
- **Replace.** Only a real collision (H1: for example a legacy `x/latest` registration against a new
  `x`) retires a registration, and only one that no lab is connected to and no pending save names,
  decided under the store lock; the helper then decides whether it holds a waiting save (H7).
  `register-prefix` with that registration as its source and `retire` does it; no new mode. When it may
  not be retired, the folder gets the one-button question of 2.6.
- **Housekeeping.** A checkout with more than 200 registrations loses up to five that nothing uses,
  oldest first, with every place or state request, through the same safe `retire`. The registry can
  therefore not grow to its 2 MiB limit.
- `retired_already` and the "registration is gone" recovery stay for VMs where an older release retired
  one.

### 2.5 One answer per folder

One function, `place_answer(lab, checkout, folder, purpose)` in `git_progress.py`, decides what a folder
is for the asking lab. The tree marks, the sentence under a typed path, the question in the chooser and
the route that applies the choice all call it, so two texts on one screen cannot disagree.

Inputs: the registrations of the checkout (`list`), the labs connected to them (the store), the
committed tree (`browse`), the manifest summaries (`history`, H3), the folders made through the manager
(`git_folders`). The two helper answers are cached per checkout and HEAD for a few seconds.

Steps:

1. **Correct the path.** `clean_folder()` splits on `/`, trims, replaces every run of characters outside
   `A-Za-z0-9_.-` by `-`, strips what cannot start a name, drops empty parts and turns `.git` into `git`.
   It never refuses a character. A path longer than 500 characters is the one validation error left.
2. **Leave a saved state.** A part named `latest`, `baseline` or `checkpoints` is part of a saved state
   when it is the last part, when it is `checkpoints` followed by one name, when the folder above it is a
   lab folder, or when the tree shows a manifest there. The folder above the first such part is used and
   the answer says so (`adjusted`). A `latest` in the middle of a path that is none of these
   (`course/latest/working`) stays an ordinary name, as today.
3. **Classify.**

| Kind | When | What *Save here* does |
|---|---|---|
| `own` | The lab saves here now | Nothing changes |
| `own-before` | The folder holds a saved state whose manifest carries this lab's id | Used; the lab continues there |
| `lab` | Another connected lab saves here, or a registration of the checkout collides with this folder (H1, checked against every registration) | Question 1 |
| `state` | The folder holds a saved state of another lab or a course (a lab of the same name included), or a lab state is being saved into it right now | Question 2 |
| `free` | Everything else: a folder that does not exist, an ordinary folder, the top level, a folder inside, above or beside any lab folder, a folder only an unused registration names | Used; created by the first save when it does not exist |

4. **Avoid what can be seen.** When `P/latest` exists without a manifest (someone's own folder of that
   name), the answer for `P` is `free` with `folder` moved to `P/<lab>` and a note saying why.

The answer carries `folder` (what will be used), `typed`, `kind`, `exists` (false for a folder that is
only planned: it is never worded as being in the repository), `label`, `lab`, `layout` (`latest` or
`flat` for a state), `adjusted`, `beside` (the suggested alternative, the first free of
`<folder>/<lab>`, `<folder>/<lab>-2`, …) and `mark` (the text beside the folder in the tree).

A repository larger than the tree cap (4000 files) lists only what came back. The answer for a typed
path there falls back to the registrations and the manifest summaries, which are not capped by the
tree; a state beyond both is met at save time as in 2.3 "Not changed".

### 2.6 The questions

Each is one sentence with its answers as buttons, shown inside the chooser. None is an error.

| # | Sentence | Buttons |
|---|---|---|
| 1 | `<Other lab> saves here too.` | **Save in `<folder>/<this lab>`** (suggested) · **Use this folder anyway** |
| 2 | `This folder holds the state "<Label>".` | **Save beside it in `<folder>/<this lab>`** (suggested) · **Replace it** |
| 3 | `1 save of <lab> is waiting for upload.` | **Upload it, then move** · **Move and keep that save on the VM only** |

- *Use this folder anyway* disconnects the other lab from the folder and connects this one in one step
  under the store lock. Its saves stay as versions, and a save of it that still waits stays uploadable
  (3.1). The button exists only when the two labs want the identical folder. For a collision (a folder
  of the other lab lies inside this folder's saved states, or the reverse) question 1 has one button,
  **Save in `<folder>/<this lab>`**.
- *Replace it*: the lab takes the folder; its next save replaces `latest` there with removals allowed,
  and older contents stay in Git history. For a state stored directly in the folder (`flat`, a manifest
  in the folder itself) nothing can replace it, so the second button reads **Use this folder anyway**
  and the sentence under it says the state stays listed.
- Question 3 appears when the lab changes its folder or repository while a save of it waits. Both
  answers go ahead. *Upload it, then move* runs the page's one upload function and then the move.
  *Move and keep…* moves; the save keeps waiting and goes up with the next Upload (3.4).
- The line that brings the lab's saved files along is offered only when the lab has saved files in the
  folder it leaves, the new folder holds none, and every pending save of the lab has a commit. A save
  that has not reached its commit would otherwise be written into the folder the lab left, after the
  move. The move's own commit waits for Upload like a save; it never uploads by itself.

### 2.7 PROMPT 6.2, row by row

| The person chooses | Outcome | By |
|---|---|---|
| A folder that does not exist | Created with the first save and used; listed as planned until then | `free` |
| An existing folder with ordinary files and no saved state | Used; other files are not touched (`publish` writes only inside `latest`, `baseline`, `checkpoints/<name>`) | `free` |
| The repository's top level | Used | `free` (H1) |
| A folder inside, above or beside another lab's folder | Used | `free` (H1) |
| The very folder another connected lab saves to | Question 1 | `lab` |
| A folder that holds a saved state of another lab or a course | Question 2 | `state` |
| A folder that is part of a saved state | The lab folder above it is used, and the chooser says so | step 2 |
| A name with unsafe characters | Corrected as typed, result shown | step 1 |
| A folder while a save of this lab waits | Question 3 | 2.6 |
| A folder registered on the VM that no lab uses | Invisible; reused when chosen, replaced only on a real collision | 2.4 |

**New folder…** is always enabled. It adds the folder to the manager's list (`git_folders`, as today)
below the folder being looked at; inside a saved state it adds it in the lab folder above and says so. A
name that already exists selects that folder instead of refusing.

### 2.8 First save and the default place

`GET /api/labs/{lab}/git/places` without a repository answers with the repositories on the VM and a
default: the repository the lab used last, else the one saved to most recently, else the first; and the
folder `clean_folder(<lab name>)`, or the first of `<lab>-2`, `<lab>-3`, … whose answer is `free`, `own`
or `own-before`. So the default can always be saved to with one click and nothing typed. When the
folder named after the lab holds the saves of a lab with the same name and another id (the lab was
removed and imported again, or it is someone else's lab of that name), the panel asks once:
`This repository already holds saves of a lab named <name>.` with **Continue there** and
**Save in `<name>-2`**. It never continues there silently.

With no repository on the VM the panel asks for the HTTPS address. The page sends it to the same route;
the manager first connects the checkout at its top level (the helper's `connect` with an empty folder,
exactly what guided setup registers) and then places the lab in its folder inside it.

### 2.9 *Save as a lab state…* (D9)

A lab state is a normal saved state in its own folder, written by a normal save that carries its own
binding:

1. The page sends the destination folder (by default `<the lab's folder>/<name>`, so `BGP/start`) and
   the name. `place_answer(…, purpose='state')` classifies it. `free`: go on. `state`: one question,
   `"Start" already exists here.` with **Replace it** and **Use another name**. `own` or `lab`: the
   state goes to `<folder>/<name>` and the dialog says so.
2. The manager registers the folder (`register-prefix`, nothing retired) and creates a save job of kind
   `state` whose frozen binding (3.1) is that registration. The lab's own binding is not touched.
3. The job captures the lab now and publishes with target `latest`; its manifest carries `state: <name>`,
   which the helper's summary returns (H3), so every lab, the authoring one included, sees a lab state
   there and not its own earlier folder. The state is
   `<folder>/latest/manifest.json` with the topology, the map, every device configuration and the
   restore artifacts, exactly like any save. It ends waiting for upload with the same sentence.

Load reads it from any lab, because it lists every saved state of the repository (LOAD.md).

### 2.10 Old installations

Existing registrations, legacy `x/latest` registrations (they keep saving to `x/latest/latest`), schema
1 snapshots, the `.set` to `.cfg` pairing, `review_before_push`, stored bindings and stored jobs are
read as before. No stored binding is rewritten. The one migration is additive (3.1).

## 3. The save model

### 3.1 A save carries its own binding

Today a job stores `binding_digest` and is executed, retried and reviewed with the lab's *current*
binding; when the two differ the job is dead ("Repository settings changed"). That is why pending saves
block folder changes, device changes, reconnects and disconnects.

New: a job stores `binding`, a private copy of the binding it was created with (never in `PUBLIC_JOB`).
`execute`, `retry` and `compare` use it. A job without one (made by an older release) keeps today's
comparison with the lab's binding. At start-up, each pending job without a `binding` whose
`binding_digest` equals its lab's current binding digest gets that binding copied in: additive, and the
digest it stores stays true.

Consequences: a waiting save stays part of the next upload of its repository (3.4) after the lab's
folder, repository or device selection changed and after the lab was disconnected; `guard_pending`
leaves `link`, `destination`, `connect` and `unlink`; a save marked uploaded by a later push is matched
by its checkout (`made_in`), not by the lab's current binding. `refuse_while_rebinding` stays: a save
that starts while its lab is being placed waits for the placement.

### 3.2 The optional name (D2)

`Save.note` may be empty. After the capture and the helper's `status` (which returns the manifest of
`latest`), and before the first `publish`, the manager names the save from what changed between that
manifest and the new one, pairing entries by device, not by file name: `ceos changed`,
`ceos and xrv9k changed`, `ceos, cjunos and xrv9k changed`, `4 devices changed`,
`Topology changed`, `Map changed`, `First save`. The name is stored once in `note` and in the publish
request (the request body is immutable for the helper's idempotent retry) with `note_auto: true`.

`POST /api/git/jobs/{id}/name` renames. It validates like today's note (one line, 120 characters),
changes what the manager shows and never touches a commit. The names are kept by commit in
`state['git_save_names']` (capped), so a renamed save keeps its name after its job is trimmed. An empty
name returns to the automatic one.

### 3.3 Devices

- The selection lives in Save settings. A device of the selection that left the lab is dropped at the
  next save (a new binding; the stored one is not edited) and the upload sentence says its file was
  removed. An empty selection is *Can't save* with **Save settings**.
- `allow_removed` is always sent as true: the selection is explicit, the removal is in the sentence and
  the drawer before anything is uploaded, and the commit stays on the VM until Upload.

### 3.4 What an upload carries

Git uploads a branch, not a save: the helper pushes only the checkout's newest commit, and that push
carries every earlier commit the remote does not have. So an upload is of **the repository's waiting
saves**, and the review says so instead of refusing while another lab's save waits (1.30.60).

- **The review.** `compare` for any waiting save answers with that save's files and with the upload it
  would be part of: `head` (the checkout's HEAD), `upload_job` (the manager's save whose commit is
  HEAD) and `also_sends`, one row for every other un-uploaded save of the checkout, older and newer,
  whichever lab made it and wherever that lab saves now: the manager's waiting and kept saves
  (`job_id`, `lab`, `name`, `kind`), plus every outgoing commit the helper reports that the manager no
  longer holds (H6), named by its subject with the paths it changed. `compare` reads through the save's
  own stored binding and accepts any save made in the same checkout, so each row can be opened.
- **The sentence** names them: `This upload also sends 2 other saves: <name> (<lab>), …`. The drawer
  shows each one's files.
- **Upload.** `gitReviewJob`, still the only sender of `{push: true, reviewed: true}`, posts to the
  retry route of `upload_job` with `head`, the HEAD the person was shown. The manager asks the helper's
  `status` and pushes only when the checkout's HEAD is still that commit and is that save's commit;
  otherwise it answers 409 `Another save was made in this repository. Look at the changes again.` and
  the page shows the review again. A successful push marks every carried save reviewed and uploaded.
- **No save at HEAD** (someone committed on the VM by hand, or the newest save belongs to a lab the
  manager no longer has): *Can't save* with the sentence of 3.6 for someone working in the repository.
- A folder move's commit is one of these waiting saves. It never uploads by itself.

### 3.5 Checkpoint from a save (D6), unchanged saves, lab states

- *Keep as a checkpoint* posts the save route with `target: 'checkpoint'`, the save's `backup_job_id`
  and a name made from the save's name (`ceos-and-xrv9k-changed`; `-2` when taken). No device is read.
  A public `capture_kept` on each job tells the page whether the capture still exists; when it does not
  the tick box is disabled with `The capture of this save is no longer kept. Save again to make a
  checkpoint.`
- An unchanged save still ends `unchanged` and the page shows the toast.
- A job of kind `state` counts as a save to upload and never as "your latest save".

### 3.6 What may still stop a save (PROMPT 6.5)

| Cause | Sentence in the chip panel | Action |
|---|---|---|
| The VM cannot be reached | `The lab VM could not be reached.` | **Try again** · **Check the VM connection…** |
| The VM account cannot upload | `The VM account cannot upload to <host>.` | **Try again** · **Details** |
| An unfinished Git operation, staged or unsaved edits in the save's folder | `Someone is working in this repository on the VM.` | **Try again** · **Details** |
| The online copy has changes this VM lacks, and nothing waits here | `The online copy has changes this VM does not have.` | **Update from the repository** |
| The same, while saves wait here: each side has changes the other lacks | `The online copy and this VM both have changes the other does not have. They have to be combined on the VM.` | **Details** (what the repository's owner does on the VM; the manager never merges, rebases or force-pushes) |
| A device cannot be read | `<device> could not be read, so nothing was saved.` | **Try again** · **Save settings** (leave it out) · **Details** |
| Files the manager did not save are inside `latest`, `baseline` or a checkpoint folder | `<folder> holds files that were not saved by the manager.` | **Choose another place** · **Details** |

*Update from the repository* is a fast-forward and cannot work while a save waits, so it is offered only
when nothing waits in the repository; with saves waiting the action is **Upload**.

Transient states (a save or load in progress, another operation running) disable Save with the reason
visible in the chip or beside the button; they are not refusals of a choice.

### 3.9 The whole lab in every save (G1)

`tests/test_git_whole_lab.py` (27 tests) proves that the topology file and the map travel with a save to
`latest`, a checkpoint, a checkpoint from an existing capture and a starting point, that a change of
only the map or only the topology is a real change with its own entry in the review, and that the view
and the ZIP hold both. It also pins eight gaps; the design closes those where a save would reach the
repository without a file the lab has:

| Gap | Decision |
|---|---|
| The map a person edited in the manager loses to the VM's map file | The capture takes the manager's map when it was changed in the manager since the VM's file was last synced into it, and the VM's file otherwise (a VM file that changed since the last sync is the newer one, as today). |
| The topology or the map could not be embedded (a write error) and the save went on without it | The save stops with `The topology could not be saved with this capture. Try again.`; nothing is committed. |
| A capture made before topologies were embedded, used for a checkpoint or a starting point | It is not offered: the tick box or button is disabled with `This capture does not include the topology. Save again first.` (public `capture_whole`). |
| A save without the files deletes them from `latest` | Follows from the two rows above: a lab that has a topology never saves without it. |
| A lab imported from an inventory has no topology text | Unchanged: it saves its device configurations, and Save settings says `This lab has no topology file in the manager, so saves hold device configurations only.` with **Update topology file…**. |
| A topology edited in the manager after deployment loses to the deployed file | Unchanged and intended: a save is what the lab runs. |
| A design export carries neither | Unchanged: it is not a save of the lab. |

### 3.7 Load: the lead's answers to LOAD.md section 14

| Question | Decision |
|---|---|
| Q1, B1: manifest contents at list time | Accepted as **H3** of this file: the summaries ride on the existing `history` mode instead of a new `states` mode, so the helper gains no mode name. The manager route is LOAD.md's B2 (`GET /api/labs/{lab}/restore/states`), built on it. |
| Q2: matching a saved device to a lab device | **Unchanged: by full node name.** PROMPT section 7 item 6 leaves the preflight untouched, and a saved configuration carries its management address, so a state fits the lab it was saved from and a lab deployed from the same topology file under the same name (a student's copy of the course lab). The live pass loads onto a second lab record of the same topology and name. Matching by the topology's node name across differently named labs is left open for the owner (section 6). |
| Q3: a lab without a save location | **Load works before the first save.** The restore `Source` gains an optional `repository` (a registration id of this VM, checked against the helper's `list`). With it, or for a lab without a binding, the state is read through that registration; the lab's own binding stays the default. The Load panel uses the default repository of 2.8. |
| Q4: the topology comparison | Compared **by structure, not by bytes**: the node names with their kinds and the link endpoints of the state's embedded topology file against the lab's topology, parsed in the preflight. `differs` is `null` when either side is missing or unreadable, and no line is shown then. |
| Q5, B4: undo after an incomplete safety backup | Accepted: `captured_snapshot(complete=False)` only for a backup whose `source` is `restore-pre`; the strict default is pinned by a test. |
| B5: keep the newest load's safety backup | Accepted: one more protected job id per lab. |
| Q6: a load that changed nothing | As designed: the chip keeps what it showed; the banner and the panel carry the failure. |
| Q7: the job window's vocabulary | Kept. Only wording that names the removed tab changes. |
| Q8: another lab's saves | Out of the Load panel, folded in All versions. "Another lab's" means inside the saved-state folders of a lab that is connected now; every other saved state is a lab state. |

### 3.8 Header and drawers: the lead's rulings on the part files

**Chip precedence (HEADER.md 3.3 and LOAD.md 5.2 disagreed).** The newest event wins between the load
family and the save family, because PROMPT 5.4 step 5 makes the chip *Running* after a load without
condition and step 9 ends it only "when the next save completes":

1. *Loading* (a load is active), 2. *Saving* (a save is active);
3. *Can't save*, when a save attempt failed after the newest effective load;
4. *Partial* or *Running*, while the newest effective load is newer than the newest save that read the
   devices (7.1);
5. otherwise *Can't save*, *Upload failed*, *N saves to upload*, *Saved*, *Kept on this VM*, *Not saved yet*.

`also` (HEADER.md 3.4) carries the highest hidden save state into the *Running* and *Partial* panels as
one line with **Show** (`Also: 1 save to upload.`), so a waiting upload is never out of reach. This
matters for safety, not only for order: after a load the Save button saves what the devices run now,
and the chip must say what that is.

**HEADER.md NEEDS.**

| Need | Ruling |
|---|---|
| N1 `lab.git_status` in `/api/state` | Yes: `{checked, ready, problem, code, waiting}` (`waiting`: how many un-uploaded saves the manager holds for the lab's checkout, any lab's) kept in memory per lab from the last helper `status` the manager ran for it (the settings route, a save, a place, an update); never fetched by the poll. `code` is one of `vm`, `account`, `busy`, `diverged`, `files`, `settings`, `other`, mapped from the helper's fixed sentences in one table in `git_progress.py`. |
| N2 `source.label` on a restore job | No. The name is derived in the page (`loadSourceName`, LOAD.md 5.2) so that a renamed save shows its current name. |
| N3 empty note, `note_auto` | Yes (3.2). |
| N4 the change summary | Yes, stored on the job: after a save committed, the worker asks the helper's `compare` once and stores `summary = {devices: [labels], added, removed, topology, map, first, removed_devices}` (counts and labels only, public). The sentence then needs no request. `compare` answers gain `role` (`device`, `restore`, `topology`, `map`, `manifest`, `other`) and `node` per file, derived from the names the manager itself gave the files, and one row for every path in `changed_files`. |
| N5 `upload_blocked_lab` | Not needed: the sibling refusal is gone (3.4). |
| N6 rename | `POST /api/git/jobs/{id}/name`; not held by `idle()`. |
| N7 checkpoint name | Yes: an empty `checkpoint` with `target: 'checkpoint'` and a `backup_job_id` derives a free name from the save's name. |
| N8 `capture_kept` | Yes (3.5). |
| N9 one place call | Yes (section 4). |

**DRAWERS.md NEEDS and questions.**

| Item | Ruling |
|---|---|
| N3, one list of saved states | The states route of 3.7 Q1 returns each state with `path`, `commit`, `name`, `group` (`latest`, `checkpoint`, `baseline`, `state`, `other-lab`), `lab`, `kind`, device counts and `saved_at`. The name rule lives there: the last folder name once a trailing `latest` is dropped, its first letter upper-cased when the name is all lower case; two equal names each add their parent (`Start · BGP`). The Load panel, All versions and the chooser's marks all read it. `savedVersionName` in `status.js` follows the same rule for a page without the list. |
| N4, a lab without a save location | List, view, download and compare take an optional `repository`, as Load does (3.7 Q3). |
| N5, a device change or a disconnect while a save waits | They go ahead (3.1). The drawer says that the waiting save stays uploadable. |
| N6, one answer per folder | The tree embeds the answer of 2.5 for every listed folder. A typed path asks `…/places/check`; the page's own `folderClean` only echoes the correction while typing and is replaced by the answer's `folder`. |
| N8, every folder of a large repository | **H5**: `browse` also returns `dirs`, every directory of the tree at HEAD (`git ls-tree -r -d`), capped at 20 000 with `dirs_truncated`. Read-only, no new mode or option. |
| Q1, the folder-change budget | The chip panel at rest gains one line, `Saves to: <repository> › <folder>` with **Change…**, which opens the chooser: chip, Change…, a folder, **Save here** is four clicks. |
| Q5, earlier saves on a folder change | Today's ticked box stays as one line in the chooser (`Bring this lab's saved files along`), shown only when the lab has saved files in the folder it leaves and the new folder holds none. |

## 4. Backend contract for the page

Routes are under the same-origin guard; mutating requests carry a body. New or changed:

| Route | Body | Answer |
|---|---|---|
| `GET /api/labs/{lab}/git/places?repository=<id>` | | `repositories`, `default`, and for a repository: the tree (`files`, `truncated`, `head`), `folders` (one full answer of 7.4 per listed folder) and `own` (the lab's folder there, how many saved files it holds) |
| `POST /api/labs/{lab}/git/places/check` | `repository`, `folder`, `purpose` | the answer of 2.5 |
| `POST /api/labs/{lab}/git/place` | `repository` or `url`, `folder`, `choice` (`''`, `beside`, `take`), `pending` (`''`, `keep`), `move_files`, `node_names`, `acknowledge` | `{question}` or `{saved, binding, job}` |
| `POST /api/labs/{lab}/git/state` | `request_id`, `repository`, `folder`, `name`, `choice` (`''`, `take` for *Replace it*) | `{question}` or the job |
| `POST /api/labs/{lab}/git/save` | as today; `note` may be empty | the job |
| `POST /api/git/jobs/{id}/name` | `note` | the job |
| `POST /api/labs/{lab}/git/compare` | as today | plus `head`, `upload_job`, `also_sends` rows, and `role` and `node` per file |
| `POST /api/git/jobs/{id}/retry` | `push`, `reviewed`, and `head` with an upload | the job; 409 when a save landed after the review |
| `POST /api/labs/{lab}/git/place` with `url` | `initialize` only from **Start the repository** | `{question: {kind: 'empty'}}` for an empty repository without it |
| `GET /api/labs/{lab}/restore/states?repository=<id>` | | LOAD.md B2: per state its coverage, `view_only` and reason |
| `POST /api/labs/{lab}/restore/preflight`, `POST /api/labs/{lab}/restore` | `source` may carry `repository` | the preflight's `source.topology` (LOAD.md B3, compared by structure) |

The existing routes (`…/git` PUT, `…/git/destination`, `…/folders`, `…/git/connect`, `…/git/unlink`) stay
for stored pages and tests; they lose `guard_pending`, the snapshot-conflict refusal and the
duplicate-folder refusal, and `destination` stops retiring.

Shapes the page relies on: `default` is `{repository, folder, answer, ask, beside}`; an empty repository
answers `{question: {kind: 'empty', name}}`; the pending question is `{kind: 'pending', count, names}`;
`also_sends` rows are `{job_id, lab, name, kind, target}` for a save the manager holds and
`{commit, name, files}` for one it does not; `upload_job` is a job id or null.

Public job fields added: `note_auto`, `summary`, `captured`, `capture_kept`, `capture_whole`. Private: `binding`.
A load's public `source` gains `repository`, `topology` and `capture_id` (the id of the capture the state is). The exact fields the chip
needs in `/api/state` are in HEADER.md section 3 and LOAD.md section 7.

## 5. Build slices, file ownership and the names they share

One owner per file. Each slice works in its own Git worktree from the commit the lead names, runs its
focused tests there and hands back a branch; the lead merges, runs both suites and commits. New test
files reach the CI lists through the lead.

| Slice | Files it owns | Agent |
|---|---|---|
| S0 The two reproduced defects (PROMPT 6.1), their own commit | `app/host_git.py` (H1 only), `deploy/setup-git.sh`, `deploy/git-onboard.py`, the overlap rule of `FakeGit` in `docs/redesign/tools/fixture_manager.py`, `gitFolderChoice` / `gitCanCreateIn` / `gitFolderTag` in `app/static/git-places.js`; `tests/test_host_git.py`, `tests/test_git_onboard.py`, `tests/test_git_places_ui.js` | Opus specialist |
| S1 Helper: H2 to H7 | `app/host_git.py`, `deploy/setup-git.sh`, `tests/test_host_git.py` | Opus specialist (after S0) |
| S2 Folder answers, pure | `app/git_places.py` (new), `tests/test_git_places.py` (new) | Fable specialist |
| S3 Save model and routes | `app/git_progress.py`, `app/main.py`, `tests/test_git_progress.py`, `tests/test_design_export_git.py` | Fable specialist |
| S4 Load backend | `app/restore.py`, `app/runner.py`, `tests/test_restore.py`, `tests/test_restore_compare.py` | Network specialist (Opus) |
| S5 Page skeleton | `app/static/index.html`, `style.css`, `shell.js`, `app.js`; `tests/test_shell_ui.js`, `tests/test_save_router_ui.js` (new) | Fable specialist |
| S6 Status functions | `app/static/status.js`, `tests/test_status_ui.js` | UI builder |
| S7 Header panels and save flow | `app/static/save-header.js` (new), `app/static/git-progress.js` (first wave: `gitReviewJob`, `gitSubmitSave`, `gitStartWatch` only), `tests/test_save_header_ui.js` (new) | UI builder |
| S8 Load panel | `app/static/load.js` (new), `app/static/restore.js`, `tests/test_load_ui.js` (new), `tests/test_restore_ui.js` | Opus specialist |
| S9 Drawers | `app/static/save-drawers.js` (new), `tests/test_save_drawers_ui.js` (new) | UI builder |
| S10 Folder chooser | `app/static/git-places.js`, `tests/test_git_places_ui.js` | UI builder (after S0) |
| S11 Progress tab removal, rewording | `app/static/git-progress.js` (second wave), `home.js`, `operations.js`, `network-design.js`, the Python-emitted texts outside `git_progress.py`, `tests/test_git_progress_ui.js`, `tests/test_home_ui.js` and every test that pins the tab | Fable specialist (after S5 to S10 merged) |
| S12 Fixture and browser tooling | `docs/redesign/tools/fixture_manager.py`, `docs/git-redesign/tools/` | Test engineer, then QA |
| S13 The whole lab in every save (G1) | `tests/test_git_whole_lab.py` (new); reports gaps to the lead | Test engineer |
| S14 Documentation | the guides of PROMPT section 10 | Docs auditors |

**Names shared between page scripts** (each is read at call time behind a `typeof` guard, so every file
loads alone in a Node test):

| Name | In | Meaning |
|---|---|---|
| `saveChipState(lab, ctx, now)`, `loadState(lab, ctx, now)`, `loadSourceName`, `loadDeviceWord`, `saveChangeSentence(summary, also)`, `savedVersionName(path)`, `relativeTimeShort` | `status.js` | pure status and wording functions |
| `initPanel`, `openPanel(id)`, `closeMenus()` | `shell.js` | panel mechanics; the only global listeners |
| `renderSaveHeader()`, `saveOpenPanel(kind)` (`'status'` or `'load'`), `saveFinished(job)`, `saveAction(action, job, origin)` | `save-header.js` | header rendering and the chip panel |
| `gitReviewJob(job, options)` | `git-progress.js` | the only sender of `{push: true, reviewed: true}`, reached with `options.upload === true` from the panel and from the drawer |
| `loadOpen(labId)`, `loadChoose(labId, source, name, options)`, `loadUndo(job)`, `loadRetry(job)`, `loadJobMarkup(job)`, `loadChipView(cs, lab)` | `load.js` | Load; `loadSubmit()` is the only sender of `acknowledge: true` to a restore route |
| `saveDrawerOpen(kind, options)` (`'changes'`, `'versions'`, `'settings'`, `'chooser'`, `'state'`, `'different'`), `saveDrawerRender()`, `saveDrawerClose()` | `save-drawers.js` | the one drawer; `'different'` shows `loadDifferentMarkup(review)` from `load.js` |
| `folderChooserMarkup(model, view)`, `folderChooserEvent(type, event)`, `folderClean(value)`, `gitTreeModel`, `gitApplySource` | `git-places.js` | the chooser's markup and its one event seam for the drawer |

**Backend seams** (so S2, S3 and S4 can be built at the same time):

- `git_places.py` is pure and takes plain data: `place_answer(lab, checkout, folder, purpose)`,
  `folder_answers(lab, checkout)`, `default_place(lab, checkouts)`, `state_rows(lab, checkout)`,
  `clean_folder(value)`, `state_name(path)`. `lab` is `{id, name, prefix}` (`prefix` is its folder in
  this checkout or `None`); `checkout` is `{registrations: [{id, prefix, lab}], files, dirs, states:
  {path: summary}, planned, truncated}`.
- `GitProgress` offers to `restore.py`: `reader(lab_id, repository='')` (the binding to read with: the
  lab's own, or the registration `repository` after checking it against the helper's `list`) and
  `states(lab_id, repository='')` (`{head, truncated, states}` with the rows of `state_rows`), and
  `captured_snapshot(store, backup, context=None, embedded_files=True, complete=True)`.

## 6. Decisions that differ from the prompt's letter

| Prompt | Decision | Why |
|---|---|---|
| 6.2: **Replace it** for any folder holding a state | **Use this folder anyway** when the state is stored directly in the folder | Nothing the helper can do replaces it; saying "Replace" would be untrue |
| 6.2: "Move and keep that save on the VM only" | The save keeps waiting and stays uploadable | Nothing is lost; a later upload from the checkout carries it in any case and says so |
| 8: `register()` equals the setup child | Both call one method | Equivalent by construction (H2) |
| 6.4: "pending jobs compare their digest" | A save carries its own binding; only saves of older releases still compare with the lab's | The comparison is what made every change of a connection strand its waiting saves (3.1). No stored binding is rewritten |
| 6.4: prefer no new helper option | `connect` gains `initialize` | Starting an empty repository uploads a file, so it needs the person's click to reach the helper (H4, review F4) |
| 5.3: Upload uploads a save | Upload uploads the repository's waiting saves, all named in the sentence | Git can only push the newest commit, which carries the others (3.4, review F1) |
| Today: a folder move uploads at once | It waits for Upload like a save | Its push would carry saves nobody pressed Upload for (review F2) |
| 5.5: the chooser of a lab state starts beside the lab's own folder | It starts in the lab's own folder, so the state of a lab that saves to `BGP` is `BGP/start` | That is the prompt's own example with the default first-save folder; the person can choose any other folder |
| 7.1: the VM's files win when they are newer than the manager's copy | For the map, the manager's copy wins when a person changed it in the manager since the last sync | Otherwise a map edited on the Topology tab would never be saved (3.9) |
| 6.2: a lab imported again continues in its folder | One question in the first-save panel when the folder holds saves of a lab with the same name and another id | A student's copy of a course lab has the same name as the instructor's (review F3) |
| 6.5: only outside causes stop a save | Another lab's waiting save no longer does | 1.30.60 added that refusal after the prompt was written (section 1) |
| 9.6: "load a state on a second lab with the same topology" | The second lab carries the same lab name | Devices match by full node name and the preflight stays untouched (3.7 Q2). Open for the owner: match by the topology's node name across differently named labs |
| G06 mockup: `Kept previous` for a device that did not accept the state | `Not loaded` with the device's reason; `Kept previous` only for `rolled_back` | PROMPT 5.4 step 6 says to use the service's vocabulary exactly (LOAD.md 5.1) |

## 7. Rulings that override the part files

Written after the UI review ([REVIEW.md](REVIEW.md) section 2). The part files were revised to follow
them; where one still differs, this section wins.

### 7.1 One status function

`saveChipState(lab, ctx, now)` and `loadState(lab, ctx, now)` live in `status.js`; the first calls the
second. Nothing else decides a chip state, a count or a name.

Definitions:

- **Effective load**: a finished restore job of the lab with at least one device that was replaced
  (`verified`, `applied`, `applied_unverified`, `verify_mismatch`) or is unknown. A device is unknown
  only when its stage is `uncertain` or it still awaits its read-back; a device interrupted before it
  was changed is not. `L` is the newest effective load. A finished deploy, redeploy, destroy or design
  apply of the lab that is newer than `L` ends it (`operations` is capped for the whole manager, so the
  lab's `last_deployed` is the second source for a deploy or redeploy).
- **Capture save**: a job of the lab that read the devices itself (public `captured`), not of kind
  `state` or `design`, finished as `synced`, `unchanged`, `committed`, `review_pending` or
  `push_pending`. `S` is the newest. A checkpoint or starting point made from an existing capture is
  not one. A job stored before `captured` existed counts when its target is `latest`.
- **Failed attempt**: the newest job of the lab ended `export_pending`, `capture_incomplete`, `failed`,
  or `interrupted` without a commit, or the page holds a refusal of a save it just sent. `A` is its time.
- **Waiting**: jobs of the lab with a commit that is not uploaded, in `committed`, `review_pending` or
  `interrupted`, whether or not the lab is connected now; lab states and folder moves count.

Order, first match wins:

| # | State | Holds when | Chip text | `also` |
|---|---|---|---|---|
| 1 | Loading | a restore job of the lab is active | `Loading… k of m` (`k` devices with a final word); `Checking devices…` during a restart read-back | |
| 2 | Saving | a Git job of the lab is active | `Saving…`; `Uploading…` while it pushes; `Updating…` for an update | |
| 3 | Can't save | `A` is newer than `L` and than `S` | `Can't save` | the load of row 4 or 5 when `L` is newer than `S`, and a second line for waiting saves |
| 4 | Partial | `L` is newer than `S` and `L` did not succeed | `Loaded n of m` (`n` verified devices only) | the highest of rows 6 to 8 that holds |
| 5 | Running | `L` is newer than `S` and `L` succeeded | `Running <name>` | the same |
| 6 | Can't save | `A` is newer than `S`, or the lab's `git_status` is not ready | `Can't save` | Upload failed or waiting saves |
| 7 | Upload failed | a waiting job is `push_pending` | `Upload failed` | |
| 8 | Waiting | one or more waiting jobs | `1 save to upload`, `N saves to upload` | |
| 9 | Saved | the newest capture save that changed something is uploaded, or the lab has only unchanged capture saves | `Saved <short time>` | |
| 10 | Kept | every save of the lab is dismissed | `Kept on this VM` | |
| 11 | Not saved | otherwise | `Not saved yet` | |

The name after *Running*: for the lab's own `latest`, the save whose capture is the loaded state's
(`source.capture_id` equals the save's `backup_job_id`; the commit cannot tell, because a folder source
pins the checkout's HEAD, which is another lab's save as soon as one lands), else
`an earlier save, <when>`; a checkpoint by its name; the starting point as `your starting point`; any
other state by its name from the states list; a backup taken before a load X as
`the configuration from before X`, and the undo of that as `X`.

Save is disabled, with the reason as visible text, while row 1 or 2 holds, while a place request of the
lab runs, and while anything `operation_busy` counts is running in the manager (`busy()` in `app.js`
mirrors it and names it). The Load button is disabled only while row 1 holds; the red **Load** of a
confirmation is disabled with `A save is running.` during row 2.

### 7.2 Load

- The review object is cleared when the Load panel closes and when the lab changes; `loadSubmit` does
  nothing unless the review is of the lab on screen; the panel always opens on the list.
- A source carries five keys: `type`, `commit`, `path`, `backup_job_id`, `repository`.
- A retry renders only the devices it asked about. The differences drawer's button reads
  `Load on <n> devices`.
- `uncertain` reads `Not confirmed` with `The manager could not confirm what this device runs. Open
  Details.` The toast fires only for a load that succeeded and says `on <m> devices` for a subset.
- The restore job window gains **Load this backup…** beside its backup from before the load, while that
  backup is kept. The panel at rest shows `Last load: <name>, <when>` with **Details**.
- *Full history…* opens today's history; a commit's view offers **Load this state…** with a `git`
  source. The confirmation says `Saved <when>.` under its sentence.

### 7.3 The review and the upload

- `gitReviewData(job)`: fetches `POST …/git/compare` for the job and caches the answer until the set of
  waiting saves in `/api/state` changes. It returns `files`, `summary`, `head`, `upload_job` and
  `also_sends`.
- The waiting view shows the sentence from the job's stored `summary` at once and enables **Upload**
  when the review answer has arrived (until then `Checking what this upload sends…`), because the
  sentence must name everything the upload carries before the click.
- `gitReviewJob(job, {upload: true})` posts `{push: true, reviewed: true, head}` to the retry route of
  `upload_job`. It is the only sender. On 409 it fetches the review again and shows it. Without
  `upload` it opens the What changed drawer.
- The view also shows `To: <repository> › <folder>` from the save's frozen destination and offers
  **Details** (today's save window, with *Keep snapshot only*).

### 7.4 The chooser's contract

| Field | Values |
|---|---|
| `kind` | `free`, `own`, `own-before`, `lab`, `state` |
| `folder` | the folder that will be used; `typed` what was asked; `adjusted`: `''`, `corrected` (unsafe characters), `above-state` (part of a saved state), `beside-files` (someone's own `latest` folder) |
| `exists` | false for a folder that is in no commit; such a folder is never worded as being in the repository |
| `label`, `lab`, `layout` | the state's name; the other lab `{id, name}`; `latest` or `flat` |
| `collision` | true when `kind` is `lab` because of a collision and not the identical folder: the question then has one button. Without a lab to name (a folder nothing uses, which still holds a waiting save) the sentence is `This folder is already used for saves on the VM.` |
| `bring` | `{offered, files, from}`: whether the line that brings the lab's saved files along applies to this folder (2.6), set by the route, never derived in the page |
| `beside` | the suggested alternative folder |
| `mark` | the text beside the folder in the tree: `This lab saves here`, `<lab> saves here`, `Lab state: <name>`, or empty |
| `choice` sent by the page | `''`, `beside`, `take` (*Use this folder anyway*, *Replace it*, *Continue there*) |
| `pending` sent by the page | `''`, `keep` (the page has uploaded first when the person chose *Upload it, then move*) |

Routes: `GET …/git/places` (repositories, the default place, and for one repository the tree with the
answer of every listed folder), `POST …/git/places/check` (the answer for a typed path),
`POST …/git/place`, `POST …/git/state`. An answer that needs a choice comes back as `{question}` with
status 200. The page's `folderClean` only echoes the correction while typing.

### 7.5 Class names

HEADER.md 1.3 is the list: `save-control`, `save-pair`, `save-chip`, `save-dot` (`ok`, `warn`, `bad`,
`none`, `busy`, `info`), `save-panel` (`wide`), `save-state`, `save-sub`, `save-row`, `save-note`,
`save-kv`, `save-foot`, `save-name`, `save-keep`, `save-heading`, `save-list`, `save-item`, `save-when`,
`save-why`, `open`, `picked`, `save-devices`, `save-end` (`ok`, `bad`, `now`, `warn`), `off`,
`save-drawer`, `save-settings`, `save-settings-foot`, and `panel-button` on a panel's opener. A quiet action is the existing
`button ghost small`. The chooser adds the names DRAWERS.md 8.2 lists under `folder-`.

### 7.6 Smaller answers

| Question | Answer |
|---|---|
| A toast after *Not now* | None: the chip says `1 save to upload`. |
| `allow_removed` | Always true (3.3). |
| The first connection by address | The checkout is connected at its top level, then the lab is placed in its folder (2.8). |
| The two save banners of the lab banner | Removed; the chip carries them. The banner keeps what a load or an operation reports. |
| Disconnect while a save waits | The save keeps waiting (3.1); nothing is dismissed. |
| A label stored on the restore job | No; the name is derived (7.1). |
| *Use as starting point…* | On the lab's own saves, plus **Choose a backup as starting point…** in the Starting point group (today's dialog). |
| A device that cannot be read | The *Can't save* row offers **Try again**, **Save settings**, **Details**. |
| *Save as a lab state…* for a lab without a save location | Offered in the foot of the first-save view. |
| Live regions | Each holds only its sentence, never a button. |
| The binding UI contract | A dated amendment to `docs/redesign/DESIGN-SPEC-ADDENDUM.md` lists what the owner decisions supersede (the ids of J2 that go, the panel bodies under J3, J4, J6). |
