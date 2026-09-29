"""Core deterministic game logic for the Marvel MCP Narrator."""

from .d616_engine import D616ConfigurationError, resolve_d616_roll, roll_d616
from .character_state import Character, CharacterRoster, character_roster
from .combat_tracker import CombatTracker, combat_tracker
from .character_creation import (
    ARCHETYPE_TEMPLATES,
    export_character_json,
    generate_character_from_template,
    load_character_json,
    list_archetypes,
    list_occupations,
    list_origins,
    list_tags,
    list_traits,
    validate_character_build,
    validate_power_selection,
    validate_character_powers,
)
from .campaign_planner import (
    CampaignPlanner,
    conclude_session,
    create_campaign_plan,
    get_current_session_context,
)
from .rules_database import (
    RulesDatabase,
    RulesLookupError,
    load_rules_database,
    lookup_rule_reference,
    query_rulebook_database,
)
from .file_loader import UnifiedContextInjector
from .session_controller import GameSessionController, get_game_session_controller

__all__ = [
    "roll_d616",
    "resolve_d616_roll",
    "Character",
    "CharacterRoster",
    "character_roster",
    "CombatTracker",
    "combat_tracker",
    "ARCHETYPE_TEMPLATES",
    "validate_character_build",
    "validate_power_selection",
    "validate_character_powers",
    "generate_character_from_template",
    "export_character_json",
    "load_character_json",
    "CampaignPlanner",
    "create_campaign_plan",
    "get_current_session_context",
    "conclude_session",
    "list_archetypes",
    "list_origins",
    "list_occupations",
    "list_traits",
    "list_tags",
    "lookup_rule_reference",
    "load_rules_database",
    "query_rulebook_database",
    "RulesDatabase",
    "D616ConfigurationError",
    "RulesLookupError",
    "UnifiedContextInjector",
    "GameSessionController",
    "get_game_session_controller",
]
