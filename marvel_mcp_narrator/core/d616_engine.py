"""d616 engine utilities for Marvel Multiverse RPG checks."""

from __future__ import annotations

import random
from typing import Any


class D616ConfigurationError(ValueError):
    """Raised for invalid d616 roll parameters."""


def roll_single_die() -> int:
    """Roll one six-sided die."""
    return random.randint(1, 6)


def _validate_target_number(target_number: int | None) -> None:
    """Validate target-number input shared by public d616 entry points."""
    if target_number is not None and target_number <= 0:
        raise D616ConfigurationError("Target number must be a positive integer.")


def _select_marvel_die(marvel_rolls: list[int], *, trouble: bool) -> int:
    """Select the kept Marvel die using the shared edge/trouble ranking."""
    selector = min if trouble else max
    return selector(marvel_rolls, key=_marvel_die_rank)


def _resolve_target_success(*, total: int, target_number: int | None, is_botch: bool, is_ultimate: bool) -> bool:
    """Resolve success against a target number with Marvel special cases."""
    if target_number is None:
        return True
    if is_botch:
        return False
    if is_ultimate:
        return True
    return total >= target_number


def resolve_d616_roll(
    ability_modifier: int = 0,
    target_number: int | None = None,
    edges: int = 0,
    troubles: int = 0,
) -> dict[str, Any]:
    """Simulate a d616 check with optional ability modifier, edges, and troubles."""
    _validate_target_number(target_number)

    s1 = roll_single_die()
    s2 = roll_single_die()
    marvel_rolls = [roll_single_die()]
    net_modifiers = edges - troubles

    if net_modifiers > 0:
        for _ in range(net_modifiers):
            if marvel_rolls[-1] == 1:
                break
            marvel_rolls.append(roll_single_die())
        m_raw = _select_marvel_die(marvel_rolls, trouble=False)
    elif net_modifiers < 0:
        for _ in range(abs(net_modifiers)):
            marvel_rolls.append(roll_single_die())
        m_raw = _select_marvel_die(marvel_rolls, trouble=True)
    else:
        m_raw = marvel_rolls[0]

    is_botch = s1 == 1 and s2 == 1 and m_raw == 1
    is_ultimate = s1 == 6 and s2 == 6 and m_raw == 1
    is_fantastic = m_raw == 1 and not is_botch
    total_score = s1 + s2 + m_raw + ability_modifier
    if is_fantastic:
        total_score += 6

    success = _resolve_target_success(
        total=total_score,
        target_number=target_number,
        is_botch=is_botch,
        is_ultimate=is_ultimate,
    )

    return {
        "raw_dice": {"standard_1": s1, "standard_2": s2, "marvel_die": m_raw},
        "dice_values": [s1, s2, m_raw],
        "ability_modifier": ability_modifier,
        "net_modifiers": net_modifiers,
        "total_score": total_score,
        "is_fantastic": is_fantastic,
        "is_ultimate": is_ultimate,
        "is_botch": is_botch,
        "target_number": target_number,
        "success": success,
    }


def _marvel_die_rank(value: int) -> int:
    """Return relative strength rank where 1 is remapped above 6 for comparisons."""
    return 7 if value == 1 else value


def roll_d616(
    *,
    edge: bool = False,
    trouble: bool = False,
    target_number: int | None = None,
    rng: random.Random | None = None,
) -> dict[str, Any]:
    """Roll Marvel's d616 check with optional edge/trouble and TN resolution.

    Pass a seeded ``rng`` instance for reproducible rolls.
    A Fantastic roll is determined from the kept Marvel die roll of ``1`` and grants +6.
    With Edge, an initial Marvel die roll of ``1`` is already best and is not rerolled.
    Trouble keeps the worse Marvel die under the same ranking where ``1`` is best.
    """
    if edge and trouble:
        raise D616ConfigurationError("Edge and trouble cannot both be active.")
    _validate_target_number(target_number)

    roller = rng if rng is not None else random

    initial_marvel_die = roller.randint(1, 6)
    marvel_rolls = [initial_marvel_die]
    if trouble:
        marvel_rolls.append(roller.randint(1, 6))
    elif edge and initial_marvel_die != 1:
        marvel_rolls.append(roller.randint(1, 6))
    if edge:
        marvel_die = _select_marvel_die(marvel_rolls, trouble=False)
    elif trouble:
        marvel_die = _select_marvel_die(marvel_rolls, trouble=True)
    else:
        marvel_die = marvel_rolls[0]

    regular_die_1 = roller.randint(1, 6)
    regular_die_2 = roller.randint(1, 6)

    botch = regular_die_1 == 1 and regular_die_2 == 1 and marvel_die == 1
    ultimate = regular_die_1 == 6 and regular_die_2 == 6 and marvel_die == 1
    fantastic = marvel_die == 1
    total = marvel_die + regular_die_1 + regular_die_2
    if fantastic:
        total += 6

    result: dict[str, Any] = {
        "marvel_die": marvel_die,
        "regular_dice": [regular_die_1, regular_die_2],
        "marvel_rolls": marvel_rolls,
        "edge": edge,
        "trouble": trouble,
        "fantastic": fantastic,
        "botch": botch,
        "ultimate": ultimate,
        "total": total,
    }

    if target_number is not None:
        result["target_number"] = target_number
        result["success"] = _resolve_target_success(
            total=total,
            target_number=target_number,
            is_botch=botch,
            is_ultimate=ultimate,
        )

    return result
