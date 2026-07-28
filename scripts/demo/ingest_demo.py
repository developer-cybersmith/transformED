"""Sprint-1 demo: upload a PDF through the real API and watch it get ingested.

Usage (inside WSL, services running — see scripts/demo/README.md):
    cd /mnt/e/transformED-corp/apps/api
    .venv/bin/python ../../scripts/demo/ingest_demo.py [path/to/chapter.pdf]

Defaults to demo-assets/sample-chapter.pdf (41-page proven chapter).
Prints a live timeline: upload -> extract -> structure -> chunk -> embed -> completed.
"""

from __future__ import annotations

import json
import pathlib
import sys
import time
import urllib.request

import httpx
import jwt

API = "http://localhost:8000"
REPO = pathlib.Path(__file__).resolve().parents[2]
ENV_PATH = REPO / "apps" / "api" / ".env"
DEFAULT_PDF = REPO / "demo-assets" / "sample-chapter.pdf"

# Demo identity — the standing test user (exists in Supabase auth)
DEMO_USER_ID = "3da3b73e-ae7b-4e4a-8916-9f393031ee39"
DEMO_EMAIL = "hieiq7@gmail.com"


def load_env() -> dict[str, str]:
    return dict(
        line.split("=", 1)
        for line in ENV_PATH.read_text().splitlines()
        if "=" in line and not line.startswith("#")
    )


def mint_jwt(env: dict[str, str]) -> str:
    """Local HS256 token — verified locally by the API (aud is required)."""
    now = int(time.time())
    return jwt.encode(
        {
            "sub": DEMO_USER_ID,
            "email": DEMO_EMAIL,
            "role": "authenticated",
            "aud": "authenticated",
            "iat": now,
            "exp": now + 2 * 3600,
        },
        env["SUPABASE_JWT_SECRET"],
        algorithm="HS256",
    )


def rest_get(env: dict[str, str], path: str) -> list[dict]:
    req = urllib.request.Request(
        env["SUPABASE_URL"].rstrip("/") + "/rest/v1/" + path,
        headers={
            "apikey": env["SUPABASE_SERVICE_ROLE_KEY"],
            "Authorization": f"Bearer {env['SUPABASE_SERVICE_ROLE_KEY']}",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())


def count(env: dict[str, str], path: str) -> int:
    req = urllib.request.Request(
        env["SUPABASE_URL"].rstrip("/") + "/rest/v1/" + path,
        headers={
            "apikey": env["SUPABASE_SERVICE_ROLE_KEY"],
            "Authorization": f"Bearer {env['SUPABASE_SERVICE_ROLE_KEY']}",
            "Prefer": "count=exact",
            "Range": "0-0",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        content_range = r.headers.get("Content-Range", "*/0")
    return int(content_range.split("/")[-1])


def main() -> None:
    pdf = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PDF
    env = load_env()
    token = mint_jwt(env)

    print(f"📄 Uploading: {pdf.name} ({pdf.stat().st_size / 1_048_576:.1f} MB)")
    t0 = time.time()
    resp = httpx.post(
        f"{API}/api/content/lessons",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": (pdf.name, pdf.read_bytes(), "application/pdf")},
        timeout=120,
    )
    resp.raise_for_status()
    lesson_id = resp.json()["lesson_id"]
    print(f"✅ Accepted (HTTP {resp.status_code}) — lesson {lesson_id}\n")

    book_id = ""
    last = ("", "")
    while True:
        rows = rest_get(
            env, f"lesson_jobs?lesson_id=eq.{lesson_id}&select=status,last_node,error"
        )
        job = rows[0] if rows else {}
        state = (job.get("status", "?"), job.get("last_node") or "-")
        if state != last:
            print(f"  [{time.time() - t0:6.0f}s]  {state[0]:<10} node={state[1]}")
            last = state
        if job.get("status") in ("completed", "failed"):
            break
        time.sleep(10)

    lesson = rest_get(env, f"lessons?lesson_id=eq.{lesson_id}&select=book_id")
    book_id = lesson[0]["book_id"] if lesson else ""
    total = time.time() - t0

    if job.get("status") == "completed":
        pages = rest_get(env, f"books?book_id=eq.{book_id}&select=page_count")
        chunks = count(env, f"chunks?book_id=eq.{book_id}&select=chunk_id")
        embedded = count(
            env, f"chunks?book_id=eq.{book_id}&embedding=not.is.null&select=chunk_id"
        )
        print(f"\n🎉 COMPLETED in {total / 60:.1f} min")
        print(f"   pages read:        {pages[0]['page_count'] if pages else '?'}")
        print(f"   knowledge chunks:  {chunks}")
        print(f"   embedded/searchable: {embedded}/{chunks}")
        print(f"\n   Next: ask it a question →")
        print(f"   .venv/bin/python ../../scripts/demo/ask_the_book.py {book_id} \"your question\"")
    else:
        print(f"\n❌ FAILED after {total / 60:.1f} min: {job.get('error')}")
        sys.exit(1)


if __name__ == "__main__":
    main()
