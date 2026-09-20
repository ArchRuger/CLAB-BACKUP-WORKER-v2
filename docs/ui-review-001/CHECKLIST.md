# UI review 001 — requirement checklist

Source: the maintainer's brief of 2026-09-20, which translates
`Containerlab_Node_Manager_UI_Review_001.pdf` (eight pages). The PDF itself was **not available on
the dev VM**; every requirement below is taken from the brief's text. Status is what Git contains,
not what a conversation said: check `git log` and the remote before trusting a row.

Legend: ☐ open · ◐ partly delivered · ☑ delivered (with the release that delivered it).

## UI-001 — "Also running on the VM" leaves the main page ☑ 1.30.2

- ☑ The section no longer occupies Home.
- ☑ Reachable under the Manager menu: **Manager ▾ › Labs found on the VM…** (a dialog), with a count
  line under the menu entry (*n not in My labs · n hidden*).
- ☑ Add to My labs (confirmation with the files), hidden labs with *Import again* and *Stop hiding*
  (button, right-click and keyboard menu) and *File check details* all moved unchanged.
- ☑ Discovery behaviour untouched: no backend change, nothing is imported or unhidden by the move.
- Decision: the first-run empty page (no labs at all) keeps its short *Already running on the VM*
  list until UI-002 rebuilds Home; it is the onboarding path the install guides use.

## UI-002 — Deploy and Build are the two primary Home actions ☑ (1.30.10 and 1.30.11)

- ☑ Two prominent, equal choices on every Home: DEPLOY (*Choose a file on the lab VM…*, *Upload a file
  from this computer…*) and BUILD (*Open the lab builder*, a direct link). 1.30.10
- ☑ Wording says where the files are; upload errors are plain sentences; the upload reuses the
  reviewed `create` and the existing *Deploy or add this lab…* / *Deploy lab* reviews, no bypass. 1.30.10
- ☑ Lab list below under a *Recent labs* tab (default), newest deployment first, from the manager's
  own record of succeeded deploys/redeploys (`last_deployed`); *All labs* keeps favourites first. 1.30.11
- ☑ Fallback, documented on the page and here: a lab without a recorded deployment comes after all
  dated labs, by name, and its card reads *No deployment recorded by this manager*. 1.30.11
- ☑ Favourites, card actions and lab access kept; the *Continue where you left off* block is gone
  (each card still shows *Last opened*). 1.30.11
- ☑ Polling, visits, saves and favourites do not reorder *Recent labs*; the tab is kept for the session. 1.30.11
- ☑ Lab card titles no longer break inside a word. 1.30.11

## UI-003 — Edit map gets the visual builder's map-editing capabilities ☑ (1.30.12 to 1.30.17)

- ☑ Capability matrix: installed builder versus Edit map, and the approach (`docs/ui-review-001/MAP-PARITY.md`). 1.30.12
- ☑ Every map-editing capability of the matrix is implemented and was driven in a browser; what was not
  driven field by field is listed in VALIDATION (1.30.17) and in the matrix. Undo / redo (1.30.15), the
  device look (1.30.16) and the link label distance (1.30.17) are the page's own, because the editor only
  offers them as topology editing or not at all in the mode Edit map uses.
- ☑ Positions, text, shapes, groups, memberships, label and grid settings survive save, close, reopen
  and further editing; the stored document equals the editor's byte for byte (1.30.13 unit, 1.30.17 browser).
- ◐ The Topology tab draws the saved map (positions, device look, texts, shapes with rotation, groups,
  label mode and distances); **line arrows, rounded text backgrounds and nested group levels are kept
  but not drawn there**. Nothing is dropped.
- ☑ Cancel / unsaved-change behaviour; no deployment, no topology or runtime change from a map edit
  (adapter whitelist, topology restore, page check, save route; browser: every write went to the map document). 1.30.14
- ☑ Annotation import/download and draw.io export kept (in the editor's bar; Import map… on the lab page unchanged). 1.30.14
- Kept on purpose: a lab without a topology text in the manager (imported from an inventory) opens the older simple dialog.

## UI-004 — Save progress options are explained ☑ 1.30.4

- ☑ Create checkpoint, Save on this VM only, Saved versions & history, Save location settings: what
  each does and where the result goes, derived from the implementation (`gitSaveHelp()`), naming the
  lab's real folder and upload host.
- ☑ On hover and on keyboard focus (and as the option's accessible description); a pane inside the
  menu, placed by measurement so it stays inside the window, never over an option, and reading it
  never closes the menu.
- The checkpoint text was updated with UI-007 C (1.30.6): uploaded only after the student has seen
  what changed and confirmed.

## UI-005 — Lab actions dropdown is simpler ☑ 1.30.3

- ☑ *Import map*, *Edit map*, *Telemetry settings*, *Operation history* moved into an expandable
  *Advanced options* group at the bottom; nothing else moved (Packet capture, Lab files, All lab
  operations, lifecycle and destructive items stay).
- ☑ Pointer and keyboard (click, Enter, Space, right/left arrow); the menu scrolls inside itself on a
  small window; same disabled states and reasons as before; *Edit map* stays on the map toolbar.

## UI-006 — Devices tab is visually consistent ☑ 1.30.9

- ☑ Identity/platform, state/reason, Open CLI and Details start at one position in every row (one list
  grid, rows as subgrids); the list is flush with the heading; heading, search and Technical view share
  a line and a height.
- ☑ Long names and multi-line reasons wrap inside their own cell and only grow their own row; every
  state keeps its label and reason (no wording or readiness change: stylesheet only).
- ☑ Measured at 1920, 1366 and a 1280×720 laptop at 125/150/200 % zoom: no clipped action, no
  overlap, no sideways scrolling; single column below 760px.

## UI-007 — Save location clean-up, review is mandatory ☑ (A + B 1.30.5, C 1.30.6)

- ☑ A. The marked *Technical details* disclosure reads *Git repo details* (only `.git-location-tech`
  on the Save location card). 1.30.5
- ☑ B. *Change folder…* is open when Save location opens; a deliberate fold survives polling, a tab
  change and the re-render after *Save settings* (per lab, for the life of the page). 1.30.5
- ☑ C. The checkbox is gone; every user-started save stops on the VM and opens *Review before
  uploading* with *Upload these changes* / *Not now*; the manager refuses an upload that does not
  state the review, so a stored opt-out or an old page cannot bypass it; cancel uploads nothing and
  reports *Not uploaded*. 1.30.6
- Findings: nothing scheduled or non-interactive creates Git saves (automatic backups never did), so
  no conflict arose. A folder move keeps its own confirmed upload (no configuration change to review).
  A push always sends every earlier unpushed commit of the branch; the review window says so.

## UI-008 — Repository folder browser ☑ (1.30.7 and 1.30.8)

- ☑ Reproduced and root cause found (1.30.7): an empty folder existed only as a VM registration; a lab
  move retires the previous registration, so the folder the lab left vanished; a folder inside the
  lab's own folder could not be created without moving there (overlap rule).
- ☑ A new folder appears at once under its parent, is selectable, stays after refresh, polling,
  reload, reopening, a manager restart and the lab moving elsewhere; shown truthfully as *not in the
  repository until the first save* (the manager's planned-folder list; no VM helper change). 1.30.7
- ☑ Duplicates and failed creations are reported accurately, without phantom entries; an unused
  empty folder can be removed from the list. 1.30.7
- ☑ Every folder with children expands and collapses (own arrow control, keyboard too), ancestors of
  the save location included; the destination is highlighted (`current`, *This lab*, *This lab is
  inside* on a closed branch) without forcing its ancestry open; the browsed folder (`selected`) is
  told apart, and the panel says that browsing does not change where the lab saves. 1.30.8
- ☑ Expansion, selection, scroll position and focus survive background refreshes, re-renders and a
  tab change while the folders exist; long names stay on one line. 1.30.8

## Planned chunk order

1. UI-001 (1.30.2, done) → 2. UI-005 (1.30.3, done) → 3. UI-004 (1.30.4, done) → 4. UI-007 A+B (1.30.5, done) → 5. UI-007 C (1.30.6, done) → 6. UI-008 root
cause and fix (1.30.7, done) → 6b. UI-008 tree expansion and highlight (1.30.8, done) → 7. UI-006 (1.30.9, done) → 8. UI-002 Home actions (1.30.10, done) → 9. UI-002 Recent labs tab and order (1.30.11, done) →
10. UI-003 matrix (1.30.12, done) → 11+. UI-003 steps B to E of `MAP-PARITY.md`. One patch release, one commit and one verified push
per chunk.
