# Reference pack: Save and Load in the lab header

Approved mockups for the feature described in [`../PROMPT.md`](../PROMPT.md) (delivered as
`CLAB_Git_Save_Load_Redesign_Claude_Code_Prompt_v2.md`).

## boards/

Screenshots of the manager's real frontend (release 1.30.59) with stand-in data and a static header control.

| Board | Shows |
|---|---|
| `G01-rest` | Header at rest: chip, Save, Load |
| `G02-load-open` | Load panel: your versions, instructor versions, a view-only version |
| `G03-load-confirm` | Load confirmation with per-device difference counts |
| `G04-loading` | Load in progress, device by device |
| `G05-running` | After a load: chip says what is running; Undo this load |
| `G06-partial-failure` | One device refused the load |
| `G07-partial-version` | A version that covers 2 of 4 devices |
| `G08-fresh-lab` | Load panel of a lab with no saves of its own |
| `G09-not-running` | Load panel of a stopped lab (stopped state set by hand in the DOM) |
| `G10-status` | Chip panel at rest |
| `G11-save` | After Save: the one-sentence upload prompt |
| `F02-saving` | Save in progress |
| `F04-changes` | "What changed" drawer with the real diff markup |
| `F05-uploaded` | After upload: toast |
| `F06-name` | Optional name and "Keep as a checkpoint" |
| `F11-all-versions` | All versions drawer |
| `F12-first-save` | First save of a lab with no save location |
| `F13-failed` | Upload failed |
| `F14-unchanged` | Nothing changed: toast only |
| `F15-settings` | Save settings drawer |
| `F16-narrow` | Header at 760 px wide |
| `now-01-progress` | The Progress tab as it is today |

The `F*` boards come from the first header version, which had no Load button; apart from that button they
are unchanged in the approved design. Where a board and the prompt disagree, the prompt wins (for example
the drawers say "Go back to this version…"; the approved wording is "Load this state…", and "From your instructor" is headed "Lab states").

## mock-src/

The Playwright scripts that produced the boards. They are a specification of markup, copy and CSS, not code
to ship.

- `emulate.py`: loads the real `index.html`, `style.css` and scripts and answers `/api/*` from memory, using
  the recorded state in `docs/netlab-ui-qa/acceptance/pass-5/preflight-api-state.json`. Set `CLAB_REPO` to
  the checkout (default `~/projects/clab-manager`).
- `mock4.py`: the approved header (boards `G*`). `mock3.py`: drawers and edge states (boards `F*`).
  `mock2.py`, `mock.py`: shared CSS and helpers from earlier rounds.

Run with a Python that has Playwright and Chromium: `python3 mock4.py` writes to `shots/`.
