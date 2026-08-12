from io import BytesIO

from reportlab.lib.colors import Color, HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

from app.services.docx_service import NOTICE, _entries
from app.services.file_service import generated_files
from app.utils.formatting_utils import format_ist

NAVY = HexColor("#0B1F3A")
GOLD = HexColor("#C4A35A")
SLATE = HexColor("#1C2430")
MUTED = HexColor("#5B6675")


def render_diary_pdf(exp):
    case = exp.case
    station = case.station
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4
    margin = 18 * mm

    def header(page_no):
        c.setFillColor(NAVY)
        c.rect(0, height - 16 * mm, width, 16 * mm, fill=1, stroke=0)
        c.setFillColor(GOLD)
        c.rect(0, height - 17.5 * mm, width, 1.5 * mm, fill=1, stroke=0)
        c.setFillColor(HexColor("#FFFFFF"))
        c.setFont("Times-Bold", 11)
        c.drawString(margin, height - 11 * mm, "CrimeGPT  ·  Case diary extract")
        c.setFont("Times-Roman", 9)
        c.drawRightString(width - margin, height - 11 * mm, f"{page_no}")

    def footer():
        c.setFillColor(MUTED)
        c.setFont("Times-Roman", 8)
        c.drawString(margin, 10 * mm, "Draft assistance. Officer remains responsible.")

    entries = _entries(exp)
    page = 1
    header(page)
    y = height - 28 * mm
    c.setFillColor(NAVY)
    c.setFont("Times-Bold", 14)
    c.drawString(margin, y, station.name if station else "CrimeGPT")
    y -= 6 * mm
    c.setFont("Times-Roman", 10)
    c.setFillColor(SLATE)
    if station and station.letterhead_line2:
        c.drawString(margin, y, station.letterhead_line2)
        y -= 5 * mm
    if station and station.letterhead_line3:
        c.drawString(margin, y, station.letterhead_line3)
        y -= 5 * mm
    io = case.assigned_io.full_name if case.assigned_io else "-"
    meta = [
        f"Station: {station.name if station else '-'} ({station.code if station else ''})",
        f"CR / FIR: {case.display_cr}",
        f"Investigating officer: {io}",
        f"Period: {exp.date_from.isoformat()} – {exp.date_to.isoformat()}",
    ]
    for line in meta:
        c.drawString(margin, y, line)
        y -= 5 * mm
    y -= 2 * mm
    c.setFillColor(Color(0.96, 0.93, 0.85))
    c.roundRect(margin, y - 22 * mm, width - 2 * margin, 24 * mm, 3, fill=1, stroke=0)
    c.setFillColor(SLATE)
    c.setFont("Times-Italic", 8)
    text = c.beginText(margin + 3 * mm, y - 4 * mm)
    text.setFont("Times-Italic", 8)
    for part in NOTICE.split(". "):
        text.textLine(part.strip() + ("" if part.endswith(".") else "."))
    c.drawText(text)
    y -= 30 * mm
    footer()

    def newline(need=16):
        nonlocal y, page
        if y < 22 * mm + need:
            c.showPage()
            page += 1
            header(page)
            footer()
            y = height - 28 * mm

    if getattr(exp, "summary_text", None):
        newline(40)
        c.setFillColor(NAVY)
        c.setFont("Times-Bold", 12)
        c.drawString(margin, y, "AI summary - verify")
        y -= 5 * mm
        c.setFillColor(SLATE)
        c.setFont("Times-Italic", 8)
        for part in NOTICE.split(". "):
            newline(12)
            c.drawString(margin, y, (part.strip() + ("." if not part.endswith(".") else ""))[:110])
            y -= 4 * mm
        c.setFont("Times-Roman", 10)
        blob = exp.summary_text
        while blob:
            newline(12)
            c.drawString(margin, y, blob[:110])
            blob = blob[110:]
            y -= 4.5 * mm
        y -= 4 * mm

    for entry in entries:
        newline(40)
        c.setStrokeColor(GOLD)
        c.setLineWidth(0.6)
        c.line(margin, y + 3 * mm, width - margin, y + 3 * mm)
        y -= 6 * mm
        c.setFillColor(NAVY)
        c.setFont("Times-Bold", 11)
        c.drawString(margin, y, f"{entry.entry_type}  ·  {entry.status}")
        y -= 5 * mm
        c.setFillColor(SLATE)
        c.setFont("Times-Roman", 9)
        author = entry.author.full_name if entry.author else "-"
        c.drawString(margin, y, f"{format_ist(entry.occurred_at)}   {author}   {entry.place or '-'}")
        y -= 6 * mm
        c.setFont("Times-Roman", 10)
        body = (entry.body or "").splitlines() or [""]
        for line in body:
            while line:
                chunk = line[:110]
                line = line[110:]
                newline(12)
                c.drawString(margin, y, chunk)
                y -= 4.5 * mm
        y -= 3 * mm

    c.save()
    key = f"diary/{exp.uuid}.pdf"
    generated_files.put(buf.getvalue(), key)
    return key


def render_court_pdf(doc_row, ctx):
    from reportlab.lib.enums import TA_JUSTIFY
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.platypus import (
        HRFlowable,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    from app.services.docx_service import _body_block

    buf = BytesIO()
    width, height = A4
    margin = 18 * mm

    def chrome(canv, _doc):
        canv.saveState()
        canv.setFillColor(NAVY)
        canv.rect(0, height - 14 * mm, width, 14 * mm, fill=1, stroke=0)
        canv.setFillColor(GOLD)
        canv.rect(0, height - 15.5 * mm, width, 1.5 * mm, fill=1, stroke=0)
        canv.setFillColor(HexColor("#FFFFFF"))
        canv.setFont("Times-Bold", 10)
        canv.drawString(margin, height - 10 * mm, "CrimeGPT  ·  Draft assistance")
        canv.setFont("Times-Roman", 9)
        canv.drawRightString(width - margin, height - 10 * mm, str(_doc.page))
        canv.setFillColor(MUTED)
        canv.setFont("Times-Roman", 8)
        canv.drawString(margin, 10 * mm, "Officer remains responsible for statutory accuracy.")
        if ctx.get("is_incomplete"):
            canv.saveState()
            canv.setFillColor(Color(0.48, 0.12, 0.17, alpha=0.12))
            canv.setFont("Times-Bold", 42)
            canv.translate(width / 2, height / 2)
            canv.rotate(38)
            canv.drawCentredString(0, 0, "DRAFT-INCOMPLETE")
            canv.restoreState()
        canv.restoreState()

    styles = getSampleStyleSheet()
    title = ParagraphStyle("DocTitle", parent=styles["Heading1"], fontName="Times-Bold", textColor=NAVY, fontSize=14, spaceAfter=8)
    body = ParagraphStyle("DocBody", parent=styles["Normal"], fontName="Times-Roman", fontSize=11, leading=15, textColor=SLATE, alignment=TA_JUSTIFY)
    small = ParagraphStyle("DocSmall", parent=styles["Normal"], fontName="Times-Italic", fontSize=8, textColor=MUTED, leading=11)
    story = []
    story.append(Paragraph(ctx.get("station_name") or "CrimeGPT", title))
    if ctx.get("letterhead_2"):
        story.append(Paragraph(ctx["letterhead_2"], body))
    if ctx.get("letterhead_3"):
        story.append(Paragraph(ctx["letterhead_3"], body))
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph(ctx.get("doc_title") or "", title))
    story.append(HRFlowable(width="100%", thickness=0.6, color=GOLD, spaceAfter=6))
    story.append(Paragraph(ctx.get("disclaimer") or "", small))
    story.append(Paragraph(ctx.get("notice") or "", small))
    story.append(Spacer(1, 3 * mm))
    for line in _body_block(ctx).splitlines():
        story.append(Paragraph(line.replace("&", "&amp;").replace("<", "&lt;"), body))
        story.append(Spacer(1, 1.5 * mm))
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=margin,
        rightMargin=margin,
        topMargin=22 * mm,
        bottomMargin=18 * mm,
        title=ctx.get("doc_title") or "CrimeGPT",
    )
    doc.build(story, onFirstPage=chrome, onLaterPages=chrome)
    key = f"docs/{doc_row.uuid}.pdf"
    generated_files.put(buf.getvalue(), key)
    return key
