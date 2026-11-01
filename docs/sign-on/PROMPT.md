# Sign-on and internet-exposure hardening: the owner's task

The owner's words and decisions, verbatim where they were given, recorded on 2026-11-01 before any
design was written. This file is the source the design answers to; the design (`DESIGN.md`) may
differ from its letter only in a section that says so and why.

## The request

> I need a cloud session / environment to complete work on my project
> https://github.com/ArchRuger/CLAB-BACKUP-WORKER-v2
>
> This will be for work the doesn't involve actually starting any nodes. Such as cosmetic UI/UX changes.
>
> I specifically want to run ultra code, as many agents as i can get to implement user sign on and
> security to start shipping this as a real product, not just a personal project

## The decisions, asked by the lead and answered by the owner

| ID | Question | Answer |
|---|---|---|
| D1 | Where do user accounts come from for the first shippable version? | **Local accounts first.** Usernames and hashed passwords stored in the manager's encrypted state; an admin creates users. OIDC/SSO is designed as a later pluggable provider, not built now. |
| D2 | What roles must the first version enforce? | **Admin + Operator, shared labs.** Two roles; every signed-in user sees every lab (today's behaviour, behind a login). Admins alone manage users, the VM connection and the manager settings. |
| D3 | What does "security" mean beyond sign-on itself? | In the owner's words: *"I am most worried about the vm being exposed to the public internet and being auto scanned by attackers. I don't want this to be compromised."* |

## What D3 settles for the design

D3 is the threat model. It ranks every other choice:

1. The manager will sit on a VM whose address is reachable from the public Internet and will be
   found by automated scanners within hours. Nothing may be reachable without a session: no page,
   no `/api/` route, no WebSocket, no static asset that reveals the product beyond the sign-in page
   itself.
2. The sign-in surface is the one thing an attacker gets to talk to. It must survive credential
   stuffing and brute force (slow password hashing, throttling, no username enumeration, no default
   account, no setup page left open).
3. Passwords and session cookies must not travel in clear text. Plain HTTP on 0.0.0.0:8081 is not
   a shippable default for an exposed VM; TLS is part of this work, not a note in a guide.
4. The VM itself has other doors (the SSH service, Docker, the lab nodes' published ports). The
   manager cannot close them, but the installer and the health check can set safe defaults and warn
   loudly when a door is open.
5. Everything that happens at the sign-in surface and to accounts is recorded (an audit log), because
   an operator of an exposed system needs to see the attempts.

## Constraints that stay

- No node is started in this campaign: validation is static, unit, fixture/browser and CI. A live
  VM pass is the owner's, afterwards.
- The repository's invariants in `CLAUDE.md` bind, except the one this campaign deliberately
  replaces: *"There is no login"*. Its replacement is written in `DESIGN.md` and in `CLAUDE.md`
  itself at the release step.
- Plain-script UI (no framework, no build step, no CDN, no inline styles on `/`), `esc()` on every
  interpolation, CSP `script-src 'self'`.
- The manager stays non-root, without a Docker socket; the VM boundary (gateway, helpers, trusted
  roots) is unchanged by sign-on.
