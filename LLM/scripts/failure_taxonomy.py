#!/usr/bin/env python3
"""Build a failure taxonomy from the sql_only adapter's failed catalog tasks.

Reads artifacts/sql-only-qlora/results.jsonl (evaluate_catalog.py output) and
groups failures by kind, schema, and Oracle error prefix (ORA-XXXXX). Prints a
summary and writes artifacts/failure_taxonomy.json. Uses only generated
candidates + evaluator reports — never the held-out gold answers.
"""
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

import sys

LLM = Path(__file__).resolve().parent.parent


def main(results_path: str, out_path: str) -> None:
    results = [json.loads(l) for l in open(results_path, encoding="utf-8") if l.strip()]
    failed = [r for r in results if not r.get("pass")]
    total = len(results)

    kind_counts = Counter(r.get("kind", "other") for r in failed)
    schema_counts = Counter(r.get("schema", "?") for r in failed)
    # Oracle error prefix (e.g. ORA-00942)
    error_prefix = Counter()
    error_codes = defaultdict(list)  # code -> [task ids]
    for r in failed:
        err = r.get("error") or ""
        m = re.search(r"(ORA-\d{5})", err)
        code = m.group(1) if m else ("no-error" if not err else "other")
        error_prefix[code] += 1
        error_codes[code].append(r.get("id"))

    # Map common codes to a coarse failure class.
    def classify(code: str) -> str:
        if code == "ORA-00942":
            return "wrong-object/table-not-found"
        if code in ("ORA-00904", "ORA-00904"):  # invalid identifier
            return "wrong-column"
        if code in ("ORA-00933", "ORA-00923", "ORA-00900", "ORA-00907", "ORA-00932",
                    "ORA-00979", "ORA-01756"):
            return "syntax"
        if code == "ORA-02290":
            return "controlled-error/constraint"
        if code == "ORA-06512":
            return "plsql-structure"
        if code in ("ORA-00979", "ORA-00937"):
            return "group-by/semantics"
        if code in ("ORA-00001", "ORA-01400"):
            return "dml/constraint"
        if code in ("ORA-01017", "ORA-01950"):
            return "privilege"
        return "other/unknown"

    class_counts = Counter(classify(c) for c in error_prefix if c != "no-error")
    no_error = failed  # includes validation-only failures with no answer error

    report = {
        "total_tasks": total,
        "failed": len(failed),
        "passed": total - len(failed),
        "pass_pct": round(100.0 * (total - len(failed)) / total, 2),
        "by_kind": dict(kind_counts),
        "by_schema": dict(schema_counts),
        "by_error_prefix": dict(error_prefix),
        "failure_class": dict(class_counts),
        "error_code_examples": {code: ids[:8] for code, ids in error_codes.items()},
    }
    Path(out_path).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print(f"tasks={total} passed={total-len(failed)} failed={len(failed)}")
    print("\n-- by kind --")
    for k, v in kind_counts.most_common():
        print(f"  {k:<11} {v}")
    print("\n-- by schema --")
    for k, v in schema_counts.most_common():
        print(f"  {k:<15} {v}")
    print("\n-- by Oracle error prefix --")
    for k, v in error_prefix.most_common():
        print(f"  {k:<10} {v}")
    print("\n-- coarse failure class --")
    for k, v in class_counts.most_common():
        print(f"  {k:<30} {v}")
    print(f"\nreport -> {out_path}")


if __name__ == "__main__":
    results_path = sys.argv[1] if len(sys.argv) > 1 else str(LLM / "artifacts/sql-only-qlora/results.jsonl")
    out_path = sys.argv[2] if len(sys.argv) > 2 else str(LLM / "artifacts/failure_taxonomy.json")
    main(results_path, out_path)
