#!/bin/bash
# One-time setup of the local search index + MCP server (macOS, Apple silicon).
# Usage: bash scripts/setup_rag.sh            (uses ./config.json, or config.example.json as a template)
set -e
REPO="$(cd "$(dirname "$0")/.." && pwd)"; H="$HOME/KnowledgeRAG"; mkdir -p "$H/app" "$H/hf"
BREW=$(command -v brew || ls "$HOME/.homebrew/bin/brew" /opt/homebrew/bin/brew /usr/local/bin/brew 2>/dev/null | head -1 || true)
[ -n "$BREW" ] || { echo "Homebrew not found - install from https://brew.sh"; exit 1; }
echo "1/4 Python 3.12 ..."; "$BREW" list python@3.12 >/dev/null 2>&1 || "$BREW" install python@3.12
PY="$("$BREW" --prefix)/bin/python3.12"
echo "2/4 Build environment (PyTorch etc., ~2 GB) ..."
[ -d "$H/venv-build" ] || "$PY" -m venv "$H/venv-build"
"$H/venv-build/bin/pip" install -q --upgrade pip
"$H/venv-build/bin/pip" install -q -r "$REPO/requirements-build.txt"
echo "3/4 Installing app + config ..."
cp "$REPO"/rag/*.py "$H/app/"
if [ ! -f "$H/config.json" ]; then
  if [ -f "$REPO/config.json" ]; then cp "$REPO/config.json" "$H/config.json"; else cp "$REPO/config.example.json" "$H/config.json"; fi
fi
echo "   config: $H/config.json"
"$H/venv-build/bin/python" - "$H/config.json" <<'PY'
import json, os, sys
c = json.load(open(sys.argv[1])); d = os.path.expanduser(c["docs_dir"])
n = sum(1 for _, _, fs in os.walk(d) for f in fs if f.endswith(".docx")) if os.path.isdir(d) else 0
print(f"   docs_dir: {d} -> {n} .docx files" + ("" if n else "   <-- EDIT config.json: folder not found or empty"))
PY
echo "4/4 Registering with Claude Desktop ..."
"$H/venv-build/bin/python" "$REPO/scripts/install_claude.py" "$H/venv-build/bin/python" "$H/app/kb_server.py" "$H/config.json"
echo; echo "Setup done. Next: bash scripts/build_index.sh"
