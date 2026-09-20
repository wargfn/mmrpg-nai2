"""Core deterministic game logic for the Marvel MCP Narrator."""

from .d616_engine import D616ConfigurationError, resolve_d616_roll, roll_d616
from .character_state import Character, CharacterRoster, character_roster
from .character_creation import (
    ARCHETYPE_TEMPLATES,
    export_character_json,
    generate_character_from_template,
    load_character_json,
    list_archetypes,
    list_occupations,
    list_origins,
    list_traits,
    validate_character_build,
    validate_character_powers,
)
from .rules_database import (
    RulesDatabase,
    RulesLookupError,
    load_rules_database,
    lookup_rule_reference,
    query_rulebook_database,
)

__all__ = [
    "roll_d616",
    "resolve_d616_roll",
    "Character",
    "CharacterRoster",
    "character_roster",
    "ARCHETYPE_TEMPLATES",
    "validate_character_build",
    "validate_character_powers",
    "generate_character_from_template",
    "export_character_json",
    "load_character_json",
    "list_archetypes",
    "list_origins",
    "list_occupations",
    "list_traits",
    "lookup_rule_reference",
    "load_rules_database",
    "query_rulebook_database",
    "RulesDatabase",
    "D616ConfigurationError",
    "RulesLookupError",
]
