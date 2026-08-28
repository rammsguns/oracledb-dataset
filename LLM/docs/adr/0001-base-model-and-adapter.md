# ADR-0001: Base model family and adapter approach

Status: Accepted
Date: 2026-08-28

## Context

PLAN.md requires a "safe, measurable Oracle Database assistant that emits
executable Oracle SQL/PLSQL and can explain or repair database errors," starting
from an open instruction base model and producing a LoRA adapter, not a new
foundation model.

## Decision

- **Approach**: QLoRA (4-bit NF4) supervised fine-tuning producing a PEFT LoRA
  adapter on top of an existing instruction model. The dataset (160 chat /
  160 code-only / 56 repair examples) is far too small to train a foundation
  model from scratch.
- **Base model**: `Qwen/Qwen2.5-Coder-7B-Instruct`
  - Code-oriented instruct model with a tokenizer chat template (required).
  - 7B size fits comfortably in QLoRA on the available dual RTX A4000 (16 GB
    each) with `device_map="auto"` (~8–10 GB VRAM), leaving headroom.
  - Revision pinned (`c03e6d3582...`) for reproducibility.
- **Hardware budget**: dual NVIDIA RTX A4000, 123 GB RAM, 32 cores. QLoRA 7B
  spreads across both GPUs; a 3-epoch chat run takes ~6 minutes.

## Alternatives considered

- Foundation-model training from scratch: rejected (dataset too small).
- Full (non-quantized) 7B fine-tuning: heavier VRAM than needed; QLoRA is
  sufficient for adapter-grade SFT.
- A 27B model (qwen3.8-27b already present in the rig): not used as the
  fine-tune base because the 7B coder instruct model matches the code-tuned
  objective, fits the GPUs with margin, and provides an apples-to-apples
  baseline.

## Consequences

- Adapters are small, cheap to store, version, and swap — enabling the
  Phase 4 selection and Phase 9 rollback workflows.
- The base-model revision is pinned so any adapter is reproducible from
  config + provenance.
- Training never reads the held-out execution catalog (deny-list enforced).
