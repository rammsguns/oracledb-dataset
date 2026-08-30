# Release-Readiness Review — Evaluation/Governance Decision (2026-08-30)

**Branch:** `gov/ieo-eval-decision` (based on clean `origin/main` = `a19c84d`)
**Type:** evaluation / governance decision — **NOT a model release**
**Verdict:** READY FOR REVIEW (not yet committed/pushed)

## Decision recorded

- **Selected:** `sql-only-rag` (Candidate A, incumbent) — unchanged.
- **Rejected:** `sql-only-errmix-rag` (Candidate B) — archived as non-promoted.
- Only **aggregate scores + integrity hashes**; no private evaluator content.

## Scoped diff (vs origin/main)

```
LLM/docs/CHANGELOG.md           | 18 ++++++++++++++++++
LLM/docs/MODEL_CARD.md          | 10 ++++++++++
LLM/docs/RELEASE_GOVERNANCE.md  | 16 ++++++++++------
LLM/docs/reports/eval-decision-A-vs-B-2026-08-30.md   (new)
3 files changed, 38 insertions(+), 6 deletions(-)   + 1 new report
```

## Validation performed (from the clone on this branch)

| check | result |
|---|---|
| Pristine test suite (`pytest tests/`) | **54 passed, 2 skipped** (2 skips = artifact-dependent CI guards) |
| Secret/credential scan of changed docs | **Clean** — no passwords, env creds, wallets, `.env` |
| Private-content scan | **Clean** — no private catalog/SQL/schema/gold/per-task content |
| Candidate A serving smoke (real model + RAG) | **All staging smoke checks PASS** (health, sql_only SQL, no-Markdown, explain, 4xx, metrics) |
| Metrics endpoint | `error_rate=0.0, retrieval_misses=0, sql_only=1` |
| Rollback test (v1.0.1: sql_only-qlora, no retrieval) | **PASS** — /health reports v1.0.1 adapter; sql_only completion works |
| Candidate A / B adapter weights integrity | A = `sql-only-qlora` (28281125…); B = `candB_bundle` `a9284ffd…` (documented) |

## Release checklist (RELEASE_GOVERNANCE §2)

- [x] Based on clean `origin/main`
- [x] Contains ONLY safe files (docs/reports) — no artifacts, weights, candidates, results, credentials
- [x] Secret scan clean
- [x] Pristine test suite passes
- [x] Champion not changed (governance decision only)
- [x] CHANGELOG.md and MODEL_CARD.md updated
- [ ] **Awaiting explicit approval to commit/push/tag/merge**

## Boundary confirmation

- No IEO_FINAL / private evaluation content was accessed.
- No training/retrieval/index change; no deployment change.
- Candidate B not tuned using any evaluation outcome.
- Private final set frozen as regression-only (not a promotion target).

## Blocked on approval

Per standing governance, this branch is **not committed, pushed, tagged,
merged, or deployed** without explicit approval. After approval it is
published as an **evaluation/governance release** (not a new model release),
keeping Candidate A deployed.
