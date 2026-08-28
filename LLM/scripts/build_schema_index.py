#!/usr/bin/env python3
"""Dump each lab schema's DDL (tables + columns + key constraints) to JSON.

Builds the approved schema-metadata index used by the retrieval layer. Reads
the live Oracle lab schemas (env-var credentials) and emits:
    {schema: {table: {columns: [(name, type)], pk: [cols], fk: [...], unique: [...]}}}

Only metadata is emitted — no row data, no secrets. Used by
oracle_llm/serving/retrieval.py to inject schema context into SQL-only prompts.

Output: artifacts/schema_index.json (gitignored) or --out <path>.
"""
import json
import os
import sys
from pathlib import Path

import oracledb

DSN = "localhost:1521/FREEPDB1"
LAB = ["SALES_LAB", "DOCUMENTS_LAB", "OPS_LAB", "LOGISTICS_LAB", "SUPPORT_LAB"]


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
        # primary key columns
        cur.execute(
            "SELECT cols.column_name FROM user_constraints c "
            "JOIN user_cons_columns cols ON c.constraint_name=cols.constraint_name "
            "WHERE c.table_name=:1 AND c.constraint_type='P' ORDER BY cols.position", [tbl])
        pk = [r[0] for r in cur.fetchall()]
        # unique constraint columns
        cur.execute(
            "SELECT cols.column_name FROM user_constraints c "
            "JOIN user_cons_columns cols ON c.constraint_name=cols.constraint_name "
            "WHERE c.table_name=:1 AND c.constraint_type='U' ORDER BY cols.position", [tbl])
        uniq = [r[0] for r in cur.fetchall()]
        tables[tbl] = {"columns": cols, "pk": pk, "unique": uniq}
    return tables


def main() -> None:
    out = sys.argv[1] if len(sys.argv) > 1 else str(
        Path(__file__).resolve().parent.parent / "artifacts" / "schema_index.json")
    index = {}
    for schema in LAB:
        pw = os.environ.get("ORACLE_LAB_PW_" + schema, "")
        if not pw:
            print(f"{schema}: MISSING ENV", file=sys.stderr)
            continue
        conn = oracledb.connect(user=schema, password=pw, dsn=DSN)
        index[schema] = _dump_schema(conn)
        conn.close()
        print(f"{schema}: {len(index[schema])} tables")
    out_path = Path(out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(index, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote schema index -> {out_path}")


if __name__ == "__main__":
    main()
