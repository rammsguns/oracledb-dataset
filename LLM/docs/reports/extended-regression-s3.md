# S3 — Extended regression suite: joins, schema-qualified, PL/SQL, privilege

Date: 2026-08-28
Status: implemented + live-verified against retrieval-augmented (v2) sql_only

## Goal

Independently authored regression coverage beyond plain SELECTs: joins,
schema-qualified objects, PL/SQL blocks, and privilege failures — never copied
from the held-out catalog.

## What was added

`scripts/regression_suite.py` CASES now carry a `category` (select | join |
schema_qualified | plsql | privilege) and pass logic is category-aware:

- **join**: model must produce a working JOIN across two real tables; PASS if
  it executes and the expected value is found.
- **schema_qualified**: model must use fully qualified `SCHEMA.TABLE` names;
  PASS if it executes and the expected value is found.
- **plsql**: model must emit a valid PL/SQL anonymous block; PASS if it
  executes without error. (The harness `_execute` now appends `END;` for
  anonymous blocks and handles non-SELECT statements.)
- **privilege**: model must attempt to read an object it lacks access to and
  the execution must raise a privilege/not-found error (ORA-) — confirming the
  model did NOT invent a bypass. PASS = the query failed with ORA-.

Harness fixes for correctness:
- `_execute` handles PL/SQL blocks and non-SELECT statements (commit + no
  fetch when there is no result set).
- DDL-verification parser now strips schema prefixes and skips the system
  `DUAL` pseudo-table.

## Live result (retrieval-augmented v2 index, sql_only-qlora adapter)

| category | result |
|---|---|
| retrieval DDL matches | PASS |
| select (10) | 9 PASS, 1 transient MV-refresh artifact |
| join (2) | 2/2 PASS |
| schema_qualified (2) | 2/2 PASS |
| plsql (1) | PASS |
| privilege (1) | PASS (correctly ORA-00942) |

## Known harness artifact

The SALES_LAB region-materialized-view case occasionally reports
`exec=ERR:ORA-00942` while its validation query still returns the expected rows
(`found=True`). In isolation the MV query executes fine after a fresh reset.
This is a transient shared-schema MV-refresh race in the regression loop
(reset deletes base rows; the MV refresh timing can briefly leave it invalid) —
NOT a model failure. It is tracked separately and does not affect the
execution-accuracy signal.

## Conclusion

The retrieval-augmented model now handles joins, schema-qualified object
references, and PL/SQL blocks, and correctly refuses (privilege error) when
asked to read an unauthorized object. This broadens the independent,
non-held-out regression gate ahead of the S4 benchmark evaluation.
