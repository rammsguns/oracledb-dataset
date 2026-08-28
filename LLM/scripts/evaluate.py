#!/usr/bin/env python3
"""Summarize / compare evaluation results (Phase 3)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from oracle_llm.cli import _cmd_evaluate
if __name__ == "__main__":
    _cmd_evaluate(sys.argv[1:])
