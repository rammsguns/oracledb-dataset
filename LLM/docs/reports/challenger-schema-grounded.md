# Step 5 — next challenger: schema-grounded DDL experiment

Date: 2026-08-28
Status: **Not promoted** — evaluated once through the promotion gate.

## Hypothesis

The independent regression suite (Step 4) confirmed the model invents generic
tables (`customers`, `orders`) even when the schema name is in the prompt —
the same ORA-00942 root cause. Fix: give the model the **real per-table DDL in
the training input** so it learns the schema-name → object-name mapping, and
oversample those records so the mapping dominates.

## Method

1. Authored `scripts/build_schema_grounded.py` — 13 production-style requests
   across all 5 lab schemas, each with the real `CREATE TABLE` DDL in the
   `input` and a verified answer query using real object names.
   Output: `../oracle_train_schema_grounded.jsonl` (13 records, **every one
   validated against live Oracle**).
2. Weighted mixture config `configs/training/qlora-7b-schema-grounded.yaml`
   (code_only 160×1 + grounded 13×3 = **199 weighted records**).
3. Trained `challenger-schema-grounded` (4 epochs, train_loss 0.164).
4. Generated + evaluated **once** against the unchanged 150-task held-out
   catalog, then ran the promotion gate.

## Result

| run | passed | % | controlled-error |
|---|---|---|---|
| **sql_only (incumbent)** | **24** | **16.0** | **6/25** |
| challenger-schema-grounded | 19 | 12.7 | 5/25 |
| schema-aware mix (earlier) | 18 | 12.0 | 7/25 |
| base baseline | 8 | 5.3 | 4/25 |

The gate rejects the challenger (`artifacts/gate_challenger_schema_grounded.json`):
- pass 12.67% does not exceed incumbent threshold 16.0%
- controlled-error 5/25 is below the 6/25 threshold

**sql_only remains the selected adapter.**

## Analysis

- The DDL-grounded supplement is directionally positive vs baseline (12.7% vs
  5.3%) and slightly better than the non-DDL schema-aware mix (12.0%), showing
  DDL context helps object-name mapping a little.
- It still does not clear the gate. A 13-record supplement is too small to
  dominate a 160-record base under weight 3×, and the held-out catalog prompts
  do NOT include DDL — so at inference the model still faces schema-name-only
  prompts it must answer from memory.
- Controlled-error regressed (5/25). The challenger did not retain the
  error-repair behavior of the incumbent.

## Takeaway for the next round

- Schema-grounded SFT is not enough on its own. The stronger levers are
  (a) a retrieval/context layer that injects the real DDL into the prompt at
  inference, and/or (b) a much larger, varied schema-grounded training set that
  spans object-name combinations, not 13 fixed records.
- No claim of improvement is made; this negative result is preserved as
  evidence.

## Artifacts

- `../oracle_train_schema_grounded.jsonl` (13 validated records)
- `artifacts/challenger-schema-grounded/{provenance,results,candidates}.jsonl`
- `artifacts/gate_challenger_schema_grounded.json` (rejection)
- `scripts/build_schema_grounded.py`
- `configs/training/qlora-7b-schema-grounded.yaml`
