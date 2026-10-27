# A04: link impairments across restart, stop/start and redeploy (live, 2026-10-27)

Evidence class: live (VM, real containerlab 0.79.0, manager 1.31.6 on http://127.0.0.1:8081). Lab `parity`
(manager id `d7e3a4686c084f9f88e344b5064aa162`), devices `clab-parity-{ceos,cjunos,vsw,vrt,xrv9k}`. All times UTC,
about 01:37 to 01:42. The VM check for every row is `sudo containerlab tools netem show -n clab-parity-<dev> -f json`
on all five containers; for ceos also `sudo nsenter -t <pid> -n tc qdisc show dev eth1` (netem qdisc present or
`noqueue`). The manager column is `GET /api/operations/impairments?lab_id=<id>`.

## Requests used

- Baseline and every re-read: `GET /api/operations/impairments?lab_id=<id>`.
- Set: `POST /api/operations/impairments/set` with `{lab_id, node:"clab-parity-ceos", interface:"eth1", delay:"50ms",
  jitter:"0ms", loss:1, rate:0, corruption:0, expected_id:<container id from the GET>}` -> 200
  `{container, impairments:[{interface:"eth1", port:"Ethernet1", delay:"50ms", jitter:"", loss:1.0, rate:0, corruption:0}]}`.
  Note the device key and `node` are the manager node name `clab-parity-ceos`, not `ceos`.
  The ceos neighbour (topology: `xrv9k Gi0/0/0/1 (eth2)` <-> `ceos eth1`) got `{interface:"eth2", delay:"30ms", loss:0, ...}`
  through the same route (extra rows below).
- Device actions: `POST /api/operations/preview {lab_id, action:"restart-node"|"stop-node"|"start-node", node:"clab-parity-ceos", options:{}}`
  then `POST /api/operations/confirm {token}`, then `GET /api/operations/<job_id>`; lab action `{lab_id, action:"redeploy", options:{}}`.
  Argv shown by the review: `containerlab restart|stop|start -t .../parity.clab.yaml --name parity --node ceos`,
  `containerlab redeploy -t .../parity.clab.yaml`.
- Clear: `POST /api/operations/impairments/clear {lab_id}` -> 200 `{cleared:2,total:2,failed:[],remaining:[],complete:true}`.

## Results

| # | Operation | Impairment before | After, VM | After, manager | Note |
|---|---|---|---|---|---|
| 1 | Baseline | none | all five `null` | `devices` all `impairments: []`, `interfaces: 0`, complete | |
| 2 | Set ceos eth1 (50ms delay, 1% loss) | none | `[{"interface":"eth1","delay":"50ms","jitter":"","packet_loss":1,...}]`; tc: `netem 1: root ... delay 50ms loss 1%` | one row, port `Ethernet1`, loss 1.0 | the Topology caption text (`device-impairments.js` `IMP_CAPTION`) reads "A restart, a stop and start, or a redeploy of the device **can remove them**"; the string "can last" appears nowhere in `app/static` |
| 3 | `restart-node` ceos (job 6 s, "2 links restored") | ceos eth1 50ms/1% | **gone** (`null`; tc `noqueue`) | **gone** (empty) | same container id `ed29d6c3b1e6`, new pid (24742 -> 215657) |
| 4a | `stop-node` ceos (job 39 s) | ceos eth1 50ms/1% | container `running=false`, `netem show` `null` | empty (a stopped device lists none; the set route would refuse it) | |
| 4b | `start-node` ceos (job 6 s, "2 links restored") | none (set again before 4a) | **gone** (`null`; tc `noqueue`) | **gone** | same container id, new pid |
| 4c (extra) | `restart-node` ceos, with the neighbour's end impaired | ceos eth1 50ms/1% **and** xrv9k eth2 30ms | ceos `null`; **xrv9k eth2 still `30ms`** (`"eth2(Gi0/0/0/1)"`) | only `clab-parity-xrv9k` listed, 30ms | job 21 s; the neighbour container is untouched, so its end persists; only the restarted container's own interface loses it |
| 5 | `redeploy` lab (job 21 s, exit 0; all five containers recreated, new ids) | ceos eth1 50ms/1% **and** xrv9k eth2 30ms | **all five `null`, including the neighbour's** | all empty, `interfaces: 0` | containers `Up` within about 20 s; management IPs unchanged (.111-.115); nos_login `booting` for all five at the end of the pass |
| 6 | Clear (Reset all) after setting ceos eth1 and xrv9k eth2 again on the redeployed lab | 2 rows | all five `null` | empty | `cleared 2 of 2` |
| 7 | cEOS detail: links across `restart-node` | `eth0 eth1 eth2` in the container (3) | after restart (`nsenter ... ip -o link`): `eth0 eth1 eth2` (3); after the stop/start the same 3, after the redeploy the same 3 | | the data interfaces are restored by containerlab ("2 links restored"); only the qdisc is lost |

## Conclusion

The "can last" claim is false for the device that is restarted, stopped and started or redeployed: an impairment set on a
device's own interface was gone from the VM and from the manager after `restart-node`, after `stop-node` + `start-node` and
after `redeploy`, and redeploy also removed the impairments on the neighbour devices (their containers are recreated).
It is true only for the peer end on a device that is not restarted (xrv9k eth2 survived a ceos restart), and the shipped
caption already says "can remove them", so the wording to keep is that a restart, a stop and start, or a redeploy of a device
removes the impairments on that device's interfaces (a redeploy: on every device of the lab), and the manager reads the
empty state back correctly in every case.

## Unexpected or worth knowing

- No errors and no 409 in the whole pass (one confirm per preview succeeded at once, including right after the redeploy).
- The map/list stays consistent with the VM in all cases (no stale rows).
- xrv9k reports the interface to containerlab as `eth2(Gi0/0/0/1)`; the manager row shows `interface:"eth2"`, `port:"Gi0/0/0/1"`.
- A stopped device lists no impairments in the manager, so after Stop the manager cannot show what was lost.
- Timing: restart 6 s (21 s with the second pass), stop 39 s, start 6 s, redeploy 21 s (container creation only).

## End state

Lab `parity`: all five containers Up (recreated by the redeploy at about 01:40:20); the NOS were still `booting` when the pass ended
(vJunos nodes need about 15 min, xrv9k about 12, ceos about 5); no impairment anywhere; `camp-vsrx`, `git-redesign` and
`git-redesign-b` untouched. Driver scripts (scratchpad only, not committed):
`/tmp/claude-1000/-home-archtop-projects-clab-manager/8c727c84-a148-42fb-b8ff-25a6638ec02a/scratchpad/a04.py`, `snap.sh`.
