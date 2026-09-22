#!/usr/bin/env python3
"""Render the Containerlab Node Manager Student Quick Start guide to PDF.

Reads docs/student-quick-start/source/guide.md (python-markdown), wraps the
HTML with docs/student-quick-start/source/style.css, and renders
Containerlab_Node_Manager_Student_Quick_Start.pdf with WeasyPrint. Also
writes build/guide.html, the intermediate HTML, so layout problems can be
inspected in a browser without re-running WeasyPrint.

Usage:
    python3 build.py            # render source/guide.md -> the PDF
    python3 build.py --check    # only verify every referenced image exists
    python3 build.py --source PATH --out PATH   # override paths (used by tests)

Exit codes: 0 on success, 1 if guide.md is missing, 2 if --check finds a
missing image, 3 if WeasyPrint fails to render or logs a problem while
rendering (WeasyPrint does not raise for a broken internal link such as
``[text](#no-such-heading)`` — it silently drops the link and only reports
it through its own logger, so build.py listens for that instead of trusting
a clean return from write_pdf()).
"""
import argparse
import html
import logging
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

TITLE = "Containerlab Node Manager Student Quick Start"
AUTHOR = "Containerlab Node Manager project"
SUBJECT = "Student quick-start guide for the Containerlab Node Manager"

IMG_SRC_RE = re.compile(r'<img\b[^>]*\bsrc="([^"]+)"[^>]*>')
IMG_ALT_RE = re.compile(r'\balt="([^"]*)"')
BARE_IMAGE_P_RE = re.compile(r'<p>\s*(<img\b[^>]*/?>)\s*</p>')
MD_IMAGE_REF_RE = re.compile(r'!\[[^\]]*\]\(([^)\s]+)(?:\s+"[^"]*")?\)')


def markdown_image_paths(markdown_text):
    """Every image path referenced by ![...](...) syntax in the raw Markdown."""
    return [m.group(1) for m in MD_IMAGE_REF_RE.finditer(markdown_text)]


def html_image_paths(html_text):
    """Every image path referenced by an <img src="..."> in rendered HTML.

    Covers both the Markdown ![]() form and figures the writer wrote as raw
    HTML (<figure><img src="...">...).
    """
    return [m.group(1) for m in IMG_SRC_RE.finditer(html_text)]


def bare_images_to_figures(html_text):
    """Turn a paragraph holding only an <img> into a <figure>/<figcaption>.

    The alt text becomes the caption verbatim, matching the writer's
    convention of putting the full caption ("Figure A.3 ...") in the alt
    attribute of the Markdown ![]() form. A paragraph that already came from
    a hand-written <figure> block (md_in_html passthrough) is untouched
    because it never matches the "<p><img></p>" shape.
    """

    def repl(match):
        img_tag = match.group(1)
        alt_match = IMG_ALT_RE.search(img_tag)
        alt = html.unescape(alt_match.group(1)) if alt_match else ""
        caption = f"<figcaption>{html.escape(alt)}</figcaption>" if alt else ""
        return f"<figure>{img_tag}{caption}</figure>"

    return BARE_IMAGE_P_RE.sub(repl, html_text)


def render_markdown(markdown_text):
    import markdown as md

    converter = md.Markdown(
        extensions=["extra", "toc", "sane_lists"],
        extension_configs={
            "toc": {
                "anchorlink": False,
                "permalink": False,
                "toc_depth": "2-3",
            },
        },
        output_format="html5",
    )
    body_html = converter.convert(markdown_text)
    return bare_images_to_figures(body_html)


def wrap_document(body_html, style_css, title=TITLE, author=AUTHOR, subject=SUBJECT):
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{html.escape(title)}</title>
<meta name="author" content="{html.escape(author)}">
<meta name="description" content="{html.escape(subject)}">
<style>
{style_css}
</style>
</head>
<body>
{body_html}
</body>
</html>
"""


def find_missing_images(markdown_text, html_text, base_dir):
    """Return the sorted list of referenced image paths that do not exist.

    Checks both the raw Markdown ![]() references and any <img src="..."> in
    the rendered HTML (which also covers hand-written <figure> blocks), so a
    broken reference is caught regardless of which form the writer used.
    """
    referenced = set(markdown_image_paths(markdown_text)) | set(html_image_paths(html_text))
    missing = []
    for ref in sorted(referenced):
        if ref.startswith(("http://", "https://", "data:")):
            continue
        if not (base_dir / ref).exists():
            missing.append(ref)
    return missing


def build(source_path, style_path, out_pdf, out_html, check_only=False):
    if not source_path.exists():
        print(f"error: {source_path} does not exist (the writer owns this file)", file=sys.stderr)
        return 1

    markdown_text = source_path.read_text(encoding="utf-8")
    body_html = render_markdown(markdown_text)
    base_dir = source_path.parent.parent  # docs/student-quick-start/ (images are screenshots/...)

    missing = find_missing_images(markdown_text, body_html, base_dir)
    if missing:
        print("error: missing image(s) referenced by the guide:", file=sys.stderr)
        for ref in missing:
            print(f"  - {ref}", file=sys.stderr)
        return 2

    if check_only:
        print(f"OK: {source_path} references {len(set(markdown_image_paths(markdown_text)) | set(html_image_paths(body_html)))} image(s), all present.")
        return 0

    style_css = style_path.read_text(encoding="utf-8")
    full_html = wrap_document(body_html, style_css)

    out_html.parent.mkdir(parents=True, exist_ok=True)
    out_html.write_text(full_html, encoding="utf-8")

    try:
        import weasyprint
    except ImportError as exc:
        print(f"error: weasyprint is not importable ({exc}); see BUILD.md", file=sys.stderr)
        return 3

    class _Collect(logging.Handler):
        def __init__(self):
            super().__init__(level=logging.WARNING)
            self.records = []

        def emit(self, record):
            self.records.append(self.format(record))

    collector = _Collect()
    wp_logger = logging.getLogger("weasyprint")
    wp_logger.addHandler(collector)
    try:
        weasyprint.HTML(string=full_html, base_url=str(base_dir)).write_pdf(str(out_pdf))
    except Exception as exc:  # noqa: BLE001 - report and fail the build
        print(f"error: WeasyPrint failed to render the PDF: {exc}", file=sys.stderr)
        return 3
    finally:
        wp_logger.removeHandler(collector)

    if collector.records:
        print("error: WeasyPrint reported problem(s) while rendering:", file=sys.stderr)
        for msg in collector.records:
            print(f"  - {msg}", file=sys.stderr)
        return 3

    print(f"wrote {out_html}")
    print(f"wrote {out_pdf}")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        default=HERE / "source" / "guide.md",
        help="path to the guide Markdown source (default: source/guide.md)",
    )
    parser.add_argument(
        "--style",
        type=Path,
        default=HERE / "source" / "style.css",
        help="path to the print stylesheet (default: source/style.css)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=HERE / "Containerlab_Node_Manager_Student_Quick_Start.pdf",
        help="path to the rendered PDF",
    )
    parser.add_argument(
        "--out-html",
        type=Path,
        default=HERE / "build" / "guide.html",
        help="path to the intermediate HTML (default: build/guide.html)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="only verify every referenced image exists; do not render",
    )
    args = parser.parse_args(argv)

    return build(args.source, args.style, args.out, args.out_html, check_only=args.check)


if __name__ == "__main__":
    raise SystemExit(main())
