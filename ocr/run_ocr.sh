#!/bin/bash
# Convert every document in IN_DIR to a text-only Word file in OUT_DIR (OCR for scans, English + Hindi).
# Usage: bash ocr/run_ocr.sh "/path/to/originals" "/path/to/Word output"
# Safe to stop (Ctrl+C) and re-run: finished files are skipped.
set -e
IN="${1:?input folder}"; OUT="${2:?output folder}"
DIR="$(cd "$(dirname "$0")" && pwd)"
caffeinate -i "$HOME/kb-ocr/venv/bin/python" "$DIR/convert_mac.py" "$IN" "$OUT"
