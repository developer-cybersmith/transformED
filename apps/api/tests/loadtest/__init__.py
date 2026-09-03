"""Story 5-1 load-testing harness (50-concurrent).

HTTP-only harness that drives real load against a running API process
(`LOADTEST_BASE_URL`, default `http://localhost:8000`) for both the book-upload
phase (Phase A, `phase_a_upload.py`) and the lesson-generation phase (Phase B).

Deliberately kept inside `apps/api/tests/` (not a top-level `scripts/` script)
so it can import shared fixtures/config the same way the rest of the test
suite does, per the story's Task 1 scaffolding note. It is NOT a pytest suite
-- none of these modules are named `test_*.py` and pytest does not collect
them; they are invoked directly (e.g. `python -m tests.loadtest.runner`) once
a human explicitly kicks off the real, cost-incurring run.
"""

from __future__ import annotations
