# Next steps after selecting `sql_only`

## Current decision

`sql_only-qlora` is the selected adapter. It achieved 24/150 (16.0%) on the
unchanged live-Oracle held-out catalog, exceeding the base-model, chat, and
error-repair runs. Treat it as the release candidate, not a final production
claim: its execution success rate leaves substantial room for improvement.

## Phase 1 — Freeze the release evidence

**Owner:** developer  
**Goal:** make the selection auditable without committing weights or secrets.

1. Read `artifacts/selected_adapter.json`, `artifacts/comparison_all.json`,
   and `artifacts/sql-only-qlora/{provenance,model_card}.json`.
2. Create `docs/reports/sql-only-selection-v1.md` containing only:
   base-model revision, adapter name, dataset hashes, training config summary,
   evaluation date, the five-run score table, promotion criteria, and known
   limitations. Do not copy candidate SQL, credentials, checkpoint paths, or
   model weights into the report.
3. Update `docs/MODEL_CARD.md` with the selected adapter and its 24/150 score.
4. Verify `.gitignore` excludes all `artifacts/` contents except `.gitkeep`;
   confirm no secret patterns, `*.safetensors`, candidates, or result JSONL
   files are staged.
5. Commit the project source, configs, tests, ADRs, runbook, model card, and
   selection report with a message such as `docs: record sql-only adapter selection`.

**Acceptance:** cloning the repository exposes the selection decision and
reproduction inputs but not any model artifact or credential.

## Phase 2 — Release-candidate serving validation

**Owner:** developer  
**Goal:** verify that the selected adapter is the one actually served.

1. Configure the service with the exact base-model revision and the
   `sql-only-qlora` adapter path, supplied through environment/configuration
   outside version control.
2. Run `scripts/serve.py` and assert `GET /health` returns the expected base
   model and adapter identifiers.
3. Exercise `POST /v1/chat/completions` in both modes:
   `sql_only` must return code without Markdown; `explain` may return prose.
4. Record latency, GPU memory, token throughput, startup time, and response
   errors for a fixed smoke-prompt set stored outside the held-out catalog.
5. Add a regression test that rejects a response containing Markdown fences in
   `sql_only` mode.

**Acceptance:** smoke tests use the real adapter; all API contract tests pass;
no secret or prompt body is logged by default.

## Phase 3 — Establish a repeatable benchmark gate

**Owner:** developer  
**Goal:** prevent regressions in future experiments.

1. Run the gold harness before every evaluation cycle; require 150/150 before
   trusting a model score.
2. Run the base-model baseline and selected-adapter evaluation with unchanged
   `llm_task_catalog_eval.jsonl`, temperature 0, and archived evaluator output
   under an ignored timestamped artifact directory.
3. Add a report generator that records: pass rate, executed-ok rate, exact
   result/checksum rate, schema/kind breakdown, and controlled-error accuracy.
4. Add a CI-safe test suite that checks data hashes, held-out deny-list rules,
   JSON schemas, and report parsing. Do not run Docker/Oracle or download a
   model in ordinary CI.
5. Define the next promotion threshold before running experiments: overall
   pass must exceed the selected adapter's 16.0%, controlled-error accuracy
   must be at least 6/25, and all provenance fields must be present.

**Acceptance:** a new candidate cannot be marked promoted without a passing
gold harness, a complete report, and the stated thresholds.

## Phase 4 — Improve data and model quality

**Owner:** ML developer + Oracle subject-matter expert  
**Goal:** raise executable Oracle correctness rather than merely language-model
loss.

1. Inspect the selected adapter's failed tasks by `schema`, `kind`, and Oracle
error. Use only the generated candidates and evaluator reports; do not add the
   held-out tasks or paraphrases to training data.
2. Build a failure taxonomy: syntax, wrong object/column, incorrect semantics,
   transaction/privilege behavior, PL/SQL structure, and controlled-error
   handling.
3. Author new training examples from independently designed schemas and tasks,
   validate each against the live Oracle instance, and place them in a new
   versioned training-only file with its own hashes and manifest.
4. Test focused improvements one at a time: higher-quality grounded SQL SFT,
   train-side catalog formatting, response-format enforcement, and a carefully
   weighted SQL + error-repair mixture. Pin all inputs and seeds.
5. Evaluate each run only once on the unchanged held-out catalog after model
   selection decisions are fixed; avoid repeatedly tuning to its score.

**Acceptance:** every new record is independently executable, split policy is
documented, and any promoted candidate clears the Phase 3 gate.

## Phase 5 — Production readiness

**Owner:** platform developer  
**Goal:** operate the selected adapter safely.

1. Add request-size limits, rate limits, timeouts, request IDs, and structured
   metrics to the serving layer.
2. Keep SQL generation separate from SQL execution. The service must never
   execute generated SQL using production database credentials.
3. Add authentication and authorization before exposing the API outside a
   trusted network.
4. Version the deployed base model, adapter, prompt policy, and API contract;
   provide rollback to the preceding adapter.
5. Monitor syntax-format failures, response latency, error rate, and user
   feedback. Store no raw sensitive prompts by default.

**Acceptance:** rollout/rollback is documented and tested; execution remains
an explicit, separately authorized action.
