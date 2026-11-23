#!/bin/bash
# Re-index only new, changed or removed documents (run after adding files to the docs folder).
H="$HOME/KnowledgeRAG"; PYB="$H/venv-slim/bin/python"; [ -x "$PYB" ] || PYB="$H/venv-build/bin/python"
export KB_RAG_CONFIG="$H/config.json" HF_HOME="$H/hf" TOKENIZERS_PARALLELISM=false
caffeinate -i "$PYB" "$H/app/build_index.py" "$@"
