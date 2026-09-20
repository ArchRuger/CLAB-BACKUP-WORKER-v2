# Lab builder quality pass: findings register

Branch `claude/lab-builder-quality-pass` (from `main` 5e9aa86, release 1.30.0). Started 2026-09-20.
Scripts, screenshots and reviewer reports are outside the repository in `~/research/lab-builder/qa/`
(`walk/` = exploratory browser scripts and shots, `baseline/` = the 38-check workflow before any change,
`integrity-review/`, `helper-review/`). Evidence is **fixture** (fixture manager on :8090) unless it says **live**.

Classes: DEFECT (confirmed), USABILITY, TEST (a check that does not prove its claim), HYPOTHESIS, ENHANCEMENT.
Status: open / fixed (commit) / wontfix (reason) / blocked (reason).

| Id | Class | Sev | Journey | Summary | Status |
|---|---|---|---|---|---|
| F-1 | DEFECT | high | B, D | Renaming the lab in the editor's Lab settings splits the names | open |
| F-2 | DEFECT | low | B | Palette "Import templates" does nothing | open |
| F-3 | DEFECT | high | F | A save whose answer is lost leaves the draft "not on the VM yet" with no way forward | open |
| T-1 | TEST | medium | E | `student_workflow.py` "refused while deployed" passes on the review's own text | open |
| S-1 | BLOCKED | — | security | Independent helper security review was stopped by the model's safety filter | blocked |

## F-1 Renaming the lab in the editor splits the names

Editor toolbar → Lab settings → Lab Name → Apply. The YAML gets `name: <new>`; the draft record, the
manager's bar, the Drafts list, the download file name and the page title keep the old name
(`walk/w2_controls.py`, `walk/w3_rename_save.py`). A first save then creates `<root>/<new>/<new>.clab.yml`
while the bar still says the old name, and the page's own "already in My labs" / "already a draft" name
checks never saw the new name. On a lab opened from the VM the rename is only refused at the save
(`The lab name cannot change when saving again`), after the student has kept working.
Files: `lab-builder-page.js` `builderPage.persist`, `draftStatus`, `builderRenderBar`.

## F-2 Palette "Import templates" does nothing

`main.tsx` answers `importCustomNodes` with `nothing`; the button is visible beside a working
"Export templates" (`walk/w5_dead.py`: no file chooser, no message).

## F-3 A save whose answer is lost has no way forward

Reproduction (`walk/w6_lost_response.py`): save a new lab, drop `vm` from the stored draft (what a closed
tab or a lost poll leaves), reload. Status: "not on the VM yet". Save again, unchanged: the helper answers
`already_published` without `published_path`, `opJobDone` ignores it, the banner says "succeeded" and the
status still says "not on the VM yet". Edit, save again: a six-second toast "A lab folder with this name
already exists on the VM … Choose another lab name." The student's work is safe in the draft but nothing on
the page says that the folder is their own earlier save, or how to continue (Edit visually on the VM file).
Files: `host_operations.py` `publish` (result of the `published` state), `lab-builder-page.js` `opJobDone`,
`builderSave`.

## T-1 "refused while deployed" check is vacuous

`student_workflow.py` step 5 accepts the word "deployed" anywhere in the body; the revise review's own copy
contains it ("Only possible while the lab is not deployed"). In `baseline/11-refused-while-deployed.png`
the review is open, i.e. nothing was refused at that moment (the fixture's discovery had not seen the
deploy yet).

## S-1 Helper security review blocked

A fresh reviewer briefed for symlink / race / preview-binding analysis of `host_operations.py`
`publish` / `revise` / `delete` was terminated by the model's safety filter before reading anything. Not
retried under another wording or model. The helper's new actions therefore have **no independent security
review from this pass**; any helper change made here is kept minimal and covered by unit tests.
