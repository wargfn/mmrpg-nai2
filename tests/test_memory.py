import sqlite3
from concurrent.futures import ThreadPoolExecutor

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

    assert {"memories", "entities", "plot_logs"} <= table_names


def test_campaign_database_saves_and_loads_memory():
    database = campaign_db.CampaignDatabase()

    database.save_memory("session-1-summary", "The Avengers secured the artifact.")

    assert database.load_memory("session-1-summary") == "The Avengers secured the artifact."


def test_get_campaign_database_singleton_supports_concurrent_writes():
    def worker(index: int) -> tuple[int, str | None]:
        database = campaign_db.get_campaign_database()
        database.save_memory(f"session-{index}", f"Event {index}")
        return id(database), database.load_memory(f"session-{index}")

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(worker, range(6)))

    assert len({database_id for database_id, _ in results}) == 1
    assert [content for _, content in results] == [f"Event {index}" for index in range(6)]


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


def test_search_entities_keeps_exact_match_and_fuzzy_matches():
    database = campaign_db.CampaignDatabase()
    database.save_entity(
        name="Hydra",
        category="Faction",
        description="Secret world-spanning organization.",
        disposition="Hostile",
        location="Global",
        notes="Exact name match.",
    )
    database.save_entity(
        name="Baron Strucker",
        category="NPC",
        description="Hydra commander.",
        disposition="Hostile",
        location="Unknown",
        notes="Fuzzy description match.",
    )

    matches = database.search_entities("Hydra")

    assert [match["name"] for match in matches] == ["Hydra", "Baron Strucker"]


def test_legacy_npc_helpers_still_work():
    message = campaign_db.save_npc(
        name="Nick Fury",
        affiliation="S.H.I.E.L.D.",
        description="Master spy.",
        notes="Coordinates global responses.",
        archetype_or_role="Director",
        disposition="Allied",
        location="Helicarrier",
        custom_stats_json={"clearance": "Omega"},
    )

    npc = campaign_db.get_npc("Nick Fury")

    assert message == "Saved NPC 'Nick Fury'."
    assert npc["category"] == "NPC"
    assert npc["description"] == "Master spy."
    assert npc["affiliation"] == "S.H.I.E.L.D."
    assert npc["archetype_or_role"] == "Director"
    assert npc["disposition"] == "Allied"
    assert npc["location"] == "Helicarrier"
    assert npc["custom_stats_json"]["clearance"] == "Omega"


def test_legacy_get_npc_returns_none_for_missing_record():
    assert campaign_db.get_npc("Unknown NPC") is None


def test_save_entity_rejects_non_mapping_custom_stats():
    with pytest.raises(ValueError, match="must be a dictionary"):
        campaign_db.save_entity(
            name="Hydra Base",
            category="Location",
            description="A hidden bunker.",
            custom_stats_json=["not", "a", "dict"],
        )


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

    assert {match["memory_type"] for match in matches} == {"entity", "memory"}
    assert any(match["name"] == "Maria Hill" for match in matches)
    assert any("Hydra" in match["summary"] for match in matches if match["memory_type"] == "memory")


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


def test_log_campaign_event_is_searchable_via_legacy_memory_flow():
    message = narrator_tools.log_campaign_event("Hydra launched an attack on the Helicarrier.", session=7)
    matches = campaign_db.search_memory("Helicarrier")
    recalled = narrator_tools.recall_npc_or_location("Helicarrier")

    assert message == "Logged campaign event for session 7."
    assert any(match["memory_type"] == "plot_log" for match in matches)
    assert "[plot_log] Session 7 @" in recalled


def test_log_event_rejects_invalid_session_number():
    with pytest.raises(ValueError, match="Session number must be at least 1"):
        campaign_db.log_event("This should fail.", session=0)


def test_search_memory_combines_memories_and_plot_logs_with_shared_limit():
    for index in range(10):
        campaign_db.save_memory(f"summary-{index}", f"Hydra report {index}")
    campaign_db.log_event("Hydra launched a final assault.", session=9)

    matches = campaign_db.search_memory("Hydra")

    assert len(matches) == campaign_db.SEARCH_RESULT_LIMIT
    assert matches[0]["memory_type"] == "plot_log"
    assert any(match["memory_type"] == "memory" for match in matches)


def test_search_memory_prioritizes_legacy_matches_over_fuzzy_entity_overflow():
    for index in range(10):
        campaign_db.save_entity(
            name=f"Hydra Agent {index}",
            category="NPC",
            description="Field operative.",
            disposition="Hostile",
            location="Unknown",
            notes="Hydra cell member.",
        )
    campaign_db.log_event("Hydra command issued a retreat order.", session=5)

    matches = campaign_db.search_memory("Hydra")

    assert len(matches) == campaign_db.SEARCH_RESULT_LIMIT
    assert any(match["memory_type"] == "plot_log" for match in matches)


def test_extract_significant_events_matches_whole_words_only():
    events = campaign_db.CampaignDatabase._extract_significant_events(
        "The team reviewed an unsaved draft. They rescued civilians from the train."
    )

    assert events == ["They rescued civilians from the train"]


def test_search_memory_prioritizes_exact_entity_name_over_legacy_matches():
    campaign_db.save_entity(
        name="Hydra",
        category="Faction",
        description="A global terror network.",
        disposition="Hostile",
        location="Worldwide",
        notes="Exact entity name match.",
    )
    campaign_db.log_event("Hydra resurfaced in Madripoor.", session=3)

    matches = campaign_db.search_memory("Hydra")

    assert matches[0]["memory_type"] == "entity"
    assert any(match["memory_type"] == "entity" for match in matches)
