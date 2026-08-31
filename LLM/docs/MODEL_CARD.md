# Model Card — Oracle Database LLM assistant

This card describes the LoRA adapter produced by the pipeline in this
directory. It is populated automatically into `artifacts/<run>/model_card.json`
at training time; this file is the human-readable template and reference.

## Model

- **Type**: LoRA adapter (PEFT) on top of an open instruction base model.
- **Base model**: `Qwen/Qwen2.5-Coder-7B-Instruct`
- **Base model revision**: `c03e6d358207e414f1eca0bb1891e29f1db0e242` (pinned
  in `configs/training/qlora-7b-sql-only.yaml`).
- **Adapter**: QLoRA (4-bit NF4), `r=16`, `alpha=32`, `dropout=0.05`,
  `target_modules=all-linear`, `bias=none`.
- **Intended use**: emit executable Oracle SQL/PLSQL and explain/repair Oracle
  database errors. Two serving modes: `sql_only` and `explain`.

## Selected adapter (2026-08-28, production release candidate)

The promoted release candidate is **`sql-only-rag`** (v1.0.2): the `sql_only`
LoRA adapter plus the approved **schema-context retrieval layer** (indexes the
resettable lab schemas' DDL — tables, columns, PK/unique/FK, check constraints,
views — never the held-out catalog). It achieved **55/150 (36.7%)** on the
unchanged 150-task held-out execution catalog against live Oracle at
temperature 0, with **11/25 controlled-error** accuracy — up from the adapter
alone (24/150, 16.0%) and the base model (8/150, 5.3%). See
`docs/reports/challenger-sql-only-rag.md` and `CHANGELOG.md`.

### Release history

| version | champion | held-out pass | controlled-error | notes |
|---|---|---|---|---|
| v1.0.0 | (dataset release) | — | — | original dataset + catalog v1.0.0 |
| v1.0.1 | sql_only-qlora | 16.0% | 6/25 | pipeline, eval, serving (follow-up) |
| v1.0.2 | **sql-only-rag** | **36.7%** | **11/25** | schema-context retrieval added |
| v1.0.3 | sql-only-rag | 36.7% | 11/25 | operational safety (disposable-schema guard, monitoring) |
| v1.0.4 | sql-only-rag | 36.7% | 11/25 | engineering/quality: read-only pilot, enriched index, regression, governance (champion unchanged) |
| v1.0.5 | sql-only-rag | 36.7% | 11/25 | compact-retrieval analysis (v3 compact RAG candidate, NOT promoted; champion unchanged) |
| v1.0.6 | sql-only-rag | 37.3% | 15/25 | sequence metadata (NEXTVAL fix) + benchmark governance deny-list; champion unchanged. Dev-benchmark metrics are for the sequence-enabled index. Acceptance-informed, validated on dev+regression only; blind-final decision deferred to an independently owned set. |
| v1.0.8 | sql-only-rag | (dev-benchmark, unchanged) | — | monitoring only: schema-detection-miss metric + tests; champion unchanged |

### Evaluation decision (2026-08-30, governance — not a model release)

The **Candidate A vs Candidate B** comparison has been recorded
(`docs/reports/eval-decision-A-vs-B-2026-08-30.md`): **Candidate A
(`sql-only-rag`) remains selected; Candidate B (`sql-only-errmix-rag`) is
rejected** and archived as a non-promoted experiment. This decision is based
on the development-side boundary only (frozen 150-task dev benchmark +
governance gate) and contains no private evaluation outcome. The deployed
adapter is unchanged.

Rollback target: **v1.0.1** (sql_only-qlora, no retrieval) is the tested
fallback — disabling `--schema-index` restores the pre-retrieval behavior with
zero weight change.

## Training

- Method: supervised fine-tuning (SFT), assistant-only loss masking (prompt
  tokens are `-100`).
- Variants: `chat`, `sql_only`, `error_repair` (trained separately; never
  implicitly mixed).
- Data: the frozen, versioned dataset at the repository root
  (`../oracle_train_chat.jsonl` etc.). Training files are validated and
  fingerprinted (SHA-256) before use.
- Guardrail: the held-out execution catalog `llm_task_catalog_eval.jsonl`
  (150 tasks) is NEVER used for training, prompt examples, or retrieval.
  It is used only for final recorded evaluation.

## Evaluation

- Offline: generation via a Transformers or OpenAI-compatible backend at
  `temperature=0`.
- Online: `evaluate_catalog.py` runs candidates against a live Oracle instance
  (resetting resettable schemas before each task) and records pass/executed-ok/
  checksum per task.
- Held-out execution accuracy is the primary selection metric, not validation
  loss.

## Intended users

Developers and DBAs who want a deterministic Oracle SQL/PLSQL assistant. For
`sql_only` mode the model is prompted to return only executable SQL/PLSQL.

## Limitations & risks

- The training set is small (160 chat / 160 code-only / 56 repair examples);
  the model is an adapter, not a foundation model. It is not a substitute for
  reviewing generated SQL against real schemas.
- Deterministic executable evaluation is only valid at `temperature=0` with
  SQL-only prompts.
- Database credentials are environment-driven; never bake them into model
  outputs, prompts, config, or logs.
- Generated SQL should be reviewed before execution on production systems.

## Safety

- No credentials, database dumps, or user data are committed to this
  repository.
- The pipeline fails closed if the held-out catalog is supplied to training.

## Provenance

Every run writes `provenance.json` (base revision, train files + hashes,
package versions, git revision, config, seed, timestamp) next to the adapter.
