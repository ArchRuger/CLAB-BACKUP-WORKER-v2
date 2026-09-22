#!/usr/bin/env bash
# Build the Containerlab Node Manager Student Quick Start PDF, from any
# directory. Verifies the toolchain, composes the screenshots, renders the
# guide, then inspects the result and prints the page count and SHA-256.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PDF="$HERE/Containerlab_Node_Manager_Student_Quick_Start.pdf"

echo "== checking the toolchain =="
python3 - <<'EOF'
import importlib
import shutil
import sys

missing = []
for mod in ("weasyprint", "markdown", "pypdf", "PIL"):
    try:
        importlib.import_module(mod)
    except ImportError:
        missing.append(mod)

for tool in ("pdftoppm", "pdfinfo", "pdftotext"):
    if shutil.which(tool) is None:
        missing.append(tool)

if missing:
    print("missing: " + ", ".join(missing), file=sys.stderr)
    print("see docs/student-quick-start/BUILD.md for the apt install line", file=sys.stderr)
    sys.exit(1)
print("toolchain OK")
EOF

echo
echo "== composing screenshots =="
python3 "$HERE/tools/compose_screenshots.py"

echo
echo "== rendering the guide =="
python3 "$HERE/build.py"

echo
echo "== inspecting the PDF =="
python3 "$HERE/tools/inspect_pdf.py" "$PDF"

echo
echo "== result =="
PAGES="$(pdfinfo "$PDF" | awk -F': *' '/^Pages/ {print $2}')"
SHA="$(sha256sum "$PDF" | awk '{print $1}')"
echo "pages: $PAGES"
echo "sha256: $SHA"
echo "pdf: $PDF"
