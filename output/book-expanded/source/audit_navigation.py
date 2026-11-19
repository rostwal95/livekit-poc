"""Validate PDF navigation, the practice index and the HTML reading guide."""
from pathlib import Path
import json
import re
from pypdf import PdfReader
from lxml import html

BASE=Path(__file__).resolve().parent
m=json.loads((BASE/'manifest.json').read_text())
r=PdfReader(m['pdf'])
page_refs={page.indirect_reference.idnum:n+1 for n,page in enumerate(r.pages)}
errors=[]
internal=external=0
for n,page in enumerate(r.pages,1):
    for obj in page.get('/Annots',[]):
        annotation=obj.get_object()
        destination=annotation.get('/Dest')
        action=annotation.get('/A')
        if action:
            if action.get('/S')=='/GoTo':destination=action.get('/D')
            if action.get('/S')=='/URI':
                external+=1
                if not str(action.get('/URI','')).startswith('https://'):
                    errors.append(('external scheme',n,str(action.get('/URI'))))
        if destination:
            internal+=1
            if isinstance(destination,list):
                first=destination[0]
                if not hasattr(first,'idnum') or first.idnum not in page_refs:
                    errors.append(('internal destination',n,str(first)))
            elif str(destination) not in r.named_destinations:
                errors.append(('named destination',n,str(destination)))
pages=json.loads((BASE/'pages.json').read_text())
content=json.loads((BASE/'book-content.json').read_text())
allq=[q for chapter in content['chapters'] for q in chapter['questions']]
index='\n'.join(r.pages[p['page']-1].extract_text() or '' for p in pages if p['kind']=='practice')
for q in allq:
    if 'Q-'+q['id'] not in index:errors.append(('missing index entry',q['id']))
sources='\n'.join(r.pages[p['page']-1].extract_text() or '' for p in pages if p.get('kicker')=='SOURCE LIBRARY')
normalized=lambda text:re.sub(r'\s+','',text)
for _,url in content['sources'].values():
    if normalized(url) not in normalized(sources):errors.append(('missing printed source',url))
guide=html.fromstring((BASE.parent/'Start-Here-Expanded-Book.html').read_bytes())
for link in guide.xpath('//a/@href'):
    if '#page=' in link and not 1<=int(link.split('#page=')[1])<=len(r.pages):
        errors.append(('HTML page destination',link))
if len(guide.xpath('//article[@class="question"]'))!=15:errors.append(('HTML preview count',))
(BASE/'change-guide-ui.js').write_text('\n'.join(guide.xpath('//script/text()')))
report={'pdf_sha256':m['sha256'],'internal_pdf_links_checked':internal,'external_pdf_links_checked':external,'question_index_entries_verified':len(allq),'source_urls_verified':len(content['sources']),'html_question_previews':15,'all_link_destinations_valid':not errors,'errors':errors}
(BASE/'navigation-audit.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
if errors:raise SystemExit(1)
