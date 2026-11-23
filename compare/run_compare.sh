#!/bin/bash
# Compare all converted documents by their text: duplicates, versions (with change reports), containment.
# Usage: DOCS_DIR="/path/to/Word files" bash compare/run_compare.sh   (needs python-docx, openpyxl)
set -e
: "${DOCS_DIR:?Set DOCS_DIR to the folder of converted .docx files}"
PY="${PYTHON:-python3}"; D="$(cd "$(dirname "$0")" && pwd)"
for s in extract compare classify diffs excel; do echo "== $s"; "$PY" "$D/$s.py" "$DOCS_DIR"; done
echo "Results: $DOCS_DIR/Document Comparison/"
