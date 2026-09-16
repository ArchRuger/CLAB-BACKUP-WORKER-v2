# Feasibility and regression-risk critique of DESIGN-SPEC.md

Lens: can the spec be implemented on the real `index.html` / `app.js` / `management.js` / `operations.js` / `git-progress.js` / `topology*.js` without breaking wiring, the 13 JS harnesses (now 14 with `test_status_ui.js`; baseline `node --test tests/*.js` = 101 pass / 0 fail) or the 4 s poll. Everything below was checked against the actual source (line numbers are from the files as of 2026-09-16, branch `claude/junos-live-restore-and-git-destinations`; `status.js` + `test_status_ui.js` already exist untracked, so spec step 1 is effectively done).

**Score: 5 / 10.** The IA and the id-preservation rule are right, and most of the spec is implementable. But six items are blockers as written: they would either throw at load (killing every handler registered after the throw), break the two `app.js` harnesses (13 tests) at `vm.runInContext` time, or wire buttons to nothing. All of them have cheap fixes; none requires changing the IA.

---

## A. Findings, most severe first

### A1 — BLOCKER · §1.3 "Tabs" · the legacy `showTab` loop does not "keep working" for nested sections
**What the spec claims.** "the legacy sections `#inventory-view`, `#git-view`, `#backups-view`, `#credentials-view`, `#logs-view` keep their ids and are nested inside the new panels (so `for(name of […]) $(name+'-view').hidden=…` keeps working)".
**What the code does.** `app.js:93` — `for(const name of ['inventory','topology','credentials','backups','logs','git'])if($(name+'-view'))$(name+'-view').hidden=name!==tab;`. With `tab='advanced'` every legacy section is hidden (`'credentials'!=='advanced'`), so Credentials and Action logs both disappear inside the Advanced panel; with `tab='tools'`, `#backups-view` is hidden inside Tools. The loop is *the* thing that must be rewritten, not the thing that keeps working.
**Second-order break.** `refresh()` (`app.js:16`) auto-refreshes logs only when `tab==='logs'`; the `[data-tab]` click handler (`app.js:103`) and `handleDownload` (`app.js:133`) do the same. If `showTab` normalises `logs→advanced`, `tab` is never `'logs'` again and the "Refreshed every four seconds" promise printed in `#logs-view` silently stops being true.
**Fix.**
```js
const PANELS=['topology','devices','progress','tools','advanced'];
const LEGACY={inventory:'devices',git:'progress',backups:'tools',credentials:'advanced',logs:'advanced'};
let devicesTechnical=false, scrollTarget='';
function showTab(value){
 const legacy=LEGACY[value]; if(legacy){ if(value==='inventory')devicesTechnical=true; scrollTarget=value==='backups'?'backups-view':value==='logs'?'logs-view':value==='credentials'?'credentials-view':''; value=legacy; }
 tab=value;
 for(const name of PANELS){const el=$(name+'-view');if(el)el.hidden=name!==tab;}
 if($('inventory-view'))$('inventory-view').hidden=!devicesTechnical;   // nested sub-state, not derived from tab
 document.querySelectorAll('[data-tab]').forEach(b=>{…active/aria-selected as today…});
 if(tab==='topology'&&typeof refreshMap==='function')refreshMap();
 if(tab==='progress'&&typeof gitShowRepository==='function')gitShowRepository();
 if(tab==='advanced'&&!$('logs-view')?.hidden)refreshLogs().catch(()=>{});
 if(scrollTarget){$(scrollTarget)?.scrollIntoView({block:'start'});scrollTarget='';}
}
```
and change the three `tab==='logs'` checks to a helper `logsVisible()` = `tab==='advanced'`. Keep every legacy section un-hidden inside its panel except `#inventory-view`, which follows `devicesTechnical`. Tests: none assert `showTab`; add it to the new `test_shell_ui.js` (legacy names map, `inventory` turns the technical view on, `advanced` refreshes logs).

### A2 — BLOCKER · §4 "app.js" row · hash routing, `closeMenus`, localStorage and `status.js` calls in `app.js` break both app.js harnesses at load
**Evidence.** `tests/test_download_ui.js:7-14` and `tests/test_readiness_ui.js:4-13` create a context with `document={getElementById,querySelectorAll,createElement,body}`, `sessionStorage`, timers, `URL`, `URLSearchParams`, `Blob`, `console` — **no `window`, no `location`, no `history`, no `localStorage`, no `document.addEventListener`, and `status.js` is not loaded**. `app.js` is executed top to bottom at load. Any of the following at top level throws a `ReferenceError`/`TypeError` and fails all 13 tests in those two files before a single assertion runs:
- `window.addEventListener('hashchange',…)` / reading `location.hash` on load (spec: "read on load and `hashchange`");
- `document.addEventListener('click'|'keydown',…)` for the shared `closeMenus(except)` helper (spec §3 "Menus");
- `localStorage.getItem('clab.lastLab')` (spec §1.2, "home.js" row says helpers live in home.js, but `refresh()`/`render()` in app.js are where the value is consumed);
- `nodeActions()` calling `deviceState(n)` for the new title/explanation (spec §1.3 Devices, §1.4): `test_readiness_ui.js:29-39` calls `nodeActions(...)` in a context where `deviceState` is undefined → `ReferenceError` → test 1 fails (and it is *the* CLI-gating test the brief names).
**Fix (pick one per item, all cheap).**
1. Put every `window`/`location`/`history`/`localStorage`/`document.addEventListener` use in a new `shell.js` (or `home.js`) that no existing harness loads, exposing `readRoute()`, `writeRoute()`, `closeMenus()`; `app.js` calls them through `typeof x==='function'&&x(...)` exactly as it already does for `renderManagement` (`app.js:51-53`). `app.js` keeps zero new top-level side effects.
2. Have both app.js harnesses load `status.js` first (like `test_git_places_ui.js:2-9` loads two sources) — a one-line harness change that preserves every behavioural claim — **and** keep a fallback in `nodeActions`: `const hint=typeof deviceState==='function'?deviceState(n).detail:sshHint(n)`.
3. Guard with `typeof localStorage!=='undefined'` + `try/catch` (private mode throws) wherever it is touched.
Add "app.js must load in `test_download_ui.js`'s context with no globals beyond today's" to the spec's non-negotiables; run `node --test tests/*.js` after every step, not just at the end.

### A3 — BLOCKER · §1.3 Lab actions menu / §1.3 Advanced · the whole lab-operations wiring hides behind `if($('import-top'))`, and `#lab-actions` is spec'd in two places
**Evidence.** `operations.js:276-284`:
```js
if($('import-top')){
 $('import-top').insertAdjacentHTML('beforebegin','<button … id="lab-actions" hidden>Lab actions ▾</button>');
 $('map-edit').onclick=…; if($('deploy-empty'))$('deploy-empty').onclick=openDeploy;
 $('lab-actions').onclick=()=>openLabOperations(); $('vm-projects').onclick=…; $('lab-start').onclick=…; $('lab-destroy').onclick=…; $('operations-history').onclick=…; $('inspect-all').onclick=…;
 $('labs').addEventListener('contextmenu',…); $('labs').addEventListener('keydown',…);
}
```
- `#lab-actions` is **created by JS**, immediately before `#import-top`. The spec moves `#import-top` into Advanced → Lab source, so the "Lab actions ▾" button will materialise inside the Advanced panel — which coincidentally is one of the two places the spec wants it (§1.3 Advanced "Lab operations: [All lab operations…] (`#lab-actions`)"), but the spec *also* puts "All lab operations…" (`#lab-actions`, existing id) inside the Lab actions ▾ menu. One id, two positions: impossible.
- If the agent drops or renames `#import-top` (spec §1.2 waffles: "keeps its id… simpler: … stays in the DOM on the lab page inside Advanced"), every handler in that block silently never attaches: Start lab, Destroy, Edit diagram, Manager ▾ items, Operation history, Running labs — no error, just dead buttons.
- The guard cannot simply be changed: `tests/test_operations_ui.js:79-84` (test 9) deliberately returns `null` for `import-top` so this block does not run; its element stub has `children/isConnected/textContent/append/replaceChildren` but **no `addEventListener`**, so guarding on any other id makes `$('labs').addEventListener` throw and test 9 fails.
**Fix.** (a) Put a static `<button id="lab-actions" class="…" hidden>` in `index.html` inside the Lab actions ▾ menu, and change line 277 to `if(!$('lab-actions'))$('import-top').insertAdjacentHTML(…)` (no-op in production, unchanged in the harness). (b) The Advanced panel gets a *different* button (`#lab-operations-all`) whose handler is `()=>openLabOperations()` — wired in the same block. (c) Keep `#import-top` in the DOM on the lab page (Advanced → Lab source, fixed label "Replace inventory…") so the guard is true; drop the "on Home its text is Deploy a new lab" idea (`app.js:49` and `management.js:111` both toggle it on `current()`; leave them). (d) Spec must say explicitly: "`#import-top` must exist at script load; do not move the wiring block's guard."

### A4 — BLOCKER · §1.3 / §4 index.html · ids the spec never mentions are written unguarded on every render or at init
**Evidence.**
- `app.js:48` `$('subtitle').textContent=…`, `app.js:50` `$('updated').textContent=…`, `app.js:43` `$('app-version').textContent=…` — the spec's shell (§1.1–1.3) has no `.page-heading` subtitle and never mentions the `<footer>` (`index.html:80`). Delete the elements and `render()` throws on the first poll and every 4 s thereafter; everything after line 43/48 (worker-state, lab-content, renderManagement, nodes, jobs, tabs) stops updating.
- `git-progress.js:316` `$('git-open-settings').onclick=gitOpenRepository;` sits inside the init block `if(typeof $==='function'&&$('git-progress-bar')){…}` (`:313-320`). The spec's status card (§1.3 Progress 1) lists `#git-progress-bar`, `#git-destination`, `#git-progress-status` but **not `#git-open-settings`** (the `<button>` that wraps `#git-destination`, `index.html:48`). Drop it and line 316 throws → lines 317-319 never run → **no `data-git-action` button in the header menu is wired** and the menu never closes on outside click. No console error is visible to the student; the Save ▾ menu is just dead.
- `renderGitProgress()` (`git-progress.js:45-58`) dereferences `#git-destination`, `#git-progress-status`, `#git-save-progress`, `#git-save-menu` unguarded and is called from `render()` **before** `if(!lab)return` (`app.js:53-54`), so a missing id kills `renderNodes/renderProfiles/renderJobs/showTab/refreshHealth` on every poll.
**Fix.** Add to §1.3 an explicit "load-bearing ids" list with owner and file:line: `#subtitle` (drop the line in `app.js:48` or keep `<p id="subtitle" hidden>`), `#updated` + `#app-version` (keep the footer — `test_release_consistency` also needs the `state.version||'1.29.0'` literal at `app.js:43`), `#git-open-settings` (keep it as the "Save location settings…" text button in the status card), plus the set already implied: `#labs #title #breadcrumb #worker-state #empty #lab-content #import-top #node-count #enabled-count #ready-count #schedule-summary #test #backup #inventory-caption #interval #search #nodes #profiles #jobs #details-* #node-history #log-* #map-* #topology-map #topology-view #node-context-menu #capture-* #git-*`. Rule for the agent: run `grep -o "\$('[a-z0-9-]*')" app/static/*.js | sort -u` and diff against `index.html` ids before publishing each step.

### A5 — BLOCKER · §1.3 Topology tab · state classes "from `deviceState(node)`" cannot be computed inside `topology-render.js`
**Evidence.** `topologyNode(n)` (`topology-render.js:20-27`) receives a *drawing* node from `/labs/{id}/topology` (`id, inventory_name, label, x, y, icon, …`) — it has no `nos_login`, `ssh_ready` or `available`. `topologyMarkup(drawing)` is pure and is (a) unit-tested in a context containing only `esc` (`tests/test_topology_ui.js`, 6 tests + `test_capture_ui.js` test 17): calling `deviceState` there is a `ReferenceError`; (b) reused by `opMapPreview` (`operations.js:252`) and the diagram editor (`diagram-editor.js:39`) where no lab state applies. Also `refreshMap()` only rewrites `map.innerHTML` when the drawing key changes (`topology.js:35-39`), so state must be applied without re-rendering — which §0.8 itself demands.
**Fix.** Keep `topologyNode` pure: always emit `<circle class="device-state-dot" …/>` (no state) — the existing regex tests still pass (`assert.match` on substrings). Add `renderMapState()` in `topology.js` (loaded after `status.js`), called from `render()` after `renderNodes()` and at the end of `refreshMap()`:
```js
function renderMapState(){const lab=current();if(!lab||!map)return;const byName=new Map(lab.nodes.map(n=>[n.name,n]));
 for(const g of map.querySelectorAll('[data-map-node]')){const s=deviceState(byName.get(g.dataset.mapNode));const key='state-'+s.key;if(g.dataset.state!==key){g.classList.remove(...[...g.classList].filter(c=>c.startsWith('state-')));g.classList.add(key);g.dataset.state=key;g.querySelector('title').textContent=s.detail;}}}
```
`classList` writes never disturb an open context menu or focus. `opMapPreview`/diagram editor stay untouched.

### A6 — BLOCKER · §1.3 Lab actions menu · `data-op-action=redeploy-cleanup` is not a backend action, and page-level `data-op-action` buttons have no handler
**Evidence.** `opCommand()`/`openLabOperations()` (`operations.js:18-21, 32-39`) express cleanup as `data-op-action="redeploy" data-op-options='{"cleanup":true}'` and only offer it when `opCaps.actions.redeploy.cleanup` is true; `opReview({action:'redeploy-cleanup'})` will be rejected by `/operations/preview`. The only place `[data-op-action]` clicks are handled is `dialog.querySelectorAll('[data-op-action]')` inside `openLabOperations` (`:36`); nothing listens on the page shell, so the spec's Stop/Restart/Redeploy menu items do nothing unless the agent invents wiring — and the spec's "wires each item to the same function the operations dialog buttons call" names no function and no gating (`opQuickActions`, `operations.js:255-259`, requires `opPath(lab)`, `discovery.connected`, a known status and `!busy()`).
**Fix.** Spec the menu items as `data-op-action="stop|restart|redeploy"` plus `data-op-options` (`{}` / `{"cleanup":true}` for the danger variant), and add to `operations.js`, inside the existing `if($('import-top'))` block:
```js
$('lab-actions-menu')?.addEventListener('click',e=>{const b=e.target.closest('[data-op-action]');if(!b||b.disabled)return;closeMenus();
 opTask(null,async()=>{const lab=current();if(!lab)return;try{await opCapabilities();}catch{opCaps=null;}
  await opReview({lab_id:lab.id,action:b.dataset.opAction,options:JSON.parse(b.dataset.opOptions||'{}')});});});
```
and extend `renderLabOperations()` to gate them from one place: `stop/restart` enabled when `quick.canDestroy && status∈{Running,Partially running}`; `redeploy` when `quick.canDestroy`; the cleanup item hidden until `opCaps?.actions?.redeploy?.cleanup===true` (fetch capabilities once on the first menu `toggle`). Reuse `opDestroyOptions()` for `#lab-destroy` as today (`opQuickRun`).

### A7 — MAJOR · §1.3 Header + Progress 1 · two `data-git-action` sets and a `#progress-save` proxy, but git-progress.js only knows about `#git-save-menu`
**Evidence.** `git-progress.js:56` disables only `$('git-save-menu').querySelectorAll('[data-git-action]')` while a save is active; `:317` wires only those; `gitRunAction` (`:301`) closes only `#git-save-menu`. The Progress tab's "More ▾" copies (`local, push, update, settings`) would stay enabled during a save (double `gitSaveOptions` → duplicate job / server 409 shown as a toast) and never close their menu. `#progress-save` "proxies `#git-save-progress`" but `renderGitProgress` sets `textContent/disabled/title` on `#git-save-progress` only (`:52-54`), so the Progress-tab button keeps saying "Save progress" and stays clickable while the header one says "Saving…"/disabled.
**Fix.** In `renderGitProgress`: `for(const b of document.querySelectorAll('#git-save-progress,#progress-save'))` mirror text/disabled/title; gate with `document.querySelectorAll('[data-git-action]')`; in the init block wire `document.querySelectorAll('[data-git-action]')` (only elements present at load — both menus are static markup, fine); `gitRunAction` calls `typeof closeMenus==='function'?closeMenus():($('git-save-menu')&&($('git-save-menu').open=false))`. Note the harnesses' `document.querySelectorAll` returns `[]` (`test_git_progress_ui.js` uses `$:()=>null`, so the init block does not run there) — no test impact.

### A8 — MAJOR · §1.3 Situational banner / §1.1 · `#operation-summary` inside `#lab-banner` puts two renderers on one element, and any innerHTML write to the header/banner kills open menus every 4 s
**Evidence.** `renderLabOperations()` (`operations.js:272`) writes `$('operation-summary').textContent` on every poll, guarded by `if($('operation-summary'))`. If `renderLabBanner()` rewrites `#lab-banner.innerHTML` (the natural way to render "exactly one of" several messages with action buttons), `#operation-summary` is destroyed on the first render and the guard makes the loss silent. Worse, if the header (`h1#title`, pills, `details#lab-actions-menu`, `details#git-save-menu`) or the banner is rendered via innerHTML, the 4 s `render()` closes any open `details` menu and drops focus — the exact race the task asked about; `renderGitProgress` and `renderLabOperations` already assume `#git-save-menu`/`#lab-start` are stable elements they mutate in place.
**Fix.** One owner: `renderLabBanner()` in app.js computes from `labState(lab, state)` + `progressState()` and only ever sets `textContent`, `className`, `hidden` on **static** children (`#lab-banner-text`, `#lab-banner-actions button[hidden]` per action: `#banner-start`→`$('lab-start').click()`, `#banner-output`→`opShowJob(op.id)`, `#banner-retry`→`gitPushPending()`, `#banner-credentials`→`showTab('credentials')`, `#banner-vm`→`openVmDialog()`, `#banner-link`→`$('link-deployment').click()`). Delete the `#operation-summary` write from `renderLabOperations` (keep the element as `hidden` `role=status` if you want the id; nothing in CSS/tests uses it). Add a hard rule to §0.8: "header, banner, tabs and menus are never re-rendered with innerHTML; only their text/attributes change."

### A9 — MAJOR · §4 app.js "hash routing" · loops, precedence and stale hashes are unspecified and the obvious implementation breaks Back
**Evidence.**
- `render()` calls `showTab(tab)` every 4 s (`app.js:66`). "write on selectLab/showTab/openDetails" with `location.hash=…` pushes a history entry per poll → Back button broken after a minute; with `history.replaceState` still fires `hashchange`? (no — `replaceState` doesn't fire it, but assignment does) → `hashchange` → `selectLab` → `render` → write → loop unless guarded.
- Precedence is undefined between `activeId=sessionStorage.getItem('activeLab')` (`app.js:4`), the hash, and Home. Journey 1 assumes `/` lands on Home, but a same-tab reload will restore the lab from sessionStorage.
- `management.js:169` (remove lab) and `:215` (manager reset) set `activeId=''` and `tab='inventory'` without touching a hash; the stale `#lab=<removed>` then re-selects nothing on `hashchange` but leaves a wrong URL, and a paste of that URL shows Home with no explanation.
- `openDetails` is closed from many places (`app.js:17,108,111`, `capture.js:91`, `management.js:169`) — the `device=` key can only be cleared reliably on the dialog's `close` event.
- Deep link `#device=RTR1` on load: `openDetails` → `renderDetails` → `current()` undefined → `$('details-dialog').close()` (`app.js:156`). Must wait for the first `/state`.
- `selectLab` hard-codes `tab='topology'` (`app.js:17`), so `#lab=x&view=progress` needs `selectLab(id, view)`.
**Fix.** Router in `shell.js`: `readRoute()` on load **after** the first successful `refresh()` (add `state.loaded=true` there); precedence `hash > sessionStorage > Home`; `goHome()` clears `sessionStorage.activeLab` and sets `location.hash=''` via `history.replaceState`; `writeRoute()` compares the serialised route with `location.hash` and uses `history.replaceState` for poll-driven writes and `pushState` only from user navigation (`selectLab`, tab clicks, `openDetails`); `hashchange` handler diffs against `activeId/tab/detailName` before acting; `$('details-dialog').addEventListener('close',…)` clears `device`; `selectLab(id,view='topology')`. Keep `sessionStorage['activeLab']` semantics (asserted by `test_operations_ui.js` test 7).

### A10 — MAJOR · §1.3 Progress tab 2 "Saved versions" · the list will not update after a save, and nesting the status card inside `#git-repository-content` blanks it while loading
**Evidence.** `gitShowRepository` renders once per lab (`gitViewLab===id&&!force` return, `git-progress.js:63`) and first writes a loading placeholder into the whole container (`:64`), then `gitRenderRepository` replaces `#git-repository-content.innerHTML` (`:77`). Nothing re-renders it when a save finishes: `gitStartWatch` (`:241-252`) only calls `gitRenderJob` + `renderGitProgress` + `refresh()`. So journey 4 ("Checkpoint appears under Checkpoints") and journey 3's "Recent saves" row will not appear until the student presses "Refresh status". Saved versions come from `/labs/{id}/git/history` (a VM-side git call, today fetched on demand in `gitHistory`, `:273`).
**Fix.** (a) `#git-progress-bar`, `#progress-save`, `#git-saved-versions` are siblings *before* `#git-repository-content`, not children — the placeholder then never blanks the status card. (b) In `gitStartWatch`'s terminal branch and in `gitDismissJob/gitPushPending` success paths call `gitShowRepository(true)` when `tab==='progress'` (cheap: the tab is visible) else set `gitViewLab=''` so the next visit re-renders. (c) Fetch history in `gitShowRepository` with the same `Promise.all`, render `#git-saved-versions` from `data.versions` grouped by path (`latest`, `checkpoints/*`, `baseline`, others), and keep `gitHistory()` as the "Saved versions & history" dialog unchanged. Tests: `test_git_places_ui.js` test 7 / `test_git_progress_ui.js` test 7 assert on `container.innerHTML` of `#git-repository-content` for `data-git-repo-action="switch|unlink|connect"`, `id="git-places-panel"`, `Verified push destination`, and the `<span>… saves to</span><code>…</code>` chain — keep those strings and nodes inside what `gitRenderRepository` writes (they can sit under the "Advanced repository details" `<details>` and the Save-location card; regex `match` does not care about nesting).

### A11 — MAJOR · §1.4 Device workspace · the drawer is rewritten every 4 s, so an Advanced `<details>` inside `#details-info` snaps shut; `data-check/data-edit` cannot be "placed by CSS"; `data-enable` in the drawer has no handler
**Evidence.** `render()` → `refreshHealth()` (`app.js:66,148-153`) → `renderDetails()` when the dialog is open → `$('details-info').innerHTML=…` (`:160`) with **no `_markup` diff**. A `<details>` rendered inside it is recreated closed on every poll; a checkbox inside it loses focus/its half-toggled state. `nodeActions(n,true)` returns one flat string of six buttons (`:72`); CSS cannot move `[data-check]`/`[data-edit]` out of `#details-actions` into a collapsed section. The `change` listener for `data-enable` is on `#nodes` only (`:116`); `handleNodeAction` is on `#nodes` and `#details-actions` only (`:114-115`).
**Fix.** (a) `renderDetails`: diff `#details-info` with `_markup` like `renderNodes` does, and make the Advanced `<details id="details-advanced">` a **static** element in `index.html` whose inner `#details-advanced-body` is the rewritten part (preserves `open`). (b) Split the renderer: `nodeActions(n,details)` keeps returning capture/terminal/backup (+ details button when `!details`), new `nodeDrawerActions(n)` returns check/edit; `renderDetails` writes the latter into `#details-advanced-actions` and registers `handleNodeAction` + the enable-`change` handler on `#details-dialog` (delegation covers both containers). (c) Update `test_readiness_ui.js` test 1 to call `nodeDrawerActions` for the two `data-check` assertions and change `>SSH` to `>Open CLI` — the behavioural claim (booting disables the CLI with an explanation; Test login stays available; failed login advises credentials) is unchanged.

### A12 — MAJOR · §1.1 / §1.3 / §4 · handlers hard-reset labels the spec renames, and `#lab-start`'s text is not managed anywhere
**Evidence.** `management.js:146` resets `#vm-refresh` to `'Refresh discovery'` after every click (spec: "Refresh lab list"); `management.js:153,156` set `#sync-vm` to `'Syncing…'` then `'Sync from VM'` (spec: "Sync topology from VM"); `topology.js:28,31` set `#map-expand` to `'Expand map'`/`'Close expanded map'` (spec: "Expand"); `renderLabOperations` (`operations.js:269`) sets only `title` on `#lab-start`, so the spec's "when the lab is running the item reads 'Start stopped devices'" needs new code — and is wrong as stated: `opQuickActions` returns `canStart=false` when `status==='Running'`, so the item is *disabled* then; it reads "Start stopped devices" for `Stopped`/`Partially running` (`startAction==='start'`).
**Fix.** List these four sites in §4's per-file rows (management.js, topology.js, operations.js) as copy changes; have `renderLabOperations` set `$('lab-start').textContent=quick.startAction==='deploy'?'Start lab':'Start stopped devices'` (guarded, as the rest of that function is). Better still: give relabelled buttons a `data-label` attribute and make the handlers restore `b.dataset.label` instead of a literal.

### A13 — MAJOR · §1.3 Danger group vs §1.3 Advanced "Danger zone" · `#remove-lab` (and `#lab-destroy`) are single elements but are wanted in two places, and a `.click()` proxy on a disabled button is a silent no-op
**Evidence.** `management.js:71` sets `$('remove-lab').disabled` per poll; `:159` assigns `onclick`. The spec puts `#remove-lab` in the Lab actions menu (§1.3 group 3) **and** in Advanced ("`#remove-lab` 'Remove this lab from the manager…' (the Lab actions menu item triggers the same button)"). A menu item that calls `$('remove-lab').click()` while the real button is disabled does nothing and shows nothing.
**Fix.** One element per id. `#remove-lab` lives in the Advanced danger zone; the menu item is `#menu-remove-lab` and `renderManagement` (or `renderLabOperations`) mirrors `disabled`/`title` onto it; its handler calls `$('remove-lab').onclick()` (a function property, so this works even when the button is hidden). Same pattern for any other "triggers X" item (`#map-edit`, `#capture-open`, `#lab-actions`): mirror `disabled`, call the `onclick`, never `.click()` a hidden/disabled control.

### A14 — MAJOR · §1.2 Home / §3 Skeleton · `render()` shows the "No labs yet" empty state on Home whenever no lab is selected, and flashes it before the first `/state`
**Evidence.** `app.js:46` `$('empty').hidden=!!lab;$('lab-content').hidden=!lab;` — with `refresh()` no longer auto-selecting, `lab` is undefined on Home even when labs exist, so `section#empty` ("No labs yet — Deploy or import…") renders under the lab cards. Before the first `/state` returns (`state.labs=[]` at `app.js:4`) it also renders on every page load, and `maybePromptVmConnection()` may pop the VM dialog over it.
**Fix.** `refresh()` sets `state.loaded=true` after the JSON parses; `render()` computes `const home=!lab; $('home').hidden=!home; $('empty').hidden=!home||!state.loaded||state.labs.length>0; $('lab-content').hidden=!lab; $('home-skeleton').hidden=state.loaded;` and `renderLanding()` keeps its `if(lab||!$('deploy-empty'))return;` (the readiness test 3 fixture has `labs:[]`, so it still passes).

### A15 — MAJOR · §1.1 lab switcher / §1.2 cards / §1.2 discovered · unconditional innerHTML rewrites every 4 s inside popovers and card grids destroy focus
**Evidence.** `app.js:42` rewrites `$('labs').innerHTML` on every poll with no `_markup` diff; `management.js:64,66,67` do the same for `#discovered-labs`, `#discovery-file-list`, `#excluded-labs`. Today these are sidebar lists; in the spec they become the body of `details#lab-switcher` (a popover) and Home cards. A keyboard user tabbing to "Open lab"/"Import" loses focus within ≤4 s; the popover itself stays open (the `details` is static) but its focused child is gone — invisible focus, Enter does nothing. Screen readers announce the list again.
**Fix.** Apply the `_markup` diff idiom (`app.js:70`) to `#labs`, `#lab-cards`, `#home-continue`, `#discovered-labs`, `#excluded-labs`, `#discovery-file-list`. Relative times change at most once a minute, so the diff is effective. Spec §0.8 should name these six ids explicitly.

### A16 — MAJOR · §4 "Tests" row · the relabels the spec mandates fail named tests; the spec must list the rewrites and add the new files to CI
**Concrete failures if the spec is implemented literally (all "mixed" tests whose claim survives a regex edit):**
| Test | Breaks because | Rewrite that keeps the claim |
|---|---|---|
| `test_readiness_ui.js` #1 | `>SSH` → "Open CLI"; `title="NOS is still booting…"`/`assign a credential profile` → `deviceState` sentences; `data-check` moves out of `nodeActions(n,true)` (A11) | `/data-terminal="r1" disabled title="R1 is still starting/`, `/data-terminal="r1" >Open CLI/`, `/Check credentials|SSH login failed/`, `nodeDrawerActions` for `data-check` |
| `test_readiness_ui.js` #5 | spec §1.3 Tools relabels `a#grafana-open` to "Open network dashboard"; test pins `'Lab map in Grafana ↗'`/`'Grafana ↗'` | keep the link text (the card heading can say "Open network dashboard"), or update the two `assert.equal`s |
| `test_readiness_ui.js` #4 | only if `renderNosReadiness` copy changes | keep it: it now lives under Advanced → Deployment details, technical is fine |
| `test_operations_ui.js` #6 | only if `opLabels.destroy/deploy/inspect` change (banner text `✖ Destroy deployment failed`) | keep `opLabels` for banners/history; add a separate `opReviewCopy[action]={title,body,confirm}` map for §1.6 dialogs |
| `test_git_progress_ui.js` #7, `test_git_places_ui.js` #7/#9 | if "Verified push destination", `data-git-repo-action=*`, `id="git-places-panel"`, `<span>… saves to</span><code>` leave `#git-repository-content` | keep them inside what `gitRenderRepository` writes (A10) |
| `test_capture_ui.js` #7 | `captureActionAttrs()` string must still start `disabled title=` | keep |
| CI | `release-check.yml:68` lists 12 files; `test_status_ui.js`, `test_home_ui.js`, `test_shell_ui.js` must be appended; `test_diagram_editor_ui.js` is still missing from CI | append all four |
Also `deploy/verify-release.py` will demand `?v=1.29.0` on the new `status.js`/`home.js`/`shell.js` tags (regex over every `/static/…?v=` in `index.html`) — the spec says so; fine.

### A17 — MINOR · §0.6 · "Show running labs" confirm label needs a code change the spec does not list
`opReview` (`operations.js:84,93`) uses one `label` for the title, the confirm button and the banner. Add `opReviewCopy` (A16) and read the confirm label from it.

### A18 — MINOR · §1.3 Lab actions · `#sync-vm` visibility claim is inaccurate
"hidden unless updates available, as today" — today `sync.hidden=!lab.deployment_name`, `sync.disabled=vmSyncBusy||!discovery.connected||!source?.can_sync` (`management.js:73-74`). A hidden-but-disabled menu row reads as a bug; spec it as "shown when the lab is linked; disabled with a title when nothing can be synced".

### A19 — MINOR · §3 Menus · the global Escape handler in `topology.js:28` collapses the expanded map on *any* Escape
`document.addEventListener('keydown', Escape)` closes the node menu, else removes `map-expanded`. With `details.menu` menus also closing on Escape, pressing Escape to close the Lab actions menu while the map is expanded also un-expands the map. Order the handlers: `closeMenus()` returns `true` when it closed something; the topology handler returns early in that case.

### A20 — MINOR · §1.1 / §1.2 · two different "Deploy a new lab" behaviours
`#vm-projects` navigates to `/static/workspace.html#mode=folder` (`operations.js:281`, the two-card page the audit criticised), while `#deploy-empty`/`#home-deploy` call `openDeploy()` = in-page `opBrowse()` dialog. Make Manager ▾ "Deploy a new lab…" call `openDeploy()` too and keep `workspace.html` reachable as "Lab topologies page ↗" (it is also the SSH-all launcher target, `opNewTab`, so it must stay).

### A21 — MINOR · §1.3 Topology · the spec misdescribes the current click handler
"the existing click handler that only selected/labelled stays as a fallback" — `topology.js:13-14` already calls `openDetails()` on left-click/Enter/Space for matched nodes. Nothing to add; just do not add a second click listener that also opens details (double `showModal()` throws `InvalidStateError` if the dialog is already open).

### A22 — MINOR · §1.4 · `<title>` and `aria-label` on map nodes say "Right-click for SSH…"/"Open X actions"
`topology-render.js:26` — relabel to "Open <label>" (test 2 asserts `aria-haspopup="menu"`, keep that attribute since the context menu remains).

---

## B. Per-topic verdicts the task asked for

| Topic | Verdict | Where it breaks | Corrected plan |
|---|---|---|---|
| File plan (§4) | Mostly feasible. `status.js` exists and is green. | New globals in `app.js` (A2); no `shell.js`; CI list (A16) | Add `shell.js` for router/menus; harnesses load `status.js`; app.js keeps zero new top-level side effects |
| Id relocations (§0.4, §1) | Feasible **if** the unlisted ids are kept (A4) and one-id-one-element is respected (A3, A13) | `app.js:43,48,50`; `git-progress.js:316`; `operations.js:277` | Publish a load-bearing id list per file; static `#lab-actions`; proxies mirror `disabled` and call `onclick` |
| `showTab` legacy mapping | **Not feasible as written** (A1) | `app.js:93,16,103,133` | Rewrite loop around the five panels + `devicesTechnical`; `logs` auto-refresh via `tab==='advanced'` |
| Hash routing | Feasible with a router that lives outside `app.js` (A2, A9) | harness has no `location`; `render()`→`showTab` every 4 s; `management.js:169,215` | `shell.js` router, `replaceState` on poll writes, precedence hash>session>Home, clear `device` on dialog `close`, apply route after `state.loaded` |
| `#git-save-progress` vs `#progress-save` | Feasible with mirroring (A7) | `git-progress.js:52-56,301,317` | Mirror both buttons in `renderGitProgress`; gate/wire every `[data-git-action]`; `closeMenus()` |
| Lab actions menu reusing `#lab-start/#lab-destroy/#sync-vm/#remove-lab` | `#lab-start/#lab-destroy/#sync-vm` fine (in-place mutation); `#remove-lab` and the `data-op-action` rows are not (A6, A12, A13) | `operations.js:36,267-284`; `management.js:71,146,153-156` | Delegated `[data-op-action]` handler on the menu; gating in `renderLabOperations`; `data-op-options` for cleanup; one `#remove-lab` |
| Device rail | Feasible; must be a third consumer of the same `handleNodeAction` delegation with `_markup` diff; the map state overlay must be a separate pass (A5) | `app.js:69-72,105,114-115`; `topology-render.js:20`; `topology.js:35` | `renderDeviceList()` renders `#device-list` and `#topology-devices` from one function, called from `render()` and `#search` input; `renderMapState()` for the SVG |
| `#inventory-view` as technical view | Feasible; the sub-state must be a variable because `showTab(tab)` runs every 4 s (A1) | `app.js:66,93,117`; `management.js:117,204` | `devicesTechnical` flag, set by `showTab('inventory')` and the toggle; `#search` filters both lists |
| Two renderers on one element | `#operation-summary` (A8); `#git-repository-content` placeholder vs status card (A10); `#details-info` (A11) | above | single owner per element; static containers for anything that holds `details`/menus/focus |
| 4 s poll races | header/banner innerHTML (A8), `#labs`/cards (A15), drawer `details` (A11), hash writes (A9), `refreshMap` per poll already exists and is fine because it diffs the drawing key | above | the "never innerHTML the chrome" rule + `_markup` on the six ids |

## C. Corrected migration order (replaces §4 "Order")
1. `status.js` (done) → add `status.js` to `test_download_ui.js`/`test_readiness_ui.js` harnesses (green run). Append new test files to `release-check.yml`.
2. `shell.js` (router, `closeMenus`, `rememberOpened`) + `test_shell_ui.js` with a richer fake DOM (`window`, `location`, `history`, `localStorage`, `document.addEventListener`). No `index.html` change yet.
3. `index.html` shell + `style.css` rewrite + `app.js` `render()/showTab()` per A1/A4/A14, `home.js` `renderHome()` with `_markup` diffs (A15). Keep `#import-top`, `#subtitle`(hidden)/footer, `#git-open-settings`, static `#lab-actions`. **Gate:** `node --test tests/*.js` green; a Playwright pass that clicks every `#` id from the load-bearing list and asserts no console errors during 12 s (three polls).
4. Devices + drawer (A11, A5): `renderDeviceList`, `nodeDrawerActions`, `renderMapState`, static `#details-advanced`. Rewrite readiness test 1 regexes.
5. Progress tab (A7, A10) — siblings before `#git-repository-content`; re-render on terminal git job; restore copy.
6. Lab actions menu + banner (A6, A8, A12, A13) + Tools + Advanced + confirmations via `opReviewCopy` (A16/A17).
7. Docs, release 1.29.0, live validation.
Each step: `node --test tests/*.js` (not the 12-file CI subset), `node --check` on every touched file, `grep -o "\$('[a-z0-9-]*')"` id diff against `index.html`, and a 12-second console-error watch in the browser with a menu and the drawer left open across three polls.

## D. What the spec gets right (keep)
- Keeping file names, global function names and every test-referenced id/data-attribute (§0.3–0.4) is exactly the right constraint; the harness inventory shows the cost of breaking it.
- `status.js` as pure functions is the correct seam; it already matches the backend vocabulary (`main.py:140-152`, `node_readiness.py:61-80`, `discovery.py:148-158`) and is green.
- Legacy-name mapping in `showTab` (idea, not the loop) and nesting the old sections in new panels is the cheapest zero-regression path.
- Retaining all dialogs verbatim and routing every "student" button to an existing handler keeps the operations/git/restore flows untouched.
- The `_markup` diff rule and "no new polling" are the right performance guard-rails — they just need to be applied to six more ids (A15) and to the chrome (A8).
