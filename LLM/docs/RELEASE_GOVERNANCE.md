# Release Governance — Oracle Database LLM

This document defines how a release branch is reviewed, approved, merged into
`main`, and published, and how a tested rollback target is maintained.

## 1. Branch model

- `main` — the canonical, always-green branch. Holds the frozen dataset/catalog
  and, once merged, the LLM release. Currently `main` is at the original
  dataset release (`a8b7add`, v1.0.0).
- `release/llm-vX.Y.Z` — a release branch created from the previous release tag
  (or from `main`), carrying only the safe source/docs/config/tests for that
  version. It is tagged `oracle-llm-vX.Y.Z` when approved.
- Tags `oracle-llm-vX.Y.Z` — immutable release points.
- LLM work is NEVER pushed directly to `main`; it lands on `main` only via an
  approved release branch.

## 2. Release-branch review checklist

Before tagging/publishing a release branch, verify all of:

- [ ] Created from the correct base (previous release tag or `main`).
- [ ] Contains ONLY safe files: source, configs, tests, docs, reports. No
      artifacts, no model weights (`.safetensors`), no generated candidates or
      result JSONLs, no credentials, no `llm-creation/` or other unrelated
      files.
- [ ] No credential values committed (secret scan clean; only env-var names).
- [ ] Full pristine-tree test suite passes (`pytest tests/` from the release
      branch's `LLM/`, with `artifacts/` absent so artifact-dependent tests
      skip).
- [ ] The held-out execution catalog (`llm_task_catalog_eval.jsonl`) was never
      used for training/retrieval (deny-list enforced).
- [ ] Champion is promoted by the gate (if a model change): held-out pass
      exceeds the incumbent and controlled-error accuracy meets the threshold.
- [ ] CHANGELOG.md and MODEL_CARD.md are updated for the new version.

## 3. Merge into `main`

`main` should always be the clean, canonical branch. **Use `origin/main`
(remote) as the merge base**, never a polluted local `main`.

> ⚠️ Local `main` is currently DIVERGED from `origin/main`: it carries the
> unrelated `llm-creation/` project, the `c5da9a5` fence-normalization commit,
> and a stash — none of which belong in the LLM release. The authoritative
> `origin/main` is at `a8b7add` (clean dataset release). Never merge the
> polluted local `main`; fast-forward `origin/main` to the release tip instead.

When a release branch is approved:

```bash
# Fast-forward remote main to the release tip (clean, no unrelated commits).
git fetch origin
git push origin <release_branch>:main     # ONLY after the review checklist passes
git push origin oracle-llm-v1.0.2         # push the tag
```

Or, to keep an explicit merge commit (requires `origin/main` to be checked out
clean):

```bash
git checkout -b main-clean origin/main
git merge --no-ff release/llm-v1.0.2
git push origin HEAD:main
git push origin oracle-llm-v1.0.2
```

Rules:
- `main` is only ever advanced by an approved release branch (or a direct fix
  that itself passes the review checklist).
- Never push the polluted local `main` (llm-creation + fence commit) to origin.
- After merge, the release branch may be deleted or kept; the tag remains the
  authoritative pointer.

## 4. Publishing a release

- An annotated tag `oracle-llm-vX.Y.Z` on the release tip is the publish
  artifact.
- Push order: branch first, then tag, so reviewers can inspect before the tag
  becomes the public pointer.
- Confirm on the remote: the tag resolves to the release tip, `main` is
  untouched/at the merge, and no stray branches/tags were pushed.

## 5. Tested rollback target

- The **tested rollback target is `oracle-llm-v1.0.1`** (`sql_only-qlora`, no
  retrieval). It is the last release before schema-context retrieval was
  added.
- Rollback mechanics (zero weight change): serve/generate with
  `sql_only-qlora` adapter and WITHOUT `--schema-index`. This restores the
  16.0% / 6/25 behavior.
- Every adapter dir and its `provenance.json`/`config.json`/`model_card.json`
  are retained under `artifacts/` (gitignored, not in the repo) so any release
  can be re-provisioned from its immutable metadata.
- Before declaring a rollback, re-run the staging smoke + regression suite
  against the target to confirm it is healthy.

## 6. Roles / ownership

- **Reviewer**: a developer other than the author verifies the checklist.
- **Release manager**: creates the branch, tags, pushes, and merges into `main`
  after approval.
- **Maintainer**: updates CHANGELOG.md and MODEL_CARD.md per release.

## 7. Current state (2026-08-30)

- Champion: **`sql-only-rag`** (v1.0.2), 37.3% dev-benchmark pass, 15/25
  controlled-error (sequence-enabled index). Deployed adapter unchanged.
- Latest release branch: `release/llm-v1.0.6` (sequence metadata + benchmark
  governance deny-list; merged to `main` at `a19c84d`).
- **Evaluation decision (2026-08-30)**: Candidate A (`sql-only-rag`) remains
  selected; Candidate B (`sql-only-errmix-rag`) rejected and archived as a
  non-promoted experiment (see `docs/reports/eval-decision-A-vs-B-2026-08-30.md`).
  This is a governance decision, not a model release.
- Rollback target: v1.0.1.
