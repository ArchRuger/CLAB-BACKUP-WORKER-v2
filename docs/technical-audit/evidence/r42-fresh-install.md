# Fresh-install evidence: release 1.30.42, unmodified Ubuntu 24.04

Independent verification (route: clab-ui-qa), run against a brand-new nested QEMU/KVM VM that
never had the manager, Docker or containerlab — not a repaired or reused VM. Everything below
happened inside that nested VM under a scratch directory; the host's own manager (port 8081),
its lab, `/srv` and `/etc` were never touched, and no `sudo` ran on the host except starting QEMU
through the `kvm` group (`sg kvm -c '...'`, no password).

Driver: `docs/technical-audit/tools/fresh_install_vm.py` (stdlib + paramiko from
`clab-backup-ui/.venv/bin/python`), run stage by stage from an interactive shell. Source: `git
archive` of commit `0cd18a7` (release 1.30.42, branch `claude/technical-audit`), verified in the
guest with `deploy/verify-release.py` before the installer ran.

## Environment

| Item | Value |
|---|---|
| Base image | `noble-server-cloudimg-amd64.img`, sha256 `612b2c0c…d7354` (matches `SHA256SUMS`) |
| Guest OS | Ubuntu 24.04.5 LTS, kernel `6.8.0-139-generic` |
| vCPUs / memory / disk | 6 / 8192 MiB / 30 GiB sparse qcow2 (`-b` backed by the base image) |
| Guest account | `student`, NOPASSWD sudo via cloud-init, key-only SSH on a host-forwarded port |
| Pre-install absence | `docker`, `containerlab`: **absent** (`command -v` failed); `/srv/containerlab-node-manager`, `/etc/clab-manager`: **absent** |
| Disk before install | `/dev/vda1` 29G, 1.9G used, 27G avail |
| Source | `~/projects/clab-manager`, `deploy/verify-release.py` → `Source release verified: 1.30.42` / `Documentation names only release 1.30.42.` |

## Phases (`bash deploy/install.sh`, Setup menu choice `1`, standard path)

| Phase | Result | Closing line / evidence |
|---|---|---|
| Setup menu | PASS | Printed the menu; chose `1`. |
| 1/6 Administrator access and settings (`sudo -v`) | PASS | Prompted `[sudo] password for student:` — see note below; answered, then `Completed: 1/6 Administrator access and settings`. |
| 2/6 VM prerequisites | PASS | `Completed: 2/6 VM prerequisites` (Docker, Compose, containerlab installed; obsolete-media APT repair ran automatically, standard path). |
| 3/6 Password, helpers, image and manager | PASS | `New password:` / `Retype new password:` for the `clab-discovery` account, answered with a locally generated password (never written to disk or evidence); `Completed: 3/6 Password, helpers, image and manager`. |
| 4/6 Browser Wireshark capture stack | PASS | `Completed: 4/6 Browser Wireshark capture stack` (pulled `ghcr.io/siemens/packetflix`, `ghcr.io/siemens/ghostwire`, the pinned Wireshark image; built `clab-capture-service:1.30.42`). |
| 5/6 Running manager verification | PASS | `Manager 1.30.42: running; HTTP and version checks passed.` / `Completed: 5/6 Running manager verification`. |
| 6/6 Engineer access for VS Code | PASS | `Engineer access ready for student: …` / `Completed: 6/6 Engineer access for VS Code`. |
| lazydocker (own step, never fails install) | PASS | `lazydocker 0.25.2 installed to /home/student/.local/bin/lazydocker.` |
| Git setup, auto-started | Stopped by design | `Manager installation is ready. Git is a separate setup step under your ordinary account.` then the Git wizard's first prompt `Where are your lab configurations going?` — interrupted here with Ctrl-C (GitHub device login is out of scope for a nested VM with no browser). |

**Exact closing lines after Ctrl-C** (verbatim, from `installer.log`, kept in scratch only):

```
Git setup cancelled. Completed files and login are retained; readiness has not been confirmed.
Resume as the same Linux account, without sudo:
  bash /home/student/projects/clab-manager/deploy/setup-git.sh

Setup stopped. Existing data is retained; rerun this installer to continue.
```

The shell's own `$?` after that was `1` (`INSTALLER_SESSION_DONE_1`), and the process exited; no
`install.sh`/`setup-git.sh` process was left running in the guest afterwards (checked with `ps
aux`). There is no separate "Grafana dashboards" phase in this release, confirming the phase list
above.

**Note on the `sudo -v` password prompt.** `deploy/install-manager.py`'s phase 1 runs a bare `sudo
-v` (validate only, no command). On this seeded account — a member of the `sudo` group (`%sudo
ALL=(ALL:ALL) ALL`, password required) that *also* has a per-user `NOPASSWD:ALL` cloud-init entry —
sudo's validate-only check still asked for a password (confirmed independently: `sudo -n true`
succeeds passwordless, `sudo -n -v` fails with `sudo: a password is required`; every *specific*
command the installer runs afterwards, e.g. `sudo bash deploy/start-manager.sh`, is passwordless).
This is a genuine sudo/Ubuntu behaviour for an ordinary `sudo`-group account, not a manager defect,
and it is exactly the quick-install guide's own documented `[sudo] password for <account>:` row; the
driver answers it with the account's own login password (created only for this VM, never written to
evidence). Total installer wall time from launch to reaching-and-leaving the Git wizard: about 8
minutes (12:41:53–12:50:11 UTC); per-phase timings were not separately instrumented.

## Health check (`deploy/check-install.sh`, run as `student`, no `sudo` prefix)

Three runs; full text of the third is saved as `r42-fresh-install-health.txt` (identical to the
second except a 0.3-point free-space percentage from the rebuild).

| Run | When | PASS | FAIL | WARN | SKIP | INFO | Overall |
|---|---|---|---|---|---|---|---|
| 1 | Right after install, before any VM connection | 31 | 0 | 3 | 2 | 2 | NEEDS ATTENTION (exit 2) |
| 2 | After the optional VM-connection test (step 5) | 54 | 0 | 3 | 0 | 3 | NEEDS ATTENTION (exit 2) |
| 3 | After the repeat "upgrade" run of `start-manager.sh` | 54 | 0 | 3 | 0 | 3 | NEEDS ATTENTION (exit 2) |

No `FAIL` row in any run. `[PASS] Retired telemetry stack — No retired telemetry containers,
volumes, .env keys or leftover folders were found.` in every run.

**Non-PASS rows (run 1, before the VM connection):**

- `[WARN] git helper installation` — Missing, unsafe or stale helper files; privileged helper
  execution will be skipped: `/usr/local/sbin/clab-manager-git`, `/usr/local/lib/clab-manager/host_git.py`,
  `/etc/sudoers.d/clab-manager-git`. *Next:* `sudo bash …/deploy/setup-git.sh --refresh`. — expected: Git
  setup was deliberately not completed.
- `[WARN] Saved VM connection` — Enabled VM connection and saved host fingerprint are not ready. —
  expected: no VM connection test had been made yet.
- `[WARN] Git repository registry` — No Git checkout is registered. — expected.
- `[SKIP] Topology browser over saved SSH connection` — Complete VM connection setup before this
  check can run. — expected, follows from the WARN above.
- `[SKIP] Git registry through saved SSH connection` — A working manager and saved VM connection
  are required. — expected.
- `[INFO] Optional Proxmox guest agent` — not confirmed installed; not required. — expected (this is
  a plain QEMU guest, not Proxmox).
- `[INFO] Online lab downloads` — disabled intentionally by default. — expected default.

**Non-PASS rows (runs 2 and 3, after the VM connection is saved and tested):**

- `[WARN] git helper installation` — same as above; still expected (Git setup still not completed by
  design).
- `[WARN] Folder coverage` — Stopped after 20 folders; more folders remain unchecked. — expected: the
  containerlab package ships many example-lab subfolders under `/etc/containerlab/lab-examples`,
  past the health check's own `--max-folders 20` default.
  `Browse folder: …` rows for `/etc/containerlab`, `/srv/containerlab-node-manager/projects` and 18
  of the shipped `lab-examples/*` subfolders all `PASS`.
- `[WARN] Git repository registry` — same as above; still expected.
- `[INFO] Git registry through saved SSH connection` — Local Git helper files are missing or
  unverified; the SSH request was skipped. — expected (follows from the Git helper not being
  installed).
- `[INFO] Optional Proxmox guest agent`, `[INFO] Online lab downloads` — unchanged, expected.

## Absence proofs (retired telemetry stack, never installed)

All gathered non-interactively as `student` (some via `sudo`, all passwordless for the specific
commands, per the note above):

- `docker ps -a --format '{{.Names}} {{.Image}} {{.Status}}'` → exactly four containers:
  `containerlab-node-manager-backup-ui-1` (`clab-backup:1.30.42`),
  `clab-manager-capture-sessions-1` (`clab-capture-service:1.30.42`),
  `clab-manager-capture-packetflix-1`, `clab-manager-capture-gostwire-1`. No telemetry container.
- `docker volume ls` → empty (header only).
- `docker images` → `clab-backup:1.30.42`, `clab-capture-service:1.30.42`,
  `ghcr.io/siemens/ghostwire@…`, `ghcr.io/siemens/packetflix@…`,
  `ghcr.io/srl-labs/wireshark-vnc-docker@…`. No `prometheus` or `grafana` image.
- `ss -ltnp` → `22` (all interfaces), `127.0.0.1:5801`, `127.0.0.1:5001`, `0.0.0.0:8081`, plus the
  systemd-resolved loopback stub. No `3000`, no `9090`.
- `grep -c TELEMETRY clab-backup-ui/.env` → `0`.
- `ls /srv/containerlab-node-manager` → `data`, `projects`. No `telemetry` folder.
- `sudo bash deploy/retire-telemetry.sh --dry-run --no-recreate` → *"Nothing to retire: no telemetry
  containers, volumes, networks, images, files or .env keys were found."* (the never-installed
  case, exactly as expected). Ran twice (once per health-check-relevant snapshot); identical result
  both times.
- `sudo grep -c grafana /usr/local/lib/clab-manager/host_operations.py` → `0`.
- Helper versions: `clab_manager_files.py` → `helper_version: '1.30.42'`; `host_operations.py` →
  `VERSION = '1.30.42'`. `host_git.py` is correctly **absent** (Git setup was not completed), matching
  the `git helper installation` WARN above.

## Repeat-upgrade case

`sudo bash deploy/start-manager.sh` run a second time, non-interactively (the `clab-discovery`
password already existed, so no prompt): `retire-telemetry.sh --no-recreate` again reported
*"Nothing to retire…"*; the capture stack and the manager image were rebuilt and their containers
recreated (expected — this is the documented "upgrade" behaviour, always rebuilds); all four
containers came back `Up`. The following health check (run 3 above) reported the identical
PASS/FAIL/WARN/SKIP/INFO counts as run 2. No telemetry stack reappeared.

## Reboot cycle

`sudo reboot`, then polled for SSH and `cloud-init status --wait` (guest came back with the same
benign `degraded done` status as the first boot — a `chpasswd.list` deprecation notice, not a new
fault). After the reboot:

- `docker ps --filter name=backup-ui` → `containerlab-node-manager-backup-ui-1 Up 16 seconds`
  (restart policy brought it back automatically).
- The three capture containers → all `Up 16 seconds`.
- `curl -s http://127.0.0.1:8081/api/state` → `version: "1.30.42"`, `labs: []`, discovery
  `connected: true` with a fresh `checked_at`/`last_success` (the saved VM connection also survived
  the reboot and reconnected on its own).
- `docker ps -a --format '{{.Names}}' | grep -i telemetry` → `NONE` (grep found nothing, echoed
  the fallback).

## Optional VM connection (step 5, bounded, ~1 minute used)

Read `app/discovery.py` (`save_host` / `HostSettings` / `consume_host_bootstrap`) and
`app/static/management.js` to confirm the *Save and test connection* button is `PUT /api/host`
followed by a discovery refresh, and that an empty `password` field reuses the already-saved
bootstrap password when the address/port/username are unchanged (`host['password'] = data.password
or (old.get('password','') if same else '')`). Called both endpoints from inside the guest with
`curl` (same-origin: no `Origin` header, JSON body, non-empty `Content-Length`), address
`127.0.0.1`, port `22`, user `clab-discovery`, **empty password field** (the seeded password was
never re-entered or written anywhere):

- `PUT /api/host` → accepted; `bootstrap_pending` flips from `true` to `false`.
- `POST /api/discovery/refresh` → `connected: true`, `error: ""`, `fingerprint:
  "SHA256:EKVxb8cjEu43z/3TvNmi4Xs4mGSM/6R+/Zj3yr+7EnE"` (equal to the `bootstrap_fingerprint`
  recorded by setup, so it was pinned rather than replaced), `file_reader: "helper"`,
  `file_import_supported: true`, `helper_version: "1.30.42"`.

This is the manager's own connected/discovery-ok state (`discovery.ok` in the UI's terms is exactly
`connected && !error`, both satisfied). The subsequent health-check jump from 31→54 PASS rows (run 1
→ run 2 above) is the direct, observed effect of this one call.

## Shutdown and artifact sizes

`sudo poweroff` over SSH, then the driver polled `/proc/<pid>` for the QEMU process: it exited
cleanly within the wait window (no `SIGTERM` needed). Left in the scratch directory (never copied
into the repository):

| File | Size |
|---|---|
| `disk.qcow2` (backed, sparse) | 3.9 GiB |
| `noble-server-cloudimg-amd64.img` (base image, untouched) | 597 MiB |
| `clab-manager-0cd18a7.tar.gz` (source archive) | 89 MiB |
| `installer.log` (raw pty transcript, includes Compose's redrawing progress spinner) | 5.0 MiB / ~21,200 lines |
| everything else (JSON/`.txt` results, `seed.iso`, keys, `console.log`) | a few hundred KiB total |

`installer.log` was **not** copied into evidence: it is far over the ~200-line budget by
construction (terminal spinner redraws), and every fact in it that matters is already extracted and
quoted above. Its content was grepped for the two secrets that ever crossed that channel (the
generated `clab-discovery` password and the guest login password); neither appears — see "Non-PASS
health rows" above for the corroborating live checks that depended on the password actually
having worked.

## Limitations

- GitHub device-code login was deliberately not attempted: no browser is available inside (or from)
  the nested VM, and it is a separate, already-documented step (`docs/GIT-SETUP.md`). The installer's
  own behaviour when stopped there (files/login retained, resumable via `deploy/setup-git.sh`, no
  Git checkout registered) was captured and is reported as `WARN`/`INFO`, not treated as a failure.
- Per-phase wall-clock timings were not individually instrumented (only the phase-completion order
  from the transcript and the overall installer runtime are reported); a future run of the same
  driver could add timestamps around each `_pump` call if per-phase duration is wanted.
- No screenshots or browser automation were used for this task; it is entirely SSH/API text
  evidence (VM boot, installer pty session, `curl` against the manager's own API, `docker`/`ss`
  inventory). No browser check was attempted or claimed.
- This is a single nested-KVM run; it does not by itself prove behaviour on bare-metal or on a
  different hypervisor. `/dev/kvm` was present and used for the guest itself, but no lab image or
  device was deployed in this task (out of scope — the fresh-install proof only needed the manager,
  not a running lab).
