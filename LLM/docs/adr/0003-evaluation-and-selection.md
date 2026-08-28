# ADR-0003: Evaluation and selection policy

Status: Accepted
Date: 2026-08-28

## Context

PLAN.md phases 3 and 4 require measuring candidate answers against live Oracle
and promoting only the best model using held-out execution pass rate — never
validation loss alone.

## Decision

- **Generation**: deterministic (`temperature=0`), SQL/PLSQL-only prompts for
  executable catalog scoring. Both an OpenAI-compatible endpoint backend and a
  direct Transformers backend (base model + LoRA adapter) are supported.
- **Execution evaluation**: reuse `evaluate_catalog.py` against the unchanged
  held-out catalog. It resets resettable schemas before each task, connects as
  the task's schema user, runs the answer + validation, and records
  pass/executed-ok/checksums. Read-only sample schemas (HR/CO) are never
  reset and must host read-only tasks.
- **Summaries**: overall pass rate, executed-ok rate, exact-result (checksum)
  rate, per-schema, per-kind, and controlled-error accuracy are computed
  machine-readably (`summarize_results`).
- **Selection**: a run is `candidate` until ALL hold: gold harness succeeds;
  dataset hashes match the frozen manifest; reproducible from config + base
  revision; no held-out violation; held-out execution accuracy improves on the
  base baseline with no material controlled-error regression
  (`check_promotion`).
- **Comparison discipline**: the base-model baseline and the gold harness are
  included in every comparison; a deliberately broken candidate must score
  below gold to prove the harness discriminates.

## Consequences

- Selection is auditable: `promotion.json` records status, reasons, checks, and
  the run/baseline/gold summaries.
- A model cannot be promoted on the strength of a low validation loss alone.
- All reports are machine-readable JSON, suitable for dashboards and CI gates.
