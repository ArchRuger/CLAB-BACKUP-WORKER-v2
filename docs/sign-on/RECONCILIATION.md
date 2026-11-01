# Reconciliation: the lead's rulings where the three designs differ

`DESIGN.md` (accounts, sessions, gate), `UI.md` (the pages) and `EXPOSURE.md` (TLS, installer, health
check) were written in parallel. This file is the lead's decision on every point where they disagree
or where one asked the other a question. A ruling here binds all three documents; the build follows
the ruling, and the documents are amended after the design review so that one source remains.

Terms: **D** = `DESIGN.md`, **U** = `UI.md` (its contract requests are U-C1…C16, its questions
U-Q1…Q8), **E** = `EXPOSURE.md`, **Dq** = D's open questions to the lead.

## 1. The contract between the pages and the manager

| Point | D says | U asks | Ruling |
|---|---|---|---|
| Assets of the sign-in page | `login.css`, `login.js`, `setup.js`, `fabric-mark.svg`; `style.css` behind the gate (D 6.3) | Full `style.css` (U-C2, U-Q2) | **D.** `login.css` is a small self-contained sheet that copies the tokens it needs from `style.css` (section 2 of this file). `style.css` names every feature of the product; the sign-in page is the one surface a scanner sees. |
| Role refusal code | `admin_required` (D 7) | `forbidden` with "Administrators only." (U-C3) | **D's code, U's sentence:** `403 {detail:{code:'admin_required', message:'Administrators only.'}}`. |
| Username rule | lowercase, 2–32, `^[a-z0-9][a-z0-9._-]{1,31}$`; the form lowercases (D 3.1) | 2–64, mixed case (U-C4) | **D.** The pages set `maxlength="32"`, lowercase the value before sending, and show the rule from the manager's 422 message. |
| `POST /api/setup` codes | 401 `invalid_code`; 404 outside setup/recovery mode; 429 (D 9) | 403 wrong code; 409 when an admin exists (U-C6) | **D.** `GET /setup` after setup is 404, not a redirect: a 404 says less than a page that exists. |
| `GET /login` with a valid session | not stated | 302 to `/` (U-C5) | **Accepted into D 6.3:** `GET /login` and `GET /setup` with a live session answer 302 `/`. |
| The user on the poll | not in `/api/state` (D 3.4) | `user:{name,role,must_change}` in `GET /api/state` (U-C8) | **Accepted, with D's field name:** `/api/state` gains `user:{name, role, must_change_password}` for the session's own user. The 4 s poll then carries a role change without a second request. The `users` table itself still never reaches `/api/state`. |
| Socket close on session end | 1008 before accept (D 6.4) | reason `signed_out`; an ended session's open sockets close within 5 s (U-C9) | **Accepted:** the close reason is `signed_out`; the terminal, console and capture socket handlers check the session on every idle tick (at most 5 s) and close 1008 when it is gone. D 11 gains the rule. |
| `PATCH /api/users/{name}` body | `{role}` or `{disabled}` (D 7.3) | `{role}` or `{active}`; code `self` (U-C10) | **D:** `disabled`, `self_change`. |
| User rows | `public_user`: `name, role, disabled, must_change_password, created, created_by, password_changed, sessions` (D 3.4) | adds `last_signin` (U-C10) | **Accepted:** the record gains `last_signin` (ISO 8601 UTC, updated on every successful sign-in, `null` before the first) and `public_user` copies it. An admin of an exposed system needs to see it without opening the audit log. |
| Own password change | other sessions always end; `{current, password}` (D 5.5, 17) | `everywhere` checkbox (U-C11) | **D.** No checkbox: a password change always ends the other sessions. U 6.2 drops the checkbox and says so in the dialog's help line. |
| Audit query | `?limit&offset&event&actor&outcome&since` → `{entries,total}` (D 10) | plus `address`; rows `{time,actor,event,outcome,address,detail}` (U-C12) | **D's shape plus the `address` filter**; the row field is `source`, as D 10.1 names it. `limit` ≤ 500. |
| `session.js` and addendum J1 | — | amend J1 (U-C13) | **Accepted.** Recorded as amendment M of `docs/redesign/DESIGN-SPEC-ADDENDUM.md` at the release step: `session.js` is a second shared script (after `status.js`, before `shell.js`) with no top-level side effect; its one `location` access is inside `sessionGo()`. |
| `DELETE /api/session` | clears both cookies (D 17) | always clears, also when already gone (U-C14) | **Accepted:** always 200, cookies cleared, no 401. |
| Page vs API without a session | GET/HEAD on a non-`/api/` path → 302; everything else 401 JSON (D 6.4) | by `Accept: text/html`, including `/student-guide` and the design export (U-C15) | **By `Accept`:** a `GET` or `HEAD` whose `Accept` includes `text/html` answers 302 `/login?next=<path>`; every other request answers 401 JSON (or 1008). This covers `window.open('/api/labs/<id>/design/export')`. `next` is the path and query only; the hash never reaches the server. |
| Capture routes | — | manager session **and** owner cookie; ending the manager session does not end the capture container (U-C16) | **Accepted** as written. |
| Health route | `GET /api/health` → `{ready:true}` (D 6.7) | — | **Kept**, pending E's view of the health checker (section 3). |

## 2. The exposed page

1. `login.css` holds: the colour, spacing, radius and font tokens copied verbatim from `style.css`
   `:root` (style.css:55-120), the dark-scheme overrides for those tokens, the rules for `body`, the
   card, the form fields, the primary button, the error and help lines, the banner and the brand mark.
   Nothing else. A test asserts that `login.css` names no selector from the application (`#save-chip`,
   `.topbar`, `.panel`, …).
2. The page `<title>` is `Sign in` (Dq 3). The brand mark and the product name appear on the page
   itself, because a student must recognise where they are; the title is what a scanner indexes.
3. `setup.html` loads `login.css` and `setup.js` only.

## 3. Questions answered

| Id | Question | Ruling |
|---|---|---|
| U-Q1 | Idle-timeout pre-warning | No, for the first version. |
| U-Q3 | Delete on the Users page | No. The route `DELETE /api/users/{name}` stays for the API and the audit reads "deactivated" in the UI. |
| U-Q4 | Account chip in the top bar | Keep, hidden under 900 px. |
| U-Q5 | Who changes `fixture_manager.py` | The QA worker, in the verification phase, against the backend's `/__fixture/expire` hook that the backend builder adds **only when `FIXTURE_DATA` is set** (never in a production path). |
| U-Q6 | `account.js` | Separate script. |
| U-Q7 | Diagnostics for operators | Admin-only: D 7 makes `GET /api/debug` admin-only, so the page would be empty. The Diagnostics menu item is hidden for operators like the Users item; `debug.html` opened directly shows the "Administrators only." sentence on the 403. |
| U-Q8 | `.eyebrow` reuse | Reuse; update the comment at style.css:190 to name both pages. |
| Dq 1 | scrypt timing measured on Python 3.13, not the image's 3.12 | The backend builder re-measures inside `python:3.12-slim` in CI (a test asserts < 500 ms with `maxmem` set) and records the figure in VALIDATION.md. |
| Dq 2 | `HostCheckTests` with explicit `Host` headers and the cookie jar | The test fixture signs in and then passes `cookies=` explicitly in those tests. |
| Dq 4 | `git_binding` fields visible to operators | Kept visible (D 18). A reviewer may contest it. |
| Dq 5 | Unify the three security-header sets | Yes: one function `security_headers(response)` in a new `app/headers.py` used by `HostCheck`, the gate and the guard. In scope for the build; it removes the gap that the guard's early returns carry no headers (INVENTORY 6.1). |
| Dq 6 | `GET /api/logs` admin-only now that it names actors | Stays operator (D2 shared labs). The actor field names users, not secrets. |

## 4. Interfaces E must answer (filled in when `EXPOSURE.md` lands)

1. The scheme rule `origin.scheme(scope)`: `https` when the ASGI scheme is `https`/`wss` or `UI_TLS=1`;
   `UI_TLS` in both compose files.
2. The health checker and the installer move their version and capture questions to `docker exec`;
   `GET /api/health` answers `{ready:true}` only.
3. The setup code file `/data/setup-code` is read and printed by the installer and reported by the
   health check while it exists.
4. `deploy/manager-recover-admin.sh` exists, runs `docker exec … python -m app.recover`, is in the CI
   `bash -n` loop.
5. No secret in the container environment (D ruling 13); a TLS key path is fine.
