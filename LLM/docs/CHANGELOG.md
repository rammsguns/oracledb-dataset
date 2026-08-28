# Changelog — Oracle Database LLM

All notable changes to the Oracle Database LLM assistant (release/llm-vX.Y.Z
branches). Semver: minor = new capability, patch = fix/operational.

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
