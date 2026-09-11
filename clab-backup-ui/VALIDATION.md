# Installer clock recovery — 1.16.1

- Prepared from merged GitHub main `58a17bd` (1.16.0); commit/push is pending.
- 105 focused tests passed: APT clock/update handling 17, installer 14, Git
  wizard 40, registrations 9, APT sources 14, release consistency 7 and helper
  preflight 4. System/package commands were mocked; no clock was changed.
- Covered the reported future Release date error, expired/stale metadata,
  synchronized/manual/unavailable clocks, bounded active-NTP waits using
  monotonic time, strict APT checks, streamed output and original failure codes.
  Git package setup stops before installation after a failed update.
- ShellCheck passed for install.sh, install-prerequisites.sh, setup-git.sh and
  start-manager.sh. Source consistency reports 1.16.1. Documentation adds
  pre-bootstrap clock checks and recovery within the original paused run.
- No live Ubuntu package installation, NTP recovery, Docker build or VM
  deployment was performed. The new CI test entry is prepared locally.

# Consolidated terminal installer — 1.16.0

- Prepared from local 1.15.3 commit e64790a; latest fetched main was 0658562.
- 88 focused tests passed: installer 14, Git wizard 40, read-only registrations 9,
  APT source handling 14, release consistency 7 and helper preflight 4.
- Covered step retry/cancel, real-owner environment, retained .env bytes, custom
  ports/IPv6 and version failures, registered checkout selection, custom binding
  preservation/rechecks, URL correction, login recovery, identity repair and
  exact APT backups that preserve network sources, disabled Docker repositories,
  and explicit local Docker targeting. Package/sudo commands were mocked.
- ShellCheck passed for install.sh, install-prerequisites.sh, setup-git.sh and
  start-manager.sh. Source verification reports 1.16.0. Git whitespace checks passed.
- CI now includes these stdlib regression tests and installer shell syntax checks;
  the updated workflow has not yet run on GitHub.
- No fresh Ubuntu install, live GitHub authorization, package installation,
  Docker build or VM deployment was performed here. Validate the complete path
  on a disposable Ubuntu 24.04 VM before treating it as a verified VM install.

# Git owner and identity guidance — 1.15.3

- Based on merged main 0658562. Guided setup accepts an existing checkout directly,
  repairs invalid identity, and retains valid settings and the owner's environment.
- 19 onboarding tests passed, including existing-checkout resume without cloning,
  blank input retry, invalid identity repair and preservation of valid identity.
  Seven release-consistency and four helper-preflight tests passed (30 total).
- ShellCheck passed for setup-git.sh and start-manager.sh. Source verification
  reports 1.15.3; Git whitespace checks passed.
- Shell registration still runs Git only after dropping to the owner. Failure
  guidance retains custom registration settings and provides absolute paths.
- No live Ubuntu registration, package installation, Docker build or deployment
  was performed. Changes are prepared locally for user commit and push.

# Guided Git setup recovery — 1.15.2

- Based on GitHub main 698fabb, preserving the latest user wiki edits.
- Reject GitHub branch/file page URLs before choosing a directory or authenticating;
  retain HTTPS repository URLs and nested namespaces on other Git hosts.
- Package-update failures stop before installation, with source-repair instructions;
  package-install errors report their own recovery step. System sources are not edited.
- Focused validation passed: 15 onboarding tests, seven release-consistency tests
  and four helper-preflight tests (26 total). Source verification reports 1.15.2;
  the Git whitespace check passed. These are local tests with mocked package commands.
- No live Ubuntu package installation, Docker build, VM upgrade or push was performed.

# Repository consistency repair — 1.15.1

- Audited current GitHub main b0389ba and reproduced its source/helper version
  mismatch. Corrected VERSION to match the existing 1.15.1 runtime components.
- Seven release-consistency tests and four helper-preflight tests passed. Cases
  include the stale VERSION file, each runtime metadata location, empty lab
  inventory, malformed responses, and version errors without credential leakage.
- Source consistency check, launcher ShellCheck and Git whitespace checks passed.
- New GitHub Actions workflow is prepared but has not run on GitHub. Docker build
  and fresh-VM launch have not been executed here. No remote push was performed.
- Existing runtime code is retained; the historical full-suite results below
  describe their original runs, not a new full-suite run for this cleanup.

# Git progress validation — 1.15.0

- Baseline: GitHub main 160fe5e. This cumulative source release includes the prior
  VM password and UI/diagram changes documented below.
- Full Python suite: 204 tests run, 198 passed, 6 platform/opt-in skips.
  Includes 20 host Git tests (real disposable repositories/bare remotes and mocked
  production dispatch), 19 coordinator tests, four bounded SSH transport tests,
  and five worker logging/persistence recovery tests. Existing backup, password,
  topology, file-transfer and lab-operation regressions also passed.
- Real Git cases cover exact artifact bytes, unrelated/staged work, foreign
  outgoing commits, no-op saves, baseline-only changes, checkpoint uniqueness,
  changed remotes, fast-forward updates/divergence, failed pushes, ancestor-save
  reconciliation, interrupted writes/commits and retries after owner repairs.
  A no-change save compares as empty; long and reserved device names export safely.
- Coordinator tests cover exact selected scope, incomplete captures, provenance,
  idempotency, review preferences, retry-without-push, lost replies, capture-ID
  persistence failure, restart recovery, pending-save guards and version ZIPs.
- JavaScript: 38 tests passed, including 14 Git workflow tests for payloads,
  escaped output, destination acknowledgement, historical target selection,
  request-ID reuse, double-click prevention and modal/polling behavior.
- Browser QA used an isolated local manager, synthetic device captures and real
  local Git checkouts/remotes. Checked repository selection, one-click save,
  diff/version viewing, ZIP download, checkpoint capture, failed push and retry,
  and baseline from an older capture. Verified retry created no new capture and
  baseline left latest untouched. No real VM/device/remote account was accessed.
- ShellCheck passed for setup-git.sh, start-manager.sh and clab-manager-gateway.
  Deploy shell files remain LF; Python source/embedded setup code compile.
- The source ZIP and cumulative patch are verified against clean 160fe5e. The
  package excludes preview state, environments, real captures and credentials.
- Linux sudo/UID transitions, the owner's noninteractive HTTPS credential helper,
  Docker image build and real NOS captures still require deployment validation.
  Mocked privilege-order checks do not establish live Linux permission behavior.
  No GitHub push, registry publication or deployment was performed. Load version
  retrieves files; applying configurations to live devices remains unavailable.

# UI and diagram validation — 1.14.0

- Baseline: GitHub main 160fe5e; includes the 1.13.0 VM password changes below.
- Full Python suite: 156 tests run, 150 passed, six platform/opt-in skips.
  New tests cover saved annotation persistence/restart, unchanged wiring/no VM writes,
  unsaved export, XML escaping, JSON style round-trip, invalid input, stale-map
  conflicts and rollback after failed saves.
- JavaScript: 24 tests passed. New geometry/payload tests cover line movement,
  coordinate limits, node identity and revision retention.
- Browser checks used an isolated local 1.14.0 fixture without a VM connection:
  sidebar labels/order, release caption, default Topology view, Credentials dropdown,
  equal 12px tab text, Deploy New Lab wording, text/box editing, saved/reopened edits,
  Undo and discard confirmation. Input events update the canvas before Save.
- Inspection dialog checked at a 1280px viewport: width about 1242px; full long
  topology path wraps and no table cell truncates its text.
- Master wiki updated from the user-supplied document. Proxmox/Ubuntu sections
  retained; old VM client-key procedures replaced with setup, encrypted persistence,
  one-time migration and password recovery. Source builds are the default.
- Source ZIP and cumulative patch checked against clean 160fe5e; Linux scripts
  remain LF. Generated artifacts exclude preview data and email attachments.
- No Linux VM installation, Docker build, live-device test, registry publication,
  GitHub push or deployment was performed. Those deployment checks remain as
  described in the password validation below.

# VM password validation — 1.13.0

- Baseline: fresh clone of GitHub origin/main at 160fe5e (V1.12.1 bug fixs).
  Work is isolated in branch codex/vm-password; previous local checkouts preserved.
- Full Python suite: 151 tests run, 145 passed, six platform/opt-in skips. Includes
  synthetic local SSH transport for discovery, SFTP and structured operations.
- New tests cover key-to-password migration, fingerprint retention, encrypted
  persistence/restart, password rotation and blank preservation, rejection of key
  fields, no credential leakage, and effective SSH policy conflict detection.
- JavaScript: 22 tests passed, including new password form and migration behavior.
  Node syntax check passed for management.js.
- ShellCheck 0.11.0: no findings for setup-discovery.sh, setup-password.sh,
  setup-operations.sh, start-manager.sh and the shared gateway.
- Browser: inspected the real local 1.13.0 app with isolated data, confirmed the
  masked/required password field, default account, absence of client-key controls,
  dialog layout and rendered password setup/recovery guide.
- Whitespace check passed with cr-at-eol for the repository's tracked CRLF files;
  Linux scripts remain LF and are protected by .gitattributes.
- No Linux VM/systemd/passwd/sshd installation, Docker image build, live NOS test,
  registry publication or GitHub push was performed. Deployment validation should
  cover a fresh account, existing key migration, cancelled password prompt, restart,
  password reset, rejected client keys/shell/forwarding and unchanged admin login.

# UI refinement validation — 1.12.1

- Python regression run: 145 tests; six platform/environment skips. The only
  initial failure was the previous version assertion, updated to 1.12.1 and rerun.
- New coverage: topology filtering before the 500-entry limit, quick-action state
  guards and deploy/start selection, and no automatic topology dialog on entry.
- Browser fixture: same-tab Deploy New Lab landing page, explicit Lab Topologies
  opening, filtering old-helper mixed results, topology Deploy lab confirmation,
  cancellation, return navigation, and status-panel Destroy confirmation. No
  browser console errors were reported during the check.
- Synthetic SSH/operation fixtures only; no live NOS commands or Docker build.
- Git fetch was unavailable because the local Git remote-https helper is missing.
  Existing local source was preserved; no push or registry publication occurred.

# Validation — Containerlab Node Manager 1.12.0 (2026-09-10)

## Current release

- Python: 144 tests completed, 138 passed and 6 existing platform/opt-in skips.
  The suite includes discovery/import, persistence, backups, terminal tickets,
  scoped host operations, source deletion and current removed-action rejection.
- JavaScript: all 17 regression tests passed. All application scripts pass Node
  syntax checks. Inspection tests cover flat/grouped JSON, surrounding CLI logs,
  IPv4/IPv6, health/image fields, malformed output and escaped untrusted values.
- Start fresh tests verify explicit confirmation, busy backup/operation/SSH/
  discovery guards, retained VM credentials/fingerprint/encryption key, deletion
  of backup files/history/exclusions, cache invalidation and retention of unknown
  files. Interrupted state commits and staged cleanup failures resume correctly.
- Draw.io tests verify the supplied fixture's annotation text, node coordinates,
  containment-relative coordinates, unique cell IDs, endpoint labels, source/target
  references, escaped XML and unsupported-layout rejection. Exporting unsaved
  node positions leaves the saved layout unchanged. The full diagrams.net desktop
  editor was not launched; pixel-identical rendering is not claimed.
- Browser checks on isolated loopback SSH fixtures: automatic page load without
  login; retained VM settings and guide link; simplified lab action menu; interactive
  editor/full export; inspect review and 12-node result table; expanded topology
  bulk backup review; node right-click SSH/backup menu; exclusion clearing; lazy
  vertical project tree and read-only YAML. Start fresh cleared preview storage,
  preserved VM connection and returned the deployment to Ready to import with
  confirmation still required. No real VM or device commands were run.
- Fetched origin/main 7c5cef6 exactly matches the previous delivered 1.11.0 source.
  Release ZIP and patches are verified against that revision, the previous source
  ZIP and original baseline 06b8624. Shell files retain LF line endings.
- This Windows environment cannot build/run the Linux Docker image or install
  privileged helpers on a Containerlab VM. Actual image build, sudo/helper setup,
  Containerlab lifecycle commands and live NOS connectivity remain VM validation.
  Use the documented start-manager command to update helpers and image together.

## Historical release evidence

# Validation — Containerlab Node Manager 1.11.0 (2026-09-10)



## 1.11.0 evidence



- Full Python suite: 136 tests, 130 passed, 6 skipped for unavailable platform

  capabilities. Existing map, persistence, import confirmation, discovery, backup,

  SSH and removal checks remain included.

- All 14 JavaScript regression tests pass; new operations/workspace scripts pass

  Node syntax checks. Browser checks cover the new interactive flows.

- Host operation tests exercise exact scoped argv, feature detection, redeploy

  fallback order, unsupported flags/actions, path traversal, changed source/state/

  options, file creation, write/delete recovery, active-lab deletion refusal,

  optional cloning/sharing/fcli constraints, output bounds and secret redaction.

- Real subprocess tests verify stderr cannot corrupt inspection JSON and a

  disconnected streaming consumer terminates the child process.

- Real loopback Paramiko tests verify structured stdin, literal forced command,

  fragmented NDJSON output, failed exit/error handling and fingerprint mismatch.

- Authenticated API tests cover cancel, single-use/expired/revision-bound reviews,

  backup/operation conflicts, disk-save failure, output persistence and restart

  interruption, YAML diffs/name overrides, favorites/layouts and XML parsing.

  GoTTY JSON-port and HOST_IP output formats are covered; fcli reads the current

  VM management network and rejects incompatible saved labs.

- Browser fixture uses the supplied BGP topology with sanitized annotations and

  twelve nodes. Verified lab header and sidebar right-click menus, cleanup review

  cancellation, inspect confirmation/live output/success, YAML diff/cancel,

  drag-and-save layout, project browser, popular catalog selection, clone details,

  GoTTY port entry, and the new-tab SSH launcher with correct node-specific links.

  No browser console errors observed. No real VM/device commands were run.

  Screenshot: dist/lab-actions-1.11.0.png.

- Latest fetched origin/main b20468e matches delivered 1.10.0 source except the

  three ignore files. Source ZIP and patches target that commit, previous 1.10.0

  delivery and original baseline 06b8624; packaging checks reconstruct the source.

- Windows has no Docker/Containerlab/Linux host service here. Actual root helper

  installation, flock/process-group behavior, Docker image build, lifecycle

  operations and external SSHX/GoTTY/fcli services require a disposable Linux lab.

  These are not claimed as live deployment validation.



## Earlier release evidence



# Validation — Containerlab Node Manager 1.10.0 (2026-09-10)



## 1.10.0 evidence



- Full Python suite: **113 tests, 108 passed, 5 skipped**. Existing platform/opt-in

  skips remain. JavaScript regressions: **14 passed**; management script syntax checked.

- Eight confirmation tests cover background polling/preview without saving, cancel

  semantics, explicit token requirement, single save, changed files/VM, expiry,

  retained exclusions on cancel, old-client bypass rejection, disk-failure rollback

  and retry, offline/cross-name rejection, and authentication. Existing file-import

  regression fixtures now explicitly confirm before expecting a saved workspace.

- Two subprocess preflight tests exercise deploy/verify-helper.py with valid current

  envelopes (including zero labs), old helpers and malformed bundles. Only controlled

  version/status text is printed, never source contents or credentials.

- Browser on synthetic local SSH fixture: 12-node lab appeared Ready to import.

  Preview showed 12 nodes, 16 links and four exact source paths. Cancel followed by

  Refresh discovery left no saved workspace. Reopening and choosing Import lab saved

  the lab, inventory credentials and map; status was Running. No browser console errors.

  Screenshot: import-confirmation-1.10.0.png. No live device actions performed.

- New host-side start-manager.sh updates/installs the helper, verifies the expected

  version/file protocol before recreation, prepares persistent storage, builds and

  starts Compose. Existing key retained; existing account plus supplied key is

  rejected to prevent accidental rotation. Another running data-sharing manager is

  rejected. Scripts kept LF for Linux.

- Latest fetched origin/main 0c0182c matches the 1.9.1 source delivery except three

  ignore/attributes files restored here. ZIP and patches are verified against that

  revision, previous 1.9.1 delivery and original baseline 06b8624.

- No Linux shell, Docker engine or live VM was available here. Privileged setup,

  shell execution, actual image build/recreation and real deployment connectivity

  remain VM checks; preflight parser tests do not establish full installer success.

  No GitHub push or user-VM deployment was performed.



## Earlier 1.9.1 evidence (retained for context)



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
