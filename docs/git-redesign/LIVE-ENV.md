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
