---
name: clab-capture
description: "Validate browser Wireshark, capture lifecycle and same-origin relay isolation."
---

# clab-capture

Read capture.py, capture_sessions.py, capture_service.py and docs/CAPTURE.md.
Only the separate capture service owns Docker access; the manager relays same-origin
HTTP/WebSockets and must not expose the service directly to browsers.

Preserve authenticated service access, owner/session checks, pinned image policy,
labelled containers, bounded sessions/timeouts and cleanup. Client input must not
select arbitrary images, commands, mounts or outbound URLs. Keep generated pcaps,
private tokens and raw packet data out of GitHub and routine logs.

Run focused capture tests, Compose validation and the existing real loopback capture
smoke when Docker is available on the assigned dev VM. Verify start, stream, stop,
idle expiry, download, failed startup, concurrent limits and orphan cleanup. Do not
label mocked HTTP tests as actual packet-capture validation. Restart only the owned
capture stack; do not reintroduce the removed telemetry/Grafana stack.
