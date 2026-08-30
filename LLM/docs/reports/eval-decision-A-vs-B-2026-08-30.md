# Evaluation Decision — Candidate A vs Candidate B (2026-08-30)

**Status:** **RECORDED** — Candidate A (`sql-only-rag`) remains the selected
champion; Candidate B (`sql-only-errmix-rag`) is **rejected** as a
non-promoted experiment.

**Scope:** evaluation / governance decision only. This is **not** a model
release and does not change the deployed adapter. It records the outcome of the
Candidate A vs Candidate B comparison in the development evaluation boundary
and the archive state of Candidate B.

## 1. Decision

- **Selected:** `sql-only-rag` (Candidate A, incumbent) — unchanged.
- **Rejected:** `sql-only-errmix-rag` (Candidate B) — archived as a
  non-promoted experiment.

Reason (governance-grounded, not a private-outcome leak): per
`docs/BENCHMARK_GOVERNANCE.md` §4 and the Candidate B bundle's own boundary
statement (§10), the frozen **150-task development benchmark is not a release
or promotion decision**. Candidate B was evaluated only on that development
benchmark; it was **not** validated on the independently-owned final set and
showed a documented, real regression on the CO schema. Promotion therefore
fails the governance gate, and the champion remains unchanged. No private
evaluation content was accessed to make or record this decision.

## 2. Aggregate development-benchmark results (frozen 150-task dev benchmark)

Both runs generated and evaluated fresh under identical conditions (same
schema index, same decoding, same live-Oracle scoring harness). These are the
development-side aggregate scores only — they are not a private final-set
result and are not treated as a release decision.

| metric | Candidate A (incumbent) | Candidate B (shipped, v2) | Δ |
|---|---|---|---|
| passed | 56/150 (37.33%) | 60/150 (40.00%) | +4 (+2.67 pp) |
| executed_ok | 105/150 (70.00%) | 86/150 (57.33%) | −19 |
| exact_result (checksum) | 41/150 (27.33%) | 39/150 (26.00%) | −2 |
| controlled_error (25 tasks) | 15/25 | 21/25 | +6 |
| by_schema: CO | **9/30** | **2/30** | **−7 (regression)** |
| by_schema: SALES_LAB | 12/39 | 16/39 | +4 |

Candidate B gains on aggregate pass rate and controlled-error accuracy but
regresses on the CO schema (2/30 vs 9/30) and on executed_ok (70% → 57.33%).
Per the governance boundary (§1), these development-benchmark numbers do not
alone justify promotion, and the CO regression is a disqualifying concern for
an un-indexed schema. See the archived bundle
`artifacts/candB_bundle/CANDIDATE_B_BUNDLE.md` (§8, §9) for the full table and
limitations.

## 3. Integrity hashes (Candidate B archive)

Candidate B's shippable adapter and the archived bundle are pinned by SHA-256
(verified at packaging time — 22/22 OK):

- `adapter/adapter_model.safetensors`:
  `a9284ffd2a47da1656a2a17608468dcebaa389f373c3425ebd0ae82037b9d6e4`
- `adapter/provenance.json`:
  `8efac57ab528aa149a69d36de554c73331c5e8ede617bee65e00211e7b16183b`
- `index/schema_index_v2_dev.json`:
  `eb2da5929ea5344af92bf15093ca3c967da74083095ee6ee2f031a11cc92fc5e`
- Full table: `artifacts/candB_bundle/SHA256SUMS.txt`.

Base-model revision (identical for both candidates):
`Qwen/Qwen2.5-Coder-7B-Instruct` @
`c03e6d358207e414f1eca0bb1891e29f1db0e242`.

## 4. What is deliberately NOT included

Per the evaluation boundary, this decision record contains **only aggregate
scores and integrity hashes**. It excludes all private evaluator content:
the private catalog, per-task SQL, schema definitions, indexes, prompts,
gold answers, and per-task results. No such content was accessed.

## 5. Archive state

Candidate B is archived at `artifacts/candB_bundle/` as a **non-promoted
experiment**. It is not tuned further using any evaluation outcome. The
private final set (independent owner) is frozen as **regression-only** and is
not a promotion target.
