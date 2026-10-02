# Agent connection guide: clab-llm-dev2

As of 2026-09-18. Also published as a Claude Doc:
https://claude.ai/code/artifact/850097ee-1d9f-4b35-ab51-1e771644b0bd

## Purpose

This guide tells Claude running on the Windows desktop how to reach the Linux VM `clab-llm-dev2`
over SSH and work in the Containerlab Node Manager checkout there. The VM is the working machine
for the `clab-manager` repository (GitHub `ArchRuger/CLAB-BACKUP-WORKER-v2`); the Windows side
only drives it. Treat every command here as something to run from the Windows terminal unless the
text says it runs on the VM.

## VM facts

All values were read on the VM on 2026-09-18. The LAN address comes from DHCP, so confirm it with
`hostname -I` on the VM console if a connection times out.

| Item | Value |
| --- | --- |
| Hostname | `clab-llm-dev2` |
| LAN address | `192.168.132.132` (interface `ens33`, DHCP, gateway `192.168.132.2`) |
| SSH port | 22 |
| Account | `clabllm` (uid 1000, passwordless `sudo`) |
| OS | Ubuntu 24.04.4 LTS, kernel 6.8 |
| Host key, ED25519 | `SHA256:xBAoWISHnGhIY7xw57npoxxAq0tnhsA9arw960J9W4k` |
| Host key, ECDSA | `SHA256:+4dpYq938McE5Zjuq1CPv7K2PR1as/TMpntq6drPfBQ` |
| Host key, RSA | `SHA256:1zcqYuaq5GjeW6nzNCL3AYMXlqIPOw1r56Bf2gsNCxs` |
| Authorized keys on the account | one ED25519 key, comment `claude-code-clab-vm2` |
| Other accounts | `clab-discovery` (the manager's forced-command gateway account; never log in with it) |

## Connecting from Windows

Use the OpenSSH client that ships with Windows 10 and 11 (`ssh.exe`, `scp.exe`, `ssh-keygen.exe`)
from Windows Terminal or PowerShell. Key login is the intended route; the server still accepts a
password, so a one-time password login can install the key.

1. Check for an existing key. The VM already trusts one ED25519 key with the comment
   `claude-code-clab-vm2`. Run `Get-Content $env:USERPROFILE\.ssh\*.pub` in PowerShell; if a key
   with that comment is there, skip to step 3.
2. Otherwise create one and install it (the password prompt is answered by the owner, never stored):

   ```
   ssh-keygen -t ed25519 -f $env:USERPROFILE\.ssh\id_ed25519_clabvm -C claude-code-windows
   Get-Content $env:USERPROFILE\.ssh\id_ed25519_clabvm.pub | ssh clabllm@192.168.132.132 "mkdir -p ~/.ssh && chmod 700 ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys"
   ```

3. Add a host entry to `%USERPROFILE%\.ssh\config` (create the file if missing):

   ```
   Host clab-llm-dev2
       HostName 192.168.132.132
       User clabllm
       Port 22
       IdentityFile ~/.ssh/id_ed25519_clabvm
       IdentitiesOnly yes
       ServerAliveInterval 30
       ServerAliveCountMax 4
   ```

4. First connection: `ssh clab-llm-dev2`. Accept the host key only if the fingerprint shown equals
   the ED25519 value in VM facts (`SHA256:xBAoWISHnGhIY7xw57npoxxAq0tnhsA9arw960J9W4k`). A
   different fingerprint means a rebuilt VM or the wrong machine; stop and ask the owner.
5. Verify the session before doing work:

   ```
   ssh clab-llm-dev2 "hostname; id -nG; cat ~/projects/clab-manager/clab-backup-ui/VERSION; sudo -n true && echo sudo-ok"
   ```

   Expected: `clab-llm-dev2`, a group list containing `docker` and `clab_admins`, the release
   number (1.29.1 on 2026-09-18) and `sudo-ok`.
6. Run long work inside tmux so a dropped connection does not kill it: `tmux new -s work` on the
   VM, later `tmux attach -t work`. Copy files with `scp <file> clab-llm-dev2:~/`.
7. Claude Code is installed on the VM (version 2.1.275, user settings already set to the Fable
   model and bypass-permissions mode). Start it from the checkout:
   `cd ~/projects/clab-manager && claude`.

### Route A: the Claude desktop app opens the session itself

The desktop app can run Claude Code on the VM directly over SSH
(https://code.claude.com/docs/en/desktop.md, "SSH sessions"). In the Code tab's environment
dropdown choose **Add SSH connection** and fill in: Name `clab-llm-dev2`; SSH Host `clab-llm-dev2`
(the alias from the config file above, or `clabllm@192.168.132.132`); SSH Port empty; Identity
File `%USERPROFILE%\.ssh\id_ed25519_clabvm` (or empty when the config entry names it). The app
resolves the host through `ssh -G`, so the config alias works, and it stores the connection under
`sshConfigs` in the Windows `~/.claude/settings.json`. It installs or updates Claude Code on the VM
on first connect. Open the checkout `/home/clabllm/projects/clab-manager` as the working folder.
Password-only login is not described in the docs, so keep the key installed. Limits the docs name:
the integrated terminal stays local, and "send to Claude Code on the web" is unavailable for SSH
sessions.

### Route B: plain SSH terminal

`ssh clab-llm-dev2`, then `tmux new -s work`, `cd ~/projects/clab-manager` and `claude`. In tmux,
add `set -g allow-passthrough on`, `set -s extended-keys on` and
`set -as terminal-features 'xterm*:extkeys'` to `~/.tmux.conf` on the VM so Shift+Enter inserts a
newline instead of submitting (https://code.claude.com/docs/en/terminal-config.md). Windows
Terminal itself needs no setup.

### Not this: Remote Control

Remote Control (https://code.claude.com/docs/en/remote-control.md) runs the session on the VM
(`claude remote-control` inside tmux) and lets claude.ai or the mobile app steer it. It is the
reverse direction and needs a claude.ai subscription login on the VM; use it only if the owner
asks for phone or web access to a VM session.

## What is on the VM

The VM is a complete dev installation of the manager with one live Junos lab. Everything below was
observed running on 2026-09-18.

| Thing | Where or how |
| --- | --- |
| Source checkout | `~/projects/clab-manager`, branch `main`, in sync with `origin/main` (`398d726`), release 1.29.1 |
| Python venv | `~/projects/clab-manager/clab-backup-ui/.venv` (Python 3.12.3, app requirements, httpx, Playwright, pexpect) |
| Tools | git 2.43, gh 2.45, node 18.19, npm 9.2, Docker 29.8.1, containerlab 0.79.0, tmux, screen, Claude Code 2.1.275 |
| Manager UI and API | `http://127.0.0.1:8081` on the VM, `http://192.168.132.132:8081` from Windows; container `containerlab-node-manager-backup-ui-1`, image `clab-backup:1.29.1`, data in `/srv/containerlab-node-manager/data` |
| Side stacks | capture: `clab-manager-capture-{gostwire,packetflix,sessions}-1`; telemetry: `clab-manager-telemetry-prometheus-1` on `127.0.0.1:9090` (Grafana stopped on demand; telemetry is being deprecated, never gate on it) |
| Lab | `clab-llm-dev2` from `/etc/containerlab/clab-llm-dev2/clab-llm-dev2.clab.yaml`; copy in `~/labs-src/clab-llm-dev2/`; PTX1 `n24l/cjunosevolved:26.2R1.7-EVO` at 172.20.20.2, SW1 `n24l/vjunos-switch:23.2R1.14` at 172.20.20.3; both reported `ssh_ready` by the manager |
| Node login | `admin` / `admin@123` (lab images only); data links use the `et-0/0/0` and `et-0/0/1` aliases |
| Manager's VM account | `clab-discovery`; its password is in `~/.clab-discovery-password` (mode 600); the manager is already connected |
| Lab-save Git checkout | `~/labs/CLAB-MNGR-DEV-LLM` of `pruger-dev/CLAB-MNGR-DEV-LLM`, three helper registrations: `clab-llm-dev2/work`, `clab-llm-dev2/reference/broken-01`, `Week-01/BGP/Final-State` (`sudo bash deploy/setup-git.sh --list`) |
| GitHub logins in `gh` | `pruger-dev` (active; owns the lab repository, used by the Git helper) and `ArchRuger` (owns the manager source); both tokens carry `repo` and `workflow` |
| Validation tooling | `~/validation-tools/` (live gate scripts `gate_stage*.py`, `live_lib.py`, `junos_ssh.py`, `prep_states.py`), `~/ui-review/` (Playwright screenshot sweeps, `student_shots.py`, `readme_shots.py`) |
| Headless Chromium libraries | `~/.local/lib/chromium-deps`; `~/.bashrc` exports `LD_LIBRARY_PATH` for them. In a non-login shell (a plain `ssh host cmd`) export it yourself before Playwright |
| Older note on the VM | `~/AGENT-CONNECT.md` (written 2026-09-17); this guide supersedes it |

## Working rules once connected

Read `CLAUDE.md`, `agent instructions.md` (newest section first) and
`docs/REPOSITORY-MAINTENANCE.md` in the checkout before changing anything; they are the binding
rules and this section only points at them.

- **Sync first.** `cd ~/projects/clab-manager && git fetch && git switch main && git pull --ff-only`,
  then branch as `claude/<topic>`.
- **Delivery is a pull request.** Push the `claude/...` branch to `ArchRuger/CLAB-BACKUP-WORKER-v2`
  and open the PR with `gh pr create --base main`; the owner merges. Commit as
  `git -c user.name=clabllm -c user.email=samcolt519@gmail.com commit ...` and end commit messages
  and PR bodies with the attribution lines your session gives you.
- **Switch `gh` accounts around a push.** `gh auth switch -u ArchRuger` before pushing manager
  source, then `gh auth switch -u pruger-dev` again so the Git helper keeps pushing lab saves.
  Check with `gh auth status`.
- **Tests, from `clab-backup-ui/`:**
  `PATH="$PWD/.venv/bin:$PATH" .venv/bin/python -m unittest discover -s tests -t tests`,
  `node --test tests/*.js`, `node --check app/static/*.js`, `git diff --check`,
  `python3 deploy/verify-release.py`. CI runs an explicit file list, so add any new test file to
  `.github/workflows/release-check.yml`.
- **Record what ran.** Every code change updates `clab-backup-ui/VALIDATION.md` and
  `docs/CHANGELOG.md`; write only what was actually executed, and say when a check was fixture-only.
- **Rebuild loop.** `sudo docker compose -f clab-backup-ui/compose.yml up -d --build` from the
  checkout recreates the manager with its data intact. After editing `app/host_git.py`,
  `host_files.py` or `host_operations.py`, refresh the VM helpers too
  (`sudo bash deploy/setup-git.sh --refresh`, or `sudo bash deploy/start-manager.sh`); the image
  rebuild alone does not install them.
- **Judge readiness from the manager.** Use `/api/state` (`ssh_ready`, the *n of m devices ready*
  header) or a real SSH login, never `docker logs` of a node. cJunosEvolved boots in about
  10 minutes and vJunos-switch in about 20 after a deploy or redeploy; a redeploy gives factory
  configs and the saved reference states restore them from the Progress tab. The factory
  cJunosEvolved image rejects any commit without `root-authentication`.
- **Browser checks without the lab.**
  `clab-backup-ui/.venv/bin/python docs/redesign/tools/fixture_manager.py --port 8090 --data /tmp/fx &`,
  then `CLAB_BASE=http://127.0.0.1:8090 CLAB_SHOTS=/tmp/shots .venv/bin/python docs/redesign/tools/verify_after.py`.
  Stop the fixture only with an anchored pattern,
  `pkill -f "^[^ ]*python[^ ]* docs/redesign/tools/fixture_manager.py"`, in its own command; an
  unanchored `pkill -f fixture_manager` kills the calling shell.
- **Health report.** `bash deploy/check-install.sh --require-git` on the VM.
- **Never edit release markers by hand;** `python3 deploy/set-release.py X.Y.Z` is the only way to
  move them, and no release is cut until browser plus live-lab validation is recorded.

## Limits and things not to do

The VM is disposable, but a rebuilt lab costs about 20 minutes of boot time, so treat it as shared
working state rather than scratch.

- **Root login and the gateway account.** `PermitRootLogin` is key-only and no root key is
  installed; work as `clabllm` and use `sudo`. Never log in as `clab-discovery`: its only purpose
  is the manager's forced-command gateway.
- **Do not run installers as root.** `deploy/*.sh` and `install-manager.py` call `sudo` themselves;
  running them under `sudo` breaks the owner-scoped Git and helper setup.
- **Do not destroy or redeploy the lab unless the task asks for it.** `sudo containerlab destroy`
  or a redeploy resets both nodes to factory configuration and the reference states must be
  reapplied from the Progress tab.
- **Do not touch manager data by hand.** `/srv/containerlab-node-manager/data` belongs to
  uid 10001; never construct a `Store` against it from a test, and never delete `state.key`.
- **Telemetry is being deprecated.** Prometheus is up, Grafana is stopped on demand; observe it,
  never gate a change on it.
- **Node.js is 18.** Claude Code's native binary does not care, but do not
  `npm install -g @anthropic-ai/claude-code` here; use `claude update` or the native installer.
- **Playwright needs the library path.** A non-login shell (`ssh host cmd`, the desktop app's SSH
  session) does not source `~/.bashrc`; export `LD_LIBRARY_PATH=$HOME/.local/lib/chromium-deps`
  before headless Chromium.
- **Secrets stay on the VM.** The node password, `~/.clab-discovery-password` and the `gh` tokens
  are never copied into documents, commits or PR text.
- **The address is DHCP.** If `192.168.132.132` stops answering, read `hostname -I` on the VM
  console and update the `HostName` in the Windows SSH config rather than accepting a new host key
  blindly.

## Troubleshooting

| Symptom | Check | Fix |
| --- | --- | --- |
| `Permission denied (publickey,password)` | Key not in `~/.ssh/authorized_keys` on the VM, or `IdentityFile` wrong | Repeat step 2; `ssh -v clab-llm-dev2` shows which key was offered |
| `WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED` | Compare the printed fingerprint with the ED25519 value in VM facts | Matches after a VM rebuild: remove the old line with `ssh-keygen -R 192.168.132.132`; does not match: stop and ask the owner |
| Connection times out | DHCP address moved, or the VM is down | `hostname -I` on the VM console; ping `192.168.132.2` (gateway) from Windows |
| `permission denied ... docker.sock` | Session started before the `docker` group was granted | Log out and back in, or prefix `sudo docker` |
| `sudo: a password is required` | Running as another account | Only `clabllm` has the passwordless rule (`/etc/sudoers.d/90-clabllm`) |
| `/api/git/repositories` answers 409, Progress tab shows an error | Helper `VERSION` differs from the manager after an upgrade | `sudo bash deploy/setup-git.sh --refresh`, then rebuild with `start-manager.sh` |
| Manager port 8081 not answering | Container not running | `sudo docker ps`; `sudo docker compose -f clab-backup-ui/compose.yml up -d` from the checkout |
| Lab nodes show not ready | Still booting (10 min PTX1, 20 min SW1) | Wait; judge from `/api/state`, not `docker logs` |
| Push rejected for `.github/workflows` | Active `gh` account lacks `workflow` scope | `gh auth status`; `gh auth refresh -h github.com -s workflow` |
| Push goes to the wrong account | `gh auth switch` not done | `gh auth switch -u ArchRuger` for manager source, back to `pruger-dev` afterwards |
| Chromium fails to start under Playwright | `LD_LIBRARY_PATH` unset in a non-login shell | `export LD_LIBRARY_PATH=$HOME/.local/lib/chromium-deps` |
| Shift+Enter submits inside tmux | tmux passthrough not configured | Add the three `~/.tmux.conf` lines from Route B, restart tmux |
| Shell exits with code 144 after `pkill` | Unanchored `pkill -f fixture_manager` matched the shell | Use the anchored pattern from Working rules, in its own command |
