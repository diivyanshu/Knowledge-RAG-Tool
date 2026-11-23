#!/bin/bash
# Build (or update) the index. First run downloads the models (~4.5 GB) and embeds all chunks.
# Safe to stop with Ctrl+C and re-run: it continues where it stopped.
H="$HOME/KnowledgeRAG"; REPO="$(cd "$(dirname "$0")/.." && pwd)"; cp "$REPO"/rag/*.py "$H/app/"
PYB="$H/venv-build/bin/python"; [ -x "$PYB" ] || PYB="$H/venv-slim/bin/python"
export KB_RAG_CONFIG="$H/config.json" HF_HOME="$H/hf" TOKENIZERS_PARALLELISM=false PYTORCH_ENABLE_MPS_FALLBACK=1
caffeinate -i "$PYB" "$H/app/build_index.py" "$@"
du -sh "$H"/kb_index.sqlite 2>/dev/null
