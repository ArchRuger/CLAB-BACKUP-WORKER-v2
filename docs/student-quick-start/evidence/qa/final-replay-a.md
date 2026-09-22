# Final acceptance replay — Scenario A (use a lab your instructor gave you)

Agent simulation (this was not a human student session): Claude agent acting as
mock student, replaying the guide's steps verbatim against a live manager and
lab VM, verifying independently after the guide's own steps.

PDF under test: `docs/student-quick-start/evidence/qa/guide-under-test.pdf`
SHA-256 `e53aa7b9af2f2542a7dd40b7e0b056dca1612586f3ff509f2b7bf03a2a1d475d` (verified
with `sha256sum` before reading; matches the assignment). Read with
`pdftotext -layout`; pages viewed as images with `pdftoppm` only where a figure
mattered for a judgement call (none needed for Scenario A beyond what the text
already stated precisely).

Manager: `http://127.0.0.1:8081` (release 1.30.35). Repository substitution:
`https://github.com/pruger-dev/netlab-course-qa2.git` in place of
`netlab-course-student.git`. Browser: Playwright/Chromium, one fresh context
for the whole scenario, closed and reopened fresh for step A11 (viewport
1366×900). Device CLI: the manager's own browser terminal (Open CLI), typed as
a student. Independent verification: `gh api repos/pruger-dev/netlab-course-qa2/...`
(read-only) after each upload.

Start: 19:57:08. End: 20:09:02. Total: ~12 minutes.

## Step-by-step

| Step | Result | Finding |
|---|---|---|
| A1 Open the manager | Pass — Home shows Deploy/Build boxes, "No labs yet" | — |
| A2 Deploy the lab | Pass — Topology file dialog matched Figure A.2a exactly; Start review text matched verbatim; confirmed | — |
| A3 Wait for ready | Pass — "Starting lab / 0 of 2 devices ready" then "Running / 2 of 2 devices ready" | — |
| A4 CLI on r1 | Pass — `show version` shows platform; Et1 `connected`; `show ip interface brief` lists only Management0 | — |
| A5 Connect repository | Pass — destination line reads exactly "link-basics saves to netlab-course-qa2 › link-basics/work › latest/"; three instructor rows present with exact paths | — |
| A6 Load starting configuration | Pass — review source line verbatim "Source: Starting state · netlab-course-qa2 › link-basics/reference/start/latest · saved … · \<commit\>"; both devices "6 differences"; ping succeeded after replace | — |
| A7 Change on r1 | Pass — Loopback0 10.255.0.1/32 read back | — |
| A8 Save progress | Pass — review listed all 4 files "added"; after upload, Latest row read "netlab-course-qa2 › link-basics/work › latest · Saved just now · 5 files"; `gh api` confirms exactly 5 files at `link-basics/work/latest/` | — |
| A9 Checkpoint, then r2's loopback | Pass — checkpoint `loopback-added` created and uploaded; second save review showed only r2 files; `gh api` confirms `link-basics/work/latest/r2.cfg` has Loopback0 and `link-basics/work/checkpoints/loopback-added/r2.cfg` does not, no nested `latest/latest` | Cosmetic: PDF says use the header's Save progress ▾ menu → Create checkpoint…; the on-page "Create checkpoint…" button in the Progress tab panel reaches the identical dialog and was used instead (not re-tested via the ▾ route) |
| A10 Break it, then recover | Pass — Troubleshooting scenario 01 applied (source line verbatim); Latest re-applied (source line "Source: work · netlab-course-qa2 › link-basics/work/latest · …", verbatim); ping restored, both loopbacks back; save location card unchanged | Cosmetic: a ping run in the ~1 second immediately after the "Configuration replaced" banner can still succeed once before Et1's notconnect state actually takes effect; a check a few seconds later reliably shows the documented failure (`final-a10d-r1-broken.png` vs `final-a10e-r1-recheck.png`). A real student typing manually would not likely hit this race. |
| A11 Next time you open this lab | Pass — new browser context/reload showed "link-basics · Running · 2 of 2 devices ready · Last saved … · Deployed …"; Progress tab retained Latest and loopback-added; Lab actions menu matched the figure; Destroy lab… review text verbatim, cancelled; Remove from this manager… review text verbatim, cancelled (lab left running, not destroyed/removed, per assignment) | — |

## Remote evidence (GitHub, read-only `gh api`)

- Commits on `netlab-course-qa2` main: `3c50a3ef` Initial commit, `0fe285fc` "Save
  link-basics progress" (first save).
- `link-basics/work/latest/{manifest.json,r1.cfg,r1.eoscfg,r2.cfg,r2.eoscfg}` —
  exactly 5 files after A8.
- `link-basics/work/checkpoints/loopback-added/r2.cfg` has no `Loopback0`;
  `link-basics/work/latest/r2.cfg` has `interface Loopback0 / description r2
  loopback / ip address 10.255.0.2/32` — confirms A9's claim.
- No `link-basics/work/latest/latest` path exists.

## Findings summary

- Blocking: none.
- Should-fix: none.
- Cosmetic: (1) alternate checkpoint-menu entry point not exercised via the
  header ▾ route named by the PDF; (2) a possible immediate-ping race right
  after a fault-injecting Replace configurations, self-resolving within
  seconds and not affecting the documented end state.

## Limitations

- All checks in this replay are an agent simulation against a real manager,
  real lab VM and real GitHub repository — not a human student session.
- Browser tooling (Playwright/Chromium) was available and used throughout;
  no gap to record for Scenario A.
- The header's "Save progress ▾" dropdown route to Create checkpoint… was not
  independently exercised (see cosmetic finding above); the reachable dialog
  and its content were still verified byte-for-byte against the PDF.

Lab left running at the end: `link-basics`, Running, 2 of 2 devices ready.
