# Critique — visual system and accessibility (DESIGN-SPEC.md §3, addendum §F, brief "Visual design / Color / Typography / Icons / Responsive / Accessibility")

Score: **5.5 / 10**. The token palette is restrained and correctly assigns meaning to colour (teal primary, one red, green/amber/grey states, light drawer head) and the component list matches the brief's requested pattern library. But the spec fails four things the brief states as hard requirements: (1) the 1366×768 fit arithmetic does not close, (2) map node state is colour-only for sighted *and* screen-reader users, (3) two token pairings and every UI-component boundary fail WCAG contrast, and (4) the menu/tab ARIA is either invalid or underspecified. Several smaller choices (uppercase eyebrows, a 7-tile Tools grid, dark "rail" code panes, cyan/coral terminal chrome carried over) reintroduce exactly the ERP / dashboard / terminal-theme feel the brief forbids.

Method: every hex in §3 was run through the WCAG 2.x relative-luminance formula (`scratchpad/contrast.py`, `contrast2.py`); heights were computed from the type scale in §3 and checked against the 1366×768 screenshots in `shots/before/`; the menu pattern was checked against the current `topology.js` node-menu code (the addendum says to reuse it) and the test contracts in `inventory/tests.md`.

---

## 1. Contrast audit of every pairing the spec implies

| Pairing (fg on bg) | Ratio | Verdict | Where it is used |
|---|---|---|---|
| `--text #24313c` on bg / surface / surface-2 | 12.27 / 13.29 / 11.81 | pass | body |
| `--ink #172430` on bg / surface / surface-2 | 14.56 / 15.77 / 14.01 | pass | headings |
| `--muted #5b6b76` on bg / surface / surface-2 | 5.09 / 5.51 / 4.90 | pass (12px caption OK) | metadata |
| white on `--accent` / `--accent-strong` | 5.65 / 7.32 | pass | `.primary` |
| white on `--danger` / `--danger-strong` | 6.54 / 8.91 | pass | `.danger` |
| white on `--ok` | 5.32 | pass | (if ever used) |
| white on `--warn #a85f00` | 4.88 | pass, thin margin | (if ever used) |
| `--accent` on `--accent-soft` (`.pill.running`, `.banner.info` text) | 4.85 | pass | |
| `--ok` on `--ok-soft` (`.pill.ok`) | 4.67 | pass | |
| **`--warn` on `--warn-soft` (`.pill.warn`, "Starting")** | **4.41** | **FAIL (< 4.5, 12px/600 is not "large")** | every Starting pill, warn banner label |
| `--danger` on `--danger-soft` | 5.58 | pass | |
| `--neutral` on `--neutral-soft` | 4.78 | pass | |
| `--accent` on surface (links, `.tabs .active` underline, `.danger-outline`) | 5.65 | pass | |
| `--focus #1d6f8e` on bg / surface / surface-2 / soft tints | 5.22 / 5.65 / 5.02 / 4.8–5.1 | pass | |
| **`--focus` on `--rail #172431`** | **2.79** | **FAIL 1.4.11 (< 3:1)** | toast buttons, terminal chrome, code-output `<pre tabindex=0>` |
| **`--focus` on `--accent` / `--danger`** | **1.00 / 1.16** | fails unless the 2px offset gap is *guaranteed* to be surface-coloured (see F3) | focused `.primary` / `.danger` |
| **`--muted` on `--rail`** | **2.86** | **FAIL** | any secondary text in toast / dark panes (no dark-surface text token exists) |
| **`--line-strong #b9c6cf` on surface** (`.secondary` border, inputs) | **1.74** | **FAIL 1.4.11** — the border is the *only* thing that says "this is a button/field" when the fill equals the surrounding card | every secondary button, every input |
| `--line #d9e1e7` on surface | 1.32 | acceptable for decorative dividers / card edges only | |
| `--surface-2` on `--surface` (skeleton shimmer, menu hover) | 1.13 | too faint to be perceived as a shimmer or a hover state by low-vision users | `.skeleton`, `.menu-list button:hover` |
| `--ok` vs `--warn` vs `--danger` vs `--neutral` (dot vs dot) | 1.04–1.34 | all four state colours sit at luminance 0.11–0.17; they are distinguishable **only by hue**, i.e. invisible to deuteranopes when no text accompanies them | map `.device-state-dot` |
| `--ok #1f7a4d` dot on the renderer's default node body `#0066ff` | ≈1.10 | the dot disappears against the node icon | map |

Corrected values (verified):
- `--warn: #8f5200` → 5.63 on `--warn-soft`, 6.22 white-on-warn, 5.74 on bg. (Alternative that keeps `#a85f00`: `--warn-soft:#fff7ea` gives only 4.59 — too thin; change the ink, not the tint.)
- `--line-strong: #74879a` → 3.70 on surface, 3.29 on surface-2, 3.42 on bg. Use it for `.secondary` borders, `input/select/textarea` borders and the `.tabs` underline track; keep `--line #d9e1e7` for card edges, `hr`, table rules.
- Add `--muted-on-dark: #b7c4cd` (8.84 on rail) and `--focus-on-dark: #9ad4ea` (9.74 on rail); scope them with `.toast, .terminal-chrome, .op-output, [data-surface="dark"] { --muted: var(--muted-on-dark); --focus: var(--focus-on-dark); }`.
- Skeleton: gradient `--line → --surface-2 → --line` (1.32 vs surface, 1.18 vs surface-2); menu hover/focus: `--surface-2` **plus** a 3px inset accent bar or the global ring — never background alone.

---

## 2. Findings

### F1 — BLOCKER — §3 Layout: the 1366×768 arithmetic does not close; the map is still below the fold
Spec: top bar 52px; stage `min(calc(100vh - 230px), 820px)`, `min-height:460px`; claim "header+tabs ≤ 200px so the map is visible at 1366×768".

Computed from the spec's own type scale (h1 24px ≈ 30px line, status line 14px×1.5 = 21px, buttons 36px, padding 16px, banner 14px line + 10/10 padding + 4px border, tabs 36px + 1px + 16px margin, content top padding assumed 20px):

| Row | Height |
|---|---|
| top bar | 52 |
| content top padding | 20 |
| `.lab-header` (title + status line, actions inline) | 89 |
| `.banner` (+12 margin) | 57 |
| `.tabs` (+16 margin) | 53 |
| **chrome before the map** | **271 with banner / 214 without** |

At a *nominal* 768px viewport `calc(100vh - 230px)` = 538 → map bottom at 271 + 538 = **809px, 41px past the viewport**, before the `#map-status` caption (~24px) and bottom padding. On a real 1366×768 Windows laptop (taskbar 40px + Chrome chrome ~71px → `innerHeight ≈ 657`) the formula gives 427 → clamped to 460 → bottom at **731px on a 657px viewport**; the student scrolls ~120px to see the bottom of the map and the caption. The "≤ 200px" sentence ignores the 52px top bar and the banner entirely, and 230 is not derived from anything. The audit's core complaint (map off screen at 1366×768, `UX-AUDIT.md §1`) survives the redesign on paper.

Fix — replace the magic number with a grid remainder and pin every chrome height:
- `--topbar-h:48px` (32px content + 8/8). `--lab-header-h:68px` = h1 22px/1.2 (26px) + status line 14px/1.5 (21px) + 4px gap + 8/8 padding, actions (36px) on the same row, right-aligned (they wrap under only ≤ 900px, +44px). `--banner-h:40px` single line (actions rendered as inline `.link-button`s, no second row), margin-bottom 12px. `--tabs-h:41px` (40px buttons incl. 2px underline + 1px rule), margin-bottom 12px. Content top padding 16px.
- `#lab-content{display:grid;grid-template-rows:auto auto auto minmax(0,1fr);min-height:calc(100dvh - var(--topbar-h))}`; `.topology-stage{min-height:420px}`; `#map-status` becomes a chip overlaid bottom-left *inside* the stage so it consumes no row.
- Resulting chrome: 48+16+68+53 = **185px** (no banner) / **237px** (banner). Map height: nominal 768 → 583 / 531; realistic 657 → 472 / 420; 1920×1080 → 871 (capped at 820, leaving 75px, fine). ≥ 460 everywhere except the realistic-viewport-with-banner case (420) — accept 420 as the floor, or add `@media (max-height:700px){.banner{--banner-h:32px;padding:6px 12px}}`.
- State these numbers in §3 and add a Playwright assertion: at 1366×768 `#topology-map.getBoundingClientRect().bottom ≤ innerHeight`.

### F2 — BLOCKER — §3 Map / addendum §C: device state on the map is colour-only, and screen readers get no state at all
Spec: `circle.device-state-dot` at `cx=16 cy=-16 r=5` filled `--ok/--warn/--danger/--neutral`; nothing else changes. Brief: "Do not rely on color alone. Use text/icons/state labels as well." and "Node appearance should communicate state visually: booting / ready / stopped / inaccessible / configuration operation running / problem."

Problems: (a) the four state fills have near-identical luminance (table above) — for a deuteranope Ready/Starting/Needs attention are the same dot; (b) at `r=5` on a 40-unit body the dot is 5px when the map is fitted for a 10-node lab; (c) it sits *on* the body corner (`cx=16` inside a ±20 body) whose renderer default fill is `#0066ff` → ≈1.1:1 against green; (d) the node's `aria-label` stays "Open PTX1 actions" — a screen-reader user tabbing the map never hears "Ready" or "Needs attention"; (e) "configuration operation running" (restore busy) has no map state at all.

Fix:
- Move the dot outside the body: `cx=r+4, cy=-(r+4)` (i.e. 24,−24), `r=7`, `stroke:var(--surface);stroke-width:2.5` (white halo → readable on any imported icon colour), scale with `vector-effect:non-scaling-stroke`.
- Give each state a **shape**, not just a fill, inside the dot: ready = filled dot with a 2px check path; starting = ring with a 90° arc (`stroke-dasharray`, rotates under `@media (prefers-reduced-motion:no-preference)`); attention = filled dot with `!` (two tiny rects); unavailable = hollow grey ring; working (restore/backup running on this node) = same arc in `--accent`. Four glyph paths, ~10 lines of SVG in `topology-render.js`.
- Append the state to the label pill text when not Ready ("RTR3 · Starting") — the label bg is already the dark `#454545`, white 12px text reads at 8+:1 — and always to the accessible name: `aria-label="PTX1 — Ready. Open device"` updated inside `applyMapStates()`; put the student sentence (`deviceState(node).detail`) in `<title>`.
- Add `state-working` to the class list (addendum only maps deviceState keys).

### F3 — MAJOR — §3 Focus: one `--focus` colour cannot work on both light and dark surfaces, and the spec does not guarantee the gap that makes it visible on primary/danger buttons
`:focus-visible{outline:3px solid var(--focus);outline-offset:2px}` with `--focus = --accent`. On a `.primary` button the ring is the button's own colour (1.00:1); it is perceivable only because `outline-offset:2px` leaves a 2px gap of the *underlying* surface. That works on white cards (ring 5.65 vs surface) but breaks (i) on `--rail` surfaces — toast buttons, terminal chrome, the `<pre tabindex="0">` operation output — where both the gap and the ring sit on navy: 2.79:1, fails 1.4.11; (ii) on `.banner.info` (accent-soft) the ring is 4.85 — fine — but the gap is accent-soft and the primary button inside the banner is accent → gap contrast 4.85, OK; (iii) inside `.menu-list` where `overflow` clips a +2px outline, and the existing node-menu rule shows focus by background only (`#edf5f6` ≈ 1.1:1, `outline:none`) — the addendum tells implementers to copy that code.

Fix: two-tone indicator that is self-sufficient on any background: `:focus-visible{outline:2px solid var(--focus-ring);outline-offset:2px;box-shadow:0 0 0 2px var(--surface)}` with `--focus-ring:#0e4a63` (9.64:1 vs surface, 8.27 vs accent-soft, 8.9 vs bg). Against the accent and danger fills the ring itself is only 1.71 / 1.47:1 — which is why the 2px white `box-shadow` separator is mandatory: it makes white the colour adjacent to the ring on *both* sides, so the indicator is the white gap + dark ring, each ≥ 3:1 against its neighbour. On `--rail` the dark ring drops to 1.63:1, so dark surfaces switch to `--focus-on-dark:#9ad4ea` (9.74 vs rail) via the scoped override in §1, with the separator becoming `var(--rail)`. For SVG nodes/wires (no `box-shadow`): `.map-device:focus-visible .device-body{stroke:var(--focus-ring);stroke-width:3;paint-order:stroke}` plus a second white stroke ring via a `<use>` or filter; addendum §F's `[tabindex="0"]:focus-visible` must name these rules. Menu items: `outline-offset:-3px` so the ring is not clipped; hover and focus both set `--surface-2` **and** the ring. Never `outline:none` without a ≥ 3:1 replacement.

### F4 — MAJOR — §3 Tokens: `--warn` on `--warn-soft` fails AA (4.41:1) for the "Starting" pill and warn banner
Every booting device and every starting lab wears this pill. Fix: `--warn:#8f5200` (5.63:1 on `--warn-soft`, 6.22 white-on-warn). Keep `--warn-soft:#fff2dc`.

### F5 — MAJOR — §3 Buttons / inputs: `--line-strong #b9c6cf` boundaries are 1.74:1 — secondary buttons and inputs on a white card have no perceivable edge
WCAG 1.4.11 requires 3:1 for the visual boundary that identifies a control when nothing else does. `.secondary` = surface bg + line-strong border on a surface card: the only cue is the 1.74:1 border. Same for `input/select/textarea` (spec gives no field style at all — a gap in itself). Fix: `--line-strong:#74879a` (3.70 on surface) for control borders only; add a field spec: `input,select,textarea{min-height:36px;border:1px solid var(--line-strong);border-radius:var(--radius);background:var(--surface);padding:0 10px;font:inherit}` + `::placeholder{color:#6b7c88}` (4.32:1 — placeholders are exempt but keep them readable) + `:disabled{color:var(--muted);background:var(--surface-2)}` (4.90).

### F6 — MAJOR — §0.7 / §3 Menus / addendum A.15: the `details/summary` menu contract is incomplete and partly invalid; specify it fully or use `button + [role=menu]`
What the spec says: "keyboard-operable (close on Escape and outside click)", `summary aria-haspopup="menu"`, `.menu-list role="menu"`, items `role="menuitem"`, "Arrow keys move focus (reuse the node-menu pattern)". What is missing or wrong:
1. `aria-expanded` is never mentioned. Browsers expose `<summary>` as a disclosure with an expanded state, but once you add `role="menu"` to the list, SR users expect a menu *button*; without `aria-expanded` mirrored on the summary (set in the `toggle` handler) NVDA/JAWS announce a collapsed disclosure and then a menu appears with no relationship.
2. No focus management: on open, focus must move to the first enabled `menuitem`; on close (Escape, item activation, outside click, `focusout` to outside) focus must return to the summary — unless the item opened a `<dialog>`, in which case the dialog's close returns focus to the summary because that is what was focused when `showModal()` ran. Say so, or every menu action strands focus at `<body>`.
3. Tab must close the menu without `preventDefault` (roving focus leaves the menu); the node-menu code being copied handles ArrowUp/Down/Home/End only.
4. Escape must `stopPropagation()` so the map's Escape (close expanded map) and the node menu chain (addendum A.14) do not also fire.
5. `hr.menu-sep` needs `role="separator"`; `.menu-danger` needs `role="group" aria-label="Destructive actions"` so the visual separation is announced.
6. Disabled items: `disabled` buttons are skipped by Tab *and* by the copied arrow-key code (`buttons` filter?), so the `.menu-reason` text the addendum adds is unreachable by keyboard focus — acceptable only because it is visible text; state explicitly that the reason is a visible `<small>`, not a `title`.
7. `summary::-webkit-details-marker{display:none}` is required in addition to `list-style:none` (Safari); the summary needs `min-width:36px;min-height:36px` for the icon-only "▾" variants (`#git-save-menu`, `#lab-switcher`).
8. Outside-click: listen on `pointerdown` in the capture phase (a `click` listener fires *after* the summary's own toggle, re-opening the menu you just closed when clicking another summary).
9. `details[name]` (exclusive accordion) must not be relied on for "one menu open at a time" — Firefox < 130 and the harness do not support it.

Fix: add a "Menu contract" block to §3 with the nine points above and a single `initMenu(details)` in `app.js` used by `#manager-menu`, `#lab-actions-menu`, `#git-save-menu`, `#lab-switcher`, map "More ▾", Progress "More ▾", Tools cards. Prefer `<button class="button" aria-haspopup="menu" aria-expanded="false">` + `<div class="menu-list" role="menu" hidden>` for all *new* menus (no disclosure/menu double semantics, no marker hacks) and keep `details` only for `#git-save-menu`, whose `ontoggle` is a harness contract (`inventory/tests.md` §1).

### F7 — MAJOR — §1.3 / §3 Tabs: `aria-selected` on plain `<button>`s inside `<nav>` is invalid ARIA (already true today, app.js line 93)
`aria-selected` is only permitted on `gridcell`, `option`, `row`, `tab`. axe flags `aria-allowed-attr`; SRs ignore it, so the active tab is conveyed by the underline colour only. Either implement the tabs pattern — `div.tabs[role=tablist][aria-label="Lab views"]`, `button[role=tab][id=tab-topology][aria-controls=topology-view][aria-selected][tabindex=0|-1]`, panels `[role=tabpanel][aria-labelledby=tab-…][tabindex=0]`, Left/Right/Home/End roving in `showTab` — or keep `nav` and switch to `aria-current="page"` (each tab is a hash route, so this is honest). Pick the tablist: the panels already exist and the addendum's `showTab` is the one place to add four key handlers. Also give the active tab a non-colour cue (the 2px underline in `--ink`, plus 600 weight vs 500 inactive — spec has both at 600).

### F8 — MAJOR — §3 Skeleton: an invisible shimmer with no ARIA is worse than no skeleton
`surface-2` on `surface` is 1.13:1 — the placeholder blocks will not be perceived on most laptop panels. Nothing says `aria-busy`, nothing hides the blocks from SRs, nothing prevents a 100 ms flash on a fast `/state`. Fix: blocks in `--line` with a `--line → --surface-2 → --line` gradient (honouring `prefers-reduced-motion`: static block, no animation); container `#lab-cards[aria-busy="true"]`, blocks `aria-hidden="true"`, one visually-hidden `<p role="status">Loading your labs…</p>`; render only after a 200 ms delay; exactly 3 cards whose box height equals the real `.lab-card` (name row 22 + pill row 20 + 2 meta rows 40 + button 36 + gaps/padding = ~190px) to avoid layout shift; and add the same treatment to the lab header + stage when the page is deep-linked with `#lab=<id>` before the first `/state`.

### F9 — MAJOR — §1.3 / §3 Device rail and device rows: the disabled "Open CLI" explains itself only by `title`
Brief: "Do not simply leave the button disabled with no explanation." Spec §1.3 gives the Devices tab an inline explanation but the rail rows get "name, state pill, [Open CLI]" only; a `title` is invisible to keyboard and touch users and unreadable on disabled buttons in Firefox. Fix: rail rows are `<li>` in `<ul aria-label="Devices">`; when `deviceState.cli===false` render `<small class="row-reason" id="why-RTR3">RTR3 is still starting.</small>` and `aria-describedby="why-RTR3"` on the button; the row for the device open in the drawer gets `aria-current="true"` + a 3px `--accent` left bar. Rail width 280px, gap 16px (map keeps 1022px at 1366).

### F10 — MAJOR — §3 Type: sizes drift small and weights are unavailable; the brief asks for scannable device names and no tiny grey metadata
- `650` weight: Segoe UI / Roboto / Arial have no 650; browsers synthesise or snap inconsistently across Windows/macOS/Linux. Use 600 for h2/h3/buttons and 700 for h1.
- Buttons at 13px make "Save progress" — the single most important control — smaller than body text. `.button` 14px/600; `.small` 13px.
- Device names have no rule. Add `.node-name{font-size:15px;font-weight:600;color:var(--ink);letter-spacing:.01em}` and use it in the rail, device rows, drawer h2 (20px) and map label; never mono (mono device names read as "container IDs").
- `h1` 24px with no line-height; set 1.2. `th` 12px muted + `.caption` 12px + pills 12px + eyebrow 11px: that is five things at ≤ 12px on one screen — the audit's "10px everywhere" problem shrunk by one step. Cap: `th` 13px, `.caption` 12px only for timestamps, nothing at 11px except the eyebrow (and see F13).

### F11 — MINOR — §3 Pills: "running: animated pulse" is ambiguous and, applied to every Running lab card, reads gamified
`labState.pill` has both `ok` (Running, steady) and `running`; §3 says `.running` pulses. If Running labs pulse, Home with five running labs has five blinking dots — the "toy-like" tell. Rule: the pulse means **in progress only** (`working`/`saving`/`starting`), never a steady state; rename the class `.busy`, cap at one pulsing element per surface (header pill or banner, not both), 1.6 s ease, disabled under reduced motion (spec says so — keep). `.pill` text 12px/600 + dot is correctly not colour-only; add `aria-hidden="true"` on the dot span.

### F12 — MINOR — §3 Banner / toast: colour classes without a textual or iconic prefix, no live-region roles
`.banner.warn/.danger/.ok/.info` differ by a 4px border and tint — hue-only for the same deuteranope. Prefix each with a 16px inline SVG glyph (info-circle, clock/arc, triangle-!, check) `aria-hidden` and let the sentence carry the meaning (spec copy already does). Roles: `#lab-banner` `role="status" aria-live="polite"` for info/ok/starting; `role="alert"` when it switches to `.danger` (attention, VM unreachable, save failed). `#toast`: `role="status"` for success, `role="alert"` for failures; add `.toast.ok/.danger` variants (left border + glyph) — today it is single-tone navy with a cyan border (the cyberpunk accent) and the spec keeps "dark rail bg" without saying the border colour changes.

### F13 — MINOR — §3 `.eyebrow` uppercase heads reintroduce the ERP look
The "before" screenshots' most admin-console elements are the tracked-uppercase eyebrows ("NETWORK ENGINEERING WORKSPACE", "NODE WORKSPACE", "NODE MANAGER"). The spec keeps the pattern for the drawer and dialog heads ("Device"). Brief: "Avoid excessive uppercase." Drop the eyebrow from the drawer (the h2 device name plus the platform · state line already says it is a device) and from dialog heads; keep uppercase only for `th` if at all (and then 12px/600, `.04em`, not `.08em`). `.eyebrow` may stay as a class for the diagnostics page.

### F14 — MINOR — §3 `--rail` dark surfaces inside the light UI = terminal-theme leakage; terminal.css keeps coral + cyan
Spec: `--rail` for "toast, terminal chrome, code output". Dark navy `<pre>` blocks inside white cards (operation output, action logs, Git technical details) are the "hacker console" cue the brief lists under cyberpunk. Use `--surface-2` + `--mono` 13px + `--line` border for all in-page code/output; reserve dark surfaces for the toast and `terminal.html` only. And "keep `terminal.css` separate but re-tokenised" gives no targets: today it is navy `#152631`, coral 2px header rule `#f15b40`, cyan mono status `#79e8f6`, peach disconnect. Specify: header bg `--rail`, rule `1px solid #2a4352`, status/endpoint mono in `--muted-on-dark #b7c4cd`, buttons `#223e4e` bg + `#74879a` border, disconnect = `.danger-outline` on dark (`#f0a9a3` text, 8.06:1 on `#152631`, 7.49 on the header `#182c38`), focus `--focus-on-dark`.

### F15 — MINOR — §3 Map surface: the renderer still emits a cream `#fdf6e3` background and `#0066ff` node bodies; the spec's "surface bg, subtle dot grid" cannot happen
`topology-render.js` line 43 always writes `fill="#fdf6e3"` and line 21 defaults `iconColor` to `#0066ff`. Addendum §C says fills are emitted only when the drawing defines them — good — but the node default is not covered, and pure blue `#0066ff` next to the teal accent is the one "rainbow" clash on the hero surface. Emit `fill` only when `n.iconColor` is set; CSS default `.device-body{fill:var(--accent)}`; `.device-label-bg` default `fill:var(--ink)`; grid dots `fill:var(--line-strong)` at `r=1`. Keep imported colours winning (they are the student's own drawing).

### F16 — MINOR — §1.3 Tools tab: a 7-tile card grid is the "more dashboards" the brief forbids
Packet capture, Telemetry, Backups, Open all CLIs, Export sessions, Lab files, Diagram exports as equal `.tool-card`s reads as a Bootstrap admin tile wall, and three of them are one-button utilities. Two tiers: three real tool cards (Capture, Telemetry, Backups — each with its status sentence and primary button) in a 3-column grid, then a compact `<ul class="tool-list">` "More tools" with a one-line description and a `.secondary.small` button each. Lab grid: `1100px` breakpoint gives 3 → 2 columns; at 1366 with 24px gutters three cards are 423px wide — fine; at 1100–1280 two columns of 520px look empty — use `repeat(auto-fill,minmax(320px,1fr))` instead of fixed column counts.

### F17 — MINOR — §1.2 Lab cards: the Continue card duplicates the only card when one lab exists; favourites have no non-colour marker
With a single lab, Home shows "Continue clabllm-dev [Open lab]" directly above "clabllm-dev … [Open lab]" — redundant and toy-like. When `labs.length === 1` render only the Continue card (it already carries state, readiness, saved time). "Favourites first" — how is a favourite shown? If by a star glyph, it must be a real `<button aria-pressed>` with an accessible name ("Favourite lab"), 16px SVG, `--warn` fill only when pressed, plus `title`. Card semantics: `article` with `h3` as the accessible landmark is right; keep the whole card non-clickable (brief: no clickable divs) — the addendum's right-click/Shift+F10 context is fine as an *additional* path.

### F18 — MINOR — §1.4 / §3 Drawer: a modal drawer with a dark backdrop over the map contradicts "topology is central"; the close control is unspecified
`dialog.drawer` opened with `showModal()` dims and blocks the map; to look at another router the student closes, re-finds the node, clicks — three steps per device. Keep `showModal()` (focus trap, Escape, focus return are free) but set `dialog.drawer::backdrop{background:rgba(23,36,48,.12)}` so the map stays legible, width `min(520px, 100vw)` at ≤ 1440 (the current 560px covers the rail at 1366), and add "Previous / Next device" `.ghost.small` buttons in `.drawer-head` (they call `openDetails()` — no new state). The close control must be a `<button class="icon-button" aria-label="Close device panel">` with a 16px SVG ×, 36×36, not the current 24px glyph.

### F19 — MINOR — §3 Icons: the spec has no icon system, so implementers will reach for Unicode glyphs and emoji
Brief: icons may supplement CLI / Save / History / Capture / Telemetry / Settings, labels always present. §3 uses "↗", "▾", "+", "−" only. Without a rule the microcopy sweep will introduce ✓ ✗ ⚠ ⟳ (already in §1.5: "Restored ✓") which render inconsistently and get read aloud as "check mark" or "heavy ballot X". Specify an inline `<svg><symbol>` sprite in `index.html` (12 symbols: terminal, save, history, capture, telemetry, settings, check, alert, info, clock, external, chevron), `class="icon"` 16px `fill:currentColor`, `aria-hidden="true"`, used via `<svg class="icon"><use href="#i-terminal"/></svg>`; text glyphs banned in student-facing strings; `esc()`-safe because the markup is constant.

### F20 — MINOR — §3 Breakpoints and sizes: a few concrete gaps
- `.button.small` 30px is fine (≥ 24px target); icon-only summaries and `.icon-button` need `min-width/height:36px`.
- `dialog` `max-height:90dvh` ✓; also `dialog{margin:auto}` and `::backdrop` token; the drawer must set `max-height:100dvh` (mobile URL bar).
- Tabs "scroll horizontally ≤ 900px": add `scrollbar-width:thin` and a right-edge fade, and make sure the active tab is scrolled into view in `showTab`.
- `@media (prefers-contrast:more)`: bump `--line-strong` to `--muted` and pills to solid fills — cheap and worth a line.
- Print/`forced-colors`: `.pill` dot and `.device-state-dot` need `forced-color-adjust:none` or an outline so Windows High Contrast keeps a marker.

---

## 3. What is right (keep)
- One primary hue (teal-blue), red reserved for danger/failed, green/amber/grey for state — exactly the brief's colour semantics; no rainbow.
- Text tokens (`--ink`, `--text`, `--muted`) all clear 4.9:1 on every light surface, including 12px captions.
- Light, sticky drawer head (the navy drawer head was the strongest "ops console" element in the old UI).
- Pills carry a dot **and** text; `.badge` aliases keep the old markup working.
- Native `<dialog>`, real `<button>`s, `:focus-visible` everywhere, reduced-motion media query, `dvh` units, 24px→16px gutters at 900px, drawer/dialog full-width at 760px.
- The component vocabulary (`.card`, `.pill`, `.banner`, `.empty-state`, `.menu`, `.drawer`, `.kv`, `.skeleton`) is the brief's pattern list one-for-one, and §3 insists every legacy family stays styled.

## 4. Priority order for the spec author
F1 (layout maths) and F2 (map state) are blockers because they are the two things a student sees first. Then the token corrections (F4, F5, F3 dark-surface focus, `--muted-on-dark`) — a five-line change to `:root`. Then the ARIA contracts (F6 menus, F7 tabs, F9 rail reasons, F8 skeleton). The remaining items are polish that decide whether the result reads "calm lab environment" or "admin console with a new palette".
