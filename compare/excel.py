import os, pickle, collections
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter
import os
import os
WORK=os.path.expanduser(os.environ.get("COMPARE_WORK","~/KnowledgeRAG/compare_work")); DOCS=os.path.expanduser(os.environ["DOCS_DIR"])
OUTDIR=os.path.join(DOCS,"Document Comparison")
C=pickle.load(open(os.path.join(WORK,'classified.pkl'),'rb')); V=pickle.load(open(os.path.join(WORK,'vers.pkl'),'rb'))
cat,pairs,gid,prim=C['cat'],C['pairs'],C['gid'],C['prim']; vers,names=V['vers'],V['names']
OUT=os.path.join(OUTDIR,'Document Comparison.xlsx')
HF=Font(bold=True,color='FFFFFF'); HFILL=PatternFill('solid',fgColor='1F4E78')
def sheet(wb,title,head,rows,widths):
    ws=wb.create_sheet(title); ws.append(head)
    for c in ws[1]: c.font=HF; c.fill=HFILL; c.alignment=Alignment(wrap_text=True,vertical='center')
    for r in rows: ws.append(r)
    for i,w in enumerate(widths,1): ws.column_dimensions[get_column_letter(i)].width=w
    ws.freeze_panes='B2'; ws.auto_filter.ref=ws.dimensions; return ws
P=lambda n: prim.get(n,n)
src=lambda n: cat[n]['src']
dt=lambda n: cat[n]['date_text'] or cat[n]['date_name']
vmap=collections.defaultdict(list)
for i,(A,B,*_) in enumerate(vers,1): vmap[A].append(f'V{i:03d}'); vmap[B].append(f'V{i:03d}')
cont=collections.defaultdict(list); controws={}
rel=collections.defaultdict(int); relrows={}
for a,b,j,ca,cb,k in pairs:
    A,B=P(a),P(b)
    if A==B: continue
    if k=='Contained':
        s,big,cov=(A,B,ca) if ca>=cb else (B,A,cb)
        key=(s,big)
        if cov>controws.get(key,0): controws[key]=cov
    elif k=='Related':
        key=tuple(sorted((A,B))); relrows[key]=max(relrows.get(key,0),j)
for (s,big),cov in controws.items(): cont[s].append((cov,big))
for (a,b) in relrows: rel[a]+=1; rel[b]+=1
wb=Workbook(); ws=wb.active; ws.title='Read me'
ndup=len(set(gid.values())); red=len(gid)-ndup; uniq=len(cat)-red
lines=[('Document comparison',''),('',''),
('Documents compared',len(cat)),('Unique documents (after removing copies)',uniq),
('Duplicate groups (same content, different files)',ndup),('Redundant copies inside those groups',red),
('Version / near-copy pairs (with a comparison file)',len(vers)),('Documents contained inside a larger document',len(cont)),
('Related pairs (20–60% shared text)',len(relrows)),('Date in file name ≠ date in text (check)',sum(1 for c in cat.values() if c['mismatch'])),('',''),
('How documents were compared',''),
('Text, not file names: every document\'s OCR/Word text was cleaned (case, spacing, page markers ignored) and broken into overlapping 4-word phrases.',''),
('Similarity = share of phrases two documents have in common. "A in B" = share of A\'s phrases found in B.',''),
('Duplicate: ≥95% similar (or each ≥97% inside the other) – same document, different scan/copy. One "main copy" is suggested: real text over OCR, then highest OCR confidence, then most complete.',''),
('Version / near-copy: 60–95% similar – e.g. MDG 2013 vs MDG 2015. See "Version comparisons" folder for what was added, removed or changed (with page numbers).',''),
('Contained: ≥80% of the smaller document appears inside a larger one (e.g. a circular reproduced in a Compendium or attached to an email).',''),
('Related: 30–60% similar – same subject, materially different text.',''),
('Reference no., subject and dates are auto-extracted from the first page and may be incomplete – verify against the original.',''),
('Nothing has been deleted or renamed.','')]
for l in lines: ws.append(list(l))
ws['A1'].font=Font(bold=True,size=14); ws.column_dimensions['A'].width=110; ws.column_dimensions['B'].width=12
for r in range(3,12): ws.cell(r,2).font=Font(bold=True)
ws['A13'].font=Font(bold=True)
for r in range(14,22): ws.cell(r,1).alignment=Alignment(wrap_text=True)
rows=[]
for n in sorted(cat,key=lambda x:(cat[x]['src'].lower())):
    c=cat[n]; g=gid.get(n,'')
    main='Yes' if not g or prim[n]==n else 'No – copy'
    cn='; '.join(src(b) for cov,b in sorted(cont.get(P(n),[]),reverse=True)[:3])
    rows.append([c['src'],c['type'],c['date_name'],c['date_text'],c['mismatch'],c['ref'],c['subject'],
                 int(c['pages']) if str(c['pages']).isdigit() else c['pages'],c['words'],
                 float(c['conf']) if c['conf'] else None,g,main,src(prim[n]) if g and prim[n]!=n else '',
                 ', '.join(vmap.get(P(n),[])),cn,rel.get(P(n),0) or None])
sheet(wb,'Catalogue',['Original file','Type (auto)','Date in file name','Date in text','Date check','Reference no. (auto)','Subject (auto)','Pages','Words','OCR confidence %','Duplicate group','Main copy?','Main copy is','Versions (see Versions sheet)','Contained in','Related docs (count)'],rows,[60,14,12,12,9,28,60,7,9,10,10,11,45,18,60,10])
dr=[]
for g in sorted(set(gid.values())):
    ms=sorted([n for n in gid if gid[n]==g],key=lambda n:(prim[n]!=n,src(n)))
    for n in ms: dr.append([g,src(n),'Main copy' if prim[n]==n else 'Copy',dt(n),cat[n]['words'],float(cat[n]['conf']) if cat[n]['conf'] else None])
sheet(wb,'Duplicate groups',['Group','File','Role','Date','Words','OCR confidence %'],dr,[9,80,11,12,9,12])
vr=[]
for i,(A,B,j,ca,cb) in enumerate(vers,1):
    vr.append([f'V{i:03d}',src(A),dt(A),src(B),dt(B),round(j*100),round(ca*100),round(cb*100),names[i-1]])
ws=sheet(wb,'Versions',['ID','Older / A','Date A','Newer / B','Date B','Similarity %','% of A in B','% of B in A','Comparison file (click)'],vr,[7,55,11,55,11,10,9,9,70])
for r in range(2,ws.max_row+1):
    c=ws.cell(r,9); c.hyperlink='Version comparisons/'+c.value; c.font=Font(color='0563C1',underline='single')
cr=[[src(s),dt(s),src(b),round(cov*100)] for s,lst in sorted(cont.items(),key=lambda x:src(x[0])) for cov,b in sorted(lst,reverse=True)]
sheet(wb,'Contained in',['Smaller document','Date','Found inside','% of smaller doc found'],cr,[70,11,70,12])
rr=[[src(a),dt(a),src(b),dt(b),round(j*100)] for (a,b),j in sorted(relrows.items(),key=lambda x:-x[1])]
sheet(wb,'Related',['Document A','Date A','Document B','Date B','Similarity %'],rr,[70,11,70,11,10])
mr=[[c['src'],c['date_name'],c['date_text']] for n,c in sorted(cat.items()) if c['mismatch']]
sheet(wb,'Check dates',['File','Date in file name','First date found in text'],mr,[80,15,18])
wb.save(OUT); print('saved', OUT.split('/')[-1], {s.title:s.max_row-1 for s in wb.worksheets})
