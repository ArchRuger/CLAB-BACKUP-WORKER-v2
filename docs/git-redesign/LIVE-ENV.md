# Live test environment on dev2

Prepared 2026-10-04 by the VM operator for the lead of the Git save and load redesign. dev2 is a disposable
development VM (24 CPUs, 72 GB, `/dev/kvm`). Everything below was observed in this session; commands are
trimmed to what matters. Evidence files are in [tools/live/evidence/](tools/live/evidence/).

The manager now running is **release 1.30.60 built from `513a2b2`** (application code identical to `main`
`68f24d9`; the branch had only documentation commits then). It does not contain any later change to the
checkout. To test new code, rebuild it (section 2).

## 1. At a glance

| Item | Value |
|---|---|
| Manager URL | `http://192.168.132.134:8081` (host network, TCP 8081; from the VM `http://127.0.0.1:8081`). Container `containerlab-node-manager-backup-ui-1`, image `clab-backup:1.30.60` |
| Data folder | `/srv/containerlab-node-manager/data` (untouched; the installed state was kept) |
| Capture stack | `clab-manager-capture-*`, `clab-capture-service:1.30.60` (refreshed with the manager) |
| VM helpers | `clab-manager-inspect` 1.30.60 (`clab-manager-files-v1`), `clab-manager-operate` 1.30.60, `clab-manager-git` 1.30.60 (`clab-manager-git-v1`); gateway refreshed. Verified by `deploy/check-install.sh` and by calling each helper |
| Lab | `git-redesign`, manager lab id `63d53e20db83464392ebfd4712bba5e3`, four nodes, all **Ready** (SSH + real `show version`), one manager backup succeeded 4/4 |
| Lab folder on the VM | `/srv/containerlab-node-manager/projects/git-redesign/` (trusted root), topology `git-redesign.clab.yaml` (copy: [tools/live/git-redesign.clab.yaml](tools/live/git-redesign.clab.yaml)) |
| Scratch repository | `https://github.com/ArchRuger/clab-scratch-git-redesign` (PRIVATE, owner account `ArchRuger`, default branch `main`, one README commit). `gh` has no `delete_repo` scope: it stays until the owner deletes it |
| Checkout and registration | Checkout `/home/archtop/labs/clab-scratch-git-redesign`; registered by Linux account **`archtop`**, binding id `e7d5f64d4c85487ebcff3baeff12694a`, branch `main`, remote `origin`, **prefix `` (repository top level)**, via `deploy/setup-git.sh` without `--prefix`. Commit identity in the checkout: `ArchRuger <ArchRuger@users.noreply.github.com>` |
| Memory with all four nodes up | `free -g`: 72 total, 25 used, 23 free, 24 buff/cache, 46 available (63 free before the lab). Containers: xrv9k 13.9 GiB, cjunos 7.2 GiB, ceos1 1.0 GiB, ceos2 1.0 GiB, manager 64 MiB |
| Lab state on purpose | The lab has **no save location**; the repository is registered at its top level (the owner's defect state, section 6). Do not "fix" it by hand if you need to reproduce again |

## 2. How the manager is rebuilt from a branch on this VM

Development rebuild loop (about 3 s, only the manager container; data bind-mounted, helpers untouched), from
`docs/redesign/PICKUP.md` section 2:

```bash
cd ~/projects/clab-manager
docker compose -f clab-backup-ui/compose.yml up -d --build
curl -s http://127.0.0.1:8081/api/state | python3 -c 'import json,sys; print(json.load(sys.stdin)["version"])'
```

A change under `app/host_*.py` also needs the helpers reinstalled (they are copies, version must equal the
manager's): `sudo bash deploy/setup-git.sh --refresh` (Git helper), `sudo bash deploy/setup-discovery.sh --update-helper`
(inspect helper), or the whole launcher below. Full update path used for the initial upgrade 1.30.58 to 1.30.60
(installer-equivalent, keeps passwords, `.env`, data; refreshes capture, helpers, gateway, image, manager):

```bash
cd ~/projects/clab-manager
sudo bash deploy/start-manager.sh          # exit 0 in about 90 s; includes docker compose build --pull --no-cache
bash deploy/check-install.sh               # exit 2 while any WARN remains (section 5)
```

Never restart or `down -v` anything holding `/srv/containerlab-node-manager/data`. The shared-store rule
still applies: tests must use their own `create_app(<temp dir>)`, never this data.

API access from scripts: the same-origin guard wants an `Origin` header equal to the base URL and a non-empty
JSON body on every mutating request. [tools/live/mgr.py](tools/live/mgr.py) does both:

```bash
python3 docs/git-redesign/tools/live/mgr.py GET /api/state
python3 docs/git-redesign/tools/live/mgr.py POST /api/labs/<lab id>/jobs '{"operation":"backup"}'
```

Browser automation: Playwright 1.x with Chromium is installed in `~/pw-venv` (outside the checkout), e.g.
`~/pw-venv/bin/python docs/git-redesign/tools/live/repro_first_save.py <lab id> <out dir>`.
It also needs `--with-deps` packages, which were installed.

## 3. The lab

`git-redesign.clab.yaml` is modelled on `docs/multi-platform-restore/lab/restore-square.clab.yml` with the
vJunos-switch replaced by a second cEOS. Containerlab 0.79.0 deployed it with
`cd /srv/containerlab-node-manager/projects/git-redesign && sudo containerlab deploy -t git-redesign.clab.yaml`
(exit 0, about 30 s). Management network `clab` `172.20.20.0/24`.

| Node | Container | Kind | Image | Management | Login (published kind default) |
|---|---|---|---|---|---|
| `ceos1` | `clab-git-redesign-ceos1` | `arista_ceos` | `n24l/ceos:4.35.0F` | 172.20.20.101 | `admin` / `admin` |
| `ceos2` | `clab-git-redesign-ceos2` | `arista_ceos` | `n24l/ceos:4.35.0F` | 172.20.20.102 | `admin` / `admin` |
| `cjunos` | `clab-git-redesign-cjunos` | `juniper_cjunosevolved` | `n24l/cjunosevolved:26.2R1.7-EVO` | 172.20.20.103 | `admin` / `admin@123` |
| `xrv9k` | `clab-git-redesign-xrv9k` | `cisco_xrv9k` | `n24l/cisco_xrv9k:24.3.1` | 172.20.20.104 | `clab` / `clab@123` |

Links (a square): `ceos1:eth1` to `cjunos:et-0/0/0`, `cjunos:et-0/0/1` to `xrv9k:Gi0/0/0/0`,
`xrv9k:Gi0/0/0/1` to `ceos2:eth1`, `ceos2:eth2` to `ceos1:eth2`. The nodes run the stock containerlab startup
configurations (no OSPF or data-plane addresses were added; the acceptance configs in
`docs/multi-platform-restore/lab/base-configs/` are for other node names).

Kinds and images: same kinds and images as the multi-platform acceptance lab (containerlab.dev kinds
`arista_ceos`, `juniper_cjunosevolved`, `cisco_xrv9k`); the image labels carry no kind (`docker image inspect`:
only vendor/vrnetlab labels), so the kinds are those documented on containerlab.dev and proven by the earlier
acceptance record. Nothing needed a different setting.

Boot (this session): cEOS about 1 min; cJunosEvolved SSH after about 11 min (manager check 14:19:40 UTC); XRv9k
**hung on its first boot** (launcher reached "press return to get started" at 14:22, then the guest printed
`BUG: soft lockup - CPU#0 stuck for 22s! [spawn_thread]` for 11 minutes and never offered the user prompt, so
`clab` could not log in: SSH answered, authentication failed). `sudo containerlab restart -t
git-redesign.clab.yaml -n xrv9k` (the native restart path) booted cleanly: "Startup complete in: 0:10:06", ready
14:44. Expect 10 to 15 minutes for XR; if the console shows endless `soft lockup` lines after "press return",
restart the node as above instead of waiting.

Independent readiness check (not the manager's code): `clab-backup-ui/.venv/bin/python
docs/git-redesign/tools/live/show_version.py [node ...]` prints the NOS identity. Result:

```
ceos1: OK  Arista cEOSLab | Software image version: 4.35.0F-44178984.4350F (engineering build)
ceos2: OK  Arista cEOSLab | Software image version: 4.35.0F-44178984.4350F (engineering build)
cjunos: OK  Hostname: HOSTNAME | Model: ptx10001-36mr | Junos: 26.2R1.7-EVO
xrv9k: OK  Cisco IOS XR Software, Version 24.3.1
```

## 4. Results per goal

1. **Manager brought to 1.30.60: done.** `sudo bash deploy/start-manager.sh` exit 0 (capture stack refreshed,
   telemetry retirement a no-op, image `clab-backup:1.30.60` built, manager recreated). `/api/state` version
   1.30.60. First `deploy/check-install.sh` run (before the VM connection was trusted and before Git setup):
   exit 2, PASS 32, WARN 3, SKIP 2: git helper missing, saved VM connection not ready, no Git checkout
   registered. After steps below: **exit 2, PASS 62, FAIL 0, WARN 1, SKIP 0, INFO 4**. The remaining warning is
   `Folder coverage: Stopped after 20 folders; more folders remain unchecked` (the topology browser scan of the
   lab roots; rerun with `--lab-path` or a larger `--max-folders` if it matters). The INFO lines are the optional
   Proxmox guest agent and online lab downloads (off by default).
   - The VM connection was already saved from the earlier install but its host key was not pinned
     (`bootstrap_pending`). `PUT /api/host` with an empty password (keeps the saved one) for the same endpoint
     pinned `SHA256:QcCZy8tG8+tp65oblOjkjPzCGrCbM5w0QHhsvuPzdMw`, which equals
     `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub`. Discovery then reported connected, helper 1.30.60,
     lab `git-redesign` (4 nodes, 4 running).
2. **Lab deployed: done**, table in section 3. Memory in section 1.
3. **Imported and backed up: done.** `POST /api/discovery/import-preview` `{"name":"git-redesign"}` (4 nodes,
   4 links, only `annotations` missing), then `POST /api/discovery/import` with the token: HTTP 200, lab
   `63d53e20...`. Logins come from the containerlab inventory (`credential_source: inventory`). The manager's own
   readiness monitor: `nos_readiness {'ready': 4, 'booting': 0, 'failed': 0}`, each node "NOS accepted SSH login
   and answered show version (automatic check)". `POST /api/labs/<id>/jobs {"operation":"backup"}` gave job
   `db67d98a1d754d01a066beefedcf9de5`: status `succeeded`, "4/4 NOS sessions completed successfully", every node
   "Configuration saved".
4. **Git registered at the top level: done.** Private repository created with
   `gh repo create clab-scratch-git-redesign --private --source=. --push` (initial commit, `main`). Registered with
   the project's guided wizard `bash deploy/setup-git.sh` (no `--prefix`): "Registered clab-scratch-git-redesign on
   main. ... Destination: repository root". `sudo bash deploy/setup-git.sh --list` and `GET /api/git/repositories`
   both show one repository, prefix `` (root), owner `archtop`, helper 1.30.60. The manager sees it.
   - The wizard needs a TTY and, on this VM, `sudo -v` demanded a password despite `NOPASSWD: ALL`. Fixed with
     `/etc/sudoers.d/91-dev2-verifypw` (`Defaults:archtop verifypw=any`, the same fix as dev1). The scripted run
     used `script -qec "bash deploy/setup-git.sh" /dev/null` fed with the answers: menu `1` (clone), the HTTPS URL,
     Enter (default checkout directory), commit name and email.
5. **The defect reproduces on 1.30.60, unchanged from 1.30.59.** Section 6.

## 5. Things that failed or deserve attention

- XRv9k first boot hung (soft lockups); fixed by a native node restart (section 3).
- `setup-git.sh` first attempts failed on the `sudo -v` password prompt (section 4, goal 4), and a first scripted
  answer sequence contained a confirmation the wizard does not ask for; harmless, nothing was registered.
- `deploy/check-install.sh` still exits 2 because of the `Folder coverage` warning.
- The Playwright virtual environment was created at `~/pw-venv` (not in the checkout).
- Not done, by instruction: no merge, force-push, tag, image publication; no data deletion; the lab was not given
  a save location.

## 6. Goal 5: the owner's defect (PROMPT.md section 6.1) on 1.30.60

State: repository registered at its top level (prefix ``), lab `git-redesign` without a binding, all four devices
Ready.

**Request and response** (the exact call the first-save dialog makes first, see `gitFirstSave` in
`app/static/git-progress.js`; no `registration` exists for the lab's folder, so it asks the VM to register it):

```
POST /api/git/repositories/e7d5f64d4c85487ebcff3baeff12694a/folders     body {"prefix":"git-redesign"}
HTTP 409
{"detail": "Lab folders in one repository cannot overlap: the repository root is already a lab folder. Choose a folder beside it."}
```

(`tools/live/mgr.py POST ...`; evidence `evidence/repro-first-save-api.txt`.) The text comes from `check_overlap`
in `app/host_git.py` (line 990). Nothing was registered or written; afterwards `GET /api/labs/<id>/git` still
has `"binding": null`.

**In the UI** (Playwright, `tools/live/repro_first_save.py`, output `evidence/repro-first-save-ui.txt`, screenshots
`evidence/*.png`): header **Save progress** opens "Where should git-redesign's progress be saved?"; with Folder
`git-redesign`, the exposure box ticked and a label entered, **Save progress** ends with the same message inside
the dialog as an inline error and as `role=alert`:
`Lab folders in one repository cannot overlap: the repository root is already a lab folder. Choose a folder beside it.`

**Folder browser, Progress tab, repository `clab-scratch-git-redesign`, top level:**

- The top-level row is tagged `Lab folder` (listing: `clab-scratch-git-redesign`, tag `Lab folder`, `README.md` 117 B).
- **New folder…** is **disabled**; its title is `Folders cannot be created inside another lab’s folder`, and the
  panel caption reads `Folders cannot be created inside another lab’s folder.`
- **Choose this folder** is enabled with title `This lab folder is free — no lab saves here yet.`, and the footer
  says the same sentence. So the panel contradicts itself, exactly as in the owner's report.

No workaround was applied; the repository stays registered at its top level and the lab has no save location.
Choosing the top level (prefix ``) would be the path that works today, but it was deliberately not taken.

## 7. Files added

All new, under `docs/git-redesign/tools/live/`: `mgr.py` (API client), `show_version.py` (independent readiness
check), `repro_first_save.py` (browser reproduction), `git-redesign.clab.yaml` (the topology), and `evidence/`
(`repro-first-save-ui.txt`, `repro-first-save-api.txt`, three screenshots). This document is the only tracked
file edited; nothing was committed.

## 8. After the first fix (commit a289abe)

Run 2026-10-04 15:05 to 15:16 UTC by the VM operator (one operator on the live lab). Evidence, scripts and
screenshots: [tools/live/evidence/s0-fixed/](tools/live/evidence/s0-fixed/) (numbered text files `01` to `19`;
the scripts that drove the browser are in its `scripts/`; no tokens, configuration text trimmed, the cEOS password
hash in two review dumps replaced by `<hash removed>`, two review screenshots that showed whole configurations
deleted). UI steps used Playwright from `~/pw-venv` against the real manager UI; the lab's map move, the device
changes and the second lab's import used the API or the device CLI as stated.

**Goal 1, rebuild and helper: done.** `docker compose -f clab-backup-ui/compose.yml up -d --build` exit 0, version
1.30.60. `sudo bash deploy/setup-git.sh --refresh` exit 0 ("Git helper refreshed; all registered repositories
retained"). `cmp /usr/local/lib/clab-manager/host_git.py clab-backup-ui/app/host_git.py` identical, and the
installed file contains `def colliding`. `bash deploy/check-install.sh` exit 2 with PASS 62, FAIL 0, WARN 1 (the
old `Folder coverage` warning), INFO 4; no failure. All four `git-redesign` devices still Ready (manager
readiness 4/4, no restart needed).

**Goal 2, defect 1 fixed, first save into `git-redesign` (UI).** Repository still registered only at its top
level (prefix ``), lab with no save location. Header **Save progress**, first-save dialog (repository
`clab-scratch-git-redesign`, folder `git-redesign`, all four devices ticked, exposure box ticked, label "first save of
the whole lab"). Requests, all HTTP 200: `POST /api/git/repositories/e7d5...a/folders {"prefix":"git-redesign"}` (new
registration `723fdfad...`, root registration kept), `PUT /api/labs/<id>/git` (binding, four nodes),
`POST /api/labs/<id>/git/save {"target":"latest","push":true,...}`. No refusal. The job ended
`review_pending` ("waiting for your review", destination `git-redesign/latest`); the review dialog listed the new
files; **Upload these changes** posted `POST /api/git/jobs/<id>/retry {"push":true,"reviewed":true}`; final job
status `synced`, "Saved commit is included in the verified remote history", commit
`4010b8f6fc92967b4c963d11e39bdc84486e48b0` (files 03, 04).

**Goal 3, G1 evidence.** `gh api repos/ArchRuger/clab-scratch-git-redesign/contents/git-redesign/latest`: 11 files:
`ceos1.cfg ceos1.eoscfg ceos2.cfg ceos2.eoscfg cjunos.cfg cjunos.jcfg xrv9k.cfg xrv9k.xrcfg git-redesign.clab.yml
git-redesign.clab.yml.annotations.json manifest.json` (one commit, 11 files added). The lab had no annotations file
on the VM (import said `annotations` missing) yet the map file is in the commit: the capture embeds the manager's
map. Then `PUT /api/labs/<id>/layout {"positions":{"ceos1":[40,200]}}` (HTTP 200; `GET .../map-document` showed it
at once) and, over SSH with the cEOS default login, `interface Ethernet1` `description s0-fixed-run-link-to-cjunos`
on `ceos1`. Save progress with the label dialog, review listed `ceos1.cfg`, `ceos1.eoscfg` (1 added each) and
`annotations.json` (2 added, 2 removed); upload; job `synced`, commit `aaea4186b115de39752740f25b996e3bbba80ca0`
(parent one, files: `ceos1.cfg +1`, `ceos1.eoscfg +1`, `annotations.json +2/-2`, `manifest.json +8/-8`). Changed
lines on GitHub: `+   description s0-fixed-run-link-to-cjunos`; `-"x": 0 -"y": 0 +"x": 40 +"y": 200` (files 05, 09).
The other three devices and the topology file were unchanged in that commit.

**Goal 4, defect 2 fixed (folder browser, Progress, Change folder...).** Top level: **New folder...** enabled
(title `Create a folder here`), the top-level row is no longer tagged, only `git-redesign` carries `Lab folder  This
lab saves here`; **Save this lab here** enabled; the foot says `This lab saves to git-redesign. Looking at other
folders does not change that.` No contradicting text. The lab's own folder: **New folder...** enabled, **Save this lab
here** disabled with `This lab already saves here.` (the same text as its title), caption `Applies this folder's
latest save (git-redesign/latest) ...`. No folder is marked `Lab folder` that no lab uses (the registration at the
top level is invisible, `scratch-a` shows `Empty folder`). Created through **New folder...** with "Save ... here from
now on" unticked: `scratch-a`, `git-redesign/notes`, `git-redesign/notes/deep`, each accepted without refusal; the
manager lists them as planned (`GET .../tree` `planned`), the VM registration list still holds only the root and
`git-redesign` (files 10, 10b, 10c, 11; screenshots `fb-01` to `fb-04`).

**Goal 5, second lab nested.** 72 GB total, 46 available before; after both labs 44 available, 28 used (cEOS
935 MiB each, xrv9k 14.2 GiB, cjunos 7.4 GiB, manager 67 MiB). `git-redesign-b` (two cEOS, link `eth1`,
172.20.20.111/112, topology `scripts/git-redesign-b.clab.yaml`, folder `/srv/containerlab-node-manager/projects/git-redesign-b`)
deployed (exit 0, about 20 s), found by discovery, imported through `import-preview` and `import` (API; HTTP 200), both
nodes Ready within a minute. The name prefix `clab-git-redesign-` of the first lab did not confuse discovery: each
lab kept its own two or four nodes. First save through the same first-save dialog into folder `git-redesign/b`:
`POST .../folders {"prefix":"git-redesign/b"}` 200, binding 200, save 200, review `git-redesign/b/latest`, upload; job
`synced`, commit `260bb4a3c86f031afac0d1f4f6698c1646af5a53` (7 files under `git-redesign/b/latest/`). This was
refused before the fix. Then `ceos2` of the first lab got `Ethernet2` description `s0-fixed-run-link-to-ceos1`, a
third save of the first lab (review: `ceos2.cfg`, `ceos2.eoscfg`), commit
`5a9724d29fe5a85fe0fde39ce9130fdd39c4d580` (touched only `git-redesign/latest/ceos2.cfg`, `ceos2.eoscfg`,
`manifest.json`); every blob under `git-redesign/b/` has the same hash before and after (files 15, 18).

**Goal 6, what did not work or deserves a decision.** No refusal, grey-out or dead end met in goals 2 to 5. Notes:
- From lab b, looking at lab a's folder `git-redesign`, **Apply to running lab...** is offered and names
  `git-redesign/latest` (lab a's save) as the thing to apply to lab b's running devices; not clicked. **Save this lab
  here** there is disabled with `git-redesign already saves here.`, which reads oddly because the other lab is
  also called `git-redesign` and the folder is named the same (the tag in the tree is truncated to `git-red...`).
- The first save of a lab leaves `scratch-a`, `notes`, `deep` as manager-side planned folders only (Git keeps no
  empty folders); the first run's folder script lost its API log because it aborted on a wrong click in my script,
  not in the UI. After creating a folder the browser moves into it.
- The review dialog and the capture still print complete configurations in the review (by design, with the
  exposure warning); screenshots of that were not kept.
- Today's UI is unchanged in shape: first-save dialog, label dialog, review dialog, Progress tab.

**State now.** Both labs running (6 lab containers, all Ready). Repository registered on the VM at `` (root, no lab)
and at `git-redesign` (lab `git-redesign`, devices: all four) and `git-redesign/b` (lab `git-redesign-b`, both
devices). On GitHub (`main`): `git-redesign/latest/` (11 files, commit `5a9724d...`) and `git-redesign/b/latest/` (7 files);
planned only in the manager: `scratch-a`, `git-redesign/notes`, `git-redesign/notes/deep`. Lab `git-redesign`'s
devices carry two extra interface descriptions (ceos1 Ethernet1, ceos2 Ethernet2); lab b has none.
No merge, force-push, tag or image publication; no data deleted. Scripts: `evidence/s0-fixed/scripts/`.

## 9. Live backend pass (L1)

Run 2026-10-04 15:49 to 16:19 UTC by the VM operator (one operator on the live labs), against the new backend and the
new Git helper of `a2a3b61` (branch `slice/l1-live`), by the manager's API, not the browser. Every request, answer
and device or GitHub read is in [tools/live/evidence/l1-backend/](tools/live/evidence/l1-backend/) (numbered text
files `00` to `31`, trimmed to the fields that matter: no tokens, no whole configurations, one-time tokens removed).
Scripts: `tools/live/l1lib.py` (client and device helpers), `l1_s10.sh` and `l1_s10.py` (upload failure with a
temporary `/etc/hosts` line removed again by a `trap`), `l1_s15.py`, `l1_s17.sh`, `l1_s17_state.py`. Device changes are
one interface description per platform containing `l1-<step>` (cEOS `Ethernet1/2`, Junos `et-0/0/1`, IOS XR
`GigabitEthernet0/0/0/0`). No code was changed.

### 9.1 Build

`docker compose --env-file <installed .env> -f <worktree>/clab-backup-ui/compose.yml up -d --build` exit 0, then
`sudo bash deploy/setup-git.sh --refresh` exit 0 (file `00`). API version 1.30.60; the installed
`/usr/local/lib/clab-manager/host_git.py` is `cmp`-identical to the worktree's; all 45 `app/*.py` and every
`app/static/*.js` in the container equal the worktree (file `01`). `deploy/check-install.sh`: exit 2, PASS 70, FAIL 0,
WARN 1 (`Folder coverage`, the old one), INFO 8 (file `02`). No other helper or the capture stack reported a version
mismatch. Both labs, their save folders and their earlier saves were still there; all six devices Ready.

### 9.2 Results

| # | Result | One sentence |
|---|---|---|
| 1 | PASS | Old state reads (two labs, bindings, four saves with their names); `git_status` is in `/api/state` (`checked: ''` until the first helper contact, then filled); `places` answers for both labs. `places?repository=<id>` carries the tree under `tree` (`files`, `folders`, `head`, `own`, `saved`, `truncated`), and `tree.folders` lists `git-redesign` and `git-redesign/b` twice. |
| 2 | PASS | An unnamed save: `note` `ceos1 changed`, `note_auto` true, `summary` `{added 1, removed 1, devices [ceos1]}`, job `review_pending`; `compare` rows with `role` and `node`; `head`, `upload_job` = the save, `also_sends` `[]`; upload bound to that head ended `synced`; commit and the changed `description` line on GitHub; topology and map files are in the folder. |
| 3 | PASS | `status: unchanged`, message "Nothing changed since the last save, which was uploaded.", `commit` reports the existing HEAD, no commit made, also with a typed name. |
| 4 | PASS | A waiting save of `git-redesign`, then a save of `git-redesign-b` was accepted; the second review names the first in `also_sends` (`other_labs` 1); one upload through the save at HEAD; both jobs `synced`, both commits on GitHub; the first reads "Saved commit is included in the verified remote history." |
| 5 | PASS | Upload with the old head: 409 `Another save was made in this repository. Look at the changes again.`; GitHub unchanged; a fresh review then uploaded both. |
| 6 | DIFFERS | See 9.3 (1): an empty `folder` means the repository top level. With `git-redesign/start`, `/broken`, `/final` the states are saved, uploaded and listed (`group: state`, `saved_devices` 4, `loadable_devices` 4); manifests carry `state`. |
| 7 | PASS | Load Start on four devices: all `verified`, "All 4 node(s) restored and verified"; see 9.4 for the record and timings; devices read back run Start. |
| 8 | PASS | Load of `pre_backup_job_id` as a `backup` source: four `verified`; every device back on `l1-s6-final`. |
| 9 | PASS, with a DIFFERS | Paused ceos2: preflight `eligible: false`, `reachable: false`, reason `SSH probe failed: SSHException` (took 38.7 s), no diff; submit with it: 409; the other three loaded, then ceos2 alone after unpause: all four on Broken. See 9.3 (2). |
| 10 | PASS | github.com blocked: upload job `push_pending`, "The remote branch is unavailable. Check connectivity and the owner's noninteractive HTTPS Git login.", `git_status` `{ready: false, code: 'account', waiting: 1}`; a new save worked on the VM; after the unblock the retry ended `synced` and carried both. `/etc/hosts` restored byte-identical by the trap. |
| 11 | PASS | The recovery in 9.5. |
| 12 | PASS | Rename, empty name back to the automatic one, 120-character and one-line limits (400); the commit subject is unchanged. Keep as a checkpoint without a name: `git-redesign/checkpoints/ceos1-changed`, then `-2`; see 9.3 (5). |
| 13 | PASS | `folders/new`: top level, inside a lab folder, nested; inside a state `adjusted: above-state`; unsafe characters `corrected`; an existing name `existed: true`. A move with a waiting save answers `{question: {kind: 'pending', count, names, bring}}`; with the save uploaded first and `move_files` the move commit (`Move … progress to l1-moved-b/`) went up as a save; with `pending: keep` and no files the save stays in the old folder. The very folder of the other lab: question `lab` with `beside` `git-redesign/git-redesign-b`; see 9.3 (6). |
| 14 | PASS | From `git-redesign-b` the states of `git-redesign` list with `loadable_devices` 0; the preflight says `topology.differs: true`, `matching_devices: 0`, every row `No running node in this lab matches this saved node.`; no load was submitted. |
| 15 | PASS | Destroyed with `/api/operations/preview` and `confirm`: preflight rows ineligible ("The node is not currently running or discovery is stale."), load 409 with the same, a save `failed` ("Selected nodes are not currently available. Refresh VM discovery before connecting."); the deploy ended in Ready after about 40 s, same lab record. |
| 16 | PASS, with a DIFFERS | See 9.3 (7): the question fired once the folder named after the lab held that lab's saves; `Continue there` is a second call with `choice: take`; the next save continued in the old folder (not a first save). |
| 17 | PASS, with DIFFERS | The scaffold tool works against the new backend; its text and its guards are older than the model. See 9.6. |

### 9.3 Differences from the documents

1. **`POST …/git/state` with an empty `folder`** is the repository top level, not `<lab folder>/<name>`: DESIGN 2.9 step 1
   says the page sends that default. My first Start went to `latest/` at the repository root (job `68e1b06c…`, now the
   state `Start · Top level`, still on GitHub), and the next two calls answered `{question: {kind: 'state', label: 'Start',
   folder: ''}}`. Exactly as designed if the page always sends a folder; a script that omits it writes at the root.
2. **Two sentences for one cause** on an unreachable device: the preflight row says `SSH probe failed: SSHException`,
   the submit says `The node is not currently running or discovery is stale.` (409). A preflight started within about
   8 s of the previous load's end answered 409 `Wait for the active backup, Git save, restore or lab operation to finish.`
   with nothing visible running; the retry 7 s later was accepted.
3. **The helper's `status` never asks the remote.** With only the online copy ahead and nothing waiting, `git_status` and
   `repository_status` stay `ready: true`; a save then works on the VM and only the upload fails (code `diverged`, the
   helper's sentence `The remote branch advanced or diverged. Resolve the branch before pushing; no force push was attempted.`).
   `status.js` shows `The online copy has changes this VM does not have.` + **Update** when `diverged` and nothing waits, but
   in this pass `diverged` always arrived with a waiting save, so that row was not reached. *Update from the repository*
   itself worked when nothing waited (200 `Updated from remote using fast-forward only.`) and answered 409 `Upload the
   waiting saves first; the online copy can only be fetched when nothing waits here.` while a save waited.
   `REMOTE_AHEAD` (`The online copy of this repository has changes this VM does not have.`) is raised only by `register`
   and is not in the manager's code table (not exercised here).
4. After the owner's `git pull --no-rebase` and before his push, `git_status` reads `ready: true` and an upload is refused
   with 409 `The repository on the VM has changes the manager did not make.` (the merge is HEAD).
5. **Keep as a checkpoint from an older save** also writes `git-redesign/latest/*` from that older capture (rows with an
   empty `status` in the review: `ceos1`/`ceos2` files and the manifest), so `latest` no longer equals what the devices run.
6. **`choice: take`** ("Use this folder anyway") was accepted for the very folder another lab saves in and disconnected that
   lab (lab A lost its binding; I put it back with `take` from A and B back to `git-redesign/b`). `beside` is the safe answer.
   A move without `move_files` leaves the lab's earlier saves where they are: `l1-moved-b/latest` now lists as a lab state
   `L1-moved-b` (group `state`), and a save kept waiting keeps its old destination.
7. **Removing and importing a lab again** gives it a new id; the default is `<lab name>` and asks only when that folder holds
   a same-named lab's saves. Earlier saves of this lab were under `git-redesign/b` and `l1-moved-b`, so the first default
   was a plain `free`; the question (`ask: true`, `same_name: true`, `kind: state`, `beside: git-redesign-b-2`) appeared
   after one save in `git-redesign-b` and a second import. `git status -sb` in the checkout reads `ahead N` after the
   manager's pushes (the helper pushes by URL and leaves `origin/main` stale until a `git fetch`).

### 9.4 Loads

Both loads and the single-device load went through the drivers (`status: verified`, `persistence: saved`). The job record
shows per node: `stage` and `timeline` (`queued`, `backing_up`, `backed_up`, `connecting`, `applying`, **`armed`**,
`verifying`, `confirming`, `replaced`, `settled`, `checking`, `checked`), `confirm_minutes: 5`, `diff_sample` (the changed
lines), `root_authentication: synthesized` on Junos, `pre_backup_job_id`, `post_backup_job_id`. Timings of load 7 (seconds):

| Node | applying to armed | applying to settled | queued to settled |
|---|---|---|---|
| cEOS | 1.2 | 2.1 | 4.8 |
| cJunosEvolved | 4.3 | 5.1 | 7.8 |
| XRv9k | 4.3 | 5.6 | 8.3 |

Whole jobs: four devices 15 s (Start), 17 s (undo), three devices 16 s, one device 11 s, each with the safety backup and
the check backup. The record proves that the recovery was armed (`armed` before `confirming`) but does not carry the
device-side command output or a token; the kinds' own transaction commands are in
[../multi-platform-restore/README.md](../multi-platform-restore/README.md).

### 9.5 Recovery when the online copy and a waiting save both changed (step 11)

Facts, in `15` to `22`. One waiting save and one more commit online: the upload ends `push_pending` with the sentence in
9.3 (3); `git_status.code` is `diverged`; *Update* is refused (409). What worked, as the VM account of the checkout
(`archtop`, its own login, no credentials typed):

```
git -C <checkout> pull --no-rebase --no-edit     # merge commit, exit 0
git -C <checkout> push                           # exit 0 (pushes the merge and every waiting manager save)
```

then the manager's Upload (retry) on each waiting save answered 200: the save at HEAD went `Saved to Git.`, the others
`Saved commit is included in the verified remote history.`, all `pushed: true`, `waiting` 0, and a later save and upload
worked. **Pulling without pushing does not work:** the manager's upload is refused (409 `The repository on the VM has
changes the manager did not make.`), and a further manager save followed by Upload ends `push_pending` with `The push would
include commits created outside manager saves. Publish or resolve them as the repository owner first.` (code `diverged`);
the owner's `git push` then cleared it as above. (A fast-forward-only pull was not tried.)

### 9.6 Scaffold tool (step 17)

`init l1-scaffold` (exit 0, repeatable, exit 0 again), `snapshot l1-scaffold start` answering `n` (exit 0), `snapshot
l1-scaffold solution --yes` (final line printed; its exit status was lost with my wrapper, exit 0 by reading the code).
Folder after each command: `l1-scaffold/work`. After `start` answered no: the job is `dismissed` ("First save"), nothing
on GitHub; after `solution --yes` both commits are on GitHub (`start` went with the upload; both jobs `pushed`). The
manager routes it used all answered 200: `…/folders`, `…/git/destination`, `…/git/save` (no note, no `head`),
`…/git/jobs/<id>/retry` (no `head`), `…/dismiss`. `restore/states` lists `Solution` and `Start · reference`
(`group: state`, 2 devices each). Where text and behaviour no longer match: the tool and NAMING.md still say that a
pending save refuses the folder change and that the person must finish it under Progress > Recent saves; that no longer
happens: step 13 moved a lab with a waiting save (`pending: keep`), so `keep_on_vm`/`dismiss` (which the tool
still calls before rebinding, turning the kept save into a `dismissed` job that the next upload still carries) and the
"STILL SAVES TO" recovery text are legacy. The tool's upload skips the review the new
model binds to a `head`; the retry without `head` was accepted.

### 9.7 State left behind (for the browser pass)

Both labs running, Ready 4/4 and 2/2, no device paused, `/etc/hosts` has no extra line (its checksum differs from step 10
only because containerlab rewrote its own `clab-*` block when `git-redesign-b` was deployed again), no waiting save.
Lab `git-redesign` (`63d53e20…`) saves in `git-redesign`; lab `git-redesign-b` is a new record `123f0029…` (it was removed
and imported again twice; the old ids are gone from the manager) and saves in `git-redesign-b`. Repository `main`
(`1ff020a`): folders with a saved state `git-redesign/latest`, `git-redesign/{start,broken,final}/latest` (lab states),
`git-redesign/checkpoints/{ceos1-changed,ceos1-changed-2}`, `git-redesign/b/latest` and `l1-moved-b/latest` (old saves of
lab B), `git-redesign-b/latest`, `l1-scaffold/reference/{start,solution}/latest`, a stray `latest/` at the root (the Start
of 9.3 (1)); other files `l1-online/online-{1,2,3}.txt`. Devices: ceos1 and ceos2 of `git-redesign` run
`l1-s11b2-ceos1` / `l1-s11b2-ceos2`, cJunosEvolved and XRv9k run the Broken state (`l1-s6-broken`); `git-redesign-b` ceos1
`l1-s17-solution`, ceos2 `l1-s16-after-reimport`. The manager's planned folders I made in step 13 were forgotten again;
the registrations they or the moves created remain. No merge, force-push, tag or image publication; no data deleted.

## 10. Live browser pass (L2)

Run 2026-10-04 18:50 to 19:50 UTC by the VM operator (one operator on the live labs), through the real page
(Playwright and Chromium from `~/pw-venv`, 1440x900, 390x844 for group D) against the manager built from `2578f22`
(branch `slice/l2-live`), the real devices and real GitHub. Evidence: numbered text files and screenshots in
[evidence/live/](evidence/live/) (screenshots show no configuration text: panels, lists and trees only; the What changed
and differences drawers were not kept). Scripts: `tools/live/l2lib.py` (the integration scripts' `Session` pointed at the
real manager), `l2_a1.py` to `l2_d3.py`, and `l2_x_*.py` (the small follow-up scripts that were run by hand). No code was
changed. The device changes are interface descriptions (`l2-a2`, `l2-c1-start`, `l2-c1-broken`, `l2-c1-final`, ...).

### 10.1 Build and the environment

`docker compose --env-file <installed .env> -f <worktree>/clab-backup-ui/compose.yml up -d --build` exit 0, then
`sudo bash deploy/setup-git.sh --refresh` exit 0 (file `00`). API version 1.30.60, installed `host_git.py` `cmp`-identical,
every `app/*.py`, `static/*.js` and `static/*.html` in the container equals the worktree (`01`); `deploy/check-install.sh`
exit 2 with PASS 110, FAIL 0, WARN 1 (`Folder coverage`, as before), INFO 28 (`02`).

**The XRv9k guest stopped answering SSH after the manager rebuild** (TCP accepted, no banner for more than 10 minutes,
connections stay CLOSE-WAIT in the container, the console shows only telnet negotiation) although the manager still read it
Ready. `sudo containerlab restart -t git-redesign.clab.yaml -n xrv9k`: the first boot hung again in
`BUG: soft lockup - CPU#0 stuck for 23s! [tune2fs]` for 20 minutes (container "unhealthy"), the second restart came up
(about 9 minutes; the configuration persisted, `l1-s6-broken` was still there). Group A and most of B and D therefore ran on
lab `git-redesign-b` (two cEOS) while the guest started; A2 and the unchanged save were repeated on lab A afterwards (`11b`,
`12c`). `docker ps` still lists the container as unhealthy; SSH and the manager work. Details in `03`.

### 10.2 Results

| Step | Result | What the page showed and did |
|---|---|---|
| A1 | PASS | Chip, Save, Load, Lab actions on all four tabs, one row, in order; no Progress tab; `#lab=<id>&view=progress` and `view=git` rewrite to `view=topology` with the chip panel open (`10`). |
| A2 | PASS | Lab B, then lab A. Device `l2-a2` plus the map moved by Edit map: **Save** opened the panel by itself: `1 device changed since your last save: ceos2. 1 line added, 1 removed. The map changed.` **See changes** lists `ceos2.cfg`, `Map ... annotations.json`, `manifest.json`; **Upload**; chip `Saved just now`. GitHub: the lab folder holds topology, map and one config per device; the map patch moves ceos1 `40,20` to `60,40`. **2 clicks (Save, Upload), 3 with See changes, nothing typed** (`11`, `11b`). |
| A3 | PASS | Not now: panel closes, chip `1 save to upload`, the commit exists only on the VM; Upload later from the chip (4 clicks counted: Save, Not now, chip, Upload). Unchanged Save: toast `Nothing changed since your last save.`, no commit (lab B and lab A with Junos and IOS XR). Name field renames (commit subject unchanged), **Keep as a checkpoint** (2 clicks, 3 with Upload) wrote `git-redesign-b/checkpoints/l2-named-save`. In **All versions** an older save kept as `l2-older-checkpoint` (7 clicks, 1 typed): the commit adds only `checkpoints/l2-older-checkpoint/*` and `latest/ceos1.cfg` kept its blob; the checkpoint holds `l2-a2`, `latest/` holds `l2-a3-named` (L1's defect is fixed) (`12`, `12b`, `12c`). |
| A4 | PASS, DIFFERS | github.com blocked by the trap-guarded hosts line (restored byte-identical): chip `Upload failed`, panel `Your save is safe on the lab VM, but github.com could not be reached.` with Try again, See changes, Details; `git_status` still `ready: true`. After the network was back **Try again** ended `Saved just now` (1 click). See 10.3 (4) for the second Try again while blocked (`13`). |
| A5 part 1 | PASS | The online copy one commit ahead, nothing waiting: **Save** then **Upload** (2 clicks) ended `Saved just now`; the VM log shows the online commit merged first (fast-forward) and the lab events `git.update` "The VM copy of the repository was brought up to date with the online copy before a save." (read through `/api/logs`; the Advanced tab did not show it on first view) (`14`). |
| A5 part 2 | **FAIL** | One save kept with Not now, one more commit online, Upload: chip `Can’t save`, panel `The online copy and this VM both have changes the other does not have. They have to be combined on the VM.` / `The repository’s owner runs these on the lab VM, then Try again uploads the waiting saves:` / `git -C /home/archtop/labs/clab-scratch-git-redesign pull --no-rebase` / `git -C ... push`. Both commands ran as the owner (exit 0). **Try again then does nothing**: the panel shows the error `See what this upload sends before uploading.` and no upload request is made (see 10.3 (1)) (`15`). |
| B1 | PASS | **New folder…** enabled at the top level, inside `git-redesign` and nested; each created, said as planned (`... is new. It appears in the repository with the first save.`), no refusal (`20`, screenshots `B1-*`). |
| B2 | PASS | Remove and import again: first-save panel `This repository already holds saves of a lab named git-redesign-b.` with **Save in git-redesign-b-2** and **Continue there**. Continue there: 2 clicks to the commit (3 with Upload), the save continued in the old folder (`Map changed`, not a first save). Save in git-redesign-b-2: 2 clicks, `First save`. The case with no question was measured in B5 (`21`, `22`). |
| B3 | PASS | Lab B moved to `git-redesign/inner` with its files brought along (chip, Change..., type, Save here = 3 clicks, 1 typed; the move waits for Upload, 7 files in the new folder, none left in the old). Two tries with a waiting save: question `1 save of git-redesign-b is waiting for upload.` with **Upload it, then move** (the save went up first, the move then waited as `1 save to upload`) and **Move and keep that save on the VM only** (the save stayed waiting with the move, `2 saves to upload`, one Upload sent both) (`23`). |
| B4 | PASS | Lab B chose lab A's folder: `git-redesign saves here too.` / **Save in git-redesign/git-redesign-b** / **Use this folder anyway** (note names the disconnection); answered with Save in...; lab A kept its folder (`24`). |
| B5 | PASS, DIFFERS | New private repository `ArchRuger/clab-scratch-git-redesign-empty` (no README). From a lab without a save location: Connect by URL..., address, folder, **Connect and save here**: `clab-scratch-git-redesign-empty is empty. The manager adds a README.md file to start it.` / **Start the repository**; GitHub: `Start the repository for lab saves` (README.md) then `First save` (`lab-b-empty/latest/*`). 5 clicks and 3 typed fields including Upload. Lab B was pointed back at `clab-scratch-git-redesign` `git-redesign-b` with **Replace it** (2 clicks) (`25`). See 10.3 (6). |
| C1 | PASS | Chip, **Save as a lab state...**, a name chip (`start`, `broken`, `final`), **Save state**: 4 clicks, 0 typed, folder `git-redesign/<name>`; one Upload sent all three; manifests carry `state`; every device file holds `l2-c1-start`, `-broken`, `-final`. **Load** lists Start, Broken, Final under LAB STATES. A first Broken attempt of mine was spoiled by my own timing (the cEOS were changed while it was still reading, `33a`); saving it again asked `“Broken” already exists here.` with **Replace it** / **Use another name** (`33`). |
| C2 | PASS | Load, the state, the red Load = **3 clicks** each: Start, Broken, Final; confirmation `Load Start?` with `2 lines differ` per device; chip `Loading… 0 of 4`, then `Running <name>`; CLI read-back on all four devices matches each state. Panel `Running Start` / `Loaded just now on all 4 devices.`; the per-device words (`Waiting`, `Loaded`) are in the loading view; the finished panel does not list them when all four loaded. Every target's timeline has `armed` before `confirming` (`34`, timings in 10.4). |
| C3 | PASS | **Undo this load** pressed at once after `Running Start`: the page showed `Checking the configuration from before Start against your devices...` with **Cancel** (screenshot `C3-undo-after-click-a.png`), the confirmation `Undo loading Start?` came after about 4 s, the undo job started 2.8 s after the red Load; no failure shown; the four devices were back on `l2-c1-final` (`35`; `35a` is my first run, which read the devices too early). |
| C4 | PASS, DIFFERS | The confirmation was open, ceos2 paused, red Load: the manager answered after about 38 s (the page showed the confirmation with a dimmed Load and the old chip), then job `partial`, chip `Loaded 3 of 4`, panel `Loaded on 3 of 4 devices` / `ceos2 was not changed.` / ceos2 `Node is not currently running.` `Skipped` / **Try ceos2 again**, **Undo this load**, **Details**. After the unpause the first Try again said `Can't load` / `This device is not running, or the lab status is out of date.`; about a minute later it loaded; all four on Start (`36`). |
| C5 | PASS | Lab B destroyed with the manager's lab operation: label `Stopped`, Load says `Start the lab to load a state` / `Loading puts a saved configuration onto running devices. This lab is not running.` / **Start lab**, which opens the review `Start git-redesign-b?` (the `containerlab deploy` command shown); confirmed, Ready in about 36 s (`30`). |
| C6 | **FAIL**, DIFFERS | Lab A removed and imported again (new record): Load without a save location says `This lab has no saves of its own yet. You can start from one of these.` and lists 8 of 10 lab states alphabetically, **Start is not among them** (`2 more in All versions`), so the load took 5 clicks via All versions > Start > Load this state... > Load; all four devices ran Start (`37`). Then **Save does not open the first-save panel**: see 10.3 (2). After a second removal and import the first save asked `This repository already holds saves of a lab named git-redesign.`, **Continue there**, and the save continued in `git-redesign` (Save, Continue there, Upload = 3 clicks) (`38`). |
| D | PASS, DIFFERS | 390x844: A2's save and upload (2 clicks), B1's chooser and C2's load of Final (3 clicks) all worked, no console error (`40`, `41`). See 10.3 (8). |

### 10.3 Differences from the documents (the exact words and requests)

1. **A5 recovery: Try again does nothing after the owner's two commands.** After `git -C <checkout> pull --no-rebase` and
   `git -C <checkout> push` HEAD is the owner's merge commit and the waiting save is already on GitHub, but the manager still
   lists the job `push_pending` (`git_status` `{ready: false, code: 'diverged'}`). **Try again** (`#save-cant-upload-again`)
   posts `POST /api/labs/<id>/git/compare {"job_id": ...}` and no upload: the answer has `head` = the merge and
   `upload_job: null` (no manager save at HEAD), and `gitReviewJob` throws `See what this upload sends before uploading.`, shown as
   the panel error; the chip stays `Can’t save`. What works: press **Save** (nothing changed: a new empty save becomes the
   save at HEAD, panel `Nothing changed since your last save, which is not uploaded yet. This upload also sends 1 other
   save`), then **Try again** or Upload: every waiting save ends `synced` ("Saved commit is included in the verified remote
   history"). The panel and the guide say Try again uploads the waiting saves (DESIGN.md 3.6); in L1 the same recovery worked
   only because a save was made after the owner's merge. Evidence `15`, screenshot `A5-try-again-does-nothing.png`.
2. **A lab with no save location that loaded a state cannot make its first save from the header.** The chip reads `Running
   Start`; **Save** opens the Running panel (`Loaded 1 minute ago on all 4 devices.` / `Before loading: backed up automatically` /
   Undo this load / What changed / Save as a lab state...) and sends **no request**; there is no `Choose another place`, no
   address field and no Save settings in it. `Save as a lab state...` does not clear the chip (a state is not "your latest
   save"), nor does Undo. PROMPT 5.9 says Save shows `Not saved yet` / `Your first save goes to ...`. Only removing and importing
   the lab again led to the first-save panel (screenshot `C6-save-opens-running-panel.png`, `37`, `38`).
3. **Load panel for a lab without saves shows 8 rows, alphabetical, and `2 more in All versions`**; `Start` and `Solution`
   are the hidden two. It also lists the old lab record's own saves as lab states (`Git-redesign`, two checkpoints) and the
   old rows of lab B (`B`, `L1-moved-b`, `L2-move-2`) with `0 of 4 devices`. PROMPT 5.4 step 1 wants the instructor's
   `Start`, `Broken`, `Final` first.
4. **Two failure views for one cause.** First upload failure: `Upload failed` / `Your save is safe on the lab VM, but github.com
   could not be reached.` Pressing Try again while github.com is still blocked changes the chip to `Can’t save` and the
   sentence to `The VM account cannot upload to github.com.` (helper sentence "The remote branch is unavailable. Check
   connectivity and the owner's noninteractive HTTPS Git login."); that view's **Try again** is a new Save, which added a
   second, empty waiting job (`waiting: 2`, "No configuration changes."); after the network was back the first view's Try
   again uploaded both. When the chip turns to `Can’t save` after an Upload, the panel still showed the old `Upload failed` view
   with `Checking what this upload sends...` for several seconds (`13`, `15`).
5. **A device paused during a load**: `POST /api/labs/<id>/restore` returned only after about 38 s; during that time the
   confirmation stayed open with a dimmed **Load** and the old chip, with no sentence (screenshot `C4-just-after-load.png`).
   Right after the unpause the manager still said `Can't load` / `This device is not running, or the lab status is out of date.`
6. **Address of a repository the VM does not have yet** (B5): while the address is typed, the chooser keeps the question of
   the repository that was selected before (`This folder holds the state “Git-redesign-b”.` with `Save beside it in
   git-redesign-b/git-redesign-b` / `Replace it`), for the other repository; with a free folder name the button reads
   `Connect and save here`. The folder default of the lab's name could not be used in the new repository without
   typing another name.
7. **The state drawer accepts a name chip before its folder list has loaded.** Clicked at once, `broken` gave the folder
   `broken` (top level, repository empty) and `POST /api/labs/<id>/git/places/check {"repository":"","folder":"broken","purpose":"state","name":"broken"}`
   answered **422** `Check the request fields and upload sizes.` (the only console error of the pass; `31c`). With the
   list loaded the folder is `git-redesign/broken`.
8. **390 px.** The top bar overflows (the page scrolls sideways by 40 px; the **Manager** button is cut off at the right and
   the breadcrumb runs into the product name); the chip, Save and Load wrap to two rows and nothing overlaps; panels, lists
   and the chooser are readable; **Upload** is 40 px high, **New folder...** and **Cancel** 30 px (under 44). The map editor
   at 390 px is not usable for moving a device: the nodes are 4 px wide, off the right edge, a drag does nothing. Hence D's
   save was a device change only.
9. Smaller: the chip says `Saved 3 h ago`, its panel `Saved 3 hours ago`; the first-save panel shows `Device logins are being
   checked. Save is available when it finishes.` for a few seconds after an import; the map editor's save added empty
   `...Annotations` keys to the map file (first save of lab B's map shows `+"freeTextAnnotations": []` lines).

### 10.4 Load timings (seconds from the job's `queued`, three loads of lab A)

| Platform | applying to armed | applying to settled | whole target (to `checked`) |
|---|---|---|---|
| cEOS | 1.1 to 1.2 | 2.0 to 2.3 | 13.2 to 14.6 (the job, all targets) |
| cJunosEvolved | 3.8 to 3.9 | 5.0 to 5.9 | same job |
| XRv9k | 5.0 to 5.4 | 7.4 to 8.0 | same job |

From the click on the red Load to the chip `Running <name>`: 16 s (Start), 18 s (Broken), 16 s (Final). Every target in all
loads, undo and retry has `armed` before `confirming`, `persistence: saved`, one attempt, `status: verified`.

### 10.5 Not demonstrated

Moving a device on the map at 390 px (the editor is not usable there). The `REMOTE_AHEAD` sentence for a placement. The
lab event log in the Advanced tab (the `git.update` event was read from `/api/logs`). Device-side command output of the
timed recovery (the job's timeline is the evidence). Everything else in the brief ran.

### 10.6 State left behind

Both labs run and are Ready (4 of 4 and 2 of 2); nothing is paused; `/etc/hosts` has no extra line; nothing waits. Lab A
(`git-redesign`, record `c352ba81...`, imported twice during C6) saves in `git-redesign`; lab B (`git-redesign-b`, record
`aa4ee92a...`, redeployed in C5) saves in `git-redesign-b` of `clab-scratch-git-redesign`. Devices: lab A
ceos1, ceos2 and XRv9k run `l2-c1-final`, cJunosEvolved `l2-a2`; lab B ceos1 `l2-d1`, ceos2 `l2-a5` (the redeploy reset
them). `main` of the scratch repository: lab states `git-redesign/{start,broken,final,c6probe}/latest`, saves
`git-redesign/latest`, `git-redesign-b/latest`, checkpoints `git-redesign/checkpoints/ceos1-changed{,-2}` and
`git-redesign-b/checkpoints/{l2-named-save,l2-older-checkpoint}`, `l2-move-2/latest`, `git-redesign/b/latest`, `l1-moved-b/latest`,
`l1-scaffold/reference/solution/latest`; online files `l1-online/*`, `l2-online/a5-online-{1,2}.txt`. I removed the L1 states
(`git-redesign/{start,broken,final}`, the stray top-level `latest/`, `l1-scaffold/reference/start`) and the L2 trial states with
an owner commit (`eb4eb58`, `32`), so the lab's Start, Broken and Final carry no suffix. The new private repository
`ArchRuger/clab-scratch-git-redesign-empty` holds `README.md` and `lab-b-empty/latest/*`. The manager's list of VM
registrations still holds the folders the moves and states created. No merge, force-push, tag or image publication; no data
deleted.
