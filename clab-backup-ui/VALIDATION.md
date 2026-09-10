# Validation — Containerlab Node Manager 1.8.0 (2026-09-10)

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
