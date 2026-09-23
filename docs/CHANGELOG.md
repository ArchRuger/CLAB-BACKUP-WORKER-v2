# Changelog

Release notes for every published version, newest first. Links point to the
guides in this folder; validation evidence for recent releases is in
[clab-backup-ui/VALIDATION.md](../clab-backup-ui/VALIDATION.md).

## Changes in 1.30.38

**Test logins includes hosts that are excluded from backups.** The lab-wide *Test logins* skipped a device whose
backup flag is off, which is every Linux host such as the network-multitool (no NOS platform, never backed up), although
its login is known and its CLI opens. Eligibility is now an address and a login only; the guide says so
([NODE-FEATURES](../clab-backup-ui/NODE-FEATURES.md)). Records of the 1.30.37 live checks are added with this release.

## Changes in 1.30.37

**Setup Script Cleanup Log, part 2: saves, diffs, restore progress and parallel restore, Test logins, the lab
builder, and the helper hardening.** Second release of the stream ([docs/ui-ux-cleanup/PICKUP.md](ui-ux-cleanup/PICKUP.md)).

- **Helper hardening (install this release, not 1.30.36, on a VM with engineer access).** The sudoers helper's
  `create` wrote the uploaded map file and set its mode by path, which follows a symlink planted in a group-writable
  engineer folder; every write in `create`, `revise` and `delete` now goes through the descriptor-based pattern
  `publish` uses (directory opened without following links, modes set on the open file, recovery copies in a history
  folder the helper owns), the review digest binds the existing map file's state, and anything but a regular file of
  at most 1 MiB in the map file's place is refused before the topology is written. The deploy review's plain text now
  says the topology runs as its file describes it (hooks, mounts, image pulls) and names the map file it will write.
- **Junos backups in the repository are `<node>.cfg`** (display-set text, as EOS and IOS XR already were); the
  hierarchical restore artifact stays `<node>.jcfg`. Older `<node>.set` saves stay listed, compared (paired per node;
  the upload review shows the rename as one changed file) and restorable ([GIT-PROGRESS](GIT-PROGRESS.md)).
- **Topology preview** fills the viewport (96% × 92%, full screen on a phone), fits the map on opening and on resize,
  and has no caption.
- **Every save has a label.** *Save progress* asks "What changed?" (required, up to 120 characters, kept as a draft
  through cancel and retry); the label is the Git commit message and names the save in the pending list, the history,
  the job window and the review. A new label on Latest still updates the same Latest folder; older saves without a
  label fall back to their kind and date.
- **The save destination is complete**: review, job window and details show `<repository> · <branch> · <path>` from
  the destination frozen on the job (never the current binding), the local checkout path and the commit, and say
  whether the save is on the VM, waiting for review, uploaded or verified on the remote.
- **Real diffs**: the upload review and *Compared with your latest save* render unified diffs (line numbers,
  insertions and deletions marked by colour and sign, hunk headers, per-file disclosure, wrapping on narrow screens)
  produced by the manager from the exact texts; nothing is normalised away.
- **"View configuration backup" closes the save windows it came from** (no stale *Saves waiting to be uploaded*
  under the destination) and moves the focus.
- **Replace running configuration**: every differing device row expands to the diff between the saved candidate and
  the running configuration read by the review, before anything is applied ("saved → running now"; devices that
  already match, or whose artifact or probe is missing, say so instead); the progress window lists each device's
  stages (Waiting → Backup → Validate → Replace, timed recovery armed → Fresh connection and read-back → Confirm →
  Done) with the current one highlighted, completed ones green with a check, and distinct Replaced / Already matched
  / Skipped / Failed / Rolled back / Uncertain outcomes, timed from the server clock and rebuilt on reopen or reload.
- **Devices are replaced in parallel**: independent devices run on a bounded pool (default 4, `RESTORE_NODE_WORKERS`
  1–8), each with its own backup check, timed recovery, fresh-connection read-back and confirmation; devices sharing
  one SSH endpoint run one after another; one device's failure or rollback never touches another's. The job records
  a per-device timeline that proves the overlap. The safety backup before and the check backup after stay one job each
  ([multi-platform restore README](multi-platform-restore/README.md)).
- **Test logins** beside the *Devices* heading (topology rail and Devices tab) runs the real SSH login test for every
  device with at most four sessions at once, shows "Testing login…" per device and updates the cards as answers come
  in; a disabled *Open CLI* names the reason and points to it. Nothing is marked ready without a real answer
  ([NODE-FEATURES](../clab-backup-ui/NODE-FEATURES.md)).
- **Lab builder**: *New lab* asks only for a name and a folder and opens a blank canvas (no starters); the empty status
  pill is hidden; a `.clab.yml` and its `.annotations.json` can be dropped on the welcome card or the canvas (or picked
  with *Open lab files…*), in any order, topology-only allowed, with the parser's reason on refusal and a confirmation
  before an unsaved draft is replaced; *View YAML* became an editable **YAML** panel beside the canvas: edit the text
  and Apply (Ctrl+Enter) to see it on the map, draw on the canvas and see the text follow, with syntax and shape
  diagnostics, Revert, and the editor's own Undo covering an apply; invalid text never replaces the last valid graph;
  a canvas edit reformats hand-written text (content kept) and the guide says so ([LAB-BUILDER](LAB-BUILDER.md)).

## Changes in 1.30.36

**Setup Script Cleanup Log, part 1: setup and onboarding, import, deploy review, layout, capture mapping.** First
release of the UI/UX cleanup stream ([docs/ui-ux-cleanup/PICKUP.md](ui-ux-cleanup/PICKUP.md); the requirement map with
PDF page numbers is [REQUIREMENTS.md](ui-ux-cleanup/REQUIREMENTS.md)).

- **Setup takes the routine choices itself** (`bash deploy/install.sh`): all VM interfaces on port 8081 when no `.env`
  exists (an existing `.env`, credentials, registrations and enabled components are retained), reviewed lab operations,
  VS Code / Containerlab access for the invoking account, backup of obsolete installation-media APT entries, the plan
  printed and started; Git setup runs as part of *Install or update manager, then set up Git*; a successful path prints
  its closing information and exits to the shell. `--advanced` restores every question ([INSTALL](INSTALL.md)).
- **Package-lock recovery**: when APT/dpkg is locked (typically `unattended-upgrades`), the installer names the process
  holding it *now*, prints one copyable command (`sudo python3 …/deploy/apt_lock.py --wait --pause-timers`) and offers to
  wait here and retry. `deploy/apt_lock.py` finds the holder from `/proc`, waits within a bound, optionally pauses the two
  `apt-daily` timers and restores exactly those it stopped, and never kills a process or deletes a lock file.
- **Git onboarding condensed**: GitHub CLI is installed when missing, the device login runs without gh's own questions
  (the one-time code and URL are printed unchanged, followed by
  `https://github.com/login/device/select_account` for browsers signed in to several accounts), a repository new to the
  manager registers at its root without the subfolder question (`--subfolder` and the "another lab in a registered
  repository" path still take one), and registration completes by itself once its checks pass. Setup still creates no
  commit and no push ([GIT-SETUP](GIT-SETUP.md)).
- **lazydocker** is installed for the invoking account from the upstream release for the VM's architecture into
  `~/.local/bin`, with one guarded PATH block in `~/.bashrc` (never duplicated).
- **VM connection prefilled from setup**: `setup-password.sh` hands the new `clab-discovery` password once to the manager
  through a one-time seed in the data directory (root and the manager account only); the manager stores it encrypted,
  fills address, port, account, inspection method and automatic check, and waits for one *Save and test connection*,
  which is the explicit first-use trust of the VM key (the key the installer recorded is shown for comparison; a
  different key is refused unless the replacement-key box is ticked) ([VM-CONNECTION](VM-CONNECTION.md)).
- **Upload a lab file** takes an optional saved map (`.annotations.json`) next to the topology; the pair goes through the
  same reviewed `create`, an existing map file is never replaced silently (the review says so and a recovery copy is
  kept), and the imported lab opens with its positions.
- **Open in Lab Builder…** (was *Edit visually…*); returning with *← My labs* or the browser's Back reopens the Topology
  file dialog on the same VM file, re-read from the VM.
- **Topology preview** is sized to the viewport and fits the map; its wiring caption is gone.
- **Start lab review** shows the command run on the VM directly (no *Technical details* toggle, no host-privilege
  warning box for a deploy, no "Runs on the lab VM…" caption), and the live output window opens by itself when the
  start is accepted; a window the student closed is not reopened by polling.
- **Notices can be hidden**: lab and home banners have an accessible close control; a hidden notice stays hidden across
  rerenders for that lab and text and returns when the text changes; a running-operation banner collapses to one line
  instead of disappearing. Hiding never acknowledges a job or enables an unavailable action.
- **network-multitool** nodes (`ghcr.io/srl-labs/network-multitool`, kind `linux`) use the image's documented login
  after profiles and inventory logins, so a stock node no longer asks for credentials; other Linux images are unchanged
  ([NODE-FEATURES](../clab-backup-ui/NODE-FEATURES.md)).
- **Topology tab**: the *Details* disclosure ("Lines show how the lab is wired…") is gone; the Devices column scrolls on
  its own beside the map at desktop widths (sticky heading, keyboard reachable).
- **Capture on the displayed port**: right-clicking a link and choosing an endpoint such as `ge-0/0/35` preselects the
  container interface containerlab created for it (per-kind rules for vJunos, cJunosEvolved, vQFX, XRv9k, cEOS, Linux),
  confirmed against the VM's live interface list; an unresolved port keeps the manual list with the reason
  ([CAPTURE](CAPTURE.md)).

## Changes in 1.30.35

**Student quick start delivered: the illustrated PDF guide, validated end to end.** Closing release of the stream
([docs/student-quick-start/PICKUP.md](student-quick-start/PICKUP.md)); no change to the manager's behaviour.
`docs/student-quick-start/Containerlab_Node_Manager_Student_Quick_Start.pdf` (20 pages, US Letter) walks a first-time
student through two workflows on the real manager — Scenario A, an instructor's lab (`link-basics`), and Scenario B, a
personal lab built in the lab builder and kept in Git together with its saved configurations — with real screenshots,
numbered steps (Action / Expected result / If not), a "what is saved where" table, troubleshooting and checklists. It
ships with its editable Markdown source, the one-command build (`build.sh`, WeasyPrint, apt-only toolchain), the
screenshot composition spec, the example materials (`examples/`), the walkthrough and reset tools (`tools/`), the
evidence of both executed scenarios and of the independent replays (`evidence/`), and `VALIDATION.md` with the SHA-256
of the inspected PDF. Two independent agent replays of both scenarios, from the documented starting states and using
only the PDF, passed every step; an Opus review of the text was applied (the guide now says plainly that the lab VM's
GitHub login is the student's account and that the Git steps run on the lab VM).

## Changes in 1.30.34

**Student quick start, part 2: Scenario B executed and recorded.** Second checkpoint of the illustrated student guide
([docs/student-quick-start/PICKUP.md](student-quick-start/PICKUP.md)); no change to the manager's behaviour. The personal-lab
walkthrough (lab builder → Save to the VM… → deploy → configure → a new private repository connected by URL → Save
progress → the owner-side Git step that publishes the topology and map → a second save and a checkpoint → destroy,
remove, clone the repository into the trusted lab folder, redeploy from that clone and apply the saved Latest) ran on the
development VM through the real pages, with device readbacks and remote trees as evidence. The guide's Scenario B text is
reconciled with that run; all figures are composed; the PDF is delivered with the next checkpoint.

- Observed and documented for students: the lab builder's *Start lab* leaves the builder page where it is (go back to
  My labs); the Node Editor can drop an image's registry prefix when the Network tab was edited (check *View YAML*);
  the redeploy from a clone must pick the file under the repository folder, whose path the *Topology file* dialog shows.

## Changes in 1.30.33

**Student quick start, part 1: Scenario A executed and recorded; a Git-identity fix in the helper.** First checkpoint
of the illustrated student guide ([docs/student-quick-start/PICKUP.md](student-quick-start/PICKUP.md)): the
instructor lab package `link-basics` (two cEOS routers, three saved states in a course repository), the Scenario A
walkthrough (deploy an instructor's lab, connect the student's own copy of the course repository, apply the starting
state, change, save, checkpoint, break and recover) executed on the development VM with screenshots and an evidence log,
the reproducible PDF pipeline (Markdown → WeasyPrint) and the first draft of the guide. The PDF itself is delivered with
the last checkpoint of the stream, not this one.

- **Connect a repository by URL no longer fails for a GitHub account without a display name.** The helper derives the
  commit identity from `gh api user`; when the profile's name is empty the tab-separated answer ends with an empty field,
  and trimming the line removed it, so the connection ended with "This VM account has no Git commit identity yet" although
  the documented fallback (login name and the account's noreply address) should have applied. Fixed in `host_git.py`
  (`ensure_identity`), with a regression test. An installed VM picks the fix up with
  `sudo bash "$HOME/projects/clab-manager/deploy/setup-git.sh" --refresh` (the launcher does this on every start).
- `docs/NAMING.md` names the three platforms live restore covers (it still said Junos only);
  `docs/student-quick-start/` is a history directory for the documentation check.

## Changes in 1.30.32

**Save location fix: live acceptance closed on the four images.** Second and closing release of the save-location
stream ([save-location-fix](save-location-fix/PICKUP.md)). No change to the manager's behaviour: this release carries
the four-image acceptance record and the QA tools that produced it.

- **Apply from `Final`, `Broken`, `working/latest`, a nested reference folder, the legacy `…/latest` layout, a
  checkpoint, the baseline and a historical commit**, each through the page onto cEOS 4.35.0F, cJunosEvolved
  26.2R1.7-EVO, vJunos-switch 23.2R1.14 and XRv9k 24.3.1 at once, with three deliberately different saved states so
  that reading the wrong folder could not pass: every node read back independently on the selected state, the lab's
  save location and the source folders untouched, no reboot, a normal backup afterwards.
- A mixed four-device apply with one node refused for somebody else's pending change ends `partial` and recovers; a
  corrupt manifest, a manifest whose file is missing, a commit outside the branch and a stale review are refused
  before any device is contacted.
- The evidence names its build and commit (`docs/save-location-fix/MATRIX.md`, `evidence/`).

## Changes in 1.30.31

**Saving as Latest updates the same `latest/` in place, and Apply to running lab… is offered for any folder that
holds a saved configuration.** First release of the save-location stream ([save-location-fix](save-location-fix/PICKUP.md)).

- **No more `working/latest/latest`.** A lab folder (the folder a lab saves to) is where Save progress writes `latest/`,
  `baseline/` and `checkpoints/<name>`; those names can no longer become a lab folder themselves. In the folder
  browser, choosing an existing `…/latest` folder resolves to the folder above it (the button says *Saves go to
  …/latest*); a typed folder name (New folder…, the first save, Connect by URL, the guided setup on the VM) and the
  API refuse such a name with that explanation, and so does the VM helper. A folder that holds a saved configuration,
  or sits inside one, is not a destination either. Reproduced live before the fix: a lab whose folder registration
  had been retired could re-choose `save-fix/working/latest` and its next save nested `save-fix/working/latest/latest`
  ([evidence](save-location-fix/evidence/00-repro-nested-latest.md)).
- **Labs that were caught by it keep working and can get out.** A registration an older release made at `…/latest` is
  left as it is (nothing stored is rewritten and its saves keep landing where they did); the Save location card now
  says so and names the way out: pick the folder above under *Change folder…* and choose *Save this lab here* without
  moving the files. The next save then updates the original `…/latest` again; the nested copy stays in the repository
  as its own saved configuration (the helper no longer refuses a save because a subfolder sits inside the snapshot).
- **Apply from any saved configuration.** A saved configuration is any repository folder holding `manifest.json`,
  whatever its name or depth: `Final`, `Broken`, `working/latest`, `course/lab/reference/solution`, the repository
  root. The folder browser offers *Apply to running lab…* on every such folder (and, for a folder whose only saved
  state is its `latest/` child, on that child, saying so), the *Saved versions* card lists them all by their exact
  path (own · instructor and reference · other labs · elsewhere in the repository), *Full history…* lists them, and
  View, Compare, Download and Apply read exactly the folder named. Folders that arrive with *Update from the
  repository* count as soon as they are there. The manifest and its files decide what can be applied: the review still
  lists every device with its reason when it cannot be.
- **The review is what gets applied.** The review of a folder source names the repository commit it read, and
  confirming applies exactly that commit's files: a repository update between the review and the confirmation cannot
  swap in different bytes, and a commit that left the branch history is refused before any device is contacted.
- Guides: [Save lab progress to Git](GIT-PROGRESS.md) (repository layout, save location rules, apply) and
  [Lab operations](LAB-OPERATIONS.md). The VM helpers changed (`read-version`, `history`, `register-prefix`,
  `connect`): the launcher refreshes them; a mixed tree is refused as before.

## Changes in 1.30.30

**Replace running configuration: acceptance closed on all four kinds.** Fourth and closing release of the
multi-platform restore stream ([multi-platform-restore](multi-platform-restore/README.md)). No change to the
manager's behaviour: this release carries the last acceptance evidence and two fixes to the acceptance tools.

- **A restored configuration survives a normal restart of the network operating system** on cEOS 4.35.0F,
  cJunosEvolved 26.2R1.7-EVO, vJunos-switch 23.2R1.14 and XRv9k 24.3.1: after a confirmed restore from the page, each
  NOS was restarted the way an operator would and came back with every statement of the restored configuration, nothing
  lost and nothing new. On cEOS that is the effect of the save the manager performs after the confirmation.
- The evidence matrix has no open row for the four images; what was not run or could not be produced (a commit-time-only
  rejection on IOS XR, IOS XR banners, a live tamper test of the integrity checks) is named in it.
- `tools/failure_harness.py` waits until a restart re-check has settled a job (an "interrupted" job is not the end any
  more); `tools/square_check.py` says that it opens a session on every node it is given.

## Changes in 1.30.29

**Replace running configuration works on Cisco IOS XR (XRv9k), and with it on all four supported kinds.** Third
release of the multi-platform restore stream ([multi-platform-restore](multi-platform-restore/README.md)).

- **Cisco IOS XR.** A saved IOS XR running-config can be applied to a running node: `configure exclusive`, the saved
  configuration entered into the empty target configuration, the device's own preview (`show configuration changes
  diff`), then one native command that replaces the whole configuration and arms the timed recovery, `commit replace
  confirmed minutes <N>`. A committed IOS XR configuration is persistent by itself. IOS XR backups carry an `.xrcfg`
  artifact since this release (the backup's own text, one capture); earlier saves list the device with "made before
  this kind of device could be restored".
- **Only the session that armed the change can confirm it on IOS XR** (shown three ways on 24.3.1). The driver
  therefore keeps that session, the manager proves with a fresh connection that management still works, and only then
  the confirmation is sent on the kept session; the change is never confirmed before that proof. When the manager
  gives up, leaving the kept session makes IOS XR undo the change at once; after a manager restart the kept session is
  gone, the device undoes the change at its timer and the read-back reports it. The manager's own session never lingers
  on the device (it used to block the next restore for minutes).
- **Refusals on IOS XR:** somebody's open configuration session or exclusive lock ("A configuration session is open on
  this node"), somebody's pending change, and a saved configuration that contains a `banner` (not supported yet) are
  refused before anything is touched.
- **For every platform:** when the safety backup of a device fails, the restore outcome says why in fixed words
  ("the device rejected the login", "the device did not answer"); a session lost inside the transaction is reported
  with what that means; a manager that is shut down inside the undo window leaves the device marked as being changed,
  so the next start reads it back, instead of recording "unknown".
- The guides describe all four kinds; the acceptance record has the four-column evidence matrix, the mixed
  four-platform runs and the failure harness (`tools/failure_harness.py`, `tools/mixed_failure.py`).

## Changes in 1.30.28

**Replace running configuration: cJunosEvolved accepted through the product, and the evidence hardened after an
independent audit.** Second release of the multi-platform restore stream
([multi-platform-restore](multi-platform-restore/README.md)). Cisco IOS XR is not restorable in this release.

- **Integrity for every source.** A Git version or folder was already checked file by file against its manifest. A
  backup had no digest at all: the runner now records a SHA-256 when it stores a capture and its restore artifact, and a
  stored file that no longer matches is refused before it is saved to Git or applied to a device. Backups taken before
  this release carry no digest and are used as they are.
- **The review looks at each device over one SSH connection** (pending change, other blockers, current configuration)
  instead of three, and a refused connection is tried three times before anything has been sent. Rejected credentials
  are never retried and are reported as such ("The device rejected the login"), in the review and at application time;
  they used to read "did not answer".
- **Clearer results.** A device that was not changed shows the reason beside its badge, not only under Details. A device
  that undid the change is counted apart from devices that were never changed ("1 device undid the change; its previous
  configuration is back"). The message of a job interrupted by a manager restart says what the manager is doing about
  it, and the restart re-check reports `verified` only after a comparison.
- **cJunosEvolved through the product:** management cut after arming (the manager waits for the device's own rollback,
  which came up to 35 s late, and reports it as read back), a manager restart during the undo window (the pending change
  is found under the job's own token, confirmed and verified), root-authentication synthesised from a backup that has
  none, A onto A, a restore from a post-restore backup. The same for vJunos-switch except the restart case. On this image
  a commit that REMOVES `root-authentication` is refused, bare `commit` included; a node that never had the statement
  only warns (the evidence file says which observation is which).
- **Acceptance tooling** under `docs/multi-platform-restore/tools/`: `readback.py` (the devices' own answer as booleans
  and counts, with a whole-configuration comparison that shares no code with the application), build identity in every
  evidence file, a browser tool without vacuous checks that reaches both source types of the page, `interruption.py`
  and `persistence_check.py` (written, the latter not yet run). On cEOS `show version` Uptime is not a boot identity
  (it was seen restarting from zero while the container and every agent kept running); the tools use the age of PID 1.

## Changes in 1.30.27

**Replace running configuration works on Arista cEOS, no longer guesses at a rollback, and never confirms
or destroys somebody else's work.** First release of the multi-platform restore stream; the platforms,
semantics, live facts and the acceptance record are in
[multi-platform-restore](multi-platform-restore/README.md). Cisco IOS XR is not restorable yet.

- **Arista cEOS.** A saved EOS running-config can now be applied to a running node. The driver empties a
  configuration session (`rollback clean-config`), loads the saved configuration into it
  (`copy terminal: session-config`), shows the device's own session diff, activates with `commit timer`, and
  after the manager reconnects confirms with `configure session <name> commit` and saves the startup
  configuration (EOS does not save on commit; a node that could not save is reported as such). A session
  starts as a copy of the running configuration, so without the emptying step a load would only merge and
  leave later additions behind. cEOS 4.35.0F needs no change to its base configuration. EOS backups carry a
  restore artifact (`.eoscfg`) since this release; it is the backup's own text, captured once.
- **One contract for every platform.** `app/restore.py` knows no NOS command. A node's driver comes from
  `app/restore_drivers.py`; the shared SSH shell is `app/restore_shell.py`; comparison lives in
  `app/restore_compare.py` and keeps hierarchy for indented configurations, so a leftover statement, a
  statement under another parent and a reordered ACL are all differences. Nothing is normalised away except
  the exclusions listed in the README.
- **No assumed rollback.** After activating, the manager keeps trying to reconnect and confirm for the whole
  undo window (it used to try once). If it cannot confirm, it reads the node back: *undone* is reported only
  when the configuration from before the restore is active again (`rolled_back`), otherwise the node is
  reported as unknown (`uncertain`). A session that dies in the middle of the transaction is read back too
  and is never reported as "not changed" on a guess. The same read-back runs after a manager restart for
  every node that was mid-change, and the job then says what it found; nothing is re-applied.
  `rollback_expected` remains only as the label of jobs stored by earlier releases.
- **Only the manager's own change is confirmed.** Every change is armed under the job's token (a Junos
  commit comment, the EOS session name). A pending change without it is somebody else's: the review refuses
  such a node, the driver refuses to start on it, and nothing is confirmed because "something is pending".
- **Junos: other people's work is preserved.** The confirmation is now `commit check`, which cancels the
  pending rollback without committing the shared candidate; the plain `commit` used before activated another
  session's uncommitted edit (shown live on cJunosEvolved). Before taking the exclusive lock the driver looks
  at the shared candidate and refuses when somebody's uncommitted changes are there; the earlier fallback to
  a shared session plus `rollback 0` discarded them.
- **Saved versions that cannot be applied say why.** A node saved before its platform was restorable, an
  artifact in another format, and an empty or truncated candidate are listed in the review with the reason
  and are refused before any device is touched; they used to be left out without a word. The backup text is
  never relabelled as a candidate.
- **Secrets.** Review and mismatch samples are cut at the first secret keyword. The previous masking kept the
  hash on EOS-style lines (`secret sha512 <hash>`, `password 7 <hash>`, `key-string 7 <hash>`).
- The page shows the device type beside each device, the new outcomes, and the EOS "not saved" note; the
  folder browser recognises `.eoscfg` artifacts. Wording that claimed a rollback had happened is gone.

## Changes in 1.30.26

**Maintenance audit follow-up 4: a save with nothing new no longer asks for a review of nothing.** Manager
only (`app/git_progress.py`); the helpers changed by their lockstep version alone.

- The VM helper has always answered `unchanged` when a save finds no changed file, but the manager ignored
  it: the save ended *Waiting for your review*, the page opened **Review before uploading** with an empty
  list, and that waiting save then blocked **Change folder…**, **Use a different repository…** and
  **Connect by URL…** until the student uploaded or set aside nothing.
- Now such a save ends *Saved to Git — nothing had changed since your last save*, but only when the manager
  already knows that the very commit it reuses was uploaded through the same save location (another save of
  it is recorded as uploaded, with the same binding). It is then not a pending save, and asking to upload
  it again simply returns it.
- Everything else keeps the previous path on purpose. When the commit was never uploaded, or was uploaded
  under different save settings, the save still waits for the review and still blocks a folder change,
  because there really is something on the VM that is not online. The review before an upload stays
  mandatory: no route uploads without it, and none was added.
- [Save progress](GIT-PROGRESS.md) describes both cases.

## Changes in 1.30.25

**Maintenance audit follow-up 3: unused code removed from the Git helper and the restore service.** No
execution path changes. `app/host_git.py` loses `allowed_version()`, which nothing called since
`allowed_repo_version()` took over when a saved state became applicable from any folder; what
`read-version`, `compare` and `history` may reach is unchanged. `app/restore.py` loses four unused imports,
the `DONE` tuple, a set that `map_targets` built and never read, and `_candidates()` (the job's candidates
are read directly, and `public_job` still leaves them out). In `app/restore_junos.py` the unused
`COMMIT_ERROR` pattern and `pending_rollback_shell()` stay, now with a note: a commit is judged by the
presence of the success line, and the probe is what an interrupted restore would need, which is a feature
decision. **Refresh the Git helper on an installed VM as with any release** (`start-manager.sh`, or
`setup-git.sh --refresh`).

## Changes in 1.30.24

**Maintenance audit follow-up 2: the last trace of Home's Continue block.** Frontend only, no visible change.
`shell.js` no longer has `lastOpened()` and no longer writes `clab.lastLab` each time a lab is opened: the
block that read it left Home when *Recent labs* arrived. `rememberOpened()` still records when each lab was
opened, which the lab cards show. The test that pinned the old pair now claims what is still true (the time
is recorded per lab, storage that throws is survived) and that no reader is left; the Home test harness lost
its unused fake. A `clab.lastLab` value left in a browser is never read again.

## Changes in 1.30.23

**Maintenance audit follow-up 1: the course scaffold tool works with the mandatory upload review, and
prepared-image installations get the Grafana idle time and a way to set up both stacks.** No change to the
manager or the helpers beyond the lockstep version.

- `deploy/scaffold-lab.py snapshot` could not finish since an upload needs a review: the save ended *Waiting
  for your review*, the tool's rebind to `work` was refused (a waiting save blocks a folder change) and the
  lab was left saving into `reference/<state>`. It now lists the files it saved and asks before it uploads,
  stating the review through the same retry route the page uses; `--yes` answers for a script, and without
  a terminal the tool refuses before it changes anything. Answering no sets the save aside (*Keep snapshot
  only*), so the state stays on the lab VM and the lab is still pointed back at `work`. When an upload
  fails it says plainly that the lab still saves to the reference folder and how to recover. Its test
  manager now behaves like the real one (review, refusal of the folder change, refusal of an unreviewed
  upload); the old tool fails those tests.
- `deploy/compose.image.yml` passes `TELEMETRY_GRAFANA_IDLE_MINUTES` like the source-build file (default 15,
  so nothing changes for an installation that never set it). A test keeps the two files' settings equal.
- The Wiki guide's prepared-image part explains how to set up browser Wireshark and the dashboards there:
  both setup scripts with `--no-recreate`, their settings copied into `deploy/image.env`, the manager
  recreated with the image Compose file, and `UI_PORT` in `clab-backup-ui/.env` when it is not 8081.
  `deploy/image.env` is now git-ignored, because it then holds the capture session token.

## Changes in 1.30.22

**Maintenance audit, chunk 5: what the independent verification found, the telemetry settings table, and
task routes for agents.** Documentation and agent configuration only.

- An independent check of 36 statements that the two documentation chunks had added or changed found 34
  correct. The two others are fixed: **Back up all configurations** does not always open a review (it starts
  at once when every device is ready, and lists the devices it will skip and asks for confirmation only
  otherwise; the guides had said "reviews" since before this audit), and the naming guide now says exactly
  what `scaffold-lab.py snapshot` leaves behind and how to recover (the defect itself stays in the audit
  record for a decision).
- [Guided VM installation](INSTALL.md) names the four telemetry keys of `clab-backup-ui/.env` with their
  defaults and rules (`TELEMETRY_GRAFANA_PORT`, `TELEMETRY_GRAFANA_BIND`, `TELEMETRY_PROMETHEUS_PORT`,
  `TELEMETRY_GRAFANA_IDLE_MINUTES`); no guide had named the first three. The capture stack's ports are fixed
  by its setup, and the guide says so.
- `.claude/agents/` has three small project agents whose model is part of their definition
  (`docs-auditor`, `mechanical-editor`, `risk-reviewer`), and `CLAUDE.md` "Delegating work" says when to use
  each, who owns shared files, and that a user or managed setting can force every subagent onto one model.
- The [audit record](maintenance-audit/AUDIT.md) is final for this pass: every audited document or group has
  a disposition, each important workflow is mapped to its code, guide and evidence, and the remaining debt
  lists what needs a decision.

## Changes in 1.30.21

**Maintenance audit, chunk 4: proven dead code removed, stale wording in the setup scripts, and eight test
files that CI never ran.** No behaviour change; the helpers changed by their lockstep version alone.

- `style.css` loses 70 rules and 20 entries of selector lists (about 200 lines) whose classes nothing
  produces any more: the sidebar shell and the landing panel and tab strip of the UI before the redesign,
  orphan classes (`card-title`, `control-row`, `deployment-bar`, `page-heading`, `op-coordinates`,
  `dialog-body`, …), `button.git-saved-job` (the element is always a `<details>`) and the unused `--focus`
  alias. Every class was searched as a whole token in the static scripts and pages, the Python modules, the
  editor bundle, the vendor files, the tests and the Playwright tools; selectors that only mention such a
  class inside `:not()`, `:where()` or `:is()` were left alone.
- `operations.js` and `management.js` no longer attach handlers to `#deploy-empty` and `#home-import`,
  which no markup creates. Seven unused imports and one unused exception name are gone from
  `discovery.py`, `inventory.py`, `main.py`, `telemetry_map.py`, `telemetry_metrics.py`,
  `deploy/capture/smoke.py` and `deploy/setup_telemetry.py`.
- The Git setup's closing lines (`git-onboard.py`, `setup-git.sh`) sent the reader to *More › Git
  repository* and said a save pushes automatically; they now say *Progress › Save location* and name the
  review. The health check, the telemetry setup and the VM connection help page use the current labels
  (*Open lab map ↗* / *Open network dashboard ↗*, *Check the VM automatically for running labs*).
- CI (`release-check.yml`) has a new step for `test_app.py`, `test_downloads.py`, `test_topology.py`,
  `test_diagram_editor.py`, `test_import_confirmation.py`, `test_remove_lab.py`, `test_manager_reset.py` and
  `test_vm_password.py`: 69 tests on the backup pipeline, download names, import confirmation, removal and
  reset that only ever ran locally. `test_eos_ssh.py` stays opt-in.

Left alone on purpose and listed in the [audit record](maintenance-audit/AUDIT.md): unused names in
`host_git.py`, `restore.py` and `restore_junos.py` (sensitive modules, a risk review first) and
`shell.js` `lastOpened()` (dead in production but pinned by a test).

## Changes in 1.30.20

**Maintenance audit, chunk 3: the student workflow guides against the UI code and the routes.**
Documentation and three screenshots only.

- [Save progress](GIT-PROGRESS.md): the introduction and both flowcharts pass through **Review before
  uploading**; a *Folder move* uploads on its own confirmation and has no separate review; **New folder…**
  without the tick only plans a folder for a connected lab; the recovery table uses the buttons that exist
  (*Retry save, then review*, *Retry save on this VM only*) instead of two that never did.
- [Lab operations](LAB-OPERATIONS.md), [Lab builder](LAB-BUILDER.md) and
  [Node features](../clab-backup-ui/NODE-FEATURES.md): *Edit map* has Undo / Redo, *Device look…* and
  *Link labels…*; line arrows, rounded text backgrounds and nested group levels are kept in the map document
  but not drawn on the Topology tab; destroy cleans up by default where the helper allows it; the
  **Advanced options** group; importing a lab found on the VM needs the confirmation. Node features drops
  the labels from before the redesign and gains **Backup download names**, the file and ZIP naming contract
  that no living guide described.
- [Naming](NAMING.md) no longer says an upload is automatic, and says that `deploy/scaffold-lab.py snapshot`
  stops at the review (recorded as a defect in the audit record, not fixed here).
- README and [Tour](TOUR.md): workstation upload, the lab builder, the upload review and *Diagnostics*;
  `00-home.png`, `20-devices.png` and `30-progress.png` showed pages that no longer exist and are replaced
  by captures of the current UI from the fixture manager (scripted VM answers, example data, as the tour
  says).

Two behaviour defects were found by reading and are in the audit record for a decision: the scaffold tool's
`snapshot`, and a save with nothing new opening a review with an empty diff.

## Changes in 1.30.19

**Maintenance audit, chunk 2: the installation and operations guides against the scripts and the UI.**
Documentation only. Eleven guides were compared with `deploy/` and the manager; the installer menu, phases,
flags, upgrade and recovery procedures, ports, `.env` keys, limits and health-check outcomes were correct
and are unchanged. What was wrong:

- **A save does not upload by itself.** Six guides still said *Save progress* "commits and pushes
  automatically" and told the reader to wait for *Saved to Git*; since the upload review became mandatory
  that wait never ends. They now include **Review before uploading › Upload these changes**, and the retry
  buttons carry their real names (*Retry save, then review*, *Review and upload…*, *Upload now*).
- The fresh VM guide and the Wiki guide said the Junos switch kinds get no default login and no live
  restore; both have containerlab's documented default login, and vJunos-switch supports *Apply to running
  lab* (vQFX does not).
- The manual setup guide said to set `UI_BIND` / `UI_PORT` in the shell; they belong in
  `clab-backup-ui/.env` (`sudo` drops shell variables and the Grafana setup reads the port from that file).
- Labels from before the redesign are replaced by the ones the pages show: the VM connection fields,
  *Labs found on the VM…*, *Add lab*, *Sync topology from VM*, *Update topology file…*, *Link to a running
  lab…*, *Lab folders on the VM*, *Restart devices*, **Lab actions ▾ › Advanced options**, the Tools ›
  Telemetry links, the capture dialog names, *Remove from this manager…*.
- The quick install lists the Git wizard's subfolder prompt; inline commands that only worked from the
  source folder are absolute; the Wiki guide says engineer access needs lab operations first.

Found and recorded, not changed (see the audit record's remaining debt): `deploy/compose.image.yml` does not
pass the Grafana idle time, and the stack setup scripts on an image-only installation.

## Changes in 1.30.18

**Maintenance audit, chunk 1: agent guidance agrees with the application again.** Documentation only; the
manager, the helpers and the editor bundle changed by their lockstep version alone. The record is
[docs/maintenance-audit/AUDIT.md](maintenance-audit/AUDIT.md).

- `CLAUDE.md` no longer says the student UI redesign is unreleased or that the checkout has no Docker (the
  redesign, the lab builder and UI review 001 are released and merged; an agent now discovers its
  environment). It stops importing the whole handoff history on every session (the default-loaded
  instructions go from 141,185 to 28,817 bytes) and instead carries the invariants that must not
  regress and a routing table that names, for each area, the handoff sections, the guide and the tests to
  read first. `agent instructions.md` and its symlink are unchanged and still checked by the release check.
  It also separates the three frontend layers: the plain-script manager UI, the editor built ahead of time
  with Node 24 from `clab-backup-ui/lab-builder/`, and a VM that needs neither Node nor npm.
- An independent review of that migration found five obligations or statements to fix before it could be
  used (the section-listing command missed the `##` sections, the no-login same-origin model and the
  logging secrecy contract were not stated, *Sync topology from VM* was described wrongly, a folder was named before it
  existed) and seven routing gaps; all are applied.
- `docs/ARCHITECTURE.md`: the module map's static-files row described the UI before the redesign; it now
  lists the current scripts and standalone pages, and `downloads.py` and `grafana_control.py` have rows.
- `docs/ui-review-001/PICKUP.md` and `docs/lab-builder/PICKUP.md` say, checked against GitHub, that their
  work is merged; every open point and qualification is kept.
- `docs/archive/DOCKER-HUB-SETUP.md`: six relative links broken by its move into the archive are repaired.
  `docs/maintenance-audit/tools/check_links.py` checks every tracked Markdown link and anchor, and the
  maintenance rules name it. The documentation index lists the naming guide, which it had missed, and the
  audit folder.

## Changes in 1.30.17

**UI review 001, step 16: link label distance in Edit map, and every map tool driven in a browser (UI-003,
row 10 and the per-row pass).** Frontend only (the editor bundle is unchanged).

- **Link labels…** in the map editor's bar: pick a link (the one selected on the canvas is preselected),
  give it its own label distance from 0 to 60, or take that away again. It changes one entry of the
  document's link annotations, found by the link's endpoints as the editor finds it; an entry that
  carries anything else is kept, one that would be empty is removed. It is one Undo step, **Save map**
  keeps it and the lab's Topology tab draws it. The label mode for all links stays the tag icon in the
  editor's toolbar.
- The editor's link menu no longer shows *capture* and *Link Impairments* in Edit map: they belong to a
  running lab and did nothing here. *Packet capture…* on the lab page is unchanged.
- With this release every row of the capability matrix was driven in a real browser, saved, reopened
  and compared with the stored document: shapes (rectangle, circle, line) and resizing by handle, a group
  and a device dragged into it, copy / paste / keyboard delete of annotations, a generated layout and
  Undo taking all of it back, the link label mode, a grid setting, the SVG export, the device look and
  the link label distance. What the manager's Topology tab does not draw (line arrows, rounded text
  backgrounds, nested group levels) is stored and shown by the editor; that difference is documented in
  [docs/ui-review-001/MAP-PARITY.md](ui-review-001/MAP-PARITY.md).

## Changes in 1.30.16

**UI review 001, step 15: the device look is editable in Edit map (UI-003, row 9).** Frontend only (the
editor bundle is unchanged). UI-003 still has its per-row browser pass open.

- **Device look…** in the map editor's bar opens on the device selected on the canvas (or any device of
  the map) and sets how it is drawn: icon (the editor's 14 types, or the default by kind), icon colour,
  icon corner radius, label position, label text direction and label background (a colour, transparent
  or the default). *Apply to this device* changes exactly those six keys of that device's entry in the
  map document; *default* removes a key instead of storing an empty value. The device itself, its kind,
  its links and everything else in the document are untouched, and the editor's own topology form is
  still not reachable.
- The look is an ordinary edit: the canvas redraws at once, it is one Undo step, **Save map** keeps it,
  and the lab's Topology tab draws the icon, colours and label position. Values the editor does not
  accept are refused in words.
- The map editor's bar wraps onto a second line instead of clipping **Save map** and the lab's name.

## Changes in 1.30.15

**UI review 001, step 14: Undo and Redo in Edit map (UI-003, row 8).** Frontend and the editor adapter.
UI-003 is not yet complete (the device look and the per-row browser pass are open).

- **Undo / Redo** buttons in the map editor's bar, and Ctrl/Cmd+Z, Ctrl/Cmd+Shift+Z and Ctrl/Cmd+Y (not
  while typing in a field, where the field's own undo applies). The editor has no undo in the mode Edit
  map uses, so the history is the page's own: each settled state of the map document is a step (up to
  60; states that follow each other within 0.7 s are one step, so typing a text or a drag that settles
  twice is a single undo), a new edit drops what could have been redone, and going back to the map as
  it was opened leaves nothing to save.
- A step is put into the running editor as one annotation-only engine command
  (`setAnnotationsContent`) followed by the snapshot message the editor already understands for a file
  changed outside it, so the canvas redraws in place and zoom, pan and the next edit keep working. The
  engine's own undo, which restores the topology file as well, is never used.

## Changes in 1.30.14

**UI review 001, step 13: Edit map is the lab builder's editor in a map mode (UI-003, steps C and D).**
Frontend, the editor adapter and one public flag in the manager; the VM helpers are unchanged apart from
the lockstep version. UI-003 is **not yet complete**: the open rows are listed at the end and in
[docs/ui-review-001/MAP-PARITY.md](ui-review-001/MAP-PARITY.md).

- **Edit map opens the same editor as the lab builder**, on the lab's own map
  (`/static/map-editor.html#lab=<id>`), for every lab whose topology text the manager has (the lab view
  carries `map_editor`). It brings the builder's map tools: dragging devices on the 20 px grid,
  generated layouts, free text with the inline toolbar (bold, italic, underline, alignment, size) and
  the text panel, rectangles, circles and lines with resize and rotate handles, arrows, corner radius
  and rotation, groups with membership by dragging devices in and nesting, copy / paste / duplicate /
  delete of annotations, per-link label offsets, the link label mode, grid style and colours, zoom,
  pan and fit, and the SVG export. A lab without a topology text (imported from an inventory) keeps
  the simple dialog, which is unchanged.
- **The drawing only.** The editor runs in its *view* mode, where adding, editing and deleting devices and
  links are absent. Because that mode is enforced in the editor's UI only, the adapter refuses every
  engine command that is not annotation-only, restores the topology text if it ever differed, and the
  page refuses a changed topology too; the save request can carry nothing but the annotations and the
  revision they were opened with. The page loads neither `operations.js` nor the builder's draft code:
  it has no way to deploy, publish, revise or reach the VM. Runtime actions of the editor's device menu
  (start, stop, SSH …), the traffic-rate widget, the inert device palette and the deploy controls are
  hidden; a test fails when an editor upgrade renames one of them.
- **Save, cancel, conflict.** *Saved in the manager* / *Unsaved changes* in the bar; **Save map** stores the
  document and the manager derives its drawing, so the lab's Topology tab, the draw.io export and the
  annotations download follow. **Back to the lab** asks (*Keep editing*, *Discard changes*, *Save map and
  leave*) only when something is unsaved, and the browser warns on closing the tab. A map changed
  elsewhere since it was opened is refused, nothing is reported as saved, and the student can download
  their version.
- **Kept:** *Download map file* (now the full document, with everything the manager does not draw),
  *Export to draw.io* (from the saved map) and *Import map file…* (checked in words, replaces the map,
  unknown keys included) are in the editor's bar; *Import map…* on the lab page is unchanged.
- **Open rows of UI-003:** undo / redo is absent in the editor's view mode (row 8); the device look (icon,
  colours, label position) is still not editable, because upstream edits it through a topology command
  (row 9); the manager's Topology view stores but does not draw rotation, line arrows, rounded text
  backgrounds and nested-group levels. Observed upstream behaviour: after *Add Text* from the context
  menu the inline box has to be clicked before typing.

## Changes in 1.30.13

**UI review 001, step 12: the manager keeps the whole map document (UI-003, step B).** Manager only; no
page uses it yet, and *Edit map* is unchanged. UI-003 is not complete.

- **The full annotations document per lab.** Until now the manager kept only its own drawing of a map
  and dropped what it does not draw (group membership and nesting, line arrows, geo coordinates,
  traffic-rate and alias entries, unknown keys). It now also keeps the annotations text a drawing was
  derived from: for *Import map…*, a lab registered with its files, and the import and *Sync topology
  from VM* of a lab's files. The text is private like the topology text and never part of `/api/state`.
- **`GET` and `PUT /api/labs/{id}/map-document`**, for the map editor that follows. Reading returns the
  lab's topology text, its annotations document and a revision; a lab that has only a drawing gets a
  document written from it. Saving takes the annotations text and the revision it was opened with,
  refuses a stale revision, a lab with a running operation, a text above 1 MiB and anything
  `parse_drawing` cannot read, then stores the text **untouched** and derives the drawing again, so the
  Topology view, the draw.io export and the annotations download follow. The request cannot carry a
  topology; the topology text is only read; no VM helper is called.
- The older *Edit map* dialog keeps saving through `PUT …/layout`. A stored document is tied to the
  drawing it produced, so after such a save (or a sync) the editor is given a document written from the
  current drawing, never a stale one.

## Changes in 1.30.12

**UI review 001, step 11: the map-editing capability matrix (UI-003, step A).** Documentation only; no
behaviour changed. UI-003 (Edit map gets the visual builder's map-editing capabilities) is **not**
complete: this release records what parity means and how it will be reached.

- [docs/ui-review-001/MAP-PARITY.md](ui-review-001/MAP-PARITY.md) compares, from the code, the
  map-editing tools of the installed editor (`@containerlab/clab-ui` 0.3.2) with today's *Edit map*,
  row by row with a status, and lists what stays out because it is topology editing.
- Finding: the manager keeps only its own normalised drawing, not the annotations document, and drops
  what it does not draw (group membership and nesting, line arrows, geo coordinates, unknown keys).
  Parity and "never drop unsupported data" therefore need the full document to be stored.
- Decision: reuse the embedded editor in a *map mode* (its `view` mode, plus an adapter that refuses
  every command that is not annotation-only and a save that refuses a changed topology text), over a
  full annotations document kept per lab from which the drawing is derived. The old dialog stays until
  that path is validated; import, the annotations download and the draw.io export stay.

## Changes in 1.30.11

**UI review 001, step 10: Recent labs, ordered by real deployments (UI-002, part 2).** Manager and
frontend; the VM helpers are unchanged apart from the lockstep version. This completes UI-002.

- **Recent labs.** Below *Deploy* and *Build* the lab list has two tabs. **Recent labs** (the first
  and default tab) lists every lab by its most recent deployment, newest first. **All labs** keeps the
  order Home always had: favourites first, then by name. A line under the tabs says which order is
  shown. The separate *Continue where you left off* block is gone, so nothing outranks the two starting
  choices; every card still says when the lab was last opened.
- **Real deployment times only.** The manager records `last_deployed` on a lab when a *deploy* or
  *redeploy* it ran succeeds (a failed one, a start, a stop or a save is not a deployment), and the
  lab view in `/api/state` carries it. For a lab deployed before this release the newest succeeded
  deployment of the kept operation history is used. A lab the manager never deployed (imported from a
  running VM, deployed from a terminal, or with its history gone) has no time: its card reads *No
  deployment recorded by this manager* and it comes after all dated labs, by name, so it is never
  presented as recently deployed. Nothing is estimated from discovery, saves or visits.
- **The order and the tab stay put.** Opening a lab, saving, a favourite and background polling do not
  reorder *Recent labs*; the chosen tab is kept for the browser session across polls, a lab visit and
  a reload, and the arrow keys move between the tabs. Unchanged cards are not redrawn.
- Lab names on the cards no longer break in the middle of a word: the card's tool buttons had been
  taking half of the card's width.

## Changes in 1.30.10

**UI review 001, step 9: Home leads with Deploy and Build (UI-002, part 1).** Frontend only. Part 2
(the lab list under a *Recent labs* tab, ordered by the most recent deployment) follows.

- **Two starting choices.** Every Home, with or without labs, begins with two equal cards. **Deploy**:
  *Choose a file on the lab VM…* (the topology browser) and *Upload a file from this computer…*.
  **Build**: *Open the lab builder*, a direct link to the visual lab builder, not another deployment
  dialog. The wording says where the files are: on the lab VM, or on this computer and copied to the VM
  when the student confirms. The old secondary *Deploy a new lab* button in the page header and the
  second set of the same buttons on the empty page are gone; **Manager ▾ › Deploy a new lab…** stays.
- **Upload without a bypass.** The browser reads the chosen file; a wrong file type, an empty file, one
  above 1 MiB, a binary file or a topology the manager cannot read is refused in plain words (with the
  manager's own reason for the last). A good file opens the existing topology editor as *Uploaded lab
  file* with its text and its destination inside a trusted lab folder
  (`<folder>/<lab name>.clab.yaml`), and the only way on is the reviewed **Create file on the VM…**
  operation. Nothing can be deployed before that.
- **After a created file: Deploy or add this lab….** A finished `create` now offers the same next step as
  a builder save (*Saved as … It is not running yet.*), for an uploaded and for a typed topology, so the
  student no longer has to find the new file in the browser again. The helper is unchanged; the page
  uses the job's own path.
- While the lab VM is not connected both Deploy buttons are off and a visible sentence says why and
  that building works meanwhile. The topology browser says that its files are on the lab VM and links
  to the upload.

## Changes in 1.30.9

**UI review 001, step 8: the Devices tab lines up (UI-006).** Stylesheet only; no markup, script,
status wording or readiness rule changed.

- **Flush with its heading.** The device list kept the browser's default list indent, so every row
  started 40 px to the right of the *Devices* heading while its right edge met the search controls. The
  list now has no indent, on the Devices tab and on the Topology tab's device rail.
- **One grid for the whole list.** Each row used to be a grid of its own; the rows are now subgrids of
  one list grid, so the device name and platform, the state with its reason, *Open CLI* and *Details*
  start at the same position in every row whatever a row contains. Every cell begins with a line as high
  as the buttons: name, state pill and *Open CLI* share one line in every row, and a reason or a long
  name only makes its own row taller. Long names wrap inside their column, the platform badge follows
  them, a reason is kept to a readable width, and the action buttons never wrap apart on a wide window.
- **Heading, search and Technical view** sit on one line with controls of one height, aligned with
  the bottom of the heading text. Below 760 px the rows become a single column and the search field
  fills the width.

## Changes in 1.30.8

**UI review 001, step 7: the folder tree opens and closes by your own clicks (UI-008, part 2).**
Frontend only. This completes UI-008.

- **Every folder with children expands and collapses.** The tree used to derive its open branches from
  the selected folder alone: the ancestors of the selection were forced open, no branch could be
  closed, and no other branch stayed open. Each folder with children now has a small arrow of its own
  that opens and closes it without selecting it (pointer, Enter or Space; on a focused folder the right
  and left arrow keys do the same). The first display of a repository opens the way down to the folder
  the lab saves to; after that only the student's clicks change it. Selecting a folder opens its
  ancestors so it can be seen, and never closes anything.
- **The save destination and the browsed folder look different.** The folder the lab saves to has an
  accent bar, bold text and the *This lab* tag wherever the student is browsing; the browsed folder is
  the filled row. A closed branch that contains the destination reads *This lab is inside*. While
  another folder is looked at the panel says *This lab saves to … Looking at other folders does not
  change that.*
- **State survives refreshes.** Open branches, the selection, the tree's scroll position and the
  keyboard focus are kept across background polling, the re-render after *Save settings*, a tab change
  and a reload of the folder list, for as long as the folders exist; another repository starts from its
  own default. A folder the page itself selects (one just created, the lab's new destination) is
  revealed once.
- Long folder names stay on one line with an ellipsis and the full name as a tooltip, and no longer
  break beside the *This lab* tag.

## Changes in 1.30.7

**UI review 001, step 6: a folder made in the folder browser no longer disappears (UI-008, part 1).**
Manager and frontend; the VM helpers are unchanged apart from the lockstep version. Part 2 (expanding
and collapsing the tree, the destination highlight, state kept across refreshes) follows.

- **Root cause.** Git keeps no empty folders, so a new folder existed only as a *lab folder
  registration* on the VM, and the browser's tree is built from the committed files plus those
  registrations. Moving a lab (*Save this lab here*, or *New folder…* with *Save … here from now on*)
  retires the lab's previous registration. An empty folder the lab left, such as `working` under
  `JunOS-TEST-2` once the lab saved to a second new folder or went back to the parent, was therefore
  known to nothing and vanished. Creating a folder inside the lab's own folder *without* moving there
  was refused outright by the VM's rule that lab folders cannot overlap.
- **Fix.** The manager remembers, per checkout, the folders made or chosen through it
  (`git_folders` in its state; the tree route reports them as `planned`), and the folder browser draws
  them. They are told apart truthfully: *Empty folder · not in the repository until the first save*,
  and inside one: *Nothing is saved here yet. The folder is kept by the manager and appears in the
  repository with the first save into it.* No directory or commit is claimed. Such a folder can be
  chosen (*Save this lab here* registers it on the VM as before), survives refreshes, polling,
  reloads, a manager restart and the lab moving elsewhere.
- **New folder…** for a connected lab without *Save … here from now on* now only lists the folder
  (`POST …/folders` with `plan: true`): nothing is registered on the VM and the message says that the
  lab still saves where it did. A name that already exists (saved, a lab folder or planned) is refused
  in the dialog before anything is sent, and by the manager with 409; a refused or failed creation
  leaves no entry. An empty folder that nothing uses can be taken off the list (*Remove empty folder*,
  `DELETE …/folders`); nothing on the VM changes.
- Tooling: the fixture manager's scripted Git helper now retires registrations, refuses overlapping
  lab folders and answers `register-prefix` like `app/host_git.py`; it had hidden this defect.

## Changes in 1.30.6

**UI review 001, step 5: the review before an upload is mandatory (UI-007 C).** Manager and frontend;
the VM helpers are unchanged apart from the lockstep version. This is an intended change of behaviour:
until now a save uploaded by itself unless *Let me review changes before they are uploaded* was ticked.

- **No opt-out any more.** The checkbox is gone from *Save location › Save settings*. Every save a
  person starts (Save progress, a checkpoint, a baseline, the first save) is committed on the lab VM and
  then opens **Review before uploading**: what the save changed, a line saying that nothing is
  uploaded unless the student chooses it (and, when earlier saves are still waiting on the VM, that
  they go along), **Upload these changes** and **Not now — keep it on the VM**. Declining uploads
  nothing and says *Not uploaded*; the save stays in *Recent saves* as *Waiting for your review* and
  the status line reads *Saved on this VM*, never *Saved to Git*.
- **Enforced by the manager, not by the page.** A save request never pushes on its own, and
  `POST /api/git/jobs/{id}/retry` with `push` answers 409 *Review the changes of this save before
  uploading it* unless the request states the review (`reviewed: true`) or the job already records
  one (an upload that failed after its review is repeated with **Upload now**). A save location stored
  with the old opt-out and a page loaded before this release therefore cannot upload unreviewed
  changes. A retry of a save that has no commit yet saves on the VM first and then waits for the
  review. `review_before_push` is still accepted in requests and ignored; new save locations record it
  as on, and stored ones are left alone so saves that are waiting keep working.
- Every upload button follows: *Recent saves* and the save window offer **Review and upload…** for a
  save that was never reviewed, also for a *Save on this VM only* that is uploaded later.
- Not changed: *Save on this VM only* (no upload, no review), a folder move (it carries no
  configuration change and keeps its own confirmed upload), and automatic backups, which never
  created Git saves. Nothing scheduled or non-interactive shared the preference.

## Changes in 1.30.5

**UI review 001, step 4: Save location shows its folders and names its Git details (UI-007 A and B).**
Frontend only. The third part of UI-007 (the review before an upload becomes mandatory) is the next step.

- **Git repo details.** The disclosure on the *Save location* card that shows the verified push
  destination, the branch, the VM account and the checkout path is now called *Git repo details*. No
  other *Technical details* or *Details* disclosure was renamed.
- **Change folder… is open.** The folder browser is unfolded when Save location is entered, for a
  connected lab too, so the save-folder controls are visible at once. A student who folds it keeps it
  folded for that lab while the page stays open (across background polling, a tab change and the
  re-render after *Save settings*); *Browse the repository…* and picking another repository open it
  again, and only those still scroll to it. A new visit starts unfolded.

## Changes in 1.30.4

**UI review 001, step 3: the Save progress options explain themselves (UI-004).** Frontend only.

- **An explanation beside the options.** The small menu next to **Save progress** now has a pane that
  says, for the option under the pointer or the keyboard focus, what it does and where its result goes:
  *Create checkpoint…* (reads the devices now, keeps a named version under `checkpoints/<name>` of the
  lab's save folder, uploaded unless the upload is unticked), *Save on this VM only* (reads the devices
  now, saves the latest version in the VM's copy of the folder, uploads nothing; *Upload saved progress*
  publishes it later), *Saved versions & history* (a list to view, download, compare or apply; reads no
  device and saves nothing) and *Save location settings…* (opens Progress › Save location; nothing
  changes until a change is confirmed there). The texts name the lab's real folder and upload host and
  follow what the manager does, not what the labels suggest.
- The pane is part of the menu, so moving the pointer onto it to read does not close anything and it
  never lies over an option. It sits to the left of the options on a wide window, to their right when
  the save control has wrapped to the left edge, and under them when the window is too narrow for both
  (placed by measurement each time the menu opens). Each option also carries its explanation as its
  accessible description.
- Fixed on the way: on a narrow or zoomed window the menu used to hang off the left edge of the window.

## Changes in 1.30.3

**UI review 001, step 2: a shorter Lab actions menu (UI-005).** Frontend only.

- **Advanced options.** *Import map…*, *Edit map*, *Telemetry settings…* and *Operation history…* moved
  into an expandable **Advanced options** group at the bottom of **Lab actions ▾**. Nothing else moved:
  the lifecycle items, *Sync topology from VM*, *Packet capture…*, *Lab files…*, *All lab operations…*
  and the separated destructive actions are where they were, and every moved action is still available
  elsewhere too (*Edit map* on the map toolbar and the Tools tab, *Import map…* under the map's *More ▾*,
  *Telemetry settings…* on the Tools tab, *Operation history…* under Advanced and in the Manager menu).
- The group opens with a click, Enter, Space or the right arrow and closes with the left arrow; opening
  it never closes the menu; its items are skipped by the arrow keys while it is collapsed; it is
  collapsed again each time the menu opens. The moved items keep their disabled state and their reason
  line. On a small window the menu scrolls inside itself instead of running off the screen, and the
  last item is scrolled into view when the group opens.
- `shell.js` supports such a group in any button menu (`data-menu-group` on the item,
  `data-menu-panel` on the group).

## Changes in 1.30.2

**UI review 001, step 1: "Also running on the VM" leaves the main page (UI-001).** The first of a
series of small releases that implement the maintainer's UI review; the requirement checklist and the
pickup notes are in [docs/ui-review-001/](ui-review-001/CHECKLIST.md). Frontend only; the backend and
the VM helpers are unchanged apart from the lockstep version.

- **Home shows labs, not discovery.** The *Also running on the VM* section is gone from My labs. Its
  contents are one click away under **Manager ▾ › Labs found on the VM…**: the labs the VM reports that
  are not in My labs (click one to add it, with the same confirmation), the labs removed earlier with
  *Import again* and *Stop hiding* (button, right-click and keyboard menu as before) and *File check
  details*. The menu entry carries a count line (*1 not in My labs · 1 hidden*) so a waiting lab is
  still noticed; the dialog says why it is empty when it is (VM not connected, VM not answering, or
  every lab already added).
- Nothing about discovery changed: no lab is imported or unhidden by the move, and the messages that
  pointed at the old section (remove dialog, hidden-lab dialog, the toast after a removal) and the
  guides now name the menu entry. The first-run page without any lab keeps its short *Already running
  on the VM* list for now.

## Changes in 1.30.1

**Lab builder quality pass.** Fixes found by walking the student journeys in a real browser (fixture
and the live dev VM, including a multi-vendor lab built in the builder) and by an independent review;
the register is [docs/lab-builder/QA-FINDINGS.md](lab-builder/QA-FINDINGS.md). The VM helpers are
unchanged apart from the lockstep version (refresh them with `start-manager.sh` as for every release).

- **Nothing is shown as kept that is not.** When the browser cannot store a change (storage full or
  switched off, or a newer version from another tab), the status says so, editing pauses, *Download
  this version* carries the newest work, *Try to store it again* works once there is room, and *Save
  to the VM* stays off meanwhile. Before, the download the message asked for was the previous version.
  A browser that refuses storage altogether still builds, with a standing note that the draft lives
  in that tab only. Draft revisions are tokens, so a draft deleted and made again elsewhere cannot be
  overwritten by a tab that still holds the old one.
- **A save whose answer got lost is no dead end.** The job is followed when its dialog is closed, a
  failed poll is repeated, an *already saved* result marks the draft saved, and a draft that never
  heard how its save ended asks the VM the next time it opens. A refused save is a dialog that stays,
  says that nothing changed and that the draft is kept, and, when the VM holds another version than
  the draft started from, offers *Open the VM version* and *Review the differences…* (a reviewed
  revision of the version that is on the VM now). Before, the refusal was a six-second toast and a
  draft with a stale base could never be saved.
- **The lab name is what the topology says.** Renaming the lab in the editor's Lab settings renames a
  draft that is not on the VM yet everywhere on the page; a lab that is on the VM keeps its name and
  the page says so at once instead of at the save.
- **A topology the editor cannot parse is refused** (a syntax error, the same key twice), with the
  parser's reason and line. Before, it opened and every edit was accepted and silently dropped.
  Downloaded drafts are checked by the manager's parser when they are opened.
- **One draft per lab**, the VM's own hashes as the base of a revision (a file with a byte-order mark
  could be opened but never saved), and the editor opens with the images this site already uses.
- **Reasons on the page.** *Save to the VM* is never off without the reason under the bar (VM not
  connected, helper too old, unusable name) with *Check again*; a deployed lab is announced when its
  draft opens; an empty canvas says how to begin; an empty My labs page offers *Build a lab
  visually…*; a lab without devices is refused with "Add at least one device before saving".
- **Working controls.** The palette's *Import templates*; *Preview topology* and *Edit visually…* in
  the Topology file dialog when it is opened from the builder page.
- **Lab operations (all pages).** A failed deploy says in words which images the VM does not have and
  where to correct them; the folder browser closes when an operation is confirmed instead of covering
  the lab page and its result; the review's *Cancel* / confirm row stays in view in a small window or
  at browser zoom; a long list of differences that is cut short says so.
- The builder bar keeps *Save to the VM* in the window down to about 900 px (150 % zoom on a laptop).
- Tooling: the fixture manager reports a lab it deployed as running, so the workflow's "refused while
  deployed" check exercises the refusal (it passed on the review's own wording before); the redesign
  gate knows the *Edit visually…* button.

## Changes in 1.30.0

**Lab builder.** A new page draws a Containerlab lab in the browser and saves it to the VM
([docs/LAB-BUILDER.md](LAB-BUILDER.md)): *Deploy a new lab › Build a lab visually…*, and *Edit
visually…* on an existing topology file. The editor is SR Labs' containerlab topology editor
(`@containerlab/clab-ui`, Apache-2.0), embedded unmodified with the manager's own host: its editing
engine runs in the page, so the manager only reads and writes two documents. Upgrading an installed
VM needs the launcher (`start-manager.sh`), because saving uses two new actions of the operations
helper; with an older helper the page says that saving is unavailable and drafts still work.

- **Saving is a reviewed lab operation.** `publish` creates `<lab folder>/<lab>/<lab>.clab.yml` and
  its `.annotations.json` layout: the helper derives every path from the lab name, writes through
  flushed private temporaries relative to the open folder, links the layout first and the topology
  last, never replaces anything, treats identical content as already saved and completes a save
  that was interrupted. `revise` saves again over a lab that is **not deployed**, only from the
  versions that were opened, keeps recovery copies of both files and shows the difference in the
  review. The manager checks the topology with `parse_definition`, pins the lab name, refuses the
  name of a lab that is in My labs with another topology file, caps the request size and warns
  when its own map cannot read the layout. After a revision My labs takes the saved topology and map.
- **Drafts live in the browser**, never on the manager: stored before the editor's edit is
  acknowledged, protected against a second tab, downloadable and uploadable.
- **Deleting a topology file** now deletes the layout file beside it (both with recovery copies),
  and a lab folder that only holds those copies no longer blocks its name.
- **Page policy.** `static/lab-builder.html` joins the two xterm pages in the `style-src
  'unsafe-inline'` exception; `script-src 'self'` is unchanged, so the editor's YAML and JSON tabs
  (schema validation by code generation) are off, its code editor is left out of the bundle, and
  Geo layout, split view, Grafana export and the editor's own deploy menu are hidden. The content-
  hashed files under `/static/lab-builder/assets/` are the only responses that may be cached.
- **Assets are committed, never built on a VM.** `clab-backup-ui/lab-builder/` is the build-time
  project (exact pins, lockfile); `node build.mjs --check` and CI compare a fresh build with the
  committed hash manifest. Licence, generated third-party notices and
  [deploy/LAB-BUILDER-THIRD-PARTY-NOTICES.md](../deploy/LAB-BUILDER-THIRD-PARTY-NOTICES.md) ship with them.
- `GET /api/operations/known-images` lists the images the topologies in My labs already use, per
  kind; the builder's device templates start from them.
- **Fix:** `parse_definition` resolves a node's kind and settings through `topology.groups`
  (node, group, kind, defaults). A device whose kind came from its group was identified from the
  defaults and got the wrong driver.
- CI now also runs `test_nodes.py` and `test_discovery.py`, which the explicit list had missed.

## Changes in 1.29.1

A patch release of the student UI after a screenshot pass over every student page on a live
lab at 1440×900, 1280×720, 1920×1080 and in an 800 px window. Frontend only: the backend, the
VM helpers and every API route are unchanged apart from the lockstep version. Upgrading an
installed VM: run the launcher as usual; a container rebuild alone leaves the helpers at the
previous version and the manager answers 409 until they are refreshed (`setup-git.sh --refresh`
for the Git helper alone).

- **Fixed (Topology):** in the device rail a long network OS badge (*Junos (vJunos-switch)*)
  ran under the state pill. A rail card shows the name and the pill on the first line, the
  badge on its own line, then the reason and *Open CLI*.
- **Fixed (Topology):** *Expand* opened an overlay in which the map filled only the top-left
  corner. The map fills the overlay.
- **Fixed (Topology):** the map toolbar's *More ▾* items were drawn as boxed toolbar buttons;
  they are plain menu entries again.
- **Fixed (Tools):** the three cards share the row instead of leaving an empty fourth column,
  the backup schedule's label and hint sit on their own lines, and a backup's date and device
  count no longer break in the middle of a phrase in a narrow card.
- **Fixed (Capture traffic):** the "Choose a device above…" sentence sat in one narrow cell of
  the interface grid; it spans the whole box.
- **Fixed (All lab operations):** *Open all CLIs ↗* kept its arrow on a second line.
- **Fixed (Progress):** when saved progress cannot be loaded, *Try again* is centred with its
  text and the manager's own explanation leads (for example the helper-version sentence of a
  409) instead of always saying to check the VM connection.
- **Advanced:** key/value lists keep a gap from the heading or caption above them.
- The tour images in `docs/images/ui/` that show the rail, the Tools cards, the capture dialog
  and the Advanced lists were regenerated from the fixture manager.

## Changes in 1.29.0

The browser UI was redesigned around what a networking student does with a lab. The
backend, the VM helpers and every API route are unchanged; every capability of the
previous UI is still reachable (the functional-parity review in
`docs/redesign/PICKUP.md` lists each one with its new place).

- **Home ("My labs")** replaces the sidebar: lab cards with a state pill, *n of m devices
  ready* and the last save, a *Continue* card, *Also running on the VM* with Import, and a
  **Manager ▾** menu (VM connection…, Import lab files…, Deploy a new lab…, Refresh lab
  list, Running labs on the VM…, Operation history…, Manager settings…, Diagnostics).
- **Lab workspace**: header with the state, readiness count, last save, **Save progress**
  (with checkpoint and baseline) and **Lab actions ▾**; a situational banner (running
  operation with *View output*, needs attention, credentials needed, starting); tabs
  **Topology · Devices · Progress · Tools · Advanced**. Deep links `#lab=<id>&view=<tab>&device=<name>`,
  the Back button and the legacy tab names keep working.
- **Topology**: device state dots and glyphs, a context menu with inline reasons (*Open CLI ↗*,
  *Capture traffic…*, *Back up configuration*, *Device details*), loading/empty map states,
  map notes; the renderer emits colours only for imported styles.
- **Devices** and the **device panel**: one state vocabulary (*Ready*, *Starting*, *Needs
  credentials*, *Needs attention*, *Unavailable*) with the sentence that says what to do;
  *Technical details* keeps the classic table; the panel offers *Test login now* / *Check
  credentials* and re-checks a device after a connection or credential edit.
- **Progress**: status card, **Saved versions** grouped as Latest / Checkpoints / Baseline /
  Instructor and reference versions / Other labs in this repository (View, *Compare with my
  latest save*, *Apply to running lab…* for Junos states from any compatible folder without
  changing the save location), **Recent saves** rows, the first-save dialog, quiet saves,
  the **Save location** card with the folder browser inside it, student copy for every Git
  and restore dialog; the restore review lists each device's outcome and the safety rules.
- **Tools**: Packet capture (the device picker first in the dialog, student copy), Telemetry
  (*Open lab map ↗* / *Open network dashboard ↗*, Telemetry settings…), Configuration
  backups, Open all CLIs, map exports. **Advanced**: deployment details with visible reasons
  and the VM file details of every lab, lab source, credentials, action logs, all lab
  operations, technical details, danger zone.
- **Lab operations**: student action names, a per-action review (effect, *Configuration
  changes you have not saved are lost.*, the last-save line, *Save progress first*, the raw
  command under *Technical details*), banner-first confirms, a sectioned *All lab
  operations…* dialog, lab-scoped operation history, *Running labs on the VM…*.
- **Standalone pages**: the CLI launcher (*Open CLIs · <lab>* with device state pills), the
  deploy page, the SSH terminal (device-first title, plain-words status, Reconnect), the
  network dashboard launcher (headline + details), **Diagnostics** (formerly Debug panel).
- **Design system**: tokens, focus ring, menu pattern, tablist, skeleton, glyph sprite;
  `terminal.css` re-tokenised; no inline styles, no CDN, self-only CSP kept.
- New scripts `status.js`, `shell.js`, `home.js`; new tests `test_status_ui.js`,
  `test_shell_ui.js`, `test_home_ui.js`, `test_topology_menu_ui.js` (in CI); every pinned
  label in the existing tests rewritten with its behavioural claim kept.
- **Fixed (VM Git helper):** the second *Save progress* or a checkpoint into a Junos folder
  saved since 1.28.0 was refused with "The destination contains files outside its manager
  manifest" because the helper did not count the folder's own `.jcfg` restore artifacts as
  manifest files. Refresh the helper (`setup-git.sh --refresh`, done by the installer).
- **Fixed (Progress tab):** *Instructor and reference versions* now lists the saved states one
  level below a sibling folder, so the course layout made by `deploy/scaffold-lab.py`
  (`<slug>/reference/{start,solution,broken-01}`) shows with *Apply to running lab…*.
- Validated live on a fresh dev VM installed with the quick-install guide (cJunosEvolved +
  vJunos-switch, real Git commits and pushes, a two-node live restore with pre/post backups, a
  management-loss rollback, browser Wireshark, the lab lifecycle through the UI); the record is
  in `clab-backup-ui/VALIDATION.md`. Pin `mgmt-ipv4` in topologies whose saved states will be
  applied after a redeploy (see [GIT-PROGRESS.md](GIT-PROGRESS.md#apply-a-saved-configuration-to-a-running-node)).

## Changes in 1.28.0

Apply a saved Junos configuration to a running node without a reboot or a containerlab
redeploy, and reach a nested Git save folder in one step. See
[GIT-PROGRESS.md](GIT-PROGRESS.md#apply-a-saved-configuration-to-a-running-node) and
[LAB-OPERATIONS.md](LAB-OPERATIONS.md#apply-a-saved-configuration-to-a-running-node).

- **Apply to running lab.** Select any folder in *Where this lab lives* that holds a
  saved Junos state and choose **Apply to running lab…** — the lab does not have to be
  connected to that folder, so a repository of named states (Base, working, Final,
  Broken) is a pick-and-load library. The same action is also on a saved version in
  *View changes / History*. The manager shows a review screen (source, target
  nodes, whether each already matches the saved state, the safety notes), backs up the
  current configuration of every target first, then loads the saved configuration onto
  the running node and activates it with a confirmed commit. This is a complete
  desired-state replacement: a statement the student added that is not in the saved
  version is removed, not merged. The node is never rebooted, restarted or redeployed.
  The restore runs as a managed job (`app/restore.py`, `POST /api/labs/{id}/restore`)
  with the same serialization, per-node results, secret redaction and persistent history
  as a backup, over the manager's existing direct node-SSH path — no new host helper.
- **Whole-device restore mechanism.** Junos `show configuration | display set` output
  can only be merged (`load set`), so it cannot remove stale statements. Every Junos
  backup now also captures a hierarchical restore-grade candidate (`show configuration`)
  beside the display-set file; the restore loads it with `load override terminal`, runs
  a configuration check, and commits with `commit confirmed`. After loading, the manager
  reconnects to prove the node is still reachable and only then confirms the commit; if
  it cannot reconnect, the node rolls back to the pre-restore state on its own. The saved
  snapshot records the restore artifact in its manifest (schema 2); a snapshot saved
  before this release has no artifact and is offered as view/download only.
- **Supported platforms.** Live restore covers `juniper_cjunosevolved` and
  `juniper_vjunosswitch`, validated on the dev VM. IOS-XR and EOS keep view/download
  only until an equivalent replace-and-verify mechanism is validated for them.
- **Safety and verification.** The pre-restore backup is mandatory: a node whose backup
  fails is not changed. After the restore the manager captures the node again, normalises
  it with the same logic as a backup and compares it to the saved desired state, so the
  UI can show that the stale statement is gone and the desired statements are present.
  The review, logs and job records carry counts and secret-masked sample lines, never a
  full configuration dump.
- **Nested Git folders in one step.** *New folder…* accepts a nested path such as
  `Week-04/BGP/Final-State` and shows the resulting destination as you type, so a novice
  can create `CCNP-SP/Labs/Week-04/BGP/Final-State` without clicking through each level.
  Every segment is validated the same way a single folder name is, on the browser, the
  manager and the VM helper.
- **Git repository is a top-level tab.** The Git repository view moved out of the
  *More* menu into the main workspace tab row (Topology, Nodes, **Git repository**,
  Backup history), so saving progress and *Apply to running lab…* are one click from
  the lab. *More* now holds Credentials and Action logs.
- Live device restore uses the manager's direct node-SSH path and touches no host helper.
  The VM Git helper does gain schema-2 support so it can save and read the new restore
  artifact, so refresh it with `setup-git.sh --refresh` (the installer does this) and
  rebuild the manager image.

## Changes in 1.27.0

Students can see where a lab keeps its files in the connected repository, move the lab
to another folder, create folders, and swap a wrongly connected repository, all from
**More → Git repository**. See [GIT-PROGRESS.md](GIT-PROGRESS.md#where-this-lab-lives)
and [GIT-SETUP.md](GIT-SETUP.md#connect-or-switch-a-repository-from-the-manager).

- **Where this lab lives.** The Git repository view shows the connected repository the
  way a file browser would: the folder path at the top, a folder outline on the left and
  the contents of the selected folder on the right, read from the VM checkout at its
  current commit (new owner-level helper mode `browse`, served by
  `GET /api/git/repositories/{id}/tree`). Lab folders are tagged with the lab that saves
  there, `latest/`, `baseline/` and `checkpoints/` carry plain-language descriptions, and
  a folder that is registered but not saved to yet reads *created on first save*. Nothing
  is read from GitHub; the browser only ever sends registration IDs and folder names, and
  the helper validates every path again.
- **Save this lab here / New folder.** Selecting a folder and choosing *Save this lab
  here*, or creating a new folder, registers that folder for the lab through the helper's
  new root-level `register-prefix` mode and reconnects the lab to it, keeping the device
  selection and the review preference (`POST /api/labs/{id}/git/destination`;
  `POST /api/git/repositories/{id}/folders` registers a folder without connecting). The
  lab's previous folder registration is retired, so a lab that saved at the repository
  root can move into a subfolder. Optionally the files already saved under the old
  folder move along in one commit that is pushed like a save (new owner-level helper
  mode `move`, recorded as a *Folder move* job with the usual retry, review and push
  handling; the journal, hook and filter checks of a save apply). Overlapping lab
  folders and mixing a root registration with subfolders are still refused on the VM,
  and a folder still cannot be nested inside another lab's folder. A pending save blocks
  a move.
- **Use a different repository.** The connected repository card names the push URL,
  branch, VM account and the exact folder path, and offers *Use a different
  repository*: pick another registered checkout, or paste an HTTPS clone URL. The
  manager then does on the VM what the terminal wizard does (new root-level helper mode
  `connect`, `POST /api/labs/{id}/git/connect`): it reuses a checkout that already holds
  that repository or clones it under `~/labs/` as the VM account that owns the registered
  repositories (or the engineer account on a fresh VM), checks that account's existing
  GitHub CLI login and write permission, sets a commit identity from that GitHub account
  when the checkout has none, registers the folder and connects the lab. GitHub page
  links such as `/tree/main` are turned into the clone URL; a repository the account
  cannot push to is refused before anything is cloned; no token or password ever enters
  the manager. A lab on a VM with no repository yet gets the same *Connect a repository
  by URL* button; the terminal wizard remains available and unchanged.
- The VM Git helper must match the manager again; the installer and
  `setup-git.sh --refresh` install it.

## Changes in 1.26.0

The map takes its node positions from the annotations file, destroy cleans up, and
Grafana runs only while someone reads it, with fifteen minutes of history everywhere.
See [LAB-OPERATIONS.md](LAB-OPERATIONS.md), [TELEMETRY.md](TELEMETRY.md) and
[GRAFANA-MAP.md](GRAFANA-MAP.md).

- **Map positions come from the annotations file.** *Deploy lab* and *Save to manager*
  registered the workspace from the topology YAML alone, so every node landed on the
  default grid (a flat row) and the `.annotations.json` beside the topology was never
  read; nothing applied it afterwards either, because discovery leaves a saved drawing
  to an explicit *Sync from VM*. Now the browser reads the file with the topology
  through the VM helper and sends it along, so the preview, the saved workspace and the
  Grafana map start from the drawn layout (`/api/operations/parse-yaml` takes
  `options.annotations` and reports `annotations_used`; a broken file falls back to the
  grid without failing the topology). A drawing records whether its nodes were placed
  (`placed`); discovery places a grid-only drawing from the annotations file beside the
  deployed topology on its next pass, without a sync and without touching logins or
  nodes, and never replaces a layout somebody saved in the editor. Drawings saved before
  this release are recognised by their coordinates, so an existing flat lab is placed
  as soon as its files are seen.
- **Destroy cleans up.** *Destroy deployment* and the quick destroy button run
  `containerlab destroy --cleanup`, so the containers go together with the generated
  lab folder (`clab-<name>`) and the next deploy starts clean; the review names the
  folder. The flag is sent unless the installed containerlab is known to lack it (the
  helper refuses an unsupported flag itself). Redeploy keeps the folder unless its
  cleanup variant is chosen; the separate *Destroy + cleanup* entry is gone.
- **Grafana on demand.** Grafana idles at a few hundred MiB, so the telemetry stack
  leaves it stopped: `deploy/compose.telemetry.yml` names the container
  `clab-manager-grafana` with the restart policy `no`, and `setup-telemetry.sh` checks
  the stack and then stops Grafana. The lab header's **Grafana ↗** button opens
  `/static/grafana.html`, which asks the manager to start Grafana on the VM when it is
  stopped (`docker start` of that one container through the reviewed operations helper,
  new mode `grafana` with `status`, `start` and `stop`) and then moves the tab to the
  dashboard on the manager's own host name; only a dashboard path travels in the link.
  The manager (`app/grafana_control.py`, `GET /api/telemetry/grafana`,
  `POST …/start`, `POST …/stop`) watches Grafana's request counters over the loopback
  and stops it after `TELEMETRY_GRAFANA_IDLE_MINUTES` (default 15, written into `.env`
  by the setup; 0 keeps it running once started) without a dashboard request; an open
  dashboard refreshes every ten seconds and keeps it alive. **Lab actions → Telemetry
  settings…** shows the state and has **Stop Grafana now**. Prometheus keeps running.
  `check-install.sh` treats a stopped Grafana as the normal state (PASS, read-only,
  never starts it) and checks its health and the Flow panel only while it runs; the CI
  smoke stops and starts the container by name and expects everything re-provisioned.
- **Fifteen minutes of history everywhere.** Prometheus keeps 15-minute blocks with a
  15-minute retention (the block size matters: retention alone would keep the default
  two-hour head block in memory), on a smaller tmpfs; the manager's session store keeps
  15 minutes per series (130 points) instead of an hour; the dashboards and the
  generated lab maps open on the last 15 minutes with 5- and 15-minute quick ranges.
- **Operational notes.** The VM helper must be reinstalled for the new `grafana` mode
  (`start-manager.sh` does it; an old helper answers with a message that says so).
  Upgrading recreates both telemetry containers; Grafana's data volume is tmpfs and
  everything in it is provisioned from files, so a stop loses nothing.

## Changes in 1.25.0

A documentation and installation audit. Grafana is the one place where telemetry is
shown, the browser Wireshark and Grafana stacks are part of every installation, every
documented command works from any directory, and the release check now refuses a guide
that names another release. See [INSTALL.md](INSTALL.md), [TELEMETRY.md](TELEMETRY.md)
and [REPOSITORY-MAINTENANCE.md](REPOSITORY-MAINTENANCE.md).

- **Telemetry lives in Grafana.** The Telemetry tab, its charts, the live link colours
  and status dots on the topology map, the *View telemetry* entries in the node menu,
  the node details and the link menu, and the per-series chart routes
  (`/telemetry/series`, `/telemetry/bgp-series`) are gone. The lab header shows
  **Grafana ↗** (or **Lab map in Grafana ↗** when the lab has a generated map), opening
  the lab's dashboards on the manager's own host name; `/api/state` announces
  `telemetry.grafana` (`enabled`, `port`, `map_uid`) per lab. **Lab actions →
  Telemetry settings…** keeps the per-lab switch, the gNMI login profile, the removal
  of manager-added lines, the reason a node is not streaming and a retry for failed
  nodes. The collector, the Prometheus exposition and the lab-map publisher are
  unchanged.
- **Link hover on the map is fixed.** The telemetry overlay applied `stroke-dasharray`
  to every path of a link group, including the invisible 16 px hit path that makes a
  link clickable, so a link without telemetry (dotted) reacted to the pointer only where
  a 1 px dash happened to lie under it and the highlight flickered along the wire. The
  map renderer and stylesheet are back to their pre-telemetry state; capture from a
  link, the right-click menus, pan, zoom and the diagram editor are as before.
- **Browser Wireshark and Grafana are standard.** The installer runs both as their own
  retryable phases after the manager (phases 4 and 5 of 6, or 7 with VS Code access);
  the launcher (`start-manager.sh`) refreshes both on every upgrade before it creates
  the manager, unless `.env` says `CAPTURE_PROVIDER=disabled` or
  `TELEMETRY_STACK=disabled` or `--manager-only` is given; menu **4** reinstalls both
  without a rebuild (Check is now 5, Exit 6). `setup-capture.sh` and
  `setup-telemetry.sh` recreate the manager themselves so their settings take effect
  (`--no-recreate` is what the launcher passes), both take `--remove` (capture keeps its
  token, telemetry its admin password), and the new `recreate-manager.sh` reloads
  `clab-backup-ui/.env` into the manager without a rebuild. The telemetry setup creates
  the manager data directory when it is missing, so a fresh VM works in any order. The
  health check reports a missing stack as **WARN** with the setup command (capture is
  now titled *Browser Wireshark capture*), and every `Next:` line is an absolute command.
- **Every command works from any directory.** The guides keep the source in
  `~/projects/clab-manager`, write every command with its absolute path and upgrade by
  pulling into the same folder; the health check's advice prints absolute paths.
- **Release numbers are tracked.** `deploy/verify-release.py` now also checks the
  documentation: the living guides may name only the current release (history is
  written as "since x.y.z" or "x.y.z or later"), versioned source folders and image tags
  are refused, and the README, changelog, validation record and handoff notes must lead
  with the current release. `deploy/set-release.py NEW` moves every runtime and
  documentation marker in one go. CI and `test_release_consistency.py` run both checks.
  Every guide was rewritten to the convention; the Docker Hub image guide and the
  repository audit narrative moved to `docs/archive/`, and
  `REPOSITORY-MAINTENANCE.md` now states the release rules.

## Changes in 1.24.0

A Grafana weathermap for every lab, generated by the manager. See
[GRAFANA-MAP.md](GRAFANA-MAP.md).

- **Lab map dashboards.** For each lab with a drawing the manager renders an SVG of the
  topology (positions, icons, labels, groups and notes as on its own map) and a Flow
  panel configuration that binds every link half, port and node to the series it
  exports, and writes one provisioned dashboard `Lab map · <name>` into the Grafana
  folder *Lab maps*. Links are coloured and dash-animated by the far end's receive rate
  (grey, green, yellow, orange, red from 10 kbit/s to 5 Mbit/s), each link end shows its
  rate, port dots follow oper-status, the node dot the telemetry state. Maps follow
  renames, redraws and removals within 30 seconds. `app/telemetry_map.py`, previews at
  `/api/labs/{id}/telemetry/map.svg`, `map.yml` and `map.json` for hand-tuned variants.
- **Flow panel plugin.** `setup-telemetry.sh` installs `andrewbmchugh-flow-panel`
  1.20.1 (Apache-2.0, community-signed) once, pinned, with the pinned Grafana image's
  CLI into `TELEMETRY_CONFIG_DIR/plugins`, mounted read-only so restarts work offline;
  it creates `TELEMETRY_MAPS_DIR` (default
  `/srv/containerlab-node-manager/data/telemetry/dashboards`) for the manager's user
  and mounts it read-only into Grafana; the readiness wait reports whether the plugin
  loaded. `--remove` deletes the plugin folder again.
- **Telemetry tab** opens the lab's map with **Open lab map in Grafana ↗** when one
  exists. New metric `clab_telemetry_node_state_code` (-1 failed … 3 streaming) for
  value-driven colours. `/api/telemetry/health` reports `maps`.
- **check-install** warns when the Flow panel is not loaded or the map folder is not
  writable. CI's telemetry smoke installs the plugin, provisions a generated map and
  verifies that every series its cells bind to is answered.

## Changes in 1.23.1

The first live run of 1.23.0 on the dev VM (cEOS 4.35.0F, Prometheus v3.14.0, Grafana
13.0.2) found six defects in the telemetry release; all are fixed and re-validated live.
See [TELEMETRY.md](TELEMETRY.md).

- **Grafana showed "An error occurred within the plugin" on every panel.** Prometheus
  v3.14.0 refuses `--web.enable-remote-write-receiver=false` ("unexpected false"), so the
  container crash-looped and the provisioned data source had nothing to answer with,
  while `setup-telemetry.sh` still reported success. The flag is gone (the receiver is off
  by default), the setup script now waits for Prometheus `/-/ready` and Grafana
  `/api/health` and fails with the container status and logs when they do not come up,
  and CI starts the real stack against a fixture manager (`deploy/telemetry/smoke.py`),
  checks the data source, the three provisioned dashboards and every panel and variable
  query.
- **cEOS samples were dropped, no receive rate, no link state.** cEOS stamps each
  notification with the last change time of the leaves it carries, so one 10 s cycle
  arrives as several notifications whose timestamps differ by minutes; the store ordered
  all leaves of an interface on one clock and discarded whichever group came "earlier"
  (half of all samples live). Samples are now ordered per leaf by the device clock while
  rates, chart points and freshness use the manager's receive time; a cycle that arrives
  in several notifications a second apart shares one chart point and each direction keeps
  its own newest rate.
- **Interface state stayed unknown on cEOS.** A plain on-change subscription is answered
  with the sync marker only (no initial value), so oper/admin state and the map link
  colour waited for the first flap. The EOS state subscription now carries a heartbeat of
  one sample interval. Verified live: shutdown turns the link red within 3 s from both
  ends, no shutdown turns it green again.
- **"BGP: failed" on every lab without BGP.** EOS sends nothing for a sampled path with
  nothing behind it; after two quiet minutes the group was closed as failed. A quiet group
  now reports *idle*, stays subscribed and turns streaming when data appears.
- **Slow recovery after `docker restart` of a node.** The address and running state do
  not change, so nothing reset the node and the retry backoff grew to minutes. A port that
  does not answer now retries every 30 s at most; the node streams again shortly after the
  NOS boots.
- **check-install** names a Prometheus that does not answer (with the Compose commands to
  inspect it) separately from a target that is not scraped, and classifies scrape errors
  instead of echoing them. Group pills keep their encoding; the telemetry setup tests run
  on Windows as well.

## Changes in 1.23.0

Live network telemetry for disposable labs, automatic from deploy to chart, kept in
memory only. See [TELEMETRY.md](TELEMETRY.md).

- **Automatic provisioning.** Once the readiness monitor has a `show version` answer
  from a node of a lab with *Automatic telemetry* on, the manager opens an SSH shell
  with the node's saved login, reads the gRPC/gNMI service configuration and adds only
  the missing lines with the NOS's own scoped commit: cEOS `management api gnmi` /
  `transport grpc default` (running-config only, never `write`), IOS XR `grpc` +
  `port 57400` + `no-tls` with `commit`, Junos Evolved `set system services extension-service
  request-response grpc clear-text port 32767` in `configure private`. Containerlab's
  cEOS and XRv9k defaults already enable gNMI, so those usually need no change.
  Every added line is logged and recorded per node; repeat checks write nothing.
- **gNMI dial-in collector** in the manager process (pygnmi, BSD-3; grpcio) using the
  host-network path the manager already uses for SSH: interface counters every 10 s,
  oper/admin state (on change on EOS), BGP neighbour session state and prefix counts
  where the model is advertised. Plain-text gRPC on all three kinds (TLS with the
  device certificate where an EOS or Junos node already has it); encodings follow the
  node's capabilities; rejected subscriptions fall back to broader paths; a login
  refusal never probes further.
- **Session-only store.** Bounded rings (60 minutes, 400 points per series, 96
  interfaces and 64 neighbours per node, 512 nodes), rates from counter deltas with
  reset, gap and out-of-order handling, generation tags so a previous deployment with
  the same name and address never feeds a new one. Cleared on stop, destroy, redeploy
  (operations submitted through the manager), removal, manager reset and restart.
  Nothing is written to the encrypted state, backups, Git or the data directory.
- **Telemetry tab**: lab verdict, node cards with state and reason, interface table
  (wired peer, admin/oper, RX/TX bit and packet rates, errors, discards, last sample),
  SVG charts for 5/15/60 minutes, BGP neighbour table and prefix chart, settings
  dialog (automatic on/off, gNMI password profile, removal of manager-added lines),
  clear empty, off, waiting, stale, partial and failed states. Unsupported metrics
  show `n/a`, never zero; no utilisation percentages.
- **Topology overlay**: links coloured from both ends (up, up on one observed end,
  down with a mismatch marker, stale, no telemetry), hover text with rates, a status
  dot per node, a right-click link menu with *Capture packets* and *Telemetry* per
  end, *View telemetry* in the node menu and details drawer. Pan, zoom, annotations
  and the existing SSH, backup and capture actions are unchanged. Interface names are
  mapped per kind (`eth1` → `Ethernet1`, `eth1` → `GigabitEthernet0/0/0/0`, `eth4` →
  `et-0/0/0`), never guessed across kinds.
- **Node states**: Off, Waiting, Configuring, Connecting, Streaming, Stale,
  Unsupported, Failed with an actionable reason; streaming means usable samples
  arrived. Telemetry defers while a lab operation or backup job runs and never blocks
  terminals, captures, backups or deployments.
- **Settings and safety**: automatic telemetry is on for labs created from 1.23.0;
  earlier labs show an explicit *Enable automatic telemetry* step before any device
  write. gNMI uses the saved password login (SSH keys cannot be used; a password
  profile can be chosen). `TELEMETRY_COLLECTOR=disabled` turns the collector off.
  Secrets never enter responses or logs; failures are classified, not echoed.
- **Grafana dashboards in another tab (optional).** `sudo bash
  deploy/setup-telemetry.sh` starts Prometheus (v3.14.0) and Grafana OSS (13.0.2),
  digest-pinned, host-networked like the manager, with dropped capabilities, memory
  and PID limits and tmpfs data (two-hour retention). Prometheus scrapes the new
  `/api/telemetry/metrics` endpoint (Prometheus text format: node states, interface
  rates and counters, link states, BGP neighbours; names only) every 10 s; Grafana
  serves three provisioned read-only dashboards (Lab overview, Interfaces, BGP
  neighbours) to anonymous Viewers, with a generated admin password kept in `.env`.
  The Telemetry tab shows **Open Grafana ↗** and a per-node **Grafana ↗** link once
  the manager is recreated with `TELEMETRY_STACK=grafana`. `--remove` takes the stack
  down again. Licences are listed in `deploy/TELEMETRY-THIRD-PARTY-NOTICES.md`.
- **Health check** gains *Network telemetry* and *Grafana telemetry dashboards*;
  `check-install` reports the collector, each linked lab's verdict, Grafana's health
  and Prometheus scraping, plus manual traffic and dashboard checks.
- **Tests**: 74 new Python tests (names, store, adapters, scripted SSH sessions for the
  three NOS families, notification fixtures, the state machine on the app, an
  in-process gRPC gNMI server driven through the real pygnmi client, the metrics
  endpoint, the Grafana stack definition and setup script, the health checks) and a
  browser test file for charts, view states, overlay, Grafana links and menus. No live
  device validation was possible for this release; the acceptance procedure is in
  TELEMETRY.md.

## Changes in 1.22.0

The manager leads with deployment instead of import, and a freshly deployed lab is
usable without any manual setup.

- **Deploy-first landing page.** With no saved lab, the workspace offers **Deploy a
  new lab** (the VM topology browser, in place), lists labs already running on the VM
  with a one-click **Import**, and asks for the VM connection first when none exists.
  Importing a lab definition or an Ansible inventory stays available as links.
- **Deploy lab saves the workspace.** **Deploy lab** in the topology browser registers
  the workspace (nodes, map and VM source path) before containerlab runs, so the lab is
  in the sidebar at once and nothing has to be imported afterwards. **Save to
  manager** still saves without deploying.
- **Automatic NOS login.** Nodes of supported kinds use containerlab's documented
  default login when no credential profile or inventory login exists: cEOS
  `admin`/`admin`, vJunos-switch, vQFX and cJunosEvolved `admin`/`admin@123`, XRv9k
  `clab`/`clab@123`. A profile or an inventory login always wins; the Nodes table shows
  *Containerlab default login* when the default is in use. A readiness monitor logs in
  to every running node of a linked lab over SSH and asks for `show version` every
  20 seconds until the NOS answers, shows *NOS booting 0/2* and then *NOS ready 2/2*
  in the deployment bar, records each answer in the *Last SSH check* column, and runs
  **Test NOS login** once when every node has answered after a deployment. SSH, the
  SSH menu entry and **SSH all nodes** open as nodes answer; a node that stops or
  restarts must answer again, and a failed automatic test sends its nodes back to
  booting and is retried up to three times per boot. A login refused three times in
  a row is reported as failed with the fix (assign a profile) and keeps being retried
  each minute. **Sync from VM** fills a blank saved login from the generated inventory.
- **Backups and login tests survive a redeploy.** Lab containers generate new SSH host
  keys on every deploy, and the Ansible transport used to record the old keys in the
  manager's `known_hosts` and then refuse the node with *host key mismatch* until the
  manager was recreated. Every job now runs with its own empty `known_hosts`.
- **Operation output** starts with a large green banner such as *✔ Deploy lab
  succeeded · Exit 0 · Operation completed*; failures are red, running jobs blue.
- **VM connection** opens with *Enable automatic discovery* and *Trust a replacement
  SSH host key on the next connection* both checked.
- **Capture dialog.** Opened from a node or a link, it lists that node's topology
  interfaces first (a single one is already ticked, and a link opens on its first
  endpoint). The remaining live Linux interfaces sit under *All live Linux
  interfaces*; scope, search and the capture-target selector sit under *Advanced* and
  unfold only when no target could be resolved.
- **Wireshark viewer.** One toolbar row with the status inline and the instructions
  under *How to save a capture*, which say to type the full file name ending in
  `.pcapng` because Wireshark on the VM does not add the extension; the *No saved
  captures yet* message says the same.

## Changes in 1.21.1 (historical)

Fixes from vetting the 1.21.0 browser Wireshark on a live Ubuntu VM. The viewer now
connects: the pinned Wireshark image's websockify only completes a handshake that
offers the `binary` WebSocket subprotocol, so the session service and the manager
relay offer it (and answer it only to a browser that asked). **Download saved
captures** returns what Wireshark saved under `/pcaps`: that folder is now a
tmpfs-backed Docker volume the daemon can read instead of a container tmpfs that the
archive API never sees; the same size, ownership and cleanup limits apply, and an
empty folder answers "No saved captures yet" instead of an empty archive. The viewer
checks a download before handing it to the browser so that message is shown in
place. `setup-capture.sh` recreates the capture services, so upgrading a 1.20.x
stack no longer stops on the renamed project network. The CI smoke test reads the
container's temporary and saved files from inside the container, where tmpfs
contents live, and checks the empty-folder response. See
[Browser capture setup](CAPTURE.md) and [validation evidence](../clab-backup-ui/VALIDATION.md).

## Changes in 1.21.0 (historical)

Wireshark now runs on the lab VM and opens in the browser. The workstation plugin,
external-app launcher and public Edgeshark URL setting are removed. A separate
session service creates isolated, pinned Wireshark containers; the manager keeps
its existing permissions. Sessions support reconnect, saved-capture downloads,
explicit removal, browser ownership and idle/lifetime/resource limits.

Run `sudo bash deploy/setup-capture.sh` on the VM, then upgrade/recreate the
manager. Existing 1.20.x local capture settings are migrated while unrelated
settings are retained. No workstation capture tunnel is needed. See
[Browser capture setup](CAPTURE.md) and [validation evidence](../clab-backup-ui/VALIDATION.md).

## Changes in 1.20.1 (historical)

Fixes from vetting the 1.20.0 Wireshark capture on a live Ubuntu VM with Edgeshark.
A selected host-namespace target no longer fails with "target changed" whenever any
container starts or stops: the target identity now covers the namespace, root
process, name and engine prefix, and only the interfaces you selected are checked
against fresh discovery. **All host targets** lists a namespace shared by a
host-networked container (the manager itself) once, naming the other as an alias,
and marks loopback-only namespaces. A namespace Edgeshark reports in an unreadable
form is skipped and counted instead of hiding every other target. Prepare capture
stays disabled until an interface is ticked, and node/menu Capture actions are
disabled when the manager reports capture disabled. `check-install` gains an
**Optional packet capture** check. [CAPTURE.md](CAPTURE.md) now states what was
observed: Packetflix 0.9.7 does not reject a mismatched PID, start time or
namespace, so the manager's re-discovery and link expiry are the real stale-target
guards. Root-run helpers (`setup-git.sh --list`, a privileged `check-install`) no
longer leave root-owned Python bytecode in the ordinary owner's source folder, which
blocked removing or re-staging that folder without sudo.

## Changes in 1.20.0 (historical; desktop launch replaced in 1.21.0)

Optional Wireshark capture is available from node actions, either endpoint of a
map link, and a searchable live interface browser. All host targets includes
bridges, physical NICs and other namespaces. Multiple interfaces in one namespace
can be selected together. The manager rechecks selections before preparing a
native Wireshark handoff; packets stream directly from Edgeshark to the workstation.

The workstation handoff introduced in this release was replaced by VM-hosted
browser sessions in 1.21.0. Use the current [capture setup](CAPTURE.md).

## Changes in 1.19.4

Engineer access for VS Code Remote - SSH and the Containerlab extension is now a
setup step instead of a paste-in block. The two errors it removes are
`Extension activation failed. Insufficient permissions. Ensure USER is in the
clab_admins and docker group(s)` and `EACCES: permission denied, mkdir
'/etc/containerlab/...'` from the VS Code file explorer. The new
`deploy/setup-engineer-access.sh` adds one ordinary account to `docker` and
`clab_admins`, makes every trusted lab root a group-writable `clab_admins`
folder with the setgid bit so new files inherit the group, restores the
containerlab SUID mode, and records the account so `start-manager.sh` reapplies
it after operations setup or a containerlab upgrade resets those. The installer
offers it in the standard flow and as menu option 3; `check-install` gains an
**Engineer access** check that names the exact missing piece. Topologies the
manager creates in such a folder are group-editable (0664; 0644 elsewhere)
instead of root-only 0600, so the same lab can be edited in VS Code. The manager
itself is unchanged and still uses sudo through its restricted gateway.

## Changes in 1.19.3

Fixes for the 1.19.2 bug-fix report. The Debug panel and the operations error now
name the real cause when the browser reaches a connected VM but folder browsing and
Git return HTTP 409: previously both said "Check the saved VM password", even though
connected discovery already proves the password. The operations "command not found"
case is now reported as "the clab-discovery SSH session did not run the operations
gateway" with the enable-operations remedy, and the Debug panel classifies it as a
gateway problem instead of an authentication failure. `check-install` gives the same
gateway-specific next step when discovery is connected.

When the web page opens and no VM connection is configured yet, the manager now
prompts for it once, since the VM connection is what makes discovery, operations and
Git work. A configured connection, or one dismissed this session, is not re-prompted.

Guided Git setup (`bash deploy/setup-git.sh`) now asks which repository subfolder
holds each lab, so one repository can hold many labs (for example `bgp`, `eth`, `ip`),
each pushed to its own subfolder, and an already-registered repository can gain a new
subfolder for another lab. Successful setup ends with a clear success banner. See
[GIT-SETUP.md](GIT-SETUP.md) and [GIT-PROGRESS.md](GIT-PROGRESS.md).

This is a source delivery; no Docker image is published. It was installed on a fresh
Ubuntu 24.04 dev VM, where folder browsing, a lab deploy through the operations
gateway, NOS login and backup on two cEOS nodes, a subfolder Git registration and a
pushed Save progress all succeeded, and `check-install` reported no failures. See
[VALIDATION.md](../clab-backup-ui/VALIDATION.md) for the exact evidence and limits.

## Changes in 1.19.2

Integrates the remaining [deployment audit fixes](archive/DEPLOYMENT-AUDIT.md)
with 1.19.1. Topology creation now preserves files created concurrently.
Discovery, scheduled backups and lab/Git operation guards recover from storage
write failures. Failed audit writes no longer fail completed actions, and Debug
panel reports the last audit-write result. Missed events are not replayed.
Git response limits include stderr, and Linux Git timeouts stop descendants
even after the parent exits.

Retains 1.19.1's SSH EOF handling, longer helper/discovery/debug timeouts,
dependency bounds and LF normalization. Install matching manager and helpers
with `bash deploy/install.sh`, keeping existing persistent data, then confirm
Release 1.19.2. See the audit for test evidence and live deployment limits.

Documentation added after publication: the installation guides gain three
paste-in fixes for the VM clock after a Proxmox snapshot rollback, passwordless
root SFTP for WinSCP, and VS Code Remote - SSH with the Containerlab extension.
The installer itself is unchanged and still leaves those choices to you.

## Changes in 1.19.1

Applies the 1.18.1 operations-transport fix to the two remaining SSH readers.
Discovery and Git transfers now wait for stream end-of-file before accepting
the helper's exit status; OpenSSH can report that status while the helper's
final stdout bytes are still queued, which truncated large inspection or Git
envelopes and produced misleading "Invalid containerlab inspection response"
or "Install or refresh the matching Git helper" errors.

The installed discovery helper allows `containerlab inspect --all` 25 seconds
instead of 8 (per-container label lookups stay at 8 seconds), the manager
waits 60 seconds for the helper, the health checker matches that budget, and
a timeout is reported as a timeout rather than a permissions failure. Update
both the image and the host helpers with `sudo bash deploy/start-manager.sh`.

Also: the Git wizard keeps `git clone` attached to the terminal with no
120-second limit; the Debug panel classifies a rejected VM password as an
authentication failure and gives the capabilities probe 90 seconds;
`setup-discovery.sh` explains a missing containerlab or Docker binary instead
of exiting silently; the browser footer fallback version is release-checked;
vendor Ansible collections are pinned to their current major versions; and
`.gitattributes` normalizes every text file to LF.

Prepared from published main `2d34415` (1.19.0) on
`claude/transport-eof-and-helper-timeouts`. Source delivery only; no image
publication, fresh-VM run or live device validation is implied.

## Changes in 1.19.0

Adds a [development debug panel](DEBUG-PANEL.md) available before any lab is imported.
Inspect runtime versions, VM readiness, recent API failures and independent
read-only folder/helper checks, then download a metadata-only JSON report.
Credentials, paths, request payloads and raw logs are excluded.

Fixes a remaining file-browser failure: a successful folder listing no longer
waits for command-capability checks. Files render immediately; failed command
checks disable only optional online controls and show a diagnostic hint.
The existing 1.18.1 SSH stream and gateway fixes are retained.

Run `bash deploy/install.sh` from the complete source root on the VM to update,
then verify the release in Debug panel. Source delivery only; no image
publication or VM deployment is implied.

## Changes in 1.18.1

Fixes operations SSH reads that could stop at the exit-status packet before the
helper's final response arrived. The manager now waits for stream EOF, retains
bounded diagnostics, and distinguishes missing gateway and sudo-permission errors.
The launcher also checks helpers through `clab-discovery` before building the image.

The health checker retains its terminal session for sudo authentication. Earlier
1.17.0/1.18.0 checkers could report administrator access PASS followed by false
failures for every privileged check. On those releases, rerun the same report
with `sudo bash deploy/check-install.sh --owner archtop` (use your ordinary account).
See [the health report guide](HEALTH-CHECK.md) for the complete recovery procedure.

## Changes in 1.18.0

Adds Juniper vQFX and vJunos-switch to node import, NOS credential profiles,
SSH checks, configuration backups and Git progress saves. They use the existing
Junos SSH driver to capture `show configuration | display set | no-more`.

| Device | Containerlab kind | Also recognized by the manager |
|---|---|---|
| Juniper vQFX | `juniper_vqfx` | `vr-vqfx`, `vqfx` |
| Juniper vJunos-switch | `juniper_vjunosswitch` | `vr-vjunosswitch`, `vjunosswitch` |

Use the canonical kind in new Containerlab YAML. Select the matching NOS in
**Credentials** and enter that device's actual login. Passwords are not filled in
automatically. Previously saved unknown nodes can use **Sync from VM**, or choose
the NOS in **Node details → Edit connection**. Check **Include in backups** for
each intended node; sync preserves existing selection and credential choices.
Captured files use `.set` internally and `junos-display-set` in Git manifests;
individual downloads are named `vQFX_*.cfg` or `vJunos-switch_*.cfg`.

Build the matching manager and update its host helpers using the source launcher
before testing a device login and backup. Live configuration restore remains
unavailable. Containerlab documents vJunos-switch as unsupported inside a VM
because of its nested architecture; adding this manager adapter does not change
that deployment requirement. See the [vQFX](https://containerlab.dev/manual/kinds/vr-vqfx/)
and [vJunos-switch](https://containerlab.dev/manual/kinds/vr-vjunosswitch/) kind guides.

The Junos support was merged in main `7331e9a` (1.18.0). Live SSH/backup
validation of these two NOS images remains pending. The 1.18.1 fixes are prepared
from that baseline; publication and a complete fresh-VM validation remain pending.

## Changes in 1.17.0

Adds a separate installation checker and connects installer menu **3** to the
full report. It verifies services, persistent state, SSH/SFTP policy, helper
execution through `clab-discovery`, actual topology folders over saved SSH,
and owner-scoped Git checkout readiness. Optional checks cover administrative
WinSCP, KVM and remote Git reads. It gives recovery commands and text/JSON
results without automatically repairing setup or running lab/push operations.

Prepared locally from published main `7c25648` (1.16.1); publication and a full
fresh-VM validation of 1.17.0 remain pending. The initial installation's short
HTTP/version check remains separate from this final report after browser setup.

## Changes in 1.16.1

Package setup now shows VM UTC time and NTP status before APT updates, with a
bounded wait for an already-active time service. It identifies future-dated or
expired repository metadata and gives clock/mirror recovery steps while keeping
APT validation enabled. The same checks cover Git/GitHub CLI package setup.
See [clock recovery](FRESH-VM-GUIDE-V2.md#recovery-c) to resume a paused install.
These changes are on published main `7c25648`; a complete fresh-VM run of 1.16.1
has not been verified. For WinSCP access to root-owned files, complete the
[manual administrative SFTP setup](FRESH-VM-GUIDE-V2.md#winscp-admin-sftp).

## Changes in 1.16.0

Run `bash deploy/install.sh` as your ordinary VM account for a consolidated
terminal installer: prerequisites, optional APT media repair, password/helpers,
image build/start, HTTP/version checks, then Git setup. Separate menu entries
reopen Git setup or check a running manager without rebuilding it.

The Git terminal wizard has numbered steps, retry/cancel recovery, owner and
identity checks, and preserves existing registration settings. Start with the
[guided installation guide](INSTALL.md); detailed manual instructions remain available.

## Changes in 1.15.3

Guided setup can resume an existing checkout with `--guided --repo PATH`, repair
missing/invalid commit identity, and show the exact source-script path after a
failed registration. Setup guidance distinguishes Linux owner, GitHub login,
commit identity and the two project directories. See [Git setup](GIT-SETUP.md).

## Changes in 1.15.2

Guided Git setup rejects GitHub page URLs before cloning, explains the local
checkout directory and reports package failures with recovery instructions.
See [package installation recovery](GIT-SETUP.md#package-installation-recovery)
for the Ubuntu `file:/cdrom` error. This source is prepared locally for publication.

## Changes in 1.15.1

Repository repair: VERSION now matches the 1.15.1 app/helpers. Run
`python3 deploy/verify-release.py` to check the complete source before publishing
or installing. The launcher runs this check automatically. See
[repository audit and maintenance](REPOSITORY-MAINTENANCE.md) for the cleanup and
repair of affected fresh installations.

Guided Git onboarding now uses the existing VM account, prepares HTTPS login and
commit identity, and checks repository readiness before registration. Run
`bash deploy/setup-git.sh` without sudo. Start with [GIT-SETUP.md](GIT-SETUP.md).
Missing identity is caught before an export writes or stages files. Helper-only
upgrades retain existing registrations; unchanged re-registration retains revisions.

## Git progress introduced in 1.15.0

- **Save progress** captures the chosen devices, exports a complete snapshot to
  the registered VM repository, commits exact changed files and pushes. Capture,
  commit and push outcomes remain separate, with retry from the saved artifacts.
- **Save locally**, named checkpoints and an explicitly selected baseline support
  offline work and milestones. History, comparison and version ZIP downloads
  let the engineer retrieve an earlier configuration set.
- A restricted host Git helper runs Git as the registered Linux owner using the
  owner's external HTTPS authentication. It does not copy tokens into the manager.
- Repository changes, unexpected staged work and remote conflicts require
  attention; no force push, automatic stash or destructive reset is offered.
- Pending saves retain their context across restarts and block destructive manager
  cleanup until resolved or explicitly dismissed while keeping the snapshot.
- Version retrieval downloads files. Applying configurations to running devices
  is unavailable until the NOS restore adapters are validated.

Read [Save lab progress to Git](GIT-PROGRESS.md) for setup, buttons, architecture,
recovery and account boundaries. This remains a trusted-operator UI without
browser sign-in; a registered owner is a Linux execution identity.

## Changes in 1.14.0

- Sidebar order and labels follow the revised workflow; supported device types show
  the active release. View running lab details opens a wider inspection table.
- Topology opens first, followed by Nodes and Backup history; Credentials and
  Action logs are available from the More dropdown.
- Edit diagram adds movable text, boxes, circles and lines with appearance controls,
  Undo and unsaved-change protection. Save persists annotations in manager storage.
  Export current edits as annotations JSON or editable draw.io without changing VM files.
- Concurrent map edits fail with a clear conflict instead of overwriting a newer map.
- The master wiki now documents password setup, persistence, migration and recovery,
  and the updated UI. The VM password behavior from 1.13.0 is included.

## Changes in 1.13.0

VM connections now use a user-created password. First host setup prompts securely
for the clab-discovery account password before launching the manager. Enter that
same password in VM connection; it is encrypted in persistent storage. Routine
upgrades retain it, and --reset-password supports recovery. SSH restrictions now
apply to the account independently of client keys. Existing key connections require
one-time migration; device credential options remain unchanged.

## Changes in 1.12.1

- **Deploy New Lab** opens in the same tab. Choose the large **Lab Topologies**
  button to browse; no dialog opens automatically. **Back to lab manager** returns
  to the saved workspace.
- Only `.clab.yaml` / `.clab.yml` files and navigation folders appear in the browser.
- **Deploy lab** opens a concise confirmation, with the command in expandable details.
- **Start lab** and **Destroy lab** appear beside deployment status. Start deploys
  an absent lab or starts stopped containers. Destroy is separate from Remove lab.

See [1.12.1 update and build instructions](archive/UI-UPDATE-1.12.1.md). This is a source
release; the previously supplied Hub image `archtop/clab-backup:1.12.0` does not
include these changes. No new Hub image has been published by this workspace.

## Changes in 1.12.0

The workspace opens directly without an access-token login. VM and device SSH
credentials remain encrypted in persistent storage. Keep VM connection enabled
for discovery, automatic file import and reviewed lab commands.

- Retained: lifecycle commands, inspect/save, SSH all, favorites, VM projects,
  new project creation, optional repository downloads, backup history and SuperPuTTY.
- Removed: existing VM YAML editing, lab path/link/folder shortcuts, separate
  layout control, SSHX/GoTTY and fcli. VM project files open read-only.
- One interactive draw.io editor with full editable export: nodes, connections,
  interface labels, groups, notes, colors and positions. No online service needed.
- Inspect results appear as a table. VM projects use an expandable vertical tree.
- Topology header offers SSH all and Back up all configs, including expanded view.
- Right-click an excluded lab to clear its exclusion without importing it.
- Manager settings → Start fresh clears manager data and backup files after
  confirmation, retaining the VM connection and leaving VM labs/files untouched.

[VM connection setup and troubleshooting](VM-CONNECTION.md) covers passwords, permissions,
helper repair and upgrades. [Lab commands](LAB-OPERATIONS.md) documents retained actions.

## Setup and import improvements retained from 1.10.0

- **Source-build launch command:** `sudo bash deploy/start-manager.sh` updates the installed
  VM helper, verifies its file-transfer protocol and version, prepares storage,
  builds the image and recreates the Compose service. Existing passwords/data are retained.
  First setup prompts for the discovery account password. An old helper cannot silently
  survive a normal upgrade; verification failures stop before container recreation.
- **Import confirmation:** discovery reads files automatically and shows new labs as
  Ready to import. Clicking a lab previews its name, node/link counts, source files
  and warnings. Only **Import lab** saves the workspace and inventory credentials.
  Cancel saves no workspace. Import again also requires confirmation and retains
  the exclusion if cancelled. Existing saved workspaces remain available.
- Confirmation expires after five minutes and is rejected if files, VM connection or
  exclusion state change. Refreshes and older API clients cannot bypass confirmation.
- Outdated inspection-only helpers now show an actionable message in VM connection
  and the sidebar instead of appearing ready for automatic file import.

## Feature baseline retained from earlier releases

- **Remove lab** clears only that saved manager workspace and its history entries.
  It never stops containers or changes VM lab files. Backup files and audit logs
  remain on disk; other labs and the VM connection are retained.
- Removed labs are excluded from automatic import by default. Use **Import again**
  in the sidebar, or uncheck the exclusion in the removal dialog to test automatic
  discovery on its next check. Queued/running jobs must finish before removal.

- Automatic retrieval of deployed lab YAML, annotations, generated inventory and topology data, followed by import confirmation.
- File change detection and **Sync from VM**, preserving saved node settings, profiles and backup history.
- Helper upgrade with `deploy/setup-discovery.sh --update-helper` retains the password after first migration.
- Standalone Compose deployment with Linux host networking and automatic restart.
- Host directory `/srv/containerlab-node-manager/data` mounted at `/data`, using
  explicit UID/GID 10001 and a one-time setup script.
- Original `.clab.yaml` registration, optional annotation maps, and updates that
  preserve matching node identities, credentials, schedules and configuration history.
- Encrypted VM password settings, fixed read-only SSH discovery every 30 seconds,
  manual refresh, stored SSH fingerprint and changed-key rejection.
- Running, Partially running, Stopped, Not deployed, Unknown and Unlinked lab states.
- Automatic node management addresses with explicit manual endpoint overrides.
- Deployment-aware scheduling for linked labs; offline/unknown labs retain their
  data and wait until they are available. Existing inventory-only behavior remains.

The list and map both retain node details, per-node backups and browser SSH tabs.
SuperPuTTY XML exports use the lab name. Junos, IOS-XR and EOS backup adapters and
historical downloads remain. Host CPU/memory monitoring is not part of this release.
