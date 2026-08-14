"""Knowledge Agent — chat with library_coderag tools enabled."""
from __future__ import annotations

from agno.agent import Agent

from app.core.prompts import get
from app.modules.chat.tools import TOOL_REGISTRY


def build_knowledge_agent(
    model,
    db,
    session_id: str = "",
    user_id: str = "",
) -> Agent:
    """Build the `knowledge` agent.

    Provides all 6 graph tools and the `knowledge` mode instructions from
    `prompts.yml#modes.knowledge.instructions` (single string — the
    prefix/suffix split is gone). The active project name reaches the model
    via `add_session_state_to_context=True` — the system message embeds the
    session_state (which includes `project`), so the LLM knows what value
    to pass to `project_whole_index_retriever` (whose cache key depends on
    the explicit `project` argument).
    """
    instructions = (get("modes.knowledge.instructions") or "").strip() or None
    return Agent(
        model=model,
        db=db,
        session_id=session_id,
        user_id=user_id,
        tools=[entry.function for entry in TOOL_REGISTRY.values()],
        instructions=instructions,
        name="knowledge",
        markdown=False,
        add_history_to_context=True,
        read_chat_history=True,
        add_session_state_to_context=True,
    )
