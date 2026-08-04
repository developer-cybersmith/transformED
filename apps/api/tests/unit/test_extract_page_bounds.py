"""Page-scoped extraction — Story 1-12 (book-scale Phase 4), AC1-AC9.

The extractor must be able to read ONE chapter's pages instead of a whole
1,151-page book. These tests are written against "THE CONTRACT" in
`docs/stories/1-12-page-scoped-extraction.md`:

  * `page_start` / `page_end` are 0-based and INCLUSIVE.
  * Both omitted -> whole document, byte-identical to today's behaviour.
  * Only one supplied, or out of range -> non-zero exit with a diagnostic.
    **Never clamped** — a clamped range means Phase 5 generates a lesson from
    the wrong pages and nothing says so.
  * `page_count` keeps its meaning (whole document); `extracted_page_count`
    and `page_offset` are added; `page_texts` is the slice only.
  * Page NUMBERS stay absolute (real book page); LIST INDICES are
    chapter-relative. The two must never be confused.

The 1,151-page book is deliberately not in the repo, so AC5 ("page 0's content
is provably absent") is exercised here against repo fixtures whose pages carry
unique per-page markers; the real-book run is the story's manual T5 step.

Nearly every test invokes the module as a subprocess, the way `extract_node`
(`graph.py:280-290`) and `book_ingest_job` do, so the CLI contract is covered
alongside the Python one. The one in-process test is the docling splice (AC9),
where the real converter costs minutes per run.
"""

from __future__ import annotations

import json
import pathlib
import re
import subprocess
import sys
from typing import Any

import pytest


def _ensure_eval_pdfs() -> None:
    """Generate the eval PDFs if absent — AT IMPORT TIME, deliberately.

    `apps/api/.gitignore:40` ignores `tests/fixtures/eval_pdfs/*.pdf`, so on a
    fresh clone — CI included — every fixture-dependent test here would skip. A
    guard that skips in CI is not a guard (binding rule 7): Phase 4 could regress
    and the suite would stay green.

    This ran as a session fixture first, and that was verifiably wrong: `skipif`
    is evaluated at COLLECTION time, so the PDFs were regenerated but the tests
    had already been marked skipped. Confirmed by deleting them and watching
    `4 passed, 24 skipped` with 5 files on disk afterwards. Import-time it is.

    `demo-assets/sample-chapter.pdf` is a real asset and cannot be generated —
    tests needing it still skip, visibly.
    """
    target = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "eval_pdfs"
    if sorted(target.glob("*.pdf")):
        return
    try:
        from tests.fixtures.generate_eval_pdfs import generate_all

        target.mkdir(parents=True, exist_ok=True)
        generate_all(target)
    except Exception:  # noqa: BLE001 — absent fixtures then skip visibly, as before
        pass


_ensure_eval_pdfs()


_REPO_ROOT = pathlib.Path(__file__).resolve().parents[4]
API_DIR = pathlib.Path(__file__).resolve().parents[2]
SAMPLE_PDF = _REPO_ROOT / "demo-assets" / "sample-chapter.pdf"
EVAL_PDFS = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "eval_pdfs"

SHORT_PDF = EVAL_PDFS / "short.pdf"  # 3 pages
DENSE_PDF = EVAL_PDFS / "dense_text.pdf"  # 15 pages, "Dense Chapter - Page N"
LONG_PDF = EVAL_PDFS / "long.pdf"  # 120 pages, "Section C.S"
IMAGE_PDF = EVAL_PDFS / "image_heavy.pdf"  # 10 pages, images on every page
TABLE_PDF = EVAL_PDFS / "table_heavy.pdf"  # 8 pages, tables on every page

_MODULE = "app.modules.content.pipeline.nodes.extract_subprocess"

# Fixture page counts, asserted rather than assumed by the tests that use them:
# a fixture regenerated at a different length must fail loudly, not silently
# turn a bounds test into a whole-document test.
DENSE_PAGES = 15
LONG_PAGES = 120
IMAGE_PAGES = 10
SHORT_PAGES = 3


def _missing(*paths: pathlib.Path) -> str:
    """Skip reason naming the absent fixture, or '' when all are present."""
    absent = [str(p) for p in paths if not p.exists()]
    return f"fixture(s) absent: {', '.join(absent)}" if absent else ""


def _cli(*args: str) -> subprocess.CompletedProcess[str]:
    """Invoke the extraction subprocess exactly as the pipeline does."""
    return subprocess.run(  # noqa: S603
        [sys.executable, "-m", _MODULE, *args],
        capture_output=True,
        text=True,
        cwd=str(API_DIR),
        timeout=600,
        check=False,
    )


def run_extract(
    pdf: pathlib.Path,
    img_dir: pathlib.Path,
    threshold: int = 100,
    bounds: tuple[int, int] | None = None,
) -> dict[str, Any]:
    """Full extraction mode. `bounds=None` uses the legacy 3-argument form."""
    img_dir.mkdir(parents=True, exist_ok=True)
    extra = [str(bounds[0]), str(bounds[1])] if bounds is not None else []
    proc = _cli(str(pdf), str(img_dir), str(threshold), *extra)
    assert proc.returncode == 0, f"extraction failed: {proc.stderr[-2000:]}"
    return json.loads(proc.stdout)


def run_text_only(
    pdf: pathlib.Path,
    front_pages: int = 0,
    head_chars: int = 0,
    bounds: tuple[int, int] | None = None,
) -> dict[str, Any]:
    """Text-only mode. `bounds=None` uses the Story 1-10 form."""
    extra = [str(bounds[0]), str(bounds[1])] if bounds is not None else []
    args = [str(pdf)] if not extra else [str(pdf), str(front_pages), str(head_chars), *extra]
    proc = _cli("--text-only", *args)
    assert proc.returncode == 0, f"text-only extraction failed: {proc.stderr[-2000:]}"
    return json.loads(proc.stdout)


def _page_marker_present(text: str, marker: str) -> bool:
    r"""Whole-token marker search.

    'Dense Chapter - Page 1' is a prefix of '...Page 10', so a plain `in`
    check cannot prove page 0 is absent. The trailing \b makes the match exact.
    """
    return re.search(re.escape(marker) + r"\b", text) is not None


# ── AC1 — the signatures ──────────────────────────────────────────────────────


@pytest.mark.unit
def test_extract_pdf_signature_matches_the_contract() -> None:
    """Bounds are appended as optional keyword-capable params, after the three
    positional ones — otherwise graph.py's positional call breaks (AC3)."""
    import inspect

    from app.modules.content.pipeline.nodes import extract_subprocess as es

    params = list(inspect.signature(es.extract_pdf).parameters.values())
    assert [p.name for p in params] == [
        "pdf_path",
        "img_dir",
        "ocr_threshold",
        "page_start",
        "page_end",
    ]
    assert params[3].default is None, "page_start must default to None (unbounded)"
    assert params[4].default is None, "page_end must default to None (unbounded)"


@pytest.mark.unit
def test_extract_text_only_signature_matches_the_contract() -> None:
    """Bounds go AFTER Story 1-10's front_pages/head_chars — those callers pass
    them positionally."""
    import inspect

    from app.modules.content.pipeline.nodes import extract_subprocess as es

    params = list(inspect.signature(es.extract_text_only).parameters.values())
    assert [p.name for p in params] == [
        "pdf_path",
        "front_pages",
        "head_chars",
        "page_start",
        "page_end",
    ]
    assert (params[1].default, params[2].default) == (0, 0)
    assert params[3].default is None
    assert params[4].default is None


# ── AC3 — backward compatibility (the highest-value test in this file) ────────


@pytest.mark.unit
@pytest.mark.skipif(bool(_missing(SHORT_PDF)), reason=_missing(SHORT_PDF) or "present")
def test_unbounded_extract_pdf_equals_explicit_full_bounds(tmp_path: pathlib.Path) -> None:
    """AC3. `graph.py:280-290` still calls the 3-positional-argument form.

    Proven by extracting the SAME PDF twice — once with no bounds, once with
    explicit whole-document bounds — and comparing the results key by key,
    rather than by eyeballing that the unbounded result 'looks right'. Any
    divergence means the bounded path is not a strict generalisation of the
    legacy path, which is the failure mode this story must not have.
    """
    legacy = run_extract(SHORT_PDF, tmp_path / "legacy")
    assert legacy["page_count"] == SHORT_PAGES, "fixture changed — rewrite the bounds below"

    explicit = run_extract(SHORT_PDF, tmp_path / "explicit", bounds=(0, SHORT_PAGES - 1))

    assert legacy["raw_text"] == explicit["raw_text"]
    assert legacy["font_blocks"] == explicit["font_blocks"]
    assert legacy["tables_detected"] == explicit["tables_detected"]
    assert legacy["docling_pages"] == explicit["docling_pages"]
    assert legacy["page_count"] == explicit["page_count"]

    # image_files carry the (differing) img_dir, so compare the parts that must
    # match: how many, from which absolute pages, under which file names.
    def _shape(result: dict[str, Any]) -> list[tuple[int, str]]:
        return [
            (img["page"], pathlib.Path(img["local_path"]).name) for img in result["image_files"]
        ]

    assert _shape(legacy) == _shape(explicit)

    # And the new keys describe "whole document" on the legacy path.
    assert legacy["page_offset"] == 0
    assert legacy["extracted_page_count"] == legacy["page_count"]


@pytest.mark.unit
@pytest.mark.skipif(bool(_missing(IMAGE_PDF)), reason=_missing(IMAGE_PDF) or "present")
def test_unbounded_extraction_of_an_image_bearing_pdf_is_unchanged(
    tmp_path: pathlib.Path,
) -> None:
    """AC3 on the path that actually writes files. Image naming is where an
    'absolute vs relative' regression shows up first (AC7), so the legacy form
    is pinned against explicit full bounds here too."""
    legacy = run_extract(IMAGE_PDF, tmp_path / "legacy")
    assert legacy["page_count"] == IMAGE_PAGES, "fixture changed — rewrite the bounds below"
    assert legacy["image_files"], "fixture yields no images — this test would be vacuous"

    explicit = run_extract(IMAGE_PDF, tmp_path / "explicit", bounds=(0, IMAGE_PAGES - 1))

    legacy_names = sorted(
        (i["page"], pathlib.Path(i["local_path"]).name) for i in legacy["image_files"]
    )
    explicit_names = sorted(
        (i["page"], pathlib.Path(i["local_path"]).name) for i in explicit["image_files"]
    )
    assert legacy_names == explicit_names
    assert legacy["raw_text"] == explicit["raw_text"]


@pytest.mark.unit
@pytest.mark.skipif(bool(_missing(LONG_PDF)), reason=_missing(LONG_PDF) or "present")
def test_unbounded_text_only_equals_explicit_full_bounds() -> None:
    """AC3 for the Story 1-10 mode: `book_ingest_job` calls it without bounds."""
    legacy = run_text_only(LONG_PDF)
    assert legacy["page_count"] == LONG_PAGES, "fixture changed — rewrite the bounds below"

    explicit = run_text_only(LONG_PDF, 0, 0, bounds=(0, LONG_PAGES - 1))

    assert legacy["page_texts"] == explicit["page_texts"]
    assert legacy["toc"] == explicit["toc"]
    assert legacy["page_count"] == explicit["page_count"]
    assert legacy["page_offset"] == 0
    assert legacy["extracted_page_count"] == LONG_PAGES


@pytest.mark.unit
def test_graph_still_uses_the_three_argument_form() -> None:
    """AC3 / Dev Notes: passing bounds from `extract_node` is Phase 5, not this
    story. If graph.py starts passing bounds here, the compatibility guarantee
    above stops being exercised by production code."""
    graph = (API_DIR / "app" / "modules" / "content" / "pipeline" / "graph.py").read_text(
        encoding="utf-8"
    )
    marker = "nodes.extract_subprocess"
    assert marker in graph, "extract_node no longer spawns the extraction subprocess"

    # Only the spawn call itself is in scope: graph.py legitimately mentions
    # page_start elsewhere (the chapters state channel).
    start = graph.index(marker)
    end = graph.index("stdout=", start)
    spawn_args = graph[start:end]

    assert "local_pdf" in spawn_args and "img_dir" in spawn_args
    assert "ocr_text_yield_threshold" in spawn_args
    assert "page_start" not in spawn_args and "page_end" not in spawn_args, (
        f"graph.py is passing page bounds — that is Phase 5. Phase 4 must leave "
        f"the 3-argument call untouched. Call site:\n{spawn_args}"
    )
    assert "--text-only" not in spawn_args


# ── AC2 — the loop is genuinely bounded (evidence, not inspection) ────────────


@pytest.mark.unit
@pytest.mark.skipif(bool(_missing(LONG_PDF)), reason=_missing(LONG_PDF) or "present")
def test_text_only_bounded_run_cannot_see_out_of_range_pages() -> None:
    """AC2/AC5. Text unique to pages OUTSIDE the range must be ABSENT — the
    only evidence that the loop is `range(page_start, page_end + 1)` and not
    `range(page_count)` with a slice afterwards."""
    out = run_text_only(LONG_PDF, 0, 0, bounds=(12, 20))
    joined = "\n".join(out["page_texts"])

    assert _page_marker_present(joined, "Section 2.3"), "page 12's own marker is missing"
    assert _page_marker_present(joined, "Section 3.1"), "page 20's own marker is missing"
    for outside in ("Section 1.1", "Section 2.2", "Section 3.2"):
        assert not _page_marker_present(joined, outside), (
            f"{outside!r} belongs to a page outside 12..20 — the extraction is not bounded"
        )


@pytest.mark.unit
@pytest.mark.skipif(bool(_missing(DENSE_PDF)), reason=_missing(DENSE_PDF) or "present")
def test_extract_pdf_bounded_run_cannot_see_out_of_range_pages(tmp_path: pathlib.Path) -> None:
    """AC2/AC5 for full extraction mode. Page 0's content — the analogue of the
    real book's front matter — is provably absent from a chapter extraction."""
    out = run_extract(DENSE_PDF, tmp_path / "imgs", bounds=(4, 9))

    assert _page_marker_present(out["raw_text"], "Dense Chapter - Page 5")
    assert _page_marker_present(out["raw_text"], "Dense Chapter - Page 10")
    for outside in (
        "Dense Chapter - Page 1",  # page index 0
        "Dense Chapter - Page 4",  # the page just before the range
        "Dense Chapter - Page 11",  # the page just after the range
        "Dense Chapter - Page 15",
    ):
        assert not _page_marker_present(out["raw_text"], outside), (
            f"{outside!r} is outside 4..9 but appears in raw_text"
        )

    # raw_text is "\n\n".join(page_texts) — exactly the slice, no blank padding
    # standing in for the skipped pages.
    assert len(out["raw_text"].split("\n\n")) == 6


# ── AC6 — the three counts are correct AND distinguishable ────────────────────


@pytest.mark.unit
@pytest.mark.skipif(bool(_missing(DENSE_PDF)), reason=_missing(DENSE_PDF) or "present")
def test_extract_pdf_reports_three_distinct_page_numbers(tmp_path: pathlib.Path) -> None:
    """AC6. 15-page document, pages 4..9 → 15 / 6 / 4. The three values differ
    from each other, so no test can pass by a coincidental alias of one key
    onto another."""
    out = run_extract(DENSE_PDF, tmp_path / "imgs", bounds=(4, 9))

    assert out["page_count"] == DENSE_PAGES, "page_count must stay the DOCUMENT's page count"
    assert out["extracted_page_count"] == 6, "page_end - page_start + 1, inclusive"
    assert out["page_offset"] == 4
    assert len({out["page_count"], out["extracted_page_count"], out["page_offset"]}) == 3


@pytest.mark.unit
@pytest.mark.skipif(bool(_missing(LONG_PDF)), reason=_missing(LONG_PDF) or "present")
def test_text_only_returns_the_slice_only_with_three_distinct_counts() -> None:
    """AC6. 120-page document, pages 12..20 → 120 / 9 / 12, all different.
    `page_texts[0]` is the page at `page_offset`, not the document's page 0."""
    out = run_text_only(LONG_PDF, 0, 0, bounds=(12, 20))

    assert out["page_count"] == LONG_PAGES
    assert out["extracted_page_count"] == 9
    assert out["page_offset"] == 12
    assert len({out["page_count"], out["extracted_page_count"], out["page_offset"]}) == 3

    assert len(out["page_texts"]) == 9, "page_texts must be the slice, not the whole document"
    assert _page_marker_present(out["page_texts"][0], "Section 2.3"), (
        "page_texts[0] must be the page at page_offset (12), not page 0"
    )
    assert _page_marker_present(out["page_texts"][-1], "Section 3.1"), (
        "page_texts[-1] must be page_end (20), inclusive"
    )


@pytest.mark.unit
@pytest.mark.skipif(bool(_missing(DENSE_PDF)), reason=_missing(DENSE_PDF) or "present")
def test_a_single_page_range_is_inclusive_on_both_ends() -> None:
    """AC1 semantics: (n, n) is one page, not zero. The off-by-one that turns a
    35-page chapter into 34 pages lives here."""
    out = run_text_only(DENSE_PDF, 0, 0, bounds=(7, 7))
    assert out["extracted_page_count"] == 1
    assert len(out["page_texts"]) == 1
    assert _page_marker_present(out["page_texts"][0], "Dense Chapter - Page 8")


# ── AC7 — page NUMBERS stay absolute ──────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.skipif(bool(_missing(IMAGE_PDF)), reason=_missing(IMAGE_PDF) or "present")
def test_image_page_numbers_and_filenames_are_absolute_not_chapter_relative(
    tmp_path: pathlib.Path,
) -> None:
    """AC7 — the one a careless implementation gets wrong, tested directly.

    Extracting pages 3..5 must produce page numbers 4, 5, 6 (page_idx + 1),
    NOT 1, 2, 3. If numbering became chapter-relative, every chapter's images
    would collide in storage at the same names, and 'page 3' in a slide would
    mean three different pages in three different lessons.
    """
    img_dir = tmp_path / "imgs"
    out = run_extract(IMAGE_PDF, img_dir, bounds=(3, 5))

    assert out["image_files"], "fixture yields no images — the assertion below would be vacuous"

    pages = {img["page"] for img in out["image_files"]}
    assert pages == {4, 5, 6}, (
        f"expected absolute 1-indexed page numbers 4-6 for pages 3..5, got {sorted(pages)} "
        f"— {{1, 2, 3}} means the numbering went chapter-relative"
    )

    names = [pathlib.Path(img["local_path"]).name for img in out["image_files"]]
    assert all(re.match(r"^p[456]_\d+\.png$", n) for n in names), names
    assert not any(n.startswith(("p1_", "p2_", "p3_")) for n in names), (
        f"chapter-relative image names would collide across chapters: {names}"
    )
    # And the files really are on disk under those absolute names.
    assert sorted(p.name for p in img_dir.glob("p*.png")) == sorted(set(names))


# ── AC4 — invalid bounds fail loudly and are NEVER clamped ────────────────────


def _assert_rejected(proc: subprocess.CompletedProcess[str], *must_mention: str) -> None:
    """A rejection is non-zero exit + a diagnostic + no result on stdout."""
    assert proc.returncode != 0, (
        f"invalid bounds exited 0 — stdout={proc.stdout[:400]!r}. Silently accepting "
        f"them is exactly the wrong-pages failure this story guards against."
    )
    message = proc.stderr
    for token in must_mention:
        assert token in message, (
            f"diagnostic must name {token!r} so the operator can see WHICH value "
            f"was wrong; got: {message[-600:]!r}"
        )
    assert '"page_count"' not in proc.stdout, "a rejected run must not emit a result"


@pytest.mark.unit
@pytest.mark.skipif(bool(_missing(SHORT_PDF)), reason=_missing(SHORT_PDF) or "present")
@pytest.mark.parametrize(
    ("bounds", "bad_value"),
    [
        ((-1, 2), "-1"),  # page_start below zero
        ((0, 3), "3"),  # page_end == page_count (0-based, so out of range)
        ((0, 999), "999"),  # page_end far past the end
        ((2, 1), "2"),  # start after end
        ((5, 7), "5"),  # whole range past the end
    ],
)
def test_out_of_range_bounds_exit_nonzero_with_a_useful_diagnostic(
    tmp_path: pathlib.Path, bounds: tuple[int, int], bad_value: str
) -> None:
    """AC4. The message must name the offending value AND the document's page
    count — 'invalid range' alone leaves the operator guessing."""
    img_dir = tmp_path / "imgs"
    img_dir.mkdir()
    proc = _cli(str(SHORT_PDF), str(img_dir), "100", str(bounds[0]), str(bounds[1]))
    _assert_rejected(proc, bad_value, str(SHORT_PAGES))


@pytest.mark.unit
@pytest.mark.skipif(bool(_missing(SHORT_PDF)), reason=_missing(SHORT_PDF) or "present")
@pytest.mark.parametrize(
    ("bounds", "bad_value"),
    [((-1, 2), "-1"), ((0, 3), "3"), ((0, 999), "999"), ((2, 1), "2")],
)
def test_text_only_out_of_range_bounds_exit_nonzero_with_a_useful_diagnostic(
    bounds: tuple[int, int], bad_value: str
) -> None:
    """AC4 for the mode chapter detection uses."""
    proc = _cli("--text-only", str(SHORT_PDF), "0", "0", str(bounds[0]), str(bounds[1]))
    _assert_rejected(proc, bad_value, str(SHORT_PAGES))


@pytest.mark.unit
@pytest.mark.skipif(bool(_missing(SHORT_PDF)), reason=_missing(SHORT_PDF) or "present")
def test_an_over_long_range_is_rejected_and_never_clamped(tmp_path: pathlib.Path) -> None:
    """AC4, stated as its own test because clamping is the SILENT failure.

    A clamped (0, 999) on a 3-page document would 'succeed' with
    extracted_page_count == 3, and Phase 5 would build a lesson from pages
    nobody asked for with nothing in the output saying so.
    """
    img_dir = tmp_path / "imgs"
    img_dir.mkdir()
    proc = _cli(str(SHORT_PDF), str(img_dir), "100", "0", "999")

    assert proc.returncode != 0
    assert proc.stdout.strip() == "" or '"extracted_page_count"' not in proc.stdout, (
        "the range was clamped and the run succeeded — silently extracting a "
        "different range than requested is the defect this story exists to prevent"
    )
    assert not list(img_dir.glob("*.png")), "a rejected run must not have extracted anything"


@pytest.mark.unit
@pytest.mark.skipif(bool(_missing(LONG_PDF)), reason=_missing(LONG_PDF) or "present")
def test_text_only_over_long_range_is_rejected_and_never_clamped() -> None:
    """AC4 no-clamp for text-only: a clamped run would return 120 pages of text
    to a caller that asked for pages 100..999 and get no signal at all."""
    proc = _cli("--text-only", str(LONG_PDF), "0", "0", "100", "999")

    assert proc.returncode != 0
    if proc.stdout.strip():
        payload = json.loads(proc.stdout)
        pytest.fail(f"clamped instead of failing: extracted {payload.get('extracted_page_count')}")


@pytest.mark.unit
@pytest.mark.skipif(bool(_missing(SHORT_PDF)), reason=_missing(SHORT_PDF) or "present")
def test_half_specified_bounds_are_rejected_in_extract_mode(tmp_path: pathlib.Path) -> None:
    """AC4: 'only one supplied → error. A half-specified range is a bug, not a
    default.' Treating a lone page_start as 'from here to the end' would make a
    truncated chapter indistinguishable from a whole one."""
    img_dir = tmp_path / "imgs"
    img_dir.mkdir()
    proc = _cli(str(SHORT_PDF), str(img_dir), "100", "1")
    _assert_rejected(proc, "page_start", "page_end")


@pytest.mark.unit
@pytest.mark.skipif(bool(_missing(SHORT_PDF)), reason=_missing(SHORT_PDF) or "present")
def test_half_specified_bounds_are_rejected_in_text_only_mode() -> None:
    """AC4, text-only form: `--text-only <pdf> <front> <head> <page_start>`."""
    proc = _cli("--text-only", str(SHORT_PDF), "0", "0", "1")
    _assert_rejected(proc, "page_start", "page_end")


# ── AC8 — _extract_font_blocks is bounded too, and stays absolute ─────────────


@pytest.mark.unit
@pytest.mark.skipif(bool(_missing(DENSE_PDF)), reason=_missing(DENSE_PDF) or "present")
def test_font_blocks_are_bounded_and_their_page_numbers_stay_absolute(
    tmp_path: pathlib.Path,
) -> None:
    """AC8. `pdftext.dictionary_output` over the WHOLE document would make a
    '6-page' extraction still parse 15 (1,151 in the real case), defeating the
    phase. Two things must both hold: fewer blocks (it really was bounded), and
    page numbers remapped by +page_start (they stay absolute).
    """
    whole = run_extract(DENSE_PDF, tmp_path / "whole")
    whole_pages = sorted({b["page"] for b in whole["font_blocks"]})
    assert whole_pages, "fixture yields no font blocks — this test would be vacuous"
    base = whole_pages[0]  # pdftext's own page base, discovered rather than assumed

    bounded = run_extract(DENSE_PDF, tmp_path / "bounded", bounds=(4, 9))
    bounded_pages = sorted({b["page"] for b in bounded["font_blocks"]})

    assert bounded_pages == [base + i for i in range(4, 10)], (
        f"expected absolute pages {[base + i for i in range(4, 10)]}, got {bounded_pages} "
        f"— starting at {base} would mean the remap by +page_start is missing"
    )
    assert len(bounded["font_blocks"]) < len(whole["font_blocks"]), (
        "the bounded run produced as many font blocks as the whole document — "
        "pdftext is still parsing every page"
    )
    outside_text = " ".join(b["text"] for b in bounded["font_blocks"])
    assert not _page_marker_present(outside_text, "Dense Chapter - Page 1"), (
        "page 0's text is in the font blocks — _extract_font_blocks is unbounded"
    )


# ── AC9 — the docling table-run splice keeps its index bases straight ─────────


@pytest.mark.unit
@pytest.mark.skipif(bool(_missing(TABLE_PDF)), reason=_missing(TABLE_PDF) or "present")
def test_docling_table_splice_uses_the_right_base_under_bounds(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    """AC9. `_convert_table_runs` mixes ABSOLUTE page indices (for
    `_build_sub_pdf`) with `page_texts` LIST POSITIONS (for the splice). Under
    bounds those bases diverge, and a silent off-by-`page_start` here writes
    table markdown onto the wrong pages.

    Run through the public `extract_pdf` so the real pdfplumber detection and
    the real splice arithmetic execute; only the converter itself is stubbed.

    # MOCK-CONTRACT: `_docling_run_pages` is replaced because a real docling
    # run costs minutes per invocation. The real converter path is covered by
    # tests/unit/test_extract_subprocess.py::TestDoclingSplice and
    # ::test_docling_run_pages_exports_1_indexed_pages_with_empty_image_placeholder.
    # Everything asserted below — run grouping, sub-PDF bounds, splice
    # positions, returned indices — is production code, not the stub.
    """
    from app.modules.content.pipeline.nodes import extract_subprocess as es

    build_calls: list[tuple[int, int]] = []
    real_build = es._build_sub_pdf

    def spy_build_sub_pdf(pdf_doc: Any, start: int, end: int, sub_path: str) -> None:  # noqa: ANN401
        build_calls.append((start, end))
        real_build(pdf_doc, start, end, sub_path)

    def fake_docling_run_pages(sub_pdf_path: str, num_pages: int) -> list[str]:
        return [f"MD-SUBPAGE-{k}" for k in range(num_pages)]

    monkeypatch.setattr(es, "_build_sub_pdf", spy_build_sub_pdf)
    monkeypatch.setattr(es, "_docling_run_pages", fake_docling_run_pages)

    img_dir = tmp_path / "imgs"
    img_dir.mkdir()
    page_start, page_end = 3, 5
    out = es.extract_pdf(str(TABLE_PDF), str(img_dir), 100, page_start, page_end)

    assert out["tables_detected"] > 0, "fixture has no tables — this test would be vacuous"
    assert out["docling_pages"], "no docling run happened on a table-bearing range"

    # Sub-PDFs are built from ABSOLUTE indices and never leave the range.
    assert build_calls, "no sub-PDF built"
    for start, end in build_calls:
        assert page_start <= start <= end <= page_end, (
            f"sub-PDF pages {start}..{end} escape the requested {page_start}..{page_end} "
            f"— the run grouping is using the wrong base"
        )

    # Returned indices are ABSOLUTE document pages.
    assert all(page_start <= p <= page_end for p in out["docling_pages"]), out["docling_pages"]

    # The splice lands at LIST position (absolute - page_offset).
    segments = out["raw_text"].split("\n\n")
    assert len(segments) == out["extracted_page_count"] == 3
    for absolute in out["docling_pages"]:
        relative = absolute - out["page_offset"]
        assert 0 <= relative < len(segments)
        assert segments[relative].startswith("MD-SUBPAGE-"), (
            f"docling markdown for absolute page {absolute} did not land at list "
            f"position {relative} — the splice base is off by page_start"
        )


# ── AC5 (repo-fixture stand-in) on the real 41-page chapter ───────────────────


@pytest.mark.unit
@pytest.mark.skipif(bool(_missing(SAMPLE_PDF)), reason=_missing(SAMPLE_PDF) or "present")
def test_a_chapter_sized_slice_of_the_reference_pdf_is_the_slice_only() -> None:
    """AC5/AC6 against the PDF every pipeline default was hardened around.

    The 1,151-page book is not in the repo (story T5 records that run
    manually); this asserts the same shape on the 41-page reference document:
    a mid-document slice returns exactly its own pages, and page 0's text is
    absent.
    """
    whole = run_text_only(SAMPLE_PDF)
    assert whole["page_count"] >= 10, "reference PDF unexpectedly short"
    page_zero_text = whole["page_texts"][0].strip()
    assert page_zero_text, "reference PDF page 0 has no text — cannot prove absence"

    start, end = 5, 12
    sliced = run_text_only(SAMPLE_PDF, 0, 0, bounds=(start, end))

    assert sliced["page_count"] == whole["page_count"], "page_count is the DOCUMENT's count"
    assert sliced["extracted_page_count"] == end - start + 1 == 8
    assert sliced["page_offset"] == start
    assert sliced["page_texts"] == whole["page_texts"][start : end + 1], (
        "a bounded slice must be exactly what the unbounded run produced for "
        "those pages — same text, same order"
    )

    probe = page_zero_text.split("\n")[0].strip()
    if len(probe) > 20:  # noqa: PLR2004 — only meaningful if page 0 has a distinctive line
        assert probe not in "\n".join(sliced["page_texts"]), (
            "page 0's content leaked into a slice starting at page 5"
        )
