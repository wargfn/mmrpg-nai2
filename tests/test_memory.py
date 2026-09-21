import sqlite3

import pytest

from marvel_mcp_narrator.core.memory import campaign_db
from marvel_mcp_narrator.mcp_servers import narrator_tools


@pytest.fixture(autouse=True)
def isolated_campaign_db(tmp_path, monkeypatch):
    db_path = tmp_path / "campaign_memory.db"
    monkeypatch.setattr(campaign_db, "CAMPAIGN_DB_PATH", db_path)
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

    assert {"npcs", "locations", "plot_logs"} <= table_names


def test_initialize_database_migrates_existing_schema(isolated_campaign_db):
    with sqlite3.connect(isolated_campaign_db) as connection:
        connection.execute(
            """
            CREATE TABLE npcs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE
            )
            """
        )
        connection.commit()

    campaign_db.initialize_database()

    with sqlite3.connect(isolated_campaign_db) as connection:
        npc_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(npcs)")
        }
        table_names = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
            if not row[0].startswith("sqlite_")
        }

    assert {"archetype_or_role", "affiliation", "disposition", "location", "notes", "custom_stats_json"} <= npc_columns
    assert {"locations", "plot_logs"} <= table_names


def test_save_npc_and_get_npc_round_trip():
    message = campaign_db.save_npc(
        name="Nick Fury",
        affiliation="S.H.I.E.L.D.",
        description="Spy master",
        notes="Keeps tabs on emerging threats.",
    )

    npc = campaign_db.get_npc("nick fury")

    assert message == "Saved NPC 'Nick Fury'."
    assert npc["name"] == "Nick Fury"
    assert npc["affiliation"] == "S.H.I.E.L.D."
    assert npc["archetype_or_role"] == "Spy master"
    assert npc["notes"] == "Keeps tabs on emerging threats."
    assert npc["custom_stats_json"] == {}


def test_save_npc_preserves_existing_location_and_disposition(isolated_campaign_db):
    campaign_db.initialize_database()
    with sqlite3.connect(isolated_campaign_db) as connection:
        connection.execute(
            """
            INSERT INTO npcs (
                name,
                archetype_or_role,
                affiliation,
                disposition,
                location,
                notes,
                custom_stats_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "Black Cat",
                "Thief",
                "Independent",
                "Wary",
                "Midtown",
                "Old notes.",
                '{"speed": 4}',
            ),
        )
        connection.commit()

    campaign_db.save_npc(
        name="Black Cat",
        affiliation="Allies",
        description="Cat burglar",
        notes="Sometimes helps Spider-Man.",
    )

    npc = campaign_db.get_npc("Black Cat")

    assert npc["disposition"] == "Wary"
    assert npc["location"] == "Midtown"
    assert npc["custom_stats_json"] == {"speed": 4}


def test_save_npc_updates_existing_entry_case_insensitively():
    campaign_db.save_npc(
        name="Nick Fury",
        affiliation="S.H.I.E.L.D.",
        description="Director",
        notes="Original record.",
    )

    campaign_db.save_npc(
        name="nick fury",
        affiliation="Avengers",
        description="Spymaster",
        notes="Updated record.",
    )

    npc = campaign_db.get_npc("Nick Fury")
    matches = campaign_db.search_memory("nick fury")

    assert npc["name"] == "nick fury"
    assert npc["affiliation"] == "Avengers"
    assert npc["archetype_or_role"] == "Spymaster"
    assert len([match for match in matches if match["memory_type"] == "npc"]) == 1


def test_save_npc_preserves_existing_values_on_blank_update():
    campaign_db.save_npc(
        name="Jessica Jones",
        affiliation="Alias Investigations",
        description="Private investigator",
        notes="Keeps her distance.",
    )

    campaign_db.save_npc(
        name="Jessica Jones",
        affiliation="",
        description="",
        notes="Updated notes.",
    )

    npc = campaign_db.get_npc("Jessica Jones")

    assert npc["affiliation"] == "Alias Investigations"
    assert npc["archetype_or_role"] == "Private investigator"
    assert npc["notes"] == "Updated notes."


def test_log_event_persists_plot_entry(isolated_campaign_db):
    message = campaign_db.log_event("Hydra stole the artifact.", session=3)

    assert message == "Logged campaign event for session 3."

    with sqlite3.connect(isolated_campaign_db) as connection:
        row = connection.execute(
            "SELECT session_number, event_summary, timestamp FROM plot_logs"
        ).fetchone()

    assert row[0] == 3
    assert row[1] == "Hydra stole the artifact."
    assert row[2]


def test_search_memory_returns_saved_npc_and_plot_log():
    campaign_db.save_npc(
        name="Maria Hill",
        affiliation="S.H.I.E.L.D.",
        description="Field commander",
        notes="Coordinates rapid response teams.",
    )
    campaign_db.log_event("Maria Hill briefed the heroes on the Skrull incursion.", session=2)

    matches = campaign_db.search_memory("Maria")

    assert [match["memory_type"] for match in matches] == ["npc", "plot_log"]
    assert matches[0]["name"] == "Maria Hill"
    assert "briefed the heroes" in matches[1]["summary"]


def test_narrator_tools_expose_campaign_memory_flow():
    remembered = narrator_tools.remember_npc(
        name="Wilson Fisk",
        affiliation="Criminal Underworld",
        description="Crime boss",
        notes="Controls several fronts across Hell's Kitchen.",
    )
    recalled = narrator_tools.recall_npc_or_location("Wilson Fisk")
    logged = narrator_tools.log_campaign_event(
        "Wilson Fisk put a bounty on the vigilantes.",
        session=4,
    )

    assert remembered["npc"]["name"] == "Wilson Fisk"
    assert "Crime boss" in recalled
    assert logged == "Logged campaign event for session 4."


def test_recall_npc_or_location_formats_search_results_and_missing_message():
    narrator_tools.log_campaign_event("The heroes regrouped in Avengers Tower.", session=2)

    recalled = narrator_tools.recall_npc_or_location("Avengers Tower")
    missing = narrator_tools.recall_npc_or_location("Latveria")

    assert "Campaign memory matches for 'Avengers Tower':" in recalled
    assert "[plot_log] Session 2" in recalled
    assert missing == "No campaign memory found for 'Latveria'."


def test_log_campaign_event_rejects_invalid_session():
    with pytest.raises(ValueError, match="Session number must be at least 1"):
        narrator_tools.log_campaign_event("This should fail.", session=0)
