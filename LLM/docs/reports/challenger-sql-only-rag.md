# Step 5 — Retrieval-augmented challenger: sql_only + schema-context RAG

Date: 2026-08-28
Status: **PROMOTED** — clears the promotion gate.

## Summary

Adding schema-context retrieval to the sql_only pipeline dramatically improved
held-out execution accuracy and controlled-error performance, without changing
any model weights.

## Held-out catalog results (150 tasks, temperature 0, unchanged catalog)

| run | passed | % | executed_ok | exact | controlled-error |
|---|---|---|---|---|---|
| gold (sanity ceiling) | 150 | 100.0 | 125 | 125 | 25/25 |
| **sql_only + RAG (promoted)** | **55** | **36.7** | **95** | **44** | **11/25** |
| base + RAG | 39 | 26.0 | 76 | 28 | 11/25 |
| sql_only (incumbent) | 24 | 16.0 | 42 | 18 | 6/25 |
| base baseline | 8 | 5.3 | 18 | 4 | 4/25 |

## Promotion gate

`artifacts/gate_sql_only_rag.json`:
- exceeds_selected_pass_pct: **True** (36.67% > 16.0%)
- controlled_error_meets_threshold: **True** (11/25 >= 6/25)
- **status: promoted**

## How it works

The schema-context retrieval layer (`oracle_llm/serving/retrieval.py`) indexes
approved, versioned schema metadata (built from live Oracle by
`scripts/build_schema_index.py`) — tables, columns, PK, unique constraints.
Per request, it detects the target schema and injects the real DDL into the
sql_only prompt so the model uses correct object names. It NEVER indexes the
held-out execution catalog or any answers.

## Independent regression suite

- Retrieval DDL verified to match target schemas: **PASS**.
- ORA-00942 (table not found) regression failures dropped from **10/10 → 1/10**
  (the single residual is a transient MV-refresh artifact in the shared-schema
  test loop, not a model object-name failure).

## Breakdown (sql_only + RAG)

- By kind: query 32/81, errors 11/25, admin 5/15, dml 3/17, plsql_json 4/12.
- By schema: SALES_LAB 13/39, DOCUMENTS_LAB 11/24, HR 10/26, CO 9/30, OPS_LAB
  6/21, LOGISTICS_LAB 3/5, SUPPORT_LAB 3/5.

## Packaging

- The promoted challenger = **sql_only-qlora adapter weights (unchanged) +
  schema-context retrieval layer**. No retraining was needed; the retrieval
  layer is the improvement.
- `artifacts/selected_adapter.json` updated to `sql-only-rag`.
- Artifacts: `artifacts/sql-only-rag/{candidates,results}.jsonl`,
  `artifacts/base-rag/{candidates,results}.jsonl`,
  `artifacts/gate_sql_only_rag.json`, `artifacts/comparison_rag.json`.

## Rollback note

Since the underlying adapter is unchanged (sql_only-qlora), "rollback" from
the RAG challenger is simply disabling the schema-index flag at serve/generate
time — restoring the prior 16.0% behavior with zero weight change.
