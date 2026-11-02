# Accounts and sign-in

Everything in the manager needs a sign-in. This guide is for the person who creates the first
administrator, for administrators who add people and for anyone who wants to know what a session is,
why a sign-in is sometimes delayed, and what the manager writes down about who did what. The words
on the pages are quoted as they appear.

The manager serves HTTPS itself (`https://VM_ADDRESS:8443` by default). Plain HTTP on port 8081 only
redirects there. The certificate, the browser warning and the ports are described in the
[installation guide](INSTALL.md); [Opening the manager by a name](INSTALL.md#opening-the-manager-by-a-name)
lists how a DNS name becomes an address the manager accepts.

## Accounts and roles

An account has a name, a role and a password. A name is 2 to 32 characters: lowercase letters, digits,
dot, dash and underscore, starting with a letter or digit. There are two roles.

| | Operator | Administrator |
|---|---|---|
| Labs: deploy, stop, redeploy, destroy, edit the map and the topology | yes | yes |
| Devices: terminals, serial console, backups, downloads, Load | yes | yes |
| Save, Upload, checkpoints, Wireshark capture, network design | yes | yes |
| See and change their own password, sign out | yes | yes |
| **VM connection…** (Manager ▾) | no: *Ask an administrator to set up the VM connection.* | yes |
| **Manager settings…**, including *Start fresh* | no: the item is disabled, *Administrators only* | yes |
| **Diagnostics** page | no: the menu item is hidden; the routes answer *Administrators only.* | yes |
| **People and sign-ins…** (add, change role, reset password, deactivate, read the audit) | no | yes |

Every signed-in person sees and can run every lab: the manager has no per-lab ownership. The roles
decide who may change the manager itself. Where a message to a student would say *see Diagnostics*, an
operator reads *ask an administrator to check Diagnostics*. The accounts live in the manager's
encrypted state, not on the VM; they are unrelated to the `clab-discovery` account, to GitHub and to
a device login.

## The first administrator

A manager with no accounts is in setup mode: the only thing it answers is the setup page, and every other
address redirects there. This is the state after a new installation and after an upgrade from a release
that had no accounts.

1. Open `https://VM_ADDRESS:8443`. The page is *Create the first administrator* and says *Enter the
   setup code the installer printed, then choose the account you will sign in with.*
2. The setup code is a 24-character code in four groups (`xxxxxx-xxxxxx-xxxxxx-xxxxxx`). The installer prints
   it in its last lines, after the steps that restart the manager. To read it again, on the VM:

   ```bash
   sudo cat /srv/containerlab-node-manager/data/setup-code
   ```

   The file has two lines, `mode=setup` and `code=…`, and is readable only by the manager's account (and root, hence `sudo`). The manager never
   writes the code to its log, only the command above. A restart of the manager in setup mode makes a new
   code, so use the latest one. Capitals, missing dashes and spaces between groups are forgiven.
3. Enter the code, a username and a password twice, and click **Create account and sign in**. This
   account is an administrator, is signed in at once and is not asked to change its password.

When the first administrator exists the code file is deleted, the setup page answers *not found* and the
only way to open it again is the recovery command below. A wrong code answers *That setup code is not
right. On the VM, run: sudo cat /srv/containerlab-node-manager/data/setup-code*. If the page says
*Setup is closed. Sign in, or ask the VM administrator to run the recovery command.*, an administrator
already exists.

## Signing in

The sign-in page is *Sign in*, with *Use the account your administrator gave you.* Enter the username and
the password and click **Sign in**. **Show** reveals the password you are typing. A wrong name, a wrong
password and a deactivated account all answer the same sentence, *Wrong username or password.*, so the page
does not tell a stranger which names exist. *Forgot your password? Ask an administrator to reset it.*

You land where you were going: a bookmark such as a lab address, with its tab and device, is kept through
the sign-in page. If the sign-in page is ever served over plain HTTP it warns that the connection is not
encrypted: use the HTTPS address.

### The required password change

When an administrator creates your account or resets your password, the password you were given is
temporary. The sign-in page then shows *Choose your own password* with *The password you signed in with was
set by an administrator. Choose your own before you continue.* Until you click **Change password and
continue** the session can do nothing else; **Sign out** is also there. The change ends your other
sessions.

### Password rules

- At least 12 and at most 128 characters. Any characters count; length matters more than symbols, and
  there are no required character classes.
- Not your username, and the username is not allowed inside it.
- Not one of a short built-in list of well-known passwords (*That password is too common. Choose another.*). The list holds only entries shorter than the 12-character minimum, so the length rule refuses them first; this message appears together with *Use at least 12 characters.*
- No expiry: passwords are never rotated on a schedule. They change when you choose to, or after an
  administrator resets them.

Passwords are stored as `scrypt` hashes in the manager's encrypted state and are never shown again, not
even to an administrator.

### Changing your own password

**Manager ▾ › Change password…** asks for the current password and the new one twice. *Your other browsers
and devices are signed out when the password changes.* The current session stays signed in. An
administrator cannot reset their own password from the People page (*Use Manager ▾ › Change password… for
your own account.*); another administrator can reset it.

## Sessions

- A session is created at sign-in and lives only in the manager's memory, in the cookie `clab_session`
  (not readable by scripts, sent only to this site, and only over HTTPS). A browser holds one cookie; a
  person can have up to 32 sessions, and the manager keeps at most 512 in all.
- It ends after **12 hours without an act of the person**, and in any case **7 days after sign-in**.
- What counts as an act: a click that changes something, opening a page, and typing in a terminal, a serial
  console or a Wireshark viewer. What does not: the page refreshing its own status every few seconds. An
  open tab that nobody touches signs out after 12 hours.
- **A restart of the manager signs everyone out**, because sessions are not written to disk: an upgrade, a
  recreate and a crash each cost one sign-in. Labs, saves and accounts are not affected. The page you were on
  sends you to the sign-in page and brings you back to the same address afterwards.
- **Sign out** (Manager ▾) ends this session. It also closes this browser's Wireshark sessions (*Signing out
  also closes this browser's Wireshark sessions.*). An expired session closes none: signing in again in the
  same browser finds them.
- A session ends at once when its account is deactivated, deleted, has its password reset by an
  administrator, or has its password changed from another session. Its open terminals and consoles close; a
  change you make yourself keeps this session and its terminals open.
- A terminal's one-time ticket (30 seconds, single use) is tied to the session that asked for it, so a ticket
  copied to another browser or another account is refused.
- Two people sharing one browser do not share Wireshark sessions: the capture owner is derived from the
  browser and from the signed-in name.

## Sign-in delays (throttling)

A wrong password is allowed a few times; then the manager makes the next attempts wait. You meet it as
*Too many sign-in attempts. Try again in N s.* with a countdown, followed by *You can sign in again.* It
is never a lock-out: the delay starts at 30 seconds, doubles with each further failure and stops at
15 minutes, and a correct sign-in is accepted as soon as the delay is over. In ordinary use:

- Five wrong passwords in a row for one name from one address start the delay for that name from that address.
- A single address that fails 100 times in 15 minutes, whatever the names, is delayed as a whole.
- Someone guessing at a name from many addresses is slowed down on that name, but a person signing in from a
  network they have signed in from before (the same /24 for IPv4, the same /64 for IPv6) is not held up by
  it. A person on a new network, while their name is under attack, may wait up to 30 seconds per try.
- A classroom behind one address is not locked out by one student's typos: the count is per name and
  address, and one success clears only that student's own count.
- Delays are kept in memory. Restarting the manager clears them, and the recovery command does not use them.
- Checking a password is expensive on purpose, and only a few checks run at once; if the manager is busy it
  answers the same *Too many sign-in attempts* sentence with a wait of a couple of seconds.

## People and sign-ins (administrators)

**Manager ▾ › People and sign-ins…** is the administrators' page. It has two parts.

**People** lists every account with its role, *Active* or *Inactive*, and the time of its last sign-in
(*Never* before the first). **Add a person…** takes a name, a role (*Operator* is the default) and a
temporary password twice, and says *They must choose a new password the first time they sign in.* On
each row:

- **Change role…** switches *Operator* and *Administrator*.
- **Reset password…** sets a temporary password. *Tell the person this password yourself; the manager does not
  show it again.* Their sessions end and they must choose their own at the next sign-in.
- **Deactivate** ends the person's sessions and stops them signing in (*Their open sessions end now. Their
  labs stay.*); **Reactivate** lets them sign in again with their current password.

Three rules protect the manager from a slip: *The last administrator stays.* (the last active administrator
cannot be deactivated or made an operator); you cannot deactivate your own account (*Sign out instead.*) or
change your own role (*Ask another administrator.*); and you reset your own password from the Manager menu.
The page has no *Delete* button.

**Sign-ins and changes** is the audit, described next.

*Start fresh* (Manager settings) keeps the accounts and the audit files: it clears labs, jobs and backups,
never the people, and never returns the manager to first-run setup.

## The audit

The manager records security events in two files in its data folder
(`/srv/containerlab-node-manager/data/` on the VM), both readable by the manager's user only and each
rotated at 5 MiB with three older copies:

- `audit.jsonl`: first administrator created, recovery code created or expired, sign-ins, sign-outs, session
  expiry and why (idle or the 7-day limit), sessions ended by the manager (deactivated, deleted, password
  reset or changed, too many sessions), password changes, accounts added, role changes, deactivations and
  reactivations, password resets, *Start fresh* (*Manager reset*) and every refusal of an
  administrators-only page to an operator.
- `audit-failures.jsonl`: failed or throttled sign-ins and failed setup attempts, **summed per source address
  and minute** (for example *3 attempts in one minute*), so a flood of guesses cannot push the security record
  out of the first file.

Both files survive *Start fresh* and are shown only to administrators, on the People page under *Sign-ins and
changes*: filter by time (last hour, 24 hours, 7 days, all), person, event, outcome (*Succeeded*, *Failed*,
*Throttled*) and address. Times are UTC. A row shows who, what, the result, the source address and a short
reason (for example *wrong password*, *this name from an unfamiliar source*, *idle*).

What the audit never holds: a password (right or wrong), a setup or recovery code, a session id or cookie, a
password hash, or the body of a sign-in. A failed attempt shows the typed name only when it matches an
existing account; otherwise the person column is a dash, so a password typed into the username box never
reaches a file or a screen. Ordinary actions on labs (a deploy, a save, a restore) go to the manager's action
log with the signed-in name as `actor`, not to the audit files; administrators and operators read that log
through `GET /api/logs`, and work done in the background writes `-` as the actor.

## Recovering a lost administrator password

If the only administrator cannot sign in, or no administrator remembers a password, someone with `sudo` on
the VM runs, from any directory:

```bash
sudo bash "$HOME/projects/clab-manager/deploy/manager-recover-admin.sh"
```

It prints `Recovery code: …`, says the code is valid for 15 minutes and prints the address
`https://VM_ADDRESS:8443/setup?recover=1`. Open it in a browser that is not signed in to the manager (sign out first, or use a private window): a signed-in browser is sent to Home. Enter the code: the page is *Recovery: create one
new administrator* (*Existing accounts are not changed.*). Choose a name no account uses, a password and
sign in. The recovery changes no account and deletes none: use the new administrator to reset or deactivate
the old one on the People page. The code expires after 15 minutes; an unused one is removed at the next
visit to the setup page. If the manager is still in first-run setup the script prints *The manager is in
setup mode: use the setup code in …/setup-code.* and exits: use that code.

The command exists only on the VM: nothing on the network can start it. It needs the manager running
(otherwise it prints how to start it) and records the request in `audit.jsonl`.

## What to read next

- [Installation](INSTALL.md#finish-in-the-browser) for the browser step after an install, and
  [Opening the manager by a name](INSTALL.md#opening-the-manager-by-a-name).
- [Health report](HEALTH-CHECK.md) for the installation checks, including whether setup is complete.
- [Diagnostics](DEBUG-PANEL.md) for the administrators' page that checks the VM connection.
- [Architecture](ARCHITECTURE.md) for the modules behind the gate, the sessions and the redirect.
