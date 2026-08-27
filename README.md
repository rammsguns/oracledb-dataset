# Oracle Dataset Verification Pipeline

Two layers of grading for `oracle_dataset_full.jsonl`, so the dataset goes
from "plausible text" to "verified code".

## Layer 1 — SQL syntax lint (runs anywhere, no Oracle needed)

```
.venv/bin/python grade_parse.py oracle_dataset_full.jsonl
```

Uses [sqlglot](https://github.com/tobymao/sqlglot) (Oracle dialect) to lint SQL
statements. It catches broken SQL but CANNOT compile PL/SQL bodies — those are
marked `unverified` and deferred to Layer 2.

## Layer 2 — execution grading (needs Docker + live Oracle)

```
docker compose up -d                       # start Oracle Free (23-slim)
docker logs -f oracle-grader | grep -i 'DATABASE IS READY'   # wait for ready
uv pip install oracledb                    # thin mode, no client libs
.venv/bin/python grade_db.py oracle_dataset_full.jsonl
```

Runs every extracted SQL/PL/SQL statement against a real Oracle and classifies
each statement:

| verdict       | meaning                                                   |
|---------------|-----------------------------------------------------------|
| PASS          | statement parsed + executed without error                 |
| FAIL          | real defect (PLS-00103, ORA-00933, ORA-01722, ...)        |
| SCHEMA_MISS   | references a table the example didn't provide             |
| CHECK_PASS    | an `expected` assertion returned the correct value        |
| CHECK_FAIL    | an `expected` assertion returned the wrong value          |
| UNKNOWN       | environmental (bind placeholder, pre-existing object, ...)|

### Schemas

The grader routes each example by its optional `schema` field:

- **GRADER** (default) — scratch schema. Each example builds its own tables
  from `input`, runs, then drops them; never collides.
- **HR** / **CO** — the Oracle sample schemas (`hr`/`HrTest_23ai`,
  `co`/`CoTest_23ai`). Queried read-only against live data; never modified.

### Expected-value verification

Examples may carry an `expected` array:
```
"expected": [{"sql": "SELECT COUNT(*) FROM employees", "value": 107}]
```
The grader runs each check and asserts the first cell equals `value`, turning
"does it compile" into "does it return the right answer".

## Why the current dataset has low execution coverage

The `input` field is empty for most rows. Without a schema, the execution
grader hits ORA-00942 ("table or view does not exist") and marks everything
SCHEMA_MISS. This is the #1 structural gap in the dataset, not a grader bug.

To make execution grading high-signal, generate examples with grounded
schemas: put the actual `CREATE TABLE` DDL for the referenced tables into the
`input` field. Then `grade_db.py` will (in a future step) auto-create that
schema before running the example's statements. The grader already classifies
the two error families separately, so mixing grounded and ungrounded rows is
fine.

## Files

- `grader_lib.py`          — statement extraction (shared by both graders)
- `grade_parse.py`         — Layer 1 SQL lint
- `grade_db.py`            — Layer 2 execution grading
- `docker-compose.yml`     — Oracle Free container (gvenzl/oracle-free:23-slim)
- `load_dataset.py`        — HuggingFace datasets loader
- `oracle_train*.jsonl`    — training splits (alpaca + chat formats)
- `oracle_eval_holdout.jsonl` — held-out eval (never train on this)

## Requirements

- Python 3.11+ with `sqlglot` (lint) and `oracledb` (execution)
- Docker with ~2 GB RAM free and ~6 GB disk for the Oracle image
- First Oracle container startup takes 2–5 minutes

## Lab harness — reset + catalog evaluator

Two tools turn the live DB into a reliable source of *verified* training
examples (the state-changing gold tasks in the catalog COMMIT internally, so a
known starting state and per-task cleanup are essential).

### reset_lab_schemas.py — known starting state
Restores SALES_LAB, DOCUMENTS_LAB, OPS_LAB to their pristine seeded rows and
resets sequences, so every task starts clean. Idempotent, no SYSDBA (connects
as each lab user).

```
.venv/bin/python reset_lab_schemas.py             # all three
.venv/bin/python reset_lab_schemas.py SALES_LAB   # one
.venv/bin/python reset_lab_schemas.py --verify    # reset then print seed counts
```

### evaluate_catalog.py — the evaluator
Reads a task catalog (JSONL: id/schema/task/gold_sql/validation_sql/expected).
For each task it resets the schema, connects AS that user, executes the answer
(gold by default, or a candidate answer via `--candidate`), runs the
validation SQL, and records **pass/fail, Oracle error, elapsed ms, and a
SHA-256 checksum** of the answer + validation results.

```
.venv/bin/python evaluate_catalog.py --catalog llm_task_catalog_v2.jsonl
.venv/bin/python evaluate_catalog.py --catalog ... --candidate answers.jsonl
```

Catalog fields:
- `gold_sql` — the canonical answer.
- `validation_sql` — asserts the outcome (e.g. `SELECT COUNT(*) FROM ...`).
- `expected` / `expected_count` / `expected_contains` — pass criteria. For
  **controlled-failure** tasks, `expected_error` (e.g. `"ORA-20001"`) makes
  PASS mean "the answer raised exactly this Oracle error".

The evaluator resets every schema before AND after the run, so the shared DB
is always left pristine. `llm_task_catalog_v2.jsonl` holds 17 curated tasks
across the taxonomy — SQL reporting, DML/transactions, PL/SQL/JSON ingestion,
admin/security, and controlled failures (trigger rejection, missing privilege,
invalid object, invalid JSON, unique-key violation, bad join) — all verified
17/17 against the live schemas.

### Catalog (500+ tasks) + held-out eval set
`llm_task_catalog_v3.jsonl` is the full verified task catalog: **538 tasks,
538/538 passing** against the live schemas (verified by `evaluate_catalog.py`),
covering **7 schemas** — the original 5 plus two new domains:

- **LOGISTICS_LAB** (`LogisticsLab_23ai`) — stock movements (IN/OUT per
  warehouse), shipments with late-delivery detection, products/warehouses,
  reorder-level analysis. 19 tasks.
- **SUPPORT_LAB** (`SupportLab_23ai`) — support tickets, SLA targets by
  priority (SLA-met/missed analytics), agents, error triage. 19 tasks.

by schema: 139 SALES_LAB, 94 HR, 106 CO, 87 DOCUMENTS_LAB, 74 OPS_LAB,
19 LOGISTICS_LAB, 19 SUPPORT_LAB.

The catalog is split into two provably-disjoint sets (verified 0 overlap by
schema+task):

- `llm_task_catalog_train.jsonl` — **388 training tasks** (stratified).
- `llm_task_catalog_eval.jsonl` — **150 held-out evaluation tasks** (stratified
  by schema, ~28%), not merely paraphrases of the training prompts.

Each task carries `{id, schema, task, gold_sql, validation_sql, expected}` and
optionally `expected_count`/`expected_contains`/`expected_error`. The
controlled-failure tasks (75+) exercise real integrity/authorization rules
(trigger rejection, check/FK/PK/NOT-NULL constraints, missing privileges,
invalid objects/JSON, bad joins, view read-only).

To evaluate a model: run its answers for `llm_task_catalog_eval.jsonl` via
`evaluate_catalog.py --candidate answers.jsonl`, which resets each schema and
compares each answer's result checksum to the gold.

The reset harness covers all 7 lab schemas:
```
.venv/bin/python reset_lab_schemas.py --verify
```

### Training variants (SQL-generation tuning)
The instruction-tuning set mixes code with prose explanations. For
SQL-generation fine-tuning, separate variants are provided:

- `oracle_train_code_only.jsonl` — 160 rows, `output` is **only the executable
  SQL/PL/SQL** (extracted via `grader_lib.extract_statements`, verified to end
  in a valid terminator). For teaching the model to emit code alone.
- `oracle_train_error_repair.jsonl` — 56 rows derived from the catalog's
  controlled-failure tasks: each prompts "diagnose and fix this Oracle error"
  and the gold answer gives the error code, root cause, fix strategy, the
  offending statement, and the validation query. For teaching error
  diagnosis / repair.
- `oracle_train_chat.jsonl` / `oracle_train_alpaca.jsonl` — the standard
  full code+explanation forms.

### Reproducibility
- `MANIFEST.md` — exact file counts, byte sizes, verification results, and the
  live environment (gvenzl/oracle-free:23-slim / banner 26ai-23.26,
  python-oracledb 4.0.2, sqlglot 30.17).
- `requirements.txt` — Python dependencies.
- Regenerated reports: `grade_parse_report.json` (178 examples, 160 SQL OK,
  2 sqlglot-gap, PL/SQL unverified) and `catalog_results_v3_full.jsonl`
  (538/538 catalog tasks pass).

### Baseline evaluation pipeline (measure Oracle competence)
The recommended loop for deciding whether the dataset improves a model:

```
# 1. Generate model answers for the held-out eval set.
.venv/bin/python generate_answers.py \
    --catalog llm_task_catalog_eval.jsonl --mode model \
    --base-url http://<llama-swap>/v1 --model <name> \
    --out candidate_answers.jsonl

# 2. Evaluate them against the live Oracle (resets schemas per task).
.venv/bin/python evaluate_catalog.py \
    --catalog llm_task_catalog_eval.jsonl \
    --candidate candidate_answers.jsonl
```

The evaluator reports, per run:
- **overall pass %** and **executed-ok %** (answer ran without error)
- **by kind**: query / dml / plsql_json / admin / controlled-error accuracy
- **by schema**: per-schema pass rate
- **controlled-error accuracy**: how often the expected Oracle error was raised
- **candidate exact-answer (checksum-matched) %**: answer result == gold result

Sanity-check the harness before trusting a model run:
- `--mode gold` → 100% pass (150/150, exact-answer 125/125 among non-error tasks).
- `--mode baseline` → ~52% pass with every category degraded, proving the
  harness discriminates correct from wrong answers.

Training variants to compare (step 3 of the plan): `oracle_train_code_only.jsonl`
(code-only SFT), `oracle_train_chat.jsonl` (instruction+explanation), and
`oracle_train_error_repair.jsonl` (error diagnosis). Compare their eval pass
rates, schema-specific performance, and kind breakdowns on
`llm_task_catalog_eval.jsonl`.

### Release freeze
The dataset/catalog are frozen as release `oracle-labs-v1.0.0`. File SHA-256
hashes and the eval-set access policy are pinned in `MANIFEST.md`. Pin training
to those hashes; keep `llm_task_catalog_eval.jsonl` (150 held-out eval tasks)
out of all training data.

### Credentials are environment-driven (no secrets committed)
This public educational repo contains NO database credentials. All passwords are
read from environment variables at runtime:

- Lab schemas: `ORACLE_LAB_PW_SALES_LAB`, `ORACLE_LAB_PW_DOCUMENTS_LAB`,
  `ORACLE_LAB_PW_OPS_LAB`, `ORACLE_LAB_PW_LOGISTICS_LAB`, `ORACLE_LAB_PW_SUPPORT_LAB`
- Sample schemas: `ORACLE_SAMPLE_PW_HR`, `ORACLE_SAMPLE_PW_CO`
- System/GRADER (scratch): `ORACLE_SYSTEM_PASSWORD` (GRADER uses its own
  synthetic scratch password, not a secret)

Example:
```
export ORACLE_LAB_PW_SALES_LAB="..." ORACLE_SAMPLE_PW_HR="..."
.venv/bin/python grade_db.py oracle_dataset_full.jsonl
```
