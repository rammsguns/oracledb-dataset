# Oracle Database LLM

This directory is the implementation workspace for an Oracle SQL/PLSQL
assistant. It fine-tunes an existing instruction model; the source dataset is
far too small for training a foundation model from scratch.

## Architecture

```
dataset JSONL -> data preparation -> LoRA/QLoRA SFT -> adapter registry
                                                  |-> offline evaluation
                                                  |-> Oracle execution evaluation
adapter + base model -> OpenAI-compatible inference service -> client/API
```

Dataset files remain at the repository root and are referenced by relative
paths in `configs/`. Do not copy `llm_task_catalog_eval.jsonl` into any
training dataset, prompt set, or retrieval index.

## Directory guide

- `configs/` — versioned experiment, data, and serving configuration.
- `src/oracle_llm/data/` — validation, formatting, and split guards.
- `src/oracle_llm/training/` — SFT/LoRA training and adapter packaging.
- `src/oracle_llm/evaluation/` — generation and database-backed scoring.
- `src/oracle_llm/serving/` — inference API and prompt handling.
- `scripts/` — reproducible command-line entry points.
- `tests/` — unit, dataset-contract, and smoke tests.
- `docs/` — model card, operational runbook, and decision records.
- `artifacts/` — local, untracked model outputs, logs, and predictions.

Read [PLAN.md](PLAN.md) before implementing a phase.
Developers should follow the detailed [implementation instructions](docs/DEVELOPER_INSTRUCTIONS.md).
After model selection, use the [next-steps delivery plan](docs/NEXT_STEPS.md).

## Status

The pipeline (Phases 1–6) is implemented as a Python package `oracle_llm`
with a project-local CLI (`oracle-llm`) and thin `scripts/` entry points:

- **Data contract** (`src/oracle_llm/data/`) — loaders, validation,
  fingerprinting/manifests, prompt rendering with assistant-only loss masking,
  and a deny-list that fails closed on the held-out catalog.
- **Training** (`src/oracle_llm/training/`) — QLoRA/LoRA SFT CLI with the
  `chat`/`sql_only`/`error_repair` variants, pinned base-model revision,
  resumable checkpoints, and `provenance.json`/`model_card.json` metadata.
- **Evaluation** (`src/oracle_llm/evaluation/`) — candidate generation
  (endpoint or local Transformers) and machine-readable summarization of
  `evaluate_catalog.py` results (overall / executed-ok / exact-result /
  per-schema / per-kind / controlled-error).
- **Selection** (`src/oracle_llm/training/selection.py`) — promotion policy
  (gold harness, frozen-manifest hashes, reproducibility, held-out
  improvement, controlled-error no-regression).
- **Serving** (`src/oracle_llm/serving/`) — FastAPI OpenAI-compatible API with
  `/health` and `/v1/chat/completions`, `response_mode` `sql_only`/`explain`,
  request validation, and metadata/latency logging (no secrets/prompts).

### Quick start

```bash
# From LLM/ with the venv activated:
python -m oracle_llm.cli validate ../oracle_train_chat.jsonl     # Phase 1
python -m oracle_llm.cli train --config configs/training/qlora-7b.yaml \
    --output-dir artifacts/chat-qlora                           # Phase 2
python -m oracle_llm.cli evaluate artifacts/gold_results.jsonl   # Phase 3
python -m oracle_llm.cli serve --port 8000                       # Phase 5
```

See [docs/RUNBOOK.md](docs/RUNBOOK.md) for the full end-to-end procedure and
[docs/MODEL_CARD.md](docs/MODEL_CARD.md) + [docs/adr/](docs/adr/) for the
design decisions.
