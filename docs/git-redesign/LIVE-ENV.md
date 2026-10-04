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
