import os, re, json, hashlib, collections, itertools, time, pickle
import os
WORK=os.path.expanduser(os.environ.get("COMPARE_WORK","~/KnowledgeRAG/compare_work")); DOCS=os.path.expanduser(os.environ["DOCS_DIR"])
OUTDIR=os.path.join(DOCS,"Document Comparison")
T=os.path.join(WORK,'text')
WORD=re.compile(r'[a-z0-9ऀ-ॿ]+')
def norm_words(t):
    lines=[l for l in t.split('\n') if not l.startswith(('Source: ','— Page'))]
    return WORD.findall('\n'.join(lines[1:]).lower())  # drop title line (file name)
docs={}; t0=time.time()
for f in sorted(os.listdir(T)):
    w=norm_words(open(os.path.join(T,f)).read())
    w=[x for x in w if len(x)>1 or x.isdigit()]
    sh={h for h in (int(hashlib.md5(' '.join(w[i:i+4]).encode()).hexdigest()[:12],16) for i in range(max(0,len(w)-3))) if h%4==0}
    docs[f[:-4]]={'words':len(w),'sh':sh,'exact':hashlib.md5(' '.join(w).encode()).hexdigest()}
print('docs',len(docs),'load',round(time.time()-t0),'s')
# inverted index on sampled shingles
inv=collections.defaultdict(list)
for d,v in docs.items():
    for h in v['sh']:
        inv[h].append(d)
pairs=collections.Counter()
for h,ds in inv.items():
    if 1<len(ds)<=60:
        for a,b in itertools.combinations(sorted(ds),2): pairs[(a,b)]+=1
print('candidate pairs',len(pairs),round(time.time()-t0),'s')
res=[]
for (a,b),c in pairs.items():
    A,B=docs[a]['sh'],docs[b]['sh']
    if not A or not B: continue
    sa=len(A); sb=len(B)
    if c/min(sa,sb)<0.2: continue
    i=len(A&B); j=i/len(A|B); ca=i/len(A); cb=i/len(B)
    res.append((a,b,round(j,3),round(ca,3),round(cb,3)))
print('pairs >=20% overlap',len(res),round(time.time()-t0),'s')
pickle.dump({'res':res,'meta':{d:{'words':v['words'],'exact':v['exact']} for d,v in docs.items()}},open(os.path.join(WORK,'pairs.pkl'),'wb'))
js=[r[2] for r in res]
for lo,hi in [(0.95,1.01),(0.8,0.95),(0.6,0.8),(0.3,0.6),(0,0.3)]: print(lo,hi,sum(lo<=x<hi for x in js))
print('contained (>=0.8 one way, jaccard<0.6)',sum(1 for r in res if r[2]<0.6 and max(r[3],r[4])>=0.8))
ex=collections.Counter(v['exact'] for v in docs.values()); print('exact dup groups',sum(1 for c in ex.values() if c>1),'files in them',sum(c for c in ex.values() if c>1))
print('empty/near-empty docs',sum(1 for v in docs.values() if v['words']<20))
