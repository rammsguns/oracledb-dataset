#!/usr/bin/env python3
"""Measure retrieved-context length impact: v1 vs v2 schema DDL prompt size."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from oracle_llm.serving.retrieval import SchemaRetriever

LLM = Path(__file__).resolve().parent.parent
v1 = SchemaRetriever(LLM / "artifacts" / "schema_index.json")
v2 = SchemaRetriever(LLM / "artifacts" / "schema_index_v2.json")

for schema in sorted(v1.schemas()):
    d1 = v1.format_schema_ddl(schema)
    d2 = v2.format_schema_ddl(schema)
    # rough token estimate (whitespace-split)
    t1 = len(d1.split())
    t2 = len(d2.split())
    print(f"{schema:<15} v1: {t1:5d} tok | v2: {t2:5d} tok | +{t2-t1:4d} ({100.0*(t2-t1)/max(t1,1):.0f}%)")

# total across all schemas (but retrieval injects only ONE schema per request)
print("\n(retrieval injects a single target schema per request)")
