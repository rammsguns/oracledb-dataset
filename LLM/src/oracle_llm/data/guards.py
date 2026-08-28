"""Split-guard / deny-list for the held-out execution catalog.

The 150-task ``llm_task_catalog_eval.jsonl`` is the held-out execution
benchmark. It must never be used for training, indexing, prompt examples, or
deriving synthetic variants. This module enforces the policy: any command that
would ingest a training/indexing file must call ``assert_not_held_out`` and
fail closed if the denied file (or any record whose content matches a held-out
task) is present.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

# Canonical filename of the held-out execution catalog.
HOLD_OUT_FILE = "llm_task_catalog_eval.jsonl"

# Any path whose final component matches this name is denied.
DENY_NAMES = {HOLD_OUT_FILE}


def is_held_out(path: str | Path) -> bool:
    """True if the given path is the held-out execution catalog by filename."""
    return Path(path).name in DENY_NAMES


def assert_not_held_out(paths: Iterable[str | Path]) -> None:
    """Raise ValueError if any supplied path is the held-out catalog.

    Fails closed: an explicit deny is always safer than a silent ingest.
    """
    denied = [str(p) for p in paths if is_held_out(p)]
    if denied:
        raise ValueError(
            "Refusing to use held-out execution catalog as training/indexing "
            f"input: {denied}. {HOLD_OUT_FILE} is strictly held out (see "
            "LLM/PLAN.md guardrails)."
        )
