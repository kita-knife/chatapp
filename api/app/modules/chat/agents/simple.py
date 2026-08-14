"""Simple Agent — direct chat, no tools."""
from __future__ import annotations

from agno.agent import Agent

from app.core.prompts import get


def build_simple_agent(
    model,
    db,
    session_id: str = "",
    user_id: str = "",
) -> Agent:
    """Build the `simple` agent.

    Direct chat with no tools and a friendly role prompt. Used for general
    questions that don't require querying the library_coderag schema.
    The role prompt comes from `prompts.yml#modes.simple`.

    Session state and conversation history are managed by agno via `db`
    (see `app/core/agno_db.py`); `session_id` maps 1:1 to our
    `chat_sessions.id` and `user_id` to `users.id`.
    """
    instructions = (get("modes.simple") or "").strip() or None
    return Agent(
        model=model,
        db=db,
        session_id=session_id,
        user_id=user_id,
        tools=[],
        instructions=instructions,
        name="simple",
        markdown=False,
        add_history_to_context=True,
        read_chat_history=True,
        add_session_state_to_context=True,
    )
