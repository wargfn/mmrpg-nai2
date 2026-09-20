"""Core deterministic game logic for the Marvel MCP Narrator."""

from .d616_engine import D616ConfigurationError, resolve_d616_roll, roll_d616
from .character_state import Character, CharacterRoster, character_roster
from .character_creation import (
    ARCHETYPE_TEMPLATES,
    generate_character_from_template,
    list_archetypes,
    validate_character_build,
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
    "generate_character_from_template",
    "list_archetypes",
    "lookup_rule_reference",
    "load_rules_database",
    "query_rulebook_database",
    "RulesDatabase",
    "D616ConfigurationError",
    "RulesLookupError",
]
