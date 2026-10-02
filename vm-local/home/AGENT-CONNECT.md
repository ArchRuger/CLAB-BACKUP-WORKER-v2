# Working on clab-llm-dev2 as a remote Claude agent

This VM is the disposable containerlab dev environment for the Containerlab Node Manager
(`https://github.com/ArchRuger/CLAB-BACKUP-WORKER-v2`, release 1.29.0). Everything below was
true on 2026-09-17.

## 1. Connect

- Host: `clab-llm-dev2`, LAN address `192.168.132.132`, SSH port 22, account `clabllm`.
- Log in with an SSH key only. Send the owner your public key; they add it to
  `/home/clabllm/.ssh/authorized_keys` (currently empty). Then open a remote SSH session from the
  Claude desktop app to this host as `clabllm` with that key. Do not use the account password.
- `sudo` needs no password for `clabllm` (`/etc/sudoers.d/90-clabllm`, incl. `verifypw=any`
  so `sudo -v` works). Never run the installer or `deploy/*.sh` as root directly; they use sudo
  themselves.
- Source checkout: `~/projects/clab-manager` (git, branch work off `main`). Local `main` may be
  behind: `git fetch && git switch main && git pull --ff-only` first.

## 2. What is running

| Thing | Where |
|---|---|
| Manager UI/API | `http://127.0.0.1:8081` (also `http://192.168.132.132:8081`), container `containerlab-node-manager-backup-ui-1`, data in `/srv/containerlab-node-manager/data` |
| Rebuild loop | `cd ~/projects/clab-manager && sudo docker compose -f clab-backup-ui/compose.yml up -d --build` (state persists) |
| Capture stack | `clab-manager-capture-{gostwire,packetflix,sessions}-1`; Grafana/Prometheus stack `clab-manager-telemetry-*` (telemetry is being deprecated; do not gate on it) |
| Lab | `clab-llm-dev2`, topology `/etc/containerlab/clab-llm-dev2/clab-llm-dev2.clab.yaml`: PTX1 `n24l/cjunosevolved:26.2R1.7-EVO` at 172.20.20.2, SW1 `n24l/vjunos-switch:23.2R1.14` at 172.20.20.3 (pinned `mgmt-ipv4`); login `admin` / `admin@123`; links on the `et-0/0/0`/`et-0/0/1` aliases (this image's data ports start at `eth4`) |
| VM discovery account | `clab-discovery`; its password is in `~/.clab-discovery-password` (mode 600). The manager is already connected with it |
| Git for lab saves | checkout `~/labs/CLAB-MNGR-DEV-LLM` of `pruger-dev/CLAB-MNGR-DEV-LLM`, registered with the helper (`sudo bash deploy/setup-git.sh --list`); lab folder `clab-llm-dev2/work`, references `clab-llm-dev2/reference/{start,solution,broken-01}`, nested test folder `Week-01/BGP/Final-State` |
| GitHub logins (`gh`) | two accounts: `pruger-dev` (active; owns the lab repository, used by the Git helper through the credential helper) and `ArchRuger` (owns the manager repository). `gh auth switch -u ArchRuger` before pushing the manager source, then `gh auth switch -u pruger-dev` again so lab saves keep pushing |

## 3. Tests and tools

- Python venv: `~/projects/clab-manager/clab-backup-ui/.venv` (fastapi, httpx, paramiko, ansible,
  playwright 1.63, pexpect). The documented `/home/clabllm/clab-venv` does not exist here.
- Suites, from `clab-backup-ui/`: `PATH="$PWD/.venv/bin:$PATH" .venv/bin/python -m unittest discover -s tests -t tests` and `node --test tests/*.js`; `node --check app/static/*.js`; `git diff --check`; `python3 deploy/verify-release.py`.
- Headless Chromium needs five Ubuntu libraries this host lacks; they are unpacked in
  `~/.local/lib/chromium-deps` and `~/.bashrc` exports `LD_LIBRARY_PATH` for them. In a
  non-login shell set it yourself before running Playwright.
- Fixture browser suite: `clab-backup-ui/.venv/bin/python docs/redesign/tools/fixture_manager.py --port 8090 --data /tmp/fx &` then `CLAB_BASE=http://127.0.0.1:8090 CLAB_SHOTS=/tmp/shots .venv/bin/python docs/redesign/tools/verify_after.py`.
- Live gate scripts from the 1.29.0 validation are kept in `~/validation-tools/` (`gate_stage*.py`,
  `live_lib.py`, `junos_ssh.py`, `prep_states.py`); run them with
  `OUT=<dir> clab-backup-ui/.venv/bin/python ~/validation-tools/gate_stage1.py`. `junos_ssh.py`
  gives a direct Junos CLI (`cli(host, [commands])`).
- Health report: `bash deploy/check-install.sh --require-git`.

## 4. Rules that matter here

- Judge node readiness from the manager (`/api/state` → `ssh_ready`, the *n of m devices ready*
  header) or a real SSH login, never from `docker logs` of a node.
- cJunosEvolved boots in ~10 min, vJunos-switch in ~20 min after a deploy or redeploy. A redeploy
  gives factory configs; the saved reference states restore them from the Progress tab.
- The factory cJunosEvolved image rejects any commit without `root-authentication`; the manager's
  restore synthesises it, a manual commit must set it.
- After changing `app/host_git.py`, `host_files.py` or `host_operations.py`, refresh the VM
  helpers (`sudo bash deploy/setup-git.sh --refresh`, `sudo bash deploy/start-manager.sh ...`)
  — the container rebuild alone does not install them.
- Release procedure and documentation rules: `CLAUDE.md`, `agent instructions.md`,
  `docs/REPOSITORY-MAINTENANCE.md`. Never edit release markers by hand.
- Nothing here is precious: the lab, the checkout and the manager data can be destroyed and
  recreated (quick-install: `docs/QUICK-INSTALL.md`; the lab file is also in
  `~/labs-src/clab-llm-dev2/`).
