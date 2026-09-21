"""Character sheet and state tracking for Marvel Multiverse RPG."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from threading import RLock


_ABILITY_FIELDS = ("melee", "agility", "resilience", "vigilance", "ego", "logic")
_CHARACTER_DEFINITION_FIELDS = (
    "archetype",
    "rank",
    *_ABILITY_FIELDS,
    "origin",
    "occupation",
    "traits",
    "tags",
    "power_sets",
)


@dataclass(slots=True)
class Character:
    """Represents a Marvel Multiverse RPG character with mutable combat state."""

    name: str
    archetype: str
    rank: int
    melee: int
    agility: int
    resilience: int
    vigilance: int
    ego: int
    logic: int
    origin: str = "Unknown"
    occupation: str = "None"
    traits: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    power_sets: list[str | dict] = field(default_factory=list)
    max_health: int | None = None
    current_health: int | None = None
    max_focus: int | None = None
    current_focus: int | None = None
    karma: int = 0
    conditions: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not 1 <= self.rank <= 6:
            raise ValueError("Rank must be between 1 and 6.")

        for ability_name in _ABILITY_FIELDS:
            ability_value = getattr(self, ability_name)
            if ability_value < 0:
                raise ValueError(f"Ability '{ability_name}' must be non-negative.")

        if self.max_health is None:
            self.max_health = max(10, self.resilience * 30)
        if self.max_focus is None:
            self.max_focus = max(10, self.vigilance * 30)

        if self.max_health < 1 or self.max_focus < 1:
            raise ValueError("Maximum health and focus must be positive.")

        if self.current_health is None:
            self.current_health = self.max_health
        if self.current_focus is None:
            self.current_focus = self.max_focus

        self.current_health = max(0, min(self.current_health, self.max_health))
        self.current_focus = max(0, min(self.current_focus, self.max_focus))
        self.conditions = list(dict.fromkeys(self.conditions))
        self.traits = [str(item).strip() for item in self.traits if str(item).strip()]
        self.traits = list(dict.fromkeys(self.traits))
        self.tags = [str(item).strip() for item in self.tags if str(item).strip()]
        self.tags = list(dict.fromkeys(self.tags))
        normalized_power_sets: list[str | dict] = []
        seen_power_sets: set[str] = set()
        for entry in self.power_sets:
            normalized_entry, key = self._normalize_power_set_entry(entry)
            if normalized_entry is None:
                continue
            if key not in seen_power_sets:
                seen_power_sets.add(key)
                normalized_power_sets.append(normalized_entry)
        self.power_sets = normalized_power_sets

    @staticmethod
    def _normalize_power_set_entry(entry: object) -> tuple[str | dict | None, str]:
        if isinstance(entry, dict):
            normalized_dict: dict[str, object] = {}
            comparable_dict: dict[str, object] = {}
            for key, value in entry.items():
                key_text = str(key).strip()
                if not key_text:
                    continue
                if isinstance(value, str):
                    normalized_value = value.strip()
                    comparable_value: object = normalized_value.casefold()
                else:
                    normalized_value = value
                    comparable_value = value
                normalized_dict[key_text] = normalized_value
                comparable_dict[key_text.casefold()] = comparable_value
            if not normalized_dict:
                return None, ""
            return normalized_dict, json.dumps(comparable_dict, ensure_ascii=False, sort_keys=True)

        normalized = str(entry).strip()
        if not normalized:
            return None, ""
        return normalized, normalized.casefold()

    @property
    def melee_defense(self) -> int:
        return 10 + self.melee

    @property
    def agility_defense(self) -> int:
        return 10 + self.agility

    @property
    def resilience_defense(self) -> int:
        return 10 + self.resilience

    @property
    def vigilance_defense(self) -> int:
        return 10 + self.vigilance

    @property
    def ego_defense(self) -> int:
        return 10 + self.ego

    @property
    def logic_defense(self) -> int:
        return 10 + self.logic

    def damage_multiplier(self, bonus_multiplier: int = 0) -> int:
        if bonus_multiplier < 0:
            raise ValueError("Bonus multiplier must be non-negative.")
        return self.rank + bonus_multiplier

    def calculate_attack_damage(
        self,
        ability: str,
        marvel_die: int,
        *,
        is_fantastic: bool = False,
        bonus_multiplier: int = 0,
    ) -> dict:
        if ability not in _ABILITY_FIELDS:
            raise ValueError(f"Unknown ability '{ability}'.")
        if marvel_die < 0:
            raise ValueError("Marvel die must be non-negative.")

        multiplier = self.damage_multiplier(bonus_multiplier=bonus_multiplier)
        base_damage = (marvel_die * multiplier) + getattr(self, ability)
        total_damage = base_damage * 2 if is_fantastic else base_damage

        return {
            "attacker": self.name,
            "ability": ability,
            "marvel_die": marvel_die,
            "damage_multiplier": multiplier,
            "ability_score": getattr(self, ability),
            "is_fantastic": is_fantastic,
            "base_damage": base_damage,
            "total_damage": total_damage,
        }

    def take_health_damage(self, amount: int) -> dict:
        if amount < 0:
            raise ValueError("Damage amount must be non-negative.")
        previous_health = self.current_health
        self.current_health = max(0, self.current_health - amount)
        return {
            "name": self.name,
            "resource": "health",
            "previous": previous_health,
            "damage": amount,
            "current": self.current_health,
            "max": self.max_health,
            "is_unconscious": self.current_health <= 0,
        }

    def take_focus_damage(self, amount: int) -> dict:
        if amount < 0:
            raise ValueError("Damage amount must be non-negative.")
        previous_focus = self.current_focus
        self.current_focus = max(0, self.current_focus - amount)
        return {
            "name": self.name,
            "resource": "focus",
            "previous": previous_focus,
            "damage": amount,
            "current": self.current_focus,
            "max": self.max_focus,
            "is_shattered": self.current_focus <= 0,
        }

    def spend_focus(self, cost: int) -> bool:
        if cost < 0:
            raise ValueError("Focus cost must be non-negative.")
        if cost > self.current_focus:
            return False
        self.current_focus -= cost
        return True

    def add_condition(self, condition: str) -> None:
        normalized = condition.strip()
        if normalized and normalized not in self.conditions:
            self.conditions.append(normalized)

    def remove_condition(self, condition: str) -> None:
        normalized = condition.strip()
        if normalized in self.conditions:
            self.conditions.remove(normalized)

    def get_defenses(self) -> dict[str, int]:
        return {
            "melee_defense": self.melee_defense,
            "agility_defense": self.agility_defense,
            "resilience_defense": self.resilience_defense,
            "vigilance_defense": self.vigilance_defense,
            "ego_defense": self.ego_defense,
            "logic_defense": self.logic_defense,
        }

    def get_attack_profiles(self) -> dict[str, dict[str, str | int]]:
        return {
            ability: {
                "ability_score": getattr(self, ability),
                "damage_multiplier": self.rank,
                "formula": "(marvel_die * damage_multiplier) + ability_score",
                "fantastic_rule": "Double total damage on Fantastic hits",
            }
            for ability in _ABILITY_FIELDS
        }

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["defenses"] = self.get_defenses()
        payload["attack_profiles"] = self.get_attack_profiles()
        return payload


class CharacterRoster:
    """In-memory character store for active sessions and encounters."""

    def __init__(self) -> None:
        self._characters: dict[str, Character] = {}
        self._lock = RLock()

    @staticmethod
    def _normalize(identifier: str) -> str:
        return str(identifier).strip().casefold()

    @staticmethod
    def _canonical_name(name: str) -> str:
        return str(name).strip()

    @staticmethod
    def _copy_character(character: Character) -> Character:
        return Character(
            name=character.name,
            archetype=character.archetype,
            rank=character.rank,
            melee=character.melee,
            agility=character.agility,
            resilience=character.resilience,
            vigilance=character.vigilance,
            ego=character.ego,
            logic=character.logic,
            max_health=character.max_health,
            current_health=character.current_health,
            max_focus=character.max_focus,
            current_focus=character.current_focus,
            karma=character.karma,
            conditions=list(character.conditions),
            origin=character.origin,
            occupation=character.occupation,
            traits=list(character.traits),
            tags=list(character.tags),
            power_sets=[dict(item) if isinstance(item, dict) else item for item in character.power_sets],
        )

    @staticmethod
    def _comparable_field_value(field_name: str, value: object) -> object:
        if field_name == "archetype":
            return str(value).strip().casefold()
        if field_name in {"origin", "occupation"}:
            return str(value).strip().casefold()
        if field_name in {"traits", "tags"}:
            return sorted({str(item).strip().casefold() for item in value if str(item).strip()})  # type: ignore[arg-type]
        if field_name == "power_sets":
            comparable: list[str] = []
            for item in value:  # type: ignore[arg-type]
                normalized_item, key = Character._normalize_power_set_entry(item)
                if normalized_item is not None:
                    comparable.append(key)
            return comparable
        return value

    def create_or_load(
        self,
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
    ) -> tuple[dict, bool]:
        canonical_name = self._canonical_name(name)
        if not canonical_name:
            raise ValueError("Character name is required.")
        key = self._normalize(canonical_name)
        requested_values = {
            "archetype": archetype,
            "rank": rank,
            "melee": melee,
            "agility": agility,
            "resilience": resilience,
            "vigilance": vigilance,
            "ego": ego,
            "logic": logic,
            "origin": str(origin).strip() or "Unknown",
            "occupation": str(occupation).strip() or "None",
            "traits": list(dict.fromkeys([str(item).strip() for item in (traits or []) if str(item).strip()])),
            "tags": list(dict.fromkeys([str(item).strip() for item in (tags or []) if str(item).strip()])),
            "power_sets": list(power_sets or []),
        }
        with self._lock:
            existing = self._characters.get(key)
            if existing is not None:
                mismatches = [
                    field_name
                    for field_name in _CHARACTER_DEFINITION_FIELDS
                    if self._comparable_field_value(field_name, getattr(existing, field_name))
                    != self._comparable_field_value(field_name, requested_values[field_name])
                ]
                if mismatches:
                    mismatch_parts = [
                        f"{field_name} (existing={getattr(existing, field_name)!r}, requested={requested_values[field_name]!r})"
                        for field_name in sorted(mismatches)
                    ]
                    raise ValueError(
                        f"Character '{existing.name}' already exists with conflicting attributes: {', '.join(mismatch_parts)}."
                    )
                return self._copy_character(existing).to_dict(), False
            created = Character(
                name=canonical_name,
                archetype=archetype,
                rank=rank,
                melee=melee,
                agility=agility,
                resilience=resilience,
                vigilance=vigilance,
                ego=ego,
                logic=logic,
                origin=requested_values["origin"],
                occupation=requested_values["occupation"],
                traits=requested_values["traits"],
                tags=requested_values["tags"],
                power_sets=requested_values["power_sets"],
            )
            self._characters[key] = created
            return self._copy_character(created).to_dict(), True

    def get_copy(self, name: str) -> Character:
        key = self._normalize(name)
        with self._lock:
            try:
                return self._copy_character(self._characters[key])
            except KeyError as error:
                raise KeyError(f"Character '{name}' was not found.") from error

    def get_sheet(self, name: str) -> dict:
        key = self._normalize(name)
        with self._lock:
            try:
                return self._copy_character(self._characters[key]).to_dict()
            except KeyError as error:
                raise KeyError(f"Character '{name}' was not found.") from error

    def apply_damage(self, name: str, health_damage: int = 0, focus_damage: int = 0) -> dict:
        if health_damage < 0 or focus_damage < 0:
            raise ValueError("Damage values must be non-negative.")
        key = self._normalize(name)
        with self._lock:
            try:
                character = self._characters[key]
            except KeyError as error:
                raise KeyError(f"Character '{name}' was not found.") from error

            health_result = character.take_health_damage(health_damage)
            focus_result = character.take_focus_damage(focus_damage)

            return {
                "name": character.name,
                "health": health_result,
                "focus": focus_result,
                "conditions": list(character.conditions),
            }

    def calculate_attack_damage(
        self,
        attacker_name: str,
        ability: str,
        marvel_die: int,
        *,
        is_fantastic: bool = False,
        bonus_multiplier: int = 0,
    ) -> dict:
        key = self._normalize(attacker_name)
        with self._lock:
            try:
                character = self._characters[key]
            except KeyError as error:
                raise KeyError(f"Character '{attacker_name}' was not found.") from error
            return character.calculate_attack_damage(
                ability=ability,
                marvel_die=marvel_die,
                is_fantastic=is_fantastic,
                bonus_multiplier=bonus_multiplier,
            )

    def clear(self) -> None:
        with self._lock:
            self._characters.clear()


character_roster = CharacterRoster()
