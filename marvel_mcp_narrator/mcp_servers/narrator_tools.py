"""FastMCP tools that expose deterministic narrator backend capabilities."""

from __future__ import annotations

from fastmcp import FastMCP

from marvel_mcp_narrator.core.character_creation import (
    ABILITY_FIELDS,
    generate_character_from_template,
    list_archetypes,
    list_occupations,
    list_origins,
    validate_character_build,
)
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
def create_character(
    *,
    name: str,
    archetype: str,
    rank: int,
    melee: int,
    agility: int,
    resilience: int,
    vigilance: int,
    ego: int,
    logic: int,
) -> dict:
    """Create a new character or load an existing one by name."""
    character_sheet, created = character_roster.create_or_load(
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
        "character": character_sheet,
    }


@mcp.tool()
def get_character(name: str) -> dict:
    """Return a full character sheet and mutable state."""
    return character_roster.get_sheet(name)


@mcp.tool()
def apply_damage_to_character(name: str, health_damage: int = 0, focus_damage: int = 0) -> dict:
    """Apply health and/or focus damage to a tracked character."""
    return character_roster.apply_damage(name=name, health_damage=health_damage, focus_damage=focus_damage)


@mcp.tool()
def calculate_attack(
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
    """Backward-compatible alias for create_character."""
    return create_character(
        name=name,
        archetype=archetype,
        rank=rank,
        melee=melee,
        agility=agility,
        resilience=resilience,
        vigilance=vigilance,
        ego=ego,
        logic=logic,
    )


@mcp.tool()
def get_character_sheet(name: str) -> dict:
    """Backward-compatible alias for get_character."""
    return get_character(name)


@mcp.tool()
def apply_damage(name: str, health_damage: int = 0, focus_damage: int = 0) -> dict:
    """Backward-compatible alias for apply_damage_to_character."""
    return apply_damage_to_character(name=name, health_damage=health_damage, focus_damage=focus_damage)


@mcp.tool()
def calculate_attack_damage(
    attacker_name: str,
    ability: str,
    marvel_die: int,
    is_fantastic: bool = False,
    bonus_multiplier: int = 0,
) -> dict:
    """Backward-compatible alias for calculate_attack."""
    return character_roster.calculate_attack_damage(
        attacker_name=attacker_name,
        ability=ability,
        marvel_die=marvel_die,
        is_fantastic=is_fantastic,
        bonus_multiplier=bonus_multiplier,
    )


@mcp.tool()
def create_character_assisted(
    name: str,
    archetype: str,
    rank: int,
    custom_abilities: dict | None = None,
    origin: str = "Unknown",
    occupation: str = "None",
    traits: list[str] | None = None,
    tags: list[str] | None = None,
) -> dict:
    """Create a character from templates with optional custom ability overrides."""
    character = generate_character_from_template(
        name=name,
        archetype=archetype,
        rank=rank,
        origin=origin,
        occupation=occupation,
        traits=traits,
        tags=tags,
    )
    abilities = {ability: getattr(character, ability) for ability in ABILITY_FIELDS}
    if custom_abilities:
        for ability in ABILITY_FIELDS:
            if ability in custom_abilities:
                abilities[ability] = custom_abilities[ability]

    validation = validate_character_build(
        name=name,
        archetype=archetype,
        rank=rank,
        abilities=abilities,
        powers=[],
        origin=origin,
        occupation=occupation,
        traits=traits,
        tags=tags,
    )
    if not validation["valid"]:
        raise ValueError("; ".join(validation["errors"]))

    character_sheet, created = character_roster.create_or_load(
        name=name,
        archetype=archetype,
        rank=rank,
        melee=abilities["melee"],
        agility=abilities["agility"],
        resilience=abilities["resilience"],
        vigilance=abilities["vigilance"],
        ego=abilities["ego"],
        logic=abilities["logic"],
        origin=validation["origin"],
        occupation=validation["occupation"],
        traits=validation["traits"],
        tags=validation["tags"],
    )
    return {
        "created": created,
        "character": character_sheet,
        "validation": validation,
    }


@mcp.tool()
def list_available_archetypes() -> list:
    """List supported archetypes and playstyle summaries."""
    return list_archetypes()


@mcp.tool()
def list_available_origins() -> list[str]:
    """List supported origins for character creation."""
    return list_origins()


@mcp.tool()
def list_available_occupations() -> list[str]:
    """List supported occupations for character creation."""
    return list_occupations()


if __name__ == "__main__":
    mcp.run()
