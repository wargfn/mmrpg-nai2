"""Combat tracking and deterministic combat resolution helpers."""

from __future__ import annotations

from threading import RLock
from typing import Any

from marvel_mcp_narrator.core.character_creation import ABILITY_FIELDS
from marvel_mcp_narrator.core.character_state import CharacterRoster, character_roster
from marvel_mcp_narrator.core.d616_engine import D616ConfigurationError, resolve_d616_roll

_VALID_COMBAT_SIDES = {"player", "ally", "npc", "enemy"}
_VALID_TARGET_RESOURCES = {"health", "focus"}


class CombatTracker:
    """Track active combatants and resolve deterministic attacks."""

    def __init__(self, roster: CharacterRoster | None = None) -> None:
        self._roster = roster or character_roster
        self._lock = RLock()
        self._combatants: dict[str, dict[str, str]] = {}

    @staticmethod
    def _normalize_name(name: str) -> str:
        return str(name).strip().casefold()

    @staticmethod
    def _normalize_side(side: str) -> str:
        normalized = str(side).strip().lower()
        if normalized not in _VALID_COMBAT_SIDES:
            raise ValueError(f"Combat side must be one of: {', '.join(sorted(_VALID_COMBAT_SIDES))}.")
        return normalized

    @staticmethod
    def _normalize_target_resource(target_resource: str) -> str:
        normalized = str(target_resource).strip().lower()
        if normalized not in _VALID_TARGET_RESOURCES:
            raise ValueError("Target resource must be 'health' or 'focus'.")
        return normalized

    def _require_known_character(self, name: str) -> dict[str, Any]:
        return self._roster.get_sheet(name)

    def _build_combatant_snapshot(self, name: str, side: str | None = None) -> dict[str, Any]:
        sheet = self._require_known_character(name)
        resolved_side = side
        if resolved_side is None:
            with self._lock:
                resolved_side = self._combatants.get(self._normalize_name(sheet["name"]), {}).get("side")
        return {
            "name": sheet["name"],
            "side": resolved_side or "unassigned",
            "rank": sheet["rank"],
            "current_health": sheet["current_health"],
            "max_health": sheet["max_health"],
            "current_focus": sheet["current_focus"],
            "max_focus": sheet["max_focus"],
            "conditions": list(sheet.get("conditions", [])),
        }

    @staticmethod
    def _validate_d616_values(dice_values: list[int], marvel_index: int, target_number: int | None = None) -> None:
        if len(dice_values) != 3:
            raise ValueError("Manual d616 rolls must include exactly three dice values.")
        if marvel_index not in {0, 1, 2}:
            raise ValueError("Marvel die index must be 0, 1, or 2.")
        if any(value < 1 or value > 6 for value in dice_values):
            raise ValueError("Each d616 die value must be between 1 and 6.")
        if target_number is not None and target_number <= 0:
            raise D616ConfigurationError("Target number must be a positive integer.")

    def clear(self) -> None:
        with self._lock:
            self._combatants.clear()

    def track_combatant(self, name: str, side: str = "player") -> dict[str, Any]:
        sheet = self._require_known_character(name)
        normalized_side = self._normalize_side(side)
        with self._lock:
            self._combatants[self._normalize_name(sheet["name"])] = {
                "name": sheet["name"],
                "side": normalized_side,
            }
        return self._build_combatant_snapshot(sheet["name"], side=normalized_side)

    def get_combat_state(self) -> dict[str, Any]:
        with self._lock:
            tracked = sorted(self._combatants.values(), key=lambda item: (item["side"], item["name"].casefold()))
        sheets = self._roster.get_sheets([entry["name"] for entry in tracked])
        combatants = []
        for entry, sheet in zip(tracked, sheets, strict=True):
            combatants.append(
                {
                    "name": sheet["name"],
                    "side": entry["side"],
                    "rank": sheet["rank"],
                    "current_health": sheet["current_health"],
                    "max_health": sheet["max_health"],
                    "current_focus": sheet["current_focus"],
                    "max_focus": sheet["max_focus"],
                    "conditions": list(sheet.get("conditions", [])),
                }
            )
        return {"combatants": combatants}

    def resolve_manual_roll(
        self,
        *,
        dice_values: list[int],
        marvel_index: int = 1,
        ability_modifier: int = 0,
        target_number: int | None = None,
    ) -> dict[str, Any]:
        self._validate_d616_values(dice_values, marvel_index, target_number=target_number)
        marvel_die = dice_values[marvel_index]
        standards = [value for index, value in enumerate(dice_values) if index != marvel_index]
        is_botch = all(value == 1 for value in dice_values)
        is_ultimate = marvel_die == 1 and standards == [6, 6]
        is_fantastic = marvel_die == 1 and not is_botch
        total_score = standards[0] + standards[1] + (6 if marvel_die == 1 else marvel_die) + ability_modifier
        success = True
        if target_number is not None:
            if is_botch:
                success = False
            elif is_ultimate:
                success = True
            else:
                success = total_score >= target_number
        return {
            "source": "manual",
            "raw_dice": {
                "standard_1": standards[0],
                "marvel_die": marvel_die,
                "standard_2": standards[1],
            },
            "dice_values": [standards[0], marvel_die, standards[1]],
            "marvel_index": marvel_index,
            "ability_modifier": ability_modifier,
            "total_score": total_score,
            "is_fantastic": is_fantastic,
            "is_ultimate": is_ultimate,
            "is_botch": is_botch,
            "target_number": target_number,
            "success": success,
        }

    def resolve_attack(
        self,
        *,
        attacker_name: str,
        target_name: str,
        ability: str,
        attacker_side: str,
        target_side: str,
        target_resource: str = "health",
        edges: int = 0,
        troubles: int = 0,
        manual_roll: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        attacker_sheet = self._require_known_character(attacker_name)
        target_sheet = self._require_known_character(target_name)
        normalized_ability = str(ability).strip().lower()
        if normalized_ability not in ABILITY_FIELDS:
            raise ValueError(f"Unknown ability '{ability}'.")
        if edges < 0 or troubles < 0:
            raise ValueError("Edges and troubles must be non-negative integers.")

        resource = self._normalize_target_resource(target_resource)
        ability_modifier = int(attacker_sheet[normalized_ability])
        target_number = int(target_sheet["defenses"][f"{normalized_ability}_defense"])
        if manual_roll is None:
            roll_result = resolve_d616_roll(
                ability_modifier=ability_modifier,
                target_number=target_number,
                edges=edges,
                troubles=troubles,
            )
        else:
            roll_result = self.resolve_manual_roll(
                dice_values=list(manual_roll["dice_values"]),
                marvel_index=int(manual_roll.get("marvel_index", 1)),
                ability_modifier=ability_modifier,
                target_number=target_number,
            )

        self.track_combatant(attacker_sheet["name"], attacker_side)
        self.track_combatant(target_sheet["name"], target_side)

        damage = None
        target_state = self._build_combatant_snapshot(target_sheet["name"], side=self._normalize_side(target_side))
        if roll_result["success"]:
            damage = self._roster.calculate_attack_damage(
                attacker_name=attacker_sheet["name"],
                ability=normalized_ability,
                marvel_die=int(roll_result["raw_dice"]["marvel_die"]),
                is_fantastic=bool(roll_result["is_fantastic"]),
            )
            damage_amount = int(damage["total_damage"])
            if resource == "health":
                applied = self._roster.apply_damage(target_sheet["name"], health_damage=damage_amount)
            else:
                applied = self._roster.apply_damage(target_sheet["name"], focus_damage=damage_amount)
            target_state = self._build_combatant_snapshot(target_sheet["name"], side=self._normalize_side(target_side))
            target_state["damage_application"] = applied

        return {
            "attacker": self._build_combatant_snapshot(attacker_sheet["name"], side=self._normalize_side(attacker_side)),
            "target": target_state,
            "ability": normalized_ability,
            "target_number": target_number,
            "target_resource": resource,
            "roll": roll_result,
            "damage": damage,
        }

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
        manual_roll = None
        if dice_values is not None:
            manual_roll = {"dice_values": list(dice_values), "marvel_index": marvel_index}
        return self.resolve_attack(
            attacker_name=attacker_name,
            target_name=target_name,
            ability=ability,
            attacker_side="player",
            target_side="enemy",
            target_resource=target_resource,
            edges=edges,
            troubles=troubles,
            manual_roll=manual_roll,
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
        return self.resolve_attack(
            attacker_name=attacker_name,
            target_name=target_name,
            ability=ability,
            attacker_side="enemy",
            target_side="player",
            target_resource=target_resource,
            edges=edges,
            troubles=troubles,
        )


combat_tracker = CombatTracker()
