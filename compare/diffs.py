import os, re, pickle, difflib, time, sys
from docx import Document
from docx.shared import Pt, RGBColor
from docx.oxml.ns import qn
import os
import os
WORK=os.path.expanduser(os.environ.get("COMPARE_WORK","~/KnowledgeRAG/compare_work")); DOCS=os.path.expanduser(os.environ["DOCS_DIR"])
OUTDIR=os.path.join(DOCS,"Document Comparison")
T=os.path.join(WORK,'text'); OUT=os.path.join(OUTDIR,'Version comparisons')
os.makedirs(OUT,exist_ok=True)
C=pickle.load(open(os.path.join(WORK,'classified.pkl'),'rb')); cat=C['cat']; prim=C['prim']
best={}
for a,b,j,ca,cb,k in C['pairs']:
    if k!='Version / near-copy': continue
    A=prim.get(a,a); B=prim.get(b,b)
    if A==B: continue
    key=tuple(sorted((A,B))); best[key]=max(best.get(key,(0,)), (j,ca,cb) if key==(A,B) else (j,cb,ca))
def dkey(n):
    c=cat[n]; s=c['date_text'] or c['date_name']
    return (s[6:10]+s[3:5]+s[:2]) if s else '9999'
vers=[]
for (A,B),(j,ca,cb) in sorted(best.items()):
    if dkey(B)<dkey(A): A,B,ca,cb=B,A,cb,ca
    vers.append((A,B,j,ca,cb))
vers.sort(key=lambda v:(v[0],v[1]))
ILL=re.compile('[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff￾￿]')
def paras(n):
    t=open(os.path.join(T,n+'.txt')).read().split('\n')[2:]
    toks=[]; pg=1
    for l in t:
        m=re.match(r'— Page (\d+)',l)
        if m: pg=int(m.group(1)); continue
        l=ILL.sub('',l.strip())
        if l: toks.append((l,pg))
    out=[]; buf=''; bpg=1
    for l,pg in toks:
        if not buf: bpg=pg
        buf=(buf+' '+l).strip()
        parts=re.split(r'(?<=[.;?!।])\s+(?=[A-Z0-9(\u0900-\u097F])',buf)
        for p in parts[:-1]: out.append((p,bpg)); bpg=pg
        buf=parts[-1]
        if len(buf)>600: out.append((buf,bpg)); buf=''
    if buf: out.append((buf,bpg))
    return out
K=lambda s: re.sub(r'[^a-z0-9ऀ-ॿ]+','',s.lower())
def doc():
    d=Document(); st=d.styles['Normal']; st.font.name='Calibri'; st.font.size=Pt(10)
    st.element.get_or_add_rPr().get_or_add_rFonts().set(qn('w:cs'),'Kohinoor Devanagari'); return d
def add(d,label,txt,color,pg):
    p=d.add_paragraph(); r=p.add_run(f'{label} (p.{pg}) '); r.bold=True; r.font.color.rgb=RGBColor(*color); p.add_run(txt[:1500])
def addchg(d,o):
    wa,wb=o[1].split(),o[3].split()
    sm=difflib.SequenceMatcher(None,[K(x) for x in wa],[K(x) for x in wb],autojunk=False)
    for lab,words,side,pg,col in (('CHANGED – was',wa,0,o[2],(0xB0,0x20,0x20)),('            now',wb,1,o[4],(0x1A,0x7F,0x37))):
        p=d.add_paragraph(); r=p.add_run(f'{lab} (p.{pg}) '); r.bold=True; r.font.color.rgb=RGBColor(0xB0,0x60,0x00)
        for op,i1,i2,j1,j2 in sm.get_opcodes():
            seg=words[i1:i2] if side==0 else words[j1:j2]
            if not seg: continue
            r=p.add_run(' '.join(seg)[:1500]+' ')
            if op!='equal': r.bold=True; r.font.color.rgb=RGBColor(*col)
t0=time.time(); made=0
names=[]
for i,(A,B,j,ca,cb) in enumerate(vers,1):
    fn=f'V{i:03d} - {A[:45].strip()} vs {B[:45].strip()}.docx'.replace('/','-')
    names.append(fn)
    p=os.path.join(OUT,fn)
    if os.path.exists(p) and not os.environ.get('FORCE'): continue
    if time.time()-t0>float(os.environ.get('TIME_LIMIT','1e9')): break
    pa,pb=paras(A),paras(B)
    sm=difflib.SequenceMatcher(None,[K(x) for x,_ in pa],[K(x) for x,_ in pb],autojunk=False)
    d=doc(); d.add_heading('Version comparison',1)
    for lab,n in (('Older / A',A),('Newer / B',B)):
        c=cat[n]; d.add_paragraph(f'{lab}: {c["src"]}  |  date: {c["date_text"] or c["date_name"] or "unknown"}  |  ref: {c["ref"] or "-"}')
    d.add_paragraph(f'Similarity: {j:.0%} overall; {ca:.0%} of A appears in B; {cb:.0%} of B appears in A.')
    d.add_paragraph('Minor differences (OCR noise, spacing, small wording changes above 90% match) are counted but not listed.').runs[0].italic=True
    rem=addd=chg=minor=0; out=[]
    for op,i1,i2,j1,j2 in sm.get_opcodes():
        if op=='equal': continue
        A_=pa[i1:i2]; B_=pb[j1:j2]
        if op=='replace':
            used=set()
            for x,pg in A_:
                bestr,bi=0,None
                for bi_,(y,_) in enumerate(B_):
                    if bi_ in used: continue
                    r=difflib.SequenceMatcher(None,K(x),K(y)).quick_ratio()
                    if r>bestr: bestr,bi=r,bi_
                if bi is not None and bestr>=0.6:
                    used.add(bi); r=difflib.SequenceMatcher(None,K(x),K(B_[bi][0])).ratio()
                    if r>=0.9: minor+=1
                    else: chg+=1; out.append(('chg',x,pg,B_[bi][0],B_[bi][1]))
                else: rem+=1; out.append(('rem',x,pg))
            for bi_,(y,pg) in enumerate(B_):
                if bi_ not in used: addd+=1; out.append(('add',y,pg))
        elif op=='delete': rem+=len(A_); out+= [('rem',x,pg) for x,pg in A_]
        elif op=='insert': addd+=len(B_); out+= [('add',y,pg) for y,pg in B_]
    d.add_paragraph(f'Summary: {chg} changed passages, {rem} only in A (removed), {addd} only in B (added), {minor} minor differences.')
    d.add_heading('Differences',2)
    out=[o for o in out if len(re.findall(r'\w+',o[1]))>=4 or o[0]=='chg']
    for o in out[:400]:
        if o[0]=='rem': add(d,'REMOVED',o[1],(0xB0,0x20,0x20),o[2])
        elif o[0]=='add': add(d,'ADDED',o[1],(0x1A,0x7F,0x37),o[2])
        else: addchg(d,o)
    if len(out)>400: d.add_paragraph(f'[{len(out)-400} further differences not shown – the documents differ substantially]')
    d.save(p+'.part'); os.replace(p+'.part',p); made+=1
pickle.dump({'vers':vers,'names':names},open(os.path.join(WORK,'vers.pkl'),'wb'))
print('made',made,'existing total',len([f for f in os.listdir(OUT) if f.endswith('.docx')]),'of',len(vers),round(time.time()-t0),'s')
