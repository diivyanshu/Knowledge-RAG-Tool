# Knowledge-RAG-Tool

Turn any large pile of documents (scanned PDFs, Word files, slides, spreadsheets, emails, in English,
Hindi or 100+ other languages) into a **private, searchable knowledge base that Claude answers from,
with citations to file and page**. Everything runs on your Mac. Only the few passages retrieved for a
question are sent to Claude. No cloud database, no API costs, no fine-tuning.

**Works for any text-heavy collection**, for example:
- **Policy & compliance**: circulars, guidelines, manuals, legal orders (the original use: ~2,000 files, ~27,600 pages)
- **Research / science**: papers, theses, lab protocols, datasheets, lecture notes
- **Exam prep (UPSC, CA, medicine, law...)**: NCERTs, standard books, coaching notes, past papers, newspaper cuttings
- **Business**: contracts, SOPs, reports, product docs, email archives
- **Personal**: notes, books, scanned family or property records

**This repository contains code only. No documents, indexes or models are included.**

## How it works

```
 your files (PDF scans, images, DOC/DOCX, XLS, PPT, Outlook .msg)
     │  1. ocr/       OCR with Apple Vision + Tesseract (English + Hindi out of the box),
     ▼                auto-rotation, garbled-font detection -> one text .docx per file
 text files with page numbers
     │  2. compare/   compares documents by their TEXT (not file names): duplicates,
     ▼                versions/editions, "contained in"  ->  Excel catalogue + what-changed reports
 catalogue + version reports
     │  3. rag/       ~300-word chunks -> bge-m3 multilingual embeddings
     ▼                + keyword index, all in one portable .sqlite file
 local index ──► MCP server: search_knowledge · read_document · document_info · find_documents
                        │   hybrid search -> rank fusion -> bge-reranker-v2-m3
                        ▼
                  Claude Desktop / Cowork answers with [file, page] citations
```

Steps 1 and 2 are optional: if your documents already have text (digital PDFs converted to .docx,
your own notes), start at step 3.

### Why it works well
- **Hybrid retrieval**: meaning-based vectors find paraphrases ("rules for appointing dealers" ≈
  "selection guidelines"); keyword search finds exact terms (section numbers, formulas, names, codes).
  Results are fused and re-ranked by a cross-encoder; max 3 passages per document for variety.
- **Multilingual**: `BAAI/bge-m3` and `bge-reranker-v2-m3` cover 100+ languages; ask in English and
  find Hindi passages, or the reverse.
- **Version-aware**: if a newer edition of a document exists, search results say so, so outdated
  rules, syllabi or protocols aren't quoted as current.
- **Small and private**: one SQLite file holds text, keyword index and vectors; search over ~50k
  chunks takes milliseconds. `make_slim.sh` shrinks the install from ~7 GB to ~2 GB (int8 ONNX models),
  and models unload after 10 idle minutes.

## Get the code
```bash
git clone https://github.com/diivyanshu/Knowledge-RAG-Tool.git
cd Knowledge-RAG-Tool
```

## Requirements
macOS on Apple silicon, Homebrew, Claude Desktop (any paid Claude plan), ~7 GB free during the build
(~2 GB afterwards). Tested on a MacBook Air M4, 16 GB.

## 1. Convert documents to text (optional)
```bash
bash ocr/setup_ocr.sh
bash ocr/run_ocr.sh "/path/to/originals" "/path/to/Word files"
```
Re-runnable. `conversion_log.csv` lists OCR confidence and low-confidence pages to check.
Other OCR languages: add the Tesseract model (e.g. `tam`, `ben`, `mar`) to `~/kb-ocr/tessdata`.

## 2. Compare documents (optional, recommended for archives with many copies/editions)
```bash
DOCS_DIR="/path/to/Word files" PYTHON=~/KnowledgeRAG/venv-build/bin/python bash compare/run_compare.sh
```
Creates `Document Comparison.xlsx` (catalogue, duplicate groups, versions, containment, date checks)
and `Version comparisons/*.docx` listing sentences added / removed / changed, with page numbers.

## 3. Build the knowledge base and connect Claude
```bash
cp config.example.json config.json      # point docs_dir at your folder of .docx files
bash scripts/setup_rag.sh               # Python env + registers the MCP server in Claude Desktop
bash scripts/build_index.sh             # downloads models once, indexes everything (resumable)
bash scripts/make_slim.sh               # optional: shrink to ~2 GB
bash scripts/update_index.sh            # later: re-index only new/changed files
```
Restart Claude Desktop; the `knowledge-base` tools appear. Suggested project instructions:
[CLAUDE_INSTRUCTIONS.md](CLAUDE_INSTRUCTIONS.md).

## MCP tools
| Tool | Purpose |
|---|---|
| `search_knowledge(query, top_k, year_from, year_to, doc_type)` | hybrid search; passages with file, pages, date, version notes |
| `read_document(file, page_from, page_to)` | read surrounding pages for context |
| `document_info(file)` | metadata, duplicate copies, older/newer versions + change report |
| `find_documents(name_contains, year_from, year_to, doc_type)` | catalogue lookup |

## Privacy
Documents, index and models stay on your machine; Claude only receives the passages its tools return.
`.gitignore` blocks documents, indexes, models and your `config.json` from ever being committed.

## Layout
```
ocr/       convert_mac.py, setup_ocr.sh, run_ocr.sh
compare/   extract, compare, classify, diffs, excel + run_compare.sh
rag/       common.py, models.py, build_index.py, kb_server.py, make_slim.py
scripts/   setup_rag.sh, build_index.sh, make_slim.sh, update_index.sh, install_claude.py
```

## License
MIT
