"""Export the assessment module OpenAPI spec to a JSON file.

Builds a minimal FastAPI app from just the assessment router so no env vars,
Redis, or DB are required. Safe to run in CI and locally without infrastructure.

Usage (from apps/api/):
    python scripts/export_openapi.py
    python scripts/export_openapi.py --out ../../docs/openapi-assessment.json
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

# Make the app package importable when run directly from apps/api/
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from fastapi import FastAPI  # noqa: E402

from app.modules.assessment.router import router as assessment_router  # noqa: E402


def build_spec_app() -> FastAPI:
    """Return a minimal FastAPI app containing only the assessment router.

    Prefix must match the assessment router's mount point in apps/api/app/main.py.
    Never change without syncing both files.
    """
    mini = FastAPI(
        title="HIE Assessment API",
        description=(
            "Assessment endpoints for TransformED — "
            "quiz submission, teach-back evaluation, session reports, "
            "Learner DNA, and onboarding diagnostic."
        ),
        version="0.1.0",
    )
    mini.include_router(assessment_router, prefix="/api/assessment")
    return mini


def _check_cwd() -> None:
    """Abort early if not running from apps/api/.

    The default --out path is relative to CWD. Running from the wrong directory
    silently writes the spec somewhere wrong. We detect this by checking that the
    expected 'app/' sub-package directory exists in CWD.
    """
    expected = pathlib.Path.cwd() / "app" / "main.py"
    if not expected.is_file():
        print("ERROR: Run this script from the apps/api/ directory.")  # noqa: T201
        print(f"  Current directory : {pathlib.Path.cwd()}")  # noqa: T201
        print(f"  Expected to find  : {expected}")  # noqa: T201
        print()  # noqa: T201
        print("  cd apps/api && python scripts/export_openapi.py")  # noqa: T201
        sys.exit(1)


def main() -> None:
    _check_cwd()

    parser = argparse.ArgumentParser(description="Dump the assessment OpenAPI spec to a JSON file.")
    parser.add_argument(
        "--out",
        default="../../docs/openapi-assessment.json",
        help=(
            "Output path (relative to CWD or absolute). "
            "Default resolves to docs/openapi-assessment.json at project root "
            "when called from apps/api/."
        ),
    )
    args = parser.parse_args()

    spec = build_spec_app().openapi()

    out_path = pathlib.Path(args.out)
    if not out_path.is_absolute():
        out_path = pathlib.Path.cwd() / out_path
    out_path = out_path.resolve()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(spec, indent=2, ensure_ascii=False), encoding="utf-8")

    assessment_paths = [p for p in spec.get("paths", {}) if "/assessment/" in p]
    schemas = spec.get("components", {}).get("schemas", {})
    http_verbs = {"get", "post", "put", "patch", "delete", "head", "options", "trace"}

    print(f"DONE: Spec written to {out_path}")  # noqa: T201
    print(f"  Total paths  : {len(spec.get('paths', {}))}")  # noqa: T201
    print(f"  Assessment   : {len(assessment_paths)} endpoints")  # noqa: T201
    print(f"  Schemas      : {', '.join(sorted(schemas.keys()))}")  # noqa: T201
    print()  # noqa: T201
    print("Assessment endpoints:")  # noqa: T201
    for path in sorted(assessment_paths):
        # Filter path-item keys to HTTP verbs only (OpenAPI path items may also
        # contain 'summary', 'description', 'parameters', 'servers', etc.)
        methods = ", ".join(k.upper() for k in spec["paths"][path].keys() if k in http_verbs)
        print(f"  [{methods}] {path}")  # noqa: T201


if __name__ == "__main__":
    main()
