#!/usr/bin/env python3
"""Author + validate a schema-awareness training supplement (P4 focused fix).

Root cause from the failure taxonomy: 81/126 failures are ORA-00942 — the
model emits generic/wrong object names instead of the real lab-schema tables
and columns. This script builds a small, grounded code_only training file that
teaches the actual object names per schema, and validates EVERY example against
live Oracle (runs the query as the schema user, requires it to execute and
return at least one row).

Output: ../oracle_train_schema_aware.jsonl (a NEW versioned training-only file,
separate from the frozen set, with its own manifest).
"""
import json
import os
import sys
from pathlib import Path

import oracledb

LLM = Path(__file__).resolve().parent.parent
DSN = "localhost:1521/FREEPDB1"
OUT = LLM.parent / "oracle_train_schema_aware.jsonl"

# (schema, prompt, query, expected_first_cell_contains)
# Each prompt asks for a query against the named schema; each query uses the
# REAL table/column names and must execute + return >=1 row on live Oracle.
EXAMPLES = [
    # ---- SALES_LAB ----
    ("SALES_LAB", "Show all columns of the orders table in the SALES_LAB schema.",
     "SELECT order_id, order_date, region_id, customer_name, channel, amount, order_json FROM llm_sales_orders", "Summit"),
    ("SALES_LAB", "List customer names and amounts from the SALES_LAB orders table, ordered by amount descending.",
     "SELECT customer_name, amount FROM llm_sales_orders ORDER BY amount DESC", "Summit"),
    ("SALES_LAB", "Count the number of orders in SALES_LAB.",
     "SELECT COUNT(*) FROM llm_sales_orders", None),
    ("SALES_LAB", "Show regions and their managers in SALES_LAB.",
     "SELECT region_name, manager_name FROM llm_sales_regions", "North"),
    ("SALES_LAB", "Show order count and revenue per region from the SALES_LAB region materialized view.",
     "SELECT region_name, order_count, revenue FROM llm_sales_region_mv", "North"),
    ("SALES_LAB", "Show the error log table structure in SALES_LAB (which columns does the load-errors table have?).",
     "SELECT COUNT(*) FROM llm_sales_load_errors", None),
    # ---- DOCUMENTS_LAB ----
    ("DOCUMENTS_LAB", "Show invoices and their suppliers in the DOCUMENTS_LAB schema.",
     "SELECT invoice_id, supplier, total FROM llm_doc_invoice", "Acme"),
    ("DOCUMENTS_LAB", "Count documents in the DOCUMENTS_LAB inbox.",
     "SELECT COUNT(*) FROM llm_doc_inbox", None),
    ("DOCUMENTS_LAB", "Show the inbox document payloads in DOCUMENTS_LAB.",
     "SELECT document_id, source_file, status FROM llm_doc_inbox", "acme"),
    # ---- OPS_LAB ----
    ("OPS_LAB", "Show recent event log entries in the OPS_LAB schema.",
     "SELECT event_id, event_type, details FROM llm_ops_event_log", "ORDER_LOAD"),
    ("OPS_LAB", "Count run log entries in OPS_LAB.",
     "SELECT COUNT(*) FROM llm_ops_run_log", None),
    ("OPS_LAB", "Show the run log table structure in OPS_LAB (which columns does the run log have?).",
     "SELECT COUNT(*) FROM llm_ops_run_log", None),
    # ---- LOGISTICS_LAB ----
    ("LOGISTICS_LAB", "Show products and their unit cost in the LOGISTICS_LAB schema.",
     "SELECT product_name, unit_cost FROM llm_log_products", "Widget"),
    ("LOGISTICS_LAB", "Count shipments in LOGISTICS_LAB.",
     "SELECT COUNT(*) FROM llm_log_shipments", None),
    ("LOGISTICS_LAB", "Show stock movements in LOGISTICS_LAB.",
     "SELECT movement_id, product_id, qty, movement_type FROM llm_log_stock_movements", None),
    ("LOGISTICS_LAB", "Show warehouses in LOGISTICS_LAB.",
     "SELECT warehouse_name, region FROM llm_log_warehouses", "East"),
    ("LOGISTICS_LAB", "Show shipments and their status in LOGISTICS_LAB.",
     "SELECT order_ref, product_id, qty, status FROM llm_log_shipments", "ORD"),
    # ---- SUPPORT_LAB ----
    ("SUPPORT_LAB", "Show open support tickets in the SUPPORT_LAB schema.",
     "SELECT ticket_id, customer_name, subject, priority FROM llm_sup_tickets", None),
    ("SUPPORT_LAB", "Count support tickets in SUPPORT_LAB.",
     "SELECT COUNT(*) FROM llm_sup_tickets", None),
    ("SUPPORT_LAB", "Show support agents and their teams in SUPPORT_LAB.",
     "SELECT agent_name, team FROM llm_sup_agents", "Tier"),
    ("SUPPORT_LAB", "Show error codes logged in SUPPORT_LAB.",
     "SELECT error_code, error_message FROM llm_sup_errors", "ORA"),
    ("SUPPORT_LAB", "Show the SLA targets in SUPPORT_LAB.",
     "SELECT priority, target_hours FROM llm_sup_sla", "HIGH"),
]


def main() -> None:
    records = []
    failures = 0
    for schema, instruction, query, contains in EXAMPLES:
        pw = os.environ.get("ORACLE_LAB_PW_" + schema, "")
        if not pw:
            print(f"  [skip] {schema}: missing env", file=sys.stderr)
            failures += 1
            continue
        try:
            conn = oracledb.connect(user=schema, password=pw, dsn=DSN)
            cur = conn.cursor()
            cur.execute(query)
            rows = cur.fetchall()
            conn.close()
        except Exception as e:  # noqa: BLE001
            print(f"  [FAIL] {schema}: {query[:60]}... -> {str(e)[:80]}", file=sys.stderr)
            failures += 1
            continue
        if not rows:
            print(f"  [FAIL] {schema}: {query[:60]}... returned 0 rows", file=sys.stderr)
            failures += 1
            continue
        if contains is not None:
            hay = " | ".join(str(c) for row in rows for c in row)
            if contains not in hay:
                print(f"  [FAIL] {schema}: {query[:60]}... missing {contains!r}", file=sys.stderr)
                failures += 1
                continue
        records.append({
            "instruction": instruction,
            "input": f"Schema: {schema}. Use the exact table and column names in this schema.",
            "output": query + ";",
            "difficulty": "easy",
            "schema": schema,
        })
        print(f"  [ok] {schema}: {query[:50]}... ({len(rows)} rows)")

    Path(OUT).write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8"
    )
    print(f"\nvalidated {len(records)}/{len(EXAMPLES)} records -> {OUT}")
    print(f"failures: {failures}")
    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
