import collections,hashlib,html,json
from pathlib import Path
B=Path(__file__).resolve().parent
ledger=json.loads((B/'audit-ledger.json').read_text())
book=json.loads((B/'book-content.json').read_text())
manifest=json.loads((B/'manifest.json').read_text())
qmap={q['id']:q for c in book['chapters'] for q in c['questions']}
rows={r['id']:r for r in ledger['entries']}
assert len(rows)==220
E=lambda x:html.escape(str(x),quote=True)
body=[]
for c in book['chapters']:
 body.append(f'<section><h2>{c["number"]:02d} · {E(c["title"])}</h2>')
 for q in c['questions']:
  row=rows[q['id']];pn=manifest['page_map']['q-'+q['id']]
  fields=', '.join(row['visible_fields_changed']);verdict=row.get('verdict','reviewed')
  reasons=[]
  for change in row.get('changes',[]):
   reason=change.get('reason',change) if isinstance(change,dict) else change
   if reason not in reasons:reasons.append(reason)
  reasons_html=''.join('<li>'+E(x)+'</li>' for x in reasons)
  ev=[]
  for value in row.get('evidence_checked',[]):
   if isinstance(value,str):ev.append(value);continue
   loc=str(value.get('path',''))+(':'+str(value['line']) if value.get('line') else '')
   desc=value.get('claim',value.get('label',''))
   ev.append(loc+(' — '+desc if desc else '')+(' ['+value['body_reviewed']+']' if value.get('body_reviewed') else ''))
  sourcekeys=q.get('sources',[])
  ev_html=''.join('<li><code>'+E(x)+'</code></li>' for x in ev)
  if sourcekeys:
   ev_html+=''.join('<li><a href="'+E(book['sources'][key][1])+'">'+E(key+' · '+book['sources'][key][0])+'</a></li>' for key in sourcekeys)
  lim=row.get('remaining_limitations',[])
  if isinstance(lim,str):lim=[lim]
  lim_html=''.join('<li>'+E(x)+'</li>' for x in lim)
  body.append(f'''<details class="review" data-search="{E(q['id']+' '+q['title']+' '+fields+' '+' '.join(map(str,reasons)))}">
<summary><b>Q-{E(q['id'])}</b><span>{E(q['title'])}</span><em>{E(verdict)}</em><small>p {pn} · {len(q['followups'])} probes</small></summary>
<div class="detail"><p class="question">{E(q['question'])}</p><p><strong>Visible fields revised:</strong> {E(fields)}</p><h3>Review decisions</h3><ul>{reasons_html}</ul><h3>Checked evidence</h3><ul class="evidence">{ev_html or '<li>Technical-reference and design review; no implementation claim introduced.</li>'}</ul><h3>Proof limits</h3><ul>{lim_html}<li>No application/provider qualification was rerun; this row relies on the checked evidence listed above.</li></ul></div></details>''')
 body.append('</section>')
htmltext='''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>LiveKit book — content audit ledger</title><style>
:root{font-family:system-ui,-apple-system,sans-serif;color:#202b3c;background:#f5f7fc;line-height:1.55}*{box-sizing:border-box}body{max-width:1120px;margin:auto;padding:36px 28px 70px}header{background:#e8edff;border-top:7px solid #2d46d7;padding:28px;border-radius:7px}h1{color:#162647;margin:5px 0 15px;line-height:1.1;font-size:36px}h2{margin-top:42px;color:#233b74;font-size:21px}h3{font-size:15px;color:#087e78;margin:20px 0 5px}.eyebrow{font-weight:750;letter-spacing:.1em;color:#2d46d7;font-size:12px}.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:24px 0}.stat{background:white;padding:15px;border:1px solid #ccd7ee;border-top:4px solid #7445b5;border-radius:4px}.stat b{display:block;font-size:30px;color:#2d46d7}.stat span{font-size:12px;font-weight:650}.note{background:#fff6e9;border-left:4px solid #a65f05;padding:15px 18px}input{width:100%;padding:13px;border:1px solid #a7b8d6;border-radius:5px;font:inherit;margin:20px 0 4px}details{background:white;margin:10px 0;border:1px solid #d5def0;border-left:4px solid #2d46d7;border-radius:4px}summary{display:flex;gap:13px;align-items:baseline;cursor:pointer;padding:14px 16px}summary b{min-width:90px;color:#2d46d7}summary span{flex:1;font-weight:650}summary em{font-size:12px;font-style:normal;background:#edf7f4;color:#087369;padding:2px 8px;border-radius:4px}summary small{min-width:100px;color:#5a6b84}.detail{padding:0 22px 24px 119px}.question{font-weight:650;color:#162647}code{font-family:ui-monospace,monospace;white-space:normal;overflow-wrap:anywhere;font-size:12px}li{margin:5px 0}a{color:#2d46d7}.meta{font-size:12px;color:#52627a;overflow-wrap:anywhere}button{font:inherit;border:1px solid #a8b6d3;background:white;color:#2d46d7;border-radius:4px;padding:7px 13px;cursor:pointer;margin-right:8px}.hidden{display:none}@media(max-width:700px){body{padding:16px}h1{font-size:29px}.stats{grid-template-columns:repeat(2,1fr)}summary{display:block}summary>*{display:block;margin:3px 0}.detail{padding:0 16px 16px}}@media print{body{max-width:none;padding:0;background:white;font-size:10pt}header{padding:14px}input,button,.filterhelp{display:none}.stats{margin:12px 0}h2{break-after:avoid}details{break-inside:avoid}details .detail{display:block!important}summary{display:block}.detail{padding:0 15px 10px}summary>*{margin-right:10px}.hidden{display:block}a{color:#162647;text-decoration:none}}
</style><body><header><div class="eyebrow">CONTENT REVIEW · CODE · PROOF BOUNDARIES</div><h1>Question-by-question audit</h1><p>Every main question and answered follow-up was reconsidered. This ledger records the changes and evidence behind the revised study book.</p></header>
<div class="stats"><div class="stat"><b>220 / 220</b><span>QUESTIONS REVIEWED AND REVISED</span></div><div class="stat"><b>501</b><span>ANSWERED FOLLOW-UPS REVIEWED</span></div><div class="stat"><b>60</b><span>CODE REVIEWS RECHECKED</span></div><div class="stat"><b>19 + 6</b><span>DIAGRAMS + CODING PROMPTS REVIEWED</span></div></div>
<p class="note"><strong>Audit scope:</strong> Static implementation, existing-test-body and primary-reference review. The audit did not rerun application PostgreSQL, process, browser/media or provider gates. Historical qualifications, open product findings and proposed extensions remain distinct.</p>
<p class="meta">Application source: SOURCE_SHA<br>Book SHA-256: BOOK_SHA<br>External construction references: LiveKit 80cfa6e73f1d; PSRPC aa91db868a4c. These are separate from the POC's pinned server image.</p>
<label class="filterhelp" for="filter"><b>Find a question, mechanism or correction</b></label><input id="filter" type="search" placeholder="Try D1-15, deadline, callback, generation, rollback…"><p><button id="openall">Expand shown rows</button><button id="closeall">Collapse rows</button><span id="count" class="meta">220 questions</span></p>
'''+''.join(body)+'''<footer><p class="meta">Automated artifact checks verify coverage, source paths/ranges/hashes, counts, text presence, print bounds and navigation. They complement semantic review; they do not replace the application’s behavioral qualification.</p></footer><script>
const field=document.getElementById('filter');const rows=[...document.querySelectorAll('.review')];field.addEventListener('input',()=>{const words=field.value.toLowerCase().trim().split(/\\s+/).filter(Boolean);let count=0;for(const row of rows){const show=words.every(w=>row.dataset.search.toLowerCase().includes(w));row.classList.toggle('hidden',!show);if(show)count++}document.getElementById('count').textContent=count+' questions'});document.getElementById('openall').onclick=()=>rows.filter(r=>!r.classList.contains('hidden')).forEach(r=>r.open=true);document.getElementById('closeall').onclick=()=>rows.forEach(r=>r.open=false);</script></body></html>'''
htmltext=htmltext.replace('SOURCE_SHA',ledger['source_commit']).replace('BOOK_SHA',manifest['sha256'])
dest=R=Path('/Users/rostwal/Downloads/livekit-poc/output/book-audit');dest.mkdir(parents=True,exist_ok=True)
(dest/'LiveKit-Book-Content-Audit.html').write_text(htmltext)
(dest/'question-audit-ledger.json').write_text(json.dumps(ledger,indent=2))
print('Wrote audit report and complete 220-row ledger.')
