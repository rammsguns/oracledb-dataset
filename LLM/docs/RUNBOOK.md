# Operational Runbook — Oracle Database LLM

This runbook covers the reproducible pipeline in `LLM/`. All commands are run
from the `LLM/` directory unless noted. Database credentials come ONLY from
environment variables (see the repo README).

## 1. Environment setup

```bash
cd LLM
python3 -m venv .venv
# Install PyTorch appropriate for your CUDA first, then:
uv pip install --python .venv/bin/python -e .
uv pip install --python .venv/bin/python pytest
```

Verify the frozen dataset hashes match `../MANIFEST.md`:

```bash
sha256sum ../oracle_train_chat.jsonl ../oracle_train_code_only.jsonl \
  ../oracle_train_error_repair.jsonl ../oracle_eval_holdout.jsonl \
  ../llm_task_catalog_eval.jsonl
```

## 2. Data validation (Phase 1)

```bash
python -m oracle_llm.cli validate ../oracle_train_chat.jsonl \
  ../oracle_train_code_only.jsonl ../oracle_train_error_repair.jsonl \
  --manifest artifacts/manifest_train.json
python -m oracle_llm.cli validate ../oracle_eval_holdout.jsonl
# The held-out catalog MUST be rejected (fail closed):
python -m oracle_llm.cli validate ../llm_task_catalog_eval.jsonl   # exits non-zero
```

## 3. Reset / verify live schemas (before DB-backed work)

```bash
python ../reset_lab_schemas.py --verify
```

## 4. Baseline (Phase 0) — do this before fine-tuning

```bash
mkdir -p artifacts/baseline
python ../generate_answers.py --catalog ../llm_task_catalog_eval.jsonl \
  --mode model --base-url <OPENAI_COMPAT_ENDPOINT> --model <BASE_MODEL> \
  --out artifacts/baseline/candidates.jsonl
python ../evaluate_catalog.py --catalog ../llm_task_catalog_eval.jsonl \
  --candidate artifacts/baseline/candidates.jsonl \
  --out artifacts/baseline/results.jsonl
python -m oracle_llm.cli evaluate artifacts/baseline/results.jsonl
```

Gold harness sanity (should be 150/150):

```bash
python ../generate_answers.py --catalog ../llm_task_catalog_eval.jsonl \
  --mode gold --out artifacts/gold_candidates.jsonl
python ../evaluate_catalog.py --catalog ../llm_task_catalog_eval.jsonl \
  --candidate artifacts/gold_candidates.jsonl --out artifacts/gold_results.jsonl
python -m oracle_llm.cli evaluate artifacts/gold_results.jsonl
```

## 5. Train (Phase 2)

```bash
python -m oracle_llm.cli train --config configs/training/qlora-7b.yaml \
  --output-dir artifacts/chat-qlora
```

`--help` works without a GPU. QLoRA (`load_in_4bit: true`) requires a CUDA GPU.
A tiny-model smoke test can validate the loop without a big GPU.

Artifacts written to the output dir:
`adapter_model.safetensors`, tokenizer files, `config.json`,
`provenance.json`, `model_card.json`, and resumable checkpoints.

## 6. Generate + evaluate candidates (Phase 3)

From an endpoint (the served adapter) or a local model+adapter:

```bash
python -m oracle_llm.cli generate --catalog ../llm_task_catalog_eval.jsonl \
  --backend endpoint --base-url http://localhost:8000/v1 --model oracle-assistant \
  --out artifacts/chat-qlora/candidates.jsonl
python ../evaluate_catalog.py --catalog ../llm_task_catalog_eval.jsonl \
  --candidate artifacts/chat-qlora/candidates.jsonl \
  --out artifacts/chat-qlora/results.jsonl
python -m oracle_llm.cli evaluate artifacts/chat-qlora/results.jsonl \
  artifacts/baseline/results.jsonl artifacts/gold_results.jsonl \
  --out artifacts/comparison.json
```

## 7. Selection / promotion (Phase 4)

Promotion requires: gold harness OK, dataset hashes match the frozen manifest,
reproducible config + base revision, no held-out-data violation, held-out
accuracy improves on baseline, no material controlled-error regression.

```bash
python -m oracle_llm.cli promote \
  --run-metadata artifacts/chat-qlora/provenance.json \
  --results artifacts/chat-qlora/results.jsonl \
  --gold-results artifacts/gold_results.jsonl \
  --baseline-results artifacts/baseline/results.jsonl \
  --manifest ../MANIFEST.md \
  --out artifacts/promotion.json
```

## 8. Serve (Phase 5)

```bash
python -m oracle_llm.cli serve --host 0.0.0.0 --port 8000 \
  --model-id oracle-assistant --adapter-version <run-version> \
  --base-model Qwen/Qwen2.5-Coder-7B-Instruct --adapter artifacts/sql-only-qlora
```

Smoke test:

```bash
curl -s localhost:8000/health
curl -s localhost:8000/metrics
curl -s localhost:8000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"oracle-assistant","messages":[{"role":"user","content":"count orders"}],"response_mode":"sql_only"}'
```

A real deployment sets a `generate` backend that loads the base model + adapter.

### Production hardening (Phase 5)

- **Request-size limit**: bodies over `MAX_BODY_BYTES` (2 MiB) are rejected with
  413; per-message length cap (200k chars) returns 400.
- **Rate limiting**: token-bucket limiter (default 10 req/s, burst 20); excess
  requests return 429.
- **Request IDs**: every completion is logged with a `request_id` for
  correlation.
- **Structured metrics**: `GET /metrics` returns uptime, request/error counts,
  error rate, mode split, and average latency. Credentials and full SQL prompts
  are never logged.
- **Security**: SQL generation is separate from SQL execution — the service
  NEVER executes generated SQL with production DB credentials. Put the API
  behind authentication/authorization before exposing outside a trusted
  network (not wired in by default).
- **sql_only Markdown guard**: a fenced (` ``` `) response in sql_only mode is
  rejected with 422.

## 9. Rollback

- Adapters are versioned by their artifact directory and immutable
  `provenance.json`; keep old adapter dirs. To roll back, point serving at a
  previously promoted adapter and restart the service.
- The base-model revision is pinned in the config, so a prior run is
  reproducible from `config` + `provenance.json`.
- Database schemas are resettable to pristine state at any time via
  `reset_lab_schemas.py`.

## 10. Monitoring

- `/health` exposes model id, adapter version, and readiness (no secrets).
- Request metadata (model, mode, message count, user word count) and latency
  are logged per request; credentials and full SQL prompts are NOT logged by
  default.
- Evaluation reports are machine-readable JSON (see `scripts/evaluate.py`)
  and should be saved per run under `artifacts/`.

## Definition of done (v1)

A new developer can clone the repo, provide environment-only DB credentials
and a base-model location, run the documented pipeline, reproduce an adapter
and its reports, and serve the promoted adapter — without accessing the
held-out catalog during training.
