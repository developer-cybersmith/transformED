"""Generate a PDF: TransformED AI — Customer-Centric Improvement Report."""

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    HRFlowable,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

REPO = Path(__file__).parent.parent
PDF_PATH = REPO / "docs" / "customer-centric-improvements-2026-08-26.pdf"

# ── Colour palette ──────────────────────────────────────────────────────────
BRAND_BLUE   = colors.HexColor("#1E3A5F")
BRAND_TEAL   = colors.HexColor("#0D7377")
ACCENT_GREEN = colors.HexColor("#2E7D32")
ACCENT_RED   = colors.HexColor("#C62828")
ACCENT_AMBER = colors.HexColor("#E65100")
BG_LIGHT     = colors.HexColor("#F5F7FA")
BG_HEADER    = colors.HexColor("#1E3A5F")
TABLE_STRIPE = colors.HexColor("#EEF2F7")
RULE_COLOR   = colors.HexColor("#CBD5E0")
TEXT_DARK    = colors.HexColor("#1A202C")
TEXT_MUTED   = colors.HexColor("#4A5568")

# ── Styles ───────────────────────────────────────────────────────────────────
base = getSampleStyleSheet()

def ms(name, parent="Normal", **kw):
    return ParagraphStyle(name, parent=base[parent], **kw)

S = {
    "doc_title": ms("DocTitle", "Title",
        fontSize=22, textColor=BRAND_BLUE, spaceAfter=4,
        fontName="Helvetica-Bold", alignment=TA_LEFT),
    "subtitle": ms("Subtitle",
        fontSize=11, textColor=BRAND_TEAL, spaceAfter=2,
        fontName="Helvetica-Bold", alignment=TA_LEFT),
    "meta": ms("Meta",
        fontSize=8.5, textColor=TEXT_MUTED,
        fontName="Helvetica", spaceAfter=2, leading=13),
    "intro": ms("Intro",
        fontSize=10, textColor=TEXT_DARK,
        fontName="Helvetica", leading=16, spaceAfter=8, alignment=TA_JUSTIFY),
    "h2": ms("H2",
        fontSize=13, textColor=BRAND_BLUE,
        fontName="Helvetica-Bold", spaceBefore=14, spaceAfter=5),
    "finding_label": ms("FindingLabel",
        fontSize=8.5, textColor=colors.white,
        fontName="Helvetica-Bold", leading=12, alignment=TA_CENTER),
    "finding_title": ms("FindingTitle",
        fontSize=12, textColor=BRAND_BLUE,
        fontName="Helvetica-Bold", spaceBefore=2, spaceAfter=4),
    "section_tag": ms("SectionTag",
        fontSize=8, textColor=TEXT_MUTED,
        fontName="Helvetica-Bold", spaceAfter=2, spaceBefore=8),
    "body": ms("Body",
        fontSize=9.5, textColor=TEXT_DARK,
        fontName="Helvetica", leading=15, spaceAfter=5, alignment=TA_JUSTIFY),
    "fix_box_title": ms("FixBoxTitle",
        fontSize=9.5, textColor=ACCENT_GREEN,
        fontName="Helvetica-Bold", leading=15, spaceAfter=3,
        backColor=colors.HexColor("#E8F5E9"),
        borderPadding=(8, 10, 2, 10), borderColor=ACCENT_GREEN, borderWidth=1),
    "fix_box_body": ms("FixBoxBody",
        fontSize=9.5, textColor=colors.HexColor("#1B5E20"),
        fontName="Helvetica", leading=15, spaceAfter=8,
        backColor=colors.HexColor("#E8F5E9"),
        borderPadding=(2, 10, 8, 10), borderColor=ACCENT_GREEN, borderWidth=1),
    "impact_high": ms("ImpactH",
        fontSize=8, textColor=ACCENT_RED,
        fontName="Helvetica-Bold", leading=11),
    "impact_med": ms("ImpactM",
        fontSize=8, textColor=ACCENT_AMBER,
        fontName="Helvetica-Bold", leading=11),
    "effort_low": ms("EffortL",
        fontSize=8, textColor=ACCENT_GREEN,
        fontName="Helvetica-Bold", leading=11),
    "effort_high": ms("EffortH",
        fontSize=8, textColor=ACCENT_RED,
        fontName="Helvetica-Bold", leading=11),
    "table_header": ms("TH",
        fontSize=8.5, textColor=colors.white,
        fontName="Helvetica-Bold", leading=12, alignment=TA_CENTER),
    "table_cell": ms("TD",
        fontSize=8.5, textColor=TEXT_DARK,
        fontName="Helvetica", leading=12),
    "table_cell_center": ms("TDC",
        fontSize=8.5, textColor=TEXT_DARK,
        fontName="Helvetica", leading=12, alignment=TA_CENTER),
    "footer_note": ms("FooterNote",
        fontSize=8.5, textColor=TEXT_MUTED,
        fontName="Helvetica-Oblique", leading=13, spaceAfter=4),
}

# ── Table style ──────────────────────────────────────────────────────────────
def base_table_style(header_rows=1):
    return TableStyle([
        ("BACKGROUND",    (0, 0), (-1, header_rows - 1), BG_HEADER),
        ("TEXTCOLOR",     (0, 0), (-1, header_rows - 1), colors.white),
        ("FONTNAME",      (0, 0), (-1, header_rows - 1), "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1, header_rows - 1), 8.5),
        ("ALIGN",         (0, 0), (-1, header_rows - 1), "CENTER"),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING",   (0, 0), (-1, -1), 6),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
        ("ROWBACKGROUNDS",(0, header_rows), (-1, -1), [colors.white, TABLE_STRIPE]),
        ("GRID",          (0, 0), (-1, -1), 0.4, RULE_COLOR),
        ("FONTNAME",      (0, header_rows), (-1, -1), "Helvetica"),
        ("FONTSIZE",      (0, header_rows), (-1, -1), 8.5),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
    ])

# ── Page header / footer ─────────────────────────────────────────────────────
def on_page(canvas, doc):
    canvas.saveState()
    w, h = A4
    canvas.setFillColor(BRAND_BLUE)
    canvas.rect(0, h - 1.1 * cm, w, 1.1 * cm, fill=True, stroke=False)
    canvas.setFillColor(colors.white)
    canvas.setFont("Helvetica-Bold", 9)
    canvas.drawString(1.8 * cm, h - 0.72 * cm,
                      "TransformED AI — Customer-Centric Improvement Report")
    canvas.setFont("Helvetica", 8)
    canvas.drawRightString(w - 1.8 * cm, h - 0.72 * cm, "2026-08-26")
    canvas.setFillColor(RULE_COLOR)
    canvas.rect(0, 0, w, 0.85 * cm, fill=True, stroke=False)
    canvas.setFillColor(TEXT_MUTED)
    canvas.setFont("Helvetica", 7.5)
    canvas.drawString(1.8 * cm, 0.3 * cm,
                      "INTERNAL — Product & Engineering")
    canvas.drawRightString(w - 1.8 * cm, 0.3 * cm, f"Page {doc.page}")
    canvas.restoreState()

# ── Helpers ───────────────────────────────────────────────────────────────────
def rule(story):
    story.append(HRFlowable(width="100%", thickness=0.5,
                            color=RULE_COLOR, spaceAfter=4))

def b(text):
    return f"<b>{text}</b>"

def p(text, style="body"):
    return Paragraph(text, S[style])

FINDING_BG = [
    colors.HexColor("#1E3A5F"),
    colors.HexColor("#0D5F6B"),
    colors.HexColor("#1B4D3E"),
    colors.HexColor("#5F3100"),
    colors.HexColor("#3D1A5F"),
    colors.HexColor("#5F1A1A"),
    colors.HexColor("#1A3D5F"),
    colors.HexColor("#3D4A1A"),
    colors.HexColor("#5F2D00"),
    colors.HexColor("#1A5F3D"),
]

def finding_block(story, number, title, effort, impact, problem, fix):
    """Render one finding card."""
    pw = A4[0] - 3.6 * cm
    bg = FINDING_BG[(number - 1) % len(FINDING_BG)]

    # Number pill + title row
    badge = Table(
        [[Paragraph(f"#{number}", S["finding_label"]),
          Paragraph(title, S["finding_title"])]],
        colWidths=[1.1 * cm, pw - 1.1 * cm],
    )
    badge.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (0, 0), bg),
        ("BACKGROUND",    (1, 0), (1, 0), colors.HexColor("#EBF0F8")),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING",   (0, 0), (-1, -1), 6),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
        ("LINEBELOW",     (0, 0), (-1, 0), 0.5, RULE_COLOR),
    ]))
    story.append(badge)

    # Effort / Impact tags
    tag_color = ACCENT_RED if impact == "High" else ACCENT_AMBER
    effort_color = ACCENT_GREEN if effort == "Low" else (ACCENT_AMBER if effort == "Medium" else ACCENT_RED)
    tags = Table(
        [[Paragraph(f"Impact: {impact}", S["table_cell"]),
          Paragraph(f"Effort: {effort}", S["table_cell"])]],
        colWidths=[pw / 2, pw / 2],
    )
    tags.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (0, 0), colors.HexColor("#FDECEC") if impact == "High" else colors.HexColor("#FFF3E0")),
        ("BACKGROUND",    (1, 0), (1, 0), colors.HexColor("#E8F5E9") if effort == "Low" else (colors.HexColor("#FFF3E0") if effort == "Medium" else colors.HexColor("#FDECEC"))),
        ("TEXTCOLOR",     (0, 0), (0, 0), tag_color),
        ("TEXTCOLOR",     (1, 0), (1, 0), effort_color),
        ("FONTNAME",      (0, 0), (-1, -1), "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1, -1), 8),
        ("TOPPADDING",    (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING",   (0, 0), (-1, -1), 8),
        ("GRID",          (0, 0), (-1, -1), 0.3, RULE_COLOR),
    ]))
    story.append(tags)

    # Problem description
    story.append(Spacer(1, 0.15 * cm))
    story.append(p("<b>Problem</b>", "section_tag"))
    story.append(p(problem))

    # Fix box
    story.append(p("<b>Fix</b>", "section_tag"))
    story.append(Paragraph("<b>Recommended Fix</b>", S["fix_box_title"]))
    story.append(Paragraph(fix, S["fix_box_body"]))
    story.append(Spacer(1, 0.3 * cm))


# ── Report data ───────────────────────────────────────────────────────────────
FINDINGS = [
    {
        "title": "The Wait Problem — No Notification When Lesson Is Ready",
        "effort": "Low",
        "impact": "High",
        "problem": (
            "Lesson generation takes 5–15 minutes. There is no email, SMS, or push "
            "notification when the lesson is ready, and the progress screen does not "
            "show named stages — only raw pipeline node names. A student who uploads "
            "their chapter and watches a spinner for 15 minutes will not return. "
            "The current WebSocket connection requires the tab to stay open, which is "
            "an unrealistic expectation on mobile devices."
        ),
        "fix": (
            "Send an email (and SMS for Indian users) when the lesson is ready. "
            "Replace the raw node-name progress display with named stages: "
            "'Analysing chapter... Building slides... Generating audio...' "
            "Allow the student to close the tab and return — the lesson should be "
            "waiting for them on the dashboard."
        ),
    },
    {
        "title": "Free Tier Too Restrictive to Demonstrate Value",
        "effort": "Low",
        "impact": "High",
        "problem": (
            "The free tier offers 1 chapter per month with no TTS, no teach-back, "
            "and no tutor Q&A. A new user experiences a silent, text-only lesson "
            "with no interaction — the least compelling version of the product. "
            "They never see the voice narration, quizzes, or AI interventions that "
            "differentiate TransformED from a plain PDF reader. Conversion requires "
            "the student to pay before they understand what they are paying for."
        ),
        "fix": (
            "Offer a 14-day full-access trial on sign-up before any tier gate "
            "activates. The marginal cost of one trial lesson is well under $3.00 — "
            "treat it as acquisition cost, not a giveaway. After the trial, show "
            "a clear side-by-side of what the student had vs. what they are losing, "
            "with a single upgrade CTA."
        ),
    },
    {
        "title": "Attention Monitoring Value Exchange Is Invisible to Students",
        "effort": "Low",
        "impact": "High",
        "problem": (
            "The consent modal asks for camera access, but students are not told "
            "what they get in return. The Composite Engagement Score (CES) is "
            "computed silently; the privacy guarantee ('video never leaves your "
            "device') is not surfaced on the consent screen. Students who decline "
            "consent receive no explanation of what they are missing, and students "
            "who grant it see no evidence the feature is helping them."
        ),
        "fix": (
            "On the consent screen, lead with the student benefit: 'We use your "
            "camera to notice when you are tired or distracted — so we can help "
            "before you fall behind.' Display the privacy guarantee prominently "
            "on the same screen, not in a linked policy. Show a real-time "
            "green/amber/red engagement indicator during the lesson with a one-line "
            "tooltip explaining what the colour means."
        ),
    },
    {
        "title": "Teach-Back Has No Visible Payoff for Students",
        "effort": "Medium",
        "impact": "High",
        "problem": (
            "Teach-back is correctly made optional and never gated on score. "
            "However, after the student types their explanation and submits, "
            "there is no visible feedback response. The scoring is computed "
            "and stored, but the student sees nothing meaningful. Teach-back "
            "currently functions as a black-box input form, which removes all "
            "motivation to engage with it seriously."
        ),
        "fix": (
            "After teach-back submission, show a brief AI-generated response: "
            "'Good — you captured the core idea. One thing to add: [X].' "
            "This closes the feedback loop and gives the student an immediate "
            "learning signal. The response can be generated by the same mini "
            "model used for scoring (gpt-4o-mini) and cached per submission — "
            "it does not need to be real-time."
        ),
    },
    {
        "title": "Intervention Messages Feel Like Interruptions, Not Support",
        "effort": "Low",
        "impact": "Medium",
        "problem": (
            "Intervention messages are pre-generated at lesson build time (not "
            "dynamic), capped at 3 per session, and triggered entirely by a "
            "formula the student never sees. Students cannot adjust their own "
            "sensitivity, cannot distinguish between dismissing and engaging with "
            "an intervention, and receive no explanation of why one fired. "
            "The feature risks feeling intrusive rather than supportive."
        ),
        "fix": (
            "Add an Intervention Style preference in settings with three options: "
            "'Check in with me often', 'Sometimes', 'Only when I am really stuck'. "
            "This maps to CES threshold tuning and makes the feature feel like "
            "personalisation rather than surveillance. Log which option a student "
            "chooses as a signal for the Learner DNA profile."
        ),
    },
    {
        "title": "Learner DNA Is Descriptive But Not Actionable",
        "effort": "Low",
        "impact": "Medium",
        "problem": (
            "The Learner DNA profile correctly avoids clinical scores and uses "
            "descriptive language. However, 'descriptive profile only' with no "
            "next steps is a curiosity, not a coaching tool. A student who reads "
            "their profile learns about themselves but receives no guidance on "
            "what to do differently."
        ),
        "fix": (
            "End every Learner DNA profile with 2–3 specific, personalised study "
            "suggestions derived from the CES history. Example: 'You tend to lose "
            "focus around the 10–12 minute mark — try a 2-minute break at the "
            "midpoint of each segment.' This transforms the profile from a report "
            "card into a coach."
        ),
    },
    {
        "title": "No Student-Facing Progress or Study History",
        "effort": "Medium",
        "impact": "High",
        "problem": (
            "There is no dashboard view showing which chapters a student has "
            "completed, their engagement scores across sessions, or their "
            "progress through a book. Without visible momentum, every session "
            "feels like starting from zero. Students preparing for exams need to "
            "track what they have covered and how well they retained it."
        ),
        "fix": (
            "Add a chapter-progress view per book on the dashboard. Each chapter "
            "shows: completion status, CES score from the last session, and date "
            "last studied. A simple progress bar across the book ('6 of 12 chapters "
            "done') provides the momentum signal. This is one bounded Supabase "
            "query per book and requires no new backend logic."
        ),
    },
    {
        "title": "Failure States Are Invisible to Students",
        "effort": "Low",
        "impact": "High",
        "problem": (
            "Several active failure modes have no defined student-facing UI: "
            "Imagen 4 Fast is confirmed dead (D121), meaning slides currently "
            "have missing images with no notice. The TTS fallback to Browser Speech "
            "degrades voice quality silently. If the $3.00 cost ceiling is hit, "
            "lesson quality downgrades with no warning. Silent degradation breaks "
            "trust permanently — students assume the product is broken."
        ),
        "fix": (
            "Define a explicit UI notice for each degraded state. Examples: "
            "'Some slide images could not be generated — we are working on it.' "
            "/ 'Audio quality has been reduced for this session.' / "
            "'This lesson was generated in economy mode.' "
            "Brief, honest notices turn a trust-breaking moment into a trust-building "
            "one. Each notice should be stored on the lesson record and rendered "
            "by the player, not ad-hoc."
        ),
    },
    {
        "title": "Mobile Experience Is Underprioritised",
        "effort": "High",
        "impact": "High",
        "problem": (
            "Sprint 3 patched 2 broken mobile screens reactively. The custom React "
            "lesson player and MediaPipe attention tracking were designed for "
            "desktop-first. Indian students — the target market — overwhelmingly "
            "study on mobile phones. A product that is hard to use on mobile "
            "cannot achieve its stated goal of reaching that student cohort."
        ),
        "fix": (
            "Schedule a dedicated mobile-first pass before Week 10 launch. "
            "At minimum: player controls sized for thumbs; attention monitoring "
            "gracefully disabled on mobile with a clear explanation of what "
            "the student is missing and why; upload flow tested on mobile Chrome "
            "and Safari. Set a mobile breakpoint budget and add a Playwright "
            "mobile viewport test to CI so regressions are caught automatically."
        ),
    },
    {
        "title": "No Student Content Quality Feedback Loop",
        "effort": "Low",
        "impact": "High",
        "problem": (
            "Students have no way to flag AI-generated content that is wrong, "
            "confusing, or off-topic. A quiz question with an incorrect answer, "
            "or a slide that misrepresents the source material, will immediately "
            "erode trust — and the engineering team will never know unless students "
            "can report it. There is currently no mechanism for this signal to "
            "reach the team."
        ),
        "fix": (
            "Add a 'Report an issue' button (flag icon) on each slide and each "
            "quiz question. Tapping it opens a two-tap flow: select a reason "
            "(Wrong information / Confusing / Off-topic / Other) and submit. "
            "Reports are logged to an admin queue. Zero backend complexity — "
            "one new table row per report. The admin view already exists; "
            "add a reports tab."
        ),
    },
]

SUMMARY_ROWS = [
    ["#", "Finding", "Effort", "Impact"],
    ["1",  "Generation completion notification",          "Low",    "High"],
    ["2",  "14-day full-access trial",                   "Low",    "High"],
    ["3",  "Attention monitoring value explanation",      "Low",    "High"],
    ["4",  "Teach-back feedback response",                "Medium", "High"],
    ["5",  "Intervention sensitivity settings",           "Low",    "Medium"],
    ["6",  "Learner DNA action recommendations",          "Low",    "Medium"],
    ["7",  "Chapter progress dashboard",                  "Medium", "High"],
    ["8",  "Failure state UI notices",                    "Low",    "High"],
    ["9",  "Mobile-first pass",                           "High",   "High"],
    ["10", "Student content quality reporting",           "Low",    "High"],
]


# ── Build ─────────────────────────────────────────────────────────────────────
def build_pdf():
    doc = SimpleDocTemplate(
        str(PDF_PATH),
        pagesize=A4,
        leftMargin=1.8 * cm,
        rightMargin=1.8 * cm,
        topMargin=1.9 * cm,
        bottomMargin=1.4 * cm,
        title="Customer-Centric Improvement Report — TransformED AI",
        author="Product Review — 2026-08-26",
    )

    story = []
    pw = A4[0] - 3.6 * cm

    # ── Cover ─────────────────────────────────────────────────────────────
    story.append(Spacer(1, 0.4 * cm))
    story.append(p("TransformED AI", "doc_title"))
    story.append(p("Customer-Centric Improvement Report", "subtitle"))
    story.append(Spacer(1, 0.15 * cm))
    story.append(p("Date: 2026-08-26  |  Audience: Product & Engineering  |  Sprint: Pre-Launch Review", "meta"))
    story.append(Spacer(1, 0.3 * cm))
    rule(story)
    story.append(Spacer(1, 0.2 * cm))

    intro = (
        "This report documents <b>10 customer-centric gaps</b> identified through a "
        "review of the TransformED AI product specification, sprint reports, CES "
        "lifecycle documentation, and decision log as of August 2026. "
        "Each finding describes a point at which the current product creates "
        "friction, confusion, or a broken feedback loop for the student — and "
        "pairs it with a concrete, scoped fix. "
        "Findings are ordered by the sequence a new student encounters them, "
        "from sign-up through active study. The summary table on page 2 gives "
        "an at-a-glance view of effort vs. impact across all ten."
    )
    story.append(p(intro, "intro"))
    story.append(Spacer(1, 0.3 * cm))

    # ── Summary table ─────────────────────────────────────────────────────
    story.append(p("Summary — All Findings", "h2"))
    rule(story)

    styled_rows = []
    for ri, row in enumerate(SUMMARY_ROWS):
        if ri == 0:
            styled_rows.append([Paragraph(c, S["table_header"]) for c in row])
        else:
            effort = row[2]
            impact = row[3]
            effort_color = (ACCENT_GREEN if effort == "Low"
                            else (ACCENT_AMBER if effort == "Medium" else ACCENT_RED))
            impact_color = ACCENT_RED if impact == "High" else ACCENT_AMBER
            styled_rows.append([
                Paragraph(row[0], S["table_cell_center"]),
                Paragraph(row[1], S["table_cell"]),
                Paragraph(f'<font color="#{effort_color.hexval()[2:]}"><b>{effort}</b></font>',
                           S["table_cell_center"]),
                Paragraph(f'<font color="#{impact_color.hexval()[2:]}"><b>{impact}</b></font>',
                           S["table_cell_center"]),
            ])

    tbl = Table(styled_rows, colWidths=[0.7*cm, pw*0.62, pw*0.19, pw*0.19], repeatRows=1)
    tbl.setStyle(base_table_style(header_rows=1))
    story.append(tbl)
    story.append(Spacer(1, 0.3 * cm))
    story.append(p(
        "<b>Key insight:</b> Seven of the ten fixes are Low effort. The biggest "
        "single gap is that students never see the loop close — they upload, wait, "
        "watch, type, and nothing visible happens in response. Every fix above "
        "addresses one point in that invisible loop.",
        "footer_note",
    ))

    story.append(PageBreak())

    # ── Detailed findings ─────────────────────────────────────────────────
    story.append(p("Detailed Findings &amp; Fixes", "h2"))
    rule(story)
    story.append(Spacer(1, 0.15 * cm))

    for i, f in enumerate(FINDINGS, start=1):
        finding_block(
            story,
            number=i,
            title=f["title"],
            effort=f["effort"],
            impact=f["impact"],
            problem=f["problem"],
            fix=f["fix"],
        )
        if i == 5:
            story.append(PageBreak())

    # ── Closing note ──────────────────────────────────────────────────────
    rule(story)
    story.append(Spacer(1, 0.2 * cm))
    story.append(p(
        "These findings were derived from the product PRD (v1.0 Final, June 2026), "
        "the Decisions Update (June 2026), sprint reports (Sprint 1–3), the CES "
        "Lifecycle &amp; Learner Scenarios specification (August 2026), and the "
        "intervention copy review. No user interviews were conducted — these are "
        "structural gaps in the product design, not usability observations. "
        "A follow-up round of student interviews before Week 10 launch is recommended "
        "to validate which of these gaps causes the highest real-world friction.",
        "footer_note",
    ))

    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    print(f"PDF written -> {PDF_PATH}")


if __name__ == "__main__":
    build_pdf()
