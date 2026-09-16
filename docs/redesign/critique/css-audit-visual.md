# CSS audit — visual system & contrast (new `style.css` / `terminal.css`, 1.29.0)

Scope: `/home/clabllm/projects/clab-manager/clab-backup-ui/app/static/style.css` (2 243 lines, sections 1–28) and `terminal.css` (90 lines), audited against DESIGN-SPEC §3/§1, addendum §A.15→J4, §C, §F, J3/J5/J7/J8 and `inventory/css.md` (§20 hook list). Ratios computed with the WCAG 2.x relative-luminance formula (`scratchpad/critique/css_contrast_new.py`, 190 pairs). Thresholds: 4.5:1 for text < 18px / < 14px-bold, 3:1 for large text and for non-text boundaries/state indicators (1.4.11). No files were edited.

Headline: the **text palette is sound** — every text-on-tint pair the spec lists passes (the CSS added `--ok-strong/--warn-strong/--danger-strong` for pill text, which is a valid alternative to J8's `--warn:#8f5200`). What fails is (1) the **control boundary token** `--line-strong #b9c6cf` (1.74:1 — every secondary button, field, node-action, map-tool and terminal button has no perceivable edge), (2) the **single-tone focus ring** (`--focus` = `--accent`, 1.00:1 on primary buttons, 2.79:1 on `--rail`; J8's two-tone ring was not applied), (3) **opacity-faded disabled reasons** in menus (2.1–2.3:1, defeating J2's "visible `.menu-reason`"), (4) the **link stroke** `--wire` (2.52:1) and the `state-neutral` dot (1.32:1), (5) **terminal button borders** (1.03:1), plus a set of J7/J8 hooks that the JS contract will emit but the stylesheet does not define (`.busy`, `.icon`, `.tool-list`, `.row-reason`, `[aria-current]` rows, `.menu-button[aria-expanded]`, `.state-working/.state-credentials`, `.device-state-glyph`, `.device-body` default fill, `forced-colors`/`prefers-contrast`).

---

## 1. Contrast results — requested pairs

### 1.1 Text on surfaces (PASS)

| pair | ratio |
|---|---|
| `--text #24313c` on `--bg` / `--surface` / `--surface-2` | 12.27 / 13.29 / 11.81 |
| `--ink #172430` on `--bg` / `--surface` / `--surface-2` | 14.56 / 15.77 / 14.01 |
| `--muted #5b6b76` on `--surface` / `--bg` / `--surface-2` | 5.51 / 5.09 / 4.90 |
| white on `--accent` / `--accent-strong` / `--danger` / `--danger-strong` / `--ok` / `--warn` | 5.65 / 7.32 / 6.54 / 8.91 / 5.32 / 4.88 |

### 1.2 Pills / badges (12px/600 → 4.5) (PASS)

| class | fg on bg | ratio |
|---|---|---|
| `.pill.ok`, `.badge.good`, `.op-banner.good` | `--ok-strong #155f3b` on `--ok-soft #e4f4ea` | 6.75 |
| `.pill.warn`, `.badge.warn`, `.git-tag.pending`, `.op-notice` | `--warn-strong #7a4500` on `--warn-soft #fff2dc` | 7.09 |
| `.pill.danger`, `.badge.bad`, `.op-banner.bad` | `--danger-strong #8f1d17` on `--danger-soft #fbe9e7` | 7.60 |
| `.pill.neutral`, `.badge`, `.git-tag.other` | `--neutral #5b6b76` on `--neutral-soft #eceff2` | 4.78 |
| `.pill.info`, `.pill.running`, `.badge.running`, `.git-tag`, `.op-banner.running`, `.lab-item.active` | `--accent-strong #175d77` on `--accent-soft #e2f0f5` | 6.28 |
| `.badge.platform`, `.platform`, `.tag` | `--muted` on `--surface` | 5.51 |
| reference: raw `--warn #a85f00` on `--warn-soft` | | **4.41 FAIL** — not used as text anywhere in the new CSS (only as border/dot, where 3:1 applies and it passes), but the token still contradicts J8 (`#8f5200`, 5.63); any future `color: var(--warn)` on the tint fails. Fix the token. |
| reference: `--ok` on `--ok-soft` / `--accent` on `--accent-soft` | | 4.67 / 4.85 (pass; the `-strong` variants used are safer) |

### 1.3 Banner text (PASS)

`.banner` text `--text` / `strong --ink` / links `--accent` / `.button.ghost --accent-strong` / `--muted` on:
`--surface` 13.29 / 15.77 / 5.65 / 7.32 / 5.51 · `.info --accent-soft` 11.41 / 13.53 / 4.85 / 6.28 / 4.73 · `.warn --warn-soft` 12.02 / 14.26 / 5.11 / 6.62 / 4.98 · `.danger --danger-soft` 11.34 / 13.45 / 4.82 / 6.24 / 4.70 · `.ok --ok-soft` 11.67 / 13.84 / 4.96 / 6.42 / 4.84.
Left borders vs their tints (non-text 3:1): info 4.85, warn 4.41, danger 5.58, ok 4.67 — pass.
**FAIL inside banners**: a `.button.secondary` placed in `.banner-actions` has a `--line-strong` border at 1.49–1.58:1 against the tints (see 1.7).

### 1.4 Menus

| pair | ratio | verdict |
|---|---|---|
| `.menu-list button` `--text` on `--surface` | 13.29 | pass |
| `.menu-reason` (11px) `--muted` on `--surface` / hover `--surface-2` / `.menu-danger` hover `--danger-soft` | 5.51 / 4.90 / 4.70 | pass |
| `.menu-danger button` `--danger` on surface; hover `--danger-strong` on `--danger-soft` | 6.54 / 7.60 | pass |
| **`.menu-list button:disabled { opacity: .55 }` → `.menu-reason` renders as `#a5aeb4` on white** | **2.25** | **FAIL** — the disabled reason is the one text that must stay legible (J2, G2) |
| same rule → the disabled item label renders as `#878e94` | 3.32 | fail (inactive-control exemption applies to the label, not to the explanatory reason) |
| **`.node-context-menu button:disabled { opacity: .5 }` → inline `<small>` reason (topology.js line 20) renders as `#adb5ba`** | **2.08** | **FAIL** (active today) |
| `.node-context-menu button small` (11px) `--muted` on surface when enabled | 5.51 | pass |
| `.menu-list button:hover` `--surface-2` on `--surface` (hover cue only) | 1.13 | informational — keyboard focus gets the global ring, so 1.4.11 is met; pointer hover is weak |

### 1.5 Links (PASS)

`a`, `.link-button`, `.git-inline-action` `--accent` on `--surface` / `--bg` / `--surface-2`: 5.65 / 5.22 / 5.02; hover `--accent-strong`: 7.32 / 6.76 / 6.50; `#toast a` `--accent-on-dark` on `--rail` 7.90; `.git-crumbs [aria-current]` 6.28; `.button.ghost` 7.32; `.button.danger-outline` 6.54 (hover 7.60); `.tabs button` 5.51; `th` 4.90; `.worker-state` 7.32.

### 1.6 Focus ring (`:focus-visible { outline: 3px solid var(--focus) }`, `--focus = #1d6f8e`)

| ring vs adjacent colour | ratio | verdict |
|---|---|---|
| vs `--surface` / `--bg` / `--surface-2` / soft tints | 5.65 / 5.22 / 5.02 / 4.8–5.1 | pass |
| **vs `--accent` (`.button.primary`, `.ssh-action`, `.side-primary`, `.map-tools .primary`)** | **1.00** | **FAIL** — the ring is the button's own colour; the only thing that makes it visible is the 2px `outline-offset` gap showing the underlying surface, which J8/F3 required to be guaranteed by a `box-shadow: 0 0 0 2px var(--surface)` separator. Not applied. |
| vs `--accent-strong` (hovered primary) / `--danger` (`.button.danger`) / `--ok` | 1.30 / 1.16 / 1.06 | FAIL (same cause) |
| **vs `--rail` (`#toast` buttons — only `#toast a` is overridden; `.op-output`, `.git-file-content`, `.vm-guide pre` if they ever hold focusables)** | **2.79** | **FAIL** |
| `--focus-on-dark #6fc3de` vs `--rail` / terminal `--rail-2` / `--rail-3` | 7.90 / 5.95 / 4.96 | pass |
| J8 `--focus-ring #0e4a63` vs `--surface` (ring vs white separator) | 9.64 | the intended design |
| white separator vs `--accent` / `--danger` | 5.65 / 6.54 | (makes the two-tone ring self-sufficient on filled buttons) |
| J8 `#9ad4ea` vs `--rail` | 9.74 | |

### 1.7 Non-text boundaries (1.4.11, 3:1)

| pair | ratio | verdict |
|---|---|---|
| **`--line-strong #b9c6cf` vs `--surface`** — `.button` base border, `.button.secondary`, `.menu > summary`, `input/select/textarea`, `.node-actions button`, `.map-tools button`, `.side-button`, `.tag`, `.file-icon`, `.map-device.unmatched` dash | **1.74** | **FAIL** — with `background: var(--surface)` on a `--surface` card the border is the only cue that says "control". J8 token `#74879a` was not applied. |
| `--line-strong` vs `--surface-2` — inputs inside `.op-sections section` / `.diagram-properties`, `.upload-field` dashed box (its inner `input` has `border:0`), `.op-code` textarea, `.git-file-icon`, `.git-folder-icon` on `.git-outline` | 1.55 | FAIL |
| `.button.secondary` border inside `.banner.info/.warn/.danger/.ok` | 1.50 / 1.58 / 1.49 / 1.53 | FAIL |
| `.empty-state` dashed `--line-strong` vs surface | 1.74 | decorative container → informational (fixed by the token) |
| `.button.secondary:hover` border `--muted` | 4.90 | pass |
| `input:focus` border `--accent` | 5.65 | pass |
| `.tabs` active underline `--accent` vs surface | 5.65 | pass |
| checkbox `accent-color: --accent` | 5.65 | pass |
| `.pill::before` dot = `currentColor` | = text ratio | pass |
| `.card`/`.table-wrap`/`hr` `--line` vs `--bg` | 1.22 | decorative — acceptable |
| **`.skeleton` `--surface-2` on `--surface`** | **1.13** | **FAIL** (F8/J8): imperceptible on most laptop panels; `.skeleton-line` has no background of its own unless combined with `.skeleton`. J8: `--line → --surface-2 → --line` gradient (1.32 base; accepted floor because the `role=status` text carries the meaning). |
| `.menu-list`/`.tabs`/`.job summary` hover `--surface-2` | 1.13 | hover-only, informational |
| `.lab-item.active` bg `--accent-soft` vs surface (+ 3px `--accent` bar 4.85) | 1.17 (+bar) | pass via the bar |

### 1.8 Map (SVG)

| pair | ratio | verdict |
|---|---|---|
| **`.topology-wire path` `--wire #93a6b2` vs `--surface`** (wires are `role=button` capture targets, so the stroke is the control boundary) | **2.52** (2.33 vs the renderer's still-emitted cream `#fdf6e3`) | **FAIL** |
| `.device-state-dot` ready `--ok` / starting `--warn` / attention `--danger` / unavailable `--neutral` vs `--surface` (J7 geometry: dot outside the body with a 2px surface halo) | 5.32 / 4.88 / 6.54 / 5.51 | pass |
| **`.map-device.state-neutral .device-state-dot { fill: var(--line) }`** vs surface | **1.32** | **FAIL** — an invisible dot; either hide it for "no state" or draw a hollow ring |
| the same dots vs the renderer's default body `#0066ff` if the dot keeps the §C geometry (`cx=16 cy=-16 r=5`, on the body) | 1.01–1.35 | FAIL until topology-render.js adopts J7 (`cx=24 cy=-24 r=7`) and the CSS supplies `.device-body:not([fill]) { fill: var(--accent) }` (rule missing) |
| ok / warn / danger / neutral luminance spread | 1.04–1.23 | hue-only — J7's `g.device-state-glyph` (check / arc / bang / hollow) is the non-colour cue; **no CSS rules exist for it** |
| `.device-symbol` white on `#0066ff`; `.device-label text` white on `#454545` (11px) | 4.83 / 9.59 | pass |
| `.interface-label text` / `.unmatched-label` `--muted` 11px | 5.51 | pass |
| hover/focus stroke `--accent`; state-ready stroke `--ok` | 5.65 / 5.32 | pass |

### 1.9 Dark surfaces (toast, code output)

| pair | ratio | verdict |
|---|---|---|
| `#toast` `--rail-text #e7eff2` on `--rail #172431`; `#toast small` `--rail-muted #a9bcc8` | 13.52 / 8.04 | pass |
| `#toast` border `--accent-on-dark` vs rail; `#toast .button.danger-outline` `--danger-on-dark` | 7.90 / 9.29 | pass |
| `.op-output` (13px mono), `.git-file-content` / `.git-diff-columns pre` (12px mono), `.vm-guide pre` — `--rail-text` on `--rail` | 13.52 | pass (but see §3: J8 says these panes must be light `--surface-2`, dark only for `#toast` and terminal.html) |
| `.op-output small` `--rail-muted` | 8.04 | pass |
| `.op-code` `--ink` on `--surface-2` | 14.01 | pass; its `--line-strong` border 1.55 fails (1.7) |
| **`--muted` is not re-scoped on dark surfaces**: any `.caption/.muted/.timestamp/.endpoint/.secondary-text` inside `#toast`/`.op-output` renders `#5b6b76` on rail | **2.86** | FAIL (latent — `notify()` writes `textContent` only today; becomes live with F12 toast variants) |
| `--text` on rail (a `.button.secondary` dropped into the toast) | 1.18 | latent, same fix |
| `#toast button:focus-visible` (not overridden; only `#toast a`) | 2.79 | FAIL (latent) |

### 1.10 terminal.css / terminal.js

| pair | ratio | verdict |
|---|---|---|
| body `--rail-text` on `--rail`; header on `--rail-2 #223a4a` | 13.52 / 10.17 | pass |
| `.brand-label` 11px `--rail-muted` on `--rail-2`; `.notice` 12px on `--rail` | 6.05 / 8.04 | pass |
| `#endpoint` / `#status` 12px mono `--accent-on-dark #6fc3de` on `--rail-2` | 5.95 | pass (but this is the "cyan mono status" F14/J8 replaced with `#b7c4cd`) |
| button `--rail-text` on `--rail-3 #2c4658`; hover on `--rail-line` | 8.49 / 8.27 | pass |
| **button border `--rail-line #31475a` vs its own fill `--rail-3`** / vs the header `--rail-2`; button fill vs header | **1.03 / 1.23 / 1.20** | **FAIL** — the buttons are identifiable only by their label text |
| `#disconnect` `--danger-on-dark #ffb4ad` on `--rail-2`; border; hover (blended `#4b343e`) | 6.99 / 6.99 / 6.66 | pass |
| focus `--focus-on-dark` vs `--rail-2` / `--rail-3` | 5.95 / 4.96 | pass |
| xterm theme (terminal.js line 5): fg `#e7eff2` on bg `#152631`; cursor `#79e8f6` | 13.32 / 10.85 | pass — but the theme bg `#152631` ≠ `--rail #172431` (1.02 seam) and the cursor is the legacy cyan; not re-tokenised |

### 1.11 Other opacity-based states found while scanning

| rule | effective colour | ratio | verdict |
|---|---|---|---|
| `.restore-target.disabled { opacity: .6 }` — the row's `<small>` reason (why a device can't be restored) | `#9da6ad` on white | ≈2.4 | FAIL — same class of bug as the menu reasons |
| `#discovery-file-list small { opacity: .85 }` (12px) | `#74818b` | 4.00 | FAIL (4.5 needed) |
| `.git-folder-icon.pending { opacity: .45 }` (icon) | | — | informational (icon, paired with the "pending" tag text) |
| `button:disabled { opacity: .5 }` on `.button.primary` | white on `#8eb7c6` | 2.16 | exempt (inactive control) — acceptable because the reason is carried by `title` + `.caption` (H2) |

---

## 2. Corrected values (verified)

| token / rule | now | corrected | resulting ratios |
|---|---|---|---|
| `--line-strong` | `#b9c6cf` | **`#74879a`** (J8) | 3.70 on surface, 3.29 on surface-2, 3.16–3.35 on the four tints; keep `--line #d9e1e7` for card edges/table rules |
| `--warn` | `#a85f00` | **`#8f5200`** (J8) | 5.63 on `--warn-soft`, 6.22 white-on-warn / on surface; `--warn-strong` may stay for pill text |
| focus | `outline: 3px solid var(--focus)` | **`--focus-ring:#0e4a63; :focus-visible{outline:2px solid var(--focus-ring);outline-offset:2px;box-shadow:0 0 0 2px var(--surface)}`** (J8) | ring 9.64 vs the white separator; separator 5.65 / 6.54 vs accent / danger fills |
| dark-surface scoping | `#toast a:focus-visible` only | **`#toast, .op-output, .git-file-content, .git-diff-columns pre, .vm-guide pre, #capture-screen { --muted: var(--rail-muted); --focus-ring: #9ad4ea; --surface: var(--rail) }`** so the separator becomes the dark surface | `#b7c4cd`/`#a9bcc8` 8.84/8.04; ring 9.74 |
| `--wire` | `#93a6b2` | **`#74879a`** | 3.70 on surface, 3.43 on cream |
| `.map-device.state-neutral .device-state-dot` | `fill: var(--line)` | **`fill: var(--surface); stroke: var(--neutral); stroke-width: 2`** (hollow "no state" ring, 5.51) or `display:none` when there is genuinely nothing to say | |
| `.menu-list button:disabled` / `.node-context-menu button:disabled` / `.restore-target.disabled` | `opacity: .55 / .5 / .6` | **`opacity: 1; color: var(--muted); cursor: not-allowed`** and `… .menu-reason, … small { color: var(--muted) }` | 5.51 |
| `#discovery-file-list small` | `opacity: .85` | remove the opacity (`color: var(--muted)`) | 5.51 |
| `.skeleton` | `--surface-2` + white shimmer | **`background: linear-gradient(90deg, var(--line), var(--surface-2), var(--line)); background-size: 200% 100%`**, animate `background-position`; static under reduced motion (J8) | 1.32 base (accepted floor) |
| terminal buttons | `#2c4658` fill, `#31475a` border | **`background:#223e4e; border:1px solid #74879a`** (J8) | 3.04 border vs fill; if `--rail-3 #2c4658` is kept use `#8497a8` (3.28) |
| terminal header/status | `--rail-2` bg, `#31475a` rule, `#6fc3de` status | J8: header `--rail`, rule `1px solid #2a4352`, `#status/#endpoint` `#b7c4cd`, disconnect `#f0a9a3` (8.18), focus `#9ad4ea` | all ≥ 8 |
| xterm theme | `background:'#152631', cursor:'#79e8f6'` | `background:'#172431'`, `cursor:'#9ad4ea'` (terminal.js, not CSS) | |

---

## 3. "Also check" items

| check | result |
|---|---|
| **No red for primary actions** | PASS. `.button.primary`, `.menu > summary.primary`, `.map-tools .button.primary`, `.node-actions .ssh-action`, `.drawer-actions .ssh-action`, `.side-button.side-primary`, `.workspace-choice-primary`, `.file-icon`, `.git-folder-icon.lab`, `.git-tag`, `.node-name:hover`, `.diagram-selected`, `#diagram-discard` (warn) are all accent/warn. Every `var(--danger*)` use (27) is semantic: `.button.danger/.danger-outline`, `.menu-danger`, `.pill.danger/.badge.bad`, `.banner.danger`, `.danger-zone`, `.deployment-nos.failed`, `.form-error`, `.debug-failure`, `.op-banner.bad`, `.device-state-dot` attention, `#toast .danger-outline`. |
| **Minimum font size 11px** | PASS at the 11px floor: smallest declared size is 11px (13 `font-size` + 1 `font:` shorthand in style.css, `.brand-label` in terminal.css); nothing smaller. **But J8 sets the floor at 12px** (only `.eyebrow` at 11px): `.menu-reason`, `.menu-list small`, `.node-context-menu button small` (the disabled-reason texts!), `.brand small`, `.side-label`, `.side-caption`, `.tag`, `.git-tag`, `.interface-label text`, `.device-label text`, `.unmatched-label`, `.topbar .worker-state` (≤760) and terminal `.brand-label` are 11px. Also below J8: `.button` 13px (J8 14), `.button.small` 12px (13), `th` 12px (13), `.node-name` 14px (15), `h1` 24px/650 (22px/700). |
| **Uppercase only on `.eyebrow`** | PASS in CSS: the only `text-transform` is `.eyebrow` (line 170). However the markup and JS templates still ship **literal capitals**: index.html lines 39, 92–98 ("NETWORK ENGINEERING WORKSPACE", "NODE WORKSPACE"…), operations.js:7, management.js ×5, git-progress.js:78, restore.js:73, workspace.html, debug.html, terminal.html `.brand-label` "CONTAINERLAB NODE MANAGER / SSH SESSION". J8/F13 drop the eyebrow from drawer/dialog heads; the CSS keeps `.drawer-head .eyebrow`, `.dialog-head .eyebrow`, `#home-continue .eyebrow` rules, which invites the markup to keep them. |
| **z-index ladder** | `thead th`/`.drawer-head` 1 → `.map-tools` 2 → `.extra-views-menu` 12 (legacy) → `.lab-switcher` dropdown / `.menu-list` / `.git-save-options` 20 → `.topbar` 30 = `#toast` 30 → `.map-expanded` 50 → `.node-context-menu` 100 → `<dialog>` top layer. Menus above sticky heads ✓, toast above menus ✓, context menu highest ✓, dialogs top layer ✓. **Inconsistency**: `#toast` (30) sits **below** `.map-expanded` (50) whose `box-shadow: 0 0 0 100vmax var(--backdrop)` covers it — toasts fired from the expanded map's More ▾ ("Back up all configurations", "Open all CLIs") are hidden. Carried over from the old sheet (same numbers); fix `#toast { z-index: 60 }`. Note also `.topology-stage .map-tools { z-index: 2 }` creates a stacking context, so the map "More ▾" `.menu-list` (20) is confined to z 2 inside the `overflow:hidden` stage — fine for its 3 items, but any longer menu there will be clipped. |
| **prefers-reduced-motion covers the pulse** | PASS: `*, *::before, *::after { animation: none !important }` disables `.pill.running::before`, `.worker-state::before` and `.skeleton::after` (also `display:none`). terminal.css has the same block. |
| **`:focus-visible` for button / a / summary / input / select / textarea / [tabindex]** | PASS: section 27 declares the global `:focus-visible`, the explicit `button, input, select, textarea, summary, a` list and `[tabindex="0"]`; SVG nodes/wires additionally get the accent stroke; `.node-context-menu button:focus-visible` restores a 2px inset ring after the `:focus { outline:none }` rule (same specificity, later → wins). Only `outline: none` uses are that rule and `.map-device:focus:not(:focus-visible)` — both replaced. The defect is the ring **colour/structure** (1.6), not coverage. |

---

## 4. Selector / hook coverage (css.md §20, spec §3, addendum §F, J3–J8)

Every hook in css.md §20 and every family in spec §3 has a rule (`.op-*`, `.git-*`, `.restore-*`, `.diagram-*`, `.capture-*`, `.job*`, `.device-download`, `.archive-download`, `.profile-card`, `.blank-state`, `.table-empty`, `.node-context-menu`, `.workspace-choice*`, `.debug-*`, `.vm-guide`, `.capture-viewer*`, `.empty-panel`, all 25 old ids, `[hidden]` + `.button[hidden]` + `.capture-dialog [hidden]`, `[tabindex="0"]:focus-visible`, `.topology-bg`, `.topology-grid-dot`, `.device-state-dot`, `.state-*` ×5, `.menu-reason`, `.pill`, `.banner`, `.empty-state`, `.lab-card`, `.device-row`, `.device-rail`, `.tool-card`, `.kv`, `.skeleton`). Documented dead CSS (`.dark`, `.full`, `.guide-row`, `#login-dialog`) is correctly gone. Classes used by markup/JS without a rule are all documented no-ops (`.close` JS hook, `.topology-map` class, `.row`, `.language-bash`).

**Missing** (the contract will emit them; the sheet has no rule):

| selector | contract | why it matters |
|---|---|---|
| `.pill.busy` (+ `::before` pulse 1.6 s) | J5 "pill class for in-progress states is `busy`", J8 | in-progress pills render as neutral grey with no pulse; `.running` keeps pulsing on `badge()` job rows instead |
| `.icon` (`svg.icon { width:16px; height:16px; fill:currentColor; flex:none; vertical-align:-3px }`) | J8 sprite `#i-info #i-clock …`, `class="icon"` | an inline `<svg>` without CSS size renders at 300×150 — banner/toast/menu glyphs explode the layout |
| `ul.tool-list`, `.tool-list li` | J8 "three cards + `ul.tool-list` More tools" | the second tier renders as a bulleted list |
| `.row-reason` | J7/F9 `<small class="row-reason" id="why-…">` | the inline reason under a disabled [Open CLI] has no size/colour (inherits 13px body, fine) but no block layout → wraps inline with the buttons |
| `.device-row[aria-current="true"]` | J7/F9 3px `--accent` left bar for the device open in the drawer | no cue which rail row is open |
| `.menu-button[aria-expanded="true"]` | J4 (button + sibling `.menu-list`, not `details`) | only `.menu[open] > summary` gets the open state; button menus show no pressed state |
| `.lab-switcher .menu-list` (left-aligned, `min-width:300px; max-height:min(60vh,520px); overflow:auto`) | J4 replaces `details#lab-switcher`; the sheet only styles `details.lab-switcher > :not(summary)` | with a button switcher the lab list becomes a 240px right-aligned menu with no max-height |
| `.map-device.state-working`, `.map-device.state-credentials` | J7 keys `ready|starting|attention|unavailable|credentials|working|neutral` | two states fall back to the base `--neutral` dot |
| `g.device-state-glyph` display rules per `state-*` | J7 (check / arc / bang / hollow) | state is colour-only (F2 blocker) |
| `.device-body:not([fill]) { fill: var(--accent) }`, `.device-label-bg:not([fill]) { fill: var(--ink) }` | J7 / F15 | when the renderer stops emitting `fill`, bodies and label plates become black |
| `@media (prefers-contrast: more)` (line-strong→muted, pills solid) and `@media (forced-colors: active)` (`.pill::before`, `.device-state-dot`, `.worker-state::before` `forced-color-adjust: none` or border-based dots) | J8 / F20 | in Windows High Contrast `background: currentColor` dots vanish, leaving text-only pills; tab underline survives (border) |
| `#toast.ok`, `#toast.danger` (left border `--ok`/`--danger-on-dark`, glyph) | F12 (accepted by J) | toast is single-tone |
| `#lab-banner-icon` / `.banner .icon` colour per tint (`--accent-strong` / `--warn-strong` / `--danger-strong` / `--ok-strong`) | J3 static children, J8 glyphs | glyph inherits `--text`; fine but the tint semantics are lost |

Dependency note: `.topology-bg:not([fill])` and `.topology-grid-dot:not([fill])` are inert until topology-render.js line 43 stops emitting `fill="#fdf6e3"` / the grid `fill` and starts emitting the classes (addendum §C); until then the map background stays cream and the `--wire` ratio is 2.33.

---

## 5. Deviations from J8/J3/J7 that are visual (not contrast) — for the fix pass

1. **Dark code panes**: `.op-output`, `.git-file-content`, `.git-diff-columns pre`, `.vm-guide pre` use `--rail`; J8: `--surface-2` + `1px solid var(--line)` + `--mono` 13px, dark only for `#toast` and terminal.html (F14 "hacker console" cue).
2. **Type**: `h1 24px/650` → `22px/700/1.2`; `h2/h3/h4/.brand/.card-title/.node-name` weight `650` → `600` (F10: system fonts have no 650); `.button` 13px → 14px, `.small` 12px → 13px; `th` 12px → 13px; `.node-name` 14px → 15px; `.tabs button` inactive weight 600 → 500 (J3 non-colour active cue).
3. **Layout tokens** (F1 blocker, J3): `--topbar-h` 52px (J3 48px), `.topology-stage { height: min(calc(100vh - 230px), 820px); min-height: 460px }` instead of `#lab-content` grid remainder + `min-height: 420px`; `#map-status` is a caption below the stage instead of a chip inside it; `--lab-header-h` absent. The map-below-the-fold arithmetic is unchanged from the spec that F1 rejected.
4. **Drawer** (J7): width `min(560px,100vw)` → `min(520px,100vw)`; `::backdrop` `.25` → `.12`.
5. **Grids** (J8): `.lab-grid repeat(3,…)`, `.tool-grid repeat(2,…)` → `repeat(auto-fill, minmax(320px, 1fr))`.
6. **Skeleton** (J8/F8): see 1.7.
7. **Eyebrow rules** for drawer/dialog/home-continue heads retained (J8: diagnostics page only).
8. **terminal.css** tokens (1.10): header `--rail-2`, rule `#31475a`, cyan status, `--rail-muted #a9bcc8` vs J8 `#b7c4cd`, disconnect `#ffb4ad` vs `#f0a9a3`, focus `#6fc3de` vs `#9ad4ea`; terminal.js theme not tokenised.
9. `--focus-on-dark #6fc3de` is 1.99:1 on `--surface` — harmless while it is only used on dark scopes; do not reuse it on light.

---

## 6. What is right (keep)

- Text tokens clear ≥ 4.7:1 on every light surface including all four tints and all captions; `-strong` pill inks give 6.3–7.6:1 headroom.
- Semantic colour: one teal primary, red only for danger/failed, green/amber/grey for state; `.badge good|bad|warn|running|platform` aliases kept.
- `[hidden]` beats `.button{display:inline-flex}`; `.capture-dialog [hidden]`, `.node-context-menu[hidden]` kept; `:has()` split-button rule kept with the same behaviour as before.
- Focus coverage is complete (global + explicit list + `[tabindex="0"]` + SVG strokes); reduced-motion kills every animation and transition; dialogs use the top layer; sticky heads sit under menus.
- Dark-surface tokens (`--rail-text`, `--rail-muted`, `--accent-on-dark`, `--danger-on-dark`, `--focus-on-dark`) all ≥ 7.9:1 where they are applied.
