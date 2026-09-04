# Staging Soak Test Report — sql-only-rag (2026-08-31)

**Status:** STAGING ACCEPTED — single staging instance left running.
**Instance:** PID `454264`, `127.0.0.1:8920`, adapter `sql-only-rag-v1.0.8`.

## Commit / adapter / hashes
- Deploy base commit: `2cdf99de5d352244fe6dc15eb6053e868ad7ace1` (origin/main)
- Adapter: `artifacts/sql-only-qlora` (Candidate A, `sql-only-rag`),
  version `sql-only-rag-v1.0.8`
  - adapter_model.safetensors sha256
    `28281125e88ab3e5c4b8a4591fa23ea2af00b9c54362701f4590d8d7201b3ea8`
  - adapter_config.json sha256
    `96d6816445bae56fe0d15669c849b090afa55cc315300607c52f23ce0dfdd7c8`
- Schema index `artifacts/schema_index_v2_dev.json` sha256
  `eb2da5929ea5344af92bf15093ca3c967da74083095ee6ee2f031a11cc92fc5e`
  (approved lab schemas only: SALES/DOCUMENTS/OPS/LOGISTICS/SUPPORT_LAB)

## Soak composition (20 requests, synthetic prompts only)
- 14 recognized-schema `sql_only`
- 2 recognized-schema `explain`
- 2 deliberately unrecognized-schema probes (`QUANTUM_CATALOG`, `ASTRO_METRICS`)
- 1 malformed-request guard (empty messages)
- 1 size-limit guard (~200 KB body)

No training, development-benchmark, frozen, or private-evaluation content was
used. Generated SQL was NOT executed and NOT retained or printed.

## Acceptance results
- **18 valid requests all returned 200.** (14 sql_only + 2 explain + 2 probes)
- **Guards:** malformed -> 400, size-limit -> 400. Both are expected client
  rejections, distinguished from server errors (`errors=0`, `error_rate=0.0`).
- **Detection misses:** baseline 0 -> after 2. Exactly the 2 deliberate
  unrecognized probes incremented `schema_detection_misses`. Recognized
  requests (16) did NOT increment it.
- **Retrieval misses:** 0 throughout (explainable: recognized schemas retrieved
  from index; unrecognized probes became detection misses, not retrieval
  misses — correct `not_detected` semantics).
- **Logs:** clean — no credentials, prompts, SQL, or DDL. Completion log is
  metadata-only (request_id, model, mode, message/user-word counts, latency,
  retrieval_miss, schema_detection_miss). Verified by code inspection
  (app.py:352-353) + observed uvicorn access log (path/status only).
- **No CUDA errors, no OOM, no duplicate processes, no restarts.**
  - Single `serve.py` process (PID 454264) confirmed.
  - Uptime monotonic (1217s pre-soak -> 1301.6s post-soak): no restart.
  - GPU peak 7049 MiB (well under 16 GiB; no OOM).

## Sanitized metrics (before -> after)
```
requests                    1 -> 19
errors                      0 -> 0
error_rate                  0.0 -> 0.0
sql_only                    1 -> 17
explain                     0 -> 2
avg_latency_ms              7979.4 -> 2139.7
retrieval_misses            0 -> 0
retrieval_miss_rate         0.0 -> 0.0
schema_detection_misses     0 -> 2
schema_detection_miss_rate  0.0 -> 11.76
refusals                    0 -> 0
refusal_rate                0.0 -> 0.0
```
(requests=19, not 20, because the two guard rejections are not counted as
completed generation requests.)

## Latency / GPU observations
- **p50 latency: 1707.6 ms**
- **p95 latency: 2869.7 ms** (18 valid requests)
- **GPU peak memory: 7049 MiB** / 16376 MiB (~43% of card)

## Detection-miss alert interpretation
Overall `schema_detection_miss_rate` = 11.76% (2/17 sql_only) — but this is
**inflated by the two deliberate unrecognized probes** and must NOT be read as
an operational alert.

Separating production-like traffic: the **16 recognized-schema requests
(14 sql_only + 2 explain) produced 0 detection misses** -> production-like
detection-miss rate = **0.0%**, well under the 5% alert threshold. The 11.76%
figure is entirely attributable to the two intentional probes. No misleading
operational alert; a monitoring backend should exclude known probe/user
synthetic schemas from the detection-miss alert.

## Rollback verification
Rollback was verified earlier this session (stop sql-only-rag staging -> start
documented prior config `sql-only-qlora-v1.0.1` on port 8921 -> health +
completion OK -> stop -> restore sql-only-rag staging on 8920). This soak did
not change that configuration.

## Remaining risks
1. GPU at ~43% (7.0/16 GiB) during soak; a heavier concurrent batch could raise
   memory — watch for OOM (alert configured).
2. Detection-miss alert threshold not yet wired to a real backend; ensure
   probe/synthetic schemas are excluded from operational alerting.
3. CPU-bound cold latency; warm p50 ~1.7s, p95 ~2.9s on this host.

## Shutdown command
```bash
pkill -TERM -f "scripts/serve.py.*--port 8920"
ss -tln | grep ':8920' || echo "port free"
nvidia-smi --query-gpu=memory.used --format=csv,noheader   # expect ~0
```

No commit, push, tag, merge, retrain, benchmark, or model-selection change.
