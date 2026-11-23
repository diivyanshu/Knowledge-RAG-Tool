"""Shared config, text normalisation and SQLite schema for the knowledge-base index."""
import json, os, re, sqlite3, sys

DEFAULT_CONFIG = {
    "docs_dir": "~/KnowledgeBase/Word",          # folder of converted .docx files
    "comparison_xlsx": "",                     # optional: Document Comparison.xlsx from compare/
    "comparison_dir": "",                      # optional: folder holding 'Version comparisons'
    "exclude_dirs": ["Document Comparison", "_to_delete"],
    "index_path": "~/KnowledgeRAG/kb_index.sqlite",
    "embed_model": "BAAI/bge-m3",
    "rerank_model": "BAAI/bge-reranker-v2-m3",
    "use_reranker": True,
    "onnx_dir": "~/KnowledgeRAG/onnx",            # created by make_slim.py
    "chunk_words": 300,
    "overlap_words": 50,
    "embed_max_tokens": 1024,
    "main_copies_only": True,
    "idle_unload_minutes": 10,
}

def log(*a):
    print(*a, file=sys.stderr, flush=True)   # stdout is reserved for MCP

def load_config(path=None):
    path = os.path.expanduser(path or os.environ.get("KB_RAG_CONFIG", "~/KnowledgeRAG/config.json"))
    cfg = dict(DEFAULT_CONFIG)
    if os.path.exists(path):
        cfg.update(json.load(open(path)))
    for k in ("docs_dir", "comparison_xlsx", "comparison_dir", "index_path", "onnx_dir"):
        if cfg.get(k):
            cfg[k] = os.path.expanduser(cfg[k])
    cfg["_path"] = path
    return cfg

# Devanagari vowel signs are not \w in Python, so include the whole block explicitly.
TOKEN = re.compile(r"[0-9a-zऀ-ॿ]+")
STOP = set("""a an and are as at be by for from has have in is it of on or that the this to was were will with
shall may any all not under such which their its been also into per""".split())

def tokens(text):
    return TOKEN.findall(text.lower())

def fts_text(text):
    """Normalised, space-separated tokens. Stored in an FTS5 table using the 'ascii'
    tokenizer, which keeps non-ASCII (Hindi) characters inside tokens."""
    return " ".join(tokens(text))

def fts_query(q, max_terms=24):
    seen, terms = set(), []
    for t in tokens(q):
        if t in STOP or t in seen or (len(t) < 2 and not t.isdigit()):
            continue
        seen.add(t); terms.append('"%s"' % t)
    return " OR ".join(terms[:max_terms])

SCHEMA = """
CREATE TABLE IF NOT EXISTS docs(
  id INTEGER PRIMARY KEY, file TEXT UNIQUE, original TEXT, title TEXT, doc_type TEXT,
  date TEXT, year INTEGER, ref TEXT, subject TEXT, dup_group TEXT, is_main INTEGER,
  main_copy TEXT, contained_in TEXT, pages INTEGER, indexed INTEGER, mtime REAL, size INTEGER);
CREATE TABLE IF NOT EXISTS pages(doc_id INTEGER, page INTEGER, section TEXT, text TEXT);
CREATE INDEX IF NOT EXISTS pages_doc ON pages(doc_id, page);
CREATE TABLE IF NOT EXISTS chunks(
  id INTEGER PRIMARY KEY, doc_id INTEGER, section TEXT, page_start INTEGER, page_end INTEGER,
  text TEXT, vector BLOB);
CREATE INDEX IF NOT EXISTS chunks_doc ON chunks(doc_id);
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(tok, tokenize='ascii');
CREATE TABLE IF NOT EXISTS versions(
  vid TEXT PRIMARY KEY, older TEXT, date_older TEXT, newer TEXT, date_newer TEXT,
  similarity INTEGER, comparison_file TEXT);
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
"""

def connect(cfg):
    os.makedirs(os.path.dirname(cfg["index_path"]), exist_ok=True)
    db = sqlite3.connect(cfg["index_path"], check_same_thread=False)
    db.executescript(SCHEMA)
    return db
