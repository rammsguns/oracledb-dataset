"""Phase 1 data-contract tests: loaders, validation, guards, formatting."""
import json
import tempfile
from pathlib import Path

import pytest

from oracle_llm.data.format import row_to_chat, tokenize_supervised
from oracle_llm.data.guards import HOLD_OUT_FILE, assert_not_held_out, is_held_out
from oracle_llm.data.loaders import load_jsonl, load_records
from oracle_llm.data.manifest import Manifest, record_hashes
from oracle_llm.data.validate import DataValidationError, fingerprint, validate_records

ROOT = Path(__file__).resolve().parent.parent.parent  # repo root
DATA = {
    "chat": ROOT / "oracle_train_chat.jsonl",
    "sql_only": ROOT / "oracle_train_code_only.jsonl",
    "repair": ROOT / "oracle_train_error_repair.jsonl",
    "holdout": ROOT / "oracle_eval_holdout.jsonl",
    "eval_catalog": ROOT / "llm_task_catalog_eval.jsonl",
}


def test_all_train_files_validate():
    for name in ("chat", "sql_only", "repair"):
        recs = load_jsonl(DATA[name])
        assert len(recs) > 0
        validate_records(recs)


def test_eval_holdout_validates():
    recs = load_jsonl(DATA["holdout"])
    validate_records(recs)
    assert len(recs) == 18


def test_malformed_row_rejected():
    bad = [{"messages": [{"role": "user", "content": "hi"}]}]  # no assistant tail
    with pytest.raises(DataValidationError):
        validate_records(bad)
    bad2 = [{"instruction": "  ", "output": "SELECT 1 FROM dual;"}]
    with pytest.raises(DataValidationError):
        validate_records(bad2)


def test_duplicate_rejected():
    rec = {"instruction": "x", "output": "y"}
    with pytest.raises(DataValidationError):
        validate_records([rec, rec])


def test_held_out_catalog_rejected_as_training_input():
    with pytest.raises(ValueError, match="held-out"):
        assert_not_held_out([DATA["eval_catalog"]])
    assert is_held_out(DATA["eval_catalog"])
    assert not is_held_out(DATA["chat"])


def test_fingerprint_deterministic():
    rec = {"instruction": "a", "output": "b"}
    assert fingerprint(rec) == fingerprint(rec)
    assert record_hashes([rec])["0"] == fingerprint(rec)


def test_manifest_save(tmp_path):
    recs = [{"instruction": "a", "output": "b"}]
    src = tmp_path / "dummy.jsonl"
    src.write_text(json.dumps(recs[0]) + "\n")
    m = Manifest([src], recs)
    out = m.save(tmp_path / "manifest.json")
    assert out.is_file()
    assert json.loads(out.read_text())["record_count"] == 1


def test_row_to_chat_and_format(tmp_path):
    # Triplet -> chat normalization
    rec = {"instruction": "q", "input": "CREATE TABLE t (x NUMBER);", "output": "SELECT 1 FROM dual;"}
    chat = row_to_chat(rec)
    assert chat[-1]["role"] == "assistant"
    assert "CREATE TABLE t" in chat[1]["content"]
    assert chat[0]["role"] == "system"

    # Chat passthrough
    chat_rec = {"messages": [{"role": "user", "content": "q"}, {"role": "assistant", "content": "a"}]}
    assert row_to_chat(chat_rec) == chat_rec["messages"]


def test_load_records_multiple():
    with tempfile.TemporaryDirectory() as d:
        p1 = Path(d) / "a.jsonl"
        p2 = Path(d) / "b.jsonl"
        p1.write_text(json.dumps({"instruction": "a", "output": "b"}) + "\n")
        p2.write_text(json.dumps({"instruction": "c", "output": "d"}) + "\n")
        assert len(load_records([p1, p2])) == 2


def test_malformed_json_rejected(tmp_path):
    p = tmp_path / "bad.jsonl"
    p.write_text('{"instruction": "a", "output": "b"}\nnot json\n')
    with pytest.raises(ValueError, match="invalid JSON"):
        load_jsonl(p)
