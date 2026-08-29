# S4 analysis — why v2 enriched index reduced 36.7% → 33.3%

Date: 2026-08-28
Status: root cause identified; informs the v3 experiment.

## Numbers

| metric | v1 RAG | v2 RAG (enriched) |
|---|---|---|
| held-out pass | **55/150 (36.7%)** | 50/150 (33.3%) |
| controlled-error | 11/25 | 11/25 |
| executed_ok | 95 | 99 |
| exact (checksum) | 44 | 39 |

Per-task delta: **8 regressed (pass→fail), 3 improved** → net −5.

## Root cause: context bloat, not detection or syntax

1. **Schema detection is identical** — 150/150 catalog tasks detected the same
   target schema under v1 and v2. The regression is NOT a detection failure.

2. **Injected context is 70–195% longer** under v2 (the enriched FKs, check
   constraints, and descriptions):
   - LOGISTICS_LAB: 65 → 192 tokens (+195%)
   - SUPPORT_LAB:  59 → 164 (+178%)
   - SALES_LAB:    59 → 160 (+171%)
   - DOCUMENTS_LAB: 39 → 93 (+138%)
   - OPS_LAB:      35 → 59 (+69%)

3. **Regression error profile**: of the 8 regressions, **6 failed with
   "no-error"** (the SQL executed but the result did NOT match the gold
   checksum), 1 ORA-00979, 1 ORA-06550. Only ~2 were genuine parse errors.
   This means the longer v2 DDL shifted *what* the model generated — valid but
   lexically/semantically different SQL — rather than breaking it.

4. **Kind concentration**: regressions hit query (4), dml (2), errors (2) —
   i.e. exactly the tasks where a longer prompt crowds out the task and the
   model loses the specific gold form. The added constraint/FK lines dilute
   the object-name signal and consume token budget (max_length 2048).

## Conclusion

The enrichment added noise relative to signal: every check-constraint and
NOT-NULL line is a token the model must read but that does not help it choose
the correct table/column (which v1 already provided). The result is a ~1.5–3×
longer prompt that (a) crowds the task out of the budget and (b) perturbs
generation toward valid-but-different SQL that fails the exact checksum.

## Implication for v3

Keep the *relevant* signal (table + columns + PK + FK for joins) but drop the
low-value noise (per-column NOT-NULL/check conditions, per-table prose
descriptions) and enforce a strict per-request context-token budget. This is
the v3 experiment (task 5).
