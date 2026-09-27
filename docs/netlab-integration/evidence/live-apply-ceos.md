# Live proof of *Apply to devices* on cEOS (`restore-square`, 2026-09-27)

The real service path (`DesignApply.review` → `submit` → `execute` → settle → ledger), run from a scratch
`create_app` instance on its own data directory (`scratchpad/live_apply_ceos.py`; discovery seeded as fresh,
the runner started for the real pre- and post-change backups through Ansible, never the deployed manager's
data). Target: `clab-restore-square-ceos` (cEOS 4.35.0F) at containerlab's startup configuration, the other
three routers unconfigured. Every device read-back below was taken independently with
`docs/multi-platform-restore/tools/nodecli.py` (transcripts under its `transcripts/` folder, tags
`pre-apply`, `post-apply1`, `post-apply4`, `post-apply5`, `post-apply6`, `post-recover7`, …).

| Step | Plan | Review (added / removed / stale / conflicts / expected / removals / kept) | Job | Device read-back |
|---|---|---|---|---|
| 1 create | OSPF + BGP, dual stack | 104 / 0 / 0 / 0 / 1 (`no ip routing`) / 0 / 0 | `succeeded`, `verified`, saved; pre and post backups `design-pre`/`design-post` succeeded | `router ospf 1`, `router bgp 65000` with three iBGP peers in `Connect`, no session left (`clabdsg-… committed` in the history row), `show running-config diffs` empty |
| 2 re-apply | same | 0 / 0 / 0 / 0 / 0 / 0 / 0, `no_op` | first run: `failed` "None of the selected devices is running" (defect, fixed: an all-no-op job finalises as `succeeded` "Every selected device already matched the plan; nothing was changed."); rerun `succeeded` | untouched |
| 3 manual + conflict | manual `interface Loopback99` (`description manual-kept`, `192.0.2.99/32`), manual `neighbor 192.0.2.200` under the owned `router bgp 65000`, and `description manual-changed` on the owned `Ethernet1` description | 1 / 1 / 0 / **1** (`interface Ethernet1 > description manual-changed`) / 0 / 0 / 0, `applicable: []` | not submittable without take-over | — |
| 3b take-over | same, `takeover: [ceos]` | as above, `applicable: [ceos]` | `succeeded`, `verified` | the design's description back; Loopback99 and the manual peer untouched |
| 4 renumber a link | `links["ceos:eth2--xrv9k:Gi0/0/0/1"].prefix = 10.9.0.0/31, 2001:db8:9::/64` | 2 / 2 / 2 / 0 / 0 / 2 (`no ip address 10.1.0.2/31`, `no ipv6 address 2001:db8:1:1::1/64` under `interface Ethernet2`) / 0 | `succeeded`, `verified` | `Ethernet2` carries `10.9.0.0/31` and `2001:db8:9::1/64`; Loopback99 and the manual peer intact |
| 5 remove a peer | `nodes.xrv9k.bgp.as = 65100` (xrv9k becomes an eBGP neighbour over the link) | 13 / 17 / 17 / 0 / 0 / 17 / 0 | `succeeded`, `verified` | iBGP `neighbor 10.255.0.4` and `2001:db8:ff:4::1` gone, eBGP `neighbor 10.9.0.1` and `2001:db8:9::2` present, `Ethernet2` OSPF lines gone. Artefact: per-line negation left `no neighbor 10.255.0.4 activate` under both address families (owned, removed by the next apply). Rule added: a neighbour whose every line is stale goes with one `no neighbor X` |
| 6 drop both modules | `modules: []` (link prefix kept) | 5 / 79 / 80 / 0 / 0 / 44 / **1** (`router bgp 65000`, manual peer under it) | first run: `partial` / `verify_mismatch` with `router bgp 65000` remaining (defect, fixed: a container kept for a manual child is not a verification failure; the device reports how many stayed) | no OSPF, no route-maps, `router bgp 65000` holding only the manual peer plus the four `network` statements EOS moved from the removed address families to the process level (owned; the next apply removes them by name). Rule added: an address family removed whole has its `network` statements removed by name first. Loopback99 intact, saved |
| 7 timer | OSPF + BGP again, `confirm_minutes 2`, the manager process killed right after arming (`_settle_and_record` replaced by `os._exit`) | 82 / 4 / 4 / 0 / 0 / 4 (`no network …` × 4) / 0 | the device held `clabdsg-…` pending with the timer; a new process on the same data 155 s later marked the job `interrupted`, rechecked the device: `rolled_back` "The change was not confirmed in time and the device undid it; the configuration from before is active."; ledger unchanged (26 statements of the previous plan) | no session, no OSPF, the four `network` lines and the manual peer as before, `diffs` empty |
| 8 restart in the window | same, `confirm_minutes 5`, killed after arming, restarted at once | as 7 | `interrupted` job; the recheck found the manager's own pending session, confirmed it, `write memory`, read back: `verified`, ledger written (104 statements, plan `387c3693eeee`). Wording fixed afterwards: the interrupted job now says per device what the read-back came to instead of "undone by the device" | OSPF and BGP back, Loopback99 and the manual peer intact, `diffs` empty |
| 9 drop both modules again (rules of steps 5 and 6 in place) | `modules: []` | 5 / 79 / 80 / 0 / 0 / … / 1 | `succeeded`, `verified`, "1 setting(s) stayed because manual configuration sits under them." | `router bgp 65000` holds only the manual peer (no relocated `network` lines, no `no neighbor … activate` leftovers), no OSPF, no route-maps, Loopback99 intact, saved |
| 10 create again | OSPF + BGP | 82 / 0 / 0 / 0 / 0 / 0 / 0 | `succeeded`, `verified`, ledger 104 statements, 8 created ancestors | the design back, the manual settings intact |

## Words the students see that came out of this run

- The review of step 5 masked `send-community standard extended large` as `send-community [redacted]`
  (the restore's secret masker matched `community`); the masker now leaves `send-community` alone while
  `snmp-server community` stays redacted.
