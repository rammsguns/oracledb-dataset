"""
Execution grader: runs each example's SQL/PL/SQL against a live Oracle and
records pass/fail/schema-missing verdicts.

Grounded examples carry their schema (CREATE TABLE / INSERT seed) in the
`input` field. This grader creates that schema before running the example's
output statements, then drops everything it created so each example runs in a
clean slate. For ungrounded examples (empty input), output statements run
against whatever schema exists, and ORA-00942/00904 land as SCHEMA_MISS.

Usage:
    .venv/bin/python grade_db.py oracle_dataset_full.jsonl

Requires python-oracledb (thin mode, no client libs):
    uv pip install oracledb

Connection comes from env vars (see README.md):
    ORACLE_DSN      e.g. localhost:1521/FREEPDB1
    ORACLE_USER     e.g. system
    ORACLE_PASSWORD e.g. oracle
"""
import json
import os
import re
import sys

try:
    import oracledb
except ImportError:
    print("oracledb not installed. Run: uv pip install oracledb")
    sys.exit(1)

from grader_lib import extract_statements

# --- Error classification ------------------------------------------------

# Codes meaning "referenced object/column missing" -> not a code defect.
SCHEMA_MISS_CODES = {
    "ORA-00942",  # table or view does not exist
    "ORA-00904",  # invalid identifier
    "ORA-00903",  # invalid table name
    "ORA-01031",  # insufficient privileges
    "ORA-06550",  # PL/SQL compiled but referenced object unknown
    "ORA-01435",  # user does not exist
}

# Codes meaning a real defect in the example regardless of schema.
CODE_FAIL_CODES = {
    "ORA-00933", "ORA-00936", "ORA-00937", "ORA-00911", "ORA-01722",
    "ORA-00918", "ORA-00920", "ORA-00923", "ORA-00907", "ORA-00905",
    "ORA-01747", "ORA-01788", "ORA-00906", "ORA-00979",
    "PLS-00103", "PLS-00201", "PLS-00306", "PLS-00323", "PLS-00382",
    "PLS-00428", "PLS-00402", "PLS-00049", "PLS-00313", "PLS-00114",
    "SP2-", "ORA-06550",
}


def classify_error(code_str, note=""):
    # ORA-06550 wraps the real error (a PL/SQL compile error). Unwrap it:
    # if it encloses a missing-table/column code, that's SCHEMA_MISS (the code
    # references an undeclared object), not a defect.
    if "06550" in code_str or "PL/SQL:" in note or "PLS-" in code_str:
        inner = re.search(r'ORA-(\d{5})', note)
        if inner:
            inner_code = "ORA-" + inner.group(1)
            if inner_code in SCHEMA_MISS_CODES:
                return "SCHEMA_MISS"
    if code_str in CODE_FAIL_CODES or code_str.startswith("PLS-"):
        return "FAIL"
    if code_str in SCHEMA_MISS_CODES:
        return "SCHEMA_MISS"
    return "UNKNOWN"


# --- Object-name extraction for cleanup ----------------------------------

CREATE_OBJECT_RE = re.compile(
    r'^\s*CREATE\s+(OR\s+REPLACE\s+)?'
    r'(TABLE|SEQUENCE|VIEW|PROCEDURE|FUNCTION|PACKAGE|TRIGGER|TYPE|'
    r'MATERIALIZED\s+VIEW|INDEX|SYNONYM)\s+'
    r'"?([A-Za-z0-9_$#]+)"?',
    re.IGNORECASE,
)

# Statement kinds we should NOT execute (client commands, DBA-only, destructive).
SKIP_PATTERNS = (
    r'^\s*(EXEC|EXECUTE)\b',          # sqlplus client command
    r'^\s*RMAN', r'^\s*srvctl', r'^\s*DGMGRL', r'^\s*netstat',
    r'^\s*(SHUTDOWN|STARTUP)\b',      # instance-level, never in grader
    r'^\s*DROP\s+(DATABASE|TABLESPACE|USER)\b',
    r'^\s*ALTER\s+SYSTEM\b',          # could change global state
    r'^\s*(ALTER\s+DATABASE|ALTER\s+DISKGROUP|CREATE\s+TABLESPACE|'
    r'ALTER\s+TABLESPACE)\b',         # DBA storage ops needing real env/files
)


def should_skip(text):
    return any(re.match(p, text, re.IGNORECASE) for p in SKIP_PATTERNS)


def extract_created_names(text):
    """Return (kind, name) pairs for objects this script creates, for cleanup."""
    found = []
    for m in CREATE_OBJECT_RE.finditer(text):
        kind = m.group(2).strip().upper()
        name = m.group(3)
        found.append((kind, name))
    return found


# --- Execution -----------------------------------------------------------

def run_script(cur, conn, statements):
    """Run a list of {text, kind} statements, returning list of verdicts."""
    results = []
    for s in statements:
        text = s["text"].strip()
        if should_skip(text):
            results.append({"kind": s["kind"], "line": s["start_line"],
                            "verdict": "SKIP", "note": "client/DBA command"})
            continue
        try:
            cur.execute(text)
            # Drain result sets so later statements aren't confused.
            try:
                while True:
                    if not cur.fetchmany(50):
                        break
            except Exception:
                pass
            results.append({"kind": s["kind"], "line": s["start_line"],
                            "verdict": "PASS", "note": ""})
        except oracledb.DatabaseError as e:
            code = None
            if e.args and e.args[0] and hasattr(e.args[0], "code"):
                code = e.args[0].code
            elif getattr(e, "code", None):
                code = e.code
            code_str = ""
            if code:
                n = abs(code)
                code_str = f"ORA-{n:05d}" if n < 100000 else str(code)
            # Fallback: parse ORA-/PLS- token from the message.
            if not code_str:
                m = re.search(r'(ORA-\d+|PLS-\d+)', str(e))
                code_str = m.group(1) if m else "UNKNOWN"
            verdict = classify_error(code_str, str(e))
            results.append({"kind": s["kind"], "line": s["start_line"],
                            "verdict": verdict,
                            "note": f"{code_str}: {str(e)[:120]}"})
    return results


def drop_objects(cur, created):
    """Drop objects in reverse-safe order. Best-effort; ignores failures."""
    # Drop procedures/functions/packages/triggers/types/views before tables.
    order_priority = {
        "TRIGGER": 0, "PACKAGE": 0, "PROCEDURE": 0, "FUNCTION": 0,
        "TYPE": 0, "VIEW": 1, "MATERIALIZED VIEW": 1, "INDEX": 2,
        "SEQUENCE": 2, "TABLE": 3, "SYNONYM": 0,
    }
    for kind, name in sorted(created, key=lambda kn: order_priority.get(kn[0], 9)):
        if kind == "MATERIALIZED VIEW":
            ddl = f'DROP MATERIALIZED VIEW "{name}"'
        elif kind == "TABLE":
            ddl = f'DROP TABLE "{name}" PURGE'
        elif kind == "INDEX":
            ddl = f'DROP INDEX "{name}"'
        else:
            ddl = f'DROP {kind} "{name}"'
        try:
            cur.execute(ddl)
        except Exception:
            pass


def main(path):
    rows = [json.loads(l) for l in open(path)]
    dsn = os.environ.get("ORACLE_DSN", "localhost:1521/FREEPDB1")

    # Real sample schemas (pre-created, populated, must NEVER be wiped).
    # Passwords are read from env (ORACLE_SAMPLE_PW_<NAME> / ORACLE_LAB_PW_<NAME>)
    # so no credentials are committed to the repo.
    def _pw(name):
        return os.environ.get("ORACLE_SAMPLE_PW_%s" % name,
                              os.environ.get("ORACLE_LAB_PW_%s" % name, ""))
    SAMPLE_SCHEMAS = {
        "HR": ("hr", "HR"),
        "CO": ("co", "CO"),
        "SALES_LAB": ("SALES_LAB", "SALES_LAB"),
        "DOCUMENTS_LAB": ("DOCUMENTS_LAB", "DOCUMENTS_LAB"),
        "OPS_LAB": ("OPS_LAB", "OPS_LAB"),
        "LOGISTICS_LAB": ("LOGISTICS_LAB", "LOGISTICS_LAB"),
        "SUPPORT_LAB": ("SUPPORT_LAB", "SUPPORT_LAB"),
    }
    GRADER_SCHEMA = "GRADER"

    results = []
    for idx, r in enumerate(rows):
        per_example = []
        target = (r.get("schema") or "GRADER").upper()

        if target in SAMPLE_SCHEMAS:
            # Real schema: connect directly, run against live data. No wipe.
            su, name = SAMPLE_SCHEMAS[target]
            spw = _pw(name)
            if not spw:
                spw = os.environ.get("ORACLE_%s_PASSWORD" % name, "")
            conn = oracledb.connect(user=su, password=spw, dsn=dsn)
            cur = conn.cursor()
            inp_stmts = []   # sample schema tables already exist; skip schema build
            out_stmts = extract_statements(r["output"])
            out_results = run_script(cur, conn, out_stmts)
            per_example.extend(out_results)
            conn.close()
        else:
            # GRADER scratch schema: connect directly if it exists; only fall
            # back to the system account to CREATE it on first run.
            try:
                conn = oracledb.connect(user=GRADER_SCHEMA, password="grader", dsn=dsn)
            except oracledb.DatabaseError:
                sysadmin = oracledb.connect(
                    user="system",
                    password=os.environ.get("ORACLE_SYSTEM_PASSWORD", "oracle"),
                    dsn=dsn)
                scur = sysadmin.cursor()
                scur.execute("SELECT COUNT(*) FROM all_users WHERE username = :u",
                             [GRADER_SCHEMA])
                if scur.fetchone()[0] == 0:
                    scur.execute(f'CREATE USER {GRADER_SCHEMA} IDENTIFIED BY grader '
                                 f'DEFAULT TABLESPACE users QUOTA UNLIMITED ON users')
                scur.execute(f'GRANT DBA TO {GRADER_SCHEMA}')
                sysadmin.commit()
                sysadmin.close()
                conn = oracledb.connect(user=GRADER_SCHEMA, password="grader", dsn=dsn)
            cur = conn.cursor()

            created = []
            # Fresh slate before EVERY example.
            cur.execute("""
                DECLARE
                  PROCEDURE try_drop(p_sql VARCHAR2) IS
                  BEGIN
                    EXECUTE IMMEDIATE p_sql;
                  EXCEPTION WHEN OTHERS THEN NULL;
                  END;
                BEGIN
                  FOR t IN (SELECT table_name FROM user_tables) LOOP
                    try_drop('DROP TABLE "' || t.table_name || '" CASCADE CONSTRAINTS PURGE');
                  END LOOP;
                  FOR s IN (SELECT sequence_name FROM user_sequences) LOOP
                    try_drop('DROP SEQUENCE "' || s.sequence_name || '"');
                  END LOOP;
                  FOR o IN (SELECT object_type, object_name FROM user_objects
                             WHERE object_type IN
                               ('PROCEDURE','FUNCTION','PACKAGE','TRIGGER','TYPE','VIEW',
                                'MATERIALIZED VIEW','SYNONYM')) LOOP
                    try_drop('DROP ' || o.object_type || ' "' || o.object_name || '"');
                  END LOOP;
                END;
            """)
            conn.commit()

            # Build schema from input (if grounded).
            inp = r.get("input", "") or ""
            inp_stmts = extract_statements(inp) if inp.strip() else []
            if inp_stmts:
                for s in inp_stmts:
                    created.extend(extract_created_names(s["text"]))
                inp_results = run_script(cur, conn, inp_stmts)
                inp_fail = [x for x in inp_results if x["verdict"] not in ("PASS", "SKIP")]
                if inp_fail:
                    per_example.append({
                        "kind": "schema", "line": 0, "verdict": "SCHEMA_SETUP_FAIL",
                        "note": "; ".join(x["note"] for x in inp_fail[:3])})
                    drop_objects(cur, created)
                    conn.commit()
                    results.append({"idx": idx, "instruction": r["instruction"][:80],
                                    "schema": target, "results": per_example})
                    conn.close()
                    continue

            out_stmts = extract_statements(r["output"])
            for s in out_stmts:
                created.extend(extract_created_names(s["text"]))
            out_results = run_script(cur, conn, out_stmts)
            per_example.extend(out_results)

            # Cleanup everything this example created.
            drop_objects(cur, created)
            conn.commit()
            conn.close()

        # 3. Optional expected-result verification: run each {sql, value} check
        #    and compare the first column of the first returned row.
        for check in r.get("expected", []) or []:
            chk_sql = check.get("sql", "")
            want = check.get("value")
            if not chk_sql:
                continue
            # Reconnect to the target schema for the check.
            if target in SAMPLE_SCHEMAS:
                su, name = SAMPLE_SCHEMAS[target]
                spw = _pw(name)
                if not spw:
                    spw = os.environ.get("ORACLE_%s_PASSWORD" % name, "")
                c2 = oracledb.connect(user=su, password=spw, dsn=dsn)
            else:
                c2 = oracledb.connect(user=GRADER_SCHEMA, password="grader", dsn=dsn)
            ccur = c2.cursor()
            try:
                ccur.execute(chk_sql)
                row = ccur.fetchone()
                got = row[0] if row else None
                # normalize for comparison: numbers compare numerically so
                # "13500.0" == "13500"; strings compare exactly.
                def norm(x):
                    if x is None:
                        return (None, None)
                    try:
                        if isinstance(x, bool):
                            raise TypeError
                        f = float(x)
                        return ("num", round(f, 6))
                    except (TypeError, ValueError):
                        return ("str", str(x))
                gn, gv = norm(got)
                wn, wv = norm(want)
                verdict = "CHECK_PASS" if (gn == wn and gv == wv) else "CHECK_FAIL"
                note = f"expected={want!r} got={got!r}"
            except oracledb.DatabaseError as e:
                verdict = "CHECK_ERROR"
                note = f"{str(e)[:120]}"
            c2.close()
            per_example.append({"kind": "check", "line": 0, "verdict": verdict, "note": note})

        results.append({"idx": idx, "instruction": r["instruction"][:80],
                        "schema": target, "results": per_example})

    # Summary.
    tally = {}
    ex_with_fail = 0
    for v in results:
        vv = [x["verdict"] for x in v["results"]]
        if "FAIL" in vv or "CHECK_FAIL" in vv:
            ex_with_fail += 1
        for x in v["results"]:
            tally[x["verdict"]] = tally.get(x["verdict"], 0) + 1

    print("=== EXECUTION GRADER SUMMARY ===")
    for k in ("PASS", "FAIL", "SCHEMA_MISS", "SCHEMA_SETUP_FAIL", "SKIP", "UNKNOWN",
              "CHECK_PASS", "CHECK_FAIL", "CHECK_ERROR"):
        if k in tally:
            print(f"  {k:18} {tally[k]}")
    print(f"  examples with >=1 FAIL/CHECK_FAIL: {ex_with_fail} / {len(results)}")

    json.dump(results, open("grade_db_report.json", "w"), indent=2, ensure_ascii=False)
    print("\nreport -> grade_db_report.json")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "oracle_dataset_full.jsonl")
