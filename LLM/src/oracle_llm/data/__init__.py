"""Data contract for the Oracle LLM training pipeline.

Responsibilities (Phase 1 of PLAN.md):
- Load chat (``messages``) and instruction-triplet (``instruction/input/output``)
  JSONL records.
- Validate mandatory keys, roles, UTF-8, non-empty answers, and duplicates.
- Compute a SHA-256 fingerprint for each input record and persist a manifest.
- Enforce the deny-list for the held-out execution catalog
  (``llm_task_catalog_eval.jsonl``): fail closed if it is ever supplied to a
  training or indexing command.
- Render prompts via a base tokenizer's chat template and mask loss on prompt
  tokens (supervision only on assistant tokens).
"""
from oracle_llm.data.loaders import load_jsonl, load_records
from oracle_llm.data.validate import (
    DataValidationError,
    fingerprint,
    validate_records,
)
from oracle_llm.data.format import (
    DEFAULT_SYSTEM,
    row_to_chat,
    render_prompt_and_answer,
    tokenize_supervised,
)
from oracle_llm.data.manifest import Manifest, record_hashes
from oracle_llm.data.guards import HOLD_OUT_FILE, assert_not_held_out, is_held_out

__all__ = [
    "load_jsonl",
    "load_records",
    "DataValidationError",
    "fingerprint",
    "validate_records",
    "DEFAULT_SYSTEM",
    "row_to_chat",
    "render_prompt_and_answer",
    "tokenize_supervised",
    "Manifest",
    "record_hashes",
    "HOLD_OUT_FILE",
    "assert_not_held_out",
    "is_held_out",
]
