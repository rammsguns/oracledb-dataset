# Failure taxonomy — sql_only adapter (v1)

Date: 2026-08-28
Source: `artifacts/sql-only-qlora/results.jsonl` (150-task held-out catalog,
live Oracle). Uses only generated candidates + evaluator reports, never the
held-out gold answers.

## Headline

24/150 passed (16.0%). **126 failures. 81 of them are `ORA-00942` (table or
view does not exist).**

## By task kind (126 failures)

| kind | failed | note |
|---|---|---|
| query | 67 | most common |
| errors | 19 | controlled-error tasks |
| dml | 17 | 0/17 passed |
| plsql_json | 12 | 0/12 passed |
| admin | 11 | |

## By schema (126 failures)

SALES_LAB 37 · DOCUMENTS_LAB 24 · CO 21 · OPS_LAB 18 · HR 16 ·
LOGISTICS_LAB 5 · SUPPORT_LAB 5

## By Oracle error

| error | count | interpretation |
|---|---|---|
| **ORA-00942** | **81** | table/view not found — model emits generic/wrong object names |
| no-error | 24 | validation failed (answer ran but produced wrong state/rows) |
| ORA-00904 | 13 | invalid identifier — wrong column name |
| ORA-06550 | 4 | PL/SQL line/column error — block structure |
| other | 4 | misc |

## Root cause

The dominant failure class is **wrong object/column names**: the model generates
plausible but incorrect table/column identifiers (e.g. `orders`,
`sales.orders`, `customer_id`) instead of the actual lab-schema objects
(e.g. `llm_sales_orders`, `order_id`, `customer_name`). The held-out catalog
prompts name the *schema* but not the table DDL, so the model must know each
lab schema's real object names — which the small 160-example `code_only`
training set does not fully teach.

This explains the per-schema distribution: the model scores best on the
schemas it saw most in training and worst (0) on DOCUMENTS_LAB / LOGISTICS_LAB
/ SUPPORT_LAB.

## Recommended fixes (feed into P4)

1. **Schema-aware training data**: author grounded examples that teach the
   actual table/column names per lab schema (SALES_LAB, DOCUMENTS_LAB,
   OPS_LAB, LOGISTICS_LAB, SUPPORT_LAB) — a focused, executable supplement.
2. Response-format enforcement (already done in serving; also add at eval).
3. Re-check against the unchanged held-out catalog only after decisions are
   fixed; never tune repeatedly to its score.
