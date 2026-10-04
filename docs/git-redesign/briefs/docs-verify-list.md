Claims in the rewritten guides that their authors could not verify (collect here; one verification pass after the tab removal and the live pass):

GIT-PROGRESS.md (D1)
- The owner's recovery when the online copy and the VM both have changes (section "When saving is not possible"): no commands spelled out; a hand merge may still not upload (the helper pushes only journaled commits). L1 step 11 finds the real recovery: quote it.
- A lab state saved into `BGP/start` is written as `BGP/start/latest/…` (worked example relies on it).
- "Name of this save" field and Keep as a checkpoint: D1 wrote "only in the Saved view of an automatically named save"; I1 changes this (finished save shows both regardless): update the two sections.
- The Load list shows the latest save and the three newest checkpoints, capped at eight lab states (constants in load.js).
- Carried over unverified: IOS XR banner refusal, Junos root-authentication synthesis, legacy-snapshot versions.
- Apostrophes: `Can’t save` curly in status.js; `See what's different` straight in the Load confirmation, curly elsewhere: make the page consistent (S11) then the guide.
- Q1 "Use this folder anyway disconnects the other lab and connects this one; a waiting save of it stays part of the next upload": check against git_place.py `take`.

GIT-SETUP.md and friends (D2)
- scaffold-lab.py against the new save model (not run; L1 step 17 runs it).
- NAMING.md: authoring Start/Broken/Final follows DESIGN 2.9 and the button strings; not exercised in a browser.
- "the manager picks a folder that avoids another lab's saved state" from DESIGN 2.1.
- `Uploaded: yes` chip text from save-header.js.
- NAMING.md "(a save that still waits for upload refuses the folder change)" in the scaffold section: old model; check what the tool meets now.

D3
- COURSE-STATES.md: a state's name appears as typed (state_mark) vs. capitalised folder name; one-click names; mgmt-ipv4 difference "can lose contact".
- STUDENT-GUIDE-GAPS.md rows marked "check live".
- NETWORK-DESIGN.md: "Advanced › Experimental" wording for the Design entry.
- Screenshots to retake: docs/images/ui/10,11,13,20,40,41,44,45,51 (old header); 30-progress, 34-saved-version, 36-restore-review, docs/images/progress-saved-versions.png, docs/images/restore-review.png (removed tab). README.md lines 40 and 46 alt texts.

Page wording still naming the tab (for S11): operations.js "Save progress first"; git-progress.js exposure tick-box strings, "Progress › Recent saves" (663, 695), the Disconnect dialog (814) says to upload or Keep snapshot only before disconnecting although a waiting save may stay; git-places.js "Save progress writes…" (136, 145) and an "Apply to running lab…" button (184).
DESIGN.md 3.6 lacks a row for the `settings` code (`No device of this lab is selected for saving.`): add.
