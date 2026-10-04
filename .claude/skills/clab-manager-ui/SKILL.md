---
name: clab-manager-ui
description: "Modify the vanilla JavaScript student UI while preserving its design and behavior."
---

# clab-manager-ui

The binding UI contract is `docs/redesign/DESIGN-SPEC-ADDENDUM.md`; preserve the
capabilities in the redesign inventory and parity records. Keep the manager UI
vanilla JavaScript, fixed script order, shared globals, local assets and existing
CSP. Do not turn the application into React/Next.js, add a CDN, or introduce inline
styles on the main page. Use esc() for interpolated untrusted values.

Search scripts, HTML, Node test harnesses and Playwright tools before deleting a
seemingly unused shared global. Keep browser-global event/history/storage handling
in shell.js where prescribed so feature scripts remain testable under Node.

For every changed flow verify default, loading, empty, error, success, disabled,
cancel, retry and reconnect states. Check keyboard focus, labels, contrast,
responsive layouts and retained selections. Use semantic controls and useful
student-facing errors; do not conceal backend failures with optimistic success.

Use `node --test` for behavior and the actual browser fixture for interaction.
Screenshots alone do not establish a workflow passed. Coordinate API contract
changes with the backend owner. Cache/version markers belong to the release owner.
External frontend-design and web-design-guidelines skills may improve an assigned
component, not override this architecture or start an unsolicited visual redesign.
