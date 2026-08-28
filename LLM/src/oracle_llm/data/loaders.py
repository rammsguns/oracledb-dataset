"""JSONL loading helpers for the Oracle LLM data contract."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, List


def load_jsonl(path: str | Path) -> List[dict]:
    """Load a JSONL file (one JSON object per line) into a list of dicts.

    Raises ValueError on malformed JSON or a non-dict line.
    """
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    out: List[dict] = []
    with path.open("r", encoding="utf-8") as handle:
        for lineno, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{lineno}: invalid JSON: {exc}") from exc
            if not isinstance(obj, dict):
                raise ValueError(f"{path}:{lineno}: expected JSON object, got {type(obj).__name__}")
            out.append(obj)
    return out


def load_records(paths: Iterable[str | Path]) -> List[dict]:
    """Load and concatenate records from one or more JSONL files."""
    records: List[dict] = []
    for p in paths:
        records.extend(load_jsonl(p))
    return records
