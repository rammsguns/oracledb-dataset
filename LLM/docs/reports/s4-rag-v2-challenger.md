# S4 — Retrieval-context challenger evaluation (enriched v2 index)

Date: 2026-08-28
Status: **NOT promoted** — fails the pass-rate threshold.

## Goal

Evaluate ONE retrieval-context challenger at a time against the unchanged
150-task benchmark. The challenger = sql_only-qlora adapter + the enriched v2
schema index (adds FKs, views, check constraints, and table descriptions).
Promote ONLY if it exceeds 36.7% AND keeps controlled-error accuracy ≥ 11/25.

## Held-out result (150 tasks, temperature 0, unchanged catalog)

| run | passed | % | executed_ok | exact | controlled-error |
|---|---|---|---|---|---|
| **sql-only-rag (v1, incumbent champion)** | **55** | **36.7** | **95** | **44** | **11/25** |
| sql-only-rag-v2 (enriched index challenger) | 50 | 33.3 | 99 | 39 | **11/25** |
| sql_only (no RAG) | 24 | 16.0 | 42 | 18 | 6/25 |
| base baseline | 8 | 5.3 | 18 | 4 | 4/25 |
| gold | 150 | 100.0 | 125 | 125 | 25/25 |

## Promotion gate

`artifacts/gate_rag_v2.json`:
- exceeds pass threshold (>36.7%): **False** (33.33% ≤ 36.7%)
- controlled-error ≥ 11/25: **True** (11/25)
- **status: candidate (NOT promoted)**

## Analysis

- The enriched v2 index did not hurt controlled-error (held at 11/25) and
  slightly raised executed-ok (99 vs 95), but overall pass dropped to 33.3%
  from 36.7%. The additional DDL context (FKs, checks, descriptions) made the
  prompts longer and, at the same token budget, did not help (and slightly
  hurt) exact SQL generation on this benchmark.
- Per the promotion rule, the challenger is **not promoted**. **sql-only-rag
  (v1) remains the production release candidate** (v1.0.2).

## Decision

- Retain `sql-only-rag` (v1) as champion.
- The v2 enriched index remains available (`artifacts/schema_index_v2.json`)
  and adds value for joins/schema-qualified/PL-SQL (S3 regression all passed
  with it), but it is not the promoted benchmark config.
- Rollback target remains `sql-only-rag` = sql_only-qlora + v1 schema index.

## Artifacts

- `artifacts/rag-v2-challenger/{candidates,results}.jsonl`
- `artifacts/gate_rag_v2.json`
- `artifacts/schema_index_v2.json` (enriched, versioned metadata)
