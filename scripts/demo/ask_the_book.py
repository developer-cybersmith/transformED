"""Sprint-1 demo: ask a question in plain English — the system finds the exact
passage in the ingested book using the stored embeddings (semantic search).

This is the same mechanism the Phase-2 tutor will use: the STUDENT'S QUESTION
is embedded at query time (explicitly permitted); stored chunk embeddings are
never regenerated.

Usage (inside WSL):
    cd /mnt/e/transformED-corp/apps/api
    .venv/bin/python ../../scripts/demo/ask_the_book.py <book_id> "How does ...?"
If book_id is omitted, uses the most recently ingested ready book.
"""

from __future__ import annotations

import json
import math
import pathlib
import sys
import urllib.request

from openai import OpenAI

REPO = pathlib.Path(__file__).resolve().parents[2]
ENV_PATH = REPO / "apps" / "api" / ".env"


def load_env() -> dict[str, str]:
    return dict(
        line.split("=", 1)
        for line in ENV_PATH.read_text().splitlines()
        if "=" in line and not line.startswith("#")
    )


def rest_get(env: dict[str, str], path: str) -> list[dict]:
    req = urllib.request.Request(
        env["SUPABASE_URL"].rstrip("/") + "/rest/v1/" + path,
        headers={
            "apikey": env["SUPABASE_SERVICE_ROLE_KEY"],
            "Authorization": f"Bearer {env['SUPABASE_SERVICE_ROLE_KEY']}",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na and nb else 0.0


def main() -> None:
    args = sys.argv[1:]
    env = load_env()

    if args and len(args[0]) == 36 and args[0].count("-") == 4:
        book_id, questions = args[0], args[1:]
    else:
        books = rest_get(env, "books?status=eq.ready&select=book_id,filename&order=created_at.desc&limit=1")
        if not books:
            sys.exit("No ready book found — run ingest_demo.py first.")
        book_id, questions = books[0]["book_id"], args
        print(f"(using most recent book: {books[0]['filename']})")

    if not questions:
        questions = ["How much virtual address space does a 32-bit Windows process get?"]

    print(f"📚 Loading knowledge chunks for book {book_id[:8]}…")
    chunks = rest_get(
        env,
        f"chunks?book_id=eq.{book_id}&embedding=not.is.null"
        f"&select=chunk_index,content,embedding&order=chunk_index",
    )
    if not chunks:
        sys.exit("Book has no embedded chunks.")
    for c in chunks:
        c["vec"] = json.loads(c["embedding"])  # pgvector serializes as JSON array text
    print(f"   {len(chunks)} chunks loaded.\n")

    client = OpenAI(api_key=env["OPENAI_API_KEY"])
    for q in questions:
        print(f"❓ {q}")
        qvec = client.embeddings.create(model="text-embedding-3-small", input=[q]).data[0].embedding
        ranked = sorted(chunks, key=lambda c: cosine(qvec, c["vec"]), reverse=True)[:2]
        for rank, c in enumerate(ranked, 1):
            score = cosine(qvec, c["vec"])
            preview = " ".join(c["content"].split())[:400]
            print(f"\n   #{rank} (chunk {c['chunk_index']}, relevance {score:.3f}):")
            print(f"   “{preview}…”")
        print("\n" + "─" * 70 + "\n")


if __name__ == "__main__":
    main()
