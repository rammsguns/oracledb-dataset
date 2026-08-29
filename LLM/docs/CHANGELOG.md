# Changelog — Oracle Database LLM

All notable changes to the Oracle Database LLM assistant (release/llm-vX.Y.Z
branches). Semver: minor = new capability, patch = fix/operational.

## [v1.0.6] — 2026-08-29 — Sequence metadata + benchmark governance (champion unchanged)
### Added
- **Sequence metadata in the schema index**: `scripts/build_schema_index_v2.py`
  now extracts sequence names (`_dump_sequences`) and emits them per schema, and
  `oracle_llm/serving/retrieval.py` renders `-- sequences: ...` in the schema
  DDL. This lets the model use correct `NEXTVAL`/`CURRVAL` names instead of
  inventing a sequence and hitting ORA-02289. **Non-model, non-ranked**
  retrieval improvement; the champion config is unchanged.
- **Governance deny-list** in `oracle_llm/serving/retrieval.py`: the frozen
  acceptance/regression suite (`acceptance`, `acceptance_set`,
  `final_acceptance`, `llm_acceptance`) and the blind final set (`blind`,
  `blind_final`, `FIN_LAB`) are added to `DENIED_INDEX_SOURCES` so they can
  never be indexed even accidentally.
- Unit tests: `tests/test_retrieval.py` — sequence rendering
  (`test_sequences_rendered_in_ddl`), sequence absence
  (`test_sequences_absent_when_none`), acceptance-suite denial
  (`test_deny_acceptance_suite`), blind-set denial (`test_deny_blind_final_set`).

### Validation (development benchmark + independent regression suite only)
The sequence fix was identified on the frozen acceptance/regression suite, so it
is **acceptance-informed evidence**, not blind-final evidence. It was validated
for release only on the 150-task development benchmark and the independent
regression suite (identical model, decoding settings, and schema coverage;
only the sequence metadata differs between the compared indexes):
- Dev benchmark: incumbent + prior-approved index 50/150 (33.3%), CE 11/25 →
  incumbent + sequence-enabled index **56/150 (37.3%), CE 15/25** (improves).
- Independent regression suite: identical 15/16 in both configs (the single
  failure is a pre-existing schema-detection limitation shared by both) — no
  regression.

### Notes
- `--ranked` (task-level table ranking, v4) is **explicitly experimental and
  off by default**. It is not part of this release; the champion remains
  whole-schema `sql-only-rag`.
- The final release decision must use an independently owned set (see
  `blind_final/BLIND_FINAL_MANIFEST.md`); the retained FIN_LAB set is a frozen
  regression reference, not a blind holdout.

## [v1.0.5] — 2026-08-28 — Compact retrieval analysis (champion unchanged)
### Added
- **Compact retrieval mode** (`compact`): low-noise DDL (columns + PK + FK
  only, dropping check constraints, NOT-NULL noise, and prose descriptions) in
  `oracle_llm/serving/retrieval.py`.
- **Per-request context token budget** (`max_context_tokens`): truncates
  retrieved DDL to a strict budget on `build_context_prompt`.
- CLI wiring (`--compact`, `--max-context-tokens`) through
  `oracle_llm/cli.py` and `oracle_llm/evaluation/generate.py`.
- Analysis scripts: `scripts/analyze_v2_regression.py` (v1→v2 per-task deltas,
  error-category shifts) and `scripts/measure_context_length.py` (v1/v2/v3
  prompt-size comparison).
- Reports: `docs/reports/s4-v2-regression-analysis.md` (root cause of the v2
  regression) and `docs/reports/s5-rag-v3-compact.md` (v3 experiment).
- Unit test: `tests/test_retrieval.py::test_retriever_compact_mode_and_budget`.

### Status
- **Champion unchanged**: `sql-only-rag` remains selected (36.7% held-out pass,
  11/25 controlled-error).
- v3 compact RAG (53/150, 35.3%, CE 12/25) recovered most of the v2 regression
  but did **not** exceed the v1 champion; recorded as a candidate, NOT promoted
  (see `docs/reports/s5-rag-v3-compact.md`).
- Engineering/analysis release only; no model or retrieval configuration change
  for the champion.

## [v1.0.4] — 2026-08-28 — Engineering/quality release (champion unchanged)
### Added
- **Staged read-only pilot** (`--read-only`): refuse DML/DDL requests (422),
  track refusal_rate in `/metrics`.
- **Enriched schema index (v2)** (`build_schema_index_v2.py`): FKs, views,
  check constraints, and table descriptions; v2 retriever support.
- **Extended regression suite**: joins, schema-qualified objects, PL/SQL, and
  privilege-failure cases (independently authored).
- Release governance (`docs/RELEASE_GOVERNANCE.md`) and changelog.

### Changed
- `docs/MODEL_CARD.md` updated with release history + rollback target.
- Regression-suite harness handles PL/SQL anonymous blocks.

### Status
- **Champion unchanged**: `sql-only-rag` remains the selected adapter —
  36.7% held-out pass, 11/25 controlled-error. This release adds engineering
  and observability; it does NOT change the model or retrieval configuration.
- The v2 enriched-index challenger was evaluated once (33.3%, CE 11/25) and
  NOT promoted (see `docs/reports/s4-rag-v2-challenger.md`).

## [v1.0.3] — 2026-08-28 — Operational safety
### Added
- **Disposable-schema execution guard** (`oracle_llm/evaluation/safety.py`):
  fail-closed policy that generated SQL may only execute against resettable
  lab schemas (SALES_LAB, DOCUMENTS_LAB, OPS_LAB, LOGISTICS_LAB, SUPPORT_LAB);
  read-only HR/CO only for read-only SQL; production never a target. Env-only
  credentials.
- **Monitoring**: retrieval-miss rate and Oracle error-category buckets in
  `GET /metrics` and the regression suite.
- **Read-only pilot mode** (`--read-only`): refuses DML/DDL requests (422),
  tracks refusal_rate.
- **Enriched schema index (v2)**: FKs, views, check constraints, and table
  descriptions (`build_schema_index_v2.py`); v2 retriever support.
- **Extended regression suite**: joins, schema-qualified objects, PL/SQL, and
  privilege-failure cases (independently authored).
- Operational-safety section in `docs/RUNBOOK.md`.

### Changed
- `reset_lab_schemas.py`: hardened to drop any candidate-created review
  trigger on `llm_sales_orders`.
- Regression suite harness handles PL/SQL anonymous blocks.

### Fixed
- Regression-suite expected values (SUPPORT_LAB agents), DDL-verification
  parser (schema prefixes, DUAL).

## [v1.0.2] — 2026-08-28 — Schema-context retrieval (promotes champion)
### Added
- **Schema-context retrieval layer** (`oracle_llm/serving/retrieval.py`):
  indexes approved schema metadata and injects DDL into sql_only prompts.
  Never indexes the held-out catalog.
- `scripts/build_schema_index.py` (v1 index), staging smoke, regression suite.
- Weighted-mixture training support.

### Changed
- **Champion promoted to `sql-only-rag`**: held-out execution 24/150 (16.0%)
  → **55/150 (36.7%)**; controlled-error 6/25 → **11/25**. ORA-00942
  regression failures dropped from 10/10 to 1/10.

## [v1.0.1] — 2026-08-28 — Pipeline, evaluation, serving
### Added
- Full `oracle_llm` package + CLI: data contract, training, evaluation,
  selection, serving.
- Staging smoke + regression suite, schema-aware supplement, weighted-mixture
  config, reports, ADRs.
- Champion: `sql_only-qlora` at 16.0% (then superseded in v1.0.2).

## [v1.0.0] — 2026-08-27 — Dataset + catalog release
- Frozen Oracle LLM dataset + executable task catalog (MANIFEST-pinned
  SHA-256s), release tag `oracle-labs-v1.0.0`.

## Rollback
The tested rollback target is **v1.0.1** (sql_only-qlora, no retrieval):
disabling `--schema-index` at serve/generate restores pre-retrieval behavior
with zero weight change. Old adapter dirs + `provenance.json` are retained for
immutable re-provisioning.
