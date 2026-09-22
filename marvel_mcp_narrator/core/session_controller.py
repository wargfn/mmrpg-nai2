"""Unified session controller for shared Marvel game mechanics."""

from __future__ import annotations

from threading import Lock
from typing import Any

from marvel_mcp_narrator.core.combat_tracker import CombatTracker
from marvel_mcp_narrator.core.d616_engine import resolve_d616_roll
from marvel_mcp_narrator.core.memory.campaign_db import CAMPAIGN_DB_PATH, CampaignDatabase, get_campaign_database
from marvel_mcp_narrator.core.rules_database import RulesDatabase

_RECENT_MEMORY_LIMIT = 5
_DEFAULT_SESSION_CONTROLLER: GameSessionController | None = None
_DEFAULT_SESSION_CONTROLLER_LOCK = Lock()


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
        tracked_side = "npc" if tracked_target is None else str(tracked_target["side"])
        self.combat_tracker.track_combatant(target_name, side=tracked_side)

        total_damage = int(rank) * int(marvel_die_value)
        applied = self.combat_tracker._roster.apply_damage(target_name, health_damage=total_damage)
        combat_state = self.combat_tracker.get_combat_state()
        target_state = next(
            combatant
            for combatant in combat_state["combatants"]
            if str(combatant["name"]).strip().casefold() == str(target_name).strip().casefold()
        )

        return {
            "target": target_state,
            "damage": {
                "rank": int(rank),
                "marvel_die_value": int(marvel_die_value),
                "damage_formula": "rank * marvel_die_value",
                "total_damage": total_damage,
            },
            "applied": applied,
            "combat_state": combat_state,
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
    """Return a reusable default session controller or a custom controller."""
    global _DEFAULT_SESSION_CONTROLLER
    if rules_database is not None or combat_tracker is not None or campaign_database is not None:
        return GameSessionController(
            rules_database=rules_database,
            combat_tracker=combat_tracker,
            campaign_database=campaign_database,
        )

    with _DEFAULT_SESSION_CONTROLLER_LOCK:
        if (
            _DEFAULT_SESSION_CONTROLLER is None
            or _DEFAULT_SESSION_CONTROLLER.campaign_database.path != CAMPAIGN_DB_PATH
        ):
            _DEFAULT_SESSION_CONTROLLER = GameSessionController()
        return _DEFAULT_SESSION_CONTROLLER
