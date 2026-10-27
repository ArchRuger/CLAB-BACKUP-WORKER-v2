# D03 report: device features and Network Design, 2026-10-27

Scope: `clab-backup-ui/NODE-FEATURES.md`, `docs/NETWORK-DESIGN.md`, `docs/DEBUG-PANEL.md` (re-check only). Static reading of the
code plus one offline call of `design_capabilities.resolve` in the local venv. No VM, browser or live-device check was run.

## Claim table

| # | Claim (guide) | Checked in | Result |
|---|---|---|---|
| 1 | Download types: cjunosevo, vJunos-switch, vJunos-router, vQFX `.cfg`, IOS-XR `.txt`, CEOS `.conf` (NODE-FEATURES) | `downloads.FORMATS` | vSRX (`vSRX`, `.cfg`) was missing: added |
| 2 | Serial console only for vJunos-switch, vJunos-router, XRv9k | `inventory.CONSOLE_PORTS` | correct; vSRX named as not offered, with the reason |
| 3 | SuperPuTTY fallback users: `clab` IOS-XR, `admin` cJunosEvolved and cEOS | `topology.py:325`, `DEFAULT_CREDENTIALS` | incomplete: every Junos kind falls back to `admin`; fixed |
| 4 | No kind table existed | `inventory.PLATFORMS/ALIASES`, `topology.PORT_RULES`, `restore_drivers.supported_kinds`, `catalog.py` | added "Device kinds" table (7 kinds: aliases, default login, backup, download name, port rule, restore, console) and `GET /api/catalog` |
| 5 | vJunos-router restore | `restore_junos.SUPPORTED_KINDS`, `inventory.py` comments, DEVICES.md | stated: driver proven on a nested derivative; published image needs bare-metal KVM |
| 6 | Timers: 25 s CLI check, 4 parallel bulk checks, 15 min starting grace, 8 consoles, 32 SSH, 15 min idle, 4 h, 2 min settle, 300 job records | `node_services.py` (`CLI_TIMEOUT`, `BULK_CHECK_WORKERS`, `CONSOLE_*`), `node_readiness.LOGIN_GRACE`, `runner.JOB_CAP` | all correct, unchanged |
| 7 | Credential order profile > inventory > kind default > image default (linux only) | `inventory.py` | correct, restated in the new table text |
| 8 | NETWORK-DESIGN: "lab's Design tab", heading "The Design tab" | `index.html` 198-205, `app.js:376`, `network-design.js` | wrong: the feature is Advanced › Experimental › Network design (closed `<details>`); no tab. Fixed in 4 places |
| 9 | Profile list in "Identity and endpoint mapping" | `design_capabilities.PROFILES` | vJunos-router (`vjunos-router`) and vSRX (`vsrx`) added, exact; port rule `eth1 = ge-0/0/0` for both |
| 10 | Validation levels vocabulary | `DESIGN_LEVEL_WORDS` in `network-design.js` | page words added; `VALIDATION` is empty (nothing reads `verified_on_image`) stated |
| 11 | "Refused per image": DHCP, VLANs, BFD, LAG, anycast (not XRv9k), STP, SRv6 | `resolve()` over all six kinds | stale for the new kinds: LAG/LACP also not on vJunos-router, anycast also not on vSRX, 6PE only cEOS and XRv9k; fixed |
| 12 | Apply available for cEOS, vJunos-switch, cJunosEvolved, XRv9k | `design_apply.DRIVERS`, `design_junos.SUPPORTED_KINDS/KIND_EVIDENCE` | drivers also list vJunos-router and vSRX ("live apply pending"); stated honestly, plus the vSRX preparer and zone-binding conflict rule |
| 13 | Generation facts: argv, 120 s, 20 generations, 512 KiB, review token 10 min, `networklab==26.9` | `design_engine`, `network_design`, `design_intent`, `design_apply.REVIEW_TTL`, `requirements.txt` | correct |
| 14 | Buttons: Generate plan, Save design, Discard changes, More (Download design file, Import design file…, Renumber, Remove design…), Check, Apply to devices…, Export plan to Git… | `index.html` | correct |
| 15 | Evidence and contract pointers (LEDGER, PROVISIONING, evidence/live-apply-*.md, DESIGN-CONTRACT.md) | file listing | all exist |
| 16 | DEBUG-PANEL: menu path, Failures only, Run checks, Download report, 200 requests, 90 s probe, rows Folder listing and VM commands | `index.html`, `debug.html`, `debug.js`, `diagnostics.py` | correct, no change |

## External URLs (HTTP status via curl, 2026-10-27)

| URL | Status |
|---|---|
| https://netlab.tools | 200 |
| https://github.com/srl-labs/network-multitool | 200 |
| https://xtermjs.org/docs/api/terminal/classes/terminal/ | 200 |
| https://containerlab.dev/manual/kinds/vr-vsrx/ | 200 |
| https://containerlab.dev/manual/kinds/vr-vjunosrouter/ | 200 |
| vscode-containerlab v0.24.0 `topology.ts`, containerlab `auto.tmpl`, superputty `SessionData.cs` (GitHub) | 200 each |

The vSRX default login text on containerlab.dev was not re-read in this pass (page reachable only); the value comes from the code comment
dated 2026-10-27 in `inventory.py`.

## Checks

- `python3 deploy/verify-release.py --docs`: exit 0 ("Documentation names only release 1.31.6.")
- `python3 docs/maintenance-audit/tools/check_links.py`: exit 0 (339 files, 0 problems)
- `git diff --check`: exit 0

## Left for the lead (outside my paths)

- `docs/GIT-PROGRESS.md:450` and `docs/ARCHITECTURE.md:171` still say "Design tab".
- `design_junos.py` header comment (line 1-6) still lists vJunos-router/vSRX as pending; fine, but the "four acceptance images" wording in NETWORK-DESIGN
  stays correct only until B05 phase 2.
