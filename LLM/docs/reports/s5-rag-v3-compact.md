# S5 — v3 retrieval experiment (compact DDL + token budget)

Date: 2026-08-28
Status: **NOT promoted** — v3 > v2 but does not exceed the v1 champion.

## Hypothesis

The v2 enriched index reduced pass 36.7% → 33.3% due to context bloat
(70–195% longer DDL; 6/8 regressions were valid-but-different SQL, not parse
errors). v3 retrieves only the *relevant* signal — columns + PK + FK (for
joins) — and drops checks/descriptions, with an optional strict token budget.

## Method

- Added `compact` mode to `SchemaRetriever.format_schema_ddl` (columns+PK+FK
  only) and a `max_context_tokens` budget on `build_context_prompt`.
- Wired `--compact` / `--max-context-tokens` through the generate CLI.
- Generated candidates once with the v2 enriched index in compact mode,
  evaluated against the unchanged 150-task catalog.

## Context size (tokens)

| schema | v1 | v2 | v3 (compact) |
|---|---|---|---|
| LOGISTICS_LAB | 64 | 191 | 82 |
| SUPPORT_LAB | 58 | 163 | 76 |
| SALES_LAB | 58 | 159 | 62 |
| DOCUMENTS_LAB | 38 | 92 | 44 |
| OPS_LAB | 34 | 58 | 34 |

v3 keeps context near v1 size while retaining the FK signal v1 lacked.

## Result

| run | passed | % | controlled-error | exact |
|---|---|---|---|---|
| **sql-only-rag (v1 champion)** | **55** | **36.7** | **11/25** | **44** |
| v3 compact | 53 | 35.3 | **12/25** | 41 |
| v2 enriched | 50 | 33.3 | 11/25 | 39 |
| sql_only (no RAG) | 24 | 16.0 | 6/25 | 18 |

Promotion gate (`gate_rag_v3.json`): pass 35.33% ≤ 36.7% → **candidate, NOT
promoted**.

## Analysis

- v3 partially recovered the v2 regression (33.3% → 35.3%) and improved
  controlled-error to 12/25 — consistent with "less context noise helps".
- It still falls ~1.3pp short of v1. The remaining gap is small; the exact
  FK/constraint surface v1 presented by omission (v1 had NO FKs at all, yet
  scored highest) suggests even the retained FK lines carry some cost for
  single-table tasks.
- A plausible next step (out of scope here): condition retrieval on task shape
  — inject FKs only when the request clearly involves a join, otherwise emit
  v1-minimal columns+PK.

## Decision

- **Champion unchanged**: `sql-only-rag` (v1) remains selected (36.7%, CE
  11/25).
- v3 compact is recorded as a candidate, not promoted.
- The `compact` flag remains available as an engineering option for future
  challengers and low-latency serving.

## Artifacts

- `artifacts/rag-v3-compact/{candidates,results}.jsonl`
- `artifacts/gate_rag_v3.json`
- `scripts/analyze_v2_regression.py`, `scripts/measure_context_length.py`
- `docs/reports/s4-v2-regression-analysis.md`