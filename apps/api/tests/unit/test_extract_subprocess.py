"""
Unit tests for Story 2-0b — extraction subprocess core (ACs 1, 2, 3, 4, 6).

extract_pdf() lazy-imports pdfplumber/pypdfium2 inside the function, so fake
modules are injected via patch.dict(sys.modules, ...). Helper functions
(_page_text, _ocr_page_text, ...) are monkeypatched on the module itself.

The final test is a real smoke run against /tmp/mini.pdf (present only in the
dev WSL environment) — skipped elsewhere.
"""

from __future__ import annotations

import os
import sys
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest

from app.modules.content.pipeline.nodes import extract_subprocess as es

# ── Harness ───────────────────────────────────────────────────────────────────


def _run_extract(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
    *,
    texts: list[str],
    table_counts: list[int] | None = None,
    ocr_threshold: int = 50,
    ocr_return: str = "OCR TEXT",
) -> tuple[dict[str, Any], SimpleNamespace]:
    """Run extract_pdf with fake pdfium/pdfplumber modules and stubbed helpers."""
    n = len(texts)

    # Ordered event log: ("process", i) when page i's text is read,
    # ("release", i) when page i's caches are flushed (AC-3 interleaving proof).
    call_log: list[tuple[str, int]] = []

    pdfium_pages = [MagicMock(name=f"pdfium_page_{i}") for i in range(n)]
    pdfium_doc = MagicMock(name="pdfium_doc")
    pdfium_doc.__len__.return_value = n
    pdfium_doc.__getitem__.side_effect = lambda i: pdfium_pages[i]
    fake_pdfium = MagicMock(name="pypdfium2")
    fake_pdfium.PdfDocument = MagicMock(return_value=pdfium_doc)

    plumb_pages = [MagicMock(name=f"plumb_page_{i}") for i in range(n)]
    for i, plumb_page in enumerate(plumb_pages):
        plumb_page.flush_cache.side_effect = lambda i=i: call_log.append(("release", i))
    plumb_pdf = MagicMock(name="plumb_pdf")
    plumb_pdf.pages = plumb_pages
    plumb_pdf.__enter__.return_value = plumb_pdf
    plumb_pdf.__exit__.return_value = False
    fake_plumber = MagicMock(name="pdfplumber")
    fake_plumber.open = MagicMock(return_value=plumb_pdf)

    page_index_by_id = {id(p): i for i, p in enumerate(pdfium_pages)}

    def _fake_page_text(pdfium_page: Any) -> str:
        i = page_index_by_id[id(pdfium_page)]
        call_log.append(("process", i))
        return texts[i]

    monkeypatch.setattr(es, "_page_text", MagicMock(side_effect=_fake_page_text))
    monkeypatch.setattr(
        es, "_page_table_count", MagicMock(side_effect=list(table_counts or [0] * n))
    )
    monkeypatch.setattr(es, "_extract_page_images", MagicMock(return_value=[]))
    monkeypatch.setattr(es, "_extract_font_blocks", MagicMock(return_value=[]))
    ocr_mock = MagicMock(return_value=ocr_return)
    monkeypatch.setattr(es, "_ocr_page_text", ocr_mock)

    captured: dict[str, Any] = {}

    def _fake_convert(
        pdf_doc: Any,
        pdf_path: str,
        page_texts: list[str],
        table_page_idxs: list[int],
        page_count: int,
    ) -> list[int]:
        captured["table_page_idxs"] = list(table_page_idxs)
        captured["page_count"] = page_count
        return []

    monkeypatch.setattr(es, "_convert_table_runs", _fake_convert)

    with patch.dict(sys.modules, {"pypdfium2": fake_pdfium, "pdfplumber": fake_plumber}):
        result = es.extract_pdf("fake.pdf", str(tmp_path), ocr_threshold)

    return result, SimpleNamespace(
        pdfium_pages=pdfium_pages,
        plumb_pages=plumb_pages,
        pdfium_doc=pdfium_doc,
        pdfium_ctor=fake_pdfium.PdfDocument,
        ocr_mock=ocr_mock,
        captured=captured,
        call_log=call_log,
    )


# ── AC-2: _group_table_runs (pure function) ───────────────────────────────────


class TestGroupTableRuns:
    def test_empty_input_returns_no_runs(self) -> None:
        assert es._group_table_runs([], 10) == []

    def test_zero_page_count_returns_no_runs(self) -> None:
        assert es._group_table_runs([1], 0) == []

    def test_single_mid_page_expands_plus_minus_one(self) -> None:
        assert es._group_table_runs([5], 20) == [(4, 6)]

    def test_clamped_at_document_start(self) -> None:
        assert es._group_table_runs([0], 5) == [(0, 1)]

    def test_clamped_at_document_end(self) -> None:
        assert es._group_table_runs([4], 5) == [(3, 4)]

    def test_single_page_document(self) -> None:
        assert es._group_table_runs([0], 1) == [(0, 0)]

    def test_contiguous_table_pages_form_one_run(self) -> None:
        assert es._group_table_runs([1, 2], 10) == [(0, 3)]

    def test_adjacent_expanded_runs_merge(self) -> None:
        # [1] → (0,2), [4] → (3,5): touching runs merge into one
        assert es._group_table_runs([1, 4], 10) == [(0, 5)]

    def test_separated_pages_stay_separate_runs(self) -> None:
        assert es._group_table_runs([1, 6], 10) == [(0, 2), (5, 7)]

    def test_duplicates_and_unsorted_input(self) -> None:
        assert es._group_table_runs([5, 1, 5], 20) == [(0, 2), (4, 6)]


# ── AC-2: per-page splice ─────────────────────────────────────────────────────


class TestDoclingSplice:
    def test_docling_markdown_replaces_only_run_pages(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        build_mock = MagicMock()
        run_mock = MagicMock(return_value=["MD-A", "MD-B", "MD-C"])
        monkeypatch.setattr(es, "_build_sub_pdf", build_mock)
        monkeypatch.setattr(es, "_docling_run_pages", run_mock)
        page_texts = ["p0", "p1", "p2", "p3", "p4"]
        pdf_doc = MagicMock()

        docling_pages = es._convert_table_runs(pdf_doc, "x.pdf", page_texts, [2], 5)

        assert page_texts == ["p0", "MD-A", "MD-B", "MD-C", "p4"]
        assert docling_pages == [1, 2, 3]
        # AC-2 whole-doc-regression guard: sub-PDF built with EXACTLY the run
        # bounds (table page 2 ± 1) — never the whole document.
        build_mock.assert_called_once()
        build_args = build_mock.call_args[0]
        assert build_args[0] is pdf_doc
        assert (build_args[1], build_args[2]) == (1, 3)
        run_mock.assert_called_once()
        assert run_mock.call_args[0][1] == 3  # num_pages == run length (3-1+1)

    def test_empty_page_markdown_keeps_original_text(self, monkeypatch: pytest.MonkeyPatch) -> None:
        build_mock = MagicMock()
        run_mock = MagicMock(return_value=["", "MD-B", "  "])
        monkeypatch.setattr(es, "_build_sub_pdf", build_mock)
        monkeypatch.setattr(es, "_docling_run_pages", run_mock)
        page_texts = ["p0", "p1", "p2", "p3", "p4"]

        docling_pages = es._convert_table_runs(MagicMock(), "x.pdf", page_texts, [2], 5)

        assert page_texts == ["p0", "p1", "MD-B", "p3", "p4"]
        assert docling_pages == [2]
        build_mock.assert_called_once()
        assert (build_mock.call_args[0][1], build_mock.call_args[0][2]) == (1, 3)
        run_mock.assert_called_once()
        assert run_mock.call_args[0][1] == 3

    def test_41_page_doc_single_table_builds_one_sub_pdf_of_at_most_3_pages(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC-2 regression guard: whole-document docling must NEVER come back.

        41-page document, ONE table page (idx 20) → exactly ONE sub-PDF is
        built, spanning at most 3 pages (19..21). The stubs are arg-aware:
        the fake docling returns exactly num_pages markdown entries, so a
        whole-document run (0..40) would fail both the span assertion and
        the untouched-pages assertions below.
        """
        build_calls: list[tuple[int, int]] = []

        def fake_build_sub_pdf(pdf_doc: Any, start: int, end: int, sub_path: str) -> None:
            build_calls.append((start, end))

        def fake_docling_run_pages(sub_pdf_path: str, num_pages: int) -> list[str]:
            return [f"MD-{k}" for k in range(num_pages)]

        monkeypatch.setattr(es, "_build_sub_pdf", fake_build_sub_pdf)
        monkeypatch.setattr(es, "_docling_run_pages", fake_docling_run_pages)
        page_texts = [f"p{i}" for i in range(41)]

        docling_pages = es._convert_table_runs(MagicMock(), "x.pdf", page_texts, [20], 41)

        assert len(build_calls) == 1
        start, end = build_calls[0]
        assert (start, end) == (19, 21)
        assert end - start + 1 <= 3
        assert docling_pages == [19, 20, 21]
        assert page_texts[19:22] == ["MD-0", "MD-1", "MD-2"]
        # Every page outside the run is byte-identical — whole-doc docling
        # would have rewritten these.
        for i in [*range(0, 19), *range(22, 41)]:
            assert page_texts[i] == f"p{i}"

    def test_no_table_pages_means_no_docling_calls(self, monkeypatch: pytest.MonkeyPatch) -> None:
        build_mock = MagicMock()
        monkeypatch.setattr(es, "_build_sub_pdf", build_mock)
        page_texts = ["p0", "p1"]

        assert es._convert_table_runs(MagicMock(), "x.pdf", page_texts, [], 2) == []
        build_mock.assert_not_called()
        assert page_texts == ["p0", "p1"]

    def test_converter_created_once_and_reused(self) -> None:
        converter_cls = MagicMock(name="DocumentConverter")
        fake_mods = {
            "docling": MagicMock(),
            "docling.datamodel": MagicMock(),
            "docling.datamodel.base_models": MagicMock(),
            "docling.datamodel.pipeline_options": MagicMock(),
            "docling.document_converter": MagicMock(
                DocumentConverter=converter_cls, PdfFormatOption=MagicMock()
            ),
        }
        original = es._docling_converter
        es._docling_converter = None
        try:
            with patch.dict(sys.modules, fake_mods):
                first = es._get_docling_converter()
                second = es._get_docling_converter()
            assert first is second
            assert converter_cls.call_count == 1
        finally:
            es._docling_converter = original


# ── AC-2: docling/sub-PDF primitives ──────────────────────────────────────────


class TestDoclingPrimitives:
    def test_docling_run_pages_exports_1_indexed_pages_with_empty_image_placeholder(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """image_placeholder='' is load-bearing (data-loss fix): the default
        '<!-- image -->' placeholder is non-empty markdown, which would pass the
        splice guard and overwrite a scanned page's Tesseract OCR text. This
        test fails if the kwarg is ever removed."""
        document = MagicMock()
        document.export_to_markdown.side_effect = ["MD-1", "MD-2", "MD-3"]
        converter = MagicMock()
        converter.convert.return_value = SimpleNamespace(document=document)
        monkeypatch.setattr(es, "_get_docling_converter", MagicMock(return_value=converter))

        result = es._docling_run_pages("sub.pdf", 3)

        assert result == ["MD-1", "MD-2", "MD-3"]
        converter.convert.assert_called_once_with("sub.pdf")
        assert document.export_to_markdown.call_args_list == [
            call(page_no=1, image_placeholder=""),
            call(page_no=2, image_placeholder=""),
            call(page_no=3, image_placeholder=""),
        ]

    def test_docling_run_pages_returns_none_on_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        converter = MagicMock()
        converter.convert.side_effect = RuntimeError("docling exploded")
        monkeypatch.setattr(es, "_get_docling_converter", MagicMock(return_value=converter))

        assert es._docling_run_pages("sub.pdf", 2) is None

    def test_build_sub_pdf_imports_inclusive_page_range(self) -> None:
        """Guards the end+1 off-by-one: import_pages must receive the full
        inclusive range list(range(start, end + 1))."""
        sub = MagicMock(name="sub_pdf")
        fake_pdfium = MagicMock(name="pypdfium2")
        fake_pdfium.PdfDocument.new.return_value = sub
        src_doc = MagicMock(name="src_doc")

        with patch.dict(sys.modules, {"pypdfium2": fake_pdfium}):
            es._build_sub_pdf(src_doc, 2, 5, "sub.pdf")

        sub.import_pages.assert_called_once_with(src_doc, [2, 3, 4, 5])
        sub.save.assert_called_once_with("sub.pdf")
        sub.close.assert_called_once()

    def test_build_sub_pdf_single_page_run(self) -> None:
        sub = MagicMock(name="sub_pdf")
        fake_pdfium = MagicMock(name="pypdfium2")
        fake_pdfium.PdfDocument.new.return_value = sub
        src_doc = MagicMock(name="src_doc")

        with patch.dict(sys.modules, {"pypdfium2": fake_pdfium}):
            es._build_sub_pdf(src_doc, 0, 0, "sub.pdf")

        sub.import_pages.assert_called_once_with(src_doc, [0])

    def test_build_sub_pdf_closes_sub_doc_even_when_save_fails(self) -> None:
        sub = MagicMock(name="sub_pdf")
        sub.save.side_effect = RuntimeError("disk full")
        fake_pdfium = MagicMock(name="pypdfium2")
        fake_pdfium.PdfDocument.new.return_value = sub

        with patch.dict(sys.modules, {"pypdfium2": fake_pdfium}):
            with pytest.raises(RuntimeError):
                es._build_sub_pdf(MagicMock(), 1, 2, "sub.pdf")

        sub.close.assert_called_once()


# ── AC-2: docling failure fallback ────────────────────────────────────────────


class TestDoclingFailureFallback:
    def _fake_plumber(self, tables_by_page: dict[int, list[list[list[Any]]]], n: int) -> Any:
        pages = []
        for i in range(n):
            page = MagicMock(name=f"plumb_page_{i}")
            page.extract_tables.return_value = tables_by_page.get(i, [])
            pages.append(page)
        pdf = MagicMock()
        pdf.pages = pages
        pdf.__enter__.return_value = pdf
        pdf.__exit__.return_value = False
        module = MagicMock(name="pdfplumber")
        module.open = MagicMock(return_value=pdf)
        return module

    def test_fallback_appends_markdown_tables_without_raising(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(es, "_build_sub_pdf", MagicMock())
        monkeypatch.setattr(es, "_docling_run_pages", MagicMock(return_value=None))
        fake_plumber = self._fake_plumber({2: [[["H1", "H2"], ["a", "b"], [None, "d"]]]}, 5)
        page_texts = ["p0", "p1", "p2", "p3", "p4"]

        with patch.dict(sys.modules, {"pdfplumber": fake_plumber}):
            docling_pages = es._convert_table_runs(MagicMock(), "x.pdf", page_texts, [2], 5)

        assert docling_pages == []
        # Table page got its rows appended as a GitHub markdown table
        assert page_texts[2].startswith("p2")
        assert "| H1 | H2 |" in page_texts[2]
        assert "| --- | --- |" in page_texts[2]
        assert "| a | b |" in page_texts[2]
        assert "|  | d |" in page_texts[2]  # None cell → empty
        # Non-table pages (even inside the run) stay byte-identical
        assert page_texts[0] == "p0"
        assert page_texts[1] == "p1"
        assert page_texts[3] == "p3"
        assert page_texts[4] == "p4"

    def test_fallback_extract_tables_error_never_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(es, "_build_sub_pdf", MagicMock())
        monkeypatch.setattr(es, "_docling_run_pages", MagicMock(return_value=None))
        fake_plumber = self._fake_plumber({}, 3)
        fake_plumber.open.return_value.pages[1].extract_tables.side_effect = RuntimeError(
            "corrupt page"
        )
        page_texts = ["p0", "p1", "p2"]

        with patch.dict(sys.modules, {"pdfplumber": fake_plumber}):
            docling_pages = es._convert_table_runs(MagicMock(), "x.pdf", page_texts, [1], 3)

        assert docling_pages == []
        assert page_texts == ["p0", "p1", "p2"]

    def test_table_rows_to_markdown_escapes_and_pads(self) -> None:
        md = es._table_rows_to_markdown([["A|B", "line\nbreak"], ["only-one"]])
        lines = md.split("\n")
        assert lines[0] == "| A\\|B | line break |"
        assert lines[1] == "| --- | --- |"
        assert lines[2] == "| only-one |  |"

    def test_table_rows_to_markdown_empty(self) -> None:
        assert es._table_rows_to_markdown([]) == ""


# ── AC-4: image pre-filter ────────────────────────────────────────────────────


class TestImagePreFilter:
    def _plumb_page(
        self, images: list[dict[str, float]], width: float = 612, height: float = 792
    ) -> Any:
        page = MagicMock()
        page.images = images
        page.width = width
        page.height = height
        return page

    def test_tiny_logo_skipped_without_render(self, tmp_path: Any) -> None:
        plumb_page = self._plumb_page([{"x0": 0, "top": 0, "x1": 10, "bottom": 10}])
        pdfium_page = MagicMock()

        result = es._extract_page_images(pdfium_page, plumb_page, str(tmp_path), 1)

        assert result == []
        pdfium_page.render.assert_not_called()

    def test_small_render_area_skipped_without_render(self, tmp_path: Any) -> None:
        # 25% of a tiny page (passes area fraction) but < 10,000 px² at 300 DPI
        plumb_page = self._plumb_page(
            [{"x0": 0, "top": 0, "x1": 10, "bottom": 10}], width=20, height=20
        )
        pdfium_page = MagicMock()

        result = es._extract_page_images(pdfium_page, plumb_page, str(tmp_path), 1)

        assert result == []
        pdfium_page.render.assert_not_called()

    def test_half_page_figure_rendered_at_300_dpi(self, tmp_path: Any) -> None:
        plumb_page = self._plumb_page([{"x0": 0, "top": 0, "x1": 306, "bottom": 396}])
        pdfium_page = MagicMock()
        pil_page = MagicMock()
        pdfium_page.render.return_value.to_pil.return_value = pil_page

        result = es._extract_page_images(pdfium_page, plumb_page, str(tmp_path), 1)

        pdfium_page.render.assert_called_once_with(scale=300 / 72)
        assert len(result) == 1
        assert result[0]["page"] == 1
        assert result[0]["local_path"].endswith("p1_0.png")
        pil_page.crop.return_value.save.assert_called_once()

    def test_mixed_images_only_large_survive(self, tmp_path: Any) -> None:
        plumb_page = self._plumb_page(
            [
                {"x0": 0, "top": 0, "x1": 10, "bottom": 10},  # tiny logo — dropped
                {"x0": 0, "top": 0, "x1": 306, "bottom": 396},  # half page — kept
            ]
        )
        pdfium_page = MagicMock()
        pdfium_page.render.return_value.to_pil.return_value = MagicMock()

        result = es._extract_page_images(pdfium_page, plumb_page, str(tmp_path), 3)

        assert len(result) == 1
        # Original enumeration index preserved in the filename
        assert result[0]["local_path"].endswith("p3_1.png")

    def test_no_images_no_render(self, tmp_path: Any) -> None:
        plumb_page = self._plumb_page([])
        pdfium_page = MagicMock()

        assert es._extract_page_images(pdfium_page, plumb_page, str(tmp_path), 1) == []
        pdfium_page.render.assert_not_called()


# ── AC-6: per-page OCR ────────────────────────────────────────────────────────


class TestPerPageOcr:
    def test_only_empty_page_is_ocred(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
        rich_a = "A" * 100
        rich_b = "B" * 100
        result, ctx = _run_extract(
            monkeypatch, tmp_path, texts=[rich_a, "", rich_b], ocr_threshold=50
        )

        ctx.ocr_mock.assert_called_once()
        assert ctx.ocr_mock.call_args[0][2] == 2  # page_num of the empty page
        assert result["raw_text"] == f"{rich_a}\n\nOCR TEXT\n\n{rich_b}"
        # AC-6: OCR reuses the still-open pdfium page — the PDF is opened
        # exactly once, never reopened for a second OCR pass.
        assert ctx.pdfium_ctor.call_count == 1

    def test_no_ocr_when_all_pages_rich(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        result, ctx = _run_extract(
            monkeypatch,
            tmp_path,
            texts=["A" * 100, "B" * 100, "C" * 100],
            ocr_threshold=50,
        )

        ctx.ocr_mock.assert_not_called()
        assert result["raw_text"] == "\n\n".join(["A" * 100, "B" * 100, "C" * 100])
        assert ctx.pdfium_ctor.call_count == 1

    def test_empty_ocr_output_keeps_original_page_text(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        result, ctx = _run_extract(
            monkeypatch,
            tmp_path,
            texts=["A" * 100, "short", "B" * 100],
            ocr_threshold=50,
            ocr_return="   ",
        )

        ctx.ocr_mock.assert_called_once()
        assert result["raw_text"] == "\n\n".join(["A" * 100, "short", "B" * 100])
        assert ctx.pdfium_ctor.call_count == 1


# ── AC-3: per-page release ────────────────────────────────────────────────────


class TestPageRelease:
    def test_release_calls_happen_every_page(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        _, ctx = _run_extract(monkeypatch, tmp_path, texts=["A" * 100, "B" * 100, "C" * 100])

        for plumb_page in ctx.plumb_pages:
            plumb_page.flush_cache.assert_called_once()
            plumb_page.close.assert_called_once()
        for pdfium_page in ctx.pdfium_pages:
            pdfium_page.close.assert_called_once()
        ctx.pdfium_doc.close.assert_called_once()

        # AC-3 interleaving: release of page i must happen BEFORE processing of
        # page i+1 — a batch release after the loop keeps every page's caches
        # alive simultaneously (O(n) RSS) and must fail here.
        log = ctx.call_log
        assert ("process", 0) in log and ("release", 2) in log
        for i in range(2):
            release_i = log.index(("release", i))
            process_next = log.index(("process", i + 1))
            assert release_i < process_next, (
                f"page {i} released at log position {release_i}, but page {i + 1} "
                f"was processed earlier at {process_next} — releases are batched. Log: {log}"
            )

    def test_release_failure_never_raises(self) -> None:
        plumb_page = MagicMock()
        plumb_page.flush_cache.side_effect = RuntimeError("boom")
        plumb_page.close.side_effect = RuntimeError("boom")
        pdfium_page = MagicMock()
        pdfium_page.close.side_effect = RuntimeError("boom")

        es._release_page(plumb_page, pdfium_page)  # must not raise

    def test_release_tolerates_pages_without_close(self) -> None:
        class PlumbNoClose:
            def __init__(self) -> None:
                self.flushed = False

            def flush_cache(self) -> None:
                self.flushed = True

        plumb_page = PlumbNoClose()
        es._release_page(plumb_page, MagicMock())
        assert plumb_page.flushed


# ── AC-1: table-page detection + output contract ──────────────────────────────


class TestTableDetectionAndContract:
    def test_table_page_idxs_recorded_and_passed_to_docling(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        result, ctx = _run_extract(
            monkeypatch,
            tmp_path,
            texts=["A" * 100, "B" * 100, "C" * 100],
            table_counts=[0, 2, 0],
        )

        assert ctx.captured["table_page_idxs"] == [1]
        assert ctx.captured["page_count"] == 3
        assert result["tables_detected"] == 2

    def test_table_free_pdf_reports_zero(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        result, ctx = _run_extract(monkeypatch, tmp_path, texts=["A" * 100, "B" * 100, "C" * 100])

        assert ctx.captured["table_page_idxs"] == []
        assert result["tables_detected"] == 0
        assert result["docling_pages"] == []

    def test_output_contract_preserved_with_additive_keys(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        result, _ = _run_extract(monkeypatch, tmp_path, texts=["A" * 100, "B" * 100, "C" * 100])

        assert set(result) == {
            "raw_text",
            "page_count",
            "image_files",
            "font_blocks",
            "tables_detected",
            "docling_pages",
        }
        assert result["page_count"] == 3
        assert result["image_files"] == []
        assert result["font_blocks"] == []

    def test_page_table_count_prefers_find_tables(self) -> None:
        page = MagicMock()
        page.find_tables.return_value = [object(), object()]

        assert es._page_table_count(page) == 2
        page.extract_tables.assert_not_called()

    def test_page_table_count_falls_back_when_find_tables_absent(self) -> None:
        class LegacyPage:
            def extract_tables(self) -> list[Any]:
                return [[["a"]]]

        assert es._page_table_count(LegacyPage()) == 1

    def test_page_table_count_swallows_errors(self) -> None:
        page = MagicMock()
        page.find_tables.side_effect = RuntimeError("boom")

        assert es._page_table_count(page) == 0


# ── Real-PDF smoke (dev WSL only) ─────────────────────────────────────────────


@pytest.mark.skipif(not os.path.exists("/tmp/mini.pdf"), reason="real test PDF only on dev WSL")
def test_real_mini_pdf_smoke(tmp_path: Any) -> None:
    result = es.extract_pdf("/tmp/mini.pdf", str(tmp_path), 50)

    assert result["page_count"] == 3
    assert result["raw_text"].strip()
    assert result["tables_detected"] == 0
    assert result["docling_pages"] == []
