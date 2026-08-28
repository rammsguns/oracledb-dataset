"""Evaluation package for the Oracle LLM pipeline (Phase 3)."""
from oracle_llm.evaluation.generate import (
    generate_from_endpoint,
    generate_from_local,
    SQL_ONLY_SYSTEM,
)
from oracle_llm.evaluation.summarize import (
    summarize_results,
    load_results,
    comparison_report,
)

__all__ = [
    "generate_from_endpoint",
    "generate_from_local",
    "SQL_ONLY_SYSTEM",
    "summarize_results",
    "load_results",
    "comparison_report",
]
