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
from oracle_llm.evaluation.safety import (
    DISPOSABLE_SCHEMAS,
    READ_ONLY_SCHEMAS,
    PRODUCTION_SCHEMAS,
    ExecutionGuardError,
    assert_executable_schema,
    is_disposable,
    is_read_only,
    disposable_credentials,
    read_only_credentials,
    classify_error_category,
)

__all__ = [
    "generate_from_endpoint",
    "generate_from_local",
    "SQL_ONLY_SYSTEM",
    "summarize_results",
    "load_results",
    "comparison_report",
    "DISPOSABLE_SCHEMAS",
    "READ_ONLY_SCHEMAS",
    "PRODUCTION_SCHEMAS",
    "ExecutionGuardError",
    "assert_executable_schema",
    "is_disposable",
    "is_read_only",
    "disposable_credentials",
    "read_only_credentials",
    "classify_error_category",
]
