# UX audit of the current WebUI (1.28.0) — from the running app

Evidence: Playwright screenshots in `shots/before/` at 1920×1080, 1440×900, 1366×768 and text dumps in `audit-report.json`, `audit-rest.json`. Live labs: `clabllm-dev` (PTX1 cJunosEvolved + SW1 vJunos-switch) and `bgp-core` (2× cJunosEvolved).

## 1. Hierarchy — the map is below the fold, the admin chrome is above it
- At 1366×768 the topology is **entirely off screen**: page heading (eyebrow + h1 + subtitle + "Replace inventory"), deployment bar (6 buttons), metrics row, Git bar, tabs row and a 5-button action row consume the whole viewport. At 1920×1080 the first node appears at y≈960.
- The page has *four* stacked toolbars before content: deployment bar actions, Save-progress bar, tab strip actions, topology section actions, then map tools. 20+ buttons visible before the map.
- The metrics row ("Lab nodes / Selected for backup / Credentials ready / Backup schedule") is backup-worker heritage; none of it answers "is my lab ready".

## 2. Terminology exposes the implementation
- Deployment bar: "2/2 discovered containers running; 2 saved nodes. Container state does not verify NOS readiness." / "Last successful inspection" / "VM files: Updates available" / "NOS ready · 2/2 nodes accept SSH login".
- Git bar: "CLAB-MNGR-DEV-LLM › labs/BGP-LAB/work › latest/ · main" and "Saved to Git · 6749b89134 · 2026-09-16 14:59:15 UTC" (commit hash, branch, `latest/`).
- Git tab: "Verified push destination: https://…", "Branch main · VM account clabllm · /home/clabllm/labs/…", "Git authentication belongs to the repository owner on the VM", "Snapshot kept locally".
- Sidebar: "Refresh discovery", "Manual discovery", "Discovery file details", "VM connection", "View running lab details" (which opens a *confirmation* to run `containerlab inspect`).
- Node table: "Node / SSH endpoint", "Platform / credentials", "Last SSH check: reachable", "Containerlab default login", "Include in scheduled backups" checkbox.
- Buttons: "Test NOS login", "Back up now →", "Export sessions" (SuperPuTTY), "Replace inventory", "Update lab YAML", "Link deployment", "Sync from VM", "Import topology".
- Lab actions dialog: "Apply topology", "Inspect lab", "Save configurations (clab)", "Delete undeployed VM YAML", "Destroy deployment", "Redeploy + cleanup", plus the VM path of the YAML as the subtitle.
- Status badges use raw backend words: `reachable`, `succeeded`, `Running`, `synced`, `push pending`.

## 3. Primary student actions are hidden or de-emphasised
- **Open CLI**: the map says "Right-click a node for SSH, backups and capture" — the primary action is behind a right-click. The Nodes table has an "SSH ↗" button of equal weight with "Capture" and "Back up". Left-clicking a map node does nothing obvious (no drawer).
- **Readiness**: per-device readiness is a `reachable` badge under "Last SSH check" plus a green "NOS ready · 2/2 nodes accept SSH login" line — not a first-class state.
- **Save Progress** is reasonably prominent (blue bar) but sits under two other toolbars and its menu has 8 mixed items (Save locally, Save checkpoint…, Set baseline…, View changes / History, Load version…, Push saved progress, Update from remote, Git repository settings).
- **Load instructor/final state**: reachable via Save menu → Load version… → "Lab versions and Git history" dialog listing every folder in the repository as "<path> · latest" rows with the same commit hash. No notion of "Final state / Baseline / Checkpoint" at a glance.

## 4. Dangerous actions are over-exposed
- "Destroy lab" (red outline) sits directly beside the disabled "Start lab" in the deployment bar on every lab; "Remove lab" and "Replace inventory" (solid red primary) are also always visible.
- Lab actions dialog puts "Destroy deployment" and "Redeploy + cleanup" in the same list as "Favorite lab" and "Operation history".
- The destroy confirmation ("Destroy deployment?") shows the YAML path, cleanup directory, affected containers and the containerlab command — good detail for engineers, but does not say what happens to saved progress.

## 5. Confirmation and dialog overuse
- "View running lab details" opens a confirmation dialog ("Confirm to run this action on the VM") before a read-only inspect.
- Node details, Git settings, history, capture, operations, deploy browser and lab actions are all modal dialogs; "Deploy New Lab" replaces the whole page with a two-card landing (Lab Topologies / Operation history) and "← Back to lab manager".

## 6. Weak or missing states
- No landing page when labs exist: the first lab auto-selects; there is no "My Labs" overview with per-lab status cards.
- Lab status vocabulary is inconsistent across surfaces: sidebar shows "2 nodes · Running", bar shows "Running" + "NOS ready", worker pill shows "WORKER IDLE"/"SSH job in progress".
- Backup history is a flat list of 25+ "Configuration backup / NOS login test · automatic" cards; the student cannot tell which entries matter.
- Git history dialog shows commits with hashes and "Move clabllm-dev progress to labs/BGP-LAB/work/" messages.
- Capture dialog opened from the lab (not a node) shows an empty "Live Linux interfaces" box with "Choose a capture target under Advanced, or open Capture from a node on the map."

## 7. What already works well (keep)
- Deploy-first landing when no labs exist; discovery of running labs.
- Automatic readiness monitor with explanatory disabled-SSH tooltips ("NOS is still booting; SSH opens when it accepts a login").
- The Git folder browser ("Where this lab lives") with "Apply to running lab…" per folder.
- Restore review ("Replace running configuration") with mandatory pre-backup.
- Consistent `esc()` escaping, self-only CSP, no inline styles, `<dialog>` semantics with focus handling, visible focus rings.
- Node details drawer with configuration history downloads.
- Terminal page is clean and works (live SSH to PTX1 confirmed in the audit).
