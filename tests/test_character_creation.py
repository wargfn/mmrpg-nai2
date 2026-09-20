import pytest

from marvel_mcp_narrator.core import character_creation
from marvel_mcp_narrator.core.character_creation import (
    ARCHETYPE_TEMPLATES,
    generate_character_from_template,
    validate_character_build,
)
from marvel_mcp_narrator.core.character_state import Character, character_roster
from marvel_mcp_narrator.mcp_servers import narrator_tools


@pytest.fixture(autouse=True)
def clear_roster():
    character_roster.clear()
    yield
    character_roster.clear()


def test_generate_character_from_template_returns_character():
    character = generate_character_from_template(name="Spidey", archetype="Polymath", rank=3)
    assert isinstance(character, Character)
    expected = ARCHETYPE_TEMPLATES["Polymath"]["ranks"][3]
    assert character.melee == expected["melee"]
    assert character.logic == expected["logic"]


def test_generate_character_from_template_rejects_blank_name():
    with pytest.raises(ValueError, match="Character name is required"):
        generate_character_from_template(name="   ", archetype="Polymath", rank=3)


def test_generate_character_from_template_rejects_none_name():
    with pytest.raises(ValueError, match="Character name is required"):
        generate_character_from_template(name=None, archetype="Polymath", rank=3)  # type: ignore[arg-type]


def test_validate_character_build_rejects_power_below_required_rank():
    result = validate_character_build(
        name="Nightcrawler",
        archetype="Way-Watcher",
        rank=1,
        abilities=ARCHETYPE_TEMPLATES["Way-Watcher"]["ranks"][1],
        powers=["Teleportation"],
    )
    assert result["valid"] is False
    assert any("requires rank" in message for message in result["errors"])


def test_validate_character_build_handles_invalid_rank_required_in_input_power_dict():
    result = validate_character_build(
        name="Nightcrawler",
        archetype="Way-Watcher",
        rank=1,
        abilities=ARCHETYPE_TEMPLATES["Way-Watcher"]["ranks"][1],
        powers=[{"name": "Teleportation", "rank_required": None}],
    )
    assert result["valid"] is False
    assert any("requires rank" in message for message in result["errors"])


def test_validate_character_build_prefers_input_rank_required_when_provided():
    result = validate_character_build(
        name="Cyclops",
        archetype="Blaster",
        rank=1,
        abilities=ARCHETYPE_TEMPLATES["Blaster"]["ranks"][1],
        powers=[{"name": "Blast", "rank_required": 2}],
    )
    assert result["valid"] is False
    assert any("Blast" in message for message in result["errors"])


def test_validate_character_build_reports_invalid_rules_rank_requirement(monkeypatch):
    monkeypatch.setattr(character_creation, "_POWER_REQUIREMENTS_CACHE", {"teleportation": None})
    result = validate_character_build(
        name="Nightcrawler",
        archetype="Way-Watcher",
        rank=3,
        abilities=ARCHETYPE_TEMPLATES["Way-Watcher"]["ranks"][3],
        powers=["Teleportation"],
    )
    assert result["valid"] is False
    assert any("invalid rank requirement" in message for message in result["errors"])


def test_validate_character_build_accepts_balanced_template_and_valid_powers():
    result = validate_character_build(
        name="Cyclops",
        archetype="Blaster",
        rank=2,
        abilities=ARCHETYPE_TEMPLATES["Blaster"]["ranks"][2],
        powers=["Blast"],
        origin="Mutation",
        occupation="Athlete",
        traits=["Iron Will"],
        tags=["X-Men"],
    )
    assert result["valid"] is True
    assert result["errors"] == []
    assert result["origin"] == "Mutation"
    assert result["occupation"] == "Athlete"
    assert result["traits"] == ["Iron Will"]
    assert result["tags"] == ["X-Men"]


def test_validate_character_build_rejects_none_name():
    result = validate_character_build(
        name=None,  # type: ignore[arg-type]
        archetype="Blaster",
        rank=2,
        abilities=ARCHETYPE_TEMPLATES["Blaster"]["ranks"][2],
        powers=["Blast"],
    )
    assert result["valid"] is False
    assert any("Character name is required" in message for message in result["errors"])


def test_validate_character_build_rejects_unknown_trait():
    result = validate_character_build(
        name="Rogue",
        archetype="Brawler",
        rank=2,
        abilities=ARCHETYPE_TEMPLATES["Brawler"]["ranks"][2],
        powers=["Blast"],
        traits=["NotARealTrait"],
    )
    assert result["valid"] is False
    assert any("Unsupported trait" in message for message in result["errors"])


def test_create_character_assisted_adds_character_to_roster():
    payload = narrator_tools.create_character_assisted(
        name="Logan",
        archetype="Brawler",
        rank=3,
        origin="Mutation",
        occupation="Military",
        traits=["Brawler", "Iron Will"],
        tags=["X-Men", "Canadian"],
    )
    assert payload["created"] is True
    assert payload["character"]["name"] == "Logan"
    assert payload["character"]["defenses"]["resilience_defense"] == payload["character"]["resilience"] + 10
    assert payload["character"]["origin"] == "Mutation"
    assert payload["character"]["occupation"] == "Military"
    assert payload["character"]["traits"] == ["Brawler", "Iron Will"]
    assert payload["character"]["tags"] == ["X-Men", "Canadian"]
    sheet = narrator_tools.get_character("Logan")
    assert sheet["rank"] == 3
    assert sheet["origin"] == "Mutation"
    assert sheet["occupation"] == "Military"
    assert sheet["traits"] == ["Brawler", "Iron Will"]
    assert sheet["tags"] == ["X-Men", "Canadian"]


def test_create_character_assisted_rejects_invalid_custom_abilities():
    with pytest.raises(ValueError, match="Ability total"):
        narrator_tools.create_character_assisted(
            name="Bad Build",
            archetype="Striker",
            rank=2,
            custom_abilities={"melee": 50},
        )


def test_create_character_assisted_rejects_out_of_guideline_warnings():
    with pytest.raises(ValueError, match="differs from Striker rank-2 template"):
        narrator_tools.create_character_assisted(
            name="Swingy Build",
            archetype="Striker",
            rank=2,
            custom_abilities={
                "melee": 10,
                "agility": 4,
                "resilience": 3,
                "vigilance": 3,
                "ego": 2,
                "logic": 2,
            },
        )


def test_list_available_archetypes_returns_supported_entries():
    archetypes = narrator_tools.list_available_archetypes()
    names = {entry["name"] for entry in archetypes}
    assert "Striker" in names
    assert "Polymath" in names


def test_list_available_origins_and_occupations():
    origins = narrator_tools.list_available_origins()
    occupations = narrator_tools.list_available_occupations()
    assert "Mutant" in origins
    assert "Scientist" in occupations
