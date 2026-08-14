"""Think Agent — CoT reasoning with tools enabled."""
from __future__ import annotations

from agno.agent import Agent

from app.core.prompts import get
from app.modules.chat.tools import TOOL_REGISTRY


def build_think_agent(
    model,
    db,
    session_id: str = "",
    user_id: str = "",
) -> Agent:
    """Build the `think` agent.

    Same tool set as `knowledge`, plus the CoT `modes.think` instructions
    and an elevated `max_tokens=4096` on the model so longer reasoning
    chains fit in one response. Session state (project) reaches the model
    via `add_session_state_to_context=True`.
    """
    if hasattr(model, "max_tokens"):
        model.max_tokens = 4096
    instructions = (get("modes.think.instructions") or "").strip() or None
    return Agent(
        model=model,
        db=db,
        session_id=session_id,
        user_id=user_id,
        tools=[entry.function for entry in TOOL_REGISTRY.values()],
        instructions=instructions,
        name="think",
        markdown=False,
        add_history_to_context=True,
        read_chat_history=True,
        add_session_state_to_context=True,
    )
