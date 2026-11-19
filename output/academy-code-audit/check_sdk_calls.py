"""Static call-shape evidence against installed SDK signatures; never invokes providers."""
from pathlib import Path
import ast
import hashlib
import inspect
import json
from importlib.metadata import version

from livekit import rtc
from livekit.agents import Agent, AgentSession, SessionConnectOptions, WorkerOptions, room_io
from livekit.agents.types import APIConnectOptions

ROOT=Path(__file__).resolve().parents[2]
DEST=Path(__file__).resolve().parent
classes={
    'Agent':Agent,'AgentSession':AgentSession,'WorkerOptions':WorkerOptions,
    'SessionConnectOptions':SessionConnectOptions,'APIConnectOptions':APIConnectOptions,
    'rtc.RoomOptions':rtc.RoomOptions,'rtc.AudioFrame':rtc.AudioFrame,'rtc.RpcError':rtc.RpcError,
    'room_io.RoomOptions':room_io.RoomOptions,
    'room_io.AudioInputOptions':room_io.AudioInputOptions,
    'room_io.AudioOutputOptions':room_io.AudioOutputOptions,
}
rows=[]
events=[]
files=[]
errors=[]
for area in ['services','projects']:
    for path in sorted((ROOT/area).rglob('*.py')):
        rel=path.relative_to(ROOT)
        if any(x in path.parts for x in ['.venv','node_modules','dist','build','__pycache__']):continue
        if any(x in rel.parts for x in ['tests','test']):continue
        raw=path.read_text()
        tree=ast.parse(raw)
        files.append({'path':str(rel),'sha256':hashlib.sha256(raw.encode()).hexdigest()})
        for node in ast.walk(tree):
            if not isinstance(node,ast.Call):continue
            name=ast.unparse(node.func)
            target=classes.get(name)
            # RoomIO imports occasionally use another module alias; retain these
            # as manual-review sites instead of guessing their runtime receiver.
            if target is not None:
                sig=inspect.signature(target)
                params=sig.parameters
                arbitrary=any(p.kind==p.VAR_KEYWORD for p in params.values())
                given=[kw.arg for kw in node.keywords if kw.arg is not None]
                unexpected=[] if arbitrary else [k for k in given if k not in params]
                row={'path':str(rel),'line':node.lineno,'call':name,'signature':str(sig),'keywords':given,'dynamic_kwargs':any(k.arg is None for k in node.keywords),'unexpected_keywords':unexpected}
                rows.append(row)
                if unexpected:errors.append(row)
            if isinstance(node.func,ast.Attribute) and node.func.attr in ['on','off']:
                if node.args and isinstance(node.args[0],ast.Constant) and isinstance(node.args[0].value,str):
                    events.append({'path':str(rel),'line':node.lineno,'receiver':ast.unparse(node.func.value),'event':node.args[0].value,'registration':node.func.attr})

report={'sdk_versions':{name:version(name) for name in ['livekit-agents','livekit','livekit-api']},'python_source_files_parsed':len(files),'constructor_sites_checked':len(rows),'event_sites_inventoried':len(events),'errors':errors,'constructor_calls':rows,'event_sites':events,'files':files,'limits':'AST and installed call-shape check only. Dynamic aliases, lifecycle semantics, actual SDK behavior and browser APIs need separate source/test review. No model/provider invoked.'}
(DEST/'sdk-call-audit.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({k:report[k] for k in ['sdk_versions','python_source_files_parsed','constructor_sites_checked','event_sites_inventoried','errors']},indent=2))
if errors:raise SystemExit(1)
