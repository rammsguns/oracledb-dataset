# Oracle LLM delivery plan

## Objective

Deliver a safe, measurable Oracle Database assistant that emits executable
Oracle SQL/PLSQL and can explain or repair database errors. Start from an
open instruction base model and produce a LoRA adapter, not a new foundation
model.

## Guardrails

- Train only on the declared training files: initially
  `../oracle_train_chat.jsonl`, `../oracle_train_code_only.jsonl`, and the
  optional error-repair training set.
- Keep `../oracle_eval_holdout.jsonl` for validation only.
- Keep `../llm_task_catalog_eval.jsonl` strictly held out: never train on it,
  generate synthetic variants from it, or place it in retrieval.
- Treat live Oracle evaluation credentials as environment variables; never
  place them in config, logs, or source control.
- Require zero temperature and SQL-only prompts for executable catalog scoring.

## Phases and acceptance criteria

| Phase | Deliverable | Exit criterion |
|---|---|---|
| 0. Baseline | model choice, hardware budget, baseline run | gold evaluator passes 150/150; baseline results recorded |
| 1. Data contract | loaders, schema validation, formatting | records validate; train/eval IDs have no overlap |
| 2. Training | reproducible QLoRA SFT experiment | adapter, tokenizer, config, seed, and metrics saved |
| 3. Evaluation | generation + execution evaluation | candidate answers scored against live Oracle; results segmented by schema/kind |
| 4. Selection | compare base, chat-SFT, code-SFT, repair-SFT | promote only the best model using held-out execution pass rate |
| 5. Serving | OpenAI-compatible inference API | health, request validation, SQL-only mode, structured logging work |
| 6. Operations | model card, rollback, monitoring | latency/error dashboards and a documented rollback tested |

## Experiment sequence

1. Measure the base model with `generate_answers.py` and the catalog evaluator.
2. Fine-tune the chat variant using `oracle_train_chat.jsonl`; use the small
   holdout only for training loss and early stopping.
3. Fine-tune the code-only variant using `oracle_train_code_only.jsonl`; do
   not use the prose holdout loss as its primary metric.
4. Fine-tune or mix the error-repair variant only after establishing a SQL
   baseline.
5. Run each selected adapter against the unchanged catalog evaluation set and
   compare overall pass rate, execution success, schema/kind breakdowns, and
   controlled-error accuracy.
6. Promote only a run with a recorded immutable base-model revision, dataset
   hashes, training configuration, and evaluation report.

## Decisions required before training

1. Base model family and license (suggestion: a current 7B/8B code-oriented
   instruct model that has a tokenizer chat template).
2. Deployment target: local GPU, single cloud GPU, or managed endpoint.
3. Target user experience: SQL-only generation, explanatory assistant, or
   both as separate modes.
4. Oracle environment available for execution evaluation and owner of its
   credentials.
