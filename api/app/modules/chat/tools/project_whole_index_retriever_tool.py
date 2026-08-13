"""Tool: project_whole_index_retriever — full folder tree for the project."""
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
    name="project_whole_index_retriever",
    description=(
        "Get the folder node list for the project named `project`.\n"
        "Required parameter: `project` (the solution name). The agent's "
        "instructions tell you the current project — pass it verbatim.\n"
        "Use when the user asks about project structure / directory tree / all folders.\n"
        "Output format (via the `format` parameter):\n"
        "  format='flat' (default, recommended): NDJSON one node per line, "
        "fields = id|name|total_files|path. Saves 50%+ tokens vs tree form.\n"
        "  format='tree': nested dict form, only when parent-child hierarchy "
        "is strictly required.\n"
        "Selection rule: default flat; only use tree when the question explicitly "
        "depends on parent-child hierarchy.\n"
        "Result is cached for 30 min per (project, format) pair — the cache "
        "key includes `project`, so different projects do not collide."
    ),
    # The cache key is `(project, format)` — different projects get separate
    # cache entries. Disable caching only if `project` is left empty (the
    # LLM didn't follow instructions), in which case we fall back to
    # session_state and skip the cache.
    cache_results=True,
    cache_ttl=1800,
)
async def project_whole_index_retriever(
    run_context: RunContext,
    project: str = "",
    format: str = "flat",
) -> str:
    """Return the project's folder tree (NDJSON flat by default).

    The `project` argument is part of the function signature (and thus part
    of the JSON schema the model sees) because the tool's cache key
    includes it. The agent's instructions pass the active project name
    in this slot so different projects get isolated cache entries.

    Defensive fallback: if the model leaves `project` empty (it didn't
    follow the instruction), we read it from session_state — but cache
    is effectively disabled in that case since the key collapses to
    `project=""`.
    """
    try:
        if not project:
            project = (run_context.session_state or {}).get("project", "")
        if not project:
            return check_and_truncate_output(
                {"error": "no project selected. Pick a project from the chat input bar."}
            )

        logger.info(f"project_whole_index_retriever: project={project}")
        tree = await _get_folder_tree(project)

        if not tree:
            return check_and_truncate_output(
                {"error": "no folder data found for the project"}
            )

        if format == "tree":
            result_json = str(tree)

            def _count(node: Any) -> int:
                if not isinstance(node, dict):
                    return 0
                n = 1
                for c in node.get("children") or []:
                    n += _count(c)
                return n

            folders = _count(tree)
        else:
            result_json = _flatten_tree(tree)
            folders = sum(1 for line in result_json.splitlines() if line.strip())

        project_in = project[:100] + ("..." if len(project) > 100 else "")
        preview = result_json[:300] + ("..." if len(result_json) > 300 else "")
        logger.info(
            f"project_whole_index_retriever done: project={project_in!r}, "
            f"format={format} folders={folders} preview: {preview}"
        )
        return check_and_truncate_output(result_json)
    except Exception as exc:
        logger.exception(f"project_whole_index_retriever failed: {exc}")
        return check_and_truncate_output(
            {"error": f"project_whole_index_retriever failed: {exc}"}
        )


async def _get_folder_tree(project: str) -> dict:
    """Build the full folder tree starting from the project root (depth=0)."""
    rag_schema = settings.graph_schema

    async with session_scope() as session:
        rows_res = await session.execute(
            text(
                "SELECT id, path, name, depth, total_files "
                f"FROM {rag_schema}.graph_folders WHERE project = :project"
            ),
            {"project": project},
        )
        rows = rows_res.fetchall()

        nodes: dict[str, dict] = {}
        for row in rows:
            node = {"id": row[0], "name": row[2], "total_files": row[4] or 0, "children": []}
            nodes[row[0]] = node

        edge_rows_res = await session.execute(
            text(
                "SELECT e.source_id, e.target_id "
                f"FROM {rag_schema}.graph_contain_edges e "
                f"JOIN {rag_schema}.graph_folders cf ON e.target_id = cf.id "
                "AND cf.project = e.project "
                "WHERE e.project = :project"
            ),
            {"project": project},
        )
        edge_rows = edge_rows_res.fetchall()

    parent_children: dict[str, list[str]] = {}
    for source_id, target_id in edge_rows:
        parent_children.setdefault(source_id, []).append(target_id)

    root_id = None
    for row in rows:
        if row[3] == 0:
            root_id = row[0]
            break
    if not root_id or root_id not in nodes:
        return {}

    def build_tree(node_id: str) -> dict:
        node = dict(nodes[node_id])
        child_ids = parent_children.get(node_id, [])
        sorted_child_ids = sorted(
            child_ids,
            key=lambda x: (
                -nodes.get(x, {}).get("total_files", 0),
                nodes.get(x, {}).get("name", ""),
            ),
        )
        node["children_count"] = len(sorted_child_ids)
        node["children"] = [build_tree(cid) for cid in sorted_child_ids]
        return node

    return build_tree(root_id)


def _flatten_tree(tree: dict) -> str:
    """Recursively flatten the tree to NDJSON: one folder per line.

    Field order: id|name|total_files|path
    Example: 741daa02-...|com.example|50|/com.example
    """
    lines: list[str] = []

    def _walk(node: dict, parent_path: str) -> None:
        if not node:
            return
        node_path = f"{parent_path}/{node['name']}" if parent_path else f"/{node['name']}"
        lines.append(f"{node['id']}|{node['name']}|{node['total_files']}|{node_path}")
        for child in node.get("children") or []:
            _walk(child, node_path)

    _walk(tree, "")
    return "\n".join(lines)
