# Live proof of *Apply to devices* on Junos (`restore-square`, 2026-09-27)

Same harness as `live-apply-ceos.md` (scratch `create_app`, real backups, independent read-backs with
`nodecli.py`). Targets: `clab-restore-square-vjunos-switch` (vJunos-switch 23.2R1.14) and
`clab-restore-square-cjunosevolved` (cJunosEvolved 26.2R1.7-EVO, the `vptx` stand-in), both at containerlab's
startup configuration; the cEOS node already carried the design, so the sessions came up (see below).

Facts probed first (`scratchpad/junos_forms_probe.py`, nothing committed): the operational
`show configuration | display set | no-more` and the configuration-mode `show | display set` render the same
statement set on both images (13 and 9 statements at the startup configuration), so the driver compares
`before` (taken at the operational prompt) with the candidate inside `configure exclusive` and refuses on any
difference.

| Step | Plan | Review per device (added / removed / stale / conflicts / removals / kept) | Job | Device read-back |
|---|---|---|---|---|
| 1 review | OSPF + BGP, dual stack | vjunos-switch 84 / 0 / 0 / 0 / 0 / 0; cjunosevolved 74 / 0 / 0 / 0 / 0 / 0; protected: `host-name`, `static-host-mapping`, the fragments' `delete:` tags (ospf, ospf3, bgp, the netlab policy statements and route-filter lists) | — | no commit (`show system commit` entry 0 unchanged) |
| 2 apply, both devices at once | same, `confirm_minutes 3` | as above | `succeeded`; both `verified`, saved (a Junos commit is persistent); pre and post backups succeeded for both; cjunosevolved staged, armed, confirmed and read back in 20 s, vJunos-switch in 55 s (its `commit check`/`commit confirmed` are slow) | `show system commit` entry 0: `commit confirmed, rollback in 3mins` with the comment `clabdsg-…` and **no** `rollback pending` (confirmed); `protocols bgp` with the three iBGP peers per family, `router-advertisement`, OSPF; ledger 84 and 74 statements |
| 3 remove a peer | `nodes.xrv9k.bgp.as = 65100` | vjunos-switch 7 / 9 / 9 / 0 / 5 / 0 (`delete protocols bgp group ibgp-peers-ipv4 neighbor 10.255.0.4`, the IPv6 twin, the two OSPF interface entries of the link, the description); cjunosevolved 0 / 6 / 6 / 0 / 2 / 0 | `partial`: cjunosevolved `verified`; vjunos-switch `verify_mismatch` with the *new* description reported as remaining (defect, fixed: the read-back accepted nothing under a removed ancestor although the design had re-created content there, and the ancestor itself was a keyword-only level `… unit 0 description` from the unfiltered word prefixes) | both peers gone, the eBGP side unchanged for cjunosevolved |
| 4 drop both modules | `modules: []` | vjunos-switch 1 / 67 / 67 / 0 / 6 / 0; cjunosevolved 0 / 56 / 56 / 0 / 5 / 0; removals at the top: `delete protocols bgp`, `delete protocols ospf`, `delete protocols ospf3`, `delete policy-options`, `delete routing-options` | `succeeded`, both `verified` | only interfaces, `router-advertisement` (the initial module) and `lldp` remain |
| 5 create again (all three routers) | OSPF + BGP | vjunos-switch 68 added, cjunosevolved 62 added, ceos no-op | `succeeded`, both `verified`, ceos `no_op` | — |

Found and fixed from this run: (a) the read-back now excludes what the design itself put back under a removed container and a container the design re-creates stays owned; (b) the created ancestors of a Junos apply were every word prefix of an added set
statement (158 and 173 "ancestors"), including keyword-only levels such as `set protocols bgp group X neighbor`
that Junos cannot `delete` without an identifier. The driver now also returns the device's own hierarchical
rendering of the would-be configuration (`show` inside the candidate) and the created ancestors are limited to
its real blocks.
