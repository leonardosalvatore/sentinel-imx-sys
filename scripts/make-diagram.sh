#!/usr/bin/env bash
# Render the sentinel-imx-sys solution poster (train -> deploy -> run).
#
#   docs/pipeline.dot   --dot-->   docs/pipeline.png
#   docs/make_poster.py --------> docs/sentinel-imx-solution.png
#   convert -------------------->  docs/sentinel-imx-solution.pdf
#
# Requirements (all host tools, no network):
#   - graphviz  (dot)
#   - python3 + Pillow
#   - imagemagick (convert)  [optional; only for the PDF]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DOCS="$ROOT/docs"

DOT_SRC="$DOCS/pipeline.dot"
DIAGRAM_PNG="$DOCS/pipeline.png"
POSTER_PNG="$DOCS/sentinel-imx-solution.png"
POSTER_PDF="$DOCS/sentinel-imx-solution.pdf"

need() { command -v "$1" >/dev/null 2>&1 || { echo "error: '$1' not found on PATH" >&2; exit 1; }; }

need dot
need python3

echo "[1/3] rendering pipeline diagram (graphviz) ..."
dot -Tpng -Gdpi=170 "$DOT_SRC" -o "$DIAGRAM_PNG"

echo "[2/3] composing poster (Pillow) ..."
python3 "$DOCS/make_poster.py"

echo "[3/3] exporting PDF ..."
if command -v convert >/dev/null 2>&1; then
    convert -density 150 "$POSTER_PNG" -quality 92 "$POSTER_PDF"
    echo "wrote $POSTER_PDF"
else
    echo "note: imagemagick 'convert' not found - skipping PDF (PNG is ready)." >&2
fi

echo "done:"
echo "  $DIAGRAM_PNG"
echo "  $POSTER_PNG"
[ -f "$POSTER_PDF" ] && echo "  $POSTER_PDF"
