"""Core deterministic game logic for the Marvel MCP Narrator."""

from .d616_engine import roll_d616
from .rules_database import lookup_rule_reference

__all__ = ["roll_d616", "lookup_rule_reference"]
