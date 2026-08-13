"""Simple Agent — direct chat, no tools."""
from __future__ import annotations

from agno.agent import Agent


def build_simple_agent(model, project: str = "") -> Agent:
    """Build the `simple` agent.

    Direct chat with no tools and no extra instructions — pure LLM
    conversation. Used for general questions that don't require querying
    the library_coderag schema.

    The `project` argument is accepted (for API symmetry with the other
    builders) but unused here since the simple mode has no tools.
    """
    return Agent(
        model=model,
        tools=[],
        name="simple",
        markdown=False,
    )
