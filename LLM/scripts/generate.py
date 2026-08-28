#!/usr/bin/env python3
"""Generate candidate answers (Phase 3)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from oracle_llm.cli import _cmd_generate
if __name__ == "__main__":
    _cmd_generate(sys.argv[1:])
