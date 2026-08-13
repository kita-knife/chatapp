"""Tool: graphdb_retrieve_relationships — contain/invoke edges of a node."""
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
    name="graphdb_retrieve_relationships",
    description=(
        "Given a node id (UUID, e.g. 741daa02-xxxx-xxxx-xxxx-582253fc1d65, NOT the "
        "node's name), return all associated edges: contain (parent + children) "
        "and invoke (callers + callees). Each neighbor carries id/name/label. "
        "Use when you need to understand a node's surroundings in the project graph."
    ),
    cache_results=False,
)
async def graphdb_retrieve_relationships(node_id: str, run_context: RunContext) -> str:
    """Return all edges of a node."""
    try:
        if not node_id:
            return check_and_truncate_output({"error": "node_id is required"})

        logger.info(f"graphdb_retrieve_relationships: node_id={node_id}")
        result = await _get_node_relationships(node_id)

        if result is None:
            return check_and_truncate_output({"error": f"node not found: node_id={node_id}"})

        result_json = str(result)
        node = result.get("node") or {}
        invoke = result.get("invoke") or {}
        callers = len(invoke.get("callers") or [])
        callees = len(invoke.get("callees") or [])
        preview = result_json[:300] + ("..." if len(result_json) > 300 else "")
        logger.info(
            f"graphdb_retrieve_relationships done: name={node.get('name', '?')!r} "
            f"callers={callers}, callees={callees} preview: {preview}"
        )
        return check_and_truncate_output(result_json, max_length=3000)
    except Exception as exc:
        logger.exception(f"graphdb_retrieve_relationships failed: {exc}")
        return check_and_truncate_output(
            {"error": f"graphdb_retrieve_relationships failed: {exc}"}
        )


async def _get_node_relationships(node_id: str) -> dict | None:
    rag_schema = settings.graph_schema

    async with session_scope() as session:
        # Determine node label (folder vs document)
        is_folder_res = await session.execute(
            text(f"SELECT id, name FROM {rag_schema}.graph_folders WHERE id = :node_id"),
            {"node_id": node_id},
        )
        is_folder = is_folder_res.fetchone()
        if is_folder:
            node_name, node_label = is_folder[1], "folder"
        else:
            is_doc_res = await session.execute(
                text(f"SELECT id, name FROM {rag_schema}.graph_documents WHERE id = :node_id"),
                {"node_id": node_id},
            )
            is_doc = is_doc_res.fetchone()
            if is_doc:
                node_name, node_label = is_doc[1], "document"
            else:
                return None

        result: dict = {
            "node": {"name": node_name, "label": node_label},
            "contain": {"parent": None, "children": []},
            "invoke": {"callers": [], "callees": []},
        }

        # Contain: parent
        parent_res = await session.execute(
            text(
                "SELECT f.id, f.name, 'folder' AS label "
                f"FROM {rag_schema}.graph_contain_edges e "
                f"JOIN {rag_schema}.graph_folders f ON e.source_id = f.id AND f.project = e.project "
                "WHERE e.target_id = :node_id"
            ),
            {"node_id": node_id},
        )
        parent_row = parent_res.fetchone()
        if parent_row:
            result["contain"]["parent"] = {"id": parent_row[0], "name": parent_row[1]}

        # Contain: child folders
        child_folders_res = await session.execute(
            text(
                "SELECT f.id, f.name, 'folder' AS label "
                f"FROM {rag_schema}.graph_contain_edges e "
                f"JOIN {rag_schema}.graph_folders f ON e.target_id = f.id AND f.project = e.project "
                "WHERE e.source_id = :node_id"
            ),
            {"node_id": node_id},
        )
        for r in child_folders_res.fetchall():
            result["contain"]["children"].append({"id": r[0], "name": r[1], "label": r[2]})

        # Contain: child documents
        child_docs_res = await session.execute(
            text(
                "SELECT d.id, d.name, 'document' AS label "
                f"FROM {rag_schema}.graph_contain_edges e "
                f"JOIN {rag_schema}.graph_documents d ON e.target_id = d.id AND d.project = e.project "
                "WHERE e.source_id = :node_id"
            ),
            {"node_id": node_id},
        )
        for r in child_docs_res.fetchall():
            result["contain"]["children"].append({"id": r[0], "name": r[1], "label": r[2]})

        # Invoke edges (only for documents)
        if node_label == "document":
            caller_res = await session.execute(
                text(
                    "SELECT d.id, d.name "
                    f"FROM {rag_schema}.graph_invoke_edges e "
                    f"JOIN {rag_schema}.graph_documents d ON e.source_id = d.id AND d.project = e.project "
                    "WHERE e.target_id = :node_id"
                ),
                {"node_id": node_id},
            )
            for r in caller_res.fetchall():
                result["invoke"]["callers"].append({"id": r[0], "name": r[1]})

            callee_res = await session.execute(
                text(
                    "SELECT d.id, d.name "
                    f"FROM {rag_schema}.graph_invoke_edges e "
                    f"JOIN {rag_schema}.graph_documents d ON e.target_id = d.id AND d.project = e.project "
                    "WHERE e.source_id = :node_id"
                ),
                {"node_id": node_id},
            )
            for r in callee_res.fetchall():
                result["invoke"]["callees"].append({"id": r[0], "name": r[1]})

    return result
