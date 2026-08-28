"""QLoRA / LoRA supervised fine-tuning (Phase 2).

Wraps the Transformers Trainer with PEFT LoRA. Supports:
- 4-bit QLoRA on CUDA (``load_in_4bit=True``)
- normal LoRA when not quantized
- three explicit variants: chat, sql_only, error_repair (driven by config)
- resumable checkpoints stored under the output dir

Every run writes adapter, tokenizer, resolved config, provenance, package
versions, git revision (if available), input hashes, and model-card metadata.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

import torch
from datasets import Dataset
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    BitsAndBytesConfig,
    DataCollatorForSeq2Seq,
    Trainer,
    TrainingArguments,
)

from oracle_llm.data.format import tokenize_supervised
from oracle_llm.data.loaders import load_records
from oracle_llm.data.validate import validate_records
from oracle_llm.training.config import TrainingConfig
from oracle_llm.training.provenance import (
    ExperimentProvenance,
    resolve_base_model_revision,
)


def _tokenize_dataset(
    records: List[dict], tokenizer, max_length: int
) -> Dataset:
    encoded = []
    for rec in records:
        example = tokenize_supervised(rec, tokenizer, max_length=max_length)
        if example is not None:
            encoded.append(example)
    if not encoded:
        raise ValueError("no usable examples after tokenization")
    return Dataset.from_list(encoded)


def _load_model(tokenizer, cfg: TrainingConfig):
    kwargs: dict = {}
    quantization = None
    if cfg.load_in_4bit:
        quantization = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.bfloat16,
        )
        kwargs.update(quantization_config=quantization, device_map="auto")
    elif torch.cuda.is_available():
        kwargs["torch_dtype"] = torch.bfloat16

    model = AutoModelForCausalLM.from_pretrained(cfg.base_model, **kwargs)
    model.config.use_cache = False
    if quantization:
        model = prepare_model_for_kbit_training(model)
    model = get_peft_model(
        model,
        LoraConfig(
            r=cfg.lora_r,
            lora_alpha=cfg.lora_alpha,
            lora_dropout=cfg.lora_dropout,
            bias="none",
            task_type="CAUSAL_LM",
            target_modules="all-linear",
        ),
    )
    return model, quantization


def _training_args(cfg: TrainingConfig, output_dir: Path, eval_exists: bool) -> TrainingArguments:
    use_bf16 = torch.cuda.is_available() and torch.cuda.is_bf16_supported()
    return TrainingArguments(
        output_dir=str(output_dir),
        num_train_epochs=cfg.epochs,
        learning_rate=cfg.learning_rate,
        per_device_train_batch_size=cfg.per_device_batch_size,
        per_device_eval_batch_size=cfg.per_device_batch_size,
        gradient_accumulation_steps=cfg.gradient_accumulation,
        logging_steps=5,
        save_strategy="epoch",
        eval_strategy="epoch" if eval_exists else "no",
        bf16=use_bf16,
        fp16=torch.cuda.is_available() and not use_bf16,
        seed=cfg.seed,
        report_to="none",
        remove_unused_columns=False,
        run_name=f"oracle-{cfg.train_variant}",
    )


def _write_model_card(cfg: TrainingConfig, output_dir: Path) -> Path:
    card = {
        "model": "Oracle Database assistant (LoRA adapter)",
        "base_model": cfg.base_model,
        "base_model_revision": cfg.base_model_revision,
        "adapter": cfg.adapter,
        "train_variant": cfg.train_variant,
        "max_length": cfg.max_length,
        "epochs": cfg.epochs,
        "learning_rate": cfg.learning_rate,
        "seed": cfg.seed,
        "lora": {"r": cfg.lora_r, "alpha": cfg.lora_alpha, "dropout": cfg.lora_dropout},
        "train_file": cfg.train_file,
        "eval_file": cfg.eval_file,
        "notes": (
            "Fine-tuned from an open instruction base model with QLoRA SFT. "
            "Do NOT train on the held-out execution catalog."
        ),
    }
    path = output_dir / "model_card.json"
    path.write_text(json.dumps(card, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def train_qlora(
    cfg: TrainingConfig,
    output_dir: str | Path,
    *,
    eval_records: Optional[List[dict]] = None,
) -> Dict:
    """Run a QLoRA/LoRA SFT experiment. Returns a summary dict of artifacts.

    ``eval_records`` are the validation holdout records (optional); when absent
    no eval split is used (e.g. smoke runs).
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    if not torch.cuda.is_available() and cfg.load_in_4bit:
        raise RuntimeError("--load-in-4bit (QLoRA) requires a CUDA-capable NVIDIA GPU")

    # --- Tokenizer + model ------------------------------------------------
    tokenizer = AutoTokenizer.from_pretrained(cfg.base_model, use_fast=True)
    if tokenizer.chat_template is None:
        raise ValueError("base model must have a tokenizer chat template")
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "right"

    model, quantization = _load_model(tokenizer, cfg)
    model.print_trainable_parameters()

    # --- Datasets ----------------------------------------------------------
    train_sources = [cfg.train_file] if not cfg.mixture else [m["file"] for m in cfg.mixture]
    train_records = validate_records(load_records(train_sources))
    train_ds = _tokenize_dataset(train_records, tokenizer, cfg.max_length)
    eval_ds = None
    if eval_records:
        eval_records = validate_records(eval_records)
        eval_ds = _tokenize_dataset(eval_records, tokenizer, cfg.max_length)

    args = _training_args(cfg, output_dir, eval_ds is not None)
    trainer = Trainer(
        model=model,
        args=args,
        train_dataset=train_ds,
        eval_dataset=eval_ds,
        data_collator=DataCollatorForSeq2Seq(tokenizer, padding=True, label_pad_token_id=-100),
    )
    trainer.train(resume_from_checkpoint=None)
    trainer.save_model(str(output_dir))
    tokenizer.save_pretrained(str(output_dir))

    # --- Metadata ----------------------------------------------------------
    if cfg.base_model_revision is None:
        cfg.base_model_revision = resolve_base_model_revision(cfg.base_model)
    cfg.output_dir = str(output_dir)

    provenance = ExperimentProvenance.build(
        base_model=cfg.base_model,
        base_model_revision=cfg.base_model_revision,
        train_variant=cfg.train_variant,
        train_files=[Path(p) for p in train_sources],
        eval_file=Path(cfg.eval_file) if cfg.eval_file else None,
        config=cfg.to_dict(),
        seed=cfg.seed,
        cwd=Path.cwd(),
    )
    provenance.save(output_dir / "provenance.json")
    (output_dir / "config.json").write_text(
        json.dumps(cfg.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    card_path = _write_model_card(cfg, output_dir)

    summary = {
        "output_dir": str(output_dir),
        "train_examples": len(train_ds),
        "eval_examples": len(eval_ds) if eval_ds is not None else 0,
        "adapter": str(output_dir / "adapter_model.safetensors"),
        "tokenizer": str(output_dir / "tokenizer_config.json"),
        "config": str(output_dir / "config.json"),
        "provenance": str(output_dir / "provenance.json"),
        "model_card": str(card_path),
    }
    print(json.dumps(summary, indent=2))
    return summary
