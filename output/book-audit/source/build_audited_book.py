"""Print-oriented expansion of the source-reviewed interview book."""
import ast, hashlib, html, json, math, re, textwrap
from pathlib import Path
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph, Table, TableStyle, Spacer, Flowable
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from color_figures import FIGURES, draw as draw_figure

BASE=Path(__file__).resolve().parent
REPO=Path(__file__).resolve().parents[3]
DEST=REPO/'output/pdf/LiveKit-Agents-Audited-Study-Edition.pdf'
RT=Path('/Users/rostwal/.cache/codex-runtimes/codex-primary-runtime/dependencies')
fonts=RT/'node/node_modules/pdfjs-dist/standard_fonts'
for n,fn in [('Body','LiberationSans-Regular.ttf'),('BodyB','LiberationSans-Bold.ttf'),('BodyI','LiberationSans-Italic.ttf')]:pdfmetrics.registerFont(TTFont(n,str(fonts/fn)))
pdfmetrics.registerFontFamily('Body',normal='Body',bold='BodyB',italic='BodyI',boldItalic='BodyB')
for n,fn in [('Display','Georgia.ttf'),('DisplayB','Georgia Bold.ttf')]:pdfmetrics.registerFont(TTFont(n,'/System/Library/Fonts/Supplemental/'+fn))
pdfmetrics.registerFont(TTFont('Code',str(RT/'native/poppler/poppler/fonts/SourceCodePro-Regular.ttf')))
W,H=595.2756,841.8898
INNER,OUTER=68,46
CW=W-INNER-OUTER
GREEN=colors.HexColor('#2D46D7'); INK=colors.HexColor('#202B3C')
MUTED=colors.HexColor('#5F6F88'); LINE=colors.HexColor('#C9D4E8')
PALE=colors.HexColor('#EDF1FF'); AMBER=colors.HexColor('#A65F05')
PURPLE=colors.HexColor('#7445B5'); TEAL=colors.HexColor('#087E78')
NAVY=colors.HexColor('#162647'); CORAL=colors.HexColor('#B44D35')
def blend(color,factor=.91):
 return colors.Color(color.red+(1-color.red)*factor,color.green+(1-color.green)*factor,color.blue+(1-color.blue)*factor)
CHAPTER_COLORS=['#2D46D7','#178061','#178061','#176FAC','#176FAC','#7950B8','#7950B8','#BF5B3F','#047D98','#4560C2','#B7650B','#0B846E','#7950B8','#176FAC','#2D46D7']
ACTIVE=GREEN
LEARNING=json.loads((BASE/'learning-cues.json').read_text()) if (BASE/'learning-cues.json').exists() else {}
HEAD='6cec82f6718cf5f9319976196d2cfd449c2b0048'
figure_order=['authority','commit','effect','lease','feedcommit','intake','context','outbound','auth','delegation','feed','facts','singleflight','webrtc','pipeline','triage','lifetime','nats','planes']
FIGURES={key:FIGURES[key] for key in figure_order}
if (BASE/'figure-overrides.json').exists():
 for key,value in json.loads((BASE/'figure-overrides.json').read_text()).items():
  if key in FIGURES:FIGURES[key].update(value)
for index,fig in enumerate(FIGURES.values(),1):fig['id']=f'F{index:02d}'
book=json.loads((BASE/'audited-content.json').read_text())
src=book['sources'];chapters=book['chapters']
olds=[chapters[i] for i in [0,1,3,5,8,9,10,11,12,13,14]]
deeps=[chapters[i] for i in [2,4,6,7]]
allq=[q for ch in chapters for q in ch['questions']]
qdict={q['id']:q for q in allq}
assert len(qdict)==len(allq)
QCOUNT=len(allq); FCOUNT=sum(len(q['followups']) for q in allq)
challenges=json.loads((BASE/'challenge-index.json').read_text())

def clean(s):
 for a,b in {'\u2011':'-','\u2013':'-','\u2014':' - ','\u2018':"'",'\u2019':"'",'\u201c':'"','\u201d':'"','\u2026':'...','\u00a0':' ','\u2022':'-'}.items():s=s.replace(a,b)
 return s

def markup(s):
 s=html.escape(clean(str(s)))
 def repl(m):
  ks=[x.strip() for x in m.group(1).split(',')]
  if not all(k in src for k in ks):return m.group(0)
  return '['+', '.join(f'<a href="{html.escape(src[k][1],quote=True)}" color="#2D46D7">{k}</a>' for k in ks)+']'
 return re.sub(r'\[([A-Za-z0-9, -]+)\]',repl,s)
def sty(size=10.5,leading=None,**kw):
 a=dict(fontName='Body',fontSize=size,leading=leading or size*1.39,textColor=INK,spaceAfter=8,splitLongWords=True)
 a.update(kw);return ParagraphStyle('print',**a)
def p(t,size=10.5,leading=None,**kw):return Paragraph(markup(t),sty(size,leading,**kw))
def rich(t,size=10.5,leading=None,**kw):return Paragraph(t,sty(size,leading,**kw))
class SectionLabel(Flowable):
 def __init__(self,text,color):
  Flowable.__init__(self);self.text=clean(text.upper());self.color=color;self.spaceBefore=6;self.spaceAfter=5
 def wrap(self,w,h):self.width=w;self.height=15;return w,15
 def draw(self):
  c=self.canv;ww=min(self.width,pdfmetrics.stringWidth(self.text,'BodyB',8.1)+16)
  c.setFillColor(blend(self.color,.91));c.roundRect(0,0,ww,15,3,fill=1,stroke=0)
  c.setFillColor(self.color);c.setFont('BodyB',8.1);c.drawString(8,4.4,self.text)
def label(t,color=GREEN):
 s=t.lower()
 if s.startswith(('model answer','what the code','a defensible','by the end')):color=TEAL
 elif s.startswith('follow'):color=PURPLE
 elif s.startswith(('watch','avoid')):color=AMBER
 elif s.startswith(('predict','common implementation')):color=CORAL
 return SectionLabel(t,color)
class QuestionHero(Flowable):
 def __init__(self,q,mode='QUESTION'):
  Flowable.__init__(self);self.q=q;self.mode=mode;self.accent=ACTIVE;self.spaceAfter=10
 def wrap(self,w,h):
  self.width=w
  self.idp=p(self.mode+'  Q-'+self.q['id']+'  /  '+self.q['title'],8.1,10.7,fontName='BodyB',textColor=self.accent,spaceAfter=0)
  self.qp=p(self.q['question'],13.0,17.5,fontName='BodyB',textColor=NAVY,spaceAfter=0)
  self.ih=self.idp.wrap(w-37,100)[1];self.qh=self.qp.wrap(w-26,200)[1]
  self.height=12+self.ih+7+self.qh+12
  return w,self.height
 def draw(self):
  c=self.canv;c.setFillColor(blend(self.accent,.92));c.rect(0,0,self.width,self.height,fill=1,stroke=0)
  c.setFillColor(self.accent);c.roundRect(0,0,3.2,self.height,1,fill=1,stroke=0)
  c.setStrokeColor(self.accent);c.setLineWidth(.7);c.rect(12,self.height-19,6.3,6.3,stroke=1,fill=0)
  self.idp.drawOn(c,25,self.height-12-self.ih);self.qp.drawOn(c,13,12)
class Callout(Flowable):
 def __init__(self,title,body,color=AMBER,fs=10.4):
  Flowable.__init__(self);self.title=title;self.body=body;self.color=color;self.fs=fs;self.spaceBefore=5;self.spaceAfter=8
 def wrap(self,w,h):
  self.width=w;self.hp=p(self.title.upper(),8.1,10.7,fontName='BodyB',textColor=self.color,spaceAfter=0)
  self.bp=p(self.body,self.fs,self.fs*1.36,spaceAfter=0)
  self.hh=self.hp.wrap(w-22,100)[1];self.bh=self.bp.wrap(w-22,1000)[1]
  self.height=10+self.hh+4+self.bh+9;return w,self.height
 def draw(self):
  c=self.canv;c.setFillColor(blend(self.color,.93));c.roundRect(0,0,self.width,self.height,4,fill=1,stroke=0)
  c.setFillColor(self.color);c.rect(0,0,3,self.height,fill=1,stroke=0)
  self.hp.drawOn(c,11,self.height-10-self.hh);self.bp.drawOn(c,11,9)
def table(rows,widths,fs=9.5,header=True):
 data=[[p(cell,fs,fs*1.38,fontName='BodyB' if i==0 and header else 'Body',spaceAfter=0) for cell in row] for i,row in enumerate(rows)]
 t=Table(data,colWidths=widths,hAlign='LEFT');t.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),8),('RIGHTPADDING',(0,0),(-1,-1),8),('TOPPADDING',(0,0),(-1,-1),7),('BOTTOMPADDING',(0,0),(-1,-1),7),('LINEBELOW',(0,0),(-1,-1),.4,LINE),('BACKGROUND',(0,0),(-1,0),PALE),('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#FAFBFF')]) ]));return t
def height(items):return sum(it.wrap(CW,2000)[1]+getattr(it,'spaceBefore',0)+getattr(it,'spaceAfter',0) for it in items)

pages=[]
def add(kind,title='',items=None,**kw):
 v=dict(kind=kind,title=title,items=items or [],**kw);pages.append(v);return v
def textpage(title,kicker,items,key=None):return add('text',title,items,kicker=kicker,key=key)
def recto():
 if (len(pages)+1)%2==0:add('blank','Chapter opening')
def figure(key):
 f=FIGURES[key];add('figure',f['title'],figure=key,kicker='FIGURE '+f['id'],key='fig-'+f['id'])

add('cover')
textpage('Reading and printing this edition','A4 DUPLEX / SOURCE REVIEWED CODE',[
 p('This audited edition revises the project and fundamentals material and contains sixty code decision reviews. Each two-page review asks why a local choice exists, shows the exact source, compares an alternative and tests a tempting edit. Common challenges connect the mechanism to a symptom and a diagnostic path.'),
 table([['Print setting','Use this'],['Paper and scale','A4 portrait, actual size / 100 percent'],['Duplex','Flip on the long edge. PDF page 1 is the front cover.'],['Binding','Mirrored margins: 68 pt inside, 46 pt outside. Do not add another printer gutter.'],['Color','Color recommended for the study cues. Labels, line style and dark text keep grayscale printing readable.'],['Chapter starts','Chapters start on right-hand pages. Light sketch pages preserve duplex order and give you room to draw.'],['PDF navigation','Contents, bookmarks, figure index, question index and printed cross-references remain available.']],[112,CW-112]),
 label('Use a facing spread actively'),
 p('Read the left-hand code page before its facing explanation. Predict the proposed edit outcome, trace the named test and then answer all three follow-ups. Line numbers refer to physical source lines; a greater-than continuation marker indicates a visual wrap only.'),
 label('What the evidence means'),
 p('Questions are inferred preparation material. Source excerpts and existing assertions were inspected; application, browser, database and paid-provider gates were not rerun for this book. Alternatives are tradeoff analysis unless a code comment or decision record documents the reason. Open findings remain open.'),
 p('Q-P1-06 and D1-06 are book IDs. They do not map directly to charter acceptance IDs. Replace personal examples with your actual contribution.')],key='print-guide')
textpage('What the content audit changed','EVERY QUESTION / EVERY FOLLOW-UP',[
 p('All 220 main questions and 501 answered follow-ups received a content review. Every main question has a visible accuracy, scope or explanation revision. The review covered implementation, cited test bodies, alternatives, counterfactuals, failure examples and source attribution; it was not limited to layout or checking that a path exists.'),
 table([['Area','Examples of corrections'],['P1','Bounded managed lifetime and finite delivery attempts; PostgreSQL DDL rollback; supplier reconciliation prerequisites.'],['P2','Input acceptance versus generation/playback; separate generation limits; canonical callback replay; capacity versus measured workload.'],['P3','Preflight cancellation race limits; retained-byte versus duplicate-classification behavior; exact bounded-scan arithmetic and fail-closed retention.'],['Shared code','Observer versus actual-work ownership; local clock versus database authority; fixture tests versus real SDK/socket evidence.'],['Fundamentals','DTLS-SRTP keying; transport versus application receipts; JetStream redelivery, quorum and filesystem-sync limits.'],['External sources','Exact employer job text rechecked. PSRPC and LiveKit construction references now pin separate inspected upstream commits.']],[92,CW-92],fs=9.5),
 label('How to use a corrected answer'),
 p('Start with the direct answer, explain the concrete mechanism, then trace a failure schedule and its existing assertion. A test supports what it actually asserts. A proposed tempting edit is reasoning about the mechanism unless an executed mutation test is explicitly recorded.'),
 Callout('Scope of this audit','This is a source, existing-test and technical-reference review. Application PostgreSQL, process, browser/media and provider gates were not rerun. Historical qualifications and current open findings retain their original limits.',AMBER,10.0),
 p('The companion audit ledger records one review row per question, changed fields, reasons and checked evidence. The source snapshot remains '+HEAD+'.')
 ],key='content-audit')
add('contents','Contents',kicker='CHAPTERS',key='contents')
add('figure-index','Figures and practice',kicker='VISUAL READING MAP',key='figure-index')
textpage('The role and your evidence','SOFTWARE ENGINEER AGENTS',[
 p('The linked role emphasizes framework abstractions for realtime voice and text, durable state, delegation, Python, TypeScript, simple developer APIs and clear examples. Use the code to demonstrate those skills rather than a dependency inventory. [JD]'),
 table([['Role theme','Evidence you can explain'],['State across interactions','P1 exact commitment, original identity, leases and persisted effects'],['Text and SMS','P2 retained intake, association, native turn admission and current-grant rehydration'],['Delegation','P3 new issuance, bounded specialist calls, factual validity and result applicability'],['Async concurrency','Actual work ownership after observer cancellation, task publication and dependency closure'],['SDK and API design','Closed contracts, immutable original bytes, explicit result variants and installed consumers'],['Developer experience','Truthful errors, useful recovery actions, examples and scope-specific evidence']],[125,CW-125]),
 label('Open with the problem'),
 p('The system keeps business work correct when a voice session ends. P1 owns durable execution and exact confirmation; P2 owns verified channel input and communication evidence; P3 owns bounded specialist coordination and derived applicability. LiveKit supplies realtime transport and conversational orchestration.'),
 label('Then defend one difficult choice'),
 p('Show the code, its commitment or disclosure boundary, one competing schedule and the specific assertion that distinguishes success from a plausible but incorrect implementation. End with the limitation and a concrete alternative.')],key='role-map')
textpage('The snapshot you can defend','IMPLEMENTATION AND QUALIFICATION',[
 p('Source reviewed 16 November 2026 at commit '+HEAD+'. The source commit is unchanged from the first edition. Generated book files are separate from application implementation.'),
 table([['Area','Defensible statement'],['P1','All twenty rows have registered historical evidence. Local V1 was qualified with provider_real v2; affected v5 requalification still has its stated open provider rerun.'],['P2','Many selected slices are qualified. All seventeen complete charter rows remain planned in the catalog.'],['P3','P3-01, P3-03 and P3-11 are registered complete rows; fourteen full rows remain planned.'],['Catalog','Fifty-five cases and twenty-four registrations, including BASE-01. Registration is not itself a pass.'],['Inference','scripted is default. provider_real is explicit. local_real remains unqualified.'],['Latest audit','0048 records five errors in a loaded-host full P1 PostgreSQL run followed by passing targeted reruns. It also records unresolved gateway and shutdown findings.']],[88,CW-88]),
 label('Do not erase the remaining risk'),
 p('Open 0048 findings include normal-stop input exhaustion (GW-A1), possible final-input stranding (GW-A2, medium confidence), shutdown budget and cleanup-observation problems (DEMO-A6), and retry pacing outside selected predispatch outages (P1-A2). Proposed repairs in the exercises are not implemented fixes.'),
 p('Historical evidence remains tied to the source and selected assertions in its work item. The additional code review did not promote the whole portfolio to a current full release.'),
 p('Read: docs/work-items/0048-code-audit-fixes-and-documentation-cleanup.md:91 and :103; docs/work-items/0047-open-findings-schema-upgrades-and-landing.md.')],key='snapshot')
textpage('Version namespaces and proof boundaries','KEEP THE AXES SEPARATE',[
 table([['Namespace','Meaning'],['P1 booking v5','Persisted selected dependency retry due time; compatible v4 behavior retained.'],['P1 work v1 to v4','Acceptance, issuance/results, delivery/action and then source-bound result feed.'],['P2 inbox v9','Operating indexes after explicit earlier native, response and result upgrades.'],['P3 metadata v3','Derived projection, processing and refresh state, not a second execution queue.'],['Consent proposal v2','New case/supplier/revision binding; legacy v1 bytes remain readable and replayable.'],['Policy v1 / v2 / v3','Original policy, fixed-policy payload and origin-bound outer envelope have distinct codecs. notice_v1 is another semantic axis.'],['provider_real v2','A selected qualification profile, not a database or Agents major version.'],['Pinned runtime','Python 3.14 only; livekit-agents 1.8.11, RTC SDK 1.2.0, server 1.13.11 and browser client 2.23.0. These are repository selections.']],[126,CW-126]),
 label('Four independent questions'),
 p('Are bytes structurally valid? Are facts supported? Was the result eligible at commit? Is the proposed disclosure, delivery or exact action permitted now? A positive answer to one does not settle the others.'),
 label('Read a diagram as a contract'),
 p('Solid arrows show an interaction or named transition. Dashed edges mark an explicitly separate or unresolved path. Timelines show order unless labeled otherwise; no diagram in this edition supplies a new performance measurement. Conceptual state labels are not a promise of exact database enum spelling.'),
 p('Source paths are relative to /Users/rostwal/Downloads/livekit-poc. Source lines and literal snippets are verified against the recorded commit. Online reference URLs can describe newer APIs.')],key='versions')
figure('authority')

figure_after={
 olds[1]['title']:['commit','effect','lease'],
 olds[2]['title']:['intake','context','outbound'],
 olds[3]['title']:['delegation','feed'],
 deeps[0]['title']:['feedcommit'],deeps[1]['title']:['auth'],deeps[2]['title']:['facts'],deeps[3]['title']:['singleflight'],
 olds[4]['title']:['webrtc'],olds[5]['title']:['pipeline'],olds[6]['title']:['triage'],olds[7]['title']:['lifetime'],olds[8]['title']:['nats'],olds[9]['title']:['planes']}

for ci,ch in enumerate(chapters,1):
 recto();ch['number']=ci
 intro=[]
 for txt in ch['intro']:intro.append(p(txt))
 for co in ch.get('concepts',[]):intro.extend([label(co['title']),p(co['body'])])
 if ch.get('deep'):intro.extend([label('Read it on paper'),p('Each review begins on a left-hand page with code and a test to inspect. Predict the change before reading the facing answer. Use the handwritten notes area to state the invariant in your own words.')])
 add('chapter',ch['title'],intro,kicker=f'CHAPTER {ci:02d}',chapter=ch,key=f'chapter-{ci}')
 if not ch.get('deep') and (ch.get('walkthrough') or ch.get('limits')):
  items=[label('Trace the public path' if ch.get('project_tag') else 'Hypothetical design path')]
  for no,step in enumerate(ch.get('walkthrough',[]),1):items.extend([p(f"{no:02d}  {step['step']}",fontName='BodyB',spaceAfter=3),p(step['detail'],10.1,14)])
  textpage('Walk the '+ch['project_tag']+' boundary' if ch.get('project_tag') else 'Trace the message boundary','IMPLEMENTATION WALKTHROUGH' if ch.get('project_tag') else 'HYPOTHETICAL DESIGN WALKTHROUGH',items)
  if ch.get('limits'):
   its=[p('These limits qualify the preceding implementation and its historical assertions.' if ch.get('project_tag') else 'These examples do not establish an implemented NATS service in the POC.')]
   for t in ch['limits']:its.extend([label('Boundary'),p(t,10.1,14)])
   textpage('What this project does not establish' if ch.get('project_tag') else 'Limits of these examples','LIMITS TO STATE CLEARLY',its)
 for fk in figure_after.get(ch['title'],[]):figure(fk)
 if ch.get('deep') and (len(pages)+1)%2==1:add('blank','Facing review spread')
 for q in ch['questions']:
  if ch.get('deep'):
   # Keep each code/defense pair on facing pages, code on the left.
   if (len(pages)+1)%2!=0:raise ValueError('Code page must be verso')
   add('code',q['title'],question=q,section=ch['title'],key='q-'+q['id'])
   add('defense',q['title'],question=q,section=ch['title'],key='defense-'+q['id'])
  else:add('question',q['title'],question=q,section=ch['title'],key='q-'+q['id'])

recto()
for group in ['Connectivity and conversation','Durable work and authority','Resources and integration']:
 entries=[x for x in challenges if x['group']==group]
 for offset in [0,3]:
  add('challenge',group+(' continued' if offset else ''),kicker='COMMON CHALLENGE LOOKUP',entries=entries[offset:offset+3],key='challenges' if group.startswith('Connectivity') and offset==0 else None)

# Preserve the six original coding exercises without reimporting an authoring script.
drills=json.loads((BASE/'drills.json').read_text())
for i,(name,prompt,approach,tests,trap) in enumerate(drills,1):
 items=[p(prompt),label('A defensible approach')]
 items.extend(p(str(j)+'. '+txt) for j,txt in enumerate(approach,1))
 items.append(label('Independent assertions'));items.extend(p(str(j)+'. '+txt) for j,txt in enumerate(tests,1))
 items.extend([label('Watch for'),p(trap),label('Change the constraint'),p('What if the caller disappears, a second owner starts, the payload changes or cleanup exceeds its budget? State what is known and unknown before extending the design.')])
 textpage(name,f'CODING DRILL {i:02d}',items,key='drill-'+str(i))
textpage('A preparation route you can rehearse','FROM THE QUESTION TO THE CODE',[
 label('Pass 1 / Build the mental model'),p('Read the authority map, version page and original project chapters. Reproduce the main path without naming an internal helper before explaining its responsibility.'),
 label('Pass 2 / Defend the difficult code'),p('Work through the four code decision chapters. For each spread, cover the facing answer, explain why the excerpt is ordered that way, predict the counterfactual and inspect its named test.'),
 label('Pass 3 / Diagnose a symptom'),p('Use the challenge lookup. Start from a symptom rather than a memorized concept. State which observation would distinguish a transport problem, a model delay, lost acceptance knowledge or unresolved actual cleanup.'),
 label('Pass 4 / Change the design'),p('Use the alternatives as changed constraints. Explain which invariant must survive if you replace a database, add a broker, enable speculative generation or support another region.'),
 label('Mock project defense / 45 minutes'),p('5 minutes problem and user journey; 10 authority and data flow; 15 one crash and one race; 10 code/test walkthrough; 5 limitations and next coherent slice.'),
 label('Score 0 to 4'),p('One point each for a precise contract, accurate mechanism, concrete failure/recovery explanation, and real evidence plus limitation. A confident unsupported guarantee earns no mechanism or evidence credit.'),
 label('Record your own understanding'),p('Use the notes area for the invariant, the alternative you would choose under a changed constraint and the test you would add. Personal contribution claims must match what you actually designed, inspected and can reproduce.')],key='route')
for i in range(0,len(allq),12):add('practice','Questions only',entries=allq[i:i+12],kicker='ACTIVE RECALL INDEX',key='practice' if i==0 else None)
for i in range(0,len(src),10):
 items=[p('Primary web references are clickable and printable. Repository source and tests define the implemented contract; current online documentation can move ahead of the pinned snapshot.',9.8,13.5)] if i==0 else []
 for key,(title,url) in list(src.items())[i:i+10]:items.extend([label(key+' / '+title),rich(f'<a href="{html.escape(url,quote=True)}" color="#164638">{html.escape(url)}</a>',8.8,12,spaceAfter=10)])
 textpage('Primary references','SOURCE LIBRARY',items,key='sources' if i==0 else None)
for name,ch in zip(['P1','P2','P3','Application'],deeps):
 refs=ch.get('reviewed_files',[])
 for i in range(0,len(refs),18):
  its=[p('Exact excerpts and named assertions appear on their review spread. This map records files inspected in the deeper pass; it is not a new runtime qualification.',9.8,13.5)]
  its.extend(p(t,8.8,11.8,spaceAfter=8) for t in refs[i:i+18])
  textpage(name+' source reading map','CODE REVIEW SCOPE',its,key='source-map' if name=='P1' and i==0 else None)
textpage('Keep these boundaries clear','FINAL REHEARSAL SHEET',[
 table([['Observation','What it does not establish'],['Connected room','Captured audio, returned audio, accepted input or actual inference'],['Final recognition','Accepted operation or exact mutation consent'],['Accepted input','Generated reply, successful dispatch or supplier effect'],['Lease authority','Human confirmation or a supplier-side fence'],['Timeout / canceled waiter','Stopped remote work or definite nonexecution'],['Stored validated result','Current applicability or permission for delivery/action'],['As-of current view','An atomic cross-store freshness or revocation fence'],['Receiver acceptance','Carrier delivery, human hearing or acknowledgment'],['Browser playout','Human understanding or exact consent'],['Selected gate passed','Fresh full release or production scale'],['PSRPC NATS support','A NATS service in this POC or every Cloud deployment']],[155,CW-155]),
 label('The answer worth practicing'),p('Name the authority, original identity, commitment point, failure boundary and recovery action. Show the exact code and assertion, then state what remains unknown.',11.3,16,fontName='BodyB')],key='last-sheet')

active_chapter=0
for i,page in enumerate(pages,1):
 page['page']=i
 if page['kind']=='chapter':active_chapter=page['chapter']['number']
 page['chapter_number']=active_chapter
 page['accent']=CHAPTER_COLORS[active_chapter-1] if active_chapter else '#2D46D7'
 if page.get('kicker') in ['COMMON CHALLENGE LOOKUP','ACTIVE RECALL INDEX'] or page.get('key','') and str(page.get('key')).startswith('drill-'):
  page['accent']='#B7650B'
loc={p['key']:p['page'] for p in pages if p.get('key')}
for ch in chapters:
 for q in ch['questions']:
  for ev in q.get('evidence',[]):
   path=REPO/ev['path'];assert path.is_file() and 1<=ev['line']<=len(path.read_text().splitlines())
  if 'code' in q:
   co=q['code'];ln=(REPO/co['path']).read_text().splitlines();assert 1<=co['start']<=co['end']<=len(ln)
   excerpt='\n'.join(ln[co['start']-1:co['end']]);digest=hashlib.sha256(excerpt.encode()).hexdigest()
   assert excerpt==q['excerpt'] and digest==q['excerpt_sha256'],('Source changed; repeat content review',q['id'])
for f in FIGURES.values():
 for ref in f['refs']:assert ref in qdict,(f['id'],ref)

def xleft(no):return INNER if no%2 else OUTER
def draw_items(cv,items,top=735,bottom=63):
 x=xleft(cv.getPageNumber());y=top
 for item in items:
  y-=getattr(item,'spaceBefore',0);_,h=item.wrap(CW,2000)
  if y-h<bottom-.2:raise ValueError(f'Overflow p{cv.getPageNumber()} at{y-h:.1f}')
  item.drawOn(cv,x,y-h);y-=h+getattr(item,'spaceAfter',0)
 return y
def title(cv,page):
 x=xleft(page['page']);accent=colors.HexColor(page['accent'])
 cv.setFillColor(accent);cv.setFont('BodyB',8.4);cv.drawString(x,780,clean(page.get('kicker','')))
 pp=p(page['title'],22,27,fontName='BodyB',textColor=NAVY,spaceAfter=0);_,h=pp.wrap(CW-24,140)
 cv.setFillColor(blend(accent,.94));cv.roundRect(x,747-h,CW,h+21,4,fill=1,stroke=0)
 cv.setFillColor(accent);cv.rect(x,747-h,3.2,h+21,fill=1,stroke=0)
 pp.drawOn(cv,x+12,758-h);return 731-h
def header(cv,page):
 if page['kind']=='cover':return
 x=xleft(page['page']);right=x+CW;accent=colors.HexColor(page['accent'])
 cv.setFont('Body',7.3);cv.setFillColor(MUTED);cv.drawString(x,H-29,'LIVEKIT / AGENTS - AUDITED STUDY EDITION')
 s=clean(page.get('section',page['title']))
 while pdfmetrics.stringWidth(s,'Body',7.3)>218:s=s[:-4]+'...'
 cv.setFillColor(accent);cv.drawRightString(right,H-29,s);cv.setStrokeColor(LINE);cv.setLineWidth(.4);cv.line(x,H-39,right,H-39)
 ci=page['chapter_number'];tabx=W-27 if page['page']%2 else 15
 if ci:
  yy=757-(ci-1)*25;cv.setFillColor(accent);cv.roundRect(tabx,yy,12,22,2,fill=1,stroke=0);cv.setFillColor(colors.white);cv.setFont('BodyB',6.8);cv.drawCentredString(tabx+6,yy+8,str(ci).zfill(2))
 for j in range(15):
  col=colors.HexColor(CHAPTER_COLORS[j]);cv.setFillColor(col if j<ci else blend(col,.9));cv.roundRect(x+j*(CW/15),44,CW/15-2,2.4,1,fill=1,stroke=0)
 cv.setFillColor(MUTED)
 cv.setFont('Body',7.4)
 if page['page']%2:
  cv.drawString(x,29,'RAHUL OSTWAL  |  AUDITED EDITION  |  SOURCE 6cec82f')
  cv.setFillColor(blend(accent,.9));cv.roundRect(right-24,22,24,15,3,fill=1,stroke=0);cv.setFillColor(accent);cv.drawCentredString(right-12,26.5,str(page['page']))
 else:
  cv.setFillColor(blend(accent,.9));cv.roundRect(x,22,24,15,3,fill=1,stroke=0);cv.setFillColor(accent);cv.drawCentredString(x+12,26.5,str(page['page']));cv.setFillColor(MUTED);cv.drawString(x+32,29,'RAHUL OSTWAL  |  AUDITED EDITION  |  SOURCE 6cec82f')

def code_rows(q,fs=8.3):
 co=q['code'];rows=[];maxw=CW-43;char=pdfmetrics.stringWidth('M','Code',fs);count=max(40,int(maxw/char))
 for line_no,raw in enumerate(q['excerpt'].splitlines(),co['start']):
  s=clean(raw.expandtabs(4));parts=textwrap.wrap(s,width=count,expand_tabs=False,replace_whitespace=False,drop_whitespace=False,break_long_words=True,break_on_hyphens=False) or ['']
  for j,part in enumerate(parts):rows.append((str(line_no) if j==0 else '>',part))
 return rows
TOKEN_PATTERN=re.compile(r'''(?P<string>"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')|(?P<comment>\#.*|//.*)|(?P<keyword>\b(?:async|await|def|class|if|elif|else|for|while|return|raise|try|except|finally|with|as|in|is|not|and|or|None|True|False|const|let|function|new|throw|catch|this|undefined|null|true|false|SELECT|UPDATE|INSERT|WHERE|FROM|SET|INTO|VALUES)\b)|(?P<number>\b\d+(?:\.\d+)?\b)''')
TOKEN_COLORS={'string':colors.HexColor('#087366'),'comment':colors.HexColor('#52627A'),'keyword':colors.HexColor('#7445B5'),'number':colors.HexColor('#A25410')}
def render_code(cv,q,top):
 x=xleft(cv.getPageNumber());fs=8.3;lead=10.7;rows=code_rows(q,fs);h=22+len(rows)*lead
 cv.setFillColor(colors.HexColor('#F2F5FC'));cv.setStrokeColor(blend(ACTIVE,.65));cv.setLineWidth(.5);cv.roundRect(x,top-h,CW,h,4,fill=1,stroke=1)
 cv.setFillColor(colors.HexColor('#E6ECF9'));cv.rect(x+1,top-h+1,34,h-2,fill=1,stroke=0)
 cv.setFillColor(ACTIVE);cv.rect(x,top-h,2.4,h,fill=1,stroke=0)
 y=top-15
 for n,line in rows:
  cv.setFont('Code',fs);cv.setFillColor(colors.HexColor('#56667F'));cv.drawRightString(x+28,y,n)
  xx=x+39;last=0
  for match in TOKEN_PATTERN.finditer(line):
   raw=line[last:match.start()];cv.setFillColor(NAVY);cv.drawString(xx,y,raw);xx+=pdfmetrics.stringWidth(raw,'Code',fs)
   raw=match.group();cv.setFillColor(TOKEN_COLORS[match.lastgroup]);cv.drawString(xx,y,raw);xx+=pdfmetrics.stringWidth(raw,'Code',fs);last=match.end()
  cv.setFillColor(NAVY);cv.drawString(xx,y,line[last:]);y-=lead
 return top-h-12,len(rows)
def related(q):
 ids=[v[2:] if v.startswith('Q-') else v for v in q.get('related',[])]
 return ', '.join(f"Q-{v} (p {loc['q-'+v]})" for v in ids if 'q-'+v in loc)

def cue_for(page):
 ci=page.get('chapter_number',0)
 if not ci:return {}
 title_=chapters[ci-1]['title']
 raw=LEARNING.get('chapters',LEARNING) if isinstance(LEARNING,dict) else LEARNING
 if isinstance(raw,dict):return raw.get(title_,{})
 return next((r for r in raw if r.get('chapter_title',r.get('title'))==title_),{})

def mission(cv,page,bottom_y):
 cue=cue_for(page)
 if not cue:return
 x=xleft(page['page']);w=CW-24;avail=bottom_y-84
 anchors=[]
 for qid in cue.get('three_anchors',[]):
  qid=qid.removeprefix('Q-')
  if 'q-'+qid in loc:anchors.append(f'<a href="#q-{qid}" color="{ACTIVE.hexval()}">Q-{qid} / p {loc["q-"+qid]}</a>')
 body=[p('YOUR CHAPTER MISSION',8.1,10.5,fontName='BodyB',textColor=ACTIVE,spaceAfter=6)]
 if cue.get('one_sentence_hook'):body.append(p(cue['one_sentence_hook'],11.1,14.5,fontName='BodyB',textColor=NAVY,spaceAfter=6))
 if cue.get('finish_line'):body.append(p(cue['finish_line'],9.8,13.1,spaceAfter=6))
 body.append(rich('START WITH  '+'  |  '.join(anchors),8.2,11.1,spaceAfter=0))
 def hh():return 24+sum(it.wrap(w,300)[1]+getattr(it,'spaceAfter',0) for it in body)
 if hh()>avail and len(body)>3:body.pop(1)
 h=hh()
 if h>avail:return
 yy=72;cv.setFillColor(blend(ACTIVE,.94));cv.setStrokeColor(blend(ACTIVE,.6));cv.setLineWidth(.5);cv.roundRect(x,yy,CW,h,5,fill=1,stroke=1)
 cv.setFillColor(ACTIVE);cv.roundRect(x,yy+h-4,CW,4,2,fill=1,stroke=0)
 top=yy+h-12
 for it in body:
  _,ih=it.wrap(w,300);it.drawOn(cv,x+12,top-ih);top-=ih+getattr(it,'spaceAfter',0)

def recall(cv,page,bottom_y):
 if bottom_y<170:return
 cue=cue_for(page);prompt=cue.get('active_recall_prompt','Explain the idea, draw one failure and point to the evidence before checking the answer again.')
 x=xleft(page['page']);cv.setFillColor(blend(ACTIVE,.95));cv.roundRect(x,70,CW,78,4,fill=1,stroke=0)
 cv.setFillColor(ACTIVE);cv.setFont('BodyB',8);cv.drawString(x+10,133,'RECALL IN ONE MINUTE')
 pp=p(prompt,9.4,12.5,spaceAfter=0);_,ph=pp.wrap(CW-20,100);pp.drawOn(cv,x+10,124-ph)
 cv.setFont('Body',8.1)
 for i,t in enumerate(['I can explain it','I can trace it','I can defend it']):
  xx=x+11+i*155;cv.setStrokeColor(ACTIVE);cv.setLineWidth(.6);cv.rect(xx,79,5.6,5.6,fill=0,stroke=1);cv.setFillColor(MUTED);cv.drawString(xx+11,79,t)

layout=[]
cv=canvas.Canvas(str(DEST),pagesize=(W,H),pageCompression=1)
cv.setTitle('LiveKit Agents Audited Study Edition');cv.setAuthor('Prepared for Rahul Ostwal');cv.setSubject('A colorful visual playbook for code decisions concepts and interview preparation')
for page in pages:
 no=page['page'];x=xleft(no);ACTIVE=colors.HexColor(page['accent']);header(cv,page)
 if page.get('key'):cv.bookmarkPage(page['key'])
 kind=page['kind']
 if kind=='cover':
  cv.setFillColor(colors.HexColor('#E8EDFF'));cv.rect(0,466,W,H-466,fill=1,stroke=0)
  cv.setFillColor(GREEN);cv.rect(0,H-12,W,12,fill=1,stroke=0)
  cv.setFont('BodyB',9);cv.drawString(x,762,'THE CODE AND CONCEPTS INTERVIEW PLAYBOOK')
  cv.setFillColor(NAVY);cv.setFont('BodyB',44);cv.drawString(x,694,'LiveKit Agents');cv.drawString(x,641,'Interview');cv.drawString(x,588,'Playbook')
  pp=p('Understand the concept, then defend the code.',15,21,textColor=MUTED,spaceAfter=0);_,ph=pp.wrap(CW,100);pp.drawOn(cv,x,552-ph)
  loop=[('LEARN',GREEN),('TRACE',TEAL),('PREDICT',PURPLE),('DEFEND',AMBER)]
  for i,(name,col) in enumerate(loop):
   xx=x+i*117;cv.setFillColor(col);cv.roundRect(xx,489,109,19,3,fill=1,stroke=0);cv.setFillColor(colors.white);cv.setFont('BodyB',8.4);cv.drawCentredString(xx+54.5,495,name)
  for i,(number,txt,col) in enumerate([(QCOUNT,'MAIN QUESTIONS',GREEN),(FCOUNT,'ANSWERED PROBES',PURPLE),(60,'CODE REVIEWS',TEAL)]):
   xx=x+i*165;cv.setFillColor(colors.white);cv.setStrokeColor(blend(col,.65));cv.setLineWidth(.65);cv.roundRect(xx,358,151,78,4,fill=1,stroke=1);cv.setFillColor(col);cv.rect(xx,432,151,4,fill=1,stroke=0);cv.setFont('BodyB',29);cv.drawString(xx+12,392,str(number));cv.setFont('BodyB',8);cv.drawString(xx+12,374,txt)
  draw_items(cv,[p('A visual guide to the Continuity Ecosystem',17,23,fontName='BodyB',textColor=NAVY),p('Three project deep dives, nineteen diagrams and practical code decisions - with real excerpts, failure scenarios and questions you can rehearse aloud.',11.3,16.4),p('Prepared for Rahul Ostwal',11.1,15,fontName='BodyB',spaceBefore=15),p('Audited study edition / source 6cec82f6718c',9.8,13.5,textColor=MUTED),p('A4 duplex / mirrored binding margins / facing code and answer pages',9.2,13,textColor=MUTED)],top=310)
 elif kind=='blank':
  cv.setFillColor(ACTIVE);cv.setFont('BodyB',8.5);cv.drawString(x,778,'PAUSE / SKETCH / EXPLAIN')
  pp=p('Make the idea your own',24,30,fontName='BodyB',textColor=NAVY);_,hh=pp.wrap(CW,80);pp.drawOn(cv,x,748-hh)
  cue=cue_for(page);prompt=cue.get('diagram_prompt','Draw the authority boundary and one failure schedule. Label what is known and what remains unknown.')
  pp=p(prompt,11.3,16);_,hh=pp.wrap(CW,100);pp.drawOn(cv,x,695-hh)
  cv.setFillColor(colors.HexColor('#DDE5F5'))
  for gx in range(10,int(CW)-4,18):
   for gy in range(171,616,18):cv.circle(x+gx,gy,.55,fill=1,stroke=0)
  cv.setFillColor(MUTED);cv.setFont('Body',8.7);cv.drawString(x,132,'What is known?  What remains unknown?  Which line enforces the boundary?')
  cv.setFont('Body',7.8);cv.drawString(x,84,'This sketch page preserves the duplex reading order.')
 elif kind=='contents':
  y=title(cv,page);draw_items(cv,[p('Main chapters begin on right-hand pages. Code reviews open as left/right spreads. Page numbers are the printed PDF page numbers.',10,14)],top=y);y-=57
  for key,txt in [('content-audit','What the content audit changed'),('role-map','The role and your evidence'),('snapshot','The snapshot you can defend'),('versions','Version namespaces and proof boundaries')]+[(f"chapter-{ch['number']}",f"{ch['number']:02d}  {ch['title']}") for ch in chapters]:
   col=colors.HexColor(pages[loc[key]-1]['accent']);cv.setFillColor(col);cv.roundRect(x,y-2,3,12,1,fill=1,stroke=0)
   cv.setFont('BodyB' if key.startswith('chapter') else 'Body',9.8);cv.setFillColor(INK);cv.drawString(x+11,y,clean(txt));cv.setFillColor(col);cv.drawRightString(x+CW,y,str(loc[key]));cv.linkRect('',key,(x,y-4,x+CW,y+12),thickness=0);y-=26
  assert y>65
 elif kind=='figure-index':
  y=title(cv,page)
  for f in FIGURES.values():
   key='fig-'+f['id'];col=colors.HexColor(pages[loc[key]-1]['accent']);cv.setFillColor(blend(col,.9));cv.roundRect(x,y-3,26,13,2,fill=1,stroke=0);cv.setFillColor(col);cv.setFont('BodyB',7.5);cv.drawString(x+4,y+1,f['id']);cv.setFont('Body',9.1);cv.setFillColor(INK);cv.drawString(x+34,y,f['title']);cv.setFillColor(col);cv.drawRightString(x+CW,y,str(loc[key]));cv.linkRect('',key,(x,y-4,x+CW,y+11),thickness=0);y-=21.5
  y-=12
  for key,txt in [('challenges','Common challenge lookup'),('drill-1','Six coding drills'),('route','A focused preparation route'),('practice','Questions-only practice index'),('sources','Primary references'),('source-map','Deeper source reading maps'),('last-sheet','Final rehearsal sheet')]:
   cv.setFont('BodyB',9.3);cv.drawString(x,y,txt);cv.drawRightString(x+CW,y,str(loc[key]));cv.linkRect('',key,(x,y-4,x+CW,y+11),thickness=0);y-=22
  assert y>60,y
 elif kind=='figure':
  top=title(cv,page)-4;f=FIGURES[page['figure']];low=draw_figure(cv,page['figure'],x,CW,top=top)
  cap=[p(f['caption'],9.6,13.2),p('Connect to the code: '+', '.join(f"Q-{r} (p {loc['q-'+r]})" for r in f['refs']),8.7,12,textColor=MUTED)]
  yy=draw_items(cv,cap,top=low-14)
  layout.append(dict(page=no,kind=kind,bottom=yy))
 elif kind=='chapter':
  cv.addOutlineEntry(f"{page['chapter']['number']:02d} {clean(page['title'])}",page['key'],level=0,closed=True)
  y=title(cv,page);sub=p(page['chapter']['subtitle'],11.5,16,textColor=MUTED,spaceAfter=13);_,hh=sub.wrap(CW,100);sub.drawOn(cv,x,y-hh);y-=hh+20
  yy=draw_items(cv,page['items'],top=y);mission(cv,page,yy);layout.append(dict(page=no,kind=kind,bottom=yy))
 elif kind=='question':
  q=page['question'];cv.addOutlineEntry('Q-'+q['id']+' '+clean(q['title']),page['key'],level=1,closed=True)
  def content(fs):
   it=[QuestionHero(q),label('Model answer')]
   it.extend(p(t,fs,fs*1.39,spaceAfter=7) for t in q['answer']);it.append(label('Follow up probes',PURPLE))
   for j,fu in enumerate(q['followups'],1):it.extend([rich('<font color="#7445B5">'+str(j)+'.</font> '+markup(fu['question']),fs,fs*1.36,fontName='BodyB',spaceAfter=3),p(fu['answer'],fs,fs*1.36,spaceAfter=7)])
   it.extend([Callout('Watch for',q['watch_for'],AMBER,fs-.1),label('Evidence to inspect')])
   for ev in q.get('evidence',[]):it.extend([p(ev['label'],8.2,10.8,textColor=MUTED,spaceAfter=2),p(f"{ev['path']}:{ev['line']}",8.0,10.5,spaceAfter=5)])
   if q.get('sources'):it.append(p('Primary sources: '+', '.join('['+k+']' for k in q['sources']),8.5,11.5))
   return it
  for fs in [10.5,10.3,10.1,10.0]:
   items=content(fs)
   if height(items)<=716:break
  else:raise ValueError('Dense original question '+q['id']+' '+str(height(items)))
  yy=draw_items(cv,items,top=785,bottom=63);recall(cv,page,yy);layout.append(dict(page=no,kind=kind,id=q['id'],font=fs,bottom=yy))
 elif kind=='code':
  q=page['question'];co=q['code'];cv.addOutlineEntry('Q-'+q['id']+' '+clean(q['title']),page['key'],level=1,closed=True)
  items=[QuestionHero(q,'CODE REVIEW / PREDICT'),p(f"{co['path']}:{co['start']}-{co['end']}",8.6,11.5,textColor=MUTED,spaceAfter=8)]
  y=draw_items(cv,items,top=785);y,rows=render_code(cv,q,y)
  rest=[label('Compare an alternative'),p(q['alternatives'],10.2,14.1),Callout('Predict this tempting edit',q['counterfactual'],CORAL,10.2),label('Inspect the existing assertion'),p(q['test']['name'],8.8,11.8,fontName='Code'),p(q['test']['assertion'],10,13.8),p(q['test']['path'],8.1,10.7,textColor=MUTED)]
  yy=draw_items(cv,rest,top=y)
  if yy>124:
   cv.setFont('BodyB',7.8);cv.setFillColor(MUTED);cv.drawString(x,101,'YOUR PREDICTION / INVARIANT');cv.setStrokeColor(LINE);cv.line(x,87,x+CW,87);cv.line(x,70,x+CW,70)
  layout.append(dict(page=no,kind=kind,id=q['id'],code_rows=rows,bottom=yy))
 elif kind=='defense':
  q=page['question'];cv.setFillColor(blend(ACTIVE,.9));cv.roundRect(x,770,CW,24,3,fill=1,stroke=0);cv.setFont('BodyB',8.5);cv.setFillColor(ACTIVE);cv.drawString(x+10,778,'Q-'+q['id']+' / DEFEND THE DECISION')
  def defense(fs):
   it=[p(q['title'],17.3,21.7,fontName='BodyB',textColor=NAVY,spaceAfter=9),label('What the code does')]
   it.extend(p(t,fs,fs*1.39,spaceAfter=7) for t in q['answer'])
   it.append(label('Common implementation challenge'))
   for name,col in [('symptom',CORAL),('diagnosis',GREEN),('handling',TEAL)]:it.append(rich('<b><font color="'+col.hexval()+'">'+name.capitalize()+'.</font></b> '+markup(q['challenge'][name]),fs,fs*1.37,spaceAfter=6))
   it.append(label('Follow up probes',PURPLE))
   for j,fu in enumerate(q['followups'],1):it.extend([rich('<font color="#7445B5">'+str(j)+'.</font> '+markup(fu['question']),fs,fs*1.35,fontName='BodyB',spaceAfter=3),p(fu['answer'],fs,fs*1.35,spaceAfter=6)])
   it.extend([Callout('Watch for',q['watch_for'],AMBER,fs-.1),p('Earlier context: '+related(q),8.5,11.3,textColor=MUTED)])
   return it
  for fs in [10.5,10.3,10.1,10.0]:
   items=defense(fs)
   if height(items)<=700:break
  else:raise ValueError('Dense defense '+q['id']+' '+str(height(items)))
  yy=draw_items(cv,items,top=755,bottom=61);recall(cv,page,yy);layout.append(dict(page=no,kind=kind,id=q['id'],font=fs,bottom=yy))
 elif kind=='challenge':
  y=title(cv,page);items=[]
  for e in page['entries']:
   refs=', '.join(f"Q-{r.removeprefix('Q-')} (p {loc['q-'+r.removeprefix('Q-')]})" for r in e['question_ids'])
   items.extend([label(e['title']),p('Symptom: '+e['symptom'],9.7,13.1,spaceAfter=4),p('First check: '+e['first_check'],9.7,13.1,spaceAfter=4),p('Handling: '+e['handling'],9.7,13.1,spaceAfter=4),p('Avoid: '+e['avoid'],9.7,13.1,spaceAfter=4),p(refs,8.3,11.1,textColor=MUTED,spaceAfter=8)])
  yy=draw_items(cv,items,top=y);layout.append(dict(page=no,kind=kind,bottom=yy))
 elif kind=='practice':
  y=title(cv,page)
  for q in page['entries']:
   key='q-'+q['id'];s=f"<a href='#{key}' color='#164638'><b>Q-{q['id']}</b></a>  {markup(q['question'])}"
   pp=rich(s,10.0,13.5,spaceAfter=0);_,hh=pp.wrap(CW-16,1000);pp.drawOn(cv,x+14,y-hh)
   cv.setStrokeColor(INK);cv.setLineWidth(.5);cv.rect(x,y-9,6,6,fill=0,stroke=1);cv.setFont('Body',8);cv.setFillColor(MUTED);cv.drawRightString(x+CW,y-hh-11,'Answer page '+str(loc[key]));y-=hh+25
  if y<61:raise ValueError('Index overflow '+str(no))
 else:
  y=title(cv,page);yy=draw_items(cv,page['items'],top=y);layout.append(dict(page=no,kind=kind,bottom=yy))
 cv.showPage()
cv.save()
manifest=dict(pdf=str(DEST),pages=len(pages),sheets_duplex=math.ceil(len(pages)/2),questions=QCOUNT,answered_followups=FCOUNT,code_reviews=60,vector_figures=len(FIGURES),challenge_patterns=len(challenges),commit=HEAD,sha256=hashlib.sha256(DEST.read_bytes()).hexdigest(),page_map=loc,chapter_pages=[loc[f"chapter-{ch['number']}"] for ch in chapters],margins=dict(inner_pt=INNER,outer_pt=OUTER),minimum_body_font=min(e['font'] for e in layout if 'font' in e))
(BASE/'manifest.json').write_text(json.dumps(manifest,indent=2))
(BASE/'layout.json').write_text(json.dumps(layout,indent=2))
(BASE/'book-content.json').write_text(json.dumps(dict(chapters=chapters,sources=src,challenges=challenges,figures=FIGURES),indent=2))
(BASE/'pages.json').write_text(json.dumps([{k:v for k,v in pg.items() if k not in ['items','question','chapter','entries']} for pg in pages],indent=2))
print(json.dumps({k:v for k,v in manifest.items() if k not in ['page_map','chapter_pages']},indent=2))
