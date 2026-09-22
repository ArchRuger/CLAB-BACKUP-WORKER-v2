# Building the Student Quick Start PDF

This turns `source/guide.md` into
`Containerlab_Node_Manager_Student_Quick_Start.pdf`. No network access, no
virtualenv, no pip: everything runs on the system `python3` with packages
installed via `apt`.

## One-time setup

```bash
sudo apt-get install -y weasyprint python3-markdown python3-pypdf python3-pil \
    fonts-dejavu fonts-liberation2 poppler-utils
```

This installs WeasyPrint (HTML/CSS → PDF), python-markdown, pypdf, Pillow,
the DejaVu and Liberation fonts, and the poppler command-line tools
(`pdftoppm`, `pdfinfo`, `pdftotext`, `pdffonts`).

## Building

From any directory:

```bash
bash "$HOME/projects/clab-manager/docs/student-quick-start/build.sh"
```

This: checks the toolchain is importable/on `PATH`, runs
`tools/compose_screenshots.py` (composes `screenshots/*.png` from
`screenshots/spec.json` and `screenshots/raw/`, if `spec.json` exists yet),
renders the guide with `build.py`, inspects the result with
`tools/inspect_pdf.py`, and prints the page count and the PDF's SHA-256.

Run the pieces individually while iterating:

```bash
python3 docs/student-quick-start/build.py               # guide.md -> the PDF + build/guide.html
python3 docs/student-quick-start/build.py --check        # only verify every referenced image exists
python3 docs/student-quick-start/tools/compose_screenshots.py --list   # show spec.json entries and whether sources exist
python3 docs/student-quick-start/tools/compose_screenshots.py          # compose screenshots/*.png
python3 docs/student-quick-start/tools/inspect_pdf.py docs/student-quick-start/Containerlab_Node_Manager_Student_Quick_Start.pdf
```

`build/guide.html` is the intermediate HTML (before WeasyPrint); open it in a
browser to debug layout without re-running the PDF renderer. Note it is HTML
for inspection only — the running headers, footers, TOC leaders and page
numbers are print-only (`@page` CSS) and only render in WeasyPrint's own
preview or the PDF itself, not in a normal browser tab.

## What `build.py` does

Reads `source/guide.md` with `python-markdown`, extensions `extra` (tables,
attr_list, md_in_html, fenced_code), `toc` (`anchorlink=False`,
`permalink=False`, `toc_depth="2-3"` — the `[TOC]` marker in the Markdown is
replaced with a linked list built from the `##`/`###` headings only), and
`sane_lists`. A Markdown paragraph holding only an image
(`![caption](screenshots/x.png)`) is turned into `<figure><img>` +
`<figcaption>` from the alt text; a hand-written `<figure>…</figure>` block
in the Markdown passes through unchanged (via `md_in_html`). The HTML is
wrapped with `source/style.css` and rendered with WeasyPrint to
`Containerlab_Node_Manager_Student_Quick_Start.pdf`; metadata (title,
author, subject) is set via `<title>`/`<meta name="author">`/`<meta
name="description">`, which WeasyPrint copies into the PDF Info dictionary.
`--check` stops after verifying every image reference (Markdown `![]()` or
raw HTML `<img src="...">`) resolves to a file under
`docs/student-quick-start/`, without rendering anything.

## `source/style.css`

US Letter, 0.8in margins, DejaVu Sans 10.5pt body / DejaVu Sans Mono 9pt
code (falls back to Liberation Sans/Mono if DejaVu is missing). Page
numbers are `@page { @bottom-center { content: "Page " counter(page) " of "
counter(pages); } }`. The running header uses `string-set: doctitle
content()` on both `h1` and `h2`, shown via `@top-center { content:
string(doctitle); }`, so it always reflects the nearest heading (the guide
title on the first page, the current section afterwards). PDF bookmarks
come from WeasyPrint's default `bookmark-level`/`bookmark-label` on
headings; `style.css` keeps that for `h1`–`h3` and sets `bookmark-level:
none` on `h4`–`h6` so only the top three levels appear in the PDF outline.
The `[TOC]` output (`.toc a::after { content: leader(dotted) "
"target-counter(attr(href), page); }`) gets dotted leaders and a real page
number resolved against the link target. `.given`, `.step`, `.tip`, `.warn`
are bordered boxes (`.step .n` is the numbered badge, accent colour
`#c05a1c`, matching the callout badges `compose_screenshots.py` draws). None
of the four boxes get a CSS-generated label ("Tip", "What you have been
given", …): the writer types that as real text (e.g. a leading `**Tip**` or
`**What you have been given**` line), which stays searchable and reads
correctly even without this stylesheet; `.given`'s first paragraph is
styled bold to stand out as that heading.
`h2.scenario` forces a page break before it. Headings use `break-after:
avoid`; figures and table rows use `break-inside: avoid`; tables use
`table-layout: fixed` with `overflow-wrap: anywhere` on cells so long
content (including inline `<code>`) wraps instead of overflowing the page.

## `screenshots/spec.json` format

A JSON list; each entry composes one screenshot from a raw capture:

```json
[
  {
    "out": "a02-topology-file.png",
    "src": "raw/a02-topology-file.png",
    "crop": [120, 80, 900, 600],
    "scale": 0.5,
    "callouts": [
      {"n": 1, "x": 420, "y": 96, "label": "Deploy lab", "anchor": "top-left"}
    ]
  }
]
```

- `out`, `src` — required, paths relative to `screenshots/` (so `src` is
  typically under `screenshots/raw/`, `out` is written directly under
  `screenshots/`).
- `crop` — optional `[x, y, w, h]` in the raw file's own pixel grid (the raw
  captures are taken at `device_scale_factor` 2, so this is already twice
  the CSS pixel size — read coordinates off the actual PNG, not the browser
  layout).
- `scale` — optional multiplier applied to the cropped image (default
  `1.0`), e.g. `0.5` to shrink a screenshot for print.
- `callouts` — optional list of numbered badges. `x`/`y` are in the same
  raw-pixel space as `crop`; the tool maps them through the crop offset and
  scale to find where they land in the output image. `label` is
  documentation only (for `--list` and the guide author's own reference) —
  it is never drawn on the image, only the numbered circle is. `anchor`
  (default `top-left`; also `top-right`, `bottom-left`, `bottom-right`,
  `center`) says which corner of the target the point represents, so the
  badge is drawn just outside that corner rather than covering the target.
  The badge itself is always ~34px in the output image regardless of
  `scale`, so numbers stay legible on a shrunk screenshot.

`tools/compose_screenshots.py --list` prints every entry with whether its
`src` exists, without composing anything. A missing raw file (or any other
problem in an entry) is reported by its `out` name and does not stop the
other entries from being composed; the tool still exits non-zero if any
entry failed. Composing the same `spec.json` + raw image twice produces
pixel-identical output (no randomness, no embedded timestamps); PNG byte
layout is stable across runs on the same machine since the tool never
varies its own encoder settings.

## What `tools/inspect_pdf.py` checks

```bash
python3 tools/inspect_pdf.py Containerlab_Node_Manager_Student_Quick_Start.pdf
```

Renders every page to `build/pages/page-NN.png` with `pdftoppm -r 110`, and
prints/checks:

- page count and the file's SHA-256
- the PDF outline (bookmarks) via `pypdf`, each with the page it lands on
- every internal link (`/Dest` or a `/GoTo` `/A` action) and whether it
  resolves to a page — an unresolved link fails the check
- fonts and whether each is embedded, via `pdffonts` if it's on `PATH`
  (parses its column layout from the header's dashes), else a `pypdf`
  fallback that checks each font's `/FontDescriptor` for `/FontFile*` — a
  non-embedded font fails the check
- text-level checks via `pdftotext -layout`: pages with no extracted text,
  the placeholder markers `TODO`, `TBD`, `XXX` (case-sensitive) and `lorem`
  (case-insensitive), and the Unicode replacement character `U+FFFD` — any
  of these fail the check; a line longer than 110 characters is printed as
  a warning (a hint that something overflowed its column) but does not by
  itself fail the check

Exit code is non-zero if any font is not embedded, any internal link does
not resolve, any placeholder text or U+FFFD is found; 0 otherwise.

## Limitations hit with WeasyPrint 61.1

- `string-set`/`string()` running headers only take the *element's own*
  text via `content()`; there is no way to combine "the fixed guide title"
  and "the current section" into one string without duplicating the title
  into every heading, so the header here shows the nearest heading instead
  (documented above).
- WeasyPrint renders `@page` margin boxes (page numbers, running headers)
  correctly in the PDF, but a plain browser opening `build/guide.html`
  never shows them — margin boxes are PDF/print-only in WeasyPrint's model,
  so layout debugging in a browser covers everything except pagination,
  headers, footers and the TOC's `target-counter` page numbers.
- `leader()` and `target-counter(attr(href), page)` both work for the TOC's
  dotted leaders and page numbers, but only against a same-document `href`
  starting with `#`; an absolute or missing target renders no counter
  rather than erroring, which is why `inspect_pdf.py` cross-checks links
  independently through `pypdf` rather than trusting the PDF's own visual
  rendering.
- A Markdown link to a heading that does not exist
  (`[text](#no-such-heading)`) does not raise or fail `write_pdf()` —
  WeasyPrint silently drops the link (no PDF link annotation at all, so
  `inspect_pdf.py` has nothing to see afterwards) and only reports it
  through its own `weasyprint` logger, which has a `NullHandler` by default
  and prints nothing on its own. `build.py` attaches a handler to that
  logger for the duration of `write_pdf()` and fails the build (exit 3) if
  it logs anything — this is also what catches invalid CSS
  (`word-break: break-word` is invalid in WeasyPrint; use `overflow-wrap`)
  before it silently turns into a dropped rule.
