# Network design: backend contract for 8a, 8d and 8e

The API the Design tab uses for the retired protocols (8a), the EVPN gate (8d) and the device review progress (8e).
The backend is `clab-backup-ui/app/design_intent.py` (`RETIRED` and helpers), `network_design.py` (context, save,
import, validate, generate), `design_capabilities.py` (`with_policy`, `public_matrix`, `public_catalogue`) and
`design_apply.py` (review jobs, apply guards). The decisions and their evidence are D10.1–D10.5 in
`docs/netlab-integration/DECISIONS.md`. Tests: `tests/test_design_retirement.py`, `tests/test_design_review_jobs.py`.

All routes sit under `/api/` behind the same-origin guard; a mutating request carries a JSON body.

## Error details: a string or an object

FastAPI answers an error as `{"detail": …}`. In this contract `detail` is **either a string** (unchanged older
errors) **or an object** whose `message` is the sentence to show. Read it as
`typeof detail === 'string' ? detail : detail.message`. The shared `api()` helper in `app.js` currently throws
`'Check the form fields and try again.'` for an object detail, so the Design tab must read object details itself
(keep the response, or extend the helper to use `detail.message` and keep the object for `problems` and
`review_job_id`).

Object details used here:

| Shape | Where |
|---|---|
| `{message, problems: [{path, message}], retired: [module id]}` | Save 400 and Import 400 (a retired module added), Generate 409 (the design uses a retired module) |
| `{message, problems: [{path, message}]}` | Generate 400 (the design has problems) |
| `{message, review_job_id}` | Review POST 409 (a review of this lab is already running) |

`problems[].path` uses validate()'s spelling (`modules`, `nodes.r1.modules`, `links.<key>.vxlan`,
`links.<key>.endpoints.r1.evpn`, `vlans.red.evpn`).

## 8a and 8d: retired modules and the EVPN gate

Retired from authoring: `eigrp` (label *EIGRP*), `ripv2` (label *RIP*; covers RIPv2 and RIPng), `vxlan` (label
*VXLAN*: netlab's VXLAN **module** only; a containerlab link of type `vxlan` in a topology is unaffected) and
`evpn` (label *EVPN*, status *under review*: unavailable until a real transport path exists).

### Context (`GET /api/labs/{id}/design`, and every view returned by save, clear, renumber, import)

| Field | Meaning |
|---|---|
| `modules` | The modules a student may choose (`AUTHORING_MODULES`): the old list without the four. Offer only these. |
| `retired` | `{module id: reason}`. The reason is the full student sentence (show it as is). |
| `retired_status` | `{module id: 'retired' \| 'under_review'}`: `under_review` for `evpn`. Suggested wording: *Retired* / *Unavailable (under review)*. |
| `retired_labels` | `{eigrp: 'EIGRP', ripv2: 'RIP', vxlan: 'VXLAN', evpn: 'EVPN'}`. |
| `retired_in_design` | `[{path, module, message}]`: where the **saved** design still uses a retired module (empty for a new design). Show it as a notice: kept and readable, no new plan from it until removed. |
| `capabilities` | The capability matrix with the product policy: a retired capability's row has `level: 'retired'`, `policy: 'retired' \| 'under_review'`, `reason` = the retirement reason, and the engine's own answer in `engine_level`. Rows of other capabilities are unchanged (no `policy` key). Word `retired` as *Retired* (or *Unavailable (under review)* when `policy` is `under_review`), never as *not supported*. |
| `catalogue` | Each entry gained `retired` (the reason, or `''`) and `policy` (`'retired'`, `'under_review'` or `''`). The retired capability ids are `eigrp`, `ripv2`, `ripng`, `vxlan`, `evpn`. |

`problems` of the view is unchanged: an old design that uses a retired module is *not* invalid (the view of an old
design shows no invented problems); `retired_in_design` is where it shows.

A plan's `compatibility` rows (generation record) gain the same `level: 'retired'`/`policy`/`engine_level` only for
plans generated from now on, which cannot carry a retired module; plans made before keep their stored rows (with
the engine's levels), so the page should also check `retired` against each row's `feature` (`ripng` belongs to
`ripv2`) when it renders an old plan.

### Save `PUT /api/labs/{id}/design` (`{intent, revision}`)

- Unchanged: 409 stale revision (string), 400 validation problems (**string**, `'Fix the design first: …'`).
- New: **400** with `{message, problems, retired}` when the intent uses a retired module that the saved design does
  not already use at the same path. Keeping an existing use and removing one are always allowed, so an old design
  can still be edited and saved. Example message: *RIP is no longer offered, so it cannot be added to a design.
  Remove it and save again; a design that already used it keeps working as it is.* For EVPN the verb is *is not
  available*.

### Import `POST /api/labs/{id}/design/import` (multipart `intent`, `revision`)

- Unchanged: 200 `{imported: false, problems}` for validation problems; 400 string for an unreadable file; 409
  stale revision.
- New: **400** `{message, problems, retired}` when the file adds a retired module compared with the saved design.

### Validate `POST /api/labs/{id}/design/validate` (`{intent, revision}`)

`{problems, valid, retired: [{path, module, message, new}]}`. `valid` still reflects `problems` only. `new: true`
marks a use the saved design does not have: Save would refuse it. Any entry at all means Generate will refuse.

### Generate `POST /api/labs/{id}/design/generate` (`{revision}`)

- Unchanged 409 strings: no saved design, stale revision, no topology, a plan already generating, storage reset.
- New: **409** `{message, problems, retired}` when the saved design uses any retired module. Nothing is queued.
  Message example: *This design uses VXLAN and EVPN, which are no longer offered or not available, so no new plan can
  be generated from it. Remove them from the design to generate again. Earlier plans, the saved design file and its
  export are kept.*
- Changed: the **400** for validation problems is now structured: `{message, problems}`. `message` is the exact
  former string (`'Fix the design first: path: message; …'`, first five problems), `problems` lists all of them.

### Apply (review and submit) of a plan that carries a retired module

`POST …/generations/{gid}/review` and `POST /api/labs/{id}/design/apply` answer **409** with a **string** when the
plan's `modules` or any device's compatibility features include `eigrp`, `ripv2`, `ripng`, `vxlan` or `evpn`
(plans generated before the retirement included), e.g. *This plan uses VXLAN, which is no longer offered, so it
cannot be applied to devices. The plan stays viewable and downloadable; remove it from the design and generate a new
plan to apply.* The page can predict this from the plan record (`modules`, `compatibility`) and disable *Apply to
devices…* with that sentence.

Untouched: reading, export, download, history, *Export plan to Git…*, *Remove design*, *Renumber*, ownership and its
removals (a new plan without VXLAN removes the owned VXLAN statements through the normal review and apply), and the
restart reconciliation. Nothing changes a device by itself.

## 8e: device review as a job

### Start: `POST /api/labs/{id}/design/generations/{gid}/review`

Body `{targets: [name], takeover: [name], request_id?: hex(16–64)}`. Send a fresh `request_id` per click (for
example 32 hex characters); retrying the same click with the same `request_id` returns the same job.

There is **one behaviour**: the endpoint always starts a job. A request without `request_id` also gets a job (it just
is not idempotent). The old synchronous body (token and per-device report in the POST answer) is gone; it now
arrives as the job's `review` when the job is done.

Checked synchronously, before any device is contacted, with the same statuses and string details as before: 400
duplicate target, 404 unknown lab or plan, 409 busy (backup, Git save, restore, lab operation, design apply, storage
reset), 409 plan not generated, 409 retired module (above), 409 plan older than the design or topology, 409 stale
discovery, 409 *None of the selected devices can be applied to: …*.

Additional synchronous answers:

| Status | Detail | Meaning |
|---|---|---|
| 409 | `{message, review_job_id}` | A review of this lab is already running. Attach to `review_job_id` (GET below) instead of starting another. |
| 409 | string | The `request_id` belongs to a review of another lab or plan. |

Success **200**:

```json
{"review_job": {"id": "<32 hex>", "request_id": "<as sent or ''>", "lab_id": "…", "generation_id": "…",
  "status": "running", "message": "Reviewing the selected devices.", "started": "<ISO time>", "finished": null,
  "progress": {"settled": 0, "total": 2}, "takeover": [],
  "targets": [{"name": "ceos", "kind": "arista_ceos", "stage": "queued", "timeline": {"queued": 1759480000.12}},
              {"name": "host1", "kind": "linux", "stage": "not_eligible", "timeline": {}, "reason_code": "not_eligible",
               "message": "A support host is generated only, never applied."}],
  "server_time": 1759480000.15}}
```

### Follow: `GET /api/labs/{id}/design/review-jobs/{job_id}`

Same object as `review_job` above (not wrapped), plus `review` **only when `status` is `done`**. `review` is exactly
the former synchronous response: `{token, expires_in, generation_id, targets: [per-device report], applicable}`.
The token is single-use, valid `expires_in` (600) seconds from the job's end, and `POST …/design/apply` still needs
it (with the same take-over choice) as before.

404 (string) when the job is unknown, belongs to another lab, or expired. Poll about once a second while `running`.

### List: `GET /api/labs/{id}/design/review-jobs`

The lab's kept jobs (running, or finished less than 600 s ago), newest first, **without** `review`. Use it after a
reload to find a running review and attach to it.

### Job status

| `status` | Meaning | Suggested student wording |
|---|---|---|
| `running` | Devices are being reviewed. | *Reviewing N devices…* |
| `done` | Every device settled; `review` (and its token) is present. Devices may still have failed individually. | *Review finished* |
| `failed` | The job could not produce a review (`message` says why, e.g. *VM connection changed. Review again.*); no token. | *The review could not finish* + `message` + *Review again* |
| `interrupted` | The manager stopped during the review; no token. | *The review was interrupted. Review again.* |

### Device stages (`targets[].stage`)

Recorded at the real call sites of the review transaction, each with its epoch time in `timeline[stage]`
(`timeline.settled` is set when the device reaches a final stage). Elapsed time is `server_time - timeline[stage]`.

| Stage | Real step | Suggested wording |
|---|---|---|
| `queued` | Waiting for a free connection slot (up to four devices at a time) | *Waiting* |
| `connecting` | Opening SSH (up to three attempts) | *Connecting…* |
| `checking_pending` | Settling an unknown earlier outcome if there is one, and checking for a change waiting for confirmation | *Checking for unconfirmed changes…* |
| `rendering` | Letting the device render the generated configuration | *Preparing the configuration…* |
| `reading_config` | Reading the running configuration | *Reading the current configuration…* |
| `staging` | Staging the whole change inside the NOS transaction, then aborting it | *Trying the change (nothing is committed)…* |
| `restaging` | Only when taking over an exclusive setting: staging once more with its removal | *Trying again with the take-over…* |
| `done` | Reviewed; the report is in `review.targets` | *Reviewed* |
| `failed` | Not reviewed; `reason_code` and `message` say why | `message` |
| `unreachable` | SSH could not be opened | *Could not be reached* |
| `not_eligible` | Never contacted; `message` is the eligibility reason | `message` |

`reason_code` (with the fixed `message` the backend sends):

| `reason_code` | Stage | `message` |
|---|---|---|
| `unreachable` | `unreachable` | The device could not be reached over SSH. |
| `auth` | `failed` | The device rejected the login credentials. |
| `pending_change` | `failed` | Another change is waiting for confirmation on this device. |
| `device_refused` | `failed` | The device refused the staged configuration during the review. |
| `connection_lost` | `failed` | The connection to the device was lost during the review. |
| `plan_files` | `failed` | A generated file of this plan is missing or changed; generate the plan again. |
| `timeout` | `failed` | The device did not finish the review in time. (540 s budget per job) |
| `interrupted` | `failed` | The manager stopped before the review of this device finished. |
| `internal` | `failed` | The review failed inside the manager for this device. |
| `not_eligible` | `not_eligible` | the eligibility reason |

A job view never carries configuration text, device output, addresses or secrets; the per-device detail (diff,
conflicts, masked statements) is only in `review`, as before.

### Rules for the page

- Closing the dialog is **not** cancel. There is no cancel route; the job finishes on its own. Reopening the dialog
  (or reloading) attaches to the running job: by the stored `review_job_id`, by the 409 detail, or by the list.
- Start a review with a new `request_id`; a retry of the same request (network error) reuses it.
- While a review of a lab runs, an apply submit for that lab answers 409 (string) *The devices of this lab are being
  reviewed; wait for the review to finish, then apply.*
- Review jobs live in memory. After a manager restart a job (and its token) is gone: GET answers 404; tell the
  student to review again.
- *Retry* after `failed`, `interrupted`, or devices that failed means starting a new review (new `request_id`).

### JavaScript tests that pin the old synchronous shape

`tests/test_network_design_ui.js` drives the review dialog with the synchronous response (token in the POST body);
those cases must be rewritten against the job shape above by the UI owner.
