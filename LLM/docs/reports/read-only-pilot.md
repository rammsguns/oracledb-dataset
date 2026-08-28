# S1 — Staged read-only pilot

Date: 2026-08-28
Status: implemented + smoke-verified

## Goal

Run a controlled pilot that generates **read-only SQL only**, collects
opt-in feedback, and monitors retrieval-miss rate, Oracle error categories,
latency, and refusal rate — without ever executing generated SQL against
non-resettable schemas.

## What was built

- **`--read-only` serving flag** (`oracle-llm serve --read-only`): in
  `sql_only` mode the service refuses (422) any request that asks for
  DML/DDL (INSERT/UPDATE/DELETE/MERGE/ALTER/DROP/CREATE/TRUNCATE/GRANT) via
  `_asks_for_write`. `explain` mode is unaffected. Fail-closed toward SELECT.
- **Pilot metrics** (`GET /metrics`): added `refusals` + `refusal_rate`
  alongside the existing `retrieval_misses`, `retrieval_miss_rate`,
  `avg_latency_ms`, `oracle_error_categories`, and `error_rate`.
- **Refusal logging**: each refused request logs its `request_id` and reason
  (metadata only — no SQL body, no credentials).

## Smoke test (live, sql_only-rag adapter + approved schema index)

| request | result |
|---|---|
| "Show orders and their customers in SALES_LAB" (SELECT) | **200**, returned valid SQL |
| "insert a new order into SALES_LAB" (DML) | **422**, refused by read-only pilot |
| `GET /metrics` | `refusals: 1, refusal_rate: 50.0, avg_latency_ms: 4431, retrieval_miss_rate: 0.0` |

## Feedback capture (operational note)

The API returns machine-readable completions; opt-in human feedback should be
collected by the caller (e.g. a thumbs-up/down on the returned SQL) and stored
outside the service. It is not stored by the HTTP layer by design.

## Tests

`tests/test_safety.py` adds 3 read-only pilot tests (keyword detection,
DML refusal + refusal-rate metric, explain-mode unaffected). Full suite: 49
passed.

## Monitoring guidance

- Alert on refusal_rate spikes (users asking for writes the pilot rejects).
- Alert on retrieval_miss_rate spikes (schema context not resolving).
- Track avg_latency_ms; watch the ORA-00942 / object-not-found bucket in
  oracle_error_categories from the execution harness.
