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

## UI-002 — Deploy and Build are the two primary Home actions ☐

- ☐ Two prominent choices: DEPLOY (browse files on the VM, or upload from this computer) and BUILD
  (opens the visual lab builder directly).
- ☐ Wording says where the files are (VM versus own computer); errors are understandable.
- ☐ Lab list below, under a *Recent labs* tab, newest deployment first, from real deployment
  information; a documented stable fallback for labs without it.
- ☐ Favourites, card actions and lab access kept; *Continue where you left off* no longer outranks
  the two actions or overrides the order.
- ☐ Polling and navigation do not reset the active tab or reorder by unrelated activity.

## UI-003 — Edit map gets the visual builder's map-editing capabilities ☐

- ☐ Capability matrix: installed builder versus Edit map (`docs/ui-review-001/MAP-PARITY.md`).
- ☐ Every map-editing capability of the matrix implemented and tested, or listed as incomplete.
- ☐ Positions, text, shapes, annotations and style survive save, close, reopen and further edits.
- ☐ The manager's topology view draws the saved map correctly; unsupported data is never dropped.
- ☐ Cancel / unsaved-change behaviour; no deployment, no topology or runtime change from a map edit.
- ☐ Annotation import/download and draw.io export kept.

## UI-004 — Save progress options are explained ☑ 1.30.4

- ☑ Create checkpoint, Save on this VM only, Saved versions & history, Save location settings: what
  each does and where the result goes, derived from the implementation (`gitSaveHelp()`), naming the
  lab's real folder and upload host.
- ☑ On hover and on keyboard focus (and as the option's accessible description); a pane inside the
  menu, placed by measurement so it stays inside the window, never over an option, and reading it
  never closes the menu.
- Follow-up for UI-007 C: the checkpoint text says "uploaded … unless you untick the upload"; review
  becomes mandatory there and the wording has to follow.

## UI-005 — Lab actions dropdown is simpler ☑ 1.30.3

- ☑ *Import map*, *Edit map*, *Telemetry settings*, *Operation history* moved into an expandable
  *Advanced options* group at the bottom; nothing else moved (Packet capture, Lab files, All lab
  operations, lifecycle and destructive items stay).
- ☑ Pointer and keyboard (click, Enter, Space, right/left arrow); the menu scrolls inside itself on a
  small window; same disabled states and reasons as before; *Edit map* stays on the map toolbar.

## UI-006 — Devices tab is visually consistent ☐

- ☐ Identity/platform, state/reason, Open CLI and Details align across rows; heading, search and
  Technical view relate properly.
- ☐ Long names and multi-line reasons do not overlap or shift other rows; every state stays readable.
- ☐ Laptop widths and zoom: no clipped actions, no needless horizontal scrolling.

## UI-007 — Save location clean-up, review is mandatory ◐ (A + B in 1.30.5)

- ☑ A. The marked *Technical details* disclosure reads *Git repo details* (only `.git-location-tech`
  on the Save location card). 1.30.5
- ☑ B. *Change folder…* is open when Save location opens; a deliberate fold survives polling, a tab
  change and the re-render after *Save settings* (per lab, for the life of the page). 1.30.5
- ☐ C. The *Let me review changes before they are uploaded* checkbox is gone; the review always
  happens for the user-started upload/save it governs, also for saved opt-outs; cancel uploads
  nothing and reports nothing as saved. Scheduled / non-interactive work is not altered silently.

## UI-008 — Repository folder browser ☐

- ☐ Reproduce: a folder `working` created under `JunOS-TEST-2` disappears. Root cause found.
- ☐ A new folder appears at once under its parent, stays after refresh, polling and reopening, and
  after a failed save while the location is still valid; empty folders are shown truthfully.
- ☐ Every folder with children expands and collapses, ancestors of the save location included; the
  destination in use is highlighted without forcing its ancestry open; browsing never changes it.
- ☐ Expansion, selection and focus survive background refreshes; duplicates and errors are accurate.

## Planned chunk order

1. UI-001 (1.30.2, done) → 2. UI-005 (1.30.3, done) → 3. UI-004 (1.30.4, done) → 4. UI-007 A+B (1.30.5, done) → 5. UI-007 C → 6. UI-008 root
cause and fix → 7. UI-006 → 8. UI-002 Home actions → 9. UI-002 Recent labs tab and order →
10+. UI-003 matrix, then parity in increments. One patch release, one commit and one verified push
per chunk.
