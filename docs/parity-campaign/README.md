# Parity campaign: containerlab-app and the VS Code extension against this manager

The owner's instruction of 2026-10-23: reach feature parity, as UI/UX improvements, between this manager and
[`srl-labs/containerlab-app`](https://github.com/srl-labs/containerlab-app) (the web, desktop and VS Code apps that
share one topology editor) and the VS Code Containerlab extension, within the development VM's memory and storage,
tested on the Juniper images first (`n24l/vjunos-switch:23.2R1.14`, `n24l/juniper_vjunos-router:26.2R1.7`,
`n24l/cjunosevolved:26.2R1.7-EVO`) with `n24l/cisco_xrv9k:24.3.1` and `n24l/ceos:4.35.0F`. The work runs
unattended in chunks; each chunk is a release with its CHANGELOG, VALIDATION and handoff sections, committed and
pushed on `claude/parity-campaign`. [PICKUP.md](PICKUP.md) is the live state; this page is the plan.

## What was researched

- [RESEARCH.md](RESEARCH.md): eight feature inventories (upstream documentation, the web app and the sandbox, the
  extension's manifest, the extension's sources, the server side, the editor packages; this manager's guides and its
  code), about 1,700 entries, each with evidence.
- [PARITY.md](PARITY.md): the matrix, 99 rows (22 present, 20 partial, 57 absent), 27 features already at parity, 22
  not pursued with the reason (the invariants in `CLAUDE.md`, the deployment model or the student audience), the
  synthesis's chunk proposal, and the critic's corrections (missing rows, wrong statuses, invariant claims that the
  design sketches must respect, uncovered areas).

Boundaries that hold throughout: the manager never gets a Docker socket or host metrics; VM work goes through the
three fixed helper request names with structured stdin and read-only or reviewed mutating modes, each addition a
security-sensitive change reviewed by `risk-reviewer`; device access is direct node SSH; browser Wireshark is the
capture path; the UI is plain JavaScript with no framework, no CDN and no inline styles on `/`; the topology editor is
the embedded `@containerlab/clab-ui` 0.3.2 in map mode (0.4.0 is in the upstream monorepo but not on npm, so every
0.4.0-only editor feature is blocked); telemetry stays retired; supported restore kinds are only those proven live.

## The plan (the lead's cut of the matrix, after the critic)

| # | Chunk | Rows | Kind of change | Live need |
|---|---|---|---|---|
| C00 | vJunos-router boot triage on the `parity` lab | - | VM operations | yes |
| C01 | `juniper_vjunosrouter` as a managed kind (backups, downloads, saves, catalog); restore and design off | R035 | app, offline: **done** (`673c0e6`) | live pass after C00 |
| C02 | Ergonomics: terminal toolbar (font size, copy, clear, export), Copy on drawer facts and operation output, stop a running lifecycle command, hide the editor's upstream About entry | R025, R110, R111, R112, R010 | page scripts, one manager route, no helper | one pass: a stopped deploy, with the process group and the lock proven gone |
| C03 | Read-only diagnostics through the operations helper, as modes outside the host lock: container logs (redacted, never persisted), interface list and a bounded counter sample, netem show, image size and age, lab-folder file listing; the Interfaces and Logs sections of the device drawer; inspect table extras; containerlab version | R020, R028, R029, R030, R013, R091, R100 | helper (read-only modes) + app + UI; `risk-reviewer` | yes (parity lab) |
| C04 | Serial console for the vrnetlab kinds once the container is healthy (vJunos-switch, vJunos-router, XRv9k), container facts in the device drawer (container id, all addresses) | R021, R024 | `node_services.py` + discovery + UI | yes |
| C05 | Mutating lifecycle through the helper, one release: link impairments (set, reset, with the management interface refused), start and stop one device, apply dry-run plan on demand, node filter for deploy and destroy, per-device save, extra run flags | R040, R041, R042, R005, R006, R007, R008, R009, R011 | helper (mutating modes) + app + UI; `risk-reviewer`, `clab-network-specialist` | yes |
| C06 | Topology tab parity: link up/down colours (from C03), Download picture (SVG, PNG through a data URL), find a node and link hover, stored annotation styles, draw.io layout and theme, one-click arrange outside Edit map | R043, R066, R067, R068, R069, R064, R070 | page scripts | no (fixture) |
| C07 | Capture parity: one Wireshark per interface or one for all, both ends of a link, remembered selection, End all my sessions | R051, R052, R053, R054 | `capture.js`, `capture.py`, session service | yes (loopback smoke) |
| C08 | Builder YAML checks: schema diagnostics from the schema that matches the VM's containerlab, stage validation with a Juniper example | R071, R072 | adapter bundle rebuild, new release | no |
| C09 | Help and preferences: Help group in the Manager menu, keyboard shortcuts dialog, Home lab filter, per-browser preferences (no dark mode: the binding design contract allows dark only for the toast and the terminal, an owner decision) | R090, R122, R123, R125 | page scripts | no (fixture) |
| C10 | Load onto vJunos-router proven live (the NOS transaction, `docs/multi-platform-restore` tools), then the kind joins the supported restore kinds | R039 | drivers, docs; `clab-network-specialist` | yes |
| C11 | Editor upgrade to `@containerlab/clab-ui` 0.4.0: boxed and elbow styles, inheritance editor, kind tab, rotation, hide dummy links, wait-for arrows | R060 to R074 | blocked until npm publishes 0.4.0 | - |

Order of value against risk: C02 and C03 first (visible, read-only), then C05 (the headline upstream feature, mutating
helper), the rest as time allows; C10 when the router boots and the VM is quiet. Each chunk: a short design under this
folder, `/clab-design-review`, build in slices with the named agents, `/clab-slice-verify`, `/clab-review-changes`, a
live pass where the table says so, then the release step and a push.

## Status

See [PICKUP.md](PICKUP.md) "Log" for the dated record and the open items of the chunk in progress.
