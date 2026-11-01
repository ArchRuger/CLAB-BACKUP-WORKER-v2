# Exposure: TLS and hardening of an Internet-facing VM

The design of the transport and of the VM's other doors for the sign-on campaign (`PROMPT.md`,
decision D3). It answers the eight questions the lead asked, in order. `DESIGN.md` owns accounts,
sessions and the gate; `UI.md` owns the pages. Section 9 states what this design needs from them.

File:line references are to the branch `claude/sign-on-and-hardening` at `1bab321` (release 1.31.8).
Where `INVENTORY.md` cites a different line of `main`, the branch line is given here (one case:
`start-manager.sh:120` in INVENTORY §4 is `start-manager.sh:105` on this branch).

## 0. Terms

| Term | Meaning |
|---|---|
| **TLS port** | The TCP port on which the manager serves HTTPS. `UI_PORT`; default **8443**. |
| **redirect port** | The TCP port on which a separate, data-less listener answers every request with `301` to the TLS port. `UI_HTTP_PORT`; default **8081**; `0` disables it. |
| **tls directory** | `/srv/containerlab-node-manager/tls` on the VM, mounted read-only at `/tls` in the manager container. |
| **certificate mode** | `self-signed` (the installer made the certificate) or `provided` (the operator supplied it). Recorded in the file `mode` of the tls directory. |
| **fingerprint** | The SHA-256 digest of the certificate in DER form, as browsers show it, printed as 32 colon-separated bytes. |
| **exposed** | Reachable on a non-loopback address of the VM. **Loopback-only** means bound to `127.0.0.1` or `::1`. |
| **plain HTTP** | HTTP without TLS. |
| **the installer** | `deploy/install.sh` → `deploy/install-manager.py` (plain menu) or `deploy/installer_tui/` (full screen); both run `deploy/start-manager.sh` under sudo (install-manager.py:593-598). |
| **the health check** | `deploy/check-install.sh` → `deploy/check_install.py` and its modules `check_host.py`, `check_git.py`. |
| **the gate** | `SessionGate` of DESIGN.md §6. |

## 1. Decisions in one table

| # | Question | Decision |
|---|---|---|
| 1 | TLS termination | **uvicorn serves HTTPS itself** (`--ssl-certfile /tls/cert.pem --ssl-keyfile /tls/key.pem`). Always on in both compose files. No Caddy sidecar. A reverse proxy is not a supported mode in this version (reasons in 2.3). |
| 2 | Certificate | **Self-signed by the installer with `openssl` on the VM**, ECDSA P-256, 730 days, SANs = the VM's addresses, its host name, `localhost`, the loopback addresses and every name in `UI_ALLOWED_HOSTS`. A **provided** certificate (any CA, Let's Encrypt through certbot included) is installed with `setup-tls.sh --cert --key`. |
| 3 | Plain HTTP | **A redirect-only listener on 8081** (a second compose service running `python -m app.redirect`), nothing else on plain HTTP. **HSTS** `max-age=31536000` on every HTTPS response, no `includeSubDomains`, no `preload`. |
| 4 | Other doors | `UI_BIND` stays `0.0.0.0`. New `deploy/setup-firewall.sh` (ufw: allow the SSH port, the TLS port and the redirect port; deny the rest). Lab-node published ports and any non-loopback listener are reported by the health check. New `deploy/setup-ssh-hardening.sh` writes a conservative sshd drop-in. The `clab-discovery` policy is not touched. |
| 5 | Health check | New module `deploy/check_exposure.py` (stdlib) with eleven checks (section 6), plus three changes in `check_install.py` (TLS-aware `Context.http`, `/api/health` instead of `/api/state`, capture and design-engine facts through `docker exec`). |
| 6 | Installer | `setup-tls.sh` runs inside `start-manager.sh` before the image build; firewall and sshd hardening are installer steps after the manager verification; `health_url`, `probes.manager_address` and the TUI's address lines become `https://`; the setup code and the fingerprint are printed at the end. The upgrade decision is 7.4. |
| 7 | Docs and CI | Section 8. |
| 8 | Attack list | Section 10. |

## 2. TLS termination

### 2.1 The facts the choice rests on

1. The manager runs with `network_mode: host` (compose.yml:7; compose.image.yml:10), `cap_drop: [ALL]` and
   `no-new-privileges:true` (compose.yml:22-24; compose.image.yml:25-27), as uid 10001 (Dockerfile:11-15,
   21). A port below 1024 needs `CAP_NET_BIND_SERVICE`. For a non-root process that capability reaches
   the effective set only through file capabilities, and `no_new_privs` refuses file capabilities.
   Lowering `net.ipv4.ip_unprivileged_port_start` would apply to every process in the host network
   namespace. **Port 443 therefore costs a sandbox property; a high port costs a redirect listener.**
2. uvicorn supports `--ssl-certfile`, `--ssl-keyfile` and `--no-server-header` on its command line;
   the compose command is the only place that command lives (compose.yml:8; compose.image.yml:11;
   Dockerfile:24 for `docker run`).
3. uvicorn's `--proxy-headers` is **on by default** and trusts `X-Forwarded-*` from loopback sources
   (uvicorn 0.54.0 as installed in this session: `config.py:225` default `True`, `config.py:363` default
   `127.0.0.1,::1`, `config.py:544` installs `ProxyHeadersMiddleware`; the image resolves
   `uvicorn>=0.30,<1`, requirements.txt:4). INVENTORY §4 says the manager runs "without
   `--proxy-headers`"; it runs without the flag, which means **with** the feature. A process on the VM
   can today rewrite `scope['scheme']` and `scope['client']` with two headers. Section 2.2 closes it.
4. "Own origin" is built from the request in three places: the guard compares `Origin` with
   `request.base_url` (main.py:122-123), both sockets compare the Origin scheme with `ws.url.scheme`
   (node_services.py:572-574; capture_sessions.py:317-319), and the capture cookie's `secure` flag reads
   `request.url.scheme` (capture_sessions.py:113-114). The pages choose `wss://` from
   `location.protocol` (terminal.js:51; capture-session.js:41). **When uvicorn terminates TLS, all of
   these are correct without a flag**; when something else terminates it, all of them are wrong unless
   a flag or a trusted header overrides the scope (DESIGN.md 5.6).
5. DESIGN.md 8.1 throttles sign-in by `scope['client'][0]`, and DESIGN.md 10 records that address in
   the audit log. Behind a proxy on the VM every source is `127.0.0.1`: one attacker throttles every
   student, and the log names nobody.

### 2.2 The options

| Option | Keeps the sandbox | Own-origin and source address correct | New third-party image | Shippable without a guide | Verdict |
|---|---|---|---|---|---|
| (a) uvicorn serves HTTPS | yes | yes, by the ASGI scope | none | yes: the installer makes the certificate | **chosen** |
| (b) Caddy sidecar, Let's Encrypt | Caddy binds 80/443 as root or with `NET_BIND_SERVICE`; the key lives in a third container | no: needs `UI_TLS=1` and `--forwarded-allow-ips`, and the throttle keys on the proxy's address (2.1.5) | one, pinned by digest | needs a public name and inbound 80 or 443; a self-signed fallback would need its own trust story anyway | not now |
| (c) document a reverse proxy | yes | no (same as b) | none | no: D3 says TLS is part of the work | not as the default; documented as unsupported until a source-address design exists |

The compose command becomes, in both files (the `image:` and `build:` lines unchanged):

```yaml
command: ["uvicorn", "app.main:create_app", "--factory",
          "--host", "${UI_BIND:-0.0.0.0}", "--port", "${UI_PORT:-8443}", "--workers", "1",
          "--ssl-certfile", "/tls/cert.pem", "--ssl-keyfile", "/tls/key.pem",
          "--no-proxy-headers", "--no-server-header"]
volumes:
  - type: bind
    source: /srv/containerlab-node-manager/data
    target: /data
    bind: {create_host_path: false}
  - type: bind
    source: /srv/containerlab-node-manager/tls
    target: /tls
    read_only: true
    bind: {create_host_path: false}
```

Rules:

1. The certificate paths inside the container are fixed. Nothing in `.env` can point the manager at
   another key file. The installer puts the files in the tls directory; that is the only variable.
2. `--no-proxy-headers` is explicit. `FORWARDED_ALLOW_IPS` is not set. No header changes the scope.
3. `--no-server-header` removes `server: uvicorn` (DESIGN.md 6.7 asks for it). The `date` header stays.
4. TLS version and ciphers stay at uvicorn's and Python's defaults (minimum TLS 1.2 by
   `ssl.SSLContext` default since Python 3.10). Section 10 lists this for the reviewer; a cipher
   string is not added without a measured reason.
5. The Dockerfile's `CMD` (Dockerfile:24) carries the same TLS arguments and `EXPOSE 8443 8081`
   (Dockerfile:22). A `docker run` without the tls mount fails at start, which is the right outcome:
   the image never serves plain HTTP by accident.
6. Plain HTTP for development is not a container mode. The fixture tools run the app directly
   (`docs/redesign/tools/fixture_manager.py`), and `127.0.0.1` is a secure context in every browser.

### 2.3 Supported modes

| Mode | What terminates TLS | Supported | Notes |
|---|---|---|---|
| `self-signed` (default) | uvicorn, certificate made by `setup-tls.sh` | yes | The student clicks through the browser's warning once per browser and may check the fingerprint (3.6). |
| `provided` | uvicorn, operator's certificate | yes | `setup-tls.sh --cert PATH --key PATH`. Let's Encrypt through certbot is this mode (3.5). |
| reverse proxy on the VM, TLS to uvicorn | the proxy, then uvicorn again on loopback | tolerated, not documented as a path | `UI_BIND=127.0.0.1`; the proxy connects with HTTPS to `127.0.0.1:8443` and trusts `cert.pem`; `Host` must be the browser's name and listed in `UI_ALLOWED_HOSTS` (INSTALL.md:220-235 already says so). The audit log and the throttle see `127.0.0.1` (2.1.5). |
| reverse proxy, plain HTTP to uvicorn | the proxy | **no** | The compose command always carries the TLS arguments. |

### 2.4 Settings

| Key | Where | Values | Default | Written by | Validation |
|---|---|---|---|---|---|
| `UI_BIND` | `.env`, compose | an address | `0.0.0.0` | the operator (unchanged; the installer never writes it, install-manager.py:244-254) | existing (`health_url`, install-manager.py:104-114) |
| `UI_PORT` | `.env`, compose | 1-65535 | **8443** (was 8081) | the operator; the installer never writes it | `setup_tls.py` refuses `UI_PORT == UI_HTTP_PORT` (7.4) |
| `UI_HTTP_PORT` | `.env`, compose (redirect service only) | 0 or 1-65535 | 8081 | the operator, or `setup_tls.py` in the one migration case of 7.4 (`UI_HTTP_PORT=0`) | `app.redirect` exits with a message on a value outside 0-65535 |
| `UI_ALLOWED_HOSTS` | `.env`, compose | names | empty | the operator (INSTALL.md:225-233) | existing (`configured_hosts`, allowed_hosts.py:67-76); its names also become SANs (3.2) |
| `UI_TLS` | — | — | — | **not introduced** (section 9, interface 1) | — |

No key holds a secret, so DESIGN.md ruling 13 (DESIGN.md:937-939, `runner.job_environment` passes
the environment to Ansible) holds: the key file is a path fixed in the compose command, not an
environment value.

The redirect service's environment is `UI_BIND`, `UI_PORT`, `UI_HTTP_PORT`, `UI_ALLOWED_HOSTS`. The
manager service's environment gains nothing. `test_release_consistency.py:88-99` compares the
**first** `environment:` block of each compose file; the lead extends it to compare both services
(8.2).

Every `.env` write goes through the pattern of `deploy/setup_capture.py` (`read_env` refuses a
symlink, setup_capture.py:16-22; `write_env` is tempfile + fsync + 0600 + chown + `os.replace`,
setup_capture.py:25-38; `without` drops a key, setup_capture.py:41-42). `setup_tls.py` imports those
three functions from `setup_capture.py` with `importlib` the way `check_install.module()` loads a
sibling (check_install.py:36-42); it does not copy them.

## 3. Certificates

### 3.1 Generation at install

`deploy/setup-tls.sh` (root; called from `start-manager.sh` right after `setup-vm.sh`,
start-manager.sh:24, so that the tls directory exists before `docker compose up` at
start-manager.sh:95 and before the prepared-image route of `recreate-manager.sh:29-41`) runs
`/usr/bin/python3 deploy/setup_tls.py` with one of:

| Invocation | Effect |
|---|---|
| `setup-tls.sh` (no option; `start-manager.sh` uses this) | **ensure**: creates the tls directory; if `mode` is absent or `self-signed` and the certificate is absent, unreadable, expired, expiring within 30 days, or lacks one of the VM's current addresses or one of the `UI_ALLOWED_HOSTS` names, a new self-signed certificate is made. A `provided` certificate is never touched; its expiry is reported. |
| `setup-tls.sh --renew` | A new self-signed certificate now (new key, new fingerprint); refused while `mode` is `provided` unless `--self-signed` is also given. |
| `setup-tls.sh --cert PATH --key PATH` | **provided**: validates (3.4), copies both files into the tls directory, writes `mode=provided`. |
| `setup-tls.sh --self-signed` | Switches back from `provided` and generates. |
| `setup-tls.sh --show` | Prints subject, SANs, notAfter, mode and fingerprint. Read-only; works as any account that can read `cert.pem`. |

Every mode except `--show` ends by printing the fingerprint and, when a manager container exists,
by running `recreate-manager.sh` unless `--no-recreate` is given (the pattern of
`setup-capture.sh:39-44`). The tool is `openssl` on the VM, not Python `cryptography` in the
container, because:

1. The key must be written by root into a root-owned directory the container cannot change
   (3.3). The container runs as uid 10001 and the tls mount is read-only.
2. The certificate must exist before the image is built (source route) or pulled (prepared-image
   route). A container-side generator would need the image first and a writable mount.
3. `openssl` is installed on every Ubuntu 24.04 system (priority *important*); `python3-cryptography`
   is not guaranteed on the VM's system Python, and the health check must stay stdlib-only.

The command `setup_tls.py` builds (argv list, never a shell string):

```
openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:P-256 -nodes -sha256
  -days 730 -subj "/CN=<primary name>" -addext "subjectAltName=<list>"
  -addext "basicConstraints=critical,CA:FALSE" -addext "keyUsage=digitalSignature"
  -addext "extendedKeyUsage=serverAuth"
  -keyout <tmp>/key.pem -out <tmp>/cert.pem
```

`-addext` exists in OpenSSL 1.1.1 and later; Ubuntu 24.04 ships 3.0.x. The files are written to a
temporary directory inside the tls directory, given their final modes, then moved with `os.replace`
(the `write_env` discipline).

### 3.2 Names in the certificate

| SAN | Source | Why |
|---|---|---|
| `IP:` every non-loopback IPv4 and IPv6 address of the VM | `ip -j address` (the health check already parses it, check_install.py:510-513); the TUI's `vm_addresses()` uses `hostname -I` (installer_tui/app.py:1818-1826) and gets the same list | Students open the manager by the VM address (README.md:89; VM-CONNECTION.md:41). |
| `IP:127.0.0.1`, `IP:::1`, `DNS:localhost` | fixed | The health check and the installer probe `127.0.0.1` or `[::1]` (install-manager.py:113-116; probes.py:103-109) and verify the host name. |
| `DNS:<hostname>` | `socket.gethostname()` | A single-label name passes `HostCheck` without configuration (allowed_hosts.py:59). |
| `DNS:` every name of `UI_ALLOWED_HOSTS` | `.env` (both `clab-backup-ui/.env` and `deploy/image.env` are read; union) | A name the operator listed is a name students will type. Parsed with `configured_hosts()` of `allowed_hosts.py:67-76`, imported from the checkout (pure module, no app import). |

The primary name (`CN`) is the first `UI_ALLOWED_HOSTS` name, else the first IPv4 address, else the
host name. The SAN list is what matters; the `CN` is cosmetic.

A dynamic address changes the list: **ensure** notices (3.1) and regenerates on the next
`start-manager.sh`; the health check warns in between (6, `tls.names`). A regenerated self-signed
certificate has a new fingerprint and every browser shows its warning again; that is stated in the
installer's output and in INSTALL.md (8.1).

### 3.3 Files, owners, modes

| Path | Owner | Mode | Content |
|---|---|---|---|
| `/srv/containerlab-node-manager/tls/` | root:root | 0755 | directory; refused when a symlink (the `setup-vm.sh:6` rule) |
| `tls/cert.pem` | root:root | 0644 | PEM certificate; for `provided`, the full chain, leaf first |
| `tls/key.pem` | root:**10001** | 0640 | PEM private key, readable by the container's group (Dockerfile:11 creates gid 10001); not readable by the ordinary VM account |
| `tls/mode` | root:root | 0644 | one line: `self-signed` or `provided` |

The health check's `FILE_PROBE` (check_install.py:389-406) already verifies owner, mode and regular
file for the helper files; `check_exposure.py` reuses it for these three files with the modes above
(the probe runs as root through `ctx.run(..., privileged=True)`, check_install.py:101-112, so the
0640 key is checked without reading it; the probe hashes only files up to 1 MiB and the report never
prints a hash of the key: the key's entry is passed with a flag that skips the digest).

The key never leaves the VM. `setup-tls.sh --show` prints the certificate's facts, never the key.
`setup_tls.py` never prints a key path's contents in an error message.

### 3.4 A provided certificate

`setup-tls.sh --cert PATH --key PATH` (root) validates before it copies:

1. Both are regular files, not symlinks, at most 64 KiB (the `.env` limit, install-manager.py:275-276).
2. `openssl x509 -in CERT -noout -checkend 0` succeeds (not expired) and `-ext subjectAltName`
   lists at least one name; the list is printed.
3. `openssl pkey -in KEY -pubout` and `openssl x509 -in CERT -noout -pubkey` print the same public
   key (the certificate matches the key). An encrypted key is refused with "decrypt the key first";
   uvicorn would otherwise prompt for a password at every start.
4. The copy has the modes of 3.3 regardless of the source files' modes; the source files are left as
   they were.
5. `mode=provided` is written last.

Rotation of a provided certificate is the same command again. A certbot deploy hook that runs
`sudo bash deploy/setup-tls.sh --cert /etc/letsencrypt/live/NAME/fullchain.pem --key /etc/letsencrypt/live/NAME/privkey.pem`
is the documented way to use Let's Encrypt (8.1); certbot in `standalone` mode needs port 80 free and
reachable, which the firewall section (5.2) does not open by default, so the guide states the DNS-01
alternative. Neither certbot nor any ACME client is installed by the installer.

### 3.5 Rotation of a self-signed certificate

- **Ensure** regenerates within 30 days of expiry, on every `start-manager.sh` run (upgrades).
- The health check warns from 30 days before expiry and fails after it (6).
- The validity of 730 days keeps the certificate importable into an Apple trust store (Apple refuses
  server certificates valid longer than 825 days) for an operator who wants to remove the warning on
  managed workstations; INSTALL.md says how (8.1), the manager does not depend on it.

### 3.6 The browser trust story

With a self-signed certificate the browser shows its warning once per browser profile and host
(Chrome and Edge: *Your connection is not private*, **Advanced** → *Proceed to …*; Firefox:
*Warning: Potential Security Risk Ahead*, **Advanced…** → *Accept the Risk and Continue*). After
that the padlock shows *Not secure* while the connection is encrypted. The person verifies the
certificate's SHA-256 fingerprint in the browser's certificate viewer against the fingerprint the
installer printed and the health check prints (`tls.cert`). The sign-in page shows nothing special
under a self-signed certificate (UI.md:229-232): the browser's interstitial already stood between the
person and the page.

What is not solved by this design and is said so in INSTALL.md: a self-signed certificate does not
protect against an active attacker who presents another self-signed certificate, unless the person
compares the fingerprint. The provided mode with a CA-issued certificate is the answer for an
installation whose students arrive over networks the operator does not control.

## 4. Plain HTTP and HSTS

### 4.1 The redirect listener

A second compose service, `http-redirect`, in both compose files:

```yaml
http-redirect:
  image: clab-backup:1.31.8          # compose.image.yml: ${MANAGER_IMAGE:?...}
  restart: unless-stopped
  network_mode: host
  read_only: true
  command: ["python", "-m", "app.redirect"]
  environment:
    UI_BIND: ${UI_BIND:-0.0.0.0}
    UI_PORT: ${UI_PORT:-8443}
    UI_HTTP_PORT: ${UI_HTTP_PORT:-8081}
    UI_ALLOWED_HOSTS: ${UI_ALLOWED_HOSTS:-}
  cap_drop: [ALL]
  security_opt: [no-new-privileges:true]
```

`app/redirect.py` (new, about 60 lines, stdlib plus `uvicorn` and `app.allowed_hosts`; it never
imports `app.main`, `app.store` or any service):

1. Reads the four variables. `UI_HTTP_PORT=0` prints `HTTP redirect disabled` and waits for SIGTERM
   without binding anything (a `threading.Event().wait()`): the container stays *running* and
   `restart: unless-stopped` has nothing to restart. (A process that exits 0 under `unless-stopped`
   restarts in a loop; a process under `on-failure` is not restarted after a VM reboot when uvicorn's
   graceful SIGTERM exit was 0. Waiting is the only shape that is quiet in both cases.)
2. Otherwise `uvicorn.run(app, host=UI_BIND, port=UI_HTTP_PORT, server_header=False, proxy_headers=False, workers=1)`.
3. `app` is a pure ASGI callable. For an `http` scope it takes the single `Host` header; when
   `host_allowed(host, configured_hosts(UI_ALLOWED_HOSTS))` (allowed_hosts.py:62-64) is false, or the
   header is missing or repeated, it answers `400` with the fixed headers of `allowed_hosts.HEADERS`
   (allowed_hosts.py:31-33) and an empty body. Otherwise it answers `301` with
   `Location: https://<host_name(host)>:<UI_PORT><path>?<query>` and the same fixed headers plus
   `Content-Length: 0`. The name is the browser's own `Host` without its port, exactly as
   `HostCheck` would accept it, so the redirect never sends a browser to a name the manager would
   refuse. The port is omitted when `UI_PORT` is 443. Methods other than `GET` and `HEAD` answer
   `405`. A `websocket` scope is closed with 1008. `lifespan` passes.
4. Nothing is logged per request (an exposed port must not fill the disk with scanner lines); uvicorn's
   access log is off (`access_log=False`).

Why a redirect listener at all: every guide and every student's bookmark says `http://VM_IP:8081`
(README.md:89; QUICK-INSTALL.md:171; VM-CONNECTION.md:41; STANDALONE-SETUP.md:89; WIKI-MASTER-GUIDE.md:753).
A TLS listener on 8081 would turn those into `ERR_SSL_PROTOCOL_ERROR` with no hint; browsers'
HTTPS-first upgrades fall back to plain HTTP on a certificate error, so they would not rescue a
self-signed installation. A `301` costs one more container of the same image and one more firewall
line, and reveals only that a redirect exists.

Why a separate container and not a second listener in the manager's process: one flood on the
redirect port must not stall the manager's single event loop, and the manager's command line stays
one uvicorn invocation that `health_url` can parse (install-manager.py:100-116).

`recreate-manager.sh:41` becomes `up -d --no-build --no-deps backup-ui http-redirect`.
`start-manager.sh:95` (`up -d --force-recreate`) already recreates every service. The data-owner loop
(start-manager.sh:75-89) inspects containers that mount the data directory; the redirect service
mounts nothing, so it is ignored, which is correct.

### 4.2 HSTS

| Rule | Value |
|---|---|
| Header | `Strict-Transport-Security: max-age=31536000` |
| Sent when | `scheme(scope) == 'https'` (DESIGN.md 5.6 item 1), on every response of the manager: pages, `/api/`, static files, the gate's and `HostCheck`'s refusals. It belongs in the one `security_headers()` of `app/headers.py` that RECONCILIATION Dq 5 creates. |
| Not sent | over plain HTTP (the redirect listener never sends it; a browser ignores it there anyway, RFC 6797 §8.1). |
| `includeSubDomains` | no: the manager owns one name, and a lab's other services may live under it. |
| `preload` | no: preloading is irreversible for a name the operator may reuse. |
| Self-signed | A browser stores HSTS only from a connection without certificate errors (RFC 6797 §8.1), so a self-signed installation sends the header and the browser discards it. The header is still sent, so a later switch to a provided certificate needs no manager change. |
| Trusted certificate | After the first visit the browser refuses plain HTTP for a year and refuses to click through a later certificate error. That is the point, and it is the lockout case 10.4. |

A test asserts the header with `TestClient(app, base_url='https://testserver')` and its absence with
the default `http://testserver` (the `HostCheckTests` pattern, test_app.py:317-399, sends explicit
`Host` headers; a `https` base URL sets `scope['scheme']`).

## 5. The listener and the VM's other doors

### 5.1 `UI_BIND`

Stays `0.0.0.0`. The product must be reachable by students; the firewall (5.2) and sign-on are the
controls. An operator with a proxy sets `127.0.0.1` (2.3). The health check reports the bind
(`tls.bind`, 6).

### 5.2 Host firewall

New `deploy/setup-firewall.sh` (root; in the installer as the step *Firewall* after the manager
verification, 7.2; `--no-firewall` in advanced mode skips it; the standard path runs it, D3 point 4):

1. Requires `ufw` (installed on Ubuntu Server 24.04; otherwise `apt-get install -y ufw` through
   `install-prerequisites.sh`, which already installs packages).
2. Determines the ports: the SSH port from `sshd -T` (the `awk '$1 == "port"'` of
   setup-password.sh:83-85), `UI_PORT` and `UI_HTTP_PORT` from `.env` with the defaults (the
   `env_value` reader of start-manager.sh:62-63), and the port of the current session from
   `SSH_CONNECTION` when set. **It refuses to continue when the session's port is not in the list**
   (an operator on a non-default SSH port is never locked out by this script).
3. Runs, in this order: `ufw allow <ssh>/tcp` for each SSH port, `ufw allow <UI_PORT>/tcp`,
   `ufw allow <UI_HTTP_PORT>/tcp` when not 0, `ufw default deny incoming`, `ufw default allow outgoing`,
   `ufw --force enable`. An already active ufw with the operator's own rules keeps them: the script
   only adds allows; it never runs `ufw reset`.
4. Prints `ufw status numbered` and the sentence *Docker-published ports bypass this firewall; the
   health check lists them.*
5. `--remove` deletes the three allows it added (by the comment `clab-manager` it attaches with
   `comment`), never disables ufw.

What the firewall does not cover, stated in INSTALL.md (8.1): Docker inserts its own `nat` and
`FORWARD` rules ahead of ufw's chains, so a port a container publishes on `0.0.0.0` is reachable
regardless of ufw. The capture stack publishes `127.0.0.1` only (compose.capture.yml:24-25, 50-51;
asserted at test_release_consistency.py:140-148), so it is safe. **Lab nodes** publish a port only when
a topology says `ports:` (the schema allows it, app/static/clab-schema/*.json:203; the template lab
has none, deploy/lab-template/bgp-core.clab.yaml:10-20; the manager already reads a container's
bindings for the diagnostics drawer, host_operations.py:247-257, 531). Such a port is a door the
manager cannot close; the health check names it (`exposure.ports`, 6), and the lab builder's check
may warn on it later (a UI item for the lead's backlog, not this campaign). The `DOCKER-USER` chain
is not written by the installer in this version (a rule there is the right tool, but a wrong rule
breaks lab connectivity; it needs its own design and live validation).

### 5.3 The capture stack

Unchanged: loopback-only by design (CAPTURE.md:214-221), reached through the manager's same-origin
relay. Under TLS the relay's `wss://` and `Secure` cookie fall out of the scope (2.1.4), and noVNC's
*requires a secure context* console line (CAPTURE.md:280-283) stops, because `https://` is a secure
context. The clipboard helper (`navigator.clipboard`, clipboard.js:19) also starts working on a
non-loopback address for the same reason; its fallback stays.

### 5.4 The SSH door

`clab-discovery` keeps its exact policy (deploy/clab-manager-password.conf:2-13, installed and verified
by setup-password.sh:43-58; checked by check_host.py:20-26, 148-154). This design changes neither
the gateway nor the helpers nor that `Match` block.

New `deploy/setup-ssh-hardening.sh` (root; installer step *SSH hardening* after the firewall; opt-out
`--no-ssh-hardening` in advanced mode): writes `/etc/ssh/sshd_config.d/40-clab-manager.conf` with
only the directives whose **effective** value (`sshd -T`, the `_effective` call of
check_host.py:100-101) is still OpenSSH's default, so an operator's own choice in `sshd_config` is
never overridden by the drop-in (Ubuntu includes `sshd_config.d/*.conf` first, and the first value
wins):

| Directive | Value | Reason |
|---|---|---|
| `PermitRootLogin` | `no` | Root has no password on Ubuntu; this closes the key path too. |
| `MaxAuthTries` | `4` | Fewer guesses per connection. |
| `LoginGraceTime` | `30` | Unauthenticated connections are dropped sooner. |
| `PerSourceMaxStartups` | `8` | Caps unauthenticated connections per source (OpenSSH 8.5+; Ubuntu 24.04 ships 9.6). |
| `X11Forwarding` | `no` | Not used by anything here. |

Not written: `PasswordAuthentication` (WinSCP users and the engineer's VS Code use passwords,
INSTALL.md "WinSCP file transfers"; the `Match User clab-discovery` block needs it), `AllowTcpForwarding`
(VS Code Remote-SSH forwards its server port), `AllowUsers`. The script validates with `sshd -t -f`
on a candidate, applies, `sshd -t`, `systemctl reload`, with the temp-and-rollback shape of
setup-password.sh:29-42. `--remove` deletes the drop-in and reloads. `fail2ban` is **recommended in
INSTALL.md and reported by the health check** (`ssh.bruteforce`, WARN when not active), not
installed by the installer: its default sshd jail bans the operator's own address after five typos
within ten minutes, which the installer cannot judge for them. OpenSSH 9.8's `PerSourcePenalties` is
noted as the built-in replacement for an Ubuntu release that ships it.

## 6. Health check additions

New module `deploy/check_exposure.py` (stdlib only; loaded with `module('check_exposure')` as
`check_host` and `check_git` are, check_install.py:758-762) exposing `check_exposure(ctx)`, run as the
group *TLS, firewall and exposure* right after *Docker, manager and persistent storage* (it needs
`ctx.container` and `ctx.base_url`). Every check uses `ctx.add(ident, status, title, detail, fix)`
(check_install.py:92-96), `ctx.run` (check_install.py:101-158) and the two HTTP helpers below.

### 6.1 Changes in `check_install.py`

| Place | Change |
|---|---|
| `Context.http` (160-202) | The opener gains `HTTPSHandler(context=ctx.tls_context)`, where `tls_context = ssl.create_default_context(cafile=<tls dir>/cert.pem)` with `check_hostname = False`: the probe **pins the installed certificate** (so a `PASS` proves the listener serves exactly that file) and the name check is a separate finding (`tls.names`). When `cert.pem` is unreadable, `tls_context` is `None` and every HTTP check reports `SKIP` with the `tls.files` fix. |
| `Context.head(path)` (new) | `GET` with `NoRedirect` (31-33) returning `(status, headers)` with no body parsing, for the redirect and HSTS checks. Mockable like `http`. |
| `check_docker` 284-295 | `health_url()` now yields `https://…/api/health`; the check expects `{"ready": true}` (DESIGN.md 6.7). The version was already proved through `docker exec` at 277-281, so nothing is lost. Title stays *Manager HTTP*; detail says *TLS* . |
| `check_design_engine` (316-327) and `check_capture` (600-630) | Both routes are behind the gate now. The facts come from `docker exec <container> python -m app.probe design-engine` and `… capture` (section 9, interface 5), parsed with `parse_json` (216-222), with the same PASS/WARN/FAIL sentences as today. |
| `Context.manual[0]` (81-84) | *open the manager at `https://<VM address>:8443` …* and *accept or verify the self-signed certificate by its fingerprint*. |

### 6.2 The checks

| id | PASS | WARN | FAIL | fix (a `Next:` line) |
|---|---|---|---|---|
| `tls.files` | directory, `cert.pem`, `key.pem`, `mode` present with the owners and modes of 3.3 | — | anything missing, a symlink, a wider mode, a world-readable key | `sudo bash …/deploy/setup-tls.sh` |
| `tls.cert` | not expired, more than 30 days left; detail prints notAfter, mode and the fingerprint (from `openssl x509 -noout -enddate -fingerprint -sha256 -in cert.pem`, run unprivileged, the file is 0644) | fewer than 30 days left | expired, or `openssl` cannot parse it | `setup-tls.sh --renew` (self-signed) or `setup-tls.sh --cert … --key …` (provided) |
| `tls.names` | every current non-loopback address (`ip -j address`, as 510-513) and every `UI_ALLOWED_HOSTS` name is a SAN | a current address or a listed name is missing from the SANs; detail names them | — | `setup-tls.sh` (ensure regenerates a self-signed one) or a new provided certificate |
| `tls.bind` | the container command (`check_docker` already inspects `.Config.Cmd`, 260-262) carries `--ssl-certfile`, `--ssl-keyfile` and `--no-proxy-headers`; detail prints the bind and the port | `--no-proxy-headers` missing (an older compose file) | no `--ssl-certfile`: the manager serves plain HTTP | `sudo bash …/deploy/start-manager.sh` (rebuilds from the current compose file) |
| `tls.listener` | `ctx.head('/api/health')` over HTTPS with the pinned certificate answers 200 | — | handshake fails against the pinned certificate (the listener serves another certificate), or no answer | `setup-tls.sh --show` then `recreate-manager.sh` |
| `http.redirect` | `ctx.head('/', base='http://127.0.0.1:<UI_HTTP_PORT>')` answers 301 with `Location` = `https://127.0.0.1:<UI_PORT>/` | `UI_HTTP_PORT` ≠ 0 and the redirect container is not running (`compose ps --status running --quiet http-redirect` empty), or it answers something other than 301 | **plain HTTP serves a page**: any 200 from the redirect port, or a 200 over plain HTTP from the TLS port's address (the probe tries `http://127.0.0.1:<UI_PORT>/` too and expects a connection error) | `start-manager.sh`; when `UI_HTTP_PORT=0` the check is `INFO HTTP redirect disabled` |
| `http.hsts` | the HTTPS `/api/health` response carries `strict-transport-security` with `max-age=31536000` | header absent or another value (an older image) | — | `start-manager.sh` (rebuild) |
| `firewall` | `ufw status verbose` (privileged) says `Status: active`, default `deny (incoming)`, and the SSH port, `UI_PORT` and `UI_HTTP_PORT` (when ≠ 0) are allowed | ufw inactive, or a needed port not allowed (the detail names it) | `ufw` not installed | `sudo bash …/deploy/setup-firewall.sh`; a cloud security group is accepted as the reason to ignore the WARN, said in the detail |
| `exposure.listeners` | every listening TCP socket (`ss -Hltn`, privileged for process names `-p`) that is not loopback is one of: the SSH port, `UI_PORT`, `UI_HTTP_PORT`; detail lists them with the process name | any other non-loopback listener; detail names port and process | `5001` or `5801` (the capture stack) not loopback-only | *Close or firewall the listed port; the capture stack must stay on 127.0.0.1 (`deploy/compose.capture.yml`).* |
| `exposure.ports` | no running container publishes a port on `0.0.0.0` or `[::]` (`docker ps --format '{{.Names}}\t{{.Ports}}'`, privileged; the capture stack's `127.0.0.1:` bindings pass) | a container does; detail names container and port (a lab node with `ports:` in its topology) | — | *Remove `ports:` from the topology or bind them to 127.0.0.1; Docker-published ports bypass ufw.* |
| `signon.bootstrap` | `/srv/containerlab-node-manager/data/setup-code` absent (`test -e`, privileged, as 662-664) | present with `mode=setup`: **Setup not completed: no administrator exists** (D3 point 2); or `mode=recover`: *A recovery is open* | — | *Open `https://<address>:<port>/setup` and enter the code from `sudo cat /srv/containerlab-node-manager/data/setup-code`.* **The report never prints the code** (HEALTH-CHECK.md "Save a support report": reports are shared). The privileged read is `head -c 16` of the first line only (`mode=…`). |
| `ssh.hardening` | `sshd -T` (privileged, 100-101) shows `permitrootlogin no`, `maxauthtries ≤ 4`, `logingracetime ≤ 30` | any of them at the OpenSSH default; detail names which | — | `sudo bash …/deploy/setup-ssh-hardening.sh` |
| `ssh.bruteforce` | `systemctl is-active fail2ban` succeeds | not active or not installed; detail: *recommended on an Internet-facing VM; see INSTALL.md* | — | `sudo apt-get install -y fail2ban` (documented, not scripted) |

Semantics: `FAIL` makes the overall result *FAILURES FOUND* (summarize, 677-682) and is reserved for a
state where the manager is unsafe or unreachable; `WARN` is a door that is open or a limit that is
near; `INFO` is a fact. The checks never change anything, never read the key, and never print a code.

### 6.3 Test pattern

`tests/test_check_exposure.py` (stdlib, runs with the system `python3` in CI's first group,
release-check.yml:19-37), modelled on `test_check_install.py`:

```python
def context(**overrides):            # as test_check_install.py:25-35
    ctx = check.Context(check.arguments([]), owner='archtop', privileged=True)
    ctx.version = VERSION; ctx.container = 'a' * 64; ctx.base_url = 'https://127.0.0.1:8443'
    ctx.tls_context = object()       # a stand-in: the opener is mocked
    ctx.run = Mock(side_effect=router(...))   # keyed on argv[0] / the openssl or ss or ufw subcommand
    ctx.head = Mock(side_effect=lambda path, base=None: ...)
```

Required cases, each asserting `check.render(check.summarize(ctx))` or the JSON:

1. A healthy VM: every id `PASS` except `ssh.bruteforce` as the test chooses.
2. An expired certificate → `tls.cert FAIL`; 20 days left → `WARN`; the fingerprint appears in the
   detail exactly as `openssl` printed it.
3. A new address not in the SANs → `tls.names WARN` naming the address.
4. The redirect port answering `200` → `http.redirect FAIL`; `UI_HTTP_PORT=0` → `INFO`.
5. `setup-code` present with `mode=setup` and a body `PRIVATE` → `signon.bootstrap WARN` and the
   sentinel `PRIVATE` (test_check_install.py:21) does not appear anywhere in the report.
6. `tls.files` with a 0644 key → `FAIL`; the report contains no key material (the fake probe returns a
   `PRIVATE` sha256 for the key and the test asserts it is absent).
7. No `docker` answer → the group's checks `SKIP` with the Docker fix, never `PASS`.

## 7. Installer changes

### 7.1 File by file

| File | Lines | Change |
|---|---|---|
| `clab-backup-ui/compose.yml` | 8, 16-21, new service | The command of 2.2, the tls mount, the `http-redirect` service (4.1). |
| `deploy/compose.image.yml` | 11, 19-24, new service | Mirror of the above with `${MANAGER_IMAGE}` for both services. |
| `clab-backup-ui/Dockerfile` | 22, 24 | `EXPOSE 8443 8081`; `CMD` with the TLS arguments and `--no-proxy-headers --no-server-header`. |
| `deploy/start-manager.sh` | after 24; 95; 101; 105 | `bash "$script_dir/setup-tls.sh" --no-recreate` after `setup-vm.sh`; `up` unchanged (recreates both services); line 101 → *Open the manager at `https://<address>:<UI_PORT>` (plain HTTP on <UI_HTTP_PORT> redirects there). Certificate fingerprint: …*; line 105 → *Sign-on: the first administrator is created in the browser with the setup code; the installer prints it, or run `sudo cat /srv/containerlab-node-manager/data/setup-code`.* |
| `deploy/recreate-manager.sh` | 41 | `up -d --no-build --no-deps backup-ui http-redirect`. |
| `deploy/setup-tls.sh`, `deploy/setup_tls.py` | new | Section 3. |
| `deploy/setup-firewall.sh` | new | 5.2. |
| `deploy/setup-ssh-hardening.sh` | new | 5.4. |
| `deploy/manager-recover-admin.sh` | new | DESIGN.md 9.5 and RECONCILIATION §4.4: root only, no options, finds the container exactly as `recreate-manager.sh:16-39` does (source route or prepared image), runs `docker exec <id> python -m app.recover`, prints its output unchanged, exits with its status. It never reads `.env` values and never prints anything of its own but the route it chose. |
| `deploy/install-manager.py` | 100-116 | `health_url(command)` returns `https://<addr>:<port>/api/health` when `--ssl-certfile` is in the command and raises `ValueError('The manager is configured without TLS; rebuild it with Install/update.')` otherwise. `test_install_manager.py:55-66` is rewritten for the new form (the behavioural claim, bind and port extraction, is kept; the expected string changes). |
| | 119-152 | `check_manager`: the opener pins `/srv/containerlab-node-manager/tls/cert.pem` (readable by the ordinary account, 0644) with `check_hostname=False`; expects `{"ready": true}`; the version comparison at 125-128 stays as the only version proof; `say` lines 143-145 print `https://`, then the fingerprint (from `openssl x509`, unprivileged) and the setup state (7.3). |
| | 244-254, 257-279 | The two sentences *all VM interfaces, port 8081* → *all VM interfaces, TLS port 8443, plain-HTTP redirect on 8081*. |
| | 544-562 | Advanced mode asks two more questions: *Firewall* (set up / skip) and *SSH hardening* (apply / skip), and the port question of 7.4 when an existing `.env` collides. |
| | 565-583 | `plan_lines` gains: *TLS: self-signed certificate for <addresses and names> in /srv/containerlab-node-manager/tls (kept if one exists)* or *TLS: keep the provided certificate (expires <date>)*; *Firewall: ufw allow <ssh>, <UI_PORT>, <UI_HTTP_PORT>; deny other incoming*; *SSH: conservative sshd drop-in (PermitRootLogin no, MaxAuthTries 4, LoginGraceTime 30)*; *Sign-on: the first administrator is created in the browser with a setup code printed at the end.* |
| | 605-631 | `install_steps`: after `verify`, `Step('signon', 'Setup code', …, bare=True)` (7.3), `Step('firewall', 'Firewall', command_step(['sudo','bash',…'setup-firewall.sh']), argv=…)`, `Step('sshd', 'SSH hardening', …)`; both `visible` only when chosen; the total count follows. |
| | 679-681 | The closing lines name the HTTPS address, the fingerprint and the setup step before the Git and health-check sentences. |
| `deploy/installer_tui/probes.py` | 7, 80-93 | The docstring and `env_settings` keys add `UI_HTTP_PORT`. |
| | 96-109 | `manager_address` returns `https://…`. `test_install_tui_core.py:1123` keeps its secrecy claim. |
| | 112-119, 141-168 | `http_version` becomes `http_ready(url, cafile)` reading `/api/health`; `probe_manager` reads the version with `sudo -n docker exec … python -c 'from app import __version__; …'` (the `sudo -n` shape of 157-159) and reports `Needs authentication` with *answering on port N; version needs sudo* when refused. The dashboard gains a row `tls` (*TLS certificate: self-signed, expires <date>* / *provided*) from `setup-tls.sh --show` run unprivileged. |
| `deploy/installer_tui/engine.py` | 352-361 | Unchanged in shape; `check_manager` now prints the extra lines through `say`. The run record (473-478) stays metadata-only: **the setup code and the fingerprint are never written to it.** |
| `deploy/installer_tui/app.py` | 261, 607 | The two *port 8081* sentences. |
| | 1753-1757 | `https://{address}:{port}/`, plus two steps: *The certificate is self-signed: the browser warns once; its SHA-256 fingerprint is <…>* and *Create the first administrator at `https://…/setup` with the setup code shown above* (or *An administrator exists; sign in*). |
| `deploy/check_install.py`, `deploy/check_exposure.py` | 6.1, 6.2 | |
| `clab-backup-ui/app/allowed_hosts.py` | 27-30 | `REFUSAL` names `https://192.0.2.10:8443/`. The docstring's *has no login* (3) is DESIGN.md's to change. |

### 7.2 Order of a fresh installation

1. Prerequisites (unchanged).
2. `start-manager.sh`: verify release (19) → `setup-vm.sh` (24) → **`setup-tls.sh --no-recreate`** (new) →
   `setup-discovery.sh` (25) → helpers → capture stack (64-70) → build (73) → `up` (95): the manager
   starts in setup mode (DESIGN.md 9.1) serving TLS; the redirect starts.
3. Verification (`check_manager`): HTTPS `/api/health` with the pinned certificate; prints address,
   fingerprint.
4. **Setup code**: `sudo cat …/data/setup-code` (the data directory is 0700 uid 10001,
   setup-vm.sh:8, so the ordinary account cannot read it); print *Open `https://<address>:<port>/setup`
   and enter: `xxxxxx-xxxxxx-xxxxxx-xxxxxx`*. When the file is absent: *An administrator exists; sign in
   at …*. The plain menu prints it; the TUI shows it on the summary screen (never persisted).
5. Firewall (5.2), SSH hardening (5.4), engineer access, lazydocker, Git: unchanged order after.
6. The health check at the end (6).

### 7.3 Prepared-image installations

`recreate-manager.sh` chooses `deploy/compose.image.yml` and `deploy/image.env` (29-39). The tls
directory is the same path, so `setup-tls.sh` serves both routes. `setup_tls.py` reads
`UI_ALLOWED_HOSTS`, `UI_PORT` and `UI_HTTP_PORT` from both env files (union for names; for ports the
file `recreate-manager.sh` would use wins, which `setup_tls.py` determines with the same test as
recreate-manager.sh:31-39, so a prepared-image install with `UI_PORT` in `image.env` is validated
against the right file). The migration write of 7.4 goes to that same file.

### 7.4 Upgrade from a plain-HTTP installation

An existing VM has: `.env` without `UI_*` (the common case, install-manager.py:244-254 never writes
them) or with `UI_PORT=8081` copied from the sample at WIKI-MASTER-GUIDE.md:1509; a manager on
`http://VM:8081`; students with that address; no certificate; no firewall rules; an operator who
has never signed in to anything. After `bash deploy/install.sh` → *Install or update*:

| Situation | What happens | Who decides |
|---|---|---|
| No `UI_PORT` in `.env` | TLS on 8443, redirect on 8081. Old links `http://VM:8081` answer `301` to `https://VM:8443`. | automatic; `plan_lines` says it |
| `UI_PORT=8081` explicit, `UI_HTTP_PORT` absent | **Standard path:** the operator's explicit port is kept for TLS and `setup_tls.py` writes `UI_HTTP_PORT=0` (the `write_env` pattern), then prints: *Your settings keep the manager on port 8081, which now serves HTTPS; there is no plain-HTTP redirect. Old links `http://VM:8081` show a browser error until retyped as `https://`. To get the redirect, set `UI_PORT=8443` and `UI_HTTP_PORT=8081` in `.env` and rerun.* **Advanced path:** the question *Manager ports: (1) TLS on 8443 and plain-HTTP redirect on your current 8081 (recommended) (2) TLS on your current 8081, no redirect*; (1) writes `UI_PORT=8443`, `UI_HTTP_PORT=8081`. | the installer; the operator in advanced mode |
| `UI_PORT == UI_HTTP_PORT`, both explicit | `setup_tls.py` refuses with the sentence above; `start-manager.sh` stops before building. | the operator |
| A certificate already in the tls directory | kept (ensure semantics, 3.1). | automatic |
| `UI_ALLOWED_HOSTS` set | its names become SANs. | automatic |

Why the operator is not locked out: the old address answers with a redirect; the new address answers
with the setup page (DESIGN.md 12.1: an upgraded install is in setup mode), and the code is printed
by the installer the operator is sitting at, and remains readable with `sudo cat`. The firewall step
runs after the manager verification and allows the session's own SSH port first (5.2). Nothing in
this design deletes or rewrites a setting the operator wrote, except the one `UI_HTTP_PORT=0` line
above, which is announced and reversible.

Why plain HTTP is not silently kept: after the upgrade the only plain-HTTP answer on the VM is
`301`; the health check fails when a page is served over plain HTTP (`http.redirect`, 6.2); the
compose files contain no plain-HTTP command.

## 8. Documentation and CI

### 8.1 Documents

| File | Section / lines | Change |
|---|---|---|
| `docs/INSTALL.md` | 202-248 *Opening the manager by a name* | Rewrite the first paragraph (the manager has a login now, DESIGN.md), keep the DNS-rebinding list, add that every listed name becomes a certificate name (3.2) and that `recreate-manager.sh` after a change needs `setup-tls.sh` too (ensure runs at upgrade only); replace the reverse-proxy advice at 220-235 and 246-248 with 2.3 (tolerated, source address caveat). |
| | new *TLS and the certificate* after *Browser Wireshark* (177-201) | Self-signed default, the browser warning and the fingerprint (3.6), `setup-tls.sh` options (3.1), a provided certificate and the certbot hook (3.4), importing the certificate on managed workstations (3.5), the 730-day renewal. |
| | new *Firewall and SSH* | 5.2 and 5.4, fail2ban recommendation, the Docker-published-ports caveat. |
| | new *Ports* | 8443 TLS, 8081 redirect, `UI_HTTP_PORT=0`, the upgrade table 7.4. |
| | *Finish in the browser* (331-391) | `https://`, the first-administrator step (UI.md's wording). |
| `docs/CAPTURE.md` | 236-243 | Replace *The manager still has no user login … authenticated HTTPS reverse proxy* with: the manager needs a session and serves TLS itself; a proxy is not needed. |
| | 280-287 | The noVNC *secure context* paragraph becomes history: *before TLS (1.31.8 and earlier) the console logged …*; the rebuild advice stays. |
| `docs/HEALTH-CHECK.md` | *What it checks* (92-123) | The new group and its ids (6.2). |
| | 232-239 | `https://…:8443`, accept or verify the certificate, the firewall sentence. |
| `docs/STANDALONE-SETUP.md` | 89-90, 107 | `https://VM_ADDRESS:8443`; the sign-in sentence; the `docker run` migration needs the tls mount. |
| `docs/FRESH-VM-GUIDE-V2.md` | 584-600 | `8443` and `8081`; *the installer sets up ufw* replaces *does not configure … firewall rules* (595-596); the `Test-NetConnection` lines. |
| `docs/VM-CONNECTION.md` | 41 | `https://VM_IP:8443`, sign in first. |
| `docs/QUICK-INSTALL.md` | 62, 171 | Same. |
| `README.md` | 89, 125 | Same; the diagram says *port 8443 TLS · 8081 redirect*. |
| `docs/WIKI-MASTER-GUIDE.md` | 31, 55, 72, 719, 753, 776-793, 808, 1399, 1414, 1509, 1572 | Each `8081` and *no login* sentence; the sample `.env` gains `UI_HTTP_PORT`. |
| `docs/ARCHITECTURE.md` | 150-157 | The transport paragraph: uvicorn-native TLS, the redirect service, `--no-proxy-headers`, HSTS in `security_headers()`. |
| `clab-backup-ui/README.md`, `deploy/*.md` | wherever `http://` or `8081` appears | Same. `verify-release.py` `verify_docs` does not check URLs; `check_links.py` does not either; a `grep -rn 'http://[^ ]*:8081'` across the living guides before the release is the lead's check. |
| `CLAUDE.md` | invariants | The lead's: *The manager serves TLS itself; the compose command carries the certificate paths and `--no-proxy-headers`; the only plain-HTTP listener is `app.redirect`, which holds no data and answers 301 or 400.* |

### 8.2 CI and tests

| Where | Addition |
|---|---|
| `.github/workflows/release-check.yml:40` (`bash -n` loop) | `deploy/setup-tls.sh deploy/setup-firewall.sh deploy/setup-ssh-hardening.sh deploy/manager-recover-admin.sh`. |
| release-check.yml:19-37 (stdlib group) | `test_setup_tls.py`, `test_setup_firewall.py`, `test_setup_ssh_hardening.py`, `test_check_exposure.py`, `test_recover_admin_script.py`. |
| venv group | `test_redirect.py` (TestClient on `app.redirect:app`: 301 with the exact `Location`, 400 on a refused `Host`, 405, 1008 on a socket; no import of `app.main`). |
| `tests/test_setup_tls.py` | SAN list from fixtures (addresses, names, union of two env files); the exact `openssl` argv; **real generation into a temp dir** (CI's Ubuntu has `openssl`) and parse-back of SANs and `-checkend`; a provided pair that does not match is refused; an encrypted key is refused; modes 0644/0640; `mode` file; `UI_PORT == UI_HTTP_PORT` refused; the 7.4 migration write through `setup_capture.write_env` keeps unrelated lines. |
| `tests/test_setup_firewall.py` | The `test_recreate_manager.py` pattern (a copy of the script with the root guard neutralised, a fake `ufw`, `sshd` and `ss` on `PATH` recording argv): the allow order, refusal when `SSH_CONNECTION`'s port is not allowed, `--remove`, never `reset`. |
| `tests/test_setup_ssh_hardening.py` | Same pattern with a fake `sshd -T`: a directive at the default is written, a customised one is not; rollback on `sshd -t` failure. |
| `tests/test_release_consistency.py:88-99` | Compare the environment keys of **both** services across the two compose files; assert both commands carry `--ssl-certfile /tls/cert.pem`, `--ssl-keyfile /tls/key.pem`, `--no-proxy-headers`; assert the tls mount is `read_only: true`; assert `http-redirect`'s command is `python -m app.redirect`. |
| `tests/test_install_manager.py:55-66` | `https://…/api/health`; a command without `--ssl-certfile` raises. |
| `tests/test_check_install.py` | `check_docker` expects `{"ready": true}`; the capture and design-engine cases route through the `docker exec` probe. |
| `tests/test_app.py` | HSTS present under `base_url='https://testserver'`, absent under `http`. |
| `deploy/verify-release.py:40-41` | No new HTML page here (UI.md adds `login.html` and `setup.html`). |

## 9. Interfaces to the other parts

What this design needs from `DESIGN.md` (D) and `UI.md` (U), and what it gives back.

1. **The scheme rule (D 5.6).** Answer: uvicorn terminates TLS, so `scope['scheme']` is `https` and
   `ws.url.scheme` is `wss` without configuration. **`UI_TLS` is not needed and this design does not
   add it to the compose files.** Recommendation: `origin.scheme(scope)` reads the scope only. If the
   lead keeps the environment read for a future remote-proxy design, it must be documented as
   unsupported and `test_release_consistency.py` must assert the key is absent from both compose
   files, because a stray `UI_TLS=1` on a plain-HTTP fixture makes every cookie `Secure` and locks the
   tester out. RECONCILIATION §4.1 expected the key in both files; this is the answer it waited for.
2. **The `Secure` cookie (D 5.3).** `Secure` when `scheme(scope) == 'https'`: on every shipped
   installation. On the fixture over `http://127.0.0.1` it is not `Secure`, which is correct.
3. **The health route (D 6.7).** `GET /api/health` → `200 {"ready": true}` with `Cache-Control:
   no-store`, exempt from the gate, answering in setup mode and in recovery mode (D 9.3 lists it).
   The installer polls it over HTTPS with the pinned certificate; the health check reads it. It must
   not redirect, not set a cookie, and not vary by `Accept`.
4. **No redirect loop.** The manager never answers a plain-HTTP request (there is no plain-HTTP
   listener on it), so the gate's `302 /login?next=…` (RECONCILIATION §1, *Page vs API*) and the
   redirect listener's `301` cannot chain: `301` goes to `https://host:8443<path>`, then the gate
   decides. U's `loginNext` must accept the paths that the `301` preserves (it already accepts `/` and
   fragment-free paths, UI.md:861).
5. **Probes without a session.** `python -m app.probe design-engine` and `python -m app.probe
   capture` (the backend's), printing the same JSON the two routes print today
   (check_install.py:316-327, 600-630 consume them), **without constructing a `Store`** (CLAUDE.md:
   constructing one writes state; a second process against live data is forbidden) and without an
   HTTP request: the design engine status is a static answer (`design_engine.engine_status()`), the
   capture facts come from the environment and the two loopback services. The health check runs
   them through `docker exec` as `STORAGE_PROBE` does (check_install.py:299-313, 331).
6. **The setup code (D 9.2).** The file `/srv/containerlab-node-manager/data/setup-code` with `mode=`
   on the first line; the installer prints the code (7.2 step 4), the health check prints only its
   presence (6.2). The manager's log line (D 9.2) should name `https://` and the TLS port it is
   bound to; the port is in uvicorn's `--port`, which the app can read from `scope` only at a
   request, so the log line uses *the manager's address* and the installer supplies the exact URL.
7. **Recovery (D 9.5).** `app/recover.py` prints the URL as `https://<address>/setup`; the script in 7.1
   runs it. The 15-minute window is the file's mtime, which is on the VM's clock (10.2).
8. **HSTS** lives in `security_headers()` (RECONCILIATION Dq 5), sent when `scheme(scope) == 'https'`.
9. **The source address (D 8.1, D 10).** `scope['client'][0]` is the real client on every supported
   mode (2.3) because `--no-proxy-headers` is explicit (2.2). Under the tolerated proxy mode it is
   `127.0.0.1`; INSTALL.md says so.
10. **The 401 on the poll (U 3.3).** Unaffected by TLS; the `Secure` cookie travels on every `wss://`
    handshake because the page is `https://`.
11. **The sign-in page's plain-HTTP banner (U, `#signin-plain`, UI.md:166, 229-230).** It can only
    appear on a fixture; on a shipped installation no page is served over plain HTTP. It stays as
    written (it is the right sentence for a fixture reached by a LAN address).
12. **Invariant wording (lead).** `app/redirect.py` is a listener outside the guard; CLAUDE.md's
    *never add a route or socket outside this* needs the sentence of 8.1 (last row) so that the
    redirect is the named exception, with its two allowed answers.

## 10. What a reviewer should attack

| # | Assumption or failure mode | What the design does | What to attack |
|---|---|---|---|
| 10.1 | **Certificate expiry.** 730 days; ensure renews within 30 days at an upgrade; the health check warns and then fails. | A VM not upgraded for two years and never health-checked serves an expired certificate; browsers warn harder (Chrome still allows click-through for an expired self-signed certificate; an HSTS-stored trusted one is blocked). | Whether a renewal should also run from a timer (a systemd timer running `setup-tls.sh` monthly). Not in this version: a timer that recreates the manager at night would end sessions mid-course. |
| 10.2 | **Clock skew.** `notBefore` is the VM's time at generation; the recovery window is the VM's mtime. | `check_host._clock` warns when NTP is not synchronised (check_host.py:67-75); the installer checks NTP before APT (install-manager.py:571). A workstation whose clock is behind the VM's sees *not yet valid*. | OpenSSL 3.0 has no `notBefore` option for `req -x509`; backdating needs `openssl ca`. Decide whether the complexity is worth one rare case. |
| 10.3 | **A name not in the certificate.** Students type a name the operator never listed. | The warning is the same interstitial as for self-signing (`ERR_CERT_COMMON_NAME_INVALID` vs `ERR_CERT_AUTHORITY_INVALID`); `HostCheck` refuses the name anyway unless listed (allowed_hosts.py:62-64), so the list and the SANs move together; `tls.names` warns. | A single-label name typed by students passes `HostCheck` without being listed and is in the SANs only when it equals the VM's host name. |
| 10.4 | **HSTS lockout.** A trusted certificate lapses to self-signed or expires. | Browsers that stored HSTS refuse to click through until the certificate is fixed; `max-age` one year; no `preload`, so a `chrome://net-internals/#hsts` deletion or the fix works. | Whether 180 days is the better `max-age` for a product whose operators are lab engineers, not web teams. |
| 10.5 | **Own origin under TLS.** The guard (main.py:122-123), both sockets, the capture cookie. | Correct by the scope because uvicorn terminates TLS and `--no-proxy-headers` is explicit (2.1.3). | Confirm in the running container that `uvicorn --no-proxy-headers` is honoured with `--factory` (it is a server option, not an app option), and that nothing else installs `ProxyHeadersMiddleware`. |
| 10.6 | **DNS rebinding under TLS.** | Unchanged: `HostCheck` stays outermost (DESIGN.md 6.1). TLS adds a second barrier: a browser's `fetch` to the attacker's name hits a certificate whose SANs lack that name and cannot click through. | The attacker first serves their own self-signed certificate on their name and the student clicks through there; Chrome stores the exception per host **and certificate**, so the manager's certificate on that host still errors. Verify this claim against current Chromium behaviour before relying on it in a guide; the design relies on `HostCheck`, not on this. |
| 10.7 | **The redirect listener.** A stdlib-free uvicorn process exposed to scanners. | Answers 301/400/405 only, no body, no log per request, `read_only`, `cap_drop ALL`, no mounts. `Location` is built from a `Host` that passed `host_allowed`. | An open-redirect reading: the target host is the one the client sent, with the scheme and port fixed, so a redirect only sends a client where it asked to go. Slow-client exhaustion of its event loop does not touch the manager. `--limit-concurrency` for both services is a possible addition. |
| 10.8 | **The disabled state waits instead of exiting.** | A container that *runs* and listens on nothing. | Someone reading `docker ps` wonders; the health check says `INFO HTTP redirect disabled`. The alternative (compose profiles) was rejected as fragile across the three scripts that run `up`. |
| 10.9 | **The firewall step on a remote session.** | The SSH port and `SSH_CONNECTION`'s port are allowed first; refusal when the session's port is unknown; never `reset`. | A session through a jump host or a port-forward where `SSH_CONNECTION` names an unexpected port; a VM whose sshd listens on several ports (the script allows all of `sshd -T`'s). A cloud security group that already blocks 8081 while the VM allows it is fine. |
| 10.10 | **Docker bypasses ufw.** | Said in INSTALL.md; `exposure.ports` names published ports. | Whether a `DOCKER-USER` rule should ship. Not now (5.2); needs live validation with deployed labs. |
| 10.11 | **sshd drop-in precedence.** `sshd_config.d/*.conf` is included first, so the drop-in wins over the main file. | Only directives at OpenSSH's default are written (5.4). | An operator's customisation in another drop-in that sorts after `40-` is overridden; the script compares effective values before writing, which covers that. |
| 10.12 | **Upgrade paths.** 7.4. | Explicit `UI_PORT=8081` keeps its port; one announced `UI_HTTP_PORT=0` write. | A prepared-image install with `UI_PORT` in `deploy/image.env` and a different value in `clab-backup-ui/.env` (`setup-capture.sh:20` writes only the latter, an existing quirk). 7.3 picks the file `recreate-manager.sh` would use. |
| 10.13 | **The key is group-readable by gid 10001 on the host.** | 0640 root:10001; the ordinary account is not in that group; `setup-engineer-access.sh` adds the engineer to `docker` and `clab_admins`, not to 10001. | Any process on the VM running as uid or gid 10001 outside the container (the data directory is already owned by 10001, setup-vm.sh:8, so this is not a new trust). |
| 10.14 | **TLS defaults.** Python's `ssl` defaults, uvicorn's `ssl_ciphers` default. | Minimum TLS 1.2. | Test with `openssl s_client -tls1_1` (must fail) and `testssl.sh` on the owner's live pass; add `--ssl-ciphers` only with a measured reason. |
| 10.15 | **The health check pins the certificate and disables the host-name check.** | Proves the listener serves the installed file; names are a separate finding. | A reviewer may prefer `check_hostname=True` against `127.0.0.1`; that breaks the provided mode (no loopback SAN), which is why it is split. |
| 10.16 | **The setup code in the TUI.** | Shown on the summary screen, never in the run record. | The TUI's log capture of step output (`bridge.output`, engine.py:427): the `signon` step is `bare` and prints through `say`, not through a captured process, so no line of it lands in a log the TUI keeps. Verify in `test_install_tui_app.py`. |
| 10.17 | **`check_manager` reads `cert.pem` as the ordinary account.** | 0644 by design. | If an operator tightens it, the installer's verification fails with a clear message (`cannot read … cert.pem`). |
| 10.18 | **Two containers from one image.** | `docker compose build` builds `backup-ui`; `http-redirect` uses the tag. | A prepared-image `.env` whose `MANAGER_IMAGE` is older than the checkout: both services run the same older image, which is the existing behaviour for one. |

## 11. Open questions for the lead

1. **`UI_TLS`:** drop it (9.1), or keep it as an undocumented fallback asserted absent from the compose
   files? This design recommends dropping it.
2. **The in-container probes (9.5):** is `python -m app.probe` the backend builder's slice, and is the
   no-`Store` rule satisfiable for the capture facts (they need the environment and two loopback
   services only; if any of them needs lab state, the health check drops that fact rather than
   constructing a `Store`)? The alternative, prompting the operator for a manager password inside
   `check-install.sh`, was rejected: it would create sign-in audit entries from a health check and
   conflate two credentials in one terminal session.
3. **`fail2ban`:** recommend only (this design), or install it from `install-prerequisites.sh` with
   `ignoreip` of the installing session's address? The latter needs the session's address from
   `SSH_CONNECTION` and a decision for console installs.
4. **`DOCKER-USER`:** out of this version (5.2); confirm, or schedule it with live validation.
5. **The `max-age`** of HSTS: one year (this design) or 180 days (10.4).
6. **`verify-release.py` and the docs:** no rule refuses `http://…:8081` in a living guide today. Add a
   documentation rule to `verify_docs()` (deploy/verify-release.py:132) that refuses `http://` manager
   URLs outside history files, or rely on the one-time grep of 8.1?
7. **The invariant sentence** for `app/redirect.py` (9.12) is the lead's at the release step.
