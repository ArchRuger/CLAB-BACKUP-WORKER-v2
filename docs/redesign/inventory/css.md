# CSS / design-system inventory — clab-manager web UI

Source of truth (read completely, verified lossless):

- `/home/clabllm/projects/clab-manager/clab-backup-ui/app/static/style.css` — 44 994 bytes, 161 physical lines, 642 rule blocks, 12 `@media` blocks. Main stylesheet for `index.html`, `workspace.html`, `debug.html`, `capture-session.html`, `capture-setup.html`, `grafana.html`, `vm-connection.html` (all load `/static/style.css?v=1.28.0`).
- `/home/clabllm/projects/clab-manager/clab-backup-ui/app/static/terminal.css` — 1 465 bytes, 1 line. Only `terminal.html` loads it (after `vendor/xterm.css`). It does **not** load style.css; it is a fully separate dark theme.
- `/home/clabllm/projects/clab-manager/clab-backup-ui/app/static/vendor/xterm.css` — unmodified xterm.js default stylesheet (skimmed; no project rules inside).

Pretty-printed working copy (not in repo): `/tmp/claude-1000/-home-clabllm/58f9753c-3287-4bf9-9f68-d2da708ca22e/scratchpad/inventory/style.pretty.css`.

The file is written as a sequence of dated "patches": base system, then blocks with header comments (`/* The drawer preserves... */`, `/* Topology geometry... */`, `/* Lab-level command workspaces */`, `/* A single expandable lab topology tree. */`, `/* Explicit deployment navigation... */`, `/* Secondary workspace views... */`, `/* Save progress keeps the destination visible... */`, `/* Development diagnostics... */`, `/* Optional packet capture... */`, `/* 1.22.0: deploy-first landing page... */`, `/* Live configuration restore */`). Later blocks frequently **re-declare earlier selectors** to override them (see §14 Inconsistencies). Cascade order therefore matters: 19 selectors are defined two or three times.

---

## 1. Tokens

### 1.1 Custom properties on `:root`

| name | value | used for |
|---|---|---|
| `--ink` | `#1b303d` | body text, headings, `.node-name`, dialog text, `.git-destination`, `.git-crumbs [aria-current]`, `.git-outline summary`, `.git-listing .name`, `.git-saved-job`, `.empty-lab strong`, `.git-save-options button` |
| `--slate` | `#416377` | secondary UI colour: `.secondary` button text, `th`, `.eyebrow`, `.crumb strong`, `.worker-state` + its dot, `.profile-card` top border, checkbox `accent-color`, `.badge` default text (`#416377` literal), `.drawer-section h3`, `.node-details .device-download` left border, `.git-progress-bar` left border, `.git-folder-icon.managed`, `.git-crumbs button`, `.git-inline-action`, `.git-node-scope small`, `.restore-advanced summary`, `.capture-more summary`, `.workspace-back`, `.capture-viewer #viewer-status`, `.deployment-bar small`, `.empty-discovered h3`, `.file-icon` text, `.tag`, `.profile-card small` |
| `--rail` | `#182c38` | sidebar background, `.dark` button, `#toast` background, `.drawer-head` background, `.ssh-action` button background (table) / text (drawer), `.extra-views summary.active` colour |
| `--coral` | `#f15b40` | primary accent: `.primary` button bg, `.lab-item.active` left border, `.tabs button.active` underline, `.extra-views summary.active` underline, `.deployment-bar` left border, `.drawer-head` bottom border, `#login-dialog` top border, `.file-icon` top border, `.side-button.side-primary`, `.git-folder-icon.lab`, map hover stroke (literal `#f15b40`), `.diagram-selected` glow, `.workspace-choice-primary` border, `#diagram-discard` border |
| `--cyan` | `#79e8f6` | `#toast` left border, `.ssh-action` text (table) / bg (drawer), `.drawer-head .endpoint`, `.empty-panel::before` diagonal stripe (`#79e8f620`) |
| `--peach` | `#ffaa99` | **declared but never referenced in style.css** (terminal.css uses the literal `#ffaa99` for `#disconnect` text) |
| `--muted` | `#5e5e5e` | **declared but never referenced via `var()`**; literal `#5e5e5e` used by `.map-tools span` and `#map-status` |
| `--line` | `#dce2e3` | the standard 1px border/divider colour (topbar, `.metrics`, `.control-row`, `.table-wrap`, `th`, `.profile-card`, `.blank-state`, `.job`, `.job-body`, `.job-result`, footer, `.drawer-section`, `.node-details .device-download`, `.deployment-bar`, `.extra-views-menu`, `.git-repository-card/.git-binding-form/.git-saves`, `.git-places*`, `.git-outline`, `.restore-targets`, `.restore-target-row`, `.empty-discovered`, `.empty-lab`, `.platform-pills span`) |
| `--mono` | `Consolas,"Liberation Mono",monospace` | `code`, `.mono`, `.lab-item small`, `.side-bottom p`, `.worker-state`, `.metrics strong`, `.endpoint`, `.timestamp`, `.platform`, `.profile-card p`, `.job-title small`, `.job-result>small`, `.archive-download small`, `.tag`, `#log-status`, `.connection-result time`, `.node-details .device-download small`, `.git-setup-command`, `.git-file-content`, `.git-listing .size` |
| `--shadow` | `0 12px 40px #182c3814` | `#toast`, `.extra-views-menu`, `.git-save-options` |
| `--border` | **not defined** | referenced only as `var(--border,#d9e1e6)` in `.op-file-tree`; fallback always wins |

`:root` also sets `font-family:"Segoe UI",Arial,sans-serif; color:#1b303d; background:#f4f6f6; font-synthesis:none`.

### 1.2 Implicit (hard-coded) palette

The file uses ~170 distinct hex values; the recurring ones that act as de-facto tokens:

| literal | count | role |
|---|---|---|
| `#fff` / `white` | 26+ | card/dialog/table surfaces |
| `#687c86`, `#687a84`, `#687b85`, `#697a83`, `#6a7a83`, `#6b7c85`, `#6b7f89`, `#6c808b`, `#6e7e86`, `#677b86`, `#647985`, `#637d8b`, `#70828a`, `#4b5f6a` | 10/9/7/… | "muted text" grey — **14 near-identical greys** for captions, help text, timestamps |
| `#edf3f5` | 9 | hover background for menu items/list rows (`.node-actions button:hover`, `.extra-views-menu button:hover`, `.git-save-options button:hover`, `.op-tree-file:hover`, `.git-outline summary:hover`, `.git-saved-job:hover`), and `.git-setup-command`, `.git-destination-line code`, `.capture-guide pre` backgrounds |
| `#edf2f3` / `#edf2f4` / `#edf5f6` / `#e6eef1` / `#e9f0f3` / `#e3ecf0` | 1–2 each | table-head bg, default badge bg, context-menu hover, crumb hover, crumb current, outline selected |
| `#f8fafb`, `#fbfcfc`, `#f7fafb`, `#f6f9fa`, `#f6f9fb`, `#f5f8f9`, `#f3f8fa`, `#f3f6f7`, `#f4f6f6`, `#f0f5f6` | 1–4 each | tinted panel/hover surfaces |
| `#a9c0cb`, `#afc1ca`, `#a9c6d3`, `#c9d8df`, `#d9e6ec`, `#d3e3eb`, `#dceaf0`, `#e2edf2`, `#cbd8dd` | | sidebar/drawer light text on `--rail` |
| `#2a4352`, `#263e4b`, `#2a4555`, `#314d5d`, `#304652`, `#385363`, `#496271`, `#537180`, `#41637780`, `#41637720` | | sidebar/drawer hover & border tones |
| `#157d91` | 3 | focus ring colour, `.link-button` colour, `.capture-viewer-help summary` colour |
| `#c24a37` / `#a73122` / `#b43825` / `#a12d1b` / `#a13a26` / `#9c3622` | | destructive reds (`.button.danger`, `.danger-outline`, `.node-name:hover`, `.debug-failure`, `.git-tag`, `.workspace-choice-primary span:last-child`) |
| `#e0b3aa` | 2 | `.button.danger:disabled` |
| Border greys `#cdd6d9`, `#aebfc7`, `#bccbd1`, `#ccd8dc`, `#c4d4dc`, `#afc7d1`, `#d3dfe3`, `#b8ccd5`, `#c6d4db`, `#cacbca`, `#d9dfdf`, `#d6dfdf`, `#e5ebeb`, `#ccd6db`, `#dce3e7`, `#cbd6dc`, `#d6e0e5`, `#d9e1e6`, `#cbd8de`, `#c5d9dd`, `#c7d5dc`, `#d5e0e3`, `#d6e0e4`, `#ccdbe0`, `#dce4e8`, `#cbd5db`, `#ccd5dd`, `#dbe3e8`, `#9fb3bd`, `#8fb0be`, `#7d8f99`, `#e7ecee` | 1 each | **32 distinct border greys** besides `--line` |

Dark surfaces for code/output: `#172f3d` (`.op-output`), `#142d3a` (`.git-file-content`), `#152631` (`.vm-guide pre`, terminal body), `#263340` (`#capture-screen`), `#173848` (`.op-code` text), `#e1edf2`/`#e5eff4`/`#e7eff2` (light text on them).

### 1.3 Typography scale

- Base: `body 14px`, `:root` "Segoe UI", Arial. Headings `font-weight:650`, colour `--ink`, `margin:0`.
- `h1 30px / letter-spacing -.035em / overflow-wrap:anywhere` (25px ≤760); `h2 19px / -.025em`; `h3 15px`.
- Overrides: `dialog h2 25px`, `.drawer-head h2 27px`, `.empty-panel h2 24px` (21px ≤760), `.profile-card h3 17px`, `.operations-dialog h3 16px`, `.drawer-section h3 13px`, `.git-diff-columns h3 12px`, `.empty-discovered h3 11px uppercase .1em`, `.workspace-choice strong 24px`, `.op-banner strong 19px`, `.metrics strong 500 23px mono -.045em` (22px ≤760), `.brand` 23px→ later overridden to 18px (see inconsistencies).
- Small text sizes used: 7px (`.brand small` ≤1150), 8px (`.brand small`, `.worker-state` ≤760), 9px (`.eyebrow`, `.side-caption`, `.tag`, `.unmatched-label`), 10px (×19: `.side-label`, `.lab-item small`, `th`, `.secondary-text`, `.timestamp`, `.badge`, `.platform`, `.worker-state`, `.job-title small`, `.required/.muted`, `.upload-field small`, footer, `#log-status`, `.git-tag`, `.git-node-scope small`, `.empty-note`…), 11px (×23), 12px (×55, the workhorse), 13px (×13).
- `.eyebrow`: 9px, `.17em` tracking, 700, `--slate`, `margin:0 0 10px`. `.side-label`: 10px, `.14em`, 600. `.side-caption`: 9px `.14em`.
- `p { line-height:1.65 }`, `small { font-size:12px }`, `code { font-size:.9em }`.
- Mono font applied through `var(--mono)`; **two other mono stacks** also appear: `ui-monospace,monospace` (`.op-path`, `.op-output`, `.op-code`) and `Consolas,monospace` (terminal.css). `#topology-map` forces `font-family:Arial,sans-serif`.

### 1.4 Radii, shadows, z-index, motion

- Radii used: 4px ×17 (buttons, inputs, lab-item, toast, pills), 5px ×8 (cards/table-wrap/job/metrics), 6px ×8 (dialogs, git cards, restore), 8px ×10 (ops sections, code blocks, op-banner, capture fieldsets), 10px ×3 (context menu, op sections, file tree), 12px ×3 (`#topology-map`, `.workspace-choice`, `.debug-card`), 14px (`.operations-dialog`), 16px (`.map-expanded`), 7px (`.map-tools button`), 3px ×5 (badges, tags, pills), 2px (git icons), 50% (dots), `0` (drawer).
- Shadows: `--shadow`; dialog `0 24px 80px #142c3830`; drawer `-12px 0 60px #142c3820`; context menu `0 12px 32px #18333d30,0 2px 8px #18333d20`; `.map-expanded` `0 0 0 30px #203b49aa` (ring acts as backdrop); `.workspace-choice:hover` `0 5px 18px #19334015`.
- z-index ladder: `.drawer-head` 1 (sticky inside drawer) · `.extra-views-menu` 12 · `.git-save-options` 20 · `#toast` 30 · `.map-expanded` 50 · `.node-context-menu` 100. (Native `<dialog>` top layer sits above all of these.)
- Transitions: `button,input,select { transition:background .15s,border-color .15s }`; `.git-outline summary::before { transition:transform .12s }`. `@media(prefers-reduced-motion:reduce){*{transition:none!important;animation:none!important}}`.

---

## 2. Base / reset rules

- `*{box-sizing:border-box}`; `body{margin:0;font-size:14px}`.
- `button,input,select{font:inherit}`; `button{cursor:pointer}`; `button:disabled{cursor:not-allowed;opacity:.45}` (global disabled look).
- `[hidden]{display:none!important}` — **all JS `el.hidden = …` toggles rely on this**; redeclared for `.node-context-menu[hidden]` and `.capture-dialog [hidden]`.
- `input,select` base: `min-width:0;max-width:100%;min-height:38px;padding:9px 11px;border:1px solid #bccbd1;border-radius:4px;background:#fff;color:var(--ink);font-size:13px`. `input[type=search]{width:240px}` (100% ≤760). `input[type=checkbox]{width:15px;height:15px;min-height:15px;accent-color:var(--slate)}`.
- `summary{cursor:pointer}`; `details:not(.job){margin-top:20px;font-size:12px}` (affects every `<details>` not marked `.job`, including sidebar `#discovery-files`, `.extra-views`, `.git-save-menu` — the latter two are reset by `.tabs .extra-views{margin-top:0}` and `.git-save-control .git-save-menu{margin:0}`).
- `.sr-only` visually-hidden utility. `.mono` utility. `code,.mono{font-family:var(--mono)}`.

---

## 3. Layout

- **App shell** (`index.html`): `.workspace{display:grid;grid-template-columns:232px minmax(0,1fr);min-height:100vh}` → `aside.sidebar` + `main`. `main` has no rule of its own.
- **Sidebar**: `position:sticky;top:0;height:100vh;display:flex;flex-direction:column;background:var(--rail);color:#fff;padding:32px 18px 24px;border-right:1px solid #304652;` later patch adds `overflow-y:auto`. `.sidebar nav{overflow:auto;min-height:50px}` later overridden to `flex:none;max-height:260px;overflow:auto` (lab list is capped at 260px tall). `.side-bottom{margin-top:auto;padding:40px 12px 0}` later overridden to `margin-top:24px` (no longer pushed to the bottom).
- **Topbar**: `.topbar{height:62px;padding:0 36px;display:flex;justify-content:space-between;align-items:center;gap:20px;border-bottom:1px solid var(--line);background:#fff}`.
- **Content**: `.content{max-width:1560px;margin:auto;padding:34px 36px 24px}`; `min-width:1550px` → `padding-top:42px` and `td` vertical padding 24px.
- **Page heading**: `.page-heading{display:flex;align-items:center;justify-content:space-between;gap:24px;margin-bottom:27px}`.
- **Control row** (tabs + action buttons): `.control-row{display:flex;justify-content:space-between;align-items:center;gap:18px;border-bottom:1px solid var(--line);margin-bottom:26px}` + later `flex-wrap:wrap`; `.control-row>.actions{flex-wrap:wrap}`.
- **Section heading**: `.section-heading{display:flex;align-items:center;justify-content:space-between;gap:20px;margin-bottom:17px}`; `.section-heading p{font-size:11px;color:#6e7e86;margin:6px 0 0}`; `#topology-view .section-heading{flex-wrap:wrap;gap:12px}` and its `.actions{flex-wrap:wrap}`.
- **Footer**: flex space-between, `margin-top:30px;padding-top:15px;border-top:1px solid var(--line);font-size:10px;color:#6c808b` (column ≤760).
- **Standalone pages** (`workspace.html`, `debug.html`): `body.standalone-workspace{background:#f3f6f7}`; `.standalone-workspace main{max-width:1200px;margin:28px auto}`; `.standalone-workspace .actions{margin-bottom:22px}`; `.debug-page{max-width:1400px;margin:auto}`.
- **Guide pages**: `.vm-guide{max-width:1000px;margin:30px auto;padding:25px}` (+ `h2{margin-top:36px}`, `p{margin:5px 0;line-height:1.6}`, `pre` dark block), `.capture-guide{max-width:900px;margin:40px auto;padding:24px;line-height:1.65}` (+ `h2{margin-top:28px}`, `pre{background:#edf3f5;border-radius:8px;padding:18px}`). Used by `capture-setup.html` and `grafana.html`.
- **Capture viewer** (`capture-session.html`): `body.capture-viewer{height:100vh;display:flex;flex-direction:column;overflow:hidden;margin:0}`; toolbar; `#capture-screen{flex:1;min-height:0;background:#263340;overflow:hidden}`.
- **Terminal page** (`terminal.html`): `body{display:flex;flex-direction:column;height:100vh;overflow:hidden}`; `header` + `.notice` + `#terminal{flex:1;min-height:0;margin:12px 24px 20px;overflow:hidden}`.

### 3.1 Breakpoints (all in style.css unless noted)

| query | what changes |
|---|---|
| `min-width:1550px` | `.content{padding-top:42px}`; `td{padding-top/bottom:24px}` |
| `max-width:1150px` | sidebar column 205px; `.brand` 21px/padding 0; `.brand small` 7px; `.brandmark` 34px; `.content{padding:27px 24px}`; `.topbar{padding:0 24px}`; `.metrics>div{display:block;padding:17px}` + `strong{display:block;margin-top:10px}`; `.control-row{flex-wrap:wrap;gap:0}`; `.actions{padding-top:10px}`; `.profile-grid` 2 cols; `td,th` side padding 12px; `.node-actions{min-width:170px;gap:4px}`, its buttons `padding:6px 8px`, `.details-action` 10px; `.timestamp` 10px |
| `max-width:900px` | `.git-places-body` 1 col; `.git-outline{border-right:0;border-bottom:1px solid var(--line);max-height:220px}` |
| `max-width:850px` | `.op-sections`, `.op-coordinates`, `.op-file-list` 1 col; `.operations-dialog{padding:18px}` |
| `max-width:800px` | `.debug-grid` 1 col; `.debug-input` column/stretch; `.debug-page .section-heading` column |
| `max-width:760px` (×5 blocks) | `.workspace{display:block}`; sidebar becomes `position:relative;height:auto;padding:18px;display:block`; `.brand{margin:0 0 18px}`; `.side-label{padding:0;margin-bottom:8px}`; `.side-bottom{padding:15px 0 0;margin:0}` and hides `.side-caption`, `p`, `small` inside it; `.side-bottom .text-button{margin:0}`; `.sidebar nav{display:flex;gap:8px;overflow:auto;max-height:none}` (horizontal lab strip); `.lab-item{width:auto;min-width:170px;max-width:260px;margin:0}`; `.side-button{margin:12px 0 0;width:100%}`; `.topbar{padding:0 18px;height:52px}`; `.content{padding:24px 18px}`; `.page-heading` column/flex-start gap 18; `h1 25px`; `.metrics` 2 cols with `nth-child(2){border-right:0}` and `nth-child(-n+2){border-bottom}`; `.metrics strong 22px`; `.tabs{gap:20px;overflow:auto;width:100%}` then later `flex-wrap:wrap;overflow:visible`; `.tabs button{white-space:nowrap;font-size:11px}`; `.actions{width:100%;padding:14px 0}` + `.actions .button{flex:1}`; `.section-heading` column; `input[type=search]{width:100%}`; `.profile-grid` 1 col; `.table-wrap table{min-width:730px}` (horizontal scroll); `.schedule-form{justify-content:flex-start}`; `.job summary{flex-wrap:wrap}`; `.form-grid` 1 col, `.form-grid.wide` `2fr 1fr`; footer column gap 8; `.job-result` 1 col; `dialog{padding:22px}`; `.drawer-head{padding:20px}`; `.drawer-content{padding:0 20px}`; `.health-grid{grid-template-columns:105px minmax(0,1fr);gap:13px}`; `.worker-state 8px`; `.empty-panel h2 21px`; `.deployment-bar` column/flex-start + `.actions{padding:0}`; `.side-bottom{margin-top:0}`; `.extra-views summary 11px`; `.diagram-workspace` 1 col; `.diagram-properties{max-height:none}`; `.diagram-workspace .op-layout-map{height:45vh}`; `.op-inspection th{white-space:normal}`; `.op-inspection td{min-width:80px}`; `.map-tools #map-edit{margin-left:0}`; `.git-progress-bar` column/stretch gap 14 padding 16; `.git-save-control{align-self:flex-end}`; `.git-save-options{width:min(260px,calc(100vw - 65px))}`; `.git-diff-columns` 1 col; git cards padding 16; `.git-node-scope` 1 col; `.git-repository-card .actions{width:auto}` + `.button{white-space:normal}`; `.git-node-scope .checkbox-label span{overflow-wrap:anywhere}`; `#git-version-dialog .actions{flex-wrap:wrap}` + `.button{white-space:normal}` |
| `max-width:720px` | `.workspace-choices` 1 col; `.workspace-choice{padding:22px;min-height:140px}` |
| `max-width:700px` (terminal.css) | `header{padding:16px}`; `.session-controls{width:100%}`; `.notice{padding:0 16px}`; `#terminal{margin:10px 16px 16px}` |
| `prefers-reduced-motion:reduce` | kills all transitions/animations |

No `prefers-color-scheme` handling anywhere; the app is light-only (terminal page is dark-only).

---

## 4. Sidebar components

| selector | role / notes |
|---|---|
| `.brand` | flex row, gap 12, `padding:0 9px;margin-bottom:48px;font-size:23px;font-weight:650;letter-spacing:-.04em`; **overridden later** to `font-size:18px;line-height:1.25` |
| `.brandmark` | 40×40 `flex:none`; overridden later to `width:34px` (height stays 40) |
| `.brand small` | block, `#a9c0cb`, 8px, `.17em`, 500, `margin-top:6px` (redeclared identically later) |
| `.side-label` | flex space-between, `padding:0 12px;margin-bottom:12px;color:#a9c0cb;font-size:10px;font-weight:600;letter-spacing:.14em` |
| `.sidebar nav` (`#labs`) | scrollable list, capped 260px (see §3) |
| `.lab-item` | full-width button: `padding:13px 14px;margin:3px 0;border:1px solid transparent;border-left:3px solid transparent;border-radius:4px;color:#c9d8df;font-size:13px;overflow-wrap:anywhere`; `:hover{background:#263e4b}`; `.active{background:#2a4352;border-color:#385363;border-left-color:var(--coral);color:#fff}`; `small{display:block;margin-top:6px;color:#a9c0cb;font:10px var(--mono)}`. Rendered by app.js with `data-lab`, `★ ` prefix for favourites, `.active` when `l.id===activeId` |
| `.side-hint` | `color:#afc1ca;padding:0 12px;font-size:13px` — used for `#operation-summary`, `#vm-summary` (role=status), empty nav hint |
| `.side-button` | `margin:17px 8px 0;padding:11px 12px;text-align:left;border:1px solid #496271;border-radius:4px;background:transparent;color:#d9e6ec;font-size:12px`; `:hover{background:#2a4352}`; `small{display:block;margin-top:5px;opacity:.8}` |
| `.side-button.side-primary` | `background:var(--coral);color:#152f3e;border-color:var(--coral);font-weight:700;min-height:54px` — "Deploy New Lab" |
| `.side-bottom` | `color:#a9c0cb`; `p{font:12px var(--mono);color:#d3e3eb;margin:13px 0 8px}`; `small{font-size:10px}`; `.text-button{margin-top:24px;color:#dceaf0}` |
| `.side-caption` | 9px `.14em`, later `line-height:1.5` |
| `.text-button` | `display:block;border:0;background:none;color:inherit;padding:0;font-size:12px`; `:hover{text-decoration:underline}` — used for "Debug panel" link, "Manager settings", `#git-open-settings` |
| `.icon-button` | `border:0;background:transparent;color:inherit;font-size:24px;min-width:32px;min-height:32px;border-radius:4px`; `:hover{background:#41637720}`; `.sidebar .icon-button:hover` and `.drawer-head .icon-button:hover` → `#41637780` |
| `#discovery-files` | `font-size:12px;margin:12px 0;color:#cbd8dd`; `summary{cursor:pointer}`; `#discovery-file-list p{overflow-wrap:anywhere;margin:10px 0}`, `small{display:block;font-size:10px;opacity:.8;margin-top:4px}` |
| `#vm-summary`, `#vm-fingerprint`, `#remove-lab-name` | `overflow-wrap:anywhere` (`#remove-lab-name` also `font-weight:700`) |

---

## 5. Topbar & heading

- `.crumb{display:flex;gap:13px;align-items:center;color:#677b86;font-size:12px;min-width:0}`; `strong{color:var(--slate);font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}`; `span{color:#9eacb3}` (the "/" separator).
- `.worker-state{font:10px var(--mono);color:var(--slate);text-transform:uppercase;letter-spacing:.04em;white-space:nowrap}` with `::before` 6px dot in `--slate`. Text values written by app.js: "Worker idle", "SSH job in progress", "Saving lab progress". **The dot colour never changes with state.**
- `.eyebrow`, `.subtitle{font-size:13px;color:#687a84;margin:10px 0 0}`, `.section-description{font-size:12px;color:#687a84;margin:8px 0 16px}`, `.notice{font-size:11px;line-height:1.7;color:#687c86;padding:15px 0}`.

---

## 6. Buttons (every family)

| selector | style | where |
|---|---|---|
| `.button` | `inline-flex;center;gap:8px;min-height:38px;padding:9px 14px;border:1px solid transparent;border-radius:4px;font-size:12px;font-weight:600;white-space:nowrap` | base for all `.button.*`; also applied to `<a>` (`#grafana-open`, `#capture-launch`, `#capture-download`) and to `<summary>` (`.git-save-menu>summary`) |
| `.primary` | `background:var(--coral);border-color:var(--coral);color:#251a17`; hover `#ef715a` | note: **`.primary`/`.secondary` are not scoped to `.button`** — any element with class `primary` gets it |
| `.secondary` | `background:white;border-color:#cdd6d9;color:var(--slate)`; hover `background:#f0f5f6;border-color:#aebfc7` | most actions |
| `.dark` | `background:var(--rail);color:white` | **unused in any HTML/JS** |
| `.full` | `width:100%` | **unused** |
| `.button.danger-outline` | `background:white;border:1px solid #c24a37;color:#a73122`; `:hover:not(:disabled){background:#fff0eb}` | `#lab-destroy`, diagram-editor buttons |
| `.button.danger` | `background:#c24a37;border:1px solid #a73122;color:#fff`; hover `#a73122`; `:disabled{background:#e0b3aa;border-color:#e0b3aa;color:#fff}` (overrides only colours; global `opacity:.45` still applies) | restore "Apply", git delete, `#capture-end` |
| `.icon-button` | see §4; `.icon-button.close` (× in dialog heads) — `.close` has no CSS, it is the JS hook (`querySelectorAll('.close')` → `closest('dialog').close()`) |
| `.text-button` | see §4; `.text-button.git-destination` (`text-align:left;font-size:13px;line-height:1.6;overflow-wrap:anywhere;color:var(--ink)`), `.text-button.git-inline-action` (`display:inline;color:var(--slate);font-weight:600;text-decoration:underline`) | |
| `.link-button` | `border:0;background:none;padding:0;color:#157d91;font:inherit;text-decoration:underline;cursor:pointer` | empty-panel "Import a lab definition" / "Import an Ansible inventory" |
| `.node-name` | text button: `border:0;background:none;padding:0;color:var(--ink);font-size:14px;font-weight:650;max-width:340px;text-align:left;overflow-wrap:anywhere`; hover `color:#b43825;underline` | node table |
| `.node-actions button` | `inline-flex;gap:8px;padding:7px 10px;border:1px solid #ccd8dc;border-radius:4px;background:#fff;color:var(--slate);font-size:11px;font-weight:600;min-height:32px`; hover `#edf3f5` | row actions (`data-terminal`, `data-backup`, `data-check`, `data-edit`, `data-details`, `data-capture` per app.js hooks) |
| `.node-actions .ssh-action` | `background:var(--rail);border-color:var(--rail);color:var(--cyan)`; hover `#2a4555` | SSH button |
| `.node-actions .details-action` | `border-color:transparent;background:transparent;padding-right:0` (10px ≤1150) | "Details" |
| `.drawer-actions button` | `border-color:#537180;background:transparent;color:#e2edf2`; hover `#314d5d`; `.ssh-action{background:var(--cyan);border-color:var(--cyan);color:var(--rail)}` hover `#a3eff8` | `#details-actions` (`class="node-actions drawer-actions"`) |
| `.tabs button` | `padding:14px 0;border:0;border-bottom:2px solid transparent;background:transparent;font-size:12px;font-weight:600;color:#647985`; `.active{border-bottom-color:var(--coral);color:var(--ink)}`; hover `--ink` | `[data-tab]` |
| `.extra-views summary` | `padding:19px 0` → later `14px 0`; `font-size:inherit` (→ 12px/600 via `.tabs .extra-views`); `color:var(--slate);border-bottom:2px solid transparent;list-style:none`; `::after{content:' ▾'}`; `.active{border-color:var(--coral);color:var(--rail)}` | "More" menu |
| `.tabs .extra-views-menu button` | `display:block;width:100%;text-align:left;padding:12px;border:0`; hover `#edf3f5` | Credentials / Action logs |
| `.map-tools button` | `padding:8px 14px;border:1px solid #cacbca;border-radius:7px;background:white;color:#416377` (no `.button` class, no min-height, no font-weight) | Expand/Fit/+/- ; `#map-edit` is `.button.secondary` **and** inside `.map-tools` so gets both; `margin-left:auto` (0 ≤760) |
| `.node-context-menu button` | `width:100%;flex;gap:12px;text-align:left;border:0;background:transparent;border-radius:5px;padding:13px 12px;color:#294555;font-size:13px`; `:hover,:focus{background:#edf5f6;outline:none}`; `:disabled{opacity:.4;cursor:default}`; `small{margin-left:auto;font-size:10px;color:#70828a}`; `span{width:18px;color:#416377;font-size:17px}` (icon slot) | right-click node menu |
| `.git-save-options button` | `display:block;width:100%;background:none;border:0;border-radius:3px;text-align:left;padding:12px;font-size:12px;color:var(--ink)`; `:hover:not(:disabled){background:#edf3f5}` | `[data-git-action]` |
| `.git-crumbs button` | `border:0;background:transparent;padding:6px 8px;border-radius:4px;color:var(--slate);font-size:12px;font-weight:600;overflow-wrap:anywhere`; hover `#e6eef1`; `[aria-current=page]{color:var(--ink);background:#e9f0f3}` | folder breadcrumbs |
| `.op-grid button`, `.op-history button`, `.op-file-list button` | `.button` variants with `height:auto;min-height:43px/42px;text-align:left;white-space:normal` (+`overflow-wrap:anywhere`) | operations dialog |
| `.op-tree-file` | `display:block;width:100%;text-align:left;background:transparent;border:0;padding:10px 8px;color:inherit;overflow-wrap:anywhere;cursor:pointer`; hover `#edf3f5` | file tree leaf ("◇ name") |
| `.git-saved-job` | column flex, gap 7, `border:1px solid #d6e0e4;border-radius:4px;background:#f8fafb;color:var(--ink);padding:15px;font-size:12px;overflow-wrap:anywhere`; hover `#edf3f5`; `span{font-size:11px;color:var(--slate)}` | saved-version list item (`data-git-job`) |
| `.workspace-choice` | big card button: column flex, gap 16, `padding:30px;border:1px solid #cbd8de;border-radius:12px;background:white;color:#193340;font:inherit;min-height:180px`; `strong 24px`; `span{line-height:1.6}`; hover shadow; `:focus-visible{outline:3px solid #416377;outline-offset:4px}`; `.workspace-choice-primary{border:2px solid #f15b40;background:#fff7f4}` + `span:last-child{color:#9c3622;font-weight:700}` | workspace.html |
| `.empty-lab .button` | `flex:0 0 auto` | "Already running on the VM" rows |
| terminal.css `button,input` | `padding:9px 12px;border:1px solid #587789;border-radius:4px;background:#223e4e;color:#e7eff2;font:12px "Segoe UI"`; hover `#345565`; `:disabled{opacity:.45;cursor:default}`; `#disconnect{border-color:#f15b40;color:#ffaa99;background:transparent}` | terminal page |

Layout helpers for button groups: `.actions{display:flex;gap:8px;padding-bottom:12px}` (many context overrides: `.deployment-bar .actions{flex-wrap:wrap;max-width:520px}`, `.git-repository-card .actions{padding:8px 0 0;flex-wrap:wrap}`, `.git-binding-form>.actions{padding:18px 0 0}`, `.git-places-head .actions{padding:0}`, `.actions.git-blank-actions{justify-content:center;padding:6px 0 16px}`, `.standalone-workspace .actions{margin-bottom:22px}`), `.dialog-actions{display:flex;justify-content:flex-end;gap:10px;margin-top:24px}` (wrap in `.capture-dialog`, `#op-layout-editor`), `.empty-actions{center;gap:12px;wrap;margin-top:8px}`, `.diagram-toolbar{flex;gap:8px;wrap;margin:18px 0}`.

---

## 7. Forms

- Base `input,select` (§2). `dialog input:not([type=checkbox]),dialog select{width:100%}`.
- `dialog label:not(.checkbox-label){display:block;font-size:12px;font-weight:600;margin:18px 0 8px}` (same pattern duplicated as `.git-binding-form>label:not(.checkbox-label)` with `margin:20px 0 8px`).
- `.form-grid{grid;1fr 1fr;gap:15px}`; `.form-grid.wide{3fr 1fr}` (`2fr 1fr` ≤760; 1 col for plain ≤760).
- `.checkbox-label{display:flex;gap:10px;align-items:center;margin-top:20px;font-size:12px;line-height:1.5}`; `.git-node-scope .checkbox-label{margin:0}`; `.git-binding-form .checkbox-label{align-items:flex-start}` + `input{flex-shrink:0;margin-top:2px}`; `.restore-target` (a `.checkbox-label`) `align-items:flex-start;gap:9px;padding:6px 4px`.
- `.form-error{color:#a13135!important;white-space:pre-wrap}` + `:empty{display:none}` — every form has `<p class="form-error" role="alert">`; JS writes `textContent`.
- `.form-help{font-size:11px!important}` (help paragraphs; `#git-job-actions .form-help{width:100%;margin:8px 0}`).
- `.required,.muted{font-size:10px;font-weight:400;color:#687c86;margin-left:5px}`.
- `.upload-field{padding:16px;border:1px dashed #afc7d1;background:#f3f8fa;border-radius:4px}`; inner `input{border:0;background:none;font-size:12px;padding:0;min-height:30px}`; `small` 10px block.
- `.schedule-form{flex;wrap;center;gap:8px;font-size:12px}`; `input{width:80px}`; `small 10px #687b85`.
- `.log-filters{flex;gap:12px;wrap;align-items:end;margin:16px 0}`; `label{display:grid;gap:6px;font-size:11px}`.
- `.capture-controls{flex;gap:16px;align-items:end;wrap}`; `label{flex:1}`. `.capture-interfaces{grid;auto-fill minmax(145px,1fr);gap:8px;max-height:240px;overflow:auto}`; `.capture-interface{flex;center;gap:8px;overflow-wrap:anywhere;margin:0;min-height:34px}`; `input{width:auto}`. `.capture-dialog fieldset{border:1px solid #cbd5db;border-radius:8px;padding:14px;margin-top:16px}`.
- `.diagram-properties label{display:grid;gap:5px;font-size:12px;margin-bottom:10px}`; inputs/select/textarea `width:100%;min-width:0;padding:7px`; `input[type=color]{height:35px;padding:3px}`; `fieldset{border:0;padding:0;margin:0}`; `legend 12px`; `.diagram-fields{grid 1fr 1fr;gap:8px}`; `textarea{resize:vertical}`.
- `.op-coordinates{grid 3 cols;gap:12px}`; `label{grid 1fr 80px 80px;center;gap:6px;font-size:12px}`; `input{width:100%;padding:8px}`.
- `.git-node-scope` fieldset: `border:1px solid #d5e0e3;border-radius:5px;grid auto-fit minmax(180px,1fr);gap:10px 18px;padding:12px 16px 16px;margin:20px 0 12px`; `legend{font-size:12px;font-weight:600;padding:0 5px}`; `small{display:block;color:var(--slate);font-size:10px}`; `input{flex-shrink:0}`.
- `.git-binding-form>select{width:100%}`; `.git-binding-form .op-path{font-size:11px}`.
- `.restore-targets` fieldset: `border:1px solid var(--line);border-radius:6px;padding:12px 14px;margin:14px 0`; `legend{font-size:11px;font-weight:700;letter-spacing:.04em;color:#687a84;padding:0 6px}`; `.restore-advanced input{width:90px;margin:6px 0}`.
- `.debug-input{flex;gap:12px;center}` + `input{flex:1;min-width:0}`.

---

## 8. Metrics, tabs, tables

- `.metrics{grid repeat(4,1fr);background:#fff;border:1px solid var(--line);border-radius:5px;margin-bottom:25px}`; cells `flex space-between;gap:12px;padding:20px;border-right:1px solid var(--line)` (last child no border); `span 11px #697a83`; `strong{font:500 23px var(--mono);letter-spacing:-.045em}`.
- `.tabs{display:flex;gap:25px;align-self:stretch}` → later `overflow:visible`; `.extra-views{position:relative;align-self:stretch}`; `.extra-views-menu{position:absolute;top:100%;right:0;min-width:170px;padding:8px;background:white;border:1px solid var(--line);box-shadow:var(--shadow);z-index:12}`.
- `.table-wrap{background:white;border:1px solid var(--line);border-radius:5px;overflow:auto}`; `#logs-view .table-wrap{max-height:65vh}`.
- `table{width:100%;border-collapse:collapse;text-align:left}`; `th{padding:14px 16px;background:#edf2f3;color:var(--slate);font-size:10px;letter-spacing:.03em;font-weight:600;white-space:nowrap;border-bottom:1px solid var(--line)}`; `td{padding:20px 16px;font-size:12px;vertical-align:middle;border-bottom:1px solid #e7ecee}`; `tr:last-child td{border-bottom:0}`.
- Node table: `#nodes tr:hover{background:#f8fafb}`; `#nodes td:first-child{width:35px;padding-right:0}` (checkbox column); `.endpoint{display:block;color:#637d8b;font:11px var(--mono);margin-top:7px;overflow-wrap:anywhere}`; `.secondary-text{display:block;color:#6a7a83;font-size:10px;margin-top:8px}`; `.timestamp{display:block;font:10px var(--mono);color:#687c86;margin-top:8px;white-space:nowrap}`; `.status-neutral{color:#6b7c85;font-size:11px}` ("Not checked", "No backup yet"); `.node-actions{flex;wrap;gap:6px;center;min-width:205px}`; `.table-empty{text-align:center;color:#687b85;padding:40px}`.
- Logs table: `#log-rows td{vertical-align:top;font-size:11px}`; `.log-message{white-space:pre-wrap;overflow-wrap:anywhere;min-width:240px}`; `#log-status{font:10px var(--mono);color:#687c86}`.
- Inspection table (`.op-inspection`): `overflow:auto;max-height:60vh`; table `width:100%;min-width:850px` → later `table-layout:auto;min-width:0`; `td{white-space:normal;overflow-wrap:anywhere;max-width:240px;vertical-align:top}` → later `max-width:none;word-break:normal;min-width:100px`; `th{white-space:nowrap}`; per-column widths `td:nth-child(1..6)` = 21%/150–320px, 12%, 22%/180px, 20%/180px, 10%, 15%/160px; `small{display:block;margin-top:5px}`; `caption{text-align:left;padding:12px 0}`.
- Git listing (`.git-listing`): `overflow:auto;max-height:420px`; `th{padding:10px 14px}`; `td{padding:11px 14px;font-size:12px}`; `tr.folder{cursor:pointer}` hover `#f6f9fa`; `.name{flex;center;gap:8px;font-weight:600;color:var(--ink);overflow-wrap:anywhere}`; `.desc{color:#687a84}`; `.size{font:11px var(--mono);color:#687a84;white-space:nowrap}`.
- `.debug-page td, .debug-page code{overflow-wrap:anywhere}`.

---

## 9. Badges, tags, pills

| selector | style | meaning |
|---|---|---|
| `.badge` | `font-size:10px;inline-flex;center;gap:5px;padding:4px 7px;border-radius:3px;background:#edf2f4;color:#416377;white-space:nowrap`; `.badge:not(.platform)::before` 4px dot in `currentColor` | neutral status |
| `.badge.good` | `#e9f3ed` / `#256447` | success: app.js statuses `Ready`, `succeeded`, `reachable`; restore `succeeded/verified/applied`; git `synced/unchanged` |
| `.badge.bad` | `#fcebea` / `#a13135` | failure: `failed`, `unreachable`, `interrupted`; restore `failed/preflight_failed/rollback_expected`; git `failed/capture_incomplete` |
| `.badge.warn` | `#fff3de` / `#805510` | fallback for any other status |
| `.badge.running` | `#e5f6f9` / `#126575` | in progress: `queued`, `running`; restore active; git `queued/capturing/exporting/pushing` |
| `.badge.platform` (`.platform`) | `border:1px solid #dce5e9;background:#f5f8f9;font:10px var(--mono)`, no dot | NOS platform label |
| `.git-job-summary .badge` | 12px | larger in job summary |
| `.git-diff-file .badge` | `margin-left:8px`; plain `.badge` with text `file.status||'changed'` | diff file status |
| `.tag` | `font:9px var(--mono);color:var(--slate);border:1px solid #c6d4db;padding:5px 7px;border-radius:3px` | dialog-head tag |
| `.git-tag` | `font-size:10px;font-weight:600;padding:3px 6px;border-radius:3px;background:#fde9e4;color:#a13a26;white-space:nowrap` | "This lab (saves here)" |
| `.git-tag.other` | `#edf2f4` / `#416377` | another lab's folder / "Lab folder · not connected" |
| `.git-tag.pending` | `#fff3de` / `#805510` | "created on first save" |
| `.platform-pills span` | `font:10px var(--mono);border:1px solid var(--line);padding:6px 10px;border-radius:3px` | Junos / IOS-XR / Arista EOS pills on empty panel |

---

## 10. Cards & panels

- `.profile-grid{grid repeat(3,minmax(0,1fr));gap:16px}` (2 ≤1150, 1 ≤760). `.profile-card{background:#fff;border:1px solid var(--line);border-top:2px solid var(--slate);border-radius:4px;padding:23px}`; `h3{17px;margin:18px 0 7px;overflow-wrap:anywhere}`; `p{font:12px var(--mono);color:#647985;margin:0}`; `.profile-type{display:block;margin:25px 0 9px;color:#687b85;font-size:11px}`; `small{10px;--slate}`.
- `.blank-state,.empty-panel{background:#fff;border:1px solid var(--line);border-radius:5px;text-align:center;padding:50px 24px;color:#687c86;grid-column:1/-1}`; `.blank-state p 13px`.
- `.empty-panel` (`#empty`): `position:relative;overflow:hidden;padding:65px 24px`; `::before` decorative diagonal stripes gradient (`#79e8f620`, `#41637718`); `h2 24px`; `p{max-width:540px;margin:16px auto 24px;13px}`; `.file-icon{60×65;margin:0 auto 26px;border:1px solid #c4d4dc;border-top:3px solid var(--coral);border-radius:4px;flex center;font:12px var(--mono);color:var(--slate)}` ("LAB"); `.platform-pills{flex center;gap:9px;margin-top:27px}`; `.empty-note{font-size:10px;margin-bottom:0}`; `.empty-actions`; `.empty-vm-note{font-size:12px;color:#805510;margin:14px auto 0!important;max-width:520px}` + `:empty{display:none}`; `.empty-discovered{max-width:560px;margin:28px auto 0;text-align:left;border:1px solid var(--line);border-radius:6px;padding:14px 18px 6px;background:#fbfcfc}`; `.empty-lab{flex space-between;gap:16px;padding:10px 0;border-top:1px solid var(--line)}` (first no border); `strong --ink`; `small{block;#687c86;11px;margin-top:4px}`.
- `.deployment-bar{flex space-between;gap:20px;padding:18px 22px;margin-bottom:22px;border:1px solid var(--line);border-left:3px solid var(--coral);background:#fff;border-radius:5px}` + later `flex-wrap:wrap`; `p{margin:5px 0;12px}`; `small{--slate;11px}`; `>div:first-child{min-width:0;flex:1}`; `.actions{flex-wrap:wrap;max-width:520px}`.
- `.deployment-nos{margin:6px 0 0!important;font-size:12px;font-weight:600}`; `.ready{#256447}`, `.booting{#805510}`, `.failed{#a13135}`; `:empty{display:none}`. management.js sets `className='deployment-nos '+nos.status` with statuses `ready|booting|failed|idle` (idle → base style).
- `.job` (`<details class="job" data-job>`): `background:white;border:1px solid var(--line);border-radius:5px;margin-bottom:12px`; `summary{cursor:pointer;list-style:none;padding:18px 20px;flex center;gap:16px}` (marker hidden); `.job-title{flex:1}` `strong 13px block`, `small{block;font:10px mono;#687b85;margin-top:7px}`; `.job-body{border-top:1px solid var(--line);padding:18px 20px}` `>p{12px;#687b85;margin:0 0 15px}`; `.job-result{grid 1fr auto;gap:9px;padding:16px 0;border-bottom:1px solid var(--line);12px}` `p{grid-column:1/-1;pre-wrap;anywhere}` `strong anywhere` `>small{block;width:100%;#687b85;font:10px mono}`; `.job-body .button{margin-top:12px}`; `.device-download{flex wrap center gap 12;width:100%;margin-top:10px}` `code{anywhere;flex:1;min-width:180px}`; `.archive-download{flex center gap 12 wrap;margin-top:18px}` `small 10px mono`. app.js preserves `.job[open]` set across re-render.
- `.op-sections section{border:1px solid #dce3e7;border-radius:10px;padding:20px;background:#f8fafb}`; `.op-notice{padding:12px 15px;border-left:3px solid #fa583f;background:#fff2ed;color:#663326}`; `.op-banner{column flex;gap:5px;padding:16px 20px;border-radius:8px;margin:0 0 14px;border:1px solid transparent}` `strong 19px -.01em` `span 12px anywhere`; `.good{#e3f4e9/#9fd3b3/#1d5a3b}` `.bad{#fcebea/#f0b4b2/#8f2a2e}` `.running{#e5f6f9/#a8dfe8/#126575}` — operations.js `tone` = `good|bad|running`.
- `.git-progress-bar{flex space-between;gap:20px;background:#eaf3f3;border:1px solid #c5d9dd;border-left:3px solid var(--slate);border-radius:6px;padding:18px 20px;margin:0 0 22px}`; `p{margin:5px 0 0;11px;--slate}`.
- `.git-repository-card,.git-binding-form,.git-saves{border:1px solid var(--line);border-radius:6px;padding:22px;background:#fff;margin:18px 0}`; `.git-repository-card p,.git-saves>p{12px}`; `#git-saves-list{grid;gap:8px}`.
- `.git-setup-command{pre-wrap;anywhere;text-align:left;background:#edf3f5;padding:16px;border-radius:4px;font:12px/1.8 var(--mono);max-width:700px;margin:18px auto}`.
- `.git-job-summary .health-grid{margin:15px 0 25px}`; `p{pre-wrap;anywhere}`; `dd 12px`.
- `.git-places` family (folder browser): `.git-places{border:1px solid var(--line);border-radius:6px;background:#fff;margin:18px 0;overflow:hidden}`; `.git-places-title{padding:18px 22px 6px}` `p{12px;#687a84;margin:6px 0 0}`; `.git-places-head{flex space-between wrap;gap:12px;padding:12px 18px;border-bottom;background:#f7fafb}`; `.git-crumbs{flex wrap center;gap:2px;12px;min-width:0}` `span{#9eacb3;padding:0 2px}`; `.git-places-body{grid 250px minmax(0,1fr);min-height:220px}`; `.git-outline{border-right;padding:10px 8px;overflow:auto;max-height:420px;background:#fbfcfc}` `details{margin:0}` `summary{list-style:none;flex center gap 7;padding:6px 8px;radius 4;12px;--ink;anywhere}` with `::before` CSS triangle (`border:4px solid transparent;border-left:5px solid #7d8f99`) rotating 90° when `details[open]`, hidden for `.git-leaf`; `summary:hover #edf3f5`; `summary.selected #e3ecf0`; `.git-outline-children{padding-left:14px}`; `.git-folder-icon` 14×11 `#8fb0be` with tab `::before`; `.lab{--coral}` `.managed{--slate}` `.pending{opacity:.45}`; `.git-file-icon` 11×14 outlined; `.git-places-foot{flex space-between wrap;padding:10px 18px;border-top;11px;#687a84}`; `.git-empty-folder{padding:40px 24px;center;#687a84;12px;margin:0}`; `.git-destination-line{flex center wrap;gap:6px;13px;margin:12px 0}` `code{#edf3f5;padding:3px 7px;radius 4;12px}` `span[aria-hidden]{#9eacb3}`.
- `.git-version-files details,.git-diff-file{border:1px solid #d6e0e4;border-radius:5px;background:#f8fafb}`; summaries `padding:14px;anywhere`; `.git-file-content,.git-diff-columns pre{white-space:pre;overflow:auto;max-height:52vh;padding:16px;background:#142d3a;color:#e5eff4;font:12px/1.65 var(--mono);margin:0;border-radius:0 0 4px 4px;tab-size:4}`; `.git-diff-columns{grid 2×minmax(0,1fr);gap:1px;background:#ccdbe0}` `section{min-width:0;#fff}` `h3{12px;margin:12px 16px}` `pre{min-height:140px}`.
- `.restore-targets-status{column flex;gap:8px;margin:12px 0}`; `.restore-target-row{border:1px solid var(--line);radius 6;padding:10px 12px;background:#fbfcfc}` `strong{margin-left:8px}` `p{margin:6px 0 0;12px;#4b5f6a}`; `.restore-safety{margin:12px 0;padding-left:18px;12px;#4b5f6a;line-height:1.6}` `li{margin:2px 0}`; `.restore-advanced{margin:8px 0;12px}` `summary{pointer;600;--slate}`; `.restore-target.disabled{opacity:.6}` (restore.js: `r.eligible ? '' : 'disabled'`).
- `.debug-grid{grid 3×minmax(0,1fr);gap:20px}`; `.debug-card{#fff;border:1px solid #dce4e8;radius 12;padding:24px;margin:20px 0}` (`margin:0` inside grid) `h2{margin-top:0}` `dl{grid 1fr 1fr;gap:10px}` `dt{#416377}` `dd{margin:0;anywhere}`; `.debug-failure{color:#a12d1b}`.
- `.workspace-choices{grid minmax(280px,2fr) minmax(230px,1fr);gap:22px;max-width:1000px;margin:8px 0 32px}`; `.workspace-back{inline-block;margin:8px 0 24px;--slate;600}`.
- `.guide-row{grid minmax(180px,1fr) 2fr;border-bottom:1px solid #d9e1e6;gap:20px;padding:12px 0;anywhere}` — **no markup uses it**.

---

## 11. Dialogs & drawer

- `dialog{border:1px solid #d3dfe3;border-radius:6px;padding:28px;width:min(520px,calc(100% - 30px));color:var(--ink);box-shadow:0 24px 80px #142c3830;max-height:90vh;overflow:auto}`; `::backdrop{background:#142c3860}`; `dialog h2{25px;margin:15px 0}`; `dialog p{13px;#687c86}`.
- `.dialog-head{flex space-between center;gap:15px}`; `.dialog-head .eyebrow{margin:0}`.
- `#login-dialog{border-top:3px solid var(--coral)}` + `form>.button{margin-top:20px}` — **no element with this id exists in HTML or JS (dead)**.
- `#vm-dialog{max-height:90dvh;overflow:auto}` (created by management.js).
- **Node drawer** `dialog.node-details` (`#details-dialog`): `position:fixed;inset:0 0 0 auto;margin:0;width:min(560px,94vw);height:100dvh;max-height:100dvh;border:0;border-left:1px solid #b8ccd5;border-radius:0;padding:0;background:#fff;overflow:auto;box-shadow:-12px 0 60px #142c3820`; `::backdrop #142c3828`; `.drawer-head{sticky top 0;z-index:1;padding:25px 28px 22px;background:var(--rail);color:#fff;border-bottom:2px solid var(--coral)}` `h2{#fff;margin:16px 0 5px;27px;anywhere}` `.eyebrow{#a9c6d3}` `.endpoint{--cyan;12px}`; `.drawer-actions{margin-top:23px;min-width:0}`; `.drawer-content{padding:0 28px 26px}`; `.drawer-section{padding:26px 0;border-bottom}` (last none) `h3{13px;--slate}`; `.health-grid{grid 130px minmax(0,1fr);gap:15px;margin:20px 0 0;12px}` `dt{#6b7f89}` `dd{margin:0;anywhere}` `.mono{11px}`; `.connection-result{margin-top:18px}` `p{12px;margin:12px 0}` `time{font:10px mono;#687c86}`; `.node-details .device-download{padding:16px;border:1px solid var(--line);border-left:2px solid var(--slate);radius 4;display:block}` `strong 12px` `small{block;10px mono;#687c86;margin:8px 0}` `code{block;10px;white-space:normal;min-width:0}` `button{margin-top:14px;min-height:32px;11px}`.
- **Operations dialog** `.operations-dialog` (created by operations.js, `#operation-output`): `width:min(1120px,94vw);max-width:94vw;max-height:92dvh;overflow:auto;padding:28px;border:1px solid #ccd6db;border-radius:14px`; `::backdrop rgba(22,43,54,.42)`; `h2{margin:10px 0 18px}` `h3{16px;margin:0 0 14px}`; `#operation-output.inspection-dialog{width:min(1680px,97vw);max-width:97vw}` (class toggled by operations.js for inspect actions); `#op-layout-editor{width:min(1500px,96vw)}`; `#git-save-options{width:min(700px,94vw)}`; `#git-history-dialog{width:min(1000px,94vw)}` (+ `.op-history .button{display:block}`, `strong{display:block}`); `#git-diff-dialog{width:min(1500px,96vw);max-width:96vw}`; `#git-version-dialog` only responsive rules. Inner pieces: `.op-sections{grid 1fr 1fr;gap:22px}`; `.op-grid{grid 1fr 1fr;gap:9px}`; `.op-grid small,.op-history small{block;11px;margin-top:4px;opacity:.75}`; `.op-path{ui-monospace;anywhere;#416377}`; `.op-output{pre-wrap;anywhere;background:#172f3d;color:#e1edf2;radius 8;padding:18px;max-height:48vh;overflow:auto;font:13px/1.55 ui-monospace}`; `.op-code{width:100%;min-height:44vh;white-space:pre;overflow:auto;tab-size:2;font:13px/1.6 ui-monospace;background:#f6f9fb;border:1px solid #cbd6dc;radius 8;padding:16px;color:#173848;resize:vertical}`; `.op-history,.op-file-list{grid;gap:8px;margin:20px 0}` (`.op-file-list` 2 cols); `.op-layout-map{block;width:100%;height:48vh;border:1px solid #d6e0e5;radius 10;background:#fcfaf1;touch-action:none}` `.map-device{cursor:grab}` `:active{grabbing}`; `.op-session-list{margin-top:22px}` `p{flex center gap 16;border-bottom:1px solid #dbe3e8;padding:12px 0}` `strong{min-width:160px}`; `.op-file-tree{block;max-height:60vh;overflow:auto;padding:12px;border:1px solid var(--border,#d9e1e6);radius 8;margin-top:16px}` `summary{pointer;padding:10px 8px;anywhere}` hover `#edf3f5`; `.op-tree-children{margin-left:22px;border-left:1px solid #d9e1e6;padding-left:10px}`.
- **Diagram editor** (`#op-layout-editor`): `.diagram-workspace{grid minmax(0,1fr) 280px;gap:16px}`; `.op-layout-map{height:56vh;min-height:360px}`; `.diagram-properties{max-height:56vh;overflow:auto;padding:12px;background:#f5f8f9;border:1px solid #d6e0e5;radius 8}`; `.diagram-workspace .topology-annotation{cursor:move;pointer-events:all}`; `.diagram-selected{filter:drop-shadow(0 0 3px #f15b40)}`; `#diagram-state{12px}`; `#diagram-discard{padding:14px;border:1px solid #f15b40;radius 8;background:#fff7f4}`; `.diagram-toolbar .button,#op-layout-editor .dialog-actions .button{white-space:normal}`.
- **Capture dialog** `.capture-dialog` (`#capture-dialog`): `width:min(740px,94vw);max-height:90vh;overflow:auto`; `h3{margin-top:22px}`; `.capture-more,.capture-advanced{margin-top:14px;border:1px solid #cbd5db;radius 8;padding:10px 14px}` `summary{pointer;12px;600;--slate}`; `.capture-more .capture-interfaces,.capture-advanced .capture-controls{margin-top:10px}`.

---

## 12. Menus, details/summary, toast

- `.node-context-menu` (`#node-context-menu`, `role=menu`): `position:fixed;z-index:100;min-width:260px;background:#fff;border:1px solid #d6dfdf;box-shadow:…;border-radius:10px;padding:6px;color:#294555`; `[hidden]{display:none}`; `.context-node-name{padding:10px 12px 12px;border-bottom:1px solid #e5ebeb;700;14px}` `small{block;400;11px;#70828a;margin-top:5px}`. Positioned by topology.js via `style.left/top` clamped to viewport (8px margin). Keyboard: Arrow/Home/End cycling, Escape closes, opens on `ContextMenu` / Shift+F10 / Enter / Space.
- `.git-save-control{flex;flex-shrink:0;gap:1px;align-items:stretch}` split button: `>.button{border-radius:4px 0 0 4px}`; `:has(.git-save-menu[hidden])>.button{border-radius:4px}` (**depends on `:has()` support**); `.git-save-menu{position:relative}` `>summary{list-style:none;border-radius:0 4px 4px 0;min-width:38px;height:100%;padding:9px 11px}` (marker hidden); `.git-save-options{absolute;top:calc(100% + 6px);right:0;width:240px;z-index:20;#fff;border:1px solid #c7d5dc;radius 6;padding:6px;shadow}`. git-progress.js closes it with `.open=false` on Escape / after action.
- `.extra-views` (see §8) — closed by app.js after tab click.
- Other `<details>` styles: `.job` (§10), `#discovery-files` (§4), `details:not(.job)` generic, `.capture-more/.capture-advanced`, `.restore-advanced`, `.git-outline details`, `.git-version-files details`, `.git-diff-file`, `.op-file-tree` folders, `.capture-viewer-help` (`[open]{flex-basis:100%;order:10}` so it drops to a full-width row).
- `#toast{position:fixed;bottom:24px;right:24px;max-width:calc(100vw - 48px);padding:15px 20px;background:var(--rail);color:white;border-left:3px solid var(--cyan);border-radius:4px;box-shadow:var(--shadow);font-size:12px;z-index:30}` — shown by `hidden=false`, auto-hidden after 5000 ms (app.js, workspace.js). Single tone; no error/success variant.

---

## 13. Topology map & map tools

- `.map-tools{flex center;gap:8px;flex-wrap:wrap}` (redeclared); `span{12px;#5e5e5e}`; buttons §6; `#map-status{12px;#5e5e5e}`.
- `#topology-map{width:100%;height:600px;min-height:350px;border:1px solid #d9dfdf;border-radius:12px;touch-action:none;cursor:grab;font-family:Arial,sans-serif}`.
- `.map-expanded{position:fixed!important;inset:14px;z-index:50;background:#fff;padding:24px;border-radius:16px;box-shadow:0 0 0 30px #203b49aa;display:flex;flex-direction:column}` on `#topology-view` section (topology.js toggles; removed on Escape); `.map-expanded #topology-map{flex:1;min-height:100px;height:auto}`; `.map-expanded .section-heading{margin-bottom:12px}`.
- SVG classes (emitted by topology-render.js): `.topology-annotation{pointer-events:none}`; `.topology-wire path{stroke:#87a9ab;stroke-width:2;fill:none}`; `.interface-label rect{fill:#fffdf4;fill-opacity:.95}` `text{fill:#607d8b;10px}`; `.map-device{cursor:pointer}`; `.device-body{stroke:#fff;stroke-width:1}`; `.device-symbol{stroke:#fff;1.4;round caps/joins;fill:none}`; `.device-label text{fill:white;11px;400}`; `.map-device:focus{outline:none}`; `.map-device:hover .device-body,.map-device:focus .device-body{stroke:#f15b40;stroke-width:3}`; `.map-device.unmatched{cursor:default}` `.device-body{stroke:#6d777b;stroke-dasharray:3 2}`; `.unmatched-label{9px;fill:#795b31}`; `.labels-on-select .interface-label{opacity:0}` + `.topology-wire:hover .interface-label{opacity:1}` (class toggled on the SVG when `labelMode==='on-select'`); `.topology-wire[role="button"]{cursor:pointer}` `:hover path,:focus path{stroke:#F15B40;stroke-width:5}`; `path.capture-hit{stroke:transparent;stroke-width:16;pointer-events:stroke}` (fat invisible hit target). Device fills, annotation colours, grid dot colour (`#d2cbb5`) and canvas background (`#fdf6e3`) come from **SVG presentation attributes in JS**, not CSS. `.device-label-bg` and `#topology-scene` are emitted but unstyled.

---

## 14. Capture viewer & guides

- `.capture-viewer-toolbar{flex;gap:12px;center;padding:12px;wrap;#fff;border-bottom:1px solid #ccd5dd}` → later `padding:6px 12px;gap:10px`; `strong{flex:0 1 auto;nowrap}`; `.capture-viewer-help{13px;margin:6px 12px}` → later `margin:0;12px`, `summary{pointer;600;#157d91;nowrap}`, `p{margin:8px 0 2px;12px;1.5}`; `.capture-viewer #viewer-status{margin:6px 12px}` → later `flex:1;min-width:220px;margin:0;12px;--slate}`.
- capture-session.js polls status every interval (`setInterval`) and writes `#viewer-status` text; `#capture-end` is `.button.danger`, disabled until connected.

---

## 15. Terminal page (terminal.css, complete)

`*{box-sizing}`; `body{margin:0;background:#152631;color:#e7eff2;font:13px "Segoe UI",Arial;flex column;height:100vh;overflow:hidden}`; `header{flex wrap space-between center;gap:16px;padding:20px 24px;border-bottom:2px solid #f15b40;background:#182c38}`; `.terminal-identity{flex center;gap:15px;min-width:0}` `img 36×36` `strong{block;15px;margin:7px 0;anywhere}`; `.brand-label{9px;.15em;#aec9d7}`; `#endpoint{font:11px Consolas,monospace;#79e8f6}`; `.session-controls{flex wrap;gap:10px;center}`; `#status{font:11px Consolas;#79e8f6;margin-right:10px}`; buttons/inputs §6; `button:focus-visible,input:focus-visible{outline:2px solid #79e8f6;outline-offset:3px}`; `.notice{padding:0 24px;#a4bbc7;11px;1.5}`; `#terminal{flex:1;min-height:0;margin:12px 24px 20px;overflow:hidden}`; `@media(max-width:700px)` (§3.1). Note `.notice` here conflicts in name with style.css `.notice` (different look) but the two sheets never load together.

## 16. xterm.css (vendor, skimmed)

Stock xterm.js 5.x stylesheet: `.xterm` (cursor:text, user-select none), `.xterm.focus/:focus{outline:none}`, helpers/textarea off-screen, `.xterm-viewport{background:#000;overflow-y:scroll}`, screen canvas positioning, accessibility tree, `.xterm-dim`, underline/overline/strikethrough classes, decoration z-indexes (2, 5, 6, 7, 8, 10). Not project code; keep as-is.

---

## 17. Status colour semantics (consolidated)

| selector | colour(s) | meaning |
|---|---|---|
| `.badge.good`, `.op-banner.good`, `.deployment-nos.ready` | `#e9f3ed/#256447`, `#e3f4e9/#9fd3b3/#1d5a3b`, `#256447` | success / ready / reachable / synced |
| `.badge.bad`, `.op-banner.bad`, `.deployment-nos.failed`, `.form-error`, `.debug-failure` | `#fcebea/#a13135`, `#fcebea/#f0b4b2/#8f2a2e`, `#a13135`, `#a13135`, `#a12d1b` | failure / unreachable / validation error |
| `.badge.warn`, `.deployment-nos.booting`, `.git-tag.pending`, `.empty-vm-note` | `#fff3de/#805510`, `#805510` | warning / pending / booting / unknown status |
| `.badge.running`, `.op-banner.running` | `#e5f6f9/#126575`, `#e5f6f9/#a8dfe8/#126575` | in progress |
| `.badge` (neutral), `.git-tag.other`, `.status-neutral` | `#edf2f4/#416377`, `#6b7c85` | neutral / not checked |
| `.git-tag` | `#fde9e4/#a13a26` | "this lab" ownership marker (coral family, not an error) |
| `.op-notice` | `#fff2ed / #fa583f / #663326` | attention notice inside ops dialog |
| `.worker-state::before` | `--slate` dot always | worker status dot (no state colours) |
| `.lab-item.active`, `.tabs .active`, `.extra-views summary.active` | `--coral` accent | selected item |
| `.git-folder-icon.lab/.managed/.pending` | coral / slate / 45% opacity | folder registered to a lab / managed / not yet created |
| `.map-device.unmatched .device-body` | `#6d777b` dashed | node not in inventory |
| map hover/focus strokes | `#f15b40` | interactive highlight |
| `.button.danger*` | `#c24a37/#a73122` | destructive |
| `.link-button`, focus ring, `.capture-viewer-help summary` | `#157d91` | link/teal |
| `--cyan` on `--rail` | `#79e8f6` | SSH / endpoint emphasis on dark surfaces |

---

## 18. Focus & accessibility rules

- Global focus ring: `button:focus-visible,input:focus-visible,select:focus-visible,summary:focus-visible{outline:3px solid #157d91;outline-offset:3px}`. **Not covered**: `<a>` links (`.button` anchors like `#grafana-open`, `#capture-launch`, `.workspace-back`, guide links), `<textarea>` (diagram properties), `[tabindex=0]` SVG nodes/wires, `<pre tabindex="0">` op output — all fall back to UA default.
- Overrides: `.workspace-choice:focus-visible{outline:3px solid #416377;outline-offset:4px}`; `.node-context-menu button:hover,:focus{background:#edf5f6;outline:none}` (focus shown by background only); `.map-device:focus{outline:none}` with focus indicated by `.device-body` stroke `#f15b40` 3px; `.topology-wire[role=button]:focus path` stroke `#F15B40` 5px. terminal.css: `outline:2px solid #79e8f6;offset 3px`.
- `button:disabled{cursor:not-allowed;opacity:.45}`; `.node-context-menu button:disabled{opacity:.4;cursor:default}`; `.button.danger:disabled` recolour; `.restore-target.disabled{opacity:.6}`; terminal `button:disabled{opacity:.45;cursor:default}`.
- `.sr-only` utility (table header for checkbox column). `[hidden]{display:none!important}`.
- `@media(prefers-reduced-motion:reduce)` disables transitions/animations.
- `details` markers removed via `list-style:none` + `::-webkit-details-marker{display:none}` for `.job summary`, `.git-save-menu>summary`, `.git-outline summary`, `.extra-views summary` (custom ` ▾` / CSS triangle).
- ARIA hooks referenced by CSS: `.git-crumbs button[aria-current=page]`, `.git-destination-line span[aria-hidden]`, `.topology-wire[role="button"]`. ARIA hooks set by JS but not styled: `aria-selected` on tabs, `aria-haspopup`, `role=menu/status/alert/group`, `aria-live`.
- `font-synthesis:none` on root. Native `<dialog>` used throughout (backdrop styled). `accent-color` for checkboxes.
- Colour-only signals: badge dot uses `currentColor`; `.deployment-nos` text colour is the only differentiator (text content also changes, so OK); `.worker-state` conveys state by text only.

---

## 19. Inconsistencies / near-duplicates / magic numbers

1. **Selectors redefined later in the file** (later wins): `.brand` (23px→18px), `.brandmark` (40→34px), `.brand small` (identical), `.sidebar` (+overflow-y), `.sidebar nav` (flex:none;max-height:260px), `.side-bottom` (margin-top:auto→24px), `.side-caption`, `.control-row` (+wrap), `.tabs` (+overflow:visible), `.map-tools` (+wrap, identical), `.deployment-bar` (+wrap, gap dup), `.deployment-bar .actions` (×3), `.op-inspection table` (min-width 850→0), `.op-inspection td` (max-width 240→none), `.extra-views summary` (padding 19→14), `.capture-viewer-toolbar` (padding/gap), `.capture-viewer-help` (margin/size), `.capture-viewer #viewer-status`, `button,input,select` (font vs transition). The ≤1150 `.brand{font-size:21px}` breakpoint is now larger than the desktop 18px.
2. **Four button systems**: `.button.*` (38px, 12px/600), `.node-actions button` (32px, 11px/600, `#ccd8dc`), `.map-tools button` (no min-height, 7px radius, `#cacbca`, no weight), `.side-button` (12px, `#496271`), plus menu-item buttons (`.git-save-options`, `.extra-views-menu`, `.node-context-menu`, `.op-tree-file`, `.git-crumbs`) each with their own padding (12px / 12px / 13px 12px / 10px 8px / 6px 8px) and hover greys (`#edf3f5`, `#edf5f6`, `#e6eef1`).
3. **Three "danger" reds**: `.button.danger` `#c24a37/#a73122`, `.node-name:hover` `#b43825`, `.debug-failure` `#a12d1b`, `.badge.bad` `#a13135`, `.git-tag` `#a13a26`, `.workspace-choice-primary span` `#9c3622`, `.op-notice` border `#fa583f` vs `--coral #f15b40`.
4. **Three monospace stacks** (`--mono`, `ui-monospace,monospace`, `Consolas,monospace`) and three code-block darks (`#172f3d`, `#142d3a`, `#152631`) with three light text tones.
5. **14 muted-grey text values** and **32 border greys** where `--line`/`--muted` should serve; `--muted` and `--peach` declared but unused; `--border` used but undeclared.
6. **Hover greys**: `#edf3f5` (6×), `#edf5f6`, `#e6eef1`, `#f0f5f6`, `#f8fafb`, `#f6f9fa`, `#263e4b`, `#2a4352`, `#2a4555`, `#314d5d` — no hover token.
7. **Card radius drift**: 4 (`.profile-card`), 5 (`.job`, `.metrics`, `.table-wrap`, `.deployment-bar`), 6 (`dialog`, git cards, restore), 8 (op-banner, fieldsets), 10 (`.op-sections section`, context menu), 12 (`.debug-card`, `.workspace-choice`, `#topology-map`), 14 (`.operations-dialog`), 16 (`.map-expanded`).
8. **Badge families**: `.badge` (10px, dot) vs `.git-tag` (10px/600, no dot) vs `.tag` (9px mono) vs `.platform-pills span` vs `.platform` — four pill styles.
9. **Label pattern duplicated**: `dialog label:not(.checkbox-label)` vs `.git-binding-form>label:not(.checkbox-label)` (18 vs 20px top margin).
10. **`.primary`/`.secondary`/`.dark`/`.full` are unscoped global classes**; `.dark`, `.full`, `.guide-row`, `#login-dialog` are dead CSS; `.view`, `.close`, `.row`, `.language-bash`, `.device-label-bg`, `.topology-map` (class) have markup/JS usage but no CSS.
11. **`[hidden]` re-declared** three times (`[hidden]`, `.node-context-menu[hidden]`, `.capture-dialog [hidden]`).
12. **`!important` usage** (9): `[hidden]`, `.form-error` colour, `.form-help` size, reduced-motion, `.map-expanded` position, `.capture-dialog [hidden]`, `.empty-vm-note` margin, `.deployment-nos` margin — the latter two fight `dialog p`/`.deployment-bar p` specificity.
13. **Magic numbers**: `.sidebar nav max-height:260px`, `.node-actions min-width:205px/170px`, `.node-name max-width:340px`, `.log-message min-width:240px`, `.op-inspection` per-column % widths, `.health-grid 130px/105px`, `.git-places-body 250px`, `.diagram-workspace 280px`, `.deployment-bar .actions max-width:520px`, `.empty-panel p max-width:540px`, `.git-save-options width:240px` / `min(260px,calc(100vw - 65px))`, `.git-outline max-height:420px`, `.capture-interfaces max-height:240px`, viewport heights `48vh/44vh/56vh/45vh/52vh/60vh/65vh`, `.map-expanded inset:14px` + 30px ring, `.empty-panel::before` gradient stops at 76%/79%.
14. **Mixed viewport units**: `100vh` (sidebar, `.capture-viewer`) vs `100dvh` (drawer) vs `90vh`/`90dvh`/`92dvh` for dialogs.
15. **Breakpoint sprawl**: 1550, 1150, 900, 850, 800, 760 (five separate blocks), 720, 700 — five distinct "mobile" thresholds.
16. `.topology-map.op-layout-map` in JS relies on `.op-layout-map` only because `topology-map` is styled as an **id**; the class is a no-op.
17. `.extra-views summary` gets `font-size:inherit` then is forced to 12px/600 through `.tabs .extra-views` — two-step fix.
18. `details:not(.job){margin-top:20px}` is a broad rule that later needs per-component resets (`.git-save-control .git-save-menu{margin:0}`, `.tabs .extra-views{margin-top:0}`, `.git-outline details{margin:0}`).
19. `.git-save-control:has(...)` — only `:has()` usage; no fallback.
20. `.op-file-tree` uses `var(--border,#d9e1e6)` — the only `var()` with fallback, token never defined.

---

## 20. Behavioural class hooks (JS toggles/queries these — must survive the redesign)

**Toggled by JS (`classList` / `className`):**
`active` (tabs `[data-tab]`, `#extra-views-label` summary, `.lab-item`), `map-expanded` (on `#topology-view`), `labels-on-select` (on `#topology-map`), `inspection-dialog` (on `#operation-output`), `diagram-selected` (SVG `[data-map-id]`/`[data-decoration-index]`), `deployment-nos ready|booting|failed|idle`, `op-banner good|bad|running`, `op-tree-children`, `op-tree-file`, `debug-failure`, `operations-dialog`.

**Queried by JS (`querySelector*` / `closest`):**
`.job[open]` (preserve expanded jobs), `.form-error`, `.form-help`, `.close`, `.device-label`, `.interface-label`, `dialog[open]`, `button[type=submit]`, `input:checked`, `[name="restore-node"]:checked`, `[name="git-node"]:checked`, `#topology-scene`, `p`, `code`, `rect`, `text`, `title`, `label`.

**Emitted in JS templates with state variants:**
`badge good|bad|warn|running|platform`, `lab-item active`, `map-device unmatched`, `restore-target disabled`, `git-folder-icon lab|managed|pending`, `git-tag other|pending`, `git-outline summary selected`, `details git-leaf`, `tr.row.folder`, `capture-hit`, `topology-wire`, `topology-annotation`, `device-body`, `device-symbol`, `device-label`, `device-label-bg`, `unmatched-label`, `context-node-name`, `status-neutral`, `timestamp`, `endpoint`, `secondary-text`, `node-name`, `node-actions`, `ssh-action`, `details-action`, `profile-card`, `profile-type`, `blank-state`, `table-empty`, `job`, `job-title`, `job-body`, `job-result`, `device-download`, `archive-download`, `health-grid`, `connection-result`, `drawer-section`, `log-message`, `mono`, `side-hint`, `side-button`, `empty-lab`, `form-grid wide`, `op-*` family, `git-*` family, `restore-*` family, `diagram-*` family, `capture-interface`, `op-session-list`, `git-inline-action`, `git-blank-actions`, `git-destination-line`, `git-setup-command`, `git-file-content`, `git-diff-columns`, `git-diff-file`, `git-version-files`, `git-saved-job`, `git-job-summary`, `git-places*`, `git-outline*`, `git-listing`, `git-crumbs`, `git-empty-folder`, `git-file-icon`, `name`, `desc`, `size`, `muted`, `eyebrow`, `dialog-head`, `dialog-actions`, `icon-button`, `button primary|secondary|danger|danger-outline`, `checkbox-label`, `actions`.

**Attribute/state hooks CSS depends on:** `[hidden]` (every `el.hidden=` toggle), `details[open]`, `dialog[open]`, `[aria-current=page]`, `[aria-hidden]`, `[role="button"]` on SVG groups, `:disabled`, `:empty` (`.form-error`, `.deployment-nos`, `.empty-vm-note`), `:has(.git-save-menu[hidden])`.

**Ids styled directly by CSS (must be kept):** `#toast`, `#nodes`, `#log-rows`, `#logs-view`, `#log-status`, `#login-dialog` (dead), `#topology-map`, `#map-status`, `#map-edit`, `#topology-view`, `#vm-dialog`, `#vm-summary`, `#vm-fingerprint`, `#remove-lab-name`, `#discovery-files`, `#discovery-file-list`, `#operation-output`, `#op-layout-editor`, `#diagram-state`, `#diagram-discard`, `#git-saves-list`, `#git-job-actions`, `#git-save-options`, `#git-history-dialog`, `#git-diff-dialog`, `#git-version-dialog`; terminal: `#endpoint`, `#status`, `#disconnect`, `#terminal`; viewer: `#viewer-status`, `#capture-screen`.

**Data hooks used by JS (unstyled, listed so the markup keeps them):** `data-tab`, `data-lab`, `data-job`, `data-map-node`, `data-map-id`, `data-decoration-index`, `data-capture-endpoints`, `data-capture-end`, `data-end-capture`, `data-op-close`, `data-op-action`, `data-op-options`, `data-local`, `data-repo`, `data-logs`, `data-download`, `data-dismiss`, `data-setup-name`, `data-allow-import`, `data-prop`, `data-add-shape`, `data-git-action`, `data-git-repo-action`, `data-git-job`, `data-git-job-action`, `data-git-pending`, `data-git-version`, `data-git-commit`, `data-git-place`, `data-git-places-action=use|new|apply`, `data-terminal`, `data-backup`, `data-check`, `data-edit`, `data-details`, `data-capture`, `data-enable`, `data-filename`, `data-node-index`, `data-diagram-node`, `data-source`, `data-target`.

**Related runtime facts seen while grepping (for completeness):** `sessionStorage` keys `activeLab` (app.js, management.js, operations.js) and a per-lab git key via `storageKey` (git-progress.js); toast auto-hide 5000 ms; `refresh()` `setInterval` in app.js; poll timers 1000/1200/1500 ms in operations.js, restore.js, git-progress.js; capture-session status `setInterval`; keyboard: Enter/Space activate map nodes & wires, ContextMenu/Shift+F10 open node menu (topology.js, operations.js, management.js), Arrow/Home/End navigate the menu, Escape closes menu / expanded map / git save menu.
