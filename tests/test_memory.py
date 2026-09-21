import sqlite3

import pytest

from marvel_mcp_narrator.core.memory import campaign_db


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
