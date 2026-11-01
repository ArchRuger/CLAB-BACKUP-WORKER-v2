# Sign-on: the pages and the interaction as the person sees them

Design slice of the sign-on stream, written 2026-11-01 against `main` at 1.31.8 (`fac28de`). It answers
`PROMPT.md` D1 to D3 and fits the facts in `INVENTORY.md` sections 2, 3 and 5. Every file:line below
refers to that commit. Sibling documents own the backend account, session and route model
(`DESIGN.md`) and TLS and exposure (`EXPOSURE.md`). This document assumes the backend contract the
lead gave (section 0.3) and lists every deviation it needs in section 12.

## 0. Scope, terms and the contract this design builds on

### 0.1 What this document decides

1. The sign-in page (section 1) and the first-run setup page (section 2).
2. What the running application does when its session ends (section 3).
3. Where the signed-in person appears in the header and what the menu offers (section 4).
4. The administrator's Users and Audit page (section 5).
5. The change-password dialog and sign-out (section 6).
6. Browser storage (section 7), wording (section 8), tests (section 9) and the reviewer's attack
   list (section 10).
7. Contract requests for `DESIGN.md` (section 12) and open questions for the lead (section 13).

### 0.2 Terms

| Term | Meaning in this document |
|---|---|
| *session* | The HttpOnly cookie the manager sets after a successful `POST /api/session`. The browser holds it; no script reads it. |
| *signed out* | The manager answered 401 with `{detail:{code:'signed_out'}}`, or a page was redirected to `/login`. |
| *Admin*, *Operator* | The two roles of D2. An Operator sees every lab; an Admin also manages people, the VM connection and the manager settings. |
| *the application* | `index.html` and its scripts (`INVENTORY.md` section 3). |
| *standalone page* | A page with its own small script: terminal, workspace, debug, vm-connection, capture-setup, capture-session, lab-builder, map-editor (`CLAUDE.md` "Frontend", item 1). |
| *the poll* | `refresh()` every 4 s (app.js:576). |
| `next` | The same-origin path (with search and hash) the sign-in page returns to after success. |
| *house style* | `'use strict'`, one statement per line, `esc()` on every interpolation, no inline styles, CSP `script-src 'self'` (`CLAUDE.md` "Frontend"). |

### 0.3 The backend contract assumed (from the lead)

1. `GET /login` serves the sign-in page. It is the only page reachable without a session.
2. `POST /api/session` with `{username,password}`: 200 `{user:{name,role}}` and the session cookie
   (HttpOnly, SameSite=Strict, Secure under TLS); 401 with one generic message on a wrong pair; 429
   with `retry_after` (seconds) when throttled.
3. `DELETE /api/session` with body `{}` signs out. `GET /api/session` returns the current user or 401.
4. Every other page and `/api/` route answers 401 JSON `{detail:{code:'signed_out'}}` without a
   session; a page is redirected to `/login?next=<path+hash>`. WebSockets refuse without a session.
5. Admin routes: `GET/POST /api/users`, `PATCH/DELETE /api/users/{name}`,
   `POST /api/users/{name}/password`, `POST /api/session/password` (own password), `GET /api/audit`.
6. A first-run bootstrap exists; the likely form is a one-time setup code printed by the installer
   that unlocks `/setup`.

Section 12 lists what this design needs beyond that contract.

### 0.4 Design stance

1. The sign-in page is the only thing an attacker gets to talk to (D3 item 2). It is small, static,
   has one script, and says nothing about the product beyond its name.
2. Nothing new is invented visually. The page reuses the tokens (style.css:55-120), the button
   classes (style.css:479-515), the form classes (style.css:1279-1330), the banner (style.css:935-975)
   and the standalone-page shell (style.css:2287-2322). A person who has seen the manager recognises
   the sign-in page; a person who has not learns nothing from it.
3. A session that ends mid-work never destroys what the person typed. Section 3.4 is the rule.
4. Every string is in the product's voice: short, concrete, no exclamation marks (the toasts in
   app.js:51 and shell.js:270-277 are the reference).

## 1. The sign-in page: `login.html` and `login.js`

### 1.1 Files and loading

| Item | Decision | Reason |
|---|---|---|
| Page file | `app/static/login.html`, served by `GET /login` (`FileResponse`, like `vm-connection.html` at main.py:501-502). | One template engine does not exist (`INVENTORY.md` 1); static HTML is the house way. |
| Script | `app/static/login.js`, `defer`, `?v=<release>`, the only script on the page. | `test_page_load_ui.js:10` pins the tag form `<script src="/static/X.js?v=…" defer></script>`; `verify-release.py:40-41` needs the page in its tuple (section 12, C1). |
| Stylesheet | `/static/style.css?v=<release>` (the whole sheet). | The page must look like the manager; a second sheet would drift. The sheet is 2760 lines and cached; the cost is one request on first load. |
| Icon | `/static/fabric-mark.svg` as favicon and brandmark, as index.html:3 and :24 do. | Same brand treatment. |
| Reachable without a session | `/login`, `/static/style.css`, `/static/login.js`, `/static/fabric-mark.svg`. Nothing else under `/static/` (section 12, C2). | D3 item 1: no static asset reveals the product beyond the sign-in page. `style.css` carries class names of the product; that is accepted (section 10, item 9). |
| CSP | The guard's CSP (main.py:154-155) unchanged: `script-src 'self'`, no inline styles. | Invariant. |
| `<title>` | `Sign in · Containerlab Node Manager` | Pattern of debug.html:2 (`Diagnostics · Containerlab Node Manager`). |

### 1.2 Layout

The page is `body.standalone-workspace.signin` (style.css:2287 gives the background) with one
`main.content.signin-page` holding one card. There is no header bar, no back link and no footer: the
page has nowhere else to go.

```
┌──────────────────────────────────────────────┐
│                                              │
│        [mark] Containerlab Node Manager      │   .brand (style.css:226-244), not a link
│                                              │
│   ┌──────────────────────────────────────┐   │
│   │ Sign in                              │   │   h1
│   │ Use the account your administrator   │   │   p (lead)
│   │ gave you.                            │   │
│   │                                      │   │
│   │ (Your session ended. Sign in again   │   │   #signin-reason, hidden unless ?reason=
│   │  to continue.)                       │   │
│   │                                      │   │
│   │ Username                             │   │   label
│   │ [__________________________________] │   │   #signin-user
│   │                                      │   │
│   │ Password                             │   │   label
│   │ [__________________________] [Show]  │   │   #signin-password + #signin-show
│   │                                      │   │
│   │ (Wrong username or password.)        │   │   #signin-error .form-error, role=alert
│   │                                      │   │
│   │ [          Sign in          ]        │   │   #signin-submit .button.primary
│   │                                      │   │
│   │ Forgot your password? Ask an         │   │   .form-help
│   │ administrator to reset it.           │   │
│   └──────────────────────────────────────┘   │
│                                              │
│   (This connection is not encrypted. …)      │   #signin-plain .banner.warn, hidden unless http:
└──────────────────────────────────────────────┘
```

Alignment: everything left-aligned inside the card; the card is centred on the page. Centred text is
not used (the product never centres a form).

Width: the card is `max-width: 440px`, with the page's 16 px gutter under 760 px. Inputs are 100 %
wide. The Sign in button is full width on every viewport: on a 390 px phone the existing rule
`.actions .button { flex: 1 1 auto }` (style.css:2449-2450) already does that, and on a desktop a
full-width button in a 440 px card reads as the one action the page has.

Vertical position: `margin-top: min(12vh, 96px)`, never vertically centred (a soft keyboard on a
phone would push a centred card off screen).

### 1.3 CSS additions (one new section 27 of style.css)

No new tokens. Values are taken from the classes they stand beside.

| Rule | Value | Source |
|---|---|---|
| `.signin-page` | `max-width: 440px; margin: min(12vh, 96px) auto 32px; padding: 0 16px;` | `.standalone-workspace main` (style.css:2288) overridden for width. |
| `.signin .brand` | `justify-content: center; margin: 0 0 20px; white-space: normal;` | `.brand` (style.css:226-241) is a flex row; the wrap is allowed at 390 px. |
| `.signin-card` | same declarations as `.debug-card` (style.css:2316): `background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius-lg); padding: 24px;` | One card look for standalone pages. Not reusing the class name `.debug-card` itself: that name is pinned by the debug report tests by position and should stay the diagnostics page's. |
| `.signin-card h1` | `margin: 0 0 6px;` | h1 is 22 px (style.css:179). |
| `.signin-card > p` | `margin: 0 0 16px; font-size: 13px; color: var(--muted);` | the lead sentence, like `.section-heading p` (style.css:1150). |
| `.signin-field` | `margin: 16px 0 0;` | the spacing of `dialog label` (style.css:1306-1312). |
| `.signin-field label` | `display: block; font-size: 12px; font-weight: 600; color: var(--ink); margin: 0 0 6px;` | same as the dialog label rule, which does not reach this page (no `dialog` ancestor). |
| `.signin-field input` | `width: 100%;` | like `dialog input` (style.css:1313). |
| `.signin-password` | `display: flex; gap: 8px; align-items: stretch;` | the input and the Show button on one row. |
| `.signin-password input` | `flex: 1 1 auto;` | |
| `.signin .actions` | `margin: 20px 0 0;` | `.dialog-actions` margin (style.css:556). |
| `.signin .actions .button` | `width: 100%;` | one action, full width. |
| `.signin .banner` | `margin-top: 16px;` | the plain-http notice under the card. |

No animation on the page. The global reduced-motion rule (style.css:2360-2363) covers the rest.

### 1.4 Markup (exact ids and classes)

```html
<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Sign in · Containerlab Node Manager</title><link rel="icon" type="image/svg+xml" href="/static/fabric-mark.svg"><link rel="stylesheet" href="/static/style.css?v=1.31.8"><script src="/static/login.js?v=1.31.8" defer></script></head>
<body class="standalone-workspace signin"><main class="content signin-page">
<div class="brand"><img class="brandmark" src="/static/fabric-mark.svg" alt="">Containerlab Node Manager</div>
<section class="signin-card" aria-labelledby="signin-title">
<h1 id="signin-title">Sign in</h1>
<p>Use the account your administrator gave you.</p>
<p id="signin-reason" class="form-help" role="status" hidden></p>
<form id="signin-form" novalidate>
<div class="signin-field"><label for="signin-user">Username</label><input id="signin-user" name="username" type="text" autocomplete="username" autocapitalize="none" autocorrect="off" spellcheck="false" maxlength="64" autofocus></div>
<div class="signin-field"><label for="signin-password">Password</label><div class="signin-password"><input id="signin-password" name="password" type="password" autocomplete="current-password" maxlength="128"><button type="button" class="button secondary" id="signin-show" aria-pressed="false" aria-controls="signin-password">Show</button></div></div>
<p id="signin-error" class="form-error" role="alert"></p>
<div class="actions"><button type="submit" class="button primary" id="signin-submit">Sign in</button></div>
</form>
<p class="form-help">Forgot your password? Ask an administrator to reset it.</p>
</section>
<div id="signin-plain" class="banner warn" role="status" hidden><p>This connection is not encrypted. Your password would travel in clear text. Ask the administrator to enable TLS before signing in from outside the lab network.</p></div>
</main></body></html>
```

Notes on the markup:

1. The brand is a `div`, not the `a.brand` of index.html:24: a link to `/` would bounce back to
   `/login`. The `.brand` rule applies to any element (style.css:226 is a class selector).
2. `novalidate` on the form: the empty-field message is the page's own (section 8), not the
   browser's bubble, so it is one voice and testable.
3. `autocomplete="username"` and `"current-password"` are what password managers key on. The form
   has no `action`: without JavaScript the page cannot work (the API takes JSON), and an accidental
   native post would send form-encoded data to `/api/session`.
4. `maxlength` equals the backend limits (section 12, C4) so the page never sends what the manager
   would refuse for length.
5. `autofocus` on the username: the page has one job. Screen readers announce the heading first
   because the card is `aria-labelledby`.
6. The Show button has text, not an icon: the product's buttons carry words (index.html:68-69).

### 1.5 Behaviour (`login.js`)

`login.js` is house style, `'use strict'`, one `const get=id=>document.getElementById(id)` as
debug.js:2 does, no inline styles, no `innerHTML`. Its pure functions are named for the tests.

| Function | Contract |
|---|---|
| `loginNext(search)` | Returns the safe `next` from a query string (section 1.6), or `'/'`. Pure. |
| `loginReason(search)` | Returns the sentence for `?reason=ended` (section 8) or `''`. Pure. |
| `loginCountdown(seconds)` | Returns the throttled sentence for a number of seconds (section 8). Pure. |
| `loginPlain(protocol, hostname)` | True when `protocol==='http:'` and `hostname` is not `localhost`, `127.0.0.1` or `::1`. Pure. |
| `loginSubmit(event)` | The submit handler below. |

Submit, in order:

1. `event.preventDefault()`.
2. Read the two fields. If either is empty after `trim()` on the username (the password is never
   trimmed): show *Enter your username and password.* in `#signin-error`, focus the empty field,
   stop.
3. Disable `#signin-submit`, set its text to *Signing in…* (the idle label is captured first, per
   DESIGN-SPEC-ADDENDUM A.4), clear `#signin-error`.
4. `fetch('/api/session',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username,password})})`.
   Default credentials (`same-origin`) carry and receive the cookie; no header is added (the guard
   of main.py:119-156 checks `Origin` and `sec-fetch-site` itself).
5. On 200: `location.replace(loginNext(location.search))`. `replace`, not `assign`: Back must not
   return to the sign-in page with the fields filled.
6. On 401: show *Wrong username or password.*; keep the username; clear the password; focus the
   password; restore the button.
7. On 429: read `retry_after` (integer seconds, default 60 when missing or not a number, capped at
   3600); show `loginCountdown(n)`; keep the button disabled; count down once per second with
   `setInterval`; at 0 clear the error, restore the button, focus the password. The person cannot
   submit before 0 (the button is disabled and the submit handler returns while a countdown runs).
8. On any other status, or a network failure: show *The manager did not answer. Try again.*;
   restore the button. The status code is not shown (the page says nothing about the product).
9. A 2xx with a body that is not JSON, or a 3xx, is treated as item 8.

Show password: `#signin-show` toggles `#signin-password.type` between `password` and `text`, sets
`aria-pressed` and its own text *Show* / *Hide*. Focus stays on the button. The field's value is
never read for this.

Enter submits: it is a form with one submit button, so the browser does it. No keydown handler
exists on the page (the reverse shortcut pin in `test_shell_ui.js:995-1021` scans every page script
for keydown sites; the page adds none).

Plain-HTTP notice: on load, if `loginPlain(location.protocol, location.hostname)` is true, unhide
`#signin-plain`. The form still works; the person is told. Under a self-signed certificate the page
shows nothing special: the browser's own interstitial already stood between the person and the page,
and the page cannot tell a self-signed certificate from a trusted one.

Reason line: on load, if `loginReason(location.search)` returns a sentence, put it in
`#signin-reason` and unhide it. The application adds `reason=ended` when it redirects after a 401
(section 3.3); the backend's own page redirect adds nothing (section 0.3 item 4).

Focus order: username, password, Show, Sign in. Nothing else on the page is focusable. The error
paragraph is `role="alert"` so a wrong pair is announced without moving focus away from the password.

### 1.6 `next`: what is accepted

`loginNext(search)` applies these rules to the raw `next` value (after `URLSearchParams` decoding):

1. Missing or empty: `'/'`.
2. Longer than 2000 characters: `'/'`.
3. Must start with `/`. Must not start with `//` or `/\` (protocol-relative forms). Must not
   contain `\`, a control character, or `:` before the first `/` (there is none: the value starts with
   `/`, so a scheme cannot appear; the check is kept for a value that was double-encoded).
4. Must not start with `/login` or `/setup` (a loop) and must not start with `/api/` (a JSON page
   is never a destination; the design export of network-design.js:1654 is reopened from the lab).
5. The value is used as given: path, search and hash. It is never resolved with `new URL(next,
   location)` and then compared, because that is where open redirects hide (`\` and `//` normalise
   differently across browsers). The string check above is the whole rule.

The application builds `next` as `encodeURIComponent(location.pathname+location.search+location.hash)`
(section 3.3). The hash carries the lab route (`#lab=…&view=…&device=…`, shell.js:15-17), so after
sign-in the person lands on the lab, tab and device they had open.

### 1.7 States of the page

| State | What is shown |
|---|---|
| Default | Empty fields, Sign in enabled, no error. |
| Empty submit | *Enter your username and password.*, focus on the empty field. |
| Sending | Sign in disabled, text *Signing in…*. |
| Wrong pair | *Wrong username or password.*, password cleared, username kept. One sentence for an unknown user, a wrong password and a deactivated account (section 12, C3). |
| Throttled | *Too many attempts. Try again in 42 s.*, counting down; Sign in disabled until 0. |
| Manager unreachable | *The manager did not answer. Try again.* |
| Plain HTTP | The warning banner under the card; the form works. |
| Returned after expiry | *Your session ended. Sign in again to continue.* above the fields. |
| Already signed in | Not handled by the page: `GET /login` with a valid session redirects to `/` (section 12, C5). |

## 2. The first-run setup page: `setup.html` and `setup.js`

### 2.1 Why a second page, not a mode of `login.html`

1. `login.js` stays the smallest script on the exposed surface. Setup fields and the policy check
   would double it.
2. `/setup` exists for minutes after installation and never again. `GET /setup` after the first
   admin exists redirects to `/login` (section 12, C6); the file and its script then have no route
   without a session, so they reveal nothing.
3. One test file per script, in the pattern of `test_debug_ui.js`.

The page shares `login.html`'s classes and layout exactly (section 1.2 and 1.3): `body.standalone-workspace.signin`,
`main.content.signin-page`, `.brand`, `section.signin-card`. Only the fields differ.

### 2.2 Markup

```html
<section class="signin-card" aria-labelledby="setup-title">
<h1 id="setup-title">Create the first administrator</h1>
<p>Enter the setup code the installer printed, then choose the account you will sign in with.</p>
<form id="setup-form" novalidate>
<div class="signin-field"><label for="setup-code">Setup code</label><input id="setup-code" name="code" type="text" autocomplete="one-time-code" autocapitalize="none" autocorrect="off" spellcheck="false" maxlength="64" autofocus><p class="form-help">Printed by <code>install-manager</code> on the VM, and in the installer's closing lines. It works once.</p></div>
<div class="signin-field"><label for="setup-user">Username</label><input id="setup-user" name="username" type="text" autocomplete="username" autocapitalize="none" autocorrect="off" spellcheck="false" maxlength="64"><p class="form-help">Letters, digits, dot, dash and underscore. 2 to 64 characters.</p></div>
<div class="signin-field"><label for="setup-password">Password</label><div class="signin-password"><input id="setup-password" name="password" type="password" autocomplete="new-password" maxlength="128"><button type="button" class="button secondary" id="setup-show" aria-pressed="false" aria-controls="setup-password setup-confirm">Show</button></div><p class="form-help" id="setup-policy">At least 12 characters. Any characters count; length matters more than symbols. Not your username, and not a common password.</p></div>
<div class="signin-field"><label for="setup-confirm">Password again</label><input id="setup-confirm" name="confirm" type="password" autocomplete="new-password" maxlength="128"></div>
<p id="setup-error" class="form-error" role="alert"></p>
<div class="actions"><button type="submit" class="button primary" id="setup-submit">Create account and sign in</button></div>
</form>
</section>
```

The same `#signin-plain` banner follows the card.

### 2.3 Password policy as the page states it

The policy is the backend's (section 12, C7); the page repeats it in one sentence and checks what it
can before sending, so the common mistakes never reach the manager:

| Check | Where | Message |
|---|---|---|
| Length ≥ 12 and ≤ 128 | page and manager | *Use at least 12 characters.* |
| The two entries match | page | *The two passwords are not the same.* |
| Not equal to the username, case-insensitive, and the username is not inside it | page and manager | *Choose a password that is not your username.* |
| Not in the manager's short deny-list (about 100 entries: `password`, `12345678…`, `containerlab`, `admin1234`, the product name) | manager only | *That password is too common. Choose another.* |
| No composition rule (no required digit, symbol or case) | both | none; the help sentence says so |

The deny-list stays on the manager: sending it to the browser would publish it on the exposed
surface, and the manager must check anyway.

Username rule as shown: `^[A-Za-z0-9][A-Za-z0-9._-]{1,63}$`, checked by the page with *Use letters,
digits, dot, dash or underscore, 2 to 64 characters.* and by the manager.

### 2.4 Behaviour (`setup.js`)

| Function | Contract |
|---|---|
| `setupProblem(username, password, confirm)` | Returns the first failing message of section 2.3 (page checks only) or `''`. Pure. |
| `setupSubmit(event)` | Below. |

Submit, in order:

1. `preventDefault()`. If the code is empty: *Enter the setup code.*, focus it, stop. If
   `setupProblem(...)` returns a message: show it, focus the field it names, stop.
2. Disable the button (*Creating…*). `POST /api/setup` with `{code,username,password}`.
3. 200: the manager has set the session cookie for the new admin (section 12, C6);
   `location.replace('/')`. The person lands on Home signed in. No welcome toast: Home's own empty
   state (*Works with Junos, IOS-XR and Arista EOS*, DESIGN-SPEC-ADDENDUM A.6) is the welcome.
4. 403 (wrong code): *That setup code is not right. Check the installer's output.* The code field
   is cleared and focused. The username and password stay.
5. 429: as the sign-in page, with its countdown.
6. 409 (an admin exists already): *The first account was already created. Sign in instead.* with
   a link to `/login` placed in the error line as text (the sentence is set with `textContent`; the
   link is a static `<a id="setup-signin" href="/login" hidden>` after the error, unhidden here).
7. 422 (the manager refused the username or the password): the manager's `detail.message` as given
   (its sentences are the ones in section 2.3). The page never shows a stack or a code.
8. Other or network: *The manager did not answer. Try again.*

The code is never stored, never put in the URL and never echoed back.

Show toggles both password fields at once (`aria-controls` names both).

## 3. Signed out while the application runs

### 3.1 The one shared behaviour

Every request helper does the same four things on `401` + `{detail:{code:'signed_out'}}`:

1. Mark the page as signed out, so no further request is sent by a poll or a heartbeat.
2. Keep what the person typed (section 3.4).
3. Tell the person once.
4. Offer the sign-in page with `next` pointing back here.

What differs per page is only whether item 4 is a redirect or a link (section 3.5).

### 3.2 Where the code lives: `session.js`

A new plain script `app/static/session.js`, loaded with `?v=` by every page that sends a request
(index.html, workspace.html, debug.html, lab-builder.html, map-editor.html, terminal.html,
capture-session.html, capture-setup.html if it fetches). On index.html it is listed after
`status.js` and before `shell.js` (index.html:3), so `shell.js` and `app.js` may call it.

| Global | Contract |
|---|---|
| `sessionLost(status, data)` | True when `status===401` and `data` is an object whose `detail.code==='signed_out'`. Pure. (A 401 of any other shape is a plain error: the capture relay's own refusals keep their wording.) |
| `loginUrl(pathname, search, hash, reason)` | `'/login?next='+encodeURIComponent(pathname+search+hash)` plus `&reason=ended` when `reason` is truthy. Pure. The page never passes an absolute URL; the sign-in page re-checks anyway (section 1.6). |
| `sessionEnded()` | True once `sessionMark()` was called on this page. |
| `sessionMark()` | Sets the flag. Returns true the first time, false after (so the caller tells the person once). |
| `sessionClear()` | Clears the flag (a request succeeded again, section 3.6). |
| `sessionGo(reason)` | `location.replace(loginUrl(location.pathname, location.search, location.hash, reason))`, under `typeof location!=='undefined'`. The only place in `session.js` that touches `location`. |

Rule for J1 (DESIGN-SPEC-ADDENDUM:99-101): `app.js` gains no top-level side effect and calls
`session.js` and `shell.js` only through `typeof x==='function'` guards. `session.js` has no top-level
side effect either, and its one `location` access is inside `sessionGo()`, so every node harness that
loads `app.js` without it keeps working. This is an amendment of J1's letter ("everything that touches
`location` lives in `shell.js`") and is written up in section 12 (C13) for the lead: the standalone
pages need the same function, and `shell.js` is not loaded there.

### 3.3 The application (`index.html`)

1. `api()` (app.js:52-63) gains one line after the status check, before the error is thrown:
   `if(response.status===401&&typeof sessionLost==='function'&&sessionLost(401,data)&&typeof signedOut==='function')signedOut();`.
   The error is still thrown (`error.status=401`, `error.message` = *Your session ended. Sign in
   again.*), so every existing `catch` runs as it does today; its toast is harmless because the page
   is leaving or already shows the banner.
2. `refresh()` (app.js:91) gains a first line: `if(typeof sessionEnded==='function'&&sessionEnded())return;`.
   The interval at app.js:576 keeps ticking; it makes no request. This is what stops the 4 s poll
   from storming the sign-in page (section 10, item 4): after the first 401 there is no second request
   from this page.
3. `refreshLogs()` (app.js:564-571) and the device drawer's diagnostics polls go through `api()`, so
   they stop by the same rule; the scheduling site of the device drawer's poll (device-diagnostics.js:316,
   which calls the pure planner `diagPollNext`, :22) must check `sessionEnded()` before it schedules
   the next fetch, as the drawer checks `pageVisible()` today (shell.js:295-298).
4. `signedOut()` lives in `shell.js` (it decides between a navigation and a banner, and it reads the
   DOM for open dialogs):

```
function signedOut(){
 if(typeof sessionMark!=='function'||!sessionMark())return false;          // once
 closeMenus();
 const dialog=typeof document!=='undefined'&&typeof document.querySelector==='function'?document.querySelector('dialog[open]'):null;
 const draft=typeof designLeaveGuard==='function'&&designLeaveGuard();
 if(!dialog&&!draft){if(typeof sessionGo==='function')sessionGo('ended');return true;}
 renderSessionBanner();return true;
}
```

5. The banner is static markup in index.html, directly after `#operation-summary` (index.html:63),
   above `#home` and `#lab-content` so it shows on Home and on a lab page alike (the rule of A.11):

```html
<div id="session-banner" class="banner danger" role="alert" hidden><svg class="icon" width="16" height="16" aria-hidden="true"><use href="#i-alert"></use></svg><div><p id="session-banner-text">Your session ended. What you typed in the open dialog is still here.</p><p class="caption">Sign in in a new tab, come back and choose Try again. Or sign in here and lose the open dialog.</p></div><div class="banner-actions"><a class="button primary small" id="session-signin-tab" href="/login" target="_blank" rel="noopener noreferrer">Sign in in a new tab <span aria-hidden="true">↗</span></a><button type="button" class="button secondary small" id="session-retry">Try again</button><button type="button" class="button ghost small" id="session-signin-here">Sign in here</button></div></div>
```

   A modal dialog (`showModal`, the pattern of management.js:153, 195, 218) makes everything outside
   it inert, so a page-level banner would be unreachable while the dialog is open, and closing the
   dialog would lose its fields. `renderSessionBanner()` (shell.js) therefore does one of two things:
   - An open `dialog[open]` exists: it appends a clone of `#session-banner` (`cloneNode(true)`, id
     `session-banner-dialog`, `hidden=false`) as the first child of that dialog, inside the modal focus
     scope, and focuses the clone's *Try again*. The three buttons carry `data-session-action` (`tab`,
     `retry`, `here`); one click listener on the clone (added when it is created) dispatches on that
     attribute, so the clone needs no per-id binding. The ids inside the clone are rewritten with the
     suffix `-dialog` so no id exists twice (J2). The dialog's `close` event (the person pressed
     Escape or Cancel while signed out) removes the clone and shows the page-level banner instead.
   - No dialog is open (the cause is an unstored design draft): `#session-banner.hidden=false`, focus
     on `#session-retry`. The same `data-session-action` listener sits on the static banner.
   The clone is removed when the session is restored (section 3.6).
6. `#session-signin-tab` opens `/login` in a new tab with no `next` (the new tab lands on Home;
   the person comes back to this tab). `rel="noopener noreferrer"` as index.html:48-52 do.
7. `#session-retry` calls `sessionRetry()`: `sessionClear()` then `refresh()`. On 200 the poll runs
   again, the banner hides and the clone is removed; on a new 401 `signedOut()` runs again (the flag
   was cleared, so `sessionMark()` is true again and the banner stays).
8. `#session-signin-here` calls `sessionGo('ended')`: the dialog is lost by the person's choice.
9. Listener count: the banner's buttons are bound with `onclick` on the elements or a listener on
   the banner element, never `document.addEventListener`, so the pin of nine document and window
   listeners in `test_shell_ui.js:947-954` stays true. If the lead prefers delegation on `document`,
   that pin is rewritten to ten with the reason, never deleted.

### 3.4 What is kept

| Content | Where it is | Rule |
|---|---|---|
| Lab builder drawing | `localStorage clab-builder:draft:*` (shell.js:323 family, reset `false`) | Already stored by the editor on every change; a redirect loses nothing. When `builderUnstored` is set (lab-builder-page.js:12, the browser could not store), the page shows the banner instead of redirecting. |
| Network design draft | `localStorage clab.design.draft.<lab>` (shell.js:254-267) | Already stored; `designLeaveGuard()` is true only when the browser could not store it (shell.js:278-280), and then `signedOut()` shows the banner, not a redirect. |
| An open dialog's fields (VM connection, credentials, import, deploy review, capture, rename…) | In memory only | The banner path (section 3.3 item 5). Nothing is written to storage: a dialog can hold a password. |
| The map editor's unsaved map (`mapIsDirty`, map-editor-page.js:21) | In memory | Banner, not redirect (section 3.5). |
| A terminal's screen | In the pop-up | Not navigated away; the message replaces the status line (section 3.5). |
| The route (lab, tab, device) | The hash | Carried in `next` (section 1.6). |

### 3.5 Each standalone page

| Page | Helper | On `sessionLost` |
|---|---|---|
| workspace.js:6 `api()` | add the check | `sessionGo('ended')` at once: the page holds nothing typed. |
| debug.js:7-14 `debugFetch()` | add the check | `sessionGo('ended')`. |
| lab-builder-page.js:17 `api()` | add the check | `sessionGo('ended')` when `builderUnstored===null`; else the page's existing problem overlay (`builderPaused`, lab-builder-page.js:15) with the banner sentence and the *Sign in in a new tab* link, and `builderPaused` stays set until a request succeeds. |
| map-editor-page.js:13-16 `api()` | add the check | When `mapIsDirty(mapBaseline,mapCurrent)` is false: `sessionGo('ended')`. When true: `mapPaused=true` (map-editor-page.js:8), the status pill reads *Editing paused* (mapStatusView, line 23) and a toast carries the sentence with the new-tab link; Save tries again after `sessionClear()` on the next click. |
| terminal.js:46 ticket `POST` | `response.status===401` and `sessionLost` | `setStatus('Your session ended. Sign in again in the lab manager, then click Reconnect.')` through the status map (terminal.js:29-34 gets one more row). No navigation: this is a pop-up (app.js:410-411); the opener holds the sign-in. |
| terminal.js:51 WebSocket | close frame reason `signed_out` (section 12, C9) | The `onclose` path (terminal.js:55) keeps the reason after *Disconnected —*; the row above maps `signed_out` to the same sentence. |
| capture-session.js:7 `status()`, :28 asset probe, :56 download, :69 end | `sessionLost` | `$('viewer-status').textContent` = *Your session ended. Sign in again in the lab manager, then click Reconnect viewer.*; `clearInterval(heartbeat)` (line 79) so the 30 s heartbeat stops; `ended` stays false so Reconnect viewer (a `location.reload()`, line 65) can work after a sign-in elsewhere. The capture owner cookie (`capture_sessions.py:24`, `:113`) is separate and untouched: a session that ends does not end the capture; the person signs in again and the owner cookie still matches (section 10, item 2). |
| vm-connection.html, capture-setup.html | no fetch today (`INVENTORY.md` 3) | Redirected by the manager before they load (section 0.3 item 4). |

### 3.6 Coming back

1. A request that succeeds after `sessionClear()` hides `#session-banner`, removes the dialog clone
   and lets the poll run. `render()` does not touch the banner (it is owned by `shell.js`, like the
   action-error banner, shell.js:281-288).
2. A page that redirected returns through `next` to the same route; `applyRoute()` (shell.js:32-51)
   opens the lab, tab and device from the hash as on any load.
3. No toast *Signed in again*: the restored page is the evidence.

## 4. The account in the header

### 4.1 Where the name appears

Two places, both static markup, text set by `render()` (J3: the header is never re-rendered with
`innerHTML`, DESIGN-SPEC-ADDENDUM:112):

1. In the top bar, before the Manager button: `<span class="account-chip" id="account-chip" hidden></span>`
   inside `.topbar-right` (index.html:26) with the person's name as text. Hidden under 900 px (the
   topbar is 48 px, index.html:23, style.css:211-222; at 760 px the crumbs already take the width).
   Reason: on a shared classroom computer the person must see who is signed in without opening a
   menu; the role is not shown here (it is not needed to recognise oneself).
2. In the Manager ▾ menu, a new group after Diagnostics and before `.menu-foot` (index.html:54-55):

```html
        <a role="menuitem" href="/static/debug.html">Diagnostics</a>
        <hr class="menu-sep" role="separator">
        <div class="menu-account" role="group" aria-labelledby="account-name"><p id="account-name"></p><p id="account-role" class="caption"></p></div>
        <a role="menuitem" id="account-users" href="/static/users.html" hidden>People and sign-ins…</a>
        <button type="button" role="menuitem" id="account-password">Change password…</button>
        <button type="button" role="menuitem" id="account-signout">Sign out</button>
        <div class="menu-foot" role="group" aria-label="Manager status">…</div>
```

   `#account-name` is the name (`state.user.name`), `#account-role` reads *Administrator* or
   *Operator*. `#account-users` is unhidden only for `state.user.role==='admin'`; an Operator never
   sees it (and the manager refuses the page anyway, section 5.5).

CSS: `.menu-account { padding: 8px 12px 4px; }`, `.menu-account p { margin: 0; font-size: 13px;
color: var(--ink); font-weight: 600; }`, `.menu-account .caption { font-weight: 400; margin-top: 2px; }`
— the menu's `p` rule (style.css:642) adds a top border and muted colour to a direct `p` child of the
list; the account block is a `div`, so it takes its own rule. `.account-chip { font-size: 13px;
color: var(--muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 180px; }`
and `@media (max-width: 900px) { .account-chip { display: none; } }`.

### 4.2 Why under Manager ▾ and not a second menu

1. The top bar has one menu button today (index.html:29); a second (an avatar menu) adds a control to
   a 48 px bar that is already full at 760 px.
2. The Manager menu is the place of everything that is not a lab (index.html:31-55); the account is
   not a lab.
3. The menu footer already carries the manager's identity (`#vm-summary`, `#app-version`,
   index.html:55); the person's identity sits just above it.

### 4.3 Keyboard behaviour (J4, DESIGN-SPEC-ADDENDUM:118-120)

Nothing new: `initMenu` (shell.js:79-123) treats every `[role="menuitem"]` that is not disabled or
hidden as an item (shell.js:89); the account block is not an item (it is a `div`, not focusable) and
is skipped by Arrow keys, Home and End. `#account-users` is an `a[role=menuitem]` like Diagnostics
(index.html:54): Enter activates it, Space is handled by shell.js:108. Click on an item closes the
menu first and returns focus to the button (shell.js:121), so the change-password dialog gives focus
back to Manager ▾ when it closes.

### 4.4 `render()` additions (app.js:144)

One function `renderAccount()` in app.js, called from `render()` next to `#app-version`
(app.js:147), guarded by `if($('account-name'))`. It sets text and `hidden` only:

```
function roleLabel(role){return role==='admin'?'Administrator':role==='operator'?'Operator':'';}
function renderAccount(){
 const user=state.user||null,name=user&&typeof user.name==='string'?user.name:'';
 if($('account-chip')){$('account-chip').textContent=name;$('account-chip').hidden=!name;}
 if($('account-name'))$('account-name').textContent=name;
 if($('account-role'))$('account-role').textContent=roleLabel(user&&user.role);
 if($('account-users'))$('account-users').hidden=!(user&&user.role==='admin');
 for(const id of ['vm-settings','manager-settings'])menuReason($(id),user&&user.role==='operator'?'Administrators only':'');
}
```

`state.user` comes with `/api/state` (section 12, C8): one request, and a role change or a
deactivation reaches the menu on the next poll (a deactivated person gets a 401 instead, section 3).

Operator gating of *VM connection…* (index.html:31) and *Manager settings…* (index.html:42): the
items stay visible and become disabled with the visible reason *Administrators only* through
`menuReason()` (app.js:86), the pattern of every disabled menu item (DESIGN-SPEC-ADDENDUM J2, last
bullet). Disabled, not hidden: an Operator should know the setting exists and who to ask. The manager
refuses the routes with 403 regardless (section 12, C3).

## 5. The administrator's page: `users.html` and `users.js`

### 5.1 A standalone page, not panels in Advanced

1. The Advanced tab belongs to one lab (`PANELS`, app.js:10); people and sign-ins belong to the
   manager. The Manager ▾ menu already sends the manager-level pages out of `index.html`
   (Diagnostics, index.html:54; the full-page browser, A.7).
2. `index.html` stays lean: the page is 300+ lines of static markup already, and every id in it is
   load-bearing (J2).
3. An Operator who types the URL gets one refusal page (section 5.5), not an empty panel in a tab.
4. The debug page is the template: `debug.html` (12 lines; `body.standalone-workspace`,
   `main.content.debug-page`, `.workspace-back`, `section.debug-card` with a form) and `debug.js`
   with `test_debug_ui.js`.

Reached from Manager ▾ › *People and sign-ins…* (section 4.1). Title *People and sign-ins ·
Containerlab Node Manager*; h1 *People and sign-ins*; back link `a.workspace-back[href="/"]` *← Back
to My labs* (debug.html:4).

### 5.2 Layout

Two sections, in `.debug-card`s under `main.content.debug-page`:

```
← Back to My labs
Manager                                     (.eyebrow, kept for this page as style.css:190-191 says)
People and sign-ins                         h1
Who can sign in to this manager, and what happened at the sign-in page.

┌ People ─────────────────────────────────────────────── [Add a person…] ┐
│ Name      Role           Status   Last sign-in         Actions          │
│ sam       Administrator  Active   Today 09:12         [Change role…] [Reset password…] [Deactivate] │
│ jo        Operator       Inactive 3 days ago          [Change role…] [Reset password…] [Reactivate] │
│ #users-status (caption, role=status)                                    │
└─────────────────────────────────────────────────────────────────────────┘

┌ Sign-ins and changes ──────────────────────────────────────────────────┐
│ Show [Last 24 hours ▾]  Person [________]  Event [All ▾]  Outcome [All ▾]  Address [________]  [Apply] │
│ Time (UTC)        Person   Event              Outcome    Source address   Details                     │
│ 2026-11-01 09:12  sam      Signed in          Succeeded  203.0.113.7                                  │
│ 2026-11-01 09:10  —        Sign-in attempt    Throttled  198.51.100.9     12 attempts in 60 s          │
│ #audit-status (caption)                                                 │
└─────────────────────────────────────────────────────────────────────────┘
```

Tables use `.table-wrap` (style.css:1350-1370; `min-width: 730px` under 760 px, style.css:2455, so
they scroll sideways on a phone). Row actions are `.button.secondary.small` (style.css:515).

### 5.3 Ids and the dialogs

| Id | Element | Purpose |
|---|---|---|
| `users-rows` | `tbody` | People rows, built with `createElement`/`textContent` like debug.js:35-44 (no `innerHTML`; a name is untrusted text). |
| `users-status` | `p.caption[role=status]` | *2 people · updated 09:14* or an error sentence. |
| `users-add` | `button.button.primary` | Opens `#user-dialog` empty. |
| `user-dialog` | `dialog` with `.dialog-head` (style.css:1585-1588) | Add a person. Fields `user-name` (`autocomplete="off"`), `user-role` (`select`: Operator, Administrator; default Operator), `user-password` + `user-confirm` (`autocomplete="new-password"`) with the policy sentence of section 2.3, `user-error`, actions *Cancel* / *Add person*. |
| `role-dialog` | `dialog` | Change role: the name as `<strong>`, `role-select`, *Cancel* / *Change role*. |
| `reset-dialog` | `dialog` | Reset password: the name, `reset-password` + `reset-confirm` (`new-password`), the sentence *They must choose a new password the next time they sign in.*, `reset-error`, *Cancel* / *Set password*. (Not `password-dialog`: that id is the change-password dialog of index.html, section 6.1; the pages are separate documents, but one name per thing keeps the tests and the wording table unambiguous.) |
| `active-dialog` | `dialog` | Deactivate: the name, *Their open sessions end now. Their labs stay.* *Cancel* / *Deactivate* (`.button.danger`, A.16). Reactivate reuses it with *Reactivate* (`.button.primary`). |
| `audit-rows` | `tbody` | Audit rows, text only. |
| `audit-since`, `audit-actor`, `audit-event`, `audit-outcome`, `audit-address`, `audit-apply` | filters, inside `form#audit-form` | Submit (`Enter` in any field or Apply) builds the query. |
| `audit-status` | `p.caption[role=status]` | *118 events shown (latest 500 matching). Updated 09:14.* — the wording of `#log-status` (app.js:569). |
| `users-forbidden` | `section.debug-card` hidden | Shown instead of both sections on 403 (section 5.5). |

Every dialog has `class="icon-button close" aria-label="Close"` in its head, as `test_shell_ui.js:861`
pins for the index.html dialogs; the same pin is extended to this page (section 9).

### 5.4 Rules the page enforces as the person sees them

| Rule | How it shows |
|---|---|
| Never delete the last admin; never deactivate or demote them | The *Deactivate* and *Change role…* buttons of the only active admin are disabled with `title` and a visible `<small class="menu-reason">`-style caption under the row: *The last administrator stays.* The manager refuses with 409 anyway (section 12, C10) and the page shows that sentence. |
| Your own account | *Deactivate* on your own row is disabled: *Sign out instead.* *Change role…* on your own row is disabled: *Ask another administrator.* (You could demote yourself out of the page.) |
| A deactivated person's sessions end | The confirmation says so (section 5.3). The manager does it (section 12, C10). |
| Reset password | The admin types a temporary password and tells the person. The manager sets `must_change` (section 12, C11); the person's next sign-in opens the change-password dialog with no Cancel (section 6.3). The page never displays a generated password: the admin chose it, so there is nothing to show once. |
| No delete | There is no Delete button. `DELETE /api/users/{name}` stays for the API; the page offers Deactivate, which keeps the audit trail readable (a name in the audit table should still resolve to a person). Open question Q3. |
| Add a person | `POST /api/users {name, role, password, must_change:true}`; the new person must change the password at first sign-in. The dialog says so. |

After every change the page reloads both lists (`usersRefresh()`); a success is a toast through the
page's own `notify()` (the pattern of workspace.js:5) with the sentences of section 8.

### 5.5 Operator or signed out

1. 401 `signed_out` → `sessionGo('ended')` (section 3.5).
2. 403 → both cards hidden, `#users-forbidden` shown: *Only administrators can open this page.* with
   the back link. The menu item is hidden for an Operator (section 4.4), so this is reached by URL only.

### 5.6 The audit table's vocabulary

The manager records events by code (section 12, C12); the page translates them, like
`debugCheckNames` (debug.js:16-20):

| Event code | Shown as | Outcome codes shown as |
|---|---|---|
| `signin` | Signed in | `succeeded`, `failed` → *Succeeded*, *Failed* |
| `signin_throttled` | Sign-in attempt | *Throttled* |
| `signout` | Signed out | *Succeeded* |
| `session_expired` | Session ended | *Idle* / *Everywhere* (the detail says which) |
| `password_changed` | Password changed | *Succeeded* / *Failed* (wrong current) |
| `password_reset` | Password reset by an administrator | *Succeeded* |
| `user_created` | Person added | *Succeeded* |
| `user_role` | Role changed | *Succeeded* |
| `user_deactivated` | Deactivated | *Succeeded* |
| `user_reactivated` | Reactivated | *Succeeded* |
| `setup` | First administrator created | *Succeeded* / *Failed* (wrong code) |
| unknown | the code itself | the code itself |

A failed sign-in row shows the username *as typed* only when it matched an existing account;
otherwise *—* (section 12, C12: the manager records `actor: null` for an unknown name, so a scanner's
guesses do not fill the table with junk and a typo'd password does not reveal usernames to anyone
with the page open). The source address is text; IPv6 addresses wrap (`overflow-wrap: anywhere` of
`.debug-card dd`, style.css:2321, is applied to the cell).

## 6. Change password and sign out

### 6.1 The dialog (index.html, static)

```html
<dialog id="password-dialog" aria-labelledby="password-title"><div class="dialog-head"><div><h2 id="password-title">Change password</h2></div><button type="button" class="icon-button close" id="password-close" aria-label="Close">×</button></div>
<p id="password-lead">Choose a new password for your account.</p>
<form id="password-form" novalidate>
<label for="password-current">Current password</label><input id="password-current" type="password" autocomplete="current-password" maxlength="128">
<label for="password-new">New password</label><input id="password-new" type="password" autocomplete="new-password" maxlength="128"><p class="form-help">At least 12 characters. Any characters count; length matters more than symbols. Not your username, and not a common password.</p>
<label for="password-confirm">New password again</label><input id="password-confirm" type="password" autocomplete="new-password" maxlength="128">
<label class="checkbox-label"><input type="checkbox" id="password-everywhere" checked>Also sign out my other browsers and devices</label>
<p id="password-error" class="form-error" role="alert"></p>
<div class="dialog-actions"><button type="button" class="button secondary" id="password-cancel">Cancel</button><button type="submit" class="button primary" id="password-submit">Change password</button></div>
</form></dialog>
```

Styling comes from the dialog rules (style.css:1568-1588, labels 1306-1313, `.checkbox-label`
1319-1326, `.form-error` 1328, `.form-help` 1330, `.dialog-actions` 556). The dialog sits after
`</main>` (index.html:319) with the other dialogs (`test_shell_ui.js:864` pins that a dialog is never
inside a tab panel).

### 6.2 Behaviour (`account.js`, a new feature script of the page)

A new script `account.js` loaded after `preferences.js` (index.html:3) holds the account functions
so `app.js` does not grow; it follows the pattern of `preferences.js` (`prefsOpen`, preferences.js:133-138:
`showModal` behind a `typeof` guard). Globals: `accountOpenPassword(options)`, `accountSignOut()`,
`passwordProblem(username, current, next, confirm)` (pure; the checks of section 2.3 plus *Enter
your current password.* and *The new password is the same as the current one.*).

1. Manager ▾ › *Change password…* → `accountOpenPassword()`: clears the fields and the error,
   `showModal()`, focus on `#password-current`.
2. Submit: `passwordProblem()` first; then `POST /api/session/password`
   `{current, password, everywhere}` (section 12, C11).
   200 → close, toast *Password changed.* (plus *Other sessions were signed out.* when the box was
   ticked, as one toast: *Password changed. Other sessions were signed out.*).
   403 → *The current password is not right.*, focus `#password-current`.
   422 → the manager's `detail.message` (section 2.3 sentences). 429 → the throttled sentence
   without a countdown (the dialog is not the sign-in page; the person waits and tries again).
3. Cancel and × close without a request.

### 6.3 Must change at first sign-in

When `state.user.must_change` is true (section 12, C11), `render()` opens the dialog once per page
load (`accountOpenPassword({required:true})`): the lead reads *Choose a new password before you
continue. The one you signed in with was set by an administrator.*; Cancel and × are hidden; Escape
is swallowed by the dialog's `cancel` event. The manager also refuses every other mutating route with
403 `{code:'password_change_required'}` until it is done (section 12, C11), so the lock is not only in
the browser. After success `must_change` clears on the next poll and the dialog closes.

### 6.4 Sign out

Manager ▾ › *Sign out* → `accountSignOut()`:

1. `sessionMark()` first, so the poll stops before the cookie is gone (otherwise the poll's 401 would
   race the navigation and add `reason=ended` to a sign-out).
2. `DELETE /api/session` with body `{}` (the guard needs a body, main.py:119-156).
3. On any answer, including a failure: `location.replace('/login')` through a `shell.js` function
   `goSignIn()` (no `next`, no reason: a person who signed out lands on a clean sign-in page).
   A failed `DELETE` is reported nowhere: the browser leaves; the cookie, if it survived, is the
   manager's to expire (section 12, C14: a sign-out must succeed or the session must be short).
4. Terminal pop-ups and capture viewers opened by this tab: the manager ends their sockets when the
   session ends (section 12, C9); their pages show the sentence of section 3.5. The application does
   not try to close them (`window.open` returns a handle the page does not keep, app.js:410-411).
5. *Sign out everywhere* is not a separate menu item: it is the checkbox in the change-password
   dialog and the administrator's Deactivate. A person who suspects a stolen session changes the
   password; that is the right reflex and the one action that helps.

## 7. Storage

1. No token is ever written to `localStorage` or `sessionStorage`. The cookie is HttpOnly; no script
   can read it, and nothing else identifies the session.
2. No new storage key. `next` rides in the URL (section 1.6), so `clab.login.next` is not needed; the
   reason rides in the URL too. Remembering the username is rejected: classroom computers are shared.
3. `PREFERENCE_FAMILIES` (shell.js:318-333) is unchanged. The forward storage pin
   (`test_shell_ui.js:955-978`) scans every `app/static/*.js` for `setItem` and `shellSet`; `login.js`,
   `setup.js`, `session.js`, `account.js` and `users.js` call none, so the pin passes without an
   addition. A test asserts that directly (section 9.1).
4. `sessionStorage.activeLab` (shell.js:35-36) is not touched by sign-out; the route is in the hash.
   After a sign-out and a sign-in by another person on the same browser, the stored lab id could open
   that lab for the second person. Decision: `accountSignOut()` calls `shellRemove('sessionStorage','activeLab')`
   before leaving (the key is `reset:false` in the families because it is data, not a preference; the
   sign-out is not a preferences reset). The opened-dates and dismissed notices (`clab.opened.*`,
   `clab.dismissed.*`) stay: they are harmless and shared labs are the model (D2).

## 8. Wording

Every new string. Product voice: short, concrete, sentence case, no exclamation marks. Where a string
is the manager's (422 messages), the manager uses the same text (section 12, C7).

| Where | Id or place | Text |
|---|---|---|
| login.html | title | Sign in · Containerlab Node Manager |
| login.html | h1 | Sign in |
| login.html | lead | Use the account your administrator gave you. |
| login.html | labels | Username / Password |
| login.html | `#signin-show` | Show / Hide |
| login.html | `#signin-submit` | Sign in / Signing in… |
| login.html | help | Forgot your password? Ask an administrator to reset it. |
| login.js | empty | Enter your username and password. |
| login.js | 401 | Wrong username or password. |
| login.js | 429 | Too many attempts. Try again in {n} s. |
| login.js | other | The manager did not answer. Try again. |
| login.js | `#signin-reason` for `reason=ended` | Your session ended. Sign in again to continue. |
| login.html | `#signin-plain` | This connection is not encrypted. Your password would travel in clear text. Ask the administrator to enable TLS before signing in from outside the lab network. |
| setup.html | title | First administrator · Containerlab Node Manager |
| setup.html | h1 | Create the first administrator |
| setup.html | lead | Enter the setup code the installer printed, then choose the account you will sign in with. |
| setup.html | code help | Printed by `install-manager` on the VM, and in the installer's closing lines. It works once. |
| setup.html | username help | Letters, digits, dot, dash and underscore. 2 to 64 characters. |
| setup.html, dialogs | policy | At least 12 characters. Any characters count; length matters more than symbols. Not your username, and not a common password. |
| setup.html | `#setup-submit` | Create account and sign in / Creating… |
| setup.js | empty code | Enter the setup code. |
| setup.js | 403 | That setup code is not right. Check the installer's output. |
| setup.js | 409 | The first account was already created. Sign in instead. |
| setup.js, users.js, account.js | length | Use at least 12 characters. |
| same | match | The two passwords are not the same. |
| same | username | Choose a password that is not your username. |
| same (manager) | deny-list | That password is too common. Choose another. |
| same | username rule | Use letters, digits, dot, dash or underscore, 2 to 64 characters. |
| app.js `api()` | 401 error message | Your session ended. Sign in again. |
| index.html | `#session-banner-text` | Your session ended. What you typed in the open dialog is still here. |
| index.html | banner caption | Sign in in a new tab, come back and choose Try again. Or sign in here and lose the open dialog. |
| index.html | banner caption, draft case | Your session ended. Your design draft is still on this page. (set by `renderSessionBanner()` when the cause is the draft, not a dialog) |
| index.html | `#session-signin-tab` | Sign in in a new tab ↗ |
| index.html | `#session-retry` | Try again |
| index.html | `#session-signin-here` | Sign in here |
| terminal.js | status | Your session ended. Sign in again in the lab manager, then click Reconnect. |
| capture-session.js | viewer status | Your session ended. Sign in again in the lab manager, then click Reconnect viewer. |
| map-editor-page.js | toast | Your session ended. Sign in in a new tab, then save again. |
| lab-builder-page.js | overlay | Your session ended. Your drawing is kept in this browser. Sign in in a new tab, then continue. |
| index.html | `#account-chip` | {name} |
| index.html | `#account-role` | Administrator / Operator |
| index.html | `#account-users` | People and sign-ins… |
| index.html | `#account-password` | Change password… |
| index.html | `#account-signout` | Sign out |
| app.js | reason on VM connection… and Manager settings… for an Operator | Administrators only |
| index.html | `#password-title` | Change password |
| index.html | `#password-lead` | Choose a new password for your account. |
| account.js | `#password-lead` when required | Choose a new password before you continue. The one you signed in with was set by an administrator. |
| index.html | labels | Current password / New password / New password again |
| index.html | `#password-everywhere` | Also sign out my other browsers and devices |
| index.html | `#password-submit` | Change password / Changing… |
| account.js | empty current | Enter your current password. |
| account.js | same | The new password is the same as the current one. |
| account.js | 403 | The current password is not right. |
| account.js | 429 | Too many attempts. Wait a minute, then try again. |
| account.js | toast | Password changed. / Password changed. Other sessions were signed out. |
| users.html | title | People and sign-ins · Containerlab Node Manager |
| users.html | h1 | People and sign-ins |
| users.html | lead | Who can sign in to this manager, and what happened at the sign-in page. |
| users.html | card 1 | People |
| users.html | columns | Name / Role / Status / Last sign-in / Actions |
| users.js | status values | Active / Inactive |
| users.js | last sign-in | Never / the relative time (`relativeTimeShort` of status.js, loaded by the page) |
| users.html | `#users-add` | Add a person… |
| users.html | `#user-dialog` title | Add a person |
| users.html | `#user-dialog` sentence | They must choose a new password the first time they sign in. |
| users.html | `#user-dialog` actions | Cancel / Add person |
| users.js | toast | {name} added. |
| users.html | row actions | Change role… / Reset password… / Deactivate / Reactivate |
| users.html | `#role-dialog` | Change role / Cancel / Change role |
| users.js | toast | {name} is now an administrator. / {name} is now an operator. |
| users.html | `#reset-dialog` | Reset password / They must choose a new password the next time they sign in. / Cancel / Set password |
| users.js | toast | Password set for {name}. |
| users.html | `#active-dialog` deactivate | Deactivate {name}? / Their open sessions end now. Their labs stay. / Cancel / Deactivate |
| users.html | `#active-dialog` reactivate | Reactivate {name}? / They can sign in again with their current password. / Cancel / Reactivate |
| users.js | toasts | {name} deactivated. / {name} reactivated. |
| users.js | last admin | The last administrator stays. |
| users.js | own row | Sign out instead. / Ask another administrator. |
| users.js | 409 from the manager | the same two sentences as above (the manager sends the code, the page the sentence) |
| users.js | `#users-status` | {n} people · updated {time} |
| users.html | card 2 | Sign-ins and changes |
| users.html | filters | Show (Last hour / Last 24 hours / Last 7 days / All) / Person / Event (All + the list of 5.6) / Outcome (All / Succeeded / Failed / Throttled) / Address / Apply |
| users.html | columns | Time (UTC) / Person / Event / Outcome / Source address / Details |
| users.js | `#audit-status` | {n} events shown (latest 500 matching). Updated {time}. |
| users.js | empty | No events match. Change the filters. |
| users.html | `#users-forbidden` | Only administrators can open this page. |
| users.js | load failure | The list could not be loaded: {detail} |

## 9. Tests

### 9.1 Node harnesses (`node --test tests/*.js`)

| New or changed file | Harness to copy | What it pins |
|---|---|---|
| `tests/test_login_ui.js` (new) | `test_debug_ui.js:4-13` (`fixture(fetch)`: a `Map` of fake elements, `vm.createContext` with `document`, `fetch`, `setTimeout`) plus a fake `location` `{search,protocol,hostname,replace(url){calls.push(url)}}` and a `setInterval` that the test ticks. | `loginNext`: `/`, `/#lab=a&view=devices`, `/static/workspace.html#mode=ssh` pass; `//evil`, `/\evil`, `https://evil`, `javascript:…`, `/login`, `/api/state`, a 3000-char path, missing → `/`. `loginPlain`. Empty submit shows the sentence and sends nothing. 401 keeps the username, clears the password, shows *Wrong username or password.* 429 with `retry_after:3` shows *Try again in 3 s*, button disabled, after three ticks enabled and the error empty. 200 calls `location.replace` with the safe `next`. Source pin: no `innerHTML`, no `style=`, no `localStorage`/`sessionStorage`, no `addEventListener('keydown'`. |
| `tests/test_setup_ui.js` (new) | same | `setupProblem` for each message; 403 clears and focuses the code; 409 unhides `#setup-signin`; 200 → `location.replace('/')`; the code never appears in `location` calls or storage. |
| `tests/test_session_ui.js` (new) | `test_operations_ui.js` (pure functions) | `sessionLost` shapes (401 without the code is false; 403 is false); `loginUrl` encoding of path, search and hash; `sessionMark` once; `sessionGo` under a fake `location`. |
| `tests/test_users_ui.js` (new) | `test_debug_ui.js` | Rows are text (a name `<b>x</b>` renders as text); the last-admin and own-row buttons are disabled with the sentences; 403 shows `#users-forbidden`; the audit query string carries the filters; unknown actor shows *—*; event codes map to the labels. |
| `tests/test_account_ui.js` (new) | `test_readiness_ui.js` (loads `status.js` and `app.js` together) + `account.js` | `passwordProblem`; `roleLabel`; `renderAccount` hides `#account-users` for an operator and sets the chip; `must_change` opens the dialog once with Cancel hidden; sign-out marks the session before `DELETE` and calls `goSignIn` after a failed `DELETE` too. |
| `tests/test_shell_ui.js` (changed) | its own harness (43-84): add `#session-banner` with its three buttons, `data-session-action`, and the `sessionMark`/`sessionClear`/`sessionGo` stubs to the context | `signedOut()` with no open dialog calls `sessionGo('ended')`; with `dialog.open` shows the banner clone inside the dialog and does not navigate; a second call does nothing; `sessionRetry` on 200 hides the banner and removes the clone. **Rewrite, never delete**: the menu-order pin at :846-859 (`Diagnostics` last) becomes "Diagnostics is the last item before the account group" with the new ids in order; the listener-count pin at :947-954 stays at nine unless the lead chooses document delegation (then ten, with the reason). |
| `tests/test_page_load_ui.js` (changed) | its own `loadPage()` (24-43) | `session.js` is listed between `status.js` and `shell.js`, `account.js` after `preferences.js`; no top-level name collides (the `get` of login.js is a file-local `const`: login.js is never loaded with the page, but `session.js` and `account.js` are, so their names must be unique: `sessionLost`, `loginUrl`, `sessionEnded`, `sessionMark`, `sessionClear`, `sessionGo`, `accountOpenPassword`, `accountSignOut`, `passwordProblem`, `roleLabel`, `renderAccount`). `api()` on a 401 `signed_out` stub calls `signedOut` (set a counter on the context) and still throws with `status 401`. `refresh()` sends nothing once `sessionEnded()` is true. The pin at :207-210 (no page other than index.html loads `device-diagnostics.js`) is unchanged; a sibling pin says no page other than `index.html` loads `account.js`, and every page that fetches loads `session.js` with the one `?v=`. Add `login.html`, `setup.html`, `users.html` to the standalone list the harness iterates for `?v=` and inline styles (:212-228 does that for lab-builder.html; the sweep at `test_shell_ui.js:879` already covers foreign assets on every `.html`). |
| `tests/test_debug_ui.js`, `test_terminal_ui.js`, `test_capture_session_ui.js`, `test_map_editor_ui.js`, `test_lab_builder_ui.js` (changed) | each its own | one test each: a 401 `signed_out` answer produces the page's sentence (section 3.5) and, where the page redirects, one `location.replace` call to `/login?next=…`; the terminal and the capture viewer never navigate. |

Python side (the backend designer's, listed so the lead can route it): `test_app.py` gains the
session fixture (`client.post('/api/session', json=…)`), and every existing test that calls a route
signs in first through a helper; TestClient keeps the cookie jar.

### 9.2 Playwright checks under `docs/sign-on/tools/`

One script `check_signon.py` in the shape of `docs/ui-review-001/tools/check_ui001.py` against
`docs/redesign/tools/fixture_manager.py` (with a fixture flag that seeds one admin and one operator
and prints the setup code; section 13, Q5), at the four viewports 1440×900, 1280×800, 760×1024,
390×844:

| Check | Assertion |
|---|---|
| Sign-in page | `/` redirects to `/login?next=%2F`; the card is within the viewport; no horizontal scroll at 390; the brand and the h1 are visible; focus is on `#signin-user`. |
| Wrong password | `#signin-error` reads *Wrong username or password.*; `#signin-user` keeps its value; `#signin-password` is empty and focused. |
| Throttling | After the fixture's limit, `#signin-error` matches `/Try again in \d+ s\./`, `#signin-submit` is disabled; after the countdown it is enabled. |
| Sign-in and `next` | Visit `/#lab=<id>&view=devices` signed out → `/login?next=%2F%23lab%3D…`; sign in → URL is `/#lab=<id>&view=devices`, the Devices tab is active, `#account-chip` shows the name at 1440 and 1280 and is hidden at 760 and 390. |
| Open redirect | `/login?next=//example.org` then sign in → the URL is `/`. Same for `/login?next=/api/state`. |
| 401 mid-work | Open the VM connection dialog, type into a field, expire the session through the fixture (`POST /__fixture/expire`), wait 6 s → one `GET /api/state` request after expiry, no more (the fixture counts); the banner clone is inside `#vm-dialog`; the typed value is still there. Click *Try again* after signing in in a second context (same browser context, new page) → the banner is gone, polling resumed. |
| Sign out | Manager ▾ › Sign out → `/login` with no `next`; `GET /api/state` answers 401; the Back button does not show the application. |
| Users page as admin | `#account-users` visible; the page lists two people; the only admin's Deactivate is disabled with the sentence; add, role change, reset and deactivate each produce their toast; the audit table shows the sign-ins of this run with the operator's failed attempt and a throttled row. |
| Users page as operator | `#account-users` hidden; `/static/users.html` shows `#users-forbidden`; *VM connection…* and *Manager settings…* are disabled with *Administrators only*. |
| Terminal pop-up | Open a CLI (fixture device), expire the session → the status line reads the sentence, the pop-up is still on `terminal.html`. |
| Student guide | With the fixture's PDF staged, the Help link downloads it when signed in and redirects to `/login?next=%2Fstudent-guide` when not. |
| Keyboard | On `/login`: Tab order user → password → Show → Sign in; Enter in the password field submits. In Manager ▾: ArrowDown reaches *Change password…* and *Sign out*, skips the account block; Escape returns focus to the button. |
| Screenshots | each viewport: `/login` default and error, the Manager menu open with the account group, the session banner in a dialog, `users.html`. |

Evidence goes to `docs/sign-on/evidence/<date>/` as the other campaigns do; the script prints its
assertion table and exit status.

## 10. What a reviewer should attack

1. **Lost functionality after sign-in.** Every page of the inventory (`INVENTORY.md` 3) must work with
   a session and nothing else changed: the hash route and `sessionStorage.activeLab` precedence
   (shell.js:29-36), the Progress-tab aliases (`TAB_ALIAS`, `SAVE_ROUTES`, app.js:11-14), the
   terminal pop-ups (`window.open`, app.js:410-411: a new window shares the cookie; the ticket POST
   at terminal.js:46 carries it by default), the CLI launcher's `rel="opener"` links
   (workspace.js:13), the design export opened in a new tab (network-design.js:1654: the cookie goes
   with it; a signed-out person gets the page redirect, lands on `/` after sign-in, section 1.6 item
   4), the download `<a href>` of the capture viewer (capture-session.js:22, 59), the student guide
   link (index.html:48, `/student-guide` at main.py:505: same-origin navigation, cookie carried).
2. **Capture sessions.** The viewer's owner cookie (`capture_sessions.py:24`, `:113`) is a second
   cookie. A manager session that ends must not end the capture container (the person may be
   capturing for an hour); a manager session that is *another person's* must not open the viewer of a
   capture they do not own (the owner cookie still decides). Attack: sign out, sign in as someone
   else in the same browser, open the old viewer link.
3. **Open redirect through `next`.** Section 1.6. Try `//`, `/\`, `/%2F%2F`, `%5C`, a double-encoded
   scheme, a `next` inside a `next`, a 10 000-character value, a value with `\r\n`. The rule is a
   string check; the attack is a browser that normalises differently.
4. **The poll storming the sign-in page.** After a 401 the page must send no second `GET /api/state`
   (section 3.3 item 2) and no other request from the device drawer, the logs, the capture session
   list (`refreshCaptureSessions`, capture.js) or the save header's watch (`gitStartWatch`); every
   one of them goes through `api()` and is guarded by `sessionEnded()`? The reviewer lists each
   `setInterval` and `setTimeout` chain in the page scripts and checks the guard. Also: ten tabs of
   the application open at once, each redirecting to `/login` at the same moment, is ten requests, not
   a storm.
5. **CSRF.** SameSite=Strict blocks a cross-site POST from carrying the cookie; the guard's
   `Origin`/`sec-fetch-site` check (main.py:119-156) blocks the rest; `DELETE /api/session` is a
   mutating request that needs the `{}` body. Attack: a top-level navigation `GET` that mutates
   (none should exist); a `GET /api/...` that returns a page a browser would execute; the sign-in
   POST itself being made cross-site to log the victim into the attacker's account (login CSRF:
   the guard already refuses a foreign `Origin` on `/api/`; confirm it covers `POST /api/session`).
6. **Username enumeration.** The wrong-pair message, the throttling counters and the response
   timing must not differ between an unknown name, a wrong password and a deactivated account
   (section 12, C3). The audit table shows `—` for unknown names (section 5.6).
7. **The banner-in-dialog path.** A modal dialog with the clone inside: can the clone's *Sign in in a
   new tab* link be reached by keyboard? Does `cloneNode` carry the `data-session-action` attributes
   and does the delegated handler on the clone work? Does closing the dialog (Escape) while signed
   out leave the page without any banner and without polling? (Decision: the dialog's `close` shows
   the page-level `#session-banner`.)
8. **Password managers.** Chrome, Firefox and Safari must offer to save after a successful sign-in
   (`autocomplete` attributes, `location.replace` after success) and must fill the change-password
   dialog correctly (`current-password` then `new-password`).
9. **What the sign-in page reveals.** `style.css` is public and names every feature class; the
   favicon names nothing. Decision: accepted. The reviewer says whether a trimmed `login.css` is
   worth the second stylesheet (section 13, Q2).
10. **Reduced motion, contrast, 390 px.** No animation on the new pages; `.form-error` on `--surface`
    is the existing contrast; the Show button and the input share a row at 390 px without overflow;
    the users tables scroll sideways rather than squeeze.
11. **`must_change` lock.** With the dialog open and required, can the person use the menus behind it?
    (A modal dialog blocks them.) Can they navigate the hash to a lab and act? (The manager refuses
    mutating routes with 403 until the change.)
12. **Two people, one browser.** Sign out, sign in as another: no trace of the first in the page
    (`activeLab` removed, section 7 item 4; `state` replaced by the first poll; the header text set by
    `render()`; the capture memory keys are per lab and harmless).

## 11. File inventory of this design

| File | New or changed | Owner (lead to route) |
|---|---|---|
| `app/static/login.html`, `login.js` | new | UI builder |
| `app/static/setup.html`, `setup.js` | new | UI builder |
| `app/static/session.js` | new | UI builder |
| `app/static/account.js` | new | UI builder |
| `app/static/users.html`, `users.js` | new | UI builder |
| `app/static/index.html` | changed: scripts (session.js, account.js), `#account-chip`, the account menu group, `#session-banner`, `#password-dialog` | UI builder |
| `app/static/app.js` | changed: `api()` 401 line, `refresh()` guard, `renderAccount()` + `roleLabel()`, call in `render()` | UI builder |
| `app/static/shell.js` | changed: `signedOut()`, `renderSessionBanner()`, `sessionRetry()`, `goSignIn()` | UI builder |
| `app/static/style.css` | changed: section 27 (sign-in, account block, chip) | UI builder |
| `app/static/workspace.js`, `debug.js`, `lab-builder-page.js`, `map-editor-page.js`, `terminal.js`, `capture-session.js`, `device-diagnostics.js` | changed: the one 401 check each | UI builder |
| the standalone `.html` pages | changed: load `session.js` | UI builder |
| `deploy/verify-release.py:40-41` | the three new pages in the tuple | the lead (release owner) |
| `.github/workflows/release-check.yml` | the five new test files on the `node --test` line | the lead |
| `tests/*` of section 9 | new and changed | test engineer |
| `docs/sign-on/tools/check_signon.py` | new | QA |

## 12. Contract requests for `DESIGN.md`

Each item is something this design needs that section 0.3 does not state. The backend designer
decides the mechanism; the UI depends on the behaviour.

| Id | Request | Why |
|---|---|---|
| C1 | `login.html`, `setup.html` and `users.html` are static files under `app/static`, served at `/login`, `/setup` and `/static/users.html`; the lead adds the first two to `verify-release.py`'s tuple (:40-41) and `set-release.py`. | `?v=` on every asset is checked only for listed pages (`INVENTORY.md` 5). |
| C2 | Without a session, exactly these are reachable: `GET /login`, `GET /setup` (while open), `GET /static/style.css`, `/static/login.js`, `/static/setup.js` (while open), `/static/fabric-mark.svg`, `POST /api/session`, `POST /api/setup`. Every other `/static/*` file, including `index.html` and the editor bundle, needs a session. | D3 item 1. |
| C3 | One 401 body for an unknown name, a wrong password and a deactivated account; equal throttling and no measurable timing difference (hash a dummy for unknown names). Role refusals answer 403 `{detail:{code:'forbidden',message:'Administrators only.'}}`. | No enumeration (section 10, item 6); the UI shows one sentence. |
| C4 | Limits the pages mirror: username 2–64 chars `^[A-Za-z0-9][A-Za-z0-9._-]{1,63}$`; password 12–128 chars; `retry_after` an integer ≤ 3600. | `maxlength` and the countdown cap. |
| C5 | `GET /login` and `GET /setup` with a valid session redirect to `/`. | A bookmark to the sign-in page must not show it to a signed-in person. |
| C6 | `POST /api/setup {code,username,password}`: 200 `{user}` and the session cookie; 403 wrong code (throttled like sign-in, 429 with `retry_after`); 409 when an admin exists; 422 `{detail:{code,message}}` for a refused username or password. `GET /setup` after setup → 302 `/login`. The code is single-use and expires (the installer prints it; the health check reports whether setup is still open). | Section 2. |
| C7 | The password policy and its sentences (section 2.3) are the manager's; 422 carries `detail.message` with exactly those sentences so the pages show the manager's own words. The deny-list stays server-side. | One voice; the deny-list is not published. |
| C8 | `GET /api/state` includes `user:{name,role,must_change}`. | One request; the role is live on the poll (section 4.4). |
| C9 | A WebSocket refused for a missing or ended session closes with code 1008 and reason `signed_out`; ending a session (sign-out, deactivation, password change with `everywhere`) closes that session's open terminal and capture sockets within 5 s. | The terminal and viewer sentences (section 3.5). |
| C10 | `PATCH /api/users/{name}` `{role}` or `{active}`; 409 `{code:'last_admin'}` when it would remove the last active admin; 409 `{code:'self'}` when an admin deactivates or demotes themselves; deactivation ends the person's sessions. `GET /api/users` rows `{name,role,active,created,last_signin,sessions}`. | Section 5.4. |
| C11 | `must_change` on a user: set by `POST /api/users` and `POST /api/users/{name}/password`; cleared by `POST /api/session/password {current,password,everywhere}`; while set, every mutating route except that one answers 403 `{code:'password_change_required'}`. `everywhere:true` ends the person's other sessions. | Sections 5.4, 6.2, 6.3. |
| C12 | `GET /api/audit?since=<iso>&actor=&event=&outcome=&address=&limit=` (≤ 500, newest first) rows `{time,actor,event,outcome,address,detail}`; `actor` is `null` for a sign-in attempt whose name matched no account; events and outcomes are the codes of section 5.6; `detail` is controlled metadata only (never a password or a user-agent string longer than 200 chars). | Section 5.6; the logs invariant (`CLAUDE.md`). |
| C13 | Amendment of DESIGN-SPEC-ADDENDUM J1: `session.js` is a second shared script (after `status.js`, before `shell.js`) with no top-level side effect whose one `location` access is inside `sessionGo()`; the standalone pages load it too. | Section 3.2. |
| C14 | `DELETE /api/session` always clears the cookie (also when the session is already gone); sessions have an idle timeout the UI does not need to know (open question Q1) and an absolute lifetime. | Section 6.4 item 3. |
| C15 | A page request (`GET`, `Accept` includes `text/html`) without a session redirects with 302 to `/login?next=<path>`; the manager builds `next` from the request path only (the hash never reaches it). Everything else answers the 401 JSON. `/student-guide` and `/api/labs/<id>/design/export` are page requests. | Section 0.3 item 4 made precise; section 10 item 1. |
| C16 | The capture viewer's HTTP routes and websockify require the manager session *and* the owner cookie; a manager session that ends does not end the capture container. | Section 10, item 2. |

## 13. Open questions for the lead

| Id | Question | This design's default |
|---|---|---|
| Q1 | Should the application warn before an idle timeout (a *Still there?* banner), which needs `expires` in `GET /api/session` and a timer in `shell.js`? | No for the first version: the banner-in-dialog path (section 3.3) makes an expiry mid-work recoverable without a warning. |
| Q2 | A trimmed `login.css` instead of the full `style.css` on the exposed page? | Full `style.css` (section 1.1); the reviewer weighs it (section 10, item 9). |
| Q3 | Should the Users page offer Delete at all? | No (section 5.4); Deactivate keeps the audit readable. The API route stays for the backend designer's reasons. |
| Q4 | Account chip in the top bar (section 4.1 item 1): keep, or menu only? | Keep, hidden under 900 px. |
| Q5 | The fixture manager needs a seeded admin and operator, a printed setup code and a `/__fixture/expire` hook for the Playwright checks (section 9.2). Who owns that change to `docs/redesign/tools/fixture_manager.py`? | The QA worker, with the backend designer's hook. |
| Q6 | `account.js` as a separate page script (section 6.2) or inside `preferences.js`? | Separate: one owner per concern, and `test_page_load_ui.js` already pins `preferences.js` by position (:243). |
| Q7 | Does the Diagnostics page (`debug.html`) stay reachable for an Operator? It shows versions, VM flags and request metadata. | Yes for both roles: a student needs it to report a problem; it holds no secret (debug.html:5, 10). The lead may restrict it. |
| Q8 | The `.eyebrow` class is "kept for the diagnostics page only" (style.css:190). `users.html` reuses it for *Manager*. Accept, or drop the eyebrow on the new page? | Reuse; the comment is updated to name both pages. |
