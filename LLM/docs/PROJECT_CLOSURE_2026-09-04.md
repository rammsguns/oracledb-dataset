# Oracle SQL LLM — Project Closure Record

**Closure date:** 2026-09-04

**Project status:** COMPLETE — learning-stage release and on-demand operation

**Selected system:** `sql-only-rag-v1.0.8`

## 1. Closure decision

The Oracle SQL LLM learning project has met its defined objective: train an
Oracle SQL adapter, compare challengers, select a champion, validate the
generation-only application surface, provide a protected learning UI, and
publish the selected adapter to Hugging Face.

No additional training or evaluation is required to close this milestone.
Any future accuracy work is a new Candidate C initiative with a new evaluation
cycle; it is not unfinished work on this release.

## 2. Final released state

- Selected adapter: `sql_only` LoRA adapter.
- Selected runtime: `sql-only-rag-v1.0.8`.
- Base model: `Qwen/Qwen2.5-Coder-7B-Instruct`.
- Pinned base revision:
  `c03e6d358207e414f1eca0bb1891e29f1db0e242`.
- Retrieval: whole-schema context with sequence metadata.
- Ranked retrieval: off.
- Serving boundary: generation only; generated SQL is never executed by the
  model-serving process.
- Repository main integration: `origin/main` was verified at merge commit
  `2cdf99de5d352244fe6dc15eb6053e868ad7ace1` after v1.0.8.
- Hugging Face adapter repository:
  `rammsguns/oracle-sql-assistant-7b-lora`.
- Hugging Face visibility at closure: private.
- Verified Hub commit:
  `a57b9b7bc2bac11904f1875a9d11300dd07b1373`.
- License: Apache-2.0.

The Hugging Face repository contains the adapter only. The schema retriever,
schema index, serving API, UI, and SQL safety boundary remain separate project
components.

## 3. Final evaluation decision

### Frozen development benchmark

| Configuration | Passed | Controlled error |
|---|---:|---:|
| Selected adapter + sequence-enabled RAG | 56/150 (37.3%) | 15/25 |
| Adapter without retrieval | 24/150 (16.0%) | 6/25 |
| Base model | 8/150 (5.3%) | 4/25 |

### Process-isolated simulated comparison

| Candidate | Passed | Controlled error | Safety violations |
|---|---:|---:|---:|
| Candidate A: `sql-only-rag` | 24/28 (85.7%) | 4/5 | 0 |
| Candidate B: `sql-only-errmix-rag` | 21/28 (75.0%) | 4/5 | 0 |

Decision: retain Candidate A. This was process-isolated simulated evaluation,
not infrastructure-isolated third-party validation. Aggregate evidence may be
retained, but private evaluation content must remain undisclosed and frozen.

## 4. Validation completed

- Gold evaluation harness validation completed.
- Candidate selection and promotion gates completed.
- Application health, SQL-only mode, explanation mode, request guards,
  rate limiting, metrics, retrieval monitoring, schema-detection monitoring,
  log redaction, and rollback validated.
- Learning soak accepted with zero server errors, retrieval misses, refusals,
  CUDA failures, or safety violations.
- Generation and SQL execution remain separated.
- Adapter bundle checksums verified after a clean Hugging Face download.
- PEFT loading and generation smoke test passed against the pinned base model.
- Learning UI authentication was user-validated.

## 5. Operational handoff

Operate the system on demand only:

1. Start it using the pinned command in `HANDOFF_2026-08-31.md`.
2. Keep the model API bound to `127.0.0.1`; expose only the authenticated UI
   to a trusted LAN when needed.
3. Check `/health` and `/metrics` before use.
4. Do not put Oracle credentials, wallets, prompts, generated SQL, or schema
   DDL in model-server logs.
5. Never execute generated SQL automatically. Human review and a separately
   restricted execution environment are required.
6. Stop the UI and model server after the learning session and confirm their
   ports and GPU resources are released.

Do not expose the unauthenticated model API or either service to the public
internet.

## 6. Accepted limitations

- This is a learning/research system, not a production-grade Oracle automation
  service.
- The adapter alone scored 16.0% on the frozen development benchmark; the
  selected RAG system scored 37.3%.
- Correct schema detection and current schema metadata materially affect
  output quality.
- Generated SQL can be syntactically valid yet semantically incorrect.
- DML, PL/SQL, JSON, schema naming, and longer generations remain important
  failure areas.
- CPU inference is slow; CUDA is the intended runtime.
- LAN access requires authentication and careful bind-address control.

## 7. Information-retention rules

Retain:

- Source, tests, configuration, release tags, governance documentation, model
  card, runbook, hashes, and aggregate evaluation reports.
- The selected adapter in controlled local storage and its Hugging Face model
  repository.
- Sanitized operational reports needed to reproduce the release decision.

Do not publish or commit:

- Oracle passwords, `.env` files, wallets, connection bundles, or tokens.
- Private evaluation tasks, schema content, seed data, gold SQL, per-task
  results, or private schema indexes.
- Training checkpoints, optimizer state, transient candidates/results, or the
  large offline evaluator archive.

## 8. Final repository review required

Before making a final archival documentation commit, review the authoritative
Git clone's untracked files individually. In particular, do not bulk-add the
working tree. The known untracked UI, tests, readiness reports, deployment
reports, and `llm-creation/` directory require an explicit keep/archive/delete
decision. Existing user files must not be removed as part of closure without
separate approval.

## 9. Closure checklist

- [x] Champion selected and recorded.
- [x] Rejected challenger recorded as non-promoted.
- [x] v1.0.8 published and merged into main.
- [x] Application validation and soak accepted.
- [x] Generation/execution separation verified.
- [x] On-demand startup and shutdown documented.
- [x] Adapter published privately to Hugging Face and clean-download tested.
- [x] No model service needs to remain running for project closure.
- [ ] Principal reviews the rendered private Hugging Face model card.
- [ ] Principal decides whether the Hugging Face repository remains private or
      is made public.
- [ ] Principal decides which untracked UI and operational documents should be
      archived in a separate documentation/application release.
- [ ] Hugging Face write credentials are removed from shared machines when no
      longer required.

## 10. Reopening criteria

Reopen this project only for an operational defect or security issue in the
released v1.0.8 system. Treat new quality work as Candidate C with a declared
objective, fixed development gate, separate release branch, and a newly
governed final comparison.
