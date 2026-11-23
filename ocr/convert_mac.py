#!/usr/bin/env python3
"""Convert documents (scans, PDFs, Office files, emails) to text-only Word files, entirely on this Mac.
English OCR: Apple Vision (via ocrmac). Hindi pages: Vision if supported, else Tesseract.
Usage: convert_mac.py IN_DIR OUT_DIR   |   convert_mac.py --check"""
import os, sys, re, csv, subprocess, tempfile, shutil, time, json, hashlib, multiprocessing as mp

T = os.path.expanduser('~/kb-ocr')
TESS = os.path.join(T, 'tessdata')
CACHE = os.path.join(T, 'cache')
STOP = set('the of and to in is for be by with on as that this are shall will from or it at an has have not may all any which'.split())
DEVA = re.compile(r'[ऀ-ॿ]')
BROKEN = re.compile('[\u00A2-\u00FF\u0100-\u024F]')
ILLEGAL = re.compile('[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\ud800-\udfff\ufffe\uffff]')
MAX_ROWS = 1000
LOW_CONF = 60
os.environ.setdefault('OMP_THREAD_LIMIT', '1')

def run(cmd, timeout=600):
    return subprocess.run(cmd, capture_output=True, timeout=timeout)

# ---------- OCR engines ----------
_VISION = None
def vision_langs():
    global _VISION
    if _VISION is None:
        try:
            import Vision
            req = Vision.VNRecognizeTextRequest.alloc().init()
            req.setRecognitionLevel_(0)
            langs, _ = req.supportedRecognitionLanguagesAndReturnError_(None)
            _VISION = [str(l) for l in langs]
        except Exception:
            _VISION = []
    return _VISION

def hindi_in_vision():
    return any(l.lower().startswith('hi') for l in vision_langs())

def vision_ocr(img, hindi=False):
    from ocrmac import ocrmac
    langs = ['en-US'] + (['hi-IN'] if hindi else [])
    res = ocrmac.OCR(img, recognition_level='accurate', language_preference=langs).recognize()
    items = [(t, c, b) for t, c, b in res if t.strip()]
    if not items: return '', None
    items.sort(key=lambda x: (-(x[2][1] + x[2][3]), x[2][0]))
    hs = sorted(b[3] for _, _, b in items); mh = hs[len(hs) // 2] or 0.01
    lines, cur, cur_top, prev_bot = [], [], None, None
    for t, c, b in items:
        top = b[1] + b[3]
        if cur and abs(top - cur_top) < mh * 0.5:
            cur.append((b[0], t)); continue
        if cur:
            lines.append(' '.join(x for _, x in sorted(cur)))
            if prev_bot is not None and prev_bot - top > mh * 1.2: lines.append('')
        prev_bot = min(b2[1] for _, _, b2 in items if abs((b2[1] + b2[3]) - cur_top) < mh * 0.5) if cur else None
        cur, cur_top = [(b[0], t)], top
    if cur: lines.append(' '.join(x for _, x in sorted(cur)))
    conf = 100 * sum(c for _, c, _ in items) / len(items)
    return '\n'.join(lines), conf

def tess_ocr(png, lang):
    r = run(['tesseract', png, '-', '--tessdata-dir', TESS, '-l', lang, '--psm', '3', '-c', 'tessedit_create_tsv=1'], 900)
    out, confs, cur, key = [], [], [], None
    for row in r.stdout.decode('utf-8', 'ignore').splitlines()[1:]:
        p = row.split('\t')
        if len(p) < 12 or p[0] != '5' or not p[11].strip(): continue
        k = (p[2], p[3], p[4])
        if key is not None and k != key:
            out.append(' '.join(cur)); cur = []
            if k[:2] != key[:2]: out.append('')
        key = k; cur.append(p[11])
        try: confs.append(float(p[10]))
        except ValueError: pass
    if cur: out.append(' '.join(cur))
    return '\n'.join(out), (sum(confs) / len(confs) if confs else None)

def osd(png):
    r = run(['tesseract', png, '-', '--tessdata-dir', TESS, '--psm', '0'], 120).stdout.decode('utf-8', 'ignore')
    rot = re.search(r'Rotate:\s*(\d+)', r); oc = re.search(r'Orientation confidence:\s*([\d.]+)', r)
    sc = re.search(r'Script:\s*(\w+)', r); scc = re.search(r'Script confidence:\s*([\d.]+)', r)
    rot = int(rot.group(1)) if rot and oc and float(oc.group(1)) > 2 else 0
    script = sc.group(1) if sc and scc and float(scc.group(1)) > 1 else 'Latin'
    return rot, script

def ocr_pil(im, tmp):
    """OCR one page image: fix rotation, detect Hindi, choose engine."""
    from PIL import Image
    im = im.convert('L')
    if max(im.size) > 5000: im.thumbnail((5000, 5000))
    png = os.path.join(tmp, f'pg{os.getpid()}.png'); im.save(png)
    rot, script = osd(png)
    if rot:
        im = im.rotate(-rot, expand=True); im.save(png)
    hindi = script == 'Devanagari'
    try:
        if hindi:  # Apple Vision's Hindi output proved unreliable; use Tesseract Hindi
            t, c = tess_ocr(png, 'hin+eng'); eng = 'tesseract-hin'
        else:
            t, c = vision_ocr(im, hindi); eng = 'vision'
    except ImportError:
        t, c = tess_ocr(png, 'hin+eng' if hindi else 'eng'); eng = 'tesseract'
    os.remove(png)
    return t, 'ocr', c, eng

# ---------- extractors ----------
def text_ok(t):
    t = t.strip()
    if len(t) < 40: return False
    nd = len(DEVA.findall(t))
    if nd > 20 and len(BROKEN.findall(t)) > 0.02 * nd: return False   # Hindi in legacy font -> garbled, OCR instead
    if nd > 0.3 * len(re.findall(r'\S', t)): return True
    toks = re.findall(r'[A-Za-z]+', t.lower())
    return len(toks) >= 8 and sum(w in STOP for w in toks) / len(toks) >= 0.07

def pdf_pages(path, tmp):
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(path)
    st = os.stat(path)
    cdir = os.path.join(CACHE, hashlib.md5(f'v3|{path}|{st.st_size}|{int(st.st_mtime)}'.encode()).hexdigest())
    os.makedirs(cdir, exist_ok=True)
    out = []
    for i in range(len(pdf)):
        cp = os.path.join(cdir, f'{i}.json')
        if os.path.exists(cp):
            out.append(tuple(json.load(open(cp)))); continue
        page = pdf[i]
        try: t = page.get_textpage().get_text_range()
        except Exception: t = ''
        if text_ok(t): res = (t, 'text', None, 'pdf-text')
        else:
            try: res = ocr_pil(page.render(scale=300 / 72).to_pil(), tmp)
            except Exception as e: res = (f'[Page could not be read: {e}]', 'error', None, '')
        json.dump(res, open(cp + '.part', 'w')); os.replace(cp + '.part', cp)
        out.append(res)
    pdf.close()
    return out

def image_pages(path, tmp):
    from PIL import Image, ImageSequence
    im = Image.open(path)
    return [ocr_pil(fr.copy(), tmp) for fr in ImageSequence.Iterator(im)]

def textutil(path, tmp):
    o = os.path.join(tmp, 'tu.txt')
    run(['textutil', '-convert', 'txt', '-encoding', 'UTF-8', '-output', o, path], 300)
    if not os.path.exists(o): raise ValueError('textutil could not read file')
    return open(o, 'rb').read().decode('utf-8', 'ignore')

def sheets(path):
    res = []
    if path.lower().endswith('.xls'):
        import xlrd
        wb = xlrd.open_workbook(path)
        for sh in wb.sheets():
            rows = [[str(c.value) if c.value != '' else '' for c in sh.row(r)] for r in range(min(sh.nrows, MAX_ROWS + 1))]
            res.append((sh.name, rows, sh.nrows))
    else:
        import openpyxl
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        for ws in wb.worksheets:
            rows, n = [], 0
            for r in ws.iter_rows(values_only=True):
                n += 1
                if n <= MAX_ROWS + 1: rows.append(['' if v is None else str(v) for v in r])
            res.append((ws.title, rows, n))
    return res

def msg_parts(path, tmp):
    import extract_msg
    m = extract_msg.Message(path)
    hdr = f"Subject: {m.subject}\nFrom: {m.sender}\nTo: {m.to}\nCc: {m.cc or ''}\nDate: {m.date}"
    body = m.body or ''
    atts = []
    for a in m.attachments:
        name = getattr(a, 'longFilename', None) or getattr(a, 'shortFilename', None) or 'attachment'
        data = getattr(a, 'data', None)
        if not isinstance(data, (bytes, bytearray)): continue
        if name.lower().rsplit('.', 1)[-1] in ('png', 'jpg', 'jpeg', 'gif') and len(data) < 30000: continue
        d = tempfile.mkdtemp(dir=tmp); fp = os.path.join(d, os.path.basename(name))
        open(fp, 'wb').write(data)
        try: atts.append((name, extract(fp, d)))
        except Exception as e: atts.append((name, ('pages', [(f'[Could not convert attachment: {e}]', 'error', None, '')])))
    m.close()
    return hdr, body, atts

def extract(path, tmp):
    ext = path.lower().rsplit('.', 1)[-1] if '.' in os.path.basename(path) else ''
    if ext == 'pdf': return ('pages', pdf_pages(path, tmp))
    if ext in ('tif', 'tiff', 'jpg', 'jpeg', 'png', 'jfif', 'bmp', 'gif'): return ('pages', image_pages(path, tmp))
    if ext in ('xls', 'xlsx'): return ('tables', sheets(path))
    if ext == 'pptx':
        from pptx import Presentation
        return ('pages', [('\n'.join(sh.text_frame.text for sh in s.shapes if sh.has_text_frame), 'text', None, 'pptx')
                          for s in Presentation(path).slides])
    if ext in ('doc', 'docx', 'rtf', 'htm', 'html', 'odt', 'webarchive'): return ('pages', [(textutil(path, tmp), 'text', None, 'textutil')])
    if ext in ('txt', 'log', 'csv'): return ('pages', [(open(path, 'rb').read().decode('utf-8', 'ignore'), 'text', None, 'text')])
    if ext == 'msg': return ('msg', msg_parts(path, tmp))
    head = open(path, 'rb').read(8)
    if head[:4] in (b'II*\x00', b'MM\x00*') or head[:3] == b'\xff\xd8\xff' or head[:4] == b'\x89PNG': return ('pages', image_pages(path, tmp))
    if head.startswith(b'%PDF'): return ('pages', pdf_pages(path, tmp))
    if head.startswith(b'\xd0\xcf\x11\xe0'): return ('msg', msg_parts(path, tmp))
    raise ValueError(f'unsupported file type ({ext or "no extension"})')

# ---------- Word output ----------
def clean(t): return ILLEGAL.sub('', t or '')

def add_text(doc, t):
    for para in re.split(r'\n\s*\n', clean(t).replace('\f', '')):
        if para.strip(): doc.add_paragraph(re.sub(r'[ \t]{3,}', '   ', para.strip('\n')))

def write_content(doc, kind, content, stats):
    from docx.shared import Pt
    if kind == 'pages':
        for i, (t, how, conf, eng) in enumerate(content, 1):
            stats['pages'] += 1; stats['eng'].add(eng)
            low = how == 'ocr' and conf is not None and conf < LOW_CONF
            if how == 'ocr':
                stats['ocr'] += 1
                if conf is not None: stats['conf'].append(conf)
                if low: stats['low'].append(i)
            if len(content) > 1 or low:
                p = doc.add_paragraph(); r = p.add_run(f'— Page {i}' + (' (OCR, low confidence — check original)' if low else '') + ' —')
                r.italic = True; r.font.size = Pt(9)
            add_text(doc, t)
    elif kind == 'tables':
        for name, rows, n in content:
            doc.add_heading(f'Sheet: {name}', level=2); stats['pages'] += 1
            rows = [r for r in rows if any(c.strip() for c in r)]
            if not rows: doc.add_paragraph('(empty)'); continue
            w = min(max(len(r) for r in rows), 30)
            tb = doc.add_table(rows=0, cols=w); tb.style = 'Table Grid'
            for r in rows:
                cells = tb.add_row().cells
                for j, v in enumerate(r[:w]): cells[j].text = clean(v)[:500]
            if n > MAX_ROWS + 1: doc.add_paragraph(f'[Truncated: first {MAX_ROWS} of {n - 1} rows shown]')
    elif kind == 'msg':
        hdr, body, atts = content
        add_text(doc, hdr); doc.add_heading('Message', level=2); add_text(doc, body); stats['pages'] += 1
        for name, (k, c) in atts:
            doc.add_heading(clean(f'Attachment: {name}'), level=2); write_content(doc, k, c, stats)

def new_doc():
    from docx import Document
    from docx.shared import Pt
    from docx.oxml.ns import qn
    d = Document(); st = d.styles['Normal']; st.font.name = 'Calibri'; st.font.size = Pt(11)
    rf = st.element.get_or_add_rPr().get_or_add_rFonts()
    rf.set(qn('w:cs'), 'Kohinoor Devanagari'); rf.set(qn('w:ascii'), 'Calibri'); rf.set(qn('w:hAnsi'), 'Calibri')
    return d

def out_name(rel, outroot):
    base, ext = os.path.splitext(rel)
    return os.path.join(outroot, base + (' (docx)' if ext.lower() == '.docx' else '') + '.docx')

def job(args):
    src, rel, outroot = args
    out = out_name(rel, outroot); t0 = time.time()
    tmp = tempfile.mkdtemp(prefix='polocr_')
    stats = {'pages': 0, 'ocr': 0, 'low': [], 'conf': [], 'eng': set()}
    try:
        kind, content = extract(src, tmp)
        from docx.shared import Pt
        doc = new_doc(); doc.add_heading(clean(os.path.basename(rel)), level=1)
        r = doc.add_paragraph().add_run(f'Source: {rel}'); r.italic = True; r.font.size = Pt(9)
        write_content(doc, kind, content, stats)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        doc.save(out + '.part'); os.replace(out + '.part', out)
        conf = round(sum(stats['conf']) / len(stats['conf']), 1) if stats['conf'] else ''
        return [rel, 'ok' if stats['pages'] else 'empty', stats['pages'], stats['ocr'], conf,
                ' '.join(map(str, stats['low'][:60])), '+'.join(sorted(e for e in stats['eng'] if e)), f'{time.time() - t0:.0f}s']
    except Exception as e:
        return [rel, 'error', '', '', '', '', '', f'{type(e).__name__}: {e}'[:300]]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

def main():
    if sys.argv[1:] == ['--check']:
        print('Apple Vision languages:', ', '.join(vision_langs()) or 'NOT AVAILABLE')
        print('Hindi via Apple Vision:', 'yes' if hindi_in_vision() else 'no -> Hindi pages will use Tesseract')
        print(run(['tesseract', '--version']).stdout.decode().splitlines()[0] if shutil.which('tesseract') else 'tesseract MISSING')
        return
    inroot, outroot = sys.argv[1], sys.argv[2]
    os.makedirs(outroot, exist_ok=True)
    logp = os.path.join(outroot, 'conversion_log.csv')
    done = set()
    if os.path.exists(logp):
        last = {}
        for r in csv.reader(open(logp)):
            if len(r) > 1: last[r[0]] = r[1]
        done = {f for f, st in last.items() if st in ('ok', 'empty')}
    outabs = os.path.abspath(outroot); files = []
    for dp, dn, fn in os.walk(inroot):
        dn[:] = [d for d in dn if os.path.abspath(os.path.join(dp, d)) != outabs]
        for f in sorted(fn):
            if f.startswith(('.', '~$')): continue
            src = os.path.join(dp, f); rel = os.path.relpath(src, inroot)
            if rel in done and os.path.exists(out_name(rel, outroot)): continue
            files.append((src, rel, outroot))
    print(f'Hindi via Apple Vision: {"yes" if hindi_in_vision() else "no (Tesseract used for Hindi pages)"}')
    print(f'{len(done)} files already done, {len(files)} to convert.', flush=True)
    new = not os.path.exists(logp)
    workers = max(2, (os.cpu_count() or 4) - 1)
    t0 = time.time(); n = 0; errs = 0
    with open(logp, 'a', newline='') as lf, mp.get_context('spawn').Pool(workers) as pool:
        w = csv.writer(lf)
        if new: w.writerow(['file', 'status', 'pages', 'ocr_pages', 'avg_ocr_conf', 'low_conf_pages', 'engine', 'time_or_error'])
        for row in pool.imap_unordered(job, files):
            n += 1; errs += row[1] == 'error'
            w.writerow(row); lf.flush()
            el = time.time() - t0; eta = el / n * (len(files) - n)
            print(f'[{n}/{len(files)}] {row[1]:5} {row[0][:70]}   (elapsed {el/60:.0f} min, ~{eta/60:.0f} min left)', flush=True)
    print(f'\nFinished: {n} files, {errs} errors. Log: {logp}')

if __name__ == '__main__':
    main()
