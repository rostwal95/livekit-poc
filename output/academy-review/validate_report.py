"""Check audit completeness, cross-references, output geometry and book preservation."""
from pathlib import Path
from lxml import html
import json
import hashlib
import re
import pdfplumber

ROOT=Path(__file__).resolve().parent
d=json.loads((ROOT/'consolidated-audit.json').read_text())
m=json.loads((ROOT/'report-manifest.json').read_text())
root=html.fromstring(Path(m['html']).read_bytes())
assert len(root.xpath('//article[@class="course"]'))==20
assert len(root.xpath('//article[@class="course"]//tr'))==133
assert len(root.xpath('//details[@class="proposal"]'))==24
assert sum(len(q['followups']) for q in d['proposals'])==48
assert len({x['url'] for c in d['courses'] for x in c['chapters']})==133
assert sum(x['quiz_count'] for c in d['courses'] for x in c['chapters'])==361
assert all(x['assessment'] and x['action'] for c in d['courses'] for x in c['chapters'])
assert all(qid in d['existing'] for c in d['courses'] for x in c['chapters'] for qid in x['existing_qids'])
assert all(x['http_status']==200 for c in d['courses'] for x in c['chapters'])
assert len(d['selected_ids'])==15
assert hashlib.sha256(Path(d['book']['path']).read_bytes()).hexdigest()==d['book']['expected_sha256']
texts=[]
outside=[]
with pdfplumber.open(m['pdf']) as pdf:
    for number,page in enumerate(pdf.pages,1):
        texts.append(page.extract_text() or '')
        for char in page.chars:
            if char['text'].strip() and (char['x0']<43 or char['x1']>552 or char['top']<15 or char['bottom']>825):
                outside.append((number,char['text'],char['x0'],char['top']))
assert not outside,outside[:10]
text='\n'.join(texts)
compact=lambda value:re.sub(r'\s+',' ',value).strip()
assert all(compact(x['title']) in compact(text) for x in d['proposals'] if x['id'] in d['selected_ids'])
assert not any(x in text for x in ['\ufffd','\u25a0','Lorem ipsum','TODO'])
assert len(texts)==m['pages']
assert all(re.search(r'\b'+re.escape(row['id'])+r'\b',text) for c in d['courses'] for row in c['chapters'])
js=root.xpath('//script/text()')
(ROOT/'report-ui-check.js').write_text('\n'.join(js))
report={
    'status':'passed','pages':len(texts),'all_course_cards':20,
    'unique_chapter_judgments':133,'quiz_items_covered':361,
    'original_proposals':24,'answered_followups':48,'shortlisted':15,
    'all_chapter_qids_resolve':True,'all_chapter_snapshots_http_200':True,
    'pdf_margin_geometry':'passed','book_hash_unchanged':True,
    'book_sha256':d['book']['sha256'],'report_sha256':m['sha256'],
    'limits':'Static reading/API audit. No examples, media, models, deployments or assessments executed. Visual QA recorded separately.'
}
(ROOT/'validation.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
