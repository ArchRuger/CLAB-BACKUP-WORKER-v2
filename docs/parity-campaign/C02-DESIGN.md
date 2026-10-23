# C02 design: ergonomics (terminal toolbar, Copy, Stop a running operation, hide the editor's About)

Rows R110, R111, R112 (terminal: font size, copy and clear, export; the plan's "R108, R109" do not exist in
`PARITY.md`, the terminal rows are these three), R025 (Copy) and R010 (cancel). Code read: `terminal.js/.html/.css`,
`shell.js`, `app.js` (`notify`, `api`, `renderDetails`, `setBanner`), `operations.js` (`opDialog`, `opShowJob`,
`opJobBanner`, `opStatusWord`, `opRetryRequest`), `status.js` (`STATUS_OPERATION_FAILED`, `labFailure`),
`lab_operations.py` (`remote`, `execute`, `install`, `operation_busy`, `record_deployment`), `main.py` (guard,
`public_lab`), `host_operations.py` (`stream`, `main`), `lab-builder.css`, the harnesses named below. No helper
change, no `VERSION` bump of the helpers, no new route outside the same-origin guard. Plain scripts, no inline
styles on `/`, `esc()` on every interpolation, `?v=<release>` moved by the release owner.

## 1. Terminal toolbar (`terminal.html`, `terminal.js`, `terminal.css`)

**Markup.** A second row under the header, before `.notice`: `<div class="terminal-tools" role="toolbar"
aria-label="Terminal tools">` with text buttons, in this order: `Smaller` (`#font-down`), `Larger` (`#font-up`),
`Reset size` (`#font-reset`), a separator, `Copy selection` (`#copy-selection`), `Copy screen` (`#copy-screen`),
`Clear` (`#clear`), a separator, `Save screen as text` (`#export-screen`), `Save session as text`
(`#export-session`), then `<span id="tools-status" role="status"></span>`. Buttons are `type="button"` and reuse the
page's `button` rule; the toolbar wraps at 700 px like `.session-controls`. The page keeps its structure (header,
notice, `#terminal`); inline styles stay xterm's only, nothing of ours is inline.

**Font size.** `FONT_SIZES` 11 to 18 px, default 14 (today's constant). `setFont(n)` clamps, sets
`terminal.options.fontSize=n`, calls `resize()` (the existing function: `fit.fit()` plus the `resize` frame; the
ResizeObserver does not fire because the container did not change), writes `clab.terminal.fontSize` through
`prefGet/prefSet`, a two-line try/catch pair like `shellGet/shellSet` (`terminal.html` deliberately loads no
manager script, so `shell.js` is not available here; storage blocked or absent, as in the Node harness, means the
size is simply not remembered). The buttons' `disabled` follows the bounds (11 disables Smaller, 18 Larger);
`#tools-status` says `Text size 14 px` after each change. Keyboard, through `terminal.attachCustomKeyEventHandler`
(xterm 5.5.0): `Alt+ArrowUp` larger, `Alt+ArrowDown` smaller, `Alt+0` reset, `Ctrl+Insert` copy the selection; the
handler returns `false` for these so xterm does not forward them to the device, `true` otherwise. `Ctrl+Shift+C` is
left alone: Chrome owns it (Inspect) and a page cannot take it reliably. `Ctrl+C` keeps sending `^C` to the device.

**Copy.** `copySelection()`: nothing selected shows `Nothing is selected` in `#tools-status` and returns; otherwise
`termCopy(terminal.getSelection())`. `copyScreen()` copies `screenText()`. `termCopy(text)` is the page's twin of
`copyText` (§2): `navigator.clipboard.writeText` when present, else a hidden textarea and `document.execCommand('copy')`
(plain HTTP origins have no Clipboard API; `execCommand` still works from a click), and on both failing the status
says `Could not copy. Select the text and press Ctrl+Insert.` Success shows `Copied` for 2 s. The terminal keeps
focus after every button (`terminal.focus()` at the end of each handler) so typing continues.

**Clear.** `terminal.clear()` (xterm keeps the current prompt line). Status `Screen cleared. The device was not told.`

**Export.** `screenText()` joins `buffer.active.getLine(viewportY+i).translateToString(true)` for the visible rows;
`sessionText()` joins lines `0..buffer.active.length-1`; both drop trailing empty lines. `download(text, kind)`
builds a `Blob` (`text/plain`), an object URL and a click on a created `<a download>`, revoked after 1 s (the
pattern of `download-logs` in `app.js`). Name `exportName(labLabel, name, date)` = `<lab>-<device>-<YYYYMMDDTHHMMSSZ>.txt`
with both names reduced to `[A-Za-z0-9_.-]` (else `lab` / `device`). Status after a save:
`Saved on this computer only. The manager keeps no copy of this session.` The scrollback is xterm's 3,000 lines, so
"session" means the last 3,000 lines; the status says `the last 3,000 lines` when `buffer.active.length>=3000`.
Nothing is sent to the manager: persistent logs and job messages never carry SSH output.

**States.** Default: toolbar enabled from load, before the socket connects (the buffer is local). Disconnected:
all tools stay enabled (copy and export of what is on screen are most wanted after a drop). Empty buffer: Copy
screen copies an empty string and says `Copied`; the exports produce a file with one empty line (no refusal).
Error: only the status line; never a dialog. Reconnect: the existing `terminal.reset()` on open empties the
buffer; the font size persists. `#tools-status` text is replaced each time (one live region, `role="status"`).

## 2. `copyText()` and Copy buttons (`shell.js`, `app.js`, `operations.js`, `style.css`)

**Helper.** `async function copyText(text, source)` in `shell.js` (browser APIs live there; it touches `navigator`
and `document` only when called, so every other script still loads in Node). Order: `navigator.clipboard.writeText`
when `navigator.clipboard` exists → hidden `<textarea readonly>` appended to `document.body`, `select()`,
`document.execCommand('copy')`, removed → if both fail and `source` is an element, select its text contents with a
`Range` and return `false`. Returns `true/false`; never throws. One document-level `click` listener in `shell.js`,
registered next to the other document listeners, delegates `[data-copy]`: `copyText(button.dataset.copy, button)`,
then flips the button's text to `Copied` for 1.5 s (`aria-live` comes from the toast) and calls `notify('Copied')`
on success or `notify('Could not copy. The text is selected: press Ctrl+C.')` on failure. Dialogs opened with
`showModal` are in the document, so the delegation serves `#details-dialog` and the operations dialogs alike, and
C03, C04 and C09 add Copy by writing `data-copy` and nothing else.

**Markup.** `copyButton(value, what)` in `app.js` returns
`<button type="button" class="button ghost small copy-button" data-copy="${esc(value)}" aria-label="Copy ${esc(what)}">Copy</button>`
or `''` when `value` is empty. One rule in `style.css`: `.copy-button{margin-left:8px;min-height:26px;padding:2px 8px;font-size:12px}`.

**Device drawer** (`renderDetails`, the `#details-info` Connection section, which `setMarkup` diffs; the header's
`#details-endpoint` stays as it is): `Name in lab files` + Copy(`n.name`, `the device name`); `Address` + Copy of
`address:port` (the form a terminal client wants) and, when `n.address` is set, a second Copy of the bare address
labelled `Copy the address only`; new rows `Container kind` (`n.kind`) and `Image` (`n.image`), each with Copy and
rendered only when the value is present (`public_lab` passes every node field but username, password,
enable_password and container_name, so kind and image reach the page when discovery or the topology named them).
Container name and ID and MAC are not shown: the public view strips `container_name` on purpose and no MAC is
collected; C04 (R024) adds those rows and gets Copy for free. Because `setMarkup` rebuilds only on changed markup,
the 4 s poll does not undo a `Copied` label mid-flip, and focus stays on the button.

**Operation output** (`opShowJob`): the dialog body gets `<div class="op-output-tools"><button … id="op-copy-output"
class="button ghost small" data-copy="">Copy output</button></div>` above `#op-job-output`; each poll sets
`dataset.copy=job.output||''` (an attribute update, not a rebuild, so focus survives) and disables the button while
the output is empty (`Waiting for the VM…` is never copied). The inspect table (`opInspectionTable`) gets no Copy
here (C03's R013 adds cells with `data-copy`).

**Keyboard.** Buttons are real buttons: Tab reaches them, Enter/Space copy. No shortcut on `/`.

## 3. Stop a running lifecycle operation (R010)

**Mechanism (manager side only).** `remote()` already polls `stopping.is_set()` every 0.2 s and raises
`'Operation connection interrupted. Inspect the lab before retrying.'`, and its `finally` closes the SSH client.
On the VM the helper's heartbeat (`stream()`, about once a second) then fails with `BrokenPipeError`, and
`stream()`'s `finally` sends SIGTERM to the containerlab process group, waits 5 s, then SIGKILL; the host flock is
released when the helper exits. Nothing in `host_operations.py` or the gateway changes.

**Per-job event.** `LabOperations.cancels: dict[str, threading.Event]`, guarded by `store.lock`. `execute()`
takes `event=self.cancels.setdefault(ident, Event())` first; `confirm` does nothing new. Before `remote`: if the
event is already set (a cancel while queued) the job ends `cancelled` without touching the VM. `remote(host, req,
output, event)` gets the job's event; `close()` sets `self.stopping` **and** every event in `cancels`, so the
shutdown path still reads `interrupted`. In `execute`'s `except`: `status='interrupted' if self.stopping.is_set()
else 'cancelled' if event.is_set() else 'failed'`, `exit_code` stays `None`, `finished=stamp()`, `message` from
`STOP_AFTERMATH[action]` (below), `output` the scrubbed text so far. `finally` pops the event. `record_deployment`
runs only in the `succeeded` branch today, so a cancelled deploy records no `last_deployed` (pin it with a test, no
code). `BUSY` is unchanged: `cancelled` is terminal, so `operation_busy` and `guard()` release at once; the helper
may still be killing the process group for up to about six seconds, and a review started inside that window gets
the helper's existing `Another host lab operation is running.`, the student reviews again. `discovery.refresh()` in
`finally` runs as today, so the half-deployed state is read back.

**Route.** `POST /api/operations/{job_id}/cancel`, body `{}` (the guard refuses a mutating request with
`content-length` 0, a `DELETE` included), no request model, any same-origin caller like every other action. With
`store.lock`: unknown id → 404 `Operation not found.`; status not in `BUSY` → 409
`This operation has already finished.`; otherwise set `job['cancel_requested']=stamp()` (idempotent: a second call
returns the same answer, no second timestamp), `self.cancels.setdefault(id, Event()).set()`, save, return 202
`{'id', 'status': 'running', 'cancel_requested'}`. The route never waits for the outcome: the job turns `cancelled`
within about a second (0.2 s poll; up to 8 s if the SSH connect itself is in progress, its own timeout), and the
output dialog's 1 s poll shows it. If the event is set after `remote` returned (the race), the real outcome wins and
`cancel_requested` stays on the record as history; the UI shows whatever status the job reached.

**Public view.** `GET /api/operations/{id}` and the history already return the whole record minus `output`; the
new fields are `status: 'cancelled'` and `cancel_requested` (a timestamp, controlled metadata). `STOP_AFTERMATH`
(plain sentences, stored in `message`): deploy/redeploy/apply/start/restart/restart-node → `Stopped by you. The
lab may be only partly started: choose Redeploy lab to repair it.`; destroy → `Stopped by you. Some devices may
still be running on the VM: run Destroy lab again.`; stop → `Stopped by you. Some devices may still be running:
run Stop devices again.`; save → `Stopped by you. Some devices may not have saved their configuration: run it
again.`; every other action → `Stopped by you. Check the lab before trying again.` Never "rolled back".

**UI wording: Stop, not Cancel.** Every dialog on `/` already has a `Cancel` that means "close without doing
anything" (`#op-cancel` in the review). The running operation gets **Stop**; the API keeps the lead's `cancel`.

**UI.** In `opShowJob`'s body, between the banner and the output: `<div id="op-job-stop" class="op-stop" hidden>`.
Each poll renders it from the job: queued/running and not requested → `[Stop this operation…]`
(`button secondary small`, `#op-stop-ask`); after the click → the confirmation sentence
`Stop ${label} on ${name}? The command on the lab VM is ended now. The lab may be only partly ${verb}; Redeploy lab
repairs it afterwards.` (verb: destroy → `removed`, stop → `stopped`, else `started`) with `[Stop]`
(`button danger`, `#op-stop-confirm`, focused) and `[Keep running]` (`#op-stop-keep`, returns focus to the ask
button); the confirmation survives polls because the markup is rebuilt only when `job.status` or
`cancel_requested` changes. After `[Stop]`: `opTask(dialog, ()=>json('/operations/'+id+'/cancel','POST',{}))`,
then the block shows `Stopping… the lab VM is ending the command.` (`role="status"`, both buttons gone). 409
`already finished` → the block hides on the next poll (the job is terminal); other errors land in the dialog's
`.form-error` through `opTask` and the ask button comes back (retry). When the job is terminal the block is hidden
and the banner carries the outcome. The lab banner's running state (`app.js` `setBanner`, the `runningOp` branch)
gets a second action `banner-stop` `{label:'Stop…', run:()=>opShowJob(runningOp.id,{stop:true})}`; the `stop`
option opens the dialog with the confirmation unfolded, so there is one place to confirm. Closing the dialog while
`Stopping…` is shown changes nothing: the job record carries the request.

**Vocabulary sites** (every one, so no page invents its own): `status.js` `STATUS_OPERATION_FAILED` gains
`'cancelled'`, `STATUS_BADGE_LABELS.cancelled='Stopped'`, `labFailure` gives a cancelled row `pill:'warn'` and
`detail:`${label} was stopped.``; `app.js` `badge()` maps `cancelled` to `warn` (its default branch already does);
`operations.js` `opStatusWord.cancelled='Stopped'`, `opJobBanner` tone `warn` with title `■ ${label} stopped`
(hint from `opJobHint` only for failed/interrupted); `style.css` one rule `.op-banner.warn{background:var(--warn-soft);
border-color:var(--warn);color:var(--warn-strong)}`. `opRetryRequest` is unchanged: Try again on a stopped deploy
repeats the confirmed request, which is the repair. `restarting_nodes`, `last_deployed`, `operation_busy` need no
change (status-based). `docs/LAB-OPERATIONS.md` line 171 (interrupted jobs) gets one sentence from the lead.

**Failure paths.** Cancel after the job finished → 409, the block hides. Cancel twice → both 202, one timestamp.
Helper not answering (hung VM, dropped network) → unaffected: the manager never waits for the helper; `remote`
raises on the next 0.2 s tick and closes the client, the record turns `cancelled`; the helper, if alive, kills the
process group on its next heartbeat. Manager restart during Stopping → startup marks the job `interrupted` (today's
rule). Storage error while writing `cancelled` → the memory record holds it (today's `except OSError` pattern).

## 4. Hide the editor's About entry (`lab-builder.css`, `tests/test_lab_builder_ui.js`)

Add `[data-testid="navbar-about"]` to the existing `display:none !important` list for controls hidden by test id
(the bundle renders the entry as an `IconButton` with that `data-testid` and tooltip `About TopoViewer`; VS Code
branding and a dialog about the upstream product mean nothing to a student). Both pages load `lab-builder.css`, so
one line covers the builder and the map editor. The test that pins the hidden ids gains this id.

## 5. Tests (new files reach CI only through the lead's explicit lists)

| Item | File (harness to copy) | Cases |
|---|---|---|
| Terminal | `tests/test_terminal_ui.js` (its own harness: the fake `Terminal` gains `options`, `getSelection`, `hasSelection`, `clear`, `buffer.active`, `attachCustomKeyEventHandler`; the context gains `localStorage`, `navigator`, `Blob`, `URL`, `document.createElement`) | clamp 11..18 and disabled buttons; remembered size read at load, blocked storage tolerated; Alt+Up/Down/0 and Ctrl+Insert handled and swallowed, other keys passed; `screenText`/`sessionText` row selection and trailing-blank trim; `exportName` sanitising; clipboard present, `execCommand` fallback, both failing; export sends nothing over `fetch` or the socket; `terminal.focus()` after each tool |
| copyText | `tests/test_shell_ui.js` (its DOM has `closest`, listeners, `document.body`) | Clipboard API path; no `navigator.clipboard` → textarea + `execCommand`; both failing → source text selected and `false`; `[data-copy]` delegation flips to `Copied` and back, toasts; a click without `data-copy` does nothing |
| Copy buttons | `tests/test_download_ui.js`-style harness for `renderDetails` (loads `status.js`+`app.js`); `tests/test_operations_ui.js` | drawer rows carry `data-copy` for name, `address:port`, address, kind, image; rows absent when the value is; `esc()` on values with quotes; `copyButton('')` is `''`; `op-copy-output` disabled while output is empty and carries the output text |
| Stop (Python) | `tests/test_lab_operations.py` (the `fixture()` `patch('app.lab_operations.remote')`, `pool.submit` captured as in the restart tests) | queued job cancelled before `execute` → `cancelled`, `remote` never called; running job: a fake `remote` that loops on `args[1].is_set()` in a real thread, cancel from the test → `cancelled`, `exit_code None`, `cancel_requested` set, `message` from `STOP_AFTERMATH`, `operation_busy` False, `last_deployed` unchanged for a deploy; second cancel → 202 and the same timestamp; cancel after finish → 409; unknown id → 404; `content=b''` → 413 and the job still running (the guard's body rule); `close()` during a run → `interrupted`, not `cancelled`; the public history shows the new fields and no `output` |
| Stop (UI) | `tests/test_operations_ui.js`; `tests/test_status_ui.js` | `opStatusWord('cancelled')`, `opJobBanner` tone `warn` and title, no hint; stop block states from `(status, cancel_requested, asked)`; `labFailure` treats cancelled as attention with `warn`; `badge('cancelled')` |
| About | `tests/test_lab_builder_ui.js` | `navbar-about` in the hidden-id rule and still present in the bundle |
| Page load | `tests/test_page_load_ui.js` | all scripts load together after `shell.js` grows a listener (its fake document has `addEventListener`) |

Static checks per changed script: `node --check`; `git diff --check`. Fixture pass (lead's `/clab-slice-verify`,
`ui:true`): one cEOS SSH session on the parity lab for a real look at font size, copy over `http://` (the fallback
path) and the export file; Stop exercised against the fixture's scripted VM, not a live deploy.

## 6. Assumptions, removed dead ends, what to attack

**Assumptions.** (a) xterm 5.5.0 exposes `options.fontSize` as a live setter, `buffer.active`, `getSelection`,
`attachCustomKeyEventHandler` (vendor README pins 5.5.0; all four are in that API). (b) `document.execCommand('copy')`
still works from a click in current Chrome, Firefox and Edge (deprecated, not removed). (c) The public node row
carries `kind` and `image` whenever discovery or the topology named them; if the fixture shows otherwise the rows are
simply absent (conditional markup), not broken. (d) sshd closes the helper's stdout when the manager closes the
channel, so the heartbeat's `print(..., flush=True)` raises `BrokenPipeError` within a second (Python ignores
SIGPIPE). (e) Browsers deliver `keydown` for `Alt+ArrowUp/Down`, `Alt+0` and `Ctrl+Insert` to the page (none is a
reserved browser shortcut on Linux or Windows; macOS has no Insert, so the buttons remain the primary path).

**Refusals and dead ends removed.** A stuck deploy could only be waited out (20-minute helper timeout) → Stop. A
projector-unreadable 14 px terminal → 11 to 18 px, remembered. Copying a device address meant retyping → Copy on
each fact and on the command output. A session could not be attached to a report → two text exports, built in the
browser only. The upstream About entry in a student tool → hidden. `DELETE /api/operations/{id}` (refused by the
guard's body rule) → `POST …/cancel {}`.

**Attack this.** (1) The cancel race: event set after `remote` returned but before `finally` pops it; the design
says the real outcome wins, check no path can leave `cancelled` on a job whose command completed. (2) The six-second
window in which the helper still holds the flock after the manager reports `cancelled`: is "review again" an
acceptable student experience, or should the Stopping… state last a fixed six seconds? (3) `close()` setting every
job event: confirm `interrupted` still wins over `cancelled` on shutdown in every ordering. (4) `Ctrl+Insert` through
`attachCustomKeyEventHandler` versus xterm's own copy handling; `Alt+ArrowUp` on Firefox/Linux (window menus).
(5) The `[data-copy]` delegation inside a `showModal` dialog: the inert tree must not swallow the click (it does
not: the dialog itself is the active tree). (6) `cancelled` joining `STATUS_OPERATION_FAILED`: every consumer
(`labFailure`, the Home card pill, the lab banner Try again) now shows a stopped operation as "Needs attention";
decide whether that is the wanted weight. (7) `termCopy` and `copyText` are twins by design (`terminal.html`
loads no manager script); the test tables must be identical so they cannot drift. (8) The export's trailing-blank
trim must never drop a real empty line inside the session (only the tail).

**Out of scope here.** `capture-session.html` (xterm too) gets no toolbar: no row asks for it; adding it later is
a copy of §1. Inspect-table and capture-dialog Copy (R013, C07) and the Container section (C04) only consume §2.
