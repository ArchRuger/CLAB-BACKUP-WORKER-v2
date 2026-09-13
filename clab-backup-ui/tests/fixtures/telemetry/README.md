# Telemetry notification fixtures

Each file is one gNMI `SubscribeResponse` sequence as pygnmi's `telemetryParser`
presents it, written to match the documented OpenConfig models and the update
shapes the three vendors use:

- `eos_interfaces_json_ietf.json`: EOS sends one notification per interface with the
  counters container as the prefix and one leaf per update (JSON_IETF numbers).
- `xr_interfaces_json_ietf.json`: IOS XR answers a module-prefixed path
  (`openconfig-interfaces:...`) with a JSON object per container and encodes
  uint64 counters as decimal strings (RFC 7951).
- `junos_interfaces_proto.json`: Junos Evolved sends the prefix as path elements and
  typed values (`uint_val`), plus its extra `__timestamp__`-style leaves.
- `*_bgp_*.json`: the OpenConfig BGP neighbour session state and prefix counts.

These are fixture validations of the normaliser and the collector pipeline. They
were written from the models and public examples, not captured from the lab
images, and do not replace the live acceptance procedure in docs/TELEMETRY.md.
