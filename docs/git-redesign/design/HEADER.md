# Header control, chip, save and upload flow, first save

Design slice for [PROMPT.md](../PROMPT.md) sections 5.1, 5.2, 5.3, 5.6, 5.9, 5.10 and 6.5; boards G01, G10,
F02, G11, F04 (its Upload / Not now head only), F05, F06, F12, F13, F14, F16. Written against
`claude/git-save-load-redesign` at base release 1.30.60, and revised after the design review to follow the
lead's rulings: [DESIGN.md](../DESIGN.md) sections 3, 4, 5 and 7 and the answers in [REVIEW.md](../REVIEW.md).
Where this file and DESIGN.md disagree, DESIGN.md wins.

Paths are relative to `clab-backup-ui/` unless they start with `docs/` or `deploy/`. A citation reads
`path:line`. Not in this slice, and named where they touch it: the Load flow (Load designer), the drawers and
the removal of the Progress tab (drawer designer), the folder model, the folder chooser and every backend
decision (lead).

The first draft's requests to the backend (N1 to N9) are answered in DESIGN.md 3.8; section 10.2 lists
each answer and where it is. `app/git_progress.py` is cited at commit `11ed352`: slice S3 is rebuilding that
file, so its working copy moves.

## 0. Decisions in one screen

1. The header gets one flat group: chip, **Save**, **Load**, then *Lab actions*. The chip and the Load button
   are popover openers built on a new `initPanel()` in `shell.js`, a sibling of `initMenu()` that shares
   `closeMenus()`, so "one panel or menu open at a time", outside click and Escape come from the code that
   already does them.
2. The chip is static markup (a dot span and a text span): only `className` and `textContent` change on the
   4 s poll. The panel has a static title and a body rendered with a keyed markup setter that keeps focus and
   typed text.
3. One pure function, `saveChipState(lab, ctx, now)` in `status.js`, decides the state; it calls `loadState`
   for the load family. Order (DESIGN.md 7.1): Loading, Saving, Can't save after an attempt newer than the
   load, Partial, Running, Can't save, Upload failed, Waiting, Saved, Kept, Not saved. It was run against
   today's `status.js` (section 3.6).
4. **Save** posts the save at once with an empty `note`. The chip panel opens (F02), and when the save ends
   it shows the upload sentence (G11), the toast (F14) or the reason it stopped (6.5).
5. An upload is of the repository's waiting saves. The upload view names every one of them and where they
   go, and enables **Upload** only when the review answer has arrived. **Upload** in the panel and in the
   *What changed* drawer are the same handler and end in `gitReviewJob(job, {upload: true})`, which stays
   the only place in the static scripts that writes `{push: true, reviewed: true}` and always sends the
   `head` the person was shown.
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
      <span class="menu">
        <button type="button" class="button secondary panel-button save-chip" id="save-chip" aria-haspopup="dialog" aria-expanded="false" aria-controls="save-panel"><span class="save-dot none" id="save-chip-dot" aria-hidden="true"></span><span id="save-chip-text">Not saved yet</span><svg class="icon" width="16" height="16" aria-hidden="true"><use href="#i-chevron"></use></svg></button>
        <div class="save-panel" id="save-panel" data-panel role="dialog" aria-labelledby="save-panel-title" hidden>
          <h2 class="save-state" id="save-panel-title" tabindex="-1" data-panel-focus><span class="save-dot none" id="save-panel-dot" aria-hidden="true"></span><span id="save-panel-title-text"></span></h2>
          <div id="save-panel-body"></div>
        </div>
      </span>
      <button type="button" class="button primary" id="git-save-progress" aria-describedby="save-reason">Save</button>
    </span>
    <span class="menu">
      <button type="button" class="button secondary panel-button" id="load-button" aria-haspopup="dialog" aria-expanded="false" aria-controls="load-panel">Load</button>
      <div class="save-panel wide" id="load-panel" data-panel role="dialog" aria-label="Load a saved state" hidden><div id="load-panel-body"></div></div>
    </span>
  </div>
  <span class="menu"><!-- Lab actions: unchanged, index.html:76-103 --></span>
  <small class="caption" id="save-reason" hidden></small>
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
- **`#save-reason`** is the visible reason when Save is disabled for a cause the chip does not state
  (section 1.7). **`#save-live`** is the polite live region (section 2.6); like every live region of this
  slice it holds a sentence only, never a button.
- **Ids, not classes, for the single elements.** `#save-chip-text` and `#save-reason` are styled by id, so
  the class list stays the one of section 1.3.
- The Load button, `#load-panel` and its body belong to the Load designer. This slice fixes only their
  position, the wrapper, the `panel-button` class and the shared `save-panel` base.

Order in the DOM equals the visual order: chip, Save, Load, Lab actions (5.1).

### 1.3 Class names (replacing `rx-*` and `px-*`)

This table is the list of class names for the header, the panels and the drawers (DESIGN.md 7.5): no part
file uses a `save-` class that is not in it. Wherever `style.css` already has a class, the placeholder maps
to it and no new class is made. The chooser adds the names DRAWERS.md 8.2 lists under `folder-`.

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
| `rx-devs`, `rx-end`, `rx-off` | `save-devices`, `save-end` with `.ok .bad .now .warn`, `.off` | new (Load designer) |
| `dialog.rx-drawer` | `dialog.drawer.save-drawer` | reused `.drawer` (`style.css:1521-1556`) |
| `dialog.px-drawer`, `px-drawer-foot` | `dialog.drawer.save-settings`, `save-settings-foot` | drawer designer |
| (none) | `panel-button` | new; the opener class `initPanel()` looks for, the counterpart of `menu-button` (section 2.2). The one new name outside the `save-` family |
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
.save-pair .menu { min-width: 0; }                         /* lets the chip shrink at 390 px */
.save-chip { gap: 8px; font-weight: 500; min-width: 0; max-width: 16rem; }
#save-chip-text { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.save-chip .icon { flex: none; }
.panel-button[aria-expanded="true"]:not(.primary):not(.danger) { background: var(--surface-2); border-color: var(--muted); color: var(--ink); }
.save-dot { width: 8px; height: 8px; border-radius: 50%; flex: none; box-sizing: border-box; background: var(--ok); }
.save-dot.warn { background: var(--warn); }
.save-dot.bad { background: var(--danger); }
.save-dot.info { background: var(--accent); }
.save-dot.busy { background: var(--accent); box-shadow: 0 0 0 4px var(--accent-soft); animation: pill-pulse 1.6s ease-in-out infinite; }
.save-dot.none { background: transparent; border: 2px solid var(--muted); }   /* a border, not an inset shadow: it survives forced colours */
.lab-header:has(.pill.busy) .save-dot.busy { animation: none; }   /* one pulsing element per surface (ADDENDUM J5) */
#save-reason { flex-basis: 100%; margin: 0; }
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
.save-kv .button.ghost { margin-left: 4px; }               /* Change… and Details at the end of a line */
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

DESIGN.md 7.1, last paragraph. Each reason is visible text; `title` is not used for reasons (unreachable on
a disabled button).

| Control | Disabled when | Visible reason |
|---|---|---|
| Save | a load of this lab runs (row 1 of section 3.3) | the chip beside it says `Loading… 2 of 4`; `#save-reason` stays hidden |
| Save | a save of this lab runs (row 2), including the moment between the click and the answer (`gitSubmitting`, `git-progress.js:548`) | the chip says `Saving…` (set at once, section 4.1) |
| Save | a place request of this lab runs (the first save, the chooser's **Save here**) | `#save-reason`: `The place to save is being set.` A save that starts meanwhile would store the old connection (review F14) |
| Save | anything `operation_busy` counts is running in the manager (`app/lab_operations.py:57-74`): a lab operation, a backup, a save or a load of another lab, a design apply or its read-back, the removal of the retired telemetry lines | `#save-reason`: the sentence of `busy()`, then `Save is available when it finishes.` |
| Load (the header button) | only while a load of this lab runs (row 1) | the chip says `Loading…` |
| the red **Load** of a confirmation (LOAD.md) | a save of this lab runs (row 2) | `A save is running.` beside the button |

`busy()` (`app.js:20`) today knows backups, lab operations and Git saves. It is widened to mirror
`operation_busy` and to name what it found: it returns the sentence, or `''` when nothing runs, so its
callers keep using it as a truth value (review K7). The sentences: `<operation label> is running.`
(`operationLabel`, `status.js:38`), `A backup is running.`, `A save is running on <lab>.`, `A load is
running on <lab>.`, `A network design is being applied on <lab>.`, `The manager is checking devices after a
restart.` Without this the click on Save fails with the server's 409 (`idle`,
`app/git_progress.py:621-629`).

During a save the Load button stays enabled: the panel opens and the states can be browsed (PROMPT 5.2,
review D1). A lab without a save location never disables Save: it opens the first-save panel, as today's
button opens the first-save flow (`git-progress.js:184-185`).

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
| `review_pending` or `committed` (a commit waits on the VM: a save, a checkpoint, a lab state, a folder move) | the chip panel opens by itself with the upload view (G11) |
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

`saveFinished` sets `saveHeader.view` to the view of the job that ended, so the panel shows that job's
result even when the chip's state is another one: a checkpoint kept after a load opens the upload view while
the chip stays *Running*.

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
never a live region; its text changes every minute. No live region of the panel (`role="status"`,
`role="alert"`) wraps a button: each holds its sentence only (DESIGN.md 7.6, review A1).

## 3. The chip state function

[DESIGN.md](../DESIGN.md) section 7.1 is the ruling: the definitions, the order and the texts below are
copied from it, and where this section and 7.1 differ, 7.1 wins. `saveChipState` and `loadState` are the only
code that decides a chip state, a count or a name.

### 3.1 Name and signature

```js
// status.js, after progressSummary (status.js:165)
function saveChipState(lab, ctx = {}, now)
//   ctx               the /api/state document: git_jobs, restore_jobs, operations, design_jobs, jobs
//   ctx.refusal       {message, at}: the refusal of a save this page just sent (page memory, not /api/state); absent when none
//   ctx.states        optional: the rows of the saved-states list the page holds for this lab (names of lab states)
// → { key, dot, text, panel, detail, code, job, load, count, at, also, saveDisabled, loadDisabled }
function loadState(lab, ctx = {}, now)     // LOAD.md owns it; saveChipState calls it first
function relativeTimeShort(value, now)     // 'just now' | '21 min ago' | '2 h ago' | 'yesterday' | '3 days ago' | '12 Sep'
```

`key` is one of `loading saving cant partial running failed waiting saved kept none`. `dot` is the `save-dot`
modifier. `panel` names the view the chip opens. `load` is the answer of `loadState` while a load is active
or still describes what the devices run. `count` is the number of waiting saves whichever state wins. `also`
is the one state the winning state hides (section 3.4). `progressState()` stays as it is for its other
consumers (section 8.3).

The name after *Running* is not this slice's: `loadSourceName` (LOAD.md 5.2) derives it by the rule of
DESIGN.md 7.1, and no label is stored on the restore job (DESIGN.md 3.8, N2 refused).

### 3.2 Inputs and where the backend produces them

`app/git_progress.py` is cited at commit `11ed352`; slice S3 is rebuilding that file.

| Field | Produced at |
|---|---|
| `lab.id`, `lab.git_binding` (with `repository.push_url`, `repository.prefix`, `node_names`) | `public_lab` copies every lab key but the excluded ones (`app/main.py:155`); the binding is built at `app/git_progress.py:1168-1169` |
| `lab.git_status = {checked, ready, problem, code}` | new, DESIGN.md 3.8 N1: kept in memory per lab from the last helper `status` the manager ran for it (the settings route, a save, a place, an update), never fetched by the poll. `code` is one of `vm`, `account`, `busy`, `diverged`, `files`, `settings`, `other`, mapped in one table in `git_progress.py` |
| `state.git_jobs[]` | `app/main.py:224` through `public_job` (`app/git_progress.py:60-61`) with the keys of `PUBLIC_JOB` (`app/git_progress.py:40-42`): `id lab_id lab_name created finished status message backup_job_id commit pushed target checkpoint changed_files snapshot_path note review_before_push reviewed destination kind generation_id` |
| new public job fields | `captured` (the job read the devices itself; DESIGN.md 7.1), `note_auto` (3.2), `summary` (3.8 N4), `capture_kept` (3.5), `capture_whole` (3.9). `binding` stays private |
| git job `status` values | `queued` (`git_progress.py:1383`), `capturing` (`git_progress.py:847`), `exporting` (`git_progress.py:867`), `pushing` (`git_progress.py:772,884`), `capture_incomplete` (`git_progress.py:860`), `synced / push_pending / export_pending / unchanged / review_pending / committed` (`git_progress.py:920-924`), `interrupted / push_pending / export_pending / failed` on an error (`git_progress.py:895`), `dismissed` (`git_progress.py:1494`) |
| job `kind` | `design` for a design export (`app/git_progress.py:1432`); `state` for a lab state (DESIGN.md 2.9); absent for the lab's own saves |
| `state.restore_jobs[]` | `app/main.py:225` through `restore.public_job` (`app/restore.py:83-92`): `PUBLIC_JOB` (`app/restore.py:47-48`) plus `rechecking` and `server_time`; each target keeps `status`, `stage` and `timeline` (only keys starting with `_` are stripped) |
| restore `targets[].status` | vocabulary in `app/static/restore.js:23-33`; "replaced" is `applied verified applied_unverified verify_mismatch` (`restore.js:31`) |
| restore `source` | five keys, DESIGN.md 7.2: `type`, `commit`, `path`, `backup_job_id`, `repository` |
| `state.operations[]` (`action`, `status`, `finished`) | `app/main.py:227`; `deploy`, `redeploy` and `destroy` are the actions that end a load |
| `state.design_jobs[]` | `app/main.py:226` through `design_apply.public_job` (`app/design_apply.py:101-105`) |
| `state.jobs[]` (`id`, `source`, `progress_id`) | `app/main.py:222`; a load's automatic backup has `source: 'restore-pre'` and names its restore job in `progress_id` |

### 3.3 Decision table

Definitions (DESIGN.md 7.1):

- **Effective load**: a finished restore job of the lab with at least one device that was replaced
  (`verified`, `applied`, `applied_unverified`, `verify_mismatch`) or is unknown. A device is unknown only
  when its stage is `uncertain` or it still awaits its read-back; a device interrupted before it was changed
  is not. `L` is the newest effective load. A finished deploy, redeploy, destroy or design apply of the lab
  that is newer than `L` ends it.
- **Capture save**: a job of the lab that read the devices itself (public `captured`), not of kind `state`
  or `design`, finished as `synced`, `unchanged`, `committed`, `review_pending` or `push_pending`. `S` is the
  newest. A checkpoint or starting point made from an existing capture is not one.
- **Failed attempt**: the newest job of the lab ended `export_pending`, `capture_incomplete`, `failed`, or
  `interrupted` without a commit, or the page holds a refusal of a save it just sent. `A` is its time.
- **Waiting**: jobs of the lab with a commit that is not uploaded, in `committed`, `review_pending` or
  `interrupted`, whether or not the lab is connected now; lab states and folder moves count. A `push_pending`
  job is one of them and turns the row into *Upload failed*.

Order, first match wins:

| # | State (key) | Holds when | Dot | Chip text | `also` | Chip opens |
|---|---|---|---|---|---|---|
| 1 | Loading (`loading`) | a restore job of the lab is active (`statusRestoreActive`, `status.js:31`) | `busy` | `Loading… k of m` (`k` devices with a final word); `Checking devices…` during a restart read-back | | the Load panel's progress view (G04, LOAD.md) |
| 2 | Saving (`saving`) | a Git job of the lab is active (`STATUS_GIT_BUSY`, `status.js:13`) | `busy` | `Saving…`; `Uploading…` while it pushes; `Updating…` for an update | | F02 |
| 3 | Can't save (`cant`) | `A` is newer than `L` and than `S` | `bad` | `Can’t save` | the load of row 4 or 5 when `L` is newer than `S` | section 5.2 |
| 4 | Partial (`partial`) | `L` is newer than `S` and `L` did not succeed | `warn` | `Loaded n of m` (`n` verified devices only) | the highest of rows 6 to 8 that holds | G06 (LOAD.md) |
| 5 | Running (`running`) | `L` is newer than `S` and `L` succeeded | `info` | `Running <name>` | the same | G05 (LOAD.md) |
| 6 | Can't save (`cant`) | `A` is newer than `S`, or the lab's `git_status` is not ready | `bad` | `Can’t save` | Upload failed or waiting saves | section 5.2 |
| 7 | Upload failed (`failed`) | a waiting job is `push_pending` | `bad` | `Upload failed` | | F13 |
| 8 | Waiting (`waiting`) | one or more waiting jobs | `warn` | `1 save to upload`, `N saves to upload` (distinct commits) | | G11 |
| 9 | Saved (`saved`) | the newest capture save that changed something is uploaded | `ok` | `Saved <short time>` | | G10, or F06 while naming (section 4.8) |
| 10 | Kept (`kept`) | every save of the lab is dismissed | `none` | `Kept on this VM` | | G10 with `Uploaded: no, kept on the lab VM` |
| 11 | Not saved (`none`) | otherwise | `none` | `Not saved yet` | | F12 |

Save and Load: section 1.7. Three details the table leaves to this slice:

- *Shown save time* (row 9): the time of the newest capture save that is not `unchanged`, so the chip keeps
  `Saved 21 min ago` after a save that changed nothing, as F14 shows. When the manager holds only
  `unchanged` capture saves (the save that changed something was trimmed), the newest of those is shown: an
  `unchanged` save is by definition equal to an uploaded one (`app/git_progress.py:911-926`), and `Not saved
  yet` would be untrue.
- A job stored by an older release has no `captured`. It counts as a capture save when its target is
  `latest` (stored-data compatibility; every such save read the devices).
- A lab without a save location (never connected, or disconnected) in rows 9 to 11 opens the first-save view
  under the chip's title, because there is no place to show at rest. Rows 3 to 8 do not depend on the
  connection.

### 3.4 Precedence, with the reasons

DESIGN.md 3.8: the newest event wins between the load family and the save family, because PROMPT 5.4 step 5
makes the chip *Running* after a load without condition and step 9 ends it only "when the next save
completes".

- **Loading and Saving first.** They are what disables Save, and the server allows neither beside the other
  (`operation_busy`, `app/lab_operations.py:57-74`; `idle`, `app/git_progress.py:621-629`). Loading is first
  because it changes devices.
- **Can't save in front of a load only when the attempt is newer** (row 3). The person just pressed Save and
  it did not work; that is the newest event. The failed attempt ends nothing: the load stays reachable
  through `also`, with Undo.
- **Partial and Running before every other save state** (rows 4, 5). After a load the Save button saves what
  the devices run now, and the chip must say what that is. A waiting upload is older news; it is one line
  away.
- **Can't save before Upload failed and Waiting** (row 6). When the repository cannot be used, uploading and
  saving both fail; offering Upload first would lead into the failure.
- **Upload failed before Waiting.** One **Try again** uploads every waiting save of the repository
  (DESIGN.md 3.4), so the count is in the panel.
- **What ends *Running* and *Partial*.** Only a newer capture save, a newer effective load, or a finished
  deploy, redeploy, destroy or design apply. A checkpoint or a starting point made from an existing capture,
  a lab state, a design export, a folder move and a failed attempt read no device of this lab's own save and
  end nothing.
- **A load that changed nothing** (`failed`, `preflight_failed`, every device not changed) is not effective
  and sets no chip state: after load A succeeded and load B failed the chip still reads *Running A*. The lab
  banner and the Load panel report B (LOAD.md 5.3).
- **Waiting counts for a lab without a connection.** After Disconnect the save keeps waiting (DESIGN.md 3.1,
  7.6) and the chip says `1 save to upload`.
- **Kind `state` and `design`** count in Waiting and in Upload failed, never as "your latest save": they are
  not `S`, they never name *Saved*, and **Try again** on one retries that job (review K5).
- **`also`.** One object `{key, text, panel}`. Under rows 4 and 5 it is the highest of rows 6 to 8 that
  holds; under row 3 it is the load; under row 6 it is Upload failed or Waiting. The panel ends with one
  line for it and a ghost button **Show**, which switches the view (`Also: 1 save to upload.`). Under row 3
  the load takes `also`, so the view adds a second line from `count` when saves wait as well. No state is
  out of reach of the chip.

Texts beyond the nine of PROMPT 5.2, each because today's behaviour exists: `Uploading…` and `Updating…`
inside Saving, `Checking devices…` inside Loading (the restart read-back, `status.js:27-31`), and `kept`
(today's "Kept on this VM", `status.js:146-149`).

### 3.5 Reference implementation

Appended to `status.js` (slice S6); it uses `statusEpoch`, `statusJobTime`, `statusLabGitJobs`,
`statusRestoreActive`, `statusRestoreRechecking`, `statusDesignRechecking`, `STATUS_GIT_BUSY`,
`STATUS_RESTORE_BUSY`, `STATUS_OPERATION_BUSY`, `plural` and `savedVersionName`, all in that file.

`loadState` and `loadSourceName` belong to LOAD.md. They are printed here in the form the check of 3.6 ran
with, so that the chip function can be read and run as a whole: the part of `loadState` the chip reads is
`{key, job, name, loaded, total, done, at, rechecking}`. LOAD.md's function returns more (the rows, `undo`);
where its body differs, these fields keep the meaning they have here.

```js
const STATUS_SAVE_WAITING=['committed','review_pending','push_pending','interrupted'];
const STATUS_SAVE_STOPPED=['export_pending','capture_incomplete','failed'];
const STATUS_SAVE_CAPTURED=['synced','unchanged','committed','review_pending','push_pending'];
const STATUS_LOAD_REPLACED=['verified','applied','applied_unverified','verify_mismatch'];
const STATUS_LOAD_OPEN=['pending','ready','preflight','backing_up','applying','confirming','applied','interrupted'];
const STATUS_LOAD_ENDERS=['deploy','redeploy','destroy'];
function relativeTimeShort(value,now){
 const time=statusEpoch(value);if(!time)return '';
 const reference=now===undefined?Date.now():now,diff=Math.max(0,reference-time),minute=60000,hour=3600000,day=86400000;
 if(diff<45000)return 'just now';if(diff<hour)return Math.min(59,Math.max(1,Math.round(diff/minute)))+' min ago';
 if(diff<day)return Math.min(23,Math.max(1,Math.round(diff/hour)))+' h ago';if(diff<day*2)return 'yesterday';
 if(diff<day*7)return plural(Math.round(diff/day),'day')+' ago';
 return new Date(time).toLocaleDateString(undefined,{month:'short',day:'numeric'});
}
// The lab's Git jobs, newest first, without repository updates and without saves the person put aside.
function statusSaveJobs(lab,ctx){return statusLabGitJobs(lab,ctx?.git_jobs).filter(j=>j.status!=='dismissed');}
// S of DESIGN.md 7.1: the newest save that read the devices itself. A job stored before `captured` existed counts when it wrote `latest`.
function statusCaptureSaves(lab,ctx){
 return statusSaveJobs(lab,ctx).filter(j=>j.kind!=='state'&&j.kind!=='design'&&STATUS_SAVE_CAPTURED.includes(j.status)&&(j.captured===undefined?j.target==='latest':j.captured===true)).sort((a,b)=>statusJobTime(b)-statusJobTime(a));
}
function statusLoadUnknown(t){return t?.status==='uncertain'||t?.stage==='uncertain'||(t?.status==='interrupted'&&!!t.timeline&&!('settled' in t.timeline));}
function statusLoadEffective(job){return !!job&&!statusRestoreActive(job)&&(job.targets||[]).some(t=>STATUS_LOAD_REPLACED.includes(t.status)||statusLoadUnknown(t));}
// The name after "Running" (DESIGN.md 7.1). Derived, never stored, so a renamed save shows its current name.
function loadSourceName(source,ctx={},lab,now,depth=0){
 const s=source||{},path=String(s.path||s.folder||'').replace(/\/+$/,'');
 if(s.type==='backup'){
  const backup=(ctx.jobs||[]).find(j=>j.id===s.backup_job_id),before=backup&&backup.source==='restore-pre'?(ctx.restore_jobs||[]).find(j=>j.id===backup.progress_id):null;
  if(!before||depth>4){const when=relativeTimeShort(backup?.finished||backup?.created,now);return when?'a backup from '+when:'a backup';}
  const inner=before.source||{},innerBackup=inner.type==='backup'?(ctx.jobs||[]).find(j=>j.id===inner.backup_job_id):null,undone=innerBackup&&innerBackup.source==='restore-pre'?(ctx.restore_jobs||[]).find(j=>j.id===innerBackup.progress_id):null;
  if(undone)return loadSourceName(undone.source,ctx,lab,now,depth+1);   // the undo of an undo of X reads "X"
  return 'the configuration from before '+loadSourceName(inner,ctx,lab,now,depth+1);
 }
 const prefix=String(lab?.git_binding?.repository?.prefix||''),own=p=>(prefix?prefix+'/':'')+p,row=(ctx.states||[]).find(r=>r.path===path&&(!s.commit||!r.commit||r.commit===s.commit));
 if(lab?.git_binding&&path===own('latest')){
  const save=(ctx.git_jobs||[]).find(j=>j.lab_id===lab.id&&j.commit&&j.commit===s.commit&&j.kind!=='state'&&j.kind!=='design');
  if(save)return save.note||'your latest save';
  const when=relativeTimeShort(row?.saved_at,now);return when?'an earlier save, '+when:'an earlier save';
 }
 if(lab?.git_binding&&path===own('baseline'))return 'your starting point';
 if(lab?.git_binding&&path.startsWith(own('checkpoints/')))return path.slice(own('checkpoints/').length)||'a checkpoint';
 if(row&&row.name)return String(row.name);
 return savedVersionName(path.replace(/(^|\/)latest$/,''))||'a saved state';
}
// LOAD.md owns loadState and its full return (rows, undo). This is the part the chip reads: the active load, or the newest
// effective load L while it is newer than the newest capture save S and no deploy, redeploy, destroy or design apply ended it.
function loadState(lab,ctx={},now){
 const none={key:'',job:null,name:'',loaded:0,total:0,done:0,at:0};if(!lab)return none;
 const mine=j=>!!j&&j.lab_id===lab.id,restores=(ctx.restore_jobs||[]).filter(mine),active=restores.find(statusRestoreActive);
 if(active){const targets=active.targets||[];return {...none,key:'loading',job:active,total:targets.length,done:targets.filter(t=>!STATUS_LOAD_OPEN.includes(t.status)).length,rechecking:statusRestoreRechecking(active)};}
 const job=restores.filter(statusLoadEffective).sort((a,b)=>statusJobTime(b)-statusJobTime(a))[0];if(!job)return none;
 const at=statusJobTime(job),save=statusCaptureSaves(lab,ctx)[0];if(save&&statusJobTime(save)>=at)return none;
 const ended=(ctx.operations||[]).some(j=>mine(j)&&STATUS_LOAD_ENDERS.includes(j.action)&&!STATUS_OPERATION_BUSY.includes(j.status)&&statusJobTime(j)>at)
  ||(ctx.design_jobs||[]).some(j=>mine(j)&&!STATUS_RESTORE_BUSY.includes(j.status)&&!statusDesignRechecking(j)&&statusJobTime(j)>at);
 if(ended)return none;
 const targets=job.targets||[],loaded=targets.filter(t=>t.status==='verified').length;
 return {...none,key:job.status==='succeeded'?'running':'partial',job,name:loadSourceName(job.source,ctx,lab,now),loaded,total:targets.length,at};
}
// The chip (DESIGN.md 7.1). ctx is the /api/state document plus ctx.refusal = {message, at}, the refusal of a save this page just sent.
function saveChipState(lab,ctx={},now){
 const base={detail:'',job:null,load:null,count:0,at:'',also:null,saveDisabled:false,loadDisabled:false};
 if(!lab)return {...base,key:'none',dot:'none',text:'Not saved yet',panel:'first'};
 const load=loadState(lab,ctx,now);
 if(load.key==='loading')return {...base,key:'loading',dot:'busy',text:load.rechecking?'Checking devices…':load.total?`Loading… ${load.done} of ${load.total}`:'Loading…',panel:'loading',load,count:load.done,saveDisabled:true,loadDisabled:true};
 const active=(ctx.git_jobs||[]).find(j=>j.lab_id===lab.id&&STATUS_GIT_BUSY.includes(j.status));
 if(active)return {...base,key:'saving',dot:'busy',text:active.target==='update'?'Updating…':active.status==='pushing'?'Uploading…':'Saving…',panel:'saving',job:active,saveDisabled:true};
 const bound=!!lab.git_binding,jobs=statusSaveJobs(lab,ctx),captures=statusCaptureSaves(lab,ctx),saveAt=captures[0]?statusJobTime(captures[0]):0;
 const newest=jobs[0]||null,stopped=newest&&(STATUS_SAVE_STOPPED.includes(newest.status)||(newest.status==='interrupted'&&!newest.commit))?newest:null;
 const refusal=ctx.refusal&&ctx.refusal.message?ctx.refusal:null,failedAt=Math.max(stopped?statusJobTime(stopped):0,refusal?statusEpoch(refusal.at)||Infinity:0);
 const status=bound?lab.git_status:null,unready=!!status&&status.checked!==false&&status.ready===false;
 const cant=()=>({key:'cant',dot:'bad',text:'Can’t save',panel:'cant',job:stopped,detail:String(refusal?.message||(failedAt>saveAt&&stopped?stopped.message:'')||status?.problem||''),code:refusal||(failedAt>saveAt&&stopped)?'':String(status?.code||'other')});
 const waiting=jobs.filter(j=>j.commit&&!j.pushed&&STATUS_SAVE_WAITING.includes(j.status)),count=new Set(waiting.map(j=>j.commit)).size,failed=waiting.find(j=>j.status==='push_pending');
 const states=[],live=load.key==='running'||load.key==='partial';
 if(failedAt>saveAt&&(!live||failedAt>load.at))states.push(cant());                                              // rows 3 and 6
 if(live)states.push(load.key==='running'?{key:'running',dot:'info',text:'Running '+load.name,panel:'running',load}:{key:'partial',dot:'warn',text:`Loaded ${load.loaded} of ${load.total}`,panel:'partial',load,count:load.loaded});   // rows 4, 5
 if(!states.some(s=>s.key==='cant')&&(failedAt>saveAt||unready))states.push(cant());                             // row 6
 if(failed)states.push({key:'failed',dot:'bad',text:'Upload failed',panel:'failed',job:failed,count});          // row 7
 else if(count)states.push({key:'waiting',dot:'warn',text:plural(count,'save')+' to upload',panel:'upload',job:waiting[0],count});   // row 8
 const shown=captures.find(j=>j.status!=='unchanged')||captures[0]||null;
 if(shown&&(shown.status==='synced'||shown.status==='unchanged')){const at=shown.finished||shown.created||'',when=relativeTimeShort(at,now);states.push({key:'saved',dot:'ok',text:when?'Saved '+when:'Saved',panel:bound?'rest':'first',job:shown,at});}   // row 9
 else{const all=statusLabGitJobs(lab,ctx.git_jobs).filter(j=>j.kind!=='state'&&j.kind!=='design'&&j.target!=='move'),kept=all.length&&all.every(j=>j.status==='dismissed')?all[0]:null;
  states.push(kept?{key:'kept',dot:'none',text:'Kept on this VM',panel:bound?'rest':'first',job:kept,at:kept.finished||kept.created||''}:{key:'none',dot:'none',text:'Not saved yet',panel:'first'});}   // rows 10, 11
 const top=states[0],rest=states.slice(1),pick=top.key==='cant'?(live?rest.find(s=>s.key==='running'||s.key==='partial'):rest.find(s=>['failed','waiting'].includes(s.key))):live?rest.find(s=>['cant','failed','waiting'].includes(s.key)):null;
 return {...base,load:live?load:null,count,...top,also:pick?{key:pick.key,text:pick.text,panel:pick.panel}:null};
}
```

Notes on the code:

- "Still awaits its read-back" is read from the public target: `interrupted` with a `timeline` that has no
  `settled` entry. A device interrupted before it was changed is settled as `failed` at start-up
  (`app/restore.py:279-281`), and a job stored before stages existed has no `timeline` and is not counted.
- A finished deploy, redeploy, destroy or design apply ends a load whatever its own outcome: a failed
  redeploy may have restarted devices, and the chip must not claim more than is known.
- A refusal without a time is the newest event.
- `code` is empty when a failed attempt or a refusal is the cause; section 5.2 then reads the job.

### 3.6 What was checked

A throwaway Node script (not in the repository) loaded today's `app/static/status.js` and the code block of
3.5, extracted from this document, into one `vm` context, ran 41 cases with one or more `assert` each, and
printed them. `node --check` on the extracted block: exit status 0. `node run.js`: exit status 0. Run on
2026-10-04 at commit `11ed352`. The six sequences the lead named are the first rows (3 and 6 in more than
one form). Columns: key, dot, chip text, panel, `also`, waiting count (for *Loading* and *Partial* the last
column is the device count). The notes in parentheses were added by hand.

```
1 loadA ok, loadB fails       running | info | Running ospf-up | running |  | 0
2 waiting, then load ok       running | info | Running ospf-up | running | waiting:1 save to upload | 1
3 load ok, then save fails    cant | bad | Can’t save | cant | running:Running ospf-up | 0
3b load ok, then refusal      cant | bad | Can’t save | cant | running:Running ospf-up | 0
4 checkpoint from capture     running | info | Running ospf-up | running | waiting:1 save to upload | 1
5 disconnect, save waiting    waiting | warn | 1 save to upload | upload |  | 1
6a state job waiting          waiting | warn | 1 save to upload | upload |  | 1
6b state job uploaded         saved | ok | Saved 1 h ago | rest |  | 0        (the lab's own save of an hour ago, not the state)
6c only a state job           none | none | Not saved yet | first |  | 0
row1 loading                  loading | busy | Loading… 2 of 4 | loading |  | 2
row1 read-back                loading | busy | Checking devices… | loading |  | 0
row2 saving                   saving | busy | Saving… | saving |  | 0
row2 uploading                saving | busy | Uploading… | saving |  | 0
row2 updating                 saving | busy | Updating… | saving |  | 0
row4 partial, verified only   partial | warn | Loaded 3 of 4 | partial | failed:Upload failed | 3   (the fourth is applied_unverified)
row4 nothing verified         partial | warn | Loaded 0 of 2 | partial |  | 0        (one uncertain, one failed)
interrupted before change     saved | ok | Saved 1 h ago | rest |  | 0
row5 status not ready         running | info | Running ospf-up | running | cant:Can’t save | 0
row5 ended by a save          saved | ok | Saved 1 h ago | rest |  | 0        (an unchanged save; the earlier time is kept)
row5 ended by redeploy        saved | ok | Saved 1 h ago | rest |  | 0
row5 ended by design apply    saved | ok | Saved 1 h ago | rest |  | 0
row5 older deploy ends nothing running | info | Running ospf-up | running |  | 0
row5 failed save older than L running | info | Running ospf-up | running | cant:Can’t save | 0
row6 failed attempt           cant | bad | Can’t save | cant | waiting:1 save to upload | 1
row6 status not ready         cant | bad | Can’t save | cant |  | 0
row7 upload failed            failed | bad | Upload failed | failed |  | 2
row8 two jobs one commit      waiting | warn | 2 saves to upload | upload |  | 2      (three waiting jobs, two commits; a dismissed one ignored)
row8 a folder move waits      waiting | warn | 1 save to upload | upload |  | 1
row9 saved                    saved | ok | Saved 21 min ago | rest |  | 0
row9 old job without captured saved | ok | Saved 21 min ago | rest |  | 0
row10 kept                    kept | none | Kept on this VM | rest |  | 0
row11 nothing                 none | none | Not saved yet | first |  | 0
row11 unbound                 none | none | Not saved yet | first |  | 0
another lab is ignored        none | none | Not saved yet | first |  | 0
name: own latest, its save    running | info | Running ospf fixed | running |  | 0
name: own latest, older commit running | info | Running an earlier save, 2 days ago | running |  | 0
name: checkpoint              running | info | Running before-bgp | running |  | 0
name: starting point          running | info | Running your starting point | running |  | 0
name: from the states list    running | info | Running Start | running |  | 0
name: undo of X               running | info | Running the configuration from before Start | running |  | 0
name: undo of the undo        running | info | Running Start | running |  | 0
just now / 59 min ago / 2 h ago / yesterday / 3 days ago / []
```

This is a smoke run of the design, not a test suite and not browser evidence. The tests to write are in
section 8.4.

### 3.7 The home card

`homeSavedLine()` (`app/static/home.js:7-14`) switches from `progressState` to
`saveChipState(lab, state).text`. The card then says exactly what the chip says, including *Can't save* from
`lab.git_status`, which is in `/api/state`. The card's attention rule (ADDENDUM J3, "progress attention label
when `progressState.key` ∈ {attention, failed, interrupted, local}") becomes "`saveChipState.key` ∈ {`cant`,
`failed`, `partial`, `waiting`}".

## 4. The save flow as the person sees it

`host` below is `statusHost(lab.git_binding.repository.push_url) || 'the online repository'`
(`status.js:44,141`). `N` devices is `lab.git_binding.node_names.length`.

### 4.1 Step 1: Save starts at once (F02)

Today Save opens the label dialog first (`gitSaveProgress` → `gitLabelDialog`, `git-progress.js:578-583,
566-577`) and the route refuses an empty note (`app/git_progress.py:1355`). By D2 and DESIGN.md 3.2 the note
may be empty and the manager names the save.

- **Action:** click `#git-save-progress`. Handler: `opTask(null, gitSaveProgress)` as today
  (`git-progress.js:784`). New body of `gitSaveProgress(id = activeId)`: a lab without a save location → open
  the chip panel (first-save view, section 6); otherwise `gitSubmitSave(id, {target: 'latest', push: true,
  note: ''}, undefined, {quiet: true})` and open the chip panel (`saveOpenPanel('status')`).
- **Request:** `POST /api/labs/{id}/git/save` with
  `{request_id, target: 'latest', checkpoint: '', push: true, note: '', backup_job_id: '', replace_baseline:
  false, expected_baseline: '', allow_removed: true}` (`gitSavePayload`, `git-progress.js:71`; model at
  `app/git_progress.py:962-972`). `allow_removed` is always true (DESIGN.md 3.3): the selection is explicit,
  the removal is in the sentence before anything is uploaded, and the commit stays on the VM until Upload.
  `push: true` does not upload: the server turns it into `review_before_push` and `want_push: false`
  (`app/git_progress.py:1376-1386`).
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
  can keep working.`; `exporting` → `Saving to the lab VM’s repository. You can keep working.` (for a folder
  move: `Moving the saved files. You can keep working.`); `pushing` → `Uploading to <host>. You can keep
  working.`
- The toast `Saving progress…` (`git-progress.js:558`) goes: the panel says it.
- The request-reuse logic (`gitReusableRequest`, `git-progress.js:538-543,554`) stays. An empty note makes
  two consecutive saves identical requests; that is the case it was written for (it replays only while the
  first save is not known as finished).

**The name (DESIGN.md 3.2).** After the capture and before the first publish the manager names the save
from what changed and answers with `note` and `note_auto: true` in the public job. The page never builds
the name itself.

**Refusals of the request** (`gitSubmitSave` throws): the message becomes `saveHeader.refusal = {lab,
message, at}`, which is the *failed attempt* of row 3 or 6: the chip turns to *Can't save* and the panel
shows the view of section 5.2. It is cleared by the next accepted save and when the panel closes. What can
still arrive: the lab is busy (`app/git_progress.py:625-628`; rare, because Save is disabled while
`busy()`), a place request of the lab is running (`refuse_while_rebinding`), `Reconnect the original VM
before saving progress.` (`app/git_progress.py:1365`), and any helper error. The refusal for another lab's
unreviewed save (`app/git_progress.py:283-292,659-662`) is gone (DESIGN.md section 1 and 3.4), and a device
of the selection that left the lab is dropped by the save instead of refusing it (DESIGN.md 3.3; today
`app/git_progress.py:1367`). Today these go to the lab banner through `showActionError`
(`operations.js:26`, `shell.js:192-197`); for the save flow the chip panel replaces the banner.

### 4.2 Step 2: nothing changed (F14)

How the backend reports it today: the helper answers `status: 'unchanged'` with `commit = HEAD`
(`app/host_git.py:644-654`); `finish()` gives the job status `unchanged` only when the manager knows that
exact commit as uploaded, with the message `Nothing changed since the last save, which was uploaded.`
(`app/git_progress.py:911-926`). When HEAD was never uploaded, the same helper answer ends as
`review_pending` with empty `changed_files` (`app/git_progress.py:923,928-929`).

- `unchanged`: toast `Nothing changed since your last save.`, the panel closes, the chip keeps its time
  (section 3.3). It is a capture save, so it ends *Running* and *Partial*: the devices equal the latest
  save.
- `review_pending` with nothing changed (an earlier save still waits): chip *Waiting*, panel as in 4.3 with
  the sentence `Nothing changed since your last save, which is not uploaded yet.` The count stays the same
  because both jobs hold the same commit (the function counts distinct commits).

### 4.3 Step 3: the upload view (G11)

Chip *Waiting*; the panel opens by itself (section 2.5). An upload is of **the repository's waiting saves**
(DESIGN.md 3.4): Git pushes the checkout's newest commit, and that push carries every earlier one the
online copy lacks. The view therefore names everything the click sends before the click is possible.

```html
<!-- title: dot warn, "Not uploaded yet" -->
<p class="save-sub" id="save-changes">2 devices changed since your last save: ceos and xrv9k. 19 lines added, 1 removed. This upload also sends 2 other saves: Start (bgp), ospf fixed (ospf-lab).</p>
<p class="save-kv" id="save-to"><span>To:</span> CLAB-MNGR-DEV-LLM › bgp</p>
<p class="save-note" id="save-checking" role="status" hidden>Checking what this upload sends…</p>
<div class="save-row">
  <button type="button" class="button primary" id="save-upload" data-save-action="upload" aria-describedby="save-checking">Upload</button>
  <button type="button" class="button ghost small" id="save-not-now" data-save-action="not-now">Not now</button>
  <button type="button" class="button ghost small" id="save-see" data-save-action="changes">See changes</button>
  <button type="button" class="button ghost small" id="save-details" data-save-action="details">Details</button>
</div>
<p class="save-note">Saved files can contain passwords or keys.</p>
<p class="form-error" role="alert" id="save-panel-error"></p>
```

The view's save is `state.job` of the chip function: the lab's newest waiting save.

**The sentence, at once.** The first part comes from the job's stored `summary` (DESIGN.md 3.8, N4:
`{devices: [labels], added, removed, topology, map, first, removed_devices}`, counts and labels only,
written by the worker after the commit), so it needs no request and is on screen when the panel opens. One
pure function in `status.js` builds the text, `saveChangeSentence(summary, also)`:

| Summary | Sentence |
|---|---|
| devices `[ceos, xrv9k]`, +19 −1 | `2 devices changed since your last save: ceos and xrv9k. 19 lines added, 1 removed.` |
| one device | `1 device changed since your last save: ceos. 3 lines added, 0 removed.` |
| more than four devices | `6 devices changed since your last save: ceos, r1, r2 and 3 more. …` (all of them are in See changes) |
| devices and topology | `… 19 lines added, 1 removed. The topology changed.` |
| devices, topology and map | `… The topology and the map changed.` |
| only the map | `The map changed since your last save.` |
| only the topology | `The topology changed since your last save.` |
| `removed_devices: [r9]` | `… r9 is no longer saved; its file was removed.` (`r8 and r9 are no longer saved; their files were removed.`) |
| `first: true` | `This is the first save here: 4 devices, the topology and the map.` |
| nothing | `Nothing changed since your last save, which is not uploaded yet.` |
| no `summary` (a save of an older release, a design export, a summary that could not be read) | `This save is on the lab VM and not uploaded yet.` |

Each device is counted once; its restore artifact is never a second change, because the manager computes
the summary from the `role` and `node` of each file (N4), not the page from file names.

Three kinds of waiting save have their own first sentence, chosen by the job, not by the summary:

| Job | Sentence |
|---|---|
| `target: 'checkpoint'` | `Checkpoint ospf-up kept. It is not uploaded yet.` |
| `target: 'move'` (a folder move's commit; DESIGN.md 2.6, 3.4) | `<lab>’s saved files moved to <folder>.` |
| `kind: 'state'` | the summary's sentence, as for any save (DESIGN.md 2.9) |

A folder move never uploads by itself (review F2): its commit waits like a save, counts in the chip and
goes up with the next Upload, named like every other save.

**Everything the upload carries.** `gitReviewData(job)` (section 4.5) fetches the review. Its `also_sends`
has one row for every other un-uploaded save of the repository: older and newer, this lab's and other
labs', wherever those labs save now, the saves kept with *Keep snapshot only*, and the commits the manager
no longer holds, which arrive named by their subject (DESIGN.md 3.4, H6). `saveChangeSentence(summary,
also)` appends:

- `This upload also sends 1 other save: <name> (<lab>).`
- `This upload also sends 3 other saves: <name> (<lab>), <name> (<lab>) and <name> (<lab>).`; beyond three,
  `…, <name> (<lab>) and 4 more.` Every one is listed with its files in See changes.
- A row without a manager save is named by its subject in quotes and has no lab: `"Save bgp: ceos changed"`.

**`To:`.** `<repository> › <folder>` from the job's own frozen `destination` (`job_destination`,
`app/git_progress.py:82-89`: `repository` and `path`), not from the lab's connection, so a save that waits
after a folder change or a disconnect names where it really goes (review F5). `<folder>` is `path` without
its saved-state part (`latest`, `baseline`, `checkpoints/<name>`); the top level reads `top level`.

**Upload is enabled only when the review answer has arrived.** Until then the button is disabled,
`#save-checking` is shown (`Checking what this upload sends…`) and is the button's description; **Not now**,
**See changes** and **Details** work. The click on Upload is the statement that the person was shown what
goes up, so it cannot come before the list of other saves. When the answer arrives the sentence gains its
second part, `#save-checking` is hidden and Upload is enabled; the keyed rebuild keeps focus (section 2.4).

| Review answer | View |
|---|---|
| not yet | Upload disabled, `Checking what this upload sends…` |
| arrived, `upload_job` set | Upload enabled |
| the request failed | `What this upload sends could not be read from the lab VM.` with **Try again** (`review-again`) in place of Upload; **Details** |
| arrived, no `upload_job` (no manager save is at the checkout's newest commit; DESIGN.md 3.4) | the *Can't save* row for someone working in the repository (section 5.2), in place of Upload |

**Details** opens today's save window (`gitShowJob(job.id)`, section 4.6), which holds *Keep snapshot only*:
a waiting save can be put aside without uploading it (review F2).

A lab without a save location shows the same view for its waiting save (after Disconnect, DESIGN.md 7.6);
only the foot differs (section 5.1).

### 4.4 Step 4: See changes (F04, head only)

**See changes** is `gitReviewJob(job)` without `upload`: it closes the panel and opens the *What changed*
drawer, `saveDrawerOpen('changes', {job, opener: $('save-chip')})` (`dialog#save-drawer.drawer.save-drawer`;
its body is the drawer designer's, built from the same review data with `gitFilesDiffMarkup`,
`git-progress.js:134-137`, one section per save of `also_sends`). The head this slice fixes:

```html
<div class="drawer-head"><div class="dialog-head"><h2 id="save-drawer-title">What changed</h2>
<button type="button" class="icon-button close" aria-label="Close"><svg class="icon" width="16" height="16" aria-hidden="true"><use href="#i-close"></use></svg></button></div>
<p class="drawer-meta">ceos and xrv9k · 19 lines added, 1 removed · not uploaded yet · to CLAB-MNGR-DEV-LLM › bgp</p>
<div class="save-row"><button type="button" class="button primary" data-save-action="upload">Upload</button><button type="button" class="button ghost small" data-save-action="not-now">Not now</button></div>
<p class="form-error" role="alert"></p></div>
```

The two buttons carry the same `data-save-action` values as the panel's and are served by the same function,
`saveAction(action, job, origin)`, through one delegated listener per container (`#save-panel`,
`#save-drawer`). Upload in the head follows the same rule: disabled until the review answer has arrived.
When the save is already uploaded (the drawer opened later from All versions) the row is not rendered and
the meta line ends `· uploaded`.

### 4.5 Step 5: Upload, through `gitReviewData` and `gitReviewJob`

Today `gitReviewJob(job)` fetches the compare answer, opens the *Review before uploading* dialog and its
**Upload these changes** button posts `{push: true, reviewed: true}` to `/api/git/jobs/{id}/retry`
(`git-progress.js:654-672`; the literal is on line 672). The server refuses an upload of an unreviewed save
without that flag (`app/git_progress.py:1464-1468`). Other callers: `gitSavesAction`
(`git-progress.js:419`), `gitRenderJob` (`git-progress.js:643`), `gitStartWatch` (`git-progress.js:692`),
and the comment contract in `network-design.js` (`operations.js:873`, `network-design.js:2122-2139`).

New shape (DESIGN.md 7.3), both in `git-progress.js`, built by the builder of `save-header.js` in the first
wave together with `gitSubmitSave` and `gitStartWatch`:

```js
const gitReviews={key:'',answers:new Map()};   // job id → the review of the current set of waiting saves
// The set of waiting saves in /api/state, of every lab: a save made anywhere changes what an upload carries.
function gitWaitingKey(){return (state.git_jobs||[]).filter(j=>j.commit&&!j.pushed).map(j=>j.id+':'+j.commit+':'+j.status).sort().join('|');}
// What a save changed and what an upload of its repository would send. Cached until the set of waiting saves changes.
async function gitReviewData(job,options={}){
 const key=gitWaitingKey();if(gitReviews.key!==key){gitReviews.key=key;gitReviews.answers.clear();}
 if(!options.fresh&&gitReviews.answers.has(job.id))return gitReviews.answers.get(job.id);
 const result=await json('/labs/'+encodeURIComponent(job.lab_id)+'/git/compare','POST',{job_id:job.id});
 const review={files:result.files||[],summary:result.summary||job.summary||null,head:result.head||'',upload_job:result.upload_job||'',also_sends:result.also_sends||[]};
 gitReviews.answers.set(job.id,review);return review;
}
// Without options.upload: opens the What changed drawer for the save. With it: uploads what the review of this save showed.
// This function is the only sender of {push:true, reviewed:true}; the body always carries the HEAD the person was shown.
async function gitReviewJob(job,options={}){
 if(!options.upload){if(typeof saveDrawerOpen==='function')saveDrawerOpen('changes',{job,opener:options.opener});return null;}
 const review=gitReviews.key===gitWaitingKey()?gitReviews.answers.get(job.id):null;
 if(!review||!review.head||!review.upload_job)throw new Error('See what this upload sends before uploading.');
 try{
  const next=await json('/git/jobs/'+encodeURIComponent(review.upload_job)+'/retry','POST',{push:true,reviewed:true,head:review.head});
  gitRememberJob(next);gitStartWatch(next,{quiet:true});await refresh();return next;
 }catch(error){
  if(error.status===409){gitReviews.answers.clear();try{await gitReviewData(job,{fresh:true});}catch{}if(typeof renderSaveHeader==='function')renderSaveHeader();if(typeof saveDrawerRender==='function')saveDrawerRender();}
  throw error;
 }
}
```

- **One request, to the save at the checkout's newest commit.** `upload_job` is the id of the manager's save
  whose commit is `head`; it may be another lab's save or a newer save of this lab. The manager asks the
  helper's `status` and pushes only when the checkout's HEAD is still `head` and is that save's commit; a
  successful push marks every carried save reviewed and uploaded (DESIGN.md 3.4).
- **409** (`Another save was made in this repository. Look at the changes again.`; `api()` puts the status
  on the error, `app.js:24-31`): the cache is emptied, the review is fetched again, the panel and the drawer
  render it, and the server's sentence is shown in the `.form-error` of the view that sent the click. The
  person presses Upload again after reading the new list. Nothing was uploaded.
- **No upload without the answer.** The function refuses when it holds no review of this save for the
  current set of waiting saves, so a click that arrives between a poll that changed the set and the next
  answer sends nothing. There is no page flag that says "shown": the views render the sentence and enable
  Upload from the same cache entry in the same render.
- **A reviewed save that failed to upload** used to retry with `{push: true}` (`git-progress.js:645`). It
  now goes the same way as every upload, with `head`, because the set of saves under it may have changed
  since.
- **Both Upload buttons and Try again:** `saveAction('upload', job, origin)` →
  `opTask(null, () => gitReviewJob(job, {upload: true}))`, with the `.form-error` holder of the panel or of
  the drawer head.
- **After the click:** the job goes `queued` → `pushing`; chip `Uploading…`; the panel shows the saving view
  with `Uploading to <host>. You can keep working.`; the drawer, when it was the origin, closes at once.
- **Success** (`synced`): toast `Uploaded to <host>.` (F05), the panel closes, focus to the chip when it was
  inside the panel. The chip is whatever the table then says (*Saved*, or *Running* after a load).
- **Failure** (`push_pending`, `app/git_progress.py:895,921`): chip *Upload failed*, panel F13
  (section 4.6).

The job window keeps its **Review changes** and **Review and upload…** buttons (`git-progress.js:639`); both
call `gitReviewJob(job)` and so open the *What changed* drawer. `network-design.js` reaches the same drawer
for a design export through the same call. `#git-diff-dialog` remains for `gitCompareVersion`
(`git-progress.js:743-748`) until the drawer designer replaces that too.

### 4.6 Step 5, failure (F13) and Details

```html
<!-- title: dot bad, "Upload failed" -->
<p class="save-sub" id="save-changes">Your save is safe on the lab VM, but github.com could not be reached. This upload sends 2 saves: ospf fixed (bgp), Start (bgp).</p>
<p class="save-kv" id="save-to"><span>To:</span> CLAB-MNGR-DEV-LLM › bgp</p>
<p class="save-note" id="save-checking" role="status" hidden>Checking what this upload sends…</p>
<div class="save-row">
  <button type="button" class="button primary" id="save-retry" data-save-action="upload" aria-describedby="save-checking">Try again</button>
  <button type="button" class="button ghost small" id="save-see" data-save-action="changes">See changes</button>
  <button type="button" class="button ghost small" id="save-details" data-save-action="details">Details</button>
</div>
<p class="form-error" role="alert" id="save-panel-error"></p>
```

- The sentence ends `…but <host> could not be reached.` only when the job message is a connectivity failure
  (`The remote branch is unavailable. Check connectivity…`, `app/host_git.py:416`; `Git command timed out`,
  `app/host_git.py:246-249`). For every other cause it ends `…but it could not be uploaded to <host>.`
  (today's sentence, `status.js:156`). When `lab.git_status` is not ready the chip is *Can't save* (row 6)
  and this view is reached through its `also` line. Saying "could not be reached" for a missing login would
  be untrue.
- **Try again** is the same `upload` action with the same rule: it needs the review answer, which this view
  fetches like the upload view, and it is disabled until the answer has arrived.
- **Details** opens today's save window: `gitShowJob(job.id)` (`git-progress.js:626-632`), the
  `#git-job-dialog` with the message, destination, commit, **View configuration backup**, the retry buttons
  and **Keep snapshot only** (`git-progress.js:633-647`). It is opened with the chip as opener so focus
  returns there.

### 4.7 Step 6: Not now

Closes the panel (or the drawer). No request and no toast (DESIGN.md 7.6): the chip says `1 save to upload`.
The job stays `review_pending`. This is what today's **Not now — keep it on the VM** does
(`git-progress.js:671`), without its toast. The save is uploaded later from the chip: chip → **Upload**.

Today's *Save on this VM only* (`gitSaveOptions('local')`, `git-progress.js:585-610`) sent `push: false`,
which ends as `committed` instead of `review_pending` (`app/git_progress.py:924`). Both are *Waiting* and
both go through the review before an upload, so the new flow needs only the one path.

**Keep snapshot only** (dismiss, `git-progress.js:698-701`, `app/git_progress.py:1489-1495`) stays in the
Details window, one click from the upload view. It is not a button of the panel.

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
  to a space, trimmed, at most 120 characters.
- **Route (DESIGN.md 3.2, N6):** `POST /api/git/jobs/{id}/name {note}` → the public job. It changes only the
  name the manager shows, never a commit, and is not held by `idle()`, so a rename works while a backup
  runs. An empty name returns to the automatic one: the page posts `{note: ''}` and shows the answer's
  `note`.
- While the request is in flight the field is read-only; on success `#save-live` says `Renamed.`; on failure
  the message is in `#save-panel-error` and the field keeps what was typed (`data-dirty` stays).

**Keep as a checkpoint** (D6, DESIGN.md 3.5).

- **Request:** `POST /api/labs/{id}/git/save` with `{request_id, target: 'checkpoint', checkpoint: '',
  backup_job_id: job.backup_job_id, push: true, note: job.note, allow_removed: true}`. The route takes a
  finished capture this way and reads no device (`app/git_progress.py:1368-1373`, `execute` at
  `git_progress.py:843-858`). The empty `checkpoint` asks the manager to derive a free name from the save's
  name (`ceos-and-xrv9k-changed`, `-2` when taken; N7); the job answers with the name used.
- The checkpoint is a new commit, so it goes through the same flow: chip `Saving…`, then the upload view
  with `Checkpoint ospf-up kept. It is not uploaded yet.` Nothing is uploaded without the Upload click. The
  job has `captured: false`: it does not end *Running* (section 3.4).
- After it exists the tick box is ticked and disabled with the text `Kept as checkpoint ospf-up.` Undoing a
  checkpoint is not offered (today's behaviour: checkpoints are never removed).
- **Disabled with its reason**, from two public fields of the job, never inferred from `state.jobs`:

| Field | Tick box | Text under it (`#save-keep-why`, the box's `aria-describedby`) |
|---|---|---|
| `capture_kept: false` (N8, DESIGN.md 3.5) | disabled | `The capture of this save is no longer kept. Save again to make a checkpoint.` |
| `capture_whole: false` (DESIGN.md 3.9) | disabled | `This capture does not include the topology. Save again first.` |

  It never recaptures silently: saving again is the ordinary Save button.

Both controls are optional and block nothing: the panel can be closed at any moment and the save is complete
without them.

## 5. The chip panel at rest, and the *Can't save* panel

### 5.1 At rest (G10)

```html
<!-- title: dot ok, "Saved 21 minutes ago"  (relativeTime, status.js:54) -->
<p class="save-sub" id="save-rest-name">Interface descriptions cleaned up</p>
<p class="save-kv"><span>Running:</span> your latest save</p>
<p class="save-kv"><span>Uploaded:</span> yes, to github.com</p>
<p class="save-kv" id="save-place"><span>Saves to:</span> CLAB-MNGR-DEV-LLM › bgp <button type="button" class="button ghost small" id="save-change" data-save-action="place">Change…</button></p>
<p class="save-kv" id="save-last-load"><span>Last load:</span> Start, 2 hours ago <button type="button" class="button ghost small" id="save-load-details" data-save-action="load-details">Details</button></p>
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
| `Running:` | `your latest save`. Shown only in the *Saved* view and only while no deploy, redeploy, destroy or design apply of the lab finished after that save; otherwise the line is left out, because the manager does not know that the devices still equal it. After a load the chip is *Running* and the Load designer's view names what runs |
| `Uploaded:` | `yes, to <host>` for `synced` / `unchanged`; `no, kept on the lab VM` for `kept` |
| `Saves to:` | `<repository> › <folder>` from the lab's connection (`gitRepoName`, `git-progress.js:26`, and `repository.prefix`; `top level` when empty). **Change…** closes the panel and opens the chooser, `saveDrawerOpen('chooser', {opener: $('save-chip')})` (DESIGN.md 3.8, Q1: chip, **Change…**, a folder, **Save here** is four clicks) |
| `Last load:` | `<name>, <when>` of the lab's newest effective load (`loadSourceName`, `relativeTime`), while the manager holds one. **Details** opens today's restore job window, `restoreShowJob(job.id)` (`app/static/restore.js:350`), with the chip as opener; that window has **Load this backup…** beside its backup from before the load (DESIGN.md 7.2), so Undo stays reachable after the next save (review F4, U1) |
| `Also:` | the `also` line of section 3.4, with **Show** |
| Foot | **All versions** → `saveDrawerOpen('versions', …)`, **Save settings** → `saveDrawerOpen('settings', …)`, **Save as a lab state…** → `saveDrawerOpen('state', …)`. Each closes the panel first and passes the chip as the opener |

The `Saves to:` and `Last load:` lines and the foot end every chip panel view of a lab that has a save
location (saving, upload, upload failed, *Can't save*, rest). In the saving view they stay enabled; they
read, they do not save, except **Change…**, which is disabled while a save or a place request runs, with
the chip saying why. A lab without a save location has no `Saves to:` line, and its foot holds **Save as a
lab state…** alone (review R2; section 6.2).

### 5.2 *Can't save* (6.5)

One view: one sentence and the actions of its row. The table is DESIGN.md 3.6; nothing else may stop a save.
The cause is found in this order: a job that stopped on a device (`capture_incomplete`); `lab.git_status.code`
when the status is not ready; else `other`. The page matches no message text: the manager maps the helper's
fixed sentences to a code in one table (N1).

```html
<!-- title: dot bad, "Can’t save" -->
<p class="save-sub" id="save-cant-why">The lab VM could not be reached.</p>
<div class="save-row">
  <button type="button" class="button primary" id="save-cant-retry" data-save-action="again">Try again</button>
  <button type="button" class="button ghost small" id="save-cant-fix" data-save-action="vm">Check the VM connection…</button>
</div>
<p class="form-error" role="alert" id="save-panel-error"></p>
```

| Cause (how the page knows) | Sentence | Actions |
|---|---|---|
| The VM cannot be reached (`vm`) | `The lab VM could not be reached.` | **Try again** · **Check the VM connection…** |
| The VM account cannot upload (`account`) | `The VM account cannot upload to <host>.` | **Try again** · **Details** |
| An unfinished Git operation, staged or unsaved edits in the save's folder (`busy`); also the upload view when no manager save is at the checkout's newest commit (section 4.3) | `Someone is working in this repository on the VM.` | **Try again** · **Details** |
| The online copy has changes this VM lacks, and nothing waits here (`diverged`, no waiting save in the repository) | `The online copy has changes this VM does not have.` | **Update from the repository** |
| The same, while saves wait here: each side has changes the other lacks (`diverged`, a save waits in the repository) | `The online copy and this VM both have changes the other does not have. They have to be combined on the VM.` | **Details** only (what the repository's owner does on the VM; the manager never merges, rebases or force-pushes) |
| A device cannot be read (the stopped job is `capture_incomplete`) | `<device> could not be read, so nothing was saved.` | **Try again** · **Save settings** · **Details** (DESIGN.md 7.6) |
| Files the manager did not save are inside `latest`, `baseline` or a checkpoint folder (`files`) | `<folder> holds files that were not saved by the manager.` | **Choose another place** · **Details** |

Two causes DESIGN.md names outside that table, and the fallback:

| Cause | Sentence | Actions |
|---|---|---|
| No device is selected (`settings`; DESIGN.md 3.3) | `No device of this lab is selected for saving.` | **Save settings** |
| Anything else (`other`: a helper that is missing or out of date, an unknown message) | `The save did not work.` | **Try again** · **Details** |

Details of the rows:

- `<device>` is the short name of each node of the linked backup job (`job.backup_job_id` in `state.jobs`)
  whose status is not `succeeded`; two read `ceos and xrv9k could not be read…`; without the names: `A
  device could not be read, so nothing was saved.`
- `<folder>` is the lab's folder (`repository.prefix`, `the top level` when empty).
- **"Nothing waits here"** is a statement about the repository, not the lab: *Update from the repository* is
  a fast-forward and cannot work while any save waits in the checkout (DESIGN.md 3.6, review X9). The page
  tests `state.git_jobs` of every lab for a job with a commit that is not uploaded and whose
  `destination.checkout` is this lab's checkout. Commits the manager no longer holds are invisible to that
  test; when the update is then refused, the refreshed status shows the row below it. With saves waiting and
  no divergence the chip is *Waiting* and the action is **Upload**.

Where each code comes from today, for the manager's table (N1; `app/git_progress.py` at `11ed352`):

| Code | Signals |
|---|---|
| `vm` | `Connect the VM and verify its SSH host fingerprint first.` (`app/git_progress.py:322`); `Cannot reach the VM Git helper…` (`app/git_progress.py:587`); `Git connection interrupted…` (`app/git_progress.py:340`); `The VM identity changed…` (`app/git_progress.py:579`); `Reconnect the original VM before saving progress.` (`app/git_progress.py:1365`) |
| `account` | `Git push preflight failed…` (`app/host_git.py:307`); `The VM account is not signed in to GitHub…` (`app/host_git.py:818`); `…cannot push to <slug>…` (`app/host_git.py:824`); `…push failed. Check authentication…` (`app/host_git.py:474`) |
| `busy` | `Finish the existing Git operation before saving lab progress.` (`app/host_git.py:340`); `The repository already has staged changes…` (`app/host_git.py:341`); `The repository has unsaved edits in the selected scope…` (`app/host_git.py:344`); the staged-edit checks (`app/host_git.py:494,499`); `The push would include commits created outside manager saves…` (`app/host_git.py:470`) |
| `diverged` | `The remote branch advanced or diverged…` (`app/host_git.py:468`); `Local and remote history diverged…` (`app/host_git.py:757`) |
| `files` | the `publish` refusal for a `latest`, `baseline` or checkpoint folder that holds files its manifest does not own (DESIGN.md 2.3, "Not changed") |
| `settings` | an empty device selection (DESIGN.md 3.3) |
| `other` | `Git helper is unavailable. Run setup-git.sh on the VM.` (`app/git_progress.py:358`); `Update the VM Git helper…` (`app/git_progress.py:592`); `Install or refresh the matching Git helper on the VM.` (`app/git_progress.py:354`); any other message |

What each action does:

- **Try again** (`again`): for a stopped job that can be retried (`export_pending`, `interrupted`), `POST
  /api/git/jobs/{id}/retry {push: false}`, which reuses the capture and ends at the upload view
  (`app/git_progress.py:1463-1465,1486`); this is the same for a job of kind `state`, whose retry retries
  that job and never starts a save of the lab (review K5). For `capture_incomplete` and `failed`, which the
  server will not retry (`app/git_progress.py:1454-1455`), a new save (section 4.1). For a status that is
  not ready or a refusal with no job, `gitLoadContext(id, true)` reads the status again
  (`git-progress.js:138-143`; the settings route refreshes `lab.git_status`) and a new save follows when it
  is ready. In every case "the save resumes from there" (PROMPT 6.5).
- **Check the VM connection…** (`vm`): `openVmDialog()` (`app/static/management.js:182`, as the banner does,
  `app.js:248`).
- **Update from the repository** (`update`): `gitUpdateRemote(id)` (`git-progress.js:714-718`, `POST
  /api/labs/{id}/git/update`, `app/git_progress.py:1497-1519`), today's confirmation dialog and request.
- **Save settings** (`settings`): `saveDrawerOpen('settings', …)`, where the device can be left out of the
  selection (review F7).
- **Choose another place** (`place`): `saveDrawerOpen('chooser', …)`.
- **Details** (`details`): with a job, `gitShowJob(job.id)` (the save window); without one, the *Git
  details* section of the Save settings drawer, which shows the raw status text (today's
  `#git-advanced-status`, `git-progress.js:428`) and, for the diverged row, what the repository's owner does
  on the VM. The raw message is only ever there, never in the sentence.

None of these is a folder rule. "Lab folders cannot overlap", the refusal for another lab's waiting save,
"Repository settings changed" and the pending-save refusals of a folder change are not in the table:
DESIGN.md sections 1, 2 and 3.1 remove them. If one still arrives it is shown as `other` with its text under
Details, which the "try to get blocked" pass must then report.

When a load is live under *Can't save* (row 3) the view ends with `Also: this lab runs <name>.` (or `Also:
<name> was loaded on 3 of 4 devices.`) and **Show**, which opens the Load designer's view with **Undo this
load**; when `count` is not zero a second line, `Also: 1 save to upload.`, opens the upload view.

The lab banner's two save branches go (`app.js:237-243`: "Saving to Git is not possible right now." with
**Save location settings**, and the save-attention banner with **Retry** and **Details**): DESIGN.md 7.6;
the chip carries them, and the banner keeps what a load or an operation reports. Banner buttons
`#banner-retry-save` and `#banner-save-details` stay in the markup (load-bearing, ADDENDUM J3) and simply
stay hidden.

## 6. First save (5.9, F12)

### 6.1 Today

`gitSaveProgress()` calls `gitFirstSave()` for a lab without a save location (`git-progress.js:578-582`): a
dialog with repository select, folder field, device list, the required label and the exposure tick box
(`git-progress.js:507-531`). It registers the folder when needed (`POST
/api/git/repositories/{id}/folders`, `git-progress.js:526`), links the lab (`PUT /api/labs/{id}/git`,
`git-progress.js:527`; route `app/git_progress.py:1158-1189`) and saves (`git-progress.js:529`). With no
repository on the VM it opens `gitConnectByUrl(id, {firstSave: true})` (`git-progress.js:512,485-504`).

### 6.2 With a repository on the VM

Pressing **Save** (or the chip) on a lab without a save location opens the chip panel and fetches `GET
/api/labs/{id}/git/places` (DESIGN.md 2.8 and section 4): the repositories on the VM and `default`, the
place a first save can go to with one click and nothing typed. While it loads:
`<p class="save-sub" role="status">Looking for a place to save…</p>`.

```html
<!-- title: dot none, "Not saved yet" -->
<p class="save-sub" id="save-first-place">Your first save goes to CLAB-MNGR-DEV-LLM, in a folder named restore-square.</p>
<div class="save-row">
  <button type="button" class="button primary" id="save-first" data-save-action="first-save">Save</button>
  <button type="button" class="button ghost small" id="save-first-place-other" data-save-action="place">Choose another place</button>
</div>
<p class="save-note">Saved files can contain passwords or keys.</p>
<p class="form-error" role="alert" id="save-panel-error"></p>
<div class="save-foot">
  <button type="button" class="button ghost small" id="save-as-state" data-save-action="lab-state">Save as a lab state…</button>
</div>
```

- **Default place.** The manager's, not the page's: the repository the lab used last, else the one saved to
  most recently, else the first; the folder `clean_folder(<lab name>)`, or the first of `<lab>-2`,
  `<lab>-3`, … whose answer is `free`, `own` or `own-before`. The page shows `default` and computes
  nothing. The sentence says "in a folder named" when the answer's `exists` is false and never claims that
  such a folder is in the repository (the planned-folder rule in `CLAUDE.md`); for `own-before` it reads
  `Your saves continue in <repository>, in the folder <folder>.`
- **A lab of the same name (review F3).** When the folder named after the lab holds saves of a lab with the
  same name and another id, the panel asks once, in place of the sentence and its row:

```html
<p class="save-sub" id="save-first-place">This repository already holds saves of a lab named restore-square.</p>
<div class="save-row">
  <button type="button" class="button primary" id="save-first" data-save-action="first-save">Save in restore-square-2</button>
  <button type="button" class="button ghost small" id="save-first-continue" data-save-action="first-continue">Continue there</button>
</div>
```

  **Save in `<name>-2`** uses `default.folder`. **Continue there** sends the folder named after the lab with
  `choice: 'take'` (DESIGN.md 7.4). It never continues there silently, and the suggested button is the one
  that replaces nobody's saves.
- **Devices.** Every supported device: the request sends `node_names: []`. Changing them is in Save
  settings. A lab with no supported device shows `This lab has no device whose configuration can be saved.`
  and no Save button; the reason is the sentence.
- **The exposure tick box is gone (D5).** The sentence `Saved files can contain passwords or keys.` stays
  beside the button, and the button's request carries `acknowledge: true`, as the red Load carries its
  acknowledgement (D4).
- **Save** (`first-save`): place, then save, in one click.
  1. `POST /api/labs/{id}/git/place {repository, folder, choice: '', pending: '', move_files: false,
     node_names: [], acknowledge: true}` (DESIGN.md section 4; N9). The answer is `{saved, binding, job}` or
     `{question}` with status 200.
  2. `gitSubmitSave(id, {target: 'latest', push: true, note: ''}, undefined, {quiet: true})` and the flow of
     section 4 from step 1.
  Save is disabled while the place request runs (`saveHeader.placing`), with the title `Saving…`: a save
  that starts during a placement would store the old connection (review F14). A `{question}` cannot come
  for the default (it was chosen because its answer needs none), but the tree can change between the two
  requests: the panel then hands over to the chooser with the question in it,
  `saveDrawerOpen('chooser', {repository, folder, question, opener, then})`. A failure for an outside cause
  shows the view of section 5.2.
- **Choose another place** (`place`): closes the panel and opens the chooser for this lab at the default
  place, `saveDrawerOpen('chooser', {repository, folder, opener: $('save-chip'), then})`; when the chooser
  ends in **Save here** it places the lab and calls `then()`, which is the save of step 2.
- **Save as a lab state…** (`lab-state`): `saveDrawerOpen('state', {repository, opener})`. It needs no save
  location of the lab (DESIGN.md 2.9, 7.6; review R2).

### 6.3 Connected, but nothing saved yet

Row 11 for a lab with a save location. Same view, sentence `Your first save goes to <repository>, in the
folder <folder>.` (or `…at its top level.`), **Save** is the ordinary save, the second button is
**Change…** (the chooser), and the foot is the full foot of section 5.1.

### 6.4 No repository on the VM

When `repositories` is empty the same panel asks for the address in one field:

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

- The address check `/^https:\/\/[^\s/]+\/\S+/` and its message are today's (`git-progress.js:493`).
- **Request:** the address goes to the place route, not to `…/git/connect`: `POST /api/labs/{id}/git/place
  {url, folder, choice: '', pending: '', move_files: false, node_names: [], acknowledge: true}`. The manager
  connects the checkout at its top level and then places the lab in its folder inside it (DESIGN.md 2.8,
  7.6). `folder` is `default.folder` of the places answer.
- **An empty repository** (review F4, DESIGN.md H4) answers `{question: {kind: 'empty'}}`. The panel shows

```html
<p class="save-sub" id="save-first-empty">your-lab-repo is empty. The manager adds a README.md file to start it.</p>
<div class="save-row">
  <button type="button" class="button primary" id="save-first-start" data-save-action="first-start">Start the repository</button>
</div>
```

  with the address field read-only above it. **Start the repository** sends the same request with
  `initialize: true`. It is the only sender of `initialize` in the static scripts: starting a repository
  uploads a file, and that needs the person's click. `<name>` is the repository's name from the address.
- The waiting label, in the panel: title `Connecting…`, `This can take a minute.` (today's,
  `git-progress.js:497`).
- Then the save, as `options.firstSave` does today (`git-progress.js:501`), without the label dialog.

A helper error (`GitHub CLI is not installed…`, `The VM account is not signed in to GitHub…`, `…cannot push
to…`, `Cloning failed…`; `app/host_git.py:816-824,853`) is shown in `#save-panel-error` in the server's own
words: these are setup instructions and need their detail. The typed address stays in the field
(`data-dirty`, section 2.4).

Retired from today's dialog for this path: the folder field (the default is stated; **Change…** changes it
afterwards), the exposure tick box, and **Back up to this VM instead** (`git-progress.js:487-490`; the
backup stays under Tools › Configuration backups, `index.html:154`). What becomes of `gitConnectByUrl`
itself and of **Connect by URL…** is the drawer designer's.

The places request can fail (`409` with the helper's reason, as the catalogue does today,
`app/git_progress.py:1138-1141`): the panel then shows the view of section 5.2 (usually `vm`), not the
address field. An empty list and an unreachable VM must never look the same.

## 7. Wording

Every final string of this slice. `…` is one character; apostrophes are typographic. `<host>` is the push
host or `the online repository`.

| Where | State | String |
|---|---|---|
| Buttons | header | `Save` · `Load` |
| Chip | Saved | `Saved just now` · `Saved 21 min ago` · `Saved 2 h ago` · `Saved yesterday` · `Saved 3 days ago` · `Saved 12 Sep` |
| Chip | Saving | `Saving…` · `Uploading…` · `Updating…` |
| Chip | Waiting | `1 save to upload` · `3 saves to upload` |
| Chip | Upload failed | `Upload failed` |
| Chip | Can't save | `Can’t save` |
| Chip | Not saved | `Not saved yet` |
| Chip | Kept | `Kept on this VM` |
| Chip | Loading | `Loading… 2 of 4` · `Loading…` · `Checking devices…` |
| Chip | Running | `Running ospf-up` · `Running an earlier save, 2 days ago` · `Running your starting point` · `Running the configuration from before Start` |
| Chip | Partial | `Loaded 3 of 4` |
| Reason line | Save disabled, a place request | `The place to save is being set.` |
| Reason line | Save disabled, other work | the sentence of `busy()`, then `Save is available when it finishes.` (section 1.7) |
| Load panel | red Load during a save | `A save is running.` |
| Panel title | Saving | `Saving…` · `Uploading…` · `Connecting…` |
| Panel | Saving | `Reading the configuration of 4 devices. You can keep working.` · `Reading the configuration of 1 device. You can keep working.` · `Saving to the lab VM’s repository. You can keep working.` · `Moving the saved files. You can keep working.` · `Uploading to github.com. You can keep working.` |
| Toast | unchanged | `Nothing changed since your last save.` |
| Panel title | Waiting | `Not uploaded yet` |
| Panel | Waiting | the sentences of section 4.3 · `Checkpoint ospf-up kept. It is not uploaded yet.` · `bgp’s saved files moved to course/bgp.` · `This save is on the lab VM and not uploaded yet.` |
| Panel | Waiting, what else goes up | `This upload also sends 1 other save: Start (bgp).` · `This upload also sends 3 other saves: Start (bgp), ospf fixed (ospf-lab) and "Save r1: first save".` · `… and 4 more.` |
| Panel | Waiting, destination | `To:` `CLAB-MNGR-DEV-LLM › bgp` · `CLAB-MNGR-DEV-LLM › top level` |
| Panel | Waiting, review | `Checking what this upload sends…` · `What this upload sends could not be read from the lab VM.` |
| Panel buttons | Waiting | `Upload` · `Not now` · `See changes` · `Details` · `Try again` |
| Note | every view that can upload or save for the first time | `Saved files can contain passwords or keys.` |
| Drawer head | What changed | `What changed` · `ceos and xrv9k · 19 lines added, 1 removed · not uploaded yet · to CLAB-MNGR-DEV-LLM › bgp` · `… · uploaded` |
| Toast | uploaded | `Uploaded to github.com.` |
| Error | a save landed after the review (409, the server's) | `Another save was made in this repository. Look at the changes again.` |
| Error | Upload without the review answer | `See what this upload sends before uploading.` |
| Panel title | Upload failed | `Upload failed` |
| Panel | Upload failed | `Your save is safe on the lab VM, but github.com could not be reached.` · `Your save is safe on the lab VM, but it could not be uploaded to github.com.` · `This upload sends 2 saves: ospf fixed (bgp), Start (bgp).` |
| Panel buttons | Upload failed | `Try again` · `See changes` · `Details` |
| Panel title | Saved | `Saved just now` · `Saved 21 minutes ago` |
| Panel | naming | label `Name of this save` · tick box `Keep as a checkpoint` · `Kept as checkpoint ospf-up.` · `Renamed.` (live region) |
| Panel | naming, disabled | `The capture of this save is no longer kept. Save again to make a checkpoint.` · `This capture does not include the topology. Save again first.` |
| Panel | rest | `Running:` `your latest save` · `Uploaded:` `yes, to github.com` / `no, kept on the lab VM` · `Saved without a name` |
| Panel | rest, place | `Saves to:` `CLAB-MNGR-DEV-LLM › bgp` · button `Change…` |
| Panel | rest, load | `Last load:` `Start, 2 hours ago` · button `Details` |
| Panel foot | a lab with a save location | `All versions` · `Save as a lab state…` · `Save settings` |
| Panel foot | a lab without one | `Save as a lab state…` |
| Panel | hidden second state | `Also: 1 save to upload.` · `Also: the last upload failed.` · `Also: saving is not possible right now.` · `Also: this lab runs ospf-up.` · `Also: ospf-up was loaded on 3 of 4 devices.` · button `Show` |
| Panel title | Can't save | `Can’t save` |
| Panel | Can't save | the nine sentences of section 5.2 |
| Panel buttons | Can't save | `Try again` · `Check the VM connection…` · `Update from the repository` · `Save settings` · `Choose another place` · `Details` |
| Panel title | Not saved | `Not saved yet` |
| Panel | first save | `Looking for a place to save…` · `Your first save goes to <repository>, in a folder named <lab>.` · `Your first save goes to <repository>, in the folder <folder>.` · `Your first save goes to <repository>, at its top level.` · `Your saves continue in <repository>, in the folder <folder>.` · `This lab has no device whose configuration can be saved.` |
| Panel | first save, a lab of the same name | `This repository already holds saves of a lab named <name>.` · buttons `Save in <name>-2` · `Continue there` |
| Panel buttons | first save | `Save` · `Choose another place` · `Change…` |
| Panel | first save, no repository | `Your saves go to a repository on GitHub. Paste its address; ask your instructor if you do not have one.` · label `Repository address (HTTPS)` · `The lab VM’s own GitHub login is used. You are never asked for a password or a token here.` · `Saved files can contain passwords or keys. They go into a folder named <lab>.` · `This can take a minute.` |
| Panel | first save, an empty repository | `<name> is empty. The manager adds a README.md file to start it.` · button `Start the repository` |
| Error | first save, bad address | `Paste the HTTPS address, for example https://github.com/you/your-lab-repo.` (today's, `git-progress.js:493`) |
| Lifecycle dialogs | `operations.js:238` | `Save first` (was `Save progress first`) |

Not used anywhere in these views: "registration", "prefix", "overlap", "commit", "push", "review", "Git"
(except "GitHub" as the place and in the server's own setup messages), "snapshot".

## 8. File plan

Ownership is DESIGN.md section 5: one owner per file. This slice's design lands in four build slices.

### 8.1 Files that change

| File | Slice | Change |
|---|---|---|
| `app/static/index.html` | S5 | header markup of section 1.2 in place of `index.html:75`; `#lab-progress` removed from `index.html:73`; `<script src="/static/save-header.js?v=<release>" defer>`; `dialog#save-drawer` at page level (drawer designer) |
| `app/static/style.css` | S5 | section 1.4; the `.git-save-*` rules go with the menu |
| `app/static/shell.js` | S5 | the four edits of section 2.2 and the sentence at `shell.js:183` |
| `app/static/app.js` | S5 | `render()` calls `renderSaveHeader()` after `renderGitProgress()` (`app.js:122`); `renderLabHeader` loses its `#lab-progress` line (`app.js:103`); the two save branches of `renderLabBanner` go (`app.js:237-243`); `renderWorkerState` text `Saving progress…` → `Saving…` (`app.js:96`); `busy()` mirrors `operation_busy` and names what runs (section 1.7) |
| `app/static/status.js` | S6 | `saveChipState`, `relativeTimeShort`, `saveChangeSentence(summary, also)`, the helpers and constants of section 3.5; `loadState`, `loadSourceName`, `loadDeviceWord` and the changed `savedVersionName` as LOAD.md and DESIGN.md 3.8 define them; header comment line 6 reworded. `progressState` and `progressSummary` stay |
| `app/static/save-header.js` | S7 | new, section 8.2 |
| `app/static/git-progress.js` | S7 in the first wave: `gitReviewJob`, `gitReviewData`, `gitSubmitSave`, `gitStartWatch` only. S11 in the second wave: everything else of section 8.3 | |
| `app/static/home.js`, `app/static/operations.js` | S11 | `homeSavedLine` uses `saveChipState` (`home.js:7-14`); button label at `operations.js:238`; the comment at `operations.js:873` stays true |
| `app/git_progress.py`, `app/main.py`, `app/restore.py` | S3, S4 | the fields and routes of DESIGN.md 3.8 and section 4 |
| `docs/redesign/DESIGN-SPEC-ADDENDUM.md` | lead | a dated amendment lists what the owner decisions supersede: the ids of J2 that go (`git-save-menu`, `lab-progress`), the panel bodies under J3 (the two save banners), J4 ("Only `#git-save-menu` stays a `details`") and J6 (the first save) (DESIGN.md 7.6, review B1) |

### 8.2 The new script

`app/static/save-header.js`, loaded only by `index.html`, after `git-progress.js` and before
`git-places.js` (order: `… diff-view.js, git-progress.js, save-header.js, git-places.js, restore.js, …`). It
needs `?v=<release>` in `index.html`; `deploy/verify-release.py` checks that marker on every static asset of
the page, and `deploy/set-release.py` moves it (the lead runs both). No other page loads it.

House style: `'use strict'`, no listener on `document` or `window`, every global read at call time behind
`typeof` guards so the file loads in a Node `vm` context with a fake `$`, `esc` and `state`.

Names other scripts call (DESIGN.md section 5):

| Function | Does |
|---|---|
| `renderSaveHeader()` | called from `render()`; computes `saveChipState(current(), {...state, refusal, states})`; writes chip, title, reason line, `disabled` of Save and of the Load button, the live region; renders the body through `savePanelMarkup` when the panel is open |
| `saveOpenPanel(kind)` | `'status'` opens the chip panel, `'load'` the Load panel, through the opener's `_menuOpen`; used by Save, by the drawers when they hand back, and by `load.js` |
| `saveFinished(job)` | section 2.5; called by `gitStartWatch` |
| `saveAction(action, job, origin)` | the one dispatcher for `data-save-action` in the panel and the drawer head: `upload`, `not-now`, `changes`, `details`, `review-again`, `again`, `vm`, `update`, `settings`, `versions`, `lab-state`, `place`, `load-details`, `first-save`, `first-continue`, `first-connect`, `first-start`, `keep`, `show-also` |

Its own:

| Function | Does |
|---|---|
| `saveHeader` | page memory: `{refusal, placing, opened: Map, last: Map, naming, view, places}` |
| `savePanelView(cs, lab)` | pure: `{title, dot, key, html}` for the views `first`, `saving`, `upload`, `failed`, `cant`, `rest`; for `loading`, `running`, `partial` it calls `loadChipView(cs, lab)` of `load.js` when defined |
| `savePanelMarkup(el, key, build)` | section 2.4 |
| `saveCantRow(cs, lab, state)` | pure: the row of section 5.2 (`{sentence, actions}`) |
| `saveRename(job, value)` | section 4.8 |
| load-time block | `if($('save-chip')){…}`: the delegated `click` and `change` listeners on `#save-panel`, `panelopen` → render, `panelclose` → clear `refusal` and `naming` |

What it calls in other files, each behind a `typeof` guard: `saveChipState`, `saveChangeSentence`,
`relativeTimeShort` (`status.js`); `gitReviewData`, `gitReviewJob`, `gitSubmitSave`, `gitShowJob`,
`gitUpdateRemote`, `gitLoadContext` (`git-progress.js`); `loadChipView` (`load.js`); `restoreShowJob`
(`restore.js`); `openVmDialog` (`management.js`); and `saveDrawerOpen(kind, options)` of `save-drawers.js`
for all five drawers: `'changes'` (See changes), `'versions'` (All versions), `'settings'` (Save settings),
`'chooser'` (Change…, Choose another place) and `'state'` (Save as a lab state…). `options` carries
`opener` (the chip) and, where they apply, `job`, `repository`, `folder`, `question` and `then`.

### 8.3 `git-progress.js` and `app.js`: what moves, stays, retires

Consumers were searched in `app/static/*.js`, `app/static/*.html`, `tests/*.js` and `docs/*/tools/*.py`.
Line numbers are of `git-progress.js` unless a file is named.

**Stay unchanged:** `gitActiveStates`, `gitPendingStates`, `gitStateLabels`, `gitSaveSentences`, `gitLabel`,
`gitJobTime`, `gitTime`, `gitWhen`, `gitLabJobs`, `gitRepository`, `gitRepoName`, `gitSnapshotPath`,
`gitTargetPath`, `gitRequestId`, `gitReusableRequest`, `closeDialogsExcept`, `gitFocusDialog`,
`gitDestinationMarkup`, `gitJobMarkup`, `gitFilesDiffMarkup`, `gitLoadContext`, `gitRememberJob`,
`gitJobTitle`, `gitShowJob`, `gitDismissJob`, `gitCheckpointName`, `gitUpdateRemote`. `gitProblem`,
`notify`, `setMarkup`, `setListMarkup` in `app.js`.

**Stay, changed:**

| Function | Change | Wave | Consumers to keep working |
|---|---|---|---|
| `gitReviewJob` (`:654`) | section 4.5 | first (S7) | `network-design.js` (comment contract), `tests/test_git_progress_ui.js`, `docs/netlab-ui-qa/tools/coverage_run.py` |
| `gitReviewData` | new, section 4.5 | first (S7) | the panel, the drawer |
| `gitSubmitSave` (`:547`) | no `Saving progress…` toast; opens the chip panel; a refusal becomes `saveHeader.refusal` | first (S7) | `tests/test_git_progress_ui.js`, `docs/save-location-fix/tools/qa_lib.py` |
| `gitStartWatch` (`:682`) | end of watch → `saveFinished(job)`; no job dialog, no review dialog | first (S7) | `network-design.js:2139`, tests, `coverage_run.py` |
| `gitSavePayload` (`:71`) | `allow_removed: true` always | second (S11) | `tests/test_git_progress_ui.js` |
| `gitSaveProgress` (`:578`) | no label dialog; a lab without a save location → first-save panel | second | `operations.js:238-241`, `tests/test_git_progress_ui.js` |
| `gitRenderJob` (`:633`) | `review` calls `gitReviewJob(job)` (the drawer); the closing note at `:639` no longer names "Progress › Recent saves" | second | job window |
| `gitUploadLabel` (`:653`) | `Review and upload…` → `See changes and upload…` | second | `tests/test_git_progress_ui.js:179` (label rewritten, claim kept) |
| `gitNeedsReview` (`:652`) | no longer chooses the request body (every upload carries `reviewed` and `head`); kept for the job window's labels | second | job window |
| `gitSaveReason` (`:186`) | superseded by `busy()`'s sentence for `#save-reason`; kept while the Progress tab exists | second | `tests/test_git_progress_ui.js` |
| `gitValidateLabel` (`:83`) | used by rename only | second | none outside the file |
| `renderGitProgress` (`:191`) | loses the header lines (`:199-203` for `#git-save-progress`, the menu, the help); what is left serves the Progress tab until S11 removes it | second | `app.js:122` |
| `gitRunAction` (`:765`) | `settings`, `history`, `load`, `browse` route to the drawers (drawer designer) | second | `app.js:354`, tools |
| `busy` (`app.js:20`) | mirrors `operation_busy` and names what runs (section 1.7) | S5 | 16 call sites; `operations.js:631,637` pass it on as an argument |

**Retire** (each has a decision that removes its subject; tests that pin them are rewritten to the new
behaviour and listed for the report, PROMPT section 8):

| Function or element | Decision | Consumers found |
|---|---|---|
| `gitLabelDialog`, `gitLabelKey`, `gitLabelDraft`, `gitSaveLabelDraft`, `gitClearLabelDraft` (`:77-80,566-577`) | D2 | `tests/test_git_progress_ui.js` (`gitLabelDraft`) |
| `gitFirstSave` dialog (`:507-531`), `gitSuggestedFolder` (`:484`) | D5; the default place is the manager's (DESIGN.md 2.8) | `tests/test_git_progress_ui.js` |
| `gitSaveOptions` for `local` and `checkpoint` (`:585-610`) | D3, D6 | `tests/test_git_progress_ui.js`; the `baseline` part becomes **Use as starting point…** (drawer designer) |
| `gitCompleteBackups` (`:67-70`) as the test for "capture kept" | `capture_kept`, `capture_whole` (DESIGN.md 3.5, 3.9) | still used by **Choose a backup as starting point…** (drawer designer) |
| `gitSaveHelp`, `gitSaveHelpMarkup`, `gitRenderSaveHelp`, `gitShowSaveHelp`, `GIT_SAVE_HELP_ACTIONS` (`:151-169`) | D1 | `tests/test_git_progress_ui.js` |
| `gitSaveMenuPlacement`, `gitPlaceSaveMenu`, `gitInsideMenu` (`:173-183`) | D1; the clamp is `initPanel`'s | `tests/test_git_progress_ui.js`, a comment in `style.css` |
| `gitDoneToast` (`:674-681`) | D3 (the panel and two toasts replace it) | `tests/test_git_progress_ui.js` |
| `gitPushPending` (`:705-713`) | 5.11 (**Upload** in the chip panel) | `app.js:240` (the banner branch that goes), `gitRunAction('push')`, `tests/test_git_progress_ui.js` |
| the `upload_blocked` branch of the review dialog (`:668`) | the sibling refusal is gone (DESIGN.md 3.4) | `tests/test_git_progress_ui.js` |
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

**`tests/test_status_ui.js`** (S6, extended; `status.js` alone in a `vm` context). One test per row of
DESIGN.md 7.1, then the order:

1. Saved: newest capture save `synced` → `saved`, dot `ok`, `Saved 21 min ago`, panel `rest`; an `unchanged`
   save after it keeps the earlier time; only `unchanged` saves known still reads Saved.
2. Saving: `queued`, `capturing`, `exporting` → `Saving…`, dot `busy`, `saveDisabled` true and
   `loadDisabled` false; `pushing` → `Uploading…`; `target: 'update'` → `Updating…`.
3. Waiting: one `review_pending` with a commit → `1 save to upload`; `committed` and `interrupted` with a
   commit count; two jobs with one commit count once; three commits → `3 saves to upload`; a `dismissed`
   job does not count; a folder move and a design export count.
4. **Waiting after Disconnect:** a lab without `git_binding` and one waiting save → `waiting`, `1 save to
   upload`, never `Not saved yet` (review K4).
5. Upload failed: `push_pending` → `Upload failed`, dot `bad`, with the count of all waiting commits.
6. Can't save: `git_status.ready === false` with each code; newest job `capture_incomplete`,
   `export_pending`, `failed`, `interrupted` without a commit; `refusal` set; each → `Can’t save`, dot
   `bad`, panel `cant`; `git_status.checked === false` or no `git_status` is not *Can't save*.
7. Not saved: no binding and no job → `Not saved yet`, dot `none`, panel `first`; a connected lab without a
   save the same. Kept: every save dismissed → `Kept on this VM`.
8. Loading: an active restore with targets → `Loading… 2 of 4` counting only devices with a final word,
   `saveDisabled` and `loadDisabled` true; `interrupted` with `rechecking: true` → `Checking devices…`; an
   `interrupted` job without `rechecking` is not Loading.
9. Running: a `succeeded` load newer than `S` → `Running <name>`, dot `info`. The name: the lab's own
   `latest` at a save's commit → that save's current name (also after a rename); at another commit → `an
   earlier save, <when>`; a checkpoint → its name; the starting point → `your starting point`; a lab state
   → its name from `ctx.states`; the backup from before load X → `the configuration from before X`; the undo
   of that → `X`. No test expects a label stored on the restore job.
10. Partial: a `needs_attention` or `partial` load → `Loaded n of m` with `n` counting `verified` only: four
    replaced devices of which one is `applied_unverified` read `Loaded 3 of 4` (review O1); `rolled_back`,
    `failed`, `uncertain` are never counted as loaded.
11. Effective load: a load whose every device is `failed`, `ineligible` or `rolled_back` sets no state; a
    device `interrupted` before it was changed (stage `failed`, settled) does not make a load effective
    (review O2); one `uncertain` device does.
12. **The order (DESIGN.md 7.1), one test per pair and the six sequences:** load A succeeds then load B
    fails → still `Running A` (K1); a save waits, then a load succeeds → `Running` with `also` Waiting (K3);
    a load succeeds, then a save attempt fails → `Can’t save` with `also` the load; the same with a refusal
    instead of a failed job; a failed attempt older than the load → `Running` with `also` Can't save; a
    checkpoint made from an existing capture (`captured: false`) after a load → still `Running`, `also`
    Waiting (K2); a capture save newer than the load → the save states; Loading over Saving over
    everything; Can't save over Upload failed over Waiting; another lab's jobs never count.
13. Kinds: a waiting job of kind `state` counts in Waiting; an uploaded one newer than the lab's own save
    never names *Saved* and never ends *Running*; a lab with only a `state` job reads `Not saved yet`; the
    same three for kind `design` (K5).
14. What ends a load: a finished `deploy`, `redeploy`, `destroy` operation or design apply of the lab newer
    than `L` → the save states; an older one, a running one, another lab's one and a `restart` do not (K6).
15. A job without `captured` counts as a capture save only when its target is `latest`.
16. `relativeTimeShort`: every threshold, an invalid time gives `''`, never `NaN`.
17. `saveChangeSentence(summary, also)`: each row of the tables in section 4.3; singular and plural; more
    than four devices; `removed_devices`; no summary; `also` with one, three and seven rows, a row of
    another lab, a kept save, and a row without a manager save named by its subject.

**`tests/test_save_header_ui.js`** (S7, new; harness as `tests/test_readiness_ui.js`: `status.js`, `app.js`,
`git-progress.js`, `save-header.js` with fake elements):

1. Panel markup per view (`first`, `first` with the same-name question, `first` without a repository,
   `first` with the empty-repository question, `saving`, `upload`, `failed`, `cant` for each of the nine
   rows, `rest`, naming): the strings of section 7, real `<input type="checkbox">` inside a `<label>`, every
   focusable control with an id, every interpolated value escaped (a lab named `<img>`).
2. Class names: every `class` token starting with `save-` in every view's markup is in the list of section
   1.3 (DESIGN.md 7.5).
3. Save on a lab with a save location posts `/labs/{id}/git/save` once with `note: ''` and
   `allow_removed: true` and opens no dialog.
4. Save on a lab without one posts nothing and opens the first-save view; its Save posts
   `/labs/{id}/git/place` with `acknowledge: true`, `choice: ''` and the default folder, then the save.
   **Continue there** posts the folder named after the lab with `choice: 'take'`. The address variant posts
   `/git/place` with `url` and `acknowledge: true` and refuses a non-HTTPS address in the page.
5. **`initialize`, single sender:** the address request never carries `initialize`; the answer `{question:
   {kind: 'empty'}}` renders the sentence and **Start the repository**, whose click posts the same body with
   `initialize: true`; in the stripped source of `app/static/*.js`, `/initialize\s*:\s*true/` matches
   exactly once.
6. Save is disabled while the place request runs and enabled when it ends or fails.
7. **Not now** sends no request, closes the panel and shows no toast.
8. **The upload view before the answer:** the sentence from `job.summary` and `To:` from `job.destination`
   are rendered with no request answered; Upload is disabled and `Checking what this upload sends…` is
   visible; after the answer the sentence names every row of `also_sends` and Upload is enabled; a failed
   request shows the failure sentence with **Try again** and no Upload.
9. **The upload carries `head`:** Upload in the panel and Upload in the drawer head each end in exactly one
   `POST /git/jobs/{upload_job}/retry` whose body is `{"push":true,"reviewed":true,"head":"<head>"}`, with
   `upload_job` and `head` from the review answer, also when `upload_job` is another lab's job. This
   rewrites the claim of `tests/test_git_progress_ui.js:170-187` for the new surface.
10. **No upload without the answer:** `gitReviewJob(job, {upload: true})` throws and posts nothing when no
    review is cached; when the set of waiting saves in `state.git_jobs` changed after the review was fetched;
    when the answer has no `upload_job`.
11. **The 409 path:** a 409 from the retry route empties the cache, fetches `…/git/compare` again, renders
    the new `also_sends`, shows the server's sentence in the view's `.form-error`, and uploads nothing
    until the next click, which then carries the new `head`.
12. **Single sender, source:** read every `app/static/*.js` (not the built `lab-builder/` bundle), strip
    comments, and assert that `/reviewed\s*:\s*true/` matches exactly once, inside the text of
    `gitReviewJob.toString()`.
13. `gitReviewJob(job)` without `upload` posts nothing and calls `saveDrawerOpen('changes', …)`.
14. `gitReviewData` caches per job, asks again when the waiting set changes, and returns `files`,
    `summary`, `head`, `upload_job`, `also_sends`.
15. **Details** in the upload view and in the failed view opens the save window (`gitShowJob`) with the chip
    as opener; that window still offers *Keep snapshot only* (review F2).
16. A waiting folder move shows `<lab>’s saved files moved to <folder>.`; finishing a move never calls the
    retry route (review F2 of the risk review).
17. `saveFinished`: `unchanged` → the toast and no panel; `review_pending` → the panel opens once for that
    job; not for another lab; not while `dialog[open]` exists; not while another menu is open; not twice.
18. `savePanelMarkup`: an unchanged key does not touch `innerHTML`; a changed key keeps focus by id, keeps
    the typed value and caret of a `data-dirty` input, and sends focus to the title when the control is gone.
19. Chip rendering changes `textContent` and `className` only (the button node is the same object after two
    renders); the live region is written on a key change, not on the first render and not on a time tick,
    and stays silent for `unchanged` and uploaded. No element with `role="status"`, `role="alert"` or
    `aria-live` contains a button (review A1).
20. **Disabled controls (section 1.7):** Save is disabled with a visible reason in `#save-reason` while a
    place request runs and while `busy()` names an operation, a backup, another lab's load or a design
    apply; the reason is hidden when the chip itself says `Saving…` or `Loading…`. The Load button is
    disabled only while a load of this lab runs and is enabled during a save.
21. The rest view shows `Saves to: <repository> › <folder>`; **Change…** calls `saveDrawerOpen('chooser', …)`
    and is disabled during a save. It shows `Last load: <name>, <when>` only while a finished effective load
    is in `state.restore_jobs`; its **Details** calls `restoreShowJob` with that job's id.
22. *Can't save*, per row: the sentence and exactly the actions of section 5.2. **Update from the
    repository** is rendered for `diverged` only when no un-uploaded job of any lab names the checkout; with
    one, the combined sentence and **Details** only. The device row has **Try again**, **Save settings**,
    **Details**; the `files` row has **Choose another place**, which calls `saveDrawerOpen('chooser', …)`.
23. **Try again** on a stopped job of kind `state` posts that job's retry and never `/git/save`.
24. Keep as a checkpoint posts `target: 'checkpoint'` with the save's `backup_job_id` and an empty
    `checkpoint`; it is disabled with its sentence for `capture_kept: false` and for `capture_whole: false`.
25. Rename: Enter commits once to `/git/jobs/{id}/name`; an empty value posts `{note: ''}` and shows the
    automatic name from the answer; a failed request leaves the typed text and shows the message.
26. The foot: three buttons for a lab with a save location, each calling `saveDrawerOpen` with `versions`,
    `state`, `settings`; **Save as a lab state…** alone for a lab without one.
27. A lab without a save location and a waiting save shows the upload view with `To:` from the job.

**`tests/test_shell_ui.js`** (S5, extended): `initPanel` opens and closes; opening a panel closes an open
menu and the reverse; Escape inside returns focus to the opener; Escape with focus outside closes and leaves
focus; a pointer down inside the wrapper keeps it open and outside closes it; `focusout` to an outside
control closes, `focusout` with no `relatedTarget` does not; `panelCanOpen` is false with a `dialog[open]`
and with another expanded menu; the `#git-save-menu` cases are rewritten to the panel. `busy()` is truthy
and names what runs for each thing `operation_busy` counts, and falsy otherwise.

**`tests/test_home_ui.js`** (S11, extended): the card's saved line equals the chip text for Saved, Waiting,
Can't save, Running and Not saved.

**`tests/test_git_progress_ui.js`** (S11; rewritten cases, claims kept): the mandatory review
(`test_git_progress_ui.js:170`), the folder-move review (`test_git_progress_ui.js:575-583`) and the
multi-lab review count (`test_git_progress_ui.js:596`) are asserted on the review data and the panel
sentence; label-draft, save-help and menu-placement tests are rewritten to the new behaviour and named in
the report with D1 and D2. Removed with their subject, each named in the report: the upload-blocked state
and "Save settings disabled while a save waits" (review D2).

## 9. Friction budget (PROMPT 9.5) for these flows

Clicks counted from a lab page with nothing open.

| Flow | Path | Clicks | Typed |
|---|---|---|---|
| First save, standard install (one repository on the VM) | **Save** → panel `Not saved yet` → **Save** | 2 | nothing |
| …and uploaded | … → **Upload** | 3 | nothing |
| First save, a lab of the same name is in the repository | **Save** → **Save in `<name>-2`** | 2 | nothing |
| First save, no repository on the VM | **Save** → paste the address → **Save** | 2 | the address |
| …into a brand-new, empty repository | … → **Start the repository** | 3 | the address |
| Later save, uploaded | **Save** → **Upload** | 2 | nothing |
| Later save, nothing changed | **Save** → toast | 1 | nothing |
| Later save, kept on the VM | **Save** → **Not now** | 2 | nothing |
| Later save, after looking | **Save** → **See changes** → **Upload** | 3 | nothing |
| Upload the waiting saves later | chip → **Upload** | 2 | nothing |
| Retry a failed upload | **Try again** (panel open) or chip → **Try again** | 1 or 2 | nothing |
| Name the latest save | chip → the field → Enter | 1 | the name |
| Keep the latest save as a checkpoint | chip → **Keep as a checkpoint** (→ **Upload**) | 2 (3) | nothing |
| Change the folder | chip → **Change…** → a folder → **Save here** | 4 | nothing (each question the situation needs adds one click; review R1) |
| Resume after *Can't save* | the first action of the panel | 1 | nothing |

The budget's "first save: at most 2 clicks and nothing typed" and "later saves: 2 clicks" hold. The first
save is on the lab VM after two clicks and on GitHub after a third; the third cannot be removed without
uploading without an explicit Upload, which section 8 of the prompt forbids. Upload waits for the review
answer (one helper round trip); that is time, not a click. Loading a lab state and saving one are measured
by their owners.

## 10. Assumptions, answered questions, what to attack

### 10.1 Assumptions

1. `/api/state` keeps `git_jobs`, `restore_jobs`, `operations`, `design_jobs` and `jobs` in their current
   public shapes; the fields of section 3.2 are additions.
2. `upload_job` in the review answer is the id of a job. Each `also_sends` row carries `name` and, for a
   manager save, `job_id`, `lab` (its name) and `kind`; a row without `job_id` is a commit named by its
   subject. `summary.removed_devices` is a list of labels.
3. The places answer's `default` carries `repository` (`{id, name}`), `folder`, `exists`, `kind` and, when
   the folder named after the lab holds saves of a lab with the same name and another id, `same_name` (that
   folder). DESIGN.md section 4 names `default` without its fields.
4. The `{question: {kind: 'empty'}}` answer carries the repository's `name`; the page falls back to the last
   part of the address.
5. A finished deploy, redeploy, destroy or design apply ends a load whatever its own outcome (section 3.5).
6. One pulsing element per surface (ADDENDUM J5) still binds: the chip dot stops pulsing while the lab pill
   pulses.
7. Design exports (`kind: 'design'`) use the same upload view with the fallback sentence and their files in
   See changes; they never open the panel by themselves.
8. The Progress tab still exists while S5 to S10 are built; nothing here needs it, and `renderGitProgress`
   keeps serving it until S11.

### 10.2 Questions the lead answered

| Question of the first draft | Answer | Where |
|---|---|---|
| N1, the problem signal | `lab.git_status = {checked, ready, problem, code}`, kept from the last helper `status`, never fetched by the poll; codes `vm`, `account`, `busy`, `diverged`, `files`, `settings`, `other` | DESIGN.md 3.8 |
| N2, a label on the restore job | No; the name is derived (`loadSourceName`). `saveLoadName` is dropped | DESIGN.md 3.8, 7.1, 7.6; review O4 |
| N3, the empty note and the automatic name | Yes | DESIGN.md 3.2 |
| N4, who computes the change summary | The manager, stored on the job as `summary` after the commit; `compare` gains `role` and `node` per file | DESIGN.md 3.8 |
| N5 and the sibling hold | Not needed: the refusal is gone, and the review names every save the upload carries | DESIGN.md section 1, 3.4, 3.8 |
| N6, rename | `POST /api/git/jobs/{id}/name`; an empty name returns to the automatic one | DESIGN.md 3.2, 3.8 |
| N7, the checkpoint name | The manager derives a free name from the save's name | DESIGN.md 3.5, 3.8 |
| N8, is the capture kept | Public `capture_kept`, and `capture_whole` for a capture without the topology | DESIGN.md 3.5, 3.9 |
| N9, one place call | `POST /api/labs/{lab}/git/place`, answering `{question}` or `{saved, binding, job}` | DESIGN.md section 4, 7.4 |
| Pending saves and *Update from the repository* | Offered only when nothing waits in the repository; with saves waiting the action is Upload; when both sides have changes, **Details** only | DESIGN.md 3.6; review X9 |
| The precedence | Newest event wins between the load family and the save family; the table of 7.1 | DESIGN.md 3.8, 7.1; review K1 to K4 |
| A stopped save that cannot be retried | It is a failed attempt until the next capture save or load; **Details** opens its window | DESIGN.md 7.1 |
| The default place with several repositories | The repository the lab used last, else the one saved to most recently, else the first | DESIGN.md 2.8 |
| A toast after *Not now*; `allow_removed`; the two save banners; Disconnect while a save waits; the device row's actions; a lab state before the first save; live regions | None; always true; removed; the save keeps waiting; **Try again**, **Save settings**, **Details**; offered in the first-save foot; a sentence only | DESIGN.md 7.6 |
| Class names | The table of section 1.3 | DESIGN.md 7.5 |

Still open, for the lead:

1. Naming form versus rest form (section 4.8): the name is an editable field while it is automatic or being
   named, and plain text afterwards. No ruling changed it; say so if the name should always be a field.
2. The points of the final report of this revision: where a ruling leaves a field or a case undefined
   (assumptions 2 to 5, the `diverged` row's "nothing waits" test, `also` under row 3).

### 10.3 What a reviewer should attack

1. **The upload is of what was shown.** Find a path on which the retry route is posted with a `head` the
   person did not see the list for: a poll that changes the waiting set between the render and the click, a
   cached answer of another job, the drawer opened for one save and the panel for another, the 409 path
   uploading by itself, a save made by another browser that `/api/state` has not delivered yet (the server's
   comparison with the helper's `status` is the backstop; the page must not depend on being it).
2. **Truth of the sentence.** Any case where the sentence under-reports what an upload sends: more than
   three other saves, a save the manager no longer holds, a kept save, a move, a state, a truncated diff
   (`counts_partial`, `diff-view.js:26`), a job without `summary`.
3. **`To:` after a change of connection.** A save that waits, then a folder change, a repository change or a
   Disconnect: the line must name where that save goes, not where the lab saves now.
4. **The order table against real sequences:** save, load, save; load during a waiting upload; a failed
   save and then a load (the failure must stop winning); two loads; a manager restart during a load
   (`rechecking`); a save by another browser; clocks (`finished` of a restore after a restart is the restart
   time, ADDENDUM J5; Git job times and restore times come from the same manager clock, operations too).
5. **`also` under row 3.** With a live load, a failed attempt and a waiting upload at once, `also` is the
   load and the waiting upload is a second line built from `count`. Check that neither is ever lost and
   that **Show** never lands on a view that hides the other.
6. **What ends *Running*.** A redeploy that failed half-way, a design apply that was refused in its
   preflight (assumption 5 ends the load for both), a `restart` (it does not), a load of another lab.
7. **Auto-open.** Any way the panel opens over a dialog, steals focus from a field, opens for a save the
   person did not start, or opens twice; and the opposite, a failure that is never shown because every
   condition failed and the person never looks at the chip.
8. **Focus.** Save becomes disabled right after it was clicked; the panel title must have focus by then.
   Upload turning from disabled to enabled under the pointer. The rebuild from the upload view to the
   uploading view removes the focused button. Tab out of the panel. The drawer's close returning to the chip.
9. **Disabled with a reason.** Every disabled control of sections 1.7, 4.3, 4.8 and 5.1 has its reason as
   visible text that a screen reader reaches (`aria-describedby`), never only a `title`.
10. **The first save.** The default place on a standard install end to end; the same-name question with a
    student's copy of a course lab; an empty repository where **Start the repository** fails half-way; the
    panel must never show a folder refusal.
11. **The *Can't save* rows.** A code the manager maps wrongly sends the person to the wrong action; the
    `diverged` row with a waiting save the manager no longer holds; `other` hiding a refusal that the
    design says no longer exists.
12. **Width.** Long lab-state names in `Running <name>`, the `Saves to:` line with a deep folder at 390 px,
    a page zoomed to 200 %, the 901 to 1279 px band, and the panel inside a 600 px high window.
13. **Removed banners.** With `app.js:237-243` gone, a save problem is visible only in the chip. Confirm
    that is enough on every tab and at 390 px, where the chip may be ellipsised.
14. **Tools and tests that still name `#git-save-menu`, `#lab-progress` or `gitPushPending`** (section 8.3).
