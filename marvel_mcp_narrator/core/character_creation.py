"""Character creation helpers and archetype templates."""

from __future__ import annotations

from typing import Any

from marvel_mcp_narrator.core.character_state import Character
from marvel_mcp_narrator.core.rules_database import load_rules_database

ABILITY_FIELDS = ("melee", "agility", "resilience", "vigilance", "ego", "logic")

_BASE_ARCHETYPE_TEMPLATES: dict[str, dict[str, Any]] = {
    "Striker": {"playstyle": "High single-target melee offense.", "base": (5, 4, 3, 2, 2, 2)},
    "Blaster": {"playstyle": "Ranged damage and pressure.", "base": (2, 4, 3, 4, 5, 2)},
    "Protector": {"playstyle": "Frontline defense and ally protection.", "base": (3, 2, 5, 4, 2, 2)},
    "Brawler": {"playstyle": "Durable close-range bruiser.", "base": (4, 3, 5, 3, 2, 2)},
    "Way-Watcher": {"playstyle": "Stealth, scouting, and awareness.", "base": (2, 5, 3, 5, 3, 2)},
    "Polymath": {"playstyle": "Flexible specialist with broad utility.", "base": (3, 3, 3, 4, 4, 4)},
}


def _rank_growth(rank: int) -> int:
    return max(0, rank - 1)


def _build_rank_template(base: tuple[int, int, int, int, int, int], rank: int) -> dict[str, int]:
    growth = _rank_growth(rank)
    return {
        "melee": base[0] + growth,
        "agility": base[1] + growth,
        "resilience": base[2] + growth,
        "vigilance": base[3] + growth,
        "ego": base[4] + growth,
        "logic": base[5] + growth,
    }


ARCHETYPE_TEMPLATES: dict[str, dict[str, Any]] = {
    archetype: {
        "playstyle": payload["playstyle"],
        "ranks": {rank: _build_rank_template(payload["base"], rank) for rank in range(1, 7)},
    }
    for archetype, payload in _BASE_ARCHETYPE_TEMPLATES.items()
}


def list_archetypes() -> list[dict[str, str]]:
    return [
        {"name": name, "playstyle": payload["playstyle"]}
        for name, payload in sorted(ARCHETYPE_TEMPLATES.items(), key=lambda item: item[0])
    ]


def validate_character_build(
    name: str,
    archetype: str,
    rank: int,
    abilities: dict,
    powers: list,
) -> dict:
    errors: list[str] = []
    warnings: list[str] = []

    if not name.strip():
        errors.append("Character name is required.")

    template_info = ARCHETYPE_TEMPLATES.get(archetype)
    if template_info is None:
        errors.append(f"Unsupported archetype '{archetype}'.")

    if not 1 <= rank <= 6:
        errors.append("Rank must be between 1 and 6.")

    normalized_abilities: dict[str, int] = {}
    for ability in ABILITY_FIELDS:
        value = abilities.get(ability) if isinstance(abilities, dict) else None
        if not isinstance(value, int):
            errors.append(f"Ability '{ability}' must be an integer.")
            continue
        if value < 0:
            errors.append(f"Ability '{ability}' must be non-negative.")
            continue
        normalized_abilities[ability] = value

    if template_info is not None and 1 <= rank <= 6 and len(normalized_abilities) == len(ABILITY_FIELDS):
        template = template_info["ranks"][rank]
        expected_total = sum(template.values())
        ability_total = sum(normalized_abilities.values())
        if ability_total != expected_total:
            errors.append(
                f"Ability total {ability_total} does not match rank-{rank} guideline total {expected_total}."
            )

        for ability in ABILITY_FIELDS:
            diff = abs(normalized_abilities[ability] - template[ability])
            if diff > 2:
                warnings.append(
                    f"Ability '{ability}' differs from {archetype} rank-{rank} template by {diff} points."
                )

    powers_data = load_rules_database().get("powers", [])
    power_index = {
        str(power.get("name", "")).strip().casefold(): int(power.get("rank_required", 1))
        for power in powers_data
        if str(power.get("name", "")).strip()
    }
    power_issues: list[dict[str, Any]] = []

    for power in powers or []:
        if isinstance(power, dict):
            power_name = str(power.get("name", "")).strip()
            required_rank = int(power.get("rank_required", 1))
        else:
            power_name = str(power).strip()
            required_rank = power_index.get(power_name.casefold(), 1)

        if not power_name:
            continue
        if power_name.casefold() not in power_index:
            warnings.append(f"Power '{power_name}' was not found in local rules data.")
            continue
        if rank < required_rank:
            issue = {
                "power": power_name,
                "rank_required": required_rank,
                "rank": rank,
                "valid": False,
            }
            power_issues.append(issue)
            errors.append(f"Power '{power_name}' requires rank {required_rank}, but rank is {rank}.")

    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "power_issues": power_issues,
        "rank": rank,
        "archetype": archetype,
    }


def generate_character_from_template(name: str, archetype: str, rank: int) -> Character:
    if archetype not in ARCHETYPE_TEMPLATES:
        raise ValueError(f"Unsupported archetype '{archetype}'.")
    if not 1 <= rank <= 6:
        raise ValueError("Rank must be between 1 and 6.")

    template = ARCHETYPE_TEMPLATES[archetype]["ranks"][rank]
    return Character(
        name=name,
        archetype=archetype,
        rank=rank,
        melee=template["melee"],
        agility=template["agility"],
        resilience=template["resilience"],
        vigilance=template["vigilance"],
        ego=template["ego"],
        logic=template["logic"],
    )
