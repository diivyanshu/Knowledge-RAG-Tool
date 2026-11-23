import os, sys, time, docx, json
import os
WORK=os.path.expanduser(os.environ.get("COMPARE_WORK","~/KnowledgeRAG/compare_work")); DOCS=os.path.expanduser(os.environ["DOCS_DIR"])
OUTDIR=os.path.join(DOCS,"Document Comparison")
W=DOCS; OUT=os.path.join(WORK,'text'); os.makedirs(OUT,exist_ok=True); LIMIT=float(os.environ.get('TIME_LIMIT','1e9')); t0=time.time(); n=0
files=sorted(f for f in os.listdir(W) if f.endswith('.docx'))
for f in files:
    o=os.path.join(OUT,f[:-5]+'.txt'); src=os.path.join(W,f)
    if os.path.exists(o) and os.path.getmtime(o)>=os.path.getmtime(src): continue
    if time.time()-t0>LIMIT: break
    try:
        d=docx.Document(src); parts=[p.text for p in d.paragraphs]
        for tb in d.tables:
            for r in tb.rows: parts.append(' | '.join(c.text for c in r.cells))
        open(o,'w').write('\n'.join(parts)); n+=1
    except Exception as e: print('ERR',f,e)
done=len(os.listdir(OUT)); print('extracted now',n,'total',done,'of',len(files))
