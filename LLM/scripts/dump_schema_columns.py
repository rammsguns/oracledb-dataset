#!/usr/bin/env python3
"""Dump each lab schema's tables + columns (for authoring schema-aware examples).

Reads the live Oracle lab schemas (env-var credentials) and prints
schema -> {table: [columns]}. Used to author grounded training examples that
teach the model the real object names. Read-only.
"""
import os
import sys
import oracledb

DSN = "localhost:1521/FREEPDB1"
LAB = ["SALES_LAB", "DOCUMENTS_LAB", "OPS_LAB", "LOGISTICS_LAB", "SUPPORT_LAB"]


def main() -> None:
    for schema in LAB:
        pw = os.environ.get("ORACLE_LAB_PW_" + schema, "")
        if not pw:
            print(f"{schema}: MISSING ENV", file=sys.stderr)
            continue
        conn = oracledb.connect(user=schema, password=pw, dsn=DSN)
        cur = conn.cursor()
        print(f"\n== {schema} ==")
        cur.execute(
            "SELECT table_name FROM user_tables WHERE table_name NOT LIKE 'BIN$%' "
            "ORDER BY table_name"
        )
        for (tbl,) in cur.fetchall():
            cur.execute(
                "SELECT column_name FROM user_tab_columns WHERE table_name=:1 "
                "ORDER BY column_id",
                [tbl],
            )
            cols = [r[0] for r in cur.fetchall()]
            print(f"  {tbl}: {', '.join(cols)}")
        conn.close()


if __name__ == "__main__":
    main()
