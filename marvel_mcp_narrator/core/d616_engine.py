"""d616 engine utilities for Marvel Multiverse RPG checks."""

from __future__ import annotations

import random
from typing import Any


class D616ConfigurationError(ValueError):
    """Raised for invalid d616 roll parameters."""


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
