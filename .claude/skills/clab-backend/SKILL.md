---
name: clab-backend
description: "Implement and test CLAB FastAPI services, state, jobs and background operations."
---

# clab-backend

Use existing `create_app(temp_dir)` service composition and install(app) routes.
Read the relevant service and tests before changing state or thread lifecycles.
Preserve the Store lock, shared operation_busy guard, startup interruption handling,
bounded jobs/logs, cleanup and thread shutdown. Do not add multi-process app
workers or share encrypted state across instances without an explicit redesign.

Public responses are allowlisted copies, not serialized internal jobs. Check new
persisted fields against public_* views, secrets, config content and raw SSH output.
Store.event does not automatically make unsafe text safe. Verify HTTP mutation
body/origin rules, WebSocket Origin and single-use terminal tickets.

Test timeout, cancellation, restart, malformed input, duplicate clicks, failed
preconditions and partial success. Never weaken assertions simply to get green.
Run focused unittest cases and the broader affected service suites. From
`clab-backup-ui/`, include `.venv/bin` on PATH because Runner invokes
ansible-playbook by name. Installer tests that CI runs before the venv stay stdlib-only.

New Python and Node test filenames must be handed to the lead for addition to the
explicit CI lists. Report exact command, exit status, environment and evidence path.
