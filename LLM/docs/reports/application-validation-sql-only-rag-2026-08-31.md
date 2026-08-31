# Application-Level Validation — sql-only-rag (2026-08-31)

**Status:** COMPLETE (local, uncommitted journal)
**Type:** application-level operational validation of the selected system —
**not** a promotion benchmark, no model/training change.

## 1. Git baseline
- `origin/main` at `d2fc471525bfc2ffa474e86ba45b036fb30a4e49`
  (governance/evaluation merge of release/llm-v1.0.7; sql-only-rag retained).
- Validated from a **pristine temporary worktree** at that commit; worktree
  removed afterward.

## 2. Selected system
- **sql-only-rag** — the retained champion. **sql-only-errmix-rag (Candidate B)
  remains non-promoted.**

## 3. Validation type, commands, configuration
- **Type:** application-level smoke validation with ordinary, new operational
  prompts only. No frozen set (private final / CLINIC_LAB / FIN_LAB) was used
  or requested.
- **Serving command** (from the pristine worktree `LLM/`):
  ```
  python scripts/serve.py --host 127.0.0.1 --port 8900 \
    --model-id oracle-assistant --adapter-version sql-only-rag-v1.0.2 \
    --base-model Qwen/Qwen2.5-Coder-7B-Instruct \
    --adapter <approved sql-only-qlora adapter> \
    --schema-index <schema_index_v2_dev.json> \
    --max-new-tokens 256
  ```
- **Configuration:** approved adapter; whole-schema retrieval with sequence
  metadata; **ranked retrieval disabled** (no `--ranked`); temperature 0.
- **Exercised:** `/health`, `/v1/chat/completions` (sql_only + explain),
  `/metrics`, plus direct invalid-input checks.

## 4. Results

| check | result |
|---|---|
| Health | 200; `status=ok`, `model_id=oracle-assistant`, `adapter_version=sql-only-rag-v1.0.2`, `ready=true`; no secrets |
| sql_only mode | 200; returns executable SQL; no Markdown fences |
| explain mode | 200; coherent prose |
| Input guards | empty messages → 400; invalid role → 400; invalid `response_mode` → 400 |
| Metrics | `requests=7, errors=0, error_rate=0.0, sql_only=6, explain=1, avg_latency_ms≈5005, refusals=0, oracle_error_categories={}` |
| Retrieval monitoring | `retrieval_misses=0, retrieval_miss_rate=0.0`; **note:** see risks — un-hinted queries show schema-detection misses not counted here |
| Generation/execution separation | Serving only *generates* SQL; SQL execution remains separately gated (never executed by the service) |
| Latency / GPU | First request ~10 s (model warm-up), subsequent ~0.5–4.5 s (CPU-bound in this dev env); after shutdown GPU fully released (1 MiB / 16376 MiB used) |
| Rollback | Verified in the prior release-validation stage: v1.0.1 path (`sql_only-qlora`, no retrieval) — `/health` reports prior adapter and a sql_only completion works |

**Operational prompt outcomes (ordinary, non-private):**
- Join query on SALES_LAB → correct join of `llm_sales_orders` and
  `llm_sales_regions`.
- Explicit DOCUMENTS_LAB query → correct table + columns.
- Safe DML (SALES_LAB insert) → correct statement using `llm_sales_order_seq.NEXTVAL`
  (confirms sequence metadata is effective).
- Two un-hinted queries → schema-detection misses (guessed object names /
  system view instead of the intended lab table). See risks.

## 5. Tests and security scans
- Pristine test suite: **54 passed, 2 skipped** (skips = artifact-dependent CI
  guards) against the merged tree and the pristine worktree.
- Secret/private-content scan: **clean** — no credentials, private eval
  content, wallets, artifacts, or weights.
- This journal contains no credentials, private evaluation content, private
  model outputs, wallets, artifacts, or weights.

## 6. Limitations / operational risks
1. **Schema-detection misses on un-hinted or loosely-hinted prompts** — the
   model can guess object names or a system view when the target schema is not
   identified; these misses are not surfaced by the current `retrieval_misses`
   metric (which counts index-level misses, not detection-level misses). A
   separate detection-miss counter is recommended.
2. **CPU-bound latency** — ~0.5–4.5 s steady-state, ~5 s average on this dev
   box; not suitable for interactive production on CPU. A CUDA GPU (e.g. the
   available 16 GiB card) is the intended deployment target.
3. **`max_new_tokens=256`** used for this smoke pass; the production default is
   `1024` — longer generated SQL was not exercised here.
4. Single-seed, single-adapter validation; these are application-level
   observations, not a promotion benchmark.

## 7. Cleanup confirmation
- Server(s) **stopped**; serving process exited cleanly.
- Serving ports **free** (8900, 8800, 8801, 8000, 8010, 8011 all clear).
- **GPU resources released** (1 MiB / 16376 MiB used after shutdown).
- Temporary worktree and scratch prompt script removed; no serving processes
  remain.
