---
name: clab-network-transactions
description: "Audit or implement EOS, Junos and IOS XR configuration apply/restore transactions."
---

# clab-network-transactions

This is high-consequence work: involve Opus for ambiguous semantics, rollback,
management lockout risk, ownership deletion, uncertain completion or recovery.
First distinguish two paths: restore replaces the active configuration; design
apply merges only the intended owned configuration. Never conflate their drivers,
verification rules or recovery behavior.

Read the per-platform restore/design drivers, ownership algebra and
`docs/netlab-integration/PROVISIONING.md`. Preserve mandatory pre-change backup,
identity and management exclusions, unowned statements, created-ancestor rules,
conflict detection, native timed transactions and read-back verification. Confirm
only the transaction owned by this operation, with the NOS-specific session
requirements. A disconnected CLI is not proof of either success or rollback.

Use the exact legally available image versions recorded in the current acceptance
lab. Test one device per required kind first: cEOS, cJunosEvolved, vJunos-switch,
XRv9k. Discover resource capacity and stagger heavy boots. Never claim one Junos
kind proves the other, or that a mocked shell proves live timed rollback.

Exercise success, no-op, conflict, drift, lost SSH, interrupted commit, expired
confirmation, partial multi-node success, recovery and untouched peer devices.
Report explicit confirmed, rolled_back, failed or uncertain outcomes backed by
read-back evidence. Redact configs and secrets from published logs.
