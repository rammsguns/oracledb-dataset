#!/usr/bin/env python3
"""Apply the selection/promotion policy (Phase 4)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from oracle_llm.cli import _cmd_promote
if __name__ == "__main__":
    _cmd_promote(sys.argv[1:])
