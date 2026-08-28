"""Validation and fingerprinting for training records (Phase 1 data contract)."""
from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List


class DataValidationError(ValueError):
    """Raised when a record fails the data contract."""


# Roles permitted inside a chat-style record.
CHAT_ROLES = {"system", "user", "assistant"}

# Keys that must be present in an instruction-triplet record.
TRIPLET_KEYS = {"instruction", "output"}


def fingerprint(record: Dict[str, Any]) -> str:
    """Deterministic SHA-256 over the record's stable, canonical JSON.

    Canonical form: keys sorted, ``ensure_ascii=False``. This is the identity
    used for dedupe and for the per-input manifest hashes.
    """
    canonical = json.dumps(record, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _validate_chat(record: Dict[str, Any], idx: int) -> None:
    messages = record.get("messages")
    if not isinstance(messages, list) or not messages:
        raise DataValidationError(f"record {idx}: 'messages' must be a non-empty list")
    last = messages[-1]
    if not isinstance(last, dict) or last.get("role") != "assistant":
        raise DataValidationError(f"record {idx}: chat row must end with an assistant message")
    for i, msg in enumerate(messages):
        if not isinstance(msg, dict):
            raise DataValidationError(f"record {idx}: message {i} is not an object")
        role = msg.get("role")
        if role not in CHAT_ROLES:
            raise DataValidationError(
                f"record {idx}: message {i} has invalid role {role!r} (allowed {sorted(CHAT_ROLES)})"
            )
        content = msg.get("content")
        if not isinstance(content, str) or not content.strip():
            raise DataValidationError(f"record {idx}: message {i} has empty content")


def _validate_triplet(record: Dict[str, Any], idx: int) -> None:
    missing = TRIPLET_KEYS - set(record.keys())
    if missing:
        raise DataValidationError(f"record {idx}: missing keys {sorted(missing)}")
    if not isinstance(record.get("instruction"), str) or not record["instruction"].strip():
        raise DataValidationError(f"record {idx}: 'instruction' must be non-empty")
    output = record.get("output")
    if not isinstance(output, str) or not output.strip():
        raise DataValidationError(f"record {idx}: 'output' must be a non-empty string")
    if "input" in record and record["input"] is not None and not isinstance(record["input"], str):
        raise DataValidationError(f"record {idx}: 'input' must be a string or absent")


def validate_records(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Validate a list of records; return it unchanged if all pass.

    Supports both chat and instruction-triplet formats (per record). Raises
    DataValidationError on the first malformed record and on duplicates
    (same canonical fingerprint).
    """
    seen: Dict[str, int] = {}
    for idx, rec in enumerate(records):
        if "messages" in rec:
            _validate_chat(rec, idx)
        elif "instruction" in rec or "output" in rec:
            _validate_triplet(rec, idx)
        else:
            raise DataValidationError(
                f"record {idx}: neither 'messages' nor 'instruction'/'output' present"
            )
        fp = fingerprint(rec)
        if fp in seen:
            raise DataValidationError(
                f"record {idx}: duplicate of record {seen[fp]} (same fingerprint)"
            )
        seen[fp] = idx
    return records
