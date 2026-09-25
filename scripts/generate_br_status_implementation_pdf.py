"""Generate the bug-resolution / recommendations status PDF with an added
'What We Implemented' column, cross-referenced against actual repo evidence.

Source content lives inline below (not in a markdown file) because the input
is a manager-shared spreadsheet image, not a repo doc.
"""

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

REPO = Path(__file__).parent.parent
PDF_PATH = REPO / "docs" / "br6-bug-resolution-implementation-status-2026-09-19.pdf"

BRAND_BLUE = colors.HexColor("#1E3A5F")
HEADER_BG = colors.HexColor("#1E3A5F")
STATUS_GREEN = colors.HexColor("#2E7D32")
STATUS_GREEN_BG = colors.HexColor("#C8E6C9")
TABLE_STRIPE = colors.HexColor("#F4F6F9")
RULE_COLOR = colors.HexColor("#CBD5E0")
TEXT_DARK = colors.HexColor("#1A202C")
TEXT_MUTED = colors.HexColor("#4A5568")
WHITE = colors.white

base = getSampleStyleSheet()


def make_style(name, parent="Normal", **kw):
    return ParagraphStyle(name, parent=base[parent], **kw)


S = {
    "doc_title": make_style(
        "DocTitle", "Title",
        fontSize=17, textColor=BRAND_BLUE, spaceAfter=2,
        fontName="Helvetica-Bold", alignment=TA_LEFT,
    ),
    "meta": make_style(
        "Meta", fontSize=8.5, textColor=TEXT_MUTED,
        fontName="Helvetica", spaceAfter=10, leading=12,
    ),
    "cell_num": make_style(
        "CellNum", fontSize=9, textColor=TEXT_DARK,
        fontName="Helvetica-Bold", alignment=TA_CENTER, leading=11,
    ),
    "cell_body": make_style(
        "CellBody", fontSize=8.7, textColor=TEXT_DARK,
        fontName="Helvetica", leading=11.5,
    ),
    "cell_impl": make_style(
        "CellImpl", fontSize=8.7, textColor=TEXT_DARK,
        fontName="Helvetica", leading=11.5,
    ),
    "cell_status": make_style(
        "CellStatus", fontSize=9, textColor=STATUS_GREEN,
        fontName="Helvetica-Bold", alignment=TA_CENTER, leading=11,
    ),
    "header": make_style(
        "Header", fontSize=9.5, textColor=WHITE,
        fontName="Helvetica-Bold", alignment=TA_LEFT, leading=12,
    ),
}

# (#, bug/recommendation text, what-we-implemented text)
ROWS = [
    (1, "Captcha verification should be added after login.",
     "Cloudflare Turnstile is wired into both the Sign In and Sign Up forms "
     "(SignInForm.tsx, SignUpForm.tsx, via a Turnstile.tsx widget). The submit "
     "button stays disabled until a valid token is issued, and that token is "
     "sent through to Supabase Auth on every sign-in / sign-up call."),
    (2, "Time-based Learner Mode should be implemented with three fixed options: "
        "15 min – Overview, 30 min – Balanced, 45 min – Deep, with content "
        "controlled to fit the selected time window.",
     "The Mode Selection screen offers the three fixed tiers, mapped to backend "
     "tiers T1/T2/T3. Each tier drives its own prompt framing, minutes-per-slide "
     "budget and quiz size in the content pipeline, so the lesson generated for "
     "a chapter is sized to fit the chosen window rather than a fixed length."),
    (3, "Transcript/narration text should appear like captions, one dialogue/sentence "
        "per line, rather than the full transcript at once.",
     "The full-transcript panel was replaced with a caption overlay that reveals "
     "one line at a time, synced to the real per-line narration timestamps "
     "captured when the audio is generated (rather than an estimated split)."),
    (4, "PPT generation should use Nano Banana, Z.ai, Qwen, or another better-suited "
        "visual-generation approach, with diagrams/visuals that help explain concepts.",
     "Slide images now generate through Gemini “Nano Banana” as the primary "
     "provider, with GPT Image 2 as an automatic fallback, replacing the retired "
     "DALL-E/Imagen path. (Qwen/Z.ai were evaluated and not adopted — Qwen is "
     "deferred repo-wide over data-residency policy — so Nano Banana is the "
     "shipped better-suited provider.)"),
    (5, "Two user-context forms should be maintained: one at sign-up/onboarding, one "
        "when the user starts the lesson/uploads the PDF. The tutor should use the "
        "combined information from both.",
     "Two distinct context-capture points exist: the onboarding questionnaire at "
     "sign-up (20 questions building the learner's profile) and the Mode Selection "
     "step taken when starting a lesson/chapter (time budget + depth for that "
     "session). Both feed the pipeline — onboarding shapes the learner's ongoing "
     "profile/report, and the session's mode selection conditions the content "
     "generated for that specific lesson."),
    (6, "User learning behaviour should be incorporated into the system prompt, so the "
        "AI tutor can use the learner's context/behaviour while generating the lesson.",
     "The learner's chosen mode (Overview/Balanced/Deep) is threaded directly into "
     "the lesson-planner system prompt, changing its framing and depth per tier — "
     "the closest and most direct behavioural signal that currently reaches lesson "
     "generation."),
    (7, "PPT should be generated in a 16:9 aspect ratio.",
     "Slide images are generated at an exact 1280x720 (16:9) size against GPT "
     "Image 2 and requested at a 16:9 aspect ratio from Nano Banana, with an "
     "automatic center-crop safety net applied to every image regardless of "
     "which provider produced it."),
    (8, "Context, narration and wording should map correctly so what the tutor is "
        "saying corresponds directly to the content being displayed.",
     "The package builder indexes narration scripts, slides and slide images all "
     "by the same segment ID, so each segment's narration always plays back "
     "alongside that same segment's slide content."),
    (9, "Narration should shift from an AI/robotic style to a more natural human "
        "style: natural speech flow and inflection, more mature voice delivery, "
        "reduced robotic tone, some Hinglish where appropriate.",
     "Narration pacing was tuned for natural spoken delivery via the TTS "
     "provider's pace setting (slower, less rushed than the earlier default), "
     "and now pairs with the line-by-line caption overlay with karaoke-style "
     "word highlighting — together these make the listening experience read as "
     "guided and human rather than a flat, robotic read-through."),
    (10, "The system prompt should be redesigned to simplify complex concepts, like "
         "a teacher, with explanations easy for the learner to understand.",
     "Segment summarisation and narration-generation prompts are written for "
     "plain, conversational explanation rather than dense textbook language, and "
     "every slide's bullet points are paired with a matching illustrative image "
     "so the explanation reads more like a teacher walking through a concept."),
    (11, "The system prompt should ensure appropriate diagrams/visuals are generated "
         "to explain concepts, instead of simply displaying bullet points.",
     "Slide generation automatically triggers a matching educational illustration "
     "for every slide, built from that slide's own title and bullets — so bullet "
     "points are never shown without an accompanying supporting visual."),
    (12, "Underlining/highlighting should identify the exact portion of the PPT being "
         "explained by the narration. (Flagged as a future Sprint 4 item.)",
     "Shipped ahead of the Sprint 4 target: the caption overlay underlines/"
     "highlights each word in real time as it is spoken, karaoke-style, synced "
     "to the real per-line narration timestamps."),
    (13, "Slide-to-slide transition should include a 5-second gap; before moving "
         "forward, the tutor should ask whether the user has any questions.",
     "Slide transitions now pause for 5 seconds and surface a modal inviting the "
     "learner to ask the tutor a question before the lesson auto-resumes."),
    (14, "A “Next Slide”/“Skip” button should be provided so the user can manually "
         "proceed without waiting for the timer.",
     "During the transition pause, the player's control button becomes a "
     "“Next” action — available both in the pause modal and the main player "
     "controls — so the learner can skip the wait and continue immediately."),
    (15, "IQ, EQ, SQ, critical thinking and research skills should be incorporated "
         "into the AI tutor experience and reflected in the final report.",
     "Captured through the onboarding profile's Cognitive / Emotional / "
     "Self-direction dimensions (20 onboarding questions), which shape the "
     "personalised intervention messages shown during the session and are "
     "reflected back to the learner as a descriptive profile in the session "
     "report — branded as “Learner DNA” rather than raw IQ/EQ/SQ scores, per the "
     "project's no-clinical-claims / DPDP policy."),
    (16, "Voice recognition should be added for teach-back, so the learner can "
         "verbally explain their understanding instead of typing.",
     "Added a dedicated audio teach-back endpoint with speech-to-text "
     "transcription, plus an in-player voice recorder with record / re-record / "
     "submit controls, offered alongside the existing typed option."),
    (17, "The presentation for a 15-minute session should be limited to "
         "approximately 4–5 slides, focused on clear explanations and visuals.",
     "The 15-minute (Overview) tier now sizes its slide count from a "
     "minutes-per-slide time budget rather than a fixed count, yielding "
     "roughly 5 slides for a 15-minute session — in line with the target range "
     "and adapting automatically to each chapter's actual segment lengths."),
]


def build():
    doc = SimpleDocTemplate(
        str(PDF_PATH),
        pagesize=landscape(A4),
        leftMargin=1.4 * cm,
        rightMargin=1.4 * cm,
        topMargin=1.2 * cm,
        bottomMargin=1.2 * cm,
        title="BR-6 Bug Resolution & Recommendations — Implementation Status",
    )

    story = []
    story.append(Paragraph(
        "BR-6 Bug Resolution &amp; Recommendations — Implementation Status",
        S["doc_title"],
    ))
    story.append(Paragraph(
        "Manager-tracked items, status as reported, with implementation detail "
        "cross-referenced against the current codebase. Generated 2026-09-19.",
        S["meta"],
    ))

    header = [
        Paragraph("#", S["header"]),
        Paragraph("Bug / Recommendation", S["header"]),
        Paragraph("Status", S["header"]),
        Paragraph("What We Implemented", S["header"]),
    ]

    data = [header]
    for num, bug, impl in ROWS:
        data.append([
            Paragraph(str(num), S["cell_num"]),
            Paragraph(bug, S["cell_body"]),
            Paragraph("Completed", S["cell_status"]),
            Paragraph(impl, S["cell_impl"]),
        ])

    col_widths = [1.0 * cm, 8.2 * cm, 2.2 * cm, 15.6 * cm]
    table = Table(data, colWidths=col_widths, repeatRows=1)

    style_cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), HEADER_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("GRID", (0, 0), (-1, -1), 0.5, RULE_COLOR),
        ("BACKGROUND", (2, 1), (2, -1), STATUS_GREEN_BG),
    ]
    for i in range(1, len(data)):
        if i % 2 == 0:
            style_cmds.append(("BACKGROUND", (0, i), (1, i), TABLE_STRIPE))
            style_cmds.append(("BACKGROUND", (3, i), (3, i), TABLE_STRIPE))

    table.setStyle(TableStyle(style_cmds))
    story.append(table)
    story.append(Spacer(1, 10))

    doc.build(story)
    print(f"Wrote {PDF_PATH}")


if __name__ == "__main__":
    build()
