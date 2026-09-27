# Junos transaction facts (vJunos-switch 23.2R1.14, `restore-square`, 2026-09-27 00:45 UTC)

Probed with a paramiko session through the application's own `restore_junos.JunosShell` helpers
(`reach_cli`, `configure private`, `load … terminal` + Ctrl-D, `show | compare`, `show | display set`,
`delete`, `rollback 0`, `exit`); nothing was committed (`show system commit` entry 0 unchanged: the
containerlab startup commit by root).

- `configure private` then `load merge terminal` with netlab's OSPF fragment shape **works**; the
  `routing-options { router-id 10.255.0.99 }` statement without a semicolon (netlab renders it so) loads
  (`load complete`).
- Inside the candidate `show | display set` renders it in set form, presence lines included:
  `set protocols ospf area 0.0.0.0 interface lo0.0`, `set protocols ospf area 0.0.0.0 interface ge-0/0/0.0
  interface-type p2p`, `set routing-options router-id 10.255.0.99`, `set policy-options policy-statement
  probe-final term one then next policy`, `… term default then reject`.
- `delete protocols ospf area 0.0.0.0 interface lo0.0` removes the presence line. `delete protocols ospf
  area 0.0.0.0 interface ge-0/0/0.0 interface-type p2p` removes the leaf and **leaves the presence line**
  `set protocols ospf area 0.0.0.0 interface ge-0/0/0.0` behind (the interface stays in OSPF): the reviewer's
  M2 case, which the created-ancestor rule of `design_ownership.plan_removals` handles by deleting at the
  ancestor.
- `load override terminal` **works in `configure private`** with a fragment that lacks
  `root-authentication` (no commit is attempted): `show | display set` then renders the candidate alone
  (`set system host-name probe`, the OSPF lines), so the device itself renders the *desired* set;
  `show | compare | count` reported 83 lines; `rollback 0` cleared everything and `show | compare` was empty.
- The first attempt through `docs/multi-platform-restore/tools/nodecli.py --ctrl-d-after` failed: that tool
  sends the fragment as separate CLI commands ("unknown command") because it does not wait for the
  `[Type ^D at a new line to end input]` prompt; the driver's 1.5 s pause after `load … terminal` is needed.
