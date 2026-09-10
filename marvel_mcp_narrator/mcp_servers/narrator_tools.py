"""FastMCP tools that expose deterministic narrator backend capabilities."""

from __future__ import annotations

from fastmcp import FastMCP

from marvel_mcp_narrator.core.d616_engine import roll_d616 as roll_d616_core
from marvel_mcp_narrator.core.rules_database import query_rulebook_database


mcp = FastMCP("mmrpg-narrator")


@mcp.tool()
def resolve_d616_roll(edge: bool = False, trouble: bool = False, target_number: int | None = None) -> dict:
    """Resolve a d616 check using deterministic core dice logic."""
    return roll_d616_core(edge=edge, trouble=trouble, target_number=target_number)


@mcp.tool()
def lookup_rule(query: str) -> str:
    """Search the rulebook by keyword and return formatted results."""
    return query_rulebook_database(query)


if __name__ == "__main__":
    mcp.run()
