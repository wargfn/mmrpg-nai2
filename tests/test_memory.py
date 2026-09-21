import sqlite3

import pytest

from marvel_mcp_narrator.core.memory import campaign_db
from marvel_mcp_narrator.mcp_servers import narrator_tools


@pytest.fixture(autouse=True)
def isolated_campaign_db(tmp_path, monkeypatch):
    db_path = tmp_path / "campaign.db"
    monkeypatch.setattr(campaign_db, "CAMPAIGN_DB_PATH", db_path)
    monkeypatch.setattr(campaign_db, "_DEFAULT_DATABASE", None)
    yield db_path


def test_initialize_database_creates_expected_tables(isolated_campaign_db):
    created_path = campaign_db.initialize_database()

    assert created_path == isolated_campaign_db
    assert isolated_campaign_db.exists()

    with sqlite3.connect(isolated_campaign_db) as connection:
        table_names = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
            if not row[0].startswith("sqlite_")
        }

    assert {"memories", "entities"} <= table_names


def test_campaign_database_saves_and_loads_memory():
    database = campaign_db.CampaignDatabase()

    database.save_memory("session-1-summary", "The Avengers secured the artifact.")

    assert database.load_memory("session-1-summary") == "The Avengers secured the artifact."


def test_list_memories_returns_saved_entries_including_timestamps():
    database = campaign_db.CampaignDatabase()
    database.save_memory("session-1", "Opened with a rooftop chase.")
    database.save_memory("session-2", "Doctor Doom escaped.")

    memories = database.list_memories()

    assert [memory["key"] for memory in memories] == ["session-2", "session-1"]
    assert all(memory["updated_at"] for memory in memories)


def test_save_entity_and_get_entity_round_trip():
    database = campaign_db.CampaignDatabase()

    database.save_entity(
        name="Wilson Fisk",
        category="NPC",
        description="Crime boss with political ambitions.",
        disposition="Hostile",
        location="Hell's Kitchen",
        notes="Backs several shell companies.",
    )

    entity = database.get_entity("wilson fisk")

    assert entity is not None
    assert entity["name"] == "Wilson Fisk"
    assert entity["category"] == "NPC"
    assert entity["description"] == "Crime boss with political ambitions."
    assert entity["disposition"] == "Hostile"
    assert entity["location"] == "Hell's Kitchen"
    assert entity["notes"] == "Backs several shell companies."
    assert entity["custom_stats_json"] == {}


def test_search_entities_matches_multiple_fields():
    database = campaign_db.CampaignDatabase()
    database.save_entity(
        name="Latveria",
        category="Location",
        description="Sovereign nation ruled by Doctor Doom.",
        disposition="Dangerous",
        location="Eastern Europe",
        notes="Heavy Doombot presence.",
    )
    database.save_entity(
        name="Fantastic Four",
        category="Faction",
        description="Super hero family based in New York.",
        disposition="Allied",
        location="Baxter Building",
        notes="Often clashes with Doom.",
    )

    matches = database.search_entities("doom")

    assert [match["name"] for match in matches] == ["Fantastic Four", "Latveria"]


def test_legacy_npc_helpers_still_work():
    message = campaign_db.save_npc(
        name="Nick Fury",
        affiliation="S.H.I.E.L.D.",
        description="Master spy.",
        notes="Coordinates global responses.",
    )

    npc = campaign_db.get_npc("Nick Fury")

    assert message == "Saved NPC 'Nick Fury'."
    assert npc["category"] == "NPC"
    assert npc["description"] == "Master spy."
    assert npc["affiliation"] == "S.H.I.E.L.D."


def test_legacy_get_npc_returns_none_for_missing_record():
    assert campaign_db.get_npc("Unknown NPC") is None


def test_search_memory_includes_entities_and_saved_memories():
    campaign_db.save_entity(
        name="Maria Hill",
        category="NPC",
        description="S.H.I.E.L.D. commander.",
        disposition="Allied",
        location="Helicarrier",
        notes="Coordinates the response team.",
    )
    campaign_db.save_memory("session-brief", "Maria Hill warned the team about Hydra.")

    matches = campaign_db.search_memory("Maria")

    assert [match["memory_type"] for match in matches] == ["entity", "memory"]
    assert matches[0]["name"] == "Maria Hill"
    assert "Hydra" in matches[1]["summary"]


def test_narrator_tools_expose_campaign_memory_and_entity_flow():
    save_message = narrator_tools.save_campaign_memory("session-3", "The team infiltrated Oscorp.")
    load_message = narrator_tools.load_campaign_memory("session-3")
    entity_message = narrator_tools.remember_entity(
        name="Oscorp Tower",
        category="Location",
        description="Corporate tower full of experimental tech.",
        disposition="Dangerous",
        location="New York",
        notes="Guard patrols every floor.",
    )
    recalled = narrator_tools.recall_entity("Oscorp Tower")

    assert save_message == "Saved campaign memory 'session-3'."
    assert load_message == "The team infiltrated Oscorp."
    assert entity_message == "Saved Location 'Oscorp Tower'."
    assert "Category: Location" in recalled
    assert "Location: New York" in recalled


def test_recall_entity_returns_search_results_and_missing_message():
    narrator_tools.remember_entity(
        name="Hydra",
        category="Faction",
        description="Secretive global terrorist network.",
        disposition="Hostile",
        location="Worldwide",
        notes="Cells embedded across governments.",
    )

    search_result = narrator_tools.recall_entity("terrorist")
    missing = narrator_tools.recall_entity("Xandar")

    assert "Entity matches for 'terrorist':" in search_result
    assert "[Faction] Hydra (Worldwide): Secretive global terrorist network." in search_result
    assert missing == "No entity found for 'Xandar'."


def test_load_campaign_memory_returns_not_found_message_for_missing_key():
    assert narrator_tools.load_campaign_memory("missing-key") == "No campaign memory found for 'missing-key'."
