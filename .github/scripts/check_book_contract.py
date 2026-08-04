#!/usr/bin/env python3
"""Diff the frozen book-scale contract against the live FastAPI OpenAPI schema.

Story W0, AC7. `apps/web` builds its MSW fixtures from
``docs/contracts/book-api.v1.json``. That makes the frontend suite honest about
what it *believes*, but nothing in it can notice when the backend moves: rename
``chapter_count`` in FastAPI and both suites stay green while the product dies.
This script is the only thing that compares the two.

Usage::

    python .github/scripts/check_book_contract.py <contract.json> <openapi.json>

Exit code 0 only when every contract endpoint and every contract schema was
found AND matched. It prints three machine-readable counters that ``ci.yml``
re-checks:

    CONTRACT_ENDPOINTS_CHECKED=<n>
    CONTRACT_SCHEMAS_CHECKED=<n>
    CONTRACT_COMPARISONS=<n>

The counters are not decoration. D51 (see the ``Migration tests`` step in
ci.yml) was a guard whose regex only ever matched an all-skipped run, so a
partial skip passed green for weeks. A comparison script that finishes without
having compared anything is the same failure in a new subsystem, so the count is
emitted and asserted rather than assumed.
"""

from __future__ import annotations

import json
import sys

# Keys inside a contract schema block that document it rather than naming a
# response field. Kept in sync with apps/web/src/test/contract.ts.
NON_FIELD_KEYS = {"$comment", "added_in"}

# Which component schema each endpoint's SUCCESS response must resolve to, and
# whether it is returned as a list. This is the linkage the field-by-field
# comparison below cannot see: a path can exist, and a schema can match, while
# the path returns an entirely different schema.
RESPONSE_SHAPE: dict[str, tuple[str, str, bool]] = {
    "GET /books": ("get", "BookResponse", True),
    "GET /books/{book_id}": ("get", "BookResponse", False),
    "GET /books/{book_id}/chapters": ("get", "ChapterResponse", True),
    "POST /books/{book_id}/chapters/{chapter_id}/lessons": (
        "post",
        "LessonGenerationResponse",
        False,
    ),
}

SUCCESS_CODES = ("200", "201", "202")


def component(spec: dict, name: str) -> dict | None:
    """Look a component schema up, tolerating FastAPI's -Input/-Output suffixes."""
    schemas = spec.get("components", {}).get("schemas", {})
    for candidate in (name, f"{name}-Output", f"{name}-Input"):
        if candidate in schemas:
            return schemas[candidate]
    return None


def ref_name(node: dict) -> str | None:
    """Resolve the component name a response schema node points at."""
    if "$ref" in node:
        return node["$ref"].rsplit("/", 1)[-1]
    if node.get("type") == "array" and isinstance(node.get("items"), dict):
        return ref_name(node["items"])
    # FastAPI emits `anyOf` for `X | None`.
    for key in ("anyOf", "oneOf", "allOf"):
        for sub in node.get(key, []):
            if isinstance(sub, dict):
                resolved = ref_name(sub)
                if resolved:
                    return resolved
    return None


def is_array_response(node: dict) -> bool:
    return node.get("type") == "array"


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(f"usage: {argv[0]} <contract.json> <openapi.json>", file=sys.stderr)
        return 2

    with open(argv[1], encoding="utf-8") as fh:
        contract = json.load(fh)
    with open(argv[2], encoding="utf-8") as fh:
        spec = json.load(fh)

    base = contract["base"]  # "/api/content"
    paths = spec.get("paths", {})
    errors: list[str] = []
    comparisons = 0
    endpoints_checked = 0
    schemas_checked = 0

    contract_endpoints = contract.get("endpoints", {})
    if not contract_endpoints:
        print("::error::the contract declares no endpoints — nothing to compare")
        return 1
    contract_schemas = contract.get("schemas", {})
    if not contract_schemas:
        print("::error::the contract declares no schemas — nothing to compare")
        return 1

    # ── Endpoints ────────────────────────────────────────────────────────────
    for key in contract_endpoints:
        method_word, _, rel_path = key.partition(" ")
        full_path = f"{base}{rel_path}"
        method = method_word.lower()

        comparisons += 1
        item = paths.get(full_path)
        if item is None:
            errors.append(
                f"contract endpoint {key!r} -> {full_path!r} is ABSENT from the live schema"
            )
            endpoints_checked += 1
            continue
        if method not in item:
            errors.append(
                f"contract endpoint {key!r}: the live schema serves {full_path!r} "
                f"but not via {method.upper()} (has: {sorted(k for k in item if k != 'parameters')})"
            )
            endpoints_checked += 1
            continue

        expected = RESPONSE_SHAPE.get(key)
        if expected is None:
            errors.append(
                f"contract endpoint {key!r} has no entry in RESPONSE_SHAPE. A new endpoint was "
                f"added to the contract without teaching this check what it returns — that is a "
                f"silent hole, not a pass."
            )
            endpoints_checked += 1
            continue

        _, expected_schema, expected_is_array = expected
        operation = item[method]
        node = None
        for code in SUCCESS_CODES:
            content = operation.get("responses", {}).get(code, {}).get("content", {})
            if "application/json" in content:
                node = content["application/json"].get("schema", {})
                break

        comparisons += 1
        if node is None:
            errors.append(
                f"{method.upper()} {full_path}: no JSON success response "
                f"({'/'.join(SUCCESS_CODES)}) in the live schema"
            )
        else:
            live_schema = ref_name(node)
            live_is_array = is_array_response(node)
            if live_schema != expected_schema:
                errors.append(
                    f"{method.upper()} {full_path}: contract says it returns {expected_schema}, "
                    f"live schema returns {live_schema}"
                )
            if live_is_array != expected_is_array:
                errors.append(
                    f"{method.upper()} {full_path}: contract says "
                    f"{'a list' if expected_is_array else 'a single object'}, live schema says "
                    f"{'a list' if live_is_array else 'a single object'}"
                )

        endpoints_checked += 1

    # ── Schemas, field by field ──────────────────────────────────────────────
    for name, block in contract_schemas.items():
        schemas_checked += 1
        comparisons += 1
        expected_fields = {k for k in block if k not in NON_FIELD_KEYS}
        live = component(spec, name)
        if live is None:
            errors.append(
                f"schema {name!r} is declared in the contract but has no component in the "
                f"live schema"
            )
            continue
        live_fields = set(live.get("properties", {}))

        missing = sorted(expected_fields - live_fields)
        added = sorted(live_fields - expected_fields)
        if missing:
            errors.append(
                f"schema {name}: field(s) {missing} are in the FROZEN contract but GONE from "
                f"the live schema. GET shapes are additive-only — a field may be added, never "
                f"removed or renamed."
            )
        if added:
            errors.append(
                f"schema {name}: field(s) {added} exist in the live schema but are undocumented "
                f"in the frozen contract. Additive changes are allowed, but they must be written "
                f"down before apps/web can rely on them."
            )

    print(f"CONTRACT_ENDPOINTS_CHECKED={endpoints_checked}")
    print(f"CONTRACT_SCHEMAS_CHECKED={schemas_checked}")
    print(f"CONTRACT_COMPARISONS={comparisons}")

    if endpoints_checked != len(contract_endpoints):
        print(
            f"::error::only {endpoints_checked} of {len(contract_endpoints)} contract endpoints "
            f"were checked — a partial run is a failed run (D51)"
        )
        return 1
    if schemas_checked != len(contract_schemas):
        print(
            f"::error::only {schemas_checked} of {len(contract_schemas)} contract schemas were "
            f"checked — a partial run is a failed run (D51)"
        )
        return 1
    if comparisons == 0:
        print("::error::zero comparisons performed — this check verified nothing")
        return 1

    if errors:
        for err in errors:
            print(f"::error::{err}")
        print(
            f"\n{len(errors)} divergence(s) between docs/contracts/book-api.v1.json and the live "
            f"API. Either the contract is stale or the API broke a frozen shape — decide which, "
            f"and update the contract's changelog if it is the former."
        )
        return 1

    print(f"OK — {comparisons} comparisons, no divergence.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
