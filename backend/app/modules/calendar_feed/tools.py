"""No agent tools.

A subscription URL is a credential a person pastes into their own
calendar client. Nothing an agent should read, mint or rotate on
somebody's behalf, so this module is deliberately not
agent-addressable — ``get_tools`` is mandatory, its being empty is a
decision (see the module CLAUDE.md).
"""

from __future__ import annotations

from app.core.agents.tools.registry import Tool


def get_tools() -> list[Tool]:
    return []
