"""Tool registry for the chat module.

Tools are loaded as plain Python callables (they are wrapped with
`@agno.tools.tool` decorators but that just registers metadata — the
underlying function is still callable). We dispatch by tool name (string)
in `app.modules.chat.providers.stream_chat`'s tool-call loop.

The `TOOL_REGISTRY` maps the tool name (the one the LLM sees and calls) to
the function that actually executes the work.
"""
from __future__ import annotations

from typing import Awaitable, Callable

from .execute_sql import execute_sql
from .get_db_schema import get_db_schema
from .graphdb_retrieve_relationships import graphdb_retrieve_relationships
from .graphdb_retrievedby_keywords import graphdb_retrievedby_keywords
from .project_partial_index_retriever_tool import project_partial_index_retriever
from .project_whole_index_retriever_tool import project_whole_index_retriever

# A tool function returns a JSON-serializable string. The `@tool` decorator
# from agno wraps each function in a `Function` object; we expose the
# underlying `entrypoint` (the original coroutine) so callers can `await` it.
ToolCallable = Callable[..., Awaitable[str]]

TOOL_REGISTRY: dict[str, ToolCallable] = {
    "execute_sql": execute_sql.entrypoint,
    "get_db_schema": get_db_schema.entrypoint,
    "graphdb_retrieve_relationships": graphdb_retrieve_relationships.entrypoint,
    "graphdb_retrievedby_keywords": graphdb_retrievedby_keywords.entrypoint,
    "project_partial_index_retriever": project_partial_index_retriever.entrypoint,
    "project_whole_index_retriever": project_whole_index_retriever.entrypoint,
}


def get_tool(name: str) -> ToolCallable | None:
    """Look up a tool by its registered name. Returns None if unknown."""
    return TOOL_REGISTRY.get(name)


def list_tools() -> list[str]:
    """Return the registered tool names (handy for debug logging)."""
    return list(TOOL_REGISTRY.keys())
