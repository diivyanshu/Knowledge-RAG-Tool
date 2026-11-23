#!/bin/bash
# One-time setup for the document converter (runs fully on this Mac).
set -e
T="$HOME/kb-ocr"; mkdir -p "$T/tessdata"
echo "1/4 Finding Homebrew..."
BREW=$(command -v brew || ls "$HOME/.homebrew/bin/brew" /opt/homebrew/bin/brew /usr/local/bin/brew 2>/dev/null | head -1 || true)
if [ -z "$BREW" ]; then echo "Homebrew not found. Install it from https://brew.sh then re-run."; exit 1; fi
echo "2/4 Installing Tesseract (used for Hindi pages)..."
"$BREW" list tesseract >/dev/null 2>&1 || "$BREW" install tesseract
echo "3/4 Downloading English + Hindi OCR models..."
for l in hin eng; do [ -s "$T/tessdata/$l.traineddata" ] || curl -fsSL -o "$T/tessdata/$l.traineddata" "https://github.com/tesseract-ocr/tessdata_best/raw/main/$l.traineddata"; done
[ -s "$T/tessdata/osd.traineddata" ] || curl -fsSL -o "$T/tessdata/osd.traineddata" "https://github.com/tesseract-ocr/tessdata/raw/main/osd.traineddata"
echo "4/4 Setting up Python packages..."
PY=$(command -v python3)
[ -d "$T/venv" ] || "$PY" -m venv "$T/venv"
"$T/venv/bin/pip" install -q --upgrade pip
"$T/venv/bin/pip" install -q ocrmac pypdfium2 python-docx openpyxl xlrd python-pptx extract_msg pillow
"$T/venv/bin/python" -c "import ocrmac, pypdfium2, docx; print('Setup complete.')"
"$T/venv/bin/python" "$(dirname "$0")/convert_mac.py" --check
