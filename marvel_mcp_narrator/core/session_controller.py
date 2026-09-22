"""Unified session controller for shared Marvel game mechanics."""

from __future__ import annotations

from typing import Any

from marvel_mcp_narrator.core.combat_tracker import CombatTracker
from marvel_mcp_narrator.core.d616_engine import resolve_d616_roll
from marvel_mcp_narrator.core.memory.campaign_db import CampaignDatabase, get_campaign_database
from marvel_mcp_narrator.core.rules_database import RulesDatabase

_RECENT_MEMORY_LIMIT = 5


class GameSessionController:
    """Shared façade for rules, dice, combat, and campaign-session state."""

    def __init__(
        self,
        *,
        rules_database: RulesDatabase | None = None,
        combat_tracker: CombatTracker | None = None,
        campaign_database: CampaignDatabase | None = None,
    ) -> None:
        self.rules_database = rules_database or RulesDatabase()
        self.combat_tracker = combat_tracker or CombatTracker()
        self.campaign_database = campaign_database or get_campaign_database()

    def roll_action(
        self,
        ability_modifier: int,
        edges: int = 0,
        troubles: int = 0,
        target_number: int | None = None,
    ) -> dict[str, Any]:
        """Resolve a standard d616 action roll."""
        return resolve_d616_roll(
            ability_modifier=ability_modifier,
            edges=edges,
            troubles=troubles,
            target_number=target_number,
        )

    def look_up_rule(self, query: str) -> str:
        """Return formatted rulebook search results."""
        return self.rules_database.query_rules(query)

    def apply_combat_damage(self, target_name: str, rank: int, marvel_die_value: int) -> dict[str, Any]:
        """Apply direct health damage to an active NPC or enemy combatant."""
        if rank < 1:
            raise ValueError("Rank must be a positive integer.")
        if not 1 <= marvel_die_value <= 6:
            raise ValueError("Marvel die value must be between 1 and 6.")

        existing_state = self.combat_tracker.get_combat_state()
        tracked_target = next(
            (
                combatant
                for combatant in existing_state["combatants"]
                if str(combatant["name"]).strip().casefold() == str(target_name).strip().casefold()
            ),
            None,
        )
        if tracked_target is None:
            raise KeyError(f"Combatant '{target_name}' is not currently tracked.")
        if str(tracked_target["side"]) not in {"enemy", "npc"}:
            raise ValueError("Combat damage can only be applied to tracked enemy or NPC combatants.")

        total_damage = int(rank) * int(marvel_die_value)
        damage_update = self.combat_tracker.apply_damage(target_name, health_damage=total_damage)
        return {
            "target": damage_update["target"],
            "damage": {
                "rank": int(rank),
                "marvel_die_value": int(marvel_die_value),
                "damage_formula": "rank * marvel_die_value",
                "total_damage": total_damage,
            },
            "applied": damage_update["applied"],
            "combat_state": damage_update["combat_state"],
        }

    def get_session_status(self) -> dict[str, Any]:
        """Return the current combat snapshot and recent campaign memory context."""
        combat_state = self.combat_tracker.get_combat_state()
        combatants = list(combat_state.get("combatants", []))
        recent_memories = self.campaign_database.list_memories()[:_RECENT_MEMORY_LIMIT]
        return {
            "combatants": combatants,
            "health_pools": {
                combatant["name"]: {
                    "health": {
                        "current": combatant["current_health"],
                        "max": combatant["max_health"],
                    },
                    "focus": {
                        "current": combatant["current_focus"],
                        "max": combatant["max_focus"],
                    },
                }
                for combatant in combatants
            },
            "recent_campaign_memories": recent_memories,
            "campaign_context": self.campaign_database.get_current_session_context(),
        }

    def clear_combat_state(self) -> None:
        """Clear tracked combatants for the active session."""
        self.combat_tracker.clear()

    def get_combat_state(self) -> dict[str, Any]:
        """Return tracked combatants without campaign-memory context."""
        return self.combat_tracker.get_combat_state()

    def resolve_manual_roll(
        self,
        *,
        dice_values: list[int],
        marvel_index: int = 1,
        ability_modifier: int = 0,
        target_number: int | None = None,
    ) -> dict[str, Any]:
        """Normalize and score a manually reported d616 roll."""
        return self.combat_tracker.resolve_manual_roll(
            dice_values=dice_values,
            marvel_index=marvel_index,
            ability_modifier=ability_modifier,
            target_number=target_number,
        )

    def resolve_player_attack(
        self,
        *,
        attacker_name: str,
        target_name: str,
        ability: str,
        dice_values: list[int] | None = None,
        marvel_index: int = 1,
        target_resource: str = "health",
        edges: int = 0,
        troubles: int = 0,
    ) -> dict[str, Any]:
        """Resolve a player-driven attack against an enemy target."""
        return self.combat_tracker.resolve_player_attack(
            attacker_name=attacker_name,
            target_name=target_name,
            ability=ability,
            dice_values=dice_values,
            marvel_index=marvel_index,
            target_resource=target_resource,
            edges=edges,
            troubles=troubles,
        )

    def resolve_npc_action(
        self,
        *,
        attacker_name: str,
        target_name: str,
        ability: str,
        target_resource: str = "health",
        edges: int = 0,
        troubles: int = 0,
    ) -> dict[str, Any]:
        """Resolve an enemy or NPC attack against a player target."""
        return self.combat_tracker.resolve_npc_action(
            attacker_name=attacker_name,
            target_name=target_name,
            ability=ability,
            target_resource=target_resource,
            edges=edges,
            troubles=troubles,
        )

    def list_campaign_memories(self, limit: int | None = None) -> list[dict[str, Any]]:
        """Return stored campaign memories, optionally limited to a recent subset."""
        memories = self.campaign_database.list_memories()
        if limit is None:
            return memories
        return memories[:limit]


def get_game_session_controller(
    *,
    rules_database: RulesDatabase | None = None,
    combat_tracker: CombatTracker | None = None,
    campaign_database: CampaignDatabase | None = None,
) -> GameSessionController:
    """Return a controller instance for an explicit session or request scope."""
    return GameSessionController(
        rules_database=rules_database,
        combat_tracker=combat_tracker,
        campaign_database=campaign_database,
    )
