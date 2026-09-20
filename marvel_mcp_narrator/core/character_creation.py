"""Character creation helpers and archetype templates."""

from __future__ import annotations

from threading import Lock
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


def _parse_rank_required(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


_POWER_REQUIREMENTS_CACHE: dict[str, int | None] | None = None
_POWER_REQUIREMENTS_LOCK = Lock()
_ORIGINS_CACHE: dict[str, str] | None = None
_OCCUPATIONS_CACHE: dict[str, str] | None = None
_TRAITS_CACHE: dict[str, str] | None = None


def _get_power_requirements() -> dict[str, int | None]:
    global _POWER_REQUIREMENTS_CACHE
    if _POWER_REQUIREMENTS_CACHE is None:
        with _POWER_REQUIREMENTS_LOCK:
            if _POWER_REQUIREMENTS_CACHE is None:
                powers_data = load_rules_database().get("powers", [])
                _POWER_REQUIREMENTS_CACHE = {
                    str(power.get("name", "")).strip().casefold(): _parse_rank_required(power.get("rank_required", 1))
                    for power in powers_data
                    if str(power.get("name", "")).strip()
                }
    return _POWER_REQUIREMENTS_CACHE


def _build_named_lookup(key: str) -> dict[str, str]:
    entries = load_rules_database().get(key, [])
    lookup: dict[str, str] = {}
    for entry in entries:
        name = str(entry.get("name", "")).strip()
        if name:
            lookup[name.casefold()] = name
    return lookup


def _get_origins_lookup() -> dict[str, str]:
    global _ORIGINS_CACHE
    if _ORIGINS_CACHE is None:
        with _POWER_REQUIREMENTS_LOCK:
            if _ORIGINS_CACHE is None:
                _ORIGINS_CACHE = _build_named_lookup("origins")
    return _ORIGINS_CACHE


def _get_occupations_lookup() -> dict[str, str]:
    global _OCCUPATIONS_CACHE
    if _OCCUPATIONS_CACHE is None:
        with _POWER_REQUIREMENTS_LOCK:
            if _OCCUPATIONS_CACHE is None:
                _OCCUPATIONS_CACHE = _build_named_lookup("occupations")
    return _OCCUPATIONS_CACHE


def _get_traits_lookup() -> dict[str, str]:
    global _TRAITS_CACHE
    if _TRAITS_CACHE is None:
        with _POWER_REQUIREMENTS_LOCK:
            if _TRAITS_CACHE is None:
                _TRAITS_CACHE = _build_named_lookup("traits")
    return _TRAITS_CACHE


def list_archetypes() -> list[dict[str, str]]:
    return [
        {"name": name, "playstyle": payload["playstyle"]}
        for name, payload in sorted(ARCHETYPE_TEMPLATES.items(), key=lambda item: item[0])
    ]


def list_origins() -> list[str]:
    return sorted(_get_origins_lookup().values())


def list_occupations() -> list[str]:
    return sorted(_get_occupations_lookup().values())


def list_traits() -> list[str]:
    return sorted(_get_traits_lookup().values())


def validate_character_build(
    name: str,
    archetype: str,
    rank: int,
    abilities: dict,
    powers: list,
    origin: str = "Unknown",
    occupation: str = "None",
    traits: list[str] | None = None,
    tags: list[str] | None = None,
) -> dict:
    errors: list[str] = []
    warnings: list[str] = []
    normalized_name = "" if name is None else str(name).strip()
    normalized_origin = str(origin).strip() or "Unknown"
    normalized_occupation = str(occupation).strip() or "None"
    normalized_traits = list(dict.fromkeys([str(item).strip() for item in (traits or []) if str(item).strip()]))
    normalized_tags = list(dict.fromkeys([str(item).strip() for item in (tags or []) if str(item).strip()]))

    if not normalized_name:
        errors.append("Character name is required.")

    template_info = ARCHETYPE_TEMPLATES.get(archetype)
    if template_info is None:
        errors.append(f"Unsupported archetype '{archetype}'.")

    if not 1 <= rank <= 6:
        errors.append("Rank must be between 1 and 6.")

    origins_lookup = _get_origins_lookup()
    occupations_lookup = _get_occupations_lookup()
    traits_lookup = _get_traits_lookup()

    if normalized_origin.casefold() not in origins_lookup and normalized_origin != "Unknown":
        errors.append(f"Unsupported origin '{normalized_origin}'.")
    elif normalized_origin.casefold() in origins_lookup:
        normalized_origin = origins_lookup[normalized_origin.casefold()]

    if normalized_occupation.casefold() not in occupations_lookup and normalized_occupation != "None":
        errors.append(f"Unsupported occupation '{normalized_occupation}'.")
    elif normalized_occupation.casefold() in occupations_lookup:
        normalized_occupation = occupations_lookup[normalized_occupation.casefold()]

    for trait in normalized_traits:
        if trait.casefold() not in traits_lookup:
            warnings.append(f"Trait '{trait}' was not found in local rules data.")

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

    power_index = _get_power_requirements()
    power_issues: list[dict[str, Any]] = []

    for power in powers or []:
        rank_required_from_input: int | None = None
        invalid_input_rank_required = False
        if isinstance(power, dict):
            power_name = str(power.get("name", "")).strip()
            if "rank_required" in power:
                rank_required_from_input = _parse_rank_required(power.get("rank_required", 1))
                invalid_input_rank_required = rank_required_from_input is None
        else:
            power_name = str(power).strip()

        if not power_name:
            continue
        power_key = power_name.casefold()
        if power_key not in power_index:
            warnings.append(f"Power '{power_name}' was not found in local rules data.")
            continue
        database_rank_required = power_index[power_key]
        if rank_required_from_input is not None:
            required_rank = rank_required_from_input
        elif invalid_input_rank_required:
            if database_rank_required is not None:
                warnings.append(
                    f"Power '{power_name}' provided invalid rank_required; using rules data value {database_rank_required}."
                )
                required_rank = database_rank_required
            else:
                errors.append(
                    f"Power '{power_name}' has invalid rank_required in input and invalid rank requirement in rules data."
                )
                continue
        else:
            required_rank = database_rank_required
        if required_rank is None:
            errors.append(f"Power '{power_name}' has an invalid rank requirement in rules data.")
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
        "name": normalized_name,
        "archetype": archetype,
        "origin": normalized_origin,
        "occupation": normalized_occupation,
        "traits": normalized_traits,
        "tags": normalized_tags,
    }


def generate_character_from_template(
    name: str,
    archetype: str,
    rank: int,
    origin: str = "Unknown",
    occupation: str = "None",
    traits: list[str] | None = None,
    tags: list[str] | None = None,
) -> Character:
    normalized_name = "" if name is None else str(name).strip()
    if not normalized_name:
        raise ValueError("Character name is required.")
    if archetype not in ARCHETYPE_TEMPLATES:
        raise ValueError(f"Unsupported archetype '{archetype}'.")
    if not 1 <= rank <= 6:
        raise ValueError("Rank must be between 1 and 6.")

    template = ARCHETYPE_TEMPLATES[archetype]["ranks"][rank]
    return Character(
        name=normalized_name,
        archetype=archetype,
        rank=rank,
        melee=template["melee"],
        agility=template["agility"],
        resilience=template["resilience"],
        vigilance=template["vigilance"],
        ego=template["ego"],
        logic=template["logic"],
        origin=origin,
        occupation=occupation,
        traits=list(traits or []),
        tags=list(tags or []),
    )
