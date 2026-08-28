#!/usr/bin/env python3
"""Leakage-guarded training data validator (Phase 1)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from oracle_llm.cli import _cmd_validate
if __name__ == "__main__":
    _cmd_validate(sys.argv[1:])
