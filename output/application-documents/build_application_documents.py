"""Create matching, editable application documents from reviewed content."""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
from lxml import etree

from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK, WD_TAB_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Mm, Pt, RGBColor

ROOT = Path(__file__).resolve().parent
OUT = ROOT.parent / "docx"
DATA = json.loads((ROOT / "application-content.json").read_text())
BLACK = "1A1F26"
MUTED = "4A5563"
LINK = "1F4E8C"
RULE = "C3CCD6"
CONTENT_WIDTH = 522.72
FONT_DIR = ROOT / "fonts"


def set_font(style, size, *, bold=False, color=BLACK):
    style.font.name = "Lato"
    style.font.size = Pt(size)
    style.font.bold = bold
    style.font.italic = False
    style.font.color.rgb = RGBColor.from_string(color)
    rpr = style.element.get_or_add_rPr()
    fonts = rpr.find(qn("w:rFonts"))
    if fonts is None:
        fonts = OxmlElement("w:rFonts")
        rpr.insert(0, fonts)
    for key in list(fonts.attrib):
        if key.rsplit("}", 1)[-1].lower().endswith("theme"):
            del fonts.attrib[key]
    for key in ("ascii", "hAnsi", "eastAsia", "cs"):
        fonts.set(qn("w:" + key), "Lato")
    for node in rpr.findall(qn("w:spacing")):
        rpr.remove(node)


def family(style, name):
    style.font.name = name
    fonts = style.element.get_or_add_rPr().find(qn("w:rFonts"))
    for key in ("ascii", "hAnsi", "eastAsia", "cs"):
        fonts.set(qn("w:" + key), name)


def rule(p, space=1):
    props = p._p.get_or_add_pPr()
    borders = props.find(qn("w:pBdr"))
    if borders is None:
        borders = OxmlElement("w:pBdr")
        props.append(borders)
    bottom = OxmlElement("w:bottom")
    for k, v in (("val", "single"), ("sz", "6"), ("space", str(space)), ("color", RULE)):
        bottom.set(qn("w:" + k), v)
    borders.append(bottom)


def section_heading(doc, title, *, first=False):
    p = doc.add_paragraph(title, "Heading 1")
    if first:
        p.paragraph_format.space_before = Pt(0)
    rule(p)
    return p


def embed_fonts(path):
    """Embed OFL Lato fonts so the Word files preserve their typography."""
    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    rns = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    pns = "http://schemas.openxmlformats.org/package/2006/relationships"
    cns = "http://schemas.openxmlformats.org/package/2006/content-types"
    with ZipFile(path) as z:
        data = {name: z.read(name) for name in z.namelist()}
    fonts = etree.fromstring(data["word/fontTable.xml"])
    rel_path = "word/_rels/fontTable.xml.rels"
    rels = etree.fromstring(data[rel_path]) if rel_path in data else etree.Element("{" + pns + "}Relationships", nsmap={None:pns})
    entries = [("Lato", "embedRegular", "Lato-Regular.ttf"), ("Lato", "embedBold", "Lato-Bold.ttf"),
               ("Lato", "embedItalic", "Lato-Italic.ttf"), ("Lato Black", "embedRegular", "Lato-Black.ttf"),
               ("Lato SemiBold", "embedRegular", "Lato-Semibold.ttf")]
    for i, (name, tag, file) in enumerate(entries, 1):
        candidates = fonts.xpath("w:font[@w:name=$name]", namespaces={"w":ns}, name=name)
        font = candidates[0] if candidates else etree.SubElement(fonts, "{" + ns + "}font", {"{" + ns + "}name":name})
        key = uuid.uuid5(uuid.NAMESPACE_URL, "livekit-resume-font/" + file)
        xor_key = key.bytes[::-1]
        raw = bytearray((FONT_DIR / file).read_bytes())
        for pos in range(32):
            raw[pos] ^= xor_key[pos % 16]
        target = f"fonts/lato-{i}.odttf"
        data["word/" + target] = bytes(raw)
        rid = f"rIdLato{i}"
        etree.SubElement(rels, "{" + pns + "}Relationship", Id=rid, Type=rns + "/font", Target=target)
        etree.SubElement(font, "{" + ns + "}" + tag, {"{" + rns + "}id":rid, "{" + ns + "}fontKey":"{" + str(key).upper() + "}", "{" + ns + "}subsetted":"false"})
    types = etree.fromstring(data["[Content_Types].xml"])
    if not types.xpath("ct:Default[@Extension='odttf']", namespaces={"ct":cns}):
        etree.SubElement(types, "{" + cns + "}Default", Extension="odttf", ContentType="application/vnd.openxmlformats-officedocument.obfuscatedFont")
    for name, tree in (("word/fontTable.xml", fonts), (rel_path, rels), ("[Content_Types].xml", types)):
        data[name] = etree.tostring(tree, xml_declaration=True, encoding="UTF-8", standalone=True)
    with ZipFile(path, "w", ZIP_DEFLATED) as z:
        for name, value in data.items():
            z.writestr(name, value)


def add_style(doc, name, size, *, before=0, after=0, leading=1.1, bold=False, color=BLACK, keep=False):
    style = doc.styles[name] if name in doc.styles else doc.styles.add_style(name, WD_STYLE_TYPE.PARAGRAPH)
    set_font(style, size, bold=bold, color=color)
    pf = style.paragraph_format
    pf.space_before = Pt(before)
    pf.space_after = Pt(after)
    pf.line_spacing = leading
    pf.keep_with_next = keep
    pf.widow_control = True
    return style


def make_doc(subject, *, letter=False):
    doc = Document()
    section = doc.sections[0]
    section.page_width, section.page_height = Pt(612), Pt(792)
    section.top_margin = Pt(36)
    section.bottom_margin = Pt(35)
    section.left_margin = Pt(44.64)
    section.right_margin = Pt(44.64)
    section.header_distance, section.footer_distance = Pt(13), Pt(14)
    add_style(doc, "Normal", 9.7, after=5, leading=Pt(13.1))
    add_style(doc, "Title", 23, after=1, leading=Pt(27), keep=True)
    family(doc.styles["Title"], "Lato Black")
    add_style(doc, "Subtitle", 11, after=4, leading=Pt(13.2), color=LINK, keep=True)
    family(doc.styles["Subtitle"], "Lato SemiBold")
    add_style(doc, "Contact", 8.9, after=3, leading=Pt(11.7), color=MUTED, keep=True)
    add_style(doc, "Heading 1", 9.4, before=8, after=5, bold=True, leading=Pt(12.2), color=LINK, keep=True)
    spacing = OxmlElement("w:spacing")
    spacing.set(qn("w:val"), "20")
    doc.styles["Heading 1"].element.get_or_add_rPr().append(spacing)
    add_style(doc, "Role", 10.2, before=5, after=2, bold=True, leading=Pt(13), keep=True)
    add_style(doc, "Context", 8.6, after=3, leading=Pt(10.8), color=MUTED, keep=True)
    doc.styles["Context"].font.italic = True
    add_style(doc, "Resume Bullet", 9.55, after=1.5, leading=Pt(12.6))
    add_style(doc, "Skills", 9.55, after=2, leading=Pt(12.6))
    add_style(doc, "Project Note", 8.6, after=5, leading=Pt(10.8), color=MUTED)
    add_style(doc, "Letter Body", 10.6, after=8, leading=Pt(14.2))
    add_style(doc, "Letter Bullet", 10.6, after=3, leading=Pt(14.2))
    for style in doc.styles:
        for border in style.element.xpath(".//w:pBdr"):
            border.getparent().remove(border)
    doc.core_properties.title = f"Rahul Ostwal {subject}"
    doc.core_properties.author = DATA["name"]
    doc.core_properties.subject = "Software Engineer Agents at LiveKit"
    doc.core_properties.keywords = "Python, TypeScript, LiveKit Agents, durable workflows, developer APIs"
    doc.core_properties.comments = ""
    settings = doc.settings.element
    for tag in ("embedTrueTypeFonts", "embedSystemFonts"):
        node = OxmlElement("w:" + tag)
        node.set(qn("w:val"), "true")
        settings.append(node)
    auto = settings.find(qn("w:autoHyphenation"))
    if auto is None:
        auto = OxmlElement("w:autoHyphenation")
        settings.append(auto)
    auto.set(qn("w:val"), "false")
    if not letter:
        section.different_first_page_header_footer = True
        p = section.footer.paragraphs[0]
        p.style = doc.styles["Contact"]
        p.paragraph_format.keep_with_next = False
        p.add_run(f"{DATA['name']} · {DATA['contact']['email']}")
        p.paragraph_format.tab_stops.add_tab_stop(Pt(CONTENT_WIDTH), WD_TAB_ALIGNMENT.RIGHT)
        p.add_run("\tPage ")
        for r in p.runs:
            r.font.size = Pt(7.6)
        field = OxmlElement("w:fldSimple")
        field.set(qn("w:instr"), "PAGE")
        run = OxmlElement("w:r")
        text = OxmlElement("w:t")
        text.text = "2"
        run.append(text)
        field.append(run)
        p._p.append(field)
    return doc


def hyperlink(p, label, url, *, bold=False, color_value=LINK):
    part = p.part
    rid = part.relate_to(url, "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink", is_external=True)
    link = OxmlElement("w:hyperlink")
    link.set(qn("r:id"), rid)
    run = OxmlElement("w:r")
    props = OxmlElement("w:rPr")
    color = OxmlElement("w:color")
    color.set(qn("w:val"), color_value)
    props.append(color)
    if bold:
        b = OxmlElement("w:b")
        props.append(b)
    run.append(props)
    text = OxmlElement("w:t")
    text.text = label
    run.append(text)
    link.append(run)
    p._p.append(link)


def identity(doc, *, cover=False):
    doc.add_paragraph(DATA["name"], "Title")
    headline = DATA["headline"].replace(" | ", " — ", 1).replace(" | ", " · ")
    doc.add_paragraph(headline, "Subtitle")
    c = DATA["contact"]
    p = doc.add_paragraph(style="Contact")
    p.add_run(c["phone"] + " · ")
    hyperlink(p, c["email"], "mailto:" + c["email"])
    p.add_run(" · " + c["location"] + " · " + c["remote"] + " · ")
    hyperlink(p, "LinkedIn", c["linkedin"])
    p.add_run(" · ")
    hyperlink(p, "GitHub", c["github"])
    p.add_run(" · ")
    hyperlink(p, "livekit-continuity", c["project"])
    p.paragraph_format.space_after = Pt(5)
    if cover:
        p = doc.add_paragraph()
        p.paragraph_format.line_spacing = Pt(1)
        p.paragraph_format.space_after = Pt(11)
        p.paragraph_format.keep_with_next = True
        p.add_run().font.size = Pt(1)
        rule(p, space=1)


def labelled(doc, item, style="Resume Bullet", *, bullet=True):
    p = doc.add_paragraph(style=style)
    p.paragraph_format.keep_together = True
    if bullet:
        p.paragraph_format.left_indent = Pt(11)
        p.paragraph_format.first_line_indent = Pt(-11)
        p.paragraph_format.tab_stops.add_tab_stop(Pt(11))
        r = p.add_run("●\t")
        r.font.size = Pt(8.4)
        r.font.color.rgb = RGBColor.from_string(LINK)
    p.add_run(item["label"] + ": ").bold = True
    p.add_run(item["text"])
    return p


def role_line(doc, title, dates, *, url=None, employer=None, descriptor=None):
    p = doc.add_paragraph(style="Role")
    p.paragraph_format.tab_stops.add_tab_stop(Pt(CONTENT_WIDTH), WD_TAB_ALIGNMENT.RIGHT)
    if url:
        hyperlink(p, title, url, bold=True, color_value=LINK)
    else:
        p.add_run(title)
    if employer:
        p.add_run(" — ")
        r = p.add_run(employer)
        r.font.color.rgb = RGBColor.from_string(LINK)
    if descriptor:
        r = p.add_run(" — " + descriptor)
        r.bold = False
    r = p.add_run("\t" + dates.replace(" - ", " – ").replace(" | ", " · "))
    r.bold = False
    r.font.size = Pt(8.7)
    r.font.color.rgb = RGBColor.from_string(MUTED)
    return p


def resume():
    doc = make_doc("Resume")
    identity(doc)
    section_heading(doc, "SUMMARY")
    doc.add_paragraph(DATA["summary"])
    section_heading(doc, "EXPERIENCE")
    for role in DATA["experience"]:
        parts = role["context"].split(" | ")
        left = role["title"] + ", " + parts[0]
        dates = role["dates"] + (" · " + parts[1] if len(parts) > 1 else "")
        role_line(doc, left, dates, employer=role["company"])
        for b in role["bullets"]:
            labelled(doc, b)
    doc.add_page_break()
    section_heading(doc, "SELECTED PROJECTS", first=True)
    for project in DATA["projects"]:
        role_line(doc, project["name"], project["dates"], url=DATA["contact"][project["url_key"]], descriptor=project["description"])
        doc.add_paragraph(project["stack"], "Context")
        for b in project["bullets"]:
            labelled(doc, b)
        if project.get("note"):
            doc.add_paragraph(project["note"], "Project Note")
    section_heading(doc, "TECHNICAL SKILLS")
    for item in DATA["skills"]:
        labelled(doc, item, style="Skills", bullet=True)
    section_heading(doc, "EDUCATION AND RECOGNITION")
    for item in DATA["education"]:
        labelled(doc, item, style="Skills", bullet=True)
    path = OUT / "Rahul_Ostwal_Resume_LiveKit.docx"
    doc.save(path)
    embed_fonts(path)
    return path


def cover():
    doc = make_doc("Cover Letter LiveKit", letter=True)
    identity(doc, cover=True)
    letter = DATA["letter"]
    p = doc.add_paragraph(letter["date"], "Letter Body")
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(11)
    p = doc.add_paragraph(letter["recipient"], "Letter Body")
    p.paragraph_format.space_after = Pt(2)
    p.runs[0].bold = True
    p = doc.add_paragraph(letter["subject"], "Letter Body")
    p.paragraph_format.space_after = Pt(12)
    doc.add_paragraph(letter["salutation"], "Letter Body")
    for index, text in enumerate(letter["paragraphs"]):
        if index == 1:
            # Retain the original letter's short introduction and three blue
            # technical bullets, preserving the reviewed wording verbatim.
            sentences = text.split(". ")
            intro = doc.add_paragraph(sentences[0] + ".", "Letter Body")
            intro.paragraph_format.space_after = Pt(4)
            for sentence in sentences[1:]:
                sentence = sentence if sentence.endswith(".") else sentence + "."
                p = doc.add_paragraph(style="Letter Bullet")
                p.paragraph_format.keep_together = True
                p.paragraph_format.left_indent = Pt(11)
                p.paragraph_format.first_line_indent = Pt(-11)
                p.paragraph_format.tab_stops.add_tab_stop(Pt(11))
                dot = p.add_run("●\t")
                dot.font.size = Pt(8.4)
                dot.font.color.rgb = RGBColor.from_string(LINK)
                phrases = ["bounded actor scheduling", "Python execution components", "shared protobuf contract"]
                remaining = sentence
                for phrase in phrases:
                    if phrase in remaining:
                        before, after = remaining.split(phrase, 1)
                        p.add_run(before)
                        p.add_run(phrase).bold = True
                        remaining = after
                p.add_run(remaining)
            p.paragraph_format.space_after = Pt(8)
            continue
        p = doc.add_paragraph(style="Letter Body")
        p.paragraph_format.keep_together = True
        if "I built livekit-continuity" in text:
            start, rest = text.split("livekit-continuity", 1)
            p.add_run(start)
            hyperlink(p, "livekit-continuity", DATA["contact"]["project"])
            p.add_run(rest)
        else:
            p.add_run(text)
    p = doc.add_paragraph(letter["closing"], "Letter Body")
    p.paragraph_format.space_after = Pt(3)
    p = doc.add_paragraph(DATA["name"], "Letter Body")
    p.runs[0].bold = True
    path = OUT / "Rahul_Ostwal_Cover_Letter_LiveKit.docx"
    doc.save(path)
    embed_fonts(path)
    return path


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for path in (resume(), cover()):
        print(path)
