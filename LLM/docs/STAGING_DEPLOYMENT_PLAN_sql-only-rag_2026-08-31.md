# Staging Deployment Plan — sql-only-rag (LEARNING-ONLY, 2026-08-31)

**Status:** DRAFT — learning-only planning document. **No deploy, no commit,
no push, no retrain, no benchmark, no model-selection change.**
**Scope:** a staged, generation-only deployment of the retained champion
**sql-only-rag** for operational validation only. It must never execute
generated SQL inside the serving process.

This plan is written to be reviewable and exercisable as a dry run. All
artifacts stay local and uncommitted.

---

## 1. System definition (fixed)

| item | value |
|---|---|
| Model | **sql-only-rag** (retained champion) |
| Base model | `Qwen/Qwen2.5-Coder-7B-Instruct` (pinned `c03e6d...`) |
| Adapter | approved `sql-only-qlora` (LoRA) |
| Retrieval | whole-schema DDL injection **with sequence metadata** |
| Ranked retrieval | **OFF** (never pass `--ranked` / v4 ranking) |
| Decoding | temperature 0, `max_new_tokens=1024` |
| Schema index | evaluator-owned / approved lab-schema index (no CLINIC_LAB, FIN_LAB, private final set) |
| Database creds | environment-only (`ORACLE_LAB_PW_<SCHEMA>`); never in files/logs |

## 2. Architecture / safety boundary (non-negotiable)

- **Generation-only API.** The serving process calls
  `TransformersBackend.generate(...)` which returns text. It performs **no**
  DDL/DML and opens **no** database connection. SQL **execution** is an
  entirely separate, manually-invoked action (e.g. the reset harness /
  `evaluate_catalog.py`) outside this service.
- **No write path.** Even in `sql_only` mode the service only *produces* SQL;
  it never runs it. Optionally run the staged `--read-only` pilot to refuse
  DML/DDL requests (422) as an extra guard.
- **No secrets in logs.** Log lines carry `request_id`, `mode`, `user_words`,
  `latency_ms`, `retrieval_miss` — never the prompt, generated SQL, or
  credentials. Verify no SQL/prompt/secret reaches stdout/stderr.

## 3. Monitoring metric (implemented in v1.0.8)

**Schema-detection-miss metric — DONE (release/llm-v1.0.8).** The
observability gap found during application validation is fixed:
`retrieve()` now returns a machine-readable `state` distinguishing
`injected` (schema detected + DDL injected), `miss` (schema detected but no
DDL), and `not_detected` (no known schema detected). `schema_detection_misses`
and `schema_detection_miss_rate` are exposed in `/metrics` and in the
completion log line. Legacy `retrieval_misses` semantics are preserved.
No code change is required before deploying this plan; simply deploy v1.0.8
(or later) and these counters are available.

## 4. Health checks

- `GET /health` → `200` with `status=ok`, `ready=true`, `adapter_version` of
  the **selected** config (assert it is the champion, not Candidate B).
- Liveness: TCP connect to the serving port succeeds.
- Readiness: `ready=true` implies the model backend is loaded.
- **GPU health:** `nvidia-smi` shows model on CUDA device with expected
  memory (~14–16 GiB for bf16 Qwen 7B), not spilling to CPU.
- Synthetic probe: a known-good, ordinary SQL-only prompt returns `200` and a
  non-empty SQL response without Markdown fences.

## 5. Resource limits

- `MAX_CHARS_PER_MESSAGE` and `MAX_MESSAGES` body caps (already enforced by
  the app; returns 400/413).
- `max_new_tokens=1024` cap per generation (avoids runaway decode).
- Rate limit via the app's token bucket (429 on burst); tune `rate_limit` /
  `rate_burst` in config.
- CUDA memory headroom: model + adapter must fit the target GPU with margin;
  use `device_map="auto"` with `torch.bfloat16` on CUDA.

## 6. Monitoring thresholds

| metric | healthy | alert |
|---|---|---|
| `error_rate` | 0.0 | > 0.02 (2%) over window |
| `refusal_rate` | 0.0 (or low) | spike beyond expected in read-only pilot |
| `retrieval_miss_rate` | near 0 | rising — check index coverage |
| `schema_detection_miss_rate` (new) | near 0 | rising — check schema token coverage / prompt wording |
| `avg_latency_ms` | < deployment budget | sustained > 3–5 s suggests CPU spill or saturation |
| GPU memory | within limit | OOM → auto-restart, alert |
| `sql_only` Markdown-fence rejections | 0 | > 0 → prompt/decode regression |

## 7. Rollback to previous serving configuration

- **Primary:** point `--adapter` back to the **prior** serving config and
  restart. For this system the tested rollback target is **v1.0.1**
  (`sql_only-qlora`, no retrieval) — serve without `--schema-index`. This is a
  pure adapter/config swap; zero weight change to the base model.
- **Mechanic:** keep the previous adapter dir + `provenance.json`/`config.json`
  retained (already done under `artifacts/`). Restart the service with the old
  `--adapter` and (if rolling back retrieval) without `--schema-index`.
- **Verify:** `/health` reports the prior `adapter_version`; a synthetic
  sql_only completion works.

## 8. Startup / shutdown / smoke / rollback commands (all from `LLM/`)

**Startup (CUDA, generation-only, champion + whole-schema+sequence index):**
```bash
export ORACLE_LAB_PW_SALES_LAB=...   # environment-only, if DB access needed downstream
PYTHONPATH=src python scripts/serve.py \
  --host 127.0.0.1 --port 8000 \
  --model-id oracle-assistant --adapter-version sql-only-rag-v1.0.2 \
  --base-model Qwen/Qwen2.5-Coder-7B-Instruct \
  --adapter ../artifacts/sql-only-qlora \
  --schema-index ../artifacts/schema_index_v2_dev.json \
  --max-new-tokens 1024
```

**Health / smoke:**
```bash
curl -s http://127.0.0.1:8000/health
curl -s http://127.0.0.1:8000/metrics
curl -s -X POST http://127.0.0.1:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"oracle-assistant","messages":[{"role":"user","content":"Count sales orders in SALES_LAB.\n\nTarget schema: SALES_LAB."}],"response_mode":"sql_only"}'
```

**Shutdown (graceful):**
```bash
# Ctrl+C on the foreground process, or:
pkill -TERM -f "scripts/serve.py --port 8000"
# confirm release:
nvidia-smi --query-gpu=memory.used --format=csv,noheader   # expect ~0 used
ss -tln | grep ':8000' || echo "port free"
```

**Rollback to v1.0.1 (no retrieval):**
```bash
PYTHONPATH=src python scripts/serve.py \
  --host 127.0.0.1 --port 8000 \
  --model-id oracle-assistant --adapter-version sql-only-qlora-v1.0.1 \
  --base-model Qwen/Qwen2.5-Coder-7B-Instruct \
  --adapter ../artifacts/sql-only-qlora \
  --max-new-tokens 1024
```

## 9. Constraints honored

- No CLINIC_LAB, FIN_LAB, or private final set used or referenced.
- No retraining, no benchmark run, no model-selection change, no deploy, no
  commit, no push.
- Credentials environment-only; logs free of prompts, SQL, and secrets.

## 10. Acceptance checklist (for the eventual reviewer)

- [ ] Generation-only confirmed: service holds no DB connection; no SQL execution in-process.
- [ ] `/health` shows champion `adapter_version`, `ready=true`.
- [ ] sql_only returns non-Markdown SQL; explain returns prose.
- [ ] Invalid input → 400/413; over-limit burst → 429.
- [ ] Metrics expose `error_rate`, `refusal_rate`, `retrieval_miss_rate`,
      **new `schema_detection_miss_rate`**, latency, GPU.
- [ ] Logs contain request_id/mode/latency/miss — no prompt, SQL, or secret.
- [ ] CUDA: model on GPU (bf16), memory within limit, `max_new_tokens=1024`.
- [ ] Rollback to v1.0.1 verified (adapter swap + no `--schema-index`).
- [ ] Shutdown frees the GPU and the port.
