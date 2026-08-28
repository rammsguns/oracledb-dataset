# ADR-0002: Data contract and held-out separation

Status: Accepted
Date: 2026-08-28

## Context

Phase 1 requires loaders, schema validation, formatting, and split guards so
that training never leaks the held-out execution benchmark. The developer
instructions list `llm_task_catalog_eval.jsonl` as a 150-task held-out set that
must never be trained on, derived from, indexed, or placed in retrieval.

## Decision

- **Formats**: accept both chat (`messages` list ending in an assistant turn)
  and instruction-triplet (`instruction/input/output`) JSONL records.
- **Validation**: enforce mandatory keys, valid roles, non-empty answers,
  UTF-8, and duplicate rejection (by canonical SHA-256 fingerprint).
- **Manifest**: every experiment persists a JSON manifest with per-source-file
  SHA-256 and per-record hashes (`Manifest`, `record_hashes`).
- **Split guard**: `assert_not_held_out()` fails closed if the held-out catalog
  filename is supplied to any training/indexing command. This is a mechanical
  floor — README rule #1 (process) is the guarantee against paraphrased
  near-duplicates, which the exact-match guard cannot catch.
- **Loss masking**: supervision is masked to assistant tokens only (`-100` on
  prompt tokens), so the model learns to produce answers, not echo prompts.

## Consequences

- Reproducibility: a run's exact inputs are recoverable from `provenance.json`
  and the frozen MANIFEST hashes.
- Safety: an accidental ingest of the held-out catalog is rejected before any
  tokenization or training begins.
- The small `oracle_eval_holdout.jsonl` (18 records) is used only for training
  loss / early stopping, never for final selection.
