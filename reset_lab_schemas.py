"""Reset each lab schema to its known pristine seed state.

Restores the exact seeded rows (and resets sequences) that the
llm_lab_install.sql installer created, so every task starts from a known state.
Idempotent: safe to run repeatedly. Does NOT require SYSDBA — connects as each
lab user directly (the schema owner), so it can run from this shell over TCP.

Usage:
    python reset_lab_schemas.py                # reset all three lab schemas
    python reset_lab_schemas.py SALES_LAB      # reset one schema
    python reset_lab_schemas.py --verify       # reset then verify seed counts
"""
import os
import sys
import oracledb

DSN = "localhost:1521/FREEPDB1"

# (schema, user, password) — the lab schemas' own credentials.
# Passwords are read from environment variables (e.g. ORACLE_LAB_PW_SALES_LAB)
# so NO credentials are committed to the repository. Each var defaults to empty
# if unset; the caller must export them before running. This keeps the public
# educational repo free of secrets.
def _lab_pw(schema):
    env_key = "ORACLE_LAB_PW_%s" % schema
    pw = os.environ.get(env_key, "")
    return pw

LAB_SCHEMAS = {
    "SALES_LAB": ("SALES_LAB", "SALES_LAB"),      # password resolved at connect
    "DOCUMENTS_LAB": ("DOCUMENTS_LAB", "DOCUMENTS_LAB"),
    "OPS_LAB": ("OPS_LAB", "OPS_LAB"),
    "LOGISTICS_LAB": ("LOGISTICS_LAB", "LOGISTICS_LAB"),
    "SUPPORT_LAB": ("SUPPORT_LAB", "SUPPORT_LAB"),
}
# Resolve real passwords lazily so connect()/reset always pull the current env.
def _resolve(schema):
    user, _pwkey = LAB_SCHEMAS[schema]
    pw = _lab_pw(schema)
    if not pw:
        raise RuntimeError("Missing %s env var for schema %s" % (
            "ORACLE_LAB_PW_%s" % schema, schema))
    return user, pw

# Stable reference timestamp for audit/loaded/created timestamps that were set
# at install time (nothing filters on them, so a fixed value keeps resets equal).
REF_TS = "TO_TIMESTAMP('2026-01-01 00:00:00','YYYY-MM-DD HH24:MI:SS')"


def _reset_sales(cur):
    cur.execute("DELETE FROM llm_sales_orders")
    cur.execute("DELETE FROM llm_sales_regions")
    cur.execute("DELETE FROM llm_sales_load_errors")
    # regions
    cur.execute("INSERT INTO llm_sales_regions(region_id, region_name, manager_name) "
                "VALUES (1, 'North', 'Ava Chen')")
    cur.execute("INSERT INTO llm_sales_regions(region_id, region_name, manager_name) "
                "VALUES (2, 'South', 'Noah Singh')")
    # orders (explicit order_id to reproduce seeds)
    orders = [
        (100, "TO_DATE('2026-01-15','YYYY-MM-DD')", 1, "Orchid Retail", "WEB", 1250.5, '{"sku":"W-100","units":5}'),
        (101, "TO_DATE('2026-02-08','YYYY-MM-DD')", 2, "Summit Supply", "PARTNER", 9250.0, '{"sku":"P-200","units":25}'),
        (102, "TO_DATE('2026-02-19','YYYY-MM-DD')", 1, "Juniper Stores", "WEB", 3200.0, '{"sku":"W-101","units":8}'),
    ]
    for oid, d, rid, name, chan, amt, j in orders:
        cur.execute(
            "INSERT INTO llm_sales_orders(order_id, order_date, region_id, customer_name, "
            "channel, amount, order_json) VALUES (:1, " + d + ", :2, :3, :4, :5, :6)",
            [oid, rid, name, chan, amt, j])
    # reset sequences
    try: cur.execute("ALTER SEQUENCE llm_sales_order_seq RESTART START WITH 103")
    except Exception: pass
    try: cur.execute("ALTER SEQUENCE llm_sales_error_seq RESTART START WITH 1")
    except Exception: pass
    # refresh the materialized view so it reflects the restored seed orders
    try: cur.execute("BEGIN DBMS_MVIEW.REFRESH('LLM_SALES_REGION_MV'); END;")
    except Exception as e: print("    (mv refresh warn: %s)" % str(e)[:50])


def _reset_docs(cur):
    cur.execute("DELETE FROM llm_doc_invoice")
    cur.execute("DELETE FROM llm_doc_inbox")
    # inbox seed document
    payload = ('{"invoiceId":"ACME-001","supplier":"Acme Parts",'
               '"invoiceDate":"2026-02-14","total":4520.75,'
               '"attributes":{"currency":"USD","priority":"high"}}')
    cur.execute(
        "INSERT INTO llm_doc_inbox(document_id, source_file, received_at, payload, status, error_message) "
        "VALUES (1, 'acme-001.json', " + REF_TS + ", :1, 'PROCESSED', NULL)",
        [payload])
    # normalized invoice seed
    attrs = '{"currency":"USD","priority":"high"}'
    cur.execute(
        "INSERT INTO llm_doc_invoice(invoice_id, document_id, supplier, invoice_date, total, attributes) "
        "VALUES ('ACME-001', 1, 'Acme Parts', TO_DATE('2026-02-14','YYYY-MM-DD'), 4520.75, :1)",
        [attrs])
    try: cur.execute("ALTER SEQUENCE llm_doc_seq RESTART START WITH 2")
    except Exception: pass


def _reset_ops(cur):
    cur.execute("DELETE FROM llm_ops_event_log")
    cur.execute("DELETE FROM llm_ops_run_log")
    details = '{"status":"completed","rows":3}'
    cur.execute(
        "INSERT INTO llm_ops_event_log(event_id, event_type, details, created_at) "
        "VALUES (1, 'ORDER_LOAD', :1, " + REF_TS + ")",
        [details])
    try: cur.execute("ALTER SEQUENCE llm_ops_event_seq RESTART START WITH 2")
    except Exception: pass
    try: cur.execute("ALTER SEQUENCE llm_ops_run_seq RESTART START WITH 1")
    except Exception: pass


def _reset_logistics(cur):
    # Delete and re-seed the logistics tables.
    cur.execute("DELETE FROM llm_log_shipments")
    cur.execute("DELETE FROM llm_log_stock_movements")
    cur.execute("DELETE FROM llm_log_products")
    cur.execute("DELETE FROM llm_log_warehouses")
    cur.execute("INSERT INTO llm_log_products VALUES (1,'Widget',10,5.00)")
    cur.execute("INSERT INTO llm_log_products VALUES (2,'Gadget',15,8.50)")
    cur.execute("INSERT INTO llm_log_products VALUES (3,'Sprocket',5,12.00)")
    cur.execute("INSERT INTO llm_log_warehouses VALUES (1,'East DC','East')")
    cur.execute("INSERT INTO llm_log_warehouses VALUES (2,'West DC','West')")
    rows = [
        (1,1,1,100,'IN',"DATE '2026-01-05'"),
        (2,1,1,30,'OUT',"DATE '2026-01-12'"),
        (3,2,1,50,'IN',"DATE '2026-01-08'"),
        (4,1,2,40,'IN',"DATE '2026-01-10'"),
        (5,2,2,20,'OUT',"DATE '2026-01-15'"),
        (6,3,1,15,'IN',"DATE '2026-01-18'"),
        (7,1,2,10,'OUT',"DATE '2026-01-22'"),
        (8,3,2,5,'OUT',"DATE '2026-01-25'"),
    ]
    for mid,pid,wid,q,typ,d in rows:
        cur.execute(f"INSERT INTO llm_log_stock_movements VALUES ({mid},{pid},{wid},{q},'{typ}',{d})")
    shp = [
        (1,'ORD-100',1,20,"DATE '2026-01-02'","DATE '2026-01-07'","DATE '2026-01-07'",'DELIVERED'),
        (2,'ORD-101',2,10,"DATE '2026-01-03'","DATE '2026-01-09'","DATE '2026-01-11'",'DELIVERED'),
        (3,'ORD-102',3,8,"DATE '2026-01-05'","DATE '2026-01-12'","DATE '2026-01-12'",'DELIVERED'),
        (4,'ORD-103',1,15,"DATE '2026-01-10'","DATE '2026-01-16'",None,'IN_TRANSIT'),
        (5,'ORD-104',2,25,"DATE '2026-01-12'","DATE '2026-01-19'",None,'IN_TRANSIT'),
        (6,'ORD-105',1,5,"DATE '2026-01-15'","DATE '2026-01-20'",None,'PLANNED'),
    ]
    for sid,o,p,q,sd,ea,aa,st in shp:
        aa_sql = aa if aa else "NULL"
        cur.execute(f"INSERT INTO llm_log_shipments VALUES ({sid},'{o}',{p},{q},{sd},{ea},{aa_sql},'{st}')")


def _reset_support(cur):
    cur.execute("DELETE FROM llm_sup_errors")
    cur.execute("DELETE FROM llm_sup_tickets")
    cur.execute("DELETE FROM llm_sup_sla")
    cur.execute("DELETE FROM llm_sup_agents")
    cur.execute("INSERT INTO llm_sup_agents VALUES (1,'Alice','Tier1')")
    cur.execute("INSERT INTO llm_sup_agents VALUES (2,'Bob','Tier2')")
    cur.execute("INSERT INTO llm_sup_agents VALUES (3,'Carol','Tier3')")
    cur.execute("INSERT INTO llm_sup_sla VALUES ('HIGH',4)")
    cur.execute("INSERT INTO llm_sup_sla VALUES ('MEDIUM',24)")
    cur.execute("INSERT INTO llm_sup_sla VALUES ('LOW',72)")
    tickets = [
        (1,'Acme','Login failure','HIGH','RESOLVED',"DATE '2026-01-03'","DATE '2026-01-03'",1),
        (2,'Beta','Slow query','MEDIUM','RESOLVED',"DATE '2026-01-04'","DATE '2026-01-05'",2),
        (3,'Gamma','Data export broken','HIGH','RESOLVED',"DATE '2026-01-05'","DATE '2026-01-06'",1),
        (4,'Acme','Invoice missing','MEDIUM','OPEN',"DATE '2026-01-08'",None,3),
        (5,'Delta','Report error','LOW','OPEN',"DATE '2026-01-09'",None,2),
        (6,'Beta','API timeout','HIGH','RESOLVED',"DATE '2026-01-06'","DATE '2026-01-06'",2),
    ]
    for t,cust,subj,pri,st,cd,rd,a in tickets:
        rd_sql = rd if rd else "NULL"
        a_sql = str(a) if a else "NULL"
        cur.execute(f"INSERT INTO llm_sup_tickets VALUES ({t},'{cust}','{subj}','{pri}','{st}',{cd},{rd_sql},{a_sql})")
    errors = [
        (1,1,'ORA-01017','invalid credentials','TRIAGED'),
        (2,2,'ORA-00942','table does not exist','TRIAGED'),
        (3,3,'ORA-20001','business rule','INVESTIGATING'),
        (4,4,'ORA-01400','null insert','OPEN'),
        (5,6,'ORA-12170','timeout','TRIAGED'),
    ]
    for eid,t,code,msg,ts in errors:
        cur.execute(f"INSERT INTO llm_sup_errors VALUES ({eid},{t},'{code}','{msg}','{ts}')")


_RESETTERS = {
    "SALES_LAB": _reset_sales,
    "DOCUMENTS_LAB": _reset_docs,
    "OPS_LAB": _reset_ops,
    "LOGISTICS_LAB": _reset_logistics,
    "SUPPORT_LAB": _reset_support,
}


def reset_schema(schema):
    """Reset one lab schema to its pristine seed state. Returns True on success."""
    schema = schema.upper()
    if schema not in LAB_SCHEMAS:
        raise ValueError("Unknown lab schema: %s (have %s)" % (schema, list(LAB_SCHEMAS)))
    user, pw = _resolve(schema)
    conn = oracledb.connect(user=user, password=pw, dsn=DSN)
    try:
        cur = conn.cursor()
        _RESETTERS[schema](cur)
        conn.commit()
        return True
    finally:
        conn.close()


def reset_all():
    for s in LAB_SCHEMAS:
        reset_schema(s)
        print("reset %s" % s)


def verify(schema=None):
    """Return a dict schema -> table count after reset."""
    targets = [schema.upper()] if schema else list(LAB_SCHEMAS)
    out = {}
    for s in targets:
        user, pw = _resolve(s)
        c = oracledb.connect(user=user, password=pw, dsn=DSN)
        cur = c.cursor()
        counts = {}
        for t in ("llm_sales_orders", "llm_sales_regions", "llm_sales_load_errors",
                  "llm_doc_invoice", "llm_doc_inbox", "llm_ops_event_log", "llm_ops_run_log",
                  "llm_log_shipments", "llm_log_stock_movements", "llm_log_products",
                  "llm_log_warehouses", "llm_sup_tickets", "llm_sup_errors",
                  "llm_sup_sla", "llm_sup_agents"):
            try:
                cur.execute("SELECT COUNT(*) FROM %s" % t)
                counts[t] = cur.fetchone()[0]
            except Exception:
                pass
        out[s] = counts
        c.close()
    return out


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if "--verify" in sys.argv:
        reset_all()
        for s, counts in verify().items():
            print("verify %s: %s" % (s, counts))
    elif args:
        reset_schema(args[0])
        print("reset %s" % args[0].upper())
    else:
        reset_all()
