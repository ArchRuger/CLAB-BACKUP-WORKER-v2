# mgr-install-security-git (condensed reader result recovered from the workflow journal)

Full report: /tmp/claude-1000/-home-clabllm-projects-clab-manager/2b0e597f-39bf-4403-8d37-3e4a96f0a0a9/scratchpad/reports/mgr-install-security-git.md

Nothing was edited, installed or started. MGR = /home/clabllm/projects/clab-manager. CAPP = the containerlab-app clone.

## 1. Security boundary
- The manager reaches the VM through one SSH account, `clab-discovery`. Its sshd policy is password-only, `ForceCommand /usr/local/sbin/clab-manager-gateway`, with no TTY, forwarding or tunnel (MGR/deploy/clab-manager-password.conf:2-12).
- The gateway accepts exactly three request names and exits 64 on anything else (MGR/deploy/clab-manager-gateway:4-8):
  - `clab-manager-git`
  - `clab-manager-operations`
  - the inspect command, in two accepted spellings
- Sudoers lists each launcher with an empty argument list (setup-operations.sh:62, setup-git.sh:74). Each launcher runs `env -i … python3 -I` on a root-owned copy of `app/host_*.py`. Each helper reads one JSON request on stdin.
- `host_operations.py`:
  - Every path must be absolute, contain no symlink, and sit inside a root listed in operations.json (:103-112).
  - A run must repeat the digest of the previewed plan (:263-264).
  - Previews and runs hold a host flock (:322-326).
  - Docker is reachable only as the fixed Grafana container name (:161-170).
- `host_git.py`:
  - Root handles only list, register-prefix and connect (:1064-1069).
  - Everything else runs after a permanent drop to the registered owner with umask 077 (:1045-1052).
- `host_files.py` takes no request and is not limited to the trusted roots; it reads the topology path that containerlab reports (:115-122).
- Version lockstep:
  - The marker set is verify-release.py FIELDS (:27-39).
  - The launcher checks the markers, each helper's version, and all three requests through the gateway as clab-discovery before it rebuilds (start-manager.sh:19-52).
  - At runtime a mismatched Git helper is refused (git_progress.py:280-281). A mismatched operations helper only produces a Diagnostics warning (diagnostics.py:144-148).
- The manager container uses host networking, mounts only the data directory, drops all capabilities, runs as UID 10001 and has no Docker socket (compose.yml:7,20-28).
- The CSP is `default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'`, plus X-Frame-Options DENY. Only terminal.html and capture-session.html get 'unsafe-inline' styles (main.py:116-123). A manager page therefore cannot fetch from or frame another port.
- There is no UI login (agent instructions.md:682).

## 2. Sidecar precedents
- **Capture stack**
  - It is its own Compose project. The session service is built on the VM, its tag carries the release, it alone mounts the Docker socket, and it binds to loopback. The other images are pinned by digest (compose.capture.yml:3-25).
  - `setup-capture.sh` and `setup_capture.py` write CAPTURE_* keys to `.env` and preserve the rest. `--remove` writes `disabled`, which the launcher respects (start-manager.sh:60-65).
  - The browser reaches it through a same-origin relay in the manager: "No additional browser-facing port or iframe" (CAPTURE.md:128).
  - Standing rule: never expose its API to browsers or accept client image, command, mount or URL parameters (agent instructions.md:482-484).
  - It has a health check (check_install.py:583-613), an installer phase, menu item 4 and a CI smoke test.
- **Telemetry stack**
  - Images are pinned by digest. The Flow panel plugin is a pinned prebuilt artifact fetched at setup time (setup_telemetry.py:28-29,176-177).
  - Grafana is on demand, driven by an extra mode of the existing operations helper (host_operations.py:161-170).
  - The browser opens Grafana in a separate tab on port 3000.
- **Third-party notices**
  - Each stack has one deploy/*-THIRD-PARTY-NOTICES.md file naming component, use, licence, whether it is modified, and that it is pulled separately.
  - Vendored JS keeps its exact version and upstream LICENSE files in app/static/vendor.
  - The README's License paragraph links all of these (README.md:209-218). The project itself is MIT.
- **What an SR Labs sidecar needs** (CAPP/docs/manual/api-server.md:65,128-166; CAPP/README.md:58-64,112):
  - clab-api-server runs as root. As a container it is `--privileged --network host --pid host` with docker.sock, /etc/shadow and /home mounted (api-server.md:128-146).
  - Login is a Linux user in the `clab_api` or `clab_admins` group, using the Linux password.
  - Labs are stored in the user's `~/.clab`.
  - The web app serves self-signed HTTPS on port 3001, and upstream docs use `:latest` tags.
- **Collisions with standing rules**
  1. Docker and host control must stay outside the manager and must never be browser-driven (CLAUDE.md:141-142).
  2. The manager has no login; the sidecar requires Linux-password login and reads /etc/shadow.
  3. It would be a second control plane that bypasses the preview digest, the host flock and `operation_busy`.
  4. `~/.clab` is outside the trusted roots, so the manager could discover those labs but would refuse to operate them (host_operations.py:109-110).
  5. The CSP leaves only two ways to show it: a same-origin relay or a new tab with its own login.
  6. VM YAML editing was removed on purpose (agent instructions.md:734-735; LAB-OPERATIONS.md:50-55). Any lab builder reverses that decision.
  7. Grafana was made on demand to save memory, so two more always-on services cut against that.
- **Boilerplate a new sidecar requires**:
  - a Compose file and a setup script pair with `.env` keys;
  - a launcher block and installer phase, both order-tested (test_release_consistency.py:93-95; test_install_manager.py:152-154);
  - env passthrough in both manager Compose files;
  - a health check, a CI smoke test, a guide and a notices file.

## 3. Git
- A registration is a checkout path plus a prefix, recorded in /etc/clab-manager/git.json. The manager owns only `latest/`, `baseline/` and `checkpoints/<name>/` under that prefix.
  - Those folders hold configs, `.jcfg` restore artifacts and `manifest.json` (host_git.py:544-559,587).
  - The manifest carries a topology digest, not the topology itself (git_progress.py:204-209; GIT-PROGRESS.md:35-37).
- Topologies are not in the checkouts today.
  - The scaffold only calls the manager API (scaffold-lab.py:96-122).
  - The lab template says to copy the file to your labs directory, not the checkout (deploy/lab-template/README.md:8-10).
  - The live checkout on this VM has 344 tracked files and no `.clab.y*ml`. The topologies live in /srv/containerlab-node-manager/projects and /etc/containerlab.
  - The docs only tolerate a topology the owner placed by hand (GIT-PROGRESS.md:134).
- Checkouts live in `~/labs/<repo>` (host_git.py:971). The default trusted roots are /etc/containerlab and /srv/containerlab-node-manager/projects (setup-operations.sh:41). `--lab-root` could add a checkout as a root.
- Creating a lab inside a checkout with the existing helpers:
  - `host_git` cannot write arbitrary files.
    - `publish` takes only snapshot filenames and refuses folders that hold files outside the manifest (host_git.py:576-580).
    - "New folder" adds a registry entry only and creates nothing on disk.
    - Commits cover exactly the exported paths (:477,489).
  - `host_operations create` works only inside a trusted root.
    - It creates a new file only; the parent folder must already exist and there is no mkdir.
    - It never overwrites, so an existing topology cannot be saved over (:211-214,283-285).
    - The file is written as root, mode 0664 inside a setgid folder and 0644 otherwise (:286-289).
  - Consequences if a checkout were made a trusted root:
    - The checkout would contain root-owned files.
    - A root-owned `clab-<name>/` folder would appear beside the topology, which would probably block `update` because it calls clean(entire=True) (:705). This is inferred, not exercised.
    - setup-engineer-access.sh runs `chgrp -R clab_admins` and chmod 2775 over every root (:53-59), so it would recurse into `.git`.
    - A hand-made commit of the topology blocks the manager's next push (host_git.py:429-430).
- Ownership:
  - Trusted roots are root:root 0755, or root:clab_admins 2775 with engineer access.
  - Checkouts are owner-only, and the helper creates folders as 0700.
  - The manager's UID touches neither.

## 4. Upgrade
- `start-manager.sh` reinstalls all helpers, the gateway, the sudoers files and the sshd policy.
  - It preserves the password, the roots and network flag, the Git registrations, `.env` and the data directory.
  - It refreshes both stacks, then runs `build --pull --no-cache` and `up --force-recreate` (:19-90).
- (a) A new mode in an existing helper needs no new gateway name, sudoers line or launcher, and the normal upgrade already reinstalls it.
  - A container-only recreate leaves an old helper in place. Git then fails hard; operations only warns, and the new mode returns "Unknown request mode".
  - `capabilities()` (:139-149) is the existing hook for advertising the new action.
  - A brand-new helper also needs a launcher, a sudoers file, a gateway case, a verify-gateway entry and check_install entries.
- (b) A Node build stage:
  - Every install and upgrade on every VM would pull a Node image and run a full pnpm install against the npm registry. Upstream pins Node 24.21.0 and pnpm 12.4.2, and its lockfile has 1123 entries.
  - CI never builds the manager image, so a broken stage would first fail on a user's VM in installer phase 3.
  - It breaks the "no build step" rule (CLAUDE.md:115).
- (c) A committed prebuilt bundle:
  - `COPY app/` ships it as-is, and nothing in install or upgrade changes (Dockerfile:17).
  - `.gitignore` ignores any `dist/` or `data/` folder (:4,13), and `.dockerignore` drops `*.md` files (:9).
  - The repo pack is 9 MiB and app/static is 872 K, while clab-ui 0.3.2 is 23.5 MB unpacked.
  - A new page must join the `?v=` cache-busting list.
  - The CSP would need 'unsafe-inline' styles for emotion/MUI, and probably a `worker-src` for Monaco and MapLibre workers (inferred, not tested).
- (d) A new sidecar needs the boilerplate listed in section 2.

## 5. Image build
- The manager image is built on the user's VM from source by default (compose.yml:4-5; start-manager.sh:73). Nothing is published to a registry; the CI workflow is read-only.
- `compose.image.yml` exists only for a separately loaded image and already lags `compose.yml`. The capture session service is also built on the VM.
- The current manager image is 537 MB.
- The time and memory cost of a Node stage were not measured. The docs give no minimum VM size. The host's own Node is v18.19.1, below the Node 24.21.0 upstream pins.

## Load-bearing claims

- **[verified-in-code]** The VM boundary is one forced-command SSH account whose gateway accepts exactly three request names, each mapped to a sudoers helper with an empty argument list. A new capability must be a JSON mode of an existing helper, or else add a gateway case, a sudoers file and a launcher.
  - Evidence: MGR/deploy/clab-manager-gateway:4-8; MGR/deploy/clab-manager-password.conf:2-12; MGR/deploy/setup-operations.sh:55-66; MGR/deploy/setup-git.sh:67-77; clab-backup-ui/app/host_operations.py:315-328; clab-backup-ui/app/host_git.py:1064-1077
- **[verified-in-code]** The operations helper can only create a new .yaml/.yml file in an existing directory inside a trusted root. It writes as root, never overwrites, and has no mkdir or edit mode. Saving edits to an existing topology or creating a lab folder is impossible with today's helper.
  - Evidence: clab-backup-ui/app/host_operations.py:103-112 (path rules), :210-214 (create: path must not exist, parent must exist), :277-289 (atomic link, 0664/0644), :269-270 (only mkdir is .clab-manager-history); docs/LAB-OPERATIONS.md:50-51,55
- **[verified-in-code]** Registered Git checkouts hold only latest/, baseline/ and checkpoints/ snapshots (configs, restore artifacts, manifest). The manager never writes topology files there, and host_git has no mode that could. Checkouts (~/labs/<repo>) are outside the default trusted roots.
  - Evidence: host_git.py:114-147,544-559,576-580,477,489,971; git_progress.py:155-210 (manifest has topology_digest only); docs/GIT-PROGRESS.md:35-37,134; deploy/scaffold-lab.py:96-122; deploy/lab-template/README.md:8-10; setup-operations.sh:41. On this VM, `git ls-files | grep clab.y` in /home/clabllm/labs/CLAB-MNGR-DEV-LLM returned nothing among 344 tracked files, and the topologies were found under /srv/containerlab-node-manager/projects and /etc/containerlab.
- **[verified-in-code]** Every manager response carries a self-only CSP: script-src, style-src and connect-src are 'self', there is no frame-src, frame-ancestors is 'none', and X-Frame-Options is DENY. Inline styles are allowed only for terminal.html and capture-session.html. A sidecar UI can therefore only be shown through a same-origin relay (the capture precedent) or a separate tab (the Grafana precedent). A React/MUI bundle would need a style exception.
  - Evidence: clab-backup-ui/app/main.py:116-123; docs/CAPTURE.md:120-128; app/capture_sessions.py:130-148,192; CAPP/packages/clab-ui/package.json:125-148 (emotion, MUI, monaco, maplibre)
- **[documented-only]** clab-api-server runs as root. As a container it is --privileged with docker.sock, /etc/shadow and /home mounted, and it authenticates Linux users by password. This collides with four project rules: no Docker or host control reachable from the manager or browser, no login, the reviewed single control plane, and the trusted roots.
  - Evidence: CAPP/docs/manual/api-server.md:65,128-146,150-166; CAPP/README.md:105,112; MGR/CLAUDE.md:141-142; 'agent instructions.md':482-484,682,977,984; host_operations.py:263-264,322-326. The clab-api-server source was not in the clone, so its behaviour is known from documentation only.
- **[verified-in-code]** The manager image is built from source on every user VM at every install and upgrade, with `docker compose build --pull --no-cache`. No registry publishes it, and CI never builds the manager Dockerfile. A Node/pnpm stage would therefore run in full on every user VM with npm-registry access, and a broken stage would first fail there.
  - Evidence: clab-backup-ui/compose.yml:4-5; deploy/start-manager.sh:73; .github/workflows/release-check.yml:3-4 and its step list (no manager build; only deploy/capture/smoke.py:77 builds the capture image); deploy/compose.image.yml:1-9; CAPP/package.json:8-10,56; pnpm-lock.yaml has 1123 package entries (awk count)
- **[verified-in-code]** A committed prebuilt bundle under app/static ships with no change to install or upgrade. However, .gitignore ignores any dist/ or data/ directory, and .dockerignore drops *.md files from the image, which would exclude licence notices written as .md.
  - Evidence: clab-backup-ui/Dockerfile:17; MGR/.gitignore:4,13; clab-backup-ui/.dockerignore:9; app/static/vendor holds xterm.LICENSE and addon-fit.LICENSE (precedent); `git count-objects` reported a 9.01 MiB pack; `du` reported app/static at 872K; `npm view @containerlab/clab-ui` returned 0.3.2, unpackedSize 23530653, 642 files, Apache-2.0
- **[verified-in-code]** The normal upgrade already reinstalls all three helpers and verifies them through the gateway before rebuilding, preserving the password, roots, registrations, .env and data. A container-only recreate leaves an old helper in place: Git then fails hard, and operations only warns.
  - Evidence: deploy/start-manager.sh:19-53,73,90; deploy/setup-operations.sh:40-48; deploy/setup-git.sh:84-87; app/git_progress.py:280-281; app/diagnostics.py:144-148; host_operations.py:139-149 (capabilities), :328 (Unknown request mode); deploy/check_install.py:392-417 (sha256 of installed helpers)
- **[verified-in-code]** Two established sidecar precedents exist, each with a fixed recipe: its own Compose project, a setup script pair, .env keys with --remove → disabled, a launcher block and installer phase (both order-tested), a health check, a CI smoke test, a guide and a notices file. An extra mode of the operations helper already controls a sidecar container by fixed name (Grafana).
  - Evidence: deploy/compose.capture.yml:3-25; deploy/compose.telemetry.yml:14-57; deploy/setup-capture.sh:17-41; deploy/setup-telemetry.sh:23-56; deploy/setup_capture.py:45-71; start-manager.sh:58-71; install-manager.py:222-225,287-288,323; tests/test_release_consistency.py:93-95; tests/test_install_manager.py:152-154; host_operations.py:26-29,161-170; deploy/*-THIRD-PARTY-NOTICES.md; README.md:209-218
- **[inferred]** If a checkout were made a trusted root, three things would follow. The engineer-access script would chgrp/chmod the whole checkout, including .git. Files written by the manager would be root-owned. A topology commit made by hand would block the manager's next push.
  - Evidence: deploy/setup-engineer-access.sh:53-59; host_operations.py:286-289; host_git.py:429-430 (push refused when outgoing commits were not manager saves), :705,712 (update uses clean(entire=True)), :782-783 (uid-only ownership check). The interaction was not exercised on a VM.

## Open questions

- Does the redesign freeze still apply? CLAUDE.md:20 still says the redesign must not touch the backend or the host_*.py helpers, but docs/redesign/PICKUP.md:123,169 records the redesign as released (1.29.0 and 1.29.1). A helper mode depends on the answer.
- What are the real build time, peak memory and download volume of a pnpm/Vite build of clab-ui on a typical student VM? None of these was measured, and the guides give no minimum VM size (FRESH-VM-GUIDE-V2.md:111).
- Does the launcher's `--no-cache` also discard BuildKit cache mounts? If not, a Node stage would cost less on repeat upgrades. Not verified.
- What happens when containerlab, run by the helper with `env -i` and no SUDO_UID, writes a root-owned clab-<name>/ folder into an owner-scoped checkout? How do `git status`, `update` and `clean(entire=True)` behave over it as the owner? This was not exercised.
- Can clab-api-server bind to loopback only, restrict its labs directory to an existing trusted root, authenticate without /etc/shadow, or run non-privileged? Its source was not in the clone; only CAPP/docs/manual/api-server.md was available.
- Are ghcr.io/srl-labs/containerlab-web and the clab-api-server image published with stable tags or digests that fit the project's pin-by-digest, no-latest convention? Upstream docs use :latest.
- Which licence governs upstream code? The root CAPP/LICENSE is MIT while root, apps/web and packages/app-server package.json say Apache-2.0; packages/clab-ui is Apache-2.0 (file and field), packages/clab-viewer is MIT, and apps/web and packages/app-server carry no LICENSE file. The answer decides what a notices file must contain.
- Which clab-ui version is the reuse target? The clone's packages/clab-ui/package.json says 0.4.0, while npm's latest is 0.3.2.
- How large is a real tree-shaken builder bundle, as opposed to the 23.5 MB unpacked npm package? Which CSP relaxations would it need beyond 'unsafe-inline' styles (worker-src for blob workers, fonts, wasm)? The CSP needs were inferred from the dependency list and not tested.
- Does the maintainer accept reversing the recorded 1.12.0 decision to remove VM YAML editing (agent instructions.md:734-735; LAB-OPERATIONS.md:55)? Every lab-builder strategy reverses it.
