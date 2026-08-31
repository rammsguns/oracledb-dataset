"""Phase 3/4 tests: summarize + selection policy + serving smoke."""
import json
from pathlib import Path

from oracle_llm.evaluation.summarize import load_results, summarize_results
from oracle_llm.serving.app import _Backend, create_app
from oracle_llm.training.selection import check_promotion


def _mk_results(passed, total, kind="query", schema="SALES_LAB", ce=0):
    """Build a synthetic result list."""
    out = []
    for i in range(total):
        ok = i < passed
        err = None if ok else "ORA-00942: table does not exist"
        is_ce = i < ce
        out.append(
            {
                "id": f"t{i:03d}",
                "schema": schema,
                "pass": ok,
                "executed_ok": ok,
                "kind": kind,
                "is_controlled_error": is_ce,
                "expected_error": "ORA-02290" if is_ce else None,
                "error": err,
                "answer_checksum": "abc" if ok else "error",
                "validation_checksum": "def" if ok else "no-rows",
            }
        )
    return out


def test_summarize_counts():
    res = _mk_results(150, 150)
    s = summarize_results(res)
    assert s["tasks"] == 150
    assert s["passed"] == 150
    assert s["passed_pct"] == 100.0
    assert s["exact_result"] == 150
    assert s["by_schema"]["SALES_LAB"]["passed"] == 150


def test_summarize_breakdown_kind_schema():
    res = _mk_results(8, 10, kind="dml", schema="DOCUMENTS_LAB")
    s = summarize_results(res)
    assert s["by_kind"]["dml"]["passed"] == 8
    assert s["by_schema"]["DOCUMENTS_LAB"]["passed"] == 8


def test_promotion_when_conditions_hold(tmp_path):
    run = _mk_results(120, 150)  # improves on baseline 90
    baseline = _mk_results(90, 150)
    gold = _mk_results(150, 150)
    meta = {
        "base_model_revision": "abc123",
        "train_variant": "chat",
        "config": {"base_model": "x", "train_variant": "chat"},
        "data_manifest": {"source_files": {}, "record_hashes": {}},
    }
    run_p = tmp_path / "run.jsonl"
    base_p = tmp_path / "base.jsonl"
    gold_p = tmp_path / "gold.jsonl"
    meta_p = tmp_path / "provenance.json"
    for p, data in ((run_p, run), (base_p, baseline), (gold_p, gold)):
        p.write_text("\n".join(json.dumps(r) for r in data) + "\n")
    meta_p.write_text(json.dumps(meta))

    d = check_promotion(
        run_metadata_path=meta_p,
        results_path=run_p,
        gold_summary=summarize_results(gold),
        baseline_summary=summarize_results(baseline),
    )
    assert d.status == "promoted"
    assert d.checks["gold_harness_ok"]
    assert d.checks["held_out_improved"]


def test_promotion_rejected_when_not_improved(tmp_path):
    run = _mk_results(80, 150)  # worse than baseline 90
    baseline = _mk_results(90, 150)
    gold = _mk_results(150, 150)
    meta = {
        "base_model_revision": "abc123",
        "config": {"base_model": "x"},
        "data_manifest": {"source_files": {}},
    }
    run_p = tmp_path / "run.jsonl"
    base_p = tmp_path / "base.jsonl"
    gold_p = tmp_path / "gold.jsonl"
    meta_p = tmp_path / "provenance.json"
    for p, data in ((run_p, run), (base_p, baseline), (gold_p, gold)):
        p.write_text("\n".join(json.dumps(r) for r in data) + "\n")
    meta_p.write_text(json.dumps(meta))

    d = check_promotion(
        run_metadata_path=meta_p,
        results_path=run_p,
        gold_summary=summarize_results(gold),
        baseline_summary=summarize_results(baseline),
    )
    assert d.status != "promoted"
    assert not d.checks["held_out_improved"]


def _client(backend=None):
    from fastapi.testclient import TestClient

    app = create_app(backend=backend or _Backend(generate=lambda msgs, t: "SELECT 1 FROM dual;",
                                                 model_id="m", adapter_version="v1"))
    return TestClient(app)


def test_health():
    c = _client()
    r = c.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["model_id"] == "m"
    assert "adapter_version" in body
    assert "secrets" not in json.dumps(body).lower()


def test_chat_completion_sql_only():
    c = _client()
    r = c.post(
        "/v1/chat/completions",
        json={"model": "m", "messages": [{"role": "user", "content": "count orders"}]},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["choices"][0]["message"]["role"] == "assistant"
    assert body["choices"][0]["message"]["content"] == "SELECT 1 FROM dual;"


def test_chat_completion_explain_mode():
    c = _client()
    r = c.post(
        "/v1/chat/completions",
        json={
            "model": "m",
            "messages": [{"role": "user", "content": "why did this fail"}],
            "response_mode": "explain",
        },
    )
    assert r.status_code == 200


def test_invalid_request_4xx():
    c = _client()
    assert c.post("/v1/chat/completions", json={"model": "m", "messages": []}).status_code == 400
    assert c.post(
        "/v1/chat/completions",
        json={"model": "m", "messages": [{"role": "bogus", "content": "x"}]},
    ).status_code == 400
    assert c.post(
        "/v1/chat/completions",
        json={"model": "m", "messages": [{"role": "user", "content": "x"}], "response_mode": "nope"},
    ).status_code == 400


def test_sql_only_no_markdown_fences():
    """sql_only mode must reject a Markdown-fenced response (regression)."""
    fenced = _Backend(generate=lambda msgs, t: "```sql\nSELECT 1 FROM dual;\n```",
                      model_id="m", adapter_version="v1")
    c = _client(fenced)
    r = c.post(
        "/v1/chat/completions",
        json={"model": "m", "messages": [{"role": "user", "content": "count orders"}],
              "response_mode": "sql_only"},
    )
    assert r.status_code == 422
    assert "Markdown" in r.json()["detail"]


def test_explain_mode_allows_markdown():
    """explain mode may return prose/Markdown and must not be rejected."""
    fenced = _Backend(generate=lambda msgs, t: "See ```sql\nSELECT 1;\n```\n", model_id="m",
                      adapter_version="v1")
    c = _client(fenced)
    r = c.post(
        "/v1/chat/completions",
        json={"model": "m", "messages": [{"role": "user", "content": "explain"}],
              "response_mode": "explain"},
    )
    assert r.status_code == 200


def test_contains_markdown_fence():
    from oracle_llm.serving.app import _contains_markdown_fence

    assert _contains_markdown_fence("```sql\nSELECT 1;\n```")
    assert _contains_markdown_fence("~~~\ntext\n~~~")
    assert not _contains_markdown_fence("SELECT 1 FROM dual;")
    assert not _contains_markdown_fence("")


def test_metrics_endpoint():
    c = _client()
    c.post("/v1/chat/completions",
           json={"model": "m", "messages": [{"role": "user", "content": "hi"}]})
    m = c.get("/metrics").json()
    assert m["requests"] >= 1
    assert m["sql_only"] >= 1
    assert "avg_latency_ms" in m
    assert "error_rate" in m


def test_schema_detection_miss_metric_serving(tmp_path):
    """Serving integration: unrecognized schema increments schema_detection_misses;
    recognized schema leaves it unchanged (and retrieval_miss semantics preserved)."""
    import json

    from fastapi.testclient import TestClient

    from oracle_llm.serving.retrieval import SchemaRetriever

    idx = tmp_path / "idx.json"
    idx.write_text(json.dumps({
        "version": "v2", "generated": "x", "schemas": {
            "SALES_LAB": {"tables": {"LLM_SALES_ORDERS": {
                "columns": [["ORDER_ID", "NUMBER"]], "pk": ["ORDER_ID"],
                "unique": [], "fk": [], "check": [], "description": ""}},
                "views": {}, "sequences": []},
        }}))
    app = create_app(
        backend=_Backend(generate=lambda msgs, t: "SELECT 1 FROM dual;", model_id="m"),
        retriever=SchemaRetriever(idx),
    )
    c = TestClient(app)

    # Recognized schema -> no detection miss, DDL injected.
    c.post("/v1/chat/completions",
           json={"model": "m",
                 "messages": [{"role": "user", "content": "Show orders from SALES_LAB"}],
                 "response_mode": "sql_only"})
    # Unrecognized schema -> schema-detection miss.
    c.post("/v1/chat/completions",
           json={"model": "m",
                 "messages": [{"role": "user", "content": "What is the total number of orders?"}],
                 "response_mode": "sql_only"})

    m = c.get("/metrics").json()
    assert m["schema_detection_misses"] == 1
    assert m["schema_detection_miss_rate"] == 50.0  # 1/2 sql_only requests
    assert m["retrieval_misses"] == 0  # neither named a known schema with no DDL


def test_rate_limit():
    """A constrained rate limiter rejects excess requests with 429."""
    app = create_app(
        backend=_Backend(generate=lambda msgs, t: "SELECT 1 FROM dual;", model_id="m"),
        rate_limit=0.001, rate_burst=2,
    )
    from fastapi.testclient import TestClient

    c = TestClient(app)
    ok = 0
    too_many = 0
    for _ in range(5):
        r = c.post("/v1/chat/completions",
                   json={"model": "m", "messages": [{"role": "user", "content": "hi"}]})
        if r.status_code == 200:
            ok += 1
        elif r.status_code == 429:
            too_many += 1
    assert too_many > 0  # burst exceeded -> 429
    assert ok + too_many == 5


def test_oversized_body_rejected():
    c = _client()
    huge = "x" * 400_000  # > MAX_CHARS_PER_MESSAGE
    r = c.post("/v1/chat/completions",
               json={"model": "m", "messages": [{"role": "user", "content": huge}]})
    assert r.status_code == 400  # per-message cap (before 413 body cap in tests)
