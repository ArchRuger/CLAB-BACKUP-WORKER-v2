---
name: clab-netlab
description: "Change network-design intent, allocation, capabilities and isolated netlab generation."
---

# clab-netlab

Read network_design.py, design_intent.py, design_adapter.py, design_engine.py and
design_capabilities.py as relevant, plus docs/NETWORK-DESIGN.md and the current
integration contract. Determine the actual pinned networklab version from the
checkout; do not silently upgrade it or infer supported features from another version.

The planner uses netlab create with the external provider in a fresh job directory
and private HOME. It must not run netlab up/down or mutate Docker, host labs or
nodes merely to create a plan. Preserve output and artifact limits, timeout,
process-group cleanup, disabled engine statistics, immutable artifacts and sanitized
errors. Only the engine integration owns the netsim/CLI dependency.

Test IPv4/IPv6 allocation, deterministic rebuilds, stable ledger behavior, endpoint
identity, platform capability mismatches, unsupported modules, malformed YAML,
child failures and cancellation. Use real pinned-engine fixtures where available.
Distinguish generated, fixture-tested and live-device-validated capabilities.

Property-based tests suit allocation overlap, adapter round trips, normalization
and ownership algebra. They complement existing unittest/Node tests; do not
replace the project's test runner. Update generated capability data through its
source pipeline, never claim an image capability from generic vendor support.
