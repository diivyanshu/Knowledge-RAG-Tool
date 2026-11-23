"""Local MCP server: gives Claude search + reading tools over your knowledge base.
Run by Claude Desktop (stdio). Everything stays on this computer; only the passages
returned by these tools are sent to Claude."""
import os, re, sys, threading
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import load_config, connect, fts_query, log
from models import Embedder, Reranker, start_idle_reaper
from mcp.server.fastmcp import FastMCP

CFG = load_config(); DB = connect(CFG)
EMB = Embedder(CFG); RR = Reranker(CFG) if CFG["use_reranker"] else None
start_idle_reaper([m for m in (EMB, RR) if m], CFG["idle_unload_minutes"])
_V = {"ids": None, "mat": None, "doc": None}; _VL = threading.Lock()

def vectors():
    with _VL:
        if _V["mat"] is None:
            rows = DB.execute("SELECT id, doc_id, vector FROM chunks WHERE vector IS NOT NULL ORDER BY id").fetchall()
            _V["ids"] = np.array([r[0] for r in rows]); _V["doc"] = np.array([r[1] for r in rows])
            _V["mat"] = np.frombuffer(b"".join(r[2] for r in rows), dtype=np.float16).reshape(len(rows), -1).astype(np.float32)
            log(f"loaded {len(rows)} vectors")
        return _V

def allowed_docs(year_from, year_to, doc_type):
    q, a = "SELECT id FROM docs WHERE indexed=1", []
    if year_from: q += " AND year>=?"; a.append(year_from)
    if year_to: q += " AND year<=?"; a.append(year_to)
    if doc_type: q += " AND lower(doc_type) LIKE ?"; a.append(f"%{doc_type.lower()}%")
    return None if not (year_from or year_to or doc_type) else {r[0] for r in DB.execute(q, a)}

def newer_versions(original):
    rows = DB.execute("SELECT vid, newer, date_newer, similarity FROM versions WHERE older=?", (original,)).fetchall()
    key = lambda v: (v[2] or "")[6:10] + (v[2] or "")[3:5] + (v[2] or "")[:2]
    return sorted(rows, key=key, reverse=True)[:3]

mcp = FastMCP("knowledge-base", instructions=(
    "Search a private knowledge base of documents (any subject, multilingual). "
    "Always call search_knowledge before answering a question about it, answer only from returned passages, "
    "cite [n] with file and page, prefer the most recent applicable document, and mention newer versions."))

@mcp.tool()
def search_knowledge(query: str, top_k: int = 8, year_from: int | None = None, year_to: int | None = None,
                    doc_type: str | None = None) -> str:
    """Hybrid (meaning + keyword) search over all documents in the knowledge base (works across languages).
    Returns the best passages with file name, page numbers, date, reference no. and version notes.
    Optional filters: year_from/year_to (document year), doc_type (e.g. 'manual', 'paper', 'notes', 'circular').
    Tip: run 2-3 searches with different wording (or another language if the sources use it) for important questions."""
    top_k = max(1, min(top_k, 20)); ok = allowed_docs(year_from, year_to, doc_type)
    V = vectors(); cand = {}
    if len(V["ids"]):
        qv = EMB.encode([query])[0]
        s = V["mat"] @ qv
        if ok is not None:
            s = np.where(np.isin(V["doc"], list(ok)), s, -1)
        for r, i in enumerate(np.argsort(-s)[:60]):
            if s[i] > 0:
                cand[int(V["ids"][i])] = cand.get(int(V["ids"][i]), 0) + 1 / (60 + r)
    fq = fts_query(query)
    if fq:
        rows = DB.execute("""SELECT f.rowid FROM chunks_fts f JOIN chunks c ON c.id=f.rowid
                             WHERE chunks_fts MATCH ? ORDER BY bm25(chunks_fts) LIMIT 120""", (fq,)).fetchall()
        r = 0
        for (cid,) in rows:
            if ok is not None and DB.execute("SELECT doc_id FROM chunks WHERE id=?", (cid,)).fetchone()[0] not in ok:
                continue
            cand[cid] = cand.get(cid, 0) + 1 / (60 + r); r += 1
            if r >= 60: break
    if not cand:
        return "No matching passages found. Try different wording, a synonym, or remove filters."
    pool = sorted(cand, key=cand.get, reverse=True)[:40]
    rows = {r[0]: r for r in DB.execute(f"""SELECT c.id, c.text, c.section, c.page_start, c.page_end, d.original, d.title,
        d.date, d.doc_type, d.ref, d.contained_in, d.id FROM chunks c JOIN docs d ON d.id=c.doc_id
        WHERE c.id IN ({','.join('?'*len(pool))})""", pool)}
    if RR:
        sc = RR.score(query, [f"{rows[c][6]}\n{rows[c][1]}" for c in pool])
        pool = [c for _, c in sorted(zip(sc, pool), reverse=True)]
    out, per_doc = [], {}
    for c in pool:
        r = rows[c]
        if per_doc.get(r[11], 0) >= 3: continue
        per_doc[r[11]] = per_doc.get(r[11], 0) + 1; out.append(r)
        if len(out) >= top_k: break
    txt = [f"{len(out)} passages for: {query}\n(Cite as [n] with file and page. Check 'Newer version' notes before relying on an old rule.)\n"]
    for n, (cid, text, sec, pa, pb, orig, title, date, typ, ref, cont, did) in enumerate(out, 1):
        pg = f"p.{pa}" if pa == pb else f"pp.{pa}-{pb}"
        head = f"[{n}] {orig} | {pg}" + (f" | {sec}" if sec else "") + f" | date: {date or 'unknown'}"
        if typ: head += f" | {typ}"
        if ref: head += f" | ref: {ref}"
        notes = [f"Newer version: {v[1]} ({v[2] or 'date?'}, {v[3]}% similar, see {v[0]})" for v in newer_versions(orig)]
        if cont: notes.append(f"Also appears in: {cont}")
        txt.append(head + ("\n  " + "\n  ".join(notes) if notes else "") + f"\n{text}\n")
    return "\n".join(txt)

def find_doc(file):
    f = file.strip()
    for q in ("SELECT * FROM docs WHERE original=? OR file=? OR title=?",):
        r = DB.execute(q, (f, f, f)).fetchone()
        if r: return r
    rows = DB.execute("SELECT * FROM docs WHERE original LIKE ? ORDER BY is_main DESC, length(original) LIMIT 1", (f"%{f}%",)).fetchone()
    return rows

COLS = "id file original title doc_type date year ref subject dup_group is_main main_copy contained_in pages indexed mtime size".split()

@mcp.tool()
def read_document(file: str, page_from: int = 1, page_to: int | None = None) -> str:
    """Read the full text of a document (or a page range) to check context around a search hit.
    'file' can be the original file name shown in search results, or part of it."""
    r = find_doc(file)
    if not r: return f"No document matching '{file}'. Use find_documents to look it up."
    d = dict(zip(COLS, r)); page_to = page_to or page_from + 4
    rows = DB.execute("SELECT page, section, text FROM pages WHERE doc_id=? AND page BETWEEN ? AND ? ORDER BY rowid",
                      (d["id"], page_from, page_to)).fetchall()
    body, used = [], 0
    for p, s, t in rows:
        piece = f"--- page {p}{' | ' + s if s else ''} ---\n{t}"
        if used + len(piece) > 20000:
            body.append(f"[truncated - ask for pages from {p}]"); break
        body.append(piece); used += len(piece)
    return f"{d['original']} | date: {d['date'] or 'unknown'} | {d['pages']} pages\n" + "\n".join(body or ["(no text on these pages)"])

@mcp.tool()
def document_info(file: str) -> str:
    """Metadata and relationships for one document: date, reference, subject, duplicate copies,
    older/newer versions (with the comparison file that lists exact changes), and where it is reproduced."""
    r = find_doc(file)
    if not r: return f"No document matching '{file}'."
    d = dict(zip(COLS, r)); o = d["original"]
    lines = [f"{o}", f"title: {d['title']}", f"type: {d['doc_type']} | date: {d['date']} | ref: {d['ref']}",
             f"subject: {d['subject']}", f"pages: {d['pages']}"]
    if d["dup_group"]:
        cp = [x[0] for x in DB.execute("SELECT original FROM docs WHERE dup_group=? AND id<>?", (d["dup_group"], d["id"]))]
        lines.append(f"duplicate group {d['dup_group']} ({'main copy' if d['is_main'] else 'copy of ' + d['main_copy']}); other copies: {'; '.join(cp)}")
    for v in DB.execute("SELECT * FROM versions WHERE older=? OR newer=?", (o, o)):
        lines.append(f"{v[0]}: {v[1]} ({v[2]})  ->  {v[3]} ({v[4]}), {v[5]}% similar. Changes listed in: {v[6]}")
    if d["contained_in"]: lines.append(f"also reproduced in: {d['contained_in']}")
    return "\n".join(lines)

@mcp.tool()
def find_documents(name_contains: str = "", year_from: int | None = None, year_to: int | None = None,
                   doc_type: str | None = None, limit: int = 30) -> str:
    """List documents by words in their file name/title, year range or type (catalogue lookup, not full-text)."""
    q, a = "SELECT original, date, doc_type, pages, is_main FROM docs WHERE 1=1", []
    for w in name_contains.split():
        q += " AND (original LIKE ? OR title LIKE ? OR subject LIKE ?)"; a += [f"%{w}%"] * 3
    if year_from: q += " AND year>=?"; a.append(year_from)
    if year_to: q += " AND year<=?"; a.append(year_to)
    if doc_type: q += " AND lower(doc_type) LIKE ?"; a.append(f"%{doc_type.lower()}%")
    rows = DB.execute(q + " ORDER BY year DESC, original LIMIT ?", a + [min(limit, 100)]).fetchall()
    return "\n".join(f"{o} | {dt or '?'} | {t or '-'} | {p}p{'' if m else ' | copy'}" for o, dt, t, p, m in rows) or "No documents found."

if __name__ == "__main__":
    log(f"knowledge-base MCP server: index {CFG['index_path']}")
    mcp.run()
