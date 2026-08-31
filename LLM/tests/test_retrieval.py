"""Step 2/3 tests: schema-context retrieval layer.

Verifies the retriever:
- loads the approved schema index and detects the target schema,
- injects correct DDL into sql_only prompts (and NOT explain),
- NEVER indexes or references the held-out execution catalog.
"""
import json
from pathlib import Path

import pytest

from oracle_llm.serving.retrieval import (
    DENIED_INDEX_SOURCES,
    SchemaRetriever,
)

ROOT = Path(__file__).resolve().parent.parent.parent  # repo root
LLM = ROOT / "LLM"

# A small approved schema index for testing (mirrors real lab schema names).
FAKE_INDEX = {
    "SALES_LAB": {
        "LLM_SALES_ORDERS": {
            "columns": [["ORDER_ID", "NUMBER"], ["CUSTOMER_NAME", "VARCHAR2"], ["AMOUNT", "NUMBER(12,2)"]],
            "pk": ["ORDER_ID"],
            "unique": [],
        },
        "LLM_SALES_REGIONS": {
            "columns": [["REGION_ID", "NUMBER"], ["REGION_NAME", "VARCHAR2"]],
            "pk": ["REGION_ID"],
            "unique": [],
        },
    },
    "LOGISTICS_LAB": {
        "LLM_LOG_PRODUCTS": {
            "columns": [["PRODUCT_ID", "NUMBER"], ["PRODUCT_NAME", "VARCHAR2"], ["UNIT_COST", "NUMBER(10,2)"]],
            "pk": ["PRODUCT_ID"],
            "unique": [],
        },
    },
}


@pytest.fixture
def index(tmp_path):
    p = tmp_path / "schema_index.json"
    p.write_text(json.dumps(FAKE_INDEX))
    return p


def test_retriever_detects_schema(index):
    r = SchemaRetriever(index)
    assert r.has_schema("SALES_LAB")
    assert r.has_schema("sales_lab")  # case-insensitive
    assert r.detect_schema("Query the SALES_LAB orders table") == "SALES_LAB"
    assert r.detect_schema("no schema here") is None


def test_retriever_format_ddl(index):
    r = SchemaRetriever(index)
    ddl = r.format_schema_ddl("SALES_LAB")
    assert "LLM_SALES_ORDERS" in ddl
    assert "CUSTOMER_NAME" in ddl
    assert "PRIMARY KEY (ORDER_ID)" in ddl
    assert "LLM_SALES_REGIONS" in ddl


def test_retriever_injects_into_sql_only(index):
    r = SchemaRetriever(index)
    prompt = r.build_context_prompt("Show orders from SALES_LAB", mode="sql_only")
    assert "Schema context" in prompt
    assert "LLM_SALES_ORDERS" in prompt
    assert "Use only the objects and columns listed above" in prompt


def test_retriever_not_injected_into_explain(index):
    r = SchemaRetriever(index)
    prompt = r.build_context_prompt("Explain SALES_LAB orders", mode="explain")
    assert "Schema context" not in prompt
    assert prompt == "Explain SALES_LAB orders"


def test_retriever_no_held_out(index):
    """The retriever must never index the held-out execution catalog."""
    r = SchemaRetriever(index)
    # It only knows the approved schemas, never catalog content.
    assert r.detect_schema("llm_task_catalog_eval") is None
    assert r.get_schema("llm_task_catalog_eval") is None
    # Denied source filenames are explicitly declared.
    assert any("llm_task_catalog_eval" in d for d in DENIED_INDEX_SOURCES)


def test_retriever_retrieve_three_states(index):
    """retrieve() distinguishes injected / miss / not_detected states.

    - Injected: schema detected and DDL injected (state="injected", miss=False).
    - Miss: schema detected but no DDL (state="miss", miss=True) — only
      reachable if a detected schema has no renderable DDL.
    - Not detected: no known schema in the request (state="not_detected").
    """
    r = SchemaRetriever(index)
    # State 1: schema detected + DDL injected.
    injected = r.retrieve("Show orders from SALES_LAB", mode="sql_only")
    assert injected["state"] == "injected"
    assert injected["detected"] is True
    assert injected["injected"] is True
    assert injected["miss"] is False
    # State 3: no schema detected (legacy field values preserved).
    not_detected = r.retrieve("What is the total number of orders?", mode="sql_only")
    assert not_detected["state"] == "not_detected"
    assert not_detected["detected"] is False
    assert not_detected["injected"] is False
    assert not_detected["miss"] is False
    # explain mode is never a detection/retrieval event.
    explain = r.retrieve("List orders from SALES_LAB", mode="explain")
    assert explain["state"] == "not_detected"
    assert explain["detected"] is False
    assert explain["miss"] is False


def test_retriever_retrieve_miss_when_no_ddl(tmp_path, monkeypatch):
    """A detected schema whose DDL cannot be rendered is a retrieval miss
    (state='miss'), distinct from not_detected and preserving legacy miss."""
    idx = tmp_path / "idx.json"
    idx.write_text(json.dumps({
        "version": "v2", "generated": "x", "schemas": {
            "SALES_LAB": {"tables": {"LLM_SALES_ORDERS": {
                "columns": [["ORDER_ID", "NUMBER"]], "pk": ["ORDER_ID"],
                "unique": [], "fk": [], "check": [], "description": ""}},
                "views": {}, "sequences": []},
        }}))
    r = SchemaRetriever(idx)
    # Simulate a detection that resolves but fails to render DDL (e.g. a
    # transient index problem) so the miss branch is exercised deterministically.
    monkeypatch.setattr(r, "format_schema_ddl", lambda *a, **k: "")
    meta = r.retrieve("Query SALES_LAB records", mode="sql_only")
    assert meta["state"] == "miss"
    assert meta["detected"] is True
    assert meta["injected"] is False
    assert meta["miss"] is True


def test_retriever_schema_detection_miss_metric(index):
    """The metrics counter distinguishes schema-detection misses (v1.0.8)."""
    from oracle_llm.serving.app import _Metrics

    m = _Metrics()
    # Unrecognized-schema sql_only request -> schema_detection_miss=True.
    m.record(mode="sql_only", latency_ms=1.0, schema_detection_miss=True)
    # Recognized-schema sql_only request (no miss) -> nothing incremented.
    m.record(mode="sql_only", latency_ms=1.0)
    snap = m.snapshot()
    assert snap["schema_detection_misses"] == 1
    assert snap["schema_detection_miss_rate"] == 50.0  # 1/2 sql_only requests
    assert snap["retrieval_misses"] == 0  # legacy semantics preserved


def test_deny_acceptance_suite(index):
    """The frozen acceptance/regression suite must never be indexed."""
    r = SchemaRetriever(index)
    assert r.detect_schema("final_acceptance") is None
    assert r.detect_schema("acceptance_set") is None
    assert any("acceptance" in d for d in DENIED_INDEX_SOURCES)


def test_deny_blind_final_set(index):
    """The blind final set (FIN_LAB) must never be indexed."""
    r = SchemaRetriever(index)
    assert r.detect_schema("query FIN_LAB accounts") is None
    assert r.detect_schema("blind_final") is None
    assert any("FIN_LAB" in d or "blind" in d for d in DENIED_INDEX_SOURCES)


def test_sequences_rendered_in_ddl(tmp_path):
    """Sequence names are rendered so NEXTVAL/CURRVAL resolve (ORA-02289 fix)."""
    idx = tmp_path / "schema_index_seq.json"
    idx.write_text(json.dumps({
        "version": "v2", "generated": "x", "schemas": {
            "SALES_LAB": {
                "tables": {"LLM_SALES_ORDERS": {
                    "columns": [["ORDER_ID", "NUMBER"]], "pk": ["ORDER_ID"],
                    "unique": [], "fk": [], "check": [], "description": ""}},
                "views": {},
                "sequences": ["LLM_SALES_ORDER_SEQ", "LLM_SALES_ERROR_SEQ"],
            },
        }}))
    r = SchemaRetriever(idx)
    ddl = r.format_schema_ddl("SALES_LAB")
    assert "LLM_SALES_ORDER_SEQ" in ddl
    assert "LLM_SALES_ERROR_SEQ" in ddl
    assert "sequences:" in ddl


def test_sequences_absent_when_none(tmp_path):
    """A schema with no sequences renders no sequence line (no ORA-02289 noise)."""
    idx = tmp_path / "schema_index_noseq.json"
    idx.write_text(json.dumps({
        "version": "v2", "generated": "x", "schemas": {
            "SALES_LAB": {
                "tables": {"LLM_SALES_ORDERS": {
                    "columns": [["ORDER_ID", "NUMBER"]], "pk": ["ORDER_ID"],
                    "unique": [], "fk": [], "check": [], "description": ""}},
                "views": {}, "sequences": [],
            },
        }}))
    r = SchemaRetriever(idx)
    assert "sequences:" not in r.format_schema_ddl("SALES_LAB")


def test_retriever_v2_enriched_format(tmp_path):
    """The retriever reads the enriched v2 index and renders FK/check/descriptions."""
    idx = tmp_path / "schema_index_v2.json"
    idx.write_text(json.dumps({
        "version": "v2",
        "generated": "2026-08-28T00:00:00",
        "schemas": {
            "SALES_LAB": {
                "tables": {
                    "LLM_SALES_ORDERS": {
                        "columns": [["ORDER_ID", "NUMBER"], ["REGION_ID", "NUMBER"]],
                        "pk": ["ORDER_ID"],
                        "unique": [],
                        "fk": [{"column": "REGION_ID",
                                "references": {"table": "LLM_SALES_REGIONS", "columns": ["REGION_ID"]}}],
                        "check": ["amount >= 0"],
                        "description": "Sales orders.",
                    },
                },
                "views": {"LLM_SALES_MONTHLY_REPORT": "Monthly report."},
            },
        },
    }))
    r = SchemaRetriever(idx)
    assert r.version == "v2"
    ddl = r.format_schema_ddl("SALES_LAB")
    assert "Sales orders." in ddl
    assert "FOREIGN KEY (REGION_ID) REFERENCES LLM_SALES_REGIONS (REGION_ID)" in ddl
    assert "CHECK (amount >= 0)" in ddl
    assert "-- view LLM_SALES_MONTHLY_REPORT" in ddl


def test_retriever_v1_still_works(index):
    """v1-format index (schema -> {table: meta}) still renders."""
    r = SchemaRetriever(index)
    assert r.version == "v1"
    ddl = r.format_schema_ddl("SALES_LAB")
    assert "LLM_SALES_ORDERS" in ddl
    assert "PRIMARY KEY (ORDER_ID)" in ddl


def test_retriever_compact_mode_and_budget(tmp_path):
    """Compact v3 mode drops checks/descriptions and honors a token budget."""
    idx = tmp_path / "idx.json"
    idx.write_text(json.dumps({
        "version": "v2", "generated": "x", "schemas": {
            "SALES_LAB": {"tables": {
                "LLM_SALES_ORDERS": {
                    "columns": [["ORDER_ID", "NUMBER"], ["REGION_ID", "NUMBER"]],
                    "pk": ["ORDER_ID"], "unique": [], "check": ["amount >= 0"],
                    "description": "Sales orders.",
                    "fk": [{"column": "REGION_ID",
                            "references": {"table": "LLM_SALES_REGIONS", "columns": ["REGION_ID"]}}],
                },
            }, "views": {}},
        }}))
    r = SchemaRetriever(idx)
    full = r.format_schema_ddl("SALES_LAB")
    compact = r.format_schema_ddl("SALES_LAB", compact=True)
    assert "CHECK (amount >= 0)" in full
    assert "Sales orders." in full
    assert "CHECK (amount >= 0)" not in compact
    assert "Sales orders." not in compact
    assert "FOREIGN KEY (REGION_ID) REFERENCES LLM_SALES_REGIONS (REGION_ID)" in compact
    # token budget truncates the DDL span (wrapper text is fixed overhead)
    p = r.build_context_prompt("orders in SALES_LAB", mode="sql_only",
                               compact=True, max_context_tokens=10)
    assert "Schema context" in p
    assert "FOREIGN KEY" not in p  # FK line is beyond the 10-token budget
    p_unlimited = r.build_context_prompt("orders in SALES_LAB", mode="sql_only", compact=True)
    assert len(p.split()) < len(p_unlimited.split())


def test_retriever_serving_integration(index):
    """sql_only completion with retriever injects context; explain does not."""
    from fastapi.testclient import TestClient

    from oracle_llm.serving.app import _Backend, create_app

    seen = {}

    def generate(messages, temperature):
        # capture the user message content
        seen["user"] = next((m["content"] for m in messages if m["role"] == "user"), "")
        return "SELECT order_id FROM llm_sales_orders;"

    app = create_app(
        backend=_Backend(generate=generate, model_id="m"),
        retriever=SchemaRetriever(index),
    )
    c = TestClient(app)
    c.post("/v1/chat/completions",
           json={"model": "m",
                 "messages": [{"role": "user", "content": "List orders from SALES_LAB"}],
                 "response_mode": "sql_only"})
    assert "LLM_SALES_ORDERS" in seen["user"]
    assert "Schema context" in seen["user"]

    c.post("/v1/chat/completions",
           json={"model": "m",
                 "messages": [{"role": "user", "content": "List orders from SALES_LAB"}],
                 "response_mode": "explain"})
    assert "Schema context" not in seen["user"]
