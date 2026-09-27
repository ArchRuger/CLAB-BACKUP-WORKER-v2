# The deployed product: *Apply to devices* on the real manager (`restore-square`, 2026-09-27)

The image was rebuilt from the tree that ships as 1.30.45 and recreated on the development VM
(`clab-backup:1.30.44` label at that moment; http://192.168.132.132:8081, host network). The live lab record
(`174386ec…`) already carried the OSPF + BGP design and a succeeded plan (`9c445661…`) from the 1.30.44 check;
its ownership ledger was empty, because every apply so far had run from the scratch harness on its own data.
The devices therefore carried the design without the product owning any of it.

## Review through the real API (`POST …/review`, same-origin headers)

- First review of `ceos`: 3 added, 1 removed, **2 conflicts** (`interface Ethernet2 > ip address 10.9.0.0/31`
  and its IPv6 twin: the scratch run had pinned another prefix for the ceos–xrv9k link, and the product does
  not own those statements), `applicable: []`. The conflict logic protects what the manager never put there,
  even when another manager did.
- After the link addresses were put back by hand (`nodecli.py`, transcript `product-prep2`) and one owned
  description removed by hand (`no neighbor 10.255.0.2 description`, transcript `product-prep`): a review of
  all five devices in one call: `ceos` 1 added, 0 conflicts; `vjunos-switch` and `cjunosevolved` `no_op`;
  `xrv9k` 2 added, 1 removed, 2 conflicts (the same link, `GigabitEthernet0/0/0/1`); `host1` "A support host is
  generated only, never applied."; `applicable: [ceos, vjunos-switch, cjunosevolved]`.

## Apply through the real API with the take-over (`xrv9k`)

`POST …/review` with `takeover: [xrv9k]` (applicable), `POST …/apply` with the token, `confirm_minutes 3`, a
32-hex `request_id` and `acknowledged: true`; the job (`a58909b0…`) went `backing_up` (the product's Runner,
source `design-pre`) → `applying` → `confirming` → `succeeded` in 15 s: `xrv9k verified`, saved, read-back
clean; the product's ledger now owns 2 statements on xrv9k for plan `9c445661…`. The device: `GigabitEthernet0/0/0/1`
on `10.1.0.3/31` and `2001:db8:1:1::2/64`, OSPF FULL to vjunos-switch and ceos, no session row.

Found here: the taken-over IPv6 address `2001:db8:9::2/64` was **still on the port** beside the new one. A
take-over unblocked the apply but removed nothing: a merge replaces a single-valued statement (the IPv4
address) by itself, while an exclusive sibling (a second IPv6 address, a Junos address) simply stays. Fixed:
when a take-over covers a conflict that the first review pass still finds in the would-be configuration, the
review stages once more with that leaf among the removals (`design_ownership.takeover_leftovers`), and the
taken-over statements are verified gone after the apply. The proof of the fix is the next section.

## The take-over fix, proven through the product (`xrv9k`)

The image was rebuilt with the fix (the compose rebuild loop, seconds) and the conflict recreated by hand: the
design's `ipv6 address 2001:db8:1:1::2/64` removed from `GigabitEthernet0/0/0/1` (transcript `product-prep3`),
leaving the old `2001:db8:9::2/64` alone on the port.

- Review without take-over: 1 added, **1 conflict** (`interface GigabitEthernet0/0/0/1 > ipv6 address
  2001:db8:9::2/64`: the design would add a second address beside an unowned one), `applicable: []`, no removals.
- A review during the lab's scheduled backup answered 409 ("Wait for the active backup … to finish"): the
  review runs under `operation_busy`, as the contract says.
- Review with take-over: `applicable: [xrv9k]`, removals `interface GigabitEthernet0/0/0/1` /
  ` no ipv6 address 2001:db8:9::2/64` (the second review pass), 1 removed.
- Apply (`035f1551…`): `succeeded`, `xrv9k verified`, saved, read-back clean (the taken-over statement is
  verified gone). Device: `10.1.0.3/31` and `2001:db8:1:1::2/64` only, no session row.

## Apply from the real dialog (`ceos`, browser)

The manager rebuilt once more with every fix of the fourth review pass, then
`docs/netlab-integration/tools/check_design_apply_ui.py --apply --targets ceos --minutes 3` drove the page in
Chromium: choose `ceos`, review (1 added: the description removed by hand earlier), tick the acknowledgement,
apply, follow the progress. The dialog reported "ceos: verified — Applied, confirmed and read back."; the device
shows the design's session `clabdsg-34e6dacc committed` at 02:07:31 UTC, `show running-config diffs` empty (saved),
and the product's ledger now owns 1 statement on `ceos` beside the 2 on `xrv9k`. The tool's last step (opening
*Owned settings* under Advanced) crashed on an ambiguous locator of its own (`summary` matched the per-device
`<details>` too); fixed and rerun (`browser-design-apply-ui.md`, run 3).
