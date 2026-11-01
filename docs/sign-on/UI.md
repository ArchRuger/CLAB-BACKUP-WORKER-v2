# Sign-on: the pages and the interaction as the person sees them

Design slice of the sign-on stream, written 2026-11-01 against `main` at 1.31.8 (`fac28de`). It answers
`PROMPT.md` D1 to D3 and fits the facts in `INVENTORY.md` sections 2, 3 and 5. Every file:line below
refers to that commit. Sibling documents own the backend account, session and route model
(`DESIGN.md`) and TLS and exposure (`EXPOSURE.md`). This document assumes the backend contract the
lead gave (section 0.3) and lists every deviation it needs in section 12.

Amended with the lead's rulings of RECONCILIATION.md (2026-11-01).
Amended with the answers of REVIEW.md (2026-11-01).

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
| *restricted session* | A session whose user has `must_change_password` (an admin created the account or reset its password). It can reach the rows reachable without a session (section 12, C2: the sign-in page and its three assets, `POST`/`GET`/`DELETE /api/session`, `GET /api/health`) plus `POST /api/session/password`, and nothing else (REVIEW R1). It never reaches the application. |
| *Admin*, *Operator* | The two roles of D2. An Operator sees every lab; an Admin also manages people, the VM connection and the manager settings. |
| *the application* | `index.html` and its scripts (`INVENTORY.md` section 3). |
| *standalone page* | A page with its own small script: terminal, workspace, debug, vm-connection, capture-setup, capture-session, lab-builder, map-editor (`CLAUDE.md` "Frontend", item 1). |
| *the poll* | `refresh()` every 4 s (app.js:576). |
| `next` | The same-origin path (with search and hash) the sign-in page returns to after success. |
| *house style* | `'use strict'`, one statement per line, `esc()` on every interpolation, no inline styles, CSP `script-src 'self'` (`CLAUDE.md` "Frontend"). |

### 0.3 The backend contract assumed (from the lead)

1. `GET /login` serves the sign-in page to a browser without a session and to a restricted session;
   an unrestricted session gets `302 /`. It is the only page reachable without a session.
2. `POST /api/session` with `{username,password}`: 200 `{user:{name,role,must_change_password},expires}`
   and the session cookie (HttpOnly, SameSite=Strict, Secure under TLS); 401
   `{detail:{code:'invalid_credentials',message}}` on a wrong pair (one body for an unknown name, a
   wrong password and a deactivated account); 429 `{detail:{code:'throttled',retry_after,message}}`
   when throttled (`retry_after` in seconds).
3. `DELETE /api/session` with body `{}` signs out (always 200, also clears `clab_capture_owner`,
   REVIEW R10). `GET /api/session` returns 200 `{user,expires}` or 401 `{detail:{code:'signed_out'}}`.
4. Every other page and `/api/` route answers 401 JSON `{detail:{code:'signed_out',message}}` without
   a session; a page request (a `GET` or `HEAD` whose `Accept` includes `text/html`) is redirected to
   `/login?next=<path+search>`, every other request answers 401 JSON (section 12, C15). A restricted
   session gets `302 /login?change=1&next=<path+search>` for a page request and 403
   `{detail:{code:'password_change_required',message}}` for anything else (REVIEW R1). WebSockets
   close 1008 without a session (`signed_out`) and for a restricted one (`password_change_required`).
5. Admin routes: `GET/POST /api/users`, `PATCH/DELETE /api/users/{name}`,
   `POST /api/users/{name}/password`, `GET /api/audit`. Any signed-in session, a restricted one
   included: `POST /api/session/password` (own password, DESIGN 7.3).
6. A first-run bootstrap exists: a one-time setup code written to `<DATA_DIR>/setup-code`, printed at
   the very end of the installation, unlocks `/setup`; the recovery command writes a new one and
   prints `https://<address>:<UI_PORT>/setup?recover=1` (REVIEW R11, U13).
7. Every 4xx body the sign-on code sends carries `detail.message`, one sentence per code and reason,
   with the texts of section 8; a 422 joins the sentences of its reasons (REVIEW U11). The pages show
   `detail.message` and use a sentence of their own only when there is none (a network failure, a
   non-JSON body).

Section 12 lists what this design needs beyond that contract.

### 0.4 Design stance

1. The sign-in page is the only thing an attacker gets to talk to (D3 item 2). It is small, static,
   has one script, and says nothing about the product beyond its name.
2. Nothing new is invented visually, but the exposed pages do not load `style.css`: it names every
   feature of the product, and the sign-in page is the one surface a scanner sees. `login.css` is a
   small self-contained sheet that copies the tokens (style.css:55-120) and the few rules the page
   needs (section 1.3); `style.css` stays behind the session. A person who has seen the manager
   recognises the sign-in page; a person who has not learns nothing from it.
3. A session that ends mid-work never destroys what the person typed. Section 3.4 is the rule.
4. Every string is in the product's voice: short, concrete, no exclamation marks (the toasts in
   app.js:51 and shell.js:270-277 are the reference).

## 1. The sign-in page: `login.html` and `login.js`

### 1.1 Files and loading

| Item | Decision | Reason |
|---|---|---|
| Page file | `app/static/login.html`, served by `GET /login` (`FileResponse`, like `vm-connection.html` at main.py:501-502). | One template engine does not exist (`INVENTORY.md` 1); static HTML is the house way. |
| Script | `app/static/login.js`, `defer`, `?v=<release>`, the only script on the page. | `test_page_load_ui.js:10` pins the tag form `<script src="/static/X.js?v=…" defer></script>`; `verify-release.py:40-41` needs the page in its tuple (section 12, C1). |
| Stylesheet | `/static/login.css?v=<release>` (section 1.3); `style.css` is not loaded. | RECONCILIATION 1 and 2: `style.css` names every feature of the product; `login.css` copies only the tokens and rules the page needs, so the page still looks like the manager. |
| Icon | `/static/fabric-mark.svg` as favicon and brandmark, as index.html:3 and :24 do. | Same brand treatment. |
| Reachable without a session | `/login`, `/static/login.css`, `/static/login.js`, `/static/fabric-mark.svg`. Nothing else under `/static/` (section 12, C2). | D3 item 1: no static asset reveals the product beyond the sign-in page. `login.css` names no selector of the application (section 1.3, section 10, item 9). |
| CSP | The guard's CSP (main.py:154-155) unchanged: `script-src 'self'`, no inline styles. | Invariant. |
| `<title>` | `Sign in` | RECONCILIATION 2: the title is what a scanner indexes. The brand mark and the product name appear on the page itself, so a student recognises where they are. |

### 1.2 Layout

The page is `body.signin` (`login.css` gives the background) with one
`main.signin-page` holding one card. There is no header bar, no back link and no footer: the
page has nowhere else to go.

```
┌──────────────────────────────────────────────┐
│                                              │
│        [mark] Containerlab Node Manager      │   .brand (login.css), not a link
│                                              │
│   ┌──────────────────────────────────────┐   │
│   │ Sign in                              │   │   h1
│   │ Use the account your administrator   │   │   p (lead)
│   │ gave you.                            │   │
│   │                                      │   │
│   │ (Checking…)                          │   │   #signin-checking, shown until GET /api/session answered (1.5)
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

The change view (REVIEW R1) is a second card in the same `main`, shown in place of the first when the
session is restricted (section 1.8):

```
│   ┌──────────────────────────────────────┐   │
│   │ Choose your own password             │   │   h1 (#change-title)
│   │ The password you signed in with was  │   │   p (lead)
│   │ set by an administrator. Choose your │   │
│   │ own before you continue.             │   │
│   │                                      │   │
│   │ Current password                     │   │   #change-current-field, hidden unless the page was reloaded
│   │ [__________________________________] │   │
│   │ New password                         │   │
│   │ [__________________________] [Show]  │   │   #change-new + #change-show
│   │ At least 12 characters. …            │   │   #change-policy .form-help
│   │ New password again                   │   │
│   │ [__________________________________] │   │   #change-confirm
│   │ (The two passwords are not the same.)│   │   #change-error .form-error, role=alert
│   │ [ Change password and continue     ] │   │   #change-submit .button.primary
│   │ [ Sign out                         ] │   │   #change-signout .button.secondary
│   └──────────────────────────────────────┘   │
```

Alignment: everything left-aligned inside the card; the card is centred on the page. Centred text is
not used (the product never centres a form).

Width: the card is `max-width: 440px`, with the page's 16 px gutter under 760 px. Inputs are 100 %
wide. The Sign in button is full width on every viewport (`.signin .actions .button { width: 100% }`,
section 1.3): a full-width button in a 440 px card reads as the one action the page has.

Vertical position: `margin-top: min(12vh, 96px)`, never vertically centred (a soft keyboard on a
phone would push a centred card off screen).

### 1.3 `login.css`: the sheet of the exposed pages

`login.css` is a small self-contained sheet (RECONCILIATION 2). It holds: the colour, spacing, radius
and font tokens copied verbatim from `style.css` `:root` (style.css:55-120); their dark-scheme
overrides; and the rules for `body`, the card, the form fields, the primary button (and the secondary
Show button), the error and help lines, the banner and the brand mark. Nothing else. The Source
column names where a value was copied from; no selector of the application is copied. A test
asserts that `login.css` names no selector of the application (`#save-chip`, `.topbar`, `.panel`, …;
section 9.1). `style.css` section 27 keeps only the account block and the chip for `index.html`
(section 4.1). `login.html` and `setup.html` load `login.css`, never `style.css`.

| Rule | Value | Source |
|---|---|---|
| `.signin-page` | `max-width: 440px; margin: min(12vh, 96px) auto 32px; padding: 0 16px;` | `main` of the standalone pages (style.css:2288), copied with the width changed. |
| `.signin .brand` | `justify-content: center; margin: 0 0 20px; white-space: normal;` | `.brand` (style.css:226-241) is a flex row; the wrap is allowed at 390 px. |
| `.signin-card` | same declarations as `.debug-card` (style.css:2316): `background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius-lg); padding: 24px;` | One card look for standalone pages. Not reusing the class name `.debug-card` itself: that name is pinned by the debug report tests by position and should stay the diagnostics page's. |
| `.signin-card h1` | `margin: 0 0 6px;` | h1 is 22 px (style.css:179). |
| `.signin-card > p` | `margin: 0 0 16px; font-size: 13px; color: var(--muted);` | the lead sentence, like `.section-heading p` (style.css:1150). |
| `.signin-field` | `margin: 16px 0 0;` | the spacing of `dialog label` (style.css:1306-1312). |
| `.signin-field label` | `display: block; font-size: 12px; font-weight: 600; color: var(--ink); margin: 0 0 6px;` | same as the dialog label rule, which does not reach this page (no `dialog` ancestor). |
| `.signin-field input` | `width: 100%;` | like `dialog input` (style.css:1313). |
| `.signin-password` | `display: flex; gap: 8px; align-items: stretch;` | the input and the Show button on one row. |
| `.signin-password input` | `flex: 1 1 auto;` | |
| `.signin .actions` | `margin: 20px 0 0; display: grid; gap: 8px;` | `.dialog-actions` margin (style.css:556); the grid stacks the change view's two buttons (REVIEW R1) one under the other at every width. |
| `.signin .actions .button` | `width: 100%;` | one action, full width. |
| `.signin .banner` | `margin-top: 16px;` | the plain-http notice under the card. |
| `.sr-only` | copied verbatim from style.css:162-169 | the seconds a screen reader hears once in the throttled sentence (REVIEW U15). |

No animation on the page. The global reduced-motion rule (style.css:2360-2363) covers the rest.

### 1.4 Markup (exact ids and classes)

```html
<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Sign in</title><link rel="icon" type="image/svg+xml" href="/static/fabric-mark.svg"><link rel="stylesheet" href="/static/login.css?v=1.31.8"><script src="/static/login.js?v=1.31.8" defer></script></head>
<body class="signin"><main class="signin-page">
<div class="brand"><img class="brandmark" src="/static/fabric-mark.svg" alt="">Containerlab Node Manager</div>
<section class="signin-card" id="signin-card" aria-labelledby="signin-title">
<h1 id="signin-title">Sign in</h1>
<p>Use the account your administrator gave you.</p>
<p id="signin-checking" class="form-help" role="status">Checking…</p>
<p id="signin-reason" class="form-help" role="status" hidden></p>
<form id="signin-form" novalidate hidden>
<div class="signin-field"><label for="signin-user">Username</label><input id="signin-user" name="username" type="text" autocomplete="username" autocapitalize="none" autocorrect="off" spellcheck="false" maxlength="32"></div>
<div class="signin-field"><label for="signin-password">Password</label><div class="signin-password"><input id="signin-password" name="password" type="password" autocomplete="current-password" maxlength="128"><button type="button" class="button secondary" id="signin-show" aria-pressed="false" aria-controls="signin-password">Show</button></div></div>
<p id="signin-error" class="form-error" role="alert"></p>
<div class="actions"><button type="submit" class="button primary" id="signin-submit">Sign in</button></div>
</form>
<p class="form-help" id="signin-help">Forgot your password? Ask an administrator to reset it.</p>
</section>
<section class="signin-card" id="signin-change" aria-labelledby="change-title" hidden>
<h1 id="change-title">Choose your own password</h1>
<p>The password you signed in with was set by an administrator. Choose your own before you continue.</p>
<form id="change-form" novalidate>
<div class="signin-field" id="change-current-field" hidden><label for="change-current">Current password</label><input id="change-current" name="current" type="password" autocomplete="current-password" maxlength="128"></div>
<div class="signin-field"><label for="change-new">New password</label><div class="signin-password"><input id="change-new" name="password" type="password" autocomplete="new-password" maxlength="128"><button type="button" class="button secondary" id="change-show" aria-pressed="false" aria-controls="change-new change-confirm">Show</button></div><p class="form-help" id="change-policy">At least 12 characters. Any characters count; length matters more than symbols. Not your username, and not a common password.</p></div>
<div class="signin-field"><label for="change-confirm">New password again</label><input id="change-confirm" name="confirm" type="password" autocomplete="new-password" maxlength="128"></div>
<p id="change-error" class="form-error" role="alert"></p>
<div class="actions"><button type="submit" class="button primary" id="change-submit">Change password and continue</button><button type="button" class="button secondary" id="change-signout">Sign out</button></div>
</form>
</section>
<div id="signin-plain" class="banner warn" role="status" hidden><p>This connection is not encrypted. Your password would travel in clear text. Ask the administrator to enable TLS before signing in from outside the lab network.</p></div>
</main></body></html>
```

The throttled sentence (section 1.5 item 7, REVIEW U15) is built by the script inside `#signin-error`
with `createElement` and text nodes, never `innerHTML`:

```html
<p id="signin-error" class="form-error" role="alert">Too many sign-in attempts. Try again in <span class="sr-only" id="signin-wait-said">42</span><span aria-hidden="true" id="signin-wait">42</span> s.</p>
```

`#signin-wait-said` is written once with the first value, so the alert is announced once with its
number; `#signin-wait` ticks every second and is `aria-hidden`, so a screen reader never hears the
ticks. When the delay ends `#signin-error` is emptied and `#signin-reason` (`role="status"`) reads *You
can sign in again.*, announced once.

Notes on the markup:

1. The brand is a `div`, not the `a.brand` of index.html:24: a link to `/` would bounce back to
   `/login`. The `.brand` rule applies to any element (style.css:226 is a class selector).
2. `novalidate` on both forms: the empty-field message is the page's own (section 8), not the
   browser's bubble, so it is one voice and testable.
3. `autocomplete="username"` and `"current-password"` are what password managers key on. The forms
   have no `action`: without JavaScript the page cannot work (the API takes JSON), and an accidental
   native post would send form-encoded data to `/api/session`.
4. `maxlength` equals the backend limits (section 12, C4) so the page never sends what the manager
   would refuse for length. The username is lowercased before it is sent (section 1.5), because the manager's rule is lowercase.
5. The sign-in form is `hidden` in the markup and `#signin-checking` is not: the page first asks
   `GET /api/session` (section 1.5, REVIEW R14) and shows the form, the change view or leaves. There is
   no `autofocus` attribute (it fires at parse time, when the form is still hidden); the script focuses
   `#signin-user` when it shows the form and `#change-new` (or `#change-current`) when it shows the
   change view. Screen readers announce the heading first because each card is `aria-labelledby`.
6. The Show buttons have text, not an icon: the product's buttons carry words (index.html:68-69).
7. `#signin-card` and `#signin-change` are never shown together: the script sets `hidden` on exactly
   one of them once the check is answered.

### 1.5 Behaviour (`login.js`)

`login.js` is house style, `'use strict'`, one `const get=id=>document.getElementById(id)` as
debug.js:2 does, no inline styles, no `innerHTML`. Its pure functions are named for the tests.

| Function | Contract |
|---|---|
| `loginNext(search, hash)` | Returns the safe `next` from a query string and the page's own hash (section 1.6), or `'/'`. Pure. |
| `loginReason(search)` | Returns the sentence for `?reason=ended` (section 8) or `''`. Pure. |
| `loginCountdown(seconds)` | Returns the throttled sentence for a number of seconds (section 8) as one string, for the tests; the script writes the number alone into `#signin-wait-said` and `#signin-wait` (section 1.4). Pure. |
| `loginPlain(protocol, hostname)` | True when `protocol==='http:'` and `hostname` is not `localhost`, `127.0.0.1` or `::1`. Pure. |
| `loginMessage(data, fallback)` | `data.detail.message` when it is a non-empty string, else `fallback`. Pure (REVIEW U11). |
| `changeProblem(username, current, password, confirm, askCurrent)` | The first failing sentence of section 2.3 for the new password, *Enter your current password.* when `askCurrent` is true and `current` is empty, or `''`. Pure. |
| `loginLoad()` | The load check below (REVIEW R14). |
| `loginSubmit(event)` | The sign-in submit handler below. |
| `loginShowForm(focus)` | Hides `#signin-checking` and `#signin-change`, shows `#signin-card` and `#signin-form`, focuses `#signin-user` when `focus` is true. |
| `loginShowChange(user, askCurrent)` | Hides `#signin-card`, shows `#signin-change`, shows `#change-current-field` when `askCurrent` is true, focuses `#change-current` or `#change-new` (section 1.8). |
| `changeSubmit(event)`, `changeSignOut()` | Section 1.8. |

Load, in order (REVIEW R14):

1. `#signin-checking` is visible and the form hidden (the markup, section 1.4). `loginReason()` and
   `loginPlain()` are applied as before (below), so the reason line and the plain-HTTP banner are
   already right whatever the outcome.
2. `fetch('/api/session',{cache:'no-store'})`. Same-origin, so the cookie goes with it even when the
   page was reached from another site (a course page, an email): with `SameSite=Strict` the navigation
   itself carried no cookie and the gate sent the person here, but the page's own request does.
3. 200 with a JSON body whose `user.must_change_password` is true: `loginShowChange(user, true)`
   (section 1.8; the current password is asked because this page load did not sign in).
4. 200 otherwise: `location.replace(loginNext(location.search, location.hash))`. The person was signed
   in all along.
5. 401, any other status, a body that is not JSON, or a network failure: `loginShowForm(true)`.
   The page does not read `?change=1`: the answer of `GET /api/session` decides, so a stale
   `change=1` after the session ended shows the form, not an empty change view.

Submit, in order:

1. `event.preventDefault()`. While a countdown runs (item 7) the handler returns at once.
2. Read the two fields. If either is empty after `trim()` on the username (the password is never
   trimmed; the username is lowercased before it is sent): show *Enter your username and password.* in `#signin-error`, focus the empty field,
   stop.
3. Disable `#signin-submit`, set its text to *Signing in…* (the idle label is captured first, per
   DESIGN-SPEC-ADDENDUM A.4), clear `#signin-error`.
4. `fetch('/api/session',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username,password})})`.
   Default credentials (`same-origin`) carry and receive the cookie; no header is added (the guard
   of main.py:119-156 checks `Origin` and `sec-fetch-site` itself).
5. On 200 with `user.must_change_password` false: `location.replace(loginNext(location.search, location.hash))`.
   `replace`, not `assign`: Back must not return to the sign-in page with the fields filled.
   On 200 with `user.must_change_password` true: keep the typed password in a file-local variable
   (`signedInWith`), clear `#signin-password`, and `loginShowChange(user, false)` (section 1.8, REVIEW
   R1). The password is never stored anywhere else; it is held until the change view ends (a 200, a
   401, *Sign out*; section 1.8 item 2), so a retry after a refused new password sends it again.
6. On 401: show `loginMessage(data, 'Wrong username or password.')` (the manager's own sentence is the
   same text, REVIEW U11); keep the username; clear the password; focus the password; restore the
   button.
7. On 429: read `retry_after` (integer seconds, default 60 when missing or not a number, capped at
   3600); build the throttled sentence in `#signin-error` as section 1.4 shows (the sentence once,
   `#signin-wait-said` once, `#signin-wait` ticking, REVIEW U15); keep the button disabled; count down
   once per second with `setInterval`, writing only `#signin-wait`; at 0 empty `#signin-error`, put *You
   can sign in again.* in `#signin-reason` and unhide it, restore the button, focus the password. The
   person cannot submit before 0 (the button is disabled and the submit handler returns while a
   countdown runs). The sentence is the one of every 429 of the manager (REVIEW R5): *Too many
   sign-in attempts. Try again in {n} s.*
8. On any other status, or a network failure: show *The manager did not answer. Try again.*;
   restore the button. The status code is not shown (the page says nothing about the product).
9. A 2xx with a body that is not JSON, or a 3xx, is treated as item 8.

Show password: `#signin-show` toggles `#signin-password.type` between `password` and `text`, sets
`aria-pressed` and its own text *Show* / *Hide*. Focus stays on the button. The field's value is
never read for this. `#change-show` does the same for `#change-new` and `#change-confirm` at once.

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

Focus order: username, password, Show, Sign in. Nothing else on the page is focusable while the
sign-in card is shown; in the change view it is Current password (when shown), New password, Show, New
password again, Change password and continue, Sign out. The error paragraphs are `role="alert"` so a
wrong pair is announced without moving focus away from the password.

### 1.6 `next`: what is accepted

`loginNext(search, hash)` applies these rules to the raw `next` value (after `URLSearchParams`
decoding), then to the page's own hash (REVIEW U7):

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
6. When the safe value contains no `#` and `hash` (the page's `location.hash`, `'#…'`) is non-empty,
   `hash` is appended, under the same checks as item 3 (no `\`, no control character) and the length
   cap of item 2 applied to the whole; a hash that fails them is dropped, never the `next`. The gate's
   `next` carries the path and query only (the hash never reaches the server), but a browser keeps the
   fragment of the address it was redirected from, so `/#lab=a&view=devices` signed out becomes
   `/login?next=%2F#lab=a&view=devices`, and after sign-in `/#lab=a&view=devices`.

The application builds `next` as `encodeURIComponent(location.pathname+location.search+location.hash)`
(section 3.3). The hash carries the lab route (`#lab=…&view=…&device=…`, shell.js:15-17), so after
sign-in the person lands on the lab, tab and device they had open, whether the application or the gate
sent them here.

### 1.7 States of the page

| State | What is shown |
|---|---|
| Checking | `#signin-checking` *Checking…* under the lead; the form hidden; until `GET /api/session` answers (section 1.5, REVIEW R14). |
| Default | Empty fields, Sign in enabled, no error, focus on the username. |
| Empty submit | *Enter your username and password.*, focus on the empty field. |
| Sending | Sign in disabled, text *Signing in…*. |
| Wrong pair | *Wrong username or password.*, password cleared, username kept. One sentence for an unknown user, a wrong password and a deactivated account (section 12, C3). |
| Throttled | *Too many sign-in attempts. Try again in 42 s.*, the seconds ticking in an `aria-hidden` span; Sign in disabled until 0; then *You can sign in again.* in `#signin-reason` (REVIEW R5, U15). |
| Manager unreachable | *The manager did not answer. Try again.* |
| Plain HTTP | The warning banner under the card; the form works. |
| Returned after expiry | *Your session ended. Sign in again to continue.* above the fields. |
| Already signed in | The load check answered 200: the page leaves for `next` at once. The server also answers `302 /` to `GET /login` with an unrestricted session (section 12, C5); the page's own check covers the cross-site navigation the server cannot (section 1.5). |
| Must change the password | The change view (section 1.8) in place of the sign-in card, after a sign-in whose answer says `must_change_password` or after a load check that says so. |

### 1.8 The change view: a required password change lives on the sign-in page (REVIEW R1)

A restricted session (section 0.2) never reaches the application: the gate sends every page request
of it to `/login?change=1&next=<path+search>` and refuses everything else with 403
`password_change_required`. The person therefore meets the change in exactly two ways, both on this
page: the answer to their own sign-in, or the load check after a reload or a bookmark. There is no
dialog in `index.html` for it (the former section 6.3 is gone), because `index.html` cannot even read
`/api/state` under a restricted session.

`loginShowChange(user, askCurrent)`:

1. `#signin-card` hidden, `#signin-change` shown, `#change-error` empty, the three fields empty.
2. `#change-current-field` shown only when `askCurrent` is true (the page load did not sign in, so
   the page does not hold the current password); hidden after a sign-in on this page load, whose
   password is held in `signedInWith`.
3. Focus on `#change-current` when shown, else `#change-new`.
4. `user.name` is kept for `changeProblem()` (the password must not be the username).

`changeSubmit(event)`, in order:

1. `preventDefault()`. `changeProblem(name, current, password, confirm, askCurrent)`: a sentence shows
   in `#change-error`, the field it names is focused, stop.
2. Disable `#change-submit` (*Changing…*). `POST /api/session/password` with
   `{current, password}` where `current` is `#change-current.value` when the field is shown, else
   `signedInWith`. `signedInWith` is **kept** through a 422, a 429 and a network failure, so the retry
   after a refused new password (the deny-list is checked on the manager only, section 2.3) sends the
   same `current` again and never a `''` that would earn a misleading *The current password is not
   right.*; it is set to `''` on a 200 (the page leaves), on either 401 (item 4 asks for the field,
   item 5 shows the sign-in form), and by `changeSignOut()`. Leaving the page clears it like any variable.
3. 200: `location.replace(loginNext(location.search, location.hash))`. The manager cleared
   `must_change_password` and rotated the cookie; the person lands where they were going.
4. 401 `invalid_credentials`: `signedInWith=''`; show `detail.message` (*The current password is not
   right.*), show `#change-current-field` (whatever `askCurrent` was: the held password was wrong, which
   happens when an administrator reset it again meanwhile), focus `#change-current`, restore the
   button. From now on `current` is the field's value.
5. 401 `signed_out` (the session ended between the two requests): `signedInWith=''`;
   `loginShowForm(true)` with `#signin-reason` reading *Your session ended. Sign in again to continue.*
6. 422: `detail.message` (the sentences of section 2.3), focus `#change-new`, restore the button;
   `signedInWith` kept.
7. 429: `detail.message` as given, no countdown (the person waits and tries again), restore the
   button; `signedInWith` kept.
8. Any other status, or a network failure: *The manager did not answer. Try again.*, restore the
   button; `signedInWith` kept.

`changeSignOut()` (L1 in REVIEW R1: the view has a way out): `signedInWith=''` first; `DELETE
/api/session` with body `{}` (`fetch`, `method:'DELETE'`, `Content-Type: application/json`, body
`'{}'`); whatever the answer, the change fields are emptied and `loginShowForm(true)` shows a clean
sign-in form (no reason line). No navigation: the person is already on the sign-in page. (A failed
`DELETE` here costs nothing: the session it leaves behind is restricted and can reach nothing but
this page, where the next load check shows the change view again.)

What the view never does: read `?change=1` (section 1.5), store the password (a file-local variable
only, never storage, never the URL), show the policy deny-list, or offer a way past the change. The
manager enforces the restriction; the view only makes it possible to leave it.

## 2. The first-run setup page: `setup.html` and `setup.js`

### 2.1 Why a second page, not a mode of `login.html`

1. `login.js` stays the smallest script on the exposed surface. Setup fields and the policy check
   would double it.
2. `/setup` exists for minutes after installation and during a recovery window (REVIEW R11); outside
   those two modes `GET /setup` answers 404 (section 12, C6: a 404 says less than a page that
   exists); `/static/setup.js` stays reachable without a session (it is in DESIGN 6.3's `EXEMPT`), but
   without `/setup` it is an unreferenced script that names no feature of the application.
3. One test file per script, in the pattern of `test_debug_ui.js`.

The page shares `login.html`'s classes and layout exactly (section 1.2 and 1.3): `body.signin`,
`main.signin-page`, `.brand`, `section.signin-card`. Only the fields differ. `setup.html` loads
`login.css` and `setup.js` only.

### 2.2 Markup

```html
<section class="signin-card" aria-labelledby="setup-title">
<h1 id="setup-title">Create the first administrator</h1>
<p id="setup-lead">Enter the setup code the installer printed, then choose the account you will sign in with.</p>
<form id="setup-form" novalidate>
<div class="signin-field"><label for="setup-code">Setup code</label><input id="setup-code" name="code" type="text" autocomplete="one-time-code" autocapitalize="none" autocorrect="off" spellcheck="false" maxlength="64" autofocus><p class="form-help">Printed at the end of the installation. On the VM: <code>sudo cat /srv/containerlab-node-manager/data/setup-code</code></p></div>
<div class="signin-field"><label for="setup-user">Username</label><input id="setup-user" name="username" type="text" autocomplete="username" autocapitalize="none" autocorrect="off" spellcheck="false" maxlength="32"><p class="form-help">Lowercase letters, digits, dot, dash and underscore. 2 to 32 characters.</p></div>
<div class="signin-field"><label for="setup-password">Password</label><div class="signin-password"><input id="setup-password" name="password" type="password" autocomplete="new-password" maxlength="128"><button type="button" class="button secondary" id="setup-show" aria-pressed="false" aria-controls="setup-password setup-confirm">Show</button></div><p class="form-help" id="setup-policy">At least 12 characters. Any characters count; length matters more than symbols. Not your username, and not a common password.</p></div>
<div class="signin-field"><label for="setup-confirm">Password again</label><input id="setup-confirm" name="confirm" type="password" autocomplete="new-password" maxlength="128"></div>
<p id="setup-error" class="form-error" role="alert"></p>
<p id="setup-reason" class="form-help" role="status" hidden></p>
<div class="actions"><button type="submit" class="button primary" id="setup-submit">Create account and sign in</button><a id="setup-signin" class="button secondary" href="/login" hidden>Sign in</a></div>
</form>
</section>
```

The same `#signin-plain` banner follows the card. The head links `/static/login.css?v=…` and
`/static/setup.js?v=…` only.

Recovery (REVIEW R11): the recovery command prints `https://<address>:<UI_PORT>/setup?recover=1`. When
`setupRecover(location.search)` is true the script sets `#setup-title` to *Recovery: create one new
administrator* and `#setup-lead` to *Enter the code the recovery command printed, then choose a new
administrator account. Existing accounts are not changed.*; the code help, the fields and the button
are the same. The page cannot know the manager's mode (it is a static file); the address it was opened
from is the only signal, and a wrong signal costs nothing: the manager decides what the code is for.

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

Username rule as shown: lowercase, 2 to 32 characters, `^[a-z0-9][a-z0-9._-]{1,31}$`. The page sets
`maxlength="32"`, lowercases the value before sending, and shows the rule from the manager's 422
message (*Use lowercase letters, digits, dot, dash or underscore, 2 to 32 characters.*).

### 2.4 Behaviour (`setup.js`)

| Function | Contract |
|---|---|
| `setupProblem(username, password, confirm)` | Returns the first failing message of section 2.3 (page checks only) or `''`. Pure. |
| `setupRecover(search)` | True when the query string carries `recover=1`. Pure (REVIEW R11). |
| `setupSubmit(event)` | Below. |

Submit, in order:

1. `preventDefault()`. If the code is empty after `trim()`: *Enter the setup code.*, focus it, stop. If
   `setupProblem(...)` returns a message: show it, focus the field it names, stop.
2. Disable the button (*Creating…*). `POST /api/setup` with `{code,username,password}` (the username
   lowercased; the code trimmed and otherwise as typed: the manager normalises both sides before it
   compares, so case, spaces and dashes do not matter, REVIEW U13).
3. 200: the manager has set the session cookie for the new admin (section 12, C6);
   `location.replace('/')`. The person lands on Home signed in. No welcome toast: Home's own empty
   state (*Works with Junos, IOS-XR and Arista EOS*, DESIGN-SPEC-ADDENDUM A.6) is the welcome.
4. 401 `invalid_code` (wrong code): the manager's `detail.message`, *That setup code is not right. On
   the VM, run: sudo cat /srv/containerlab-node-manager/data/setup-code* (REVIEW U13: the file keeps
   the code a restart regenerated, so the sentence points at the file, never at earlier output). The
   code field is cleared and focused. The username and password stay.
5. 429 with `retry_after`: as the sign-in page (section 1.5 item 7, REVIEW R5, U15), with the same
   accessible countdown: the sentence is built once inside `#setup-error` with `createElement` and text
   nodes, the number in `<span class="sr-only" id="setup-wait-said">` (written once, never changed) and
   in `<span aria-hidden="true" id="setup-wait">` (ticking); the button stays disabled and the submit
   handler returns while the countdown runs; at 0 `#setup-error` is emptied, `#setup-reason`
   (`role="status"`, section 2.2) reads *You can sign in again.* and is unhidden, the button is
   restored and `#setup-code` is focused. The same `retry_after` rules apply (default 60, cap 3600).
6. 422 (the manager refused the username or the password): the manager's `detail.message` as given
   (its sentences are the ones in section 2.3). The page never shows a stack or a code.
7. 409 `exists` (recovery: the chosen name is an existing account; `POST /api/setup` never overwrites a
   record, REVIEW R11): the manager's `detail.message`, *That name already exists. Choose a new name for
   the recovery administrator.*; `#setup-user` is focused and kept; the code and the passwords stay.
   First-run setup has no accounts, so this answer is a recovery answer in practice, but the page
   handles it the same way in both modes.
8. 404 `setup_closed` (setup is closed: another person finished setup or the recovery window ended
   while the page was open): the manager's `detail.message`, *Setup is closed. Sign in, or ask the VM
   administrator to run the recovery command.*, and the static `<a id="setup-signin" class="button secondary" href="/login" hidden>Sign in</a>` is
   unhidden (RECONCILIATION 5, lead's ruling). A 404 to a person already holding the page says nothing a
   scanner learns: `GET /setup` itself is 404 outside the two modes. The former 409 sentence (*The first
   account was already created…*) is gone; the 409 of item 7 is a different answer with its own code.
9. Any other status, or a network failure: *The manager did not answer. Try again.*

The code is never stored, never put in the URL and never echoed back.

Show toggles both password fields at once (`aria-controls` names both).

## 3. Signed out while the application runs

### 3.1 The one shared behaviour

Every request helper does the same four things on `401` + `{detail:{code:'signed_out'}}`:

1. Mark the page as signed out, so no further request is sent by a poll or a heartbeat.
2. Keep what the person typed (section 3.4).
3. Tell the person once.
4. Offer the sign-in page with `next` pointing back here.

And one thing before every request (REVIEW U8): while the page is marked signed out, the helper sends
nothing and throws `sessionEndedError()` (section 3.2), an error marked `sessionEnded: true`. The guard
sits at the source, so a chain that was not written for a 401 still cannot storm the manager; the
chains that re-arm themselves are listed in section 3.3 with what each does on top.

What differs per page is only whether item 4 is a redirect or a link (section 3.5). A session renews
only on acts of the person (any method but GET and HEAD through the gate, a page navigation, socket
input; REVIEW R9): no poll of this document keeps a tab signed in, so an idle tab ends in exactly the
path below, with its typed content kept.

The manager chooses between a page and an API answer by `Accept` (section 12, C15): a `GET` or `HEAD`
whose `Accept` includes `text/html` without a session is redirected 302 to `/login?next=<path+search>`
(the hash never reaches the server), every other request answers 401 JSON `signed_out` (or closes a
socket with 1008). A `window.open` of an API URL such as the design export is therefore a page
request and is redirected.

### 3.2 Where the code lives: `session.js`

A new plain script `app/static/session.js`, loaded with `?v=` by every page that sends a request
(index.html, workspace.html, debug.html, lab-builder.html, map-editor.html, terminal.html,
capture-session.html, capture-setup.html if it fetches). On index.html it is listed after
`status.js` and before `shell.js` (index.html:3), so `shell.js` and `app.js` may call it.

This table is the contract the other UI slices build against (BUILD.md S7 to S10). Every name is a
classic-script global; none collides with a name in another page script (`test_page_load_ui.js`).

| Global | Arguments | Returns | Contract |
|---|---|---|---|
| `sessionLost(status, data)` | the HTTP status (number), the parsed body (any) | boolean | True when `status===401` and `data` is an object whose `detail.code==='signed_out'`. Pure. (A 401 of any other shape is a plain error: the capture relay's own refusals and `invalid_credentials` keep their wording.) |
| `loginUrl(pathname, search, hash, reason)` | strings; `reason` any | string | `'/login?next='+encodeURIComponent(pathname+search+hash)` plus `&reason=ended` when `reason` is truthy. Pure. The page never passes an absolute URL; the sign-in page re-checks anyway (section 1.6). |
| `sessionEnded()` | none | boolean | True once `sessionMark()` was called on this page and `sessionClear()` has not been called since. |
| `sessionMark()` | none | boolean | Sets the flag. Returns true the first time (or the first time after a `sessionClear()`), false while it is already set, so the caller tells the person once. |
| `sessionClear()` | none | undefined | Clears the flag (section 3.6). |
| `sessionEndedError()` | none | `Error` | A new `Error` with `message` *Your session ended. Sign in again.*, `status: 401` and `sessionEnded: true`. What `api()` and every page helper throw **without sending** while `sessionEnded()` is true (REVIEW U8). The marker is only on the unsent error; the error of a real 401 carries `status: 401` and the same message but no marker. A chain tells the two apart by nothing: both mean `sessionEnded()` is true, which is what a chain checks. |
| `sessionGo(reason)` | any | undefined | `location.replace(loginUrl(location.pathname, location.search, location.hash, reason))`, under `typeof location!=='undefined'`. The only place in `session.js` that touches `location`. |
| `sessionOnResume(fn)` | a function | undefined | Registers `fn` to run once after the next successful `sessionRetry()`. Kept in a `Set`: the same function registered twice runs once; a non-function is ignored. A chain registers its own resume function when it stops on a session end (section 3.3) and registers again at its next stop. |
| `sessionRetry()` | none | `Promise<boolean>` | `sessionClear()`; then `await refresh()` when `typeof refresh==='function'` (the application), its rejection swallowed (`refresh()` throws on a network failure, app.js:91: the flag then stays clear and the poll goes on at its next tick), nothing to await on a standalone page; then, if `sessionEnded()` is true again (the refresh answered 401 and `signedOut()` re-marked the page, recomputing the banner), resolve `false` and keep the registered functions; otherwise call `sessionRestored()` when it is a function, take every registered function out of the set and run each once (an exception in one does not stop the others), resolve `true`. There is no third state: after a `sessionRetry()` the page is either marked again, with its banner, or fully back, with every chain resumed (a chain whose first request then fails on the network handles it as it does today). The only caller of the resume functions. |
| `signedOut()` (shell.js) | none | boolean | The application's one reaction to a 401 `signed_out` (section 3.3 item 4): `sessionMark()` once, then a navigation or the banner. Returns false when the page was already marked. Lives in `shell.js` because it reads the DOM for open dialogs and panels; `api()` calls it under a `typeof` guard. |
| `sessionRestored()` (shell.js) | none | undefined | Hides `#session-banner`, removes the dialog clone (section 3.3 item 5). Called by `sessionRetry()` under a `typeof` guard; absent on the standalone pages, which keep their own overlay rules (section 3.5). |
| `goSignIn()` (shell.js) | none | undefined | `location.replace('/login')`: the sign-out landing (section 6.4). |

`session.js` holds one file-local flag and one file-local `Set`, declared at the top level; neither
touches the DOM, storage or `location`.

Rule for J1 (DESIGN-SPEC-ADDENDUM:99-101): `app.js` gains no top-level side effect and calls
`session.js` and `shell.js` only through `typeof x==='function'` guards. `session.js` has no top-level
side effect either, and its one `location` access is inside `sessionGo()`, so every node harness that
loads `app.js` without it keeps working. This is an amendment of J1's letter ("everything that touches
`location` lives in `shell.js`") and is written up in section 12 (C13) for the lead: the standalone
pages need the same function, and `shell.js` is not loaded there.

### 3.3 The application (`index.html`)

1. `api()` (app.js:52-63) gains two lines. The first, before the `fetch`:
   `if(typeof sessionEnded==='function'&&sessionEnded())throw sessionEndedError();` (REVIEW U8: no
   request leaves a signed-out page). The second after the status check, before the error is thrown:
   `if(response.status===401&&typeof sessionLost==='function'&&sessionLost(401,data)&&typeof signedOut==='function')signedOut();`.
   The error is still thrown (`error.status=401`, `error.message` = *Your session ended. Sign in
   again.*), so every existing `catch` runs as it does today; its toast is harmless because the page
   is leaving or already shows the banner. `json()` (app.js:63) goes through `api()` and needs nothing.
2. `refresh()` (app.js:91) gains a first line: `if(typeof sessionEnded==='function'&&sessionEnded())return;`.
   The interval at app.js:576 keeps ticking; it makes no request. This is what stops the 4 s poll
   from storming the sign-in page (section 10, item 4): after the first 401 there is no second request
   from this page. `refreshLogs()` (app.js:564-571) runs inside `refresh()` and stops with it;
   `refreshCaptureSessions()` (capture.js:408) runs from `render()` (app.js:374) and stops with it.
3. **Every polling chain** (REVIEW U8). The helper guard of item 1 already means a chain cannot send
   after the first 401. On top of it, each chain that catches the error stops without spending a retry,
   without writing its failure sentence, and registers its resume through `sessionOnResume(fn)`; the two
   chains that re-arm from a render path check `sessionEnded()` at their start as well. The rule in each
   `catch`, first thing: `if(typeof sessionEnded==='function'&&sessionEnded()){sessionOnResume(<resume>);return;}`.
   `sessionRetry()` runs `refresh()` and then every registered function once (section 3.2). Every
   snippet in the table, and every start guard, is written with that `typeof` guard, because the
   existing harnesses load these files without `session.js` (`test_device_diagnostics_ui.js`,
   `test_map_tools_ui.js`, …) and their failure paths must not throw `ReferenceError`; inside the
   guarded branch `sessionOnResume` exists, since both come from the same file.

| Chain | File, function, timer sites | On a session end | Resume registered |
|---|---|---|---|
| The 4 s poll and the logs | app.js:576 `setInterval` → `refresh()` (:91) → `refreshLogs()` (:564) | `refresh()` returns before any request (item 2) | none needed: `sessionRetry()` runs `refresh()` itself |
| Capture session list, capture status | capture.js:408 `refreshCaptureSessions()` from `render()` (app.js:374); capture.js:28 one-shot | stop with `render()`; the guard | with the next `render()` |
| Operation output | operations.js:572 `opShowJob()` → `poll` (:607, :624, :625 `setTimeout(poll,…)`) | the `catch` at :625 returns before `++fails` and before the dialog's `.form-error` is written | `poll` |
| Design generation watch | network-design.js:1001 `designMaybeStartWatch()` → `poll` (:1017, :1020, :1034, :1042) | the `catch` at :1027 returns before `failures++`; `designWatch` stays set, so the render path (:994, :1250) does not start a second watch | `poll` |
| Design review watch | network-design.js:1840 `designReviewStartWatch()` → `poll` (:1851, :1856, :1878, :1881) | the `catch` at :1858 returns before the 404 branch and before `failures++`; `designReviewWatch` stays | `poll` |
| Design apply watch | network-design.js:2008 `designApplyStartWatch()` → `poll` (:2020, :2037, :2048) | the `catch` at :2027 returns before `failures++`; `designApplyFollow.problem` is not written | `poll` |
| Git save watch | git-progress.js:328 `gitStartWatch()` → `poll` (:339, :347); re-armed from the render path at :127 (`if(active&&!gitWatch)`), save-header.js:545, save-drawers.js:711, network-design.js:2138 | `gitStartWatch()` returns at its start while `sessionEnded()`; the `catch` at :346 keeps `gitWatch` set (so :127 does not re-arm), writes no dialog text and no toast | `poll` |
| Load watch | load.js:465 `loadWatch()` → `poll` (:475, :480); re-armed from `renderSaveHeader()` through load.js:417 and :329 on every render (the refuter's finding: every 1.5 s after a 401) | `loadWatch()` returns at its start while `sessionEnded()`; the `catch` at :472 calls `loadStopWatch()` and does **not** set `loadPaused` (the panel shows no *paused* state for a sign-out) | `()=>loadWatch(job)` |
| Restore watch | restore.js:357 `restoreStartWatch()` → `poll` (:366, :370); re-armed at :302 from the job window | start guard; the `catch` at :368 calls `restoreStopWatch()` and does not set `restorePaused` | `()=>restoreStartWatch(job)` |
| Device diagnostics (Interfaces, Logs) | device-diagnostics.js:298 `diagRun()` → `setTimeout` at :322, :328, planned by `diagPollNext` (:22) | after the `catch` at :307: `if(!result.ok&&typeof sessionEnded==='function'&&sessionEnded()){sec.flight=false;sessionOnResume(()=>diagRun(name,replace));return;}` before `diagPollNext` runs, so no failure is planned and nothing is said; `diagRun` itself checks `sec.open` on resume | `()=>diagRun(name,replace)` |
| Map link state | map-tools.js:157 `mapLinkSchedule()` → :180 `mapLinkRun()` (:177, :218); re-armed from topology.js:210 on every render | `mapLinkSchedule()` returns at its start while `typeof sessionEnded==='function'&&sessionEnded()`; in `mapLinkRun()` after the `catch` at :187: `if(typeof sessionEnded==='function'&&sessionEnded()){poll.fresh=true;sessionOnResume(mapLinkSchedule);return;}` before `diagPollNext`, so the colours stay and no *paused* sentence is written | `mapLinkSchedule` |
| Drawer upload wait | save-drawers.js:612 `drwAwaitUpload()` (a loop with `setTimeout` at :617) | the guard's error ends the loop and reaches the drawer's own error line, which shows the sentence; the person reopens the drawer after signing in | none |
| One-shot requests behind a timer | lab-builder-page.js:399 (image check), :461 (topology check note); device-impairments.js:218, :229 | the guard; the builder's overlay rule (section 3.5) | none |
| Capture viewer heartbeat | capture-session.js:79 `setInterval` | `clearInterval(heartbeat)` (section 3.5) | the page's *Reconnect viewer* |

   Timers that send nothing are not chains and change nothing: shell.js:308 and :383 (DOM), home.js:83
   (the filter announcement), network-design.js:1806 (the review expiry), clipboard.js:55, map-tools.js:327,
   the toasts and the `URL.revokeObjectURL` timeouts.
4. `signedOut()` lives in `shell.js` (it decides between a navigation and a banner, and it reads the
   DOM for open dialogs and panels). The panel check runs **before** `closeMenus()` (REVIEW U9):
   `closeMenus()` (shell.js:73-78) closes the chip panel and its render clears the typed save name.

```
function signedOut(){
 if(typeof sessionMark!=='function'||!sessionMark())return false;          // once
 const panel=sessionDirtyPanel();                                            // before closeMenus(): it would clear #save-name
 if(!panel)closeMenus();
 const dialog=typeof document!=='undefined'&&typeof document.querySelector==='function'?document.querySelector('dialog[open]'):null;
 const draft=typeof designLeaveGuard==='function'&&designLeaveGuard();
 if(!dialog&&!draft&&!panel){if(typeof sessionGo==='function')sessionGo('ended');return true;}
 renderSessionBanner(panel?'panel':dialog?'dialog':'draft');return true;
}
function sessionDirtyPanel(){
 if(typeof document==='undefined'||typeof document.querySelector!=='function')return null;
 const name=document.querySelector('[data-panel]:not([hidden]) #save-name[data-dirty]');
 const url=document.querySelector('[data-panel]:not([hidden]) #save-url');
 return name||(url&&url.value?url:null);
}
```

   `#save-name` carries `data-dirty` while the person's typed name differs from the manager's
   (save-header.js:172, set from `saveHeader.typed`); `#save-url` is the first-connect address field
   (save-header.js:208). Both live in `#save-panel[data-panel]` (index.html:100); `#load-panel`
   (index.html:109) has no text input, so it is never dirty. With a dirty panel the menus stay open, the
   page-level banner shows (the panel is not modal, so the banner is reachable) with the text *Your
   session ended. What you typed in the save panel is still here.* The rule that closes a panel on a
   press outside it is not a bubbling click listener: it is `shellPointerDown` (shell.js:198-203),
   registered in the capture phase on `document` (`document.addEventListener('pointerdown',
   shellPointerDown,true)`, shell.js:300), which calls `closeMenus()` before the target is reached and
   before any `click`, so nothing a button handler does can be early enough. `shellPointerDown` therefore
   gains one line before `closeMenus()`:
   `if(target&&target.closest('#session-banner, #session-banner-dialog'))return;` — a press on the banner
   or on its dialog clone (item 5) closes nothing, and the panel with the typed name survives *Try again*
   and *Sign in in a new tab*. The Escape rule gets the same exemption: the `closest` list at shell.js:191
   (`'.menu-list, [data-panel]'`) also names `#session-banner, #session-banner-dialog`, so Escape with
   focus on a banner button (focus lands there, item 5) does not close the panel either. `closeMenus()`
   itself is untouched. `sessionRetry()` on success leaves the panel as it was; *Sign in here* loses it
   by the person's choice.

5. The banner is static markup in index.html, directly after `#operation-summary` (index.html:63),
   above `#home` and `#lab-content` so it shows on Home and on a lab page alike (the rule of A.11):

```html
<div id="session-banner" class="banner danger" role="alert" hidden><svg class="icon" width="16" height="16" aria-hidden="true"><use href="#i-alert"></use></svg><div><p id="session-banner-text">Your session ended. What you typed in the open dialog is still here.</p><p class="caption" id="session-banner-caption">Sign in in a new tab, come back and choose Try again. Or sign in here and lose the open dialog.</p></div><div class="banner-actions"><a class="button primary small" id="session-signin-tab" href="/login" target="_blank" rel="noopener noreferrer">Sign in in a new tab <span aria-hidden="true">↗</span></a><button type="button" class="button secondary small" id="session-retry">Try again</button><button type="button" class="button ghost small" id="session-signin-here">Sign in here</button></div></div>
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
   - No dialog is open (the cause is an unstored design draft or a dirty save panel, REVIEW U9):
     `#session-banner.hidden=false`, focus on `#session-retry`. The same `data-session-action` listener
     sits on the static banner.
   `renderSessionBanner(cause)` takes the cause (`'dialog'`, `'draft'`, `'panel'`) and sets both
   paragraphs from section 8: `#session-banner-text` (*…What you typed in the open dialog is still
   here.*, *…Your design draft is still on this page.*, *…What you typed in the save panel is still
   here.*) and `#session-banner-caption`, whose last words name the same thing (*…and lose the open
   dialog.*, *…and lose the draft.*, *…and lose what you typed.*); the clone copies both after they were
   set, and the static markup carries the dialog texts only as a default. The clone is removed when the
   session is restored (section 3.6).
6. `#session-signin-tab` opens `/login` in a new tab with no `next` (the new tab lands on Home;
   the person comes back to this tab). `rel="noopener noreferrer"` as index.html:48-52 do.
7. `#session-retry` calls `sessionRetry()` (session.js, section 3.2): `sessionClear()`, then `refresh()`,
   then on success `sessionRestored()` and every registered resume function (the chains of item 3). On
   200 the poll runs again, the banner hides and the clone is removed; on a new 401 `signedOut()` runs
   again (the flag was cleared, so `sessionMark()` is true again and the banner stays, with the same
   cause recomputed; `sessionRetry()` resolves `false` and keeps the resume functions); on a network
   failure `refresh()` rejected without marking the page, so `sessionRetry()` resolves `true` like a
   success: the banner hides, the chains resume and meet the failure as they do today (a retry spent,
   their own sentence), and the poll's ordinary unreachable handling takes over at its next tick. The
   page then says what is known (the manager did not answer), not what is no longer known (that the
   session ended); the next answer of the manager decides, and a 401 brings the banner back.
8. `#session-signin-here` calls `sessionGo('ended')`: the dialog, draft or panel is lost by the
   person's choice.
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
| The save chip panel's typed save name (`#save-name[data-dirty]`, save-header.js:172) and the first-connect repository address (`#save-url`, save-header.js:208) | In memory (`saveHeader.typed`, `saveHeader.first`) | The panel is a non-modal `div[data-panel]` (index.html:100), not a dialog, and `closeMenus()` would clear it: `signedOut()` checks it **before** `closeMenus()` and takes the banner path with the text *What you typed in the save panel is still here.*; a press or Escape on the banner closes no panel (section 3.3 item 4, REVIEW U9). The Load panel (index.html:109) holds nothing typed and is closed as any menu. |
| The map editor's unsaved map (`mapIsDirty`, map-editor-page.js:21) | In memory | Banner, not redirect (section 3.5). |
| A terminal's screen | In the pop-up | Not navigated away; the message replaces the status line (section 3.5). |
| The route (lab, tab, device) | The hash | Carried in `next` (section 1.6). |

### 3.5 Each standalone page

Every helper in the table gains the same first line as `api()` (section 3.3 item 1): while
`sessionEnded()` is true it throws `sessionEndedError()` and sends nothing (REVIEW U8). Every page that
shows an error sentence shows `detail.message` when the answer carries one (REVIEW U11) and its own
sentence only for a network failure or a body without one.

| Page | Helper | On `sessionLost` |
|---|---|---|
| workspace.js:6 `api()` | the guard and the check | `sessionGo('ended')` at once: the page holds nothing typed. After `refresh()` the page hides `#workspace-links` (the Diagnostics link of workspace.html:3) when `state.user.role==='operator'` (REVIEW U5: an operator is not sent to Diagnostics). |
| debug.js:7-14 `debugFetch()` | the guard and the check | `sessionGo('ended')`. On 403 `admin_required` the page shows the answer's `detail.message`, *Administrators only.*, in place of the report (Diagnostics is admin-only, section 4.4). |
| lab-builder-page.js:17 `api()` | the guard and the check | `sessionGo('ended')` when `builderUnstored===null`; else the page's existing problem overlay (`builderPaused`, lab-builder-page.js:15) with the banner sentence, the *Sign in in a new tab* link and a *Try again* button that calls `sessionRetry()` (on this page it clears the flag and runs the resume functions; there is no `refresh()`); `builderPaused` stays set until a request succeeds. |
| map-editor-page.js:13-16 `api()` | the guard and the check | When `mapIsDirty(mapBaseline,mapCurrent)` is false: `sessionGo('ended')`. When true: `mapPaused=true` (map-editor-page.js:8), the status pill reads *Editing paused* (mapStatusView, line 23) and a toast carries the sentence with the new-tab link; the next Save click calls `sessionRetry()` first, then saves. |
| terminal.js:46 ticket `POST` | the guard; `response.status===401` and `sessionLost` | `setStatus('Your session ended. Sign in again in the lab manager, then click Reconnect.')` through the status map (terminal.js:29-34 gets one more row). No navigation: this is a pop-up (app.js:410-411); the opener holds the sign-in. Reconnect calls `sessionClear()` before the ticket `POST`, so the guard lets the one request through and the answer decides. |
| terminal.js:51 WebSocket | close frame reason `signed_out` (section 12, C9) | The `onclose` path (terminal.js:55) keeps the reason after *Disconnected —*; the row above maps `signed_out` to the same sentence. |
| capture-session.js:7 `status()`, :28 asset probe, :56 download, :69 end | the guard; `sessionLost` | `$('viewer-status').textContent` = *Your session ended. Sign in again in the lab manager, then click Reconnect viewer.*; `clearInterval(heartbeat)` (line 79) so the 30 s heartbeat stops; `ended` stays false so Reconnect viewer (a `location.reload()`, line 65) can work after a sign-in elsewhere. The capture owner cookie (`capture_sessions.py:24`, `:113`) is separate and untouched by an expiry: a session that expires does not end the capture; the person signs in again and the owner cookie still matches (section 10, item 2). A sign-out is different (section 6.4). |
| users.js (section 5) | its own `usersApi()` with the guard | `sessionGo('ended')` (section 5.5). |
| vm-connection.html, capture-setup.html | no fetch today (`INVENTORY.md` 3) | Redirected by the manager before they load (section 0.3 item 4). |

### 3.6 Coming back

1. `sessionRetry()` is the way back on a page that stayed: it clears the flag, runs `refresh()`, and
   unless that re-marked the page with a new 401 calls `sessionRestored()` (shell.js: hides
   `#session-banner`, removes the dialog clone) and the resume function of every chain that stopped
   (section 3.3 item 3), so the operation output, a running save, load or restore and the open drawer
   sections carry on where they were (section 3.3 item 7 for a refresh that failed on the network).
   `render()` does not touch the banner (it is owned by `shell.js`, like the action-error banner,
   shell.js:281-288).
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
        <a role="menuitem" id="manager-diagnostics" href="/static/debug.html">Diagnostics</a>
        <hr class="menu-sep" role="separator">
        <div class="menu-account" role="group" aria-labelledby="account-name"><p id="account-name"></p><p id="account-role" class="caption"></p></div>
        <a role="menuitem" id="account-users" href="/static/users.html" hidden>People and sign-ins…</a>
        <button type="button" role="menuitem" id="account-password">Change password…</button>
        <button type="button" role="menuitem" id="account-signout"><span>Sign out</span><small class="menu-reason" id="account-signout-note" hidden>Signing out also closes this browser's Wireshark sessions.</small></button>
        <div class="menu-foot" role="group" aria-label="Manager status">…</div>
```

   `#account-name` is the name (`state.user.name`), `#account-role` reads *Administrator* or
   *Operator*. `#account-users` is unhidden only for `state.user.role==='admin'`; an Operator never
   sees it (and the manager refuses the page anyway, section 5.5). `#manager-diagnostics` is hidden for
   an Operator the same way (section 4.4). `#account-signout-note` is unhidden while capture is enabled
   on this VM (`captureEnabled!==false`, capture.js:20; REVIEW R10, section 6.4).

   The two admin-only items of the Manager menu that stay visible for an Operator gain the child
   markup `menuReason()` (app.js:86) writes into, which they lack today (index.html:31 and :42 are
   bare buttons; REVIEW U4), in the form of `#vm-projects` (index.html:34):

```html
        <button type="button" role="menuitem" id="vm-settings"><span>VM connection…</span><small class="menu-reason" hidden></small></button>
        …
        <button type="button" role="menuitem" id="manager-settings"><span>Manager settings…</span><small class="menu-reason" hidden></small></button>
```

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
 const user=state.user||null,name=user&&typeof user.name==='string'?user.name:'',operator=!!user&&user.role==='operator';
 if($('account-chip')){$('account-chip').textContent=name;$('account-chip').hidden=!name;}
 if($('account-name'))$('account-name').textContent=name;
 if($('account-role'))$('account-role').textContent=roleLabel(user&&user.role);
 if($('account-users'))$('account-users').hidden=!(user&&user.role==='admin');
 if($('manager-diagnostics'))$('manager-diagnostics').hidden=!(user&&user.role==='admin');
 if($('account-signout-note'))$('account-signout-note').hidden=typeof captureEnabled!=='undefined'&&captureEnabled===false;
 for(const id of ['vm-settings','manager-settings']){const el=$(id);if(!el)continue;el.disabled=operator;el.title=operator?'Administrators only':'';menuReason(el,operator?'Administrators only':'');}
}
```

`state.user` is `{name, role, must_change_password}` and comes with `/api/state` (section 12, C8): one
request, and a role change or a deactivation reaches the menu on the next poll (a deactivated person
gets a 401 instead, section 3). The application does not act on `must_change_password`: a restricted
session never reaches `index.html` (section 1.8, REVIEW R1), so the field is carried for completeness
and read by nothing here.

Operator gating of *VM connection…* (index.html:31) and *Manager settings…* (index.html:42): the
items stay visible and become **disabled** (`disabled` on the button, which `initMenu` then skips,
shell.js:89) with the visible reason *Administrators only* in their `small.menu-reason` child through
`menuReason()` (app.js:86), the pattern of every disabled menu item (DESIGN-SPEC-ADDENDUM J2, last
bullet). `menuReason()` only fills that child and never disables (app.js:86), and the two items had no
such child (REVIEW U4): `renderAccount()` sets `disabled` itself and the markup of section 4.1 adds the
child. Disabled, not hidden: an Operator should know the setting exists and who to ask. The manager
refuses the routes with 403 regardless (section 12, C3).

*Diagnostics* is different (RECONCILIATION 3, U-Q7): `GET /api/debug` is admin-only, so the page
would be empty for an Operator. The item is hidden for an Operator like *People and sign-ins…*, and
`debug.html` opened directly shows the sentence *Administrators only.* on the 403.

### 4.5 What an Operator is never sent into (REVIEW R13, U5)

The menu items are one of eight ways into the admin-only VM connection dialog, and several student
sentences end in "see Diagnostics". Each is role-aware so an Operator never meets a form whose Save
answers 403 or a page that refuses them.

**The VM connection dialog.** `openVmDialog()` (management.js:182) is itself role-aware, so every
entry point is covered at once: `$('vm-settings').onclick` (:197), `maybePromptVmConnection()` (:203,
called from the render path at :108), `#vm-connect-empty` (:157), `#home-vm-connect` (:158), the lab
banner's *VM connection…* action (app.js:287), the save drawers (save-drawers.js:330, :445, :793) and
the chip panel (save-header.js:567). For an Operator (`state.user.role==='operator'`) it shows, in the
same `#vm-dialog`, the block `#vm-operator` instead of `#vm-form` and sends nothing:

```html
<dialog id="vm-dialog"><div id="vm-operator" hidden><div class="dialog-head"><h2>VM connection</h2><button type="button" class="icon-button" data-dismiss aria-label="Close">×</button></div><p>Ask an administrator to set up the VM connection.</p><div class="dialog-actions"><button type="button" class="button secondary" data-dismiss>Close</button></div></div><form id="vm-form">…</form></dialog>
```

`openVmDialog()` sets `#vm-operator.hidden` and `#vm-form.hidden` from the role before `showModal()`,
and for an Operator fills nothing. `maybePromptVmConnection()` returns at once for an Operator (the
automatic first-load prompt is an administrator's). The Home banner (management.js:142) for an
Operator reads *The lab VM is not connected yet. Ask an administrator to connect it.* with
`#home-vm-connect` hidden; `#vm-connect-empty` (:135) is hidden for an Operator; the lab banner's
`banner-vm` action (app.js:287) is omitted for an Operator; `homeStartReason()` (home.js:14) answers
*Ask an administrator to connect the VM* instead of *Connect the VM first*. A test calls every entry
point with an operator `state.user` and asserts that no `PUT /api/host` is sent and that
`#vm-form` is hidden (section 9.1). `vm-connection.html:7` becomes role-neutral: *An administrator can
open Diagnostics to check the manager version and the VM connection.* (an Operator reaches that page
only by typing its address).

**"See Diagnostics".** One pure helper in `status.js`:

```
function diagnosticsAdvice(role){return role==='operator'?'ask an administrator to check Diagnostics':'see Diagnostics';}
```

Every student-facing sentence that named Diagnostics uses it, with the role read as
`typeof state==='object'&&state&&state.user?state.user.role:''` at the call site (the pure functions of
`operations.js` take it through one local `opRole()`):

| File:line | Today | With the helper |
|---|---|---|
| operations.js:36 | `Not available on this VM — see Diagnostics` | `Not available on this VM — ${diagnosticsAdvice(role)}` |
| operations.js:796 | `… open Diagnostics for details.` | `… ${diagnosticsAdvice(role)}.` |
| operations.js:938 | `The VM helpers are older than the manager: refresh them (see Diagnostics)` | `… (${diagnosticsAdvice(role)})` |
| operations.js:976, :986 | `… cannot ${verb} one device (see Diagnostics)`, `… cannot save one device (see Diagnostics)` | the same with the helper |
| operations.js:1222 | `Not available on this VM — see Diagnostics` | the same with the helper |
| device-impairments.js:16 | `const IMP_NO_CAP='… (see Diagnostics)'` | a function `impNoCap(role)` returning the sentence with the helper |
| management.js:97 | `… the VM helper may need an update (Manager ▾ › Diagnostics).` | `… (${diagnosticsAdvice(role)}).` |

Pinned labels (test_operations_ui.js:871-872, test_device_impairments_ui.js:221) are rewritten with an
admin `state.user` in their context so they keep asserting the *see Diagnostics* text, and each gains a
sibling assertion for the operator text; none is deleted.

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
Manager                                     (.eyebrow, reused; the comment at style.css:190 names both pages)
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
│ 2026-11-01 09:10  —        Sign-in attempt    Throttled  198.51.100.9     12 attempts in one minute   │
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
| Never delete the last admin; never deactivate or demote them | The *Deactivate* and *Change role…* buttons of the only active admin are disabled with `title` and a visible `<small class="menu-reason">`-style caption under the row: *The last administrator stays.* The manager refuses with 409 `last_admin` anyway (section 12, C10) and the page shows that sentence. |
| Your own account | *Deactivate* on your own row is disabled: *Sign out instead.* *Change role…* on your own row is disabled: *Ask another administrator.* (You could demote yourself out of the page.) *Reset password…* on your own row is disabled: *Use Manager ▾ › Change password… for your own account.* (REVIEW R12: a reset through the users route ends every session of its user and restricts the next one, which for yourself means being thrown out of this page into the change view.) The three disabled captions are the page's own (one per button, so each says what to do instead). The manager refuses all three with 409 `self_change` anyway, and on a 409 the page shows the manager's `detail.message` as it is (section 8): `DESIGN.md` 7.4 gives one sentence per request: *You cannot deactivate your own account. Sign out instead.* (`PATCH` with `disabled: true`), *You cannot change your own role. Ask another administrator.* (`PATCH` with `role`), *You cannot remove your own account. Ask another administrator.* (`DELETE`) and *Use Manager ▾ › Change password… for your own account.* (the password route), so a request forged past the disabled buttons is answered with a longer sentence than the caption; the caption is never derived from the 409. |
| A deactivated person's sessions end | The confirmation says so (section 5.3). The manager does it (section 12, C10). |
| Reset password | The admin types a temporary password and tells the person. The manager sets `must_change_password` (section 12, C11); the person's next sign-in lands in the change view of the sign-in page (section 1.8; REVIEW R1), never in the application. The page never displays a generated password: the admin chose it, so there is nothing to show once. |
| No delete | There is no Delete button. `DELETE /api/users/{name}` stays for the API; the page offers Deactivate, which keeps the audit trail readable (a name in the audit table should still resolve to a person). Decided (U-Q3): no Delete on the Users page; the audit reads "deactivated". |
| Add a person | `POST /api/users {name, role, password}`; the manager sets `must_change_password: true` on the new record, so the person must change the password at first sign-in. The dialog says so. |

Wire form: *Change role…* sends `PATCH /api/users/{name}` `{role}`; *Deactivate* and *Reactivate* send
`{disabled:true}` and `{disabled:false}`. A user row is `{name, role, disabled, must_change_password,
created, created_by, password_changed, last_signin, sessions}`; the *Status* column labels `disabled`
as *Inactive* and its negation as *Active* (wording is the page's, the field is `disabled`).

After every change the page reloads both lists (`usersRefresh()`); a success is a toast through the
page's own `notify()` (the pattern of workspace.js:5) with the sentences of section 8.

### 5.5 Operator or signed out

1. 401 `signed_out` → `sessionGo('ended')` (section 3.5). The page's helper `usersApi()` carries the
   guard of section 3.3 item 1 like every other.
2. 403 → both cards hidden, `#users-forbidden` shown: *Only administrators can open this page.* with
   the back link. The menu item is hidden for an Operator (section 4.4), so this is reached by URL only.

### 5.6 The audit table's vocabulary (REVIEW R3, R2, R8)

There is one vocabulary: the table in `DESIGN.md` 10.2, with its `event`, `outcome` and `detail`
columns, from which the constants `AUDIT_EVENTS`, `AUDIT_OUTCOMES` (`ok`, `failed`, `throttled`) and
`AUDIT_REASONS` in `app/accounts.py` are built. The page translates exactly those codes, like
`debugCheckNames` (debug.js:16-20), and nothing else; a row is `{time, actor, event, outcome, source,
target, detail}` (section 12, C12), the *Source address* column shows `source`. The label maps are
three object literals in `users.js`, `AUDIT_EVENT_LABELS`, `AUDIT_OUTCOME_LABELS` and
`AUDIT_DETAIL_LABELS`, written as JSON (quoted keys, one entry per line) so that `test_audit.py` can
lift them out of the file with a regex and `json.loads` and compare their key sets with the three
constants: a code added on one side without the other fails that test.

| `event` | Shown as |
|---|---|
| `setup` | First administrator created (the detail `recover` shows *Recovery administrator created*) |
| `setup.failed` | Setup attempt |
| `recover.requested` | Recovery code created |
| `recover.expired` | Recovery code expired |
| `signin` | Signed in |
| `signin.failed` | Sign-in attempt |
| `signin.throttled` | Sign-in attempt |
| `signout` | Signed out |
| `session.expired` | Session ended |
| `session.ended` | Session ended |
| `password.changed` | Password changed (outcome `ok` for the change, `failed` for a wrong current password) |
| `user.created` | Person added |
| `user.deleted` | Person deleted |
| `user.disabled` | Deactivated |
| `user.enabled` | Reactivated |
| `user.role` | Role changed |
| `user.password_reset` | Password reset by an administrator |
| `forbidden` | Refused (administrators only); outcome `failed` |
| `manager.reset` | Manager reset |
| unknown | the code itself |

| `outcome` | Shown as |
|---|---|
| `ok` | Succeeded |
| `failed` | Failed |
| `throttled` | Throttled |
| unknown | the code itself |

The *Details* column shows `detail` through one pure `auditDetail(event, detail)`. `detail` is a
space-separated list of tokens (`DESIGN.md` 10.2: `<reason> count=<n> retry_after=<n>`, `role=<r>`, or
one reason word); each token is translated and the translations joined with ` · `: `count=<n>` (the
per-minute sum of `signin.failed`, `signin.throttled` and `setup.failed` from one source, REVIEW R8) →
*{n} attempts in one minute*; `retry_after=<n>` → *delayed {n} s*; `role=<r>` → *{Administrator |
Operator}*; `idle` / `absolute` (on `session.expired`) → *idle* / *after the maximum session length*;
`user_disabled`, `user_deleted`, `password_reset`, `password_changed`, `evicted` (on `session.ended`) →
*deactivated*, *deleted*, *password reset by an administrator*, *password changed*, *too many
sessions*; `setup` / `recover` (on `setup`) → *first run* / *recovery*; `invalid_code`,
`weak_password`, `invalid_name`, `exists`, `invalid_credentials`, `disabled`, `bad_record`,
`admin_required` → *wrong code*, *password refused*, *name refused*, *name taken*, *wrong password*,
*account deactivated*, *record unreadable*, *administrators only*; the throttle reasons `pair`,
`source`, `name`, `busy` → *this name from this source*, *this source*, *this name from an unfamiliar
source*, *the manager was busy*; anything else as given. The reason words are the `AUDIT_REASONS` of
`app/accounts.py`, and the same `test_audit.py` case compares `AUDIT_DETAIL_LABELS` of `users.js` with
them. The *Target* of a `user.*` and `forbidden` row is appended to the Details cell as *for {name}*
or *at {route}*.

The *Event* filter lists the labels above (one option per distinct label, each carrying its codes;
*Sign-in attempt* sends `event=signin.failed,signin.throttled`, the manager accepting a comma list,
section 12, C12). The *Outcome* filter is *All / Succeeded / Failed / Throttled* → `ok`, `failed`,
`throttled`.

A failed or throttled sign-in row, and a failed setup, shows the submitted name only when it equals an
existing record's name; otherwise the manager recorded `actor: '-'` (REVIEW R2: a password typed into
the username field never reaches the file or this table) and the cell shows *—*. The two files the
manager keeps (`audit.jsonl`, `audit-failures.jsonl`) are merged by time behind `GET /api/audit`; the
page sees one list. The source address is text; IPv6 addresses wrap (`overflow-wrap: anywhere` of
`.debug-card dd`, style.css:2321, is applied to the cell).

## 6. Change password and sign out

### 6.1 The dialog (index.html, static)

```html
<dialog id="password-dialog" aria-labelledby="password-title"><div class="dialog-head"><div><h2 id="password-title">Change password</h2></div><button type="button" class="icon-button close" id="password-close" aria-label="Close">×</button></div>
<p id="password-lead">Choose a new password for your account.</p>
<form id="password-form" novalidate>
<label for="password-current">Current password</label><input id="password-current" type="password" autocomplete="current-password" maxlength="128">
<label for="password-new">New password</label><input id="password-new" type="password" autocomplete="new-password" maxlength="128"><p class="form-help">At least 12 characters. Any characters count; length matters more than symbols. Not your username, and not a common password.</p>
<label for="password-confirm">New password again</label><input id="password-confirm" type="password" autocomplete="new-password" maxlength="128"><p class="form-help" id="password-sessions">Your other browsers and devices are signed out when the password changes.</p>
<p id="password-error" class="form-error" role="alert"></p>
<div class="dialog-actions"><button type="button" class="button secondary" id="password-cancel">Cancel</button><button type="submit" class="button primary" id="password-submit">Change password</button></div>
</form></dialog>
```

Styling comes from the dialog rules (style.css:1568-1588, labels 1306-1313, `.form-error` 1328, `.form-help` 1330, `.dialog-actions` 556). The dialog sits after
`</main>` (index.html:319) with the other dialogs (`test_shell_ui.js:864` pins that a dialog is never
inside a tab panel).

### 6.2 Behaviour (`account.js`, a new feature script of the page)

A new script `account.js` loaded after `preferences.js` (index.html:3) holds the account functions
so `app.js` does not grow; it follows the pattern of `preferences.js` (`prefsOpen`, preferences.js:133-138:
`showModal` behind a `typeof` guard). Globals: `accountOpenPassword()`, `accountSignOut()`,
`passwordProblem(username, current, next, confirm)` (pure; the checks of section 2.3 plus *Enter
your current password.* and *The new password is the same as the current one.*).

1. Manager ▾ › *Change password…* → `accountOpenPassword()`: clears the fields and the error,
   `showModal()`, focus on `#password-current`.
2. Submit: `passwordProblem()` first; then `POST /api/session/password`
   `{current, password}` (section 12, C11). A password change always ends the person's other
   sessions; there is no checkbox.
   200 → close, one toast *Password changed. Other sessions were signed out.*
   401 `invalid_credentials` → the answer's `detail.message` (*The current password is not right.*),
   focus `#password-current`. This 401 is not `signed_out`: `sessionLost` matches only
   `detail.code==='signed_out'`, so the page does not treat it as an ended session.
   422 → the manager's `detail.message` (section 2.3 sentences). 429 → the manager's `detail.message`
   (*Too many sign-in attempts. Try again in {n} s.*, REVIEW R5) as given, without a countdown (the
   dialog is not the sign-in page; the person waits and tries again). Any other failure → *The manager
   did not answer. Try again.*
3. Cancel and × close without a request.

### 6.3 A required change never happens inside the application (REVIEW R1)

The former required dialog of `index.html` is gone. `must_change_password` is set only when an
administrator creates a person or resets a password, and a reset ends every session of that person; a
live session therefore never becomes restricted, and a restricted session never gets past the gate to
`index.html` (its page requests go to `/login?change=1&next=…`, its `/api/state` answers 403). The
change happens on the sign-in page (section 1.8) and nowhere else; `render()` opens no dialog for the
flag, `accountOpenPassword()` has no `required` option, and the dialog of section 6.1 keeps its Cancel.

### 6.4 Sign out (REVIEW R10)

Manager ▾ › *Sign out* → `accountSignOut()`:

1. `sessionMark()` first, so the poll stops before the cookie is gone (otherwise the poll's 401 would
   race the navigation and add `reason=ended` to a sign-out). Nothing is removed from storage yet
   (item 4).
2. This browser's Wireshark sessions end first: `POST /api/capture/sessions/end-all` with body `{}`
   (the existing owner-scoped route, capture_sessions.py:213, the one `endAllCaptureSessions()` calls at
   capture.js:453), sent directly with `fetch` because `api()` refuses to send after `sessionMark()`;
   best effort (its answer and any failure are ignored); skipped when `captureEnabled===false`
   (capture.js:20). `DELETE /api/session` cannot do this itself: the owner cookie `clab_capture_owner`
   is set with `Path=/api/capture` (capture_sessions.py:113-114) and never reaches `/api/session`.
3. `DELETE /api/session` with body `{}` (the guard needs a body, main.py:119-156), sent directly with
   `fetch` (`method:'DELETE'`, `Content-Type: application/json`, body `'{}'`) for the same reason as
   step 2: `api()` and `json()` refuse to send after `sessionMark()` and would throw
   `sessionEndedError()` with the session still alive on the manager. Its response always clears
   `clab_capture_owner` with `Path=/api/capture` as well as the session cookie (section 12, C14), so a
   later person in the same browser can never inherit a desktop session even when step 2 failed (a
   session left behind by a failed step 2 ends at the capture service's own limit).
4. Only a 200 leaves (`DESIGN.md` 7.3: the route answers 200 always, also for a session already gone,
   never 401, so any other status means the manager was not reached or failed): then
   `shellRemove('sessionStorage','activeLab')` (section 7 item 4) and `location.replace('/login')`
   through the `shell.js` function `goSignIn()` (no `next`, no reason: a person who signed out lands on
   a clean sign-in page; the body is not read, the clearing cookies travel in the headers). On a
   non-200 answer or a network failure the page stays: `sessionRetry()` restores it (the flag is cleared, the poll and any chain that met the guard
   during the attempt resume, section 3.2), `notify()` (app.js:51) shows *Sign-out did not reach the
   manager. Try again.*, and *Sign out* stays enabled. Reason: since the load check (REVIEW R14) a
   `/login` reached with a live session answers 200 to `GET /api/session` and sends the browser straight
   back into the application, so on a shared classroom computer a sign-out that did not happen must be
   seen, never papered over by a navigation (the former "a failed `DELETE` is reported nowhere" is
   withdrawn).
5. Terminal pop-ups and capture viewers opened by this tab: the manager ends their sockets when the
   session ends (section 12, C9); their pages show the sentence of section 3.5. The application does
   not try to close them (`window.open` returns a handle the page does not keep, app.js:410-411).
6. The menu item says what step 2 does: *Signing out also closes this browser's Wireshark sessions.*
   (`#account-signout-note`, section 4.1), shown while capture is enabled. An **expiry** ends nothing
   of this: the owner cookie stays and the same browser, signed in again, finds its capture sessions
   (section 3.5).
7. *Sign out everywhere* is not a separate menu item: a password change always ends the person's
   other sessions, and so does the administrator's Deactivate. A person who suspects a stolen session
   changes the password; that is the right reflex and the one action that helps.

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
   after the 200 of `DELETE /api/session`, just before leaving (section 6.4 item 4; a sign-out that
   failed keeps the page and its lab; the key is `reset:false` in the families because it is data, not
   a preference; the sign-out is not a preferences reset). The opened-dates and dismissed notices (`clab.opened.*`,
   `clab.dismissed.*`) stay: they are harmless and shared labs are the model (D2).

## 8. Wording

Every new string. Product voice: short, concrete, sentence case, no exclamation marks. Where a string
is the manager's (every 4xx body the sign-on code sends carries `detail.message`, REVIEW U11; the 422
sentences, section 12, C7), the manager uses the same text and the page shows what it received; the
rows marked "the manager's … message" are those. A page's own sentence is used only when there is none
(a network failure, a non-JSON body).

| Where | Id or place | Text |
|---|---|---|
| login.html | title | Sign in |
| login.html | h1 | Sign in |
| login.html | lead | Use the account your administrator gave you. |
| login.html | labels | Username / Password |
| login.html | `#signin-show` | Show / Hide |
| login.html | `#signin-submit` | Sign in / Signing in… |
| login.html | help | Forgot your password? Ask an administrator to reset it. |
| login.js | empty | Enter your username and password. |
| login.html | `#signin-checking` | Checking… |
| login.js (the manager's 401 `message`) | 401 | Wrong username or password. |
| login.js, setup.js, account.js (the manager's 429 `message`, one sentence for every 429, REVIEW R5) | 429 | Too many sign-in attempts. Try again in {n} s. |
| login.js, setup.js | `#signin-reason` / `#setup-reason` when a countdown ends (REVIEW U15) | You can sign in again. |
| login.js | other | The manager did not answer. Try again. |
| login.js | `#signin-reason` for `reason=ended` | Your session ended. Sign in again to continue. |
| login.html | `#signin-plain` | This connection is not encrypted. Your password would travel in clear text. Ask the administrator to enable TLS before signing in from outside the lab network. |
| login.html | `#change-title` | Choose your own password |
| login.html | change view lead | The password you signed in with was set by an administrator. Choose your own before you continue. |
| login.html | change view labels | Current password / New password / New password again |
| login.html | `#change-policy` | the policy sentence below |
| login.html | `#change-submit` | Change password and continue / Changing… |
| login.html | `#change-signout` | Sign out |
| login.js, account.js | empty current | Enter your current password. |
| login.js, account.js (the manager's 401 `invalid_credentials` message) | wrong current | The current password is not right. |
| setup.html | title | Create an administrator (RECONCILIATION 5: a bare title on an exposed page, as `Sign in`) |
| setup.html | h1 | Create the first administrator |
| setup.html | lead | Enter the setup code the installer printed, then choose the account you will sign in with. |
| setup.js | h1 with `?recover=1` (REVIEW R11) | Recovery: create one new administrator |
| setup.js | lead with `?recover=1` | Enter the code the recovery command printed, then choose a new administrator account. Existing accounts are not changed. |
| setup.html | code help (REVIEW U13) | Printed at the end of the installation. On the VM: `sudo cat /srv/containerlab-node-manager/data/setup-code` |
| setup.html | username help | Lowercase letters, digits, dot, dash and underscore. 2 to 32 characters. |
| setup.html, dialogs | policy | At least 12 characters. Any characters count; length matters more than symbols. Not your username, and not a common password. |
| setup.html | `#setup-submit` | Create account and sign in / Creating… |
| setup.js | empty code | Enter the setup code. |
| setup.js (the manager's 401 `invalid_code` message) | 401 | That setup code is not right. On the VM, run: sudo cat /srv/containerlab-node-manager/data/setup-code |
| setup.js (the manager's 409 `exists` message) | 409 | That name already exists. Choose a new name for the recovery administrator. |
| setup.js (the manager's 404 `setup_closed` message) | 404 | Setup is closed. Sign in, or ask the VM administrator to run the recovery command. |
| setup.js, users.js, account.js | length | Use at least 12 characters. |
| same | match | The two passwords are not the same. |
| same | username | Choose a password that is not your username. |
| same (manager) | deny-list | That password is too common. Choose another. |
| same (manager's 422 text) | username rule | Use lowercase letters, digits, dot, dash or underscore, 2 to 32 characters. |
| app.js `api()` | 401 error message | Your session ended. Sign in again. |
| index.html | `#session-banner-text`, dialog case (the markup's default; `renderSessionBanner('dialog')`) | Your session ended. What you typed in the open dialog is still here. |
| index.html | `#session-banner-caption`, dialog case (the markup's default) | Sign in in a new tab, come back and choose Try again. Or sign in here and lose the open dialog. |
| shell.js | `#session-banner-text`, draft case (`renderSessionBanner('draft')`) | Your session ended. Your design draft is still on this page. |
| shell.js | `#session-banner-caption`, draft case | Sign in in a new tab, come back and choose Try again. Or sign in here and lose the draft. |
| shell.js | `#session-banner-text`, save panel case (`renderSessionBanner('panel')`, REVIEW U9) | Your session ended. What you typed in the save panel is still here. |
| shell.js | `#session-banner-caption`, save panel case | Sign in in a new tab, come back and choose Try again. Or sign in here and lose what you typed. |
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
| index.html | `#account-signout-note` (REVIEW R10) | Signing out also closes this browser's Wireshark sessions. |
| account.js | toast when `DELETE /api/session` did not answer 200 (section 6.4 item 4) | Sign-out did not reach the manager. Try again. |
| management.js | `#vm-operator` (REVIEW R13) | Ask an administrator to set up the VM connection. |
| management.js | `#home-vm-banner-text` for an Operator | The lab VM is not connected yet. Ask an administrator to connect it. |
| home.js | `homeStartReason()` for an Operator | Ask an administrator to connect the VM |
| status.js | `diagnosticsAdvice(role)` (REVIEW U5) | see Diagnostics / ask an administrator to check Diagnostics |
| vm-connection.html | the Diagnostics sentence | An administrator can open Diagnostics to check the manager version and the VM connection. |
| app.js | reason on VM connection… and Manager settings… for an Operator | Administrators only |
| index.html | `#password-title` | Change password |
| index.html | `#password-lead` | Choose a new password for your account. |
| index.html | labels | Current password / New password / New password again |
| index.html | `#password-sessions` | Your other browsers and devices are signed out when the password changes. |
| index.html | `#password-submit` | Change password / Changing… |
| account.js | empty current | Enter your current password. |
| account.js | same | The new password is the same as the current one. |
| account.js | 401 `invalid_credentials` | The current password is not right. |
| account.js | 429 | the manager's `detail.message` (the 429 sentence above), shown as given, no countdown |
| account.js | toast | Password changed. Other sessions were signed out. |
| users.html | title | People and sign-ins · Containerlab Node Manager |
| users.html | h1 | People and sign-ins |
| users.html | lead | Who can sign in to this manager, and what happened at the sign-in page. |
| users.html | card 1 | People |
| users.html | columns | Name / Role / Status / Last sign-in / Actions |
| users.js | status values (the field is `disabled`) | Active / Inactive |
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
| users.js | own row | Sign out instead. / Ask another administrator. / Use Manager ▾ › Change password… for your own account. (REVIEW R12) |
| users.js | 409 from the manager | the manager's `detail.message` as given: `DESIGN.md` 7.4's sentence per code and route (*The last administrator stays.* for `last_admin`; for `self_change`: *You cannot deactivate your own account. Sign out instead.* on `PATCH` with `disabled: true`, *You cannot change your own role. Ask another administrator.* on `PATCH` with `role`, *You cannot remove your own account. Ask another administrator.* on `DELETE`, *Use Manager ▾ › Change password… for your own account.* on the password route; section 5.4) |
| users.js | event and outcome labels, details | the tables of section 5.6 (`AUDIT_EVENT_LABELS`, `AUDIT_OUTCOME_LABELS`, `AUDIT_DETAIL_LABELS`, `auditDetail()`) |
| users.js | `#users-status` | {n} people · updated {time} |
| users.html | card 2 | Sign-ins and changes |
| users.html | filters | Show (Last hour / Last 24 hours / Last 7 days / All) / Person / Event (All + the labels of 5.6) / Outcome (All / Succeeded / Failed / Throttled → `ok` / `failed` / `throttled`) / Address / Apply |
| users.html | columns | Time (UTC) / Person / Event / Outcome / Source address / Details |
| users.js | `#audit-status` | {n} events shown (latest 500 matching). Updated {time}. |
| users.js | empty | No events match. Change the filters. |
| users.html | `#users-forbidden` | Only administrators can open this page. |
| debug.js | 403 `admin_required` | Administrators only. |
| users.js | load failure | The list could not be loaded: {detail} |

## 9. Tests

### 9.1 Node harnesses (`node --test tests/*.js`)

| New or changed file | Harness to copy | What it pins |
|---|---|---|
| `tests/test_login_ui.js` (new) | `test_debug_ui.js:4-13` (`fixture(fetch)`: a `Map` of fake elements, `vm.createContext` with `document`, `fetch`, `setTimeout`) plus a fake `location` `{search,hash,protocol,hostname,replace(url){calls.push(url)}}` and a `setInterval` that the test ticks. | `loginNext`: `/`, `/#lab=a&view=devices`, `/static/workspace.html#mode=ssh` pass; `//evil`, `/\evil`, `https://evil`, `javascript:…`, `/login`, `/api/state`, a 3000-char path, missing → `/`; with `hash` `#lab=a&view=devices` and `next=%2F` → `/#lab=a&view=devices`, with a `next` that already has a `#` the hash is not appended, a hash with `\` is dropped (REVIEW U7). `loginPlain`. **Load check (REVIEW R14):** the form is hidden and `#signin-checking` shown until the first `fetch` (`GET /api/session`) answers; 401 shows the form and focuses `#signin-user`; a network failure shows the form; 200 with `must_change_password:false` calls `location.replace` with `next` and shows no form; 200 with `must_change_password:true` shows `#signin-change` with `#change-current-field` visible. Empty submit shows the sentence and sends nothing. 401 keeps the username, clears the password, shows the answer's `detail.message` and the fallback when the body has none. 429 with `retry_after:3` puts the sentence in `#signin-error` once, `#signin-wait-said` reads `3` and never changes, `#signin-wait` reads `3`, `2`, `1` on the ticks, the button is disabled, and after three ticks the button is enabled, `#signin-error` is empty and `#signin-reason` reads *You can sign in again.* (REVIEW U15). 200 calls `location.replace` with the safe `next` including the hash. **Change view (REVIEW R1):** after a 200 with `must_change_password:true`, `#signin-card` is hidden, `#change-current-field` is hidden, `changeProblem` sentences show without a request, the `POST /api/session/password` body is `{current:<the typed sign-in password>, password}`; after a 422 a second submit sends the same `current` again (the held password is kept through 422, 429 and a network failure); 200 → `location.replace(next)`; 401 `invalid_credentials` shows the message and the current field, and the next submit sends the field's value (the held password is gone); 401 `signed_out` shows the sign-in form with the reason line; `#change-signout` sends `DELETE /api/session` with `{}` through the fake `fetch` and shows the sign-in form, and a submit after it would send `current:''` (the held password was cleared). Source pin: no `innerHTML`, no `style=`, no `localStorage`/`sessionStorage`, no `addEventListener('keydown'`. The username is lowercased in the request body. `login.css` names no selector of the application (`#save-chip`, `.topbar`, `.panel`, …; a list is asserted absent). `login.html` and `setup.html` link `/static/login.css` and never `style.css`; `setup.html` loads `login.css` and `setup.js` only. |
| `tests/test_setup_ui.js` (new) | same | `setupProblem` for each message; `setupRecover` (`?recover=1` true, `?recover=0` and nothing false) and the heading and lead it sets (REVIEW R11); 401 shows the answer's `detail.message`, clears and focuses the code; the code is sent trimmed and otherwise as typed (REVIEW U13); 409 `exists` shows the message and focuses `#setup-user` with the fields kept; 404 shows the answer's `detail.message` (*Setup is closed…*) and unhides `#setup-signin` (href `/login`); another status shows *The manager did not answer. Try again.*; 429 with `retry_after:3` puts the sentence in `#setup-error` once, `#setup-wait-said` reads `3` and never changes, `#setup-wait` reads `3`, `2`, `1` on the ticks, the button is disabled, and after three ticks the button is enabled, `#setup-error` is empty and `#setup-reason` reads *You can sign in again.* (the three assertions of the login 429 test, REVIEW U15); 422 shows the manager's message; 200 → `location.replace('/')`; the code never appears in `location` calls or storage. |
| `tests/test_session_ui.js` (new) | `test_operations_ui.js` (pure functions) | `sessionLost` shapes (401 without the code is false; 403 is false); `loginUrl` encoding of path, search and hash; `sessionMark` once, true again after `sessionClear`; `sessionGo` under a fake `location`; `sessionEndedError()` carries `sessionEnded:true`, `status:401` and the sentence; `sessionOnResume` keeps one entry per function; `sessionRetry` with a `refresh` that resolves runs `sessionRestored` and each function once, empties the set and resolves `true`; with a `refresh` that rejects without marking (a network failure) does the same and leaves `sessionEnded()` false; with a `refresh` that marks the session again (calls `sessionMark` and rejects) runs none, keeps them, resolves `false` and leaves `sessionEnded()` true; without a `refresh` global runs them (REVIEW U8). |
| `tests/test_users_ui.js` (new) | `test_debug_ui.js` | Rows are text (a name `<b>x</b>` renders as text); the last-admin and own-row buttons (Deactivate, Change role…, Reset password…) are disabled with the sentences (REVIEW R12); 403 shows `#users-forbidden`; the audit query string carries the filters (`limit&offset&event&actor&outcome&since&address`); the PATCH bodies are `{role}` and `{disabled}`; actor `-` shows *—*; every event and outcome code of section 5.6 maps to its label and an unknown code shows itself; `auditDetail` for `count=12`, `retry_after=30`, `role=admin`, `idle`; a 409 shows the answer's `detail.message`. |
| `tests/test_account_ui.js` (new) | `test_readiness_ui.js` (loads `status.js` and `app.js` together) + `account.js` | `passwordProblem`; `roleLabel`; `renderAccount` hides `#account-users` and `#manager-diagnostics` for an operator, sets the chip, and sets `disabled` **and** the visible reason *Administrators only* on `#vm-settings` and `#manager-settings` for an operator and clears both for an admin (REVIEW U4); `renderAccount` opens no dialog for `must_change_password:true` (REVIEW R1); `#account-signout-note` hidden when `captureEnabled===false`; sign-out marks the session first, then both `POST /api/capture/sessions/end-all` and `DELETE /api/session` reach the context's fake `fetch` in that order while `sessionEnded()` is true (never `api()` or `json()`, which the test stubs to throw), end-all is skipped when `captureEnabled===false`, a failed end-all still leads to the `DELETE`; after a `DELETE` answered 200 `shellRemove('sessionStorage','activeLab')` and `goSignIn` are called; after a `DELETE` that rejects, or answers 500, `goSignIn` and `shellRemove` are not called, `sessionRetry` is called once and `notify` carries *Sign-out did not reach the manager. Try again.* (REVIEW R10, R14); the password dialog's 429 and 401 show `detail.message`. |
| `tests/test_shell_ui.js` (changed) | its own harness (43-84): add `#session-banner` with its three buttons, `data-session-action`, and the `sessionMark`/`sessionClear`/`sessionGo` stubs to the context | `signedOut()` with no open dialog calls `sessionGo('ended')`; with `dialog.open` shows the banner clone inside the dialog and does not navigate; with a visible `[data-panel]` holding `#save-name[data-dirty]` (and separately `#save-url` with a value) it does not call `closeMenus()`, does not navigate, shows the page banner with the save-panel text and caption (REVIEW U9); in that state a `pointerdown` dispatched on `#session-retry` (the harness runs the capture-phase `document` listeners first, :26-34) leaves the panel open and `#save-name` untouched, while a `pointerdown` on the harness's `outside` element still closes it; an Escape `keydown` dispatched on `#session-retry` closes nothing; `renderSessionBanner('draft')` and `('panel')` write both `#session-banner-text` and `#session-banner-caption`; a second `signedOut()` call does nothing; `sessionRestored` hides the banner and removes the clone. **Rewrite, never delete**: the menu-order pin at :846-859 (`Diagnostics` last) becomes "Diagnostics is the last item before the account group" with the new ids in order; the listener-count pin at :947-954 stays at nine unless the lead chooses document delegation (then ten, with the reason). |
| `tests/test_page_load_ui.js` (changed) | its own `loadPage()` (24-43) | `session.js` is listed between `status.js` and `shell.js`, `account.js` after `preferences.js`; no top-level name collides (the `get` of login.js is a file-local `const`: login.js is never loaded with the page, but `session.js` and `account.js` are, so their names must be unique: `sessionLost`, `loginUrl`, `sessionEnded`, `sessionMark`, `sessionClear`, `sessionEndedError`, `sessionGo`, `sessionOnResume`, `sessionRetry`, `accountOpenPassword`, `accountSignOut`, `passwordProblem`, `roleLabel`, `renderAccount`). `api()` on a 401 `signed_out` stub calls `signedOut` (set a counter on the context) and still throws with `status 401`; `api()` throws `sessionEnded:true` without calling `fetch` once `sessionEnded()` is true. `refresh()` sends nothing once `sessionEnded()` is true. The pin at :207-210 (no page other than index.html loads `device-diagnostics.js`) is unchanged; a sibling pin says no page other than `index.html` loads `account.js`, and every page that fetches loads `session.js` with the one `?v=`. Add `login.html`, `setup.html`, `users.html` to the standalone list the harness iterates for `?v=` and inline styles (:212-228 does that for lab-builder.html; the sweep at `test_shell_ui.js:879` already covers foreign assets on every `.html`). |
| `tests/test_status_ui.js` (changed) | its own | `diagnosticsAdvice('admin')`, `('operator')`, `('')` (REVIEW U5). |
| `tests/test_home_ui.js` (changed) | its own | `homeStartReason` for an operator with the VM not connected answers *Ask an administrator to connect the VM* and *Connect the VM first* for an admin (REVIEW R13). |
| `tests/test_vm_password_ui.js` (changed; it loads `management.js`) | its own `harness()` (1-13), with `state.user` added to the context | **Every entry point as an operator** (REVIEW R13), the eight of section 4.5: the five this harness can call, `$('vm-settings').onclick()`, `openVmDialog()`, `maybePromptVmConnection()` with `discovery.configured` false, `$('vm-connect-empty').onclick()`, `$('home-vm-connect').onclick()` → no call to `json('/host','PUT',…)`, `#vm-form` hidden and `#vm-operator` shown (or the dialog not opened, for the prompt); `#home-vm-banner-text` reads the operator sentence and `#home-vm-connect` is hidden. The other three live in files this harness does not load and are pinned at the source in the same file: every `'vm'` action site of save-drawers.js (:330, :445, :793) and save-header.js (:567) and the `banner-vm` action of app.js (:287) calls `openVmDialog()` under its `typeof` guard and none of those lines names `/host` or `PUT` (a regex over the non-comment lines), so each reaches the one role-aware function; and `test_readiness_ui.js` (it paints `renderLabBanner()`, :180) adds the case `ls.key==='unknown'` with an operator `state.user`: the spec passed to `setBanner('lab-banner', …)` has no `banner-vm` action, and with an admin it has one. The existing admin tests pass unchanged with an admin `state.user` in their contexts. |
| `tests/test_operations_ui.js`, `test_device_impairments_ui.js` (changed) | each its own | the pinned *see Diagnostics* sentences (test_operations_ui.js:871-872, test_device_impairments_ui.js:221) are kept with an admin `state.user` in the context and gain the operator variant (REVIEW U5). |
| `tests/test_operations_ui.js`, `test_network_design_ui.js` (three chains), `test_git_progress_ui.js`, `test_load_ui.js`, `test_restore_ui.js`, `test_device_diagnostics_ui.js`, `test_map_tools_ui.js` (changed) | each its own, with `sessionEnded`/`sessionOnResume`/`sessionEndedError` stubs in the context | **one test per chain of section 3.3 item 3** (REVIEW U8): the first answer is a 401 that sets the stub's flag; the chain makes no further request while the flag is set (the test ticks the fake timers), writes none of its failure sentences (no `.form-error` text, no `pollProblem`, no `loadPaused`, no `restorePaused`, no *paused* link-state sentence), does not count a retry, and registers exactly one resume function; after the test clears the flag and runs that function the chain requests again. For the Load, Git and map link chains a second test calls the render-path entry (`loadWatch(job)`, `gitStartWatch(job)`, `mapLinkSchedule()`) while the flag is set and asserts that no timer is armed. |
| `tests/test_debug_ui.js`, `test_terminal_ui.js`, `test_capture_session_ui.js`, `test_map_editor_ui.js`, `test_lab_builder_ui.js` (changed) | each its own | one test each: a 401 `signed_out` answer produces the page's sentence (section 3.5) and, where the page redirects, one `location.replace` call to `/login?next=…`; the terminal and the capture viewer never navigate; each helper throws `sessionEnded:true` without calling `fetch` once `sessionEnded()` is true; `test_debug_ui.js` also pins the 403 `admin_required` sentence as the answer's `detail.message`; `test_map_editor_ui.js` pins that Save calls `sessionRetry` first when paused. |
| `tests/test_workspace_ui.js` (new) | `test_debug_ui.js` | a test of `workspace.js` (S10a, the owner of `workspace.js` and `workspace.html` in BUILD.md 2) pins that `#workspace-links` is hidden for an operator and shown for an admin, and that its `api()` throws `sessionEnded:true` without calling `fetch` once `sessionEnded()` is true. |

Python side (the backend designer's, listed so the lead can route it): `test_app.py` gains the
session fixture (`client.post('/api/session', json=…)`), and every existing test that calls a route
signs in first through a helper; TestClient keeps the cookie jar. One Python test crosses into this
document's files: `test_audit.py` lifts `AUDIT_EVENT_LABELS`, `AUDIT_OUTCOME_LABELS` and
`AUDIT_DETAIL_LABELS` out of `users.js` (section 5.6) and compares their key sets with the backend's
`AUDIT_EVENTS`, `AUDIT_OUTCOMES` and `AUDIT_REASONS` (REVIEW R3); it belongs to S1 and reads S9's
file, so the lead runs it at integration.

### 9.2 Playwright checks under `docs/sign-on/tools/`

One script `check_signon.py` in the shape of `docs/ui-review-001/tools/check_ui001.py` against
`docs/redesign/tools/fixture_manager.py` (REVIEW R15, R21: the fixture completes setup with fixture
credentials, seeds one admin and one operator, and by default signs every request in through a
fixture-only ASGI wrapper that adds the fixture admin's cookie when a request has none; `--signed-out`
and `--role operator` switch it; its `POST /__fixture/expire` route is a route of the wrapper calling
`app.state.sessions.end_user(name, reason)`, and `app/` contains no fixture code; section 13, Q5; the
QA worker owns it in BUILD.md S11), at the four viewports 1440×900, 1280×800, 760×1024, 390×844. The
sign-on checks run the fixture with `--signed-out` (and `--role operator` where the row says so); the
other campaigns' checks keep running against the default and change nothing.

| Check | Assertion |
|---|---|
| Sign-in page | `/` redirects to `/login?next=%2F`; `#signin-checking` is gone and the form visible once `GET /api/session` answered 401; the card is within the viewport; no horizontal scroll at 390; the brand and the h1 are visible; focus is on `#signin-user`. |
| Signed in from another site (REVIEW R14) | Signed in, navigate to `/#lab=<id>` from a page on another origin (a `data:` or `file:` page with a link; the context's cookie is `SameSite=Strict`) → the gate sends the browser to `/login`, the page shows *Checking…* and leaves for `/#lab=<id>` without showing the form. |
| Wrong password | `#signin-error` reads *Wrong username or password.*; `#signin-user` keeps its value; `#signin-password` is empty and focused. |
| Throttling | After the fixture's limit, `#signin-error` matches `/^Too many sign-in attempts\. Try again in \d+ s\.$/` (textContent, the two spans included once each), `#signin-wait-said` keeps its first value while `#signin-wait` changes, `#signin-submit` is disabled; after the countdown it is enabled, `#signin-error` is empty and `#signin-reason` reads *You can sign in again.* (REVIEW R5, U15). |
| Sign-in and `next` (REVIEW U7) | Visit `/#lab=<id>&view=devices` signed out → the address is `/login?next=%2F#lab=<id>&view=devices` (the gate's `next` is the path; the browser kept the fragment); sign in → URL is `/#lab=<id>&view=devices`, the Devices tab is active, `#account-chip` shows the name at 1440 and 1280 and is hidden at 760 and 390. |
| Forced change (REVIEW R1) | As the admin, add a person; in a fresh context sign in as that person with the temporary password → every redirect ends in a 200, the page shows `#signin-change` with `#change-current-field` hidden; typing a weak password shows the sentence without a request; a good password → `location` is `next` (`/`), Home renders, `GET /api/state` is 200. Reload `/login` as a restricted session (sign in again before the change in another fresh context) → the change view with the Current password field. `#change-signout` → the sign-in form, `GET /api/session` 401. A `GET /static/style.css` sent without `text/html` in `Accept` (Playwright `request.get`) as a restricted session is 403 `password_change_required`; a navigation to it is `302 /login?change=1&next=%2Fstatic%2Fstyle.css`; `/` is `302 /login?change=1&next=%2F`. |
| Open redirect | `/login?next=//example.org` then sign in → the URL is `/`. Same for `/login?next=/api/state`. |
| 401 mid-work | As the admin, open the VM connection dialog, type into a field, expire the session through the fixture (`POST /__fixture/expire`, the fixture wrapper's route), wait 6 s → one `GET /api/state` request after expiry, no more (the fixture counts); the banner clone is inside `#vm-dialog`; the typed value is still there. Click *Try again* after signing in in a second page of the same context → the banner is gone, polling resumed. |
| 401 with a dirty save panel (REVIEW U9) | Open the save chip panel on a lab, type a save name, expire the session → the panel stays open, `#save-name` keeps the text, `#session-banner` is visible with the save-panel text and caption, no navigation; a real click on *Try again* (still signed out) leaves the panel open and the text in place. |
| 401 under a running chain (REVIEW U8) | Start an operation whose output dialog polls (the fixture's scripted job stays `running`), expire the session → after the first 401 the fixture counts no further `GET /api/operations/<id>`; sign in in a second page, *Try again* → the output poll requests again and the dialog shows the job's end. |
| Sign out (REVIEW R10) | With a capture session open in the fixture, Manager ▾ › Sign out → the fixture saw `POST /api/capture/sessions/end-all` before `DELETE /api/session`; `/login` with no `next`, its load check answering 401 and the form shown; `GET /api/state` answers 401; the Back button does not show the application; the response to `DELETE /api/session` carried a `Set-Cookie` clearing `clab_capture_owner` with `Path=/api/capture`. With the route blocked in the browser context (`page.route('**/api/session', abort)` for `DELETE` only): the page stays on `/`, the toast reads *Sign-out did not reach the manager. Try again.*, and the next poll request is seen by the fixture (REVIEW R14). |
| Users page as admin | `#account-users` visible; the page lists two people; the only admin's Deactivate is disabled with the sentence; add, role change, reset and deactivate each produce their toast; the audit table shows the sign-ins of this run with the operator's failed attempt and a throttled row. |
| Users page as admin, own row (REVIEW R12) | The admin's own *Reset password…* is disabled with *Use Manager ▾ › Change password… for your own account.*; the audit table's failed sign-in with a password typed as the username shows *—* (REVIEW R2). |
| Users page as operator | `#account-users` and `#manager-diagnostics` hidden; `/static/users.html` shows `#users-forbidden`; `/static/debug.html` shows *Administrators only.*; *VM connection…* and *Manager settings…* are `disabled` and show *Administrators only* (REVIEW U4). |
| Operator and the VM (REVIEW R13) | With the fixture's VM unconfigured and `--role operator`: no dialog opens on load; `#home-vm-banner-text` reads the operator sentence and `#home-vm-connect` is hidden; Manager ▾ › *VM connection…* cannot be activated; `openVmDialog()` run from the console shows `#vm-operator` and the fixture counts no `PUT /api/host`. |
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
   (section 3.3 item 2) and no other request from any chain of section 3.3 item 3: `api()` and every
   page helper refuse to send while `sessionEnded()` is true, and each chain stops without a retry and
   resumes only through `sessionRetry()` (REVIEW U8). The reviewer checks the table of 3.3 against
   every `setInterval` and `setTimeout` in `app/static/*.js` (the list in 3.3 names the timers that
   send nothing too) and attacks the two render-path re-arms (Load at load.js:417, Git at
   git-progress.js:127) and the map link schedule (topology.js:210). Also: ten tabs of the application
   open at once, each redirecting to `/login` at the same moment, is ten requests, not a storm.
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
9. **What the sign-in page reveals.** Decided (RECONCILIATION 1 and 2): the exposed pages load
   `login.css`, a small self-contained sheet, never `style.css`; the favicon and the title name
   nothing. The reviewer attacks the sheet: does any selector or comment of `login.css` name a feature
   of the application (section 9.1)?
10. **Reduced motion, contrast, 390 px.** No animation on the new pages; `.form-error` on `--surface`
    is the existing contrast; the Show button and the input share a row at 390 px without overflow;
    the users tables scroll sideways rather than squeeze.
11. **The restricted session and the change view (REVIEW R1).** Follow every redirect of a new
    person to a final 200: `/` → `/login?change=1&next=%2F` → the page (served, not `302 /`) →
    `GET /api/session` 200 with the flag → the change view. Attack the loop the review found: can a
    restricted session reach a page that needs `/api/state`? Can the person leave the view without
    changing (only *Sign out*)? Does the held sign-in password survive anywhere (a variable only, kept
    through a refused new password so the retry does not send `''`, cleared on a 200, a 401 and *Sign
    out*; never storage, never the URL)? Does a reload ask for the current password? Does
    an administrator's second reset between the sign-in and the change end in the sign-in form with the
    reason line, not a stuck view?
12. **Two people, one browser.** Sign out, sign in as another: no trace of the first in the page
    (`activeLab` removed, section 7 item 4; `state` replaced by the first poll; the header text set by
    `render()`; the capture memory keys are per lab and harmless; the Wireshark sessions ended by the
    sign-out and the owner cookie cleared by `DELETE /api/session`, section 6.4).
13. **The load check (REVIEW R14).** `GET /api/session` on every load of `/login`: a slow manager
    leaves *Checking…* for how long before the form shows? (Decision: until the request settles; a
    network failure shows the form; there is no timer, because a form shown early would let a signed-in
    person sign in again and rotate their own session for nothing.) Can the check leak to a scanner?
    (It answers 401 with a cookie-clearing header and nothing else.)
14. **The dirty save panel (REVIEW U9).** With the chip panel open and a name typed: does the banner
    reach the person (the panel is not modal), does a press on the banner close the panel through the
    capture-phase `pointerdown` rule (`shellPointerDown`, shell.js:198-203, registered at :300, must
    return for a target inside `#session-banner` or its clone before `closeMenus()`; a `click` handler
    is too late), does Escape with focus on a banner button close it (shell.js:191 must exempt the
    banner too), does *Try again* leave the text in place, and does the Load panel ever count as
    dirty (it must not)?
16. **A sign-out that did not happen (REVIEW R10, R14).** Block `DELETE /api/session` and sign out:
    the page must stay, say so, and keep polling; a navigation to `/login` would come straight back
    through the load check with the first person still signed in. Also: does `sessionRetry()` after
    the failure resume a chain that met the guard during the attempt?
15. **The throttled sentence (REVIEW U15).** With a screen reader: is the sentence announced once with
    its number, never on a tick, and is *You can sign in again.* announced once? Does the visible
    sentence stay one line at 390 px with the two spans?

## 11. File inventory of this design

The slice letters are BUILD.md section 2.

| File | New or changed | Slice |
|---|---|---|
| `app/static/login.html`, `login.js`, `login.css` | new (sections 1 and 1.8: the load check, the change view, the countdown spans, `.sr-only`) | S7 |
| `app/static/setup.html`, `setup.js` | new (section 2: `?recover=1`, the 409, the code help, `#setup-reason` and the countdown spans) | S7 |
| `app/static/session.js` | new (section 3.2: the whole contract table, `sessionOnResume`, `sessionRetry`, `sessionEndedError`) | S8 |
| `app/static/account.js` | new (section 6: the dialog, the two-step sign-out with both requests through `fetch`, the stay-and-say path when the `DELETE` is not a 200; no `required` option) | S8 |
| `app/static/users.html`, `users.js` | new (section 5: `usersApi()` with the guard, `AUDIT_EVENT_LABELS`, `AUDIT_OUTCOME_LABELS`, `AUDIT_DETAIL_LABELS`, `auditDetail()`, the own-row reset caption) | S9 |
| `app/static/index.html` | changed: scripts (session.js, account.js), `#account-chip`, `#manager-diagnostics` id, the account menu group with `#account-signout-note`, the `span` + `small.menu-reason` children of `#vm-settings` and `#manager-settings`, `#session-banner`, `#password-dialog` (with Cancel) | S8 |
| `app/static/app.js` | changed: `api()` guard line and 401 line, `refresh()` guard, `renderAccount()` + `roleLabel()` (disabling the two items, the sign-out note), call in `render()`, the `banner-vm` action omitted for an operator (:287) | S8 |
| `app/static/shell.js` | changed: `signedOut()` with `sessionDirtyPanel()`, `renderSessionBanner(cause)` (text and caption), `sessionRestored()`, `goSignIn()`; `shellPointerDown` (:198-203) returns for a target inside `#session-banner` or `#session-banner-dialog`, and `shellEscape` (:191) exempts them too | S8 |
| `app/static/status.js` | changed: `diagnosticsAdvice(role)` | S8 |
| `app/static/style.css` | changed: section 27 (account block and chip for `index.html` only; the sign-in rules live in `login.css`); the comment at :190 names both pages that use `.eyebrow` | S8 |
| `app/static/management.js` | changed: `#vm-operator` in the dialog template, role-aware `openVmDialog()` and `maybePromptVmConnection()`, the operator Home banner and hidden connect buttons (:135, :142, :157-158), the sentence at :97 | S8 |
| `app/static/home.js` | changed: `homeStartReason()` for an operator | S8 |
| `app/static/operations.js` | changed: the output poll's `catch` (:625) and the six Diagnostics sentences (:36, :796, :938, :976, :986, :1222) through `opRole()` | S10a |
| `app/static/network-design.js` | changed: the three watchers' `catch` blocks (:1027, :1858, :2027) | S10a |
| `app/static/git-progress.js` | changed: `gitStartWatch()` start guard and `catch` (:346) | S10a |
| `app/static/load.js` | changed: `loadWatch()` start guard and `catch` (:472) | S10a |
| `app/static/restore.js` | changed: `restoreStartWatch()` start guard and `catch` (:368) | S10a |
| `app/static/device-diagnostics.js` | changed: `diagRun()` after its `catch` (:307) | S10a |
| `app/static/map-tools.js` | changed: `mapLinkSchedule()` start guard, `mapLinkRun()` after its `catch` (:187) | S10a |
| `app/static/device-impairments.js` | changed: `IMP_NO_CAP` becomes `impNoCap(role)` | S10a |
| `app/static/workspace.js` | changed: the guard and the 401 check in its `api()` (section 3.5); hides `#workspace-links` for an operator | S10a |
| `app/static/workspace.html` | changed: loads `session.js` with `?v=`; gives its links paragraph `id="workspace-links"` | S10a |
| `app/static/debug.js`, `lab-builder-page.js`, `map-editor-page.js`, `terminal.js`, `capture-session.js` | changed: the guard and the 401 check in each helper; the builder overlay's *Try again*; the map editor's Save calling `sessionRetry()`; the terminal's Reconnect calling `sessionClear()` | S10b |
| `app/static/debug.html`, `lab-builder.html`, `map-editor.html`, `terminal.html`, `capture-session.html`, `capture-setup.html` | changed: load `session.js` with `?v=` | S10b |
| `app/static/vm-connection.html` | changed: the role-neutral Diagnostics sentence (:7) | S10b |
| `deploy/verify-release.py:40-41` | the three new pages in the tuple | the lead (release owner) |
| `.github/workflows/release-check.yml` | the six new test files on the `node --test` line | the lead |
| `tests/test_login_ui.js`, `test_setup_ui.js` | new | S7 |
| `tests/test_session_ui.js`, `test_account_ui.js` | new | S8 |
| `tests/test_users_ui.js` | new | S9 |
| `tests/test_shell_ui.js`, `test_page_load_ui.js`, `test_status_ui.js`, `test_home_ui.js`, `test_vm_password_ui.js` (loads `management.js`; the five callable entry points and the source pins of the other three), `test_readiness_ui.js` (loads `management.js`; its contexts gain `state.user`; the `banner-vm` case) | changed | S8 |
| `tests/test_operations_ui.js`, `test_network_design_ui.js`, `test_git_progress_ui.js`, `test_load_ui.js`, `test_restore_ui.js`, `test_device_diagnostics_ui.js`, `test_map_tools_ui.js`, `test_device_impairments_ui.js` | changed: one chain test each (section 9.1); the rewritten Diagnostics pins | S10a |
| `tests/test_workspace_ui.js` | new (section 9.1; BUILD.md 2 adds it to S10a's Owns column so the lead puts it on the CI line) | S10a |
| `tests/test_debug_ui.js`, `test_terminal_ui.js`, `test_capture_session_ui.js`, `test_map_editor_ui.js`, `test_lab_builder_ui.js` | changed | S10b |
| `tests/test_audit.py` | new (S1); its label-map case reads the three label maps of `users.js` (`AUDIT_EVENT_LABELS` ↔ `AUDIT_EVENTS`, `AUDIT_OUTCOME_LABELS` ↔ `AUDIT_OUTCOMES`, `AUDIT_DETAIL_LABELS` ↔ `AUDIT_REASONS`) | S1, run by the lead at integration |
| `docs/redesign/tools/fixture_manager.py` | changed: setup with fixture credentials, the signing wrapper, `--signed-out`, `--role`, `POST /__fixture/expire` | S11 |
| `docs/sign-on/tools/check_signon.py`, `docs/sign-on/tools/manager_http.py`, `docs/sign-on/TOOLS.md` | new | S11 |

## 12. Contract requests for `DESIGN.md`

Each item is something this design needs that section 0.3 does not state. The backend designer
decides the mechanism; the UI depends on the behaviour. The Ruling column is the outcome in
`RECONCILIATION.md` (2026-11-01); the text of each request is already amended to it.

| Id | Request | Why | Ruling |
|---|---|---|---|
| C1 | `login.html`, `setup.html` and `users.html` are static files under `app/static`, served at `/login`, `/setup` and `/static/users.html`; the lead adds the first two to `verify-release.py`'s tuple (:40-41) and `set-release.py`. | `?v=` on every asset is checked only for listed pages (`INVENTORY.md` 5). | Not contested. |
| C2 | Without a session, exactly these are reachable: `GET /login`, `GET /setup` (while open), `GET /static/login.css`, `/static/login.js`, `/static/setup.js`, `/static/fabric-mark.svg`, `POST /api/session`, `GET /api/session`, `DELETE /api/session`, `POST /api/setup`, `GET /api/health`. Every other `/static/*` file, including `style.css`, `index.html` and the editor bundle, needs a session. A restricted session reaches the same rows plus `POST /api/session/password` and nothing else (REVIEW R1). | D3 item 1. | **Answered (D):** the exposed pages use `login.css`, not `style.css` (RECONCILIATION 1, 2); the restricted allowlist (REVIEW R1). |
| C3 | One 401 body for an unknown name, a wrong password and a deactivated account; equal throttling and no measurable timing difference (hash a dummy for unknown names). Role refusals answer 403 `{detail:{code:'admin_required',message:'Administrators only.'}}`. | No enumeration (section 10, item 6); the UI shows one sentence. | **D's code, U's sentence:** `admin_required`. |
| C4 | Limits the pages mirror: username lowercase, 2–32 chars `^[a-z0-9][a-z0-9._-]{1,31}$` (the pages set `maxlength="32"`, lowercase before sending and show the manager's 422 message); password 12–128 chars; `retry_after` an integer ≤ 3600. | `maxlength` and the countdown cap. | **D.** |
| C5 | `GET /login` and `GET /setup` with an **unrestricted** session redirect (302) to `/`; `GET /login` **serves** the page to a restricted session (the change view lives there, section 1.8). | A bookmark to the sign-in page must not show it to a signed-in person; a restricted person must reach the change form. | **Accepted** into D 6.3; the restricted case by REVIEW R1. |
| C6 | `POST /api/setup {code,username,password}`: 200 `{user}` and the session cookie; 401 `invalid_code` (throttled like sign-in; the code normalised on both sides before the comparison, REVIEW U13); 404 outside setup or recovery mode; 409 `{code:'exists'}` when the name is an existing record (never overwritten, REVIEW R11); 429 with `retry_after`; 422 `{detail:{code,message}}` for a refused username or password. `GET /setup` after setup → 404. The code is single-use and expires; the installer prints it at its very end; the recovery command prints `https://<address>:<UI_PORT>/setup?recover=1`. | Section 2. | **D** (401 / 404 / 429); no redirect after setup; 409 and the URL by REVIEW R11, U13. |
| C7 | The password policy and its sentences (section 2.3) are the manager's; 422 carries `detail.message` with exactly those sentences so the pages show the manager's own words. The deny-list stays server-side. | One voice; the deny-list is not published. | Not contested. |
| C8 | `GET /api/state` includes `user:{name, role, must_change_password}`. The application reads `name` and `role`; `must_change_password` is never true on a session that reaches `/api/state` (REVIEW R1). | One request; the role is live on the poll (section 4.4). | **Accepted, with D's field name.** The `users` table itself never reaches `/api/state`. |
| C9 | A WebSocket refused for a missing or ended session closes with code 1008 and reason `signed_out`; an ended session's open terminal, console and capture sockets close within 5 s (the handlers check the session on every idle tick); ending a session (sign-out, deactivation) is the cause. | The terminal and viewer sentences (section 3.5). | **Accepted.** |
| C10 | `PATCH /api/users/{name}` `{role}` or `{disabled}`; 409 `{code:'last_admin'}` when it would remove the last active admin; 409 `{code:'self_change'}` when an admin deactivates or demotes themselves, and from `POST /api/users/{own name}/password` (REVIEW R12); deactivation ends the person's sessions. `GET /api/users` rows `{name, role, disabled, must_change_password, created, created_by, password_changed, last_signin, sessions}`. The `self_change` sentences are the manager's per request (`DESIGN.md` 7.4: *You cannot deactivate your own account. Sign out instead.* for `PATCH` with `disabled: true`, *You cannot change your own role. Ask another administrator.* for `PATCH` with `role`, *You cannot remove your own account. Ask another administrator.* for `DELETE`, *Use Manager ▾ › Change password… for your own account.* for the password route); the page's three disabled captions are its own and are not derived from them (section 5.4). | Section 5.4. | **D:** `disabled`, `self_change`; `last_signin` accepted into the record; the own-password 409 by REVIEW R12; the sentences as DESIGN 7.4 gives them. |
| C11 | `must_change_password` on a user: set by `POST /api/users {name, role, password}` (a new record starts with it true) and by `POST /api/users/{name}/password` (which ends every session of that user); cleared by `POST /api/session/password {current,password}`. A session of such a user is **restricted** (section 0.2): a page request answers `302 /login?change=1&next=<path+search>`, any other request 403 `{detail:{code:'password_change_required',message}}`, a socket closes 1008 `password_change_required`; only the exempt rows, `GET`/`DELETE /api/session` and `POST /api/session/password` answer it (REVIEW R1). A password change always ends the person's other sessions; there is no `everywhere` option. A wrong current password answers 401 `invalid_credentials` (not `signed_out`). | Sections 1.8, 5.4, 6.2, 6.3. | **D.** No checkbox; the restricted session by REVIEW R1. |
| C12 | `GET /api/audit?limit&offset&event&actor&outcome&since&address` → `{entries,total}`, newest first, `limit` ≤ 500, merged by time from `audit.jsonl` and `audit-failures.jsonl` (REVIEW R8); `event` accepts a comma-separated list of codes (section 5.6's *Sign-in attempt* filter); entry fields `{time,actor,event,outcome,source,target,detail}` (`DESIGN.md` 10.1: `target` on every entry, the person on `user.*` rows, the route template on `forbidden` rows, empty elsewhere; section 5.6 appends it for those two); `actor` is `'-'` for a failed or throttled sign-in and a failed setup whose submitted name equals no record's name (REVIEW R2); events, outcomes and details are the codes of `DESIGN.md` 10.2, which section 5.6 maps; failures from one source are summed per minute with `detail: count=<n>`; `detail` is controlled metadata only (never a password or a user-agent string longer than 200 chars). | Section 5.6; the logs invariant (`CLAUDE.md`). | **D's shape plus the `address` filter;** the field is `source`; the one vocabulary by REVIEW R3; the comma list and `target` are this document's asks. |
| C13 | Amendment of DESIGN-SPEC-ADDENDUM J1: `session.js` is a second shared script (after `status.js`, before `shell.js`) with no top-level side effect whose one `location` access is inside `sessionGo()`; the standalone pages load it too. | Section 3.2. | **Accepted;** recorded as amendment M of `docs/redesign/DESIGN-SPEC-ADDENDUM.md` at the release step. |
| C14 | `DELETE /api/session` always answers 200 and clears the cookies (also when the session is already gone), including `clab_capture_owner` with `Path=/api/capture` (REVIEW R10); sessions have an idle timeout the UI does not need to know (open question Q1) and an absolute lifetime; a session renews only on acts of the person, never on a `GET /api/...` (REVIEW R9), so the application's polls keep nothing alive. | Section 6.4 item 3; section 3.1. | **Accepted.** |
| C15 | A page request (`GET` or `HEAD`, `Accept` includes `text/html`) without a session redirects with 302 to `/login?next=<path+search>`; the manager builds `next` from the request path and query only (the hash never reaches it). Every other request answers the 401 JSON. `/student-guide` and `/api/labs/<id>/design/export` are page requests. | Section 0.3 item 4 made precise; section 3.1; section 10 item 1. | **Accepted** as written: decided by `Accept`. |
| C16 | The capture viewer's HTTP routes and websockify require the manager session *and* the owner cookie; a manager session that **expires** does not end the capture container; a **sign-out** ends this browser's capture sessions through `POST /api/capture/sessions/end-all` before `DELETE /api/session` (REVIEW R10). | Section 10, item 2; section 6.4. | **Accepted** as written; the sign-out step by REVIEW R10. |
| C17 | Every 4xx body the sign-on code sends (the session, setup, users, audit and password routes, and the gate's own 401, 403 and 503) carries `detail.message`, one sentence per code and reason from section 8; a 422 joins the sentences of its reasons. | The pages show the manager's words; a page script without the 401 hook still shows a sentence (REVIEW U11). | **Accepted** (REVIEW U11; DESIGN 17 records it). |
| C18 | No fixture code in `app/`: the `/__fixture/expire` hook is a route of the fixture wrapper in `docs/redesign/tools/fixture_manager.py` on the app it wraps, calling `app.state.sessions.end_user(name, reason)`. | Section 9.2. | **Accepted** (REVIEW R15, R21). |

## 13. Open questions for the lead

| Id | Question | Ruling (RECONCILIATION 3) |
|---|---|---|
| Q1 | Should the application warn before an idle timeout (a *Still there?* banner), which needs `expires` in `GET /api/session` and a timer in `shell.js`? | **No** idle pre-warning in the first version; the banner-in-dialog path (section 3.3) makes an expiry mid-work recoverable. |
| Q2 | A trimmed `login.css` instead of the full `style.css` on the exposed page? | **Answered:** `login.css`, self-contained (section 1.1, 1.3); `style.css` is not loaded by `login.html` or `setup.html`. |
| Q3 | Should the Users page offer Delete at all? | **No.** The route `DELETE /api/users/{name}` stays for the API; the UI reads "deactivated" (section 5.4). |
| Q4 | Account chip in the top bar (section 4.1 item 1): keep, or menu only? | **Keep,** hidden under 900 px. |
| Q5 | The fixture manager needs a seeded admin and operator, a printed setup code and a `/__fixture/expire` hook for the Playwright checks (section 9.2). Who owns that change to `docs/redesign/tools/fixture_manager.py`? | **The QA worker** (BUILD.md S11). Superseded in one point by REVIEW R15 and R21: the hook is **not** a backend route behind `FIXTURE_DATA`; it is a route of the fixture's own ASGI wrapper, which also signs requests in by default (`--signed-out`, `--role operator` switch it), so `app/` holds no fixture code and the other campaigns' checks run unchanged. |
| Q6 | `account.js` as a separate page script (section 6.2) or inside `preferences.js`? | **Separate script.** |
| Q7 | Does the Diagnostics page (`debug.html`) stay reachable for an Operator? | **Admin-only.** `GET /api/debug` is admin-only; the Diagnostics menu item is hidden for operators like the Users item (section 4.4); `debug.html` opened directly shows *Administrators only.* on the 403. |
| Q8 | The `.eyebrow` class is "kept for the diagnostics page only" (style.css:190). `users.html` reuses it for *Manager*. Accept, or drop the eyebrow on the new page? | **Reuse;** the comment at style.css:190 is updated to name both pages. |
