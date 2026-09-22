"""FastMCP tools that expose deterministic narrator backend capabilities."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from tempfile import gettempdir

from fastmcp import FastMCP

from marvel_mcp_narrator.core.campaign_planner import (
    conclude_session as conclude_session_core,
    create_campaign_plan as create_campaign_plan_core,
    get_current_session_context as get_current_session_context_core,
)
from marvel_mcp_narrator.core.memory.campaign_db import (
    get_entity,
    get_npc,
    load_memory,
    save_entity,
    save_memory,
    log_event,
    save_npc,
    search_entities,
    search_memory,
)
from marvel_mcp_narrator.core.character_creation import (
    ABILITY_FIELDS,
    export_character_json,
    generate_character_from_template,
    list_archetypes,
    list_occupations,
    list_origins,
    list_tags,
    validate_character_powers as validate_character_powers_core,
    validate_character_build,
)
from marvel_mcp_narrator.core.combat_tracker import combat_tracker
from marvel_mcp_narrator.core.character_state import character_roster
from marvel_mcp_narrator.core.d616_engine import (
    roll_d616 as roll_d616_core,
)
from marvel_mcp_narrator.core.rules_database import lookup_rule_reference


mcp = FastMCP("mmrpg-narrator")
_TOOL_HELP_ENTRIES = [
    ("roll_d616", "Resolve a d616 check with optional edge, trouble, and target number."),
    ("lookup_rule", "Look up an exact mechanics or power reference from the rule database."),
    ("create_character", "Create or load a tracked character sheet with explicit stats."),
    ("get_character", "Fetch a tracked character sheet and mutable combat state."),
    ("apply_damage_to_character", "Apply health and/or focus damage to a tracked character."),
    ("calculate_attack", "Calculate rank-based attack damage from a Marvel die result."),
    ("track_combatant", "Add an existing character to the active combat roster."),
    ("get_combat_state", "Show all combatants currently tracked in combat."),
    ("resolve_manual_d616_roll", "Normalize a manually reported d616 roll payload."),
    ("resolve_player_attack", "Resolve a player attack, optionally from a manual roll."),
    ("resolve_npc_action", "Auto-resolve an NPC or enemy combat action."),
    ("create_character_assisted", "Create a character from an archetype template."),
    ("list_available_archetypes", "List supported archetypes and playstyle summaries."),
    ("list_available_origins", "List supported origins for character creation."),
    ("list_available_occupations", "List supported occupations for character creation."),
    ("list_available_tags", "List supported character tags."),
    ("export_character", "Write a tracked character sheet to a JSON export file."),
    ("validate_character_powers", "Validate selected powers against a tracked character rank."),
    ("save_campaign_memory", "Persist a named campaign memory entry."),
    ("load_campaign_memory", "Load a named campaign memory entry."),
    ("create_campaign_plan", "Generate and persist a structured campaign plan."),
    ("get_next_session_briefing", "Return the active campaign session briefing."),
    ("wrap_up_current_session", "Conclude the active campaign session and advance progress."),
    ("remember_entity", "Persist a named campaign entity."),
    ("recall_entity", "Recall a named entity or search across saved entities."),
    ("log_campaign_event", "Persist a campaign event in the plot log."),
    ("remember_npc", "Persist legacy NPC memory details."),
    ("recall_npc_or_location", "Recall legacy NPC, location, or plot-log memory matches."),
]


def clear_combat_state() -> None:
    combat_tracker.clear()


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
    origin: str = "Unknown",
    occupation: str = "None",
    traits: list[str] | None = None,
    tags: list[str] | None = None,
    power_sets: list[str | dict] | None = None,
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
        origin=origin,
        occupation=occupation,
        traits=traits,
        tags=tags,
        power_sets=power_sets,
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
def track_combatant(name: str, side: str = "player") -> dict:
    """Mark an existing tracked character as part of the current combat."""
    return combat_tracker.track_combatant(name, side=side)


@mcp.tool()
def get_combat_state() -> dict:
    """Return all combatants currently tracked in the active combat."""
    return combat_tracker.get_combat_state()


@mcp.tool()
def resolve_manual_d616_roll(
    dice_values: list[int],
    marvel_index: int = 1,
    ability_modifier: int = 0,
    target_number: int | None = None,
) -> dict:
    """Normalize a manually reported d616 roll into the standard deterministic payload."""
    return combat_tracker.resolve_manual_roll(
        dice_values=dice_values,
        marvel_index=marvel_index,
        ability_modifier=ability_modifier,
        target_number=target_number,
    )


@mcp.tool()
def resolve_player_attack(
    attacker_name: str,
    target_name: str,
    ability: str,
    dice_values: list[int] | None = None,
    marvel_index: int = 1,
    target_resource: str = "health",
    edges: int = 0,
    troubles: int = 0,
) -> dict:
    """Resolve a player attack, optionally using a manually reported d616 result."""
    return combat_tracker.resolve_player_attack(
        attacker_name=attacker_name,
        target_name=target_name,
        ability=ability,
        dice_values=dice_values,
        marvel_index=marvel_index,
        target_resource=target_resource,
        edges=edges,
        troubles=troubles,
    )


@mcp.tool()
def resolve_npc_action(
    attacker_name: str,
    target_name: str,
    ability: str,
    target_resource: str = "health",
    edges: int = 0,
    troubles: int = 0,
) -> dict:
    """Automatically resolve an NPC or enemy combat action against a tracked target."""
    return combat_tracker.resolve_npc_action(
        attacker_name=attacker_name,
        target_name=target_name,
        ability=ability,
        target_resource=target_resource,
        edges=edges,
        troubles=troubles,
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
    origin: str = "Unknown",
    occupation: str = "None",
    traits: list[str] | None = None,
    tags: list[str] | None = None,
    power_sets: list[str | dict] | None = None,
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
        origin=origin,
        occupation=occupation,
        traits=traits,
        tags=tags,
        power_sets=power_sets,
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
    return calculate_attack(
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
    power_sets: list[str | dict] | None = None,
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
        power_sets=power_sets,
    )
    abilities = {ability: getattr(character, ability) for ability in ABILITY_FIELDS}
    if custom_abilities:
        for ability in ABILITY_FIELDS:
            if ability in custom_abilities:
                abilities[ability] = custom_abilities[ability]
    for ability in ABILITY_FIELDS:
        setattr(character, ability, abilities[ability])

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
        power_sets=power_sets,
    )
    if not validation["valid"]:
        raise ValueError("; ".join(validation["errors"]))
    if validation["warnings"]:
        raise ValueError("; ".join(validation["warnings"]))

    character_sheet, created = character_roster.create_or_load(
        name=validation["name"],
        archetype=validation["archetype"],
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
        power_sets=validation["power_sets"],
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


@mcp.tool()
def list_available_tags() -> list[str]:
    """List supported character tags."""
    return list_tags()


@mcp.tool()
def export_character(name: str) -> dict:
    """Export a tracked character sheet to JSON on disk."""
    character = character_roster.get_copy(name)
    export_dir = Path(gettempdir()) / "mmrpg-character-exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    safe_name = "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in character.name.strip())
    safe_name = safe_name.strip("_") or "character"
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    filename = f"{safe_name}_{timestamp}.json"
    filepath = export_dir / filename
    export_character_json(character, str(filepath))
    return {
        "name": character.name,
        "filepath": str(filepath),
        "character": character.to_dict(),
    }


@mcp.tool()
def validate_character_powers(name: str, powers_list: list) -> dict:
    """Validate selected powers against the tracked character's rank."""
    character = character_roster.get_copy(name)
    return validate_character_powers_core(rank=character.rank, powers_list=powers_list)


@mcp.tool()
def remember_npc(name: str, affiliation: str = "", description: str = "", notes: str = "") -> str:
    """Persist NPC campaign memory details."""
    return save_npc(name=name, affiliation=affiliation, description=description, notes=notes)


@mcp.tool()
def save_campaign_memory(key: str, content: str) -> str:
    """Persist a named campaign memory entry."""
    return save_memory(key=key, content=content)


@mcp.tool()
def load_campaign_memory(key: str) -> str:
    """Load a named campaign memory entry."""
    content = load_memory(key)
    if content is None:
        return f"No campaign memory found for '{key}'."
    return content


@mcp.tool()
def create_campaign_plan(
    theme: str,
    villain: str,
    session_count: int,
    hero_team: list[str] | None = None,
) -> str:
    """Create and persist a structured campaign plan."""
    plan = create_campaign_plan_core(
        theme=theme,
        villain=villain,
        hero_team=hero_team,
        desired_session_count=session_count,
    )
    titles = ", ".join(session["title"] for session in plan["sessions"])
    return (
        f"Created {plan['session_count']}-session campaign against {plan['villain']} "
        f"with sessions: {titles}."
    )


@mcp.tool()
def get_next_session_briefing() -> str:
    """Return the active session briefing for the current campaign."""
    context = get_current_session_context_core()
    session = context["session"]
    return "\n".join(
        [
            f"Session {session['session_number']}: {session['title']}",
            f"Theme: {context['theme']}",
            f"Villain: {context['villain']}",
            f"Objectives: {', '.join(session['objectives'])}",
            f"Key NPCs: {', '.join(session['key_npcs'])}",
            f"Locations: {', '.join(session['locations'])}",
            f"Milestone: {session['completion_milestone']}",
        ]
    )


@mcp.tool()
def wrap_up_current_session(session_log_summary: str) -> str:
    """Generate recap data and advance the active campaign session."""
    context = get_current_session_context_core()
    session = context["session"]
    wrap_up = conclude_session_core(
        session_number=session["session_number"],
        raw_session_log=session_log_summary,
    )
    highlight_names = ", ".join(wrap_up["hero_highlights"].keys())
    return "\n".join(
        [
            wrap_up["player_recap"],
            f"Bridge Prompt: {wrap_up['narrator_bridge_prompt']}",
            f"Hero Highlights: {highlight_names}",
        ]
    )


@mcp.tool()
def remember_entity(
    name: str,
    category: str,
    description: str,
    disposition: str = "Neutral",
    location: str = "Unknown",
    notes: str = "",
) -> str:
    """Persist a named campaign entity."""
    save_entity(
        name=name,
        category=category,
        description=description,
        disposition=disposition,
        location=location,
        notes=notes,
    )
    return f"Saved {category.strip() or 'entity'} '{name.strip()}'."


@mcp.tool()
def recall_entity(name_or_query: str) -> str:
    """Recall a single entity or search across tracked entities."""
    entity = get_entity(name_or_query)
    if entity:
        return "\n".join(
            [
                f"Name: {entity['name']}",
                f"Category: {entity.get('category') or 'Unknown'}",
                f"Description: {entity.get('description') or 'Unknown'}",
                f"Disposition: {entity.get('disposition') or 'Neutral'}",
                f"Location: {entity.get('location') or 'Unknown'}",
                f"Notes: {entity.get('notes') or 'None'}",
            ]
        )

    matches = search_entities(name_or_query)
    if not matches:
        return f"No entity found for '{name_or_query}'."

    lines = [f"Entity matches for '{name_or_query}':"]
    for match in matches:
        lines.append(
            f"- [{match['category']}] {match['name']} ({match['location']}): "
            f"{match['description']}"
        )
    return "\n".join(lines)


@mcp.tool()
def recall_npc_or_location(query: str) -> str:
    """Recall matching NPC, location, or plot memories."""
    npc = get_npc(query)
    if npc:
        return "\n".join(
            [
                f"NPC: {npc['name']}",
                f"Affiliation: {npc.get('affiliation') or 'Unknown'}",
                f"Role: {npc.get('archetype_or_role') or 'Unknown'}",
                f"Notes: {npc.get('notes') or 'None'}",
            ]
        )

    matches = search_memory(query)
    if not matches:
        return f"No campaign memory found for '{query}'."

    lines = [f"Campaign memory matches for '{query}':"]
    for match in matches:
        details = match.get("summary") or match.get("notes") or "No details recorded."
        if match["memory_type"] == "plot_log" and match.get("affiliation"):
            lines.append(f"- [plot_log] {match['name']} @ {match['affiliation']}: {details}")
            continue
        lines.append(f"- [{match['memory_type']}] {match['name']}: {details}")
    return "\n".join(lines)


@mcp.tool()
def log_campaign_event(summary: str, session: int = 1) -> str:
    """Persist a campaign event to the plot log."""
    return log_event(summary, session=session)


def format_tool_help() -> str:
    """Render a concise list of exposed FastMCP tools."""
    lines = ["Available FastMCP narrator tools:"]
    for name, description in _TOOL_HELP_ENTRIES:
        lines.append(f"- {name}: {description}")
    return "\n".join(lines)


def build_argument_parser() -> argparse.ArgumentParser:
    """Build a small CLI for starting or inspecting the FastMCP narrator server."""
    parser = argparse.ArgumentParser(
        description="Start the Marvel MCP Narrator FastMCP server.",
        epilog=(
            "Examples:\n"
            "  python -m marvel_mcp_narrator.mcp_servers.narrator_tools\n"
            "  python -m marvel_mcp_narrator.mcp_servers.narrator_tools --list-tools\n\n"
            "Use this server with a FastMCP-compatible client. Run with --list-tools to review the "
            "available narrator tools before connecting."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--list-tools",
        action="store_true",
        help="Print the exposed FastMCP narrator tools and exit.",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    """Run the narrator FastMCP server or print local startup help."""
    parser = build_argument_parser()
    args = parser.parse_args(argv)
    if args.list_tools:
        print(format_tool_help())
        return
    mcp.run()


if __name__ == "__main__":
    main()
