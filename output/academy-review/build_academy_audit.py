"""Build the course audit without altering the interview book or application."""
from __future__ import annotations

from collections import Counter
import hashlib
import html
import json
from pathlib import Path
import re

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import BaseDocTemplate, Frame, PageTemplate, Paragraph, Spacer, PageBreak, KeepTogether, Table, TableStyle, Flowable
from reportlab.platypus.tableofcontents import TableOfContents

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
PDF = REPO / "output/pdf/LiveKit-Academy-Course-Audit-and-Book-Recommendations.pdf"
HTML = ROOT / "LiveKit-Academy-Course-Audit.html"
RT = Path("/Users/rostwal/.cache/codex-runtimes/codex-primary-runtime/dependencies")
for name, file in (("Body","LiberationSans-Regular.ttf"),("BodyB","LiberationSans-Bold.ttf"),("BodyI","LiberationSans-Italic.ttf")):
    pdfmetrics.registerFont(TTFont(name, str(RT/"node/node_modules/pdfjs-dist/standard_fonts"/file)))
pdfmetrics.registerFontFamily("Body", normal="Body", bold="BodyB", italic="BodyI", boldItalic="BodyB")
pdfmetrics.registerFont(TTFont("Display", "/System/Library/Fonts/Supplemental/Georgia Bold.ttf"))
W,H = 595.2756,841.8898
CW = W-68-46
NAVY=colors.HexColor("#162647"); INK=colors.HexColor("#202B3C"); MUTED=colors.HexColor("#5F6F88")
BLUE=colors.HexColor("#2D46D7"); TEAL=colors.HexColor("#087E78"); PURPLE=colors.HexColor("#7445B5")
AMBER=colors.HexColor("#A65F05"); LINE=colors.HexColor("#C9D4E8"); PALE=colors.HexColor("#EDF1FF")


def read(name): return json.loads((ROOT/name).read_text())
def as_text(v):
    if isinstance(v,str):return v
    if isinstance(v,list):return " ".join(as_text(x) for x in v)
    if isinstance(v,dict):return "; ".join(f"{k}: {as_text(x)}" for k,x in v.items())
    return str(v) if v is not None else ""
def get(d,*keys,default=None):
    for key in keys:
        if d.get(key) is not None:return d[key]
    return default
def qids(v):
    if isinstance(v,list):
        return list(dict.fromkeys(x["id"] if isinstance(x,dict) else x for x in v))
    return []
def clean(s):
    for a,b in {"\u2011":"-","\u2013":"-","\u2014":" - ","\u2018":"'","\u2019":"'","\u201c":'"',"\u201d":'"',"\u00a0":" "}.items():s=s.replace(a,b)
    return s
def esc(s):return html.escape(clean(as_text(s)),quote=False)
def urls(value):
    found=[]
    if isinstance(value,str):found.extend(re.findall(r'https://[^\s<>"\]]+',value))
    elif isinstance(value,dict):
        for v in value.values():found.extend(urls(v))
    elif isinstance(value,list):
        for v in value:found.extend(urls(v))
    return list(dict.fromkeys(found))


def normalize():
    catalogue=read("course-catalogue.json"); crawl=read("crawl-inventory.json"); plan=read("editorial-plan.json")
    book=json.loads((REPO/"output/book-audit/source/audited-content.json").read_text())
    manifest=json.loads((REPO/"output/book-audit/source/manifest.json").read_text())
    existing={q["id"]:{"title":q["title"],"page":manifest["page_map"].get("q-"+q["id"])} for c in book["chapters"] for q in c["questions"]}
    course_reviews={}; proposals=[]; cautions=[]; sources={}; quizzes=[]
    for owner in ["p1","p2","p3"]:
        review=read(owner+"-course-review.json")
        crs=get(review,"courses","inventory","course_chapter_inventory",default=[])
        for c in crs:
            cid=get(c,"courseid","course_id","id")
            chapters=get(c,"chapterinventory","chapters",default=[])
            lessons=[]
            for row in chapters:
                action=as_text(get(row,"recommendation","judgment",default="review"))
                note=as_text(get(row,"assessment","judgment",default=""))
                extra=as_text(get(row,"concrete_gap_or_action",default=""))
                if extra:note+=" "+extra
                ids=qids(get(row,"coverageexistingQIDs","existingQIDcoverage","existing_qids",default=[]))
                assert all(x in existing for x in ids),(cid,ids)
                lessons.append({"title":row["title"],"url":row["url"],"action":action,"assessment":note,"existing_qids":ids})
            course_reviews[cid]={"summary":as_text(get(c,"summary","assessment",default="")),"chapters":lessons}
            for issue in c.get("technicalcautions",[]):
                cautions.append({"owner":owner,"course_id":cid,"data":issue})
        for key in ["technicalcautions","cautions"]:
            for issue in review.get(key,[]):cautions.append({"owner":owner,"data":issue})
        owner_sources={}
        for source in get(review,"officialsources","primarysources","official_sources",default=[]):
            source_url=source.get("url")
            if source_url:
                title=source.get('title') or sources.get(source_url,{}).get('title')
                if not title:title=source_url.rstrip('/').split('/')[-1].replace('-',' ').capitalize()
                sources[source_url]={"url":source_url,"title":title,"supports":as_text(get(source,"supports","scope","verified_use",default=""))}
                owner_sources[source['id']]=source_url
        for q in review.get("proposed_questions",[]):
            related=qids(get(q,"related_existing_QIDs","existingQIDcoverage","existing_qids",default=[]))
            assert all(x in existing for x in related),(q["id"],related)
            source_ids=get(q,'official_source_ids','primarysources','source_ids',default=[])
            assert all(s in owner_sources for s in source_ids),(q['id'],source_ids)
            proposals.append({"id":q["id"],"title":q["title"],"question":q["question"],"answer":q["answer"],"followups":q["followups"],"existing_qids":related,"rationale":as_text(get(q,"gap_boundary","new_value","gap",default="")),"source_urls":[owner_sources[s] for s in source_ids]})
        quizzes.append({"owner":owner,"audit":review.get("quiz_audit")})
    assert quizzes[0]['audit']['reviewed_count']==136
    assert quizzes[1]['audit']['counts']['quiz_questions_reviewed']==91
    assert quizzes[2]['audit']['count_reviewed']==134
    assert set(course_reviews)=={c["id"] for c in catalogue}
    courses=[]
    for c in catalogue:
        review=course_reviews[c["id"]]
        by_url={l["url"]:l for l in review["chapters"]}
        assert set(by_url)=={l["url"] for l in c["chapters"]},c["id"]
        lessons=[]
        for index,l in enumerate(c["chapters"],1):
            snapshot=crawl["lessons"][l["url"]]
            lessons.append({**l,**by_url[l["url"]],"id":c["id"]+f".{index}","quiz_count":snapshot.get("quiz_questions",0)})
        decision=plan["course_decisions"][c["id"]]
        courses.append({**c,**decision,"review_summary":review["summary"],"chapters":lessons,"quiz_count":sum(l["quiz_count"] for l in lessons)})
    selection=["REC-P1-01","REC-P1-03","REC-P1-05","REC-P1-06","REC-P1-07","AC-P2-01","AC-P2-02","AC-P2-03","AC-P2-05","AC-P3-01","AC-P3-04","AC-P3-05","AC-P3-06","AC-P3-07","AC-P3-08"]
    assert set(selection)<={q["id"] for q in proposals}
    data={"date":plan["date"],"plan":plan,"courses":courses,"proposals":proposals,"selected_ids":selection,"cautions":cautions,"sources":list(sources.values()),"existing":existing,"quiz_reviews":quizzes,
          "counts":{"courses":len(courses),"chapters":sum(len(c['chapters']) for c in courses),"quizzes":sum(c['quiz_count'] for c in courses),"code_blocks_retained":sum(c.get('code_blocks',0) for c in crawl['lessons'].values()),"proposed_questions":len(proposals),"shortlisted_questions":len(selection)},
          "book":{"path":manifest['pdf'],"pages":manifest['pages'],"questions":manifest['questions'],"sha256":hashlib.sha256(Path(manifest['pdf']).read_bytes()).hexdigest(),"expected_sha256":manifest['sha256']}}
    assert data['book']['sha256']==data['book']['expected_sha256']
    (ROOT/"consolidated-audit.json").write_text(json.dumps(data,indent=2)+"\n")
    return data


def p(text,size=10.2,bold=False,color=INK,after=7,leading=None,markup=False):
    return Paragraph(text if markup else esc(text),ParagraphStyle("p",fontName="BodyB" if bold else "Body",fontSize=size,leading=leading or size*1.36,textColor=color,spaceAfter=after))
def link(label,url,size=8.4):
    return p(f'<a href="{html.escape(url,quote=True)}" color="#2D46D7">{esc(label)}</a>',size=size,leading=size*1.3,markup=True,after=5)
def heading(text,level=1,key=None):
    x=Paragraph(esc(text),ParagraphStyle("H"+str(level),fontName="Display" if level==1 else "BodyB",fontSize=21 if level==1 else 12.5,leading=26 if level==1 else 16,textColor=NAVY,spaceBefore=4 if level==1 else 8,spaceAfter=11 if level==1 else 7,keepWithNext=True))
    x.audit_key=key;x.audit_level=level-1
    return x
def label(text):return p(text.upper(),8.2,True,TEAL,after=4)
def ref_text(ids,data):
    return "; ".join(f"{qid} p{data['existing'][qid]['page']}" for qid in ids) if ids else "New topic; no direct existing question."
def tb(rows,widths,size=9.2):
    t=Table([[p(x,size=size,after=0,leading=size*1.33,bold=i==0) for x in row] for i,row in enumerate(rows)],colWidths=widths,hAlign="LEFT",repeatRows=1)
    t.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),7),('RIGHTPADDING',(0,0),(-1,-1),7),('TOPPADDING',(0,0),(-1,-1),6),('BOTTOMPADDING',(0,0),(-1,-1),6),('BACKGROUND',(0,0),(-1,0),PALE),('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#F8FAFF')]),('LINEBELOW',(0,0),(-1,-1),.4,LINE)]))
    return t


class Route(Flowable):
    def wrap(self,w,h):self.width=w;return w,80
    def draw(self):
        labels=[("Inventory","20 / 133 / 361"),("Check","Docs + SDK source"),("Compare","220 book questions"),("Recommend","Focused additions")]
        width=(self.width-36)/4
        for i,(a,b) in enumerate(labels):
            x=i*(width+12)
            self.canv.setFillColor(PALE);self.canv.roundRect(x,10,width,58,5,fill=1,stroke=0)
            self.canv.setFillColor(BLUE);self.canv.setFont('BodyB',10.2);self.canv.drawString(x+9,47,a)
            self.canv.setFillColor(INK);self.canv.setFont('Body',7.7);self.canv.drawString(x+9,28,b)
            if i<3:
                self.canv.setStrokeColor(TEAL);self.canv.line(x+width+2,38,x+width+10,38)
                self.canv.line(x+width+7,41,x+width+10,38);self.canv.line(x+width+7,35,x+width+10,38)


class AuditDoc(BaseDocTemplate):
    def __init__(self,path):
        super().__init__(str(path),pagesize=(W,H),leftMargin=68,rightMargin=46,topMargin=51,bottomMargin=49,title="LiveKit Academy Course Audit and Book Recommendations",author="Prepared for Rahul Ostwal")
        self.map={}
        for name,x,next_name in [('Odd',68,'Even'),('Even',46,'Odd')]:
            self.addPageTemplates(PageTemplate(id=name,frames=[Frame(x,49,CW,H-100,leftPadding=0,rightPadding=0,topPadding=0,bottomPadding=0)],onPage=self.decorate,autoNextPageTemplate=next_name))
    def decorate(self,c,doc):
        x=68 if doc.page%2 else 46
        c.setFont('BodyB',7.8);c.setFillColor(BLUE);c.drawString(x,H-30,"ACADEMY AUDIT / RECOMMENDATIONS / 19 NOV 2026")
        c.setStrokeColor(LINE);c.setLineWidth(.5);c.line(x,39,x+CW,39)
        c.setFont('Body',7.8);c.setFillColor(MUTED);c.drawString(x,25,"READ-ONLY COURSE AUDIT / CURRENT BOOK PRESERVED")
        c.drawRightString(x+CW,25,str(doc.page))
    def afterFlowable(self,f):
        if hasattr(f,'audit_key') and f.audit_key:
            self.canv.bookmarkPage(f.audit_key);self.canv.addOutlineEntry(f.getPlainText(),f.audit_key,f.audit_level,False)
            self.map[f.audit_key]=self.page
            if f.audit_level==0:self.notify('TOCEntry',(0,f.getPlainText(),self.page,f.audit_key))


def pdf_report(data):
    story=[]
    story += [Spacer(1,28),p("A SOURCE-CHECKED CURRICULUM REVIEW",9.0,True,TEAL),p("What belongs in\nyour LiveKit book",28,True,NAVY,leading=34),p("A deep audit of all public courses, chapter text, code examples and delivered quiz explanations",13,False,MUTED,leading=18),Spacer(1,18),Route(),Spacer(1,20),p(data['plan']['decision'],12,leading=17),Spacer(1,13),p("Prepared for Rahul Ostwal",11,True),p("19 November 2026 / A4 duplex / mirrored book-style margins",9.3,color=MUTED),Spacer(1,18),p("This report recommends changes. It does not revise the audited interview book, qualify the POC, or claim course or certification completion.",10.5,color=MUTED),PageBreak()]
    story.append(heading("Read this report",key="contents"))
    toc=TableOfContents();toc.levelStyles=[ParagraphStyle('toc',fontName='Body',fontSize=11,leading=16,spaceBefore=7,textColor=NAVY)]
    story += [toc,Spacer(1,18),label("Review scope"),p("20 course pages and 133 chapter pages were reachable with HTTP 200. The reading audit covered their public article text, displayed examples and 361 quiz prompts/options/explanations delivered in those public pages. No login, answer submission, completion action or hidden/private resource was used."),p("691 code blocks were retained for inspection. Selected API contracts were checked statically against installed livekit-agents 1.8.11, the repository's declared pin, and current official documentation. This is not a claim that all examples execute successfully."),p("No providers, deployments, audio experiments or course exercises were run; no videos were watched. Advertised course durations total 48 hours; listed chapter estimates total 44 hours 20 minutes. Neither total includes a verified practice-time estimate."),p("The baseline is the existing 392-page book, with 220 main questions and 501 answered follow-ups. Its PDF hash is checked before and after this build. Current documentation is a comparison source, not permission to silently upgrade the project."),PageBreak()]
    story.append(heading("Findings and recommendation",key="recommendation"))
    story += [p("Add a focused advanced supplement and expand selected existing answers. The largest gaps concern framework-native abstractions, frontend APIs, voice RAG, behavior evaluation and phone routing. More generic WebRTC or durability exposition would add less value."),Route(),label("Recommended scope"),tb([["Change","Recommendation"],["New questions","Shortlist 15 original scenarios from the 24 reviewed proposals."],["Existing answers","Expand targeted runtime, interruption, testing, latency and deployment explanations; retain stable IDs."],["Visuals and practice","Five diagrams and four bounded exercises, with explicit expected evidence."],["Print budget","Aim for approximately 30-40 added pages after typesetting, with the existing typography, gutter and navigation."],["Keep as optional","Hardware projects, avatar vendor setup, carrier provisioning, changing pricing tables and credential claims."]],[126,CW-126]),label("How to use the courses"),p("Read high-priority lessons for their problems and design dimensions. Rebuild any adopted example against the selected SDK version and inspect the actual resource, authority and failure boundaries. Use primary documentation to correct mismatched APIs or operational guarantees."),label("An important distinction"),p("A course may identify an excellent topic while showing an incompatible example. A 'correct' chapter decision below means fix or qualify the teaching before reuse; it does not mean that the existing book has that defect."),p(data['plan']['study_budget']),PageBreak()]
    story.append(heading("Course by course decisions",key="courses"))
    story.append(p("High = important book gap. Selective = useful targeted depth or an existing-answer expansion. Reference = mostly covered. Optional = outside the immediate preparation priority. These are editorial priorities, not runtime benchmark or credential ratings.",9.5,color=MUTED))
    for index,c in enumerate(data['courses']):
        block=[heading(c['id']+"  "+c['title'],2,"course-"+c['id']),p(f"{c['priority'].upper()} / {len(c['chapters'])} chapters / {c['quiz_count']} public quiz items / advertised {c['advertised_minutes']} min",8.4,True,TEAL),p(c['decision']),label("What to do in the book"),p(c['treatment']),p("Existing coverage: "+ref_text(c['existing'],data),8.8,color=MUTED),link(c['url'],c['url'])]
        # Keep the summary card intact; detailed judgments follow in the chapter ledger.
        story.append(KeepTogether(block));story.append(Spacer(1,10))
        if index in (2,6,10,13,16):story.append(PageBreak())
    story.append(PageBreak())
    story.append(heading("Corrections before copying examples",key="corrections"))
    story.append(p("The following are representative, source-checked reasons to verify examples. Full course and quiz caution registers are retained in the accompanying audit data; this report does not republish an assessment answer key."))
    issues=read("headline-findings.json")
    for n,issue in enumerate(issues,1):
        block=[heading(f"F{n:02d}  "+issue['title'],2,"finding-"+str(n)),p(issue['observed']),p(issue['correction'],color=TEAL),p("Book implication: "+issue['book_action'],9.5)]
        for title,url in issue['sources']:block.append(link(title,url))
        story.append(KeepTogether(block));story.append(Spacer(1,7))
    story.append(PageBreak())
    story.append(heading("A concrete book integration plan",key="integration"))
    for i,item in enumerate(data['plan']['integration_plan'],1):
        story.append(KeepTogether([heading(f"{i:02d}  "+item['title'],2),p("Courses "+", ".join(item['courses'])+" / "+item['placement'],8.7,True,TEAL),p(item['change'])]))
    story.append(PageBreak())
    story.append(heading("Diagrams and exercises worth adding",key="visuals"))
    story.append(label("Five diagrams"))
    for item in data['plan']['diagrams']:story.append(p(item['title']+". "+item['purpose']))
    story.append(label("Four exercises - proposed, not executed"))
    for item in data['plan']['labs']:
        story.append(KeepTogether([p(item['title'],10.3,True,TEAL,after=3),p(item['exercise'],after=3),p("Expected evidence: "+item['assertion'],9.6)]))
    story.append(p(data['plan']['print_plan'],9.6,color=MUTED));story.append(PageBreak())
    story.append(heading("Original interview question shortlist",key="shortlist"))
    story.append(p("These 15 original proposals are the recommended core. They are not copied course quizzes. The searchable report also contains all 24 candidate answers and answered follow-ups, so additions can be reviewed before typesetting the book.",9.6,color=MUTED))
    by_id={q['id']:q for q in data['proposals']}
    for qid in data['selected_ids']:
        q=by_id[qid]
        block=[heading(qid+"  "+q['title'],2),p(q['question'],10.4,True),p("Connect to: "+ref_text(q['existing_qids'],data),8.5,color=MUTED)]
        for f in q['followups']:
            block.append(p("Follow-up: "+as_text(f['question']),9.5,after=4))
        story.append(KeepTogether(block))
    story.append(PageBreak())
    story.append(heading("Every chapter reviewed",key="ledger"))
    story.append(p("Each entry links to its public lesson and maps the editorial decision to existing book questions. A correction applies to the course teaching/example; it is not an assertion of a production incident. Quiz items were read as public data, without attempting the assessments.",9.6,color=MUTED))
    for c in data['courses']:
        for row_index,row in enumerate(c['chapters']):
            action=clean(row['action']).replace('_',' ')
            # Avoid using the P1 prose judgment as a category: its recommendation is separate.
            block=[p(row['id']+"  "+row['title'],10.0,True,NAVY,after=3),p(action.upper()+f" / {row['quiz_count']} quiz items",7.9,True,TEAL,after=3),p(row['assessment'],9.2,leading=12.3,after=4),p("Book: "+ref_text(row['existing_qids'],data),8.0,color=MUTED,after=3),link("Lesson / "+row['url'].split('/')[-1],row['url'],8.0)]
            if row_index==0:block.insert(0,heading(c['id']+"  "+c['title'],2))
            story.append(KeepTogether(block))
    story.append(PageBreak())
    story.append(heading("Primary references and scope",key="sources"))
    story += [p("Primary documentation supports corrections; the Academy pages supply the curriculum being assessed. Official documentation may evolve, so adopted code must keep an explicit version label and receive a separate execution check."),p("Pinned source: livekit-agents 1.8.11 installed in this checkout; browser livekit-client 2.23.0. The static evidence ledger records paths, signatures and line numbers. Source inspection is not application qualification."),p("The reviewed course titles and chapter metadata are used for traceability. Course articles, code collections and quiz answer keys have not been reproduced in this report."),p("Book preserved: "+data['book']['sha256'],8.0,color=MUTED)]
    for i,s in enumerate(data['sources'],1):
        story.append(KeepTogether([p(f"S{i:02d}  "+as_text(s['title']),9.2,True,after=3),link(s['url'],s['url']),p(s['supports'],8.5,color=MUTED,after=8)]))
    doc=AuditDoc(PDF);doc.multiBuild(story)
    return doc.map


def html_report(data):
    e=lambda x:html.escape(as_text(x))
    bookref=lambda ids:'; '.join(f'<a href="../pdf/LiveKit-Agents-Audited-Study-Edition.pdf#page={data["existing"][i]["page"]}">{e(i)} p{data["existing"][i]["page"]}</a>' for i in ids) if ids else 'New topic; no direct existing question.'
    blocks=[]
    for c in data['courses']:
        lessons=''.join(f'<tr><td>{e(l["id"])}</td><td><a href="{e(l["url"])}">{e(l["title"])}</a><small>{e(l["action"]).replace("_"," ")} · {l["quiz_count"]} quiz items</small><p>{e(l["assessment"])}</p><small>{bookref(l["existing_qids"])}</small></td></tr>' for l in c['chapters'])
        blocks.append(f'<article class="course" data-search="{e((c["id"]+" "+c["title"]+" "+" ".join(l["title"]+" "+l["assessment"] for l in c["chapters"])).lower())}"><div class="eyebrow">COURSE {e(c["id"])} · {e(c["priority"])} PRIORITY · {len(c["chapters"])} CHAPTERS</div><h2>{e(c["title"])}</h2><p>{e(c["decision"])}</p><p><b>Book treatment.</b> {e(c["treatment"])}</p><p class="muted">Existing coverage: {bookref(c["existing"])}</p><p><a href="{e(c["url"])}">Open course</a> · {c["quiz_count"]} public quiz items reviewed</p><details><summary>Read all {len(c["chapters"])} chapter judgments</summary><table>{lessons}</table></details></article>')
    findings=''.join('<article><h3>F%02d %s</h3><p>%s</p><p class="correction">%s</p><p><b>Book implication.</b> %s</p><p>%s</p></article>'%(i,e(f['title']),e(f['observed']),e(f['correction']),e(f['book_action']),' · '.join(f'<a href="{e(url)}">{e(title)}</a>' for title,url in f['sources'])) for i,f in enumerate(read('headline-findings.json'),1))
    proposals=[]
    for q in sorted(data['proposals'],key=lambda q:(q['id'] not in data['selected_ids'],q['id'])):
        answer=q['answer'] if isinstance(q['answer'],list) else [q['answer']]
        fus=''.join(f'<h4>{e(f["question"])}</h4><p>{e(f["answer"])}</p>' for f in q['followups'])
        refs=' · '.join(f'<a href="{e(u)}">{e(u)}</a>' for u in q['source_urls'])
        proposals.append(f'<details class="proposal"><summary>{e(q["id"])} · {e(q["title"])} {"— CORE" if q["id"] in data["selected_ids"] else "— OPTIONAL / MERGE"}</summary><h3>{e(q["question"])}</h3>'+''.join(f'<p>{e(a)}</p>' for a in answer)+fus+f'<small>Existing book: {bookref(q["existing_qids"])}</small><small>Primary references: {refs or "Project invariants and static example analysis; validate adopted code separately."}</small></details>')
    integration=''.join(f'<li><b>{e(x["title"])}</b><p>{e(x["change"])}</p><small>{e(x["placement"])}</small></li>' for x in data['plan']['integration_plan'])
    sources=''.join(f'<li><a href="{e(s["url"])}">{e(s["title"])}</a><p>{e(s["supports"])}</p></li>' for s in data['sources'])
    content=f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>LiveKit Academy course audit</title><style>
    :root{{--navy:#162647;--ink:#202b3c;--muted:#5f6f88;--blue:#2d46d7;--teal:#087e78;--line:#c9d4e8}}*{{box-sizing:border-box}}body{{margin:0;background:#f1f4fa;color:var(--ink);font:16px/1.6 Arial,sans-serif}}main{{max-width:1060px;margin:auto;padding:40px 30px 80px}}h1,h2{{color:var(--navy);line-height:1.22}}h1{{font:700 44px/1.15 Georgia,serif;max-width:800px}}h2{{font-size:25px}}h3{{line-height:1.35}}a{{color:var(--blue);overflow-wrap:anywhere}}.eyebrow{{color:var(--teal);font-size:12px;font-weight:bold;letter-spacing:.08em}}.stats{{display:flex;gap:12px;flex-wrap:wrap;margin:28px 0}}.stats div{{background:white;padding:16px 23px;border:1px solid var(--line);border-radius:8px}}.stats strong{{display:block;font-size:29px;color:var(--blue)}}nav{{display:flex;gap:18px;flex-wrap:wrap;margin:25px 0}}article,.proposal{{background:white;border:1px solid var(--line);border-radius:8px;padding:23px;margin:18px 0}}small,.muted{{color:var(--muted)}}small{{display:block;font-size:13px}}summary{{cursor:pointer;font-weight:bold;color:var(--navy)}}details[open]>summary{{margin-bottom:18px}}table{{border-collapse:collapse;width:100%;font-size:14px}}td{{vertical-align:top;border-top:1px solid var(--line);padding:13px 10px}}td:first-child{{white-space:nowrap;color:var(--teal);font-weight:bold}}td p{{margin:8px 0}}input{{width:100%;padding:14px;border:1px solid #9eafcc;border-radius:6px;font:inherit;background:white}}.correction{{border-left:3px solid var(--teal);padding-left:14px}}.scope{{font-size:14px;color:var(--muted)}}section{{margin-top:48px}}ol>li{{padding:10px 0}}.hidden{{display:none}}@media print{{@page{{size:A4;margin:20mm 16mm}}body{{background:white;font-size:10pt}}main{{padding:0}}nav,input,button{{display:none}}h1{{font-size:27pt}}article,.proposal{{break-inside:avoid;border:0;border-bottom:1px solid #bbb;padding:8pt 0}}details:not([open])>*:not(summary){{display:block}}a{{color:#162647;text-decoration:none}}section{{break-before:page}}}}
    </style><main><div class="eyebrow">SOURCE-CHECKED CURRICULUM REVIEW · 19 NOVEMBER 2026</div><h1>What belongs in your LiveKit book</h1><p>{e(data['plan']['decision'])}</p><div class="stats"><div><strong>20</strong>courses</div><div><strong>133</strong>chapters</div><div><strong>361</strong>public quiz items</div><div><strong>15</strong>core question proposals</div></div><nav><a href="#courses">Course audit</a><a href="#corrections">Corrections</a><a href="#integration">Book plan</a><a href="#questions">Candidate questions</a><a href="#sources">Primary sources</a></nav><p class="scope">All public article text and examples were reviewed, with a separate public quiz-data pass. Selected contracts were checked against official documentation and installed Python SDK 1.8.11. No examples, providers, videos, assessments or deployments were executed. The current 392-page book remains unchanged.</p><section id="courses"><h2>All courses and chapter judgments</h2><label for="filter">Filter by course, chapter or topic</label><input id="filter" placeholder="Try RAG, SIP, testing, interruption, or a course number">{''.join(blocks)}</section><section id="corrections"><h2>Corrections before copying examples</h2>{findings}</section><section id="integration"><h2>Recommended book integration</h2><ol>{integration}</ol><h3>Print plan</h3><p>{e(data['plan']['print_plan'])}</p><h3>Study budget</h3><p>{e(data['plan']['study_budget'])}</p></section><section id="questions"><h2>24 original candidate questions</h2><p>15 are shortlisted for the core; nine are optional or merge candidates. These are newly written proposals, not a copied quiz bank.</p>{''.join(proposals)}</section><section id="sources"><h2>Primary references and scope</h2><ol>{sources}</ol><p class="scope">Snapshots, signature checks and reviewer ledgers are retained alongside this report. Quiz answer keys are not republished here. Source reading does not qualify the POC or certify a credential. Book hash preserved: {e(data['book']['sha256'])}</p></section></main><script>document.getElementById('filter').addEventListener('input',event=>{{const q=event.target.value.trim().toLowerCase();document.querySelectorAll('.course').forEach(c=>c.classList.toggle('hidden',!c.dataset.search.includes(q)));}});</script></html>'''
    HTML.write_text(content)


if __name__=='__main__':
    data=normalize()
    html_report(data)
    pages=pdf_report(data)
    assert hashlib.sha256(Path(data['book']['path']).read_bytes()).hexdigest()==data['book']['sha256'], 'Interview book changed during report build'
    from pypdf import PdfReader
    manifest={"pdf":str(PDF),"html":str(HTML),"pages":len(PdfReader(PDF).pages),"counts":data['counts'],"page_map":pages,"book_sha256":data['book']['sha256'],"sha256":hashlib.sha256(PDF.read_bytes()).hexdigest()}
    (ROOT/'report-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps(manifest,indent=2))
