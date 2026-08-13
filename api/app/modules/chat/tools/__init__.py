"""Tool registry for the chat module.

Tools are wrapped by `agno.tools.tool` decorators into `Function` objects.
We keep BOTH the wrapper (for `to_dict()` schema serialisation to the LLM)
and the entrypoint (the raw async callable that we `await` at runtime).

The registry maps the tool name (what the LLM sees in its function-call
arguments) to a `ToolEntry` carrying both representations. `stream_chat`
serialises the `Function` via `to_dict()` so the model receives a proper
OpenAI-compatible tool schema; the entrypoint is invoked when the model
actually returns a tool_call.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from .execute_sql import execute_sql
from .get_db_schema import get_db_schema
from .graphdb_retrieve_relationships import graphdb_retrieve_relationships
from .graphdb_retrievedby_keywords import graphdb_retrievedby_keywords
from .project_partial_index_retriever_tool import project_partial_index_retriever
from .project_whole_index_retriever_tool import project_whole_index_retriever


@dataclass
class ToolEntry:
    function: Any            # agno.tools.function.Function
    entrypoint: Callable[..., Awaitable[str]]


TOOL_REGISTRY: dict[str, ToolEntry] = {
    "execute_sql": ToolEntry(function=execute_sql, entrypoint=execute_sql.entrypoint),
    "get_db_schema": ToolEntry(function=get_db_schema, entrypoint=get_db_schema.entrypoint),
    "graphdb_retrieve_relationships": ToolEntry(
        function=graphdb_retrieve_relationships,
        entrypoint=graphdb_retrieve_relationships.entrypoint,
    ),
    "graphdb_retrievedby_keywords": ToolEntry(
        function=graphdb_retrievedby_keywords,
        entrypoint=graphdb_retrievedby_keywords.entrypoint,
    ),
    "project_partial_index_retriever": ToolEntry(
        function=project_partial_index_retriever,
        entrypoint=project_partial_index_retriever.entrypoint,
    ),
    "project_whole_index_retriever": ToolEntry(
        function=project_whole_index_retriever,
        entrypoint=project_whole_index_retriever.entrypoint,
    ),
}


def get_tool(name: str) -> ToolEntry | None:
    """Look up a tool by its registered name. Returns None if unknown."""
    return TOOL_REGISTRY.get(name)


def get_tool_callable(name: str) -> Callable[..., Awaitable[str]] | None:
    """Return the underlying async entrypoint (or None)."""
    entry = TOOL_REGISTRY.get(name)
    return entry.entrypoint if entry else None


def list_tools() -> list[str]:
    """Return the registered tool names (handy for debug logging)."""
    return list(TOOL_REGISTRY.keys())
