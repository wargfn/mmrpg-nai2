"""d616 engine utilities for Marvel Multiverse RPG checks."""

from __future__ import annotations

import random
from typing import Any


class D616ConfigurationError(ValueError):
    """Raised for invalid d616 roll parameters."""


def roll_single_die() -> int:
    """Roll one six-sided die."""
    return random.randint(1, 6)


def resolve_d616_roll(
    ability_modifier: int = 0,
    target_number: int | None = None,
    edges: int = 0,
    troubles: int = 0,
) -> dict[str, Any]:
    """Simulate a d616 check with optional ability modifier, edges, and troubles."""
    s1 = roll_single_die()
    s2 = roll_single_die()
    m_raw = roll_single_die()  # 1 represents the Marvel "6" logo.

    dice_pool = [s1, s2, m_raw]
    net_modifiers = edges - troubles

    # Apply Edges (reroll lowest, keep higher)
    if net_modifiers > 0:
        for _ in range(net_modifiers):
            min_val = min(dice_pool)
            min_index = dice_pool.index(min_val)
            rerolled = roll_single_die()
            if rerolled > dice_pool[min_index]:
                dice_pool[min_index] = rerolled

    # Apply Troubles (reroll highest, keep lower - M counts as highest/best)
    elif net_modifiers < 0:
        for _ in range(abs(net_modifiers)):
            sort_key = lambda x: 7 if x == 1 else x
            max_val = max(dice_pool, key=sort_key)
            max_index = dice_pool.index(max_val)
            rerolled = roll_single_die()
            if sort_key(rerolled) < sort_key(dice_pool[max_index]):
                dice_pool[max_index] = rerolled

    s1, s2, m_raw = dice_pool[0], dice_pool[1], dice_pool[2]

    # A '1' on the Marvel die counts as a 6 mathematically
    m_val = 6 if m_raw == 1 else m_raw

    raw_dice_sum = s1 + s2 + m_val
    total_score = raw_dice_sum + ability_modifier

    is_botch = s1 == 1 and s2 == 1 and m_raw == 1
    is_ultimate = s1 == 6 and s2 == 6 and m_raw == 1
    is_fantastic = m_raw == 1 and not is_botch

    success = True
    if target_number is not None:
        if is_botch:
            success = False
        elif is_ultimate:
            success = True
        else:
            success = total_score >= target_number

    return {
        "raw_dice": {"standard_1": s1, "standard_2": s2, "marvel_die": m_raw},
        "dice_values": [s1, s2, m_val],
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

    roller = rng if rng is not None else random

    initial_marvel_die = roller.randint(1, 6)
    marvel_rolls = [initial_marvel_die]
    if trouble:
        marvel_rolls.append(roller.randint(1, 6))
    elif edge and initial_marvel_die != 1:
        marvel_rolls.append(roller.randint(1, 6))
    if edge:
        marvel_die = max(marvel_rolls, key=_marvel_die_rank)
    elif trouble:
        marvel_die = min(marvel_rolls, key=_marvel_die_rank)
    else:
        marvel_die = marvel_rolls[0]

    regular_die_1 = roller.randint(1, 6)
    regular_die_2 = roller.randint(1, 6)

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
        "total": total,
    }

    if target_number is not None:
        result["target_number"] = target_number
        result["success"] = total >= target_number

    return result
