"""Chapter-scoped generation — Story 1-13 (book-scale Phase 5), AC1-AC7.

Written against "THE CONTRACT" in `docs/stories/1-13-chapter-scoped-generation.md`:

  * `chapter_id` is a required pipeline input on the PDF path; `run_pipeline`
    and `content_pipeline_job` carry it (`lessons.chapter_id`).  (AC1)
  * `extract_node` resolves the chapter's `page_start`/`page_end` and passes
    them to the extraction subprocess as argv 4 and 5.                  (AC2)
  * A missing chapter, or one belonging to a different book, is a HARD ERROR
    naming both ids — **never** a silent fallback to whole-document
    extraction. That silent fallback is the exact defect this whole effort
    exists to remove, so it is tested for by its ABSENCE (the subprocess must
    not be spawned at all), not assumed away.                           (AC3)
  * `chunk_node` no longer writes a `chapters` row; it takes `chapter_id`
    from state and stamps it onto the chunk rows.                  (AC4, AC5)
  * Regenerating the same chapter performs ZERO new embedding API calls —
    asserted by COUNTING provider calls across two full chunk→embed runs
    against one shared chunk store.                                     (AC6)
  * No `or ""` / `.get(..., "")` default survives for `book_id`/`chapter_id`:
    a missing upstream output must produce a diagnostic that names what is
    missing, not a bare Pydantic `ValidationError` after full spend.    (AC7)

Doubles
-------
`_FakeTable` is a small PostgREST-shaped query-builder double: it honours
`.eq()` filters, distinguishes reads from writes, records every write, and
(for `chunks`) is backed by a MUTABLE store so a second pipeline run really
does see what the first run wrote.  That statefulness is what makes the AC6
call-count meaningful — a fresh mock per run could only ever prove that a mock
returns what it was told to.

Patch note: `graph.py` and `content_pipeline.py` use lazy imports inside
function bodies, so patches target the ORIGINAL module
(`app.core.db.get_supabase`), never the consumer.
"""

from __future__ import annotations

import inspect
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── Constants ─────────────────────────────────────────────────────────────────

FAKE_LESSON_ID = "13131313-1313-1313-1313-131313131313"
SECOND_LESSON_ID = "13131313-1313-1313-1313-131313131399"
FAKE_USER_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
FAKE_BOOK_ID = "11111111-1111-1111-1111-111111111111"
OTHER_BOOK_ID = "22222222-2222-2222-2222-222222222222"
FAKE_CHAPTER_ID = "cccccccc-cccc-cccc-cccc-cccccccccccc"
FAKE_PDF_PATH = f"{FAKE_USER_ID}/{FAKE_BOOK_ID}/book.pdf"
FAKE_PDF_BYTES = b"%PDF-1.4 minimal\n%%EOF"

# Chapter 3 of a big book: 0-based, INCLUSIVE (Story 1-12's contract).
CHAPTER_PAGE_START = 41
CHAPTER_PAGE_END = 78

EXTRACT_MODULE = "app.modules.content.pipeline.nodes.extract_subprocess"

SUBPROCESS_STDOUT = json.dumps(
    {
        "raw_text": "Chapter 3: Thermodynamics\n\nBody text.",
        "page_count": 1151,
        "extracted_page_count": CHAPTER_PAGE_END - CHAPTER_PAGE_START + 1,
        "page_offset": CHAPTER_PAGE_START,
        "image_files": [],
        "font_blocks": [],
    }
).encode()

_SECTION_A = {
    "id": "s0",
    "title": "Entropy",
    "level": "section",
    "body": "Entropy is a measure of disorder in a closed system.",
    "page_start": 41,
    "page_end": 44,
}
_SECTION_B = {
    "id": "s1",
    "title": "Heat transfer",
    "level": "section",
    "body": "Heat flows from a hotter body to a colder body.",
    "page_start": 45,
    "page_end": 50,
}


def _chapter_row(book_id: str = FAKE_BOOK_ID) -> dict[str, Any]:
    return {
        "chapter_id": FAKE_CHAPTER_ID,
        "book_id": book_id,
        "lesson_id": None,
        "title": "Chapter 3 — Thermodynamics",
        "chapter_index": 3,
        "page_start": CHAPTER_PAGE_START,
        "page_end": CHAPTER_PAGE_END,
    }


# ── PostgREST-shaped doubles ──────────────────────────────────────────────────


class _Response:
    """Minimal postgrest response: `.data` plus a `.count` (head/count selects)."""

    def __init__(self, data: Any) -> None:  # noqa: ANN401 — mirrors postgrest
        self.data = data
        if isinstance(data, list):
            self.count = len(data)
        else:
            self.count = 0 if data is None else 1


_CHAINABLE = (
    "select",
    "eq",
    "neq",
    "is_",
    "in_",
    "order",
    "range",
    "limit",
    "gte",
    "lte",
    "not_",
)
_WRITES = ("insert", "upsert", "update", "delete")


class _FakeTable:
    """A PostgREST query-builder double that honours `.eq()` and records writes.

    `select_router(methods, eq_filters)` overrides the default "filter the
    stored rows by the eq() predicates" read behaviour; `write_handler(kind,
    args, kwargs)` overrides what a write returns (and may mutate a store).
    """

    def __init__(
        self,
        name: str,
        rows: list[dict[str, Any]] | None = None,
        *,
        select_router: Any = None,  # noqa: ANN401
        write_handler: Any = None,  # noqa: ANN401
        merge_updates: bool = False,
    ) -> None:
        self.name = name
        self.rows: list[dict[str, Any]] = list(rows or [])
        self.writes: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.selects: list[dict[str, Any]] = []
        self._select_router = select_router
        self._write_handler = write_handler
        self._merge_updates = merge_updates
        self._reset()

    # -- chain bookkeeping -------------------------------------------------
    def _reset(self) -> None:
        self._methods: list[str] = []
        self._eq: dict[str, Any] = {}
        self._single = False
        self._pending: tuple[str, tuple[Any, ...], dict[str, Any]] | None = None

    def __getattr__(self, item: str) -> Any:  # noqa: ANN401
        if item in _CHAINABLE:

            def _chain(*args: Any, **kwargs: Any) -> _FakeTable:
                if item == "select" and self._pending is None:
                    self._reset()
                self._methods.append(item)
                if item == "eq" and len(args) == 2:
                    self._eq[args[0]] = args[1]
                return self

            return _chain
        if item in _WRITES:

            def _write(*args: Any, **kwargs: Any) -> _FakeTable:
                self._reset()
                self._pending = (item, args, kwargs)
                return self

            return _write
        raise AttributeError(item)

    def single(self) -> _FakeTable:
        self._methods.append("single")
        self._single = True
        return self

    def maybe_single(self) -> _FakeTable:
        return self.single()

    # -- terminal ----------------------------------------------------------
    def execute(self) -> _Response:
        if self._pending is not None:
            kind, args, kwargs = self._pending
            eq_filters = dict(self._eq)
            self.writes.append((kind, args, kwargs))
            self._reset()
            if self._write_handler is not None:
                return _Response(self._write_handler(kind, args, kwargs))
            if kind == "update" and self._merge_updates and args:
                for row in self.rows:
                    if all(row.get(k) == v for k, v in eq_filters.items()):
                        row.update(args[0])
                return _Response(list(self.rows))
            return _Response([dict(r) for r in self.rows])

        methods, eq_filters, single = list(self._methods), dict(self._eq), self._single
        self.selects.append({"methods": methods, "eq": eq_filters})
        self._reset()
        if self._select_router is not None:
            data = self._select_router(methods, eq_filters)
        else:
            data = [dict(r) for r in self.rows if all(r.get(k) == v for k, v in eq_filters.items())]
        if single:
            return _Response(data[0] if data else None)
        return _Response(data)

    # -- assertions --------------------------------------------------------
    def write_kinds(self) -> list[str]:
        return [kind for kind, _a, _k in self.writes]


class _FakeSupabase:
    """`sb.table(name)` returns a stable `_FakeTable`; storage is a MagicMock."""

    def __init__(self, tables: dict[str, _FakeTable]) -> None:
        self._tables = tables
        self.storage = MagicMock()
        self.storage.from_.return_value.download.return_value = FAKE_PDF_BYTES
        self.table_names: list[str] = []

    def table(self, name: str) -> _FakeTable:
        self.table_names.append(name)
        if name not in self._tables:
            self._tables[name] = _FakeTable(name)
        return self._tables[name]

    def __getitem__(self, name: str) -> _FakeTable:
        return self.table(name)


def _jobs_table(lesson_id: str, node_outputs: dict[str, Any] | None = None) -> _FakeTable:
    """lesson_jobs double that is STATEFUL: an update merges into the row, so a
    checkpoint written by chunk_node is visible to embed_node in the same run."""
    return _FakeTable(
        "lesson_jobs",
        rows=[{"lesson_id": lesson_id, "node_outputs": dict(node_outputs or {})}],
        merge_updates=True,
    )


def _make_subprocess_mock(stdout: bytes | None = None, returncode: int = 0) -> AsyncMock:
    proc = MagicMock()
    proc.returncode = returncode
    proc.communicate = AsyncMock(return_value=(stdout or SUBPROCESS_STDOUT, b""))
    return AsyncMock(return_value=proc)


def _make_tiktoken_patch() -> dict[str, Any]:
    """Fake tiktoken where one whitespace-separated word == one token."""
    enc = MagicMock()
    enc.encode.side_effect = lambda text: text.split()
    enc.decode.side_effect = lambda tokens: " ".join(tokens)
    module = MagicMock()
    module.get_encoding.return_value = enc
    return {"tiktoken": module}


def _configure_settings(mock_settings: MagicMock) -> None:
    """Real numbers for every settings field the nodes under test do maths on."""
    cfg = mock_settings.return_value
    # extract_node
    cfg.ocr_text_yield_threshold = 50
    cfg.extract_timeout_base_s = 120
    cfg.extract_timeout_per_page_s = 1.3
    cfg.extract_timeout_cap_s = 1500
    cfg.arq_job_timeout_s = 1800
    # chunk_node
    cfg.chunk_target_tokens = 512
    cfg.chunk_overlap_tokens = 64
    cfg.embedding_tokenizer = "cl100k_base"
    # embed_node
    cfg.embedding_model = "text-embedding-3-small"
    cfg.embedding_dimensions = 1536
    cfg.embed_batch_token_budget = 100_000


def _extract_state(**overrides: Any) -> dict[str, Any]:
    state: dict[str, Any] = {
        "lesson_id": FAKE_LESSON_ID,
        "user_id": FAKE_USER_ID,
        "book_id": FAKE_BOOK_ID,
        "chapter_id": FAKE_CHAPTER_ID,
        "source_pdf_path": FAKE_PDF_PATH,
        "chapter_content": "",
        "progress_pct": 0.0,
        "error": None,
    }
    state.update(overrides)
    return state


def _chunk_state(**overrides: Any) -> dict[str, Any]:
    state: dict[str, Any] = {
        "lesson_id": FAKE_LESSON_ID,
        "book_id": FAKE_BOOK_ID,
        "chapter_id": FAKE_CHAPTER_ID,
        "sections": [dict(_SECTION_A), dict(_SECTION_B)],
        "progress_pct": 14.0,
        "error": None,
    }
    state.update(overrides)
    return state


def _extract_argv(exec_mock: AsyncMock) -> list[Any]:
    """Positional argv AFTER `-m <module>` from the recorded spawn."""
    args = list(exec_mock.await_args.args)
    assert EXTRACT_MODULE in args, f"extraction module not in spawn argv: {args}"
    return args[args.index(EXTRACT_MODULE) + 1 :]


# ══════════════════════════════════════════════════════════════════════════════
# AC1 — chapter_id is a pipeline input and reaches run_pipeline
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
def test_ac1_pipeline_state_declares_chapter_id() -> None:
    """AC1: `chapter_id` is a declared PipelineState channel, typed `str`.

    Without the annotation the value cannot survive a LangGraph node hop —
    StateGraph drops keys that are not channels, so extract_node would read a
    chapter_id that chunk_node never sees.
    """
    from typing import get_type_hints

    from app.modules.content.pipeline.graph import PipelineState

    annotations = PipelineState.__annotations__
    assert "chapter_id" in annotations, (
        f"PipelineState has no `chapter_id` channel; declared inputs: {sorted(annotations)}"
    )
    # `from __future__ import annotations` makes the raw values ForwardRefs —
    # resolve them so the assertion is about the TYPE, not its spelling.
    hints = get_type_hints(PipelineState, include_extras=True)
    assert hints["chapter_id"] is str, (
        f"chapter_id must be a plain `str` channel; got {hints['chapter_id']!r}"
    )


@pytest.mark.unit
def test_ac1_run_pipeline_accepts_chapter_id() -> None:
    """AC1: `run_pipeline` takes `chapter_id` as a keyword with a default, so
    the raw-text callers that pass no chapter keep working."""
    from app.modules.content.pipeline.graph import run_pipeline

    params = inspect.signature(run_pipeline).parameters
    assert "chapter_id" in params, f"run_pipeline has no chapter_id: {list(params)}"
    assert params["chapter_id"].default == "", (
        "chapter_id must default to empty so the raw-text (`chapter_content`) path "
        f"stays callable; got default={params['chapter_id'].default!r}"
    )


@pytest.mark.unit
async def test_ac1_run_pipeline_seeds_chapter_id_into_initial_state() -> None:
    """AC1: the chapter_id argument reaches the graph's initial state."""
    from app.modules.content.pipeline import graph as graph_mod

    captured: dict[str, Any] = {}

    async def _ainvoke(state: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
        captured.update(state)
        return {"lesson_package": {"lesson_id": FAKE_LESSON_ID}}

    fake_graph = MagicMock()
    fake_graph.ainvoke = AsyncMock(side_effect=_ainvoke)

    with patch.object(graph_mod, "get_pipeline_graph", return_value=fake_graph):
        await graph_mod.run_pipeline(
            lesson_id=FAKE_LESSON_ID,
            user_id=FAKE_USER_ID,
            source_pdf_path=FAKE_PDF_PATH,
            book_id=FAKE_BOOK_ID,
            chapter_id=FAKE_CHAPTER_ID,
        )

    assert captured.get("chapter_id") == FAKE_CHAPTER_ID, (
        f"initial pipeline state is missing chapter_id: {sorted(captured)}"
    )
    assert captured.get("book_id") == FAKE_BOOK_ID


@pytest.mark.unit
async def test_ac1_raw_text_path_still_runs_without_a_chapter_id() -> None:
    """AC1: the `chapter_content` path (raw text, no PDF, no chapter) is
    untouched — `chapter_id` is only required on the PDF path."""
    from app.modules.content.pipeline import graph as graph_mod

    captured: dict[str, Any] = {}

    async def _ainvoke(state: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
        captured.update(state)
        return {"lesson_package": {"lesson_id": FAKE_LESSON_ID}}

    fake_graph = MagicMock()
    fake_graph.ainvoke = AsyncMock(side_effect=_ainvoke)

    with patch.object(graph_mod, "get_pipeline_graph", return_value=fake_graph):
        await graph_mod.run_pipeline(
            lesson_id=FAKE_LESSON_ID,
            chapter_content="Raw chapter text passed straight in, with no PDF at all.",
        )

    assert captured["chapter_content"].startswith("Raw chapter text")
    assert captured["source_pdf_path"] == ""
    assert not captured.get("chapter_id"), (
        "the raw-text path must not invent a chapter_id — it has no chapter row"
    )


@pytest.mark.unit
async def test_ac1_content_pipeline_job_reads_lessons_chapter_id_and_passes_it() -> None:
    """AC1: `content_pipeline_job` selects `lessons.chapter_id` (the column
    Phase 2 added and nothing has read yet) and forwards it to run_pipeline.

    Both halves are asserted: the SELECT must name the column (a double returns
    whatever it is told regardless of the projection, so passing the value on
    proves nothing about the query), and run_pipeline must receive it.
    """
    from app.workers.jobs.content_pipeline import content_pipeline_job

    select_args: list[Any] = []
    run_pipeline_kwargs: dict[str, Any] = {}

    def _table(name: str) -> MagicMock:
        t = MagicMock()
        if name == "lessons":

            def _select(*args: Any, **kwargs: Any) -> MagicMock:
                select_args.extend(args)
                return t.select.return_value

            t.select.side_effect = _select
            t.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {
                "user_id": FAKE_USER_ID,
                "source_file_path": FAKE_PDF_PATH,
                "book_id": FAKE_BOOK_ID,
                "chapter_id": FAKE_CHAPTER_ID,
                "tier": "T2",
            }
        return t

    sb = MagicMock()
    sb.table.side_effect = _table

    async def _mock_run_pipeline(**kwargs: Any) -> dict[str, Any]:
        run_pipeline_kwargs.update(kwargs)
        return {"lesson_id": FAKE_LESSON_ID, "segments": []}

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.modules.content.pipeline.graph.run_pipeline", side_effect=_mock_run_pipeline),
        patch("app.core.cost_tracker.clear_lesson_cost", new_callable=AsyncMock),
        patch("app.core.redis.get_redis", return_value=AsyncMock()),
    ):
        await content_pipeline_job({}, FAKE_LESSON_ID)

    projection = " ".join(str(a) for a in select_args)
    assert "chapter_id" in projection, (
        f"content_pipeline_job must SELECT lessons.chapter_id; projection was {projection!r}"
    )
    assert run_pipeline_kwargs.get("chapter_id") == FAKE_CHAPTER_ID, (
        f"run_pipeline did not receive chapter_id; got {run_pipeline_kwargs}"
    )


# ══════════════════════════════════════════════════════════════════════════════
# AC2 — extract_node passes the chapter's page bounds to the subprocess
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
async def test_ac2_extract_node_passes_chapter_bounds_as_argv_4_and_5() -> None:
    """AC2: the chapter row's page_start/page_end are argv 4 and 5, positionally.

    The subprocess CLI is `<pdf> <img_dir> <ocr_threshold> [page_start]
    [page_end]` — position is the whole contract, so this asserts the actual
    spawn argv (not that "some argument somewhere equals 41"), and that the
    values are the CHAPTER ROW's, not derived from anything else.

    # MOCK-CONTRACT: this asserts the spawn shape only. That those two argv
    # positions actually restrict extraction to that page range is proven
    # against real PDFs by tests/unit/test_extract_page_bounds.py (Story 1-12),
    # which invokes the module as a real subprocess.
    """
    from app.modules.content.pipeline.graph import extract_node

    tables = {
        "lesson_jobs": _jobs_table(FAKE_LESSON_ID),
        "chapters": _FakeTable("chapters", rows=[_chapter_row()]),
    }
    sb = _FakeSupabase(tables)
    exec_mock = _make_subprocess_mock()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.config.get_settings") as mock_settings,
        patch("asyncio.create_subprocess_exec", exec_mock),
        patch("app.modules.content.pipeline.graph._update_job_progress", new_callable=AsyncMock),
    ):
        _configure_settings(mock_settings)
        await extract_node(_extract_state())

    exec_mock.assert_awaited_once()
    argv = _extract_argv(exec_mock)

    assert len(argv) == 5, (
        "the subprocess must be spawned with exactly 5 positional arguments "
        f"(pdf, img_dir, ocr_threshold, page_start, page_end); got {argv!r}"
    )
    assert str(argv[0]).endswith(".pdf"), f"argv 1 must be the local PDF path; got {argv[0]!r}"
    assert str(argv[2]) == "50", f"argv 3 must stay the OCR threshold; got {argv[2]!r}"
    assert argv[3] == str(CHAPTER_PAGE_START), (
        f"argv 4 must be the chapter row's page_start ({CHAPTER_PAGE_START}); got {argv[3]!r}"
    )
    assert argv[4] == str(CHAPTER_PAGE_END), (
        f"argv 5 must be the chapter row's page_end ({CHAPTER_PAGE_END}); got {argv[4]!r}"
    )
    # create_subprocess_exec rejects non-str argv at runtime.
    assert isinstance(argv[3], str) and isinstance(argv[4], str)


@pytest.mark.unit
async def test_ac2_extract_node_bounds_track_the_chapter_row_not_a_constant() -> None:
    """AC2: a different chapter row yields different bounds.

    Guards the failure mode where the bounds are hardcoded (or read off the
    wrong row) and the previous test passes for the wrong reason.
    """
    from app.modules.content.pipeline.graph import extract_node

    row = _chapter_row()
    row["page_start"] = 900
    row["page_end"] = 941

    sb = _FakeSupabase(
        {
            "lesson_jobs": _jobs_table(FAKE_LESSON_ID),
            "chapters": _FakeTable("chapters", rows=[row]),
        }
    )
    exec_mock = _make_subprocess_mock()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.config.get_settings") as mock_settings,
        patch("asyncio.create_subprocess_exec", exec_mock),
        patch("app.modules.content.pipeline.graph._update_job_progress", new_callable=AsyncMock),
    ):
        _configure_settings(mock_settings)
        await extract_node(_extract_state())

    argv = _extract_argv(exec_mock)
    assert (argv[3], argv[4]) == ("900", "941"), f"bounds did not follow the chapter row: {argv!r}"


@pytest.mark.unit
async def test_ac2_extract_node_looks_the_chapter_up_by_its_id() -> None:
    """AC2 premise: the chapter row is fetched by `chapter_id`.

    A resolver that queried by lesson_id (the pre-Phase-5 shape of `chapters`)
    would still find a row in production and silently extract the wrong pages.
    """
    from app.modules.content.pipeline.graph import extract_node

    chapters = _FakeTable("chapters", rows=[_chapter_row()])
    sb = _FakeSupabase({"lesson_jobs": _jobs_table(FAKE_LESSON_ID), "chapters": chapters})

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.config.get_settings") as mock_settings,
        patch("asyncio.create_subprocess_exec", _make_subprocess_mock()),
        patch("app.modules.content.pipeline.graph._update_job_progress", new_callable=AsyncMock),
    ):
        _configure_settings(mock_settings)
        await extract_node(_extract_state())

    assert chapters.selects, "extract_node never read the `chapters` table"
    assert any(q["eq"].get("chapter_id") == FAKE_CHAPTER_ID for q in chapters.selects), (
        f"chapters was not queried by chapter_id={FAKE_CHAPTER_ID}; queries: {chapters.selects}"
    )


# ══════════════════════════════════════════════════════════════════════════════
# AC3 — a missing / foreign chapter is a hard error, never a fallback
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
async def test_ac3_missing_chapter_raises_naming_both_ids() -> None:
    """AC3: no chapter row for `chapter_id` → raise, naming chapter_id AND book_id."""
    from app.modules.content.pipeline.graph import extract_node

    sb = _FakeSupabase(
        {
            "lesson_jobs": _jobs_table(FAKE_LESSON_ID),
            "chapters": _FakeTable("chapters", rows=[]),  # chapter does not exist
        }
    )
    exec_mock = _make_subprocess_mock()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.config.get_settings") as mock_settings,
        patch("asyncio.create_subprocess_exec", exec_mock),
        patch("app.modules.content.pipeline.graph._update_job_progress", new_callable=AsyncMock),
    ):
        _configure_settings(mock_settings)
        with pytest.raises(Exception) as excinfo:  # noqa: B017, PT011
            await extract_node(_extract_state())

    message = str(excinfo.value)
    assert FAKE_CHAPTER_ID in message, f"error must name the chapter_id; got: {message!r}"
    assert FAKE_BOOK_ID in message, f"error must name the book_id; got: {message!r}"


@pytest.mark.unit
async def test_ac3_missing_chapter_does_not_fall_back_to_whole_document() -> None:
    """AC3: the silent whole-document fallback must be ABSENT, not assumed absent.

    This is the defect the entire book-scale effort exists to remove: extracting
    1,151 pages when one 38-page chapter was asked for, with nothing saying so.
    Tested by observation — the extraction subprocess must never be spawned.
    """
    from app.modules.content.pipeline.graph import extract_node

    jobs = _jobs_table(FAKE_LESSON_ID)
    sb = _FakeSupabase({"lesson_jobs": jobs, "chapters": _FakeTable("chapters", rows=[])})
    exec_mock = _make_subprocess_mock()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.config.get_settings") as mock_settings,
        patch("asyncio.create_subprocess_exec", exec_mock),
        patch("app.modules.content.pipeline.graph._update_job_progress", new_callable=AsyncMock),
    ):
        _configure_settings(mock_settings)
        with pytest.raises(Exception):  # noqa: B017, PT011
            await extract_node(_extract_state())

    exec_mock.assert_not_awaited()
    assert exec_mock.call_args_list == [], (
        "extract_node fell back to whole-document extraction after failing to resolve "
        "the chapter — AC3 forbids any fallback"
    )
    # A failed resolution must not leave an `extract` checkpoint behind either:
    # a cached whole-book extraction would survive the fix and poison retries.
    assert jobs.write_kinds() == [], f"extract_node checkpointed a failed run: {jobs.writes}"


@pytest.mark.unit
async def test_ac3_chapter_from_a_different_book_raises_naming_both_ids() -> None:
    """AC3: a chapter row that exists but belongs to another book → raise.

    An IDOR-shaped case as much as a correctness one: `chapter_id` arrives from
    a row the caller influences, so the book must be re-checked here.
    """
    from app.modules.content.pipeline.graph import extract_node

    sb = _FakeSupabase(
        {
            "lesson_jobs": _jobs_table(FAKE_LESSON_ID),
            # Row exists, but under OTHER_BOOK_ID — the lesson's book is FAKE_BOOK_ID.
            "chapters": _FakeTable("chapters", rows=[_chapter_row(book_id=OTHER_BOOK_ID)]),
        }
    )
    exec_mock = _make_subprocess_mock()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.config.get_settings") as mock_settings,
        patch("asyncio.create_subprocess_exec", exec_mock),
        patch("app.modules.content.pipeline.graph._update_job_progress", new_callable=AsyncMock),
    ):
        _configure_settings(mock_settings)
        with pytest.raises(Exception) as excinfo:  # noqa: B017, PT011
            await extract_node(_extract_state())

    message = str(excinfo.value)
    assert FAKE_CHAPTER_ID in message, f"error must name the chapter_id; got: {message!r}"
    assert FAKE_BOOK_ID in message, (
        f"error must name the lesson's book_id ({FAKE_BOOK_ID}); got: {message!r}"
    )
    exec_mock.assert_not_awaited()
    assert exec_mock.call_args_list == [], (
        "a chapter belonging to a different book must NOT be extracted — and must "
        "not degrade into a whole-document extraction either"
    )


# ══════════════════════════════════════════════════════════════════════════════
# AC4 / AC5 — chunk_node writes no chapter row and stamps the state chapter_id
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
async def test_ac4_chunk_node_creates_no_chapter_row() -> None:
    """AC4: the hardcoded `chapters` upsert (graph.py:609-651) is gone.

    `book_ingest_job` is the sole writer of `chapters` — a pipeline that also
    invents a chapter row is exactly how a 1,151-page book ended up with one
    chapter covering 4 % of itself.
    """
    from app.modules.content.pipeline.graph import chunk_node

    chapters = _FakeTable("chapters", rows=[_chapter_row()])
    sb = _FakeSupabase(
        {
            "lesson_jobs": _jobs_table(FAKE_LESSON_ID),
            "chapters": chapters,
            "chunks": _FakeTable("chunks"),
        }
    )

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.config.get_settings") as mock_settings,
        patch.dict("sys.modules", _make_tiktoken_patch()),
        patch("app.modules.content.pipeline.graph._update_job_progress", new_callable=AsyncMock),
    ):
        _configure_settings(mock_settings)
        await chunk_node(_chunk_state())

    assert chapters.write_kinds() == [], (
        f"chunk_node still writes `chapters` — AC4 requires the row to come from "
        f"book_ingest_job only. Writes: {chapters.writes}"
    )


@pytest.mark.unit
async def test_ac5_chunk_rows_carry_the_state_chapter_id() -> None:
    """AC5: every chunk row written carries state['chapter_id'] verbatim."""
    from app.modules.content.pipeline.graph import chunk_node

    chunks = _FakeTable("chunks")
    sb = _FakeSupabase(
        {
            "lesson_jobs": _jobs_table(FAKE_LESSON_ID),
            "chapters": _FakeTable("chapters", rows=[_chapter_row()]),
            "chunks": chunks,
        }
    )

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.config.get_settings") as mock_settings,
        patch.dict("sys.modules", _make_tiktoken_patch()),
        patch("app.modules.content.pipeline.graph._update_job_progress", new_callable=AsyncMock),
    ):
        _configure_settings(mock_settings)
        result = await chunk_node(_chunk_state())

    assert result["chunks"], "chunk_node produced no chunks — the AC5 assertion would be vacuous"
    written = [w for w in chunks.writes if w[0] in ("insert", "upsert")]
    assert written, f"chunk_node wrote no chunk rows: {chunks.writes}"

    rows: list[dict[str, Any]] = []
    for _kind, args, _kwargs in written:
        payload = args[0]
        rows.extend(payload if isinstance(payload, list) else [payload])

    assert rows
    for row in rows:
        assert row["chapter_id"] == FAKE_CHAPTER_ID, (
            f"chunk row carries chapter_id={row['chapter_id']!r}, expected the state's "
            f"{FAKE_CHAPTER_ID!r}"
        )
        assert row["book_id"] == FAKE_BOOK_ID


# ══════════════════════════════════════════════════════════════════════════════
# AC6 — regenerating the same chapter performs ZERO new embedding calls
# ══════════════════════════════════════════════════════════════════════════════


def _chunk_store_tables(store: list[dict[str, Any]]) -> _FakeTable:
    """A `chunks` table double backed by a MUTABLE row store.

    # MOCK-CONTRACT: this double stands in for Postgres. It models exactly two
    # behaviours the reuse decision depends on — (a) rows written for a
    # chapter_id are visible to a later read of that chapter_id, and (b) a row
    # with a non-NULL embedding drops out of an `embedding IS NULL` filter.
    # That those two behaviours hold against real Postgres (including the
    # chunks NOT NULL columns and the ON CONFLICT arbitration) is proven by
    # tests/integration/test_migration_chapters_book_scoped.py and by
    # tests/unit/test_embed_node.py's writeback-shape assertions.
    """

    def _select(methods: list[str], eq: dict[str, Any]) -> list[dict[str, Any]]:
        chapter_id = eq.get("chapter_id")
        found = [r for r in store if chapter_id is None or r.get("chapter_id") == chapter_id]
        if "is_" in methods:  # `.is_("embedding", "null")`
            found = [r for r in found if r.get("embedding") is None]
        return [dict(r) for r in found]

    def _write(kind: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> list[dict[str, Any]]:
        if kind not in ("insert", "upsert") or not args:
            return []
        payload = args[0]
        incoming = payload if isinstance(payload, list) else [payload]
        out: list[dict[str, Any]] = []
        for row in incoming:
            chunk_id = row.get("chunk_id")
            existing = None
            if chunk_id:
                existing = next((r for r in store if r["chunk_id"] == chunk_id), None)
            if existing is None:
                created = dict(row)
                created.setdefault("chunk_id", f"chunk-{len(store)}")
                created.setdefault("embedding", None)
                store.append(created)
                existing = created
            else:
                existing.update(row)
            out.append(dict(existing))
        return out

    return _FakeTable("chunks", select_router=_select, write_handler=_write)


async def _chunk_then_embed(
    lesson_id: str,
    store: list[dict[str, Any]],
    provider_cls: MagicMock,
) -> dict[str, _FakeTable]:
    """Run chunk_node then embed_node for one lesson against the shared store."""
    from app.modules.content.pipeline.graph import chunk_node, embed_node

    tables = {
        "lesson_jobs": _jobs_table(lesson_id),
        "chapters": _FakeTable("chapters", rows=[_chapter_row()]),
        "chunks": _chunk_store_tables(store),
    }
    sb = _FakeSupabase(tables)
    state = _chunk_state(lesson_id=lesson_id)

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.config.get_settings") as mock_settings,
        patch.dict("sys.modules", _make_tiktoken_patch()),
        patch("app.modules.content.pipeline.graph._update_job_progress", new_callable=AsyncMock),
        patch("app.providers.embeddings.openai.OpenAIEmbeddingsProvider", provider_cls),
    ):
        _configure_settings(mock_settings)
        chunk_out = await chunk_node(state)
        await embed_node({**state, **chunk_out})

    return tables


def _counting_provider_cls() -> MagicMock:
    """Provider class double that COUNTS embedding API calls.

    # MOCK-CONTRACT: counts calls only — it asserts nothing about OpenAI's
    # behaviour. The real request/response contract (batching, token budget,
    # 1536-dim writeback) is covered by tests/unit/test_embed_node.py and
    # tests/unit/test_provider_tracing_resilience.py.
    """
    provider = AsyncMock()

    async def _embed(texts: list[str]) -> tuple[list[list[float]], int]:
        return [[0.1] * 1536 for _ in texts], 10 * len(texts)

    provider.embed_texts.side_effect = _embed
    cls = MagicMock(return_value=provider)
    cls.provider = provider
    return cls


@pytest.mark.unit
async def test_ac6_regenerating_the_same_chapter_makes_zero_embedding_calls() -> None:
    """AC6 — THE load-bearing test. Two lessons, same chapter, one embedding spend.

    Counted, not inspected: the second run must call the embeddings API exactly
    zero times. The chunk store is shared between the runs and is stateful, so
    the second run really is reading what the first run wrote.
    """
    store: list[dict[str, Any]] = []

    first_cls = _counting_provider_cls()
    first_tables = await _chunk_then_embed(FAKE_LESSON_ID, store, first_cls)

    # Premise: run 1 DID spend. A counter that is zero both times proves nothing.
    assert first_cls.provider.embed_texts.await_count >= 1, (
        "the first run made no embedding calls at all — the AC6 comparison would be "
        "vacuous (nothing was ever embedded, so nothing could be reused)"
    )
    assert store, "the first run persisted no chunks; there is nothing to reuse"
    assert all(r.get("embedding") is not None for r in store), (
        f"the first run left chunks unembedded: {[r.get('chunk_index') for r in store]}"
    )
    first_chunk_ids = [r["chunk_id"] for r in store]

    # ── Regeneration: a NEW lesson over the SAME chapter ─────────────────────
    second_cls = _counting_provider_cls()
    second_tables = await _chunk_then_embed(SECOND_LESSON_ID, store, second_cls)

    assert second_cls.call_count == 0, (
        f"the embeddings provider was CONSTRUCTED {second_cls.call_count} time(s) on "
        "regeneration — chunks for this chapter already exist and must be reused "
        "(CLAUDE.md: chunk embeddings at ingestion only)"
    )
    assert second_cls.provider.embed_texts.await_count == 0, (
        f"regenerating the same chapter made "
        f"{second_cls.provider.embed_texts.await_count} embedding API call(s); AC6 requires 0"
    )

    # Reuse, not re-creation: the same chunk rows, untouched.
    assert [r["chunk_id"] for r in store] == first_chunk_ids, (
        "regeneration created new chunk rows instead of reusing the existing ones"
    )
    assert second_tables["chunks"].write_kinds() == [], (
        f"regeneration re-wrote `chunks`: {second_tables['chunks'].writes}"
    )
    # And the first run is unaffected by the assertion machinery.
    assert first_tables["chunks"].write_kinds(), "sanity: run 1 must have written chunks"


@pytest.mark.unit
async def test_ac6_reuse_skips_chunking_work_entirely() -> None:
    """AC6: reuse skips CHUNKING too, not just embedding.

    Re-tokenising the chapter is wasted CPU, but worse: it can produce a
    different chunk set from the one whose embeddings are already stored, so
    the lesson and the vectors would describe different text.
    """
    from app.modules.content.pipeline.graph import chunk_node

    store: list[dict[str, Any]] = [
        {
            "chunk_id": "chunk-0",
            "chapter_id": FAKE_CHAPTER_ID,
            "book_id": FAKE_BOOK_ID,
            "section": "Entropy",
            "content": "Entropy is a measure of disorder in a closed system.",
            "chunk_index": 0,
            "token_count": 9,
            "page_start": 41,
            "page_end": 44,
            "embedding": [0.1] * 1536,
        }
    ]
    chunks_table = _chunk_store_tables(store)
    sb = _FakeSupabase(
        {
            "lesson_jobs": _jobs_table(SECOND_LESSON_ID),
            "chapters": _FakeTable("chapters", rows=[_chapter_row()]),
            "chunks": chunks_table,
        }
    )

    tiktoken_patch = _make_tiktoken_patch()
    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.config.get_settings") as mock_settings,
        patch.dict("sys.modules", tiktoken_patch),
        patch("app.modules.content.pipeline.graph._update_job_progress", new_callable=AsyncMock),
    ):
        _configure_settings(mock_settings)
        result = await chunk_node(_chunk_state(lesson_id=SECOND_LESSON_ID))

    tiktoken_patch["tiktoken"].get_encoding.assert_not_called()
    assert chunks_table.write_kinds() == [], (
        f"chunk_node re-wrote chunk rows that already exist: {chunks_table.writes}"
    )
    assert result["chunks"], "the reused chunks must still be returned on state"


# ══════════════════════════════════════════════════════════════════════════════
# AC7 — D33: no empty-string default for book_id / chapter_id
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
async def test_ac7_missing_chapter_id_on_the_pdf_path_is_diagnosed_at_extract() -> None:
    """AC7/D33: a missing chapter_id must fail LOUDLY at the first node that
    needs it, naming what is missing — not coerce to "" and travel downstream.

    An empty string can never satisfy the UUID fields at
    schemas/lesson.py:212-213, so the old default turned a missing upstream
    output into a bare Pydantic ValidationError at package_builder — i.e. after
    the entire lesson had already been paid for.
    """
    from app.modules.content.pipeline.graph import extract_node

    sb = _FakeSupabase(
        {
            "lesson_jobs": _jobs_table(FAKE_LESSON_ID),
            "chapters": _FakeTable("chapters", rows=[_chapter_row()]),
        }
    )
    exec_mock = _make_subprocess_mock()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.config.get_settings") as mock_settings,
        patch("asyncio.create_subprocess_exec", exec_mock),
        patch("app.modules.content.pipeline.graph._update_job_progress", new_callable=AsyncMock),
    ):
        _configure_settings(mock_settings)
        with pytest.raises(Exception) as excinfo:  # noqa: B017, PT011
            await extract_node(_extract_state(chapter_id=""))

    message = str(excinfo.value)
    assert "chapter_id" in message, (
        f"the diagnostic must name the missing input (`chapter_id`); got: {message!r}"
    )
    assert FAKE_LESSON_ID in message, f"the diagnostic must name the lesson; got: {message!r}"
    exec_mock.assert_not_awaited()


@pytest.mark.unit
async def test_ac7_missing_book_id_is_diagnosed_not_coerced_to_empty_string() -> None:
    """AC7/D33: `state.get("book_id") or ""` is gone from chunk_node.

    The coercion pushed an empty string at a NOT NULL uuid column and relied on
    Postgres to produce the error — which a Supabase mock can never do
    (binding rule 4), so it was invisible in every test.
    """
    from app.modules.content.pipeline.graph import chunk_node

    chunks = _FakeTable("chunks")
    sb = _FakeSupabase(
        {
            "lesson_jobs": _jobs_table(FAKE_LESSON_ID),
            "chapters": _FakeTable("chapters", rows=[_chapter_row()]),
            "chunks": chunks,
        }
    )

    state = _chunk_state()
    del state["book_id"]

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.config.get_settings") as mock_settings,
        patch.dict("sys.modules", _make_tiktoken_patch()),
        patch("app.modules.content.pipeline.graph._update_job_progress", new_callable=AsyncMock),
    ):
        _configure_settings(mock_settings)
        with pytest.raises(Exception) as excinfo:  # noqa: B017, PT011
            await chunk_node(state)

    message = str(excinfo.value)
    assert "book_id" in message, (
        f"the diagnostic must name the missing input (`book_id`); got: {message!r}"
    )
    written_rows = [
        row
        for _kind, args, _kwargs in chunks.writes
        if args
        for row in (args[0] if isinstance(args[0], list) else [args[0]])
    ]
    assert all(row.get("book_id") != "" for row in written_rows), (
        f"a chunk row was written with an empty-string book_id: {written_rows}"
    )


@pytest.mark.unit
async def test_ac7_package_builder_diagnoses_a_missing_chapter_id() -> None:
    """AC7/D33: package_builder must not default chapter_id to "".

    The failure this closes: `.get("chapter_id", "")` produced a bare
    `ValidationError` on a `UUID` field at the very last node, after full spend,
    with nothing in the message about which upstream output was missing.
    """
    from pydantic import ValidationError

    from app.modules.content.pipeline.graph import package_builder_node

    sb = _FakeSupabase(
        {
            # No `chunk` checkpoint, and no chapter_id on state either.
            "lesson_jobs": _jobs_table(FAKE_LESSON_ID, node_outputs={}),
            "lessons": _FakeTable("lessons", rows=[{"lesson_id": FAKE_LESSON_ID}]),
        }
    )

    state: dict[str, Any] = {
        "lesson_id": FAKE_LESSON_ID,
        "book_id": FAKE_BOOK_ID,
        "lesson_plan": {
            "title": "Thermodynamics",
            "subject": "Physics",
            "total_segments": 1,
            "total_duration_min": 6.0,
            "complexity_level": "medium",
            "segments": [
                {
                    "segment_id": "sec_0",
                    "title": "Entropy",
                    "summary": "Intro to entropy.",
                    "duration_min": 6.0,
                }
            ],
        },
        "tier": "T2",
        "complexity_scores": [],
        "slides": [],
        "slide_images": [],
        "audio_assets": [],
        "narration_scripts": [],
        "quiz_questions": [],
        "glossary": [],
        "intervention_prompts": [],
        "progress_pct": 93.0,
        "error": None,
    }

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.config.get_settings") as mock_settings,
        patch("app.modules.content.pipeline.graph._update_job_progress", new_callable=AsyncMock),
    ):
        _configure_settings(mock_settings)
        with pytest.raises(Exception) as excinfo:  # noqa: B017, PT011
            await package_builder_node(state)

    assert not isinstance(excinfo.value, ValidationError), (
        "a missing chapter_id still surfaces as a bare Pydantic ValidationError — D33 "
        f"requires a diagnostic naming the missing upstream output. Got: {excinfo.value!r}"
    )
    assert "chapter_id" in str(excinfo.value), (
        f"the diagnostic must name `chapter_id`; got: {str(excinfo.value)!r}"
    )
