"""CI-safe guard tests (Phase 3, NEXT_STEPS).

These run WITHOUT Docker, Oracle, or downloading a model — safe for ordinary
CI. They verify the frozen dataset hashes against MANIFEST.md, the held-out
deny-list rules, JSON record schemas, and report parsing.
"""
import json
import hashlib
import re
from pathlib import Path

import pytest

from oracle_llm.data.guards import HOLD_OUT_FILE, assert_not_held_out, is_held_out
from oracle_llm.data.loaders import load_jsonl
from oracle_llm.data.validate import validate_records
from oracle_llm.evaluation.summarize import load_results, summarize_results

ROOT = Path(__file__).resolve().parent.parent.parent  # repo root
LLM = ROOT / "LLM"
MANIFEST = ROOT / "MANIFEST.md"

DATA_FILES = [
    "oracle_train_chat.jsonl",
    "oracle_train_code_only.jsonl",
    "oracle_train_error_repair.jsonl",
    "oracle_eval_holdout.jsonl",
    "llm_task_catalog_eval.jsonl",
    "llm_task_catalog_train.jsonl",
    "llm_task_catalog_v3.jsonl",
    "oracle_dataset_full.jsonl",
]


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _manifest_hashes() -> dict:
    """Parse MANIFEST.md's integrity table into {filename: sha256}."""
    text = MANIFEST.read_text(encoding="utf-8")
    out = {}
    # lines like: | oracle_train_chat.jsonl | `abc123...` |
    for line in text.splitlines():
        m = re.match(r"\|\s*([\w.\-]+\.jsonl)\s*\|\s*`([0-9a-f]{64})`\s*\|", line)
        if m:
            out[m.group(1)] = m.group(2)
    return out


def test_manifest_hashes_match_frozen_release():
    """Every pinned data file on disk must match its MANIFEST.md SHA-256."""
    manifest = _manifest_hashes()
    assert manifest, "MANIFEST.md integrity table not parsed"
    for name in DATA_FILES:
        p = ROOT / name
        if not p.is_file():
            continue  # skip files not present in this tree
        assert name in manifest, f"{name} not pinned in MANIFEST.md"
        assert _sha256(p) == manifest[name], f"{name} hash does not match MANIFEST.md"


def test_held_out_deny_list_fails_closed():
    assert is_held_out(ROOT / HOLD_OUT_FILE)
    with pytest.raises(ValueError, match="held-out"):
        assert_not_held_out([ROOT / HOLD_OUT_FILE])
    # A training file is fine.
    assert_not_held_out([ROOT / "oracle_train_chat.jsonl"])


def test_train_and_eval_catalog_disjoint():
    """The training catalog must not contain any held-out eval task id."""
    train_ids = {r["id"] for r in load_jsonl(ROOT / "llm_task_catalog_train.jsonl")}
    eval_ids = {r["id"] for r in load_jsonl(ROOT / HOLD_OUT_FILE)}
    overlap = train_ids & eval_ids
    assert not overlap, f"held-out ids leaked into train catalog: {overlap}"


def test_record_schema_and_validation():
    """Every training file parses, validates, and matches the record schema."""
    schemas = {
        "oracle_train_chat.jsonl": "chat",
        "oracle_train_code_only.jsonl": "triplet",
        "oracle_train_error_repair.jsonl": "triplet",
        "oracle_eval_holdout.jsonl": "triplet",
    }
    for name, kind in schemas.items():
        recs = load_jsonl(ROOT / name)
        assert recs, f"{name} is empty"
        validate_records(recs)
        for r in recs:
            if kind == "chat":
                assert r["messages"][-1]["role"] == "assistant"
            else:
                assert r.get("instruction") and r.get("output")


def test_report_parsing_and_summary():
    """evaluate_catalog.py result JSONL parses into a machine-readable summary."""
    results = load_results(LLM / "artifacts" / "gold_results.jsonl")
    s = summarize_results(results)
    assert s["tasks"] == 150
    assert s["passed"] == 150  # gold harness = sanity ceiling
    assert s["passed_pct"] == 100.0


def test_report_json_schema():
    """Selected-adapter and comparison metadata are valid JSON with expected keys."""
    sel = json.loads((LLM / "artifacts" / "selected_adapter.json").read_text())
    assert sel["selected_adapter"] == "sql-only-qlora"
    assert "held_out_scores" in sel
    assert "sql_only" in sel["held_out_scores"]

    comp = json.loads((LLM / "artifacts" / "comparison_all.json").read_text())
    assert comp["run_count"] == 5
    assert all("passed_pct" in r for r in comp["runs"])


def test_no_secrets_in_committed_metadata():
    """Committed docs/reports and configs must not contain credential patterns."""
    roots = [LLM / "docs", LLM / "configs", LLM / "README.md", LLM / "pyproject.toml"]
    bad = re.compile(r"(Passw0rd|SalesLab_23ai|DocsLab_23ai|OpsLab_23ai|HrTest_23ai|"
                     r"CoTest_23ai|LogisticsLab_23ai|SupportLab_23ai|password\s*=)", re.I)
    for root in roots:
        if root.is_dir():
            files = list(root.rglob("*.md")) + list(root.rglob("*.yaml"))
        else:
            files = [root]
        for f in files:
            if bad.search(f.read_text(encoding="utf-8", errors="ignore")):
                pytest.fail(f"credential pattern found in {f}")
