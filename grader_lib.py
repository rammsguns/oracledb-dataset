"""
Shared statement extraction for the Oracle dataset graders.

extract_statements(text) -> list of dicts: {text, start_line, kind}

kind:
    'sql'     - single SQL statement (SELECT/DML/DDL/MERGE...)
    'plsql'   - CREATE OR REPLACE PROCEDURE/FUNCTION/PACKAGE/TRIGGER/TYPE block
    'anon'    - anonymous PL/SQL block (DECLARE ... END; or BEGIN ... END;)

Design: conservative extraction. We only emit a candidate when it TERMINATES
properly (semicolon for SQL, "/" or "END;" for PL/SQL) and its start line
looks like code, not prose. Unterminated or prose-looking chunks are skipped —
false negatives (unverified) are cheap; false positives (valid code marked
broken) erode trust in the grader.
"""
import re

SQL_START = re.compile(
    r'^\s*(SELECT|INSERT|UPDATE|DELETE|MERGE|WITH|CREATE|ALTER|DROP|'
    r'TRUNCATE|GRANT|REVOKE|COMMENT|ANALYZE|AUDIT|LOCK|BEGIN|DECLARE|'
    r'EXECUTE|EXEC|CALL)\b',
    re.IGNORECASE,
)

PLSQL_CREATE = re.compile(
    r'^\s*CREATE\s+OR\s+REPLACE\s+(PROCEDURE|FUNCTION|PACKAGE|TRIGGER|TYPE)\b',
    re.IGNORECASE,
)

SLASH_TERMINATOR = re.compile(r'^\s*/\s*$')
# A PL/SQL block ends at "END;" or "END <blockname>;" (the name of the enclosing
# procedure/function/package). It must NOT match compound endings like
# "END LOOP;", "END IF;", "END CASE;", "END WHILE;", "END FOR;" — those close an
# inner structure, not the block.
_COMPOUND_END = r'(?:IF|LOOP|CASE|WHILE|FOR)\b'
END_SEMICOLON = re.compile(
    r'^\s*END\s*(?:'
    r';(?![\S])|'                              # bare "END;" (then optional spaces)
    r'(?!' + _COMPOUND_END + r')[A-Za-z_][A-Za-z0-9_$#]*\s*;'  # END <blockname>;
    r')\s*$',
    re.IGNORECASE,
)
# A NAMED block end: "END <identifier>;" (used for CREATE ... blocks).
NAMED_END = re.compile(
    r'^\s*END\s+(?!' + _COMPOUND_END + r')[A-Za-z_][A-Za-z0-9_$#]*\s*;\s*$',
    re.IGNORECASE,
)

# A start line whose keyword is immediately followed by prose punctuation
# (colon, em-dash, or nothing-but-words) is an explanation, not code.
PROSE_AFTER_KEYWORD = re.compile(
    r'^\s*(SELECT|INSERT|UPDATE|DELETE|MERGE|CREATE|ALTER|DROP|TRUNCATE|'
    r'GRANT|BEGIN|DECLARE|EXEC|EXECUTE|CALL)\s*[:—,.]',
    re.IGNORECASE,
)


def _looks_like_sql_start(line):
    """True if line is a plausible SQL/code start, not prose."""
    if not SQL_START.match(line):
        return False
    if PROSE_AFTER_KEYWORD.match(line):
        return False
    return True


def _terminated(buf):
    """Check whether a captured block ends in a proper terminator."""
    if not buf:
        return False
    last = buf[-1].strip()
    return last.endswith(";") or SLASH_TERMINATOR.match(last)


def extract_statements(text):
    lines = text.split("\n")
    n = len(lines)
    stmts = []
    i = 0
    while i < n:
        line = lines[i]
        if not _looks_like_sql_start(line):
            i += 1
            continue

        if PLSQL_CREATE.match(line):
            kind = "plsql"
        elif re.match(r'^\s*(DECLARE|BEGIN)\b', line, re.IGNORECASE):
            kind = "anon"
        else:
            kind = "sql"

        start_line = i + 1
        buf = [line.rstrip()]
        i += 1

        # Bound the capture: a statement longer than 60 lines is almost
        # certainly prose. This also caps worst-case scan cost.
        max_lines = 60
        consumed = 0

        if kind in ("plsql", "anon"):
            # For a CREATE PROCEDURE/FUNCTION/PACKAGE/TRIGGER block, the block
            # ends with "END <object_name>;" (never a bare "END;" — that closes
            # an inner CASE/IF). For an anonymous block, bare "END;" closes it.
            while i < n and consumed < max_lines:
                buf.append(lines[i].rstrip())
                consumed += 1
                if SLASH_TERMINATOR.match(lines[i]):
                    i += 1
                    break
                if END_SEMICOLON.match(lines[i]):
                    if kind == "plsql":
                        # require a NAMED end (END <name>;) for CREATE blocks;
                        # a bare "END;" here is an inner CASE/IF, keep going.
                        if not NAMED_END.match(lines[i]):
                            i += 1
                            continue
                    # optional trailing "/"
                    if i + 1 < n and SLASH_TERMINATOR.match(lines[i + 1]):
                        buf.append(lines[i + 1].rstrip())
                        i += 2
                    else:
                        i += 1
                    break
                # Blank lines are LEGAL inside PL/SQL blocks; never abort on one.
                # The block ends at a proper terminator only.
                i += 1
        else:
            # SQL: the statement's FIRST line may already carry the terminator
            # (e.g. a one-line "CREATE TABLE ...;"). In that case it is complete
            # on its own: i already points past it (it was pre-appended above),
            # and the while-guard below won't run because buf[-1] ends with ";".
            # Otherwise consume following lines until a line ends with ";", or
            # max_lines is hit. Do NOT break on nested statement keywords (a
            # subquery's inner SELECT must not split the outer statement).
            while i < n and consumed < max_lines and not buf[-1].rstrip().endswith(";"):
                cur = lines[i].rstrip()
                buf.append(cur)
                consumed += 1
                if cur.endswith(";"):
                    i += 1
                    break
                i += 1

        # Only keep properly-terminated candidates. Strip any trailing "/"
        # (SQL*Plus terminator) lines — they are not part of the statement
        # Oracle should execute.
        while buf and SLASH_TERMINATOR.match(buf[-1]):
            buf.pop()
        if not _terminated(buf):
            continue

        text_out = "\n".join(buf).strip()
        if text_out:
            stmts.append({"text": text_out, "start_line": start_line, "kind": kind})

    return stmts
