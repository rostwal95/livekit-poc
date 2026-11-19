"""Additional vector study diagrams, independent of the book builder.

These are framework explanations and proposed integration designs. They do not
assert that the local POC implements the illustrated frontend, SIP, RAG or model
evaluation extensions. Existing F01-F19 are owned by color_figures.py.
"""

from __future__ import annotations

import html
import math

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.platypus import Paragraph


BLACK = colors.HexColor("#23343F")
GRAY = colors.HexColor("#5D6D78")
EDGE = colors.HexColor("#8397A5")
PALETTE = {
    "blue": dict(fill=colors.HexColor("#EAF3FF"), edge=colors.HexColor("#4078C7"), ink=colors.HexColor("#204E88")),
    "teal": dict(fill=colors.HexColor("#E8F7F3"), edge=colors.HexColor("#2D947E"), ink=colors.HexColor("#186653")),
    "violet": dict(fill=colors.HexColor("#F2EDFC"), edge=colors.HexColor("#8B65C0"), ink=colors.HexColor("#58358A")),
    "amber": dict(fill=colors.HexColor("#FFF5DF"), edge=colors.HexColor("#BE8923"), ink=colors.HexColor("#81580E")),
    "rose": dict(fill=colors.HexColor("#FFF0EC"), edge=colors.HexColor("#C86D62"), ink=colors.HexColor("#9C4438")),
    "slate": dict(fill=colors.HexColor("#F0F4F7"), edge=colors.HexColor("#8095A3"), ink=colors.HexColor("#3F596A")),
}


FIGURES = {
    "sdk_work": {
        "id": "F20",
        "title": "Choose the owner of the work",
        "caption": "Framework and project boundaries. Conversational tasks and Python task groups own different in-process behavior. An application may submit business work through public P1 APIs; that is an explicit integration, not automatic durability or confirmation supplied by the SDK.",
        "refs": ["LK-09", "LK-20"],
    },
    "frontend_authority": {
        "id": "F21",
        "title": "Name the frontend acknowledgment",
        "caption": "Proposed frontend design. A signed token, room data and a durable command receipt establish different facts. The adapter enforces application scope and exact intent. A lost reply preserves uncertainty and the original command identity; it does not authorize a second booking.",
        "refs": ["LK-14", "LK-15"],
    },
    "sip_transfer": {
        "id": "F22",
        "title": "Route the call before transferring it",
        "caption": "Telephony concepts and a proposed warm-transfer recovery path. Room placement does not prove named-agent dispatch. Consultation, answer, permitted merge and cleanup are separate observations. This is not an atomic transfer/effect protocol or evidence of a working PSTN integration in the POC.",
        "refs": ["LK-16", "LK-17"],
    },
    "rag_output": {
        "id": "F23",
        "title": "Admit evidence before releasing speech",
        "caption": "Proposed turn-scoped retrieval and output admission. Current access, evidence provenance, output policy and lifecycle binding are separate checks. Once audio escapes, a later filter cannot retract it. Ending a waiter neither proves actual I/O stopped nor cancels accepted business work.",
        "refs": ["LK-11", "LK-12", "LK-18", "LK-19"],
    },
    "evidence_layers": {
        "id": "F24",
        "title": "Match each claim to its evidence",
        "caption": "Independent evidence obligations, not a ladder of automatic promotion. Passing one category does not pass another. Model quality, actual media, recovery and capacity need their own relevant observations, versions, workload and limits; this diagram grants no new qualification to the POC.",
        "refs": ["ROLE-13", "SCALE-09", "SCALE-10"],
    },
}


def _font(bold: bool = False) -> str:
    name = "BodyB" if bold else "Body"
    return name if name in pdfmetrics.getRegisteredFontNames() else ("Helvetica-Bold" if bold else "Helvetica")


def _paragraph(cv, text, x, top, w, *, size=9.4, bold=False, color=BLACK, draw=True):
    style = ParagraphStyle(
        "academy-figure",
        fontName=_font(bold),
        fontSize=size,
        leading=size * 1.30,
        textColor=color,
        splitLongWords=False,
    )
    para = Paragraph(html.escape(text).replace("\n", "<br/>"), style)
    _, h = para.wrap(w, 1200)
    if draw:
        para.drawOn(cv, x, top - h)
    return h


def _node(cv, x, top, w, h, title, body="", *, role="blue", dashed=False):
    theme = PALETTE[role]
    pad = 11
    th = _paragraph(cv, title, x + pad, top - 10, w - 2 * pad, size=10.2, bold=True, draw=False)
    bh = _paragraph(cv, body, x + pad, top - 16 - th, w - 2 * pad, draw=False) if body else 0
    needed = 20 + th + (6 + bh if body else 0)
    if needed > h + 0.1:
        raise ValueError(f"Diagram node overflow: {title!r} needs {needed:.1f}pt, has {h:.1f}pt")
    cv.saveState()
    cv.setFillColor(theme["fill"])
    cv.setStrokeColor(theme["edge"])
    cv.setLineWidth(1)
    if dashed:
        cv.setDash(4, 3)
    cv.roundRect(x, top - h, w, h, 4, fill=1, stroke=1)
    cv.setDash()
    cv.setFillColor(theme["edge"])
    cv.roundRect(x + 3, top - h + 7, 2.2, h - 14, 1.1, fill=1, stroke=0)
    _paragraph(cv, title, x + pad, top - 10, w - 2 * pad, size=10.2, bold=True, color=theme["ink"])
    if body:
        _paragraph(cv, body, x + pad, top - 16 - th, w - 2 * pad)
    cv.restoreState()


def _arrow(cv, points, *, role="blue", dashed=False):
    theme = PALETTE[role]
    cv.saveState()
    cv.setStrokeColor(theme["edge"])
    cv.setFillColor(theme["edge"])
    cv.setLineWidth(1.15)
    if dashed:
        cv.setDash(4, 3)
    path = cv.beginPath()
    path.moveTo(*points[0])
    for point in points[1:]:
        path.lineTo(*point)
    cv.drawPath(path)
    cv.setDash()
    (x1, y1), (x2, y2) = points[-2:]
    angle = math.atan2(y2 - y1, x2 - x1)
    s = 5
    head = cv.beginPath()
    head.moveTo(x2, y2)
    head.lineTo(x2 - s * math.cos(angle - 0.45), y2 - s * math.sin(angle - 0.45))
    head.lineTo(x2 - s * math.cos(angle + 0.45), y2 - s * math.sin(angle + 0.45))
    head.close()
    cv.drawPath(head, stroke=0, fill=1)
    cv.restoreState()


def _label(cv, text, x, top, w, *, role="slate"):
    h = _paragraph(cv, text, x, top, w, size=9.0, bold=True, draw=False)
    # Section text may interrupt a connector, but must never share its ink.
    cv.saveState()
    cv.setFillColor(colors.white)
    cv.rect(x - 1, top - h - 2, w + 2, h + 4, fill=1, stroke=0)
    cv.restoreState()
    return _paragraph(cv, text, x, top, w, size=9.0, bold=True, color=PALETTE[role]["ink"])


def _sdk_work(cv, x, w, top):
    _label(cv, "IN-PROCESS CONTROL / DIFFERENT CONTRACTS", x, top, w)
    gap = 12
    cw = (w - 2 * gap) / 3
    nodes = [
        ("AgentTask", "Focused multi-turn collection; await a result and validate its values.", "teal"),
        ("SDK TaskGroup", "Sequence task factories by ID; return keyed conversational results.", "blue"),
        ("asyncio.TaskGroup", "Own related Python tasks, failures and cancellation in this process.", "slate"),
    ]
    for i, (title, body, role) in enumerate(nodes):
        _node(cv, x + i * (cw + gap), top - 28, cw, 116, title, body, role=role, dashed=True)
    _node(cv, x, top - 168, w, 66, "Process loss crosses a lifetime boundary", "Local context and task ownership do not become durable business receipts.", role="amber")
    _arrow(cv, [(x + w / 2, top - 236), (x + w / 2, top - 292)], role="violet", dashed=True)
    _label(cv, "WHEN REQUIRED: APPLICATION SUBMITS / RECONCILES PUBLIC P1 WORK", x, top - 253, w, role="violet")
    _node(cv, x, top - 296, w, 92, "P1 / durable business authority", "Retain original acceptance, issued execution permission, effect knowledge and receipts under the selected public contract.", role="violet")
    _node(cv, x, top - 416, w, 66, "Keep exact permission separate", "A task result or graph checkpoint is not human confirmation or permission to repeat an uncertain effect.", role="rose")
    return top - 488


def _frontend_authority(cv, x, w, top):
    _label(cv, "1 / AUTHORIZE TOKEN ISSUANCE", x, top, w)
    left = 158
    gap = 32
    right = w - left - gap
    _node(cv, x, top - 24, left, 92, "Browser / user", "Requests access; supplied room and role labels need authorization.", role="teal")
    _node(cv, x + left + gap, top - 24, right, 92, "Trusted token issuer", "Authenticate user; choose scope and grants. JWT = signed join permission.", role="blue")
    _arrow(cv, [(x + left + 2, top - 54), (x + left + gap - 2, top - 54)], role="teal")
    _arrow(cv, [(x + left + gap - 2, top - 92), (x + left + 2, top - 92)], role="blue")
    _label(cv, "2 / ROOM DATA HAS TRANSPORT-SPECIFIC MEANING", x, top - 140, w)
    cw = (w - 24) / 3
    for i, (title, body, role) in enumerate([
        ("RPC", "Reply = handler observation. Payload and response schemas are application-owned.", "blue"),
        ("Text / byte streams", "Incremental content. Stream completion is not a business command receipt.", "teal"),
        ("Attributes", "Current room participant state. A UI projection is not a durable journal.", "slate"),
    ]):
        _node(cv, x + i * (cw + 12), top - 165, cw, 116, title, body, role=role)
    _arrow(cv, [(x + w / 2, top - 284), (x + w / 2, top - 330)], role="violet", dashed=True)
    _label(cv, "EXPLICIT AUTHENTICATED ADAPTER / EXACT INTENT", x, top - 305, w, role="violet")
    _node(cv, x, top - 334, w, 78, "3 / durable case command", "Original command ID + expected revision + exact proposal. The case authority commits and retains its supported receipt.", role="violet")
    _node(cv, x, top - 438, w, 60, "Reply lost? Reconcile the same command", "A transport ACK or timeout cannot establish the business outcome.", role="amber")
    return top - 500


def _sip_transfer(cv, x, w, top):
    _label(cv, "CALL PLACEMENT AND AGENT DISPATCH ARE SEPARATE", x, top, w)
    cw = (w - 28) / 3
    for i, (title, body, role) in enumerate([
        ("1 / SIP trunk", "A carrier call leg enters the SIP integration.", "teal"),
        ("2 / SIP dispatch rule", "Select the caller's destination room.", "blue"),
        ("3 / room", "SIP caller present; agent dispatch still needs evidence.", "slate"),
    ]):
        xx = x + i * (cw + 14)
        _node(cv, xx, top - 24, cw, 86, title, body, role=role)
        if i < 2:
            _arrow(cv, [(xx + cw + 1, top - 67), (xx + cw + 13, top - 67)], role=role)
    bw = (w - 28) / 2
    _arrow(cv, [(x + 2 * (cw + 14) + cw / 2, top - 112), (x + 2 * (cw + 14) + cw / 2, top - 133), (x + bw / 2, top - 133), (x + bw / 2, top - 154)], role="blue")
    _node(cv, x, top - 158, bw, 76, "4 / named-agent dispatch", "Resolve registered agent_name; observe job acceptance.", role="violet")
    _node(cv, x + bw + 28, top - 158, bw, 76, "5 / agent joins", "Observe readiness and media separately from room placement.", role="teal")
    _arrow(cv, [(x + bw + 2, top - 196), (x + bw + 26, top - 196)], role="violet")
    _label(cv, "WARM TRANSFER / PROPOSED WORKFLOW", x, top - 258, w, role="violet")
    for i, (title, body, role) in enumerate([
        ("Hold caller", "Own the live caller and its hold state.", "blue"),
        ("Private consultation", "Dial the intended recipient; brief privately.", "violet"),
        ("Recipient ready", "Permitted move / merge; observe actual outcome.", "teal"),
    ]):
        xx = x + i * (cw + 14)
        _node(cv, xx, top - 282, cw, 86, title, body, role=role)
        if i < 2:
            _arrow(cv, [(xx + cw + 1, top - 325), (xx + cw + 13, top - 325)], role=role)
    _arrow(cv, [(x + w / 2, top - 370), (x + w / 2, top - 404)], role="amber", dashed=True)
    _node(cv, x, top - 408, w, 72, "No answer / caller hangs up", "Return to a still-connected caller or close owned legs and rooms. Observe actual cleanup; no human ownership receipt is implied.", role="amber")
    return top - 486


def _rag_output(cv, x, w, top):
    main = 300
    gap = 24
    side = w - main - gap
    sx = x + main + gap
    center = x + main / 2
    scenter = sx + side / 2
    _node(cv, x, top, main, 82, "Original turn + trusted scope", "turn_ctx + new_message; source access and the original turn / generation identity.", role="blue")
    _node(cv, sx, top, side, 82, "Proposed extension", "General RAG is not an implemented POC capability.", role="slate", dashed=True)
    _arrow(cv, [(center, top - 84), (center, top - 118)], role="blue")
    _node(cv, x, top - 122, main, 84, "Bounded lookup / cache", "Limit deadline, bytes and chunks. Bind cache reuse to current access and evidence version.", role="teal")
    _node(cv, sx, top - 122, side, 84, "Waiter leaves", "Interruption or timeout can end this wait.", role="amber")
    _arrow(cv, [(x + main + 2, top - 164), (sx - 2, top - 164)], role="amber", dashed=True)
    _arrow(cv, [(center, top - 208), (center, top - 242)], role="teal")
    _arrow(cv, [(scenter, top - 208), (scenter, top - 242)], role="amber", dashed=True)
    _node(cv, x, top - 246, main, 120, "Evidence + output admission", "Check provenance, access and the original lifecycle binding. Generate candidate text into a bounded buffer. Validate schema / policy before yielding each approved segment.", role="violet")
    _node(cv, sx, top - 246, side, 120, "Own actual work", "Retain I/O until settled. Timeout does not prove a remote effect stopped.", role="amber")
    _arrow(cv, [(center, top - 368), (center, top - 400)], role="violet")
    _arrow(cv, [(scenter, top - 368), (scenter, top - 400)], role="amber", dashed=True)
    _node(cv, x, top - 404, main, 78, "Release approved text", "TTS then published audio. A later replacement cannot retract speech already released.", role="teal")
    _node(cv, sx, top - 404, side, 78, "Late result", "Retain its identity; do not inject it into a newer turn.", role="rose")
    return top - 488


def _evidence_layers(cv, x, w, top):
    _label(cv, "INDEPENDENT CHECKS / NO AUTOMATIC PROMOTION", x, top, w)
    left = 126
    rows = [
        ("Contract checks", "Exact assertions for scoped validation, identity and authority invariants.", "Not model quality, actual media or untested failures.", "blue"),
        ("Model turn tests", "Tool / handoff observations and calibrated judgments for pinned cases.", "Not supplier execution inferred from generated wording.", "violet"),
        ("Conversation cases", "Scenario coverage for dialog, refusal, recovery and task outcomes.", "Text simulation does not establish real audio behavior.", "teal"),
        ("Actual media", "Observed capture, recognition, interruption, transport and playout.", "Not human understanding, consent or business commitment.", "amber"),
        ("Fault + recovery", "Owned kills / restart, reconciliation and actual resource cleanup.", "Not unmeasured regional failover or production capacity.", "rose"),
    ]
    for i, (title, evidence, limit, role) in enumerate(rows):
        yy = top - 28 - i * 84
        theme = PALETTE[role]
        cv.saveState()
        cv.setFillColor(theme["fill"])
        cv.setStrokeColor(theme["edge"])
        cv.setLineWidth(0.9)
        cv.roundRect(x, yy - 74, w, 74, 4, fill=1, stroke=1)
        cv.setStrokeColor(theme["edge"])
        cv.line(x + left, yy - 62, x + left, yy - 12)
        _paragraph(cv, title, x + 12, yy - 12, left - 24, size=10.2, bold=True, color=theme["ink"])
        a = _paragraph(cv, evidence, x + left + 12, yy - 10, w - left - 24)
        b = _paragraph(cv, limit, x + left + 12, yy - 16 - a, w - left - 24, color=GRAY)
        if 26 + a + b > 74.1:
            raise ValueError(f"Evidence row overflow: {title}")
        cv.restoreState()
    _paragraph(cv, "A better average score cannot erase a failed hard invariant.", x, top - 462, w, size=10.2, bold=True, color=PALETTE["violet"]["ink"])
    return top - 484


_DRAWERS = {
    "sdk_work": _sdk_work,
    "frontend_authority": _frontend_authority,
    "sip_transfer": _sip_transfer,
    "rag_output": _rag_output,
    "evidence_layers": _evidence_layers,
}


def draw(cv, key, x, w, top=700):
    """Draw one diagram in book coordinates and return its lowest occupied y.

    The caller owns titles, captions and references. At the book's 481pt content
    width, diagram height is at most 500pt; text uses 9.4pt or larger, with 9pt
    section labels. Meaning is carried by explicit text, direction and dashes.
    """
    if key not in FIGURES:
        raise KeyError(key)
    if w < 475:
        raise ValueError("Academy figures require a content width of at least 475pt")
    cv.saveState()
    try:
        return _DRAWERS[key](cv, x, w, top)
    finally:
        cv.restoreState()
