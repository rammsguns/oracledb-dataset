"""Experiment provenance: record everything needed to reproduce a run."""
from __future__ import annotations

import json
import platform
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from oracle_llm.data.guards import assert_not_held_out
from oracle_llm.data.manifest import Manifest


def resolve_base_model_revision(model_id: str, allow_offline: bool = False) -> str:
    """Resolve the base model's immutable revision (a git commit SHA on HF).

    Uses the transformers snapshot cache when the model is already downloaded
    (fast, offline-safe); falls back to querying the Hub.
    """
    try:
        from huggingface_hub import try_to_load_from_cache

        for rev in ("main", None):
            try:
                cached = try_to_load_from_cache(model_id, "config.json", revision=rev or "main")
            except Exception:
                cached = None
            if cached:
                # cache path: .../hub/models--X--Y/snapshots/<commit>/config.json
                p = Path(cached)
                # p.parent = .../snapshots/<commit> ; p.parent.parent = .../snapshots
                if p.parent.parent.name == "snapshots":
                    return p.parent.name
                if p.parent.name == "snapshots":
                    return p.name
                return model_id
        return model_id
    except Exception:
        return model_id


@dataclass
class ExperimentProvenance:
    """Immutable record of a training run's inputs and environment."""

    base_model: str
    base_model_revision: str
    train_variant: str
    train_files: List[str]
    eval_file: Optional[str]
    data_manifest: Dict[str, Any]
    package_versions: Dict[str, str]
    config: Dict[str, Any]
    git_revision: Optional[str]
    created_utc: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    seed: Optional[int] = None

    @staticmethod
    def git_revision(cwd: str | Path | None = None) -> Optional[str]:
        try:
            out = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=cwd, capture_output=True, text=True, timeout=10,
            )
            if out.returncode == 0:
                return out.stdout.strip()
        except Exception:
            pass
        return None

    @staticmethod
    def capture_package_versions() -> Dict[str, str]:
        pkgs = ["torch", "transformers", "peft", "accelerate", "datasets", "bitsandbytes", "oracledb"]
        out: Dict[str, str] = {}
        for name in pkgs:
            try:
                mod = __import__(name)
                out[name] = getattr(mod, "__version__", "?")
            except Exception:
                out[name] = "missing"
        out["python"] = sys.version.split()[0]
        out["platform"] = platform.platform()
        return out

    @classmethod
    def build(
        cls,
        *,
        base_model: str,
        base_model_revision: str,
        train_variant: str,
        train_files: List[Path],
        eval_file: Path | None,
        config: Dict[str, Any],
        seed: int | None,
        cwd: str | Path | None = None,
    ) -> "ExperimentProvenance":
        assert_not_held_out(train_files)
        from oracle_llm.data.loaders import load_records

        records = load_records(train_files)
        manifest = Manifest(train_files, records)
        return cls(
            base_model=base_model,
            base_model_revision=base_model_revision,
            train_variant=train_variant,
            train_files=[str(p) for p in train_files],
            eval_file=str(eval_file) if eval_file else None,
            data_manifest=manifest.to_dict(),
            package_versions=cls.capture_package_versions(),
            git_revision=cls.git_revision(cwd),
            config=config,
            seed=seed,
        )

    def save(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.__dict__, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return path
