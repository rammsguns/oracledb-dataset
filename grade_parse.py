"""
Parser-only grader (runs without a live Oracle).

Verifies that SQL statements and PL/SQL block *framing* parse under the
Oracle dialect using sqlglot. This is a syntax layer — it catches broken
SQL and malformed block structure, but does NOT compile PL/SQL bodies
(that requires the execution grader in grade_db.py).

Usage:
    .venv/bin/python grade_parse.py oracle_dataset_full.jsonl
"""
import json
import logging
import re
import sys

import sqlglot

# sqlglot logs "unsupported syntax -> falling back to Command" warnings for
# PL/SQL bodies (expected: it treats them as opaque). Silence the noise.
logging.getLogger("sqlglot").setLevel(logging.ERROR)

from grader_lib import extract_statements


def parse_one(stmt):
    """Return (ok, note). ok=True means sqlglot parsed without raising."""
    try:
        parsed = sqlglot.parse(stmt["text"], read="oracle")
        if not parsed:
            return True, "empty"
        return True, ""
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)[:80]}"


def grade_output(output_text):
    """Grade one example's output. SQL statements are linted; PL/SQL blocks are
    only FRAMING-checked (sqlglot cannot compile PL/SQL bodies — that needs the
    execution grader)."""
    stmts = extract_statements(output_text)
    results = []
    for s in stmts:
        if s["kind"] in ("plsql", "anon"):
            # sqlglot treats PL/SQL bodies as opaque commands; a parse "ok" here
            # only means the CREATE/block header was frameable. Mark unverified.
            results.append({"kind": s["kind"], "line": s["start_line"],
                            "ok": None, "note": "unverified (needs live Oracle)"})
            continue
        # EXEC/EXECUTE are SQL*Plus client commands (dynamic invocation), not SQL
        # parseable by sqlglot — they're exercised by the execution grader.
        if re.match(r'^\s*(EXEC|EXECUTE)\b', s["text"], re.IGNORECASE):
            results.append({"kind": s["kind"], "line": s["start_line"],
                            "ok": None, "note": "sqlplus EXEC (execution-graded)"})
            continue
        ok, note = parse_one(s)
        results.append({"kind": s["kind"], "line": s["start_line"],
                        "ok": ok, "note": note})
    return results


def main(path):
    rows = [json.loads(l) for l in open(path)]

    stats = {"examples": len(rows), "sql_ok": 0, "sql_fail": 0,
             "plsql_unverified": 0, "anon_unverified": 0,
             "examples_with_sql_failures": 0, "examples_with_code": 0,
             "no_code_found": 0}

    failures = []

    for idx, r in enumerate(rows):
        res = grade_output(r["output"])
        if res:
            stats["examples_with_code"] += 1
        else:
            stats["no_code_found"] += 1

        ex_fail = 0
        for x in res:
            if x["ok"] is None:
                stats[f"{x['kind']}_unverified"] = stats.get(f"{x['kind']}_unverified", 0) + 1
                continue
            key = f"sql_{'ok' if x['ok'] else 'fail'}"
            stats[key] = stats.get(key, 0) + 1
            if not x["ok"]:
                ex_fail += 1
        if ex_fail:
            stats["examples_with_sql_failures"] += 1
            failures.append({
                "idx": idx,
                "instruction": r["instruction"][:90],
                "fail_count": ex_fail,
                "details": [x for x in res if x["ok"] is False],
            })

    print(f"=== PARSER GRADER (SQL lint only): {path} ===")
    print(f"examples: {stats['examples']}")
    print(f"with detectable code: {stats['examples_with_code']}  "
          f"no code found: {stats['no_code_found']}")
    print(f"SQL statements        OK={stats.get('sql_ok',0)}  FAIL={stats.get('sql_fail',0)}")
    print(f"PL/SQL create blocks  unverified={stats.get('plsql_unverified',0)} "
          f"(needs live Oracle)")
    print(f"anon PL/SQL blocks    unverified={stats.get('anon_unverified',0)} "
          f"(needs live Oracle)")
    print(f"examples with >=1 SQL parse failure: {stats['examples_with_sql_failures']}")

    print(f"\n=== SQL FAILURES ({len(failures)}) ===")
    for f in failures:
        print(f"\n[{f['idx']}] {f['instruction']}")
        for d in f["details"]:
            print(f"    line {d['line']} [sql]: {d['note']}")

    json.dump({"stats": stats, "failures": failures},
              open("grade_parse_report.json", "w"), indent=2, ensure_ascii=False)
    print("\nreport -> grade_parse_report.json")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "oracle_dataset_full.jsonl")
