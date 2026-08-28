# sql_only selection report (v1)

Status: Accepted — release candidate
Date: 2026-08-28

## Decision

The **`sql_only`** LoRA adapter is selected as the release candidate. It
outperforms the base model, `chat`, and `error_repair` variants on the
unchanged 150-task held-out execution catalog, on both overall execution
accuracy and controlled-error performance.

## Reproduction inputs

- Base model: `Qwen/Qwen2.5-Coder-7B-Instruct`
- Base model revision: `c03e6d358207e414f1eca0bb1891e29f1db0e242` (pinned)
- Adapter: QLoRA (4-bit NF4), `r=16`, `alpha=32`, `dropout=0.05`,
  `target_modules=all-linear`, `bias=none`
- Training file: `oracle_train_code_only.jsonl` (160 examples)
- Validation holdout: `oracle_eval_holdout.jsonl` (18 examples, train-time only)
- Catalog: `llm_task_catalog_eval.jsonl` (150 tasks, strictly held out)
- Training seed: 42, epochs: 3, lr: 2e-4, max_length: 2048

## Dataset hashes (frozen MANIFEST.md)

The training/eval/catalog files are pinned in `MANIFEST.md`; the promotion
check verified the run's input hashes appear in the frozen manifest.

## Score table (live Oracle, temperature 0, SQL-only prompts)

| run | passed | % | executed_ok | exact | controlled-error |
|---|---|---|---|---|---|
| gold (sanity ceiling) | 150 | 100.0 | 125 | 125 | 25/25 |
| **sql_only (selected)** | **24** | **16.0** | **42** | **18** | **6/25** |
| chat | 16 | 10.7 | 33 | 11 | 5/25 |
| error_repair | 10 | 6.7 | 29 | 5 | 5/25 |
| base model baseline | 8 | 5.3 | 18 | 4 | 4/25 |

## Promotion criteria (all met)

- [x] Gold harness succeeds (150/150)
- [x] Held-out execution accuracy improves on baseline (16.0% > 5.3%)
- [x] No controlled-error regression (6/25 ≥ baseline 4/25)
- [x] Dataset hashes match frozen manifest
- [x] Reproducible from pinned config + base-model revision
- [x] No held-out-data violation (deny-list enforced at data ingest)

## Known limitations

- Absolute pass rate is 16.0% — this is a release candidate, not a
  production-quality model. The execution success rate leaves substantial room
  for improvement (see NEXT_STEPS.md Phase 4).
- Failures concentrate on DML (0/17) and PL/SQL/JSON (0/12) task kinds, and on
  the DOCUMENTS_LAB (0/24), LOGISTICS_LAB (0/5), and SUPPORT_LAB (0/5) schemas.
- Controlled-error accuracy is 6/25; error-repair training alone did not lift
  it (error_repair variant: 5/25).

## Artifacts (not committed — under ignored `artifacts/`)

- `artifacts/sql-only-qlora/` — adapter, checkpoints, provenance, model card
- `artifacts/comparison_all.json` — 5-run comparison
- `artifacts/promotion_sql-only-qlora.json` — promotion decision
- `artifacts/selected_adapter.json` — selection metadata

This report contains no credentials, no model weights, no candidate SQL, and no
checkpoint paths.
