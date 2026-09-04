# Staging Deployment Report — sql-only-rag (2026-08-31)

**Status:** DEPLOYED AND RUNNING (learning-only staging)
**Decision:** Keep staging running — all acceptance checks passed.

## Process / port
- Process PID: `454264` (python `scripts/serve.py`), listening on
  `127.0.0.1:8920`
- Serving process environment **scrubbed**: no Oracle credentials/wallet/DSN
  vars. Generation-only — no DB connection, no SQL-execution path.
- Deploy source: pristine worktree at `/tmp/staging_deploy` (origin/main
  `2cdf99de5d352244fe6dc15eb6053e868ad7ace1`).

## Commit and hashes
- Deploy base commit: `2cdf99de5d352244fe6dc15eb6053e868ad7ace1` (origin/main)
- Adapter `artifacts/sql-only-qlora`:
  - adapter_model.safetensors sha256
    `28281125e88ab3e5c4b8a4591fa23ea2af00b9c54362701f4590d8d7201b3ea8`
  - adapter_config.json sha256
    `96d6816445bae56fe0d15669c849b090afa55cc315300607c52f23ce0dfdd7c8`
- Schema index `artifacts/schema_index_v2_dev.json` sha256
  `eb2da5929ea5344af92bf15093ca3c967da74083095ee6ee2f031a11cc92fc5e`
  (schemas: SALES/DOCUMENTS/OPS/LOGISTICS/SUPPORT_LAB only; sequence metadata
  present; no CLINIC/FIN/ANGEL/IEO)

## Checks (all PASS)
- `/health`: `status=ok, adapter_version=sql-only-rag-v1.0.8, ready=true`
- sql_only: returns executable SQL, no Markdown fences
- explain: returns prose (200)
- Input-size guard: oversized body -> 400
- Malformed requests: empty messages -> 400, bad role -> 400, bad mode -> 400
- Rate limit: within-burst requests allowed (200); 429-on-burst-exceed covered
  by unit test `test_rate_limit` (pristine suite passes)
- `/metrics`: exposes retrieval_misses, schema_detection_misses +
  rate, error_rate, refusal_rate, avg_latency_ms, mode counters
- Schema-detection-miss behavior:
  - recognized-schema request -> schema_detection_misses **unchanged**
  - unrecognized-schema request -> schema_detection_misses **+1**
- Logs: metadata-only (uvicorn access + completion metadata); **no** prompt,
  generated SQL, DDL, secrets, or credentials
- No Oracle connection from serving process (only outbound = HF Hub model
  download on first load; listens only on its own port)

## Metrics snapshot (during validation, instance 1)
```
requests=4 errors=0 error_rate=0.0 sql_only=3 explain=1
avg_latency_ms=6573.4 retrieval_misses=0 retrieval_miss_rate=0.0
schema_detection_misses=1 schema_detection_miss_rate=33.33
refusals=0 refusal_rate=0.0 oracle_error_categories={}
```
(Note: this is the pre-rollback validation instance. The restored instance
starts its own counters.)

## Latency / GPU observations
- GPU memory: serving process uses **~8,630 MiB** (bf16 Qwen 7B + adapter) on
  the 16 GiB card.
- Warm latency (sql_only, recognized schema): **~2.8 s avg** (range
  2.75–3.04 s). Cold/load latency ~10 s first request.

## Rollback result (PASS)
- Stopped sql-only-rag staging.
- Started documented prior config (v1.0.1: `sql-only-qlora`, no schema-index)
  on port 8921.
- `/health` reported `adapter_version=sql-only-qlora-v1.0.1, ready=true`;
  one sql_only completion returned SQL (200).
- Stopped rollback server; **restored sql-only-rag staging** on port 8920
  (health + completion confirmed).

## Initial learning alerts (configured)
- Credential/private-data log finding -> IMMEDIATE SHUTDOWN
- SQL-execution capability in serving -> IMMEDIATE SHUTDOWN
- schema_detection_miss_rate > 5% over >=20 requests -> warning
- HTTP error_rate > 5% over >=20 requests -> warning
- GPU OOM / repeated CUDA failure -> rollback/shutdown

## Risks
1. GPU headroom: ~8.6/16 GiB used. Comfortable, but a second concurrent load or
   larger batch could approach the limit; watch for OOM.
2. Detection-miss alert threshold not yet wired to a real alerting backend
   (recorded as rules only for this learning staging).
3. CPU-bound first-load latency (~10 s); warm ~2.8 s on this host.
4. Serving process environment must be scrubbed on every restart (credentials
   are in the parent shell's environment).

## Shutdown command
```bash
# Stop sql-only-rag staging (port 8920):
pkill -TERM -f "scripts/serve.py.*--port 8920"
# Verify release:
ss -tln | grep ':8920' || echo "port free"
nvidia-smi --query-gpu=memory.used --format=csv,noheader   # expect ~0 after process exits
```
Or, via the process helper used here: kill background process `proc_7113addb554e`
(PID 454264).
