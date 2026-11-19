import hashlib,json,re
from pathlib import Path
import pdfplumber
from pypdf import PdfReader
B=Path(__file__).resolve().parent;R=Path(__file__).resolve().parents[3]
m=json.loads((B/'manifest.json').read_text());d=json.loads((B/'book-content.json').read_text());pages=json.loads((B/'pages.json').read_text())
reader=PdfReader(m['pdf']);errors=[];refs=0;snippets=0;allq=[]
for ch in d['chapters']:
 if m['page_map']['chapter-'+str(ch['number'])]%2!=1:errors.append(('chapter parity',ch['number']))
 for q in ch['questions']:
  allq.append(q);qid=q['id'];pn=m['page_map']['q-'+qid]
  txt=reader.pages[pn-1].extract_text()
  if 'Q-'+qid not in txt:errors.append(('question destination',qid,pn))
  for ev in q.get('evidence',[]):
   refs+=1;p=R/ev['path']
   if not p.is_file() or not 1<=ev['line']<=len(p.read_text().splitlines()):errors.append(('bad evidence',qid,ev))
  for ref in q.get('related',[]):
   if 'q-'+ref.removeprefix('Q-') not in m['page_map']:errors.append(('bad related',qid,ref))
  for fu in q['followups']:
   if not fu['answer'].strip():errors.append(('unanswered',qid))
  if 'code' in q:
   snippets+=1;co=q['code'];source=(R/co['path']).read_text().splitlines();excerpt='\n'.join(source[co['start']-1:co['end']])
   if excerpt!=q['excerpt'] or hashlib.sha256(excerpt.encode()).hexdigest()!=q['excerpt_sha256']:errors.append(('snippet mismatch',qid))
   if not 8<=co['end']-co['start']+1<=18:errors.append(('snippet length',qid))
   testsource=(R/q['test']['path']).read_text();testname=q['test']['name']
   if testname.startswith('main mode '):
    tokens=testname.split();mode=tokens[2]
    valid=('function main(' in testsource and bool(re.search(r"mode\s*===\s*['\"]"+re.escape(mode)+r"['\"]",testsource)))
    if len(tokens)>3:
     valid=valid and tokens[3]=='stage' and bool(re.search(r"stage\s*=\s*['\"]"+re.escape(tokens[4])+r"['\"]",testsource))
    if not valid:errors.append(('missing fixture mode/stage',qid,testname))
   elif testname not in testsource:errors.append(('missing named test',qid))
   if pn%2 or m['page_map']['defense-'+qid]!=pn+1:errors.append(('spread parity',qid,pn))
   if len(q['followups'])!=3:errors.append(('code probes',qid))
text='\n'.join(pg.extract_text() or '' for pg in reader.pages)
for bad in ['\ufffd','TODO','TBD','Lorem ipsum','Walk the P8 boundary','Walk the P9 boundary']:
 if bad in text:errors.append(('bad visible string',bad))
if len(reader.pages)!=m['pages']:errors.append(('page count',len(reader.pages)))
if len(allq)!=m['questions'] or snippets!=60:errors.append(('question count',len(allq),snippets))
if sum(len(q['followups']) for q in allq)!=501:errors.append(('followup count',))
out=[]
def outline(items):
 for item in items:
  if isinstance(item,list):outline(item)
  else:out.append(item)
outline(reader.outline)
if len(out)!=len(allq)+len(d['chapters']):errors.append(('outline count',len(out)))
# Verify printed margins, content boxes and actual glyph bounds for all pages.
geom=[]; rendered_code={}
with pdfplumber.open(m['pdf']) as doc:
 for n,page in enumerate(doc.pages,1):
  if n==1:continue
  x=68 if n%2 else 46;right=x+481.2756
  rendered_code[n]=''.join(ch['text'] for ch in page.chars if abs(ch['size']-8.3)<.02 and 'SourceCodePro' in ch['fontname'] and ch['x0']>=x+38)
  for word in page.extract_words():
   tab=pages[n-1]['chapter_number'] and word['text']==str(pages[n-1]['chapter_number']).zfill(2) and ((n%2 and word['x0']>565 and word['x1']<582) or (not n%2 and word['x0']>14 and word['x1']<29))
   if not tab and (word['x0']<x-1 or word['x1']>right+1):geom.append(('horizontal',n,word['text'],word['x0'],word['x1']))
   if word['top']<15 or word['bottom']>819:geom.append(('vertical',n,word['text'],word['top'],word['bottom']))
errors.extend(geom)
# This edition intentionally changes content. Require a complete per-question audit instead.
ledger=json.loads((B/'audit-ledger.json').read_text())
if ledger['questions_reviewed']!=220 or ledger['questions_visibly_revised']!=220:errors.append(('audit coverage',))
if {r['id'] for r in ledger['entries']}!={q['id'] for q in allq}:errors.append(('audit identities',))
# Verify every question, model-answer paragraph, probe and code decision is present in its actual PDF spread.
import unicodedata

def code_normalized(value):
 for a,b in {'\u2011':'-','\u2013':'-','\u2014':' - ','\u2018':chr(39),'\u2019':chr(39),'\u201c':chr(34),'\u201d':chr(34),'\u2026':'...','\u00a0':' ','\u2022':'-'}.items():value=value.replace(a,b)
 return re.sub(r'\s+','',unicodedata.normalize('NFKC',value))

def normalized(value):
 value=unicodedata.normalize('NFKC',value)
 return re.sub(r'[^A-Za-z0-9]','',value).lower()

presence=0
for q in allq:
 pn=m['page_map']['q-'+q['id']]
 spread=reader.pages[pn-1].extract_text()
 if 'code' in q:spread+='\n'+reader.pages[pn].extract_text()
 actual=normalized(spread)
 checks=[('question',q['question']),('watch_for',q['watch_for'])]
 checks.extend(('answer',s) for s in q['answer'])
 for fu in q['followups']:checks.extend([('followup question',fu['question']),('followup answer',fu['answer'])])
 if 'code' in q:
  if code_normalized(q['excerpt'])!=code_normalized(rendered_code.get(pn,'')):errors.append(('rendered code mismatch',q['id']))
  checks.extend([('alternative',q['alternatives']),('counterfactual',q['counterfactual']),('test assertion',q['test']['assertion'])])
  checks.extend(('challenge '+k,v) for k,v in q['challenge'].items())
 for label,s in checks:
  presence+=1
  if normalized(s) not in actual:errors.append(('missing rendered content',q['id'],label,s[:80]))
for key,f in d['figures'].items():
 pn=m['page_map']['fig-'+f['id']]
 if normalized(f['caption']) not in normalized(reader.pages[pn-1].extract_text()):errors.append(('missing figure caption',f['id']))
report=dict(rendered_content_checks=presence,audited_questions=220,pages=len(reader.pages),questions=len(allq),answered_followups=501,code_snippets=snippets,repository_evidence_references=refs,vector_figures=len(d['figures']),primary_sources=len(d['sources']),chapters=len(d['chapters']),outline_entries=len(out),minimum_body_font=m['minimum_body_font'],duplex_sheets=m['sheets_duplex'],sha256=hashlib.sha256(Path(m['pdf']).read_bytes()).hexdigest(),bytes=Path(m['pdf']).stat().st_size,errors=errors)
(B/'audit.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
if errors:raise SystemExit(1)
