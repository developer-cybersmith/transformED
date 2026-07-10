"""
AC-8 (Story 2-0) — runtime-dependency contract test.

tests/conftest.py stubs sys.modules['openai'] session-wide (autouse), which
means an entirely missing runtime dependency can pass the whole unit suite
and only explode in production (the 2026-07-08 E2E outage class). This test
imports the real provider modules in a SUBPROCESS — no conftest, no stubs —
proving the actual openai / langfuse / tiktoken imports resolve in the
runtime image.

Provider modules are enumerated DYNAMICALLY (every .py under app/providers/
except __init__.py) so a newly added provider is covered the moment the file
lands — no manual list to forget to update.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_API_DIR = Path(__file__).resolve().parents[2]  # apps/api
_PROVIDERS_DIR = _API_DIR / "app" / "providers"


def _provider_modules() -> list[str]:
    """Every provider module path, e.g. 'app.providers.llm.openai'."""
    modules = []
    for py_file in sorted(_PROVIDERS_DIR.rglob("*.py")):
        if py_file.name == "__init__.py":
            continue
        rel = py_file.relative_to(_API_DIR).with_suffix("")
        modules.append(".".join(rel.parts))
    return modules


def test_provider_modules_import_without_stubs() -> None:
    modules = _provider_modules()
    assert modules, f"no provider modules found under {_PROVIDERS_DIR}"

    targets = [*modules, "app.modules.content.pipeline.graph"]
    code = "import " + ", ".join(targets)
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
        f"needs at runtime is missing or broken.\nModules: {targets}\n"
        f"{result.stderr}"
    )
