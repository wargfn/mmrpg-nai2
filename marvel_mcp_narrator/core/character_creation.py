"""Character creation helpers and archetype templates."""

from __future__ import annotations

import json
from dataclasses import fields
from pathlib import Path
from threading import RLock
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
_ARCHETYPE_LOOKUP = {name.casefold(): name for name in ARCHETYPE_TEMPLATES}


def _parse_rank_required(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _canonicalize_archetype(archetype: str) -> str | None:
    return _ARCHETYPE_LOOKUP.get(str(archetype).strip().casefold())


def _normalize_power_dict_keys(entry: dict[str, Any]) -> dict[str, Any]:
    return {str(key).strip().casefold(): value for key, value in entry.items()}


def _parse_power_entry(entry: Any) -> tuple[str, int | None, bool]:
    if isinstance(entry, dict):
        normalized = _normalize_power_dict_keys(entry)
        power_name = str(normalized.get("name", "")).strip()
        rank_key_present = "rank_required" in normalized
        rank_required = _parse_rank_required(normalized.get("rank_required", 1)) if rank_key_present else None
        return power_name, rank_required, rank_key_present
    return str(entry).strip(), None, False


_POWER_REQUIREMENTS_CACHE: dict[str, int | None] | None = None
_POWER_DETAILS_CACHE: dict[str, dict[str, Any]] | None = None
_POWER_REQUIREMENTS_LOCK = RLock()
_ORIGINS_CACHE: dict[str, str] | None = None
_OCCUPATIONS_CACHE: dict[str, str] | None = None
_TRAITS_CACHE: dict[str, str] | None = None
_TAGS_CACHE: dict[str, str] | None = None


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
                    power_set_name = str(power_set.get("name", "Power Set")).strip() or "Power Set"
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
                            existing_prereqs = [str(item).strip() for item in existing.get("prerequisites", []) if str(item).strip()]
                            incoming_summary = str(power.get("summary", "")).strip()
                            incoming_description = str(power.get("description", "")).strip()
                            existing_summary = str(existing.get("summary", "")).strip()
                            existing_description = str(existing.get("description", "")).strip()
                            incoming_text = incoming_description or incoming_summary
                            existing_text = existing_description or existing_summary
                            if (
                                rank_required != existing_rank
                                or set(prerequisites) != set(existing_prereqs)
                                or incoming_text != existing_text
                            ):
                                raise ValueError(
                                    f"Conflicting definitions for power '{name}' in power set '{power_set_name}'."
                                )
                            memberships = list(existing.get("power_sets", []))
                            if power_set_name not in memberships:
                                memberships.append(power_set_name)
                            existing["power_sets"] = memberships
                            continue

                        details[key] = {
                            "name": name,
                            "rank_required": rank_required,
                            "prerequisites": prerequisites,
                            "summary": str(power.get("summary", "")).strip(),
                            "description": str(power.get("description", "")).strip(),
                            "power_sets": [power_set_name],
                        }

                for power_set in rules.get("power_sets", []):
                    power_set_name = str(power_set.get("name", "Power Set")).strip() or "Power Set"
                    for reference in power_set.get("power_references", []):
                        ref_name = str(reference).strip()
                        if not ref_name:
                            continue
                        ref_key = ref_name.casefold()
                        if ref_key not in details:
                            continue
                        memberships = list(details[ref_key].get("power_sets", []))
                        if power_set_name not in memberships:
                            memberships.append(power_set_name)
                        details[ref_key]["power_sets"] = memberships

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
        if not name:
            continue
        lookup[name.casefold()] = name
        for alias in entry.get("aliases", []):
            alias_name = str(alias).strip()
            if alias_name:
                lookup[alias_name.casefold()] = name
        for subcategory in entry.get("subcategories", []):
            sub_name = str(subcategory).strip()
            if not sub_name:
                continue
            lookup[sub_name.casefold()] = sub_name
            lookup[f"{name}: {sub_name}".casefold()] = sub_name
    return lookup


def _list_catalog_names(key: str, *, include_subcategories: bool = False) -> list[str]:
    entries = load_rules_database().get(key, [])
    values: list[str] = []
    for entry in entries:
        name = str(entry.get("name", "")).strip()
        if include_subcategories:
            subcategories = [str(item).strip() for item in entry.get("subcategories", []) if str(item).strip()]
            if name:
                values.append(name)
            if subcategories:
                values.extend(subcategories)
                continue
        if name:
            values.append(name)
    return sorted(set(values))


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


def _get_tags_lookup() -> dict[str, str]:
    global _TAGS_CACHE
    if _TAGS_CACHE is None:
        with _POWER_REQUIREMENTS_LOCK:
            if _TAGS_CACHE is None:
                _TAGS_CACHE = _build_named_lookup("tags")
    return _TAGS_CACHE


def list_archetypes() -> list[dict[str, str]]:
    return [
        {"name": name, "playstyle": payload["playstyle"]}
        for name, payload in sorted(ARCHETYPE_TEMPLATES.items(), key=lambda item: item[0])
    ]


def list_origins() -> list[str]:
    return _list_catalog_names("origins", include_subcategories=True)


def list_occupations() -> list[str]:
    return _list_catalog_names("occupations")


def list_traits() -> list[str]:
    return _list_catalog_names("traits")


def list_tags() -> list[str]:
    return _list_catalog_names("tags")


def validate_power_selection(
    character_rank: int,
    owned_powers: list[str],
    target_power: str,
    rank_required_override: int | None = None,
) -> tuple[bool, str]:
    normalized_target = str(target_power).strip()
    if not normalized_target:
        return False, "Power name is required."

    power_details = _get_power_details()
    target_data = power_details.get(normalized_target.casefold())
    if target_data is None:
        return False, f"Unsupported power '{normalized_target}'."

    required_rank = rank_required_override if rank_required_override is not None else target_data.get("rank_required")
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
    owned_so_far: list[str] = []

    for power in powers_list or []:
        power_name, rank_required_from_input, rank_required_was_provided = _parse_power_entry(power)

        if not power_name:
            continue
        if rank_required_was_provided and rank_required_from_input is None:
            errors.append(f"Power '{power_name}' has an invalid rank requirement.")
            continue
        power_key = power_name.casefold()
        if power_key in power_index:
            valid_selection, selection_message = validate_power_selection(
                character_rank=rank,
                owned_powers=owned_so_far,
                target_power=power_name,
                rank_required_override=rank_required_from_input,
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
            errors.append(f"Unsupported power '{power_name}'.")
            continue

        db_rank = power_index[power_key]
        required_rank = rank_required_from_input if rank_required_from_input is not None else db_rank

        if required_rank is None:
            errors.append(f"Power '{power_name}' has an invalid rank requirement.")
            continue
        if rank < required_rank:
            issue = {"power": power_name, "rank_required": required_rank, "rank": rank, "valid": False}
            power_issues.append(issue)
            errors.append(f"Power '{power_name}' requires rank {required_rank}, but rank is {rank}.")
            continue

        owned_so_far.append(power_name)

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
    canonical_archetype = _canonicalize_archetype(archetype)
    normalized_origin = str(origin).strip() or "Unknown"
    normalized_occupation = str(occupation).strip() or "None"
    normalized_traits = list(dict.fromkeys([str(item).strip() for item in (traits or []) if str(item).strip()]))
    normalized_tags = list(dict.fromkeys([str(item).strip() for item in (tags or []) if str(item).strip()]))
    normalized_power_sets = list(power_sets or [])

    if not normalized_name:
        errors.append("Character name is required.")

    template_info = ARCHETYPE_TEMPLATES.get(canonical_archetype) if canonical_archetype else None
    if template_info is None:
        errors.append(f"Unsupported archetype '{archetype}'.")

    if not 1 <= rank <= 6:
        errors.append("Rank must be between 1 and 6.")

    origins_lookup = _get_origins_lookup()
    occupations_lookup = _get_occupations_lookup()
    traits_lookup = _get_traits_lookup()
    tags_lookup = _get_tags_lookup()

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

    canonical_tags: list[str] = []
    for tag in normalized_tags:
        key = tag.casefold()
        if key not in tags_lookup:
            errors.append(f"Unsupported tag '{tag}'.")
            continue
        canonical_tags.append(tags_lookup[key])
    normalized_tags = list(dict.fromkeys(canonical_tags))

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
                    f"Ability '{ability}' differs from {(canonical_archetype or archetype)} rank-{rank} template by {diff} points."
                )

    power_order: list[str] = []
    merged_power_entries: dict[str, Any] = {}
    merged_power_sources: dict[str, str] = {}
    source_precedence = {"powers": 1, "power_sets": 2}
    explicit_rank_requirements: dict[str, int] = {}
    for source_name, source in [("powers", powers or []), ("power_sets", normalized_power_sets)]:
        for entry in source:
            power_name, rank_required, rank_required_was_provided = _parse_power_entry(entry)
            if power_name:
                key = power_name.casefold()
            else:
                key = str(entry).strip().casefold()
            if not key:
                continue
            if rank_required_was_provided and rank_required is None:
                errors.append(f"Power '{power_name}' has an invalid rank requirement.")
                continue
            if rank_required_was_provided and rank_required is not None:
                existing_rank = explicit_rank_requirements.get(key)
                if existing_rank is not None and existing_rank != rank_required:
                    errors.append(
                        f"Conflicting rank requirements provided for power '{power_name}': {existing_rank} vs {rank_required}."
                    )
                    continue
                explicit_rank_requirements[key] = rank_required
            if key in merged_power_entries:
                previous_entry = merged_power_entries[key]
                _, _, previous_rank_was_provided = _parse_power_entry(previous_entry)
                previous_source = merged_power_sources[key]
                if rank_required_was_provided and (
                    not previous_rank_was_provided
                    or source_precedence[source_name] > source_precedence[previous_source]
                    or source_name == previous_source
                ):
                    merged_power_entries[key] = entry
                    merged_power_sources[key] = source_name
                continue
            power_order.append(key)
            merged_power_entries[key] = entry
            merged_power_sources[key] = source_name
    combined_powers = [merged_power_entries[key] for key in power_order]
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
        "archetype": canonical_archetype or archetype,
        "origin": normalized_origin,
        "occupation": normalized_occupation,
        "traits": normalized_traits,
        "tags": normalized_tags,
        "power_sets": combined_powers,
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
    canonical_archetype = _canonicalize_archetype(archetype)
    if not normalized_name:
        raise ValueError("Character name is required.")
    if canonical_archetype is None:
        raise ValueError(f"Unsupported archetype '{archetype}'.")
    if not 1 <= rank <= 6:
        raise ValueError("Rank must be between 1 and 6.")

    template = ARCHETYPE_TEMPLATES[canonical_archetype]["ranks"][rank]
    validation = validate_character_build(
        name=normalized_name,
        archetype=canonical_archetype,
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
        archetype=canonical_archetype,
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
