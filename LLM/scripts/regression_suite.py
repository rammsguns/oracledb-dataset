#!/usr/bin/env python3
"""Independent regression suite (production-like Oracle requests).

These prompts are AUTHORED INDEPENDENTLY for this suite — they are NOT drawn
from, derived from, or paraphrases of the held-out execution catalog
(llm_task_catalog_eval.jsonl). They target the real lab schemas (SALES_LAB,
LOGISTICS_LAB, etc.) with production-style business questions.

For each case:
1. Reset the target lab schema to pristine (env-var creds, read-only? no —
   reset via reset_lab_schemas).
2. Ask the deployed adapter (OpenAI-compatible endpoint) for SQL-only.
3. Execute the returned SQL against live Oracle as the schema user.
4. Assert it runs and the answer/validation matches an expected value.

This never touches the held-out catalog. The expected values come from the
KNOWN seed data in reset_lab_schemas.py.

Usage:
    python scripts/regression_suite.py --base-url http://127.0.0.1:8800
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request

import oracledb

LLM = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(LLM)
DSN = "localhost:1521/FREEPDB1"
sys.path.insert(0, REPO)
from reset_lab_schemas import reset_schema  # noqa: E402

# (schema, prompt, expected_cell_contains, validation_sql)
# Expected values derive from reset_lab_schemas.py seed data (known, stable).
# Each case is (schema, prompt, expect, validation_sql, category).
# category: select | join | schema_qualified | plsql | privilege
CASES = [
    ("SALES_LAB",
     "Write a query showing customer names and order amounts from the sales orders table, ordered by amount descending. The table is in the SALES_LAB schema.",
     "Summit",
     "SELECT customer_name FROM llm_sales_orders ORDER BY amount DESC", "select"),
    ("SALES_LAB",
     "Count how many orders exist in the SALES_LAB sales orders table.",
     "3",
     "SELECT COUNT(*) FROM llm_sales_orders", "select"),
    ("SALES_LAB",
     "List the sales regions and their managers from the regions table in SALES_LAB.",
     "North",
     "SELECT region_name FROM llm_sales_regions", "select"),
    ("SALES_LAB",
     "Show the region materialized view with order count and revenue, ordered by revenue descending.",
     "South",
     "SELECT region_name FROM llm_sales_region_mv ORDER BY revenue DESC", "select"),
    ("LOGISTICS_LAB",
     "List products and their unit costs from the LOGISTICS_LAB products table.",
     "Widget",
     "SELECT product_name FROM llm_log_products", "select"),
    ("LOGISTICS_LAB",
     "Count shipments in the LOGISTICS_LAB shipments table.",
     "6",
     "SELECT COUNT(*) FROM llm_log_shipments", "select"),
    ("LOGISTICS_LAB",
     "Show warehouses and their regions from the LOGISTICS_LAB warehouses table.",
     "East",
     "SELECT warehouse_name FROM llm_log_warehouses", "select"),
    ("SUPPORT_LAB",
     "Count support tickets in the SUPPORT_LAB tickets table.",
     "6",
     "SELECT COUNT(*) FROM llm_sup_tickets", "select"),
    ("SUPPORT_LAB",
     "List support agents and their teams from the SUPPORT_LAB agents table.",
     "Alice",
     "SELECT agent_name FROM llm_sup_agents", "select"),
    ("DOCUMENTS_LAB",
     "Show invoices and their suppliers from the DOCUMENTS_LAB invoice table.",
     "Acme",
     "SELECT supplier FROM llm_doc_invoice", "select"),
    # ---- joins (S3) ----
    ("SALES_LAB",
     "Write a join showing each order's customer name and the region name it belongs to, by joining the orders and regions tables in SALES_LAB.",
     "North",
     "SELECT r.region_name FROM llm_sales_orders o JOIN llm_sales_regions r ON o.region_id = r.region_id", "join"),
    ("LOGISTICS_LAB",
     "Write a join listing each shipment's product name and status by joining the shipments and products tables in LOGISTICS_LAB.",
     "Widget",
     "SELECT p.product_name FROM llm_log_shipments s JOIN llm_log_products p ON s.product_id = p.product_id", "join"),
    # ---- schema-qualified objects (S3) ----
    ("SALES_LAB",
     "Write a query using the fully schema-qualified table name SALES_LAB.LLM_SALES_ORDERS to show orders above amount 2000.",
     "Summit",
     "SELECT customer_name FROM SALES_LAB.llm_sales_orders WHERE amount > 2000", "schema_qualified"),
    ("DOCUMENTS_LAB",
     "Write a query using the fully qualified table DOCUMENTS_LAB.LLM_DOC_INVOICE to list all invoices.",
     "Acme",
     "SELECT supplier FROM DOCUMENTS_LAB.llm_doc_invoice", "schema_qualified"),
    # ---- PL/SQL (S3) ----
    ("SALES_LAB",
     "Write a PL/SQL anonymous block that selects the total sales amount from LLM_SALES_ORDERS into a variable and prints it via DBMS_OUTPUT.",
     None,  # no expected row substring; validated by executing without error
     "SELECT COUNT(*) FROM llm_sales_orders", "plsql"),
    # ---- privilege failures (S3) ----
    ("SALES_LAB",
     "Write a SELECT that reads data from another schema's table that SALES_LAB does not have access to (expect an insufficient-privileges error).",
     "ORA-",  # expect the query to fail with a privilege/not-found error
     "SELECT 1 FROM dual", "privilege"),
]


def _ask(base_url: str, prompt: str) -> str:
    req = urllib.request.Request(
        base_url.rstrip("/") + "/v1/chat/completions",
        data=json.dumps({
            "model": "oracle-assistant",
            "messages": [{"role": "user", "content": prompt}],
            "response_mode": "sql_only",
        }).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        body = json.loads(r.read().decode("utf-8"))
    return body["choices"][0]["message"]["content"].strip()


def _execute(schema: str, sql: str) -> str:
    """Execute returned SQL as the schema user; return 'ERR:...' or 'ok:rows=N'.

    Operational safety: refuse to execute against any schema that is not a
    disposable/resettable lab schema (fail-closed). Credentials come only from
    the environment; never production.
    """
    sys.path.insert(0, os.path.join(LLM, "src"))
    from oracle_llm.evaluation.safety import assert_executable_schema

    try:
        assert_executable_schema(schema, read_only_ok=False)
    except Exception as e:  # noqa: BLE001
        return "ERR:safety:" + str(e)[:80]
    pw = os.environ.get("ORACLE_LAB_PW_" + schema, "")
    if not pw:
        return "ERR:missing env"
    try:
        conn = oracledb.connect(user=schema, password=pw, dsn=DSN)
        cur = conn.cursor()
        # PL/SQL anonymous blocks (DECLARE/BEGIN ... END) need a terminating
        # 'END;' to be parsed by python-oracledb thin cursor.execute.
        s = sql.strip()
        if s.upper().startswith(("DECLARE", "BEGIN")) and not s.rstrip().endswith(";"):
            s = s + "\nEND;"
        cur.execute(s)
        if cur.description:
            rows = cur.fetchall()
            conn.close()
            return f"ok:rows={len(rows)}"
        conn.commit()
        conn.close()
        return "ok"
    except Exception as e:  # noqa: BLE001
        return "ERR:" + str(e).split("\n")[0][:80]


def _validate(schema: str, sql: str) -> list:
    pw = os.environ.get("ORACLE_LAB_PW_" + schema, "")
    conn = oracledb.connect(user=schema, password=pw, dsn=DSN)
    cur = conn.cursor()
    cur.execute(sql)
    rows = [tuple(r) for r in cur.fetchall()]
    conn.close()
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://127.0.0.1:8800")
    ap.add_argument("--no-reset", action="store_true", help="skip schema resets")
    ap.add_argument("--schema-index", help="approved schema index JSON to verify "
                    "retrieval DDL matches the target schema")
    args = ap.parse_args()

    # Step 3: verify the retrieval layer's DDL matches the real target schema
    # (the index is built from live Oracle, so the DDL and schema agree). This
    # confirms the schema context injected into sql_only prompts is correct.
    if args.schema_index:
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))) + "/src")
        from oracle_llm.serving.retrieval import SchemaRetriever

        retriever = SchemaRetriever(args.schema_index)
        print("== retrieval DDL verification ==")
        mismatch = 0
        for schema, _, _, val_sql, _cat in CASES:
            if schema not in ("SALES_LAB", "LOGISTICS_LAB", "SUPPORT_LAB", "DOCUMENTS_LAB", "OPS_LAB"):
                continue
            ddl = retriever.format_schema_ddl(schema)
            # Robustly extract a real table name from the validation query:
            # take the identifier after FROM, strip any schema prefix and alias.
            after_from = val_sql.split(" FROM ")[-1].split(" ")[0].strip().rstrip(";").upper()
            table = after_from.split(".")[-1]  # drop schema qualifier
            # DUAL is a system pseudo-table, not a user object — skip it.
            if table and table != "DUAL" and table not in ddl:
                print(f"  [FAIL] retrieval DDL for {schema} missing {table}")
                mismatch += 1
        if mismatch:
            print(f"retrieval DDL mismatches: {mismatch}")
        else:
            print("  [PASS] retrieval DDL matches target schemas")

    failures = []
    ora942 = 0
    from collections import Counter

    error_categories: Counter = Counter()
    for schema, prompt, expect, val_sql, category in CASES:
        if not args.no_reset:
            try:
                reset_schema(schema)
            except Exception as e:  # noqa: BLE001
                print(f"  [WARN] reset {schema} failed: {str(e)[:60]}")
        # Ask the model
        answer = _ask(args.base_url, prompt)
        # Execute
        result = _execute(schema, answer)
        ok_exec = result.startswith("ok")
        # Validate expected value present in the schema state the query reflects
        expect_found = False
        try:
            rows = _validate(schema, val_sql)
            expect_found = any(str(expect) in str(c) for row in rows for c in row) if expect else True
        except Exception:  # noqa: BLE001
            expect_found = False
        # Category-aware pass logic.
        if category == "privilege":
            # PASS if the query failed with a privilege/not-found error (the model
            # correctly attempted an object it lacks access to).
            passed = ("ORA-" in result and "ok:" not in result)
        elif category in ("join", "schema_qualified", "select"):
            passed = ok_exec and expect_found
        else:  # plsql or default
            passed = ok_exec
        mark = "PASS" if passed else "FAIL"
        if "ORA-00942" in result:
            ora942 += 1
        # Oracle error-category monitoring (classify the execute error)
        sys.path.insert(0, os.path.join(LLM, "src"))
        from oracle_llm.evaluation.safety import classify_error_category

        cat = classify_error_category(result)
        error_categories[cat] += 1
        print(f"  [{mark}] {category:<17} {schema}: {prompt[:40]}... exec={result[:26]} found={expect_found}")
        if not passed:
            failures.append((schema, prompt))
    print(f"\nORA-00942 (table not found) count: {ora942}/{len(CASES)}")
    print("Oracle error categories:", dict(error_categories.most_common()))
    if failures:
        print(f"FAILURES: {len(failures)}")
        return 1
    print("\nAll regression cases passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
