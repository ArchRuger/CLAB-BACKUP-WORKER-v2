# D02b: Git save and load, course structure, naming, telemetry retirement (2026-10-27)

Release 1.31.6, branch `claude/parity-campaign`. Files audited: `docs/GIT-SETUP.md`, `docs/GIT-PROGRESS.md`,
`docs/COURSE-STATES.md`, `docs/NAMING.md`, `docs/TELEMETRY.md`. Method: every bold label and inline-code
string was extracted and searched in `clab-backup-ui/app` and `deploy` (a script, then reading the matching line),
and the rest of each claim (routes, options, defaults, layout) was read against the code. Static reading only:
no browser, VM or live-device check was run.

| File | Claim | What the code says | Action |
|---|---|---|---|
| GIT-PROGRESS.md (Choosing a folder) | Typing an address turns the button into **Connect and save here** | `git-places.js:487`: the button stays **Save here**, disabled until an address is typed; no "Connect and save here" string exists | fixed |
| GIT-PROGRESS.md (confirmation table) | Row word `Can't load` | `load.js:251` uses `Can’t load` (typographic apostrophe) | fixed |
| GIT-PROGRESS.md (confirmation buttons) | Drawer `What's different` | `save-drawers.js:807` title is `What’s different` | fixed |
| GIT-PROGRESS.md | Chip states, panel lines, `Upload`/`Not now`/`See changes`/`Details`/`Keep snapshot only`, checkpoint, starting point, first-save panel, three folder questions, folder-chooser lines | strings and buttons found in `status.js`, `save-header.js`, `git-places.js`, `save-drawers.js`, `git-progress.js` | correct |
| GIT-PROGRESS.md | Load list (`Your saves`, `Lab states`, 8 states, 3 checkpoints), row words, result words, `Options` 5 min default 2 to 60, `Undo this load`, `Try n devices again` | `load.js` (`LOAD_STATE_CAP=8`, `LOAD_OWN_CHECKPOINTS=3`, `LOAD_MINUTES=5`), `status.js` `STATUS_LOAD_WORDS` | correct |
| GIT-PROGRESS.md | Old links: `view=progress|git` open Topology with the chip panel, `save-location|save-settings` open Save settings, `saved-versions|versions` open All versions; no Progress tab | `app.js` `TAB_ALIAS`, `SAVE_ROUTES` | correct |
| GIT-PROGRESS.md | Platforms that can be loaded; transaction commands (`load override terminal`, `rollback clean-config`, `commit timer`, `commit replace confirmed`, `write memory`); IOS XR banner refused | `restore_junos/eos/iosxr.py` `SUPPORTED_KINDS`, command strings, `BANNER_LINE` | correct |
| GIT-PROGRESS.md | Limits: 500 devices, 2 MiB per file, 16 MiB total; name up to 120; failed catch-up not repeated for ten minutes | `host_git.py` `MAX_FILE`, `MAX_TOTAL`, `SUMMARY_DEVICES`; `git_progress.py` `NOTE_LIMIT`, `UPDATE_PAUSE=600` | correct |
| GIT-PROGRESS.md | Registration lock `git.json.lock`, `<checkout>/.git/clab-manager/` | `host_git.py:1426`, journal under the checkout | correct |
| GIT-SETUP.md | Wizard options `--guided --repo --subfolder`, `setup-git.sh --repo --owner --remote --prefix --label`, `--list`, `--refresh` (alone), `install.sh --git` | `deploy/setup-git.sh`, `git-onboard.py:270`, `install-manager.py:729` | correct |
| GIT-SETUP.md | Waiting-save refusal sentences; REMOTE_AHEAD / not-manager-saves sentences; select_account URL printed by the wizard; clone into `~/labs/REPOSITORY`; noreply commit email | `host_git.py:54-60,1082,1392`, `git-onboard.py:17-20` | correct |
| GIT-SETUP.md | Health check: none; the guide never claims every registration is verified | `deploy/check_git.py` `MAX_REPOSITORIES = 20`; `docs/HEALTH-CHECK.md` already says "at most 20 registrations ... remaining ones unverified" | correct (open follow-up stays with the script, not a guide) |
| GIT-SETUP.md | Wizard "reports **Registered** and **Ready**" | `setup-git.sh:135` prints `Registered <label> ...`; `git-onboard.py:573` prints `Ready.` after a SUCCESS banner | correct |
| COURSE-STATES.md | Save-as-lab-state drawer, `State Start saved in BGP/start.`, `“Start” already exists here.`, `Replace it`/`Use another name`, `Put it somewhere else`, `Saved 21 min ago`, `Running Start`, view-only wording, `2 of 4 devices`, `Not in this state`, `Start the lab to load a state`, `Saved on a different topology` | `save-drawers.js:712`, `git-places.js:399-402`, `status.js:217`, `load.js` | correct |
| COURSE-STATES.md | Repository layout `<state>/latest/{manifest.json, cfg, clab.yml, annotations}`; fast-forward `Update from the repository` in Save settings > Git details | `git_places.py`, `save-drawers.js` | correct |
| NAMING.md | Loadable platforms (`juniper_cjunosevolved`, `juniper_vjunosswitch`, `arista_ceos`, `cisco_xrv9k`) | `SUPPORTED_KINDS` in the three drivers (vQFX, vJunos-router and vSRX are saves only) | correct |
| NAMING.md | Scaffold: `init`, `snapshot`, `--states`, `--yes`, default `start,solution,broken-01`, `reference/` and `work`, `This upload also sends: <lab>: <name>`, `rebound to`, `Cannot reach the manager`, proxy ignored; `deploy/lab-template/` | `deploy/scaffold-lab.py:36,38,66,181,216-311`; `lab-template/bgp-core.clab.yaml` present | correct |
| NAMING.md | `bgp/latest/start` is saved as `bgp/start` | rule `colliding()` in `git_places.py` / `host_git.py` | correct |
| TELEMETRY.md | Retirement notice only; `retire-telemetry.sh` options `--purge --dry-run --no-recreate`, auto-run by `start-manager.sh`, archive `telemetry-retired-<UTC stamp>/`, two pinned images, Compose project label, `TELEMETRY_*` lines removed, health row `Retired telemetry stack`; manager notice, `Review and remove…`, dialog `Retired telemetry configuration`, menu path Lab actions > Advanced options > `Retired telemetry configuration…`, `Remove from devices`, `Forget`, outcomes `removed/absent/failed/skipped` | `deploy/retire-telemetry.sh`, `retire_telemetry.py`, `app.js:118,289`, `operations.js:117-131`, `index.html:136`, `telemetry_retirement.py`, `check_install.py:633` | correct (no current telemetry or Grafana instruction found) |

Counts: 3 fixed, 0 cannot verify as a claim; roughly 160 label and message strings matched.
Not verified: the wizard's interactive prompts beyond the lines read, the live GitHub login flow, and everything
that needs a browser or VM.

## External URLs

| URL | File | Status |
|---|---|---|
| https://cli.github.com/manual/gh_auth_login | GIT-SETUP, GIT-PROGRESS | ok |
| https://cli.github.com/manual/gh_auth_setup-git | GIT-SETUP, GIT-PROGRESS | ok |
| https://manpages.ubuntu.com/manpages/noble/man5/sources.list.5.html | GIT-SETUP | ok |
| https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/about-authentication-to-github | GIT-PROGRESS | ok |
| https://github.com/login/device/select_account | GIT-SETUP | ok (shows the GitHub sign-in page when not signed in; expected) |
| https://packages.ubuntu.com/noble/gh | GIT-PROGRESS | HTTP 500 on two tries; transient server error, not shown dead |
| https://github.com/OWNER/REPOSITORY.git | GIT-SETUP | placeholder, not fetched |
