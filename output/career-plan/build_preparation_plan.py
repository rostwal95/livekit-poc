"""Build the print companion to the repository-grounded application plan.

The content is supplied as reviewed JSON. All page geometry is checked before
the PDF is saved; reading the result still requires a rendered visual review.
"""
from __future__ import annotations

import hashlib
import html
import json
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph

ROOT = Path(__file__).resolve().parent
DEST = ROOT.parent / "pdf" / "LiveKit-Application-Preparation-Plan.pdf"
RT = Path("/Users/rostwal/.cache/codex-runtimes/codex-primary-runtime/dependencies")
FONTS = RT / "node/node_modules/pdfjs-dist/standard_fonts"
for name, file in (("Body", "LiberationSans-Regular.ttf"), ("BodyB", "LiberationSans-Bold.ttf"), ("BodyI", "LiberationSans-Italic.ttf")):
    pdfmetrics.registerFont(TTFont(name, str(FONTS / file)))
pdfmetrics.registerFontFamily("Body", normal="Body", bold="BodyB", italic="BodyI", boldItalic="BodyB")
pdfmetrics.registerFont(TTFont("Display", "/System/Library/Fonts/Supplemental/Georgia Bold.ttf"))

NAVY = colors.HexColor("#172E48")
INK = colors.HexColor("#26384B")
MUTED = colors.HexColor("#586A7C")
TEAL = colors.HexColor("#087E8B")
PURPLE = colors.HexColor("#7045A6")
CORAL = colors.HexColor("#B64F37")
GREEN = colors.HexColor("#267450")
LINE = colors.HexColor("#DCE4EC")
PALE = colors.HexColor("#F3F7FA")
W, H = A4
BOTTOM = 55
layout = []


def esc(value: str) -> str:
    return html.escape(value, quote=False)


class Page:
    def __init__(self, cv: canvas.Canvas, number: int, label: str, title: str, subtitle: str, accent=TEAL):
        self.cv = cv
        self.no = number
        self.x = 56 if number % 2 else 44
        self.width = W - 100
        self.y = H - 50
        self.accent = accent
        cv.bookmarkPage(f"page-{number}")
        cv.addOutlineEntry(title, f"page-{number}", 0, False)
        cv.setFillColor(accent)
        cv.rect(self.x, self.y - 5, 28, 3, fill=1, stroke=0)
        self.y -= 21
        self.text(label.upper(), size=8.4, color=accent, bold=True, after=10)
        self.text(title, size=25, leading=29, font="Display", color=NAVY, after=10)
        self.text(subtitle, size=10.4, leading=14.3, color=MUTED, after=17)

    def paragraph(self, value: str, width=None, size=10.5, leading=None, bold=False, font=None, color=INK):
        style = ParagraphStyle("p", fontName=font or ("BodyB" if bold else "Body"), fontSize=size,
                               leading=leading or size * 1.37, textColor=color, alignment=TA_LEFT,
                               splitLongWords=True)
        p = Paragraph(value, style)
        pw, ph = p.wrap(width or self.width, H)
        return p, pw, ph

    def text(self, value: str, *, after=8, markup=False, **kwargs):
        p, _, ph = self.paragraph(value if markup else esc(value), **kwargs)
        self.require(ph + after)
        p.drawOn(self.cv, self.x, self.y - ph)
        self.y -= ph + after

    def require(self, height: float):
        if self.y - height < BOTTOM:
            raise ValueError(f"Page {self.no} overflow: y={self.y:.1f}, required={height:.1f}")

    def section(self, label: str):
        self.y -= 5
        self.text(label.upper(), size=8.7, color=self.accent, bold=True, after=8)

    def card(self, title: str, body: str, color=None):
        color = color or self.accent
        hp, _, hh = self.paragraph(esc(title), width=self.width - 28, size=10.8, bold=True, color=color)
        bp, _, bh = self.paragraph(esc(body), width=self.width - 28, size=10.3, leading=14.2)
        height = hh + bh + 29
        self.require(height + 10)
        self.cv.setFillColor(PALE)
        self.cv.roundRect(self.x, self.y - height, self.width, height, 6, fill=1, stroke=0)
        self.cv.setFillColor(color)
        self.cv.rect(self.x, self.y - height + 7, 3, height - 14, fill=1, stroke=0)
        hp.drawOn(self.cv, self.x + 14, self.y - 11 - hh)
        bp.drawOn(self.cv, self.x + 14, self.y - 17 - hh - bh)
        self.y -= height + 10

    def bullets(self, values, size=10.4, after=6):
        for value in values:
            p, _, ph = self.paragraph(esc(value), width=self.width - 17, size=size)
            self.require(ph + after)
            self.cv.setStrokeColor(self.accent)
            self.cv.setLineWidth(.8)
            self.cv.rect(self.x + 1, self.y - 8, 5.5, 5.5, fill=0, stroke=1)
            p.drawOn(self.cv, self.x + 17, self.y - ph)
            self.y -= ph + after

    def table(self, headers, rows, proportions, size=9.7, padding=8):
        widths = [self.width * item / sum(proportions) for item in proportions]
        for row_no, row in enumerate([headers] + rows):
            cells = [self.paragraph(esc(str(value)), width=width - padding * 2, size=size,
                                    leading=size * 1.32, bold=row_no == 0,
                                    color=colors.white if row_no == 0 else INK)
                     for value, width in zip(row, widths)]
            height = max(item[2] for item in cells) + padding * 2
            self.require(height)
            self.cv.setFillColor(self.accent if row_no == 0 else (PALE if row_no % 2 else colors.white))
            self.cv.rect(self.x, self.y - height, self.width, height, fill=1, stroke=0)
            x = self.x
            for (p, _, ph), width in zip(cells, widths):
                p.drawOn(self.cv, x + padding, self.y - padding - ph)
                x += width
            self.cv.setStrokeColor(LINE)
            self.cv.setLineWidth(.4)
            self.cv.line(self.x, self.y - height, self.x + self.width, self.y - height)
            self.y -= height
        self.y -= 12

    def source(self, label: str, value: str, target: str | None = None):
        self.text(label, size=8.7, bold=True, after=2)
        self.text(value, size=8.1, leading=10.5, color=MUTED, after=8)
        if target:
            self.cv.linkURL(target, (self.x, self.y + 7, self.x + self.width, self.y + 28), relative=0)

    def done(self):
        self.cv.setStrokeColor(LINE)
        self.cv.line(self.x, 42, self.x + self.width, 42)
        self.cv.setFillColor(MUTED)
        self.cv.setFont("Body", 8)
        self.cv.drawString(self.x, 28, "LIVEKIT / APPLICATION & PREPARATION / 17 NOV 2026")
        self.cv.drawRightString(self.x + self.width, 28, f"{self.no:02d} / 08")
        layout.append({"page": self.no, "content_bottom": round(self.y, 2), "width": round(self.width, 2)})
        self.cv.showPage()


def main():
    data = json.loads((ROOT / "plan-content.json").read_text())
    DEST.parent.mkdir(parents=True, exist_ok=True)
    cv = canvas.Canvas(str(DEST), pagesize=A4, pageCompression=1)
    cv.setTitle("LiveKit Agents - Application and Preparation Plan")
    cv.setAuthor("Prepared for Rahul Ostwal")
    cv.setSubject("India remote eligibility, repository evidence, and a 22-hour weekly preparation plan")
    for i, content in enumerate(data["pages"], 1):
        accent = {"teal": TEAL, "purple": PURPLE, "coral": CORAL, "green": GREEN}[content.get("accent", "teal")]
        page = Page(cv, i, content["label"], content["title"], content["subtitle"], accent)
        for block in content["blocks"]:
            kind = block["kind"]
            if kind == "text":
                page.text(block["text"], size=block.get("size", 10.5), after=block.get("after", 8), bold=block.get("bold", False))
            elif kind == "section":
                page.section(block["text"])
            elif kind == "card":
                page.card(block["title"], block["text"])
            elif kind == "bullets":
                page.bullets(block["items"], size=block.get("size", 10.4))
            elif kind == "table":
                page.table(block["headers"], block["rows"], block["widths"], size=block.get("size", 9.7), padding=block.get("padding", 8))
            elif kind == "source":
                page.source(block["label"], block["text"], block.get("url"))
            else:
                raise ValueError(kind)
        page.done()
    if len(data["pages"]) != 8:
        raise ValueError("This edition is designed as eight A4 pages")
    cv.save()
    minimum_table_type = min(block.get("size", 9.7) for page in data["pages"] for block in page["blocks"] if block["kind"] == "table")
    metadata = {"pdf": str(DEST), "pages": len(layout), "sha256": hashlib.sha256(DEST.read_bytes()).hexdigest(), "layout": layout, "minimum_table_type_pt": minimum_table_type}
    (ROOT / "manifest.json").write_text(json.dumps(metadata, indent=2) + "\n")
    print(json.dumps(metadata, indent=2))


if __name__ == "__main__":
    main()
