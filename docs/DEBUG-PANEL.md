# Diagnostics

Open **Manager ▾ › Diagnostics** in the top bar. It is also linked from the deploy page
and the VM connection guide. No lab needs to be open. The direct address is
`/static/debug.html` on your manager (the page was called *Debug panel* before the
student-centred UI).

## Find out why a VM folder does not open

1. Reproduce the error in **Manager ▾ › Deploy a new lab…** (the topology browser).
2. Open **Diagnostics** and select **Refresh**. Tick **Failures only** under *Recent
   requests to the manager* to find the failed route, HTTP status, UTC timestamp, request
   ID and elapsed time.
3. Under **VM connection checks**, paste the folder that would not open in **VM folder**,
   or leave it blank to check the lab folders root, then select **Run checks**.
4. Read the two independent rows, **Folder listing** and **VM commands**. A working
   listing stays usable even when the command check fails. The download buttons of the
   topology browser stay disabled until the command check passes.
5. Select **Download report** to save the displayed snapshot and the most recent checks
   as JSON. Refresh before downloading if you need newer requests.

The checks use the saved password and pinned SSH connection. They do not read
topology contents, run lifecycle commands, change settings, or deploy labs.
The command check bypasses the normal cache to detect stale helpers after setup.
Only one check runs at a time. Each of its two helper responses has a 90-second
timeout, in addition to SSH connection setup time; the command check runs several
containerlab help commands on the VM, so a slow VM is reported as slow rather than as
missing. A failed row leads with a sentence in plain words (the VM refused the saved
password; the VM account cannot run lab operations; this folder is outside the allowed
lab folders; …) followed by the manager's exact hint, which names the launcher command
that repairs it. A helper that is a different release than the manager is reported as
such. Rerun after changing VM settings.

## Report contents and limits

The page shows the manager, Python and dependency versions, how long the manager has
been running, the counts of what is saved in it, the VM connection flags and the VM
helper version. **Activity log** reports whether the most recent action-log write
succeeded (*Working* or *Failed — check storage*). On failure, check manager storage
permissions and free space; the console also records a controlled warning. Logging
resumes on the next successful write, but missed events are not replayed. This flag
describes the last write, not a continuous storage probe.

The request list contains the latest 200 API requests since startup, excluding
routine status polling. Failures are included even for those polling endpoints. Route
templates omit actual lab/job identifiers; unknown routes use `/api/unknown`.

Reports omit credentials, host addresses, usernames, VM paths, file contents,
headers, request bodies, query strings and raw logs. The optional folder value
is used for the check but is not included in the report. Diagnostic history is
in memory and disappears on manager restart; ordinary action logs keep their
existing retention. The page has the same access policy as this lab manager,
including its same-origin API checks. It adds no terminal or arbitrary command
execution endpoint.

This is application diagnostics, not a replacement for installation checks.
If the manager cannot start, run the [health report](HEALTH-CHECK.md) from any
directory in the VM terminal:

```bash
bash "$HOME/projects/clab-manager/deploy/check-install.sh"
```

To install a source release or refresh mismatched helpers, run the installer from
the same source folder and choose the install/update option; it retains persistent
data, VM credentials and settings:

```bash
bash "$HOME/projects/clab-manager/deploy/install.sh"
```

Then reopen Diagnostics and confirm that **Version** shows the number in
`clab-backup-ui/VERSION` and that the VM connection checks pass.
