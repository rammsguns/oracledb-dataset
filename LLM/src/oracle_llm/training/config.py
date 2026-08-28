"""Training configuration loading and resolution (Phase 2)."""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from oracle_llm.data.guards import assert_not_held_out

# Variants this pipeline supports explicitly. Mixing requires a config that
# lists sources and weights — never implicit blending.
SUPPORTED_VARIANTS = {"chat", "sql_only", "error_repair"}

# Map variant name -> data.yaml key pointing at the source file.
_VARIANT_DATA_KEYS = {
    "chat": "train_chat",
    "sql_only": "train_sql_only",
    "error_repair": "train_error_repair",
}


@dataclass
class TrainingConfig:
    """Resolved training configuration.

    Field names mirror the training YAML (see configs/training/qlora-7b.yaml)
    plus resolved paths and the data policy.
    """

    base_model: str
    adapter: str = "lora"
    load_in_4bit: bool = True
    max_length: int = 2048
    epochs: float = 3.0
    learning_rate: float = 2e-4
    per_device_batch_size: int = 1
    gradient_accumulation: int = 16
    seed: int = 42
    train_variant: str = "chat"
    # Lora hyper-parameters
    lora_r: int = 16
    lora_alpha: int = 32
    lora_dropout: float = 0.05
    # Resolved at runtime
    train_file: Optional[str] = None
    eval_file: Optional[str] = None
    output_dir: Optional[str] = None
    base_model_revision: Optional[str] = None
    mixture: List[Dict[str, Any]] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = {k: v for k, v in self.__dict__.items() if k != "raw"}
        d["raw"] = self.raw
        return d


def _resolve_rel(path: str, base_dir: Path) -> Path:
    p = Path(path)
    return p if p.is_absolute() else (base_dir / p)


def load_config(
    config_path: str | Path,
    *,
    data_yaml: Optional[str | Path] = None,
    cwd: Optional[Path] = None,
    output_dir: Optional[str] = None,
) -> TrainingConfig:
    """Load a training YAML plus the data policy file and resolve paths.

    ``cwd`` is the directory relative paths resolve against (default: the
    config file's directory's parent, i.e. the LLM/ dir when configs/training
    is used). ``data_yaml`` defaults to ``<cwd>/configs/data.yaml``.
    """
    config_path = Path(config_path)
    # Resolve against the caller's working directory (the LLM/ dir per the
    # developer instructions). Relative data.yaml paths are anchored there.
    base_dir = cwd or Path.cwd()
    cfg = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}

    variant = str(cfg.get("train_variant", "chat"))
    if variant not in SUPPORTED_VARIANTS:
        raise ValueError(
            f"train_variant {variant!r} not supported; use one of {sorted(SUPPORTED_VARIANTS)}"
        )

    if data_yaml is None:
        data_yaml = base_dir / "configs" / "data.yaml"
    data = yaml.safe_load(Path(data_yaml).read_text(encoding="utf-8")) or {}

    data_key = _VARIANT_DATA_KEYS[variant]
    train_rel = data.get(data_key)
    if not train_rel:
        raise ValueError(f"data.yaml has no {data_key!r} for variant {variant!r}")

    # Explicit mixture (list of {file, weight}); when present it overrides the
    # single train_file. Deny-list is enforced on every source.
    mixture = cfg.get("mixture") or []
    resolved_mixture: List[Dict[str, Any]] = []
    if mixture:
        for src in mixture:
            rel = src["file"]
            assert_not_held_out([rel])
            resolved_mixture.append({"file": str(_resolve_rel(rel, base_dir)),
                                     "weight": float(src.get("weight", 1.0))})
    else:
        assert_not_held_out([train_rel])

    resolved = TrainingConfig(
        base_model=cfg.get("base_model"),
        adapter=cfg.get("adapter", "lora"),
        load_in_4bit=bool(cfg.get("load_in_4bit", True)),
        max_length=int(cfg.get("max_length", 2048)),
        epochs=float(cfg.get("epochs", 3)),
        learning_rate=float(cfg.get("learning_rate", 2e-4)),
        per_device_batch_size=int(cfg.get("per_device_batch_size", 1)),
        gradient_accumulation=int(cfg.get("gradient_accumulation", 16)),
        seed=int(cfg.get("seed", 42)),
        train_variant=variant,
        lora_r=int(cfg.get("lora_r", 16)),
        lora_alpha=int(cfg.get("lora_alpha", 32)),
        lora_dropout=float(cfg.get("lora_dropout", 0.05)),
        train_file=str(_resolve_rel(train_rel, base_dir)),
        eval_file=str(_resolve_rel(data.get("validation", ""), base_dir))
        if data.get("validation")
        else None,
        output_dir=output_dir,
        base_model_revision=cfg.get("base_model_revision"),
        mixture=resolved_mixture,
        raw=cfg,
    )
    return resolved


def resolve_train_file(cfg: TrainingConfig) -> Path:
    """Return the validated training file path, raising if missing."""
    p = Path(cfg.train_file)
    if not p.is_file():
        raise FileNotFoundError(f"training file not found: {p}")
    return p


def main_help() -> None:
    """Print CLI help (works without a GPU / model load)."""
    print(
        "oracle-llm train --config configs/training/qlora-7b.yaml [--output-dir artifacts/run]\n"
        "  variant (from config): chat | sql_only | error_repair\n"
        "  requires: base_model, train_variant, explicit output-dir for a real run"
    )
