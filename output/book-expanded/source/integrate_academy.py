"""Merge reviewed additions into a separate source bundle; preserve the prior edition."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import shutil

BASE=Path(__file__).resolve().parent
REPO=BASE.parents[2]
INPUT=REPO/'output/academy-review/integration'

def read(path):return json.loads(path.read_text())
def write(name,data):(BASE/name).write_text(json.dumps(data,indent=2)+'\n')

book=read(BASE/'baseline-content.json')
baseline_manifest=read(BASE/'baseline-manifest.json')
baseline_hash=hashlib.sha256(Path(baseline_manifest['pdf']).read_bytes()).hexdigest()
assert baseline_hash==baseline_manifest['sha256']
new=read(INPUT/'new-questions.json')
expanded=read(INPUT/'existing-expansions.json')
practice=read(INPUT/'practice-additions.json')

# Retain established source IDs; deduplicate new URLs against those IDs.
source_map={}
by_url={v[1]:k for k,v in book['sources'].items()}
for bundle in [new,expanded]:
    for key,value in bundle['sources'].items():
        title,url=value
        assert url.startswith('https://')
        if url in by_url:source_map[key]=by_url[url]
        else:
            assert key not in book['sources'],key
            book['sources'][key]=value
            source_map[key]=key
            by_url[url]=key

def remap(value):
    if isinstance(value,list):return [remap(x) for x in value]
    if isinstance(value,dict):
        out={k:remap(v) for k,v in value.items()}
        if 'sources' in out and isinstance(out['sources'],list):
            out['sources']=list(dict.fromkeys(source_map.get(s,s) for s in out['sources']))
        return out
    if isinstance(value,str):
        return re.sub(r'\[([A-Z][A-Za-z0-9]*(?:,\s*[A-Z][A-Za-z0-9]*)*)\]',lambda m:'['+', '.join(source_map.get(s.strip(),s.strip()) for s in m.group(1).split(','))+']',value)
    return value

all_original={q['id']:q for c in book['chapters'] for q in c['questions']}
updates={item['id']:remap(item['replacement']) for item in expanded['updates']}
assert len(updates)==10
assert set(updates)<=set(all_original)
for ch in book['chapters']:
    ch['questions']=[deepcopy(updates.get(q['id'],q)) for q in ch['questions']]

new_meta=[]
assert len(new['questions'])==15
for item in new['questions']:
    q=remap(deepcopy(item))
    integration=q.pop('integration')
    assert q['id'] not in all_original
    assert len(q['followups'])==2
    book['chapters'][integration['chapter_index']]['questions'].append(q)
    new_meta.append({'id':q['id'],'title':q['title'],**integration})

book['chapters'][9]['subtitle']='Rooms tasks turns frontend data retrieval and phone routing'
book['chapters'][9]['intro'][1]='The public docs may evolve. Explain the architectural role before quoting an API signature. The new questions separate SDK conversational tasks, frontend data APIs, voice retrieval and SIP dispatch from the POC\'s durable input and business authority. These are preparation scenarios; their presence here does not establish that the POC implements RAG, SIP service or graph recovery.'
book['chapters'][14]['intro'][1]='Use the project as evidence, then reason about the changed constraint. Name a concrete API behavior and a failure schedule. For model behavior, separate a calibrated quality judgment from a deterministic tool invariant, actual media evidence and a durable business receipt.'

assert len(practice['drills'])==4 and len(practice['field_guides'])==3
practice=remap(practice)
shutil.copy2(INPUT/'academy_figures.py',BASE/'academy_figures.py')
write('audited-content.json',book)
write('practice-additions.json',practice)

cue=read(BASE/'learning-cues.json')
runtime=cue['chapters'][book['chapters'][9]['title']]
runtime['three_anchors']=['LK-09','LK-15','LK-18']
runtime['finish_line']='Choose the SDK abstraction, data API and turn-scoped extension point; trace one lost reply or interruption without inventing business authority.'
write('learning-cues.json',cue)

old_ledger=read(BASE/'baseline-audit-ledger.json')
old_rows={r['id']:r for r in old_ledger['entries']}
new_ids={r['id'] for r in new_meta}
reasons={u['id']:u['reason'] for u in expanded['updates']}
entries=[]
for ch in book['chapters']:
    for q in ch['questions']:
        qid=q['id']
        status='new source-reviewed question' if qid in new_ids else 'expanded from audited baseline' if qid in updates else 'retained from audited baseline'
        entries.append({'id':qid,'title':q['title'],'status':status,'reason':reasons.get(qid,'Original interview scenario derived from the curriculum gap audit.' if qid in new_ids else 'Prior reviewed content preserved.'),'followups_reviewed':len(q['followups']),'sources':q.get('sources',[]),'evidence':q.get('evidence',[]),'baseline_review':old_rows.get(qid),'execution':'No new application, provider, media or designed-exercise execution.'})
write('audit-ledger.json',{'scope':'Prior complete baseline review retained;15 new questions and10 expanded existing questions receive the current content review. This is document/source work, not product qualification.','questions_accounted_for':len(entries),'new_questions_reviewed':15,'existing_questions_expanded':10,'entries':entries})
write('integration-manifest.json',{'date':'19 November 2026','baseline_pdf':baseline_manifest['pdf'],'baseline_pdf_sha256':baseline_hash,'baseline_questions':220,'baseline_followups':501,'new_question_ids':[q['id'] for q in new_meta],'new_question_mapping':new_meta,'expanded_existing_ids':list(updates),'update_reasons':reasons,'new_figures':['F20','F21','F22','F23','F24'],'new_failure_exercises':4,'comparison_guides':3,'source_key_map':source_map,'application_commit':baseline_manifest['commit'],'scope':'Original book IDs, code-review text, literal excerpts and original figure IDs preserved. Added framework/telephony/RAG examples and exercises do not assert new POC implementation.'})
assert hashlib.sha256(Path(baseline_manifest['pdf']).read_bytes()).hexdigest()==baseline_hash
print('Integrated15 questions,10 answer expansions,5 figures,4 exercises and3 comparison guides.')
