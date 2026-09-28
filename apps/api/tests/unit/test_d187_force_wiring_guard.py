"""Guard: D187 — force:true must be wired through the frontend generate-lesson call chain."""

from __future__ import annotations

from pathlib import Path

_WEB = Path(__file__).resolve().parents[4] / "apps" / "web" / "src"

_SERVICE = (_WEB / "services" / "books.service.ts").read_text(encoding="utf-8")
_FORM = (_WEB / "components" / "dashboard" / "books" / "ChapterContextForm.tsx").read_text(
    encoding="utf-8"
)
_CONTROL = (_WEB / "components" / "dashboard" / "books" / "ChapterGenerateControl.tsx").read_text(
    encoding="utf-8"
)


def test_generate_lesson_request_has_force_field():
    """AC3: GenerateLessonRequest interface must declare force?: boolean."""
    assert "force?" in _SERVICE, (
        "D187: GenerateLessonRequest in books.service.ts must have a force?: boolean field"
    )


def test_generate_lesson_function_accepts_force():
    """AC5: generateLesson function passes force to the request body via conditional spread."""
    assert "force ? { force }" in _SERVICE, (
        "D187: generateLesson in books.service.ts must spread force into the request body"
    )


def test_chapter_context_form_on_generate_takes_boolean():
    """AC4: ChapterContextFormProps.onGenerate must be typed (force: boolean) => void."""
    assert "(force: boolean) => void" in _FORM, (
        "D187: ChapterContextForm onGenerate prop must be typed '(force: boolean) => void'"
    )


def test_handle_generate_now_calls_on_generate_true():
    """AC4: handleGenerateNow must call onGenerate(true)."""
    assert "onGenerate(true)" in _FORM, (
        "D187: handleGenerateNow() in ChapterContextForm.tsx must call onGenerate(true)"
    )


def test_chapter_generate_control_threads_force():
    """AC5: ChapterGenerateControl must pass force through onGenerate callback."""
    assert "(force) => handleGenerate(phase.tier, force)" in _CONTROL, (
        "D187: ChapterGenerateControl onGenerate prop must be"
        " '(force) => handleGenerate(phase.tier, force)'"
    )


def test_skip_does_not_pass_force():
    """AC2: the Skip callback must NOT pass force — it calls handleGenerate without it."""
    assert "onSkip={() => handleGenerate(phase.tier)}" in _CONTROL, (
        "D187: onSkip in ChapterGenerateControl must call handleGenerate(phase.tier)"
        " with no force argument"
    )
