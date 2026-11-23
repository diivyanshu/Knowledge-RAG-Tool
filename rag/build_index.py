"""Build or incrementally update the knowledge-base index.
Pass 1 parses new/changed .docx files into pages + ~300-word chunks (with page numbers).
Pass 2 embeds any chunks that have no vector yet. Both passes are resumable (Ctrl+C safe).
Usage: python build_index.py [--config path] [--reembed]"""
import argparse, os, re, sys, time
import numpy as np
from common import load_config, connect, fts_text, log

PAGE = re.compile(r"^— Page (\d+)")

def out_name(original):
    b, e = os.path.splitext(original)
    return b + (" (docx)" if e.lower() == ".docx" else "") + ".docx"

def load_catalogue(cfg, db):
    """Optional metadata from compare/'s Document Comparison.xlsx."""
    cat = {}
    x = cfg.get("comparison_xlsx")
    if not x or not os.path.exists(x):
        return cat
    from openpyxl import load_workbook
    wb = load_workbook(x, read_only=True, data_only=True)
    rows = list(wb["Catalogue"].iter_rows(values_only=True)); h = rows[0]
    for r in rows[1:]:
        d = dict(zip(h, r)); cat[out_name(d["Original file"])] = d
    db.execute("DELETE FROM versions")
    if "Versions" in wb.sheetnames:
        vr = list(wb["Versions"].iter_rows(values_only=True))
        for r in vr[1:]:
            d = dict(zip(vr[0], r))
            db.execute("INSERT OR REPLACE INTO versions VALUES(?,?,?,?,?,?,?)",
                       (d["ID"], d["Older / A"], d["Date A"], d["Newer / B"], d["Date B"], d["Similarity %"],
                        os.path.join(cfg.get("comparison_dir") or "", "Version comparisons", d["Comparison file (click)"] or "")))
    log(f"catalogue: {len(cat)} documents")
    return cat

def read_docx(path):
    """Yields (page, section, text) in document order, including tables."""
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph
    d = Document(path)
    title, page, section = None, 1, ""
    for el in d.element.body.iterchildren():
        tag = el.tag.split("}")[-1]
        if tag == "p":
            p = Paragraph(el, d); t = p.text.strip()
            if not t:
                continue
            st = p.style.name if p.style is not None else ""
            m = PAGE.match(t)
            if m:
                page = int(m.group(1)); continue
            if st == "Heading 1" and title is None:
                title = t; continue
            if st.startswith("Heading"):
                section = t; page = 1; continue
            if t.startswith("Source: "):
                continue
            yield title, page, section, t
        elif tag == "tbl":
            for row in Table(el, d).rows:
                cells = []
                for c in row.cells:
                    if c.text.strip() and (not cells or cells[-1] != c.text.strip()):
                        cells.append(c.text.strip())
                if cells:
                    yield title, page, section, " | ".join(cells)

def chunk(paras, size, overlap):
    """paras: list of (page, section, text). Chunks never cross sections."""
    out, buf = [], []   # buf: list of (page, word)
    def flush(sec):
        if buf:
            out.append((sec, buf[0][0], buf[-1][0], " ".join(w for _, w in buf)))
    sec = None
    for page, s, text in paras:
        if s != sec and buf:
            flush(sec); buf.clear()
        sec = s
        for w in text.split():
            buf.append((page, w))
            if len(buf) >= size:
                flush(sec); del buf[:size - overlap]
        buf.append((page, "\n")) if buf else None
    flush(sec)
    return [(s, a, b, re.sub(r"\s*\n\s*", "\n", t).strip()) for s, a, b, t in out if t.strip()]

def year_of(d):
    m = re.search(r"(19|20)\d\d", d or "")
    return int(m.group(0)) if m else None

def index_files(cfg, db, cat):
    root = cfg["docs_dir"]; ex = set(cfg.get("exclude_dirs", []))
    files = []
    for dp, dn, fn in os.walk(root):
        dn[:] = [x for x in dn if x not in ex]
        files += [os.path.join(dp, f) for f in fn if f.endswith(".docx") and not f.startswith(("~$", "."))]
    have = {r[0]: (r[1], r[2]) for r in db.execute("SELECT file, mtime, size FROM docs")}
    seen, changed, t0 = set(), 0, time.time()
    for i, path in enumerate(sorted(files), 1):
        rel = os.path.relpath(path, root); seen.add(rel)
        try:
            st = os.stat(path)
        except OSError:
            continue
        if have.get(rel) == (st.st_mtime, st.st_size):
            continue
        c = cat.get(os.path.basename(rel), {})
        is_main = 0 if (c.get("Main copy?") or "Yes").startswith("No") else 1
        try:
            items = list(read_docx(path))
        except Exception as e:
            log(f"  skip {rel}: {e}"); continue
        title = (items[0][0] if items else None) or os.path.splitext(os.path.basename(rel))[0]
        paras = [(p, s, t) for _, p, s, t in items]
        old = db.execute("SELECT id FROM docs WHERE file=?", (rel,)).fetchone()
        if old:
            for (cid,) in db.execute("SELECT id FROM chunks WHERE doc_id=?", old):
                db.execute("DELETE FROM chunks_fts WHERE rowid=?", (cid,))
            db.execute("DELETE FROM chunks WHERE doc_id=?", old); db.execute("DELETE FROM pages WHERE doc_id=?", old)
            db.execute("DELETE FROM docs WHERE id=?", old)
        date = c.get("Date in text") or c.get("Date in file name") or ""
        index_it = 1 if (is_main or not cfg["main_copies_only"]) else 0
        cur = db.execute("""INSERT INTO docs(file, original, title, doc_type, date, year, ref, subject, dup_group, is_main,
            main_copy, contained_in, pages, indexed, mtime, size) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (rel, c.get("Original file") or title, title, c.get("Type (auto)") or "", date, year_of(date),
             c.get("Reference no. (auto)") or "", c.get("Subject (auto)") or "", c.get("Duplicate group") or "",
             is_main, c.get("Main copy is") or "", c.get("Contained in") or "",
             max([p for p, _, _ in paras] or [0]), index_it, st.st_mtime, st.st_size))
        did = cur.lastrowid
        pages = {}
        for p, s, t in paras:
            pages.setdefault((s, p), []).append(t)
        db.executemany("INSERT INTO pages VALUES(?,?,?,?)", [(did, p, s, "\n".join(t)) for (s, p), t in pages.items()])
        if index_it:
            for s, a, b, t in chunk(paras, cfg["chunk_words"], cfg["overlap_words"]):
                cid = db.execute("INSERT INTO chunks(doc_id, section, page_start, page_end, text) VALUES(?,?,?,?,?)",
                                 (did, s, a, b, t)).lastrowid
                db.execute("INSERT INTO chunks_fts(rowid, tok) VALUES(?,?)", (cid, fts_text(title + " " + s + " " + t)))
        changed += 1
        if changed % 50 == 0:
            db.commit(); log(f"  parsed {changed} changed files ({i}/{len(files)} checked, {time.time()-t0:.0f}s)")
    gone = [r for r in have if r not in seen]
    for rel in gone:
        (did,) = db.execute("SELECT id FROM docs WHERE file=?", (rel,)).fetchone()
        for (cid,) in db.execute("SELECT id FROM chunks WHERE doc_id=?", (did,)):
            db.execute("DELETE FROM chunks_fts WHERE rowid=?", (cid,))
        db.execute("DELETE FROM chunks WHERE doc_id=?", (did,)); db.execute("DELETE FROM pages WHERE doc_id=?", (did,))
        db.execute("DELETE FROM docs WHERE id=?", (did,))
    db.commit()
    log(f"pass 1: {changed} new/changed files parsed, {len(gone)} removed, {len(files)} files in folder")

def embed_missing(cfg, db):
    from models import Embedder
    todo = db.execute("""SELECT c.id, d.title, c.section, c.text FROM chunks c JOIN docs d ON d.id=c.doc_id
                         WHERE c.vector IS NULL ORDER BY c.id""").fetchall()
    log(f"pass 2: {len(todo)} chunks to embed")
    if not todo:
        return
    emb = Embedder(cfg); t0 = time.time(); B = 64
    for i in range(0, len(todo), B):
        part = todo[i:i + B]
        texts = [f"{t}\n{s}\n{x}" if s else f"{t}\n{x}" for _, t, s, x in part]
        v = emb.encode(texts).astype(np.float16)
        db.executemany("UPDATE chunks SET vector=? WHERE id=?", [(v[j].tobytes(), part[j][0]) for j in range(len(part))])
        db.commit()
        done = i + len(part); el = time.time() - t0
        if (i // B) % 10 == 0 or done == len(todo):
            log(f"  embedded {done}/{len(todo)}  ({done/el:.1f}/s, ~{(len(todo)-done)/(done/el)/60:.0f} min left)")
    db.execute("INSERT OR REPLACE INTO meta VALUES('embed_backend', ?)", (emb.backend,)); db.commit()

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--config"); ap.add_argument("--reembed", action="store_true")
    a = ap.parse_args(); cfg = load_config(a.config); db = connect(cfg)
    log(f"docs: {cfg['docs_dir']}\nindex: {cfg['index_path']}")
    if a.reembed:
        db.execute("UPDATE chunks SET vector=NULL"); db.commit()
    index_files(cfg, db, load_catalogue(cfg, db))
    embed_missing(cfg, db)
    n = db.execute("SELECT COUNT(*), SUM(vector IS NOT NULL) FROM chunks").fetchone()
    d = db.execute("SELECT COUNT(*), SUM(indexed) FROM docs").fetchone()
    log(f"done: {d[0]} documents ({d[1]} searchable), {n[0]} chunks ({n[1]} embedded)")
    db.execute("INSERT OR REPLACE INTO meta VALUES('built', ?)", (time.strftime("%Y-%m-%d %H:%M"),)); db.commit()

if __name__ == "__main__":
    main()
