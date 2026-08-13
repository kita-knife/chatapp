"""Knowledge Agent — chat with library_coderag tools enabled."""
from __future__ import annotations

from agno.agent import Agent

from app.core.prompts import get
from app.modules.chat.tools import TOOL_REGISTRY


def _build_project_hint(project: str) -> str:
    """Inject the active project into the agent's instructions.

    Only `project_whole_index_retriever` requires the project name in its
    function signature (because its cache key includes `project`). The
    other tools read it from session_state automatically. We tell the LLM
    this so it knows exactly which tool needs the explicit parameter.
    """
    if not project:
        return ""
    return (
        f"\n\nCurrent project: '{project}'. "
        f"When calling `project_whole_index_retriever`, always pass "
        f"`project='{project}'` as the parameter. For all other tools in "
        f"this session, the project is auto-injected — do NOT pass `project`."
    )


def build_knowledge_agent(model, project: str = "") -> Agent:
    """Build the `knowledge` agent.

    Provides all 6 graph tools and the `knowledge` mode prompt prefix/suffix
    (from `prompts.yml`). The active project name is injected into the
    instructions so the model knows to pass it as a parameter to
    `project_whole_index_retriever` (the only tool whose cache key depends
    on it).
    """
    prefix = get("modes.knowledge.prefix") or ""
    suffix = get("modes.knowledge.suffix") or ""
    base = (prefix + suffix).strip()
    instructions = (base + _build_project_hint(project)).strip() or None
    return Agent(
        model=model,
        tools=[entry.function for entry in TOOL_REGISTRY.values()],
        instructions=instructions,
        name="knowledge",
        markdown=False,
    )
