# C02 design: ergonomics (terminal toolbar, Copy, Stop a running operation, hide the editor's About)

Rows R110, R111, R112 (terminal: font size, copy and clear, export; the plan's "R108, R109" do not exist in
`PARITY.md`, the terminal rows are these three), R025 (Copy) and R010 (cancel). Code read: `terminal.js/.html/.css`,
`shell.js`, `app.js` (`notify`, `api`, `renderDetails`, `setBanner`, `BANNER_BUTTONS`, `dismissedSet`),
`operations.js` (`opDialog`, `opShowJob`, `opJobBanner`, `opStatusWord`, `opRetryRequest`), `status.js`
(`STATUS_OPERATION_FAILED`, `labFailure`), `lab_operations.py` (`remote`, `execute`, `install`, `operation_busy`,
`record_deployment`), `main.py` (guard, `public_lab`), `host_operations.py` (`stream`, `main`), `lab-builder.css`,
the harnesses named in §5. Revised after the design review (§7 answers every confirmed finding). No helper change,
no helper `VERSION` bump, no route outside the same-origin guard. Plain scripts, no inline styles on `/`, `esc()` on
every interpolation, `?v=<release>` moved by the release owner.

## 1. Terminal toolbar (`terminal.html`, `terminal.js`, `terminal.css`)

**Markup.** A second row under the header, before `.notice`: `<div class="terminal-tools" role="toolbar"
aria-label="Terminal tools" title="Alt+T moves here">` with text buttons, in this order: `Smaller` (`#font-down`),
`Larger` (`#font-up`), `Reset size` (`#font-reset`), a separator, `Copy selection` (`#copy-selection`),
`Copy screen` (`#copy-screen`), `Clear` (`#clear`), a separator, `Save screen as text` (`#export-screen`),
`Save session as text` (`#export-session`), then `<span id="tools-status" role="status"></span>`. Roving tabindex:
one button carries `tabindex="0"`, the others `-1`; ArrowLeft/ArrowRight move between them (the house `.map-tools`
pattern on `/`); Tab leaves the toolbar. `type="button"`, the page's `button` rule, wrapping at 700 px like
`.session-controls`. The notice gains one sentence: `Alt+T moves to the terminal tools; Alt+Up, Alt+Down and
Alt+0 change the text size.` The page keeps its structure; inline styles stay xterm's only.

**Font size.** `FONT_SIZES` 11 to 18 px, default 14 (today's constant). `setFont(n)` clamps, sets
`terminal.options.fontSize=n`, calls `resize()` (the existing function: `fit.fit()` plus the `resize` frame; the
ResizeObserver does not fire because the container did not change), writes `clab.terminal.fontSize` through
`prefGet/prefSet`, a two-line try/catch pair like `shellGet/shellSet` (storage blocked or absent, as in the Node
harness, means the size is simply not remembered). The buttons' `disabled` follows the bounds (11 disables Smaller,
18 Larger); when the disabled button holds focus, focus moves to the other size button. `#tools-status` says
`Text size 14 px` after each change.

**Keys.** `terminal.attachCustomKeyEventHandler(keyHandler)`; xterm 5.5.0 calls it for keydown, keypress and
keyup, so `keyHandler` acts only when `e.type==='keydown'` and returns `false` for every event type of a handled
chord (otherwise one press acts twice), `true` for everything else. Chords: `Alt+ArrowUp` larger, `Alt+ArrowDown`
smaller, `Alt+0` reset, `Alt+T` focus the toolbar's current button, `Ctrl+Insert` copy the selection without
`preventDefault` (the browser's own copy event may fire too; harmless, same text). `Ctrl+Shift+C` is left alone
(Chrome owns it). `Ctrl+C` keeps sending `^C` to the device.

**Focus.** A toolbar button hands focus back to the terminal only after a pointer activation (`event.detail>0`);
after Enter or Space the button keeps focus, so a second Enter never reaches the device as a carriage return.

**Copy.** `copySelection()`: nothing selected shows `Nothing is selected` and returns; otherwise
`copyText(terminal.getSelection(), button)`. `copyScreen()` copies `screenText()`. `copyText` comes from
`clipboard.js` (§2), loaded by `terminal.html` too; its status goes to `#tools-status` (`Copied`, or
`Could not copy. Select the text and press Ctrl+Insert.`), never to a toast (the page has none).

**Clear.** `terminal.clear()` (xterm keeps the current prompt line). Status `Screen cleared. The device was not told.`

**Export.** `rowsText(buffer, from, to)` walks lines `from..to`, appends `getLine(i).translateToString(false)` and
joins a row to the next **without** a newline when the next row's `isWrapped` is true (xterm's own selection does
the same, so a long `show running-config` line is one line again whatever the width), right-trims only at the end
of a logical line, and drops trailing empty lines. `screenText()` = `rowsText(buffer.active, viewportY,
viewportY+rows-1)`; `sessionText()` = `rowsText(buffer.normal, 0, length-1)` (the normal buffer holds the
scrollback even while a pager owns the alternate screen). `download(text, kind)` builds a `Blob` (`text/plain`), an
object URL and a click on a created `<a download>`, revoked after 1 s (the `download-logs` pattern in `app.js`).
Name `exportName(labLabel, name, date)` = `<lab>-<device>-<YYYYMMDDTHHMMSSZ>.txt`, both names reduced to
`[A-Za-z0-9_.-]` (else `lab` / `device`). Status: `Saved on this computer only. The manager keeps no copy of this
session.`, plus `the last 3,000 lines` when `buffer.normal.length>=3000` (xterm's scrollback). Nothing is sent to
the manager: persistent logs and job messages never carry SSH output.

**States.** Default: toolbar enabled from load, before the socket connects (the buffer is local). Disconnected: all
tools stay enabled. Empty buffer: Copy screen copies an empty string and says `Copied`; the exports produce a file
with one empty line (no refusal). Error: only the status line; never a dialog. Reconnect: the existing
`terminal.reset()` empties the buffer (a decision kept from `main`; the status says `Reconnected; the previous screen
was cleared`), the font size persists. `#tools-status` is replaced each time (one live region).

## 2. `clipboard.js`, `copyText()` and the Copy buttons

**New script `clipboard.js`** (house style, loads in Node: it touches `navigator` and `document` only inside
functions, except one `document.addEventListener('click', …)` guarded by `typeof document!=='undefined'`). Loaded
with `?v=<release>` before `operations.js` on every page that loads `operations.js` (`index.html`,
`workspace.html`, `lab-builder.html`; `vm-connection.html` names the file in its text only, the builder confirms at
build) and by `terminal.html`. The release owner adds it to `verify-release.py`'s pages. `shell.js` is unchanged.

**`async function copyText(text, source)`.** Order: `navigator.clipboard.writeText` when `navigator.clipboard`
exists (secure origins) → a hidden `<textarea readonly>` appended to `source.closest('dialog[open]')||document.body`
(a modal dialog makes the rest of the page inert; a textarea outside it never takes focus, `execCommand` still
returns `true` and nothing is copied: the default deployment is plain `http://VM_IP:8081`, so this is the main path),
`focus()`, `select()`, then `execCommand('copy')` only if `document.activeElement` is that textarea with its value
selected, removed afterwards → on both failing, select the text of the element named by `source.dataset.copyTarget`
(never the button) and return `false`. Returns `true/false`; never throws.

**Delegation and feedback.** The one document-level `click` listener in `clipboard.js` handles
`button[data-copy]`: `copyText(button.dataset.copy, button)`, then flips the button text **and** `aria-label` to
`Copied` for two seconds and restores the label stored once at render (`data-label`, written by `copyButton`), so a
double click cannot leave it stuck. Where the result is announced: inside an open dialog, the `role="status"` span
`copy-status` rendered next to the button (`Copied` / `Could not copy. The value is selected: press Ctrl+C.`), and a
failure also in the dialog's `.form-error`; outside a dialog, `notify()` when it exists (the toast is inert and
underneath while a modal is open); on `terminal.html`, `#tools-status`. C03, C04 and C09 add Copy by writing
`data-copy` and `data-copy-target` and nothing else.

**Markup.** `copyButton(value, what, targetId)` in `clipboard.js` returns
`<button type="button" class="button ghost small copy-button" data-copy="${esc(value)}" data-copy-target="${esc(targetId)}"
data-label="Copy" aria-label="Copy ${esc(what)}">Copy</button><span class="copy-status" role="status"></span>` or
`''` when `value` is empty. One rule in `style.css`:
`.copy-button{margin-left:8px;min-height:26px;padding:2px 8px;font-size:12px}.copy-status{margin-left:6px;font-size:12px;color:var(--muted)}`;
`terminal.css` repeats the two for its dark chrome.

**Device drawer** (`renderDetails`, the `#details-info` Connection section, which `setMarkup` diffs; the header's
`#details-endpoint` is untouched): each `<dd>` gets an id (`details-fact-name`, `-endpoint`, `-address`, `-kind`,
`-image`) named by its button's `data-copy-target`. Rows: `Name in lab files` + Copy(`n.name`); `Address` + Copy of
the endpoint, written `[address]:port` when the address contains `:` (IPv6) and `address:port` otherwise, and a
second Copy `Copy the address only` when `n.address` is set; new rows `Container kind` (`n.kind`) and `Image`
(`n.image`), each with Copy, rendered only when present (`public_lab` passes every node field but username,
password, enable_password and container_name, so kind and image reach the page when discovery or the topology named
them). Container name and ID and MAC are not shown: the public view strips `container_name` on purpose and no MAC
is collected; C04 (R024) adds those rows and gets Copy for free. `setMarkup` rebuilds only on changed markup, so the
4 s poll does not undo a `Copied` flip, and focus stays on the button.

**Operation output** (`opShowJob`): `<div class="op-output-tools"><button type="button" id="op-copy-output"
class="button ghost small" data-label="Copy output" aria-label="Copy the command output" data-copy-target="op-job-output">Copy output</button><span class="copy-status" role="status"></span></div>`
above `#op-job-output`. It carries **no** `data-copy`: `opShowJob` binds its own click (`copyText(job.output,
button)` with the same flip) like its other controls, so it works on `workspace.html` and `lab-builder.html`, which
load `operations.js` without `shell.js`, and never copies twice on `/`. Disabled while the output is empty
(`Waiting for the VM…` is never copied). The inspect table gets no Copy here (C03's R013 adds cells).

**Keyboard.** Buttons are real buttons: Tab reaches them, Enter/Space copy. No shortcut on `/`.

## 3. Stop a running lifecycle operation (R010)

**Mechanism (manager side only).** `remote()` polls its stop condition every 0.2 s and its `finally` closes the
SSH client. On the VM the helper's heartbeat (`stream()`, about once a second) then fails with `BrokenPipeError`, and
`stream()`'s `finally` sends SIGTERM to the containerlab process group, waits 5 s, then SIGKILL; the host flock is
released when the helper exits. Nothing in `host_operations.py` or the gateway changes.

**Which jobs.** `STOPPABLE = ('deploy', 'redeploy', 'destroy', 'apply', 'start', 'stop', 'restart',
'restart-node', 'save', 'clone', 'inspect-all')` in `lab_operations.py`: the actions that run through `stream()`
and so die with the channel. `create`, `delete`, `publish`, `revise` (file actions that write first and emit once at
the end) and `inspect` (one short read) cannot be stopped: the route answers 409 `This step finishes on its own in a
moment and cannot be stopped.` and `opShowJob` never renders the Stop block for them. `STATUS_STOPPABLE` in
`status.js` is the same list; a test pins the two equal.

**Per-job event and the stop condition.** `confirm()` creates `self.cancels[id]=threading.Event()` under
`store.lock` **before** `pool.submit` (the `network_design.py` precedent); `execute()` reads it with `get()`.
`remote(host, req, output, stop)` gets a small object whose `is_set()` is `self.stopping.is_set() or event.is_set()`.
`close()` sets `self.stopping` first, then every job event; `execute()` reads `self.stopping` first, so a shutdown
racing a stop always reads `interrupted`, in every ordering (combined condition plus explicit read order).

**`remote()` honours the stop only while nothing final arrived.** The condition is checked after `connect` and
before `exec_command` (a stop during the 8 s connect never sends the request), then on each loop pass only while
`result is None` and no `error` item has arrived. That path alone raises `OperationStopped(ValueError)` with
`'Operation stopped. Inspect the lab before retrying.'`. Once the helper's `{'result'}` line is in, the loop runs to
EOF and exit status as today: a command that completed is never relabelled.

**Classification in `execute()`.** `self.stopping.is_set()` → `interrupted` (shutdown; today's message);
`isinstance(exc, OperationStopped)` → `cancelled`; every other exception → `failed` with its own message, even
when `cancel_requested` is set (a helper `{'error'}`, a digest mismatch, a non-zero exit, an exception after
`remote` returned). Before `remote`: an already-set event (stop while queued) ends `cancelled` without touching the
VM. `exit_code` stays `None` on `cancelled`, `finished=stamp()`, `output` the scrubbed text so far.
`record_deployment` runs only in the `succeeded` branch today, so a cancelled deploy records no `last_deployed`
(pinned by a test, no code). `discovery.refresh()` in `finally` runs as today.

**Why a new status.** `interrupted` means the manager lost the operation (restart, dropped connection) and its
contract is "inspect before retrying"; `cancelled` means a person asked for it, the aftermath is known per action,
and Try again can repair it. Reusing `interrupted` would make Stop look like an accident and lose the repair advice.

**The job stays busy until the VM is free (the 202 state).** After a stop the record keeps `status='running'`
(in `BUSY`), gets `cancel_requested=stamp()` and the message `Stopping… the manager has asked the lab VM to end
the command`. `OperationStopped` is caught inside `execute()`, which then runs a **follow-up on the same worker**:
once a second, for up to 20 s, `remote()` with the same request in `mode: 'preview'` (digest dropped, timeout 8 s).
Preview is a read-only plan under the same flock, so the helper answers `Another host lab operation is running.`
while containerlab is still being ended, and anything else (a plan, a different error) once the lock is free; an
SSH failure counts as "not yet proven" and the loop continues. On proof: `cancelled`, `message` from the aftermath
table. After 20 s without proof: `cancelled` with `The lab VM is still ending the command; wait a moment before the
next operation.` Consequence, stated plainly: `operation_busy` and `guard()` keep refusing backups, saves, loads,
imports and new operations until the follow-up ends (`Wait for the current lab operation to finish.`), and for the
moment of the synchronous `discovery.refresh()` after it, as after every operation today (QA-020). That is the
correct behaviour: nothing else may touch the lab while containerlab may still be writing to it.

**Route.** `POST /api/operations/{job_id}/cancel`, body `{}` (the guard refuses a mutating request with
`content-length` 0, a `DELETE` included; body-less POST routes without a model exist, `git_progress.update_remote`),
any same-origin caller like every other action. Under `store.lock`: unknown id → 404 `Operation not found.`; action
not in `STOPPABLE` → 409 `This step finishes on its own in a moment and cannot be stopped.`; status not in `BUSY`
→ 409 `This operation has already finished.`; otherwise set `cancel_requested` once (idempotent: a second call
returns the same timestamp), set the event, save, return 202 `{'id', 'status': 'running', 'cancel_requested',
'message'}`. The route never waits for the outcome; the output dialog's 1 s poll follows it.

**Public view.** `GET /api/operations/{id}` and the history already return the record minus `output`; new fields
are `status: 'cancelled'` and `cancel_requested` (controlled metadata). `message` is the aftermath sentence.

**One per-action table, `STOP_AFTERMATH`** (Python; `status.js` holds the same words for the confirmation):
deploy, redeploy, apply, start, restart → `Redeploy lab`; destroy → `run Destroy lab again`; stop → `run Stop
devices again`; restart-node → `Restart device again (Redeploy lab also works but clears unsaved configuration on
every device)`; save → `run Save device configurations again`; clone → `run Download lab again`; inspect-all →
`run it again`. The stored message is `You stopped <label>. The lab may be only partly <verb>: <repair>.` (verb:
destroy → `removed`, stop → `stopped`, save/clone/inspect-all → the sentence drops the clause, else `started`).
Never "rolled back". `opRetryRequest` maps a cancelled `deploy` to a `redeploy` review with the same options (so
the button and the advice agree); every other cancelled action repeats itself.

**UI wording: the button is Stop, the outcome is "Stopped by you".** Every dialog on `/` has a `Cancel` that means
"close without doing anything" (`#op-cancel`), the lab state already uses `Stopped` and an action is named `Stop
devices`, so: badge and history word `Stopped by you` (`STATUS_BADGE_LABELS.cancelled`, `opStatusWord.cancelled`);
banner title `■ ${label} ended early: you stopped it`; `labFailure` detail `You stopped ${label} before it
finished.` (with the -ing label `status.js` already gives); confirmation `End the running command (${label}) on
${name}?`. The API keeps the lead's `cancel`.

**UI.** In `opShowJob`'s body, between the banner and the output: `<div id="op-job-stop" class="op-stop" hidden>`,
rendered only when `STATUS_STOPPABLE.includes(job.action)`, rebuilt only when `(job.status, cancel_requested,
asked)` changes. States: queued/running, no request → `[Stop this operation…]` (`button secondary small`,
`#op-stop-ask`). Asked → `End the running command (${label}) on ${name}? The manager asks the lab VM to end it now.
The lab may be only partly ${verb}; afterwards: ${repair}.` with `[Keep running]` (`#op-stop-keep`, focused first)
and `[Stop]` (`button danger`, `#op-stop-confirm`, one Tab away); Keep running returns focus to the ask button.
After `[Stop]`: `opTask(dialog, ()=>json('/operations/'+id+'/cancel','POST',{}))`, then the block shows
`<p id="op-stop-status" role="status" tabindex="-1">Stopping… the manager has asked the lab VM to end the
command.</p>` and focuses it. When the block hides while it holds focus (the job turned terminal), focus moves to
the job banner (`#op-job-banner` gets `tabindex="-1"`). 409 `already finished` → the block hides on the next poll;
other errors land in `.form-error` through `opTask` and the ask button comes back (retry). The banner carries the
outcome (`warn` tone). Closing the dialog while `Stopping…` changes nothing: the record carries the request.
`opShowJob(id,{stop:true})` opens with the confirmation unfolded (focus on Keep running).

**Lab banner.** `index.html` gains a static `<button type="button" class="button secondary small" id="banner-stop"
hidden>Stop…</button>` inside `#lab-banner`'s actions, listed in `BANNER_BUTTONS['lab-banner']`. `setBanner`'s
`runningOp` branch adds `banner-stop` `{label:'Stop…', run:()=>opShowJob(runningOp.id,{stop:true})}` only while the
job is queued or running, its action is in `STATUS_STOPPABLE` and `cancel_requested` is unset. Jobs without a lab
(`clone`, `inspect-all`) are stopped from the Stop block in View output; the home banner gets no button.

**Vocabulary sites** (every one): `status.js` `STATUS_OPERATION_FAILED` gains `'cancelled'`,
`STATUS_BADGE_LABELS.cancelled`, `labFailure` gives a cancelled row `pill:'warn'` and the detail above,
`STATUS_STOPPABLE`, the aftermath words; `app.js` `dismissedSet` derives its list from `STATUS_OPERATION_FAILED`,
`STATUS_RESTORE_FAILED` and `STATUS_RESTORE_ATTENTION` (their union is today's literal list, so Dismiss clears a
stopped job without a second edit), `badge()` maps `cancelled` to `warn` (its default branch), `BANNER_BUTTONS`;
`operations.js` `opStatusWord`, `opJobBanner` tone `warn` (hint only for failed/interrupted), `opRetryRequest`,
the Stop block; `style.css` `.op-banner.warn{background:var(--warn-soft);border-color:var(--warn);color:var(--warn-strong)}`
and `.op-stop` spacing. `restarting_nodes`, `last_deployed`, `operation_busy` are status-based and unchanged.
`docs/LAB-OPERATIONS.md` line 171 gets one sentence from the lead.

**Failure paths.** Stop after the job finished → 409, the block hides. Stop twice → both 202, one timestamp. Helper
not answering (hung VM, dropped network) → `remote` raises on its next 0.2 s tick and closes the client; the
follow-up probes fail over SSH for 20 s and the job ends `cancelled` with the "still ending" sentence; the helper,
if alive, kills the process group on its next heartbeat. Manager restart during Stopping → startup marks the job
`interrupted` (today's rule). Storage error while writing `cancelled` → the memory record holds it (today's
`except OSError` pattern). A stop during `plan()` of a preview is impossible: previews are not jobs.

## 4. Hide the editor's About entry (`lab-builder.css`, `tests/test_lab_builder_ui.js`)

Add `[data-testid="navbar-about"]` to the existing `display:none !important` list for controls hidden by test id
(the bundle renders the entry as an `IconButton` with that `data-testid` and tooltip `About TopoViewer`; VS Code
branding and a dialog about the upstream product mean nothing to a student). Both pages load `lab-builder.css`, so
one line covers the builder and the map editor. The test that pins the hidden ids gains this id.

## 5. Tests (new files reach CI only through the lead's explicit lists)

| Item | File (harness to copy) | Cases |
|---|---|---|
| Terminal | `tests/test_terminal_ui.js` (its own harness; the fake `Terminal` gains `options`, `getSelection`, `hasSelection`, `clear`, `buffer.active`/`buffer.normal` with `isWrapped` rows, `attachCustomKeyEventHandler`; the context gains `localStorage`, `navigator`, `Blob`, `URL`, `document.createElement`; `clipboard.js` loaded first) | clamp 11..18, disabled buttons and focus moving to the sibling; remembered size, blocked storage tolerated; keydown then keyup of Alt+ArrowUp gives one step, keydown then keyup of Ctrl+Insert one copy, both swallowed on every event type, other keys passed; Alt+T focuses the toolbar's current button; pointer activation refocuses the terminal, Enter does not; roving tabindex with the arrow keys; `rowsText` joins a wrapped row without a newline and trims only at the logical end; `sessionText` reads `buffer.normal` while the alternate screen is active; `exportName` sanitising; export sends nothing over `fetch` or the socket |
| clipboard.js | new `tests/test_clipboard_ui.js` (copy `test_shell_ui.js`'s DOM: `closest`, listeners, `body`) | Clipboard API path; no `navigator.clipboard` → textarea inside `dialog[open]` (else body), `execCommand` only when the textarea is `activeElement` with a selection, else the failure path; failure selects the `data-copy-target` element, never the button; delegation flips text and `aria-label` to `Copied` and restores `data-label` after a double click; status span inside a dialog, `notify` outside, nothing when neither exists |
| Copy buttons | `tests/test_download_ui.js`-style harness for `renderDetails` (loads `status.js`+`clipboard.js`+`app.js`); `tests/test_operations_ui.js` with `clipboard.js` and without `shell.js` | drawer rows carry `data-copy` and `data-copy-target` for name, endpoint, address, kind, image; `[3fff::5]:22` for an IPv6 address; rows absent when the value is; `esc()` on values with quotes; `copyButton('')` is `''`; `#op-copy-output` disabled while empty, copies through its own binding on a page without `shell.js`, once on `/` |
| Page load | `tests/test_page_load_ui.js` | all scripts load together with `clipboard.js` in its place (its fake document has `addEventListener`) |
| Stop (Python) | `tests/test_lab_operations.py` (the `fixture()` `patch('app.lab_operations.remote')`, `pool.submit` captured as in the restart tests) | queued job stopped before `execute` → `cancelled`, `remote` never called; running job: a fake `remote` that loops on `args[1].is_set()` in a real thread and raises `OperationStopped`, then answers the lock sentence twice and a plan once in preview mode → `cancelled`, `exit_code None`, `cancel_requested` set, the aftermath message, `operation_busy` True during the follow-up and False after, `last_deployed` unchanged for a deploy; 20 s without proof (patched clock) → the "still ending" message; result line then event set before exit status → `succeeded` with `last_deployed`; error line with the event set → `failed` with the helper's message; a stop during connect never sends the request; `close()` between submit and `execute` → `interrupted`, never connects; `close()` racing a stop → `interrupted`; second stop → 202 and the same timestamp; stop after finish → 409; each of create, delete, publish, revise, inspect → 409 and no event; unknown id → 404; `content=b''` → 413 and the job still running; the history shows the new fields and no `output`; `STOPPABLE` equals `STATUS_STOPPABLE` read from `status.js` |
| Stop (UI) | `tests/test_operations_ui.js`; `tests/test_status_ui.js`; a `status.js`+`app.js` harness (`test_readiness_ui.js` style) | `opStatusWord('cancelled')`, `opJobBanner` tone `warn` and title, no hint; Stop block states from `(action, status, cancel_requested, asked)`, none for the refused actions; focus on Keep running, then `#op-stop-status`, then the banner when the block hides; `opRetryRequest` maps a cancelled deploy to redeploy; `labFailure` treats cancelled as attention with `warn` and the detail sentence; a dismissed cancelled job leaves `labState` out of attention; `badge('cancelled')`; `#banner-stop` shown only while queued/running, stoppable and unrequested |
| About | `tests/test_lab_builder_ui.js` | `navbar-about` in the hidden-id rule and still present in the bundle |

Static checks per changed script: `node --check`; `git diff --check`. Fixture pass (lead's `/clab-slice-verify`,
`ui:true`, Chromium and Firefox over `http://`): Copy output and a drawer Copy with a paste back to prove the copy;
one cEOS SSH session on the parity lab for font size, Ctrl+Insert, Alt+T and the export file; the Stop block against
the fixture's scripted VM. **Live need: one pass.** A `clab-devops-engineer` stops a deploy of a small cEOS lab on
the parity VM and records, with timings, from `ps`, `containerlab inspect` and a following preview that the process
group is gone and the flock is free. Until that pass exists, the 202 state's wording stays as in §3 and the README's
C02 row reads "Live need: one pass".

## 6. Assumptions, removed dead ends, what to attack

**Assumptions.** (a) xterm 5.5.0 exposes `options.fontSize` as a live setter, `buffer.active`/`buffer.normal` with
`isWrapped`, `getSelection`, `attachCustomKeyEventHandler` (vendor README pins 5.5.0; all are in that API).
(b) `document.execCommand('copy')` still works from a click in current Chrome, Firefox and Edge when the textarea is
focused inside the active dialog (deprecated, not removed; the verifier's scratch check passed with the textarea
inside the dialog). (c) The public node row carries `kind` and `image` whenever named; otherwise the rows are absent,
not broken. (d) sshd closes the helper's stdout when the manager closes the channel, so the heartbeat's
`print(..., flush=True)` raises `BrokenPipeError` within a second; the live pass proves it. (e) Browsers deliver
`keydown` for `Alt+ArrowUp/Down`, `Alt+0`, `Alt+T` and `Ctrl+Insert` to the page (macOS has no Insert; the buttons
remain the primary path; Alt+T on Firefox/Linux is checked in the fixture pass). (f) A `preview` of the stopped
request is a safe probe: `plan()` is read-only and already what every review runs.

**Refusals and dead ends removed.** A stuck deploy could only be waited out (20-minute helper timeout) → Stop. A
projector-unreadable 14 px terminal → 11 to 18 px, remembered. Copying a device address meant retyping → Copy on
each fact and on the command output, on every page that shows output. A session could not be attached to a report
→ two text exports, built in the browser only. The upstream About entry in a student tool → hidden.
`DELETE /api/operations/{id}` (refused by the guard's body rule) → `POST …/cancel {}`.

**Attack this.** (1) `OperationStopped` only while `result is None`: find a path where a completed command still
reads `cancelled`, or a real error reads as a stop. (2) The follow-up probe: can a preview under the flock have a
side effect, and is 20 s the right bound against the helper's SIGTERM 5 s plus SIGKILL? (3) `close()` ordering with
the combined condition. (4) `Ctrl+Insert` through `attachCustomKeyEventHandler` versus the browser's copy event;
`Alt+T` and `Alt+ArrowUp` on Firefox/Linux. (5) The textarea inside `dialog[open]` plus the activeElement check: a
false `Copied` must be impossible. (6) `cancelled` in `STATUS_OPERATION_FAILED`: the Needs-attention weight for a
stopped `inspect-all`. (7) `STOPPABLE` and `STATUS_STOPPABLE` drifting (one test pins them). (8) Wrapped-row joining
must never drop a real empty line inside the session or a space at the wrap point.

**Out of scope here.** `capture-session.html` (xterm too) gets no toolbar: no row asks for it; later it is a copy of
§1. Inspect-table and capture-dialog Copy (R013, C07) and the Container section (C04) only consume §2.

## 7. Review answers (one row per confirmed finding; F-ids from the review's synthesis table)

| Finding | Answer | Where |
|---|---|---|
| F1, F12 stop relabels a finished command or a real error | Accepted: stop honoured only while `result is None`, dedicated `OperationStopped`, `failed` keeps its message; tests added | §3 "`remote()` honours…", "Classification", §5 |
| F2, F18 `cancelled` frees `operation_busy` while the helper runs; refused twice afterwards | Accepted with change: the job stays `running` with `Stopping…` and a 20 s preview probe; `guard()` keeps refusing until then and that is stated as correct | §3 "The job stays busy…", "Failure paths" |
| F3, F14 Dismiss never clears a stopped job | Accepted: `dismissedSet` derives from the status.js sets; harness case | §3 "Vocabulary sites", §5 Stop (UI) |
| F4 event created too late; shutdown race | Accepted: event created in `confirm()` under the lock before submit; combined condition; test | §3 "Per-job event", §5 |
| F5, F13 Stop offered for file actions | Accepted: `STOPPABLE` (stream-backed actions, `inspect-all` and `clone` included), 409 for create, delete, publish, revise, inspect; no Stop block; tests per action | §3 "Which jobs", "Route", §5 |
| F6, F19 "Stopped" collides; advice contradicts | Accepted with change: outcome word `Stopped by you`, banner `ended early: you stopped it`, the button stays Stop; why `cancelled` not `interrupted` recorded | §3 "UI wording", "Why a new status" |
| F7, F15 Copy output dead on pages without `shell.js` | Accepted with change (lead's cut): `clipboard.js` holds `copyText` and the delegation, loaded by every page that loads `operations.js` and by `terminal.html`; the terminal twin is dropped; `#op-copy-output` binds its own click | §2 "New script", "Operation output", §1 "Copy" |
| F8, F16 textarea in an inert body; last resort selects the button | Accepted: textarea in `dialog[open]`, activeElement check, `data-copy-target` selected | §2 "`copyText`" |
| F9, F21 handler acts on keyup too | Accepted: keydown only, `false` on every event type of the chords, no `preventDefault` on Ctrl+Insert | §1 "Keys", §5 |
| F10 refocusing the terminal breaks keyboard use | Accepted with change: refocus only after pointer activation (`detail>0`); `role=toolbar` kept (house `.map-tools` pattern) with roving tabindex; sibling focus at a bound | §1 "Focus", "Font size" |
| F11, F25 wrapped rows split; alternate screen | Accepted (raised to should-fix): `isWrapped` rows joined, `sessionText` reads `buffer.normal`; tests | §1 "Export", §5 |
| F17 feedback wrong or invisible in dialogs | Accepted: `data-copy-target`, status span inside dialogs, `aria-label` flips with the label stored once | §2 "Delegation and feedback" |
| F20 confirmation, aftermath and Try again disagree | Accepted with change: one per-action table feeds both; `opRetryRequest` maps a cancelled deploy to redeploy | §3 "One per-action table" |
| F22 tools unreachable by keyboard once connected | Accepted with change: `Alt+T` (the lead's chord, not Alt+Shift+T) focuses the toolbar, named in its title and the notice | §1 "Markup", "Keys" |
| F23 focus lost when the Stop controls change | Accepted: Keep running focused first, `#op-stop-status` focused after the call, banner focused when the block hides | §3 "UI" |
| F24 banner Stop needs a static button | Accepted: `#banner-stop` in `index.html` and `BANNER_BUTTONS`; lab-less jobs stopped from View output; harness case | §3 "Lab banner", §5 |
| F26 "ended now" promise without live evidence | Accepted: stop checked before `exec_command`; wording `asks the lab VM to end it now`; one live pass by `clab-devops-engineer` | §3 "`remote()` honours…", §5 last paragraph |
| F27 shutdown ordering; IPv6 copy | Accepted: `close()` sets `self.stopping` first and `execute()` reads it first; `[address]:port` for IPv6 with a case | §3 "Per-job event", §2 "Device drawer", §5 |
| Refuted (3): the `Empty` model and readiness on a queued stop; the null boundary finding; Reconnect discarding the buffer | No change; the Reconnect status hint is added as wording only | §1 "States" |
