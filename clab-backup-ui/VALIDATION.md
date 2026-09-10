# Validation — Containerlab Node Manager 1.9.1 (2026-09-10)

## 1.9.1 evidence

- Full Python suite: **103 tests, 98 passed, 5 skipped**. Existing platform/opt-in
  skips remain. New coverage includes missing Docker labels, standard generated
  folder lookup, grouped inspect output, absolute labPath, permission errors,
  sanitized diagnostics, automatic-import retry and old-helper upgrade feedback.
- Real local Paramiko server tests exercised direct inspection plus SFTP on the
  same authenticated connection: original YAML and generated inventory read,
  permission-denied definition, and unavailable SFTP. Discovery survives file
  failures and no unrelated files are opened.
- New imports retain valid YAML when optional exports/inventory are mismatched;
  tests verify foreign credentials are discarded. Existing explicit sync remains
  atomic and preserves the saved workspace on invalid optional files.
- JavaScript regressions: **14 passed**. Production script syntax checked.
- Browser: synthetic SSH helper using the production collector, with the screenshot's
  `/etc/containerlab/<name>/clab-<name>/` layout and a sanitized 12-node BGP fixture.
  Denied YAML access produced a detected lab; clicking it attempted automatic
  import and then opened the manual form with a retry button. File details showed
  the exact denied YAML path and three found companion files. Restoring fixture
  access and clicking retry imported 12 nodes, inventory credentials and 16 map
  links with zero unmatched nodes. No files were uploaded through the form.
  General Import a lab offered the detected name and automatic retry. Right-click
  PE1 showed SSH, backup and details. No browser console errors were observed.
  Screenshot: auto-import-1.9.1.png. No live NOS actions were invoked.
- GitHub origin/main at d84c76b matches delivered 1.9.0 except the three missing
  ignore/attributes files restored here. Source ZIP and patches are verified against
  that commit, the 1.9.0 delivery, and baseline 06b8624.
- This upgrade changes the installed VM helper; --update-helper retains the current
  account and authorized key. Docker image label and static asset versions are 1.9.1.
- Docker builds, privileged Linux provisioning, Linux openat protections and access
  to the user's actual VM remain untested here. No GitHub push or VM deployment.

## Earlier 1.9.0 evidence (retained for context)

## 1.9.0 evidence

- Full Python suite: 94 tests, 89 passed, 5 existing platform/integration skips.
  Eight new removal tests verify scoped state/history removal, retained backup
  files and other labs/host credentials, absence of remote command calls,
  persistent exclusions across restarts, explicit reimport, immediate rediscovery,
  removal during an in-flight poll, active-job and stale-name guards, failed-save
  rollback, authentication, and manual import clearing a matching exclusion.
- JavaScript regressions: 14 passed. All application JavaScript syntax checked.
- Browser with synthetic local data: Cancel retains the workspace; default removal
  leaves an excluded sidebar entry, and refreshing discovery does not recreate it.
  Import again creates a new 13-node Running workspace. Removing with exclusion
  unchecked and refreshing discovery also imports a fresh workspace successfully.
  No browser console errors were observed. Screenshot: remove-lab-1.9.0.png.
- Removal has no remote side effects and performs no filesystem deletion. Saved
  backup files and shared audit logs remain on disk; prior history entries and
  credential profiles are not restored when a new workspace is imported.
- Latest fetched GitHub commit 63ca6d6 contains the 1.8.0 delivery except for the
  three ignore/attributes files restored here. Source ZIP and patches verified
  against that commit, prior 1.8.0 delivery, and original 06b8624 baseline.
- No helper/key change is required from 1.8.0. Docker/Linux deployment remains
  untested here; no changes were pushed to GitHub or deployed to the user's VM.

## Earlier 1.8.0 validation (retained for context)

## 1.8.0 evidence

- Full Python suite: 86 tests, 81 passed, 5 skipped. Added 18 VM-file tests:
  automatic import; encrypted persistence and public/log secret exclusion;
  explicit sync preserving manual endpoints, credentials, profiles, identity,
  schedules and history; pending annotation changes; bad/mismatched/missing files;
  removed deployments; old helper compatibility; authentication/offline rejection;
  custom inventory ports; saved display-name map binding; real loopback SSH file
  transport; helper paths, custom generated directories, digests and size budgets.
- The additional skip is the helper's Linux openat/O_NOFOLLOW symlink test. The
  original four platform/integration skips remain as documented below.
- JavaScript regressions: 14 passed. Application JavaScript syntax checked.
- Browser: the production app received all four files over a local Paramiko SSH
  fixture, automatically created the 13-node BGP workspace, imported credentials
  and rendered 16 links with zero unmatched nodes. A changed annotation produced
  Updates available while retaining the map. Clicking Sync from VM changed the
  saved/rendered coordinate from x=320 to x=360 and returned Up to date. Restored
  original fixture geometry afterward. Right-click node actions remain available.
- Updated the restricted helper installation and added a key-preserving upgrade.
  Added FRESH-VM-GUIDE.md covering clean Ubuntu installation through deployment,
  connectivity, keys, persistence, first lab, backups and upgrades.
- Verified complete source archive and patches against Git baseline 06b8624 and
  the previously delivered 1.7.0 source archive, and GitHub commit 4742a90. The
  fetched GitHub 1.7.0 source matches that delivery except for three absent ignore/
  attributes files, restored here. No live state/keys included.

No Docker engine, Linux VM or WSL distribution is available in this workspace.
Docker image build, privileged installation, sudoers/SSH restrictions, Linux
openat protections and real vendor-node operations remain VM deployment checks.
The helper's portable file-collection branch was tested with temporary directories;
that is not evidence that Linux provisioning has run successfully.
No code was pushed to GitHub or deployed to the user's VM.

## Earlier 1.7.0 evidence (retained for context)

Repository: ArchRuger/CLAB-BACKUP-WORKER-v2. Git baseline: 06b8624 (1.6.0 upload).
This release includes the previously delivered 1.6.1 map corrections. No changes
were pushed to GitHub or deployed to the user's VM.

## Automated evidence

- Across the full suite and focused reruns: 68 Python tests covered, 64 passed,
  4 skipped. Discovery coverage includes 21 passing tests, three of which use
  real loopback SSH. Existing JavaScript behavior tests: 14 passed.
- All application JavaScript syntax checks passed.
- Compose YAML structure checked for host networking, persistent bind mount,
  create_host_path=false, and absence of Docker port publishing.
- CRLF-aware git diff whitespace check passed. Linux shell scripts retain LF endings.
- Full source ZIP and patches verified during packaging against the v2 baseline
  and the delivered 1.6.1 source ZIP, ignoring checkout line-ending differences.

Four existing skips: two Ansible control-node integrations require Linux; one
symlink check requires Windows privileges; one EOS fixture requires the opt-in
Ansible collections environment. No additional tests were skipped for discovery.

New coverage includes registration from YAML, default kinds and prefixes, exact
node matching, multiple active labs, discovery without registration, empty and
malformed inspect output, IPv6 addresses, partial/stopped/missing/stale conditions,
credential exclusion/encryption, restart invalidation, manual endpoint retention,
reimport identity/history preservation, renamed deployment linking, stale in-flight
result rejection, unavailable node-action blocking, and scheduled-backup resumption.

Three tests run a real Paramiko server on loopback: the fixed inspect command and
JSON response, rejection of a nonzero remote exit even with plausible JSON, and a
changed SSH fingerprint blocking command execution. Other tests simulate inspection
results. No live lab devices or actual host containerlab instance were contacted.

## Browser verification

Ran the production FastAPI app with disposable local state and a loopback SSH
server returning synthetic inspect JSON. The map uses sanitized copies of the
user's actual annotation/wiring geometry.

- Saved VM password credentials through the UI and tested discovery over SSH.
- Retested the same account with blank credential fields; retained credentials
  worked and the UI reported "VM connected. Lab discovery is active."
- Confirmed Running for the 13-node lab and Not deployed for a second saved lab.
- Confirmed a discovered but unregistered lab offers setup.
- Inspected the YAML/annotation import dialog and legacy inventory alternative;
  multipart YAML import/reimport behavior is covered through the real API tests.
- Saved a deployment link from the browser.
- Set PE1's address/port to a manual endpoint, refreshed discovery, and verified
  the override remained unchanged.
- Verified the existing topology view still shows 13 nodes, 16 links, zero unmatched.
- Adjusted sidebar scrolling so saved labs and discovery controls remain accessible.
- Captured the final standalone workspace screenshot in the release artifacts.

## Deployment limits

No Docker engine or Linux/WSL execution environment is available here. The image
was not built, host networking was not exercised on Linux, and privileged VM setup,
sudoers installation and migration scripts were not executed. Script contents and
Compose structure were reviewed; Linux provisioning is the remaining deployment
validation. No real NOS backup, SuperPuTTY import, or live host discovery was run.

Follow STANDALONE-SETUP.md for a deployment test: preserve existing data, start one
standalone manager, configure the restricted account, import an edited lab YAML,
verify discovery through lab stop/redeploy, and test a real node SSH/backup. Verify
history and keys before removing the old worker. Discovery reports container state;
it does not prove that a virtual NOS has finished booting.

The source archive excludes raw uploads, preview state, tokens, private keys,
configuration captures, virtual environments and .build/. Only sanitized geometry
regression fixtures are included. Original uploaded YAML is encrypted at runtime
and omitted from public API responses.
