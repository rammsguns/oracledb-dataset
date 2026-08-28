# Developer instructions: Oracle Database LLM

## Mission

Implement an Oracle Database assistant by fine-tuning an existing instruction
model with LoRA/QLoRA. Do **not** attempt to train a foundation model from
scratch: this dataset is designed for supervised adaptation and evaluation.

The deliverable is a reproducible pipeline that can:

1. validate and format the dataset;
2. train versioned LoRA adapters;
3. generate deterministic SQL/PLSQL candidates;
4. score them using the repository's live Oracle execution evaluator; and
5. serve the chosen adapter through a small API.

Read `../PLAN.md` and `../configs/data.yaml` before making changes.

## Non-negotiable rules

- Never train on, derive synthetic records from, index, or include in prompts
  `../../llm_task_catalog_eval.jsonl`. It is the 150-task held-out execution
  benchmark.
- Use `../../oracle_eval_holdout.jsonl` only for validation loss / early
  stopping; it is not training data.
- Do not commit passwords, DSNs containing passwords, `.env` files, database
  dumps, model weights, adapter checkpoints, generated candidates, or logs
  containing user/database content. Keep outputs in `../artifacts/`.
- Read DB credentials only from environment variables. Never print them.
- Do not modify the root dataset JSONL files. New derived datasets must carry
  input hashes, generation code version, and a declared split policy.
- For executable evaluation, use `temperature=0` and request SQL/PLSQL only.
- Do not claim model improvement until `evaluate_catalog.py` has evaluated the
  adapter on the unchanged held-out catalog.

## Existing resources

| Resource | Purpose |
|---|---|
| `../../oracle_train_chat.jsonl` | 160 full-answer chat SFT examples |
| `../../oracle_train_code_only.jsonl` | 160 SQL/PLSQL-only SFT examples |
| `../../oracle_train_error_repair.jsonl` | 56 Oracle error diagnosis/repair examples |
| `../../oracle_eval_holdout.jsonl` | 18-record validation holdout |
| `../../llm_task_catalog_train.jsonl` | training-side verified task catalog; do not automatically mix into SFT |
| `../../llm_task_catalog_eval.jsonl` | execution benchmark; strictly held out |
| `../../generate_answers.py` | OpenAI-compatible candidate generator |
| `../../evaluate_catalog.py` | live Oracle execution evaluator |
| `../../reset_lab_schemas.py` | restores the resettable lab schemas |
| `../../finetune_oracle.py` | initial LoRA SFT entrypoint |

The local Oracle container is `oracle23ai_dataset`, exposes port 1521, and was
confirmed healthy. Treat it as shared state: evaluation must use the reset
harness and leave resettable schemas pristine.

## Required implementation order

### 1. Dataset contract (`src/oracle_llm/data/`)

Implement a loader/validator with commands under `scripts/`.

- Accept chat and instruction-triplet JSONL formats.
- Validate mandatory keys and roles, UTF-8, nonempty target answers, and
  duplicate records.
- Compute SHA-256 for each input and persist a JSON data manifest next to each
  experiment artifact.
- Enforce a deny-list for `llm_task_catalog_eval.jsonl`; fail closed if it is
  supplied to a training or indexing command.
- Render prompts using the base tokenizer's chat template. Mask loss on prompt
  tokens, retaining loss only on assistant tokens.

Acceptance: a unit test validates all train files, rejects a malformed row,
and rejects the held-out catalog as training input.

### 2. Training (`src/oracle_llm/training/`)

Refactor or extend `../../finetune_oracle.py` behind a project-local CLI.

- Use PEFT LoRA; support 4-bit QLoRA on CUDA and normal LoRA when not using
  quantization.
- Require explicit base model revision, random seed, config file, and output
  directory.
- Save adapter, tokenizer, resolved config, package versions, git revision if
  available, input hashes, training metrics, and model card metadata.
- Support three explicit variants: `chat`, `sql_only`, and `error_repair`.
- Do not mix variants implicitly. Any mixture needs a config listing sources
  and weights.
- Add resumable checkpoints; store them only under `artifacts/`.

Acceptance: `--help` works without a GPU; a tiny local model smoke test can
complete one training step; artifact metadata is produced.

### 3. Offline generation and evaluation (`src/oracle_llm/evaluation/`)

- Implement adapter-aware generation via an OpenAI-compatible endpoint or a
  direct Transformers backend.
- Write candidates as JSONL `{id, answer}` without overwriting an existing
  result unless `--overwrite` is explicitly supplied.
- Preserve evaluator output in a timestamped experiment directory.
- Execute `../../evaluate_catalog.py` against the unchanged held-out catalog.
- Summarize overall pass rate, executed-ok rate, exact result/checksum rate,
  per-schema rate, per-kind rate, and controlled-error rate.
- Include the base-model baseline and gold-harness run in every comparison.

Acceptance: gold candidates yield the documented 150/150 pass result; a
deliberately broken candidate scores below gold; reports are machine-readable.

### 4. Selection policy

Implement a promotion command or document that records a model as `candidate`
or `promoted` only when all conditions hold:

- the gold harness succeeds;
- dataset hashes match the frozen manifest;
- the run is reproducible from its config and base-model revision;
- no held-out-data violation occurred; and
- held-out execution accuracy improves on the selected base baseline, with no
  material regression in controlled-error accuracy.

Do not choose by validation loss alone.

### 5. Serving (`src/oracle_llm/serving/`)

Implement a minimal FastAPI service only after a model is selected.

- `GET /health` returns model ID, adapter version, and readiness—never secrets.
- `POST /v1/chat/completions` accepts OpenAI-style messages.
- Add `response_mode` values `sql_only` and `explain`.
- `sql_only` applies the SQL-only system prompt and default temperature 0.
- Validate request length and return clear 4xx errors for invalid requests.
- Log request metadata and latency, but not credentials or full SQL prompts by
  default.

Acceptance: a smoke test starts the API with a local stub/tiny model and
verifies health and a valid completion response.

## First experiment to execute

Use the exact config in `../configs/training/qlora-7b.yaml`, after pinning a
specific base model revision. Train the chat variant first; then separately
train the code-only variant. Evaluate each against the same held-out catalog.

Run these commands from the `LLM/` directory (adapt only model revision and
artifact path):

```bash
# Reset/verify the live schemas before database-backed work.
python ../reset_lab_schemas.py --verify

# Baseline; do this before fine-tuning.
python ../generate_answers.py \
  --catalog ../llm_task_catalog_eval.jsonl --mode model \
  --base-url http://MODEL_ENDPOINT/v1 --model BASE_MODEL \
  --out ../artifacts/baseline/candidates.jsonl
python ../evaluate_catalog.py \
  --catalog ../llm_task_catalog_eval.jsonl \
  --candidate ../artifacts/baseline/candidates.jsonl

# Train by invoking the project-local training CLI once implemented.
# python scripts/train.py --config configs/training/qlora-7b.yaml
```

## Definition of done

The project is complete for v1 only when a new developer can clone the repo,
provide environment-only database credentials and a base-model location, run
the documented pipeline, reproduce an adapter and its reports, and serve the
promoted adapter—without accessing the held-out catalog during training.
