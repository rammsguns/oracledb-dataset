#!/usr/bin/env python3
"""Author + validate a schema-grounded challenger training supplement (Step 5).

Target: ORA-00942 (model invents generic table names). Fix: teach the exact
object names per lab schema AND give the model the real table DDL in the
prompt, so it learns schema-name -> object-name mapping.

Method: for each lab schema, author a set of production-style requests, each
with the real CREATE TABLE DDL in the `input` (like the grounded dataset
records), and a verified answer query using the real object names. Every
answer is validated against live Oracle (must execute + return expected seed
value) before the record is kept.

Output: a new versioned training-only file
    ../oracle_train_schema_grounded.jsonl
(separate from the frozen set and the earlier 22-record schema-aware file).
"""
import json
import os
import sys
from pathlib import Path

import oracledb

LLM = Path(__file__).resolve().parent.parent
DSN = "localhost:1521/FREEPDB1"
OUT = LLM.parent / "oracle_train_schema_grounded.jsonl"

# Per-schema: (table, ddl, seed_check_query, expected_substring)
# The DDL is the REAL object name; seed_check confirms the real table has data.
SCHEMAS = {
    "SALES_LAB": [
        ("llm_sales_orders",
         "CREATE TABLE llm_sales_orders (order_id NUMBER PRIMARY KEY, order_date DATE, "
         "region_id NUMBER, customer_name VARCHAR2(60), channel VARCHAR2(10), "
         "amount NUMBER(12,2), order_json CLOB)",
         "SELECT customer_name FROM llm_sales_orders", "Summit"),
        ("llm_sales_regions",
         "CREATE TABLE llm_sales_regions (region_id NUMBER PRIMARY KEY, region_name VARCHAR2(20), "
         "manager_name VARCHAR2(40))",
         "SELECT region_name FROM llm_sales_regions", "North"),
        ("llm_sales_region_mv",
         "CREATE MATERIALIZED VIEW llm_sales_region_mv (region_name, order_count, revenue) "
         "AS SELECT r.region_name, COUNT(o.order_id), SUM(o.amount) "
         "FROM llm_sales_regions r LEFT JOIN llm_sales_orders o ON r.region_id=o.region_id "
         "GROUP BY r.region_name",
         "SELECT region_name FROM llm_sales_region_mv", "North"),
    ],
    "DOCUMENTS_LAB": [
        ("llm_doc_invoice",
         "CREATE TABLE llm_doc_invoice (invoice_id VARCHAR2(30) PRIMARY KEY, document_id NUMBER, "
         "supplier VARCHAR2(60), invoice_date DATE, total NUMBER(12,2), attributes CLOB)",
         "SELECT supplier FROM llm_doc_invoice", "Acme"),
    ],
    "OPS_LAB": [
        ("llm_ops_event_log",
         "CREATE TABLE llm_ops_event_log (event_id NUMBER PRIMARY KEY, event_type VARCHAR2(30), "
         "details CLOB, created_at TIMESTAMP)",
         "SELECT event_type FROM llm_ops_event_log", "ORDER_LOAD"),
    ],
    "LOGISTICS_LAB": [
        ("llm_log_products",
         "CREATE TABLE llm_log_products (product_id NUMBER PRIMARY KEY, product_name VARCHAR2(40), "
         "reorder_level NUMBER, unit_cost NUMBER(10,2))",
         "SELECT product_name FROM llm_log_products", "Widget"),
        ("llm_log_warehouses",
         "CREATE TABLE llm_log_warehouses (warehouse_id NUMBER PRIMARY KEY, warehouse_name VARCHAR2(40), "
         "region VARCHAR2(20))",
         "SELECT warehouse_name FROM llm_log_warehouses", "East"),
    ],
    "SUPPORT_LAB": [
        ("llm_sup_tickets",
         "CREATE TABLE llm_sup_tickets (ticket_id NUMBER PRIMARY KEY, customer_name VARCHAR2(60), "
         "subject VARCHAR2(80), priority VARCHAR2(10), status VARCHAR2(12), created_at DATE, "
         "resolved_at DATE, agent_id NUMBER)",
         "SELECT customer_name FROM llm_sup_tickets", "Acme"),
        ("llm_sup_agents",
         "CREATE TABLE llm_sup_agents (agent_id NUMBER PRIMARY KEY, agent_name VARCHAR2(40), "
         "team VARCHAR2(10))",
         "SELECT team FROM llm_sup_agents", "Tier"),
    ],
}

# Per (schema, table): list of (instruction, answer_query, expected_substring)
# Production-style requests; answers use real object names.
QUERIES = {
    ("SALES_LAB", "llm_sales_orders"): [
        ("List the order id, customer, and amount of each sales order, ordered by amount descending.",
         "SELECT order_id, customer_name, amount FROM llm_sales_orders ORDER BY amount DESC", "Summit"),
        ("Count the number of sales orders.",
         "SELECT COUNT(*) FROM llm_sales_orders", "3"),
        ("Show the highest sales order amount.",
         "SELECT MAX(amount) FROM llm_sales_orders", "9250"),
    ],
    ("SALES_LAB", "llm_sales_regions"): [
        ("List the sales regions and their managers.",
         "SELECT region_name, manager_name FROM llm_sales_regions", "North"),
    ],
    ("SALES_LAB", "llm_sales_region_mv"): [
        ("Show the order count and revenue per region, ordered by revenue.",
         "SELECT region_name, order_count, revenue FROM llm_sales_region_mv ORDER BY revenue DESC", "South"),
    ],
    ("DOCUMENTS_LAB", "llm_doc_invoice"): [
        ("List invoice id, supplier, and total from the invoices table.",
         "SELECT invoice_id, supplier, total FROM llm_doc_invoice", "Acme"),
        ("Show the total value of all invoices.",
         "SELECT SUM(total) FROM llm_doc_invoice", "4520"),
    ],
    ("OPS_LAB", "llm_ops_event_log"): [
        ("Show the most recent event types in the event log.",
         "SELECT event_type, details FROM llm_ops_event_log", "ORDER_LOAD"),
    ],
    ("LOGISTICS_LAB", "llm_log_products"): [
        ("List the products and their unit cost.",
         "SELECT product_name, unit_cost FROM llm_log_products", "Widget"),
    ],
    ("LOGISTICS_LAB", "llm_log_warehouses"): [
        ("List the warehouses and their regions.",
         "SELECT warehouse_name, region FROM llm_log_warehouses", "East"),
    ],
    ("SUPPORT_LAB", "llm_sup_tickets"): [
        ("Count the support tickets.",
         "SELECT COUNT(*) FROM llm_sup_tickets", "6"),
        ("List open support tickets with their priority.",
         "SELECT ticket_id, customer_name, priority FROM llm_sup_tickets WHERE status = 'OPEN'", "Acme"),
    ],
    ("SUPPORT_LAB", "llm_sup_agents"): [
        ("List the support agents and their teams.",
         "SELECT agent_name, team FROM llm_sup_agents", "Alice"),
    ],
}


def _check(schema: str, sql: str, expect: str) -> bool:
    pw = os.environ.get("ORACLE_LAB_PW_" + schema, "")
    if not pw:
        return False
    try:
        conn = oracledb.connect(user=schema, password=pw, dsn=DSN)
        cur = conn.cursor()
        cur.execute(sql)
        rows = cur.fetchall()
        conn.close()
        if not rows:
            return False
        hay = " | ".join(str(c) for row in rows for c in row)
        return expect in hay
    except Exception:  # noqa: BLE001
        return False


def main() -> int:
    # Pre-validate every seed/answer query against live Oracle.
    records = []
    for schema, tables in SCHEMAS.items():
        for table, ddl, seed_q, seed_expect in tables:
            # Verify the real table + seed
            if not _check(schema, seed_q, seed_expect):
                print(f"  [FAIL seed] {schema}.{table}", file=sys.stderr)
                continue
            for (instruction, answer, expect) in QUERIES.get((schema, table), []):
                if not _check(schema, answer, expect):
                    print(f"  [FAIL] {schema}.{table}: {instruction[:50]} -> no {expect!r}", file=sys.stderr)
                    continue
                records.append({
                    "instruction": instruction,
                    # Grounded: include real DDL so the model learns the mapping.
                    "input": f"Schema: {schema}.\n{ddl}",
                    "output": answer + ";",
                    "difficulty": "easy",
                    "schema": schema,
                })
                print(f"  [ok] {schema}.{table}: {instruction[:40]}...")

    Path(OUT).write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8"
    )
    print(f"\nvalidated {len(records)} records -> {OUT}")
    return 0 if records else 1


if __name__ == "__main__":
    sys.exit(main())
