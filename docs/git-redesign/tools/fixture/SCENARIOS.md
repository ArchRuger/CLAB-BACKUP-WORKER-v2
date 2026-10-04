# Fixture scenarios for the Git save and load redesign

The fixture is the real application on a scratch data directory (`docs/redesign/tools/fixture_manager.py`) with three scripted
edges: the VM Git helper (`fake_git.py`), the devices (`fixture_devices.py`) and the capture (`fixture_backups.py`). Nothing
reaches a VM, a device or live data. Everything it shows is **fixture evidence**; it says nothing about a real NOS or a real GitHub.

```bash
cd <checkout>
FIXTURE_DATA=$(mktemp -d) clab-backup-ui/.venv/bin/python docs/redesign/tools/fixture_manager.py --port 8191   # ports 8191 to 8199 for this work
clab-backup-ui/.venv/bin/python docs/git-redesign/tools/fixture/check_fixture.py        # starts its own copies, asserts every scenario below (about 80 s)
```

`--classic` seeds only the four labs and the `Course-Labs` repository the first fixture had. Restart the fixture after any `app/*.py`
change and use a **fresh `FIXTURE_DATA` per run** (and per QA worker: one fixture per port). Lab ids change per run
(`GET /fixture/state` -> `labs`); names and registration ids do not.

Five things every QA worker needs to know before the first click:

1. **A scenario consumes the fixture.** Placing a lab, saving, uploading and loading change the repositories, the bindings and the devices
   for good. `reset` (below) clears the switches and puts the devices back; it does not undo a save, a placement or a load. For a clean
   start of a state, restart the fixture on a fresh data directory. Do the *first-save* states (F12, G08, the first-save default) before any
   other lab saves into its repository.
2. **The chip's "Can't save" state is only as fresh as the last time the manager asked the helper.** The 4 s poll never asks. The code
   (`lab.git_status.code`) changes when you press **Save**, **Upload** / **Try again**, **Update from the repository**, open **Save settings**
   (the settings read), or place the lab. Set a switch, then do one of those; reloading the page changes nothing.
3. **The manager keeps the helper's tree, history and states for 10 s per repository** (`CHECKOUT_VIEW_SECONDS`). After a switch or a
   placement, a panel that lists folders or states can show the old answer for up to 10 s; a placement and a save clear it themselves.
4. **A save takes 6 s to capture** (`capture_seconds`, default 6): set 1 to go fast, 30 to hold the *Saving…* state for a screenshot.
   A *slow* load takes about 20 s for four devices.
5. **The default repository of a first save is the manager's choice, not the fixture's.** It is the repository the lab used last, else the
   one any save used most recently, else the first by name (`Archtop-Lab`, the owner's standard install, registered at its top level
   only). A fresh fixture therefore offers `Archtop-Lab` to `square-fresh`; as soon as another lab has saved into `Nested-Labs` that
   repository is the default. `prefer_repository` (below) puts it back.

## Files

| File | What |
|---|---|
| `fake_git.py` | `FakeGit`: the helper as redesigned (H1 to H7), several checkouts, journals, a fake remote; imports the real helper's pure rules and fixed sentences from `app/host_git.py` |
| `fixture_content.py` | device configurations (EOS, IOS XR, Junos set + hierarchical), manifests, topologies |
| `fixture_devices.py` | the device model, the scripted restore driver and connector (the real restore service runs on top) |
| `fixture_backups.py` | the capture that reads the device model, with the real `Runner.embed_topology` |
| `fixture_scenarios.py` | the seeding below |
| `fixture_control.py` | the control (below) |
| `check_fixture.py` | the self-check: five sections, each on its own fresh fixture (`--only seed,places,saves,causes,helper`), no SKIP |

## The control (one mechanism: three routes mounted by the fixture, outside `/api/`)

```
GET  /fixture/state    switches, devices (outcome, armed), repositories (head, waiting commits, registrations), labs
POST /fixture/switch   {"name": value, ...}   null or false clears; "name@Repository" scopes a switch to one repository
POST /fixture/action   {"action": "...", ...}
```

From Playwright: `page.request.post(BASE + '/fixture/switch', data={...})`. From a shell:

```bash
FX=http://127.0.0.1:8191; C=docs/git-redesign/tools/fixture/fixture_control.py
python3 $C $FX switch capture_seconds=1 push_fail_once=true        # several at once; `name=null` clears
python3 $C $FX action '{"action":"lab_state","lab":"restore-square","state":"stopped"}'
python3 $C $FX state
```

These routes need no `Origin` header and are not part of the application.

### Switches

| Switch | Effect |
|---|---|
| `vm_unreachable` | every Git helper call fails the way an unreachable VM does (`Cannot reach the VM Git helper...`): chip code `vm` |
| `status_problem` | what the checkout answers, **where the real helper would** (table below). Scope: `status_problem@Nested-Labs` |
| `remote_unreachable` | the remote cannot be asked: push fails (`The remote branch is unavailable...`, code `account`), `compare.outgoing` is `null`, update, retire and a new folder refuse |
| `remote_ahead` | the remote has a commit this VM lacks: a push is refused as diverged (code `diverged`), a new folder beside waiting saves is refused, `update` fast-forwards when nothing waits. A **Save** made while nothing waits in that repository fast-forwards first (the manager calls `update` before the save's first publication), so the switch is used up and the upload then works; set it AFTER the save to see the diverged upload |
| `push_fail_once` | the next push fails (`...saved on the VM, but push failed...`, code `account`), then the switch clears itself: the *Upload failed* state |
| `push_refused` | every push fails the same way until cleared (no permission); a new folder cannot be registered either (the push probe fails) |
| `no_repositories` | `list` answers no repository (the first save asks for an address); cleared by the first `connect` |
| `list_first` | repository name to list first (only the order of the helper's list; the manager's default does not read it) |
| `unreadable_states` | folder paths whose history `summary` is `null` (the state still lists, loads through the preflight, counts unknown) |
| `initialize_fails` | starting an empty repository fails with the helper's sentence (`The manager could not start the repository; connecting again retries it.`) |
| `capture_seconds` | length of a capture (Save), default 6: set 1 for speed, 30 to hold *Saving...* |
| `restore_capture_seconds` | length of each safety backup of a load, default 2 |
| `device_unreadable` | devices (short or full name) a capture cannot read: Save ends `capture_incomplete` (*could not be read*) |
| `load_preset` | `all-ok`, `one-failed`, `one-rolled-back`, `one-uncertain`, `one-unreachable`, `one-blocked`, `one-editing`, `one-bad-login`, `slow` |
| `load_device` | device the `one-*` presets act on (default `xrv9k`) |
| `load_script` | `{device: outcome}` for any mix; outcomes `failed rolled_back uncertain unreachable blocked blocked-editing bad-login slow ok` |
| `load_seconds` | for `slow`: device k of the lab settles after k times this (default 5: about 20 s for four) |

`status_problem` values (the sentence is the helper's own; the stage says which modes raise it, as in `host_git.py`):

| Value | Sentence says | Stage: stops | Chip code | What it is in the real helper |
|---|---|---|---|---|
| `staged`, `edits`, `operation` | someone is working in the repository | `clean`: status, publish, move, update, an upload's last check. **Not** history, browse, read-version, compare | `busy` | staged changes, unsaved edits in the save's folder, an unfinished Git operation |
| `settings` | `The repository branch changed...` | `validate`: every mode; status answers no `head` | `settings` | the checkout left its registered branch |
| `files` | `Existing snapshot files no longer match...` | `manifest`: status and publish | `files` | files the manager did not save in `latest`, `baseline` or a checkpoint |
| `identity` (alias `permission`) | `Git commit identity is missing...` | `write`: publish and move only; status stays ready, the **save** meets it | `account` | the VM account has no Git identity |
| `diverged` | `The remote branch advanced or diverged...` | `clean` | `diverged` | **fixture shortcut**: the real `status` never says this; it is the answer of a failed upload or update. The real thing is `remote_ahead` |
| any other text | that text | `clean` | `other` | |

Because history and browse are not stopped by `busy` causes, the Load panel and the folder chooser keep working while Save says *Someone is working in this repository*.

### Actions

`helper` (a raw helper request, `{"repository": "reg-bgp", "request": {"mode": "history"}}`; answers the helper's answer or `{"error": sentence}`),
`edit_device` (`device`, `add: [lines]`, `remove: [lines]`: the next Save reports exactly this; **use the full name** `clab-edge-lab-r1` for the two-device labs, whose `r1`/`r2` repeat),
`device_config` (`device`, `tag`: `start broken ospf-up loopbacks-reachable latest final other baseline`),
`lab_state` (`lab`, `state: running|stopped`),
`hand_commit` (`repository`: a commit nobody journaled; the next upload is refused, a new folder in that repository is refused),
`remote_readme` (`url`: someone adds a README on GitHub to an empty repository, so the next connect finishes the clone),
`prefer_repository` (`repository`: `Archtop-Lab`, optional `lab`, default `square-fresh`: make that checkout the one the manager offers the lab first),
`reset` (clears every switch and restores the devices; **not** saves, placements or loads).

The two edits that make *two devices changed, 5 lines added, 1 removed* (G11 and F04):

```bash
python3 $C $FX action '{"action":"edit_device","device":"ceos","add":["   ip route 0.0.0.0/0 10.0.0.1","   ip route 10.1.1.0/24 10.0.0.1"],"remove":["   no switchport"]}'
python3 $C $FX action '{"action":"edit_device","device":"xrv9k","add":[" router static","  address-family ipv4 unicast","   0.0.0.0/0 10.0.0.1"]}'
```

## Labs

| Lab | State |
|---|---|
| `restore-square` | four devices `ceos` (EOS), `cjunosevolved`, `vjunos-switch` (Junos), `xrv9k` (IOS XR), running, Ready. Saves to `BGP` in Nested-Labs. Its newest save, *Interface descriptions cleaned up*, is uploaded and 21 minutes old; the devices run it |
| `square-fresh` | the same four devices, running, Ready, **never saved**, no save location. The first-save lab |
| `edge-lab` | 2 EOS devices (`clab-edge-lab-r1`, `-r2`), saves to `BGP/edge` (inside `BGP`) |
| `shared-a` / `shared-b` | 2 EOS devices each. `shared-a` saves to `shared`; `shared-b` is not connected and wants it |
| `solo-lab` | 2 EOS devices, saves to the top level of Solo-Lab (another repository: its saves never meet the Nested-Labs ones) |
| `BGP_TheoryToPractice`, `vlan-lab`, `ospf-basics` (stopped), `switching-basics` | the first fixture's labs and its `Course-Labs` saves (`labs/BGP/work`, `labs/VLAN`), unchanged |

Device captures of the six new labs are deterministic (a second Save with nothing changed is `unchanged`); the first fixture's labs keep their drifting captures (every Save is a change).
At start every device of `restore-square` and `square-fresh` runs the configuration of the lab's own newest save (`latest`).

## Repositories (registration ids are fixed)

| Repository | Registrations | Content |
|---|---|---|
| `Archtop-Lab` | `reg-archtop` at the **top level only**, no lab connected | README, `notes/`, `Examples/` (ordinary files); `Course/start|broken|final/latest` made from `square-fresh`, marked `state` Start, Broken, Final (Start is view only) |
| `Nested-Labs` | `reg-bgp` (`BGP`, restore-square), `reg-bgp-edge` (`BGP/edge`, edge-lab), `reg-shared` (`shared`, shared-a), `reg-unused` (`old-lab-folder`, no lab) | see below |
| `Solo-Lab` | `reg-solo` (top level, solo-lab) | one save |
| `Big-Repo` | `reg-big` (top level) | 5000 files in about 300 folders (`docs/week-NN/topic-NNN`); states `zz-states/start|broken|final/latest` (marked) sort after the 4000th file |
| `Course-Labs` | `reg-work`, `reg-vlan` | the first fixture's content |
| `New-Empty` | not registered; reachable by `https://github.com/ArchRuger/New-Empty.git` | no commits yet: asked for `{question: {kind: 'empty'}}`, started by `initialize` |
| `Late-README` | not registered; `https://github.com/ArchRuger/Late-README.git` | empty until the `remote_readme` action; then a connect finishes the clone with no question |
| `Spare-Lab` | not registered; `https://github.com/ArchRuger/Spare-Lab.git` | README only (connects). Any other unknown address connects as a repository with a README; an address containing `forbidden` is refused (the account cannot push), `missing` is refused (`Cloning failed`) |

`Nested-Labs` holds, under and beside `BGP`:

| Path | What |
|---|---|
| `BGP/latest`, `BGP/baseline`, `BGP/checkpoints/ospf-up`, `.../loopbacks-reachable` | the lab's own saves: a latest save (uploaded, named *Interface descriptions cleaned up*), a starting point, two checkpoints, three latest saves and six commits in history |
| `BGP/start/latest`, `BGP/broken/latest`, `BGP/final/latest` | course states in `latest` layout with `state: Start|Broken|Final` in their manifests. **Start has no restore artifacts (view only)**. Final equals `latest` on the two Junos devices (*Already matches*) and differs on EOS and IOS XR |
| `Final` | a state stored directly in a folder (`Final/manifest.json`, flat layout), **no mark**: it is named `Final · Top level` beside `Final · BGP` |
| `BGP/junos-only/latest` | a state covering 2 of the lab's 4 devices |
| `BGP/other-topology/latest` | saved on a different topology: its topology file has other links and a node `ceos2`; 3 of its 4 devices match the lab |
| `BGP/checkpoints/plan-sept` | a design export (`kind: network-design`, no devices, view and download only) |
| `BGP/legacy` | a manifest that cannot be read (`summary` is `null`; it lists, counts unknown) |
| `BGP/notes.md`, `BGP/exercises/`, `notes/`, `notes-old/` | ordinary files beside saved states (`notes-old` exists to show Git's tree order: it sorts before `notes`) |
| `BGP/edge/latest`, `shared/latest` | the saves of the other labs |

A state made by **Save as a lab state…** writes `state: <name>` into its manifest, so every lab lists it as a lab state under that name (group `state`), the lab that saved it included.

## PROMPT section 5: how to reach each state

Open the lab (name in the first column of every table), do the setup (shell commands above), then the clicks. `C` and `FX` are the variables defined above.
Controls are named as in PROMPT section 5: the chip, **Save**, **Load**, the chip panel and its buttons.

### Header and chip states (5.2, 5.3)

| Board / chip state | Lab and setup | Clicks |
|---|---|---|
| **G01** header at rest, **G10** chip panel at rest, chip *Saved 21 min ago* | `restore-square`, as seeded | open the lab; click the chip. The panel reads the save's name, `Running: your latest save`, `Uploaded: yes, to github.com`, then **All versions**, **Save as a lab state…**, **Save settings** |
| **F02** *Saving…*, Save disabled | `restore-square`, `capture_seconds=30` | **Save**. Chip pulses; panel *Reading the configuration of 4 devices*. Clear the switch (`capture_seconds=null`) before the next scenario |
| **F14** nothing changed | `restore-square`, as seeded, `capture_seconds=1` | **Save**. Toast *Nothing changed since your last save.*; chip stays *Saved* |
| **G11** *Waiting*, the upload prompt opens by itself | `restore-square`, `capture_seconds=1`, the two `edit_device` commands above | **Save**. Chip *1 save to upload*; panel *2 devices changed since your last save: ceos and xrv9k. 5 lines added, 1 removed.* with **Upload**, **Not now**, **See changes** |
| **F04** *What changed* drawer | as G11 | in the panel click **See changes**: one entry per device (ceos, xrv9k) and one each for the topology and the map only when they changed (not here); the real line diff; Upload / Not now at the top |
| **F05** uploaded | as G11 | **Upload**. Chip *Saved*, toast *Uploaded to github.com.* |
| *Waiting*, kept (the "Not now" state) | as G11 | **Not now**. Panel closes, chip stays *1 save to upload* |
| *Kept on this VM* | as G11 | chip panel, the save's **Details** → **Keep snapshot only** (confirm). The save is dismissed but still goes up with the next upload |
| **F06** name and **Keep as a checkpoint** | as G11, after Save | the panel shows the name (`ceos and xrv9k changed`, written by the manager) in an editable field: type `Routes added`, Enter (rename: the commit is untouched, empty returns to the automatic name). Tick **Keep as a checkpoint**: the folder is `routes-added` (`-2` when taken); no device is read again, and only `checkpoints/routes-added` is written (the helper's `checkpoint_only`): keeping an OLDER save as a checkpoint leaves `latest` as the newest save wrote it |
| **F13** *Upload failed* | as G11, plus `push_fail_once=true` | **Upload**. Chip *Upload failed*, *Your save is safe on the lab VM*; **Try again** (works: the switch cleared itself) and **Details**. For a persistent failure use `push_refused=true` instead |
| **F12** *Not saved yet*, first save | `square-fresh` (fresh fixture: nothing saved elsewhere) | chip *Not saved yet*; **Save**. Panel *Your first save goes to Archtop-Lab, in a folder named square-fresh.* with **Save**, **Choose another place**. **Save** places the lab (no question) and saves; the chip then says *First save* waiting (the name the manager wrote). The default is `Archtop-Lab`: see point 5 above |
| **F12** with no repository on the VM | `square-fresh`, `no_repositories=true` | **Save**: the panel asks for the repository's HTTPS address in one field. Paste `https://github.com/ArchRuger/Spare-Lab.git` (connects, then saves in `square-fresh`). `New-Empty.git` → *This repository has no commits yet* with **Start the repository**; `Late-README.git` the same until `remote_readme`; `...forbidden-x.git` and `...missing-x.git` are refused with the helper's sentence |
| **F15** Save settings drawer | any lab with a save location | chip panel → **Save settings**: where the lab saves, **Change folder…**, **Use a different repository…**, **Connect by URL…**, devices, Git details (Refresh status, Update from the repository), **Disconnect this lab…** |
| **F11** All versions | `restore-square` | chip panel → **All versions**: groups *Your saves*, *Checkpoints*, *Starting point*, *Lab states* (Start, Broken, Final · BGP, Final · Top level, Junos-only, Legacy, Other-topology, plus any you saved), folded *other labs* (Edge, Shared) |
| **F16** narrow header | any lab at 1280, 1024, 760 and 390 px wide | chip and Save on the first row, nothing overlaps; 1280 and wider: chip, Save, Load, Lab actions on one row |

### Can't save (5.2, 6.5, DESIGN 3.6): one row per cause

Set the switch, then press **Save** (or open **Save settings**): the chip changes only when the manager asks (point 2). Use `solo-lab` (a quick two-device save) or any lab. Clear the switch, press **Try again**.

| Cause (chip sentence of DESIGN 3.6) | Setup | Chip code | Clicks and what follows |
|---|---|---|---|
| The VM cannot be reached | `vm_unreachable=true` | `vm` | **Save** → *The lab VM could not be reached.* **Try again**, **Check the VM connection…** |
| The VM account cannot upload | `push_refused=true` (needs a waiting save: do G11 first) | `account` | **Upload** → push failed. **Try again**, **Details** |
| The VM account cannot commit | `status_problem=identity`, change a device | `account` | **Save** → the save stops after its capture (`export_pending`), chip *Can't save*. Clear and **Try again**: the capture is reused |
| The remote cannot be reached | `remote_unreachable=true` (a waiting save) | `account` | **Upload** → *The remote branch is unavailable...*; the review (**See changes**) still opens and says nothing about other saves (`outgoing` null) |
| Someone is working in the repository | `status_problem=staged` (or `edits`, `operation`) | `busy` | **Save** → *Someone is working in this repository on the VM.* The Load panel still lists states |
| The online copy has changes this VM lacks, nothing waits | `status_problem=diverged` (shortcut) or `remote_ahead=true` then **Update from the repository** (Save settings) | `diverged` | chip *The online copy has changes this VM does not have.* with **Update from the repository**; with `remote_ahead` the update fast-forwards. With `remote_ahead=true` and nothing waiting, **Save** alone is enough: the save fast-forwards first and its **Upload** ends *Saved* |
| ...while saves wait here | G11 (the save is made first), then `remote_ahead=true` | `diverged` | **Upload** → refused, nothing forced; *both have changes the other does not have*, **Details**. **Update from the repository** is not offered while a save waits |
| Files the manager did not save | `status_problem=files` | `files` | **Save** → *<folder> holds files that were not saved by the manager.* **Choose another place**, **Details** |
| The checkout left its registered branch | `status_problem=settings` | `settings` | **Save** → the save location has to be set up again; **Save settings**. Every mode refuses, so the Load panel is empty too |
| A device cannot be read | `device_unreadable=["xrv9k"]` | none (the job is `capture_incomplete`) | **Save** → *xrv9k could not be read, so nothing was saved.* **Try again**, **Save settings** (leave it out), **Details** |
| No save at HEAD | G11, then `hand_commit` `{"repository":"Nested-Labs"}` | none | **Upload** → *Another save was made in this repository. Look at the changes again.* The review then shows no save of the manager at HEAD; **Upload** → *The repository on the VM has changes the manager did not make.* A **Save** on top of the hand commit is refused at upload as made up of commits created outside manager saves (`diverged`), and a new folder is refused with *This checkout has commits that were not made by manager saves.* |
| Something unlisted | `status_problem` = any sentence | `other` | **Save** → the sentence, as is |

### Two labs, one upload (3.4) and the folders that move

| State | Lab and setup | Clicks |
|---|---|---|
| A second lab's save while the first waits | `restore-square` and `edge-lab` (both in Nested-Labs), `capture_seconds=1`; edit `ceos` of restore-square and `clab-edge-lab-r1` of edge-lab | **Save** in restore-square (waits), then **Save** in edge-lab: not refused. Each panel says *This upload also sends 1 other save: …*; **See changes** names it (`kind`, lab, name) |
| One upload carrying both | as above | **Upload** in either lab: both end *Saved*; the push is always of the newest save, and the other lab's chip drops to *Saved* at its next poll |
| A commit the manager does not hold in the upload | as above, plus `hand_commit` `Nested-Labs` before the second save | the review names `Edited by hand` with its files (`by-hand.txt`); the upload is then refused (outside manager saves) |
| Upload bound to the HEAD shown | as above | open **See changes**, save in the other lab, then **Upload** in the first review → *Another save was made in this repository. Look at the changes again.* and the review shows again |

### Loading (5.4)

| Board / state | Lab and setup | Clicks |
|---|---|---|
| **G02** Load panel | `restore-square` | **Load**: groups *Your saves* (latest, newest checkpoints), *Lab states* (Start **View only**: no restore data; Broken, Final · BGP, Final · Top level, Junos-only `2 of 4 devices`, Other-topology, Legacy), then **All versions**, **Browse the repository…** |
| **G03** load confirmation | `restore-square`, no preset | **Load** → *Final · BGP*: *Load Final?* with one row per device: `ceos` and `xrv9k` *N lines differ*, the two Junos devices *Already matches*; **Load** (danger), **Cancel**, **See what's different** |
| **G07** *Not in this state* (greyed) | `restore-square` | **Load** → *Junos-only*: `ceos` and `xrv9k` greyed *Not in this state* |
| Saved on a different topology | `restore-square` | **Load** → *Other-topology*: one line *Saved on a different topology: 3 of 4 devices match.* with **View its topology**; the fourth device is not offered |
| View only | `restore-square` | **Load** → *Start*: row disabled, `View only`, the reason (no restore data). A design export (`plan-sept`) is view and download only |
| Unreachable / blocked / editing / bad login in the review | `load_preset=one-unreachable` (or `one-blocked`, `one-editing`, `one-bad-login`) | **Load** → *Final · BGP*: `xrv9k` shows the reason and cannot be ticked |
| **G04** *Loading… 2 of 4*, each device Waiting / Loading… / Loaded | `load_preset=slow` (`load_seconds=1.5` for a faster one) | **Load** → *Final · BGP* → **Load**. Close the panel: the load goes on; chip *Loading… k of 4*, Save and Load disabled |
| **G05** *Running Final* | `load_preset=all-ok` (or none) | **Load** → *Final · BGP* → **Load**. Toast *Final loaded on 4 devices.*; panel *Running Final · Loaded 1 minute ago on all 4 devices · Before loading: backed up automatically*, **Undo this load**, **What changed** |
| Undo | after G05 | **Undo this load** → confirm: the safety backup is loaded back (a `backup` source); the ceos and xrv9k configurations return |
| **G06** *Loaded 3 of 4* with `Not loaded` | `load_preset=one-failed` | as G05. Panel *Loaded on 3 of 4 devices*; **Try xrv9k again** (clear the preset first with `load_preset=null` to see it succeed), **Undo this load**, **Details** |
| **G06** *Kept previous* | `load_preset=one-rolled-back` | as G05: `xrv9k` *Kept previous* (the job read the device back as rolled back) |
| **G06** not confirmed | `load_preset=one-uncertain` | as G05: `xrv9k` worded as not confirmed, sends to **Details**; never *Kept previous* |
| **G09** lab not running | `lab_state` `{"lab":"restore-square","state":"stopped"}` (or the stopped lab `ospf-basics`) | **Load**: *Start the lab to load a state* with **Start lab**. Restore with `"state":"running"` |
| **G08** a lab with no saves of its own still offers lab states | `square-fresh` (default repository `Archtop-Lab`, `Course/...`) or choose `Big-Repo` | **Load**: *Lab states* Start (View only), Broken, Final; no *Your saves* group. **Load** → Final loads on 4 devices before the lab ever saved |
| The same through another repository | `square-fresh` | **Load** → **Browse the repository…** → another repository (`Nested-Labs`): its states list (read through the repository, the lab keeps no save location) |

### Save as a lab state (5.5, D9, DESIGN 2.9)

| State | Lab and setup | Clicks |
|---|---|---|
| A free folder | `restore-square`, `capture_seconds=1` | chip panel → **Save as a lab state…** → name `Mine`, folder `BGP/mine` (offered beside the lab's own folder; **Start**, **Broken**, **Final** are one-click names) → saves at once; waits for upload with the usual sentence. The lab's own folder does not change. **Load** lists *Mine* under *Lab states* for every lab |
| A folder that holds a state | as above | folder `BGP/start`, name `Start` → one question *"Start" already exists here.* **Replace it** / **Use another name**. Replace it: the state is complete afterwards (no longer View only) |
| The lab's own folder | as above | folder `BGP`, name `Inside` → the state goes to `BGP/Inside` and the dialog says so |
| A lab without a save location | `square-fresh` | the chooser asks which repository (`Archtop-Lab`), then as above (`Course/mine`) |

## PROMPT 6.2: how to reach each row

The folder chooser: for a lab with a save location, chip panel → *Saves to: … **Change…***, or **Save settings** → **Change folder…**; for a never-saved lab, the first-save panel's **Choose another place**. Pick a folder in the tree or type a path; read the sentence and the mark beside it, press **Save here**. The questions are buttons inside the chooser; none is an error. Nothing may say *registration*, *prefix* or *overlap*.

| The person chooses | Lab, repository, folder | What the chooser says and does |
|---|---|---|
| A folder that does not exist | `square-fresh` / Archtop-Lab / `brand-new/deeper` | free; created with the first save; listed as planned (*not in the repository yet*) until then |
| Ordinary files, no saved state | `square-fresh` / Archtop-Lab / `notes` or `Examples`; `shared-b` / Nested-Labs / `BGP/exercises` | free; used; the other files are left alone |
| The top level | `square-fresh` / Archtop-Lab / the top; `shared-b` / Nested-Labs / the top | free; used |
| Inside, above or beside another lab's folder | `shared-b` / Nested-Labs / `BGP/edge/inner` (inside), the top (above every lab folder), `BGP-beside` (beside) | free; used; nesting is allowed. (`BGP` itself is restore-square's own folder: that is the next row) |
| The very folder another lab saves to | `shared-b` / Nested-Labs / `shared`, `BGP/edge` or `BGP`; mark *shared-a saves here* | one question *shared-a saves here too.* **Save in shared/shared-b** (suggested) · **Use this folder anyway** (shared-a is disconnected from it, its saves stay as versions; check Save settings of shared-a: no save location) |
| A folder that holds a saved state | `shared-b` / Nested-Labs / `BGP/start`, `BGP/final`, flat `Final`; `square-fresh` / Archtop-Lab / `Course/start`, `Course/final` | one question *This folder holds the state "Start".* **Save beside it in BGP/start/shared-b** (suggested) · **Replace it** (for flat `Final`: **Use this folder anyway**, the state stays listed). A lab's **own** earlier save (a folder shared-a saved in, asked by shared-a) is no question: the lab continues there |
| Part of a saved state | `restore-square` / Nested-Labs / `BGP/checkpoints/ospf-up` or `BGP/latest`; `square-fresh` / Archtop-Lab / `Course/latest` | the lab folder above is used (`BGP`, `Course`) and the chooser says so (*adjusted*); for another lab's folder (`shared-b` typing `BGP/latest`) the question of the row above follows |
| Unsafe characters | `square-fresh` / Archtop-Lab / type `My Lab: A/B` | corrected as typed, the result shown (`My-Lab-A/B`); a name over 181 characters is cut, a path over 500 is the one 400 |
| A folder while a save waits | `restore-square`, `capture_seconds=1`, edit a device, **Save**, **Not now**; then **Change…** → `BGP-moved` | one question *1 save of restore-square is waiting for upload.* **Upload it, then move** · **Move and keep that save on the VM only**; with *Bring this lab's saved files along* ticked a move save follows (committed, never uploaded by itself; its review names the waiting save) |
| Registered on the VM, no lab uses it | `shared-b` / Nested-Labs / `old-lab-folder` | invisible in the tree (never *another lab's folder*); choosing it is free and reuses it |
| New folder… (always enabled) | `square-fresh` / Archtop-Lab: top level `Week 2` (corrected to `Week-2`); in `notes` `drafts`; nested `a/b` + `c/d/e`; inside a saved state (`Course/start`'s latest) `extra` → `Course/start/extra`, adjusted *above-state*; a name that exists (`notes`) selects it | never refused; planned folders are listed as not yet in the repository |
| A large repository | `square-fresh` / Big-Repo | the file list stops at 4000 (*truncated*), every folder is still offered (`docs/week-22/topic-269`), saved states beyond the cap are found by the states list |
| An empty repository, by address | the first-save panel's address field (`no_repositories=true`) or **Connect by URL…**: `https://github.com/ArchRuger/New-Empty.git` | *This repository has no commits yet.* with **Start the repository** → the README is committed and uploaded, the lab is placed in its folder |

## Where the real helper and the fixture agree (and where the page must not expect more)

* `FakeGit` imports the helper's own pure rules and fixed sentences (`snapshot`, `content_digest`, `colliding`, `collision_message`, `base_prefix`, `relpath`, `clone_url`,
  `manifest_summary`, `display_text`, the connect and start sentences, the limits). `check_fixture.py` compares the sentences it copies with the manager's table of the helper's sentences.
* `history` rows carry `summary` = `{lab_id, lab_name, kind, state, captured_at, topology_digest, devices: [{node, short_name, platform, restore}]}` or `null`; a missing field is `null` (an
  ordinary capture has `kind: null`), `state` is `''` unless the manifest has a top-level `state` string. `history` answers `head`, `commits`, `versions`, `summaries_truncated`.
* `browse` answers `files` and `dirs` in **Git's tree order** (`notes-old` before `notes`), `truncated` and `dirs_truncated`.
* `compare` answers `outgoing` **oldest first** with `{commit, operation_id, subject, files, approved}` and `outgoing_truncated`, or `outgoing: null` when the remote cannot be asked. It does not answer `head`: the manager reads it from `status`.
* `register-prefix` never refuses nesting (H1); a new folder sits beside waiting saves only when every commit in between is a manager save and the remote is asked (H2); a `retire` is refused while a save made through that registration waits (H7, the check runs before anything is registered).
* A push carries every earlier waiting commit and only the newest can be pushed (`synced_operations` names all, like `mark_synced`); a commit nobody journaled refuses the push (*outside manager saves*).
* `connect` takes `initialize`, finishes an unborn clone when the remote has its branch, refuses an empty repository with the helper's sentence and starts it with the fixed README and message.
* A problem is raised at the stage the helper raises it (table under *Switches*): `busy` causes stop status, publish, move, update and an upload's last check, not history, browse, read-version or compare.
* The load runs through the real `RestoreService` (preflight, safety backups, per-device transaction, confirmation on a fresh connection, read-back, undo from the safety backup). Only the device edge is scripted.
* Not scripted: real timing of a NOS, the timed recovery actually firing (a `rolled_back` device reverts when asked), a topology change made on the VM, a real GitHub. `diverged` as a *status* problem is a shortcut (the real status never says it).
* Known application differences from DESIGN.md that the fixture does not hide: `lab.git_status` is not recorded by the **place** route (DESIGN 3.8 N1 lists "a place"): it stays `ready: null` until the settings read, a save or an upload.
