"""FastMCP tools that expose deterministic narrator backend capabilities."""

from __future__ import annotations

from fastmcp import FastMCP

from marvel_mcp_narrator.core.character_state import character_roster
from marvel_mcp_narrator.core.d616_engine import roll_d616 as roll_d616_core
from marvel_mcp_narrator.core.rules_database import lookup_rule_reference


mcp = FastMCP("mmrpg-narrator")


@mcp.tool()
def roll_d616(edge: bool = False, trouble: bool = False, target_number: int | None = None) -> dict:
    """Resolve a d616 check using deterministic core dice logic."""
    return roll_d616_core(edge=edge, trouble=trouble, target_number=target_number)


@mcp.tool()
def lookup_rule(rule_key: str) -> dict:
    """Look up an exact rule reference by mechanic key or power name."""
    return lookup_rule_reference(rule_key)


@mcp.tool()
def create_or_load_character(
    *,
    name: str,
    rank: int,
    archetype: str,
    melee: int,
    agility: int,
    resilience: int,
    vigilance: int,
    ego: int,
    logic: int,
) -> dict:
    """Create a new character or load an existing one by name."""
    character, created = character_roster.create_or_load(
        name=name,
        rank=rank,
        archetype=archetype,
        melee=melee,
        agility=agility,
        resilience=resilience,
        vigilance=vigilance,
        ego=ego,
        logic=logic,
    )
    return {
        "created": created,
        "character": character.to_dict(),
    }


@mcp.tool()
def get_character_sheet(name: str) -> dict:
    """Return a full character sheet and mutable state."""
    return character_roster.get_sheet(name)


@mcp.tool()
def apply_damage(name: str, health_damage: int = 0, focus_damage: int = 0) -> dict:
    """Apply health and/or focus damage to a tracked character."""
    return character_roster.apply_damage(name=name, health_damage=health_damage, focus_damage=focus_damage)


@mcp.tool()
def calculate_attack_damage(
    attacker_name: str,
    ability: str,
    marvel_die: int,
    is_fantastic: bool = False,
    bonus_multiplier: int = 0,
) -> dict:
    """Calculate attack damage using rank-based multipliers."""
    return character_roster.calculate_attack_damage(
        attacker_name=attacker_name,
        ability=ability,
        marvel_die=marvel_die,
        is_fantastic=is_fantastic,
        bonus_multiplier=bonus_multiplier,
    )


if __name__ == "__main__":
    mcp.run()
