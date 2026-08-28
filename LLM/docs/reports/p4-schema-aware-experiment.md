# P4 focused-improvement experiment: schema-aware supplement

Date: 2026-08-28
Status: **Not promoted** — negative result, documented honestly.

## Hypothesis

The failure taxonomy showed 81/126 sql_only failures are `ORA-00942` (the model
emits generic/wrong object names instead of the real lab-schema tables). The
fix: author a small grounded supplement that teaches the actual table/column
names per lab schema, mix it into the `code_only` training file, and re-train.

## Method

1. Queried live Oracle for each lab schema's real tables/columns
   (`scripts/dump_schema_columns.py`).
2. Authored 22 grounded code_only examples (`scripts/build_schema_aware.py`),
   **every one validated against live Oracle** (must execute + return >=1 row).
   Output: `../oracle_train_schema_aware.jsonl`.
3. Trained `sql-schema-mix-qlora` (182 examples = 160 code_only + 22
   schema-aware; explicit `mixture` config
   `configs/training/qlora-7b-sql-schema-mix.yaml`).
4. Generated + evaluated against the unchanged 150-task held-out catalog.

## Result

| run | passed | % | controlled-error |
|---|---|---|---|
| **sql_only (selected)** | **24** | **16.0** | **6/25** |
| sql-schema-mix (experiment) | 18 | 12.0 | 7/25 |
| base baseline | 8 | 5.3 | 4/25 |

The promotion gate rejects the experiment: pass 12.0% does not exceed the
selected 16.0% threshold (`artifacts/gate_schema_mix.json`). **sql_only remains
the champion.**

## Analysis / why it did not help

- The supplement improved controlled-error slightly (7/25 vs 6/25) but hurt
  overall execution accuracy (18 vs 24). Mixed with the full code_only set, the
  22 schema examples were diluted and did not dominate the model's object-name
  behavior enough to move the ORA-00942 failures.
- A more consequential failure: for the controlled-error task `sales-009`, the
  schema-mix model emitted `CREATE OR REPLACE TRIGGER trg_sales_order_review`
  (threshold 1000) on the REAL shared table. This is harmful DDL: it polluted
  the shared SALES_LAB schema and blocked re-seeding (a candidate answer must
  never do DDL that alters a shared, resettable schema used by other tasks).
  The reset harness was hardened (`reset_lab_schemas.py` now drops stray
  review triggers) so future runs are robust to this class of pollution.

## Takeaways

- Object-name grounding alone is insufficient; the model needs the schema DDL
  **in the prompt** (retrieval/context) or far more targeted object-name
  supervision to fix ORA-00942 at scale.
- Candidates must be constrained to never emit shared-schema DDL. A
  response-format/DDL guard in the generation path is a stronger lever than
  more SFT examples.
- This negative result is preserved as evidence; no claim of improvement is made.

## Artifacts

- `../oracle_train_schema_aware.jsonl` (22 validated records)
- `artifacts/sql-schema-mix-qlora/{provenance,results,candidates}.jsonl`
- `artifacts/gate_schema_mix.json` (rejection)
- `scripts/build_schema_aware.py`, `scripts/dump_schema_columns.py`
