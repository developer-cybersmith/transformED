"""Generate a PDF for the merged Sprint 4 whole-team manager report."""

import re
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

# ── Paths ──────────────────────────────────────────────────────────────────
REPO = Path(__file__).parent.parent
MD_PATH = REPO / "docs" / "sprint4-full-team-report-2026-09-07.md"
PDF_PATH = REPO / "docs" / "sprint4-full-team-report-2026-09-07.pdf"

# ── Colour palette ─────────────────────────────────────────────────────────
BRAND_BLUE   = colors.HexColor("#1E3A5F")
BRAND_TEAL   = colors.HexColor("#0D7377")
ACCENT_GREEN = colors.HexColor("#2E7D32")
ACCENT_RED   = colors.HexColor("#C62828")
ACCENT_AMBER = colors.HexColor("#E65100")
BG_HEADER    = colors.HexColor("#1E3A5F")
TABLE_STRIPE = colors.HexColor("#EEF2F7")
RULE_COLOR   = colors.HexColor("#CBD5E0")
TEXT_DARK    = colors.HexColor("#1A202C")
TEXT_MUTED   = colors.HexColor("#4A5568")

# ── Styles ─────────────────────────────────────────────────────────────────
base = getSampleStyleSheet()

def make_style(name, parent="Normal", **kw):
    return ParagraphStyle(name, parent=base[parent], **kw)

S = {
    "doc_title": make_style(
        "DocTitle", "Title",
        fontSize=19, textColor=BRAND_BLUE, spaceAfter=4,
        fontName="Helvetica-Bold", alignment=TA_LEFT,
    ),
    "meta": make_style(
        "Meta", fontSize=8.5, textColor=TEXT_MUTED,
        fontName="Helvetica", spaceAfter=2, leading=13,
    ),
    "h2": make_style(
        "H2", fontSize=13, textColor=BRAND_BLUE,
        fontName="Helvetica-Bold", spaceBefore=14, spaceAfter=5,
    ),
    "h3": make_style(
        "H3", fontSize=11, textColor=BRAND_TEAL,
        fontName="Helvetica-Bold", spaceBefore=10, spaceAfter=4,
    ),
    "body": make_style(
        "Body", fontSize=9.5, textColor=TEXT_DARK,
        fontName="Helvetica", leading=15, spaceAfter=6,
    ),
    "body_muted": make_style(
        "BodyMuted", fontSize=8.5, textColor=TEXT_MUTED,
        fontName="Helvetica-Oblique", leading=13, spaceAfter=4,
    ),
    "bullet": make_style(
        "Bullet", fontSize=9.5, textColor=TEXT_DARK,
        fontName="Helvetica", leading=14, spaceAfter=3,
        leftIndent=16, firstLineIndent=-10,
    ),
    "footer": make_style(
        "Footer", fontSize=7.5, textColor=TEXT_MUTED,
        fontName="Helvetica-Oblique", alignment=TA_CENTER,
    ),
    "table_header": make_style(
        "TH", fontSize=8, textColor=colors.white,
        fontName="Helvetica-Bold", leading=11, alignment=TA_CENTER,
    ),
    "table_cell": make_style(
        "TD", fontSize=8, textColor=TEXT_DARK,
        fontName="Helvetica", leading=11,
    ),
}

# ── Table style helpers ─────────────────────────────────────────────────────
def base_table_style(header_rows=1):
    return TableStyle([
        ("BACKGROUND",  (0, 0), (-1, header_rows - 1), BG_HEADER),
        ("TEXTCOLOR",   (0, 0), (-1, header_rows - 1), colors.white),
        ("FONTNAME",    (0, 0), (-1, header_rows - 1), "Helvetica-Bold"),
        ("FONTSIZE",    (0, 0), (-1, header_rows - 1), 8),
        ("ALIGN",       (0, 0), (-1, header_rows - 1), "CENTER"),
        ("TOPPADDING",  (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("ROWBACKGROUNDS", (0, header_rows), (-1, -1),
         [colors.white, TABLE_STRIPE]),
        ("GRID",        (0, 0), (-1, -1), 0.4, RULE_COLOR),
        ("FONTNAME",    (0, header_rows), (-1, -1), "Helvetica"),
        ("FONTSIZE",    (0, header_rows), (-1, -1), 8),
        ("VALIGN",      (0, 0), (-1, -1), "MIDDLE"),
    ])

# ── Inline markdown → ReportLab XML ────────────────────────────────────────
def md_inline(text: str) -> str:
    """Convert inline markdown marks to ReportLab XML tags."""
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    text = re.sub(r"~~(.+?)~~", r'<font color="#9CA3AF"><strike>\1</strike></font>', text)
    text = re.sub(r"\*\*\*(.+?)\*\*\*", r"<b><i>\1</i></b>", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"\*(.+?)\*", r"<i>\1</i>", text)
    text = re.sub(r"`([^`]+)`",
                  r'<font name="Courier" color="#0D7377">\1</font>', text)
    text = text.replace("✅", '<font color="#2E7D32">✅</font>')
    text = text.replace("❌", '<font color="#C62828">❌</font>')
    text = text.replace("⚠️", '<font color="#E65100">⚠️</font>')
    text = text.replace("⏳", '<font color="#E65100">⏳</font>')
    return text

# ── Table parser ────────────────────────────────────────────────────────────
def parse_md_table(lines: list[str]) -> list[list[str]]:
    rows = []
    for line in lines:
        if re.match(r"^\s*\|[-: |]+\|\s*$", line):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        rows.append(cells)
    return rows

def build_table(rows: list[list[str]], col_widths=None) -> Table:
    page_w = A4[0] - 3.2 * cm
    if col_widths is None:
        n = len(rows[0]) if rows else 1
        col_widths = [page_w / n] * n

    styled_rows = []
    for ri, row in enumerate(rows):
        styled_row = []
        for ci, cell in enumerate(row):
            style = S["table_header"] if ri == 0 else S["table_cell"]
            styled_row.append(Paragraph(md_inline(cell), style))
        styled_rows.append(styled_row)

    t = Table(styled_rows, colWidths=col_widths, repeatRows=1)
    t.setStyle(base_table_style(header_rows=1))
    return t

def ol_item(n, text):
    return Paragraph(f'<b>{n}.</b> {md_inline(text)}', S["bullet"])

# ── Page template with header/footer ──────────────────────────────────────
def on_page(canvas, doc):
    canvas.saveState()
    w, h = A4
    canvas.setFillColor(BRAND_BLUE)
    canvas.rect(0, h - 1.1 * cm, w, 1.1 * cm, fill=True, stroke=False)
    canvas.setFillColor(colors.white)
    canvas.setFont("Helvetica-Bold", 9)
    canvas.drawString(1.6 * cm, h - 0.72 * cm,
                      "TransformED AI — Sprint 4: Whole-Team Report")
    canvas.setFont("Helvetica", 8)
    canvas.drawRightString(w - 1.6 * cm, h - 0.72 * cm, "2026-09-07")
    canvas.setFillColor(RULE_COLOR)
    canvas.rect(0, 0, w, 0.85 * cm, fill=True, stroke=False)
    canvas.setFillColor(TEXT_MUTED)
    canvas.setFont("Helvetica", 7.5)
    canvas.drawString(1.6 * cm, 0.3 * cm, "CONFIDENTIAL — For Engineering Manager only")
    canvas.drawRightString(w - 1.6 * cm, 0.3 * cm, f"Page {doc.page}")
    canvas.restoreState()

# ── Column width guesses by column count ───────────────────────────────────
def col_widths_for(n_cols, pw):
    if n_cols == 2:
        return [pw * 0.35, pw * 0.65]
    if n_cols == 3:
        return [pw * 0.28, pw * 0.52, pw * 0.20]
    if n_cols == 4:
        return [pw * 0.22, pw * 0.46, pw * 0.14, pw * 0.18]
    if n_cols == 5:
        return [pw * 0.05, pw * 0.35, pw * 0.14, pw * 0.14, pw * 0.32]
    return [pw / n_cols] * n_cols

# ── Main builder ────────────────────────────────────────────────────────────
def build_pdf(md_path: Path, pdf_path: Path):
    text = md_path.read_text(encoding="utf-8")
    lines = text.splitlines()

    doc = SimpleDocTemplate(
        str(pdf_path),
        pagesize=A4,
        leftMargin=1.6 * cm,
        rightMargin=1.6 * cm,
        topMargin=1.8 * cm,
        bottomMargin=1.4 * cm,
        title="Sprint 4 — Whole Team Report",
        author="TransformED AI",
    )

    story = []
    i = 0

    while i < len(lines):
        line = lines[i]

        if line.startswith("# "):
            story.append(Spacer(1, 0.3 * cm))
            story.append(Paragraph(md_inline(line[2:]), S["doc_title"]))
            i += 1
            continue

        if line.startswith("**For:**") or line.startswith("**Sprint:**") \
                or line.startswith("**Report date:**") or line.startswith("**Prepared by:**") \
                or line.startswith("**Scope:**"):
            story.append(Paragraph(md_inline(line), S["meta"]))
            i += 1
            continue

        if line.startswith("## "):
            story.append(HRFlowable(width="100%", thickness=0.5,
                                    color=RULE_COLOR, spaceAfter=2))
            story.append(Paragraph(md_inline(line[3:]), S["h2"]))
            i += 1
            continue

        if line.startswith("### "):
            story.append(Paragraph(md_inline(line[4:]), S["h3"]))
            i += 1
            continue

        if line.strip() == "---":
            story.append(Spacer(1, 0.15 * cm))
            story.append(HRFlowable(width="100%", thickness=0.5,
                                    color=RULE_COLOR, spaceAfter=4))
            i += 1
            continue

        if line.startswith("|"):
            table_lines = []
            while i < len(lines) and lines[i].startswith("|"):
                table_lines.append(lines[i])
                i += 1
            rows = parse_md_table(table_lines)
            if rows:
                n_cols = len(rows[0])
                pw = A4[0] - 3.2 * cm
                cw = col_widths_for(n_cols, pw)
                story.append(build_table(rows, cw))
                story.append(Spacer(1, 0.25 * cm))
            continue

        if line.startswith("- "):
            bullet_text = line[2:].strip()
            story.append(Paragraph(
                f'<bullet>&bull;</bullet> {md_inline(bullet_text)}',
                S["bullet"]
            ))
            i += 1
            continue

        m = re.match(r"^(\d+)\. (.+)$", line)
        if m:
            story.append(ol_item(m.group(1), m.group(2)))
            i += 1
            continue

        stripped = line.strip()

        if stripped.startswith("*") and stripped.endswith("*") and not stripped.startswith("**"):
            story.append(Paragraph(md_inline(stripped), S["body_muted"]))
            i += 1
            continue

        if not stripped:
            story.append(Spacer(1, 0.15 * cm))
            i += 1
            continue

        story.append(Paragraph(md_inline(stripped), S["body"]))
        i += 1

    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    print(f"PDF written -> {pdf_path}")


if __name__ == "__main__":
    build_pdf(MD_PATH, PDF_PATH)
