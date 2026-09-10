"""FastMCP tools that expose deterministic narrator backend capabilities."""

from __future__ import annotations

from fastmcp import FastMCP

from marvel_mcp_narrator.core.d616_engine import roll_d616 as roll_d616_core
from marvel_mcp_narrator.core.rules_database import lookup_rule_reference as lookup_rule_reference_core


mcp = FastMCP("mmrpg-narrator")


@mcp.tool()
def roll_d616(edge: bool = False, trouble: bool = False, target_number: int | None = None) -> dict:
    """Roll a deterministic d616 check using the core dice engine."""
    return roll_d616_core(edge=edge, trouble=trouble, target_number=target_number)


@mcp.tool()
def lookup_rule_reference(rule_key: str) -> dict:
    """Return a rule reference from the local rules database."""
    return lookup_rule_reference_core(rule_key)


if __name__ == "__main__":
    mcp.run()
