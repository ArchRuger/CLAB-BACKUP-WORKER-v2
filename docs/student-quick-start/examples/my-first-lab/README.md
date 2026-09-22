# my-first-lab

A two-router Arista cEOS lab built in the manager's visual lab builder.
`r1` and `r2` are joined by one link (r1 Ethernet1 <-> r2 Ethernet1).
The link is addressed 10.0.0.1/30 (r1) and 10.0.0.2/30 (r2); r2 also carries a
Loopback0 at 10.255.0.2/32.
Saved progress (device configurations, not this topology file) lives in `latest/`
and `checkpoints/`.
