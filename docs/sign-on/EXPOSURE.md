# Exposure: TLS and hardening of an Internet-facing VM

Amended with the lead's rulings of RECONCILIATION.md section 4 (2026-11-01).
Amended with the answers of REVIEW.md (2026-11-01), and with the reviewer's second pass on that amendment
(the same day: the probe fallbacks, `fingerprint_saved`, the rewritten test list, the log line's port, the
TUI's addresses, the CLAUDE.md bullet, the non-origin-form target, the helper locks).

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
| **the health check** | `deploy/check-install.sh` → `deploy/check_install.py` and its modules `check_host.py`, `check_git.py`, and the new `check_exposure.py`. |
| **the gate** | `SessionGate` of DESIGN.md §6. |
| **a probe** | `python -m app.probe <name>`, run inside the manager container by the health check through `docker exec` (6.1). A probe reads the environment, a loopback service or `state.enc` read-only in the `STORAGE_PROBE` pattern, or, for `browse` and `git-registry`, the VM's helpers over the saved SSH connection in their read-only modes only (`browse`, `list`); it never constructs a `Store`, never writes and never makes an HTTP request to the manager. |
| **certificate addresses** | The IP addresses the certificate names (3.2): the global-scope addresses of the default-route interface(s) plus what the operator lists; never a bridge, a veth or a link-local address (REVIEW R18). |

## 1. Decisions in one table

| # | Question | Decision |
|---|---|---|
| 1 | TLS termination | **uvicorn serves HTTPS itself** (`--ssl-certfile /tls/cert.pem --ssl-keyfile /tls/key.pem`). Always on in both compose files. No Caddy sidecar. A reverse proxy is not a supported mode in this version (reasons in 2.3). |
| 2 | Certificate | **Self-signed by the installer with `openssl` on the VM**, ECDSA P-256, 730 days, SANs = the certificate addresses of 3.2 (the default-route interface's global addresses, never a bridge or a link-local address; REVIEW R18), its host name, `localhost`, the loopback addresses, every name in `UI_ALLOWED_HOSTS` and every name or address the operator gives with `setup-tls.sh --name`. A **provided** certificate (any CA, Let's Encrypt through certbot included) is installed with `setup-tls.sh --cert --key`. |
| 3 | Plain HTTP | **A redirect-only listener on 8081** (a second compose service running `python -m app.redirect`), nothing else on plain HTTP. It answers 301 to the manager's own HTTPS origin after `host_allowed`, 400 for a refused Host or a request target that is not a path, 405 for any method but GET and HEAD, closes a socket 1008, and nothing else (the one sentence of REVIEW R19, 4.1); `Location` is built from the raw path and query (REVIEW R20, 4.1 rule 3). **HSTS** `max-age=15552000` (180 days) on every HTTPS response, no `includeSubDomains`, no `preload`; its port-wide scope is documented (REVIEW R17, 4.2). |
| 4 | Other doors | `UI_BIND` stays `0.0.0.0`. New `deploy/setup-firewall.sh` (ufw: allow the SSH port, the TLS port and the redirect port; deny the rest). Lab-node published ports and any non-loopback listener are reported by the health check. New `deploy/setup-ssh-hardening.sh` writes a conservative sshd drop-in. The `clab-discovery` policy is not touched. |
| 5 | Health check | New module `deploy/check_exposure.py` (stdlib) with fourteen checks (section 6.2), plus the changes in `check_install.py` of 6.1: `GET /api/health` over TLS with the pinned certificate is **the only HTTP question the checker asks**; every other manager fact (design engine, capture, the saved VM connection, the topology browser, the Git registry) comes from a probe through `docker exec` (REVIEW R16). No check is dropped silently. |
| 6 | Installer | `setup-tls.sh` runs inside `start-manager.sh` before the image build; firewall and sshd hardening are installer steps after the manager verification; `health_url`, `probes.manager_address` and the TUI's address lines become `https://`; the fingerprint is printed with the verification and **the setup code is printed last, after every step that recreates the manager** (REVIEW U13). The recovery script prints the exact recovery URL (REVIEW R11). The upgrade decision is 7.4. |
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
5. The Dockerfile's `CMD` (Dockerfile:24) carries `--port 8443` (was 8081), the same TLS arguments, `--no-proxy-headers` and `--no-server-header` explicitly, and `EXPOSE 8443 8081`
   (Dockerfile:22). A `docker run` without the tls mount fails at start, which is the right outcome:
   the image never serves plain HTTP by accident.
6. Plain HTTP for development is not a container mode. The fixture tools run the app directly
   (`docs/redesign/tools/fixture_manager.py`, which signs the requests in through its own fixture-only
   ASGI wrapper and carries the `/__fixture/expire` hook as a route of its own, REVIEW R15 and R21:
   nothing fixture-only lives in `app/`), and `127.0.0.1` is a secure context in every browser.

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
| `UI_PORT` | `.env`, compose (both commands, and the `environment:` of both services: the manager prints it in its setup log line, 7.2) | 1-65535 | **8443** (was 8081) | the operator; the installer only in 7.4's advanced option (1), which writes `UI_PORT=8443` through `setup_capture.write_env` | `setup_tls.py` refuses `UI_PORT == UI_HTTP_PORT` (7.4) |
| `UI_HTTP_PORT` | `.env`, compose (redirect service only) | 0 or 1-65535 | 8081 | the operator; `setup_tls.py` (`UI_HTTP_PORT=0`, the standard path of 7.4) or the installer (advanced option (1), `UI_HTTP_PORT=8081`), both through `setup_capture.write_env` | `app.redirect` exits with a message on a value outside 0-65535 |
| `UI_ALLOWED_HOSTS` | `.env`, compose | names | empty | the operator (INSTALL.md:225-233) | existing (`configured_hosts`, allowed_hosts.py:67-76); its names also become SANs (3.2) |
| `UI_TLS` | — | — | — | **not introduced** (section 9, interface 1) | — |

No key holds a secret, so DESIGN.md ruling 13 (DESIGN.md:937-939, `runner.job_environment` passes
the environment to Ansible) holds: the key file is a path fixed in the compose command, not an
environment value.

The redirect service's environment is `UI_BIND`, `UI_PORT`, `UI_HTTP_PORT`, `UI_ALLOWED_HOSTS`. The
manager service's environment gains **one** key, `UI_PORT: ${UI_PORT:-8443}` (not a secret), for the
container log line of DESIGN.md 9.2 (7.2): the compose environment carries neither `UI_BIND` nor
`UI_PORT` today (compose.yml:8-15, they live on the command line only), uvicorn's `--port` reaches the
app only inside a request `scope`, and the line is printed at startup before any request.
`test_release_consistency.py:88-99` compares the **first** `environment:` block of each compose file;
the lead extends it to compare both services and to assert `UI_PORT` in both (8.2).

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
| `setup-tls.sh` (no option; `start-manager.sh` uses this) | **ensure**: creates the tls directory; if `mode` is absent or `self-signed` and the certificate is absent, unreadable, expired, expiring within 30 days, or lacks one of the certificate addresses of 3.2, one of the `UI_ALLOWED_HOSTS` names or one of the `tls/names` entries, a new self-signed certificate is made. **An address outside that set never triggers a regeneration** (a lab deploy adds bridges and veths; the certificate does not change, REVIEW R18). A `provided` certificate is never touched; its expiry is reported. |
| `setup-tls.sh --renew` | A new self-signed certificate now (new key, new fingerprint); refused while `mode` is `provided` unless `--self-signed` is also given. |
| `setup-tls.sh --cert PATH --key PATH` | **provided**: validates (3.4), copies both files into the tls directory, writes `mode=provided`. |
| `setup-tls.sh --self-signed` | Switches back from `provided` and generates. |
| `setup-tls.sh --name NAME` (repeatable) | Writes the given names and IP addresses, one per line, to `tls/names` (replacing its content; `--name ''` removes the file), then runs **ensure**, which regenerates a self-signed certificate when one of them is missing. Each value must pass `allowed_hosts.host_name()` or parse as an IP address; anything else is refused with the value quoted. For a `provided` certificate the file is recorded and reported by `tls.names` (6.2) but changes nothing. |
| `setup-tls.sh --show` | Prints subject, SANs, notAfter, mode, fingerprint and `primary: <name>` (the primary name of 3.2). Read-only; works as any account that can read `cert.pem`. |
| `setup-tls.sh --primary` | Prints the primary name of 3.2 alone, for `start-manager.sh` and `manager-recover-admin.sh` (7.1). Read-only, no root. |

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

**As built (S4, the lead's record after three verification rounds).** (1) A certificate that `setup-tls.sh`
did not make is never regenerated: when `cert.pem` exists and `tls/mode` is absent ("unregistered"), `ensure`
(and so `start-manager.sh`) keeps it when the pair can serve (`cert.pem` readable by openssl and free of a
`PRIVATE KEY` block, `key.pem` a regular file that matches it), prints that `setup-tls.sh` did not make it and how to
register it (`setup-tls.sh --cert PATH --key PATH`) or replace it (`setup-tls.sh --self-signed`), reports its
expiry (within 30 days and expired named), and does not recreate the manager for it; when the pair cannot serve,
`ensure` and `--prepare` fail and `start-manager.sh` stops before recreating. `--renew` refuses an unregistered pair;
`--show` prints `mode: none`; file modes are repaired to 3.3 without touching content, and a `cert.pem` holding a
private key is never widened. The health check's `tls.files` Next line for a missing mode names those two commands.
(2) `--name` refuses a scoped IPv6 address (`%zone`) with a sentence naming the value; a hand-written `tls/names` line
of that kind is skipped with a note on stderr and never reaches openssl. (3) A root-only read-only mode `setup_tls.py
digest` (SHA-256 over the length-prefixed content of `cert.pem` and `key.pem`) decides whether the manager is
recreated: a change of either file recreates it even behind the same leaf fingerprint (a corrected chain), and the
person is told which. (4) `--prepare` creates the tls directory (0755 root) when it is absent, because the lock lives
inside it; it still never generates. (5) `--primary` and `--fingerprint` print exactly one line on stdout; notes go to
stderr.

### 3.2 Names in the certificate

| SAN | Source | Why |
|---|---|---|
| `IP:` the **certificate addresses**: every global-scope IPv4 and IPv6 address of the default-route interface(s) | `ip -j route show default` (IPv4) and `ip -6 -j route show default` name the interfaces; `ip -j address show dev <if>` gives their addresses; only `scope: global` entries count. **Never** an address of `docker0`, `br-*`, `veth*`, `virbr*`, `cni*`, `clab*`, a `127.0.0.0/8`, `::1`, `169.254.0.0/16` or `fe80::/10` address, whatever interface it sits on. A VM with no default route falls back to the global-scope addresses of every interface whose name is not in that exclusion list. (REVIEW R18) | Students open the manager by the VM address (README.md:89; VM-CONNECTION.md:41). Every interface would put `docker0`, every containerlab management bridge and link-local addresses into the certificate, and a lab deploy would change the set and regenerate it with a new fingerprint for every student. |
| `IP:127.0.0.1`, `IP:::1`, `DNS:localhost` | fixed | The health check and the installer probe `127.0.0.1` or `[::1]` (install-manager.py:113-116; probes.py:103-109) and verify the host name. |
| `DNS:<hostname>` | `socket.gethostname()` | A single-label name passes `HostCheck` without configuration (allowed_hosts.py:59). |
| `DNS:` every name of `UI_ALLOWED_HOSTS` | `.env` (both `clab-backup-ui/.env` and `deploy/image.env` are read; union) | A name the operator listed is a name students will type. Parsed with `configured_hosts()` of `allowed_hosts.py:67-76`, imported from the checkout (pure module, no app import). |
| `DNS:` or `IP:` every entry of `tls/names` | `setup-tls.sh --name` (3.1) | The operator's own list for an address outside the default-route rule (a second uplink, a NAT address students use). |

The rule is one pure function `certificate_addresses(routes, addresses)` in `setup_tls.py`, fed the
parsed JSON of the three `ip -j` commands; `check_exposure.py` loads it with `module('setup_tls')` (the
`module()` loader of check_install.py:36-42) so that **ensure** and `tls.names` apply the same rule. The TUI's
`vm_addresses()` (`hostname -I`, installer_tui/app.py:1818-1826) is **removed** with its one caller, the
summary screen's *open the manager at* line (app.py:1753-1757; the plan lines never used it, they come from
`install.plan_lines`, app.py:787): `hostname -I` lists `docker0` and every containerlab bridge, exactly the
addresses the certificate never names, and a URL on one of them would add a name-mismatch warning to the
self-signed one. That line now prints `https://<primary>:<port>/` from `setup-tls.sh --primary` and the
certificate addresses (7.1).

The primary name (`CN`) is the first `UI_ALLOWED_HOSTS` name, else the first `tls/names` entry that is a name, else
the first IPv4 certificate address, else the host name. The SAN list is what matters; the `CN` is cosmetic.
`setup-tls.sh --primary` prints it (3.1).

A dynamic address of the default-route interface changes the list: **ensure** notices (3.1) and regenerates on the next
`start-manager.sh`; the health check warns in between (6, `tls.names`). A regenerated self-signed
certificate has a new fingerprint and every browser shows its warning again; that is stated in the
installer's output and in INSTALL.md (8.1). An address outside the rule (a new lab's bridge) changes nothing.

### 3.3 Files, owners, modes

| Path | Owner | Mode | Content |
|---|---|---|---|
| `/srv/containerlab-node-manager/tls/` | root:root | 0755 | directory; refused when a symlink (the `setup-vm.sh:6` rule) |
| `tls/cert.pem` | root:root | 0644 | PEM certificate; for `provided`, the full chain, leaf first |
| `tls/key.pem` | root:**10001** | 0640 | PEM private key, readable by the container's group (Dockerfile:11 creates gid 10001); not readable by the ordinary VM account |
| `tls/mode` | root:root | 0644 | one line: `self-signed` or `provided` |
| `tls/names` (optional) | root:root | 0644 | the operator's names and addresses, one per line (`setup-tls.sh --name`, 3.1); absent when none were given |

The health check's `FILE_PROBE` (check_install.py:389-406) already verifies owner, mode and regular
file for the helper files; `check_exposure.py` reuses it for these three files (and for `tls/names` when it exists) with the modes above
(the probe runs as root through `ctx.run(..., privileged=True)`, check_install.py:101-112, so the
0640 key is checked without reading it; the probe hashes only files up to 1 MiB and the report never
prints a hash of the key: the key's entry is passed with a flag that skips the digest).

The key never leaves the VM. `setup-tls.sh --show` prints the certificate's facts, never the key.
`setup_tls.py` never prints a key path's contents in an error message.

**As built (S4):** the directory also holds `tls/.lock` (root:root, 0600, empty, permanent): every writing mode
takes an exclusive `fcntl.flock` on it (opened with `O_NOFOLLOW`, never unlinked) from before its first read of the
directory until its files are installed; a second run waits up to 60 s and then refuses with a sentence that names
the lock; the read-only modes take no lock.

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

**As built (S4), rule 1 for symlinks:** a `--cert` or `--key` path is resolved with `realpath` over every
component. A path that is its own real path is used as is (a regular file of at most 64 KiB). A path whose real path
differs (a link as its last component, or a linked ancestor directory) is followed only when the real path lies under
`/etc/letsencrypt/archive/`, the last component (the link or the file) is owned by root, its directory is owned by root
and writable by root alone, and the target is a regular file owned by root: certbot's `live/NAME/*.pem` layout and
nothing else. Any other link, including a root-owned link in a root-owned directory to a root-owned key outside the
archive (an SSH host key), is refused before anything is read into the tls directory, with the real path named; a
dangling link is refused as such. The copied files are regular files with the modes of 3.3.

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

`app/redirect.py` (new, about 60 lines, stdlib plus `uvicorn`, `app.allowed_hosts` and `app.headers`;
it never imports `app.main`, `app.store` or any service). Every response it sends carries the headers of
`app.headers.security_headers(scope, status=<code>, refusal=True)` (DESIGN.md 16.3; over plain HTTP the
function adds no HSTS) encoded into the ASGI header list, plus `Content-Length: 0`, and an empty body;
`allowed_hosts.HEADERS` is not used, because it carries the `Content-Length` and `Content-Type` of
`HostCheck`'s refusal body (allowed_hosts.py:31-33) and would contradict an empty body:

1. Reads the four variables. `UI_HTTP_PORT=0` prints `HTTP redirect disabled` and waits for SIGTERM
   without binding anything (a `threading.Event().wait()`): the container stays *running* and
   `restart: unless-stopped` has nothing to restart. (A process that exits 0 under `unless-stopped`
   restarts in a loop; a process under `on-failure` is not restarted after a VM reboot when uvicorn's
   graceful SIGTERM exit was 0. Waiting is the only shape that is quiet in both cases.)
2. Otherwise `uvicorn.run(app, host=UI_BIND, port=UI_HTTP_PORT, server_header=False, proxy_headers=False, workers=1)`.
3. `app` is a pure ASGI callable. For an `http` scope it takes the single `Host` header; when
   `host_allowed(host, configured_hosts(UI_ALLOWED_HOSTS))` (allowed_hosts.py:62-64) is false, or the
   header is missing or repeated, it answers `400` with the headers of
   `security_headers(scope, status=400, refusal=True)` plus `Content-Length: 0` and an empty body. **A
   `raw_path` that does not start with `b'/'` answers the
   same `400`** (REVIEW R20, the reviewer's second pass): h11 accepts a request target that is not
   origin-form, and uvicorn splits it at the first `?` and passes the rest unchanged (uvicorn 0.54.0
   h11_impl.py:204-218), so an absolute-form target, `*` or `@evil.example/` would otherwise become
   `Location: https://host:8443@evil.example/`, the userinfo form that points at another host. Browsers send
   origin-form targets only, so a victim's browser cannot be made to send one; the listener refuses it
   anyway. (REVIEW R19's sentence names this refusal: *400 for a refused Host or a request target that is
   not a path*.) The checks run in that order: Host, target form, then method. Otherwise it answers `301`
   with `Location: https://<host_name(host)>:<UI_PORT><raw_path>[?<query_string>]` and the headers of
   `security_headers(scope, status=301, refusal=True)` plus `Content-Length: 0`. **`Location` is built
   from `scope['raw_path']` and `scope['query_string']`, both
   bytes, unchanged** (REVIEW R20): never from the decoded `scope['path']`, so `%0d%0a` stays `%0d%0a`
   (a decoded CR/LF is a header h11 refuses), `%3F` stays `%3F` (decoded it would move the query), and a
   UTF-8 path travels as the percent-encoded bytes the browser sent; `?` and the query are appended only
   when `query_string` is non-empty. The name is the browser's own `Host` without its port, exactly as
   `HostCheck` would accept it, so the redirect never sends a browser to a name the manager would
   refuse. The port is omitted when `UI_PORT` is 443. Methods other than `GET` and `HEAD` answer
   `405` (the headers of `security_headers(scope, status=405, refusal=True)`, `Allow: GET, HEAD`,
   `Content-Length: 0`, empty body). A `websocket` scope is closed with 1008
   before accept. `lifespan` passes. The fragment never reaches the server; the browser carries a
   bookmark's `#lab=…` over the 301 itself (9, interface 4).
4. Nothing is logged per request (an exposed port must not fill the disk with scanner lines); uvicorn's
   access log is off (`access_log=False`).

The one sentence that describes it everywhere (REVIEW R19; CLAUDE.md, ARCHITECTURE.md, the handoff
section and INSTALL.md use it verbatim):

> `app/redirect.py` is the one listener outside the gate and the guard: it holds no data and answers 301
> to the manager's own HTTPS origin after `host_allowed`, 400 for a refused Host or a request target that
> is not a path, 405 for any method but GET and HEAD, closes a socket 1008, and nothing else.

What the redirect cannot do (REVIEW R17): HSTS applies to every port of a host name (RFC 6797 §8.3). With
a **provided** certificate on a name, a browser that once opened `https://<name>:8443` rewrites
`http://<name>:8081` to `https://<name>:8081` before any request leaves it, and the plain-HTTP listener
is never reached by that name for 180 days. The redirect still works by IP address (HSTS is never
stored for an IP literal) and for a browser that has not yet visited the HTTPS origin; INSTALL.md says
so (8.1), the health check says so in provided mode (`tls.hsts-scope`, 6.2), and the upgrade table
names it (7.4). Under a self-signed certificate nothing is stored and the redirect works by name too.

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

**As built (S3, the lead's record after three verification rounds).** `app/redirect.py` runs uvicorn with
`http=DeadlineH11Protocol` (h11 with a 10 s per-connection deadline: a connection that has not sent its request
within 10 s is aborted), `server_header=False`, `proxy_headers=False`, `workers=1`, `access_log=False` and
`log_level='error'`. At start it caps the soft descriptor limit at `NOFILE_CEILING = 4096` (raised to it, or lowered to
it when it starts higher), so held connections bound the listener's memory (about 57 MB at the measured 13.7 kB a
connection), and asyncio's own error lines are throttled to one a minute. Every answer the listener itself makes has an
empty body, `security_headers(scope, status=<code>, refusal=True)` and `Content-Length: 0`; answers that uvicorn, h11
or the websockets library make before the app is called (a malformed request line) keep their own short form. The
redirect service in both compose files carries `mem_limit: 128m` and a bounded `json-file` log driver.

### 4.2 HSTS

| Rule | Value |
|---|---|
| Header | `Strict-Transport-Security: max-age=15552000` (180 days) |
| Sent when | `scheme(scope) == 'https'` (DESIGN.md 5.6 item 1), on every response of the manager: pages, `/api/`, static files, the gate's and `HostCheck`'s refusals. It belongs in the one `security_headers()` of `app/headers.py` that RECONCILIATION Dq 5 creates. |
| Not sent | over plain HTTP (the redirect listener never sends it; a browser ignores it there anyway, RFC 6797 §8.1). |
| `includeSubDomains` | no: the manager owns one name, and a lab's other services may live under it. |
| `preload` | no: preloading is irreversible for a name the operator may reuse. |
| Self-signed | A browser stores HSTS only from a connection without certificate errors (RFC 6797 §8.1), so a self-signed installation sends the header and the browser discards it. The header is still sent, so a later switch to a provided certificate needs no manager change. |
| Trusted certificate | After the first visit the browser refuses plain HTTP for 180 days and refuses to click through a later certificate error. That is the point, and it is the lockout case 10.4. |
| **Every port of the name** (REVIEW R17) | HSTS is stored per host name, not per port (RFC 6797 §8.3). With a provided certificate on `<name>`, the browser upgrades `http://<name>:8081` (the redirect listener, 4.1) **and** `http://<name>:<any port>` (a plain-HTTP lab service the operator exposes on that name) to `https://` for 180 days. Both are reached by IP address instead, or before the first HTTPS visit. Stated in 4.1, in the upgrade table (7.4), in INSTALL.md (8.1) and by the health check (`tls.hsts-scope`, 6.2). Not a reason to drop the header: an IP-literal installation (the common classroom case) stores nothing, and a named installation wants exactly this protection for the manager. |

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

### 6.1 Changes in `check_install.py`: one HTTP question, every other fact from a probe

The gate (DESIGN.md 6) puts every route the health check used to read behind a session, and the
checker holds no credential (RECONCILIATION E 9.5; REVIEW R16 narrows the earlier ruling E-Q2). The
rule, binding for the health-check builder (S6) and the probe builder (S3):

1. **`GET /api/health` is the only HTTP request `check_install.py` and `check_exposure.py` send to the
   manager.** `Context.http` is given no other path; `Context.head` is given exactly three (path, base)
   pairs: `/api/health` over TLS with the pinned certificate (`tls.listener`, `http.hsts`), `/` on
   `http://127.0.0.1:<UI_HTTP_PORT>` (the redirect port, `http.redirect`) and `/` on
   `http://127.0.0.1:<UI_PORT>` (plain HTTP on the TLS port, which must fail to connect or to parse:
   `http.redirect`'s FAIL case, 6.2). Tests pin both sets (6.3: case 1 of `test_check_exposure.py` for
   `ctx.head`, case 9 of `test_check_install.py` for `ctx.http`).
2. **Every other manager fact comes from `docker exec <container> python -m app.probe <name> [arg]`**,
   run privileged by `ctx.run` exactly as `STORAGE_PROBE` is (check_install.py:331), with `timeout=30`,
   parsed with `parse_json` (216-222). A probe never constructs a `Store` (constructing one writes
   state; a second process against live data is forbidden, CLAUDE.md), never writes under `/data`,
   never logs, never prints a password, a key, a hash, the setup code, a session id or a cookie
   value, and never makes an HTTP request to the manager. A probe that needs the saved state
   **decrypts `state.enc` read-only in the `STORAGE_PROBE` pattern** (check_install.py:299-313:
   `Fernet(key).decrypt(data)` on at most 64 MiB, the result held in the probe's own memory and
   discarded; REVIEW R16 allows exactly this).
3. The end-to-end checks that used the manager's routes (`http-browse`, `git-http`) become probes that
   run **the manager's own clients read-only** from that state: `lab_operations.remote()`
   (lab_operations.py:142-199, the helper's `browse` mode, the one the route sends at
   device_diagnostics.py:438) and `git_progress.remote_git()` (git_progress.py:639-686, mode `list`,
   what `GitProgress.repositories()` sends at git_progress.py:956). Both are module-level functions that
   take the `host` record and a request and know no `Store`. The probe therefore uses the saved VM
   password the way the manager does, from a separate process on the same data, and prints nothing of it
   (10.19).
4. **No check is dropped silently.** A check whose fact cannot be read answers `SKIP` with the reason
   (the list below), never `PASS`, and every matching `test_check_install.py` case is rewritten, never
   deleted (6.3).

**The changes, place by place:**

| Place | Change |
|---|---|
| `Context.http` (160-202) | The opener gains `HTTPSHandler(context=ctx.tls_context)`, where `tls_context = ssl.create_default_context(cafile=<tls dir>/cert.pem)` with `check_hostname = False`: the request **pins the installed certificate** (so a `PASS` proves the listener serves exactly that file) and the name check is a separate finding (`tls.names`). The context is built once, before `check_docker`'s request. When `cert.pem` is unreadable, `tls_context` is `None`: `http` answers `SKIP` (today's `FAIL` at 287 and 291 becomes a skip, because the cause is the file, which `tls.files` reports as `FAIL`) with *The installed certificate could not be read, so the manager was not asked over HTTPS.* and the `tls.files` fix, no request is sent, `ctx.base_url` stays empty so `tls.listener` and `http.hsts` skip the same way, `manager-version` is unaffected (proved by `docker exec`, 277-281) and the probe checks run regardless (they guard on `ctx.container`). The only path it is ever given is `/api/health`. |
| `Context.head(path, base=None)` (new) | `GET` with `NoRedirect` (31-33) returning `(status, headers)` with no body parsing, for the redirect and HSTS checks. Mockable like `http`. |
| `Context.probe(name, *args)` (new) | `parse_json(self.run([*docker, 'exec', self.container, 'python', '-m', 'app.probe', name, *args], privileged=True, timeout=30))`, plus the one distinction the callers need: it returns `(value, missing)` where `missing` is true when the exec failed with `No module named app.probe` on stderr (an older image still running during an upgrade). Every probe call goes through it, so a test routes on `name`. |
| `check_docker` 284-295 | `health_url()` now yields `https://…/api/health`; the check expects `{"ready": true}` (DESIGN.md 6.7). The version was already proved through `docker exec` at 277-281, so nothing is lost. Title stays *Manager HTTP*; detail says *TLS, pinned certificate*. `ctx.base_url` is kept for `tls.listener` and `http.hsts`. |
| `check_design_engine` (316-327) | `ctx.probe('design-engine')`; the same PASS/WARN/FAIL sentences as today; `missing` → `SKIP` (below). |
| `check_manager_routes` (488-578) | Guard on `ctx.container` instead of `ctx.base_url`. `/api/discovery` → `ctx.probe('vm-connection')` (`configured`, `host`, `connected` as today, `ctx.host` set from it); **the presence test at 501 reads `host.get('fingerprint_saved') is True`** in place of `bool(host.get('fingerprint'))`, because the probe prints the flag and never the value (a literal port would answer `WARN` on every healthy VM and skip `http-browse` and `git-http` with it); `/api/operations/browse {path}` → `ctx.probe('browse', path)` per folder, the same queue, the same `folder-N` and `folder-budget` rows, the same 500-entry WARN. The `vm-target` address comparison keeps using `ip -j address` (510-513): that one is about this VM, not the certificate. |
| `check_git_route` (581-597) | Guard on `ctx.container`, `ctx.host.get('enabled')` and **`ctx.host.get('fingerprint_saved')`** (582 reads the flag, as 501 does); `/api/git/repositories` → `ctx.probe('git-registry')`; the protocol and version comparison and the `require_git` severities stay; the detail adds *… ; N lab(s) connected to a repository* from `bound_labs`. |
| `check_capture` (600-630) | Guard on `ctx.container`; the three routes → one `ctx.probe('capture')`; `enabled` false → the same WARN, `targets` null → the same FAIL with the probe's `diagnostic` (scrubbed by the probe), `ready` not true → the same FAIL, else PASS with the count; the manual Wireshark line stays. |
| `Context.manual[0]` (81-84) | *open the manager at `https://<VM address>:8443` …* and *accept or verify the self-signed certificate by its fingerprint*. |

**Every manager HTTP call of `check_install.py` today and its new source** (the installer's two calls are
listed for completeness; `check_git.py` and `check_host.py` make none):

| Today (file:line) | Route | New source | Check id(s) |
|---|---|---|---|
| check_install.py:289 | `GET /api/state` (version) | `GET /api/health` over TLS with the pinned certificate, expecting `{"ready": true}`; the version stays proved by `docker exec … python -c 'from app import __version__; print(__version__)'` (277-281) | `http`, `manager-version` |
| check_install.py:318 | `GET /api/design/engine` | probe `design-engine` | `design-engine` |
| check_install.py:492 | `GET /api/discovery` | probe `vm-connection` | `vm-connection`, `vm-target`, `vm-mode`, `discovery-status` |
| check_install.py:530, 557 | `POST /api/operations/browse {path}` | probe `browse <path>` (one call per folder, `''` for the trusted roots) | `http-browse`, `folder-N`, `folder-limit-N`, `folder-budget`, `folders` |
| check_install.py:589 | `GET /api/git/repositories` | probe `git-registry` | `git-http` |
| check_install.py:606, 616, 618 | `GET /api/capture/status`, `GET /api/capture/targets`, `GET /api/capture/health` | probe `capture` (one call) | `capture` |
| install-manager.py:118-152 (`check_manager`) | `GET /api/state` | `GET /api/health` with the pinned `cert.pem`; version by `compose exec` (125-128, unchanged) | the installer's verification (7.1) |
| installer_tui/probes.py:112-119 (`http_version`) | `GET /api/state` | `http_ready(url, cafile)` on `/api/health`; version by `sudo -n docker exec` (7.1) | the TUI dashboard |

**The probe contract** (`clab-backup-ui/app/probe.py`, slice S3). `python -m app.probe <name> [arg]` prints
**exactly one line of JSON** on stdout and nothing on stderr unless it crashes; exit 0 when the line is an
answer, 1 when the line is `{"error": "<sentence>"}`, 2 for an unknown name or a bad argument (usage on
stderr, no JSON). Every string value is at most 600 characters. Field order is as written; a field is
never omitted.

| Name | Reads | Never | Prints (one line) |
|---|---|---|---|
| `design-engine` | `design_engine.engine_status()` (design_engine.py:72-88): the `netlab` binary on `PATH` and the `networklab` distribution metadata, without starting a process | the state, the network | `{"available": <bool>, "version": "<x.y>" or "", "path": "<path>" or "", "diagnostic": "<sentence>" or ""}`, the same JSON `GET /api/design/engine` prints (network_design.py:569-571) |
| `capture` | the environment (`CAPTURE_PROVIDER`, `CAPTURE_EDGESHARK_URL`, `CAPTURE_SESSION_URL`, `CAPTURE_SESSION_TOKEN`, through `capture.configured_provider()` and `capture_sessions.BrowserSessions`, capture.py:175-184, capture_sessions.py:150-155); then two loopback services: Edgeshark discovery (`EdgesharkProvider.discover()`, capture.py:160-164, the 8 s and 4 MiB limits of `read_discovery`) and the session service's `GET health` (`BrowserSessions.request('GET','health')`, what `/api/capture/health` returns, capture_sessions.py:196-198) | the state (the lab names of `/api/capture/targets` need it; the count does not: a fact that would need lab state is dropped, E-Q2); the token or any URL in its output | `{"enabled": <bool>, "provider": "edgeshark" or "disabled", "message": "<the status route's sentence>", "targets": <int> or null, "ready": <bool> or null, "diagnostic": "<CaptureError sentence>" or ""}`. `targets` is `len(merge_shared_namespaces(provider.discover()))` (capture.py:134-152), null when discovery raised (`diagnostic` carries the `CaptureError` sentence, which names no URL by construction, capture.py:80); `ready` is the service's `ready` field, null when the service could not be asked. When `enabled` is false, `targets` and `ready` are null and `message` is the status route's disabled sentence or the `CaptureError` of the configuration. |
| `vm-connection` | `state.key` and `state.enc` read-only (the `STORAGE_PROBE` pattern); from the state, `host` and `discovery`; `discovery.discovery_fresh(state)` (discovery.py:193-197, a pure function) | the password, `bootstrap_*`, the labs; any write | `{"configured": <bool>, "connected": <bool>, "host": {"address": "<str>", "port": <int>, "username": "<str>", "auth": "<str>", "command_mode": "<str>", "enabled": <bool>, "fingerprint_saved": <bool>} or null, "checked_at": "<iso>" or null}`. `configured` is `bool(state.get('host'))` as `Discovery.public()` computes it (discovery.py:622); `fingerprint_saved` is `bool(host.get('fingerprint'))`: the check needs presence only, so the value is not printed. |
| `browse <path>` | the state as above (host record only); then `lab_operations.remote(host, {'mode': 'browse', 'path': <path>}, timeout=25)` (lab_operations.py:142), the request the route sends (device_diagnostics.py:438) | any other helper mode; the lab files mode; a write | `{"path": "<path>", "entries": [{"name": "<str>", "path": "<str>", "directory": <bool>}, …]}` with at most the helper's 500 entries, or `{"error": "<sentence>"}`. The argument must be `''` or an absolute path without `..` and control characters (the `valid_path` rule of check_install.py:672-674); the helper enforces the trusted roots itself. The error sentence is the `ValueError` the manager would show, passed through `lab_operations.scrub(text, state)` (lab_operations.py:318) before printing; any other exception prints the fixed `UNREACHABLE_SENTENCE` of device_diagnostics.py:35. |
| `git-registry` | the state as above (host record and, for the count, each lab's `git_binding`); then `git_progress.remote_git(host, {'mode': 'list'})` (git_progress.py:639) | a binding id, a revision, any mode but `list`; a write | `{"protocol": "<str>", "version": "<str>", "repositories": <int>, "bound_labs": <int>}` (the helper's `protocol` and `version` as it printed them, the length of its `repositories` list, the number of labs whose `git_binding` is set), or `{"error": "<sentence>"}` scrubbed as above. The registrations' `owner`, `path` and `push_url` are not printed: the check counts them (check_install.py:593) and `check_git.py` reads the root-owned registry itself. **REVIEW R16's *list of Git bindings* is served as the `bound_labs` count, deliberately:** no check consumes the list itself, and a lab's binding (`repository`, `folder`, `url`) would be printed only to be counted. |

Three probes share the state reader: `probe.read_state()` returns the decrypted document or raises
`ProbeError` with one of the fixed sentences *state unreadable* (missing or undecryptable files, more
than 64 MiB) or *reset pending* (`<DATA_DIR>/.reset-pending` exists, store.py:53-54: the manager may be
moving the files aside); the probe then prints `{"error": "<sentence>"}` and exits 1. `probe.py` imports
`lab_operations`, `git_progress`, `discovery` and `capture` as modules (their module-level functions
only) and never calls `create_app`, `Store()` or any class that takes a `Store`.

**Every check that answers SKIP, with its reason** (the detail sentence; the fix line where one exists):

| Check | SKIP when | Detail |
|---|---|---|
| `manager`, and with it every check of this group | Docker could not be queried (244) | unchanged: *Docker access is required for these checks.* |
| `privilege-skip-N` | the group runs without administrator access (770-773) | unchanged |
| `http`, `tls.listener`, `http.hsts` | `cert.pem` unreadable, so no pinned `tls_context` (the `Context.http` row above) | `http`: *The installed certificate could not be read, so the manager was not asked over HTTPS.*; the other two: *The installed certificate could not be read, so the TLS listener was not probed.*; fix for all three: `sudo bash …/deploy/setup-tls.sh` (the `tls.files` fix) |
| `design-engine`, `vm-connection`, `capture`, `http-browse`, `git-http` | `ctx.probe()` reports `missing` (the running image predates the probe) | *The running manager predates this check's probe; rebuild it.*; fix: `sudo bash …/deploy/start-manager.sh` |
| `vm-connection`, `http-browse` | the probe answered `{"error": "state unreadable"}` or `{"error": "reset pending"}` | *The saved state could not be read without the manager (<sentence>); the manager's own page runs this check.*; fix: *Open Manager ▾ › Diagnostics, which runs the same check.* (`POST /api/debug/probe` runs the helper's `browse` and `capabilities` modes over the saved connection, diagnostics.py:147-154; `storage` already says why when the files are the cause) |
| `git-http` | the same two answers | *The saved state could not be read without the manager (<sentence>); a lab's save drawer lists the registry.*; fix: *Open a lab's Save ▾ drawer: its folder chooser lists the repositories through the same request.* (`GET /api/git/repositories`, save-drawers.js:436). Diagnostics is **not** named here: it never lists the Git registry (diagnostics.py counts `git_jobs` at 99 and asks the Git helper nothing) |
| `vm-connection`, `http-browse`, `git-http`, `capture`, `design-engine` | no container (`ctx.container` empty; the guard that was `ctx.base_url` at 490, 583, 604) | the sentences of 490 and 604 with *HTTP* replaced, since the guard is the container now: *Manager container unavailable; saved-connection tests could not run.*, *Manager container unavailable; the capture provider could not be queried.*; 583 stays *A working manager and saved VM connection are required.*; `design-engine`: *Manager container unavailable; the design engine could not be queried.* |
| `http-browse` | the VM connection is not configured (505), or the operations helper files are untrusted (527, `INFO` with `--discovery-only`) | unchanged |
| `git-http` | no saved connection (583); the Git helper files are untrusted (586, `INFO` unless `--require-git`) | unchanged |
| `git.repo.N.remote` | `check_git.py:177` | unchanged |
| `deadline`, `interrupted` | check_install.py:766, 778 | unchanged |

A probe that answers `{"error": …}` for a reason other than the two state sentences (the helper refused,
the VM did not answer) is a `FAIL` with that sentence, exactly as the failed HTTP request was today
(check_install.py:494, 541, 595, 627): a reachable manager whose VM path is broken is a finding, not a skip.

**As built (S3).** Every probe runs under an overall deadline of 25 s (`SIGALRM`); when it fires the probe prints
`{"error": "The probe did not finish within 25 seconds."}` with exit 1, which the health check reports as a FAIL with
that sentence, and a hard exit follows about 3 s later (`GRACE`), inside the checker's 30 s `docker exec` timeout. The
deadline runs between Python bytecodes, so a blocking C call (DNS resolution of an unreachable VM name) can delay it up
to the hard exit. `browse` passes a helper's own error line through `lab_operations.scrub(text, state)` (lines that
carry `from_helper`) and in the manager's own sentences replaces only the stored secrets; `git-registry` lets the
fixed `PROBLEM_CODES` sentences and the VM-password setup sentence through as they are and scrubs everything else, as
`GitProgress.invoke` does. A probe never imports `app.main` or `app.store`, never constructs a `Store`, `Captures` or
`GitProgress`, sets `sys.dont_write_bytecode`, turns logging off while it runs, and prints any unexpected failure as
`{"error": "The probe failed unexpectedly."}`, never a traceback.

### 6.2 The checks

| id | PASS | WARN | FAIL | fix (a `Next:` line) |
|---|---|---|---|---|
| `tls.files` | directory, `cert.pem`, `key.pem`, `mode` present with the owners and modes of 3.3 (`names`, when present, root:root 0644) | — | anything missing, a symlink, a wider mode, a world-readable key | `sudo bash …/deploy/setup-tls.sh` |
| `tls.cert` | not expired, more than 30 days left; detail prints notAfter, mode and the fingerprint (from `openssl x509 -noout -enddate -fingerprint -sha256 -in cert.pem`, run unprivileged, the file is 0644) | fewer than 30 days left | expired, or `openssl` cannot parse it | `setup-tls.sh --renew` (self-signed) or `setup-tls.sh --cert … --key …` (provided) |
| `tls.hsts-scope` | — (emitted only in `provided` mode, right after `tls.cert`, as `INFO`: *With a trusted certificate, browsers that opened `https://<name>` apply HSTS to every port of that name for 180 days: `http://<name>:<UI_HTTP_PORT>` and plain-HTTP lab services on that name are opened by IP address or before the first HTTPS visit.* REVIEW R17) | — | — | — |
| `tls.names` | every certificate address of 3.2 (`certificate_addresses()` of `setup_tls.py` on `ip -j route show default`, `ip -6 -j route show default` and `ip -j address`), every `UI_ALLOWED_HOSTS` name and every `tls/names` entry is a SAN; an address of `docker0`, a `br-*`, `veth*`, `virbr*`, `cni*` or `clab*` interface, or a link-local address, is **never** required and never named (REVIEW R18) | a certificate address or a listed name is missing from the SANs; detail names them | — | `setup-tls.sh` (ensure regenerates a self-signed one) or a new provided certificate |
| `tls.bind` | the container command (`check_docker` already inspects `.Config.Cmd`, 260-262) carries `--ssl-certfile`, `--ssl-keyfile` and `--no-proxy-headers`; detail prints the bind and the port | `--no-proxy-headers` missing (an older compose file) | no `--ssl-certfile`: the manager serves plain HTTP | `sudo bash …/deploy/start-manager.sh` (rebuilds from the current compose file) |
| `tls.listener` | `ctx.head('/api/health')` over HTTPS with the pinned certificate answers 200 | — | handshake fails against the pinned certificate (the listener serves another certificate), or no answer | `setup-tls.sh --show` then `recreate-manager.sh` |
| `http.redirect` | `ctx.head('/', base='http://127.0.0.1:<UI_HTTP_PORT>')` answers 301 with `Location` = `https://127.0.0.1:<UI_PORT>/` | `UI_HTTP_PORT` ≠ 0 and the redirect container is not running (`compose ps --status running --quiet http-redirect` empty), or it answers something other than 301 | **plain HTTP serves a page**: any 200 from the redirect port, or a 200 over plain HTTP from the TLS port's address (the check also calls `ctx.head('/', base='http://127.0.0.1:<UI_PORT>')`, the third pair of 6.1 rule 1, and expects a connection or protocol error) | `start-manager.sh`; when `UI_HTTP_PORT=0` the check is `INFO HTTP redirect disabled` |
| `http.hsts` | the HTTPS `/api/health` response carries `strict-transport-security` with `max-age=15552000` | header absent or another value (an older image) | — | `start-manager.sh` (rebuild) |
| `firewall` | `ufw status verbose` (privileged) says `Status: active`, default `deny (incoming)`, and the SSH port, `UI_PORT` and `UI_HTTP_PORT` (when ≠ 0) are allowed | ufw inactive, or a needed port not allowed (the detail names it) | `ufw` not installed | `sudo bash …/deploy/setup-firewall.sh`; a cloud security group is accepted as the reason to ignore the WARN, said in the detail |
| `exposure.listeners` | every listening TCP socket (`ss -Hltn`, privileged for process names `-p`) that is not loopback is one of: the SSH port, `UI_PORT`, `UI_HTTP_PORT`; detail lists them with the process name | any other non-loopback listener; detail names port and process | `5001` or `5801` (the capture stack) not loopback-only | *Close or firewall the listed port; the capture stack must stay on 127.0.0.1 (`deploy/compose.capture.yml`).* |
| `exposure.ports` | no running container publishes a port on `0.0.0.0` or `[::]` (`docker ps --format '{{.Names}}\t{{.Ports}}'`, privileged; the capture stack's `127.0.0.1:` bindings pass) | a container does; detail names container and port (a lab node with `ports:` in its topology) | — | *Remove `ports:` from the topology or bind them to 127.0.0.1; Docker-published ports bypass ufw.* |
| `signon.bootstrap` | `/srv/containerlab-node-manager/data/setup-code` absent (`test -e`, privileged, as 662-664) | present with `mode=setup`: **Setup not completed: no administrator exists** (D3 point 2); or `mode=recover` and the file's mtime (`stat -c %Y`, privileged) younger than 15 minutes: *A recovery is open (it closes 15 minutes after the recovery command ran)*; or `mode=recover` and the mtime 15 minutes or older: *A recovery code expired unused; the manager removes it at the next /setup request.* (DESIGN.md 9.5: the manager deletes an expired file only when `/setup` or `/api/setup` is next requested, and `read_setup_code` treats it as absent, DESIGN.md 16.1) | — | `mode=setup`: *Open `https://<address>:<port>/setup` and enter the code from `sudo cat /srv/containerlab-node-manager/data/setup-code`.*; `mode=recover`, open: *Open `https://<address>:<port>/setup?recover=1` with the code the recovery command printed, or run `sudo bash …/deploy/manager-recover-admin.sh` again.* (REVIEW R11); `mode=recover`, expired: *Run `sudo bash …/deploy/manager-recover-admin.sh` again and open the URL it prints within 15 minutes.* **The report never prints the code** (HEALTH-CHECK.md "Save a support report": reports are shared). The privileged reads are `head -c 16` of the first line only (`mode=…`) and `stat -c %Y`; the age is `time.time()` minus that mtime, with the same 15-minute limit as `read_setup_code`. |
| `ssh.hardening` | `sshd -T` (privileged, 100-101) shows `permitrootlogin no`, `maxauthtries ≤ 4`, `logingracetime ≤ 30` | any of them at the OpenSSH default; detail names which | — | `sudo bash …/deploy/setup-ssh-hardening.sh` |
| `ssh.bruteforce` | `systemctl is-active fail2ban` succeeds | not active or not installed; detail: *recommended on an Internet-facing VM; see INSTALL.md* | — | `sudo apt-get install -y fail2ban` (documented, not scripted) |

Semantics: `FAIL` makes the overall result *FAILURES FOUND* (summarize, 677-682) and is reserved for a
state where the manager is unsafe or unreachable; `WARN` is a door that is open or a limit that is
near; `INFO` is a fact. The checks never change anything, never read the key, and never print a code.
The `tls.*` and `http.*` checks run before the probes of 6.1 are needed; a group that cannot reach
Docker answers `SKIP` as the manager group does (6.1, the SKIP table).

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

1. A healthy VM: every id `PASS` except `ssh.bruteforce` as the test chooses; `ctx.head` was given exactly
   the three (path, base) pairs of 6.1 rule 1 and `ctx.http` nothing (the exposure group asks no HTTP
   question of its own).
2. An expired certificate → `tls.cert FAIL`; 20 days left → `WARN`; the fingerprint appears in the
   detail exactly as `openssl` printed it.
3. A new address of the default-route interface not in the SANs → `tls.names WARN` naming the address;
   the same fixture with a new `docker0`, `br-…`, `veth…`, `virbr0`, `cni0` or `fe80::` address and an unchanged
   uplink → `PASS`, and no such address appears in the report (REVIEW R18). The fixture is one `ip -j
   address` document with all of those interfaces and one `ip -j route show default` document; the same
   fixture feeds `test_setup_tls.py` (8.2).
4. The redirect port answering `200` → `http.redirect FAIL`; `UI_HTTP_PORT=0` → `INFO`.
5. `setup-code` present with `mode=setup` and a body `PRIVATE` → `signon.bootstrap WARN` and the
   sentinel `PRIVATE` (test_check_install.py:21) does not appear anywhere in the report; `mode=recover`
   with a `stat -c %Y` answer 5 minutes old → `WARN` *A recovery is open* whose fix names `?recover=1`
   and the recovery script; the same file with a `stat -c %Y` answer 16 minutes old → `WARN` *A recovery
   code expired unused* whose fix names the recovery script and not `?recover=1` (the page would answer
   404, DESIGN.md 9.5); in both the body stays absent from the report.
6. `tls.files` with a 0644 key → `FAIL`; the report contains no key material (the fake probe returns a
   `PRIVATE` sha256 for the key and the test asserts it is absent).
7. No `docker` answer → the group's checks `SKIP` with the Docker fix, never `PASS`.
8. `mode=provided` → `tls.hsts-scope INFO` present; `mode=self-signed` → absent (REVIEW R17).

In `tests/test_check_install.py` (slice S6; every case keeps its behavioural claim, REVIEW R16):

9. `test_empty_trusted_folder_is_healthy_and_only_read_routes_are_called` (157-179) becomes *only read
   probes are run*: the allowed set is the probe names `vm-connection`, `browse`, `git-registry` (routed on
   `ctx.probe`'s `name`, or on the `app.probe` argument of `ctx.run`), a `browse` call carries exactly one
   path argument and the others none, and **`ctx.http` is never called with a path other than
   `/api/health` by any check** (the one HTTP question, 6.1 rule 1). The three unit tests of the opener
   itself, `test_http_errors_and_malformed_json_discard_private_bodies` (490),
   `test_http_response_size_and_report_deadline_are_bounded` (507) and
   `test_http_open_and_body_share_one_absolute_deadline` (703), call `Context.http` directly against a
   fake opener and keep their paths: they test the method, not a check.
10. Every other case that drives these checks through `ctx.http` mocks `ctx.probe` instead (routed on
    the probe name, the way `browse_router` routes on the path today) and keeps its claim; none is
    deleted (REVIEW R16):
    - the fixtures: `browse_router` (54-72) becomes `probe_router(folders, discovery_value, engine_value)`,
      keyed on `name` (`vm-connection`; `browse` with its one path argument; `git-registry`;
      `design-engine`) and answering `(value, False)`; `discovery()` (48-51) carries
      `'fingerprint_saved': True` in place of `'fingerprint': 'public-host-fingerprint'`;
    - `test_an_available_engine_passes_with_its_version` (80) and
      `test_a_missing_engine_warns_with_the_managers_diagnostic_and_keeps_the_rest` (87): the engine JSON
      comes from the `design-engine` probe; the second's *manager HTTP unavailable* branch (93) becomes a
      probe `{"error": …}` and still answers `WARN` with *Every other feature keeps working*;
    - `test_successful_root_browse_does_not_mask_failed_child_folder` (146),
      `test_folder_budget_prioritizes_explicit_problem_path_and_reports_remaining` (343),
      `test_folder_traversal_does_not_follow_malformed_or_nonchild_paths` (352) and
      `test_wrong_folder_response_path_fails_instead_of_claiming_listed` (363): the browsed paths are read
      from the `browse` probe calls' argument instead of `call.args[1]['path']`; the asserted sequences
      (`['', problem]`, `['', ROOT]`) and statuses are unchanged;
    - `test_missing_vm_setup_warns_and_skips_live_operations` (172): exactly one probe call,
      `vm-connection`;
    - `test_git_route_is_checked_even_when_operations_are_unavailable` (181): the probe sequence is
      `['vm-connection', 'git-registry']`;
    - `test_git_route_protocol_and_version_are_required` (191): the three payloads are `git-registry`
      answers (`repositories: PRIVATE` is not an `int` and fails as the non-list did); `PRIVATE` stays
      absent from the report;
    - `test_untrusted_helper_cannot_be_executed_or_reached_over_http` (294): **no probe is run** when the
      Git helper is untrusted (`ctx.probe.assert_not_called()` beside the existing
      `ctx.run.assert_not_called()`), and `git-http` is `SKIP`;
    - `test_manager_unavailable_does_not_report_connection_success` (335): sets `ctx.container = ''` (the
      guard moved from `ctx.base_url`), asserts `vm-connection` `SKIP` and that no probe ran;
    - `test_capture_check_reports_disabled_enabled_and_failed_provider` (203): the disabled, enabled,
      failed-discovery and not-ready states come from one `capture` probe answer each; the `PRIVATE`
      message stays absent; the *manager unavailable* branch (236-239) sets `ctx.container = ''` and
      asserts no probe;
    - `test_running_source_mismatch_and_stopped_or_missing_manager` (415): `ctx.http` returns
      `{'ready': True, 'private': PRIVATE}`; `http` is still not called for `missing`, `stopped` and
      `invalid-metadata`; `PRIVATE` stays absent;
    - `test_daemon_failure_prevents_http_or_container_claims` (444): the unchanged claim, plus no probe.
11. New: a probe exec that fails with `No module named app.probe` → `design-engine`, `vm-connection`,
    `http-browse`, `git-http` and `capture` answer `SKIP` with the rebuild fix, never `PASS` and never
    `FAIL`; `{"error": "state unreadable"}` → `SKIP` naming Diagnostics for `vm-connection` and
    `http-browse` and the save drawer for `git-http` (6.1, the SKIP table); `{"error": "<helper sentence>"}`
    → `FAIL` with that sentence; `check_docker` expects `{"ready": true}` from `/api/health` and `FAIL`s on
    `{"version": …}` alone; `tls_context is None` → `http` `SKIP` with the `tls.files` fix and no request
    sent; a `vm-connection` answer whose `host` lacks `fingerprint_saved` → `WARN`, never `PASS`.

In `tests/test_probe.py` (slice S3, the venv group): each probe's JSON shape against a temporary
data directory written by a real `Store` **in the test process only** (the probe runs as a subprocess
with `DATA_DIR` pointing at it and must not change `state.enc`'s bytes or mtime); `browse` and
`git-registry` with the transport functions patched; `capture` with `CAPTURE_PROVIDER=disabled` and
with a loopback fake; `assert_not_logged`-style assertions that the password, the token and the setup
code never appear in stdout or stderr; an unknown name exits 2 with no JSON.

## 7. Installer changes

### 7.1 File by file

| File | Lines | Change |
|---|---|---|
| `clab-backup-ui/compose.yml` | 8, 16-21, new service | The command of 2.2, the tls mount, the `http-redirect` service (4.1). |
| `deploy/compose.image.yml` | 11, 19-24, new service | Mirror of the above with `${MANAGER_IMAGE}` for both services. |
| `clab-backup-ui/Dockerfile` | 22, 24 | `EXPOSE 8443 8081`; `CMD` with the TLS arguments and `--no-proxy-headers --no-server-header`. |
| `deploy/start-manager.sh` | after 24; 95; 101; 105 | `bash "$script_dir/setup-tls.sh" --no-recreate` after `setup-vm.sh`; `up` unchanged (recreates both services); line 101 → *Open the manager at `https://<primary>:<UI_PORT>` (plain HTTP on <UI_HTTP_PORT> redirects there). Certificate fingerprint: …*, where `<primary>` is `setup-tls.sh --primary` (3.1) and the ports come from `env_value` (62-63); line 105 → *Sign-on: the first administrator is created in the browser with the setup code. On the VM: sudo cat /srv/containerlab-node-manager/data/setup-code* (the `sudo cat` form of REVIEW U13; the script never prints the code itself: the installer prints it last, 7.2). |
| `deploy/recreate-manager.sh` | 41 | `up -d --no-build --no-deps backup-ui http-redirect`. |
| `deploy/setup-tls.sh`, `deploy/setup_tls.py` | new | Section 3, with `--name`, `--primary` and the pure `certificate_addresses()` (3.2). |
| `deploy/setup-firewall.sh` | new | 5.2. |
| `deploy/setup-ssh-hardening.sh` | new | 5.4. |
| `deploy/manager-recover-admin.sh` | new | DESIGN.md 9.5, RECONCILIATION §4.4 and REVIEW R11: root only, no options, finds the container exactly as `recreate-manager.sh:16-39` does (source route or prepared image), runs `docker exec <id> python -m app.recover` and prints its output unchanged (the code is in it, DESIGN.md 9.5). When that command exits 0 the script prints **one more line of its own, last**: `Open https://<primary>:<UI_PORT>/setup?recover=1 within 15 minutes and create one new administrator.`, where `<UI_PORT>` is read with the `env_value` reader of start-manager.sh:62-63 from the env file the chosen route uses (`clab-backup-ui/.env` or `deploy/image.env`, default 8443; the port is omitted when it is 443) and `<primary>` is `setup-tls.sh --primary` (3.1). It exits with `app.recover`'s status and prints nothing else of its own but the route it chose. The URL is the script's, not `app.recover`'s, because the TLS port is a VM setting the container does not know (9, interface 6). |
| `deploy/install-manager.py` | 100-116 | `health_url(command)` returns `https://<addr>:<port>/api/health` when `--ssl-certfile` is in the command and raises `ValueError('The manager is configured without TLS; rebuild it with Install/update.')` otherwise. `test_install_manager.py:55-66` is rewritten for the new form (the behavioural claim, bind and port extraction, is kept; the expected string changes). |
| | 119-152 | `check_manager`: the opener pins `/srv/containerlab-node-manager/tls/cert.pem` (readable by the ordinary account, 0644) with `check_hostname=False`; expects `{"ready": true}`; the version comparison at 125-128 stays as the only version proof; `say` lines 143-145 print `https://`, then the fingerprint (from `openssl x509`, unprivileged). The setup code is **not** printed here (REVIEW U13: it is printed last, 7.2 step 7). |
| | 244-254, 257-279 | The two sentences *all VM interfaces, port 8081* → *all VM interfaces, TLS port 8443, plain-HTTP redirect on 8081*. |
| | 544-562 | Advanced mode asks two more questions: *Firewall* (set up / skip) and *SSH hardening* (apply / skip), and the port question of 7.4 when an existing `.env` collides. |
| | 565-583 | `plan_lines` gains: *TLS: self-signed certificate for <the certificate addresses and names of 3.2> in /srv/containerlab-node-manager/tls (kept if one exists)* or *TLS: keep the provided certificate (expires <date>)*; *Firewall: ufw allow <ssh>, <UI_PORT>, <UI_HTTP_PORT>; deny other incoming*; *SSH: conservative sshd drop-in (PermitRootLogin no, MaxAuthTries 4, LoginGraceTime 30)*; *Sign-on: the first administrator is created in the browser with a setup code printed at the very end.* |
| | 605-631 | `install_steps`: after `verify`, `Step('firewall', 'Firewall', command_step(['sudo','bash',…'setup-firewall.sh']), argv=…)`, `Step('sshd', 'SSH hardening', …)`, both `visible` only when chosen, then the unchanged steps, and **as the last step of the list** `Step('signon', 'Setup code', …, bare=True)` (7.2 step 7): it runs after every step that could recreate or restart the manager (a restart in setup mode regenerates the code, DESIGN.md 9.2), so the code it prints is the one the file holds when the installer ends (REVIEW U13). The total count follows. |
| | 679-681 | The closing lines name the HTTPS address and the fingerprint before the Git and health-check sentences; **the setup code and its URL are the final lines of the installer's output**. |
| `deploy/installer_tui/probes.py` | 7, 80-93 | The docstring and `env_settings` keys add `UI_HTTP_PORT`. |
| | 96-109 | `manager_address` returns `https://…`. `test_install_tui_core.py:1123` keeps its secrecy claim. |
| | 112-119, 141-168 | `http_version` becomes `http_ready(url, cafile)` reading `/api/health`; `probe_manager` reads the version with `sudo -n docker exec … python -c 'from app import __version__; …'` (the `sudo -n` shape of 157-159) and reports `Needs authentication` with *answering on port N; version needs sudo* when refused. The dashboard gains a row `tls` (*TLS certificate: self-signed, expires <date>* / *provided*) from `setup-tls.sh --show` run unprivileged. |
| `deploy/installer_tui/engine.py` | 352-361 | Unchanged in shape; `check_manager` now prints the extra lines through `say`. The run record (473-478) stays metadata-only: **the setup code and the fingerprint are never written to it.** |
| `deploy/installer_tui/app.py` | 261, 607 | The two *port 8081* sentences. |
| | 1753-1757, 1818-1826 | The *open the manager at* line lists `https://<primary>:<port>/` (`setup-tls.sh --primary`, unprivileged, 3.1) and then each IP certificate address of 3.2 that differs from it (the `IP:` SANs of `setup-tls.sh --show`; at most three addresses in all, as today), **never `hostname -I`** (REVIEW R18): `vm_addresses()` (1818-1826) is removed with this, its only caller, because `hostname -I` lists `docker0` and the containerlab bridges, the very addresses the certificate never names, and a URL on one of them would add a name-mismatch warning to the self-signed one. When `--primary` cannot be run the line falls back to `https://<VM address>:<port>/`. Plus two steps: *The certificate is self-signed: the browser warns once; its SHA-256 fingerprint is <…>* and *Create the first administrator at `https://…/setup` with this setup code: <code>* (or *An administrator exists; sign in*). The summary screen reads the file when it is shown, after the last step (REVIEW U13); the code is never in the run record (engine.py:473-478). `test_install_tui_app.py:1454` patches the `--primary` and `--show` readers instead of `vm_addresses`. |
| `deploy/check_install.py`, `deploy/check_exposure.py` | 6.1, 6.2 | |
| `clab-backup-ui/app/allowed_hosts.py` | 27-30 | `REFUSAL` names `https://192.0.2.10:8443/`. The docstring's *has no login* (3) is DESIGN.md's to change. |

### 7.2 Order of a fresh installation

1. Prerequisites (unchanged).
2. `start-manager.sh`: verify release (19) → `setup-vm.sh` (24) → **`setup-tls.sh --no-recreate`** (new) →
   `setup-discovery.sh` (25) → helpers → capture stack (64-70) → build (73) → `up` (95): the manager
   starts in setup mode (DESIGN.md 9.1) serving TLS; the redirect starts.
3. Verification (`check_manager`): HTTPS `/api/health` with the pinned certificate; prints address,
   fingerprint.
4. Firewall (5.2), SSH hardening (5.4).
5. Engineer access, lazydocker, Git: unchanged order after.
6. The health check (6).
7. **Setup code, last** (REVIEW U13: every step that recreates or restarts the manager has run, and a
   restart in setup mode regenerates the code): `sudo cat …/data/setup-code` (the data directory is
   0700 uid 10001, setup-vm.sh:8, so the ordinary account cannot read it); print *Open
   `https://<primary>:<UI_PORT>/setup` and enter this setup code: `xxxxxx-xxxxxx-xxxxxx-xxxxxx`*, then
   *It is also readable on the VM with: sudo cat /srv/containerlab-node-manager/data/setup-code*. When the
   file is absent: *An administrator exists; sign in at …*. The plain menu prints it as its final lines;
   the TUI shows it on the summary screen (never persisted). The step reads the file at that moment,
   never a value captured earlier.

The manager's own container log never carries the code (REVIEW R22a): its line is *Setup required: open
https://<address>:<port>/setup and enter the code from <DATA_DIR>/setup-code (on the VM: sudo cat
/srv/containerlab-node-manager/data/setup-code).*, where `<port>` is `UI_PORT` from the manager's environment
(2.4; 8443 when the variable is absent, as under a bare `docker run`: DESIGN.md 9.2's default and the port of
the Dockerfile `CMD`, 2.2 rule 5) and `<address>` is the
first `UI_ALLOWED_HOSTS` name or the literal words *the VM's address* (DESIGN.md 9.2): the app knows its bind,
not the address students use, so the exact URL comes from the installer (step 7) and the recovery script
(7.1) (9, interface 6). The code is typed by a person and
compared normalised (strip, lowercase, dashes and spaces removed, then `compare_digest`; REVIEW U13), so a
code copied from the terminal with a line break or without its dashes still works.

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
| `UI_PORT=8081` explicit, `UI_HTTP_PORT` absent | **Standard path:** the operator's explicit port is kept for TLS and `setup_tls.py` writes `UI_HTTP_PORT=0` (the `write_env` pattern), then prints: *Your settings keep the manager on port 8081, which now serves HTTPS; there is no plain-HTTP redirect. Old links `http://VM:8081` show a browser error until retyped as `https://`. To get the redirect, set `UI_PORT=8443` and `UI_HTTP_PORT=8081` in `.env` and rerun.* **Advanced path:** the question *Manager ports: (1) TLS on 8443 and plain-HTTP redirect on your current 8081 (recommended) (2) TLS on your current 8081, no redirect*; on (1) the installer writes `UI_PORT=8443`, `UI_HTTP_PORT=8081` (the `write_env` pattern, 2.4) before `start-manager.sh` runs. | the installer; the operator in advanced mode |
| `UI_PORT == UI_HTTP_PORT`, both explicit | `setup_tls.py` refuses with the sentence above; `start-manager.sh` stops before building. | the operator |
| A certificate already in the tls directory | kept (ensure semantics, 3.1). | automatic |
| `UI_ALLOWED_HOSTS` set | its names become SANs. | automatic |
| A **provided** certificate on a name, students who open the manager by that name (REVIEW R17) | After the first HTTPS visit the browser applies HSTS to every port of the name: `http://<name>:8081` is rewritten to `https://<name>:8081` before any request, so the redirect listener is never reached by name and old links by name show a browser error until retyped as `https://<name>:8443`. Links by IP address keep redirecting. A plain-HTTP lab service the operator exposes on that name is opened by IP. The installer's closing lines and INSTALL.md say so; the health check prints `tls.hsts-scope` (6.2). | automatic; the operator announces the new address |

Why the operator is not locked out: the old address answers with a redirect; the new address answers
with the setup page (DESIGN.md 12.1: an upgraded install is in setup mode), and the code is printed
by the installer the operator is sitting at, and remains readable with `sudo cat`. The firewall step
runs after the manager verification and allows the session's own SSH port first (5.2). Nothing in
this design deletes or rewrites a setting the operator wrote, except the two writes of the
`UI_PORT=8081` row above, both announced and reversible, both through `setup_capture.write_env` (2.4):
the standard path's `UI_HTTP_PORT=0` line, written by `setup_tls.py`, and the advanced option (1),
`UI_PORT=8443` with `UI_HTTP_PORT=8081`, written by the installer (slice S5b) after the operator chose
it and before `start-manager.sh` runs, so `setup_tls.py` then finds no collision and writes nothing.

Why plain HTTP is not silently kept: after the upgrade the only plain-HTTP answer on the VM is
`301`; the health check fails when a page is served over plain HTTP (`http.redirect`, 6.2); the
compose files contain no plain-HTTP command.

## 8. Documentation and CI

### 8.1 Documents

| File | Section / lines | Change |
|---|---|---|
| `docs/INSTALL.md` | 202-248 *Opening the manager by a name* | Rewrite the first paragraph (the manager has a login now, DESIGN.md), keep the DNS-rebinding list, add that every listed name becomes a certificate name (3.2) and that `recreate-manager.sh` after a change needs `setup-tls.sh` too (ensure runs at upgrade only); replace the reverse-proxy advice at 220-235 and 246-248 with 2.3 (tolerated, source address caveat). |
| | new *TLS and the certificate* after *Browser Wireshark* (177-201) | Self-signed default, the browser warning and the fingerprint (3.6), `setup-tls.sh` options (3.1, with `--name` for an address outside the default-route rule), **which addresses the certificate names and which it never names** (3.2, REVIEW R18: a lab deploy does not change the certificate), a provided certificate and the certbot hook (3.4), importing the certificate on managed workstations (3.5), the 730-day renewal, and **the HSTS scope of a provided certificate** (4.2, REVIEW R17: by name, `http://<name>:8081` and plain-HTTP lab services on that name are reached by IP or before the first HTTPS visit). |
| | new *Firewall and SSH* | 5.2 and 5.4, fail2ban recommendation, the Docker-published-ports caveat. |
| | new *Ports* | 8443 TLS, 8081 redirect, `UI_HTTP_PORT=0`, the upgrade table 7.4 including its HSTS row. |
| | *Finish in the browser* (331-391) | `https://`, the first-administrator step (UI.md's wording): the code is the installer's final lines or `sudo cat /srv/containerlab-node-manager/data/setup-code` (REVIEW U13); the recovery command and the URL it prints (`…/setup?recover=1`, REVIEW R11). |
| `docs/sign-on/TOOLS.md` | new (REVIEW R15, slice S11) | Every tool under `docs/*/tools` that talks HTTP to the manager, with its status: *works through the fixture* (the Playwright checks against `fixture_manager.py`, which signs requests in through its fixture-only ASGI wrapper; `--signed-out` and `--role operator` switch it), *migrated* to `docs/sign-on/tools/manager_http.py`, or *needs the helper* with the reason it was not migrated. |
| `docs/sign-on/tools/manager_http.py` | new (REVIEW R15) | The standard-library helper of the live tools: an `https://` base URL, `--cafile PATH` or `--pin cert.pem` (the installed certificate, 3.3), credentials from `CLAB_USER` and `CLAB_PASSWORD` or a prompt (never a command-line value), a cookie jar; `docs/git-redesign/tools/live/*`, `integration/*` and `docs/multi-platform-restore/tools/*` move to it. Not a document, listed here because 8.1 is where the tool inventory lives. |
| `docs/CAPTURE.md` | 236-243 | Replace *The manager still has no user login … authenticated HTTPS reverse proxy* with: the manager needs a session and serves TLS itself; a proxy is not needed. |
| | 280-287 | The noVNC *secure context* paragraph becomes history: *before TLS (1.31.8 and earlier) the console logged …*; the rebuild advice stays. |
| `docs/HEALTH-CHECK.md` | *What it checks* (92-123) | The new group and its ids (6.2). |
| | 232-239 | `https://…:8443`, accept or verify the certificate, the firewall sentence. |
| `docs/STANDALONE-SETUP.md` | 89-90, 107 | `https://VM_ADDRESS:8443`; the sign-in sentence; the `docker run` migration needs the tls mount and `-e UI_PORT=<port>` for the setup log line (absent, the line names 8443, which is right unless the `docker run` overrides `--port`; 7.2). |
| `docs/FRESH-VM-GUIDE-V2.md` | 584-600 | `8443` and `8081`; *the installer sets up ufw* replaces *does not configure … firewall rules* (595-596); the `Test-NetConnection` lines. |
| `docs/VM-CONNECTION.md` | 41 | `https://VM_IP:8443`, sign in first. |
| `docs/QUICK-INSTALL.md` | 62, 171 | Same. |
| `README.md` | 89, 125 | Same; the diagram says *port 8443 TLS · 8081 redirect*. |
| `docs/WIKI-MASTER-GUIDE.md` | 31, 55, 72, 719, 753, 776-793, 808, 1399, 1414, 1509, 1572 | Each `8081` and *no login* sentence; the sample `.env` gains `UI_HTTP_PORT`. |
| `docs/ARCHITECTURE.md` | 150-157 | The transport paragraph: uvicorn-native TLS, the redirect service described with the one sentence of 4.1 (REVIEW R19), `--no-proxy-headers`, HSTS in `security_headers()`. |
| `clab-backup-ui/README.md`, `deploy/*.md` | wherever `http://` or `8081` appears | Same. **Ruling (RECONCILIATION 4, E-Q6): yes.** The build adds a rule to `verify_docs()` in `deploy/verify-release.py` that refuses `http://…:8081` manager URLs in the living guides; history files are exempt. `check_links.py` does not check URLs. |
| `docs/HEALTH-CHECK.md` | *What it checks* | Besides the new group (above): the one-HTTP-question rule and the probes of 6.1, and the SKIP reasons a reader may meet (*predates this check's probe*, *Diagnostics runs the same check*, *a lab's save drawer lists the registry*). |
| `CLAUDE.md` | invariants (the lead, at the release step; REVIEW R19) | The replacement of the "There is no login" bullet **keeps every sentence of the current bullet** (CLAUDE.md:247-253: the guard's body rule, *a mutating request needs a body; content-length 0 is refused, so pages post `{}`*; *every WebSocket checks `Origin` itself and terminals need a single-use ticket*; `HostCheck` *stays the outermost ASGI layer (added last in `create_app`)* and *nothing bypasses it*), rewriting only *There is no login* and the guard's description for the gate, and in particular the three REVIEW R19 found dropped: *Never add a route or socket outside this*, the DNS-rebinding sentence (*a `Host` that outside DNS could control is refused unless `UI_ALLOWED_HOSTS` lists it*) and *`X-Forwarded-Host` is never read*, with the redirect named as the one exception by the sentence of 4.1, verbatim: *`app/redirect.py` is the one listener outside the gate and the guard: it holds no data and answers 301 to the manager's own HTTPS origin after `host_allowed`, 400 for a refused Host or a request target that is not a path, 405 for any method but GET and HEAD, closes a socket 1008, and nothing else.* Plus: *The manager serves TLS itself; the compose command carries the certificate paths and `--no-proxy-headers`.* A row *Sign-on, sessions, TLS* joins the routing table. |
| `.claude/rules/routing-privileged-paths.md` | the path globs (the lead; REVIEW R19) | `app/sessions.py`, `app/accounts.py`, `app/origin.py`, `app/headers.py`, `app/recover.py`, `app/probe.py`, `app/redirect.py`, `deploy/setup_tls.py`, `deploy/manager-recover-admin.sh` join the rule **once the files exist** (`deploy/setup-tls.sh`, `deploy/setup-firewall.sh` and `deploy/setup-ssh-hardening.sh` are already covered by the rule's existing `deploy/setup-*.sh` glob, routing-privileged-paths.md:5, so no glob is added for them) (`test_claude_config.py` `test_path_globs_match_a_repository_file` refuses a glob without a file), so the rule change is part of the integration commit, not of a slice. |

### 8.2 CI and tests

| Where | Addition |
|---|---|
| `.github/workflows/release-check.yml:40` (`bash -n` loop) | `deploy/setup-tls.sh deploy/setup-firewall.sh deploy/setup-ssh-hardening.sh deploy/manager-recover-admin.sh`. |
| release-check.yml:19-37 (stdlib group) | `test_setup_tls.py`, `test_setup_firewall.py`, `test_setup_ssh_hardening.py`, `test_check_exposure.py`, `test_manager_recover_admin.py` (the name BUILD.md S5a uses). |
| venv group | `test_redirect.py` (TestClient on `app.redirect:app`: 301 with the exact `Location`, 400 on a refused `Host`, 405 on `POST`, 1008 on a socket; no import of `app.main`; and the three `raw_path` cases of REVIEW R20: `/a%0d%0ab` gives `Location: …/a%0d%0ab` and no second header line, `/a%3Fb?c=1` gives `…/a%3Fb?c=1`, a UTF-8 path travels as its percent-encoded bytes; and a target that is not origin-form, `@evil.example/`, `http://evil.example/` and `*`, sent through a raw socket or a transport that passes the target unchanged, answers 400 with the `security_headers(refusal=True)` headers and `Content-Length: 0` and no `Location`; every 400, 301 and 405 carries exactly one `Content-Length`, `0`, and no `Strict-Transport-Security`), `test_probe.py` (6.3). |
| `tests/test_setup_tls.py` | SAN list from fixtures (addresses, names, union of two env files, `tls/names`); **`certificate_addresses()` on the `ip -j` fixture of 6.3 case 3**: the default-route interface's global addresses are in, `docker0`, `br-…`, `veth…`, `virbr0`, `cni0`, `clab…`, link-local and loopback are out, and a VM without a default route falls back to every non-excluded interface (REVIEW R18); **ensure does not regenerate** when only an excluded address appeared; the exact `openssl` argv; **real generation into a temp dir** (CI's Ubuntu has `openssl`) and parse-back of SANs and `-checkend`; a provided pair that does not match is refused; an encrypted key is refused; modes 0644/0640; `mode` file; `--name` validation and `tls/names`; `--primary`; `UI_PORT == UI_HTTP_PORT` refused; the 7.4 migration write through `setup_capture.write_env` keeps unrelated lines. |
| `tests/test_manager_recover_admin.py` | The `test_recreate_manager.py` pattern (a copy of the script with the root guard neutralised, a fake `docker` and `setup-tls.sh` on `PATH`): the route choice, `app.recover`'s output passed through unchanged, the final URL line built from the chosen env file's `UI_PORT` (default 8443; omitted at 443) with `?recover=1`, no URL line when `app.recover` exited non-zero, the exit status passed through (REVIEW R11). |
| `tests/test_setup_firewall.py` | The `test_recreate_manager.py` pattern (a copy of the script with the root guard neutralised, a fake `ufw`, `sshd` and `ss` on `PATH` recording argv): the allow order, refusal when `SSH_CONNECTION`'s port is not allowed, `--remove`, never `reset`. |
| `tests/test_setup_ssh_hardening.py` | Same pattern with a fake `sshd -T`: a directive at the default is written, a customised one is not; rollback on `sshd -t` failure. |
| `tests/test_release_consistency.py:88-99` | Compare the environment keys of **both** services across the two compose files; assert `UI_PORT` is in both services' environment and that the manager's environment gains no other key (2.4); assert both commands carry `--ssl-certfile /tls/cert.pem`, `--ssl-keyfile /tls/key.pem`, `--no-proxy-headers`; assert the tls mount is `read_only: true`; assert `http-redirect`'s command is `python -m app.redirect`; assert `UI_TLS` is absent from both compose files (E-Q1, RECONCILIATION 4). |
| `tests/test_release_consistency.py` (`verify_docs`) | The E-Q6 rule of 8.1 is in the documentation half that this test runs against the checkout: a living guide with `http://…:8081` fails it, history files pass. |
| `tests/test_install_manager.py:55-66` | `https://…/api/health`; a command without `--ssl-certfile` raises. |
| `tests/test_install_tui_app.py:1454` | The summary-screen fixture patches the `--primary` and `--show` readers (7.1) in place of `vm_addresses`; the asserted line is `https://192.0.2.10:8443/` and no `hostname -I` runs. |
| `tests/test_check_install.py` | 6.3 cases 9-11: `check_docker` expects `{"ready": true}`; every route case routes through `Context.probe`; `ctx.http` is never given a path but `/api/health`; the SKIP reasons of 6.1. |
| `tests/test_app.py` | HSTS present under `base_url='https://testserver'`, absent under `http`. |
| `tests/test_claude_config.py` | Unchanged test, new expectation: the globs added to `routing-privileged-paths.md` (8.1) each match a file; the lead runs it at integration. |
| `deploy/verify-release.py:40-41` | No new HTML page here (UI.md adds `login.html` and `setup.html`). |

## 9. Interfaces to the other parts

What this design needs from `DESIGN.md` (D) and `UI.md` (U), and what it gives back.

1. **The scheme rule (D 5.6).** Answer: uvicorn terminates TLS, so `scope['scheme']` is `https` and
   `ws.url.scheme` is `wss` without configuration. **Decided: `UI_TLS` is dropped** (RECONCILIATION 4,
   E-Q1). It is in neither compose file, and `origin.scheme(scope)` reads the ASGI scope only.
   `test_release_consistency.py` asserts the key is absent from both compose files (8.2), because a
   stray `UI_TLS=1` on a plain-HTTP fixture makes every cookie `Secure` and locks the tester out.
2. **The `Secure` cookie (D 5.3).** `Secure` when `scheme(scope) == 'https'`: on every shipped
   installation. On the fixture over `http://127.0.0.1` it is not `Secure`, which is correct.
3. **The health route (D 6.7).** `GET /api/health` → `200 {"ready": true}` with `Cache-Control:
   no-store`, exempt from the gate (it is in `EXEMPT`, so it answers to no session, to a restricted
   session, REVIEW R1, in setup mode and in recovery mode, D 9.3). The installer polls it over HTTPS
   with the pinned certificate; the health check reads it and asks the manager nothing else over HTTP
   (6.1, REVIEW R16). It must not redirect, not set a cookie, not renew a session (it is a `GET`, and no
   `GET` renews one, REVIEW R9) and not vary by `Accept`. Its body carries no `message` because it is
   not a refusal; the gate's own 401, 403 and 503 bodies do (REVIEW U11), which this design does not
   consume.
4. **No redirect loop, and the fragment.** The manager never answers a plain-HTTP request (there is
   no plain-HTTP listener on it), so the gate's `302 /login?next=…` (D 6.4) and the redirect listener's
   `301` cannot chain: `301` goes to `https://host:8443<raw_path>?<query>`, then the gate decides. The
   fragment never reaches either server; a browser re-attaches a bookmark's `#lab=…&view=devices` to
   the `301`'s `Location` (it has none of its own) and again to the gate's `302 /login?next=%2F`, and
   `loginNext` appends `location.hash` to a safe `next` that has no `#` (REVIEW U7), so a student's old
   `http://VM:8081/#lab=…` bookmark ends on that lab and tab after sign-in. U's `loginNext` must accept
   the paths that the `301` preserves (it accepts `/` and fragment-free paths, UI.md 1.6).
5. **Probes without a session (REVIEW R16; slice S3).** `python -m app.probe <name>` with the five
   names and the exact JSON of 6.1: `design-engine`, `capture`, `vm-connection`, `browse <path>`,
   `git-registry`. A probe never constructs a `Store`, never writes and never makes an HTTP request; the
   three that need the saved state decrypt `state.enc` read-only in the `STORAGE_PROBE` pattern
   (check_install.py:299-313) and run the manager's own module-level clients (`lab_operations.remote`,
   `git_progress.remote_git`) read-only. The health check runs them through `docker exec` as
   `STORAGE_PROBE` is run (check_install.py:331). D 6.7's "every other manager fact … through `docker
   exec`" is this contract; D 16's probe row (`app/probe.py`, the backend builder; BUILD.md S3 routes it to
   `clab-opus-specialist`) should name the same five names, a request to DESIGN.md.
6. **The setup code (D 9.2).** The file `/srv/containerlab-node-manager/data/setup-code`, 0600 uid
   10001, with `mode=setup` or `mode=recover` on the first line and `code=<code>` on the second. The
   installer prints the code **last** (7.2 step 7, REVIEW U13); the health check prints only its
   presence and mode (6.2). The manager's container log never carries the code (REVIEW R22a): the
   line is *Setup required: open https://<address>:<port>/setup and enter the code from
   <DATA_DIR>/setup-code (on the VM: sudo cat /srv/containerlab-node-manager/data/setup-code).*;
   `<port>` is `UI_PORT`, which the manager's environment carries for this line alone (2.4: uvicorn's
   `--port` is otherwise known to the app only inside a request `scope`, and the line is printed at
   startup), and `<address>` is the first `UI_ALLOWED_HOSTS` name or the words *the VM's address*
   (D 9.2): the app cannot know the address students use, so the installer and the recovery script
   supply the exact URL. The manager compares the typed code normalised (strip, lowercase, dashes and
   spaces removed) before `compare_digest`; the setup page's help reads *Printed at the end of the
   installation. On the VM: sudo cat /srv/containerlab-node-manager/data/setup-code* and its 401
   sentence *That setup code is not right. On the VM, run: sudo cat
   /srv/containerlab-node-manager/data/setup-code* (REVIEW U13; U 2, U 8), which is why 7.1 keeps that
   exact command in every operator-facing line.
7. **Recovery (D 9.5, REVIEW R11).** `deploy/manager-recover-admin.sh` (7.1) runs `docker exec
   <container> python -m app.recover`, prints its output unchanged (the code), then one line of its
   own, last: `Open https://<primary>:<UI_PORT>/setup?recover=1 within 15 minutes and create one new
   administrator.` The script, not `app.recover`, owns the URL: the TLS port and the primary name are
   VM settings (`.env`, `setup-tls.sh --primary`) the container does not know. `setup.js` reads
   `?recover=1` from its own address and shows *Recovery: create one new administrator* with the lead
   *Enter the code the recovery command printed, then choose a new administrator account. Existing
   accounts are not changed.* (U 2); `POST /api/setup` never overwrites a record (an existing name is
   `409 {code:'exists', message:'That name already exists. Choose a new name for the recovery
   administrator.'}`, D 7.3). The 15-minute window is the file's mtime, which is on the VM's clock
   (10.2); the health check names the open recovery (`signon.bootstrap`, 6.2).
8. **HSTS** lives in `security_headers()` (RECONCILIATION Dq 5), sent when `scheme(scope) == 'https'`;
   its port-wide scope under a provided certificate is this document's to state (4.2, REVIEW R17).
9. **The source address (D 8.1, D 10).** `scope['client'][0]` is the real client on every supported
   mode (2.3) because `--no-proxy-headers` is explicit (2.2). Under the tolerated proxy mode it is
   `127.0.0.1`; INSTALL.md says so. D 8's throttle keys (IPv4 address, IPv6 /64, an IPv4-mapped
   address unmapped first, REVIEW R6) are computed from that value; the manager's bind (`UI_BIND`,
   default `0.0.0.0`) decides whether IPv6 clients exist at all, which 2.4 leaves to the operator.
10. **The 401 on the poll (U 3.3).** Unaffected by TLS; the `Secure` cookie travels on every `wss://`
    handshake because the page is `https://`. The one guard in `api()` (REVIEW U8) is the page's.
11. **The sign-in page's plain-HTTP banner (U, `#signin-plain`).** It can only appear on a fixture; on
    a shipped installation no page is served over plain HTTP. It stays as written (it is the right
    sentence for a fixture reached by a LAN address).
12. **Invariant wording (lead, at the release step; REVIEW R19).** The CLAUDE.md replacement keeps
    every sentence of the current bullet (the body rule, WebSocket `Origin` and single-use tickets,
    `HostCheck` outermost and added last, nothing bypasses it; 8.1), among them the three REVIEW R19
    found dropped, *Never add a route or socket outside this*, the DNS-rebinding sentence and
    *`X-Forwarded-Host` is never read*, and names the redirect as the one exception with the sentence of 4.1, verbatim and
    the same everywhere (CLAUDE.md, ARCHITECTURE.md, INSTALL.md, the handoff section): *`app/redirect.py`
    is the one listener outside the gate and the guard: it holds no data and answers 301 to the
    manager's own HTTPS origin after `host_allowed`, 400 for a refused Host or a request target that
    is not a path, 405 for any method but GET and HEAD, closes a socket 1008, and nothing else.* The new files join
    `routing-privileged-paths.md` at integration (8.1) and a *Sign-on, sessions, TLS* row joins the
    routing table.
13. **The TLS paths (D 16, slice S4).** The certificate paths inside the container are fixed:
    `/tls/cert.pem` and `/tls/key.pem` on the compose command and the Dockerfile `CMD` (2.2); on the VM
    `/srv/containerlab-node-manager/tls/{cert.pem,key.pem,mode,names}` with the owners and modes of
    3.3. Nothing in `app/` reads them: uvicorn does. The installer and the health check pin `cert.pem`
    (0644) for their own `/api/health` request; `key.pem` (0640 root:10001) is read by uvicorn alone.

## 10. What a reviewer should attack

| # | Assumption or failure mode | What the design does | What to attack |
|---|---|---|---|
| 10.1 | **Certificate expiry.** 730 days; ensure renews within 30 days at an upgrade; the health check warns and then fails. | A VM not upgraded for two years and never health-checked serves an expired certificate; browsers warn harder (Chrome still allows click-through for an expired self-signed certificate; an HSTS-stored trusted one is blocked). | Whether a renewal should also run from a timer (a systemd timer running `setup-tls.sh` monthly). Not in this version: a timer that recreates the manager at night would end sessions mid-course. |
| 10.2 | **Clock skew.** `notBefore` is the VM's time at generation; the recovery window is the VM's mtime. | `check_host._clock` warns when NTP is not synchronised (check_host.py:67-75); the installer checks NTP before APT (install-manager.py:571). A workstation whose clock is behind the VM's sees *not yet valid*. | OpenSSL 3.0 has no `notBefore` option for `req -x509`; backdating needs `openssl ca`. Decide whether the complexity is worth one rare case. |
| 10.3 | **A name or address not in the certificate.** Students type a name the operator never listed, or open the VM by an address outside the default-route rule (a second uplink, REVIEW R18). | The warning is the same interstitial as for self-signing (`ERR_CERT_COMMON_NAME_INVALID` vs `ERR_CERT_AUTHORITY_INVALID`); `HostCheck` refuses the name anyway unless listed (allowed_hosts.py:62-64), so the list and the SANs move together; `tls.names` warns; `setup-tls.sh --name` adds the address (3.1). | A single-label name typed by students passes `HostCheck` without being listed and is in the SANs only when it equals the VM's host name. A VM with two uplinks and one default route has one of them in the certificate until the operator runs `--name`; the installer's plan line names which addresses are in. |
| 10.4 | **HSTS lockout and scope.** A trusted certificate lapses to self-signed or expires; or the name's HSTS covers a port the operator meant to keep plain (REVIEW R17). | Browsers that stored HSTS refuse to click through until the certificate is fixed; `max-age` 180 days (`15552000`); no `preload`, so a `chrome://net-internals/#hsts` deletion or the fix works. The port-wide scope is stated (4.1, 4.2, 7.4, INSTALL.md) and reported (`tls.hsts-scope`). | **Decided (RECONCILIATION 4, E-Q5): 180 days.** Operators are lab engineers, and a lapsed trusted certificate must not lock a course out for a year. Attack: an operator who serves a lab's plain-HTTP tool on the manager's name learns of HSTS from a browser error; the INFO and INSTALL.md are the only warnings. |
| 10.5 | **Own origin under TLS.** The guard (main.py:122-123), both sockets, the capture cookie. | Correct by the scope because uvicorn terminates TLS and `--no-proxy-headers` is explicit (2.1.3). | Confirm in the running container that `uvicorn --no-proxy-headers` is honoured with `--factory` (it is a server option, not an app option), and that nothing else installs `ProxyHeadersMiddleware`. |
| 10.6 | **DNS rebinding under TLS.** | Unchanged: `HostCheck` stays outermost (DESIGN.md 6.1). TLS adds a second barrier: a browser's `fetch` to the attacker's name hits a certificate whose SANs lack that name and cannot click through. | The attacker first serves their own self-signed certificate on their name and the student clicks through there; Chrome stores the exception per host **and certificate**, so the manager's certificate on that host still errors. Verify this claim against current Chromium behaviour before relying on it in a guide; the design relies on `HostCheck`, not on this. |
| 10.7 | **The redirect listener.** A stdlib-free uvicorn process exposed to scanners. | Answers 301/400/405 only, closes a socket 1008, no body, no log per request, `read_only`, `cap_drop ALL`, no mounts. `Location` is built from a `Host` that passed `host_allowed` and from `raw_path` and `query_string` unchanged (REVIEW R20). | An open-redirect reading: the target host is the one the client sent, with the scheme and port fixed, so a redirect only sends a client where it asked to go. The one byte string that broke *port fixed* was a non-origin-form target (`@evil.example/` → `https://host:8443@evil.example/`, the userinfo form); 4.1 rule 3 answers it 400 and `test_redirect.py` pins it. Look for another target shape that passes the `b'/'` test and still changes the authority: a path starting with `//` gives `https://host:8443//x`, where the port already closes the authority, so it stays on the host. Header injection: `raw_path` is the bytes the client sent, so a CR or LF can only arrive percent-encoded and stays so; h11 refuses a raw one on the way in. Slow-client exhaustion of its event loop does not touch the manager. `--limit-concurrency` for both services is a possible addition. |
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
| 10.19 | **The probes read the saved VM password** (REVIEW R16). `vm-connection`, `browse` and `git-registry` decrypt `state.enc` in a second process and `browse` and `git-registry` use the password to open an SSH session as the manager would. | Only through `docker exec` as root on the VM (the docker group is root); the same trust `STORAGE_PROBE` already exercises (it decrypts the whole state today, check_install.py:299-313); the probe prints no password, fingerprint value, `bootstrap_*` field or helper registration detail; the transport functions are the manager's own, read-only modes only. **`browse` and `list` take no helper lock and change nothing**: the operations helper locks only `netem-set`, `netem-reset`, `preview` and `run` (host_operations.py:1381-1384), and that lock is non-blocking anyway (held elsewhere, it answers `LOCK_SENTENCE` instead of waiting, 1355-1360); the Git helper's `list` reads the registry without a lock (host_git.py:1527-1528). The probe also runs outside `GitProgress.helper_lock` (git_progress.py:895-897, 945), the manager's own serialiser, which guards against the per-repository lock that `list` never takes. | A probe call can neither wait on a running deploy or save nor make one refuse: neither side takes a lock the other holds (a probe during a `run` is one more SSH session, as a page's own browse is today). The 25 s timeout and `ctx.run`'s 30 s kill bound a slow VM, and the check then `FAIL`s with the helper sentence rather than hang. Check that the probe never grows a mode that does take a lock (`preview`, `run`, `connect`, a binding mode): the *Never* column of 6.1 forbids it. Whether `read_state()` could see a half-written `state.enc`: `Store.atomic` replaces the file in one `os.replace`, so a reader sees the old or the new document, never a partial one; `.reset-pending` is the one window where files move, and the probe answers *reset pending*. Whether a scrubbed helper sentence can still leak a path: `lab_operations.scrub` is what the manager shows operators today. |
| 10.20 | **The default-route rule for certificate addresses** (REVIEW R18). | The certificate names the default-route interface(s)' global addresses, the operator's `--name` list and `UI_ALLOWED_HOSTS`; bridges, veths and link-local addresses never. | A VM whose students arrive through an interface that is not the default route (a lab-side NIC) gets a warning page until `--name` is run; `tls.names` cannot know which address students use, only which are in the certificate. A policy-routed VM with two default routes: both interfaces are taken (the rule reads every `default` entry). A VM where `ip -j route` is unavailable: the fallback is every non-excluded interface, and the installer's plan line shows the result before anything is generated. |

## 11. Open questions for the lead

1. **`UI_TLS`:** drop it (9.1), or keep it as an undocumented fallback asserted absent from the compose
   files? This design recommends dropping it.
   **Ruling (RECONCILIATION 4):** dropped (E-Q1). `origin.scheme(scope)` reads the ASGI scope only;
   `test_release_consistency.py` asserts the key is absent from both compose files (8.2).
2. **The in-container probes (9.5):** is `python -m app.probe` the backend builder's slice, and is the
   no-`Store` rule satisfiable for the capture facts (they need the environment and two loopback
   services only; if any of them needs lab state, the health check drops that fact rather than
   constructing a `Store`)? The alternative, prompting the operator for a manager password inside
   `check-install.sh`, was rejected: it would create sign-in audit entries from a health check and
   conflate two credentials in one terminal session.
   **Ruling (RECONCILIATION 4):** yes, the backend builder's slice. `python -m app.probe design-engine|capture`
   never constructs a `Store`; a fact that would need lab state is dropped from the health check rather than read (E-Q2).
   **Narrowed by REVIEW R16:** a probe may **decrypt `state.enc` read-only** in the `STORAGE_PROBE` pattern
   (never a `Store`, never a write, never a value in its output), which serves the VM connection and
   discovery facts, the folder browse and the Git registry list (the probes `vm-connection`, `browse`,
   `git-registry` of 6.1); `GET /api/health` stays the only HTTP question the checker asks; a check whose
   probe cannot run answers SKIP with its reason and names where the same request runs (Diagnostics for
   the VM connection and the topology browser, a lab's save drawer for the Git registry: 6.1, the SKIP
   table), never a silent drop. The capture probe still drops the lab names (E-Q2) and prints a count.
3. **`fail2ban`:** recommend only (this design), or install it from `install-prerequisites.sh` with
   `ignoreip` of the installing session's address? The latter needs the session's address from
   `SSH_CONNECTION` and a decision for console installs.
   **Ruling (RECONCILIATION 4):** recommend and WARN (`ssh.bruteforce`, 6.2), as designed; not installed by the installer in this version (E-Q3).
4. **`DOCKER-USER`:** out of this version (5.2); confirm, or schedule it with live validation.
   **Ruling (RECONCILIATION 4):** out of this version; scheduled for the owner's live pass with deployed labs (E-Q4, 10.10).
5. **The `max-age`** of HSTS: one year (this design) or 180 days (10.4).
   **Ruling (RECONCILIATION 4):** 180 days, `max-age=15552000` (E-Q5, 4.2). No `includeSubDomains`, no `preload`.
6. **`verify-release.py` and the docs:** no rule refuses `http://…:8081` in a living guide today. Add a
   documentation rule to `verify_docs()` (deploy/verify-release.py:132) that refuses `http://` manager
   URLs outside history files, or rely on the one-time grep of 8.1?
   **Ruling (RECONCILIATION 4):** yes (E-Q6). The build adds the rule to `verify_docs()` in `deploy/verify-release.py`; history files are exempt (8.1, 8.2).
7. **The invariant sentence** for `app/redirect.py` (9.12) is the lead's at the release step.
   **Ruling (RECONCILIATION 4):** the lead writes it at the release step (E-Q7). The draft sentence that ruling carried is **superseded by the final wording below** and is not quoted here, so that this document carries one description of the redirect (REVIEW R19).
   **Final wording (REVIEW R19), the same in every document:** *`app/redirect.py` is the one listener outside the gate and the guard: it holds no data and answers 301 to the manager's own HTTPS origin after `host_allowed`, 400 for a refused Host or a request target that is not a path, 405 for any method but GET and HEAD, closes a socket 1008, and nothing else.* The replacement bullet keeps every sentence of CLAUDE.md's current bullet, among them the three REVIEW R19 found dropped (*Never add a route or socket outside this*, DNS rebinding, *`X-Forwarded-Host` is never read*; 8.1); the new files join `routing-privileged-paths.md` once they exist; a *Sign-on, sessions, TLS* row joins the routing table (8.1).
8. **Which probes exist and what they print** (REVIEW R16): decided in 6.1, five names with their exact JSON; the probe builder (S3) and the health-check builder (S6) build against that table and `test_probe.py` and `test_check_install.py` pin it from both sides.
