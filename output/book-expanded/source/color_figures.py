"""Color vector learning diagrams for the duplex interview book.

All event sequences are conceptual explanations of cited contracts, not new
measurements. No color is required to interpret a node, edge or status.
"""
import html, math
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph

BLACK=colors.HexColor('#23343F'); GRAY=colors.HexColor('#5D6D78')
EDGE=colors.HexColor('#8397A5'); LIGHT=colors.HexColor('#F1F6FA')

# Saturated edges carry the visual rhythm; pale surfaces keep the diagrams
# useful on paper. Labels, dashes and arrow direction retain all meaning in
# grayscale. P1/P2/P3 keep their authority/channel/specialist color families.
PALETTE={
 'blue':dict(fill=colors.HexColor('#EAF3FF'),edge=colors.HexColor('#4078C7'),ink=colors.HexColor('#204E88')),
 'teal':dict(fill=colors.HexColor('#E8F7F3'),edge=colors.HexColor('#2D947E'),ink=colors.HexColor('#186653')),
 'violet':dict(fill=colors.HexColor('#F2EDFC'),edge=colors.HexColor('#8B65C0'),ink=colors.HexColor('#58358A')),
 'amber':dict(fill=colors.HexColor('#FFF5DF'),edge=colors.HexColor('#BE8923'),ink=colors.HexColor('#81580E')),
 'rose':dict(fill=colors.HexColor('#FFF0EC'),edge=colors.HexColor('#C86D62'),ink=colors.HexColor('#9C4438')),
 'slate':dict(fill=colors.HexColor('#F0F4F7'),edge=colors.HexColor('#8095A3'),ink=colors.HexColor('#3F596A')),
}
_FIGURE_KIND='authority'
_BOX_INDEX=0
_FIGURE_ACCENTS={
 'authority':'violet','commit':'violet','effect':'amber','lease':'violet',
 'intake':'blue','context':'blue','outbound':'blue','delegation':'violet',
 'feed':'blue','webrtc':'teal','pipeline':'violet','lifetime':'amber',
 'nats':'blue','planes':'teal','singleflight':'violet','triage':'blue',
 'feedcommit':'violet','auth':'blue','facts':'violet',
}
_NODE_ROLES={
 'authority':['teal','slate','blue','violet','amber','rose'],
 'effect':['slate','teal','blue','rose','teal','amber','violet'],
 'delegation':['blue','violet','teal','amber','teal'],
 'webrtc':['blue','teal','amber','teal','violet','rose'],
 'pipeline':['teal','blue','violet','amber','teal'],
 'planes':['teal','blue','slate','amber','violet'],
 'facts':['blue','violet','teal','amber','violet'],
}
_LANE_ROLES={
 'Revision B':'blue','P1 guard':'violet','Intent A':'amber',
 'Worker A':'blue','Database lock':'violet','Clock / grant':'amber',
 'Caller / RTC':'teal','Native adapter':'amber','P2 authority':'blue','SDK output':'violet',
 'Current grant':'violet','P2 read':'blue','Public P1':'violet',
 'Request / callback':'teal','P2 admission':'blue','Carrier':'amber',
 'Publisher':'teal','JetStream':'blue','Consumer':'amber','P1 / supplier':'violet',
 'Reader A':'teal','Published scan':'violet','Reader B':'blue',
 'Writer A':'teal','Shared guard':'violet','Writer B':'blue',
 'Raw request':'teal','Local adapter':'blue','PostgreSQL':'violet',
}

def _node_role(title,body,index):
 if title in _LANE_ROLES:return _LANE_ROLES[title]
 if _FIGURE_KIND=='feed':
  if body in ('terminal','unknown','pending'):
   return {'terminal':'teal','unknown':'amber','pending':'blue'}[body]
  return {'Contiguous terminal watermark = 1':'amber','Discovery scan position is separate':'blue'}.get(title,'violet')
 if _FIGURE_KIND=='triage':
  return 'violet' if index==0 else ('amber' if index%2 else 'blue')
 if _FIGURE_KIND=='feedcommit':return 'rose' if title.startswith('Allocate ') else 'violet'
 if _FIGURE_KIND=='lifetime':return 'rose'
 roles=_NODE_ROLES.get(_FIGURE_KIND)
 return roles[index%len(roles)] if roles else _FIGURE_ACCENTS.get(_FIGURE_KIND,'blue')

def _message_role(text,fallback):
 if 'reject' in text or text.startswith('expired:'):return 'rose'
 if any(word in text for word in ('unknown','uncertain','unresolved')):return 'amber'
 return fallback

FIGURES={
 'authority':dict(id='F01',title='Who owns each fact',kind='authority',refs=['SYS-02','D4-04'],caption='Application composition borrows public ports. Dashed boundaries separate ownership. P3 uses public P1 grants/results; none of the three libraries gains permission to copy sibling storage.'),
 'commit':dict(id='F02',title='The two orders of revision and intent',kind='commit',refs=['P1-07','P3-16'],caption='Conceptual competing schedules. The guarded transaction defines the winner; a later observation or wall-clock timestamp cannot rewrite that commitment.'),
 'effect':dict(id='F03',title='A possible external effect stays possible',kind='effect',refs=['P1-11','D1-12'],caption='Conceptual knowledge states, not a literal enumeration of every storage value. Cancellation or deadline after a prior reservation cannot establish that a paused call never ran.'),
 'lease':dict(id='F04',title='A lease check after the lock wait',kind='lease',refs=['P1-14','D1-01'],caption='Illustrative ordering without measured durations. A request can start before expiry and acquire the lock after expiry; eligibility must use fresh authoritative time.'),
 'intake':dict(id='F05',title='Durable input before dispatched generation',kind='intake',refs=['P2-12','P2-13','D4-11'],caption='The opt-in native adapter admits the original input before dispatched generation. This does not guarantee exactly one generation or playback. STT stream overlap is a resource lifetime, separate from intake identity.'),
 'context':dict(id='F06',title='Rehydrate without inventing an atomic snapshot',kind='context',refs=['P2-17','P2-25','D4-12'],caption='P2 and public P1 observations occur at different times. The final permission check restricts disclosure but does not make the earlier reads a cross-store atomic transaction.'),
 'outbound':dict(id='F07',title='Reserve permission before carrier I O',kind='outbound',refs=['P2-20','P2-23'],caption='The reservation transaction shares admission with callback and current-permission checks. A later callback cannot fence an external call that was already admitted.'),
 'delegation':dict(id='F08',title='Acceptance issuance result and action',kind='delegation',refs=['P3-06','P3-10','P3-15'],caption='These gates answer different questions. The original v1 action path and the explicit newer policy delivery facades have separate support; the diagram grants no automatic version compatibility.'),
 'feed':dict(id='F09',title='Scan progress is not the terminal watermark',kind='feed',refs=['P3-18','D3-10'],caption='Illustrative eight-event window. Later useful terminal observations can progress while an earlier unknown prevents a contiguous terminal watermark from advancing.'),
 'webrtc':dict(id='F10',title='Signaling and media use different paths',kind='webrtc',refs=['RTC-01','RTC-03','RTC-04'],caption='Protocol overview. A control connection is not proof of a working media path. TURN relays a path; it does not become application consent or a durable inbox.'),
 'pipeline':dict(id='F11',title='Where a voice answer can pause',kind='pipeline',refs=['LK-03','FAIL-02'],caption='A conceptual pipeline, not measured latency. Streaming stages may overlap; do not sum arbitrary component durations and call that observed end-to-end delay.'),
 'lifetime':dict(id='F12',title='One timeout and three remaining lifetimes',kind='lifetime',refs=['ROLE-01','D4-05','D4-09'],caption='Composite example for retained loopback/media owners, not every slot in the repo. Ordinal stages are not measurements. Each slot releases when its own protected actual resource settles; some require writer closure.'),
 'nats':dict(id='F13',title='Three acknowledgments with different meanings',kind='nats',refs=['NATS-05','NATS-06','BUS-05'],caption='Hypothetical messaging integration. A stream storage acknowledgment, consumer progress acknowledgment and retained application receipt are distinct facts.'),
 'planes':dict(id='F14',title='LiveKit transport bus and application authority',kind='planes',refs=['BUS-01','BUS-02'],caption='Public evidence supports Redis/local server wiring and a NATS-capable PSRPC library. It does not establish every LiveKit Cloud internal deployment or a NATS service in this POC.'),
 'singleflight':dict(id='F15',title='Shared scan and independent observers',kind='singleflight',refs=['D4-01','D4-02'],caption='One published scan can serve two observers. Canceling the first does not cancel the second; losing the last observer abandons interest while actual ownership remains until settled.'),
 'triage':dict(id='F16',title='Start with the missing observation',kind='triage',refs=['FAIL-01','FAIL-02','FAIL-03'],caption='A diagnostic decision guide. Follow the evidence for the failing layer instead of treating every silence, delay or missing receipt as one retryable error.'),
 'feedcommit':dict(id='F17',title='Feed sequence follows visible commit order',kind='feedcommit',refs=['D1-14','D3-13','P1-25'],caption='Same source and scope under the shared work admission guard. The counterexample is an unimplemented alternative showing why an earlier sequence allocation alone is insufficient.'),
 'auth':dict(id='F18',title='Authenticate twice for two different questions',kind='auth',refs=['D2-01','D2-09'],caption='The cheap pass validates signed bytes before SQL. It uses signed time and cannot establish current freshness; the protected pass uses fresh database time after the lock.'),
 'facts':dict(id='F19',title='Valid bytes can still be unsupported facts',kind='facts',refs=['D3-01','D3-03','P3-11'],caption='Independent gates, not one success flag. In fixed-policy verification, unsupported factual output remains invalid even when it is late; expiry must not mask the factual error.')
}

def para(cv,text,x,y,w,size=9.4,bold=False,color=BLACK):
 st=ParagraphStyle('fig',fontName='BodyB' if bold else 'Body',fontSize=size,leading=size*1.32,textColor=color,splitLongWords=True)
 p=Paragraph(html.escape(text),st);_,h=p.wrap(w,1000);p.drawOn(cv,x,y-h);return h

def box(cv,x,y,w,h,title,body='',dash=False,role=None):
 global _BOX_INDEX
 role=role or _node_role(title,body,_BOX_INDEX);_BOX_INDEX+=1
 theme=PALETTE[role]
 cv.saveState()
 cv.setFillColor(theme['fill']);cv.setStrokeColor(theme['edge']);cv.setLineWidth(1)
 cv.setDash(4,3) if dash else cv.setDash()
 cv.roundRect(x,y,w,h,4,stroke=1,fill=1);cv.setDash()
 # A narrow rail makes color visible without a heavy full-page background.
 cv.setFillColor(theme['edge']);cv.roundRect(x+3,y+7,2.2,max(h-14,1),1.1,stroke=0,fill=1)
 th=para(cv,title,x+10,y+h-10,w-20,10.4,True,theme['ink'])
 if body and _FIGURE_KIND=='feed' and body in ('terminal','unknown','pending'):
  # The original status word remains the cue; the pill only reinforces it.
  chip_w=min(w-12,{'terminal':49,'unknown':50,'pending':47}[body])
  cv.setFillColor(colors.white);cv.setStrokeColor(theme['edge']);cv.setLineWidth(.65)
  cv.roundRect(x+6,y+h-54,chip_w,18,6,stroke=1,fill=1)
  para(cv,body,x+10,y+h-38,chip_w-8,8.2,True,theme['ink'])
 elif body:para(cv,body,x+10,y+h-17-th,w-20,9.1)
 cv.restoreState()

def arrow(cv,x1,y1,x2,y2,label='',dashed=False,role=None):
 theme=PALETTE[role or _FIGURE_ACCENTS.get(_FIGURE_KIND,'blue')]
 cv.saveState()
 cv.setStrokeColor(theme['edge']);cv.setFillColor(theme['edge']);cv.setLineWidth(1.15)
 if dashed:cv.setDash(4,3)
 cv.line(x1,y1,x2,y2);cv.setDash()
 a=math.atan2(y2-y1,x2-x1);s=5
 p=cv.beginPath();p.moveTo(x2,y2);p.lineTo(x2-s*math.cos(a-.45),y2-s*math.sin(a-.45));p.lineTo(x2-s*math.cos(a+.45),y2-s*math.sin(a+.45));p.close();cv.drawPath(p,stroke=0,fill=1)
 if label:para(cv,label,min(x1,x2)+5,(y1+y2)/2+18,max(abs(x2-x1)-10,50),8.6,color=theme['ink'])
 cv.restoreState()

def sequence(cv,x,top,w,lanes,steps,dy=44):
 n=len(lanes);lx=[x+(i+.5)*w/n for i in range(n)]
 floor=top-69-len(steps)*dy
 for i,l in enumerate(lanes):
  theme=PALETTE[_LANE_ROLES.get(l,'blue')]
  box(cv,x+i*w/n+2,top-40,w/n-4,40,l,role=_LANE_ROLES.get(l,'blue'))
  cv.setStrokeColor(theme['edge']);cv.setLineWidth(.55);cv.setDash(2,3);cv.line(lx[i],top-40,lx[i],floor);cv.setDash()
 for no,(a,b,text) in enumerate(steps,1):
  yy=top-78-(no-1)*dy
  role=_message_role(text,_LANE_ROLES.get(lanes[b],'blue'));theme=PALETTE[role]
  if a==b:
   cv.setFillColor(theme['fill']);cv.roundRect(lx[a]-w/n*.43,yy-10,w/n*.86,31,4,fill=1,stroke=0)
   para(cv,f'{no}. '+text,lx[a]-w/n*.4,yy+19,w/n*.8,8.8,True,theme['ink'])
  else:
   left=min(lx[a],lx[b]);width=abs(lx[b]-lx[a]);
   cv.setFillColor(colors.white);cv.roundRect(left+2,yy+2,width-4,30,3,fill=1,stroke=0)
   para(cv,f'{no}. '+text,left+5,yy+28,width-10,8.8)
   arrow(cv,lx[a],yy,lx[b],yy,dashed=text.startswith('return') or text.startswith('lookup'),role=role)
 return floor

def flow(cv,x,top,w,items):
 h=66;gap=24
 for i,(a,b) in enumerate(items):
  yy=top-h-i*(h+gap);box(cv,x,yy,w,h,a,b)
  if i<len(items)-1:arrow(cv,x+w/2,yy-1,x+w/2,yy-gap+2)

def draw(cv,key,x,w,top=700):
 global _FIGURE_KIND,_BOX_INDEX
 k=FIGURES[key]['kind'];low=top-510
 _FIGURE_KIND=k;_BOX_INDEX=0
 if k=='authority':
  box(cv,x,top-72,w,72,'Conversation / Browser / LiveKit','Transport, turn handling, session and playback observations')
  box(cv,x,top-185,w,66,'Application composition','Trusted bindings and bounded owners use the three public interfaces')
  arrow(cv,x+w/2,top-73,x+w/2,top-118)
  bw=(w-24)/3
  for i,(a,b) in enumerate([('P2 - Channel','Verified input, history, permission, outbound operation and callbacks'),('P1 - Authority','Case revision, exact intent, acceptance, issuance, effects and result truth'),('P3 - Delegation','Bounded specialist coordination, evidence validation and derived applicability')]):
   xx=x+i*(bw+12);box(cv,xx,top-400,bw,150,a,b,True);arrow(cv,x+w/2,top-186,xx+bw/2,top-249)
  box(cv,x,top-505,w,70,'No competing durable execution owner','P1 owns accepted work. Channels, models, rooms and specialist status cannot create a replacement execution permission.')
  low=top-515
 elif k=='commit':
  para(cv,'SCHEDULE A  /  REVISION WINS',x,top,w,10.2,True)
  sequence(cv,x,top-22,w,['Revision B','P1 guard','Intent A'],[(0,1,'revise from expected A'),(1,1,'commit revision B'),(2,1,'confirm stale A'),(1,2,'reject stale revision')],42)
  para(cv,'SCHEDULE B  /  INTENT WINS',x,top-300,w,10.2,True)
  sequence(cv,x,top-322,w,['Intent A','P1 guard','Revision B'],[(0,1,'exact confirmation A'),(1,1,'commit intent A'),(2,1,'revise after intent'),(1,2,'reject intent_committed')],42)
  low=top-566
 elif k=='effect':
  bw=(w-30)/2; ys=[top-75,top-195,top-315]
  box(cv,x,ys[0],bw,75,'No possible call','Zero dispatch reservations')
  box(cv,x+bw+30,ys[0],bw,75,'Definite prevention','Cancel or deadline may prevent dispatch')
  arrow(cv,x+bw,ys[0]+38,x+bw+30,ys[0]+38)
  box(cv,x,ys[1],bw,75,'Reservation committed','External call may start after SQL releases')
  arrow(cv,x+bw/2,ys[0],x+bw/2,ys[1]+75)
  box(cv,x+bw+30,ys[1],bw,75,'Cancel / deadline later','Does not prove the earlier call stopped')
  arrow(cv,x+bw,ys[1]+38,x+bw+30,ys[1]+38)
  box(cv,x,ys[2],bw,75,'Known supplier result','Preserve success or known rejection')
  box(cv,x+bw+30,ys[2],bw,75,'Unknown supplier result','Retain uncertainty and original identity',True)
  arrow(cv,x+bw/2,ys[1],x+bw/2,ys[2]+75)
  arrow(cv,x+bw+30+bw/2,ys[1],x+bw+30+bw/2,ys[2]+75)
  box(cv,x,top-440,w,80,'Reconcile through the actual operation contract','A database lease cannot independently fence a supplier. Do not create a replacement logical operation to hide an unknown outcome.')
  low=top-450
 elif k=='lease':
  sequence(cv,x,top,w,['Worker A','Database lock','Clock / grant'],[(0,1,'request begins before expiry'),(1,1,'wait for conflicting lock'),(2,2,'grant expires during wait'),(1,0,'lock finally acquired'),(0,2,'read fresh database time'),(2,0,'expired: reject protected write'),(0,0,'retain possible external truth')],57)
  low=top-474
 elif k=='intake':
  sequence(cv,x,top,w,['Caller / RTC','Native adapter','P2 authority','SDK output'],[(0,1,'audio or text arrives'),(1,1,'retain final event before await'),(1,2,'accept original input'),(2,1,'durable receipt / operation'),(1,3,'generate after acceptance'),(3,0,'publish returned audio'),(0,1,'playback observation only')],53)
  low=top-452
 elif k=='context':
  sequence(cv,x,top,w,['Current grant','P2 read','Public P1'],[(0,1,'validate and capture P2 state'),(1,1,'release P2 SQL'),(1,2,'read public current case'),(2,1,'return separate observation'),(1,0,'recheck current permission'),(0,0,'admit scoped disclosure')],58)
  box(cv,x,top-475,w,66,'No cross-store atomic snapshot','Equal revision does not prove supplier freshness. A final response fence cannot retract bytes already sent.')
  low=top-485
 elif k=='outbound':
  sequence(cv,x,top,w,['Request / callback','P2 admission','Carrier'],[(0,1,'new-send request'),(1,1,'lock shared admission'),(1,1,'check permission and prior facts'),(1,1,'reserve immutable possible attempt'),(1,1,'commit and release SQL'),(1,2,'external send outside SQL'),(2,1,'known result or uncertain ACK'),(0,1,'separate authenticated callback fact')],51)
  low=top-482
 elif k=='delegation':
  flow(cv,x,top,w,[('1  Accepted original work','One scoped identity and immutable request'),('2  New P1 issuance','created=true and exact running observation permit invocation'),('3  Validated result retained by P1','P3 validates structure, correlation and facts; P1 records disposition'),('4  Separate next-operation guards','As-of applicability, delivery eligibility and exact action consent are distinct'),('5  Bound outcome and receipt','No retargeting; known facts survive later cancellation')]);low=top-450
 elif k=='feed':
  para(cv,'RETAINED EVENTS AND PROCESSING KNOWLEDGE',x,top,w,10.5,True)
  states=['terminal','unknown','terminal','terminal','unknown','terminal','pending','terminal']
  cw=w/8
  for i,state in enumerate(states):
   box(cv,x+i*cw+1,top-111,cw-2,80,str(i+1),state,dash=state!='terminal')
  arrow(cv,x+8,top-148,x+w-8,top-148,'Scan can examine later useful events')
  box(cv,x,top-248,w,68,'Contiguous terminal watermark = 1','Event 2 remains unknown, so the watermark cannot jump to event 8.')
  box(cv,x,top-349,w,68,'Discovery scan position is separate','At most eight rows total including a bounded wrap. Examining a row is not acknowledging it.')
  box(cv,x,top-450,w,68,'Retention protects unresolved identity','A hidden display row or expired badge cannot free protected processing capacity.')
  low=top-460
 elif k=='webrtc':
  bw=(w-30)/2
  box(cv,x,top-80,bw,80,'Control plane','Authenticated join and signaling; SDP and candidates')
  box(cv,x+bw+30,top-80,bw,80,'Media plane','ICE selected path; DTLS keys; SRTP media')
  arrow(cv,x+bw,top-40,x+bw+30,top-40)
  box(cv,x,top-210,w,82,'Candidate discovery and connectivity','Host / mapped / relay candidates are possibilities. Connectivity checks select a working pair; a TURN relay can supply a reachable path.')
  arrow(cv,x+w/2,top-82,x+w/2,top-128)
  box(cv,x,top-340,bw,82,'Realtime media','Timestamped packets, loss, jitter buffer, decode and playback')
  box(cv,x+bw+30,top-340,bw,82,'Application data','Data channel transport does not create durable message history')
  arrow(cv,x+w/2,top-212,x+bw/2,top-258)
  arrow(cv,x+w/2,top-212,x+bw+30+bw/2,top-258)
  box(cv,x,top-465,w,80,'Application facts stay separate','A track, a transcript or a browser level meter does not establish accepted work, exact quote confirmation or human hearing.')
  low=top-475
 elif k=='pipeline':
  flow(cv,x,top,w,[('Capture and recognition','Actual input track and original final transcript'),('Turn boundary and durable admission','P2 opt-in path: accepted input before dispatched generation'),('LLM and specialist work','Streaming response; independent background business progress'),('TTS publication and transport','First generated audio differs from first received audio'),('Decode and browser playout','Observed output is not human understanding or consent')]);low=top-450
 elif k=='lifetime':
  names=['Observer','Actual call','Writer / close','Capacity slot'];left=x+105;ww=w-110;cell=ww/4
  phases=['admit','waiter leaves','result known','close observed']
  row_roles=['blue','violet','amber','teal']
  for i,t in enumerate(phases):para(cv,t,left+i*cell,top,cell-3,8.8,True,PALETTE[row_roles[i]]['ink'])
  for j,name in enumerate(names):
   theme=PALETTE[row_roles[j]]
   yy=top-75-j*85;para(cv,name,x,yy+28,95,10,True,theme['ink'])
   for i in range(4):
    cv.setStrokeColor(EDGE);cv.setDash(2,3);cv.line(left+i*cell,yy-20,left+i*cell,yy+42);cv.setDash()
   starts=[0,0,2,0];ends=[1,2,3,3];a,b=starts[j],ends[j]
   cv.setFillColor(theme['fill']);cv.setStrokeColor(theme['edge']);cv.setLineWidth(1.1);cv.roundRect(left+a*cell,yy,(b-a)*cell,24,3,fill=1,stroke=1)
   para(cv,['wait budget','in flight until result','cleanup retained','held until actual closure'][j],left+a*cell+4,yy+19,(b-a)*cell-8,8.5)
  box(cv,x,top-455,w,75,'Do not release by the shortest lifetime','Known business bytes may survive cleanup failure. A timed-out observer can coexist with a still-running remote request and a retained slot.')
  low=top-465
 elif k=='nats':
  sequence(cv,x,top,w,['Publisher','JetStream','Consumer','P1 / supplier'],[(0,1,'publish stable event identity'),(1,0,'ACK A: configured storage accepted'),(1,2,'deliver retained message'),(2,3,'use original business identity'),(3,2,'receipt or unresolved outcome'),(2,1,'ACK B only after durable handling'),(3,0,'ACK C: business receipt via API')],54)
  para(cv,'In this hypothetical policy, an unresolved delivery stays unACKed while its original identity is reconciled. No blind external-effect retry follows from broker redelivery.',x,top-469,w,9.2)
  low=top-510
 elif k=='planes':
  independent=[('WebRTC media','Browser / native participants exchange protected media through the SFU'),('LiveKit control and internal RPC','Signaling, room routing and server components use their selected bus'),('Public self-host server evidence','Distributed docs and public wiring use Redis; single-node wiring can be local'),('PSRPC transport capability','The library supports NATS, Redis and local adapters'),('This POC business authority','PostgreSQL accepted work remains in P1. No NATS service is implemented here')]
  for i,(a,b) in enumerate(independent):box(cv,x,top-70-i*90,w,70,a,b)
  low=top-450
 elif k=='singleflight':
  sequence(cv,x,top,w,['Reader A','Published scan','Reader B'],[(0,1,'reserve and publish one owner'),(2,1,'join active scan'),(0,1,'A cancels its waiter'),(1,1,'B still interested: continue'),(1,2,'return same scoped observation'),(2,1,'if last waiter leaves: abandon'),(1,1,'retain actual owner until drain')],55)
  low=top-465
 elif k=='triage':
  box(cv,x,top-65,w,65,'What is actually missing?','Pick one correlated input and separate control, media, inference and business observations.')
  rows=[('Cannot join','Check authentication, trusted room binding and control readiness.'),('Connected but silent','Inspect capture, track publish/subscribe, packets and browser output.'),('Media works but reply stalls','Inspect turn admission, event loop, provider and slot contention.'),('No business receipt','Inspect original durable identity, possible-call marker and reconciliation.'),('Old result or stuck capacity','Inspect current permission, original result identity and actual owner drain.')]
  yy=top-155
  for a,b in rows:
   box(cv,x,yy-42,135,60,a);box(cv,x+156,yy-42,w-156,60,b);arrow(cv,x+135,yy-12,x+156,yy-12);yy-=88
  low=top-554
 elif k=='feedcommit':
  para(cv,'IMPLEMENTED  /  ONE ADMISSION ORDER',x,top,w,10.2,True)
  sequence(cv,x,top-25,w,['Writer A','Shared guard','Writer B'],[(0,1,'lock; write result and scoped n'),(2,1,'wait for same admission'),(0,1,'commit result and event together'),(1,2,'then lock; write scoped n+1')],44)
  para(cv,'COUNTEREXAMPLE  /  GLOBAL PRECOMMIT SEQUENCE',x,top-310,w,10.2,True)
  box(cv,x,top-425,w,85,'Allocate n to A, then pause A before commit','B commits n+1. A consumer advances beyond n+1. A later commits n, which that cursor can miss. Unique numbers alone do not establish safe visibility order.')
  box(cv,x,top-530,w,72,'Scope is part of the cursor','Source UUID and account scope bind the feed. A read cursor is not an execution grant or a source acknowledgment.')
  low=top-540
 elif k=='auth':
  sequence(cv,x,top,w,['Raw request','Local adapter','PostgreSQL'],[(0,1,'bounded local call admission'),(1,1,'check MAC and bytes using signed time'),(1,2,'connect only after cheap check'),(2,2,'acquire shared admission lock'),(2,2,'read fresh database time'),(1,2,'authenticate again for freshness'),(2,2,'check current sender binding'),(2,1,'commit or reject authentic stale input')],52)
  low=top-490
 elif k=='facts':
  flow(cv,x,top,w,[('1  Structural parse','Closed fields, primitive types, bounds and supported codec'),('2  Correlation and original identity','Match scope, work, attempt, result and immutable evidence bindings'),('3  Factual support','Verify the result against the exact policy and fact records'),('4  Time and current applicability','Late truth can remain historical; unsupported facts do not become valid'),('5  Permission for a next operation','Delivery and exact human-confirmed action need their own current guards')]);low=top-450
 return low
