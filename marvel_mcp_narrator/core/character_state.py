"""Character sheet and state tracking for Marvel Multiverse RPG."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from threading import RLock


_ABILITY_FIELDS = ("melee", "agility", "resilience", "vigilance", "ego", "logic")


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
        if condition and condition not in self.conditions:
            self.conditions.append(condition)

    def remove_condition(self, condition: str) -> None:
        if condition in self.conditions:
            self.conditions.remove(condition)

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["defenses"] = {
            "melee_defense": self.melee_defense,
            "agility_defense": self.agility_defense,
            "resilience_defense": self.resilience_defense,
            "vigilance_defense": self.vigilance_defense,
            "ego_defense": self.ego_defense,
            "logic_defense": self.logic_defense,
        }
        return payload


class CharacterRoster:
    """In-memory character store for active sessions and encounters."""

    def __init__(self) -> None:
        self._characters: dict[str, Character] = {}
        self._lock = RLock()

    @staticmethod
    def _normalize(identifier: str) -> str:
        return identifier.casefold()

    @staticmethod
    def _copy_character(character: Character) -> Character:
        return Character(**asdict(character))

    def create_or_load(self, **character_kwargs: int | str) -> tuple[Character, bool]:
        name = str(character_kwargs["name"])
        key = self._normalize(name)
        with self._lock:
            existing = self._characters.get(key)
            if existing is not None:
                definition_fields = (
                    "name",
                    "archetype",
                    "rank",
                    "melee",
                    "agility",
                    "resilience",
                    "vigilance",
                    "ego",
                    "logic",
                )
                mismatches = [
                    field_name
                    for field_name in definition_fields
                    if field_name in character_kwargs and getattr(existing, field_name) != character_kwargs[field_name]
                ]
                if mismatches:
                    mismatched_values = {
                        field_name: {
                            "existing": getattr(existing, field_name),
                            "requested": character_kwargs[field_name],
                        }
                        for field_name in mismatches
                    }
                    raise ValueError(
                        f"Character '{name}' already exists with conflicting attributes: {mismatched_values}."
                    )
                return existing, False
            created = Character(**character_kwargs)
            self._characters[key] = created
            return created, True

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
                return self._characters[key].to_dict()
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

            health_result = character.take_health_damage(health_damage) if health_damage else None
            focus_result = character.take_focus_damage(focus_damage) if focus_damage else None

            return {
                "name": character.name,
                "health": health_result
                or {
                    "resource": "health",
                    "current": character.current_health,
                    "max": character.max_health,
                    "is_unconscious": character.current_health <= 0,
                },
                "focus": focus_result
                or {
                    "resource": "focus",
                    "current": character.current_focus,
                    "max": character.max_focus,
                    "is_shattered": character.current_focus <= 0,
                },
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
