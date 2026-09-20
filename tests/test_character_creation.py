import pytest
from pathlib import Path

from marvel_mcp_narrator.core import character_creation
from marvel_mcp_narrator.core.character_creation import (
    ARCHETYPE_TEMPLATES,
    export_character_json,
    generate_character_from_template,
    load_character_json,
    validate_character_powers,
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


def test_generate_character_from_template_validates_origin_and_traits():
    character = generate_character_from_template(
        name="Ororo",
        archetype="Polymath",
        rank=3,
        origin="mutation",
        occupation="scientist",
        traits=["iron will"],
    )
    assert character.origin == "Mutation"
    assert character.occupation == "Scientist"
    assert character.traits == ["Iron Will"]


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


def test_validate_character_build_normalizes_trait_casing():
    result = validate_character_build(
        name="Cyclops",
        archetype="Blaster",
        rank=2,
        abilities=ARCHETYPE_TEMPLATES["Blaster"]["ranks"][2],
        powers=["Blast"],
        traits=["iron will"],
    )
    assert result["valid"] is True
    assert result["traits"] == ["Iron Will"]


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


def test_validate_character_build_accepts_default_sentinels_case_insensitively():
    result = validate_character_build(
        name="Baseline Hero",
        archetype="Polymath",
        rank=1,
        abilities=ARCHETYPE_TEMPLATES["Polymath"]["ranks"][1],
        powers=[],
        origin="unknown",
        occupation="none",
    )
    assert result["valid"] is True


def test_validate_character_build_uses_input_rank_for_unknown_power():
    result = validate_character_build(
        name="Mystery Hero",
        archetype="Polymath",
        rank=1,
        abilities=ARCHETYPE_TEMPLATES["Polymath"]["ranks"][1],
        powers=[{"name": "UnknownPower", "rank_required": 2}],
    )
    assert result["valid"] is False
    assert any("UnknownPower" in message for message in result["errors"])


def test_validate_character_powers_rejects_above_rank():
    result = validate_character_powers(rank=1, powers_list=["Regeneration"])
    assert result["valid"] is False
    assert any("requires rank" in message for message in result["errors"])


def test_validate_character_powers_rejects_unsupported_power_name():
    result = validate_character_powers(rank=3, powers_list=["MadeUpPower"])
    assert result["valid"] is False
    assert any("Unsupported power" in message for message in result["errors"])


def test_validate_character_build_validates_power_sets_when_powers_empty():
    result = validate_character_build(
        name="Nova",
        archetype="Polymath",
        rank=1,
        abilities=ARCHETYPE_TEMPLATES["Polymath"]["ranks"][1],
        powers=[],
        power_sets=["Regeneration"],
    )
    assert result["valid"] is False
    assert any("requires rank" in message for message in result["errors"])


def test_create_character_assisted_adds_character_to_roster():
    payload = narrator_tools.create_character_assisted(
        name="Logan",
        archetype="Brawler",
        rank=3,
        origin="Mutation",
        occupation="Military",
        traits=["Brawler", "Iron Will"],
        tags=["X-Men", "Canadian"],
        power_sets=["Regeneration", "Blast"],
    )
    assert payload["created"] is True
    assert payload["character"]["name"] == "Logan"
    assert payload["character"]["defenses"]["resilience_defense"] == payload["character"]["resilience"] + 10
    assert payload["character"]["origin"] == "Mutation"
    assert payload["character"]["occupation"] == "Military"
    assert payload["character"]["traits"] == ["Brawler", "Iron Will"]
    assert payload["character"]["tags"] == ["X-Men", "Canadian"]
    assert payload["character"]["power_sets"] == ["Regeneration", "Blast"]
    sheet = narrator_tools.get_character("Logan")
    assert sheet["rank"] == 3
    assert sheet["origin"] == "Mutation"
    assert sheet["occupation"] == "Military"
    assert sheet["traits"] == ["Brawler", "Iron Will"]
    assert sheet["tags"] == ["X-Men", "Canadian"]
    assert sheet["power_sets"] == ["Regeneration", "Blast"]


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


def test_character_json_export_and_import_roundtrip(tmp_path: Path):
    character = generate_character_from_template(
        name="Jean",
        archetype="Blaster",
        rank=3,
        origin="Mutation",
        occupation="Scientist",
        traits=["Iron Will"],
        tags=["X-Men"],
        power_sets=["Blast", {"name": "Regeneration", "rank_required": 3}],
    )
    output = tmp_path / "jean.json"
    export_character_json(character, str(output))
    loaded = load_character_json(str(output))
    assert loaded.name == "Jean"
    assert loaded.origin == "Mutation"
    assert loaded.occupation == "Scientist"
    assert loaded.traits == ["Iron Will"]
    assert loaded.tags == ["X-Men"]
    assert loaded.power_sets == ["Blast", {"name": "Regeneration", "rank_required": 3}]


def test_export_character_json_creates_parent_directories(tmp_path: Path):
    character = generate_character_from_template(name="Jean", archetype="Blaster", rank=3)
    output = tmp_path / "nested" / "dir" / "jean.json"
    export_character_json(character, str(output))
    assert output.is_file()


def test_load_character_json_rejects_unknown_fields(tmp_path: Path):
    output = tmp_path / "bad.json"
    output.write_text('{"name":"Jean","archetype":"Blaster","rank":3,"melee":1,"agility":1,"resilience":1,"vigilance":1,"ego":1,"logic":1,"unknown_field":"x"}', encoding="utf-8")
    with pytest.raises(ValueError, match="Unsupported fields"):
        load_character_json(str(output))


def test_load_character_json_rejects_non_object_payload(tmp_path: Path):
    output = tmp_path / "bad-array.json"
    output.write_text('["not","an","object"]', encoding="utf-8")
    with pytest.raises(ValueError, match="JSON object"):
        load_character_json(str(output))


def test_validate_character_powers_tool_uses_character_rank():
    narrator_tools.create_character_assisted(
        name="Logan",
        archetype="Brawler",
        rank=2,
        origin="Mutation",
        occupation="Military",
        traits=["Brawler"],
    )
    result = narrator_tools.validate_character_powers("Logan", ["Regeneration"])
    assert result["valid"] is False
    assert any("requires rank" in message for message in result["errors"])


def test_export_character_tool_writes_json_file():
    narrator_tools.create_character_assisted(
        name="Peter Parker",
        archetype="Polymath",
        rank=3,
        origin="Mutation",
        occupation="Scientist",
        traits=["Connections"],
        tags=["Spider-Man"],
        power_sets=["Blast"],
    )
    payload = narrator_tools.export_character("Peter Parker")
    assert Path(payload["filepath"]).is_file()
    assert payload["character"]["name"] == "Peter Parker"


def test_create_character_assisted_rejects_power_sets_above_rank():
    with pytest.raises(ValueError, match="requires rank"):
        narrator_tools.create_character_assisted(
            name="Low Rank Hero",
            archetype="Polymath",
            rank=1,
            origin="Mutation",
            occupation="Scientist",
            traits=["Connections"],
            power_sets=["Regeneration"],
        )
