# Reproduction 1: nested `latest` — evidence

QA operator run against the **running deployed manager 1.30.30** (not rebuilt, not restarted) and the
real lab `restore-square` (id `904a35a79dc341ce8a4638f83fc34185`), through the product only: the
browser's Progress tab (Playwright, `docs/save-location-fix/tools/repro_nested_latest.py`), the
mandatory review-before-upload dialog, and same-origin API calls issued the same way the page itself
issues them. Full raw records are in `00-repro-nested-latest.json`; this file is the readable step
table. Result: **PASS — the bug reproduces** exactly as described in `docs/save-location-fix/PICKUP.md`
"Findings": a lab folder that is itself a reserved snapshot child (`…/working/latest`) is accepted as a
destination once its parent's registration is retired, and the next Save Latest nests a second `latest`
inside it.

Environment note: the checkout `~/labs/CLAB-MNGR-DEV-LLM` had 4 pre-existing local commits not yet on
`origin/main` and one pending `committed` Git job for this lab; both had to be cleared (a plain
`git push origin main`, and `POST /api/git/jobs/70789a7131e8427f87f6bcb3a4da700d/dismiss
{"acknowledge": true}`) before the manager's own destination-change validation (`register()` in
`host_git.py` requires local HEAD to equal the verified remote HEAD) would proceed. One transient
device-read miss (`capture_incomplete`, job `39aceddf2fe9975494eac97b6e52ad80`) occurred on the very
first Save Latest attempt; all four nodes' `readiness` read `Ready` again within the retry window and
it left no commit and no changed `latest` — an environment flake, unrelated to either reported bug.

## Step table

| Step | What was done | Through | Request / action | Result | Evidence |
|---|---|---|---|---|---|
| a | Destination → `save-fix/working` | API (`curl`, same-origin headers) | `POST /api/labs/<lab>/git/destination {"prefix":"save-fix/working","move_files":false}` | `200`, binding `6ea219554263445f8f5cd9a7f57b3578`, prefix `save-fix/working` | JSON `steps.a_change_destination_to_save-fix/working` |
| b | Save Latest (1st save) | **Real browser**: Progress tab → Save progress → review dialog → Upload these changes | `POST /api/git/jobs/<id>/retry {"push":true,"reviewed":true}` | Job `7e98c025264aad61c1e7a56ab87928d0` **synced**, commit `4fa25780…`, `snapshot_path` = `save-fix/working/latest` | `00-b1-before-save.png`, `00-b2-review-dialog.png`, `00-b3-job-result.png` |
| — | Independent verify | `git -C ~/labs/CLAB-MNGR-DEV-LLM fetch origin && git ls-tree -r --name-only origin/main -- save-fix` | — | local HEAD == `origin/main` == `4fa25780…`; 9 files under `save-fix/working/latest/` | JSON `steps.b….git_verification` |
| — | Helper journal | `~/labs/CLAB-MNGR-DEV-LLM/.git/clab-manager/journals/7e98c025264aad61c1e7a56ab87928d0.json` | — | `snapshot_path`=`save-fix/working/latest`, `status`=`synced`, 9 `changed_files` | JSON `steps.b….helper_journal` |
| c | Move away, no file move | **Real browser**, same-origin `fetch` from the page context (same request `gitApplyDestination` sends) | `POST /api/labs/<lab>/git/destination {"prefix":"save-fix/elsewhere","move_files":false}` | `200`; registration for `save-fix/working` retired; binding prefix now `save-fix/elsewhere` | JSON `steps.c_move_away_without_moving_files` |
| d | Change folder… → browse to `save-fix/working/latest` | **Real browser**: Progress tab → Save location → Change folder… → outline `save-fix` → `working` → `latest` | selection only (no request yet) | **"Save this lab here" is ENABLED** on a folder that holds `manifest.json` and is itself named `latest` (the reported defect) | `00-d1-places-panel.png`, `00-d2-save-here-enabled.png` |
| d | Confirm | **Real browser**: click Save this lab here → confirm dialog → Save here (move box not offered: 0 files under `save-fix/elsewhere`) | `POST /api/labs/<lab>/git/destination {"prefix":"save-fix/working/latest","move_files":false}` | Dialog text itself: *"restore-square will keep its progress in CLAB-MNGR-DEV-LLM › save-fix/working/latest from now on."* Registry (`sudo cat /etc/clab-manager/git.json`) confirms the only `save-fix` entry afterward is prefix `save-fix/working/latest` | `00-d3-confirm-dialog.png`, `00-d4-destination-line.png` |
| e | Save Latest again | **Real browser**: Save progress → review dialog → Upload these changes | `POST /api/git/jobs/<id>/retry {"push":true,"reviewed":true}` | Job `cfd2de958d1739fbeee82a6957fdc8a7` **synced**, commit `94944cf6…`, **`snapshot_path` = `save-fix/working/latest/latest`** (nested — the bug) | `00-e1-review-dialog.png`, `00-e2-job-result.png` (banner literally says *"Saving to CLAB-MNGR-DEV-LLM › save-fix/working/latest"*, dialog *"Progress saved to Git"*) |
| — | Helper journal | `.../journals/cfd2de958d1739fbeee82a6957fdc8a7.json` | — | `snapshot_path`=`save-fix/working/latest/latest`, `status`=`synced`, 9 `changed_files` | JSON `steps.e….helper_journal` |
| — | Independent verify | `git fetch origin && git ls-tree -r --name-only HEAD -- save-fix` (local) and `... origin/main -- save-fix` | — | Both list `save-fix/working/latest/latest/manifest.json` (**new**) *and* `save-fix/working/latest/manifest.json` (**still present**); local `HEAD` == `origin/main` == `94944cf6…` | JSON `steps.e….git_verification.ls_tree_save-fix` |
| — | Blob comparison | `git log -- save-fix/working/latest/manifest.json` and `git ls-tree HEAD --` on both paths | — | Parent `manifest.json` blob `b0baf92d…` was written **only** by commit `4fa2578` (step b) and is unchanged at `HEAD`; nested `latest/manifest.json` blob `c99db469…` was created fresh by commit `94944cf` (step e) | JSON `steps.e….git_verification.manifest_blob_comparison` |
| f | Reload + save once more | **Real browser**: page reload, Save progress (device config unchanged, so the manager reports `unchanged` with no new commit and no dialog — read back from `/api/labs/<lab>/git`) | `POST /api/labs/<lab>/git/save {"target":"latest","push":true}` (page's own `gitSaveProgress`) | Job `e586740b…` **unchanged**, `snapshot_path` stays `save-fix/working/latest/latest` | `00-f1-reload-save-job.png` |
| f | Direct API save, fresh `request_id` | Same-origin `fetch` (equivalent to `curl … -H Origin: http://127.0.0.1:8081`) | `POST /api/labs/<lab>/git/save {"target":"latest","push":false,"request_id":"745fe1dae18581ecc48a3611cef0f13d", ...}` | Job `745fe1da…` **unchanged**, `snapshot_path` stays `save-fix/working/latest/latest`; helper journal agrees | JSON `steps.f_reload_and_save_again_stays_nested.direct_api_save` |

## What did NOT reproduce cleanly (script artifacts, not product behaviour)

- The automated destination-line text check in step d raced the UI's asynchronous re-render and read
  the *old* text once; the confirm dialog's own text, the VM registry, and the next save's resolved
  `snapshot_path` (step e) all independently confirm the destination really became
  `save-fix/working/latest`. The polling bug in the check was fixed in the committed tool (see the tool's
  own comment) but not re-run live, to avoid a second unnecessary round-trip through all four devices.
- One transient `capture_incomplete` (a device momentarily not answering) on the very first Save Latest
  attempt — unrelated to either reported bug; retried successfully once readiness settled.

## Final state (left deliberately, per the assignment)

- Lab `restore-square` is bound to prefix **`save-fix/working/latest`** (the nested, legacy
  destination) — kept as-is because this state is wanted for testing the fix.
- Repository `~/labs/CLAB-MNGR-DEV-LLM`: local `main` and `origin/main` are in sync at
  `94944cf6c3f9e134ba9041327cdb3a5218db065f` (verified with `git fetch` + `git rev-parse`).

## Tooling

`docs/save-location-fix/tools/repro_nested_latest.py` — rerunnable; supports `--skip-bc` (resume after
steps b/c) and `--only-f` (resume after steps b–e) for exactly this kind of phased, evidence-checked
run. Needs `clab-backup-ui/.venv/bin/python` with `LD_LIBRARY_PATH=$HOME/.local/lib/chromium-deps` set.
