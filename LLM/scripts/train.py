#!/usr/bin/env python3
"""Project-local training CLI (Phase 2)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from oracle_llm.cli import _cmd_train
if __name__ == "__main__":
    _cmd_train(sys.argv[1:])
