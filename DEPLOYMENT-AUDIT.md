# Deployment and operation audit — 1.19.2

Originally reviewed from `2d34415` (1.19.0), now integrated with merged main
`2c10037` (1.19.1) on `codex/deployment-operation-audit`. These are reproduced source defects, not
claims about the cause of an error on a particular VM. No live VM, router,
credentials or deployment was changed.

## Confirmed findings and fixes

| Priority | Finding and trigger | Result before the fix | Fix and regression evidence |
|---|---|---|---|
| P1 | A topology file appears after Create's final existence check, for example from an external editor. | Atomic replacement overwrites that file. | Publish the completed temporary file with a no-overwrite hard link. A race test verifies that the external file survives and creation fails clearly. |
| P2 | Discovery or Git SSH exit status arrives before the last stdout packets. | A valid response is truncated or rejected, affecting discovery and Git saves. | 1.19.1 already waits for stream EOF; this integration retains it and adds bounded Git stderr. Real localhost Paramiko tests reproduce delayed output, a fragmented 160 KiB response, and missing/nonzero status. Git stderr now counts toward its response limit. |
| P2 | A storage write fails in a discovery poll or scheduled-backup tick. | The background thread exits and never resumes polling or scheduling. | Catch storage failures at the loop boundary, issue a controlled warning, and retry on the normal interval. Fault-injection tests verify the next iteration and scheduler deferral. |
| P2 | A lab operation finishes while its audit log or final state write fails. | Cleanup can retain the active-operation guard and block subsequent work. | Always release the guard; retain terminal state in memory if disk is unavailable. Tests cover both audit and state-write failures. |
| P2 | Git progress or update-from-remote cannot persist its final status. | State rollback leaves a busy reservation even after the worker ends and storage recovers. | Preserve a terminal/retryable in-memory result, original capture identity and known commit. Tests verify guard release and retry without recapturing devices. |
| P2 | Appending the audit log fails during startup or after an API mutation has already saved. | Logging can prevent startup or report an already-completed action as failed. | Make audit writes best effort, emit a controlled console warning, and expose the last audit-write result in Debug panel. API tests verify the saved mutation and diagnostic flag. Lost audit events are not replayed. |
| P2 | A Git helper/hook inherits stdout and outlives the Git parent. | The timeout sees an exited parent and leaves its descendant holding the pipe open indefinitely. | Kill the Linux process group at the deadline even if the parent exited, and return a controlled timeout. The simulated ordering regression passes locally; a real Linux process-group regression is included in CI but skipped on this Windows host. |

P1 denotes a data-loss path; P2 denotes a functional or recovery failure.
The storage fixes keep failures recoverable; they do not make unavailable disk
writes durable or provide transactions across state, snapshots and remote Git.
After an interrupted remote action, inspect its saved status and the VM before
retrying. Discovery and scheduler warnings retry every 30 and two seconds,
respectively; a persistent storage fault still needs repair.

## Integration with current main

Latest main already fixes the original discovery/Git response truncation. Its
60-second discovery deadline, helper timeout budgets, 90-second debug probes,
authentication hints, dependency bounds and LF normalization are retained.
The other six original findings and the Git stderr limit remained unfixed:
running 16 focused audit regressions against `2c10037` produced three passes,
five assertion failures, seven errors and one Linux-only skip. These are
fault-injection regressions, not the result of its full test suite.

Version 1.19.2 combines those remaining fixes with current main. The validation
record below links the combined test results; no remote merge or push is implied.

## Review coverage and limits

The review followed the installer menu, prerequisite/APT setup, helper and
restricted SSH gateway installation, VM password setup, Git onboarding,
Compose launcher, volume migration and installation health checks. Runtime
review covered discovery, folder browsing, lab operations, the backup scheduler,
Git export/retry, persistence, diagnostics and their API/browser connections.

No additional fresh-install packaging defect was confirmed in that review.
Existing installer and health-check regression tests were exercised, but their
mocked host probes do not establish that an Ubuntu installation succeeds.
The existing 1.19.0 independent file-browser/capability behavior remains covered.

The full local test results are recorded in
[VALIDATION.md](clab-backup-ui/VALIDATION.md). Local tests use temporary state,
temporary repositories and localhost SSH fixtures. Docker, WSL and a live Ubuntu
target were unavailable. This is not an end-to-end deployment certification.

Outstanding deployment evidence:

- Fresh Ubuntu installation and upgrade with the existing data mount retained;
  actual APT, Docker build/recreation, system services, SSHD, sudo and gateway policy.
- Matching installed helpers and browser-to-VM folder browsing using the real
  saved connection; run `bash deploy/check-install.sh` and the Debug panel checks.
- Actual device login, terminal and backup behavior for the deployed NOS images,
  plus Git credential-helper/network behavior. Any live lifecycle action or push
  must be performed deliberately in the intended lab/repository.
- The new real Linux inherited-stdout timeout test and other platform-specific
  tests skipped locally; remote CI results are not available for this unpushed branch.

## Apply the fixes

Once this source is merged and obtained on the VM, run `bash deploy/install.sh`
from its complete root checkout. Use the normal install/update path to install
matching helpers and recreate the manager with its existing persistent data.
Confirm **Release 1.19.2**, matching helper versions and the last audit write in
Debug panel, then run the installation health report. Rebuilding an image alone
does not update a running container. No image publication is included here.
