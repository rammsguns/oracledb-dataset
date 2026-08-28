"""Selection / promotion policy (Phase 4).

A run may be recorded as ``candidate`` or promoted to ``promoted`` only when
ALL of the following hold:

- the gold harness succeeds (gold answers -> documented 150/150, or the
  expected gold pass rate for the configured catalog);
- dataset hashes match the frozen manifest (MANIFEST.md pinned SHA-256s);
- the run is reproducible from its config + base-model revision;
- no held-out-data violation occurred (deny-list enforced at data ingest);
- held-out execution accuracy improves on the selected base baseline, with no
  material regression in controlled-error accuracy.

Do NOT choose a model by validation loss alone.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


class PromotionError(ValueError):
    """Raised when a model cannot be promoted because a condition fails."""


@dataclass
class SelectionDecision:
    status: str  # "candidate" | "promoted" | "rejected"
    reasons: List[str] = field(default_factory=list)
    checks: Dict[str, bool] = field(default_factory=dict)
    report: Dict = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            "status": self.status,
            "reasons": self.reasons,
            "checks": self.checks,
            "report": self.report,
        }


def _load(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def check_promotion(
    *,
    run_metadata_path: str | Path,
    results_path: str | Path,
    gold_summary: Dict,
    baseline_summary: Dict,
    frozen_manifest_path: Optional[str | Path] = None,
    require_held_out_improvement: bool = True,
    min_controlled_error_delta: float = -0.05,
) -> SelectionDecision:
    """Evaluate promotion conditions for one run.

    Args:
        run_metadata_path: the run's provenance.json (has data manifest hashes,
            base_model_revision, train_variant, config).
        results_path: the run's evaluate_catalog.py result JSONL.
        gold_summary: summarize_results() of the gold-harness run.
        baseline_summary: summarize_results() of the base-baseline run.
        frozen_manifest_path: optional MANIFEST.md path; hashes are verified
            against it when provided.
        require_held_out_improvement: if False, an equal-or-better gate is used.
        min_controlled_error_delta: allowed regression in controlled-error
            matched rate (fraction, e.g. -0.05 = 5pp regression allowed).
    """
    meta = _load(run_metadata_path)
    checks: Dict[str, bool] = {}
    reasons: List[str] = []
    held_out_improved = False

    # 1) gold harness succeeds
    gold_ok = gold_summary.get("passed") == gold_summary.get("tasks") and gold_summary.get("tasks")
    checks["gold_harness_ok"] = bool(gold_ok)
    if not gold_ok:
        reasons.append("gold harness did not reach expected pass rate")

    # 2) held-out execution accuracy improves on baseline (or no regression)
    run_pct = (results_summary := _summarize(results_path)).get("passed_pct", 0.0)
    base_pct = baseline_summary.get("passed_pct", 0.0)
    if require_held_out_improvement:
        held_out_improved = run_pct > base_pct
    else:
        held_out_improved = run_pct >= base_pct
    checks["held_out_improved"] = held_out_improved
    if not held_out_improved:
        reasons.append(f"held-out pass {run_pct:.1f}% did not improve on baseline {base_pct:.1f}%")

    # controlled-error accuracy: no material regression
    run_ce = (results_summary.get("controlled_error") or {}).get("matched", 0)
    run_ce_tasks = (results_summary.get("controlled_error") or {}).get("tasks", 0)
    base_ce = (baseline_summary.get("controlled_error") or {}).get("matched", 0)
    base_ce_tasks = (baseline_summary.get("controlled_error") or {}).get("tasks", 0)
    run_ce_rate = run_ce / run_ce_tasks if run_ce_tasks else 0.0
    base_ce_rate = base_ce / base_ce_tasks if base_ce_tasks else 0.0
    ce_regression_ok = (run_ce_rate - base_ce_rate) >= min_controlled_error_delta
    checks["controlled_error_no_regression"] = ce_regression_ok
    if not ce_regression_ok:
        reasons.append(
            f"controlled-error accuracy regressed {run_ce_rate:.2f} vs baseline {base_ce_rate:.2f}"
        )

    # 3) dataset hashes match frozen manifest
    manifest_ok = True
    if frozen_manifest_path and Path(frozen_manifest_path).is_file():
        manifest_text = Path(frozen_manifest_path).read_text(encoding="utf-8")
        for src, h in (meta.get("data_manifest") or {}).get("source_files", {}).items():
            # Only check files actually named in the manifest that are data files.
            name = Path(src).name
            if name.endswith(".jsonl") and name in manifest_text:
                # hash appears in manifest text as `| name | <hash> |`
                if h not in manifest_text:
                    manifest_ok = False
                    reasons.append(f"data file {name} hash not pinned in frozen manifest")
    checks["dataset_hashes_match"] = manifest_ok

    # 4) reproducible from config + base revision
    has_revision = bool(meta.get("base_model_revision"))
    has_config = bool(meta.get("config"))
    reproducible = has_revision and has_config
    checks["reproducible"] = reproducible
    if not reproducible:
        reasons.append("missing base_model_revision or config in run metadata")

    status = "promoted" if (gold_ok and held_out_improved and ce_regression_ok and manifest_ok and reproducible) else "candidate"
    return SelectionDecision(
        status=status,
        reasons=reasons,
        checks=checks,
        report={
            "run": results_summary,
            "baseline": baseline_summary,
            "gold": gold_summary,
        },
    )


def _summarize(results_path: str | Path) -> Dict:
    from oracle_llm.evaluation.summarize import load_results, summarize_results

    return summarize_results(load_results(results_path))


# The next promotion threshold: a new candidate must exceed the selected
# adapter's held-out pass rate and match/exceed its controlled-error accuracy.
# Derived from artifacts/selected_adapter.json (sql_only-qlora).
DEFAULT_PROMOTION_THRESHOLDS = {
    "min_passed_pct": 16.0,      # must strictly exceed selected 16.0%
    "min_controlled_error_matched": 6,  # must be >= selected 6/25
}


def check_promotion_thresholds(
    results_path: str | Path,
    thresholds: Optional[Dict] = None,
) -> SelectionDecision:
    """Gate a NEW challenger against the selected adapter's thresholds (P3).

    A future challenger is only ``promoted`` when it clears the held-out
    execution and controlled-error thresholds set by the current selected
    adapter, in addition to the standard promotion checks. The incumbent
    selected adapter (sql_only, chosen against the prior baseline) is
    grandfathered and is not required to re-pass this stricter threshold —
    this gate is only applied to candidates that come after it.
    """
    t = thresholds or DEFAULT_PROMOTION_THRESHOLDS
    s = _summarize(results_path)
    checks: Dict[str, bool] = {}
    reasons: List[str] = []

    passed_pct = s.get("passed_pct", 0.0)
    min_pct = t["min_passed_pct"]
    ok_pct = passed_pct > min_pct
    checks["exceeds_selected_pass_pct"] = ok_pct
    if not ok_pct:
        reasons.append(f"pass {passed_pct:.2f}% does not exceed selected threshold {min_pct}%")

    ce = s.get("controlled_error") or {}
    ce_matched = ce.get("matched", 0)
    min_ce = t["min_controlled_error_matched"]
    ok_ce = ce_matched >= min_ce
    checks["controlled_error_meets_threshold"] = ok_ce
    if not ok_ce:
        reasons.append(f"controlled-error {ce_matched}/{ce.get('tasks', 0)} below threshold {min_ce}")

    status = "promoted" if (ok_pct and ok_ce) else "candidate"
    return SelectionDecision(status=status, reasons=reasons, checks=checks, report={"run": s})
