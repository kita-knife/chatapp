"""Tool: execute_sql — AI-generated SQL queries against the library_coderag schema.

Read-only SELECT/WITH only. Schema and project binding come from settings
and run_context.session_state respectively. Defense in depth:
  - Step 0: strip SQL comments
  - Step 1: reject non-SELECT/WITH top-level keywords
  - Step 2: schema whitelist (only `settings.graph_schema`)
  - Step 3: require `:project` placeholder
  - Step 4 (DB layer): SET TRANSACTION READ ONLY + search_path + statement_timeout
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, time
from decimal import Decimal

from agno.run import RunContext
from agno.tools import tool
from sqlalchemy import text

from app.core.config import settings
from app.core.db import session_scope
from app.modules.chat.utils import check_and_truncate_output

logger = logging.getLogger(__name__)

_STATEMENT_TIMEOUT_MS = 30000


def _build_execute_sql_description() -> str:
    """Dynamically inject the configured rag_schema name into the tool description."""
    rag_schema = settings.graph_schema
    return (
        "Run an AI-generated read-only SQL query (only SELECT/WITH allowed). "
        "Call get_db_schema first to learn the table layout.\n"
        "Constraints:\n"
        "- Top-level keyword must be SELECT or WITH.\n"
        "- DDL/DML forbidden: CREATE/DROP/ALTER/INSERT/UPDATE/DELETE/MERGE, "
        "VACUUM/ANALYZE/REINDEX, SET_*, pg_*, dblink, lo_*, pg_sleep, "
        "pg_advisory_lock, pg_terminate_backend, GRANT/REVOKE, SECURITY LABEL, "
        "COMMENT, COPY, CALL, SELECT INTO.\n"
        "- Schema whitelist: only `" + rag_schema + "` is allowed.\n"
        "- The query MUST bind `:project` (e.g. `WHERE project = :project`).\n"
        "- Be careful with large content columns: a single record's `content` "
        "may be several KB; SELECT 10-30 rows can exceed 10KB.\n"
        "  - For summary/title/path only: `SELECT id, name, summary`.\n"
        "  - For full text: `SELECT content, id, name WHERE id = '<id>' LIMIT 1`.\n"
        "DB layer fallback: each connection runs `SET TRANSACTION READ ONLY` + "
        "`SET search_path TO " + rag_schema + "` + `SET statement_timeout = 30s`.\n"
        "Example: `SELECT id, name, summary FROM " + rag_schema
        + ".graph_documents WHERE project = :project LIMIT 10`"
    )


@tool(
    name="execute_sql",
    description=_build_execute_sql_description(),
    cache_results=False,
)
async def execute_sql(
    sql: str,
    run_context: RunContext,
) -> str:
    """Execute a read-only SQL query against the configured graph schema.

    Args:
        sql: SELECT/WITH query. Must contain the `:project` named-parameter
            placeholder; tables must be qualified with `schema.table_name`.
        run_context: agno run context; `session_state["project"]` is the
            active project name.

    Returns:
        JSON string of the query result rows.
    """
    try:
        if not sql or not sql.strip():
            return check_and_truncate_output({"error": "sql must not be empty"})

        project = (run_context.session_state or {}).get("project", "")
        print(f"Executing SQL for project: {project}")
        if not project:
            return check_and_truncate_output(
                {"error": "no project selected. Pick a project from the chat input bar."}
            )

        rag_schema = settings.graph_schema
        sql_clean = sql.strip()

        # Step 0: strip comments (prevent hidden keywords)
        sql_clean = re.sub(r"--[^\n]*", "", sql_clean)
        sql_clean = re.sub(r"/\*.*?\*/", "", sql_clean, flags=re.DOTALL)

        # Step 1: top-level keyword must be SELECT or WITH
        sql_clean_upper = sql_clean.strip().upper()
        if not (
            sql_clean_upper.startswith("SELECT")
            or sql_clean_upper.startswith("WITH")
        ):
            first_word = sql_clean_upper.split()[0] if sql_clean_upper.split() else "empty"
            _audit_reject("non_select", sql, f"query starts with '{first_word}'")
            raise ValueError(
                f"query rejected: only SELECT/WITH (read-only) queries are allowed "
                f"(query starts with '{first_word}')."
            )

        # Step 2: schema whitelist — only rag_schema
        schema_pattern = re.compile(
            r'\b(FROM|JOIN|INTO)\s+("([^"]+)"|([a-zA-Z_][a-zA-Z0-9_]*))\s*\.\s*'
            r'("([^"]+)"|([a-zA-Z_][a-zA-Z0-9_]*))',
            re.IGNORECASE,
        )
        comma_schema_pattern = re.compile(
            r',\s*("([^"]+)"|([a-zA-Z_][a-zA-Z0-9_]*))\s*\.\s*'
            r'("([^"]+)"|([a-zA-Z_][a-zA-Z0-9_]*))',
            re.IGNORECASE,
        )
        forbidden_found: list[str] = []
        for m in schema_pattern.finditer(sql_clean):
            schema_ident = (m.group(3) or m.group(4) or "").strip().strip('"')
            if schema_ident and schema_ident != rag_schema:
                forbidden_found.append(schema_ident)
        for m in comma_schema_pattern.finditer(sql_clean):
            schema_ident = (m.group(2) or m.group(3) or "").strip().strip('"')
            if schema_ident and schema_ident != rag_schema:
                forbidden_found.append(schema_ident)
        forbidden_found = sorted(set(forbidden_found))
        if forbidden_found:
            _audit_reject(
                "schema_whitelist",
                sql,
                f"forbidden_schemas={forbidden_found}, allowed={rag_schema}",
            )
            raise ValueError(
                f"query rejected: only tables under schema `{rag_schema}` may be "
                f"accessed. Forbidden schemas detected: {forbidden_found}."
            )

        # Step 3: require `:project` placeholder (word-boundary to avoid
        # `my_project` etc.)
        if not re.search(r":project\b", sql_clean, re.IGNORECASE):
            _audit_reject("missing_project_placeholder", sql, "no :project placeholder")
            raise ValueError(
                "query rejected: SQL must contain the `:project` placeholder "
                "(e.g. `WHERE project = :project`)."
            )

        all_params = {"project": project, "rag_schema": rag_schema}

        # Step 4: DB-layer defenses + run the query.
        async with session_scope() as session:
            try:
                await session.execute(text("SET TRANSACTION READ ONLY"))
            except Exception:
                # In some connection states this can fail; the search_path +
                # statement_timeout fallbacks below still hold.
                pass
            await session.execute(text(f'SET search_path TO "{rag_schema}"'))
            await session.execute(text(f"SET statement_timeout = {_STATEMENT_TIMEOUT_MS}"))
            result = await session.execute(text(sql_clean), all_params)
            columns = result.keys()
            rows = [_jsonable_row(columns, row) for row in result.fetchall()]

        if not rows:
            logger.info("execute_sql: 0 rows")
            return check_and_truncate_output([])

        sql_preview = sql[:300] + ("..." if len(sql) > 300 else "")
        result_json = str(rows)
        preview = result_json[:300] + ("..." if len(result_json) > 300 else "")
        logger.info(
            f"execute_sql done: sql={sql_preview!r} | rows={len(rows)} | preview: {preview}"
        )
        return check_and_truncate_output(result_json, max_length=5000)

    except ValueError as exc:
        logger.warning(f"execute_sql rejected by validator: {exc}")
        return check_and_truncate_output(
            {"error": f"execute_sql rejected: {exc}"}
        )
    except Exception as exc:
        logger.exception(f"execute_sql failed: {exc}")
        return check_and_truncate_output(
            {"error": "execute_sql failed (details in server log). "
                      "Check table/column spellings, :project placeholder, and SQL syntax."}
        )


def _audit_reject(reason: str, sql: str, detail: str) -> None:
    """Audit log entry for an SQL rejection — used to detect probing later."""
    logger.warning(f"[execute_sql.reject] reason={reason} detail={detail} sql={sql[:300]}")


def _jsonable_row(columns, row) -> dict:
    """Convert a SQLAlchemy row into a JSON-serializable dict."""
    out: dict = {}
    for col, val in zip(columns, row):
        if isinstance(val, Decimal):
            out[col] = float(val)
        elif isinstance(val, (datetime, date, time)):
            out[col] = val.isoformat()
        else:
            out[col] = val
    return out
