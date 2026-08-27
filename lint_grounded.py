import json
import logging
import sys

import sqlglot

logging.getLogger("sqlglot").setLevel(logging.ERROR)

from grader_lib import extract_statements

# Lint only SQL statements (not PL/SQL bodies) in the grounded batches.
for f in sys.argv[1:]:
    rows = [json.loads(l) for l in open(f)]
    bad = 0
    total = 0
    for i, r in enumerate(rows):
        for s in extract_statements(r.get("input", "") or "") + extract_statements(r["output"]):
            if s["kind"] != "sql":
                continue
            total += 1
            try:
                sqlglot.parse(s["text"], read="oracle")
            except Exception as e:
                bad += 1
                print(f"[{f}:{i}] line {s['start_line']}: {type(e).__name__}: {str(e)[:80]}")
                print(f"    {s['text'][:120]}")
    print(f"{f}: {total} SQL statements, {bad} parse failures")
