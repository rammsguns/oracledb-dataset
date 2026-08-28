"""Summarize evaluate_catalog.py results and compare runs (Phase 3).

Consumes the per-task JSONL written by evaluate_catalog.py (fields: id,
schema, pass, executed_ok, kind, is_controlled_error, expected_error, error,
answer_checksum, validation_checksum) and produces machine-readable summary +
breakdowns: overall pass rate, executed-ok rate, exact-result (checksum) rate,
per-schema rate, per-kind rate, and controlled-error rate.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List


def load_results(path: str | Path) -> List[dict]:
    return [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]


def summarize_results(results: List[dict]) -> Dict:
    n = len(results)
    if n == 0:
        return {"tasks": 0}
    passed = sum(1 for r in results if r.get("pass"))
    executed = sum(1 for r in results if r.get("executed_ok"))
    # exact-result = answer executed, validation passed, and no checksum-mismatch
    # note (i.e. answer output matched gold).
    exact = sum(
        1
        for r in results
        if r.get("pass")
        and r.get("executed_ok")
        and not (r.get("notes") or "").startswith("answer_checksum_mismatch")
    )

    def pct(num: int, den: int) -> float:
        return 100.0 * num / den if den else 0.0

    kind_stats = defaultdict(lambda: [0, 0])
    schema_stats = defaultdict(lambda: [0, 0])
    for r in results:
        kind_stats[r.get("kind", "other")][1] += 1
        if r.get("pass"):
            kind_stats[r.get("kind", "other")][0] += 1
        schema_stats[r.get("schema", "?")][1] += 1
        if r.get("pass"):
            schema_stats[r.get("schema", "?")][0] += 1

    ce = [r for r in results if r.get("is_controlled_error")]
    ce_ok = sum(
        1
        for r in ce
        if r.get("pass") and r.get("expected_error") and r.get("error")
        and r["expected_error"] in r["error"]
    )

    return {
        "tasks": n,
        "passed": passed,
        "passed_pct": round(pct(passed, n), 2),
        "failed": n - passed,
        "executed_ok": executed,
        "executed_ok_pct": round(pct(executed, n), 2),
        "exact_result": exact,
        "exact_result_pct": round(pct(exact, n), 2),
        "controlled_error": {"tasks": len(ce), "matched": ce_ok},
        "by_kind": {k: {"passed": v[0], "total": v[1]} for k, v in sorted(kind_stats.items())},
        "by_schema": {k: {"passed": v[0], "total": v[1]} for k, v in sorted(schema_stats.items())},
    }


def comparison_report(*runs: List[dict]) -> Dict:
    """Compare multiple result sets (e.g. gold, baseline, chat, sql_only)."""
    summaries = [summarize_results(r) for r in runs]
    return {"runs": summaries, "run_count": len(summaries)}
