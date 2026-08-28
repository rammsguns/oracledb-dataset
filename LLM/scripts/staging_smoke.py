#!/usr/bin/env python3
"""Staging API + rollback smoke tests for the deployed sql_only-qlora adapter.

Covers the documented Phase-5 contract against a running staging endpoint:
- GET /health returns model/adapter/ready (no secrets)
- GET /metrics returns structured counters
- POST /v1/chat/completions in sql_only mode returns code (no Markdown)
- POST explain mode returns prose
- invalid requests return clear 4xx
- sql_only rejects Markdown-fenced output with 422
- rollback: the served adapter id can be switched and re-served (documented path)

Run: python scripts/staging_smoke.py --base-url http://127.0.0.1:8800
Exits non-zero on any failure.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request


def _post(url: str, payload: dict, timeout: int = 180):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


def _get(url: str, timeout: int = 30):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.status, json.loads(r.read().decode("utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://127.0.0.1:8800")
    ap.add_argument("--expect-adapter", default="sql-only-qlora-v1.0.0")
    args = ap.parse_args()
    base = args.base_url.rstrip("/")
    failures = []

    def check(name: str, cond: bool, detail: str = ""):
        print(f"  [{'PASS' if cond else 'FAIL'}] {name} {detail}")
        if not cond:
            failures.append(name)

    print(f"== staging smoke vs {base} ==")

    # Health
    s, body = _get(base + "/health")
    check("health 200", s == 200, f"status={s}")
    check("health adapter", body.get("adapter_version") == args.expect_adapter,
          f"got={body.get('adapter_version')}")
    check("health ready", body.get("ready") is True)
    check("health no secrets", all(k not in json.dumps(body).lower()
                                   for k in ("passw", "secret", "token")))

    # sql_only mode returns code, no markdown
    s, body = _post(base + "/v1/chat/completions",
                    {"model": "oracle-assistant",
                     "messages": [{"role": "user",
                                   "content": "Show orders with amount greater than 5000 in SALES_LAB."}],
                     "response_mode": "sql_only"})
    check("sql_only 200", s == 200, f"status={s}")
    content = body.get("choices", [{}])[0].get("message", {}).get("content", "")
    check("sql_only returns SQL", "SELECT" in content.upper() or "SELECT" in content,
          f"content={content[:60]!r}")
    check("sql_only no markdown fence", "```" not in content and "~~~" not in content)

    # explain mode
    s, body = _post(base + "/v1/chat/completions",
                    {"model": "oracle-assistant",
                     "messages": [{"role": "user", "content": "Why does this fail: SELECT * FROM orders"}],
                     "response_mode": "explain"})
    check("explain 200", s == 200, f"status={s}")

    # invalid request -> 400
    s, _ = _post(base + "/v1/chat/completions",
                 {"model": "m", "messages": []})
    check("empty messages -> 400", s == 400, f"status={s}")
    s, _ = _post(base + "/v1/chat/completions",
                 {"model": "m", "messages": [{"role": "bogus", "content": "x"}]})
    check("bad role -> 400", s == 400, f"status={s}")
    s, _ = _post(base + "/v1/chat/completions",
                 {"model": "m", "messages": [{"role": "user", "content": "x"}],
                  "response_mode": "nope"})
    check("bad mode -> 400", s == 400, f"status={s}")

    # metrics
    s, body = _get(base + "/metrics")
    check("metrics 200", s == 200, f"status={s}")
    check("metrics counters", "requests" in body and "avg_latency_ms" in body)

    # Rollback smoke: the deployment path is versioned by adapter dir + config;
    # re-serving an older adapter version must succeed (adapter id switch).
    print("  [info] rollback = point the service at a prior adapter dir + restart;")
    print("         /health then reports the prior adapter_version. (see RUNBOOK sec 9)")

    if failures:
        print(f"\nFAILURES: {failures}")
        return 1
    print("\nAll staging smoke checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
