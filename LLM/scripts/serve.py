#!/usr/bin/env python3
"""Start the OpenAI-compatible API (Phase 5)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from oracle_llm.cli import _cmd_serve
if __name__ == "__main__":
    _cmd_serve(sys.argv[1:])
