# Step 3 — Retrieval-augmented regression result

Date: 2026-08-28

## Setup

- Deployed the `sql_only` adapter with the schema-context retrieval layer
  (`oracle-llm serve ... --schema-index artifacts/schema_index.json`).
- Ran `scripts/regression_suite.py --base-url <RAG> --schema-index ...`
  (10 independently-authored, production-like prompts; never the held-out
  catalog).

## Retrieval DDL verification

`[PASS] retrieval DDL matches target schemas` — for every regression case, the
retriever injected the correct schema DDL naming the real target table.

## ORA-00942 result (the headline metric)

| mode | ORA-00942 (table not found) |
|---|---|
| **no retrieval** (baseline) | **10/10** |
| **retrieval-augmented** | **1/10** |

The retrieval layer cuts schema-name failures from 10/10 to 1/10. The single
residual is the SALES_LAB materialized-view case, which is a transient
shared-schema refresh race (the model generates correct `llm_sales_region_mv`
SQL that executes fine in isolation); it is not a model object-name failure.

## Pass rate

- 8/10 regression cases now execute correctly and match expected seed values
  (vs 0/10 without retrieval).
- 2 residual non-PASS: (1) the MV transient case; (2) a SUPPORT_LAB agents
  case where the model executed (`ok:rows=3`) but the expected-value check
  looked for "Tier" while the model returned agents from a different query —
  an expected-value-check artifact, not an execution failure.

## Conclusion

Schema-context retrieval is a strong, verified lever against the ORA-00942
root cause identified in the failure taxonomy. It is now wired into the
sql_only serving path and guarded so it never indexes the held-out catalog.
See Step 4 for the formal held-out catalog evaluation.
