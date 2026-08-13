"""Tool: graphdb_retrievedby_keywords — keyword search across graph nodes."""
from __future__ import annotations

import logging

from agno.run import RunContext
from agno.tools import tool
from sqlalchemy import text

from app.core.config import settings
from app.core.db import session_scope
from app.modules.chat.utils import check_and_truncate_output

logger = logging.getLogger(__name__)


@tool(
    name="graphdb_retrievedby_keywords",
    description=(
        "Search the graph DB for nodes matching a keyword (case-insensitive). "
        "Searches folder names, document names, and document content. "
        "Returns matching nodes with id/name/label (folder or document). "
        "Useful for quickly locating nodes by topic."
    ),
    cache_results=False,
)
async def graphdb_retrievedby_keywords(keyword: str, run_context: RunContext) -> str:
    """Search for nodes by keyword in name and content (case-insensitive)."""
    try:
        if not keyword:
            return check_and_truncate_output({"error": "keyword is required"})

        project = (run_context.session_state or {}).get("project", "")
        if not project:
            return check_and_truncate_output(
                {"error": "no project selected. Pick a project from the chat input bar."}
            )

        logger.info(f"graphdb_retrievedby_keywords: keyword={keyword!r}")
        nodes = await _search_by_keywords(keyword, project)

        if not nodes:
            return check_and_truncate_output({"nodes": []})

        result_payload = {"nodes": nodes}
        result_json = str(result_payload)
        keyword_in = keyword[:80] + ("..." if len(keyword) > 80 else "")
        preview = result_json[:300] + ("..." if len(result_json) > 300 else "")
        logger.info(
            f"graphdb_retrievedby_keywords done: keyword={keyword_in!r} "
            f"nodes={len(nodes)} preview: {preview}"
        )
        return check_and_truncate_output(result_json, max_length=5000)
    except Exception as exc:
        logger.exception(f"graphdb_retrievedby_keywords failed: {exc}")
        return check_and_truncate_output(
            {"error": f"graphdb_retrievedby_keywords failed: {exc}"}
        )


async def _search_by_keywords(keyword: str, project: str) -> list[dict]:
    rag_schema = settings.graph_schema
    search_term = f"%{keyword}%"
    results: list[dict] = []
    seen_ids: set[str] = set()

    async with session_scope() as session:
        # folder names
        folder_res = await session.execute(
            text(
                f"SELECT id, name, 'folder' AS label "
                f"FROM {rag_schema}.graph_folders "
                "WHERE project = :project AND name ILIKE :keyword"
            ),
            {"project": project, "keyword": search_term},
        )
        for r in folder_res.fetchall():
            results.append({"id": r[0], "name": r[1], "label": r[2]})
            seen_ids.add(r[0])

        # document names
        doc_name_res = await session.execute(
            text(
                f"SELECT id, name, 'document' AS label "
                f"FROM {rag_schema}.graph_documents "
                "WHERE project = :project AND name ILIKE :keyword"
            ),
            {"project": project, "keyword": search_term},
        )
        for r in doc_name_res.fetchall():
            if r[0] not in seen_ids:
                results.append({"id": r[0], "name": r[1], "label": r[2]})
                seen_ids.add(r[0])

        # document content
        doc_content_res = await session.execute(
            text(
                f"SELECT id, name, 'document' AS label "
                f"FROM {rag_schema}.graph_documents "
                "WHERE project = :project AND content ILIKE :keyword"
            ),
            {"project": project, "keyword": search_term},
        )
        for r in doc_content_res.fetchall():
            if r[0] not in seen_ids:
                results.append({"id": r[0], "name": r[1], "label": r[2]})
                seen_ids.add(r[0])

    return results
