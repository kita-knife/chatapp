"""Think Agent — CoT reasoning with tools enabled."""
from __future__ import annotations

from agno.agent import Agent

from app.core.prompts import get
from app.modules.chat.tools import TOOL_REGISTRY


def _build_project_hint(project: str) -> str:
    """Same as in knowledge — `project_whole_index_retriever`'s cache key
    includes `project`, so the LLM must pass it explicitly."""
    if not project:
        return ""
    return (
        f"\n\nCurrent project: '{project}'. "
        f"When calling `project_whole_index_retriever`, always pass "
        f"`project='{project}'` as the parameter. For all other tools in "
        f"this session, the project is auto-injected — do NOT pass `project`."
    )


def build_think_agent(model, project: str = "") -> Agent:
    """Build the `think` agent.

    Same tool set as `knowledge`, plus the CoT `modes.think` instructions
    and an elevated `max_tokens=4096` on the model so longer reasoning
    chains fit in one response.
    """
    if hasattr(model, "max_tokens"):
        model.max_tokens = 4096
    base = (get("modes.think") or "").strip()
    instructions = (base + _build_project_hint(project)).strip() or None
    return Agent(
        model=model,
        tools=[entry.function for entry in TOOL_REGISTRY.values()],
        instructions=instructions,
        name="think",
        markdown=False,
    )
