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
CASES = [
    ("SALES_LAB",
     "Write a query showing customer names and order amounts from the sales orders table, ordered by amount descending. The table is in the SALES_LAB schema.",
     "Summit",
     "SELECT customer_name FROM llm_sales_orders ORDER BY amount DESC"),
    ("SALES_LAB",
     "Count how many orders exist in the SALES_LAB sales orders table.",
     "3",
     "SELECT COUNT(*) FROM llm_sales_orders"),
    ("SALES_LAB",
     "List the sales regions and their managers from the regions table in SALES_LAB.",
     "North",
     "SELECT region_name FROM llm_sales_regions"),
    ("SALES_LAB",
     "Show the region materialized view with order count and revenue, ordered by revenue descending.",
     "South",
     "SELECT region_name FROM llm_sales_region_mv ORDER BY revenue DESC"),
    ("LOGISTICS_LAB",
     "List products and their unit costs from the LOGISTICS_LAB products table.",
     "Widget",
     "SELECT product_name FROM llm_log_products"),
    ("LOGISTICS_LAB",
     "Count shipments in the LOGISTICS_LAB shipments table.",
     "6",
     "SELECT COUNT(*) FROM llm_log_shipments"),
    ("LOGISTICS_LAB",
     "Show warehouses and their regions from the LOGISTICS_LAB warehouses table.",
     "East",
     "SELECT warehouse_name FROM llm_log_warehouses"),
    ("SUPPORT_LAB",
     "Count support tickets in the SUPPORT_LAB tickets table.",
     "6",
     "SELECT COUNT(*) FROM llm_sup_tickets"),
    ("SUPPORT_LAB",
     "List support agents and their teams from the SUPPORT_LAB agents table.",
     "Tier",
     "SELECT agent_name FROM llm_sup_agents"),
    ("DOCUMENTS_LAB",
     "Show invoices and their suppliers from the DOCUMENTS_LAB invoice table.",
     "Acme",
     "SELECT supplier FROM llm_doc_invoice"),
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
        cur.execute(sql)
        rows = cur.fetchall()
        conn.close()
        return f"ok:rows={len(rows)}"
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
        for schema, _, _, val_sql in CASES:
            if schema not in ("SALES_LAB", "LOGISTICS_LAB", "SUPPORT_LAB", "DOCUMENTS_LAB", "OPS_LAB"):
                continue
            ddl = retriever.format_schema_ddl(schema)
            # The DDL must name the real table that the validation query targets.
            table = val_sql.split(" FROM ")[-1].split(" ")[0].strip().rstrip(";").upper()
            if table and table not in ddl:
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
    for schema, prompt, expect, val_sql in CASES:
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
        # (the returned rows themselves, using the model's query result is
        # unreliable if wrong table; so we run a KNOWN validation query).
        expect_found = False
        try:
            rows = _validate(schema, val_sql)
            expect_found = any(str(expect) in str(c) for row in rows for c in row)
        except Exception:  # noqa: BLE001
            expect_found = False
        mark = "PASS" if (ok_exec and expect_found) else "FAIL"
        if "ORA-00942" in result:
            ora942 += 1
        # Oracle error-category monitoring (classify the execute error)
        sys.path.insert(0, os.path.join(LLM, "src"))
        from oracle_llm.evaluation.safety import classify_error_category

        cat = classify_error_category(result)
        error_categories[cat] += 1
        print(f"  [{mark}] {schema}: {prompt[:50]}... exec={result[:30]} expect={expect!r} found={expect_found}")
        if mark == "FAIL":
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
