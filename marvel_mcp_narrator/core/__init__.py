"""Core deterministic game logic for the Marvel MCP Narrator."""

from .d616_engine import D616ConfigurationError, roll_d616
from .rules_database import (
    RulesDatabase,
    RulesLookupError,
    load_rules_database,
    lookup_rule_reference,
    query_rulebook_database,
)

__all__ = [
    "roll_d616",
    "lookup_rule_reference",
    "load_rules_database",
    "query_rulebook_database",
    "RulesDatabase",
    "D616ConfigurationError",
    "RulesLookupError",
]
