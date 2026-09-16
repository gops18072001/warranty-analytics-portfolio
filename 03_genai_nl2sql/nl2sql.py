"""
Ask the warranty database questions in plain English.

A small natural-language-to-SQL tool over the same SQLite database built in
project 01. Claude is given the schema, writes a SELECT, the query runs
locally, and Claude explains the result.

Why this one: it is a GenAI project an *analyst* would build - it makes a
database answerable by someone who does not write SQL, which is a real thing
analysts are asked for. It is not a chatbot demo.

Setup:
    pip install -r requirements.txt
    export ANTHROPIC_API_KEY=sk-ant-...     # or: ant auth login

Usage:
    python nl2sql.py "which supplier costs us the most in warranty claims?"
    python nl2sql.py --explain "how did Shreeji Connectors trend over 2025?"
    python nl2sql.py                         # interactive
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from pathlib import Path

import anthropic

DB_PATH = Path(__file__).parent.parent / "01_sql_warranty_analytics" / "warranty.db"
MODEL = "claude-opus-5"
MAX_ROWS = 50

# Only SELECT runs. The model is told this, but the guard below is what
# actually enforces it - never rely on the prompt alone for a safety property.
FORBIDDEN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|REPLACE|TRUNCATE|ATTACH|DETACH|PRAGMA|VACUUM)\b",
    re.IGNORECASE,
)


def load_schema(con: sqlite3.Connection) -> str:
    """Read the live schema so the prompt can never drift from the database."""
    rows = con.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND sql IS NOT NULL"
    ).fetchall()
    return "\n\n".join(r[0] for r in rows)


SYSTEM = """You translate questions about an automotive warranty database into SQLite SQL.

Rules:
- Emit exactly one SELECT statement. No INSERT, UPDATE, DELETE, DDL or PRAGMA.
- Return only the SQL. No markdown fences, no commentary.
- Dates are TEXT in 'YYYY-MM-DD' form; use strftime() for date parts.
- Always LIMIT to 50 rows or fewer unless the question is an aggregate that
  naturally returns fewer.
- Give every computed column a readable alias.

Critical correctness rule - join fan-out:
production_batches and warranty_claims are one-to-many. Joining them directly
and then summing units_produced multiplies that sum by the claim count, which
is silently wrong. When a query needs BOTH a units measure and a claims
measure, aggregate claims to one row per batch first:

    WITH claims_per_batch AS (
        SELECT batch_id, COUNT(*) AS claims, SUM(claim_cost_inr) AS cost
        FROM warranty_claims GROUP BY batch_id
    )
    SELECT ... FROM production_batches pb
    LEFT JOIN claims_per_batch cpb ON cpb.batch_id = pb.batch_id

Data caveat worth respecting: claims surface 20-400 days after production and
the data ends 2026-06-30, so recent batches are right-censored and look
artificially healthy. If a question asks about a trend or compares periods,
prefer batches produced on or before 2025-12-31."""


def strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:sql)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip().rstrip(";")


def generate_sql(client: anthropic.Anthropic, schema: str, question: str) -> str:
    response = client.messages.create(
        model=MODEL,
        max_tokens=2000,
        system=[
            {
                "type": "text",
                "text": SYSTEM + "\n\nSchema:\n" + schema,
                # The schema and rules are identical on every call, so cache
                # them: only the question varies.
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": question}],
    )
    if response.stop_reason == "refusal":
        raise RuntimeError("Model declined to answer this question.")
    sql = next((b.text for b in response.content if b.type == "text"), "")
    return strip_fences(sql)


def run_sql(con: sqlite3.Connection, sql: str) -> tuple[list[str], list[tuple]]:
    if FORBIDDEN.search(sql):
        raise ValueError(f"Refusing to run non-SELECT statement:\n{sql}")
    if not sql.lstrip().upper().startswith(("SELECT", "WITH")):
        raise ValueError(f"Not a SELECT statement:\n{sql}")
    cur = con.execute(sql)
    cols = [d[0] for d in cur.description]
    return cols, cur.fetchmany(MAX_ROWS)


def explain(client: anthropic.Anthropic, question: str, sql: str,
            cols: list[str], rows: list[tuple]) -> str:
    table = " | ".join(cols) + "\n" + "\n".join(
        " | ".join(str(v) for v in r) for r in rows[:20]
    )
    response = client.messages.create(
        model=MODEL,
        max_tokens=1000,
        system="You are a data analyst. Answer the question from the result "
               "table in 2-4 sentences. Quote the specific numbers that matter. "
               "If the result looks distorted by the right-censoring caveat, say so.",
        messages=[{
            "role": "user",
            "content": f"Question: {question}\n\nSQL:\n{sql}\n\nResult:\n{table}",
        }],
    )
    return next((b.text for b in response.content if b.type == "text"), "")


def render(cols: list[str], rows: list[tuple]) -> str:
    if not rows:
        return "(no rows)"
    widths = [
        max(len(str(c)), max((len(str(r[i])) for r in rows), default=0))
        for i, c in enumerate(cols)
    ]
    out = ["  ".join(str(c).ljust(w) for c, w in zip(cols, widths))]
    out.append("  ".join("-" * w for w in widths))
    out += ["  ".join(str(v).ljust(w) for v, w in zip(r, widths)) for r in rows]
    return "\n".join(out)


def answer(client, con, schema, question: str, do_explain: bool) -> None:
    print(f"\nQ: {question}")
    try:
        sql = generate_sql(client, schema, question)
    except anthropic.AuthenticationError:
        sys.exit("No valid credentials. Set ANTHROPIC_API_KEY or run `ant auth login`.")
    except anthropic.RateLimitError:
        sys.exit("Rate limited - wait a moment and retry.")
    except anthropic.APIConnectionError:
        sys.exit("Network error reaching the API.")

    print(f"\n--- SQL ---\n{sql}\n")
    try:
        cols, rows = run_sql(con, sql)
    except (ValueError, sqlite3.Error) as e:
        print(f"Query failed: {e}")
        return

    print(f"--- Result ({len(rows)} rows) ---")
    print(render(cols, rows))

    if do_explain and rows:
        print(f"\n--- Answer ---\n{explain(client, question, sql, cols, rows)}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Ask the warranty database in English.")
    ap.add_argument("question", nargs="*", help="question in plain English")
    ap.add_argument("--explain", action="store_true",
                    help="have Claude interpret the result table too")
    args = ap.parse_args()

    if not DB_PATH.exists():
        sys.exit(f"Database not found at {DB_PATH}\n"
                 f"Run: cd ../01_sql_warranty_analytics && python generate_data.py")

    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)  # read-only
    schema = load_schema(con)
    client = anthropic.Anthropic()

    if args.question:
        answer(client, con, schema, " ".join(args.question), args.explain)
        return

    print("Warranty DB - ask a question, or Ctrl-D to quit.")
    while True:
        try:
            q = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if q:
            answer(client, con, schema, q, args.explain)


if __name__ == "__main__":
    main()
