"""d616 engine utilities for Marvel Multiverse RPG checks."""

from __future__ import annotations

import random
from typing import Any, Callable


class D616ConfigurationError(ValueError):
    """Raised for invalid d616 roll parameters."""


def roll_single_die() -> int:
    """Roll one six-sided die."""
    return random.randint(1, 6)


def _validate_target_number(target_number: int | None) -> None:
    """Validate target-number input shared by public d616 entry points."""
    if target_number is not None and target_number <= 0:
        raise D616ConfigurationError("Target number must be a positive integer.")


def _marvel_die_rank(value: int) -> int:
    """Return relative strength rank where the Marvel 1 outranks a natural 6."""
    return 7 if value == 1 else value


def _marvel_die_total(value: int) -> int:
    """Return the numeric value contributed by the kept Marvel die."""
    return 6 if value == 1 else value


def _resolve_target_success(*, total: int, target_number: int | None, is_botch: bool, is_ultimate: bool) -> bool:
    """Resolve success against a target number with Marvel special cases."""
    if target_number is None:
        return True
    if is_botch:
        return False
    if is_ultimate:
        return True
    return total >= target_number


def _select_low_standard_index(standards: list[int]) -> int:
    """Select the current lowest standard die, preferring the first die on ties."""
    return 0 if standards[0] <= standards[1] else 1


def _select_high_standard_index(standards: list[int]) -> int:
    """Select the current highest standard die, preferring the first die on ties."""
    return 0 if standards[0] >= standards[1] else 1


def _apply_edge_to_marvel(current_value: int, roller: Callable[[], int], marvel_rolls: list[int]) -> int:
    """Reroll the Marvel die and keep the stronger result."""
    reroll = roller()
    marvel_rolls.append(reroll)
    return reroll if _marvel_die_rank(reroll) > _marvel_die_rank(current_value) else current_value


def _apply_trouble_to_marvel(current_value: int, roller: Callable[[], int], marvel_rolls: list[int]) -> int:
    """Reroll the Marvel die and keep the weaker result."""
    reroll = roller()
    marvel_rolls.append(reroll)
    return reroll if _marvel_die_rank(reroll) < _marvel_die_rank(current_value) else current_value


def _apply_edge_to_standard(standards: list[int], roller: Callable[[], int], standard_rolls: dict[str, list[int]]) -> None:
    """Reroll the current lowest standard die and keep the higher result."""
    index = _select_low_standard_index(standards)
    key = f"standard_{index + 1}"
    reroll = roller()
    standard_rolls[key].append(reroll)
    if reroll > standards[index]:
        standards[index] = reroll


def _apply_trouble_to_standard(
    standards: list[int], roller: Callable[[], int], standard_rolls: dict[str, list[int]]
) -> None:
    """Reroll the current highest standard die and keep the lower result."""
    index = _select_high_standard_index(standards)
    key = f"standard_{index + 1}"
    reroll = roller()
    standard_rolls[key].append(reroll)
    if reroll < standards[index]:
        standards[index] = reroll


def _resolve_dice_pool(
    *,
    roller: Callable[[], int],
    net_modifiers: int,
) -> tuple[dict[str, int], dict[str, list[int]], list[int]]:
    """Roll and adjust a d616 pool in Standard-Marvel-Standard order."""
    standard_1 = roller()
    marvel_die = roller()
    standard_2 = roller()
    standards = [standard_1, standard_2]
    marvel_rolls = [marvel_die]
    standard_rolls = {
        "standard_1": [standards[0]],
        "standard_2": [standards[1]],
    }

    if net_modifiers > 0:
        remaining_edges = net_modifiers
        while remaining_edges > 0 and marvel_die != 1:
            marvel_die = _apply_edge_to_marvel(marvel_die, roller, marvel_rolls)
            remaining_edges -= 1
        while remaining_edges > 0:
            _apply_edge_to_standard(standards, roller, standard_rolls)
            remaining_edges -= 1
    elif net_modifiers < 0:
        remaining_troubles = abs(net_modifiers)
        while remaining_troubles > 0 and marvel_die == 1:
            marvel_die = _apply_trouble_to_marvel(marvel_die, roller, marvel_rolls)
            remaining_troubles -= 1
        while remaining_troubles > 0:
            _apply_trouble_to_standard(standards, roller, standard_rolls)
            remaining_troubles -= 1

    raw_dice = {
        "standard_1": standards[0],
        "marvel_die": marvel_die,
        "standard_2": standards[1],
    }
    return raw_dice, standard_rolls, marvel_rolls


def _build_roll_summary(
    *,
    raw_dice: dict[str, int],
    target_number: int | None,
    ability_modifier: int = 0,
) -> dict[str, Any]:
    """Build the shared roll summary fields."""
    standard_1 = raw_dice["standard_1"]
    marvel_die = raw_dice["marvel_die"]
    standard_2 = raw_dice["standard_2"]
    is_botch = standard_1 == 1 and marvel_die == 1 and standard_2 == 1
    is_ultimate = standard_1 == 6 and marvel_die == 1 and standard_2 == 6
    is_fantastic = marvel_die == 1 and not is_botch
    total = standard_1 + _marvel_die_total(marvel_die) + standard_2 + ability_modifier

    return {
        "raw_dice": raw_dice,
        "dice_values": [standard_1, marvel_die, standard_2],
        "ability_modifier": ability_modifier,
        "total_score": total,
        "is_fantastic": is_fantastic,
        "is_ultimate": is_ultimate,
        "is_botch": is_botch,
        "target_number": target_number,
        "success": _resolve_target_success(
            total=total,
            target_number=target_number,
            is_botch=is_botch,
            is_ultimate=is_ultimate,
        ),
    }


def resolve_d616_roll(
    ability_modifier: int = 0,
    target_number: int | None = None,
    edges: int = 0,
    troubles: int = 0,
) -> dict[str, Any]:
    """Simulate a d616 check with optional ability modifier, edges, and troubles."""
    _validate_target_number(target_number)

    raw_dice, standard_rolls, marvel_rolls = _resolve_dice_pool(
        roller=roll_single_die,
        net_modifiers=edges - troubles,
    )
    result = _build_roll_summary(
        raw_dice=raw_dice,
        target_number=target_number,
        ability_modifier=ability_modifier,
    )
    result["net_modifiers"] = edges - troubles
    result["roll_history"] = {
        "standard_1": standard_rolls["standard_1"],
        "marvel_die": marvel_rolls,
        "standard_2": standard_rolls["standard_2"],
    }
    return result


def roll_d616(
    *,
    edge: bool = False,
    trouble: bool = False,
    target_number: int | None = None,
    rng: random.Random | None = None,
) -> dict[str, Any]:
    """Roll Marvel's d616 check with optional edge/trouble and TN resolution."""
    if edge and trouble:
        raise D616ConfigurationError("Edge and trouble cannot both be active.")
    _validate_target_number(target_number)

    roller = (rng if rng is not None else random).randint

    raw_dice, standard_rolls, marvel_rolls = _resolve_dice_pool(
        roller=lambda: roller(1, 6),
        net_modifiers=int(edge) - int(trouble),
    )
    summary = _build_roll_summary(
        raw_dice=raw_dice,
        target_number=target_number,
    )

    result: dict[str, Any] = {
        "raw_dice": raw_dice,
        "dice_values": summary["dice_values"],
        "marvel_die": raw_dice["marvel_die"],
        "regular_dice": [raw_dice["standard_1"], raw_dice["standard_2"]],
        "standard_rolls": standard_rolls,
        "marvel_rolls": marvel_rolls,
        "edge": edge,
        "trouble": trouble,
        "fantastic": summary["is_fantastic"],
        "botch": summary["is_botch"],
        "ultimate": summary["is_ultimate"],
        "total": summary["total_score"],
    }

    if target_number is not None:
        result["target_number"] = target_number
        result["success"] = summary["success"]

    return result
