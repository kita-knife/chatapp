"""Agent factories for the three chat modes.

Each builder takes an agno `Model` instance and returns a configured
`Agent` with mode-specific tools and instructions. The factory dispatch
lives in `app.modules.chat.providers._get_agent`.
"""
from __future__ import annotations

from .knowledge import build_knowledge_agent
from .simple import build_simple_agent
from .think import build_think_agent

__all__ = ["build_simple_agent", "build_knowledge_agent", "build_think_agent"]
