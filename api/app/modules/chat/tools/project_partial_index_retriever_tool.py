"""Tool: project_partial_index_retriever — recursive descendant query under a folder."""
from __future__ import annotations

import logging
from typing import Any

from agno.run import RunContext
from agno.tools import tool
from sqlalchemy import text

from app.core.config import settings
from app.core.db import session_scope
from app.modules.chat.utils import check_and_truncate_output

logger = logging.getLogger(__name__)


@tool(
    name="project_partial_index_retriever",
    description=(
        "Given a folder id (UUID), recursively query all child folders and "
        "documents under it, returning a tree. Folder nodes carry id/name/children; "
        "document nodes additionally carry label='document'. Use for understanding "
        "a specific section of the project structure / navigation."
    ),
    cache_results=False,
)
async def project_partial_index_retriever(
    run_context: RunContext,
    folder_id: str = "",
    max_depth: int = 4,
) -> str:
    """Walk descendants under a folder node, up to max_depth."""
    try:
        if not folder_id:
            return check_and_truncate_output({"error": "folder_id is required"})

        project = (run_context.session_state or {}).get("project", "")
        if not project:
            return check_and_truncate_output(
                {"error": "no project selected. Pick a project from the chat input bar."}
            )

        logger.info(
            f"project_partial_index_retriever: project={project} folder_id={folder_id}"
        )
        folder_name, descendants = await _get_descendants(folder_id, project, max_depth=max_depth)

        if not descendants:
            return check_and_truncate_output({"error": "no descendant nodes found"})

        result_data = {"descendants": descendants}
        result_json = str(result_data)
        n = len(descendants) if isinstance(descendants, list) else 0
        preview = result_json[:300] + ("..." if len(result_json) > 300 else "")
        logger.info(
            f"project_partial_index_retriever done: folder_name={folder_name!r} "
            f"descendants={n} preview: {preview}"
        )
        return check_and_truncate_output(result_json, max_length=10000)
    except Exception as exc:
        logger.exception(f"project_partial_index_retriever failed: {exc}")
        return check_and_truncate_output(
            {"error": f"project_partial_index_retriever failed: {exc}"}
        )


async def _get_descendants(folder_id: str, project: str, max_depth: int = 4) -> tuple[str, list[dict[str, Any]]]:
    """Recursive descendant walker. At max_depth, folder nodes are marked truncated."""
    rag_schema = settings.graph_schema

    async with session_scope() as session:
        result = await session.execute(
            text(
                f"SELECT id, name FROM {rag_schema}.graph_folders "
                "WHERE id = :id AND project = :project"
            ),
            {"id": folder_id, "project": project},
        )
        row = result.first()
        if not row:
            return "", []
        folder_name = row[1]

        async def _walk(parent_id: str, current_depth: int) -> list[dict]:
            f_rows_res = await session.execute(
                text(
                    "SELECT f.id, f.name "
                    f"FROM {rag_schema}.graph_contain_edges e "
                    f"JOIN {rag_schema}.graph_folders f ON e.target_id = f.id AND f.project = e.project "
                    "WHERE e.project = :project AND e.source_id = :parent_id"
                ),
                {"project": project, "parent_id": parent_id},
            )
            f_rows = f_rows_res.fetchall()

            d_rows_res = await session.execute(
                text(
                    "SELECT d.id, d.name "
                    f"FROM {rag_schema}.graph_contain_edges e "
                    f"JOIN {rag_schema}.graph_documents d ON e.target_id = d.id AND d.project = e.project "
                    "WHERE e.project = :project AND e.source_id = :parent_id"
                ),
                {"project": project, "parent_id": parent_id},
            )
            d_rows = d_rows_res.fetchall()

            children: list[dict] = []
            if current_depth >= max_depth:
                for r in f_rows:
                    children.append({"id": r[0], "name": r[1], "truncated": True})
                for r in d_rows:
                    children.append({"id": r[0], "name": r[1], "label": "document"})
                return children

            for r in f_rows:
                child: dict = {"id": r[0], "name": r[1]}
                child["children"] = await _walk(r[0], current_depth + 1)
                children.append(child)
            for r in d_rows:
                children.append({"id": r[0], "name": r[1], "label": "document"})
            return children

        descendants = await _walk(folder_id, current_depth=0)

    return folder_name, descendants
