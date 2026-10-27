# C09 design: Help group, keyboard shortcuts dialog, Home lab filter, browser preferences

Rows R122 (help links), R123 (keyboard shortcuts dialog), R090 (lab filter on Home) and R125 (per-browser
preferences); R120 (dark mode) is **not pursued**: the binding UI contract (`docs/redesign/DESIGN-SPEC-ADDENDUM.md` J8,
"dark only for `#toast` and terminal.html") allows dark surfaces for the toast and the terminal only, and the owner
decided not to amend it (README.md, C09 row). R101 (vendor image notes) has no page in this repository to link and is
not pursued here either (§8). Written against `claude/parity-campaign` at `2e082c2` (release 1.31.2). Code read:
`shell.js` (the router, `initMenu` with its collapsed groups and `menuopen`, `initPanel`, `shellEscape`, every storage
helper), `home.js`, `app.js` (`PANELS`, `render`, `renderNodes`, `renderDeviceList`, `tabKeydown`, `openDetails`,
`stepDetails`, the `.close` wiring at line 386), `status.js`, `management.js` (the external-link pattern at line 50),
`operations.js` (`opDialog`, the `menuopen` listener at line 874), `terminal.js` (C02: `FONT_SIZES`, `FONT_KEY`, the
Alt and Ctrl+Insert chords), `topology.js` (the map's keys and the Escape order), `map-editor-page.js` (undo and
redo), `git-places.js` (`folderKey`), `save-drawers.js` (`drwOpenBranches`), `lab-builder-page.js` and
`git-progress.js` (their storage keys), `index.html`, `style.css` (the motion, contrast and forced-colour rules, the
menu and dialog rules), `main.py` (`/api/state`, the CSP and headers, `/vm-connection-guide`, the static mount),
`Dockerfile`, `.dockerignore`, `compose.yml`, `deploy/start-manager.sh`, the tests `test_shell_ui.js`,
`test_home_ui.js`, `test_page_load_ui.js`, `docs/redesign/tools/verify_after.py` and
`docs/ui-review-001/tools/check_ui008b.py`, `docs/student-quick-start/` (BUILD.md, PICKUP.md, the PDF), `docs/LAB-OPERATIONS.md`,
`docs/TOUR.md`. No helper, no helper `VERSION` bump, no new socket. One optional backend addition (§2.3): a GET page
route for the student guide, built like `/vm-connection-guide`. Nothing in this chunk sends a preference to the manager.

## 1. Decisions in one place

1. **The Help entries are a collapsed group in the Manager menu**, built with the `data-menu-group` machinery that
   `Lab actions ▾ › Advanced options` already uses (`shell.js:84-96`, `setGroup`, collapsed on every open, ArrowRight and
   ArrowLeft open and close it, the toggle never closes the menu). A flat list would take the Manager menu from 11 to 17
   items, which at 390 × 844 no longer fits under the top bar; the group costs one keystroke and keeps every present pin
   of `verify_after.py` on the menu (open across a poll, Escape returns focus). **Diagnostics stays the last item**,
   outside the group (an administrator's page, not help).
2. **External links are plain `<a role="menuitem">` items**, the pattern the Diagnostics item and the VM dialog's guide
   link already use (`index.html:43`, `management.js:50`): `target="_blank" rel="noopener noreferrer"`, the `↗` glyph in
   an `aria-hidden` span, no icon, no fetched asset, no reachability check. `initMenu`'s capture-phase click listener
   closes the menu and returns focus to the button before the browser follows the link (`shell.js:118-120`), and nothing
   calls `preventDefault`, so the new tab opens and the page behind it is tidy. The manager already sends
   `Referrer-Policy: no-referrer` (`main.py:133`); `noreferrer` on the anchor says the same thing where a reviewer looks
   first. CSP is untouched: `default-src 'self'` governs what the page loads, not where a link goes.
3. **The student guide route ships; the guide itself is not staged until the owner revises it.** Today the guide is
   not served: the Docker build context is `clab-backup-ui/` (`compose.yml:4`), so `docs/student-quick-start/` is
   unreachable by `COPY`, and the repository is private, so a GitHub link is a login wall for a student. The review
   found worse (§9 [0], [5]): the PDF was tested with release 1.30.35 and teaches the Progress tab that 1.31.0 removed
   (`guide.md:136` "Open the **Progress** tab", `:163` "On the Progress tab, find **Starting state** and click its
   **Apply to running lab…**", `:426` "→ **Progress** tab → **Connect a repository by URL**"), so serving it as it is
   would send students to a tab and buttons that do not exist. **Lead's decision, reversing the earlier one:** S0 builds
   the plumbing only: a `GET /student-guide` page route, a `student_guide` boolean in `/api/state` and the hidden menu
   item; `deploy/start-manager.sh` removes any staged copy and does **not** stage the PDF, so every installed manager
   hides the item until the owner reopens the guide's scope and supplies a guide written for 1.31.x (the owner question
   is in §8). The guide's content is not edited by this chunk.
4. **The shortcuts dialog lists only behaviours that exist, each with its line in the code** (§3). The drawer's Previous
   and Next are buttons without a key (`app.js:547`) and are not listed; the embedded editor's canvas keys are the
   editor's own and are not listed. **No `?` key**, for three reasons: `?` is a typed character in every field the page
   has (the Devices search, the new Home filter, the save path field, the topology editor in the operations dialog, the
   builder's fields), so a global chord would need an exclusion list that every new field extends or breaks; the
   manager's keyboard contract (J4) binds every key to a focused widget and keeps `Escape` as the only document-level
   key, and a hidden global chord has no visible affordance the way the menu item does; and `?` is `Shift+/` only on US
   layouts (AZERTY: `Shift+,`; German: `Shift+ß`), unreliable for an international class. The dialog is three keystrokes
   from the Manager button and the docs say where it is.
5. **Focus return is the browser's own.** A `<dialog>` closed with Escape or its × returns focus to the element that was
   focused when `showModal()` ran; the menu's capture-phase click has already put that focus on `#manager-button`
   (`shell.js:118-120`). No code is added for it; the fixture check asserts it (§6). The dialogs are static markup in
   `index.html` (J2: load-bearing ids exist at script load), so `app.js:386` wires their × at load as it wires every
   other `.close`.
6. **One text matcher for the Devices search and the Home filter**: `textMatch(term, parts)` in `status.js` (pure,
   loaded by every harness), a trimmed case-insensitive substring of the joined non-empty parts, an empty term matching
   everything, no wildcards (C03 §1.9 refused the upstream `* ? #` grammar for the same students). `app.js:290` and
   `app.js:322` call it instead of their two inline copies; the Devices claims ("No devices match. Try another name,
   address or platform.") are kept.
7. **The Home filter is a static input above the cards, never stored and never in the URL.** It survives the 4-second
   re-render for the same reason the Devices `#search` does: it is not inside the list that `setMarkup` rewrites, so the
   element, its value, its caret and its focus are untouched; `renderHome()` only reads it. It is not stored because a
   remembered filter would open Home with cards missing for a reason the student cannot see; it is not in the hash
   because the route is `lab`, `view`, `device` (`SHELL_ROUTE_KEYS`) and a filter is not a place. A lab matches on its
   name, its state word (`labState().label`: Running, Stopped, Starting, Needs attention) and its devices' short names,
   the Home analogue of the Devices fields (name, address, platform).
8. **Browser preferences is its own dialog, one item below Manager settings…**, so "settings" sit together while the
   two stay distinct: Manager settings… acts on the manager (Start fresh); Browser preferences… acts on this browser
   only and sends nothing to the manager (pinned: the script has no `fetch`, `api` or `json` call). It lists every key
   the manager's pages write today, by family, with its meaning and count (§5.1): the page scripts' keys, the keys the
   committed editor bundle writes on `lab-builder.html` and `map-editor.html` (same origin, the manager's own pages),
   and C07's capture memory keys as that design names them; the terminal text size as the one editable preference, the
   three display settings the stylesheet follows, and a **Reset browser preferences…** button. Two pins keep the list
   true (§6): every key literal a non-vendor script stores must match a family, and the editor's key literals are read
   out of the committed bundle so a pinned upgrade cannot change them silently.
9. **Reset clears preferences, never drafts or in-flight data.** The reset set is `clab.terminal.fontSize`,
   `clab.opened.<lab>`, `clab.dismissed.<job>`, the editor view keys and the capture memory keys in `localStorage` and
   `clab.homeTab`, `clab.notice.<key>` in `sessionStorage`. Kept, and said so in the dialog: Network design drafts
   (`clab.design.draft.<lab>`, "that draft exists nowhere else", `shell.js:248`), lab builder drafts and templates
   (`clab-builder:*`, "never on the manager", `docs/LAB-BUILDER.md:94`), the Try again request (`clab.request.<job>`), a
   save being sent (`git-save-request:<lab>`), the builder's return marker (`op-return`) and the consumed `activeLab`.
   Two steps in the dialog: the button reveals a confirm row that says exactly what changes, including that the
   warnings the student closed come back and their labs read *Needs attention* again, and that the tab-scoped items
   change in this tab only (§5.3); a `role="status"` result; every read and write in try/catch; the whole thing lives in
   `shell.js` (the storage rule) behind two functions the dialog calls.
10. **The dialog tells the truth about what is not stored.** The folder chooser's open branches belong to the student
    and are remembered per lab and repository (invariant), but today only in memory (`drwOpenBranches`,
    `save-drawers.js:524-527`): a reload forgets them. The dialog says "kept while this page is open; not stored", and
    §8 lists persisting them as an open question for the saving stream, not for this chunk. Reduced motion, more
    contrast and forced colours are followed from the system (`style.css:2302-2335`) and the manager stores nothing
    for them; the dialog shows each as on or off and says where it comes from. Appearance is light only, by the owner's
    decision; the dialog says so in one line rather than offering a disabled dark toggle.
11. **Storage states are three, detected once per open, and only *blocked* disables Reset**: *blocked* (reading
    `window.localStorage` throws, as Firefox does with site data blocked), *cannot store* (reads work, a probe write
    fails: Safari's private window, or a store the lab builder's drafts have filled, where `removeItem` still works) and
    *normal*. Blocked: the inventory is replaced by one sentence and Reset is disabled with its reason. Cannot store:
    the inventory shows, only the text-size select is disabled, with the sentence `This browser is not letting the page
    store anything new (storage full or read-only).`, and Reset runs and reports its own count. The probe key
    `clab.probe` is removed at once and never listed.
12. **The one new page script is `preferences.js`** (the two dialogs' behaviour and the pure markup function), listed in
    `index.html` with `?v=<release>`; `shell.js` gains the storage and `matchMedia` helpers it calls; `home.js` gains the
    filter; `status.js` gains `textMatch`; `app.js` loses two inline matchers and gains one line that hides the guide
    item. No new document-level listener outside `shell.js` (pinned by a source test).

## 2. The Manager menu (`index.html`, `app.js`, optional `main.py`)

### 2.1 Markup

After `#manager-settings` and before the Diagnostics anchor:

```html
<button type="button" role="menuitem" id="manager-preferences">Browser preferences…</button>
<hr class="menu-sep" role="separator">
<button type="button" role="menuitem" class="menu-group-toggle" id="manager-help-toggle" data-menu-group="manager-help" aria-expanded="false" aria-controls="manager-help"><span>Help</span><svg class="icon" width="16" height="16" aria-hidden="true"><use href="#i-chevron"></use></svg></button>
<div class="menu-group" id="manager-help" data-menu-panel role="group" aria-labelledby="manager-help-toggle" hidden>
  <button type="button" role="menuitem" id="manager-shortcuts">Keyboard shortcuts…</button>
  <a role="menuitem" id="help-student-guide" href="/student-guide" target="_blank" rel="noopener noreferrer" hidden>Student quick start (PDF) <span aria-hidden="true">↗</span></a>
  <a role="menuitem" id="help-containerlab" href="https://containerlab.dev/" target="_blank" rel="noopener noreferrer">containerlab documentation <span aria-hidden="true">↗</span></a>
  <a role="menuitem" id="help-lab-examples" href="https://containerlab.dev/lab-examples/lab-examples/" target="_blank" rel="noopener noreferrer">Lab examples <span aria-hidden="true">↗</span></a>
  <a role="menuitem" id="help-kinds" href="https://containerlab.dev/manual/kinds/" target="_blank" rel="noopener noreferrer">Device kinds and their images <span aria-hidden="true">↗</span></a>
  <a role="menuitem" id="help-srl-labs" href="https://github.com/srl-labs" target="_blank" rel="noopener noreferrer">srl-labs lab repositories on GitHub <span aria-hidden="true">↗</span></a>
</div>
<a role="menuitem" href="/static/debug.html">Diagnostics</a>
```

Order inside Help: the dialog first (it works offline), the guide (hidden until §2.3 says it exists), then the three
containerlab.dev pages, then GitHub. The lab-examples and kinds pages are the two places a student is sent when a
topology names a kind or an image they do not know; "vendor image notes" (R101) has no page in this repository, so the
kinds page of containerlab.dev stands in (each kind page documents its image). The four `https://` targets are
assumptions verified by the builder with one `curl -I` each at build time (not in tests: CI has no network promise).

`render()` (`app.js`) gets one line next to the version line: `if($('help-student-guide'))$('help-student-guide').hidden=!state.student_guide;`.
A hidden `<a>` is skipped by `items()` (`shell.js:88`: `!item.hidden`), so the arrow keys never land on it.

### 2.2 Behaviour (all existing, no new code in `shell.js` for the menu)

Open the menu (click, Enter, Space or ArrowDown on the button): every group is collapsed (`open` at `shell.js:101`).
Help: click, Enter, Space or ArrowRight expands it and moves focus to Keyboard shortcuts…; ArrowLeft collapses it and
returns focus to the toggle; ArrowDown/ArrowUp/Home/End rove across the visible items only. Escape closes the menu and
returns focus to the Manager button. A click on a Help link closes the menu (capture phase), focus returns to the button
and the link opens its new tab; a click on Keyboard shortcuts… or Browser preferences… closes the menu the same way and
then the item's own handler (`preferences.js`) opens the dialog with `showModal()`.

### 2.3 The student guide route (slice S0: the plumbing ships, the PDF is not staged)

- `clab-backup-ui/guide/.keep` (committed, empty) and a `.gitignore` line `clab-backup-ui/guide/*.pdf`; `Dockerfile`
  gains `COPY guide/ ./guide/` after `COPY VERSION ./VERSION` (the folder always exists, so a hand build never fails).
  `.dockerignore` excludes `*.md`, not `*.pdf`.
- `deploy/start-manager.sh`, just before `docker compose … build`: `rm -f "$repo_dir/clab-backup-ui/guide/"*.pdf`, so
  the staging folder never carries a copy from an earlier run and the image mirrors the decision of this release. **No
  `install` line in this chunk** (lead's decision, §9 [0], [5]): the staging line, when the owner has supplied a
  revised guide, is `install -m 644 "$repo_dir/docs/student-quick-start/<name>.pdf" "$repo_dir/clab-backup-ui/guide/"
  2>/dev/null || echo 'Student guide PDF not found in docs/student-quick-start; the Help menu will not offer it.'`,
  placed after the `rm -f` so the folder always mirrors `docs/student-quick-start/`. The file is 2.8 MB (`ls -l`); a
  staged copy is ignored by Git and root-owned in the checkout like other files this root script writes.
- `main.py`: `GUIDE_NAME = 'Containerlab_Node_Manager_Student_Quick_Start.pdf'`; `guide_path()` returns the first of
  `APP.parents[1]/'docs'/'student-quick-start'/GUIDE_NAME` (a checkout: the tracked copy wins over any staged one, so the
  fixture manager and the tests serve what Git has) and `APP.parent/'guide'/GUIDE_NAME` (the image:
  `/opt/nos-backup/guide`) that `is_file()`, else `None`; computed once in `create_app` into `app.state.student_guide`.
  `/api/state` adds `'student_guide': app.state.student_guide is not None`. `GET /student-guide` →
  `FileResponse(path, media_type='application/pdf', headers={'Content-Disposition': f'inline; filename="{GUIDE_NAME}"'})`
  so the browser's viewer opens it in the new tab; with no file, `HTTPException(404, 'The student guide is not
  installed on this manager. Ask your instructor for the quick start PDF.')`. A fixed path, no client input, a GET page
  outside `/api/` exactly as `/vm-connection-guide` (`main.py:487`); the middleware's `Cache-Control: no-store` and the
  other headers apply unchanged.
- Consequence: an installed manager (the image) has no file and hides the item; a checkout (the fixture, the tests)
  has the tracked PDF and shows it, which is what the route tests and the fixture check need. The item's label and the
  route stay as designed; when the owner supplies a revised guide, enabling the staging line is the whole change.

## 3. Keyboard shortcuts dialog (`index.html`, `preferences.js`, `style.css`)

`<dialog id="shortcuts-dialog" aria-labelledby="shortcuts-title">` with `<div class="dialog-head"><h2
id="shortcuts-title">Keyboard shortcuts</h2><button type="button" class="icon-button close" aria-label="Close">×</button></div>`,
one sentence (`Everything here can also be done with the mouse. Escape closes a menu, a panel or a dialog and returns
focus to where you were. On macOS, Alt is Option; on the Edit map page Cmd works for undo and redo. Ctrl+Insert has no
Mac equivalent: use Copy selection.`), then one `<section>` per group with an `<h3>` and a
`<dl class="kv shortcuts">` whose `<dt>` holds `<kbd>` keys and whose `<dd>` says what happens. Static text; nothing is
interpolated. `#manager-shortcuts` → `showModal()` when not open. Contents, each row verified:

| Group | Keys | What happens | Code |
|---|---|---|---|
| Menus (Manager ▾, Lab actions ▾, the map's More ▾) | ArrowDown on the button | Opens the menu and focuses its first item | `shell.js:104` |
| | ArrowDown, ArrowUp, Home, End | Move between items (wrapping) | `shell.js:113-116` |
| | ArrowRight, ArrowLeft | Open and close a group such as Advanced options or Help | `shell.js:108-112` |
| | Escape | Closes the menu, focus returns to its button | `shell.js:106` |
| | Tab | Leaves the menu (it closes) | `shell.js:107` |
| Tabs (Topology · Devices · Tools · Advanced; Recent labs · All labs) | ArrowLeft, ArrowRight, Home, End | Move between tabs and show the tab | `app.js:371-375`, `home.js:93` |
| Home cards, the lab switcher's entries, the labs under Labs found on the VM… | Shift+F10 or the Menu key on an entry | Opens that lab's actions (the ⋯ button does the same); on a hidden lab, its Hidden lab menu | `home.js:90`, `operations.js:877`, `management.js:304` |
| Topology map | Tab | Reaches each device and each link | `topology.js` (focusable nodes and wires) |
| | Enter or Space | Opens the focused device; on a link, opens Capture traffic for that link | `topology.js:22`, `capture.js:194` |
| | Shift+F10 or the Menu key on a device | Opens the device menu | `topology.js:105` |
| | ArrowDown, ArrowUp, Home, End in the device menu | Move between its actions | `topology.js:107` |
| | Escape | Closes the device menu, then any open menu or panel, then the expanded map | `topology.js:111`, `shell.js:184-192` |
| Save chip panel and Load panel | Escape | Closes the panel, focus returns to its button; Tab moves through it | `shell.js:159`, `:124` |
| Folder chooser (Save location) | ArrowDown, ArrowUp, Home, End | Move between folders without selecting | `git-places.js:251-254` |
| | ArrowRight | Opens a closed folder, or moves into an open one | `git-places.js:255-258` |
| | ArrowLeft | Closes an open folder, or moves to its parent | `git-places.js:259-262` |
| | Enter or Space | Selects the focused folder | `git-places.js:263` |
| | A letter | Moves to the next folder whose name starts with it | `git-places.js:265-269` |
| Terminal page (Open CLI ↗, Console ↗) | Alt+ArrowUp, Alt+ArrowDown, Alt+0 | Larger, smaller and default text size | `terminal.js:149-162` |
| | Alt+T | Moves to the terminal tools | `terminal.js:149` |
| | ArrowLeft, ArrowRight, Home, End in the terminal tools | Move between the tools | `terminal.js:141-146` |
| | Ctrl+Insert | Copies the selection | `terminal.js:153` |
| Edit map page | Ctrl+Z | Undoes the last change (not while typing in a field) | `map-editor-page.js:205-208` |
| | Ctrl+Shift+Z or Ctrl+Y | Redoes it | same |
| Lab builder, the YAML panel | Ctrl+Enter (Cmd+Enter) | Applies the YAML to the drawing | `lab-builder-yaml.js:103-105` |
| | Escape | Closes the panel when it has no unapplied change (otherwise a warning says so) | `lab-builder-yaml.js:108-111` |

Not listed, on purpose, each an explicit exclusion in the reverse pin of §6: Previous and Next device in the device
panel (buttons, no key, `app.js:547`); the embedded editor's canvas keys (its own, version-bound, not the manager's
claim); the lab switcher as a `details` element (Escape closes it, `shell.js:190`, the first sentence); the Escape
handlers themselves (`shell.js:269`, `topology.js:111`, `shell.js:159`, the first sentence); the builder's new-lab name
field (`lab-builder-page.js:323`: Enter submits a form field, a browser default); the save drawer's and chip panel's
`keydown` delegates (`save-drawers.js:1020`, `save-header.js:667`: they carry the folder chooser rows above and Enter on
a form control). A new key behaviour added later must add its row here or name its exclusion, or the reverse pin fails.

`style.css`: `kbd{font:12px/1.4 var(--mono);padding:1px 5px;border:1px solid var(--line-strong);border-bottom-width:2px;border-radius:4px;background:var(--surface-2);white-space:nowrap}`,
`.shortcuts dt{display:flex;flex-wrap:wrap;gap:4px;align-items:center}`. The `.kv` grid already wraps to one column in
the 520 px drawer; the builder confirms it at 390 in the fixture pass (no horizontal scroll: `scrollWidth <= innerWidth`).
The Manager menu itself gets the scroll rule `#lab-actions-menu` has (`style.css:635`): `#manager-menu-list {
max-height: calc(100vh - 120px); overflow-y: auto; overscroll-behavior: contain; }`, because with Help expanded the
list (11 items, Browser preferences…, the toggle, six Help items, two separators and the two-line footer) is about
830 px and hangs from the sticky top bar, which the page's own scroll cannot bring into view; the fixture check reads
Diagnostics and the footer inside the viewport or the scrolled list at 390 × 844 and 1366 × 768 (§6).

## 4. Home lab filter (`index.html`, `status.js`, `app.js`, `home.js`, `style.css`)

### 4.1 Markup (inside `#home-labs`, between `#home-tab-note` and `#lab-cards`)

```html
<div class="home-list-tools" id="home-filter-row" hidden>
  <label for="home-filter">Find a lab</label>
  <input id="home-filter" type="search" autocomplete="off" placeholder="Name, state or device…">
  <button type="button" class="button secondary small" id="home-filter-clear" hidden>Clear</button>
  <span class="caption" id="home-filter-count"></span>
</div>
```

and after `#lab-cards`: `<p class="table-empty home-filter-empty" id="home-filter-empty" hidden></p>` (visible text, not
live) and `<p class="sr-only" id="home-filter-live" role="status" aria-live="polite"></p>` (the one live region: always
present, never hidden, empty when there is nothing to say; §4.3). A visible `<label>` (the Devices search has only
`aria-label`; the lead asked for a visible one here and the row has the room).
`.home-list-tools{display:flex;flex-wrap:wrap;gap:8px 12px;align-items:center;margin:8px 0 12px}` with the input
`flex:1 1 220px;min-width:0`; at 390 px the label, the field, Clear and the count wrap onto two lines.

### 4.2 The matcher (`status.js`)

```js
// The one text matcher of the Devices search (app.js) and the Home filter (home.js): a trimmed, case-insensitive
// substring of the joined non-empty parts. An empty term matches everything. No wildcards (C03 §1.9).
function textMatch(term,parts){const t=String(term||'').trim().toLowerCase();if(!t)return true;return (parts||[]).filter(p=>p!==undefined&&p!==null&&p!=='').map(String).join(' ').toLowerCase().includes(t);}
```

`app.js:290` and `:322` become `lab.nodes.filter(n=>textMatch(term,[n.name,n.address,platformLabel(n.platform)]))` with
`term=$('search').value` (no `.toLowerCase()` of its own). The only behavioural change for Devices is the trim: a
trailing space typed into the search no longer hides every device.

### 4.3 `home.js`

- `homeFilterTerm()` → `$('home-filter')?.value||''` (the harness's elements carry `value`).
- `homeLabMatch(lab, ls, term)` (pure, tested) → `{match, device}`: the trimmed lower-cased term is a **substring** of
  the lab name (`textMatch(term,[lab.name])`), or **equals the whole state word** (`ls.label.toLowerCase()===t`:
  `running` matches *Running* and not *Not matched to a running lab*; `stopped` does not match *Some devices stopped*;
  the label changes on every poll, so an exact word is the only stable use of it), or is a substring of a device's
  short name (`textMatch(term,[n.short_name||n.name])`; `device` is the first such name). Hidden labs are already
  excluded before this runs: hiding is a different feature and stays so.
- `renderHome()`: `term`, `matches=labs.map(l=>({lab:l,...homeLabMatch(l,homeLabState(l),term)})).filter(m=>m.match)`;
  the cards are `homeOrder(matches.map(m=>m.lab), tab)` (the order is the tab's, unchanged); a card matched through a
  device name only (not by name or state) gets a small caption under its times line, `has device <name>` (escaped, in
  `homeCard` through an optional second argument), so a card never appears for a reason the student cannot see;
  `cards.hidden=!matches.length`.
- The row: `row.hidden = !loaded || (labs.length<2 && !term && !focused)` where `focused` is
  `typeof document!=='undefined' && row.contains(document.activeElement)` (focus anywhere inside `#home-filter-row`:
  the field or Clear): a filter above a single card is noise, but a control that has focus or a value is never hidden
  under the student's hands (a lab removed while they type; Clear pressed with one lab).
- `#home-filter-clear.hidden = !term`; `#home-filter-count.textContent = term ? `${matches.length} of ${labs.length}
  labs` : ''` (visible text, not live).
- `#home-filter-empty`: shown only when `term && labs.length && !matches.length`, `textContent` = `No lab matches
  “<term>”. Try part of a lab name, a state such as Running, or a device name.` (textContent, so the term needs no
  `esc()`); visible text, **not** a live region.
- The live region `#home-filter-live`: one `role="status"` element that is never hidden. `homeFilterAnnounce()` is
  scheduled by the input handler with a 500 ms timer (`homeFilterTimer`, cleared on every keystroke) and writes one
  sentence without the term: `3 of 7 labs shown` or `No lab matches. Try part of a lab name, a state or a device name.`;
  an empty term writes `''`. The poll never writes it (only the input handler and Clear schedule it), so a screen
  reader hears one sentence per pause in typing, never one per keystroke and never one per poll.
- Wiring in the `if($('home'))` block: `$('home-filter').oninput=()=>{renderHome();homeFilterSchedule();}` and
  `$('home-filter-clear').onclick=()=>{const f=$('home-filter');f.value='';if(typeof f.focus==='function')f.focus();renderHome();homeFilterSchedule();}`
  (focus first, then render: with one lab the row stays visible because the field inside it has focus).
- `#home-labs` keeps `hidden=!loaded||!labs.length`, so with labs and no match the row and the empty sentence stay
  visible while the cards are hidden; `#home-tab-note` keeps the tab's note.

### 4.4 States

Default: no filter, the row shows with two or more labs. Typing: cards narrow on each keystroke, the count reads
`3 of 7 labs`, Clear appears; half a second after the last keystroke the live region says `3 of 7 labs shown`. No
match: cards hidden, the visible sentence with the term, Clear; the live region says the no-match sentence once. A
device-name match: the card carries `has device r1`. Cleared (Clear, or the field's own ✕ where the browser draws
one): all cards, count and sentence gone, the live region emptied, focus in the field (with one lab too). Across the
4-second poll: the field, its value, caret and focus are untouched (static element; `setMarkup` rewrites only
`#lab-cards`, and only when the markup changed). Leaving Home and coming back: the field keeps its text for the page's
lifetime, like the Devices search; a reload clears it; nothing is stored or routed (§1.7). One lab and an empty field:
the row is hidden. Loading: the row is hidden until `state.loaded`. Escape in the field: not handled by the page
(Chromium and WebKit clear a `type=search` field natively; `shellEscape` runs and closes nothing); no new key.

## 5. Browser preferences dialog (`index.html`, `shell.js`, `preferences.js`, `style.css`)

### 5.1 What the pages store today (verified by `grep -n 'localStorage\|sessionStorage' app/static/*.js *.html`)

| Key | Where written | Meaning in the dialog | Scope | Reset |
|---|---|---|---|---|
| `clab.terminal.fontSize` | `terminal.js:17-20,86` | Terminal text size (11–18 px, default 14) | this browser | yes, and editable |
| `clab.opened.<lab id>` | `shell.js:195` | When you last opened each lab (the *Last opened* line on Home cards) | this browser | yes |
| `clab.dismissed.<job id>` | `shell.js:201` | Job warnings you closed | this browser | yes |
| `clab.design.draft.<lab id>` | `shell.js:227-237` | Unsaved Network design drafts: the only copy | this browser | **no** (discard on the Network design card) |
| `clab-builder:draft:<id>` | `lab-builder-page.js:117-129` | Lab builder drafts: the only copy until saved to the VM | this browser | **no** (Drafts… in the lab builder) |
| `clab-builder:templates`, `clab-builder:templates-version` | `lab-builder-page.js:183-192` | Your device templates in the lab builder's palette | this browser | **no** |
| `react-topoviewer-grid-line-width`, `react-topoviewer-grid-style`, `contextPanelSide` | the committed editor bundle (`app/static/lab-builder/assets/c-TPSDO2KM.js`: `jn`, `Mn`, `Sn`, each with a `setItem`), on `lab-builder.html` and `map-editor.html` | Editor view: grid style, grid line width, which side the editor's panel opens on | this browser | yes |
| `mui-mode`, `mui-color-scheme-light`, `mui-color-scheme-dark` | the bundle's MUI storage code (`modeStorageKey:"mui-mode"`, `colorSchemeStorageKey:"mui-color-scheme"` with `-light`/`-dark`); whether the adapter ever writes them is not verified, so they are matched by exact name and counted only when present | Editor colour mode (the editor is light by the adapter's `applyThemeVars("light")`, `main.tsx:269`) | this browser | yes |
| `clab.capture.<lab id>.<scope>`, `clab.capture.openas` | C07 (`C07-DESIGN.md` §1.7, through `shell.js`), when it lands | Remembered capture choices: the interfaces ticked per device and link, and the last *Open as* choice | this browser | yes |
| `clab.homeTab` | `shell.js:197-198` | The Home list tab (Recent labs or All labs) | this tab | yes |
| `clab.notice.<key>` | `shell.js:205-206` | Notices you closed with × | this tab | yes |
| `activeLab` | `app.js:102`, `operations.js:517,640`, `management.js:167,284` | The lab that was open, for a reload (read once, then removed) | this tab | not needed (consumed on load) |
| `clab.request.<job id>` | `shell.js:211-216` | The request behind *Try again* on a failed operation | this tab | **no** |
| `git-save-request:<lab id>` | `git-progress.js:164-170` | A save being sent (removed when the manager answers) | this tab | **no** |
| `op-return` | `operations.js:540-541` | Where to return after publishing from the lab builder (read once) | this tab | **no** |

Not stored at all, and said so: the folder chooser's open branches (memory only, `save-drawers.js:524-527`); the Home
filter (§4); the Devices search; reduced motion, more contrast and forced colours (system settings the stylesheet
follows at `style.css:2302`, `:2308`, `:2320`). The builder's `clab-builder:probe` is read, never written
(`lab-builder-page.js:180`), and is not a key. The first version of this table came from a grep of `app/static/*.js`
only and missed the editor bundle's keys (§9 [2], [11]); two pins in §6 now keep it complete: every key literal stored by
a non-vendor script must match a family, and the editor's literals are read out of the committed bundle.

### 5.2 `shell.js` additions (the storage rule: every `window`, `localStorage` and `matchMedia` touch lives here)

```js
// Browser preferences (preferences.js): the manager's own keys by family, so the dialog can list them and Reset can
// clear exactly the preferences. Drafts and in-flight requests are data, never cleared here.
// The exact keys the committed editor bundle writes (app/static/lab-builder/assets, clab-ui 0.3.2) plus MUI's mode keys;
// a test reads the literals out of the bundle, so a pinned upgrade that renames one fails the test, not the dialog.
const EDITOR_VIEW_KEYS=['react-topoviewer-grid-line-width','react-topoviewer-grid-style','contextPanelSide','mui-mode','mui-color-scheme-light','mui-color-scheme-dark'];
const PREFERENCE_FAMILIES=[
 {kind:'localStorage',match:k=>k==='clab.terminal.fontSize',id:'terminal-font',reset:true},
 {kind:'localStorage',match:k=>k.startsWith('clab.opened.'),id:'opened',reset:true},
 {kind:'localStorage',match:k=>k.startsWith('clab.dismissed.'),id:'dismissed',reset:true},
 {kind:'localStorage',match:k=>k.startsWith('clab.design.draft.'),id:'design-drafts',reset:false},
 {kind:'localStorage',match:k=>k.startsWith('clab-builder:draft:'),id:'builder-drafts',reset:false},
 {kind:'localStorage',match:k=>k==='clab-builder:templates'||k==='clab-builder:templates-version',id:'builder-templates',reset:false},
 {kind:'localStorage',match:k=>EDITOR_VIEW_KEYS.includes(k),id:'editor-view',reset:true},
 {kind:'localStorage',match:k=>k.startsWith('clab.capture.'),id:'capture',reset:true},
 {kind:'sessionStorage',match:k=>k==='clab.homeTab',id:'home-tab',reset:true},
 {kind:'sessionStorage',match:k=>k.startsWith('clab.notice.'),id:'notices',reset:true},
 {kind:'sessionStorage',match:k=>k==='activeLab',id:'active-lab',reset:false},
 {kind:'sessionStorage',match:k=>k.startsWith('clab.request.'),id:'requests',reset:false},
 {kind:'sessionStorage',match:k=>k.startsWith('git-save-request:'),id:'save-requests',reset:false},
 {kind:'sessionStorage',match:k=>k==='op-return',id:'op-return',reset:false}];
function shellStorageKeys(kind){try{const s=window[kind],out=[];for(let i=0;i<s.length;i++){const k=s.key(i);if(k!==null)out.push(k);}return out;}catch{return null;}}   // null: blocked
function shellStorageWritable(kind){return shellSet(kind,'clab.probe','1')&&shellRemove(kind,'clab.probe');}
// {blocked, writable, families:[{id, kind, reset, count, keys}], terminalFont}. Keys are counted, never shown.
function preferenceInventory(){...}
// Removes every key of a reset:true family; {cleared, blocked}. Never touches a reset:false family.
function resetPreferences(){...}
function mediaMatches(query){try{return !!(window.matchMedia&&window.matchMedia(query).matches);}catch{return false;}}
const TERMINAL_FONT_SIZES=[11,12,13,14,15,16,17,18],TERMINAL_FONT_DEFAULT=14;   // equal to terminal.js FONT_SIZES/FONT_DEFAULT; a test reads both files
function terminalFontPreference(){const v=Number(shellGet('localStorage','clab.terminal.fontSize'));return TERMINAL_FONT_SIZES.includes(v)?v:TERMINAL_FONT_DEFAULT;}
function setTerminalFontPreference(value){const v=Number(value);return TERMINAL_FONT_SIZES.includes(v)&&shellSet('localStorage','clab.terminal.fontSize',String(v));}
```

`preferenceInventory()` lists keys once per kind and matches each against the families in order (a key matching no
family is not counted; the forward pin of §6 makes sure no key the manager's own scripts write can be such a key);
`blocked` is true when `shellStorageKeys('localStorage')` is `null`; `writable` is the probe's answer and governs the
text-size select only. `resetPreferences()` removes the matched keys of the `reset:true` families through `shellRemove`
and counts successes (removal works on a full store); a blocked store yields `{cleared:0, blocked:true}`.

### 5.3 The dialog

`<dialog id="preferences-dialog" aria-labelledby="preferences-title">` with the house head (`h2` "Browser preferences",
the × `.close`), one sentence `What this browser remembers for the manager. Nothing here is sent to the manager or
shared with other browsers.`, `<div id="preferences-body"></div>` and, outside the body so a text change announces,
`<p id="prefs-status" class="caption" role="status"></p>`. `#manager-preferences` → empties `#prefs-status` (a sentence
from the last visit must not greet the next one), `prefsRender()`, then `showModal()`.
`prefsRender()` writes `prefsMarkup(inventory, display, font)` (pure, tested) into the body. Sections:

1. **Terminal**: `<label for="pref-terminal-font">Terminal text size</label><select id="pref-terminal-font">` with the
   eight sizes, `14 px (default)` marked; `onchange` → `setTerminalFontPreference(v)`; success → `#prefs-status`
   `Terminal text size <n> px. Applies to terminals opened from now on; open terminals keep theirs.`; failure (read-only
   storage) → the select reverts and the status reads `This browser does not let the page keep this setting.`. The
   terminal page reads the key when it loads (`terminal.js:22`), so no live update is promised.
2. **Remembered in this browser**: a `dl.kv` with one row per `localStorage` family: *Terminal text size* (`16 px` or
   `default (14 px)`), *Last opened times* (`for n labs`), *Closed warnings about failed operations* (`n`), *Editor
   view* (`n settings`: grid style, grid line width, panel side, colour mode, in the lab builder and Edit map),
   *Remembered capture choices* (`for n devices and links`, present once C07 lands; the row reads `none` until then),
   then a sub-heading *Kept by Reset*: *Network design drafts* (`n · discard them on the Network design card`), *Lab
   builder drafts* (`n · Drafts… in the lab builder`), *Lab builder templates* (`yes`/`none`).
3. **Remembered in this tab**: *Home list tab* (`Recent labs`/`All labs`/`default`), *Closed notices* (`n`); *Kept by
   Reset*: *Try again requests* (`n`), *A save being sent* (`n`), *Return to the lab builder* (`yes`/`no`), *The lab that
   was open* (`yes`/`no`, read once at load).
4. **Not stored**: one line: `The open folders of the save chooser and the Home filter are kept only while this page is
   open.`
5. **Display settings the manager follows** (from your system or browser; the manager stores nothing): *Reduced motion*
   on/off (`mediaMatches('(prefers-reduced-motion: reduce)')`), *More contrast* (`(prefers-contrast: more)`), *Forced
   colours* (`(forced-colors: active)`); then `Appearance: light. The terminal page is dark by design; there is no dark
   mode setting.`
6. **Reset**: `<div class="dialog-actions"><button type="button" class="button secondary" id="prefs-reset">Reset browser
   preferences…</button></div>` and a hidden `<div id="prefs-reset-confirm" class="banner warn" role="group"
   aria-label="Confirm reset">` holding, with the counts from the inventory: `In this browser this forgets the terminal
   text size, the Last opened times of <n> labs, the editor view settings, the remembered capture choices, and which
   warnings about failed operations you closed (<n> warnings): those warnings show again and their labs read Needs
   attention until you close them again. In this tab only, it forgets the Home list tab and the closed notices; other
   open tabs keep theirs. Drafts, templates and Try again requests are kept.` (a family with nothing stored is left out
   of the sentence; with nothing to clear at all the sentence is `Nothing is stored for the manager in this browser.`
   and Reset is still allowed: it reports `0 items`). `[Keep]` (`#prefs-reset-keep`, `.button.secondary`) and `[Reset]`
   (`#prefs-reset-go`, `.button.danger`; `.dialog-actions .danger{order:10}` puts it last). `#prefs-reset` reveals the
   row and focuses **Keep**; Keep hides it and focuses `#prefs-reset`; Reset calls `resetPreferences()`, re-renders the
   body, focuses `#prefs-reset` and writes `#prefs-status`: `Browser preferences reset: <n> items cleared. Terminals
   opened from now on use the default text size.` (`1 item` singular; `0 items` when nothing was stored). The
   `dismissedSet()` effect is real and named: `labFailure()` returns again the newest failed or interrupted job of each
   lab whose warning was closed, so Home cards and lab headers read *Needs attention* and the banners come back.

States. *Blocked*: the body is one sentence `This browser does not let the page read or keep its storage (a private
window, or site data blocked). Nothing is remembered between visits, so there is nothing to show or reset.` plus the
display section (it needs no storage); Reset is disabled with `title` and a visible `.menu-reason`-style caption `Not
available: storage is blocked in this browser.`; the select is absent. *Cannot store* (the probe write failed): the
inventory shows; only the text-size select is disabled, with the caption `This browser is not letting the page store
anything new (storage full or read-only).`; Reset stays enabled (removal works on a full store) and reports its own
count. *Normal*: as above. The dialog never fetches, never writes an event, never touches the Store (pinned: `preferences.js` contains no
`fetch(`, `api(` or `json(` and no `document.addEventListener`). Width: `dialog` is `min(680px, calc(100vw - 32px))`;
the `dl.kv` rows wrap at 390 as in the drawer.

## 6. Tests

- `tests/test_status_ui.js`: `textMatch`: empty, blank and missing term match; case; a trailing space trims; `null`
  and `''` parts skipped; the substring spans a joined boundary only through the single space.
- `tests/test_readiness_ui.js` (the `appHarness` with `status.js` + `app.js`): the Devices list and technical table use
  `textMatch` (`R1` finds `r1`, an address and a platform label still match, `'r1 '` with a trailing space matches,
  "No devices match. Try another name, address or platform." and "This lab has no devices yet." keep their words);
  `render()` hides `#help-student-guide` without `state.student_guide` and shows it with `true`.
- `tests/test_home_ui.js` (its harness: `$('home-filter')` carries `value`; `textMatch` comes from `status.js`, already
  loaded): a term narrows by name (substring), by the whole state word (`running` matches a *Running* lab and **not**
  an unlinked lab whose label is *Not matched to a running lab*; `stopped` does not match *Some devices stopped*) and
  by a device's short name (the card then carries `has device r1`, escaped); the count caption; the visible empty
  sentence with the term and Clear shown, cards hidden; the live region is empty right after a keystroke and holds `3
  of 7 labs shown` or the no-match sentence (without the term) after the 500 ms timer (fake timers), and `''` after
  Clear; Clear focuses the field before rendering and with one lab the row stays visible; the same element and value
  survive two `renderHome()` calls and `_markup` is unchanged when nothing changed; the row hidden with one lab and an
  empty field, shown with two labs, shown with one lab and a term, shown while focus is on Clear; hidden labs stay out
  whatever the term; the order is the tab's; lab names in cards still escaped (existing test kept).
- `tests/test_shell_ui.js`: (a) `index.html` static test: after `#manager-settings` come `#manager-preferences`, a
  separator, `#manager-help-toggle` with `data-menu-group="manager-help"`, the `#manager-help` panel with exactly
  `manager-shortcuts`, `help-student-guide` (hidden, `href="/student-guide"`), `help-containerlab`, `help-lab-examples`,
  `help-kinds`, `help-srl-labs`; every `https://` item carries `target="_blank"` and `rel="noopener noreferrer"`; the
  Diagnostics anchor is the last item; the two dialogs exist with `aria-labelledby`, a `.close` and (preferences)
  `#preferences-body` and `#prefs-status[role=status]`; `#home-filter-row` holds the labelled input, Clear and the
  count, `#home-filter-empty` has no live role and `#home-filter-live` is the one `role="status"` of the filter;
  `preferences.js` is listed once with `?v=`; no `src="http` or `href="http` in a `<script>`, `<link>` or `<img>` of
  any page; `style.css` gives `#manager-menu-list` the same `max-height`/`overflow-y` rule as `#lab-actions-menu`. (b)
  The harness's Manager list gains the Help toggle and panel; the group test of line 153 is run on it (toggle never
  closes the menu, collapsed items skipped, ArrowRight opens, reopening collapses). (c) `preferenceInventory()` on a
  seeded storage: one key per family, counts right, `blocked:false`, `writable:true`, a foreign key `other.thing` not
  counted, `clab.probe` absent afterwards; with `throwStorage`: `blocked:true`, empty families; with a storage whose
  `setItem` throws `QuotaExceededError` while `getItem`/`removeItem` work: `blocked:false`, `writable:false`. (d)
  `resetPreferences()`: seeded with every family (including `react-topoviewer-grid-style`, `contextPanelSide`,
  `mui-mode`, `clab.capture.l.node:r1`, `clab.capture.openas`), removes exactly the `reset:true` keys, leaves
  `clab.design.draft.l`, `clab-builder:draft:x`, `clab-builder:templates`, `clab.request.j`, `git-save-request:l`,
  `op-return`, `activeLab`; returns the count; blocked → `{cleared:0,blocked:true}`; on the quota-throwing store the
  removals still count. (e) `terminalFontPreference()` default 14, a stored `16` → 16, a stored `9` or `abc` → 14;
  `setTerminalFontPreference(19)` false and nothing written. (f) `mediaMatches` with and without `matchMedia`, and when
  it throws. (g) Source pins: no `'?'` key test in `shell.js` or `preferences.js`; `preferences.js` contains no
  `document.addEventListener`, `window.addEventListener`, `localStorage`, `sessionStorage`, `fetch(`, `api(`, `json(`;
  `TERMINAL_FONT_SIZES` and `TERMINAL_FONT_DEFAULT` in `shell.js` equal `FONT_SIZES` and `FONT_DEFAULT` in `terminal.js`
  (both read by regex). (h) **Forward storage pin**: every key literal passed to `shellSet`, `shellGet`,
  `shellRemove`, `setItem`, `getItem` or `removeItem` in non-vendor `app/static/*.js` (a string literal, a
  `'prefix.'+x` concatenation taken by its prefix, or `BUILDER_PREFIX+'…'` resolved through the constant) matches a
  `PREFERENCE_FAMILIES` entry; `clab.probe` is the one named exception; the test fails naming the key, so C07's
  `clab.capture.*` and any later key must join a family. (i) **Bundle pin**: the test reads
  `app/static/lab-builder/assets/*.js`, collects every identifier bound to a string that is then passed to
  `localStorage.setItem` (`jn="react-topoviewer-grid-line-width"` and the `setItem(jn,` call, likewise `Mn`, `Sn`) and
  the `modeStorageKey`/`colorSchemeStorageKey` literals, and asserts each is in `EDITOR_VIEW_KEYS` (`mui-color-scheme`
  with its `-light`/`-dark` suffixes), so an editor upgrade (C11) that renames a key fails here. (j) **Reverse
  shortcut pin**: the test lists every `addEventListener('keydown'` and `.onkeydown=` in non-vendor `app/static/*.js`
  (today: `app.js:388`, `capture.js:194`, `home.js:90,93`, `lab-builder-page.js:323`, `lab-builder-yaml.js:131-132`,
  `management.js:304`, `map-editor-page.js:205`, `operations.js:877`, `save-drawers.js:1020`, `save-header.js:667`,
  `shell.js:104,105,159,269`, `terminal.js:141` and its `attachCustomKeyEventHandler`, `topology.js:22,105,107,111`) and
  requires each `<file>:<line>` to appear either in a `data-source` attribute of a shortcuts row in `index.html` or in
  the dialog's exclusion list (`SHORTCUT_EXCLUSIONS` in `preferences.js`, each with its reason from §3), so C06 and C07
  must add their rows or their exclusions when they land.
- `tests/test_preferences_ui.js` (new; the `test_operations_ui.js` harness shape with a fake `$`, `esc`, stubs for
  `preferenceInventory`, `resetPreferences`, `mediaMatches`, `terminalFontPreference`, `setTerminalFontPreference`):
  `prefsMarkup` renders every row of §5.3 with its count words (`for 3 labs`, `1 item`, `n settings`), the two *Kept by
  Reset* groups, the display rows on/off, the appearance line; the blocked body (one sentence, no select, Reset
  disabled with the caption); the cannot-store body (select disabled with the full-store sentence, Reset enabled); no
  stored value other than the font size and the Home tab word is ever interpolated (keys and ids never appear).
  Behaviour: opening empties `#prefs-status` then calls `showModal` (a stale sentence from the last visit is gone); the
  select's change writes through the stub and sets the status sentence, a failed write reverts the select and sets the
  other sentence; the reset flow: the confirm row appears with the counts and the *Needs attention* clause, and Keep
  gets focus; Keep hides it and focuses `#prefs-reset`; Reset calls the stub once, re-renders, focuses `#prefs-reset`,
  and the status reads the count; `SHORTCUT_EXCLUSIONS` lists each excluded `<file>:<line>` with a reason.
- `tests/test_page_load_ui.js`: `preferences.js` loads in the shared context; `prefsMarkup`, `prefsRender`, `textMatch`,
  `preferenceInventory`, `resetPreferences` exist once the page is loaded; no name collision (the existing test).
- `tests/test_student_guide.py` (new, S0; `create_app` + `httpx`): `/api/state` carries `student_guide` true in the
  checkout (the PDF exists under `docs/student-quick-start/`) and false with `guide_path` patched to `None`; `GET
  /student-guide` answers `application/pdf` with an inline `Content-Disposition` naming the file, and 404 with the
  sentence when absent; the response carries `Cache-Control: no-store`; the route is a GET and writes no `api.request`
  event (`events.jsonl` unchanged across a call); `guide_path()` with both a `docs/` copy and a `guide/` copy present
  (a temporary tree) returns the `docs/` one. `deploy/start-manager.sh`: `bash -n`, and a text test in the existing
  deploy-script suite (`test_install_manager.py` or its sibling, stdlib only) that the script contains the `rm -f` of
  `clab-backup-ui/guide/*.pdf` before the compose build and no `install` of the PDF (the staging line is enabled only
  with the owner's revised guide).
- `tests/test_release_consistency.py` / `verify-release.py`: unchanged; `preferences.js` carries `?v=` because the test
  above pins it and `set-release.py` moves it.
- Fixture pass (`clab-ui-qa`, `/clab-slice-verify` with `ui: true`, Chromium and Firefox as in C02): a new
  `docs/parity-campaign/tools/check_c09.py` modelled on `check_ui008b.py` (`CLAB_BASE`, a fresh `FIXTURE_DATA`), at
  1440 × 900, 760 × 1024 and 390 × 844: (1) Manager ▾ → ArrowDown → End → ArrowUp → ArrowRight opens Help and focuses
  Keyboard shortcuts…; Enter opens the dialog; Escape closes it and `document.activeElement.id === 'manager-button'`;
  (2) the four external items carry `target`/`rel`; `help-student-guide` is visible (the fixture runs from the checkout)
  and `page.request.get('/student-guide')` answers 200 `application/pdf` (skipped with a note when S0 is not built);
  (3) Home: type `bgp` → only matching cards, the count caption; wait `POLL + 0.5 s` → the field still has focus and
  its text, and `#home-filter-live` reads `n of m labs shown`; type `zzz` → no cards, the visible sentence with “zzz”,
  Clear, the live sentence without the term; Clear → all cards, focus in the field, the live region empty; then with a
  fixture state of one lab (`POST /fixture/switch`): type a term, click Clear, `activeElement.id === 'home-filter'` and
  the row still visible; a device-name term (`PE1`) shows the card with `has device PE1`; (4) Browser preferences…: the
  rows render; change the text size to 16 and read `localStorage['clab.terminal.fontSize'] === '16'`; seed
  `clab-builder:draft:x`, `clab.opened.a` and `react-topoviewer-grid-style` through `evaluate`, Reset… → the confirm
  sentence names the counts → Keep → nothing changes; Reset… → Reset → the status sentence, `clab.opened.a` and the
  grid key gone, `clab-builder:draft:x` kept; close and reopen → `#prefs-status` empty; (5) a context with
  `add_init_script` making `window.localStorage` throw → the blocked sentence and Reset disabled; one making `setItem`
  throw a `QuotaExceededError` → the select disabled with the full-store sentence and Reset enabled; (6) at every
  viewport `document.documentElement.scrollWidth <= innerWidth` with each dialog open and the Manager menu open with
  Help expanded; (7) vertical: at 390 × 844 and 1366 × 768 with Help expanded, End moves focus to Diagnostics and its
  `getBoundingClientRect().bottom` lies within the viewport (the list scrolled it into view), and the footer's version
  line is reachable by scrolling the list; screenshots per viewport. `docs/redesign/tools/verify_after.py` is re-run unchanged (its viewports are
  1920/1440/1366 and its Home and Manager menu pins must keep passing); it is not extended. CI: the lead appends
  `tests/test_preferences_ui.js` to the `node --test` line and `-p test_student_guide.py` to the Python list.

## 7. Documentation

- `docs/LAB-OPERATIONS.md` "Where the commands are": the Manager ▾ sentence reads *… holds the actions that are not
  about one lab: **Deploy a new lab…**, **Running labs on the VM…**, **Operation history…**, **Manager settings…**,
  **Browser preferences…**, and a **Help** group (Keyboard shortcuts…, the student quick start when the manager carries
  it, and the containerlab documentation, lab examples, device kinds and srl-labs pages, which open in a new tab).* A
  new section after "Diagnostics: logs, interfaces, inspect and images", **"Help, keyboard shortcuts and browser
  preferences"**: the Home filter (a lab name or device name by part, a state by its whole word; a card matched by a
  device name says so; kept only while the page is open and never stored); the shortcuts dialog (lists only keys the
  manager binds; no `?` key, in one sentence: it is a character in every field and differs by keyboard layout);
  Browser preferences (the table of §5.1 in prose: what is remembered, including the editor's view settings and the
  remembered capture choices; what Reset forgets, in the confirm row's own words, with the sentence that closed
  warnings come back and their labs read Needs attention again, and that the tab-scoped items change in this tab only;
  what it keeps; the three storage states, with Reset disabled only when storage is blocked; nothing is sent to the
  manager); the guide item (hidden until the owner supplies a guide for the current release; the route is in place).
- `docs/TOUR.md` line 19: the Manager ▾ sentence adds *browser preferences and Help*.
- `docs/INSTALL.md`: not edited in this chunk (nothing is staged). When the owner's revised guide lands, one sentence
  in the start-manager step says the script copies it from `docs/student-quick-start/` into the image.
- `docs/student-quick-start/`: **not edited** (owner's scope).
- `docs/parity-campaign/README.md` and `PARITY.md` (the lead applies): the C09 row and the R101 row record that R101
  (per-kind image guidance at the point where an image is reported missing) is **not pursued in this campaign** and
  that the Help group's kinds link is a pointer to containerlab.dev, not R101's counterpart; R102 keeps its "lead
  decides" status from PARITY.md.
- `CLAUDE.md` (the lead): the frontend file list in "Frontend: three different things" names `preferences` after
  `home`; the routing row "Home, menus, Devices tab, shell, status vocabulary" lists `test_preferences_ui.js` and
  `check_c09.py`.

## 8. Build slices, acceptance checks, assumptions, dead ends, refusals, what to attack

| Slice | Owner | Files (disjoint) | Size |
|---|---|---|---|
| S0 student guide route (the plumbing; the PDF is not staged) | `clab-backend-engineer` for `main.py` and the test; `clab-devops-engineer` for `start-manager.sh` (the `rm -f` line) and the Dockerfile; `risk-reviewer` on the diff (`main.py` and a root deploy script) | `clab-backup-ui/app/main.py`, `clab-backup-ui/Dockerfile`, `clab-backup-ui/guide/.keep` (new), `deploy/start-manager.sh`, `clab-backup-ui/tests/test_student_guide.py` (new), the deploy-script text test; the lead: `.gitignore` | S (about 25 lines, 70 of tests) |
| S1 shell and menu | `clab-ui-builder` | `app/static/index.html` (the menu items, the two dialogs' static markup with `data-source` on each shortcuts row, the Home filter row and live region, the `<script>` line), `shell.js` (§5.2 with `EDITOR_VIEW_KEYS`), `style.css` (`kbd`, `.shortcuts`, `.home-list-tools`, the `#manager-menu-list` scroll rule), `tests/test_shell_ui.js` (with the forward storage pin, the bundle pin and the reverse shortcut pin) | M (about 100 lines of code and markup, 220 of tests) |
| S2 Home filter and the matcher | `clab-ui-builder` (a second worker, in parallel; starts from the ids of §4.1) | `status.js`, `app.js`, `home.js`, `tests/test_status_ui.js`, `tests/test_home_ui.js`, `tests/test_readiness_ui.js` | S (about 60 lines, 150 of tests) |
| S3 preferences and shortcuts script | `clab-ui-builder` (a third worker; starts from §3 and §5.3 and the `shell.js` function names of §5.2) | `app/static/preferences.js` (new, with `SHORTCUT_EXCLUSIONS`), `tests/test_preferences_ui.js` (new), `tests/test_page_load_ui.js` | M (about 130 lines, 160 of tests) |
| S4 docs | `docs-auditor`, after S1–S3 land | `docs/LAB-OPERATIONS.md`, `docs/TOUR.md`, `docs/INSTALL.md` (with S0) | S |
| S5 fixture check | `clab-ui-qa` within `/clab-slice-verify` | `docs/parity-campaign/tools/check_c09.py` (new) | S |
| Lead | release records, CI lists, `.gitignore`, `CLAUDE.md`, `?v=` through `set-release.py`, `/clab-review-changes` | | |

Contracts between slices: the ids of §2.1, §3, §4.1 and §5.3; the `shell.js` names `preferenceInventory`,
`resetPreferences`, `mediaMatches`, `terminalFontPreference`, `setTerminalFontPreference`, `PREFERENCE_FAMILIES`,
`TERMINAL_FONT_SIZES`, `TERMINAL_FONT_DEFAULT`; `textMatch(term, parts)` in `status.js`; `state.student_guide`. S2 and
S3 can run on a `test_shell_ui.js`-style fake DOM before S1 lands; `test_page_load_ui.js` (S3) passes only once S1's
`index.html` lists the script, so S3's final run follows S1.

Acceptance checks for `/clab-slice-verify`:

S0: `PATH="$PWD/.venv/bin:$PATH" .venv/bin/python -m unittest discover -s tests -t tests -p test_student_guide.py -v`,
`bash -n deploy/start-manager.sh`, then: (1) `/student-guide` takes no input and serves one fixed path; (2) the route is
not under `/api/` and writes no event; (3) a build without the PDF succeeds (`COPY guide/` finds `.keep`); (4)
`state.student_guide` is false when the file is absent and the item is hidden; (5) `start-manager.sh` removes staged
copies and stages nothing, so an installed manager hides the item; (6) in a checkout the tracked `docs/` copy wins over
a staged one.

S1: `node --test tests/test_shell_ui.js tests/test_page_load_ui.js`, `node --check app/static/shell.js`, then: (1) every
Manager menu pin of `verify_after.py` still holds (open across a poll, Escape returns focus); (2) the Help group
collapses on every open and its items are skipped by the arrows while collapsed; (3) every external item has
`target="_blank" rel="noopener noreferrer"`; no foreign `src`/`href` on a script, stylesheet or image anywhere; (4)
`resetPreferences()` never removes a `reset:false` key (seed every family and diff), and removes the editor view and
capture keys; (5) a blocked store makes every helper return its empty or false value without throwing, and a
quota-throwing store leaves `blocked` false; (6) no inline style, no `document`-level listener added; (7) the three
source pins (forward storage, bundle, reverse shortcut) pass against the tree as it stands; (8) `#manager-menu-list`
scrolls (the rule is present and the fixture's vertical check holds).

S2: `node --test tests/test_status_ui.js tests/test_home_ui.js tests/test_readiness_ui.js tests/test_download_ui.js`,
then: (1) the Devices search claims are unchanged apart from the trim; (2) the filter element is never rebuilt
(`renderHome()` twice: same object, same value); (3) the visible sentence contains the term as text, not markup, and
the live sentence never contains it; (4) hidden labs stay out; (5) the row is never hidden while focus is inside it or
it has a value, and Clear with one lab leaves focus in the field; (6) nothing of the filter reaches `location`,
`history` or storage (grep `home.js`); (7) `running` does not match an unlinked lab; (8) the live region is written by
the timer only, never by the poll.

S3: `node --test tests/test_preferences_ui.js tests/test_page_load_ui.js`, `node --check app/static/preferences.js`,
then: (1) the script holds no `fetch(`, `api(`, `json(`, storage or `document.addEventListener` (the pins of §6); (2) the
confirm row's Reset is the only caller of `resetPreferences`; (3) the shortcuts dialog's rows each name a key the code
binds (the reviewer spot-checks against §3's table); (4) the status sentences match §5.3 verbatim; (5) focus lands on
Keep when the confirm row opens and on `#prefs-reset` after Keep or Reset; (6) `esc()` on the only interpolated values
(the font size number and the Home tab word) or none needed.

Fixture pass: §6's `check_c09.py` at the three viewports in Chromium and Firefox, `verify_after.py` re-run.

**Assumptions.** The four containerlab.dev and GitHub URLs of §2.1 resolve (the builder checks each with `curl -I`
once; a classroom without internet sees the browser's own error in the new tab, which the design accepts: the item
says `↗` and the docs say the links go outside). Native `<dialog>` focus restore in Chromium, Firefox and WebKit (the
fixture pass runs two of them). `window.matchMedia` exists (every supported browser; the helper tolerates its absence).
The `.kv` grid wraps at 390 px as it does in the 520 px drawer. The fixture manager runs from a checkout, so the guide
item is visible there. `FONT_SIZES` in `terminal.js` stays `[11..18]` (pinned by the two-file regex test).

**Dead ends removed.** A student with twelve labs scrolling cards to find one; no pointer from the manager to the
containerlab documentation, the lab examples or the kind pages; keyboard operation that existed but could not be
discovered; a terminal text size changeable only after opening a terminal; stale *Last opened* times and closed
warnings with no way to clear them; no place that says what this browser remembers. **Not removed in this chunk**: the
missing pointer to a student guide, because the only guide that exists teaches a removed tab (§1.3); the route is
ready for the day the owner supplies a current one.

**R101, vendor image notes (explicit record, §9 [13]).** Not pursued in this campaign. PARITY.md planned R101 as
per-kind guidance (how to obtain the vrnetlab, cJunosEvolved and cEOS images) shown where an image is reported *not
found* (the Images dialog, the review's "Images needing attention"); that needs a maintained table of vendor
procedures that this repository does not have and that the owner has not asked for. The Help group's *Device kinds and
their images* link is a pointer to containerlab.dev's kind pages, not R101's counterpart: it does not answer at the
point where an image is missing. The lead records the same in README.md's C09 row and PARITY.md's R101 row.

**Refusals, each with its wording.** `/student-guide` without the file: 404 `The student guide is not installed on this
manager. Ask your instructor for the quick start PDF.`; Reset with blocked storage: disabled, `Not available: storage
is blocked in this browser.`; Reset and the size select with read-only storage: disabled, `This browser lets the page
read its stored preferences but not change them.`; a failed size write: `This browser does not let the page keep this
setting.`; a size outside 11–18: `setTerminalFontPreference` returns false and writes nothing (the select offers only
the list). Kept: the filter refuses nothing (an empty term shows everything); Reset never removes a draft; the student
guide is not edited; dark mode is not added.

**What to attack.** For `risk-reviewer`: the reset set is exact (`clab.opened.` with the dot cannot catch a
`clab.openedX`; `clab-builder:draft:` and `clab.design.draft.` are `reset:false`; a key matching no family is left
alone); the probe key is removed in the same call; nothing in `preferences.js` reaches the network or the Store;
`/student-guide` is a GET page outside `/api/` with a fixed server-side path (as `/vm-connection-guide`), no query, no
client-named file, `no-store`; `start-manager.sh` writes one root-owned ignored file into the checkout and tolerates its
absence; `COPY guide/` cannot fail; the external anchors carry both `noopener` and `noreferrer` and CSP is untouched;
the menu closes and refocuses before the browser follows a `target=_blank` link (capture phase, no `preventDefault`).
For `clab-ui-reviewer`: the Help group costs one keystroke and collapses on every open (consistent with Advanced
options: is that the right trade for a 17-item menu at 390 px?); every row of the shortcuts table names code that
exists, and the omissions (Previous/Next, the editor's canvas) are stated; the `?` decision; the filter's
hidden-with-one-lab rule and the never-hide-while-focused clause; the empty sentence names the three things it matches;
the count caption is not live and the empty sentence is; the Preferences dialog says plainly what is not stored (open
folders, the filter) and offers no dead dark-mode control; Reset's confirm row names exactly what goes and what stays
and focuses Keep first; "applies to terminals opened from now on" is true (`terminal.js:22` reads at load); the
Diagnostics item stays last; the three dialogs' 390 px layouts.

**Open questions for the lead or the owner.** (1) **Owner question, to be raised before the guide is ever served:**
the student quick start PDF (`docs/student-quick-start/`, byline "tested with manager release 1.30.35",
`VALIDATION.md:6,10`) teaches the saving flow that release 1.31.0 removed. Two of its steps as they stand:
`guide.md:163` *"On the Progress tab, find **Starting state** and click its **Apply to running lab…**."* and
`guide.md:426-427` *"In the manager, open `my-first-lab` → **Progress** tab → **Connect a repository by URL**."* There is
no Progress tab (`PANELS` is `topology, devices, tools, advanced`; saving is in the lab header). Does the owner reopen
the guide's scope and supply a guide written for 1.31.x? Until then the Help item stays hidden on every installed
manager (§1.3, §2.3). (2) The folder chooser's open branches are memory-only today; persisting them (`localStorage`,
one key per lab and repository, through `shell.js`) belongs to the saving stream (`docs/git-redesign/DESIGN.md` binds)
and would then join the Preferences inventory. (3) Whether Escape in the Home filter should clear it (this design
leaves Escape to menus and dialogs).

**Lead's decisions on the open questions** (as amended after the design review, §9): S0 ships as plumbing only: the
route, the `student_guide` flag and the hidden item; `start-manager.sh` removes staged copies and does **not** stage the
PDF, because the guide teaches the removed Progress tab (this reverses the first decision, which was to serve the guide
as it is); the owner question above is raised before any guide is staged; persisting the folder chooser's open branches
stays with the saving stream (not this chunk); Escape in the Home filter does not clear it (Escape stays with menus and
dialogs, as designed).

## 9. Review answers

One row per confirmed finding of `/clab-design-review` (16 confirmed: 2 must-fix, 12 should-fix, 2 optional; the 7
refuted items need no row), in the review's order; R = `risk-reviewer`, U = `clab-ui-reviewer`. The lead's decisions
on each are binding and are the dispositions below.

| # | Finding | Answer | Where |
|---|---|---|---|
| 0 | R, must-fix: S0 would serve a guide built around the Progress tab, which no longer exists | Accepted with change (lead's decision, reversing the earlier one): S0 keeps the route, the `student_guide` flag and the hidden item; `start-manager.sh` does not stage the PDF, so every installed manager hides the item; the owner question quotes two stale steps (`guide.md:163`, `:426-427`) and is raised before the guide is ever staged | §1.3, §2.3, §8 dead ends and open question (1), lead's note |
| 1 | R, should-fix: an old staged PDF is never removed; the script's message becomes false | Accepted: `rm -f "$repo_dir/clab-backup-ui/guide/"*.pdf` before the (future) install line; `guide_path()` prefers the tracked `docs/` copy in a checkout; both pinned (a deploy-script text test; a two-copy path test) | §2.3, §6 `test_student_guide.py`, §8 S0 checks (5), (6) |
| 2 | R, should-fix: the preferences list misses the keys the embedded editor writes | Accepted: an *Editor view* family over the exact literals the committed bundle writes (`react-topoviewer-grid-line-width`, `react-topoviewer-grid-style`, `contextPanelSide`) and MUI's `mui-mode`, `mui-color-scheme-light/-dark`, `reset:true`, as `EDITOR_VIEW_KEYS`; a bundle pin reads the literals out of `app/static/lab-builder/assets/*.js` | §1.8, §5.1 table, §5.2, §5.3 row, §6 (i) |
| 3 | R, should-fix: a full store is treated as read-only and Reset is disabled although removal works | Accepted (lead's decision): Reset is disabled only when storage is blocked; a failed write probe disables the text-size select alone, worded `This browser is not letting the page store anything new (storage full or read-only).`; Reset reports its own count; a quota-throwing store is tested | §1.11, §5.2, §5.3 states, §6 (c), (d), fixture (5) |
| 4 | R, should-fix: the Reset confirmation misstates what changes | Accepted (lead's decision, with [10]): the confirm row says exactly what changes, with counts, that closed warnings show again and their labs read Needs attention, and that the Home tab and notices change in this tab only while other tabs keep theirs; LAB-OPERATIONS.md agrees | §1.9, §5.3 item 6, §7 |
| 5 | U, must-fix: the Help item would serve a guide built around UI that 1.31.0 removed | Accepted with change (lead's decision, with [0]): the route, the flag and the hidden item ship; the PDF is not staged; the owner's answer is recorded in §8 when it comes | §1.3, §2.3, §8 |
| 6 | U, should-fix: with Help expanded the Manager menu can run past the viewport and nothing scrolls it | Accepted (lead's decision): `#manager-menu-list` gets `#lab-actions-menu`'s rule (`max-height: calc(100vh - 120px); overflow-y: auto; overscroll-behavior: contain`); the fixture check reads Diagnostics and the footer inside the viewport or the scrolled list at 390 × 844 and 1366 × 768 | §3 last paragraph, §6 (a) and fixture (7), §8 S1 check (8) |
| 7 | U, should-fix: Clear loses focus when the student has a single lab | Accepted (lead's decision): `focused` means focus inside `#home-filter-row` (`row.contains(document.activeElement)`), and Clear focuses the field before rendering; a one-lab fixture step pins it | §4.3 row rule and wiring, §4.4, §6 test and fixture (3), §8 S2 check (5) |
| 8 | U, should-fix: substring matching on the state word gives wrong and unstable results | Accepted (lead's decision): the state matches by whole-label equality, case-insensitive; lab and device names by substring; a card matched through a device name alone carries `has device <name>`; `running` not matching an unlinked lab is pinned | §1.7 (unchanged intent), §4.3 `homeLabMatch`, §4.4, §6, §8 S2 check (7) |
| 9 | U, should-fix: the filter's live-region behaviour is the opposite of what §4.3 promises | Accepted (lead's decision): one always-present `role="status"` element (`#home-filter-live`), written once about 500 ms after the last input with `3 of 7 labs shown` or the no-match sentence without the term; the visible count and the visible empty sentence keep their form outside the live region; the poll never writes it | §4.1, §4.3 live region, §4.4, §6, §8 S2 checks (3), (8) |
| 10 | U, should-fix: Reset brings back Needs attention on labs and the confirmation does not say so | Accepted (lead's decision, with [4]): the confirm row says the warnings show again and their labs read Needs attention until closed again, with the count of closed warnings; the `dismissedSet()`/`labFailure()` effect is named in the design | §5.3 item 6, §7 |
| 11 | U, should-fix: the inventory misses the editor's own keys and C07's planned keys, and nothing would catch the next one | Accepted (lead's decision, with [2]): the *Editor view* family and a *Remembered capture choices* family (`clab.capture.` prefix, C07 §1.7), both `reset:true`; a forward pin fails on any key literal a non-vendor script stores outside the families | §1.8, §5.1, §5.2, §5.3, §6 (h) |
| 12 | U, should-fix: the shortcuts table leaves out keys that exist and gets one wrong | Accepted (lead's decision): rows added for Enter/Space and letter jump in the folder chooser, the terminal toolbar's arrows and Home/End, Shift+F10 on the lab switcher's entries and the excluded labs, the YAML panel's Ctrl+Enter and Escape; the link row now reads "opens Capture traffic for that link" and cites `capture.js:194`; a reverse pin maps every `keydown` listener in non-vendor scripts to a row's `data-source` or to `SHORTCUT_EXCLUSIONS` with its reason | §3 table and exclusions, §6 (j), §8 S1 check (7) |
| 13 | U, should-fix: R101 is dropped without the record the design claims | Accepted (lead's decision): an explicit R101 entry in §8 (not pursued in this campaign, with the reason; the kinds link is a pointer, not R101's counterpart) and the README/PARITY note for the lead to apply | §8 R101 paragraph, §7 last bullet |
| 14 | U, optional: the macOS sentence is wrong for the terminal chords | Accepted as proposed: `On macOS, Alt is Option; on the Edit map page Cmd works for undo and redo. Ctrl+Insert has no Mac equivalent: use Copy selection.` | §3 intro sentence |
| 15 | U, optional: the Preferences status sentence carries over to the next opening | Accepted as proposed: the open handler empties `#prefs-status` before `showModal()`; pinned in `test_preferences_ui.js` and the fixture check | §5.3 open handler, §6, fixture (4) |

## 10. Verification answers (`/clab-slice-verify` on `claude/c09-int` at e398842, six workers; the fixture passes at 1440, 760 and 390 in Chromium and Firefox)

| Finding | Answer | Where |
|---|---|---|
| Medium: Escape cleared the Home filter in both browsers (a `type=search` input clears itself) | Accepted: the input's own keydown prevents the default on Escape; Clear stays the only way to empty it | §4.4; `home.js` |
| Medium: the Reset confirmation was 668 px tall at 760 and 390 and pushed the buttons down | Accepted: one short paragraph with the counts and a collapsed "What exactly" (110 px at 1440 and 760, 130 px at 390; the buttons in view at 390×844) | §5.2; `preferences.js` |
| Low: the student-guide `render()` line from §2.1 was missing, so the item could never show once the guide is served | Accepted: added with tests for hidden, shown and hidden again | `app.js`, `test_readiness_ui.js` |
| Low: four stale `SHORTCUT_EXCLUSIONS` cites, and the reverse pin never checked that an exclusion or a row cites a real keydown site | Accepted: the stale entries dropped, the cites refreshed, the pin now requires a keydown site at every cited line (the folder-chooser rows cite their `case` lines) | §3, §6; `preferences.js`, `test_shell_ui.js` |
| Low: a whitespace-only term showed the count and Clear | Accepted: trimmed once in `renderHome` | §4.1 |
| Low: a double-click on Clear at 390 dropped focus to the body | Accepted: the field keeps one line with Clear and takes its place when it hides; a mousedown guard keeps focus in the row | §4.1; `style.css` |
| Low: an out-of-range stored terminal size was misreported | Accepted: the same clamp as the terminal page (a pinned claim rewritten: '' and '9' read 11) | §5.1; `shell.js` |
| Low: "1 of 1 labs"; a long term overflowing at 390; stale cards after Reset; the dialogs' columns cramped at 390 and misaligned across sections | Accepted: pluralised, `overflow-wrap: anywhere`, `render()` after a reset, one shared label column and one column at 420 px and narrower | §4.3, §5.2; `style.css` |
| Review: the visible Reset confirmation no longer said that closed warnings come back and their labs read *Needs attention* (both clauses were only in the collapsed details), nor that some items change in this tab only | Accepted: §1.9 holds again; the short paragraph adds one sentence for the closed warnings and one for the tab-scoped items, only when they apply (exact strings pinned) | `preferences.js`, `test_preferences_ui.js` |
| `verify_after.py` fails one pre-existing device-menu order check (Console, Stop and Start device were added by C04 and C05) | Not a C09 defect: the tool's expectation is refreshed by the lead with the next release that touches it | `docs/redesign/tools/verify_after.py` |

## 11. The deferred full branch review (campaign 2, A02, 2026-10-27)

The two full reviewer passes on the 1.31.5 → 1.31.6 diff (C06-DESIGN §13 has the method and the whole table). C09
rows: **U3** (should-fix, fixed): Find's Enter and Escape get their "Topology map" rows in the shortcuts dialog, and
the reverse pin in `test_shell_ui.js` now also catches `'keydown'` passed as an argument (the `on(…)` helper form).
**R7** (low, amended here): §9 rows 0–1 say a `/student-guide` route, a `student_guide` state flag, `guide_path()`,
`test_student_guide.py` and an installer `rm -f …/guide/*.pdf` shipped. They did not: outside `docs/` only
`index.html` and `app.js` carry the hidden Help item and the shell and readiness tests pin it hidden. The backend half
of S0 was deferred; campaign 2's D10 regenerates the guide from its sources and restores the Help entry with the route
and its test in the same release. **A07** (the stale device-menu order in `verify_after.py`, §10) is a campaign 2
chunk. The reviewer answers VALIDATION cites as "C09-DESIGN §11" are the §9/§10 sections above (the cite was off by
one; this section is the campaign 2 review).
