# D06: user-guide screenshots under docs/images/ (2026-10-27)

Application commit 64e8b66 (UI of 973668e plus the plan-limit sentences). Chromium (Playwright, `/home/archtop/pw-venv/bin/python`), 1440x900,
device scale factor 1, no `networkidle` waits. Nineteen PNG files are referenced by tracked Markdown (README.md and docs/TOUR.md); all exist.
Result: 19 referenced, 19 replaced (one of them re-compressed only, see below), 0 kept as-is, 0 missing.

## How the pictures were taken (evidence class: fixture, plus one live terminal)

- Fixture evidence: `docs/redesign/tools/fixture_manager.py --capture --classic` on port 8962 with a fresh scratch `FIXTURE_DATA`, driven by the
  maintained `docs/redesign/tools/verify_after.py` restricted to 1440x900 through a scratch wrapper (the wrapper only sets `VIEWPORTS`): 107/107 checks,
  0 console errors, 0 page errors, exit 0. These are the same scripted labs, scenes and framing as the old set (the file name is the script's shot name).
- `all-versions.png` and `load-confirmation.png`: `docs/redesign/tools/readme_shots.py` against the full fixture (lab `restore-square`), fresh data, port 8961,
  0 console and page errors, exit 0. It opens All versions and the Load confirmation and never presses Load.
- `ssh-terminal.png`: the live manager (127.0.0.1:8081), lab `parity`, device cjunos (cJunosEvolved), Open CLI in a new tab, one read-only command
  (`show version`). Nothing was changed on the VM; no save, no confirm. The screen shows only the lab's 172.20.20.x management address and `show version`
  output, no credentials. The old picture was a lab (clab-llm-dev2, PTX1) that no longer exists.
- The fixture was used instead of the live labs for the rest because the pictures need states a read-only pass cannot create (a waiting save, an operation
  banner, All versions with lab states) and the captions name the 13-device example course lab.

## Table

Sizes in bytes before -> after. "Guide" is `file:line` of the reference. All new files are under 400 KB.

| Image | Guide | What the old picture lacked | Size |
|---|---|---|---|
| docs/images/ui/00-home.png | TOUR.md:23 | Home: new subtitle ("...and your saves"), the Find a lab field, unfilled star on the cards | 124720 -> 126230 |
| docs/images/ui/10-topology.png | TOUR.md:44, README.md:51 | map toolbar now has Find, Edit topology..., the "n links impaired" chip with Clear impairments, the link-state legend; banner is the partial-load notice | 238128 -> 248645 |
| docs/images/ui/11-topology-context-menu.png | TOUR.md:46 | device menu: Console, Capture traffic..., Restart, Stop, Start (with its reason), Device details | 236942 -> 242132 |
| docs/images/ui/13-device-drawer-attention.png | TOUR.md:58 | drawer: Capture/Stop/Start buttons, Check credentials, Connection with Copy buttons, Container section, Interfaces/Logs/Impairments sections | 249792 -> 255306 |
| docs/images/ui/20-devices.png | TOUR.md:56 | a Console button per vrnetlab row | 125750 -> 131442 |
| docs/images/ui/30-save-panel.png | TOUR.md:76 | panel layout (Saves to / Change..., Last load), 13 lines added in the sentence, new toolbar behind it | 257332 -> 270086 |
| docs/images/ui/34-all-versions.png | TOUR.md:84 | new toolbar behind, current fixture dates and rows (lab state Solution still opened) | 213329 -> 223954 |
| docs/images/ui/36-load-confirmation.png | TOUR.md:93 | new toolbar behind, Options disclosure; wording of the device list unchanged | 252667 -> 262468 |
| docs/images/ui/40-tools.png | TOUR.md:100 | Edit topology... next to Edit map under More tools, Map text, capture no longer "not set up" | 113620 -> 116306 |
| docs/images/ui/41-capture-dialog.png | TOUR.md:102 | capture dialog with the stack enabled: Scope, Capture on, Interfaces, Your capture sessions with Refresh list | 144599 -> 167488 |
| docs/images/ui/44-destroy-review.png | TOUR.md:122 | review wording ("Last saved just now", Open CLI sessions notice, 13 running devices affected) and Run with options | 126620 -> 133949 |
| docs/images/ui/45-operation-banner.png | TOUR.md:124 | banner now also has Stop... while the operation runs | 123407 -> 122097 |
| docs/images/ui/51-advanced.png | TOUR.md:108 | full page of lab ospf-basics (1440x2062 -> 1440x2089): Deployment details, Credentials, Action logs, Lab operations row, Experimental, Danger zone | 241143 -> 245809 |
| docs/images/ui/55-cli-launcher.png | TOUR.md:133 | launcher heading, Open all ready CLIs, pop-up/32-CLI sentence (1440x1134 -> 1440x1171) | 113956 -> 123591 |
| docs/images/ui/61-terminal.png | TOUR.md:135 | terminal toolbar (Smaller, Larger, Reset size, Copy selection, Copy screen, Clear, Save screen/session as text) and the Alt+T notice | 37072 -> 53800 |
| docs/images/all-versions.png | README.md:57 | same view, new Find/Edit topology... toolbar behind, rows of the current fixture | 129630 -> 144974 |
| docs/images/load-confirmation.png | README.md:57 | same view (Final, four devices, 4 lines differ / Already matches), new toolbar behind | 144040 -> 158360 |
| docs/images/ssh-terminal.png | README.md:59 | replaced by a live terminal with the toolbar (old one showed neither the toolbar nor the Alt+T notice) | 83883 -> 91422 |
| docs/images/wireshark-in-browser.png | README.md:59 | content KEPT (re-compressed only: 128-colour palette, no dithering, 1440x900 unchanged; was over the 400 KB limit). The viewer toolbar markup is unchanged since the picture was taken (capture-session.html differs only in the `?v=`); a new capture needs a real Wireshark session, which a read-only pass cannot start | 513798 -> 122441 |

## Limits

- The wireshark picture shows a lab (clab-llm-dev2) and a PTX1 capture that no longer exist; it was not retaken because that would start a capture session
  on a live lab. The viewer page's behaviour changed since (page title, status wording for stopped desktops), none of it visible in the picture.
- Fixture dates and times in the pictures (saves "23 min ago", lab states "Sep 7, 2026") are scripted and move with the fixture clock.
- The fixture pictures show the lab banner "The load finished on some devices only." (the fixture's last load is a partial one), unlike the old "1 device
  needs login credentials" banner; both are real banners.
- Not checked: the 760 and 390 widths (the guides use 1440x900 only).

## Captions and text the lead must fix (TOUR.md and README.md are owned by another worker, so not edited here)

- docs/TOUR.md:64-65: the sentence quotes "12 lines added, 12 removed" for 30-save-panel.png; the picture now reads "13 devices ... 13 lines added, 12 removed."
  Either quote "13 lines added, 12 removed" or drop the numbers.
- docs/TOUR.md:48-52 (Devices paragraph): optional, the new 20-devices.png rows carry a Console button for vrnetlab kinds (PE1, GTW-1, UP-1); the
  Topology paragraph at :37 already names Console.
- No alt text names something that no longer exists (README.md:51, 57, 59; TOUR.md alt texts at 76, 84, 93 still match what the new pictures show).

Scratch scripts and raw shots: `/tmp/claude-1000/-home-archtop-projects-clab-manager/8c727c84-a148-42fb-b8ff-25a6638ec02a/scratchpad/d06/` (run_va.py, live_term.py).
