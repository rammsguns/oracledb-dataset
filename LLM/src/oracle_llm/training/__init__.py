"""Training package for the Oracle LLM pipeline (Phase 2)."""
from oracle_llm.training.config import TrainingConfig, load_config, resolve_train_file
from oracle_llm.training.provenance import (
    ExperimentProvenance,
    resolve_base_model_revision,
)
from oracle_llm.training.train import train_qlora
from oracle_llm.training.selection import (
    PromotionError,
    SelectionDecision,
    check_promotion,
    check_promotion_thresholds,
    DEFAULT_PROMOTION_THRESHOLDS,
)

__all__ = [
    "TrainingConfig",
    "load_config",
    "resolve_train_file",
    "ExperimentProvenance",
    "resolve_base_model_revision",
    "train_qlora",
    "PromotionError",
    "SelectionDecision",
    "check_promotion",
    "check_promotion_thresholds",
    "DEFAULT_PROMOTION_THRESHOLDS",
]
