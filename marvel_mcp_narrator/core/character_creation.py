"""Character creation helpers and archetype templates."""

from __future__ import annotations

import json
from dataclasses import fields
from pathlib import Path
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
_POWER_DETAILS_CACHE: dict[str, dict[str, Any]] | None = None
_POWER_REQUIREMENTS_LOCK = Lock()
_ORIGINS_CACHE: dict[str, str] | None = None
_OCCUPATIONS_CACHE: dict[str, str] | None = None
_TRAITS_CACHE: dict[str, str] | None = None


def _get_power_details() -> dict[str, dict[str, Any]]:
    global _POWER_DETAILS_CACHE
    if _POWER_DETAILS_CACHE is None:
        with _POWER_REQUIREMENTS_LOCK:
            if _POWER_DETAILS_CACHE is None:
                rules = load_rules_database()
                details: dict[str, dict[str, Any]] = {}

                for power in rules.get("powers", []):
                    name = str(power.get("name", "")).strip()
                    if not name:
                        continue
                    details[name.casefold()] = {
                        "name": name,
                        "rank_required": _parse_rank_required(power.get("rank_required", 1)),
                        "prerequisites": [],
                    }

                for power_set in rules.get("power_sets", []):
                    for power in power_set.get("powers", []):
                        name = str(power.get("name", "")).strip()
                        if not name:
                            continue
                        key = name.casefold()
                        prerequisites = [
                            str(prerequisite).strip()
                            for prerequisite in power.get("prerequisites", [])
                            if str(prerequisite).strip()
                        ]
                        rank_required = _parse_rank_required(power.get("rank_required", 1))
                        if key in details:
                            existing = details[key]
                            existing_rank = existing.get("rank_required")
                            if rank_required is not None and (
                                existing_rank is None or rank_required > existing_rank
                            ):
                                existing["rank_required"] = rank_required
                            existing_prereqs = [str(item).strip() for item in existing.get("prerequisites", [])]
                            merged_prereqs = list(dict.fromkeys(existing_prereqs + prerequisites))
                            existing["prerequisites"] = merged_prereqs
                            continue

                        details[key] = {
                            "name": name,
                            "rank_required": rank_required,
                            "prerequisites": prerequisites,
                        }

                _POWER_DETAILS_CACHE = details
    return _POWER_DETAILS_CACHE


def _get_power_requirements() -> dict[str, int | None]:
    global _POWER_REQUIREMENTS_CACHE
    if _POWER_REQUIREMENTS_CACHE is None:
        with _POWER_REQUIREMENTS_LOCK:
            if _POWER_REQUIREMENTS_CACHE is None:
                _POWER_REQUIREMENTS_CACHE = {
                    name: payload.get("rank_required") for name, payload in _get_power_details().items()
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


def validate_power_selection(character_rank: int, owned_powers: list[str], target_power: str) -> tuple[bool, str]:
    normalized_target = str(target_power).strip()
    if not normalized_target:
        return False, "Power name is required."

    power_details = _get_power_details()
    target_data = power_details.get(normalized_target.casefold())
    if target_data is None:
        return False, f"Unsupported power '{normalized_target}'."

    required_rank = target_data.get("rank_required")
    if required_rank is None:
        return False, f"Power '{target_data['name']}' has an invalid rank requirement."
    if character_rank < required_rank:
        return (
            False,
            f"Power '{target_data['name']}' requires rank {required_rank}, but rank is {character_rank}.",
        )

    owned_lookup = {str(power).strip().casefold() for power in owned_powers if str(power).strip()}
    missing_prerequisites = [
        prerequisite
        for prerequisite in target_data.get("prerequisites", [])
        if str(prerequisite).strip().casefold() not in owned_lookup
    ]
    if missing_prerequisites:
        return (
            False,
            f"Power '{target_data['name']}' requires: {', '.join(missing_prerequisites)}.",
        )

    return True, f"Power '{target_data['name']}' is valid."


def validate_character_powers(rank: int, powers_list: list) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    power_issues: list[dict[str, Any]] = []
    power_index = _get_power_requirements()
    normalized_names: list[str] = []

    for power in powers_list or []:
        if isinstance(power, dict):
            power_name = str(power.get("name", "")).strip()
        else:
            power_name = str(power).strip()
        if power_name:
            normalized_names.append(power_name)
    normalized_names = list(dict.fromkeys(normalized_names))

    for power in powers_list or []:
        rank_required_from_input: int | None = None
        if isinstance(power, dict):
            power_name = str(power.get("name", "")).strip()
            if "rank_required" in power:
                rank_required_from_input = _parse_rank_required(power.get("rank_required", 1))
        else:
            power_name = str(power).strip()

        if not power_name:
            continue

        power_key = power_name.casefold()
        if power_key in power_index:
            remaining_owned = [entry for entry in normalized_names if entry.casefold() != power_name.casefold()]
            valid_selection, selection_message = validate_power_selection(
                character_rank=rank,
                owned_powers=remaining_owned,
                target_power=power_name,
            )
            if not valid_selection:
                errors.append(selection_message)
                required_rank = power_index.get(power_key)
                if isinstance(required_rank, int) and rank < required_rank:
                    power_issues.append(
                        {"power": power_name, "rank_required": required_rank, "rank": rank, "valid": False}
                    )
                continue

        if power_key not in power_index:
            if rank_required_from_input is None:
                errors.append(f"Unsupported power '{power_name}'.")
                continue
            required_rank = rank_required_from_input
        else:
            db_rank = power_index[power_key]
            required_rank = rank_required_from_input if rank_required_from_input is not None else db_rank

        if required_rank is None:
            errors.append(f"Power '{power_name}' has an invalid rank requirement.")
            continue
        if rank < required_rank:
            issue = {"power": power_name, "rank_required": required_rank, "rank": rank, "valid": False}
            power_issues.append(issue)
            errors.append(f"Power '{power_name}' requires rank {required_rank}, but rank is {rank}.")

    return {"valid": not errors, "errors": errors, "warnings": warnings, "power_issues": power_issues}


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
    power_sets: list[str | dict] | None = None,
) -> dict:
    errors: list[str] = []
    warnings: list[str] = []
    normalized_name = "" if name is None else str(name).strip()
    normalized_origin = str(origin).strip() or "Unknown"
    normalized_occupation = str(occupation).strip() or "None"
    normalized_traits = list(dict.fromkeys([str(item).strip() for item in (traits or []) if str(item).strip()]))
    normalized_tags = list(dict.fromkeys([str(item).strip() for item in (tags or []) if str(item).strip()]))
    normalized_power_sets = list(power_sets or [])

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

    if normalized_origin.casefold() not in origins_lookup and normalized_origin.casefold() != "unknown":
        errors.append(f"Unsupported origin '{normalized_origin}'.")
    elif normalized_origin.casefold() in origins_lookup:
        normalized_origin = origins_lookup[normalized_origin.casefold()]

    if normalized_occupation.casefold() not in occupations_lookup and normalized_occupation.casefold() != "none":
        errors.append(f"Unsupported occupation '{normalized_occupation}'.")
    elif normalized_occupation.casefold() in occupations_lookup:
        normalized_occupation = occupations_lookup[normalized_occupation.casefold()]

    canonical_traits: list[str] = []
    for trait in normalized_traits:
        key = trait.casefold()
        if key not in traits_lookup:
            errors.append(f"Unsupported trait '{trait}'.")
            continue
        canonical_traits.append(traits_lookup[key])
    normalized_traits = list(dict.fromkeys(canonical_traits))

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

    combined_powers: list = []
    seen_power_entries: set[str] = set()
    for source in [powers or [], normalized_power_sets]:
        for entry in source:
            if isinstance(entry, dict):
                key = json.dumps(entry, ensure_ascii=False, sort_keys=True)
            else:
                key = str(entry).strip().casefold()
            if not key:
                continue
            if key in seen_power_entries:
                continue
            seen_power_entries.add(key)
            combined_powers.append(entry)
    if not normalized_power_sets and combined_powers:
        normalized_power_sets = list(combined_powers)
    power_validation = validate_character_powers(rank=rank, powers_list=combined_powers)
    errors.extend(power_validation["errors"])
    warnings.extend(power_validation["warnings"])

    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "power_issues": power_validation["power_issues"],
        "rank": rank,
        "name": normalized_name,
        "archetype": archetype,
        "origin": normalized_origin,
        "occupation": normalized_occupation,
        "traits": normalized_traits,
        "tags": normalized_tags,
        "power_sets": normalized_power_sets,
    }


def generate_character_from_template(
    name: str,
    archetype: str,
    rank: int,
    origin: str = "Unknown",
    occupation: str = "None",
    traits: list[str] | None = None,
    tags: list[str] | None = None,
    power_sets: list[str | dict] | None = None,
) -> Character:
    normalized_name = "" if name is None else str(name).strip()
    if not normalized_name:
        raise ValueError("Character name is required.")
    if archetype not in ARCHETYPE_TEMPLATES:
        raise ValueError(f"Unsupported archetype '{archetype}'.")
    if not 1 <= rank <= 6:
        raise ValueError("Rank must be between 1 and 6.")

    template = ARCHETYPE_TEMPLATES[archetype]["ranks"][rank]
    validation = validate_character_build(
        name=normalized_name,
        archetype=archetype,
        rank=rank,
        abilities=template,
        powers=list(power_sets or []),
        origin=origin,
        occupation=occupation,
        traits=traits,
        tags=tags,
        power_sets=power_sets,
    )
    if not validation["valid"]:
        raise ValueError("; ".join(validation["errors"]))
    return Character(
        name=validation["name"],
        archetype=archetype,
        rank=rank,
        melee=template["melee"],
        agility=template["agility"],
        resilience=template["resilience"],
        vigilance=template["vigilance"],
        ego=template["ego"],
        logic=template["logic"],
        origin=validation["origin"],
        occupation=validation["occupation"],
        traits=validation["traits"],
        tags=validation["tags"],
        power_sets=validation["power_sets"],
    )


def export_character_json(character: Character, filepath: str) -> None:
    output_path = Path(filepath)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(character.to_dict(), handle, ensure_ascii=False, indent=2)


def load_character_json(filepath: str) -> Character:
    with open(filepath, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("Character file must contain a JSON object.")
    allowed_fields = {field.name for field in fields(Character)}
    derived_fields = {"defenses", "attack_profiles"}
    unknown_fields = sorted(set(payload) - allowed_fields - derived_fields)
    if unknown_fields:
        raise ValueError(f"Unsupported fields in character file: {', '.join(unknown_fields)}")
    character_kwargs = {key: value for key, value in payload.items() if key in allowed_fields}
    return Character(**character_kwargs)
