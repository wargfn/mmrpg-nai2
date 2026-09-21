import pytest

from marvel_mcp_narrator.core import campaign_planner
from marvel_mcp_narrator.core.memory import campaign_db
from marvel_mcp_narrator.mcp_servers import narrator_tools


@pytest.fixture(autouse=True)
def isolated_campaign_db(tmp_path, monkeypatch):
    db_path = tmp_path / "campaign.db"
    monkeypatch.setattr(campaign_db, "CAMPAIGN_DB_PATH", db_path)
    monkeypatch.setattr(campaign_db, "_DEFAULT_DATABASE", None)
    yield db_path


def test_create_campaign_plan_generates_structured_sessions():
    planner = campaign_planner.CampaignPlanner()

    plan = planner.create_campaign_plan(
        theme="Cosmic Rift",
        villain="Doctor Doom",
        hero_team=["Captain Marvel", "Spider-Man"],
        desired_session_count=3,
    )

    assert plan["theme"] == "Cosmic Rift"
    assert plan["villain"] == "Doctor Doom"
    assert plan["session_count"] == 3
    assert len(plan["sessions"]) == 3
    assert plan["sessions"][0]["session_number"] == 1
    assert plan["sessions"][0]["objectives"]
    assert plan["sessions"][2]["title"] == "Final Showdown with Doctor Doom"


def test_get_current_session_context_tracks_active_pointer():
    planner = campaign_planner.CampaignPlanner()
    planner.create_campaign_plan(
        theme="Street War",
        villain="Kingpin",
        hero_team=["Daredevil", "Spider-Man"],
        desired_session_count=2,
    )

    context = planner.get_current_session_context()

    assert context["active_session_number"] == 1
    assert context["session"]["title"] == "Street War Sparks Fly"


def test_conclude_session_generates_recap_highlights_and_logs_events():
    planner = campaign_planner.CampaignPlanner()
    planner.create_campaign_plan(
        theme="Hydra Uprising",
        villain="Red Skull",
        hero_team=["Captain America", "Black Widow"],
        desired_session_count=2,
    )

    result = planner.conclude_session(
        1,
        (
            "Captain America rescued civilians from the collapsing bridge. "
            "Black Widow uncovered Hydra's signal tower. "
            "The heroes defeated a Hydra strike team and discovered Red Skull's escape route."
        ),
    )

    current = planner.get_current_session_context()
    memories = campaign_db.list_memories()

    assert "Captain America rescued civilians" in result["player_recap"]
    assert "session 2" in result["narrator_bridge_prompt"].lower()
    assert "Captain America" in result["hero_highlights"]
    assert result["significant_events"]
    assert current["active_session_number"] == 2
    assert any("Hydra strike team" in memory["content"] for memory in memories)


def test_conclude_session_rejects_out_of_order_progression():
    planner = campaign_planner.CampaignPlanner()
    planner.create_campaign_plan(
        theme="Temporal Fracture",
        villain="Kang",
        hero_team=["Wasp", "Iron Man"],
        desired_session_count=2,
    )

    with pytest.raises(ValueError, match="session 1 is active"):
        planner.conclude_session(2, "The heroes leaped ahead in the timeline.")


def test_wrap_up_current_session_tool_advances_campaign():
    narrator_tools.create_campaign_plan("Mystic Crisis", "Loki", 2)

    wrap_up = narrator_tools.wrap_up_current_session(
        "Marvel heroes saved the Sanctum. Loki escaped, but the team discovered his portal nexus."
    )
    briefing = narrator_tools.get_next_session_briefing()

    assert "Bridge Prompt:" in wrap_up
    assert "Hero Highlights:" in wrap_up
    assert "Session 2:" in briefing


def test_create_campaign_plan_tool_returns_summary():
    summary = narrator_tools.create_campaign_plan("Gamma Panic", "Leader", 2)

    assert "Created 2-session campaign against Leader" in summary


def test_create_campaign_plan_defaults_blank_hero_team_entries():
    planner = campaign_planner.CampaignPlanner()

    plan = planner.create_campaign_plan(
        theme="Shadow Scheme",
        villain="Mister Negative",
        hero_team=["   "],
        desired_session_count=1,
    )

    assert plan["hero_team"] == ["Marvel heroes"]


def test_get_next_session_briefing_requires_active_campaign():
    with pytest.raises(ValueError, match="No active campaign plan is available"):
        narrator_tools.get_next_session_briefing()
