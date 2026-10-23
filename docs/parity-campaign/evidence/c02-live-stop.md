# C02 live pass: Stop of a running lifecycle command (R010)

Live evidence on the disposable development VM, 2026-10-23 (all times UTC, `date -u +%T.%N` or the
manager's own stamps). Manager `http://127.0.0.1:8081`, release 1.31.1 rebuilt from the tree with the cancel
route; containerlab 0.79.0; helper `clab-manager-operate` 1.31.1. Mechanism under test: `C02-DESIGN.md` §3
(manager closes the SSH channel, the helper's heartbeat fails with `BrokenPipeError`, `stream()`'s `finally`
sends SIGTERM then SIGKILL to the containerlab process group, the host flock is released when the helper exits,
the manager probes with `preview` for up to 20 s before writing `cancelled`).

Evidence class: live (real manager, real SSH gateway and helper, real containerlab, real cEOS containers).
Nothing here is a unit or fixture result. Two independent stop runs were made (the brief asked for one).

No passwords, keys or device configuration text appear below. The `parity` lab and the manager's other labs
were not touched (the five `clab-parity-*` containers were running before and after; the other two labs
were already `exited`).

## Setup (disposable lab `stoptest`)

| Step | Command (`M="python3 docs/git-redesign/tools/live/mgr.py"`) | Result |
|---|---|---|
| Memory | `free -g` | 72 GB total, 36 GB available before the first deploy, 34 GB with the lab running |
| Folder | `mkdir -p /srv/containerlab-node-manager/projects/stoptest; chgrp clab_admins ...; chmod 2775 ...` | `drwxrwsr-x archtop clab_admins`, like `parity` |
| Topology | `stoptest.clab.yaml`: two `arista_ceos` (`n24l/ceos:4.35.0F`), `ceos1` 172.20.20.121, `ceos2` 172.20.20.122, one link `ceos1:eth1`-`ceos2:eth1`, mgmt network `clab` 172.20.20.0/24 | `-rw-rw-r-- archtop clab_admins`; both addresses were free |
| Refresh | `$M POST /api/discovery/refresh` | 200; `stoptest` not listed (discovery lists deployed labs only) |
| Preview | `$M POST /api/discovery/import-preview '{"name":"stoptest"}'` | **409** `The deployed files are unavailable...` (expected for an undeployed lab; this is the fallback case the brief named) |
| Deploy once | `cd .../projects/stoptest && sudo containerlab deploy -t stoptest.clab.yaml` | exit 0, both nodes `running`, 25.2 s (02:56:58.8 to 02:57:24.0) |
| Import | refresh, then `import-preview` (200, token), then `$M POST /api/discovery/import '{"name":"stoptest","token":"<token>"}'` | 200, lab id `477e7b7a...` |
| Undeploy through the manager | preview `{"action":"destroy","lab_id":...}` then `POST /api/operations/confirm {"token":...}` | 200, job `a1046cc1...` `succeeded` exit 0 in 1.0 s; `containerlab inspect --all` then lists no `stoptest` container |

Operation bodies (manager routes in `lab_operations.py` `install()`): `POST /api/operations/preview`
`{"action":"deploy","lab_id":"<id>"}` returns the plan and a `token`; `POST /api/operations/confirm`
`{"token":"<token>"}` returns the job (202-less, plain 200 with `status: queued`); `GET /api/operations/{id}`
is the poll; `POST /api/operations/{id}/cancel` with body `{}` is the stop.

Observers (scripts in the session scratchpad, not committed): a 4 Hz sampler (actual cycle about 0.34 s)
recording `ps -eo pid,pgid,etimes,args` lines whose command word is `containerlab` or the operations helper,
plus `sudo -n fuser /run/clab-manager-operations.lock` (the holders of the host flock; `fuser` does not take the
lock, so it cannot disturb the manager's probe); and a 1 Hz Python poller of `GET /api/operations/{id}`.
The brief's literal `ps ... | grep -E 'containerlab|clab-manager-operate'` also matches every cEOS container's
`/sbin/init` line (its command line carries `CLAB_LABEL_CONTAINERLAB=...`), so the sampler matches the command
word instead. `ps` runs a few milliseconds before `fuser` in each cycle.

## Run 1: deploy, stop 3.6 s after the job started (job `4ce5d39ffdc84574b50ff589d98ca29b`)

Commands: `preview deploy` (200, plan, no warnings), `confirm` (200), 1 Hz poll, `sleep 4`,
`$M POST /api/operations/4ce5d39f.../cancel '{}'` twice, then `preview deploy` through the manager.

| Time (UTC) | Event |
|---|---|
| 02:58:18.759 | `confirm` answered 200, job `queued` |
| 02:58:18.766 | poll: `running`, `Executing on the VM` |
| 02:58:19.10 | first sample with the helper (`sudo -n /usr/local/sbin/clab-manager-operate`, flock holder pid 554655) and `/usr/bin/containerlab deploy ... --name stoptest`, pid = pgid 554704 |
| 02:58:22.766 | **cancel sent** (t = 0) |
| 02:58:22.770 | cancel answered **202** `{"id":"4ce5d39f...","status":"running","cancel_requested":"2026-10-23T02:58:22.768174+00:00","message":"Stopping… the manager has asked the lab VM to end the command"}` (3.6 ms) |
| 02:58:22.770 | second cancel: **202**, identical `cancel_requested` (idempotent) |
| 02:58:22.777 | poll: still `running`, message still `Executing on the VM`, `cancel_requested` set (the 0.2 s stop tick had not run yet) |
| 02:58:22.779 | `preview deploy` through the manager: **409** `Wait for the current lab operation to finish.` (the manager's busy guard, as designed) |
| 02:58:23.442 | last sample with the process group: containerlab pgid 554704 `etimes` 4, flock held by 554655 (t + 0.67 s) |
| 02:58:23.781 | poll: `running`, message `Stopping… the manager has asked the lab VM to end the command` |
| 02:58:23.804 | first sample with **no** containerlab or helper process and **no** flock holder (t + 1.04 s) |
| 02:58:24.147 | sample shows the manager's follow-up probe: a new `sudo -n ...clab-manager-operate` (pid 557094) holding the flock, no containerlab child |
| 02:58:24.285 | job `finished` stamp written (t + 1.52 s) |
| 02:58:24.783 | poll: **`cancelled`**, message `You stopped Start lab. The lab may be only partly started: Redeploy lab.`, `exit_code` null |

ps lines (awk's own line removed, command shortened; columns: sample time, pid, pgid, etimes, command, flock holders):

```
02:58:22.717733010  554654  554653       3 sudo -n /usr/local/sbin/clab-manager-operate lockholders=[554655]
02:58:22.717733010  554704  554704       3 /usr/bin/containerlab deploy -t <projects>/stoptest/stoptest.clab.yaml --name stoptest lockholders=[554655]
            <-- cancel sent 02:58:22.766 -->
02:58:23.073211172  554654  554653       4 sudo -n /usr/local/sbin/clab-manager-operate lockholders=[554655]
02:58:23.073211172  554704  554704       4 /usr/bin/containerlab deploy -t <projects>/stoptest/stoptest.clab.yaml --name stoptest lockholders=[554655]
02:58:23.442037417  554654  554653       4 sudo -n /usr/local/sbin/clab-manager-operate lockholders=[554655]
02:58:23.442037417  554704  554704       4 /usr/bin/containerlab deploy -t <projects>/stoptest/stoptest.clab.yaml --name stoptest lockholders=[554655]
02:58:23.804057279  (no containerlab/helper process) lockholders=[]
02:58:24.147459438  557094  557093       0 sudo -n /usr/local/sbin/clab-manager-operate lockholders=[557095]      <-- follow-up probe
02:58:24.488651629  (no containerlab/helper process) lockholders=[]
```

The 25.2 s deploy of the setup step, and the 16.4 s and 21.2 s redeploys below, show the command had 12 to 20 s
left when it was stopped; the job output ends at `Running postdeploy actions for Arista cEOS 'ceos2' node` with
no result table, so the command did not finish by itself.

## Run 2 (repeat on a freshly destroyed lab), stop 2.5 s after the job started (job `16b374a5aca34ea3bb71bfbc49b2e68a`)

Same commands; `CANCEL_AFTER=2.5`.

| Time (UTC) | Event |
|---|---|
| 03:01:26.845 | `confirm` 200 |
| 03:01:27.35 | first sample with helper (flock holder 625032) and containerlab pgid 625111 |
| 03:01:29.351 | **cancel sent**; answered 202 at 03:01:29.355, `cancel_requested` `2026-10-23T03:01:29.353206+00:00`, same Stopping message; repeat 202, same stamp; manager `preview deploy` 409 `Wait for the current lab operation to finish.` |
| 03:01:30.231 | last sample with flock held (625032) and containerlab 625111 `etimes` 3 (t + 0.88 s) |
| 03:01:30.591 | flock **free**; the helper and containerlab lines still listed (ps ran milliseconds before fuser, so the processes were exiting) (t + 1.24 s) |
| 03:01:30.986 | no deploy process; the only lines are the manager's follow-up probe (`containerlab inspect --all --format json`, pgid 627209) (t + 1.64 s) |
| 03:01:29.859 and 03:01:30.863 | polls: `running`, `Stopping… the manager has asked the lab VM to end the command` |
| 03:01:31.090 | `finished` stamp (t + 1.74 s) |
| 03:01:31.866 | poll: **`cancelled`**, message `You stopped Start lab. The lab may be only partly started: Redeploy lab.` |

## What the half-deployed lab looks like (checked after both runs)

After run 1 (02:58:52) and after run 2:

- `sudo containerlab inspect --all`: no `stoptest` row (0 matching lines). `docker ps -a --filter name=clab-stoptest`: no container. `docker network inspect clab`: only the five `clab-parity-*` members. `ip -br link | grep -iE 'ceos|stoptest'`: nothing. `/etc/ssh/ssh_config.d/`: no `clab-stoptest.conf`. containerlab had already created the two containers (the output shows postdeploy actions) and removed them again before it exited, so a stopped deploy was cleaned up by containerlab itself on SIGTERM (inferred from the result: the signal itself is not visible).
- What does remain after run 1: the lab directory `<projects>/stoptest/clab-stoptest` (root-owned: `.state.clab.yaml`, `ceos1/`, `ceos2/`, `.tls/`, `authorized_keys`) and three **zero-byte** files written at 02:58: `ansible-inventory.yml`, `nornir-simple-inventory.yml`, `topology-data.json`. (Not re-listed after run 2.)
- Manager view (`GET /api/state`, lab `stoptest`): `deployment.status` `Not deployed`, `No matching containers found on the VM.`; both nodes readiness `Lab unavailable`; `last_deployed` empty (a cancelled deploy records no deployment time, as designed).

## The following preview (lock free for the manager)

`preview deploy` through the manager after the job ended (`02:59:19.549`, after run 1; `03:01:49.808`, after
run 2): **200**, a plan (`action, affected, argv, digest, images, name, path, source_hash, source_name, steps,
token, warnings`), not `Another host lab operation is running.` The same `preview` during `Stopping…` was refused
at the manager (409 `Wait for the current lab operation to finish.`), so the helper's own busy message was
never visible from outside; the probes' individual answers are not recorded in the job.

## The aftermath the message names: Redeploy lab through the manager

| Run | Commands | Result |
|---|---|---|
| After run 1 | `preview redeploy` (200, one warning: `Runs this trusted topology with host privileges...`), `confirm` (200), poll | job `7263e6fe...` `succeeded`, `Operation completed`, exit 0, 16.4 s (02:59:20.72 to 02:59:37.08); output ends with the table: `clab-stoptest-ceos1` and `-ceos2` `running`, 172.20.20.121 and .122 |
| After run 2 | same, job `aa55a017...` | `succeeded`, exit 0, 21.2 s (03:01:50.93 to 03:02:12.18); same table; `containerlab inspect --all` shows both `running` |

## Second experiment: cancel in other states

| Command | Answer |
|---|---|
| `POST /api/operations/7263e6fe.../cancel '{}'` (redeploy, finished) at 02:59:37.800 | **409** `This operation has already finished.` (same at 03:02:12.182 for job `aa55a017...`) |
| `POST /api/operations/000...0/cancel '{}'` (unknown id) | **404** `Operation not found.` |
| cancel of a finished `inspect` job (`bf2fed6b...`, ran 02:59:45 to :46) | **409** `This step finishes on its own in a moment and cannot be stopped.` |
| cancel of a finished `create` job (`9248a421...`, new file `stoptest-create.clab.yaml` in the stoptest folder, ran 02:59:46 to :47, succeeded) | **409** `This step finishes on its own in a moment and cannot be stopped.` |

Limit: `create` and `inspect` finish in about 0.25 s and 1 s, so they could only be cancelled after they
ended. The route tests the action before the status, so the answer is the same for a running one, but a
running `create` was not caught.

## Cleanup

`$M` destroy through the manager (job `afcbd0e5...` `succeeded`, 1.0 s); `containerlab inspect --all` and
`docker ps -a` showed no `stoptest` container; `sudo rm -rf --one-file-system /srv/containerlab-node-manager/projects/stoptest`
(exit 0; `projects/` lists `git-redesign`, `git-redesign-b`, `parity`); `$M DELETE /api/labs/477e7b7a... '{"name":"stoptest"}'`
returned 200 `{"name":"stoptest","prevent_reimport":true,"removed":"477e7b7a..."}`. The default `prevent_reimport` added
`stoptest` to `ignored_labs`; `$M POST /api/discovery/forget-exclusion '{"name":"stoptest"}'` cleared it
(`ignored_labs` is `[]`, the lab list is `git-redesign-b`, `git-redesign`, `parity`). The nine `stoptest` /
`stoptest-create` records stay in the manager's operation history (Remove lab does not delete operations).

## Verdicts

| Claim | Verdict |
|---|---|
| Stop ends the containerlab process group on the VM | **Met.** Group (and the `sudo`/helper chain) gone within 1.04 s of the cancel in run 1 (last seen at +0.67 s) and 1.64 s in run 2 (last seen at +0.88 s); design bound was about 6 s. The command was ended 12 to 20 s before it would have finished. SIGTERM was enough in both runs, so the 5 s wait and the SIGKILL branch were **not** exercised live. |
| The host flock is free when the helper has exited | **Met.** No holder after 1.04 s (run 1) and 1.24 s (run 2). |
| Job reads `Stopping…` then `cancelled` with the aftermath sentence | **Met.** 202 body carries `Stopping…`; the record showed it from the next poll; `cancelled` after 1.52 s (run 1) and 1.74 s (run 2) by the job's own stamps, with `You stopped Start lab. The lab may be only partly started: Redeploy lab.` and `exit_code` null. The fallback sentence `The lab VM is still ending the command...` did not appear. |
| A following preview answers a plan | **Met** (200 plan after both runs); during `Stopping…` the manager refuses with its busy guard. |
| Redeploy repairs the stopped deploy | **Met** twice (exit 0, both nodes running). The lab was left with no containers and three zero-byte inventory files, which the redeploy rewrote. |
| 409 after finish; 409 for a non-stoppable action; 404 unknown | **Met** (finished jobs only, see the limit above). |

## What did not match the design, or was not observed

1. The 5 s wait and SIGKILL escalation were not reached (containerlab exits on SIGTERM within about a second); the
   `etimes` of the stopped group was 3 to 4 s, so this was a stop at an early stage (containers created, postdeploy
   running), not a late one.
2. The job record's message stayed `Executing on the VM` for the first poll after the 202 (about 10 ms later) and
   showed `Stopping…` on the next one. Not an error; a 1 s UI poll sees `Stopping…` for 0 to 2 polls.
3. The follow-up probes' own answers (helper busy vs. plan) are not visible in the record; only the end state
   (`cancelled` with the aftermath sentence, written 0.1 to 0.5 s after the group left) is.
4. A `confirm` of a destroy sent about 20 s after the first redeploy (02:59:57.8) got **409** `Wait for the lab backup or login
   job to finish.` (`guard()`), and the next `preview deploy` 409'd the same way; it cleared by itself within about
   a minute. Cause not verified (a post-deploy backup or login job on the lab is the only source of that
   message); unrelated to Stop as far as seen, but a script or student who stops and redeploys quickly meets it.
5. Release wording: the job label for the `deploy` action is `Start lab`, so the stored sentence reads
   `You stopped Start lab. The lab may be only partly started: Redeploy lab.`, consistent with §3's template.
6. A stopped deploy leaves zero-byte `topology-data.json`, `ansible-inventory.yml` and `nornir-simple-inventory.yml`
   in `clab-<lab>/` (containerlab truncates them at start); the manager showed `Not deployed` and nothing consumed them.
