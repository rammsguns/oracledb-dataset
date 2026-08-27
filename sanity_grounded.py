import json
import sys

from grader_lib import extract_statements

# Quick sanity: parse JSON + extract statements from the grounded batches.
for f in sys.argv[1:]:
    rows = [json.loads(l) for l in open(f)]
    print(f"{f}: {len(rows)} records, all JSON-valid")
    total_sql, total_plsql = 0, 0
    for r in rows:
        # input statements (schema)
        for s in extract_statements(r.get("input", "") or ""):
            if s["kind"] == "sql":
                total_sql += 1
            else:
                total_plsql += 1
        # output statements
        for s in extract_statements(r["output"]):
            if s["kind"] == "sql":
                total_sql += 1
            else:
                total_plsql += 1
    print(f"  extracted: {total_sql} sql, {total_plsql} plsql/anon statements")

    # Verify every record has a non-empty input (grounded) and output
    ungrounded = [i for i, r in enumerate(rows) if not (r.get("input") or "").strip()]
    print(f"  ungrounded (empty input): {len(ungrounded)} {ungrounded}")
