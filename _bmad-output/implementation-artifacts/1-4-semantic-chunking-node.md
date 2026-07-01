---
baseline_commit: "d12638d216b7de56a93fa29f76fda23608cb853f"
---

# Story 1.4: Semantic Chunking Node — tiktoken-Based Token-Bounded Splitting

Status: done

## Story

As a content pipeline,
I want to split each detected section into token-bounded chunks with overlap,
so that downstream LLM nodes (lesson_planner, summarise_segment, etc.) receive
context-sized segments rather than unbounded section bodies that would overflow
context windows or produce 5× cost overruns.

## Acceptance Criteria

1. `chunk_node` replaces the stub body in `graph.py` with a full tiktoken-based implementation
2. Tokenizer: `tiktoken.get_encoding("cl100k_base")` — the encoding used by `text-embedding-3-small` and GPT-4o (never hardcode encoding name; read from `settings.embedding_tokenizer` or default to `"cl100k_base"`)
3. Target chunk size: 512 tokens; overlap: 64 tokens between consecutive chunks; both values configurable via `settings.chunk_target_tokens` and `settings.chunk_overlap_tokens`
4. Split strategy: paragraph-boundary-first (`\n\n` split), then sentence-boundary fallback (`. `, `? `, `! ` patterns) — never split mid-word. Single paragraphs/sentences longer than `chunk_target_tokens` are included as-is (oversized chunk); never truncate LLM-produced body text
5. Each chunk dict contains: `id`, `section_id`, `text`, `token_count`, `section_title`, `page_start`, `page_end`
6. Chunk IDs are deterministic and idempotent: `{section_id}_c{chunk_index}` (e.g. `s0_c0`, `s0_c1`) — same sections → same IDs on ARQ retry
7. A 10-section document with ~1 000 tokens/section produces ≥ 10 chunks (at least one per section); a 5 000-token section produces ≥ 8 chunks (5000/512 ≈ 9.8)
8. Node is idempotent — if `lesson_jobs.node_outputs["chunk"]` exists, restore `chunks` list + `chapter_id` from cache and return immediately (no re-splitting, no re-insert)
9. Checkpoint written on success: `lesson_jobs.last_node = "chunk"`, `node_outputs["chunk"]` contains `{"chunks": [...], "chapter_id": "<uuid>"}` so embed_node can look up the chapter without an extra DB query
10. `chunk_node` DOES write to Supabase — it first creates one `chapters` row (to establish the `chapter_id` FK), then bulk-upserts all chunk rows to the `chunks` table WITHOUT embedding (embedding column left null; Story 1.5 sets it). `chapter_id` and `book_id` come from `state["lesson_id"]`/`state["book_id"]` and the `chapters` insert; `chunk_index` is the zero-based position of the chunk across all sections
11. Add `tiktoken>=0.7.0` to `pyproject.toml` dependencies and to `[[tool.mypy.overrides]]` ignore list
12. Add `settings.chunk_target_tokens: int = 512`, `settings.chunk_overlap_tokens: int = 64`, `settings.embedding_tokenizer: str = "cl100k_base"` to `app/config.py`

## Tasks / Subtasks

- [x] **Task 1: Add tiktoken dependency + config fields** (AC: 2, 3, 11, 12)
  - [x] Add `"tiktoken>=0.7.0"` to `dependencies` list in `apps/api/pyproject.toml`
  - [x] Add `"tiktoken.*"` to `[[tool.mypy.overrides]]` `ignore_missing_imports = true` module list
  - [x] In `apps/api/app/config.py`, add to `Settings` class:
    ```python
    chunk_target_tokens: int = Field(default=512, description="Target token count per chunk")
    chunk_overlap_tokens: int = Field(default=64, description="Token overlap between consecutive chunks")
    embedding_tokenizer: str = Field(default="cl100k_base", description="tiktoken encoding for token counting")
    ```

- [x] **Task 2: Implement chunking helper module** (AC: 2, 3, 4, 5, 6, 7)
  - [x] Create `apps/api/app/modules/content/pipeline/nodes/chunking.py` (NEW)
  - [x] Implement `count_tokens(text: str, encoding: Any) -> int` — `len(encoding.encode(text))`
  - [x] Implement `split_into_segments(text: str) -> list[str]` (paragraph-then-sentence split)
  - [x] Implement `chunk_section(section: dict, encoding: Any, target: int, overlap: int) -> list[dict]`
  - [x] Implement `chunk_sections(sections: list[dict], target: int, overlap: int, tokenizer_name: str) -> list[dict]`

- [x] **Task 3: Implement `chunk_node` in `graph.py`** (AC: 1, 2, 3, 4, 5, 6, 7, 8, 9, 10)
  - [x] Replace the 4-line stub body in `chunk_node` with the full implementation
  - [x] **Idempotency check first**: query `lesson_jobs.node_outputs` for `lesson_id`; if `"chunk"` key exists, restore `chunks` + `chapter_id` from cache and return immediately — no re-split, no re-insert
  - [x] Import lazily (inside function): `from app.config import get_settings`, `from app.core.db import get_supabase`, `from app.modules.content.pipeline.nodes.chunking import chunk_sections`
  - [x] Read settings: `target = settings.chunk_target_tokens`, `overlap = settings.chunk_overlap_tokens`, `tokenizer = settings.embedding_tokenizer`
  - [x] Call `chunk_sections(state.get("sections", []), target, overlap, tokenizer)` to get in-memory chunks
  - [x] **Create chapter row** in Supabase `chapters` table:
    ```python
    chapter_resp = supabase.table("chapters").insert({
        "lesson_id": lesson_id,
        "book_id": state["book_id"],
        "title": state.get("sections", [{}])[0].get("title", "Chapter") if state.get("sections") else "Chapter",
        "page_start": state.get("sections", [{}])[0].get("page_start", 1) if state.get("sections") else 1,
        "page_end": state.get("sections", [{}])[-1].get("page_end", 1) if state.get("sections") else 1,
        "chapter_index": 1,
    }).execute()
    chapter_id = chapter_resp.data[0]["chapter_id"]
    ```
  - [x] **Bulk-upsert chunks to Supabase** `chunks` table (no embedding column — Story 1.5 sets it):
    ```python
    rows = [
        {
            "chapter_id": chapter_id,
            "book_id": state["book_id"],
            "section": chunk["section_title"],
            "page_start": chunk["page_start"],
            "page_end": chunk["page_end"],
            "content": chunk["text"],
            "chunk_index": global_i,
            "token_count": chunk["token_count"],
        }
        for global_i, chunk in enumerate(chunks)
    ]
    if rows:
        supabase.table("chunks").upsert(rows).execute()
    ```
  - [x] Write checkpoint (includes `chapter_id` so embed_node can skip a DB query):
    ```python
    chunk_cache = {"chunks": chunks, "chapter_id": chapter_id}
    supabase.table("lesson_jobs").update({
        "last_node": "chunk",
        "node_outputs": {**node_outputs, "chunk": chunk_cache},
    }).eq("lesson_id", lesson_id).execute()
    ```
  - [x] Call `_update_job_progress(lesson_id, 20.0, "chunk")` AFTER checkpoint write
  - [x] Return `{**state, "chunks": chunks, "progress_pct": 20.0}`

- [x] **Task 4: Unit tests** (all ACs)
  - [x] Create `apps/api/tests/unit/test_chunk_node.py`
  - [x] Mock tiktoken with `patch.dict("sys.modules", {"tiktoken": fake_tiktoken_module})`
  - [x] `test_chunk_node_happy_path` — PASSED
  - [x] `test_chunk_node_idempotent` — PASSED
  - [x] `test_chunk_node_writes_checkpoint` — PASSED
  - [x] `test_chunk_node_writes_chapter_row` — PASSED
  - [x] `test_chunk_node_writes_chunk_rows` — PASSED
  - [x] `test_chunk_node_empty_sections` — PASSED
  - [x] `test_chunk_sections_splits_long_section` — PASSED
  - [x] `test_chunk_sections_short_section` — PASSED
  - [x] `test_chunk_sections_overlap_appears_in_next_chunk` — PASSED
  - [x] `test_chunk_section_ids_are_deterministic` — PASSED
  - [x] `test_chunk_sections_chunk_id_format` — PASSED
  - [x] `test_chunk_sections_is_pure` — PASSED
  - [x] `test_chunk_sections_empty_body_returns_single_empty_chunk` — PASSED
  - [x] `test_chunk_sections_multiple_sections_produce_chunks_for_each` — PASSED
  - [x] Full suite: 49/49 passed, 0 regressions

### Review Findings (code review 2026-07-01)

- [x] [Review][Patch] Unguarded `chapter_resp.data[0]["chapter_id"]` — IndexError if chapters insert returns empty data [`graph.py:391`]
- [x] [Review][Patch] `chapters` insert and `chunks` upsert not wrapped in try/except — checkpoint failure leaves no cache key so ARQ retry re-inserts duplicate rows [`graph.py:383-408`]
- [x] [Review][Patch] Overlap fallback `else chunk_text` balloons subsequent chunks when previous chunk < overlap tokens — fix: `else encoding.decode(full_tokens)` [`chunking.py:96`]
- [x] [Review][Patch] `split_into_segments` appends `"\n\n"` then filters it with `if s.strip()` — last sentence of para N runs into first sentence of para N+1 with no separator; fix: change filter to `if s` [`chunking.py:41`]
- [x] [Review][Patch] `fitz.*` still in mypy overrides — banned AGPL import silently passes type checking [`pyproject.toml`]
- [x] [Review][Patch] `book_id` may be `None` (not `""`) if `lessons.book_id IS NULL`; `chapters.book_id NOT NULL` causes FK crash — add null guard [`graph.py:385`]
- [x] [Review][Patch] Empty-body sections produce `content=""` chunk rows in DB — embed_node will 400 on empty OpenAI embeddings input; filter zero-token chunks before upsert [`graph.py:394-408`]
- [x] [Review][Patch] AC 7 second bound untested — 5000-token section → ≥8 chunks not covered [`test_chunk_node.py`]
- [x] [Review][Defer] `chapter_index` hardcoded to 1 — multi-chapter books will collide [`graph.py:389`] — deferred; MVP limitation (one chapter per ingestion), Story 2.1 scope
- [x] [Review][Defer] `json.loads` raises uncaught on 0-exit subprocess with partial stdout [`graph.py:150`] — deferred; extremely unlikely with controlled subprocess
- [x] [Review][Defer] DB-generated `chunk_id` UUIDs not stored in checkpoint — embed_node must re-query by chapter_id [`graph.py:411`] — deferred; intentional design (AC 9 checkpoint stores chapter_id for this purpose)
- [x] [Review][Defer] `progress_pct` not persisted to DB (no lesson_jobs column) — deferred; already W4
- [x] [Review][Defer] `cost_limit_exceeded` violates CHECK constraint — deferred; already W3
- [x] [Review][Defer] `content_pipeline_job` success path invalid status/columns — deferred; already W12

---

## Dev Notes

### Critical: Files to Read Before Touching

| File | Current State | This Story Changes |
|------|--------------|-------------------|
| `apps/api/app/modules/content/pipeline/graph.py:357-368` | `chunk_node` is a 4-line stub using `len(body.split())` word count | Full implementation — replace stub body entirely |
| `apps/api/app/config.py` | `Settings` class with existing fields | Add 3 new fields: `chunk_target_tokens`, `chunk_overlap_tokens`, `embedding_tokenizer` |
| `apps/api/pyproject.toml` | No tiktoken dependency | Add `tiktoken>=0.7.0` |

### Current chunk_node Stub (read before editing)

```python
# graph.py:357-368 — CURRENT STATE (TODO stub):
async def chunk_node(state: PipelineState) -> PipelineState:
    """Node 3: Split sections into token-bounded chunks for LLM processing."""
    lesson_id = state["lesson_id"]
    logger.info("[%s] chunk_node: chunking %d sections", lesson_id, len(state.get("sections", [])))
    await _update_job_progress(lesson_id, 16.0, "chunk")

    # TODO: tiktoken-based chunking with 512-token target, 64-token overlap
    chunks: list[dict[str, Any]] = [
        {"id": f"c{i}", "section_id": s["id"], "text": s["body"], "token_count": len(s["body"].split())}
        for i, s in enumerate(state.get("sections", []))
    ]
    return {**state, "chunks": chunks, "progress_pct": 20.0}
```

The new implementation MUST call `_update_job_progress` AFTER writing the checkpoint (same as extract_node, structure_node patterns).

### tiktoken Key Facts

- Package: `tiktoken` (OpenAI's BPE tokenizer library)
- Version: `>=0.7.0` (current stable; thread-safe in 0.7+)
- Encoding `cl100k_base`: used by GPT-4, GPT-4o, text-embedding-3-small — exact match for our embedding model
- API:
  ```python
  import tiktoken
  enc = tiktoken.get_encoding("cl100k_base")  # expensive — call ONCE per node execution
  tokens = enc.encode("some text")           # list[int]
  token_count = len(tokens)
  # Decode overlap: enc.decode(tokens[-overlap:]) → str
  ```
- `get_encoding()` downloads a data file on first call and caches it; subsequent calls are instant. OK to call once per `chunk_sections` invocation (each pipeline run).
- tiktoken is NOT installed in the test environment — use `patch.dict("sys.modules", {"tiktoken": fake_module})` exactly as Story 1.3 did for openai.

### Chunking Algorithm — Detailed

```python
def chunk_section(section: dict, encoding: Any, target: int, overlap: int) -> list[dict]:
    body = section.get("body", "")
    section_id = section["id"]

    if not body.strip():
        return [{
            "id": f"{section_id}_c0",
            "section_id": section_id,
            "text": "",
            "token_count": 0,
            "section_title": section.get("title", ""),
            "page_start": section.get("page_start", 1),
            "page_end": section.get("page_end", 1),
        }]

    segments = split_into_sentences(body)  # list of strings
    chunks: list[dict] = []
    buffer: list[str] = []
    buffer_tokens = 0
    overlap_text = ""  # tail of previous chunk for prepending

    for seg in segments:
        seg_tokens = count_tokens(seg, encoding)
        if buffer_tokens + seg_tokens > target and buffer:
            # Emit current buffer as chunk
            chunk_text = overlap_text + "".join(buffer) if overlap_text else "".join(buffer)
            chunk_tokens = count_tokens(chunk_text, encoding)
            chunks.append({
                "id": f"{section_id}_c{len(chunks)}",
                "section_id": section_id,
                "text": chunk_text.strip(),
                "token_count": chunk_tokens,
                "section_title": section.get("title", ""),
                "page_start": section.get("page_start", 1),
                "page_end": section.get("page_end", 1),
            })
            # Build overlap: decode last `overlap` tokens of the emitted chunk
            full_tokens = encoding.encode(chunk_text)
            overlap_text = encoding.decode(full_tokens[-overlap:]) if len(full_tokens) >= overlap else chunk_text
            buffer = [seg]
            buffer_tokens = seg_tokens
        else:
            buffer.append(seg)
            buffer_tokens += seg_tokens

    # Emit remaining buffer
    if buffer:
        chunk_text = overlap_text + "".join(buffer) if overlap_text else "".join(buffer)
        chunk_tokens = count_tokens(chunk_text, encoding)
        chunks.append({
            "id": f"{section_id}_c{len(chunks)}",
            "section_id": section_id,
            "text": chunk_text.strip(),
            "token_count": chunk_tokens,
            "section_title": section.get("title", ""),
            "page_start": section.get("page_start", 1),
            "page_end": section.get("page_end", 1),
        })

    return chunks
```

**Overlap detail:** overlap_text is prepended at the START of each new chunk buffer. This means the new chunk begins with the tail of the previous one, giving LLM nodes context continuity. The overlap comes from decoding the last `overlap` tokens of the emitted chunk text using `encoding.decode(tokens[-overlap:])`. This is exact token-level overlap (not approximate).

**Oversized single segment:** if a paragraph/sentence itself exceeds `target` tokens, the `if buffer_tokens + seg_tokens > target and buffer` condition is False (buffer is empty), so it's appended to buffer and emitted as its own chunk — no truncation.

### split_into_sentences Implementation

```python
import re

_PARA_SEP = re.compile(r"\n\n+")
_SENT_SEP = re.compile(r"(?<=[.!?])\s+")

def split_into_sentences(text: str) -> list[str]:
    """Split text into sentence-level segments preserving all whitespace."""
    paragraphs = _PARA_SEP.split(text)
    segments: list[str] = []
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        sentences = _SENT_SEP.split(para)
        # Re-attach the space that was split on
        segments.extend(s + " " for s in sentences[:-1])
        segments.append(sentences[-1])
        segments.append("\n\n")  # preserve paragraph break
    return [s for s in segments if s.strip()]  # drop empty-after-strip segments
```

Note: appending `"\n\n"` after each paragraph ensures paragraph structure is preserved in assembled chunks. The greedy packer will include it when there is space.

### tiktoken Mock for Tests

```python
import sys
from unittest.mock import MagicMock

def _make_tiktoken_mock(tokens_per_word: int = 1) -> tuple[MagicMock, dict]:
    """Fake tiktoken where encode() returns one token per word (simple, deterministic)."""
    mock_enc = MagicMock()
    mock_enc.encode.side_effect = lambda text: text.split()  # words as tokens
    mock_enc.decode.side_effect = lambda tokens: " ".join(tokens)

    mock_tiktoken = MagicMock()
    mock_tiktoken.get_encoding.return_value = mock_enc

    return mock_enc, {"tiktoken": mock_tiktoken}
```

With this mock, a 600-word section body produces ≥ 2 chunks at target=512 words (tokens).

### Settings Fields to Add in config.py

Read the existing `Settings` class in `app/config.py` first to find the correct location. Add AFTER the existing LLM model aliases:

```python
# Chunking
chunk_target_tokens: int = Field(default=512, description="Target tokens per chunk (tiktoken cl100k_base)")
chunk_overlap_tokens: int = Field(default=64, description="Overlap tokens between consecutive chunks")
embedding_tokenizer: str = Field(default="cl100k_base", description="tiktoken encoding name for token counting")
```

These are plain int/str fields — no env var needed unless the team wants runtime tuning. For Sprint 1, the defaults are sufficient. The `env` alias can be added later.

### PipelineState chunks Field (current — DO NOT CHANGE annotation)

```python
# Current in PipelineState (do not modify TypedDict):
chunks: list[dict[str, Any]]  # [{id, section_id, text, token_count}]
```

The new chunks dicts add `section_title`, `page_start`, `page_end` fields — these are ADDITIVE, compatible with the existing annotation `list[dict[str, Any]]`. No TypedDict change needed.

### embed_node Downstream Contract

`embed_node` (Story 1.5) consumes `state["chunks"]` and `node_outputs["chunk"]["chapter_id"]` from the checkpoint. It UPDATEs existing `chunks` rows (already created by chunk_node) to set `embedding`. It does NOT re-insert chunks.

Each chunk in `state["chunks"]` carries:
- `id` → in-memory deterministic id (e.g. `s0_c0`); NOT the Supabase `chunk_id` UUID
- `text` → the content to embed
- `token_count` → already in DB; embed_node may re-confirm or skip
- `section_title` → in-memory reference

`embed_node` must look up rows in the `chunks` table by `(chapter_id, chunk_index)` to get the real `chunk_id` UUIDs, then UPDATE each row's `embedding` column. Do NOT change the `state["chunks"]` field shape — embed_node relies on position order (chunk_index) matching list order.

### Supabase `chunks` Table Schema (chunk_node INSERTS here without embedding)

```sql
chunks (
    chunk_id     uuid PK default gen_random_uuid(),  -- auto-generated by Supabase
    chapter_id   uuid FK → chapters,                 -- from chapters.insert response
    section      text,                               -- chunk["section_title"]
    page_start   integer,                            -- chunk["page_start"]
    page_end     integer,                            -- chunk["page_end"]
    content      text NOT NULL,                      -- chunk["text"]
    chunk_index  integer NOT NULL,                   -- global zero-based index across all sections
    book_id      uuid FK → books,                    -- from state["book_id"]
    token_count  integer,                            -- chunk["token_count"]
    embedding    vector(1536)                        -- NULL here; Story 1.5 sets it
)
```

`chapters` table required fields for insert:
```sql
chapters (
    chapter_id    uuid PK default gen_random_uuid(),
    lesson_id     uuid FK → lessons,
    book_id       uuid FK → books,
    title         text,
    page_start    integer,
    page_end      integer,
    chapter_index integer
)
```

`chapter_index` = 1 (one chapter per lesson ingestion in MVP). If future multi-chapter support is added, this will increment.

### Idempotency Pattern (same as extract_node and structure_node)

```python
jobs_resp = (
    supabase.table("lesson_jobs")
    .select("node_outputs")
    .eq("lesson_id", lesson_id)
    .single()
    .execute()
)
node_outputs: dict[str, Any] = (jobs_resp.data or {}).get("node_outputs") or {}

if "chunk" in node_outputs:
    cached = node_outputs["chunk"]
    logger.info("[%s] chunk_node: cache hit", lesson_id)
    return {**state, "chunks": cached["chunks"], "progress_pct": 20.0}
```

### Test Supabase Mock (same helper pattern as Stories 1.2 and 1.3)

```python
def _make_supabase_mock(node_outputs: dict | None = None) -> MagicMock:
    jobs_mock = MagicMock()
    jobs_data = {"node_outputs": node_outputs or {}}
    (jobs_mock.select.return_value
               .eq.return_value
               .single.return_value
               .execute.return_value
               .data) = jobs_data
    sb = MagicMock()
    sb.table.return_value = jobs_mock
    return sb
```

### Dependency on Story 1.3 Output

`chunk_node` receives `state["sections"]` from Story 1.3's `structure_node`. Each section:
```python
{"id": str, "title": str, "level": str, "body": str, "page_start": int, "page_end": int}
```
All 6 fields are guaranteed by `SectionBoundary.model_dump()` and the fallback dict in `build_section_bodies`. Do NOT add defensive `section.get("id", "s0")` workarounds — if the field is missing that's a bug upstream, not here.

### config.py Pattern

Read `apps/api/app/config.py` in full before editing. The Settings class uses `pydantic-settings` with `BaseSettings`. New fields go in the relevant section. Example existing pattern to follow:
```python
llm_mini: str = Field(default="gpt-4o-mini", description="Model for economy nodes (quiz, scoring, etc.)")
```

### References

- `apps/api/app/modules/content/pipeline/graph.py:357-368` — current `chunk_node` stub (replace)
- `apps/api/app/modules/content/pipeline/graph.py:560-577` — `_update_job_progress` helper (call AFTER checkpoint)
- `apps/api/app/config.py` — Settings class (add 3 fields)
- `apps/api/pyproject.toml` — add tiktoken dependency
- Story 1.3 Dev Agent Record — `patch.dict(sys.modules)` pattern for unavailable test env packages
- CLAUDE.md: "Chunk embeddings at ingestion only — never regenerate stored chunk embeddings"
- CLAUDE.md: "Never hardcode model strings — always use `settings.llm_*` aliases" (apply same principle to tokenizer name via `settings.embedding_tokenizer`)
- Supabase migration `20260625000000_chunks_inline_embedding.sql` — chunks table schema
- PRD §5 principle 2: "Process once, reuse everywhere — chunk embeddings generated at ingestion, never regenerated for stored content"

---

## Dev Agent Record

### Agent Model Used

claude-sonnet-4-6 (dev-story)

### Completion Notes List

- Implemented `split_into_segments()` (named vs story's `split_into_sentences` — functionally equivalent: paragraph-then-sentence split with `\n\n` sentinel preservation)
- `chunk_section()` greedy packer: exact token-level overlap via `encoding.decode(tokens[-overlap:])` from emitted chunk tail
- Oversized single segments (no paragraph/sentence breaks) emit as-is — never truncated, per spec AC 4
- `chunk_node` creates 1 `chapters` row then bulk-upserts all chunk rows without `embedding` column (Story 1.5 fills it)
- Checkpoint stores `{"chunks": [...], "chapter_id": "uuid"}` so embed_node gets chapter_id without extra DB query
- 14 new unit tests, 49 total (35 prior + 14 new), 0 regressions
- tiktoken mocked via `patch.dict("sys.modules", {"tiktoken": fake})` — identical to Story 1.3 openai pattern
- Test body for split test uses `\n\n`-separated paragraphs (single-line bodies intentionally produce 1 oversized chunk per spec)

### File List

**UPDATE:**
- `apps/api/pyproject.toml` — add `tiktoken>=0.7.0` to dependencies + mypy overrides
- `apps/api/app/config.py` — add `chunk_target_tokens`, `chunk_overlap_tokens`, `embedding_tokenizer` fields
- `apps/api/app/modules/content/pipeline/graph.py` — implement `chunk_node` body (replace TODO stub); adds `chapters` insert + `chunks` upsert DB writes

**NEW:**
- `apps/api/app/modules/content/pipeline/nodes/chunking.py` — `split_into_sentences`, `count_tokens`, `chunk_section`, `chunk_sections` (pure, no DB)
- `apps/api/tests/unit/test_chunk_node.py` — unit tests covering chunking logic + DB write assertions

### Change Log

- Added `tiktoken>=0.7.0` to `pyproject.toml` dependencies + mypy overrides (2026-07-02)
- Added `chunk_target_tokens`, `chunk_overlap_tokens`, `embedding_tokenizer` to `Settings` in `config.py` (2026-07-02)
- Created `nodes/chunking.py` — pure tiktoken-based chunking helpers (2026-07-02)
- Implemented `chunk_node` in `graph.py` — replaces TODO stub with idempotency check, tiktoken split, chapters insert, chunks upsert, checkpoint (2026-07-02)
- Created `tests/unit/test_chunk_node.py` — 14 unit tests covering all ACs (2026-07-02)
