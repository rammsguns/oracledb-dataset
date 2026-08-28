"""Schema-context retrieval layer (Step 2).

Indexes ONLY approved, versioned schema metadata (built from the live lab
schemas by scripts/build_schema_index.py) and injects the relevant table/view
definitions into the SQL-only prompt. It NEVER indexes the held-out execution
catalog (llm_task_catalog_eval.jsonl) or any task answers.

Design:
- The index is a static JSON built from schema metadata (tables, columns, PK,
  unique constraints) — no row data, no secrets.
- Retrieval is schema-based: the request's target schema is matched by name
  (case-insensitive) against the index, and the schema's table definitions are
  formatted as compact DDL.
- Injection prepends a "Schema context" section to the user message in
  sql_only mode so the model knows the exact object names.

Held-out guard: this module never reads or references llm_task_catalog_eval.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List, Optional

# Filenames that are NEVER indexed (defensive).
DENIED_INDEX_SOURCES = {"llm_task_catalog_eval.jsonl", "llm_task_catalog_train.jsonl",
                        "llm_task_catalog_v2.jsonl", "llm_task_catalog_v3.jsonl",
                        "catalog_results", "catalog_results_v2", "catalog_results_v3",
                        "catalog_results_gold", "catalog_results_demo"}

SCHEMA_TOKEN_PATTERN = re.compile(r"([A-Za-z_][A-Za-z0-9_]*(?:\.LAB)?)", re.IGNORECASE)


class SchemaRetriever:
    """Retrieve schema DDL context for a request's target schema.

    Supports both the v1 index format ``{schema: {table: {...}}}`` and the
    enriched v2 format ``{version, generated, schemas: {schema: {tables,
    views}}}``. v2 adds foreign keys, check constraints, and table
    descriptions to the rendered DDL.
    """

    def __init__(self, index_path: str | Path):
        self.index_path = Path(index_path)
        if not self.index_path.is_file():
            raise FileNotFoundError(f"schema index not found: {self.index_path}")
        with self.index_path.open(encoding="utf-8") as fh:
            data = json.load(fh)
        # Normalize v1 or v2 into {SCHEMA: {"tables": {...}, "views": {...}}}
        self.version = data.get("version", "v1")
        raw_schemas = data.get("schemas") if "schemas" in data else data
        self.index: Dict[str, dict] = {}
        for name, payload in (raw_schemas or {}).items():
            if isinstance(payload, dict) and "tables" in payload:
                self.index[name] = payload
            else:
                # v1: payload is {table: meta}
                self.index[name] = {"tables": payload, "views": {}}
        self._canon = {k.lower(): k for k in self.index}

    def schemas(self) -> List[str]:
        return sorted(self.index.keys())

    def has_schema(self, name: str) -> bool:
        return name.strip().lower() in self._canon

    def get_schema(self, name: str) -> Optional[dict]:
        canon = self._canon.get(name.strip().lower())
        return self.index.get(canon) if canon else None

    def detect_schema(self, text: str) -> Optional[str]:
        """Find a known schema name mentioned in the request text."""
        for token in SCHEMA_TOKEN_PATTERN.findall(text or ""):
            if self.has_schema(token):
                return self._canon[token.strip().lower()]
        return None

    def format_schema_ddl(self, name: str) -> str:
        """Render a schema's table + view definitions as compact DDL.

        Includes columns, PK, unique, FK, check constraints, and (when
        present) a concise table description.
        """
        schema = self.get_schema(name)
        if not schema:
            return ""
        tables = schema.get("tables", schema)  # tolerate v1 {table: meta}
        views = schema.get("views", {})
        lines = [f"-- {name} schema (tables, columns, constraints, views)"]
        for tbl, meta in sorted(tables.items()):
            desc = meta.get("description")
            if desc:
                lines.append(f"-- {tbl}: {desc}")
            cols = ", ".join(f"{c} {t}" for c, t in meta.get("columns", []))
            lines.append(f"{tbl} ({cols})")
            if meta.get("pk"):
                lines.append(f"  PRIMARY KEY ({', '.join(meta['pk'])})")
            for u in meta.get("unique", []):
                lines.append(f"  UNIQUE ({u})")
            for fk in meta.get("fk", []):
                ref = fk.get("references", {})
                lines.append(f"  FOREIGN KEY ({fk.get('column')}) "
                             f"REFERENCES {ref.get('table')} ({', '.join(ref.get('columns', []))})")
            for c in meta.get("check", []):
                lines.append(f"  CHECK ({c})")
        for v in sorted(views.keys()):
            vdesc = views.get(v) or ""
            lines.append(f"-- view {v}{(': ' + vdesc) if vdesc else ''}")
        return "\n".join(lines)

    def build_context_prompt(self, user_content: str, *, mode: str = "sql_only") -> str:
        """Inject retrieved schema DDL into the user prompt for sql_only mode."""
        if mode != "sql_only":
            return user_content  # explain mode keeps natural language
        schema = self.detect_schema(user_content)
        if not schema:
            return user_content  # no known schema -> no context
        ddl = self.format_schema_ddl(schema)
        if not ddl:
            return user_content
        return (
            f"Schema context (authoritative table and column names for {schema}):\n"
            f"{ddl}\n\n"
            f"Use only the objects and columns listed above.\n\n"
            f"Task: {user_content}"
        )

    def retrieve(self, user_content: str, *, mode: str = "sql_only") -> dict:
        """Return retrieval metadata for monitoring.

        Emits a dict with whether a schema was detected, the schema name, and
        whether DDL was injected. This is the hook for retrieval-miss metrics
        (a request that named a schema but got no context is a retrieval miss).
        """
        if mode != "sql_only":
            return {"detected": False, "schema": None, "injected": False, "miss": False}
        schema = self.detect_schema(user_content)
        if not schema:
            return {"detected": False, "schema": None, "injected": False, "miss": False}
        ddl = self.format_schema_ddl(schema)
        injected = bool(ddl)
        return {
            "detected": True,
            "schema": schema,
            "injected": injected,
            "miss": not injected,
        }
