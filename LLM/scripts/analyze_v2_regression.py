#!/usr/bin/env python3
"""Analyze why v2 (enriched index) reduced held-out pass 36.7% -> 33.3%.

Compares the v1 RAG (artifacts/sql-only-rag/results.jsonl) and v2 RAG
(artifacts/rag-v2-challenger/results.jsonl) results against the held-out
catalog: per-task pass changes, error-category shifts, and prompt-length
impact of the richer v2 DDL.
"""
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

LLM = Path(__file__).resolve().parent.parent


def load(path):
    return [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]


def summarize(results):
    n = len(results)
    passed = sum(1 for r in results if r.get("pass"))
    ce = [r for r in results if r.get("is_controlled_error")]
    ce_ok = sum(1 for r in ce if r.get("pass") and r.get("expected_error")
                and r.get("error") and r["expected_error"] in r["error"])
    kinds = defaultdict(lambda: [0, 0])
    for r in results:
        kinds[r.get("kind", "other")][1] += 1
        if r.get("pass"):
            kinds[r.get("kind", "other")][0] += 1
    err = Counter()
    for r in results:
        if not r.get("pass"):
            e = r.get("error") or "no-error"
            code = e.split(":")[0].split(" ")[0] if "ORA-" in e else (e.split()[0] if e else "no-error")
            err[code] += 1
    return {
        "n": n, "passed": passed, "pct": round(100.0 * passed / n, 2),
        "ce": f"{ce_ok}/{len(ce)}",
        "kinds": {k: (v[0], v[1]) for k, v in sorted(kinds.items())},
        "errors": dict(err.most_common(12)),
    }


def main():
    v1 = load(LLM / "artifacts" / "sql-only-rag" / "results.jsonl")
    v2 = load(LLM / "artifacts" / "rag-v2-challenger" / "results.jsonl")
    s1, s2 = summarize(v1), summarize(v2)
    print("=== v1 RAG ===")
    print(json.dumps(s1, indent=1))
    print("=== v2 RAG ===")
    print(json.dumps(s2, indent=1))

    # Per-task delta
    m1 = {r["id"]: r for r in v1}
    m2 = {r["id"]: r for r in v2}
    common = set(m1) & set(m2)
    regressions = [t for t in common if m1[t].get("pass") and not m2[t].get("pass")]
    improvements = [t for t in common if not m1[t].get("pass") and m2[t].get("pass")]
    print(f"\n=== per-task deltas (common {len(common)}) ===")
    print(f"regressed v1->v2: {len(regressions)}")
    print(f"improved  v1->v2: {len(improvements)}")
    # error categories of regressions
    rc = Counter()
    for t in regressions:
        e = m2[t].get("error") or "no-error"
        code = e.split(":")[0].split(" ")[0] if "ORA-" in e else ("no-error" if not e else e.split()[0])
        rc[code] += 1
    print("regression error codes:", dict(rc.most_common(12)))
    # kinds of regressions
    rk = Counter(m2[t].get("kind", "?") for t in regressions)
    print("regression kinds:", dict(rk.most_common()))
    print("\nregressed task ids (sample):", regressions[:20])


if __name__ == "__main__":
    main()
