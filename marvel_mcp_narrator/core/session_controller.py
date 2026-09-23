"""Unified session controller for shared Marvel game mechanics."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from marvel_mcp_narrator.core.character_state import CharacterRoster, character_roster
from marvel_mcp_narrator.core.combat_tracker import CombatTracker
from marvel_mcp_narrator.core.d616_engine import resolve_d616_roll
from marvel_mcp_narrator.core.file_loader import UnifiedContextInjector
from marvel_mcp_narrator.core.memory.campaign_db import CampaignDatabase, get_campaign_database
from marvel_mcp_narrator.core.rules_database import RulesDatabase

RECENT_MEMORY_LIMIT = 5
DEFAULT_MAX_HISTORY_TURNS = 8
DEFAULT_SUMMARIZATION_INTERVAL = 5


@dataclass(slots=True)
class SessionHistoryManager:
    """Manage active chat history, pruning, and periodic summarization."""

    session_controller: "GameSessionController"
    system_prompt_builder: Callable[[], str]
    max_history_turns: int = DEFAULT_MAX_HISTORY_TURNS
    summarization_interval: int = DEFAULT_SUMMARIZATION_INTERVAL
    history: list[dict[str, str]] = field(default_factory=list)
    _raw_messages: list[dict[str, str]] = field(default_factory=list)
    completed_turns: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.max_history_turns, int) or self.max_history_turns < 1:
            raise ValueError("max_history_turns must be a positive integer.")
        if not isinstance(self.summarization_interval, int) or self.summarization_interval < 1:
            raise ValueError("summarization_interval must be a positive integer.")
        self.refresh_history()

    def refresh_history(self) -> None:
        """Rebuild the exposed prompt history with the latest system context."""
        self.history[:] = [
            {"role": "system", "content": str(self.system_prompt_builder())},
            *self._raw_messages[-self.max_history_turns :],
        ]

    def build_request_messages(self, user_prompt: str | None = None) -> list[dict[str, str]]:
        """Return the active prompt window to send to the model."""
        self.refresh_history()
        messages = list(self.history)
        injected_context = self.session_controller.build_context_injection(user_prompt or "")
        if injected_context:
            messages.insert(1, {"role": "system", "content": injected_context})
        return messages

    def raw_length(self) -> int:
        """Return the current count of raw non-system messages."""
        return len(self._raw_messages)

    def append_message(self, role: str, content: str) -> None:
        """Append a raw history message and refresh the active window."""
        self._raw_messages.append({"role": role, "content": content})
        self.refresh_history()

    def rollback_to(self, raw_length: int) -> None:
        """Rollback pending messages after a failed model request."""
        del self._raw_messages[raw_length:]
        self.refresh_history()

    def reset(self) -> None:
        """Clear active raw history for the current session."""
        self._raw_messages.clear()
        self.completed_turns = 0
        self.refresh_history()

    def complete_turn(self, summarizer: Callable[[str, list[dict[str, str]]], str] | None = None) -> bool:
        """Record a completed prompt-response cycle and summarize older turns when due."""
        self.completed_turns += 1
        if self.completed_turns % self.summarization_interval != 0:
            self.refresh_history()
            return False
        if len(self._raw_messages) <= self.max_history_turns:
            self.refresh_history()
            return False

        pruned_messages = list(self._raw_messages[:-self.max_history_turns])
        existing_summary = self.session_controller.get_previous_campaign_events_summary() or ""
        summary = ""
        if summarizer is not None:
            try:
                summary = str(summarizer(existing_summary, pruned_messages)).strip()
            except Exception:
                summary = ""
        if not summary:
            summary = self._fallback_summary(existing_summary, pruned_messages)
        self.session_controller.save_previous_campaign_events_summary(summary)
        self._raw_messages[:] = self._raw_messages[-self.max_history_turns :]
        self.refresh_history()
        return True

    @staticmethod
    def _fallback_summary(existing_summary: str, messages: list[dict[str, str]]) -> str:
        rendered_messages = [
            f"{message['role'].capitalize()}: {message['content'].strip()}"
            for message in messages
            if str(message.get("content", "")).strip()
        ]
        compressed_excerpt = " ".join(rendered_messages[:6]).strip()
        compressed_excerpt = compressed_excerpt[:800].rstrip()
        if existing_summary and compressed_excerpt:
            return f"{existing_summary} {compressed_excerpt}".strip()
        return existing_summary or compressed_excerpt or "No summarized campaign events yet."


class GameSessionController:
    """Shared façade for rules, dice, combat, and campaign-session state."""

    def __init__(
        self,
        *,
        rules_database: RulesDatabase | None = None,
        combat_tracker: CombatTracker | None = None,
        campaign_database: CampaignDatabase | None = None,
        character_roster_store: CharacterRoster | None = None,
        context_injector: UnifiedContextInjector | None = None,
    ) -> None:
        roster = character_roster_store or character_roster
        self.rules_database = rules_database or RulesDatabase()
        self.character_roster = roster
        self.combat_tracker = combat_tracker or CombatTracker(roster=roster)
        self.campaign_database = campaign_database or get_campaign_database()
        self.context_injector = context_injector or UnifiedContextInjector(
            campaign_database=self.campaign_database,
            character_roster_store=roster,
        )

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
        if not isinstance(rank, int):
            raise ValueError("Rank must be a positive integer.")
        if not isinstance(marvel_die_value, int):
            raise ValueError("Marvel die value must be an integer between 1 and 6.")
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
                "rank": rank,
                "marvel_die_value": marvel_die_value,
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
        recent_memories = self.campaign_database.list_memories()[:RECENT_MEMORY_LIMIT]
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
            "previous_campaign_events_summary": self.get_previous_campaign_events_summary(),
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
        if limit is not None and not isinstance(limit, int):
            raise ValueError("Memory limit must be a non-negative integer.")
        if limit is not None and limit < 0:
            raise ValueError("Memory limit must be a non-negative integer.")
        memories = self.campaign_database.list_memories()
        if limit is None:
            return memories
        return memories[:limit]

    def get_previous_campaign_events_summary(self) -> str | None:
        """Return the persisted rolling summary of previous campaign events."""
        return self.campaign_database.get_previous_campaign_events_summary()

    def save_previous_campaign_events_summary(self, summary: str) -> str:
        """Persist the rolling summary of previous campaign events."""
        return self.campaign_database.save_previous_campaign_events_summary(summary)

    def build_context_injection(self, query: str) -> str:
        """Return relevant prompt-specific RAG context for the current session."""
        if not str(query).strip():
            return ""
        return self.context_injector.build_context_block(query)


def get_game_session_controller(
    *,
    rules_database: RulesDatabase | None = None,
    combat_tracker: CombatTracker | None = None,
    campaign_database: CampaignDatabase | None = None,
    character_roster_store: CharacterRoster | None = None,
    context_injector: UnifiedContextInjector | None = None,
) -> GameSessionController:
    """Return a controller instance for an explicit session or request scope."""
    return GameSessionController(
        rules_database=rules_database,
        combat_tracker=combat_tracker,
        campaign_database=campaign_database,
        character_roster_store=character_roster_store,
        context_injector=context_injector,
    )
