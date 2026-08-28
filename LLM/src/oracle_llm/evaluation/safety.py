"""Execution-safety guard (operational safety).

Codifies the policy that generated SQL may ONLY be executed against
disposable/resettable evaluation schemas, and NEVER with production
credentials.

- ``DISPOSABLE_SCHEMAS`` = the resettable lab schemas (safe to execute DML).
- ``READ_ONLY_SCHEMAS`` = sample schemas (HR/CO) that must NOT be written
  (no reset available) — execution is permitted but only read-only SQL.
- ``PRODUCTION_SCHEMAS`` = the empty set by default; any schema not in the
  disposable set is denied.
- ``assert_executable_schema`` rejects execution against a non-disposable
  schema (fail-closed).
- ``disposable_credentials(schema)`` returns (user, password) ONLY for a
  disposable schema, reading the password from the environment — never
  hardcoded, never production.

The serving layer must NOT execute SQL at all (generation only); this guard
lives at the execution boundary (evaluation harness, regression suite).
"""
from __future__ import annotations

import os
from typing import Optional, Tuple

# Resettable lab schemas — disposable; DML is safe because they can be reset.
DISPOSABLE_SCHEMAS = frozenset([
    "SALES_LAB", "DOCUMENTS_LAB", "OPS_LAB", "LOGISTICS_LAB", "SUPPORT_LAB",
])

# Sample schemas with no reset — read-only execution only.
READ_ONLY_SCHEMAS = frozenset(["HR", "CO"])

# Production schemas must never be reached by generated SQL. This is an
# allow-list of execution targets; production is NOT in it.
PRODUCTION_SCHEMAS = frozenset()


class ExecutionGuardError(RuntimeError):
    """Raised when generated SQL would execute against a non-disposable schema."""


def is_disposable(schema: str) -> bool:
    return schema.strip().upper() in DISPOSABLE_SCHEMAS


def is_read_only(schema: str) -> bool:
    return schema.strip().upper() in READ_ONLY_SCHEMAS


def assert_executable_schema(schema: str, *, read_only_ok: bool = True) -> None:
    """Fail-closed guard: raise unless the schema is disposable (or, with
    read_only_ok, a read-only sample schema). Never allows production."""
    s = schema.strip().upper()
    if is_disposable(s):
        return
    if read_only_ok and is_read_only(s):
        return
    raise ExecutionGuardError(
        f"Refusing to execute generated SQL against schema {s!r}: it is not a "
        f"disposable/resettable evaluation schema. Allowed: "
        f"{sorted(DISPOSABLE_SCHEMAS)} (+ read-only {sorted(READ_ONLY_SCHEMAS)})."
    )


def disposable_credentials(schema: str) -> Tuple[str, str]:
    """Return (user, password) for a disposable schema, from env only."""
    s = schema.strip().upper()
    assert_executable_schema(s, read_only_ok=False)
    if s in DISPOSABLE_SCHEMAS:
        pw = os.environ.get("ORACLE_LAB_PW_" + s, "")
        if not pw:
            raise ExecutionGuardError(f"Missing ORACLE_LAB_PW_{s} env var")
        return s, pw
    raise ExecutionGuardError(f"{s} is not a disposable schema")


def read_only_credentials(schema: str) -> Tuple[str, str]:
    """Return (user, password) for a read-only sample schema, from env only."""
    s = schema.strip().upper()
    if not is_read_only(s):
        raise ExecutionGuardError(f"{s} is not a read-only sample schema")
    name = "HR" if s == "HR" else "CO"
    pw = os.environ.get("ORACLE_SAMPLE_PW_" + name, "")
    if not pw:
        raise ExecutionGuardError(f"Missing ORACLE_SAMPLE_PW_{name} env var")
    return name.lower(), pw


def classify_error_category(error_text: str) -> str:
    """Bucket an Oracle error string into a coarse category (monitoring)."""
    import re

    if not error_text:
        return "none"
    m = re.search(r"(ORA-\d{5})", error_text)
    if not m:
        return "non-ora"
    code = m.group(1)
    if code == "ORA-00942":
        return "object-not-found"
    if code == "ORA-00904":
        return "invalid-identifier"
    if code in ("ORA-00933", "ORA-00923", "ORA-00900", "ORA-00907", "ORA-00932", "ORA-01756"):
        return "syntax"
    if code in ("ORA-02290", "ORA-00001", "ORA-01400", "ORA-20001", "ORA-20003"):
        return "constraint/business-rule"
    if code in ("ORA-01017", "ORA-01950"):
        return "privilege"
    if code == "ORA-06550":
        return "plsql"
    if code in ("ORA-00942",):
        return "object-not-found"
    return f"ora-{code[-4:]}"  # fine-grained fallback by last 4 digits
