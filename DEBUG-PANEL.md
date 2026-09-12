# Development debug panel — 1.19.1

Open **Debug panel** at the bottom of the manager sidebar. It is also linked
from **Deploy New Lab** and the VM connection guide. No imported lab is required.
The direct address is `/static/debug.html` on your manager.

## Diagnose a file-browsing failure

1. Reproduce the error in **Deploy New Lab → Lab Topologies**.
2. Open **Debug panel** and select **Refresh**. Enable **Failures only** to find
   the failed route, HTTP status, UTC timestamp, request ID and elapsed time.
3. Enter the failing absolute VM folder in **VM folder**, or leave it blank to
   check the trusted root listing. Select **Run read-only checks**.
4. Check the independent **browse** and **capabilities** results. A working
   listing remains usable even when command checks fail. Clone/catalog buttons
   remain disabled until capability checks succeed.
5. Select **Download report** to save the displayed snapshot and most recent
   probe as JSON. Refresh before downloading if you need newer requests.

The checks use the saved password and pinned SSH connection. They do not read
topology contents, run lifecycle commands, change settings, or deploy labs.
Capability checks bypass the normal cache to detect stale helpers after setup.
Only one diagnostic probe runs at a time. Each of its two helper responses has
a 30-second timeout, in addition to SSH connection setup time. Failed checks
include controlled recovery hints; a helper-version mismatch requests a matching
source installation. Rerun after changing VM settings.

## Report contents and limits

The panel shows manager/Python/dependency versions, uptime, saved record counts,
VM readiness flags and the discovered helper version. **Last audit write**
reports whether the most recent action-log write succeeded. On failure, check
manager storage permissions and free space; the console also records a controlled
warning. Logging resumes on the next successful write, but missed events are not
replayed. This flag describes the last write, not a continuous storage probe. Request history contains
the latest 200 API requests since startup, excluding successful state/debug
polling. Failures are included even for those polling endpoints. Route templates
omit actual lab/job identifiers; unknown routes use `/api/unknown`.

Reports omit credentials, host addresses, usernames, VM paths, file contents,
headers, request bodies, query strings and raw logs. The optional folder value
is used for the probe but is not included in the report. Diagnostic history is
in memory and disappears on manager restart; ordinary action logs keep their
existing retention. The panel has the same access policy as this lab manager,
including its same-origin API checks. It adds no terminal or arbitrary command
execution endpoint.

This is application diagnostics, not a replacement for installation checks.
If the manager cannot start, run from the source root in the VM terminal:

```bash
bash deploy/check-install.sh
```

To install this source release or refresh mismatched helpers, use the existing
installer from the complete 1.19.1 source checkout:

```bash
bash deploy/install.sh
```

Choose the install/update option and retain your existing settings. Then reopen
the debug page and confirm **Release 1.19.1** and matching helper results. The
installer retains persistent data and VM credentials. This source change is
not a published image or a completed VM deployment.
