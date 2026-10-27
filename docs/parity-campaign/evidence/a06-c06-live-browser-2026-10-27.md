# A06: C06 items run live in a browser, 2026-10-27

Live manager 1.31.6 at http://127.0.0.1:8081, lab `parity` (id d7e3a4686c084f9f88e344b5064aa162, five devices), Topology tab.
Playwright Chromium, viewport 1440x900, no `networkidle` waits. READ-ONLY: the script made no non-GET request
(recorded with `page.on('request')`: none) and produced no console or page error. Another worker was restarting devices on
the lab at the same time; at 01:43 the header said "Starting, 1 of 5 devices ready" (vsw, vrt, cjunos, xrv9k Starting, ceos ready).
Evidence class: live manager, browser. Scripts: scratchpad `a07a06/a06.py`, `a06b.py` (not committed).

| Item | Observed | Screenshot |
|---|---|---|
| 1 Link-state chip | 01:43:38 and again 01:43:49 (one poll later): `#map-links` = "Links: 5 connected" plus the legend "dotted red = down (container link)". 5 `.topology-wire`, 5 `link-up`, 0 `link-down`. Caption "5 devices · 5 links". "connected" (not "up") because the answer carries VM devices. The chip stayed "5 connected" while four devices were Starting. | `a06/1-chip.png` |
| 2 Find | `ceos` + Enter: "1 of 5 devices matches" (visible), 4 devices `dimmed`, viewBox `-35 -46 761 321` -> `580 -60 200 160` (fitted to the one match). Escape: input empty, count hidden, 0 dimmed; the view stays fitted (`580 -60 200 160`) until Fit is pressed (Escape clears the term only; recorded, not claimed as a defect). | `a06/2-find-ceos.png` |
| 3 Hover a wire | Pointer at the wire midpoint (vsw:ge-0/0/0 to vrt:ge-0/0/0), 01:43:51: wire classes `topology-wire link-up hover`, 2 `hover-end` devices, `#map-link-hover` visible with the same text as the SVG `<title>`: "vsw:ge-0/0/0 — vrt:ge-0/0/0 · connected (the VM's link to vsw and vrt; a port shut down inside vsw and vrt may not show here)". aria-label: "Capture vsw:ge-0/0/0 to vrt:ge-0/0/0 · connected (same clause)". Pointer away hides the line. | `a06/3-hover.png` |
| 4 Download picture | More > Download picture... enabled. SVG (Whole map, background on, state colours off): `parity-map.svg`, 9644 bytes, contains the device labels vsw, vrt, cjunos, xrv9k, ceos and the interface labels (not the `clab-parity-` container names). PNG: `parity-map.png`, 85931 bytes, 1522x642. Dialog status empty both times; the dialog closes itself. | `a06/4-picture-dialog.png`, `a06/6-downloaded-picture.png` |
| 5 Shortcuts dialog | The `?` key does NOT open it (Shift+Slash, no dialog; no page script has a handler for it). It opens from Manager > Help > Keyboard shortcuts... The Topology map section lists 7 rows (Tab, Enter/Space on device and link, Shift+F10 on device and link, arrows in menus, Escape order). The two Find rows (Enter in Find fits; Escape in Find clears) are ABSENT live: they are in the lead's uncommitted tree, not in the 1.31.6 image, as expected. | `a06/5-shortcuts.png` |

Downloaded files (scratchpad, not committed): `/tmp/claude-1000/-home-archtop-projects-clab-manager/8c727c84-a148-42fb-b8ff-25a6638ec02a/scratchpad/a07a06/dl/parity-map.svg` and `.../dl/parity-map.png`.

Not covered: the chip with a down wire (no wire was down), the "What is shown now" area and "Device state and link colours" picture options, any viewport other than 1440x900.
