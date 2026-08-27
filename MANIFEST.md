# Dataset & Catalog Manifest
This manifest records the exact state of the Oracle LLM dataset and task catalog
so runs are reproducible and auditable.

## Version
- manifest_version: 3.0.0
- release_tag: `oracle-labs-v1.0.0`
- generated: 2026-08-27
- frozen: yes (see "Integrity" below — file hashes pinned)

This is a frozen release. Any subsequent change to the data files bumps the
release tag and updates the hashes below; training must pin to the hashes in
this manifest.

## Data files (current counts, all JSONL, one JSON object per line)
| file | records | bytes | notes |
|---|---|---|---|
| oracle_dataset_full.jsonl | 178 | 230,797 | canonical instruction-tuning set |
| oracle_train.jsonl | 160 | 205,701 | training split (stratified, disjoint) |
| oracle_eval_holdout.jsonl | 18 | 25,096 | held-out eval (disjoint from train) |
| oracle_train_chat.jsonl | 160 | 252,031 | messages format |
| oracle_train_alpaca.jsonl | 160 | 185,747 | instruction triplet format |
| oracle_train_code_only.jsonl | 160 | 112,228 | SQL-generation: code-only answers |
| oracle_train_error_repair.jsonl | 56 | 42,280 | error-diagnosis / repair variants |
| llm_task_catalog_v3.jsonl | 538 | 200,123 | full executable task catalog |
| llm_task_catalog_train.jsonl | 388 | 143,618 | catalog training split |
| llm_task_catalog_eval.jsonl | 150 | 56,505 | catalog held-out eval (disjoint) |

## Verification results (current)
| report | verifies | result |
|---|---|---|
| grade_db_report.json | execution grading of oracle_dataset_full.jsonl | 195 PASS, 127 CHECK_PASS, 0 FAIL/CHECK_FAIL |
| grade_parse_report.json | sqlglot lint of oracle_dataset_full.jsonl | 178 examples, 160 SQL OK, 2 sqlglot-gap, PL/SQL unverified |
| catalog_results_v3_full.jsonl | full v3 catalog (538 tasks) | 538/538 passed, 0 failed |
| catalog_results_v2.jsonl | v2 catalog (17 tasks) | 17/17 passed |
| catalog_results_gold.jsonl | original 5 gold tasks | 5/5 passed |
| (eval harness, gold mode) | eval set answers = gold | 150/150 pass, exact-answer 125/125 |
| (eval harness, baseline mode) | deliberately wrong half | 78/150 pass — proves discrimination |

## Live environment
- Oracle: gvenzl/oracle-free:23-slim Docker image, container `oracle23ai_dataset`
- Instance banner: `Oracle AI Database 26ai Free Release 23.26.3.0.0`
  (Docker tags the image "23"; the banner reports 26ai/23.26 — same engine)
- DSN: `localhost:1521/FREEPDB1`
- Python: 3.14 (`.venv`), python-oracledb 4.0.2 (thin mode), sqlglot 30.17

## Schemas
Resettable lab schemas (reset_lab_schemas.py): SALES_LAB, DOCUMENTS_LAB,
OPS_LAB, LOGISTICS_LAB, SUPPORT_LAB.
Read-only sample schemas (never reset): HR, CO.
Dedicated scratch schema: GRADER (built/dropped per example).

## Record schema
- `oracle_dataset_full.jsonl`: {instruction, input, output, difficulty,
  schema?, expected?}
- `llm_task_catalog_v3.jsonl`: {id, schema, task, gold_sql, validation_sql,
  expected, expected_count?|expected_contains?|expected_error?}
- `catalog_results_*.jsonl`: {id, schema, pass, error, notes, elapsed_ms,
  answer_checksum?, validation_rows?, validation_checksum, expected}

## Integrity

### Secrets
This repository contains NO database credentials. All passwords are read from
environment variables at runtime (see README "Credentials are environment-driven").
Scratch-schema GRADER uses a synthetic password. Do not commit real credentials.

### File hashes (SHA-256, release `oracle-labs-v1.0.0`)
| file | sha256 |
|---|---|
| oracle_dataset_full.jsonl | `2ca6e014341b434cc32e37034cb6d075d3a96cac94e43674f1b823a26d4322f0` |
| oracle_train.jsonl | `3b4cb82b3e023629b02e92c5d8ab8c7ff201914835f7fd9efed5169d9c5c23e3` |
| oracle_eval_holdout.jsonl | `dd4c7217f2f32fe6e86ba2fe66e0e076713a591db3f96e6565929a6871059375` |
| oracle_train_chat.jsonl | `fc3d943e23f348a8e75bd6b2e191b4b456c4416a8a9d4bc851f1f87c1ba50690` |
| oracle_train_alpaca.jsonl | `41e9f94758e944a256ab13ba3b7889e49759c2256ea190936df4bb9153f03171` |
| oracle_train_code_only.jsonl | `fb44dde950dc85090e37e9f8416c713ec8743c66ca043cf4d9ecbf554f316a1c` |
| oracle_train_error_repair.jsonl | `b71f80a2630fe01dc9ef820c69e0a7dc5ea3f00e0a745741d775e5c31bdb978b` |
| llm_task_catalog_v3.jsonl | `01eea5f2bd8deb880289900d9e9e3652b5c9edbc39049844917d08faa834ad10` |
| llm_task_catalog_train.jsonl | `6f1f665e53b532ebb61917cbcfbef1b4fbe805be3f251e06949ef6641ffdad86` |
| llm_task_catalog_eval.jsonl | `128855bf26d3f8063f0859a1a37f6a599cb27938c6057312347f633a97b50628` |
| catalog_results_v3_full.jsonl | `0264169768491a2f5ea893038cfc527c3636d8ed7ca2213d1db3af201269bc3a` |
| grade_db_report.json | `88ea14d710d345e5aa3be87f9bd9d3fff39083de86dbbd129976e34798928aa9` |
| grade_parse_report.json | `5fdd4f3f1b526b82f211927a340c6d2a4042159d2b2441a619ea0d1f066914b3` |

Verify with: `sha256sum <file>` and compare.

### Access policy
- `llm_task_catalog_eval.jsonl` (150 held-out eval tasks) is the **held-out
  evaluation set**. Keep it out of all training data and do not regenerate
  training examples from it. Pin it to this hash so evaluation results are
  comparable across model runs.

### Rules
- HR/CO tasks must be read-only (no reset available).
- DML/state-changing tasks only on resettable lab schemas.
- Every task in the catalog is verified by `evaluate_catalog.py` against live
  Oracle before it is added; schemas are restored to pristine after each run.
