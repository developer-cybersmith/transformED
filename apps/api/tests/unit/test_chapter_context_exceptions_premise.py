"""Premise assertion for the APIError FK-violation catch in put_chapter_context.

CLAUDE.md binding rule 3: "Any `except SomeLib.Error` needs an executable premise
assertion proving the type hierarchy is what you think."

This test pins the contract of `postgrest.exceptions.APIError` — specifically that:
1. The class is `Exception`-derived (not httpx.HTTPError or similar)
2. Instances carry a `.code` attribute populated with the Postgres SQLSTATE string
3. `getattr(exc, "code", None) == "23503"` is the correct FK-violation check

Pattern mirrors `test_openai_exceptions_are_not_httpx_derived` in test_retry.py.
"""

from __future__ import annotations

import inspect


def test_postgrest_api_error_is_exception_derived() -> None:
    """APIError must be a plain Exception subclass — not httpx or requests derived."""
    from postgrest.exceptions import APIError

    assert issubclass(APIError, Exception), (
        "postgrest.exceptions.APIError is not Exception-derived — "
        "the `except APIError` clause in put_chapter_context will not catch it"
    )


def test_postgrest_api_error_has_code_attribute() -> None:
    """APIError must carry a `.code` attribute — the handler uses `getattr(exc, 'code', None)`."""
    from postgrest.exceptions import APIError

    init_source = inspect.getsource(APIError)
    assert "code" in init_source, (
        "postgrest.exceptions.APIError no longer exposes a 'code' attribute — "
        "the FK-violation handler in put_chapter_context uses "
        "`getattr(exc, 'code', None) == '23503'` which would silently never match"
    )


def test_postgrest_api_error_code_is_string_type() -> None:
    """APIError.code must be a string (Postgres SQLSTATE is always a 5-char string).

    The handler compares `getattr(exc, 'code', None) == '23503'` (string equality).
    If the library changed .code to an int, every FK violation would surface as 500.
    """
    from postgrest.exceptions import APIError

    # Instantiate with a minimal valid JSON body that includes a code field.
    # postgrest APIError takes (message, json) where json is the parsed error body.
    try:
        err = APIError({"message": "FK violation", "code": "23503", "details": "", "hint": ""})
        assert hasattr(err, "code"), "APIError instance has no .code attribute"
        assert isinstance(err.code, str), (
            f"APIError.code is {type(err.code).__name__}, not str — "
            "string comparison '== \"23503\"' will never match"
        )
        assert err.code == "23503", (
            "APIError.code did not round-trip from the JSON body as expected"
        )
    except TypeError as err:
        raise AssertionError(
            "postgrest.exceptions.APIError constructor signature has changed — "
            "review the FK-violation handler in put_chapter_context"
        ) from err


def test_postgrest_api_error_code_is_int_for_non_json_response() -> None:
    """Issue #245: APIError.code is an INT (the HTTP status), not a string, when
    the response body was not valid JSON — e.g. Cloudflare's HTML error page
    for a 521 "origin down". `with_retry`'s postgrest classification branch
    depends on this being distinguishable from the normal string-code case
    above (binding rule 3: an executable premise for BOTH shapes, not just one).

    Sourced directly from the installed package's own fallback constructor,
    `postgrest.exceptions.generate_default_error_message(r)`:
        {"message": "JSON could not be generated", "code": r.status_code, ...}
    """
    from postgrest.exceptions import APIError, generate_default_error_message

    class _FakeResponse:
        status_code = 521
        content = b"<html>Cloudflare error 521: origin is down</html>"

    err = APIError(generate_default_error_message(_FakeResponse()))
    assert hasattr(err, "code"), "APIError instance has no .code attribute"
    assert isinstance(err.code, int), (
        f"APIError.code is {type(err.code).__name__}, not int — "
        "generate_default_error_message's fallback shape has changed; "
        "with_retry's int-vs-string postgrest classification depends on this"
    )
    assert err.code == 521
