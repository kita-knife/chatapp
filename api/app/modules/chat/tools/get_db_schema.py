"""Tool: get_db_schema — list tables/columns/types/comments in library_coderag."""
from __future__ import annotations

import logging

from agno.run import RunContext
from agno.tools import tool
from sqlalchemy import text

from app.core.config import settings
from app.core.db import session_scope
from app.modules.chat.utils import check_and_truncate_output

logger = logging.getLogger(__name__)


_TABLE_DESCRIPTIONS: dict[str, str] = {
    "graph_folders": (
        "Folder/project node. Each row is a directory. "
        "Root has depth=0. id is the primary key; (project, path) is unique."
    ),
    "graph_documents": (
        "Document/file node. Each row is a source file. Stores "
        "content (full text), summary (AI-generated), and embedding "
        "(pgvector, 1024 dims). id is the primary key; (project, path) is unique."
    ),
    "graph_contain_edges": (
        "Containment edges forming the tree hierarchy. source_id is the parent "
        "folder; target_id is a child folder or document. Both reference "
        "graph_folders.id or graph_documents.id."
    ),
    "graph_invoke_edges": (
        "Invoke/import edges connecting documents. source_id is the caller "
        "document; target_id is the callee. Directed: A calls B."
    ),
}


@tool(
    name="get_db_schema",
    description=(
        "Get database schema metadata (tables, columns, types, comments) for "
        "the graph DB. Call this before execute_sql to learn the table layout. "
        "Returns JSON with: schema name, tables array (name + columns + description)."
    ),
    cache_results=False,
)
async def get_db_schema(run_context: RunContext) -> str:
    """Return the configured graph schema's tables/columns/types/comments."""
    try:
        rag_schema = settings.graph_schema

        async with session_scope() as session:
            result = await session.execute(
                text(
                    """
                    SELECT
                        table_name,
                        column_name,
                        data_type,
                        is_nullable,
                        col_description(
                            (table_schema || '.' || table_name)::regclass,
                            ordinal_position
                        ) AS column_comment
                    FROM information_schema.columns
                    WHERE table_schema = :schema
                    ORDER BY table_name, ordinal_position
                    """
                ),
                {"schema": rag_schema},
            )
            rows = result.fetchall()

        tables: dict[str, dict] = {}
        for row in rows:
            tn = row[0]
            if tn not in tables:
                tables[tn] = {"name": tn, "columns": []}
            col = {
                "name": row[1],
                "type": row[2],
                "nullable": row[3] == "YES",
            }
            desc = row[4] or ""
            if desc:
                col["description"] = desc
            tables[tn]["columns"].append(col)

        result_payload: dict[str, object] = {
            "schema": rag_schema,
            "tables": [],
        }
        for tn in [
            "graph_folders",
            "graph_documents",
            "graph_contain_edges",
            "graph_invoke_edges",
        ]:
            if tn in tables:
                t = tables[tn]
                desc = _TABLE_DESCRIPTIONS.get(tn, "")
                if desc:
                    t["description"] = desc
                result_payload["tables"].append(t)

        logger.info(f"get_db_schema done: tables={len(result_payload['tables'])}")
        return check_and_truncate_output(str(result_payload), max_length=8000)
    except Exception as exc:
        logger.exception(f"get_db_schema failed: {exc}")
        return check_and_truncate_output({"error": str(exc)})
