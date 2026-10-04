# Header control, chip, save and upload flow, first save

Design slice for [PROMPT.md](../PROMPT.md) sections 5.1, 5.2, 5.3, 5.6, 5.9, 5.10 and 6.5; boards G01, G10,
F02, G11, F04 (its Upload / Not now head only), F05, F06, F12, F13, F14, F16. Written against
`claude/git-save-load-redesign` at base release 1.30.60.

Paths are relative to `clab-backup-ui/` unless they start with `docs/` or `deploy/`. A citation reads
`path:line`. Not in this slice, and named where they touch it: the Load flow (Load designer), the drawers and
the removal of the Progress tab (drawer designer), the folder model, the folder chooser and every backend
decision (lead).

Lines marked **NEEDS (backend)** are requests to the lead; each names the smallest field or route that would
do and what the page does until it exists.

## 0. Decisions in one screen

1. The header gets one flat group: chip, **Save**, **Load**, then *Lab actions*. The chip and the Load button
   are popover openers built on a new `initPanel()` in `shell.js`, a sibling of `initMenu()` that shares
   `closeMenus()`, so "one panel or menu open at a time", outside click and Escape come from the code that
   already does them.
2. The chip is static markup (a dot span and a text span): only `className` and `textContent` change on the
   4 s poll. The panel has a static title and a body rendered with a keyed markup setter that keeps focus and
   typed text.
3. One pure function, `saveChipState(lab, ctx, now)` in `status.js`, decides the state. Precedence: Loading,
   Saving, Partial, Can't save, Failed, Waiting, Running, Saved, Not saved. It was run against today's
   `status.js` (section 3.6).
4. **Save** posts the save at once with an empty `note`. The chip panel opens (F02), and when the save ends
   it shows the upload sentence (G11), the toast (F14) or the reason it stopped (6.5).
5. **Upload** in the panel and in the *What changed* drawer are the same handler and end in
   `gitReviewJob(job, {upload: true})`, which stays the only place in the static scripts that writes
   `{push: true, reviewed: true}`.
6. A new script `save-header.js` holds the header rendering, the chip panel views and the first save. The
   header split menu, the "What changed?" label dialog and the first-save dialog retire.

## 1. The header control

### 1.1 What is there today

- The lab header is `header.lab-header` with the title block and `div.lab-header-actions`
  (`app/static/index.html:72-105`). The actions hold `div.git-save-control` (the **Save progress** button
  `#git-save-progress` and the `details#git-save-menu` split menu, `index.html:75`) and the *Lab actions*
  menu (`index.html:76-103`).
- `#lab-progress` is the third span of the status line (`index.html:73`); `renderLabHeader()` writes
  `progressSummary()` into it (`app/static/app.js:103`).
- `renderGitProgress()` sets the label, `disabled` and `title` of `#git-save-progress` and `#progress-save`
  and hides the split menu for an unbound lab (`app/static/git-progress.js:199-203`).
- CSS: `.lab-header` and `.lab-header-actions` (`app/static/style.css:454-474`), the desktop action column
  `--lab-action-col: 26rem` from 901 px (`style.css:886-890`), `.lab-header-actions { flex-basis: 100% }` at
  900 px and narrower (`style.css:2388`), the split control (`style.css:649-707`).

### 1.2 Markup

This replaces the content of `div.git-save-control` and removes `<span id="lab-progress">`. The whole group
is static in `index.html`; nothing in it is rendered with `innerHTML` except the two panel bodies
(DESIGN-SPEC-ADDENDUM J3: "Header, banner, tabs and menus are never re-rendered with innerHTML").

```html
<div class="lab-header-actions">
  <div class="save-control" id="save-control">
    <span class="save-pair">
      <span class="menu save-menu">
        <button type="button" class="button secondary panel-button save-chip" id="save-chip" aria-haspopup="dialog" aria-expanded="false" aria-controls="save-panel"><span class="save-dot none" id="save-chip-dot" aria-hidden="true"></span><span class="save-chip-text" id="save-chip-text">Not saved yet</span><svg class="icon" width="16" height="16" aria-hidden="true"><use href="#i-chevron"></use></svg></button>
        <div class="save-panel" id="save-panel" data-panel role="dialog" aria-labelledby="save-panel-title" hidden>
          <h2 class="save-state" id="save-panel-title" tabindex="-1" data-panel-focus><span class="save-dot none" id="save-panel-dot" aria-hidden="true"></span><span id="save-panel-title-text"></span></h2>
          <div id="save-panel-body"></div>
        </div>
      </span>
      <button type="button" class="button primary" id="git-save-progress" aria-describedby="save-reason">Save</button>
    </span>
    <span class="menu load-menu">
      <button type="button" class="button secondary panel-button" id="load-button" aria-haspopup="dialog" aria-expanded="false" aria-controls="load-panel">Load</button>
      <div class="save-panel wide" id="load-panel" data-panel role="dialog" aria-label="Load a saved state" hidden><div id="load-panel-body"></div></div>
    </span>
  </div>
  <span class="menu"><!-- Lab actions: unchanged, index.html:76-103 --></span>
  <small class="caption save-reason" id="save-reason" hidden></small>
  <p class="sr-only" id="save-live" role="status" aria-live="polite"></p>
</div>
```

Why each choice:

- **`id="git-save-progress"` stays on the Save button.** It is a load-bearing id (ADDENDUM J2) read by
  `git-progress.js:200,784`, `docs/redesign/tools/verify_after.py` and
  `docs/ui-ux-cleanup/tools/live_1_30_37_b.py`. Only its label changes. `#git-save-menu`, `#git-save-help*`
  and the four header `[data-git-action]` items go (consumers in section 8.3).
- **`span.menu` wrappers.** `.menu` is `position: relative; display: inline-block` (`style.css:567`) and it is
  the element `shellPointerDown()` looks for to decide that a click was inside an open menu
  (`app/static/shell.js:134`). A panel inside a `.menu` wrapper therefore stays open while the person clicks
  in it, with no new listener.
- **`panel-button`, not `menu-button`.** `initMenu()` gives a list `role="menu"`, arrow-key roving, closes on
  Tab and closes on any item click (`shell.js:82,104-119`). A panel holds a text field, tick boxes and
  buttons that must not close it, so it is a non-modal dialog (`role="dialog"`, `aria-haspopup="dialog"`).
- **The chip is two spans.** `#save-chip-text` gets `textContent`, `#save-chip-dot` gets `className`. The
  chevron and the button never change, so focus on the chip survives every poll.
- **`.save-pair`** keeps the chip and Save on one row at every width (F16).
- **`#save-reason`** is the visible reason when Save or Load is disabled for a cause the chip does not state
  (section 1.6). **`#save-live`** is the polite live region (section 2.6).
- The Load button, `#load-panel` and its body belong to the Load designer. This slice fixes only their
  position, the wrapper, the `panel-button` class and the shared `save-panel` base.

Order in the DOM equals the visual order: chip, Save, Load, Lab actions (5.1).

### 1.3 Class names (replacing `rx-*` and `px-*`)

Shared base names `save-chip`, `save-panel`, `save-dot`, `save-list`, `save-devices` as agreed. Wherever
`style.css` already has a class, the placeholder maps to it and no new class is made.

| Mockup | Final | New or reused |
|---|---|---|
| `rx-head` | `save-control` + `save-pair` | new |
| `rx-chip` | `save-chip` | new; on top of `.button.secondary` (`style.css:479-504`) |
| `rx-dot`, `.warn .bad .none .busy .info` | `save-dot`, `.ok .warn .bad .none .busy .info` | new (`.ok` is spelled out; the mockup's default is green) |
| `rx-pop`, `rx-pop.rx-wide` | `save-panel`, `save-panel.wide` | new |
| `rx-state` | `save-state` | new |
| `rx-sub` | `save-sub` | new |
| `rx-row` | `save-row` | new |
| `rx-quiet` | `button ghost small` | reused: `.button.ghost` (`style.css:506-507`), `.button.small` (`style.css:515`) |
| `rx-save` (large primary) | `button primary` inside `.save-panel` | reused; sized by `.save-panel .button.primary` |
| `rx-note` | `save-note` | new |
| `rx-kv` | `save-kv` | new |
| `rx-foot` | `save-foot` | new |
| `#rx-name` | `#save-name` (`input.save-name`) | new |
| `label.rx-keep.checkbox-label` | `label.checkbox-label.save-keep` | reused `.checkbox-label` |
| `rx-h` | `save-heading` | new (Load designer, drawer designer) |
| `rx-list`, `rx-ver`, `rx-when`, `rx-why`, `rx-open`, `rx-picked` | `save-list`, `save-item`, `save-when`, `save-why`, `.open`, `.picked` | new (Load designer, drawer designer) |
| `rx-devs`, `rx-end`, `rx-off` | `save-devices`, `save-end`, `.off` | new (Load designer) |
| `dialog.rx-drawer` | `dialog.drawer.save-drawer` | reused `.drawer` (`style.css:1521-1556`) |
| `dialog.px-drawer`, `px-drawer-foot` | `dialog.drawer.save-settings`, `save-settings-foot` | drawer designer |
| `rx-menu`, `rx-col`, `rx-more`, `rx-center`, `rx-back`, `rx-dialog` | none | earlier mock rounds, not on any approved board of this slice |

`rx-quiet` becomes the existing ghost button on purpose: it has a hover state, a 30 px target and the house
focus ring already, and a second borderless accent button class would duplicate it. The visible difference
from the board is 4 px more padding.

### 1.4 CSS

New rules, placed after the menu section (`style.css:648`), replacing the `.git-save-*` block
(`style.css:649-707` and the two lines at `style.css:2444-2445`) once `#git-save-menu` is gone. Started from
Appendix A.1; differences are commented.

```css
/* Save and Load in the lab header (save-header.js). The chip and the Load button open a .save-panel. */
.save-control { display: contents; }                       /* its children wrap with Lab actions as one flex row */
.save-pair { display: flex; align-items: center; gap: 8px; min-width: 0; flex: 0 1 auto; }
.save-menu { min-width: 0; }                               /* lets the chip shrink at 390 px */
.save-chip { gap: 8px; font-weight: 500; min-width: 0; max-width: 16rem; }
.save-chip-text { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.save-chip .icon { flex: none; }
.panel-button[aria-expanded="true"]:not(.primary):not(.danger) { background: var(--surface-2); border-color: var(--muted); color: var(--ink); }
.save-dot { width: 8px; height: 8px; border-radius: 50%; flex: none; box-sizing: border-box; background: var(--ok); }
.save-dot.warn { background: var(--warn); }
.save-dot.bad { background: var(--danger); }
.save-dot.info { background: var(--accent); }
.save-dot.busy { background: var(--accent); box-shadow: 0 0 0 4px var(--accent-soft); animation: pill-pulse 1.6s ease-in-out infinite; }
.save-dot.none { background: transparent; border: 2px solid var(--muted); }   /* a border, not an inset shadow: it survives forced colours */
.lab-header:has(.pill.busy) .save-dot.busy { animation: none; }   /* one pulsing element per surface (ADDENDUM J5) */
.save-reason { flex-basis: 100%; margin: 0; }
.save-panel { position: absolute; top: calc(100% + 6px); right: 0; width: min(380px, calc(100vw - 32px)); box-sizing: border-box; max-height: calc(100dvh - 140px); overflow-y: auto; overscroll-behavior: contain; padding: 18px; background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius-lg); box-shadow: var(--shadow-menu); z-index: 20; text-align: left; white-space: normal; font-size: 13px; color: var(--text); }
.save-panel.wide { width: min(440px, calc(100vw - 32px)); }
.save-panel.menu-clamped { right: auto; left: 0; }
.save-state { display: flex; align-items: center; gap: 10px; margin: 0; font-size: 18px; font-weight: 700; letter-spacing: -.02em; line-height: 1.2; color: var(--ink); }
.save-state .save-dot { width: 10px; height: 10px; }
.save-state:focus-visible { outline-offset: 4px; }
.save-sub { margin: 6px 0 14px; font-size: 13px; line-height: 1.5; color: var(--muted); }
.save-row { display: flex; align-items: center; gap: 8px 12px; flex-wrap: wrap; }
.save-panel .save-row .button.primary, .save-panel .save-row .button.danger { min-height: 40px; padding: 8px 22px; }
.save-note { margin: 12px 0 0; font-size: 12px; color: var(--muted); }
.save-kv { margin: 0 0 4px; font-size: 13px; color: var(--text); }
.save-kv span { color: var(--muted); }
.save-name { width: 100%; margin: 8px 0 12px; box-sizing: border-box; }
.save-keep { margin: 0 0 4px; font-size: 13px; font-weight: 400; color: var(--text); }
.save-foot { display: flex; justify-content: space-between; flex-wrap: wrap; gap: 4px 8px; margin: 10px -10px 0; padding: 10px 0 0; border-top: 1px solid var(--line); }
.save-foot .button.ghost { font-size: 13px; }
dialog.save-drawer { width: min(760px, 100vw); }
.save-drawer .drawer-head .save-row { margin-top: 14px; }
.save-drawer .diff-file { margin: 0 0 8px; }
@media (min-width: 1280px) { #lab-content { --lab-action-col: 35rem; } }
```

Additions to existing blocks:

- `style.css:2331` (`prefers-contrast: more`): nothing; the dots are already at or above 4.7:1.
- `style.css:2343` (`forced-colors: active`): `.save-dot { forced-color-adjust: none; background: none;
  border: 3px solid CanvasText; } .save-dot.none { border-width: 1px; }` so filled and hollow stay
  distinguishable, as the pill dots are handled there.
- Reduced motion is already global (`style.css:2325-2328`).
- The inset focus rule (`style.css:2322-2323`) is not extended: panel controls keep the standard two-tone
  ring (`style.css:2316-2317`), which fits inside the panel's 18 px padding.

Existing rules this leans on: `.button` and its variants (`style.css:479-515`), `.menu` (`style.css:567`),
the menu surface values copied into `.save-panel` (`style.css:596-609`), `.menu-clamped`
(`style.css:1927`), `pill-pulse` (`style.css:831-834`), `.caption` (`style.css:189`), `.sr-only`
(`style.css:162`), `.checkbox-label`, `.form-error`, `.drawer`, `.drawer-head`, `.drawer-meta`,
`.drawer-content` (`style.css:1521-1556`), `.diff-file`, and `[hidden]` beating `.button`
(`style.css:497`).

### 1.5 Contrast

Computed with the WCAG 2.x formula against the tokens in `style.css:55-78`; the documented figures are in
`style.css:30-49`.

| Use | Pair | Ratio | Needed |
|---|---|---|---|
| Chip dot at rest | ok / warn / danger / accent on surface | 5.32 / 6.22 / 6.54 / 5.65 | 3 (documented, `style.css:46`) |
| Chip dot, chip hovered or open | ok / warn / danger / accent on surface-2 | 4.72 / 5.53 / 5.81 / 5.02 | 3 |
| Hollow dot ring | muted on surface / surface-2 | 5.51 / 4.90 | 3 |
| Busy dot against its halo | accent on accent-soft | 4.85 | 3 |
| Chip text | text on surface / surface-2 | 13.29 / 11.81 | 4.5 |
| Ghost buttons in the panel | accent-strong on surface / on accent-soft (hover) | 7.32 / 6.28 | 4.5 |
| `save-sub`, `save-note`, `save-kv span` | muted on surface | 5.51 | 4.5 |
| `save-end.ok / .bad / .now` (Load designer) | ok-strong / danger-strong / accent-strong on surface | 7.69 / 8.91 / 7.32 | 4.5 |
| Picked row (Load designer) | ink on accent-soft; muted on accent-soft | 13.53; 4.73 | 4.5 |

No new colour token. Colour is never the only signal: every dot sits beside text that names the state, and
the two red states and the two amber states differ by their text.

### 1.6 Layout at 1440, 1280, 760 and 390 px

Widths measured on board G01: chip "Saved 21 min ago" 187 px, Save 63 px, Load 63 px, Lab actions 132 px,
gaps 8 px. The chip is capped at 16 rem (256 px) and its text ellipsises; the panel title always carries the
full text.

| Width | Action area | Result |
|---|---|---|
| 1440 | grid column 35 rem = 560 px | worst case 256 + 8 + 63 + 8 + 63 + 8 + 132 = 538 px: one row |
| 1280 | content 1280 − 48 = 1232 px (`.content` padding, `style.css:373-378`); column 560 px | one row; title block keeps 656 px |
| 901 to 1279 | column 26 rem = 416 px (`style.css:887`) | row 1: chip, Save, Load (at most 398 px); row 2: Lab actions |
| 760 | actions take a full row (`style.css:2388`), 728 px | one row (538 px); may also stand as F16 shows, chip and Save first |
| 390 | 358 px | row 1: chip (shrinks to at most 287 px) and Save; row 2: Load, Lab actions (203 px) |

Nothing overlaps because nothing is positioned: the group is one wrapping flex row and the only absolutely
positioned element is the open panel. The panel is `min(380px, 100vw − 32px)` wide, right-aligned to the
chip, and takes the existing left-edge clamp (`shell.js:99`) when its left edge would leave the screen, which
is the case at 390 px (panel 358 px from the left gutter). `max-height` plus `overflow-y: auto` keeps a tall
panel (the device list of a load) inside a short window.

The fixture pass must confirm these with screenshots; the 760 px row count is the one figure this document
derives rather than measures.

### 1.7 Disabled controls

| Control | Disabled when | Visible reason |
|---|---|---|
| Save | chip state Saving or Loading | the chip beside it says `Saving…` / `Loading… 2 of 4`; `#save-reason` stays hidden |
| Save | `busy()` (`app.js:20`) for another cause, the server's `idle()` rule (`app/git_progress.py:604-605`) | `#save-reason`: `A backup or lab operation is running. Save is available when it finishes.` (today's sentence, `git-progress.js:188`) |
| Save | bound lab, request in flight (`gitSubmitting`, `git-progress.js:548`) | chip `Saving…` (set at once, section 4.1) |
| Load | Load designer; it writes its reason to `#save-reason` through the same helper | |

An unbound lab never disables Save: it opens the first-save panel, as today's button opens the first-save
flow (`git-progress.js:184-185`). `title` is not used for reasons (unreachable on a disabled button).

## 2. Panel mechanics

### 2.1 What exists in `shell.js`

- `closeMenus(except)` closes every `.menu-button[aria-expanded="true"]` through its `_menuClose` and every
  open `details.menu`, `#git-save-menu`, `#lab-switcher`, except the one containing `except`
  (`shell.js:71-76`).
- `initMenu(button)` builds open and close, the left clamp, and returns focus to the button on Escape and on
  item activation (`shell.js:77-121`).
- `shellEscape` on the document, capture phase: node context menu first, then leaves a `.menu-list` to its
  own handler, then `<details>` menus, then `closeMenus()` (`shell.js:125-133`).
- `shellPointerDown` on the document, capture phase: closes every menu except the `.menu` the pointer is in
  (`shell.js:134`).
- `selectLab()` and `goHome()` call `closeMenus()` (`app.js:64`, `shell.js:62`). Modal dialogs are closed by
  `closeLabDialogs()` and `closeDialogsExcept()` (`shell.js:54-58`, `git-progress.js:92-95`).
- `opDialog()` records the element that had focus and gives focus back on close
  (`app/static/operations.js:13-22`).

### 2.2 Exact changes in `shell.js`

No listener is added to `document` or `window`. Four edits:

**(a)** `closeMenus`, `shell.js:73`: the selector becomes
`'.menu-button[aria-expanded="true"], .panel-button[aria-expanded="true"]'`. Panels expose `_menuClose`
like menus, so the loop body is unchanged. On `shell.js:74` the `details#git-save-menu[open]` part is dropped
with the element.

**(b)** New function after `initMenu` (`shell.js:121`):

```js
// Panels: a .panel-button and its sibling [data-panel] inside span.menu (the chip panel, the Load panel). A panel is a
// non-modal dialog, not a menu: no roving focus, Tab moves through it, a click inside never closes it. It shares
// closeMenus(), so one panel or menu is open at a time; shellPointerDown closes it on an outside click.
function initPanel(button){
 if(!button||button._menuReady)return null;
 const wrapper=button.parentElement,panel=wrapper&&typeof wrapper.querySelector==='function'?wrapper.querySelector('[data-panel]'):null;
 if(!panel)return null;button._menuReady=true;
 button.setAttribute('aria-expanded','false');panel.hidden=true;
 const fire=name=>{if(typeof CustomEvent==='function'&&typeof panel.dispatchEvent==='function')panel.dispatchEvent(new CustomEvent(name));};
 const close=restore=>{if(panel.hidden)return false;panel.hidden=true;button.setAttribute('aria-expanded','false');fire('panelclose');if(restore&&typeof button.focus==='function')button.focus();return true;};
 const clamp=()=>{if(typeof panel.getBoundingClientRect!=='function'||!panel.classList)return;panel.classList.remove('menu-clamped');if(panel.getBoundingClientRect().left<8)panel.classList.add('menu-clamped');};
 // options.focus===false: opened by the page, not by the person; focus stays where it is.
 const open=(options={})=>{closeMenus(wrapper);panel.hidden=false;clamp();button.setAttribute('aria-expanded','true');fire('panelopen');if(options.focus!==false){const target=panel.querySelector('[data-panel-focus]')||panel;if(typeof target.focus==='function')target.focus();}return true;};
 button._menuClose=close;button._menuOpen=open;
 button.addEventListener('click',()=>{if(panel.hidden)open();else close(false);});
 panel.addEventListener('keydown',e=>{if(e.key==='Escape'){e.preventDefault();e.stopPropagation();close(true);}});
 // Tab or a click that moves focus to another control closes it; a rebuilt body (focus falls to nothing) does not.
 wrapper.addEventListener('focusout',e=>{const next=e.relatedTarget;if(next&&!shellContains(wrapper,next))close(false);});
 return {open,close};
}
// Whether the page may open a panel by itself: never over a modal dialog, never while another menu or panel is open.
function panelCanOpen(button){
 if(typeof document==='undefined'||typeof document.querySelector!=='function')return false;
 if(document.querySelector('dialog[open]'))return false;
 const other=document.querySelector('.menu-button[aria-expanded="true"], .panel-button[aria-expanded="true"], details.menu[open], details#lab-switcher[open]');
 return !other||other===button;
}
```

**(c)** `shellEscape`, `shell.js:129`: `if(target&&target.closest('.menu-list, [data-panel]'))return;`. Focus
inside a panel leaves Escape to the panel's own handler, which closes and returns focus to the opener.
With focus elsewhere (a panel the page opened by itself), the existing last line `closeMenus()` closes it and
focus does not move. `shell.js:130` and `shell.js:134` lose their `details#git-save-menu` selector parts.

**(d)** Load-time wiring, after `shell.js:202`:
`document.querySelectorAll('.panel-button').forEach(initPanel);`

And one wording fix that belongs to 5.11: `shellErrorSentence`, `shell.js:183`, "…Check the devices under
Progress › Save settings." becomes "…Check the devices under Save settings."

Removed elsewhere: the two document listeners `git-progress.js:794-795` (outside click and Escape for
`#git-save-menu`) go with the menu. After this change no script but `shell.js` holds a document-level
`click`, `keydown` or `pointerdown` listener for the save UI.

### 2.3 Open, close, focus

| Event | Result | Focus |
|---|---|---|
| Click or Enter/Space on the chip | chip panel toggles; opening closes any other menu or panel | to the panel title (`h2[data-panel-focus]`, `tabindex="-1"`), so a screen reader reads the state first |
| Click on Save, bound lab | save request, chip panel opens showing `Saving…` | to the panel title; Save is disabled a moment later and must not keep focus |
| Click on Save, unbound lab | chip panel opens with the first-save view | to the panel title |
| Click on Load | Load panel toggles (Load designer) | Load designer |
| Escape, focus inside a panel | closes | back to the opener (chip or Load) |
| Escape, focus outside | closes (`closeMenus()`) | unchanged |
| Pointer down outside the `.menu` wrapper | closes (`shellPointerDown`) | follows the click |
| Tab past the last control or Shift+Tab before the title | closes (`focusout`) | continues to the next control |
| A drawer or dialog opens (`See changes`, `Details`, `All versions`, `Save settings`) | the handler calls `closeMenus()` first, then `showModal()` | into the dialog; on close back to the chip (see below) |
| `selectLab()`, `goHome()` | closes (`closeMenus()`, already called) | as today |

Returning focus from a drawer or dialog: the buttons that open one live in a panel that is closed by then.
`opDialog(id, title, body, opener)` takes the control to return to (`operations.js:13-17`), so every such
call from the panel passes `$('save-chip')`; the *What changed* drawer does the same in its own `close`
handler. Without this, focus would fall to `<body>`.

Only one open at a time: panels and menus through `closeMenus(wrapper)` in `open()`; drawers and dialogs are
modal (`showModal()`), which makes the header inert, and each opener closes the panel first.

### 2.4 Re-rendering on the 4 s poll

`render()` runs after every poll (`app.js:61,106`) and calls `renderSaveHeader()` (new, section 8). Rules:

1. Chip: `textContent` and `className` only.
2. Panel title: `#save-panel-title-text.textContent` and `#save-panel-dot.className` only. The title is the
   focus target, so it must never be rebuilt. Relative times ("Saved 21 minutes ago") live only here and in
   the chip, never in the body, so the minute tick does not rebuild anything.
3. Panel body: `savePanelMarkup(el, key, build)`, modelled on `setListMarkup()` (`app.js:47-54`):

```js
// Like setListMarkup (app.js): rebuild only when the state-free key changed, and hand focus, the caret and text the person typed
// but did not commit back to the control with the same id. Every focusable control of a panel body has a stable id.
function savePanelMarkup(el,key,build){
 if(!el||el._listKey===key)return false;
 const a=typeof document!=='undefined'?document.activeElement:null,inside=a&&a.id&&typeof el.contains==='function'&&el.contains(a);
 const typed=inside&&a.dataset&&a.dataset.dirty==='1'?{value:a.value,start:a.selectionStart,end:a.selectionEnd}:null,id=inside?a.id:'';
 el.innerHTML=build();el._listKey=key;
 if(id){const next=typeof $==='function'?$(id):null;if(next&&typeof next.focus==='function'){if(typed&&'value' in next){next.value=typed.value;next.dataset.dirty='1';}next.focus({preventScroll:true});if(typed&&typeof next.setSelectionRange==='function')next.setSelectionRange(typed.start,typed.end);}else if($('save-panel-title'))$('save-panel-title').focus({preventScroll:true});}
 return true;
}
```

   The key is `view + job id + job status + the fields the view shows` (for the name view: `job.note`,
   `job.note_auto`, whether the capture is kept, whether a checkpoint exists). It contains no time. While the
   person types in `#save-name` the input carries `data-dirty="1"`; a rebuild caused by another change keeps
   the typed text. When the focused control no longer exists after a rebuild (Upload replaced by the
   uploading view), focus goes to the panel title, never to `<body>`.
4. Tick boxes are real inputs; a rebuild reads `checked` from state, never from the DOM, and a box whose
   request is in flight is disabled, so there is no "ticked but not kept" moment.
5. The body is delegated: one `click` and one `change` listener on `#save-panel` (element level), reading
   `data-save-action`. No handler is attached to rebuilt nodes.

### 2.5 The chip panel opening by itself

`gitStartWatch()` already follows a save every 1.5 s until it leaves the active states
(`git-progress.js:682-697`). Its end-of-watch branch (`git-progress.js:692`) is replaced by one call,
`saveFinished(job)`:

| The save ended as | Action |
|---|---|
| `unchanged` | toast `Nothing changed since your last save.`; the panel closes if it shows this save |
| `review_pending` or `committed` (a commit waits on the VM) | the chip panel opens by itself with the upload view (G11) |
| `synced` after an upload | toast `Uploaded to <host>.`; the panel closes if it shows this save (F05) |
| `push_pending` | the chip panel opens with the *Upload failed* view (F13) |
| `export_pending`, `capture_incomplete`, `failed`, `interrupted` | the chip panel opens with the *Can't save* view (6.5) |

"Opens by itself" is `$('save-chip')._menuOpen({focus: …})` and happens only when all of these hold:

1. the job's `lab_id` equals `activeId`;
2. the save was started from this page (`gitStartWatch` ran for it with `quiet: true`, which
   `gitSubmitSave` does, `git-progress.js:558`); a save found on page load, started in another browser or by
   the Network design export never opens a panel, it only changes the chip;
3. `panelCanOpen($('save-chip'))`: no modal dialog or drawer is open, and no other menu or panel (for
   example the Load panel with a confirmation in it) is open;
4. it was not already opened for this job id and status (`saveHeader.opened`, in memory).

When a condition fails the chip still changes and the live region announces the new state; nothing is lost,
the person opens the panel from the chip.

Focus on self-opening: if the panel was already open (the usual case: it has shown `Saving…` since the
click) nothing moves; the keyed rebuild keeps focus on the title. If it was closed, focus moves to the title
only when `document.activeElement` is `<body>`, the chip or the Save button; otherwise
`_menuOpen({focus: false})` and the live region carries the message. Typing in the map editor search or a
device filter is never interrupted.

It must not open: over any `dialog[open]`; while the person is on Home; for another lab's save; twice for
the same result; for a design export (`job.kind === 'design'`, which keeps its own review path in
`network-design.js:2139` and reaches the same upload view when the person opens the chip).

### 2.6 The live region

`<p id="save-live" class="sr-only" role="status" aria-live="polite">`. `renderSaveHeader()` remembers the
last chip key per lab (`saveHeader.last`) and writes the region only when the key changes after the first
render of that lab (no announcement on page load or on switching labs). The text is the chip's full
sentence: the panel title plus, where there is one, the first sentence of the panel
(`Not uploaded yet. 2 devices changed since your last save: ceos and xrv9k.`).

Two transitions are announced by the toast instead (`#toast` is `role="status"`, `index.html:292`), and the
region stays silent for them so nothing is read twice: `unchanged` and uploaded. The chip button itself is
never a live region; its text changes every minute.

## 3. The chip state function

### 3.1 Name and signature

```js
// status.js, after progressSummary (status.js:165)
function saveChipState(lab, ctx = {}, now)
//   ctx.git_jobs      state.git_jobs
//   ctx.restore_jobs  state.restore_jobs
//   ctx.problem       why the save location cannot be used now ('' when fine)
//   ctx.refusal       the message of a save request the manager just refused ('' when none; page memory, not /api/state)
// → { key, dot, text, panel, detail, job, load, count, at, also, saveDisabled, loadDisabled }
function relativeTimeShort(value, now)     // 'just now' | '21 min ago' | '2 h ago' | 'yesterday' | '3 days ago' | '12 Sep'
function saveLoadName(restoreJob)          // the name after "Running"
```

`key` is one of `loading saving partial cant failed waiting running saved kept none`. `dot` is the `save-dot`
modifier. `panel` names the view the chip opens. `also` is the highest of `cant`, `failed`, `waiting` that the
winning state hides, so its panel can add one line for it (section 3.4). `progressState()` stays as it is for
its other consumers (section 8.3).

### 3.2 Inputs and where the backend produces them

| Field | Produced at |
|---|---|
| `lab.id`, `lab.git_binding` (with `repository.push_url`, `repository.prefix`, `node_names`) | `public_lab` copies every lab key but the excluded ones (`app/main.py:155`); the binding is built at `app/git_progress.py:1145-1146` |
| `state.git_jobs[]` | `app/main.py:224` through `public_job` (`app/git_progress.py:60-61`) with the keys of `PUBLIC_JOB` (`app/git_progress.py:40-42`): `id lab_id created finished status message backup_job_id commit pushed target checkpoint changed_files snapshot_path note review_before_push reviewed destination kind generation_id` |
| git job `status` values | `queued` (`git_progress.py:1360`), `capturing` (`:824`), `exporting` (`:844`), `pushing` (`:749,861`), `capture_incomplete` (`:837`), `synced / push_pending / export_pending / unchanged / review_pending / committed` (`:897-901`), `interrupted / push_pending / export_pending / failed` on an error (`:872`), `dismissed` (`:1471`) |
| `state.restore_jobs[]` | `app/main.py:225` through `restore.public_job` (`app/restore.py:83-92`): `PUBLIC_JOB` (`app/restore.py:47-48`: `id lab_id lab_name created finished status message source confirm_minutes pre_backup_job_id post_backup_job_id targets progress`) plus `rechecking` and `server_time` |
| restore `targets[].status` | vocabulary in `app/static/restore.js:23-33`; "replaced" is `applied verified applied_unverified verify_mismatch` (`restore.js:32`) |
| restore `source` | `{type: 'folder', folder}` / `{type: 'git', commit, path}` / `{type: 'backup', backup_job_id}` (`app/restore.py:164-173`, stored at `app/restore.py:712`) |
| `ctx.problem` | today only `repository_status.problem` of `GET /api/labs/{id}/git` (`app/git_progress.py:1129-1133`), cached in `gitContexts` and read by `gitProblem()` (`app.js:88`). It is a VM round trip and is **not** in `/api/state` |

**NEEDS (backend) N1:** `lab.git_status = {checked, ready, problem, code}` in `public_lab`, cached from the
last helper `status` the manager ran for that lab (settings route, save, update), never fetched on the poll.
`code` is one of `vm account busy diverged settings other` (section 5.2). Until it exists the page passes
`gitProblem(lab)` (known only after the chip panel or a drawer loaded the lab's Git context) and classifies
the text with the table of section 5.2.

**NEEDS (backend) N2 (through the Load designer):** `source.label` on the public restore job, the state's
display name frozen when the load was submitted. Until it exists `saveLoadName()` derives it: a folder
through `savedVersionName()` (`status.js:171-177`), a Git path from its last segment.

Everything else the nine states need is in `/api/state` today.

### 3.3 Decision table

Evaluated top to bottom; the first row that holds wins. "Save" below means a job of this lab with
`target === 'latest'` and `kind !== 'design'`, not `dismissed`.

| # | State (key) | Holds when | Dot | Chip text | Chip opens | Save / Load |
|---|---|---|---|---|---|---|
| 1 | Loading (`loading`) | a restore job of the lab is active: `statusRestoreActive(job)` (`status.js:31`) | `busy` | `Loading… N of M` (N targets no longer in `pending backing_up applying confirming interrupted`, M targets); `Loading…` before targets exist; `Checking devices…` while `rechecking` | the Load panel's progress view (G04) | both disabled |
| 2 | Saving (`saving`) | a git job of the lab is in `STATUS_GIT_BUSY` (`status.js:13`) | `busy` | `Saving…`; `Uploading…` while `pushing`; `Updating…` for `target: 'update'` | F02 | both disabled |
| 3 | Partial (`partial`) | the newest finished load is newer than the newest capture and its status is `partial`, `needs_attention` or `interrupted` | `warn` | `Loaded N of M` (N targets replaced) | G06 (Load designer) | enabled |
| 4 | Needs attention (`cant`) | lab is bound and: `ctx.refusal`, or `ctx.problem`, or the newest job is `export_pending`, `capture_incomplete`, `failed`, or `interrupted` without a commit | `bad` | `Can’t save` | 6.5 view (section 5.2) | enabled (Save is the retry) |
| 5 | Failed (`failed`) | a job with a commit, not pushed, is `push_pending` | `bad` | `Upload failed` | F13 | enabled |
| 6 | Waiting (`waiting`) | one or more jobs with a commit, not pushed, in `committed review_pending interrupted` | `warn` | `1 save to upload` / `N saves to upload` (N distinct commits) | G11 | enabled |
| 7 | Running (`running`) | the newest finished load is newer than the newest capture and its status is `succeeded` | `info` | `Running <name>` | G05 (Load designer) | enabled |
| 8 | Not saved (`none`) | no `git_binding` | `none` | `Not saved yet` | F12 | enabled |
| 9 | Saved (`saved`) | the newest save that changed something is `synced`, or only `unchanged` saves are known | `ok` | `Saved <short time>` | G10, or F06 while naming (section 4.7) | enabled |
| 9a | Saved, kept (`kept`) | bound, every save is `dismissed` | `none` | `Kept on this VM` (today's label, `status.js:148`) | G10 with `Uploaded: no, kept on the lab VM` | enabled |
| 9b | Not saved (`none`) | bound, no save at all | `none` | `Not saved yet` | F12, bound variant | enabled |

Definitions:

- *Newest capture*: the newest save in `synced unchanged committed review_pending push_pending`, time
  `finished || created` (`statusJobTime`, `status.js:42`). An `unchanged` save counts: it proves the devices
  equal the latest save, so it ends Running (5.4 step 9, "leaves Running when the next save completes").
- *Shown save time*: the newest such save that is not `unchanged`, so the chip keeps `Saved 21 min ago` after
  a save that changed nothing, as F14 shows.
- *Newest finished load*: the restore job with the greatest `statusJobTime` that is not active.
- `relativeTimeShort` uses the thresholds of `relativeTime` (`status.js:54-61`) with short units.

### 3.4 Precedence, with the reasons

- **Loading and Saving first.** They disable Save and Load, and the server allows neither beside the other
  (`operation_busy`, `app/lab_operations.py:57-71`; `idle`, `app/git_progress.py:598-606`), so the text must
  say why the buttons are off. Loading is first because it changes devices.
- **Partial before the save states.** Devices in a mixed state are the thing the person must know before
  anything else, including before uploading. It is cleared by the next save or the next load.
- **Needs attention before Failed and Waiting.** When the repository cannot be used, uploading and saving
  both fail; offering Upload first would lead into the failure.
- **Failed before Waiting.** One Try again uploads every waiting commit (a push carries all of them, and
  `finish()` marks the earlier jobs `synced`, `app/git_progress.py:907-925`), so the count is in the panel.
- **Waiting before Running.** Something the person still has to do outranks information. The panel keeps the
  information: every view shows `Running: <name>` when `state.load` is set.
- **Running before Saved.** 5.2: Saved means "nothing newer was loaded".
- **A save newer than a load** removes Running and Partial, by time comparison only.
- **Needs attention versus Not saved.** An unbound lab is always *Not saved*: there is no location that
  could be broken, and the first-save panel reports whatever stops it. A bound lab with no save and a
  repository problem is *Can't save*.
- **A failed or refused load** (`failed`, `preflight_failed`, `dismissed`) sets no chip state: no device
  changed. The lab banner already reports it (`labFailure`, `status.js:75-82`; `app.js:224-236`).
- **`also`.** When Partial hides Can't save, Failed or Waiting, or Can't save hides Failed or Waiting, the
  panel ends with one line, for example `Also: 1 save to upload.` and a ghost button **Show**, which switches
  the panel view. No state is unreachable from the chip.

Rows that go beyond the nine of 5.2, each because the prompt is silent and today's behaviour exists:
`Uploading…` and `Updating…` texts inside Saving, `Checking devices…` inside Loading (the restart read-back,
`status.js:27-31`), and `kept` (today's "Kept on this VM", `status.js:146-149`).

### 3.5 Reference implementation

Appended to `status.js`; it uses `statusEpoch`, `statusJobTime`, `statusLabGitJobs`, `statusRestoreActive`,
`statusRestoreRechecking`, `STATUS_GIT_BUSY`, `plural` and `savedVersionName`, all in that file.

```js
const STATUS_SAVE_HELD=['committed','review_pending','push_pending','interrupted'];
const STATUS_SAVE_STOPPED=['export_pending','capture_incomplete','failed'];
const STATUS_SAVE_CAPTURED=['synced','unchanged','committed','review_pending','push_pending'];
const STATUS_LOAD_REPLACED=['applied','verified','applied_unverified','verify_mismatch'];
const STATUS_LOAD_MIXED=['partial','needs_attention','interrupted'];
function relativeTimeShort(value,now){
 const time=statusEpoch(value);if(!time)return '';
 const reference=now===undefined?Date.now():now,diff=Math.max(0,reference-time),minute=60000,hour=3600000,day=86400000;
 if(diff<45000)return 'just now';if(diff<hour)return Math.min(59,Math.max(1,Math.round(diff/minute)))+' min ago';
 if(diff<day)return Math.min(23,Math.max(1,Math.round(diff/hour)))+' h ago';if(diff<day*2)return 'yesterday';
 if(diff<day*7)return plural(Math.round(diff/day),'day')+' ago';
 return new Date(time).toLocaleDateString(undefined,{month:'short',day:'numeric'});
}
function saveLoadName(job){
 const s=job?.source||{};if(s.label)return String(s.label);
 if(s.type==='folder')return savedVersionName(s.folder)||'the top folder';
 if(s.type==='git'){const parts=String(s.path||'').split('/').filter(Boolean),leaf=parts[parts.length-1]||'';if(leaf==='latest')return parts.length>1?savedVersionName(parts.slice(0,-1).join('/')):'your latest save';if(leaf==='baseline')return 'the starting point';return leaf||'a saved state';}
 if(s.type==='backup')return 'the backup';
 return 'a saved state';
}
function saveChipState(lab,ctx={},now){
 const base={detail:'',job:null,load:null,count:0,at:'',also:null,saveDisabled:false,loadDisabled:false};
 if(!lab)return {...base,key:'none',dot:'none',text:'Not saved yet',panel:'first'};
 const mine=j=>!!j&&j.lab_id===lab.id,bound=!!lab.git_binding;
 const restores=(ctx.restore_jobs||[]).filter(mine),loading=restores.find(statusRestoreActive);
 if(loading){
  const targets=loading.targets||[],done=targets.filter(t=>!['pending','backing_up','applying','confirming','interrupted'].includes(t.status)).length;
  const text=statusRestoreRechecking(loading)?'Checking devices…':targets.length?`Loading… ${done} of ${targets.length}`:'Loading…';
  return {...base,key:'loading',dot:'busy',text,panel:'loading',load:loading,count:done,saveDisabled:true,loadDisabled:true};
 }
 const all=(ctx.git_jobs||[]).filter(mine),active=all.find(j=>STATUS_GIT_BUSY.includes(j.status));
 if(active){const text=active.target==='update'?'Updating…':active.status==='pushing'?'Uploading…':'Saving…';return {...base,key:'saving',dot:'busy',text,panel:'saving',job:active,saveDisabled:true,loadDisabled:true};}
 const live=statusLabGitJobs(lab,all).filter(j=>j.status!=='dismissed'),saves=live.filter(j=>j.target==='latest'&&j.kind!=='design');
 const captured=saves.find(j=>STATUS_SAVE_CAPTURED.includes(j.status))||null,shown=saves.find(j=>STATUS_SAVE_CAPTURED.includes(j.status)&&j.status!=='unchanged')||captured;
 const load=restores.slice().sort((a,b)=>statusJobTime(b)-statusJobTime(a))[0]||null,loadNewer=!!load&&statusJobTime(load)>(captured?statusJobTime(captured):0);
 const held=bound?live.filter(j=>j.commit&&!j.pushed&&STATUS_SAVE_HELD.includes(j.status)):[],count=new Set(held.map(j=>j.commit)).size;
 const stopped=bound&&live[0]&&(STATUS_SAVE_STOPPED.includes(live[0].status)||(live[0].status==='interrupted'&&!live[0].commit))?live[0]:null;
 const states=[];
 if(loadNewer&&STATUS_LOAD_MIXED.includes(load.status)){const total=(load.targets||[]).length,ok=(load.targets||[]).filter(t=>STATUS_LOAD_REPLACED.includes(t.status)).length;states.push({key:'partial',dot:'warn',text:`Loaded ${ok} of ${total}`,panel:'partial',load,count:ok});}
 if(bound&&(ctx.refusal||ctx.problem||stopped))states.push({key:'cant',dot:'bad',text:'Can’t save',panel:'cant',job:stopped,detail:String(ctx.refusal||ctx.problem||stopped.message||'')});
 if(held.some(j=>j.status==='push_pending'))states.push({key:'failed',dot:'bad',text:'Upload failed',panel:'failed',job:held.find(j=>j.status==='push_pending'),count});
 else if(count)states.push({key:'waiting',dot:'warn',text:plural(count,'save')+' to upload',panel:'upload',job:held[0],count});
 if(loadNewer&&load.status==='succeeded')states.push({key:'running',dot:'info',text:'Running '+saveLoadName(load),panel:'running',load});
 if(!bound)states.push({key:'none',dot:'none',text:'Not saved yet',panel:'first'});
 else if(shown&&(shown.status==='synced'||shown.status==='unchanged')){const at=shown.finished||shown.created||'',when=relativeTimeShort(at,now);states.push({key:'saved',dot:'ok',text:when?'Saved '+when:'Saved',panel:'rest',job:shown,at});}
 else if(!shown){const kept=statusLabGitJobs(lab,all).find(j=>j.status==='dismissed'&&j.target==='latest');states.push(kept?{key:'kept',dot:'none',text:'Kept on this VM',panel:'rest',job:kept,at:kept.finished||kept.created||''}:{key:'none',dot:'none',text:'Not saved yet',panel:'first'});}
 else states.push({key:'none',dot:'none',text:'Not saved yet',panel:'first'});
 const also=states.slice(1).find(s=>['cant','failed','waiting'].includes(s.key));
 return {...base,load:loadNewer?load:null,...states[0],also:also?{key:also.key,text:also.text,panel:also.panel}:null};
}
```

### 3.6 What was checked

A throwaway Node script loaded today's `app/static/status.js` and the code above into one `vm` context and
printed 18 cases (exit status 0; `node --check` on the function file, exit status 0). The script is not in
the repository. Output:

```
saved                saved | ok | Saved 21 min ago | rest |
saving               saving | busy | Saving… | saving |
uploading            saving | busy | Uploading… | saving |
waiting              waiting | warn | 1 save to upload | upload |
waiting2same         waiting | warn | 2 saves to upload | upload |      (three jobs, two distinct commits)
failed               failed | bad | Upload failed | failed |
cantProblem          cant | bad | Can’t save | cant | waiting       (also: waiting)
cantDevice           cant | bad | Can’t save | cant |
none                 none | none | Not saved yet | first |
noneBound            none | none | Not saved yet | first |
loading              loading | busy | Loading… 2 of 4 | loading |
running              running | info | Running ospf-up | running |
runningThenSave      saved | ok | Saved just now | rest |
partial              partial | warn | Loaded 3 of 4 | partial | waiting
waitingOverRunning   waiting | warn | 1 save to upload | upload |
kept                 kept | none | Kept on this VM | rest |
unchangedKeepsTime   saved | ok | Saved 21 min ago | rest |
failedLoadIgnored    saved | ok | Saved 21 min ago | rest |
just now / 59 min ago / 2 h ago / yesterday / 3 days ago
```

This is a smoke run of the design, not a test suite and not browser evidence. The tests to write are in
section 8.4.

### 3.7 The home card

`homeSavedLine()` (`app/static/home.js:7-14`) switches from `progressState` to
`saveChipState(lab, state).text`. The card then says exactly what the chip says. Home has no `problem`
input until N1 exists, which is also true today (`home.js:8` passes none). The card's attention rule
(ADDENDUM J3, "progress attention label when `progressState.key` ∈ {attention, failed, interrupted, local}")
becomes "`saveChipState.key` ∈ {`cant`, `failed`, `partial`, `waiting`}".

## 4. The save flow as the person sees it

`host` below is `statusHost(lab.git_binding.repository.push_url) || 'the online repository'`
(`status.js:44,141`). `N` devices is `lab.git_binding.node_names.length`.

### 4.1 Step 1: Save starts at once (F02)

Today Save opens the label dialog first (`gitSaveProgress` → `gitLabelDialog`, `git-progress.js:578-583,
566-577`) and the route refuses an empty note (`app/git_progress.py:1332`). By D2 the lead removes that
check; the page then sends an empty note.

- **Action:** click `#git-save-progress`. Handler: `opTask(null, gitSaveProgress)` as today
  (`git-progress.js:784`). New body of `gitSaveProgress(id = activeId)`: unbound lab → open the chip panel
  (first-save view, section 6); otherwise `gitSubmitSave(id, {target: 'latest', push: true, note: ''},
  undefined, {quiet: true})` and open the chip panel.
- **Request:** `POST /api/labs/{id}/git/save` with
  `{request_id, target: 'latest', checkpoint: '', push: true, note: '', backup_job_id: '', replace_baseline:
  false, expected_baseline: '', allow_removed: false}` (`gitSavePayload`, `git-progress.js:71`; model at
  `app/git_progress.py:939-949`). `push: true` does not upload: the server turns it into
  `review_before_push` and `want_push: false` (`app/git_progress.py:1353-1363`).
- **State:** the response is the queued job; `gitRememberJob` puts it into `state.git_jobs`
  (`git-progress.js:611-614`), so the chip reads *Saving* on the same frame. `gitSubmitting`
  (`git-progress.js:548-561`) covers the moment before the response: `renderSaveHeader()` treats it as
  Saving too.
- **Panel:**

```html
<!-- title: dot busy, "Saving…" -->
<p class="save-sub">Reading the configuration of 4 devices. You can keep working.</p>
```

  The sentence follows the job's phase: `queued`, `capturing` → `Reading the configuration of N devices. You
  can keep working.`; `exporting` → `Saving to the lab VM’s repository. You can keep working.`; `pushing` →
  `Uploading to <host>. You can keep working.`
- The toast `Saving progress…` (`git-progress.js:558`) goes: the panel says it.
- The request-reuse logic (`gitReusableRequest`, `git-progress.js:538-543,554`) stays. An empty note makes
  two consecutive saves identical requests; that is the case it was written for (it replays only while the
  first save is not known as finished).

**What the page needs back (D2):**

- **NEEDS (backend) N3:** `note` may be empty; once the changed files are known and before the commit the
  manager sets `job.note` to the automatic name and `job.note_auto = true`, both in `public_job`. The page
  never builds the name itself.

**Refusals of the request** (`gitSubmitSave` throws): the message becomes `saveHeader.refusal = {lab,
message}`, the chip turns to *Can't save* and the panel shows the 6.5 view for it. It is cleared by the next
accepted save and when the panel closes. Messages that can arrive: lab busy (`app/git_progress.py:602-605`),
`Reconnect the original VM before saving progress.` (`:1342`), `Configured devices changed…` (`:1344`), the
sibling refusal (`:283-292,636-639`; its future is the lead's, D8), and any helper error. Today these go to
the lab banner through `showActionError` (`operations.js:26`, `shell.js:192-197`); for the save flow the chip
panel replaces the banner.

### 4.2 Step 2: nothing changed (F14)

How the backend reports it today: the helper answers `status: 'unchanged'` with `commit = HEAD`
(`app/host_git.py:644-654`); `finish()` gives the job status `unchanged` only when the manager knows that
exact commit as uploaded through the same binding, with the message `Nothing changed since the last save,
which was uploaded.` (`app/git_progress.py:888-903`). When HEAD was never uploaded, the same helper answer
ends as `review_pending` with empty `changed_files` (`app/git_progress.py:900,905-906`).

- `unchanged`: toast `Nothing changed since your last save.`, the panel closes, the chip returns to its
  previous state and keeps its time (section 3.3).
- `review_pending` with nothing changed (an earlier save still waits): chip *Waiting*, panel as in 4.3 with
  the sentence `Nothing changed since your last save, which is not uploaded yet.` The count stays the same
  because both jobs hold the same commit (the function counts distinct commits).

### 4.3 Step 3: the upload sentence (G11)

Chip *Waiting*; the panel opens by itself (section 2.5).

```html
<!-- title: dot warn, "Not uploaded yet" -->
<p class="save-sub" id="save-changes">2 devices changed since your last save: ceos and xrv9k. 19 lines added, 1 removed.</p>
<div class="save-row">
  <button type="button" class="button primary" id="save-upload" data-save-action="upload">Upload</button>
  <button type="button" class="button ghost small" id="save-not-now" data-save-action="not-now">Not now</button>
  <button type="button" class="button ghost small" id="save-see" data-save-action="changes">See changes</button>
</div>
<p class="save-note">Saved files can contain passwords or keys.</p>
<p class="form-error" role="alert" id="save-panel-error"></p>
```

**Where the sentence comes from.** The review data of today is the answer of
`POST /api/labs/{id}/git/compare {job_id}` (`app/git_progress.py:1531-1567`):

- `files[]`: each `{name, status: 'added'|'removed'|'changed', before, after}` from the helper
  (`app/host_git.py:729-749`), plus `diff` (`{hunks, added, removed, truncated, identical}`) and `label` (the
  name without its extension) from `annotated_compare` (`app/git_progress.py:144-151`), and `renamed_from`
  for a folded suffix rename (`app/git_progress.py:108-141`);
- `also_sends`, `also_sends_other_labs`, `also_sends_kept`, and `upload_blocked` when another lab's
  unreviewed save holds the upload (`app/git_progress.py:1563-1566`).

That list is every file of the saved folder that differs from the parent commit. It contains, as separate
entries with no mark telling them apart:

- each changed device's human file (`<label>.cfg`, `app/git_progress.py:403-408`),
- the same device's restore artifact (`<label>.jcfg`, `.xrcfg`, `.eoscfg`; `app/git_progress.py:422-430`,
  `app/inventory.py:17,28,30`), which changes whenever the device changes,
- the topology file and the map (`<lab>.clab.yml`, `<lab>.clab.yml.annotations.json`;
  `app/git_progress.py:433-462`, `app/downloads.py:133-136`).

`manifest.json` is not in the list (`read_version` returns only the manifest's files,
`app/host_git.py:712-726`). `job.changed_files` is a list of repository paths that does include the manifest
and the artifacts (`app/host_git.py:635-643`), so it cannot give a device count either.

So "each device counted once and its restore artifact never a second change" cannot be computed safely in
the page today: it would have to guess from file extensions, and a legacy artifact suffix or a device named
like the lab would break the guess.

- **NEEDS (backend) N4:** the compare answer for a job gains
  `summary: {devices: [short names, sorted], lines_added, lines_removed, topology: bool, map: bool, first:
  bool}` computed from the manifest (an entry with `node` is a device, its `restore_artifact` belongs to it,
  an entry with `kind` is the topology or the map; `_node_slots` already pairs them this way for the
  version compare, `app/git_progress.py:502-516`). `lines_*` count the device human files only. And each
  `files[]` entry gains `kind: 'device' | 'restore' | 'topology' | 'map'` and, for the first two, `node`, so
  the drawer can list one entry per device. The automatic name of N3 comes from the same summary, so the
  name and the sentence never disagree.

The sentence is built by one pure function, `saveChangeSentence(summary)`:

| Summary | Sentence |
|---|---|
| devices `[ceos, xrv9k]`, +19 −1 | `2 devices changed since your last save: ceos and xrv9k. 19 lines added, 1 removed.` |
| one device | `1 device changed since your last save: ceos. 3 lines added, 0 removed.` |
| more than four devices | `6 devices changed since your last save: ceos, r1, r2 and 3 more. …` (all of them are in See changes) |
| devices and topology | `… 19 lines added, 1 removed. The topology changed.` |
| devices, topology and map | `… The topology and the map changed.` |
| only the map | `The map changed since your last save.` |
| only the topology | `The topology changed since your last save.` |
| `first: true` | `This is the first save here: 4 devices, the topology and the map.` |
| nothing | `Nothing changed since your last save, which is not uploaded yet.` |

After the sentence, when the review data says so (today's wording, `git-progress.js:668`, kept because the
person must know what an upload carries):

- `also_sends > 0`: a second `save-note`: `Upload also sends 1 earlier save that is still on the lab VM.`
  (`N earlier saves that are`; `, K of them from other labs in this repository` when
  `also_sends_other_labs > 0`; the kept ones named as today).
- `upload_blocked`: the server's sentence replaces the Upload button's row: the text, Upload disabled, and
  the action that clears it beside it. **NEEDS (backend) N5** (only if the lead keeps the sibling rule):
  `upload_blocked_lab: {id, name}` so the button can read **Open <lab>**; and the sentence's "› Progress"
  wording (`app/git_progress.py:290-292`) must change with the tab.

**Loading and failure of the review data.** The panel calls `gitReviewJob(job)` (section 4.5) when it shows
the upload view. Until the answer is there the body is `<p class="save-sub" role="status">Reading what
changed…</p>` with **Not now** only: Upload is not rendered before the sentence is, because the click on
Upload is the statement that the review happened. If the request fails: `What changed could not be read from
the lab VM.` with **Try again** (`data-save-action="review-again"`) and **Details** (section 4.6). The
answer is cached per job id in `gitReviews`, so the poll does not ask again.

### 4.4 Step 4: See changes (F04, head only)

**See changes** closes the panel and opens the *What changed* drawer (`dialog#save-drawer.drawer.save-drawer`;
its body is the drawer designer's, built from the same cached review data with `gitFilesDiffMarkup`,
`git-progress.js:134-137`). The head this slice fixes:

```html
<div class="drawer-head"><div class="dialog-head"><h2 id="save-drawer-title">What changed</h2>
<button type="button" class="icon-button close" aria-label="Close"><svg class="icon" width="16" height="16" aria-hidden="true"><use href="#i-close"></use></svg></button></div>
<p class="drawer-meta">ceos and xrv9k · 19 lines added, 1 removed · not uploaded yet</p>
<div class="save-row"><button type="button" class="button primary" data-save-action="upload">Upload</button><button type="button" class="button ghost small" data-save-action="not-now">Not now</button></div>
<p class="form-error" role="alert"></p></div>
```

The two buttons carry the same `data-save-action` values as the panel's and are served by the same function,
`saveAction(action, job)`, through one delegated listener per container (`#save-panel`, `#save-drawer`).
When the save is already uploaded (the drawer opened later from All versions) the row is not rendered and
the meta line ends `· uploaded`.

### 4.5 Step 5: Upload, through `gitReviewJob`

Today `gitReviewJob(job)` fetches the compare answer, opens the *Review before uploading* dialog and its
**Upload these changes** button posts `{push: true, reviewed: true}` to `/api/git/jobs/{id}/retry`
(`git-progress.js:654-672`; the literal is on line 672). The server refuses an upload of an unreviewed save
without that flag (`app/git_progress.py:1441-1445`). `gitNeedsReview` says when a save needs it
(`git-progress.js:652`). Other callers: `gitSavesAction` (`:419`), `gitRenderJob` (`:643`), `gitStartWatch`
(`:692`), and the comment contract in `network-design.js` (`operations.js:873`, `network-design.js:2122-2139`).

New shape, same name, same file, still the only sender:

```js
const gitReviews=new Map();   // job id → the compare answer the person was shown
// The review of a save. Without options it reads what the save changed (and what an upload would carry along) and returns it;
// the chip panel and the What changed drawer render it. With {upload:true} it uploads, and only for a save whose review data
// was read and rendered: this function is the only sender of {push:true, reviewed:true}.
async function gitReviewJob(job,options={}){
 if(!options.upload){
  const result=await json('/labs/'+encodeURIComponent(job.lab_id)+'/git/compare','POST',{job_id:job.id});
  gitReviews.set(job.id,{...result,shown:false});return gitReviews.get(job.id);
 }
 const review=gitReviews.get(job.id);
 if(gitNeedsReview(job)&&!(review&&review.shown))throw new Error('See what changed before uploading.');
 const next=await json('/git/jobs/'+encodeURIComponent(job.id)+'/retry','POST',gitNeedsReview(job)?{push:true,reviewed:true}:{push:true});
 gitRememberJob(next);gitStartWatch(next,{quiet:true});await refresh();return next;
}
```

- `review.shown` is set by the panel and by the drawer when they have rendered the sentence (or the file
  list) for that job. An Upload click that arrives without it is refused in the page.
- A save whose review is already recorded (`job.reviewed`, an upload that failed afterwards) uploads with
  `{push: true}`, as `gitRenderJob` does today (`git-progress.js:645`).
- **Both Upload buttons:** `saveAction('upload', job)` →
  `opTask(null, () => gitReviewJob(job, {upload: true}))`. The panel passes its own `.form-error` holder so a
  refusal (for example the 409 of `app/git_progress.py:1462`) is shown in the panel, not in the lab banner.
- **After the click:** the job goes `queued` → `pushing`; chip `Uploading…`; the panel shows the saving view
  with `Uploading to <host>. You can keep working.`; the drawer, when it was the origin, closes at once.
- **Success** (`synced`): chip *Saved*, toast `Uploaded to <host>.` (F05), the panel closes, focus to the
  chip when it was inside the panel.
- **Failure** (`push_pending`, `app/git_progress.py:872,898`): chip *Failed*, panel F13 (section 4.6).

The job window keeps its **Review changes** and **Review and upload…** buttons (`git-progress.js:639`); they
now open the *What changed* drawer instead of the old dialog. `#git-diff-dialog` remains for
`gitCompareVersion` (`git-progress.js:743-748`) until the drawer designer replaces that too.

### 4.6 Step 5, failure (F13) and Details

```html
<!-- title: dot bad, "Upload failed" -->
<p class="save-sub">Your save is safe on the lab VM, but github.com could not be reached.</p>
<div class="save-row">
  <button type="button" class="button primary" id="save-retry" data-save-action="upload">Try again</button>
  <button type="button" class="button ghost small" id="save-details" data-save-action="details">Details</button>
</div>
<p class="form-error" role="alert" id="save-panel-error"></p>
```

- The sentence ends `…but <host> could not be reached.` only when the job message is a connectivity failure
  (`The remote branch is unavailable. Check connectivity…`, `app/host_git.py:416`; `Git command timed out`,
  `:246-249`). For every other cause it ends `…but it could not be uploaded to <host>.` (today's sentence,
  `status.js:156`) and the 6.5 table adds the reason and its action (section 5.2). Saying "could not be
  reached" for a missing login would be untrue.
- **Try again** is the same `upload` action: the review is already recorded when the failed attempt was an
  upload of a reviewed save, so it sends `{push: true}`; when it is not (a save that never got to its
  review), the panel shows the upload view first.
- **Details** opens today's save window: `gitShowJob(job.id)` (`git-progress.js:626-632`), the
  `#git-job-dialog` with the message, destination, commit, **View configuration backup**, the retry buttons
  and **Keep snapshot only** (`git-progress.js:633-647`). It is opened with the chip as opener so focus
  returns there.

### 4.7 Step 6: Not now

Closes the panel (or the drawer). No request. The job stays `review_pending`; the chip stays *Waiting*. This
is what today's **Not now — keep it on the VM** does (`git-progress.js:671`), without its toast. The save is
uploaded later from the chip: chip → **Upload**.

Today's *Save on this VM only* (`gitSaveOptions('local')`, `git-progress.js:585-610`) sent `push: false`,
which ends as `committed` instead of `review_pending` (`app/git_progress.py:901`). Both are *Waiting* and both
need the review before an upload (`gitNeedsReview`, `git-progress.js:652`), so the new flow needs only the
one path.

**Keep snapshot only** (dismiss, `git-progress.js:698-701`, `app/git_progress.py:1466-1472`) stays in the
Details window. It is not offered in the panel.

### 4.8 Step 7: name and checkpoint (F06)

The *Saved* panel has two forms:

- **Naming form (F06)** when the latest save's name is automatic (`job.note_auto`) or it is the save the
  person is naming in this panel session (`saveHeader.naming === job.id`, kept until the panel closes).
- **Rest form (G10)** otherwise (section 5.1).

```html
<!-- title: dot ok, "Saved just now" -->
<label class="sr-only" for="save-name">Name of this save</label>
<input id="save-name" class="save-name" value="ceos and xrv9k changed" maxlength="120" autocomplete="off" spellcheck="false">
<label class="checkbox-label save-keep"><input type="checkbox" id="save-keep" data-save-action="keep"> Keep as a checkpoint</label>
<p class="form-error" role="alert" id="save-panel-error"></p>
<!-- then the rest form's lines and foot (section 5.1) -->
```

**Rename.** Committed on `change` (blur or Enter), never per keystroke; Enter does not close the panel.

- Validation in the page as today's `gitValidateLabel` (`git-progress.js:83-88`): tabs and newlines folded
  to a space, trimmed, at most 120 characters. An empty field restores the previous name and sends nothing.
- **NEEDS (backend) N6:** `POST /api/git/jobs/{job_id}/rename {note}` → the public job with the new `note`
  and `note_auto: false`. It changes only the name the manager shows, never a commit (PROMPT 7.3), validates
  like the save route's note (`app/git_progress.py:1328`), works for a save in any finished status, and is
  not held by `idle()` (a rename must work while a backup runs).
- While the request is in flight the field is read-only; on success the live region says `Renamed.`; on
  failure the message is in `#save-panel-error` and the field keeps what was typed (`data-dirty` stays).

**Keep as a checkpoint** (D6).

- **Request:** `POST /api/labs/{id}/git/save` with `{request_id, target: 'checkpoint', checkpoint: <name>,
  backup_job_id: job.backup_job_id, push: true, note: job.note}`. The route already takes a finished capture
  this way and reads no device (`app/git_progress.py:1345-1350`, `execute` at `:820-835`).
- The checkpoint name must match `[A-Za-z0-9][A-Za-z0-9_-]{0,99}` (`app/git_progress.py:1325`) and be unused
  (`app/host_git.py:603`). The page proposes `gitCheckpointName(job.note)` (`git-progress.js:584`).
  **NEEDS (backend) N7:** with `target: 'checkpoint'` and a `backup_job_id`, an empty `checkpoint` means
  "derive it from the note and make it unique"; the job answers with the name used. Without this a name
  collision would only show up later, as a save that needs attention.
- The checkpoint is a new commit, so it goes through the same flow: chip `Saving…`, then *Waiting* with the
  sentence `Checkpoint ospf-up kept. It is not uploaded yet.` and **Upload** / **Not now**. Nothing is
  uploaded without that click.
- After it exists the tick box is ticked and disabled with the text `Kept as checkpoint ospf-up.` Undoing a
  checkpoint is not offered (today's behaviour: checkpoints are never removed).
- **Disabled with its reason.** The capture is "kept" when `state.jobs` still holds the backup job
  `job.backup_job_id` as a complete capture of the binding's devices; `gitCompleteBackups`
  (`git-progress.js:67-70`) is the existing test, and the server refuses otherwise
  (`Capture not found in this lab.`, `app/git_progress.py:1347`). When it is not kept:

```html
<label class="checkbox-label save-keep"><input type="checkbox" id="save-keep" disabled aria-describedby="save-keep-why"> Keep as a checkpoint</label>
<p class="save-note" id="save-keep-why">The device files of this save are no longer kept on the lab VM, so it cannot become a checkpoint. <button type="button" class="link-button" data-save-action="save">Save again</button>, then keep that save.</p>
```

  It never recaptures silently: **Save again** is an ordinary Save.
- **NEEDS (backend) N8:** `capture_kept: bool` on the public job would let the page stop inferring this from
  `state.jobs`; optional.

Both controls are optional and block nothing: the panel can be closed at any moment and the save is complete
without them.

## 5. The chip panel at rest, and the *Can't save* panel

### 5.1 At rest (G10)

```html
<!-- title: dot ok, "Saved 21 minutes ago"  (relativeTime, status.js:54) -->
<p class="save-sub" id="save-rest-name">Interface descriptions cleaned up</p>
<p class="save-kv"><span>Running:</span> your latest save</p>
<p class="save-kv"><span>Uploaded:</span> yes, to github.com</p>
<p class="save-note" id="save-also" hidden></p>
<div class="save-foot">
  <button type="button" class="button ghost small" id="save-all" data-save-action="versions">All versions</button>
  <button type="button" class="button ghost small" id="save-as-state" data-save-action="lab-state">Save as a lab state…</button>
  <button type="button" class="button ghost small" id="save-settings" data-save-action="settings">Save settings</button>
</div>
```

| Line | Source |
|---|---|
| Title | `Saved ` + `relativeTime(state.at)` (long form in the panel, short form in the chip) |
| Name | `job.note` (`PUBLIC_JOB`, `app/git_progress.py:41`); a save from before labels existed shows `Saved without a name` |
| `Running:` | `your latest save` when no load is newer; `<name>, loaded <time>` when `state.load` is set |
| `Uploaded:` | `yes, to <host>` for `synced` / `unchanged`; `no, kept on the lab VM` for `kept`; `not yet` in the other views that reuse the line |
| Foot | **All versions** and **Save settings** open the drawer designer's drawers; **Save as a lab state…** opens the lead's flow (5.5). Each closes the panel first and passes the chip as the opener |

The same foot ends every chip panel view except the first-save view of an unbound lab (nothing to list or
set yet; **Choose another place** is its way to the settings). In the saving view the foot buttons stay
enabled; they read, they do not save.

### 5.2 *Can't save* (6.5)

One view, one sentence, at most two actions and **Details**. The cause is found in this order: `ctx.refusal`
(a refused request), `git_status.code` (N1), else the message text of `ctx.problem` or of the stopped job,
matched by a pure function `saveProblem(message, lab, state)` in `status.js`, in the manner of
`shellErrorSentence` (`shell.js:181-188`).

```html
<!-- title: dot bad, "Can’t save" -->
<p class="save-sub" id="save-cant-why">The lab VM cannot be reached, so nothing can be saved right now.</p>
<div class="save-row">
  <button type="button" class="button primary" id="save-cant-fix" data-save-action="vm">Check the VM connection…</button>
  <button type="button" class="button ghost small" id="save-cant-retry" data-save-action="again">Try again</button>
  <button type="button" class="button ghost small" id="save-details" data-save-action="details">Details</button>
</div>
```

| Cause (code) | Existing backend signal | Sentence | Primary action | Also |
|---|---|---|---|---|
| VM unreachable (`vm`) | `Connect the VM and verify its SSH host fingerprint first.` (`app/git_progress.py:322`); `Cannot reach the VM Git helper…` (`:583`); `Git connection interrupted…` (`:340`); `The VM identity changed…` (`:575`); `Reconnect the original VM before saving progress.` (`:1342`); `state.discovery.connected === false` (`home.js:17`) | `The lab VM cannot be reached, so nothing can be saved right now.` | **Check the VM connection…** → `openVmDialog()` (`app/static/management.js:182`, as the banner does, `app.js:248`) | Try again, Details |
| Account cannot upload (`account`) | `Git push preflight failed…` (`app/host_git.py:307`); `The VM account is not signed in to GitHub…` (`:818`); `…cannot push to <slug>…` (`:824`); `…push failed. Check authentication…` (`:474`) | `The lab VM’s account cannot upload to <host>: it is not signed in there, or it may not write to this repository.` | **Try again** | Details |
| Unfinished Git work (`busy`) | `Finish the existing Git operation before saving lab progress.` (`app/host_git.py:340`); `The repository already has staged changes…` (`:341`); `The repository has unsaved edits in the selected scope…` (`:344`); the staged-edit checks (`:494,499`) | `Someone’s unfinished Git work in the repository on the lab VM is in the way.` | **Try again** | Details |
| Histories diverged (`diverged`) | `The remote branch advanced or diverged…` (`app/host_git.py:468`); `Local and remote history diverged…` (`:757`); `The checkout moved since this save…` (`:465`); `The push would include commits created outside manager saves…` (`:470`) | `The repository on the lab VM and its online copy have gone different ways.` | **Update from the repository** → `gitUpdateRemote(id)` (`git-progress.js:714-718`, `POST /api/labs/{id}/git/update`, `app/git_progress.py:1474-1496`) | Try again, Details |
| A device cannot be read (`device`) | job status `capture_incomplete` (`app/git_progress.py:835-838`, message from `:369`) | `xrv9k could not be read, so nothing was saved.` (the names are the nodes of the linked backup job `job.backup_job_id` in `state.jobs` whose status is not `succeeded`; without them: `A device could not be read, so nothing was saved.`) | **Try again** | Details |
| Devices changed (`settings`) | `Configured devices changed. Review the Git repository device selection.` (`app/git_progress.py:1344`) | `The devices of this lab changed since saving was set up.` | **Save settings** | Details |
| Helper missing or out of date (`other`) | `Git helper is unavailable. Run setup-git.sh on the VM.` (`app/git_progress.py:358`); `Update the VM Git helper…` (`:588`); `Install or refresh the matching Git helper on the VM.` (`:354`) | `Saving is not set up on this lab VM. Ask the person who runs the VM.` | **Details** | Try again |
| Anything else (`other`) | any other message | `The save did not work.` | **Try again** | Details |

What each action does:

- **Try again** (`again`): for a stopped job that can be retried (`export_pending`, `interrupted`), `POST
  /api/git/jobs/{id}/retry {push: false}`, which reuses the capture and ends at the review
  (`app/git_progress.py:1440-1442,1463`); for `capture_incomplete` and `failed`, which the server will not
  retry (`app/git_progress.py:1431-1432`), a new save (section 4.1); for a `problem` or a refusal with no
  job, `gitLoadContext(id, true)` to read the status again (`git-progress.js:138-143`) and then a new save
  when it is ready. In every case "the save resumes from there" (6.5): no other step is needed.
- **Update from the repository**: today's confirmation dialog and request. The route refuses while a save of
  this lab is pending (`guard_pending`, `app/git_progress.py:1477`); a diverged history with a waiting save
  is exactly that case, so the lead must settle it with the pending-save rule of 6.2 (open question 3).
- **Details**: with a job, `gitShowJob(job.id)` (the save window); without one, the *Git details* section of
  the Save settings drawer, which shows the raw status text (today's `#git-advanced-status`,
  `git-progress.js:428`). The raw message is only ever there, never in the sentence.

None of these is a folder rule. The sibling refusal (`app/git_progress.py:283-292`) and "Lab folders cannot
overlap" are not in the table: section 6 of the prompt removes them, and if one still arrives it is shown as
`other` with its text under Details, which the "try to get blocked" pass must then report.

The lab banner's two save branches go (`app.js:237-243`: "Saving to Git is not possible right now." with
**Save location settings**, and the save-attention banner with **Retry** and **Details**): PROMPT 5.11 moves
them to the chip. Banner buttons `#banner-retry-save` and `#banner-save-details` stay in the markup
(load-bearing, ADDENDUM J3) and simply stay hidden.

## 6. First save (5.9, F12)

### 6.1 Today

`gitSaveProgress()` calls `gitFirstSave()` for an unbound lab (`git-progress.js:578-582`): a dialog with
repository select, folder field, device list, the required label and the exposure tick box
(`git-progress.js:507-531`). It registers the folder when needed (`POST
/api/git/repositories/{id}/folders`, `git-progress.js:526`), links the lab (`PUT /api/labs/{id}/git`,
`:527`; route `app/git_progress.py:1135-1166`) and saves (`:529`). With no repository on the VM it opens
`gitConnectByUrl(id, {firstSave: true})` (`git-progress.js:512,485-504`).

### 6.2 With a repository on the VM

Pressing **Save** (or the chip) on an unbound lab opens the chip panel and fetches `GET
/api/git/repositories` and `GET /api/labs/{id}/git` (as `gitFirstSave` does, `git-progress.js:509`). While
they load: `<p class="save-sub" role="status">Looking for a place to save…</p>`.

```html
<!-- title: dot none, "Not saved yet" -->
<p class="save-sub" id="save-first-place">Your first save goes to CLAB-MNGR-DEV-LLM, in a folder named restore-square.</p>
<div class="save-row">
  <button type="button" class="button primary" id="save-first" data-save-action="first-save">Save</button>
  <button type="button" class="button ghost small" id="save-first-place-other" data-save-action="place">Choose another place</button>
</div>
<p class="save-note">Saved files can contain passwords or keys.</p>
<p class="form-error" role="alert" id="save-panel-error"></p>
```

- **Default place.** Repository: the name of the checkout (`gitRepoName`, `git-progress.js:26`); with several
  checkouts (`git-progress.js:513` collapses registrations by path), the one most labs of this manager save
  to, else the first by name. Folder: `gitSuggestedFolder(lab.name)` (`git-progress.js:484`), which is
  today's default in both first-save dialogs. The sentence says "in a folder named" and never claims that
  the folder exists (the planned-folder rule in `CLAUDE.md`).
- **Devices.** Every supported device (`supported_nodes`, `app/git_progress.py:1127`), as the dialog's
  default today (`git-progress.js:514`). Changing them is in Save settings. A lab with no supported device
  shows `This lab has no device whose configuration can be saved.` and no Save button; the reason is the
  sentence.
- **The exposure tick box is gone (D5).** The sentence beside the button replaces it. No route on this path
  asks for an acknowledgement (`Link` has none, `app/git_progress.py:933-937`).
- **Save** (`first-save`): bind, then save, in one click:
  1. `POST /api/git/repositories/{registration}/folders {prefix}` when no registration has that folder, then
     `PUT /api/labs/{id}/git {binding_id, node_names}`: today's two calls
     (`git-progress.js:524-527`). The lead's folder model replaces them.
     **NEEDS (backend) N9:** one call that places a lab: repository (checkout), folder, devices → the
     binding, with every folder situation of 6.2 answered in the response rather than as an error. On a
     standard install the checkout is registered at its top level (PROMPT 6.1) and today's first call is the
     one that is refused; the first-save panel is only as good as that route.
  2. `gitSubmitSave(id, {target: 'latest', push: true, note: ''}, undefined, {quiet: true})` and the flow of
     section 4 from step 1.
  If step 1 answers with a question (another lab saves there, the folder holds a lab state), the panel hands
  over to the folder chooser, which asks it with its buttons (6.2 and 6.3; the lead's component). If it
  fails for an outside cause, the panel shows the 6.5 view.
- **Choose another place** (`place`): closes the panel and opens the folder chooser for this lab, starting
  at the proposed repository and folder. Contract with the lead: `saveChoosePlace(labId, {repository,
  prefix, opener: $('save-chip'), then})`; when the chooser ends in **Save here** it binds the lab and calls
  `then()`, which is the save of step 2. Today's counterpart is **Browse…** (`git-progress.js:517`).

### 6.3 Bound, but nothing saved yet

Row 9b. Same view, sentence `Your first save goes to <repository>, in the folder <prefix>.` (or `…at its
top level.`), **Save** is the ordinary save, and the second button is **Save settings**.

### 6.4 No repository on the VM

When the catalogue is empty the same panel asks for the address in one field:

```html
<!-- title: dot none, "Not saved yet" -->
<p class="save-sub">Your saves go to a repository on GitHub. Paste its address; ask your instructor if you do not have one.</p>
<label for="save-url">Repository address (HTTPS)</label>
<input id="save-url" class="save-name" placeholder="https://github.com/you/your-lab-repo" autocomplete="off" spellcheck="false" inputmode="url">
<p class="save-note">The lab VM’s own GitHub login is used. You are never asked for a password or a token here.</p>
<div class="save-row">
  <button type="button" class="button primary" id="save-first" data-save-action="first-connect">Save</button>
</div>
<p class="save-note">Saved files can contain passwords or keys. They go into a folder named restore-square.</p>
<p class="form-error" role="alert" id="save-panel-error"></p>
```

Reused from `gitConnectByUrl` (`git-progress.js:485-504`):

- the address check `/^https:\/\/[^\s/]+\/\S+/` and its message (`:493`);
- the request `POST /api/labs/{id}/git/connect {url, prefix, acknowledge: true, node_names: []}` (`:499`;
  route `app/git_progress.py:1289-1306`, model `:981-987`). The route requires `acknowledge: true`
  (`app/git_progress.py:1292`); the Save button sends it, as the Load button sends its acknowledgement (D4).
  `prefix` is `gitSuggestedFolder(lab.name)`; empty `node_names` means every supported device
  (`app/git_progress.py:1301`);
- the waiting label, moved to the panel: title `Connecting…`, `This can take a minute.` (`:497`);
- then the save, as `options.firstSave` does today (`:501`), without the label dialog.

A helper error (`GitHub CLI is not installed…`, `The VM account is not signed in to GitHub…`, `…cannot push
to…`, `Cloning failed…`; `app/host_git.py:816-824,853`) is shown in `#save-panel-error` in the server's own
words: these are setup instructions and need their detail. The typed address stays in the field
(`data-dirty`, section 2.4).

Retired from that dialog for this path: the folder field (the default is stated; **Save settings** changes
it afterwards), the exposure tick box, and **Back up to this VM instead**
(`git-progress.js:487-490`; the backup stays under Tools › Configuration backups, `index.html:154`).
`gitConnectByUrl` itself stays for **Connect by URL…** in the Save settings drawer.

The catalogue request can fail (`409` with the helper's reason, `app/git_progress.py:1115-1118`): the panel
then shows the 6.5 view (usually `vm` or the helper row), not the address field. An empty catalogue and an
unreachable VM must never look the same.

## 7. Wording

Every final string of this slice. `…` is one character; apostrophes are typographic. `<host>` is the push
host or `the online repository`.

| Where | State | String |
|---|---|---|
| Buttons | header | `Save` · `Load` |
| Chip | Saved | `Saved just now` · `Saved 21 min ago` · `Saved 2 h ago` · `Saved yesterday` · `Saved 3 days ago` · `Saved 12 Sep` |
| Chip | Saving | `Saving…` · `Uploading…` · `Updating…` |
| Chip | Waiting | `1 save to upload` · `3 saves to upload` |
| Chip | Failed | `Upload failed` |
| Chip | Needs attention | `Can’t save` |
| Chip | Not saved | `Not saved yet` |
| Chip | kept | `Kept on this VM` |
| Chip | Loading | `Loading… 2 of 4` · `Loading…` · `Checking devices…` |
| Chip | Running | `Running ospf-up` |
| Chip | Partial | `Loaded 3 of 4` |
| Reason line | Save disabled, other work | `A backup or lab operation is running. Save is available when it finishes.` |
| Panel title | Saving | `Saving…` · `Uploading…` · `Connecting…` |
| Panel | Saving | `Reading the configuration of 4 devices. You can keep working.` · `Reading the configuration of 1 device. You can keep working.` · `Saving to the lab VM’s repository. You can keep working.` · `Uploading to github.com. You can keep working.` |
| Toast | unchanged | `Nothing changed since your last save.` |
| Panel title | Waiting | `Not uploaded yet` |
| Panel | Waiting | the sentences of section 4.3 · `Reading what changed…` · `What changed could not be read from the lab VM.` |
| Panel | Waiting, more | `Upload also sends 1 earlier save that is still on the lab VM.` · `Upload also sends 3 earlier saves that are still on the lab VM, 1 of them from another lab in this repository.` |
| Panel | Waiting, checkpoint | `Checkpoint ospf-up kept. It is not uploaded yet.` |
| Panel buttons | Waiting | `Upload` · `Not now` · `See changes` |
| Note | every view that can upload or save for the first time | `Saved files can contain passwords or keys.` |
| Drawer head | What changed | `What changed` · `ceos and xrv9k · 19 lines added, 1 removed · not uploaded yet` · `… · uploaded` |
| Toast | uploaded | `Uploaded to github.com.` |
| Panel title | Failed | `Upload failed` |
| Panel | Failed | `Your save is safe on the lab VM, but github.com could not be reached.` · `Your save is safe on the lab VM, but it could not be uploaded to github.com.` |
| Panel buttons | Failed | `Try again` · `Details` |
| Panel title | Saved | `Saved just now` · `Saved 21 minutes ago` |
| Panel | naming | label `Name of this save` · tick box `Keep as a checkpoint` · `Kept as checkpoint ospf-up.` · `Renamed.` (live region) |
| Panel | naming, disabled | `The device files of this save are no longer kept on the lab VM, so it cannot become a checkpoint.` `Save again`, `then keep that save.` |
| Panel | rest | `Running:` `your latest save` / `ospf-up, loaded 1 minute ago` · `Uploaded:` `yes, to github.com` / `no, kept on the lab VM` · `Saved without a name` |
| Panel foot | every bound view | `All versions` · `Save as a lab state…` · `Save settings` |
| Panel | hidden second state | `Also: 1 save to upload.` · `Also: the last upload failed.` · `Also: saving is not possible right now.` · button `Show` |
| Panel title | Needs attention | `Can’t save` |
| Panel | Needs attention | the seven sentences of section 5.2 |
| Panel buttons | Needs attention | `Try again` · `Update from the repository` · `Check the VM connection…` · `Save settings` · `Details` |
| Panel title | Not saved | `Not saved yet` |
| Panel | first save | `Looking for a place to save…` · `Your first save goes to <repository>, in a folder named <lab>.` · `Your first save goes to <repository>, in the folder <prefix>.` · `Your first save goes to <repository>, at its top level.` · `This lab has no device whose configuration can be saved.` |
| Panel buttons | first save | `Save` · `Choose another place` |
| Panel | first save, no repository | `Your saves go to a repository on GitHub. Paste its address; ask your instructor if you do not have one.` · label `Repository address (HTTPS)` · `The lab VM’s own GitHub login is used. You are never asked for a password or a token here.` · `Saved files can contain passwords or keys. They go into a folder named <lab>.` · `This can take a minute.` |
| Error | first save, bad address | `Paste the HTTPS address, for example https://github.com/you/your-lab-repo.` (today's, `git-progress.js:493`) |
| Error | Upload before the sentence | `See what changed before uploading.` |
| Lifecycle dialogs | `operations.js:238` | `Save first` (was `Save progress first`) |

Not used anywhere in these views: "registration", "prefix", "overlap", "commit", "push", "review", "Git"
(except "GitHub" as the place and in the server's own setup messages), "snapshot".

## 8. File plan

### 8.1 Files that change

| File | Change |
|---|---|
| `app/static/index.html` | header markup of section 1.2 in place of `index.html:75`; `#lab-progress` removed from `index.html:73`; `<script src="/static/save-header.js?v=<release>" defer>`; `dialog#save-drawer` at page level (drawer designer) |
| `app/static/status.js` | `saveChipState`, `relativeTimeShort`, `saveLoadName`, `saveProblem`, `saveChangeSentence`, the five constants; header comment line 6 reworded. `progressState` and `progressSummary` stay |
| `app/static/shell.js` | the four edits of section 2.2 and the sentence at `:183` |
| `app/static/app.js` | `render()` calls `renderSaveHeader()` after `renderGitProgress()` (`app.js:122`); `renderLabHeader` loses its `#lab-progress` line (`app.js:103`); the two save branches of `renderLabBanner` go (`app.js:237-243`); `renderWorkerState` text `Saving progress…` → `Saving…` (`app.js:96`) |
| `app/static/save-header.js` | new, section 8.2 |
| `app/static/git-progress.js` | section 8.3 |
| `app/static/home.js` | `homeSavedLine` uses `saveChipState` (`home.js:7-14`) |
| `app/static/operations.js` | button label at `:238`; the comment at `:873` stays true |
| `app/static/style.css` | section 1.4; the `.git-save-*` rules go with the menu |
| `app/git_progress.py`, `app/main.py`, `app/restore.py` | the lead's, for N1 to N9 |
| `docs/redesign/DESIGN-SPEC-ADDENDUM.md` | not edited by this slice; the lead records that J2's `git-save-menu`, J3's two save banners, J4's "Only `#git-save-menu` stays a `details`" and J6's first save are superseded by owner decisions D1, D2, D3 and D5 |

### 8.2 The new script

`app/static/save-header.js`, loaded only by `index.html`, after `git-progress.js` and before
`git-places.js` (order: `… diff-view.js, git-progress.js, save-header.js, git-places.js, restore.js, …`). It
needs `?v=<release>` in `index.html`; `deploy/verify-release.py` checks that marker on every static asset of
the page, and `deploy/set-release.py` moves it (the lead runs both). No other page loads it.

House style: `'use strict'`, no listener on `document` or `window`, every global read at call time behind
`typeof` guards so the file loads in a Node `vm` context with a fake `$`, `esc` and `state`.

| Function | Does |
|---|---|
| `saveHeader` | page memory: `{refusal, opened: Map, last: Map, naming, view}` |
| `renderSaveHeader()` | called from `render()`; computes `saveChipState(current(), {…state, problem: gitProblem(lab), refusal})`; writes chip, title, reason line, `disabled` of Save and Load, the live region; renders the body through `savePanelMarkup` when the panel is open |
| `savePanelView(cs, lab)` | pure: `{title, dot, key, html}` for the views `first`, `saving`, `upload`, `failed`, `cant`, `rest`; for `loading`, `running`, `partial` it calls the Load designer's `loadChipView(cs, lab)` when defined |
| `savePanelMarkup(el, key, build)` | section 2.4 |
| `saveAction(action, job, origin)` | the one dispatcher for `data-save-action` in the panel and the drawer head: `upload`, `not-now`, `changes`, `details`, `again`, `review-again`, `vm`, `update`, `settings`, `versions`, `lab-state`, `place`, `first-save`, `first-connect`, `keep`, `save`, `show-also` |
| `saveFinished(job)` | section 2.5; called by `gitStartWatch` |
| `saveFirstPlace(lab, catalog)` | pure: the default repository and folder of section 6.2 |
| `saveRename(job, value)` | section 4.8 |
| load-time block | `if($('save-chip')){…}`: the delegated `click` and `change` listeners on `#save-panel`, `panelopen` → render, `panelclose` → clear `refusal` and `naming` |

Hand-off points in this file: `loadChipView` and the Load button's reason (Load designer);
`saveOpenVersions(id, opener)`, `saveOpenSettings(id, opener)`, `saveOpenChanges(job, opener)` (drawer
designer); `saveChoosePlace(…)` and `saveAsLabState(id, opener)` (lead).

### 8.3 `git-progress.js` and `app.js`: what moves, stays, retires

Consumers were searched in `app/static/*.js`, `app/static/*.html`, `tests/*.js` and `docs/*/tools/*.py`.

**Stay unchanged:** `gitActiveStates`, `gitPendingStates`, `gitStateLabels`, `gitSaveSentences`, `gitLabel`,
`gitJobTime`, `gitTime`, `gitWhen`, `gitLabJobs`, `gitRepository`, `gitRepoName`, `gitSnapshotPath`,
`gitTargetPath`, `gitSavePayload`, `gitRequestId`, `gitReusableRequest`, `closeDialogsExcept`,
`gitFocusDialog`, `gitDestinationMarkup`, `gitJobMarkup`, `gitFilesDiffMarkup`, `gitLoadContext`,
`gitRememberJob`, `gitJobTitle`, `gitShowJob`, `gitNeedsReview`, `gitDismissJob`, `gitCompleteBackups`,
`gitCheckpointName`, `gitSuggestedFolder`, `gitUpdateRemote`, `gitConnectByUrl` (without its `firstSave`
branch). `gitProblem`, `busy`, `notify`, `setMarkup`, `setListMarkup` in `app.js`.

**Stay, changed:**

| Function | Change | Consumers to keep working |
|---|---|---|
| `gitSaveProgress` (`:578`) | no label dialog; unbound → first-save panel | `operations.js:238-241`, `tests/test_git_progress_ui.js` |
| `gitSubmitSave` (`:547`) | no `Saving progress…` toast; opens the chip panel | `tests/test_git_progress_ui.js`, `docs/save-location-fix/tools/qa_lib.py` |
| `gitReviewJob` (`:654`) | section 4.5 | `network-design.js` (comment contract), `tests/test_git_progress_ui.js`, `docs/netlab-ui-qa/tools/coverage_run.py` |
| `gitStartWatch` (`:682`) | end of watch → `saveFinished(job)`; no job dialog, no review dialog | `network-design.js:2139`, tests, `coverage_run.py` |
| `gitRenderJob` (`:633`) | `review` opens the *What changed* drawer; the closing note at `:639` no longer names "Progress › Recent saves" | job window |
| `gitUploadLabel` (`:653`) | `Review and upload…` → `See changes and upload…` | `tests/test_git_progress_ui.js:179` (label rewritten, claim kept) |
| `gitSaveReason` (`:186`) | sentence says "Save", feeds `#save-reason` | `tests/test_git_progress_ui.js` |
| `gitValidateLabel` (`:83`) | used by rename only | none outside the file |
| `renderGitProgress` (`:191`) | loses the header lines (`:199-203` for `#git-save-progress`, the menu, the help); what is left serves the Progress tab until the drawer designer removes it | `app.js:122` |
| `gitRunAction` (`:765`) | `settings`, `history`, `load`, `browse` route to the drawers (drawer designer) | `app.js:354`, tools |

**Retire** (each has a decision that removes its subject; tests that pin them are rewritten to the new
behaviour and listed for the report, PROMPT section 8):

| Function or element | Decision | Consumers found |
|---|---|---|
| `gitLabelDialog`, `gitLabelKey`, `gitLabelDraft`, `gitSaveLabelDraft`, `gitClearLabelDraft` (`:77-80,566-577`) | D2 | `tests/test_git_progress_ui.js` (`gitLabelDraft`) |
| `gitFirstSave` dialog (`:507-531`) | D5 | `tests/test_git_progress_ui.js` |
| `gitSaveOptions` for `local` and `checkpoint` (`:585-610`) | D3, D6 | `tests/test_git_progress_ui.js`; the `baseline` part becomes **Use as starting point…** (drawer designer) |
| `gitSaveHelp`, `gitSaveHelpMarkup`, `gitRenderSaveHelp`, `gitShowSaveHelp`, `GIT_SAVE_HELP_ACTIONS` (`:151-169`) | D1 | `tests/test_git_progress_ui.js` |
| `gitSaveMenuPlacement`, `gitPlaceSaveMenu`, `gitInsideMenu` (`:173-183`) | D1; the clamp is `initPanel`'s | `tests/test_git_progress_ui.js`, a comment in `style.css` |
| `gitDoneToast` (`:674-681`) | D3 (the panel and two toasts replace it) | `tests/test_git_progress_ui.js` |
| `gitPushPending` (`:705-713`) | 5.11 (**Upload** in the chip panel) | `app.js:240` (the banner branch that goes), `gitRunAction('push')`, `tests/test_git_progress_ui.js` |
| `GIT_EXPOSURE_TEXT`, `GIT_EXPOSURE_ERROR` on the first-save path (`:10-11`) | D5 | still used by the settings form (`:275,299`) and `gitConnectByUrl` (`:488,496`) until the drawer designer decides |
| `details#git-save-menu`, `#git-save-help*`, header `[data-git-action]` items (`index.html:75`) | D1 | `shell.js:74,130,134`; `tests/test_shell_ui.js`; `docs/redesign/tools/audit_current.py`, `verify_after.py`; `docs/save-location-fix/tools/b4_checkpoints_baseline.py`, `b7_apply.py`, `c_apply.py`; `docs/ui-review-001/tools/check_ui004.py`, `check_ui007ab.py`, `check_ui007c.py`; `docs/ui-ux-cleanup/tools/live_1_30_37_b.py` |
| `#lab-progress` (`index.html:73`) | 5.1 | `app.js:103`; `tests/test_git_onboard.py`; `docs/redesign/tools/verify_after.py`, `verify_stage1.py` |
| document listeners `:794-795` | 5.1 | none |

The Playwright tools under `docs/*/tools` that drive `#git-save-menu` or `#lab-progress` belong to finished
work streams. The ones `CLAUDE.md` names as working regression tooling (`docs/redesign/tools/verify_after.py`,
`docs/ui-review-001/tools/check_ui*.py`) need their selectors moved to the chip in the same change; the
dated ones (`docs/save-location-fix`, `docs/ui-ux-cleanup`, `docs/student-quick-start`) are records and are
listed as out of date, not edited. `tests/test_git_onboard.py` mentions `lab-progress` and is a CI test: it
must be read before the span is removed.

`progressState` and `progressSummary` are not retired: `operations.js:160-161` uses `progressState` for the
last-save line of the lifecycle confirmations, and `tests/test_status_ui.js` pins both.

### 8.4 Node tests to write

New files go to the CI list through the lead (`.github/workflows/release-check.yml` names each browser test
file on one `node --test` line).

**`tests/test_save_chip_ui.js`** (new; harness as `tests/test_status_ui.js`: `status.js` alone in a `vm`
context). One test per row of PROMPT 5.2, then the precedence:

1. Saved: newest save `synced` → `saved`, dot `ok`, `Saved 21 min ago`, panel `rest`.
2. Saving: `queued`, `capturing`, `exporting` → `Saving…`, dot `busy`, `saveDisabled`; `pushing` →
   `Uploading…`.
3. Waiting: one `review_pending` with a commit → `1 save to upload`; `committed` counts; two jobs with one
   commit count once; three commits → `3 saves to upload`; a `dismissed` job does not count.
4. Failed: `push_pending` → `Upload failed`, dot `bad`, and its count.
5. Needs attention: `problem` set; newest `capture_incomplete`; newest `export_pending`; `refusal` set; each
   → `Can’t save`, dot `bad`, panel `cant`.
6. Not saved: no binding → `Not saved yet`, dot `none`, panel `first`; bound without a save the same; an
   unbound lab with old `synced` jobs is still Not saved.
7. Loading: restore `applying` with targets → `Loading… 2 of 4`, both disabled; `interrupted` with
   `rechecking: true` → `Checking devices…`; an `interrupted` job without `rechecking` is not Loading.
8. Running: `succeeded` load newer than the newest save → `Running ospf-up`, dot `info`; `source.label` wins
   over the derived name.
9. Partial: `partial` load with three of four targets replaced → `Loaded 3 of 4`, dot `warn`;
   `rolled_back`, `failed`, `uncertain` targets are not counted as loaded.
10. Precedence: Loading over Saving over everything; Partial over Can't save, Failed and Waiting with
    `also` naming the hidden one; Can't save over Failed over Waiting; Waiting over Running with `load`
    still set; Running over Saved; a save newer than the load gives Saved; an `unchanged` save newer than
    the load clears Running and keeps the earlier save's time; a `failed` or `preflight_failed` load sets no
    state; another lab's jobs never count.
11. `relativeTimeShort`: every threshold, an invalid time gives `''`, never `NaN`.
12. `saveChangeSentence`: each row of the table in section 4.3; a device with a changed restore artifact is
    one device; singular and plural.
13. `saveProblem`: each message cited in section 5.2 maps to its code; an unknown message maps to `other`.

**`tests/test_save_header_ui.js`** (new; harness as `tests/test_readiness_ui.js`: `status.js`, `app.js`,
`git-progress.js`, `save-header.js` with fake elements):

1. Panel markup per view (`first`, `first` without a repository, `saving`, `upload`, `failed`, `cant` for
   each cause, `rest`, naming): the strings of section 7, real `<input type="checkbox">` inside a `<label>`,
   every focusable control with an id, every interpolated value escaped (a lab named `<img>`).
2. Save on a bound lab posts `/labs/{id}/git/save` once with `note: ''` and opens no dialog.
3. Save on an unbound lab posts nothing and opens the first-save view; its Save posts the binding calls and
   then the save; the URL variant posts `/git/connect` with `acknowledge: true` and refuses a non-HTTPS
   address in the page.
4. **Not now** sends no request and closes the panel.
5. **Single sender, behaviour:** Upload in the panel and Upload in the drawer head both end in one
   `POST /git/jobs/{id}/retry` with the body `{"push":true,"reviewed":true}`, and both throw `See what
   changed before uploading.` and post nothing when the review data was not shown. This rewrites the claim
   of `tests/test_git_progress_ui.js:170-187` for the new surface.
6. **Single sender, source:** read every `app/static/*.js` (not the built `lab-builder/` bundle), strip
   comments, and assert that `/reviewed\s*:\s*true/` matches exactly once, inside the text of
   `gitReviewJob.toString()`.
7. `saveFinished`: `unchanged` → the toast and no panel; `review_pending` → the panel opens once for that
   job; not for another lab; not while `dialog[open]` exists; not while another menu is open; not twice.
8. `savePanelMarkup`: an unchanged key does not touch `innerHTML`; a changed key keeps focus by id, keeps
   the typed value and caret of a `data-dirty` input, and sends focus to the title when the control is gone.
9. Chip rendering changes `textContent` and `className` only (the button node is the same object after two
   renders); the live region is written on a key change, not on the first render and not on a time tick, and
   stays silent for `unchanged` and uploaded.
10. Disabled Save: the reason is in `#save-reason` and visible when `busy()`; hidden when the chip is
    `Saving…`.
11. Keep as a checkpoint: enabled when the capture is in `state.jobs`, posts `target: 'checkpoint'` with the
    save's `backup_job_id`; disabled with the reason text and **Save again** when it is not.
12. Rename: Enter commits once, an empty value restores the name and posts nothing, a failed request leaves
    the typed text and shows the message.

**`tests/test_shell_ui.js`** (extended): `initPanel` opens and closes; opening a panel closes an open menu
and the reverse; Escape inside returns focus to the opener; Escape with focus outside closes and leaves
focus; a pointer down inside the wrapper keeps it open and outside closes it; `focusout` to an outside
control closes, `focusout` with no `relatedTarget` does not; `panelCanOpen` is false with a `dialog[open]`
and with another expanded menu; the `#git-save-menu` cases are rewritten to the panel.

**`tests/test_home_ui.js`** (extended): the card's saved line equals the chip text for Saved, Waiting,
Can't save and Not saved.

**`tests/test_git_progress_ui.js`** (rewritten cases, claims kept): the mandatory review (`:170`), the
folder-move review (`:575-583`), the multi-lab review count (`:596`) now asserted on the review data and the
panel sentence; label-draft, save-help and menu-placement tests are rewritten to the new behaviour and named
in the report with D1 and D2.

## 9. Friction budget (PROMPT 9.5) for these flows

Clicks counted from a lab page with nothing open.

| Flow | Path | Clicks | Typed |
|---|---|---|---|
| First save, standard install (one repository on the VM) | **Save** → panel `Not saved yet` → **Save** | 2 | nothing |
| …and uploaded | … → **Upload** | 3 | nothing |
| First save, no repository on the VM | **Save** → paste the address → **Save** | 2 | the address |
| Later save, uploaded | **Save** → **Upload** | 2 | nothing |
| Later save, nothing changed | **Save** → toast | 1 | nothing |
| Later save, kept on the VM | **Save** → **Not now** | 2 | nothing |
| Later save, after looking | **Save** → **See changes** → **Upload** | 3 | nothing |
| Upload a waiting save later | chip → **Upload** | 2 | nothing |
| Retry a failed upload | **Try again** (panel open) or chip → **Try again** | 1 or 2 | nothing |
| Name the latest save | chip → the field → Enter | 1 | the name |
| Keep the latest save as a checkpoint | chip → **Keep as a checkpoint** (→ **Upload**) | 2 (3) | nothing |
| Resume after *Can't save* | the primary action of the panel | 1 | nothing |

The budget's "first save: at most 2 clicks and nothing typed" and "later saves: 2 clicks" hold. The first
save is on the lab VM after two clicks and on GitHub after a third; the third cannot be removed without
uploading without an explicit Upload, which section 8 of the prompt forbids. Change folder, load a lab state
and save as a lab state are measured by their owners.

## 10. Assumptions, open questions, what to attack

### 10.1 Assumptions

1. `/api/state` keeps `git_jobs` and `restore_jobs` in their current public shapes; N1 to N9 are additions.
2. The lead removes the label requirement (`app/git_progress.py:1332`) and writes the automatic name before
   the commit (N3). Until then a page that sends `note: ''` gets a 400.
3. Only `target: 'latest'` saves end *Running* / *Partial* and feed *Saved*. Checkpoints made from a save and
   the starting point read no device, so they say nothing about what runs. Lab-state saves (D9) are assumed
   to be jobs the function does not treat as the lab's own save (a `kind` or a target other than `latest`).
4. One pulsing element per surface (ADDENDUM J5) still binds: the chip dot stops pulsing while the lab pill
   pulses.
5. Design exports (`kind: 'design'`) count in *Waiting* (their commit does wait on the VM) and use the same
   upload view with the files listed in See changes; they never open the panel by themselves.
6. Folder moves (`target: 'move'`) show as `Saving…` while they run; everything else about them is the
   folder model's.
7. `state.jobs` still holds the capture of a recent save, so "capture kept" can be read from it until N8.
8. The Progress tab may still exist while this slice is built (PROMPT 11 puts its removal later); nothing
   here needs it, and `renderGitProgress` keeps serving it.

### 10.2 Open questions for the lead

1. **N1, the problem signal.** `saveChipState` cannot show *Can't save* from `/api/state` alone today: the
   repository status is a VM round trip behind `GET /labs/{id}/git`. Is a cached `lab.git_status` with a
   `code` acceptable, and when is it refreshed? Without it the chip learns of a broken repository only after
   a save failed or a panel loaded the context.
2. **N4, who computes the change summary.** The helper's compare returns files without the manifest. Does
   the manager derive `summary` and `kind` from the capture it holds, or does the helper return the two
   manifests (a helper change that needs the risk review)?
3. **Pending saves and "Update from the repository".** The fix for a diverged history is refused while a
   save waits (`app/git_progress.py:1477`). Which wins under the new pending-save rule?
4. **The sibling hold** (`upload_blocked`, `sibling_refusal`): does it survive D8? If yes the page needs N5
   and a reworded sentence; if no, the `also_sends` line is all that remains.
5. **Precedence of Partial over Can't save, and of Waiting over Running.** Both are judgement calls
   (section 3.4). The `also` line and the `Running:` line make either order workable; confirm the order.
6. A stopped save that cannot be retried (`capture_incomplete`, `failed`) keeps the chip on *Can't save*
   until the next save, as "Save failed" does today. Should the panel offer a way to put it aside?
7. Naming form versus rest form (section 4.8): is "automatic name, or being named now" the right rule, or
   should the name always be an editable field?
8. With several repositories on the VM, which is the default place (section 6.2)?
9. N7: may the manager choose the checkpoint name, or must the panel ask for one?

### 10.3 What a reviewer should attack

1. **The single sender.** `gitReviewJob(job, {upload: true})` trusts `review.shown`, a flag the page sets.
   Find a path that sets it without the sentence or the file list being on screen (a rebuild race, a cached
   answer from an older state of the job, the drawer opened for another job).
2. **Truth of the sentence.** Any case where the sentence under-reports what an upload sends: earlier saves,
   other labs' saves, kept saves, a truncated diff (`counts_partial`, `diff-view.js:26`), more than four
   devices.
3. **Auto-open.** Any way the panel opens over a dialog, steals focus from a field, opens for a save the
   person did not start, or opens twice; and the opposite, a failure that is never shown because every
   condition failed and the person never looks at the chip.
4. **Focus.** Save becomes disabled right after it was clicked; the panel title must have focus by then.
   The rebuild from the upload view to the uploading view removes the focused button. Tab out of the panel.
   The drawer's close returning to the chip.
5. **The precedence table** against real sequences: save, load, save; load during a waiting upload; a
   manager restart during a load (`rechecking`); a save by another browser; clocks (`finished` of a restore
   after a restart is the restart time, ADDENDUM J5).
6. **`interrupted` loads as Partial**: the count of loaded devices may understate what changed. The Load
   designer owns the wording; check that the chip never claims more than the job proved.
7. **Width.** Long lab-state names in `Running <name>`, a translated or zoomed page at 200 %, the 901 to
   1279 px band, and the panel inside a 600 px high window.
8. **First save on a standard install** end to end, since N9 is not designed here: the panel must never
   show a folder refusal.
9. **Removed banners.** With `app.js:237-243` gone, a save problem is visible only in the chip. Confirm that
   is enough on every tab and at 390 px, where the chip may be ellipsised.
10. **Tools and tests that still name `#git-save-menu`, `#lab-progress` or `gitPushPending`** (section 8.3).
