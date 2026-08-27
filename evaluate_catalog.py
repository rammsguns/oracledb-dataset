"""Evaluator for the Oracle task catalog.

Reads a task catalog (JSONL: id/schema/task/gold_sql/validation_sql/expected),
and for each task:
  1. RESETS the task's schema to a known pristine state (imports
     reset_lab_schemas) so state-changing tasks start clean.
  2. Connects AS the task's schema user.
  3. Executes the answer (the gold SQL/PL/SQL by default, or a candidate
     answer passed in via --candidate).
  4. Runs the task's validation_sql.
  5. Records: pass/fail, Oracle error text, elapsed ms, and a SHA-256 checksum
     of the validation result (for later candidate-vs-gold comparison).

Usage:
    python evaluate_catalog.py --catalog llm_task_catalog.jsonl                 # gold answers
    python evaluate_catalog.py --catalog llm_task_catalog.jsonl --candidate answers.jsonl
    python evaluate_catalog.py --catalog C --gold-db <path>                     # save to another db file

Output: catalog_results.jsonl (per-task record) + summary printed to stdout.
"""
import argparse
import hashlib
import json
import os
import sys
import time
import oracledb

from reset_lab_schemas import LAB_SCHEMAS, reset_schema, DSN

# Schemas that map to the lab reset harness (have a known seed state).
RESETTABLE = set(LAB_SCHEMAS)
# Also allow HR/CO/SALES/DOCS/OPS via catalog 'schema' names that are lab users.
SCHEMA_USER = {k: v[0] for k, v in LAB_SCHEMAS.items()}

# Read-only sample schema credentials (HR/CO) — also from env vars, no secrets
# committed. e.g. ORACLE_SAMPLE_PW_HR, ORACLE_SAMPLE_PW_CO.
def _sample_pw(name):
    return os.environ.get("ORACLE_SAMPLE_PW_%s" % name, "")


def connect(schema):
    schema = schema.upper()
    if schema in LAB_SCHEMAS:
        from reset_lab_schemas import _resolve
        user, pw = _resolve(schema)
        return oracledb.connect(user=user, password=pw, dsn=DSN)
    # Fall back to HR/CO (read-only sample schemas, no reset).
    fallback = {"HR": ("hr", "HR"), "CO": ("co", "CO")}
    if schema in fallback:
        user, name = fallback[schema]
        pw = _sample_pw(name)
        if not pw:
            raise RuntimeError("Missing ORACLE_SAMPLE_PW_%s env var" % name)
        return oracledb.connect(user=user, password=pw, dsn=DSN)
    raise ValueError("Unknown schema: %s" % schema)


def checksum(rows):
    """SHA-256 of a normalized repr of the result rows (stable across types)."""
    h = hashlib.sha256()
    for row in rows:
        h.update(repr([str(x) for x in row]).encode("utf-8"))
    return h.hexdigest()


def run(conn, sql):
    """Execute SQL/PL/SQL, returning (error_text_or_None, rows).

    Handles multi-statement scripts (statements separated by ';') and single
    PL/SQL blocks (BEGIN..END;). Commits at the end.
    """
    cur = conn.cursor()
    rows = []
    try:
        stmts = split_statements(sql)
        if not stmts:
            return None, rows
        for s in stmts:
            cur.execute(s)
            if cur.description:  # a query
                rows = [tuple(r) for r in cur.fetchall()]
        conn.commit()
        return None, rows
    except oracledb.DatabaseError as e:
        conn.rollback()
        return str(e).split("\n")[0], []
    finally:
        cur.close()


def split_statements(sql):
    """Split a SQL/PL/SQL script into statements on ';'.

    Handles multi-statement scripts on one or many lines. PL/SQL blocks
    (BEGIN..END;) are kept whole: once a BEGIN/DECLARE is seen, statements are
    only split at the ';' after an END that closes the top-level block. Text is
    preserved verbatim (spaces intact); string literals and comments are
    skipped so a ';' or BEGIN/END inside them doesn't confuse the splitter.
    """
    if not sql or not sql.strip():
        return []
    out = []
    depth = 0       # PL/SQL block nesting (BEGIN/DECLARE up, END down)
    last_word = ""  # previous significant word, to detect BEGIN/END keywords
    in_block = False
    buf = []

    i, n = 0, len(sql)
    in_str = None
    while i < n:
        ch = sql[i]
        if in_str:
            buf.append(ch)
            if ch == in_str:
                if i + 1 < n and sql[i + 1] == in_str:
                    buf.append(sql[i + 1]); i += 2; continue
                in_str = None
            i += 1
            continue
        if ch in ("'", '"'):
            in_str = ch; buf.append(ch); i += 1; continue
        if ch == "-" and i + 1 < n and sql[i + 1] == "-":
            # line comment to end of line
            j = sql.find("\n", i)
            if j == -1: j = n
            buf.append(sql[i:j]); i = j; continue
        if ch == ";":
            # boundary if not inside a PL/SQL block, or closing its END;
            if depth == 0:
                buf.append(ch)
                out.append("".join(buf).strip())
                buf = []
            else:
                # inside a block: only the ';' that follows the END closes it
                # but we can't know until END is seen; handle END below instead
                buf.append(ch)
            last_word = ""
            i += 1
            continue
        # word
        if ch.isalnum() or ch == "_":
            j = i
            while j < n and (sql[j].isalnum() or sql[j] == "_"):
                j += 1
            word = sql[i:j]
            buf.append(word)
            up = word.upper()
            if up in ("BEGIN", "DECLARE") and depth == 0 and not in_block:
                depth = 1; in_block = True
            elif up == "BEGIN":
                depth += 1
            elif up == "END":
                # 'END LOOP/IF/CASE/FOR/WHILE' close inner structures, NOT the
                # block; only a bare END followed by ';' closes the block.
                # Peek ahead: if the next token is a structure keyword, ignore.
                j2 = j
                while j2 < n and sql[j2].isspace():
                    j2 += 1
                m = j2
                while m < n and (sql[m].isalnum() or sql[m] == "_"):
                    m += 1
                nxt = sql[j2:m].upper()
                if nxt in ("LOOP", "IF", "CASE", "FOR", "WHILE"):
                    pass  # not a block terminator
                else:
                    depth = max(0, depth - 1)
                    if depth == 0:
                        in_block = False
            last_word = up
            i = j
            continue
        buf.append(ch)
        i += 1

    if buf and "".join(buf).strip():
        out.append("".join(buf).strip())
    return out


def evaluate_task(conn, task, answer_sql, gold_answer_checksum=None):
    """Run one task's answer + validation. Returns a result dict."""
    start = time.perf_counter()
    err, arows = run(conn, answer_sql)
    elapsed = (time.perf_counter() - start) * 1000.0
    acs = "error" if err else checksum(arows)   # checksum([]) is deterministic

    # Run validation regardless of whether the answer executed, so we capture
    # the state the answer (partially) produced.
    verr, vrows = run(conn, task.get("validation_sql", ""))
    vcs = checksum(vrows) if vrows else ("no-rows" if not verr else "error")

    # Determine pass/fail.
    passed = True
    notes = []
    exp_err = task.get("expected_error")
    if exp_err:
        # Controlled-failure task: the answer MUST raise the expected error.
        if not err:
            passed = False
            notes.append("expected_error=%r but answer did NOT raise" % exp_err)
        elif exp_err not in (err or ""):
            passed = False
            notes.append("expected_error=%r got %r" % (exp_err, err))
    elif err:
        passed = False
        notes.append("answer_error: " + err)
    if verr:
        passed = False
        notes.append("validation_error: " + verr)
    # expected handling: 'expected_count' asserts the FIRST CELL of the first
    # validation row (e.g. a COUNT(*) value), not the row count; also allow a
    # numeric 'expected_count'. 'expected_contains' checks any cell substring.
    exp_count = task.get("expected_count")
    if exp_count is not None and not verr:
        if not vrows:
            passed = False
            notes.append("expected_count=%s but validation returned no rows" % exp_count)
        else:
            try:
                got_cell = float(vrows[0][0])
            except (TypeError, ValueError):
                got_cell = None
            if got_cell is None or got_cell != float(exp_count):
                passed = False
                notes.append("expected_count=%s got_cell=%r" % (exp_count, vrows[0][0] if vrows else None))
    exp_contains = task.get("expected_contains")
    if exp_contains and not err:
        # search both the answer output AND the validation output (DML effects
        # surface in validation, queries surface in the answer)
        hay = [str(c) for r in (arows + vrows) for c in r]
        if exp_contains not in " | ".join(hay):
            passed = False
            notes.append("expected_contains=%r not in answer/validation output" % exp_contains)
    if gold_answer_checksum is not None:
        # candidate mode: the candidate's ANSWER output must match the gold
        # answer's output (same rows), plus validation must pass.
        if not err and acs != gold_answer_checksum:
            passed = False
            notes.append("answer_checksum_mismatch gold=%s got=%s" % (
                gold_answer_checksum[:12], acs[:12]))

    return {
        "id": task.get("id"),
        "schema": task.get("schema"),
        "pass": passed,
        "executed_ok": err is None,          # answer ran without error
        "kind": classify_kind(task),          # query/dml/plsql_json/errors/other
        "is_controlled_error": bool(task.get("expected_error")),
        "expected_error": task.get("expected_error"),
        "error": err or verr or None,
        "notes": "; ".join(notes) or None,
        "elapsed_ms": round(elapsed, 1),
        "answer_checksum": acs,
        "validation_rows": len(vrows) if not verr else None,
        "validation_checksum": vcs,
        "expected": task.get("expected"),
    }


def classify_kind(task):
    """Categorize a task for metric breakdowns."""
    if task.get("expected_error"):
        return "errors"
    s = (task.get("task") or "").lower()
    if any(k in s for k in ("insert", "update", "delete", "dml", "transaction",
                            "add order", "health_check", "merge", "rollback")):
        return "dml"
    if any(k in s for k in ("ingest", "package", "pl/sql", "json", "extract",
                            "function", "units")):
        return "plsql_json"
    if any(k in s for k in ("job", "scheduler", "constraint", "privilege",
                            "security", "admin", "status")):
        return "admin"
    return "query"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", required=True)
    ap.add_argument("--candidate", default=None,
                    help="JSONL of {id, answer} to evaluate instead of gold_sql")
    ap.add_argument("--out", default="catalog_results.jsonl")
    ap.add_argument("--no-reset", action="store_true",
                    help="do NOT reset schemas before each task")
    args = ap.parse_args()

    tasks = [json.loads(l) for l in open(args.catalog) if l.strip()]
    candidates = {}
    if args.candidate:
        for l in open(args.candidate):
            if l.strip():
                c = json.loads(l)
                candidates[c["id"]] = c.get("answer", c.get("answer_sql", ""))

    results = []
    for t in tasks:
        schema = (t.get("schema") or "").upper()
        # Reset to known state before each task (skip for read-only fallbacks
        # like HR/CO that aren't resettable).
        if not args.no_reset and schema in RESETTABLE:
            try:
                reset_schema(schema)
            except Exception as e:
                print("reset failed for %s: %s" % (schema, str(e)[:80]))
        try:
            conn = connect(schema)
        except Exception as e:
            results.append({"id": t.get("id"), "schema": schema, "pass": False,
                            "error": "connect: " + str(e)[:100],
                            "elapsed_ms": 0, "validation_rows": None,
                            "validation_checksum": None, "expected": t.get("expected")})
            continue
        # Decide the answer to run.
        if candidates.get(t["id"]):
            answer = candidates[t["id"]]
            # compute gold answer checksum from a clean run of the gold answer
            if schema in RESETTABLE:
                reset_schema(schema)
            _, gold_rows = run(conn, t.get("gold_sql", ""))
            gold_ac = checksum(gold_rows)
            if schema in RESETTABLE:
                reset_schema(schema)  # clean again for the candidate run
            res = evaluate_task(conn, t, answer, gold_answer_checksum=gold_ac)
        else:
            res = evaluate_task(conn, t, t.get("gold_sql", ""))
        conn.close()
        results.append(res)

    with open(args.out, "w") as f:
        for r in results:
            f.write(json.dumps(r) + "\n")

    # Restore every resettable schema to pristine after the run, so the shared
    # DB is never left polluted by state-changing (internally-COMMIT) gold tasks.
    if not args.no_reset:
        for s in RESETTABLE:
            try:
                reset_schema(s)
            except Exception:
                pass

    n = len(results)
    passed = sum(1 for r in results if r["pass"])
    executed = sum(1 for r in results if r.get("executed_ok"))
    print("=== CATALOG EVALUATION ===")
    print("  tasks:        %d" % n)
    print("  passed:       %d (%.1f%%)" % (passed, 100.0 * passed / n if n else 0))
    print("  failed:       %d" % (n - passed))
    print("  executed_ok:  %d (%.1f%%)  [answer ran without error]" % (
        executed, 100.0 * executed / n if n else 0))
    print("  total time:   %.1fs" % (sum(r["elapsed_ms"] for r in results) / 1000))
    print("  results ->    %s" % args.out)

    # ---- Metric breakdowns (candidate-eval diagnostics) ----
    from collections import defaultdict
    def pct(num, den):
        return 100.0 * num / den if den else 0.0

    # by kind (query/dml/plsql_json/admin/errors)
    kind_stats = defaultdict(lambda: [0, 0])   # kind -> [passed, total]
    for r in results:
        k = r.get("kind", "other")
        kind_stats[k][1] += 1
        if r["pass"]:
            kind_stats[k][0] += 1
    print("  -- by kind --")
    for k in ("query", "dml", "plsql_json", "admin", "errors"):
        if k in kind_stats:
            p, t = kind_stats[k]
            print("    %-11s %3d/%3d  (%.1f%%)" % (k, p, t, pct(p, t)))

    # by schema
    schema_stats = defaultdict(lambda: [0, 0])
    for r in results:
        schema_stats[r["schema"]][1] += 1
        if r["pass"]:
            schema_stats[r["schema"]][0] += 1
    print("  -- by schema --")
    for s in sorted(schema_stats):
        p, t = schema_stats[s]
        print("    %-15s %3d/%3d  (%.1f%%)" % (s, p, t, pct(p, t)))

    # controlled-error accuracy: expected_error set AND the right error raised
    ce = [r for r in results if r.get("is_controlled_error")]
    if ce:
        ce_ok = sum(1 for r in ce if r["pass"] and r.get("expected_error")
                    and r.get("error") and r["expected_error"] in r["error"])
        print("  -- controlled-error accuracy --")
        print("    %d/%d raised the expected Oracle error" % (ce_ok, len(ce)))

    # if candidate mode, also report exact-answer (checksum) accuracy vs gold
    if args.candidate:
        exact = sum(1 for r in results
                    if not r.get("error") and r.get("answer_checksum")
                    and r.get("answer_checksum") != "error")
        # exact-answer = answer ran, validation passed, and answer checksum
        # matched gold (best proxy: pass + no error + matched checksum note)
        matched = sum(1 for r in results if r["pass"] and r.get("executed_ok")
                      and not (r.get("notes") or "").startswith("answer_checksum_mismatch"))
        print("  -- candidate exact-answer (checksum-matched) --")
        print("    %d/%d  (%.1f%%)" % (matched, n, pct(matched, n)))

    print()
    for r in results:
        mark = "PASS" if r["pass"] else "FAIL"
        print("  [%s] %-10s %-12s %-9s err=%s rows=%s cs=%.10s" % (
            mark, r["id"], r["schema"], r.get("kind", "-"),
            (r["error"] or "-")[:45], r["validation_rows"],
            r["validation_checksum"] or "-"))


if __name__ == "__main__":
    main()
