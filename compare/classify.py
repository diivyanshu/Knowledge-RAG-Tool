import os, re, pickle, csv, collections, json
import os
WORK=os.path.expanduser(os.environ.get("COMPARE_WORK","~/KnowledgeRAG/compare_work")); DOCS=os.path.expanduser(os.environ["DOCS_DIR"])
OUTDIR=os.path.join(DOCS,"Document Comparison")
T=os.path.join(WORK,'text'); W=DOCS
d=pickle.load(open(os.path.join(WORK,'pairs.pkl'),'rb')); res=d['res']; meta=d['meta']
log={}
lp=os.path.join(W,'conversion_log.csv')
for x in (csv.DictReader(open(lp)) if os.path.exists(lp) else []): log[x['file']]=x
stem2src={}
for f in log:
    b,e=os.path.splitext(f); stem2src[b+(' (docx)' if e.lower()=='.docx' else '')]=f
MON={m:i+1 for i,m in enumerate('jan feb mar apr may jun jul aug sep oct nov dec'.split())}
def dates(s):
    out=[]
    for y,mo,dd in re.findall(r'\b((?:19|20)\d\d)[-./](\d{1,2})[-./](\d{1,2})\b',s): out.append((int(y),int(mo),int(dd)))
    for dd,mo,y in re.findall(r'\b(\d{1,2})[-./ ](\d{1,2})[-./ ]((?:19|20)\d\d|\d\d)\b',s):
        y=int(y); y=y+2000 if y<50 else (y+1900 if y<100 else y); out.append((y,int(mo),int(dd)))
    for dd,mon,y in re.findall(r'\b(\d{1,2})(?:st|nd|rd|th)?[\s.,-]*(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*[\s.,\'-]*((?:19|20)\d\d)\b',s.lower()):
        out.append((int(y),MON[mon],int(dd)))
    return [x for x in out if 1<=x[1]<=12 and 1<=x[2]<=31 and 1950<=x[0]<=2027]
def fmt(x): return f'{x[2]:02d}-{x[1]:02d}-{x[0]}' if x else ''
REF=re.compile(r'(?:\bNo\.?|\bRef\.?|संख्या|सं\.)\s*[:.\-]?\s*([A-Z0-9][A-Za-z0-9\-\(\)\.&]*(?:\s?/\s?[A-Za-z0-9\-\(\)\.&]+){1,8})')
REF2=re.compile(r'\b([A-Z]{1,6}[-.]?\d{2,6}(?:\(\d+\))?(?:/[A-Za-z0-9\-\(\)\.&]+){2,8})')
SUBJ=re.compile(r'^\s*(?:Subject|Sub|विषय)\s*[:.\-–]+\s*(.+)',re.I|re.M)
# File-name keyword -> document type. Edit these for your organisation's naming conventions.
DOC_TYPE_RULES=json.loads(os.environ.get('DOC_TYPE_RULES','null')) or [('paper','Paper'),('thesis','Thesis'),('report','Report'),('lecture','Lecture notes'),('notes','Notes'),('chapter','Chapter'),('book','Book'),('ministry','Ministry letter'),('circular','Circular'),('iom','Office memo'),('memo','Office memo'),('manual','Manual'),('brochure','Brochure'),('compendium','Compendium'),('agreement','Agreement'),('judg','Court order'),('court','Court order'),('sop','SOP'),('guideline','Guidelines'),('policy','Policy'),('faq','FAQ')]
def doctype(name,txt):
    n=name.lower(); e=os.path.splitext(stem2src.get(name,name))[1].lower()
    for k,v in DOC_TYPE_RULES:
        if re.search(r'\b'+k, n): return v
    if e=='.msg' or n.startswith(('fw','re ')) or ' fw ' in n or 'mail' in n: return 'Email'
    if e in ('.xls','.xlsx'): return 'Spreadsheet'
    if e in ('.ppt','.pptx'): return 'Presentation'
    head=txt[:3000].lower()
    if 'circular' in head: return 'Circular'
    if 'inter office memo' in head or 'iom' in head: return 'IOM'
    return 'Other'
cat={}
for name in meta:
    txt=open(os.path.join(T,name+'.txt')).read()
    body='\n'.join(l for l in txt.split('\n')[2:] if not l.startswith('— Page'))
    head=body[:4000]
    dn=dates(name); dt=dates(head)
    refm=REF.search(head) or REF2.search(head); sub=SUBJ.search(head)
    src=stem2src.get(name,name+'?'); L=log.get(src,{})
    yn=dn[0][0] if dn else None; yt=dt[0][0] if dt else None
    cat[name]={'src':src,'type':doctype(name,head),'date_name':fmt(dn[0]) if dn else '','date_text':fmt(dt[0]) if dt else '',
        'mismatch':'Check' if (yn and yt and abs(yn-yt)>1 and yn not in [x[0] for x in dt[:5]]) else '',
        'ref':refm.group(1).strip()[:60] if refm else '','subject':re.sub(r'\s+',' ',sub.group(1))[:200] if sub else '',
        'words':meta[name]['words'],'pages':L.get('pages',''),'conf':L.get('avg_ocr_conf',''),'engine':L.get('engine',''),'exact':meta[name]['exact']}
# --- classify pairs
def kind(j,ca,cb):
    if j>=0.95 or min(ca,cb)>=0.97: return 'Duplicate'
    if j>=0.6 or min(ca,cb)>=0.75: return 'Version / near-copy'
    if max(ca,cb)>=0.8: return 'Contained'
    if j>=0.3: return 'Related'
    return None
pairs=[]
for a,b,j,ca,cb in res:
    k='Duplicate' if cat[a]['exact']==cat[b]['exact'] and meta[a]['words']>20 else kind(j,ca,cb)
    if k: pairs.append((a,b,j,ca,cb,k))
# union-find duplicates
par={n:n for n in cat}
def f(x):
    while par[x]!=x: par[x]=par[par[x]]; x=par[x]
    return x
for a,b,j,ca,cb,k in pairs:
    if k=='Duplicate' and meta[a]['words']>20: par[f(a)]=f(b)
groups=collections.defaultdict(list)
for n in cat: groups[f(n)].append(n)
def score(n):
    c=cat[n]; ocr=0 if c['engine'] in ('pdf-text','textutil','pptx','text') else 1
    try: conf=float(c['conf'] or 100)
    except: conf=0
    return (ocr, -conf, -c['words'], len(n))
gid={}; prim={}; k=0
for root,ms in sorted(groups.items(), key=lambda x: min(x[1])):
    if len(ms)>1:
        k+=1; p=sorted(ms,key=score)[0]
        for m in ms: gid[m]=f'D{k:03d}'; prim[m]=p
pickle.dump({'cat':cat,'pairs':pairs,'gid':gid,'prim':prim},open(os.path.join(WORK,'classified.pkl'),'wb'))
cnt=collections.Counter(p[5] for p in pairs); print(cnt)
print('dup groups',k,'files in groups',len(gid),'redundant copies',len(gid)-k)
# versions between distinct primaries
vp=set()
for a,b,j,ca,cb,kk in pairs:
    if kk=='Version / near-copy':
        A=prim.get(a,a); B=prim.get(b,b)
        if A!=B: vp.add(tuple(sorted((A,B))))
print('version pairs between unique docs',len(vp))
print('types',collections.Counter(c['type'] for c in cat.values()).most_common())
print('with date_text',sum(1 for c in cat.values() if c['date_text']),'ref',sum(1 for c in cat.values() if c['ref']),'subject',sum(1 for c in cat.values() if c['subject']),'mismatch',sum(1 for c in cat.values() if c['mismatch']))
import random; random.seed(3)
for n in random.sample(list(cat),6): c=cat[n]; print(n[:50],'|',c['type'],c['date_name'],c['date_text'],c['mismatch'],'|',c['ref'],'|',c['subject'][:70])
