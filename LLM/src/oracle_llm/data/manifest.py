"""Per-input SHA-256 manifest (Phase 1 data contract)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from oracle_llm.data.validate import fingerprint


def record_hashes(records: List[Dict[str, Any]]) -> Dict[str, str]:
    """Map record index -> SHA-256 fingerprint for every record."""
    return {str(i): fingerprint(r) for i, r in enumerate(records)}


class Manifest:
    """Persists per-input record hashes next to an experiment artifact.

    JSON layout::

        {
          "source_files": {path: sha256_of_raw_file},
          "record_hashes": {index: sha256_of_canonical_record},
          "record_count": N,
          "deny_list_checked": true
        }
    """

    def __init__(self, source_files: List[Path], records: List[Dict[str, Any]]):
        self.source_files = source_files
        self.records = records

    @staticmethod
    def _file_hash(path: Path) -> str:
        import hashlib

        h = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()

    def to_dict(self, deny_checked: bool = True) -> Dict[str, Any]:
        return {
            "source_files": {str(p): self._file_hash(p) for p in self.source_files},
            "record_hashes": record_hashes(self.records),
            "record_count": len(self.records),
            "deny_list_checked": deny_checked,
        }

    def save(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2) + "\n", encoding="utf-8")
        return path
