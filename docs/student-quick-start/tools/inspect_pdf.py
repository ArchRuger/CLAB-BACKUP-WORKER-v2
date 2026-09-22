#!/usr/bin/env python3
"""Inspect a rendered guide PDF and report anything a reader would notice.

    python3 tools/inspect_pdf.py <pdf> [--out-dir DIR] [--resolution DPI]

Prints:
  - page count and the file's SHA-256
  - the PDF outline (bookmarks) with the page each one lands on
  - every internal link's destination and whether it resolves to a page
  - the fonts used and whether each is embedded (pdffonts if on PATH, else a
    pypdf fallback that checks each font's /FontDescriptor for font-file data)
  - text-level checks: pages with no extracted text, placeholder markers
    ("TODO", "TBD", "XXX", "lorem"), the Unicode replacement character
    U+FFFD, and any extracted line longer than 110 characters (a hint that
    something overflowed its column)

Also renders every page to <out-dir>/page-NN.png with `pdftoppm -r <dpi>`
(default <student-quick-start>/build/pages, 110 dpi) so the pages can be
opened and looked at directly.

Exit codes: 0 if clean. Non-zero if any of these were found: a font that is
not embedded, an internal link that does not resolve, placeholder text, or
U+FFFD. A long line is reported but does not by itself fail the check.
"""
import argparse
import hashlib
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_OUT_DIR = HERE.parent / "build" / "pages"

PLACEHOLDER_PATTERNS = {
    "TODO": re.compile(r"TODO"),
    "TBD": re.compile(r"TBD"),
    "XXX": re.compile(r"XXX"),
    "lorem": re.compile(r"lorem", re.IGNORECASE),
}
REPLACEMENT_CHAR = "�"
LONG_LINE_LENGTH = 110


def sha256_of(path):
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def render_pages(pdf_path, out_dir, resolution):
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("page-*.png"):
        old.unlink()
    prefix = out_dir / "page"
    subprocess.run(
        ["pdftoppm", "-r", str(resolution), "-png", str(pdf_path), str(prefix)],
        check=True,
    )
    # pdftoppm numbers "page-1.png", "page-2.png", ...; rename to page-NN.png
    # (zero-padded) so listings sort naturally.
    produced = sorted(
        out_dir.glob("page-*.png"),
        key=lambda p: int(re.search(r"-(\d+)\.png$", p.name).group(1)),
    )
    renamed = []
    for path in produced:
        n = int(re.search(r"-(\d+)\.png$", path.name).group(1))
        target = out_dir / f"page-{n:02d}.png"
        if path != target:
            path.rename(target)
        renamed.append(target)
    return renamed


def get_outline(reader):
    """Flat list of (title, page_number) for every outline entry, in order."""
    entries = []

    def walk(items):
        for item in items:
            if isinstance(item, list):
                walk(item)
                continue
            title = item.get("/Title", "(untitled)")
            try:
                page_number = reader.get_destination_page_number(item)
            except Exception:
                page_number = None
            entries.append((title, page_number))

    try:
        outline = reader.outline
    except Exception:
        outline = []
    walk(outline)
    return entries


def resolve_dest(reader, dest):
    """Best-effort page number for a pypdf destination (name, array or object)."""
    try:
        if isinstance(dest, str):
            named = reader.named_destinations
            if dest not in named:
                return None
            return reader.get_destination_page_number(named[dest])
        return reader.get_destination_page_number(dest)
    except Exception:
        return None


def get_internal_links(reader):
    """List of dicts: page (1-based, source), dest (raw), resolved_page or None.

    Only /GoTo-style internal links are reported; /URI (external) links are
    skipped since they have no in-document destination to resolve.
    """
    links = []
    for page_index, page in enumerate(reader.pages):
        annots = page.get("/Annots")
        if not annots:
            continue
        for ref in annots:
            annot = ref.get_object()
            if annot.get("/Subtype") != "/Link":
                continue
            dest = annot.get("/Dest")
            if dest is None:
                action = annot.get("/A")
                if action and action.get("/S") == "/GoTo":
                    dest = action.get("/D")
            if dest is None:
                continue  # e.g. a /URI action; not an internal link
            resolved = resolve_dest(reader, dest)
            links.append(
                {
                    "source_page": page_index + 1,
                    "dest": dest if isinstance(dest, str) else "(explicit destination)",
                    "resolved_page": resolved,
                }
            )
    return links


def get_fonts_pdffonts(pdf_path):
    result = subprocess.run(["pdffonts", str(pdf_path)], capture_output=True, text=True)
    lines = result.stdout.splitlines()
    if len(lines) < 2:
        return []
    header, dashes = lines[0], lines[1]
    ranges = [(m.start(), m.end()) for m in re.finditer(r"-+", dashes)]
    cols = [header[s:e].strip().lower() for s, e in ranges]
    fonts = []
    for line in lines[2:]:
        if not line.strip():
            continue
        values = [line[s:e].strip() for s, e in ranges]
        row = dict(zip(cols, values))
        fonts.append({"name": row.get("name", "?"), "embedded": row.get("emb") == "yes"})
    return fonts


def get_fonts_pypdf(reader):
    seen = {}
    for page in reader.pages:
        resources = page.get("/Resources")
        if not resources:
            continue
        font_dict = resources.get("/Font")
        if not font_dict:
            continue
        for _, font_ref in font_dict.items():
            font = font_ref.get_object()
            name = font.get("/BaseFont", "?")
            if name in seen:
                continue
            descriptor = font.get("/FontDescriptor")
            embedded = False
            if descriptor:
                descriptor = descriptor.get_object()
                embedded = any(
                    k in descriptor for k in ("/FontFile", "/FontFile2", "/FontFile3")
                )
            elif font.get("/Subtype") == "/Type0":
                # Composite font: descriptor lives on the descendant font.
                descendants = font.get("/DescendantFonts")
                if descendants:
                    child = descendants[0].get_object()
                    child_desc = child.get("/FontDescriptor")
                    if child_desc:
                        child_desc = child_desc.get_object()
                        embedded = any(
                            k in child_desc for k in ("/FontFile", "/FontFile2", "/FontFile3")
                        )
            seen[name] = embedded
    return [{"name": name, "embedded": embedded} for name, embedded in seen.items()]


def get_fonts(pdf_path, reader):
    import shutil

    if shutil.which("pdffonts"):
        fonts = get_fonts_pdffonts(pdf_path)
        if fonts:
            return fonts, "pdffonts"
    return get_fonts_pypdf(reader), "pypdf"


def extract_page_texts(pdf_path):
    result = subprocess.run(
        ["pdftotext", "-layout", str(pdf_path), "-"], capture_output=True, text=True, check=True
    )
    pages = result.stdout.split("\f")
    if pages and pages[-1] == "":
        pages = pages[:-1]
    return pages


def check_text(pages):
    """Returns (problems, warnings): problems fail the build, warnings do not."""
    problems = []
    warnings = []
    for i, text in enumerate(pages, start=1):
        if not text.strip():
            problems.append(f"page {i}: no extracted text")
        for label, pattern in PLACEHOLDER_PATTERNS.items():
            for m in pattern.finditer(text):
                line_no = text.count("\n", 0, m.start()) + 1
                problems.append(f"page {i} line {line_no}: placeholder text ({label})")
        if REPLACEMENT_CHAR in text:
            count = text.count(REPLACEMENT_CHAR)
            problems.append(f"page {i}: U+FFFD replacement character x{count}")
        for line_no, line in enumerate(text.split("\n"), start=1):
            if len(line) > LONG_LINE_LENGTH:
                warnings.append(f"page {i} line {line_no}: {len(line)} characters (possible overflow)")
    return problems, warnings


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("pdf", type=Path, help="the PDF to inspect")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR, help="where to render page PNGs")
    parser.add_argument("--resolution", type=int, default=110, help="pdftoppm -r value (default 110)")
    args = parser.parse_args(argv)

    pdf_path = args.pdf
    if not pdf_path.exists():
        print(f"error: {pdf_path} does not exist", file=sys.stderr)
        return 1

    import pypdf

    digest = sha256_of(pdf_path)
    reader = pypdf.PdfReader(str(pdf_path))
    page_count = len(reader.pages)

    print(f"file: {pdf_path}")
    print(f"pages: {page_count}")
    print(f"sha256: {digest}")

    print("\n-- outline (bookmarks) --")
    outline = get_outline(reader)
    if not outline:
        print("  (none)")
    for title, page_number in outline:
        shown = "?" if page_number is None else page_number + 1
        print(f"  - {title!r} -> page {shown}")

    print("\n-- internal links --")
    links = get_internal_links(reader)
    unresolved = [l for l in links if l["resolved_page"] is None]
    if not links:
        print("  (none)")
    for link in links:
        shown = "UNRESOLVED" if link["resolved_page"] is None else f"page {link['resolved_page'] + 1}"
        print(f"  - from page {link['source_page']} to {link['dest']!r}: {shown}")

    print("\n-- fonts --")
    fonts, source = get_fonts(pdf_path, reader)
    print(f"  (via {source})")
    not_embedded = [f for f in fonts if not f["embedded"]]
    if not fonts:
        print("  (none found)")
    for font in fonts:
        status = "embedded" if font["embedded"] else "NOT EMBEDDED"
        print(f"  - {font['name']}: {status}")

    print("\n-- text checks --")
    page_texts = extract_page_texts(pdf_path)
    problems, warnings = check_text(page_texts)
    for w in warnings:
        print(f"  warning: {w}")
    for p in problems:
        print(f"  problem: {p}")
    if not problems and not warnings:
        print("  (clean)")

    print("\n-- rendering pages --")
    rendered = render_pages(pdf_path, args.out_dir, args.resolution)
    for path in rendered:
        print(f"  wrote {path}")

    print("\n-- summary --")
    ok = True
    if not_embedded:
        print(f"FAIL: {len(not_embedded)} font(s) not embedded")
        ok = False
    if unresolved:
        print(f"FAIL: {len(unresolved)} internal link(s) do not resolve")
        ok = False
    if problems:
        print(f"FAIL: {len(problems)} text problem(s) (placeholder text, missing text, or U+FFFD)")
        ok = False
    if warnings:
        print(f"NOTE: {len(warnings)} long line(s) reported above (not a failure by itself)")
    if ok:
        print("OK")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
