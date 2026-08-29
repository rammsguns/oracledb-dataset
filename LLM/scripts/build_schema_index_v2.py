#!/usr/bin/env python3
"""Enriched schema-metadata index (v2) — tables + columns + PK/FK/unique/check
constraints + views + concise table descriptions.

Builds the approved, versioned schema-metadata index used by the retrieval
layer. Reads the live Oracle lab schemas (env-var credentials) and emits a
versioned index:
    {
      "version": "v2",
      "generated": "<iso>",
      "schemas": {
        "SALES_LAB": {
          "tables": { "LLM_SALES_ORDERS": {
              "columns": [[name,type],...],
              "pk": [cols],
              "unique": [cols],
              "fk": [{col, references: {table, columns}}],
              "check": ["CONDITION",...],
              "description": "concise table description"
          }},
          "views": { "LLM_SALES_REGION_MV": "comment" },
          "sequences": ["LLM_SALES_ORDER_SEQ", ...]
        }
      }
    }

Only metadata is emitted — no row data, no secrets. Metadata-only and
versioned so the retrieval layer (and any downstream consumer) can pin to a
specific version.

Usage: python scripts/build_schema_index_v2.py [out_path]
"""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import oracledb

DSN = "localhost:1521/FREEPDB1"
LAB = ["SALES_LAB", "DOCUMENTS_LAB", "OPS_LAB", "LOGISTICS_LAB", "SUPPORT_LAB"]

# Concise table descriptions (human-authored, metadata-only). These help the
# model map a business request to the right object. Never include data/secrets.
DESCRIPTIONS = {
    "SALES_LAB.LLM_SALES_ORDERS": "Sales orders: one row per order with customer, channel, amount.",
    "SALES_LAB.LLM_SALES_REGIONS": "Sales regions and their managers.",
    "SALES_LAB.LLM_SALES_LOAD_ERRORS": "Log of sales data load errors (source + message).",
    "SALES_LAB.LLM_SALES_REGION_MV": "Materialized view: order count and revenue per region.",
    "DOCUMENTS_LAB.LLM_DOC_INBOX": "Incoming document JSON payloads waiting for processing.",
    "DOCUMENTS_LAB.LLM_DOC_INVOICE": "Normalized invoice records extracted from inbox documents.",
    "OPS_LAB.LLM_OPS_EVENT_LOG": "Operational events (e.g. ORDER_LOAD) with JSON details.",
    "OPS_LAB.LLM_OPS_RUN_LOG": "Scheduled job runs and their status/timing.",
    "LOGISTICS_LAB.LLM_LOG_PRODUCTS": "Products with reorder level and unit cost.",
    "LOGISTICS_LAB.LLM_LOG_WAREHOUSES": "Warehouses and their regions.",
    "LOGISTICS_LAB.LLM_LOG_STOCK_MOVEMENTS": "Stock in/out movements per product/warehouse.",
    "LOGISTICS_LAB.LLM_LOG_SHIPMENTS": "Shipments with dates and delivery status.",
    "SUPPORT_LAB.LLM_SUP_AGENTS": "Support agents and their team.",
    "SUPPORT_LAB.LLM_SUP_TICKETS": "Support tickets with priority/status and assigned agent.",
    "SUPPORT_LAB.LLM_SUP_SLA": "SLA target hours per priority.",
    "SUPPORT_LAB.LLM_SUP_ERRORS": "Errors associated with support tickets (ORA codes).",
}


def _dump_schema(conn) -> dict:
    cur = conn.cursor()
    tables = {}
    cur.execute(
        "SELECT table_name FROM user_tables WHERE table_name NOT LIKE 'BIN$%' ORDER BY table_name")
    for (tbl,) in cur.fetchall():
        cur.execute(
            "SELECT column_name, data_type || CASE WHEN data_precision IS NOT NULL "
            "THEN '('||data_precision||CASE WHEN data_scale>0 THEN ','||data_scale END||')' "
            "ELSE '' END "
            "FROM user_tab_columns WHERE table_name=:1 ORDER BY column_id", [tbl])
        cols = [(r[0], r[1]) for r in cur.fetchall()]
        # primary key
        cur.execute(
            "SELECT cols.column_name FROM user_constraints c "
            "JOIN user_cons_columns cols ON c.constraint_name=cols.constraint_name "
            "WHERE c.table_name=:1 AND c.constraint_type='P' ORDER BY cols.position", [tbl])
        pk = [r[0] for r in cur.fetchall()]
        # unique
        cur.execute(
            "SELECT cols.column_name FROM user_constraints c "
            "JOIN user_cons_columns cols ON c.constraint_name=cols.constraint_name "
            "WHERE c.table_name=:1 AND c.constraint_type='U' ORDER BY cols.position", [tbl])
        uniq = [r[0] for r in cur.fetchall()]
        # foreign keys
        cur.execute(
            "SELECT c.constraint_name, cols.column_name, c.r_constraint_name "
            "FROM user_constraints c "
            "JOIN user_cons_columns cols ON c.constraint_name=cols.constraint_name "
            "WHERE c.table_name=:1 AND c.constraint_type='R' AND cols.position=1", [tbl])
        fk_rows = cur.fetchall()
        fk = []
        for cname, col, rname in fk_rows:
            cur.execute(
                "SELECT table_name FROM user_constraints WHERE constraint_name=:1", [rname])
            rtab = cur.fetchone()
            rtbl = rtab[0] if rtab else None
            if rtbl:
                cur.execute(
                    "SELECT column_name FROM user_cons_columns WHERE constraint_name=:1 "
                    "ORDER BY position", [rname])
                fk.append({"column": col, "references": {"table": rtbl,
                                                          "columns": [r[0] for r in cur.fetchall()]}})
        # check constraints
        cur.execute(
            "SELECT search_condition FROM user_constraints "
            "WHERE table_name=:1 AND constraint_type='C' AND search_condition IS NOT NULL", [tbl])
        checks = [r[0] for r in cur.fetchall()]
        tables[tbl] = {
            "columns": cols,
            "pk": pk,
            "unique": uniq,
            "fk": fk,
            "check": checks,
        }
    return tables


def _dump_views(conn) -> dict:
    cur = conn.cursor()
    views = {}
    cur.execute(
        "SELECT view_name FROM user_views WHERE view_name NOT LIKE 'BIN$%' ORDER BY view_name")
    for (v,) in cur.fetchall():
        views[v] = ""  # description filled from DESCRIPTIONS if present
    return views


def _dump_sequences(conn) -> list:
    """Sequence names so the model can use NEXTVAL/CURRVAL correctly.

    Sequences are metadata-only (name). Included because generated PKs rely on
    them; without the names the model invents one and hits ORA-02289 (sequence
    does not exist). This is a non-model, non-ranked retrieval improvement.
    """
    cur = conn.cursor()
    cur.execute(
        "SELECT sequence_name FROM user_sequences "
        "WHERE sequence_name NOT LIKE 'BIN$%' ORDER BY sequence_name")
    return [r[0] for r in cur.fetchall()]


def main() -> None:
    out = sys.argv[1] if len(sys.argv) > 1 else str(
        Path(__file__).resolve().parent.parent / "artifacts" / "schema_index_v2.json")
    index = {"version": "v2", "generated": datetime.now(timezone.utc).isoformat(), "schemas": {}}
    for schema in LAB:
        pw = os.environ.get("ORACLE_LAB_PW_" + schema, "")
        if not pw:
            print(f"{schema}: MISSING ENV", file=sys.stderr)
            continue
        conn = oracledb.connect(user=schema, password=pw, dsn=DSN)
        tables = _dump_schema(conn)
        # attach descriptions
        for t in tables:
            tables[t]["description"] = DESCRIPTIONS.get(f"{schema}.{t}", "")
        index["schemas"][schema] = {"tables": tables, "views": _dump_views(conn),
                                    "sequences": _dump_sequences(conn)}
        conn.close()
        print(f"{schema}: {len(tables)} tables, {len(index['schemas'][schema]['views'])} views")
    out_path = Path(out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(index, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote enriched schema index (v2) -> {out_path}")


if __name__ == "__main__":
    main()
