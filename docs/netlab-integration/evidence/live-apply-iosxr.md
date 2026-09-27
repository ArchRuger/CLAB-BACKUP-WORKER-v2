# Live proof of *Apply to devices* on IOS XR (`restore-square`, 2026-09-27)

Same harness as `live-apply-ceos.md`. Target: `clab-restore-square-xrv9k` (XRv9k 24.3.1) at containerlab's startup
configuration (data ports `shutdown`, management in VRF `clab-mgmt`); the other three routers carried the design.

Facts found while bringing the driver up (`scratchpad/xr_probe*.py`, nothing committed):

- The first review stalled 30 s and failed "did not return to its prompt in time": the driver reached the CLI
  twice on one channel (`capture_shell` includes `reach_cli`, which waits for a prompt that never comes again).
  A raw channel proved the device answers `show configuration sessions detail` in 0.2 s right after an aborted
  100-line plain session. Fixed: `before` is read with a plain `show running-config` on the reached shell.
- `show configuration merge` never prints `no shutdown` or `no management enable`; the port's `shutdown` simply
  disappears. Two rules followed: a vanishing `shutdown` under an interface the design configures is an
  *expected* change (the review had reported the two data ports as conflicts), and a typed negation in the
  desired set is verified as the absence of its positive form (the first apply had reported four "missing"
  statements after a correct commit).
- `commit confirmed minutes N` on the exclusive session is armed evidence only together with
  `do show configuration sessions detail` on the same session showing `Client: commit-confirm`; the fresh
  connection's `pending()` recognises the trial as ours by the peer address of the held connection.

| Step | Plan | Review (added / removed / stale / conflicts / expected / removals) | Job | Device read-back |
|---|---|---|---|---|
| 1 review | OSPF + BGP | 13 / 2 / 0 / **2** (the two `shutdown` lines) / 0 / 0 before the rule; 82 / 0 / 0 / 0 / 2 / 0 after it | — | no session row left after the aborted review |
| 2 apply | same, `confirm_minutes 3` | 82 / 0 / 0 / 0 / 2 / 0 | the session was kept open after `commit confirmed minutes 3`; a fresh connection reached the CLI and the held session's `commit` answered "Confirming commit for trial session"; `verify_mismatch` with the four negations reported missing (defect, fixed as above; the configuration itself was complete) | `router ospf 1` with the three interfaces, `router bgp 65000` with the iBGP peers, OSPF neighbours FULL to vjunos-switch and ceos within 25 s, no session row left, commit persistent |
| 3 re-apply | same | 0 / 0 / 0 / 0 / 0 / 0, `no_op` | `succeeded` "Every selected device already matched the plan; nothing was changed." | untouched |
| 4 BGP AS identity change | `nodes.xrv9k.bgp.as = 65100` (netlab then runs no OSPF on a router whose links are all external) | 33 / 71 / 71 / 0 / 0 / 5 (`no description …` on both ports, `no router bgp 65000`, `no router ospf 1`, `no router ospfv3 1`) | `failed`, "Configuration was not changed: The node did not accept the timed commit of the design; nothing was applied." — IOS XR refuses to remove `router bgp 65000` and create `router bgp 65100` in one commit; the exclusive session was aborted, nothing changed. The driver now adds the device's own `!!%` reasons from `show configuration failed` to that message; probed again through the fixed driver (`scratchpad/xr_as_probe.py`, `no router bgp 65000` + `router bgp 65100` in one exclusive session, `commit confirmed minutes 2`): refused in 4 s with "The node said: BGP is still in process of unconfiguration for instance default", nothing armed, no session row, `router bgp 65000` still running. The way through is two applies (drop BGP, then add it with the new AS) | unchanged, no session row |
| 5 drop both modules | `modules: []` | 0 / 69 / 69 / 0 / 0 / 3 (`no router bgp 65000`, `no router ospf 1`, `no router ospfv3 1`) | `succeeded`, `verified` (with the negation rule: nothing "missing") | only the interfaces' addressing and `domain lookup disable` of the initial module remain |

