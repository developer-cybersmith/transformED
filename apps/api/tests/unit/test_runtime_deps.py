"""
AC-8 (Story 2-0) — runtime-dependency contract test.

tests/conftest.py stubs sys.modules['openai'] session-wide (autouse), which
means an entirely missing runtime dependency can pass the whole unit suite
and only explode in production (the 2026-07-08 E2E outage class). This test
imports the real provider modules in a SUBPROCESS — no conftest, no stubs —
proving the actual openai / langfuse / tiktoken imports resolve in the
runtime image.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_API_DIR = Path(__file__).resolve().parents[2]  # apps/api


def test_provider_modules_import_without_stubs() -> None:
    code = (
        "import app.providers.llm.openai, "
        "app.providers.embeddings.openai, "
        "app.modules.content.pipeline.graph"
    )
    env = {**os.environ, "PYTHONPATH": str(_API_DIR)}
    result = subprocess.run(  # noqa: S603 — fixed argv, our own interpreter
        [sys.executable, "-c", code],
        cwd=_API_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, (
        "real (unstubbed) runtime imports failed — a dependency the pipeline "
        f"needs at runtime is missing or broken:\n{result.stderr}"
    )
