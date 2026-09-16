# Student-first critique of DESIGN-SPEC.md (+ ADDENDUM + parity/*.md)

Lens: a CCNP student who has never seen the tool, and a UX lead scoring the spec against the brief's 12-point success standard, the seven journeys, "what should I do next", the status vocabulary, the danger-zone rules, empty/loading/error states, microcopy and the "things I do not want" list. The addendum says the parity files' fixes are accepted, so everything below is judged **after** those fixes. I do not repeat what parity already caught.

Score: **6.5 / 10**. The information architecture, vocabulary functions, banner, drawer and confirmations are the right shape and most journeys are 2–4 clicks. What still fails the brief: the first-ever save is undefined and heavy (Journey 3), a failed lab start is silent (Journey 2, standard 11), "n of m devices ready" lies when devices lack credentials, Destroy never says unsaved work is lost (standard 12), and "Instructor final state" is a folder-name guessing game (Journey 5, standards 8–9).

## Journey walk-through (clicks counted from Home)

| Journey | Path in the spec | Clicks | Unfamiliar words met | Verdict |
|---|---|---|---|---|
| 1 Resume | Continue card [Open lab] → Topology → rail [Open CLI] (or node → drawer → Open CLI) | 2–3 | none | Good |
| 2 Launch | card [Start lab] → review "Start <lab>?" → confirm → banner "Starting lab…" → header "Starting — 1 of 2 devices ready" → Ready → Open CLI | 3–4 | "Technical details" (collapsed) | Good while it works; **silent when the operation fails** (F3) |
| 3 Save | connected lab: [Save progress] → "Saving progress…" → "Saved to Git just now" | 1 | none | Good. **Unconnected lab: [Connect a save location…] → Progress tab → repository select → folder browser → tick devices → acknowledgement → [Connect] → back to header → [Save progress]** | 7+ | Repository, folder, "complete device configurations… uploaded" | **Fails the brief** (F1) |
| 4 Checkpoint | Progress → [Create checkpoint…] → type "OSPF complete" → **validation error** (spaces forbidden) → retype → confirm | 3 + retry | "letters, numbers, underscores or hyphens" | Friction (F9) |
| 5 Final state | Progress → Saved versions → scan a list of every folder in the repository incl. other labs → guess `reference/solution` → [Apply to running lab…] → tick ack → [Replace configurations] → result | 4 | folder paths, "reference/solution", "broken-01" | **Concept missing** (F5) |
| 6 Troubleshoot | red dot → click RTR3 → drawer "RTR3 is running, but SSH login failed…" [Check credentials] → Edit connection → save → … waits up to 60 s with no hint | 3 | none | Good until the fix; no "what happens now" (F15) |
| 7 Capture | Tools → [Capture traffic] → choose device → tick interface → [Start capture] → [Open Wireshark ↗] (from a link on the map: 3) | 3–6 | "Everything on the VM (bridges…)" only under Advanced | Good |

Screens vs the brief's student questions:

- **Home** answers "what lab / is it running / are routers ready / last save". It does not answer "what do I click to get my lab" cleanly: three sibling add-lab actions, one of them "Import an Ansible inventory…" (F6).
- **Lab header** answers name, state, readiness, progress, save, actions. "Not connected" as the progress text reads as *the lab* being disconnected (F12). "n of m ready" is wrong for credential-less devices (F4).
- **Topology + rail** answers "this is my network", "which router is ready", "how do I open one". Good. No loading state distinct from "no map" (F20).
- **Devices** answers readiness per device with an explanation sentence and Open CLI. Good.
- **Progress** answers "where is it saved / how do I go back" for a connected lab. Does not answer "which one is the instructor's" (F5) nor "how do I save the very first time" (F1).
- **Device drawer** answers name, platform, state, next action, CLI. Its "Configuration history" is VM backups, not the saved versions the tab next door calls "Saved versions" (F21).

## Findings (ranked)

### F1 — BLOCKER · §1.3 header / §2 `progressState` `unconnected` / §5.3 · The first save is undefined and is a 7-step Git setup
**Problem.** Journey 3's acceptance check only covers a lab that is already connected. For any lab without a binding the header's primary button reads "Connect a save location…" (git-progress.js:52 today: "Connect Git repository"). Parity GAP-J/GAP-M/GAP-H (accepted) route that click to Progress › Save location, where the student must: pick a repository in a select, open the folder browser, choose/create a folder, tick devices, tick "I understand that complete device configurations… will be saved to this repository and uploaded to its online copy", press [Connect], return to the header and press [Save progress]. That is the "Git architecture" the brief says the student must never need. A student in a class has no GitHub repository of their own; the instructor has usually registered one on the VM.
**Evidence.** Brief "SAVE PROGRESS MUST BE A FIRST-CLASS STUDENT WORKFLOW"; `POST /git/save` returns 409 without a binding (vocabulary.md §415); binding is one call, `PUT /labs/{id}/git {binding_id,node_names,review_before_push}` (git-progress.js:102).
**Fix.** Add §1.3 "First save": when `#git-save-progress` is clicked with no binding **and** at least one registered repository exists, open one dialog "Where should <lab>'s progress be saved?" — Repository (select, preselected when there is one), Folder (text, default `labs/<lab-id>` or the folder the instructor suggested, with a "Browse…" link that opens the folder browser), Devices (all supported ticked, collapsed under "Devices included"), the acknowledgement checkbox (GAP-U wording), [Save progress] → `PUT /labs/{id}/git` then `gitSaveProgress()`; total ≤ 3 clicks. When no repository is registered: dialog "Ask your instructor for the repository address, or paste it below" (= the existing connect-by-URL dialog) plus a secondary [Back up to this VM instead] (`#backup`). Add acceptance check 3b for the unconnected case and a `test_git_progress_ui.js` case that the dialog issues the PUT then the save.

### F2 — MAJOR · §1.6 Destroy / Redeploy / Stop · Confirmations do not say that unsaved work is lost, nor when the student last saved
**Problem.** Destroy copy: "The running devices are removed from the VM. Your saved progress and Git history remain. The generated lab folder is also removed (cleanup)." A student reads "saved progress remains" and destroys a lab with two hours of unsaved router config. Redeploy says it; Destroy does not. Neither shows the last-save time, which is the single fact that decides whether the action is safe. "(cleanup)" is containerlab jargon in a student dialog.
**Evidence.** Brief "Each one should answer: Will my work be lost? Can it be recovered?"; success standard 12.
**Fix.** Every lifecycle confirmation (destroy, redeploy, redeploy+cleanup, stop, restart) gets: line 1 the effect, line 2 "Configuration changes you have not saved are lost.", line 3 `progressState` in words — "Last saved 12 minutes ago to Git" / "Never saved" (danger-tinted when never saved or older than the last operation), and a secondary button [Save progress first] that closes the dialog and triggers `gitSaveProgress()` (hidden when unconnected). Destroy body: "The running devices are removed from the VM and the lab's generated folder is deleted. Configuration changes you have not saved are lost. Your saved progress, checkpoints and backups remain."

### F3 — MAJOR · §1.3 situational banner / §2 `labState` / §5.2 · A failed or interrupted lab operation is invisible
**Problem.** The banner list has "operation running" only. Operations parity G7 (accepted) stops the output modal from auto-opening for lifecycle actions. So when containerlab fails to deploy, the banner disappears, `labState` falls back to "Stopped · This lab is not running. [Start lab]" and the student loops on Start with no idea why. Success standard 11 ("understand when something is wrong") fails for the most common failure in a lab class.
**Evidence.** vocabulary.md §281: operation statuses `failed` ("Host command returned an error") / `interrupted`; `state.operations` carries them.
**Fix.** Banner case, placed right after "operation running": newest `state.operations` job for this lab with status `failed|interrupted` that is not dismissed → `.banner.danger` "Starting lab did not finish. [View output] [Try again] [Dismiss]" with the backend message under Details; dismissal remembered in `localStorage clab.opDismissed.<jobId>`; `labState` returns key `attention`, label "Needs attention" while undismissed so Home cards agree. Same for `restore_jobs` ending `failed|preflight_failed|interrupted`.

### F4 — MAJOR · §2 `labState` "n of m devices ready" · Devices without credentials vanish from the count and from the banner
**Problem.** `labState` takes ready/total from `nos_readiness`, but `node_readiness.summarize()` counts only nodes in `ready|booting|failed`; `needs_credentials` and `unavailable` are excluded (node_readiness.py:74-82). A 4-device lab where 2 devices have no login shows "Running · 2 of 2 devices ready" while the Devices tab lists two "Needs credentials". The `idle` case ("Devices are running.") is exactly the fresh-lab-without-credentials state and gives no next action. "Partially running" reuses "n of m" for a different quantity (running containers).
**Evidence.** node_readiness.py `summarize`; vocabulary.md §1.5 "Only nodes whose nos_login.status ∈ ready|booting|failed are counted".
**Fix.** `labState`: `total = lab.nodes.length`, `ready = nodes.filter(n=>n.ssh_ready).length`; detail "2 of 4 devices ready · 2 need login credentials" / "· 1 not running". New banner case (priority after needs-attention): "2 devices need login credentials before you can open their CLI. [Add credentials]" → `openProfile()` directly. `idle` label stays "Running" with that detail, never "Devices are running." Partially-running detail says "2 of 4 devices are running (containers)" only in Advanced; the header always uses the ready count.

### F5 — MAJOR · §1.3 Progress › Saved versions / §5.5 · "Instructor final state" is not a concept; the list is every folder of every lab
**Problem.** The brief's Journey 5 is "Selects Instructor Final State". The spec offers "Other saved states in this repository: every other folder that has a `latest/`", i.e. the audit's list reborn as an inline section: in lab clabllm-dev the student sees `bgp-core/reference/broken-01`, `bgp-core/reference/solution`, `bgp-core/reference/start`, `bgp-core/work`, `ARISTA-LAB-TEST`, `labs/BGP-LAB/reference/…` (screenshot 06b). Nothing says which is theirs, which is the instructor's, or that "solution" means final state. Standards 8–9 depend on this.
**Evidence.** shots/before/06b-git-load-dialog; spec §1.3 item 2.
**Fix.** (a) Scope: first section "Instructor and reference versions" = folders under the lab's parent folder (for `labs/BGP-LAB/work` → `labs/BGP-LAB/*` except itself), then a collapsed "Other labs in this repository". (b) Names: row title from the last segment through a small map — `solution|final` → "Final state (instructor)", `start|base|initial` → "Starting state", `broken-<n>` → "Troubleshooting scenario <n>", else the folder name; full path as a caption. (c) One sentence under the heading: "Versions your instructor put in the repository appear here. Apply one to load it onto your running devices; the current configuration is backed up first." (d) `Baseline` row gets "the reference version set for this lab" so students do not confuse it with "Starting state". (e) Add to `inventory/vocabulary.md`.

### F6 — MAJOR · §1.2 Home secondary actions · Home exposes "Ansible inventory" and three look-alike add-lab actions
**Problem.** The landing page's secondary row is [Deploy a new lab] [Import lab files…] [Import an Ansible inventory…] plus the "Also running on the VM · Import" list. A first-time student cannot tell which one gets them their lab, and "Ansible" is on the brief's list of things the student may not understand. Four different "Import" verbs exist across Home and Topology.
**Evidence.** Brief "PRIMARY USER: may NOT understand … Ansible"; "Do not put … advanced configuration prominently on each card".
**Fix.** Home row = [Deploy a new lab] only. "Import lab files…" and "Import an Ansible inventory…" live under Manager ▾ (already there) and as a "Have lab files instead?" link inside the deploy dialog (`#home-import`, `#home-import-inventory` keep their ids there). Discovered-lab action reads "Add to My labs" (matches parity D1 "Add lab"); "Import" is reserved for file uploads; the map keeps "Import map…".

### F7 — MEDIUM · §1.3 header `details#git-save-menu` · The header's save menu still has the audit's 8 mixed items
**Problem.** UX-AUDIT §3 flagged the 8-item Save menu; the spec keeps all 8 in the header (relabelled, grouped by GAP-A). "Update from the repository", "Upload saved progress", "Set baseline…", "Load a saved version…" are Progress-tab tasks, not header tasks. The brief: "Avoid five or ten competing buttons."
**Fix.** Header ▾ = Create checkpoint… · Save on this VM only · Saved versions & history · Save location settings… (4). The other four stay reachable on the Progress tab (status-card More ▾ / Advanced repository details) as the `data-git-action` owners per the addendum's proxy rule; no value disappears.

### F8 — MEDIUM · §5.3 / git-progress.js:181 · Every plain Save pops the job modal
**Problem.** `gitSubmitSave` opens `gitShowJob` after submit; the spec's Journey 3 describes a header-only "Saving progress… → Saved to Git just now" but never says the modal stops opening. Result: the calmest action in the app interrupts with a dialog each time (the same problem operations G7 fixed for lifecycle actions).
**Fix.** State in §1.3/§4: for the plain [Save progress] path the dialog is not opened; `#lab-progress`, `#worker-state`, the status card and a toast carry the phases (the 4 s `/state` poll already contains git jobs, so no new watch is needed); the job dialog opens automatically only when the job ends in `attention|failed|interrupted|review_pending`, and on demand from [Details]. Checkpoint/baseline saves show a toast "Checkpoint 'OSPF-done' saved."

### F9 — MEDIUM · §1.3 Progress [Create checkpoint…] / Journey 4 · The brief's own checkpoint names are rejected
**Problem.** Backend regex `[A-Za-z0-9][A-Za-z0-9_-]{0,99}` (git_progress.py:672) rejects "OSPF complete" and "OSPF working before BGP" — both examples in the brief. The accepted GAP-R help ("Letters, numbers, underscores or hyphens") turns the game-like "name your milestone" into a validation error on first use.
**Fix.** Sanitise on input: whitespace → `-`, drop other characters, show a live line "Saved as: OSPF-complete"; put the free-text sentence in the existing `note` field labelled "What did you get working? (optional)"; validation message "Use letters, numbers, - or _ (spaces become -)". Row label in Saved versions shows the note when present.

### F10 — MEDIUM · §1.3 Tools · "Lab files" and "Export sessions" are not student tools; Lab files can deploy another lab
**Problem.** Tools › "Lab files" opens the same `op-browser` as "Deploy a new lab"; clicking a `.clab.yaml` opens the viewer whose primary button is [Deploy lab]. A student "looking at files" can start a second lab. "Export SuperPuTTY sessions" is a niche Windows-tool export sitting next to Packet capture and Telemetry.
**Fix.** Move both cards to Advanced (Lab source & deployment). Tools shows Packet capture, Telemetry, Configuration backups, Open all CLIs, Map. When `opBrowse` is opened from a lab (parity G9 title "Lab files · <lab>"), the file viewer hides [Deploy lab] and [Add to My labs without starting] and shows "Viewing this lab's files. Deploying is under Manager ▾ › Deploy a new lab."

### F11 — MEDIUM · §1.3 Tools › Telemetry · "status line from `lab.telemetry.status` in words" has no words
**Problem.** Seven backend values (`unmonitored, disabled, unsupported, streaming, failed, partial, waiting`, vocabulary.md §200) and the spec supplies only "Telemetry is not installed on this VM." Operations parity G14 rewrites the settings *dialog* summary, not the card line.
**Fix.** Add to §2 `telemetryLine(status, counts)`: streaming "Collecting live data from n devices."; partial "Some devices are not reporting — open Telemetry settings."; waiting "Waiting for devices to finish starting."; failed "k devices could not be set up for telemetry. [Telemetry settings…]"; unsupported "None of this lab's devices support telemetry."; disabled "Telemetry is off for this lab. [Turn on…]"; unmonitored "Available once the lab is running on the VM."; stack unavailable "Telemetry is not installed on this VM." + setup link.

### F12 — MEDIUM · §1.3 header `#lab-progress` / §2 `progressState` · "Not connected" reads as the lab being offline
**Problem.** The status line renders "Running · 2 of 2 devices ready · Not connected". Two words earlier the student read "Running"; "Not connected" next to it means "my lab is disconnected".
**Fix.** Label "No save location yet" (pill neutral), detail "Choose where this lab's progress is saved."; Home card "Not saved anywhere yet"; the word "connected" is reserved for the VM.

### F13 — MEDIUM · §0.5 / opTask(null,…) · Header-action failures are 5-second toasts of raw backend text
**Problem.** `#git-save-progress`, Lab actions ▾ items and Tools buttons run through `opTask(null, fn)`, whose failure path is `notify(message)`. Backend 409s such as "Configured devices changed. Review the Git repository device selection." or "Reconnect the original VM before saving progress." flash for 5 s and vanish; the student cannot open Details. Operations G4 fixes this for lifecycle items only.
**Fix.** Rule in §1.3: any failure from a header/menu/tool action renders a dismissible `.banner.danger` in `#lab-banner` with a student sentence and the raw message under Details; map the git/save messages ("The devices in this lab changed since the save location was set up. Check the devices under Progress › Save settings." / "This lab was set up on a different VM. Reconnect that VM before saving.").

### F14 — MEDIUM · brief "JOB STATUS" / §2 `progressState` busy phases · No per-device progress while saving
**Problem.** The brief's example is "Saving lab progress — RTR1 ✓ RTR2 ✓ RTR3 Saving…". The spec gives phases only ("Reading device configurations…"). A 12-device lab shows one sentence for a minute.
**Fix.** While the git job is `capturing`, the banner/job dialog reads the linked backup job (`backup_job_id` in `state.jobs`, already polled) and renders per-device rows with the `badgeLabel` vocabulary; no new polling loop.

### F15 — MEDIUM · §1.4 drawer Status / §5.6 · After fixing credentials nothing tells the student what happens next
**Problem.** The automatic monitor retries a `failed` device every 60 s (vocabulary.md §172); after the student saves a new credential profile the drawer still says "Needs attention" for up to a minute. "Test login" is under the collapsed Advanced section.
**Fix.** Status section for `attention` shows two actions: [Check credentials] (opens Edit connection with the credential select focused) and [Test login now]; after any credential/connection save the sentence becomes "Checking RTR3 again… (automatic within a minute — or Test login now)".

### F16 — MINOR · §1.3 Lab actions ▾ Lifecycle group · "Redeploy lab" sits with Start/Stop but destroys unsaved work
**Fix.** "Redeploy lab…" with `.menu-reason` "Unsaved changes are lost — you will be asked to confirm", or move it to the Danger group beside "Redeploy and clear the lab folder…".

### F17 — MINOR · §1.5, §2, §1.3 banner, parity OPS-05 · Vocabulary leaks and inconsistencies that survive the addendum
- "routers" throughout restore copy while the lab contains switches (SW1 is vJunos-switch) — use "devices".
- `labState` working label "Applying topology" — "Updating the lab from its topology file".
- `unlinked`: "Not linked" / "This workspace is not linked to a running lab. [Link deployment]" — "Not matched to a running lab" / "The manager cannot tell which lab on the VM this is. [Match to a running lab…]".
- `deviceState` unavailable "…or the VM status is stale" → "…or the lab status is out of date"; unmonitored "Manual connection." → "Connected with the saved address."
- Destroy body "(cleanup)" → drop the parenthesis.
- "Start lab" (menu) vs "Deploy lab" (All lab operations dialog) for one action → "Start lab (deploy)".

### F18 — MINOR · §1.2 · Four different "Import" actions (see F6) and the leftover editing notes
Spec §1.2 contains "Hidden when only one lab exists and… no: shown whenever a last-opened lab exists" and "— simpler: …"; §1.3 Advanced "plus `#sync-vm`… no —". An implementer cannot tell which sentence wins. Also: with exactly one lab the Continue card and the lab card are the same lab twice. **Fix.** Clean the text; when `labs.length===1` render the Continue card only.

### F19 — MINOR · §3 skeleton / addendum C · The map has no loading state
Until the first `/topology` answer the stage is blank, indistinguishable from "No map for this lab yet". **Fix.** `.topology-stage` shows a skeleton block + "Loading map…" while `drawing===undefined`; the empty state only when `drawing===null`.

### F20 — MINOR · §1.4 · Drawer "Configuration history" is VM backups, one tab away from "Saved versions"
**Fix.** Caption "Backups kept on this VM by the manager. Progress saved to Git is under the Progress tab." and rename the section "Backups of this device".

### F21 — MINOR · §1.2 lab cards · Progress attention never reaches the card
Cards show only "Last saved <relative>". **Fix.** When `progressState.key ∈ {attention, failed, interrupted, local}` show its label instead ("Saved on this VM — upload needs attention").

### F22 — MINOR · §1.3 Topology More ▾ "Back up all configurations" · A confirmation for a safe action
The backup-all review is a dialog for a read-only-safe action (brief: confirmation fatigue). **Fix.** Keep the dialog only when devices will be skipped (it then informs); otherwise start immediately with the toast "Backing up 2 devices…".

## What the spec gets right for a student (keep)
- One header: name · state pill · "n of m devices ready" · progress · [Save progress] [Lab actions ▾]; five tabs in the brief's order; Home with a Continue card and skeletons.
- `status.js` pure vocabulary with priority tables and sentences that name the device and the next action; "Ready" ambiguity resolved in the addendum.
- Situational banner with a priority order and actions (Retry, Check credentials, Start lab, VM connection).
- Topology is the tab: state dots, left-click opens the drawer, device rail with Open CLI, honest caption "Lines show how the lab is wired, not whether links are up", link-click capture kept.
- Device drawer: primary row (Open CLI / Capture traffic / Back up configuration), status sentence + Details, Advanced for Test login / Edit connection.
- Danger grouped and styled; destroy/redeploy/disconnect copy says what persists; restore review keeps the acknowledgement and the three safety guarantees; twelve restore outcomes stay distinct.
- Honest "Compare with latest save" rather than a false "compare with current".
- Empty states taken from the brief; hash routing so the back button works; proxy pattern so no id is duplicated.
