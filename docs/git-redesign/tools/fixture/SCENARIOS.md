# Fixture scenarios for the Git save and load redesign

The fixture is the real application on a scratch data directory (`docs/redesign/tools/fixture_manager.py`) with three scripted
edges: the VM Git helper (`fake_git.py`), the devices (`fixture_devices.py`) and the capture (`fixture_backups.py`). Nothing
reaches a VM, a device or live data. Everything it shows is **fixture evidence**; it says nothing about a real NOS or a real GitHub.

```bash
cd <checkout>
FIXTURE_DATA=$(mktemp -d) clab-backup-ui/.venv/bin/python docs/redesign/tools/fixture_manager.py --port 8191   # ports 8191 to 8199 for this work
clab-backup-ui/.venv/bin/python docs/git-redesign/tools/fixture/check_fixture.py        # starts its own copy, asserts every scenario below
```

`--classic` seeds only the four labs and the `Course-Labs` repository the first fixture had. Restart the fixture after any `app/*.py`
change and use a fresh `FIXTURE_DATA` per run. Lab ids change per run (`GET /fixture/state` -> `labs`); names and registration ids do not.

## Files

| File | What |
|---|---|
| `fake_git.py` | `FakeGit`: the helper as redesigned (H1 to H7), several checkouts, journals, a fake remote |
| `fixture_content.py` | device configurations (EOS, IOS XR, Junos set + hierarchical), manifests, topologies |
| `fixture_devices.py` | the device model, the scripted restore driver and connector (the real restore service runs on top) |
| `fixture_backups.py` | the capture that reads the device model, with the real `Runner.embed_topology` |
| `fixture_scenarios.py` | the seeding below |
| `fixture_control.py` | the control (below) |
| `check_fixture.py` | the self-check |

## The control (one mechanism: three routes mounted by the fixture, outside `/api/`)

```
GET  /fixture/state    switches, devices (outcome, armed), repositories (head, waiting commits, registrations), labs
POST /fixture/switch   {"name": value, ...}   null or false clears; "name@Repository" scopes a switch to one repository
POST /fixture/action   {"action": "...", ...}
```

From Playwright: `page.request.post(BASE + '/fixture/switch', data={...})`. From a shell: `python docs/git-redesign/tools/fixture/fixture_control.py http://127.0.0.1:8191 switch push_fail_once=true`.
These routes need no `Origin` header and are not part of the application.

### Switches

| Switch | Effect |
|---|---|
| `vm_unreachable` | every Git helper call fails the way an unreachable VM does (`Cannot reach the VM Git helper...`) |
| `status_problem` | `staged`, `edits`, `operation`, `diverged`, `permission` or any sentence: `status` answers `ready: false` with it; every write refuses with it. Scope: `status_problem@Nested-Labs` |
| `remote_unreachable` | push fails (`The remote branch is unavailable...`), `compare.outgoing` is `null`, update and retire refuse |
| `remote_ahead` | the remote has a commit this VM lacks: a push is refused as diverged; `update` fast-forwards when nothing waits |
| `push_fail_once` | the next push fails (`...saved on the VM, but push failed...`), then the switch clears itself: the *Upload failed* state |
| `push_refused` | every push fails the same way until cleared (no permission) |
| `no_repositories` | `list` answers no repository (first save asks for an address); cleared by the first `connect` |
| `list_first` | repository name to list first |
| `unreadable_states` | folder paths whose history `summary` is `null` |
| `capture_seconds` | length of a capture (Save), default 6: set 30 to hold *Saving...* |
| `restore_capture_seconds` | length of each safety backup of a load, default 2 |
| `device_unreadable` | devices (short or full name) a capture cannot read: Save ends *could not be read* |
| `load_preset` | `all-ok`, `one-failed`, `one-rolled-back`, `one-uncertain`, `one-unreachable`, `one-blocked`, `one-editing`, `one-bad-login`, `slow` |
| `load_device` | device the `one-*` presets act on (default `xrv9k`) |
| `load_script` | `{device: outcome}` for any mix; outcomes `failed rolled_back uncertain unreachable blocked blocked-editing bad-login slow ok` |
| `load_seconds` | for `slow`: device k of the lab settles after k times this (default 5: about 20 s for four) |

### Actions

`helper` (a raw helper request, `{"repository": "reg-bgp", "request": {"mode": "history"}}`; answers the helper's answer or `{"error": sentence}`),
`edit_device` (`device`, `add: [lines]`, `remove: [lines]`: the next Save reports exactly this), `device_config` (`device`, `tag`: `start broken ospf-up loopbacks-reachable latest final other baseline`),
`lab_state` (`lab`, `state: running|stopped`), `hand_commit` (`repository`: a commit nobody journaled, the next push refuses it), `reset` (clears every switch and restores the devices).

## Labs

| Lab | State |
|---|---|
| `restore-square` | four devices `ceos` (EOS), `cjunosevolved`, `vjunos-switch` (Junos), `xrv9k` (IOS XR), running, Ready. Saves to `BGP` in Nested-Labs |
| `square-fresh` | the same four devices, running, Ready, **never saved**, no save location |
| `edge-lab` | 2 EOS devices, saves to `BGP/edge` (inside `BGP`) |
| `shared-a` / `shared-b` | 2 EOS devices each. `shared-a` saves to `shared`; `shared-b` is not connected and wants it |
| `solo-lab` | saves to the top level of Solo-Lab |
| `BGP_TheoryToPractice`, `vlan-lab`, `ospf-basics` (stopped), `switching-basics` | the first fixture's labs and its `Course-Labs` saves (`labs/BGP/work`, `labs/VLAN`), unchanged |

Device captures of the six new labs are deterministic (a second Save with nothing changed is `unchanged`); the first fixture's labs keep their drifting captures (every Save is a change).
At start every device of `restore-square` and `square-fresh` runs the configuration of the lab's own newest save (`latest`).

## Repositories (registration ids are fixed)

| Repository | Registrations | Content |
|---|---|---|
| `Archtop-Lab` | `reg-archtop` at the **top level only**, no lab connected | README, `notes/`, `Examples/` (ordinary files); `Course/start|broken|final/latest` made from `square-fresh` (Start is view only) |
| `Nested-Labs` | `reg-bgp` (`BGP`, restore-square), `reg-bgp-edge` (`BGP/edge`, edge-lab), `reg-shared` (`shared`, shared-a), `reg-unused` (`old-lab-folder`, no lab) | see below |
| `Solo-Lab` | `reg-solo` (top level, solo-lab) | one save |
| `Big-Repo` | `reg-big` (top level) | 5000 files in about 300 folders; states `zz-states/start|broken|final/latest` sort after the 4000th file |
| `Course-Labs` | `reg-work`, `reg-vlan` | the first fixture's content |
| `New-Empty` | not registered; reachable by `https://github.com/ArchRuger/New-Empty.git` | no commits yet |
| `Spare-Lab` | not registered; `https://github.com/ArchRuger/Spare-Lab.git` | README only (connects). Any other unknown address connects as a repository with a README; an address containing `forbidden` is refused (no permission), `missing` is refused (cannot clone) |

`Nested-Labs` holds, under and beside `BGP`:

| Path | What |
|---|---|
| `BGP/latest`, `BGP/baseline`, `BGP/checkpoints/ospf-up`, `.../loopbacks-reachable` | the lab's own saves: a latest save (uploaded, named *Interface descriptions cleaned up*), a starting point, two checkpoints, three latest saves and six commits in history |
| `BGP/start/latest`, `BGP/broken/latest`, `BGP/final/latest` | course states in `latest` layout, made from the lab's four devices. **Start has no restore artifacts (view only)**. Final equals `latest` on the two Junos devices (*Already matches*) and differs on EOS and IOS XR |
| `Final` | a state stored directly in a folder (`Final/manifest.json`, flat layout) |
| `BGP/junos-only/latest` | a state covering 2 of the lab's 4 devices |
| `BGP/other-topology/latest` | saved on a different topology: its topology file has other links and a node `ceos2`; 3 of its 4 devices match the lab |
| `BGP/checkpoints/plan-sept` | a design export (`kind: network-design`, no devices, view and download only) |
| `BGP/legacy` | a manifest that cannot be read (`summary` is `null`) |
| `BGP/notes.md`, `BGP/exercises/` | ordinary files beside saved states |
| `BGP/edge/latest`, `shared/latest` | the saves of the other labs |

## PROMPT section 5: how to reach each state

| State | In the fixture |
|---|---|
| Saved (G01, G10) | `restore-square` as seeded |
| Saving (F02) | `capture_seconds=30`, press Save |
| Unchanged (F14) | `restore-square` as seeded, press Save |
| Waiting, upload prompt (G11, F04) | `edit_device` `ceos` and `xrv9k`, Save, **Not now** (two devices changed, with a real line diff) |
| Uploaded (F05) | the same, then Upload |
| Failed (F13) | `push_fail_once=true` (or `push_refused`), Save, Upload |
| Can't save | `status_problem` = `staged`/`edits`/`operation` (Someone is working in the repository), `permission` (account cannot upload), `diverged`; `vm_unreachable`; `device_unreadable=["xrv9k"]`; `hand_commit` then Save (no save at HEAD) |
| Not saved yet (F12) | `square-fresh`; `list_first=Archtop-Lab` puts the top-level-only repository first; `no_repositories=true` for the address field |
| Loading, progress (G04) | `load_preset=slow`, Load a state |
| Running (G05) | `load_preset=all-ok` (or none), load Final |
| Partial (G06) | `load_preset=one-failed` (Not loaded), `one-rolled-back` (Kept previous), `one-uncertain` (not confirmed, see Details) |
| Load panel (G02), All versions (F11) | `restore-square`: Your saves, Checkpoints, Starting point, Lab states |
| Load confirmation (G03, G07) | load Final (ceos/xrv9k differ, Junos match); `BGP/junos-only` gives *Not in this state* for ceos and xrv9k |
| Unreachable / blocked in the review | `one-unreachable`, `one-blocked`, `one-editing`, `one-bad-login` |
| Lab not running (G09) | `lab_state` `{lab: "restore-square", state: "stopped"}`, or `ospf-basics` |
| Fresh lab with lab states (G08) | `square-fresh` with repository `Archtop-Lab` (`Course/...`), or `Big-Repo` |
| View only (G02) | `BGP/start/latest` (Start) |
| Saved on a different topology (G03 line) | `BGP/other-topology/latest` |
| Save as a lab state (D9) | `restore-square`, folder `BGP/mine` (free) or `BGP/start` (the question) |
| Narrow header (F16) | any lab at 760 or 390 px |

## PROMPT 6.2: how to reach each row

| The person chooses | Fixture |
|---|---|
| A folder that does not exist | any new name, for example `brand-new/deeper` in `Archtop-Lab` |
| Ordinary files, no saved state | `Archtop-Lab` `notes` or `Examples`; `Nested-Labs` `BGP/exercises` |
| The top level | `Archtop-Lab` (registered at top level only), `Nested-Labs` top level (above every lab folder) |
| Inside, above or beside another lab's folder | `Nested-Labs`: `BGP/edge/inner`, `BGP` (above `BGP/edge`), `BGP-beside` |
| The very folder another lab saves to | `shared-b` choosing `shared` (shared-a), or any lab choosing `BGP/edge` |
| A folder that holds a saved state | `BGP/start` or `BGP/final` (layout `latest`), `Final` (flat) |
| Part of a saved state | `BGP/latest`, `BGP/baseline`, `BGP/checkpoints/ospf-up` |
| Unsafe characters | type `My Lab: A/B` |
| While a save waits for upload | Save, **Not now**, then change folder |
| Registered, no lab uses it | `Nested-Labs` `old-lab-folder` (must stay invisible) |
| Large repository / brand-new empty repository | `Big-Repo` (listing stops at 4000 files, every folder in `dirs`); connect `https://github.com/ArchRuger/New-Empty.git` (refused with `This repository has no commits yet`; `initialize` starts it) |

## Fidelity and limits

* `FakeGit` imports the helper's own pure rules (`snapshot`, `content_digest`, `colliding`, `base_prefix`, `relpath`, `clone_url`) and answers with its sentences.
  `register-prefix` never refuses nesting (H1); a `retire` is refused while a save made through that registration waits (H7); a push carries every earlier waiting commit and
  only the newest can be pushed (`synced_operations` names all, like `mark_synced`); `history` rows carry `summary` (H3), `browse` carries `dirs` (a sorted list of paths) and
  `dirs_truncated` (H5), `compare` carries `outgoing` newest first (H6), `connect` takes `initialize` (H4).
* The load runs through the real `RestoreService` (preflight, safety backups, per-device transaction, confirmation on a fresh connection, read-back, undo from the safety backup). Only the device edge is scripted.
* Not scripted: real timing of a NOS, the timed recovery actually firing (a `rolled_back` device reverts when asked), a topology change made on the VM.
* The summary field `kind` is `''` for an ordinary capture, `network-design` for a design export; `restore` per device is a boolean.
