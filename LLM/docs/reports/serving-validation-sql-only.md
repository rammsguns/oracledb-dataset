# sql_only release-candidate serving validation

Date: 2026-08-28
Adapter: `sql-only-qlora` (selected), base `Qwen/Qwen2.5-Coder-7B-Instruct`
(revision `c03e6d35...`), served via `scripts/serve.py` /
`python -m oracle_llm.cli serve` on `127.0.0.1:8767`.

## Results

| check | result |
|---|---|
| `GET /health` | `{"status":"ok","model_id":"oracle-assistant","adapter_version":"sql-only-qlora-v1","ready":true}` |
| `POST /v1/chat/completions`, `response_mode=sql_only` | returned code only, no Markdown fences |
| `POST /v1/chat/completions`, `response_mode=explain` | returned code + prose explanation |
| Cold-start (first request, model load) | ~8.9 s |
| Warm request latency | ~1.4 s |
| GPU memory while serving | ~6.8–8.5 GiB per GPU (dual RTX A4000) |
| Logging | request metadata (model, mode, message count, user word count, latency) only; no SQL prompt body, no credentials |

## Notes

- `sql_only` mode enforces the SQL-only system prompt and default temperature 0.
- Markdown-fence rejection is enforced by a regression test
  (`tests/test_eval_serve.py::test_sql_only_no_markdown_fences`).
- The served adapter is the exact selected `sql-only-qlora` adapter (base model
  revision + adapter path supplied at startup).
