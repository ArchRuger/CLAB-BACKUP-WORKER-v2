# Lab builder quality pass: findings register

Branch `claude/lab-builder-quality-pass` (from `main` 5e9aa86, as of 1.30.0), 2026-09-20, dev VM
`clab-llm-dev2`. Scripts, screenshots and logs are outside the repository in `~/research/lab-builder/qa/`:
`baseline/` (the workflow before any change), `walk/` (exploratory browser scripts `w1`–`w15` with
`shots*/`), `after1`–`after3/` (workflow runs), `verify-after/` (main-app gate), `live1/`, `live2-lan/`,
`live-nos/` (live manager), `integrity-review/` and `final-review/` (the reviewers' experiment scripts).

Evidence is **fixture** (fixture manager, VM answered in-process) unless it says **live**.
Classes: DEFECT, USABILITY, TEST (a check that did not prove its claim), NOTE. Every id below is fixed and
verified unless the status column says otherwise.

| Id | Class | Sev | Journey | Summary | Status |
|---|---|---|---|---|---|
| F-1 | DEFECT | high | B, D | A lab renamed in the editor's Lab settings: the page kept the old name | fixed |
| F-2 | DEFECT | low | B | Palette *Import templates* did nothing | fixed |
| F-3 | DEFECT | high | F | A save whose answer was lost left the draft "not on the VM yet" with no way forward | fixed |
| F-4 | USABILITY | medium | A, F | *Save to the VM* greyed without a reason (VM not connected, capabilities unknown) | fixed |
| F-5 | DEFECT | high | C, F | After a failed store the page handed out the previous draft as the current one | fixed |
| F-6 | USABILITY | low | F | "Failed to fetch" when the manager is away; a draft did not open without the manager | fixed |
| F-7 | USABILITY | low | C | A `#draft=` link to a draft that is not in this browser showed nothing | fixed |
| F-8 | DEFECT | medium | C | A draft file with unreadable YAML opened as an empty canvas, without a word | fixed |
| F-9 | NOTE | — | packaging | `assets/main.js?v=<release>` is cached `immutable` without a content hash | release number moved |
| F-10 | DEFECT | medium | B | (own regression, found live) palette templates lost the site's images | fixed |
| F-11 | USABILITY | medium | F | A failed deploy for a missing image only showed containerlab's raw output | fixed |
| F-12 | DEFECT | medium | D, G | The folder browser stayed open over the lab page after a confirmed deploy | fixed |
| F-13 | USABILITY | medium | all | Review dialog: confirm row below the fold; builder bar: Save off-screen at 150 % zoom | fixed |
| U-1 | USABILITY | low | A, B | An empty canvas gave no hint how to begin | fixed |
| U-2 | USABILITY | medium | A | With no labs, the first page never mentioned the builder | fixed |
| I-4 | DEFECT | high | E | YAML with a syntax error or a repeated key: every edit acknowledged, none written | fixed |
| I-6 | DEFECT | medium | E, F | A draft whose VM base is stale could never be saved | fixed |
| I-7 | DEFECT | low | E | A file with a byte-order mark could be opened but never revised | fixed |
| I-8 | DEFECT | medium | C, E | One lab in two drafts that drift apart | fixed |
| I-9 | DEFECT | low | C | Revision counter restarted after delete and re-create: silent overwrite from another tab | fixed |
| I-11 | DEFECT | low | D | *Preview topology* and *Edit visually…* dead in the Topology file dialog on the builder page | fixed |
| I-13 | USABILITY | low | D | "must contain topology.nodes" for an empty lab; a truncated diff without a marker | fixed |
| I-14 | DEFECT | low | C | A browser that refuses storage: raw error text, Drafts button dead | fixed |
| R-1 | DEFECT | **high** | E | **Opened as `http://<VM address>` there is no `crypto.subtle`: every second save threw a TypeError** | fixed, **live** |
| R-2 | DEFECT | medium | F | "Editing is paused" was not true: keyboard edits went through under the overlay | fixed |
| R-3 | DEFECT | medium | all | (own regression) the sticky review row hid a failed confirm; 6 px side scroll below 900 px | fixed |
| R-4 | DEFECT | medium | F | The lost-save marker was dropped when the VM could not be asked, or after further edits | fixed |
| R-5 | DEFECT | low | E | Opening from the VM crashed after a transient read failure; a failed layout read passed for "no layout" | fixed |
| R-6 | DEFECT | low | E | The VM's hashes were dropped when a VM version was adopted | fixed |
| R-7 | DEFECT | low | B, C | Rename bookkeeping: duplicate check by id, stale path and name | fixed |
| R-8 | USABILITY | low | C | Without browser storage the page's own reloads wiped the drafts unasked | fixed (asks first) |
| R-9 | DEFECT | low | F | A second Save while the first job still ran dropped its outcome; ten failed polls ended silently | fixed |
| R-10 | DEFECT | low | F | *Review the differences…* on a folder that carries another lab's name bound the draft to it | fixed |
| R-11 | DEFECT | low | E | Two old drafts on one file: opening failed with "changed in another tab" | fixed |
| R-12 | USABILITY | nit | A | Save off without a reason while capabilities load | fixed |
| R-13 | DEFECT | nit | B | An imported default template starred a second template | fixed |
| R-14 | NOTE | nit | packaging | `yaml` imported by `main.tsx` without being a declared dependency | fixed (pinned) |
| D-1 | DEFECT | medium | E | (own regression, second review) opening the VM version could discard an older draft with unsaved changes unasked | fixed |
| D-2 | DEFECT | low | F | A state refresh that failed right after the confirm left Save blocked until reload | fixed |
| D-3 | DEFECT | low | F | *Try to store it again* did nothing when it was the page's own write that failed | fixed |
| D-4 | DEFECT | low | F | The path of a save was not remembered: a rename after a lost answer orphaned the lab on the VM | fixed |
| D-5 | USABILITY | low | C | Opening a draft file could remove two same-named drafts after one question, and deleted before it wrote | fixed (writes first, says how many); two unsaved drafts may still share a name after a rename, which the save then refuses |
| T-1 | TEST | medium | E | `student_workflow.py` "refused while deployed" passed on the review's own wording | fixed |
| T-2 | TEST | low | G | `verify_after.py` expected the Topology file dialog without *Edit visually…* (stale since 1.30.0) | fixed |
| T-3 | TEST | medium | D | `student_workflow.py` "the deploy job succeeds" was `True`, and its wait matched the previous job's banner | fixed |
| S-1 | BLOCKED | — | security | Independent security review of the helper's `publish` / `revise` / `delete` | **not done** |
| L-1 | NOTE | — | live NOS | cJunosEvolved did not boot on the first deploy of the builder-made lab (>40 min); it did after one redeploy | environment, verified after redeploy |
| E-1 | NOTE | — | environment | The dev VM's capture session service still runs the image of an earlier release | open, not touched |
| I-15 | NOTE | low | E | After a revision My labs takes the builder's layout, also over a map arranged in the manager | by design, documented |
| I-12 | NOTE | low | B | The icon dialog's custom-icon upload does nothing (`uploadIcon`); `runLifecycle` answers "success" | open, low |

## The defects that mattered, with their causes

**R-1 (high, found by the final reviewer, reproduced live).** `builderHash` used `crypto.subtle`, which
browsers give to secure contexts only. The manager is normally opened as `http://<VM address>:8081`
(QUICK-INSTALL says so), where it is `undefined`: the first save worked, *Save changes to the VM…* threw
`Cannot read properties of undefined (reading 'digest')` into a six-second toast, for ever. Every earlier
validation ran on `127.0.0.1`, which is a secure context. Fix: `builderSha256()` (plain JavaScript, checked
against Node's SHA-256 for eight inputs) runs when `crypto.subtle` is missing, and the VM's own hashes are
kept wherever a VM version is read. Live evidence: `isSecureContext false`, `typeof crypto.subtle
'undefined'` on `http://192.168.132.132:8081`, and the 40-check workflow including the revision passes
there (`live2-lan/`).

**F-5 / R-2.** `persist()` assigned `builderDraft` only on success, so after a failed `draftWrite` the bar,
*Download draft*, *View YAML* and *Save to the VM* all used the previous version while the message said
"Download the draft". Now the editor's texts are held in `builderUnstored`; the pill, the overlay and Save
follow it; while the overlay is up `persist()` refuses to store (`builderPaused`) and `#root` is `inert`.
Before / after: `walk/shots/w7-B-storage-full.png`, `walk/shots-after2/` (w9), test *a change the browser
could not store…*.

**F-3 / I-6 / R-4 / R-9.** The only way a save reached the draft was an open output dialog whose poll
succeeded at the right moment; `already_published` carried no path and was ignored; a refusal was a toast.
Now: `saving` marker with the hashes of what was sent, `opJobStarted` / `opJobDone` / `opJobLost`,
`opShowJob` follows the job with the dialog closed (builder page only) and repeats failed polls,
`builderReconcile()` on the next visit (kept while the VM cannot be asked), and `builderSaveRefused()`:
a dialog that stays, with *Open the VM version* and *Review the differences…* when the VM holds another
version of this lab. Before / after: `walk/shots/w6-*`, `walk/shots-after2/w9-05-refused-dialog.png`,
`w9-06-rebase-review.png`.

**I-4.** The editing engine acknowledges commands on a YAML document with parse errors and writes none of
them (measured by the reviewer in Node: `addNode → ack`, YAML unchanged, layout written). PyYAML accepts a
repeated key, so such a file passed the manager's check and opened. `main.tsx` now parses the draft with
the bundled `yaml` library first and refuses it with the first error (`w9-07-duplicate-key.png`).

**F-10 (own regression, caught live).** Opening the local draft before the manager answered made the
editor take its templates before the known images arrived; the multi-vendor lab built on the live VM got
`cjunosevolved:26.2R1.7-EVO` instead of `n24l/cjunosevolved:26.2R1.7-EVO` and its deploy failed. The
editor now mounts after the manager was asked (five-second cap). The failed deploy became the live test of
the recovery journey (F-11): the output names the two images, *Edit visually…* corrected them, the revision
was saved with a recovery copy and the lab deployed.

## Not done, and why

- **S-1.** A fresh reviewer briefed for an adversarial review of `host_operations.py` (`publish`, `revise`,
  `delete`) was stopped by the model's safety filter before it read anything. It was not retried under
  another wording or model. This pass changed no helper code; the helper still has no independent security
  review beyond the one made before its release.
- **L-1 (resolved).** In the builder-made lab `qa-nos-105458` (2 × cEOS, cJunosEvolved, vJunos-switch) the
  cJunosEvolved node did not answer SSH within 40 minutes of the first deploy (no soft lockups in its log, last
  line `Launching /sbin/init`; this host showed the same hang on 2026-09-18 with a lab that is not the
  builder's). After one *Redeploy* through the manager it was ready, and all four links were proven by LLDP
  on the devices (`live-nos/wiring-check-3.txt`). Cisco XRv9k is not on this VM: its pattern stays unverified.
- **E-1.** `clab-manager-capture-sessions-1` runs an image built for an earlier release because the manager
  was upgraded with `docker compose up --build` instead of `start-manager.sh`. A capture session that is not
  this pass's was running, so the capture stack was left alone (`start-manager.sh --manager-only`). Capture
  discovery through the manager answered for the builder-made lab.
- Not covered by a unit test: the `opJobStarted` call inside `opReview` and `opJobLost` after ten failed polls
  (both exercised by the browser runs only); the ≤900 px rule of the sticky review row was checked in a
  browser at 911 px, not below.
- No student took part. Everything here is a browser walkthrough, failure injection and review.
