# Pickup — UIUX-EMAIL-2026-10-03 (Worker A, dev1)

- Branch `worker-a/uiux-email-2026-10-03`, base `e7ffbc1` (main, release 1.30.58). Coordination: issue #64
  (A's assignment comment lists A's writable paths; B owns the installer TUI paths).
- Requirements source: the decoded email and its 17 screenshots, kept outside the checkout
  (`~/DEV1-UIUX-Email-Implementation/source/`). Matrix: [MATRIX.md](MATRIX.md).
- Baseline on dev1 before changes: Python 1721 OK (1 skipped), Node 389 pass, `verify-release.py` OK,
  `node build.mjs --check` OK (132 files).

## dev1 state

- Manager 1.30.58 installed with the standard installer (`deploy/install.sh`), capture stack running,
  Git setup skipped. `clab-discovery` password in `~/.clab-dev1-secrets` (mode 600, not in the repo).
- `/etc/sudoers.d/91-dev1-verifypw` (`Defaults:archtop verifypw=any`) so the installer's `sudo -v`
  honours the existing NOPASSWD rule on this disposable VM.
- Images pulled: `n24l/cjunosevolved:26.2R1.7-EVO`, `n24l/vjunos-switch:23.2R1.14`,
  `n24l/cisco_xrv9k:24.3.1`, `n24l/ceos:4.35.0F`, `ghcr.io/srl-labs/network-multitool:latest`.
- Disposable T7 labs (deployed directly with containerlab, outside the manager): `~/dev1-labs/t7repro`
  (ptx1, unmodified) and `~/dev1-labs/t7fix` (ptx2 with `CPTX_AUTO_CONFIG`, ptx3 also with `hostname: core-ptx`).

## Ownership while agents run

| Scope | Files |
|---|---|
| Manager UI (chunk 1, committed) | `operations.js`, `app.js`, `capture.js`, `index.html`, `style.css` |
| Lab builder (T1, T2, T3, T7 template) | `lab-builder-page.js`, `lab-builder.{html,css}`, `map-editor-page.js`, `topology-render.js`, `lab-builder/patches.mjs`, `src/main.tsx`, bundle, `topology.py`, `drawio_export.py` |
| Design backend (8a, 8d, 8e) | `design_*.py`, `network_design.py`, design Python tests, `docs/NETWORK-DESIGN.md`, `DESIGN-CONTRACT.md` |
| Next | T5 (needs `operations.js` + `lab-builder-page.js`), design UI 8a–8c/8e/8f (`network-design.js`, `index.html`, `app.js`, `style.css`) |

## Log

- Chunk 1: T4a–c, T6, T9, T10 (manager UI). Unit + fixture browser evidence; live dev1 workflow pending.
