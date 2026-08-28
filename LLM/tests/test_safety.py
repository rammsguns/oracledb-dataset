"""Operational-safety tests (execution guard + monitoring).

Verifies:
- generated SQL execution is confined to disposable/resettable lab schemas and
  never reaches production credentials (fail-closed guard);
- retrieval-miss metrics are recorded in serving;
- Oracle error categories are classified for monitoring.
"""
import os
from pathlib import Path

import pytest

from oracle_llm.evaluation.safety import (
    DISPOSABLE_SCHEMAS,
    READ_ONLY_SCHEMAS,
    ExecutionGuardError,
    assert_executable_schema,
    classify_error_category,
    disposable_credentials,
    is_disposable,
    read_only_credentials,
)


# --- Execution guard -------------------------------------------------------

def test_disposable_schemas_are_resettable_labs():
    assert "SALES_LAB" in DISPOSABLE_SCHEMAS
    assert "LOGISTICS_LAB" in DISPOSABLE_SCHEMAS
    assert "PRODUCTION_SCHEMAS" in globals() or True
    from oracle_llm.evaluation.safety import PRODUCTION_SCHEMAS

    assert len(PRODUCTION_SCHEMAS) == 0  # production is never an execution target


def test_assert_executable_allows_disposable_and_readonly():
    assert_executable_schema("SALES_LAB")
    assert_executable_schema("HR")  # read-only ok by default
    assert_executable_schema("co")  # case-insensitive


def test_assert_executable_rejects_unknown():
    with pytest.raises(ExecutionGuardError):
        assert_executable_schema("PROD_ORDERS")
    with pytest.raises(ExecutionGuardError):
        assert_executable_schema("SALES")  # not a real lab schema


def test_read_only_requires_readonly_ok_flag():
    # A read-only schema is rejected when read_only_ok=False (DML not allowed)
    with pytest.raises(ExecutionGuardError):
        assert_executable_schema("HR", read_only_ok=False)


def test_disposable_credentials_env_only(monkeypatch):
    monkeypatch.setenv("ORACLE_LAB_PW_SALES_LAB", "secret")
    user, pw = disposable_credentials("SALES_LAB")
    assert user == "SALES_LAB"
    assert pw == "secret"
    # non-disposable -> refused
    with pytest.raises(ExecutionGuardError):
        disposable_credentials("PROD")


def test_read_only_credentials_env_only(monkeypatch):
    monkeypatch.setenv("ORACLE_SAMPLE_PW_HR", "hrpw")
    user, pw = read_only_credentials("HR")
    assert user == "hr"
    assert pw == "hrpw"
    with pytest.raises(ExecutionGuardError):
        read_only_credentials("PROD")


# --- Monitoring ------------------------------------------------------------

def test_error_category_classification():
    assert classify_error_category("ORA-00942: table or view does not exist") == "object-not-found"
    assert classify_error_category("ORA-00904: invalid identifier") == "invalid-identifier"
    assert classify_error_category("ORA-00933: SQL command not properly ended") == "syntax"
    assert classify_error_category("ORA-02290: check constraint violated") == "constraint/business-rule"
    assert classify_error_category("ORA-01017: invalid username/password") == "privilege"
    assert classify_error_category("ORA-06550: line 1, column 7") == "plsql"
    assert classify_error_category("") == "none"
    assert classify_error_category("some random text") == "non-ora"
    assert classify_error_category("ORA-12345: custom") == "ora-2345"


def test_retriever_retrieve_meta(tmp_path):
    from oracle_llm.serving.retrieval import SchemaRetriever

    idx = tmp_path / "idx.json"
    idx.write_text(
        '{"SALES_LAB": {"LLM_SALES_ORDERS": {"columns": [["ORDER_ID","NUMBER"]], '
        '"pk": ["ORDER_ID"], "unique": []}}}'
    )
    r = SchemaRetriever(idx)
    meta = r.retrieve("List orders in SALES_LAB", mode="sql_only")
    assert meta["detected"] is True
    assert meta["schema"] == "SALES_LAB"
    assert meta["injected"] is True
    assert meta["miss"] is False
    # unknown schema -> miss
    meta2 = r.retrieve("list things in NOPE", mode="sql_only")
    assert meta2["detected"] is False
    assert meta2["miss"] is False  # no schema named, not a miss
    # explain mode -> not injected, not a miss
    meta3 = r.retrieve("List orders in SALES_LAB", mode="explain")
    assert meta3["injected"] is False
    assert meta3["miss"] is False


def test_serving_metrics_record_retrieval_miss_and_errors():
    from oracle_llm.serving.app import _Metrics

    m = _Metrics()
    m.record(mode="sql_only", latency_ms=1.0, retrieval_miss=True)
    m.record(mode="sql_only", latency_ms=2.0)
    snap = m.snapshot()
    assert snap["retrieval_misses"] == 1
    assert snap["sql_only"] == 2
    assert "retrieval_miss_rate" in snap


# --- Read-only pilot (S1) -------------------------------------------------

def test_read_only_asks_for_write():
    from oracle_llm.serving.app import _asks_for_write

    assert _asks_for_write("insert an order")
    assert _asks_for_write("update the inventory")
    assert _asks_for_write("DELETE FROM orders")
    assert _asks_for_write("create a table")
    assert _asks_for_write("merge these rows")
    assert not _asks_for_write("select orders")
    assert not _asks_for_write("show customers")
    assert not _asks_for_write("what is the total sales")


def test_read_only_pilot_refuses_dml():
    from fastapi.testclient import TestClient

    from oracle_llm.serving.app import _Backend, create_app

    app = create_app(
        backend=_Backend(generate=lambda msgs, t: "SELECT 1 FROM dual;", model_id="m"),
        read_only=True,
    )
    c = TestClient(app)
    # read-oriented -> allowed
    r = c.post("/v1/chat/completions",
               json={"model": "m", "messages": [{"role": "user", "content": "show orders"}],
                     "response_mode": "sql_only"})
    assert r.status_code == 200
    # DML -> refused 422
    r2 = c.post("/v1/chat/completions",
                json={"model": "m", "messages": [{"role": "user", "content": "insert an order"}],
                      "response_mode": "sql_only"})
    assert r2.status_code == 422
    # refusal tracked in metrics
    m = c.get("/metrics").json()
    assert m["refusals"] == 1
    assert m["refusal_rate"] > 0


def test_read_only_pilot_non_sql_only_ignores():
    from fastapi.testclient import TestClient

    from oracle_llm.serving.app import _Backend, create_app

    app = create_app(
        backend=_Backend(generate=lambda msgs, t: "explanation", model_id="m"),
        read_only=True,
    )
    c = TestClient(app)
    # explain mode is not subject to the read-only SQL refusal
    r = c.post("/v1/chat/completions",
               json={"model": "m", "messages": [{"role": "user", "content": "how to update x"}],
                     "response_mode": "explain"})
    assert r.status_code == 200
