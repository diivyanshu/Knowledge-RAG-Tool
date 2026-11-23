#!/bin/bash
# After the index is built: switch to the small runtime (~2 GB instead of ~7 GB).
# Exports + int8-quantises the models, verifies them, creates a light environment, points Claude Desktop
# at it, then OFFERS to delete PyTorch and the full-size models. Nothing is deleted without a 'y'.
set -e
H="$HOME/KnowledgeRAG"; REPO="$(cd "$(dirname "$0")/.." && pwd)"; cp "$REPO"/rag/*.py "$H/app/"
export KB_RAG_CONFIG="$H/config.json" HF_HOME="$H/hf" TOKENIZERS_PARALLELISM=false
echo "1/3 Exporting + quantising models (needs ~6 GB free temporarily) ..."
"$H/venv-build/bin/python" "$H/app/make_slim.py"
echo "2/3 Creating slim environment ..."
PY=$(ls "$(brew --prefix 2>/dev/null || echo /opt/homebrew)"/bin/python3.12 2>/dev/null || command -v python3.12)
[ -d "$H/venv-slim" ] || "$PY" -m venv "$H/venv-slim"
"$H/venv-slim/bin/pip" install -q --upgrade pip; "$H/venv-slim/bin/pip" install -q -r "$REPO/requirements-slim.txt"
"$H/venv-slim/bin/python" - <<'PY'
import os, sys; sys.path.insert(0, os.path.expanduser("~/KnowledgeRAG/app"))
import kb_server as s
assert s.EMB.backend == "onnx", "slim models not found"
r = s.search_knowledge("eligibility criteria", top_k=1); print("   test search OK:", r.splitlines()[min(3, len(r.splitlines())-1)][:120])
PY
"$H/venv-slim/bin/python" "$REPO/scripts/install_claude.py" "$H/venv-slim/bin/python" "$H/app/kb_server.py" "$H/config.json"
echo "3/3 Clean-up"; du -sh "$H/venv-build" "$H/hf" 2>/dev/null || true
read -r -p "Delete the build environment and full-size models above? [y/N] " a
if [ "$a" = "y" ] || [ "$a" = "Y" ]; then rm -rf "$H/venv-build" "$H/hf"; echo "   removed."; fi
du -sh "$H"; echo "Done. Restart Claude Desktop."
