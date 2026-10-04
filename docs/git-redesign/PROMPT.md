> Stored verbatim as the owner pasted it on 2026-10-04. The corrections the owner gave in the same session
> (dev2 instead of dev1, base release 1.30.60, the setup kit kept, the device images) are in
> [PICKUP.md](PICKUP.md) section 1 and win over this text.

# Claude Code prompt (v2): Git save and load redesign for the Containerlab Node Manager

You are working in the Containerlab Node Manager repository (`ArchRuger/CLAB-BACKUP-WORKER-v2`, checkout
`~/projects/clab-manager`) on **dev1**, a local disposable development VM with 70 GB of memory where bypass
permissions are already enabled. The owner authorizes everything in this prompt. The owner considers this the
hardest task of the project so far: design it properly, use the strongest models where they help, run as many
agents in parallel as the work can use, and deliver it as one pull request.

This prompt is complete on its own. Appendix A carries the exact markup, wording and CSS of the approved
header mockups. If a `reference/` folder sits beside this file it holds the same mockups as screenshots plus
the scripts that made them; use it when present, do not wait for it when absent. Where this prompt and a
mockup disagree, this prompt wins. Where both are silent, keep today's behaviour.

## 0. What the owner wants (the four goals)

Read these as the purpose of every decision below. When a detail in this prompt would work against one of
them, the goal wins and you say so in the report.

**G1. A save is the whole lab, in GitHub.** One save puts the lab's topology file (`<lab>.clab.yml`), its
map (`<lab>.clab.yml.annotations.json`) and the running configuration of every included device into one
folder of a Git repository, as one commit, and uploads it to the repository's online copy on GitHub. The
topology and map already travel with every capture (`git_progress.py`, "embedded" provenance,
`NODE-FEATURES.md` "The topology travels with every backup"). Prove it end to end and close any path where
a save reaches the repository without them.

**G2. Any folder, never blocked.** A person can save to any folder they choose, and create a folder
anywhere, at any time. The manager never answers a folder choice with a refusal such as "lab folders cannot
overlap", "choose a folder beside it", "folders cannot be created inside another lab's folder" or a greyed
out **New folder…**. Whatever the manager needs to do to make the choice work, it does itself. Where a
choice is truly ambiguous (two labs wanting the very same folder), it asks one plain question with the
answers as buttons. Today this area has far too much friction; removing it is the core of this task.

**G3. Lab states.** A person can load a saved state of the lab onto the running lab: their own saves and
checkpoints, and the prepared states a course ships, typically *start*, *broken* and *final*. Everything
"Apply to running lab…" does today must work, fully, inside the new design, on every supported platform.

**G4. Radical simplicity.** Everything that can be hidden from the person is hidden. Saving is two clicks.
The Progress tab is replaced by a small control in the lab header.

## 1. Owner decisions (already made; do not reopen)

| # | Today | Decided |
|---|---|---|
| D1 | The Progress tab holds saving, versions and settings | The tab is removed. Saving and loading live in the lab header on every tab. |
| D2 | Every save asks "What changed?"; the label is required | The label is optional. A save without one is named from what changed (`ceos and xrv9k changed`). It can be renamed afterwards. |
| D3 | A save that needs upload opens "Review before uploading" with the full diff | One sentence in the header panel (devices changed, lines added and removed) with **Upload** and **Not now**; the full diff is one click away. Nothing is uploaded without that Upload click. |
| D4 | Loading opens "Replace running configuration" with an acknowledgement tick box | The red **Load** button is the acknowledgement. The per-device list, difference counts and the choice to leave a device out stay. |
| D5 | The first save asks for repository, folder, devices and an exposure tick box | One button with a default place and the passwords-and-keys sentence beside it. **Choose another place** opens the folder chooser. |
| D6 | "Create checkpoint…" is a separate capture | **Keep as a checkpoint** on a save that already exists. |
| D7 | No one-click way back after a load | **Undo this load** loads the automatic pre-load backup. |
| D8 | Lab folders of one repository cannot overlap; one registered folder per lab; the VM helper refuses the rest | **Any folder.** Folders may sit inside, above or beside each other. The folder rules are redesigned (section 6) so that no folder choice is refused. |
| D9 | A lab saves only to its own save location | **Save as a lab state…** writes the current state to any other folder (for example `BGP/start`) without changing where the lab normally saves. |
| D10 | Loading replaces device configurations and nothing else | Unchanged: Load never redeploys or edits the topology. When a saved state was made on a different topology, Load says which devices match and loads those. |
| D11 | Two or three workers; Sonnet by default; Opus on judgement | New routing rules (section 2): Fable 5.1 for design and the hardest work, Opus 5.5 for review and specialist work, as many parallel agents as the 70 GB VM can use. |

If one of these cannot be built without breaking a rule in section 8, stop that item, build everything
else, and report the conflict with evidence. Do not silently pick a different design.

## 2. Team, models and parallelism (update the project's rules first)

The owner is changing how this project routes work. Before anything else, rewrite
`.claude/rules/fable-opus-routing.md` and `.claude/rules/clab-ui-routing.md`, the "Delegating work" section of
`CLAUDE.md`, and the agent definitions in `.claude/agents/`, so they say the following. Commit that as its
own first commit. These rules then govern this task and later ones.

**Models**

- **Fable 5.1 (`claude-fable-5-1`) leads and designs.** The lead does product and interaction design,
  architecture, the folder model, the state model, integration, and any implementation it judges hardest.
  It may also run Fable 5.1 workers for design and architecture slices. Add an agent definition
  `clab-fable-designer` (`model: claude-fable-5-1`, read and write) for that: design documents, interaction
  specifications, state machines, wording, and reference implementations of the hardest pieces.
- **Opus 5.5 (`claude-opus-5-5`) reviews and specializes.** `risk-reviewer` (read-only: anything touching
  `host_*.py`, the gateway, trusted paths, owner-scoped Git, restore, persistence, concurrency),
  `clab-ui-reviewer` (read-only: design decisions, transactions, rollback, lost functionality) and
  `clab-opus-specialist` (difficult debugging, complex implementation, adversarial verification). No failed
  cheaper attempt is needed before using Opus. A model change never removes a role's tool restrictions.
- **Sonnet** does routine implementation, tests, documentation and QA runs (`clab-ui-builder`, `clab-ui-qa`,
  `docs-auditor`). **Haiku** does bounded inventory and decided mechanical edits (`clab-ui-scout`,
  `mechanical-editor`). Scripts and searches come before any model. Do not send trivial edits to a premium
  model out of habit, and do not hold back Fable or Opus where their judgement changes the result.

**Parallelism**

- The old "two or three workers" guidance is withdrawn. dev1 has 70 GB of memory: run as many workers at
  once as have independent work, each with its own files or its own Git worktree. One owner per file at a
  time. No recursive delegation beyond what a worker needs to finish its own slice.
- Each browser or fixture worker gets its own port and its own fresh `FIXTURE_DATA`. Several disposable
  labs may run at once; measure memory (`free -g`) before starting one and keep headroom, because the
  VM-in-container nodes are heavy. A live lab has one operator at a time, assigned by the lead.
- If the installed Claude Code offers agent teams or workflow features, you may enable them in
  `.claude/settings.json` and use them. Check what they actually do on this installation before relying on
  them, and keep `availableModels` and the default-subagent settings consistent with these rules.
- State task, agent, model, scope and acceptance check before each delegation. Verify the model a worker
  actually ran on from task or transcript metadata, never from its self-description, and report any
  substitution.

**Standing rules that do not change**

The lead integrates, owns shared files, release markers, commits, pushes and pickup notes. An implementer is
never the only verifier of its own work. Tests use disposable fixtures. Never claim a VM, browser or
live-device validation that did not happen in this session.

**How to staff this task**

1. *Design round (Fable).* The lead, with `clab-fable-designer` workers in parallel, writes
   `docs/git-redesign/DESIGN.md`: the folder model (section 6), the save and load state model, the header
   interaction, the wording, and the list of every refusal the Git flows can produce today with its new
   outcome. Scouts gather the inventory it needs.
2. *Design review (Opus).* `risk-reviewer` attacks the folder model and every `host_git.py` change before
   code is written; `clab-ui-reviewer` attacks the load path and the lost-functionality map. Their findings
   are answered in `DESIGN.md`, not waved through.
3. *Build (parallel).* Slices with disjoint files: VM helper and its tests; manager backend; header control
   and status function; save flow; load flow; folder chooser; drawers; fixture and Playwright tooling;
   documentation. Hard slices go to Fable or `clab-opus-specialist`, routine ones to `clab-ui-builder`.
4. *Verification (independent).* `clab-ui-qa` workers run the fixture pass at four widths in parallel; an
   Opus specialist runs the "try to get blocked" pass (section 9); the lead runs the live pass on dev1.

## 3. Environment and authorization

- dev1 is disposable and you have full permissions. Discover the environment before relying on it (Docker,
  `/srv/containerlab-node-manager/data`, the running manager, Node 24, a GitHub repository the VM account can
  push to, disposable labs). The rebuild loop and live-lab facts are in `docs/redesign/PICKUP.md` §2 and
  `docs/uiux-email-2026-10-03/PICKUP.md`.
- You may: create a feature branch and worktrees, commit, push the branch, open one pull request, rebuild
  and recreate the manager container, reinstall the VM helpers with the project's own setup scripts, deploy
  and destroy disposable labs, change device configuration on disposable labs, and create scratch
  repositories and folders in the GitHub account the VM is logged in to for testing.
- You may not: merge to `main`, force-push, tag, publish an image, or point tests or a `Store` at live data.
  Never delete `/data`, `state.key` or backups to make something pass.

## 4. Read before you write

1. `CLAUDE.md` (invariants and routing table), then the handoff sections it names for *Save progress,
   folders, upload review* and *Apply to running lab (restore)* in `agent instructions.md`. Find and read the
   passages that explain **why** lab folders may not overlap today (search `overlap` in the handoff and in
   `app/host_git.py`); the folder redesign must answer that reasoning, not ignore it.
2. `docs/GIT-PROGRESS.md`, `docs/GIT-SETUP.md`, `docs/LAB-OPERATIONS.md`,
   `docs/redesign/DESIGN-SPEC-ADDENDUM.md`, `docs/multi-platform-restore/README.md`.
3. Code: `app/static/index.html`, `app.js`, `shell.js`, `status.js`, `git-progress.js`, `git-places.js`,
   `restore.js`, `diff-view.js`, `home.js`; `app/git_progress.py`, `app/host_git.py`, `app/restore.py`,
   `app/restore_drivers.py`; `deploy/setup-git.sh`, `deploy/git-onboard.py`, `deploy/git-registrations.py`.
4. Appendix A, and `git-redesign reference/` when present.

Then write `docs/git-redesign/INVENTORY.md`: every capability reachable today from the Progress tab, the
header save menu, the folder browser, the lab banner and the home card (control, function, endpoint), and
every message with which the Git flows refuse or disable something (text, where it is raised, what triggers
it). Section 5.11 and section 6.4 are the starting maps. Both lists are acceptance artifacts.

## 5. Design specification: the header

Board names such as `G03` or `F11` identify a state. Each has its markup in Appendix A and, when the pack
is present, a screenshot in `reference/boards/`.

### 5.1 The header control

Order, left to right, before "Lab actions": **chip**, **Save** (primary), **Load** (secondary). It is
present on every lab tab. `#lab-progress` goes away because the chip carries it. The header's action column
must hold all four controls on one row at 1280 px and wider; below that the row may wrap, with the chip and
Save together on the first row, and nothing may overlap (`F16`).

Only one panel or drawer is open at a time. Panels close on Escape and on outside click and return focus to
the control that opened them. Use the existing menu, drawer and dialog mechanics in `shell.js`; add no new
global listeners outside `shell.js`.

### 5.2 Chip states

| State | Dot | Chip text | When |
|---|---|---|---|
| Saved | green | `Saved 21 min ago` | The latest save is uploaded and nothing newer was loaded. |
| Saving | accent, pulsing | `Saving…` | A save is queued, capturing or exporting. Save is disabled. |
| Waiting | amber | `1 save to upload` | One or more saves are committed on the VM and not uploaded. |
| Failed | red | `Upload failed` | The last upload failed; the save is safe on the VM. |
| Needs attention | red | `Can't save` | Something outside the manager stops saving (section 6.5). The panel says what and offers the fix. |
| Not saved | hollow | `Not saved yet` | No save location, or no save yet. |
| Loading | accent, pulsing | `Loading… 2 of 4` | A load is running. Save and Load are disabled. |
| Running | accent | `Running ospf-up` | The newest finished load is newer than the newest save. |
| Partial | amber | `Loaded 3 of 4` | The newest load changed some devices and not others. |

The text always states the state; colour is never the only signal. Derive every state from `/api/state`
through a pure function in `status.js` beside `progressState`, unit-testable in Node and shared with the
home card.

### 5.3 Saving

1. **Save** starts a save at once. No dialog, nothing to type. Chip *Saving*, panel `Saving…` /
   `Reading the configuration of 4 devices. You can keep working.` (`F02`).
2. Nothing changed since an uploaded save: toast `Nothing changed since your last save.` (`F14`).
3. Otherwise chip *Waiting* and its panel opens by itself (`G11`): `Not uploaded yet` /
   `2 devices changed since your last save: ceos and xrv9k. 19 lines added, 1 removed.` with **Upload**,
   **Not now**, **See changes** and `Saved files can contain passwords or keys.` A change to the topology
   file or the map is named in the sentence too (`The topology changed.`). Each device counts once; its
   restore artifact is never a second change.
4. **See changes** opens the *What changed* drawer (`F04`): one entry per device and one each for the
   topology file and the map when they changed, with the real line diff from `diff-view.js`, and the same
   Upload / Not now at the top. Every file the upload would send is visible in this drawer.
5. **Upload** pushes. Success: chip *Saved*, toast `Uploaded to github.com.` (the real remote host).
   Failure: chip *Failed*, panel `Upload failed` / `Your save is safe on the lab VM, but github.com could
   not be reached.` with **Try again** and **Details** (`F13`); Details opens today's save window.
6. **Not now** leaves the save on the VM; the chip stays *Waiting*. This is today's "Save on this VM only".
7. Naming (`F06`): the panel of a finished save shows its name in an editable field and
   **Keep as a checkpoint**. Both are optional and never block anything.

### 5.4 Loading (this is "Apply to running lab", in full)

1. **Load** opens the Load panel (`G02`) with two groups. `Your saves`: the latest save and the most recent
   checkpoints. `Lab states`: every other folder of the repository that holds a saved state, named from its
   folder (today's `gitVersionGroups` and `version_label` logic), so a course's `start`, `broken` and `final`
   appear as **Start**, **Broken**, **Final**. The appendix markup says "From your instructor"; the heading
   is **Lab states**. Then **All versions** and **Browse the repository…**.
2. A state that covers fewer devices than the lab says so on its row (`2 of 4 devices`). A state saved
   without restore artifacts stays listed, disabled, as `View only` with the reason.
3. Choosing one runs the existing restore preflight and shows (`G03`): `Load Final?` / `The running
   configuration of the ticked devices is replaced. The current one is backed up first; nothing reboots.`
   and one row per device with a tick box and `5 lines differ`, `Already matches`, or, greyed, `Not in this
   state` (`G07`); then **Load** (danger), **Cancel**, **See what's different**. A device the preflight
   reports unreachable or blocked shows that reason and cannot be ticked. When the state's topology file
   differs from the lab's, one line says so (`Saved on a different topology: 3 of 4 devices match.`) with
   **View its topology**; Load never changes the topology (D10).
4. **Load** submits the restore for the ticked devices. Chip *Loading*; the panel lists each device as
   `Waiting`, `Loading…`, `Loaded` (`G04`). Closing the panel does not stop the load.
5. All loaded: chip *Running*, toast `Final loaded on 4 devices.`, chip panel (`G05`) `Running Final` /
   `Loaded 1 minute ago on all 4 devices.` / `Your latest save: …` / `Before loading: backed up
   automatically`, with **Undo this load** and **What changed** (today's restore job window).
6. Some not changed: chip *Partial*, panel `Loaded on 3 of 4 devices` with one row per device (`G06`),
   **Try xrv9k again**, **Undo this load**, **Details**. Use the restore service's outcome vocabulary
   exactly: `Kept previous` only when the job read the device back as rolled back; `uncertain` is worded as
   not confirmed and sends the person to Details. Never soften or guess an outcome.
7. Lab not running: `Start the lab to load a state` with **Start lab** (`G09`).
8. A lab with no saves of its own still offers the lab states (`G08`).
9. The chip leaves *Running* when the next save completes.

**Parity gate.** Every way to reach "Apply to running lab…" today has a counterpart: Saved versions rows,
the saved-version view dialog, the folder browser's apply for any folder, "Load a saved version…", the lab
banner while a restore runs, and the restore job window. Loading works from any folder of the repository
that holds a saved state, whether or not any lab is connected to it. The pre-restore backup, the per-device
transaction with timed recovery, the confirmation only after management was proven, and the result
vocabulary are untouched.

### 5.5 Save as a lab state (D9)

The chip panel and the All versions drawer offer **Save as a lab state…**. It asks for a name and a folder
(the folder chooser of section 6.3, starting beside the lab's own folder, with `start`, `broken` and `final`
offered as one-click names), captures the lab now, and writes the complete state (topology, map, device
configurations, restore artifacts) to that folder, with the same upload sentence as any save. The lab's own
save location does not change. This is how a course author produces the states that students load.

### 5.6 The chip panel at rest

`G10`: `Saved 21 minutes ago` / the save's name / `Running: your latest save` / `Uploaded: yes, to
github.com`, then **All versions**, **Save as a lab state…** and **Save settings**.

### 5.7 All versions drawer

`F11`: groups `Your saves`, `Checkpoints`, `Starting point` (the baseline), `Lab states`, then, folded,
other labs in the repository and everything else. A row opens in place with **Load this state…**,
**See what's different**, **View files** (topology and map included) and **Download ZIP**. Your own saves
also offer **Keep as a checkpoint** and **Use as starting point…** (today's Set baseline with its replace
review). A design export stays view and download only. The drawer ends with **Full history…** and
**Browse the repository…**. The appendix markup says "Go back to this version…"; the wording is
**Load this state…**.

### 5.8 Save settings drawer

`F15`: where the lab saves (repository and folder) with **Change folder…** (the folder chooser),
**Use a different repository…**, **Connect by URL…**; the devices included in every save; the folded Git
details including Refresh status and Update from the repository; **Disconnect this lab…**; **Save settings**.

### 5.9 First save

`F12`: chip *Not saved*; pressing Save shows `Not saved yet` / `Your first save goes to <repository>, in a
folder named <lab>.` with **Save**, **Choose another place** and `Saved files can contain passwords or
keys.` With no repository on the VM, the same panel asks for the repository's HTTPS address in one field
(today's connect-by-URL logic) and continues to the save. It must work on a standard install, where the
repository is registered at its top level (see 6.1).

### 5.10 Frontend house rules

Plain scripts, no framework, no build step, no CDN, CSP `script-src 'self'`, no inline styles on `/`,
`esc()` on every interpolation, `setMarkup` for anything re-rendered on the 4 s poll. A new script needs
`?v=<release>` in every page. Replace the `rx-*` placeholder classes with names that fit `style.css`. Keep
the two-tone focus ring and the documented contrast figures; compute contrast for any new colour use.
Every panel and drawer is operable by keyboard; tick boxes are real inputs with labels; status changes are
announced through a polite live region. Wherever a control is disabled, the reason is visible text and the
action that clears it is beside it.

### 5.11 Where everything goes

| Today | After |
|---|---|
| Save progress (header and tab) | **Save** |
| "What changed?" label | Optional name after the save |
| Review before uploading | The upload sentence and the *What changed* drawer |
| Save on this VM only | Save, then **Not now** |
| Upload saved progress / Review and upload… | **Upload** in the chip panel |
| Create checkpoint… | **Keep as a checkpoint** |
| Set baseline… | **Use as starting point…** in All versions |
| Load a saved version… / Apply to running lab… (every entry point) | **Load** and **Load this state…** |
| Saved versions: View, Compare, Apply | All versions drawer rows |
| Full history… | All versions drawer |
| Recent saves: Open, Review and upload, Keep snapshot only | Chip panel; **Details** opens today's save window |
| Save location card, folder browser, devices, Git details, Update, Disconnect | Save settings drawer and the folder chooser |
| Last configuration change line | Chip *Running* / *Partial* and **What changed** |
| "Saving to Git is not possible right now" | Chip *Can't save* with the reason and its fix |
| Lab banner actions that pointed at the tab | The matching header panel or today's job window |
| Links to the Progress tab (`view=progress`, alias `git`) | The lab's default tab with the chip panel open |
| Text that says "under Progress" | Reworded to name Save, Load or Save settings |

## 6. Design specification: any folder, never blocked (G2, D8)

This is the hard part. Design it in `DESIGN.md` and have it reviewed before writing code.

### 6.1 What is wrong today (reproduced by the owner on 1.30.59)

- First save of lab `UX-TEST-003` into repository `Archtop-Lab`, folder `UX-TEST-003`: refused with
  `Lab folders in one repository cannot overlap: the repository root is already a lab folder. Choose a
  folder beside it.` Nothing is beside the root, so the person cannot continue.
- Same lab, folder browser: the top level is marked `Lab folder`, **New folder…** is greyed out with
  `Folders cannot be created inside another lab's folder.`, while the same panel says `This lab folder is
  free — no lab saves here yet.`
- Cause: guided setup (`deploy/setup-git.sh` without `--prefix`) and connect-by-URL with an empty folder
  register the checkout with `prefix: ''`. The manager then asks the VM helper to register the lab's folder
  (`register-prefix`, no `retire`), and `check_overlap` in `host_git.py` refuses any folder under, above or
  equal to a registered one. The registration at the root belongs to no lab; it exists only because the
  repository was registered. More generally, the model "each lab folder is a registration on the VM, and
  registrations may not nest" leaks into the UI as rules a person cannot be expected to know.

### 6.2 The outcome required

For any repository the VM account can use and any folder path a person chooses or types:

| The person chooses | What happens |
|---|---|
| A folder that does not exist | It is created and used. |
| An existing folder with ordinary files and no saved state | It is used. Other files are left alone. |
| The repository's top level | It is used. |
| A folder inside, above or beside a folder another lab saves to | It is used. Nesting is allowed. |
| The very folder another connected lab saves to | One question: `<Other lab> saves here too.` with **Save in <folder>/<this lab>** (suggested) and **Use this folder anyway** (the other lab is disconnected from it; its saves stay as versions). |
| A folder that already holds a saved state from another lab or a course (a lab state) | One question: `This folder holds the state "Start".` with **Save beside it in <folder>/<this lab>** (suggested) and **Replace it** (older contents stay in Git history). |
| A folder that is part of a saved state (`latest`, `baseline`, `checkpoints/<name>`) | The lab folder above it is used, and the panel says so. |
| A name with characters that are not safe in a path | Corrected as typed, with the result shown, as the checkpoint name field does today. |
| A folder while a save of this lab still waits for upload | The change proceeds after one inline choice: **Upload it, then move** or **Move and keep that save on the VM only**. Never a refusal. |
| A folder registered on the VM that no lab uses | Invisible. It never blocks, never shows as "another lab's folder", and is replaced or reused as needed. |

**New folder…** is always enabled, everywhere it appears, in every state of the repository. Inside a saved
state it creates the folder in the lab folder above and says so; everywhere else it creates the folder
where the person is. Two texts on one screen never contradict each other: "free", "in use" and every reason
come from one answer.

### 6.3 The folder chooser

One component replaces the first-save form's folder field, the Save location card and the folder browser's
several modes. It shows the repository as a tree, lets the person pick or type any path, shows **New
folder…** always, marks folders that hold saves with whose they are (`UX-TEST-003 saves here`, `Lab state:
Start`), and ends in one button: **Save here**. The questions of 6.2 appear inside it, as buttons. It never
shows the words "registration", "prefix" or "overlap". The folder tree's open branches still belong to the
person (`gitPlacesState.expanded`).

### 6.4 How to get there (design constraints, not a prescription)

The lead designs the mechanism; these are the constraints and the author's reading of the code.

- Each lab writes only `<its folder>/latest`, `<its folder>/baseline` and `<its folder>/checkpoints/…`
  (`GitRepository.scope`, `clean`, `history`, `move`). Two labs in nested folders therefore do not write the
  same files unless they share the folder itself, or one lab's folder is named like a saved-state folder of
  the other. Verify this reading against every helper mode before relying on it. If it holds, the overlap
  rule can shrink to those two real collisions, both handled by 6.2; if it does not, find the smallest
  rule that is true and handle everything else automatically.
- Keep the VM helper a narrow tool. Structured stdin, fixed argv, the host lock, review digests, the
  option whitelist and the gateway's command list stay exact. Paths stay inside the registered checkout,
  with no `.`, `..`, `.git` segment and no symlink traversal. No force push, stash or destructive reset.
  The manager still never collects Git tokens or sends Git command text. `register()` in `host_git.py`
  stays equivalent to the child in `deploy/setup-git.sh`. Helper `VERSION` stays in lockstep.
- Prefer removing a restriction to adding a mechanism. Prefer the manager resolving a situation with the
  helper's existing modes (`register-prefix` with `retire`, `move`, `connect`) to a new helper mode. A new
  mode or option needs a written reason in `DESIGN.md` and `risk-reviewer`'s review.
- A registration that no lab is connected to and no pending save refers to is the manager's to replace.
  Decide that under the store lock.
- Stored bindings are never rewritten in place; pending jobs compare their digest. A folder change creates a
  new binding as today. Design the "save waits for upload" case of 6.2 around that fact.
- "Save as a lab state" (5.5) needs a save whose destination is a folder other than the lab's own. Design
  it so the lab's binding does not change and the state is a normal saved state that Load can read from
  any lab.
- The fixture's scripted helper (`docs/redesign/tools/fixture_manager.py`, `FakeGit`) must keep matching the
  real helper, including the new folder rules.
- Old installations keep working: existing registrations, legacy `x/latest` registrations, schema 1
  snapshots and the `.set` to `.cfg` pairing are compatibility code, not dead code.

### 6.5 What may still stop a save, and how it is shown

Only things outside the manager's control: the VM is unreachable; the VM account cannot push (no login, no
permission); the checkout has someone's unfinished Git operation, staged or unsaved edits in the save's
folder; the local and online histories diverged; an included device cannot be read. Each of these is stated
in one plain sentence in the chip panel with the action that clears it (**Try again**, **Update from the
repository**, **Check the VM connection…**, **Details**), and the save resumes from there. None of them is
a folder rule.

## 7. Backend and data changes

Each needs unit tests. Keep them as small as the design allows.

1. **The whole lab in every save (G1).** Verify, with tests, that every save path (latest, checkpoint,
   baseline, lab state, checkpoint from an existing save) carries the topology file and the map when the lab
   has them, that the manifest records them, that the upload review shows them, and that All versions can
   view and download them. A lab without a map saves without one and says so nowhere as an error. If the VM's
   own files beside the deployed topology are newer than the manager's copy, the capture uses them, as today.
2. **Folder model (D8).** As designed in section 6: helper rule change, manager folder route, bindings,
   pending-save handling, the folder chooser's single answer for "who saves here".
3. **Optional label (D2).** `Save.note` may be empty; the manager writes the label once the changed files
   are known and before the commit, and records that it was automatic. Renaming afterwards changes the name
   the manager shows and never rewrites a Git commit. A rename route validates like today's note.
4. **Checkpoint from an existing save (D6).** Through the save route's existing `backup_job_id` path with
   `target: 'checkpoint'`, without reading a device. If the save's capture is no longer kept, the tick box
   is disabled with that reason. Never recapture silently.
5. **Upload (D3).** The server rule is unchanged: an upload requires the request that states the review
   happened. `gitReviewJob` remains the only sender of `{push: true, reviewed: true}`; the Upload buttons in
   the panel and the drawer both go through it.
6. **Load (D4, G3).** The restore route still requires `acknowledge: true`; the Load button sends it.
   Preflight, pre-restore backup, timed recovery and outcome rules are untouched; `restore.py` knows no NOS
   command. Add what the panel needs and does not have: the per-state device coverage for the list, and
   the topology comparison of 5.4 step 3.
7. **Undo this load (D7).** A load of the previous job's `pre_backup_job_id` through the existing restore
   source `backup_job_id`, through the same preflight and confirmation. No new restore mechanism.
8. **Save as a lab state (D9).** As designed in section 6.4.

Check the `public_*` function before exposing any new field. Stored-data compatibility code stays.

## 8. Rules that still hold, and the three that change

All of `CLAUDE.md` "Invariants that must not regress" applies, with these three owner changes, which you
must also write into `CLAUDE.md`:

- *Was:* "Pending saves block folder moves and reconnects; one registration per lab; overlap rules are the
  VM's." *Now:* any folder may be chosen; the manager resolves folder situations itself (section 6); a
  pending save is resolved inline when the folder changes; a planned folder is still never worded as
  existing in the repository.
- *Was:* the label is required. *Now:* optional, with an automatic name (D2).
- *Was:* the review dialog opens before every upload. *Now:* the review is the upload sentence with the
  diff on request (D3). There is still no upload without a person's explicit Upload, no opt-out and no
  setting that skips it.

Unchanged and most at risk here:

- The helper boundary in section 6.4, second point.
- A load is a whole-configuration replace inside the NOS's own transaction with timed recovery, after a
  mandatory backup; an unconfirmed change is reported rolled back only after read-back, otherwise uncertain;
  a state without restore artifacts is view and download only and listed with that reason.
- No login; every route behind the same-origin guard; mutating requests carry a body.
- Logs and job messages carry controlled metadata only, never configuration text.
- Every existing test keeps its behavioural claim. A label pinned by an old regex is rewritten, never
  deleted. A test whose subject an owner decision removes is rewritten to assert the new behaviour, and the
  change is listed in the report with the decision that caused it.

## 9. Tests and evidence

1. **Unit.** Python: helper folder rules (every row of 6.2), manager folder route, bindings and pending
   saves, optional label, rename, checkpoint from a save, lab state save, undo source, topology and map in
   every save path. Node: the chip state function for every row of 5.2, panel markup per state, folder
   chooser answers, New folder enabled in every state, routing of old Progress links, the single-sender rule
   for `{push: true, reviewed: true}`.
2. **CI list.** `.github/workflows/release-check.yml` runs an explicit list; append every new test file.
3. **Fixture browser pass.** Extend the fixture manager so it has: a repository registered only at its top
   level, nested lab folders, a folder shared by two labs, course states `start`, `broken`, `final`, a state
   without restore artifacts, a state covering a subset of devices, a state from a different topology.
   Every state in section 5 and every row of 6.2 gets a screenshot from the working implementation at 1440,
   1280, 760 and 390 px, with zero console and page errors, stored under `docs/git-redesign/evidence/`.
4. **The "try to get blocked" pass.** An Opus specialist, who did not write the folder code, spends a full
   pass trying to reach any refusal, greyed-out control or dead end in the save, folder and load flows, in
   the fixture and on dev1: odd names, deep nesting, the top level, another lab's folder, a state's folder,
   pending saves, two labs at once, a repository with thousands of files, a brand-new empty repository.
   Every finding is fixed or listed with the reason it is outside the manager's control (6.5).
5. **Friction budget**, measured and recorded: first save on a standard install, at most 2 clicks and
   nothing typed; later saves, 2 clicks; load a lab state, 3 clicks; change folder, at most 4 clicks with
   no refusal; save as a lab state, at most 4 clicks plus the name.
6. **Live pass on dev1**, against a real GitHub repository, with at least one device per restore driver
   available on dev1 (Junos, EOS, IOS XR where images exist):
   - G1: after a save, the folder on github.com holds the topology file, the map and one configuration
     per included device; change the map and a device, save, and see both in the next commit.
   - G2: repository registered by guided setup at its top level; first saves of two labs; a lab moved into
     a folder inside another lab's folder; a new folder created at the top level, inside a lab folder and
     inside a nested one; a folder change while a save waits for upload.
   - G3: author `start`, `broken` and `final` with Save as a lab state; load each onto the running lab and
     confirm on every device's CLI that the configuration is that state's; load a state on a second lab
     with the same topology; a device made unreachable during a load; undo a load; a stopped lab.
   - Saving: See changes, Upload; Not now then upload later; unchanged save; upload failure and Try again.
   Record what ran, on which devices, with which results.
7. `clab-backup-ui/VALIDATION.md` states which evidence is unit, fixture, CI or live. Anything not run is
   listed as not run, with the reason.

## 10. Documentation and release

- Rewrite `docs/GIT-PROGRESS.md` and `docs/GIT-SETUP.md` for the new model, and update
  `docs/LAB-OPERATIONS.md`, `docs/TOUR.md`, `docs/README.md`, the app README and `NODE-FEATURES.md` wherever
  they describe the Progress tab, folder rules or Apply to running lab. Add a short guide for course
  authors: how to produce start, broken and final states and how students load them.
  `docs/student-quick-start/` is a dated record: do not edit it, list which of its steps are out of date.
- New folder `docs/git-redesign/` (design, inventory, evidence, pickup notes, this prompt, the reference
  pack when present). Register it as a history folder in `deploy/verify-release.py` (`HISTORY_DIRS`) and in
  `docs/REPOSITORY-MAINTENANCE.md`.
- One release when the work is complete: number by `docs/REPOSITORY-MAINTENANCE.md`, moved only with
  `deploy/set-release.py`; the three history sections; `deploy/verify-release.py` and
  `python3 docs/maintenance-audit/tools/check_links.py`. Update `CLAUDE.md` (changed invariants, routing
  row, delegation section).

## 11. Order of work

1. Routing rules and agent definitions (section 2), first commit. Baseline: both suites and
   `verify-release.py`, counts recorded.
2. Inventory, then the design round and its Opus review (`DESIGN.md`).
3. The owner's two reproduced defects (6.1) fixed against today's UI as their own commit with tests, so
   they can ship alone if the owner asks.
4. Folder model: helper, manager, fixture helper, folder chooser.
5. Header control and status function; save flow; load flow with undo; save as a lab state.
6. Drawers; first save; remove the Progress tab; redirect old links; reword references.
7. Fixture pass, the "try to get blocked" pass, the live pass.
8. Documentation, release, pull request.

Steps 4 to 6 run in parallel wherever files do not collide. Commit with the suites green and push the
branch after each step.

## 12. Done means

- G1 to G4 are each demonstrated live on dev1, or each undemonstrated item is named with its reason.
- No folder choice in 6.2 ends in a refusal, and New folder is never disabled, in the fixture and live.
- Every entry point of Apply to running lab has its counterpart and was exercised on each available
  platform.
- The inventory shows a new home for every capability and a new outcome for every refusal message.
- Both suites, `node --check` on every changed script, `git diff --check`, `verify-release.py` and the link
  check pass; CI is green on the pull request.
- The pull request description lists: what changed; the owner decisions as implemented; the folder model
  in ten lines; every helper change with its review; every rewritten test and why; what was validated
  where; which models ran which slices; anything left open. End the session by printing that summary.

If something outside this prompt blocks you, record the assumption in `docs/git-redesign/PICKUP.md` and
continue. Stop and report instead of continuing only if continuing would break a rule in section 8.

## Appendix A. Exact markup and CSS of the approved mockups

This is the static markup and the extra stylesheet that produced the reference boards, so the look and the
wording can be rebuilt without the images. It is a specification, not code to ship: there is no state or
behaviour in it, `rx-*` and `px-*` are placeholder class names, icons are abbreviated to `<svg class="icon">…</svg>`,
and names, times and counts are stand-in data. Every other class (`button`, `pill`, `menu`, `drawer`,
`dialog-head`, `checkbox-label`, `git-destination-line`, `git-node-scope`, `diff-file` …) already exists in
`style.css`. The header markup replaces the content of `.git-save-control`; panels sit inside `.rx-pop`.

The mockups predate three wording decisions. Where they differ, sections 5 and 6 win: the Load panel's
second group is headed **Lab states** (the markup says "From your instructor"); the action on a row is
**Load this state…** (the markup says "Load this version…"); and the Save settings drawer's folder controls
open the folder chooser of section 6.3. There is no mockup of the folder chooser or of "Save as a lab
state…": design them in the same visual language (one sentence, one primary button, quiet secondary
actions, plain lists).

### A.1 Extra CSS

```css
dialog.px-drawer{width:min(600px,100vw)}
.px-drawer h3{font-size:15px;margin:20px 0 6px}
.px-drawer .git-node-scope{grid-template-columns:repeat(2,minmax(0,1fr));margin:8px 0}
.px-drawer details{margin-top:8px}
.px-drawer details summary{cursor:pointer;font-size:13px;font-weight:600;color:var(--accent-strong)}
.px-drawer-foot{display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap;margin-top:20px;padding-top:16px;border-top:1px solid var(--line)}
.rx-col{max-width:620px;margin:48px auto 72px;position:relative}
.rx-more{position:absolute;top:0;right:0}
.rx-state{display:flex;align-items:center;gap:12px;font-size:28px;font-weight:700;letter-spacing:-.02em;color:var(--ink);margin:0;line-height:1.2}
.rx-dot{width:12px;height:12px;border-radius:50%;background:var(--ok);flex:none}
.rx-dot.warn{background:var(--warn)}
.rx-sub{margin:8px 0 28px;color:var(--muted);font-size:15px;line-height:1.5;max-width:520px}
.rx-save{min-height:48px;padding:12px 28px;font-size:16px}
.rx-row{display:flex;align-items:center;gap:8px 18px;flex-wrap:wrap}
.rx-quiet{border:0;background:none;padding:6px 2px;font-size:14px;font-weight:600;color:var(--accent-strong);cursor:pointer}
.rx-note{margin:16px 0 0;font-size:12px;color:var(--muted)}
.rx-h{font-size:12px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);margin:64px 0 4px}
.rx-list{list-style:none;margin:0;padding:0}
.rx-list>li{border-bottom:1px solid var(--line)}
.rx-ver{display:flex;width:100%;justify-content:space-between;gap:16px;align-items:baseline;padding:14px 2px;border:0;background:none;text-align:left;cursor:pointer;font-size:15px;color:var(--text)}
.rx-ver .rx-when{color:var(--muted);font-size:13px;white-space:nowrap}
.rx-ver svg{color:var(--accent);margin-right:8px;vertical-align:-2px}
.rx-list>li.rx-open{border:1px solid var(--line);border-radius:var(--radius-lg);background:var(--surface);padding:4px 16px 16px;margin:8px -16px}
.rx-open .rx-ver{font-weight:600;color:var(--ink)}
.rx-open p{margin:0 0 14px;color:var(--muted);font-size:13px}
.rx-foot{margin:20px 0 0}
.rx-center{max-width:520px;margin:96px auto 120px;text-align:center}
.rx-center .rx-state{justify-content:center}
.rx-center .rx-sub{margin-left:auto;margin-right:auto}
.rx-center .rx-row{justify-content:center}
.rx-center .rx-back{margin-top:28px}
dialog.rx-dialog{width:min(560px,calc(100vw - 32px))}
.rx-dialog .rx-list{margin-top:8px}
.rx-dialog .rx-note{margin-top:14px}
.rx-dialog .rx-ver{padding:12px 10px;border-radius:var(--radius)}
.rx-dialog li.rx-picked{border-bottom-color:transparent}
.rx-dialog li.rx-picked .rx-ver{background:var(--accent-soft);color:var(--ink);font-weight:600}
.rx-head{display:flex;align-items:center;gap:8px}
.rx-chip{gap:8px;font-weight:500}
.rx-chip .rx-dot{width:8px;height:8px}
.rx-pop{position:absolute;top:calc(100% + 6px);right:0;width:380px;box-sizing:border-box;padding:18px;background:var(--surface);border:1px solid var(--line);border-radius:var(--radius-lg);box-shadow:var(--shadow-menu);z-index:20;text-align:left;white-space:normal}
.rx-pop .rx-save{min-height:40px;padding:8px 22px;font-size:14px}
.rx-pop .rx-note{margin-top:12px}
.rx-pop .rx-state{font-size:18px;gap:10px}
.rx-pop .rx-state .rx-dot{width:10px;height:10px}
.rx-pop .rx-sub{font-size:13px;margin:6px 0 14px}
.rx-pop .rx-h{margin:18px 0 0}
.rx-pop .rx-ver{font-size:13px;padding:9px 2px}
.rx-pop .rx-ver .rx-when{font-size:12px}
.rx-pop .rx-list>li:last-child{border-bottom:0}
.rx-pop .rx-foot{margin:10px 0 0;padding:10px 0 0;border-top:1px solid var(--line);display:flex;justify-content:space-between}
.rx-pop .rx-quiet{font-size:13px;padding:2px}
.rx-menu{min-width:260px}
.rx-dot.bad{background:var(--danger)}
.rx-dot.none{background:transparent;box-shadow:inset 0 0 0 2px var(--muted)}
.rx-dot.busy{background:var(--accent);box-shadow:0 0 0 4px var(--accent-soft)}
.rx-pop .rx-open{margin:6px -10px;padding:2px 10px 12px}
.rx-pop .rx-open p{font-size:12px;margin-bottom:10px}
.rx-pop .button.small{min-height:32px}
.rx-pop #rx-name{width:100%;margin:8px 0 12px;box-sizing:border-box}
.rx-pop label.rx-keep{display:flex;align-items:center;gap:8px;font-size:13px;margin:0 0 4px;color:var(--text);font-weight:400}
.rx-pop label.rx-keep input{width:auto;margin:0;flex:none}
.rx-pop .rx-sub+.rx-row{margin-top:-2px}
dialog.rx-drawer{width:min(760px,100vw)}
.rx-drawer .drawer-head .rx-row{margin-top:14px}
.rx-drawer .diff-file{margin:0 0 8px}
.rx-drawer .rx-h{margin:28px 0 4px}
.rx-drawer .rx-h:first-child{margin-top:16px}
.rx-drawer .rx-list>li.rx-open{margin:8px -12px;padding:4px 12px 14px}
.rx-drawer .rx-foot{margin:24px 0 0}
#lab-content{--lab-action-col:35rem}
.rx-dot.info{background:var(--accent)}
.rx-pop.rx-wide{width:440px}
.rx-pop .rx-h:first-child{margin-top:0}
.rx-pop .rx-h{margin:16px 0 0}
.rx-ver[disabled]{cursor:default;color:var(--muted)}
.rx-ver .rx-why{display:block;font-size:12px;color:var(--muted);margin-top:2px}
.rx-devs{list-style:none;margin:0 0 14px;padding:0;border:1px solid var(--line);border-radius:var(--radius)}
.rx-devs li{display:flex;align-items:center;gap:10px;padding:8px 12px;font-size:13px;border-top:1px solid var(--line)}
.rx-devs li:first-child{border-top:0}
.rx-devs label{display:flex;align-items:center;gap:10px;margin:0;font-weight:500;color:var(--ink)}
.rx-devs input{margin:0;flex:none}
.rx-devs small{color:var(--muted);font-size:12px;font-weight:400}
.rx-devs .rx-end{margin-left:auto;color:var(--muted);font-size:12px;white-space:nowrap}
.rx-devs .rx-end.ok{color:var(--ok-strong);font-weight:600}
.rx-devs .rx-end.bad{color:var(--danger-strong);font-weight:600}
.rx-devs .rx-end.now{color:var(--accent-strong);font-weight:600}
.rx-devs li.rx-off{color:var(--muted)}
.rx-kv{margin:0 0 4px;font-size:13px;color:var(--text)}
.rx-kv span{color:var(--muted)}
```

### A.2 Markup by state

**Header control at rest (G01)**

```html
<span class="rx-head"><span class="menu"><button type="button" class="button secondary rx-chip" aria-haspopup="true" aria-expanded="false"><span class="rx-dot"></span>Saved 21 min ago<svg class="icon">…</svg></button></span><button type="button" class="button primary">Save</button><span class="menu"><button type="button" class="button secondary" aria-haspopup="true" aria-expanded="false">Load</button></span></span>
```

**Chip panel at rest (G10)**

```html
<p class="rx-state"><span class="rx-dot "></span>Saved 21 minutes ago</p>
<p class="rx-sub">Interface descriptions cleaned up</p>
<p class="rx-kv"><span>Running:</span> your latest save</p>
<p class="rx-kv"><span>Uploaded:</span> yes, to github.com</p>
<div class="rx-foot"><button type="button" class="rx-quiet">All versions</button><button type="button" class="rx-quiet">Save settings</button></div>
```

**Chip panel while saving (F02)**

```html
<p class="rx-state"><span class="rx-dot busy"></span>Saving…</p>
<p class="rx-sub">Reading the configuration of 4 devices. You can keep working.</p>
```

**Chip panel after Save: upload prompt (G11)**

```html
<p class="rx-state"><span class="rx-dot warn"></span>Not uploaded yet</p>
<p class="rx-sub">2 devices changed since your last save: ceos and xrv9k. 19 lines added, 1 removed.</p>
<div class="rx-row"><button type="button" class="button primary rx-save">Upload</button><button type="button" class="rx-quiet">Not now</button><button type="button" class="rx-quiet">See changes</button></div>
<p class="rx-note">Saved files can contain passwords or keys.</p>
```

**Chip panel: name and checkpoint (F06, without its version list)**

```html
<p class="rx-state"><span class="rx-dot"></span>Saved just now</p>
<label class="sr-only" for="rx-name">Name of this save</label>
<input id="rx-name" value="ceos and xrv9k changed" maxlength="120" autocomplete="off"><label class="rx-keep checkbox-label"><input type="checkbox">Keep as a checkpoint</label>
```

**Chip panel: upload failed (F13, without its version list)**

```html
<p class="rx-state"><span class="rx-dot bad"></span>Upload failed</p>
<p class="rx-sub">Your save is safe on the lab VM, but github.com could not be reached.</p>
<div class="rx-row"><button type="button" class="button primary rx-save">Try again</button><button type="button" class="rx-quiet">Details</button></div>
```

**Chip panel: first save (F12)**

```html
<p class="rx-state"><span class="rx-dot none"></span>Not saved yet</p>
<p class="rx-sub">Your first save goes to CLAB-MNGR-DEV-LLM, in a folder named restore-square.</p>
<div class="rx-row"><button type="button" class="button primary rx-save">Save</button><button type="button" class="rx-quiet">Choose another place</button></div>
<p class="rx-note">Saved files can contain passwords or keys.</p>
```

**Load panel (G02)**

```html
<h2 class="rx-h">Your versions</h2>
<ul class="rx-list"><li><button type="button" class="rx-ver"><span>Interface descriptions cleaned up</span><span class="rx-when">21 minutes ago</span></button></li>
<li><button type="button" class="rx-ver"><span><svg class="icon">…</svg>ospf-up</span><span class="rx-when">2 hours ago</span></button></li>
<li><button type="button" class="rx-ver"><span><svg class="icon">…</svg>loopbacks-reachable</span><span class="rx-when">5 hours ago</span></button></li>
</ul>
<h2 class="rx-h">From your instructor</h2>
<ul class="rx-list"><li><button type="button" class="rx-ver"><span>Final state (instructor)</span><span class="rx-when">2 of 4 devices</span></button></li>
<li><button type="button" class="rx-ver"><span>Broken</span><span class="rx-when">4 devices</span></button></li>
<li><button type="button" class="rx-ver" disabled><span>Starting state<span class="rx-why">Saved without the files needed to load it</span></span><span class="rx-when">View only</span></button></li>
</ul>
<div class="rx-foot"><button type="button" class="rx-quiet">All versions</button><button type="button" class="rx-quiet">Browse the repository…</button></div>
```

**Load panel: confirmation (G03)**

```html
<p class="rx-state"><span class="rx-dot warn"></span>Load ospf-up?</p>
<p class="rx-sub">The running configuration of the ticked devices is replaced. The current one is backed up first; nothing reboots.</p>
<ul class="rx-devs"><li class=""><label><input type="checkbox" checked><span>ceos <small>EOS</small></span></label>
<span class="rx-end ">5 lines differ</span></li>
<li class=""><label><input type="checkbox" checked><span>cjunosevolved <small>Junos</small></span></label>
<span class="rx-end ">4 lines differ</span></li>
<li class=""><label><input type="checkbox" checked><span>vjunos-switch <small>Junos</small></span></label>
<span class="rx-end ">Already matches</span></li>
<li class=""><label><input type="checkbox" checked><span>xrv9k <small>IOS-XR</small></span></label>
<span class="rx-end ">7 lines differ</span></li>
</ul>
<div class="rx-row"><button type="button" class="button danger">Load</button><button type="button" class="rx-quiet">Cancel</button><button type="button" class="rx-quiet">See what’s different</button></div>
```

**Load panel: a version covering 2 of 4 devices (G07)**

```html
<p class="rx-state"><span class="rx-dot warn"></span>Load Final state (instructor)?</p>
<p class="rx-sub">This version covers 2 of your 4 devices. The others are left as they are.</p>
<ul class="rx-devs"><li class=""><label><input type="checkbox" checked><span>cjunosevolved <small>Junos</small></span></label>
<span class="rx-end ">12 lines differ</span></li>
<li class=""><label><input type="checkbox" checked><span>vjunos-switch <small>Junos</small></span></label>
<span class="rx-end ">9 lines differ</span></li>
<li class="rx-off"><label><input type="checkbox" disabled><span>ceos <small>EOS</small></span></label>
<span class="rx-end ">Not in this version</span></li>
<li class="rx-off"><label><input type="checkbox" disabled><span>xrv9k <small>IOS-XR</small></span></label>
<span class="rx-end ">Not in this version</span></li>
</ul>
<div class="rx-row"><button type="button" class="button danger">Load</button><button type="button" class="rx-quiet">Cancel</button><button type="button" class="rx-quiet">See what’s different</button></div>
```

**Load panel: loading (G04)**

```html
<p class="rx-state"><span class="rx-dot busy"></span>Loading ospf-up…</p>
<p class="rx-sub">Each device checks the new configuration itself and undoes it if it loses contact. You can keep working.</p>
<ul class="rx-devs"><li><span>ceos <small>EOS</small></span><span class="rx-end ok">Loaded</span></li>
<li><span>cjunosevolved <small>Junos</small></span><span class="rx-end ok">Loaded</span></li>
<li><span>vjunos-switch <small>Junos</small></span><span class="rx-end now">Loading…</span></li>
<li><span>xrv9k <small>IOS-XR</small></span><span class="rx-end ">Waiting</span></li>
</ul>
```

**Chip panel after a load (G05)**

```html
<p class="rx-state"><span class="rx-dot info"></span>Running ospf-up</p>
<p class="rx-sub">Loaded 1 minute ago on all 4 devices.</p>
<p class="rx-kv"><span>Your latest save:</span> Interface descriptions cleaned up, 22 minutes ago</p>
<p class="rx-kv"><span>Before loading:</span> backed up automatically</p>
<div class="rx-foot"><button type="button" class="rx-quiet">Undo this load</button><button type="button" class="rx-quiet">What changed</button></div>
```

**Chip panel: one device refused (G06)**

```html
<p class="rx-state"><span class="rx-dot warn"></span>Loaded on 3 of 4 devices</p>
<p class="rx-sub">xrv9k did not accept ospf-up and kept its previous configuration.</p>
<ul class="rx-devs"><li><span>ceos <small>EOS</small></span><span class="rx-end ok">Loaded</span></li>
<li><span>cjunosevolved <small>Junos</small></span><span class="rx-end ok">Loaded</span></li>
<li><span>vjunos-switch <small>Junos</small></span><span class="rx-end ok">Loaded</span></li>
<li><span>xrv9k <small>IOS-XR</small></span><span class="rx-end bad">Kept previous</span></li>
</ul>
<div class="rx-row"><button type="button" class="button primary">Try xrv9k again</button><button type="button" class="rx-quiet">Undo this load</button><button type="button" class="rx-quiet">Details</button></div>
```

**Load panel: lab with no saves (G08)**

```html
<p class="rx-sub">This lab has no saves of its own yet. You can start from one of these.</p>
<h2 class="rx-h">From your instructor</h2>
<ul class="rx-list"><li><button type="button" class="rx-ver"><span>Final state (instructor)</span><span class="rx-when">2 of 4 devices</span></button></li>
<li><button type="button" class="rx-ver"><span>Broken</span><span class="rx-when">4 devices</span></button></li>
<li><button type="button" class="rx-ver" disabled><span>Starting state<span class="rx-why">Saved without the files needed to load it</span></span><span class="rx-when">View only</span></button></li>
</ul>
<div class="rx-foot"><button type="button" class="rx-quiet">All versions</button><button type="button" class="rx-quiet">Browse the repository…</button></div>
```

**Load panel: lab not running (G09)**

```html
<p class="rx-state"><span class="rx-dot none"></span>Start the lab to load a version</p>
<p class="rx-sub">Loading puts a saved configuration onto running devices. This lab is not running.</p>
<div class="rx-row"><button type="button" class="button primary">Start lab</button></div>
```

**"What changed" drawer (F04; DIFF is the output of gitFilesDiffMarkup)**

```html
<dialog class="drawer rx-drawer" id="rx-drawer" aria-labelledby="rx-drawer-title"><div class="drawer-head"><div class="dialog-head"><h2 id="rx-drawer-title">What changed</h2>
<button type="button" class="icon-button close" aria-label="Close"><svg class="icon">…</svg></button></div>
<p class="drawer-meta">ceos and xrv9k · 19 lines added, 1 removed · not uploaded yet</p>
<div class="rx-row"><button type="button" class="button primary">Upload</button><button type="button" class="rx-quiet">Not now</button></div>
</div>
<div class="drawer-content"><p class="rx-note">Saved files can contain passwords or keys.</p>
DIFF</div>
</dialog>
```

**All versions drawer (F11; action reads "Load this version…" in the approved design)**

```html
<dialog class="drawer rx-drawer" id="rx-drawer" aria-labelledby="rx-drawer-title"><div class="drawer-head"><div class="dialog-head"><h2 id="rx-drawer-title">All versions</h2>
<button type="button" class="icon-button close" aria-label="Close"><svg class="icon">…</svg></button></div>
<p class="drawer-meta">Everything saved for restore-square. Choose one to load it.</p>
</div>
<div class="drawer-content"><h3 class="rx-h">Your saves</h3>
<ul class="rx-list"><li><button type="button" class="rx-ver"><span>Interface descriptions cleaned up</span><span class="rx-when">21 minutes ago</span></button></li>
<li><button type="button" class="rx-ver"><span>Point-to-point OSPF on all four links</span><span class="rx-when">47 minutes ago</span></button></li>
</ul>
<h3 class="rx-h">Checkpoints</h3>
<ul class="rx-list"><li><button type="button" class="rx-ver"><span><svg class="icon">…</svg>ospf-up</span><span class="rx-when">2 hours ago</span></button></li>
<li><button type="button" class="rx-ver"><span><svg class="icon">…</svg>loopbacks-reachable</span><span class="rx-when">5 hours ago</span></button></li>
</ul>
<h3 class="rx-h">Starting point</h3>
<ul class="rx-list"><li><button type="button" class="rx-ver"><span>Starting configuration</span><span class="rx-when">Yesterday</span></button></li>
</ul>
<h3 class="rx-h">From your instructor</h3>
<ul class="rx-list"><li class="rx-open"><button type="button" class="rx-ver"><span>Final state (instructor)</span><span class="rx-when">9 files</span></button><p>From your instructor · can be applied to all 4 devices</p>
<div class="rx-row"><button type="button" class="button secondary">Load this version…</button><button type="button" class="rx-quiet">See what’s different</button></div>
</li>
<li><button type="button" class="rx-ver"><span>Starting state</span><span class="rx-when">5 files</span></button></li>
<li><button type="button" class="rx-ver"><span>Broken</span><span class="rx-when">9 files</span></button></li>
</ul>
<div class="rx-foot"><button type="button" class="rx-quiet">Browse the repository…</button></div>
</div>
</dialog>
```

**Save settings drawer (F15)**

```html
<dialog class="drawer px-drawer" id="px-drawer" aria-labelledby="px-drawer-title"><div class="drawer-head"><div class="dialog-head"><h2 id="px-drawer-title">Save settings</h2>
<button type="button" class="icon-button close" aria-label="Close save settings"><svg class="icon">…</svg></button></div>
<p class="drawer-meta">Where restore-square saves, and which devices each save includes.</p>
</div>
<div class="drawer-content"><h3>Save location</h3>
<p class="git-destination-line"><code>CLAB-MNGR-DEV-LLM</code><span aria-hidden="true">›</span><code>restore-square/qa-1-30-37</code><span aria-hidden="true">›</span><code>latest/</code></p>
<div class="actions"><button type="button" class="button secondary small">Change folder…</button><button type="button" class="button secondary small">Use a different repository…</button><button type="button" class="button secondary small">Connect by URL…</button></div>
<details><summary>Git repo details</summary></details><h3>Devices included in every save</h3>
<fieldset class="git-node-scope"><legend class="sr-only">Devices included in every save</legend><label class="checkbox-label"><input type="checkbox" checked><span>ceos<small>EOS</small></span></label>
<label class="checkbox-label"><input type="checkbox" checked><span>cjunosevolved<small>Junos</small></span></label>
<label class="checkbox-label"><input type="checkbox" checked><span>vjunos-switch<small>Junos (vJunos-switch)</small></span></label>
<label class="checkbox-label"><input type="checkbox" checked><span>xrv9k<small>IOS-XR</small></span></label>
</fieldset><p class="form-help">clab-restore-square-host1 can’t be included yet — configuration saves aren’t supported for its platform.</p>
<p class="form-help">If an included device can’t be reached, the save stops and nothing is written — an older configuration is never saved in its place.</p>
<details><summary>Registration details</summary></details><details><summary>Advanced repository details</summary></details><div class="px-drawer-foot"><button type="button" class="link-button">Disconnect this lab…</button><button type="button" class="button primary">Save settings</button></div>
</div>
</dialog>
```
