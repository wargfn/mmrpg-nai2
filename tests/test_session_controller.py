import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from marvel_mcp_narrator.core.character_state import CharacterRoster, character_roster
from marvel_mcp_narrator.core.memory.campaign_db import CampaignDatabase
from marvel_mcp_narrator.core.session_controller import (
    RECENT_MEMORY_LIMIT,
    GameSessionController,
    SessionHistoryManager,
)


class GameSessionControllerTests(unittest.TestCase):
    def setUp(self):
        character_roster.clear()
        self._tmpdir = TemporaryDirectory()
        self.database = CampaignDatabase(Path(self._tmpdir.name) / "campaign.db")
        self.controller = GameSessionController(campaign_database=self.database)

    def tearDown(self):
        character_roster.clear()
        self.controller.clear_combat_state()
        self._tmpdir.cleanup()

    @patch("marvel_mcp_narrator.core.session_controller.resolve_d616_roll")
    def test_roll_action_wraps_resolve_d616_roll(self, mock_roll):
        mock_roll.return_value = {"total_score": 14}

        payload = self.controller.roll_action(ability_modifier=3, edges=2, troubles=1, target_number=12)

        self.assertEqual(payload, {"total_score": 14})
        mock_roll.assert_called_once_with(ability_modifier=3, edges=2, troubles=1, target_number=12)

    def test_look_up_rule_uses_loaded_rules_database(self):
        payload = self.controller.look_up_rule("edge")

        self.assertIn("Rulebook Search Results", payload)
        self.assertIn("Edges and Troubles", payload)

    def test_apply_combat_damage_updates_tracked_health_pool(self):
        character_roster.create_or_load(
            name="Hydra Agent",
            archetype="Striker",
            rank=2,
            melee=4,
            agility=2,
            resilience=3,
            vigilance=2,
            ego=1,
            logic=1,
        )
        self.controller.combat_tracker.track_combatant("Hydra Agent", side="enemy")

        payload = self.controller.apply_combat_damage("Hydra Agent", rank=3, marvel_die_value=4)

        self.assertEqual(payload["damage"]["total_damage"], 12)
        self.assertEqual(payload["target"]["side"], "enemy")
        self.assertEqual(payload["target"]["current_health"], 63)
        self.assertEqual(payload["applied"]["health"]["damage"], 12)

    def test_apply_combat_damage_rejects_invalid_rank(self):
        with self.assertRaisesRegex(ValueError, "Rank must be a positive integer"):
            self.controller.apply_combat_damage("Hydra Agent", rank=0, marvel_die_value=4)

    def test_apply_combat_damage_rejects_invalid_marvel_die_value(self):
        with self.assertRaisesRegex(ValueError, "Marvel die value must be between 1 and 6"):
            self.controller.apply_combat_damage("Hydra Agent", rank=3, marvel_die_value=7)

    def test_apply_combat_damage_rejects_non_integer_inputs(self):
        with self.assertRaisesRegex(ValueError, "Rank must be a positive integer"):
            self.controller.apply_combat_damage("Hydra Agent", rank=1.5, marvel_die_value=4)
        with self.assertRaisesRegex(ValueError, "Marvel die value must be an integer between 1 and 6"):
            self.controller.apply_combat_damage("Hydra Agent", rank=3, marvel_die_value=4.5)

    def test_apply_combat_damage_rejects_tracked_player_target(self):
        character_roster.create_or_load(
            name="Captain America",
            archetype="Protector",
            rank=4,
            melee=5,
            agility=3,
            resilience=4,
            vigilance=4,
            ego=4,
            logic=3,
        )
        self.controller.combat_tracker.track_combatant("Captain America", side="player")

        with self.assertRaisesRegex(ValueError, "tracked enemy or NPC combatants"):
            self.controller.apply_combat_damage("Captain America", rank=4, marvel_die_value=3)

    def test_get_session_status_returns_combatants_health_pools_and_memories(self):
        character_roster.create_or_load(
            name="Hydra Agent",
            archetype="Striker",
            rank=2,
            melee=4,
            agility=2,
            resilience=3,
            vigilance=2,
            ego=1,
            logic=1,
        )
        self.controller.combat_tracker.track_combatant("Hydra Agent", side="npc")
        self.database.save_memory("session-1", "Hydra breached the hangar.")
        self.database.save_memory("session-2", "Captain Marvel arrived.")

        payload = self.controller.get_session_status()

        self.assertEqual(payload["combatants"][0]["name"], "Hydra Agent")
        self.assertEqual(payload["health_pools"]["Hydra Agent"]["health"]["current"], 75)
        self.assertEqual(
            [memory["key"] for memory in payload["recent_campaign_memories"]],
            ["session-2", "session-1"],
        )
        self.assertIsNone(payload["campaign_context"])

    def test_get_session_status_limits_recent_memories_to_latest_five(self):
        for index in range(7):
            self.database.save_memory(f"session-{index}", f"Event {index}")

        payload = self.controller.get_session_status()

        self.assertEqual(
            [memory["key"] for memory in payload["recent_campaign_memories"]],
            [f"session-{index}" for index in range(6, 6 - RECENT_MEMORY_LIMIT, -1)],
        )

    def test_get_session_status_includes_active_campaign_context(self):
        self.database.create_campaign_plan(
            theme="Hydra Uprising",
            villain="Red Skull",
            hero_team=["Captain America", "Black Widow"],
            sessions=[
                {
                    "session_number": 1,
                    "title": "The Helicarrier Falls",
                    "objectives": ["Protect civilians"],
                    "key_npcs": ["Maria Hill"],
                    "locations": ["Helicarrier"],
                    "completion_milestone": "Secure the bridge",
                }
            ],
        )

        payload = self.controller.get_session_status()

        self.assertIsNotNone(payload["campaign_context"])
        self.assertEqual(payload["campaign_context"]["theme"], "Hydra Uprising")
        self.assertEqual(payload["campaign_context"]["active_session_number"], 1)
        self.assertEqual(payload["campaign_context"]["session"]["title"], "The Helicarrier Falls")

    def test_get_session_status_includes_previous_campaign_events_summary(self):
        self.controller.save_previous_campaign_events_summary("Spider-Man stopped the reactor meltdown.")

        payload = self.controller.get_session_status()

        self.assertEqual(payload["previous_campaign_events_summary"], "Spider-Man stopped the reactor meltdown.")

    def test_list_campaign_memories_rejects_negative_limit(self):
        with self.assertRaisesRegex(ValueError, "Memory limit must be a non-negative integer"):
            self.controller.list_campaign_memories(limit=-1)
        with self.assertRaisesRegex(ValueError, "Memory limit must be a non-negative integer"):
            self.controller.list_campaign_memories(limit=1.5)

    def test_controllers_can_isolate_character_rosters(self):
        first_roster = CharacterRoster()
        second_roster = CharacterRoster()
        first_controller = GameSessionController(campaign_database=self.database, character_roster_store=first_roster)
        second_controller = GameSessionController(campaign_database=self.database, character_roster_store=second_roster)

        first_roster.create_or_load(
            name="Storm",
            archetype="Blaster",
            rank=4,
            melee=2,
            agility=4,
            resilience=3,
            vigilance=5,
            ego=5,
            logic=3,
        )

        with self.assertRaisesRegex(KeyError, "Character 'Storm' was not found"):
            second_controller.character_roster.get_sheet("Storm")

    def test_session_history_manager_summarizes_pruned_messages_every_interval(self):
        history_manager = SessionHistoryManager(
            session_controller=self.controller,
            system_prompt_builder=lambda: "system context",
            max_history_turns=2,
            summarization_interval=2,
        )
        history_manager.append_message("user", "We entered the base.")
        history_manager.append_message("assistant", "The guards spotted you.")
        history_manager.complete_turn()
        history_manager.append_message("user", "We dive for cover.")
        history_manager.append_message("assistant", "Blaster fire scorches the walls.")

        history_manager.complete_turn(lambda existing, pruned: f"{existing} Summary: {pruned[0]['content']}".strip())

        self.assertEqual(self.controller.get_previous_campaign_events_summary(), "Summary: We entered the base.")
        self.assertEqual(
            [message["content"] for message in history_manager.history[1:]],
            ["We dive for cover.", "Blaster fire scorches the walls."],
        )

    def test_build_context_injection_returns_prompt_specific_reference_blocks(self):
        data_dir = Path(self._tmpdir.name) / "data"
        notebook_dir = data_dir / "notebooks"
        data_dir.mkdir()
        notebook_dir.mkdir(parents=True)
        (data_dir / "rules.json").write_text(
            '{"mechanics":{"edge":{"description":"Keep the best die."}}}',
            encoding="utf-8",
        )
        (notebook_dir / "medbay.md").write_text("Hydra medbay antidote protocol.", encoding="utf-8")
        self.controller.context_injector.data_directory = data_dir
        self.controller.context_injector.notebook_directory = notebook_dir
        self.controller.character_roster.create_or_load(
            name="Spider-Man",
            archetype="Striker",
            rank=4,
            melee=4,
            agility=6,
            resilience=3,
            vigilance=4,
            ego=3,
            logic=4,
        )
        self.database.save_previous_campaign_events_summary("Spider-Man escaped the Hydra lab.")

        payload = self.controller.build_context_injection("Should Spider-Man use edge at the Hydra medbay?")

        self.assertIn("Relevant Character Sheets:", payload)
        self.assertIn("Relevant Rules Data:", payload)
        self.assertIn("Relevant Campaign Context:", payload)
        self.assertIn("Relevant Notebook Sources:", payload)

    def test_session_history_manager_inserts_injected_context_before_recent_turns(self):
        self.controller.save_previous_campaign_events_summary("Hydra is regrouping.")
        history_manager = SessionHistoryManager(
            session_controller=self.controller,
            system_prompt_builder=lambda: "system context",
        )
        history_manager.append_message("user", "Tell me about Hydra.")

        with patch.object(self.controller, "build_context_injection", return_value="Relevant Campaign Context:\n- Hydra is regrouping."):
            messages = history_manager.build_request_messages("Tell me about Hydra.")

        self.assertEqual(messages[0], {"role": "system", "content": "system context"})
        self.assertEqual(messages[1]["role"], "system")
        self.assertIn("Hydra is regrouping", messages[1]["content"])
        self.assertEqual(messages[2]["role"], "user")


if __name__ == "__main__":
    unittest.main()
