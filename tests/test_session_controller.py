import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from marvel_mcp_narrator.core.character_state import character_roster
from marvel_mcp_narrator.core.memory.campaign_db import CampaignDatabase
from marvel_mcp_narrator.core.session_controller import GameSessionController


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
            ["session-6", "session-5", "session-4", "session-3", "session-2"],
        )


if __name__ == "__main__":
    unittest.main()
