import inspect

import pytest

from marvel_mcp_narrator.core.character_state import Character, character_roster
from marvel_mcp_narrator.mcp_servers import narrator_tools


@pytest.fixture(autouse=True)
def clear_roster():
    character_roster.clear()
    yield
    character_roster.clear()


def test_defenses_auto_calculate_from_abilities():
    character = Character(
        name="Spider-Man",
        archetype="Striker",
        rank=3,
        melee=4,
        agility=6,
        resilience=3,
        vigilance=5,
        ego=2,
        logic=3,
    )
    assert character.melee_defense == 14
    assert character.agility_defense == 16
    assert character.resilience_defense == 13
    assert character.vigilance_defense == 15
    assert character.ego_defense == 12
    assert character.logic_defense == 13


def test_health_and_focus_pools_initialize_from_resilience_and_vigilance():
    character = Character(
        name="Wolverine",
        archetype="Striker",
        rank=4,
        melee=5,
        agility=3,
        resilience=4,
        vigilance=2,
        ego=2,
        logic=2,
    )
    assert character.max_health == 120
    assert character.current_health == 120
    assert character.max_focus == 60
    assert character.current_focus == 60


def test_take_damage_threshold_states():
    character = Character(
        name="Jean Grey",
        archetype="Blaster",
        rank=5,
        melee=2,
        agility=3,
        resilience=1,
        vigilance=1,
        ego=6,
        logic=5,
    )
    health_result = character.take_health_damage(31)
    focus_result = character.take_focus_damage(30)

    assert health_result["is_unconscious"] is True
    assert health_result["current"] == 0
    assert focus_result["is_shattered"] is True
    assert focus_result["current"] == 0


def test_attack_damage_formula_and_fantastic_double():
    character = Character(
        name="Captain Marvel",
        archetype="Blaster",
        rank=4,
        melee=3,
        agility=3,
        resilience=4,
        vigilance=4,
        ego=5,
        logic=3,
    )
    normal = character.calculate_attack_damage(ability="ego", marvel_die=6)
    fantastic = character.calculate_attack_damage(ability="ego", marvel_die=6, is_fantastic=True)

    assert normal["damage_multiplier"] == 4
    assert normal["base_damage"] == 29
    assert normal["total_damage"] == 29
    assert fantastic["total_damage"] == 58


def test_attack_damage_rejects_negative_bonus_multiplier():
    character = Character(
        name="Captain Marvel",
        archetype="Blaster",
        rank=4,
        melee=3,
        agility=3,
        resilience=4,
        vigilance=4,
        ego=5,
        logic=3,
    )
    with pytest.raises(ValueError, match="Bonus multiplier must be non-negative"):
        character.calculate_attack_damage(ability="ego", marvel_die=6, bonus_multiplier=-1)


def test_tools_character_management_and_damage_response():
    create_payload = narrator_tools.create_or_load_character(
        name="Storm",
        rank=4,
        archetype="Polymath",
        melee=2,
        agility=4,
        resilience=3,
        vigilance=5,
        ego=5,
        logic=3,
    )
    assert create_payload["created"] is True
    assert create_payload["character"]["defenses"]["vigilance_defense"] == 15

    sheet = narrator_tools.get_character_sheet("Storm")
    assert sheet["max_health"] == 90
    assert sheet["max_focus"] == 150

    damage_result = narrator_tools.apply_damage("Storm", health_damage=10, focus_damage=25)
    assert damage_result["health"]["previous"] == 90
    assert damage_result["health"]["damage"] == 10
    assert damage_result["health"]["current"] == 80
    assert damage_result["focus"]["previous"] == 150
    assert damage_result["focus"]["damage"] == 25
    assert damage_result["focus"]["current"] == 125

    attack_result = narrator_tools.calculate_attack_damage(
        attacker_name="Storm",
        ability="vigilance",
        marvel_die=5,
        is_fantastic=True,
    )
    assert attack_result["damage_multiplier"] == 4
    assert attack_result["base_damage"] == 25
    assert attack_result["total_damage"] == 50


def test_create_or_load_character_rejects_conflicting_definition():
    narrator_tools.create_or_load_character(
        name="Storm",
        rank=4,
        archetype="Polymath",
        melee=2,
        agility=4,
        resilience=3,
        vigilance=5,
        ego=5,
        logic=3,
    )

    with pytest.raises(ValueError, match="conflicting attributes"):
        narrator_tools.create_or_load_character(
            name="Storm",
            rank=5,
            archetype="Polymath",
            melee=2,
            agility=4,
            resilience=3,
            vigilance=5,
            ego=5,
            logic=3,
        )


def test_create_or_load_character_accepts_case_only_name_variation():
    narrator_tools.create_or_load_character(
        name="Storm",
        rank=4,
        archetype="Polymath",
        melee=2,
        agility=4,
        resilience=3,
        vigilance=5,
        ego=5,
        logic=3,
    )
    payload = narrator_tools.create_or_load_character(
        name="storm",
        rank=4,
        archetype="Polymath",
        melee=2,
        agility=4,
        resilience=3,
        vigilance=5,
        ego=5,
        logic=3,
    )
    assert payload["created"] is False


def test_roster_get_returns_copy_not_live_state():
    narrator_tools.create_or_load_character(
        name="Storm",
        rank=4,
        archetype="Polymath",
        melee=2,
        agility=4,
        resilience=3,
        vigilance=5,
        ego=5,
        logic=3,
    )

    detached = character_roster.get_copy("Storm")
    detached.current_health = 1

    sheet = narrator_tools.get_character_sheet("Storm")
    assert sheet["current_health"] == 90


def test_tool_error_paths():
    with pytest.raises(KeyError, match="was not found"):
        narrator_tools.get_character_sheet("Unknown")

    narrator_tools.create_or_load_character(
        name="Storm",
        rank=4,
        archetype="Polymath",
        melee=2,
        agility=4,
        resilience=3,
        vigilance=5,
        ego=5,
        logic=3,
    )

    with pytest.raises(ValueError, match="Unknown ability"):
        narrator_tools.calculate_attack_damage(attacker_name="Storm", ability="strength", marvel_die=5)

    with pytest.raises(ValueError, match="Damage values must be non-negative"):
        narrator_tools.apply_damage("Storm", health_damage=-1)


def test_tool_signatures():
    create_signature = inspect.signature(narrator_tools.create_or_load_character)
    apply_signature = inspect.signature(narrator_tools.apply_damage)
    calculate_signature = inspect.signature(narrator_tools.calculate_attack_damage)

    assert list(create_signature.parameters) == [
        "name",
        "rank",
        "archetype",
        "melee",
        "agility",
        "resilience",
        "vigilance",
        "ego",
        "logic",
    ]
    assert apply_signature.parameters["health_damage"].default == 0
    assert apply_signature.parameters["focus_damage"].default == 0
    assert calculate_signature.parameters["is_fantastic"].default is False
    assert calculate_signature.parameters["bonus_multiplier"].default == 0
