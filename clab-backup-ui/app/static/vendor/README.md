# Vendored terminal assets

- `@xterm/xterm` 5.5.0: `xterm.js`, `xterm.css`, `xterm.LICENSE`
- `@xterm/addon-fit` 0.10.0: `addon-fit.js`, `addon-fit.LICENSE`

Obtained from the matching versioned npm package archives. Assets are served
locally so deployment needs no CDN (the Content Security Policy allows scripts
from the manager's own origin only). The upstream license files are included.
Only `terminal.html` loads them, for the SSH session and the serial console; the
browser Wireshark viewer uses the noVNC modules of the pinned capture image
instead (`docs/CAPTURE.md`), and the topology editor's assets are under
`../lab-builder/`.
